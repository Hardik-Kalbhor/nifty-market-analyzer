"""
debate/model_heal.py — In-process Gemini model self-healer.

Called automatically when _gemini_call() exhausts all configured models.
  1. Quick-fetches available flash models from the API
  2. Parallel-tests top candidates with a 6s timeout
  3. Updates debate.constants._GEMINI_MODELS in-memory (heals the running process)
  4. Also patches the 3 config files on disk for persistence across restarts
  5. Returns the new model list so the caller can retry immediately

Thread-safe: uses a module-level lock + cooldown so multiple concurrent
Gunicorn threads don't trigger redundant heal storms.
"""

import json
import logging
import re
import requests
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Cooldown guard ─────────────────────────────────────────────────────────────
_heal_lock      = threading.Lock()
_last_heal_time = 0.0
_HEAL_COOLDOWN  = 300  # seconds — don't re-heal more than once every 5 min

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE = Path(__file__).parent.parent
_CONFIG_FILES = [
    _BASE / "debate"        / "constants.py",
    _BASE / "subagents"     / "constants.py",
    _BASE / "institutional" / "agent.py",
]

_LIST_URL = "https://generativelanguage.googleapis.com/v1beta/models?key={key}"
_GEN_URL  = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# Minimal JSON probe — must return a valid NIFTY judge structure
_PROBE_PAYLOAD_TEMPLATE = {
    "contents": [{
        "role": "user",
        "parts": [{"text": (
            'You are a JSON-only responder. Reply ONLY with valid JSON:\n'
            '{"structure": "SCALP_PULLBACKS_ONLY", "confidence_adjustment": 0, '
            '"judge_rationale": "heal-probe ok"}\n\n'
            "Return the exact JSON above."
        )}]
    }],
    "generationConfig": {"response_mime_type": "application/json"},
}

_VALID_STRUCTURES = {
    "TREND_BUY_CALLS", "TREND_BUY_PUTS", "RANGE_OPTION_SELLING",
    "SCALP_DIPS_ONLY", "SCALP_PULLBACKS_ONLY", "STRICT_WAIT_AND_WATCH"
}

# Image / audio / non-text suffixes to skip
_SKIP_SUFFIXES = ("-image", "-tts", "-preview-tts", "-lite-image", "-omni")


def _fetch_available_models(gemini_key: str) -> list[str]:
    """List all flash models that support generateContent (text-capable only)."""
    try:
        r = requests.get(_LIST_URL.format(key=gemini_key), timeout=8)
        r.raise_for_status()
        models = r.json().get("models", [])
        return sorted([
            m["name"].replace("models/", "")
            for m in models
            if "flash" in m["name"].lower()
            and "generateContent" in m.get("supportedGenerationMethods", [])
            and not any(m["name"].replace("models/", "").endswith(s) for s in _SKIP_SUFFIXES)
        ])
    except Exception as e:
        logger.warning(f"[ModelHeal] Could not fetch model list: {e}")
        return []


def _probe_model(model: str, gemini_key: str, timeout: int = 6) -> Optional[float]:
    """
    Fire a probe against one model.
    Returns latency (float) if PASS, None if fail.
    """
    try:
        url = _GEN_URL.format(model=model, key=gemini_key)
        t0  = time.time()
        r   = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json=_PROBE_PAYLOAD_TEMPLATE,
            timeout=timeout,
        )
        latency = time.time() - t0
        if r.status_code == 200:
            text      = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            parsed    = json.loads(text)
            structure = parsed.get("structure")
            if structure in _VALID_STRUCTURES:
                return round(latency, 2)
    except Exception:
        pass
    return None


def _model_rank_score(model: str, latency: float) -> float:
    """Lower = better. Prefer lite, newer generation, lower latency. Penalise aliases."""
    ver_match = re.search(r"gemini-(\d+(?:\.\d+)?)", model)
    version   = float(ver_match.group(1)) if ver_match else 0.0
    is_lite   = "lite" in model
    is_alias  = "latest" in model   # hot-swap aliases — unreliable, penalise
    score     = latency
    score    -= version * 2
    score    -= 5 if is_lite else 0
    score    += 15 if is_alias else 0
    return score


def _patch_config_files(new_models: list[str]) -> list[str]:
    """Replace _GEMINI_MODELS = [...] in all 3 config files. Returns patched filenames."""
    pattern   = re.compile(r'(_GEMINI_MODELS\s*=\s*)\[[^\]]+\]')
    new_value = "[" + ", ".join(f'"{m}"' for m in new_models) + "]"
    patched   = []
    for fp in _CONFIG_FILES:
        if not fp.exists():
            continue
        text     = fp.read_text()
        new_text = pattern.sub(lambda _: f"_GEMINI_MODELS = {new_value}", text)
        if new_text != text:
            fp.write_text(new_text)
            patched.append(fp.name)
    return patched


def _update_in_memory(new_models: list[str]) -> None:
    """
    Mutate debate.constants._GEMINI_MODELS in-place so the running process
    uses the new list immediately without a restart.
    Also updates institutional.agent._GEMINI_MODELS if present.
    """
    import sys
    for mod_name in ("debate.constants", "institutional.agent", "subagents.constants"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_GEMINI_MODELS"):
            mod._GEMINI_MODELS.clear()
            mod._GEMINI_MODELS.extend(new_models)
            logger.info(f"[ModelHeal] Updated {mod_name}._GEMINI_MODELS in-memory → {new_models}")


def heal_gemini_models(gemini_key: str, select: int = 3) -> list[str]:
    """
    Entry point: called when _gemini_call() fails all configured models.

    - Thread-safe with a 5-minute cooldown.
    - Tests all available flash models in parallel (max 8 threads, 6s timeout each).
    - Selects `select` best models, updates in-memory + disk.
    - Returns the new model list (empty list if heal failed).
    """
    global _last_heal_time

    with _heal_lock:
        now = time.time()
        if now - _last_heal_time < _HEAL_COOLDOWN:
            remaining = int(_HEAL_COOLDOWN - (now - _last_heal_time))
            logger.info(f"[ModelHeal] Cooldown active — skipping heal ({remaining}s remaining)")
            return []

        logger.warning("[ModelHeal] ⚡ All Gemini models failed — triggering in-process self-heal...")
        t_start = time.time()

        available = _fetch_available_models(gemini_key)
        if not available:
            logger.error("[ModelHeal] Could not fetch model list — giving up")
            return []

        logger.info(f"[ModelHeal] Probing {len(available)} models in parallel...")

        passing: dict[str, float] = {}  # model → latency
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(_probe_model, m, gemini_key): m for m in available}
            for fut in as_completed(futures, timeout=20):
                model   = futures[fut]
                latency = fut.result()
                if latency is not None:
                    passing[model] = latency
                    logger.info(f"[ModelHeal]   ✅ {model} @ {latency}s")
                else:
                    logger.debug(f"[ModelHeal]   ❌ {model} failed probe")

        if not passing:
            logger.error("[ModelHeal] No models passed probe — cannot self-heal")
            return []

        # Rank and select top models
        ranked     = sorted(passing, key=lambda m: _model_rank_score(m, passing[m]))
        new_models = ranked[:select]

        elapsed = round(time.time() - t_start, 1)
        logger.warning(
            f"[ModelHeal] ✅ Self-healed in {elapsed}s — new list: {new_models}"
        )

        # Update in-memory first (instant effect for this and future requests)
        _update_in_memory(new_models)

        # Patch config files (persists across restarts)
        patched = _patch_config_files(new_models)
        if patched:
            logger.info(f"[ModelHeal] Patched disk files: {patched}")

        _last_heal_time = time.time()
        return new_models

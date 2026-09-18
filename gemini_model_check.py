#!/usr/bin/env python3
"""
gemini_model_check.py — Weekly Gemini API self-healing model check.

Steps:
  1. List all available generateContent flash models from the API
  2. Live-test each currently configured model
  3. If ANY configured model fails → test ALL available models, rank by latency
  4. Auto-select best 3 (fastest lite primary, lite backup, full fallback)
  5. Patch _GEMINI_MODELS in-place across all 3 config files
  6. Write JSON report to history/gemini_model_health.json

Run:
  ./venv/bin/python gemini_model_check.py
"""

import json, os, re, sys, time, requests
from datetime import datetime
from pathlib import Path

BASE_DIR    = Path(__file__).parent
REPORT_PATH = BASE_DIR / "history" / "gemini_model_health.json"
GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "").strip()
LIST_URL    = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}"
GEN_URL     = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# Files that contain _GEMINI_MODELS = [...]
CONFIG_FILES = [
    BASE_DIR / "debate"     / "constants.py",
    BASE_DIR / "subagents"  / "constants.py",
    BASE_DIR / "institutional" / "agent.py",
]

# Models currently configured (read dynamically from constants.py)
def _read_configured_models() -> list:
    path = BASE_DIR / "debate" / "constants.py"
    text = path.read_text()
    m = re.search(r'_GEMINI_MODELS\s*=\s*\[([^\]]+)\]', text)
    if not m:
        return []
    return [s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip().strip('"').strip("'")]

# Minimal judge-style prompt — tests JSON mode + NIFTY schema
TEST_SYSTEM = (
    "You are a JSON-only responder. Reply ONLY with valid JSON, no markdown fences:\n"
    '{"structure": "SCALP_PULLBACKS_ONLY", "confidence_adjustment": 0, "judge_rationale": "test ok"}'
)
TEST_USER = "Synthesize committee: return the exact JSON from your system prompt."

VALID_STRUCTURES = {
    "TREND_BUY_CALLS", "TREND_BUY_PUTS", "RANGE_OPTION_SELLING",
    "SCALP_DIPS_ONLY", "SCALP_PULLBACKS_ONLY", "STRICT_WAIT_AND_WATCH"
}

# Scoring weights: prefer lite, newer generation, lower latency
# Higher score = better candidate for primary slot
PREFERENCE_ORDER = [
    "flash-lite",   # prefer lite (fastest, cheapest)
    "flash",        # full flash as fallback
]

DIVIDER = "=" * 68
SEP     = "-" * 68


def list_available_flash_models() -> list:
    """Return all flash models supporting generateContent, excluding non-text ones."""
    EXCLUDE_SUFFIXES = ("-image", "-tts", "-preview-tts", "-lite-image", "-omni")
    try:
        r = requests.get(LIST_URL, timeout=10)
        r.raise_for_status()
        models = r.json().get("models", [])
        return sorted([
            m["name"].replace("models/", "")
            for m in models
            if "flash" in m["name"].lower()
            and "generateContent" in m.get("supportedGenerationMethods", [])
            and not any(m["name"].replace("models/", "").endswith(s) for s in EXCLUDE_SUFFIXES)
        ])
    except Exception as e:
        print(f"  ⚠️  Could not list models: {e}")
        return []


def live_test_model(model: str, timeout: int = 14) -> dict:
    """Fire a real generateContent call. Returns status dict."""
    t0 = time.time()
    try:
        url = GEN_URL.format(model=model, key=GEMINI_KEY)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": TEST_SYSTEM + "\n\n" + TEST_USER}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        r = requests.post(url, headers={"Content-Type": "application/json"},
                          json=payload, timeout=timeout)
        latency = round(time.time() - t0, 2)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            structure = parsed.get("structure")
            ok = structure in VALID_STRUCTURES
            return {"status": "PASS" if ok else "WRONG_OUTPUT", "latency_s": latency,
                    "structure": structure, "error": None}
        else:
            return {"status": f"HTTP_{r.status_code}", "latency_s": latency,
                    "structure": None, "error": r.text[:300]}
    except Exception as e:
        return {"status": "ERROR", "latency_s": round(time.time() - t0, 2),
                "structure": None, "error": str(e)}


def is_passing(res: dict) -> bool:
    return res["status"] == "PASS"


def is_fatal(res: dict) -> bool:
    """429 is quota — not a permanent failure. 503 and 404 are fatal."""
    s = res["status"]
    return "404" in s or "503" in s or s == "ERROR" or s == "WRONG_OUTPUT"


def status_icon(res: dict) -> str:
    s = res["status"]
    if s == "PASS":          return "✅"
    if "429" in s:           return "⚠️ "  # quota — model itself is fine
    if "503" in s:           return "🔴"   # overloaded
    if "404" in s:           return "🚫"   # removed
    if s == "WRONG_OUTPUT":  return "⚠️ "
    return "❌"


def _model_score(model: str, latency: float) -> float:
    """
    Lower score = better rank.
    Prefer lite > full. Prefer higher version. Penalise latency.
    """
    # Extract numeric version if present (e.g. 3.1, 2.5)
    ver_match = re.search(r"gemini-(\d+(?:\.\d+)?)", model)
    version = float(ver_match.group(1)) if ver_match else 0.0

    is_lite = "lite" in model
    is_latest_alias = "latest" in model  # avoid aliases — they hot-swap

    score = latency                      # latency in seconds (lower = better)
    score -= version * 2                 # prefer newer generation
    score -= 5 if is_lite else 0         # prefer lite
    score += 10 if is_latest_alias else 0  # penalise hot-swap aliases
    return score


def select_best_models(passing_results: dict, count: int = 3) -> list:
    """
    From a dict of {model: result} where result["status"] == "PASS",
    return the top `count` models ranked by score (lower = better).
    Tries to keep variety: at least one lite, one full.
    """
    ranked = sorted(
        passing_results.items(),
        key=lambda x: _model_score(x[0], x[1]["latency_s"])
    )
    return [m for m, _ in ranked[:count]]


def patch_config_files(new_models: list) -> list:
    """
    Replace _GEMINI_MODELS = [...] in all 3 config files.
    Returns list of patched file paths.
    """
    pattern = re.compile(r'(_GEMINI_MODELS\s*=\s*)\[[^\]]+\]')
    new_value = "[" + ", ".join(f'"{m}"' for m in new_models) + "]"
    patched = []
    for fp in CONFIG_FILES:
        if not fp.exists():
            print(f"  ⚠️  {fp} not found — skipping")
            continue
        text = fp.read_text()
        new_text, n = pattern.subn(lambda _: f"_GEMINI_MODELS = {new_value}", text)
        if n > 0:
            fp.write_text(new_text)
            patched.append(str(fp.relative_to(BASE_DIR)))
        else:
            print(f"  ⚠️  Could not find _GEMINI_MODELS pattern in {fp.name}")
    return patched


def main():
    if not GEMINI_KEY:
        print("❌  GEMINI_API_KEY not set in environment.")
        sys.exit(1)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"\n{DIVIDER}")
    print(f"  🔍 GEMINI API WEEKLY MODEL HEALTH CHECK  (self-healing)")
    print(f"  📅 {now}")
    print(f"{DIVIDER}\n")

    # ── Step 1: Read current config ───────────────────────────────────────────
    configured = _read_configured_models()
    print(f"  📌 Currently configured models:\n")
    for m in configured:
        print(f"    • {m}")

    # ── Step 2: List available models ─────────────────────────────────────────
    print(f"\n{SEP}")
    print("  📋 Step 2: Fetching available text flash models from API...")
    available = list_available_flash_models()
    print(f"  Found {len(available)} text flash models:\n")
    for m in available:
        tag = " ← configured" if m in configured else ""
        print(f"    • {m}{tag}")

    # ── Step 3: Live-test configured models ───────────────────────────────────
    print(f"\n{SEP}")
    print("  ⚡ Step 3: Live-testing configured models...")
    print(f"{SEP}\n")

    configured_results = {}
    for model in configured:
        print(f"  Testing {model}...", end=" ", flush=True)
        res = live_test_model(model)
        configured_results[model] = res
        icon   = status_icon(res)
        detail = f"structure={res['structure']!r}" if is_passing(res) else (res["error"] or "")[:80]
        print(f"{icon} {res['status']} [{res['latency_s']}s]  {detail}")

    # Determine if any are fatally broken (429 = quota, not fatal)
    fatal_models   = [m for m, r in configured_results.items() if is_fatal(r)]
    quota_models   = [m for m, r in configured_results.items() if "429" in r["status"]]
    passing_models = [m for m, r in configured_results.items() if is_passing(r)]

    action_needed = len(fatal_models) > 0

    # ── Step 4: Self-heal if needed ───────────────────────────────────────────
    new_selection  = None
    all_tested     = {}

    if action_needed:
        print(f"\n{SEP}")
        print(f"  🚨 {len(fatal_models)} fatal failure(s) detected — running full model scan...")
        print(f"{SEP}\n")

        # Test all available text models (skip image/tts)
        for model in available:
            if model in configured_results:
                # Reuse already-tested result
                all_tested[model] = configured_results[model]
                continue
            print(f"  Testing {model}...", end=" ", flush=True)
            res = live_test_model(model)
            all_tested[model] = res
            icon   = status_icon(res)
            detail = f"structure={res['structure']!r}" if is_passing(res) else (res["error"] or "")[:80]
            print(f"{icon} {res['status']} [{res['latency_s']}s]  {detail}")

        # Select best 3 from all passing
        all_passing = {m: r for m, r in all_tested.items() if is_passing(r)}
        if len(all_passing) < 1:
            print("\n  ❌ No models passed! Cannot auto-heal. Check your API key quota.")
        else:
            new_selection = select_best_models(all_passing, count=3)
            print(f"\n{SEP}")
            print("  🏆 Best models selected (ranked by lite preference + latency):")
            print(f"{SEP}\n")
            for rank, model in enumerate(new_selection, 1):
                r = all_passing[model]
                role = "PRIMARY" if rank == 1 else ("BACKUP" if rank == 2 else "LAST RESORT")
                print(f"    #{rank} [{role}]  {model}  @ {r['latency_s']}s")

            # Patch files
            print(f"\n{SEP}")
            print("  ✏️  Auto-patching config files...")
            print(f"{SEP}\n")
            patched = patch_config_files(new_selection)
            for fp in patched:
                print(f"    ✅ Updated: {fp}")

            print(f"\n  ⚠️  ACTION: Commit and push these changes to Render:")
            print(f"    git add {' '.join(patched)}")
            print(f"    git commit -m \"fix(judge): auto-heal Gemini model list [{now}]\"")
            print(f"    git push origin main")

    elif quota_models:
        print(f"\n  ℹ️  {len(quota_models)} model(s) hit quota (429) — model itself is healthy, just rate-limited.")
        print(f"     No config change needed.")

    # ── Step 5: Summary ───────────────────────────────────────────────────────
    print(f"\n{DIVIDER}")
    print("  💡 Summary")
    print(f"{DIVIDER}\n")

    if not action_needed and not quota_models:
        print("  ✅ All configured models are healthy. No action needed.")
    elif not action_needed and quota_models:
        print("  ✅ Models healthy — quota warnings only (not config failures).")
    elif new_selection:
        print(f"  🔧 Config auto-healed.")
        print(f"  New _GEMINI_MODELS: {new_selection}")
    else:
        print("  ❌ Could not auto-heal — no passing models found.")

    if passing_models:
        fastest = min(passing_models, key=lambda m: configured_results[m]["latency_s"])
        print(f"  ⚡ Fastest configured model: {fastest} @ {configured_results[fastest]['latency_s']}s")

    # ── Step 6: Write JSON report ─────────────────────────────────────────────
    report = {
        "checked_at":            now,
        "available_flash_models": available,
        "configured_models":     configured,
        "configured_test_results": configured_results,
        "fatal_models":          fatal_models,
        "quota_limited_models":  quota_models,
        "action_needed":         action_needed,
        "new_selection":         new_selection,
        "all_tested":            all_tested if action_needed else {},
        "all_passing":           len(fatal_models) == 0,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  📄 Report → {REPORT_PATH}")
    print(f"\n{DIVIDER}\n")

    sys.exit(1 if (action_needed and not new_selection) else 0)


if __name__ == "__main__":
    main()

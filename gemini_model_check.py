#!/usr/bin/env python3
"""
gemini_model_check.py — Weekly Gemini API health check.

Checks:
  1. Lists all available generateContent models from the API
  2. Live-tests each configured model (debate + institutional + subagents)
  3. Detects newly available, degraded, or removed models
  4. Prints a ranked recommendation if a faster/better model is available
  5. Writes a JSON report to history/gemini_model_health.json

Run:
  ./venv/bin/python gemini_model_check.py
"""

import json, os, sys, time, requests
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

BASE_DIR    = Path(__file__).parent
REPORT_PATH = BASE_DIR / "history" / "gemini_model_health.json"
GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "").strip()
LIST_URL    = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}"
GEN_URL     = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

CONFIGURED_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
]

TEST_SYSTEM = (
    "You are a JSON-only responder. Reply ONLY with valid JSON, no markdown:\n"
    '{"structure": "SCALP_PULLBACKS_ONLY", "confidence_adjustment": 0, "judge_rationale": "test ok"}'
)
TEST_USER = "Test: return the exact JSON from your system prompt."

VALID_STRUCTURES = {
    "TREND_BUY_CALLS", "TREND_BUY_PUTS", "RANGE_OPTION_SELLING",
    "SCALP_DIPS_ONLY", "SCALP_PULLBACKS_ONLY", "STRICT_WAIT_AND_WATCH"
}

DIVIDER = "=" * 68


def list_available_flash_models() -> list:
    try:
        r = requests.get(LIST_URL, timeout=10)
        r.raise_for_status()
        models = r.json().get("models", [])
        return sorted([
            m["name"].replace("models/", "")
            for m in models
            if "flash" in m["name"].lower()
            and "generateContent" in m.get("supportedGenerationMethods", [])
        ])
    except Exception as e:
        print(f"  ⚠️  Could not list models: {e}")
        return []


def live_test_model(model: str, timeout: int = 12) -> dict:
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
                    "structure": None, "error": r.text[:200]}
    except Exception as e:
        return {"status": "ERROR", "latency_s": round(time.time() - t0, 2),
                "structure": None, "error": str(e)}


def status_icon(status: str) -> str:
    if status == "PASS":           return "✅"
    if "503" in status:            return "🔴"
    if "404" in status:            return "🚫"
    if "429" in status:            return "⚠️ "
    if status == "WRONG_OUTPUT":   return "⚠️ "
    return "❌"


def main():
    if not GEMINI_KEY:
        print("❌ GEMINI_API_KEY not set in environment.")
        sys.exit(1)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"\n{DIVIDER}")
    print(f"  🔍 GEMINI API WEEKLY MODEL HEALTH CHECK")
    print(f"  📅 {now}")
    print(f"{DIVIDER}\n")

    print("  📋 Step 1: Fetching available flash models from API...")
    available = list_available_flash_models()
    print(f"  Found {len(available)} flash models:\n")
    for m in available:
        tag = " ← configured" if m in CONFIGURED_MODELS else ""
        print(f"    • {m}{tag}")

    print(f"\n{DIVIDER}")
    print("  ⚡ Step 2: Live-testing configured models...")
    print(f"{DIVIDER}\n")

    test_results = {}
    for model in CONFIGURED_MODELS:
        print(f"  Testing {model}...", end=" ", flush=True)
        res = live_test_model(model)
        test_results[model] = res
        icon   = status_icon(res["status"])
        detail = f"structure={res['structure']!r}" if res["status"] == "PASS" else (res["error"] or "")[:80]
        print(f"{icon} {res['status']} [{res['latency_s']}s]  {detail}")

    print(f"\n{DIVIDER}")
    print("  🆕 Step 3: Newly available models (not yet configured)")
    print(f"{DIVIDER}\n")
    new_models = [m for m in available if m not in CONFIGURED_MODELS]
    if new_models:
        for m in new_models:
            print(f"  • {m}  ← consider testing as faster/cheaper option")
    else:
        print("  None — configured list matches available models.")

    print(f"\n{DIVIDER}")
    print("  💡 Step 4: Recommendation")
    print(f"{DIVIDER}\n")

    passing = [(m, r) for m, r in test_results.items() if r["status"] == "PASS"]
    failing = [(m, r) for m, r in test_results.items() if r["status"] != "PASS"]

    if failing:
        print(f"  ⚠️  {len(failing)} configured model(s) are FAILING:\n")
        for m, r in failing:
            print(f"    ❌ {m} — {r['status']}: {(r['error'] or '')[:80]}")
        print()
        print("  👉 ACTION REQUIRED: Update _GEMINI_MODELS in:")
        print("       debate/constants.py")
        print("       subagents/constants.py")
        print("       institutional/agent.py")
    else:
        print("  ✅ All configured models are healthy. No action needed.")

    if passing:
        fastest = sorted(passing, key=lambda x: x[1]["latency_s"])[0]
        print(f"  ⚡ Fastest passing model: {fastest[0]} @ {fastest[1]['latency_s']}s")

    report = {
        "checked_at": now,
        "available_flash_models": available,
        "configured_models": CONFIGURED_MODELS,
        "test_results": test_results,
        "new_models_available": new_models,
        "all_passing": len(failing) == 0,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  📄 Report saved → {REPORT_PATH}")
    print(f"\n{DIVIDER}\n")

    sys.exit(1 if failing else 0)


if __name__ == "__main__":
    main()

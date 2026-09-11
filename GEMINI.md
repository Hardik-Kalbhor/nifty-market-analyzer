# Project Rules for NIFTY Market Analyzer (Render Production Readiness)

## Workflow Trigger: "RENDER check codebase is ready for Production grade build for render"

Whenever the user prompts **"RENDER check codebase is ready for Production grade build for render"** (or any close variation), follow this standardized production-readiness audit and deployment workflow:

### Step 1: Render Configuration & Build Spec Audit
- Inspect `render.yaml`, `Procfile`, and `gunicorn.conf.py`.
- Verify:
  - `plan: free`
  - Single-worker multi-threaded Gunicorn: `--workers 1 --threads 4 --worker-class gthread` (strictly required for 512 MB RAM ceiling).
  - Port binding: `0.0.0.0:$PORT` (fallback 10000).
  - WSGI entry point: `server:app` (ensure `server.py` exports `app = routes.app`).
  - Gunicorn timeout: `180s`.
  - Python version: `3.11.8`.

### Step 2: Dependency & Import Parity Check
- Verify `requirements.txt` covers 100% of non-standard-library imports across all `.py` files.
- Verify pre-built Linux x86_64 wheels exist for all dependencies (`numpy`, `lxml`, `Pillow`, `gunicorn`, etc.).
- Check system binaries: note that native Python on Render does not include `tesseract-ocr` CLI, so ensure client-side `Tesseract.js` fallback is intact.

### Step 3: Resource & Memory Ceiling Hardening (512 MB RAM)
- Verify `app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024` (16 MB) in `routes/app.py` to prevent OOM kills on file uploads.
- Verify image downscaling guardrails (max 1920px) in `ocr_extractor.py` prior to 2x Lanczos upscaling.

### Step 4: Git Tracking & Hygiene Audit
- Run `git status`.
- Check for any **untracked or uncommitted files** (especially new modules in `exit/`, `exit_fast/`, `routes/`, `market_signals/`, `test_*.py`).
- Flag any missing files that would cause `ModuleNotFoundError` on a clean `git clone` on Render.

### Step 5: Complete Test Suite Verification
- Run the full test discovery suite: `./venv/bin/python -m unittest discover -s . -p "test_*.py"`.
- Require **100% passing tests** (all 236+ tests). Investigate and fix any failures or regressions immediately.

### Step 6: Demo & Test Data Inspection & Purge
- Before git push, purge all demo / manual test artifacts from `history/`:
  - Delete `analysis_manual_*.json`, `latest.json`, `memory_fts.db`, `memory_log.md`.
  - Delete `exit_sessions.jsonl`, `exit_evaluations.jsonl`, `trajectories_*.jsonl`, `walk_forward_simulation_report.json`.
  - Verify no accidental sub-history folders exist (e.g. `cognigraph/history/`, `wfs/history/`).
  - Verify that UI templates and scripts have no hardcoded demo prices/coordinates and default to clean empty state placeholders (`--`, `Awaiting Analysis`, etc.).

### Step 7: Render Free Tier Caveats Check
- Check & inform user of:
  - **15-Minute Inactivity Sleep**: APScheduler stops running when idle. Recommend external cron ping (e.g. cron-job.org / UptimeRobot) targeting `/api/health` or `/api/trigger-schedule` during market hours.
  - **Ephemeral Filesystem**: Data in `history/` resets on restart/redeploy.

### Step 8: Git Commit & Push (When Requested / All Checks Pass)
- Stage all changes: `git add -A`.
- Commit with a clear conventional commit message.
- Push to `origin main` using `BypassSandbox: true` for network connectivity.
- Verify working tree is 100% clean (`git status`).

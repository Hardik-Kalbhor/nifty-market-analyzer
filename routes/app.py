"""
routes/app.py — Flask application initialization, CORS, base routes, and shared helpers.
"""

import os
import logging
from flask import Flask, render_template

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_DIR, "templates"),
    static_folder=os.path.join(_BASE_DIR, "static"),
)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB guardrail for Render 512MB RAM

# Start AutoScheduler at module load time so it works under both
# `python server.py` (development) and Gunicorn (production on Render).
try:
    from auto_scheduler import init_scheduler
    # Avoid double-starting in Gunicorn pre-fork model by using an env flag
    if not os.environ.get("SCHEDULER_STARTED"):
        os.environ["SCHEDULER_STARTED"] = "1"
        init_scheduler()
except Exception as _sched_err:
    logging.getLogger(__name__).warning(f"AutoScheduler could not start: {_sched_err}")


@app.after_request
def add_cors_headers(response):
    """Add CORS and cache headers for smooth cross-device / mobile browser support."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


def get_history_dir():
    """Return the absolute path to the history directory."""
    import sys
    server_mod = sys.modules.get("server")
    if server_mod and hasattr(server_mod, "get_history_dir") and server_mod.get_history_dir != get_history_dir:
        return server_mod.get_history_dir()
    base_dir = os.path.join(_BASE_DIR, "history")
    try:
        os.makedirs(base_dir, exist_ok=True)
        return base_dir
    except (OSError, PermissionError):
        tmp_dir = "/tmp/history"
        os.makedirs(tmp_dir, exist_ok=True)
        return tmp_dir


@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("index.html")

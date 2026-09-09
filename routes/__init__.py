"""
routes package — Modular Flask application routes.
"""

from .app import app, get_history_dir

# Import all route modules to register endpoints on app
from . import analyze
from . import memory
from . import scheduler
from . import history
from . import advisor

__all__ = ["app", "get_history_dir"]

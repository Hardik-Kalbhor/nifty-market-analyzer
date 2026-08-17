"""
app.py — Entry point wrapper for WSGI servers (Gunicorn, Render, Vercel, etc.)
Imports Flask application instance from server.py.
"""
from server import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)

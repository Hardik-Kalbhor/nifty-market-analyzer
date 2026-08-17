# Gunicorn configuration file
# Automatically discovered and loaded by Gunicorn on startup

bind = "0.0.0.0:10000"
workers = 1
threads = 4
worker_class = "gthread"
timeout = 180
graceful_timeout = 30
keepalive = 5

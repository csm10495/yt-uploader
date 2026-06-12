"""Gunicorn configuration for the YouTube Uploader web app.

IMPORTANT: this app keeps the state of in-progress uploads in an in-memory
dictionary inside a single process. It must therefore run with **exactly one
worker** and use threads for concurrency (the ``gthread`` worker). Running
multiple workers would route a user's status/cancel polls to a different
process that has no knowledge of their upload.

Override any of these via environment variables (e.g. GUNICORN_THREADS).
"""

import os

# Bind to all interfaces inside the container; the reverse proxy terminates TLS.
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# Single worker only (see module docstring). Threads handle concurrency.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "16"))

# Video uploads can take a long time; don't let gunicorn kill the worker
# mid-upload. 0 disables the timeout.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "0"))
graceful_timeout = 30

# Log to stdout/stderr so container log drivers capture everything.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")

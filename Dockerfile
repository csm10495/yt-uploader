# YouTube Uploader web app - production image
#
# Runs the Flask app under gunicorn (a production WSGI server). Intended to
# sit behind a reverse proxy (nginx/Caddy/Traefik) that terminates TLS.
#
# Build:
#   docker build -t yt-uploader-web .
#
# Run (mount client_secrets.json and a volume for per-user tokens):
#   docker run -d --name yt-uploader -p 8000:8000 \
#     -e PUBLIC_BASE_URL=https://uploader.example.com \
#     -e TRUST_PROXY=1 \
#     -v $PWD/client_secrets.json:/app/client_secrets.json:ro \
#     -v yt_uploader_data:/data \
#     yt-uploader-web
#
# The OAuth redirect URI registered in the Google console must match
# "${PUBLIC_BASE_URL}/oauth2callback".

FROM python:3.12-slim

# Don't write .pyc files; flush stdout/stderr immediately for clean logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# tzdata provides the timezone database so a TZ env var (e.g.
# TZ=America/Los_Angeles) makes the container's local time match yours, which
# the scheduled-publish feature relies on for local<->UTC conversion.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first to leverage Docker layer caching.
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Copy the application code.
COPY app.py gunicorn.conf.py ./
COPY templates/ ./templates/
COPY static/ ./static/

# Per-user data (OAuth tokens, signed-cookie secret) lives on a volume so it
# survives container restarts. Default the app to store it under /data.
ENV WEB_DATA_DIR=/data \
    GUNICORN_BIND=0.0.0.0:8000 \
    YT_UPLOADER_OPEN_BROWSER=0
RUN mkdir -p /data

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /data
USER appuser

VOLUME ["/data"]
EXPOSE 8000

# gunicorn.conf.py pins this to a single gthread worker (required: in-memory
# upload state must live in one process).
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]

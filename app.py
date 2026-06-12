#!/usr/bin/env python3
"""
YouTube Video Uploader - Web App

A Flask-based web version of the desktop uploader. Provides the core
upload features of yt_uploader.py: title/description/tags/category,
privacy options (including scheduled publishing), made-for-kids flag,
upload progress with cancel, "next day slot" scheduling, and OAuth2 with
cached credentials.

Multi-user safety
-----------------
Unlike the single-user desktop app, the web app may be used by more than
one person/browser. Each browser session is treated as a distinct user,
identified by a random id stored in a *signed* session cookie. Each
user's OAuth credentials are stored under ``web_data/<uid>/`` so users
can never read each other's tokens. Only non-sensitive, shared data (the
public category list) is cached globally.

Run with:  python app.py   (or use run_uploader_web.bat)
Then open: http://localhost:5000
"""

import os
import re
import json
import time
import uuid
import pickle
import secrets
import threading
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, render_template, request, jsonify, redirect, session, url_for
)
from markupsafe import escape

# Google API imports
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ---------------------------------------------------------------------------
# Configuration (environment-driven so the same app runs locally and in
# production behind a reverse proxy / production WSGI server).
# ---------------------------------------------------------------------------
# Apply the TZ environment variable (e.g. TZ=America/Los_Angeles) to this
# process so local<->UTC conversion for scheduled videos uses the intended
# timezone. tzset() is POSIX-only; on Windows the OS timezone is used.
if hasattr(time, "tzset"):
    time.tzset()

# Host/port the WSGI server binds to. In Docker this is typically 0.0.0.0.
HOST = os.environ.get("YT_UPLOADER_HOST", "localhost")
PORT = int(os.environ.get("YT_UPLOADER_PORT", "5000"))

# The externally reachable base URL (what the user's browser hits). Behind a
# reverse proxy with TLS this is e.g. "https://uploader.example.com". It is
# used to build the OAuth redirect URI that must match the Google console.
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL", f"http://{HOST}:{PORT}"
).rstrip("/")
REDIRECT_URI = os.environ.get(
    "OAUTH_REDIRECT_URI", f"{PUBLIC_BASE_URL}/oauth2callback"
)

# OAuth over plain http is only acceptable for local/dev use. Enable the
# insecure-transport shim automatically when the redirect URI is http, unless
# explicitly overridden via the OAUTHLIB_INSECURE_TRANSPORT env var.
if REDIRECT_URI.lower().startswith("http://"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
# Don't fail if Google grants a superset/different ordering of scopes.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Whether to open a browser window on startup (only useful for local desktop
# use; disabled in containers/production).
OPEN_BROWSER = os.environ.get("YT_UPLOADER_OPEN_BROWSER", "1") == "1"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
CLIENT_SECRETS_FILE = Path(
    os.environ.get("CLIENT_SECRETS_FILE", SCRIPT_DIR / "client_secrets.json")
)
# Non-sensitive, identical for everyone -> safe to cache globally.
CATEGORIES_CACHE_FILE = SCRIPT_DIR / "categories_cache.json"

# Per-user data lives here, keyed by the signed-cookie session id. Point this
# at a mounted volume in production so tokens survive container restarts.
WEB_DATA_DIR = Path(os.environ.get("WEB_DATA_DIR", SCRIPT_DIR / "web_data"))
WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY_FILE = WEB_DATA_DIR / "secret_key"

SCOPES = [
    "https://www.googleapis.com/auth/youtube",            # full access (delete)
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",   # read scheduled videos
]

VIDEO_EXTENSIONS = {
    '.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv',
    '.webm', '.m4v', '.mpeg', '.mpg', '.3gp'
}

DEFAULT_YOUTUBE_CATEGORIES = {
    "Film & Animation": "1",
    "Autos & Vehicles": "2",
    "Music": "10",
    "Pets & Animals": "15",
    "Sports": "17",
    "Travel & Events": "19",
    "Gaming": "20",
    "People & Blogs": "22",
    "Comedy": "23",
    "Entertainment": "24",
    "News & Politics": "25",
    "Howto & Style": "26",
    "Education": "27",
    "Science & Technology": "28",
    "Nonprofits & Activism": "29",
}

# Directory used to stage browser-uploaded files before sending to YouTube.
# Defaults to the system temp dir but can be pointed at a volume-backed path
# (e.g. under WEB_DATA_DIR) so multi-GB uploads don't fill the container's
# writable layer.
UPLOAD_TMP_DIR = Path(
    os.environ.get("UPLOAD_TMP_DIR", Path(tempfile.gettempdir()) / "yt_uploader_web")
)
UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)

# In-memory registry of active/finished uploads, keyed by upload id.
# Each entry also records the owning uid so users can't poll/cancel
# each other's uploads.
UPLOADS = {}
UPLOADS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Per-user storage helpers (multi-user isolation)
# ---------------------------------------------------------------------------
def load_secret_key():
    """Load (or create) a persistent secret key used to sign session cookies.

    Persisting it means users stay logged in across server restarts, and the
    signed cookie cannot be forged to impersonate another user's session id.
    An explicit SECRET_KEY env var takes precedence (useful in production).
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")
    if SECRET_KEY_FILE.exists():
        try:
            return SECRET_KEY_FILE.read_bytes()
        except Exception:
            pass
    key = secrets.token_bytes(32)
    try:
        SECRET_KEY_FILE.write_bytes(key)
    except Exception:
        pass
    return key


# A valid user id is exactly what secrets.token_hex(16) produces: 32 lowercase
# hex chars. Validating it before using it as a path segment is defense in
# depth on top of the signed session cookie (no path traversal via uid).
_UID_RE = re.compile(r"^[0-9a-f]{32}$")


def current_uid():
    """Return the current session's user id, creating one if needed."""
    uid = session.get('uid')
    if not uid or not _UID_RE.match(uid):
        uid = secrets.token_hex(16)
        session['uid'] = uid
        session.permanent = True
    return uid


def user_dir(uid=None, create=False):
    uid = uid or current_uid()
    d = WEB_DATA_DIR / uid
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def user_token_file(uid=None, create=False):
    return user_dir(uid, create=create) / "token.pickle"


# ---------------------------------------------------------------------------
# Categories (global, non-sensitive)
# ---------------------------------------------------------------------------
def get_youtube_categories():
    """Get YouTube categories from cache or return defaults."""
    if CATEGORIES_CACHE_FILE.exists():
        try:
            with open(CATEGORIES_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            fetched_at = datetime.fromisoformat(cache_data["fetched_at"])
            if datetime.now() - fetched_at < timedelta(days=7):
                return cache_data["categories"]
        except Exception:
            pass
    return DEFAULT_YOUTUBE_CATEGORIES.copy()


def categories_cache_is_fresh():
    if not CATEGORIES_CACHE_FILE.exists():
        return False
    try:
        with open(CATEGORIES_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        fetched_at = datetime.fromisoformat(cache_data["fetched_at"])
        return datetime.now() - fetched_at < timedelta(days=7)
    except Exception:
        return False


def fetch_and_cache_categories(youtube_service, region_code="US"):
    """Fetch YouTube categories from API and cache them."""
    try:
        response = youtube_service.videoCategories().list(
            part="snippet", regionCode=region_code
        ).execute()

        categories = {}
        for item in response.get("items", []):
            if item["snippet"].get("assignable", False):
                categories[item["snippet"]["title"]] = item["id"]

        if categories:
            cache_data = {
                "fetched_at": datetime.now().isoformat(),
                "region_code": region_code,
                "categories": categories,
            }
            with open(CATEGORIES_CACHE_FILE, 'w') as f:
                json.dump(cache_data, f, indent=2)
            return categories
    except Exception as e:
        print(f"Failed to fetch categories: {e}")
    return None


# ---------------------------------------------------------------------------
# Authentication (per user)
# ---------------------------------------------------------------------------
def load_credentials(token_file):
    """Load and refresh a user's cached credentials. Returns Credentials or None."""
    token_file = Path(token_file)
    credentials = None
    if token_file.exists():
        try:
            with open(token_file, 'rb') as token:
                credentials = pickle.load(token)
        except Exception:
            credentials = None

    if credentials and getattr(credentials, "scopes", None):
        if not all(scope in credentials.scopes for scope in SCOPES):
            credentials = None
            try:
                token_file.unlink()
            except Exception:
                pass

    if credentials and not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                save_credentials(credentials, token_file)
            except Exception as e:
                print(f"Token refresh failed: {e}")
                credentials = None
                try:
                    token_file.unlink()
                except Exception:
                    pass
        else:
            credentials = None

    return credentials


def save_credentials(credentials, token_file):
    token_file = Path(token_file)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, 'wb') as token:
        pickle.dump(credentials, token)


def get_youtube_service(token_file):
    """Return an authenticated YouTube service, or None if not authenticated."""
    credentials = load_credentials(token_file)
    if not credentials or not credentials.valid:
        return None
    return build('youtube', 'v3', credentials=credentials)


def is_authenticated(token_file):
    return get_youtube_service(token_file) is not None


def get_channel_name(youtube_service):
    """Return the signed-in user's YouTube channel title, or None."""
    try:
        resp = youtube_service.channels().list(
            mine=True, part='snippet'
        ).execute()
        items = resp.get('items', [])
        if items:
            return items[0]['snippet'].get('title')
    except Exception as e:
        print(f"Failed to fetch channel name: {e}")
    return None


# ---------------------------------------------------------------------------
# Scheduling helpers (local <-> UTC)
#
# Conversions use datetime.astimezone(), which resolves the system local
# timezone's UTC offset for the *given* datetime. This correctly accounts for
# daylight-saving time on the scheduled date, even when that date is in a
# different DST period than "now".
# ---------------------------------------------------------------------------
def local_to_iso8601_utc(dt_local):
    """Convert a naive local datetime to the ISO8601 UTC string YouTube wants."""
    # A naive datetime is interpreted as system local time by astimezone().
    utc_dt = dt_local.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def utc_to_local_naive(dt_utc):
    """Convert a naive/UTC datetime to a naive datetime in system local time."""
    return (dt_utc.replace(tzinfo=timezone.utc)
            .astimezone()
            .replace(tzinfo=None))


def parse_local_datetime(date_str, time_str):
    """date_str = 'YYYY-MM-DD', time_str = 'HH:MM' (24h). Returns naive datetime."""
    combined = f"{date_str} {time_str}"
    return datetime.strptime(combined, "%Y-%m-%d %H:%M")


def get_scheduled_videos(youtube_service):
    """Return (scheduled_videos, suggested_next_slot_local) mirroring the desktop logic."""
    channels_response = youtube_service.channels().list(
        mine=True, part='contentDetails'
    ).execute()
    if not channels_response.get('items'):
        return [], None

    uploads_playlist_id = (
        channels_response['items'][0]['contentDetails']
        ['relatedPlaylists']['uploads']
    )

    playlist_response = youtube_service.playlistItems().list(
        playlistId=uploads_playlist_id, part='contentDetails', maxResults=50
    ).execute()
    if not playlist_response.get('items'):
        return [], None

    video_ids = [item['contentDetails']['videoId']
                 for item in playlist_response['items']]

    videos_response = youtube_service.videos().list(
        id=','.join(video_ids), part='status,snippet'
    ).execute()

    scheduled = []
    for video in videos_response.get('items', []):
        publish_at = video.get('status', {}).get('publishAt')
        if not publish_at:
            continue
        clean = publish_at.replace('Z', '+00:00')
        if '.' in clean:
            dt_utc = datetime.fromisoformat(clean.split('.')[0])
        else:
            dt_utc = datetime.fromisoformat(clean.replace('+00:00', ''))
        dt_local = utc_to_local_naive(dt_utc)
        scheduled.append({
            'title': video['snippet']['title'],
            'publishAtUtc': dt_utc,
            'publishAtLocal': dt_local,
        })

    scheduled.sort(key=lambda x: x['publishAtUtc'])
    if scheduled:
        next_slot = scheduled[-1]['publishAtLocal'] + timedelta(days=1)
    else:
        next_slot = None
    return scheduled, next_slot


# ---------------------------------------------------------------------------
# Upload worker
# ---------------------------------------------------------------------------
def _safe_remove(path):
    try:
        os.remove(path)
    except Exception:
        pass


def _find_partial_upload_video_id(youtube_service, title, description, publish_at):
    """Best-effort search for a partially uploaded video to clean up on cancel."""
    try:
        search_response = youtube_service.search().list(
            part='snippet', forMine=True, type='video',
            maxResults=10, order='date'
        ).execute()

        for item in search_response.get('items', []):
            if item['snippet'].get('title', '') != title:
                continue
            video_desc = item['snippet'].get('description', '')
            if description and not video_desc.startswith(description[:100]):
                continue
            video_id = item['id'].get('videoId')
            if publish_at and video_id:
                vr = youtube_service.videos().list(
                    part='status', id=video_id
                ).execute()
                if vr.get('items'):
                    vpa = vr['items'][0].get('status', {}).get('publishAt', '')
                    if publish_at.replace('.000Z', 'Z') != vpa.replace('.000Z', 'Z'):
                        continue
            return video_id
    except Exception as e:
        print(f"Error searching for partial upload: {e}")
    return None


def run_upload(upload_id, body, video_path, publish_at,
               cleanup_temp, token_file):
    """Background worker that uploads a single video to YouTube.

    Runs outside any request context, so the owning user's token file path
    is passed in explicitly rather than read from the session. Upload state
    is tracked in the in-memory UPLOADS registry.

    The whole body is wrapped in try/except/finally so that ANY failure
    (including credential loading) always marks the upload done and removes
    the staged temp file -- otherwise a poller would hang forever and the
    file would leak.
    """
    state = UPLOADS[upload_id]
    try:
        youtube_service = get_youtube_service(token_file)
        if youtube_service is None:
            state['error'] = "Not authenticated"
            state['status'] = 'failed'
            return

        title = body['snippet']['title']
        description = body['snippet'].get('description', '')

        media = MediaFileUpload(
            video_path, chunksize=4 * 1024 * 1024, resumable=True
        )
        request_ = youtube_service.videos().insert(
            part=','.join(body.keys()), body=body, media_body=media
        )

        response = None
        while response is None:
            if state.get('cancel_requested'):
                state['status'] = 'cancelling'
                break
            status, response = request_.next_chunk()
            if status:
                state['progress'] = status.progress() * 100
            if response:
                state['video_id'] = response.get('id')

        # Handle cancellation
        if state.get('cancel_requested'):
            video_id = state.get('video_id') or _find_partial_upload_video_id(
                youtube_service, title, description, publish_at)
            if video_id:
                try:
                    youtube_service.videos().delete(id=video_id).execute()
                    state['status'] = 'cancelled'
                    state['note'] = 'Video deleted from YouTube'
                except Exception as del_error:
                    state['status'] = 'cancelled'
                    state['note'] = (f'Failed to delete video {video_id}: '
                                     f'{del_error}')
            else:
                state['status'] = 'cancelled'
                state['note'] = 'No matching video found on YouTube to delete'
            return

        # Success
        video_id = response['id']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
        state['progress'] = 100
        state['status'] = 'completed'
        state['video_id'] = video_id
        state['video_url'] = video_url
        state['studio_url'] = studio_url

    except Exception as e:
        state['error'] = str(e)
        state['status'] = 'failed'
    finally:
        # Always mark the upload finished and clean up the staged file.
        state['done'] = True
        if cleanup_temp:
            _safe_remove(video_path)


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = load_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Send the session cookie only over HTTPS when served behind TLS.
app.config['SESSION_COOKIE_SECURE'] = PUBLIC_BASE_URL.lower().startswith("https://")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
# Trust X-Forwarded-* headers from one reverse proxy hop so url building and
# the OAuth callback work correctly behind nginx/Caddy/Traefik.
if os.environ.get("TRUST_PROXY", "0") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
# Max request body for uploads (bytes). Defaults to 16 GB.
app.config['MAX_CONTENT_LENGTH'] = int(
    os.environ.get("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024 * 1024))
)


@app.errorhandler(413)
def _too_large(_e):
    """Return JSON (not HTML) when an upload exceeds MAX_CONTENT_LENGTH."""
    limit_gb = app.config['MAX_CONTENT_LENGTH'] / (1024 ** 3)
    return jsonify({
        "error": f"File is too large (limit {limit_gb:.0f} GB)."
    }), 413


def _owned_upload(upload_id):
    """Return the upload state if it belongs to the current user, else None."""
    state = UPLOADS.get(upload_id)
    if state is None or state.get('uid') != current_uid():
        return None
    return state


def _prune_uploads(max_age=6 * 3600, max_entries=200):
    """Drop old finished uploads so the in-memory registry can't grow forever.

    Must be called while holding UPLOADS_LOCK. Finished entries older than
    max_age are removed; if still too many, the oldest finished ones go first.
    """
    now = time.time()
    finished = [(uid, s) for uid, s in UPLOADS.items() if s.get('done')]
    for uid, s in finished:
        if now - s.get('created_at', now) > max_age:
            UPLOADS.pop(uid, None)
    if len(UPLOADS) > max_entries:
        finished = sorted(
            ((uid, s) for uid, s in UPLOADS.items() if s.get('done')),
            key=lambda kv: kv[1].get('created_at', 0),
        )
        for uid, _ in finished[: len(UPLOADS) - max_entries]:
            UPLOADS.pop(uid, None)


@app.route("/")
def index():
    # Establish the session cookie up front so the user id is stable before
    # any API request fires.
    current_uid()
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    """Auth state + signed-in channel + categories. Refreshes category cache when stale."""
    token_file = user_token_file()
    service = get_youtube_service(token_file)
    authed = service is not None
    categories = get_youtube_categories()
    channel_name = None

    if authed:
        channel_name = get_channel_name(service)
        if not categories_cache_is_fresh():
            try:
                fresh = fetch_and_cache_categories(service)
                if fresh:
                    categories = fresh
            except Exception:
                pass

    return jsonify({
        "authenticated": authed,
        "channel_name": channel_name,
        "has_client_secrets": CLIENT_SECRETS_FILE.exists(),
        "categories": categories,
        "default_category": "Entertainment",
        "video_extensions": sorted(VIDEO_EXTENSIONS),
    })


@app.route("/api/auth/login")
def auth_login():
    if not CLIENT_SECRETS_FILE.exists():
        return ("client_secrets.json is missing. See the README for setup "
                "instructions."), 400
    # Bind the session to this user before starting the OAuth dance.
    current_uid()
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        access_type='offline', include_granted_scopes='true', prompt='consent'
    )
    # Map this flow's state -> PKCE code verifier so concurrent logins (e.g.
    # two browser tabs) don't clobber each other. The callback looks up the
    # verifier by the state it receives. Keep only the few most recent.
    pending = session.get('oauth_pending', {})
    pending[state] = flow.code_verifier
    if len(pending) > 5:
        # Drop oldest insertion(s); dict preserves insertion order.
        for old in list(pending)[:-5]:
            pending.pop(old, None)
    session['oauth_pending'] = pending
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    returned_state = request.args.get('state')
    pending = session.get('oauth_pending', {})
    code_verifier = pending.get(returned_state)
    try:
        if code_verifier is None:
            raise ValueError("Unrecognized or expired OAuth state.")
        flow = Flow.from_client_secrets_file(
            str(CLIENT_SECRETS_FILE), scopes=SCOPES,
            state=returned_state, redirect_uri=REDIRECT_URI
        )
        # Restore the PKCE code verifier captured during /api/auth/login.
        flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=request.url)
        # Consume this one-time state; leave any other pending logins intact.
        pending.pop(returned_state, None)
        session['oauth_pending'] = pending
        # Save credentials for THIS user only.
        save_credentials(flow.credentials, user_token_file())
        # Refresh categories now that we're authenticated.
        try:
            fetch_and_cache_categories(
                build('youtube', 'v3', credentials=flow.credentials))
        except Exception:
            pass
    except Exception as e:
        print(f"OAuth callback failed: {e}")
        safe_msg = escape(str(e))
        return (f"<h3>Authentication failed</h3><p>{safe_msg}</p>"
                f"<a href='/'>Back</a>"), 400
    return redirect(url_for('index'))


@app.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    try:
        tf = user_token_file()
        if tf.exists():
            tf.unlink()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


@app.route("/api/categories")
def api_categories():
    return jsonify({"categories": get_youtube_categories()})


@app.route("/api/schedule")
def api_schedule():
    service = get_youtube_service(user_token_file())
    if service is None:
        return jsonify({"error": "Not authenticated"}), 401
    try:
        scheduled, next_slot = get_scheduled_videos(service)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    videos = [{
        "title": v["title"],
        "publishAtLocal": v["publishAtLocal"].strftime("%Y-%m-%dT%H:%M"),
        "display": v["publishAtLocal"].strftime("%a %b %d, %Y @ %I:%M %p"),
    } for v in scheduled]

    next_slot_data = None
    if next_slot is not None:
        next_slot_data = {
            "date": next_slot.strftime("%Y-%m-%d"),
            "time": next_slot.strftime("%H:%M"),
            "display": next_slot.strftime("%a %b %d, %Y @ %I:%M %p"),
            "based_on": scheduled[-1]["title"] if scheduled else None,
        }

    return jsonify({"scheduled": videos, "next_slot": next_slot_data})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    token_file = user_token_file()
    if get_youtube_service(token_file) is None:
        return jsonify({"error": "Not authenticated"}), 401

    form = request.form
    title = (form.get("title") or "").strip()
    description = (form.get("description") or "").strip()
    tags = [t.strip() for t in (form.get("tags") or "").split(",") if t.strip()]
    category_label = form.get("category") or "Entertainment"
    privacy = form.get("privacy") or "private"
    made_for_kids = form.get("madeForKids") == "true"

    # Validation
    if not title:
        return jsonify({"error": "Please enter a title."}), 400
    if len(title) > 100:
        return jsonify({"error": "Title must be 100 characters or less."}), 400

    categories = get_youtube_categories()
    category_id = categories.get(category_label, "24")

    # Resolve the video source. The web app only accepts browser file
    # uploads -- it never reads from the server's filesystem.
    cleanup_temp = False
    if "video" in request.files and request.files["video"].filename:
        f = request.files["video"]
        suffix = Path(f.filename).suffix or ".mp4"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, dir=str(UPLOAD_TMP_DIR))
        os.close(fd)
        try:
            f.save(tmp_path)
        except Exception as e:
            # Don't leave a partial file behind if the transfer fails.
            _safe_remove(tmp_path)
            return jsonify({"error": f"Failed to receive upload: {e}"}), 400
        video_path = tmp_path
        cleanup_temp = True
    else:
        return jsonify({"error": "Please select a video file."}), 400

    file_size = Path(video_path).stat().st_size

    # Scheduling
    publish_at = None
    effective_privacy = privacy
    if privacy == "scheduled":
        date_str = form.get("schedule_date")
        time_str = form.get("schedule_time")
        try:
            dt_local = parse_local_datetime(date_str, time_str)
        except Exception:
            if cleanup_temp:
                _safe_remove(video_path)
            return jsonify({"error": "Invalid schedule date/time."}), 400
        if dt_local <= datetime.now():
            if cleanup_temp:
                _safe_remove(video_path)
            return jsonify({"error": "Scheduled time must be in the future."}), 400
        publish_at = local_to_iso8601_utc(dt_local)
        # Scheduled videos go up as private until publishAt.
        effective_privacy = "private"

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': category_id,
        },
        'status': {
            'privacyStatus': effective_privacy,
            'selfDeclaredMadeForKids': made_for_kids,
        },
    }
    if publish_at:
        body['status']['publishAt'] = publish_at

    upload_id = uuid.uuid4().hex
    with UPLOADS_LOCK:
        _prune_uploads()
        UPLOADS[upload_id] = {
            'uid': current_uid(),
            'progress': 0,
            'status': 'uploading',
            'done': False,
            'cancel_requested': False,
            'error': None,
            'video_id': None,
            'video_url': None,
            'studio_url': None,
            'note': None,
            'file_size': file_size,
            'title': title,
            'privacy': privacy,
            'publish_at': publish_at,
            'created_at': time.time(),
        }

    thread = threading.Thread(
        target=run_upload,
        args=(upload_id, body, video_path, publish_at,
              cleanup_temp, str(token_file)),
        daemon=True,
    )
    thread.start()

    return jsonify({"upload_id": upload_id, "file_size": file_size})


@app.route("/api/upload/<upload_id>/status")
def api_upload_status(upload_id):
    state = _owned_upload(upload_id)
    if state is None:
        return jsonify({"error": "Unknown upload id"}), 404
    return jsonify({
        "progress": state["progress"],
        "status": state["status"],
        "done": state["done"],
        "error": state["error"],
        "video_id": state["video_id"],
        "video_url": state["video_url"],
        "studio_url": state["studio_url"],
        "note": state["note"],
        "file_size": state["file_size"],
        "publish_at": state["publish_at"],
        "privacy": state["privacy"],
    })


@app.route("/api/upload/<upload_id>/cancel", methods=["POST"])
def api_upload_cancel(upload_id):
    state = _owned_upload(upload_id)
    if state is None:
        return jsonify({"error": "Unknown upload id"}), 404
    state['cancel_requested'] = True
    return jsonify({"ok": True})


def main():
    import webbrowser
    url = PUBLIC_BASE_URL
    # Open a browser shortly after the server starts (skip in reloader child
    # and when disabled, e.g. in containers).
    if OPEN_BROWSER and not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"YouTube Uploader web app running at {url}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()

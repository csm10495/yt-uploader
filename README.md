# YouTube Video Uploader

Upload videos to YouTube with either a **desktop GUI** or a **web app**.

- **Desktop app** (`run_uploader.bat`): drag-and-drop a video onto the launcher.
- **Web app** (`run_uploader_web.bat`): runs a local server at <http://localhost:5000> and opens your browser. See [Web App](#web-app) below.

## Features

- 🎬 Drag-and-drop video upload
- 🔒 **Private by default** - videos are never uploaded as public without explicit confirmation
- 📝 Set title, description, tags, and category
- 🔐 OAuth2 authentication with credential caching
- 📊 Upload progress indicator
- 🎯 Self-contained with local virtual environment

## Setup Instructions

### Step 1: Create Google Cloud Project & Enable YouTube API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
3. Name it something like "YouTube Uploader" and click **Create**
4. Wait for the project to be created, then select it
5. In the search bar, search for **"YouTube Data API v3"**
6. Click on **YouTube Data API v3** and click **Enable**

### Step 2: Configure OAuth Consent Screen

1. In the left sidebar, go to **APIs & Services** → **OAuth consent screen**
2. Select **External** user type (unless you have Google Workspace) and click **Create**
3. Fill in the required fields:
   - **App name**: YouTube Uploader (or any name you prefer)
   - **User support email**: Your email
   - **Developer contact email**: Your email
4. Click **Save and Continue**
5. On the **Scopes** page, click **Add or Remove Scopes**
6. Search for `youtube.upload` and check the box for:
   - `https://www.googleapis.com/auth/youtube.upload`
7. Click **Update** and then **Save and Continue**
8. On the **Test users** page, click **Add Users**
9. Add your Google/YouTube email address
10. Click **Save and Continue**, then **Back to Dashboard**

### Step 3: Create OAuth 2.0 Credentials

1. In the left sidebar, go to **APIs & Services** → **Credentials**
2. Click **+ Create Credentials** → **OAuth client ID**
3. Select **Desktop app** as the application type
4. Name it "YouTube Uploader Desktop" (or any name)
5. Click **Create**
6. Click **Download JSON** on the popup that appears
7. **Rename the downloaded file to `client_secrets.json`**
8. **Move `client_secrets.json` to this folder** (same folder as `run_uploader.bat`)

### Step 4: First Run & Authentication

1. Double-click `run_uploader.bat` (or drag a video onto it)
2. The first time, it will:
   - Create a virtual environment
   - Install required packages
   - Open your browser for Google authentication
3. Log in with the Google account you added as a test user
4. Grant permission for the app to upload videos
5. The browser will show "Authentication successful" - you can close it
6. Your credentials are saved in `token.pickle` for future use

## Usage

### Method 1: Drag and Drop
Drag any video file onto `run_uploader.bat`

### Method 2: Run Directly
Double-click `run_uploader.bat` and use the **Browse** button to select a video

### Method 3: Command Line
```batch
run_uploader.bat "C:\path\to\video.mp4"
```

## Web App

The web app provides a browser-based uploader. It uses its own `client_secrets.json` and the shared `categories_cache.json`, and stores each user's OAuth credentials separately (see [Multi-user isolation](#multi-user-isolation)).

### Running it

1. Complete the OAuth setup in **Steps 1–3** above (the same `client_secrets.json` works — a "Desktop app" client supports the localhost redirect the web app uses).
2. Double-click **`run_uploader_web.bat`**. On first run it creates the virtual environment and installs dependencies from `requirements-web.txt`.
3. Your browser opens at <http://localhost:5000>. If it doesn't, open that URL manually.
4. Click **Sign in with Google** the first time to authenticate. Credentials are cached per browser session, so you won't need to sign in again.
5. Press **Ctrl+C** in the console window to stop the server.

### Web app features

- 🎬 Select a video by **drag-and-drop** or **browse**, with an inline video preview
- 📝 Title (with character counter), description, tags, and live category list
- 🔒 Privacy: Private / Unlisted / Public (with confirmation) / **Scheduled**
- 📅 **Calculate Next Day Slot** and **View Schedule** — reads your existing scheduled videos and suggests the next daily slot
- 👶 Made for kids (COPPA) toggle
- 📊 Upload progress with speed and ETA, plus **Cancel** (deletes the partially uploaded video from YouTube)
- 🔐 OAuth2 with cached credentials

> **Note:** The web app is intended to run **locally** on your own machine (the server uploads to YouTube on your behalf). The browser only ever sends the file you explicitly choose — the server never browses its own filesystem. Don't expose the app to the public internet.

### Multi-user isolation

The web app is multi-user safe. Each browser session is treated as a separate user, identified by a random id stored in a **signed session cookie** (signed with a persistent key in `web_data/secret_key`). Per-user data is isolated:

- **Credentials** are stored per user in `web_data/<id>/token.pickle` — one user signing in never authenticates anyone else.
- An upload's progress/cancel endpoints only work for the session that started it.
- The server never reads its own filesystem — only files you explicitly upload from your browser are sent to YouTube.

The `web_data/` directory is git-ignored. Note: the web app's credentials are separate from the desktop app's `token.pickle`, so you sign in to each independently.

## Running with Docker

The web app ships with a production-ready image: it runs under **gunicorn** (a single `gthread` worker — required because in-progress upload state is kept in memory) and is meant to sit behind a TLS-terminating reverse proxy (nginx/Caddy/Traefik) in production.

### How OAuth credentials enter the container

No secrets are baked into the image (`.dockerignore` excludes them, and the `Dockerfile` copies only application code). Credentials are provided at **run time**:

- **`client_secrets.json`** (your Google OAuth client) is **bind-mounted read-only** into the container at `/app/client_secrets.json`.
- **Per-user tokens** are created at runtime when each user signs in via the browser, and are written to `/data/<uid>/token.pickle` on a mounted volume (along with the cookie-signing key at `/data/secret_key`), so they survive restarts.

### Pull from GHCR

Every push to `master` publishes an image to GitHub Container Registry via the included workflow (`.github/workflows/publish.yml`):

```bash
docker pull ghcr.io/csm10495/yt-uploader:latest
```

Images are tagged `latest` and `sha-<commit>`.

### Run via the Docker CLI

Build locally (or use the GHCR image above) and run:

```bash
docker run -d --name yt-uploader -p 8000:8000 \
  -e PUBLIC_BASE_URL=http://localhost:8000 \
  -e TZ=America/Los_Angeles \
  -e UPLOAD_TMP_DIR=/data/uploads \
  -v "$PWD/client_secrets.json:/app/client_secrets.json:ro" \
  -v yt_uploader_data:/data \
  ghcr.io/csm10495/yt-uploader:latest
```

On **Windows cmd**:

```bat
docker run -d --name yt-uploader -p 8000:8000 ^
  -e PUBLIC_BASE_URL=http://localhost:8000 ^
  -e TZ=America/Los_Angeles ^
  -e UPLOAD_TMP_DIR=/data/uploads ^
  -v "%cd%\client_secrets.json:/app/client_secrets.json:ro" ^
  -v yt_uploader_data:/data ^
  ghcr.io/csm10495/yt-uploader:latest
```

Then open the value of `PUBLIC_BASE_URL` in your browser and click **Sign in with Google**.

> The OAuth **redirect URI** registered in the Google console must exactly match `${PUBLIC_BASE_URL}/oauth2callback`. For local use a **Desktop app** OAuth client accepts any `http://localhost:<port>` callback automatically; for a public domain create a **Web application** client and register `https://your-domain/oauth2callback`.

### Run via Docker Compose

```yaml
services:
  yt-uploader:
    image: ghcr.io/csm10495/yt-uploader:latest
    # Or build locally instead of pulling:
    # build: .
    ports:
      - "8000:8000"
    environment:
      # Externally reachable URL; used to build the OAuth redirect URI.
      PUBLIC_BASE_URL: http://localhost:8000
      # Timezone so scheduled-publish times match your local clock.
      TZ: America/Los_Angeles
      # Stage uploads on the volume rather than the container's writable layer.
      UPLOAD_TMP_DIR: /data/uploads
      # Uncomment when running behind an HTTPS reverse proxy:
      # TRUST_PROXY: "1"
    volumes:
      - ./client_secrets.json:/app/client_secrets.json:ro
      - yt_uploader_data:/data
    restart: unless-stopped

volumes:
  yt_uploader_data:
```

Bring it up with `docker compose up -d`.

### Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `PUBLIC_BASE_URL` | `http://localhost:5000` | Externally reachable base URL; builds the OAuth redirect URI and enables secure cookies when `https`. |
| `OAUTH_REDIRECT_URI` | `${PUBLIC_BASE_URL}/oauth2callback` | Override the redirect URI explicitly if needed. |
| `TRUST_PROXY` | `0` | Set to `1` behind a reverse proxy to honor `X-Forwarded-*` headers. |
| `SECRET_KEY` | auto / `web_data/secret_key` | Cookie-signing key; set explicitly to share across replicas. |
| `WEB_DATA_DIR` | `/data` (in image) | Where per-user tokens and the secret key are stored. |
| `UPLOAD_TMP_DIR` | system temp | Where browser uploads are staged before sending to YouTube. |
| `MAX_CONTENT_LENGTH` | `16` GB | Max upload size in bytes. |
| `TZ` | `UTC` | Container timezone (affects scheduled-publish conversion). |

> **Run it behind a reverse proxy / don't expose it directly to the internet.** The server uploads to YouTube on behalf of signed-in users; keep it on a trusted network or behind authentication.

## Supported Video Formats

- MP4, AVI, MOV, MKV, WMV, FLV, WebM, M4V, MPEG, MPG, 3GP

## Privacy Settings

- **Private** (default): Only you can see the video
- **Unlisted**: Anyone with the link can see it, but it won't appear in search
- **Public**: Everyone can find and watch it

⚠️ **Public uploads require explicit confirmation** - you'll be asked to confirm before uploading a public video.

## File Structure

```
yt-uploader/
├── run_uploader.bat      # Desktop launcher (drag videos here)
├── run_uploader_web.bat  # Web app launcher (opens http://localhost:5000)
├── yt_uploader.py        # Desktop GUI upload script
├── app.py                # Web app (Flask) backend
├── templates/            # Web app HTML
├── static/               # Web app CSS/JS
├── requirements.txt      # Desktop dependencies
├── requirements-web.txt  # Web app dependencies
├── Dockerfile            # Production image (gunicorn)
├── gunicorn.conf.py      # gunicorn config (single gthread worker)
├── .dockerignore         # Keeps secrets/venv out of the build context
├── .github/workflows/    # CI: publish image to GHCR on push to master
├── client_secrets.json   # YOUR OAuth credentials (you create this)
├── token.pickle          # Desktop app auth token (auto-created)
├── categories_cache.json # Cached YouTube categories (auto-created, shared)
├── web_data/             # Web app per-user data: OAuth tokens (auto-created)
├── venv/                 # Virtual environment (auto-created)
└── README.md             # This file
```

## Troubleshooting

### "Missing Credentials" Error
Make sure `client_secrets.json` is in the same folder as the script. See Step 3 above.

### "Access blocked" or "App not verified"
This is normal for personal/test apps. Click **Advanced** → **Go to [App Name] (unsafe)** to continue.

### "Quota exceeded"
YouTube API has daily quotas. Wait 24 hours or request a quota increase in Google Cloud Console.

### Authentication Issues
Delete `token.pickle` and run again to re-authenticate.

### "Python not found"
Install Python from [python.org](https://www.python.org/downloads/) and make sure to check "Add Python to PATH" during installation.

## Security Notes

- 🔐 **Never share `client_secrets.json`** - it contains your API credentials
- 🔐 **Never share `token.pickle`** - it contains your authenticated session
- Both files are in `.gitignore` if you version control this folder

## License

MIT License - Feel free to modify and distribute.

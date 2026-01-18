# YouTube Video Uploader

A simple Python script with a GUI to upload videos to YouTube. Drag and drop a video file onto `run_uploader.bat` to launch the uploader.

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
├── run_uploader.bat      # Main launcher (drag videos here)
├── yt_uploader.py        # Python upload script
├── requirements.txt      # Python dependencies
├── client_secrets.json   # YOUR OAuth credentials (you create this)
├── token.pickle          # Saved auth token (auto-created)
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

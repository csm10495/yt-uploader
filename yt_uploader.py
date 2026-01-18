#!/usr/bin/env python3
"""
YouTube Video Uploader
Drag a video file onto this script to upload it to YouTube.
"""

import os
import sys
import json
import pickle
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime, timedelta

# Drag-and-drop support
from tkinterdnd2 import DND_FILES, TkinterDnD

# Video thumbnail support
import cv2
from PIL import Image, ImageTk, ImageDraw

# Google API imports
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Constants
SCRIPT_DIR = Path(__file__).parent.resolve()
CLIENT_SECRETS_FILE = SCRIPT_DIR / "client_secrets.json"
TOKEN_FILE = SCRIPT_DIR / "token.pickle"
CATEGORIES_CACHE_FILE = SCRIPT_DIR / "categories_cache.json"
HISTORY_FILE = SCRIPT_DIR / "upload_history.json"
SCOPES = [
    "https://www.googleapis.com/auth/youtube",  # Full access (needed for delete)
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # For reading scheduled videos
]

# Supported video formats
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg', '.3gp'}

# Fallback YouTube categories (used if API fetch fails)
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


def get_youtube_categories():
    """Get YouTube categories from cache or return defaults."""
    if CATEGORIES_CACHE_FILE.exists():
        try:
            with open(CATEGORIES_CACHE_FILE, 'r') as f:
                cache_data = json.load(f)
            # Check if cache is less than 7 days old
            fetched_at = datetime.fromisoformat(cache_data["fetched_at"])
            if datetime.now() - fetched_at < timedelta(days=7):
                return cache_data["categories"]
        except Exception:
            pass
    return DEFAULT_YOUTUBE_CATEGORIES.copy()


def load_upload_history():
    """Load upload history from file."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_upload_history(history):
    """Save upload history to file."""
    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save history: {e}")


def add_to_history(entry):
    """Add an entry to upload history. Returns the entry's uploaded_at timestamp for later updates."""
    history = load_upload_history()
    # Add timestamp if not present
    if 'uploaded_at' not in entry:
        entry['uploaded_at'] = datetime.now().isoformat()
    # Add to beginning of list (most recent first)
    history.insert(0, entry)
    # Keep only last 100 entries
    history = history[:100]
    save_upload_history(history)
    return entry['uploaded_at']


def update_history_entry(uploaded_at, updates):
    """Update an existing history entry by its uploaded_at timestamp."""
    history = load_upload_history()
    for entry in history:
        if entry.get('uploaded_at') == uploaded_at:
            entry.update(updates)
            save_upload_history(history)
            return True
    return False


def create_app_icon(size=32):
    """Create a YouTube-style app icon programmatically."""
    try:
        # Create a red rounded rectangle with white play triangle
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Red background (rounded rectangle approximation)
        margin = size // 8
        draw.rounded_rectangle(
            [margin, margin, size - margin, size - margin],
            radius=size // 6,
            fill='#FF0000'
        )

        # White play triangle
        center_x = size // 2
        center_y = size // 2
        tri_size = size // 4

        # Triangle points (pointing right)
        points = [
            (center_x - tri_size // 2 + 1, center_y - tri_size),
            (center_x - tri_size // 2 + 1, center_y + tri_size),
            (center_x + tri_size, center_y)
        ]
        draw.polygon(points, fill='white')

        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def fetch_and_cache_categories(youtube_service, region_code="US"):
    """Fetch YouTube categories from API and cache them."""
    try:
        response = youtube_service.videoCategories().list(
            part="snippet",
            regionCode=region_code
        ).execute()

        categories = {}
        for item in response.get("items", []):
            # Only include assignable categories
            if item["snippet"].get("assignable", False):
                categories[item["snippet"]["title"]] = item["id"]

        if categories:
            cache_data = {
                "fetched_at": datetime.now().isoformat(),
                "region_code": region_code,
                "categories": categories
            }
            with open(CATEGORIES_CACHE_FILE, 'w') as f:
                json.dump(cache_data, f, indent=2)
            return categories
    except Exception as e:
        print(f"Failed to fetch categories: {e}")
    return None


def get_authenticated_service():
    """Authenticate and return YouTube service."""
    credentials = None

    # Check if we have saved credentials
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, 'rb') as token:
            credentials = pickle.load(token)

        # Check if credentials have all required scopes
        if credentials and hasattr(credentials, 'scopes'):
            if not all(scope in credentials.scopes for scope in SCOPES):
                # Scopes changed, need to re-authenticate
                credentials = None
                TOKEN_FILE.unlink()  # Delete old token

    # If no valid credentials, authenticate
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                messagebox.showerror(
                    "Missing Credentials",
                    f"Please place your 'client_secrets.json' file in:\n{SCRIPT_DIR}\n\n"
                    "To obtain this file:\n"
                    "1. Go to https://console.cloud.google.com/\n"
                    "2. Create a new project (or select existing)\n"
                    "3. Search for 'YouTube Data API v3' and Enable it\n"
                    "4. Go to APIs & Services → OAuth consent screen\n"
                    "   - Select 'External', fill in app name & emails\n"
                    "   - Add scope: youtube.upload\n"
                    "   - Add your email as a test user\n"
                    "5. Go to APIs & Services → Credentials\n"
                    "   - Create Credentials → OAuth client ID\n"
                    "   - Select 'Desktop app'\n"
                    "   - Download JSON and rename to 'client_secrets.json'\n"
                    "6. Place the file in the folder shown above"
                )
                return None

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRETS_FILE), SCOPES
            )
            credentials = flow.run_local_server(port=0)

        # Save credentials for next run
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(credentials, token)

    return build('youtube', 'v3', credentials=credentials)


class UploadProgressWindow:
    """Window showing upload progress."""

    def __init__(self, parent, filename, file_size):
        self.window = tk.Toplevel(parent)
        self.window.title("Uploading...")
        self.window.geometry("400x200")
        self.window.resizable(False, False)
        self.window.transient(parent)
        # Don't use grab_set() - it blocks the window from being responsive

        self.cancelled = False
        self.parent = parent
        self._current_progress = 0
        self.file_size = file_size  # Total file size in bytes
        self.start_time = None  # Track upload start time

        # Center on parent
        self.window.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 200) // 2
        self.window.geometry(f"+{x}+{y}")

        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"Uploading: {filename}").pack(anchor=tk.W)

        self.progress = ttk.Progressbar(frame, length=360, mode='determinate')
        self.progress.pack(pady=10, fill=tk.X)

        status_frame = ttk.Frame(frame)
        status_frame.pack(fill=tk.X)

        self.status_label = ttk.Label(status_frame, text="Starting upload...")
        self.status_label.pack(side=tk.LEFT, anchor=tk.W)

        self.percent_label = ttk.Label(status_frame, text="0%")
        self.percent_label.pack(side=tk.RIGHT, anchor=tk.E)

        # Transfer info label (shows transferred/total and speed)
        self.transfer_label = ttk.Label(frame, text=f"0 MB / {self._format_size(self.file_size)}")
        self.transfer_label.pack(anchor=tk.W, pady=(5, 0))

        # Speed/ETA label
        self.speed_label = ttk.Label(frame, text="Calculating speed...")
        self.speed_label.pack(anchor=tk.W)

        # Cancel button
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        self.cancel_btn = ttk.Button(btn_frame, text="Cancel Upload", command=self._on_cancel)
        self.cancel_btn.pack(side=tk.RIGHT)

        # Handle window close button
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Force initial render
        self.window.update_idletasks()
        self.window.update()

    def _on_cancel(self):
        """Handle cancel button click."""
        if self.cancelled:
            return
        if messagebox.askyesno("Cancel Upload",
                               "Are you sure you want to cancel the upload?\n\n"
                               "The partially uploaded video will be deleted from YouTube.",
                               parent=self.window):
            self.cancelled = True
            self.status_label.config(text="Cancelling...")
            self.cancel_btn.config(state=tk.DISABLED)
            self.window.update()

    def is_cancelled(self):
        """Check if upload was cancelled."""
        return self.cancelled

    def get_progress(self):
        """Get current progress value."""
        return self._current_progress

    def update_progress(self, progress):
        """Update progress bar (0-100)."""
        import time

        # Initialize start time on first progress update
        if self.start_time is None and progress > 0:
            self.start_time = time.time()

        self._current_progress = progress
        self.progress['value'] = progress
        self.percent_label.config(text=f"{progress:.1f}%")
        self.status_label.config(text=f"Uploading... {progress:.1f}%")

        # Calculate transferred bytes
        transferred = int(self.file_size * progress / 100)
        self.transfer_label.config(
            text=f"{self._format_size(transferred)} / {self._format_size(self.file_size)}"
        )

        # Calculate speed and ETA
        if self.start_time and progress > 0:
            elapsed = time.time() - self.start_time
            if elapsed > 0:
                speed = transferred / elapsed  # bytes per second
                speed_text = f"{self._format_size(speed)}/s"

                # Estimate time remaining
                if progress < 100:
                    remaining_bytes = self.file_size - transferred
                    if speed > 0:
                        eta_seconds = remaining_bytes / speed
                        eta_text = self._format_time(eta_seconds)
                        self.speed_label.config(text=f"Speed: {speed_text} • ETA: {eta_text}")
                    else:
                        self.speed_label.config(text=f"Speed: {speed_text}")
                else:
                    self.speed_label.config(text=f"Speed: {speed_text} • Complete!")

        self.window.update()

    def _format_size(self, size_bytes):
        """Format bytes into human-readable size."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def _format_time(self, seconds):
        """Format seconds into human-readable time."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m"

    def close(self):
        self.window.destroy()


class YouTubeUploaderApp:
    """Main application window."""

    def __init__(self, video_path=None):
        # Use TkinterDnD for drag-and-drop support
        self.root = TkinterDnD.Tk()

        self.root.title("YouTube Video Uploader")
        self.root.geometry("500x800")
        self.root.minsize(400, 450)  # Minimum usable size
        self.root.resizable(True, True)

        # Set window icon
        self.app_icon = create_app_icon(32)
        if self.app_icon:
            self.root.iconphoto(True, self.app_icon)

        self.video_path = video_path
        self.youtube_service = None
        self.youtube_categories = get_youtube_categories()
        self._scheduled_videos_cache = None

        self._create_menu()
        self._create_widgets()

        # Set up drag-and-drop on the whole window
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind('<<Drop>>', self._on_drop)

        # Show schedule frame since scheduled is default
        self._on_privacy_change()

        if video_path:
            self.video_entry.delete(0, tk.END)
            self.video_entry.insert(0, video_path)
            # Auto-fill title from filename
            self.title_entry.delete(0, tk.END)
            self.title_entry.insert(0, Path(video_path).stem)
            # Show thumbnail
            self._update_thumbnail(video_path)

        # Try to refresh categories in background if cache is stale
        self.root.after(500, self._refresh_categories_if_needed)

    def _create_menu(self):
        """Create the menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="History...", command=self._show_history)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

    def _show_history(self):
        """Show upload history dialog."""
        history = load_upload_history()

        dialog = tk.Toplevel(self.root)
        dialog.title("Upload History")
        dialog.geometry("600x500")
        dialog.minsize(500, 400)
        dialog.transient(self.root)

        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 600) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 500) // 2
        dialog.geometry(f"+{x}+{y}")

        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        if not history:
            ttk.Label(main_frame, text="No upload history yet.",
                     font=('Segoe UI', 11)).pack(pady=20)
            ttk.Button(main_frame, text="Close", command=dialog.destroy).pack()
            return

        # Instructions
        ttk.Label(main_frame, text="Select an upload to view details. Use buttons to copy or apply values.",
                 font=('Segoe UI', 9), foreground='gray').pack(anchor=tk.W, pady=(0, 5))

        # Create a paned window for list and details
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Left side: history list
        list_frame = ttk.Frame(paned)
        paned.add(list_frame, weight=1)

        ttk.Label(list_frame, text="Previous Uploads:", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)

        list_container = ttk.Frame(list_frame)
        list_container.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        history_listbox = tk.Listbox(list_container, font=('Segoe UI', 9))
        list_scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=history_listbox.yview)
        history_listbox.configure(yscrollcommand=list_scrollbar.set)

        history_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Populate list
        for entry in history:
            title = entry.get('title', 'Untitled')[:40]
            date = entry.get('uploaded_at', '')[:10]
            video_path = entry.get('video_path', entry.get('filename', 'Unknown'))
            history_listbox.insert(tk.END, f"{date} - {video_path}")

        # Right side: details
        details_frame = ttk.Frame(paned)
        paned.add(details_frame, weight=2)

        ttk.Label(details_frame, text="Details:", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)

        details_container = ttk.Frame(details_frame)
        details_container.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        details_text = tk.Text(details_container, wrap=tk.WORD, font=('Segoe UI', 9), state=tk.DISABLED)
        details_scrollbar = ttk.Scrollbar(details_container, orient=tk.VERTICAL, command=details_text.yview)
        details_text.configure(yscrollcommand=details_scrollbar.set)

        details_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        details_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)

        selected_entry = [None]  # Use list to allow modification in nested function

        def on_select(event):
            selection = history_listbox.curselection()
            if not selection:
                return
            idx = selection[0]
            entry = history[idx]
            selected_entry[0] = entry

            details_text.config(state=tk.NORMAL)
            details_text.delete("1.0", tk.END)

            details_text.insert(tk.END, "TITLE:\n", "header")
            details_text.insert(tk.END, f"{entry.get('title', '')}\n\n")

            details_text.insert(tk.END, "VIDEO PATH:\n", "header")
            details_text.insert(tk.END, f"{entry.get('video_path', entry.get('filename', '(unknown)'))}\n\n")

            details_text.insert(tk.END, "DESCRIPTION:\n", "header")
            details_text.insert(tk.END, f"{entry.get('description', '')}\n\n")

            details_text.insert(tk.END, "TAGS:\n", "header")
            tags = entry.get('tags', [])
            details_text.insert(tk.END, f"{', '.join(tags) if tags else '(none)'}\n\n")

            details_text.insert(tk.END, "CATEGORY:\n", "header")
            details_text.insert(tk.END, f"{entry.get('category', '')}\n\n")

            details_text.insert(tk.END, "PRIVACY:\n", "header")
            details_text.insert(tk.END, f"{entry.get('privacy', '')}\n\n")

            if entry.get('video_url'):
                details_text.insert(tk.END, "VIDEO URL:\n", "header")
                details_text.insert(tk.END, f"{entry.get('video_url', '')}\n\n")

            details_text.insert(tk.END, "UPLOADED:\n", "header")
            details_text.insert(tk.END, f"{entry.get('uploaded_at', '')}\n")

            details_text.tag_configure("header", font=('Segoe UI', 9, 'bold'))
            details_text.config(state=tk.DISABLED)

        history_listbox.bind('<<ListboxSelect>>', on_select)

        def copy_title():
            if selected_entry[0]:
                self.root.clipboard_clear()
                self.root.clipboard_append(selected_entry[0].get('title', ''))
                messagebox.showinfo("Copied", "Title copied to clipboard!", parent=dialog)

        def copy_description():
            if selected_entry[0]:
                self.root.clipboard_clear()
                self.root.clipboard_append(selected_entry[0].get('description', ''))
                messagebox.showinfo("Copied", "Description copied to clipboard!", parent=dialog)

        def copy_tags():
            if selected_entry[0]:
                tags = selected_entry[0].get('tags', [])
                self.root.clipboard_clear()
                self.root.clipboard_append(', '.join(tags) if tags else '')
                messagebox.showinfo("Copied", "Tags copied to clipboard!", parent=dialog)

        def apply_all():
            if not selected_entry[0]:
                return
            entry = selected_entry[0]
            self.title_entry.delete(0, tk.END)
            self.title_entry.insert(0, entry.get('title', ''))
            self.desc_text.delete("1.0", tk.END)
            self.desc_text.insert("1.0", entry.get('description', ''))
            self.tags_entry.delete(0, tk.END)
            self.tags_entry.insert(0, ', '.join(entry.get('tags', [])))
            if entry.get('category') in self.youtube_categories:
                self.category_var.set(entry.get('category'))
            # Apply video path if it exists and file still exists
            video_path = entry.get('video_path', entry.get('filename', ''))
            path_msg = ""
            if video_path and Path(video_path).exists():
                self.video_entry.delete(0, tk.END)
                self.video_entry.insert(0, video_path)
                self._update_thumbnail(video_path)
                path_msg = f"\n\nVideo path: {video_path}"
            elif video_path:
                path_msg = f"\n\nVideo path not applied (file not found):\n{video_path}"
            else:
                path_msg = "\n\nNo video path stored in this entry."
            dialog.destroy()
            messagebox.showinfo("Applied", f"Title, description, tags, and category applied to the form!{path_msg}")

        ttk.Button(button_frame, text="Copy Title", command=copy_title).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Copy Description", command=copy_description).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Copy Tags", command=copy_tags).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Apply All to Form", command=apply_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)

        # Select first item by default
        if history:
            history_listbox.selection_set(0)
            history_listbox.event_generate('<<ListboxSelect>>')

    def _create_widgets(self):
        """Create all UI widgets."""
        # Use a canvas with scrollbar for the entire content
        canvas = tk.Canvas(self.root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient=tk.VERTICAL, command=canvas.yview)

        # Main scrollable frame
        main_frame = ttk.Frame(canvas, padding=15)

        # Configure canvas scrolling
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # Make the frame fill the canvas width
            canvas.itemconfig(frame_window, width=event.width)

        frame_window = canvas.create_window((0, 0), window=main_frame, anchor=tk.NW)
        main_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", configure_scroll)

        canvas.configure(yscrollcommand=scrollbar.set)

        # Pack canvas and scrollbar
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Enable mousewheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        # Video file selection
        ttk.Label(main_frame, text="Video File:", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)

        ttk.Label(main_frame, text="(drag & drop a file anywhere on this window)",
                 font=('Segoe UI', 8), foreground='gray').pack(anchor=tk.W)

        file_frame = ttk.Frame(main_frame)
        file_frame.pack(fill=tk.X, pady=(5, 10))

        self.video_entry = ttk.Entry(file_frame)
        self.video_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        browse_btn = ttk.Button(file_frame, text="Browse...", command=self._browse_video)
        browse_btn.pack(side=tk.LEFT, padx=(5, 0))

        # Video thumbnail preview (next to browse button)
        self.thumbnail_label = ttk.Label(file_frame, cursor='hand2')
        self.thumbnail_label.bind('<Button-1>', self._show_full_thumbnail)
        self.thumbnail_image = None  # Keep reference to prevent garbage collection
        self.thumbnail_full_image = None  # Full-size image for popup
        # Will be shown when a video is selected

        # Title
        ttk.Label(main_frame, text="Title: *", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)
        self.title_entry = ttk.Entry(main_frame)
        self.title_entry.pack(fill=tk.X, pady=(5, 10))

        # Description - using a frame with fixed minimum height
        ttk.Label(main_frame, text="Description:", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)

        desc_frame = ttk.Frame(main_frame)
        desc_frame.pack(fill=tk.X, pady=(5, 10))

        self.desc_text = tk.Text(desc_frame, height=4, wrap=tk.WORD)
        desc_scrollbar = ttk.Scrollbar(desc_frame, orient=tk.VERTICAL, command=self.desc_text.yview)
        self.desc_text.configure(yscrollcommand=desc_scrollbar.set)

        self.desc_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        desc_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Tags
        ttk.Label(main_frame, text="Tags (comma-separated):", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)
        self.tags_entry = ttk.Entry(main_frame)
        self.tags_entry.pack(fill=tk.X, pady=(5, 10))

        # Category
        ttk.Label(main_frame, text="Category:", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)
        self.category_var = tk.StringVar(value="Entertainment")
        self.category_combo = ttk.Combobox(
            main_frame,
            textvariable=self.category_var,
            values=sorted(self.youtube_categories.keys()),
            state='readonly'
        )
        self.category_combo.pack(fill=tk.X, pady=(5, 10))

        # Privacy setting
        ttk.Label(main_frame, text="Privacy: *", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W)

        privacy_frame = ttk.Frame(main_frame)
        privacy_frame.pack(fill=tk.X, pady=(5, 10))

        self.privacy_var = tk.StringVar(value="scheduled")

        ttk.Radiobutton(
            privacy_frame, text="Private (only you can see)",
            variable=self.privacy_var, value="private"
        ).pack(anchor=tk.W)

        ttk.Radiobutton(
            privacy_frame, text="Unlisted (anyone with link can see)",
            variable=self.privacy_var, value="unlisted"
        ).pack(anchor=tk.W)

        ttk.Radiobutton(
            privacy_frame, text="Public (everyone can see)",
            variable=self.privacy_var, value="public"
        ).pack(anchor=tk.W)

        ttk.Radiobutton(
            privacy_frame, text="Scheduled (publish at a specific time)",
            variable=self.privacy_var, value="scheduled"
        ).pack(anchor=tk.W)

        # Warning label for public
        self.warning_label = ttk.Label(
            main_frame,
            text="⚠️ Public videos are immediately visible to everyone!",
            foreground='red'
        )
        self.warning_label.pack(anchor=tk.W)
        self.warning_label.pack_forget()  # Hide initially

        # Schedule frame (hidden by default)
        self.schedule_frame = ttk.LabelFrame(main_frame, text="Schedule Publication", padding=10)

        schedule_inner = ttk.Frame(self.schedule_frame)
        schedule_inner.pack(fill=tk.X)

        # Date selection
        ttk.Label(schedule_inner, text="Date:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))

        date_frame = ttk.Frame(schedule_inner)
        date_frame.grid(row=0, column=1, sticky=tk.W)

        # Default to tomorrow
        tomorrow = datetime.now() + timedelta(days=1)

        self.month_var = tk.StringVar(value=str(tomorrow.month).zfill(2))
        self.day_var = tk.StringVar(value=str(tomorrow.day).zfill(2))
        self.year_var = tk.StringVar(value=str(tomorrow.year))

        months = [str(i).zfill(2) for i in range(1, 13)]
        days = [str(i).zfill(2) for i in range(1, 32)]
        years = [str(y) for y in range(datetime.now().year, datetime.now().year + 3)]

        month_combo = ttk.Combobox(date_frame, textvariable=self.month_var, values=months, width=4, state='readonly')
        month_combo.pack(side=tk.LEFT)
        ttk.Label(date_frame, text="/").pack(side=tk.LEFT)
        day_combo = ttk.Combobox(date_frame, textvariable=self.day_var, values=days, width=4, state='readonly')
        day_combo.pack(side=tk.LEFT)
        ttk.Label(date_frame, text="/").pack(side=tk.LEFT)
        year_combo = ttk.Combobox(date_frame, textvariable=self.year_var, values=years, width=6, state='readonly')
        year_combo.pack(side=tk.LEFT)

        # Time selection
        ttk.Label(schedule_inner, text="Time:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(10, 0))

        time_frame = ttk.Frame(schedule_inner)
        time_frame.grid(row=1, column=1, sticky=tk.W, pady=(10, 0))

        self.hour_var = tk.StringVar(value="12")
        self.minute_var = tk.StringVar(value="00")
        self.ampm_var = tk.StringVar(value="PM")

        hours = [str(i).zfill(2) for i in range(1, 13)]
        minutes = [str(i).zfill(2) for i in range(0, 60, 5)]

        hour_combo = ttk.Combobox(time_frame, textvariable=self.hour_var, values=hours, width=4, state='readonly')
        hour_combo.pack(side=tk.LEFT)
        ttk.Label(time_frame, text=":").pack(side=tk.LEFT)
        minute_combo = ttk.Combobox(time_frame, textvariable=self.minute_var, values=minutes, width=4, state='readonly')
        minute_combo.pack(side=tk.LEFT)
        ttk.Label(time_frame, text=" ").pack(side=tk.LEFT)
        ampm_combo = ttk.Combobox(time_frame, textvariable=self.ampm_var, values=["AM", "PM"], width=4, state='readonly')
        ampm_combo.pack(side=tk.LEFT)

        ttk.Label(self.schedule_frame, text="(Local time - will be converted to UTC)", font=('Segoe UI', 8)).pack(anchor=tk.W, pady=(5, 0))

        # Next day slot and view schedule buttons
        slot_btn_frame = ttk.Frame(self.schedule_frame)
        slot_btn_frame.pack(anchor=tk.W, pady=(10, 0))

        self.next_slot_btn = ttk.Button(
            slot_btn_frame,
            text="📅 Calculate Next Day Slot",
            command=self._calculate_next_day_slot
        )
        self.next_slot_btn.pack(side=tk.LEFT)

        self.view_schedule_btn = ttk.Button(
            slot_btn_frame,
            text="📋 View Schedule",
            command=self._view_schedule,
            state=tk.DISABLED
        )
        self.view_schedule_btn.pack(side=tk.LEFT, padx=(5, 0))

        self.slot_status_label = ttk.Label(self.schedule_frame, text="", font=('Segoe UI', 8))
        self.slot_status_label.pack(anchor=tk.W, pady=(2, 0))

        self.privacy_var.trace_add('write', self._on_privacy_change)

        # Made for kids
        self.kids_var = tk.BooleanVar(value=False)
        self.kids_checkbox = ttk.Checkbutton(
            main_frame,
            text="Made for kids (COPPA compliance)",
            variable=self.kids_var
        )
        self.kids_checkbox.pack(anchor=tk.W, pady=(10, 10))

        # Buttons - fixed at bottom
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 5))

        ttk.Button(btn_frame, text="Cancel", command=self.root.quit).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Upload", command=self._upload).pack(side=tk.RIGHT, padx=(0, 10))

    def _on_privacy_change(self, *args):
        """Show/hide warning and schedule frame based on privacy selection."""
        privacy = self.privacy_var.get()

        # Handle warning label
        if privacy == "public":
            self.warning_label.pack(anchor=tk.W)
        else:
            self.warning_label.pack_forget()

        # Handle schedule frame
        if privacy == "scheduled":
            self.schedule_frame.pack(fill=tk.X, pady=(5, 15), before=self.kids_checkbox)
        else:
            self.schedule_frame.pack_forget()

    def _refresh_categories_if_needed(self):
        """Refresh categories from API if cache is stale and we have credentials."""
        # Check if cache needs refresh
        needs_refresh = True
        if CATEGORIES_CACHE_FILE.exists():
            try:
                with open(CATEGORIES_CACHE_FILE, 'r') as f:
                    cache_data = json.load(f)
                fetched_at = datetime.fromisoformat(cache_data["fetched_at"])
                if datetime.now() - fetched_at < timedelta(days=7):
                    needs_refresh = False
            except Exception:
                pass

        if not needs_refresh:
            return

        # Only try if we have saved credentials (don't prompt user)
        if not TOKEN_FILE.exists():
            return

        try:
            if not self.youtube_service:
                self.youtube_service = get_authenticated_service()

            if self.youtube_service:
                new_categories = fetch_and_cache_categories(self.youtube_service)
                if new_categories:
                    self.youtube_categories = new_categories
                    current_value = self.category_var.get()
                    self.category_combo['values'] = sorted(new_categories.keys())
                    # Keep current selection if valid, otherwise default to Entertainment
                    if current_value not in new_categories:
                        if "Entertainment" in new_categories:
                            self.category_var.set("Entertainment")
                        elif new_categories:
                            self.category_var.set(list(new_categories.keys())[0])
        except Exception:
            pass  # Silent fail, we have fallback categories

    def _on_drop(self, event):
        """Handle file drop onto the window."""
        # Get the dropped file path
        file_path = event.data

        # Handle paths with curly braces (tkinterdnd2 wraps paths with spaces)
        if file_path.startswith('{') and file_path.endswith('}'):
            file_path = file_path[1:-1]

        # Handle multiple files - just take the first one
        if '\n' in file_path:
            file_path = file_path.split('\n')[0]

        # Clean up the path
        file_path = file_path.strip()

        # Check if it's a video file
        path = Path(file_path)
        if not path.exists():
            messagebox.showerror("Error", f"File not found: {file_path}")
            return

        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            result = messagebox.askyesno(
                "Unknown Format",
                f"'{path.suffix}' may not be a supported video format.\n\n"
                "Do you want to use this file anyway?"
            )
            if not result:
                return

        # Set the file path
        self.video_entry.delete(0, tk.END)
        self.video_entry.insert(0, file_path)

        # Auto-fill title if empty
        if not self.title_entry.get().strip():
            self.title_entry.delete(0, tk.END)
            self.title_entry.insert(0, path.stem)

        # Show thumbnail
        self._update_thumbnail(file_path)

    def _update_thumbnail(self, video_path):
        """Extract and display a thumbnail from the video."""
        try:
            # Open the video file
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                self.thumbnail_label.pack_forget()
                return

            # Get video properties
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)

            # Seek to 10% into the video (or 1 second, whichever is less)
            # This usually gets a more interesting frame than the first frame
            if total_frames > 0 and fps > 0:
                target_frame = min(int(total_frames * 0.1), int(fps))  # 10% or 1 second
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

            # Read a frame
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                self.thumbnail_label.pack_forget()
                return

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Convert to PIL Image
            pil_image = Image.fromarray(frame_rgb)

            # Store full-size image for popup (scaled to reasonable max size)
            full_width, full_height = pil_image.size
            max_full_dim = 800
            if full_width > max_full_dim or full_height > max_full_dim:
                if full_width > full_height:
                    ratio = max_full_dim / full_width
                else:
                    ratio = max_full_dim / full_height
                full_image = pil_image.resize(
                    (int(full_width * ratio), int(full_height * ratio)),
                    Image.Resampling.LANCZOS
                )
            else:
                full_image = pil_image.copy()
            self.thumbnail_full_image = ImageTk.PhotoImage(full_image)

            # Resize to fit next to browse button (small thumbnail)
            max_height = 40
            width, height = pil_image.size
            ratio = max_height / height
            new_width = int(width * ratio)
            pil_image = pil_image.resize((new_width, max_height), Image.Resampling.LANCZOS)

            # Convert to PhotoImage for tkinter
            self.thumbnail_image = ImageTk.PhotoImage(pil_image)

            # Update the label
            self.thumbnail_label.configure(image=self.thumbnail_image)
            self.thumbnail_label.pack(side=tk.LEFT, padx=(5, 0))

        except Exception as e:
            # If thumbnail extraction fails, just hide the label
            self.thumbnail_label.pack_forget()
            self.thumbnail_full_image = None

    def _show_full_thumbnail(self, event=None):
        """Show the full-size thumbnail in a popup window."""
        if not self.thumbnail_full_image:
            return

        popup = tk.Toplevel(self.root)
        popup.title("Video Thumbnail")
        popup.transient(self.root)

        # Get image dimensions
        img_width = self.thumbnail_full_image.width()
        img_height = self.thumbnail_full_image.height()

        # Set window size to fit image with small padding
        popup.geometry(f"{img_width + 20}x{img_height + 70}")

        # Center on parent
        popup.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - img_width - 20) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - img_height - 50) // 2
        popup.geometry(f"+{x}+{y}")

        frame = ttk.Frame(popup, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Display the image
        img_label = ttk.Label(frame, image=self.thumbnail_full_image)
        img_label.pack()

        # Close button
        ttk.Button(frame, text="Close", command=popup.destroy).pack(pady=(10, 0))

        # Also close on Escape key
        popup.bind('<Escape>', lambda e: popup.destroy())
        popup.focus_set()

    def _calculate_next_day_slot(self):
        """Find the latest scheduled video and set date to the next day at the same time."""
        self.slot_status_label.config(text="Searching for scheduled videos...")
        self.view_schedule_btn.config(state=tk.DISABLED)
        self._scheduled_videos_cache = None
        self.root.update()

        # Authenticate if needed
        if not self.youtube_service:
            self.youtube_service = get_authenticated_service()
            if not self.youtube_service:
                self.slot_status_label.config(text="Authentication failed")
                return

        try:
            # Get the user's channel
            channels_response = self.youtube_service.channels().list(
                mine=True,
                part='contentDetails'
            ).execute()

            if not channels_response.get('items'):
                self.slot_status_label.config(text="No channel found")
                return

            # Get uploads playlist ID
            uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

            # Get recent videos from uploads playlist (get more to find scheduled ones)
            playlist_response = self.youtube_service.playlistItems().list(
                playlistId=uploads_playlist_id,
                part='contentDetails',
                maxResults=50
            ).execute()

            if not playlist_response.get('items'):
                self.slot_status_label.config(text="No videos found")
                return

            # Get video IDs
            video_ids = [item['contentDetails']['videoId'] for item in playlist_response['items']]

            # Get video details including status
            videos_response = self.youtube_service.videos().list(
                id=','.join(video_ids),
                part='status,snippet'
            ).execute()

            # Get timezone offset for local time conversion
            import time
            if time.daylight and time.localtime().tm_isdst:
                utc_offset_seconds = -time.altzone
            else:
                utc_offset_seconds = -time.timezone

            # Find videos with publishAt (scheduled videos)
            scheduled_videos = []
            now = datetime.utcnow()

            for video in videos_response.get('items', []):
                status = video.get('status', {})
                publish_at = status.get('publishAt')

                if publish_at:
                    # Parse ISO 8601 datetime
                    # Format: 2026-01-20T17:00:00Z or 2026-01-20T17:00:00.000Z
                    publish_at_clean = publish_at.replace('Z', '+00:00')
                    if '.' in publish_at_clean:
                        dt_utc = datetime.fromisoformat(publish_at_clean.split('.')[0])
                    else:
                        dt_utc = datetime.fromisoformat(publish_at_clean.replace('+00:00', ''))

                    # Convert to local time
                    dt_local = dt_utc + timedelta(seconds=utc_offset_seconds)

                    scheduled_videos.append({
                        'title': video['snippet']['title'],
                        'publishAt': dt_utc,
                        'publishAtLocal': dt_local,
                        'publishAtStr': publish_at
                    })

            if not scheduled_videos:
                self.slot_status_label.config(text="No scheduled videos found. Using current time + 1 day.")
                # Default to tomorrow at the currently selected time
                current_dt = self._get_scheduled_datetime()
                if current_dt:
                    next_dt = current_dt + timedelta(days=1)
                    self._set_schedule_datetime(next_dt)
                return

            # Sort by publish date (earliest first for display, but we need latest for calculation)
            scheduled_videos.sort(key=lambda x: x['publishAt'])
            latest = scheduled_videos[-1]  # Last one is the latest

            # Calculate next day at same time
            next_day_local = latest['publishAtLocal'] + timedelta(days=1)

            # Update the UI
            self._set_schedule_datetime(next_day_local)

            # Store scheduled videos data for "View Schedule" button
            self._scheduled_videos_cache = {
                'videos': scheduled_videos,
                'latest': latest,
                'next_day': next_day_local
            }
            self.view_schedule_btn.config(state=tk.NORMAL)

            self.slot_status_label.config(
                text=f"✓ Set to day after \"{latest['title'][:30]}{'...' if len(latest['title']) > 30 else ''}\""
            )

        except Exception as e:
            self.slot_status_label.config(text=f"Error: {str(e)[:40]}")
            messagebox.showerror("Error", f"Failed to fetch scheduled videos:\n\n{str(e)}")

    def _view_schedule(self):
        """Show the scheduled videos dialog from cached data."""
        if not self._scheduled_videos_cache:
            messagebox.showinfo("No Data", "Click 'Calculate Next Day Slot' first to fetch scheduled videos.")
            return

        self._show_scheduled_videos_dialog(
            self._scheduled_videos_cache['videos'],
            self._scheduled_videos_cache['latest'],
            self._scheduled_videos_cache['next_day']
        )

    def _show_scheduled_videos_dialog(self, scheduled_videos, latest, next_day_local):
        """Show a dialog with all scheduled videos."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Scheduled Videos")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()

        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 500) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 400) // 2
        dialog.geometry(f"+{x}+{y}")

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        video_count = len(scheduled_videos)
        ttk.Label(frame, text=f"Upcoming Scheduled Videos ({video_count}):", font=('Segoe UI', 11, 'bold')).pack(anchor=tk.W)
        ttk.Label(frame, text="(sorted by release date)", font=('Segoe UI', 8), foreground='gray').pack(anchor=tk.W)

        # Create scrollable list
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 10))

        # Text widget for the list (supports colors better than Listbox)
        text_widget = tk.Text(list_frame, wrap=tk.WORD, font=('Consolas', 9), cursor='arrow')
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure tags for highlighting
        text_widget.tag_configure('latest', background='#d4edda', font=('Consolas', 9, 'bold'))
        text_widget.tag_configure('new_video', background='#cce5ff', font=('Consolas', 9, 'bold'))
        text_widget.tag_configure('date', foreground='#0066cc')

        # Add scheduled videos to the list
        for i, video in enumerate(scheduled_videos):
            date_str = video['publishAtLocal'].strftime("%a %b %d, %Y @ %I:%M %p")
            title = video['title'][:50] + ('...' if len(video['title']) > 50 else '')

            is_latest = video == latest
            line = f"{date_str}\n  {title}\n\n"

            if is_latest:
                text_widget.insert(tk.END, line, 'latest')
            else:
                text_widget.insert(tk.END, line)

        # Add the new video slot
        new_date_str = next_day_local.strftime("%a %b %d, %Y @ %I:%M %p")
        new_line = f"{new_date_str}\n  → YOUR NEW VIDEO (this upload)\n"
        text_widget.insert(tk.END, new_line, 'new_video')

        # Make text widget read-only
        text_widget.configure(state=tk.DISABLED)

        # Legend
        legend_frame = ttk.Frame(frame)
        legend_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Label(legend_frame, text="Legend:", font=('Segoe UI', 8, 'bold')).pack(side=tk.LEFT)

        latest_label = tk.Label(legend_frame, text=" Latest scheduled ", bg='#d4edda', font=('Segoe UI', 8))
        latest_label.pack(side=tk.LEFT, padx=(10, 5))

        new_label = tk.Label(legend_frame, text=" Your new video ", bg='#cce5ff', font=('Segoe UI', 8))
        new_label.pack(side=tk.LEFT, padx=(5, 0))

        # Close button
        ttk.Button(frame, text="OK", command=dialog.destroy).pack(pady=(10, 0))

    def _set_schedule_datetime(self, dt):
        """Set the schedule UI fields from a datetime object."""
        self.month_var.set(str(dt.month).zfill(2))
        self.day_var.set(str(dt.day).zfill(2))
        self.year_var.set(str(dt.year))

        # Convert to 12-hour format
        hour = dt.hour
        if hour == 0:
            hour_12 = 12
            ampm = "AM"
        elif hour < 12:
            hour_12 = hour
            ampm = "AM"
        elif hour == 12:
            hour_12 = 12
            ampm = "PM"
        else:
            hour_12 = hour - 12
            ampm = "PM"

        self.hour_var.set(str(hour_12).zfill(2))
        self.minute_var.set(str(dt.minute).zfill(2))
        self.ampm_var.set(ampm)

    def _browse_video(self):
        """Open file dialog to select video."""
        filetypes = [
            ("Video files", " ".join(f"*{ext}" for ext in VIDEO_EXTENSIONS)),
            ("All files", "*.*")
        ]
        filepath = filedialog.askopenfilename(filetypes=filetypes)
        if filepath:
            self.video_entry.delete(0, tk.END)
            self.video_entry.insert(0, filepath)
            # Auto-fill title if empty
            if not self.title_entry.get().strip():
                self.title_entry.delete(0, tk.END)
                self.title_entry.insert(0, Path(filepath).stem)
            # Show thumbnail
            self._update_thumbnail(filepath)

    def _validate_inputs(self):
        """Validate all inputs before upload."""
        video_path = self.video_entry.get().strip()
        title = self.title_entry.get().strip()

        if not video_path:
            messagebox.showerror("Error", "Please select a video file.")
            return False

        if not Path(video_path).exists():
            messagebox.showerror("Error", "Video file does not exist.")
            return False

        if Path(video_path).suffix.lower() not in VIDEO_EXTENSIONS:
            messagebox.showwarning("Warning", "File may not be a supported video format.")

        if not title:
            messagebox.showerror("Error", "Please enter a title for the video.")
            return False

        if len(title) > 100:
            messagebox.showerror("Error", "Title must be 100 characters or less.")
            return False

        # Validate scheduled time
        if self.privacy_var.get() == "scheduled":
            scheduled_dt = self._get_scheduled_datetime()
            if scheduled_dt is None:
                return False
            if scheduled_dt <= datetime.now():
                messagebox.showerror("Error", "Scheduled time must be in the future.")
                return False

        # Confirm public upload
        if self.privacy_var.get() == "public":
            result = messagebox.askyesno(
                "Confirm Public Upload",
                "You are about to upload this video as PUBLIC.\n\n"
                "This means ANYONE can see it immediately.\n\n"
                "Are you sure you want to continue?",
                icon='warning'
            )
            if not result:
                return False

        return True

    def _get_scheduled_datetime(self):
        """Parse the scheduled date/time from UI inputs. Returns datetime or None if invalid."""
        try:
            month = int(self.month_var.get())
            day = int(self.day_var.get())
            year = int(self.year_var.get())
            hour = int(self.hour_var.get())
            minute = int(self.minute_var.get())
            ampm = self.ampm_var.get()

            # Convert to 24-hour format
            if ampm == "PM" and hour != 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0

            return datetime(year, month, day, hour, minute)
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid date/time: {e}")
            return None

    def _datetime_to_iso8601(self, dt):
        """Convert datetime to ISO 8601 format for YouTube API."""
        # YouTube API expects ISO 8601 format with timezone
        # We need to convert local time to UTC
        import time

        # Get local timezone offset in seconds
        if time.daylight and time.localtime().tm_isdst:
            utc_offset = time.altzone
        else:
            utc_offset = time.timezone

        # Convert to UTC
        utc_dt = dt + timedelta(seconds=utc_offset)

        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _find_partial_upload_video_id(self, title, description, publish_at):
        """
        Try to find a partially uploaded video by matching title, description, and publish time.
        Returns the video_id if found, None otherwise.
        """
        try:
            # Search for videos on the user's channel uploaded in the last few minutes
            # that match our title and description
            search_response = self.youtube_service.search().list(
                part='snippet',
                forMine=True,
                type='video',
                maxResults=10,
                order='date'  # Most recent first
            ).execute()

            for item in search_response.get('items', []):
                video_title = item['snippet'].get('title', '')
                video_desc = item['snippet'].get('description', '')
                video_id = item['id'].get('videoId')

                # Check if title matches exactly
                if video_title != title:
                    continue

                # Check if description matches (at least the beginning, as it may be truncated in search results)
                if description and not video_desc.startswith(description[:100]):
                    # Description doesn't match
                    continue

                # If we have a publish_at time, verify it matches
                if publish_at and video_id:
                    # Get full video details to check publishAt
                    video_response = self.youtube_service.videos().list(
                        part='status',
                        id=video_id
                    ).execute()

                    if video_response.get('items'):
                        video_publish_at = video_response['items'][0].get('status', {}).get('publishAt', '')
                        # Compare publish times (normalize format)
                        if publish_at.replace('.000Z', 'Z') != video_publish_at.replace('.000Z', 'Z'):
                            continue

                # Found a match!
                return video_id

        except Exception as e:
            print(f"Error searching for partial upload: {e}")

        return None

    def _upload(self):
        """Perform the upload."""
        if not self._validate_inputs():
            return

        # Authenticate if needed
        if not self.youtube_service:
            self.youtube_service = get_authenticated_service()
            if not self.youtube_service:
                return

        video_path = self.video_entry.get().strip()
        title = self.title_entry.get().strip()
        description = self.desc_text.get("1.0", tk.END).strip()
        tags = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]
        category_id = self.youtube_categories.get(self.category_var.get(), "24")  # Default to Entertainment (24)
        privacy = self.privacy_var.get()
        made_for_kids = self.kids_var.get()

        # Handle scheduled publishing
        publish_at = None
        if privacy == "scheduled":
            scheduled_dt = self._get_scheduled_datetime()
            publish_at = self._datetime_to_iso8601(scheduled_dt)
            # For scheduled videos, set privacy to private initially
            privacy = "private"

        # Prepare video metadata
        body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags,
                'categoryId': category_id,
            },
            'status': {
                'privacyStatus': privacy,
                'selfDeclaredMadeForKids': made_for_kids,
            }
        }

        # Add publishAt for scheduled videos
        if publish_at:
            body['status']['publishAt'] = publish_at

        # Create media upload
        media = MediaFileUpload(
            video_path,
            chunksize=4*1024*1024,  # 4MB chunks
            resumable=True
        )

        # Show progress window
        file_size = Path(video_path).stat().st_size
        progress_window = UploadProgressWindow(self.root, Path(video_path).name, file_size)

        # Save to history immediately when upload starts
        history_timestamp = add_to_history({
            'title': title,
            'description': description,
            'tags': tags,
            'category': self.category_var.get(),
            'privacy': self.privacy_var.get(),
            'filename': video_path,
            'status': 'uploading',
            'progress': 0,
        })

        # Upload state shared between threads
        upload_state = {
            'response': None,
            'error': None,
            'progress': 0,
            'done': False,
            'video_id': None,
        }

        def upload_thread():
            """Background thread for uploading."""
            try:
                request = self.youtube_service.videos().insert(
                    part=','.join(body.keys()),
                    body=body,
                    media_body=media
                )

                response = None
                while response is None:
                    # Check for cancellation
                    if progress_window.is_cancelled():
                        upload_state['done'] = True
                        return

                    status, response = request.next_chunk()
                    if status:
                        upload_state['progress'] = status.progress() * 100

                    # If we got a response, extract video_id immediately
                    if response:
                        upload_state['video_id'] = response.get('id')

                upload_state['response'] = response
                upload_state['done'] = True

            except Exception as e:
                upload_state['error'] = e
                upload_state['done'] = True

        # Start upload in background thread
        thread = threading.Thread(target=upload_thread, daemon=True)
        thread.start()

        # Poll for updates while keeping UI responsive
        def check_upload():
            # Update progress display
            if upload_state['progress'] > 0:
                progress_window.update_progress(upload_state['progress'])
                # Update history periodically
                update_history_entry(history_timestamp, {'progress': upload_state['progress']})

            if not upload_state['done']:
                # Continue polling
                self.root.after(100, check_upload)
                return

            # Upload finished (success, error, or cancelled)
            progress_window.close()

            # Handle cancellation
            if progress_window.is_cancelled():
                # Try to delete the video from YouTube if it was created
                video_id = upload_state.get('video_id')

                # If we don't have a video_id, try to find it by searching recent uploads
                if not video_id:
                    video_id = self._find_partial_upload_video_id(title, description, publish_at)

                if video_id:
                    try:
                        self.youtube_service.videos().delete(id=video_id).execute()
                        update_history_entry(history_timestamp, {
                            'status': 'cancelled',
                            'progress': upload_state['progress'],
                            'note': 'Video deleted from YouTube',
                        })
                        messagebox.showinfo("Cancelled", "Upload was cancelled and the video was deleted from YouTube.")
                    except Exception as del_error:
                        update_history_entry(history_timestamp, {
                            'status': 'cancelled',
                            'progress': upload_state['progress'],
                            'video_id': video_id,
                            'note': f'Failed to delete video: {del_error}',
                        })
                        messagebox.showwarning("Cancelled",
                            f"Upload was cancelled but failed to delete video from YouTube.\n\n"
                            f"Video ID: {video_id}\n\n"
                            f"Error: {str(del_error)}\n\n"
                            f"You may need to delete it manually in YouTube Studio.")
                else:
                    update_history_entry(history_timestamp, {
                        'status': 'cancelled',
                        'progress': upload_state['progress'],
                    })
                    messagebox.showinfo("Cancelled", "Upload was cancelled.\n\n"
                        "No matching video was found on YouTube to delete.")
                return

            # Handle error
            if upload_state['error']:
                update_history_entry(history_timestamp, {
                    'status': 'failed',
                    'error': str(upload_state['error']),
                })
                messagebox.showerror("Upload Error", f"Failed to upload video:\n\n{str(upload_state['error'])}")
                return

            # Handle success
            response = upload_state['response']
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            studio_url = f"https://studio.youtube.com/video/{video_id}/edit"

            update_history_entry(history_timestamp, {
                'status': 'completed',
                'progress': 100,
                'video_url': video_url,
                'video_id': video_id,
            })

            # Build success message
            if publish_at:
                scheduled_dt = self._get_scheduled_datetime()
                schedule_str = scheduled_dt.strftime("%B %d, %Y at %I:%M %p")
                privacy_info = f"Scheduled to publish: {schedule_str}"
            else:
                privacy_info = f"Privacy: {privacy}"

            self._show_upload_complete_dialog(title, privacy_info, video_url, studio_url)

        # Start polling
        self.root.after(100, check_upload)

    def _reset_form(self):
        """Reset the form for a new upload."""
        self.video_entry.delete(0, tk.END)
        self.title_entry.delete(0, tk.END)
        self.desc_text.delete("1.0", tk.END)
        self.tags_entry.delete(0, tk.END)
        self.category_var.set("Entertainment")
        self.privacy_var.set("scheduled")
        self.kids_var.set(False)
        # Reset schedule to tomorrow
        tomorrow = datetime.now() + timedelta(days=1)
        self.month_var.set(str(tomorrow.month).zfill(2))
        self.day_var.set(str(tomorrow.day).zfill(2))
        self.year_var.set(str(tomorrow.year))
        self.hour_var.set("12")
        self.minute_var.set("00")
        self.ampm_var.set("PM")
        # Hide thumbnail
        self.thumbnail_label.pack_forget()
        self.thumbnail_image = None
        self.thumbnail_full_image = None
        # Clear scheduled videos cache
        self._scheduled_videos_cache = None
        self.view_schedule_btn.config(state=tk.DISABLED)
        self.slot_status_label.config(text="")

    def _show_upload_complete_dialog(self, title, privacy_info, video_url, studio_url):
        """Show upload complete dialog with clickable link. Returns True if user wants to upload another."""
        import webbrowser

        dialog = tk.Toplevel(self.root)
        dialog.title("Upload Complete!")
        dialog.geometry("450x250")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        upload_another = [False]  # Use list to allow modification in nested function

        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 450) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 250) // 2
        dialog.geometry(f"+{x}+{y}")

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # Success message
        ttk.Label(frame, text="✓ Video uploaded successfully!",
                  font=('Segoe UI', 11, 'bold'), foreground='green').pack(anchor=tk.W)

        ttk.Label(frame, text=f"\nTitle: {title}", font=('Segoe UI', 10)).pack(anchor=tk.W)
        ttk.Label(frame, text=privacy_info, font=('Segoe UI', 10)).pack(anchor=tk.W)

        # URL section
        url_frame = ttk.Frame(frame)
        url_frame.pack(anchor=tk.W, pady=(10, 0), fill=tk.X)

        ttk.Label(url_frame, text="URL: ", font=('Segoe UI', 10)).pack(side=tk.LEFT)

        # Clickable link
        link_label = tk.Label(url_frame, text=video_url, fg='blue', cursor='hand2',
                              font=('Segoe UI', 10, 'underline'))
        link_label.pack(side=tk.LEFT)
        link_label.bind('<Button-1>', lambda e: webbrowser.open(video_url))

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))

        def open_studio():
            webbrowser.open(studio_url)

        def do_upload_another():
            upload_another[0] = True
            dialog.destroy()

        ttk.Button(btn_frame, text="Open in YouTube Studio", command=open_studio).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Upload Another", command=do_upload_another).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)

        # Close on Escape
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        dialog.focus_set()

        # Wait for dialog to close
        self.root.wait_window(dialog)

        # If user wants to upload another, reset the form
        if upload_another[0]:
            self._reset_form()
        else:
            self.root.quit()

    def run(self):
        """Start the application."""
        self.root.mainloop()


def main():
    """Main entry point."""
    video_path = None

    # Check if a video was dragged onto the script
    if len(sys.argv) > 1:
        video_path = sys.argv[1]
        if not Path(video_path).exists():
            messagebox.showerror("Error", f"File not found: {video_path}")
            sys.exit(1)

    app = YouTubeUploaderApp(video_path)
    app.run()


if __name__ == "__main__":
    main()

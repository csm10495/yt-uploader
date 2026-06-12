"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  authenticated: false,
  categories: {},
  videoExtensions: [],
  selectedFile: null,     // File object (browser upload)
  fileSize: 0,
  uploadId: null,
  pollTimer: null,
  startTime: null,
  scheduledCache: null,   // { scheduled: [...], next_slot: {...} }
  xhr: null,              // active XMLHttpRequest during browser->server staging
  staging: false,         // true while the file is being sent to the server
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1048576).toFixed(2)} MB`;
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}

function localDateStr(date) {
  // yyyy-mm-dd in the user's LOCAL timezone (toISOString would use UTC).
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function formatTime(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3000);
}

// ---------------------------------------------------------------------------
// Theme (auto / light / dark)
// ---------------------------------------------------------------------------
const THEME_ORDER = ["auto", "light", "dark"];
const THEME_ICON = { auto: "🖥️", light: "☀️", dark: "🌙" };
const THEME_LABEL = { auto: "Auto (system)", light: "Light", dark: "Dark" };

function getTheme() {
  const t = localStorage.getItem("theme");
  return t === "light" || t === "dark" ? t : "auto";
}

function applyTheme(theme) {
  if (theme === "auto") {
    document.documentElement.removeAttribute("data-theme");
    localStorage.removeItem("theme");
  } else {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }
  const btn = $("themeToggle");
  if (btn) {
    btn.textContent = THEME_ICON[theme];
    btn.title = `Theme: ${THEME_LABEL[theme]} (click to change)`;
  }
}

function cycleTheme() {
  const next = THEME_ORDER[(THEME_ORDER.indexOf(getTheme()) + 1) % THEME_ORDER.length];
  applyTheme(next);
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
async function init() {
  applyTheme(getTheme());
  populateScheduleDefaults();
  wireEvents();
  await loadStatus();
}

async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    state.authenticated = data.authenticated;
    state.categories = data.categories || {};
    state.videoExtensions = data.video_extensions || [];
    populateCategories(data.default_category);
    renderAuth(data);
  } catch (e) {
    toast("Failed to load status");
  }
}

function renderAuth(data) {
  const accountMenu = $("accountMenu");
  const accountName = $("accountName");
  const signInBtn = $("signInBtn");
  const banner = $("authBanner");
  const form = $("uploadForm");
  const prompt = $("signInPrompt");

  // Always reset the dropdown to closed state on (re)render.
  closeAccountDropdown();

  // The form is usable only when signed in.
  form.disabled = !state.authenticated;

  if (state.authenticated) {
    accountName.textContent = data.channel_name || "My channel";
    if (data.channel_name) $("accountBtn").title = data.channel_name;
    accountMenu.classList.remove("hidden");
    signInBtn.classList.add("hidden");
    banner.classList.add("hidden");
    prompt.classList.add("hidden");
  } else {
    accountMenu.classList.add("hidden");
    if (data.has_client_secrets) {
      signInBtn.classList.remove("hidden");
      signInBtn.onclick = () => { window.location.href = "/api/auth/login"; };
      banner.classList.add("hidden");
      prompt.classList.remove("hidden");
    } else {
      signInBtn.classList.add("hidden");
      prompt.classList.add("hidden");
      banner.textContent =
        "client_secrets.json is missing. Follow the README setup steps and place the file next to app.py, then refresh.";
      banner.classList.remove("hidden");
    }
  }
}

function toggleAccountDropdown() {
  const dd = $("accountDropdown");
  const open = dd.classList.toggle("hidden") === false;
  $("accountBtn").setAttribute("aria-expanded", open ? "true" : "false");
}

function closeAccountDropdown() {
  $("accountDropdown").classList.add("hidden");
  $("accountBtn").setAttribute("aria-expanded", "false");
}

async function signOut() {
  closeAccountDropdown();
  await fetch("/api/auth/logout", { method: "POST" });
  state.authenticated = false;
  await loadStatus();
  toast("Signed out");
}

function populateCategories(defaultLabel) {
  const sel = $("category");
  sel.innerHTML = "";
  Object.keys(state.categories).sort().forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  if (state.categories[defaultLabel]) sel.value = defaultLabel;
}

function populateScheduleDefaults() {
  const tomorrow = new Date(Date.now() + 86400000);
  $("scheduleDate").value = localDateStr(tomorrow);
  $("scheduleTime").value = "12:00";
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------
function wireEvents() {
  // Theme toggle (auto -> light -> dark -> auto)
  $("themeToggle").addEventListener("click", cycleTheme);

  // Account menu (click name to reveal sign out)
  $("accountBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleAccountDropdown();
  });
  $("signOutItem").addEventListener("click", signOut);
  $("promptSignInBtn").addEventListener("click", () => {
    window.location.href = "/api/auth/login";
  });
  // Close the dropdown when clicking anywhere else.
  document.addEventListener("click", (e) => {
    if (!$("accountMenu").contains(e.target)) closeAccountDropdown();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAccountDropdown();
  });

  // Title counter
  $("title").addEventListener("input", () => {
    $("titleCount").textContent = `${$("title").value.length}/100`;
  });

  // File selection
  $("browseBtn").addEventListener("click", () => $("videoInput").click());
  $("videoInput").addEventListener("change", (e) => {
    if (e.target.files.length) setBrowserFile(e.target.files[0]);
  });
  $("clearFileBtn").addEventListener("click", clearFile);

  // Drag and drop
  const dz = $("dropZone");
  ["dragenter", "dragover"].forEach((ev) =>
    document.addEventListener(ev, (e) => {
      e.preventDefault();
      if (!state.authenticated) return;
      dz.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    document.addEventListener(ev, (e) => {
      e.preventDefault();
      if (ev === "dragleave" && e.relatedTarget) return;
      dz.classList.remove("dragover");
    })
  );
  document.addEventListener("drop", (e) => {
    if (!state.authenticated) return;
    if (e.dataTransfer.files.length) setBrowserFile(e.dataTransfer.files[0]);
  });

  // Privacy
  document.querySelectorAll('input[name="privacy"]').forEach((r) =>
    r.addEventListener("change", onPrivacyChange)
  );
  onPrivacyChange();

  // Schedule buttons
  $("nextSlotBtn").addEventListener("click", calculateNextSlot);
  $("viewScheduleBtn").addEventListener("click", showScheduleModal);
  $("closeScheduleBtn").addEventListener("click", () => $("scheduleModal").classList.add("hidden"));

  // Upload
  $("uploadBtn").addEventListener("click", startUpload);
  $("cancelUploadBtn").addEventListener("click", cancelUpload);

  // Complete modal
  $("uploadAnotherBtn").addEventListener("click", () => {
    $("completeModal").classList.add("hidden");
    resetForm();
  });
  $("closeCompleteBtn").addEventListener("click", () =>
    $("completeModal").classList.add("hidden")
  );
}

// ---------------------------------------------------------------------------
// File handling
// ---------------------------------------------------------------------------
function setBrowserFile(file) {
  state.selectedFile = file;
  state.fileSize = file.size;
  $("videoPreview").src = URL.createObjectURL(file);
  $("fileName").textContent = file.name;
  $("fileSize").textContent = formatSize(file.size);
  $("selectedFile").classList.remove("hidden");
  autofillTitle(file.name);
}

function autofillTitle(filename) {
  const titleEl = $("title");
  if (!titleEl.value.trim()) {
    titleEl.value = filename.replace(/\.[^.]+$/, "");
    $("titleCount").textContent = `${titleEl.value.length}/100`;
  }
}

function clearFile() {
  state.selectedFile = null;
  state.fileSize = 0;
  $("videoPreview").removeAttribute("src");
  $("videoPreview").load();
  $("videoInput").value = "";
  $("selectedFile").classList.add("hidden");
}

// ---------------------------------------------------------------------------
// Privacy / schedule
// ---------------------------------------------------------------------------
function selectedPrivacy() {
  return document.querySelector('input[name="privacy"]:checked').value;
}

function onPrivacyChange() {
  const p = selectedPrivacy();
  $("publicWarning").classList.toggle("hidden", p !== "public");
  $("scheduleBox").style.display = p === "scheduled" ? "block" : "none";
}

async function calculateNextSlot() {
  if (!state.authenticated) {
    toast("Sign in first to read your schedule");
    return;
  }
  $("slotStatus").textContent = "Searching for scheduled videos…";
  $("viewScheduleBtn").disabled = true;
  try {
    const res = await fetch("/api/schedule");
    const data = await res.json();
    if (!res.ok) {
      $("slotStatus").textContent = data.error || "Failed to fetch schedule";
      return;
    }
    state.scheduledCache = data;
    if (data.next_slot) {
      $("scheduleDate").value = data.next_slot.date;
      $("scheduleTime").value = data.next_slot.time;
      const basedOn = data.next_slot.based_on || "";
      $("slotStatus").textContent =
        `✓ Set to day after "${basedOn.slice(0, 40)}"`;
      $("viewScheduleBtn").disabled = false;
    } else {
      // No scheduled videos; default to tomorrow at current selection.
      const d = new Date($("scheduleDate").value + "T" + $("scheduleTime").value);
      const next = new Date(d.getTime() + 86400000);
      $("scheduleDate").value = localDateStr(next);
      $("slotStatus").textContent =
        "No scheduled videos found. Using current time + 1 day.";
      $("viewScheduleBtn").disabled = (data.scheduled || []).length === 0;
    }
  } catch (e) {
    $("slotStatus").textContent = "Error fetching schedule";
  }
}

function showScheduleModal() {
  if (!state.scheduledCache) return;
  const box = $("scheduleListBox");
  box.innerHTML = "";
  const videos = state.scheduledCache.scheduled || [];
  videos.forEach((v, i) => {
    const div = document.createElement("div");
    const isLatest = i === videos.length - 1;
    div.className = "sched-item" + (isLatest ? " latest" : "");
    div.innerHTML = `<div class="date">${v.display}</div><div>${escapeHtml(v.title)}</div>`;
    box.appendChild(div);
  });
  const ns = state.scheduledCache.next_slot;
  if (ns) {
    const div = document.createElement("div");
    div.className = "sched-item newvid";
    div.innerHTML = `<div class="date">${ns.display}</div><div>→ YOUR NEW VIDEO (this upload)</div>`;
    box.appendChild(div);
  }
  $("scheduleModal").classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------
function validate() {
  if (!state.selectedFile) {
    toast("Please select a video file.");
    return false;
  }
  const title = $("title").value.trim();
  if (!title) { toast("Please enter a title."); return false; }
  if (title.length > 100) { toast("Title must be 100 characters or less."); return false; }

  if (selectedPrivacy() === "scheduled") {
    const dt = new Date($("scheduleDate").value + "T" + $("scheduleTime").value);
    if (isNaN(dt.getTime())) { toast("Invalid schedule date/time."); return false; }
    if (dt <= new Date()) { toast("Scheduled time must be in the future."); return false; }
  }

  if (selectedPrivacy() === "public") {
    if (!confirm(
      "You are about to upload this video as PUBLIC.\n\n" +
      "This means ANYONE can see it immediately.\n\nContinue?")) {
      return false;
    }
  }
  return true;
}

function startUpload() {
  if (!state.authenticated) { toast("Please sign in first."); return; }
  if (!validate()) return;

  const fd = new FormData();
  fd.append("title", $("title").value.trim());
  fd.append("description", $("description").value);
  fd.append("tags", $("tags").value);
  fd.append("category", $("category").value);
  fd.append("privacy", selectedPrivacy());
  fd.append("madeForKids", $("madeForKids").checked ? "true" : "false");
  if (selectedPrivacy() === "scheduled") {
    fd.append("schedule_date", $("scheduleDate").value);
    fd.append("schedule_time", $("scheduleTime").value);
  }
  fd.append("video", state.selectedFile);

  // Show progress modal
  state.startTime = null;
  state.uploadId = null;
  state.staging = true;
  $("progressBar").style.width = "0%";
  $("progressPercent").textContent = "0%";
  $("progressStatus").textContent = "Uploading to server…";
  $("transferInfo").textContent = `0 B / ${formatSize(state.fileSize)}`;
  $("speedInfo").textContent = "Calculating speed…";
  $("cancelUploadBtn").disabled = false;
  $("progressTitle").textContent = "Uploading…";
  $("progressModal").classList.remove("hidden");

  // Use XMLHttpRequest so we get real upload progress and can abort during
  // the browser->server staging phase (before an upload_id exists).
  const xhr = new XMLHttpRequest();
  state.xhr = xhr;
  state.startTime = Date.now();
  xhr.open("POST", "/api/upload");

  xhr.upload.onprogress = (e) => {
    if (!state.staging || !e.lengthComputable) return;
    const pct = (e.loaded / e.total) * 100;
    $("progressBar").style.width = `${pct}%`;
    $("progressPercent").textContent = `${pct.toFixed(1)}%`;
    $("progressStatus").textContent = `Uploading to server… ${pct.toFixed(1)}%`;
    $("transferInfo").textContent =
      `${formatSize(e.loaded)} / ${formatSize(e.total)}`;
    const elapsed = (Date.now() - state.startTime) / 1000;
    if (elapsed > 0) {
      const speed = e.loaded / elapsed;
      let txt = `Speed: ${formatSize(speed)}/s`;
      if (pct < 100 && speed > 0) {
        txt += ` • ETA: ${formatTime((e.total - e.loaded) / speed)}`;
      }
      $("speedInfo").textContent = txt;
    }
  };

  xhr.onload = () => {
    state.staging = false;
    state.xhr = null;
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch (_) { data = {}; }
    if (xhr.status < 200 || xhr.status >= 300) {
      $("progressModal").classList.add("hidden");
      const fallback = xhr.status === 413
        ? "File is too large."
        : `Upload failed to start (HTTP ${xhr.status}).`;
      toast(data.error || fallback);
      return;
    }
    // Server received the file; now it uploads to YouTube. Switch to polling.
    state.uploadId = data.upload_id;
    state.fileSize = data.file_size || state.fileSize;
    state.startTime = null;
    $("progressStatus").textContent = "Sending to YouTube…";
    $("speedInfo").textContent = "Calculating speed…";
    pollStatus();
  };

  xhr.onerror = () => {
    state.staging = false;
    state.xhr = null;
    $("progressModal").classList.add("hidden");
    toast("Upload request failed");
  };

  xhr.onabort = () => {
    state.staging = false;
    state.xhr = null;
    $("progressModal").classList.add("hidden");
    toast("Upload cancelled.");
  };

  xhr.send(fd);
}

function pollStatus() {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/api/upload/${state.uploadId}/status`);
      const s = await res.json();
      updateProgress(s);
      if (s.done) {
        onUploadDone(s);
      } else {
        pollStatus();
      }
    } catch (e) {
      pollStatus();
    }
  }, 500);
}

function updateProgress(s) {
  const pct = s.progress || 0;
  $("progressBar").style.width = `${pct}%`;
  $("progressPercent").textContent = `${pct.toFixed(1)}%`;

  if (s.status === "cancelling") {
    $("progressStatus").textContent = "Cancelling…";
  } else {
    $("progressStatus").textContent = `Uploading to YouTube… ${pct.toFixed(1)}%`;
  }

  const transferred = Math.round(state.fileSize * pct / 100);
  $("transferInfo").textContent =
    `${formatSize(transferred)} / ${formatSize(state.fileSize)}`;

  if (pct > 0 && state.startTime === null) state.startTime = Date.now();
  if (state.startTime && pct > 0) {
    const elapsed = (Date.now() - state.startTime) / 1000;
    if (elapsed > 0) {
      const speed = transferred / elapsed;
      let txt = `Speed: ${formatSize(speed)}/s`;
      if (pct < 100 && speed > 0) {
        const eta = (state.fileSize - transferred) / speed;
        txt += ` • ETA: ${formatTime(eta)}`;
      } else if (pct >= 100) {
        txt += " • Complete!";
      }
      $("speedInfo").textContent = txt;
    }
  }
}

function onUploadDone(s) {
  $("progressModal").classList.add("hidden");
  if (s.status === "completed") {
    $("completeTitle").textContent = $("title").value.trim();
    if (s.publish_at) {
      const dt = new Date($("scheduleDate").value + "T" + $("scheduleTime").value);
      $("completePrivacy").innerHTML =
        `<strong>Scheduled to publish:</strong> ${dt.toLocaleString()}`;
    } else {
      $("completePrivacy").innerHTML = `<strong>Privacy:</strong> ${selectedPrivacy()}`;
    }
    $("completeUrl").href = s.video_url;
    $("completeUrl").textContent = s.video_url;
    $("studioLink").href = s.studio_url;
    $("completeModal").classList.remove("hidden");
  } else if (s.status === "cancelled") {
    toast(s.note ? `Cancelled. ${s.note}` : "Upload cancelled.");
  } else if (s.status === "failed") {
    alert("Upload failed:\n\n" + (s.error || "Unknown error"));
  }
}

async function cancelUpload() {
  if (!confirm(
    "Are you sure you want to cancel the upload?\n\n" +
    "The partially uploaded video will be deleted from YouTube.")) {
    return;
  }
  $("cancelUploadBtn").disabled = true;
  $("progressStatus").textContent = "Cancelling…";
  // Still streaming to the server: abort the request locally.
  if (state.staging && state.xhr) {
    state.xhr.abort();
    return;
  }
  // Already handed off to YouTube: ask the server to cancel + delete.
  if (state.uploadId) {
    await fetch(`/api/upload/${state.uploadId}/cancel`, { method: "POST" });
  }
}

function resetForm() {
  clearFile();
  $("title").value = "";
  $("titleCount").textContent = "0/100";
  $("description").value = "";
  $("tags").value = "";
  if (state.categories["Entertainment"]) $("category").value = "Entertainment";
  document.querySelector('input[name="privacy"][value="scheduled"]').checked = true;
  $("madeForKids").checked = false;
  populateScheduleDefaults();
  state.scheduledCache = null;
  $("viewScheduleBtn").disabled = true;
  $("slotStatus").textContent = "";
  onPrivacyChange();
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

document.addEventListener("DOMContentLoaded", init);

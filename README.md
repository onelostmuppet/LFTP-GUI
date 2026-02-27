# LFTP Download GUI

A sleek, dark-themed web GUI that allows you to browse files on your remote seedbox via SFTP and download them to your local Windows machine using the high-performance, multi-threaded `lftp` client.

---

## Project Structure

| File | Purpose |
|---|---|
| `app.py` | Flask backend — SFTP browsing (Paramiko), LFTP download queue, SSE progress |
| `templates/index.html` | Single-page HTML shell with split-panel layout |
| `static/style.css` | Dark-mode design system — glassmorphism, animated progress bars |
| `static/app.js` | Client-side file browser, live queue updates via SSE |
| `config.example.py` | Example configuration — copy to `config.py` and fill in your values |
| `requirements.txt` | `flask`, `paramiko` |

---

## How to Run

```bash
# 1. From WSL, navigate to the project
cd "/mnt/c/your_user/LFTP-GUI"

# 2. Create virtual environment (one-time)
python3 -m venv venv

# 3. Activate the venv (required every new terminal session)
source venv/bin/activate

# 4. Install lftp (one-time, required for transfers)
sudo apt install lftp

# 5. Install Python dependencies (one-time)
pip install -r requirements.txt

# 6. Start the server
python3 app.py
```

Then open **http://localhost:5000** in your Windows browser.

---

## Features

- **📂 File Browser** — Navigates `rtorrent/` with breadcrumbs, shows file types/sizes, folders first
- **⬇ Single File Download** — `lftp pget -c -n 6` (6-thread, resumable)
- **📁 Folder Mirror** — `lftp mirror --parallel=6 --continue` for directories
- **📥 Download Queue** — Enqueue multiple items, up to 5 concurrent downloads
- **📊 Live Progress** — Speed, percentage, and ETA via SSE (updates every 0.5s)
- **✕ Cancel / Clear** — Cancel in-progress or queued items; clear completed/failed; delete cancelled items and their partial local files
- **🔑 Auto Key Detection** — Supports Ed25519, ECDSA, RSA, and DSS key types
- **↻ Resume** — Partial downloads resume automatically via the `-c` flag
- **💾 Persistent Cancelled Downloads** — Cancelled downloads are saved to `state.json` and restored on server restart so they can be resumed later

All downloads are saved to `/mnt/c/your_user/Downloads` (your Windows Downloads folder).

---

## Configuration

Copy `config.example.py` to `config.py` and fill in your details:

```python
SFTP_HOST = "123.456.78.90"
SFTP_PORT = 22
SFTP_USER = "your_username"
SFTP_KEY = os.path.expanduser("~/.ssh/your_ssh_key")
REMOTE_ROOT = "/path/to/remote/downloads"
LOCAL_DIR = "/mnt/c/Users/your_user/Downloads"
THREADS = 6
MAX_CONCURRENT_DOWNLOADS = 5
```

---

## Architecture Overview

### Backend (`app.py`)
- **Tech Stack**: Python 3, Flask, Paramiko, default subprocess module.
- **Paramiko Integration**: Handles seamless directory navigation without spawning shells. Auto-supplies passwordless SSH keys.
- **Subprocess Integration**: Spawns `lftp` over a Pseudo-Terminal (PTY). This ensures `lftp` runs interactively and streams live progress bytes (`\r`) to Python, which gets regex-parsed into ETA, speed, and thread states.
- **Server-Sent Events (SSE)**: Pushes queue updates to the frontend natively, rather than having the frontend poll via AJAX.

### Frontend (`static/`, `templates/index.html`)
- **Modern UI Components**: Dark theme, glassmorphism UI elements, file-type emoji icons.
- **Client-Side Sorting**: JavaScript rapidly handles the sorting of tables locally.
- **Vanilla JS & CSS**: No bloated frameworks. Everything is implemented in native lightweight JavaScript and custom CSS logic.

---

## LFTP Command Breakdown

The application programmatically constructs `lftp` commands based on whether you are downloading a single file or a full directory.

**Single File (`pget`):**
```bash
lftp -c "set sftp:connect-program 'ssh -a -x -i ~/.ssh/your_key'; set sftp:auto-confirm yes; set net:timeout 15; set net:max-retries 3; set xfer:clobber on; open 'sftp://user@host'; cd '/remote/path'; pget -c -n 6 -O '/local/downloads' 'filename.mkv'"
```

**Directory (`mirror`):**
```bash
lftp -c "set sftp:connect-program 'ssh -a -x -i ~/.ssh/your_key'; set sftp:auto-confirm yes; set net:timeout 15; set net:max-retries 3; open 'sftp://user@host/remote/path'; mirror --continue --parallel=6 . '/local/downloads/dir'"
```

## Known Limitations and Future Features
- **Connection Pooling** — Paramiko currently opens a fresh SSH transport per browse request; pooling would speed up rapid directory navigation
- **File Size Totals** — Show total size for directories before downloading
- **Search / Filter** — Filter files by name within the current directory
- **Download History** — Persist completed download history across app restarts
- **Notifications** — Browser notification when a download completes

---

## Roadmap

### Infrastructure
- **Migrate from WSL to DietPi (Debian)** — Move the server off WSL onto a dedicated DietPi instance for always-on operation, better resource isolation, and proper service management via systemd
- **NGINX reverse proxy** — Sit NGINX in front of Flask to handle SSL termination, serve static assets efficiently, and provide a clean entry point for external access

### Remote Access
- **Cloudflare Argo Tunnel** — Expose the GUI securely to the internet without opening firewall ports, using a Cloudflare tunnel pointed at the local NGINX instance
- **Cloudflare Access with Entra ID (free tier)** — Gate the tunnel behind Cloudflare Access, using Microsoft Entra ID (formerly Azure AD free tier) as the identity provider for SSO login

### Authentication
- **HTTP Basic Auth** ✓ — Nginx basic auth gate (`/etc/nginx/.htpasswd`) protects all routes
- **TOTP / MFA** — Add time-based one-time password support as a second factor, either via Cloudflare Access policies or a lightweight in-app auth layer

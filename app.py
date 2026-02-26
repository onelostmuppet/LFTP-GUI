#!/usr/bin/env python3
"""LFTP Download GUI — Flask backend with Paramiko SFTP browsing and LFTP download management."""

import collections
import json
import logging
import os
import pty
import re
import stat as stat_mod
import subprocess
import threading
import time
import uuid
from datetime import datetime

import paramiko
from flask import Flask, Response, jsonify, render_template, request

# ── Logging setup ────────────────────────────────────────────────────────────

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lftp_gui.log")
MAX_LOG_LINES = 500  # ring buffer size for /api/logs

# Ring buffer handler — keeps last N log records for the web UI
class RingBufferHandler(logging.Handler):
    def __init__(self, capacity):
        super().__init__()
        self.buffer = collections.deque(maxlen=capacity)

    def emit(self, record):
        self.buffer.append(self.format(record))

    def get_logs(self, n=100):
        return list(self.buffer)[-n:]


log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

# File handler
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.DEBUG)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# Ring buffer handler (for web UI)
ring_handler = RingBufferHandler(MAX_LOG_LINES)
ring_handler.setFormatter(log_formatter)
ring_handler.setLevel(logging.DEBUG)

logger = logging.getLogger("lftp_gui")
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.addHandler(ring_handler)

# Quieten noisy libs
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.INFO)

# ── Configuration ────────────────────────────────────────────────────────────
from config import SFTP_HOST, SFTP_PORT, SFTP_USER, SFTP_KEY, REMOTE_ROOT, LOCAL_DIR, THREADS, MAX_CONCURRENT_DOWNLOADS

app = Flask(__name__)

# ── SFTP connection helpers ──────────────────────────────────────────────────

def _get_sftp():
    """Create a fresh Paramiko SFTP connection."""
    key = None
    for key_cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            key = key_cls.from_private_key_file(SFTP_KEY)
            logger.debug(f"Loaded SSH key with {key_cls.__name__}")
            break
        except Exception:
            continue
    if key is None:
        logger.error(f"Could not load SSH key from {SFTP_KEY}")
        raise ValueError(f"Could not load SSH key from {SFTP_KEY}")
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(username=SFTP_USER, pkey=key)
    sftp = paramiko.SFTPClient.from_transport(transport)
    logger.info(f"SFTP connected to {SFTP_HOST}")
    return sftp, transport


def _human_size(nbytes):
    """Format byte count into a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(nbytes) < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def _get_local_size(path):
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total

def _lftp_quote(s):
    """Wrap a string in single quotes, escaping any embedded single quotes for LFTP."""
    return "'" + s.replace("'", "'\\''") + "'"


def _format_duration(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


# ── Persistent state helpers ─────────────────────────────────────────────────

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


def _read_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_state(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)


# ── Download queue ───────────────────────────────────────────────────────────

class DownloadItem:
    def __init__(self, remote_path, name, is_dir):
        self.id = str(uuid.uuid4())[:8]
        self.remote_path = remote_path
        self.name = name
        self.is_dir = is_dir
        self.status = "queued"          # queued | downloading | completed | failed | cancelled
        self.progress = ""              # raw progress string from LFTP
        self.speed = ""
        self.eta = ""
        self.threads = 0
        self.percent = 0
        self.error = ""
        self.process = None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "remote_path": self.remote_path,
            "is_dir": self.is_dir,
            "status": self.status,
            "progress": self.progress,
            "speed": self.speed,
            "eta": self.eta,
            "threads": self.threads,
            "percent": self.percent,
            "error": self.error,
        }


class DownloadManager:
    def __init__(self):
        self.queue: list[DownloadItem] = []
        self.lock = threading.Lock()
        self._version = 0           # bumped on any queue change for SSE
        self._restore_cancelled()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _restore_cancelled(self):
        """Reload cancelled downloads from state.json so they survive restarts."""
        state = _read_state()
        for entry in state.get("cancelled_downloads", []):
            item = DownloadItem(entry["remote_path"], entry["name"], entry["is_dir"])
            item.id = entry["id"]
            item.status = "cancelled"
            self.queue.append(item)
        if self.queue:
            logger.info(f"Restored {len(self.queue)} cancelled download(s) from state")

    def _save_cancelled(self):
        """Persist currently cancelled items to state.json. Must be called with self.lock held."""
        entries = [
            {"id": i.id, "remote_path": i.remote_path, "name": i.name, "is_dir": i.is_dir}
            for i in self.queue if i.status == "cancelled"
        ]
        state = _read_state()
        state["cancelled_downloads"] = entries
        _write_state(state)

    def add(self, remote_path, name, is_dir):
        item = DownloadItem(remote_path, name, is_dir)
        with self.lock:
            self.queue.append(item)
            self._version += 1
        return item.id

    def cancel(self, item_id):
        with self.lock:
            for item in self.queue:
                if item.id == item_id:
                    if item.status == "queued":
                        item.status = "cancelled"
                    elif item.status == "downloading" and item.process:
                        item.process.terminate()
                        item.status = "cancelled"
                    self._version += 1
                    self._save_cancelled()
                    return True
        return False

    def resume(self, item_id):
        with self.lock:
            for item in self.queue:
                if item.id == item_id and item.status == "cancelled":
                    item.status = "queued"
                    item.progress = ""
                    item.speed = ""
                    item.eta = ""
                    item.threads = 0
                    item.error = ""
                    item.process = None
                    self._version += 1
                    self._save_cancelled()
                    return True
        return False

    def clear_finished(self):
        with self.lock:
            self.queue = [i for i in self.queue if i.status in ("queued", "downloading")]
            self._version += 1
            self._save_cancelled()

    def get_state(self):
        with self.lock:
            return [i.to_dict() for i in self.queue], self._version

    def _run(self):
        """Worker loop: spawn up to MAX_CONCURRENT_DOWNLOADS concurrent download threads."""
        while True:
            with self.lock:
                active = sum(1 for i in self.queue if i.status == "downloading")
                item = None
                if active < MAX_CONCURRENT_DOWNLOADS:
                    for i in self.queue:
                        if i.status == "queued":
                            i.status = "downloading"
                            item = i
                            self._version += 1
                            break
            if item is not None:
                t = threading.Thread(target=self._download, args=(item,), daemon=True)
                t.start()
            else:
                time.sleep(0.5)

    def _download(self, item: DownloadItem):
        """Run LFTP for one item and parse progress."""
        start_time = time.time()
        try:
            # Connect to root URL for directory mirroring (dummy password 'x' prevents LFTP interactive prompt)
            sftp_root_url = f"sftp://{SFTP_USER}:x@{SFTP_HOST}"
            # Refined SSH command to force our key and disable all prompts/hangs
            ssh_cmd = f"ssh -a -x -i {SFTP_KEY} -o IdentitiesOnly=yes -o BatchMode=yes"
            
            # Common LFTP settings to suppress fingerprint prompts and handle timeouts
            lftp_base_settings = (
                f"set sftp:connect-program '{ssh_cmd}'; "
                f"set sftp:auto-confirm yes; "
                f"set net:timeout 15; "
                f"set net:max-retries 3; "
                # f"debug 9; " # Uncomment for low-level connection debugging
            )

            # Ensure local directory exists
            os.makedirs(LOCAL_DIR, exist_ok=True)

            if item.is_dir:
                local_dest = os.path.join(LOCAL_DIR, item.name)
                lftp_commands = (
                    lftp_base_settings +
                    f"open {_lftp_quote(sftp_root_url + item.remote_path)}; "
                    f"mirror --continue --parallel={THREADS} . {_lftp_quote(local_dest)}"
                )
            else:
                lftp_commands = (
                    lftp_base_settings +
                    f"set xfer:clobber on; "
                    f"open {_lftp_quote(sftp_root_url)}; "
                    f"cd {_lftp_quote(os.path.dirname(item.remote_path))}; "
                    f"pget -c -n {THREADS} -O {_lftp_quote(LOCAL_DIR)} {_lftp_quote(os.path.basename(item.remote_path))}"
                )

            logger.info(f"[{item.id}] Starting download: {item.name}")
            logger.debug(f"[{item.id}] LFTP command: lftp -c {lftp_commands}")

            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(
                ["lftp", "-c", lftp_commands],
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True
            )
            os.close(slave_fd)
            item.process = proc

            stderr_lines = []
            line_acc = []
            
            # Read from the PTY master until the process closes it
            try:
                while True:
                    try:
                        char_bytes = os.read(master_fd, 1)
                    except OSError:
                        # Raised when the child process closes the PTY (EIO) on Linux
                        break
                        
                    if not char_bytes:
                        break
                        
                    char = char_bytes.decode('utf-8', errors='replace')
                    
                    if char in ('\n', '\r'):
                        line = "".join(line_acc).strip()
                        if line:
                            # Strip terminal ANSI escape codes from progress bars
                            clean_line = re.sub(r'\x1b\[.*?m', '', line)
                            clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', clean_line)
                            
                            # Filter out high-verbosity packet logs
                            is_packet_log = clean_line.startswith(('---', '-->', '<--'))
                            
                            # Log and parse
                            if not is_packet_log:
                                # logger.info(f"[{item.id}] LFTP: {clean_line}")
                                pass

                            self._parse_progress(item, clean_line)
                            
                            # Keep a small buffer for error reporting
                            stderr_lines.append(clean_line)
                            if len(stderr_lines) > 10:
                                stderr_lines.pop(0)
                                
                        line_acc = []
                    else:
                        line_acc.append(char)
            finally:
                os.close(master_fd)

            proc.wait()

            with self.lock:
                if item.status == "cancelled":
                    logger.info(f"[{item.id}] Download cancelled: {item.name}")
                elif proc.returncode == 0:
                    item.status = "completed"
                    item.percent = 100
                    
                    duration_s = time.time() - start_time
                    local_dest = os.path.join(LOCAL_DIR, item.name)
                    size_bytes = _get_local_size(local_dest)
                    
                    if duration_s > 0:
                        speed_mbps = (size_bytes / duration_s) / (1024 * 1024)
                    else:
                        speed_mbps = 0.0
                        
                    item.speed = f"{_human_size(size_bytes)}  ·  {_format_duration(duration_s)}  ·  {speed_mbps:.1f} MB/s"
                    item.eta = ""
                    
                    logger.info(f"[{item.id}] Download completed: {item.name}")
                else:
                    item.status = "failed"
                    stderr_msg = "\n".join(stderr_lines[-5:]) if stderr_lines else ""
                    item.error = stderr_msg or f"LFTP exited with code {proc.returncode}"
                    logger.error(f"[{item.id}] Download FAILED (code {proc.returncode}): {item.name}")
                    for line in stderr_lines:
                        logger.error(f"[{item.id}]   {line}")
                self._version += 1

        except Exception as e:
            logger.exception(f"[{item.id}] Exception during download of {item.name}")
            with self.lock:
                item.status = "failed"
                item.error = str(e)
                self._version += 1

    def _parse_progress(self, item: DownloadItem, line: str):
        """Parse LFTP output lines for progress info."""
        with self.lock:
            item.progress = line
            self._version += 1

            # pget progress:  `12345678 bytes transferred (45%)`  or speed lines
            pct_match = re.search(r'(\d+)%', line)
            if pct_match:
                item.percent = int(pct_match.group(1))

            # Match speeds like "1.25M/s", "500K/s", "12 MB/s"
            speed_match = re.search(r'([\d.]+\s*[a-zA-Z]*/s)', line, re.IGNORECASE)
            if speed_match:
                item.speed = speed_match.group(1)

            eta_match = re.search(r'eta:\s*(\S+)', line, re.IGNORECASE)
            if not eta_match:
                eta_match = re.search(r'(\d+[dhms](?:\s*\d+[dhms])*)', line)
            if eta_match:
                item.eta = eta_match.group(1)
                
            # LFTP pget shows a visual bar of 'o' (done) and '.' (pending) chars.
            # Each distinct 'o' group = one active thread segment.
            # e.g. "ooo..........oo...........oo...........oo...........oo...........oo............" → 6 threads
            bar_match = re.fullmatch(r'[o.]+', line)
            if bar_match and len(line) > 10:
                item.threads = len(re.findall(r'o+', line))


manager = DownloadManager()


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/browse")
def browse():
    """List files and directories at the given remote path."""
    rel_path = request.args.get("path", "/")
    abs_path = os.path.normpath(REMOTE_ROOT + "/" + rel_path).replace("\\", "/")

    # Safety: prevent escaping the root
    if not abs_path.startswith(REMOTE_ROOT):
        return jsonify({"error": "Path outside root"}), 400

    try:
        sftp, transport = _get_sftp()
        entries = []
        for attr in sftp.listdir_attr(abs_path):
            is_dir = stat_mod.S_ISDIR(attr.st_mode) if attr.st_mode else False
            entries.append({
                "name": attr.filename,
                "is_dir": is_dir,
                "size": attr.st_size if not is_dir else None,
                "size_human": _human_size(attr.st_size) if not is_dir else None,
                "mtime": attr.st_mtime,
            })
        transport.close()

        # Sort: folders first, then alpha
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        logger.debug(f"Browse {abs_path}: {len(entries)} entries")
        return jsonify({"path": rel_path, "entries": entries})

    except FileNotFoundError:
        logger.warning(f"Browse path not found: {abs_path}")
        return jsonify({"error": "Path not found"}), 404
    except Exception as e:
        logger.exception(f"Browse error at {abs_path}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/download", methods=["POST"])
def download():
    """Add a file or directory to the download queue."""
    data = request.get_json()
    rel_path = data.get("path", "")
    name = data.get("name", os.path.basename(rel_path))
    is_dir = data.get("is_dir", False)
    abs_path = os.path.normpath(REMOTE_ROOT + "/" + rel_path).replace("\\", "/")

    if not abs_path.startswith(REMOTE_ROOT):
        return jsonify({"error": "Path outside root"}), 400

    item_id = manager.add(abs_path, name, is_dir)
    return jsonify({"id": item_id, "queued": True})


@app.route("/api/queue")
def queue_stream():
    """SSE stream of the download queue state."""
    def generate():
        last_version = -1
        while True:
            state, version = manager.get_state()
            if version != last_version:
                last_version = version
                yield f"data: {json.dumps(state)}\n\n"
            time.sleep(0.5)
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/cancel/<item_id>", methods=["POST"])
def cancel(item_id):
    ok = manager.cancel(item_id)
    return jsonify({"cancelled": ok})


@app.route("/api/resume/<item_id>", methods=["POST"])
def resume(item_id):
    ok = manager.resume(item_id)
    return jsonify({"resumed": ok})


@app.route("/api/clear", methods=["POST"])
def clear():
    manager.clear_finished()
    return jsonify({"cleared": True})


@app.route("/api/last-path", methods=["GET"])
def get_last_path():
    state = _read_state()
    return jsonify({"path": state.get("last_path", "/")})


@app.route("/api/last-path", methods=["POST"])
def set_last_path():
    data = request.get_json()
    path = data.get("path", "/")
    state = _read_state()
    state["last_path"] = path
    _write_state(state)
    return jsonify({"ok": True})


@app.route("/api/logs")
def logs():
    """Return recent log entries for the web UI."""
    count = request.args.get("n", 100, type=int)
    lines = ring_handler.get_logs(min(count, MAX_LOG_LINES))
    return jsonify({"logs": lines})


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(LOCAL_DIR, exist_ok=True)
    logger.info("═" * 50)
    logger.info("LFTP Download GUI starting")
    logger.info(f"  Remote: {SFTP_USER}@{SFTP_HOST}:{REMOTE_ROOT}")
    logger.info(f"  Local:  {LOCAL_DIR}")
    logger.info(f"  Threads: {THREADS}")
    logger.info(f"  Log file: {LOG_FILE}")
    logger.info("═" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

import os

SFTP_HOST = "203.0.113.1"                         # seedbox IP or hostname
SFTP_PORT = 22
SFTP_USER = "your_username"
SFTP_KEY = "/home/dietpi/.ssh/your_seedbox_key"   # absolute path on DietPi
REMOTE_ROOT = "/homeXX/your_username/downloads/rtorrent"
LOCAL_DIR = "/mnt/NAS/downloads"  # fallback if no DOWNLOAD_MAPPINGS rule matches
THREADS = 6
MAX_CONCURRENT_DOWNLOADS = 5
APP_PORT = 5000

# DOWNLOAD_MAPPINGS: list of (regex_pattern, local_destination) tuples.
# Patterns are matched case-insensitively against the full remote path.
# First match wins. If nothing matches, LOCAL_DIR is used as fallback.
DOWNLOAD_MAPPINGS = [
    (r"#?movies?",     "/mnt/NAS/movies"),
    (r"#?tv",          "/mnt/NAS/tv"),
    (r"games?",        "/mnt/NAS/games"),
    (r"#?audiobooks?", "/mnt/NAS/audiobooks"),
    (r"#?sports?",     "/mnt/NAS/sport"),
]

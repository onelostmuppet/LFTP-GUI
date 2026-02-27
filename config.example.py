import os

SFTP_HOST = "5.79.112.170"
SFTP_PORT = 22
SFTP_USER = "boxofseeds"
SFTP_KEY = "/home/dietpi/.ssh/seedhost_key_lftp_1"  # absolute path on DietPi
REMOTE_ROOT = "/home15/boxofseeds/downloads/rtorrent"
LOCAL_DIR = "/mnt/BRAT6TB/downloads"  # fallback if no DOWNLOAD_MAPPINGS rule matches
THREADS = 6
MAX_CONCURRENT_DOWNLOADS = 5

# DOWNLOAD_MAPPINGS: list of (regex_pattern, local_destination) tuples.
# Patterns are matched case-insensitively against the full remote path.
# First match wins. If nothing matches, LOCAL_DIR is used as fallback.
DOWNLOAD_MAPPINGS = [
    (r"#?movies?",     "/mnt/BRAT6TB/#newmovies"),
    (r"#?tv",          "/mnt/BRAT6TB/#newtv"),
    (r"games?",        "/mnt/BRAT6TB/Games"),
    (r"#?audiobooks?", "/mnt/BRAT6TB/audiobooks"),
    (r"#?sports?",     "/mnt/BRAT6TB/#sport"),
]

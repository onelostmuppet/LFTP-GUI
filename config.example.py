import os

SFTP_HOST = "123.456.78.90"
SFTP_PORT = 22
SFTP_USER = "your_username"
SFTP_KEY = os.path.expanduser("~/.ssh/your_ssh_key")
REMOTE_ROOT = "/path/to/remote/downloads"
LOCAL_DIR = "/mnt/c/Users/your_user/Downloads"
THREADS = 6
MAX_CONCURRENT_DOWNLOADS = 5

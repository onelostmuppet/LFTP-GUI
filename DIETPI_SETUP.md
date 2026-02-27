# LFTP-GUI DietPi Setup Guide

Setup guide for running LFTP-GUI on DietPi at `https://lftpgui.example.com`.

Adapted from the ABS DietPi HTTPS setup (`ABS DietPi/Dietpi ABS https setup & seedbox audiobook sync.md`).

---

## DietPi Infrastructure (already in place from ABS setup)

| Item | Value |
|---|---|
| DietPi LAN IP | YOUR_DIETPI_IP |
| Public IP | YOUR_PUBLIC_IP |
| Router port 80 → | YOUR_DIETPI_IP:80 |
| Router port 443 → | YOUR_DIETPI_IP:443 |
| Nginx | Installed |
| Certbot | Installed |
| Existing nginx site | `audiobookshelf` (audiobookshelf.example.com) |

---

## SSH Config (WSL `~/.ssh/config`)

The existing `dietpi` host entry connects as **root**. Add a second entry to connect as **dietpi** user:

```
Host dietpi-root
    HostName YOUR_DIETPI_IP
    User root
    IdentityFile ~/.ssh/dietpi_root_key
    IdentitiesOnly yes
    ControlMaster auto
    ControlPath ~/.ssh/control-%r@%h:%p
    ControlPersist 10m

Host dietpi-user
    HostName YOUR_DIETPI_IP
    User dietpi
    IdentityFile ~/.ssh/dietpi_user_key
    IdentitiesOnly yes

Host seedbox
    HostName YOUR_SEEDBOX_HOST
    Port 22
    User YOUR_SEEDBOX_USER
    IdentityFile ~/.ssh/YOUR_SEEDBOX_KEY
    IdentitiesOnly yes
    ControlMaster auto
    ControlPath ~/.ssh/control-%r@%h:%p
    ControlPersist 10m
```

Test:
```bash
ssh dietpi-user "whoami"   # should print: dietpi
```

---

## 1. DNS Record

At your DNS provider, add an A record:

```
Type:      A
Subdomain: lftpgui
IP:        YOUR_PUBLIC_IP
Domain:    example.com
Result:    lftpgui.example.com
```

Allow up to 30 minutes for propagation. Verify:
```bash
nslookup lftpgui.example.com   # should return YOUR_PUBLIC_IP
```

---

## 2. Copy Seedbox SSH Key to DietPi

The app authenticates to the seedbox using `YOUR_SEEDBOX_KEY`.
Copy it from WSL to the DietPi's `dietpi` user:

```bash
# From WSL — copy key to DietPi
scp ~/.ssh/YOUR_SEEDBOX_KEY dietpi-root:/home/dietpi/.ssh/YOUR_SEEDBOX_KEY

# Set correct ownership and permissions on DietPi
ssh dietpi-root "chown dietpi:dietpi /home/dietpi/.ssh/YOUR_SEEDBOX_KEY && chmod 600 /home/dietpi/.ssh/YOUR_SEEDBOX_KEY"

# Verify
ssh dietpi-user "ls -la ~/.ssh/YOUR_SEEDBOX_KEY"
# Expected: -rw------- 1 dietpi dietpi ...
```

---

## 3. Install git, lftp and Python on DietPi

SSH into DietPi as root:
```bash
ssh dietpi-root
```

Install required packages:
```bash
apt-get update
apt-get install -y git lftp python3 python3-venv python3-pip
```

Verify the packages are available:
```bash
which git        # /usr/bin/git
git --version

which lftp       # /usr/bin/lftp
lftp --version
```

---

## 4. Clone Repo and Set Up Virtual Environment

```bash
# Ensure the target directory exists (e.g. USB drive mount or /opt)
ls /path/to/

# Clone the repository (dietpi branch)
git clone https://github.com/onelostmuppet/LFTP-GUI.git \
    /path/to/lftp-gui

cd /path/to/lftp-gui

# Configure git to trust this directory (required if cloning as root)
# This prevents "detected dubious ownership" errors when using git later
git config --global --add safe.directory /path/to/lftp-gui

# Switch to the DietPi branch
git checkout dietpi

# Create virtual environment and install dependencies
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# Give dietpi user ownership of the whole directory
chown -R dietpi:dietpi /path/to/lftp-gui
```

---

## 5. Configure the App

```bash
cd /path/to/lftp-gui

# Create config.py from the example template
cp config.example.py config.py

# Edit and verify all values
nano config.py
```

Key values to check in `config.py`:
- `SFTP_HOST` — seedbox IP or hostname
- `SFTP_USER` — seedbox username
- `SFTP_KEY` — `/home/dietpi/.ssh/YOUR_SEEDBOX_KEY`
- `REMOTE_ROOT` — remote downloads path on seedbox
- `DOWNLOAD_MAPPINGS` — regex rules for routing to NAS folders

Test the config by running the app manually as `dietpi` user before enabling the service:
```bash
su - dietpi -s /bin/bash -c "cd /path/to/lftp-gui && venv/bin/python3 app.py"
# Look for "LFTP Download GUI starting" in output
# Press Ctrl+C after confirming it starts without errors
```

---

## 6. Systemd Service (autostart + autorestart)

Edit `lftp-gui.service` and replace `/path/to/lftp-gui` with your actual install path,
then copy it to systemd:

```bash
# Copy service file
cp /path/to/lftp-gui/lftp-gui.service /etc/systemd/system/

# Reload systemd, enable on boot, and start now
systemctl daemon-reload
systemctl enable lftp-gui
systemctl start lftp-gui

# Verify it's running
systemctl status lftp-gui

# View live logs
journalctl -u lftp-gui -f
```

---

## 7. Nginx Site Configuration

```bash
# Copy and customise the nginx template
cp /path/to/lftp-gui/nginx/lftpgui.example.com \
   /etc/nginx/sites-available/lftpgui.example.com

# Replace example.com with your actual domain in the config
sed -i 's/lftpgui\.example\.com/lftpgui.YOUR_DOMAIN/g' \
    /etc/nginx/sites-available/lftpgui.example.com

# Rename the file to match your domain
mv /etc/nginx/sites-available/lftpgui.example.com \
   /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN

# Enable the site
ln -s /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN \
      /etc/nginx/sites-enabled/lftpgui.YOUR_DOMAIN
```

**Do not reload nginx yet** — the SSL certificate doesn't exist yet (step 8).

> **HTTP/2 note:** The template uses the `http2 on;` standalone directive (requires nginx ≥ 1.25.1).
> Do **not** use the older `listen 443 ssl http2;` syntax — it is deprecated and will generate warnings.
> Verify your version with `nginx -v`.

---

## 7a. Basic Authentication (htpasswd)

The nginx config requires a password file at `/etc/nginx/.htpasswd`. Create it before nginx is reloaded in step 8.

```bash
# Install apache2-utils if not already present
apt-get install -y apache2-utils

# Create the file and add a user (-c creates the file)
htpasswd -c /etc/nginx/.htpasswd YOUR_USERNAME
# Enter and confirm a password when prompted

# To add more users later (omit -c to avoid overwriting):
# htpasswd /etc/nginx/.htpasswd ANOTHER_USER
```

---

## 8. SSL Certificate via Certbot

DNS must be propagated before this step (verify with `nslookup lftpgui.example.com`).

> **Bootstrap problem:** The nginx config references the cert before it exists, so
> `nginx -t` fails, which blocks `certbot --nginx`. Work around this by temporarily
> stripping the config down to the HTTP-only block to let nginx start, then using
> the webroot challenge.

```bash
# 1. Back up the full config and replace it with HTTP-only (lines 1–20)
cp /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN \
   /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN.bak
sed -n '1,20p' /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN.bak \
   > /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN

# 2. Start nginx with the HTTP-only config
nginx -t && systemctl reload nginx

# 3. Obtain the certificate via webroot challenge
certbot certonly --webroot -w /var/www/html -d lftpgui.YOUR_DOMAIN

# 4. Restore the full config
cp /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN.bak \
   /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN

# 5. Reload nginx with full HTTPS + HTTP/2 config
nginx -t && systemctl reload nginx
```

Verify auto-renewal timer is still active:
```bash
systemctl status certbot.timer
certbot renew --dry-run
```

---

## 9. Verification

```bash
# App is listening on the correct port
ss -tlnp | grep YOUR_PORT

# Local access works
curl -I http://127.0.0.1:YOUR_PORT

# HTTPS access works — unauthenticated request should return 401
curl -I https://lftpgui.YOUR_DOMAIN   # expect HTTP/2 401 WWW-Authenticate: Basic realm="LFTP-GUI"

# Authenticated request should return 200
curl -u YOUR_USERNAME:YOUR_PASSWORD -I https://lftpgui.YOUR_DOMAIN   # expect HTTP/2 200

# Check nginx logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# Check app logs
journalctl -u lftp-gui -f
```

In the browser:
1. Open `https://lftpgui.YOUR_DOMAIN`
2. File browser should load and show seedbox directories
3. Queue a test download and confirm the file lands in the expected NAS folder
4. Check `journalctl -u lftp-gui` for the mapping log line:
   `Mapped '.../...#tv...' → '/mnt/NAS/tv' (pattern: #?tv)`

Reboot test:
```bash
reboot
# After reboot:
systemctl status lftp-gui   # should be active (running)
```

---

## Download Path Mappings

The app routes downloads to NAS subfolders based on the remote path. Rules (first match wins):

| Remote path contains | Downloads to |
|---|---|
| `#movies` or `movies` | `/mnt/NAS/movies` |
| `#tv` or `tv` | `/mnt/NAS/tv` |
| `#games` or `games` | `/mnt/NAS/games` |
| `#audiobooks` or `audiobooks` | `/mnt/NAS/audiobooks` |
| `#sport` or `sports` | `/mnt/NAS/sport` |
| *(no match)* | `/mnt/NAS/downloads` (fallback) |

To adjust rules, edit `DOWNLOAD_MAPPINGS` in `config.py` (regex, case-insensitive).

---

## Maintenance Reference

### LFTP-GUI Service
```bash
systemctl status lftp-gui
systemctl restart lftp-gui
systemctl stop lftp-gui
journalctl -u lftp-gui -f                    # live logs
journalctl -u lftp-gui --since "1 hour ago"  # recent logs
```

### App Updates
```bash
cd /path/to/lftp-gui
git pull origin dietpi
systemctl restart lftp-gui
```

> **Git ownership error?** If you see `fatal: detected dubious ownership in repository`,
> run: `git config --global --add safe.directory /path/to/lftp-gui`
> This happens when the repo was cloned as root but is being accessed as a different user.

### Nginx
```bash
nginx -t                              # test config syntax
systemctl reload nginx                # reload without downtime
systemctl restart nginx
systemctl status nginx
tail -f /var/log/nginx/error.log
nano /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN
```

### SSL Certificates
```bash
certbot certificates                  # list all certs and expiry dates
certbot renew --dry-run               # test renewal without making changes
certbot renew --force-renewal         # force immediate renewal
systemctl reload nginx                # reload after manual renewal
systemctl status certbot.timer        # check auto-renewal timer
```

### Troubleshooting
```bash
# App not starting
journalctl -u lftp-gui -xe            # full error details
su - dietpi -s /bin/bash -c "cd /path/to/lftp-gui && venv/bin/python3 app.py"

# Nginx config error
nginx -t
tail -f /var/log/nginx/error.log

# Can't reach the domain
ss -tlnp | grep YOUR_PORT                 # verify app is listening
curl -I http://127.0.0.1:YOUR_PORT        # test app directly
curl -I https://lftpgui.YOUR_DOMAIN   # test full path
certbot certificates                  # verify cert isn't expired

# SSH key issues
ssh dietpi-user "ls -la ~/.ssh/"      # check key permissions
ssh -v dietpi-user                    # verbose SSH debug
```

---

## Network Configuration Reference

### Router Port Forwards
```
Port 80  → YOUR_DIETPI_IP:80   (HTTP — certbot renewal + redirect to HTTPS)
Port 443 → YOUR_DIETPI_IP:443  (HTTPS — nginx serves all virtual hosts)
```

### DNS Records
```
A  audiobookshelf  → YOUR_PUBLIC_IP
A  lftpgui         → YOUR_PUBLIC_IP
```

### Security Model
- LFTP-GUI Flask app is bound to `127.0.0.1:YOUR_PORT` (localhost only)
- All external access goes through nginx on port 443 (HTTPS)
- No direct port YOUR_PORT access from LAN or internet
- HTTP basic auth required for all routes (credentials stored in `/etc/nginx/.htpasswd`)
- SSH key for seedbox is passwordless (required for background LFTP operations)

---

## Troubleshooting: Antigravity Server "Crash" on DietPi

If Antigravity (VS Code) reports that the server crashed unexpectedly during the "Resolving ssh remote" stage, it is likely due to the initialization script failing to create a lock file.

### Root Cause
The server script tries to write to `~/.antigravity-server/.installation_lock` before the `.antigravity-server` directory itself exists. This causes a "Bad file descriptor" error in the shell script, which VS Code interprets as a crash.

### Fix
Manually initialize the environment on the DietPi:

1. **Create the directory and lock file**:
   ```bash
   ssh dietpi-root "mkdir -p /home/dietpi/.antigravity-server && touch /home/dietpi/.antigravity-server/.installation_lock && chown -R dietpi:dietpi /home/dietpi/.antigravity-server && chmod 755 /home/dietpi/.antigravity-server && chmod 600 /home/dietpi/.antigravity-server/.installation_lock"
   ```

2. **Install ARM-specific dependencies**:
   Some native modules require `libatomic1` on ARM platforms:
   ```bash
   ssh dietpi-root "apt-get update && apt-get install -y libatomic1"
   ```

3. **Restart VS Code** and try connecting again.

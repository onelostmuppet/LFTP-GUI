# LFTP-GUI DietPi Setup Guide

Setup guide for running LFTP-GUI on DietPi at `https://lftpgui.brynley.au`.

Adapted from the ABS DietPi HTTPS setup (`ABS DietPi/Dietpi ABS https setup & seedbox audiobook sync.md`).

---

## DietPi Infrastructure (already in place from ABS setup)

| Item | Value |
|---|---|
| DietPi LAN IP | 192.168.1.100 |
| Public IP | 115.69.2.169 |
| Router port 80 → | 192.168.1.100:80 |
| Router port 443 → | 192.168.1.100:443 |
| Nginx | Installed |
| Certbot | Installed |
| Existing nginx site | `audiobookshelf` (abs.brynley.au) |

---

## SSH Config (WSL `~/.ssh/config`)

The existing `dietpi` host entry connects as **root**. Add a second entry to connect as **dietpi** user:

```
Host dietpi-root
    HostName 192.168.1.100
    User root
    IdentityFile ~/.ssh/dietpi_root_key
    IdentitiesOnly yes
    ControlMaster auto
    ControlPath ~/.ssh/control-%r@%h:%p
    ControlPersist 10m

Host dietpi-user
    HostName 192.168.1.100
    User dietpi
    IdentityFile ~/.ssh/dietpi_user_key
    IdentitiesOnly yes

Host boxofseeds
    HostName horn.seedhost.eu
    Port 22
    User boxofseeds
    IdentityFile ~/.ssh/brynley_key
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

At **iwantmyname.com**, add a second A record alongside the existing `abs` entry:

```
Type:      A
Subdomain: lftpgui
IP:        115.69.2.169
Domain:    brynley.au
Result:    lftpgui.brynley.au
```

Allow up to 30 minutes for propagation. Verify:
```bash
nslookup lftpgui.brynley.au   # should return 115.69.2.169
```

---

## 2. Copy Seedbox SSH Key to DietPi

The app authenticates to the seedbox using `seedhost_key_lftp_1`.
Copy it from WSL to the DietPi's `dietpi` user:

```bash
# From WSL — copy key to DietPi
scp ~/.ssh/seedhost_key_lftp_1 dietpi-root:/home/dietpi/.ssh/seedhost_key_lftp_1

# Set correct ownership and permissions on DietPi
ssh dietpi-root "chown dietpi:dietpi /home/dietpi/.ssh/seedhost_key_lftp_1 && chmod 600 /home/dietpi/.ssh/seedhost_key_lftp_1"

# Verify
ssh dietpi-user "ls -la ~/.ssh/seedhost_key_lftp_1"
# Expected: -rw------- 1 dietpi dietpi ...
```

---

## 3. Install lftp and Python on DietPi

SSH into DietPi as root:
```bash
ssh dietpi-root
```

Install required packages:
```bash
apt-get update
apt-get install -y lftp python3 python3-venv python3-pip
```

Verify lftp is available:
```bash
which lftp       # /usr/bin/lftp
lftp --version
```

---

## 4. Clone Repo and Set Up Virtual Environment

```bash
# Ensure USB drive is mounted
ls /mnt/256GBUSB3/dietpi_userdata/

# Clone the repository (dietpi branch)
git clone https://github.com/onelostmuppet/LFTP-GUI.git \
    /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI

cd /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI

# Switch to the DietPi branch
git checkout dietpi

# Create virtual environment and install dependencies
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# Give dietpi user ownership of the whole directory
chown -R dietpi:dietpi /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI
```

---

## 5. Configure the App

```bash
cd /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI

# Create config.py from the DietPi template
cp config.example.py config.py

# Edit and verify all values
nano config.py
```

Key values to check in `config.py`:
- `SFTP_HOST` — seedbox IP
- `SFTP_USER` — seedbox username
- `SFTP_KEY` — `/home/dietpi/.ssh/seedhost_key_lftp_1`
- `REMOTE_ROOT` — remote downloads path on seedbox
- `DOWNLOAD_MAPPINGS` — regex rules for routing to NAS folders

Test the config by running the app manually as `dietpi` user before enabling the service:
```bash
su - dietpi -s /bin/bash -c "cd /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI && venv/bin/python3 app.py"
# Look for "LFTP Download GUI starting" in output
# Press Ctrl+C after confirming it starts without errors
```

---

## 6. Systemd Service (autostart + autorestart)

```bash
# Copy service file
cp /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI/lftp-gui.service /etc/systemd/system/

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
# Copy site config
cp /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI/nginx/lftpgui.brynley.au \
   /etc/nginx/sites-available/lftpgui.brynley.au

# Enable the site
ln -s /etc/nginx/sites-available/lftpgui.brynley.au \
      /etc/nginx/sites-enabled/lftpgui.brynley.au

# Test config syntax — must pass before proceeding
nginx -t
```

**Do not reload nginx yet** — the SSL certificate doesn't exist yet (step 8).

---

## 8. SSL Certificate via Certbot

DNS must be propagated before this step (verify with `nslookup lftpgui.brynley.au`).

```bash
# Obtain certificate (reuses the existing certbot account from ABS setup)
certbot certonly --nginx -d lftpgui.brynley.au
```

Once the certificate is issued, reload nginx to activate HTTPS:
```bash
nginx -t && systemctl reload nginx
```

Verify auto-renewal timer is still active (shared with ABS cert):
```bash
systemctl status certbot.timer
certbot renew --dry-run
```

---

## 9. Verification

```bash
# App is listening on the correct port
ss -tlnp | grep 57423

# Local access works
curl -I http://127.0.0.1:57423

# HTTPS access works (run from any machine)
curl -I https://lftpgui.brynley.au   # expect HTTP/2 200

# Check nginx logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# Check app logs
journalctl -u lftp-gui -f
```

In the browser:
1. Open `https://lftpgui.brynley.au`
2. File browser should load and show seedbox directories
3. Queue a download from `#tv` — confirm file lands in `/mnt/BRAT6TB/#newtv`
4. Check `journalctl -u lftp-gui` for the mapping log line:
   `Mapped '.../...#tv...' → '/mnt/BRAT6TB/#newtv' (pattern: #?tv)`

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
| `#movies` or `movies` | `/mnt/BRAT6TB/#newmovies` |
| `#tv` or `tv` | `/mnt/BRAT6TB/#newtv` |
| `games` | `/mnt/BRAT6TB/Games` |
| `#audiobooks` or `audiobooks` | `/mnt/BRAT6TB/audiobooks` |
| `#sport` or `sports` | `/mnt/BRAT6TB/#sport` |
| *(no match)* | `/mnt/BRAT6TB/downloads` (fallback) |

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
cd /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI
git pull origin dietpi
systemctl restart lftp-gui
```

### Nginx
```bash
nginx -t                              # test config syntax
systemctl reload nginx                # reload without downtime
systemctl restart nginx
systemctl status nginx
tail -f /var/log/nginx/error.log
nano /etc/nginx/sites-available/lftpgui.brynley.au
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
su - dietpi -s /bin/bash -c "cd /mnt/256GBUSB3/dietpi_userdata/LFTP-GUI && venv/bin/python3 app.py"

# Nginx config error
nginx -t
tail -f /var/log/nginx/error.log

# Can't reach lftpgui.brynley.au
ss -tlnp | grep 57423                 # verify app is listening
curl -I http://127.0.0.1:57423        # test app directly
curl -I https://lftpgui.brynley.au    # test full path
certbot certificates                  # verify cert isn't expired

# SSH key issues
ssh dietpi-user "ls -la ~/.ssh/"      # check key permissions
ssh -v dietpi-user                    # verbose SSH debug
```

---

## Network Configuration Reference

### Router Port Forwards (TP-Link Archer AX10) — already configured for ABS
```
Port 80  → 192.168.1.100:80   (HTTP — certbot renewal + redirect to HTTPS)
Port 443 → 192.168.1.100:443  (HTTPS — nginx serves both abs and lftpgui)
```

### DNS Records at iwantmyname.com
```
A  abs      → 115.69.2.169   (AudiobookShelf)
A  lftpgui  → 115.69.2.169   (LFTP-GUI)
```

### Security Model
- LFTP-GUI Flask app is bound to `127.0.0.1:57423` (localhost only)
- All external access goes through nginx on port 443 (HTTPS)
- No direct port 57423 access from LAN or internet
- SSH key for seedbox is passwordless (required for background LFTP operations)

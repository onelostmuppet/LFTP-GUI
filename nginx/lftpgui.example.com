# LFTP-GUI — https://lftpgui.example.com
# Nginx reverse proxy config
# Install: copy to /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN
#          edit server_name and certificate paths to match your domain
#          ln -s /etc/nginx/sites-available/lftpgui.YOUR_DOMAIN /etc/nginx/sites-enabled/

# ── HTTP: redirect to HTTPS + allow certbot ACME challenge ───────────────────
server {
    listen 80;
    listen [::]:80;
    server_name lftpgui.example.com;

    # Allow certbot ACME challenge through before redirecting
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# ── HTTPS: proxy to Flask app on port 57423 ──────────────────────────────────
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name lftpgui.example.com;

    ssl_certificate     /etc/letsencrypt/live/lftpgui.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lftpgui.example.com/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options           SAMEORIGIN                             always;
    add_header X-Content-Type-Options    nosniff                                always;
    add_header Referrer-Policy           "strict-origin-when-cross-origin"      always;

    # ── Standard proxy ────────────────────────────────────────────────────────
    location / {
        proxy_pass         http://127.0.0.1:57423;
        proxy_http_version 1.1;

        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        proxy_read_timeout  60s;
        proxy_send_timeout  60s;
        proxy_connect_timeout 10s;
    }

    # ── SSE endpoint /api/queue — disable buffering, long timeout ─────────────
    # Server-Sent Events requires buffering off so updates stream in real time.
    # The connection stays open indefinitely while the app is running.
    location /api/queue {
        proxy_pass         http://127.0.0.1:57423;
        proxy_http_version 1.1;

        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout  3600s;
        proxy_send_timeout  3600s;
        add_header         X-Accel-Buffering no;
    }
}

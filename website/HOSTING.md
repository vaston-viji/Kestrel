# Kestrel Website — VPS Hosting Guide

## Overview

The website is a FastAPI app (`server.py`) that:
- Serves `index.html` and `unsubscribe.html`
- Handles POST `/api/subscribe` and POST `/api/unsubscribe`
- Reads/writes `data/subscribers.xlsx` in the project root
- Runs on port 8080 behind nginx

---

## Local preview (Windows dev)

```powershell
cd C:\Claude\kestrel
.venv\Scripts\pip install -r website\requirements.txt
.venv\Scripts\uvicorn website.server:app --host 127.0.0.1 --port 8080 --reload
```

Open: http://localhost:8080

---

## VPS deployment (Ubuntu / Debian)

### 1. Transfer files to VPS

```bash
rsync -avz --exclude='.venv' --exclude='output' --exclude='__pycache__' \
  C:/Claude/kestrel/ user@your-vps:/opt/kestrel/
```

### 2. Create Python venv on VPS

```bash
cd /opt/kestrel
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r website/requirements.txt
```

### 3. Create a system user

```bash
sudo useradd --system --home /opt/kestrel --shell /usr/sbin/nologin kestrel
sudo chown -R kestrel:kestrel /opt/kestrel
```

### 4. Install systemd service

```bash
sudo cp website/kestrel-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kestrel-web
sudo systemctl start kestrel-web
sudo systemctl status kestrel-web
```

### 5. Install and configure nginx

```bash
sudo apt install nginx -y
sudo cp website/nginx.conf /etc/nginx/sites-available/kestrel
sudo ln -s /etc/nginx/sites-available/kestrel /etc/nginx/sites-enabled/
sudo nginx -t
sudo nginx -s reload
```

### 6. Obtain SSL certificate (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d kestrel.quantrim.com
# Certbot auto-patches nginx.conf with the certificate paths
sudo nginx -s reload
```

### 7. DNS

Point `kestrel.quantrim.com` A record to your VPS IP.
Allow inbound 80 and 443 in your VPS firewall:

```bash
sudo ufw allow 80
sudo ufw allow 443
```

---

## Updating the site

```bash
rsync -avz --exclude='.venv' --exclude='output' \
  C:/Claude/kestrel/website/ user@your-vps:/opt/kestrel/website/
sudo systemctl restart kestrel-web
```

---

## File structure

```
kestrel/
├── website/
│   ├── index.html          # Landing page
│   ├── unsubscribe.html    # Unsubscribe page
│   ├── server.py           # FastAPI application
│   ├── requirements.txt    # Website Python dependencies
│   ├── nginx.conf          # Nginx reverse-proxy config
│   ├── kestrel-web.service # Systemd service definition
│   ├── HOSTING.md          # This file
│   └── static/
│       ├── style.css       # Stylesheet
│       ├── script.js       # Client-side form handling
│       ├── logo-light.png  # Logo (light backgrounds)
│       ├── logo-dark.png   # Logo (dark backgrounds)
│       └── favicon.png     # Favicon
└── data/
    └── subscribers.xlsx    # Subscriber list (Name, Email, Subscription Preference)
```

---

## Email unsubscribe links

To pre-fill the unsubscribe form from emails, append the subscriber's email
to the unsubscribe URL:

```
https://kestrel.quantrim.com/unsubscribe?email=recipient@example.com
```

In the Kestrel email template (email.html.j2), update the footer unsubscribe
link to use this pattern when per-subscriber rendering is implemented.

---

## Monitoring

```bash
# Live logs
sudo journalctl -u kestrel-web -f

# Check running
sudo systemctl status kestrel-web

# Restart after config change
sudo systemctl restart kestrel-web
```

---

## Subscriber data

Subscriptions are written to `data/subscribers.xlsx` with three columns:
- **Name** — provided by subscriber (optional, may be blank)
- **Email** — subscriber email address
- **Subscription Preference** — `active` or `unsubscribed`

The Kestrel pipeline reads this file via `read_subscribers()` in
`src/kestrel/store/excel.py` to determine who to send the brief to.

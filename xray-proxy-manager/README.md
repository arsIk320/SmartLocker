# Xray Proxy Manager

Production-ready project for managing an Xray-core VLESS + TLS proxy on Ubuntu 22.04/24.04.

## Features

- Xray-core installation from official GitHub releases
- VLESS over TCP + TLS
- Split tunneling using `/etc/xray/domains.json`
- User management in SQLite
- FastAPI backend with local-only Web UI
- CLI for user and routing management
- systemd services and Xray auto-update timer
- Connection QR generation for mobile clients
- Safe firewall defaults with UFW

## Project layout

```text
xray-proxy-manager/
├── bin/
│   └── xray-manager
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_domains.py
│   │   ├── routes_system.py
│   │   ├── routes_users.py
│   │   └── ui.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   ├── links.py
│   │   ├── users.py
│   │   └── xray.py
│   ├── static/
│   │   ├── app.js
│   │   └── style.css
│   ├── templates/
│   │   └── index.html
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   └── schemas.py
├── cli/
│   ├── __init__.py
│   └── xray_manager.py
├── config/
│   ├── config.json
│   └── domains.json
├── scripts/
│   └── xray_update.sh
├── systemd/
│   ├── xray-manager.service
│   ├── xray-update.service
│   ├── xray-update.timer
│   └── xray.service
├── .env.example
├── install.sh
└── requirements.txt
```

## Runtime architecture

- `xray.service` reads `/etc/xray/config.json`
- `xray-manager.service` runs FastAPI on `127.0.0.1:8080`
- SQLite database lives at `/etc/xray/manager.sqlite3`
- Routing domains live at `/etc/xray/domains.json`
- The backend regenerates `/etc/xray/config.json` and issues `systemctl reload xray`

## Install

Run on a fresh Ubuntu server:

```bash
chmod +x install.sh
sudo ./install.sh \
  --domain vpn.example.com \
  --email admin@example.com \
  --port 443 \
  --initial-user admin
```

If you already have TLS certificates:

```bash
sudo ./install.sh \
  --domain vpn.example.com \
  --port 443 \
  --cert-path /etc/letsencrypt/live/vpn.example.com/fullchain.pem \
  --key-path /etc/letsencrypt/live/vpn.example.com/privkey.pem \
  --skip-certbot
```

## Open the Web UI

The management UI is intentionally bound to localhost only. Access it over SSH:

```bash
ssh -L 8080:127.0.0.1:8080 root@your-server
```

Then open [http://127.0.0.1:8080](http://127.0.0.1:8080).

## CLI examples

```bash
sudo xray-manager list-users
sudo xray-manager add-user --name alice
sudo xray-manager remove-user --uuid <uuid>
sudo xray-manager set-domains --domain netflix.com --domain openai.com
sudo xray-manager status
```

## Notes

- Standard TLS requires a valid public domain and certificate chain.
- Only SSH and the VLESS server port are exposed through UFW by default.
- Both logs and health checks are available through systemd and the API.
- Server-side split tunneling follows the requested routing model. If you also want true client-side bypass for all non-listed destinations, add matching routing rules in v2rayNG or Shadowrocket with the same domain list.

#!/usr/bin/env bash
set -euo pipefail

DOMAIN=""
EMAIL=""
PORT="443"
UI_HOST="127.0.0.1"
UI_PORT="8080"
CERT_PATH=""
KEY_PATH=""
INITIAL_USER="admin"
SKIP_CERTBOT="false"
INSTALL_DIR="/opt/xray-manager"
ENV_FILE="/etc/xray-manager.env"
XRAY_DIR="/etc/xray"
XRAY_SERVICE_NAME="xray"

usage() {
  cat <<'EOF'
Usage:
  sudo ./install.sh --domain vpn.example.com --email admin@example.com [options]

Options:
  --domain         Public domain used by TLS and client configs
  --email          Email for Let's Encrypt
  --port           VLESS TCP port, default 443
  --ui-host        FastAPI bind host, default 127.0.0.1
  --ui-port        FastAPI bind port, default 8080
  --cert-path      Existing certificate fullchain path
  --key-path       Existing private key path
  --initial-user   Initial proxy username, default admin
  --skip-certbot   Skip certificate issuance when existing cert paths are provided
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --ui-host) UI_HOST="$2"; shift 2 ;;
    --ui-port) UI_PORT="$2"; shift 2 ;;
    --cert-path) CERT_PATH="$2"; shift 2 ;;
    --key-path) KEY_PATH="$2"; shift 2 ;;
    --initial-user) INITIAL_USER="$2"; shift 2 ;;
    --skip-certbot) SKIP_CERTBOT="true"; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

if [[ -z "$DOMAIN" ]]; then
  echo "--domain is required." >&2
  exit 1
fi

if [[ "$SKIP_CERTBOT" != "true" && -z "$EMAIL" ]]; then
  echo "--email is required unless --skip-certbot is used." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

install_packages() {
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    curl \
    unzip \
    jq \
    sqlite3 \
    python3 \
    python3-venv \
    python3-pip \
    ufw \
    certbot
}

install_xray() {
  local version archive url
  version="$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest | jq -r '.tag_name')"
  archive="$TMP_DIR/xray.zip"
  url="https://github.com/XTLS/Xray-core/releases/download/${version}/Xray-linux-64.zip"

  curl -fsSL "$url" -o "$archive"
  unzip -q "$archive" -d "$TMP_DIR/xray"
  install -m 0755 "$TMP_DIR/xray/xray" /usr/local/bin/xray
}

issue_certificate() {
  if [[ -n "$CERT_PATH" && -n "$KEY_PATH" ]]; then
    return
  fi

  ufw allow 80/tcp
  certbot certonly --standalone --non-interactive --agree-tos -m "$EMAIL" -d "$DOMAIN"
  ufw delete allow 80/tcp || true

  CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
  KEY_PATH="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
}

prepare_layout() {
  mkdir -p "$XRAY_DIR" /var/log/xray "$INSTALL_DIR"
  cp -R "$SCRIPT_DIR"/app "$INSTALL_DIR"/
  cp -R "$SCRIPT_DIR"/bin "$INSTALL_DIR"/
  cp -R "$SCRIPT_DIR"/cli "$INSTALL_DIR"/
  cp -R "$SCRIPT_DIR"/scripts "$INSTALL_DIR"/
  install -m 0644 "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/requirements.txt"
  install -m 0755 "$SCRIPT_DIR/bin/xray-manager" /usr/local/bin/xray-manager
  install -m 0644 "$SCRIPT_DIR/systemd/xray.service" /etc/systemd/system/xray.service
  install -m 0644 "$SCRIPT_DIR/systemd/xray-manager.service" /etc/systemd/system/xray-manager.service
  install -m 0644 "$SCRIPT_DIR/systemd/xray-update.service" /etc/systemd/system/xray-update.service
  install -m 0644 "$SCRIPT_DIR/systemd/xray-update.timer" /etc/systemd/system/xray-update.timer
  install -m 0755 "$INSTALL_DIR/scripts/xray_update.sh" "$INSTALL_DIR/scripts/xray_update.sh"
  install -m 0600 "$SCRIPT_DIR/config/domains.json" "$XRAY_DIR/domains.json"
  touch /var/log/xray/access.log /var/log/xray/error.log
  chmod 0600 /var/log/xray/access.log /var/log/xray/error.log
}

install_python_env() {
  python3 -m venv "$INSTALL_DIR/.venv"
  "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
  "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
}

write_env_file() {
  cat > "$ENV_FILE" <<EOF
XRAY_MANAGER_DOMAIN=$DOMAIN
XRAY_MANAGER_SERVER_PORT=$PORT
XRAY_MANAGER_UI_HOST=$UI_HOST
XRAY_MANAGER_UI_PORT=$UI_PORT
XRAY_MANAGER_DATABASE_URL=sqlite:////etc/xray/manager.sqlite3
XRAY_MANAGER_XRAY_CONFIG_PATH=/etc/xray/config.json
XRAY_MANAGER_DOMAINS_PATH=/etc/xray/domains.json
XRAY_MANAGER_CERT_PATH=$CERT_PATH
XRAY_MANAGER_KEY_PATH=$KEY_PATH
XRAY_MANAGER_ACCESS_LOG_PATH=/var/log/xray/access.log
XRAY_MANAGER_ERROR_LOG_PATH=/var/log/xray/error.log
XRAY_MANAGER_REMARK_PREFIX=$DOMAIN
XRAY_MANAGER_XRAY_SERVICE=$XRAY_SERVICE_NAME
EOF
  chmod 0600 "$ENV_FILE"
}

bootstrap_config() {
  systemctl daemon-reload
  "$INSTALL_DIR/.venv/bin/python" -m cli.xray_manager init --initial-user "$INITIAL_USER"
}

configure_firewall() {
  ufw allow OpenSSH
  ufw allow "${PORT}/tcp"
  ufw --force enable
}

enable_services() {
  systemctl enable --now xray.service
  systemctl enable --now xray-manager.service
  systemctl enable --now xray-update.timer
}

print_summary() {
  local server_ip uuid link
  server_ip="$(curl -fsSL https://api.ipify.org || hostname -I | awk '{print $1}')"
  uuid="$("$INSTALL_DIR/.venv/bin/python" -m cli.xray_manager list-users | awk 'NR==1 {print $1}')"
  link="$("$INSTALL_DIR/.venv/bin/python" -m cli.xray_manager show-link --uuid "$uuid")"

  cat <<EOF

Installation completed.

Server IP: $server_ip
Domain: $DOMAIN
Port: $PORT
UUID: $uuid
VLESS: $link

Web UI: ssh -L ${UI_PORT}:127.0.0.1:${UI_PORT} root@${DOMAIN}
CLI: xray-manager
EOF
}

install_packages
install_xray
issue_certificate
prepare_layout
install_python_env
write_env_file
bootstrap_config
configure_firewall
enable_services
print_summary

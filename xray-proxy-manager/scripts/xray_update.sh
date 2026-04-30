#!/usr/bin/env bash
set -euo pipefail

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

ARCHIVE="$TMP_DIR/xray.zip"
VERSION="$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest | jq -r '.tag_name')"
URL="https://github.com/XTLS/Xray-core/releases/download/${VERSION}/Xray-linux-64.zip"

curl -fsSL "$URL" -o "$ARCHIVE"
unzip -q "$ARCHIVE" -d "$TMP_DIR/xray"
install -m 0755 "$TMP_DIR/xray/xray" /usr/local/bin/xray

if /usr/local/bin/xray run -test -config /etc/xray/config.json; then
  systemctl restart xray
fi

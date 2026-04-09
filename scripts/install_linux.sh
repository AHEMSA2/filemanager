#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/filemanager}"
SERVICE_NAME="filemanager"
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Bu script root ile çalıştırılmalı: sudo bash scripts/install_linux.sh"
  exit 1
fi

echo "[1/8] Paketler kuruluyor"
apt-get update
apt-get install -y python3 python3-venv python3-pip rsync network-manager iw

echo "[2/8] Uygulama dizini hazırlanıyor: $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete --exclude '.git' "$SCRIPT_ROOT/" "$APP_DIR/"

echo "[3/8] Python ortamı"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[4/8] config.json kontrolü"
if [[ ! -f "$APP_DIR/config.json" ]]; then
  if [[ -f "$APP_DIR/config.example.json" ]]; then
    cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
    echo "config.json oluşturuldu. Devam etmeden önce düzenlemen önerilir."
  else
    echo "config.json bulunamadı ve config.example.json yok."
    exit 1
  fi
fi

python3 - <<PY
import json
with open("$APP_DIR/config.json", "r", encoding="utf-8") as fh:
    json.load(fh)
print("config.json JSON doğrulaması tamam")
PY

echo "[5/8] AP profile hazırlığı (NetworkManager)"
AP_SSID=$(python3 - <<PY
import json
with open("$APP_DIR/config.json", "r", encoding="utf-8") as fh:
    cfg = json.load(fh)
print(cfg.get("ap_ssid", "FileManager-AP"))
PY
)

AP_PASSWORD=$(python3 - <<PY
import json
with open("$APP_DIR/config.json", "r", encoding="utf-8") as fh:
    cfg = json.load(fh)
print(cfg.get("ap_password", "ChangeMe123"))
PY
)

nmcli connection show "$AP_SSID" >/dev/null 2>&1 || {
  nmcli connection add type wifi ifname "*" con-name "$AP_SSID" autoconnect no ssid "$AP_SSID"
}

nmcli connection modify "$AP_SSID" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$AP_PASSWORD"

echo "[6/8] systemd unit kurulumu"
install -d /etc/systemd/system
cp "$APP_DIR/systemd/filemanager.service" /etc/systemd/system/filemanager.service
sed -i "s|/opt/filemanager|$APP_DIR|g" /etc/systemd/system/filemanager.service

systemctl daemon-reload

echo "[7/8] servis enable/start"
systemctl enable --now "$SERVICE_NAME"

echo "[8/8] sağlık kontrol"
bash "$APP_DIR/scripts/post_install_check.sh"

echo "Kurulum tamamlandı."
echo "Durum: systemctl status $SERVICE_NAME"

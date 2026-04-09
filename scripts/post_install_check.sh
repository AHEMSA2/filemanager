#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/filemanager}"
SERVICE_NAME="${SERVICE_NAME:-filemanager}"
CONFIG_PATH="$APP_DIR/config.json"

echo "[check] service state"
systemctl is-active --quiet "$SERVICE_NAME" && echo "  - service: active" || { echo "  - service: inactive"; exit 1; }

echo "[check] config"
python3 - <<PY
import json
with open("$CONFIG_PATH", "r", encoding="utf-8") as fh:
    cfg = json.load(fh)
print("  - web_port:", cfg.get("web_port"))
PY

WEB_PORT=$(python3 - <<PY
import json
with open("$CONFIG_PATH", "r", encoding="utf-8") as fh:
    cfg = json.load(fh)
print(cfg.get("web_port", 5000))
PY
)

echo "[check] port"
if ss -tuln | grep -q ":${WEB_PORT} "; then
  echo "  - listening: ${WEB_PORT}"
else
  echo "  - not listening: ${WEB_PORT}"
  exit 1
fi

echo "[check] nmcli"
if command -v nmcli >/dev/null 2>&1; then
  echo "  - nmcli: ok"
else
  echo "  - nmcli: missing"
fi

echo "[ok] post install checks finished"

#!/bin/sh
set -e

echo "[Init] Syncing engine scripts..."

# Overwrite all python files and requirements from the image defaults into /app
cp -f /defaults/*.py /app/
cp -f /defaults/requirements.txt /app/ 2>/dev/null || true

# Verify credentials
if [ ! -f "/app/service_account.json" ]; then
  echo "===================================================================="
  echo "[WARNING] service_account.json not found in /app!"
  echo "Please place your Google service_account.json inside your app folder."
  echo "===================================================================="
fi

exec python -u /app/main.py
#!/bin/sh
set -e

# Always copy core application code from image to ensure container updates take effect
echo "[Init] Syncing engine scripts..."
cp -f /defaults/watcher.py /app/watcher.py

# Only seed prompt.txt and doc_updater.py if they don't already exist on the host
for file in doc_updater.py prompt.txt; do
  if [ ! -f "/app/$file" ]; then
    echo "[Init] Seeding default $file into /app..."
    cp "/defaults/$file" "/app/$file"
  fi
done

if [ ! -f "/app/service_account.json" ]; then
  echo "===================================================================="
  echo "[WARNING] service_account.json not found in /app!"
  echo "Please place your Google service_account.json inside your app folder."
  echo "===================================================================="
fi

exec python -u /app/watcher.py
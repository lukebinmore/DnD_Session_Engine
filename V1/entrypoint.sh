#!/bin/sh
set -e

# Seed default files into /app only if they do not already exist on the host
for file in watcher.py doc_updater.py prompt.txt; do
  if [ ! -f "/app/$file" ]; then
    echo "[Init] Seeding default $file into /app..."
    cp "/defaults/$file" "/app/$file"
  fi
done

# Inform user if service_account.json is still needed
if [ ! -f "/app/service_account.json" ]; then
  echo "===================================================================="
  echo "[WARNING] service_account.json not found in /app!"
  echo "Please place your Google service_account.json inside your app folder."
  echo "===================================================================="
fi

# Run the watcher directly from /app
exec python /app/watcher.py
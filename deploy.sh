#!/bin/bash
# ── Shelly deploy script ───────────────────────────────────────────────────────
# Run this from your Mac whenever you want to push updates to Unraid.
# Usage: ./deploy.sh
# ──────────────────────────────────────────────────────────────────────────────

UNRAID_IP="10.1.1.4"
UNRAID_USER="root"
REMOTE_PATH="/mnt/user/appdata/shelly"
LOCAL_PATH="$(cd "$(dirname "$0")" && pwd)"   # folder this script lives in

echo "▶ Syncing files to Unraid..."
rsync -av --progress \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='data' \
  "$LOCAL_PATH/" "$UNRAID_USER@$UNRAID_IP:$REMOTE_PATH/"

echo ""
echo "▶ Rebuilding and restarting container on Unraid..."
ssh "$UNRAID_USER@$UNRAID_IP" "
  cd $REMOTE_PATH &&
  docker build -t shelly-app . &&
  docker stop shelly 2>/dev/null || true &&
  docker rm shelly 2>/dev/null || true &&
  docker run -d \
    --name shelly \
    --restart unless-stopped \
    -p 8001:8000 \
    -v $REMOTE_PATH/data:/app/data \
    shelly-app
"

echo ""
echo "✓ Done. Shelly is running at http://$UNRAID_IP:8001"

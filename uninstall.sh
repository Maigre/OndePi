#!/usr/bin/env bash
set -euo pipefail

BIN_LINK="/usr/local/bin/ondepi"
SYSTEMD_LINK="/etc/systemd/system/ondepi.service"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Stop & disable service ---
if systemctl is-active --quiet ondepi.service 2>/dev/null; then
  echo "Stopping ondepi.service..."
  sudo systemctl stop ondepi.service
fi

if systemctl is-enabled --quiet ondepi.service 2>/dev/null; then
  echo "Disabling ondepi.service..."
  sudo systemctl disable ondepi.service
fi

# --- Remove symlinks ---
if [ -L "$SYSTEMD_LINK" ]; then
  echo "Removing $SYSTEMD_LINK"
  sudo rm "$SYSTEMD_LINK"
fi

if [ -L "$BIN_LINK" ]; then
  echo "Removing $BIN_LINK"
  sudo rm "$BIN_LINK"
fi

sudo systemctl daemon-reload

# --- Remove venv ---
if [ -d "$PROJECT_DIR/.venv" ]; then
  read -rp "Remove virtual environment ($PROJECT_DIR/.venv)? [y/N] " answer
  if [[ "$answer" =~ ^[Yy]$ ]]; then
    rm -rf "$PROJECT_DIR/.venv"
    echo "Virtual environment removed."
  fi
fi

# --- Remove generated service file ---
if [ -f "$PROJECT_DIR/ondepi.service" ]; then
  git -C "$PROJECT_DIR" checkout -- ondepi.service 2>/dev/null || true
fi

echo ""
echo "Uninstall complete."

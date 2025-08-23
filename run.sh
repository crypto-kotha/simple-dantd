#!/usr/bin/env bash
set -euo pipefail

# Ensure loopback alias exists (idempotent)
if ! ip addr show lo | grep -q "127.0.0.50"; then
  echo "Adding 127.0.0.50 to lo (requires sudo)"
  sudo ip addr add 127.0.0.50/32 dev lo || true
fi

# Create venv if missing
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -r webui/requirements.txt

# Run UI
exec python webui/app.py

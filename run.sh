#!/usr/bin/env bash
set -euo pipefail

# Ensure loopback alias exists (idempotent)
if ! ip addr show lo | grep -q "127.0.0.50"; then
  echo "Adding 127.0.0.50 to lo (requires sudo)"
  sudo ip addr add 127.0.0.50/32 dev lo || true
fi

# Detect python interpreter
PY_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  echo "Error: python3 or python not found in PATH" >&2
  exit 1
fi

# Create venv if missing
if [ ! -d .venv ]; then
  "$PY_BIN" -m venv .venv
fi
. .venv/bin/activate
pip install -r webui/requirements.txt

# Decide host binding based on UFW allowing port 7000
APP_HOST="127.0.0.50"
APP_PORT="7000"
if command -v ufw >/dev/null 2>&1; then
  # Try to read UFW status without prompting for password
  UFW_OUT=$(sudo -n ufw status 2>/dev/null || ufw status 2>/dev/null || true)
  if echo "$UFW_OUT" | grep -qi "Status: active" && echo "$UFW_OUT" | grep -Eqi "(^|\s)7000(/tcp)?\s+ALLOW"; then
    APP_HOST="0.0.0.0"
    echo "UFW allows port 7000 -> binding UI to 0.0.0.0 so it is reachable from your network"
  fi
fi

# Run UI with explicit host/port via environment
export APP_HOST APP_PORT
exec python webui/app.py

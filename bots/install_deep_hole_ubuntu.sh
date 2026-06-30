#!/usr/bin/env bash
set -euo pipefail

# Ubuntu server setup for the deep-hole alert feature.
# Usage:
#   cd ~/bot/saias-bot2
#   bash bots/install_deep_hole_ubuntu.sh

BOT_ROOT="${BOT_ROOT:-$(pwd)}"

echo "[1/4] Installing Ubuntu packages..."
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv ca-certificates tzdata sqlite3

echo "[2/4] Installing Python packages required by user_system.py..."
python3 -m pip install --user --upgrade pip
python3 -m pip install --user --upgrade pytz python-dotenv

echo "[3/4] Checking required Python modules..."
python3 - <<'PY'
import importlib.util
import sys

required = {
    "pytz": "pytz",
    "dotenv": "python-dotenv",
    "iris": "iris bot runtime",
}

missing = [pkg_name for module, pkg_name in required.items() if importlib.util.find_spec(module) is None]
if missing:
    print("Missing modules/runtime:", ", ".join(missing))
    print("Install or activate the missing runtime before starting the bot.")
    sys.exit(1)

print("Python module check passed.")
PY

echo "[4/4] Checking syntax for the changed files..."
python3 -m py_compile "$BOT_ROOT/bots/user_system.py" "$BOT_ROOT/bots/deep_hole_alert.py"

echo "Done. Restart the bot process after deploying these files."

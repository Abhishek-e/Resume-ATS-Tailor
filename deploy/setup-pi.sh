#!/usr/bin/env bash
# One-shot setup for running Resumify on a Raspberry Pi (Debian/Raspberry Pi OS).
# Safe to re-run: it only (re)creates the venv and reinstalls dependencies.
#
#   cd ~/Resume-ATS-Tailor
#   bash deploy/setup-pi.sh
#
set -euo pipefail

# Resolve the project root (the parent of this deploy/ dir), regardless of cwd.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Project root: $ROOT"

# --- System packages -------------------------------------------------------
# python3-venv is not always present on a fresh Pi image. build-essential and
# the libjpeg/zlib headers are a fallback for Pillow on the rare Pi/Python
# combo without a prebuilt wheel; harmless if wheels are used instead.
echo "==> Installing system packages (needs sudo)..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev build-essential \
    libjpeg-dev zlib1g-dev

# --- Virtual environment ---------------------------------------------------
echo "==> Creating virtual environment in .venv ..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Upgrading pip and installing dependencies..."
pip install --upgrade pip wheel
pip install -r requirements.txt

# --- Secrets check ---------------------------------------------------------
echo "==> Checking for secrets..."
missing=0
if [[ ! -f .env ]]; then
    echo "    [!] .env not found. Copy .env.example to .env and fill it in:"
    echo "        cp .env.example .env && nano .env"
    missing=1
fi
if [[ ! -f serviceAccountKey.json ]]; then
    echo "    [!] serviceAccountKey.json not found. Copy it from your Mac, e.g.:"
    echo "        scp serviceAccountKey.json pi@<pi-ip>:$ROOT/"
    echo "        (login/registration/save features need it; the rest still runs)"
fi

echo
if [[ "$missing" -eq 0 ]]; then
    echo "==> Setup complete. Test it with:"
    echo "    source .venv/bin/activate && \\"
    echo "    gunicorn app:app --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:5000"
else
    echo "==> Dependencies installed. Add the secrets above, then re-run to verify."
fi

#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

APP_URL="${APP_URL:-http://localhost:8501}"
VENV_DIR="$PWD/.venv"
OFFLINE_PACKAGES="$PWD/offline_packages_linux"

echo "============================================"
echo "  Citizen Requests Analyzer - Web interface"
echo "============================================"
echo

if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python was not found."
    echo "Install Python 3.10+ or put portable_python_linux into the project."
    exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "[1/3] Creating virtual environment..."
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR"; then
        echo "[ERROR] Failed to create virtual environment."
        echo "On Debian/Ubuntu, install python3-venv and try again."
        exit 1
    fi
fi

PYTHON="$VENV_DIR/bin/python"

echo "[2/3] Installing dependencies..."
if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
    echo "Preparing pip inside virtual environment..."
    if ! "$PYTHON" -m ensurepip --upgrade; then
        echo "[ERROR] Failed to prepare pip in virtual environment."
        echo "On Debian/Ubuntu, install python3-venv and python3-pip, then try again."
        exit 1
    fi
fi

if find "$OFFLINE_PACKAGES" -maxdepth 1 -name "*.whl" -print -quit 2>/dev/null | grep -q .; then
    echo "Offline package folder found: offline_packages_linux"
    "$PYTHON" -m pip install --no-index --find-links "$OFFLINE_PACKAGES" -r requirements.txt
else
    echo "[ERROR] Offline package folder offline_packages_linux was not found or is empty."
    echo "Internet is not used by this launcher."
    exit 1
fi

echo "[3/3] Starting web interface..."
echo "Opening $APP_URL"
echo

(
    sleep 3
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$APP_URL" >/dev/null 2>&1 || true
    elif command -v sensible-browser >/dev/null 2>&1; then
        sensible-browser "$APP_URL" >/dev/null 2>&1 || true
    elif command -v open >/dev/null 2>&1; then
        open "$APP_URL" >/dev/null 2>&1 || true
    fi
) &

exec "$PYTHON" -m streamlit run app.py --server.address localhost --server.port 8501 --server.headless true --server.maxUploadSize 5120

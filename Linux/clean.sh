#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "Cleaning installed dependencies for demo..."
rm -rf .venv
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
echo "Done. Now run ./Запуск\ Linux.sh"

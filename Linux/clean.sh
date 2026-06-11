#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "Очистка установленных зависимостей и кэша..."
rm -rf .venv
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
echo "Готово."
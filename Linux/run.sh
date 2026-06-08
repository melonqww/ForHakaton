#!/bin/bash
cd "$(dirname "$0")/.."

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 не найден. Установите Python 3.10+ и повторите попытку."
    read -p "Нажмите Enter для выхода..."
    exit 1
fi

echo "Запуск интерфейса Streamlit..."
python3 -m streamlit run app.py
if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Ошибка запуска Streamlit. Проверьте окружение Python."
    read -p "Нажмите Enter для выхода..."
fi

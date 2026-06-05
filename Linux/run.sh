#!/bin/bash
cd "$(dirname "$0")/.."
echo "Запуск интерфейса Streamlit..."
python3 -m streamlit run app.py
if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Ошибка запуска Streamlit. Проверьте окружение Python."
    read -p "Нажмите Enter для выхода..."
fi

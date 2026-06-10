#!/bin/bash
# ── Определяем корень проекта (папка с app.py) ───────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/../app.py" ]; then
    PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "$SCRIPT_DIR/app.py" ]; then
    PROJECT_DIR="$SCRIPT_DIR"
else
    echo "[ОШИБКА] app.py не найден. Убедитесь что run.sh лежит в Linux/ или в корне."
    read -rp "Нажмите Enter для выхода..."
    exit 1
fi

cd "$PROJECT_DIR"
echo "============================================"
echo "  Запуск системы анализа обращений"
echo "============================================"
echo
echo "Рабочая папка: $PROJECT_DIR"
echo

# ── 1. Python ─────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ОШИБКА] Python3 не найден."
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "Fedora:        sudo dnf install python3"
    read -rp "Нажмите Enter для выхода..."
    exit 1
fi
echo "[1/4] $(python3 --version) — OK"

# ── 2. Проверка файлов проекта ────────────────────────────────────────────────
if [ ! -f "app.py" ]; then
    echo "[ОШИБКА] app.py не найден в: $(pwd)"
    read -rp "Нажмите Enter для выхода..."
    exit 1
fi

if [ ! -f "requirements.txt" ]; then
    echo "[ОШИБКА] requirements.txt не найден в: $(pwd)"
    read -rp "Нажмите Enter для выхода..."
    exit 1
fi

# ── 3. Зависимости ────────────────────────────────────────────────────────────
echo "[2/4] Установка зависимостей..."
python3 -m pip install --upgrade pip -q 2>&1 | tail -1
python3 -m pip install -r requirements.txt -q
if [ $? -ne 0 ]; then
    echo "[ОШИБКА] Не удалось установить зависимости."
    echo "Попробуйте вручную: pip3 install -r requirements.txt"
    read -rp "Нажмите Enter для выхода..."
    exit 1
fi
echo "[2/4] Зависимости — OK"

# ── 4. Ollama ─────────────────────────────────────────────────────────────────
echo "[3/4] Проверка Ollama..."
if curl -s --max-time 2 http://localhost:11434/api/tags &>/dev/null; then
    echo "    Ollama — OK"
    if curl -s http://localhost:11434/api/tags | grep -q "qwen2.5:0.5b"; then
        echo "    Модель qwen2.5:0.5b — OK"
    else
        echo "    Загрузка модели qwen2.5:0.5b (~300MB)..."
        ollama pull qwen2.5:0.5b
        if [ $? -eq 0 ]; then
            echo "    Модель — OK"
        else
            echo "    [WARN] Не удалось загрузить модель. Работаем без ИИ."
        fi
    fi
else
    echo "    Ollama не запущена. Пробуем запустить..."
    if command -v ollama &>/dev/null; then
        ollama serve &>/dev/null &
        echo "    Ожидание (5 сек)..."
        sleep 5
        if curl -s --max-time 3 http://localhost:11434/api/tags &>/dev/null; then
            echo "    Ollama — OK"
        else
            echo "    [WARN] Ollama не ответила. Работаем без ИИ."
        fi
    else
        echo "    [WARN] Ollama не установлена: https://ollama.com/download"
    fi
fi

# ── 5. Порт 8501 ──────────────────────────────────────────────────────────────
echo "[4/4] Запуск..."
PORT_BUSY=0
if lsof -i :8501 &>/dev/null 2>&1; then
    PORT_BUSY=1
fi
if ss -tlnp 2>/dev/null | grep -q ":8501"; then
    PORT_BUSY=1
fi

if [ $PORT_BUSY -eq 1 ]; then
    echo "    [WARN] Порт 8501 занят. Приложение уже работает: http://localhost:8501"
    command -v xdg-open &>/dev/null && xdg-open http://localhost:8501
    command -v open     &>/dev/null && open     http://localhost:8501
    read -rp "Нажмите Enter для выхода..."
    exit 0
fi

# ── 6. Streamlit ──────────────────────────────────────────────────────────────
echo "    Streamlit из: $PROJECT_DIR"
echo

# Открываем браузер через 3 сек в фоне
(
    sleep 3
    command -v xdg-open &>/dev/null && xdg-open http://localhost:8501 && exit
    command -v open     &>/dev/null && open     http://localhost:8501
) &

python3 -m streamlit run app.py --server.headless true

if [ $? -ne 0 ]; then
    echo
    echo "[ОШИБКА] Streamlit завершился с ошибкой."
    echo "Попробуйте вручную: python3 -m streamlit run app.py"
    read -rp "Нажмите Enter для выхода..."
fi

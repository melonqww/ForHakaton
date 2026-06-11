#!/usr/bin/env bash
# ── Настройка путей ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

VENV_DIR="$PROJECT_DIR/.venv"
OFFLINE_PACKAGES="$SCRIPT_DIR/offline_packages_linux"
APP_URL="${APP_URL:-http://localhost:8501}"

echo "============================================"
echo "  Система анализа обращений — Запуск (Linux)"
echo "============================================"
echo "Рабочая папка: $PROJECT_DIR"
echo

# ── 1. Поиск Python ──────────────────────────────────────────────────────────
PYTHON_CMD=""

for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "[ОШИБКА] Подходящая версия Python 3.10+ не найдена."
    exit 1
fi
echo "[1/5] $($PYTHON_CMD --version) — OK"

# ── 2. Создание виртуального окружения ───────────────────────────────────────
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "[2/5] Создание виртуального окружения .venv..."
    if ! "$PYTHON_CMD" -m venv "$VENV_DIR"; then
        echo "[ОШИБКА] Не удалось создать виртуальное окружение."
        echo "В системах Debian/Ubuntu выполните: sudo apt install python3-venv"
        exit 1
    fi
fi
echo "[2/5] Виртуальное окружение OK"

PYTHON="$VENV_DIR/bin/python"

# ── 3. Установка зависимостей ───────────────────────────────────────────────
echo "[3/5] Проверка и установка зависимостей..."

# Проверяем, установлены ли уже зависимости (по наличию streamlit)
if [ -x "$PYTHON" ] && "$PYTHON" -c "import streamlit" >/dev/null 2>&1; then
    echo "[3/5] Зависимости уже установлены. Пропуск установки."
else
    # Проверка pip в виртуальном окружении
    if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
        echo "Подготовка pip в виртуальном окружении..."
        "$PYTHON" -m ensurepip --upgrade
    fi

    # Проверка наличия колес в папке offline_packages_linux
    HAS_WHEELS=0
    if [ -d "$OFFLINE_PACKAGES" ] && ls "$OFFLINE_PACKAGES"/*.whl >/dev/null 2>&1; then
        HAS_WHEELS=1
    fi

    if [ "$HAS_WHEELS" -eq 1 ]; then
        echo "Обнаружена папка с офлайн пакетами. Установка офлайн..."
        "$PYTHON" -m pip install --no-index --find-links "$OFFLINE_PACKAGES" -r "$PROJECT_DIR/requirements.txt"
    else
        echo "Офлайн пакеты не найдены. Установка через Интернет..."
        "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
    fi

    if [ $? -ne 0 ]; then
        echo "[ОШИБКА] Не удалось установить зависимости."
        exit 1
    fi
    echo "[3/5] Зависимости установлены OK"
fi

# ── 4. Проверка и запуск Ollama ─────────────────────────────────────────────
echo "[4/5] Проверка службы Ollama..."

# Поиск пути к ollama
OLLAMA_CMD=""
if command -v ollama >/dev/null 2>&1; then
    OLLAMA_CMD="ollama"
elif [ -x "/usr/local/bin/ollama" ]; then
    OLLAMA_CMD="/usr/local/bin/ollama"
elif [ -x "/usr/bin/ollama" ]; then
    OLLAMA_CMD="/usr/bin/ollama"
elif [ -x "$HOME/bin/ollama" ]; then
    OLLAMA_CMD="$HOME/bin/ollama"
fi

if [ -z "$OLLAMA_CMD" ]; then
    echo "[ПРЕДУПРЕЖДЕНИЕ] Утилита ollama не найдена в системе."
    echo "LLM-анализ (Qwen) будет недоступен. Будет использован стандартный TextRank."
    OLLAMA_AVAILABLE=0
else
    OLLAMA_AVAILABLE=1
fi

if [ "$OLLAMA_AVAILABLE" -eq 1 ]; then
    # Проверка, слушает ли порт 11434
    if ! ss -tuln | grep -q ":11434"; then
        echo "Ollama не запущена. Попытка запуска..."
        echo "Запуск Ollama serve в фоновом режиме..."
        "$OLLAMA_CMD" serve >/dev/null 2>&1 &
        
        # Ожидаем запуска порта 11434 (до 30 секунд)
        echo "Ожидание инициализации Ollama..."
        for i in {1..30}; do
            if ss -tuln | grep -q ":11434"; then
                break
            fi
            sleep 1
        done
    fi

    # Проверка наличия модели qwen2.5:0.5b
    echo "Проверка модели qwen2.5:0.5b в Ollama..."
    if ! "$OLLAMA_CMD" list | grep -q "qwen2.5:0.5b"; then
        echo "Модель qwen2.5:0.5b не найдена. Скачивание модели..."
        "$OLLAMA_CMD" pull qwen2.5:0.5b
        if [ $? -ne 0 ]; then
            echo "[ПРЕДУПРЕЖДЕНИЕ] Не удалось скачать модель qwen2.5:0.5b."
        fi
    fi
fi
echo "[4/5] Ollama проверена."

# ── 5. Проверка порта и запуск Streamlit ────────────────────────────────────
echo "[5/5] Проверка порта 8501..."
if ss -tuln | grep -q ":8501"; then
    echo "[ПРЕДУПРЕЖДЕНИЕ] Порт 8501 уже занят другим процессом."
    echo "Проверьте http://localhost:8501 или закройте другие процессы Streamlit."
fi

echo "Запуск веб-интерфейса..."
echo "Перейдите по адресу: $APP_URL"
echo

# Попытка открыть браузер в фоновом режиме (если графическая среда доступна)
if command -v xdg-open >/dev/null 2>&1; then
    (sleep 3 && xdg-open "$APP_URL") &
elif command -v open >/dev/null 2>&1; then
    (sleep 3 && open "$APP_URL") &
fi

"$PYTHON" -m streamlit run app.py --server.address localhost --server.port 8501 --server.headless true --server.maxUploadSize 5120
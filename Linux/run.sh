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
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "[ОШИБКА] Python не найден."
    echo "Пожалуйста, установите Python 3.10+."
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

# Проверка pip в виртуальном окружении
if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
    echo "Подготовка pip в виртуальном окружении..."
    "$PYTHON" -m ensurepip --upgrade
fi

# ── 3. Установка зависимостей ───────────────────────────────────────────────
echo "[3/5] Проверка и установка зависимостей..."

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

# ── 4. Проверка и запуск Ollama ─────────────────────────────────────────────
echo "[4/5] Проверка службы Ollama..."

OLLAMA_AVAILABLE=1
# Проверка, слушает ли порт 11434
if ! ss -tuln | grep -q ":11434"; then
    echo "Ollama не запущена. Попытка запуска..."
    if command -v ollama >/dev/null 2>&1; then
        echo "Запуск Ollama serve в фоновом режиме..."
        ollama serve >/dev/null 2>&1 &
        
        # Ожидаем запуска порта 11434
        echo "Ожидание инициализации Ollama..."
        for i in {1..10}; do
            if ss -tuln | grep -q ":11434"; then
                break
            fi
            sleep 1
        done
    else
        echo "[ПРЕДУПРЕЖДЕНИЕ] Утилита ollama не найдена."
        echo "LLM-анализ (Qwen) будет недоступен. Будет использован стандартный TextRank."
        OLLAMA_AVAILABLE=0
    fi
fi

if [ "$OLLAMA_AVAILABLE" -eq 1 ]; then
    # Проверка наличия модели qwen2.5:0.5b
    echo "Проверка модели qwen2.5:0.5b в Ollama..."
    if ! ollama list | grep -q "qwen2.5:0.5b"; then
        echo "Модель qwen2.5:0.5b не найдена. Скачивание модели..."
        ollama pull qwen2.5:0.5b
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

"$VENV_DIR/bin/streamlit" run app.py --server.address localhost --server.port 8501 --server.headless true --server.maxUploadSize 5120
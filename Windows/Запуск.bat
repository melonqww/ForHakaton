@echo off
chcp 1251 >nul 2>&1
setlocal

:: -- Переходим в корень проекта (на один уровень выше папки Windows) ---------
cd /d "%~dp0.."
set "PROJECT_DIR=%CD%"
set "SCRIPT_DIR=%~dp0"

set "VENV_DIR=%PROJECT_DIR%\.venv"
set "OFFLINE_PACKAGES=%SCRIPT_DIR%offline_packages_windows"
set "PORTABLE_PYTHON=%SCRIPT_DIR%portable_python_windows\python.exe"
set "APP_URL=http://localhost:8501"

echo ============================================
echo   Система анализа обращений - Запуск
echo ============================================
echo Рабочая папка: %PROJECT_DIR%
echo.

:: -- 1. Поиск интерпретатора Python -----------------------------------------
set "PYTHON_CMD="
set "PYTHON_ARGS="

if exist "%PORTABLE_PYTHON%" (
    "%PORTABLE_PYTHON%" --version >nul 2>&1
    if not errorlevel 1 (
        "%PORTABLE_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_CMD=%PORTABLE_PYTHON%"
            echo [1/5] Использование портативного Python OK
        )
    )
)

if not defined PYTHON_CMD (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 --version >nul 2>&1
        if not errorlevel 1 (
            py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_CMD=py"
                set "PYTHON_ARGS=-3"
                echo [1/5] Использование системного py launcher OK
            )
        )
    )
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python --version >nul 2>&1
        if not errorlevel 1 (
            python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_CMD=python"
                echo [1/5] Использование системного python OK
            )
        )
    )
)

if not defined PYTHON_CMD (
    echo [ОШИБКА] Подходящая версия Python 3.10+ не найдена.
    echo Пожалуйста, установите Python 3.10+ или поместите портативную версию в %PORTABLE_PYTHON%
    pause
    exit /b 1
)

:: -- 2. Создание виртуального окружения ---------------------------------------
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [2/5] Создание виртуального окружения .venv...
    "%PYTHON_CMD%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать виртуальное окружение.
        pause
        exit /b 1
    )
)
echo [2/5] Виртуальное окружение OK

set "PYTHON=%VENV_DIR%\Scripts\python.exe"

:: -- 3. Установка зависимостей -----------------------------------------------
echo [3/5] Проверка и установка зависимостей...

:: Проверяем, установлены ли уже зависимости (по наличию streamlit)
if exist "%VENV_DIR%\Scripts\python.exe" (
    "%PYTHON%" -c "import streamlit" >nul 2>&1
    if not errorlevel 1 (
        echo [3/5] Зависимости уже установлены. Пропуск установки.
        goto skip_install
    )
)

"%PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo Подготовка pip внутри виртуального окружения...
    "%PYTHON%" -m ensurepip --upgrade
)

:: Проверяем наличие офлайн колес
set "HAS_WHEELS=0"
if exist "%OFFLINE_PACKAGES%" (
    dir "%OFFLINE_PACKAGES%\*.whl" >nul 2>&1
    if not errorlevel 1 (
        set "HAS_WHEELS=1"
    )
)

if "%HAS_WHEELS%"=="1" (
    echo Обнаружена папка с офлайн пакетами. Установка офлайн...
    "%PYTHON%" -m pip install --no-index --find-links "%OFFLINE_PACKAGES%" -r "%PROJECT_DIR%\requirements.txt"
) else (
    echo Офлайн пакеты не найдены. Установка через Интернет...
    "%PYTHON%" -m pip install -r "%PROJECT_DIR%\requirements.txt"
)

if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить зависимости.
    pause
    exit /b 1
)
echo [3/5] Зависимости установлены OK

:skip_install

:: -- 4. Проверка и запуск Ollama ---------------------------------------------
echo [4/5] Проверка службы Ollama...

:: Ищем ollama в системе
set "OLLAMA_EXE="
where ollama >nul 2>&1
if not errorlevel 1 (
    set "OLLAMA_EXE=ollama"
) else (
    if exist "%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe" (
        set "OLLAMA_EXE=%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe"
    ) else (
        if exist "%ProgramFiles%\Ollama\ollama.exe" (
            set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"
        )
    )
)

if not defined OLLAMA_EXE (
    echo [ПРЕДУПРЕЖДЕНИЕ] Утилита ollama.exe не найдена в системе.
    echo LLM-анализ (Qwen) будет недоступен. Будет использован стандартный TextRank.
    goto skip_ollama
)

:: Проверяем, запущена ли Ollama на порту 11434
netstat -ano | findstr :11434 >nul 2>&1
if errorlevel 1 (
    echo Ollama не запущена. Запуск службы Ollama в фоновом режиме...
    start "" "%OLLAMA_EXE%" serve
    
    :: Ожидаем запуска порта 11434 (до 30 секунд)
    echo Ожидание инициализации Ollama...
    for /l %%i in (1,1,30) do (
        netstat -ano | findstr :11434 >nul 2>&1
        if not errorlevel 1 (
            goto ollama_started
        )
        timeout /t 1 >nul
    )
    echo [ПРЕДУПРЕЖДЕНИЕ] Ollama не ответила за 30 секунд.
    :ollama_started
)

:: Проверка наличия модели qwen2.5:0.5b
echo Проверка модели qwen2.5:0.5b в Ollama...
"%OLLAMA_EXE%" list | findstr "qwen2.5:0.5b" >nul 2>&1
if errorlevel 1 (
    echo Модель qwen2.5:0.5b не найдена. Попытка скачивания модели...
    "%OLLAMA_EXE%" pull qwen2.5:0.5b
    if errorlevel 1 (
        echo [ПРЕДУПРЕЖДЕНИЕ] Не удалось скачать модель qwen2.5:0.5b. LLM будет недоступна.
    )
)
echo [4/5] Ollama проверена.

:skip_ollama

:: -- 5. Проверка порта и запуск Streamlit ------------------------------------
echo [5/5] Проверка порта 8501...
netstat -ano | findstr :8501 >nul 2>&1
if not errorlevel 1 (
    echo [ПРЕДУПРЕЖДЕНИЕ] Порт 8501 уже занят другим процессом.
    echo Пожалуйста, закройте другие приложения Streamlit или проверьте http://localhost:8501
    pause
)

echo Запуск веб-интерфейса...
echo Открытие браузера: %APP_URL%
echo.

:: Открываем веб-страницу напрямую через проводник
start "" "%APP_URL%"

:: Запускаем streamlit через интерпретатор python
"%PYTHON%" -m streamlit run app.py --server.address localhost --server.port 8501 --server.headless true --server.maxUploadSize 5120

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Streamlit завершился с ошибкой.
    pause
)

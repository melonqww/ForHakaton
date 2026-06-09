@echo off
cd /d "%~dp0.."

echo ============================================
echo   Анализ обращений граждан - Запуск системы
echo ============================================
echo.

:: 1. Проверка Python
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [1/4] Python не найден. Скачивание...
    where winget >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        winget install Python.Python.3.13 -h --accept-package-agreements >nul 2>&1
    ) else (
        echo Скачайте Python с https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo Установка Python завершена. Запустите файл снова.
    pause
    exit /b 0
)

:: 2. Установка зависимостей
echo [1/3] Установка зависимостей...
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q
echo Готово.

:: 3. Проверка Ollama
echo [2/3] Проверка Ollama...
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing -TimeoutSec 2; $ok = $true } catch { $ok = $false }; if (!$ok) { exit 1 }" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Ollama не найдена. Система будет работать без ИИ.
) else (
    echo Ollama подключена.
    powershell -Command "$r = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing | ConvertFrom-Json; $models = $r.models.name -join ' '; if ($models -match 'qwen2.5:0.5b') { exit 0 } else { exit 1 }" >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo Загрузка модели qwen2.5:0.5b...
        start /b /wait cmd /c "ollama pull qwen2.5:0.5b" >nul 2>&1
    )
)
echo.

:: 4. Запуск
echo [3/3] Запуск...
echo.
start http://localhost:8501
python -m streamlit run app.py --server.headless true

if %ERRORLEVEL% neq 0 (
    pause
)


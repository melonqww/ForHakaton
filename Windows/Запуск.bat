@echo off
cd /d "%~dp0.."

python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Python не найден. Установите Python 3.10+ и добавьте его в PATH.
    pause
    exit /b 1
)

echo Запуск интерфейса Streamlit...
python -m streamlit run app.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Ошибка запуска Streamlit. Проверьте окружение Python.
    pause
)

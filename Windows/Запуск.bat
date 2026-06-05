@echo off
cd /d "%~dp0.."
echo Запуск интерфейса Streamlit...
python -m streamlit run app.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Ошибка запуска Streamlit. Проверьте окружение Python.
    pause
)

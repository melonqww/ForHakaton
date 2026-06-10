@echo off
chcp 65001 >nul 2>&1

:: ── Ищем корень проекта (папку с app.py) ──────────────────────────────
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR="

:: Вариант 1: батник лежит в Windows\ → родитель = корень
pushd "%SCRIPT_DIR%.." >nul 2>&1
if exist "%CD%\app.py" (
    set "PROJECT_DIR=%CD%"
    popd >nul
    goto :found_project
)
popd >nul

:: Вариант 2: батник прямо в корне
if exist "%SCRIPT_DIR%app.py" (
    set "PROJECT_DIR=%SCRIPT_DIR%"
    goto :found_project
)

:: Вариант 3: два уровня вверх
pushd "%SCRIPT_DIR%..\.." >nul 2>&1
if exist "%CD%\app.py" (
    set "PROJECT_DIR=%CD%"
    popd >nul
    goto :found_project
)
popd >nul

echo [OSHIBKA] app.py ne najden. Ubedites chto batnik v Windows\ ili v korne proekta.
pause
exit /b 1

:found_project
cd /d "%PROJECT_DIR%"
echo ============================================
echo   Zapusk sistemy analiza obraschenij
echo ============================================
echo.
echo Rabochaya papka: %CD%
echo.

:: ── 1. Python ─────────────────────────────────────────────────────────
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 goto :no_python
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [1/4] %%v OK
goto :check_req

:no_python
echo [1/4] Python ne najden.
where winget >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Ustanovka cherez winget...
    winget install Python.Python.3.13 -h --accept-package-agreements
) else (
    echo Skachayte: https://www.python.org/downloads/
)
pause
exit /b 1

:: ── 2. requirements.txt ────────────────────────────────────────────────
:check_req
if not exist "requirements.txt" (
    echo [OSHIBKA] requirements.txt ne najden v: %CD%
    pause
    exit /b 1
)

:: ── 3. Зависимости ─────────────────────────────────────────────────────
echo [2/4] Ustanovka zavisimostej...
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q
if %ERRORLEVEL% neq 0 (
    echo [OSHIBKA] pip install zavershilsya s oshibkoj.
    echo Poprobuyte vruchnyyu: pip install -r requirements.txt
    pause
    exit /b 1
)
echo [2/4] Zavisimosti OK

:: ── 4. Ollama ──────────────────────────────────────────────────────────
echo [3/4] Proverka Ollama...

:: Проверяем доступность Ollama
powershell -NoProfile -Command "try{$null=iwr http://localhost:11434/api/tags -UseBasicParsing -TimeoutSec 2;exit 0}catch{exit 1}" >nul 2>&1
set "OLLAMA_OK=%ERRORLEVEL%"

if %OLLAMA_OK% neq 0 goto :ollama_start

:: Ollama уже работает — проверяем модель
echo     Ollama OK
ollama list 2>nul | findstr /C:"qwen2.5:0.5b" >nul 2>&1
if %ERRORLEVEL% equ 0 goto :ollama_model_ok
echo     Zagruzka modeli qwen2.5:0.5b (~300MB)...
ollama pull qwen2.5:0.5b
if %ERRORLEVEL% equ 0 (
    echo     Model OK
) else (
    echo     [WARN] Model ne zagruzhena - rabotaem bez II-summarizacii.
)
goto :check_port

:ollama_model_ok
echo     Model qwen2.5:0.5b OK
goto :check_port

:: Ollama не запущена — пробуем запустить
:ollama_start
echo     Ollama ne zapuschena. Pytaemsya zapustit...
where ollama >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo     [WARN] Ollama ne ustanovlena. Skachat: https://ollama.com/download
    goto :check_port
)
start /b ollama serve
timeout /t 5 /nobreak >nul
powershell -NoProfile -Command "try{$null=iwr http://localhost:11434/api/tags -UseBasicParsing -TimeoutSec 3;exit 0}catch{exit 1}" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo     Ollama OK
) else (
    echo     [WARN] Ollama ne otvetila - rabotaem bez II-summarizacii.
)

:: ── 5. Порт 8501 ───────────────────────────────────────────────────────
:check_port
echo [4/4] Zapusk...
powershell -NoProfile -Command "if(Get-NetTCPConnection -LocalPort 8501 -ErrorAction SilentlyContinue){exit 1}else{exit 0}" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo     Port 8501 uzhe zanyat - prilozhenie uzhe rabotaet: http://localhost:8501
    start http://localhost:8501
    pause
    exit /b 0
)

:: ── 6. Запуск Streamlit ────────────────────────────────────────────────
echo     Streamlit iz: %CD%
echo.
timeout /t 2 /nobreak >nul
start http://localhost:8501
python -m streamlit run app.py --server.headless true

if %ERRORLEVEL% neq 0 (
    echo.
    echo [OSHIBKA] Streamlit zavershilsya s oshibkoj.
    echo Poprobuyte: python -m streamlit run app.py
    pause
)

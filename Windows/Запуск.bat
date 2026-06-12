@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

cd /d "%~dp0.."
set "PROJECT_DIR=%CD%"
set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%PROJECT_DIR%\.venv"
set "OFFLINE_PACKAGES=%SCRIPT_DIR%offline_packages_windows"
set "PORTABLE_PYTHON=%SCRIPT_DIR%portable_python_windows\python.exe"
set "APP_URL=http://localhost:8501"

echo ============================================
echo   Sistema analiza obrasheniy - Zapusk
echo ============================================
echo Proekt: %PROJECT_DIR%
echo.

:: -- 1. Poisk Python
set "PYTHON_CMD="
set "PYTHON_ARGS="

if exist "%PORTABLE_PYTHON%" (
    "%PORTABLE_PYTHON%" --version >nul 2>&1
    if not errorlevel 1 (
        "%PORTABLE_PYTHON%" -c "import sys; v=sys.version_info; sys.exit(0 if v>=(3,10) else 1)" >nul 2>&1
        if not errorlevel 1 ( set "PYTHON_CMD=%PORTABLE_PYTHON%" & echo [1/5] Portativny Python OK )
    )
)

if not defined PYTHON_CMD (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -c "import sys; v=sys.version_info; sys.exit(0 if v>=(3,10) else 1)" >nul 2>&1
        if not errorlevel 1 ( set "PYTHON_CMD=py" & set "PYTHON_ARGS=-3" & echo [1/5] py launcher OK )
    )
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; v=sys.version_info; sys.exit(0 if v>=(3,10) else 1)" >nul 2>&1
        if not errorlevel 1 ( set "PYTHON_CMD=python" & echo [1/5] Sistemny python OK )
    )
)

if not defined PYTHON_CMD (
    echo [OSHIBKA] Python 3.10+ ne najden.
    pause & exit /b 1
)

:: -- 2. Virtualnoe okruzhenie
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [2/5] Sozdayu .venv...
    "%PYTHON_CMD%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
    if errorlevel 1 ( echo [OSHIBKA] ne udalos sozdat .venv & pause & exit /b 1 )
)
echo [2/5] .venv OK
set "PYTHON=%VENV_DIR%\Scripts\python.exe"

:: -- 3. Zavisimosti
echo [3/5] Proverka zavisimostej...
"%PYTHON%" -c "import streamlit, docx, reportlab" >nul 2>&1
if not errorlevel 1 ( echo [3/5] Zavisimosti uzhe est. & goto skip_install )

"%PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 ( "%PYTHON%" -m ensurepip --upgrade )

set "HAS_WHEELS=0"
if exist "%OFFLINE_PACKAGES%" (
    dir "%OFFLINE_PACKAGES%\*.whl" >nul 2>&1
    if not errorlevel 1 ( set "HAS_WHEELS=1" )
)

if "%HAS_WHEELS%"=="1" (
    "%PYTHON%" -m pip install --no-index --find-links "%OFFLINE_PACKAGES%" -r "%PROJECT_DIR%\requirements.txt"
) else (
    "%PYTHON%" -m pip install -r "%PROJECT_DIR%\requirements.txt"
)

if errorlevel 1 ( echo [OSHIBKA] ne udalos ustanovit zavisimosti & pause & exit /b 1 )
echo [3/5] Zavisimosti OK

:skip_install

:: -- 4. Ollama
echo [4/5] Proverka Ollama...

set "OLLAMA_EXE="
where ollama >nul 2>&1
if not errorlevel 1 ( set "OLLAMA_EXE=ollama" )
if not defined OLLAMA_EXE (
    if exist "%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe" (
        set "OLLAMA_EXE=%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe"
    )
)
if not defined OLLAMA_EXE (
    if exist "%ProgramFiles%\Ollama\ollama.exe" (
        set "OLLAMA_EXE=%ProgramFiles%\Ollama\ollama.exe"
    )
)

if not defined OLLAMA_EXE (
    echo [WARN] ollama.exe ne najden. Budet ispolzovan TextRank.
    goto skip_ollama
)

:: Esli port 11434 uzhe zanyat
netstat -ano | findstr ":11434 " >nul 2>&1
if not errorlevel 1 (
    "%OLLAMA_EXE%" list >nul 2>&1
    if not errorlevel 1 (
        echo Ollama uzhe zapushena i otvechaet.
        goto check_model
    )
    echo Port 11434 zanyat chuzhim processom. Osvobozhdam...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":11434 "') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    ping -n 3 127.0.0.1 >nul 2>&1
)

echo Ollama ne zapushena. Zapuskayu serve v fone...
start "" "%OLLAMA_EXE%" serve

echo Ozhidanie Ollama (do 30 sek)...
set "OLLAMA_LOOP=0"
:ollama_wait_loop
"%OLLAMA_EXE%" list >nul 2>&1
if not errorlevel 1 goto check_model
ping -n 2 127.0.0.1 >nul 2>&1
set /a OLLAMA_LOOP+=1
if %OLLAMA_LOOP% lss 30 goto ollama_wait_loop
echo [WARN] Ollama ne otvetila za 30 sek. Prodolzhaem bez LLM.
goto skip_ollama

:check_model
echo Proverka modeli qwen2.5:0.5b...
"%OLLAMA_EXE%" list | findstr "qwen2.5:0.5b" >nul 2>&1
if not errorlevel 1 goto check_15b
echo Model 0.5b ne najdena. Skachivayu...
"%OLLAMA_EXE%" pull qwen2.5:0.5b

:check_15b
echo Proverka modeli qwen2.5:1.5b (dlya AI-dokumenta)...
"%OLLAMA_EXE%" list | findstr "qwen2.5:1.5b" >nul 2>&1
if not errorlevel 1 goto ollama_ready
echo Model 1.5b ne najdena. Skachivayu...
"%OLLAMA_EXE%" pull qwen2.5:1.5b

:ollama_ready
echo [4/5] Ollama OK - modeli 0.5b i 1.5b gotovy

:skip_ollama

:: -- 5. Streamlit - ubivayem staryj process esli port 8501 zanyat
echo [5/5] Proverka porta 8501...
netstat -ano | findstr ":8501 " >nul 2>&1
if not errorlevel 1 (
    echo Port 8501 uzhe zanyat. Perezapuskayu Streamlit...
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501 "') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    ping -n 3 127.0.0.1 >nul 2>&1
    echo Port 8501 osvobozhdyon.
)

echo Zapuskayu interfejs...
echo Otkrojte brauzer: %APP_URL%
echo.
start "" "%APP_URL%"

"%PYTHON%" -m streamlit run app.py --server.address localhost --server.port 8501 --server.headless true --server.maxUploadSize 5120

if errorlevel 1 ( echo [OSHIBKA] Streamlit zavershilsya s oshibkoy & pause )

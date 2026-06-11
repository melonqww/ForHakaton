@echo off
setlocal

cd /d "%~dp0"

set "APP_URL=http://localhost:8501"
set "VENV_DIR=%CD%\.venv"
set "OFFLINE_PACKAGES=%CD%\offline_packages_windows"
set "PYTHON_CMD="
set "PYTHON_ARGS="
set "PORTABLE_PYTHON=%CD%\portable_python_windows\python.exe"

echo ============================================
echo   Citizen Requests Analyzer - Web interface
echo ============================================
echo.

if exist "%PORTABLE_PYTHON%" (
    "%PORTABLE_PYTHON%" --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=%PORTABLE_PYTHON%"
    )
)

if not defined PYTHON_CMD (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 --version >nul 2>&1
    )
    if not errorlevel 1 (
        set "PYTHON_CMD=py"
        set "PYTHON_ARGS=-3"
    ) else (
        where python >nul 2>&1
        if not errorlevel 1 (
            python --version >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_CMD=python"
            )
        )
    )
)

if not defined PYTHON_CMD (
    echo [ERROR] Python was not found.
    echo Put portable_python_windows next to this file or install Python 3.10+.
    pause
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    "%PYTHON_CMD%" %PYTHON_ARGS% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

set "PYTHON=%VENV_DIR%\Scripts\python.exe"

echo [2/3] Installing dependencies...
"%PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo Preparing pip inside virtual environment...
    "%PYTHON%" -m ensurepip --upgrade
    if errorlevel 1 (
        echo [ERROR] Failed to prepare pip in virtual environment.
        pause
        exit /b 1
    )
)

if exist "%OFFLINE_PACKAGES%\*.whl" (
    echo Offline package folder found: offline_packages_windows
    "%PYTHON%" -m pip install --no-index --find-links "%OFFLINE_PACKAGES%" -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies from offline packages.
        echo Check that offline_packages_windows contains packages for this Python version.
        pause
        exit /b 1
    )
) else (
    echo [ERROR] Offline package folder offline_packages_windows was not found or is empty.
    echo Internet is not used by this launcher.
    pause
    exit /b 1
)

echo [3/3] Starting web interface...
echo Opening %APP_URL%
echo.

start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 3; Start-Process '%APP_URL%'"
"%PYTHON%" -m streamlit run app.py --server.address localhost --server.port 8501 --server.headless true --server.maxUploadSize 5120

if errorlevel 1 (
    echo.
    echo [ERROR] Streamlit stopped with an error.
    pause
)

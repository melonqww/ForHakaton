@echo off
setlocal

cd /d "%~dp0"

set "PROJECT_DIR=%CD%"
set "VENV_DIR=%PROJECT_DIR%\.venv"

echo Cleaning installed dependencies for demo...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$project=(Resolve-Path '%PROJECT_DIR%').Path; " ^
  "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|streamlit' -and $_.CommandLine -like ('*' + $project + '*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; " ^
  "Start-Sleep -Seconds 1; " ^
  "$venv=Join-Path $project '.venv'; " ^
  "if ((Test-Path -LiteralPath $venv) -and ((Resolve-Path -LiteralPath $venv).Path.StartsWith($project, [System.StringComparison]::OrdinalIgnoreCase))) { Remove-Item -LiteralPath $venv -Recurse -Force -ErrorAction SilentlyContinue }; " ^
  "Get-ChildItem -LiteralPath $project -Recurse -Force -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; " ^
  "Get-ChildItem -LiteralPath $project -Recurse -Force -File -Include '*.pyc','*.pyo' | Remove-Item -Force -ErrorAction SilentlyContinue"

echo Done. Now run "Запуск Windows.bat".
pause

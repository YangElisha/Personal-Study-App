@echo off
rem MonoSpace: double-click to start the local server and open the app in the browser.
rem The FIRST run needs internet once: it creates .venv and installs requirements.txt.
rem After that everything runs offline. Close this window (or press Ctrl+C) to stop.
setlocal
cd /d "%~dp0"
title MonoSpace server

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating the Python environment in .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo.
    echo Could not create .venv. Is Python 3.12 installed and on PATH?
    pause
    exit /b 1
  )
)

rem (Re)install requirements if they changed since the last install.
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
  echo Installing requirements ...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    rem Offline, or the install failed: carry on with what .venv already has, if it can run.
    ".venv\Scripts\python.exe" -c "import fastapi, uvicorn" >nul 2>&1
    if errorlevel 1 (
      echo.
      echo Installing requirements failed and the server cannot run without them.
      echo The first start needs internet once. Connect and double-click start.bat again.
      pause
      exit /b 1
    )
    echo.
    echo WARNING: requirements.txt changed but could not be installed ^(offline?^).
    echo          Starting with the packages already in .venv. Run start.bat again when online.
    echo.
  ) else (
    copy /y requirements.txt ".venv\requirements.installed" >nul
  )
)

".venv\Scripts\python.exe" -m server --open
echo.
echo MonoSpace server stopped.
pause

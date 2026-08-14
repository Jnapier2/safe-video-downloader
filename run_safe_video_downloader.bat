@echo off
REM Copyright 2026 Gateway Information Group LLC. All rights reserved.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || (
    echo ERROR: The Safe Video Downloader project folder could not be opened.
    exit /b 2
)

set "SVD_SCRIPT=%~dp0safe_media_downloader.py"
if not exist "%SVD_SCRIPT%" (
    echo ERROR: safe_media_downloader.py is missing beside this launcher.
    exit /b 2
)

set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not defined PYTHON_EXE (
    where py.exe >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py.exe"
        set "PYTHON_ARGS=-3"
    )
)

if not defined PYTHON_EXE (
    where python.exe >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python.exe"
)

if not defined PYTHON_EXE (
    echo ERROR: Python 3.11 or newer was not found.
    echo See README.md for setup instructions.
    exit /b 3
)

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11 or newer is required.
    exit /b 3
)

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import yt_dlp" >nul 2>&1
if errorlevel 1 (
    echo ERROR: The project dependency is not installed.
    echo Run: "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
    exit /b 4
)

if "%~1"=="" (
    "%PYTHON_EXE%" %PYTHON_ARGS% "%SVD_SCRIPT%" --gui
) else (
    "%PYTHON_EXE%" %PYTHON_ARGS% "%SVD_SCRIPT%" %*
)
exit /b %errorlevel%

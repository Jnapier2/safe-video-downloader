@echo off
setlocal
cd /d "%~dp0" || exit /b 1

set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

if not defined PYTHON_EXE (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    )
)

if not defined PYTHON_EXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    echo Python 3.11 or newer was not found.
    echo See README.md for setup instructions.
    exit /b 1
)

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 or newer is required.
    exit /b 1
)

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import yt_dlp" >nul 2>nul
if errorlevel 1 (
    echo The project dependency is not installed.
    echo Run: "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
    exit /b 1
)

"%PYTHON_EXE%" %PYTHON_ARGS% safe_media_downloader.py --gui
exit /b %ERRORLEVEL%

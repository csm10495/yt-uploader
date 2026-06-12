@echo off
setlocal

:: Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Path to the virtual environment
set "VENV_DIR=%SCRIPT_DIR%venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "PIP_EXE=%VENV_DIR%\Scripts\pip.exe"
set "REQUIREMENTS_FILE=%SCRIPT_DIR%requirements-web.txt"
set "INSTALLED_MARKER=%VENV_DIR%\.requirements_web_installed"

:: Check if venv exists, create if not
if not exist "%PYTHON_EXE%" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create virtual environment. Make sure Python is installed.
        pause
        exit /b 1
    )
)

:: Check if requirements need to be installed/updated
set "NEEDS_INSTALL=0"

if not exist "%INSTALLED_MARKER%" (
    set "NEEDS_INSTALL=1"
) else (
    fc /b "%REQUIREMENTS_FILE%" "%INSTALLED_MARKER%" >nul 2>&1
    if errorlevel 1 (
        set "NEEDS_INSTALL=1"
    )
)

if "%NEEDS_INSTALL%"=="1" (
    echo Installing/updating dependencies...
    "%PIP_EXE%" install -r "%REQUIREMENTS_FILE%"
    if errorlevel 1 (
        echo Failed to install dependencies.
        pause
        exit /b 1
    )
    copy /y "%REQUIREMENTS_FILE%" "%INSTALLED_MARKER%" >nul
    echo.
    echo Dependencies installed successfully!
    echo.
)

:: Run the web app (it opens your browser automatically at http://localhost:5000)
echo Starting YouTube Uploader web app...
echo Open http://localhost:5000 in your browser if it doesn't open automatically.
echo Press Ctrl+C in this window to stop the server.
echo.
"%PYTHON_EXE%" "%SCRIPT_DIR%app.py"

if errorlevel 1 (
    pause
)

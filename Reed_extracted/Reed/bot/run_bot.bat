@echo off
title PolyM Polymarket Paper Trading Bot
echo =======================================================
echo   PolyM PAPER TRADING BOT - STARTUP SCRIPT
echo =======================================================
echo.

:: Checking if Python is installed
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not added to PATH. 
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    pause
    exit /b
)

:: Check if virtual environment exists
IF NOT EXIST ".venv" (
    echo [INFO] Virtual environment not found. Creating one...
    python -m venv .venv
    
    echo [INFO] Activating virtual environment...
    call .venv\Scripts\activate.bat
    
    echo [INFO] Installing required libraries...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    
    echo [INFO] Setup complete.
) ELSE (
    echo [INFO] Activating existing virtual environment...
    call .venv\Scripts\activate.bat
)

echo.
echo [INFO] Starting PolyM Bot...
echo [INFO] Press Ctrl+C to stop the bot cleanly.
echo.

:: Run the main bot script
python bot_main.py

echo.
echo [INFO] Bot stopped. Have a good day!
pause

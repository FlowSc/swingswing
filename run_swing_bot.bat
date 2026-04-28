@echo off
setlocal

cd /d "%~dp0"

if not exist "kis_config.local.env" (
    echo Missing kis_config.local.env
    echo Run setup_kis_config.bat first.
    pause
    exit /b 1
)

if not exist ".venv\" (
    echo Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Python launcher not found or virtual environment creation failed.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo.
    echo ERROR: Failed to activate the virtual environment.
    pause
    exit /b 1
)

echo Installing required packages...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed.
    pause
    exit /b 1
)

echo Running unified swing bot...
python run_swing_bot.py
set "EXIT_CODE=%errorlevel%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Done. Check output\positions.json and output\trade_log.csv.
) else (
    echo Unified swing bot failed. Exit code: %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%

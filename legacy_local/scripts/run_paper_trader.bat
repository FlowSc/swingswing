@echo off
setlocal

cd /d "%~dp0"

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
python -m pip install finance-datareader pandas openpyxl
if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed.
    pause
    exit /b 1
)

echo Running paper_trader.py...
python paper_trader.py
set "EXIT_CODE=%errorlevel%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Done. Check output\positions.json and output\trade_log.csv.
) else (
    echo Script finished with errors. Exit code: %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%

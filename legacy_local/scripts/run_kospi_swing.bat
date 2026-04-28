@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\" (
    echo Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Python launcher not found or virtual environment creation failed.
        echo Install Python 3.11+ and make sure "Add python.exe to PATH" is enabled.
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

echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo.
    echo ERROR: pip upgrade failed.
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

echo Running kospi_swing.py...
python kospi_swing.py
set "EXIT_CODE=%errorlevel%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Script finished successfully.
) else (
    echo Script finished with errors. Exit code: %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%

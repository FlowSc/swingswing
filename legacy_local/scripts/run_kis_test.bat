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
python -m pip install requests
if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed.
    pause
    exit /b 1
)

if not exist "kis_config.local.env" (
    echo.
    echo Missing kis_config.local.env. Run setup_kis_config.bat first.
    pause
    exit /b 1
)

echo.
echo Running KIS paper connection test...
python kis_test_connection.py
set "EXIT_CODE=%errorlevel%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Connection test completed.
) else (
    echo Connection test failed. Exit code: %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%

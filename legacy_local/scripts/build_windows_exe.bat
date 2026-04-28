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

python -m pip install --upgrade pip
if errorlevel 1 (
    echo.
    echo ERROR: pip upgrade failed.
    pause
    exit /b 1
)

python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

echo Building EXE with PyInstaller...
python -m PyInstaller --onefile --clean --noconsole --name kospi_momentum kospi_momentum.py
set "EXIT_CODE=%errorlevel%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Build completed.
    echo EXE file: dist\kospi_momentum.exe
) else (
    echo Build failed. Exit code: %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%

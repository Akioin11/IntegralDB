@echo on
setlocal enabledelayedexpansion

:: =====================================================
::   PYTHON CHECK + AUTO-INSTALL + STREAMLIT LAUNCHER
:: =====================================================

set "PYTHON_URL=https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe"
set "PYTHON_INSTALLER=%TEMP%\python_installer.exe"
set "STREAMLIT_APP=dashboard/streamlit_app.py"

echo =====================================================
echo   PYTHON CHECK ^& STREAMLIT EXECUTION
echo =====================================================
echo.

:: ====== MOVE TO SCRIPT DIRECTORY ======
cd /d "%~dp0"

:: ====== CHECK PYTHON ======
where python >nul 2>nul
if %errorlevel%==0 (
    echo [OK] Python is already installed.
) else (
    echo [INFO] Python not found. Installing silently...
    
    :: ====== DOWNLOAD PYTHON ======
    powershell -Command "Invoke-WebRequest '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%'" || (
        echo [ERROR] Failed to download Python installer.
        pause
        exit /b 1
    )

    :: ====== INSTALL PYTHON ======
    echo [INFO] Installing Python silently...
    "%PYTHON_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 SimpleInstall=1 || (
        echo [ERROR] Python installation failed.
        pause
        exit /b 1
    )

    :: ====== VERIFY INSTALL ======
    where python >nul 2>nul
    if %errorlevel%==0 (
        echo [OK] Python installation successful.
    ) else (
        echo [ERROR] Python not detected after installation.
        pause
        exit /b 1
    )
)

echo.
echo [INFO] Launching Streamlit app: %STREAMLIT_APP%
echo =====================================================
echo.

:: ====== RUN STREAMLIT ======
python -m streamlit run "%STREAMLIT_APP%"
if %errorlevel% neq 0 (
    echo [ERROR] Streamlit execution failed.
    pause
    exit /b %errorlevel%
)

echo.
echo [INFO] Streamlit process ended.
echo [DONE] Execution complete.
pause

endlocal
exit /b 0

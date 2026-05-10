@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   OCR Backend Server
echo ========================================
echo.

:: ============================================================
::  Step 0: Resolve Anaconda path
:: ============================================================
set "CONDA_PATH_FILE=%~dp0.conda_path"
set "CONDA_ROOT="

:: 0a - Read saved path
if exist "%CONDA_PATH_FILE%" (
    set /p SAVED=<"%CONDA_PATH_FILE%"
    set "SAVED=!SAVED:"=!"
    if exist "!SAVED!\condabin\conda.bat"    set "CONDA_ROOT=!SAVED!"
    if not defined CONDA_ROOT if exist "!SAVED!\Scripts\conda.exe"  set "CONDA_ROOT=!SAVED!"
    if defined CONDA_ROOT (
        echo   Using saved Anaconda: !CONDA_ROOT!
        goto :step0_done
    )
    echo   [WARN] Saved path invalid, re-detecting...
)

:: 0b - Registry (user install)
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Python\ContinuumAnalytics" /s 2^>nul ^| findstr /r "^.*InstallPath.*REG_SZ"') do set "CONDA_ROOT=%%b"

:: 0c - Registry (system-wide install)
if not defined CONDA_ROOT (
    for /f "tokens=2,*" %%a in ('reg query "HKLM\Software\Python\ContinuumAnalytics" /s 2^>nul ^| findstr /r "^.*InstallPath.*REG_SZ"') do set "CONDA_ROOT=%%b"
)

:: 0d - Common paths
if not defined CONDA_ROOT if exist "%USERPROFILE%\Anaconda3\condabin\conda.bat"     set "CONDA_ROOT=%USERPROFILE%\Anaconda3"
if not defined CONDA_ROOT if exist "%USERPROFILE%\miniconda3\condabin\conda.bat"     set "CONDA_ROOT=%USERPROFILE%\miniconda3"
if not defined CONDA_ROOT if exist "%USERPROFILE%\Miniconda3\condabin\conda.bat"     set "CONDA_ROOT=%USERPROFILE%\Miniconda3"
if not defined CONDA_ROOT if exist "D:\SOFTWARE\Anaconda\condabin\conda.bat"         set "CONDA_ROOT=D:\SOFTWARE\Anaconda"
if not defined CONDA_ROOT if exist "%PROGRAMDATA%\Anaconda3\condabin\conda.bat"      set "CONDA_ROOT=%PROGRAMDATA%\Anaconda3"
if not defined CONDA_ROOT if exist "%PROGRAMDATA%\miniconda3\condabin\conda.bat"      set "CONDA_ROOT=%PROGRAMDATA%\miniconda3"
if not defined CONDA_ROOT if exist "%PROGRAMDATA%\Miniconda3\condabin\conda.bat"      set "CONDA_ROOT=%PROGRAMDATA%\Miniconda3"

:: 0e - Scan drive roots
if not defined CONDA_ROOT (
    for %%D in (C D E F G H I J K) do (
        if exist "%%D:\Anaconda3\condabin\conda.bat"    set "CONDA_ROOT=%%D:\Anaconda3"
        if exist "%%D:\Anaconda\condabin\conda.bat"      set "CONDA_ROOT=%%D:\Anaconda"
        if exist "%%D:\miniconda3\condabin\conda.bat"    set "CONDA_ROOT=%%D:\miniconda3"
        if exist "%%D:\Miniconda3\condabin\conda.bat"    set "CONDA_ROOT=%%D:\Miniconda3"
        if exist "%%D:\Anaconda\Scripts\conda.exe"       set "CONDA_ROOT=%%D:\Anaconda"
        if exist "%%D:\Anaconda3\Scripts\conda.exe"      set "CONDA_ROOT=%%D:\Anaconda3"
        if defined CONDA_ROOT goto :step0_done
    )
)

:: 0f - Prompt user
:prompt_conda
echo.
echo   Anaconda / Miniconda not found automatically.
echo   Please enter your installation path.
echo   Example: D:\SOFTWARE\Anaconda
echo.
set "CONDA_ROOT="
set /p "CONDA_ROOT=Path: "
if "!CONDA_ROOT!"=="" (
    echo   [ERROR] Path cannot be empty.
    goto :prompt_conda
)
:: Strip quotes & trailing backslash
set "CONDA_ROOT=!CONDA_ROOT:"=!"
if "!CONDA_ROOT:~-1!"=="\" set "CONDA_ROOT=!CONDA_ROOT:~0,-1!"

if not exist "!CONDA_ROOT!\condabin\conda.bat" if not exist "!CONDA_ROOT!\Scripts\conda.exe" (
    echo   [ERROR] conda.bat / conda.exe not found at "!CONDA_ROOT!"
    goto :prompt_conda
)

:: Save for next time
echo !CONDA_ROOT!>"%CONDA_PATH_FILE%"
echo   Path saved.

:step0_done
echo.
set "CONDA_CMD="
if exist "!CONDA_ROOT!\condabin\conda.bat" set "CONDA_CMD=!CONDA_ROOT!\condabin\conda.bat"
if not defined CONDA_CMD if exist "!CONDA_ROOT!\Scripts\conda.exe" set "CONDA_CMD=!CONDA_ROOT!\Scripts\conda.exe"

:: ============================================================
::  Activate environment
:: ============================================================
call "%CONDA_CMD%" activate PaddleOCR-Server 2>nul
if errorlevel 1 (
    echo   [INFO] PaddleOCR-Server not found, trying base...
    call "%CONDA_CMD%" activate base 2>nul
    if errorlevel 1 (
        echo   [ERROR] Cannot activate any conda environment
        pause
        exit /b 1
    )
)

:: ============================================================
::  Verify Python
:: ============================================================
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python not found in active environment
    pause
    exit /b 1
)

python --version

cd /d "%~dp0backend"
echo   [OK] Working dir: %CD%
echo   [OK] Dependencies OK
echo.
echo   Starting backend at http://localhost:8000
echo   Press Ctrl+C to stop
echo ========================================

python main.py

echo Backend stopped
pause

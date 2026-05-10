@echo off

echo ========================================
echo   OCR Web Tool - Starting All
echo ========================================
echo.

echo [1/2] Starting Backend...
start "OCR Backend" cmd /k "call %~dp0start_backend.bat"

timeout /t 3 /nobreak >nul

echo [2/2] Starting Frontend...
start "OCR Frontend" cmd /k "cd /d %~dp0frontend && cmd /c npm run dev"

echo.
echo ========================================
echo   Services Started!
echo ========================================
echo.
echo   Frontend: http://localhost:5173
echo   Backend:  http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo.
echo   OCR Server: http://localhost:7950 (start separately)
echo.
echo   Close this window won't stop services
echo   Press Ctrl+C in each window to stop
echo.
pause

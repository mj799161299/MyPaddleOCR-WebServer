@echo off
cd /d "%~dp0frontend"
echo Starting OCR Frontend...
echo.
echo Frontend: http://localhost:5173
echo.
echo Press Ctrl+C to stop
echo.
cmd /c npm run dev
pause

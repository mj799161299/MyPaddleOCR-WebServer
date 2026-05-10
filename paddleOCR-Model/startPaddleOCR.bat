@echo off
chcp 65001 >nul
title PaddleOCR-VL-1.5
set "MODEL_PATH=.\PaddleOCR-VL-1.5.gguf"
set "MMPROJ_PATH=.\PaddleOCR-VL-1.5-mmproj.gguf"
set "PORT=7950"

echo ========================================
echo PaddleOCR VL 1.5
echo ========================================
echo.

.\llama-b9095-bin-win-cuda-12.4-x64\llama-server.exe ^
  -m "%MODEL_PATH%" ^
  --mmproj %MMPROJ_PATH% ^
  --port 7950 ^
  --host 0.0.0.0 ^
  --temp 0
echo.
if %errorlevel% neq 0 (
    echo [错误] 启动失败
) else (
    echo 服务已停止
)
pause
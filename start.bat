@echo off
REM Aesir AI Service 一键启动
REM 用法：双击本文件，或在终端执行 start.bat [端口]
REM 可选环境变量（默认无需设置）：
REM   AESIR_ASR_BACKEND=mock|faster_whisper   语音识别后端
REM   AESIR_PARSER_BACKEND=rule|llm            指令解析后端
REM 默认端口 8000，可用第一个参数覆盖，例如：start.bat 8001

setlocal
cd /d "%~dp0"

set PORT=%1
if "%PORT%"=="" set PORT=8000

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv，请先执行：
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo [INFO] 启动 Aesir AI Service：http://127.0.0.1:%PORT%
echo [INFO] 接口文档：http://127.0.0.1:%PORT%/docs
echo [INFO] 按 Ctrl+C 停止服务
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload

endlocal

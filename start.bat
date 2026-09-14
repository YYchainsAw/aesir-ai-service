@echo off
chcp 65001 >nul
REM Aesir AI Service one-click launcher
REM Usage:
REM   start.bat            start server only (default port 8000)
REM   start.bat 8001       start server on a given port
REM   start.bat chat       start server (reuse if running) and enter terminal chat
REM   start.bat chat 8001  given port + terminal chat
REM Optional env vars (defaults in .env.example):
REM   AESIR_ASR_BACKEND=mock/faster_whisper      ASR backend
REM   AESIR_PARSER_BACKEND=rule/llm              parser backend
REM   AESIR_COMPANION_BACKEND=mock/llm           companion chat backend
REM NOTE: keep REM lines ASCII-only; cmd parses non-ASCII REM under the
REM       pre-chcp codepage and garbles multi-byte sequences.

setlocal
cd /d "%~dp0"

set MODE=%1
set PORT=%2
if "%PORT%"=="" set PORT=8000

if /i not "%MODE%"=="chat" (
    if not "%MODE%"=="" set PORT=%MODE%
)

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv，请先执行:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

if /i not "%MODE%"=="chat" goto run_server

REM ---- chat mode: reuse running server, else start minimized in background ----
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:%PORT%/health 2>nul | findstr "200" >nul
if %errorlevel%==0 (
    echo [INFO] 服务已在 http://127.0.0.1:%PORT% 运行, 直接进入对话.
) else (
    echo [INFO] 正在启动服务 http://127.0.0.1:%PORT% ...
    start "Aesir AI Service" /min ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
)
echo [INFO] 进入终端对话(/help 查看调试命令，/quit 退出；服务窗口留在后台)。
".venv\Scripts\python.exe" -m scripts.chat_console --port %PORT%
goto end

:run_server
echo [INFO] 启动 Aesir AI Service(http://127.0.0.1:%PORT%)
echo [INFO] 接口文档:http://127.0.0.1:%PORT%/docs
echo [INFO] 按 Ctrl+C 停止服务
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload

:end
endlocal

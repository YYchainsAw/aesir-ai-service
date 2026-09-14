@echo off
REM Aesir AI Service 一键启动
REM 用法（双击或在终端执行）：
REM   start.bat            仅启动服务（默认端口 8000）
REM   start.bat 8001       指定端口启动服务
REM   start.bat chat       启动服务并进入终端对话（服务已运行则直接复用）
REM   start.bat chat 8001  指定端口 + 终端对话
REM 可选环境变量（默认值见 .env.example）：
REM   AESIR_ASR_BACKEND=mock|faster_whisper   语音识别后端
REM   AESIR_PARSER_BACKEND=rule|llm           指令解析后端
REM   AESIR_COMPANION_BACKEND=mock|llm        陪伴对话后端

setlocal
cd /d "%~dp0"
chcp 65001 >nul

set MODE=%1
set PORT=%2
if "%PORT%"=="" set PORT=8000

if /i not "%MODE%"=="chat" (
    if not "%MODE%"=="" set PORT=%MODE%
)

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境 .venv，请先执行：
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

if /i not "%MODE%"=="chat" goto run_server

REM ---- chat 模式：服务已运行则复用，否则后台启动 ----
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:%PORT%/health 2>nul | findstr "200" >nul
if %errorlevel%==0 (
    echo [INFO] 服务已在 http://127.0.0.1:%PORT% 运行，直接进入对话。
) else (
    echo [INFO] 正在启动服务（http://127.0.0.1:%PORT%）……
    start "Aesir AI Service" /min ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
)
echo [INFO] 进入终端对话（/help 查看调试命令，/quit 退出；服务窗口留在后台）。
".venv\Scripts\python.exe" -m scripts.chat_console --port %PORT%
goto end

:run_server
echo [INFO] 启动 Aesir AI Service（http://127.0.0.1:%PORT%）
echo [INFO] 接口文档：http://127.0.0.1:%PORT%/docs
echo [INFO] 按 Ctrl+C 停止服务
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT% --reload

:end
endlocal

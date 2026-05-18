@echo off
chcp 65001 >nul
echo ================================================
echo   BidMaster Pro 快速启动
echo ================================================
echo.

REM 检查虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo [!] 虚拟环境不存在，正在创建...
    python -m venv venv
    if errorlevel 1 (
        echo [X] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [√] 虚拟环境创建成功
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 检查依赖
echo [*] 检查依赖...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo [!] 依赖未安装，正在安装...
    pip install -e .
    if errorlevel 1 (
        echo [X] 依赖安装失败
        pause
        exit /b 1
    )
)
echo [√] 依赖已安装

REM 检查 .env 文件
if not exist ".env" (
    echo [!] .env 文件不存在，正在从 .env.example 创建...
    copy .env.example .env >nul
    echo [√] 已创建 .env 文件
    echo [!] 请编辑 .env 文件填写 API Key
)

echo.
echo ================================================
echo   启动 FastAPI 服务
echo ================================================
echo   访问地址: http://localhost:8000
echo   API 文档: http://localhost:8000/docs
echo ================================================
echo.
echo 按 Ctrl+C 停止服务
echo.

uvicorn services.main:app --host 0.0.0.0 --port 8000 --reload

pause

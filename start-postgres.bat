@echo off
chcp 65001 >nul
setlocal
set "PGBIN=%~dp0.pgsql\extracted\pgsql\bin"
set "PGDATA=%~dp0.pgsql\data"
set "PGLOG=%~dp0.pgsql\pg.log"

if not exist "%PGBIN%\postgres.exe" (
    echo [X] 未找到 PostgreSQL 二进制，请先运行初始化步骤
    exit /b 1
)
if not exist "%PGDATA%\PG_VERSION" (
    echo [X] 数据目录未初始化: %PGDATA%
    exit /b 1
)

"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p 5432 >nul 2>&1
if %errorlevel%==0 (
    echo [√] PostgreSQL 已在运行 (127.0.0.1:5432)
    exit /b 0
)

echo [*] 启动 PostgreSQL ...
start "BidMaster-PostgreSQL" /min "%PGBIN%\postgres.exe" -D "%PGDATA%" >>"%PGLOG%" 2>&1

set /a tries=0
:wait
"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p 5432 >nul 2>&1
if %errorlevel%==0 (
    echo [√] PostgreSQL 启动成功 (127.0.0.1:5432)
    exit /b 0
)
set /a tries+=1
if %tries% geq 15 (
    echo [X] PostgreSQL 启动超时，请查看日志: %PGLOG%
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait

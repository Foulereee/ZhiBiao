@echo off
chcp 65001 >nul
setlocal
set "PGBIN=%~dp0.pgsql\extracted\pgsql\bin"
set "PGDATA=%~dp0.pgsql\data"

if not exist "%PGBIN%\pg_ctl.exe" (
    echo [X] 未找到 pg_ctl.exe
    exit /b 1
)

"%PGBIN%\pg_ctl.exe" -D "%PGDATA%" stop -m fast
if %errorlevel%==0 (
    echo [√] PostgreSQL 已停止
) else (
    echo [!] pg_ctl 停止失败，尝试用 taskkill 结束 postgres 进程...
    taskkill /IM postgres.exe /F
)
exit /b 0

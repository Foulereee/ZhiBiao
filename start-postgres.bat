@echo off
rem ============================================================
rem  Start the bundled portable PostgreSQL  (ASCII only, on purpose)
rem
rem  Do NOT add "chcp 65001" to this file: cmd.exe re-reads a batch
rem  file at byte offsets computed with the PREVIOUS code page, so
rem  switching to 65001 halfway makes cmd skip every following line and
rem  the script silently does nothing (reproduced on Windows 11 zh-CN).
rem ============================================================
setlocal
set "PGBIN=%~dp0.pgsql\extracted\pgsql\bin"
set "PGDATA=%~dp0.pgsql\data"
set "PGLOG=%~dp0.pgsql\pg.log"

if not exist "%PGBIN%\postgres.exe" (
    echo [X] PostgreSQL binaries not found: %PGBIN%
    echo     Expected layout: .pgsql\extracted\pgsql\bin\postgres.exe
    exit /b 1
)
if not exist "%PGDATA%\PG_VERSION" (
    echo [X] data directory not initialized: %PGDATA%
    exit /b 1
)

"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p 5432 >nul 2>&1
if %errorlevel%==0 (
    echo [OK] PostgreSQL already running on 127.0.0.1:5432
    exit /b 0
)

echo [*] starting PostgreSQL ...
start "BidMaster-PostgreSQL" /min "%PGBIN%\postgres.exe" -D "%PGDATA%" >>"%PGLOG%" 2>&1

set /a tries=0
:wait
"%PGBIN%\pg_isready.exe" -h 127.0.0.1 -p 5432 >nul 2>&1
if %errorlevel%==0 (
    echo [OK] PostgreSQL started on 127.0.0.1:5432
    exit /b 0
)
set /a tries+=1
if %tries% geq 15 (
    echo [X] timed out waiting for PostgreSQL, see log: %PGLOG%
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait
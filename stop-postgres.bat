@echo off
rem ASCII only, on purpose - see start-postgres.bat for the reason.
setlocal
set "PGBIN=%~dp0.pgsql\extracted\pgsql\bin"
set "PGDATA=%~dp0.pgsql\data"

if not exist "%PGBIN%\pg_ctl.exe" (
    echo [X] pg_ctl.exe not found: %PGBIN%
    exit /b 1
)

"%PGBIN%\pg_ctl.exe" -D "%PGDATA%" stop -m fast
if %errorlevel%==0 (
    echo [OK] PostgreSQL stopped
    exit /b 0
)

rem Fallback: terminate ONLY the postmaster recorded in THIS data directory.
rem Never use "taskkill /IM postgres.exe /F" - that kills unrelated instances
rem (including a production database on the same machine).
if not exist "%PGDATA%\postmaster.pid" (
    echo [!] pg_ctl stop failed and no postmaster.pid - nothing to stop
    exit /b 1
)
set /p PGPID=<"%PGDATA%\postmaster.pid"
echo [!] pg_ctl stop failed, terminating pid %PGPID% only ...
taskkill /PID %PGPID% /F
exit /b 0
@echo off
rem ---------------------------------------------------------------------------
rem  Stops whatever start-all.bat left running.
rem
rem  Closing the two windows is normally enough. This is for the case it is
rem  not: uvicorn --reload runs the server in a child process, and if the
rem  parent is killed rather than closed, the child keeps the port. The next
rem  start then refuses with "port already in use" and nothing on screen says
rem  which process is holding it.
rem
rem    stop-all.bat            frees 8000 and 3000
rem    stop-all.bat mock       frees 8001 and 3000
rem    stop-all.bat api 3100   frees 8000 and 3100
rem ---------------------------------------------------------------------------
setlocal enabledelayedexpansion

if /i "%~1"=="mock" (set "API_PORT=8001") else (set "API_PORT=8000")
set "PORT=%~2"
if "%PORT%"=="" set "PORT=3000"

for %%P in (%API_PORT% %PORT%) do (
    set "FOUND="
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr /r /c:":%%P .*LISTENING"') do (
        if not "%%A"=="0" (
            echo Stopping the process on port %%P, pid %%A.
            taskkill /F /T /PID %%A >nul 2>&1
            set "FOUND=1"
        )
    )
    if not defined FOUND echo Nothing was listening on port %%P.
)

echo.
echo Done.
endlocal

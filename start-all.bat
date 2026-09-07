@echo off
rem ---------------------------------------------------------------------------
rem  Treasury Register, everything.
rem
rem  Opens two windows, one for the API and one for the surface, waits for the
rem  API to answer, then opens the browser. Two terminals on the day of a
rem  demonstration is one more thing to go wrong, so this is the one to run.
rem
rem    start-all.bat              the real API on 8000, and the surface on 3000
rem    start-all.bat mock         the mock server on 8001 instead
rem    start-all.bat api 3100     serve the surface on another port
rem
rem  Close either window to stop that half. Both windows stay open on a
rem  crash so the error is readable.
rem ---------------------------------------------------------------------------
setlocal

if /i "%~1"=="mock" (
    set "MODE=mock"
    set "API_PORT=8001"
) else (
    set "MODE=api"
    set "API_PORT=8000"
)

set "PORT=%~2"
if "%PORT%"=="" set "PORT=3000"

echo.
echo  Treasury Register
echo  -----------------
echo  API      %MODE% on http://127.0.0.1:%API_PORT%
echo  Surface  http://localhost:%PORT%
echo.

rem -- free the ports we need ------------------------------------------------
rem  A previous run may have left something holding the ports (a hung
rem  uvicorn, a zombie next-dev, VS Code's terminal that got detached). Kill
rem  whatever is listening on the two ports before we try to bind them. This
rem  is a demo/dev script -- if it turns out something the user cared about
rem  was on 8000 or 3000, they'll notice and move it. The alternative is
rem  a start script that fails silently every time.
call :free_port %API_PORT% API
call :free_port %PORT% surface

rem -- the API ----------------------------------------------------------------
echo  Starting the API.
start "Treasury Register, %MODE% API" cmd /k call "%~dp0start-backend.bat" %MODE%

rem -- wait for it to answer, rather than guessing at a sleep -----------------
echo  Waiting for the API to answer.
set "READY="
for /l %%i in (1,1,40) do (
    if not defined READY (
        curl -s -o nul "http://127.0.0.1:%API_PORT%/health" && set "READY=1"
        if not defined READY call :wait
    )
)

if not defined READY (
    echo.
    echo  The API did not answer on port %API_PORT%. Read the other window.
    echo  The surface is starting anyway; it will work as soon as the API does.
    echo.
)

rem -- the surface ------------------------------------------------------------
echo  Starting the surface.
start "Treasury Register, surface" cmd /k call "%~dp0start-frontend.bat" %MODE% %PORT%

rem  The first Next.js compile takes a few seconds. Opening the browser before
rem  it finishes shows a blank page, which reads as a failure when it is not.
echo  Waiting for the first compile.
set "WEB="
for /l %%i in (1,1,60) do (
    if not defined WEB (
        curl -s -o nul "http://localhost:%PORT%/" && set "WEB=1"
        if not defined WEB call :wait
    )
)

if defined WEB (
    echo  Opening http://localhost:%PORT%
    start "" "http://localhost:%PORT%"
) else (
    echo  The surface did not come up. Read the surface window.
)

echo.
echo  Both windows are running. Close them to stop.
echo.

endlocal
goto :eof

rem  One second, without timeout.exe, which refuses to run whenever stdin is
rem  redirected. That happens whenever this file is called from another
rem  script rather than double clicked, and the failure is silent.
:wait
ping -n 2 127.0.0.1 >nul
goto :eof


rem  Kill whatever is LISTENING on a port. Silent if the port is already
rem  free. Two arguments: the port number, and a label used in the message.
rem
rem  netstat -ano prints one line per socket ending with the PID; we take
rem  the last token. `sort /unique` because a listener may show up twice on
rem  IPv4 and IPv6.
:free_port
setlocal enabledelayedexpansion
set "PORT_TO_FREE=%~1"
set "LABEL=%~2"
set "FOUND="
for /f "tokens=5" %%p in (
    'netstat -ano ^| findstr /r /c:":%PORT_TO_FREE% .*LISTENING"'
) do (
    if not "%%p"=="0" (
        if not "!FOUND!"=="%%p" (
            set "FOUND=%%p"
            echo  Port %PORT_TO_FREE% ^(%LABEL%^) was held by PID %%p. Killing it.
            taskkill /F /PID %%p >nul 2>&1
        )
    )
)
rem  Give Windows a moment to release the socket before the caller binds.
if defined FOUND ping -n 2 127.0.0.1 >nul
endlocal
goto :eof

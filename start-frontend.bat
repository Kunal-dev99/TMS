@echo off
rem ---------------------------------------------------------------------------
rem  Treasury Register, the surface.
rem
rem  Next.js rewrites /api to whichever API is running, so the browser only
rem  ever sees one origin and there is no cross origin configuration anywhere.
rem
rem    start-frontend.bat              reads the real API on 8000, serves on 3000
rem    start-frontend.bat mock         reads the mock on 8001
rem    start-frontend.bat api 3100     serves on a different port
rem ---------------------------------------------------------------------------
setlocal

cd /d "%~dp0frontend" || (echo Could not find the frontend folder. & pause & exit /b 1)

if /i "%~1"=="mock" (set "TREASURY_API_ORIGIN=http://127.0.0.1:8001") else (set "TREASURY_API_ORIGIN=http://127.0.0.1:8000")

rem Next reads PORT. Nothing in the scripts hard codes 3000 twice.
set "PORT=%~2"
if "%PORT%"=="" set "PORT=3000"

if not exist "node_modules" (
    echo Installing the frontend dependencies. This runs once.
    call npm install --no-audit --no-fund
    if errorlevel 1 (echo npm install failed. & pause & exit /b 1)
)

echo.
echo Reading the API at %TREASURY_API_ORIGIN%
echo Serving the surface on http://localhost:%PORT%
echo Close this window to stop it.
echo.
call npm run dev

endlocal

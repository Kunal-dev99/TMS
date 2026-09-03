@echo off
rem ---------------------------------------------------------------------------
rem  Treasury Register, the API side.
rem
rem  Builds the schema from the migrations, loads the seed if there is no
rem  database yet, and serves the API.
rem
rem    start-backend.bat          the real API on 8000
rem    start-backend.bat mock     the mock server on 8001
rem
rem  Phase one put groups 1, 2, 5 and 6 live, which is everything the surface
rem  reads. The mock still answers the twenty-two endpoints whose tables
rem  arrive in phases two and three.
rem ---------------------------------------------------------------------------
setlocal

cd /d "%~dp0backend" || (echo Could not find the backend folder. & pause & exit /b 1)

if /i "%~1"=="mock" (
    set "MODULE=mock.main:app"
    set "PORT=8001"
    set "LABEL=mock"
) else (
    set "MODULE=app.main:app"
    set "PORT=8000"
    set "LABEL=api"
)

echo.
echo [1/3] Building the schema from the migrations.
python -m alembic upgrade head
if errorlevel 1 (
    echo.
    echo Migrations failed. Is Python 3.13 on the path, and are the
    echo requirements installed?  pip install -r backend\requirements.txt
    pause
    exit /b 1
)

echo.
if exist "treasury.db" (
    echo [2/3] Database already present, leaving the seed alone.
    echo       Delete backend\treasury.db to reload it.
) else (
    echo [2/3] Loading the seed.
    python -m seed.seed
    if errorlevel 1 (echo Seeding failed. & pause & exit /b 1)
)

echo.
echo [3/3] Starting the %LABEL% on http://127.0.0.1:%PORT%
echo       Generated documentation at http://127.0.0.1:%PORT%/docs
echo       Close this window to stop it.
echo.
python -m uvicorn %MODULE% --port %PORT% --reload

endlocal

<#
.SYNOPSIS
    Starts everything. One command, because two terminals on the day of a
    demonstration is one more thing to go wrong.

.DESCRIPTION
    Phase zero starts the mock server and the frontend. The frontend rewrites
    /api to whichever origin is given, so the browser only ever sees one
    origin and there is no cross origin configuration anywhere.

    Phase one put groups 1, 2, 5 and 6 live, so the real API is the default.
    Pass -Mock to read the mock instead. Nothing in the frontend changes,
    because the shapes are identical.

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Mock
    .\start.ps1 -Reseed
#>
[CmdletBinding()]
param(
    [switch]$Mock,
    [switch]$Reseed
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Push-Location $backend
try {
    Write-Host "Building the schema from the migrations." -ForegroundColor Cyan
    python -m alembic upgrade head

    if ($Reseed -or -not (Test-Path (Join-Path $backend "treasury.db"))) {
        Write-Host "Loading the seed." -ForegroundColor Cyan
        python -m seed.seed
    }
}
finally {
    Pop-Location
}

if ($Mock) {
    $module = "mock.main:app"
    $port = 8001
    $label = "mock"
}
else {
    $module = "app.main:app"
    $port = 8000
    $label = "api"
}

Write-Host "Starting the $label on port $port." -ForegroundColor Cyan
$api = Start-Process -PassThru -WorkingDirectory $backend -FilePath "python" `
    -ArgumentList @("-m", "uvicorn", $module, "--port", "$port", "--reload")

$env:TREASURY_API_ORIGIN = "http://127.0.0.1:$port"

Write-Host "Starting the surface on port 3000." -ForegroundColor Cyan
Write-Host "Open http://localhost:3000" -ForegroundColor Green

Push-Location $frontend
try {
    npm run dev
}
finally {
    Pop-Location
    if ($api -and -not $api.HasExited) {
        Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    }
}

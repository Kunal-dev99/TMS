# start-backend.ps1 — OneDrive-safe uvicorn restart loop.
#
# uvicorn --reload spawns a reloader + worker tree that doesn't always
# die cleanly on Ctrl+C — the next start then collides on port 8000
# with a stuck child. This script clears any orphan holding the port
# before launching.
#
# Usage: pwsh scripts/start-backend.ps1

$ErrorActionPreference = "Stop"
$Port = 8000
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $ProjectRoot "backend"

Write-Host "[start-backend] clearing orphan listeners on port $Port"

# Find processes listening on $Port (TCP). Get-NetTCPConnection is
# PowerShell 5.1+ and comes stock on Windows 10/11.
$owning = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

foreach ($procId in $owning) {
    if ($procId -and $procId -ne 0) {
        try {
            $p = Get-Process -Id $procId -ErrorAction Stop
            Write-Host ("  killing PID {0} ({1})" -f $p.Id, $p.ProcessName)
            Stop-Process -Id $procId -Force -ErrorAction Stop
        } catch {
            Write-Host "  PID $procId already gone"
        }
    }
}

# Also kill any stray python holding backend\treasury.db (OneDrive +
# SQLite WAL + reload tree = occasional file-lock orphan). Scoped to
# python.exe so we don't shoot something unrelated.
Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path -like "*Python3*" } |
    ForEach-Object {
        $isUs = $false
        try {
            # Only kill python processes whose cwd is under this project.
            # Fallback: skip if we can't inspect — don't guess.
            $cwd = (Get-Process -Id $_.Id).Path
            if ($cwd -like "$ProjectRoot*") { $isUs = $true }
        } catch { }
        if ($isUs) {
            Write-Host ("  killing stale python PID {0}" -f $_.Id)
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    }

Set-Location $BackendDir
Write-Host "[start-backend] uvicorn app.main:app --port $Port --reload"
& python -m uvicorn app.main:app --port $Port --reload

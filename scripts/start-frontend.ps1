# start-frontend.ps1 — OneDrive-safe Next.js dev restart.
#
# OneDrive's sync agent leaves .next directories in placeholder states
# that `rmdir /q /s` chokes on and that Next.js then half-reads on the
# next build, producing phantom "cannot find module" errors.
# Remove-Item -Recurse -Force follows placeholders correctly.
#
# Usage: pwsh scripts/start-frontend.ps1

$ErrorActionPreference = "Stop"
$Port = 3000
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $ProjectRoot "frontend"
$NextDir = Join-Path $FrontendDir ".next"

Write-Host "[start-frontend] clearing orphan listeners on port $Port"
$owning = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $owning) {
    if ($procId -and $procId -ne 0) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "  killed PID $procId"
        } catch {
            Write-Host "  PID $procId already gone"
        }
    }
}

if (Test-Path $NextDir) {
    Write-Host "[start-frontend] wiping .next (OneDrive-safe)"
    Remove-Item -Recurse -Force $NextDir
}

Set-Location $FrontendDir
Write-Host "[start-frontend] npm run dev"
& npm run dev

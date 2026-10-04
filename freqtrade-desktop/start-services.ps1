# Start backend + Vite as detached background processes (browser mode).
# Unlike dev.cmd (foreground Electron), these survive closing this terminal.
# Usage: .\start-services.ps1   then open http://127.0.0.1:5173
#
# To stop them later:
#   Stop-Process -Id (Get-NetTCPConnection -LocalPort 8765).OwningProcess -Force
#   Stop-Process -Id (Get-NetTCPConnection -LocalPort 5173).OwningProcess -Force
#
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 misreads UTF-8 no-BOM
# scripts containing CJK characters).
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $root "backend"
$desktopDir = Join-Path $root "desktop"
$logDir = Join-Path $backendDir "data"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Treat an outdated backend (missing new features) as "not up" so the new code
# is actually started instead of silently reusing the old process.
$backendUp = $false
$health = $null
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8766/api/health" -TimeoutSec 3
    if ($health -and ($health.features -contains "public_download")) {
        $backendUp = $true
    }
} catch {
    $backendUp = $false
}
if (-not $backendUp -and $health) {
    Write-Host "Existing backend on 8766 is outdated (version $($health.version)); restarting it ..."
    for ($i = 0; $i -lt 3; $i++) {
        $owner = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue
        if (-not $owner) { break }
        Stop-Process -Id $owner.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}
if (-not $backendUp) {
    Write-Host "Starting backend (127.0.0.1:8766) ..."
    $backendLog = Join-Path $logDir "backend-services.log"
    $s1 = "Set-Location -LiteralPath '$backendDir'; `$env:FTDESK_PORT='8766'; python -m app.main *> '$backendLog' 2>&1"
    Start-Process powershell -ArgumentList @("-NoProfile", "-Command", $s1) -WindowStyle Hidden
    Start-Sleep -Seconds 4
}

$viteUp = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 2
    $viteUp = $resp.StatusCode -eq 200
} catch {
    $viteUp = $false
}
if (-not $viteUp) {
    Write-Host "Starting Vite (127.0.0.1:5173) ..."
    $viteLog = Join-Path $desktopDir "vite-services.log"
    $s2 = "Set-Location -LiteralPath '$desktopDir'; npm run dev:web *> '$viteLog' 2>&1"
    Start-Process powershell -ArgumentList @("-NoProfile", "-Command", $s2) -WindowStyle Hidden
    Start-Sleep -Seconds 6
}

Write-Host "Backend:  http://127.0.0.1:8766  (api/health)"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Logs: backend\data\backend-services.log , desktop\vite-services.log"
Write-Host "Stop hint: Stop-Process -Id (Get-NetTCPConnection -LocalPort 8766).OwningProcess -Force"

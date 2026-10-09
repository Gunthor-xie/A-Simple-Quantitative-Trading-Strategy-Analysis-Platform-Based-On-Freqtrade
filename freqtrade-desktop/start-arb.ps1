# Delta-neutral arbitrage position scheduler (mark open positions + risk unwind).
# ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI and
# would mis-parse non-ASCII text.
#
#   .\start-arb.ps1            # start in a hidden background window
#   .\start-arb.ps1 status     # open positions + recent events
#   .\start-arb.ps1 once       # single pass (scheduler friendly)
#   .\start-arb.ps1 stop       # stop the background scheduler
#
# No-op until OKX trade keys are configured AND ordering is enabled from the
# "套利机会" page. Logs land in backend\data\.

param(
    [ValidateSet("start", "status", "once", "stop")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$dataDir = Join-Path $backend "data"
$logPath = Join-Path $dataDir "arb-scheduler.log"
$errPath = Join-Path $dataDir "arb-scheduler.err.log"
$scriptPath = Join-Path $backend "scripts\run_arb_scheduler.py"

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

function Get-ArbProcess {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*run_arb_scheduler.py*" }
}

switch ($Action) {
    "start" {
        $running = Get-ArbProcess
        if ($running) {
            Write-Host "arb scheduler already running (PID $($running.ProcessId -join ',')); log: $logPath"
            break
        }
        $python = (Get-Command python).Source
        Start-Process -FilePath $python -ArgumentList @($scriptPath, "--loop") `
            -WorkingDirectory $backend -WindowStyle Hidden `
            -RedirectStandardOutput $logPath -RedirectStandardError $errPath
        Start-Sleep -Seconds 4
        $running = Get-ArbProcess
        if ($running) {
            Write-Host "arb scheduler started (PID $($running.ProcessId -join ',')); log: $logPath"
            Write-Host "follow progress:  Get-Content `"$logPath`" -Wait"
        } else {
            Write-Host "arb scheduler failed to start; see $errPath"
        }
    }
    "status" {
        & python $scriptPath --status
    }
    "once" {
        & python $scriptPath --once
    }
    "stop" {
        $running = Get-ArbProcess
        if (-not $running) { Write-Host "arb scheduler is not running"; break }
        foreach ($item in $running) {
            Stop-Process -Id $item.ProcessId -Force
            Write-Host "stopped PID $($item.ProcessId)"
        }
    }
}

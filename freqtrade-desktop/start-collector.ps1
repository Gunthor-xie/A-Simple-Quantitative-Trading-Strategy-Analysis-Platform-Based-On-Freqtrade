# OKX liquidation / open-interest / taker-volume collector.
# ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI and
# would mis-parse non-ASCII text.
#
#   .\start-collector.ps1            # start in a hidden background window
#   .\start-collector.ps1 status     # coverage collected so far
#   .\start-collector.ps1 once       # single poll (scheduler friendly)
#   .\start-collector.ps1 stop       # stop the background collector
#
# Data (public endpoints only, no API key) lands in user_data\liquidation\.

param(
    [ValidateSet("start", "status", "once", "stop")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$backend = Join-Path $root "backend"
$dataDir = Join-Path $backend "data"
$logPath = Join-Path $dataDir "collector.log"
$errPath = Join-Path $dataDir "collector.err.log"
$scriptPath = Join-Path $backend "scripts\collect_liquidations.py"

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

function Get-CollectorProcess {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*collect_liquidations.py*" }
}

switch ($Action) {
    "start" {
        $running = Get-CollectorProcess
        if ($running) {
            Write-Host "collector already running (PID $($running.ProcessId -join ',')); log: $logPath"
            break
        }
        $python = (Get-Command python).Source
        Start-Process -FilePath $python -ArgumentList @($scriptPath, "--loop") `
            -WorkingDirectory $backend -WindowStyle Hidden `
            -RedirectStandardOutput $logPath -RedirectStandardError $errPath
        Start-Sleep -Seconds 4
        $running = Get-CollectorProcess
        if ($running) {
            Write-Host "collector started (PID $($running.ProcessId -join ',')); log: $logPath"
            Write-Host "follow progress:  Get-Content `"$logPath`" -Wait"
        } else {
            Write-Host "collector failed to start; see $errPath"
        }
    }
    "status" {
        & python $scriptPath --status --minutes 120
    }
    "once" {
        & python $scriptPath --once
    }
    "stop" {
        $running = Get-CollectorProcess
        if (-not $running) { Write-Host "collector is not running"; break }
        foreach ($item in $running) {
            Stop-Process -Id $item.ProcessId -Force
            Write-Host "stopped PID $($item.ProcessId)"
        }
    }
}

@echo off
rem ============================================================================
rem  Freqtrade Desktop - dev launcher for Windows (cmd.exe)
rem
rem  Usage, run from this folder:
rem    dev.cmd            local backend + desktop app window   [default]
rem    dev.cmd backend    local backend only, keeps running in the background
rem    dev.cmd web        local backend + Vite, use it in the browser
rem    dev.cmd stop       stop backend and Vite
rem    dev.cmd help       show this help
rem
rem  The backend always listens on 127.0.0.1:8766 (FTDESK_PORT=8766) because the
rem  Electron app and the web UI default to http://127.0.0.1:8766.
rem  Logs: backend\data\backend-dev.log , desktop\vite-dev.log
rem
rem  NOTE: keep this file ASCII-only. cmd.exe reads .cmd files with the current
rem  OEM code page, so non-ASCII text here can break parsing on some systems.
rem ============================================================================

setlocal EnableExtensions
set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "DESKTOP_DIR=%ROOT%desktop"
set "LOG_DIR=%BACKEND_DIR%\data"
set "BACKEND_LOG=%LOG_DIR%\backend-dev.log"
set "VITE_LOG=%DESKTOP_DIR%\vite-dev.log"
set "PORT=8766"
set "WEB_PORT=5173"
set "FTDESK_PORT=%PORT%"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=all"

if /i "%MODE%"=="all" goto :start_all
if /i "%MODE%"=="backend" goto :start_backend
if /i "%MODE%"=="web" goto :start_web
if /i "%MODE%"=="stop" goto :stop_all
if /i "%MODE%"=="help" goto :usage
if /i "%MODE%"=="-h" goto :usage
if /i "%MODE%"=="--help" goto :usage
goto :usage


rem ----------------------------------------------------------------------------
rem  modes
rem ----------------------------------------------------------------------------

:start_all
call :require_python
if errorlevel 1 exit /b 1
call :ensure_backend
if errorlevel 1 exit /b 1
call :vite_running
if not errorlevel 1 goto :attach_electron
echo Starting Vite + Electron window ...
echo Close the Electron window or press Ctrl+C here to stop the frontend.
pushd "%DESKTOP_DIR%"
call npm run dev
popd
exit /b 0

:attach_electron
echo Vite is already running at http://127.0.0.1:%WEB_PORT% - opening Electron against it.
set "NODE_ENV=development"
pushd "%DESKTOP_DIR%"
call npm run start
popd
exit /b 0

:start_backend
call :require_python
if errorlevel 1 exit /b 1
call :ensure_backend
if errorlevel 1 exit /b 1
echo.
echo Backend: http://127.0.0.1:%PORT%/api/health
echo Log:     %BACKEND_LOG%
echo Stop:    dev.cmd stop
exit /b 0

:start_web
call :require_python
if errorlevel 1 exit /b 1
call :ensure_backend
if errorlevel 1 exit /b 1
call :vite_running
if not errorlevel 1 goto :web_ready
echo Starting Vite on http://127.0.0.1:%WEB_PORT% ...
pushd "%DESKTOP_DIR%"
start "freqtrade-vite" /min cmd /c "npm run dev:web >> vite-dev.log 2>&1"
popd
call :wait_vite
if not errorlevel 1 goto :web_ready
echo WARNING: Vite did not answer on http://127.0.0.1:%WEB_PORT%
echo          check the log: %VITE_LOG%
exit /b 1

:web_ready
echo.
echo Backend:  http://127.0.0.1:%PORT%/api/health
echo Frontend: http://127.0.0.1:%WEB_PORT%  - open it in your browser
echo Logs:     %BACKEND_LOG%
echo           %VITE_LOG%
echo Stop:     dev.cmd stop
exit /b 0

:stop_all
call :stop_backend
if errorlevel 1 (
    echo WARNING: something still answers on http://127.0.0.1:%PORT%
    echo          run netstat -ano and look for port %PORT%, then close that process
) else (
    echo Stopped the backend on port %PORT%.
)
call :kill_port %WEB_PORT%
echo Stopped Vite on port %WEB_PORT%.
echo The Electron window, if any, closes with the terminal that started it.
exit /b 0

:usage
echo Freqtrade Desktop dev launcher
echo.
echo   dev.cmd            backend + desktop app window   [default]
echo   dev.cmd backend    backend only, runs in the background
echo   dev.cmd web        backend + Vite, use it in the browser
echo   dev.cmd stop       stop backend and Vite
echo   dev.cmd help       show this help
echo.
echo   backend: http://127.0.0.1:%PORT%   log: %BACKEND_LOG%
echo   web UI:  http://127.0.0.1:%WEB_PORT%   log: %VITE_LOG%
exit /b 0


rem ----------------------------------------------------------------------------
rem  helpers
rem ----------------------------------------------------------------------------

:require_python
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: "python" was not found on PATH.
    echo        Install 64-bit Python 3.11+ and make sure "python" works in cmd.
    exit /b 1
)
exit /b 0

rem  0 = /api/health answers and reports the current feature set
rem  1 = not running, still starting, or running an outdated build
:backend_ready
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%PORT%/api/health' -TimeoutSec 3; if ($r.Content -like '*public_download*') { exit 0 } } catch { }; exit 1"
exit /b

rem  0 = /api/health answers (any version), 1 = nothing listening
:api_reachable
powershell -NoProfile -Command "try { $null = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%PORT%/api/health' -TimeoutSec 3; exit 0 } catch { exit 1 }"
exit /b

rem  0 = Vite answers on 5173, 1 = Vite is not up
:vite_running
powershell -NoProfile -Command "try { $null = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%WEB_PORT%' -TimeoutSec 2; exit 0 } catch { exit 1 }"
exit /b

:ensure_backend
call :backend_ready
if not errorlevel 1 (
    echo Backend is already running on http://127.0.0.1:%PORT%
    exit /b 0
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
call :api_reachable
if errorlevel 1 (
    echo Starting the local backend on http://127.0.0.1:%PORT% ...
) else (
    echo The running backend is outdated - restarting it ...
)
call :stop_backend
if errorlevel 1 (
    echo ERROR: a leftover backend still owns http://127.0.0.1:%PORT% and could not be stopped
    echo        run netstat -ano, look for port %PORT%, then kill that process
    echo        hint: close any leftover freqtrade-backend window first
    exit /b 1
)
rem keep the log path relative: it has no spaces, so no nested quoting is needed
pushd "%BACKEND_DIR%"
start "freqtrade-backend" /min cmd /c "python -m app.main >> data\backend-dev.log 2>&1"
popd
call :wait_backend
if not errorlevel 1 goto :backend_up
call :api_reachable
if errorlevel 1 echo ERROR: the backend did not answer on http://127.0.0.1:%PORT%/api/health
if not errorlevel 1 echo ERROR: an old backend still answers on http://127.0.0.1:%PORT% without the new features
echo        check the log: %BACKEND_LOG%
echo        list owners:   netstat -ano and look for port %PORT%
exit /b 1

:backend_up
echo Backend ready: http://127.0.0.1:%PORT%/api/health
exit /b 0

:wait_backend
for /l %%I in (1,1,30) do (
    call :backend_ready
    if not errorlevel 1 exit /b 0
    ping -n 2 127.0.0.1 >nul 2>&1
)
exit /b 1

:wait_vite
for /l %%I in (1,1,30) do (
    call :vite_running
    if not errorlevel 1 exit /b 0
    ping -n 2 127.0.0.1 >nul 2>&1
)
exit /b 1

rem  %~1 = TCP port: stop whatever listens on it, child processes included
:kill_port
rem  netstat is used instead of Get-NetTCPConnection: it keeps reporting sockets
rem  whose creating process is already gone, which is the case that hurts.
if "%~1"=="" exit /b 0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%~1" ^| findstr "LISTENING"') do taskkill /PID %%P /T /F >nul 2>&1
ping -n 2 127.0.0.1 >nul 2>&1
exit /b 0

rem  backends started by this script own a console window with a known title
:kill_window
taskkill /FI "WINDOWTITLE eq freqtrade-backend*" /T /F >nul 2>&1
exit /b 0

rem  %~1 = command line pattern, e.g. *app.main*
:kill_commandline
powershell -NoProfile -Command "$me = $PID; $ids = (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessId -ne $me -and $_.CommandLine -like '%~1' }).ProcessId | Sort-Object -Unique; foreach ($procId in $ids) { if ($procId) { & taskkill /PID $procId /T /F *> $null } }"
ping -n 2 127.0.0.1 >nul 2>&1
exit /b 0

rem  last resort: 'uvicorn --reload' spawns a child that inherits the listening
rem  socket, so a child whose parent is gone keeps port 8766 alive forever
:kill_reload_orphan
powershell -NoProfile -Command "$me = $PID; $p = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue; $live = $p.ProcessId; $ids = ($p | Where-Object { $_.ProcessId -ne $me -and $_.Name -like 'python*' -and $_.CommandLine -like '*multiprocessing-fork*' -and ($live -notcontains $_.ParentProcessId) }).ProcessId | Sort-Object -Unique; foreach ($procId in $ids) { if ($procId) { & taskkill /PID $procId /T /F *> $null } }"
ping -n 2 127.0.0.1 >nul 2>&1
exit /b 0

rem  0 = port %PORT% stopped answering (retries: a killed process releases its
rem  socket a moment later), 1 = something is still serving there
:port_free
for /l %%I in (1,1,3) do (
    call :api_reachable
    if errorlevel 1 exit /b 0
    ping -n 2 127.0.0.1 >nul 2>&1
)
exit /b 1

rem  0 = port %PORT% is free again, 1 = something still answers there
:stop_backend
call :kill_window
call :kill_port %PORT%
call :port_free
if not errorlevel 1 exit /b 0
call :kill_commandline *app.main*
call :port_free
if not errorlevel 1 exit /b 0
call :kill_reload_orphan
call :port_free
exit /b

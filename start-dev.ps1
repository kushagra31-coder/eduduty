<#
.SYNOPSIS
    Starts the EduDuty development stack (FastAPI backend and Next.js frontend).

.DESCRIPTION
    One-command development startup for EduDuty:
    - FastAPI Backend: http://127.0.0.1:8000
    - Next.js Frontend: http://127.0.0.1:3000
    - Validates prerequisites, port availability, and database configuration.
    - Launches each service in a separate terminal so logs remain visible.
    - Checks readiness with bounded timeouts.

.PARAMETER Stop
    Stops running EduDuty backend and frontend processes on ports 8000 and 3000.

.PARAMETER Headless
    Launches services in the background without opening separate terminal windows.

.PARAMETER TimeoutSeconds
    Maximum time in seconds to wait for backend and frontend readiness (default: 45).
#>

[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Headless,
    [int]$TimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"
$RootDir = $PSScriptRoot
if (-not $RootDir) {
    $RootDir = (Get-Location).Path
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "                EduDuty Development Suite                 " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# ── Function: Test-IsEduDutyProcess ───────────────────────────────────────────
function Test-IsEduDutyProcess([int]$ProcessId, [int]$Port) {
    if ($ProcessId -le 0) { return $false }
    try {
        $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
        if (-not $procInfo) {
            $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
            if (-not $p) { return $false }
            if ($Port -eq 8000 -and $p.ProcessName -like "*python*") { return $true }
            if ($Port -eq 3000 -and $p.ProcessName -like "*node*") { return $true }
            return $false
        }

        $cmdLine = if ($procInfo.CommandLine) { $procInfo.CommandLine.ToLower() } else { "" }
        $procName = if ($procInfo.Name) { $procInfo.Name.ToLower() } else { "" }

        # Port 8000: FastAPI / Uvicorn Backend
        if ($Port -eq 8000) {
            if ($cmdLine -match "uvicorn" -or $cmdLine -match "main:app" -or $cmdLine -match "eduduty") {
                return $true
            }
            if ($procName -like "*python*") {
                if ($cmdLine -match "main\.py" -or $cmdLine -match "backend") {
                    return $true
                }
            }
            if ($procInfo.ParentProcessId -gt 0) {
                $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($procInfo.ParentProcessId)" -ErrorAction SilentlyContinue
                if ($parent -and $parent.CommandLine -and $parent.CommandLine -match "eduduty") {
                    return $true
                }
            }
            return $false
        }

        # Port 3000: Next.js Frontend
        if ($Port -eq 3000) {
            if ($cmdLine -match "next" -or $cmdLine -match "eduduty" -or $cmdLine -match "frontend") {
                return $true
            }
            if ($procName -like "*node*") {
                if ($cmdLine -match "next-server" -or $cmdLine -match "next dev" -or $cmdLine -match "3000") {
                    return $true
                }
            }
            if ($procInfo.ParentProcessId -gt 0) {
                $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($procInfo.ParentProcessId)" -ErrorAction SilentlyContinue
                if ($parent -and $parent.CommandLine -and $parent.CommandLine -match "eduduty") {
                    return $true
                }
            }
            return $false
        }

        return $false
    } catch {
        return $false
    }
}

# ── Function: Find-ListeningProcess ───────────────────────────────────────────
function Find-ListeningProcess([int]$Port) {
    $procs = @()
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($connections) {
            $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($p in $pids) {
                if ($p -gt 0) {
                    $procObj = Get-Process -Id $p -ErrorAction SilentlyContinue
                    $procs += [PSCustomObject]@{
                        Port = $Port
                        PID  = $p
                        Name = if ($procObj) { $procObj.ProcessName } else { "Unknown" }
                    }
                }
            }
            return $procs
        }
    } catch {
        # Fallback to netstat if Get-NetTCPConnection fails
        $lines = netstat -ano | Select-String ":$Port\s+.*LISTENING\s+(\d+)"
        if ($lines) {
            foreach ($line in $lines) {
                if ($line.Matches -and $line.Matches[0].Groups.Count -gt 1) {
                    $p = [int]$line.Matches[0].Groups[1].Value
                    if ($p -gt 0) {
                        $procObj = Get-Process -Id $p -ErrorAction SilentlyContinue
                        $procs += [PSCustomObject]@{
                            Port = $Port
                            PID  = $p
                            Name = if ($procObj) { $procObj.ProcessName } else { "Unknown" }
                        }
                    }
                }
            }
            return $procs
        }
    }
    return $procs
}

# ── Stop Routine ─────────────────────────────────────────────────────────────
if ($Stop) {
    Write-Host "[STOP] Checking for running EduDuty processes..." -ForegroundColor Yellow
    $bProcs = @(Find-ListeningProcess -Port 8000)
    $fProcs = @(Find-ListeningProcess -Port 3000)
    $all = @($bProcs) + @($fProcs)

    # Check for recorded dev session launcher PIDs
    $sessionFile = Join-Path ([System.IO.Path]::GetTempPath()) "eduduty-dev-session.json"
    $sessionPids = @()
    if (Test-Path $sessionFile) {
        try {
            $sessJson = Get-Content $sessionFile -Raw | ConvertFrom-Json
            if ($sessJson.BackendCmdPID) { $sessionPids += [int]$sessJson.BackendCmdPID }
            if ($sessJson.FrontendCmdPID) { $sessionPids += [int]$sessJson.FrontendCmdPID }
        } catch {}
    }

    if ($all.Count -eq 0 -and $sessionPids.Count -eq 0) {
        Write-Host "[OK] No processes found listening on port 8000 or 3000." -ForegroundColor Green
        if (Test-Path $sessionFile) { Remove-Item $sessionFile -Force -ErrorAction SilentlyContinue }
        exit 0
    }

    foreach ($item in $all) {
        # Verify process is EduDuty-owned before killing
        $isEduDuty = Test-IsEduDutyProcess -ProcessId $item.PID -Port $item.Port
        if (-not $isEduDuty -and ($sessionPids -notcontains $item.PID)) {
            Write-Warning "Process $($item.Name) (PID $($item.PID)) on port $($item.Port) does not match EduDuty signatures. Skipping."
            continue
        }

        Write-Host "Stopping Process $($item.Name) (PID $($item.PID)) on port $($item.Port)..." -ForegroundColor Yellow
        try {
            $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($item.PID)" -ErrorAction SilentlyContinue
            $parentPid = if ($procInfo) { [int]$procInfo.ParentProcessId } else { 0 }

            Stop-Process -Id $item.PID -Force -ErrorAction SilentlyContinue
            Write-Host "  -> Terminated PID $($item.PID)" -ForegroundColor Green

            # Terminate parent terminal window if it was spawned for EduDuty
            if ($parentPid -gt 0 -and ($sessionPids -contains $parentPid)) {
                Stop-Process -Id $parentPid -Force -ErrorAction SilentlyContinue
                Write-Host "  -> Terminated console wrapper PID $parentPid" -ForegroundColor Green
            } elseif ($parentPid -gt 0) {
                $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId = $parentPid" -ErrorAction SilentlyContinue
                if ($parentProc -and $parentProc.CommandLine -and $parentProc.CommandLine -match "EduDuty") {
                    Stop-Process -Id $parentPid -Force -ErrorAction SilentlyContinue
                    Write-Host "  -> Terminated console wrapper PID $parentPid" -ForegroundColor Green
                }
            }
        } catch {
            Write-Warning "  -> Could not terminate PID $($item.PID): $_"
        }
    }

    # Clean up recorded session launcher processes if still active
    foreach ($sPid in $sessionPids) {
        $p = Get-Process -Id $sPid -ErrorAction SilentlyContinue
        if ($p) {
            try {
                Stop-Process -Id $sPid -Force -ErrorAction SilentlyContinue
                Write-Host "  -> Terminated launcher PID $sPid" -ForegroundColor Green
            } catch {}
        }
    }

    if (Test-Path $sessionFile) {
        Remove-Item $sessionFile -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Seconds 1

    # Verify both ports are released
    $rem8000 = @(Find-ListeningProcess -Port 8000)
    $rem3000 = @(Find-ListeningProcess -Port 3000)
    if ($rem8000.Count -eq 0 -and $rem3000.Count -eq 0) {
        Write-Host "[OK] EduDuty services stopped. Ports 8000 and 3000 are free." -ForegroundColor Green
    } else {
        if ($rem8000.Count -gt 0) {
            Write-Warning "Port 8000 is still in use by PID $($rem8000[0].PID) ($($rem8000[0].Name))."
        }
        if ($rem3000.Count -gt 0) {
            Write-Warning "Port 3000 is still in use by PID $($rem3000[0].PID) ($($rem3000[0].Name))."
        }
    }
    exit 0
}

# ── 1. Check for Port Conflicts ──────────────────────────────────────────────
Write-Host "[1/5] Checking port availability..." -ForegroundColor White
$backendPortConflict = @(Find-ListeningProcess -Port 8000)
if ($backendPortConflict.Count -gt 0) {
    $conflict = $backendPortConflict[0]
    Write-Host ""
    Write-Host "[ERROR] Port 8000 is already in use by $($conflict.Name) (PID $($conflict.PID))." -ForegroundColor Red
    Write-Host "Action Required: Stop the existing process before launching EduDuty:" -ForegroundColor Yellow
    Write-Host "  PowerShell: Stop-Process -Id $($conflict.PID) -Force" -ForegroundColor Yellow
    Write-Host "  Or run:     .\start-dev.ps1 -Stop" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$frontendPortConflict = @(Find-ListeningProcess -Port 3000)
if ($frontendPortConflict.Count -gt 0) {
    $conflict = $frontendPortConflict[0]
    Write-Host ""
    Write-Host "[ERROR] Port 3000 is already in use by $($conflict.Name) (PID $($conflict.PID))." -ForegroundColor Red
    Write-Host "Action Required: Stop the existing process before launching EduDuty:" -ForegroundColor Yellow
    Write-Host "  PowerShell: Stop-Process -Id $($conflict.PID) -Force" -ForegroundColor Yellow
    Write-Host "  Or run:     .\start-dev.ps1 -Stop" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
Write-Host "  -> Ports 8000 and 3000 are free." -ForegroundColor Green

# ── 2. Check Database Configuration ──────────────────────────────────────────
Write-Host "[2/5] Validating database configuration..." -ForegroundColor White
$demoDbPath = Join-Path $RootDir "backend\eduduty_demo.db"
$backendEnvPath = Join-Path $RootDir "backend\.env"

if (-not (Test-Path $demoDbPath)) {
    Write-Host ""
    Write-Host "[ERROR] Demo database not found at '$demoDbPath'." -ForegroundColor Red
    Write-Host "Action Required: Generate the demo database before starting:" -ForegroundColor Yellow
    Write-Host "  cd backend && python seed_demo_data.py" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

if (-not (Test-Path $backendEnvPath)) {
    $backendEnvExamplePath = Join-Path $RootDir "backend\.env.example"
    Write-Host ""
    Write-Host "[ERROR] Backend environment configuration file not found at '$backendEnvPath'." -ForegroundColor Red
    Write-Host "Action Required: Create backend/.env from backend/.env.example before starting:" -ForegroundColor Yellow
    Write-Host "  Copy-Item backend\.env.example backend\.env" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$envContent = Get-Content $backendEnvPath -Raw
if ($envContent -notmatch "DATABASE_URL=sqlite:///\./eduduty_demo\.db") {
    Write-Warning "backend/.env does not appear to point to 'sqlite:///./eduduty_demo.db'."
    Write-Warning "Ensure DATABASE_URL=sqlite:///./eduduty_demo.db is set to avoid touching eduduty.db."
}
Write-Host "  -> Demo database verified: backend/eduduty_demo.db" -ForegroundColor Green

# ── 3. Check Python and Backend Dependencies ─────────────────────────────────
Write-Host "[3/5] Locating Python runtime..." -ForegroundColor White
$venvPaths = @(
    (Join-Path $RootDir "backend\.venv\Scripts\python.exe"),
    (Join-Path $RootDir "backend\venv\Scripts\python.exe"),
    (Join-Path $RootDir ".venv\Scripts\python.exe"),
    (Join-Path $RootDir "venv\Scripts\python.exe")
)

$pythonExe = $null
foreach ($vp in $venvPaths) {
    if (Test-Path $vp) {
        $pythonExe = $vp
        break
    }
}

if (-not $pythonExe) {
    $sysPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($sysPython) {
        $pythonExe = $sysPython.Source
    }
}

if (-not $pythonExe) {
    Write-Host ""
    Write-Host "[ERROR] Python runtime not found." -ForegroundColor Red
    Write-Host "Action Required: Install Python 3.11+ or create a virtual environment in backend/.venv" -ForegroundColor Yellow
    Write-Host "  python -m venv backend/.venv" -ForegroundColor Yellow
    Write-Host "  backend/.venv/Scripts/pip install -r backend/requirements.txt" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# Verify required backend packages
$checkCmd = "& '$pythonExe' -c `"import fastapi, uvicorn, sqlalchemy; print('OK')`""
$pkgCheck = Invoke-Expression $checkCmd 2>$null
if ($pkgCheck -ne "OK") {
    Write-Host ""
    Write-Host "[ERROR] Required Python packages (fastapi, uvicorn, sqlalchemy) missing in '$pythonExe'." -ForegroundColor Red
    Write-Host "Action Required: Install backend dependencies:" -ForegroundColor Yellow
    Write-Host "  & '$pythonExe' -m pip install -r backend/requirements.txt" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
Write-Host "  -> Python runtime: $pythonExe" -ForegroundColor Green

# ── 4. Check Node.js and Frontend Dependencies ───────────────────────────────
Write-Host "[4/5] Locating Node.js and Frontend setup..." -ForegroundColor White
$nodeCmd = Get-Command node.exe -ErrorAction SilentlyContinue
$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue

if (-not $nodeCmd -or -not $npmCmd) {
    Write-Host ""
    Write-Host "[ERROR] Node.js and npm are required to run the frontend." -ForegroundColor Red
    Write-Host "Action Required: Install Node.js v18+ (https://nodejs.org)." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$frontendNodeModules = Join-Path $RootDir "frontend\node_modules"
if (-not (Test-Path $frontendNodeModules)) {
    Write-Host ""
    Write-Host "[ERROR] Frontend dependencies not installed ('frontend/node_modules' missing)." -ForegroundColor Red
    Write-Host "Action Required: Install frontend dependencies:" -ForegroundColor Yellow
    Write-Host "  cd frontend && npm install" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
Write-Host "  -> Node.js runtime and node_modules verified." -ForegroundColor Green

# ── 5. Launch Services ───────────────────────────────────────────────────────
Write-Host "[5/5] Launching EduDuty services..." -ForegroundColor White
$backendDir = Join-Path $RootDir "backend"
$frontendDir = Join-Path $RootDir "frontend"

$backendProc = $null
$frontendProc = $null

if ($Headless) {
    Write-Host "  -> Starting FastAPI in background (hidden window)..." -ForegroundColor Gray
    $backendProc = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList "-m uvicorn main:app --host 127.0.0.1 --port 8000" `
        -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -PassThru

    Write-Host "  -> Starting Next.js in background (hidden window)..." -ForegroundColor Gray
    $frontendProc = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/c npm run dev -- -H 127.0.0.1 -p 3000" `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -PassThru
} else {
    Write-Host "  -> Spawning terminal for FastAPI Backend (127.0.0.1:8000)..." -ForegroundColor Gray
    $backendProc = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/k", "title EduDuty Backend (FastAPI :8000) && `"$pythonExe`" -m uvicorn main:app --host 127.0.0.1 --port 8000" `
        -WorkingDirectory $backendDir `
        -PassThru

    Write-Host "  -> Spawning terminal for Next.js Frontend (127.0.0.1:3000)..." -ForegroundColor Gray
    $frontendProc = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/k", "title EduDuty Frontend (Next.js :3000) && npm run dev -- -H 127.0.0.1 -p 3000" `
        -WorkingDirectory $frontendDir `
        -PassThru
}

Write-Host "  Backend PID:  $($backendProc.Id)" -ForegroundColor Cyan
Write-Host "  Frontend PID: $($frontendProc.Id)" -ForegroundColor Cyan

# Write session file to temp directory for robust stop tracking
$sessionFile = Join-Path ([System.IO.Path]::GetTempPath()) "eduduty-dev-session.json"
$sessionData = @{
    BackendCmdPID  = $backendProc.Id
    FrontendCmdPID = $frontendProc.Id
    RootDir        = $RootDir
    Timestamp      = (Get-Date).ToString("o")
}
try {
    $sessionData | ConvertTo-Json | Set-Content -Path $sessionFile -Encoding UTF8 -ErrorAction SilentlyContinue
} catch {}

# ── 6. Health & Readiness Polling ─────────────────────────────────────────────
Write-Host ""
Write-Host "Waiting for services to become ready (max $TimeoutSeconds seconds)..." -ForegroundColor Yellow

$backendReady = $false
$frontendReady = $false
$lastBackendError = $null
$lastFrontendError = $null
$startTime = Get-Date

while (((Get-Date) - $startTime).TotalSeconds -lt $TimeoutSeconds) {
    # Check if backend wrapper process unexpectedly died
    if ($backendProc -and $backendProc.HasExited) {
        Write-Host ""
        Write-Host "  [ERROR] Backend process (PID $($backendProc.Id)) exited prematurely with code $($backendProc.ExitCode)." -ForegroundColor Red
        break
    }
    if ($frontendProc -and $frontendProc.HasExited) {
        Write-Host ""
        Write-Host "  [ERROR] Frontend process (PID $($frontendProc.Id)) exited prematurely with code $($frontendProc.ExitCode)." -ForegroundColor Red
        break
    }

    if (-not $backendReady) {
        $backendResp = $null
        try {
            $backendResp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
            if ($backendResp -and ($backendResp.status -eq "ok" -or $backendResp.status -eq "healthy")) {
                $backendReady = $true
                Write-Host "  [OK] Backend healthy at http://127.0.0.1:8000/health" -ForegroundColor Green
            }
        } catch {
            $lastBackendError = $_.Exception.Message
        }
    }

    if (-not $frontendReady) {
        $frontendResp = $null
        try {
            $frontendResp = Invoke-WebRequest -Uri "http://127.0.0.1:3000/login" -Method Get -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            if ($frontendResp -and $frontendResp.StatusCode -eq 200) {
                $frontendReady = $true
                Write-Host "  [OK] Frontend responsive at http://127.0.0.1:3000/login" -ForegroundColor Green
            }
        } catch {
            $lastFrontendError = $_.Exception.Message
        }
    }

    if ($backendReady -and $frontendReady) {
        break
    }

    Start-Sleep -Seconds 1
}

Write-Host ""
if ($backendReady -and $frontendReady) {
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "             EduDuty Stack Successfully Started!          " -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "  Web Application:   http://127.0.0.1:3000/login" -ForegroundColor White
    Write-Host "  FastAPI Backend:   http://127.0.0.1:8000" -ForegroundColor White
    Write-Host "  Interactive Docs:  http://127.0.0.1:8000/docs" -ForegroundColor White
    Write-Host "  Active Database:   backend/eduduty_demo.db (SQLite Demo)" -ForegroundColor White
    Write-Host ""
    Write-Host "Demo Personas (Single-Click Login on /login):" -ForegroundColor Cyan
    Write-Host "  1. Exam Coordinator : coord@eduduty.ac.in" -ForegroundColor White
    Write-Host "  2. Faculty Member    : faculty@eduduty.ac.in (Prof. Test Faculty)" -ForegroundColor White
    Write-Host "  3. Super Admin       : admin@eduduty.ac.in" -ForegroundColor White
    Write-Host "  4. Read-Only Viewer  : viewer@eduduty.ac.in" -ForegroundColor White
    Write-Host ""
    Write-Host "To stop both services:" -ForegroundColor Yellow
    Write-Host "  Run:  .\start-dev.ps1 -Stop" -ForegroundColor Yellow
    Write-Host "  Or:   Stop-Process -Id $($backendProc.Id), $($frontendProc.Id) -Force" -ForegroundColor Yellow
    Write-Host "==========================================================" -ForegroundColor Green
    exit 0
} else {
    Write-Host "==========================================================" -ForegroundColor Red
    Write-Host "                 Startup Readiness Warning                " -ForegroundColor Red
    Write-Host "==========================================================" -ForegroundColor Red
    Write-Host "Timed out waiting for full service readiness after $TimeoutSeconds seconds." -ForegroundColor Red
    Write-Host "  Backend Ready : $backendReady" -ForegroundColor $(if ($backendReady) { "Green" } else { "Red" })
    if (-not $backendReady) {
        if ($lastBackendError) {
            Write-Host "    -> Last probe error: $lastBackendError" -ForegroundColor Yellow
        }
        $p8000 = @(Find-ListeningProcess -Port 8000)
        if ($p8000.Count -gt 0) {
            Write-Host "    -> Port 8000 is listening by $($p8000[0].Name) (PID $($p8000[0].PID)), but /health did not return 'ok'." -ForegroundColor Yellow
        } else {
            Write-Host "    -> No process is listening on port 8000." -ForegroundColor Yellow
        }
    }
    Write-Host "  Frontend Ready: $frontendReady" -ForegroundColor $(if ($frontendReady) { "Green" } else { "Red" })
    if (-not $frontendReady -and $lastFrontendError) {
        Write-Host "    -> Last probe error: $lastFrontendError" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Check the spawned console windows for error traces." -ForegroundColor Yellow
    Write-Host "To shut down: .\start-dev.ps1 -Stop" -ForegroundColor Yellow
    exit 1
}

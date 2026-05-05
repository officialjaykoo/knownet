param(
  [switch]$KeepExisting,
  [switch]$KeepWebCache,
  [switch]$ProductionWeb
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "local_paths.ps1")
$Root = $KnownetRoot
$ApiDir = $KnownetApiDir
$CoreDir = $KnownetCoreDir
$WebDir = $KnownetWebDir
$VenvPython = $KnownetApiVenvPython
$RunDir = Join-Path $Root "data/tmp/dev"
$LogDir = Join-Path $Root "data/logs/dev"

function Step($Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Stop-ProcessTree($ProcessId) {
  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
  foreach ($child in $children) {
    Stop-ProcessTree $child.ProcessId
  }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-KnownetDevProcesses {
  $ids = New-Object System.Collections.Generic.HashSet[int]
  foreach ($pidFile in @("api.pid", "web.pid", "api.wrapper.pid", "web.wrapper.pid")) {
    $path = Join-Path $RunDir $pidFile
    if (Test-Path $path) {
      $saved = Get-Content $path -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($saved -match '^\d+$') {
        [void]$ids.Add([int]$saved)
      }
    }
  }
  foreach ($port in @(3000, 8000)) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
      if ($connection.OwningProcess -and $connection.OwningProcess -ne 0) {
        [void]$ids.Add([int]$connection.OwningProcess)
      }
    }
  }

  $escapedRoot = [regex]::Escape($Root)
  $currentProcessId = $PID
  $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessId -ne $currentProcessId -and $_.CommandLine -and (
      $_.CommandLine -match "knownet-core\.exe" -or
      $_.CommandLine -match "knownet_api\.main:app" -or
      ($_.CommandLine -match "next dev" -and $_.CommandLine -match $escapedRoot) -or
      ($_.CommandLine -match "next start" -and $_.CommandLine -match $escapedRoot) -or
      ($_.CommandLine -match "npm.*run dev" -and $_.CommandLine -match $escapedRoot) -or
      ($_.CommandLine -match "KNOWNET_API_INTERNAL" -and $_.CommandLine -match "3000") -or
      ($_.CommandLine -match "NEXT_PUBLIC_API_BASE" -and $_.CommandLine -match "3000") -or
      ($_.CommandLine -match "LOCAL_EMBEDDING_AUTO_LOAD" -and $_.CommandLine -match "8000")
    )
  }
  foreach ($process in $processes) {
    [void]$ids.Add([int]$process.ProcessId)
  }

  foreach ($id in $ids) {
    Stop-ProcessTree $id
  }
  Remove-Item -LiteralPath (Join-Path $RunDir "api.pid") -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath (Join-Path $RunDir "web.pid") -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath (Join-Path $RunDir "api.wrapper.pid") -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath (Join-Path $RunDir "web.wrapper.pid") -Force -ErrorAction SilentlyContinue
}

function Wait-Http($Url, $Name) {
  for ($i = 0; $i -lt 40; $i++) {
    try {
      $response = Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        return $response
      }
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  throw "$Name did not become ready at $Url"
}

function Get-ListeningProcessId($Port) {
  $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($connection -and $connection.OwningProcess -and $connection.OwningProcess -ne 0) {
    return [int]$connection.OwningProcess
  }
  return $null
}

function Assert-Listening($Port, $Name) {
  $processId = Get-ListeningProcessId $Port
  if (-not $processId) {
    throw "$Name is not listening on port $Port"
  }
  return $processId
}

function Test-WebAssets {
  $html = (Wait-Http "http://127.0.0.1:3000" "Web").Content
  $assetMatches = [regex]::Matches($html, '/_next/static/[^"'' <]+')
  if ($assetMatches.Count -eq 0) {
    throw "Web returned HTML without Next static assets"
  }
}

if (-not $KeepExisting) {
  Step "Stopping existing KnowNet dev processes"
  Stop-KnownetDevProcesses
  Start-Sleep -Seconds 1
}

if (-not $KeepWebCache) {
  Step "Clearing Next dev cache"
  Remove-Item -LiteralPath (Join-Path $WebDir ".next") -Recurse -Force -ErrorAction SilentlyContinue
}

Step "Building Rust daemon"
Push-Location $CoreDir
cargo build
Pop-Location

Step "Preparing API virtual environment"
if (-not (Test-Path $VenvPython)) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $KnownetApiVenvDir) | Out-Null
  python -m venv $KnownetApiVenvDir
}

Push-Location $ApiDir
& $VenvPython -m pip install -e .
Pop-Location

Step "Installing web dependencies"
Push-Location $WebDir
npm install
if ($ProductionWeb) {
  npm run build
}
Pop-Location

if (-not $env:LOCAL_EMBEDDING_AUTO_LOAD) {
  $env:LOCAL_EMBEDDING_AUTO_LOAD = "false"
}
if (-not (Test-Path Env:NEXT_PUBLIC_API_BASE)) {
  $env:NEXT_PUBLIC_API_BASE = ""
}
if (-not $env:KNOWNET_API_INTERNAL) {
  $env:KNOWNET_API_INTERNAL = "http://127.0.0.1:8000"
}

New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null
$ApiOut = Join-Path $LogDir "api.out.log"
$ApiErr = Join-Path $LogDir "api.err.log"
$WebOut = Join-Path $LogDir "web.out.log"
$WebErr = Join-Path $LogDir "web.err.log"
Remove-Item -LiteralPath $ApiOut, $ApiErr, $WebOut, $WebErr -Force -ErrorAction SilentlyContinue

Step "Starting API and Web"
Write-Host "API: http://127.0.0.1:8000"
Write-Host "Web: http://127.0.0.1:3000"
if ($ProductionWeb) {
  Write-Host "Web mode: production"
} else {
  Write-Host "Web mode: development"
}
Write-Host "Logs: $LogDir"

$apiProcess = Start-Process $VenvPython -WindowStyle Hidden -PassThru -WorkingDirectory $ApiDir -RedirectStandardOutput $ApiOut -RedirectStandardError $ApiErr -ArgumentList @(
  "-m",
  "uvicorn",
  "knownet_api.main:app",
  "--host",
  "127.0.0.1",
  "--port",
  "8000"
)
Set-Content -LiteralPath (Join-Path $RunDir "api.wrapper.pid") -Value $apiProcess.Id

$nextBin = Join-Path $WebDir "node_modules/next/dist/bin/next"
$nextCommand = if ($ProductionWeb) { "start" } else { "dev" }
$webProcess = Start-Process node -WindowStyle Hidden -PassThru -WorkingDirectory $WebDir -RedirectStandardOutput $WebOut -RedirectStandardError $WebErr -ArgumentList @(
  $nextBin,
  $nextCommand,
  "--hostname",
  "127.0.0.1",
  "--port",
  "3000"
)
Set-Content -LiteralPath (Join-Path $RunDir "web.wrapper.pid") -Value $webProcess.Id

Step "Checking dev servers"
try {
  Wait-Http "http://127.0.0.1:8000/health/summary" "API" | Out-Null
  Test-WebAssets
  $apiListenerPid = Assert-Listening 8000 "API"
  $webListenerPid = Assert-Listening 3000 "Web"
  Set-Content -LiteralPath (Join-Path $RunDir "api.pid") -Value $apiListenerPid
  Set-Content -LiteralPath (Join-Path $RunDir "web.pid") -Value $webListenerPid
} catch {
  Write-Host ""
  Write-Host "Startup failed. Recent API log:" -ForegroundColor Yellow
  Get-Content $ApiErr, $ApiOut -Tail 40 -ErrorAction SilentlyContinue
  Write-Host ""
  Write-Host "Recent Web log:" -ForegroundColor Yellow
  Get-Content $WebErr, $WebOut -Tail 40 -ErrorAction SilentlyContinue
  throw
}
Write-Host "Dev servers are ready." -ForegroundColor Green
Write-Host "API listener PID: $apiListenerPid"
Write-Host "Web listener PID: $webListenerPid"
Write-Host "PID files: $RunDir"

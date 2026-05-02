$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root "data/tmp/dev"

Write-Host "Ports"
Get-NetTCPConnection -LocalPort 3000,8000 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object {
    $process = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    Write-Host "$($_.LocalPort) pid=$($_.OwningProcess) process=$($process.ProcessName)"
  }

Write-Host ""
Write-Host "PID files"
foreach ($name in @("api.pid", "web.pid", "api.wrapper.pid", "web.wrapper.pid")) {
  $path = Join-Path $RunDir $name
  $value = if (Test-Path $path) { Get-Content $path -ErrorAction SilentlyContinue | Select-Object -First 1 } else { "<missing>" }
  Write-Host "$name=$value"
}

Write-Host ""
Write-Host "Health"
try {
  $response = Invoke-WebRequest http://127.0.0.1:8000/health/summary -UseBasicParsing -TimeoutSec 5
  Write-Host $response.Content
} catch {
  Write-Host $_.Exception.Message
}

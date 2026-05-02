$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root "data/tmp/dev/cloudflared.pid"

if (Test-Path $PidFile) {
  $savedProcessId = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($savedProcessId -match '^\d+$') {
    Stop-Process -Id ([int]$savedProcessId) -Force -ErrorAction SilentlyContinue
  }
  Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "Cloudflare tunnel stopped." -ForegroundColor Green

param(
  [switch]$SkipHealthCheck
)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

function Resolve-Cloudflared {
  $command = Get-Command cloudflared -ErrorAction SilentlyContinue
  if ($command) {
    return $command.Source
  }

  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Microsoft/WinGet/Links/cloudflared.exe"),
    (Join-Path $env:LOCALAPPDATA "Microsoft/WinGet/Packages/Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe/cloudflared.exe"),
    (Join-Path $env:ProgramFiles "cloudflared/cloudflared.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }
  return $null
}

$Cloudflared = Resolve-Cloudflared
if (-not $Cloudflared) {
  throw "cloudflared was not found. Install it first, for example: winget install Cloudflare.cloudflared"
}

if (-not $SkipHealthCheck) {
  & (Join-Path $Root "scripts/ops_check.ps1")
  Invoke-WebRequest "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 5 | Out-Null
}

Write-Host ""
Write-Host "Starting a Cloudflare quick tunnel to the KnowNet web app." -ForegroundColor Cyan
Write-Host "This exposes http://127.0.0.1:3000 only. The API should stay bound to 127.0.0.1:8000." -ForegroundColor Cyan
Write-Host "For real external use, enable PUBLIC_MODE, a long ADMIN_TOKEN, and a Cloudflare Access policy." -ForegroundColor Yellow
Write-Host "Stop the tunnel with Ctrl+C." -ForegroundColor Yellow
Write-Host ""

& $Cloudflared tunnel --url http://127.0.0.1:3000

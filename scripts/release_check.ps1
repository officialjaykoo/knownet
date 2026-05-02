$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root "apps/api"
$CoreDir = Join-Path $Root "apps/core"
$WebDir = Join-Path $Root "apps/web"
$VenvPython = Join-Path $ApiDir ".venv/Scripts/python.exe"

function Step($Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

Step "Rust tests"
Push-Location $CoreDir
cargo test
Pop-Location

Step "API tests"
if (-not (Test-Path $VenvPython)) {
  throw "API virtualenv not found at apps/api/.venv. Run scripts/dev.ps1 first."
}
Push-Location $ApiDir
& $VenvPython -m pytest -m "not slow and not smoke"
Pop-Location

Step "Slow operational API tests"
Push-Location $ApiDir
& $VenvPython -m pytest -m slow
Pop-Location

Step "Smoke tests"
Push-Location $ApiDir
& $VenvPython -m pytest -m smoke
Pop-Location

Step "Web dependency audit"
Push-Location $WebDir
npm audit --audit-level=moderate
Pop-Location

Step "Web build"
Push-Location $WebDir
npm run build
Pop-Location

Write-Host ""
Write-Host "Release checks passed." -ForegroundColor Green

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root "apps/api"
$VenvPython = Join-Path $ApiDir ".venv/Scripts/python.exe"

if (-not (Test-Path $VenvPython)) {
  throw "API virtualenv not found at apps/api/.venv. Run scripts/dev.ps1 first."
}

Push-Location $ApiDir
& $VenvPython -m pytest -m "not slow and not smoke" --lf -q
Pop-Location

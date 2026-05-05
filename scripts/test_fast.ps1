$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "local_paths.ps1")
$Root = $KnownetRoot
$ApiDir = $KnownetApiDir
$VenvPython = $KnownetApiVenvPython

if (-not (Test-Path $VenvPython)) {
  throw "API virtualenv not found at .local/venvs/api. Run scripts/dev.ps1 first."
}

Push-Location $ApiDir
& $VenvPython -m pytest -m "not slow and not smoke" --lf -q
Pop-Location

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "local_paths.ps1")
$Root = $KnownetRoot
$ApiDir = $KnownetApiDir
$Python = $KnownetPython

Push-Location $ApiDir
& $Python -m pytest -m "not slow and not smoke" --lf -q
Pop-Location

$KnownetRoot = Split-Path -Parent $PSScriptRoot
$KnownetApiDir = Join-Path $KnownetRoot "apps/api"
$KnownetCoreDir = Join-Path $KnownetRoot "apps/core"
$KnownetWebDir = Join-Path $KnownetRoot "apps/web"
$KnownetLocalDir = Join-Path $KnownetRoot ".local"
$KnownetApiVenvDir = Join-Path $KnownetLocalDir "venvs/api"
$KnownetApiVenvPython = Join-Path $KnownetApiVenvDir "Scripts/python.exe"

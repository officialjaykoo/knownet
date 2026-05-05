param(
  [switch]$All
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "local_paths.ps1")

function Resolve-InRepoPath($RelativePath) {
  $path = Join-Path $KnownetRoot $RelativePath
  if (-not (Test-Path $path)) {
    return $null
  }
  $resolved = (Resolve-Path -LiteralPath $path).Path
  $root = (Resolve-Path -LiteralPath $KnownetRoot).Path
  if (-not ($resolved -eq $root -or $resolved.StartsWith($root + [IO.Path]::DirectorySeparatorChar))) {
    throw "Refusing to remove path outside repository: $resolved"
  }
  return $resolved
}

function Remove-GeneratedPath($RelativePath) {
  $resolved = Resolve-InRepoPath $RelativePath
  if ($resolved) {
    Write-Host "Removing $RelativePath"
    Remove-Item -LiteralPath $resolved -Recurse -Force
  }
}

$targets = @(
  ".pytest_cache",
  "apps/api/.pytest_cache",
  "apps/api/knownet_api.egg-info",
  "packages/knownet-agent-py/.pytest_cache",
  "packages/knownet-agent-py/knownet_agent.egg-info",
  "apps/web/.next",
  "data/experiment-packets",
  "data/project-snapshot-packets"
)

$root = (Resolve-Path -LiteralPath $KnownetRoot).Path
$excludedGeneratedRoots = @(
  (Join-Path $root ".local"),
  (Join-Path $root "apps/web/node_modules"),
  (Join-Path $root "apps/core/target")
)

foreach ($cache in Get-ChildItem -LiteralPath $KnownetRoot -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue) {
  $insideExcludedRoot = $false
  foreach ($excludedRoot in $excludedGeneratedRoots) {
    if ($cache.FullName -eq $excludedRoot -or $cache.FullName.StartsWith($excludedRoot + [IO.Path]::DirectorySeparatorChar)) {
      $insideExcludedRoot = $true
      break
    }
  }
  if (-not $insideExcludedRoot -and $cache.FullName.StartsWith($root + [IO.Path]::DirectorySeparatorChar)) {
    Write-Host "Removing $($cache.FullName.Substring($root.Length + 1))"
    Remove-Item -LiteralPath $cache.FullName -Recurse -Force
  }
}

foreach ($target in $targets) {
  Remove-GeneratedPath $target
}

if ($All) {
  foreach ($target in @(".local", "apps/api/.venv", "apps/web/node_modules", "apps/core/target")) {
    Remove-GeneratedPath $target
  }
}

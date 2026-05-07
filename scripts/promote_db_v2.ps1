param(
  [string]$Source = "data\knownet.db",
  [string]$Candidate = "data\knownet-v2.db",
  [string]$BackupDir = "data\backups",
  [switch]$Apply,
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\local_paths.ps1"

$sourcePath = Join-Path $KnownetRoot $Source
$candidatePath = Join-Path $KnownetRoot $Candidate
$backupDirPath = Join-Path $KnownetRoot $BackupDir

if (-not $SkipTests) {
  Push-Location $KnownetApiDir
  try {
    & $KnownetPython -m pytest tests\test_phase31_v2_boot.py tests\test_phase31_v2_collaboration.py -q
  }
  finally {
    Pop-Location
  }
}

$args = @(
  "-m", "knownet_api.db.v2_promote",
  "--source", $sourcePath,
  "--candidate", $candidatePath,
  "--backup-dir", $backupDirPath,
  "--overwrite-candidate"
)

if ($Apply) {
  $args += "--apply"
}

Push-Location $KnownetApiDir
try {
  & $KnownetPython @args
}
finally {
  Pop-Location
}

param(
  [Parameter(Mandatory = $true)]
  [string]$SarifPath,
  [Parameter(Mandatory = $true)]
  [string]$Repository,
  [string]$CommitSha = "",
  [string]$Ref = ""
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  throw "GitHub CLI 'gh' is required for SARIF upload. Install and authenticate gh first."
}

$resolvedSarif = Resolve-Path -LiteralPath $SarifPath
if (-not $CommitSha) {
  $CommitSha = (git rev-parse HEAD).Trim()
}
if (-not $Ref) {
  $branch = (git branch --show-current).Trim()
  if (-not $branch) {
    $branch = "main"
  }
  $Ref = "refs/heads/$branch"
}

$bytes = [System.IO.File]::ReadAllBytes($resolvedSarif)
$base64 = [Convert]::ToBase64String($bytes)
$body = @{
  commit_sha = $CommitSha
  ref = $Ref
  sarif = $base64
  tool_name = "KnowNet"
} | ConvertTo-Json -Depth 4

$tmp = New-TemporaryFile
try {
  Set-Content -LiteralPath $tmp -Value $body -Encoding UTF8
  gh api "repos/$Repository/code-scanning/sarifs" --method POST --input $tmp
  Write-Output "SARIF upload requested for $Repository at $CommitSha ($Ref)."
} finally {
  Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}

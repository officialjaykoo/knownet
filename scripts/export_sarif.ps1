param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$OutputPath = "data/exports/knownet-findings.sarif",
  [string]$VaultId = "local-default",
  [string]$Status = "accepted,implemented",
  [string]$EvidenceQuality = "direct_access,operator_verified",
  [int]$Limit = 100
)

$ErrorActionPreference = "Stop"

$output = Resolve-Path -LiteralPath "." | ForEach-Object { Join-Path $_ $OutputPath }
$outputDir = Split-Path -Parent $output
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$uri = "$BaseUrl/api/collaboration/findings.sarif?vault_id=$([uri]::EscapeDataString($VaultId))&status=$([uri]::EscapeDataString($Status))&evidence_quality=$([uri]::EscapeDataString($EvidenceQuality))&limit=$Limit"
Invoke-WebRequest -Uri $uri -OutFile $output -Headers @{ Accept = "application/sarif+json" }
Write-Output "SARIF exported to $output"

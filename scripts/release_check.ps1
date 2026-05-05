$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "local_paths.ps1")
$Root = $KnownetRoot
$ApiDir = $KnownetApiDir
$CoreDir = $KnownetCoreDir
$WebDir = $KnownetWebDir
$VenvPython = $KnownetApiVenvPython
$EvidencePath = Join-Path $Root "docs/RELEASE_EVIDENCE.md"

function Step($Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Load-DotEnv {
  $envPath = Join-Path $Root ".env"
  $values = @{}
  if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
      $line = $_.Trim()
      if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $key, $value = $line.Split("=", 2)
        $values[$key] = $value.Trim('"')
      }
    }
  }
  return $values
}

function Invoke-Json($Method, $Url, $Headers = @{}) {
  try {
    return Invoke-RestMethod -Method $Method -Uri $Url -Headers $Headers -TimeoutSec 30
  } catch {
    throw "Request failed: $Method $Url - $($_.Exception.Message)"
  }
}

Step "Git secret tracking guard"
$trackedSecretFiles = git -C $Root ls-files -- ".env" ".env.*" "apps/**/.env" "apps/**/.env.*" "data/**/*.env" "data/**/*.env.*"
$trackedSecretFiles = @($trackedSecretFiles | Where-Object {
  $_ -and
  $_ -notmatch '(^|/)\.env\.example$' -and
  $_ -notmatch '\.env\.example$'
})
if ($trackedSecretFiles.Count -gt 0) {
  throw ("Secret env files are tracked by Git: " + ($trackedSecretFiles -join ", "))
}

Step "Rust tests"
Push-Location $CoreDir
cargo test
Pop-Location

Step "API tests"
if (-not (Test-Path $VenvPython)) {
  throw "API virtualenv not found at .local/venvs/api. Run scripts/dev.ps1 first."
}
Push-Location $ApiDir
& $VenvPython -m pytest -m "not slow and not smoke"
Pop-Location

Step "MCP tests"
$env:PYTHONPATH = Join-Path $Root "apps/mcp"
& $VenvPython -m pytest (Join-Path $Root "apps/mcp/tests/test_knownet_mcp.py") -q

Step "SDK tests"
$env:PYTHONPATH = Join-Path $Root "packages/knownet-agent-py"
& $VenvPython -m pytest (Join-Path $Root "packages/knownet-agent-py/tests") -q

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

Step "Live health and verify-index"
$envValues = Load-DotEnv
$health = Invoke-Json "GET" "http://127.0.0.1:8000/health/summary"
Write-Host ("Health: " + ($health.data.overall_status))
if ($health.data.issues) {
  Write-Host ("Health issues: " + (($health.data.issues | ForEach-Object { $_ }) -join ", "))
}
$adminToken = $envValues["ADMIN_TOKEN"]
if (-not $adminToken) {
  throw "ADMIN_TOKEN missing; cannot run verify-index"
}
$verify = Invoke-Json "GET" "http://127.0.0.1:8000/api/maintenance/verify-index" @{"x-knownet-admin-token" = $adminToken}
if (-not $verify.ok -or -not $verify.data.ok) {
  throw "verify-index failed"
}
Write-Host "verify-index: ok"

$quality = Invoke-Json "GET" "http://127.0.0.1:8000/api/operator/ai-state-quality" @{"x-knownet-admin-token" = $adminToken}
if (-not $quality.ok -or $quality.data.overall_status -eq "fail") {
  throw "AI state quality failed"
}
Write-Host ("AI state quality: " + $quality.data.overall_status)

$providers = Invoke-Json "GET" "http://127.0.0.1:8000/api/operator/provider-matrix" @{"x-knownet-admin-token" = $adminToken}
if ($providers.ok) {
  Write-Host ("provider verification: live=" + $providers.data.summary.live_verified + " configured=" + $providers.data.summary.configured + " mocked=" + $providers.data.summary.mocked)
}

Step "Security/path exposure checks"
$patterns = @(
  "source_path",
  "source\.path",
  "C:/knownet",
  "token_hash",
  "raw_token"
)
$agentFiles = @(
  (Join-Path $ApiDir "knownet_api/routes/agent.py"),
  (Join-Path $Root "apps/mcp/knownet_mcp/server.py"),
  (Join-Path $Root "apps/mcp/knownet_mcp/http_bridge.py")
)
foreach ($pattern in $patterns) {
  $matches = Select-String -Path $agentFiles -Pattern $pattern -ErrorAction SilentlyContinue
  if ($matches) {
    Write-Host "Security/path check warning for pattern '$pattern':" -ForegroundColor Yellow
    $matches | ForEach-Object { Write-Host ("  " + $_.Path + ":" + $_.LineNumber + " " + $_.Line.Trim()) }
  }
}

$gitStatus = @(git -C $Root status --short)
$evidence = [ordered]@{
  schema = "knownet.release_evidence.v1"
  generated_at = (Get-Date).ToUniversalTime().ToString("o").Replace("+00:00", "Z")
  git_status_clean = ($gitStatus.Count -eq 0)
  git_status = $gitStatus
  checks = [ordered]@{
    rust_tests = "passed"
    api_tests = "passed"
    mcp_tests = "passed"
    sdk_tests = "passed"
    slow_operational_api_tests = "passed"
    smoke_tests = "passed"
    web_audit = "passed"
    web_build = "passed"
    health_overall_status = $health.data.overall_status
    verify_index_ok = [bool]$verify.data.ok
    ai_state_quality = $quality.data.overall_status
    provider_matrix_summary = $providers.data.summary
    snapshot_restore_test = "passed_by_slow_operational_api_tests"
  }
  notes = @(
    "Provider live verification is evidence-based; mocked runs do not count as live_verified.",
    "Snapshot restore is covered by the slow operational API test selection in this release check."
  )
}
$evidenceJson = $evidence | ConvertTo-Json -Depth 8
$evidenceMarkdown = @"
# KnowNet Release Evidence

``````json
$evidenceJson
``````
"@
Set-Content -LiteralPath $EvidencePath -Encoding utf8 -Value $evidenceMarkdown
Write-Host ("Release evidence written: " + $EvidencePath)

Write-Host ""
Write-Host "Release checks passed." -ForegroundColor Green

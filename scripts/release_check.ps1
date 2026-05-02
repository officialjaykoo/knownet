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
  throw "API virtualenv not found at apps/api/.venv. Run scripts/dev.ps1 first."
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

Write-Host ""
Write-Host "Release checks passed." -ForegroundColor Green

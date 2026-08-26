param([string]$Output = "")
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root
if (-not $Output) { $Output = Join-Path $Root ("sigq-runtime-{0}.zip" -f (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if (-not (Test-Path backend/.env)) { throw 'Missing backend/.env' }
if (-not (Test-Path config/cloudflare/credentials.json)) { throw 'Missing Cloudflare credentials.json' }

$Stage = Join-Path ([IO.Path]::GetTempPath()) ("sigq-export-" + [guid]::NewGuid())
$Secrets = Join-Path $Stage 'secrets'; $Volumes = Join-Path $Stage 'volumes'
New-Item -ItemType Directory -Force $Secrets,$Volumes | Out-Null
$Stopped = $false
try {
  Copy-Item backend/.env (Join-Path $Secrets 'backend.env')
  Copy-Item config/cloudflare/credentials.json (Join-Path $Secrets 'cloudflare-credentials.json')
  $running = docker compose ps --status running --services
  if ($running -match 'market-api|ai-news') {
    docker compose stop market-api ai-news | Out-Null
    $Stopped = $true
  }
  foreach ($volume in @('iros-desk-state','iros-backend-data','iros-eod-archive')) {
    docker volume inspect "sigq_${volume}" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Missing Docker volume sigq_${volume}" }
    docker run --rm -v "sigq_${volume}:/source:ro" -v "${Volumes}:/backup" alpine:3.21 sh -c "tar czf /backup/${volume}.tar.gz -C /source ."
    if ($LASTEXITCODE -ne 0) { throw "Failed to export $volume" }
  }
  @("bundleVersion=1", "createdAt=$((Get-Date).ToUniversalTime().ToString('o'))", "gitCommit=$(git rev-parse HEAD)", 'composeProject=sigq') |
    Set-Content (Join-Path $Stage 'manifest.txt')
  Compress-Archive -Path (Join-Path $Stage '*') -DestinationPath $Output -Force
  Write-Warning 'The ZIP contains live credentials. Transfer it through an encrypted channel and delete it after import.'
  Write-Host "Runtime bundle: $Output" -ForegroundColor Green
} finally {
  if ($Stopped) { docker compose start market-api ai-news | Out-Null }
  Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
}

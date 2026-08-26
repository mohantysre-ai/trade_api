param([ValidateSet('Pull','Build')][string]$Mode = 'Build')
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop/Engine is required.' }
docker info | Out-Null
docker compose version | Out-Null
if (-not (Test-Path backend/.env)) { throw 'Missing backend/.env. Copy backend/.env.example and add credentials.' }
$envText = Get-Content backend/.env -Raw
foreach ($key in @('ANGEL_API_KEY','ANGEL_CLIENT_ID','ANGEL_TOTP_SECRET')) {
  if ($envText -notmatch "(?m)^$key=.+$") { throw "backend/.env is missing $key." }
}
if ($envText -notmatch '(?m)^ANGEL_(MPIN|PASSWORD)=.+$') { throw 'backend/.env needs ANGEL_MPIN or ANGEL_PASSWORD.' }
if (-not (Test-Path config/cloudflare/credentials.json)) { throw 'Missing config/cloudflare/credentials.json.' }
$credential = Get-Content config/cloudflare/credentials.json -Raw | ConvertFrom-Json
if (-not $credential.TunnelID) { throw 'Cloudflare credentials.json does not contain TunnelID.' }
docker compose --profile tunnel config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed.' }

if ($Mode -eq 'Pull') {
  docker compose --profile tunnel pull
  if ($LASTEXITCODE -ne 0) { throw 'Image pull failed. Check Docker Hub login/network.' }
  docker compose --profile tunnel up -d --no-build --remove-orphans --wait --wait-timeout 300
} else {
  docker compose --profile tunnel up -d --build --remove-orphans --wait --wait-timeout 300
}
if ($LASTEXITCODE -ne 0) { throw 'Container startup or health validation failed.' }
docker compose --profile tunnel ps
Write-Host 'SIGQ is healthy: local http://127.0.0.1:3000 | public https://sigq.in' -ForegroundColor Green

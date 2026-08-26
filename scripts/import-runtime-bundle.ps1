param([Parameter(Mandatory=$true)][string]$Bundle)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root
$Bundle = (Resolve-Path $Bundle).Path
$Stage = Join-Path ([IO.Path]::GetTempPath()) ("sigq-import-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force $Stage | Out-Null
try {
  Expand-Archive -Path $Bundle -DestinationPath $Stage -Force
  Copy-Item (Join-Path $Stage 'secrets/backend.env') backend/.env -Force
  Copy-Item (Join-Path $Stage 'secrets/cloudflare-credentials.json') config/cloudflare/credentials.json -Force
  foreach ($volume in @('iros-desk-state','iros-backend-data','iros-eod-archive')) {
    docker volume create --label com.docker.compose.project=sigq --label "com.docker.compose.volume=${volume}" "sigq_${volume}" | Out-Null
    $archive = Join-Path $Stage "volumes/${volume}.tar.gz"
    if (-not (Test-Path $archive)) { continue }
    docker run --rm -v "sigq_${volume}:/target" -v "${Stage}/volumes:/backup:ro" alpine:3.21 sh -c "find /target -mindepth 1 -maxdepth 1 -exec rm -rf {} + && tar xzf /backup/${volume}.tar.gz -C /target"
    if ($LASTEXITCODE -ne 0) { throw "Failed to restore $volume" }
  }
  Write-Host 'Runtime restored. Run: .\scripts\deploy-portable.ps1 -Mode Build' -ForegroundColor Green
} finally {
  Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
}

#Requires -Version 5.1
# Start cloudflared tunnel fully hidden (no extra terminal).
# Logs to logs/cloudflared.out.log and logs/cloudflared.err.log

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$LogDir = Join-Path $ProjectRoot "logs"
$ConfigPath = Join-Path $env:USERPROFILE ".cloudflared\config.yml"

$Cloudflared = @(
  "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe",
  "$env:ProgramFiles\cloudflared\cloudflared.exe",
  (Get-Command cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $Cloudflared) {
  Write-Host "[WARN] cloudflared.exe not found" -ForegroundColor Yellow
  exit 2
}
if (-not (Test-Path $ConfigPath)) {
  Write-Host "[WARN] Missing $ConfigPath - run setup-cloudflare-tunnel.bat once" -ForegroundColor Yellow
  exit 3
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$OutLog = Join-Path $LogDir "cloudflared.out.log"
$ErrLog = Join-Path $LogDir "cloudflared.err.log"

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Hidden process - no console window. Survives after this script exits.
$proc = Start-Process -FilePath $Cloudflared `
  -ArgumentList @("tunnel", "--config", $ConfigPath, "run") `
  -WorkingDirectory $ProjectRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $OutLog `
  -RedirectStandardError $ErrLog `
  -PassThru

Start-Sleep -Seconds 3
if ($proc.HasExited) {
  Write-Host "[FAIL] cloudflared exited early (code $($proc.ExitCode)). See $ErrLog" -ForegroundColor Red
  if (Test-Path $ErrLog) { Get-Content $ErrLog -Tail 20 }
  exit 1
}

Write-Host "[OK] cloudflared running hidden (PID $($proc.Id))" -ForegroundColor Green
Write-Host "     logs: $OutLog"
Write-Host "     errs: $ErrLog"
exit 0

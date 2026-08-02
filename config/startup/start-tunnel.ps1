#Requires -Version 5.1
<#
.SYNOPSIS
  Run Cloudflare Tunnel hidden (prefer start_app.bat which already does this).
#>
& "$PSScriptRoot\start-cloudflared-background.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Tunnel is running in the background. This window can be closed." -ForegroundColor Cyan
Write-Host "Public: https://sigq.in"
Write-Host "Stop:   taskkill /IM cloudflared.exe /F"

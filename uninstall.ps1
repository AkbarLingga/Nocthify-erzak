# Nocthify - erzak | Windows uninstaller
#   powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Nocthify\app\uninstall.ps1"
$ErrorActionPreference = "SilentlyContinue"
$Root = Join-Path $env:LOCALAPPDATA "Nocthify"
$pyw  = Join-Path $Root "venv\Scripts\pythonw.exe"
$run  = Join-Path $Root "app\run.pyw"

Write-Host "  >  Stopping Nocthify and restoring the Windows taskbar..." -ForegroundColor Cyan
if (Test-Path $pyw) { Start-Process $pyw -ArgumentList "`"$run`" --restore-taskbar" -Wait }

Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "Nocthify"
$sm = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
foreach ($n in @("Nocthify", "Nocthify Settings", "Restore Windows Taskbar")) { Remove-Item (Join-Path $sm "$n.lnk") }

Set-Location $env:TEMP
Remove-Item $Root -Recurse -Force
Write-Host "  OK Nocthify removed. Your settings are kept in %APPDATA%\Nocthify (delete it to remove them too)." -ForegroundColor Green

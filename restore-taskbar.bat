@echo off
rem Emergency: bring the normal Windows taskbar back (also stops Nocthify).
set "PYW=%LOCALAPPDATA%\Nocthify\venv\Scripts\pythonw.exe"
set "APP=%LOCALAPPDATA%\Nocthify\app\run.pyw"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  set "PYW=%~dp0.venv\Scripts\pythonw.exe"
  set "APP=%~dp0run.pyw"
)
if exist "%PYW%" (
  "%PYW%" "%APP%" --restore-taskbar
) else (
  rem No Python found: restarting Explorer always brings the taskbar back.
  taskkill /f /im explorer.exe >nul 2>&1
  start explorer.exe
)
echo Taskbar restored.
timeout /t 2 >nul

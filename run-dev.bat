@echo off
rem Run Nocthify straight from this folder (for development / trying it out).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Creating .venv and installing dependencies...
  python -m venv .venv || py -3 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
if not exist ".venv\Scripts\Nocthify.exe" ".venv\Scripts\python.exe" run.pyw --make-exe >nul 2>&1
if exist ".venv\Scripts\Nocthify.exe" (
  start "" ".venv\Scripts\Nocthify.exe" "%~dp0run.pyw" %*
) else (
  start "" ".venv\Scripts\pythonw.exe" "%~dp0run.pyw" %*
)

@echo off
rem Run Nocthify straight from this folder (for development / trying it out).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Creating .venv and installing dependencies...
  python -m venv .venv || py -3 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0run.pyw" %*

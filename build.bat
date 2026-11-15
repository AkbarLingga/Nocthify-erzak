@echo off
rem Double-click to build release\NocthifySetup-<version>.exe (developer machine only).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv and installing dependencies...
  python -m venv .venv || py -3 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
".venv\Scripts\python.exe" build.py
pause

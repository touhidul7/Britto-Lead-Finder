@echo off
cd /d "%~dp0"
if not exist ".venv-win\Scripts\python.exe" python -m venv .venv-win
".venv-win\Scripts\python.exe" -m pip install --upgrade pip
".venv-win\Scripts\python.exe" -m pip install -r requirements.txt
echo Install complete. Run run_app.bat

@echo off
cd /d "%~dp0"
if not exist ".venv-win\Scripts\python.exe" call install.bat
".venv-win\Scripts\python.exe" -c "import streamlit" >nul 2>&1
if errorlevel 1 call install.bat
".venv-win\Scripts\python.exe" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501

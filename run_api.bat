@echo off
call .venv\Scripts\activate.bat
uvicorn listingsfinder.api:app --host 0.0.0.0 --port 8000

@echo off
echo Starting RFM Segmentation App...

echo.
echo [1/2] Starting FastAPI backend on http://localhost:8000
start "RFM Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\pip install -r requirements.txt && venv\Scripts\uvicorn main:app --reload --port 8000"

timeout /t 3 /nobreak > nul

echo [2/2] Starting React frontend on http://localhost:3000
start "RFM Frontend" cmd /k "cd /d %~dp0frontend && npm install && npm start"

echo.
echo Both servers are starting. Open http://localhost:3000 in your browser.

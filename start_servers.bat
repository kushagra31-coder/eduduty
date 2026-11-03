@echo off
title EduDuty Server Launcher
echo ========================================================
echo   Starting EduDuty Portal (Backend + Frontend)
echo ========================================================
echo.

echo Starting FastAPI Backend on port 8000...
start "EduDuty Backend" cmd /k "cd /d %~dp0backend && (if exist venv\Scripts\uvicorn.exe (venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000) else (uvicorn main:app --host 0.0.0.0 --port 8000))"

timeout /t 3 /nobreak >nul

echo Starting Next.js Frontend on port 3000...
start "EduDuty Frontend" cmd /k "cd /d %~dp0frontend && npm start"

echo.
echo ========================================================
echo   Servers are launching!
echo   Frontend: http://localhost:3000
echo   Backend:  http://localhost:8000
echo ========================================================
pause

@echo off
REM Grove launcher for Windows.
REM Opens two separate console windows: one for the backend, one for the
REM frontend. Closing either window stops that server; closing both stops
REM Grove entirely. No admin rights or tmux needed.

cd /d "%~dp0"

echo Installing/checking backend dependency (aiohttp)...
python -m pip install aiohttp --quiet

start "Grove backend" cmd /k "cd backend && python server.py"
timeout /t 2 /nobreak >nul
start "Grove frontend" cmd /k "cd frontend && python serve.py"

echo.
echo Grove is starting in two new windows: "Grove backend" and "Grove frontend".
echo Open http://localhost:8080 in your browser.
echo To stop Grove, close both of those windows.
echo.
pause

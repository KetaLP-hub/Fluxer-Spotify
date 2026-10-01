@echo off
cd /d "%~dp0"
python spotify_status.py %*
if errorlevel 1 (
  echo.
  echo Fehler / Error - siehe oben / see above. Tipp / hint: start.bat doctor
)
pause

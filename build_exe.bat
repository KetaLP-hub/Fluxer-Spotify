@echo off
rem Builds dist\Fluxer-Spotify.exe (single file, console app). Needs: pip install -r requirements-dev.txt
cd /d "%~dp0"
python -m PyInstaller --onefile --console --clean --noconfirm --name Fluxer-Spotify spotify_status.py || exit /b 1
echo.
echo Fertig / Done: dist\Fluxer-Spotify.exe
certutil -hashfile dist\Fluxer-Spotify.exe SHA256

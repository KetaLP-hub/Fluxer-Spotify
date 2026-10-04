@echo off
rem Builds dist\Fluxer-Spotify.exe: one file, a windowed program (no console window; double-click opens the launcher).
rem Needs: pip install -r requirements-dev.txt
rem --noupx: UPX-packed programs are flagged by antivirus tools far more often.
cd /d "%~dp0"
python -m PyInstaller --onefile --windowed --noupx --clean --noconfirm --name Fluxer-Spotify --icon assets\icon.ico --version-file version_info.txt --add-data "assets\icon.ico;assets" spotify_status.py || exit /b 1
echo.
echo Fertig / Done: dist\Fluxer-Spotify.exe
certutil -hashfile dist\Fluxer-Spotify.exe SHA256
echo.
echo Optional: sign it (see SIGNING.md) so Windows SmartScreen trusts it.

#!/data/data/com.termux/files/usr/bin/sh
# Alles in einem: anmelden, Autostart einrichten, jetzt im Hintergrund starten.
# Everything in one go: log in, set up autostart, start in the background now.
cd "$(dirname "$0")/.." || exit 1
if ! command -v python >/dev/null 2>&1; then
    echo "Python fehlt / Python is missing. Install it with:  pkg install python"
    exit 1
fi
export BROWSER="${BROWSER:-termux-open-url}"  # Spotify login opens the phone's browser
trap ':' INT  # Ctrl+C below ends the program, not this script

echo "== 1/3 Anmelden / Log in =="
echo "Beantworte die Fragen. Sobald es laeuft und dein Status stimmt: Strg+C druecken."
echo "Answer the questions. Once it is running and your status looks right: press Ctrl+C."
python spotify_status.py run
echo
echo "== Pruefe die Anmeldung / Checking the login =="
if ! python spotify_status.py doctor; then
    echo
    echo "Die Einrichtung ist noch nicht fertig (siehe oben). Nochmal starten: sh termux/setup.sh"
    echo "Setup is not finished yet (see above). Run it again: sh termux/setup.sh"
    exit 1
fi

echo
echo "== 2/3 Autostart nach Neustart / Autostart after reboot =="
sh termux/install-boot.sh

echo
echo "== 3/3 Jetzt im Hintergrund starten / Start in the background now =="
nohup sh termux/start.sh >/dev/null 2>&1 &
echo "Fertig / Done. Der Status laeuft jetzt im Hintergrund. / The status now runs in the background."
echo "Log: python spotify_status.py logs   |   Beenden / stop: python spotify_status.py stop"

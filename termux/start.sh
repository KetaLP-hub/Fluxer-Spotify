#!/data/data/com.termux/files/usr/bin/sh
# Fluxer-Spotify auf Android (Termux) starten / Start Fluxer-Spotify on Android (Termux).
#
# Haelt die CPU wach und startet das Programm im Hintergrundmodus (fragt nie etwas, Log in fluxer-spotify.log).
# Endet es mit einem Fehler (z. B. abgelaufener Login, kein Netz), wird es nach 5 Minuten erneut versucht.
# Wurde es mit "stop" beendet oder laeuft schon eine Instanz, endet dieses Skript.
# Keeps the CPU awake and runs the program in background mode (never prompts, log in fluxer-spotify.log).
# After an error (e.g. expired login, no network) it tries again after 5 minutes.
# After "stop", or when an instance already runs, this script ends.
cd "$(dirname "$0")/.." || exit 1
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
RETRY="${FLUXER_SPOTIFY_RETRY_SECONDS:-300}"
while true; do
    python spotify_status.py run --background
    code=$?
    [ "$code" -eq 0 ] && exit 0
    sleep "$RETRY"
done

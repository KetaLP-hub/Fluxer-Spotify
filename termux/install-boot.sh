#!/data/data/com.termux/files/usr/bin/sh
# Autostart nach dem Booten einrichten (braucht die App "Termux:Boot", einmal oeffnen).
# Set up autostart after boot (needs the "Termux:Boot" app, open it once).
REPO="$(cd "$(dirname "$0")/.." && pwd)" || exit 1
BOOT="${HOME}/.termux/boot"
mkdir -p "$BOOT" || exit 1
cat > "$BOOT/fluxer-spotify" <<SCRIPT
#!/data/data/com.termux/files/usr/bin/sh
nohup sh "$REPO/termux/start.sh" >/dev/null 2>&1 &
SCRIPT
chmod +x "$BOOT/fluxer-spotify" "$REPO/termux/start.sh"
echo "Autostart eingerichtet / autostart installed: $BOOT/fluxer-spotify"
echo "Entfernen / remove: rm \"$BOOT/fluxer-spotify\""

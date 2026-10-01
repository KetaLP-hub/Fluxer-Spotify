# Spotify -> Fluxer

Zeigt, was du gerade auf Spotify hörst, als **benutzerdefinierten Status in deinem Fluxer-Profil** (z. B. "🎵 Song – Künstler"). Optional postet es zusätzlich eine Karte per Webhook in einen Channel, die sich live selbst aktualisiert.

Ein einziges Python-Script, keine Abhängigkeiten (nur Python 3.8+ ab python.org).

> **Hinweis:** Fluxer hat keine native Spotify-Integration. Dieses Tool setzt nur den **Text-Status**, mehr nicht.

## Einrichtung in 5 Schritten

1. **Spotify-App anlegen:** Auf https://developer.spotify.com/dashboard einloggen, "Create app". Als Redirect URI genau `http://127.0.0.1:8888/callback` eintragen und speichern. Die **Client ID** notieren.
2. **Fluxer-Token holen:** Fluxer im Browser öffnen, `F12` drücken, Reiter **Network** (Netzwerk). Einmal den Status ändern oder die Seite neu laden, eine Anfrage namens `settings` (URL endet auf `users/@me/settings`) anklicken, unter **Headers -> Request Headers** den Wert von **Authorization** kopieren.
3. **`.env` ausfüllen:** `.env.example` nach `.env` kopieren und `SPOTIFY_CLIENT_ID` und `FLUXER_TOKEN` eintragen (optional `FLUXER_WEBHOOK`).
4. **Einmalig anmelden:** `python spotify_status.py login` (oder `start.bat login`). Der Browser öffnet sich, bei Spotify zustimmen.
5. **Starten:** `start.bat` doppelklicken (oder `python spotify_status.py`). Mit `Strg+C` beenden, der Status wird dabei gelöscht.

## Probleme?

- **"INVALID_CLIENT: Invalid redirect URI"** bei Spotify: Die Redirect URI im Dashboard muss exakt `http://127.0.0.1:8888/callback` lauten (nicht `localhost`, kein Slash am Ende).
- **401** von Spotify: Neu anmelden mit `python spotify_status.py login`. **401** von Fluxer: Token ist abgelaufen oder falsch kopiert, Schritt 2 wiederholen.
- **403** von Fluxer: Der Server verweigert die Aktion (z. B. gesperrter Token oder Automatisierung nicht erlaubt). Neuen Token holen; hilft das nicht, nutze nur den Webhook.
- Nichts passiert: Läuft auf Spotify wirklich gerade ein Song (am besten in der Desktop- oder Handy-App)?

## Warnung

Die Nutzung eines **persönlichen Account-Tokens für Automatisierung kann gegen die Nutzungsbedingungen von Fluxer verstoßen** (Self-Bot). Benutzung auf eigenes Risiko. Der Token gibt vollen Zugriff auf deinen Account: **behandle ihn wie ein Passwort**, teile ihn nie, committe `.env` und `state.json` nie (sind in `.gitignore`). Wer nur den Webhook nutzt, braucht keinen Token.

---

## English

Mirrors your Spotify "now playing" into your Fluxer profile custom status, and optionally posts a self-updating embed via a Fluxer webhook. Single stdlib-only Python script, no dependencies. Fluxer has no native Spotify integration, so this only sets the text status.

**Setup:** (1) Create a Spotify app at developer.spotify.com/dashboard with redirect URI `http://127.0.0.1:8888/callback`. (2) Copy your Fluxer token: browser DevTools -> Network -> a `users/@me/settings` request -> `Authorization` header. (3) Copy `.env.example` to `.env` and fill it in. (4) Run `python spotify_status.py login` once. (5) Run `python spotify_status.py` (or double-click `start.bat`); Ctrl+C stops it and clears the status.

**Warning:** Using a personal account token for automation may violate Fluxer's Terms of Service. Use at your own risk and treat the token like a password.

Licence: MIT.

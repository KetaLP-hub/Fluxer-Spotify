# Spotify -> Fluxer

Zeigt, was du gerade auf Spotify hörst, als **benutzerdefinierten Status in deinem Fluxer-Profil** (z. B. "🎵 Song – Künstler"). Optional postet es zusätzlich eine Karte per Webhook in einen Channel, die sich live selbst aktualisiert.

Keine Abhängigkeiten (nur Python 3.10+ ab python.org, keine `pip install`-Pakete).

> **Hinweis:** Fluxer hat keine native Spotify-Integration. Dieses Tool setzt nur den **Text-Status**, mehr nicht.

## Einrichtung (3 Schritte)

1. **Spotify-App anlegen** (jede Person braucht ihre eigene, das ist von Spotify so gewollt): Auf https://developer.spotify.com/dashboard einloggen, "Create app". Als Redirect URI genau `http://127.0.0.1:8888/callback` eintragen und speichern. Die **Client ID** notieren und in `.env` eintragen (`.env.example` nach `.env` kopieren, Zeile `SPOTIFY_CLIENT_ID`).
2. **Einmal anmelden:**
   ```
   python spotify_status.py login          # Spotify (Browser öffnet sich)
   python spotify_status.py fluxer-login   # Fluxer: E-Mail + Passwort (+ 2FA-Code falls aktiv)
   ```
   Unter Windows geht auch `start.bat login` / `start.bat fluxer-login`.
3. **Starten:** `start.bat` doppelklicken (oder `python spotify_status.py`). Mit `Strg+C` beenden, der Status wird dabei gelöscht.

Kein DevTools, kein Token-Kopieren mehr.

### Was passiert mit deinem Passwort?

- Du gibst E-Mail und Passwort **nur in der Konsole** ein (unsichtbar, `getpass`). Es gibt bewusst **keine** Option, das Passwort per Flag, Umgebungsvariable oder Datei zu übergeben.
- Das Passwort wird **genau einmal** an die Fluxer-API (`https://api.fluxer.app/v1/auth/login`) gesendet und **nirgends gespeichert**, auch nicht im Log.
- Gespeichert wird nur der **Session-Token** in `state.json` (lokal, atomar geschrieben, unter Linux/macOS mit Rechten `0600`). Der Token erscheint in keiner Log-Zeile.
- Das Tool legt eine **eigene Sitzung** an. Du siehst sie in den Fluxer-Einstellungen und kannst sie dort jederzeit beenden. `logout` beendet sie ebenfalls.
- Python kann Strings nicht aktiv überschreiben; das Tool verwirft die Referenz sofort nach dem Login, der Prozess endet danach.
- Das Captcha beim Login (ALTCHA, eine reine Rechenaufgabe) löst das Tool automatisch.

### Weitere Befehle

| Befehl | Zweck |
|---|---|
| `status` / `doctor` | prüft Konfiguration, Spotify- und Fluxer-Login und gibt Hinweise in Klartext (zeigt nie Geheimnisse) |
| `logout` | löscht den Fluxer-Status, beendet die Fluxer-Sitzung (nur wenn sie von `fluxer-login` stammt) und löscht gespeicherte Tokens (`--keep-spotify` behält den Spotify-Login) |
| `fluxer-token` | Fallback: Token aus dem Browser einfügen (siehe unten) |
| `install-autostart` / `uninstall-autostart` | Windows: Start mit der Anmeldung (Startup-Ordner, kein Admin nötig, Log in `fluxer-spotify.log`) |
| `-v` / `--verbose` | ausführliches Log (ohne Geheimnisse) |

### Einstellungen

Reihenfolge: **Kommandozeilen-Flags > Umgebungsvariablen > `.env`**. Siehe `.env.example`.

- `--template` / `STATUS_TEMPLATE`: Text des Status, z. B. `🎵 {title} – {artist}` (Standard). Platzhalter: `{title}`, `{artist}`, `{album}`. Maximal 128 Zeichen.
- `--on-pause` / `ON_PAUSE`: `clear` (Standard, Status bei Pause löschen) oder `keep` (stehen lassen). Wenn gar nichts läuft, wird der Status immer gelöscht.
- `--webhook` / `FLUXER_WEBHOOK`: optionale Karte im Channel.
- `--interval` / `POLL_INTERVAL`: Abfrage in Sekunden (mindestens 2).

## Probleme?

Zuerst: `python spotify_status.py status`.

- **"INVALID_CLIENT: Invalid redirect URI"** bei Spotify: Die Redirect URI im Dashboard muss exakt `http://127.0.0.1:8888/callback` lauten (nicht `localhost`, kein Slash am Ende).
- **Spotify 401 / "Neu anmelden"**: `python spotify_status.py login`.
- **Fluxer 401**: Sitzung abgelaufen oder in den Einstellungen beendet: `python spotify_status.py fluxer-login`.
- **"E-Mail oder Passwort falsch"**: Tippfehler? Achtung, Fluxer erlaubt nur 5 Versuche pro 15 Minuten pro E-Mail.
- **Neue IP-Adresse**: Fluxer schickt eine Bestätigungs-Mail. Link öffnen, das Tool wartet bis zu 10 Minuten.
- **Account nur mit Passkey (WebAuthn) oder SSO**: Das geht in der Konsole nicht. Nutze den Fallback `fluxer-token`:
  1. Fluxer im Browser öffnen (eingeloggt), `F12`, Reiter **Console**.
  2. `copy(localStorage.getItem('token'))` eingeben (kopiert den Token in die Zwischenablage; laut Quellcode von Fluxer liegt er dort unter dem Schlüssel `token`).
  3. `python spotify_status.py fluxer-token` und mit Strg+V einfügen. Der Token wird geprüft und gespeichert.
  Dieser Token ist deine Browser-Sitzung: `logout` löscht ihn lokal, widerruft ihn aber **nicht**.
- **403 von Fluxer**: Der Server verweigert die Aktion (z. B. Account gesperrt oder Automatisierung nicht erlaubt).
- **Captcha-Fehler**: Der Server verlangt ein Captcha, das nicht ALTCHA ist: `fluxer-token` nutzen.
- Nichts passiert: Läuft auf Spotify wirklich gerade ein Song (am besten in der Desktop- oder Handy-App)?
- **Umlaute/Emoji als `?` in der Konsole**: nur Darstellung in alten Windows-Konsolen, der Status ist trotzdem korrekt.

## Warnung (Nutzungsbedingungen)

Das Automatisieren eines **persönlichen Accounts** (Self-Bot) **kann gegen die Nutzungsbedingungen von Fluxer verstoßen**. Das Tool meldet sich wie ein Client mit deinem Account an und ändert nur deinen Status, aber **Benutzung auf eigenes Risiko**. Wer nur den Webhook nutzen will, braucht keinen Login (`FLUXER_WEBHOOK` setzen, kein `fluxer-login`).

## SECURITY

- `state.json` und `.env` enthalten Geheimnisse (Tokens, Webhook-URL). Sie stehen in `.gitignore`, **nie committen oder teilen**. Wer den Session-Token hat, hat vollen Zugriff auf deinen Fluxer-Account, bis die Sitzung beendet wird (`logout` oder Fluxer-Einstellungen).
- Das Tool spricht nur mit `api.fluxer.app`, `accounts.spotify.com`, `api.spotify.com` und deinem Webhook. `FLUXER_API` muss `https://` nutzen (Ausnahme: localhost).
- Auf Windows setzt das Tool keine NTFS-Rechte; die Datei liegt in deinem Benutzerordner. Auf einem geteilten Rechner den Ordner entsprechend schützen.
- Sicherheitslücke gefunden? Bitte einen privaten Hinweis an die Maintainer statt eines öffentlichen Issues.

---

## English

Mirrors your Spotify "now playing" into your Fluxer profile custom status, and optionally posts a self-updating embed via a Fluxer webhook. Stdlib-only Python 3.10+, no dependencies. Fluxer has no native Spotify integration, so this only sets the text status.

**Setup**
1. Create your own Spotify app at developer.spotify.com/dashboard (redirect URI exactly `http://127.0.0.1:8888/callback`) and put its Client ID into `.env` as `SPOTIFY_CLIENT_ID` (copy `.env.example`). Every user needs their own app; that is a Spotify requirement.
2. `python spotify_status.py login` (Spotify, browser) and `python spotify_status.py fluxer-login` (Fluxer e-mail + password, plus your 2FA code if enabled).
3. `python spotify_status.py` (or `start.bat`). Ctrl+C stops it and clears the status.

**Your password:** typed into the console only (hidden), sent exactly once to the Fluxer API, never stored or logged. Only the session token is stored in `state.json` (atomic writes, mode 0600 on POSIX). The tool creates its own session, which you can end in Fluxer's settings or with `logout`. The login captcha (ALTCHA proof-of-work) is solved automatically. Passkey-only or SSO accounts cannot log in from a CLI: use `fluxer-token` (browser console: `copy(localStorage.getItem('token'))`).

**Commands:** `run` (default), `login`, `fluxer-login`, `fluxer-token`, `logout`, `status`/`doctor`, `install-autostart`, `uninstall-autostart`, plus `-v`. Config precedence: flags > environment > `.env`. Options: `--template "🎵 {title} – {artist}"`, `--on-pause clear|keep`, `--webhook`, `--interval`.

**Warning:** Automating a personal account may violate Fluxer's Terms of Service. Use at your own risk. Never commit or share `state.json` / `.env`.

Licence: MIT.

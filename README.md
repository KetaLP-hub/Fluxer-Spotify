# Spotify -> Fluxer

Zeigt, was du gerade auf Spotify hörst, als **benutzerdefinierten Status in deinem Fluxer-Profil** (z. B. "🎵 Song – Künstler"). Optional postet es zusätzlich eine Karte per Webhook in einen Channel, die sich live selbst aktualisiert.

Windows-Programm zum Doppelklicken, nichts zu installieren. Der Quellcode braucht nur Python 3.10+ (keine `pip install`-Pakete).

> **Hinweis:** Fluxer hat keine native Spotify-Integration. Dieses Tool setzt nur den **Text-Status**, mehr nicht.

## Einrichtung (Doppelklick, den Rest erledigt das Programm)

1. **`Fluxer-Spotify.exe` herunterladen** unter [Releases](https://github.com/KetaLP-hub/Fluxer-Spotify/releases) und doppelklicken.
2. **Fragen beantworten.** Beim ersten Start führt dich das Programm Schritt für Schritt durch alles, was noch fehlt, und überspringt, was schon erledigt ist:
   1. **Spotify Client ID:** Das Programm öffnet https://developer.spotify.com/dashboard. Dort "Create app" wählen, als Redirect URI genau `http://127.0.0.1:8888/callback` eintragen, die **Client ID** kopieren und im Fenster einfügen. Sie wird gespeichert.
   2. **Spotify-Login:** Der Browser öffnet sich, "Zustimmen" klicken.
   3. **Fluxer-Login:** E-Mail und Passwort (und 2FA-Code, falls aktiv). Geht das nicht (z. B. Passkey-Account), bietet das Programm an, stattdessen einen Token einzufügen.
   4. Zum Schluss sagt es **klar, dass es dauerhaft im Hintergrund weiterlaufen kann und wie man es beendet bzw. deinstalliert**, und fragt einmal, ob es **mit Windows starten** soll (j/n, startet dann unsichtbar) und ob es **jetzt das Fenster verstecken** und im Hintergrund weiterlaufen soll (j/n).
3. Danach läuft der Status. Im Vordergrund: Fenster offen lassen und mit `Strg+C` beenden, der Status wird dabei gelöscht.

Beim nächsten Start fragt das Programm nur noch nach, wenn ein Login abgelaufen ist. Alle Daten liegen in `%APPDATA%\spotify-fluxer` (u. a. `state.json`, `.env` optional). Bei einem Fehler bleibt das Fenster offen ("Drücke Enter"), damit du die Meldung lesen kannst.

**Jede Person braucht ihre eigene (kostenlose) Spotify-App.** Das ist von Spotify so gewollt: Eine App im Entwicklermodus darf nur 25 Nutzer freischalten, deshalb kann es keine gemeinsame App für alle geben.

### Hintergrundbetrieb (ohne sichtbares Fenster)

`Fluxer-Spotify.exe run --background` (Alias `--hidden`) läuft ohne Fenster: Die Konsole wird versteckt, das Log geht in eine Datei, es gibt nie eine Eingabeaufforderung. Ist die Einrichtung unvollständig oder ein Login abgelaufen, beendet es sich mit einem Log-Eintrag und zeigt **einmal** eine Windows-Meldung: dann das Programm normal (Doppelklick) starten, es fragt nur nach, was fehlt. Ist beim Windows-Start das Netzwerk noch nicht da, versucht es es einige Minuten lang erneut. Den Autostart-Eintrag (`install-autostart`, oder die Frage im Assistenten) startet immer diese unsichtbare Variante.

- **Beenden:** `Fluxer-Spotify.exe stop` (löscht vorher den Fluxer-Status) oder im Task-Manager den Prozess `Fluxer-Spotify.exe` beenden (das löscht den Status nicht; ein Neustart oder `logout` setzt ihn zurück). Es läuft immer nur **eine** Instanz; ein zweiter Start meldet das bzw. beendet sich still.
- **Log:** `%APPDATA%\spotify-fluxer\fluxer-spotify.log` (rotierend, max. ca. 1,5 MB), die letzten 50 Zeilen mit `Fluxer-Spotify.exe logs`. `status` zeigt, ob die Hintergrund-Instanz läuft.
- **Komplett entfernen:** `Fluxer-Spotify.exe uninstall` (nach Rückfrage: stoppt das Programm, entfernt den Autostart, meldet ab und löscht `state.json`, `.env` und Logs). Die exe selbst löschst du danach von Hand.
- **Ehrlicher Hinweis:** Ein unsichtbar laufendes Programm ist nur dann für die Person transparent, wenn sie es weiß. Deshalb sagt der Einrichtungs-Assistent ausdrücklich, dass das Programm im Hintergrund weiterläuft und wie man es beendet und deinstalliert. Installiere es nicht auf Rechnern anderer Personen ohne deren Wissen.
- Das Verstecken betrifft nur das eigene Fenster der exe; startest du es aus einer geöffneten Eingabeaufforderung, bleibt diese sichtbar (nur das Log geht in die Datei).

### Windows warnt vor der Datei (SmartScreen / Virenscanner)

Die exe ist **nicht code-signiert** (ein Zertifikat kostet Geld). Windows SmartScreen zeigt daher "Der Computer wurde durch Windows geschützt" ("Weitere Informationen" -> "Trotzdem ausführen"), und manche Virenscanner schlagen bei PyInstaller-Programmen fälschlich an (Fehlalarm). Prüfe die Datei mit der `.sha256` aus dem Release (`certutil -hashfile Fluxer-Spotify.exe SHA256`) oder baue sie selbst aus dem Quellcode (siehe unten). Wer der exe nicht traut, startet einfach `python spotify_status.py`.

Kein DevTools, kein Token-Kopieren, keine Umgebungsvariablen.

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
| `run --background` | unsichtbar im Hintergrund laufen (siehe oben) |
| `stop` / `logs` / `uninstall` | Hintergrund-Instanz beenden / letzte 50 Logzeilen / alles entfernen |
| `install-autostart` / `uninstall-autostart` | Windows: unsichtbarer Start mit der Anmeldung (Startup-Ordner, kein Admin nötig, Log in `fluxer-spotify.log`) |
| `-v` / `--verbose` | ausführliches Log (ohne Geheimnisse) |

### Einstellungen

Normalerweise nicht nötig. Reihenfolge: **Kommandozeilen-Flags > Umgebungsvariablen > `.env` (im Datenordner) > vom Programm gespeicherte Werte**. Siehe `.env.example`.

- `--template` / `STATUS_TEMPLATE`: Text des Status, z. B. `🎵 {title} – {artist}` (Standard). Platzhalter: `{title}`, `{artist}`, `{album}`. Maximal 128 Zeichen.
- `--on-pause` / `ON_PAUSE`: `clear` (Standard, Status bei Pause löschen) oder `keep` (stehen lassen). Wenn gar nichts läuft, wird der Status immer gelöscht.
- `--webhook` / `FLUXER_WEBHOOK`: optionale Karte im Channel.
- `--interval` / `POLL_INTERVAL`: Abfrage in Sekunden (mindestens 2).

## Probleme?

Zuerst: `Fluxer-Spotify.exe status` (bzw. `python spotify_status.py status`). Abgelaufene Logins erneuert das Programm beim nächsten Start von selbst.

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

## Für Entwickler: Quellcode und exe bauen

```
python spotify_status.py                     # Start aus dem Quellcode (Daten im Projektordner)
python -m unittest discover -s tests -t .    # Tests (nur Standardbibliothek)
pip install -r requirements-dev.txt          # PyInstaller, nur zum Bauen
build_exe.bat                                # erzeugt dist\Fluxer-Spotify.exe
```

Die Laufzeit nutzt ausschließlich die Standardbibliothek; PyInstaller wird nur zum Bauen gebraucht. Ein Tag `v*` (z. B. `git tag v2.1.0 && git push --tags`) startet `.github/workflows/release.yml`: Tests, exe bauen, Release mit exe und SHA256 anlegen. Als exe liegen die Daten in `%APPDATA%\spotify-fluxer`, aus dem Quellcode im Projektordner (überschreibbar mit `--data-dir` oder `FLUXER_SPOTIFY_HOME`).

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

**Setup (Windows):** download `Fluxer-Spotify.exe` from [Releases](https://github.com/KetaLP-hub/Fluxer-Spotify/releases) and double-click it. On first start it walks you through whatever is missing and skips what is done: (1) your Spotify Client ID (it opens the Spotify developer dashboard; create an app with redirect URI exactly `http://127.0.0.1:8888/callback`, paste the Client ID, it is saved), (2) Spotify login in the browser, (3) Fluxer login with e-mail + password (+ 2FA), with a token-paste fallback if that cannot work, (4) a one-time y/n question whether to start with Windows. The wizard states clearly that the program can keep running in the background and how to stop or uninstall it, then asks (y/n) whether to hide the window and continue in the background. Then the status loop runs; in a visible window Ctrl+C stops it and clears the status. Expired logins are renewed on the next start. Data lives in `%APPDATA%\spotify-fluxer`; on errors the window stays open until you press Enter.

**Each user needs their own free Spotify developer app.** That is how Spotify works: apps in development mode are limited to 25 users, so a shared app for everyone is not possible.

**Background mode:** `Fluxer-Spotify.exe run --background` (alias `--hidden`) runs with no window: console hidden, logging to `%APPDATA%\spotify-fluxer\fluxer-spotify.log` (rotating; `Fluxer-Spotify.exe logs` prints the last 50 lines), never prompts. If setup is incomplete or a login expired it exits with a log entry and shows a one-time Windows message asking you to start the program normally. Autostart always launches this hidden variant. Only one instance runs at a time. Stop it with `Fluxer-Spotify.exe stop` (clears the Fluxer status first) or end the `Fluxer-Spotify.exe` process in Task Manager (does not clear the status). `status` shows whether it runs. `Fluxer-Spotify.exe uninstall` (asks first) stops it, removes autostart, logs out and deletes `state.json`, `.env` and logs; delete the exe yourself. Running hidden is only transparent to the user if they were told, which is why the first-run wizard says explicitly that the program keeps running in the background and how to stop and uninstall it. Do not install it on someone else's machine without their knowledge.

**SmartScreen / antivirus:** the exe is **unsigned**. Windows SmartScreen will warn ("More info" -> "Run anyway") and some antivirus tools flag PyInstaller executables as false positives. Verify the SHA256 published with each release, or build it yourself (`pip install -r requirements-dev.txt`, `build_exe.bat`), or run from source with `python spotify_status.py`.

**Your password:** typed into the console only (hidden), sent exactly once to the Fluxer API, never stored or logged. Only the session token is stored in `state.json` (atomic writes, mode 0600 on POSIX). The tool creates its own session, which you can end in Fluxer's settings or with `logout`. The login captcha (ALTCHA proof-of-work) is solved automatically. Passkey-only or SSO accounts cannot log in from a CLI: use `fluxer-token` (browser console: `copy(localStorage.getItem('token'))`).

**Commands:** `run` (default; `--background`/`--hidden`), `login`, `fluxer-login`, `fluxer-token`, `logout`, `status`/`doctor`, `stop`, `logs`, `uninstall`, `install-autostart`, `uninstall-autostart`, plus `-v`. Config precedence: flags > environment > `.env` > values stored by the wizard. Options: `--template "🎵 {title} – {artist}"`, `--on-pause clear|keep`, `--webhook`, `--interval`.

**Warning:** Automating a personal account may violate Fluxer's Terms of Service. Use at your own risk. Never commit or share `state.json` / `.env`.

Licence: MIT.

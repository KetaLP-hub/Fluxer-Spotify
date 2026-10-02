[English](README.md) | Deutsch

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

### Android (Termux): läuft auch bei ausgeschaltetem PC

Der Status wird nur aktualisiert, solange das Programm irgendwo läuft. Damit er auch bei ausgeschaltetem PC weiterläuft, lass es auf deinem **Handy** laufen (kein Server nötig). Das nutzt den Quellcode (die exe gibt es nur für Windows) und die Python-Standardbibliothek, es gibt nichts per `pip` zu installieren.

1. Installiere **Termux** und **Termux:Boot** über [F-Droid](https://f-droid.org/packages/com.termux/) (die Play-Store-Version von Termux ist veraltet).
2. In Termux: `pkg update && pkg install python git`, dann `git clone https://github.com/KetaLP-hub/Fluxer-Spotify && cd Fluxer-Spotify`.
3. **Melde dich auf dem Handy selbst an.** Ein Login vom PC lässt sich nicht mitnehmen: Unter Windows sind die Tokens für deinen Windows-Benutzer verschlüsselt.
   - `export BROWSER=termux-open-url` (damit sich der Spotify-Login im Browser des Handys öffnet), dann `python spotify_status.py`. Die Einrichtung fragt nach der Spotify Client ID, dann nach Spotify (der Browser springt zurück auf `http://127.0.0.1:8888/callback`, das ist dieses Handy, also klappt es) und nach Fluxer-E-Mail und -Passwort. Optional: `python spotify_status.py github-login`.
   - Prüfen mit `python spotify_status.py doctor`.
4. Ausprobieren: `sh termux/start.sh` (beenden mit Strg+C). Das Skript hält die CPU wach (`termux-wake-lock`, dafür erscheint eine Termux-Benachrichtigung) und startet das Programm im Hintergrundmodus: Es fragt nie etwas, schreibt `fluxer-spotify.log` und versucht es nach einem Fehler wie abgelaufenem Login oder fehlendem Netz alle 5 Minuten erneut.
5. Start nach einem Neustart: `sh termux/install-boot.sh`, danach die App **Termux:Boot** einmal öffnen.
6. **Schalte den Windows-Autostart ab** (`Fluxer-Spotify.exe uninstall-autostart`) oder beende die Instanz am PC. Zwei Instanzen würden sich gegenseitig den Status überschreiben.

Beenden: `python spotify_status.py stop` (löscht den Status). Log: `python spotify_status.py logs`. Aktualisieren: `git pull`.

Gut zu wissen:
- **Android kann Termux beenden, um Akku zu sparen.** Nimm Termux (und Termux:Boot) in den Android-Einstellungen von der Akku-Optimierung aus. Ab Android 12 kann das System außerdem Hintergrundprozesse von Apps wie Termux beenden (der „Phantom Process Killer“); hört der Status nach einer Weile auf, suche nach diesem Begriff für deine Android-Version. Wie streng das ist, hängt vom Hersteller deines Handys ab.
- Android hat kein DPAPI: Die Tokens in `state.json` sind dort **nicht verschlüsselt**, nur durch Dateirechte im privaten Ordner der App geschützt. Kopiere diesen Ordner nicht herum.
- Ist die Einrichtung unvollständig oder ein Login abgelaufen, steht im Log „Bitte Fluxer-Spotify.exe normal starten (Doppelklick)“. Auf dem Handy heißt das: `python spotify_status.py` in Termux ausführen.
- Das wurde ohne Test auf einem echten Android-Gerät geschrieben. Die Logik der Skripte ist unter Linux getestet, die Android-Besonderheiten (Akku, Termux:Boot) nicht.

### Windows warnt vor der Datei (SmartScreen / Virenscanner)

Die exe ist **nicht code-signiert** (ein Zertifikat kostet Geld). Windows SmartScreen zeigt daher "Der Computer wurde durch Windows geschützt" ("Weitere Informationen" -> "Trotzdem ausführen"), und manche Virenscanner schlagen bei PyInstaller-Programmen fälschlich an (Fehlalarm). Prüfe die Datei mit der `.sha256` aus dem Release (`certutil -hashfile Fluxer-Spotify.exe SHA256`) oder baue sie selbst aus dem Quellcode (siehe unten). Wer der exe nicht traut, startet einfach `python spotify_status.py`.

Kein DevTools, kein Token-Kopieren, keine Umgebungsvariablen.

### Was passiert mit deinem Passwort?

- Du gibst E-Mail und Passwort **nur in der Konsole** ein (unsichtbar, `getpass`). Es gibt bewusst **keine** Option, das Passwort per Flag, Umgebungsvariable oder Datei zu übergeben.
- Das Passwort wird **genau einmal** an die Fluxer-API (`https://api.fluxer.app/v1/auth/login`) gesendet und **nirgends gespeichert**, auch nicht im Log.
- Gespeichert wird nur der **Session-Token** in `state.json` (lokal, atomar geschrieben, unter Linux/macOS mit Rechten `0600`). Der Token erscheint in keiner Log-Zeile.
- **Unter Windows sind die Tokens in `state.json` mit DPAPI verschlüsselt** (in Windows eingebaut, kein Zusatzpaket). Sie lassen sich nur von deinem Windows-Benutzer auf diesem PC entschlüsseln, eine kopierte `state.json` nützt anderen nichts. Eine ältere Klartext-Datei wird beim nächsten Start automatisch umgestellt. Lässt sich ein Token nicht entschlüsseln (anderer Benutzer oder PC), gilt es als abgemeldet und du meldest dich neu an. `doctor` zeigt, ob die Verschlüsselung aktiv ist. Unter Linux/macOS gibt es noch kein solches Verfahren, dort bleiben die Tokens im Klartext und nur durch Dateirechte geschützt.
- Das Tool legt eine **eigene Sitzung** an. Du siehst sie in den Fluxer-Einstellungen und kannst sie dort jederzeit beenden. `logout` beendet sie ebenfalls.
- Python kann Strings nicht aktiv überschreiben; das Tool verwirft die Referenz sofort nach dem Login, der Prozess endet danach.
- Das Captcha beim Login (ALTCHA, eine reine Rechenaufgabe) löst das Tool automatisch.

### Weitere Befehle

| Befehl | Zweck |
|---|---|
| `status` / `doctor` | prüft Konfiguration, Spotify- und Fluxer-Login und gibt Hinweise in Klartext (zeigt nie Geheimnisse) |
| `logout` | löscht den Fluxer-Status, beendet die Fluxer-Sitzung (nur wenn sie von `fluxer-login` stammt) und löscht gespeicherte Tokens (`--keep-spotify` behält den Spotify-Login) |
| `fluxer-token` | Fallback: Token aus dem Browser einfügen (siehe unten) |
| `github-login` | optional: GitHub mit einem Nur-Lese-Token verbinden (ergänzt die GitHub-Statuszeilen, siehe unten) |
| `run --background` | unsichtbar im Hintergrund laufen (siehe oben) |
| `stop` / `logs` / `uninstall` | Hintergrund-Instanz beenden / letzte 50 Logzeilen / alles entfernen |
| `install-autostart` / `uninstall-autostart` | Windows: unsichtbarer Start mit der Anmeldung (Startup-Ordner, kein Admin nötig, Log in `fluxer-spotify.log`) |
| `-v` / `--verbose` | ausführliches Log (ohne Geheimnisse) |

### Einstellungen

Normalerweise nicht nötig. Reihenfolge: **Kommandozeilen-Flags > Umgebungsvariablen > `.env` (im Datenordner) > vom Programm gespeicherte Werte**. Siehe `.env.example`.

- `--template` / `STATUS_TEMPLATE`: Text des Status, z. B. `🎵 {title} – {artist}` (Standard). Platzhalter: `{title}`, `{artist}`, `{album}`. Maximal 128 Zeichen.
- `--on-pause` / `ON_PAUSE`: `clear` (Standard, Status bei Pause löschen), `keep` (stehen lassen) oder `stats` (bei Pause nur die Statistik-Zeilen `top_artist`, `listening_today` und die GitHub-Zeilen rotieren lassen; ist keine davon aktiv, wird gelöscht).
- `--on-idle` / `ON_IDLE`: was passiert, wenn gar nichts läuft (kein Titel, nicht einmal pausiert). `clear` (Standard) löscht den Status. `lines` rotiert weiter durch alle eingestellten Zeilen, die keinen Titel brauchen (`top_artist`, `listening_today`, die GitHub-Zeilen und eigene Zeilen, die nur diese Werte nutzen), damit dein GitHub-Status auch ohne Musik sichtbar bleibt.
- `--lang` / `LANGUAGE`: Sprache aller Programmtexte: `auto` (Standard: folgt der Anzeigesprache des Betriebssystems; beginnt sie mit `de`, wird Deutsch genommen, sonst Englisch), `de` oder `en`. Beim ersten interaktiven Start wird einmal gefragt (Enter übernimmt die erkannte Sprache) und die Antwort gespeichert; wer die Option setzt, wird nicht gefragt. Sie betrifft Meldungen, Fehler, den Einrichtungsassistenten, `doctor`, Tipps, Hintergrund-Hinweise, die Standardtexte der Statuszeilen und die Webhook-Karte. Eigene `STATUS_TEMPLATE`- bzw. `STATUS_LINES`-Texte werden nie übersetzt. Unbekannte Werte brechen den Start mit einer Fehlermeldung ab. (Ein POSIX-`LANGUAGE=de_DE:en` in der echten Umgebung wird ignoriert; es zählt nur `auto`, `de` oder `en`.) Die versteckte Hintergrund-Kopie übernimmt die Einstellung.
- `--lines` / `STATUS_LINES`: die rotierenden Statuszeilen in der gewünschten Reihenfolge (Standard `now,playlist,top_artist,listening_today`). Siehe unten.
- `--rotate` / `ROTATE_SECONDS`: Sekunden pro Zeile (Standard 30, **Minimum 15**; kleinere Werte werden mit einer Warnung auf 15 gesetzt, damit Fluxer nicht zugespammt wird).
- `--no-rotate` / `NO_ROTATE=1`: keine Rotation, es wird nur die erste Zeile gezeigt (wie vor dieser Funktion).

### Rotierende Statuszeilen

Während ein Titel läuft, wechselt der Status reihum zwischen diesen Zeilen:

| Name | Beispiel | Quelle |
|---|---|---|
| `now` | `🎵 Titel – Artist` | aktueller Titel (Text über `--template`) |
| `playlist` | `💿 aus "Playlist-Name"` | Playlist oder Album, aus dem gerade abgespielt wird (englisch: `💿 from "…"`) |
| `top_artist` | `🏆 Top-Artist diese Woche: Muse` | deine Top-Artists (`short_term`, ca. 4 Wochen laut Spotify), höchstens stündlich neu geholt |
| `listening_today` | `🎧 heute 1 h 30 min gehört` | aus „zuletzt gespielt“, höchstens alle 5 Minuten neu geholt |

(Deutsche Texte gezeigt. Mit `LANGUAGE=en` lauten sie `💿 from "…"`, `🏆 Top artist this week: …` und `🎧 1 h 30 min listened today`. Ein Teil mit null entfällt: `🎧 heute 25 min gehört`, `🎧 heute 2 h gehört`.)

- Zeilen ohne Daten werden übersprungen, nie mit leeren Platzhaltern angezeigt (z. B. `playlist` bei Podcasts, Liked Songs oder Künstler-Radio). Bleibt nur eine Zeile übrig, gibt es keine Rotation.
- Bei einem Titelwechsel (und bei Play/Pause) beginnt die Rotation neu mit der `now`-Zeile. Es wird nur dann an Fluxer gesendet, wenn sich der Text wirklich ändert. Bei Fehlern oder Rate-Limits (Retry-After) pausiert das Programm nur die Status-Updates, es stürzt nicht ab.
- `playlist`: Der Playlist-Name wird einmal pro Playlist abgefragt. Private oder von Spotify generierte Playlists (403/404) liefern keinen Namen; dann steht der Album-Name da. Bei Alben wird der Album-Name ohne Anfrage genommen.
- **Grenze von `listening_today`:** Die Spotify-API liefert nur die letzten 50 Wiedergaben. Wer heute mehr gehört hat, sieht deshalb nur einen Mindestwert („Untergrenze“). „Heute“ ist der lokale Kalendertag deines Rechners (ab 00:00 Uhr). Übersprungene Titel werden nur mit der Zeit gezählt, die sie tatsächlich liefen (grobe Schätzung aus den Abständen). Unter einer Minute wird die Zeile ausgelassen.
- Eigene Zeilen: In `STATUS_LINES` kannst du statt eines Namens einen Text mit Platzhaltern angeben: `{title}` `{artist}` `{album}` `{playlist}` `{top_artist}` `{hours}` `{minutes}` sowie die GitHub-Werte `{gh_repo}` `{gh_ago}` `{gh_commits}` `{gh_prs}` `{gh_reviews}` `{gh_issues}` `{gh_streak}` `{gh_stars}` `{gh_followers}`. Fehlt ein Wert, wird die Zeile übersprungen. Namen trennst du mit Komma; enthält eine eigene Zeile selbst ein Komma, trenne alles mit `|`.
- Jede Zeile wird auf 128 Zeichen gekürzt (mit `…` am Ende, das Emoji am Anfang bleibt).

### GitHub-Statuszeilen (optional)

`python spotify_status.py github-login` (bzw. `Fluxer-Spotify.exe github-login`) verbindet GitHub mit einem **Nur-Lese-Token** (die Eingabe ist unsichtbar; unter Windows wird der Token wie die anderen verschlüsselt gespeichert). Erstelle auf <https://github.com/settings/personal-access-tokens/new> einen *Fine-grained token*: „Public repositories“ reicht für öffentliche Daten; für Zähler aus privaten Repos (offene PRs, Reviews, Issues) wähle „All repositories“ mit **Pull requests: Read** und **Issues: Read**. Gib ihm nie Schreibrechte.

Nach dem Verbinden laufen diese Zeilen in der Rotation mit (außer du hast `STATUS_LINES` selbst gesetzt, dann ergänzt du die Namen unten von Hand). Spotify bleibt Pflicht, GitHub ist eine zusätzliche Quelle. Mit `ON_IDLE=lines` bleiben sie auch ohne Musik sichtbar.

| Name | Beispiel | Bedeutung |
|---|---|---|
| `gh_push` | `💻 zuletzt gepusht: du/projekt (vor 2 h)` | dein zuletzt gepushtes **öffentliches** Repo (ein privater Repo-Name wird nie gezeigt) |
| `gh_commits` | `💻 heute 5 Beiträge auf GitHub` | heutige Beiträge aus deinem Contribution-Kalender (Commits, Issues, PRs, Reviews) |
| `gh_prs` | `🔀 2 offene Pull Requests` | deine offenen Pull Requests |
| `gh_reviews` | `👀 1 Review angefragt` | offene Pull Requests, die auf dein Review warten |
| `gh_issues` | `📌 3 Issues zugewiesen` | offene Issues, die dir zugewiesen sind |
| `gh_streak` | `🔥 5 Tage in Folge aktiv` | aufeinanderfolgende Tage mit Beiträgen (ein Tag ohne bisherigen Beitrag unterbricht die Serie erst, wenn er vorbei ist) |
| `gh_stars` | `⭐ 13 Sterne auf GitHub` | Sterne auf deinen eigenen Repos (die 100 meistbesternten: darüber hinaus ein Mindestwert) |
| `gh_followers` | `👥 42 Follower` | deine Follower |

Beim Verbinden kommen `gh_push gh_commits gh_prs gh_reviews gh_issues gh_streak` dazu; `gh_stars` und `gh_followers` musst du selbst eintragen. Zähler mit null werden ausgeblendet („0 offene Pull Requests“ ist Rauschen), ebenso eine Serie unter 2 Tagen. Alles kommt aus einer einzigen GraphQL-Abfrage, 5 Minuten zwischengespeichert. Ist GitHub nicht erreichbar, im Rate-Limit oder der Token widerrufen, verschwinden nur die GitHub-Zeilen; der Spotify-Status läuft weiter (`doctor` sagt, was los ist). `logout` löscht den gespeicherten Token lokal; zum Widerrufen löschst du ihn auf <https://github.com/settings/personal-access-tokens>. Die Benachrichtigungs-API wird nicht genutzt (Fine-grained Tokens haben darauf keinen Zugriff).

Beispiel `.env`:

```
STATUS_LINES=now,playlist,top_artist,listening_today
ROTATE_SECONDS=30
ON_PAUSE=stats
ON_IDLE=lines
# oder eigene Zeilen:
# STATUS_LINES=now|🔥 {top_artist} läuft bei mir|⏱ {hours} h {minutes} min heute
# Rotation aus:
# NO_ROTATE=1
# Sprache: auto (Standard), de oder en
LANGUAGE=de
```

`doctor` zeigt die aktiven Zeilen und das Intervall an.
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

- `state.json` und `.env` enthalten Geheimnisse (Tokens, Webhook-URL). Sie stehen in `.gitignore`, **nie committen oder teilen**. Wer den Session-Token hat, hat vollen Zugriff auf deinen Fluxer-Account, bis die Sitzung beendet wird (`logout` oder Fluxer-Einstellungen). Unter Windows sind die Tokens in `state.json` verschlüsselt, die Webhook-URL und `.env` aber nicht.
- Das Tool spricht nur mit `api.fluxer.app`, `accounts.spotify.com`, `api.spotify.com` und deinem Webhook. `FLUXER_API` muss `https://` nutzen (Ausnahme: localhost).
- Auf Windows setzt das Tool keine NTFS-Rechte; die Datei liegt in deinem Benutzerordner. Auf einem geteilten Rechner den Ordner entsprechend schützen.
- Sicherheitslücke gefunden? Bitte einen privaten Hinweis an die Maintainer statt eines öffentlichen Issues.

## Mitwirken und Lizenz

Siehe [CONTRIBUTING.md](CONTRIBUTING.md). Lizenz: MIT ([LICENSE](LICENSE)).

English version: [README.md](README.md)

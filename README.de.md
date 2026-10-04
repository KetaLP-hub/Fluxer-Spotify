[English](README.md) | Deutsch

# Spotify -> Fluxer

Zeigt, was du gerade auf Spotify hörst, als **benutzerdefinierten Status in deinem Fluxer-Profil** (z. B. "🎵 Song – Künstler"). Optional postet es zusätzlich eine Karte per Webhook in einen Channel, die sich live selbst aktualisiert.

Windows-Programm zum Doppelklicken, nichts zu installieren. Der Quellcode braucht nur Python 3.10+ (keine `pip install`-Pakete).

> **Hinweis:** Fluxer hat keine native Spotify-Integration. Dieses Tool setzt nur den **Text-Status**, mehr nicht.

## Einrichtung (einfach doppelklicken)

1. **`Fluxer-Spotify.exe` herunterladen** unter [Releases](https://github.com/KetaLP-hub/Fluxer-Spotify/releases), an einen festen Ort legen (zum Beispiel `C:\Programme\Fluxer-Spotify\`) und doppelklicken. Es öffnet sich ein Fenster: **der Launcher**. Ein Konsolenfenster gibt es nicht.
2. **Die Schritte durchklicken.** Der große Knopf zeigt immer, was als Nächstes dran ist:
   1. **Spotify verbinden.** Einmalig brauchst du eine kostenlose Spotify-App (jede Person braucht ihre eigene, siehe unten). Der Launcher öffnet das Dashboard, zeigt die genaue Redirect-URI `http://127.0.0.1:8888/callback` mit einem *Kopieren*-Knopf und fragt nach der Client ID. Danach öffnet sich dein Browser: auf „Zustimmen“ klicken.
   2. **Fluxer verbinden.** E-Mail und Passwort (und der 2FA-Code, falls du einen nutzt). Konto mit Passkey/SSO: „Token einfügen …“.
   3. **GitHub verbinden** (optional, empfohlen). „Token-Seite öffnen“ öffnet GitHub mit Name, Laufzeit und den beiden **reinen Lese-Rechten** schon ausgefüllt. Auf „Generate token“ klicken, kopieren, im Launcher einfügen. „GitHub überspringen“ geht auch.
   4. **Starten.** Ein Klick startet das Programm unsichtbar im Hintergrund. Danach bietet der Launcher **„Mit Windows starten“** an – so läuft es rund um die Uhr, auch nach einem Neustart, bis du es stoppst.
3. **Fertig.** Fenster schließen; das Programm läuft weiter. Doppelklicke die Exe später wieder, um den Zustand zu sehen, es zu **stoppen**, die Anzeige zu ändern (Tab „Anzeige“), etwas neu zu verbinden, die Verbindungen zu prüfen, das Log zu lesen oder zu deinstallieren.

Was der Status zeigt, sobald alles verbunden ist: aktueller Titel, Playlist, Top-Artist, Hörzeit heute und die GitHub-Zeilen (letzter Push, Beiträge heute, offene Pull Requests, angefragte Reviews, zugewiesene Issues, Serie). Im Tab „Anzeige“ schaltest du jede Zeile an oder aus und nimmst auch Sterne und Follower dazu. Der erste Start aus dem Launcher schaltet einmalig **„Auch zeigen, wenn nichts spielt“**, **„Auch bei Pause zeigen“** und **„Status läuft von selbst ab“** ein (alles änderbar).

**Update von 2.2 oder älter:** Deine Anmeldungen bleiben erhalten (derselbe Datenordner). Starte einfach die neue Exe. Der Launcher erkennt einen alten Autostart-Eintrag und bietet „Autostart auf diese Exe aktualisieren“ an.

**Jede Person braucht ihre eigene (kostenlose) Spotify-App.** Das ist von Spotify so gewollt: Eine App im Entwicklungsmodus darf nur 25 Nutzer zulassen, eine gemeinsame App für alle geht daher nicht.

Lieber im Terminal (oder aus dem Quellcode)? `python spotify_status.py` startet weiterhin die klassische Frage-und-Antwort-Einrichtung in der Konsole, `python spotify_status.py gui` öffnet den Launcher. Alle Befehle unten funktionieren auch mit der Exe (`Fluxer-Spotify.exe stop`, `status`, `logs` … schreiben in das Terminal, aus dem du sie startest).

### Hintergrundbetrieb (ohne sichtbares Fenster)

`Fluxer-Spotify.exe run --background` (Alias `--hidden`) läuft ohne Fenster: Die Konsole wird versteckt, das Log geht in eine Datei, es gibt nie eine Eingabeaufforderung. Ist die Einrichtung unvollständig oder ein Login abgelaufen, beendet es sich mit einem Log-Eintrag und zeigt **einmal** eine Windows-Meldung: dann das Programm normal (Doppelklick) starten, es fragt nur nach, was fehlt. Ist beim Windows-Start das Netzwerk noch nicht da, versucht es es einige Minuten lang erneut. Den Autostart-Eintrag (`install-autostart`, oder die Frage im Assistenten) startet immer diese unsichtbare Variante.

- **Beenden:** `Fluxer-Spotify.exe stop` (löscht vorher den Fluxer-Status) oder im Task-Manager den Prozess `Fluxer-Spotify.exe` beenden (das löscht den Status nicht; ein Neustart oder `logout` setzt ihn zurück). Es läuft immer nur **eine** Instanz; ein zweiter Start meldet das bzw. beendet sich still.
- **Log:** `%APPDATA%\spotify-fluxer\fluxer-spotify.log` (rotierend, max. ca. 1,5 MB), die letzten 50 Zeilen mit `Fluxer-Spotify.exe logs`. `status` zeigt, ob die Hintergrund-Instanz läuft.
- **Komplett entfernen:** `Fluxer-Spotify.exe uninstall` (nach Rückfrage: stoppt das Programm, entfernt den Autostart, meldet ab und löscht `state.json`, `.env` und Logs). Die exe selbst löschst du danach von Hand.
- **Ehrlicher Hinweis:** Ein unsichtbar laufendes Programm ist nur dann für die Person transparent, wenn sie es weiß. Deshalb sagt der Einrichtungs-Assistent ausdrücklich, dass das Programm im Hintergrund weiterläuft und wie man es beendet und deinstalliert. Installiere es nicht auf Rechnern anderer Personen ohne deren Wissen.
- Das Verstecken betrifft nur das eigene Fenster der exe; startest du es aus einer geöffneten Eingabeaufforderung, bleibt diese sichtbar (nur das Log geht in die Datei).
- **Launcher:** Der *Starten/Stoppen*-Knopf und der Schalter *Mit Windows starten* tun dasselbe wie `run --background`, `stop` und `install-autostart`.
- **Der Autostart** ist ein einzelner Wert im *Run*-Schlüssel deines Benutzers (`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`), sichtbar und schaltbar im Task-Manager unter „Autostart“. Ältere Versionen legten eine versteckte VBScript-Datei in den Startup-Ordner; sie wird beim Einrichten des neuen Eintrags automatisch entfernt. (Versteckte Skript-Starter sind genau das, was Virenscanner-Heuristiken melden, und Windows schafft VBScript ab.)
- **Läuft weiter:** Im Hintergrundbetrieb beendet ein unerwarteter Fehler das Programm nicht; er wird protokolliert und mit wachsender Pause (15 s bis 5 min) erneut versucht. Nur was dich braucht (eine Anmeldung, die nicht mehr funktioniert) hält es an – der Launcher zeigt dann, was zu tun ist.
- **Räumt selbst auf:** `STATUS_TTL` (im Launcher „Status läuft von selbst ab“) lässt Fluxer den Status von allein löschen, wenn das Programm es nicht kann, z. B. weil der PC ausgeschaltet wurde. Das Programm erneuert ihn nach je einem Drittel der Zeit. Voraussetzung: Fluxer akzeptiert `expires_at`; antwortet es mit HTTP 400, schaltet sich die Option selbst ab.
- `FLUXER_SPOTIFY_NO_POPUP=1` unterdrückt das einmalige Windows-Hinweisfenster (Automatisierung); der Launcher zeigt denselben Hinweis in seinem Fenster.

### Android (Termux): läuft auch bei ausgeschaltetem PC

Der Status wird nur aktualisiert, solange das Programm irgendwo läuft. Damit er auch bei ausgeschaltetem PC weiterläuft, lass es auf deinem **Handy** laufen (kein Server nötig). Das nutzt den Quellcode (die exe gibt es nur für Windows) und die Python-Standardbibliothek, es gibt nichts per `pip` zu installieren.

1. Installiere **Termux** und **Termux:Boot** über [F-Droid](https://f-droid.org/packages/com.termux/) (die Play-Store-Version von Termux ist veraltet).
2. In Termux: `pkg update && pkg install python git`, dann `git clone https://github.com/KetaLP-hub/Fluxer-Spotify && cd Fluxer-Spotify`.
3. Führe **`sh termux/setup.sh`** aus. Das erledigt alles in einem Rutsch:
   - **Anmeldung auf dem Handy selbst.** Ein Login vom PC lässt sich nicht mitnehmen: Unter Windows sind die Tokens für deinen Windows-Benutzer verschlüsselt. Der Spotify-Login öffnet den Browser deines Handys und springt zurück auf `http://127.0.0.1:8888/callback`, das ist dieses Handy, also klappt es. Du wirst nach der Spotify Client ID gefragt, dann nach Spotify, dann nach Fluxer-E-Mail und -Passwort. Sobald es läuft und dein Status stimmt, drückst du **Strg+C**.
   - Danach prüft es die Anmeldung (`doctor`), richtet den Autostart nach einem Neustart ein (öffne die App **Termux:Boot** einmal) und **startet den Status sofort im Hintergrund**.
   - Optional danach: `python spotify_status.py github-login`.
4. Was dahinter steckt: `sh termux/start.sh` hält die CPU wach (`termux-wake-lock`, dafür erscheint eine Termux-Benachrichtigung) und startet das Programm im Hintergrundmodus: Es fragt nie etwas, schreibt `fluxer-spotify.log` und versucht es nach einem Fehler wie abgelaufenem Login oder fehlendem Netz alle 5 Minuten erneut. `sh termux/install-boot.sh` richtet nur den Autostart ein. Beides kannst du statt `setup.sh` auch von Hand ausführen, sobald du dich mit `python spotify_status.py` angemeldet hast.
5. **Schalte den Windows-Autostart ab** (`Fluxer-Spotify.exe uninstall-autostart`) oder beende die Instanz am PC. Zwei Instanzen würden sich gegenseitig den Status überschreiben.

Beenden: `python spotify_status.py stop` (löscht den Status). Log: `python spotify_status.py logs`. Aktualisieren: `git pull`.

Gut zu wissen:
- **Android kann Termux beenden, um Akku zu sparen.** Nimm Termux (und Termux:Boot) in den Android-Einstellungen von der Akku-Optimierung aus. Ab Android 12 kann das System außerdem Hintergrundprozesse von Apps wie Termux beenden (der „Phantom Process Killer“); hört der Status nach einer Weile auf, suche nach diesem Begriff für deine Android-Version. Wie streng das ist, hängt vom Hersteller deines Handys ab.
- Android hat kein DPAPI: Die Tokens in `state.json` sind dort **nicht verschlüsselt**, nur durch Dateirechte im privaten Ordner der App geschützt. Kopiere diesen Ordner nicht herum.
- Ist die Einrichtung unvollständig oder ein Login abgelaufen, steht im Log „Bitte Fluxer-Spotify.exe normal starten (Doppelklick)“. Auf dem Handy heißt das: `python spotify_status.py` in Termux ausführen.
- Das wurde ohne Test auf einem echten Android-Gerät geschrieben. Die Logik der Skripte ist unter Linux getestet, die Android-Besonderheiten (Akku, Termux:Boot) nicht.

### Windows warnt vor der Datei (SmartScreen / Virenscanner)

**Kurz:** Ein heruntergeladenes Programm ohne Code-Signatur löst immer SmartScreen aus („Der PC wurde durch Windows geschützt“ -> „Weitere Informationen“ -> „Trotzdem ausführen“). Das kann kein Programm selbst abschalten; nur ein Zertifikat einer vertrauenswürdigen Stelle (oder aufgebauter Ruf) hilft. In **[SIGNING.md](SIGNING.md)** steht, wie du eins bekommst (für Open-Source-Projekte kostenlos über die SignPath Foundation) und wie der Release-Workflow die Exe automatisch signiert, sobald die zwei Secrets gesetzt sind.

Was das Projekt tut, damit es möglichst leise bleibt:
- **Kein Packer** (`--noupx`), saubere Versionsinfo und Icon, `asInvoker` (fragt nie nach Admin-Rechten).
- **Keine versteckten Skript-Starter**: Der Autostart ist ein normaler Run-Key-Eintrag, kein VBScript.
- **Fenster-Programm** statt einer Konsole, die beim Anmelden aufblitzt.
- Zu jedem Release eine `.sha256` und ein Rauchtest im Release-Workflow.

Ohne Zertifikat kannst du sie trotzdem sicher starten: Hash prüfen (`certutil -hashfile Fluxer-Spotify.exe SHA256`), die Exe selbst bauen (eine selbst gebaute Datei hat keine Markierung „aus dem Internet“, SmartScreen fragt dann nicht) oder einfach `python spotify_status.py` benutzen. Setzt dein Virenscanner die Exe in Quarantäne (Fehlalarm bei einem PyInstaller-Programm), stelle sie wieder her und melde sie dem Hersteller als Fehlalarm.

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

**Im Launcher:** Übersicht > GitHub > Verbinden (öffnet die Token-Seite vorausgefüllt). **Auf der Kommandozeile:** `python spotify_status.py github-login` (bzw. `Fluxer-Spotify.exe github-login`) verbindet GitHub mit einem **Nur-Lese-Token** (die Eingabe ist unsichtbar; unter Windows wird der Token wie die anderen verschlüsselt gespeichert). Erstelle auf <https://github.com/settings/personal-access-tokens/new> einen *Fine-grained token*: „Public repositories“ reicht für öffentliche Daten; für Zähler aus privaten Repos (offene PRs, Reviews, Issues) wähle „All repositories“ mit **Pull requests: Read** und **Issues: Read**. Gib ihm nie Schreibrechte.

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
- `--ttl` / `STATUS_TTL`: Sekunden, nach denen Fluxer den Status von selbst löscht, wenn das Programm ihn nicht erneuert (Standard `0` = aus, Minimum 120, Maximum 86400). Sinnvoll, wenn der PC ausgehen kann.

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
python spotify_status.py                     # Start aus dem Quellcode (klassische Konsolen-Einrichtung; Daten im Projektordner)
python spotify_status.py gui                 # das Launcher-Fenster aus dem Quellcode
python -m unittest discover -s tests -t .    # Tests (nur Standardbibliothek; Fenster-Tests brauchen tkinter und ein Display, sonst werden sie übersprungen)
pip install -r requirements-dev.txt          # PyInstaller, nur zum Bauen
build_exe.bat                                # erzeugt dist\Fluxer-Spotify.exe
python assets/make_icon.py                   # erzeugt assets/icon.ico neu (braucht Pillow, nur wenn du das Icon änderst)
```

Die Laufzeit nutzt nur die Standardbibliothek (der Launcher nutzt `tkinter`, das zu Python gehört); PyInstaller wird nur zum Bauen gebraucht. Die Exe ist ein **Fenster-Programm** (`--windowed`): Doppelklick öffnet den Launcher, mit Argumenten gestartet schreibt sie in das Terminal, aus dem sie kam. Ein Tag `v*` (z. B. `git tag v2.3.0 && git push --tags`) startet `.github/workflows/release.yml`: Tests, Bau, optionales Signieren ([SIGNING.md](SIGNING.md)), Rauchtest der gebauten Exe (`--selftest`: ist Tcl/Tk drin?), SHA256, Release. Als Exe liegen die Daten in `%APPDATA%\spotify-fluxer`, aus dem Quellcode im Projektordner (überschreibbar mit `--data-dir` oder `FLUXER_SPOTIFY_HOME`).

Aufbau: `fluxer_spotify/launcher.py` enthält alles, was das Fenster zeigt und tut (kein GUI-Code, vollständig getestet); `ui.py` ist nur die tkinter-Oberfläche darüber. Tests öffnen nie einen echten Browser und zeigen keine Fenster (`tests/__init__.py` verhindert das).

## Warnung (Nutzungsbedingungen)

Das Automatisieren eines **persönlichen Accounts** (Self-Bot) **kann gegen die Nutzungsbedingungen von Fluxer verstoßen**. Das Tool meldet sich wie ein Client mit deinem Account an und ändert nur deinen Status, aber **Benutzung auf eigenes Risiko**. Wer nur den Webhook nutzen will, braucht keinen Login (`FLUXER_WEBHOOK` setzen, kein `fluxer-login`).

## SECURITY

- `state.json` und `.env` enthalten Geheimnisse (Tokens, Webhook-URL). Sie stehen in `.gitignore`, **nie committen oder teilen**. Wer den Session-Token hat, hat vollen Zugriff auf deinen Fluxer-Account, bis die Sitzung beendet wird (`logout` oder Fluxer-Einstellungen). Unter Windows sind die Tokens in `state.json` verschlüsselt, die Webhook-URL und `.env` aber nicht.
- Das Tool spricht nur mit `api.fluxer.app`, `accounts.spotify.com`, `api.spotify.com` und deinem Webhook. `FLUXER_API` muss `https://` nutzen (Ausnahme: localhost).
- **Weiterleitungen auf andere Hosts werden nicht verfolgt.** Python behält bei einer Weiterleitung den `Authorization`-Header; ein anderer Server bekäme so deinen Token. Nur Weiterleitungen innerhalb desselben Hosts werden verfolgt, jede andere 3xx-Antwort ist ein Fehler.
- **`stop` beendet nie ein Programm, das es nicht zuordnen kann.** PIDs werden wiederverwendet; bevor eine hängende Instanz beendet wird, prüft das Programm, dass die PID noch zu ihm gehört (sonst: `unresponsive`). Eine veraltete PID-Datei, die ein anderes Programm nennt, blockiert keinen Start.
- **Keine versteckten Skript-Starter, keine Admin-Rechte, kein offener Port außer dem kurzen Loopback-Login** (`127.0.0.1:8888`, nur beim Verbinden von Spotify). Der GitHub-Token braucht nur die zwei Lese-Rechte (`pull_requests`, `issues`); die vorausgefüllte Token-Seite fragt nach nichts anderem.
- Der Launcher speichert das Fluxer-Passwort nie (er leert das Feld, sobald die Anmeldung läuft) und meldet Passwort und Tokens für die Log-Schwärzung an.
- Releases sind prüfbar: SHA256, Versionsinfo, optional Authenticode-Signatur. Es gibt kein Auto-Update, das Programm lädt also nie Code nach und führt ihn aus.
- Auf Windows setzt das Tool keine NTFS-Rechte; die Datei liegt in deinem Benutzerordner. Auf einem geteilten Rechner den Ordner entsprechend schützen.
- Sicherheitslücke gefunden? Bitte einen privaten Hinweis an die Maintainer statt eines öffentlichen Issues.

## Mitwirken und Lizenz

Siehe [CONTRIBUTING.md](CONTRIBUTING.md). Lizenz: MIT ([LICENSE](LICENSE)).

English version: [README.md](README.md)

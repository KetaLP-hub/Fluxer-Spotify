"""Command line: login, fluxer-login, fluxer-token, github-login, logout, status/doctor, run (--background), stop, logs, uninstall, autostart."""
import argparse
import getpass
import logging
import signal
import sys
import time
import types
import webbrowser

from . import __version__, autostart, background, github as github_mod, log as logmod
from .config import GH_DEFAULT_LINES, GH_LINES, load_config
from .errors import LANGS, AuthError, Fatal, bi, get_lang, set_lang, blog
from .fluxer import FluxerClient, Webhook, login as fluxer_login_flow
from .github import GitHubClient
from .http import Http, HttpError, NetworkError
from .runner import Runner
from .spotify import SpotifyClient
from .store import FLUXER_KEYS, GITHUB_KEYS, SPOTIFY_KEYS, Store
from . import wizard

log = logging.getLogger("fluxer_spotify")
COMMANDS = ("run", "gui", "login", "fluxer-login", "fluxer-token", "github-login", "logout", "status", "doctor",
            "install-autostart", "uninstall-autostart", "stop", "logs", "uninstall")


class Stop(Exception):
    """Raised by SIGTERM/SIGBREAK or a stop request so the shutdown path (clear status) runs."""


class NeedsUser(Fatal):
    """Background mode must never prompt: the user has to start the program normally."""


def _no_prompt(*_, **__):
    raise NeedsUser(bi("Einrichtung unvollstaendig oder Login abgelaufen. Bitte Fluxer-Spotify.exe normal starten (Doppelklick).",
                       "Setup incomplete or login expired. Please start Fluxer-Spotify.exe normally (double-click)."))


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    S = argparse.SUPPRESS  # unset flags must not shadow env/.env values
    common.add_argument("-v", "--verbose", action="store_true", default=S, help="debug logging (never prints secrets)")
    common.add_argument("--log-file", default=S, help="also write the log to this file")
    common.add_argument("--data-dir", default=S, help="where .env and state.json live (default: project folder, or %%APPDATA%%\\spotify-fluxer for the exe)")
    common.add_argument("--background", "--hidden", dest="background", action="store_true", default=S,
                        help="run without any window: hides the console, logs to fluxer-spotify.log, never prompts")
    common.add_argument("--lang", dest="language", default=S, help="language of all messages: auto (default, from the OS), de or en (LANGUAGE in .env)")
    common.add_argument("--client-id", dest="client_id", default=S, help="Spotify Client ID")
    common.add_argument("--api", default=S, help="Fluxer API base URL (own instances only)")
    common.add_argument("--webhook", default=S, help="optional Fluxer webhook URL (channel card)")
    common.add_argument("--template", default=S, help="text of the 'now' status line, with {title} {artist} {album}")
    common.add_argument("--lines", default=S, help="rotating status lines, comma separated (default: now,playlist,top_artist,listening_today); "
                                                   "GitHub lines: gh_push gh_commits gh_prs gh_reviews gh_issues gh_streak gh_stars gh_followers; "
                                                   "custom templates with {title} {artist} {album} {playlist} {top_artist} {hours} {minutes} "
                                                   "{gh_repo} {gh_ago} {gh_commits} {gh_prs} {gh_reviews} {gh_issues} {gh_streak} {gh_stars} {gh_followers}, separated by |")
    common.add_argument("--rotate", default=S, help="seconds per status line (default 30, minimum 15)")
    common.add_argument("--no-rotate", dest="no_rotate", action="store_true", default=S, help="no rotation: only the first line")
    common.add_argument("--on-pause", dest="on_pause", choices=("clear", "keep", "stats"), default=S,
                        help="paused: clear the status, keep it, or rotate only the stats lines")
    common.add_argument("--on-idle", dest="on_idle", choices=("clear", "lines"), default=S,
                        help="nothing playing at all: clear the status (default) or keep rotating the lines that need no track (GitHub, stats)")
    common.add_argument("--interval", default=S, help="poll interval in seconds (min 2)")
    common.add_argument("--ttl", default=S, help="status lifetime in seconds: Fluxer clears it by itself after that (default 0 = off; min 120)")
    p = argparse.ArgumentParser(prog="spotify_status.py", parents=[common],
                                description="Mirror Spotify 'now playing' into your Fluxer custom status.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)  # CI: does the packaged exe start (GUI toolkit present)?
    sub = p.add_subparsers(dest="command", metavar="command")
    helps = {"run": "start mirroring (default)", "gui": "open the launcher window (default for the exe)", "login": "log in to Spotify (browser, once)",
             "fluxer-login": "log in to Fluxer with e-mail + password (token is stored, password is not)",
             "fluxer-token": "fallback: paste a Fluxer token from the browser",
             "github-login": "optional: connect GitHub with a read-only token (adds GitHub status lines)",
             "logout": "clear the status and delete stored tokens", "status": "check setup and logins",
             "doctor": "same as status", "install-autostart": "start with Windows",
             "uninstall-autostart": "remove the Windows autostart entry",
             "stop": "stop the running (background) instance and clear the status", "logs": "print the last 50 log lines",
             "uninstall": "remove autostart, stop, log out and delete all stored data (asks first)"}
    for name in COMMANDS:
        sp = sub.add_parser(name, parents=[common], help=helps[name])
        if name == "fluxer-login":
            sp.add_argument("--email", help="e-mail (asked interactively if omitted); the password is never a flag")
        if name == "logout":
            sp.add_argument("--keep-spotify", action="store_true", help="keep the Spotify login")
    return p


def _sigterm(*_):
    raise Stop()


def entry():
    """Console entry point. As a frozen exe the window would vanish on errors, so wait for Enter."""
    frozen = getattr(sys, "frozen", False)
    argv = sys.argv[1:]
    if frozen and argv and sys.stdout is None:
        background.attach_parent_console()  # the exe is a windowed program: show its output in the terminal it was started from
    try:
        # Double-click (no arguments): the exe opens the launcher window. Source runs keep the console wizard (`gui` opens the window).
        rc = main(["gui"] if frozen and not argv else None, keep_lang=True)
    except Exception:
        import traceback
        traceback.print_exc()
        log.exception(bi("Absturz", "crash", " / "))  # background mode has no console: the log file is the only trace
        rc = 1
    # No "press Enter" pause any more: the exe is a windowed program (no console window that could vanish). Errors of a double-click
    # start appear in a message box; with arguments they stay in the terminal the exe was started from.
    return rc


def main(argv=None, http=None, getpass_fn=getpass.getpass, input_fn=input, keep_lang=False):
    """`keep_lang`: leave the selected language set on return (entry() still prints in it); otherwise restore the previous one."""
    prev = get_lang()
    try:
        return _main(argv, http, getpass_fn, input_fn)
    finally:
        if not keep_lang:
            set_lang(prev)


def _main(argv, http, getpass_fn, input_fn):
    for stream in (sys.stdout, sys.stderr):  # emoji in logs must not crash legacy Windows consoles
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    if sys.stdout is None or sys.stderr is None:  # windowed exe without a terminal
        background.fix_streams()
    args = build_parser().parse_args(argv)
    if getattr(args, "selftest", False):
        return selftest()
    early = str(getattr(args, "language", "")).lower()
    set_lang(early if early in LANGS else None)  # so even config errors use the language given on the command line
    command = args.command or "run"
    bg = bool(getattr(args, "background", False)) and command == "run"
    if bg:
        background.fix_streams()
        background.hide_console()
        getpass_fn = input_fn = _no_prompt

    def fail(msg):  # no console in background mode: errors go to the log file
        if bg:
            log.error("%s", msg.strip())
        else:
            print(msg, file=sys.stderr)
        return 1

    logmod.setup(getattr(args, "verbose", False), getattr(args, "log_file", None), console=not bg)
    try:
        cfg = load_config(args)
        if bg:  # ponytail: errors before this point (unwritable data dir) are not logged anywhere
            logmod.add_file(cfg.data_dir / background.LOG_NAME)
        ctx = Ctx(cfg, http or Http(), getpass_fn, input_fn, background=bg)
        set_lang(cfg.lang)
        if bg:
            ctx.open_browser = _no_prompt
        return {"run": ctx.run, "gui": ctx.gui, "login": ctx.spotify_login, "fluxer-login": lambda: ctx.fluxer_login(args),
                "fluxer-token": ctx.fluxer_token, "github-login": ctx.github_login, "logout": lambda: ctx.logout(args), "status": ctx.doctor,
                "doctor": ctx.doctor, "install-autostart": lambda: ctx.autostart(True),
                "uninstall-autostart": lambda: ctx.autostart(False), "stop": ctx.stop, "logs": ctx.logs,
                "uninstall": ctx.uninstall}[command]() or 0
    except Fatal as e:
        return fail(f"\n{bi('[FEHLER]', '[ERROR]', ' / ')}\n{e}\n")
    except HttpError as e:
        return fail(f"\n{bi('[FEHLER]', '[ERROR]', ' / ')} HTTP {e.status} {e.code or ''} ({e.url})\n")
    except NetworkError as e:
        return fail(bi(f"\n[FEHLER] Keine Verbindung: {e}\n", f"[ERROR] Network problem: {e}\n"))
    except KeyboardInterrupt:
        print("\n" + bi("Abgebrochen.", "Cancelled.", " / "), file=sys.stderr)
        return 130


def selftest():
    """Smoke test of a packaged exe (run by the release workflow): can the launcher's GUI toolkit start? 0 = fine."""
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
    except Exception as e:  # missing Tcl/Tk files in the bundle, no display, ...
        print(f"selftest FAILED: tkinter: {e}", file=sys.stderr)
        return 1
    print(f"selftest ok ({__version__})")
    return 0


class Ctx:
    def __init__(self, cfg, http, getpass_fn, input_fn, open_browser=webbrowser.open, background=False):
        self.cfg, self.http, self.getpass, self.input, self.open_browser = cfg, http, getpass_fn, input_fn, open_browser
        self.background, self._lock = background, None
        self.store = Store(cfg.state_file)
        if not cfg.client_id:  # precedence: flags > env > .env > stored by the wizard
            cfg.client_id = self.store.get("client_id", "")
        if not cfg.language and self.store.get("language") in LANGS:
            cfg.language = self.store.get("language")
        if self.store.get("github_token") and not cfg.lines_explicit:  # connecting GitHub is the opt-in for its lines
            cfg.lines = cfg.lines + tuple(n for n in GH_DEFAULT_LINES if n not in cfg.lines)

    # --- builders
    def spotify(self):
        if not self.cfg.client_id:
            raise Fatal(bi("Spotify Client ID fehlt. Starte das Programm ohne Zusatz (run), dann fragt es danach.",
                           "Spotify Client ID is missing. Start the program without arguments (run) and it will ask for it."))
        return SpotifyClient(self.http, self.store, self.cfg.client_id)

    def github(self):
        token = self.store.get("github_token")
        return GitHubClient(self.http, token) if token else None

    def fluxer(self):
        token, source = self.store.fluxer_token(self.cfg)
        return FluxerClient(self.http, self.cfg.api, token, source) if token else None

    # --- commands
    def spotify_login(self):
        self.spotify().login()
        print(bi("Spotify-Login ok.", "Spotify login ok."))

    def fluxer_login(self, args):
        print(bi("Fluxer-Login. Dein Passwort wird nur einmal an die Fluxer-API gesendet und nicht gespeichert.",
                 "Fluxer login. Your password is sent once to the Fluxer API only and is not stored."))
        email = (getattr(args, "email", None) or self.input("E-Mail: ")).strip()
        password = self.getpass(bi("Passwort (Eingabe unsichtbar): ", "Password (input hidden): "))
        logmod.add_secret(password)

        def ask_code(attempt):
            return self.getpass(bi("2FA-Code (Authenticator oder Backup-Code, leer = Abbruch): ",
                                           "2FA code (authenticator or backup code, empty = cancel): ")).strip()

        try:
            res = fluxer_login_flow(self.http, self.cfg.api, email, password, ask_code, notify=print)
        finally:
            del password  # drops our reference; Python cannot zero an immutable str, so keep the lifetime short
        logmod.add_secret(res["token"])
        self.store.update(fluxer_token=res["token"], fluxer_token_source="login", fluxer_user=res["user"].get("username"))
        name = res["user"].get("global_name") or res["user"].get("username") or "?"
        print(bi(f"Angemeldet als {name}. Nur der Token wurde gespeichert.", f"Logged in as {name}. Only the token was stored."))
        if self.cfg.fluxer_token:
            print(bi("Hinweis: FLUXER_TOKEN ist noch gesetzt (.env/Umgebung) und hat Vorrang. Entferne ihn, um den neuen Login zu nutzen.",
                     "Note: FLUXER_TOKEN is still set (.env/environment) and takes precedence. Remove it to use the new login."))

    def fluxer_token(self):
        print(bi("Fallback: Token aus dem Browser einfuegen (siehe README). Eingabe unsichtbar.",
                 "Fallback: paste the token from your browser (see README). Input is hidden."))
        token = self.getpass("Fluxer-Token: ").strip().strip("\"'")
        if not token:
            raise Fatal(bi("Kein Token eingegeben.", "No token entered."))
        logmod.add_secret(token)
        me = FluxerClient(self.http, self.cfg.api, token, "manual").me()  # validates before storing
        self.store.update(fluxer_token=token, fluxer_token_source="manual", fluxer_user=me.get("username"))
        print(bi(f"Token gueltig ({me.get('username', '?')}) und gespeichert.", f"Token valid ({me.get('username', '?')}) and stored."))

    def github_login(self):
        url = github_mod.token_page_url()
        print(bi("GitHub verbinden (optional). Das Tool braucht nur LESE-Rechte.\n"
                 f"  1. Oeffne {url} (Name, Laufzeit und die beiden Lese-Rechte sind schon eingetragen) und klicke 'Generate token'.\n"
                 "  2. Repository access: 'Public repositories' reicht fuer oeffentliche Daten. Fuer Zaehler aus privaten Repos\n"
                 "     (offene PRs, Reviews, Issues): 'All repositories' mit den Rechten 'Pull requests: Read' und 'Issues: Read'.\n"
                 "  3. Gib dem Token keine Schreibrechte. Er wird verschluesselt gespeichert (Windows), die Eingabe ist unsichtbar.",
                 "Connect GitHub (optional). The tool only needs READ access.\n"
                 f"  1. Open {url} (name, lifetime and the two read permissions are pre-filled) and click 'Generate token'.\n"
                 "  2. Repository access: 'Public repositories' is enough for public data. For counts from private repos\n"
                 "     (open PRs, reviews, issues): 'All repositories' with 'Pull requests: Read' and 'Issues: Read'.\n"
                 "  3. Give the token no write permissions. It is stored encrypted (Windows); the input is hidden."))
        try:
            self.open_browser(url)
        except Exception:
            pass  # the URL is printed above anyway
        token = self.getpass(bi("GitHub-Token: ", "GitHub token: ")).strip().strip("\"'")
        logmod.add_secret(token)
        login = github_mod.connect(self.http, self.store, token)  # validates before storing; raises AuthError on a bad token
        print(bi(f"GitHub verbunden als {login}. Nur der Token wurde gespeichert.", f"GitHub connected as {login}. Only the token was stored."))
        print(bi("Die GitHub-Zeilen laufen jetzt in der Rotation mit (wenn du STATUS_LINES nicht selbst gesetzt hast).\n"
                 "Tipp: ON_IDLE=lines zeigt sie auch, wenn gerade keine Musik laeuft. Zum Entfernen: logout oder den Token auf GitHub loeschen.",
                 "The GitHub lines now join the rotation (unless you set STATUS_LINES yourself).\n"
                 "Tip: ON_IDLE=lines keeps showing them while no music plays. To remove: logout, or delete the token on GitHub."))

    def logout(self, args):
        fx = self.fluxer()
        if fx:
            try:
                fx.set_status(None)
                print(bi("Fluxer-Status geloescht.", "Fluxer status cleared."))
            except (Fatal, HttpError, NetworkError) as e:
                log.warning(blog("Status konnte nicht geloescht werden: %s", "Could not clear status: %s", e))
            if fx.source == "login" and not self.cfg.fluxer_token:
                try:
                    fx.logout()
                    print(bi("Fluxer-Sitzung beendet.", "Fluxer session revoked."))
                except (Fatal, HttpError, NetworkError) as e:
                    log.warning(blog("Sitzung konnte nicht beendet werden: %s", "Could not revoke session: %s", e))
        had_github = bool(self.store.get("github_token"))
        self.store.clear(FLUXER_KEYS + GITHUB_KEYS + (() if args.keep_spotify else SPOTIFY_KEYS))
        print(bi("Gespeicherte Tokens geloescht.", "Stored tokens deleted."))
        if had_github:
            print(bi("Der GitHub-Token wurde nur lokal geloescht. Zum Widerrufen: https://github.com/settings/personal-access-tokens",
                     "The GitHub token was only deleted locally. To revoke it: https://github.com/settings/personal-access-tokens"))
        if self.cfg.fluxer_token:
            print(bi("FLUXER_TOKEN in .env/Umgebung bleibt bestehen (dein Browser-Token, wird nicht widerrufen). Entferne ihn von Hand.",
                     "FLUXER_TOKEN in .env/environment stays (it is your browser token, not revoked). Remove it by hand."))

    def doctor(self):
        problems = []

        def line(ok, de, en):
            text = bi(de, en, "\n         ")
            print(f"  [{'OK' if ok is True else 'INFO' if ok is None else '!!'}] {text}")
            if ok is False:
                problems.append(text)

        fix = lambda cmd: bi(f"Loesung: python spotify_status.py {cmd}", f"Fix: python spotify_status.py {cmd}", " / ")
        print(bi(f"spotify-fluxer {__version__}  (Daten: {self.cfg.data_dir})", f"spotify-fluxer {__version__}  (data: {self.cfg.data_dir})", " / "))
        line(None, f"Sprache: {self.cfg.lang} (Einstellung: {self.cfg.language or 'auto'})",
             f"Language: {self.cfg.lang} (setting: {self.cfg.language or 'auto'})")
        line(bool(self.cfg.client_id),
             "Spotify Client ID gesetzt" if self.cfg.client_id else "Spotify Client ID fehlt (beim Start ohne Zusatz wird sie abgefragt)",
             "Spotify Client ID set" if self.cfg.client_id else "Spotify Client ID missing (asked on a plain start)")
        if self.store.get("refresh") and self.cfg.client_id:
            try:
                sp = self.spotify()
                sp.refresh()  # live check; works for expired access tokens too
                line(True, "Spotify-Login funktioniert", "Spotify login works")
            except AuthError as e:
                line(False, str(e).split("\n")[0], fix("login"))
            except (HttpError, NetworkError) as e:
                line(False, f"Spotify nicht erreichbar: {e}", f"Spotify unreachable: {e}")
        else:
            line(False, "Nicht bei Spotify angemeldet", "Not logged in to Spotify")
            print("         " + fix("login"))
        fx = self.fluxer()
        if fx:
            try:
                me = fx.me()
                where = "env/.env" if fx.source == "manual" and self.cfg.fluxer_token else fx.source
                line(True, f"Fluxer-Token gueltig: {me.get('username', '?')} (Quelle: {where})",
                     f"Fluxer token valid: {me.get('username', '?')} (source: {where})")
            except AuthError as e:
                line(False, str(e).split("\n")[0], fix("fluxer-login"))
            except (HttpError, NetworkError) as e:
                line(False, f"Fluxer nicht erreichbar: {e}", f"Fluxer unreachable: {e}")
        else:
            line(None if self.cfg.webhook else False, "Kein Fluxer-Token" + (" (nur Webhook-Betrieb)" if self.cfg.webhook else ""),
                 "No Fluxer token" + (" (webhook-only operation)" if self.cfg.webhook else ""))
            if not self.cfg.webhook:
                print("         " + fix("fluxer-login"))
        gh = self.github()
        wants_gh = any(n in GH_LINES or "{gh_" in n for n in self.cfg.lines)
        if gh:
            try:
                login = gh.me()
                line(True, f"GitHub-Token gueltig: {login}", f"GitHub token valid: {login}")
            except AuthError as e:
                line(False, str(e).split("\n")[0], fix("github-login"))
            except (HttpError, NetworkError) as e:
                line(False, f"GitHub nicht erreichbar: {e}", f"GitHub unreachable: {e}")
        else:
            line(False if wants_gh else None,
                 "GitHub-Zeilen sind aktiv, aber GitHub ist nicht verbunden" if wants_gh else "GitHub nicht verbunden (optional): github-login",
                 "GitHub lines are enabled but GitHub is not connected" if wants_gh else "GitHub not connected (optional): github-login")
            if wants_gh:
                print("         " + fix("github-login"))
        prot = self.store.protection
        line(True if prot else None,
             f"Tokens in state.json verschluesselt ({prot})" if prot else "Tokens liegen unverschluesselt in state.json (nur Dateirechte); sichere Speicherung gibt es nur unter Windows",
             f"Tokens in state.json are encrypted ({prot})" if prot else "Tokens are stored unencrypted in state.json (file permissions only); secure storage is Windows-only")
        line(None, f"Webhook: {'konfiguriert' if self.cfg.webhook else 'nicht gesetzt'}; Template: {self.cfg.template}; Pause: {self.cfg.on_pause}; Leerlauf: {self.cfg.on_idle}",
             f"Webhook: {'configured' if self.cfg.webhook else 'not set'}; template: {self.cfg.template}; pause: {self.cfg.on_pause}; idle: {self.cfg.on_idle}")
        line(None, f"Status-Zeilen: {', '.join(self.cfg.lines)}; " + ("keine Rotation" if self.cfg.no_rotate else f"Rotation alle {self.cfg.rotate:g} s"),
             f"Status lines: {', '.join(self.cfg.lines)}; " + ("no rotation" if self.cfg.no_rotate else f"rotation every {self.cfg.rotate:g} s"))
        pid = background.running_pid(self.cfg.data_dir)
        line(None, f"Hintergrund-Instanz laeuft (PID {pid}); beenden: stop" if pid else "Keine Instanz laeuft",
             f"Background instance running (PID {pid}); stop it with: stop" if pid else "No instance is running")
        log_path = self.cfg.data_dir / background.LOG_NAME
        line(None, f"Log: {log_path}", f"Log: {log_path}")
        print("\n" + (bi("Alles in Ordnung.", "All good.") if not problems else bi(f"{len(problems)} Problem(e).", f"{len(problems)} problem(s).")))
        return 1 if problems else 0

    def autostart(self, install):
        if install:
            where = autostart.install(self.cfg.data_dir)
            print(bi(f"Autostart eingerichtet (startet unsichtbar im Hintergrund, siehe Task-Manager > Autostart): {where}\nLog: {self.cfg.data_dir / background.LOG_NAME}",
                     f"Autostart installed (starts hidden in the background, see Task Manager > Startup apps): {where}\nLog: {self.cfg.data_dir / background.LOG_NAME}"))
        else:
            t = autostart.uninstall()
            print(bi("Autostart entfernt.", "Autostart removed.") if t else bi("Kein Autostart gefunden.", "No autostart entry found."))

    def run(self):
        try:
            self._lock = background.InstanceLock(self.cfg.data_dir).acquire()
        except background.AlreadyRunning as e:
            if self.background:
                log.info(blog("Zweiter Start ignoriert: %s", "Second start ignored: %s", str(e).splitlines()[0]))
                return 0
            raise
        try:
            return self._run()
        except Fatal as e:
            if not self.background:
                raise
            log.error("%s", e)
            where = self.cfg.data_dir / background.LOG_NAME
            background.notify_once(self.cfg.data_dir, bi(
                f"Fluxer Spotify braucht dich: Bitte Fluxer-Spotify.exe normal starten (Doppelklick), um das Problem zu beheben.\nDetails: {where}",
                f"Fluxer Spotify needs you: please start Fluxer-Spotify.exe normally (double-click) to fix the problem.\nDetails: {where}"))
            return 1
        finally:
            self._lock.release()
            background.clear_stop(self.cfg.data_dir)

    def _setup(self):
        """Wizard; in background mode a missing network (boot) is retried instead of giving up."""
        sleep = background.make_stop_sleep(self.cfg.data_dir, stop_exc=Stop)
        for attempt in range(10 if self.background else 1):
            try:
                return wizard.setup(self, interactive=not self.background)
            except (HttpError, NetworkError) as e:
                if not self.background or attempt == 9:
                    raise
                log.warning(blog("Netzwerk noch nicht bereit: %s (neuer Versuch in 30 s)", "Network not ready: %s (retry in 30 s)", e))
                sleep(30)

    def _run(self):
        try:
            if self._setup():
                return 0  # handed over to the hidden background process
        except Stop:
            return 0
        sp = self.spotify()
        fx = self.fluxer()
        hook = Webhook(self.http, self.cfg.webhook, self.store) if self.cfg.webhook else None
        if not (fx or hook):
            raise Fatal(bi("Kein Fluxer-Login. Erst ausfuehren: python spotify_status.py fluxer-login",
                           "No Fluxer login. Run first: python spotify_status.py fluxer-login"))
        runner = Runner(self.cfg, sp, fx, hook, github=self.github())
        for name in ("SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), _sigterm)
        if self.background:
            background.clear_attention(self.cfg.data_dir)
        where = (bi(" im Hintergrund", " in the background"),) if self.background else ("",)
        log.info(blog("Laeuft%s. Strg+C bzw. 'stop' beendet und loescht den Status.",
                     "Running%s. Ctrl+C or 'stop' ends it and clears the status.", *where))
        try:
            sleep = background.make_stop_sleep(self.cfg.data_dir, stop_exc=Stop)
            if self.background:
                self._supervise(runner, sleep)
            else:
                runner.run(sleep=sleep)
        except (KeyboardInterrupt, Stop):
            print("\n" + bi("Beendet.", "Stopped.", " / "))
            log.info(bi("Beendet.", "Stopped.", " / "))
        finally:
            runner.shutdown()
        return 0

    def _supervise(self, runner, sleep, clock=time.monotonic):
        """24/7 mode: an unexpected error (a bug, an odd API answer) must not end the run. Log it, wait, carry on.

        Anything that needs the user (a login that stopped working -> Fatal/AuthError) and every stop request still end it.
        """
        failures, began = 0, clock()
        while True:
            try:
                runner.run(sleep=sleep)
            except (KeyboardInterrupt, Stop, Fatal):
                raise
            except Exception:
                log.exception(bi("Unerwarteter Fehler, mache weiter", "Unexpected error, carrying on", " / "))
                if clock() - began > 600:  # it had been running fine for a while: start the back-off over
                    failures = 0
                failures += 1
                sleep(min(300, 15 * 2 ** (failures - 1)))
                began = clock()

    def gui(self):
        from . import ui  # tkinter is only needed here
        return ui.run(self.cfg, self.http)

    def start_background(self):
        """Wizard hand-over: free the lock, start a hidden copy of ourselves, True once it is up."""
        if self._lock:
            self._lock.release()
        cfg = self.cfg
        extra = ["--template", cfg.template, "--on-pause", cfg.on_pause, "--on-idle", cfg.on_idle, "--interval", str(cfg.interval), "--api", cfg.api,
                 "--lines", "|".join(cfg.lines), "--rotate", str(cfg.rotate), "--lang", cfg.lang, "--ttl", str(cfg.ttl)] + (["--no-rotate"] if cfg.no_rotate else [])
        try:
            pid = background.spawn_background(cfg.data_dir, extra)
        except OSError as e:
            log.warning(blog("Start im Hintergrund fehlgeschlagen: %s", "Background start failed: %s", e))
            pid = None
        where = cfg.data_dir / background.LOG_NAME
        if pid:
            print(bi(f"Laeuft jetzt unsichtbar im Hintergrund (PID {pid}). Dieses Fenster schliesst sich.\n"
                     f"Beenden: Fluxer-Spotify.exe stop   |   Log: {where}",
                     f"Now running hidden in the background (PID {pid}). This window closes.\n"
                     f"Stop: Fluxer-Spotify.exe stop   |   Log: {where}"))
            time.sleep(3)  # leave time to read it
            return True
        print(bi("Der Hintergrundstart hat nicht geklappt. Das Programm laeuft weiter in diesem Fenster.",
                 "Starting in the background did not work. The program keeps running in this window."))
        if self._lock:
            try:
                self._lock.acquire()
            except Fatal:
                pass
        return False

    def stop(self):
        res = background.stop_instance(self.cfg.data_dir)
        if res == "none":
            print(bi("Es laeuft keine Instanz.", "No instance is running."))
        elif res == "clean":
            print(bi("Instanz beendet, Fluxer-Status geloescht.", "Instance stopped, Fluxer status cleared."))
        elif res == "unresponsive":
            print(bi("Instanz reagierte nicht, und es ist nicht sicher, dass die PID noch zu diesem Programm gehoert - nichts wurde beendet.\n"
                     "Beende \"Fluxer-Spotify.exe\" bei Bedarf im Task-Manager.",
                     "The instance did not respond and it is not certain the PID still belongs to this program - nothing was terminated.\n"
                     "End \"Fluxer-Spotify.exe\" in Task Manager if needed."))
        else:
            print(bi("Instanz reagierte nicht und wurde hart beendet.", "Instance did not respond and was terminated."))
            fx = self.fluxer()
            if fx:
                try:
                    fx.set_status(None)
                    print(bi("Fluxer-Status geloescht.", "Fluxer status cleared."))
                except (Fatal, HttpError, NetworkError) as e:
                    log.warning(blog("Status konnte nicht geloescht werden: %s", "Could not clear status: %s", e))

    def logs(self):
        lines = background.tail(self.cfg.data_dir / background.LOG_NAME, 50)
        print("\n".join(lines) if lines else bi("Noch kein Log vorhanden.", "No log yet."))

    def uninstall(self):
        d = self.cfg.data_dir
        print(bi(f"Das stoppt das Programm, entfernt den Autostart, meldet bei Fluxer/Spotify ab und loescht state.json, .env und Logs in {d}.\n"
                 "Die exe selbst bleibt liegen (von Hand loeschen).",
                 f"This stops the program, removes autostart, logs out and deletes state.json, .env and logs in {d}.\n"
                 "The exe itself stays (delete it by hand)."))
        if self.input(bi("Wirklich deinstallieren? (j/n): ", "Really uninstall? (y/n): ")).strip().lower() not in wizard.YES:
            print(bi("Abgebrochen.", "Cancelled."))
            return 1
        self.stop()
        if autostart.available() and autostart.uninstall():
            print(bi("Autostart entfernt.", "Autostart removed."))
        self.logout(types.SimpleNamespace(keep_spotify=False))
        root = logging.getLogger("fluxer_spotify")
        for h in list(root.handlers):  # Windows cannot delete an open log file
            h.close()
            root.removeHandler(h)
        n = background.LOG_NAME
        for name in ("state.json", "state.json.corrupt", ".env", n, n + ".1", n + ".2", background.PID_NAME,
                     background.STOP_NAME, background.ATTN_NAME):
            try:
                (d / name).unlink()
            except FileNotFoundError:
                pass
            except OSError as e:
                print(bi(f"Konnte {name} nicht loeschen: {e}", f"Could not delete {name}: {e}"))
        try:
            d.rmdir()  # only succeeds when empty: a source checkout keeps its folder
        except OSError:
            pass
        print(bi("Deinstalliert. Zum Schluss die exe loeschen.", "Uninstalled. Finally, delete the exe."))

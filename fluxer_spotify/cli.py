"""Command line: login, fluxer-login, fluxer-token, logout, status/doctor, run, install/uninstall-autostart."""
import argparse
import getpass
import logging
import signal
import sys

from . import __version__, autostart, log as logmod
from .config import load_config
from .errors import AuthError, Fatal, bi
from .fluxer import FluxerClient, Webhook, login as fluxer_login_flow
from .http import Http, HttpError, NetworkError
from .runner import Runner
from .spotify import SpotifyClient
from .store import FLUXER_KEYS, SPOTIFY_KEYS, Store

log = logging.getLogger("fluxer_spotify")
COMMANDS = ("run", "login", "fluxer-login", "fluxer-token", "logout", "status", "doctor",
            "install-autostart", "uninstall-autostart")


class Stop(Exception):
    """Raised by SIGTERM/SIGBREAK so the shutdown path (clear status) runs."""


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    S = argparse.SUPPRESS  # unset flags must not shadow env/.env values
    common.add_argument("-v", "--verbose", action="store_true", default=S, help="debug logging (never prints secrets)")
    common.add_argument("--log-file", default=S, help="also write the log to this file")
    common.add_argument("--data-dir", default=S, help="where .env and state.json live (default: project folder)")
    common.add_argument("--client-id", dest="client_id", default=S, help="Spotify Client ID")
    common.add_argument("--api", default=S, help="Fluxer API base URL (own instances only)")
    common.add_argument("--webhook", default=S, help="optional Fluxer webhook URL (channel card)")
    common.add_argument("--template", default=S, help="status text with {title} {artist} {album}")
    common.add_argument("--on-pause", dest="on_pause", choices=("clear", "keep"), default=S,
                        help="clear or keep the status when playback is paused")
    common.add_argument("--interval", default=S, help="poll interval in seconds (min 2)")
    p = argparse.ArgumentParser(prog="spotify_status.py", parents=[common],
                                description="Mirror Spotify 'now playing' into your Fluxer custom status.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", metavar="command")
    helps = {"run": "start mirroring (default)", "login": "log in to Spotify (browser, once)",
             "fluxer-login": "log in to Fluxer with e-mail + password (token is stored, password is not)",
             "fluxer-token": "fallback: paste a Fluxer token from the browser",
             "logout": "clear the status and delete stored tokens", "status": "check setup and logins",
             "doctor": "same as status", "install-autostart": "start with Windows",
             "uninstall-autostart": "remove the Windows autostart entry"}
    for name in COMMANDS:
        sp = sub.add_parser(name, parents=[common], help=helps[name])
        if name == "fluxer-login":
            sp.add_argument("--email", help="e-mail (asked interactively if omitted); the password is never a flag")
        if name == "logout":
            sp.add_argument("--keep-spotify", action="store_true", help="keep the Spotify login")
    return p


def _sigterm(*_):
    raise Stop()


def main(argv=None, http=None, getpass_fn=getpass.getpass, input_fn=input):
    for stream in (sys.stdout, sys.stderr):  # emoji in logs must not crash legacy Windows consoles
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    logmod.setup(getattr(args, "verbose", False), getattr(args, "log_file", None))
    command = args.command or "run"
    try:
        cfg = load_config(args)
        ctx = Ctx(cfg, http or Http(), getpass_fn, input_fn)
        return {"run": ctx.run, "login": ctx.spotify_login, "fluxer-login": lambda: ctx.fluxer_login(args),
                "fluxer-token": ctx.fluxer_token, "logout": lambda: ctx.logout(args), "status": ctx.doctor,
                "doctor": ctx.doctor, "install-autostart": lambda: ctx.autostart(True),
                "uninstall-autostart": lambda: ctx.autostart(False)}[command]() or 0
    except Fatal as e:
        print(f"\n[FEHLER / ERROR]\n{e}\n", file=sys.stderr)
        return 1
    except HttpError as e:
        print(f"\n[FEHLER / ERROR] HTTP {e.status} {e.code or ''} ({e.url})\n", file=sys.stderr)
        return 1
    except NetworkError as e:
        print(bi(f"\n[FEHLER] Keine Verbindung: {e}\n", f"[ERROR] Network problem: {e}\n"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAbgebrochen. / Cancelled.", file=sys.stderr)
        return 130


class Ctx:
    def __init__(self, cfg, http, getpass_fn, input_fn):
        self.cfg, self.http, self.getpass, self.input = cfg, http, getpass_fn, input_fn
        self.store = Store(cfg.state_file)

    # --- builders
    def spotify(self):
        if not self.cfg.client_id:
            raise Fatal(bi("SPOTIFY_CLIENT_ID fehlt. Kopiere .env.example nach .env und trage die Client ID aus "
                           "https://developer.spotify.com/dashboard ein.",
                           "SPOTIFY_CLIENT_ID is missing. Copy .env.example to .env and paste the Client ID from "
                           "https://developer.spotify.com/dashboard."))
        return SpotifyClient(self.http, self.store, self.cfg.client_id)

    def fluxer(self):
        token, source = self.store.fluxer_token(self.cfg)
        return FluxerClient(self.http, self.cfg.api, token, source) if token else None

    # --- commands
    def spotify_login(self):
        self.spotify().login()
        print("Spotify-Login ok. / Spotify login ok.")

    def fluxer_login(self, args):
        print(bi("Fluxer-Login. Dein Passwort wird nur einmal an die Fluxer-API gesendet und nicht gespeichert.",
                 "Fluxer login. Your password is sent once to the Fluxer API only and is not stored."))
        email = (args.email or self.input("E-Mail: ")).strip()
        password = self.getpass("Passwort / Password (Eingabe unsichtbar / hidden): ")
        logmod.add_secret(password)

        def ask_code(attempt):
            return self.getpass("2FA-Code (Authenticator oder Backup-Code, leer = Abbruch / empty = cancel): ").strip()

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

    def logout(self, args):
        fx = self.fluxer()
        if fx:
            try:
                fx.set_status(None)
                print(bi("Fluxer-Status geloescht.", "Fluxer status cleared."))
            except (Fatal, HttpError, NetworkError) as e:
                log.warning("Status konnte nicht geloescht werden / could not clear status: %s", e)
            if fx.source == "login" and not self.cfg.fluxer_token:
                try:
                    fx.logout()
                    print(bi("Fluxer-Sitzung beendet.", "Fluxer session revoked."))
                except (Fatal, HttpError, NetworkError) as e:
                    log.warning("Sitzung konnte nicht beendet werden / could not revoke session: %s", e)
        self.store.clear(FLUXER_KEYS + (() if args.keep_spotify else SPOTIFY_KEYS))
        print(bi("Gespeicherte Tokens geloescht.", "Stored tokens deleted."))
        if self.cfg.fluxer_token:
            print(bi("FLUXER_TOKEN in .env/Umgebung bleibt bestehen (dein Browser-Token, wird nicht widerrufen). Entferne ihn von Hand.",
                     "FLUXER_TOKEN in .env/environment stays (it is your browser token, not revoked). Remove it by hand."))

    def doctor(self):
        problems = []

        def line(ok, de, en=None):
            print(f"  [{'OK' if ok is True else 'INFO' if ok is None else '!!'}] {de}" + (f"\n         {en}" if en else ""))
            if ok is False:
                problems.append(de)

        print(f"spotify-fluxer {__version__}  (Daten / data: {self.cfg.data_dir})")
        line(bool(self.cfg.client_id), "Spotify Client ID gesetzt" if self.cfg.client_id else "SPOTIFY_CLIENT_ID fehlt (.env.example -> .env)")
        if self.store.get("refresh") and self.cfg.client_id:
            try:
                sp = self.spotify()
                sp.refresh()  # live check; works for expired access tokens too
                line(True, "Spotify-Login funktioniert")
            except AuthError as e:
                line(False, str(e).split("\n")[0], "Loesung / fix: python spotify_status.py login")
            except (HttpError, NetworkError) as e:
                line(False, f"Spotify nicht erreichbar / unreachable: {e}")
        else:
            line(False, "Nicht bei Spotify angemeldet", "Loesung / fix: python spotify_status.py login")
        fx = self.fluxer()
        if fx:
            try:
                me = fx.me()
                where = "env/.env" if fx.source == "manual" and self.cfg.fluxer_token else fx.source
                line(True, f"Fluxer-Token gueltig: {me.get('username', '?')} (Quelle / source: {where})")
            except AuthError as e:
                line(False, str(e).split("\n")[0], "Loesung / fix: python spotify_status.py fluxer-login")
            except (HttpError, NetworkError) as e:
                line(False, f"Fluxer nicht erreichbar / unreachable: {e}")
        else:
            line(None if self.cfg.webhook else False, "Kein Fluxer-Token" + (" (nur Webhook-Betrieb)" if self.cfg.webhook else ""),
                 "Loesung / fix: python spotify_status.py fluxer-login")
        line(None, f"Webhook: {'konfiguriert / configured' if self.cfg.webhook else 'nicht gesetzt / not set'}; "
                   f"Template: {self.cfg.template}; Pause: {self.cfg.on_pause}")
        print("\n" + ("Alles in Ordnung. / All good." if not problems else f"{len(problems)} Problem(e). / problem(s)."))
        return 1 if problems else 0

    def autostart(self, install):
        if install:
            path = autostart.install(_project_root())
            print(bi(f"Autostart eingerichtet: {path} (Log: fluxer-spotify.log)", f"Autostart installed: {path} (log: fluxer-spotify.log)"))
        else:
            t = autostart.uninstall()
            print(bi("Autostart entfernt.", "Autostart removed.") if t else bi("Kein Autostart gefunden.", "No autostart entry found."))

    def run(self):
        sp = self.spotify()
        if not self.store.get("refresh"):
            raise AuthError(bi("Noch nicht bei Spotify angemeldet. Erst ausfuehren: python spotify_status.py login",
                               "Not logged in to Spotify yet. Run first: python spotify_status.py login"))
        fx = self.fluxer()
        hook = Webhook(self.http, self.cfg.webhook, self.store) if self.cfg.webhook else None
        if not (fx or hook):
            raise Fatal(bi("Kein Fluxer-Login. Erst ausfuehren: python spotify_status.py fluxer-login",
                           "No Fluxer login. Run first: python spotify_status.py fluxer-login"))
        runner = Runner(self.cfg, sp, fx, hook)
        for name in ("SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), _sigterm)
        log.info("Laeuft. Strg+C beendet und loescht den Status. / Running. Ctrl+C stops and clears the status.")
        try:
            runner.run()
        except (KeyboardInterrupt, Stop):
            print("\nBeendet. / Stopped.")
        finally:
            runner.shutdown()


def _project_root():
    from .config import default_data_dir
    return default_data_dir()

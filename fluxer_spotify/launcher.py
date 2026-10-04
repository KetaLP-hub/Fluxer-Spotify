"""Launcher logic without any GUI toolkit: what the window shows and what its buttons do. Testable without a display.

The window (ui.py) is only a thin skin over this. Long-running calls (logins, start/stop) block, so the window runs them in
a worker thread. Nothing here prints or prompts: inputs arrive as arguments, progress goes to a `notify` callback.
"""
import logging
import os
import sys
import types
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from . import __version__, autostart, background, github as github_mod, log as logmod, settings, wizard
from .config import GH_DEFAULT_LINES, GH_LINES, LINE_NAMES
from .errors import AuthError, Fatal, bi
from .fluxer import FluxerClient, login as fluxer_login_flow
from .http import Http, HttpError, NetworkError
from .spotify import SpotifyClient
from .store import FLUXER_KEYS, SPOTIFY_KEYS, Store

log = logging.getLogger("fluxer_spotify.launcher")
FIRST_RUN_DEFAULTS = {"ON_IDLE": "lines", "ON_PAUSE": "stats", "STATUS_TTL": "600"}  # what "show me everything" means for the launcher
DEFAULT_ROTATE = 30
TTL_ON = "600"


@dataclass(frozen=True)
class Account:
    connected: bool
    detail: str = ""


@dataclass(frozen=True)
class Snapshot:
    version: str
    data_dir: Path
    exe: str
    frozen: bool
    exe_hint: str
    pid: object  # int | None
    attention: object  # str | None
    problem: object  # str | None: the .env file is invalid
    spotify: Account
    fluxer: Account
    github: Account
    webhook: bool
    client_id: str
    autostart_supported: bool
    autostart_on: bool
    autostart_current: bool
    autostart_blocked: bool
    lines: tuple
    default_lines: tuple
    show_when_idle: bool
    show_on_pause: bool
    rotate: int
    ttl_on: bool
    next_step: object  # "spotify" | "fluxer" | "github" | "start" | None

    @property
    def running(self):
        return self.pid is not None

    @property
    def ready(self):
        return self.spotify.connected and (self.fluxer.connected or self.webhook)


@dataclass(frozen=True)
class Check:
    name: str
    ok: object  # True / False / None (= informational)
    text: str


class Launcher:
    def __init__(self, cfg, http=None, which_exe=None):
        self.data_dir = Path(cfg.data_dir)
        self.http = http or Http()
        self._exe = which_exe or sys.executable
        self.cfg0 = cfg

    # ------------------------------------------------------------------ state
    def store(self):
        return Store(self.data_dir / "state.json")  # re-read every time: the background process updates tokens on its own

    def config(self):
        """Current configuration from .env (raises Fatal if the file is invalid)."""
        return settings.validate(self.data_dir, {})

    def snapshot(self):
        """Everything the window shows. Reads small local files only (no network), so it is cheap enough to call every second."""
        problem = None
        try:
            cfg = self.config()
        except Fatal as e:
            cfg, problem = self.cfg0, str(e).splitlines()[0]
        st = self.store()
        frozen = bool(getattr(sys, "frozen", False))
        gh_user = st.get("github_user") if st.get("github_token") else ""
        fx_token, _ = st.fluxer_token(cfg)
        fx_user = st.get("fluxer_user") or ""
        client_id = cfg.client_id or st.get("client_id") or ""
        pid = background.running_pid(self.data_dir)
        spotify = Account(bool(st.get("refresh") and client_id), "")
        fluxer = Account(bool(fx_token), fx_user)
        github = Account(bool(st.get("github_token")), gh_user or "")
        defaults = settings.default_lines(github.connected)
        lines = tuple(cfg.lines)
        if github.connected and not cfg.lines_explicit:  # same rule as cli.Ctx: connecting GitHub adds its lines unless STATUS_LINES is set
            lines += tuple(n for n in GH_DEFAULT_LINES if n not in lines)
        sup = autostart.available()
        snap_next = None
        if not spotify.connected:
            snap_next = "spotify"
        elif not (fluxer.connected or cfg.webhook):
            snap_next = "fluxer"
        elif not github.connected and not st.get("github_asked"):
            snap_next = "github"
        elif pid is None:
            snap_next = "start"
        return Snapshot(
            version=__version__, data_dir=self.data_dir, exe=self._exe, frozen=frozen, exe_hint=self.exe_hint(),
            pid=pid, attention=background.read_attention(self.data_dir), problem=problem,
            spotify=spotify, fluxer=fluxer, github=github, webhook=bool(cfg.webhook), client_id=client_id,
            autostart_supported=sup, autostart_on=bool(sup and autostart.installed()),
            autostart_current=bool(sup and autostart.matches(self.data_dir)), autostart_blocked=bool(sup and autostart.disabled_by_user()),
            lines=lines, default_lines=defaults,
            show_when_idle=cfg.on_idle == "lines", show_on_pause=cfg.on_pause == "stats",
            rotate=int(cfg.rotate), ttl_on=cfg.ttl > 0, next_step=snap_next,
        )

    def exe_hint(self):
        """A warning if the exe sits in a place where it is likely to disappear (autostart would then point at nothing)."""
        if not getattr(sys, "frozen", False):
            return ""
        low = str(self._exe).lower().replace("/", "\\")
        for part, de, en in (("\\downloads\\", "im Downloads-Ordner", "in the Downloads folder"), ("\\temp\\", "in einem Temp-Ordner", "in a temp folder")):
            if part in low:
                return bi(f"Die Exe liegt {de}. Lege sie vor dem Autostart an einen festen Ort (z. B. C:\\Programme\\Fluxer-Spotify), sonst verschwindet der Autostart, wenn du sie loeschst.",
                          f"The exe is {en}. Move it somewhere permanent (e.g. C:\\Programs\\Fluxer-Spotify) before enabling autostart, or autostart breaks when you delete it.")
        return ""

    # ------------------------------------------------------------------ run / stop
    def start(self):
        """Start the hidden background process (and make the one-time 'show me everything' defaults). Returns its PID or None."""
        self.apply_first_run_defaults()
        pid = background.running_pid(self.data_dir)
        if pid is not None:
            return pid
        background.clear_attention(self.data_dir)
        background.clear_stop(self.data_dir)
        return background.spawn_background(self.data_dir)

    def stop(self):
        """Ask the background process to end (it clears the Fluxer status). Returns background.stop_instance()'s result."""
        res = background.stop_instance(self.data_dir)
        if res == "killed":  # it could not clear the status itself
            self._clear_status()
        return res

    def restart(self):
        self.stop()
        return self.start()

    def _clear_status(self):
        try:
            cfg = self.config()
            token, source = self.store().fluxer_token(cfg)
            if token:
                FluxerClient(self.http, cfg.api, token, source).set_status(None)
        except (Fatal, HttpError, NetworkError) as e:
            log.warning("Could not clear status: %s", e)

    def apply_first_run_defaults(self):
        """The first time the program is started from the window, switch on the 'show everything' options (once, never overwriting)."""
        st = self.store()
        if st.get("launcher_configured"):
            return
        have = settings.read_env(self.data_dir)
        changes = {k: v for k, v in FIRST_RUN_DEFAULTS.items() if k not in have}
        if changes:
            settings.apply(self.data_dir, changes)
        st.update(launcher_configured=True)

    # ------------------------------------------------------------------ autostart
    def set_autostart(self, on):
        if on:
            return autostart.install(self.data_dir)
        return autostart.uninstall()

    # ------------------------------------------------------------------ logins
    def spotify_login(self, client_id, open_browser=webbrowser.open, notify=print, cancel=None):
        cid = (client_id or "").strip().strip("\"'").lower()
        if not wizard.valid_client_id(cid):
            raise Fatal(bi("Die Client ID besteht aus genau 32 Zeichen (0-9, a-f). Du findest sie in den Einstellungen deiner Spotify-App.",
                           "The Client ID is exactly 32 characters (0-9, a-f). You find it in your Spotify app's settings."))
        st = self.store()
        fresh = st.get("client_id") != cid
        st.update(client_id=cid)
        try:
            SpotifyClient(self.http, st, cid).login(open_browser=open_browser, notify=notify, cancel=cancel)
        except Fatal:
            if fresh:  # the ID we just stored may be the culprit
                st.clear(("client_id",))
            raise

    def fluxer_login(self, email, password, ask_code, notify=print):
        """Returns the account name. The password is used for exactly one request and never stored or logged."""
        cfg = self.config()
        email = (email or "").strip()
        if not email or not password:
            raise Fatal(bi("Bitte E-Mail und Passwort eingeben.", "Please enter e-mail and password."))
        logmod.add_secret(password)
        try:
            res = fluxer_login_flow(self.http, cfg.api, email, password, ask_code, notify=notify)
        finally:
            del password
        logmod.add_secret(res["token"])
        user = res["user"].get("username")
        self.store().update(fluxer_token=res["token"], fluxer_token_source="login", fluxer_user=user)
        return res["user"].get("global_name") or user or "?"

    def fluxer_token(self, token):
        """Fallback for accounts that cannot use the password login (SSO, passkey only): a token pasted from the browser."""
        cfg = self.config()
        token = (token or "").strip().strip("\"'")
        if not token:
            raise Fatal(bi("Kein Token eingegeben.", "No token entered."))
        logmod.add_secret(token)
        me = FluxerClient(self.http, cfg.api, token, "manual").me()  # validates before storing
        self.store().update(fluxer_token=token, fluxer_token_source="manual", fluxer_user=me.get("username"))
        return me.get("username", "?")

    def github_connect(self, token):
        logmod.add_secret((token or "").strip())
        st = self.store()
        login = github_mod.connect(self.http, st, token)
        st.update(github_asked=True)
        return login

    def github_skip(self):
        self.store().update(github_asked=True)

    def github_disconnect(self):
        st = self.store()
        github_mod.disconnect(st)
        st.update(github_asked=True)

    def fluxer_disconnect(self):
        """End the Fluxer session (if this program created it) and forget the token."""
        st = self.store()
        cfg = self.config()
        token, source = st.fluxer_token(cfg)
        if token:
            fx = FluxerClient(self.http, cfg.api, token, source)
            try:
                fx.set_status(None)
                if source == "login" and not cfg.fluxer_token:
                    fx.logout()
            except (Fatal, HttpError, NetworkError) as e:
                log.warning("Fluxer logout: %s", e)
        st.clear(FLUXER_KEYS)

    def spotify_disconnect(self):
        self.store().clear(SPOTIFY_KEYS)

    # ------------------------------------------------------------------ checks, settings
    def check(self):
        """Live checks of the three connections (network). Returns a list of Check."""
        out = []
        cfg = self.config()
        st = self.store()
        cid = cfg.client_id or st.get("client_id")
        if st.get("refresh") and cid:
            try:
                SpotifyClient(self.http, st, cid).refresh()
                out.append(Check("Spotify", True, bi("Login funktioniert", "Login works")))
            except AuthError as e:
                out.append(Check("Spotify", False, str(e).splitlines()[0]))
            except (HttpError, NetworkError) as e:
                out.append(Check("Spotify", None, bi(f"Nicht erreichbar: {e}", f"Unreachable: {e}")))
        else:
            out.append(Check("Spotify", False, bi("Nicht verbunden", "Not connected")))
        token, source = st.fluxer_token(cfg)
        if token:
            try:
                me = FluxerClient(self.http, cfg.api, token, source).me()
                out.append(Check("Fluxer", True, bi(f"Angemeldet als {me.get('username', '?')}", f"Logged in as {me.get('username', '?')}")))
            except AuthError as e:
                out.append(Check("Fluxer", False, str(e).splitlines()[0]))
            except (HttpError, NetworkError) as e:
                out.append(Check("Fluxer", None, bi(f"Nicht erreichbar: {e}", f"Unreachable: {e}")))
        else:
            out.append(Check("Fluxer", None if cfg.webhook else False,
                             bi("Nur Webhook-Betrieb", "Webhook-only operation") if cfg.webhook else bi("Nicht verbunden", "Not connected")))
        gh = st.get("github_token")
        if gh:
            try:
                login = github_mod.GitHubClient(self.http, gh).me()
                out.append(Check("GitHub", True, bi(f"Verbunden als {login}", f"Connected as {login}")))
            except AuthError as e:
                out.append(Check("GitHub", False, str(e).splitlines()[0]))
            except (HttpError, NetworkError) as e:
                out.append(Check("GitHub", None, bi(f"Nicht erreichbar: {e}", f"Unreachable: {e}")))
        else:
            out.append(Check("GitHub", None, bi("Nicht verbunden (optional)", "Not connected (optional)")))
        return out

    def save_settings(self, lines, show_when_idle, show_on_pause, rotate, ttl_on):
        """Write the display options into .env (validated first). Returns the new Config; restart the background process to apply."""
        gh = bool(self.store().get("github_token"))
        selected = [n for n in lines if n in LINE_NAMES]
        if not selected:
            raise Fatal(bi("Waehle mindestens eine Zeile aus.", "Select at least one line."))
        if not gh and all(n in GH_LINES for n in selected):
            raise Fatal(bi("Es sind nur GitHub-Zeilen gewaehlt, aber GitHub ist nicht verbunden.", "Only GitHub lines are selected, but GitHub is not connected."))
        changes = {
            "STATUS_LINES": settings.lines_value(selected, gh),
            "ON_IDLE": "lines" if show_when_idle else None,
            "ON_PAUSE": "stats" if show_on_pause else None,
            "ROTATE_SECONDS": None if int(rotate) == DEFAULT_ROTATE else str(int(rotate)),
            "STATUS_TTL": TTL_ON if ttl_on else None,
        }
        return settings.apply(self.data_dir, changes)

    # ------------------------------------------------------------------ housekeeping
    def log_text(self, n=200):
        lines = background.tail(self.data_dir / background.LOG_NAME, n)
        return "\n".join(lines) if lines else bi("Noch kein Log vorhanden.", "No log yet.")

    def open_data_dir(self):
        if os.name == "nt":
            os.startfile(str(self.data_dir))  # noqa: S606 - opens the user's own folder in Explorer

    def uninstall(self):
        """Stop, remove autostart, log out of everything and delete the program's data. The exe itself stays (delete it by hand)."""
        self.stop()
        if autostart.available():
            autostart.uninstall()
        from . import cli  # lazy: cli imports this module's window lazily
        ctx = cli.Ctx(self.config(), self.http, None, None)
        ctx.logout(types.SimpleNamespace(keep_spotify=False))
        root = logging.getLogger("fluxer_spotify")
        for h in list(root.handlers):  # Windows cannot delete an open log file
            h.close()
            root.removeHandler(h)
        n = background.LOG_NAME
        for name in ("state.json", "state.json.corrupt", ".env", n, n + ".1", n + ".2", background.PID_NAME, background.STOP_NAME, background.ATTN_NAME):
            try:
                (self.data_dir / name).unlink()
            except OSError:
                pass
        try:
            self.data_dir.rmdir()  # only succeeds when empty
        except OSError:
            pass

"""First-run setup wizard: fills in whatever is missing, step by step, then returns so the loop can start.

Order: Spotify Client ID -> Spotify login -> Fluxer login -> (once) autostart offer. Done steps are skipped;
an invalid/expired token re-triggers only its own step.
"""
import re

from . import autostart
from .errors import AuthError, Fatal, LoginError, bi
from .store import FLUXER_KEYS, SPOTIFY_KEYS

DASHBOARD = "https://developer.spotify.com/dashboard"
CLIENT_ID_RE = re.compile(r"[0-9a-fA-F]{32}")
YES = ("j", "ja", "y", "yes")


def valid_client_id(s):
    return bool(CLIENT_ID_RE.fullmatch(s))


def setup(ctx, tries=5):
    """Run all steps. `ctx` is cli.Ctx (cfg, store, http, input, open_browser, spotify(), fluxer_login(), ...)."""
    fresh = _client_id(ctx, tries)
    try:
        _spotify(ctx)
    except Fatal:
        if fresh:  # the ID we just stored may be the culprit: ask again next time
            ctx.store.clear(("client_id",))
        raise
    _fluxer(ctx, tries)
    _autostart(ctx)


def _client_id(ctx, tries):
    """Returns True when the ID was entered just now."""
    if ctx.cfg.client_id:
        return False
    print(bi("\nSchritt 1: Spotify-App (einmalig, kostenlos, dauert 2 Minuten).\n"
             f"  1. Im Browser {DASHBOARD} oeffnen, anmelden, \"Create app\" waehlen.\n"
             "  2. Bei \"Redirect URI\" genau eintragen: http://127.0.0.1:8888/callback  (dann \"Add\" und speichern)\n"
             "  3. In den App-Einstellungen die \"Client ID\" kopieren und hier einfuegen.",
             "\nStep 1: Spotify app (one time, free, 2 minutes).\n"
             f"  1. Open {DASHBOARD} in your browser, log in, choose \"Create app\".\n"
             "  2. As \"Redirect URI\" enter exactly: http://127.0.0.1:8888/callback  (click \"Add\" and save)\n"
             "  3. In the app settings copy the \"Client ID\" and paste it here."))
    try:
        ctx.open_browser(DASHBOARD)
    except Exception:
        pass  # the URL is printed above anyway
    for _ in range(tries):
        cid = _ask(ctx, "Client ID (leer = Abbruch / empty = cancel): ").strip().strip("\"'")
        if not cid:
            raise Fatal(bi("Abgebrochen: ohne Client ID geht es nicht.", "Cancelled: a Client ID is required."))
        if valid_client_id(cid):
            ctx.cfg.client_id = cid.lower()
            ctx.store.update(client_id=ctx.cfg.client_id)
            print(bi("Client ID gespeichert.", "Client ID saved."))
            return True
        print(bi("Das sieht nicht richtig aus: Die Client ID besteht aus genau 32 Zeichen (0-9, a-f). Nochmal versuchen.",
                 "That does not look right: the Client ID is exactly 32 characters (0-9, a-f). Try again."))
    raise Fatal(bi("Zu viele ungueltige Eingaben.", "Too many invalid entries."))


def _spotify(ctx):
    sp = ctx.spotify()
    if ctx.store.get("refresh"):
        try:
            sp.refresh()  # live check; network errors propagate (we cannot judge the login then)
            return
        except AuthError:
            print(bi("Spotify-Anmeldung ist abgelaufen. Bitte neu anmelden.", "Your Spotify login expired. Please log in again."))
            ctx.store.clear(SPOTIFY_KEYS)
    print(bi("\nSchritt 2: Bei Spotify anmelden. Der Browser oeffnet sich, bitte \"Zustimmen\" klicken.",
             "\nStep 2: Log in to Spotify. Your browser opens, please click \"Agree\"."))
    sp.login(open_browser=ctx.open_browser)
    print(bi("Spotify-Login ok.", "Spotify login ok."))


def _fluxer(ctx, tries):
    fx = ctx.fluxer()
    if fx:
        try:
            fx.me()
            return
        except AuthError:
            if ctx.cfg.fluxer_token:  # from flag/env/.env: we must not silently replace it
                raise
            print(bi("Fluxer-Anmeldung ist abgelaufen. Bitte neu anmelden.", "Your Fluxer login expired. Please log in again."))
            ctx.store.clear(FLUXER_KEYS)
    elif ctx.cfg.webhook:
        return  # webhook-only operation needs no login
    print(bi("\nSchritt 3: Bei Fluxer anmelden. Dein Passwort wird nur einmal gesendet und nicht gespeichert.",
             "\nStep 3: Log in to Fluxer. Your password is sent once and is not stored."))
    for _ in range(tries):
        try:
            ctx.fluxer_login(None)
            return
        except LoginError as e:
            print(f"\n{e}\n")
        choice = _ask(ctx, "[Enter] nochmal versuchen / retry, t = Token einfuegen / paste token, q = Abbruch / quit: ").strip().lower()
        if choice == "q":
            raise Fatal(bi("Abgebrochen.", "Cancelled."))
        if choice == "t":
            ctx.fluxer_token()
            return
    raise Fatal(bi("Fluxer-Login nicht moeglich.", "Fluxer login not possible."))


def _autostart(ctx):
    if ctx.store.get("autostart_asked") or not autostart.available() or autostart.installed():
        return
    ans = _ask(ctx, bi("\nSoll das Programm automatisch mit Windows starten? (j/n): ",
                       "Start automatically with Windows? (y/n): ")).strip().lower()
    ctx.store.update(autostart_asked=True)
    if ans in YES:
        ctx.autostart(True)


def _ask(ctx, prompt):
    try:
        return ctx.input(prompt)
    except EOFError:
        raise Fatal(bi("Keine Eingabe moeglich (kein interaktives Fenster).", "No input possible (not an interactive window).")) from None

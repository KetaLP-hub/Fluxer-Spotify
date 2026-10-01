"""First-run setup wizard: fills in whatever is missing, step by step, then returns so the loop can start.

Order: language (only if never chosen) -> Spotify Client ID -> Spotify login -> Fluxer login -> (once) autostart offer. Done steps are skipped;
an invalid/expired token re-triggers only its own step.
"""
import re

from . import autostart, background
from .errors import LANGS, AuthError, Fatal, LoginError, bi, detect_lang, set_lang
from .store import FLUXER_KEYS, SPOTIFY_KEYS

DASHBOARD = "https://developer.spotify.com/dashboard"
CLIENT_ID_RE = re.compile(r"[0-9a-fA-F]{32}")
YES = ("j", "ja", "y", "yes")


def valid_client_id(s):
    return bool(CLIENT_ID_RE.fullmatch(s))


def setup(ctx, tries=5, interactive=True):
    """Run all steps. Returns True when the program was handed over to a hidden background process (caller must exit).
    interactive=False (background mode) skips the closing offers; missing steps still fail via ctx.input. `ctx` is cli.Ctx (cfg, store, http, input, open_browser, spotify(), fluxer_login(), ...)."""
    if interactive and not ctx.cfg.language:
        _language(ctx)
    fresh = _client_id(ctx, tries)
    try:
        _spotify(ctx)
    except Fatal:
        if fresh:  # the ID we just stored may be the culprit: ask again next time
            ctx.store.clear(("client_id",))
        raise
    _fluxer(ctx, tries)
    if interactive and not ctx.cfg.no_rotate and not ctx.store.get("rotation_noted"):
        n = f"{ctx.cfg.rotate:g}"
        print(bi(f"Tipp: Der Status wechselt alle {n} s zwischen Titel, Playlist, Top-Artist und Hoerzeit; aendern mit --lines / --rotate / --no-rotate (siehe README).",
                 f"Tip: the status rotates every {n} s between track, playlist, top artist and listening time; change it with --lines / --rotate / --no-rotate (see README)."))
        ctx.store.update(rotation_noted=True)
    return interactive and _finish(ctx)


LANG_NAMES = {"de": "Deutsch", "en": "English"}


def _language(ctx):
    """Step 0, only when no language is configured/stored: Enter accepts the detected one. Prompt is deliberately bilingual."""
    guess = detect_lang()
    other = "en" if guess == "de" else "de"
    ans = _ask(ctx, f"\nSprache / Language: [Enter] = {LANG_NAMES[guess]}, {other[0]} = {LANG_NAMES[other]}: ").strip().lower()
    chosen = other if ans in (other, other[0], LANG_NAMES[other].lower()) else guess
    ctx.cfg.language = chosen
    ctx.store.update(language=chosen)
    set_lang(chosen)
    print(bi(f"Sprache: {LANG_NAMES[chosen]} (aendern mit --lang oder LANGUAGE in .env).",
             f"Language: {LANG_NAMES[chosen]} (change with --lang or LANGUAGE in .env)."))


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
        cid = _ask(ctx, bi("Client ID (leer = Abbruch): ", "Client ID (empty = cancel): ")).strip().strip("\"'")
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
        choice = _ask(ctx, bi("[Enter] nochmal versuchen, t = Token einfuegen, q = Abbruch: ", "[Enter] retry, t = paste token, q = quit: ")).strip().lower()
        if choice == "q":
            raise Fatal(bi("Abgebrochen.", "Cancelled."))
        if choice == "t":
            ctx.fluxer_token()
            return
    raise Fatal(bi("Fluxer-Login nicht moeglich.", "Fluxer login not possible."))


def notice():
    return bi(
    "\nWICHTIG: Dieses Programm laeuft dauerhaft im Hintergrund und aktualisiert deinen Fluxer-Status, solange es laeuft.\n"
    "  - Beenden: \"Fluxer-Spotify.exe stop\" (oder im Task-Manager den Prozess \"Fluxer-Spotify.exe\" beenden).\n"
    "  - Komplett entfernen: \"Fluxer-Spotify.exe uninstall\" (Autostart, Login, gespeicherte Daten).\n"
    "  - Protokoll: \"Fluxer-Spotify.exe logs\".",
    "\nIMPORTANT: This program keeps running in the background and updates your Fluxer status for as long as it runs.\n"
    "  - Stop it: \"Fluxer-Spotify.exe stop\" (or end the \"Fluxer-Spotify.exe\" process in Task Manager).\n"
    "  - Remove everything: \"Fluxer-Spotify.exe uninstall\" (autostart, login, stored data).\n"
    "  - Log: \"Fluxer-Spotify.exe logs\".")


def _finish(ctx):
    """Closing offers, each asked once: autostart (starts hidden), then 'hide this window and continue in the background'."""
    ask_auto = not (ctx.store.get("autostart_asked") or not autostart.available() or autostart.installed())
    ask_bg = background.available() and not ctx.store.get("background_asked")
    if not (ask_auto or ask_bg):
        return False
    print(notice())
    if ask_auto:
        ans = _ask(ctx, bi("\nSoll das Programm automatisch (unsichtbar) mit Windows starten? (j/n): ",
                           "Start automatically (hidden) with Windows? (y/n): ")).strip().lower()
        ctx.store.update(autostart_asked=True)
        if ans in YES:
            ctx.autostart(True)
    if not ask_bg:
        return False
    ans = _ask(ctx, bi("\nFenster jetzt verstecken und im Hintergrund weiterlaufen? (j/n): ",
                       "Hide this window now and continue in the background? (y/n): ")).strip().lower()
    ctx.store.update(background_asked=True)
    return ans in YES and ctx.start_background()


def _ask(ctx, prompt):
    try:
        return ctx.input(prompt)
    except EOFError:
        raise Fatal(bi("Keine Eingabe moeglich (kein interaktives Fenster).", "No input possible (not an interactive window).")) from None

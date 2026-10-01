"""Windows autostart via a launcher script in the user's Startup folder (no admin rights needed)."""
import os
import sys
from pathlib import Path

from .errors import Fatal, bi

NAME = "Fluxer Spotify Status.cmd"


def startup_dir():
    appdata = os.environ.get("APPDATA")
    if os.name != "nt" or not appdata:
        raise Fatal(bi("Autostart-Hilfe gibt es nur unter Windows.", "The autostart helper is Windows-only."))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def available():
    return os.name == "nt" and bool(os.environ.get("APPDATA"))


def installed():
    return (startup_dir() / NAME).exists()


def launcher_text(root, python, log_file, frozen=None):
    if frozen is None:
        frozen = getattr(sys, "frozen", False)
    if frozen:  # python is the exe itself (sys.executable); it is a console app, so start it minimised
        return (f'@echo off\r\ncd /d "{root}"\r\nstart "" /min "{python}" run --log-file "{log_file}"\r\n')
    pyw = Path(python).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(python)
    flag = "" if pyw.exists() else "/min "  # pythonw has no console window; plain python gets a minimised one
    return (f'@echo off\r\ncd /d "{root}"\r\nstart "" {flag}"{exe}" -m fluxer_spotify run --log-file "{log_file}"\r\n')


def install(root):
    root = Path(root).resolve()
    target = startup_dir() / NAME
    target.write_text(launcher_text(root, sys.executable, root / "fluxer-spotify.log"), encoding="utf-8")
    return target


def uninstall():
    target = startup_dir() / NAME
    if target.exists():
        target.unlink()
        return target
    return None

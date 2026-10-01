"""Windows autostart via a launcher script in the user's Startup folder (no admin rights needed)."""
import os
import subprocess
from pathlib import Path

from .errors import Fatal, bi

NAME = "Fluxer Spotify Status.vbs"
OLD_NAME = "Fluxer Spotify Status.cmd"  # v2 launcher (visible console window); replaced on install


def startup_dir():
    appdata = os.environ.get("APPDATA")
    if os.name != "nt" or not appdata:
        raise Fatal(bi("Autostart-Hilfe gibt es nur unter Windows.", "The autostart helper is Windows-only."))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def available():
    return os.name == "nt" and bool(os.environ.get("APPDATA"))


def installed():
    return any((startup_dir() / n).exists() for n in (NAME, OLD_NAME))


def launcher_text(argv, cwd):
    """VBScript: wscript runs without any console and Run(..., 0) starts the program in a hidden window."""
    q = lambda t: str(t).replace('"', '""')
    cmd = subprocess.list2cmdline([str(a) for a in argv])
    return (f'Set s = CreateObject("WScript.Shell")\r\n'
            f's.CurrentDirectory = "{q(cwd)}"\r\n'
            f's.Run "{q(cmd)}", 0, False\r\n')


def install(data_dir):
    from . import background
    argv, cwd = background.background_command(data_dir)
    target = startup_dir() / NAME
    target.write_text(launcher_text(argv, cwd), encoding="utf-8", newline="")
    (startup_dir() / OLD_NAME).unlink(missing_ok=True)
    return target


def uninstall():
    removed = None
    for n in (NAME, OLD_NAME):
        t = startup_dir() / n
        if t.exists():
            t.unlink()
            removed = t
    return removed

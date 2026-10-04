"""Windows autostart: one value in the user's Run key (HKCU, no admin rights needed).

Earlier versions dropped a VBScript launcher into the Startup folder. That is gone on purpose: a hidden `wscript` launcher
is exactly what antivirus heuristics flag, and Windows is retiring VBScript. A Run entry that starts the exe directly is the
standard, transparent way (it shows up in Task Manager > Startup apps, where the user can also switch it off).
Old launcher files are removed when the new entry is installed.
"""
import os
import subprocess
import sys
from pathlib import Path

from .errors import Fatal, bi

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"  # Task Manager's on/off switch
VALUE = "Fluxer-Spotify"
LEGACY = ("Fluxer Spotify Status.vbs", "Fluxer Spotify Status.cmd")  # v2 launchers in the Startup folder


def _winreg():  # indirection so tests can swap in a fake registry
    import winreg
    return winreg


def startup_dir():
    appdata = os.environ.get("APPDATA")
    if os.name != "nt" or not appdata:
        raise Fatal(bi("Autostart-Hilfe gibt es nur unter Windows.", "The autostart helper is Windows-only."))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def available():
    return os.name == "nt"


def command_line(data_dir, frozen=None, executable=None):
    """The exact command Windows runs at login: this program, hidden, with an explicit data folder."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = executable or sys.executable
    tail = ["run", "--background", "--data-dir", str(data_dir)]
    if frozen:
        return subprocess.list2cmdline([exe, *tail])
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")  # source run: no console window
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spotify_status.py")
    return subprocess.list2cmdline([pyw if os.path.exists(pyw) else exe, script, *tail])


def current():
    """The command registered in the Run key, or None."""
    if not available():
        return None
    reg = _winreg()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            value, _ = reg.QueryValueEx(key, VALUE)
    except OSError:
        return None
    return value if isinstance(value, str) else None


def _legacy_files():
    try:
        return [p for p in (startup_dir() / n for n in LEGACY) if p.exists()]
    except Fatal:
        return []


def installed():
    return current() is not None or bool(_legacy_files())


def matches(data_dir, **kw):
    """True when the registered command is exactly what install() would write now (False after the exe was moved)."""
    return current() == command_line(data_dir, **kw)


def disabled_by_user():
    """True when the user switched the entry off in Task Manager > Startup apps (Windows keeps that on/off flag separately)."""
    if not available():
        return False
    reg = _winreg()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, APPROVED_KEY, 0, reg.KEY_READ) as key:
            data, _ = reg.QueryValueEx(key, VALUE)
    except OSError:
        return False
    return bool(data) and bool(data[0] & 1)  # 0x02/0x06 = enabled, 0x03/0x07 = disabled


def install(data_dir):
    """Register the autostart entry (and drop old launcher files). Returns a short description of where it lives."""
    if not available():
        raise Fatal(bi("Autostart-Hilfe gibt es nur unter Windows.", "The autostart helper is Windows-only."))
    reg = _winreg()
    with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
        reg.SetValueEx(key, VALUE, 0, reg.REG_SZ, command_line(data_dir))
    for p in _legacy_files():
        try:
            p.unlink()
        except OSError:
            pass
    return f"HKEY_CURRENT_USER\\{RUN_KEY}\\{VALUE}"


def uninstall():
    """Remove the entry and any old launcher files. Returns what was removed (a string) or None."""
    removed = None
    if available():
        reg = _winreg()
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                reg.DeleteValue(key, VALUE)
            removed = f"HKEY_CURRENT_USER\\{RUN_KEY}\\{VALUE}"
        except OSError:
            pass
    for p in _legacy_files():
        try:
            p.unlink()
            removed = str(p)
        except OSError:
            pass
    return removed

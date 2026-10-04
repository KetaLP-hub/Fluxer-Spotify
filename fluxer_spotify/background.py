"""Background (hidden) mode: console hiding, single-instance pid lock, stop request, detached self-spawn, notices.

Windows bits use stdlib ctypes only. Everything OS-specific is isolated in small functions so tests can mock it.
"""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path, PureWindowsPath

from .errors import Fatal, bi

log = logging.getLogger("fluxer_spotify.bg")
LOG_NAME = "fluxer-spotify.log"
PID_NAME = "fluxer-spotify.pid"
STOP_NAME = "fluxer-spotify.stop"  # `stop` drops this file; the running loop sees it and shuts down cleanly
ATTN_NAME = ".needs-attention"  # marker: the one-time "please fix me" notice was already shown
PROCESS_NAME = "Fluxer-Spotify.exe"
CREATE_NO_WINDOW, DETACHED_PROCESS = 0x08000000, 0x00000008
SW_HIDE = 0


class AlreadyRunning(Fatal):
    def __init__(self, pid):
        self.pid = pid
        super().__init__(bi(f"Laeuft bereits im Hintergrund (PID {pid}). Beenden: {PROCESS_NAME} stop",
                            f"Already running (PID {pid}). Stop it with: {PROCESS_NAME} stop"))


def available():
    return os.name == "nt"


# --- console / streams -------------------------------------------------------------------------------------------
def hide_console(frozen=None):
    """Hide our console window (also covers Task Scheduler / shortcuts that start us minimised).

    Never hides a console shared with a terminal (cmd.exe, PowerShell): that would hide the user's own window.
    ponytail: shared-console detection is a process count heuristic; a onefile exe has a bootloader + child, so 2.
    Returns True when the window was hidden.
    """
    if os.name != "nt":
        return False
    import ctypes
    k32 = ctypes.windll.kernel32
    hwnd = k32.GetConsoleWindow()
    if not hwnd:
        return False  # no console at all (started detached / pythonw): nothing to hide
    if frozen is None:
        frozen = getattr(sys, "frozen", False)
    buf = (ctypes.c_uint * 8)()
    if k32.GetConsoleProcessList(buf, 8) > (2 if frozen else 1):
        log.warning(bi("Konsole wird mit einem Terminal geteilt, nicht versteckt.", "Console shared with a terminal, not hidden.", " / "))
        return False
    ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)
    return True


def attach_parent_console():
    """Windowed exe started from cmd/PowerShell with arguments: print into that terminal.

    A windowed exe has no console and sys.stdout/stderr/stdin are None. Attaching to the parent's console makes
    `Fluxer-Spotify.exe stop`, `status`, `logs` and `--version` show their output. Streams that were redirected
    (> file, | more) are left alone. Returns True when attached.
    """
    if os.name != "nt":
        return False
    import ctypes
    if not ctypes.windll.kernel32.AttachConsole(0xFFFFFFFF):  # ATTACH_PARENT_PROCESS
        return False
    for name, mode, device in (("stdout", "w", "CONOUT$"), ("stderr", "w", "CONOUT$"), ("stdin", "r", "CONIN$")):
        if getattr(sys, name) is None:
            try:
                setattr(sys, name, open(device, mode, encoding="utf-8", errors="replace"))
            except OSError:
                pass
    return True


def fix_streams():
    """Without a console sys.stdout/stderr are None (pythonw, CREATE_NO_WINDOW): give print() a harmless sink."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def notify_once(data_dir, text, title="Fluxer Spotify", messagebox=None):
    """One Windows MessageBox per problem; the marker is removed again once the loop runs fine.

    The marker holds the message text, so the launcher window can show the same hint without a pop-up.
    """
    marker = Path(data_dir) / ATTN_NAME
    no_popup = bool(os.environ.get("FLUXER_SPOTIFY_NO_POPUP"))  # automation / tests: the launcher window shows the same hint
    if marker.exists() or (messagebox is None and not no_popup and os.name != "nt"):
        return False
    try:
        marker.write_text(text, encoding="utf-8")
    except OSError:
        pass
    if messagebox is None:
        if no_popup:
            return True
        import ctypes
        messagebox = lambda t, c: ctypes.windll.user32.MessageBoxW(0, c, t, 0x40 | 0x40000)  # information icon, topmost
    messagebox(title, text)
    return True


def read_attention(data_dir):
    """The text of the pending 'please fix me' hint, or None."""
    try:
        text = (Path(data_dir) / ATTN_NAME).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or "?"


def clear_attention(data_dir):
    try:
        (Path(data_dir) / ATTN_NAME).unlink()
    except OSError:
        pass


# --- single instance -----------------------------------------------------------------------------------------------
def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied = exists
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)  # never on Windows: signal 0 would be a CTRL_C_EVENT there
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_image(pid):
    """What is running under this PID? Windows: the exe path; Linux: the command line. None = cannot tell."""
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_uint(len(buf))
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return None
            return buf.value
        finally:
            k32.CloseHandle(h)
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return None


def is_ours(pid, image=None):
    """True: this PID is (still) this program. False: some other program has that PID now, so a pid file naming it is stale.
    None: cannot tell (no permission, unsupported OS).

    PIDs are reused quickly. Without this check a stale pid file could make us believe we are already running, and
    `stop` could terminate an unrelated process after its 20 second wait.
    """
    img = (image or process_image)(pid)
    if not img:
        return None
    if os.name == "nt":
        name = PureWindowsPath(img).name.lower()
        own = {PROCESS_NAME.lower(), PureWindowsPath(sys.executable).name.lower()}
        return name in own or name.startswith("python") or name == "py.exe"  # the latter: running from source (also Store python3.13.exe)
    return "fluxer_spotify" in img or "spotify_status" in img


def read_pid(data_dir):
    try:
        return int((Path(data_dir) / PID_NAME).read_text().strip())
    except (OSError, ValueError):
        return None


def running_pid(data_dir):
    """PID of a live instance, else None. A stale pid file (dead process) is removed on the way.

    ponytail: a reused PID after a crash reads as "running"; `stop` then times out. Add a start-time check if it bites.
    """
    path = Path(data_dir) / PID_NAME
    pid = read_pid(data_dir)
    if pid == os.getpid() or (pid is not None and pid_alive(pid) and is_ours(pid) is not False):
        return pid
    try:
        if pid is not None or path.stat().st_size:  # dead pid or garbage; an empty file is a lock being written right now
            path.unlink()
    except OSError:
        pass
    return None


class InstanceLock:
    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.path = self.dir / PID_NAME
        self.held = False

    def acquire(self):
        for _ in range(3):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                pid = running_pid(self.dir)
                if pid is not None:
                    raise AlreadyRunning(pid)
                continue  # stale file was removed: retry
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            self.held = True
            try:
                (self.dir / STOP_NAME).unlink()  # a leftover stop request must not kill the new instance
            except OSError:
                pass
            return self
        raise Fatal(bi("Sperrdatei nicht anlegbar.", "Could not create the lock file."))

    def release(self):
        if self.held:
            self.held = False
            try:
                self.path.unlink()
            except OSError:
                pass

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()


def stop_requested(data_dir):
    return (Path(data_dir) / STOP_NAME).exists()


def clear_stop(data_dir):
    try:
        (Path(data_dir) / STOP_NAME).unlink()
    except OSError:
        pass


def stop_instance(data_dir, wait=20, sleep=time.sleep, kill=None):
    """Ask the running instance to shut down via its normal path (it clears the Fluxer status).

    Returns "none" (nothing running), "clean" (exited by itself), "killed" (had to be terminated; status NOT cleared) or
    "unresponsive" (did not react and we cannot be sure the PID is still ours, so nothing was terminated).
    """
    pid = running_pid(data_dir)
    if pid is None:
        return "none"
    (Path(data_dir) / STOP_NAME).write_text("1")
    for _ in range(int(wait * 2)):
        if not pid_alive(pid):
            break
        sleep(0.5)
    else:
        if is_ours(pid) is not True:
            clear_stop(data_dir)
            return "unresponsive"
        (kill or _kill)(pid)
        clear_stop(data_dir)
        try:
            (Path(data_dir) / PID_NAME).unlink()
        except OSError:
            pass
        return "killed"
    clear_stop(data_dir)
    return "clean"


def _kill(pid):
    import signal
    os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows


def make_stop_sleep(data_dir, sleep=time.sleep, stop_exc=None, clock=time.monotonic):
    """A sleep() that wakes every second to look for a stop request; raises stop_exc to unwind the main loop."""
    def stoppable(seconds):
        end = clock() + seconds
        while True:
            if stop_requested(data_dir):
                raise stop_exc()
            left = end - clock()
            if left <= 0:
                return
            sleep(min(1.0, left))
    return stoppable


# --- detached self-spawn ------------------------------------------------------------------------------------------
def background_command(data_dir, extra=(), frozen=None, executable=None):
    """(argv, cwd) that starts this program hidden. Frozen exe: itself. Source: pythonw (no console) if present."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = executable or sys.executable
    tail = ["run", "--background", "--data-dir", str(data_dir), *extra]
    if frozen:
        return [exe, *tail], str(Path(exe).parent)
    pyw = Path(exe).with_name("pythonw.exe")
    return [str(pyw) if pyw.exists() else exe, "-m", "fluxer_spotify", *tail], str(Path(__file__).resolve().parent.parent)


def spawn_background(data_dir, extra=(), popen=subprocess.Popen, frozen=None, executable=None, wait=15, sleep=time.sleep):
    """Start a detached hidden child and wait until it holds the lock. Returns its PID or None."""
    argv, cwd = background_command(data_dir, extra, frozen, executable)
    flags = (CREATE_NO_WINDOW | DETACHED_PROCESS) if os.name == "nt" else 0
    popen(argv, cwd=cwd, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(int(wait * 4)):
        pid = running_pid(data_dir)
        if pid is not None and pid != os.getpid():
            return pid
        sleep(0.25)
    return None


def tail(path, n=50):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []

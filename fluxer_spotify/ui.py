"""The launcher window (tkinter, standard library only). A thin skin over launcher.Launcher: every decision lives there.

Long-running calls (logins, start/stop, checks) run in a worker thread; their results come back to the window through a
queue, so the window never freezes and tkinter is only touched from its own thread.
"""
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path

from . import __version__, github as github_mod
from .config import GH_LINES, LINE_NAMES
from .errors import Fatal, tr
from .http import HttpError, NetworkError
from .launcher import Launcher

BG, SURFACE, SURFACE2, BORDER = "#0e1013", "#171a1f", "#20242b", "#2a2f37"
TEXT, MUTED, ACCENT, ACCENT_HOVER, ACCENT_TEXT = "#eef0f3", "#8b929c", "#1ed760", "#3be477", "#04130a"
DANGER, WARN = "#ff6b6b", "#ffb454"
FONT = "Segoe UI"
LINE_LABELS = {
    "now": ("Aktueller Titel", "Current track"), "playlist": ("Playlist", "Playlist"),
    "top_artist": ("Top-Artist der Woche", "Top artist this week"), "listening_today": ("Hörzeit heute", "Listening time today"),
    "gh_push": ("Letzter Push", "Last push"), "gh_commits": ("Beiträge heute", "Contributions today"),
    "gh_prs": ("Offene Pull Requests", "Open pull requests"), "gh_reviews": ("Angefragte Reviews", "Requested reviews"),
    "gh_issues": ("Zugewiesene Issues", "Assigned issues"), "gh_streak": ("Serie (Tage in Folge)", "Streak (days in a row)"),
    "gh_stars": ("Sterne auf deinen Repos", "Stars on your repos"), "gh_followers": ("Follower", "Followers"),
}
SPOTIFY_DASHBOARD = "https://developer.spotify.com/dashboard"
REDIRECT = "http://127.0.0.1:8888/callback"


def T(de, en):
    return tr(de, en)


def error_text(e):
    if isinstance(e, HttpError):
        return T(f"Der Dienst hat die Anfrage abgelehnt (HTTP {e.status}).", f"The service rejected the request (HTTP {e.status}).")
    if isinstance(e, NetworkError):
        return T(f"Keine Verbindung: {e}", f"No connection: {e}")
    return str(e).strip() or e.__class__.__name__


def enable_dpi_awareness():
    """Crisp text on high-DPI screens (must happen before the first window)."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def icon_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "assets" / "icon.ico"
    return p if p.exists() else None


# ---------------------------------------------------------------------------------------------------- small widgets
class Btn(tk.Label):
    """Flat button (a Label): consistent look on every Windows theme, with hover and keyboard focus."""
    KINDS = {"primary": (ACCENT, ACCENT_TEXT, ACCENT_HOVER), "secondary": (SURFACE2, TEXT, BORDER),
             "danger": (SURFACE2, DANGER, BORDER), "ghost": (None, MUTED, SURFACE2)}

    def __init__(self, parent, text, command, kind="secondary", px=lambda n: n, bold=False, bg=None, **kw):
        base, fg, hover = self.KINDS[kind]
        self.kind = kind
        self.base = base or bg or parent.cget("bg")
        self.hover, self.fg0, self.command, self.enabled = hover, fg, command, True
        super().__init__(parent, text=text, bg=self.base, fg=fg, font=(FONT, 10, "bold" if bold or kind == "primary" else "normal"),
                         padx=px(14), pady=px(7), cursor="hand2", takefocus=1, highlightthickness=1, highlightbackground=self.base, **kw)
        self.bind("<Enter>", lambda e: self.enabled and self.config(bg=self.hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._rest()))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self.bind("<FocusIn>", lambda e: self.config(highlightbackground=ACCENT))
        self.bind("<FocusOut>", lambda e: self.config(highlightbackground=self.base))

    def _click(self, event):
        if not self.enabled:
            return
        if event.type == tk.EventType.ButtonRelease:
            w = self.winfo_containing(event.x_root, event.y_root)
            if w is not self:
                return
        self.command()

    def _rest(self):
        """Background when the pointer is not over the button (a disabled primary button is dimmed instead of glowing green)."""
        return self.base if self.enabled or self.kind != "primary" else "#1d3a2a"

    def set_enabled(self, on):
        self.enabled = on
        self.config(fg=self.fg0 if on else "#59606b", cursor="hand2" if on else "arrow", bg=self._rest())

    def set_text(self, text):
        self.config(text=text)

    def set_kind(self, kind):
        base, fg, hover = self.KINDS[kind]
        self.kind = kind
        self.base, self.fg0, self.hover = base or self.master.cget("bg"), fg, hover
        self.config(bg=self._rest(), fg=fg if self.enabled else "#59606b", highlightbackground=self.base,
                    font=(FONT, 10, "bold" if kind in ("primary", "danger") else "normal"))


class Toggle(tk.Canvas):
    """On/off switch."""

    def __init__(self, parent, value=False, command=None, px=lambda n: n, bg=SURFACE):
        self.w, self.h = px(40), px(22)
        super().__init__(parent, width=self.w, height=self.h, bg=bg, highlightthickness=1, highlightbackground=bg, cursor="hand2", takefocus=1)
        self.value, self.command, self.enabled, self._bg = bool(value), command, True, bg
        self.bind("<ButtonRelease-1>", lambda e: self.toggle())
        self.bind("<space>", lambda e: self.toggle())
        self.bind("<FocusIn>", lambda e: self.config(highlightbackground=ACCENT))
        self.bind("<FocusOut>", lambda e: self.config(highlightbackground=self._bg))
        self.draw()

    def draw(self):
        self.delete("all")
        w, h, r = self.w, self.h, self.h / 2
        track = ACCENT if self.value else "#3a404a"
        if not self.enabled:
            track = "#2b3037"
        self.create_oval(0, 0, h, h, fill=track, outline=track)
        self.create_oval(w - h, 0, w, h, fill=track, outline=track)
        self.create_rectangle(r, 0, w - r, h, fill=track, outline=track)
        pad = 3
        x = w - h + pad if self.value else pad
        self.create_oval(x, pad, x + h - 2 * pad, h - pad, fill="#ffffff" if self.enabled else "#6b7280", outline="")

    def toggle(self):
        if not self.enabled:
            return
        self.value = not self.value
        self.draw()
        if self.command:
            self.command(self.value)

    def set(self, value):
        self.value = bool(value)
        self.draw()

    def get(self):
        return self.value

    def set_enabled(self, on):
        self.enabled = on
        self.config(cursor="hand2" if on else "arrow")
        self.draw()


class Scroll(tk.Frame):
    """Vertically scrollable area (mouse wheel and a slim bar). Put the content into .inner."""

    def __init__(self, parent, px, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.bar = tk.Canvas(self, width=px(8), bg=bg, highlightthickness=0, borderwidth=0)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self._thumb)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        for w in (self, self.canvas, self.inner):
            w.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
            w.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self.bar.bind("<B1-Motion>", self._drag)
        self.bar.bind("<Button-1>", self._drag)
        self._range = (0.0, 1.0)

    def _wheel(self, event):
        if self._range != (0.0, 1.0):
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _thumb(self, first, last):
        first, last = float(first), float(last)
        self._range = (first, last)
        self.bar.delete("all")
        if first <= 0.0 and last >= 1.0:
            self.bar.pack_forget()
            return
        if not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y", padx=(2, 0))
        h = self.bar.winfo_height()
        self.bar.create_rectangle(1, int(first * h), self.bar.winfo_width() - 1, max(int(first * h) + 24, int(last * h)), fill=BORDER, outline=BORDER)

    def _drag(self, event):
        h = max(1, self.bar.winfo_height())
        self.canvas.yview_moveto(max(0.0, min(1.0, event.y / h - (self._range[1] - self._range[0]) / 2)))


def dark_titlebar(widget):
    """Windows 10/11: dark window title bar that matches the content. Silently does nothing where unsupported."""
    if os.name != "nt":
        return
    import ctypes
    try:
        widget.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(widget.winfo_id())
        dwm = ctypes.windll.dwmapi
        for attr, value in ((20, 1), (19, 1), (35, 0x13100E), (36, 0xF3F0EE)):  # dark mode, caption colour, caption text (COLORREF = 0xBBGGRR)
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


def card(parent, px, pad=16):
    outer = tk.Frame(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
    inner = tk.Frame(outer, bg=SURFACE)
    inner.pack(fill="both", expand=True, padx=px(pad), pady=px(pad - 2))
    return outer, inner


def label(parent, text, size=10, color=TEXT, bold=False, bg=SURFACE, **kw):
    return tk.Label(parent, text=text, bg=bg, fg=color, font=(FONT, size, "bold" if bold else "normal"), anchor="w", justify="left", **kw)


def entry(parent, px, show=None, width=34):
    e = tk.Entry(parent, bg=SURFACE2, fg=TEXT, insertbackground=TEXT, relief="flat", font=(FONT, 11), show=show, width=width,
                 highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, disabledbackground=SURFACE2)
    return e


class Dot(tk.Canvas):
    def __init__(self, parent, px, bg=SURFACE, size=12):
        s = px(size)
        super().__init__(parent, width=s, height=s, bg=bg, highlightthickness=0)
        self.s = s
        self.set(MUTED)

    def set(self, color):
        self.delete("all")
        self.create_oval(1, 1, self.s - 1, self.s - 1, fill=color, outline=color)


class Worker:
    """Runs jobs in threads and hands their results back to the tkinter thread."""

    def __init__(self, root):
        self.root, self.q, self._job = root, queue.Queue(), None
        self._poll()

    def stop(self):
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _poll(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        try:
            self._job = self.root.after(80, self._poll)
        except tk.TclError:
            pass  # window already destroyed

    def run(self, job, on_ok=None, on_err=None):
        def target():
            try:
                res = job()
            except BaseException as e:  # noqa: BLE001 - everything goes back to the window
                if on_err:
                    self.q.put(lambda e=e: on_err(e))
                return
            if on_ok:
                self.q.put(lambda: on_ok(res))
        threading.Thread(target=target, daemon=True).start()

    def ask(self, fn):
        """Called from a worker thread: run `fn` in the window's thread and wait for its result (e.g. a 2FA prompt)."""
        done, box = threading.Event(), []
        self.q.put(lambda: (box.append(fn()), done.set()))
        done.wait()
        return box[0]

    def post(self, fn):
        self.q.put(fn)


# ---------------------------------------------------------------------------------------------------- dialogs
class Dialog:
    def __init__(self, app, title, width=460):
        self.app = app
        px = app.px
        self.top = tk.Toplevel(app.root, bg=BG)
        self.top.title(title)
        self.top.transient(app.root)
        self.top.resizable(False, False)
        ico = icon_path()
        if ico and os.name == "nt":
            try:
                self.top.iconbitmap(str(ico))
            except tk.TclError:
                pass
        self.body = tk.Frame(self.top, bg=BG)
        self.body.pack(fill="both", expand=True, padx=px(20), pady=px(18))
        self.width = px(width)
        dark_titlebar(self.top)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.closed = False

    def show(self):
        self.top.update_idletasks()
        root = self.app.root
        w, h = max(self.width, self.top.winfo_reqwidth()), self.top.winfo_reqheight()
        x = root.winfo_rootx() + (root.winfo_width() - w) // 2
        y = root.winfo_rooty() + max(20, (root.winfo_height() - h) // 3)
        self.top.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.top.grab_set()
        self.top.focus_set()
        return self

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.top.grab_release()
            self.top.destroy()
        except tk.TclError:
            pass
        self.app.refresh()


# ---------------------------------------------------------------------------------------------------- the window
class App:
    def __init__(self, launcher):
        enable_dpi_awareness()
        self.L = launcher
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Fluxer Spotify")
        self.root.configure(bg=BG)
        self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.root.resizable(False, False)
        ico = icon_path()
        if ico and os.name == "nt":
            try:
                self.root.iconbitmap(str(ico))
            except tk.TclError:
                pass
        self.work = Worker(self.root)
        self._tick_job = None
        self.root.bind("<Destroy>", self._on_destroy)
        self.snap = None
        self.busy = False
        self.dirty = False
        self.line_toggles = {}
        self._build()
        w, h = self.px(500), self.px(740)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        h = min(h, sh - self.px(80))
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        dark_titlebar(self.root)
        self.root.deiconify()
        self.refresh(force=True)
        self._tick_job = self.root.after(1500, self._tick)

    def _on_destroy(self, event):
        if event.widget is self.root:  # the root was closed: stop the timers so nothing fires into a dead window
            self.work.stop()
            if self._tick_job is not None:
                try:
                    self.root.after_cancel(self._tick_job)
                except tk.TclError:
                    pass

    def px(self, n):
        return int(round(n * self.scale))

    # ------------------------------------------------------------ layout
    def _build(self):
        px, root = self.px, self.root
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=px(22), pady=(px(20), px(6)))
        logo = tk.Canvas(head, width=px(46), height=px(46), bg=BG, highlightthickness=0)
        logo.create_oval(1, 1, px(46) - 1, px(46) - 1, fill=ACCENT, outline=ACCENT)
        logo.create_text(px(23), px(24), text="♪", fill=ACCENT_TEXT, font=(FONT, 20, "bold"))
        logo.pack(side="left")
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", padx=px(14))
        tk.Label(titles, text="Fluxer Spotify", bg=BG, fg=TEXT, font=(FONT, 17, "bold"), anchor="w").pack(anchor="w")
        tk.Label(titles, text=T("Dein Spotify im Fluxer-Status – rund um die Uhr", "Your Spotify in your Fluxer status – around the clock"),
                 bg=BG, fg=MUTED, font=(FONT, 9), anchor="w").pack(anchor="w")

        tabs = tk.Frame(root, bg=BG)
        tabs.pack(fill="x", padx=px(22), pady=(px(10), px(8)))
        self.tab_btns = {}
        for key, text in (("home", T("Übersicht", "Overview")), ("display", T("Anzeige", "Display"))):
            b = Btn(tabs, text, lambda k=key: self.show_tab(k), kind="ghost", px=px, bold=True)
            b.pack(side="left", padx=(0, px(4)))
            self.tab_btns[key] = b

        self.pages = {}
        host = tk.Frame(root, bg=BG)
        host.pack(fill="both", expand=True, padx=px(22))
        for key in ("home", "display"):
            f = tk.Frame(host, bg=BG)
            self.pages[key] = f
        self._build_home(self.pages["home"])
        self._build_display(self.pages["display"])

        foot = tk.Frame(root, bg=BG)
        foot.pack(fill="x", padx=px(22), pady=(px(6), px(14)), side="bottom")
        tk.Label(foot, text=f"v{__version__}", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")
        for text, cmd in ((T("Deinstallieren…", "Uninstall…"), self.uninstall), (T("Log", "Log"), self.dlg_log), (T("Verbindungen prüfen", "Check connections"), self.dlg_check)):
            Btn(foot, text, cmd, kind="ghost", px=px).pack(side="right")
        self.show_tab("home")

    def show_tab(self, key):
        for k, f in self.pages.items():
            f.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for k, b in self.tab_btns.items():
            b.config(fg=TEXT if k == key else MUTED)
            b.base = SURFACE2 if k == key else BG
            b.config(bg=b.base, highlightbackground=b.base)
        self.tab = key

    def _build_home(self, page):
        px = self.px
        # --- status card
        outer, c = card(page, px)
        outer.pack(fill="x", pady=(0, px(10)))
        row = tk.Frame(c, bg=SURFACE)
        row.pack(fill="x")
        self.status_dot = Dot(row, px, size=14)
        self.status_dot.pack(side="left", padx=(0, px(10)))
        self.status_title = label(row, "", 14, bold=True)
        self.status_title.pack(side="left")
        self.status_text = label(c, "", 9, MUTED, wraplength=px(420))
        self.status_text.pack(fill="x", pady=(px(4), px(8)))
        self.banner = label(c, "", 9, WARN, wraplength=px(420))
        self.primary = Btn(c, "", lambda: None, kind="primary", px=px)
        self.primary.pack(fill="x", pady=(px(4), 0), ipady=px(4))
        self.skip_btn = Btn(c, T("GitHub überspringen", "Skip GitHub"), self.skip_github, kind="ghost", px=px)

        # --- connections
        outer, c = card(page, px)
        outer.pack(fill="x", pady=(0, px(10)))
        label(c, T("Verbindungen", "Connections"), 10, MUTED, bold=True).pack(fill="x", pady=(0, px(6)))
        self.conn = {}
        for key, name in (("spotify", "Spotify"), ("fluxer", "Fluxer"), ("github", "GitHub")):
            r = tk.Frame(c, bg=SURFACE)
            r.pack(fill="x", pady=px(5))
            dot = Dot(r, px, size=10)
            dot.pack(side="left", padx=(0, px(10)))
            txt = tk.Frame(r, bg=SURFACE)
            txt.pack(side="left", fill="x", expand=True)
            label(txt, name + (T("  (optional)", "  (optional)") if key == "github" else ""), 11, bold=True).pack(fill="x")
            detail = label(txt, "", 9, MUTED)
            detail.pack(fill="x")
            btn = Btn(r, "", lambda k=key: self.connect(k), kind="secondary", px=px)
            btn.pack(side="right")
            self.conn[key] = (dot, detail, btn)

        # --- autostart
        outer, c = card(page, px)
        outer.pack(fill="x", pady=(0, px(10)))
        r = tk.Frame(c, bg=SURFACE)
        r.pack(fill="x")
        t = tk.Frame(r, bg=SURFACE)
        t.pack(side="left", fill="x", expand=True)
        label(t, T("Mit Windows starten", "Start with Windows"), 11, bold=True).pack(fill="x")
        self.auto_text = label(t, "", 9, MUTED, wraplength=px(340))
        self.auto_text.pack(fill="x")
        self.auto_toggle = Toggle(r, False, self.set_autostart, px=px)
        self.auto_toggle.pack(side="right")
        self.auto_fix = Btn(c, T("Autostart auf diese Exe aktualisieren", "Point autostart at this exe"), self.fix_autostart, kind="secondary", px=px)
        self.auto_warn = label(c, "", 9, WARN, wraplength=px(420))

    def _build_display(self, page):
        px = self.px
        bottom = tk.Frame(page, bg=BG)  # packed first so it keeps its space at the bottom
        bottom.pack(side="bottom", fill="x")
        scroll = Scroll(page, px)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner
        outer, c = card(body, px)
        outer.pack(fill="x", pady=(0, px(10)))
        label(c, T("Was im Status erscheint", "What the status shows"), 10, MUTED, bold=True).pack(fill="x", pady=(0, px(2)))
        for title, names in ((T("Spotify", "Spotify"), [n for n in LINE_NAMES if n not in GH_LINES]), ("GitHub", [n for n in LINE_NAMES if n in GH_LINES])):
            label(c, title, 9, MUTED).pack(fill="x", pady=(px(8), px(2)))
            grid = tk.Frame(c, bg=SURFACE)
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1, uniform="c")
            grid.columnconfigure(1, weight=1, uniform="c")
            for i, name in enumerate(names):
                cell = tk.Frame(grid, bg=SURFACE)
                cell.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0 if i % 2 == 0 else px(14), px(14) if i % 2 == 0 else 0), pady=px(3))
                de, en = LINE_LABELS[name]
                lab = label(cell, T(de, en), 10)
                lab.pack(side="left")
                tg = Toggle(cell, False, lambda v: self.mark_dirty(), px=px)
                tg.pack(side="right")
                self.line_toggles[name] = (tg, lab)
        self.gh_note = label(c, T("GitHub-Zeilen brauchen eine GitHub-Verbindung (Übersicht).", "GitHub lines need a GitHub connection (Overview)."), 9, MUTED, wraplength=px(400))

        outer, c = card(body, px)
        outer.pack(fill="x", pady=(0, px(10)))
        self.opt = {}
        for key, title, desc in (
            ("idle", T("Auch zeigen, wenn nichts spielt", "Also show when nothing plays"),
             T("Statistik- und GitHub-Zeilen bleiben im Status, statt dass er gelöscht wird.", "Statistics and GitHub lines stay in the status instead of it being cleared.")),
            ("pause", T("Auch bei Pause zeigen", "Also show while paused"),
             T("Bei Pause rotieren Statistik und GitHub weiter.", "While paused, statistics and GitHub keep rotating.")),
            ("ttl", T("Status läuft von selbst ab", "Status expires by itself"),
             T("Geht der PC aus, verschwindet der Status nach etwa 10 Minuten von allein.", "If the PC shuts down, the status disappears by itself after about 10 minutes.")),
        ):
            r = tk.Frame(c, bg=SURFACE)
            r.pack(fill="x", pady=px(5))
            t = tk.Frame(r, bg=SURFACE)
            t.pack(side="left", fill="x", expand=True)
            label(t, title, 10, bold=True).pack(fill="x")
            label(t, desc, 9, MUTED, wraplength=px(340)).pack(fill="x")
            tg = Toggle(r, False, lambda v: self.mark_dirty(), px=px)
            tg.pack(side="right")
            self.opt[key] = tg
        r = tk.Frame(c, bg=SURFACE)
        r.pack(fill="x", pady=px(5))
        t = tk.Frame(r, bg=SURFACE)
        t.pack(side="left", fill="x", expand=True)
        label(t, T("Wechsel alle … Sekunden", "Switch every … seconds"), 10, bold=True).pack(fill="x")
        label(t, T("Mindestens 15. Jeder Wechsel ist eine Anfrage an Fluxer.", "At least 15. Every switch is one request to Fluxer."), 9, MUTED, wraplength=px(300)).pack(fill="x")
        self.rotate = tk.Spinbox(r, from_=15, to=300, increment=5, width=5, bg=SURFACE2, fg=TEXT, insertbackground=TEXT, relief="flat", font=(FONT, 11),
                                 buttonbackground=SURFACE2, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
                                 command=self.mark_dirty)
        self.rotate.pack(side="right")
        self.rotate.bind("<KeyRelease>", lambda e: self.mark_dirty())

        self.save_btn = Btn(bottom, T("Speichern", "Save"), self.save_display, kind="primary", px=px)
        self.save_btn.pack(fill="x", ipady=px(4))
        self.save_note = label(bottom, "", 9, MUTED, bg=BG, wraplength=px(440))
        self.save_note.pack(fill="x", pady=(px(6), 0))

    # ------------------------------------------------------------ state -> widgets
    def _tick(self):
        try:
            self.refresh()
            self._tick_job = self.root.after(1500, self._tick)
        except tk.TclError:
            pass

    def refresh(self, force=False):
        try:
            snap = self.L.snapshot()
        except Exception as e:  # noqa: BLE001 - the window must survive a broken file
            self.status_title.config(text=T("Fehler beim Lesen", "Error reading state"))
            self.status_text.config(text=str(e))
            return
        if snap == self.snap and not force:
            return
        first = self.snap is None
        self.snap = snap
        self.render(snap, first)

    def render(self, s, first=False):
        # status card
        if s.running:
            color, title, text = ACCENT, T("Läuft im Hintergrund", "Running in the background"), T(
                f"Dein Fluxer-Status wird automatisch aktualisiert (PID {s.pid}). Du kannst dieses Fenster schließen.",
                f"Your Fluxer status is updated automatically (PID {s.pid}). You can close this window.")
        elif not s.ready:
            color, title, text = WARN, T("Einrichtung nötig", "Setup needed"), T(
                "Verbinde Spotify und Fluxer – dann läuft alles von allein.", "Connect Spotify and Fluxer – then everything runs by itself.")
        else:
            color, title, text = MUTED, T("Gestoppt", "Stopped"), T("Alles verbunden. Drücke „Starten“.", "Everything is connected. Press “Start”.")
        if s.problem:
            color, title, text = DANGER, T("Einstellungen fehlerhaft", "Invalid settings"), s.problem
        self.status_dot.set(color)
        self.status_title.config(text=title)
        self.status_text.config(text=text)
        if s.attention and not s.running:
            self.banner.config(text="⚠  " + s.attention)
            self.banner.pack(fill="x", pady=(0, self.px(6)), before=self.primary)
        else:
            self.banner.pack_forget()

        step = s.next_step
        self.primary.set_kind("danger" if s.running else "primary")
        if s.running:
            self.primary.set_text("■   " + T("Stoppen", "Stop"))
            self.primary.command = self.do_stop
            self.primary.set_enabled(not self.busy)
        elif step == "spotify":
            self.primary.set_text(T("Spotify verbinden", "Connect Spotify"))
            self.primary.command = lambda: self.connect("spotify")
        elif step == "fluxer":
            self.primary.set_text(T("Fluxer verbinden", "Connect Fluxer"))
            self.primary.command = lambda: self.connect("fluxer")
        elif step == "github":
            self.primary.set_text(T("GitHub verbinden (empfohlen)", "Connect GitHub (recommended)"))
            self.primary.command = lambda: self.connect("github")
        else:
            self.primary.set_text("▶   " + T("Starten", "Start"))
            self.primary.command = self.do_start
        if not s.running:
            self.primary.set_enabled(not self.busy)
        if step == "github" and not s.running:
            self.skip_btn.pack(fill="x", pady=(self.px(4), 0), after=self.primary)
        else:
            self.skip_btn.pack_forget()

        # connections
        def conn(key, account, on_text, off_text, connect_label, disconnect_label):
            dot, detail, btn = self.conn[key]
            dot.set(ACCENT if account.connected else "#59606b")
            detail.config(text=on_text if account.connected else off_text)
            btn.set_text(disconnect_label if account.connected else connect_label)
        conn("spotify", s.spotify, T("Verbunden", "Connected"), T("Nicht verbunden", "Not connected"), T("Verbinden", "Connect"), T("Trennen", "Disconnect"))
        conn("fluxer", s.fluxer, T(f"Angemeldet als {s.fluxer.detail}" if s.fluxer.detail else "Angemeldet", f"Logged in as {s.fluxer.detail}" if s.fluxer.detail else "Logged in"),
             T("Nur Webhook-Betrieb" if s.webhook else "Nicht verbunden", "Webhook-only" if s.webhook else "Not connected"), T("Anmelden", "Log in"), T("Abmelden", "Log out"))
        conn("github", s.github, T(f"Verbunden als {s.github.detail}" if s.github.detail else "Verbunden", f"Connected as {s.github.detail}" if s.github.detail else "Connected"),
             T("Für GitHub-Zeilen im Status", "For GitHub lines in the status"), T("Verbinden", "Connect"), T("Trennen", "Disconnect"))

        # autostart
        self.auto_toggle.set(s.autostart_on)
        self.auto_toggle.set_enabled(s.autostart_supported)
        if not s.autostart_supported:
            self.auto_text.config(text=T("Nur unter Windows verfügbar.", "Only available on Windows."))
        else:
            self.auto_text.config(text=T("Startet unsichtbar beim Anmelden. Steht auch im Task-Manager unter „Autostart“.",
                                         "Starts hidden when you sign in. Also listed in Task Manager under “Startup apps”."))
        warn = ""
        if s.autostart_blocked and s.autostart_on:
            warn = T("Im Task-Manager ist der Autostart ausgeschaltet. Dort wieder aktivieren.", "Autostart is switched off in Task Manager. Turn it on there.")
        elif s.exe_hint and not s.autostart_on:
            warn = s.exe_hint
        self.auto_warn.config(text=warn)
        if warn:
            self.auto_warn.pack(fill="x", pady=(self.px(6), 0))
        else:
            self.auto_warn.pack_forget()
        if s.autostart_on and not s.autostart_current:
            self.auto_fix.pack(fill="x", pady=(self.px(8), 0))
        else:
            self.auto_fix.pack_forget()

        # display tab
        if first or not self.dirty:
            for name, (tg, lab) in self.line_toggles.items():
                gh_line = name in GH_LINES
                tg.set(name in s.lines and (not gh_line or s.github.connected))
                tg.set_enabled(not gh_line or s.github.connected)
                lab.config(fg=MUTED if gh_line and not s.github.connected else TEXT)
            self.opt["idle"].set(s.show_when_idle)
            self.opt["pause"].set(s.show_on_pause)
            self.opt["ttl"].set(s.ttl_on)
            self.rotate.delete(0, "end")
            self.rotate.insert(0, str(s.rotate))
            self.save_btn.set_enabled(False)
        if s.github.connected:
            self.gh_note.pack_forget()
        else:
            self.gh_note.pack(fill="x", pady=(self.px(6), 0))

    def mark_dirty(self):
        self.dirty = True
        self.save_btn.set_enabled(True)
        self.save_note.config(text="")

    # ------------------------------------------------------------ actions
    def toast(self, text, color=ACCENT):
        """A short message in the status card; the normal text comes back after a few seconds."""
        self.status_text.config(text=text, fg=color)
        self.root.after(6000, lambda: (self.status_text.config(fg=MUTED), self.refresh(force=True)))

    def fail(self, e):
        self.busy = False
        self.refresh(force=True)
        self.message(T("Das hat nicht geklappt", "That did not work"), error_text(e))

    def message(self, title, text, kind="error"):
        d = Dialog(self, title, 440)
        label(d.body, title, 13, bold=True, bg=BG).pack(fill="x")
        label(d.body, text, 10, MUTED if kind != "error" else TEXT, bg=BG, wraplength=self.px(400)).pack(fill="x", pady=(self.px(8), self.px(14)))
        Btn(d.body, "OK", d.close, kind="primary", px=self.px).pack(anchor="e")
        d.show()

    def do_start(self):
        self.busy = True
        self.primary.set_enabled(False)
        self.status_text.config(text=T("Starte …", "Starting …"))
        self.work.run(self.L.start, on_ok=self._started, on_err=self.fail)

    def _started(self, pid):
        self.busy = False
        self.refresh(force=True)
        if pid is None:
            self.message(T("Start fehlgeschlagen", "Start failed"), T(
                "Das Hintergrundprogramm ist nicht angesprungen. Im Log (unten) steht der Grund.", "The background program did not come up. The log (below) says why."))
            return
        if self.snap and self.snap.autostart_supported and not self.snap.autostart_on and not self.auto_asked:
            self.auto_asked = True
            self.ask_autostart()

    auto_asked = False

    def ask_autostart(self):
        d = Dialog(self, T("Immer laufen lassen?", "Keep it running?"), 440)
        label(d.body, T("Mit Windows starten?", "Start with Windows?"), 13, bold=True, bg=BG).pack(fill="x")
        label(d.body, T("Dann läuft Spotify im Status rund um die Uhr, auch nach einem Neustart – unsichtbar im Hintergrund. Das lässt sich hier jederzeit wieder abschalten.",
                        "Then Spotify keeps showing in your status around the clock, even after a restart – hidden in the background. You can switch it off here any time."),
              10, MUTED, bg=BG, wraplength=self.px(400)).pack(fill="x", pady=(self.px(8), self.px(14)))
        row = tk.Frame(d.body, bg=BG)
        row.pack(fill="x")

        def yes():
            d.close()
            self.set_autostart(True)
        Btn(row, T("Ja, immer laufen lassen", "Yes, keep it running"), yes, kind="primary", px=self.px).pack(side="right")
        Btn(row, T("Nein danke", "No thanks"), d.close, kind="ghost", px=self.px).pack(side="right", padx=(0, self.px(8)))
        d.show()

    def do_stop(self):
        self.busy = True
        self.primary.set_enabled(False)
        self.status_text.config(text=T("Beende …", "Stopping …"))
        self.work.run(self.L.stop, on_ok=lambda r: (setattr(self, "busy", False), self.refresh(force=True)), on_err=self.fail)

    def set_autostart(self, on):
        try:
            self.L.set_autostart(on)
        except Exception as e:  # noqa: BLE001
            self.fail(e)
            return
        self.refresh(force=True)

    def fix_autostart(self):
        self.set_autostart(True)

    def skip_github(self):
        self.L.github_skip()
        self.refresh(force=True)

    def connect(self, key):
        s = self.snap
        if key == "spotify":
            if s.spotify.connected:
                self.L.spotify_disconnect()
                self.refresh(force=True)
            else:
                self.dlg_spotify()
        elif key == "fluxer":
            if s.fluxer.connected:
                self.busy = True
                self.work.run(self.L.fluxer_disconnect, on_ok=lambda r: (setattr(self, "busy", False), self.refresh(force=True)), on_err=self.fail)
            else:
                self.dlg_fluxer()
        else:
            if s.github.connected:
                self.L.github_disconnect()
                self.refresh(force=True)
            else:
                self.dlg_github()

    def save_display(self):
        try:
            lines = [n for n, (tg, _) in self.line_toggles.items() if tg.get()]
            rotate = int(float(self.rotate.get()))
        except ValueError:
            self.message(T("Ungültiger Wert", "Invalid value"), T("Bei „Wechsel alle … Sekunden“ bitte eine Zahl eintragen.", "Please enter a number for “Switch every … seconds”."))
            return
        try:
            self.L.save_settings(lines, self.opt["idle"].get(), self.opt["pause"].get(), rotate, self.opt["ttl"].get())
        except Fatal as e:
            self.message(T("Nicht gespeichert", "Not saved"), str(e))
            return
        self.dirty = False
        self.save_btn.set_enabled(False)
        if self.snap and self.snap.running:
            self.save_note.config(text=T("Gespeichert. Das Hintergrundprogramm wird neu gestartet …", "Saved. Restarting the background program …"))
            self.busy = True
            self.work.run(self.L.restart, on_ok=lambda r: (setattr(self, "busy", False), self.save_note.config(text=T("Gespeichert und neu gestartet.", "Saved and restarted.")), self.refresh(force=True)),
                          on_err=self.fail)
        else:
            self.save_note.config(text=T("Gespeichert. Gilt beim nächsten Start.", "Saved. Applies at the next start."))
        self.refresh(force=True)

    # ------------------------------------------------------------ dialogs
    def dlg_spotify(self):
        px = self.px
        d = Dialog(self, T("Spotify verbinden", "Connect Spotify"), 480)
        label(d.body, T("Spotify verbinden", "Connect Spotify"), 14, bold=True, bg=BG).pack(fill="x")
        label(d.body, T("Einmalig brauchst du eine kostenlose Spotify-App (2 Minuten):", "Once, you need a free Spotify app (2 minutes):"), 10, MUTED, bg=BG).pack(fill="x", pady=(px(6), px(8)))
        steps = tk.Frame(d.body, bg=BG)
        steps.pack(fill="x")
        label(steps, T("1.  Öffne das Spotify-Dashboard und wähle „Create app“.", "1.  Open the Spotify dashboard and choose “Create app”."), 10, bg=BG, wraplength=px(430)).pack(fill="x")
        Btn(steps, T("Dashboard öffnen", "Open dashboard"), lambda: webbrowser.open(SPOTIFY_DASHBOARD), kind="secondary", px=px).pack(anchor="w", pady=(px(4), px(8)))
        label(steps, T("2.  Trage bei „Redirect URI“ genau diese Adresse ein und speichere:", "2.  Enter exactly this address as “Redirect URI” and save:"), 10, bg=BG, wraplength=px(430)).pack(fill="x")
        rr = tk.Frame(steps, bg=BG)
        rr.pack(fill="x", pady=(px(4), px(8)))
        uri = entry(rr, px, width=34)
        uri.insert(0, REDIRECT)
        uri.config(state="readonly", readonlybackground=SURFACE2)
        uri.pack(side="left", ipady=px(4))

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(REDIRECT)
            copy_btn.set_text(T("Kopiert", "Copied"))
        copy_btn = Btn(rr, T("Kopieren", "Copy"), copy, kind="secondary", px=px)
        copy_btn.pack(side="left", padx=(px(8), 0))
        label(steps, T("3.  Kopiere die „Client ID“ aus den App-Einstellungen hierher:", "3.  Copy the “Client ID” from the app settings here:"), 10, bg=BG, wraplength=px(430)).pack(fill="x")
        cid = entry(d.body, px, width=44)
        cid.pack(fill="x", ipady=px(4), pady=(px(4), px(10)))
        if self.snap and self.snap.client_id:
            cid.insert(0, self.snap.client_id)
        info = label(d.body, "", 10, MUTED, bg=BG, wraplength=px(430))
        info.pack(fill="x", pady=(0, px(8)))
        row = tk.Frame(d.body, bg=BG)
        row.pack(fill="x")
        state = {"cancel": False, "running": False}

        def go():
            if state["running"]:
                return
            state.update(cancel=False, running=True)
            go_btn.set_enabled(False)
            info.config(text=T("Dein Browser öffnet sich. Klicke bei Spotify auf „Zustimmen“ (bis zu 3 Minuten) …", "Your browser opens. Click “Agree” at Spotify (up to 3 minutes) …"), fg=MUTED)

            def done(_):
                d.close()

            def failed(e):
                state["running"] = False
                go_btn.set_enabled(True)
                if not d.closed:
                    info.config(text=error_text(e), fg=DANGER)
            self.work.run(lambda: self.L.spotify_login(cid.get(), open_browser=webbrowser.open, notify=lambda m: None, cancel=lambda: state["cancel"] or d.closed),
                          on_ok=done, on_err=failed)

        def cancel():
            state["cancel"] = True
            d.close()
        go_btn = Btn(row, T("Weiter – bei Spotify anmelden", "Continue – log in at Spotify"), go, kind="primary", px=px)
        go_btn.pack(side="right")
        Btn(row, T("Abbrechen", "Cancel"), cancel, kind="ghost", px=px).pack(side="right", padx=(0, px(8)))
        d.top.protocol("WM_DELETE_WINDOW", cancel)
        d.show()
        cid.focus_set()

    def dlg_fluxer(self):
        px = self.px
        d = Dialog(self, T("Bei Fluxer anmelden", "Log in to Fluxer"), 440)
        label(d.body, T("Bei Fluxer anmelden", "Log in to Fluxer"), 14, bold=True, bg=BG).pack(fill="x")
        label(d.body, T("Dein Passwort wird nur einmal an Fluxer gesendet und nie gespeichert. Gespeichert wird nur eine eigene Sitzung (in den Fluxer-Einstellungen sichtbar und jederzeit beendbar), verschlüsselt für dein Windows-Konto.",
                        "Your password is sent to Fluxer once and never stored. Only a session of its own is kept (visible in your Fluxer settings, can be ended any time), encrypted for your Windows account."),
              9, MUTED, bg=BG, wraplength=px(400)).pack(fill="x", pady=(px(6), px(10)))
        label(d.body, T("E-Mail", "E-mail"), 9, MUTED, bg=BG).pack(fill="x")
        em = entry(d.body, px, width=40)
        em.pack(fill="x", ipady=px(4), pady=(px(2), px(8)))
        label(d.body, T("Passwort", "Password"), 9, MUTED, bg=BG).pack(fill="x")
        pw = entry(d.body, px, show="•", width=40)
        pw.pack(fill="x", ipady=px(4), pady=(px(2), px(8)))
        code_frame = tk.Frame(d.body, bg=BG)
        label(code_frame, T("Zwei-Faktor-Code (Authenticator oder Backup-Code)", "Two-factor code (authenticator or backup code)"), 9, MUTED, bg=BG).pack(fill="x")
        code = entry(code_frame, px, width=20)
        code.pack(fill="x", ipady=px(4), pady=(px(2), px(8)))
        info = label(d.body, "", 10, MUTED, bg=BG, wraplength=px(400))
        info.pack(fill="x", pady=(0, px(8)))
        row = tk.Frame(d.body, bg=BG)
        row.pack(fill="x")
        state = {"running": False, "wait": None}

        def ask_code(attempt):
            """Worker thread: show the code field and wait until the user presses the button again (or closes the dialog)."""
            ev, box = threading.Event(), {}

            def prompt():
                code_frame.pack(fill="x", before=info)
                code.delete(0, "end")
                code.focus_set()
                info.config(text=T("Gib den Code ein und drücke „Code senden“.", "Enter the code and press “Send code”."), fg=MUTED)
                go_btn.set_text(T("Code senden", "Send code"))
                go_btn.set_enabled(True)
                state["wait"] = (ev, box)
            self.work.post(prompt)
            ev.wait(300)
            return box.get("code", "")

        def go():
            if state["wait"]:  # second press = the 2FA code was typed
                ev, box = state["wait"]
                state["wait"] = None
                box["code"] = code.get().strip()
                go_btn.set_enabled(False)
                ev.set()
                return
            if state["running"]:
                return
            state["running"] = True
            go_btn.set_enabled(False)
            info.config(text=T("Melde an …", "Logging in …"), fg=MUTED)
            password, email = pw.get(), em.get()
            pw.delete(0, "end")  # do not keep the password in the widget longer than needed

            def notify(msg):
                self.work.post(lambda: info.config(text=msg, fg=MUTED) if not d.closed else None)

            def ok(name):
                d.close()
                self.toast(T(f"Bei Fluxer angemeldet als {name}.", f"Logged in to Fluxer as {name}."))

            def failed(e):
                state["running"] = False
                go_btn.set_enabled(True)
                if not d.closed:
                    info.config(text=error_text(e), fg=DANGER)
            self.work.run(lambda: self.L.fluxer_login(email, password, ask_code, notify=notify), on_ok=ok, on_err=failed)
        go_btn = Btn(row, T("Anmelden", "Log in"), go, kind="primary", px=px)
        go_btn.pack(side="right")

        def close():
            if state["wait"]:  # unblock the worker thread that waits for a code
                state["wait"][1]["code"] = ""
                state["wait"][0].set()
                state["wait"] = None
            d.close()
        Btn(row, T("Abbrechen", "Cancel"), close, kind="ghost", px=px).pack(side="right", padx=(0, px(8)))
        Btn(row, T("Token einfügen …", "Paste token …"), lambda: (close(), self.dlg_fluxer_token()), kind="ghost", px=px).pack(side="left")
        d.top.protocol("WM_DELETE_WINDOW", close)
        pw.bind("<Return>", lambda e: go())
        code.bind("<Return>", lambda e: go())
        d.show()
        em.focus_set()

    def dlg_fluxer_token(self):
        px = self.px
        d = Dialog(self, T("Fluxer-Token einfügen", "Paste Fluxer token"), 440)
        label(d.body, T("Token statt Passwort", "Token instead of password"), 14, bold=True, bg=BG).pack(fill="x")
        label(d.body, T("Nur für Konten, die sich nicht per Passwort anmelden können (SSO, nur Passkey). Der Token gibt vollen Zugriff auf dein Konto – teile ihn nie.",
                        "Only for accounts that cannot log in with a password (SSO, passkey only). The token gives full access to your account – never share it."),
              9, MUTED, bg=BG, wraplength=px(400)).pack(fill="x", pady=(px(6), px(10)))
        tok = entry(d.body, px, show="•", width=44)
        tok.pack(fill="x", ipady=px(4), pady=(0, px(10)))
        info = label(d.body, "", 10, MUTED, bg=BG, wraplength=px(400))
        info.pack(fill="x", pady=(0, px(8)))
        row = tk.Frame(d.body, bg=BG)
        row.pack(fill="x")

        def go():
            btn.set_enabled(False)
            value = tok.get()
            tok.delete(0, "end")

            def failed(e):
                btn.set_enabled(True)
                if not d.closed:
                    info.config(text=error_text(e), fg=DANGER)
            self.work.run(lambda: self.L.fluxer_token(value), on_ok=lambda n: (d.close(), self.toast(T(f"Token gültig ({n}).", f"Token valid ({n})."))), on_err=failed)
        btn = Btn(row, T("Speichern", "Save"), go, kind="primary", px=px)
        btn.pack(side="right")
        Btn(row, T("Abbrechen", "Cancel"), d.close, kind="ghost", px=px).pack(side="right", padx=(0, px(8)))
        d.show()
        tok.focus_set()

    def dlg_github(self):
        px = self.px
        d = Dialog(self, T("GitHub verbinden", "Connect GitHub"), 480)
        label(d.body, T("GitHub verbinden", "Connect GitHub"), 14, bold=True, bg=BG).pack(fill="x")
        label(d.body, T("Der Status zeigt dann z. B. heutige Beiträge, offene Pull Requests und deine Serie. Das Programm braucht nur Lese-Rechte.",
                        "The status then shows e.g. today's contributions, open pull requests and your streak. The program only needs read access."),
              10, MUTED, bg=BG, wraplength=px(430)).pack(fill="x", pady=(px(6), px(10)))
        label(d.body, T("1.  Öffne die Token-Seite. Name, Laufzeit und die Lese-Rechte sind schon ausgefüllt – klicke unten auf „Generate token“.",
                        "1.  Open the token page. Name, lifetime and the read permissions are pre-filled – click “Generate token” at the bottom."), 10, bg=BG, wraplength=px(430)).pack(fill="x")
        Btn(d.body, T("Token-Seite öffnen", "Open token page"), lambda: webbrowser.open(github_mod.token_page_url()), kind="secondary", px=px).pack(anchor="w", pady=(px(4), px(4)))
        label(d.body, T("Tipp: Sollen auch private Repos mitzählen, wähle auf der Seite bei „Repository access“ → „All repositories“.",
                        "Tip: to count private repos too, choose “Repository access” → “All repositories” on that page."), 9, MUTED, bg=BG, wraplength=px(430)).pack(fill="x", pady=(0, px(8)))
        label(d.body, T("2.  Kopiere den Token und füge ihn hier ein:", "2.  Copy the token and paste it here:"), 10, bg=BG).pack(fill="x")
        tok = entry(d.body, px, show="•", width=44)
        tok.pack(fill="x", ipady=px(4), pady=(px(4), px(10)))
        info = label(d.body, "", 10, MUTED, bg=BG, wraplength=px(430))
        info.pack(fill="x", pady=(0, px(8)))
        row = tk.Frame(d.body, bg=BG)
        row.pack(fill="x")

        def go():
            btn.set_enabled(False)
            info.config(text=T("Prüfe …", "Checking …"), fg=MUTED)
            value = tok.get()

            def failed(e):
                btn.set_enabled(True)
                if not d.closed:
                    info.config(text=error_text(e), fg=DANGER)

            def ok(login):
                tok.delete(0, "end")
                d.close()
                self.toast(T(f"GitHub verbunden als {login}.", f"GitHub connected as {login}."))
            self.work.run(lambda: self.L.github_connect(value), on_ok=ok, on_err=failed)
        btn = Btn(row, T("Verbinden", "Connect"), go, kind="primary", px=px)
        btn.pack(side="right")
        Btn(row, T("Abbrechen", "Cancel"), d.close, kind="ghost", px=px).pack(side="right", padx=(0, px(8)))
        tok.bind("<Return>", lambda e: go())
        d.show()
        tok.focus_set()

    def dlg_check(self):
        px = self.px
        d = Dialog(self, T("Verbindungen prüfen", "Check connections"), 440)
        label(d.body, T("Verbindungen prüfen", "Check connections"), 14, bold=True, bg=BG).pack(fill="x")
        out = tk.Frame(d.body, bg=BG)
        out.pack(fill="x", pady=(px(10), px(12)))
        working = label(out, T("Prüfe …", "Checking …"), 10, MUTED, bg=BG)
        working.pack(fill="x")

        def show(results):
            working.destroy()
            for c in results:
                r = tk.Frame(out, bg=BG)
                r.pack(fill="x", pady=px(3))
                dot = Dot(r, px, bg=BG, size=10)
                dot.set(ACCENT if c.ok else MUTED if c.ok is None else DANGER)
                dot.pack(side="left", padx=(0, px(8)))
                label(r, c.name, 10, bold=True, bg=BG).pack(side="left")
                label(r, "  " + c.text, 10, MUTED, bg=BG, wraplength=px(300)).pack(side="left")
        self.work.run(self.L.check, on_ok=lambda r: None if d.closed else show(r), on_err=lambda e: None if d.closed else working.config(text=error_text(e), fg=DANGER))
        Btn(d.body, "OK", d.close, kind="primary", px=px).pack(anchor="e")
        d.show()

    def dlg_log(self):
        px = self.px
        d = Dialog(self, "Log", 640)
        label(d.body, T("Protokoll des Hintergrundprogramms", "Background program log"), 14, bold=True, bg=BG).pack(fill="x", pady=(0, px(8)))
        frame = tk.Frame(d.body, bg=BORDER)
        frame.pack(fill="both", expand=True)
        txt = tk.Text(frame, width=80, height=18, bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat", font=("Consolas", 9), wrap="none")
        sb = tk.Scrollbar(frame, command=txt.yview)
        txt.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True, padx=1, pady=1)

        def load():
            txt.config(state="normal")
            txt.delete("1.0", "end")
            txt.insert("end", self.L.log_text())
            txt.see("end")
            txt.config(state="disabled")
        load()
        row = tk.Frame(d.body, bg=BG)
        row.pack(fill="x", pady=(px(10), 0))
        Btn(row, "OK", d.close, kind="primary", px=px).pack(side="right")
        Btn(row, T("Aktualisieren", "Refresh"), load, kind="secondary", px=px).pack(side="right", padx=(0, px(8)))
        Btn(row, T("Ordner öffnen", "Open folder"), self.L.open_data_dir, kind="ghost", px=px).pack(side="left")
        d.show()

    def uninstall(self):
        from tkinter import messagebox
        if not messagebox.askyesno(
                T("Deinstallieren", "Uninstall"),
                T("Das stoppt das Programm, entfernt den Autostart, meldet bei Fluxer ab und löscht alle gespeicherten Daten (Anmeldungen, Einstellungen, Log).\n\nDie Exe selbst bleibt liegen – lösche sie danach von Hand.\n\nWirklich?",
                  "This stops the program, removes autostart, logs out of Fluxer and deletes all stored data (logins, settings, log).\n\nThe exe itself stays – delete it by hand afterwards.\n\nReally?"),
                icon="warning", parent=self.root):
            return
        self.busy = True
        self.status_text.config(text=T("Deinstalliere …", "Uninstalling …"))
        self.work.run(self.L.uninstall, on_ok=lambda r: (setattr(self, "busy", False), self.root.destroy()), on_err=self.fail)

    def run(self):
        self.root.mainloop()


def _already_open():
    """True if another launcher window of this user is open (so a second double-click does not stack windows)."""
    if os.name != "nt":
        return False
    import ctypes
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\FluxerSpotifyLauncher")
    _already_open.handle = handle  # keep it alive for the lifetime of the process
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


def _show_error(text):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Fluxer Spotify", 0x10 | 0x40000)
    else:
        print(text, file=sys.stderr)


def run(cfg, http=None):
    """Open the launcher window. Returns the process exit code."""
    if _already_open():
        return 0
    try:
        App(Launcher(cfg, http, which_exe=sys.executable)).run()
    except Exception as e:  # noqa: BLE001 - a windowed exe has no console: tell the user in a box
        import traceback
        traceback.print_exc()
        _show_error(T(f"Das Fenster konnte nicht geöffnet werden:\n{e}", f"The window could not be opened:\n{e}"))
        return 1
    return 0


__all__ = ["App", "run"]

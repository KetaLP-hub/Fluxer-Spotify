"""The launcher window, driven without a human. Skipped where there is no tkinter or no display (e.g. a headless Linux CI)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fluxer_spotify import autostart, background as bg
from fluxer_spotify.config import Config
from fluxer_spotify.errors import set_lang
from fluxer_spotify.launcher import Launcher
from fluxer_spotify.store import Store
from tests.helpers import have_tkinter, make_http

CID = "0123456789abcdef0123456789abcdef"


def display_available():
    if not have_tkinter():
        return False
    import tkinter
    try:
        root = tkinter.Tk()
        root.destroy()
        return True
    except tkinter.TclError:
        return False


HAVE_DISPLAY = display_available()


@unittest.skipUnless(HAVE_DISPLAY, "needs tkinter and a display")
class WindowTest(unittest.TestCase):
    def setUp(self):
        from fluxer_spotify import ui
        self.ui = ui
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name) / "data"
        self.d.mkdir()
        for k in [k for k in os.environ if k.startswith(("STATUS_", "FLUXER_", "SPOTIFY_", "ROTATE_", "ON_", "POLL_", "NO_ROTATE", "LANGUAGE"))]:
            p = mock.patch.dict(os.environ)
            p.start()
            self.addCleanup(p.stop)
            del os.environ[k]
        for patcher in (mock.patch.object(autostart, "available", return_value=False), mock.patch.object(bg, "is_ours", return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        set_lang("de")
        self.addCleanup(set_lang, None)
        # The window is built and driven, but never shown: tests must not flash windows on somebody's screen.
        import tkinter
        p = mock.patch.object(tkinter.Tk, "deiconify", lambda self: None)
        p.start()
        self.addCleanup(p.stop)
        self.apps = []

    def app(self, http=None, **state):
        if state:
            Store(self.d / "state.json").update(**state)
        L = Launcher(Config(data_dir=self.d), http=http or make_http()[0], which_exe=r"C:\Apps\Fluxer-Spotify.exe")
        app = self.ui.App(L)
        self.apps.append(app)
        self.addCleanup(self.close, app)
        self.pump(app, 5)
        return app

    @staticmethod
    def close(app):
        try:
            app.root.destroy()
        except Exception:
            pass

    @staticmethod
    def pump(app, rounds=1, until=None, timeout=3.0):
        """Process window events (and worker results). With `until`: wait for the condition."""
        end = time.time() + timeout
        while True:
            for _ in range(max(1, rounds)):
                app.root.update()
            if until is None or until():
                return True
            if time.time() > end:
                return False
            time.sleep(0.02)

    def test_fresh_install_shows_setup_with_spotify_first(self):
        app = self.app()
        self.assertEqual(app.status_title.cget("text"), "Einrichtung nötig")
        self.assertEqual(app.primary.cget("text"), "Spotify verbinden")
        self.assertIn("Nicht verbunden", app.conn["spotify"][1].cget("text"))
        self.assertEqual(app.root.title(), "Fluxer Spotify")

    def test_steps_follow_the_connections(self):
        app = self.app(client_id=CID, refresh="r", fluxer_token="flx_" + "T" * 36, fluxer_user="sophie")
        self.assertEqual(app.primary.cget("text"), "GitHub verbinden (empfohlen)")
        self.assertNotEqual(app.skip_btn.winfo_manager(), "")  # packed = visible
        app.skip_github()
        self.pump(app, 2)
        self.assertIn("Starten", app.primary.cget("text"))
        self.assertEqual(app.status_title.cget("text"), "Gestoppt")
        self.assertIn("sophie", app.conn["fluxer"][1].cget("text"))

    def test_running_state_offers_stop(self):
        with mock.patch.object(bg, "running_pid", return_value=4242):
            app = self.app(client_id=CID, refresh="r", fluxer_token="flx_" + "T" * 36, github_asked=True)
            self.assertEqual(app.status_title.cget("text"), "Läuft im Hintergrund")
            self.assertIn("Stoppen", app.primary.cget("text"))
            self.assertIn("4242", app.status_text.cget("text"))

    def test_start_button_starts_the_background_process(self):
        app = self.app(client_id=CID, refresh="r", fluxer_token="flx_" + "T" * 36, github_asked=True, launcher_configured=True)
        with mock.patch.object(bg, "spawn_background", return_value=99) as spawn:
            app.primary.command()
            self.assertTrue(self.pump(app, until=lambda: spawn.called))
        self.assertTrue(self.pump(app, until=lambda: not app.busy))

    def test_stop_button_calls_stop(self):
        with mock.patch.object(bg, "running_pid", return_value=4242), mock.patch.object(bg, "stop_instance", return_value="clean") as stop:
            app = self.app(client_id=CID, refresh="r", fluxer_token="flx_" + "T" * 36, github_asked=True)
            app.primary.command()
            self.assertTrue(self.pump(app, until=lambda: stop.called))

    def test_github_lines_are_locked_until_github_is_connected(self):
        app = self.app(client_id=CID, refresh="r")
        tg, _ = app.line_toggles["gh_commits"]
        self.assertFalse(tg.enabled)
        self.assertFalse(tg.get())
        tg.toggle()
        self.assertFalse(tg.get())  # a disabled switch does nothing
        self.assertTrue(app.line_toggles["now"][0].get())

    def test_saving_display_choices_writes_env(self):
        app = self.app(client_id=CID, refresh="r", github_token="t", github_user="sophie")
        self.assertTrue(app.line_toggles["gh_commits"][0].get(), "GitHub lines are on by default once connected")
        app.line_toggles["gh_stars"][0].toggle()
        app.opt["idle"].toggle()
        app.mark_dirty()
        self.assertTrue(app.save_btn.enabled)
        app.save_display()
        env = (self.d / ".env").read_text(encoding="utf-8")
        self.assertIn("gh_stars", env)
        self.assertIn("ON_IDLE=lines", env)
        self.assertFalse(app.save_btn.enabled)
        self.assertIn("Gespeichert", app.save_note.cget("text"))

    def test_saving_nothing_selected_is_refused_with_a_message(self):
        app = self.app(client_id=CID, refresh="r")
        for tg, _ in app.line_toggles.values():
            tg.set(False)
        with mock.patch.object(app, "message") as msg:
            app.save_display()
        msg.assert_called_once()
        self.assertFalse((self.d / ".env").exists())

    def test_autostart_toggle_calls_the_launcher(self):
        app = self.app()
        with mock.patch.object(app.L, "set_autostart") as setter:
            app.auto_toggle.set_enabled(True)
            app.auto_toggle.toggle()
        setter.assert_called_once_with(True)

    def test_worker_returns_results_and_errors_in_the_window_thread(self):
        app = self.app()
        got = []
        app.work.run(lambda: 41 + 1, on_ok=got.append)
        app.work.run(lambda: 1 / 0, on_err=lambda e: got.append(type(e).__name__))
        self.assertTrue(self.pump(app, until=lambda: len(got) == 2))
        self.assertEqual(sorted(map(str, got)), ["42", "ZeroDivisionError"])

    def test_buttons_ignore_clicks_while_disabled(self):
        app = self.app()
        hits = []
        b = self.ui.Btn(app.root, "x", lambda: hits.append(1), px=app.px)
        ev = mock.Mock()
        ev.type = self.ui.tk.EventType.KeyPress
        b._click(ev)
        b.set_enabled(False)
        b._click(ev)
        self.assertEqual(hits, [1])

    def test_english_ui(self):
        set_lang("en")
        app = self.app()
        self.assertEqual(app.status_title.cget("text"), "Setup needed")
        self.assertEqual(app.primary.cget("text"), "Connect Spotify")

    def test_error_texts_are_readable(self):
        from fluxer_spotify.http import HttpError, NetworkError
        self.assertIn("401", self.ui.error_text(HttpError(401, {})))
        self.assertIn("offline", self.ui.error_text(NetworkError("offline")))
        self.assertEqual(self.ui.error_text(ValueError("Klartext")), "Klartext")
        self.assertEqual(self.ui.error_text(ValueError()), "ValueError")


class WithoutDisplay(unittest.TestCase):
    def test_background_and_cli_paths_never_import_tkinter(self):
        """The 24/7 background process must not drag in the GUI toolkit (and a server without Tk must still run the CLI)."""
        import subprocess
        import sys
        code = "import sys, fluxer_spotify.cli, fluxer_spotify.launcher, fluxer_spotify.settings, fluxer_spotify.runner; print('tkinter' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


if __name__ == "__main__":
    unittest.main()

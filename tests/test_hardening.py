"""Security hardening, status expiry (STATUS_TTL), the new entry points and the GitHub helpers."""
import contextlib
import http.server
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from fluxer_spotify import __version__, background as bg, cli, github as gh, http as http_mod
from fluxer_spotify.config import Config, load_config
from fluxer_spotify.errors import AuthError, Fatal, set_lang
from fluxer_spotify.fluxer import FluxerClient
from fluxer_spotify.http import Http, HttpError
from fluxer_spotify.runner import Runner
from fluxer_spotify.spotify import Snapshot
from fluxer_spotify.store import Store
from tests.helpers import have_tkinter, make_http

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------------------------- HTTP redirects
class RedirectPolicy(unittest.TestCase):
    def handler(self):
        return http_mod._SameOriginRedirect()

    def request(self, url="https://api.spotify.com/v1/me"):
        return urllib.request.Request(url, headers={"Authorization": "Bearer geheim"})

    def test_other_host_scheme_or_port_is_not_followed(self):
        h, req = self.handler(), self.request()
        for target in ("https://evil.example/steal", "http://api.spotify.com/v1/me", "https://api.spotify.com:8443/v1/me", "https://api.spotify.com.evil.example/x"):
            self.assertIsNone(h.redirect_request(req, None, 302, "Found", {}, target), target)

    def test_same_origin_is_followed_with_relative_and_absolute_targets(self):
        h, req = self.handler(), self.request()
        for target, expect in (("/v1/other", "https://api.spotify.com/v1/other"), ("https://API.spotify.com/v1/x", "https://API.spotify.com/v1/x")):
            new = h.redirect_request(req, None, 302, "Found", {}, target)
            self.assertEqual(new.full_url, expect)
            self.assertEqual(new.get_header("Authorization"), "Bearer geheim")


class LoopbackServers(unittest.TestCase):
    """Real sockets on 127.0.0.1: the token must not travel to a second server."""

    def setUp(self):
        self.seen = []
        outer = self

        class Target(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok": true}')
            log_message = lambda *a: None

        self.target = http.server.HTTPServer(("127.0.0.1", 0), Target)
        port = self.target.server_address[1]

        class Origin(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/away":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{port}/stolen")
                elif self.path == "/same":
                    self.send_response(302)
                    self.send_header("Location", "/final")
                else:
                    outer.seen.append(("origin", self.headers.get("Authorization")))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"ok": "origin"}')
                    return
                self.end_headers()
            log_message = lambda *a: None

        self.origin = http.server.HTTPServer(("127.0.0.1", 0), Origin)
        for srv in (self.target, self.origin):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
        self.base = f"http://127.0.0.1:{self.origin.server_address[1]}"

    def test_a_redirect_to_another_server_never_receives_the_token(self):
        resp = http_mod.default_transport("GET", self.base + "/away", {"Authorization": "Bearer geheim"}, None, 5)
        self.assertEqual(resp.status, 302)
        self.assertEqual(self.seen, [], "the second server must not have been contacted at all")
        with self.assertRaises(HttpError) as cm:
            Http(retries=0).request("GET", self.base + "/away", headers={"Authorization": "Bearer geheim"})
        self.assertEqual(cm.exception.status, 302)  # a redirect is an error, not a silent empty answer

    def test_a_same_server_redirect_is_followed(self):
        data = Http(retries=0).request("GET", self.base + "/same", headers={"Authorization": "Bearer geheim"})
        self.assertEqual(data, {"ok": "origin"})
        self.assertEqual(self.seen, [("origin", "Bearer geheim")])


# ---------------------------------------------------------------------------------------------- process identity
class PidIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def test_windows_image_names(self):
        with mock.patch.object(os, "name", "nt"):
            ours = lambda img: bg.is_ours(1, image=lambda pid: img)
            for img in (r"C:\Apps\Fluxer-Spotify.exe", r"C:\Apps\FLUXER-SPOTIFY.EXE", r"C:\Python311\pythonw.exe", r"C:\Python311\python.exe"):
                self.assertTrue(ours(img), img)
            for img in (r"C:\Windows\explorer.exe", r"C:\Program Files\Spotify\Spotify.exe", r"C:\x\Fluxer-Spotify-Setup.exe"):
                self.assertFalse(ours(img), img)
            self.assertIsNone(ours(None))
            self.assertIsNone(ours(""))

    def test_a_renamed_exe_is_still_recognised_by_its_own_name(self):
        with mock.patch.object(os, "name", "nt"), mock.patch.object(sys, "executable", r"C:\Apps\MeinSpotify.exe"):
            self.assertTrue(bg.is_ours(1, image=lambda pid: r"D:\Anderswo\MeinSpotify.exe"))

    def test_posix_command_lines(self):
        with mock.patch.object(os, "name", "posix"):
            self.assertTrue(bg.is_ours(1, image=lambda p: "python3 -m fluxer_spotify run --background"))
            self.assertTrue(bg.is_ours(1, image=lambda p: "python spotify_status.py run"))
            self.assertFalse(bg.is_ours(1, image=lambda p: "/usr/bin/bash -l"))

    @unittest.skipUnless(os.name == "nt", "image path lookup is Windows-specific here")
    def test_this_very_process_is_recognised_on_windows(self):
        self.assertTrue(bg.is_ours(os.getpid()))
        self.assertIsNone(bg.is_ours(0))
        self.assertIsNone(bg.is_ours(4_000_000_000))  # no such process

    def test_pid_file_naming_a_foreign_program_is_stale(self):
        (self.d / bg.PID_NAME).write_text("4242")
        with mock.patch.object(bg, "pid_alive", return_value=True), mock.patch.object(bg, "is_ours", return_value=False):
            self.assertIsNone(bg.running_pid(self.d))
            lock = bg.InstanceLock(self.d).acquire()  # a reused PID must not lock us out
        self.assertEqual(bg.read_pid(self.d), os.getpid())
        lock.release()

    def test_unknown_identity_still_counts_as_running(self):
        (self.d / bg.PID_NAME).write_text("4242")
        with mock.patch.object(bg, "pid_alive", return_value=True), mock.patch.object(bg, "is_ours", return_value=None):
            self.assertEqual(bg.running_pid(self.d), 4242)

    def test_stop_never_terminates_a_process_it_cannot_identify(self):
        (self.d / bg.PID_NAME).write_text("4242")
        for identity in (None, False):
            kill = mock.Mock()
            (self.d / bg.PID_NAME).write_text("4242")
            with mock.patch.object(bg, "pid_alive", return_value=True), mock.patch.object(bg, "is_ours", side_effect=[True, identity]):
                self.assertEqual(bg.stop_instance(self.d, wait=1, sleep=lambda s: None, kill=kill), "unresponsive")
            kill.assert_not_called()
            self.assertFalse(bg.stop_requested(self.d))

    def test_stop_still_kills_a_verified_hung_instance(self):
        (self.d / bg.PID_NAME).write_text("4242")
        kill = mock.Mock()
        with mock.patch.object(bg, "pid_alive", return_value=True), mock.patch.object(bg, "is_ours", return_value=True):
            self.assertEqual(bg.stop_instance(self.d, wait=1, sleep=lambda s: None, kill=kill), "killed")
        kill.assert_called_once_with(4242)

    def test_stop_command_explains_the_unresponsive_case(self):
        set_lang("de")
        self.addCleanup(set_lang, None)
        c = cli.Ctx(Config(data_dir=self.d), None, None, None)
        with mock.patch.object(bg, "stop_instance", return_value="unresponsive"), contextlib.redirect_stdout(io.StringIO()) as out:
            c.stop()
        self.assertIn("Task-Manager", out.getvalue())
        self.assertIn("nichts wurde beendet", out.getvalue())


# ---------------------------------------------------------------------------------------------- console / pop-up
class WindowedExe(unittest.TestCase):
    def test_attach_parent_console_gives_missing_streams_a_terminal(self):
        k32 = mock.Mock()
        k32.AttachConsole.return_value = 1
        opened = []

        def fake_open(device, mode="r", **kw):
            opened.append((device, mode))
            return io.StringIO()

        with mock.patch.object(os, "name", "nt"), mock.patch("ctypes.windll", create=True) as win, mock.patch("builtins.open", fake_open), \
                mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None), mock.patch.object(sys, "stdin", None):
            win.kernel32 = k32
            self.assertTrue(bg.attach_parent_console())
            self.assertIsNotNone(sys.stdout)
        k32.AttachConsole.assert_called_once_with(0xFFFFFFFF)
        self.assertEqual(opened, [("CONOUT$", "w"), ("CONOUT$", "w"), ("CONIN$", "r")])

    def test_redirected_streams_are_left_alone_and_a_missing_console_is_fine(self):
        keep = io.StringIO()
        k32 = mock.Mock()
        k32.AttachConsole.return_value = 1
        with mock.patch.object(os, "name", "nt"), mock.patch("ctypes.windll", create=True) as win, mock.patch("builtins.open") as op, \
                mock.patch.object(sys, "stdout", keep), mock.patch.object(sys, "stderr", keep), mock.patch.object(sys, "stdin", keep):
            win.kernel32 = k32
            bg.attach_parent_console()
            self.assertIs(sys.stdout, keep)
            op.assert_not_called()
            k32.AttachConsole.return_value = 0  # started by double-click: no parent console
            self.assertFalse(bg.attach_parent_console())
        with mock.patch.object(os, "name", "posix"):
            self.assertFalse(bg.attach_parent_console())

    def test_notice_text_is_kept_for_the_launcher_window(self):
        with tempfile.TemporaryDirectory() as d:
            box = mock.Mock()
            self.assertIsNone(bg.read_attention(d))
            bg.notify_once(d, "Bitte neu anmelden.", messagebox=box)
            self.assertEqual(bg.read_attention(d), "Bitte neu anmelden.")
            bg.clear_attention(d)
            self.assertIsNone(bg.read_attention(d))

    def test_popup_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"FLUXER_SPOTIFY_NO_POPUP": "1"}):
            self.assertTrue(bg.notify_once(d, "Hinweis"))  # would crash if it tried a real Windows message box
            self.assertEqual(bg.read_attention(d), "Hinweis")


# ---------------------------------------------------------------------------------------------- status expiry
class FakeFluxer:
    def __init__(self, reject_ttl=False):
        self.calls, self.reject_ttl = [], reject_ttl

    def set_status(self, text, ttl=None):
        if ttl and self.reject_ttl:
            raise HttpError(400, {"code": "INVALID_FORM_BODY"})
        self.calls.append((text, ttl))


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def playing(track="t1"):
    item = {"id": track, "name": "Song", "artists": [{"name": "A"}], "album": {"name": "Alb"}}
    return Snapshot((track, True), True, item, {}, None)


class StatusExpiry(unittest.TestCase):
    def runner(self, fx, **cfg):
        self.clock = Clock()
        sp = mock.Mock()
        sp.snapshot.return_value = playing()
        return Runner(Config(data_dir=Path("."), lines=("now",), **cfg), sp, fx, clock=self.clock)

    def test_client_sends_expires_at_only_when_asked(self):
        http, t, _ = make_http((200, {}), (200, {}), (200, {}))
        fx = FluxerClient(http, "https://api.fluxer.app/v1", "flx_" + "T" * 36)
        fx.set_status("🎵 Song", ttl=600, clock=lambda: 0)
        fx.set_status("🎵 Song")
        fx.set_status(None, ttl=600, clock=lambda: 0)
        self.assertEqual(t.calls[0][3], {"custom_status": {"text": "🎵 Song", "expires_at": "1970-01-01T00:10:00.000Z"}})
        self.assertEqual(t.calls[1][3], {"custom_status": {"text": "🎵 Song"}})
        self.assertEqual(t.calls[2][3], {"custom_status": None})  # clearing never carries an expiry

    def test_status_is_renewed_after_a_third_of_its_lifetime(self):
        fx = FakeFluxer()
        r = self.runner(fx, ttl=300.0)
        r.tick()
        self.clock.t += 99
        r.tick()
        self.assertEqual(len(fx.calls), 1, "not yet due")
        self.clock.t += 2
        r.tick()
        self.assertEqual(fx.calls, [("🎵 Song – A", 300.0)] * 2)

    def test_without_ttl_nothing_is_resent_and_the_old_call_shape_is_kept(self):
        fx = mock.Mock()
        r = self.runner(fx)
        r.tick()
        self.clock.t += 5000
        r.tick()
        fx.set_status.assert_called_once_with("🎵 Song – A")

    def test_clearing_is_not_renewed(self):
        fx = FakeFluxer()
        r = self.runner(fx, ttl=300.0)
        r.spotify.snapshot.return_value = Snapshot("idle", False, None, {}, None)
        r.tick()
        self.clock.t += 1000
        r.tick()
        self.assertEqual(fx.calls, [(None, None)])

    def test_an_expiry_fluxer_rejects_is_dropped_and_the_status_still_gets_set(self):
        fx = FakeFluxer(reject_ttl=True)
        r = self.runner(fx, ttl=300.0)
        with self.assertLogs("fluxer_spotify.run", level="WARNING") as cm:
            r.tick()
        self.assertEqual(fx.calls, [("🎵 Song – A", None)])
        self.assertEqual(r.cfg.ttl, 0)
        self.assertIn("STATUS_TTL", cm.output[0])
        self.clock.t += 5000
        r.tick()
        self.assertEqual(len(fx.calls), 1, "no endless resending once expiry is off")


class TtlConfig(unittest.TestCase):
    def cfg(self, **env):
        with tempfile.TemporaryDirectory() as d:
            return load_config(None, {"FLUXER_SPOTIFY_HOME": d, **env})

    def test_values(self):
        self.assertEqual(self.cfg().ttl, 0)
        self.assertEqual(self.cfg(STATUS_TTL="0").ttl, 0)
        self.assertEqual(self.cfg(STATUS_TTL="600").ttl, 600)
        self.assertEqual(self.cfg(STATUS_TTL="30").ttl, 120, "too short would mean a PATCH every few seconds")
        self.assertEqual(self.cfg(STATUS_TTL="9999999").ttl, 86400)

    def test_bad_values(self):
        for bad in ("-5", "bald", "nan"):
            with self.assertRaises(Fatal, msg=bad):
                self.cfg(STATUS_TTL=bad)

    def test_flag_and_background_hand_over(self):
        args = cli.build_parser().parse_args(["run", "--ttl", "900"])
        with tempfile.TemporaryDirectory() as d:
            args.data_dir = d
            self.assertEqual(load_config(args, {}).ttl, 900)
            c = cli.Ctx(Config(data_dir=Path(d), ttl=900.0), None, None, None)
            with mock.patch.object(bg, "spawn_background", return_value=1) as spawn, contextlib.redirect_stdout(io.StringIO()), mock.patch("time.sleep"):
                c.start_background()
            extra = spawn.call_args.args[1]
            self.assertEqual(extra[extra.index("--ttl") + 1], "900.0")


# ---------------------------------------------------------------------------------------------- entry points
class Entry(unittest.TestCase):
    def test_double_click_opens_the_window_and_arguments_do_not(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(cli, "main", return_value=0) as main:
            with mock.patch.object(sys, "argv", ["Fluxer-Spotify.exe"]):
                cli.entry()
            main.assert_called_once_with(["gui"], keep_lang=True)
            main.reset_mock()
            with mock.patch.object(sys, "argv", ["Fluxer-Spotify.exe", "stop"]), mock.patch.object(sys, "stdout", io.StringIO()):
                cli.entry()
            main.assert_called_once_with(None, keep_lang=True)

    def test_source_runs_keep_the_console_wizard(self):
        with mock.patch.object(cli, "main", return_value=0) as main, mock.patch.object(sys, "argv", ["spotify_status.py"]):
            cli.entry()
        main.assert_called_once_with(None, keep_lang=True)

    def test_windowed_exe_with_arguments_attaches_to_the_terminal(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(cli, "main", return_value=0), \
                mock.patch.object(sys, "argv", ["Fluxer-Spotify.exe", "logs"]), mock.patch.object(sys, "stdout", None), \
                mock.patch.object(bg, "attach_parent_console") as attach:
            cli.entry()
        attach.assert_called_once()

    def test_an_error_without_a_terminal_does_not_crash_on_input(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(cli, "main", return_value=1), \
                mock.patch.object(sys, "argv", ["Fluxer-Spotify.exe", "status"]), mock.patch.object(sys, "stdin", None), \
                mock.patch("builtins.input", side_effect=AssertionError("no terminal to ask")):
            self.assertEqual(cli.entry(), 1)

    def test_gui_command_hands_over_to_the_window(self):
        fake = mock.Mock()
        fake.run.return_value = 0
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(sys.modules, {"fluxer_spotify.ui": fake}), mock.patch("fluxer_spotify.ui", fake, create=True):
            self.assertEqual(cli.main(["gui", "--data-dir", d, "--lang", "de"], http=make_http()[0]), 0)
        self.assertEqual(fake.run.call_args.args[0].data_dir, Path(d))

    @unittest.skipUnless(have_tkinter(), "tkinter is not usable here")
    def test_selftest(self):
        with mock.patch.dict(sys.modules), mock.patch("tkinter.Tk") as tk:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(["--selftest"]), 0)
            self.assertIn(__version__, out.getvalue())
            tk.return_value.destroy.assert_called_once()
            tk.side_effect = RuntimeError("no display")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(cli.main(["--selftest"]), 1)
            self.assertIn("no display", err.getvalue())


class Supervisor(unittest.TestCase):
    """24/7 mode: unexpected errors are survived, anything that needs the user is not."""

    def setUp(self):
        self.ctx = cli.Ctx(Config(data_dir=Path(".")), None, None, None, background=True)
        self.sleeps = []
        self.clock = Clock()

    def run_with(self, *outcomes):
        runner = mock.Mock()
        runner.run.side_effect = list(outcomes)
        self.ctx._supervise(runner, self.sleeps.append, clock=self.clock)
        return runner

    def test_unexpected_errors_back_off_and_carry_on(self):
        with self.assertLogs("fluxer_spotify", level="ERROR"), self.assertRaises(cli.Stop):
            runner = self.run_with(ValueError("kaputt"), KeyError("auch"), RuntimeError("und noch"), cli.Stop())
        self.assertEqual(self.sleeps, [15, 30, 60])

    def test_backoff_is_capped_and_resets_after_a_long_quiet_run(self):
        outcomes = [ValueError()] * 7 + [cli.Stop()]
        with self.assertLogs("fluxer_spotify", level="ERROR"), self.assertRaises(cli.Stop):
            self.run_with(*outcomes)
        self.assertEqual(self.sleeps, [15, 30, 60, 120, 240, 300, 300])

        self.sleeps.clear()
        runner = mock.Mock()

        def quiet_then_fail(sleep=None):
            self.clock.t += 700  # it ran for a good while before this error
            raise ValueError()
        calls = iter([quiet_then_fail, quiet_then_fail, cli.Stop()])

        def run(sleep=None):
            nxt = next(calls)
            if isinstance(nxt, Exception):
                raise nxt
            nxt(sleep)
        runner.run.side_effect = run
        with self.assertLogs("fluxer_spotify", level="ERROR"), self.assertRaises(cli.Stop):
            self.ctx._supervise(runner, self.sleeps.append, clock=self.clock)
        self.assertEqual(self.sleeps, [15, 15], "a long quiet run starts the back-off over")

    def test_things_that_need_the_user_end_the_run(self):
        for exc in (AuthError("Login weg"), Fatal("nein"), KeyboardInterrupt(), cli.Stop()):
            self.sleeps.clear()
            with self.assertRaises(type(exc)):
                self.run_with(exc)
            self.assertEqual(self.sleeps, [])

    def test_foreground_runs_are_not_supervised(self):
        fg = cli.Ctx(Config(data_dir=Path(".")), None, None, None, background=False)
        self.assertFalse(fg.background)  # _run() only calls _supervise when background is set


# ---------------------------------------------------------------------------------------------- GitHub helpers
class GitHubHelpers(unittest.TestCase):
    def test_token_page_is_prefilled_read_only(self):
        u = urllib.parse.urlparse(gh.token_page_url())
        q = dict(urllib.parse.parse_qsl(u.query))
        self.assertEqual((u.scheme, u.netloc, u.path), ("https", "github.com", "/settings/personal-access-tokens/new"))
        self.assertEqual((q["pull_requests"], q["issues"], q["expires_in"], q["name"]), ("read", "read", "365", "Fluxer-Spotify"))
        self.assertNotIn("write", gh.token_page_url())
        self.assertNotIn("admin", gh.token_page_url())
        self.assertLessEqual(len(q["name"]), 40)  # GitHub's documented limit

    def test_connect_strips_quotes_validates_and_stores(self):
        with tempfile.TemporaryDirectory() as d:
            st = Store(Path(d) / "state.json")
            http, t, _ = make_http((200, {"login": "KetaLP-hub"}))
            self.assertEqual(gh.connect(http, st, " 'github_pat_abc' "), "KetaLP-hub")
            self.assertEqual(st.get("github_token"), "github_pat_abc")
            self.assertEqual(t.calls[0][2]["Authorization"], "Bearer github_pat_abc")
            gh.disconnect(st)
            self.assertIsNone(st.get("github_token"))
            self.assertIsNone(st.get("github_user"))

    def test_rejected_or_empty_token_is_not_stored(self):
        with tempfile.TemporaryDirectory() as d:
            st = Store(Path(d) / "state.json")
            with self.assertRaises(AuthError):
                gh.connect(make_http((401, {"message": "Bad credentials"}))[0], st, "falsch")
            with self.assertRaises(Fatal):
                gh.connect(make_http()[0], st, "   ")
            self.assertIsNone(st.get("github_token"))

    def test_cli_github_login_shows_and_opens_the_prefilled_page(self):
        set_lang("de")
        self.addCleanup(set_lang, None)
        with tempfile.TemporaryDirectory() as d:
            opened = []
            c = cli.Ctx(Config(data_dir=Path(d)), make_http((200, {"login": "sophie"}))[0], lambda p="": "github_pat_xyz", None, open_browser=opened.append)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                c.github_login()
        self.assertEqual(opened, [gh.token_page_url()])
        self.assertIn("pull_requests=read", out.getvalue())
        self.assertIn("sophie", out.getvalue())


# ---------------------------------------------------------------------------------------------- release files stay consistent
class NoRealDesktop(unittest.TestCase):
    def test_tests_cannot_open_a_real_browser_or_explorer_window(self):
        import webbrowser
        for opener in (webbrowser.open, webbrowser.open_new, webbrowser.open_new_tab):
            with self.assertRaises(RuntimeError):
                opener("https://github.com/")
        if hasattr(os, "startfile"):
            with self.assertRaises(RuntimeError):
                os.startfile(".")

    def test_the_default_browser_argument_of_the_program_is_the_guard_too(self):
        import inspect
        default = inspect.signature(cli.Ctx.__init__).parameters["open_browser"].default
        with self.assertRaises(RuntimeError):
            default("https://github.com/")


class ReleaseFiles(unittest.TestCase):
    def test_version_resource_matches_the_package_version(self):
        text = (ROOT / "version_info.txt").read_text(encoding="utf-8")
        nums = tuple(int(x) for x in re.search(r"filevers=\(([\d, ]+)\)", text).group(1).split(","))
        self.assertEqual(".".join(map(str, nums[:3])), __version__)
        self.assertEqual(re.search(r"StringStruct\('FileVersion', '([\d.]+)'\)", text).group(1), ".".join(map(str, nums)))
        self.assertEqual(re.search(r"StringStruct\('ProductVersion', '([\d.]+)'\)", text).group(1), ".".join(map(str, nums)))

    def test_local_build_and_release_workflow_use_the_same_pyinstaller_flags(self):
        def flags(path):
            line = re.search(r"-m PyInstaller (.+)", (ROOT / path).read_text(encoding="utf-8")).group(1)
            line = line.replace("\\", "/").replace("||", "").replace("exit /b 1", "")
            return sorted(t for t in re.findall(r'"[^"]*"|\S+', line) if t.startswith("--") or t.startswith('"'))
        bat, yml = flags("build_exe.bat"), flags(".github/workflows/release.yml")
        self.assertEqual(bat, yml)
        for must in ("--windowed", "--noupx", "--onefile", "--icon", "--version-file"):
            self.assertIn(must, bat)

    def test_icon_and_version_files_exist_and_workflow_checks_the_exe(self):
        self.assertGreater((ROOT / "assets" / "icon.ico").stat().st_size, 5000)
        yml = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        for needed in ("--selftest", "ProductName", "Get-AuthenticodeSignature", "WINDOWS_CERT_PFX_BASE64", "signtool"):
            self.assertIn(needed, yml)
        self.assertNotIn("--console", yml)


if __name__ == "__main__":
    unittest.main()

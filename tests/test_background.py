import ctypes  # noqa: F401 - must be imported before os.name is patched to "nt"
import contextlib
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fluxer_spotify import autostart, background as bg, cli, wizard
from fluxer_spotify.config import Config
from fluxer_spotify.errors import AuthError, Fatal
from tests import test_wizard as tw
from tests.helpers import make_http


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "data"
        self.d.mkdir()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.close_logs)

    @staticmethod
    def close_logs():  # Windows cannot delete a temp dir holding an open log file
        root = logging.getLogger("fluxer_spotify")
        for h in list(root.handlers):
            h.close()
            root.removeHandler(h)

    def bg_ctx(self, **cfg):
        c = cli.Ctx(Config(data_dir=self.d, **cfg), make_http()[0], cli._no_prompt, cli._no_prompt,
                    open_browser=cli._no_prompt, background=True)
        return c


class HiddenMode(Base):
    def test_streams_none_get_a_sink(self):
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            bg.fix_streams()
            print("x")
            print("y", file=sys.stderr)  # must not raise
            sys.stdout.close()
            sys.stderr.close()

    def test_main_background_with_no_stdio_logs_to_file_and_never_prompts(self):
        prompt = mock.Mock(side_effect=AssertionError("must not prompt"))
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None), \
                mock.patch.object(bg, "hide_console") as hide, mock.patch.object(bg, "notify_once") as note:
            rc = cli.main(["run", "--background", "--lang", "en", "--data-dir", str(self.d)], http=make_http()[0],
                          getpass_fn=prompt, input_fn=prompt)
            sys.stdout.close()
            sys.stderr.close()
        self.assertEqual(rc, 1)
        hide.assert_called_once()
        note.assert_called_once()
        prompt.assert_not_called()
        logtxt = (self.d / bg.LOG_NAME).read_text(encoding="utf-8")
        self.assertIn("Setup incomplete", logtxt)

    def test_hidden_alias_and_default_command(self):
        args = cli.build_parser().parse_args(["--hidden"])
        self.assertTrue(args.background)

    def test_incomplete_setup_does_not_block_and_notifies_once(self):
        c = self.bg_ctx()
        with mock.patch.object(bg, "notify_once") as note:
            self.assertEqual(c.run(), 1)
        note.assert_called_once()
        self.assertFalse((self.d / bg.PID_NAME).exists())

    def test_expired_spotify_token_does_not_open_browser(self):
        (self.d / "state.json").write_text(json.dumps({"client_id": tw.CID, "refresh": "rr", "fluxer_token": tw.TOKEN}))
        c = self.bg_ctx()

        class Sp(tw.FakeSpotify):
            def login(self, open_browser=None, **_):
                open_browser("https://accounts.spotify.com")

        c.spotify = lambda: Sp(refresh_error=AuthError("expired"))
        with mock.patch.object(bg, "notify_once") as note, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(c.run(), 1)
        note.assert_called_once()

    def test_second_background_start_exits_quietly(self):
        (self.d / bg.PID_NAME).write_text("4242")
        with mock.patch.object(bg, "pid_alive", return_value=True), mock.patch.object(bg, "notify_once") as note:
            self.assertEqual(self.bg_ctx().run(), 0)
        note.assert_not_called()
        self.assertEqual((self.d / bg.PID_NAME).read_text(), "4242")  # foreign lock untouched

    def test_hide_console_hides_own_window_but_not_a_shared_terminal(self):
        k32, u32 = mock.Mock(), mock.Mock()
        k32.GetConsoleWindow.return_value = 77
        with mock.patch.object(os, "name", "nt"), mock.patch("ctypes.windll", create=True) as win:
            win.kernel32, win.user32 = k32, u32
            k32.GetConsoleProcessList.return_value = 2  # onefile exe: bootloader + child
            self.assertTrue(bg.hide_console(frozen=True))
            u32.ShowWindow.assert_called_once_with(77, bg.SW_HIDE)
            u32.ShowWindow.reset_mock()
            k32.GetConsoleProcessList.return_value = 3  # + cmd.exe
            self.assertFalse(bg.hide_console(frozen=True))
            k32.GetConsoleProcessList.return_value = 2  # source run from cmd.exe: python + cmd
            self.assertFalse(bg.hide_console(frozen=False))
            u32.ShowWindow.assert_not_called()
            k32.GetConsoleWindow.return_value = 0  # detached: no console
            self.assertFalse(bg.hide_console(frozen=True))

    def test_notify_once(self):
        box = mock.Mock()
        self.assertTrue(bg.notify_once(self.d, "hi", messagebox=box))
        self.assertFalse(bg.notify_once(self.d, "hi", messagebox=box))
        box.assert_called_once()
        bg.clear_attention(self.d)
        self.assertTrue(bg.notify_once(self.d, "hi", messagebox=box))

    def test_entry_does_not_wait_for_enter_in_background(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(cli, "main", return_value=1), \
                mock.patch.object(sys, "argv", ["x.exe", "run", "--background"]), mock.patch("builtins.input") as inp:
            self.assertEqual(cli.entry(), 1)
        inp.assert_not_called()


class SingleInstance(Base):
    def test_acquire_release_and_second_blocked(self):
        lock = bg.InstanceLock(self.d).acquire()
        self.assertEqual(bg.read_pid(self.d), os.getpid())
        self.assertTrue(bg.pid_alive(os.getpid()))
        with mock.patch.object(bg, "pid_alive", return_value=True), mock.patch.object(os, "getpid", return_value=999):
            with self.assertRaises(bg.AlreadyRunning):
                bg.InstanceLock(self.d).acquire()
        lock.release()
        self.assertFalse((self.d / bg.PID_NAME).exists())
        bg.InstanceLock(self.d).acquire().release()

    def test_stale_pid_file_is_taken_over(self):
        (self.d / bg.PID_NAME).write_text("99999999")
        (self.d / bg.STOP_NAME).write_text("1")  # leftover stop request must not kill the new instance
        with mock.patch.object(bg, "pid_alive", return_value=False):
            lock = bg.InstanceLock(self.d).acquire()
        self.assertEqual(bg.read_pid(self.d), os.getpid())
        self.assertFalse(bg.stop_requested(self.d))
        lock.release()

    def test_garbage_pid_file_counts_as_stale(self):
        (self.d / bg.PID_NAME).write_text("not a number")
        bg.InstanceLock(self.d).acquire().release()

    def test_foreground_run_refuses_when_running(self):
        (self.d / bg.PID_NAME).write_text("4242")
        c = cli.Ctx(Config(data_dir=self.d), None, None, None)
        with mock.patch.object(bg, "pid_alive", return_value=True):
            with self.assertRaises(bg.AlreadyRunning) as cm:
                c.run()
        self.assertIn("stop", str(cm.exception))

    def test_status_reports_background_instance(self):
        c = cli.Ctx(Config(data_dir=self.d), None, None, None)
        with mock.patch.object(bg, "running_pid", return_value=4242), contextlib.redirect_stdout(io.StringIO()) as out:
            c.doctor()
        self.assertIn("4242", out.getvalue())
        with mock.patch.object(bg, "running_pid", return_value=None), contextlib.redirect_stdout(io.StringIO()) as out:
            c.doctor()
        self.assertIn("No instance is running", out.getvalue())


class Stop(Base):
    def test_nothing_running(self):
        self.assertEqual(bg.stop_instance(self.d), "none")

    def test_clean_stop_goes_through_stop_file(self):
        (self.d / bg.PID_NAME).write_text("4242")
        seen = []
        alive = iter([True, True, False])  # running_pid check, one wait loop, then gone

        def sleep(_):
            seen.append(bg.stop_requested(self.d))

        with mock.patch.object(bg, "pid_alive", side_effect=lambda p: next(alive)):
            self.assertEqual(bg.stop_instance(self.d, sleep=sleep, kill=mock.Mock(side_effect=AssertionError)), "clean")
        self.assertEqual(seen, [True])
        self.assertFalse(bg.stop_requested(self.d))

    def test_unresponsive_instance_is_killed(self):
        (self.d / bg.PID_NAME).write_text("4242")
        kill = mock.Mock()
        with mock.patch.object(bg, "pid_alive", return_value=True):
            self.assertEqual(bg.stop_instance(self.d, wait=1, sleep=lambda s: None, kill=kill), "killed")
        kill.assert_called_once_with(4242)
        self.assertFalse((self.d / bg.PID_NAME).exists())

    def test_loop_sleep_raises_on_stop_request(self):
        class Halt(Exception):
            pass
        sl = bg.make_stop_sleep(self.d, sleep=lambda s: None, stop_exc=Halt)
        sl(0)
        (self.d / bg.STOP_NAME).write_text("1")
        with self.assertRaises(Halt):
            sl(30)

    def test_stop_command_after_kill_clears_status_itself(self):
        (self.d / "state.json").write_text(json.dumps({"fluxer_token": tw.TOKEN, "fluxer_token_source": "login"}))
        http, t, _ = make_http((200, {}))
        c = cli.Ctx(Config(data_dir=self.d), http, None, None)
        with mock.patch.object(bg, "stop_instance", return_value="killed"), contextlib.redirect_stdout(io.StringIO()):
            c.stop()
        self.assertEqual(t.calls[0][0], "PATCH")

    def test_main_stop_with_nothing_running(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["stop", "--lang", "en", "--data-dir", str(self.d)]), 0)
        self.assertIn("No instance", out.getvalue())


class Spawn(Base):
    def test_frozen_command_is_the_exe_itself(self):
        argv, cwd = bg.background_command(self.d, ["--interval", "5"], frozen=True, executable=r"C:\Apps\Fluxer-Spotify.exe")
        self.assertEqual(argv, [r"C:\Apps\Fluxer-Spotify.exe", "run", "--background", "--data-dir", str(self.d), "--interval", "5"])
        self.assertNotIn("-m", argv)

    def test_source_command_prefers_pythonw(self):
        (self.d / "python.exe").write_text("")
        (self.d / "pythonw.exe").write_text("")
        argv, cwd = bg.background_command("D", frozen=False, executable=str(self.d / "python.exe"))
        self.assertEqual(argv[:3], [str(self.d / "pythonw.exe"), "-m", "fluxer_spotify"])
        self.assertTrue((Path(cwd) / "fluxer_spotify").is_dir())  # -m needs the package on the path
        (self.d / "pythonw.exe").unlink()
        argv, _ = bg.background_command("D", frozen=False, executable=str(self.d / "python.exe"))
        self.assertEqual(argv[0], str(self.d / "python.exe"))

    def test_spawn_is_detached_and_waits_for_child(self):
        popen = mock.Mock()
        with mock.patch.object(bg, "running_pid", side_effect=[None, 31337]):
            pid = bg.spawn_background(self.d, popen=popen, frozen=True, executable="x.exe", sleep=lambda s: None)
        self.assertEqual(pid, 31337)
        (argv,), kw = popen.call_args
        self.assertEqual(argv[:3], ["x.exe", "run", "--background"])
        want = (bg.CREATE_NO_WINDOW | bg.DETACHED_PROCESS) if os.name == "nt" else 0
        self.assertEqual(kw["creationflags"], want)
        self.assertEqual((kw["stdin"], kw["stdout"], kw["stderr"]), (subprocess.DEVNULL,) * 3)

    def test_spawn_reports_failure_when_child_never_appears(self):
        with mock.patch.object(bg, "running_pid", return_value=None):
            self.assertIsNone(bg.spawn_background(self.d, popen=mock.Mock(), frozen=True, executable="x", wait=1,
                                                  sleep=lambda s: None))


class WizardHandoff(tw.WizardCase):
    def done(self):
        self.done_state(autostart_asked=True)
        return self.ctx(http=make_http((200, {}))[0])

    def test_yes_hands_over_and_exits(self):
        self.done_state(autostart_asked=True)
        c = self.ctx(inputs=["j"], http=make_http((200, {}))[0])
        c.start_background = mock.Mock(return_value=True)
        with mock.patch.object(bg, "available", return_value=True):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertTrue(wizard.setup(c))
        c.start_background.assert_called_once()
        self.assertTrue(self.state()["background_asked"])
        self.assertIn("stop", out.getvalue())  # the notice names the stop command...
        self.assertIn("Task Manager", out.getvalue())  # ...and the Task Manager entry

    def test_no_continues_in_this_window_and_asks_only_once(self):
        self.done_state(autostart_asked=True)
        c = self.ctx(inputs=["n"], http=make_http((200, {}))[0])
        c.start_background = mock.Mock()
        with mock.patch.object(bg, "available", return_value=True):
            self.run_wizard(c)
            c2 = self.ctx(http=make_http((200, {}))[0])  # no input available: would raise StopIteration if asked again
            self.run_wizard(c2)
        c.start_background.assert_not_called()

    def test_non_interactive_skips_offers(self):
        self.done_state()
        c = self.ctx(http=make_http((200, {}))[0])
        with mock.patch.object(bg, "available", return_value=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(wizard.setup(c, interactive=False))

    def test_start_background_passes_data_dir_and_releases_lock(self):
        c = cli.Ctx(Config(data_dir=self.d), None, None, None)
        c._lock = bg.InstanceLock(self.d).acquire()
        with mock.patch.object(bg, "spawn_background", return_value=555) as sp, mock.patch.object(cli.time, "sleep"), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(c.start_background())
        self.assertFalse((self.d / bg.PID_NAME).exists())  # child can take the lock
        self.assertEqual(sp.call_args[0][0], self.d)
        # failure: stay in this window and hold the lock again
        with mock.patch.object(bg, "spawn_background", side_effect=OSError("boom")), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(c.start_background())
        self.assertEqual(bg.read_pid(self.d), os.getpid())
        c._lock.release()


class Uninstall(Base):
    def files(self):
        for n in ("state.json", ".env", bg.LOG_NAME, bg.PID_NAME):
            (self.d / n).write_text("{}" if n == "state.json" else "x")

    def test_confirmed_removes_everything_and_the_empty_folder(self):
        self.files()
        c = cli.Ctx(Config(data_dir=self.d), make_http()[0], None, lambda p="": "j")
        with mock.patch.object(autostart, "available", return_value=True), \
                mock.patch.object(autostart, "uninstall", return_value=Path("x")) as un, \
                mock.patch.object(bg, "stop_instance", return_value="none") as st, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(c.uninstall(), None)
        un.assert_called_once()
        st.assert_called_once()
        self.assertFalse(self.d.exists())

    def test_declined_keeps_everything(self):
        self.files()
        c = cli.Ctx(Config(data_dir=self.d), make_http()[0], None, lambda p="": "n")
        with mock.patch.object(bg, "stop_instance") as st, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(c.uninstall(), 1)
        st.assert_not_called()
        self.assertTrue((self.d / "state.json").exists())

    def test_foreign_files_survive(self):
        self.files()
        (self.d / "keep.txt").write_text("mine")
        c = cli.Ctx(Config(data_dir=self.d), make_http()[0], None, lambda p="": "y")
        with mock.patch.object(autostart, "available", return_value=False), mock.patch.object(bg, "stop_instance", return_value="none"), \
                contextlib.redirect_stdout(io.StringIO()):
            c.uninstall()
        self.assertEqual([p.name for p in self.d.iterdir()], ["keep.txt"])  # never rmtree


class Logs(Base):
    def test_tail_prints_last_50(self):
        (self.d / bg.LOG_NAME).write_text("\n".join(f"line{i}" for i in range(80)), encoding="utf-8")
        c = cli.Ctx(Config(data_dir=self.d), None, None, None)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            c.logs()
        lines = out.getvalue().splitlines()
        self.assertEqual((len(lines), lines[0], lines[-1]), (50, "line30", "line79"))


if __name__ == "__main__":
    unittest.main()

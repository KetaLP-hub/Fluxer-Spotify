"""The launcher's logic (no window): state shown, start/stop, logins, settings, uninstall."""
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fluxer_spotify import autostart, background as bg, launcher as lm, settings
from fluxer_spotify.config import Config
from fluxer_spotify.errors import AuthError, Fatal, LoginError, set_lang
from fluxer_spotify.launcher import Launcher
from fluxer_spotify.store import Store
from tests.helpers import make_http

EXE = r"C:\Users\me\Programs\Fluxer-Spotify\Fluxer-Spotify.exe"
CID = "0123456789abcdef0123456789abcdef"
FLX = "flx_" + "T" * 36
ENV_PREFIXES = ("STATUS_", "FLUXER_", "SPOTIFY_", "ROTATE_", "ON_", "POLL_", "NO_ROTATE", "LANGUAGE")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name) / "data"
        self.d.mkdir()
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        for k in [k for k in os.environ if k.startswith(ENV_PREFIXES)]:
            del os.environ[k]
        for patcher in (mock.patch.object(autostart, "available", return_value=False), mock.patch.object(bg, "is_ours", return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        set_lang("de")
        self.addCleanup(set_lang, None)
        self.addCleanup(self.close_logs)

    @staticmethod
    def close_logs():
        root = logging.getLogger("fluxer_spotify")
        for h in list(root.handlers):
            h.close()
            root.removeHandler(h)

    def state(self, **data):
        if data:
            Store(self.d / "state.json").update(**data)
        return Store(self.d / "state.json").data

    def env(self, text):
        (self.d / ".env").write_text(text, encoding="utf-8")

    def make(self, *script, exe=EXE, **state):
        if state:
            self.state(**state)
        http, transport, _ = make_http(*script)
        return Launcher(Config(data_dir=self.d), http=http, which_exe=exe), transport


class Snapshots(Base):
    def test_fresh_install_needs_spotify_first(self):
        s = self.make()[0].snapshot()
        self.assertEqual((s.next_step, s.ready, s.running), ("spotify", False, False))
        self.assertEqual(s.lines, ("now", "playlist", "top_artist", "listening_today"))
        self.assertFalse(s.spotify.connected or s.fluxer.connected or s.github.connected)
        self.assertEqual(s.version, lm.__version__)

    def test_setup_steps_in_order_and_github_is_offered_once(self):
        L, _ = self.make(client_id=CID, refresh="r")
        self.assertEqual(L.snapshot().next_step, "fluxer")
        self.state(fluxer_token=FLX, fluxer_token_source="login", fluxer_user="sophie")
        s = L.snapshot()
        self.assertEqual((s.next_step, s.ready, s.fluxer.detail), ("github", True, "sophie"))
        L.github_skip()
        self.assertEqual(L.snapshot().next_step, "start")
        with mock.patch.object(bg, "running_pid", return_value=4242):
            s = L.snapshot()
        self.assertEqual((s.next_step, s.running, s.pid), (None, True, 4242))

    def test_webhook_only_counts_as_ready(self):
        self.env("FLUXER_WEBHOOK=https://api.fluxer.app/v1/webhooks/1/abc\n")
        s = self.make(client_id=CID, refresh="r", github_asked=True)[0].snapshot()
        self.assertTrue(s.ready and s.webhook)
        self.assertEqual(s.next_step, "start")

    def test_connecting_github_adds_its_lines_unless_status_lines_is_set(self):
        L, _ = self.make(client_id=CID, refresh="r", github_token="t", github_user="sophie")
        s = L.snapshot()
        self.assertEqual(s.github.detail, "sophie")
        self.assertIn("gh_commits", s.lines)
        self.assertNotIn("gh_stars", s.lines)
        self.assertEqual(s.lines, s.default_lines)
        self.env("STATUS_LINES=now,gh_stars\n")
        self.assertEqual(L.snapshot().lines, ("now", "gh_stars"))

    def test_invalid_env_file_is_reported_not_raised(self):
        self.env("ROTATE_SECONDS=schnell\n")
        s = self.make()[0].snapshot()
        self.assertIn("ROTATE_SECONDS", s.problem)

    def test_attention_hint_from_the_background_process(self):
        L, _ = self.make()
        self.assertIsNone(L.snapshot().attention)
        (self.d / bg.ATTN_NAME).write_text("Bitte neu anmelden.", encoding="utf-8")
        self.assertEqual(L.snapshot().attention, "Bitte neu anmelden.")

    def test_display_options_are_read_from_env(self):
        self.env("ON_IDLE=lines\nON_PAUSE=stats\nROTATE_SECONDS=45\nSTATUS_TTL=600\n")
        s = self.make()[0].snapshot()
        self.assertEqual((s.show_when_idle, s.show_on_pause, s.rotate, s.ttl_on), (True, True, 45, True))

    def test_exe_in_downloads_gets_a_hint_only_when_frozen(self):
        L, _ = self.make(exe=r"C:\Users\me\Downloads\Fluxer-Spotify.exe")
        with mock.patch("sys.frozen", True, create=True):
            self.assertIn("Downloads", L.exe_hint())
            self.assertEqual(self.make(exe=EXE)[0].exe_hint(), "")
        self.assertEqual(L.exe_hint(), "")  # a source run has no exe to lose

    def test_autostart_state_in_snapshot(self):
        L, _ = self.make()
        with mock.patch.object(autostart, "available", return_value=True), mock.patch.object(autostart, "installed", return_value=True), \
                mock.patch.object(autostart, "matches", return_value=False), mock.patch.object(autostart, "disabled_by_user", return_value=True):
            s = L.snapshot()
        self.assertEqual((s.autostart_supported, s.autostart_on, s.autostart_current, s.autostart_blocked), (True, True, False, True))


class StartStop(Base):
    def test_first_start_switches_on_show_everything_once_and_never_overwrites(self):
        self.env("# mein Kommentar\nON_PAUSE=clear\n")
        L, _ = self.make(client_id=CID, refresh="r")
        with mock.patch.object(bg, "spawn_background", return_value=777) as spawn:
            self.assertEqual(L.start(), 777)
        spawn.assert_called_once_with(self.d)
        env = settings.read_env(self.d)
        self.assertEqual((env["ON_IDLE"], env["STATUS_TTL"], env["ON_PAUSE"]), ("lines", "600", "clear"))  # the user's own value stays
        self.assertIn("# mein Kommentar", (self.d / ".env").read_text(encoding="utf-8"))
        self.assertTrue(self.state()["launcher_configured"])
        self.env("ON_IDLE=clear\n")  # user changes his mind later: not touched again
        with mock.patch.object(bg, "spawn_background", return_value=778):
            L.start()
        self.assertEqual(settings.read_env(self.d)["ON_IDLE"], "clear")

    def test_start_when_running_does_not_spawn_again(self):
        L, _ = self.make(launcher_configured=True)
        with mock.patch.object(bg, "running_pid", return_value=4242), mock.patch.object(bg, "spawn_background") as spawn:
            self.assertEqual(L.start(), 4242)
        spawn.assert_not_called()

    def test_start_clears_old_hint_and_stop_request(self):
        L, _ = self.make(launcher_configured=True)
        (self.d / bg.ATTN_NAME).write_text("alt")
        (self.d / bg.STOP_NAME).write_text("1")
        with mock.patch.object(bg, "spawn_background", return_value=1):
            L.start()
        self.assertFalse((self.d / bg.ATTN_NAME).exists() or (self.d / bg.STOP_NAME).exists())

    def test_stop_clean_does_not_touch_fluxer(self):
        L, t = self.make(client_id=CID, refresh="r", fluxer_token=FLX, fluxer_token_source="login")
        with mock.patch.object(bg, "stop_instance", return_value="clean"):
            self.assertEqual(L.stop(), "clean")
        self.assertEqual(t.calls, [])

    def test_stop_after_kill_clears_the_status_itself(self):
        L, t = self.make((200, {}), client_id=CID, refresh="r", fluxer_token=FLX, fluxer_token_source="login")
        with mock.patch.object(bg, "stop_instance", return_value="killed"):
            L.stop()
        self.assertEqual((t.calls[0][0], t.calls[0][3]), ("PATCH", {"custom_status": None}))

    def test_restart_stops_then_starts(self):
        L, _ = self.make(launcher_configured=True)
        order = []
        with mock.patch.object(bg, "stop_instance", side_effect=lambda d: order.append("stop") or "clean"), \
                mock.patch.object(bg, "spawn_background", side_effect=lambda d: order.append("start") or 5):
            self.assertEqual(L.restart(), 5)
        self.assertEqual(order, ["stop", "start"])


class Logins(Base):
    def test_spotify_rejects_a_malformed_client_id_without_touching_state(self):
        L, _ = self.make()
        with self.assertRaises(Fatal):
            L.spotify_login("nicht-32-zeichen")
        self.assertNotIn("client_id", self.state())

    def test_spotify_login_stores_the_id_and_forwards_cancel_and_browser(self):
        L, _ = self.make()
        opened, cancel = [], lambda: False
        with mock.patch.object(lm.SpotifyClient, "login") as login:
            L.spotify_login("  " + CID.upper() + " ", open_browser=opened.append, notify=print, cancel=cancel)
        self.assertEqual(self.state()["client_id"], CID)
        kw = login.call_args.kwargs
        self.assertIs(kw["cancel"], cancel)
        self.assertEqual(kw["open_browser"], opened.append)

    def test_failed_login_forgets_a_new_client_id_but_keeps_the_old_one(self):
        L, _ = self.make()
        with mock.patch.object(lm.SpotifyClient, "login", side_effect=Fatal("kein Code")):
            with self.assertRaises(Fatal):
                L.spotify_login(CID)
        self.assertNotIn("client_id", self.state())
        L.store().update(client_id=CID)
        with mock.patch.object(lm.SpotifyClient, "login", side_effect=Fatal("Abbruch")):
            with self.assertRaises(Fatal):
                L.spotify_login(CID)  # same id: not the culprit
        self.assertEqual(self.state()["client_id"], CID)

    def test_fluxer_login_stores_only_the_session_token(self):
        L, t = self.make((200, {"token": FLX, "user_id": "1", "user": {"username": "sophie", "global_name": "Sophie"}}))
        name = L.fluxer_login(" me@example.com ", "geheimes-passwort", lambda n: "")
        self.assertEqual(name, "Sophie")
        st = self.state()
        self.assertEqual((st["fluxer_token"], st["fluxer_token_source"], st["fluxer_user"]), (FLX, "login", "sophie"))
        self.assertEqual(t.calls[0][3], {"email": "me@example.com", "password": "geheimes-passwort"})
        self.assertNotIn("geheimes-passwort", (self.d / "state.json").read_text(encoding="utf-8"))

    def test_fluxer_login_with_second_factor(self):
        L, t = self.make((200, {"mfa": True, "ticket": "tk", "totp": True}), (200, {"token": FLX, "user": {"username": "sophie"}}))
        asked = []
        L.fluxer_login("me@example.com", "pw", lambda n: asked.append(n) or "123 456")
        self.assertEqual(asked, [0])
        self.assertEqual(t.calls[1][3], {"code": "123456", "ticket": "tk"})
        self.assertEqual(self.state()["fluxer_token"], FLX)

    def test_fluxer_login_errors_are_readable_and_store_nothing(self):
        L, _ = self.make((401, {"code": "INVALID_EMAIL_OR_PASSWORD"}))
        with self.assertRaises(LoginError) as cm:
            L.fluxer_login("me@example.com", "falsch", lambda n: "")
        self.assertIn("falsch", str(cm.exception))
        self.assertNotIn("fluxer_token", self.state())
        for email, pw in (("", "x"), ("a@b.c", "")):
            with self.assertRaises(Fatal):
                L.fluxer_login(email, pw, lambda n: "")

    def test_password_and_tokens_are_registered_for_log_redaction(self):
        from fluxer_spotify import log as logmod
        self.addCleanup(logmod._SECRETS.clear)
        L, _ = self.make((401, {"code": "INVALID_EMAIL_OR_PASSWORD"}), (200, {"login": "x"}))
        with self.assertRaises(LoginError):
            L.fluxer_login("me@example.com", "supergeheim123", lambda n: "")
        L.github_connect("github_pat_geheim_456")
        line = logmod.redact("Passwort supergeheim123 und Token github_pat_geheim_456")
        self.assertNotIn("supergeheim123", line)
        self.assertNotIn("github_pat_geheim_456", line)

    def test_fluxer_token_fallback(self):
        L, _ = self.make((200, {"username": "sophie"}))
        self.assertEqual(L.fluxer_token("  " + FLX + "  "), "sophie")
        self.assertEqual(self.state()["fluxer_token_source"], "manual")
        L2, _ = self.make((401, {"message": "no"}))
        with self.assertRaises(AuthError):
            L2.fluxer_token("flx_" + "x" * 36)
        with self.assertRaises(Fatal):
            L2.fluxer_token("  ")

    def test_github_connect_and_disconnect(self):
        L, t = self.make((200, {"login": "KetaLP-hub"}))
        self.assertEqual(L.github_connect(" github_pat_abc "), "KetaLP-hub")
        st = self.state()
        self.assertEqual((st["github_token"], st["github_user"], st["github_asked"]), ("github_pat_abc", "KetaLP-hub", True))
        self.assertEqual(t.calls[0][2]["Authorization"], "Bearer github_pat_abc")
        L.github_disconnect()
        st = self.state()
        self.assertNotIn("github_token", st)
        self.assertTrue(st["github_asked"])  # disconnecting is a decision: do not ask again

    def test_github_wrong_token_stores_nothing(self):
        L, _ = self.make((401, {"message": "Bad credentials"}))
        with self.assertRaises(AuthError):
            L.github_connect("falsch")
        self.assertNotIn("github_token", self.state())

    def test_fluxer_disconnect_ends_only_sessions_created_here(self):
        L, t = self.make((200, {}), (204, None), client_id=CID, refresh="r", fluxer_token=FLX, fluxer_token_source="login", fluxer_user="sophie")
        L.fluxer_disconnect()
        self.assertEqual([c[0] for c in t.calls], ["PATCH", "POST"])
        self.assertTrue(t.calls[1][1].endswith("/auth/logout"))
        self.assertNotIn("fluxer_token", self.state())
        L2, t2 = self.make((200, {}), fluxer_token="manuell" * 5, fluxer_token_source="manual")
        L2.fluxer_disconnect()
        self.assertEqual([c[0] for c in t2.calls], ["PATCH"])  # a pasted browser token is not ours to revoke

    def test_spotify_disconnect_keeps_other_logins(self):
        L, _ = self.make(client_id=CID, refresh="r", access="a", exp=1, fluxer_token=FLX)
        L.spotify_disconnect()
        st = self.state()
        self.assertEqual((st.get("refresh"), st.get("fluxer_token")), (None, FLX))


class SettingsAndChecks(Base):
    def test_default_selection_removes_status_lines(self):
        L, _ = self.make()
        self.env("# Kommentar bleibt\nSTATUS_LINES=now\nFLUXER_WEBHOOK=https://x\n")
        L.save_settings(["now", "playlist", "top_artist", "listening_today"], False, False, 30, False)
        text = (self.d / ".env").read_text(encoding="utf-8")
        self.assertNotIn("STATUS_LINES", text)
        self.assertIn("# Kommentar bleibt", text)
        self.assertIn("FLUXER_WEBHOOK=https://x", text)

    def test_choices_are_written_and_validated(self):
        L, _ = self.make(github_token="t")
        cfg = L.save_settings(["now", "gh_commits", "gh_stars"], True, True, 45, True)
        env = settings.read_env(self.d)
        self.assertEqual((env["STATUS_LINES"], env["ON_IDLE"], env["ON_PAUSE"], env["ROTATE_SECONDS"], env["STATUS_TTL"]),
                         ("now,gh_commits,gh_stars", "lines", "stats", "45", "600"))
        self.assertEqual((cfg.lines, cfg.on_idle, cfg.rotate, cfg.ttl), (("now", "gh_commits", "gh_stars"), "lines", 45.0, 600.0))

    def test_unusable_choices_are_refused_and_nothing_is_written(self):
        L, _ = self.make()
        for lines in ([], ["gh_commits"]):  # nothing selected / only GitHub lines although GitHub is not connected
            with self.assertRaises(Fatal):
                L.save_settings(lines, False, False, 30, False)
            self.assertFalse((self.d / ".env").exists())

    def test_rotation_below_the_minimum_is_raised_by_the_program_not_an_error(self):
        cfg = self.make()[0].save_settings(["now"], False, False, 5, False)
        self.assertEqual(cfg.rotate, 15.0)

    def test_check_reports_each_connection(self):
        L, _ = self.make((200, {"access_token": "a", "expires_in": 3600}), (200, {"username": "sophie"}), (200, {"login": "KetaLP-hub"}),
                         client_id=CID, refresh="r", fluxer_token=FLX, fluxer_token_source="login", github_token="g")
        res = {c.name: c for c in L.check()}
        self.assertTrue(res["Spotify"].ok and res["Fluxer"].ok and res["GitHub"].ok)
        self.assertIn("sophie", res["Fluxer"].text)

    def test_check_distinguishes_rejected_from_unreachable(self):
        from fluxer_spotify.http import NetworkError
        L, _ = self.make((400, {"error": "invalid_grant"}), *[NetworkError("offline")] * 4, client_id=CID, refresh="r", fluxer_token=FLX, fluxer_token_source="login")
        res = {c.name: c for c in L.check()}
        self.assertIs(res["Spotify"].ok, False)
        self.assertIsNone(res["Fluxer"].ok)  # offline is not a failed login
        self.assertIsNone(res["GitHub"].ok)  # optional

    def test_log_text(self):
        L, _ = self.make()
        self.assertIn("kein Log", L.log_text())
        (self.d / bg.LOG_NAME).write_text("\n".join(f"zeile{i}" for i in range(300)), encoding="utf-8")
        text = L.log_text(50)
        self.assertTrue(text.endswith("zeile299") and "zeile249" not in text)

    def test_set_autostart_delegates(self):
        L, _ = self.make()
        with mock.patch.object(autostart, "install", return_value="x") as inst, mock.patch.object(autostart, "uninstall", return_value="y") as un:
            self.assertEqual(L.set_autostart(True), "x")
            self.assertEqual(L.set_autostart(False), "y")
        inst.assert_called_once_with(self.d)
        un.assert_called_once_with()


class Uninstall(Base):
    def test_removes_everything_it_created_and_leaves_foreign_files(self):
        L, _ = self.make(client_id=CID, refresh="r")
        for n in (".env", bg.LOG_NAME, bg.PID_NAME, bg.ATTN_NAME):
            (self.d / n).write_text("x")
        (self.d / "meine-notizen.txt").write_text("bleibt")
        with mock.patch.object(bg, "stop_instance", return_value="none") as stop, mock.patch.object(autostart, "available", return_value=True), \
                mock.patch.object(autostart, "uninstall") as un:
            L.uninstall()
        stop.assert_called_once()
        un.assert_called_once()
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), ["meine-notizen.txt"])


if __name__ == "__main__":
    unittest.main()

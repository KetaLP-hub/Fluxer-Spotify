import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fluxer_spotify import autostart, background, cli, config, wizard
from fluxer_spotify.config import Config, load_config
from fluxer_spotify.errors import AuthError, Fatal, set_lang
from fluxer_spotify.store import Store
from tests.helpers import make_http

CID = "0123456789abcdef0123456789ABCDEF"
TOKEN = "flx_" + "T" * 36
LOGIN_OK = (200, {"token": TOKEN, "user_id": "1", "user": {"username": "sophie"}})


class FakeSpotify:
    def __init__(self, refresh_error=None, login_error=None):
        self.refresh_error, self.login_error, self.refreshed, self.logins = refresh_error, login_error, 0, 0

    def refresh(self):
        self.refreshed += 1
        if self.refresh_error:
            raise self.refresh_error

    def login(self, open_browser=None, **_):
        self.logins += 1
        if self.login_error:
            raise self.login_error
        self.ctx.store.update(refresh="r" * 8, access="a", exp=1)


class WizardCase(unittest.TestCase):
    skip_github_step = True  # the optional GitHub question is tested on its own (GitHubStep)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(set_lang, None)  # the language step sets the process-wide language
        self.d = Path(self.tmp.name)
        for mod in (autostart, background):
            p = mock.patch.object(mod, "available", return_value=False)
            p.start()
            self.addCleanup(p.stop)
        if self.skip_github_step:
            p = mock.patch.object(wizard, "_github")
            p.start()
            self.addCleanup(p.stop)

    def ctx(self, inputs=(), secrets=(), http=None, sp=None, **cfg):
        """Scripted input()/getpass(): running out of answers raises StopIteration = an unexpected prompt."""
        self.opened = []
        cfg.setdefault("language", "auto")  # configured: the language step is tested separately (test_language.py)
        inputs, secrets = iter(inputs), iter(secrets)
        http = http or make_http()[0]
        c = cli.Ctx(Config(data_dir=self.d, **cfg), http, lambda p="": next(secrets), lambda p="": next(inputs),
                    open_browser=self.opened.append)
        self.sp = sp or FakeSpotify()
        self.sp.ctx = c
        c.spotify = lambda: self.sp
        return c

    def run_wizard(self, c):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            wizard.setup(c)
        return out.getvalue()

    def state(self):
        return Store(self.d / "state.json").data  # decrypted view: tokens may be sealed on disk (Windows DPAPI)

    def done_state(self, **extra):
        (self.d / "state.json").write_text(json.dumps({"client_id": CID, "refresh": "rr", "fluxer_token": TOKEN,
                                                      "fluxer_token_source": "login", **extra}))


class GitHubStep(WizardCase):
    skip_github_step = False

    ME = (200, {"username": "sophie"})  # the Fluxer step re-checks the stored token on every start

    def test_asked_once_and_declining_is_remembered(self):
        self.done_state()
        c = self.ctx(inputs=["n"], http=make_http(self.ME)[0])
        out = self.run_wizard(c)
        self.assertIn("GitHub", out)
        self.assertTrue(self.state()["github_asked"])
        self.assertNotIn("github_token", self.state())
        self.run_wizard(self.ctx(inputs=[], http=make_http(self.ME)[0]))  # second start: no prompt at all (StopIteration would fail the test)

    def test_yes_opens_the_prefilled_token_page_and_stores_the_token(self):
        self.done_state()
        http, t, _ = make_http(self.ME, (200, {"login": "sophie"}))
        c = self.ctx(inputs=["j"], secrets=["github_pat_" + "x" * 30], http=http)
        out = self.run_wizard(c)
        url = self.opened[0]
        self.assertTrue(url.startswith("https://github.com/settings/personal-access-tokens/new?"))
        for part in ("pull_requests=read", "issues=read", "expires_in=365"):
            self.assertIn(part, url)
        self.assertNotIn("=write", url)  # read-only: never ask for write permissions
        self.assertIn("sophie", out)
        self.assertEqual(self.state()["github_user"], "sophie")
        self.assertEqual(t.calls[1][2]["Authorization"], "Bearer github_pat_" + "x" * 30)

    def test_wrong_token_does_not_block_the_program(self):
        self.done_state()
        http, _, _ = make_http(self.ME, (401, {"message": "Bad credentials"}))
        c = self.ctx(inputs=["y"], secrets=["nope"], http=http)
        out = self.run_wizard(c)  # must not raise
        self.assertIn("github-login", out)
        self.assertNotIn("github_token", self.state())
        self.assertTrue(self.state()["github_asked"])

    def test_already_connected_is_not_asked(self):
        self.done_state(github_token="t", github_user="x")
        self.run_wizard(self.ctx(inputs=[], http=make_http(self.ME)[0]))

    def test_background_never_asks(self):
        self.done_state()
        c = self.ctx(inputs=[], http=make_http(self.ME)[0])
        with contextlib.redirect_stdout(io.StringIO()):
            wizard.setup(c, interactive=False)
        self.assertNotIn("github_asked", self.state())


class ClientId(WizardCase):
    def test_format(self):
        self.assertTrue(wizard.valid_client_id(CID))
        for bad in ("", "xyz", CID[:-1], CID + "0", "g" * 32, "deine_spotify_client_id"):
            self.assertFalse(wizard.valid_client_id(bad))

    def test_reprompts_on_invalid_then_persists_and_opens_dashboard(self):
        (self.d / "state.json").write_text(json.dumps({"refresh": "rr", "fluxer_token": TOKEN, "autostart_asked": True}))
        http, t, _ = make_http((200, {"username": "sophie"}))
        c = self.ctx(inputs=["nope", "  " + CID + " "], http=http)
        out = self.run_wizard(c)
        self.assertEqual(self.opened, [wizard.DASHBOARD])
        self.assertIn("http://127.0.0.1:8888/callback", out)
        self.assertEqual(c.cfg.client_id, CID.lower())
        self.assertEqual(self.state()["client_id"], CID.lower())
        c2 = cli.Ctx(Config(data_dir=self.d), None, None, None)  # next start: loaded without any prompt
        self.assertEqual(c2.cfg.client_id, CID.lower())

    def test_empty_input_cancels_and_too_many_failures(self):
        with self.assertRaises(Fatal):
            self.run_wizard(self.ctx(inputs=[""]))
        with self.assertRaises(Fatal):
            self.run_wizard(self.ctx(inputs=["bad"] * 5))
        self.assertFalse((self.d / "state.json").exists())

    def test_precedence_env_dotenv_over_stored(self):
        (self.d / "state.json").write_text(json.dumps({"client_id": "stored"}))
        (self.d / ".env").write_text("SPOTIFY_CLIENT_ID=fromdotenv\n")
        home = {"FLUXER_SPOTIFY_HOME": str(self.d)}
        self.assertEqual(cli.Ctx(load_config(None, environ=home), None, None, None).cfg.client_id, "fromdotenv")
        cfg = load_config(None, environ={**home, "SPOTIFY_CLIENT_ID": "fromenv"})
        self.assertEqual(cli.Ctx(cfg, None, None, None).cfg.client_id, "fromenv")
        (self.d / ".env").unlink()
        self.assertEqual(cli.Ctx(load_config(None, environ=home), None, None, None).cfg.client_id, "stored")

    def test_rejected_new_client_id_is_forgotten(self):
        c = self.ctx(inputs=[CID], sp=FakeSpotify(login_error=Fatal("no code")))
        with self.assertRaises(Fatal):
            self.run_wizard(c)
        self.assertNotIn("client_id", self.state())


class Steps(WizardCase):
    def test_everything_done_skips_all_prompts(self):
        self.done_state(autostart_asked=True)
        http, t, _ = make_http((200, {"username": "sophie"}))
        self.run_wizard(self.ctx(http=http))
        self.assertEqual((self.sp.refreshed, self.sp.logins, len(t.calls)), (1, 0, 1))
        self.assertEqual(self.opened, [])

    def test_rotation_tip_is_printed_once_and_asks_nothing(self):
        self.done_state(autostart_asked=True)
        out = self.run_wizard(self.ctx(http=make_http((200, {"username": "s"}), (200, {"username": "s"}))[0]))
        self.assertIn("--no-rotate", out)
        out = self.run_wizard(self.ctx(http=make_http((200, {"username": "s"}))[0]))
        self.assertNotIn("--no-rotate", out)

    def test_expired_spotify_relogs_in_only_spotify(self):
        self.done_state(autostart_asked=True)
        http, _, _ = make_http((200, {"username": "sophie"}))
        self.run_wizard(self.ctx(http=http, sp=FakeSpotify(refresh_error=AuthError("expired"))))
        self.assertEqual(self.sp.logins, 1)
        self.assertEqual(self.state()["fluxer_token"], TOKEN)  # Fluxer step untouched

    def test_expired_fluxer_token_relogs_in_only_fluxer(self):
        self.done_state(autostart_asked=True)
        http, t, _ = make_http((401, {}), LOGIN_OK)
        self.run_wizard(self.ctx(inputs=["a@b.c"], secrets=["pw"], http=http))
        self.assertEqual(self.sp.logins, 0)
        self.assertEqual(self.state()["fluxer_user"], "sophie")
        self.assertEqual(t.calls[1][3], {"email": "a@b.c", "password": "pw"})

    def test_fresh_start_runs_all_steps_in_order(self):
        http, _, _ = make_http(LOGIN_OK)
        c = self.ctx(inputs=[CID, "a@b.c", "n"], secrets=["pw"], http=http)
        with mock.patch.object(autostart, "available", return_value=True), \
                mock.patch.object(autostart, "installed", return_value=False):
            self.run_wizard(c)
        st = self.state()
        self.assertEqual((st["client_id"], st["fluxer_token"], st["autostart_asked"]), (CID.lower(), TOKEN, True))
        self.assertEqual(self.sp.logins, 1)

    def test_login_failure_offers_token_paste_fallback(self):
        http, _, _ = make_http((400, {"code": "INVALID_EMAIL_OR_PASSWORD"}), (200, {"username": "sophie"}))
        (self.d / "state.json").write_text(json.dumps({"client_id": CID, "refresh": "rr", "autostart_asked": True}))
        out = self.run_wizard(self.ctx(inputs=["a@b.c", "t"], secrets=["bad", " " + TOKEN], http=http))
        self.assertEqual(self.state()["fluxer_token_source"], "manual")
        self.assertNotIn(TOKEN, out)

    def test_login_failure_quit(self):
        http, _, _ = make_http((400, {"code": "INVALID_EMAIL_OR_PASSWORD"}))
        (self.d / "state.json").write_text(json.dumps({"client_id": CID, "refresh": "rr"}))
        with self.assertRaises(Fatal):
            self.run_wizard(self.ctx(inputs=["a@b.c", "q"], secrets=["bad"], http=http))

    def test_webhook_only_needs_no_fluxer_login(self):
        (self.d / "state.json").write_text(json.dumps({"client_id": CID, "refresh": "rr", "autostart_asked": True}))
        self.run_wizard(self.ctx(webhook="https://hook"))  # no prompts

    def test_autostart_offer_yes_asked_once(self):
        self.done_state()
        c = self.ctx(inputs=["j"], http=make_http((200, {}))[0])
        calls = []
        c.autostart = calls.append
        with mock.patch.object(autostart, "available", return_value=True), \
                mock.patch.object(autostart, "installed", return_value=False):
            self.run_wizard(c)
            self.assertEqual(calls, [True])
            self.run_wizard(self.ctx(http=make_http((200, {}))[0]))  # flag stored: no second question

    def test_no_terminal_input_is_a_clean_error(self):
        class Eof:
            def __call__(self, p=""):
                raise EOFError
        c = self.ctx()
        c.input = Eof()
        with self.assertRaises(Fatal):
            self.run_wizard(c)


class Frozen(unittest.TestCase):
    def test_data_dir_is_per_user_when_frozen(self):
        with tempfile.TemporaryDirectory() as appdata, mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.dict(os.environ, {"APPDATA": appdata}):
            os.environ.pop("FLUXER_SPOTIFY_HOME", None)
            self.assertEqual(config.default_data_dir(), Path(appdata) / "spotify-fluxer")
            cfg = load_config(None)
            self.assertTrue(cfg.data_dir.is_dir())
            self.assertEqual(cfg.state_file.parent, Path(appdata) / "spotify-fluxer")

    def test_source_run_keeps_project_folder(self):
        self.assertFalse(getattr(sys, "frozen", False))
        self.assertTrue((config.default_data_dir() / "fluxer_spotify").is_dir())

    def test_autostart_and_spawn_start_the_exe_hidden(self):
        line = autostart.command_line(r"C:\My Data", frozen=True, executable=r"C:\Apps\Fluxer-Spotify.exe")
        self.assertEqual(line, r'C:\Apps\Fluxer-Spotify.exe run --background --data-dir "C:\My Data"')
        cmd, _ = background.background_command(r"C:\d", frozen=True, executable=r"C:\Apps\Fluxer-Spotify.exe")
        self.assertEqual(cmd[:3], [r"C:\Apps\Fluxer-Spotify.exe", "run", "--background"])

    def test_errors_never_wait_for_enter(self):
        # The exe is a windowed program: there is no console window that could vanish, and a terminal must get its prompt back.
        for frozen in (True, False):
            with mock.patch.object(sys, "frozen", frozen, create=True), mock.patch.object(cli, "main", return_value=1), \
                    mock.patch.object(sys, "argv", ["x", "status"]), mock.patch("builtins.input", side_effect=AssertionError("must not wait")):
                self.assertEqual(cli.entry(), 1)


if __name__ == "__main__":
    unittest.main()

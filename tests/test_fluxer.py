import base64
import hashlib
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

from fluxer_spotify import cli, log as logmod
from fluxer_spotify.errors import AuthError, LoginError
from fluxer_spotify.fluxer import FluxerClient, login, solve_altcha
from tests.helpers import CAPTCHA_ERR, altcha_challenge, make_http

API = "https://api.example/v1"
OK = (200, {"token": "flx_" + "a" * 36, "user_id": "1", "user": {"username": "sophie"}})
no_prompt = lambda attempt: (_ for _ in ()).throw(AssertionError("MFA prompt not expected"))


class Captcha(unittest.TestCase):
    def test_solution_is_valid_and_echoes_challenge(self):
        ch = altcha_challenge(cost=10, counter=300, prefix_bytes=2)
        payload = json.loads(base64.b64decode(solve_altcha(ch)))
        self.assertEqual(payload["challenge"], ch)
        sol, p = payload["solution"], ch["parameters"]
        key = hashlib.pbkdf2_hmac("sha256", bytes.fromhex(p["nonce"]) + sol["counter"].to_bytes(4, "big"),
                                  bytes.fromhex(p["salt"]), p["cost"], p["keyLength"]).hex()
        self.assertEqual(key, sol["derivedKey"])
        self.assertTrue(key.startswith(p["keyPrefix"]))
        self.assertLessEqual(sol["counter"], 300)

    def test_unsupported_algorithm(self):
        ch = altcha_challenge()
        ch["parameters"]["algorithm"] = "ARGON2"
        with self.assertRaises(LoginError):
            solve_altcha(ch)

    def test_timeout(self):
        ch = altcha_challenge()
        ch["parameters"]["keyPrefix"] = "ffffffffffffffff"  # practically unsolvable
        ticks = iter(range(0, 10_000, 50))
        with self.assertRaises(LoginError):
            solve_altcha(ch, timeout=90, clock=lambda: next(ticks))


class LoginFlow(unittest.TestCase):
    def test_plain_login(self):
        http, t, _ = make_http(OK)
        r = login(http, API, "a@b.c", "pw", no_prompt)
        self.assertEqual((r["token"][:4], r["user"]["username"]), ("flx_", "sophie"))
        m, url, headers, body = t.calls[0]
        self.assertEqual((m, url, body), ("POST", API + "/auth/login", {"email": "a@b.c", "password": "pw"}))
        self.assertNotIn("Authorization", headers)

    def test_captcha_solved_then_retried(self):
        http, t, _ = make_http(CAPTCHA_ERR(), OK)
        login(http, API, "a@b.c", "pw", no_prompt, notify=lambda *_: None)
        self.assertEqual(len(t.calls), 2)
        h = t.calls[1][2]
        self.assertEqual(h["X-Captcha-Type"], "altcha")
        self.assertIn("solution", json.loads(base64.b64decode(h["X-Captcha-Token"])))

    def test_non_altcha_captcha_points_to_fallback(self):
        http, _, _ = make_http((400, {"code": "CAPTCHA_REQUIRED", "captcha_provider": "hcaptcha"}))
        with self.assertRaises(LoginError) as cm:
            login(http, API, "a@b.c", "pw", no_prompt)
        self.assertIn("fluxer-token", str(cm.exception))

    def test_wrong_password(self):
        http, _, sleeps = make_http((400, {"code": "INVALID_EMAIL_OR_PASSWORD"}))
        with self.assertRaises(LoginError) as cm:
            login(http, API, "a@b.c", "bad", no_prompt)
        self.assertIn("falsch", str(cm.exception))
        self.assertEqual(sleeps, [])  # login is never auto-retried

    def test_mfa_totp_with_one_wrong_code(self):
        mfa = (200, {"mfa": True, "ticket": "T1", "allowed_methods": ["totp", "webauthn"], "totp": True, "webauthn": True})
        http, t, _ = make_http(mfa, (400, {"code": "INVALID_CODE"}), OK)
        codes = iter(["111 111", "222222"])
        msgs = []
        r = login(http, API, "a@b.c", "pw", lambda a: next(codes), notify=msgs.append)
        self.assertEqual(r["user_id"], "1")
        self.assertEqual(t.calls[1][1], API + "/auth/login/mfa/totp")
        self.assertEqual(t.calls[1][3], {"code": "111111", "ticket": "T1"})
        self.assertEqual(t.calls[2][3], {"code": "222222", "ticket": "T1"})
        self.assertEqual(len(msgs), 1)

    def test_mfa_gives_up_after_three_wrong_codes(self):
        mfa = (200, {"mfa": True, "ticket": "T1", "totp": True})
        bad = (400, {"code": "INVALID_CODE"})
        http, t, _ = make_http(mfa, bad, bad, bad)
        with self.assertRaises(LoginError):
            login(http, API, "a@b.c", "pw", lambda a: "000000", notify=lambda *_: None)
        self.assertEqual(len(t.calls), 4)

    def test_mfa_cancel_and_webauthn_only(self):
        http, _, _ = make_http((200, {"mfa": True, "ticket": "T", "totp": True}))
        with self.assertRaises(LoginError):
            login(http, API, "a@b.c", "pw", lambda a: "")
        http, _, _ = make_http((200, {"mfa": True, "ticket": "T", "allowed_methods": ["webauthn"], "webauthn": True}))
        with self.assertRaises(LoginError) as cm:
            login(http, API, "a@b.c", "pw", no_prompt)
        self.assertIn("WebAuthn", str(cm.exception))

    def test_mfa_session_timeout(self):
        http, _, _ = make_http((200, {"mfa": True, "ticket": "T", "totp": True}), (400, {"code": "SESSION_TIMEOUT"}))
        with self.assertRaises(LoginError) as cm:
            login(http, API, "a@b.c", "pw", lambda a: "123456")
        self.assertIn("neu anmelden", str(cm.exception))

    def test_new_ip_requires_email_approval(self):
        ip = (403, {"code": "IP_AUTHORIZATION_REQUIRED", "ticket": "TK", "email": "a@b.c", "resend_available_in": 30})
        http, t, _ = make_http(ip, (200, {"completed": False}), (200, {"completed": True, "token": "flx_" + "b" * 36}))
        clock = iter(range(0, 1000, 3))
        r = login(http, API, "a@b.c", "pw", no_prompt, notify=lambda *_: None, sleep=lambda s: None, clock=lambda: next(clock))
        self.assertEqual(r["token"], "flx_" + "b" * 36)
        self.assertEqual(t.calls[1][1:4:2], (API + "/auth/ip-authorization/poll", {"ticket": "TK"}))

    def test_ip_authorization_timeout(self):
        ip = (403, {"code": "IP_AUTHORIZATION_REQUIRED", "ticket": "TK", "email": "a@b.c"})
        http, _, _ = make_http(ip, *[(200, {"completed": False})] * 5)
        clock = iter(range(0, 10_000, 200))
        with self.assertRaises(LoginError):
            login(http, API, "a@b.c", "pw", no_prompt, notify=lambda *_: None, sleep=lambda s: None,
                  clock=lambda: next(clock), ip_timeout=600)


class TokenFormatFallback(unittest.TestCase):
    def test_session_token_sent_without_prefix_and_not_probed(self):
        http, t, _ = make_http((401, {"code": "UNAUTHORIZED"}))
        with self.assertRaises(AuthError):
            FluxerClient(http, API, "flx_" + "a" * 36).me()
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(t.calls[0][2]["Authorization"], "flx_" + "a" * 36)

    def test_unknown_format_falls_back_to_bearer_and_remembers(self):
        http, t, _ = make_http((401, {}), (200, {}), (200, {}))
        c = FluxerClient(http, API, "oddtoken", "manual")
        c.set_status("hi")
        c.set_status(None)
        auth = [call[2]["Authorization"] for call in t.calls]
        self.assertEqual(auth, ["oddtoken", "Bearer oddtoken", "Bearer oddtoken"])
        self.assertEqual(t.calls[2][3], {"custom_status": None})
        self.assertEqual(t.calls[1][3], {"custom_status": {"text": "hi"}})

    def test_401_message_depends_on_source(self):
        for src, word in (("manual", "fluxer-token"), ("login", "fluxer-login")):
            http, _, _ = make_http((401, {}), (401, {}))
            with self.assertRaises(AuthError) as cm:
                FluxerClient(http, API, "x", src).me()
            self.assertIn(word, str(cm.exception))


class CliLogin(unittest.TestCase):
    """End to end through cli.main: token stored, password and token never in logs/state/stdout."""

    def test_fluxer_login_stores_only_token_and_leaks_nothing(self):
        pw, token = "CorrectHorse!Battery9", "flx_" + "Z" * 36
        mfa = (200, {"mfa": True, "ticket": "T", "totp": True})
        http, t, _ = make_http(CAPTCHA_ERR(), mfa, (200, {"token": token, "user_id": "1", "user": {"username": "sophie"}}))
        buf = io.StringIO()
        out = io.StringIO()
        lg = logging.getLogger("fluxer_spotify")
        with tempfile.TemporaryDirectory() as d:
            answers = iter([pw, "123456"])
            real_setup = logmod.setup
            logmod.setup = lambda *a, **k: (lg.handlers.__setitem__(slice(None), [logmod.make_handler(buf, True)]),
                                           lg.setLevel(logging.DEBUG), setattr(lg, "propagate", False))
            try:
                import contextlib
                with contextlib.redirect_stdout(out):
                    rc = cli.main(["fluxer-login", "--email", "a@b.c", "--data-dir", d, "-v"], http=http,
                                  getpass_fn=lambda prompt="": next(answers), input_fn=lambda p="": "")
            finally:
                logmod.setup = real_setup
            self.assertEqual(rc, 0)
            state = (Path(d) / "state.json").read_text()
            self.assertEqual(json.loads(state)["fluxer_token"], token)
            self.assertEqual(json.loads(state)["fluxer_token_source"], "login")
            for blob in (state, buf.getvalue(), out.getvalue()):
                self.assertNotIn(pw, blob)
            self.assertNotIn(token, buf.getvalue() + out.getvalue())
            self.assertTrue(buf.getvalue())  # something was logged, and it was clean

    def test_logout_revokes_own_session_only(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "state.json").write_text(json.dumps(
                {"fluxer_token": "flx_" + "q" * 36, "fluxer_token_source": "login", "refresh": "rr" * 4}))
            http, t, _ = make_http((200, {}), (204, None))
            self.assertEqual(cli.main(["logout", "--data-dir", d], http=http), 0)
            self.assertEqual([(c[0], c[1].split("/v1")[1]) for c in t.calls],
                             [("PATCH", "/users/@me/settings"), ("POST", "/auth/logout")])
            self.assertEqual(json.loads((Path(d) / "state.json").read_text()), {})
            # a manually pasted token is the user's browser session: status cleared, but NOT revoked
            (Path(d) / "state.json").write_text(json.dumps({"fluxer_token": "tok", "fluxer_token_source": "manual"}))
            http, t, _ = make_http((200, {}))
            cli.main(["logout", "--data-dir", d], http=http)
            self.assertEqual(len(t.calls), 1)


if __name__ == "__main__":
    unittest.main()

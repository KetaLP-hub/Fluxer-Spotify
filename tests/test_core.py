import json
import logging
import io
import os
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from fluxer_spotify import log as logmod
from fluxer_spotify.config import DEFAULT_TEMPLATE, Config, load_config, parse_dotenv
from fluxer_spotify.errors import Fatal
from fluxer_spotify.http import HttpError, NetworkError
from fluxer_spotify.runner import KEEP, Runner
from fluxer_spotify.spotify import Snapshot, bar, lines, mmss, status_text, who
from fluxer_spotify.store import Store
from tests.helpers import make_http

TRACK = {"id": "t1", "name": "Song", "artists": [{"name": "A"}, {"name": "B"}], "album": {"name": "Alb"}}


class Formatting(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(mmss(65000), "1:05")
        self.assertEqual(bar(0, 0), "▱" * 14)
        self.assertEqual(bar(5, 10, 4), "▰▰▱▱")
        self.assertEqual(who(TRACK), "A, B")
        self.assertEqual(who({"show": {"name": "Pod"}}), "Pod")
        self.assertEqual(lines([]), "-")
        self.assertEqual(len(lines(["x" * 2000])), 1000)

    def test_template(self):
        self.assertEqual(status_text(TRACK, DEFAULT_TEMPLATE), "🎵 Song – A, B")
        self.assertEqual(status_text(TRACK, "{album}: {title}"), "Alb: Song")

    def test_template_truncated_and_safe(self):
        self.assertEqual(len(status_text({"name": "x" * 500}, "{title}")), 128)
        self.assertEqual(status_text(TRACK, "{nope}"), "🎵 Song – A, B")  # bad template -> default
        self.assertIsNone(status_text({"name": ""}, "{title}"))


class HttpRetry(unittest.TestCase):
    def test_retry_after_header_then_success(self):
        http, t, sleeps = make_http((429, {"code": "RATE_LIMITED"}, {"Retry-After": "7"}), (200, {"ok": 1}))
        self.assertEqual(http.request("GET", "https://x/y"), {"ok": 1})
        self.assertEqual(sleeps, [7.0])

    def test_retry_after_in_body(self):
        http, _, sleeps = make_http((429, {"retry_after": 1.5}), (200, {}))
        http.request("GET", "https://x/y")
        self.assertEqual(sleeps, [1.5])

    def test_exponential_backoff_on_5xx_and_network(self):
        http, _, sleeps = make_http((503, b"down"), NetworkError("boom"), (502, b""), (200, {"ok": 1}))
        self.assertEqual(http.request("GET", "https://x/y"), {"ok": 1})
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])

    def test_gives_up_and_raises(self):
        http, t, _ = make_http((500, b"a"), (500, b"b"))
        with self.assertRaises(HttpError) as cm:
            http.request("GET", "https://x/y", retries=1)
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual(len(t.calls), 2)

    def test_4xx_not_retried(self):
        http, t, sleeps = make_http((404, {"code": "NOPE"}))
        with self.assertRaises(HttpError) as cm:
            http.request("GET", "https://x/y")
        self.assertEqual((cm.exception.code, len(t.calls), sleeps), ("NOPE", 1, []))

    def test_backoff_capped(self):
        http, _, sleeps = make_http((429, {}, {"Retry-After": "9999"}), (200, {}))
        http.request("GET", "https://x/y")
        self.assertEqual(sleeps, [120.0])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.path = Path(self.d.name) / "state.json"

    def tearDown(self):
        self.d.cleanup()

    def test_roundtrip_atomic_no_temp_left(self):
        s = Store(self.path)
        s.update(access="a" * 8, refresh="r" * 8, msg="1")
        self.assertEqual(Store(self.path).get("refresh"), "r" * 8)
        self.assertEqual([p.name for p in Path(self.d.name).iterdir()], ["state.json"])
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_corrupt_file_is_set_aside(self):
        self.path.write_text("{not json")
        s = Store(self.path)
        self.assertEqual(s.data, {})
        self.assertTrue(self.path.with_name("state.json.corrupt").exists())

    def test_legacy_v1_state_loads(self):
        self.path.write_text(json.dumps({"access": "x" * 8, "exp": 1, "refresh": "r" * 8, "msg": "9", "auth": ["tok"]}))
        s = Store(self.path)
        self.assertEqual(s.get("refresh"), "r" * 8)
        self.assertNotIn("auth", s.data)

    def test_token_provenance(self):
        s = Store(self.path)
        cfg = Namespace(fluxer_token="")
        self.assertEqual(s.fluxer_token(cfg), (None, None))
        s.update(fluxer_token="flx_abc", fluxer_token_source="manual")
        self.assertEqual(s.fluxer_token(cfg), ("flx_abc", "manual"))
        self.assertEqual(s.fluxer_token(Namespace(fluxer_token="envtok")), ("envtok", "manual"))  # env wins

    def test_password_never_in_state_keys(self):
        s = Store(self.path)
        s.update(fluxer_token="flx_abc")
        self.assertNotIn("password", self.path.read_text().lower())


class ConfigTests(unittest.TestCase):
    def test_precedence_flags_env_dotenv(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".env").write_text("SPOTIFY_CLIENT_ID=fromfile\nON_PAUSE=keep\nFLUXER_WEBHOOK=\n# c\n", encoding="utf-8")
            c = load_config(Namespace(data_dir=d), environ={})
            self.assertEqual((c.client_id, c.on_pause), ("fromfile", "keep"))
            c = load_config(Namespace(data_dir=d), environ={"SPOTIFY_CLIENT_ID": "fromenv"})
            self.assertEqual(c.client_id, "fromenv")
            c = load_config(Namespace(data_dir=d, client_id="fromflag"), environ={"SPOTIFY_CLIENT_ID": "fromenv"})
            self.assertEqual(c.client_id, "fromflag")

    def test_validation(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Fatal):
                load_config(Namespace(data_dir=d), environ={"FLUXER_API": "http://evil.example/v1"})
            with self.assertRaises(Fatal):
                load_config(Namespace(data_dir=d), environ={"ON_PAUSE": "maybe"})
            c = load_config(Namespace(data_dir=d), environ={"FLUXER_API": "http://localhost:8080/v1/", "POLL_INTERVAL": "0.1"})
            self.assertEqual((c.api, c.interval), ("http://localhost:8080/v1", 2.0))

    def test_parse_dotenv(self):
        self.assertEqual(parse_dotenv('A="x y"\n#B=1\nC = z\nbad'), {"A": "x y", "C": "z"})


class FakeSpotify:
    def __init__(self, *snaps):
        self.snaps = list(snaps)

    def snapshot(self, full=False):
        return self.snaps.pop(0)


class FakeFluxer:
    def __init__(self):
        self.sent = []

    def set_status(self, text):
        self.sent.append(text)


def snap(playing=True, item=TRACK, key=None):
    return Snapshot(key or (item and item["id"], playing), playing, item, {})


class RunnerTests(unittest.TestCase):
    def make(self, on_pause, *snaps):
        cfg = Config(data_dir=Path("."), on_pause=on_pause, interval=2, lines=("now",))
        fx = FakeFluxer()
        return Runner(cfg, FakeSpotify(*snaps), fx), fx

    def test_play_pause_clear(self):
        r, fx = self.make("clear", snap(True), snap(True), snap(False, key=("t1", False)), snap(False, None, "idle"))
        for _ in range(4):
            r.tick()
        self.assertEqual(fx.sent, ["🎵 Song – A, B", None])  # unchanged text => no re-send (pause and idle both clear)

    def test_pause_keep(self):
        r, fx = self.make("keep", snap(True), snap(False, key=("t1", False)), snap(False, None, "idle"))
        for _ in range(3):
            r.tick()
        self.assertEqual(fx.sent, ["🎵 Song – A, B", None])  # keep on pause, still clear on idle

    def test_shutdown_clears_and_never_raises(self):
        r, fx = self.make("clear")
        r.shutdown()
        self.assertEqual(fx.sent, [None])
        fx.set_status = lambda t: (_ for _ in ()).throw(RuntimeError("x"))
        r.shutdown()


class SecretsNotLogged(unittest.TestCase):
    def test_redaction_formatter(self):
        logmod.add_secret("SuperSecretValue123")
        buf = io.StringIO()
        lg = logging.getLogger("fluxer_spotify.test_redact")
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        lg.handlers[:] = [logmod.make_handler(buf, verbose=True)]
        lg.info("token SuperSecretValue123 and flx_AbCd1234xyz and Bearer abc.def and %s",
                "https://api.fluxer.app/webhooks/123/WEBHOOKTOKEN_x")
        lg.info('Authorization: flx_zzzz X-Captcha-Token: aGVsbG8=')
        try:
            raise ValueError("oops SuperSecretValue123")
        except ValueError:
            lg.exception("failed")
        out = buf.getvalue()
        for leak in ("SuperSecretValue123", "flx_AbCd1234xyz", "abc.def", "WEBHOOKTOKEN_x", "flx_zzzz", "aGVsbG8"):
            self.assertNotIn(leak, out)


if __name__ == "__main__":
    unittest.main()

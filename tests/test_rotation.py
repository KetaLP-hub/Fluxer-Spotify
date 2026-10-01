"""Rotating status lines: fake clock, fake Spotify routes, fake Fluxer. Nothing touches the network."""
import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fluxer_spotify import background, cli, lines
from fluxer_spotify.config import Config, load_config
from fluxer_spotify.errors import Fatal
from fluxer_spotify.http import HttpError, NetworkError
from fluxer_spotify.runner import Runner
from fluxer_spotify.spotify import Snapshot, truncate

T0 = datetime(2026, 10, 2, 15, 0, 0).timestamp()  # local time on purpose: "today" is the local day
NOW, PL, TOP, TODAY = "🎵 Song – A", '💿 aus "Mix"', "🏆 Top-Artist diese Woche: Muse", "🎧 heute 1 h 30 min gehört"
TRACK = {"id": "t1", "name": "Song", "artists": [{"name": "A"}], "album": {"name": "Alb"}}
TRACK2 = {"id": "t2", "name": "Other", "artists": [{"name": "A"}], "album": {"name": "Alb"}}
PODCAST = {"id": "e1", "name": "Folge 1", "show": {"name": "Pod"}, "duration_ms": 1000}
PLAYLIST = {"type": "playlist", "uri": "spotify:playlist:PL1"}


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def recent(*plays):
    """plays: (end_ts, minutes), newest first like the API -> a recently-played response."""
    return {"items": [{"played_at": iso(e), "track": {"duration_ms": m * 60000}} for e, m in plays]}


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


class FakeSpotify:
    """`routes` maps a path prefix to a dict or an exception; `calls` records every API path."""

    def __init__(self):
        self.snap, self.calls = None, []
        self.routes = {"/playlists/PL1": {"name": "Mix"}, "/me/top/artists": {"items": [{"name": "Muse"}]},
                       "/me/player/recently-played": recent((T0 - 600, 90))}

    def snapshot(self, full=False):
        return self.snap

    def get(self, path, retries=None):
        self.calls.append(path)
        for prefix, val in self.routes.items():
            if path.startswith(prefix):
                if isinstance(val, Exception):
                    raise val
                return val
        raise AssertionError("unexpected " + path)

    def n(self, prefix):
        return sum(c.startswith(prefix) for c in self.calls)


class FakeFluxer:
    def __init__(self):
        self.sent, self.error = [], None

    def set_status(self, text):
        if self.error:
            raise self.error
        self.sent.append(text)


def snap(item=TRACK, playing=True, context=PLAYLIST):
    return Snapshot((item["id"], playing), playing, item, {}, context)


class Base(unittest.TestCase):
    def make(self, **cfg):
        self.clock, self.sp, self.fx = Clock(), FakeSpotify(), FakeFluxer()
        self.sp.snap = snap()
        self.r = Runner(Config(data_dir=Path("."), **cfg), self.sp, self.fx, clock=self.clock)
        return self.r

    def tick(self, seconds=0):
        """Advance the fake clock, run one poll, return the last status Fluxer accepted."""
        self.clock.t += seconds
        self.r.tick()
        return self.fx.sent[-1] if self.fx.sent else None


class Rotation(Base):
    def test_order_and_timing(self):
        self.make()
        self.assertEqual(self.tick(), NOW)
        self.assertEqual(self.tick(29), NOW)
        self.assertEqual(self.tick(1), PL)
        self.assertEqual(self.tick(30), TOP)
        self.assertEqual(self.tick(30), TODAY)
        self.assertEqual(self.tick(30), NOW)  # wraps around
        self.assertEqual(self.tick(30), PL)
        self.assertEqual(self.fx.sent, [NOW, PL, TOP, TODAY, NOW, PL])

    def test_no_patch_when_text_unchanged(self):
        self.make()
        self.tick()
        for _ in range(12):  # 60 s of 5 s polls = two slot changes
            self.tick(5)
        self.assertEqual(self.fx.sent, [NOW, PL, TOP])

    def test_track_change_shows_now_immediately_and_restarts(self):
        self.make()
        self.tick()
        self.assertEqual(self.tick(30), PL)
        self.sp.snap = snap(TRACK2)
        self.assertEqual(self.tick(5), "🎵 Other – A")
        self.assertEqual(self.tick(29), "🎵 Other – A")
        self.assertEqual(self.tick(1), PL)

    def test_new_song_starts_on_now_even_if_now_is_not_first(self):
        self.make(lines=("top_artist", "now"))
        self.assertEqual(self.tick(), "🎵 Song – A")  # 'now' leads on a fresh track
        self.assertEqual(self.tick(30), TOP)

    def test_unavailable_lines_are_skipped(self):
        self.make()
        self.sp.snap = snap(PODCAST, context={"type": "show", "uri": "spotify:show:S1"})
        self.sp.routes["/me/top/artists"] = {"items": []}
        for dt in (0, 30, 30):
            self.tick(dt)
        self.assertEqual(self.fx.sent, ["🎵 Folge 1 – Pod", TODAY, "🎵 Folge 1 – Pod"])

    def test_single_available_line_never_rotates(self):
        self.make()
        self.sp.snap = snap(PODCAST, context=None)
        self.sp.routes["/me/top/artists"] = {"items": []}
        self.sp.routes["/me/player/recently-played"] = {"items": []}
        for _ in range(10):
            self.tick(30)
        self.assertEqual(self.fx.sent, ["🎵 Folge 1 – Pod"])

    def test_no_rotate_is_first_line_only_and_makes_no_extra_calls(self):
        self.make(no_rotate=True)
        for _ in range(5):
            self.tick(30)
        self.assertEqual((self.fx.sent, self.sp.calls), ([NOW], []))

    def test_first_line_unavailable_falls_to_next_in_no_rotate(self):
        self.make(no_rotate=True, lines=("playlist", "now"))
        self.sp.snap = snap(context=None)
        self.assertEqual(self.tick(), NOW)

    def test_custom_lines_and_order(self):
        self.make(lines=("top_artist", "{title} @ {album}", "{playlist}"))
        self.assertEqual(self.tick(), TOP)
        self.assertEqual(self.tick(30), "Song @ Alb")
        self.assertEqual(self.tick(30), "Mix")

    def test_custom_line_with_missing_data_is_skipped(self):
        self.make(lines=("now", "{playlist} · {top_artist}"))
        self.sp.snap = snap(context=None)
        for _ in range(3):
            self.tick(30)
        self.assertEqual(self.fx.sent, [NOW])


class Caches(Base):
    def test_ttls(self):
        self.make(lines=("top_artist", "playlist", "listening_today"))
        self.tick()
        for _ in range(59):  # 59 minutes of polling, one poll a minute
            self.tick(60)
        self.assertEqual((self.sp.n("/me/top/artists"), self.sp.n("/playlists/")), (1, 1))
        self.assertEqual(self.sp.n("/me/player/recently-played"), 12)  # every 5 min
        self.tick(60)
        self.assertEqual((self.sp.n("/me/top/artists"), self.sp.n("/playlists/")), (2, 2))  # hourly

    def test_playlist_looked_up_once_per_context(self):
        self.make(lines=("playlist",))
        self.tick()
        self.sp.snap = snap(TRACK2)  # same playlist, next song
        self.tick(5)
        self.assertEqual(self.sp.n("/playlists/"), 1)
        self.sp.routes["/playlists/PL2"] = {"name": "Other mix"}
        self.sp.snap = snap(TRACK2, context={"type": "playlist", "uri": "spotify:playlist:PL2"})
        self.assertEqual(self.tick(5), '💿 aus "Other mix"')
        self.assertEqual(self.sp.n("/playlists/"), 2)

    def test_playlist_403_404_falls_back_to_album_without_hammering(self):
        for status in (403, 404):
            self.make(lines=("playlist",))
            self.sp.routes["/playlists/PL1"] = HttpError(status, {"error": {"status": status}})
            self.assertEqual(self.tick(), '💿 aus "Alb"')
            self.sp.snap = snap({**TRACK2, "album": {"name": "Alb2"}})
            self.assertEqual(self.tick(5), '💿 aus "Alb2"')  # fallback follows the track, the 403 is cached
            self.assertEqual(self.sp.n("/playlists/"), 1)

    def test_playlist_without_album_and_no_name_skips_the_line(self):
        self.make(lines=("now", "playlist"))
        self.sp.routes["/playlists/PL1"] = HttpError(404, {})
        self.sp.snap = snap({**TRACK, "album": {}})
        for _ in range(3):
            self.tick(30)
        self.assertEqual(self.fx.sent, [NOW])

    def test_playlist_rate_limit_uses_album_then_retries_after_retry_after(self):
        self.make(lines=("playlist",))
        self.sp.routes["/playlists/PL1"] = HttpError(429, {}, {"retry-after": "90"})
        self.assertEqual(self.tick(), '💿 aus "Alb"')
        self.tick(60)
        self.assertEqual(self.sp.n("/playlists/"), 1)
        self.sp.routes["/playlists/PL1"] = {"name": "Mix"}
        self.assertEqual(self.tick(31), PL)

    def test_album_context_needs_no_request(self):
        self.make(lines=("playlist",))
        self.sp.snap = snap(context={"type": "album", "uri": "spotify:album:AL1"})
        self.assertEqual(self.tick(), '💿 aus "Alb"')
        self.assertEqual(self.sp.calls, [])

    def test_failed_top_lookup_is_negative_cached_and_never_raises(self):
        self.make(lines=("top_artist", "now"))
        self.sp.routes["/me/top/artists"] = NetworkError("down")
        for _ in range(6):
            self.tick(5)
        self.assertEqual((self.sp.n("/me/top/artists"), self.fx.sent), (1, [NOW]))

    def test_new_local_day_does_not_reuse_yesterdays_total(self):
        self.make(lines=("listening_today",))
        self.tick()
        self.clock.t = datetime(2026, 10, 3, 0, 1).timestamp()
        self.sp.routes["/me/player/recently-played"] = recent((self.clock.t - 30, 3))
        self.r.tick()
        self.assertEqual(self.sp.n("/me/player/recently-played"), 2)
        self.assertEqual(self.fx.sent[-1], "🎧 heute 0 h 3 min gehört")


class Today(Base):
    def test_sum_and_local_day_boundary(self):
        mid = lines.local_midnight(T0)
        items = recent((T0, 30), (mid + 3600, 50), (mid + 600, 10), (mid - 3600, 60))["items"]
        # 23:00 yesterday is excluded; 00:10 counts (a play belongs to the day it ended); 01:00 ran at most the 50 min gap
        self.assertEqual(lines.listened_seconds(items, mid), (30 + 50 + 10) * 60)

    def test_skipped_track_is_capped_by_the_gap(self):
        mid = lines.local_midnight(T0)
        items = recent((mid + 3630, 4), (mid + 3600, 4))["items"]  # second play ended 30 s after the first
        self.assertEqual(lines.listened_seconds(items, mid), 4 * 60 + 30)

    def test_midnight_is_local_not_utc(self):
        mid = lines.local_midnight(T0)
        self.assertEqual(datetime.fromtimestamp(mid).time().isoformat(), "00:00:00")
        self.assertEqual(lines.local_midnight(mid + 1), mid)

    def test_garbage_items_ignored(self):
        self.assertEqual(lines.listened_seconds([{"played_at": "nope"}, {}, {"track": {}}], 0), 0)

    def test_under_a_minute_is_unavailable(self):
        self.make(lines=("listening_today",))
        self.sp.routes["/me/player/recently-played"] = recent((T0 - 60, 0))
        self.tick()
        self.assertEqual(self.fx.sent, [None])  # nothing to show -> status cleared, no "0 h 0 min"

    def test_hours_and_minutes(self):
        self.make(lines=("listening_today",))
        self.sp.routes["/me/player/recently-played"] = recent((T0 - 60, 125))
        self.assertEqual(self.tick(), "🎧 heute 2 h 5 min gehört")


class PauseModes(Base):
    def paused(self, mode, **cfg):
        self.make(on_pause=mode, **cfg)
        self.tick()
        self.sp.snap = snap(playing=False)

    def test_clear(self):
        self.paused("clear")
        self.assertIsNone(self.tick(5))
        self.assertEqual(self.fx.sent, [NOW, None])

    def test_keep(self):
        self.paused("keep")
        for _ in range(4):
            self.tick(30)
        self.assertEqual(self.fx.sent, [NOW])

    def test_stats_rotates_only_stats_lines(self):
        self.paused("stats")
        seen = [self.tick(0 if i == 0 else 30) for i in range(5)]
        self.assertEqual(seen, [TOP, TODAY, TOP, TODAY, TOP])
        self.assertFalse({NOW, PL} & set(self.fx.sent[1:]))

    def test_stats_without_any_stats_line_clears(self):
        self.paused("stats", lines=("now", "playlist"))
        self.assertIsNone(self.tick(5))

    def test_resume_starts_with_now(self):
        self.paused("stats")
        self.tick(5)
        self.sp.snap = snap()
        self.assertEqual(self.tick(5), NOW)

    def test_idle_always_clears_even_with_keep_or_stats(self):
        for mode in ("keep", "stats"):
            self.paused(mode)
            self.sp.snap = Snapshot("idle", False, None, {})
            self.assertIsNone(self.tick(5))
            self.assertIsNone(self.fx.sent[-1])


class Truncation(Base):
    def test_long_title_keeps_leading_emoji_and_128_limit(self):
        self.make(lines=("now",))
        self.sp.snap = snap({**TRACK, "name": "x" * 300})
        out = self.tick()
        self.assertEqual(len(out), 128)
        self.assertTrue(out.startswith("🎵 xxx") and out.endswith("…"))

    def test_truncate_helper(self):
        self.assertEqual(truncate("a" * 200), "a" * 127 + "…")
        self.assertEqual(truncate("a" * 126 + "‍" + "bbbb"), "a" * 126 + "…")  # no dangling ZWJ
        self.assertEqual(truncate("short"), "short")

    def test_custom_line_truncated(self):
        self.make(lines=("🔥 {title}",))
        self.sp.snap = snap({**TRACK, "name": "y" * 300})
        out = self.tick()
        self.assertEqual((len(out), out[:2]), (128, "🔥 "))


class Failures(Base):
    def test_fluxer_errors_never_crash_and_retry_after_is_honoured(self):
        self.make(lines=("now",))
        self.fx.error = HttpError(429, {}, {"retry-after": "60"})
        self.tick()  # must not raise
        self.fx.error = None
        self.tick(30)
        self.assertEqual(self.fx.sent, [])  # still on hold
        self.assertEqual(self.tick(31), NOW)  # hold over

    def test_network_error_backs_off_exponentially_and_recovers(self):
        self.make(lines=("now",))
        self.fx.error = NetworkError("down")
        self.tick()
        self.assertEqual(self.r.hold_until, T0 + 10)
        self.tick(10)
        self.assertEqual(self.r.hold_until, T0 + 30)
        self.fx.error = None
        self.assertEqual(self.tick(20), NOW)
        self.assertEqual(self.r.status_failures, 0)

    def test_webhook_still_pushed_while_status_is_on_hold(self):
        self.make(lines=("now",))
        self.r.webhook = mock.Mock()
        self.fx.error = HttpError(500, {})
        self.tick()
        self.r.webhook.push.assert_called_once()


class ConfigAndCli(unittest.TestCase):
    def cfg(self, environ=None, **flags):
        with tempfile.TemporaryDirectory() as d:
            return load_config(Namespace(data_dir=d, **flags), environ=environ or {})

    def test_defaults(self):
        c = self.cfg()
        self.assertEqual((c.lines, c.rotate, c.no_rotate), (("now", "playlist", "top_artist", "listening_today"), 30.0, False))

    def test_rotate_minimum_is_clamped_with_warning(self):
        with self.assertLogs("fluxer_spotify.config", "WARNING"):
            self.assertEqual(self.cfg({"ROTATE_SECONDS": "3"}).rotate, 15.0)
        with self.assertLogs("fluxer_spotify.config", "WARNING"):
            self.assertEqual(self.cfg(rotate="1").rotate, 15.0)
        self.assertEqual(self.cfg(rotate="45").rotate, 45.0)

    def test_precedence_flag_over_env(self):
        self.assertEqual(self.cfg({"ROTATE_SECONDS": "40"}, rotate="20").rotate, 20.0)
        self.assertEqual(self.cfg({"STATUS_LINES": "now,top_artist"}).lines, ("now", "top_artist"))
        self.assertEqual(self.cfg({"STATUS_LINES": "now"}, lines="top_artist").lines, ("top_artist",))

    def test_dotenv(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".env").write_text("STATUS_LINES=now|📀 {album}, remastered\nNO_ROTATE=1\nON_PAUSE=stats\n", encoding="utf-8")
            c = load_config(Namespace(data_dir=d), environ={})
        self.assertEqual((c.lines, c.no_rotate, c.on_pause), (("now", "📀 {album}, remastered"), True, "stats"))

    def test_no_rotate_flag_and_env_zero(self):
        self.assertTrue(self.cfg(no_rotate=True).no_rotate)
        self.assertFalse(self.cfg({"NO_ROTATE": "0"}).no_rotate)

    def test_invalid_values(self):
        for env in ({"ROTATE_SECONDS": "abc"}, {"STATUS_LINES": "now,nwo"}, {"STATUS_LINES": "{bogus}"},
                    {"STATUS_LINES": "{title"}, {"ON_PAUSE": "maybe"}):
            with self.assertRaises(Fatal, msg=env):
                self.cfg(env)

    def test_doctor_shows_lines_and_interval(self):
        with tempfile.TemporaryDirectory() as d:
            c = cli.Ctx(Config(data_dir=Path(d), lines=("now", "top_artist"), rotate=45), None, None, None)
            with mock.patch.object(background, "running_pid", return_value=None), contextlib.redirect_stdout(io.StringIO()) as out:
                c.doctor()
            self.assertIn("now, top_artist", out.getvalue())
            self.assertIn("45", out.getvalue())
            c.cfg.no_rotate = True
            with mock.patch.object(background, "running_pid", return_value=None), contextlib.redirect_stdout(io.StringIO()) as out:
                c.doctor()
            self.assertIn("no rotation", out.getvalue())

    def test_background_handover_passes_rotation_settings(self):
        with tempfile.TemporaryDirectory() as d:
            c = cli.Ctx(Config(data_dir=Path(d), lines=("now", "{album}"), rotate=20, no_rotate=True), None, None, None)
            with mock.patch.object(background, "spawn_background", return_value=1) as sp, \
                    mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
                c.start_background()
            extra = sp.call_args[0][1]
            self.assertEqual(extra[extra.index("--lines") + 1], "now|{album}")
            self.assertIn("--no-rotate", extra)
            self.assertEqual(extra[extra.index("--rotate") + 1], "20")


if __name__ == "__main__":
    unittest.main()

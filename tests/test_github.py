"""GitHub source: parsing, client, status lines, ON_IDLE, config and the github-login command. No network."""
import contextlib
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from fluxer_spotify import background, cli, errors, github
from fluxer_spotify.config import DEFAULT_LINES, GH_DEFAULT_LINES, Config, load_config, parse_lines
from fluxer_spotify.errors import AuthError, Fatal
from fluxer_spotify.http import HttpError, NetworkError
from fluxer_spotify.lines import Lines
from fluxer_spotify.runner import Runner
from fluxer_spotify.spotify import Snapshot
from fluxer_spotify.store import Store
from tests.helpers import make_http
from tests.test_rotation import NOW, TOP, TRACK, Clock, FakeFluxer, FakeSpotify, T0, iso

TOKEN = "github_pat_" + "Q" * 30
PLAYING, IDLE = Snapshot(("t1", True), True, TRACK, {}), Snapshot("idle", False, None, {})
DAYS = [("2026-09-28", 3), ("2026-09-29", 1), ("2026-09-30", 2), ("2026-10-01", 4), ("2026-10-02", 5)]


def gql(days=DAYS, prs=2, reviews=1, issues=0, repo="sophie/Fluxer-Spotify", pushed_at=None, stars=(10, 3), followers=42):
    """A GraphQL response the way GitHub shapes it (see github.QUERY)."""
    pushed = [{"nameWithOwner": repo, "pushedAt": pushed_at or iso(T0 - 7200)}] if repo else []
    return {"data": {
        "viewer": {"login": "sophie", "followers": {"totalCount": followers},
                   "starred": {"nodes": [{"stargazerCount": s} for s in stars]}, "pushed": {"nodes": pushed},
                   "contributionsCollection": {"contributionCalendar": {"weeks": [
                       {"contributionDays": [{"date": d, "contributionCount": c} for d, c in days[:3]]},
                       {"contributionDays": [{"date": d, "contributionCount": c} for d, c in days[3:]]}]}}},
        "prs": {"issueCount": prs}, "reviews": {"issueCount": reviews}, "issues": {"issueCount": issues}}}


STATS = github.parse_stats(gql()["data"])


class FakeGitHub:
    def __init__(self, stats=None, error=None):
        self.data, self.error, self.calls = dict(STATS if stats is None else stats), error, 0

    def stats(self):
        self.calls += 1
        if self.error:
            raise self.error
        return dict(self.data)


class Parsing(unittest.TestCase):
    def test_stats(self):
        self.assertEqual(STATS, {"repo": "sophie/Fluxer-Spotify", "pushed_at": T0 - 7200, "commits": 5, "streak": 5, "prs": 2,
                                 "reviews": 1, "issues": 0, "stars": 13, "followers": 42})

    def test_today_without_contributions_does_not_break_the_streak_yet(self):
        self.assertEqual(github.activity([{"contributionDays": [{"date": "2026-10-01", "contributionCount": 4},
                                                                  {"date": "2026-10-02", "contributionCount": 0}]}]), (0, 1))

    def test_a_gap_ends_the_streak(self):
        days = [("2026-09-29", 5), ("2026-09-30", 0), ("2026-10-01", 2), ("2026-10-02", 1)]
        self.assertEqual(github.parse_stats(gql(days=days)["data"])["streak"], 2)

    def test_days_after_today_are_ignored(self):
        weeks = [{"contributionDays": [{"date": "2026-10-01", "contributionCount": 4}, {"date": "2026-10-02", "contributionCount": 5},
                                       {"date": "2026-10-03", "contributionCount": 0}, {"date": "2026-10-04", "contributionCount": 0}]}]
        self.assertEqual(github.activity(weeks, until="2026-10-02"), (5, 2))
        self.assertEqual(github.activity(weeks), (0, 0))  # without the bound a zero-filled future day would hide today's work
        self.assertIn(github.latest_date(T0), ("2026-10-02", "2026-10-03"))  # the later of local and UTC date: depends on the time zone

    def test_empty_and_garbage(self):
        self.assertEqual(github.activity([]), (None, None))
        self.assertEqual(github.activity([None, {"contributionDays": [{"date": 5}, {"date": "x", "contributionCount": "7"}]}]), (None, None))
        self.assertEqual(set(github.parse_stats({}).values()), {None})
        self.assertEqual(set(github.parse_stats(None).values()), {None})

    def test_timestamp_with_and_without_fraction(self):
        self.assertEqual(github.parse_epoch("2026-10-02T08:04:20Z"), github.parse_epoch("2026-10-02T08:04:20.000Z"))
        self.assertIsNone(github.parse_epoch("nope"))

    def test_private_repo_names_cannot_reach_the_status(self):
        self.assertIn("privacy: PUBLIC", github.QUERY)  # the only repo name we ever show comes from this field


class Client(unittest.TestCase):
    def test_stats_request(self):
        http, t, _ = make_http((200, gql()))
        self.assertEqual(github.GitHubClient(http, TOKEN, clock=lambda: T0).stats(), STATS)
        method, url, headers, body = t.calls[0]
        self.assertEqual((method, url), ("POST", github.GRAPHQL))
        self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
        self.assertIn("2022-11-28", headers["X-GitHub-Api-Version"])
        self.assertIn("viewer", body["query"])

    def test_me(self):
        http, t, _ = make_http((200, {"login": "sophie"}))
        self.assertEqual(github.GitHubClient(http, TOKEN).me(), "sophie")
        self.assertEqual((t.calls[0][0], t.calls[0][1]), ("GET", github.API + "/user"))

    def test_rejected_token_is_an_auth_error(self):
        for call in ("me", "stats"):
            http, _, _ = make_http((401, {"message": "Bad credentials"}))
            with self.assertRaises(AuthError) as cm:
                getattr(github.GitHubClient(http, TOKEN, clock=lambda: T0), call)()
            self.assertNotIn(TOKEN, str(cm.exception))

    def test_graphql_errors_without_data_are_a_transient_error(self):
        http, _, _ = make_http((200, {"data": None, "errors": [{"message": "Something broke"}]}))
        with self.assertRaises(NetworkError) as cm:
            github.GitHubClient(http, TOKEN, clock=lambda: T0).stats()
        self.assertIn("Something broke", str(cm.exception))

    def test_graphql_rate_limit_becomes_429(self):
        http, _, _ = make_http((200, {"data": None, "errors": [{"type": "RATE_LIMITED", "message": "x"}]}))
        with self.assertRaises(HttpError) as cm:
            github.GitHubClient(http, TOKEN, clock=lambda: T0).stats()
        self.assertEqual(cm.exception.status, 429)

    def test_other_http_errors_pass_through_without_retry(self):
        http, t, sleeps = make_http((403, {"message": "limit"}, {"X-RateLimit-Remaining": "0"}))
        with self.assertRaises(HttpError) as cm:
            github.GitHubClient(http, TOKEN, clock=lambda: T0).stats()
        self.assertEqual((cm.exception.status, len(t.calls), sleeps), (403, 1, []))


class LineCase(unittest.TestCase):
    def setUp(self):
        self.addCleanup(errors.set_lang, errors.get_lang())
        self.clock, self.sp = Clock(), FakeSpotify()

    def lines(self, gh, **cfg):
        self.gh = gh
        return Lines(Config(data_dir=Path("."), **cfg), self.sp, self.clock, gh)

    def render(self, name, snap=PLAYING, **stats):
        return self.lines(FakeGitHub({**STATS, **stats})).render(name, snap)


class Rendering(LineCase):
    def test_german(self):
        errors.set_lang("de")
        self.assertEqual([self.render(n) for n in ("gh_push", "gh_commits", "gh_prs", "gh_reviews", "gh_issues", "gh_streak", "gh_stars", "gh_followers")],
                         ["💻 zuletzt gepusht: sophie/Fluxer-Spotify (vor 2 h)", "💻 heute 5 Beiträge auf GitHub", "🔀 2 offene Pull Requests",
                          "👀 1 Review angefragt", None, "🔥 5 Tage in Folge aktiv", "⭐ 13 Sterne auf GitHub", "👥 42 Follower"])

    def test_english(self):
        errors.set_lang("en")
        self.assertEqual([self.render(n) for n in ("gh_push", "gh_commits", "gh_prs", "gh_reviews", "gh_issues", "gh_streak", "gh_stars", "gh_followers")],
                         ["💻 last push: sophie/Fluxer-Spotify (2 h ago)", "💻 5 contributions on GitHub today", "🔀 2 open pull requests",
                          "👀 1 review requested", None, "🔥 5-day streak on GitHub", "⭐ 13 stars on GitHub", "👥 42 followers"])

    def test_singular(self):
        errors.set_lang("de")
        one = dict(commits=1, prs=1, reviews=1, issues=1, stars=1, followers=1)
        self.assertEqual([self.render(n, **one) for n in ("gh_commits", "gh_prs", "gh_reviews", "gh_issues", "gh_stars")],
                         ["💻 heute 1 Beitrag auf GitHub", "🔀 1 offener Pull Request", "👀 1 Review angefragt",
                          "📌 1 Issue zugewiesen", "⭐ 1 Stern auf GitHub"])
        errors.set_lang("en")
        self.assertEqual([self.render(n, **one) for n in ("gh_commits", "gh_prs", "gh_issues", "gh_stars", "gh_followers")],
                         ["💻 1 contribution on GitHub today", "🔀 1 open pull request", "📌 1 issue assigned", "⭐ 1 star on GitHub", "👥 1 follower"])

    def test_zero_and_a_one_day_streak_are_hidden(self):
        for name, stats in (("gh_prs", dict(prs=0)), ("gh_commits", dict(commits=0)), ("gh_stars", dict(stars=0)),
                            ("gh_followers", dict(followers=0)), ("gh_streak", dict(streak=1)), ("gh_streak", dict(streak=0))):
            self.assertIsNone(self.render(name, **stats), (name, stats))

    def test_missing_data_hides_the_line(self):
        for name, stats in (("gh_push", dict(repo=None)), ("gh_push", dict(pushed_at=None)), ("gh_prs", dict(prs=None)),
                            ("gh_streak", dict(streak=None))):
            self.assertIsNone(self.render(name, **stats), (name, stats))

    def test_ago_units(self):
        errors.set_lang("en")
        for seconds, text in ((5, "just now"), (120, "2 min ago"), (7200, "2 h ago"), (86400, "1 day ago"), (3 * 86400, "3 days ago")):
            self.assertEqual(self.render("gh_push", pushed_at=T0 - seconds), f"💻 last push: sophie/Fluxer-Spotify ({text})")
        errors.set_lang("de")
        self.assertEqual(self.render("gh_push", pushed_at=T0 - 86400), "💻 zuletzt gepusht: sophie/Fluxer-Spotify (vor 1 Tag)")
        self.assertEqual(self.render("gh_push", pushed_at=T0 - 3 * 86400), "💻 zuletzt gepusht: sophie/Fluxer-Spotify (vor 3 Tagen)")

    def test_custom_line_may_show_zero_and_mix_with_spotify(self):
        l = self.lines(FakeGitHub({**STATS, "issues": 0}))
        self.assertEqual(l.render("{gh_issues} Issues · {title}", PLAYING), "0 Issues · Song")
        self.assertEqual(l.render("{gh_repo} {gh_prs}/{gh_reviews}", IDLE), "sophie/Fluxer-Spotify 2/1")

    def test_not_connected(self):
        l = self.lines(None)
        for name in ("gh_push", "gh_prs", "{gh_prs} PRs"):
            self.assertIsNone(l.render(name, PLAYING))

    def test_track_lines_are_unavailable_while_idle_but_the_rest_works(self):
        l = self.lines(FakeGitHub())
        self.assertIsNone(l.render("now", IDLE))
        self.assertIsNone(l.render("playlist", IDLE))
        self.assertIsNone(l.render("{title}", IDLE))
        self.assertEqual(l.render("top_artist", IDLE), TOP)
        self.assertEqual(l.render("{playlist} x", IDLE) , None)


class Caching(LineCase):
    def test_one_request_serves_all_lines_for_five_minutes(self):
        l = self.lines(FakeGitHub())
        for name in ("gh_push", "gh_commits", "gh_prs", "gh_reviews", "gh_streak", "gh_stars", "gh_followers"):
            l.render(name, PLAYING)
        self.assertEqual(self.gh.calls, 1)
        self.clock.t += 299
        l.render("gh_prs", PLAYING)
        self.assertEqual(self.gh.calls, 1)
        self.clock.t += 2
        l.render("gh_prs", PLAYING)
        self.assertEqual(self.gh.calls, 2)

    def test_network_failure_never_raises_and_is_negative_cached(self):
        l = self.lines(FakeGitHub(error=NetworkError("down")))
        self.assertIsNone(l.render("gh_prs", PLAYING))
        self.assertIsNone(l.render("gh_push", PLAYING))
        self.assertEqual(self.gh.calls, 1)
        self.clock.t += 121
        l.render("gh_prs", PLAYING)
        self.assertEqual(self.gh.calls, 2)

    def test_rejected_token_never_stops_the_music_status(self):
        l = self.lines(FakeGitHub(error=github.rejected()))
        with self.assertLogs("fluxer_spotify.lines", "WARNING"):
            self.assertIsNone(l.render("gh_prs", PLAYING))
        self.assertEqual(l.render("top_artist", PLAYING), TOP)  # Spotify lines unaffected
        self.clock.t += 3000
        l.render("gh_prs", PLAYING)
        self.assertEqual(self.gh.calls, 1)  # quiet for an hour, not hammered

    def test_primary_rate_limit_waits_for_the_reset(self):
        err = HttpError(403, {"message": "limit"}, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(T0) + 500)})
        l = self.lines(FakeGitHub(error=err))
        l.render("gh_prs", PLAYING)
        self.clock.t += 400
        l.render("gh_prs", PLAYING)
        self.assertEqual(self.gh.calls, 1)
        self.clock.t += 101
        l.render("gh_prs", PLAYING)
        self.assertEqual(self.gh.calls, 2)

    def test_retry_after_wins(self):
        l = self.lines(FakeGitHub(error=HttpError(403, {}, {"retry-after": "60"})))
        l.render("gh_prs", PLAYING)
        self.clock.t += 61
        l.render("gh_prs", PLAYING)
        self.assertEqual(self.gh.calls, 2)


class RunnerCase(unittest.TestCase):
    def make(self, gh=None, **cfg):
        errors.set_lang("de")
        self.addCleanup(errors.set_lang, None)
        self.clock, self.sp, self.fx = Clock(), FakeSpotify(), FakeFluxer()
        self.sp.snap = PLAYING
        self.r = Runner(Config(data_dir=Path("."), **cfg), self.sp, self.fx, clock=self.clock, github=FakeGitHub() if gh is None else gh)

    def tick(self, seconds=0):
        self.clock.t += seconds
        self.r.tick()
        return self.fx.sent[-1] if self.fx.sent else "nothing sent"


PRS, PUSH = "🔀 2 offene Pull Requests", "💻 zuletzt gepusht: sophie/Fluxer-Spotify (vor 2 h)"


class Idle(RunnerCase):
    def test_default_still_clears_when_nothing_plays(self):
        self.make(lines=("now", "gh_prs"))
        self.tick()
        self.sp.snap = IDLE
        self.assertIsNone(self.tick(5))

    def test_idle_lines_keeps_rotating_what_needs_no_track(self):
        self.make(on_idle="lines", lines=("now", "playlist", "top_artist", "gh_prs", "gh_push"))
        self.sp.snap = IDLE
        self.assertEqual([self.tick(0 if i == 0 else 30) for i in range(5)], [TOP, PRS, PUSH, TOP, PRS])

    def test_idle_lines_includes_custom_lines_that_need_no_track(self):
        self.make(on_idle="lines", lines=("now", "{gh_prs} offen", "{title}"))
        self.sp.snap = IDLE
        self.assertEqual([self.tick(0 if i == 0 else 30) for i in range(3)], ["2 offen"] * 3)

    def test_idle_lines_with_nothing_available_clears(self):
        self.make(on_idle="lines", lines=("now", "playlist"))
        self.sp.snap = PLAYING
        self.tick()
        self.sp.snap = IDLE
        self.assertIsNone(self.tick(5))

    def test_music_starts_with_now_again(self):
        self.make(on_idle="lines", lines=("now", "gh_prs"))
        self.sp.snap = IDLE
        self.assertEqual(self.tick(), PRS)
        self.sp.snap = PLAYING
        self.assertEqual(self.tick(5), NOW)

    def test_github_down_while_idle_clears_instead_of_crashing(self):
        self.make(gh=FakeGitHub(error=NetworkError("down")), on_idle="lines", lines=("now", "gh_prs"))
        self.sp.snap = IDLE
        self.assertIsNone(self.tick())


class Rotation(RunnerCase):
    def test_github_lines_join_the_rotation_while_playing(self):
        self.make(lines=("now", "gh_prs", "gh_push"))
        self.assertEqual([self.tick(0 if i == 0 else 30) for i in range(4)], [NOW, PRS, PUSH, NOW])

    def test_pause_stats_mode_includes_github_lines(self):
        self.make(on_pause="stats", lines=("now", "top_artist", "gh_prs"))
        self.tick()
        self.sp.snap = Snapshot(("t1", False), False, TRACK, {})
        self.assertEqual([self.tick(0 if i == 0 else 30) for i in range(3)], [TOP, PRS, TOP])

    def test_without_github_nothing_changes(self):
        self.make(gh=None, lines=("now", "gh_prs", "top_artist"))
        self.r.lines.gh = None
        self.assertEqual([self.tick(0 if i == 0 else 30) for i in range(3)], [NOW, TOP, NOW])


class ConfigCase(unittest.TestCase):
    def cfg(self, environ=None, **flags):
        with tempfile.TemporaryDirectory() as d:
            return load_config(Namespace(data_dir=d, **flags), environ=environ or {})

    def test_on_idle(self):
        self.assertEqual(self.cfg().on_idle, "clear")
        self.assertEqual(self.cfg({"ON_IDLE": "Lines"}).on_idle, "lines")
        self.assertEqual(self.cfg({"ON_IDLE": "clear"}, on_idle="lines").on_idle, "lines")  # flag wins
        with self.assertRaises(Fatal):
            self.cfg({"ON_IDLE": "never"})

    def test_lines_explicit(self):
        self.assertFalse(self.cfg().lines_explicit)
        self.assertTrue(self.cfg({"STATUS_LINES": "now,gh_prs"}).lines_explicit)
        self.assertTrue(self.cfg({"STATUS_LINES": ",".join(DEFAULT_LINES)}).lines_explicit)  # same as the default, but chosen

    def test_github_lines_and_placeholders_are_accepted(self):
        self.assertEqual(parse_lines("now,gh_push,gh_prs"), ("now", "gh_push", "gh_prs"))
        self.assertEqual(parse_lines("{gh_commits} Commits|{gh_repo} ({gh_ago})"), ("{gh_commits} Commits", "{gh_repo} ({gh_ago})"))
        with self.assertRaises(Fatal):
            parse_lines("{gh_nope}")
        with self.assertRaises(Fatal):
            parse_lines("gh_nope")


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def run_cli(self, argv, http, token=TOKEN):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = cli.main(argv + ["--data-dir", str(self.d)], http=http, getpass_fn=lambda prompt="": token, input_fn=lambda p="": "")
        return rc, out.getvalue()

    def ctx(self, http=None, **cfg):
        return cli.Ctx(Config(data_dir=self.d, **cfg), http, None, None)

    def test_github_login_validates_stores_and_never_prints_the_token(self):
        http, t, _ = make_http((200, {"login": "sophie"}))
        rc, out = self.run_cli(["github-login"], http)
        self.assertEqual(rc, 0)
        store = Store(self.d / "state.json")
        self.assertEqual((store.get("github_token"), store.get("github_user")), (TOKEN, "sophie"))
        self.assertNotIn(TOKEN, out)
        self.assertEqual(t.calls[0][2]["Authorization"], f"Bearer {TOKEN}")
        self.assertIn("ON_IDLE=lines", out)

    def test_rejected_token_is_not_stored(self):
        http, _, _ = make_http((401, {"message": "Bad credentials"}))
        rc, out = self.run_cli(["github-login"], http)
        self.assertEqual(rc, 1)
        self.assertFalse((self.d / "state.json").exists() and Store(self.d / "state.json").get("github_token"))
        self.assertNotIn(TOKEN, out)

    def test_empty_token_is_cancelled(self):
        rc, _ = self.run_cli(["github-login"], make_http()[0], token="  ")
        self.assertEqual(rc, 1)

    def test_connecting_adds_the_default_github_lines_unless_lines_were_chosen(self):
        Store(self.d / "state.json").update(github_token=TOKEN, github_user="sophie")
        self.assertEqual(self.ctx().cfg.lines, DEFAULT_LINES + GH_DEFAULT_LINES)
        self.assertEqual(self.ctx(lines=("now",), lines_explicit=True).cfg.lines, ("now",))

    def test_not_connected_keeps_the_default_lines(self):
        self.assertEqual(self.ctx().cfg.lines, DEFAULT_LINES)

    def test_logout_deletes_the_github_token_and_points_to_revocation(self):
        Store(self.d / "state.json").update(github_token=TOKEN, github_user="sophie")
        rc, out = self.run_cli(["logout"], make_http()[0])
        self.assertEqual(rc, 0)
        store = Store(self.d / "state.json")
        self.assertIsNone(store.get("github_token"))
        self.assertIsNone(store.get("github_user"))
        self.assertIn("personal-access-tokens", out)

    def doctor(self, c):
        with mock.patch.object(background, "running_pid", return_value=None), contextlib.redirect_stdout(io.StringIO()) as out:
            code = c.doctor()
        return code, out.getvalue()

    def test_doctor_checks_the_token(self):
        Store(self.d / "state.json").update(github_token=TOKEN, github_user="sophie")
        _, out = self.doctor(self.ctx(make_http((200, {"login": "sophie"}))[0]))
        self.assertIn("GitHub token valid: sophie", out)
        _, out = self.doctor(self.ctx(make_http((401, {"message": "Bad credentials"}))[0]))
        self.assertIn("[!!] GitHub-Token ungueltig", out)  # a problem, not just info
        self.assertIn("python spotify_status.py github-login", out)
        self.assertNotIn(TOKEN, out)

    def test_doctor_flags_github_lines_without_a_connection_but_not_otherwise(self):
        code, out = self.doctor(self.ctx(lines=("now", "gh_prs")))
        self.assertIn("GitHub lines are enabled but GitHub is not connected", out)
        _, out = self.doctor(self.ctx())
        self.assertIn("GitHub not connected (optional)", out)

    def test_background_handover_passes_on_idle(self):
        c = self.ctx(on_idle="lines")
        with mock.patch.object(background, "spawn_background", return_value=1) as sp, mock.patch("time.sleep"), \
                contextlib.redirect_stdout(io.StringIO()):
            c.start_background()
        extra = sp.call_args[0][1]
        self.assertEqual(extra[extra.index("--on-idle") + 1], "lines")


if __name__ == "__main__":
    unittest.main()

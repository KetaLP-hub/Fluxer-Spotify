"""Language selection: detection, precedence, bi()/tr(), localized status lines, wizard step, background forwarding."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fluxer_spotify import background, cli, errors, wizard
from fluxer_spotify.config import Config, load_config
from fluxer_spotify.errors import Fatal, bi, blog, detect_lang, set_lang, tr
from fluxer_spotify.spotify import Snapshot
from tests import test_rotation as tr_
from tests.helpers import make_http
from tests.test_wizard import WizardCase


class Detect(unittest.TestCase):
    def check(self, code, expect):
        with mock.patch.object(errors.os, "name", "posix"), mock.patch.dict(errors.os.environ, {"LC_ALL": code}):
            self.assertEqual(detect_lang(), expect)

    def test_mapping(self):
        for code, expect in (("de_DE.UTF-8", "de"), ("de", "de"), ("DE_AT", "de"), ("en_US", "en"), ("fr_FR", "en"), ("C", "en")):
            self.check(code, expect)

    def test_undetectable_is_english(self):
        with mock.patch.object(errors.os, "name", "posix"), mock.patch.dict(errors.os.environ, {}, clear=True), \
                mock.patch("locale.getlocale", return_value=(None, None)):
            self.assertEqual(detect_lang(), "en")

    def test_windows_ui_language_id(self):
        import locale
        self.assertEqual(locale.windows_locale[0x0407], "de_DE")  # what GetUserDefaultUILanguage returns for German


class Bi(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_lang, None)

    def test_selection(self):
        set_lang("de")
        self.assertEqual((bi("a", "b"), tr("a", "b"), blog("a %s", "b %s", 1)), ("a", "a", "a 1"))
        set_lang("en")
        self.assertEqual((bi("a", "b"), tr("a", "b"), blog("a %s", "b %s", 1)), ("b", "b", "b 1"))

    def test_undetermined_shows_both_and_never_doubles_log_args(self):
        set_lang(None)
        self.assertEqual(bi("a", "b"), "a\nb")
        self.assertEqual(bi("a", "b", " / "), "a / b")
        self.assertEqual(blog("a %s", "b %s", 1), "a 1 / b 1")
        self.assertEqual(tr("a", "b"), "a")  # a single-language text cannot show both
        set_lang("xx")
        self.assertIsNone(errors.get_lang())


class ConfigPrecedence(unittest.TestCase):
    def cfg(self, env=None, dotenv=None, args=None):
        with tempfile.TemporaryDirectory() as d:
            if dotenv:
                (Path(d) / ".env").write_text(dotenv, encoding="utf-8")
            ns = mock.Mock(spec=[])
            ns.data_dir = d
            for k, v in (args or {}).items():
                setattr(ns, k, v)
            return load_config(ns, environ=env or {})

    def test_flag_beats_env_beats_dotenv(self):
        self.assertEqual(self.cfg(dotenv="LANGUAGE=de").language, "de")
        self.assertEqual(self.cfg({"LANGUAGE": "en"}, "LANGUAGE=de").language, "en")
        self.assertEqual(self.cfg({"LANGUAGE": "en"}, "LANGUAGE=de", {"language": "DE"}).language, "de")

    def test_unset_is_empty_and_lang_falls_back_to_detection(self):
        c = self.cfg()
        self.assertEqual(c.language, "")
        with mock.patch("fluxer_spotify.config.detect_lang", return_value="de"):
            self.assertEqual(c.lang, "de")
            c.language = "en"
            self.assertEqual(c.lang, "en")
            c.language = "auto"
            self.assertEqual(c.lang, "de")

    def test_unknown_value_fails_clearly(self):
        for kw in ({"dotenv": "LANGUAGE=fr"}, {"args": {"language": "klingon"}}):
            with self.assertRaises(Fatal) as cm:
                self.cfg(**kw)
            self.assertIn("LANGUAGE", str(cm.exception))

    def test_posix_language_variable_is_not_ours(self):
        self.assertEqual(self.cfg({"LANGUAGE": "de_DE:en"}).language, "")

    def test_stored_language_is_last(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "state.json").write_text(json.dumps({"language": "en"}))
            self.assertEqual(cli.Ctx(Config(data_dir=Path(d)), None, None, None).cfg.language, "en")
            self.assertEqual(cli.Ctx(Config(data_dir=Path(d), language="de"), None, None, None).cfg.language, "de")


class LineTexts(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_lang, None)

    def test_defaults_and_plural_zero_cases(self):
        from fluxer_spotify.lines import default_template as t
        set_lang("de")
        self.assertEqual(t("playlist"), '💿 aus "{playlist}"')
        self.assertEqual(t("top_artist"), "🏆 Top-Artist diese Woche: {top_artist}")
        self.assertEqual([t("listening_today", *hm) for hm in ((1, 30), (0, 25), (2, 0), (1, 1))],
                         ["🎧 heute 1 h 30 min gehört", "🎧 heute 25 min gehört", "🎧 heute 2 h gehört", "🎧 heute 1 h 1 min gehört"])
        set_lang("en")
        self.assertEqual(t("playlist"), '💿 from "{playlist}"')
        self.assertEqual(t("top_artist"), "🏆 Top artist this week: {top_artist}")
        self.assertEqual([t("listening_today", *hm) for hm in ((1, 30), (0, 25), (2, 0), (1, 1))],
                         ["🎧 1 h 30 min listened today", "🎧 25 min listened today", "🎧 2 h listened today", "🎧 1 h 1 min listened today"])

    def test_custom_template_untouched_and_limit(self):
        from fluxer_spotify.lines import Lines
        from fluxer_spotify.config import Config
        for lang in ("de", "en"):
            set_lang(lang)
            sp = tr_.FakeSpotify()
            ln = Lines(Config(data_dir=Path(".")), sp, tr_.Clock())
            snap = Snapshot(("t1", True), True, tr_.TRACK, {}, None)
            self.assertEqual(ln.render("{hours}h-{minutes}m {title}", snap), "1h-30m Song")
            sp.routes["/me/top/artists"] = {"items": [{"name": "x" * 300}]}
            self.assertEqual(len(ln.render("top_artist", snap)), 128)

    def test_rendered_in_english(self):
        from fluxer_spotify.lines import Lines
        from fluxer_spotify.config import Config
        set_lang("en")
        ln = Lines(Config(data_dir=Path(".")), tr_.FakeSpotify(), tr_.Clock())
        snap = Snapshot(("t1", True), True, tr_.TRACK, {}, {"type": "playlist", "uri": "spotify:playlist:PL1"})
        self.assertEqual([ln.render(n, snap) for n in ("playlist", "top_artist", "listening_today")],
                         ['💿 from "Mix"', "🏆 Top artist this week: Muse", "🎧 1 h 30 min listened today"])


class WizardLanguageStep(WizardCase):
    def test_skipped_when_configured_or_stored(self):
        self.done_state(autostart_asked=True, background_asked=True)
        for kw in ({"language": "de"}, {"language": "auto"}):
            self.run_wizard(self.ctx(http=make_http((200, {}))[0], **kw))  # would raise StopIteration if it asked
        (self.d / "state.json").write_text(json.dumps({**self.state(), "language": "en"}))
        c = self.ctx(http=make_http((200, {}))[0], language="")
        self.assertEqual(c.cfg.language, "en")
        self.run_wizard(c)

    def test_enter_accepts_detected_language_and_saves_it(self):
        self.done_state(autostart_asked=True, background_asked=True)
        c = self.ctx(inputs=[""], http=make_http((200, {}))[0], language="")
        with mock.patch.object(wizard, "detect_lang", return_value="de"):
            out = self.run_wizard(c)
        self.assertEqual((self.state()["language"], c.cfg.language, errors.get_lang()), ("de", "de", "de"))
        self.assertIn("Sprache", out)

    def test_other_language_can_be_picked(self):
        self.done_state(autostart_asked=True, background_asked=True)
        c = self.ctx(inputs=["e"], http=make_http((200, {}))[0], language="")
        with mock.patch.object(wizard, "detect_lang", return_value="de"):
            self.run_wizard(c)
        self.assertEqual(self.state()["language"], "en")

    def test_not_asked_in_background_mode(self):
        self.done_state(autostart_asked=True, background_asked=True)
        c = self.ctx(http=make_http((200, {}))[0], language="")
        with contextlib.redirect_stdout(io.StringIO()):
            wizard.setup(c, interactive=False)
        self.assertNotIn("language", self.state())


class Forwarding(unittest.TestCase):
    def test_background_gets_the_concrete_language(self):
        for configured, detected, expect in (("en", "de", "en"), ("auto", "de", "de"), ("", "en", "en")):
            with tempfile.TemporaryDirectory() as d, mock.patch("fluxer_spotify.config.detect_lang", return_value=detected):
                c = cli.Ctx(Config(data_dir=Path(d), language=configured), None, None, None)
                with mock.patch.object(background, "spawn_background", return_value=1) as sp, \
                        mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
                    c.start_background()
                extra = sp.call_args[0][1]
                self.assertEqual(extra[extra.index("--lang") + 1], expect)

    def test_lang_flag_works_for_single_commands(self):
        self.addCleanup(set_lang, None)
        for lang, text in (("en", "No instance is running."), ("de", "Es laeuft keine Instanz.")):
            with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(["stop", "--lang", lang, "--data-dir", d]), 0)
            self.assertEqual(out.getvalue().strip(), text)
        self.assertIsNone(errors.get_lang())  # main restores the previous (undetermined) state

    def test_doctor_shows_language(self):
        self.addCleanup(set_lang, None)
        set_lang("en")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(background, "running_pid", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli.Ctx(Config(data_dir=Path(d), language="en"), None, None, None).doctor()
        self.assertIn("Language: en (setting: en)", out.getvalue())
        self.assertNotIn("Sprache", out.getvalue())

    def test_invalid_lang_flag_fails_at_startup(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli.main(["doctor", "--lang", "fr", "--data-dir", d]), 1)
        self.assertIn("'auto', 'de'", err.getvalue())


if __name__ == "__main__":
    unittest.main()

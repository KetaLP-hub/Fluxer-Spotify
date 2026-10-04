"""Writing .env without damaging it, and validating before saving."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fluxer_spotify import settings
from fluxer_spotify.errors import Fatal


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        p = mock.patch.dict(os.environ)
        p.start()
        self.addCleanup(p.stop)
        for k in [k for k in os.environ if k.startswith(("STATUS_", "FLUXER_", "SPOTIFY_", "ROTATE_", "ON_", "POLL_", "NO_ROTATE", "LANGUAGE"))]:
            del os.environ[k]

    def text(self):
        return (self.d / ".env").read_text(encoding="utf-8")


class UpdateEnv(Base):
    def test_creates_the_file_with_the_given_keys(self):
        settings.update_env(self.d, {"ON_IDLE": "lines", "ROTATE_SECONDS": 45})
        self.assertEqual(self.text(), "ON_IDLE=lines\nROTATE_SECONDS=45\n")
        self.assertEqual(settings.read_env(self.d), {"ON_IDLE": "lines", "ROTATE_SECONDS": "45"})

    def test_keeps_comments_order_and_foreign_keys(self):
        (self.d / ".env").write_text("# Kopf\nSPOTIFY_CLIENT_ID=abc\n\n# Reihenfolge\nON_IDLE=clear\nSTATUS_TEMPLATE=🎵 {title} – {artist}\n", encoding="utf-8")
        settings.update_env(self.d, {"ON_IDLE": "lines", "ON_PAUSE": "stats"})
        self.assertEqual(self.text(), "# Kopf\nSPOTIFY_CLIENT_ID=abc\n\n# Reihenfolge\nON_IDLE=lines\nSTATUS_TEMPLATE=🎵 {title} – {artist}\nON_PAUSE=stats\n")

    def test_none_removes_a_key_and_a_commented_example_is_not_a_key(self):
        (self.d / ".env").write_text("#ON_IDLE=clear\nON_IDLE=lines\nROTATE_SECONDS=20\n", encoding="utf-8")
        settings.update_env(self.d, {"ON_IDLE": None})
        self.assertEqual(self.text(), "#ON_IDLE=clear\nROTATE_SECONDS=20\n")
        settings.update_env(self.d, {"ON_IDLE": None, "NICHT_DA": None})  # removing something absent is fine
        self.assertEqual(self.text(), "#ON_IDLE=clear\nROTATE_SECONDS=20\n")

    def test_bom_and_crlf_files_are_read_and_rewritten_cleanly(self):
        (self.d / ".env").write_bytes(b"\xef\xbb\xbfON_IDLE=clear\r\nROTATE_SECONDS=20\r\n")
        settings.update_env(self.d, {"ON_IDLE": "lines"})
        self.assertEqual(self.text(), "ON_IDLE=lines\nROTATE_SECONDS=20\n")

    def test_values_with_line_breaks_are_refused(self):
        with self.assertRaises(ValueError):
            settings.update_env(self.d, {"STATUS_TEMPLATE": "a\nINJIZIERT=1"})
        self.assertFalse((self.d / ".env").exists())

    def test_no_temp_files_are_left_behind(self):
        settings.update_env(self.d, {"ON_IDLE": "lines"})
        self.assertEqual(sorted(p.name for p in self.d.iterdir()), [".env"])


class Validate(Base):
    def test_valid_changes_are_returned_as_config(self):
        cfg = settings.validate(self.d, {"ON_IDLE": "lines", "STATUS_LINES": "now,gh_stars", "STATUS_TTL": "600"})
        self.assertEqual((cfg.on_idle, cfg.lines, cfg.ttl), ("lines", ("now", "gh_stars"), 600.0))

    def test_bad_values_raise_a_readable_error_and_write_nothing(self):
        for key, value in (("ON_IDLE", "immer"), ("STATUS_LINES", "gibtsnicht"), ("ROTATE_SECONDS", "schnell"), ("STATUS_TTL", "-5"), ("ON_PAUSE", "x")):
            with self.assertRaises(Fatal, msg=key):
                settings.apply(self.d, {key: value})
        self.assertFalse((self.d / ".env").exists())

    def test_existing_env_file_is_part_of_the_check(self):
        (self.d / ".env").write_text("ON_IDLE=kaputt\n", encoding="utf-8")
        with self.assertRaises(Fatal):
            settings.validate(self.d, {"ROTATE_SECONDS": "30"})

    def test_removing_a_bad_key_repairs_the_file(self):
        (self.d / ".env").write_text("ON_IDLE=kaputt\n", encoding="utf-8")
        with self.assertRaises(Fatal):
            settings.validate(self.d, {})
        # the changes replace the broken value: the launcher can fix a hand-edited mistake
        cfg = settings.validate(self.d, {"ON_IDLE": "lines"})
        self.assertEqual(cfg.on_idle, "lines")

    def test_a_real_environment_variable_cannot_mask_the_tested_value(self):
        os.environ["ON_IDLE"] = "kaputt"
        cfg = settings.validate(self.d, {"ON_IDLE": "lines"})
        self.assertEqual(cfg.on_idle, "lines")


class Lines(unittest.TestCase):
    def test_default_lines_depend_on_github(self):
        self.assertEqual(settings.default_lines(False), ("now", "playlist", "top_artist", "listening_today"))
        self.assertIn("gh_streak", settings.default_lines(True))
        self.assertNotIn("gh_stars", settings.default_lines(True))

    def test_lines_value_is_none_for_the_default_and_ordered_otherwise(self):
        self.assertIsNone(settings.lines_value(["listening_today", "now", "playlist", "top_artist"], False))
        self.assertEqual(settings.lines_value(["gh_stars", "now"], True), "now,gh_stars")  # program order, not click order
        self.assertIsNone(settings.lines_value(settings.default_lines(True), True))


if __name__ == "__main__":
    unittest.main()

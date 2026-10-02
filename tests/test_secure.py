import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from fluxer_spotify import secure
from fluxer_spotify.store import SECRET_KEYS, Store


class FakeBackend:
    """Reversible stand-in for DPAPI so the sealing logic is tested on every OS."""
    prefix = "fake:"
    name = "Fake"

    def protect(self, data):
        return bytes(b ^ 0x5A for b in data)

    def unprotect(self, blob):
        return bytes(b ^ 0x5A for b in blob)


class BrokenBackend(FakeBackend):
    def protect(self, data):
        raise OSError("boom")

    def unprotect(self, blob):
        raise OSError("wrong user")


class SealedStoreTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.path = Path(self.d.name) / "state.json"

    def tearDown(self):
        self.d.cleanup()

    def raw(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_secrets_are_encrypted_on_disk_and_roundtrip(self):
        s = Store(self.path, backend=FakeBackend())
        s.update(fluxer_token="flx_secret", access="acc_secret", refresh="ref_secret", github_token="gh_secret",
                 client_id="cid", exp=123)
        text = self.path.read_text(encoding="utf-8")
        for secret in ("flx_secret", "acc_secret", "ref_secret", "gh_secret"):
            self.assertNotIn(secret, text)
        raw = self.raw()
        for key in SECRET_KEYS:
            self.assertTrue(raw[key].startswith("fake:"), key)
        self.assertEqual((raw["client_id"], raw["exp"]), ("cid", 123))  # only secrets are sealed
        again = Store(self.path, backend=FakeBackend())
        self.assertEqual((again.get("fluxer_token"), again.get("access"), again.get("refresh"), again.get("github_token")),
                         ("flx_secret", "acc_secret", "ref_secret", "gh_secret"))
        self.assertEqual(again.protection, "Fake")

    def test_in_memory_value_stays_plaintext_after_save(self):
        s = Store(self.path, backend=FakeBackend())
        s.update(fluxer_token="flx_secret")
        self.assertEqual(s.get("fluxer_token"), "flx_secret")
        self.assertEqual(s.fluxer_token(type("C", (), {"fluxer_token": ""})()), ("flx_secret", "login"))

    def test_legacy_plaintext_file_is_upgraded_on_load(self):
        self.path.write_text(json.dumps({"fluxer_token": "old_plain", "refresh": "old_ref", "client_id": "cid"}))
        s = Store(self.path, backend=FakeBackend())
        self.assertEqual((s.get("fluxer_token"), s.get("refresh")), ("old_plain", "old_ref"))
        self.assertNotIn("old_plain", self.path.read_text(encoding="utf-8"))
        self.assertTrue(self.raw()["fluxer_token"].startswith("fake:"))

    def test_already_sealed_file_is_not_rewritten_on_load(self):
        Store(self.path, backend=FakeBackend()).update(fluxer_token="t")
        before = self.path.stat().st_mtime_ns
        Store(self.path, backend=FakeBackend())
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_unreadable_secret_is_dropped_without_crashing(self):
        Store(self.path, backend=FakeBackend()).update(fluxer_token="t", refresh="r", client_id="cid")
        with self.assertLogs("fluxer_spotify.store", level=logging.WARNING) as logs:
            s = Store(self.path, backend=BrokenBackend())  # e.g. another Windows user / machine
        self.assertIsNone(s.get("fluxer_token"))
        self.assertIsNone(s.get("refresh"))
        self.assertEqual(s.get("client_id"), "cid")
        self.assertTrue(any("fluxer_token" in line for line in logs.output))

    def test_damaged_blob_is_dropped(self):
        self.path.write_text(json.dumps({"fluxer_token": "fake:%%%not-base64%%%", "client_id": "cid"}))
        with self.assertLogs("fluxer_spotify.store", level=logging.WARNING):
            s = Store(self.path, backend=FakeBackend())
        self.assertIsNone(s.get("fluxer_token"))
        self.assertEqual(s.get("client_id"), "cid")

    def test_no_backend_keeps_plaintext(self):
        s = Store(self.path, backend=None)
        s.update(fluxer_token="flx_plain")
        self.assertEqual(self.raw()["fluxer_token"], "flx_plain")
        self.assertIsNone(s.protection)

    def test_sealed_file_without_backend_drops_the_secret(self):
        """state.json copied from Windows to Linux/macOS: the blob is unusable, so it counts as logged out."""
        self.path.write_text(json.dumps({"fluxer_token": "dpapi:AAAA", "client_id": "cid"}))
        with self.assertLogs("fluxer_spotify.store", level=logging.WARNING):
            s = Store(self.path, backend=None)
        self.assertIsNone(s.get("fluxer_token"))
        self.assertEqual(s.get("client_id"), "cid")

    def test_backend_failure_on_save_falls_back_to_plaintext_instead_of_losing_the_login(self):
        s = Store(self.path, backend=BrokenBackend())
        with self.assertLogs("fluxer_spotify.store", level=logging.WARNING):
            s.update(fluxer_token="flx_keep")
        self.assertEqual(self.raw()["fluxer_token"], "flx_keep")

    def test_clear_removes_sealed_secret(self):
        s = Store(self.path, backend=FakeBackend())
        s.update(fluxer_token="t", fluxer_user="me")
        s.clear(("fluxer_token", "fluxer_user"))
        self.assertNotIn("fluxer_token", self.raw())

    def test_default_backend_matches_platform(self):
        self.assertEqual(secure.default_backend() is not None, os.name == "nt")


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
class RealDpapiTests(unittest.TestCase):
    def test_roundtrip(self):
        b = secure.Dpapi()
        blob = b.protect(b"flx_token \xc3\xa4")
        self.assertNotIn(b"flx_token", blob)
        self.assertEqual(b.unprotect(blob), b"flx_token \xc3\xa4")

    def test_empty_and_garbage(self):
        b = secure.Dpapi()
        self.assertEqual(b.unprotect(b.protect(b"")), b"")
        with self.assertRaises(OSError):
            b.unprotect(b"definitely not a dpapi blob")

    def test_store_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            Store(path).update(fluxer_token="flx_real", refresh="ref_real")
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("flx_real", text)
            self.assertIn("dpapi:", text)
            self.assertEqual(Store(path).get("fluxer_token"), "flx_real")


if __name__ == "__main__":
    unittest.main()

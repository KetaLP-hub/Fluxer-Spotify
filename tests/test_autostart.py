"""Autostart through the HKCU Run key, against a fake registry (no real registry access)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fluxer_spotify import autostart
from fluxer_spotify.errors import Fatal

EXE = r"C:\Apps\Fluxer-Spotify.exe"
DATA = r"C:\Users\me\AppData\Roaming\spotify-fluxer"


class FakeKey:
    def __init__(self, reg, path):
        self.reg, self.path = reg, path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    """Just enough of winreg: nested keys with string/binary values; missing keys/values raise FileNotFoundError like the real thing."""
    HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_SZ = "HKCU", 1, 2, 1

    def __init__(self):
        self.keys = {}

    def OpenKey(self, root, path, reserved=0, access=0):
        if path not in self.keys:
            raise FileNotFoundError(path)
        return FakeKey(self, path)

    def CreateKeyEx(self, root, path, reserved=0, access=0):
        self.keys.setdefault(path, {})
        return FakeKey(self, path)

    def SetValueEx(self, key, name, reserved, typ, value):
        self.keys[key.path][name] = (value, typ)

    def QueryValueEx(self, key, name):
        try:
            return self.keys[key.path][name]
        except KeyError:
            raise FileNotFoundError(name) from None

    def DeleteValue(self, key, name):
        try:
            del self.keys[key.path][name]
        except KeyError:
            raise FileNotFoundError(name) from None


class AutostartTest(unittest.TestCase):
    def setUp(self):
        self.reg = FakeWinreg()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.startup = Path(self.tmp.name)
        for p in (mock.patch.object(autostart, "_winreg", return_value=self.reg), mock.patch.object(autostart.os, "name", "nt"),
                  mock.patch.object(autostart, "startup_dir", return_value=self.startup)):
            p.start()
            self.addCleanup(p.stop)

    def cmd(self, data=DATA):
        return autostart.command_line(data, frozen=True, executable=EXE)

    def test_install_writes_one_run_value_with_the_exact_command(self):

        with mock.patch.object(autostart, "command_line", return_value=self.cmd()):
            where = autostart.install(DATA)
        self.assertIn(autostart.VALUE, where)
        self.assertEqual(self.reg.keys[autostart.RUN_KEY][autostart.VALUE], (self.cmd(), self.reg.REG_SZ))
        self.assertTrue(autostart.installed())

    def test_command_quotes_paths_with_spaces_and_runs_hidden(self):
        line = autostart.command_line(r"C:\My Data", frozen=True, executable=r"C:\Program Files\FS\Fluxer-Spotify.exe")
        self.assertEqual(line, r'"C:\Program Files\FS\Fluxer-Spotify.exe" run --background --data-dir "C:\My Data"')

    def test_source_run_uses_the_absolute_script_path(self):
        line = autostart.command_line(DATA, frozen=False, executable=r"C:\Python\python.exe")
        self.assertTrue(line.startswith(r"C:\Python\python.exe ") or "pythonw.exe" in line)  # pythonw.exe is preferred when it exists
        self.assertIn("spotify_status.py", line)
        self.assertIn("run --background", line)

    def test_matches_detects_a_moved_exe(self):
        with mock.patch.object(autostart, "command_line", return_value=self.cmd()):
            autostart.install(DATA)
            self.assertTrue(autostart.matches(DATA))
        with mock.patch.object(autostart, "command_line", return_value=r"D:\New\Fluxer-Spotify.exe run --background --data-dir x"):
            self.assertFalse(autostart.matches(DATA))

    def test_uninstall_removes_value_and_reports_it_once(self):
        with mock.patch.object(autostart, "command_line", return_value=self.cmd()):
            autostart.install(DATA)
        self.assertTrue(autostart.uninstall())
        self.assertFalse(autostart.installed())
        self.assertIsNone(autostart.current())
        self.assertIsNone(autostart.uninstall())  # nothing left

    def test_legacy_launchers_are_removed_on_install_and_uninstall(self):
        for name in autostart.LEGACY:
            (self.startup / name).write_text("old")
        (self.startup / "other.lnk").write_text("keep")
        self.assertTrue(autostart.installed())  # an old launcher counts as installed until it is replaced
        with mock.patch.object(autostart, "command_line", return_value=self.cmd()):
            autostart.install(DATA)
        self.assertEqual(sorted(p.name for p in self.startup.iterdir()), ["other.lnk"])
        (self.startup / autostart.LEGACY[0]).write_text("old")
        self.assertTrue(autostart.uninstall())
        self.assertEqual(sorted(p.name for p in self.startup.iterdir()), ["other.lnk"])

    def test_task_manager_switch(self):
        self.assertFalse(autostart.disabled_by_user())
        self.reg.keys[autostart.APPROVED_KEY] = {autostart.VALUE: (bytes([2, 0, 0, 0]) + bytes(8), 3)}
        self.assertFalse(autostart.disabled_by_user())
        self.reg.keys[autostart.APPROVED_KEY] = {autostart.VALUE: (bytes([3, 0, 0, 0]) + bytes(8), 3)}
        self.assertTrue(autostart.disabled_by_user())

    def test_not_windows(self):
        with mock.patch.object(autostart.os, "name", "posix"):
            self.assertFalse(autostart.available())
            self.assertIsNone(autostart.current())
            self.assertFalse(autostart.disabled_by_user())
            with self.assertRaises(Fatal):
                autostart.install(DATA)
            self.assertIsNone(autostart.uninstall())


if __name__ == "__main__":
    unittest.main()

"""state.json: Spotify tokens, Fluxer session token, webhook message id.

Written atomically (temp file + fsync + os.replace) and with mode 0600 where
the OS supports it. The Fluxer *password* is never stored.
"""
import json
import logging
import os
import tempfile
from pathlib import Path

from . import log as _log

log = logging.getLogger("fluxer_spotify.store")
SPOTIFY_KEYS = ("access", "exp", "refresh")
FLUXER_KEYS = ("fluxer_token", "fluxer_token_source", "fluxer_user")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        self._load()
        _log.add_secret(self.data.get("fluxer_token"))
        _log.add_secret(self.data.get("access"))
        _log.add_secret(self.data.get("refresh"))

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
            data.pop("auth", None)  # v1 leftover (token-format guess)
            self.data = data
        except (ValueError, OSError) as e:
            bad = self.path.with_name(self.path.name + ".corrupt")
            log.warning("%s unreadable (%s); moved to %s, starting empty", self.path.name, e, bad.name)
            try:
                os.replace(self.path, bad)
            except OSError:
                pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def update(self, **kw):
        self.data.update(kw)
        for v in kw.values():
            if isinstance(v, str):
                _log.add_secret(v)
        self.save()

    def clear(self, keys):
        for k in keys:
            self.data.pop(k, None)
        self.save()

    def save(self):
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.data))
                f.flush()
                os.fsync(f.fileno())
            if os.name == "posix":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # --- Fluxer token with provenance: only tokens *we* created may be revoked on logout
    def fluxer_token(self, cfg):
        """(token, source): 'manual' = pasted by the user (env/.env/fluxer-token), 'login' = created by fluxer-login."""
        if cfg.fluxer_token:
            return cfg.fluxer_token, "manual"
        t = self.data.get("fluxer_token")
        return (t, self.data.get("fluxer_token_source", "login")) if t else (None, None)

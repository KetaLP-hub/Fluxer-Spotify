"""state.json: Spotify tokens, Fluxer session token, webhook message id.

Written atomically (temp file + fsync + os.replace) and with mode 0600 where
the OS supports it. The Fluxer *password* is never stored. Where the OS offers
a secure backend (Windows DPAPI, see secure.py) the token values are encrypted
inside the file; older plaintext files are upgraded on the next start.
"""
import base64
import json
import logging
import os
import tempfile
from pathlib import Path

from . import log as _log
from . import secure
from .errors import bi, blog

log = logging.getLogger("fluxer_spotify.store")
SPOTIFY_KEYS = ("access", "exp", "refresh")
FLUXER_KEYS = ("fluxer_token", "fluxer_token_source", "fluxer_user")
GITHUB_KEYS = ("github_token", "github_user")
SECRET_KEYS = ("fluxer_token", "access", "refresh", "github_token")  # values that get sealed by a backend
_DEFAULT = object()


class Store:
    def __init__(self, path, backend=_DEFAULT):
        self.path = Path(path)
        self.backend = secure.default_backend() if backend is _DEFAULT else backend
        self.data = {}
        self._legacy_plaintext = False
        self._load()
        for key in SECRET_KEYS:
            _log.add_secret(self.data.get(key))
        if self._legacy_plaintext:  # upgrade an old plaintext file in place
            try:
                self.save()
            except OSError as e:
                log.warning(blog("Konnte state.json nicht verschluesseln (%s)", "Could not encrypt state.json (%s)", e))

    @property
    def protection(self):
        """Name of the backend that encrypts the tokens, or None when they are stored as plaintext."""
        return self.backend.name if self.backend else None

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
            data.pop("auth", None)  # v1 leftover (token-format guess)
            self.data = data
            self._unseal()
        except (ValueError, OSError) as e:
            bad = self.path.with_name(self.path.name + ".corrupt")
            log.warning(blog("%s nicht lesbar (%s); verschoben nach %s, starte leer", "%s unreadable (%s); moved to %s, starting empty", self.path.name, e, bad.name))
            try:
                os.replace(self.path, bad)
            except OSError:
                pass

    def _unseal(self):
        """Decrypt sealed values in place. A value we cannot decrypt (other Windows user/machine, damaged, no backend
        on this OS) is dropped, which just means 'not logged in' for that service."""
        for key in SECRET_KEYS:
            value = self.data.get(key)
            if not isinstance(value, str):
                continue
            prefix = self.backend.prefix if self.backend else secure.Dpapi.prefix
            if value.startswith(prefix):
                try:
                    if not self.backend:
                        raise ValueError("no secure storage on this system")
                    blob = base64.b64decode(value[len(prefix):], validate=True)
                    self.data[key] = self.backend.unprotect(blob).decode("utf-8")
                except Exception as e:  # DPAPI/OS errors, bad base64, bad utf-8: all mean "unusable"
                    del self.data[key]
                    log.warning(blog("Gespeichertes Geheimnis '%s' nicht lesbar (%s); bitte neu anmelden",
                                     "Stored secret '%s' is unreadable (%s); please log in again", key, e))
            elif self.backend:
                self._legacy_plaintext = True

    def _seal(self):
        """Copy of the data with secret values encrypted. If the backend fails, keep plaintext rather than lose the login."""
        out = dict(self.data)
        if not self.backend:
            return out
        for key in SECRET_KEYS:
            value = out.get(key)
            if not isinstance(value, str) or not value:
                continue
            try:
                out[key] = self.backend.prefix + base64.b64encode(self.backend.protect(value.encode("utf-8"))).decode("ascii")
            except Exception as e:
                log.warning(blog("Verschluesseln von '%s' fehlgeschlagen (%s); wird unverschluesselt gespeichert",
                                 "Encrypting '%s' failed (%s); storing it unencrypted", key, e))
        return out

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
                f.write(json.dumps(self._seal()))
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

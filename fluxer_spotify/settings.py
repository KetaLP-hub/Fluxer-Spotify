"""Settings the launcher window can change: read and write the `.env` file in the data folder without touching anything else.

The `.env` file is the same one the README describes (SPOTIFY_CLIENT_ID, FLUXER_WEBHOOK, STATUS_LINES, ...). Writing keeps
comments, order and keys the launcher does not manage, so hand-edited files survive. A change is validated with the very same
`load_config` the program uses at startup *before* it is written, so the launcher can never save a file that stops the program
from starting.
"""
import os
import tempfile
from pathlib import Path

from .config import GH_LINES, DEFAULT_LINES, LINE_NAMES, load_config, parse_dotenv

# Keys the launcher manages (everything else in .env is left alone)
MANAGED = ("STATUS_LINES", "ON_IDLE", "ON_PAUSE", "ROTATE_SECONDS", "STATUS_TTL", "FLUXER_WEBHOOK")
SECRET_KEYS = ("FLUXER_WEBHOOK",)  # shown masked in the UI


def env_path(data_dir):
    return Path(data_dir) / ".env"


def read_env(data_dir):
    p = env_path(data_dir)
    try:
        return parse_dotenv(p.read_text(encoding="utf-8-sig"))
    except OSError:
        return {}


def _render(lines, changes):
    """Apply `changes` (key -> value, None removes the key) to the text lines of an .env file."""
    out, seen = [], set()
    for line in lines:
        key, eq, _ = line.partition("=")
        key = key.strip()
        if eq and key in changes and not line.lstrip().startswith("#"):
            seen.add(key)
            if changes[key] is not None:
                out.append(f"{key}={changes[key]}")
            continue  # None: drop the line
        out.append(line)
    for key, value in changes.items():
        if key not in seen and value is not None:
            out.append(f"{key}={value}")
    return out


def update_env(data_dir, changes):
    """Write `changes` into .env (atomically, owner-only file mode where the OS has one). Values must be single-line."""
    for k, v in changes.items():
        if v is not None and ("\n" in str(v) or "\r" in str(v)):
            raise ValueError(f"{k}: line breaks are not allowed")
    p = env_path(data_dir)
    try:
        existing = p.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        existing = []
    text = "\n".join(_render(existing, {k: (None if v is None else str(v)) for k, v in changes.items()})) + "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".env-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def validate(data_dir, changes, environ=None):
    """Raise errors.Fatal (readable message) if the program could not start with these values; otherwise return the Config."""
    env = dict(os.environ if environ is None else environ)
    env["FLUXER_SPOTIFY_HOME"] = str(data_dir)
    merged = {**read_env(data_dir), **{k: v for k, v in changes.items() if v is not None}}
    for k in changes:
        env.pop(k, None)  # a stale real environment variable must not mask the value being tested
    for k, v in merged.items():
        env[k] = v
    return load_config(None, env)


def apply(data_dir, changes, environ=None):
    """validate(), then update_env(). Returns the validated Config."""
    cfg = validate(data_dir, changes, environ)
    update_env(data_dir, changes)
    return cfg


def default_lines(github_connected):
    """What the program shows when STATUS_LINES is not set."""
    from .config import GH_DEFAULT_LINES
    return tuple(DEFAULT_LINES) + (tuple(GH_DEFAULT_LINES) if github_connected else ())


def lines_value(selected, github_connected):
    """None (= use the program's default, so STATUS_LINES is removed) if `selected` equals the default, else the joined value."""
    ordered = tuple(n for n in LINE_NAMES if n in set(selected))
    return None if ordered == default_lines(github_connected) else ",".join(ordered)


__all__ = ["MANAGED", "SECRET_KEYS", "GH_LINES", "env_path", "read_env", "update_env", "validate", "apply", "default_lines", "lines_value"]

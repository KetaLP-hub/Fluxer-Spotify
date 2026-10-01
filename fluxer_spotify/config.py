"""Configuration. Precedence: CLI flags > real environment > .env file > defaults."""
import logging
import os
import string
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from . import log
from .errors import LANGS, Fatal, bi, detect_lang, blog

DEFAULT_API = "https://api.fluxer.app/v1"
DEFAULT_TEMPLATE = "🎵 {title} – {artist}"
DEFAULT_LINES = ("now", "playlist", "top_artist", "listening_today")
LINE_NAMES = DEFAULT_LINES
LINE_FIELDS = ("title", "artist", "album", "playlist", "top_artist", "hours", "minutes")  # allowed in custom lines
MIN_ROTATE = 15.0  # hard floor: every rotation step is one PATCH to Fluxer
ON_PAUSE_MODES = ("clear", "keep", "stats")
_log = logging.getLogger("fluxer_spotify.config")
ENV_KEYS = {  # attribute -> environment variable
    "client_id": "SPOTIFY_CLIENT_ID", "fluxer_token": "FLUXER_TOKEN", "webhook": "FLUXER_WEBHOOK",
    "api": "FLUXER_API", "template": "STATUS_TEMPLATE", "on_pause": "ON_PAUSE", "interval": "POLL_INTERVAL",
    "lines": "STATUS_LINES", "rotate": "ROTATE_SECONDS", "no_rotate": "NO_ROTATE", "language": "LANGUAGE",
}
LANG_CHOICES = ("auto",) + LANGS


@dataclass
class Config:
    data_dir: Path
    client_id: str = ""
    fluxer_token: str = ""  # only set when the user provides one manually (env/.env/flag)
    webhook: str = ""
    api: str = DEFAULT_API
    template: str = DEFAULT_TEMPLATE
    on_pause: str = "clear"  # "clear", "keep" or "stats"
    interval: float = 5.0
    lines: tuple = DEFAULT_LINES  # names from LINE_NAMES or custom templates, in rotation order
    rotate: float = 30.0
    no_rotate: bool = False
    language: str = ""  # "" = not configured anywhere yet, else "auto" / "de" / "en"

    @property
    def lang(self):
        """Concrete language: the configured one, or the OS UI language for "auto" / not configured."""
        return self.language if self.language in LANGS else detect_lang()

    @property
    def state_file(self):
        return self.data_dir / "state.json"


def parse_dotenv(text):
    out = {}
    for line in text.splitlines():
        k, eq, v = line.partition("=")
        k = k.strip()
        if eq and k and not k.startswith("#"):
            out[k] = v.strip().strip("\"'")
    return out


def parse_lines(value):
    """'now,playlist' or 'now|🎧 {hours} h, ok' (a '|' switches the separator so templates may contain commas)."""
    if isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = str(value).split("|" if "|" in str(value) else ",")
    out = tuple(p.strip() for p in parts if p.strip())
    for p in out:
        if p in LINE_NAMES:
            continue
        if p.replace("_", "").isalpha() and p.islower():
            raise Fatal(bi(f"STATUS_LINES: unbekannte Zeile '{p}'. Erlaubt: {', '.join(LINE_NAMES)} oder ein Text mit {{platzhaltern}}.",
                           f"STATUS_LINES: unknown line '{p}'. Allowed: {', '.join(LINE_NAMES)} or a text with {{placeholders}}."))
        try:
            names = [f for _, f, _, _ in string.Formatter().parse(p) if f is not None]
        except ValueError as e:
            raise Fatal(bi(f"STATUS_LINES: ungueltige Vorlage '{p}' ({e}).", f"STATUS_LINES: invalid template '{p}' ({e}).")) from None
        bad = [n for n in names if n not in LINE_FIELDS]
        if bad:
            raise Fatal(bi(f"STATUS_LINES: unbekannter Platzhalter {bad[0]} in '{p}'. Erlaubt: {' '.join('{'+f+'}' for f in LINE_FIELDS)}",
                           f"STATUS_LINES: unknown placeholder {bad[0]} in '{p}'. Allowed: {' '.join('{'+f+'}' for f in LINE_FIELDS)}"))
    return out or DEFAULT_LINES


def default_data_dir():
    """Source run: the project folder. Frozen exe: a per-user writable folder (never next to the exe, which may sit in Program Files)."""
    if getattr(sys, "frozen", False):
        base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
        return Path(base) / "spotify-fluxer"
    return Path(__file__).resolve().parent.parent


def load_config(args=None, environ=None):
    """`args` is an argparse Namespace (or None); only attributes that are set count."""
    environ = os.environ if environ is None else environ
    get = lambda name: getattr(args, name, None) if args is not None else None
    data_dir = Path(get("data_dir") or environ.get("FLUXER_SPOTIFY_HOME") or default_data_dir())
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise Fatal(bi(f"Datenordner nicht beschreibbar: {data_dir} ({e})", f"Data folder not writable: {data_dir} ({e})"))
    dotenv = {}
    env_file = data_dir / ".env"
    if env_file.exists():
        dotenv = parse_dotenv(env_file.read_text(encoding="utf-8-sig"))
    cfg = Config(data_dir=data_dir)
    for attr, var in ENV_KEYS.items():
        val = get(attr)
        if val in (None, ""):
            val = environ.get(var)
            if attr == "language" and str(val).strip().lower() not in LANG_CHOICES:
                val = None  # POSIX uses LANGUAGE=de_DE:en for something else; only a real value counts from the environment
            val = val or dotenv.get(var)
        if val not in (None, ""):
            setattr(cfg, attr, val)
    cfg.api = cfg.api.rstrip("/")
    cfg.webhook = cfg.webhook.rstrip("/")
    cfg.on_pause = str(cfg.on_pause).lower()
    try:
        cfg.interval = float(cfg.interval)
    except ValueError:
        raise Fatal(bi("POLL_INTERVAL muss eine Zahl sein.", "POLL_INTERVAL must be a number."))
    cfg.interval = max(2.0, cfg.interval)  # be nice to the Spotify API
    if cfg.on_pause not in ON_PAUSE_MODES:
        raise Fatal(bi("ON_PAUSE muss 'clear', 'keep' oder 'stats' sein.", "ON_PAUSE must be 'clear', 'keep' or 'stats'."))
    cfg.language = str(cfg.language).strip().lower()
    if cfg.language and cfg.language not in LANG_CHOICES:
        raise Fatal(bi(f"LANGUAGE/--lang muss 'auto', 'de' oder 'en' sein (nicht '{cfg.language}').",
                       f"LANGUAGE/--lang must be 'auto', 'de' or 'en' (not '{cfg.language}')."))
    cfg.lines = parse_lines(cfg.lines)
    cfg.no_rotate = str(cfg.no_rotate).strip().lower() in ("1", "true", "yes", "on", "j", "ja")
    try:
        cfg.rotate = float(cfg.rotate)
    except ValueError:
        raise Fatal(bi("ROTATE_SECONDS muss eine Zahl sein.", "ROTATE_SECONDS must be a number."))
    if not cfg.rotate >= MIN_ROTATE:  # also catches NaN
        _log.warning(blog("ROTATE_SECONDS=%s ist zu klein, nehme %ss (Fluxer-Rate-Limits).",
                      "ROTATE_SECONDS=%s is too small, using %ss (Fluxer rate limits).", cfg.rotate, MIN_ROTATE))
        cfg.rotate = MIN_ROTATE
    u = urllib.parse.urlparse(cfg.api)
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")):
        raise Fatal(bi(f"FLUXER_API muss https:// nutzen (Passwort/Token wuerden sonst im Klartext gesendet): {cfg.api}",
                       f"FLUXER_API must use https:// (password/token would be sent in clear text): {cfg.api}"))
    log.add_secret(cfg.fluxer_token)
    log.add_secret(cfg.webhook)
    return cfg

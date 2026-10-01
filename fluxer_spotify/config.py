"""Configuration. Precedence: CLI flags > real environment > .env file > defaults."""
import os
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from . import log
from .errors import Fatal, bi

DEFAULT_API = "https://api.fluxer.app/v1"
DEFAULT_TEMPLATE = "🎵 {title} – {artist}"
ENV_KEYS = {  # attribute -> environment variable
    "client_id": "SPOTIFY_CLIENT_ID", "fluxer_token": "FLUXER_TOKEN", "webhook": "FLUXER_WEBHOOK",
    "api": "FLUXER_API", "template": "STATUS_TEMPLATE", "on_pause": "ON_PAUSE", "interval": "POLL_INTERVAL",
}


@dataclass
class Config:
    data_dir: Path
    client_id: str = ""
    fluxer_token: str = ""  # only set when the user provides one manually (env/.env/flag)
    webhook: str = ""
    api: str = DEFAULT_API
    template: str = DEFAULT_TEMPLATE
    on_pause: str = "clear"  # "clear" or "keep"
    interval: float = 5.0

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


def default_data_dir():
    return Path(__file__).resolve().parent.parent


def load_config(args=None, environ=None):
    """`args` is an argparse Namespace (or None); only attributes that are set count."""
    environ = os.environ if environ is None else environ
    get = lambda name: getattr(args, name, None) if args is not None else None
    data_dir = Path(get("data_dir") or environ.get("FLUXER_SPOTIFY_HOME") or default_data_dir())
    dotenv = {}
    env_file = data_dir / ".env"
    if env_file.exists():
        dotenv = parse_dotenv(env_file.read_text(encoding="utf-8-sig"))
    cfg = Config(data_dir=data_dir)
    for attr, var in ENV_KEYS.items():
        val = get(attr)
        if val in (None, ""):
            val = environ.get(var) or dotenv.get(var)
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
    if cfg.on_pause not in ("clear", "keep"):
        raise Fatal(bi("ON_PAUSE muss 'clear' oder 'keep' sein.", "ON_PAUSE must be 'clear' or 'keep'."))
    u = urllib.parse.urlparse(cfg.api)
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")):
        raise Fatal(bi(f"FLUXER_API muss https:// nutzen (Passwort/Token wuerden sonst im Klartext gesendet): {cfg.api}",
                       f"FLUXER_API must use https:// (password/token would be sent in clear text): {cfg.api}"))
    log.add_secret(cfg.fluxer_token)
    log.add_secret(cfg.webhook)
    return cfg

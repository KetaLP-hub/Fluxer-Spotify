"""Logging with secret redaction.

Redaction happens on the *final formatted line* (message + traceback), so it
also catches secrets inside exception texts. Request bodies are never logged.
"""
import logging
import re
import sys

_SECRETS = set()
_PATTERNS = [
    re.compile(r"flx_[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)bearer\s+[\w\-.~+/=]+"),
    re.compile(r"/webhooks/\d+/[\w\-]+"),
    re.compile(r"(?i)(authorization|x-captcha-token)([\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"),
]


def add_secret(value):
    if value and len(value) >= 4:
        _SECRETS.add(value)


def redact(text: str) -> str:
    for s in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(s, "***")
    text = _PATTERNS[3].sub(lambda m: m.group(1) + m.group(2) + "***", text)
    for p in _PATTERNS[:3]:
        text = p.sub("***", text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def make_handler(stream=None, verbose=False):
    h = logging.StreamHandler(stream or sys.stderr)
    fmt = "%(asctime)s %(levelname)-7s %(message)s" if verbose else "%(asctime)s %(message)s"
    h.setFormatter(RedactingFormatter(fmt, "%H:%M:%S"))
    return h


def setup(verbose=False, log_file=None):
    root = logging.getLogger("fluxer_spotify")
    root.handlers.clear()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(make_handler(verbose=verbose))
    if log_file:
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(log_file, maxBytes=512_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(RedactingFormatter("%(asctime)s %(levelname)-7s %(message)s"))
        root.addHandler(fh)
    root.propagate = False
    return root

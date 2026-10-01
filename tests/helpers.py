"""Shared test helpers: a scripted fake transport and a real-ish ALTCHA challenge."""
import hashlib
import json

from fluxer_spotify.http import Http, NetworkError, Response


class FakeTransport:
    """Pops scripted responses per call. Items: (status, body_dict_or_bytes[, headers]) or an Exception."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []  # (method, url, headers, parsed_json_body)

    def __call__(self, method, url, headers, body, timeout):
        parsed = None
        if body:
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = body.decode()
        self.calls.append((method, url, dict(headers), parsed))
        if not self.script:
            raise AssertionError(f"unexpected request {method} {url}")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        status, payload, *rest = item
        raw = payload if isinstance(payload, bytes) else (json.dumps(payload).encode() if payload is not None else b"")
        return Response(status, {k.lower(): v for k, v in (rest[0] if rest else {}).items()}, raw)


def make_http(*script, sleeps=None):
    t = FakeTransport(*script)
    sl = [] if sleeps is None else sleeps
    return Http(transport=t, sleep=sl.append, rand=lambda: 0.0), t, sl


def altcha_challenge(cost=10, counter=7, prefix_bytes=1):
    """Build a challenge the way altcha-lib v2 does (unsigned: signature is opaque to the solver)."""
    nonce, salt = bytes(range(16)), bytes(range(16, 32))
    key = hashlib.pbkdf2_hmac("sha256", nonce + counter.to_bytes(4, "big"), salt, cost, 32)
    return {"parameters": {"algorithm": "PBKDF2/SHA-256", "nonce": nonce.hex(), "salt": salt.hex(), "cost": cost,
                           "keyLength": 32, "keyPrefix": key[:prefix_bytes].hex(), "keySignature": "ab",
                           "expiresAt": 4102444800}, "signature": "cd" * 8}


CAPTCHA_ERR = lambda: (400, {"code": "CAPTCHA_REQUIRED", "message": "x", "captcha_provider": "altcha",
                             "altcha_challenge": altcha_challenge()})

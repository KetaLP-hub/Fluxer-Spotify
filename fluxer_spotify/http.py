"""Tiny HTTP layer: JSON in/out, retries with backoff, Retry-After, injectable transport."""
import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

from .errors import bi, blog

log = logging.getLogger("fluxer_spotify.http")
MAX_WAIT = 120.0


class Response(NamedTuple):
    status: int
    headers: dict
    body: bytes


class NetworkError(Exception):
    pass


class HttpError(Exception):
    def __init__(self, status, body, headers=None, url=""):
        self.status, self.body, self.headers = status, body, headers or {}
        self.url = url
        super().__init__(f"HTTP {status} {self.code or ''}".strip())

    @property
    def code(self):
        """Fluxer error code (e.g. CAPTCHA_REQUIRED) or Spotify's `error` string."""
        if isinstance(self.body, dict):
            c = self.body.get("code") or self.body.get("error")
            return c if isinstance(c, str) else None
        return None

    def field(self, key):
        """Extra data of an error body. Looked up top-level, then in common wrappers."""
        if not isinstance(self.body, dict):
            return None
        for src in (self.body, self.body.get("data"), self.body.get("context")):
            if isinstance(src, dict) and key in src:
                return src[key]
        return None


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to the same scheme and host.

    urllib keeps every request header on a redirect, including `Authorization`: a redirect to another host would hand over the
    Spotify/GitHub/Fluxer token. None of the APIs we call needs such a redirect, so anything else is simply not followed
    (the 3xx then surfaces as an HttpError).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)  # a relative Location resolves against the request URL
        old, new = urllib.parse.urlparse(req.full_url), urllib.parse.urlparse(target)
        if (old.scheme, old.netloc.lower()) != (new.scheme, new.netloc.lower()):
            return None
        return super().redirect_request(req, fp, code, msg, headers, target)


_opener = urllib.request.build_opener(_SameOriginRedirect)


def default_transport(method, url, headers, body, timeout):
    req = urllib.request.Request(url, body, headers, method=method)
    try:
        with _opener.open(req, timeout=timeout) as r:
            return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
    except urllib.error.HTTPError as e:
        return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetworkError(str(getattr(e, "reason", e))) from None


def _loc(url):  # host + path only: no query, and the redaction filter masks webhook tokens
    p = urllib.parse.urlparse(url)
    return p.netloc + p.path


class Http:
    def __init__(self, transport=default_transport, sleep=time.sleep, rand=random.random,
                 user_agent="spotify-fluxer/2.0", timeout=15, retries=3):
        self.transport, self.sleep, self.rand = transport, sleep, rand
        self.user_agent, self.timeout, self.retries = user_agent, timeout, retries

    @staticmethod
    def retry_delay(resp, attempt, rand=random.random):
        """Server hint (Retry-After / retry_after) wins, else exponential backoff + jitter."""
        hint = resp.headers.get("retry-after") if resp else None
        if hint is None and resp:
            try:
                hint = json.loads(resp.body).get("retry_after")
            except Exception:
                pass
        try:
            return min(MAX_WAIT, max(0.0, float(hint)))
        except (TypeError, ValueError):
            return min(MAX_WAIT, 2 ** attempt + rand())

    def request(self, method, url, *, headers=None, json_body=None, form=None, retries=None):
        h = {"User-Agent": self.user_agent, **(headers or {})}
        data = None
        if json_body is not None:
            data, h["Content-Type"] = json.dumps(json_body).encode(), "application/json"
        elif form is not None:
            data, h["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
        tries = self.retries if retries is None else retries
        for attempt in range(tries + 1):
            try:
                resp = self.transport(method, url, h, data, self.timeout)
            except NetworkError as e:
                if attempt >= tries:
                    raise
                delay = self.retry_delay(None, attempt, self.rand)
                log.warning(blog("%s %s: Netzwerkfehler (%s), neuer Versuch in %.0f s", "%s %s: network error (%s), retry in %.0fs", method, _loc(url), e, delay))
                self.sleep(delay)
                continue
            log.debug("%s %s -> %s", method, _loc(url), resp.status)
            if resp.status < 300:
                return json.loads(resp.body) if resp.body.strip() else {}
            try:
                body = json.loads(resp.body)
            except ValueError:
                body = resp.body[:200].decode("utf-8", "replace")
            if (resp.status == 429 or resp.status >= 500) and attempt < tries:
                delay = self.retry_delay(resp, attempt, self.rand)
                log.warning(blog("%s %s: HTTP %s, neuer Versuch in %.0f s", "%s %s: HTTP %s, retry in %.0fs", method, _loc(url), resp.status, delay))
                self.sleep(delay)
                continue
            raise HttpError(resp.status, body, resp.headers, _loc(url))

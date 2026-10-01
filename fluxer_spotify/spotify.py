"""Spotify: PKCE login, token refresh, now-playing snapshot, text/embed formatting."""
import base64
import hashlib
import http.server
import logging
import secrets
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Any, Optional

from .config import DEFAULT_TEMPLATE
from .errors import AuthError, Fatal, bi, tr, blog
from .http import HttpError

log = logging.getLogger("fluxer_spotify.spotify")
REDIRECT_HOST, REDIRECT_PORT = "127.0.0.1", 8888
REDIRECT = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"  # must match the Spotify dashboard exactly
SCOPES = "user-read-playback-state user-read-recently-played user-top-read"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
MAX_STATUS = 128  # Fluxer custom status limit


# ---------------------------------------------------------------- pure formatting helpers
def mmss(ms):
    return f"{ms // 60000}:{ms // 1000 % 60:02d}"


def bar(p, d, n=14):
    filled = round(n * p / d) if d else 0
    return "▰" * filled + "▱" * (n - filled)


def who(t):
    return ", ".join(a["name"] for a in t.get("artists", [])) or t.get("show", {}).get("name", "")


def lines(xs):
    return "\n".join(xs)[:1000] or "-"


class _Safe(dict):
    def __missing__(self, key):
        raise KeyError(key)


def truncate(text, limit=MAX_STATUS):
    """Cut to the limit with an ellipsis. Only the end is cut, so a leading emoji survives; a dangling ZWJ is dropped."""
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip().rstrip("‍") + "…"


def status_text(item, template):
    """Render the status template for a track/episode. Never raises on a bad template."""
    alb = item.get("album") or item.get("show") or {}
    fields = _Safe(title=item.get("name", ""), artist=who(item), album=alb.get("name", ""))
    try:
        text = template.format_map(fields)
    except (KeyError, IndexError, ValueError) as e:
        log.warning(blog("Ungueltiges STATUS_TEMPLATE (%s); nehme den Standard. Erlaubt: {title} {artist} {album}", "Bad STATUS_TEMPLATE (%s); using the default. Allowed: {title} {artist} {album}", e))
        text = DEFAULT_TEMPLATE.format_map(fields)
    return truncate(" ".join(text.split())) or None


@dataclass
class Snapshot:
    key: Any  # changes whenever something worth re-publishing changes
    playing: bool
    item: Optional[dict]
    embed: dict
    context: Optional[dict] = None  # Spotify playback context {type, uri} (playlist/album/...), if any


# ---------------------------------------------------------------- client
class SpotifyClient:
    def __init__(self, http, store, client_id, clock=time.time):
        self.http, self.store, self.client_id, self.clock = http, store, client_id, clock
        self._slow = {"track": None, "top": 0.0}  # queue/recent only on track change, tops hourly

    # --- tokens
    def _token_request(self, **params):
        try:
            t = self.http.request("POST", TOKEN_URL, form={"client_id": self.client_id, **params})
        except HttpError as e:
            if e.status in (400, 401) and e.code in ("invalid_grant", "invalid_client", "invalid_request"):
                raise AuthError(bi("Spotify-Anmeldung ungueltig oder abgelaufen. Bitte neu anmelden: login",
                                   "Spotify login invalid or expired. Please log in again: login")) from None
            raise
        self.store.update(access=t["access_token"], exp=self.clock() + t["expires_in"],
                          refresh=t.get("refresh_token", self.store.get("refresh")))

    def refresh(self):
        if not self.store.get("refresh"):
            raise AuthError(bi("Noch nicht bei Spotify angemeldet. Erst ausfuehren: login",
                               "Not logged in to Spotify yet. Run first: login"))
        self._token_request(grant_type="refresh_token", refresh_token=self.store.get("refresh"))

    def login(self, open_browser=webbrowser.open, timeout=180, notify=print):
        ver = secrets.token_urlsafe(64)
        state = secrets.token_urlsafe(16)
        chal = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).rstrip(b"=").decode()
        got = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                if u.path != "/callback":  # favicon etc.
                    self.send_response(404); self.end_headers()
                    return
                got.update(urllib.parse.parse_qsl(u.query))
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(bi("Fertig, Fenster kann zu.", "Done, you can close this window.", " / ").encode())

            log_message = lambda *a: None

        srv = http.server.HTTPServer((REDIRECT_HOST, REDIRECT_PORT), H)
        srv.timeout = 1
        url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
            "code_challenge_method": "S256", "code_challenge": chal, "state": state})
        notify(bi(f"Browser oeffnet sich... (Redirect URI: {REDIRECT})", f"Opening browser... (Redirect URI: {REDIRECT})", " / "))
        open_browser(url)
        deadline = time.monotonic() + timeout
        try:
            while not got and time.monotonic() < deadline:
                srv.handle_request()
        finally:
            srv.server_close()
        if got.get("state") != state and "code" in got:
            raise Fatal(bi("Spotify-Antwort hatte einen falschen 'state' (abgebrochen).", "Spotify response had a wrong 'state' (aborted)."))
        if "code" not in got:
            err = got.get("error", "timeout")
            raise Fatal(bi(f"Spotify hat keinen Code geliefert ({err}). Redirect-URI im Dashboard exakt {REDIRECT} eintragen "
                           "und nochmal versuchen.",
                           f"Spotify returned no code ({err}). Add the redirect URI {REDIRECT} exactly in the dashboard and retry."))
        self._token_request(grant_type="authorization_code", code=got["code"], redirect_uri=REDIRECT, code_verifier=ver)

    # --- API
    def get(self, path, retries=None):
        if self.clock() > self.store.get("exp", 0) - 60:
            self.refresh()
        for attempt in (0, 1):
            try:
                return self.http.request("GET", API + path, headers={"Authorization": "Bearer " + self.store.get("access", "")},
                                         retries=retries)
            except HttpError as e:
                if e.status == 401 and attempt == 0:
                    log.info(bi("Spotify 401: Access-Token wird erneuert", "Spotify 401: refreshing the access token", " / "))
                    self.refresh()
                    continue
                if e.status == 401:
                    raise AuthError(bi("Spotify lehnt den Zugang ab (401). Bitte neu anmelden: login",
                                       "Spotify rejected access (401). Please log in again: login")) from None
                raise

    def snapshot(self, full=False):
        """`full=True` additionally fetches queue/recent/top (only needed for the webhook card)."""
        pb = self.get("/me/player?additional_types=track,episode")
        it = pb.get("item") if pb else None
        if not it:
            return Snapshot("idle", False, None,
                            {"title": "Spotify", "description": tr("Gerade nichts am Laufen", "Nothing playing right now"), "color": 0x535353})
        playing = bool(pb.get("is_playing"))
        dev = pb.get("device", {})
        key = (it["id"], playing, dev.get("name"), pb.get("shuffle_state"), pb.get("repeat_state"))
        return Snapshot(key, playing, it, self._embed(pb, it, playing, dev) if full else {}, pb.get("context"))

    def _embed(self, pb, it, playing, dev):
        s = self._slow
        if s["track"] != it["id"]:
            s["track"] = it["id"]
            q = self.get("/me/player/queue").get("queue", [])
            s["next"] = f"{q[0]['name']} – {who(q[0])}" if q else "-"
            rec = self.get("/me/player/recently-played?limit=5")["items"]
            s["recent"] = [f"{r['track']['name']} – {who(r['track'])}" for r in rec if r["track"]["id"] != it["id"]][:3]
        if self.clock() - s["top"] > 3600:
            s["top"] = self.clock()
            s["ta"] = [f"{i}. {a['name']}" for i, a in enumerate(self.get("/me/top/artists?time_range=short_term&limit=5")["items"], 1)]
            s["tt"] = [f"{i}. {t['name']} – {who(t)}" for i, t in enumerate(self.get("/me/top/tracks?time_range=short_term&limit=5")["items"], 1)]
        alb = it.get("album") or it.get("show") or {}
        foot = [dev.get("name", "?"), f"🔊 {dev.get('volume_percent', '?')}%"]
        if pb.get("shuffle_state"): foot.append("🔀")
        if pb.get("repeat_state") != "off": foot.append("🔁" if pb["repeat_state"] == "context" else "🔂")
        if "popularity" in it: foot.append(f"★ {it['popularity']}")
        if it.get("explicit"): foot.append("E")
        if alb.get("release_date"): foot.append(alb["release_date"][:4])
        e = {
            "title": it["name"][:256], "url": it.get("external_urls", {}).get("spotify"),
            "description": f"{who(it)} · {alb.get('name', '')}\n{'▶' if playing else '⏸'} "
                           f"{bar(pb['progress_ms'], it['duration_ms'])} {mmss(pb['progress_ms'])}/{mmss(it['duration_ms'])}",
            "color": 0x1DB954 if playing else 0x535353,
            "fields": [
                {"name": tr("⏭ Als Nächstes", "⏭ Up next"), "value": s["next"], "inline": True},
                {"name": tr("🕘 Zuletzt", "🕘 Recently"), "value": lines(s["recent"]), "inline": True},
                {"name": tr("🏆 Top Artists (4 Wo.)", "🏆 Top artists (4 wks)"), "value": lines(s["ta"]), "inline": True},
                {"name": tr("🔥 Top Tracks (4 Wo.)", "🔥 Top tracks (4 wks)"), "value": lines(s["tt"]), "inline": True},
            ],
            "footer": {"text": " · ".join(foot)},
        }
        if alb.get("images"): e["thumbnail"] = {"url": alb["images"][0]["url"]}
        return e

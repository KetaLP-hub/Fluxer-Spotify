"""Status lines: turn a playback snapshot into the candidate texts the runner rotates through.

Every line is a template. Placeholders are resolved lazily (and cached with a TTL), so a line whose data is
missing (podcast without playlist, API error, nothing played today) is simply unavailable and never renders
with an empty gap. Spotify is only asked for what the active lines need.
"""
import logging
from datetime import datetime

from .errors import bi, tr, blog
from .http import HttpError, NetworkError
from .spotify import status_text, truncate, who

log = logging.getLogger("fluxer_spotify.lines")
STATS = ("top_artist", "listening_today")  # lines that do not depend on the current track


def default_template(name, hours=0, minutes=0):
    """Default text of a built-in line in the selected language; 'listening_today' drops a zero part ("25 min", "2 h")."""
    if name == "playlist":
        return tr('💿 aus "{playlist}"', '💿 from "{playlist}"')
    if name == "top_artist":
        return tr("🏆 Top-Artist diese Woche: {top_artist}", "🏆 Top artist this week: {top_artist}")
    if name == "listening_today":
        part = " ".join(p for p in (f"{hours} h" if hours else "", f"{minutes} min" if minutes else "") if p)
        return tr(f"🎧 heute {part} gehört", f"🎧 {part} listened today")
    return name


TTL_NAME, TTL_TOP, TTL_TODAY = 3600, 3600, 300  # seconds
ERR_TTL = (30, 3600)  # clamp for "try again later" after a failed lookup (Retry-After wins inside this range)


def listened_seconds(items, day_start):
    """Seconds listened at/after `day_start` (epoch) from recently-played `items` (newest first).

    `played_at` is when a play ended, so a play lasted at most until the previous one ended: that gap caps a
    skipped track at the time it actually ran. The API returns 50 plays at most, so this is a lower bound.
    """
    plays = []
    for it in items:
        try:
            end = datetime.fromisoformat(it["played_at"].replace("Z", "+00:00")).timestamp()
            plays.append((end, it["track"]["duration_ms"] / 1000))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    plays.sort(reverse=True)
    total = 0.0
    for i, (end, dur) in enumerate(plays):
        if end < day_start:
            break
        total += min(dur, end - plays[i + 1][0]) if i + 1 < len(plays) else dur
    return total


def local_midnight(now):
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class _Fields(dict):
    """format_map source: computes a placeholder on first use; unavailable (None/"") -> KeyError."""

    def __init__(self, providers):
        super().__init__()
        self.providers = providers

    def __missing__(self, key):
        val = self.providers[key]()
        if val is None or val == "":
            raise KeyError(key)
        self[key] = val
        return val


class Lines:
    def __init__(self, cfg, spotify, clock):
        self.cfg, self.sp, self.clock = cfg, spotify, clock
        self.cache = {}  # key -> (value, expires_at)

    # --- caching: failures are cached too (short), so a broken endpoint is not hammered every poll
    def _cached(self, key, ttl, fetch):
        now = self.clock()
        hit = self.cache.get(key)
        if hit and now < hit[1]:
            return hit[0]
        try:
            val = fetch()
        except (HttpError, NetworkError) as e:
            try:
                wait = float(e.headers.get("retry-after"))
            except (AttributeError, TypeError, ValueError):
                wait = 120
            wait = min(ERR_TTL[1], max(ERR_TTL[0], wait))
            log.info(blog("Abfrage %s fehlgeschlagen (%s), neuer Versuch in %.0f s", "Lookup %s failed (%s), retry in %.0fs", key[0], e, wait))
            val, ttl = None, wait
        self.cache[key] = (val, now + ttl)
        return val

    # --- data
    def _playlist(self, snap):
        ctx = snap.context or {}
        parts = str(ctx.get("uri", "")).split(":")
        kind, cid = (parts[-2], parts[-1]) if len(parts) >= 3 else (None, None)
        album = (snap.item.get("album") or {}).get("name") or None
        if kind == "album":
            return album  # the context is the album itself: no request needed
        if kind != "playlist":
            return None  # show, artist, liked songs, no context ...

        def fetch():
            try:
                return self.sp.get(f"/playlists/{cid}?fields=name", retries=0).get("name")
            except HttpError as e:
                if e.status in (403, 404):  # private / algorithmic / deleted: cache "no name", use the album
                    return None
                raise
        return self._cached(("playlist", cid), TTL_NAME, fetch) or album  # album is per track: never cached

    def _top_artist(self):
        def fetch():
            items = self.sp.get("/me/top/artists?time_range=short_term&limit=1", retries=0).get("items") or []
            return items[0]["name"] if items else None
        return self._cached(("top",), TTL_TOP, fetch)

    def _today(self):
        start = local_midnight(self.clock())  # in the key: a new local day never reuses yesterday's total

        def fetch():
            items = self.sp.get("/me/player/recently-played?limit=50", retries=0).get("items") or []
            minutes = int(listened_seconds(items, start) // 60)
            return divmod(minutes, 60) if minutes else None
        return self._cached(("today", start), TTL_TODAY, fetch)

    # --- rendering
    def render(self, name, snap):
        """Text for one configured line, or None if it is unavailable right now."""
        item = snap.item
        if name == "now":
            return status_text(item, self.cfg.template)
        alb = item.get("album") or item.get("show") or {}
        today = lambda i: (lambda: (self._today() or (None, None))[i])
        fields = _Fields({
            "title": lambda: item.get("name"), "artist": lambda: who(item), "album": lambda: alb.get("name"),
            "playlist": lambda: self._playlist(snap), "top_artist": self._top_artist,
            "hours": today(0), "minutes": today(1)})
        try:
            tpl = name
            if name == "listening_today":
                h, m = self._today() or (None, None)
                tpl = default_template(name, h, m) if h is not None else None  # no data: unavailable
            elif name in ("playlist", "top_artist"):
                tpl = default_template(name)
            text = tpl.format_map(fields) if tpl else None
        except (KeyError, IndexError, ValueError):
            return None
        return truncate(" ".join(text.split())) if text else None

    def available(self, snap, names, first_only=False):
        """[(name, text)] for the lines that have data; stops at the first one if `first_only` (no API calls for the rest)."""
        out = []
        for name in names:
            text = self.render(name, snap)
            if text:
                out.append((name, text))
                if first_only:
                    break
        return out

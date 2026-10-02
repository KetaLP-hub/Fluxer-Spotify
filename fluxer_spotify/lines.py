"""Status lines: turn a playback snapshot into the candidate texts the runner rotates through.

Every line is a template. Placeholders are resolved lazily (and cached with a TTL), so a line whose data is
missing (podcast without playlist, API error, nothing played today) is simply unavailable and never renders
with an empty gap. Spotify is only asked for what the active lines need.
"""
import logging
from datetime import datetime

from .config import GH_LINES, TRACK_LINES
from .errors import AuthError, bi, tr, blog
from .http import HttpError, NetworkError
from .spotify import status_text, truncate, who

log = logging.getLogger("fluxer_spotify.lines")
STATS = ("top_artist", "listening_today") + GH_LINES  # lines that do not depend on the current track
GH_KEY = {"gh_push": "repo", "gh_commits": "commits", "gh_prs": "prs", "gh_reviews": "reviews", "gh_issues": "issues",
          "gh_streak": "streak", "gh_stars": "stars", "gh_followers": "followers"}  # line name -> key in GitHubClient.stats()


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


def gh_template(name, n):
    """Default text of a GitHub line in the selected language; `n` picks singular or plural. The placeholder is filled in later."""
    one = n == 1
    if name == "gh_push":
        return tr("💻 zuletzt gepusht: {gh_repo} ({gh_ago})", "💻 last push: {gh_repo} ({gh_ago})")
    if name == "gh_commits":
        return tr("💻 heute {gh_commits} " + ("Beitrag" if one else "Beiträge") + " auf GitHub",
                  "💻 {gh_commits} contribution" + ("" if one else "s") + " on GitHub today")
    if name == "gh_prs":
        return tr("🔀 {gh_prs} " + ("offener" if one else "offene") + " Pull Request" + ("" if one else "s"),
                  "🔀 {gh_prs} open pull request" + ("" if one else "s"))
    if name == "gh_reviews":
        return tr("👀 {gh_reviews} Review" + ("" if one else "s") + " angefragt", "👀 {gh_reviews} review" + ("" if one else "s") + " requested")
    if name == "gh_issues":
        return tr("📌 {gh_issues} Issue" + ("" if one else "s") + " zugewiesen", "📌 {gh_issues} issue" + ("" if one else "s") + " assigned")
    if name == "gh_streak":
        return tr("🔥 {gh_streak} Tage in Folge aktiv", "🔥 {gh_streak}-day streak on GitHub")
    if name == "gh_stars":
        return tr("⭐ {gh_stars} " + ("Stern" if one else "Sterne") + " auf GitHub", "⭐ {gh_stars} star" + ("" if one else "s") + " on GitHub")
    if name == "gh_followers":
        return tr("👥 {gh_followers} Follower", "👥 {gh_followers} follower" + ("" if one else "s"))
    return name


def ago(seconds):
    s = max(0, int(seconds))
    if s < 60:
        return tr("gerade eben", "just now")
    m = s // 60
    if m < 60:
        return tr(f"vor {m} min", f"{m} min ago")
    h = m // 60
    if h < 24:
        return tr(f"vor {h} h", f"{h} h ago")
    d = h // 24
    return tr(f"vor {d} Tag" + ("" if d == 1 else "en"), f"{d} day" + ("" if d == 1 else "s") + " ago")


TTL_NAME, TTL_TOP, TTL_TODAY, TTL_GH = 3600, 3600, 300, 300  # seconds
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
    def __init__(self, cfg, spotify, clock, github=None):
        self.cfg, self.sp, self.clock, self.gh = cfg, spotify, clock, github
        self.cache = {}  # key -> (value, expires_at)

    # --- caching: failures are cached too (short), so a broken endpoint is not hammered every poll
    def _cached(self, key, ttl, fetch):
        now = self.clock()
        hit = self.cache.get(key)
        if hit and now < hit[1]:
            return hit[0]
        try:
            val = fetch()
        except AuthError as e:  # e.g. a revoked GitHub token: never stop the music status for it, just stay quiet for a while
            log.warning("%s", str(e).replace("\n", " / "))
            val, ttl = None, ERR_TTL[1]
        except (HttpError, NetworkError) as e:
            headers = getattr(e, "headers", None) or {}
            try:
                wait = float(headers.get("retry-after"))
            except (AttributeError, TypeError, ValueError):
                try:  # GitHub primary rate limit: wait until the window resets
                    wait = float(headers["x-ratelimit-reset"]) - now if headers.get("x-ratelimit-remaining") == "0" else 120
                except (KeyError, TypeError, ValueError):
                    wait = 120
            wait = min(ERR_TTL[1], max(ERR_TTL[0], wait))
            log.info(blog("Abfrage %s fehlgeschlagen (%s), neuer Versuch in %.0f s", "Lookup %s failed (%s), retry in %.0fs", key[0], e, wait))
            val, ttl = None, wait
        self.cache[key] = (val, now + ttl)
        return val

    # --- data
    def _gh_data(self):
        return self._cached(("github",), TTL_GH, self.gh.stats) if self.gh else None

    def _gh_value(self, key, hide_zero):
        """One GitHub number/text, or None when unavailable. Built-in lines pass hide_zero: '0 open pull requests' is noise."""
        data = self._gh_data()
        if not data:
            return None
        if key == "ago":
            return ago(self.clock() - data["pushed_at"]) if data.get("pushed_at") else None
        value = data.get(key)
        if hide_zero and value is not None and not isinstance(value, str) and value < (2 if key == "streak" else 1):
            return None
        return value

    def _playlist(self, snap):
        if snap.item is None:
            return None
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
        if item is None and name in TRACK_LINES:
            return None  # nothing plays: only the lines that need no track can be shown
        if name == "now":
            return status_text(item, self.cfg.template)
        item = item or {}
        alb = item.get("album") or item.get("show") or {}
        today = lambda i: (lambda: (self._today() or (None, None))[i])
        hide = name in GH_LINES
        gh = lambda key: (lambda: self._gh_value(key, hide))
        fields = _Fields({
            "title": lambda: item.get("name"), "artist": lambda: who(item), "album": lambda: alb.get("name"),
            "playlist": lambda: self._playlist(snap), "top_artist": self._top_artist,
            "hours": today(0), "minutes": today(1),
            "gh_repo": gh("repo"), "gh_ago": gh("ago"), "gh_commits": gh("commits"), "gh_prs": gh("prs"),
            "gh_reviews": gh("reviews"), "gh_issues": gh("issues"), "gh_streak": gh("streak"),
            "gh_stars": gh("stars"), "gh_followers": gh("followers")})
        try:
            tpl = name
            if name == "listening_today":
                h, m = self._today() or (None, None)
                tpl = default_template(name, h, m) if h is not None else None  # no data: unavailable
            elif name in ("playlist", "top_artist"):
                tpl = default_template(name)
            elif name in GH_LINES:
                tpl = gh_template(name, (self._gh_data() or {}).get(GH_KEY[name]) or 0)
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

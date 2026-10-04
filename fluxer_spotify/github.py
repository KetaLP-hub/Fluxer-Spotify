"""GitHub: everything the `gh_*` status lines need, read-only, from one GraphQL request (token login).

The query was validated against GitHub's public GraphQL schema. Privacy: the repository shown in `gh_push` is limited
to PUBLIC repositories (a private repo name must never end up in a public status); everything else is only a number.
"""
import logging
import time
import urllib.parse
from datetime import datetime, timezone

from .errors import AuthError, Fatal, bi
from .http import HttpError, NetworkError
from .store import GITHUB_KEYS

log = logging.getLogger("fluxer_spotify.github")
API = "https://api.github.com"
GRAPHQL = API + "/graphql"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
TOKEN_PAGE = "https://github.com/settings/personal-access-tokens/new"
TOKEN_REVOKE_PAGE = "https://github.com/settings/personal-access-tokens"


def token_page_url():
    """GitHub's fine-grained token page with name, lifetime and the only two permissions we need (read) already filled in.

    GitHub documents these URL parameters. The user still reviews the page and clicks "Generate token" himself.
    "Repository access" stays on GitHub's default (public repositories); choosing "All repositories" there adds the counts of private repos.
    """
    return TOKEN_PAGE + "?" + urllib.parse.urlencode({
        "name": "Fluxer-Spotify", "description": "Read-only: GitHub lines in the Fluxer status",
        "expires_in": "365", "pull_requests": "read", "issues": "read"})
QUERY = """
query {
  viewer {
    login
    followers { totalCount }
    starred: repositories(first: 100, ownerAffiliations: OWNER, isFork: false, orderBy: {field: STARGAZERS, direction: DESC}) {
      nodes { stargazerCount }
    }
    pushed: repositories(first: 1, privacy: PUBLIC, ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER], orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes { nameWithOwner pushedAt }
    }
    contributionsCollection {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
  prs: search(query: "is:pr is:open author:@me archived:false", type: ISSUE) { issueCount }
  reviews: search(query: "is:pr is:open review-requested:@me archived:false", type: ISSUE) { issueCount }
  issues: search(query: "is:issue is:open assignee:@me archived:false", type: ISSUE) { issueCount }
}
"""


def rejected():
    return AuthError(bi("GitHub-Token ungueltig, abgelaufen oder widerrufen. Bitte neu anmelden: github-login",
                        "GitHub token invalid, expired or revoked. Please log in again: github-login"))


def _num(obj, *path):
    for key in path:
        obj = obj.get(key) if isinstance(obj, dict) else None
    return obj if isinstance(obj, int) and not isinstance(obj, bool) else None


def parse_epoch(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def latest_date(now):
    """The latest calendar date it can be anywhere on Earth right now (local or UTC), as YYYY-MM-DD."""
    return max(datetime.fromtimestamp(now).date(), datetime.fromtimestamp(now, timezone.utc).date()).isoformat()


def activity(weeks, until=None):
    """(contributions today, streak in days) from GitHub's contribution calendar.

    'Today' is the calendar's last day up to `until` (so zero-filled future days, should the API send any, are ignored
    and a timezone difference cannot shift it). A day without contributions yet does not break the streak until it is over.
    """
    days = []
    for week in weeks or []:
        for day in (week or {}).get("contributionDays") or []:
            count = _num(day, "contributionCount")
            if count is not None and isinstance(day.get("date"), str) and (until is None or day["date"] <= until):
                days.append((day["date"], count))
    days.sort()
    if not days:
        return None, None
    today = days[-1][1]
    streak = 0
    for _, count in reversed(days[:-1] if today == 0 else days):
        if count <= 0:
            break
        streak += 1
    return today, streak


def parse_stats(data, until=None):
    """The wanted numbers from a GraphQL `data` object. Anything missing stays None (that line is then unavailable)."""
    viewer = (data or {}).get("viewer") or {}
    pushed = ((viewer.get("pushed") or {}).get("nodes") or [None])[0] or {}
    stars = [_num(n, "stargazerCount") for n in (viewer.get("starred") or {}).get("nodes") or []]
    today, streak = activity((((viewer.get("contributionsCollection") or {}).get("contributionCalendar") or {}).get("weeks")), until)
    return {
        "repo": pushed.get("nameWithOwner") or None, "pushed_at": parse_epoch(pushed.get("pushedAt")),
        "commits": today, "streak": streak,
        "prs": _num(data, "prs", "issueCount"), "reviews": _num(data, "reviews", "issueCount"),
        "issues": _num(data, "issues", "issueCount"),
        "stars": sum(s for s in stars if s) if stars else None,  # the 100 most starred own repos: a lower bound beyond that
        "followers": _num(viewer, "followers", "totalCount"),
    }


def connect(http, store, token):
    """Check a token (read-only call) and keep it. Returns the account's login. Raises AuthError for a rejected token."""
    token = (token or "").strip().strip("\"'")
    if not token:
        raise Fatal(bi("Kein Token eingegeben.", "No token entered."))
    login = GitHubClient(http, token).me()  # validates before storing
    store.update(github_token=token, github_user=login)
    return login


def disconnect(store):
    """Forget the token locally. (Revoking it on GitHub has to happen there: TOKEN_REVOKE_PAGE.)"""
    store.clear(GITHUB_KEYS)


class GitHubClient:
    def __init__(self, http, token, clock=time.time):
        self.http, self.token, self.clock = http, token, clock

    def _headers(self):
        return {**HEADERS, "Authorization": f"Bearer {self.token}"}

    def _request(self, method, url, **kw):
        try:
            return self.http.request(method, url, headers=self._headers(), retries=0, **kw)
        except HttpError as e:
            if e.status == 401:
                raise rejected() from None
            raise

    def me(self):
        """Validates the token (works for classic and fine-grained ones); returns the account's login."""
        return (self._request("GET", API + "/user") or {}).get("login") or ""

    def stats(self):
        """dict for the gh_* lines; raises AuthError (token rejected), HttpError or NetworkError (try again later)."""
        resp = self._request("POST", GRAPHQL, json_body={"query": QUERY})
        data = resp.get("data") if isinstance(resp, dict) else None
        errors = resp.get("errors") if isinstance(resp, dict) else None
        if errors and any(isinstance(e, dict) and e.get("type") == "RATE_LIMITED" for e in errors):
            raise HttpError(429, {"message": "GitHub GraphQL rate limit"}, {}, "api.github.com/graphql")
        if not isinstance(data, dict) or not data.get("viewer"):
            first = errors[0].get("message") if errors and isinstance(errors[0], dict) else "no data"
            raise NetworkError(f"GitHub GraphQL: {str(first)[:120]}")
        return parse_stats(data, latest_date(self.clock()))

"""Spotify -> Fluxer Webhook. Eine Nachricht, die sich live selbst aktualisiert.

Setup:  set SPOTIFY_CLIENT_ID=...   set FLUXER_WEBHOOK=https://api.fluxer.app/webhooks/ID/TOKEN
        python spotify_status.py login     (einmalig, Browser)
        python spotify_status.py           (laeuft dauerhaft)
"""
import base64, hashlib, http.server, json, os, secrets, sys, time, urllib.error, urllib.parse, urllib.request, webbrowser
from pathlib import Path


class Fatal(Exception):
    """Fehler, bei dem Weitermachen sinnlos ist / Error that retrying cannot fix."""


def die(de, en):
    sys.exit(f"\n[FEHLER] {de}\n[ERROR]  {en}\n")


def load_env(path):  # .env neben dem Script; echte Umgebungsvariablen gewinnen
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        k, eq, v = line.partition("=")
        k = k.strip()
        if eq and k and not k.startswith("#"):
            os.environ.setdefault(k, v.strip().strip("\"'"))


load_env(Path(__file__).with_name(".env"))
CID = os.environ.get("SPOTIFY_CLIENT_ID", "")
HOOK = os.environ.get("FLUXER_WEBHOOK", "").rstrip("/")  # optional: Karte im Channel
TOKEN = os.environ.get("FLUXER_TOKEN", "")  # optional: eigener Account-Token -> Profil-Status
API = os.environ.get("FLUXER_API", "https://api.fluxer.app/v1")
REDIRECT = "http://127.0.0.1:8888/callback"  # exakt so im Spotify-Dashboard eintragen
SCOPES = "user-read-playback-state user-read-recently-played user-top-read"
FILE = Path(__file__).with_name("state.json")  # Tokens + ID der Fluxer-Nachricht
st = json.loads(FILE.read_text()) if FILE.exists() else {}
save = lambda: FILE.write_text(json.dumps(st))


def call(url, data=None, headers=None, method=None):
    h = {"User-Agent": "spotify-fluxer/1.0", **(headers or {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, h, method=method), timeout=15) as r:
            b = r.read()
            return json.loads(b) if b else {}
    except urllib.error.HTTPError as e:
        host = urllib.parse.urlparse(url).netloc  # nur der Host: Webhook-URLs enthalten ein Geheimnis
        print(f"HTTP {e.code} bei {host}: {e.read()[:300]}")
        if e.code == 401 and host.endswith("spotify.com"):
            raise Fatal("Spotify lehnt den Zugang ab (401). Bitte erneut anmelden: python spotify_status.py login\n"
                        "Spotify rejected access (401). Please log in again: python spotify_status.py login")
        if e.code == 429:
            time.sleep(int(e.headers.get("Retry-After", 5)))
        raise


def token(**p):
    t = call("https://accounts.spotify.com/api/token",
             urllib.parse.urlencode({"client_id": CID, **p}).encode(),
             {"Content-Type": "application/x-www-form-urlencoded"})
    st["access"], st["exp"] = t["access_token"], time.time() + t["expires_in"]
    st["refresh"] = t.get("refresh_token", st.get("refresh"))
    save()


def login():
    ver = secrets.token_urlsafe(64)
    chal = base64.urlsafe_b64encode(hashlib.sha256(ver.encode()).digest()).rstrip(b"=").decode()
    webbrowser.open("https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": CID, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
        "code_challenge_method": "S256", "code_challenge": chal}))
    got = {}
    print("Browser oeffnet sich... / Opening browser... (Redirect URI: " + REDIRECT + ")")

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            self.send_response(200); self.end_headers()
            self.wfile.write(b"Fertig, Fenster kann zu.")
        log_message = lambda *a: None

    http.server.HTTPServer(("127.0.0.1", 8888), H).handle_request()
    if "code" not in got:
        die(f"Spotify hat keinen Code geliefert ({got.get('error', 'unbekannt')}). Redirect-URI im Dashboard exakt "
            f"{REDIRECT} eintragen und nochmal versuchen.",
            f"Spotify returned no code ({got.get('error', 'unknown')}). Add the redirect URI {REDIRECT} exactly in the "
            "dashboard and retry.")
    token(grant_type="authorization_code", code=got["code"], redirect_uri=REDIRECT, code_verifier=ver)
    print("Login ok.")


def sp(path):
    if time.time() > st.get("exp", 0) - 60:
        token(grant_type="refresh_token", refresh_token=st["refresh"])
    return call("https://api.spotify.com/v1" + path, headers={"Authorization": "Bearer " + st["access"]})


mmss = lambda ms: f"{ms // 60000}:{ms // 1000 % 60:02d}"
bar = lambda p, d, n=14: "▰" * (round(n * p / d) if d else 0) + "▱" * (n - (round(n * p / d) if d else 0))
who = lambda t: ", ".join(a["name"] for a in t.get("artists", [])) or t.get("show", {}).get("name", "")
lines = lambda xs: "\n".join(xs)[:1000] or "-"

slow = {"track": None, "top": 0}  # Queue/Zuletzt nur bei Songwechsel, Tops stuendlich


def build():
    pb = sp("/me/player?additional_types=track,episode")
    it = pb.get("item")
    if not it:
        slow["now"] = None
        return {"title": "Spotify", "description": "Gerade nichts am Laufen", "color": 0x535353}, "idle"
    playing = pb["is_playing"]
    slow["now"] = f"{it['name']} – {who(it)}" if playing else None
    if slow["track"] != it["id"]:
        slow["track"] = it["id"]
        q = sp("/me/player/queue").get("queue", [])
        slow["next"] = f"{q[0]['name']} – {who(q[0])}" if q else "-"
        rec = sp("/me/player/recently-played?limit=5")["items"]
        slow["recent"] = [f"{r['track']['name']} – {who(r['track'])}" for r in rec if r["track"]["id"] != it["id"]][:3]
    if time.time() - slow["top"] > 3600:
        slow["top"] = time.time()
        slow["ta"] = [f"{i}. {a['name']}" for i, a in enumerate(sp("/me/top/artists?time_range=short_term&limit=5")["items"], 1)]
        slow["tt"] = [f"{i}. {t['name']} – {who(t)}" for i, t in enumerate(sp("/me/top/tracks?time_range=short_term&limit=5")["items"], 1)]
    alb = it.get("album") or it.get("show") or {}
    dev = pb.get("device", {})
    foot = [dev.get("name", "?"), f"🔊 {dev.get('volume_percent', '?')}%"]
    if pb.get("shuffle_state"): foot.append("🔀")
    if pb.get("repeat_state") != "off": foot.append("🔁" if pb["repeat_state"] == "context" else "🔂")
    if "popularity" in it: foot.append(f"★ {it['popularity']}")
    if it.get("explicit"): foot.append("E")
    if alb.get("release_date"): foot.append(alb["release_date"][:4])
    e = {
        "title": it["name"][:256], "url": it.get("external_urls", {}).get("spotify"),
        "description": f"{who(it)} · {alb.get('name', '')}\n{'▶' if playing else '⏸'} {bar(pb['progress_ms'], it['duration_ms'])} "
                       f"{mmss(pb['progress_ms'])}/{mmss(it['duration_ms'])}",
        "color": 0x1DB954 if playing else 0x535353,
        "fields": [
            {"name": "⏭ Als Nächstes", "value": slow["next"], "inline": True},
            {"name": "🕘 Zuletzt", "value": lines(slow["recent"]), "inline": True},
            {"name": "🏆 Top Artists (4 Wo.)", "value": lines(slow["ta"]), "inline": True},
            {"name": "🔥 Top Tracks (4 Wo.)", "value": lines(slow["tt"]), "inline": True},
        ],
        "footer": {"text": " · ".join(foot)},
    }
    if alb.get("images"): e["thumbnail"] = {"url": alb["images"][0]["url"]}
    return e, (it["id"], playing, dev.get("name"), pb.get("shuffle_state"), pb.get("repeat_state"))


def set_status(text):
    body = json.dumps({"custom_status": {"text": ("🎵 " + text)[:128]} if text else None}).encode()
    for auth in (st.get("auth") or [TOKEN, "Bearer " + TOKEN]):  # welches Format Fluxer will, merkt sich das Script
        try:
            call(API + "/users/@me/settings", body, {"Authorization": auth, "Content-Type": "application/json"}, "PATCH")
            st["auth"] = [auth]; save()
            return
        except urllib.error.HTTPError as ex:
            if ex.code != 401:
                raise
    raise Fatal("Fluxer lehnt den Token ab (401). FLUXER_TOKEN neu aus dem Browser holen (siehe README) und in .env eintragen.\n"
                "Fluxer rejected the token (401). Copy a fresh FLUXER_TOKEN from the browser (see README) into .env.")


def push(embed):
    body = json.dumps({"username": "Spotify", "embeds": [embed]}).encode()
    h = {"Content-Type": "application/json"}
    if st.get("msg"):
        try:
            return call(f"{HOOK}/messages/{st['msg']}", body, h, "PATCH")
        except Exception as ex:  # ponytail: bei jedem Fehler neu posten, evtl. Duplikat bei kurzem Netzfehler
            print("edit failed, posting new:", ex)
    st["msg"] = call(HOOK + "?wait=true", body, h, "POST").get("id")
    save()


if __name__ == "__main__":
    if not CID:
        die("SPOTIFY_CLIENT_ID fehlt. Kopiere .env.example nach .env und trage die Client ID aus "
            "https://developer.spotify.com/dashboard ein.",
            "SPOTIFY_CLIENT_ID is missing. Copy .env.example to .env and paste the Client ID from "
            "https://developer.spotify.com/dashboard.")
    try:
        if sys.argv[1:] == ["login"]:
            login(); sys.exit()
    except Fatal as ex:
        sys.exit(f"\n{ex}\n")
    except urllib.error.HTTPError:
        die("Spotify-Login fehlgeschlagen. Stimmt die SPOTIFY_CLIENT_ID?", "Spotify login failed. Is SPOTIFY_CLIENT_ID correct?")
    if not (HOOK or TOKEN):
        die("Weder FLUXER_TOKEN noch FLUXER_WEBHOOK gesetzt. Trage mindestens eines in .env ein (siehe README).",
            "Neither FLUXER_TOKEN nor FLUXER_WEBHOOK is set. Put at least one into .env (see README).")
    if not st.get("refresh"):
        die("Noch nicht bei Spotify angemeldet. Erst ausfuehren: python spotify_status.py login",
            "Not logged in to Spotify yet. Run first: python spotify_status.py login")
    last, last_push = None, 0
    try:
        while True:
            try:
                e, key = build()
                # Neu senden bei Aenderung, sonst alle 30 s fuer den Fortschrittsbalken (nur wenn es laeuft)
                if key != last and TOKEN:
                    set_status(slow["now"])  # Profil-Status nur bei Wechsel; leer bei Pause/Idle
                if HOOK and (key != last or (key != "idle" and key[1] and time.time() - last_push > 30)):
                    push(e); last_push = time.time()
                last = key
            except Fatal as ex:
                sys.exit(f"\n{ex}\n")
            except Exception as ex:
                print("Fehler:", ex)
                time.sleep(10)
            time.sleep(5)
    except KeyboardInterrupt:
        print("\nBeendet. / Stopped.")
        if TOKEN:
            try: set_status(None)
            except Exception: pass

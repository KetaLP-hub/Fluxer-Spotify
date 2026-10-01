"""Fluxer API: password login (ALTCHA captcha, MFA, new-IP approval), status, logout, webhook.

Endpoints (docs.fluxer.app/http-api/authentication, /topics/captcha):
  POST /auth/login                      {email, password} -> {token,user_id,user} | {mfa:true,ticket,...} | 403 IP_AUTHORIZATION_REQUIRED
  POST /auth/login/mfa/totp             {code, ticket}    -> {token,...}
  POST /auth/ip-authorization/poll      {ticket}          -> {completed, token?}
  POST /auth/logout                     (session token)   -> 204
  GET  /users/@me, PATCH /users/@me/settings
Session tokens go into `Authorization` WITHOUT a scheme prefix.
"""
import base64
import hashlib
import json
import logging
import time

from .errors import AuthError, LoginError, bi, blog
from .http import HttpError

log = logging.getLogger("fluxer_spotify.fluxer")
CAPTCHA_CODES = ("CAPTCHA_REQUIRED", "INVALID_CAPTCHA")
DIGESTS = {"PBKDF2/SHA-256": "sha256", "PBKDF2/SHA-384": "sha384", "PBKDF2/SHA-512": "sha512"}


# ---------------------------------------------------------------- ALTCHA (v2, PBKDF2) proof of work
def solve_altcha(challenge, timeout=90.0, clock=time.monotonic):
    """Return the base64 value for the X-Captcha-Token header.

    Mirrors altcha-lib v2 `solveChallenge`: password = bytes.fromhex(nonce) + uint32_be(counter),
    key = PBKDF2(digest, password, bytes.fromhex(salt), cost, keyLength); first counter whose key
    starts with keyPrefix (hex) wins. `parameters` and `signature` are echoed back unchanged.
    """
    p = challenge["parameters"]
    digest = DIGESTS.get(p.get("algorithm"))
    if not digest:
        raise LoginError(bi(f"Unbekannter Captcha-Algorithmus: {p.get('algorithm')}",
                            f"Unsupported captcha algorithm: {p.get('algorithm')}"))
    nonce, salt = bytes.fromhex(p["nonce"]), bytes.fromhex(p["salt"])
    cost, klen, prefix = int(p["cost"]), int(p["keyLength"]), p["keyPrefix"].lower()
    start, counter = clock(), 0
    while True:
        key = hashlib.pbkdf2_hmac(digest, nonce + counter.to_bytes(4, "big"), salt, cost, klen).hex()
        if key.startswith(prefix):
            break
        counter += 1
        if counter >= 2 ** 32 or clock() - start > timeout:
            raise LoginError(bi("Captcha konnte nicht geloest werden (Zeitlimit).",
                                "Could not solve the captcha (timeout)."))
    payload = {"challenge": {"parameters": p, "signature": challenge["signature"]},
               "solution": {"counter": counter, "derivedKey": key, "time": int((clock() - start) * 1000)}}
    token = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    if len(token) > 4096:  # server limit
        raise LoginError(bi("Captcha-Token zu lang.", "Captcha token too long."))
    return token


def _read_challenge(err):
    provider = err.field("captcha_provider")
    if provider != "altcha":
        raise LoginError(bi(
            f"Dieser Server verlangt ein Captcha vom Typ '{provider}', das die Konsole nicht loesen kann. "
            "Nutze stattdessen: fluxer-token (Token aus dem Browser einfuegen).",
            f"This server requires a '{provider}' captcha which a CLI cannot solve. "
            "Use instead: fluxer-token (paste the token from your browser)."))
    ch = err.field("altcha_challenge")
    if not (isinstance(ch, dict) and isinstance(ch.get("parameters"), dict) and isinstance(ch.get("signature"), str)):
        raise LoginError(bi("Captcha-Challenge hat ein unerwartetes Format.", "Unexpected captcha challenge format."))
    return ch


# ---------------------------------------------------------------- login
LOGIN_ERRORS = {
    "INVALID_EMAIL_OR_PASSWORD": ("E-Mail oder Passwort falsch.", "Wrong e-mail or password."),
    "RATE_LIMITED": ("Zu viele Versuche. Bitte spaeter erneut probieren (Limit: 5 Versuche / 15 Min pro E-Mail).",
                     "Too many attempts. Try again later (limit: 5 attempts / 15 min per e-mail)."),
    "ACCOUNT_SUSPENDED_TEMPORARILY": ("Account ist vorlaeufig gesperrt.", "Account is temporarily suspended."),
    "ACCOUNT_SUSPENDED_PERMANENTLY": ("Account ist gesperrt.", "Account is suspended."),
    "REGISTRATION_PENDING_APPROVAL": ("Account wartet noch auf Freischaltung.", "Account is still pending approval."),
    "SSO_REQUIRED": ("Dieser Account nutzt SSO. Nutze stattdessen: fluxer-token.",
                     "This account uses SSO. Use fluxer-token instead."),
    "GLOBAL_IP_TEMPORARILY_BANNED": ("Deine IP ist voruebergehend gesperrt.", "Your IP is temporarily banned."),
    "GLOBAL_IP_BANNED": ("Deine IP ist gesperrt.", "Your IP is banned."),
    "TWO_FACTOR_REQUIRED": ("Zwei-Faktor-Anmeldung erforderlich.", "Two-factor authentication required."),
}


def login_error(e):
    de, en = LOGIN_ERRORS.get(e.code, (f"Anmeldung fehlgeschlagen (HTTP {e.status} {e.code or ''}).",
                                       f"Login failed (HTTP {e.status} {e.code or ''})."))
    if e.code == "INVALID_FORM_BODY":  # welches Feld stoert? nur Pfad/Meldung, nie Werte
        errs = e.field("errors") or e.field("issues") or e.field("message")
        detail = json.dumps(errs, ensure_ascii=False)[:300] if errs else ""
        de, en = de + " " + detail, en + " " + detail
    return LoginError(bi(de, en))


def _post(http, api, path, body, headers=None, max_solves=2):
    """POST that transparently solves ALTCHA challenges (like the web client's interceptor). No retries:
    login endpoints have tight, per-account limits."""
    headers = dict(headers or {})
    for solves in range(max_solves + 1):
        try:
            return http.request("POST", api + path, json_body=body, headers=headers, retries=0)
        except HttpError as e:
            if e.status == 400 and e.code in CAPTCHA_CODES and solves < max_solves:
                log.info(bi("Loese Captcha ...", "Solving captcha ...", " / "))
                headers["X-Captcha-Token"], headers["X-Captcha-Type"] = solve_altcha(_read_challenge(e)), "altcha"
                continue
            raise


def login(http, api, email, password, prompt_code, notify=print, sleep=time.sleep, clock=time.monotonic,
          ip_timeout=600, ip_interval=3, mfa_attempts=3):
    """Returns {"token", "user_id", "user"}. `prompt_code(attempt) -> str | None` supplies MFA codes.

    The password only lives in the JSON body of this single request; nothing is logged or persisted.
    """
    try:
        r = _post(http, api, "/auth/login", {"email": email, "password": password})
    except HttpError as e:
        if e.status == 403 and e.code == "IP_AUTHORIZATION_REQUIRED":
            r = _wait_ip_authorization(http, api, e, notify, sleep, clock, ip_timeout, ip_interval)
        else:
            raise login_error(e) from None
    if r.get("mfa"):
        r = _mfa(http, api, r, prompt_code, notify, mfa_attempts)
    if not isinstance(r.get("token"), str) or not r["token"]:
        raise LoginError(bi("Unerwartete Antwort vom Server (kein Token).", "Unexpected server response (no token)."))
    return {"token": r["token"], "user_id": r.get("user_id"), "user": r.get("user") or {}}


def _mfa(http, api, ch, prompt_code, notify, attempts):
    methods = set(ch.get("allowed_methods") or [m for m in ("totp", "backup_codes", "webauthn") if ch.get(m)])
    if not methods & {"totp", "backup_codes"}:
        raise LoginError(bi(
            "Dein Account nutzt nur Passkey/WebAuthn als 2. Faktor - das geht nicht in der Konsole. "
            "Nutze stattdessen: fluxer-token (Token aus dem Browser einfuegen).",
            "Your account only has passkey/WebAuthn as second factor, which a CLI cannot do. "
            "Use instead: fluxer-token (paste the token from your browser)."))
    for attempt in range(attempts):
        code = prompt_code(attempt)
        if not code:
            raise LoginError(bi("Abgebrochen.", "Cancelled."))
        try:
            return _post(http, api, "/auth/login/mfa/totp",
                         {"code": code.strip().replace(" ", ""), "ticket": ch["ticket"]})
        except HttpError as e:
            if e.code in ("INVALID_CODE", "INVALID_MFA_CODE") and attempt < attempts - 1:
                notify(bi("Code falsch, nochmal versuchen.", "Wrong code, try again."))
                continue
            if e.code == "SESSION_TIMEOUT":
                raise LoginError(bi("Das Zeitfenster (5 Min) fuer den Code ist abgelaufen. Bitte neu anmelden.",
                                    "The 5 minute window for the code expired. Please log in again.")) from None
            raise login_error(e) from None


def _wait_ip_authorization(http, api, err, notify, sleep, clock, timeout, interval):
    ticket = err.field("ticket")
    if not ticket:
        raise login_error(err)
    where = err.field("email") or "?"
    notify(bi(f"Neue IP-Adresse: Fluxer hat eine Bestaetigungs-Mail an {where} geschickt. "
              "Bitte den Link darin oeffnen, ich warte ...",
              f"New IP address: Fluxer sent a confirmation e-mail to {where}. Open the link in it, waiting ..."))
    deadline = clock() + timeout
    while clock() < deadline:
        sleep(interval)
        try:
            r = http.request("POST", api + "/auth/ip-authorization/poll", json_body={"ticket": ticket}, retries=2)
        except HttpError as e:
            raise login_error(e) from None
        if r.get("completed"):
            return r
    raise LoginError(bi("Zeit abgelaufen, IP wurde nicht bestaetigt.", "Timed out; the IP was not confirmed."))


# ---------------------------------------------------------------- authenticated client
class FluxerClient:
    def __init__(self, http, api, token, source="login"):
        self.http, self.api, self.token, self.source = http, api, token, source
        # Session tokens ("flx_...") take no prefix. Anything else (hand-pasted) gets a one-time scheme probe.
        self._schemes = [""] if token.startswith("flx_") else ["", "Bearer "]

    def _call(self, method, path, body=None):
        last = None
        for scheme in list(self._schemes):
            try:
                r = self.http.request(method, self.api + path, json_body=body,
                                      headers={"Authorization": scheme + self.token})
                self._schemes = [scheme]  # remember what worked
                return r
            except HttpError as e:
                if e.status != 401:
                    raise
                last = e
        raise AuthError(self._relogin_hint()) from last

    def _relogin_hint(self):
        if self.source == "manual":
            return bi("Fluxer lehnt den Token ab (401). Hole einen neuen: fluxer-login (empfohlen) oder fluxer-token.",
                      "Fluxer rejected the token (401). Get a new one: fluxer-login (recommended) or fluxer-token.")
        return bi("Fluxer-Sitzung ist abgelaufen oder wurde beendet (401). Bitte neu anmelden: fluxer-login",
                  "Fluxer session expired or was revoked (401). Please log in again: fluxer-login")

    def me(self):
        return self._call("GET", "/users/@me")

    def set_status(self, text):
        return self._call("PATCH", "/users/@me/settings", {"custom_status": {"text": text} if text else None})

    def logout(self):
        """Revoke this session. Only call for tokens created by fluxer-login."""
        return self._call("POST", "/auth/logout")


class Webhook:
    """Optional self-updating embed card in a channel."""

    def __init__(self, http, url, store):
        self.http, self.url, self.store = http, url, store

    def push(self, embed):
        body = {"username": "Spotify", "embeds": [embed]}
        if self.store.get("msg"):
            try:
                return self.http.request("PATCH", f"{self.url}/messages/{self.store.get('msg')}", json_body=body)
            except HttpError as e:
                log.warning(blog("Webhook-Bearbeitung fehlgeschlagen (HTTP %s), sende neue Nachricht", "Webhook edit failed (HTTP %s), posting a new message", e.status))
        r = self.http.request("POST", self.url + "?wait=true", json_body=body)
        self.store.update(msg=r.get("id"))

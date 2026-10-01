"""The main loop: poll Spotify, publish changes to Fluxer (status) and optionally a webhook card."""
import logging
import time

from .errors import AuthError, bi
from .http import HttpError, NetworkError
from .lines import STATS, Lines
from .spotify import status_text

log = logging.getLogger("fluxer_spotify.run")
KEEP = object()  # "leave the current status alone"
UNSET = object()  # nothing sent yet: the first wanted status (even "clear") always goes out


def retry_wait(e, failures):
    """Seconds to leave Fluxer alone after a failed status call: Retry-After if it sent one, else 10s .. 120s backoff."""
    try:
        return min(120.0, max(1.0, float(e.headers.get("retry-after") or e.body.get("retry_after"))))
    except (AttributeError, TypeError, ValueError):
        return min(120.0, 10.0 * 2 ** (failures - 1))


class Runner:
    def __init__(self, cfg, spotify, fluxer=None, webhook=None, clock=time.time):
        self.cfg, self.spotify, self.fluxer, self.webhook, self.clock = cfg, spotify, fluxer, webhook, clock
        self.last_key, self.last_push, self.failures = None, 0.0, 0
        self.lines = Lines(cfg, spotify, clock)
        self.sent, self.hold_until, self.status_failures = UNSET, 0.0, 0  # last status Fluxer accepted; PATCH pause after errors
        self.rot_id, self.rot_start = None, 0.0  # (track, playing) the rotation belongs to, and when it began

    def wanted_status(self, snap, now=None):
        """The text that should be shown right now (None = clear, KEEP = leave alone). Rotates through the lines."""
        now = self.clock() if now is None else now
        if snap.item is None:
            self.rot_id = None
            return None  # nothing active: always clear
        rot_id = (snap.item.get("id"), snap.playing)
        if rot_id != self.rot_id:  # song change / play / pause: start over, 'now' first
            self.rot_id, self.rot_start = rot_id, now
        names = self.cfg.lines
        if not snap.playing:
            if self.cfg.on_pause != "stats":
                return None if self.cfg.on_pause == "clear" else KEEP
            names = [n for n in names if n in STATS]
        rotating = not self.cfg.no_rotate
        avail = self.lines.available(snap, names, first_only=not rotating)
        if not avail:
            return None
        if len(avail) == 1:
            return avail[0][1]
        step = int(max(0.0, now - self.rot_start) // self.cfg.rotate)
        start = next((i for i, (n, _) in enumerate(avail) if n == "now"), 0)  # a new song begins on its 'now' line
        return avail[(start + step) % len(avail)][1]

    def tick(self):
        snap = self.spotify.snapshot(full=self.webhook is not None)
        changed = snap.key != self.last_key
        now = self.clock()
        if self.fluxer and now >= self.hold_until:
            want = self.wanted_status(snap, now)
            if want is not KEEP and want != self.sent:  # PATCH only when the text really changes
                self._set_status(want, now)
        if self.webhook and (changed or (snap.playing and self.clock() - self.last_push > 30)):
            self.webhook.push(snap.embed)
            self.last_push = self.clock()
        if changed:
            log.info("Now: %s", self.describe(snap))
        self.last_key = snap.key

    @staticmethod
    def describe(snap):
        if snap.item is None:
            return "idle"
        return ("playing " if snap.playing else "paused ") + status_text(snap.item, "{title} – {artist}")

    def _set_status(self, text, now):
        try:
            self.fluxer.set_status(text)
            self.sent, self.status_failures = text, 0
            log.debug("Status: %s", text)
        except (HttpError, NetworkError) as e:  # a failing status call must not stop polling or the webhook
            self.status_failures += 1
            wait = retry_wait(e, self.status_failures)
            self.hold_until = now + wait
            log.warning("Status konnte nicht gesetzt werden / could not set status: %s (again in %.0fs)", e, wait)
        except AuthError as e:
            if not self.webhook:
                raise
            log.error("%s\n-> Profil-Status deaktiviert, Webhook laeuft weiter. / Profile status disabled, webhook keeps running.", e)
            self.fluxer = None

    def run(self, sleep=time.sleep):
        """Loop until interrupted. Transient errors back off exponentially (10s .. 120s)."""
        while True:
            try:
                self.tick()
                self.failures = 0
                sleep(self.cfg.interval)
            except (HttpError, NetworkError) as e:
                self.failures += 1
                wait = min(120, 10 * 2 ** (self.failures - 1))
                log.warning("Fehler / error: %s (again in %ss)", e, wait)
                sleep(wait)

    def shutdown(self):
        """Clear the status on the way out (best effort)."""
        if self.fluxer:
            try:
                self.fluxer.set_status(None)
                log.info("Status geloescht. / Status cleared.")
            except Exception as e:  # never block shutdown
                log.warning("Konnte Status nicht loeschen / could not clear status: %s", e)

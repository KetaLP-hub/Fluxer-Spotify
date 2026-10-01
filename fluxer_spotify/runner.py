"""The main loop: poll Spotify, publish changes to Fluxer (status) and optionally a webhook card."""
import logging
import time

from .errors import AuthError, bi
from .http import HttpError, NetworkError
from .spotify import status_text

log = logging.getLogger("fluxer_spotify.run")
KEEP = object()  # "leave the current status alone"


class Runner:
    def __init__(self, cfg, spotify, fluxer=None, webhook=None, clock=time.time):
        self.cfg, self.spotify, self.fluxer, self.webhook, self.clock = cfg, spotify, fluxer, webhook, clock
        self.last_key, self.last_push, self.failures = None, 0.0, 0

    def wanted_status(self, snap):
        if snap.item is None:
            return None  # nothing active: always clear
        if snap.playing:
            return status_text(snap.item, self.cfg.template)
        return None if self.cfg.on_pause == "clear" else KEEP

    def tick(self):
        snap = self.spotify.snapshot(full=self.webhook is not None)
        changed = snap.key != self.last_key
        if changed and self.fluxer:
            want = self.wanted_status(snap)
            if want is not KEEP:
                self._set_status(want)
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

    def _set_status(self, text):
        try:
            self.fluxer.set_status(text)
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

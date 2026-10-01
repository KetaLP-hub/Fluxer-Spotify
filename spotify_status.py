"""Thin entry point so `python spotify_status.py ...` and start.bat keep working. Code lives in fluxer_spotify/."""
import sys

from fluxer_spotify.cli import entry

if __name__ == "__main__":
    sys.exit(entry())

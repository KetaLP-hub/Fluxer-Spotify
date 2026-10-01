# Changelog

All notable changes to this project. Format based on [Keep a Changelog](https://keepachangelog.com/).

## [2.1.0] - 2026-10-02

### Added
- **Configurable language**: `--lang {auto,de,en}` / `LANGUAGE` (flags > env > `.env` > stored value). `auto` follows the Windows UI language (German if it starts with `de`, English otherwise).
- Messages, wizard texts, `doctor` output, errors and the default status lines now appear only in the selected language instead of always in both.
- First-run wizard asks for the language first (Enter accepts the detected one).
- Default status lines in English, e.g. `🏆 Top artist this week: …` and `🎧 2 h 14 min listened today`; the "today" line drops zero parts (`25 min`, `2 h`, `1 h 30 min`). Custom templates are unchanged.
- `doctor` shows the active language; the hidden background copy inherits it.

### Changed
- `README.md` is now the full English README; the German version moved to `README.de.md` (language switch at the top of both).
- Added missing translations for doctor lines, login prompts, the Spotify "close this window" page and the webhook card.

### Notes
- `LANGUAGE` from the real environment is ignored unless it is `auto`, `de` or `en` (POSIX uses `LANGUAGE` for locale lists).
- `--help` text and debug log lines (`-v`) stay English.

## [2.0.0] - 2026-10-02

### Added
- **Fluxer login inside the tool** (`fluxer-login`): e-mail and password prompt, ALTCHA captcha solved locally, 2FA (TOTP and backup codes), new-IP approval. Only the session token is stored; the password is never saved. `fluxer-token` as paste-token fallback (passkey-only accounts).
- **First-run setup wizard** (double-click the exe): Spotify Client ID (validated and saved), Spotify login, Fluxer login, optional Windows autostart.
- **Windows exe** (`Fluxer-Spotify.exe`) built with PyInstaller and a GitHub Actions release workflow (tests, smoke test, SHA256).
- **Hidden background mode** (`run --background`): no console window, rotating log file, single instance, `stop`, `logs`, `uninstall`, and `status`/`doctor` report whether it runs.
- **Rotating status lines**: now playing, playlist/album, top artist this week, listening time today; configurable (`--lines`, `--rotate`, `--no-rotate`, minimum 15 s) and pause modes `clear` / `keep` / `stats`.
- `doctor` command, structured logging with secret redaction, retries with backoff, atomic state file writes, and a unit test suite with CI on Windows and Linux (Python 3.10 to 3.13).

### Changed
- The single script became the `fluxer_spotify/` package (stdlib only); `spotify_status.py` stays as entry point.
- Fluxer API base switched to `https://api.fluxer.app/v1` (the web client origin rejects non-browser clients).

## [1.0.0] - 2026-10-01

### Added
- Initial release: Spotify now-playing as the Fluxer custom status, optional self-updating webhook card with queue, recent plays and top lists.

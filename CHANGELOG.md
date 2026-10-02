# Changelog

All notable changes to this project. Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- Release workflow: if a release for the tag already exists (e.g. created by hand in the GitHub UI), the exe and the `.sha256` are attached to it instead of failing at `gh release create`.

## [2.2.0] - 2026-10-02

### Added
- **Android (Termux) guide and scripts** so the status keeps running with the PC off, without a server: `termux/setup.sh` (one command: log in, autostart, start now), `termux/start.sh` (wake lock, background mode, retry every 5 minutes after errors) and `termux/install-boot.sh` (autostart through Termux:Boot). Written without a test on a real Android device. `.gitattributes` keeps `*.sh` on LF line endings.
- **GitHub as a second status source** (optional): `github-login` connects GitHub with a read-only token (stored encrypted on Windows, validated before saving). New lines `gh_push`, `gh_commits`, `gh_prs`, `gh_reviews`, `gh_issues`, `gh_streak`, `gh_stars`, `gh_followers` and the placeholders `{gh_repo}` `{gh_ago}` `{gh_commits}` `{gh_prs}` `{gh_reviews}` `{gh_issues}` `{gh_streak}` `{gh_stars}` `{gh_followers}`. One GraphQL request, cached for 5 minutes; zero counts are hidden; only a **public** repo name is ever shown. Connecting adds `gh_push gh_commits gh_prs gh_reviews gh_issues gh_streak` unless `STATUS_LINES` is set. A revoked token, rate limit or outage only hides the GitHub lines.
- **`--on-idle` / `ON_IDLE`** (`clear` default, or `lines`): keep rotating the lines that need no track while nothing plays at all. `ON_PAUSE=stats` now includes the GitHub lines.
- `doctor` checks the GitHub token; `logout` deletes it locally.
- **Encrypted token storage on Windows**: the Fluxer session token and the Spotify access/refresh tokens in `state.json` are now sealed with DPAPI (stdlib `ctypes`, no new dependency) and bound to your Windows user. Old plaintext files are upgraded on the next start; a token that cannot be decrypted counts as logged out. If encryption fails, the token is kept unencrypted (with a warning) instead of losing the login.
- `doctor` shows whether the tokens are encrypted.

### Fixed
- CI on Linux: the hidden-console test imports `ctypes` before faking `os.name`.

### Notes
- Linux/macOS keep plaintext tokens with `0600` permissions; the webhook URL and `.env` are never encrypted.

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

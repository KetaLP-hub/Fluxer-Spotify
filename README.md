English | [Deutsch](README.de.md)

# Spotify -> Fluxer

Shows what you are currently listening to on Spotify as the **custom status in your Fluxer profile** (e.g. "🎵 Song – Artist"). Optionally it also posts a card into a channel via webhook that keeps updating itself live.

A Windows program you just double-click, nothing to install. The source code only needs Python 3.10+ (no `pip install` packages).

> **Note:** Fluxer has no native Spotify integration. This tool only sets the **text status**, nothing more.

## Quick start (double-click, the program handles the rest)

1. **Download `Fluxer-Spotify.exe`** from [Releases](https://github.com/KetaLP-hub/Fluxer-Spotify/releases) and double-click it.
2. **Answer the questions.** On first start the program walks you through everything that is still missing and skips what is already done:
   1. **Spotify Client ID:** The program opens https://developer.spotify.com/dashboard. Choose "Create app", enter exactly `http://127.0.0.1:8888/callback` as the Redirect URI, copy the **Client ID** and paste it into the window. It is saved.
   2. **Spotify login:** Your browser opens, click "Agree".
   3. **Fluxer login:** E-mail and password (and a 2FA code if enabled). If that does not work (e.g. passkey account), the program offers to let you paste a token instead.
   4. Finally it **states clearly that it can keep running in the background and how to stop or uninstall it**, and asks once whether it should **start with Windows** (y/n, then it starts invisibly) and whether it should **hide the window now** and continue in the background (y/n).
3. After that the status is running. In the foreground: keep the window open and stop with `Ctrl+C`; the status is cleared when you do.

On the next start the program only asks again if a login has expired. All data lives in `%APPDATA%\spotify-fluxer` (including `state.json`, optionally `.env`). On an error the window stays open ("Press Enter") so you can read the message.

**Every person needs their own (free) Spotify app.** This is by Spotify's design: an app in development mode may only allow 25 users, so there cannot be one shared app for everyone.

### Background mode (no visible window)

`Fluxer-Spotify.exe run --background` (alias `--hidden`) runs without a window: the console is hidden, the log goes to a file, and there is never a prompt. If setup is incomplete or a login has expired, it exits with a log entry and shows a Windows message **once**: then start the program normally (double-click), it only asks for what is missing. If the network is not up yet at Windows startup, it retries for a few minutes. The autostart entry (`install-autostart`, or the question in the wizard) always launches this invisible variant.

- **Stop:** `Fluxer-Spotify.exe stop` (clears the Fluxer status first) or end the `Fluxer-Spotify.exe` process in Task Manager (this does not clear the status; a restart or `logout` resets it). Only **one** instance runs at a time; a second start reports that or exits silently.
- **Log:** `%APPDATA%\spotify-fluxer\fluxer-spotify.log` (rotating, max. about 1.5 MB); the last 50 lines with `Fluxer-Spotify.exe logs`. `status` shows whether the background instance is running.
- **Remove completely:** `Fluxer-Spotify.exe uninstall` (after confirmation: stops the program, removes autostart, logs out and deletes `state.json`, `.env` and logs). You delete the exe itself by hand afterwards.
- **Honest note:** A program running invisibly is only transparent to a person if they know about it. That is why the setup wizard explicitly says that the program keeps running in the background and how to stop and uninstall it. Do not install it on other people's machines without their knowledge.
- Hiding only affects the exe's own window; if you start it from an open command prompt, that stays visible (only the log goes to the file).

### Android (Termux): runs while your PC is off

The status is only updated while the program runs somewhere, so to keep it going with the PC off, run it on your **phone** (no server needed). This uses the source code (the exe is Windows-only) and Python's standard library, nothing to `pip install`.

1. Install **Termux** and **Termux:Boot** from [F-Droid](https://f-droid.org/packages/com.termux/) (the Play Store version of Termux is outdated).
2. In Termux: `pkg update && pkg install python git`, then `git clone https://github.com/KetaLP-hub/Fluxer-Spotify && cd Fluxer-Spotify`.
3. **Log in on the phone itself.** A login from the PC cannot be moved: on Windows the tokens are encrypted for your Windows user.
   - `export BROWSER=termux-open-url` (so the Spotify login opens your phone's browser), then `python spotify_status.py`. The setup asks for the Spotify Client ID, then Spotify (the browser returns to `http://127.0.0.1:8888/callback`, which is this phone, so it works), then the Fluxer e-mail and password. Optional: `python spotify_status.py github-login`.
   - Check with `python spotify_status.py doctor`.
4. Try it: `sh termux/start.sh` (stop with Ctrl+C). It keeps the CPU awake (`termux-wake-lock`, you get a Termux notification) and runs the program in background mode: it never asks questions, writes `fluxer-spotify.log`, and after an error such as an expired login or no network it tries again every 5 minutes.
5. Start after a reboot: `sh termux/install-boot.sh`, then open the **Termux:Boot** app once.
6. **Switch off the Windows autostart** (`Fluxer-Spotify.exe uninstall-autostart`) or stop the PC instance. Two instances would overwrite each other's status.

Stop: `python spotify_status.py stop` (clears the status). Log: `python spotify_status.py logs`. Update: `git pull`.

Things to know:
- **Android may kill Termux to save battery.** Exclude Termux (and Termux:Boot) from battery optimization in the Android settings. Android 12 and later can also end background processes of apps like Termux (the "phantom process killer"); if the status stops after a while, search for that term for your Android version. How strict this is depends on your phone's maker.
- Android has no DPAPI: the tokens in `state.json` are **not encrypted**, only protected by file permissions in the app's private folder. Do not copy that folder around.
- If setup is incomplete or a login expired, the log says "Please start Fluxer-Spotify.exe normally (double-click)". On the phone that means: run `python spotify_status.py` in Termux.
- This was written without a test on a real Android device. The scripts' logic is tested on Linux, the Android specifics (battery, Termux:Boot) are not.

### Windows warns about the file (SmartScreen / antivirus)

The exe is **not code-signed** (a certificate costs money). Windows SmartScreen therefore shows "Windows protected your PC" ("More info" -> "Run anyway"), and some antivirus tools wrongly flag PyInstaller programs (false positive). Verify the file with the `.sha256` from the release (`certutil -hashfile Fluxer-Spotify.exe SHA256`) or build it yourself from source (see below). If you do not trust the exe, just run `python spotify_status.py`.

No DevTools, no copying tokens, no environment variables.

### What happens to your password?

- You enter e-mail and password **only in the console** (hidden, `getpass`). There is deliberately **no** option to pass the password via a flag, environment variable or file.
- The password is sent **exactly once** to the Fluxer API (`https://api.fluxer.app/v1/auth/login`) and **stored nowhere**, not even in the log.
- Only the **session token** is stored, in `state.json` (local, written atomically, with `0600` permissions on Linux/macOS). The token appears in no log line.
- **On Windows the tokens inside `state.json` are encrypted with DPAPI** (built into Windows, no extra package). They can only be decrypted by your Windows user on this PC, so a copied `state.json` is useless to others. An older plaintext file is upgraded automatically on the next start. If a token cannot be decrypted (other user or PC), it is treated as logged out and you log in again. `doctor` shows whether encryption is active. On Linux/macOS there is no such backend yet, so the tokens stay plaintext and protected by file permissions only.
- The tool creates its **own session**. You can see it in the Fluxer settings and end it there at any time. `logout` ends it as well.
- Python cannot actively overwrite strings; the tool drops the reference right after login, and the process ends afterwards.
- The login captcha (ALTCHA, a pure proof-of-work puzzle) is solved automatically by the tool.

### More commands

| Command | Purpose |
|---|---|
| `status` / `doctor` | checks configuration, Spotify and Fluxer login and gives hints in plain language (never shows secrets) |
| `logout` | clears the Fluxer status, ends the Fluxer session (only if it came from `fluxer-login`) and deletes stored tokens (`--keep-spotify` keeps the Spotify login) |
| `fluxer-token` | fallback: paste a token from the browser (see below) |
| `github-login` | optional: connect GitHub with a read-only token (adds the GitHub status lines, see below) |
| `run --background` | run invisibly in the background (see above) |
| `stop` / `logs` / `uninstall` | stop the background instance / last 50 log lines / remove everything |
| `install-autostart` / `uninstall-autostart` | Windows: invisible start at login (Startup folder, no admin needed, log in `fluxer-spotify.log`) |
| `-v` / `--verbose` | verbose log (without secrets) |

### Settings

Normally not needed. Order of precedence: **command-line flags > environment variables > `.env` (in the data folder) > values saved by the program**. See `.env.example`.

- `--template` / `STATUS_TEMPLATE`: text of the status, e.g. `🎵 {title} – {artist}` (default). Placeholders: `{title}`, `{artist}`, `{album}`. Maximum 128 characters.
- `--on-pause` / `ON_PAUSE`: `clear` (default, clear the status on pause), `keep` (leave it) or `stats` (on pause, only rotate the statistics lines `top_artist`, `listening_today` and the GitHub lines; if none is active, the status is cleared).
- `--on-idle` / `ON_IDLE`: what to do when nothing is playing at all (no track, not even paused). `clear` (default) clears the status. `lines` keeps rotating every configured line that needs no track (`top_artist`, `listening_today`, the GitHub lines and custom lines that only use those values), so your GitHub status stays visible without music.
- `--lang` / `LANGUAGE`: language of all program texts: `auto` (default: follows the OS display language; German if it starts with `de`, otherwise English), `de` or `en`. The first interactive start asks once (Enter accepts the detected language) and stores the answer; set it explicitly to skip the question. It affects messages, errors, the setup wizard, `doctor`, tips, background notices, the default texts of the status lines and the webhook card. Your own `STATUS_TEMPLATE` / custom `STATUS_LINES` are never translated. Unknown values stop the program at startup. (A POSIX `LANGUAGE=de_DE:en` in the real environment is ignored; it is only used if it is `auto`, `de` or `en`.) The hidden background copy inherits the setting.
- `--lines` / `STATUS_LINES`: the rotating status lines in the desired order (default `now,playlist,top_artist,listening_today`). See below.
- `--rotate` / `ROTATE_SECONDS`: seconds per line (default 30, **minimum 15**; smaller values are set to 15 with a warning so Fluxer is not spammed).
- `--no-rotate` / `NO_ROTATE=1`: no rotation, only the first line is shown (as before this feature).
- `--webhook` / `FLUXER_WEBHOOK`: optional card in the channel.
- `--interval` / `POLL_INTERVAL`: polling in seconds (at least 2).

### Rotating status lines

While a track is playing, the status cycles through these lines:

| Name | Example | Source |
|---|---|---|
| `now` | `🎵 Title – Artist` | current track (text via `--template`) |
| `playlist` | `💿 from "Playlist name"` | playlist or album currently playing from |
| `top_artist` | `🏆 Top artist this week: Muse` | your top artists (`short_term`, about 4 weeks according to Spotify), fetched at most hourly |
| `listening_today` | `🎧 1 h 30 min listened today` | from "recently played", fetched at most every 5 minutes |

(English texts shown. With `LANGUAGE=de` they read `💿 aus "…"`, `🏆 Top-Artist diese Woche: …` and `🎧 heute 1 h 30 min gehört`. A zero part is dropped: `🎧 25 min listened today`, `🎧 2 h listened today`.)

- Lines without data are skipped, never shown with empty placeholders (e.g. `playlist` for podcasts, Liked Songs or artist radio). If only one line is left, there is no rotation.
- On a track change (and on play/pause) the rotation restarts with the `now` line. Something is only sent to Fluxer when the text actually changes. On errors or rate limits (Retry-After) the program only pauses status updates; it does not crash.
- `playlist`: The playlist name is looked up once per playlist. Private or Spotify-generated playlists (403/404) yield no name; the album name is shown instead. For albums the album name is used without a request.
- **Limit of `listening_today`:** The Spotify API only returns the last 50 plays. If you listened to more today, you therefore only see a minimum value ("lower bound"). "Today" is the local calendar day of your machine (from 00:00). Skipped tracks only count for the time they actually ran (rough estimate from the gaps between plays). Under one minute the line is omitted.
- Custom lines: in `STATUS_LINES` you can give a text with placeholders instead of a name: `{title}` `{artist}` `{album}` `{playlist}` `{top_artist}` `{hours}` `{minutes}` and the GitHub values `{gh_repo}` `{gh_ago}` `{gh_commits}` `{gh_prs}` `{gh_reviews}` `{gh_issues}` `{gh_streak}` `{gh_stars}` `{gh_followers}`. If a value is missing, the line is skipped. Separate names with a comma; if a custom line itself contains a comma, separate everything with `|`.
- Every line is truncated to 128 characters (with `…` at the end, the leading emoji stays).

### GitHub status lines (optional)

`python spotify_status.py github-login` (or `Fluxer-Spotify.exe github-login`) connects GitHub with a **read-only token** (the input is hidden; on Windows the token is stored encrypted like the others). Create a *fine-grained* token at <https://github.com/settings/personal-access-tokens/new>: "Public repositories" is enough for public data; for counts from private repos (open PRs, reviews, issues) choose "All repositories" with **Pull requests: Read** and **Issues: Read**. Never give it write permissions.

Once connected, these lines join the rotation (unless you set `STATUS_LINES` yourself; add the names below to it by hand in that case). Spotify stays required, GitHub is an extra source. Add `ON_IDLE=lines` to keep them visible while no music plays.

| Name | Example | Meaning |
|---|---|---|
| `gh_push` | `💻 last push: you/project (2 h ago)` | your most recently pushed **public** repository (a private repo name is never shown) |
| `gh_commits` | `💻 5 contributions on GitHub today` | today's contributions from your contribution calendar (commits, issues, PRs, reviews) |
| `gh_prs` | `🔀 2 open pull requests` | your open pull requests |
| `gh_reviews` | `👀 1 review requested` | open pull requests waiting for your review |
| `gh_issues` | `📌 3 issues assigned` | open issues assigned to you |
| `gh_streak` | `🔥 5-day streak on GitHub` | consecutive days with contributions (a day without any yet does not break it until it is over) |
| `gh_stars` | `⭐ 13 stars on GitHub` | stars on your own repositories (the 100 most starred: a lower bound beyond that) |
| `gh_followers` | `👥 42 followers` | your followers |

Connecting adds `gh_push gh_commits gh_prs gh_reviews gh_issues gh_streak`; `gh_stars` and `gh_followers` are opt-in. Zero counts are hidden (`0 open pull requests` is noise), and so is a streak below 2 days. Everything comes from one GraphQL request, cached for 5 minutes. If GitHub is unreachable, rate-limited or the token was revoked, only the GitHub lines disappear; the Spotify status keeps running (`doctor` tells you what is wrong). `logout` deletes the stored token locally; to revoke it, delete it at <https://github.com/settings/personal-access-tokens>. The notifications API is not used (fine-grained tokens cannot access it).

Example `.env`:

```
STATUS_LINES=now,playlist,top_artist,listening_today
ROTATE_SECONDS=30
ON_PAUSE=stats
ON_IDLE=lines
# or custom lines:
# STATUS_LINES=now|🔥 {top_artist} läuft bei mir|⏱ {hours} h {minutes} min heute
# rotation off:
# NO_ROTATE=1
# language: auto (default), de or en
LANGUAGE=en
```

`doctor` shows the active lines and the interval.

## Troubleshooting

First: `Fluxer-Spotify.exe status` (or `python spotify_status.py status`). Expired logins are renewed by the program itself on the next start.

- **"INVALID_CLIENT: Invalid redirect URI"** at Spotify: The Redirect URI in the dashboard must be exactly `http://127.0.0.1:8888/callback` (not `localhost`, no trailing slash).
- **Spotify 401 / "log in again"**: `python spotify_status.py login`.
- **Fluxer 401**: Session expired or ended in the settings: `python spotify_status.py fluxer-login`.
- **"Wrong e-mail or password"**: Typo? Note that Fluxer only allows 5 attempts per 15 minutes per e-mail.
- **New IP address**: Fluxer sends a confirmation e-mail. Open the link; the tool waits up to 10 minutes.
- **Account with passkey (WebAuthn) only, or SSO**: This does not work in the console. Use the `fluxer-token` fallback:
  1. Open Fluxer in the browser (logged in), `F12`, **Console** tab.
  2. Enter `copy(localStorage.getItem('token'))` (copies the token to the clipboard; according to Fluxer's source code it is stored there under the key `token`).
  3. Run `python spotify_status.py fluxer-token` and paste with Ctrl+V. The token is verified and saved.
  This token is your browser session: `logout` deletes it locally but does **not** revoke it.
- **403 from Fluxer**: The server refuses the action (e.g. account blocked or automation not allowed).
- **Captcha error**: The server requires a captcha that is not ALTCHA: use `fluxer-token`.
- Nothing happens: Is a song really playing on Spotify right now (ideally in the desktop or phone app)?
- **Umlauts/emoji shown as `?` in the console**: display issue in old Windows consoles only, the status itself is still correct.

## For developers: building from source and the exe

```
python spotify_status.py                     # run from source (data in the project folder)
python -m unittest discover -s tests -t .    # tests (standard library only)
pip install -r requirements-dev.txt          # PyInstaller, only needed for building
build_exe.bat                                # produces dist\Fluxer-Spotify.exe
```

The runtime uses only the standard library; PyInstaller is only needed for building. A `v*` tag (e.g. `git tag v2.1.0 && git push --tags`) triggers `.github/workflows/release.yml`: tests, build the exe, create a release with the exe and SHA256. As an exe, data lives in `%APPDATA%\spotify-fluxer`; from source it lives in the project folder (overridable with `--data-dir` or `FLUXER_SPOTIFY_HOME`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md): standard library only, run the tests before opening a PR, never log or commit secrets, user-facing messages are bilingual (German first, then English).

## Warning (Terms of Service)

Automating a **personal account** (self-bot) **may violate Fluxer's Terms of Service**. The tool signs in like a client with your account and only changes your status, but **use at your own risk**. If you only want the webhook, you do not need a login (set `FLUXER_WEBHOOK`, skip `fluxer-login`).

## SECURITY

- `state.json` and `.env` contain secrets (tokens, webhook URL). They are in `.gitignore`; **never commit or share them**. Whoever has the session token has full access to your Fluxer account until the session is ended (`logout` or Fluxer settings). On Windows the tokens in `state.json` are encrypted, but the webhook URL and `.env` are not.
- The tool only talks to `api.fluxer.app`, `accounts.spotify.com`, `api.spotify.com` and your webhook. `FLUXER_API` must use `https://` (exception: localhost).
- On Windows the tool sets no NTFS permissions; the file lives in your user folder. On a shared machine, protect the folder accordingly.
- Found a vulnerability? Please send a private note to the maintainers instead of opening a public issue.

## License

MIT, see [LICENSE](LICENSE).

# Contributing

- Stdlib only. No new dependencies; Python 3.10+.
- Run the tests before opening a PR: `python -m unittest discover -s tests -t .`
- Tests use a scripted fake HTTP transport (`tests/helpers.py`); never hit live services or commit real tokens.
- Never log request bodies, passwords, tokens or webhook URLs. New secrets go through `log.add_secret()`.
- User-facing messages are bilingual (German first, then English) via `errors.bi()`.
- Layout: `cli.py` (commands), `fluxer.py` (login/captcha/MFA/status), `spotify.py`, `runner.py` (loop), `http.py` (retries), `config.py`, `store.py`, `log.py`.

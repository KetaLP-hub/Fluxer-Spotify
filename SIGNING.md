# Signing the exe (and why Windows still warns without it)

**Kurz auf Deutsch:** Windows SmartScreen warnt bei jedem heruntergeladenen Programm ohne gültige Code-Signatur („Der PC wurde durch Windows geschützt“). Kein Programm kann das selbst abschalten – nur ein Zertifikat einer vertrauenswürdigen Stelle (und mit der Zeit aufgebauter Ruf). Dieses Projekt ist darauf vorbereitet: Der Release-Workflow signiert die Exe automatisch, sobald unten beschriebene Secrets gesetzt sind. Bis dahin hilft: Hash prüfen, selbst bauen (dann gibt es die Markierung „aus dem Internet“ nicht) oder „Weitere Informationen → Trotzdem ausführen“.

## What actually triggers the warnings

| Warning | Cause | What helps |
|---|---|---|
| SmartScreen "Windows protected your PC / Unknown publisher" | The file came from the internet (it carries a "mark of the web") **and** has no trusted signature / no reputation yet | A code-signing certificate; reputation builds with downloads. Or: no internet mark (build it yourself, or `Unblock-File`) |
| Antivirus quarantines or flags it ("Trojan:...!ml", "Wacatac") | PyInstaller programs are a frequent **false positive**: the self-extracting bootloader looks like a dropper to heuristics | No packer (`--noupx`, done), version resource and icon (done), no hidden script launchers (done), a signature, and reporting false positives |
| UAC prompt | Program asks for admin rights | Never: the exe runs as the normal user (`asInvoker`), autostart uses the per-user Run key |

What this project already does is listed in the README ("Windows warns about the file"). The one thing it cannot do for you is buy trust.

## Getting a certificate

- **SignPath Foundation (free for open source):** <https://signpath.org/>. Apply with this repository; it must meet their open-source criteria (public repo, OSI license — MIT qualifies). They sign through a GitHub Actions integration; the key never leaves their HSM. Good fit for this project.
- **Azure Trusted Signing** (Microsoft, a few euros per month, identity validation required, available for individuals/organizations in supported countries). Uses a GitHub Action instead of a PFX file.
- **A commercial code-signing certificate** (OV/EV) from a certificate authority. Since mid-2023 new public certificates must live on hardware or in a cloud HSM, so a downloadable `.pfx` is usually **not** issued any more; use the provider's cloud-signing service/CLI.
- **Self-signed certificate:** does **not** remove the warning for anybody else (they do not trust it). It only helps if you install that certificate as trusted on your own PC.

## How this repository signs

`.github/workflows/release.yml` has a step "Sign exe" that runs **only if** the repository secrets `WINDOWS_CERT_PFX_BASE64` and `WINDOWS_CERT_PASSWORD` exist. It signs with SHA-256 and an RFC 3161 timestamp (so the signature stays valid after the certificate expires), verifies it with `signtool verify /pa`, and the release notes say "Signed exe". Without the secrets the exe is built unsigned and the notes say so.

This path fits a certificate you **can export** as `.pfx`. Create the secrets with:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("codesign.pfx")) | Set-Clipboard   # paste as WINDOWS_CERT_PFX_BASE64
```

If you use SignPath, Azure Trusted Signing or another cloud service instead, replace that one step with the provider's action (their documentation shows the few lines); the rest of the workflow (build, smoke test, hash, release) stays the same. **Note:** none of the signing paths could be tested without a certificate; the workflow step is conditional so an unsigned release is never blocked by it.

## Sign by hand (e.g. with a hardware token)

```
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a dist\Fluxer-Spotify.exe
signtool verify /pa /v dist\Fluxer-Spotify.exe
certutil -hashfile dist\Fluxer-Spotify.exe SHA256
```

Upload the signed exe and a fresh `.sha256` to the release (replace the unsigned files).

## Until it is signed

- Check the hash against the `.sha256` file of the release: `certutil -hashfile Fluxer-Spotify.exe SHA256`.
- Build it yourself (`build_exe.bat`): a file you built has no mark of the web, so SmartScreen does not ask. Or run from source: `python spotify_status.py gui`.
- For a file you already downloaded and trust: right-click > Properties > "Unblock", or `Unblock-File .\Fluxer-Spotify.exe` in PowerShell.
- If Microsoft Defender flags it: restore it from quarantine and submit it as a false positive at <https://www.microsoft.com/wdsi/filesubmission> (developer submission); other vendors have similar forms.

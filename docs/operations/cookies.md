# Operations — Reels cookies

Reels are served to logged-in sessions. Without a session, Instagram returns
`empty media response`. This document records the tested options on this host
(2026-11-02, `yt-dlp 2026.10.26`).

## Test results

| Browser | Cookies found (instagram) | Extraction result |
|---|---|---|
| Firefox (`kvl29ev8.default-release`) | **0** | 342 cookies extracted, 0 undecryptable |
| Brave (`Default`) | 9 | 126 extracted, **366 undecryptable** (keyring locked over SSH) |
| Vivaldi (`Default`) | 7 | **0 extracted**, 9 undecryptable |

Interpretation:

- **Firefox is the only browser that decrypts cleanly** on this host, but it has no
  Instagram session yet. One login there is all that's needed.
- Brave holds the Instagram session but its cookie encryption depends on the desktop
  keyring, which is unavailable to a non-graphical session. It will work when run from
  inside the logged-in desktop, not over SSH.

## Recommended path

1. Open Firefox on the machine and log into Instagram once (remember-me).
2. Keep using `--cookies-from-browser firefox` — no credential file is ever written.

```bash
yt-dlp --cookies-from-browser firefox --simulate --print "%(title)s" "<reel-url>"
```

## Fallback path (exported cookies)

Only if Firefox is unavailable:

1. Export Netscape-format `cookies.txt` from a logged-in browser.
2. Save as `~/.hermes/cookies/instagram.txt`, `chmod 600`.
3. Reference the **path** in config; never copy it into the repository or artifacts.

```yaml
sources:
  reels:
    cookies_from_browser: firefox   # preferred
    cookies_file: /home/hardik/.hermes/cookies/instagram.txt  # fallback
```

## Expiry and failure behaviour

- Auth failure is detected as `empty media response` / `login required`, **not** as a
  network error.
- On detection the source is marked `quarantined` with reason `auth_expired`; the daemon
  does not retry it (retrying burns quota and can trip rate limits).
- Quarantine is visible in `status.json` and in the daily run report.

## Security notes

- `~/.hermes` is `700`, `.env` is `600` (verified 2026-11-02).
- Cookies grant account access: treat `cookies.txt` as a password. Never commit, never
  include in `derived/`, never log the value (log only "cookies loaded: N").
- `--cookies-from-browser` copies the cookie DB to a temp file; it must be cleaned up by
  the tool. Do not point `--cookies` at the live browser database.

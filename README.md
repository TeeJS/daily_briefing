# daily_briefing

A scheduled job that delivers a daily HTML email summarizing the things I want to start each day with. Designed so the same HTML can be served verbatim from `briefing.schmitzplex.com` (planned).

## What the briefing contains

Each morning at 6:00 AM Mountain Time:

- **Daily schedule** — today's calendar events across 6 of my 8 Google calendars (kids' calendars excluded).
- **Important emails** — last 24h of inbox, broadly pre-filtered by Gmail category, then LLM-triaged into *Action today* and *FYI*. Starred items always included.
- **Claude account usage** — current 5-hour window, weekly limits, weekly Sonnet limits, and extra-usage credits used / available. Pulled from the undocumented OAuth endpoint Claude Code itself uses.
- **Etsy outstanding orders** — unshipped receipts grouped by overdue / due-soon / other, with ship-by dates.
- **News digest** — 7 subsections, each curated by the LLM down to 3–5 "water cooler" items:
  1. World news
  2. US news
  3. Regional (Utah + Springville)
  4. NWPX (Northwest Pipe Infrastructure + subsidiaries: NWPX Geneva, NWPX Park, Boughton's Precast) — stock price, new SEC filings, press releases, news mentions
  5. ERP / precast software (SAP, Muka Development Group, Titan 3000)
  6. AI (high-level breakthroughs, new Claude features)
  7. LDS Church newsroom

## Architecture

- **Runtime**: ephemeral Docker container running on the main Unraid server (`noraid.schmitzplex.com`).
- **Schedule**: Unraid User Scripts plugin, cron `0 6 * * *` (America/Denver).
- **LLM**: local — calls the LiteLLM proxy on the other Unraid server (`lite.schmitzplex.com:4000`). LiteLLM routes to a llama.cpp backend. The Anthropic API is not called at runtime.
- **Image**: built by GitHub Actions on push to `main`, pushed to `ghcr.io/teejs/daily-briefing:latest`.
- **State** (secrets, OAuth tokens, daily archive, logs) lives on Unraid at `/mnt/user/appdata/daily_briefing/`, mounted into the container. Nothing stateful in the image.
- **Delivery**: HTML email via the Gmail API, sent from the user account to itself.
- **Archive**: every day's rendered HTML is written to `/mnt/user/appdata/daily_briefing/briefings/YYYY/MM/DD.html`. When `briefing.schmitzplex.com` is built, it serves this directory directly via the existing reverse proxy.

## Repo layout

```
.
├── briefing/                     # Python package
│   ├── run.py                    # entry point — `python -m briefing.run`
│   ├── config.py                 # env vars, paths
│   ├── secrets.py                # load/persist OAuth tokens
│   ├── render.py                 # Jinja2 HTML renderer
│   ├── send.py                   # Gmail API send
│   ├── sources/                  # one module per data source
│   │   ├── calendar.py
│   │   ├── email.py              # (stub for now)
│   │   ├── claude_usage.py       # (stub for now)
│   │   ├── etsy.py               # (stub for now)
│   │   └── news.py               # (stub for now)
│   └── templates/
│       └── briefing.html.j2
├── scripts/
│   └── bootstrap_google_oauth.py # one-time interactive auth
├── Dockerfile
├── pyproject.toml
└── .github/workflows/
    └── build-and-push.yml
```

## Status

Scaffolding + calendar section + email delivery are functional. The other four sources currently render placeholder blocks; they'll be filled in incrementally without breaking the running pipeline.

## Setup

These are one-time steps to bootstrap the deployment.

### 1. Google OAuth (Gmail send + Calendar read)

1. Create a Google Cloud project at https://console.cloud.google.com/.
2. Enable the Gmail API and the Google Calendar API.
3. Configure the OAuth consent screen (External, with your account as a test user).
4. Create OAuth client credentials — Desktop App type. Download the `client_secret.json`.
5. On the Unraid host, place it at `/mnt/user/appdata/daily_briefing/secrets/google_client_secret.json`.
6. Run the bootstrap script once from a machine with a browser:
   ```
   python scripts/bootstrap_google_oauth.py
   ```
   This opens a browser, runs the OAuth flow, and writes the resulting tokens to `secrets/google_tokens.json`. Refresh tokens persist; the briefing job refreshes silently from there on.

### 2. Unraid

- Create the directory tree `/mnt/user/appdata/daily_briefing/{secrets,briefings,logs}`.
- Place `google_client_secret.json` and `google_tokens.json` (from the bootstrap step above) in `secrets/`.
- Install the **User Scripts** plugin from Community Apps.
- Add a new script with cron schedule `0 6 * * *` and this body:
  ```bash
  #!/bin/bash
  docker pull ghcr.io/teejs/daily-briefing:latest
  docker run --rm \
    --name daily-briefing \
    -v /mnt/user/appdata/daily_briefing/secrets:/app/secrets \
    -v /mnt/user/appdata/daily_briefing/briefings:/app/briefings \
    -v /mnt/user/appdata/daily_briefing/logs:/app/logs \
    -e LLM_BASE_URL=http://lite.schmitzplex.com:4000/v1 \
    -e LLM_MODEL=<your-litellm-model-name> \
    -e TZ=America/Denver \
    -e ETSY_CLIENT_ID=<your-etsy-keystring> \
    ghcr.io/teejs/daily-briefing:latest
  ```

### 3. Anthropic OAuth (Claude usage section)

The undocumented `/api/oauth/usage` endpoint uses a PKCE flow against `claude.ai`. No app registration needed — we reuse the public client_id from the `trickv/hass-claude-usage` HA integration.

```
python scripts/bootstrap_anthropic_oauth.py
```

The script opens the authorize URL, you authorize in your browser, and the redirect lands at `console.anthropic.com` showing an authorization code. Paste it back into the script. Tokens are written to `secrets/anthropic_tokens.json` and refreshed silently thereafter.

**Rate-limit warning**: the API backs off aggressively (~24h lockout for both the briefing AND `/usage` in Claude Code itself). Never poll faster than 300s. The daily briefing hits it once/morning — well under the limit.

### 4. Etsy OAuth (outstanding orders section)

1. Register an app at https://www.etsy.com/developers/your-apps. Note the **API Keystring** (your `client_id`) and the **Callback URL** you register (HTTPS only; the page it points to doesn't have to actually exist — we just need the redirect URL to match).
2. Export both as env vars before running the bootstrap:
   ```
   set ETSY_CLIENT_ID=<your keystring>
   set ETSY_REDIRECT_URI=<your registered callback URL>
   ```
   (On Linux/macOS: `export …=…`)
3. Run the bootstrap:
   ```
   python scripts/bootstrap_etsy_oauth.py
   ```
   It opens the Etsy authorize URL. After you authorize, your browser redirects to your callback URL (the page may 404 — that's fine). Copy the **full URL** from your address bar and paste it back into the script. It extracts the code, exchanges for tokens, looks up your `shop_id`, and writes everything to `secrets/etsy_tokens.json`.
4. On Unraid, the same `ETSY_CLIENT_ID` env var must also be set in the User Scripts `docker run` command (used during refresh). `ETSY_REDIRECT_URI` is only needed at bootstrap time, not at runtime.

### 5. (Later) News digest data sources

Most news subsections use public RSS feeds (no auth). The NWPX section will additionally need a free **Finnhub API key** for stock quotes — register at https://finnhub.io/ and set `FINNHUB_API_KEY` in the env when that section is wired up.

## Local development

```
# create + activate a venv (Windows)
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# dry-run (renders to ./briefings/YYYY/MM/DD.html, skips send)
python -m briefing.run --dry-run
```

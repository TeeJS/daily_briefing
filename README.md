# daily_briefing

A scheduled job that writes a daily HTML file summarizing the things I want to start each day with. The same HTML is served from `briefing.schmitzplex.com` — that's the user-facing distribution channel. The job has zero send/modify authority on any account; Google OAuth scopes are read-only.

## What the briefing contains

Each morning at 6:00 AM Mountain Time, in this layout order. No LLM is involved: every section is a direct query or feed, and each one fails on its own, so a broken section shows an error block while the rest of the page still ships.

- **Today's schedule** — today's events from the Google calendars listed in `INCLUDED_CALENDARS` (`briefing/config.py`): all-day events first, then timed ones. When the job runs after noon, tomorrow's events are added.
- **Meeting prep** — links to that day's meeting-prep briefs, which a separate overnight job writes. Hidden when there are none. Action items on a brief can be ticked off with the "Mark complete" button (see Setup → 6).
- **Freshservice — unassigned** — tickets with no agent in the Titan Admins and SAP Basis Admins groups, created in the last 6 months. It mirrors the kanban board's Unassigned column.
- **Etsy orders to ship** — unshipped paid receipts grouped as overdue, due within 3 days, and other, with ship-by dates.
- **Claude usage** — the 5-hour session, 7-day (all models) and 7-day Sonnet limits, plus extra-usage dollars when that is enabled. Pulled from the undocumented OAuth endpoint Claude Code itself uses.
- **Codex usage** — the Codex (ChatGPT) rate-limit windows, labelled from the window lengths the endpoint returns (about 5 hours and weekly).
- **News** — seven RSS-fed subsections, newest first and each capped, with no LLM curation:
  1. World
  2. United States
  3. NWPX Infrastructure — press releases and the company blog, last 15 days
  4. SAP — a Google News search for SAP with stock-promotion and off-topic sources filtered out
  5. Utah / Local — last 7 days
  6. LDS Church Newsroom
  7. AI — six feeds, last 2 days
- **Events this week** — a weekly feed of local movies and venue events.
- **Work email — unread** — unread Focused-inbox messages from the last 7 days in the work Outlook. Unraid can't reach Outlook, so a Windows scheduled task (`scripts/prefetch_outlook.py`, 5:45 AM) writes them to the archive share first. A placeholder shows if that file is missing or more than 24 hours old.
- **Unread / starred email** — Gmail: unread Primary-tab threads from the last 7 days plus starred inbox threads from the last 30 days, oldest first. No triage or classification.

## Architecture

- **Runtime**: ephemeral Docker container running on the main Unraid server (`noraid.schmitzplex.com`).
- **Schedule**: Unraid User Scripts plugin, cron `0 6 * * *` (America/Denver).
- **LLM**: none at runtime (dropped 2026-05-19). `briefing/llm.py` is still in the repo but nothing calls it, and `LLM_BASE_URL` / `LLM_MODEL` are not set. The Anthropic API is not called either.
- **Image**: built by GitHub Actions on push to `main`, pushed to `ghcr.io/teejs/daily_briefing:latest`.
- **State** lives on Unraid and is mounted into the container; nothing stateful in the image. Secrets, OAuth tokens and logs are under `/mnt/user/appdata/daily_briefing/`; the daily archive is `/mnt/user/data/websites/briefing/`.
- **Delivery**: HTML file written to `/mnt/user/data/websites/briefing/YYYY/MM/DD.html`. An always-on `nginx:alpine` container (`briefing_web`, port 8181) serves that directory, and NPM Plus publishes it at `briefing.schmitzplex.com` behind Authelia. No email is sent; the briefing's Google OAuth grant is read-only (calendar + inbox view), with no send authority.

## Repo layout

```
.
├── briefing/                     # Python package
│   ├── run.py                    # entry point — `python -m briefing.run`
│   ├── config.py                 # env vars, paths
│   ├── secrets.py                # load/persist OAuth tokens
│   ├── render.py                 # Jinja2 HTML renderer
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

Every section listed above is live. A source that fails to fetch renders an error block (with the command that fixes it) instead of breaking the page. No email is sent; the HTML page is the only output.

## Setup

These are one-time steps to bootstrap the deployment.

### 1. Google OAuth (Calendar read + Gmail read)

Both scopes are read-only. The briefing job has no send/modify authority on the Google account.

1. Create a Google Cloud project at https://console.cloud.google.com/. No billing account is needed; both APIs are free.
2. Enable the **Google Calendar API** and the **Gmail API** (both must be enabled or Google silently drops the scope during consent).
3. **APIs & Services → OAuth consent screen** (opens Google Auth Platform) → **Get started**: app name, support email, **External**, contact email.
4. **Branding**: set the home page and privacy policy links to `https://briefing.schmitzplex.com` and add `schmitzplex.com` as an authorized domain (Google won't publish without them). Leave the logo blank; uploading one triggers Google's verification review. Skip Data Access and test users.
5. **Audience → Publish app**. Status must read *In production*: in *Testing*, Google expires the refresh token after 7 days and the briefing breaks weekly.
6. **Clients → Create client → Desktop app**. Click **Download JSON** in the creation pop-up; the secret is never shown again.
7. On the Unraid host, place it at `/mnt/user/appdata/daily_briefing/secrets/google_client_secret.json`.
8. Run the bootstrap script once from a machine with a browser:
   ```
   python scripts/bootstrap_google_oauth.py
   ```
   This opens a browser, runs the OAuth flow, and writes the resulting tokens to `secrets/google_tokens.json`. On the "Google hasn't verified this app" screen, click **Advanced → Go to … (unsafe)** (expected for a personal app), then tick **both** permission checkboxes; leaving one unticked makes the script fail. Refresh tokens persist; the briefing job refreshes silently from there on.

### 2. Unraid

- Create `/mnt/user/appdata/daily_briefing/{secrets,logs}` for tokens and logs, and `/mnt/user/data/websites/briefing/` for the archive that `briefing_web` serves.
- Place `google_client_secret.json` and `google_tokens.json` (from the bootstrap step above) in `secrets/`.
- Install the **User Scripts** plugin from Community Apps.
- Add a new script with cron schedule `0 6 * * *` and this body:
  ```bash
  #!/bin/bash
  docker pull ghcr.io/teejs/daily_briefing:latest
  docker run --rm \
    --name daily_briefing \
    -v /mnt/user/appdata/daily_briefing/secrets:/app/secrets \
    -v /mnt/user/data/websites/briefing:/app/briefings \
    -v /mnt/user/appdata/daily_briefing/logs:/app/logs \
    -v /mnt/user/data/meetings/meeting_prep:/app/meeting_prep:ro \
    -e EVENTS_URL=http://192.168.1.25:8087/events.json \
    -e TZ=America/Denver \
    -e ETSY_CLIENT_ID=<your-etsy-keystring> \
    -e ETSY_CLIENT_SECRET=<your-etsy-shared-secret> \
    -e FRESHSERVICE_DOMAIN=<your-domain>.freshservice.com \
    -e FRESHSERVICE_APIKEY=<your-freshservice-api-key> \
    ghcr.io/teejs/daily_briefing:latest
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
4. On Unraid, the same `ETSY_CLIENT_ID` and `ETSY_CLIENT_SECRET` env vars must also be set in the User Scripts `docker run` command (both are used during refresh). `ETSY_REDIRECT_URI` is only needed at bootstrap time, not at runtime.

### 5. (Later) News digest data sources

Most news subsections use public RSS feeds (no auth). The NWPX section will additionally need a free **Finnhub API key** for stock quotes — register at https://finnhub.io/ and set `FINNHUB_API_KEY` in the env when that section is wired up.

### 6. "Mark complete" service (meeting-prep briefs)

A small second container (`ghcr.io/teejs/daily_briefing-actions:latest`, built from `Dockerfile.actions`) lets you tick items off a meeting-prep brief. Ticked items are recorded in `done.json`, so the meeting-prep skill leaves them out of later briefs and lists them once under "Completed since last meeting"; if the row has a kanban card, the card moves to Done. Source: `briefing/actions.py` (service) and `briefing/templates/done.js` (page script, served at `/api/done.js`).

| Setting | Value | Where it comes from |
|---|---|---|
| Port | `8183` (env `BRIEFING_ACTIONS_PORT`) | Checked free on the host 2026-11-12 (8182 is Tautulli). Re-check with `ss -tlnp` before changing it: host-network containers don't show in `docker ps` |
| Volume `/app/state` (RW) | `/mnt/user/data/meetings/meeting_prep/_state` | Inside the folder the nightly job saves briefs to (`M:\meetings\meeting_prep\_state\done.json` on Windows); the skill reads it from there |
| `KANBAN_URL` | `http://192.168.1.25:17808` | The kanban app's own port, from golang-kanban's `docker-compose.yml` |
| `KANBAN_API_KEY` | your kanban API key (mask it) | The key kanban's `X-API-Key` login accepts — the same one the `kanban-mcp` container uses |

Without the two kanban variables the list still works; ticking a card-backed row just reports "kanban is not connected". NPM Plus: on the `briefing.schmitzplex.com` proxy host add a custom location `/api/` forwarding to `http://192.168.1.25:8183` (the host is protected by Authelia, not basic auth; after adding the location, confirm an unauthenticated request to `/api/done` is redirected to the login instead of answered). State-changing requests must carry an `X-Briefing-Action: 1` header and a same-host `Origin`, which is what blocks cross-site clicks.

## Local development

```
# create + activate a venv (Windows)
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# run once — writes ./briefings/YYYY/MM/DD.html
python -m briefing.run
```

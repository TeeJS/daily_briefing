# HANDOFF

What's done, what's next, and exactly what to do to get the briefing running. Aimed at the person (or future-self) picking this up cold.

## Current state

**Merged to main**: PR #1 (commit `f901d17`) — 25 files, full scaffold + 4 of 5 data sources fully implemented + news v1.

**GitHub Actions**: builds the Docker image on every push to `main`, pushes to `ghcr.io/teejs/daily-briefing:latest`. First image is published.

**Not yet running**: the briefing hasn't been triggered in production — needs the Unraid setup below.

## Section completeness

| Section | State | Notes |
|---|---|---|
| 📅 Calendar | Full | Pulls from 6 included calendars; kids' calendars (`jonah@`, `noah@`) excluded |
| 📧 Important emails | Full | Broad Gmail pre-filter + LLM triage into Action today / FYI; starred bypasses filter |
| 🤖 Claude usage | Full | Undocumented `/api/oauth/usage` endpoint |
| 📦 Etsy orders | Full | Unshipped paid receipts, bucketed by overdue / due-soon / other |
| 📰 News v1 | Partial | 3 of 7 subsections live (World, US, LDS Newsroom). 4 sub-stubs: Utah/Springville, NWPX, ERP/SAP/Muka/Titan, AI |

## To get it running in production

### Step 1 — Make the ghcr.io package public (or set up `docker login`)

Repo is private, which means the package is too by default. The image contains zero secrets, so making just the package public is the simplest path:

1. https://github.com/users/TeeJS/packages/container/daily-briefing/settings
2. Danger Zone → Change package visibility → Public

Alternative: create a PAT with `read:packages` scope and `docker login ghcr.io -u TeeJS --password-stdin` on noraid.

### Step 2 — Create the appdata tree on noraid

```bash
mkdir -p /mnt/user/appdata/daily_briefing/{secrets,briefings,logs}
chmod 700 /mnt/user/appdata/daily_briefing/secrets
```

### Step 3 — Bootstrap the three OAuth integrations

Run these from a desktop with a browser. On this machine the repo lives at `D:\Github\daily_briefing`. First-time venv setup:

```powershell
cd D:\Github\daily_briefing
python -m venv .venv
.venv\Scripts\activate
pip install -e .
$env:BRIEFING_SECRETS_DIR = ".\local_secrets"
mkdir local_secrets -ErrorAction SilentlyContinue
```

(On subsequent runs, skip the `python -m venv` and `pip install -e .` lines — just `cd`, `activate`, set env vars.)

**3a. Google (Gmail send + Calendar read)**
1. https://console.cloud.google.com/ — create or reuse a project
2. Enable Gmail API + Google Calendar API
3. OAuth consent screen → External, add yourself as a test user
4. Credentials → OAuth client ID → **Desktop app**
5. Download the JSON, save as `local_secrets/google_client_secret.json`
6. `python scripts/bootstrap_google_oauth.py`
7. Browser opens, you authorize, control returns. `local_secrets/google_tokens.json` created.

**3b. Anthropic (Claude usage)**

No app registration needed (uses public client_id).

```powershell
python scripts/bootstrap_anthropic_oauth.py
```

Browser opens claude.ai authorize page. After authorizing, redirect lands at console.anthropic.com showing an auth code. Paste it back. `local_secrets/anthropic_tokens.json` created.

**3c. Etsy (orders)**
1. https://www.etsy.com/developers/your-apps — register an app. Note the **API Keystring** and a **Callback URL** (must be HTTPS; the page doesn't need to actually exist)
2. Set env vars and run:
   ```powershell
   $env:ETSY_CLIENT_ID = "<your keystring>"
   $env:ETSY_REDIRECT_URI = "<your callback URL>"
   python scripts/bootstrap_etsy_oauth.py
   ```
3. Browser opens, you authorize, browser redirects to your callback URL (probably 404s — fine). Copy the **full URL** from address bar, paste it back. `local_secrets/etsy_tokens.json` created (includes the looked-up `shop_id`).

### Step 4 — Move secrets to noraid

Copy these four files from `local_secrets/` on your desktop to `/mnt/user/appdata/daily_briefing/secrets/` on noraid:
- `google_client_secret.json`
- `google_tokens.json`
- `anthropic_tokens.json`
- `etsy_tokens.json`

Use SMB / scp / Unraid Shares UI / whatever's convenient.

### Step 5 — Install Unraid User Scripts plugin

Apps tab → search "User Scripts" → install.

### Step 6 — Add the briefing script

Settings → User Scripts → Add New Script → name `daily_briefing`. Body:

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

Replace `<your-litellm-model-name>` with whatever LiteLLM advertises and `<your-etsy-keystring>` with the same value used in step 3c.

Schedule: Custom → `0 6 * * *` (6 AM MT, matches `TZ=America/Denver`).

### Step 7 — Manual test

Click **Run Script**. Wait ~30 seconds. Verify:
- `/mnt/user/appdata/daily_briefing/logs/briefing-2026-05.log` has a "sent email" line
- `/mnt/user/appdata/daily_briefing/briefings/2026/05/DD.html` exists
- Inbox at teejschmitz@gmail.com has a "Daily Briefing — …" email

If any section failed, its error block in the email tells you which bootstrap script to re-run.

## What still needs to be built

In rough priority order:

### Near-term

- **News section 3 — Utah / Springville**: discover a working RSS feed (KSL.com, Daily Herald, or Google News geo). Wire into `briefing/sources/news.py`.
- **News section 7 — Anthropic feed for AI subsection**: try `https://www.anthropic.com/news/feed` or similar. If no feed, scrape the news page.
- **News section 6 — AI**: TechCrunch AI RSS (`https://techcrunch.com/category/artificial-intelligence/feed/`).
- **News section 5 — ERP / SAP**: `https://news.sap.com/feed/` (verify URL). Muka/Titan: defer until web-search integration.

### Bigger pieces

- **NWPX subsection** (section 4): multi-source.
  - Stock: Finnhub free tier (`FINNHUB_API_KEY` env). Quote endpoint: `https://finnhub.io/api/v1/quote?symbol=NWPX&token=<key>`.
  - SEC filings: EDGAR JSON API at `https://data.sec.gov/submissions/CIK<padded-cik>.json` (no key). NWPX CIK lookup needed once.
  - Press releases: discover RSS at `investor.nwpx.com` or scrape.
  - News mentions: Google News search RSS with quoted query for NWPX + subsidiary brand names.

- **LLM-based news curation**: currently each subsection just takes the top N items from its feed verbatim. A future pass should have the LLM rank/dedupe across all subsections (e.g., a single story that's both AI and ERP shouldn't appear twice; "water cooler" judgment).

- **briefing.schmitzplex.com static site**: serve `/mnt/user/appdata/daily_briefing/briefings/` directly via the existing reverse proxy on Unraid. Needs an `index.html` generator that lists archived briefings chronologically.

### Polish

- Mobile reflow for narrow screens (the 2-column layout currently scales rather than stacks on phones — Gmail mobile handles it, but reflow would be nicer)
- Per-section render error isolation (currently a single bad section's template can crash the whole render, since renderer-side errors aren't isolated like fetch errors are)
- Tests around the orchestrator's error-isolation and the template rendering for each section status

## Pending decisions

- **ghcr.io package visibility** (Step 1 above) — user needs to choose public vs. authenticated pull
- **`LLM_MODEL` name** — depends on what LiteLLM is configured with

## Key file pointers for navigation

| Need to | Look at |
|---|---|
| Add a new section | New module in `briefing/sources/`, wire into `briefing/run.py`, add a macro + block in `briefing/templates/briefing.html.j2`, render call in `briefing/render.py` |
| Add a new OAuth integration | Pattern in `briefing/etsy_auth.py` + `scripts/bootstrap_etsy_oauth.py` (PKCE) or `briefing/secrets.py` + `scripts/bootstrap_google_oauth.py` (InstalledAppFlow) |
| Change calendar inclusion list | `INCLUDED_CALENDARS` tuple in `briefing/config.py` |
| Change email filter behavior | `CANDIDATE_QUERY` constant + `TRIAGE_SYSTEM` prompt in `briefing/sources/email.py` |
| Change LLM endpoint | `LLM_BASE_URL` env var; backend defaults in `briefing/config.py` |
| Change archive path / layout | `_archive_path()` in `briefing/run.py` |
| Change subject line format | `render()` in `briefing/render.py` |

## Repo / infra summary

- **Repo**: https://github.com/TeeJS/daily_briefing (private)
- **Image**: `ghcr.io/teejs/daily-briefing:latest` (visibility TBD per Step 1)
- **Build**: GitHub Actions on push to `main` (`.github/workflows/build-and-push.yml`)
- **Runtime host**: `noraid.schmitzplex.com` (192.168.1.25) — main Unraid box
- **LLM host**: `oc.schmitzplex.com` (192.168.1.95) — second Unraid box, runs LiteLLM at `:4000`, llama.cpp at `:8080`
- **Schedule**: Unraid User Scripts, cron `0 6 * * *` America/Denver
- **State on Unraid**: `/mnt/user/appdata/daily_briefing/{secrets,briefings,logs}`
- **Delivery**: HTML email via Gmail API, sent from teejschmitz@gmail.com to itself
- **Archive**: `briefings/YYYY/MM/DD.html` — future source for `briefing.schmitzplex.com`

For architecture context not in CLAUDE.md, see the memory files at `C:\Users\tschmitz\.claude\projects\D--Github-daily-briefing\memory\` (local to this Windows desktop).

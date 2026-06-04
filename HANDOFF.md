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
| 📧 Important emails | Full | Broad Gmail pre-filter (`gmail.readonly` scope, read-only) + LLM triage into Action today / FYI; starred bypasses filter |
| 🤖 Claude usage | Full | Undocumented `/api/oauth/usage` endpoint |
| 📦 Etsy orders | Full | Unshipped paid receipts, bucketed by overdue / due-soon / other |
| 📰 News v1 | Partial | 3 of 7 subsections live (World, US, LDS Newsroom). 4 sub-stubs: Utah/Springville, NWPX, ERP/SAP/Muka/Titan, AI |

**Delivery**: HTML file written to `/mnt/user/appdata/daily_briefing/briefings/YYYY/MM/DD.html`. No email is sent. The Google OAuth grant is read-only (calendar + inbox view) with no send/modify authority.

## To get it running in production

### Step 1 — ghcr.io package visibility ✅ (done)

The `ghcr.io/teejs/daily_briefing` package is public — noraid can pull it anonymously.

Verify with `curl -sI https://ghcr.io/v2/teejs/daily_briefing/manifests/latest -H "Authorization: Bearer $(curl -s 'https://ghcr.io/token?service=ghcr.io&scope=repository:teejs/daily_briefing:pull' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')"` → expect HTTP 200. (The initial unauthenticated GET returns 401 by OCI convention; that's the bearer-token dance, not a private-package signal.)

If the package ever needs to go private again, the alternative is a PAT with `read:packages` and `docker login ghcr.io -u TeeJS --password-stdin` on noraid.

### Step 2 — Create the appdata tree on noraid

```bash
mkdir -p /mnt/user/appdata/daily_briefing/{secrets,briefings,logs,prompts}
chmod 700 /mnt/user/appdata/daily_briefing/secrets
```

The `prompts/` directory is optional but recommended — drop tunable prompt files (currently just `email_triage.txt`) here and the container will read them at runtime, no rebuild needed.

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

**3a. Google (Calendar read + Gmail read — both read-only)**
1. https://console.cloud.google.com/ — create or reuse a project
2. Enable **Google Calendar API** and **Gmail API** (both must be enabled or Google silently drops the scope during consent)
3. OAuth consent screen → External, add yourself as a test user
4. Credentials → OAuth client ID → **Desktop app**
5. Download the JSON, save as `local_secrets/google_client_secret.json`
6. `python scripts/bootstrap_google_oauth.py`
7. Browser opens, you authorize (the consent screen will list two read-only scopes; no send/modify). `local_secrets/google_tokens.json` created.

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
docker pull ghcr.io/teejs/daily_briefing:latest
docker run --rm \
  --name daily_briefing \
  -v /mnt/user/appdata/daily_briefing/secrets:/app/secrets \
  -v /mnt/user/appdata/daily_briefing/briefings:/app/briefings \
  -v /mnt/user/appdata/daily_briefing/logs:/app/logs \
  -v /mnt/user/appdata/daily_briefing/prompts:/app/prompts \
  -e LLM_BASE_URL=http://lite.schmitzplex.com:4000/v1 \
  -e LLM_MODEL=<your-litellm-model-name> \
  -e TZ=America/Denver \
  -e ETSY_CLIENT_ID=<your-etsy-keystring> \
  ghcr.io/teejs/daily_briefing:latest
```

Replace `<your-litellm-model-name>` with whatever LiteLLM advertises and `<your-etsy-keystring>` with the same value used in step 3c. (The image and container name use an underscore, matching the GitHub repo name and the published ghcr.io package; an earlier doc draft used a hyphen — corrected.)

Schedule: Custom → `0 6 * * *` (6 AM MT, matches `TZ=America/Denver`).

### Step 7 — Manual test

Click **Run Script**. Wait ~30 seconds. Verify:
- `/mnt/user/appdata/daily_briefing/logs/briefing-2026-05.log` has a "wrote briefing to …" line
- `/mnt/user/appdata/daily_briefing/briefings/2026/05/DD.html` exists
- Open that file in a browser (or hit it via `briefing.schmitzplex.com` once the reverse proxy is wired up) — every section renders, no error blocks

If any section failed, its error block in the rendered HTML tells you which bootstrap script to re-run.

## Outlook pre-fetch — Windows Task Scheduler setup

The work-email section is fed by `scripts/prefetch_outlook.py`, which runs on the
Windows machine at 5:45 AM (15 minutes before the Unraid briefing container fires).
It requires Outlook Desktop (Classic / OUTLOOK.EXE) to be running — which it is 24/7.

### One-time setup

**1. Install pywin32 in the daily_briefing venv (Windows only):**

```powershell
cd D:\Github\daily_briefing
.venv\Scripts\activate
pip install pywin32
```

**2. Create the output directory on the share:**

The script creates this automatically on first run, but you can pre-create it:
```
\\192.168.1.25\data\websites\briefing\outlook\
```
(On Unraid this is `/mnt/user/data/websites/briefing/outlook/`)

**3. Test the script manually first:**

```powershell
cd D:\Github\daily_briefing
.venv\Scripts\activate
python scripts\prefetch_outlook.py
```

Expected output:
```
Fetching unread Outlook messages — last 7 days, max 50 …
  Found N unread message(s).
  Wrote cache → \\192.168.1.25\data\websites\briefing\outlook\outlook_cache.json
```

**4. Create the Task Scheduler job:**

Open Task Scheduler → Create Task (not Basic Task):

- **General tab:**
  - Name: `Daily Briefing — Prefetch Outlook`
  - Run whether user is logged on or not: ✓
  - Run with highest privileges: ✓ (needed to access the UNC path reliably)

- **Triggers tab:** New → Daily, Start: 5:45 AM, Recur every 1 day

- **Actions tab:** New → Start a program
  - Program/script: `D:\Github\daily_briefing\.venv\Scripts\python.exe`
  - Add arguments: `D:\Github\daily_briefing\scripts\prefetch_outlook.py`
  - Start in: `D:\Github\daily_briefing`

- **Conditions tab:** Uncheck "Start the task only if the computer is on AC power"

- **Settings tab:** If the task is already running: `Do not start a new instance`

**5. Verify end-to-end:**

After the Task Scheduler job runs, check:
- `\\192.168.1.25\data\websites\briefing\outlook\outlook_cache.json` exists and has today's timestamp
- Next morning's briefing HTML shows the Work Email section with real data

### Graceful degradation

If the cache file is missing or older than 24 hours, `briefing/sources/outlook.py`
returns `status="stub"` and the template shows a placeholder — the briefing still
ships normally. No error block appears unless the file is present but unreadable.

---

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

- Mobile reflow for narrow screens (the 2-column layout currently scales rather than stacks on phones — fine in modern browsers, but reflow would be nicer)
- Per-section render error isolation (currently a single bad section's template can crash the whole render, since renderer-side errors aren't isolated like fetch errors are)
- Tests around the orchestrator's error-isolation and the template rendering for each section status
- Reverse-proxy entry for `briefing.schmitzplex.com` → `/mnt/user/appdata/daily_briefing/briefings/` on noraid + a small chronological `index.html` generator

## Pending decisions

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

- **Repo**: https://github.com/TeeJS/daily_briefing (public)
- **Image**: `ghcr.io/teejs/daily_briefing:latest` (public package)
- **Build**: GitHub Actions on push to `main` (`.github/workflows/build-and-push.yml`)
- **Runtime host**: `noraid.schmitzplex.com` (192.168.1.25) — main Unraid box
- **LLM host**: `oc.schmitzplex.com` (192.168.1.95) — second Unraid box, runs LiteLLM at `:4000`, llama.cpp at `:8080`
- **Schedule**: Unraid User Scripts, cron `0 6 * * *` America/Denver
- **State on Unraid**: `/mnt/user/appdata/daily_briefing/{secrets,briefings,logs}`
- **Delivery**: static HTML file written to `briefings/YYYY/MM/DD.html` on Unraid. No email sent. Google OAuth grant is read-only (calendar + inbox view).
- **Archive / consumption**: `briefings/YYYY/MM/DD.html` served by the existing reverse proxy at `briefing.schmitzplex.com` (reverse-proxy entry still to be wired up).

For architecture context not in CLAUDE.md, see the memory files at `C:\Users\tschmitz\.claude\projects\D--Github-daily-briefing\memory\` (local to this Windows desktop).

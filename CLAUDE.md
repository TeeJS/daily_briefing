# CLAUDE.md

Context for future Claude Code sessions working on this repo. Read this first.

## What this is

A scheduled daily briefing rendered as a static HTML file. Runs in a Docker container on Unraid (`noraid.schmitzplex.com`) at 6 AM MT, pulls data from 5 sources, and writes one self-contained HTML document to `/mnt/user/data/websites/briefing/YYYY/MM/DD.html`. An always-on `nginx:alpine` container serves that directory on port 8181; NPMPlus proxies `briefing.schmitzplex.com` to it with basic auth. **No email is sent** — the Google OAuth grant is read-only (calendar + inbox view) and the job has no send/modify authority anywhere.

User: TJ Schmitz (teejschmitz@gmail.com), running on Windows 11.

## Hosting topology

Three components on noraid:

1. **Daily generator** (this repo's container) — runs once/day via Unraid User Scripts cron at 6 AM MT, writes today's HTML + updates `index.html` / `today.html` / `robots.txt`, exits.
2. **Static webserver** — `nginx:alpine` container, always on, mounts `/mnt/user/data/websites/briefing` read-only at `/usr/share/nginx/html`, listens on host port 8181.
3. **NPMPlus** — terminates HTTPS for `briefing.schmitzplex.com`, applies basic auth, forwards to `localhost:8181`.

Generated outputs in the briefings volume:
- `YYYY/MM/DD.html` — permanent dated archive
- `today.html` — latest pointer, overwritten each morning
- `index.html` — archive listing grouped by year → month (newest first)
- `robots.txt` — `Disallow: /` (defense-in-depth alongside basic auth)

## Repo layout

```
briefing/                  Python package (the actual code)
  run.py                   Entry point: python -m briefing.run [--date YYYY-MM-DD]
  config.py                Env vars, paths, OAuth constants, calendar inclusion list
  secrets.py               Google OAuth credentials load/save
  anthropic_auth.py        Anthropic OAuth tokens (load + auto-refresh)
  etsy_auth.py             Etsy OAuth tokens (load + auto-refresh)
  llm.py                   OpenAI SDK wrapper pointed at the local LiteLLM proxy
  render.py                Jinja2 HTML renderer
  sources/                 One module per data source, each exposes fetch() -> SectionResult
    calendar.py            Full
    email.py               Full (LLM triage)
    claude_usage.py        Full
    etsy.py                Full
    news.py                v1: 3 of 7 subsections via RSS; 4 sub-stubs
  templates/
    briefing.html.j2       Per-day briefing HTML (responsive, dark mode)
    index.html.j2          Archive index (year/month groups, newest first)

scripts/
  bootstrap_google_oauth.py     One-time browser auth
  bootstrap_anthropic_oauth.py  One-time browser auth (PKCE)
  bootstrap_etsy_oauth.py       One-time browser auth (PKCE)

Dockerfile                 python:3.12-slim base
.github/workflows/build-and-push.yml   Builds + pushes to ghcr.io/teejs/daily_briefing:latest on push to main
```

## Data flow

`run.py` orchestrates: `_gather_sections()` calls each source's `fetch()`, wraps each call in try/except so one bad source can't break the briefing — failed sources become `{"status": "error", "error": str(exc)}` and render as an actionable error block in the template (with the exact bootstrap command to fix).

Each `fetch()` returns a dict with a `status` field: `"ready"` | `"stub"` | `"error"`. The template handles all three branches per section.

After gathering: `render.render(sections, today)` produces `(subject, html)` — the subject is embedded in the HTML `<title>` and otherwise unused. The HTML is written to the archive path (`/YYYY/MM/DD.html`), copied to `/today.html`, and `render.render_index()` walks the briefings dir to regenerate `/index.html`. `/robots.txt` is also rewritten each run (idempotent). The nginx container serves the whole directory at `briefing.schmitzplex.com`.

## OAuth: three bootstraps, one pattern

All three (Google, Anthropic, Etsy) follow the same model:
- One-time script run from a desktop with a browser
- Browser opens, user authorizes, code (or full redirect URL) gets pasted back into the script
- Tokens written to `SECRETS_DIR` (default `/app/secrets` in container; override `BRIEFING_SECRETS_DIR` for local dev)
- Refresh tokens **rotate** on every refresh; the source's auth module writes the rotated tokens back to disk
- The briefing job needs `secrets/` mounted **read-write** because of this rotation

Anthropic uses the public client_id from the `trickv/hass-claude-usage` HA integration. Etsy and Google need user-registered OAuth apps (their client_id / keystring becomes runtime env: `ETSY_CLIENT_ID`; Google's `client_secret.json` lives in `secrets/`).

**Google scopes are read-only**: `calendar.readonly` (for today's events) and `gmail.readonly` (for the Important Emails section's inbox triage). The job has no send/modify authority on the Google account. If the Gmail API is not enabled in the GCP project, Google silently drops `gmail.readonly` from the consent response — make sure both APIs are enabled before running the bootstrap.

## LLM access

**LLM has been dropped (2026-05-19).** `LLM_BASE_URL` and `LLM_MODEL` are dead env vars — do not add them to the Unraid User Scripts run command. `briefing/llm.py` and its callers remain in the codebase but are unused at runtime.

## Container conventions

Image contains only Python + deps. **No state** in the image. All state lives in volume mounts:
- `/app/secrets` (RW) — OAuth tokens, client secrets
- `/app/briefings` (RW) — daily HTML archive
- `/app/logs` (RW) — rotating logs

Container is **ephemeral** — `docker run --rm` once per day, exits when done.

Env vars at runtime: `TZ` (defaults `America/Denver`), `ETSY_CLIENT_ID`, `ETSY_CLIENT_SECRET` (both needed during Etsy token refresh), `FRESHSERVICE_DOMAIN`, `FRESHSERVICE_APIKEY`. **`LLM_BASE_URL` and `LLM_MODEL` are dropped — do not include them.**

## Adding a new section — checklist

Every new source requires changes in **four** places. Missing any one causes a silent stub or an UndefinedError at render time:

1. `briefing/sources/<name>.py` — `fetch() -> SectionResult`
2. `briefing/run.py` — import + entry in `sources` dict
3. **`briefing/render.py`** — add `<name>=sections.get("<name>", {"status": "stub"})` to `template.render()` ← easy to forget
4. `briefing/templates/briefing.html.j2` — macro + call site in layout

## Known gotchas

- **Jinja2 + `dict.items`** — never use `items` as a key on a dict passed to a template; `obj.items` returns the dict method, not the value. Use `entries` or any other name. This bit us on news.
- **Windows time formatting** — `%-d` / `%-I` not supported on Windows. Use `%d` / `%I` then `.lstrip("0")` or `.replace(" 0", " ")`. Already done throughout.
- **`tzdata` package required** — Windows + minimal Linux images lack the IANA tz db. Listed as a runtime dep in pyproject.
- **Etsy receipt ship-by date** lives on `transaction.expected_ship_date` (line item), not the receipt. Receipt-level ship-by = `min(expected_ship_date)` across transactions.
- **Etsy access token format** — `<user_id>.<random>`. We extract `user_id` by splitting on `.` so we don't need extra OAuth scopes to call `getMe`.
- **Etsy `x-api-key` header** — must be `keystring:secret` (colon-separated), NOT just the keystring. Etsy enforced this Feb 9, 2026. Applies to all API calls (not the OAuth token endpoint). Computed as `ETSY_API_KEY = f"{ETSY_CLIENT_ID}:{ETSY_CLIENT_SECRET}"` in `config.py`. Both env vars required at runtime.
- **Etsy status strings are title-cased** — the API returns `"Paid"`, `"Canceled"`, `"Completed"`, not lowercase. Always compare with `.lower()`. Active unshipped orders have `status="Paid"`; `status="open"` means unpaid/pending, not active.
- **Anthropic `/api/oauth/usage` rate limit** — ~24h backoff if hit too fast. Minimum 300s. The daily briefing is well under, but never put it on a fast retry loop.

## Memory files (deeper context)

Architectural decisions and trade-offs are documented in this user's local memory:
`C:\Users\tschmitz\.claude\projects\D--Github-daily-briefing\memory\`

Entries cover: calendar inclusion list, email filter design, Claude usage API reverse-engineering, Etsy approach (API v3 direct, not third-party MCPs), news subsection sources, delivery channel choice, deployment topology.

These are local to this laptop — not in the repo. If you're working on this in a fresh environment, this CLAUDE.md is your starting point.

## Local development

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .

# Run with local paths — writes the HTML to .\preview\briefings\YYYY\MM\DD.html
$env:BRIEFING_SECRETS_DIR = ".\preview\secrets"
$env:BRIEFING_ARCHIVE_DIR = ".\preview\briefings"
$env:BRIEFING_LOGS_DIR = ".\preview\logs"
# Point at the real meeting-prep share to exercise the Meeting Prep section
# (files live under YYYY\MM\DD\; use --date to hit a day that has one).
$env:BRIEFING_MEETING_PREP_DIR = "M:\media\meetings\meeting_prep"
python -m briefing.run
```

`preview/` is gitignored. Without OAuth tokens, sources fail gracefully into error blocks — useful for template/rendering work. Open the resulting HTML file in any browser.

## Conventions

- Inline CSS in the template (originally Gmail-safe, kept for self-contained HTML). CSS variables drive light/dark mode; a `<style>` block in `<head>` defines the palette and responsive grid (640px breakpoint). System font stack. 720px max content width.
- Section macros in the template are pure: data in, HTML out.
- `:visited` rules MUST use hard-coded color literals, not `var()` — Chromium blocks CSS variable resolution inside `:visited` as anti-history-sniffing. (Chrome 136+ also partitions `:visited` by top-level site, so `file://` won't show visited styling at all — only `https://briefing.schmitzplex.com` exhibits the expected behavior.)
- No tests yet. If logic gets complex enough that a regression would be hard to spot, add them — but most of this is glue code where a smoke test (`--dry-run`) catches breakage.
- Don't add CLI flags or env vars without need. Anything new should have a clear caller.

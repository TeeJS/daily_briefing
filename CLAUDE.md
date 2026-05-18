# CLAUDE.md

Context for future Claude Code sessions working on this repo. Read this first.

## What this is

A scheduled daily HTML email briefing. Runs in a Docker container on Unraid (`noraid.schmitzplex.com`) at 6 AM MT, pulls data from 5 sources, renders one self-contained HTML document, archives to disk, and sends via Gmail API. The same HTML is intended to be served verbatim from `briefing.schmitzplex.com` when that site is built.

User: TJ Schmitz (teejschmitz@gmail.com), running on Windows 11.

## Repo layout

```
briefing/                  Python package (the actual code)
  run.py                   Entry point: python -m briefing.run [--dry-run] [--date YYYY-MM-DD]
  config.py                Env vars, paths, OAuth constants, calendar inclusion list
  secrets.py               Google OAuth credentials load/save
  anthropic_auth.py        Anthropic OAuth tokens (load + auto-refresh)
  etsy_auth.py             Etsy OAuth tokens (load + auto-refresh)
  llm.py                   OpenAI SDK wrapper pointed at the local LiteLLM proxy
  render.py                Jinja2 HTML renderer
  send.py                  Gmail API send
  sources/                 One module per data source, each exposes fetch() -> SectionResult
    calendar.py            Full
    email.py               Full (LLM triage)
    claude_usage.py        Full
    etsy.py                Full
    news.py                v1: 3 of 7 subsections via RSS; 4 sub-stubs
  templates/
    briefing.html.j2       Email + future-static-site HTML

scripts/
  bootstrap_google_oauth.py     One-time browser auth
  bootstrap_anthropic_oauth.py  One-time browser auth (PKCE)
  bootstrap_etsy_oauth.py       One-time browser auth (PKCE)

Dockerfile                 python:3.12-slim base
.github/workflows/build-and-push.yml   Builds + pushes to ghcr.io/teejs/daily-briefing:latest on push to main
```

## Data flow

`run.py` orchestrates: `_gather_sections()` calls each source's `fetch()`, wraps each call in try/except so one bad source can't break the briefing — failed sources become `{"status": "error", "error": str(exc)}` and render as an actionable error block in the template (with the exact bootstrap command to fix).

Each `fetch()` returns a dict with a `status` field: `"ready"` | `"stub"` | `"error"`. The template handles all three branches per section.

After gathering: `render.render(sections, today)` produces `(subject, html)`. The HTML is written to the archive path (`briefings/YYYY/MM/DD.html`) **before** the email is sent — archive is the source of truth, email is one delivery channel. With `--dry-run`, archive is written, send is skipped.

## OAuth: three bootstraps, one pattern

All three (Google, Anthropic, Etsy) follow the same model:
- One-time script run from a desktop with a browser
- Browser opens, user authorizes, code (or full redirect URL) gets pasted back into the script
- Tokens written to `SECRETS_DIR` (default `/app/secrets` in container; override `BRIEFING_SECRETS_DIR` for local dev)
- Refresh tokens **rotate** on every refresh; the source's auth module writes the rotated tokens back to disk
- The briefing job needs `secrets/` mounted **read-write** because of this rotation

Anthropic uses the public client_id from the `trickv/hass-claude-usage` HA integration. Etsy and Google need user-registered OAuth apps (their client_id / keystring becomes runtime env: `ETSY_CLIENT_ID`; Google's `client_secret.json` lives in `secrets/`).

## LLM access

`briefing/llm.py` uses the OpenAI Python SDK with `base_url=LLM_BASE_URL` (default `http://lite.schmitzplex.com:4000/v1`). LiteLLM routes to a llama.cpp backend on `192.168.1.95:8080`. The model name comes from `LLM_MODEL` env (set per-deployment to whatever LiteLLM advertises).

`chat_json()` asks for `response_format={"type": "json_object"}` — works on LiteLLM-proxied OpenAI-compatible backends. If a backend doesn't honor it, the JSON parse will raise `ValueError` and email triage falls back to top-5-as-FYI (see `sources/email.py`).

## Container conventions

Image contains only Python + deps. **No state** in the image. All state lives in volume mounts:
- `/app/secrets` (RW) — OAuth tokens, client secrets
- `/app/briefings` (RW) — daily HTML archive
- `/app/logs` (RW) — rotating logs

Container is **ephemeral** — `docker run --rm` once per day, exits when done.

Env vars at runtime: `LLM_BASE_URL`, `LLM_MODEL`, `TZ` (defaults `America/Denver`), `ETSY_CLIENT_ID` (needed during refresh).

## Known gotchas

- **Jinja2 + `dict.items`** — never use `items` as a key on a dict passed to a template; `obj.items` returns the dict method, not the value. Use `entries` or any other name. This bit us on news.
- **Windows time formatting** — `%-d` / `%-I` not supported on Windows. Use `%d` / `%I` then `.lstrip("0")` or `.replace(" 0", " ")`. Already done throughout.
- **`tzdata` package required** — Windows + minimal Linux images lack the IANA tz db. Listed as a runtime dep in pyproject.
- **Etsy receipt ship-by date** lives on `transaction.expected_ship_date` (line item), not the receipt. Receipt-level ship-by = `min(expected_ship_date)` across transactions.
- **Etsy access token format** — `<user_id>.<random>`. We extract `user_id` by splitting on `.` so we don't need extra OAuth scopes to call `getMe`.
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

# Dry-run with local paths (skips email send, just renders to disk)
$env:BRIEFING_SECRETS_DIR = ".\preview\secrets"
$env:BRIEFING_ARCHIVE_DIR = ".\preview\briefings"
$env:BRIEFING_LOGS_DIR = ".\preview\logs"
python -m briefing.run --dry-run
```

`preview/` is gitignored. Without OAuth tokens, sources fail gracefully into error blocks — useful for template/rendering work.

## Conventions

- Inline CSS only in the template (Gmail-safe). System font stack. 720px max width, 2-column layout above the news section.
- Section macros in the template are pure: data in, HTML out.
- No tests yet. If logic gets complex enough that a regression would be hard to spot, add them — but most of this is glue code where a smoke test (`--dry-run`) catches breakage.
- Don't add CLI flags or env vars without need. Anything new should have a clear caller.

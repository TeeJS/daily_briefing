"""Runtime configuration — paths, env vars, calendar inclusion list."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load .env from CWD if present (local dev). In the container, env vars come from
# `docker run --env-file` instead.
load_dotenv()

# Default paths match the container layout. Override with env vars for local dev.
SECRETS_DIR = Path(os.environ.get("BRIEFING_SECRETS_DIR", "/app/secrets"))
BRIEFINGS_DIR = Path(os.environ.get("BRIEFING_ARCHIVE_DIR", "/app/briefings"))
LOGS_DIR = Path(os.environ.get("BRIEFING_LOGS_DIR", "/app/logs"))

# User-facing settings
TIMEZONE = ZoneInfo(os.environ.get("TZ", "America/Denver"))
RECIPIENT_EMAIL = os.environ.get("BRIEFING_RECIPIENT", "teejschmitz@gmail.com")
SENDER_EMAIL = os.environ.get("BRIEFING_SENDER", RECIPIENT_EMAIL)
ARCHIVE_BASE_URL = os.environ.get("BRIEFING_ARCHIVE_URL", "https://briefing.schmitzplex.com")

# LLM endpoint (LiteLLM proxy by default; see project_briefing_deployment memory)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://lite.schmitzplex.com:4000/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "not-needed")  # LiteLLM may not require one


@dataclass(frozen=True)
class CalendarRef:
    id: str
    label: str


# Calendars to include in the daily-schedule section.
# Decision recorded in project_briefing_calendars memory (2026-05-17).
INCLUDED_CALENDARS: tuple[CalendarRef, ...] = (
    CalendarRef("teejschmitz@gmail.com", "Personal"),
    CalendarRef("7t8v7cqf5c8688nqajplej0ka0@group.calendar.google.com", "Nozbe"),
    CalendarRef("tprd0n50dsp37ia629e2mo65lc@group.calendar.google.com", "Con Schedule"),
    CalendarRef(
        "tjschmitz.com_hkpt0d74ppjcecpcdt2u6ip898@group.calendar.google.com", "Church"
    ),
    CalendarRef(
        "2ilh48eb9tb9mcom33a1a28htln6imau@import.calendar.google.com", "Calendar"
    ),
    CalendarRef("en.usa#holiday@group.v.calendar.google.com", "Holidays"),
)

# Google OAuth scopes the briefing job needs.
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    # gmail.readonly is for the future email-triage section; including it now means
    # the user only has to consent once.
    "https://www.googleapis.com/auth/gmail.readonly",
)

GOOGLE_CLIENT_SECRET_FILE = SECRETS_DIR / "google_client_secret.json"
GOOGLE_TOKENS_FILE = SECRETS_DIR / "google_tokens.json"

# Anthropic OAuth — undocumented /api/oauth/usage endpoint.
# Client ID is the one registered by the trickv/hass-claude-usage HA integration;
# reusing it is fine for a personal job (see project_briefing_claude_usage memory).
ANTHROPIC_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
ANTHROPIC_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
ANTHROPIC_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
ANTHROPIC_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
ANTHROPIC_OAUTH_SCOPES = "org:create_api_key user:profile user:inference"
ANTHROPIC_API_BETA_HEADER = "oauth-2025-04-20"
ANTHROPIC_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
ANTHROPIC_TOKENS_FILE = SECRETS_DIR / "anthropic_tokens.json"

# Etsy OAuth — Etsy Open API v3.
# client_id (keystring) and redirect URI come from the user's Etsy app registration
# (https://www.etsy.com/developers/your-apps). Both required at bootstrap time;
# read from env at runtime to avoid hardcoding.
ETSY_CLIENT_ID = os.environ.get("ETSY_CLIENT_ID", "")
ETSY_REDIRECT_URI = os.environ.get("ETSY_REDIRECT_URI", "")
ETSY_AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
ETSY_SCOPES = "transactions_r"
ETSY_API_BASE = "https://api.etsy.com/v3/application"
ETSY_TOKENS_FILE = SECRETS_DIR / "etsy_tokens.json"

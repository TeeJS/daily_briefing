# Project charter: "Mark complete" on meeting-prep action items

Status: **DRAFT — awaiting T.J. sign-off** (2026-11-12). Nothing is built yet.

## Goal (from T.J.)

Done items must stop lingering in meeting-prep briefs. Not every action item is T.J.'s,
and not every item has a kanban card — but if it's done, it should disappear from future briefs.

## 1. The one thing this must do

From a meeting-prep brief, one click marks **any** action-item row complete (T.J.'s or anyone
else's, with or without a kanban card). That item never appears in a later brief. If the row
has a kanban card, the card moves to Done.

## 2. What would be wrong if we shipped "working" software without it

- A checkbox that only greys the row in one browser: the next prep re-lists it. That is the exact problem.
- Completion that only works for kanban-backed rows (many rows have no card).
- A click that is lost on reload or isn't visible from another device.

## 3. Off-limits as a workaround

- `localStorage`-only state.
- Hand-editing `done.json` or kanban cards to clear items.
- Putting the kanban `X-API-Key` in the page (the key stays server-side).
- Making T.J. tell Claude in chat "that one's done".
- Running anything new on the work laptop (EDR).

## 4. Deployment target and backup location

- **Service:** small new container on Unraid, `:latest` (never pinned), reached at
  `briefing.schmitzplex.com/api/` through NPM Plus behind the host's **existing Authelia login**
  (same origin, no CORS).
- **State:** `done.json` in `M:\meetings\meeting_prep\_state\` (`/mnt/user/data/meetings/meeting_prep/_state`
  on Unraid) — inside the folder the nightly job saves briefs to; T.J. fixed that root on 2026-11-11 and
  never uses `M:\media\meetings\meeting_prep`. (Moved from the briefing volume: it isn't known to be mounted
  for the skill. The first draft of this charter had the `media\` path wrong.)
- **Code:** this repo (service + `done.js`) and `D:\Github\skills\meeting-prep\` (template +
  SKILL.md; not a git repo, so timestamped `.bak-YYYYMMDD-HHMMSS` copies before every edit).
- **Backups:** git for this repo; timestamped copies for the skill; NPM Plus host config
  exported before any route change. Unraid changes happen only with T.J.'s go-ahead at that step.

## 5. How we verify it is done

1. Click "Mark complete" on a kanban-backed row: row greys with Undo, card #N is in `done`
   on the board, `done.json` has the entry.
2. Same on a row with no card: `done.json` entry only, no kanban call.
3. Reload, and open on another device: both rows still show complete.
4. Undo restores the row and the card's previous status.
5. Generate next week's prep for the same meeting: neither item appears in the action items, and both
   appear once in the Completed since last meeting table; the prep after that omits both.
6. POST with no auth, or from another origin / without the custom header: rejected.
7. The kanban key does not appear in any served file.

## Design

| Piece | Where | What it does |
|---|---|---|
| Template + SKILL.md | `D:\Github\skills\meeting-prep` | Each row gets a stable ID (`card-<#>` if a card exists, else a slug of the analysis row). Adds checkbox + "Mark complete" button, hidden unless the API answers. Steps 4/7 read `done.json` and drop matching items (same ID, or same owner + meaning). Also builds the "Completed since last meeting" table: item, owner, date completed, how we know — only completions dated after the last occurrence (a button click's timestamp, a card's move to Done, or a dated email). |
| `done.js` | this repo, served from the briefing site | Click → POST `/api/done`; row greys with Undo. On load → GET `/api/done` to restore state. External file (CSP-safe). |
| `briefing-actions` service | this repo, own small image (`Dockerfile.actions`, stdlib only) | Validates input, writes `done.json` atomically. For `card-N` IDs, calls kanban `PATCH /api/cards/N` with `status=done` using `X-API-Key` from an env var, and records the previous status for Undo. Needs a custom request header (CSRF guard). |
| Container + route | Unraid / NPM Plus | Template via the unraid-container-template workflow; route `/api/` on the briefing host. |

## Decisions needing sign-off (defaults chosen)

1. **Rows the skill already finds complete from evidence** (card in Done, email confirms): also drop
   them from the table. Instead, anything completed since the last meeting appears once in a
   "Completed since last meeting" table under the action items, for T.J.'s items and everyone
   else's (recurring meetings only). *Default: yes.*
2. **Ticking a row with a card moves it to Done even if the owner is someone else** — it's your board
   and Undo restores it. *Default: yes.*
3. **The published Artifact copy of a brief can't save clicks** (no backend there); buttons stay hidden
   there. The copy on `briefing.schmitzplex.com` is the live one. *Default: accept.*

## Known limits / unverified

- Kanban `PATCH /api/cards/{id}` is documented in the kanban repo's PROJECT.md; not exercised by me yet.
- If a later meeting's analysis re-lists a done item, the skill matches by meaning, not exact text;
  a reworded repeat could reappear (Undo/re-mark fixes it).
- Port for the new container will be checked against host-network containers before choosing.
- The meeting-prep skill exists in three drifted copies. The nightly job (`claude -p`, 3 AM, `run.ps1`)
  uses the Claude Code copy in `~\.claude\skills\meeting-prep`, so that one and the template in
  `D:\Github\skills\meeting-prep\assets` are patched (backups beside each file). The claude.ai-synced copy
  is a mirror and is untouched. That installed copy has no `assets\`, so its Step 9 now names the template
  by absolute path.

## Build status (2026-11-12)

Built and tested locally: service + page script (`briefing/actions.py`, `templates/done.js`, 25 tests),
template + SKILL.md changes in `D:\Github\skills\meeting-prep` and in the Claude Code skill the nightly job
runs (backups beside each file), an end-to-end click-through in a browser against a fake kanban (tick, mark
complete, reload, undo; Artifact copy stays plain). **Not done:** nothing deployed; the Unraid container and
the NPM Plus route need T.J.'s go-ahead. GHCR needs no change: Unraid already holds a ghcr.io login that
pulls private `ghcr.io/teejs/...` images.

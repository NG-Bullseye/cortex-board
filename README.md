# cortex-board

Cortex' Kanban board — backend **and** the Ionic app in one repo, served at one origin.

The board is projected **live** from `~/cortex/docs/tickets/*.md` (Leo's single
ticket truth). There is no separate JSON store: every read re-parses the `.md`
files, every write edits one `.md` file.

```
        ~/cortex/docs/tickets/*.md            ← truth (one .md per ticket)
                     │
              tickets_source.py               (status → column, projects the board)
             ┌───────┴────────┐
        server.py          api.py ──serves──>  app/  (Ionic/Angular/Capacitor)
     FastMCP (Claude)   FastAPI (REST)              builds to app/www
     add/move/update/   GET /api/board
     remove_ticket      GET /api/board/{column}
```

## Layout

- `tickets_source.py` — parse + project the board from the ticket `.md` files
- `server.py` — MCP face for Claude (registered in `~/.claude.json` as `board`, stdio)
- `api.py` — REST face + serves the built app at the same origin (systemd `--user` unit `cortex-board-api`, port 8930)
- `app/` — the Ionic/Angular/Capacitor app; `cd app && npm install && npm run build` → `app/www`

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -e .   # one-time
.venv/bin/python server.py                            # MCP (stdio, for Claude)
.venv/bin/python api.py                                # REST + app host, :8930
```

Truth dir overridable via `CORTEX_TICKETS_DIR`, API port via `CORTEX_BOARD_PORT`,
app build dir via `CORTEX_BOARD_WWW` (default repo-relative `app/www`).

## Board-Agent (`board` tmux-Session)

A dedicated, generic Claude instance (Opus 4.7, bypass permissions = global default,
no special priming) that lives in this repo and does one thing: **turn Telegram
`/board` messages into tickets.** No system monitoring — that stays with the
Watchdog.

```
Telegram  ──/board <text>──▶  watchdog telegram_inbox  ──▶  data/board_notify.jsonl
                                  (route(): /board → here, everything else → watchdog)
data/board_notify.jsonl  ──Monitor──▶  board-agent  ──mcp__board__add_ticket──▶
                                                          ~/cortex/docs/tickets/T-NN_*.md
                                                          → board column "new"
```

- **`/board <text>`** in Telegram → the Watchdog's `daemon/telegram_inbox.py`
  splits it off (prefix stripped) into `data/board_notify.jsonl`. A bare `/board`
  or any other message stays on the Watchdog channel (`telegram_notify.jsonl`),
  untouched.
- **`data/board_notify.jsonl`** — append-only intake stream (git-ignored, created
  at runtime). One JSONL line per `/board` input: `{id, ts, chat_id, from_id, username, text}`.
- The board-agent runs the built-in **Monitor** tool on that file; each new line
  becomes a ticket via the `board` MCP (`add_ticket` → `T-NN_slug.md`, status `new`),
  sorted into the right column.

Spawn:

```bash
tmux new-session -d -s board "cd ~/repos/cortex-board && claude --model opus"
```

Then hand it its mandate (create tickets from `board_notify.jsonl`, no system
monitoring, style per `~/cortex/CLAUDE.md`).

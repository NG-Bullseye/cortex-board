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
Telegram  ──any update──▶  watchdog telegram_inbox (the ONLY getUpdates poller)
                                  └─ append-only ──▶  ~/repos/watchdog/data/telegram_updates.jsonl
                                                       (one queue, raw updates, update_id = offset)
board-agent  ──mcp__telegram-hub__telegram_poll(offset)──▶  filters `/board <text>` client-side
             ──mcp__board__add_ticket──▶  ~/cortex/docs/tickets/T-NN_*.md  → column "new"
```

- The Watchdog's `daemon/telegram_inbox.py` is the **Telegram hub**: the single
  getUpdates poller. It no longer fans messages out — it writes every raw update
  append-only into ONE queue `~/repos/watchdog/data/telegram_updates.jsonl`
  (`{"update_id": N, "update": <raw>}`, `update_id` = monotonic offset).
- The board-agent pulls that queue via the `telegram-hub` MCP:
  `mcp__telegram-hub__telegram_poll(offset)` → `{"updates": [...], "next_offset": N}`
  (keep your own offset). It **filters client-side**: only messages whose text
  starts with `/board ` are board intake (prefix stripped); everything else is
  the Watchdog's. A `tail -F` on the queue file is a pure wakeup; the structured
  read is `telegram_poll`. Each `/board` line becomes a ticket via the `board`
  MCP (`add_ticket` → `T-NN_slug.md`, status `new`).

Spawn:

```bash
tmux new-session -d -s board "cd ~/repos/cortex-board && claude --model opus"
```

Then hand it its mandate (create tickets from `/board` messages pulled via
`telegram-hub`, no system monitoring, style per `~/cortex/CLAUDE.md`).

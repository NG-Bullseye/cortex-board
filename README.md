# cortex-board

Cortex' Kanban board — backend **and** the Ionic app in one repo, served at one origin.

The board is projected **live** from GitHub Issues `NG-Bullseye/cortex` (SSOT since
2026-07-02, `tickets_source.py:50`, `config.py:343`). `BOARD_BACKEND=markdown|todoist`
switches to the legacy `.md` or the Todoist backend; there is no separate JSON store.

```
        GitHub Issues NG-Bullseye/cortex      ← truth (BOARD_BACKEND, default github)
                     │
              tickets_source.py               (status → column, projects the board)
             ┌───────┴────────┐
        server.py          api.py ──serves──>  app/  (Ionic/Angular/Capacitor)
     FastMCP (Claude)   FastAPI (REST)              builds to app/www
     add/move/update/   GET /api/board
     remove_ticket      GET /api/board/{column}
```

## Layout

- `tickets_source.py` — facade; picks the backend (`github_backend.py` · `backend.py` · `todoist_backend.py`)
- `server.py` — MCP face for Claude (stdio; not registered in `~/.claude.json` as of 2026-09-15)
- `api.py` — REST face + serves the built app at the same origin (systemd `--user` unit `cortex-board-api`, port 8930)
- `app/` — the Ionic/Angular/Capacitor app; `cd app && npm install && npm run build` → `app/www`

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -e .   # one-time
.venv/bin/python server.py                            # MCP (stdio, for Claude)
.venv/bin/python api.py                                # REST + app host, :8930
```

Markdown truth dir (backend `markdown`) via `CORTEX_TICKETS_DIR`, API port via `CORTEX_BOARD_PORT`,
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
             ──mcp__board__add_ticket──▶  GitHub Issue T-NN in NG-Bullseye/cortex  → column "new"
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
  MCP (`add_ticket` → GitHub Issue `T-NN`, status `new`).

Spawn:

```bash
tmux new-session -d -s board "cd ~/repos/cortex-board && claude --model opus"
```

Then hand it its mandate (create tickets from `/board` messages pulled via
`telegram-hub`, no system monitoring, style per `~/cortex/CLAUDE.md`).

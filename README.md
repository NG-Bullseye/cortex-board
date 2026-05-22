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

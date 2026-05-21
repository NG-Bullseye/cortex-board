# cortex-board

Kanban board for Cortex. Five per-column JSON files are the single source of
truth; two faces sit on the same core so there is never a second truth:

```
        ~/cortex/board/{backlog,new,inprogress,testing,done}.json   ← truth
                              │
                        board_core.py        (load/save, rev = content-hash, atomic)
                       ┌──────┴───────┐
                  server.py        api.py
              FastMCP (Claude)   FastAPI (Ionic app)
```

## Concurrency — no blind overwrite

`rev` is a short sha256 of a column's content, *derived* not stored, so it can
never drift. `get_column` returns it; `set_column` (and `PUT`) require a matching
`rev` — a mismatch means the column changed since you read it and the write is
rejected (stale). Single-ticket ops (`add`/`move`/`update`/`remove`) are atomic
read-modify-write, so they need no rev and cannot lose updates.

## Ticket shape

```json
{ "id": "t1a2b3c4", "title": "...", "description": "...",
  "next_step": "...", "created": "ISO", "updated": "ISO" }
```

## Run

```bash
# one-time
python3 -m venv .venv && .venv/bin/pip install -e .

# MCP (registered in ~/.claude.json as "cortex-board", stdio)
.venv/bin/python server.py

# REST API for the app (systemd --user service cortex-board-api)
.venv/bin/python api.py            # or: uvicorn api:app --port 8930
```

Board location overridable via `CORTEX_BOARD_DIR`, API port via `CORTEX_BOARD_PORT`.

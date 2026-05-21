#!/usr/bin/env python3
"""
Cortex Board REST API — the bridge the Ionic/Capacitor app reads from.

The MCP server (server.py) is for Claude; an Angular app cannot speak MCP, it
speaks HTTP. Both sit on the *same* board_core, so there is exactly one source of
truth and no drift between what Claude edits and what the app shows.

Endpoints (v1):
    GET  /healthz              -> {"ok": true}
    GET  /board                -> whole board
    GET  /board/{column}       -> one column {column, rev, count, tickets}
    PUT  /board/{column}       -> replace column; body=[tickets], header If-Match: <rev>
                                  (forward-compat for drag & drop; 409 on stale rev)

Run:  uvicorn api:app --host 0.0.0.0 --port ${CORTEX_BOARD_PORT:-8930}
"""
from __future__ import annotations

import os

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import board_core as bc

bc.ensure_layout()

app = FastAPI(title="Cortex Board API", version="1.0")

# LAN dev tool — any local origin (ionic serve :8100, capacitor webview) may read.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "columns": list(bc.COLUMNS)}


@app.get("/board")
def board() -> dict:
    return bc.read_board()


@app.get("/board/{column}")
def column(column: str) -> dict:
    try:
        return bc.read_column(column)
    except bc.UnknownColumn as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.put("/board/{column}")
def put_column(
    column: str,
    tickets: list[dict] = Body(...),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict:
    if not if_match:
        raise HTTPException(status_code=428, detail="If-Match: <rev> header required")
    try:
        return bc.set_column(column, tickets, if_match)
    except bc.UnknownColumn as e:
        raise HTTPException(status_code=404, detail=str(e))
    except bc.StaleRev as e:
        # 409 Conflict + current state so the client can re-apply
        raise HTTPException(status_code=409, detail={"error": "stale", "current": e.current})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("CORTEX_BOARD_PORT", "8930")))

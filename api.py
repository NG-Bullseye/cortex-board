#!/usr/bin/env python3
"""
Cortex Board REST API + app host.

The MCP server (server.py) is for Claude; the Angular/Ionic app speaks HTTP.
Both sit on the *same* board_core, so there is one source of truth and no drift.

This one process also serves the built Ionic app, so the whole board is a single
origin on one port:

    GET  /api/healthz            -> {"ok": true}
    GET  /api/board              -> whole board
    GET  /api/board/{column}     -> one column {column, rev, count, tickets}
    PUT  /api/board/{column}     -> replace column; body=[tickets], header If-Match: <rev>
                                    (drag & drop write-back; 409 on stale rev)
    GET  /*                      -> the built app (index.html SPA fallback)

Because the app is served from the same origin as the API, it calls /api/... with a
*relative* URL — no CORS in production and no hardcoded host IP. (CORS stays open so
`ionic serve` on :8100 can still talk to :8930 during development.)

Run:  uvicorn api:app --host 0.0.0.0 --port ${CORTEX_BOARD_PORT:-8930}
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import board_core as bc

bc.ensure_layout()

# Built Ionic app (cortex-dashboard `ng build` output). Overridable for other layouts.
WWW = Path(os.environ.get("CORTEX_BOARD_WWW", "/home/leona/repos/cortex-dashboard/www"))

app = FastAPI(title="Cortex Board API", version="1.1")

# Dev convenience: `ionic serve` (:8100) -> API (:8930) is cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- API (under /api so it never collides with the SPA's own /board route) -
@app.get("/api/healthz")
def healthz() -> dict:
    return {"ok": True, "columns": list(bc.COLUMNS)}


@app.get("/api/board")
def board() -> dict:
    return bc.read_board()


@app.get("/api/board/{column}")
def column(column: str) -> dict:
    try:
        return bc.read_column(column)
    except bc.UnknownColumn as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.put("/api/board/{column}")
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
        raise HTTPException(status_code=409, detail={"error": "stale", "current": e.current})


# ---- Static: serve the built Ionic app with SPA fallback --------------------
@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="unknown api route")
    target = WWW / full_path
    if full_path and target.is_file():
        return FileResponse(target)
    index = WWW / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail=f"app not built at {WWW}")
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("CORTEX_BOARD_PORT", "8930")))

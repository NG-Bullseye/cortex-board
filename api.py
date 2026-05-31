#!/usr/bin/env python3
"""
Cortex Board REST API + app host.

The board is projected *live* from ~/cortex/docs/tickets/*.md (Leo's "Ein Board"
/ einzige Ticket-Wahrheit). There is no separate JSON store on the read path
anymore — every GET re-reads the .md files.

Endpoints (v2):
    GET  /api/healthz            -> {"ok": true, "columns": [...], "source": "..."}
    GET  /api/board              -> whole board, projected from docs/tickets
    GET  /api/board/{column}     -> one column {column, rev, count, tickets}
    GET  /*                      -> the built Ionic app (index.html SPA fallback)

PUT /api/board/{column} is intentionally removed: replacing an entire column
doesn't fit a per-file source. The write path lives in the MCP (server.py) and
edits individual .md files (status change, add, remove).

Run:  uvicorn api:app --host 0.0.0.0 --port ${CORTEX_BOARD_PORT:-8930}
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import tickets_source as ts

# The Ionic app now lives in-repo at app/ and builds to app/www — served from
# here at the same origin. Repo-relative, so it survives a move / disaster recovery.
WWW = Path(os.environ.get("CORTEX_BOARD_WWW", str(Path(__file__).resolve().parent / "app" / "www")))

app = FastAPI(title="Cortex Board API", version="2.0")

# Dev convenience: `ionic serve` (:8100) -> API (:8930) is cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "columns": list(ts.COLUMNS),
        "source": str(ts.TICKETS_DIR),
        "scan_columns": list(ts.SCAN_COLUMNS),
        "scan_source": str(ts.SCAN_TICKETS_DIR),
    }


@app.get("/api/board")
def board() -> dict:
    return ts.read_board()


@app.get("/api/board/{column}")
def column(column: str) -> dict:
    try:
        return ts.read_column(column)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown column {column!r}")


@app.get("/api/scan-board")
def scan_board() -> dict:
    return ts.read_scan_board()


@app.get("/api/scan-board/{column}")
def scan_column(column: str) -> dict:
    try:
        return ts.read_scan_column(column)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown scan column {column!r}")


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

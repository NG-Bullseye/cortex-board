#!/usr/bin/env python3
"""
Cortex Board MCP — agents touch the board through docs/tickets/*.md (Leo's
single ticket truth). Read is a live projection of those files; write creates
or edits them in place. There is no parallel JSON store anymore.

Read tools (always safe, just re-parse docs/tickets):
    get_board, get_column

Write tools (atomic edits of the .md files):
    add_ticket     -> create a fresh T-NN_slug.md with **Status:** new
    move_ticket    -> rewrite the **Status:** line of an existing ticket
    update_ticket  -> rewrite the H1 heading (body edits stay manual)
    remove_ticket  -> delete the ticket .md (for done items, prefer git mv to archive/)

SYSTEMSCANN board (docs/scan-tickets/SC-NN_*.md):
    get_scan_board     -> read all 3 columns (new, open, resolved)
    add_scan_ticket    -> create SC-NN_slug.md with **Status:** new
    move_scan_ticket   -> change status (new / open / resolved)
"""
from __future__ import annotations

import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import tickets_source as ts

# ---- Logging (grep-able: `grep add_ticket logs/server.log`) -----------------
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "server.log"


def slog(tag: str, **kv) -> None:
    ts_ = time.strftime("%Y-%m-%d %H:%M:%S")
    parts = " ".join(f"{k}={v}" for k, v in kv.items())
    try:
        with LOG_FILE.open("a") as f:
            f.write(f"{ts_} {tag} {parts}\n")
    except Exception:
        pass


mcp = FastMCP("board")


# ---- Read -------------------------------------------------------------------
@mcp.tool()
def get_board() -> dict:
    """Read the whole Kanban board, projected live from ~/cortex/docs/tickets.

    Returns every column (backlog, new, inprogress, testing, done) with its
    current `rev` (content hash), ticket count and tickets. Each card carries
    `id` (T-NN / WD-NN) and `title` (`<id> — <heading title>`). Read-only.
    """
    b = ts.read_board()
    slog("get_board", **{c: b[c]["count"] for c in ts.COLUMNS})
    return b


@mcp.tool()
def get_column(column: str) -> dict:
    """Read one column -> {column, rev, count, tickets}. Live from docs/tickets.

    `column` must be one of: backlog, new, inprogress, testing, done.
    """
    try:
        out = ts.read_column(column)
    except KeyError:
        return {"ok": False, "error": f"unknown column {column!r}"}
    slog("get_column", column=column, count=out["count"])
    return out


# ---- Write ------------------------------------------------------------------
@mcp.tool()
def add_ticket(title: str, description: str = "", next_step: str = "") -> dict:
    """Create a new ticket as a fresh T-NN_slug.md in ~/cortex/docs/tickets.

    The new file gets `# T-NN — <title>`, `**Status:** new`, and the body
    sections `## Kontext` (from `description`) and `## Next` (from `next_step`)
    if those are non-empty. The id is the lowest free T-NN across active and
    archive. Returns {id, title, path, column}.
    """
    try:
        out = ts.add_ticket(title, description, next_step)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    slog("add_ticket", id=out["id"])
    return {"ok": True, **out}


@mcp.tool()
def move_ticket(ticket_id: str, to_column: str) -> dict:
    """Move a ticket to another column by rewriting its `**Status:**` line.

    `to_column` is one of: backlog (parks the ticket), new, inprogress, testing,
    done. The canonical status word written into the file is `new` /
    `in_progress` / `testing` / `done` / `parked`.
    """
    try:
        out = ts.move_ticket(ticket_id, to_column)
    except KeyError:
        return {"ok": False, "error": f"unknown column {to_column!r}"}
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    slog("move_ticket", id=ticket_id, to=to_column)
    return {"ok": True, **out}


@mcp.tool()
def update_ticket(
    ticket_id: str,
    title: str | None = None,
    description: str | None = None,
    next_step: str | None = None,
) -> dict:
    """Edit an existing ticket's H1 heading (the title). Description and
    next_step are kept as the long-form body — for those, hand-edit the .md
    (that is what the .md is for).
    """
    try:
        out = ts.update_ticket(
            ticket_id, title=title, description=description, next_step=next_step
        )
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    slog("update_ticket", id=ticket_id)
    return {"ok": True, **out}


@mcp.tool()
def remove_ticket(ticket_id: str) -> dict:
    """Delete a ticket .md file. For done items prefer `git mv` to
    archive/<YYYY-MM>/ (Cortex Daily convention) — this tool removes outright.
    """
    try:
        out = ts.remove_ticket(ticket_id)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    slog("remove_ticket", id=ticket_id)
    return {"ok": True, **out}


# ---- SYSTEMSCANN Board -------------------------------------------------------

@mcp.tool()
def get_scan_board() -> dict:
    """Read the whole SYSTEMSCANN board, projected live from ~/cortex/docs/scan-tickets.

    Returns all 3 columns (new, open, resolved) with rev hash, count and tickets.
    Each SC-NN card carries `id`, `title`, `description`, and `next_step`. Read-only.
    """
    b = ts.read_scan_board()
    slog("get_scan_board", **{c: b[c]["count"] for c in ts.SCAN_COLUMNS})
    return b


@mcp.tool()
def add_scan_ticket(title: str, description: str = "", next_step: str = "") -> dict:
    """Create a new SYSTEMSCANN ticket as SC-NN_slug.md in ~/cortex/docs/scan-tickets.

    The file gets `# SC-NN — <title>`, `**Status:** new`, and optional sections
    `## Kontext` and `## Next`. The id is the lowest free SC-NN (SC-00 reserved
    for INDEX). Returns {id, title, path, column}.
    """
    try:
        out = ts.add_scan_ticket(title, description, next_step)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    slog("add_scan_ticket", id=out["id"])
    return {"ok": True, **out}


@mcp.tool()
def move_scan_ticket(ticket_id: str, to_column: str) -> dict:
    """Move a SYSTEMSCANN ticket to another column by rewriting its `**Status:**` line.

    `ticket_id` must be a SC-NN id. `to_column` is one of: new, open, resolved.
    """
    try:
        out = ts.move_scan_ticket(ticket_id, to_column)
    except KeyError:
        return {"ok": False, "error": f"unknown scan column {to_column!r} (must be new/open/resolved)"}
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    slog("move_scan_ticket", id=ticket_id, to=to_column)
    return {"ok": True, **out}


if __name__ == "__main__":
    mcp.run()

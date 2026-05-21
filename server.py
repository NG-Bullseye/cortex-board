#!/usr/bin/env python3
"""
Cortex Board MCP — let Claude manage the Kanban board safely.

The board is five per-column JSON files under ~/cortex/board (see board_core).
This server is a thin, typed layer over that core with one safety rule baked in:

  * Whole-column replacement (`set_column`) requires the `rev` you got from a
    prior `get_column`/`get_board`. If the column changed in between, the call is
    rejected as stale and you get the current content back to re-apply. That is
    the "get-before-set, no blind overwrite" guarantee — implemented as a content
    hash, not a timestamp, so it is exact.
  * For everyday edits use the atomic single-ticket tools (`add_ticket`,
    `move_ticket`, `update_ticket`, `remove_ticket`) — no rev needed, the
    lost-update problem cannot occur for them.

Read-before-write is therefore only a discipline for bulk reorders; the common
path is safe by construction.
"""
from __future__ import annotations

import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import board_core as bc

# ---- Logging (grep-able: `grep set_column logs/server.log`) ----------------
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "server.log"


def slog(tag: str, **kv) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    parts = " ".join(f"{k}={v}" for k, v in kv.items())
    try:
        with LOG_FILE.open("a") as f:
            f.write(f"{ts} {tag} {parts}\n")
    except Exception:
        pass


bc.ensure_layout()
mcp = FastMCP("cortex-board")


# ---- Read ------------------------------------------------------------------
@mcp.tool()
def get_board() -> dict:
    """Read the whole Kanban board in one call.

    Returns every column (backlog, new, inprogress, testing, done) with its
    current `rev` (content hash), ticket count and tickets. Use the `rev` of a
    column if you later want to `set_column` it. Read-only.
    """
    board = bc.read_board()
    slog("get_board", **{c: board[c]["count"] for c in bc.COLUMNS})
    return board


@mcp.tool()
def get_column(column: str) -> dict:
    """Read one column -> {column, rev, count, tickets}.

    `column` must be one of: backlog, new, inprogress, testing, done. The
    returned `rev` is the token required by `set_column`. Read-only.
    """
    try:
        out = bc.read_column(column)
    except bc.UnknownColumn as e:
        return {"ok": False, "error": str(e)}
    slog("get_column", column=column, rev=out["rev"], count=out["count"])
    return out


# ---- Write (bulk, rev-guarded) ---------------------------------------------
@mcp.tool()
def set_column(column: str, tickets: list[dict], rev: str) -> dict:
    """Replace a whole column's tickets at once. Requires `rev` from a prior
    get_column/get_board for that column.

    Use this only for bulk operations (reordering, mass edits). For moving or
    editing a single ticket prefer move_ticket/update_ticket — they need no rev.

    Each ticket is a dict with `title`, `description`, `next_step` (and optional
    `id` to keep identity; omit `id` for new tickets). On success returns the new
    {column, rev, count, tickets}. If `rev` is stale you get
    {ok:false, error:"stale", current:{...}} — re-read from `current` and retry.
    """
    try:
        out = bc.set_column(column, tickets, rev)
    except bc.UnknownColumn as e:
        return {"ok": False, "error": str(e)}
    except bc.StaleRev as e:
        slog("set_column.stale", column=column, passed=rev, current=e.current["rev"])
        return {"ok": False, "error": "stale", "current": e.current}
    slog("set_column", column=column, rev=out["rev"], count=out["count"])
    return {"ok": True, **out}


# ---- Write (atomic single-ticket ops, no rev needed) -----------------------
@mcp.tool()
def add_ticket(column: str, title: str, description: str = "", next_step: str = "") -> dict:
    """Create a ticket and append it to a column. Atomic — no rev needed.

    A ticket has a `title`, a longer `description`, and a `next_step` (the single
    next action). Returns the created ticket (with generated id) and the column's
    new rev.
    """
    try:
        out = bc.add_ticket(column, title, description, next_step)
    except bc.UnknownColumn as e:
        return {"ok": False, "error": str(e)}
    slog("add_ticket", column=column, id=out["ticket"]["id"])
    return {"ok": True, **out}


@mcp.tool()
def move_ticket(ticket_id: str, to_column: str, position: int = -1) -> dict:
    """Move a ticket to another column by id. Atomic — no rev needed.

    `position` = -1 appends to the end (default); >=0 inserts at that index.
    This is the normal way to advance a ticket new -> inprogress -> testing -> done.
    """
    try:
        out = bc.move_ticket(ticket_id, to_column, None if position < 0 else position)
    except bc.UnknownColumn as e:
        return {"ok": False, "error": str(e)}
    except bc.TicketNotFound as e:
        return {"ok": False, "error": str(e)}
    slog("move_ticket", id=ticket_id, **{"from": out["from"], "to": out["to"]})
    return {"ok": True, **out}


@mcp.tool()
def update_ticket(
    ticket_id: str,
    title: str | None = None,
    description: str | None = None,
    next_step: str | None = None,
) -> dict:
    """Edit a ticket's title / description / next_step in place. Atomic.

    Pass only the fields you want to change; omit the rest.
    """
    try:
        out = bc.update_ticket(
            ticket_id, title=title, description=description, next_step=next_step
        )
    except bc.TicketNotFound as e:
        return {"ok": False, "error": str(e)}
    slog("update_ticket", id=ticket_id)
    return {"ok": True, **out}


@mcp.tool()
def remove_ticket(ticket_id: str) -> dict:
    """Delete a ticket from the board by id. Atomic."""
    try:
        out = bc.remove_ticket(ticket_id)
    except bc.TicketNotFound as e:
        return {"ok": False, "error": str(e)}
    slog("remove_ticket", id=ticket_id, column=out["column"])
    return {"ok": True, **out}


if __name__ == "__main__":
    mcp.run()

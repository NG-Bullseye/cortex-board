#!/usr/bin/env python3
"""
Cortex Board — core. Per-column JSON files are the single source of truth.

Layout  (CORTEX_BOARD_DIR, default ~/cortex/board):

    backlog.json  new.json  inprogress.json  testing.json  done.json

Each file is a plain JSON array of tickets — directly editable by Claude and
parseable by the web app:

    [{"id","title","description","next_step","created","updated"}, ...]

Concurrency model (the root of "no blind overwrite"):
  * rev = short sha256 of the column's canonical content. It is *derived*, never
    stored — so it can never drift from the file. Editing a file by hand changes
    the rev automatically.
  * get_*  returns the current rev; set_column requires a matching rev. A wrong
    rev means the column changed since you read it -> StaleRev (caller re-reads).
  * Single-ticket ops (add / move / update / remove) are atomic read-modify-write
    inside one process call, so the lost-update edge-case cannot arise for them
    and no rev juggling is needed.

This module is the shared core behind both the MCP server (server.py, for Claude)
and the REST API (api.py, for the Ionic app). One core, one truth.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

# Column order is the board's left-to-right order. "backlog" is hidden by
# default in the UI but is a full first-class column here.
COLUMNS: tuple[str, ...] = ("backlog", "new", "inprogress", "testing", "done")

BOARD_DIR = Path(
    os.environ.get("CORTEX_BOARD_DIR", Path.home() / "cortex" / "board")
).expanduser()

# Fields a ticket may carry. Only the first three are user/Claude-editable.
EDITABLE_FIELDS = ("title", "description", "next_step")


# ---- Errors ----------------------------------------------------------------
class BoardError(Exception):
    """Base for all board errors."""


class UnknownColumn(BoardError):
    def __init__(self, column: str):
        super().__init__(
            f"unknown column {column!r} — valid: {', '.join(COLUMNS)}"
        )
        self.column = column


class StaleRev(BoardError):
    """set_column called with a rev that no longer matches the column."""

    def __init__(self, column: str, expected: str, current: dict):
        super().__init__(
            f"stale rev for {column!r}: you passed {expected!r} but current is "
            f"{current['rev']!r} — re-read and re-apply"
        )
        self.column = column
        self.expected = expected
        self.current = current  # full {column, rev, tickets} so caller can retry


class TicketNotFound(BoardError):
    def __init__(self, ticket_id: str):
        super().__init__(f"ticket {ticket_id!r} not found in any column")
        self.ticket_id = ticket_id


# ---- Helpers ---------------------------------------------------------------
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _path(column: str) -> Path:
    if column not in COLUMNS:
        raise UnknownColumn(column)
    return BOARD_DIR / f"{column}.json"


def _canon(tickets: list[dict]) -> str:
    """Stable serialization used for hashing (order + spacing fixed)."""
    return json.dumps(tickets, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _rev(tickets: list[dict]) -> str:
    return hashlib.sha256(_canon(tickets).encode("utf-8")).hexdigest()[:12]


def _gen_id() -> str:
    return "t" + uuid.uuid4().hex[:8]


def _atomic_write(path: Path, tickets: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(tickets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX


def _normalize(ticket: dict, *, keep_created: str | None = None) -> dict:
    """Coerce a ticket dict into the canonical shape."""
    now = _now()
    return {
        "id": str(ticket.get("id") or _gen_id()),
        "title": str(ticket.get("title", "")).strip(),
        "description": str(ticket.get("description", "")).strip(),
        "next_step": str(ticket.get("next_step", "")).strip(),
        "created": keep_created or str(ticket.get("created") or now),
        "updated": now,
    }


# ---- Storage ---------------------------------------------------------------
def ensure_layout() -> None:
    """Create the board dir and any missing (empty) column files."""
    BOARD_DIR.mkdir(parents=True, exist_ok=True)
    for col in COLUMNS:
        p = BOARD_DIR / f"{col}.json"
        if not p.exists():
            _atomic_write(p, [])


def _load(column: str) -> list[dict]:
    p = _path(column)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError as e:
        raise BoardError(f"{column}.json is not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise BoardError(f"{column}.json must be a JSON array, got {type(data).__name__}")
    return data


# ---- Read API --------------------------------------------------------------
def read_column(column: str) -> dict:
    """Return {column, rev, count, tickets} for one column."""
    tickets = _load(column)
    return {"column": column, "rev": _rev(tickets), "count": len(tickets), "tickets": tickets}


def read_board() -> dict:
    """Return the whole board: {columns: [...], <col>: {rev,count,tickets}}."""
    ensure_layout()
    board = {"columns": list(COLUMNS)}
    for col in COLUMNS:
        board[col] = read_column(col)
    return board


# ---- Write API -------------------------------------------------------------
def set_column(column: str, tickets: list[dict], rev: str) -> dict:
    """Replace a whole column. Requires `rev` to match the current content
    (optimistic lock). Raises StaleRev if the column changed since you read it.
    Returns the new {column, rev, count, tickets}."""
    if column not in COLUMNS:
        raise UnknownColumn(column)
    current = read_column(column)
    if rev != current["rev"]:
        raise StaleRev(column, rev, current)
    # preserve created-timestamps where ids already existed
    prev_created = {t.get("id"): t.get("created") for t in current["tickets"]}
    normalized = [_normalize(t, keep_created=prev_created.get(t.get("id"))) for t in tickets]
    _atomic_write(_path(column), normalized)
    return read_column(column)


def add_ticket(column: str, title: str, description: str = "", next_step: str = "") -> dict:
    """Append a new ticket to a column (atomic). Returns {ticket, column rev}."""
    tickets = _load(column) if column in COLUMNS else _raise_col(column)
    ticket = _normalize({"title": title, "description": description, "next_step": next_step})
    tickets.append(ticket)
    _atomic_write(_path(column), tickets)
    return {"ticket": ticket, "column": column, "rev": _rev(tickets)}


def _raise_col(column: str):
    raise UnknownColumn(column)


def find_ticket(ticket_id: str) -> tuple[str, int, dict]:
    """Locate a ticket by id across all columns -> (column, index, ticket)."""
    for col in COLUMNS:
        for i, t in enumerate(_load(col)):
            if t.get("id") == ticket_id:
                return col, i, t
    raise TicketNotFound(ticket_id)


def move_ticket(ticket_id: str, to_column: str, position: int | None = None) -> dict:
    """Move a ticket to another column (atomic). position=None appends."""
    if to_column not in COLUMNS:
        raise UnknownColumn(to_column)
    src_col, idx, ticket = find_ticket(ticket_id)
    src = _load(src_col)
    ticket = src.pop(idx)
    ticket["updated"] = _now()
    if to_column == src_col:
        dst = src
    else:
        dst = _load(to_column)
    if position is None or position < 0 or position > len(dst):
        dst.append(ticket)
    else:
        dst.insert(position, ticket)
    # write dst first, then src (if different) — order irrelevant, single process
    _atomic_write(_path(to_column), dst)
    if to_column != src_col:
        _atomic_write(_path(src_col), src)
    return {"ticket": ticket, "from": src_col, "to": to_column}


def update_ticket(ticket_id: str, **fields) -> dict:
    """Patch a ticket's editable fields (title/description/next_step) in place."""
    col, idx, _ = find_ticket(ticket_id)
    tickets = _load(col)
    t = tickets[idx]
    for k, v in fields.items():
        if k in EDITABLE_FIELDS and v is not None:
            t[k] = str(v).strip()
    t["updated"] = _now()
    _atomic_write(_path(col), tickets)
    return {"ticket": t, "column": col}


def remove_ticket(ticket_id: str) -> dict:
    """Delete a ticket from the board."""
    col, idx, _ = find_ticket(ticket_id)
    tickets = _load(col)
    removed = tickets.pop(idx)
    _atomic_write(_path(col), tickets)
    return {"removed": removed, "column": col}

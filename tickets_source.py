#!/usr/bin/env python3
"""
Project the Cortex board against ~/cortex/docs/tickets/*.md.

Per Leo's INDEX note (2026-05-21): docs/tickets is "die einzige Ticket-Wahrheit".
The board is therefore a *live projection* of those files — no second store, no
sync daemon, no migration job. Edit a ticket's `**Status:**` line, and the card
jumps to the right column on the next read.

Each ticket file is `T-NN_slug.md` or `WD-NN_slug.md` with:
    # ID — Title
    **Status:** <status>
    <body...>

Status normalization (the messy vocabulary in the existing tickets is
straightened on the fly into the four-column flow):
    new / open / 🆕                  -> new
    in_progress / 🔄                 -> inprogress
    testing / TESTING / 🧪           -> testing
    done / DONE / closed / ✅ / 🟢   -> done
    wont-do / hw-block / parked      -> backlog (parked bucket)

SYSTEMSCANN board: ~/cortex/docs/scan-tickets/SC-NN_slug.md
    Columns: new / open / resolved
    **Status:** new | open | resolved

--- T-2 Phase 1 ---
This module is now a thin facade over `config.BoardConfig` + `backend.BoardBackend`.
The cortex-specific knobs (columns, status maps, id schema, paths, md regexes)
live in config.py; the markdown read/write engine lives in backend.py. The
module-level names and free functions below are kept verbatim so server.py /
api.py (and any other importer) need no change. Nothing about the behaviour or
the on-disk format changed.
"""
from __future__ import annotations

import json
import os

from config import CORTEX_BOARD, CORTEX_SCAN_BOARD
from backend import MarkdownBackend


# ---- Backend selection (T-2 Phase 2a) ---------------------------------------
# BOARD_BACKEND=todoist|markdown, default markdown. NO live cutover here — the
# default keeps the on-disk md projection. The scan board stays markdown-only
# (Phase 2a only ports the cortex ticket board to Todoist). Module globals +
# function signatures below are identical regardless of backend, so server.py /
# api.py need no change.
def _make_board():
    if os.environ.get("BOARD_BACKEND", "markdown").strip().lower() == "todoist":
        from todoist_backend import TodoistBackend
        return TodoistBackend(CORTEX_BOARD)
    return MarkdownBackend(CORTEX_BOARD)


# ---- Backend instances ------------------------------------------------------
_board = _make_board()
_scan = MarkdownBackend(CORTEX_SCAN_BOARD)

# ---- Backward-compatible module globals (server.py / api.py read these) -----
TICKETS_DIR = CORTEX_BOARD.tickets_dir
SCAN_TICKETS_DIR = CORTEX_SCAN_BOARD.tickets_dir
COLUMNS = CORTEX_BOARD.columns
SCAN_COLUMNS = CORTEX_SCAN_BOARD.columns


# ---- Ticket board (delegates to the markdown backend) -----------------------
def read_board() -> dict:
    return _board.read_board()


def read_column(column: str) -> dict:
    return _board.read_column(column)


def add_ticket(title: str, description: str = "", next_step: str = "") -> dict:
    return _board.add_ticket(title, description, next_step)


def move_ticket(ticket_id: str, to_column: str) -> dict:
    return _board.move_ticket(ticket_id, to_column)


def update_ticket(
    ticket_id: str,
    title: str | None = None,
    description: str | None = None,
    next_step: str | None = None,
) -> dict:
    return _board.update_ticket(
        ticket_id, title=title, description=description, next_step=next_step
    )


def remove_ticket(ticket_id: str) -> dict:
    return _board.remove_ticket(ticket_id)


# ---- SYSTEMSCANN board ------------------------------------------------------
def read_scan_board() -> dict:
    return _scan.read_board()


def read_scan_column(column: str) -> dict:
    return _scan.read_column(column)


def add_scan_ticket(title: str, description: str = "", next_step: str = "") -> dict:
    return _scan.add_ticket(title, description, next_step)


def move_scan_ticket(ticket_id: str, to_column: str) -> dict:
    return _scan.move_ticket(ticket_id, to_column)


if __name__ == "__main__":
    b = read_board()
    print(json.dumps({c: b[c]["count"] for c in b["columns"]}))
    print(f"source: {b['source']}")
    sb = read_scan_board()
    print(json.dumps({c: sb[c]["count"] for c in sb["columns"]}))
    print(f"scan source: {sb['source']}")

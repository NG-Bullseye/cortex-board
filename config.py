#!/usr/bin/env python3
"""
BoardConfig — the cortex-specific configuration of a Kanban board, lifted out of
the generic engine so a second board (different columns, ids, status vocabulary,
storage dir) is just another `BoardConfig` instance.

Phase 1 of the libboard rework (T-2): this only *separates* the cortex constants
from the engine; it does not change a single value. `CORTEX_BOARD` and
`CORTEX_SCAN_BOARD` carry exactly the values that used to live as module globals
in tickets_source.py.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BoardConfig:
    """Everything cortex-specific about one board: where it lives, how its
    columns are named, how a status word maps to a column (and back), and the
    regexes that recognize / rewrite the ticket markdown."""

    tickets_dir: Path
    columns: tuple[str, ...]
    status_to_column: dict[str, str]
    column_to_status: dict[str, str]
    file_re: re.Pattern
    default_column: str  # column a ticket lands in when its status is unknown
    id_prefix: str  # prefix of a fresh auto-numbered id, e.g. "T" / "SC"
    # which dirs to also scan for *used* ids when picking the next free number
    # (relative globs against tickets_dir); cortex tickets also reserve archive/.
    extra_id_globs: tuple[str, ...] = field(default_factory=tuple)
    # dir-prefix globs (relative to tickets_dir) where a ticket by id may also
    # live (e.g. the cortex archive); `{id}` is filled in at lookup time.
    archive_find_globs: tuple[str, ...] = field(default_factory=tuple)
    reserved_ids: frozenset[str] = field(default_factory=frozenset)
    # which files to glob when projecting the board, and what to drop from them.
    iter_glob: str = "*.md"
    excluded_names: frozenset[str] = field(default_factory=frozenset)
    excluded_prefixes: tuple[str, ...] = field(default_factory=tuple)

    # ---- Todoist backend (T-2 Phase 2a) ------------------------------------
    # Where this same board lives when projected from Todoist instead of md:
    # a sub-project `todoist_project` under the parent project `todoist_parent`,
    # whose Sections are the columns. Pure config so a second board
    # (maintenance/security, Phase 3) is just another BoardConfig — no engine
    # change. Defaults keep existing CORTEX_BOARD construction unchanged.
    todoist_parent: str = "boards"
    todoist_project: str = "cortex"

    # ---- markdown format (shared across cortex boards, kept per-config so a
    #      future board can use a different format without touching the engine).
    # Postel — accept both the standard `**Status:** <val>` and the dash-list
    # form `- **Status:** <val>` emitted by watchdog tools/ticket.py. The
    # optional leading `- ` (or `* `) + whitespace keeps the parser tolerant;
    # the replace pattern matches the whole line incl. any dash prefix so a
    # status rewrite normalizes back to a valid, re-parseable standard line.
    status_line_re: re.Pattern = field(
        default=re.compile(r"^[ \t]*(?:[-*][ \t]+)?\*\*[Ss]tatus\s*:\*\*\s*([^\s(]+)", re.M)
    )
    status_replace_re: re.Pattern = field(
        default=re.compile(r"^[ \t]*(?:[-*][ \t]+)?\*\*[Ss]tatus\s*:\*\*[^\n]*$", re.M)
    )
    heading_re: re.Pattern = field(default=re.compile(r"^#\s+(.+?)\s*$", re.M))
    sep_re: re.Pattern = field(default=re.compile(r"\s+[—–\-]\s+"))


# ---- Default cortex board (docs/tickets) ------------------------------------
_TICKETS_DIR = Path(os.environ.get(
    "CORTEX_TICKETS_DIR", Path.home() / "cortex" / "docs" / "tickets"
))

_SCAN_TICKETS_DIR = Path(os.environ.get(
    "CORTEX_SCAN_TICKETS_DIR", Path.home() / "cortex" / "docs" / "scan-tickets"
))

CORTEX_BOARD = BoardConfig(
    tickets_dir=_TICKETS_DIR,
    columns=("backlog", "new", "inprogress", "testing", "done"),
    status_to_column={
        "new": "new", "open": "new", "🆕": "new",
        "in_progress": "inprogress", "in-progress": "inprogress", "inprogress": "inprogress",
        "🔄": "inprogress",
        "testing": "testing", "🧪": "testing",
        "done": "done", "closed": "done", "✅": "done", "🟢": "done",
        "wont-do": "backlog", "wontdo": "backlog",
        "hw-block": "backlog", "hwblock": "backlog", "blocked": "backlog",
        "deferred": "backlog", "parked": "backlog",
    },
    column_to_status={
        "new": "new",
        "inprogress": "in_progress",
        "testing": "testing",
        "done": "done",
        "backlog": "parked",
    },
    file_re=re.compile(r"^(?P<id>(?:T|WD)-\d+[A-Za-z]?)_(?P<slug>.+)\.md$"),
    default_column="backlog",
    id_prefix="T",
    extra_id_globs=("archive/**/T-*.md",),
    archive_find_globs=("archive/**/{id}_*.md",),
    iter_glob="*.md",
    excluded_names=frozenset({"INDEX.md", "README.md"}),
    excluded_prefixes=("EXECUTION_PLAN_", "RUNBOOK_"),
)


# ---- SYSTEMSCANN board (docs/scan-tickets) ----------------------------------
CORTEX_SCAN_BOARD = BoardConfig(
    tickets_dir=_SCAN_TICKETS_DIR,
    columns=("new", "open", "resolved"),
    status_to_column={
        "new": "new",
        "open": "open",
        "resolved": "resolved",
        "done": "resolved",
        "closed": "resolved",
    },
    column_to_status={
        "new": "new",
        "open": "open",
        "resolved": "resolved",
    },
    file_re=re.compile(r"^(?P<id>SC-\d+[A-Za-z]?)_(?P<slug>.+)\.md$"),
    default_column="new",
    id_prefix="SC",
    reserved_ids=frozenset({"SC-00"}),  # SC-00 reserved for INDEX
    iter_glob="SC-*.md",
)

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

    # ---- source backend (T-135) --------------------------------------------
    # Which BoardBackend projects this board. Default "markdown" keeps every
    # existing board (cortex/cerebellum) byte-identical — they are file-backed
    # `<ID>_slug.md` boards. "findings" reads a maintenance-style findings.json
    # (a dict keyed by a stable `key`, values carry severity/title/detail/…) and
    # is strictly READ-ONLY (the maintenance scanner owns that file). The backend
    # factory in the mirror tool dispatches on this field; the Todoist sink is
    # source-agnostic.
    source: str = "markdown"
    # findings.json path for source=="findings" boards (None for markdown).
    findings_path: Path | None = None

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


# ---- Cerebellum board (cerebellum/board/tickets, CB-NN ids) -----------------
# The cerebellum prediction operator writes defect tickets (CB-NN) into its own
# dedicated board dir (see cerebellum/integrations/board.py, which mirrors the
# cortex ticket markdown format verbatim: `# CB-NN — title` + `**Status:** …`).
# It defines NO own column/status vocabulary, so this reuses the cortex standard
# (backlog/new/inprogress/testing/done) one-to-one — same status words, same
# parser. Projected into Todoist as a sibling sub-project `cerebellum` under the
# same `boards` parent.
_CEREBELLUM_TICKETS_DIR = Path(os.environ.get(
    "CEREBELLUM_TICKETS_DIR", Path.home() / "repos" / "cerebellum" / "board" / "tickets"
))

CEREBELLUM_BOARD = BoardConfig(
    tickets_dir=_CEREBELLUM_TICKETS_DIR,
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
    file_re=re.compile(r"^(?P<id>CB-\d+[A-Za-z]?)_(?P<slug>.+)\.md$"),
    default_column="backlog",
    id_prefix="CB",
    extra_id_globs=("archive/**/CB-*.md",),
    archive_find_globs=("archive/**/{id}_*.md",),
    iter_glob="CB-*.md",
    excluded_names=frozenset({"INDEX.md", "README.md"}),
    todoist_parent="boards",
    todoist_project="cerebellum",
)


# ---- Maintenance board (findings.json source, MNT-<hash> ids) ---------------
# The maintenance scanner (~/repos/maintenance/scan.py) writes a single
# state/findings.json (dict keyed by a stable `key`; each value carries
# severity ∈ {critical,warn,info}, title, detail, suggestion, active(bool), …).
# This board projects the *active* findings into Leo's Todoist as a sibling
# sub-project `maintenance` under the same `boards` parent — same Todoist sink
# as the cortex/cerebellum md boards, but fed by `FindingsBackend` instead of
# `MarkdownBackend` (source="findings"). READ-ONLY: nothing here ever writes
# findings.json or MAINTENANCE_LOG.md — the scanner stays the single source.
#
# Columns ARE the severities (identity status<->column map). `tickets_dir` /
# `file_re` are required by the dataclass but unused by FindingsBackend; they
# carry harmless sane values (the state dir / a never-matching regex) so the
# board never accidentally behaves like a markdown board.
_MAINTENANCE_FINDINGS = Path(os.environ.get(
    "MAINTENANCE_FINDINGS", Path.home() / "repos" / "maintenance" / "state" / "findings.json"
))

MAINTENANCE_BOARD = BoardConfig(
    tickets_dir=_MAINTENANCE_FINDINGS.parent,  # unused by FindingsBackend
    columns=("critical", "warn", "info"),
    status_to_column={"critical": "critical", "warn": "warn", "info": "info"},
    column_to_status={"critical": "critical", "warn": "warn", "info": "info"},
    file_re=re.compile(r"^(?!x)x$"),  # never matches — findings source, no md files
    default_column="info",
    id_prefix="MNT",
    source="findings",
    findings_path=_MAINTENANCE_FINDINGS,
    todoist_parent="boards",
    todoist_project="maintenance",
)


# ---- Registry of named boards (single source — both tools import from here) --
# `sync_md_to_todoist.py` and `archive_done_tickets.py` used to each carry their
# own duplicate BOARDS dict; consolidated here so adding a board is exactly one
# line, and argparse `choices=sorted(BOARDS)` stays in lockstep across tools.
BOARDS: dict[str, BoardConfig] = {
    "cortex": CORTEX_BOARD,
    "cerebellum": CEREBELLUM_BOARD,
    "maintenance": MAINTENANCE_BOARD,
}

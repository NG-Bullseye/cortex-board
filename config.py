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
    # is strictly READ-ONLY (the maintenance scanner owns that file). "github"
    # projects from GitHub Issues (SSOT) via `gh` CLI — requires `github_repo`.
    # The backend factory dispatches on this field; the Todoist sink is
    # source-agnostic.
    source: str = "markdown"
    # findings.json path for source=="findings" boards (None for markdown).
    findings_path: Path | None = None
    # GitHub repo for source=="github" boards, e.g. "NG-Bullseye/cortex".
    github_repo: str | None = None

    # ---- lane split (T-251) -------------------------------------------------
    # Two boards can share one GitHub-Issues source (same github_repo) and
    # split by a title substring — the existing `[cortex-b]` lane-tag
    # convention (see cortex/CLAUDE.md: cortex-b only touches tickets tagged
    # `[cortex-b]` in the title). `title_tag` = only sync issues whose title
    # contains this substring (Lane B). `title_tag_exclude` = skip issues
    # whose title contains this substring (Lane A, so it never re-syncs a
    # Lane B ticket into its own Todoist project). At most one of the two is
    # set per board; sync_github_todoist.py applies whichever is set.
    title_tag: str | None = None
    title_tag_exclude: str | None = None

    # ---- provenance-based Todoist routing (T-297) ---------------------------
    # MANAGER_BOARD-only concern: Leo's Todoist inbox mixes his ~8 direct asks
    # with ~200 self-generated backfill/maintenance tickets. A ticket carrying
    # a free-text `Provenance: leo-direct` line still syncs to its normal
    # status-column section (today's behaviour); anything else (missing line,
    # malformed, or any other value incl. `self`) is routed to a single fixed
    # "maintainance" section instead, regardless of status column, so it never
    # lands in Leo's status-driven view. `todoist_extra_sections` are Section
    # IDs that already exist in Todoist (created by hand, e.g. via the app) —
    # `provision()` merges them into the resolved section map verbatim, it
    # never creates/renames them. `provenance_section` names which of those
    # extra sections is the "not leo-direct" catch-all; None (every other
    # board) keeps sync_md_to_todoist's routing byte-identical to before.
    todoist_extra_sections: dict[str, str] = field(default_factory=dict)
    provenance_section: str | None = None

    # ---- release-gate routing (T-303) ----------------------------------------
    # MANAGER_BOARD-only concern, orthogonal to the provenance axis above: a
    # ticket carrying `Release: pending` (project-manager-agent's Phase-1
    # Capture marker — see backend.py `_parse_release_pending`) is held out of
    # its normal status-column/provenance routing entirely and pinned to this
    # fixed section instead, so it never reaches coding-agent's pipeline view
    # before Leo's explicit "schick los". Once project-manager-agent flips/
    # removes the marker (Phase 2 Release, on Leo's command), the ticket falls
    # back through to its normal target (provenance routing if the board has
    # `provenance_section`, else its status column) on the next sync. Checked
    # *before* provenance in `_target_section` — the release gate wins even for
    # a `Provenance: leo-direct` ticket. None (every other board) keeps routing
    # byte-identical to before T-303. Unlike `todoist_extra_sections` (T-297,
    # pre-existing hand-created section) this section is auto-provisioned by
    # name in `TodoistBackend.provision()`, same as the per-column sections —
    # no manual Todoist setup required.
    release_pending_section: str | None = None

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
    todoist_parent="boards",
    todoist_project="coding-agent-a",
    # Lane A (T-251 review-fix): exclude Lane-B-tagged tickets so the daily
    # markdown mirror (sync_md_to_todoist.py, production's live systemd timer)
    # stops re-syncing [cortex-b] tickets into coding-agent-a. Mirrors
    # GITHUB_CORTEX_BOARD's identical exclude below, for the markdown path.
    title_tag_exclude="[cortex-b]",
)


# ---- SYSTEMSCANN board (docs/scan-tickets) ----------------------------------
# PARKED, NOT WIRED TO PRODUCTION (T-257 audit): no systemd unit and no
# `BOARDS` entry references this config — it exists only as a fully-formed
# BoardConfig for whenever ~/cortex/docs/scan-tickets (SC-NN findings from
# SYSTEMSCANN.md probes) gets a Todoist mirror. Structurally it would be a
# clean one-way md->Todoist sync like CORTEX_BOARD if ever activated (same
# `sync_md_to_todoist.py` engine, no reverse-write path exists to add). Its
# `todoist_project="cortex"` target is itself a stale/orphaned Todoist
# project (see docs/T-255_todoist_bestandsaufnahme.md Befund 3) — do not
# wire this up without first deciding what "cortex" should hold.
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
    todoist_parent="boards",
    todoist_project="cortex",
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


# ---- GitHub-backed cortex board (NG-Bullseye/cortex Issues as SSOT) ----------
# Same columns + status vocabulary as CORTEX_BOARD, but projected from GitHub
# Issues via `gh` CLI. Ticket IDs (T-NN, WD-NN) live in issue titles; status is
# a `status:*` label. This is the SSOT board — the md directory becomes a
# lagging mirror during migration and eventually an archive.
GITHUB_CORTEX_BOARD = BoardConfig(
    tickets_dir=_TICKETS_DIR,  # kept for archive lookups during migration
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
    extra_id_globs=("archive/**/T-*.md", "archive/**/WD-*.md"),
    archive_find_globs=("archive/**/{id}_*.md",),
    iter_glob="*.md",
    excluded_names=frozenset({"INDEX.md", "README.md"}),
    excluded_prefixes=("EXECUTION_PLAN_", "RUNBOOK_"),
    source="github",
    github_repo="NG-Bullseye/cortex",
    todoist_parent="boards",
    todoist_project="cortex",
    # Lane A: exclude Lane-B-tagged issues so this board never re-syncs a
    # cortex-b ticket into its own Todoist project (see CORTEX_B_BOARD below).
    title_tag_exclude="[cortex-b]",
)


# ---- GitHub-backed Cortex-B board (Lane B — same GitHub Issues source as
#      GITHUB_CORTEX_BOARD, filtered to tickets tagged `[cortex-b]`) --------
# NOT YET WIRED TO PRODUCTION (T-251 review-fix): the live
# sync-github-todoist.timer (every 5min) invokes sync_github_todoist.py with
# no --board arg, i.e. only the default "cortex-github" (Lane A). Nothing
# in production runs `--board cortex-b` against this github-sourced config
# today — it's a ready-but-dormant board for whenever the GitHub-Issues-SSOT
# migration goes live for Lane B too. Keep the name distinct from the
# markdown-sourced `CORTEX_B_BOARD` below (the one production's
# sync_md_to_todoist.py / maintenance-board-mirror.timer actually uses) so
# "CORTEX_B_BOARD" unambiguously means "what production runs".
GITHUB_CORTEX_B_BOARD = BoardConfig(
    tickets_dir=_TICKETS_DIR,  # kept for archive lookups during migration
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
    extra_id_globs=("archive/**/T-*.md", "archive/**/WD-*.md"),
    archive_find_globs=("archive/**/{id}_*.md",),
    iter_glob="*.md",
    excluded_names=frozenset({"INDEX.md", "README.md"}),
    excluded_prefixes=("EXECUTION_PLAN_", "RUNBOOK_"),
    source="github",
    github_repo="NG-Bullseye/cortex",
    todoist_parent="boards",
    todoist_project="coding-agent-b",
    # Lane B: only sync issues tagged [cortex-b] in the title.
    title_tag="[cortex-b]",
)


# ---- Cortex-B board (Lane B — markdown source, PRODUCTION) -----------------
# What production's sync_md_to_todoist.py / maintenance-board-mirror.timer
# actually run for Lane B (T-251 review-fix). Lane B tickets are NOT a
# separate directory — cortex-b works the SAME docs/tickets markdown files
# as Lane A, distinguished only by a `[cortex-b]` tag in the title (see
# ~/cortex/CLAUDE.md § Rolle: cortex-b only touches tickets tagged
# `[cortex-b]`). So this reuses CORTEX_BOARD's tickets_dir/file_re/columns/
# status vocabulary byte-for-byte, just filtered by `title_tag` and
# projected into its own Todoist project (coding-agent-b) so Lane A/B never
# collide in the same project.
CORTEX_B_BOARD = BoardConfig(
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
    todoist_parent="boards",
    todoist_project="coding-agent-b",
    # Lane B: only sync tickets tagged [cortex-b] in the title.
    title_tag="[cortex-b]",
)


# ---- Manager board (project-manager-agent/docs/tickets, MB-NN ids) ---------
# The Manager (project-manager-agent, Leo's direct-facing agent) writes tickets
# for tasks Leo hands it directly (T-246), before it delegates them onward to
# coding-agent/cortex — its own step in the Leo -> Manager -> Cortex-Board ->
# Cortex/Cortex-B ticket-handoff chain (see project-manager-agent/docs/
# plan-manager-board.md). Same markdown format + same status vocabulary as
# CORTEX_BOARD (reused one-to-one, no new column/status logic). Projected into
# Todoist as a sibling sub-project `manager` under the same `boards` parent.
_MANAGER_TICKETS_DIR = Path(os.environ.get(
    "MANAGER_TICKETS_DIR",
    Path.home() / "repos" / "project-manager-agent" / "docs" / "tickets",
))

MANAGER_BOARD = BoardConfig(
    tickets_dir=_MANAGER_TICKETS_DIR,
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
    file_re=re.compile(r"^(?P<id>MB-\d+[A-Za-z]?)_(?P<slug>.+)\.md$"),
    default_column="backlog",
    id_prefix="MB",
    extra_id_globs=("archive/**/MB-*.md",),
    archive_find_globs=("archive/**/{id}_*.md",),
    iter_glob="MB-*.md",
    excluded_names=frozenset({"INDEX.md", "README.md"}),
    todoist_parent="boards",
    todoist_project="manager",
    # T-297: leo-direct tickets keep syncing to their status column; every
    # other ticket (self-generated backfill/maintenance, incl. missing/
    # malformed Provenance) routes to this fixed pre-existing section instead.
    todoist_extra_sections={"maintainance": "6h4fX65xc9JhrCGX"},
    provenance_section="maintainance",
    # T-303: Phase-1-Capture tickets (`Release: pending`) are held here until
    # project-manager-agent flips the marker on Leo's explicit release command.
    release_pending_section="wartet auf Freigabe",
)


# ---- Coding-Agent board (coding-agent/docs/tickets, CA-NN ids) --------------
# Middle stage of the 3-stage ticket-handoff chain confirmed final by Leo
# (T-260): Leo(Telegram) -> Manager-Board(MB) -> Coding-Agent-Board(CA) ->
# Cortex-/Cortex-B-Board(T). coding-agent (PO/Scrum-Master, ~/repos/coding-agent)
# writes CA-NN tickets here after breaking down a Manager-Board (MB-NN) item,
# before delegating the actual implementation cut onward to cortex/cortex-b as
# T-NN tickets. Same markdown format + same status vocabulary as CORTEX_BOARD
# (reused one-to-one, no new column/status logic — see docs/board-chain-refs.md
# for the freetext back-ref convention between stages). Projected into Todoist
# as a sibling sub-project `coding-agent` under the same `boards` parent.
_CODING_AGENT_TICKETS_DIR = Path(os.environ.get(
    "CODING_AGENT_TICKETS_DIR",
    Path.home() / "repos" / "coding-agent" / "docs" / "tickets",
))

CODING_AGENT_BOARD = BoardConfig(
    tickets_dir=_CODING_AGENT_TICKETS_DIR,
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
    file_re=re.compile(r"^(?P<id>CA-\d+[A-Za-z]?)_(?P<slug>.+)\.md$"),
    default_column="backlog",
    id_prefix="CA",
    extra_id_globs=("archive/**/CA-*.md",),
    archive_find_globs=("archive/**/{id}_*.md",),
    iter_glob="CA-*.md",
    excluded_names=frozenset({"INDEX.md", "README.md"}),
    todoist_parent="boards",
    todoist_project="coding-agent",
)


# ---- Registry of named boards (single source — both tools import from here) --
# `sync_md_to_todoist.py` and `archive_done_tickets.py` used to each carry their
# own duplicate BOARDS dict; consolidated here so adding a board is exactly one
# line, and argparse `choices=sorted(BOARDS)` stays in lockstep across tools.
BOARDS: dict[str, BoardConfig] = {
    "cortex": CORTEX_BOARD,
    "cortex-github": GITHUB_CORTEX_BOARD,
    "cortex-b": CORTEX_B_BOARD,
    "cortex-b-github": GITHUB_CORTEX_B_BOARD,
    "cerebellum": CEREBELLUM_BOARD,
    "maintenance": MAINTENANCE_BOARD,
    "manager": MANAGER_BOARD,
    "coding-agent": CODING_AGENT_BOARD,
}

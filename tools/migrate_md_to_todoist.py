#!/usr/bin/env python3
"""
migrate_md_to_todoist — one-shot, idempotent, create-only migration of a
markdown board into its Todoist projection.

It reads the *active* tickets of a `BoardConfig` through `MarkdownBackend`
(the same source the live board serves) and recreates each card as a Todoist
task in the board's sub-project, under the section that matches the card's
column — **keeping the existing id** by writing the full `"T-NN — <text>"`
title verbatim as the task content. The done column is never migrated.

Reusable by config: maintenance / security boards are just a different
`--board` (another `BoardConfig` in config.py). Nothing here is cortex-specific
beyond the default config choice.

Guarantees
----------
- **Create-only / reversible.** Only `provision()` (parent reuse + sub-project +
  sections) and `add_task` run. No delete, no move of any existing task, nothing
  touched on the parent project or its loose ideas.
- **Idempotent.** Existing tasks in the sub-project are listed first; any ticket
  whose id-prefix (`"T-NN"` at the start of a task title) already exists is
  skipped. A second run creates zero duplicates.
- **id-preserving.** The task content is the card's full title incl. id prefix,
  so the markdown id survives — `add_ticket` (which allocates a *new* id) is
  deliberately NOT used.

Usage
-----
    python tools/migrate_md_to_todoist.py --dry-run     # show plan, write nothing
    python tools/migrate_md_to_todoist.py               # real run (default)
    python tools/migrate_md_to_todoist.py --board cortex
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# repo root on path so `config` / `backend` / `todoist_backend` import as on the
# live service (they use top-level imports, not a package).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfgmod  # noqa: E402
from backend import MarkdownBackend  # noqa: E402
from todoist_backend import TodoistBackend  # noqa: E402

# columns that get migrated; `done`/archive are intentionally excluded so Leo's
# Todoist board stays the *active* board, not a graveyard.
MIGRATE_COLUMNS = ("backlog", "new", "inprogress", "testing")

# registry of migratable boards -> their BoardConfig. Adding maintenance/security
# later is one line here once their BoardConfig exists in config.py.
BOARDS = {
    "cortex": cfgmod.CORTEX_BOARD,
}


def _id_of(backend: TodoistBackend, title: str) -> str | None:
    """Extract the card's id from its title using the *backend's own* parser, so
    the dedup key matches exactly what the backend would store/read back. Handles
    every id prefix the board uses (T-, WD-, …), not just config.id_prefix — the
    cortex board mixes T and WD ids and both must dedup. Falls back to None when
    no id is recognizable."""
    tid, _ = backend._parse_id_title(title)
    return tid or None


def migrate(board_key: str, dry_run: bool) -> int:
    board_cfg = BOARDS[board_key]
    md = MarkdownBackend(board_cfg)
    board = md.read_board()

    print(f"=== migrate_md_to_todoist  board={board_key}  "
          f"dry_run={dry_run} ===")
    print(f"source: {board.get('source')}")
    print(f"target: todoist parent={board_cfg.todoist_parent!r} "
          f"project={board_cfg.todoist_project!r}")

    # source cards per migrated column
    src: dict[str, list[dict]] = {}
    total_src = 0
    for col in MIGRATE_COLUMNS:
        cards = board.get(col, {}).get("tickets", [])
        src[col] = cards
        total_src += len(cards)
        print(f"  src[{col:10s}] = {len(cards)}")
    print(f"  src[total]      = {total_src}")
    # report done count purely for the operator's sanity (never migrated)
    print(f"  (done not migrated; src[done] = "
          f"{board.get('done', {}).get('count', 0)})")

    backend = TodoistBackend(board_cfg)

    if dry_run:
        # provision is itself idempotent + create-only, but in dry-run we don't
        # call it either — we only need the *plan*. Without a provisioned target
        # we can't list existing tasks, so dry-run reports the full source as the
        # would-create plan and notes that idempotent skipping is resolved live.
        print("--- DRY RUN: would provision (idempotent) + create below; "
              "writes nothing ---")
        for col in MIGRATE_COLUMNS:
            for card in src[col]:
                print(f"  WOULD-CREATE [{col:10s}] {card['title']}")
        print(f"--- DRY RUN plan total = {total_src} "
              f"(live run skips any id already present) ---")
        return 0

    # ---- real run: provision (idempotent) then create missing ----
    prov = backend.provision()
    sections = prov["sections"]
    project_id = prov["project_id"]
    print(f"provisioned: project_id={project_id}")
    for col in board_cfg.columns:
        print(f"  section[{col:10s}] = {sections.get(col)}")

    # existing ids in the sub-project -> for idempotent skip
    existing_tasks = backend._client.list_tasks(project_id)
    existing_ids: set[str] = set()
    for t in existing_tasks:
        tid = _id_of(backend, t.get("content", ""))
        if tid:
            existing_ids.add(tid)
    print(f"existing tasks in sub-project: {len(existing_tasks)} "
          f"({len(existing_ids)} with id-prefix)")

    created: dict[str, int] = {c: 0 for c in MIGRATE_COLUMNS}
    skipped: dict[str, int] = {c: 0 for c in MIGRATE_COLUMNS}

    for col in MIGRATE_COLUMNS:
        section_id = sections[col]
        for card in src[col]:
            title = card["title"]
            tid = _id_of(backend, title) or title
            if tid in existing_ids:
                skipped[col] += 1
                continue
            description = backend._compose_desc(
                card.get("description", ""), card.get("next_step", "")
            )
            backend._client.add_task(
                content=title,
                project_id=project_id,
                section_id=section_id,
                description=description,
            )
            existing_ids.add(tid)  # guard against intra-run dup
            created[col] += 1

    print("--- RESULT ---")
    tot_c = tot_s = 0
    for col in MIGRATE_COLUMNS:
        print(f"  [{col:10s}] created={created[col]:3d}  skipped={skipped[col]:3d}")
        tot_c += created[col]
        tot_s += skipped[col]
    print(f"  [total     ] created={tot_c:3d}  skipped={tot_s:3d}  "
          f"(source={total_src})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", default="cortex", choices=sorted(BOARDS),
                    help="which BoardConfig to migrate (default: cortex)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be created, write nothing")
    args = ap.parse_args()
    return migrate(args.board, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())

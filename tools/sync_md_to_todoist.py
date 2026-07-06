#!/usr/bin/env python3
"""
sync_md_to_todoist — idempotent ONE-WAY reconcile of a markdown board into its
Todoist *mirror* projection (T-2 Phase 3, corrected direction).

Architecture decision (supersedes the earlier todoist->md attempt, PR #4):
**Markdown is operationally authoritative** — the rich, local, robust ticket
bodies under ~/cortex/docs/tickets are the single source of truth. **Todoist is
only Leo's slim, mirrored VIEW of the active board.** This tool pushes md ->
todoist; it never reads anything back into md and never writes a markdown file.

What it reconciles
------------------
Source  = `MarkdownBackend(cfg).read_board()`, *active* columns only
          (backlog/new/inprogress/testing). `done`/archive are never read.
Target  = the Todoist sub-project `cfg.todoist_project` under `cfg.todoist_parent`,
          whose Sections are the columns. One task per ticket, keyed by id.

Per active md ticket, the matching Todoist task is **upserted by id**
(`T-NN` / `WD-NN`, also tolerant of labelled titles like `T-27 [EPIC]` — the id
key comes from `TodoistBackend._parse_id_title`):

  * exists   -> update only the fields that actually differ (idempotent: a second
               run with no md change writes nothing):
                 - section  = column(=status)
                 - content  = "<ID> — <md-title>"
                 - description = SHORT summary (never the full body): the md
                   backend's own `_extract_description` (first non-metadata
                   paragraph, single line, capped) — Leo's board stays slim.
  * missing  -> create it (section + content + short description), like migrate.

Active Todoist tasks whose id is no longer in the md board are moved to the
Todoist **TRASH** (`is_deleted`/v1 delete is a soft delete = trash), never
hard-purged. The boards parent project and its loose root ideas are never
touched — we operate strictly inside the cortex sub-project.

Guarantees
----------
- **One-way md -> todoist.** No markdown file is ever written; md is read-only.
- **done/archive never read.** Only the 4 active columns are pulled from md.
- **Description always short.** Always the md `_extract_description` summary,
  never the full ticket body.
- **Trash, not purge.** Removals go through `delete_task` (Todoist soft-delete /
  trash), recoverable from Leo's Todoist trash; nothing is hard-deleted.
- **Idempotent.** Field-level diffing: only changed fields are written; an
  unchanged board reconciles with zero writes.

Reuse: like migrate_md_to_todoist this is config-parametrized — a maintenance /
security board is just another `--board` once its BoardConfig exists.

Usage
-----
    python tools/sync_md_to_todoist.py --dry-run            # plan only, writes nothing
    python tools/sync_md_to_todoist.py                      # real run (default)
    python tools/sync_md_to_todoist.py --board cortex
    python tools/sync_md_to_todoist.py --only T-19          # upsert ONLY this id (live test)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# repo root on path so `config` / `backend` / `todoist_backend` import as on the
# live service (top-level imports, not a package) — same shim as migrate.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BOARDS, BoardConfig  # noqa: E402  single source — registry in config.py
from backend import MarkdownBackend, FindingsBackend, BoardBackend  # noqa: E402
from todoist_backend import TodoistBackend  # noqa: E402


def _source_backend(cfg: BoardConfig) -> BoardBackend:
    """Pick the read-side backend for the board's `source` (T-135). markdown =
    file-per-ticket `<ID>_slug.md` board; findings = read-only findings.json
    (maintenance). The Todoist sink downstream is source-agnostic."""
    if cfg.source == "findings":
        return FindingsBackend(cfg)
    return MarkdownBackend(cfg)


def _active_columns(cfg: BoardConfig) -> tuple[str, ...]:
    """Columns mirrored into Todoist: every column except the `done` graveyard.
    For cortex/cerebellum this yields ("backlog","new","inprogress","testing")
    byte-identical to the old hardcoded constant; for the maintenance findings
    board (critical/warn/info, no done column) it yields all three."""
    return tuple(c for c in cfg.columns if c != "done")


# ---- Lane filtering (T-251 review-fix) -------------------------------------
# Mirrors sync_github_todoist.py's `_issue_in_lane` substring-check verbatim —
# CORTEX_BOARD (Lane A) and CORTEX_B_BOARD (Lane B) share the same markdown
# tickets_dir, split only by a `[cortex-b]` title tag (see config.py, T-251).
def _card_in_lane(cfg: BoardConfig, title: str) -> bool:
    if cfg.title_tag is not None:
        return cfg.title_tag in title
    if cfg.title_tag_exclude is not None:
        return cfg.title_tag_exclude not in title
    return True


def _short_desc(card: dict) -> str:
    """The slim mirror description for Todoist: the md backend's own
    `_extract_description` summary (first non-metadata paragraph, single line,
    already length-capped). NEVER the full ticket body — Leo's board is a view,
    not a copy. `read_board` already ran this, so we just take it verbatim."""
    return (card.get("description") or "").strip()


def build_plan(board_cfg, backend: TodoistBackend, only: str | None):
    """Compute the reconcile plan without writing anything.

    Returns (creates, updates, trashes, sections, project_id) where:
      creates = [(col, card)]
      updates = [(task, col, new_content|None, new_desc|None)]  (None = unchanged)
      trashes = [task]   (active todoist tasks whose id left the md board)
    """
    src = _source_backend(board_cfg)
    board = src.read_board()  # active columns only; done/archive never read

    # md side: id -> (column, card). active columns only.
    active_columns = _active_columns(board_cfg)
    md_by_id: dict[str, tuple[str, dict]] = {}
    for col in active_columns:
        for card in board.get(col, {}).get("tickets", []):
            if not _card_in_lane(board_cfg, card["title"]):
                continue
            tid, _ = backend._parse_id_title(card["title"])
            if not tid:
                tid = card["id"]
            md_by_id[tid] = (col, card)

    prov = backend.provision()  # idempotent: parent reuse + sub-project + sections
    project_id = prov["project_id"]
    sections = prov["sections"]
    sec_to_col = {sid: c for c, sid in sections.items()}

    # todoist side: id -> task (only inside the cortex sub-project)
    tasks = backend._client.list_tasks(project_id)
    todoist_by_id: dict[str, dict] = {}
    for t in tasks:
        tid, _ = backend._parse_id_title(t.get("content", ""))
        if tid:
            todoist_by_id[tid] = t

    creates: list[tuple[str, dict]] = []
    updates: list[tuple[dict, str, str | None, str | None, str | None]] = []
    trashes: list[dict] = []

    ids = sorted(md_by_id) if only is None else [only]
    for tid in ids:
        if tid not in md_by_id:
            continue
        col, card = md_by_id[tid]
        _, md_title = backend._parse_id_title(card["title"])
        new_content = f"{tid} — {md_title}" if md_title else tid
        new_desc = _short_desc(card)

        task = todoist_by_id.get(tid)
        if task is None:
            creates.append((col, card))
            continue

        # field-level diff -> only write what changed (idempotency)
        cur_content = (task.get("content") or "").strip()
        cur_desc, cur_next = backend._split_desc(task.get("description", "") or "")
        # the mirror writes a description-only summary; the canonical stored form
        # carries no next_step, so the target description is just new_desc.
        want_desc = new_desc
        content_change = new_content if cur_content != new_content else None
        desc_change = want_desc if (cur_desc.strip() != want_desc or cur_next) else None
        # section move?
        cur_col = sec_to_col.get(task.get("section_id"))
        col_change = col if cur_col != col else None
        if content_change is None and desc_change is None and col_change is None:
            continue
        updates.append((task, col_change, content_change, desc_change, want_desc))

    # trash: active todoist tasks whose id is no longer in the md board.
    # only when syncing the *whole* board (--only never trashes — it touches one id).
    if only is None:
        for tid, task in sorted(todoist_by_id.items()):
            if tid not in md_by_id:
                trashes.append(task)

    return creates, updates, trashes, sections, project_id


def sync(board_key: str, dry_run: bool, only: str | None) -> int:
    board_cfg = BOARDS[board_key]
    backend = TodoistBackend(board_cfg)

    mode = "DRY-RUN" if dry_run else "LIVE"
    scope = f"only={only}" if only else "full-board"
    print(f"=== sync_md_to_todoist  board={board_key}  {mode}  {scope} ===")
    print(f"  direction: md -> todoist (one-way, md authoritative; "
          f"never writes md)")
    print(f"  target: todoist parent={board_cfg.todoist_parent!r} "
          f"project={board_cfg.todoist_project!r}")
    print(f"  source backend: {board_cfg.source}")
    print(f"  active columns synced: {_active_columns(board_cfg)}  (done/archive never read)")

    creates, updates, trashes, sections, project_id = build_plan(
        board_cfg, backend, only
    )

    print(f"  project_id: {project_id}")
    print("--- PLAN ---")
    print(f"  updates = {len(updates)}")
    print(f"  creates = {len(creates)}")
    print(f"  trashes = {len(trashes)}  (-> Todoist trash, soft-delete)")

    for col, card in creates:
        print(f"  CREATE [{col:10s}] {card['title']}")
    for task, col_change, content_change, desc_change, _ in updates:
        tid, _ = backend._parse_id_title(task.get("content", ""))
        bits = []
        if col_change:
            bits.append(f"section->{col_change}")
        if content_change is not None:
            bits.append("content")
        if desc_change is not None:
            bits.append("desc")
        print(f"  UPDATE {tid:8s} [{', '.join(bits)}]")
    for task in trashes:
        tid, _ = backend._parse_id_title(task.get("content", ""))
        print(f"  TRASH  {tid:8s} (no longer in md)")

    if dry_run:
        print("--- DRY RUN: wrote nothing ---")
        return 0

    # ---- real run -----------------------------------------------------------
    # trashes FIRST: they free up project-item headroom before creates spend it.
    # Reversed order used to hard-crash the whole run on
    # MAX_ITEMS_LIMIT_REACHED (HTTP 403/49) as soon as a project was full,
    # never reaching the trashes that would have freed the room (FBL-1).
    cl = backend._client
    for task in trashes:
        # delete_task on /api/v1 is a SOFT delete = moves to Todoist trash,
        # recoverable by Leo; never a hard purge.
        cl.delete_task(task["id"])
    for task, col_change, content_change, desc_change, want_desc in updates:
        fields: dict = {}
        if content_change is not None:
            fields["content"] = content_change
        if desc_change is not None:
            fields["description"] = want_desc
        if fields:
            cl.update_task(task["id"], **fields)
        if col_change is not None:
            cl.move_task(task["id"], sections[col_change])
    for col, card in creates:
        _, md_title = backend._parse_id_title(card["title"])
        tid = card["id"]
        content = f"{tid} — {md_title}" if md_title else tid
        cl.add_task(
            content=content,
            project_id=project_id,
            section_id=sections[col],
            description=_short_desc(card),
        )

    print(f"--- DONE: created={len(creates)} updated={len(updates)} "
          f"trashed={len(trashes)} ---")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", default="cortex", choices=sorted(BOARDS),
                    help="which BoardConfig to sync (default: cortex)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the reconcile plan, write nothing")
    ap.add_argument("--only", default=None, metavar="ID",
                    help="upsert ONLY this ticket id (e.g. T-19); never trashes")
    args = ap.parse_args()
    return sync(args.board, args.dry_run, args.only)


if __name__ == "__main__":
    raise SystemExit(main())

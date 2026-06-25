#!/usr/bin/env python3
"""
export_todoist_to_md — the reverse of migrate_md_to_todoist: regenerate the
markdown ticket files of a `BoardConfig` from its Todoist projection, so the
markdown board stays a *current* disaster-recovery fallback instead of freezing
at the migration cutover (T-2 Phase 3).

It reads the *active* columns of the board's Todoist sub-project through
`TodoistBackend` and writes/updates one `<ID>_slug.md` per task under the
target tickets dir — keeping the id verbatim from the task title
(`"T-NN — <text>"`), with the `**Status:**` line and column derived from the
task's section via `BoardConfig.column_to_status`. Afterwards
`MarkdownBackend(cfg).read_board()` projects the same active board state as
Todoist.

Reusable by config: maintenance / security boards are just a different
`--board` (another `BoardConfig` in config.py). Nothing here is cortex-specific
beyond the default config choice. σ-free: no store dispatch, no learning path.

Guarantees
----------
- **Active columns only.** Only backlog/new/inprogress/testing are exported.
  `done`/archive are NEVER touched — the migration deliberately left `done`
  out, and the live `docs/tickets` carries ~40 done tickets + archive/ that are
  NOT in Todoist and must not be lost. Only files that belong to *active*
  tickets are written; done files and archive/ stay byte-for-byte untouched.
- **md mirrors Todoist.** With `--prune` (default on) an active md ticket that
  no longer exists in Todoist is removed from the active set — but a removal
  only ever targets a top-level active ticket file (`_iter_ticket_files`),
  never anything under archive/ and never a `done`-column file.
- **Idempotent.** The canonical body is built once and only written when it
  differs from what's on disk; a second run without a Todoist change produces
  no diff and no prune.

Usage
-----
    python tools/export_todoist_to_md.py --dry-run --target-dir /tmp/x
    python tools/export_todoist_to_md.py --target-dir /tmp/x        # real run
    python tools/export_todoist_to_md.py                            # live tickets_dir
    python tools/export_todoist_to_md.py --board cortex --no-prune
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from datetime import date
from pathlib import Path

# repo root on path so `config` / `backend` / `todoist_backend` import as on the
# live service (they use top-level imports, not a package).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfgmod  # noqa: E402
from backend import MarkdownBackend  # noqa: E402
from todoist_backend import TodoistBackend  # noqa: E402

# columns that get exported; `done`/archive are intentionally excluded so the
# md fallback mirrors the *active* Todoist board, never the graveyard. This is
# the exact mirror of migrate_md_to_todoist.MIGRATE_COLUMNS.
EXPORT_COLUMNS = ("backlog", "new", "inprogress", "testing")

# registry of exportable boards -> their BoardConfig (mirror of migrate's BOARDS).
BOARDS = {
    "cortex": cfgmod.CORTEX_BOARD,
}


def _file_id(board_cfg, tid: str) -> str:
    """The `file_re`-canonical id used in the *filename* (`T-27_slug.md`), which
    must be the bare `T-NN` even when the card's id carries a label like
    `"T-27 [EPIC]"`. The full label stays in the heading (so read-back via the
    H1 separator reproduces the labelled id exactly, matching Todoist). Falls
    back to the raw id when no canonical prefix is recognizable."""
    import re
    m = re.match(rf"^{re.escape(board_cfg.id_prefix)}-\d+[A-Za-z]?", tid)
    if m:
        return m.group(0)
    # cortex mixes T- and WD- ids; recognize any <ALPHA>-NN[suffix] head
    m = re.match(r"^[A-Za-z]+-\d+[A-Za-z]?", tid)
    return m.group(0) if m else tid


def _retarget(board_cfg, target_dir: Path | None):
    """Return a BoardConfig whose tickets_dir is `target_dir` (frozen dataclass
    -> replace), so a self-test never has to touch the live docs/tickets. With
    no target_dir the live config is used unchanged."""
    if target_dir is None:
        return board_cfg
    return dataclasses.replace(board_cfg, tickets_dir=Path(target_dir))


def _canonical_body(cfg, tid: str, title: str, status_word: str,
                    description: str, next_step: str,
                    existing_text: str | None) -> str:
    """Canonical .md content for one active card.

    Reuses MarkdownBackend's section layout (## Kontext / ## Next) and the
    `**Status:** <word>` line shape. If the file already exists we preserve its
    `**Erstellt:**` date (and keep the body stable) so re-export is diff-free;
    a fresh file gets today's date. Heading + status are always normalized to
    Todoist truth."""
    heading = f"# {tid} — {title}" if title else f"# {tid}"
    # preserve an existing Erstellt date so idempotent re-runs don't churn it
    created = date.today().isoformat()
    if existing_text:
        for line in existing_text.splitlines():
            s = line.strip()
            if s.lower().startswith("**erstellt:**"):
                created = s.split(":**", 1)[1].strip()
                break
    body: list[str] = [
        heading,
        "",
        f"**Status:** {status_word}",
        f"**Erstellt:** {created}",
        "",
    ]
    if description.strip():
        body += ["## Kontext", "", description.strip(), ""]
    if next_step.strip():
        body += ["## Next", "", next_step.strip(), ""]
    return "\n".join(body)


def export(board_key: str, target_dir: Path | None, dry_run: bool,
           prune: bool) -> int:
    board_cfg = _retarget(BOARDS[board_key], target_dir)
    md = MarkdownBackend(board_cfg)

    print(f"=== export_todoist_to_md  board={board_key}  "
          f"dry_run={dry_run}  prune={prune} ===")
    print(f"target tickets_dir: {board_cfg.tickets_dir}")
    print(f"source: todoist parent={board_cfg.todoist_parent!r} "
          f"project={board_cfg.todoist_project!r}")

    # ---- pull the active board state from Todoist ----
    todo = TodoistBackend(board_cfg)
    board = todo.read_board()
    print(f"todoist source: {board.get('source')}")

    # cards per exported column, keyed by id for prune diffing
    cards_by_col: dict[str, list[dict]] = {}
    todoist_ids: set[str] = set()
    total_src = 0
    for col in EXPORT_COLUMNS:
        cards = board.get(col, {}).get("tickets", [])
        cards_by_col[col] = cards
        for c in cards:
            todoist_ids.add(c["id"])
        total_src += len(cards)
        print(f"  todoist[{col:10s}] = {len(cards)}")
    print(f"  todoist[total]      = {total_src}")
    print(f"  (done not exported; todoist[done] = "
          f"{board.get('done', {}).get('count', 0)})")

    written = 0
    unchanged = 0
    # ---- write/update one active md file per Todoist card ----
    for col in EXPORT_COLUMNS:
        status_word = board_cfg.column_to_status[col]
        for card in cards_by_col[col]:
            tid = card["id"]  # full, possibly labelled ("T-27 [EPIC]")
            fid = _file_id(board_cfg, tid)  # bare, file_re-canonical ("T-27")
            # title field is the display title "T-NN — Title"; recover the bare
            # title via the backend's own parser so heading matches read-back.
            _id2, title = todo._parse_id_title(card["title"])
            description = card.get("description", "")
            next_step = card.get("next_step", "")

            existing_path = md._find_by_id(fid)
            existing_text = None
            if existing_path is not None:
                try:
                    existing_text = existing_path.read_text(encoding="utf-8")
                except Exception:
                    existing_text = None

            content = _canonical_body(
                board_cfg, tid, title, status_word, description, next_step,
                existing_text,
            )

            if existing_path is not None:
                path = existing_path
            else:
                slug = md._slugify(title or fid)
                path = board_cfg.tickets_dir / f"{fid}_{slug}.md"

            if existing_text is not None and existing_text == content:
                unchanged += 1
                continue

            verb = "WOULD-WRITE" if dry_run else "WRITE"
            tag = "update" if existing_path is not None else "create"
            print(f"  {verb} [{col:10s}] {tid} ({tag}) -> {path.name}")
            if not dry_run:
                md._atomic_write(path, content)
            written += 1

    # ---- prune: active md tickets that vanished from Todoist ----
    pruned = 0
    if prune:
        for p in md._iter_ticket_files():  # active top-level files ONLY
            # membership must be tested in Todoist's id space, which is the
            # *heading* id (labelled, e.g. "T-27 [EPIC]") — the same id
            # read_board projects — NOT the bare filename id, or labelled
            # tickets would be falsely pruned.
            t = md._parse_ticket(p)
            if not t:
                continue
            pid = t["id"]
            if pid in todoist_ids:
                continue
            # extra guard: never prune a file whose status maps to `done`
            if t.get("column") == "done":
                continue
            verb = "WOULD-PRUNE" if dry_run else "PRUNE"
            print(f"  {verb} [absent in todoist] {pid} -> {p.name}")
            if not dry_run:
                p.unlink()
            pruned += 1

    print("--- RESULT ---")
    for col in EXPORT_COLUMNS:
        print(f"  [{col:10s}] todoist={len(cards_by_col[col]):3d}")
    print(f"  written={written}  unchanged={unchanged}  "
          f"pruned={pruned}  (todoist active total={total_src})")
    if dry_run:
        print("--- DRY RUN: nothing written ---")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", default="cortex", choices=sorted(BOARDS),
                    help="which BoardConfig to export (default: cortex)")
    ap.add_argument("--target-dir", default=None,
                    help="override the board's tickets_dir (REQUIRED for a "
                         "self-test so the live docs/tickets stays untouched)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show planned writes/prunes, change nothing")
    ap.add_argument("--no-prune", dest="prune", action="store_false",
                    help="keep active md tickets that are absent from Todoist")
    ap.set_defaults(prune=True)
    args = ap.parse_args()
    target = Path(args.target_dir) if args.target_dir else None
    return export(args.board, target, args.dry_run, args.prune)


if __name__ == "__main__":
    raise SystemExit(main())

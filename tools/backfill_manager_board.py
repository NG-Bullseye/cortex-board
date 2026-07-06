#!/usr/bin/env python3
"""One-shot backfill (T-263): mirror every historical Cortex-board T-*.md ticket
into the Manager-Board as MB-NN.md.

Context: the Manager-/Coding-Agent-Board stages (T-260) were built AFTER these
35 T-tickets already existed on the Cortex board. Leo asked for a one-time
historical backfill so the Manager board has visibility into that backlog too
— NOT a recurring sync (the normal direction is Manager -> Coding-Agent ->
Cortex, this script runs the mirror once, backwards, then is done).

Strictly additive: reads ~/cortex/docs/tickets/T-*.md (skips INDEX.md,
README.md, EXECUTION_PLAN_*, RUNBOOK_*, and anything under archive/), never
touches the source ticket. For each source ticket, writes a NEW
MB-NN_<slug>.md into ~/repos/project-manager-agent/docs/tickets/ with:
  - fresh sequential MB-NN id (starting after the highest existing MB id, 0 today)
  - `# MB-NN — <original title, incl. any [cortex-b] lane tag>` heading
  - `Cortex-Ref: T-NN` back-ref header line (reverse-direction special case,
    see docs/board-chain-refs.md)
  - `**Status:** backlog` (Manager board always receives these as fresh backlog
    items regardless of the original Cortex-side status — Leo/manager decide
    from there whether/how to re-triage)
  - the original ticket's body verbatim below the header (no rewrording/cuts)

Run once, from repo root:
    python3 tools/backfill_manager_board.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CORTEX_TICKETS_DIR = Path.home() / "cortex" / "docs" / "tickets"
MANAGER_TICKETS_DIR = Path.home() / "repos" / "project-manager-agent" / "docs" / "tickets"

EXCLUDED_NAMES = {"INDEX.md", "README.md"}
EXCLUDED_PREFIXES = ("EXECUTION_PLAN_", "RUNBOOK_")

SOURCE_FILE_RE = re.compile(r"^(?P<id>T-\d+[A-Za-z]?)_?.*\.md$")
HEADING_RE = re.compile(r"^#\s+T-\d+[A-Za-z]?\s*[—–-]\s*(?P<title>.+?)\s*$", re.M)
EXISTING_MB_RE = re.compile(r"^MB-(\d+)")
CORTEX_REF_RE = re.compile(r"^Cortex-Ref:\s*(?P<id>T-\d+[A-Za-z]?)\s*$", re.M)


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9äöüß]+", "_", s)
    s = s.strip("_")
    return s[:60] or "ticket"


def iter_source_tickets() -> list[Path]:
    out = []
    for f in sorted(CORTEX_TICKETS_DIR.glob("T-*.md")):
        if f.name in EXCLUDED_NAMES:
            continue
        if any(f.name.startswith(p) for p in EXCLUDED_PREFIXES):
            continue
        if not SOURCE_FILE_RE.match(f.name):
            continue
        out.append(f)
    return out


def next_mb_start() -> int:
    highest = 0
    if MANAGER_TICKETS_DIR.exists():
        for f in MANAGER_TICKETS_DIR.glob("MB-*.md"):
            m = EXISTING_MB_RE.match(f.name)
            if m:
                highest = max(highest, int(m.group(1)))
    return highest + 1


def already_migrated_sources() -> set[str]:
    """T-NN ids that already have a migrated MB ticket, per `Cortex-Ref:` header.

    WARUM: a re-run computes a FRESH sequential MB-NN start (next_mb_start()
    just looks at the highest existing MB number), so the dest path for an
    already-migrated T-ticket differs from what's already on disk — the
    dest.exists() path check below never fires on a re-run and would happily
    write 35 duplicate MB-36..MB-70 tickets for the same 35 T-sources. The
    Cortex-Ref header is the only stable, content-based link back to the
    source, so it's the authoritative dedup check; the path check stays as
    a harmless extra safety net.
    """
    seen: set[str] = set()
    if not MANAGER_TICKETS_DIR.exists():
        return seen
    for f in MANAGER_TICKETS_DIR.glob("MB-*.md"):
        m = CORTEX_REF_RE.search(f.read_text())
        if m:
            seen.add(m.group("id"))
    return seen


def build_mb_ticket(source: Path, mb_id: str) -> tuple[str, str]:
    """Returns (filename, content) for the new MB ticket."""
    text = source.read_text()
    m = re.match(r"^(?P<id>T-\d+[A-Za-z]?)", source.name)
    src_id = m.group("id") if m else source.stem

    heading_m = HEADING_RE.search(text)
    title = heading_m.group("title") if heading_m else source.stem

    body = text
    if heading_m:
        # drop the original heading line; we replace it with our own MB heading
        body = text[heading_m.end():].lstrip("\n")
    # Drop the ORIGINAL Status line too — we stamp our own `**Status:** backlog`
    # right after the Cortex-Ref header; keeping both would leave two
    # `**Status:**` lines in one file (parser takes the first = ours, but it's
    # confusing to a human reader and looks like a doubled field).
    body = re.sub(r"^\*\*Status:\*\*[^\n]*\n?", "", body, count=1, flags=re.M)

    new_heading = f"# {mb_id} — {title}"
    content = (
        f"{new_heading}\n\n"
        f"Cortex-Ref: {src_id}\n"
        f"**Status:** backlog\n\n"
        f"{body}"
    )
    filename = f"{mb_id}_{slugify(title)}.md"
    return filename, content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sources = iter_source_tickets()
    if not sources:
        print("No source T-*.md tickets found — aborting.", file=sys.stderr)
        return 1

    migrated = already_migrated_sources()
    pending = []
    for src in sources:
        src_m = re.match(r"^(?P<id>T-\d+[A-Za-z]?)", src.name)
        src_id = src_m.group("id") if src_m else src.stem
        if src_id in migrated:
            print(f"SKIP (already migrated, Cortex-Ref match): {src.name}", file=sys.stderr)
            continue
        pending.append(src)

    start = next_mb_start()
    print(f"Found {len(sources)} source tickets, {len(pending)} pending "
          f"({len(sources) - len(pending)} already migrated). First new id: MB-{start:02d}")

    MANAGER_TICKETS_DIR.mkdir(parents=True, exist_ok=True)

    created = []
    for i, src in enumerate(pending):
        mb_id = f"MB-{start + i:02d}"
        filename, content = build_mb_ticket(src, mb_id)
        dest = MANAGER_TICKETS_DIR / filename
        if dest.exists():
            # Harmless extra safety net — see already_migrated_sources() WARUM
            # for why this path check alone is insufficient on a re-run.
            print(f"SKIP (exists): {dest}", file=sys.stderr)
            continue
        if args.dry_run:
            print(f"WOULD WRITE: {dest}  <- {src.name}")
        else:
            dest.write_text(content)
            print(f"WROTE: {dest}  <- {src.name}")
        created.append(dest)

    print(f"\n{'Would create' if args.dry_run else 'Created'} {len(created)} MB tickets "
          f"from {len(sources)} source tickets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

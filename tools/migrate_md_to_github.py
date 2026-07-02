#!/usr/bin/env python3
"""
Migrate md ticket files → GitHub Issues (SSOT).

One-shot script (idempotent — safe to re-run):
1. Parse each T-NN_*.md / WD-NN_*.md from ~/cortex/docs/tickets/
2. If a GitHub Issue with that ID already exists:
   - If it has no status:* label, add one matching the md status
   - Leave existing labeled issues alone (they're already managed via SSOT)
3. If no GitHub Issue exists: create one with the md content + status label
4. Archive the md file to archive/2026-07/

Usage:
    BOARD_BACKEND=github .venv/bin/python tools/migrate_md_to_github.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Ensure the cortex-board package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GITHUB_CORTEX_BOARD
from github_backend import GitHubBackend, STATUS_LABELS


def parse_md_ticket(path: Path) -> dict | None:
    """Parse a ticket md file, return {id, title, status_raw, column, description, next_step} or None."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    cfg = GITHUB_CORTEX_BOARD

    # Extract ID from filename
    m = cfg.file_re.match(path.name)
    if not m:
        return None
    tid = m.group("id")

    # Extract title from H1
    title = ""
    m_heading = cfg.heading_re.search(text)
    if m_heading:
        line = m_heading.group(1).strip()
        parts = cfg.sep_re.split(line, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() == tid:
            title = parts[1].strip()
        elif line.startswith(tid):
            title = line[len(tid):].lstrip(" —:-").strip()

    # Extract status
    status_raw = ""
    m_status = cfg.status_line_re.search(text)
    if m_status:
        status_raw = m_status.group(1).strip()
        status_raw = re.sub(r"[(),.\[\]]+$", "", status_raw).lower()

    # Map to column
    column = cfg.status_to_column.get(status_raw, "new")

    # Extract description: first meaningful paragraph block after metadata
    description = ""
    lines = text.splitlines()
    in_meta = True
    para: list[str] = []
    for line in lines:
        s = line.strip()
        if in_meta:
            if s.startswith("# "):
                in_meta = False
            continue
        if s.startswith("**") and ":**" in s[:80]:
            continue  # metadata line
        if s.startswith("## "):
            if para:
                break
            continue
        if not s:
            if para:
                break
            continue
        para.append(s)
    description = " ".join(para)

    # Extract next_step from ## Next section
    next_step = ""
    m_next = re.search(r"^##\s+Next\s*\n+(.*?)(?:^##\s|\Z)", text, re.M | re.S)
    if m_next:
        next_step = m_next.group(1).strip()

    return {
        "id": tid,
        "title": title,
        "status_raw": status_raw,
        "column": column,
        "description": description,
        "next_step": next_step,
        "path": path,
    }


def migrate(dry_run: bool = False) -> dict:
    """Run the migration. Returns stats dict."""
    tickets_dir = GITHUB_CORTEX_BOARD.tickets_dir
    archive_dir = tickets_dir / "archive" / "2026-07"
    backend = GitHubBackend(GITHUB_CORTEX_BOARD)

    # Pre-build index: ticket ID → GitHub issue (one gh call, not N)
    print("Indexing GitHub Issues...")
    all_issues = backend._cached_issues()
    issue_by_id: dict[str, dict] = {}
    for issue in all_issues:
        tid = backend._match_id(issue.get("title", ""))
        if tid:
            issue_by_id[tid] = issue
    print(f"  {len(issue_by_id)} IDs indexed from {len(all_issues)} issues")

    stats = {"created": 0, "updated": 0, "skipped": 0, "archived": 0, "errors": 0}

    md_files = sorted(
        [p for p in tickets_dir.glob("*.md")
         if p.name not in ("INDEX.md", "README.md")
         and not p.name.startswith("EXECUTION_PLAN_")
         and not p.name.startswith("RUNBOOK_")],
        key=lambda p: p.name,
    )
    print(f"\nProcessing {len(md_files)} md files...\n")

    for path in md_files:
        ticket = parse_md_ticket(path)
        if not ticket:
            print(f"  SKIP {path.name} — could not parse")
            stats["skipped"] += 1
            continue

        tid = ticket["id"]
        existing = issue_by_id.get(tid)  # O(1) lookup, no API call

        try:
            if existing:
                # Issue already exists — add status label if missing
                current_labels = {l["name"] for l in existing.get("labels", [])}
                has_status = any(lbl.startswith("status:") for lbl in current_labels)

                if not has_status:
                    new_label = STATUS_LABELS.get(ticket["column"], STATUS_LABELS["new"])
                    if not dry_run:
                        # Add status label; remove conflicting status labels just in case
                        args = ["issue", "edit", str(existing["number"]),
                                "--add-label", new_label]
                        # Also update body if the md has richer content
                        if ticket["description"] or ticket["next_step"]:
                            body = backend._compose_desc(ticket["description"], ticket["next_step"])
                            # Only update if issue body is empty or very short
                            existing_body = (existing.get("body") or "").strip()
                            if len(existing_body) < 50 and len(body) > 50:
                                args += ["--body", body]
                        from github_backend import _gh
                        _gh(*args, repo=backend._repo)

                    print(f"  LABEL {tid} (#{existing['number']}) → {new_label}")
                    stats["updated"] += 1
                else:
                    # Already has status label — issue is SSOT-managed
                    existing_status = [l for l in current_labels if l.startswith("status:")][0]
                    print(f"  OK   {tid} (#{existing['number']}) — already labeled {existing_status}")
                    stats["skipped"] += 1
            else:
                # No existing issue — create one
                title = ticket["title"] or tid
                new_label = STATUS_LABELS.get(ticket["column"], STATUS_LABELS["new"])
                issue_title = f"{tid} — {title}"

                body = backend._compose_desc(ticket["description"], ticket["next_step"])
                # Add a migration note
                body = f"*(Migrated from md ticket {path.name})*\n\n{body}" if body.strip() else f"*(Migrated from md ticket {path.name})*"

                if not dry_run:
                    result = backend.add_ticket(
                        title=title,
                        description=ticket["description"],
                        next_step=ticket["next_step"],
                    )
                    # The add_ticket always creates with status:new, but the md might
                    # have a different status — move if needed
                    if ticket["column"] != "new":
                        backend.move_ticket(tid, ticket["column"])
                    print(f"  CREATE {tid} (#{result['path']}) → {ticket['column']} \"{title[:50]}\"")
                else:
                    print(f"  CREATE {tid} → {ticket['column']} \"{title[:50]}\"")
                stats["created"] += 1

            # Archive the md file
            if not dry_run:
                archive_dir.mkdir(parents=True, exist_ok=True)
                dest = archive_dir / path.name
                shutil.move(str(path), str(dest))
                print(f"  ARCHIVE {path.name} → archive/2026-07/")
            stats["archived"] += 1

        except Exception as e:
            print(f"  ERROR {tid}: {e}")
            stats["errors"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate md tickets → GitHub Issues")
    parser.add_argument("--dry-run", action="store_true", help="Don't write, just preview")
    args = parser.parse_args()

    print(f"{'DRY RUN — ' if args.dry_run else ''}Migrating md tickets → GitHub Issues (NG-Bullseye/cortex)")
    print()

    stats = migrate(dry_run=args.dry_run)

    print()
    print(f"Done. created={stats['created']} updated={stats['updated']} "
          f"skipped={stats['skipped']} archived={stats['archived']} errors={stats['errors']}")


if __name__ == "__main__":
    main()

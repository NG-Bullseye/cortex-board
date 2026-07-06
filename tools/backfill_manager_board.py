#!/usr/bin/env python3
"""Manager-Board <- GitHub-Issues backfill (T-263, scope-corrected, round 4).

History: the first version of this script (T-263 v1) mirrored the 35
historical Cortex-board T-*.md tickets into MB-01..MB-35 with a
`Cortex-Ref: T-NN` back-ref, all stamped `backlog`. coding-agent then found
the real SSOT is not that local md directory but the GitHub Issues in
`NG-Bullseye/cortex` (T-NN AND WD-NN prefixes share one board there) — 303
issues total, ~197 open / ~106 closed. This version generalizes the source to
GitHub Issues and fixes two things the v1 backfill got wrong:

  1. The 35 already-migrated MB tickets are DEDUPED by title-matching their
     `Cortex-Ref: T-NN` header against the GitHub issue title (which embeds
     the same `T-NN` token) -- no duplicate MB ticket is created for them.
     Their status is corrected to match the *real* GitHub issue state (8 of
     them are actually CLOSED on GitHub despite v1 stamping everything
     `backlog`), and a `GitHub-Ref: #NNN` line is added alongside the existing
     `Cortex-Ref: T-NN` so future runs can dedup off the single GitHub-Ref key
     like every other ticket.
  2. Every remaining GitHub issue (open or closed, T-NN or WD-NN, ~268 today)
     gets a new MB-NN ticket: `GitHub-Ref: #NNN` back-ref (see
     docs/board-chain-refs.md "Sonderfall: GitHub-Ref"), body = the issue body
     verbatim, status per `status_for_issue()`:
       - CLOSED               -> `done`
       - OPEN, in MOVED_TO_MANAGER_ONLY (23 tickets Leo confirmed round 4,
         removed from the Cortex board, exist only here now) -> `new`
       - OPEN, everything else (~174) -> `backlog` (still live on the Cortex
         board too; this MB copy is awareness only, not a fresh-intake item)

Idempotent: the single dedup key across every MB-*.md file is `GitHub-Ref:
#NNN`. A re-run only touches status lines that drifted (issue closed since
last run, or the moved-only set changes) and never re-creates or duplicates
a ticket.

Run once from repo root:
    python3 tools/backfill_manager_board.py [--dry-run]

Requires `gh` authenticated against NG-Bullseye/cortex.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = "NG-Bullseye/cortex"

# T-263 round 4 (Leo-bestätigt): these 23 T-tickets were removed from the
# Cortex board (~/cortex/docs/tickets/) because they were unbearbeitete
# GitHub-only neuanlagen never delegated to cortex — they now exist ONLY on
# the Manager board, so they alone get `new` (Manager board's dedicated
# fresh-ticket column). Every OTHER still-open GitHub issue keeps its T-/WD-
# ticket alive on the Cortex board too and gets `backlog` here instead (it's
# already tracked live elsewhere, this MB copy is just visibility/awareness).
# Closed issues are unaffected (`done` regardless of this set).
MOVED_TO_MANAGER_ONLY = {
    "T-186", "T-187", "T-188", "T-190", "T-191", "T-192", "T-193", "T-198",
    "T-199", "T-200", "T-201", "T-202", "T-203", "T-204", "T-205", "T-206",
    "T-207", "T-209", "T-210", "T-211", "T-212", "T-214", "T-216",
}
# Overridable so a worktree checkout of project-manager-agent (recommended when
# the shared live checkout has foreign uncommitted WIP, see T-263 v2 report)
# can be targeted without touching the primary working tree.
MANAGER_TICKETS_DIR = Path(
    os.environ.get("MANAGER_TICKETS_DIR")
    or (Path.home() / "repos" / "project-manager-agent" / "docs" / "tickets")
)

EXISTING_MB_RE = re.compile(r"^MB-(\d+)")
CORTEX_REF_RE = re.compile(r"^Cortex-Ref:\s*(?P<id>T-\d+[A-Za-z]?)\s*$", re.M)
GITHUB_REF_RE = re.compile(r"^GitHub-Ref:\s*#(?P<num>\d+)\s*$", re.M)
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(?P<status>\S+)\s*$", re.M)
TITLE_TID_RE = re.compile(r"\b(T-\d+|WD-\d+)\b")


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9äöüß]+", "_", s)
    s = s.strip("_")
    return s[:60] or "ticket"


def fetch_issues() -> list[dict]:
    out = subprocess.run(
        [
            "gh", "issue", "list", "--repo", REPO, "--state", "all",
            "--limit", "500", "--json", "number,title,state,body",
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def existing_mb_files() -> list[Path]:
    if not MANAGER_TICKETS_DIR.exists():
        return []
    return sorted(MANAGER_TICKETS_DIR.glob("MB-*.md"))


def next_mb_start(files: list[Path]) -> int:
    highest = 0
    for f in files:
        m = EXISTING_MB_RE.match(f.name)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def status_for_issue(issue: dict) -> str:
    """`done` for CLOSED, `new` only for the 23 moved-only tickets, else `backlog`."""
    if issue["state"] == "CLOSED":
        return "done"
    m = TITLE_TID_RE.search(issue["title"])
    if m and m.group(1) in MOVED_TO_MANAGER_ONLY:
        return "new"
    return "backlog"


def build_new_ticket(mb_id: str, issue: dict) -> tuple[str, str]:
    title = issue["title"]
    status = status_for_issue(issue)
    body = (issue.get("body") or "").strip() or "_(kein Issue-Body)_"
    content = (
        f"# {mb_id} — {title}\n\n"
        f"GitHub-Ref: #{issue['number']}\n"
        f"**Status:** {status}\n\n"
        f"{body}\n"
    )
    filename = f"{mb_id}_{slugify(title)}.md"
    return filename, content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    issues = fetch_issues()
    title_map: dict[str, dict] = {}
    for it in issues:
        m = TITLE_TID_RE.search(it["title"])
        if m:
            title_map[m.group(1)] = it
    print(f"Fetched {len(issues)} GitHub issues from {REPO} "
          f"({sum(1 for i in issues if i['state']=='OPEN')} open / "
          f"{sum(1 for i in issues if i['state']=='CLOSED')} closed).",
          file=sys.stderr)

    files = existing_mb_files()

    covered_issue_nums: set[int] = set()
    status_fixes = []  # (path, old_status, new_status, issue_number)

    for f in files:
        text = f.read_text()
        gh_m = GITHUB_REF_RE.search(text)
        issue = None
        new_text = text

        if gh_m:
            issue_num = int(gh_m.group("num"))
            issue = next((it for it in issues if it["number"] == issue_num), None)
            if issue is None:
                print(f"WARN: GitHub-Ref #{issue_num} in {f.name} not found among "
                      f"fetched issues (deleted/renumbered?)", file=sys.stderr)
                covered_issue_nums.add(issue_num)
                continue
        else:
            cr_m = CORTEX_REF_RE.search(text)
            if not cr_m:
                continue
            tid = cr_m.group("id")
            issue = title_map.get(tid)
            if not issue:
                print(f"WARN: no GitHub issue title-matches {tid} for {f.name}", file=sys.stderr)
                continue
            # add GitHub-Ref right after the Cortex-Ref line for future-proof dedup
            new_text = new_text.replace(
                cr_m.group(0), f"{cr_m.group(0)}\nGitHub-Ref: #{issue['number']}", 1
            )

        covered_issue_nums.add(issue["number"])
        real_status = status_for_issue(issue)
        st_m = STATUS_RE.search(text)
        cur_status = st_m.group("status") if st_m else None
        if cur_status != real_status:
            new_text = STATUS_RE.sub(f"**Status:** {real_status}", new_text, count=1)
            status_fixes.append((f, cur_status, real_status, issue["number"]))
        if new_text != text:
            if args.dry_run:
                print(f"WOULD UPDATE: {f.name} (status {cur_status} -> {real_status}, "
                      f"GitHub-Ref #{issue['number']})")
            else:
                f.write_text(new_text)
                print(f"UPDATED: {f.name} (status {cur_status} -> {real_status}, "
                      f"GitHub-Ref #{issue['number']})")

    pending_issues = [it for it in issues if it["number"] not in covered_issue_nums]
    start = next_mb_start(files)
    print(f"\n{len(covered_issue_nums)} issues already covered by existing MB tickets, "
          f"{len(pending_issues)} pending new tickets. First new id: MB-{start:02d}",
          file=sys.stderr)

    MANAGER_TICKETS_DIR.mkdir(parents=True, exist_ok=True)
    created = []
    for i, issue in enumerate(pending_issues):
        mb_id = f"MB-{start + i:02d}"
        filename, content = build_new_ticket(mb_id, issue)
        dest = MANAGER_TICKETS_DIR / filename
        if dest.exists():
            print(f"SKIP (exists): {dest}", file=sys.stderr)
            continue
        if args.dry_run:
            print(f"WOULD WRITE: {dest}  <- issue #{issue['number']}")
        else:
            dest.write_text(content)
            print(f"WROTE: {dest}  <- issue #{issue['number']}")
        created.append(dest)

    print(f"\n{'Would fix' if args.dry_run else 'Fixed'} {len(status_fixes)} status "
          f"mismatches on existing tickets.")
    for f, old, new, num in status_fixes:
        print(f"  {f.name}: {old} -> {new} (issue #{num})")
    print(f"{'Would create' if args.dry_run else 'Created'} {len(created)} new MB tickets "
          f"from {len(issues)} total GitHub issues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

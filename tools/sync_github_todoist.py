#!/usr/bin/env python3
"""
sync_github_todoist.py — GitHub Issues -> Todoist Sync (one-way).

RETIRED-then-restructured (T-251 disabled it, T-257 removed the reverse
direction from the code): this used to be a bidirectional GitHub<->Todoist
mirror (project "cortex"). It is superseded in production by
tools/sync_md_to_todoist.py, the one-way md->Todoist mirror (--board cortex
-> "coding-agent-a", --board cortex-b -> "coding-agent-b"), which is the
approved SSOT mirror per Leo's "Todoist-Struktur ist SSOT" call, and per
T-257's binding directive that every board has exactly ONE local source and
syncs in exactly ONE direction (local -> Todoist), no exceptions.

Its systemd timer (sync-github-todoist.timer, every 5min) has been
`systemctl --user disable --now`'d (T-251). Root-cause evidence for the
retire: every single run since the timer last started (Jul 02 18:04,
1055/1055 in journalctl) failed with HTTP 403 MAX_ITEMS_LIMIT_REACHED
before ever persisting ~/.cache/board/github_todoist_sync.json — the old
reverse (Todoist-checkbox -> GitHub-close) path never successfully fired
even once in the observable history. Meanwhile it kept creating tasks in a
separate Todoist project ("cortex") in parallel with sync_md_to_todoist's
"coding-agent-a"/"coding-agent-b" projects, duplicating tickets (confirmed
live: T-221 existed in both "cortex" and "coding-agent-a"). That silent
double-mirror is the likely root cause of the original Todoist chaos that
led to T-251 in the first place.

T-257 removed `sync_todoist_to_github()` (the Todoist -> GitHub write-back:
label edits, issue create/close/reopen) structurally, so re-enabling the
timer can never reintroduce bidirectionality by accident — this script now
can only read GitHub Issues and write Todoist tasks. Script + unit files
stay in place as a dormant reference; the MAX_ITEMS_LIMIT_REACHED loop and
the "cortex" project double-mirror still need a decision (Leo/coding-agent)
before this is ever pointed at production again. The stale "cortex" Todoist
project itself was left untouched (frozen snapshot, not deleted) — that's a
Todoist-data decision, out of scope for this code change.

Direction (GitHub → Todoist, one-way):
    New/updated GitHub Issue → upsert Todoist task in the board project.
    Closed issue → complete Todoist task.
    Todoist task with no matching open GitHub Issue → complete it (cleanup).

Sync state: ~/.cache/board/github_todoist_sync.json
    {issue_number: {todoist_id, gh_hash, todoist_hash, last_sync}}
    (todoist_hash is kept only as a bookkeeping field; nothing reads it to
    drive a write back to GitHub anymore.)

Usage:
    python tools/sync_github_todoist.py --dry-run
    python tools/sync_github_todoist.py
    python tools/sync_github_todoist.py --board cortex
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BOARDS, BoardConfig, GITHUB_CORTEX_BOARD
from github_backend import GitHubBackend
from todoist_backend import TodoistBackend


# ---- Sync state -----------------------------------------------------------
STATE_DIR = Path.home() / ".cache" / "board"
STATE_FILE = STATE_DIR / "github_todoist_sync.json"


def load_state() -> dict:
    """Load sync state: {issue_number: {todoist_id, gh_hash, todoist_hash, last_sync}}."""
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def content_hash(title: str, body: str, status: str) -> str:
    """Stable hash of the content fields we sync."""
    raw = f"{title}\0{body or ''}\0{status}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---- Lane filtering (T-251) -------------------------------------------------
# CORTEX_B_BOARD (Lane B) and GITHUB_CORTEX_BOARD (Lane A) share one GitHub
# Issues source (NG-Bullseye/cortex) but must land in different Todoist
# projects (coding-agent-b vs cortex) and never both pick up the same issue.
# `BoardConfig.title_tag` / `title_tag_exclude` (set per-board in config.py)
# say which lane an issue belongs to purely by a title substring — no new
# framework, just a filter applied once before either sync direction runs.
def _issue_in_lane(cfg: BoardConfig, title: str) -> bool:
    if cfg.title_tag is not None:
        return cfg.title_tag in title
    if cfg.title_tag_exclude is not None:
        return cfg.title_tag_exclude not in title
    return True


# ---- Issue/Task helpers ----------------------------------------------------

def issue_to_hash(issue: dict, column: str) -> str:
    """Compute content hash of a GitHub Issue for sync comparison."""
    title = issue.get("title", "")
    body = issue.get("body") or ""
    return content_hash(title, body, column)


def todoist_task_to_hash(task: dict, column: str) -> str:
    """Compute content hash of a Todoist task for sync comparison."""
    title = task.get("content", "")
    body = task.get("description") or ""
    return content_hash(title, body, column)


# ---- Sync logic -----------------------------------------------------------


def sync_github_to_todoist(
    gh_backend: GitHubBackend,
    td_backend: TodoistBackend,
    state: dict,
    dry_run: bool = False,
) -> dict:
    """Push GitHub Issues → Todoist. Returns stats."""
    stats = {"created": 0, "updated": 0, "completed": 0, "skipped": 0}

    # Ensure Todoist project/sections exist
    td_info = td_backend.provision()
    project_id = td_info["project_id"]
    sections = td_info["sections"]  # {column: section_id}
    col_to_section = sections
    section_to_col = {sid: col for col, sid in sections.items()}

    # Get all Todoist tasks in the project
    td_tasks = td_backend._client.list_tasks(project_id)
    td_by_id: dict[str, dict] = {}  # todoist task id → task
    td_by_ticket_id: dict[str, dict] = {}  # T-NN → task
    for task in td_tasks:
        td_by_id[task["id"]] = task
        tid, _ = td_backend._parse_id_title(task.get("content", ""))
        if tid:
            td_by_ticket_id[tid] = task

    # Get all GitHub Issues, filtered to this board's lane (T-251)
    gh_issues = {i["number"]: i for i in gh_backend._cached_issues()}
    gh_by_id: dict[str, dict] = {}
    for issue in gh_issues.values():
        tid = gh_backend._match_id(issue.get("title", ""))
        if tid and _issue_in_lane(gh_backend.config, issue.get("title", "")):
            gh_by_id[tid] = issue

    # Direction 1: GitHub → Todoist
    for tid, issue in gh_by_id.items():
        column = gh_backend._status_column(issue)
        title = issue.get("title", "")
        body = issue.get("body") or ""
        gh_hash = issue_to_hash(issue, column)
        issue_num = str(issue["number"])

        # Load previous state
        prev = state.get(issue_num, {})
        prev_gh_hash = prev.get("gh_hash", "")
        prev_td_hash = prev.get("todoist_hash", "")
        td_task_id = prev.get("todoist_id")

        # Check if task still exists in Todoist
        td_task = td_by_id.get(td_task_id) if td_task_id else None

        # If no Todoist task mapping exists, try to find by ticket ID
        if not td_task:
            td_task = td_by_ticket_id.get(tid)

        if gh_hash == prev_gh_hash:
            # GitHub didn't change since last sync → skip GitHub→Todoist push
            stats["skipped"] += 1
            # Still update state with current td_task info
            if td_task:
                state[issue_num] = {
                    "todoist_id": td_task["id"],
                    "gh_hash": gh_hash,
                    "todoist_hash": prev_td_hash,  # will be updated in reverse pass
                    "last_sync": time.time(),
                }
            continue

        target_section_id = col_to_section.get(column, col_to_section.get("new"))

        if td_task:
            # Update existing Todoist task
            td_task_id = td_task["id"]
            td_col = section_to_col.get(td_task.get("section_id"), "")
            td_hash = todoist_task_to_hash(td_task, td_col)

            # Check if actual update needed
            current_content = td_task.get("content", "")
            current_section = td_task.get("section_id", "")

            if current_content != title or current_section != target_section_id:
                if not dry_run:
                    td_backend._client.update_task(td_task_id, content=title)
                    if current_section != target_section_id:
                        td_backend._client.move_task(td_task_id, target_section_id)
                stats["updated"] += 1
                print(f"  TODOIST↑ {tid}: updated (column={column})")
            else:
                stats["skipped"] += 1

            state[issue_num] = {
                "todoist_id": td_task_id,
                "gh_hash": gh_hash,
                "todoist_hash": td_hash,
                "last_sync": time.time(),
            }
        else:
            # Create new Todoist task
            if not dry_run:
                created = td_backend._client.add_task(
                    content=title,
                    project_id=project_id,
                    section_id=target_section_id or list(sections.values())[0],
                )
                td_task_id = created["id"]
                state[issue_num] = {
                    "todoist_id": td_task_id,
                    "gh_hash": gh_hash,
                    "todoist_hash": content_hash(title, "", column),
                    "last_sync": time.time(),
                }
            stats["created"] += 1
            print(f"  TODOIST+ {tid}: created → {column}")

        # Handle closed/completed issues
        if column == "done" and td_task:
            if not dry_run and not td_task.get("is_completed"):
                td_backend._client._request("POST", f"tasks/{td_task['id']}/close")
                stats["completed"] += 1
                print(f"  TODOIST✓ {tid}: completed")

    # Handle issues that were removed (closed since last sync, or deleted)
    # Tasks in Todoist that no longer have an open GitHub Issue → complete them
    for td_task in td_tasks:
        tid, _ = td_backend._parse_id_title(td_task.get("content", ""))
        if tid and tid not in gh_by_id and not td_task.get("is_completed"):
            if not dry_run:
                td_backend._client._request("POST", f"tasks/{td_task['id']}/close")
                stats["completed"] += 1
                print(f"  TODOIST✓ {tid}: completed (no matching GitHub Issue)")

    return stats


def sync(board_name: str = "cortex-github", dry_run: bool = False) -> dict:
    """Run a one-way GitHub -> Todoist sync (T-257: no reverse direction).

    Returns stats. This never writes to GitHub Issues — see the module
    docstring for why `sync_todoist_to_github()` was removed entirely
    rather than merely left unused.
    """
    cfg = BOARDS.get(board_name)
    if not cfg:
        print(f"Unknown board: {board_name}. Choices: {sorted(BOARDS)}")
        return {}

    gh_backend = GitHubBackend(cfg)
    td_backend = TodoistBackend(cfg)

    state = load_state()
    print(f"State: {len(state)} tracked items")

    print("\n── GitHub → Todoist ──")
    stats = sync_github_to_todoist(gh_backend, td_backend, state, dry_run=dry_run)

    if not dry_run:
        save_state(state)
        print(f"\nState saved: {len(state)} items")

    stats["total"] = sum(stats.values())
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="GitHub Issues -> Todoist sync (one-way, T-257)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--board", default="cortex-github",
                        choices=sorted(BOARDS),
                        help="Board to sync (default: cortex-github)")
    args = parser.parse_args()

    print(f"{'DRY RUN — ' if args.dry_run else ''}"
          f"Syncing {args.board} (GitHub → Todoist, one-way)\n")

    stats = sync(board_name=args.board, dry_run=args.dry_run)

    print(f"\nDone. created={stats.get('created',0)} updated={stats.get('updated',0)} "
          f"completed={stats.get('completed',0)} skipped={stats.get('skipped',0)} "
          f"total={stats.get('total',0)}")


if __name__ == "__main__":
    main()

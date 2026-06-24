#!/usr/bin/env python3
"""
T-2 Phase 2a smoketest — exercises TodoistBackend against a *throwaway*
sub-project `boards/_smoketest` (NEVER Leo's real boards/cortex), runs the full
lifecycle, asserts the return contracts match MarkdownBackend's shape, then
deletes the throwaway project so Todoist is left exactly as it was found.

Runs only when a Todoist token is reachable (env TODOIST_API_KEY or
~/.claude/mcp.json); otherwise SKIPs with exit 0. Self-cleaning: the throwaway
project is deleted in a finally block even on failure. Exit 0 == green.

No token value is ever printed.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CORTEX_BOARD  # noqa: E402
from todoist_backend import TodoistBackend, TodoistClient, resolve_token, TodoistError  # noqa: E402

SMOKE_PROJECT = "_smoketest"


def _fail(msg: str):
    raise AssertionError(msg)


def main() -> int:
    try:
        token = resolve_token()
    except Exception as e:
        print(f"SKIP: no Todoist token available ({type(e).__name__}); not running.")
        return 0

    # Throwaway board config: same parent ("boards"), but a sandbox sub-project.
    cfg = dataclasses.replace(CORTEX_BOARD, todoist_project=SMOKE_PROJECT)
    client = TodoistClient(token)
    be = TodoistBackend(cfg, client=client)

    project_id = None
    try:
        # 1. provision (idempotent — call twice, expect identical resolution)
        prov1 = be.provision()
        project_id = prov1["project_id"]
        be2 = TodoistBackend(cfg, client=client)
        prov2 = be2.provision()
        assert prov2["project_id"] == project_id, "provision not idempotent (project)"
        assert prov2["sections"] == prov1["sections"], "provision not idempotent (sections)"
        assert set(prov1["sections"]) == set(cfg.columns), "missing column sections"
        print(f"OK provision: project={project_id} sections={list(prov1['sections'])}")

        # 2. read empty board — contract check
        b0 = be.read_board()
        assert b0["columns"] == list(cfg.columns), "columns mismatch"
        assert b0["source"] == f"todoist:{project_id}"
        for c in cfg.columns:
            col = b0[c]
            assert set(col) == {"column", "rev", "count", "tickets"}, f"col {c} keys"
            assert col["count"] == 0 and col["tickets"] == []
        print("OK read_board (empty) contract")

        # 3. add_ticket
        add = be.add_ticket("Smoke Feature", description="ctx body", next_step="do the next thing")
        assert set(add) == {"id", "title", "path", "column"}, f"add keys {set(add)}"
        assert add["column"] == "new"
        assert add["title"] == "Smoke Feature"
        assert add["path"].startswith("todoist:")
        tid = add["id"]
        print(f"OK add_ticket: {tid} {add['path']}")

        # 4. projected into 'new' with title/desc/next_step recovered
        cnew = be.read_column("new")
        card = next((t for t in cnew["tickets"] if t["id"] == tid), None)
        assert card is not None, "added card not projected into 'new'"
        assert set(card) == {"id", "title", "description", "next_step"}, f"card keys {set(card)}"
        assert card["title"] == f"{tid} — Smoke Feature"
        assert card["description"] == "ctx body", card["description"]
        assert card["next_step"] == "do the next thing", card["next_step"]
        print(f"OK read_column projection: {card}")

        # 5. move_ticket new -> inprogress
        mv = be.move_ticket(tid, "inprogress")
        assert set(mv) == {"id", "to_column", "path"}, f"move keys {set(mv)}"
        assert mv["to_column"] == "inprogress"
        cip = be.read_column("inprogress")
        assert any(t["id"] == tid for t in cip["tickets"]), "card not in inprogress after move"
        assert all(t["id"] != tid for t in be.read_column("new")["tickets"]), "card still in new"
        print("OK move_ticket new->inprogress")

        # 6. update_ticket (title + next_step; description preserved)
        up = be.update_ticket(tid, title="Smoke Renamed", next_step="updated step")
        assert set(up) == {"id", "path"}, f"update keys {set(up)}"
        card2 = next(t for t in be.read_column("inprogress")["tickets"] if t["id"] == tid)
        assert card2["title"] == f"{tid} — Smoke Renamed", card2["title"]
        assert card2["description"] == "ctx body", card2["description"]
        assert card2["next_step"] == "updated step", card2["next_step"]
        print("OK update_ticket (title+next_step, desc preserved)")

        # 7. next free id respects existing tasks (add a second)
        add2 = be.add_ticket("Second")
        assert add2["id"] != tid, "next_id collided"
        print(f"OK next_id: second ticket {add2['id']}")

        # 8. remove_ticket
        rm = be.remove_ticket(tid)
        assert set(rm) == {"id", "removed_path"}, f"remove keys {set(rm)}"
        assert rm["removed_path"].startswith("todoist:")
        assert all(t["id"] != tid for t in be.read_board()["inprogress"]["tickets"]), "not removed"
        be.remove_ticket(add2["id"])
        print("OK remove_ticket")

        print("\nSMOKETEST GREEN: TodoistBackend full lifecycle passed")
        return 0
    finally:
        if project_id:
            try:
                client.delete_project(project_id)
                print(f"CLEANUP: deleted throwaway project {project_id}")
            except TodoistError as e:
                print(f"CLEANUP WARNING: could not delete {project_id}: {e}")


if __name__ == "__main__":
    sys.exit(main())

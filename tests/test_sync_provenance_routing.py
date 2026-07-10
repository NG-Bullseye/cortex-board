#!/usr/bin/env python3
"""
T-297 — provenance-based Todoist routing, MANAGER_BOARD-only.

Exercises `tools/sync_md_to_todoist.build_plan` against a fake, fully
in-memory Todoist client (no network, no real Todoist project is ever
touched) so the routing logic can be verified without a token and without
any risk of mutating Leo's live board.

Covers:
  1. `Provenance: leo-direct` ticket -> still routes to its status-column
     section (unchanged behaviour).
  2. `Provenance: self` ticket        -> routes to the fixed "maintainance"
     section regardless of status column.
  3. ticket with NO Provenance line   -> defaults to "maintainance" too.
  4. a non-MANAGER_BOARD config (no `provenance_section` set) keeps routing
     straight to the status column — proves the feature is opt-in / scoped.

Exit 0 == green.
"""
from __future__ import annotations

import dataclasses
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import MANAGER_BOARD, CORTEX_BOARD  # noqa: E402
from todoist_backend import TodoistBackend  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from sync_md_to_todoist import build_plan  # noqa: E402

MAINT_SECTION_ID = "6h4fX65xc9JhrCGX"


class FakeClient:
    """Minimal in-memory stand-in for TodoistClient — no HTTP, ever."""

    def __init__(self) -> None:
        self._projects: dict[str, dict] = {}
        self._sections: dict[str, list[dict]] = {}
        self._tasks: dict[str, dict] = {}
        self._next_id = 1

    def _fresh_id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}{self._next_id}"

    # ---- projects ---
    def list_projects(self) -> list[dict]:
        return list(self._projects.values())

    def add_project(self, name: str, parent_id: str | None = None) -> dict:
        pid = self._fresh_id("proj")
        p = {"id": pid, "name": name, "parent_id": parent_id}
        self._projects[pid] = p
        self._sections[pid] = []
        return p

    # ---- sections ---
    def list_sections(self, project_id: str) -> list[dict]:
        return list(self._sections.get(project_id, []))

    def add_section(self, name: str, project_id: str) -> dict:
        sid = self._fresh_id("sec")
        s = {"id": sid, "name": name, "project_id": project_id}
        self._sections.setdefault(project_id, []).append(s)
        return s

    # ---- tasks ---
    def list_tasks(self, project_id: str) -> list[dict]:
        return [t for t in self._tasks.values() if t.get("project_id") == project_id]

    def add_task(self, content: str, project_id: str, section_id: str,
                 description: str = "") -> dict:
        tid = self._fresh_id("task")
        t = {
            "id": tid, "content": content, "project_id": project_id,
            "section_id": section_id, "description": description,
        }
        self._tasks[tid] = t
        return t

    def update_task(self, task_id: str, **fields) -> dict:
        self._tasks[task_id].update(fields)
        return self._tasks[task_id]

    def move_task(self, task_id: str, section_id: str) -> dict:
        self._tasks[task_id]["section_id"] = section_id
        return self._tasks[task_id]

    def delete_task(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)


TICKETS = {
    # 1. leo-direct, status "new" -> stays in the "new" status section.
    "MB-1_leo_direct_new.md": (
        "# MB-1 — Leo direct new\n\n"
        "**Status:** new\n"
        "Provenance: leo-direct\n\n"
        "Something Leo asked for directly.\n"
    ),
    # 2. explicit self, status "inprogress" -> routes to maintainance anyway.
    "MB-2_self_inprogress.md": (
        "# MB-2 — Self-generated inprogress\n\n"
        "**Status:** inprogress\n"
        "Provenance: self\n\n"
        "Backfill housekeeping ticket.\n"
    ),
    # 3. no Provenance line at all, status "testing" -> defaults to maintainance.
    "MB-3_no_provenance.md": (
        "# MB-3 — No provenance line\n\n"
        "**Status:** testing\n\n"
        "Legacy ticket predating the Provenance convention.\n"
    ),
}


def _fail(msg: str):
    raise AssertionError(msg)


def main() -> int:
    tdir = Path(tempfile.mkdtemp(prefix="mb_provenance_"))
    for name, content in TICKETS.items():
        (tdir / name).write_text(content, encoding="utf-8")

    cfg = dataclasses.replace(
        MANAGER_BOARD,
        tickets_dir=tdir,
        todoist_extra_sections={"maintainance": MAINT_SECTION_ID},
        provenance_section="maintainance",
    )
    client = FakeClient()
    backend = TodoistBackend(cfg, client=client)

    creates, updates, trashes, sections, project_id = build_plan(cfg, backend, only=None)

    assert sections["maintainance"] == MAINT_SECTION_ID, sections
    by_id = {card["id"]: col for col, card in creates}

    assert by_id["MB-1"] == "new", f"leo-direct ticket misrouted: {by_id}"
    print("OK: Provenance: leo-direct -> status section ('new')")

    assert by_id["MB-2"] == "maintainance", f"self ticket misrouted: {by_id}"
    print("OK: Provenance: self -> maintainance (ignores status 'inprogress')")

    assert by_id["MB-3"] == "maintainance", f"no-provenance ticket misrouted: {by_id}"
    print("OK: missing Provenance line -> defaults to maintainance")

    # section_id resolution: MB-1 goes to the real 'new' column section (a
    # fresh in-memory id), MB-2/MB-3 both resolve to the *same* fixed id.
    assert sections["maintainance"] == MAINT_SECTION_ID
    assert sections["new"] != MAINT_SECTION_ID
    print("OK: maintainance section id is the fixed pre-provisioned id, not auto-created")

    # ---- scope check: a board with no provenance_section keeps old behaviour ---
    tdir2 = Path(tempfile.mkdtemp(prefix="cortex_no_provenance_"))
    (tdir2 / "T-1_plain.md").write_text(
        "# T-1 — Plain ticket\n\n**Status:** new\n\nNo provenance opt-in on this board.\n",
        encoding="utf-8",
    )
    cfg2 = dataclasses.replace(CORTEX_BOARD, tickets_dir=tdir2)
    assert cfg2.provenance_section is None, "CORTEX_BOARD must not opt into provenance routing"
    client2 = FakeClient()
    backend2 = TodoistBackend(cfg2, client=client2)
    creates2, _, _, _, _ = build_plan(cfg2, backend2, only=None)
    col2 = {card["id"]: col for col, card in creates2}["T-1"]
    assert col2 == "new", f"non-opted-in board routing changed: {col2}"
    print("OK: board without provenance_section (e.g. CORTEX_BOARD) routes unchanged")

    print("\nALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
T-303 — release-gate Todoist routing, MANAGER_BOARD-only, orthogonal to T-297's
provenance axis.

Exercises `tools/sync_md_to_todoist.build_plan` against a fake, fully
in-memory Todoist client (no network, no real Todoist project is ever
touched) so the routing logic can be verified without a token and without
any risk of mutating Leo's live board.

Covers:
  1. `Release: pending` ticket           -> routes to the fixed
     "wartet auf Freigabe" section regardless of status column/provenance.
  2. `Release: pending` + `Provenance: leo-direct` -> release gate still wins
     (checked before provenance).
  3. ticket with NO Release line          -> falls through to normal routing
     (provenance routing still applies on MANAGER_BOARD, same as T-297) — the
     gate is opt-in, so every ticket predating the marker is unaffected by it.
  4. `Release: pending` flips away (marker removed) -> ticket moves OUT of
     "wartet auf Freigabe" back to its normal target on the next sync
     (idempotent col_change, same mechanism as a provenance flip).
  5. a non-MANAGER_BOARD config (no `release_pending_section` set) ignores
     `Release: pending` entirely — proves the feature is opt-in / scoped.
  6. the "wartet auf Freigabe" section is auto-provisioned by name (no
     pre-existing hand-created id required, unlike T-297's "maintainance").

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
    # 1. captured, not yet released -> "wartet auf Freigabe" regardless of
    # its status column ("inprogress").
    "MB-1_captured_pending.md": (
        "# MB-1 — Captured, pending release\n\n"
        "**Status:** inprogress\n"
        "Release: pending\n\n"
        "Phase-1 capture, no Leo command yet.\n"
    ),
    # 2. pending release AND leo-direct provenance -> release gate wins.
    "MB-2_pending_leo_direct.md": (
        "# MB-2 — Pending, leo-direct\n\n"
        "**Status:** new\n"
        "Release: pending\n"
        "Provenance: leo-direct\n\n"
        "Leo asked directly but hasn't said 'schick los' yet.\n"
    ),
    # 3. no Release line at all -> normal routing (status column).
    "MB-3_no_release_marker.md": (
        "# MB-3 — No release marker\n\n"
        "**Status:** testing\n\n"
        "Legacy ticket predating the Release convention.\n"
    ),
}


def _fail(msg: str):
    raise AssertionError(msg)


def main() -> int:
    tdir = Path(tempfile.mkdtemp(prefix="mb_release_gate_"))
    for name, content in TICKETS.items():
        (tdir / name).write_text(content, encoding="utf-8")

    cfg = dataclasses.replace(
        MANAGER_BOARD,
        tickets_dir=tdir,
        todoist_extra_sections={"maintainance": MAINT_SECTION_ID},
        provenance_section="maintainance",
        release_pending_section="wartet auf Freigabe",
    )
    client = FakeClient()
    backend = TodoistBackend(cfg, client=client)

    creates, updates, trashes, sections, project_id = build_plan(cfg, backend, only=None)

    # 6. auto-provisioned by name, no manual id needed.
    assert "wartet auf Freigabe" in sections, sections
    assert sections["wartet auf Freigabe"] not in (MAINT_SECTION_ID,), sections
    print("OK: 'wartet auf Freigabe' section auto-provisioned by name")

    by_id = {card["id"]: col for col, card in creates}

    assert by_id["MB-1"] == "wartet auf Freigabe", f"pending ticket misrouted: {by_id}"
    print("OK: Release: pending -> 'wartet auf Freigabe' (ignores status 'inprogress')")

    assert by_id["MB-2"] == "wartet auf Freigabe", f"pending+leo-direct misrouted: {by_id}"
    print("OK: Release: pending beats Provenance: leo-direct (gate checked first)")

    # MB-3 has neither Release nor Provenance -> falls through the release
    # gate (opt-in, no marker) into T-297's provenance routing (also opt-in,
    # no marker), which sends it to "maintainance" — proves the two axes
    # compose rather than fight each other.
    assert by_id["MB-3"] == "maintainance", f"no-marker ticket misrouted: {by_id}"
    print("OK: missing Release line -> falls through to provenance routing (composes with T-297)")

    # apply the plan into the fake client (build_plan is read-only; a real
    # sync() would upsert these) so the next build_plan() call sees existing
    # tasks and computes a col_change instead of a fresh create.
    for col, card in creates:
        _, md_title = backend._parse_id_title(card["title"])
        tid = card["id"]
        client.add_task(
            content=f"{tid} — {md_title}" if md_title else tid,
            project_id=project_id,
            section_id=sections[col],
            description=card.get("description", ""),
        )

    # 4. release flip: rewrite MB-1 without the pending marker (keep it
    # leo-direct so the expected fallback is unambiguous), re-sync -> moves
    # OUT of the gate section back to its (now provenance-routed) target.
    (tdir / "MB-1_captured_pending.md").write_text(
        "# MB-1 — Captured, pending release\n\n"
        "**Status:** inprogress\n"
        "Provenance: leo-direct\n\n"
        "Released — Leo said go.\n",
        encoding="utf-8",
    )
    creates2, updates2, trashes2, sections2, _ = build_plan(cfg, backend, only=None)
    assert not creates2 and not trashes2, (creates2, trashes2)
    mb1_update = next(u for u in updates2 if backend._parse_id_title(u[0]["content"])[0] == "MB-1")
    task, col_change, content_change, desc_change, _ = mb1_update
    assert col_change == "inprogress", f"release flip didn't move MB-1 out: {col_change}"
    print("OK: Release marker removed -> ticket flips out of 'wartet auf Freigabe' on next sync")

    # ---- scope check: a board with no release_pending_section keeps old behaviour ---
    tdir2 = Path(tempfile.mkdtemp(prefix="cortex_no_release_gate_"))
    (tdir2 / "T-1_plain.md").write_text(
        "# T-1 — Plain ticket\n\n**Status:** new\nRelease: pending\n\n"
        "No release-gate opt-in on this board.\n",
        encoding="utf-8",
    )
    cfg2 = dataclasses.replace(CORTEX_BOARD, tickets_dir=tdir2)
    assert cfg2.release_pending_section is None, "CORTEX_BOARD must not opt into release-gate routing"
    client2 = FakeClient()
    backend2 = TodoistBackend(cfg2, client=client2)
    creates2b, _, _, _, _ = build_plan(cfg2, backend2, only=None)
    col2 = {card["id"]: col for col, card in creates2b}["T-1"]
    assert col2 == "new", f"non-opted-in board routing changed: {col2}"
    print("OK: board without release_pending_section (e.g. CORTEX_BOARD) ignores Release: pending")

    print("\nALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())

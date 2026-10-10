#!/usr/bin/env python3
"""
pma#145 R5-S3 — md->Todoist mirror survives a full project and id-less tasks.

Exercises `tools/sync_md_to_todoist.sync` / `build_plan` against an in-memory
Todoist client (no network, no token, Leo's live board is never touched).

Covers:
  1. HTTP 403 `MAX_ITEMS_LIMIT_REACHED` on `POST tasks` (the journal traceback
     of maintenance-board-mirror, 09.10./10.10.2026): the run ends without an
     exception, returns 0, has applied trashes + updates + the creates before
     the limit, and reports the skipped creates once on stderr.
  2. any OTHER TodoistError still propagates (no blanket swallow).
  3. Todoist tasks without a ticket id (free title, `content: null`, missing
     `content`) do not crash the plan and are left untouched (never trashed).

Runs under pytest and standalone (exit 0 == green).
"""
from __future__ import annotations

import dataclasses
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CORTEX_BOARD  # noqa: E402
from todoist_backend import TodoistBackend, TodoistError  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import sync_md_to_todoist as sync_mod  # noqa: E402

LIMIT_BODY = (
    'POST tasks -> HTTP 403: {"error":"Maximum number of items per user project '
    'limit reached","error_code":49,"error_tag":"MAX_ITEMS_LIMIT_REACHED",'
    '"http_code":403}'
)


class FakeClient:
    """In-memory TodoistClient stand-in. `add_error_after=N` lets N creates
    through and raises `add_error` on every later `add_task`."""

    def __init__(self, add_error: str | None = None, add_error_after: int = 0) -> None:
        self._projects: dict[str, dict] = {}
        self._sections: dict[str, list[dict]] = {}
        self.tasks: dict[str, dict] = {}
        self._n = 0
        self._add_error = add_error
        self._add_ok_left = add_error_after
        self.add_calls = 0
        self.deleted: list[str] = []

    def _fresh(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def list_projects(self) -> list[dict]:
        return list(self._projects.values())

    def add_project(self, name: str, parent_id: str | None = None) -> dict:
        pid = self._fresh("proj")
        self._projects[pid] = {"id": pid, "name": name, "parent_id": parent_id}
        self._sections[pid] = []
        return self._projects[pid]

    def list_sections(self, project_id: str) -> list[dict]:
        return list(self._sections.get(project_id, []))

    def add_section(self, name: str, project_id: str) -> dict:
        s = {"id": self._fresh("sec"), "name": name, "project_id": project_id}
        self._sections.setdefault(project_id, []).append(s)
        return s

    def list_tasks(self, project_id: str) -> list[dict]:
        return [t for t in self.tasks.values() if t.get("project_id") == project_id]

    def seed(self, project_id: str, section_id: str, **fields) -> dict:
        tid = self._fresh("task")
        self.tasks[tid] = {"id": tid, "project_id": project_id,
                           "section_id": section_id, "description": "", **fields}
        return self.tasks[tid]

    def add_task(self, content: str, project_id: str, section_id: str,
                 description: str = "") -> dict:
        self.add_calls += 1
        if self._add_error is not None:
            if self._add_ok_left <= 0:
                raise TodoistError(self._add_error)
            self._add_ok_left -= 1
        return self.seed(project_id, section_id, content=content,
                         description=description)

    def update_task(self, task_id: str, **fields) -> dict:
        self.tasks[task_id].update(fields)
        return self.tasks[task_id]

    def move_task(self, task_id: str, section_id: str) -> dict:
        self.tasks[task_id]["section_id"] = section_id
        return self.tasks[task_id]

    def delete_task(self, task_id: str) -> None:
        self.deleted.append(task_id)
        self.tasks.pop(task_id, None)


def _board(n_tickets: int):
    tdir = Path(tempfile.mkdtemp(prefix="sync_limit_"))
    for i in range(1, n_tickets + 1):
        (tdir / f"T-{i}_ticket.md").write_text(
            f"# T-{i} — Ticket {i}\n\n**Status:** new\n\nBody {i}.\n", encoding="utf-8")
    return dataclasses.replace(CORTEX_BOARD, tickets_dir=tdir)


def _run_sync(monkey_cfg, client) -> int:
    """Drive the real `sync()` with the board registry and backend pointed at
    the fake — same seam the CLI uses (BOARDS[...] + TodoistBackend(cfg))."""
    orig_boards, orig_backend = sync_mod.BOARDS, sync_mod.TodoistBackend
    sync_mod.BOARDS = {"t": monkey_cfg}
    sync_mod.TodoistBackend = lambda cfg: orig_backend(cfg, client=client)
    try:
        return sync_mod.sync("t", dry_run=False, only=None)
    finally:
        sync_mod.BOARDS, sync_mod.TodoistBackend = orig_boards, orig_backend


def test_project_limit_403_does_not_abort_the_run(capsys=None):
    cfg = _board(3)
    client = FakeClient(add_error=LIMIT_BODY, add_error_after=1)
    # pre-existing state: one stale task (must be trashed) and one task whose
    # title drifted (must be updated) — both have to happen despite the limit.
    prov = TodoistBackend(cfg, client=client).provision()
    pid, sec = prov["project_id"], prov["sections"]["new"]
    stale = client.seed(pid, sec, content="T-99 — gone from md")
    drift = client.seed(pid, sec, content="T-1 — old title", description="Body 1.")

    rc = _run_sync(cfg, client)

    assert rc == 0, f"limit must not fail the unit step, rc={rc}"
    assert stale["id"] in client.deleted, "trash before the limit was not applied"
    assert client.tasks[drift["id"]]["content"] == "T-1 — Ticket 1", "update lost"
    contents = sorted(t["content"] for t in client.tasks.values())
    assert "T-2 — Ticket 2" in contents, "create before the limit was not applied"
    assert "T-3 — Ticket 3" not in contents
    assert client.add_calls == 2, (
        f"a full project must not be hammered: {client.add_calls} POSTs")
    if capsys is not None:
        out = capsys.readouterr()
        assert out.err.count("MAX_ITEMS_LIMIT_REACHED") == 1, out.err
        assert "skipped_limit=1" in out.out, out.out


def test_other_todoist_error_still_propagates():
    cfg = _board(1)
    client = FakeClient(add_error="POST tasks -> HTTP 500: boom")
    try:
        _run_sync(cfg, client)
    except TodoistError as e:
        assert "HTTP 500" in str(e)
    else:
        raise AssertionError("a non-limit TodoistError must not be swallowed")


def test_tasks_without_ticket_id_do_not_crash_and_stay_untouched():
    cfg = _board(1)
    client = FakeClient()
    backend = TodoistBackend(cfg, client=client)
    prov = backend.provision()
    pid, sec = prov["project_id"], prov["sections"]["new"]
    free = client.seed(pid, sec, content="Milch kaufen")
    null = client.seed(pid, sec, content=None)
    missing = client.seed(pid, sec)

    creates, updates, trashes, _, _ = sync_mod.build_plan(cfg, backend, only=None)

    assert [c["id"] for _, c in creates] == ["T-1"]
    assert updates == [] and trashes == [], (updates, trashes)

    assert _run_sync(cfg, client) == 0
    for t in (free, null, missing):
        assert t["id"] in client.tasks and t["id"] not in client.deleted


if __name__ == "__main__":
    test_project_limit_403_does_not_abort_the_run()
    test_other_todoist_error_still_propagates()
    test_tasks_without_ticket_id_do_not_crash_and_stay_untouched()
    print("ALL GREEN")

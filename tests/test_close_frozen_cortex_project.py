#!/usr/bin/env python3
"""
#144 — TodoistClient.close_task + tools/close_frozen_cortex_project guards.

HTTP is mocked (urllib.request.urlopen patched / in-memory fake client): no
network, no token, no real Todoist task is ever touched. Exit 0 == green.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import todoist_backend  # noqa: E402
from todoist_backend import TodoistClient, TodoistError  # noqa: E402
import close_frozen_cortex_project as tool  # noqa: E402


class _Resp:
    def __init__(self, raw: bytes = b"") -> None:
        self._raw = raw

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_close_task_request() -> None:
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req)
        return _Resp(b"")  # Todoist answers 204 No Content

    with mock.patch.object(todoist_backend.urllib.request, "urlopen", fake_urlopen):
        assert TodoistClient("tok-x").close_task("abc123") is None
    assert len(seen) == 1
    req = seen[0]
    assert req.get_method() == "POST"
    assert req.full_url == "https://api.todoist.com/api/v1/tasks/abc123/close"
    assert req.get_header("Authorization") == "Bearer tok-x"
    assert req.data is None


def test_close_task_http_error_hides_token() -> None:
    import io
    import urllib.error

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"not found"))

    with mock.patch.object(todoist_backend.urllib.request, "urlopen", boom):
        try:
            TodoistClient("tok-secret").close_task("gone")
        except TodoistError as e:
            assert "HTTP 404" in str(e) and "tok-secret" not in str(e)
        else:
            raise AssertionError("TodoistError expected")


class FakeClient:
    def __init__(self) -> None:
        self.projects = [
            {"id": "P0", "name": "boards", "parent_id": None},
            {"id": "PC", "name": "cortex", "parent_id": "P0"},
            {"id": "PM", "name": "maintenance", "parent_id": "P0"},
            {"id": "PX", "name": "cortex", "parent_id": None},  # foreign namesake
        ]
        self.tasks = {
            "a": {"id": "a", "content": "A", "project_id": "PC", "checked": False},
            "b": {"id": "b", "content": "B", "project_id": "PC", "checked": True},
            "c": {"id": "c", "content": "C", "project_id": "PM", "checked": False},
            "e": {"id": "e", "content": "E", "project_id": "PC", "checked": False},
            "f": {"id": "f", "content": "FBL-1", "project_id": "PM", "checked": False},
        }
        self.closed: list[str] = []

    def list_projects(self):
        return self.projects

    def list_tasks(self, project_id):
        return [t for t in self.tasks.values()
                if t["project_id"] == project_id and not t["checked"]]

    def get_task(self, task_id):
        if task_id not in self.tasks:
            raise TodoistError(f"GET tasks/{task_id} -> HTTP 404: ")
        return self.tasks[task_id]

    def close_task(self, task_id):
        if task_id == "e":
            raise TodoistError("POST tasks/e/close -> HTTP 500: ")
        self.tasks[task_id]["checked"] = True
        self.closed.append(task_id)


def _liste(tmp: Path) -> Path:
    p = tmp / "liste.json"
    p.write_text(json.dumps({
        "gruppe_A_issue_geschlossen": [
            {"todoist_task_id": i, "projekt": "cortex", "issue": f"x#{n}"}
            for n, i in enumerate(["a", "b", "c", "d", "e"])
        ],
        "gruppe_B_kein_existierendes_issue": [
            {"todoist_task_id": "f", "projekt": "maintenance"},
            {"todoist_task_id": "a", "projekt": "cortex"},  # duplicate
        ],
    }), encoding="utf-8")
    return p


def test_tool_guards() -> None:
    with tempfile.TemporaryDirectory() as d:
        cands, left = tool.load_candidates(_liste(Path(d)))
    assert [c["todoist_task_id"] for c in cands] == ["a", "b", "c", "d", "e"]
    assert [c["todoist_task_id"] for c in left] == ["f"]  # FBL never a candidate

    fc = FakeClient()
    pid, family = tool.find_project(fc)
    assert pid == "PC" and family == {"boards": "P0", "cortex": "PC", "maintenance": "PM"}

    dry = tool.run(fc, cands, pid, apply=False)
    assert fc.closed == [], "dry-run must not write"
    assert [r["id"] for r in dry["closed"]] == ["a", "e"]

    logged: list[str] = []
    res = tool.run(fc, cands, pid, apply=True, on_closed=lambda r: logged.append(r["id"]))
    assert fc.closed == ["a"] and logged == ["a"], "protocol hook fires per write"
    assert [r["id"] for r in res["closed"]] == ["a"]
    assert {s["id"]: s["grund"].split(":")[0] for s in res["skipped"]} == {
        "b": "bereits erledigt",
        "c": "liegt nicht im Projekt cortex",
        "d": "GET fehlgeschlagen",
    }
    assert [e["id"] for e in res["errors"]] == ["e"]
    assert fc.tasks["c"]["checked"] is False and fc.tasks["f"]["checked"] is False


def test_rate_limit_stops_run() -> None:
    fc = FakeClient()

    def limited(task_id):
        raise TodoistError("POST tasks/x/close -> HTTP 429: LIMITS_REACHED")

    fc.close_task = limited
    cands = [{"todoist_task_id": i, "projekt": "cortex"} for i in ("a", "e")]
    res = tool.run(fc, cands, "PC", apply=True)
    assert res["closed"] == [] and [e["id"] for e in res["errors"]] == ["a"], "stop at first 429"


def main() -> int:
    for fn in (test_close_task_request, test_close_task_http_error_hides_token, test_tool_guards,
               test_rate_limit_stops_run):
        fn()
        print(f"OK {fn.__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

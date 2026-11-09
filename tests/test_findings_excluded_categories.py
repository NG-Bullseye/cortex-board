#!/usr/bin/env python3
"""
Leo 09.11. „ja behebe das alles bitte“ — the maintenance mirror skips categories.

`pm-watchdog` findings ("Issue steckt: <repo>#N …") are copies of GitHub issues;
GitHub is that board already, so they must not fill Leo's Todoist project
`boards/maintenance` (09.11.: 144 of 514 active findings, project full).

Covers:
  1. FindingsBackend drops findings whose category is in
     `BoardConfig.excluded_categories`; other active findings stay.
  2. MAINTENANCE_BOARD excludes `pm-watchdog`.
  3. A previously mirrored pm-watchdog task is trashed by build_plan, and the
     live sync applies that trash even when the project is full (trash first).

In-memory Todoist client from test_sync_limit_and_idless_tasks (no network).
Runs under pytest and standalone (exit 0 == green).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import tempfile
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TESTS.parent))
sys.path.insert(0, str(_TESTS.parent / "tools"))
sys.path.insert(0, str(_TESTS))

from backend import FindingsBackend  # noqa: E402
from config import MAINTENANCE_BOARD  # noqa: E402
from todoist_backend import TodoistBackend  # noqa: E402
import sync_md_to_todoist as sync_mod  # noqa: E402
from test_sync_limit_and_idless_tasks import LIMIT_BODY, FakeClient, _run_sync  # noqa: E402

PM_KEY = "pm-watchdog:WMS#6"
HP_KEY = "hardcoded_path:cortex:tools/x.sh:3"


def _mnt(key: str) -> str:
    return "MNT-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]


def _cfg():
    d = Path(tempfile.mkdtemp(prefix="findings_excl_"))
    p = d / "findings.json"
    p.write_text(json.dumps({
        PM_KEY: {"key": PM_KEY, "category": "pm-watchdog", "severity": "warn",
                 "title": "Issue steckt: WMS#6", "active": True},
        HP_KEY: {"key": HP_KEY, "category": "hardcoded_paths", "severity": "info",
                 "title": "cortex/tools/x.sh:3 hardcodet /home/leona/y", "active": True},
    }), encoding="utf-8")
    return dataclasses.replace(MAINTENANCE_BOARD, findings_path=p, tickets_dir=d)


def test_backend_drops_excluded_category():
    board = FindingsBackend(_cfg()).read_board()
    ids = [t["id"] for c in board["columns"] for t in board[c]["tickets"]]
    assert ids == [_mnt(HP_KEY)], ids


def test_maintenance_board_excludes_pm_watchdog():
    assert "pm-watchdog" in MAINTENANCE_BOARD.excluded_categories


def test_mirrored_pm_watchdog_task_is_trashed_even_when_project_full():
    cfg = _cfg()
    client = FakeClient(add_error=LIMIT_BODY, add_error_after=0)
    backend = TodoistBackend(cfg, client=client)
    prov = backend.provision()
    pid, sec = prov["project_id"], prov["sections"]["warn"]
    old = client.seed(pid, sec, content=f"{_mnt(PM_KEY)} — Issue steckt: WMS#6")

    creates, _, trashes, _, _ = sync_mod.build_plan(cfg, backend, only=None)
    assert [t["id"] for t in trashes] == [old["id"]], trashes
    assert [c["id"] for _, c in creates] == [_mnt(HP_KEY)], creates

    assert _run_sync(cfg, client) == 0
    assert old["id"] in client.deleted, "trash must run before the full-project creates"


if __name__ == "__main__":
    test_backend_drops_excluded_category()
    test_maintenance_board_excludes_pm_watchdog()
    test_mirrored_pm_watchdog_task_is_trashed_even_when_project_full()
    print("ALL GREEN")

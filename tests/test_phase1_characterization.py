#!/usr/bin/env python3
"""
T-2 Phase 1 characterization test — proves the BoardConfig + MarkdownBackend
refactor is byte-identical to the pre-refactor tickets_source.py.

Strategy: a single driver script (`_driver.py`) runs the full ticket lifecycle
(read -> add -> get -> move -> update -> remove) plus the scan board against a
*temp* tickets dir (via CORTEX_TICKETS_DIR / CORTEX_SCAN_TICKETS_DIR env), and
emits a canonical JSON snapshot of every return value AND the resulting on-disk
file contents. We run that driver twice in isolated subprocesses:

    1. importing the ORIGINAL tickets_source (git main, copied to _orig_tickets_source.py)
    2. importing the NEW facade tickets_source

over IDENTICAL fixture trees, and assert the two snapshots are equal.

Nothing here touches the live ~/cortex/docs/tickets — everything is in tmp dirs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

FIXTURE_TICKETS = {
    "T-5_some_feature.md": (
        "# T-5 — Some Feature\n\n"
        "**Status:** 🔄\n"
        "**Erstellt:** 2026-01-01\n\n"
        "This is the first paragraph describing the feature in some detail.\n\n"
        "## Next\ndo the thing\n"
    ),
    "T-12_another_thing.md": (
        "# T-12 — Another Thing\n\n**Status:** testing\n\nA testing-column ticket.\n"
    ),
    "WD-3_watchdog_finding.md": (
        "# WD-3 — Watchdog Finding\n\n**Status:** new\n\nSomething the watchdog saw.\n"
    ),
    "T-9_done_already.md": (
        "# T-9 — Done Already\n\n**Status:** ✅\n\nFinished work.\n"
    ),
    "T-2_parked_item.md": (
        "# T-2 — Parked Item\n\n**Status:** wont-do\n\nNot doing this.\n"
    ),
    "INDEX.md": "# INDEX\n\nshould be ignored\n",
    "EXECUTION_PLAN_x.md": "# plan\n\nshould be ignored\n",
}

FIXTURE_SCAN = {
    "SC-1_scan_finding.md": "# SC-1 — Scan Finding\n\n**Status:** open\n\nan open scan.\n",
    "SC-3_resolved_scan.md": "# SC-3 — Resolved Scan\n\n**Status:** resolved\n\ndone scan.\n",
    "SC-00_INDEX.md": "# SC-00 — INDEX\n\n**Status:** new\n\nindex, ignored.\n",
}

ARCHIVE_TICKETS = {
    "archive/2026-01/T-1_old_done.md": "# T-1 — Old Done\n\n**Status:** done\n\narchived.\n",
}

DRIVER = r'''
import json, os, sys, importlib
mod_name = sys.argv[1]
ts = importlib.import_module(mod_name)

def _norm_path(d):
    return {k: (os.path.basename(v) if k in ("path", "removed_path") else v) for k, v in d.items()}

def snap_board():
    return ts.read_board()

def snap_scan():
    return ts.read_scan_board()

result = {}
# 1. initial projection
result["board_initial"] = snap_board()
result["scan_initial"] = snap_scan()
result["read_column_new"] = ts.read_column("new")
result["read_scan_column_open"] = ts.read_scan_column("open")

# 2. add (next id should be T-3: T-1 archived, T-2 parked, T-5/9/12 used)
add = ts.add_ticket("Brand New Task", description="ctx here", next_step="do x")
result["add"] = {k: (os.path.basename(v) if k == "path" else v) for k, v in add.items()}
new_id = add["id"]

# 3. get board after add
result["board_after_add"] = snap_board()

# 4. move the new ticket through columns
result["move_inprogress"] = _norm_path(ts.move_ticket(new_id, "inprogress"))
result["move_testing"] = _norm_path(ts.move_ticket(new_id, "testing"))
# move an existing one
result["move_existing"] = _norm_path(ts.move_ticket("T-12", "done"))

# 5. update title
result["update"] = _norm_path(ts.update_ticket(new_id, title="Renamed Task"))
result["board_after_moves"] = snap_board()

# 6. scan board mutations
sadd = ts.add_scan_ticket("New Scan", description="scan ctx")
result["scan_add"] = {k: (os.path.basename(v) if k == "path" else v) for k, v in sadd.items()}
result["scan_move"] = _norm_path(ts.move_scan_ticket("SC-1", "resolved"))
result["scan_after"] = snap_scan()

# 7. remove
result["remove"] = _norm_path(ts.remove_ticket(new_id))
result["board_after_remove"] = snap_board()

# 8. dump every file content on disk (relative paths), so MD format is compared
files = {}
for base_env in ("CORTEX_TICKETS_DIR", "CORTEX_SCAN_TICKETS_DIR"):
    root = os.environ[base_env]
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            rel = base_env + ":" + os.path.relpath(p, root)
            with open(p, encoding="utf-8") as f:
                files[rel] = f.read()
result["files"] = files

print(json.dumps(result, sort_keys=True, ensure_ascii=False))
'''


def _provision_original() -> str:
    """Materialize the pre-refactor tickets_source.py (from git main) as an
    importable module `_orig_tickets_source` in tests/, so the differential
    comparison always uses the real baseline and never a frozen copy."""
    # Pinned pre-refactor baseline: cortex-board main @ the T-2 Phase 1 cut.
    BASELINE = "12b544a509e3869542af518702dcf59f6bf1809c"
    orig = HERE / "_orig_tickets_source.py"
    for ref in (BASELINE, "origin/main", "main"):
        try:
            src = subprocess.check_output(
                ["git", "show", f"{ref}:tickets_source.py"],
                cwd=str(REPO), text=True, stderr=subprocess.DEVNULL,
            )
            orig.write_text(src, encoding="utf-8")
            return "_orig_tickets_source"
        except subprocess.CalledProcessError:
            continue
    raise AssertionError("could not extract baseline tickets_source.py from git")


def _materialize(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _run(mod_name: str) -> dict:
    tdir = Path(tempfile.mkdtemp(prefix="board_t_"))
    sdir = Path(tempfile.mkdtemp(prefix="board_s_"))
    try:
        _materialize(tdir, FIXTURE_TICKETS)
        _materialize(tdir, ARCHIVE_TICKETS)
        _materialize(sdir, FIXTURE_SCAN)
        driver = REPO / "tests" / "_driver_tmp.py"
        driver.write_text(DRIVER, encoding="utf-8")
        env = dict(os.environ)
        env["CORTEX_TICKETS_DIR"] = str(tdir)
        env["CORTEX_SCAN_TICKETS_DIR"] = str(sdir)
        # _orig module imports as tests._orig_tickets_source path-wise; we point
        # sys.path at both repo root (for new ts / config / backend) and tests/.
        env["PYTHONPATH"] = f"{REPO}:{REPO / 'tests'}:" + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, str(driver), mod_name],
            cwd=str(REPO), env=env, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise AssertionError(f"driver {mod_name} failed:\n{proc.stderr}")
        return json.loads(proc.stdout)
    finally:
        shutil.rmtree(tdir, ignore_errors=True)
        shutil.rmtree(sdir, ignore_errors=True)
        (REPO / "tests" / "_driver_tmp.py").unlink(missing_ok=True)


def _strip_volatile(snap: dict) -> dict:
    """The `source` field and absolute paths differ per temp run; the driver
    already basenamed paths. `source` (the temp dir) differs between the two
    runs, so drop it before comparison — it is just str(tickets_dir)."""
    s = json.loads(json.dumps(snap))  # deep copy

    def scrub(obj):
        if isinstance(obj, dict):
            obj.pop("source", None)
            for v in obj.values():
                scrub(v)
        elif isinstance(obj, list):
            for v in obj:
                scrub(v)

    scrub(s)
    return s


def main() -> int:
    orig_mod = _provision_original()
    orig = _run(orig_mod)
    new = _run("tickets_source")

    o, n = _strip_volatile(orig), _strip_volatile(new)
    if o == n:
        print("OK: new facade byte-identical to original tickets_source")
        print(f"  board columns: {[ (c, new['board_initial'][c]['count']) for c in new['board_initial']['columns'] ]}")
        print(f"  scan columns:  {[ (c, new['scan_initial'][c]['count']) for c in new['scan_initial']['columns'] ]}")
        print(f"  files compared: {len(new['files'])}")
        return 0

    # Pinpoint the first differing key for a readable failure.
    print("FAIL: snapshots differ")
    for k in sorted(set(o) | set(n)):
        if o.get(k) != n.get(k):
            print(f"  --- differs at: {k}")
            print(f"  orig: {json.dumps(o.get(k), ensure_ascii=False)[:500]}")
            print(f"  new:  {json.dumps(n.get(k), ensure_ascii=False)[:500]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Smoketest: status parser is tolerant of the dash-list form (Postel).

Asserts `MarkdownBackend._parse_status` returns the same status for the
standard `**Status:** <val>` form and the dash-list `- **Status:** <val>`
form (emitted by watchdog tools/ticket.py). Also round-trips the write path:
a dash-form ticket set to `done` via move_ticket must re-parse as `done`.

Self-contained, no framework. Exit 0 = green.
"""
from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import MarkdownBackend  # noqa: E402
from config import CORTEX_BOARD  # noqa: E402

backend = MarkdownBackend(CORTEX_BOARD)

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


# ---- 1. parse: both forms yield the same status -----------------------------
for status in ("new", "parked", "resolved", "done"):
    std = f"# T-1 — x\n\n**Status:** {status}\n\nbody\n"
    dash = f"# T-1 — x\n\n- **Status:** {status}\n\nbody\n"
    check(f"standard form '{status}'", backend._parse_status(std), status)
    check(f"dash form '{status}'", backend._parse_status(dash), status)

# Case-insensitive Status keyword still works on the dash form too.
check(
    "dash form 'done' (lowercase status keyword)",
    backend._parse_status("# T-2 — y\n\n- **status:** done\n"),
    "done",
)

# ---- 2. write-path round-trip on a dash-form ticket -------------------------
with tempfile.TemporaryDirectory() as td:
    tdir = Path(td)
    cfg = replace(CORTEX_BOARD, tickets_dir=tdir, extra_id_globs=(), archive_find_globs=())
    be = MarkdownBackend(cfg)

    ticket = tdir / "WD-99_dash_form_ticket.md"
    ticket.write_text(
        "# WD-99 — dash form ticket\n\n- **Status:** new\n\nbody line\n",
        encoding="utf-8",
    )

    # The dash form must be picked up by the board parser (not blind -> default).
    parsed = be._parse_ticket(ticket)
    check("dash-form ticket parsed status_raw", parsed["status_raw"], "new")
    check("dash-form ticket lands in 'new' column (not default)", parsed["column"], "new")

    # Move to done via the write path, then re-parse.
    be.move_ticket("WD-99", "done")
    after = ticket.read_text(encoding="utf-8")
    check("write-path round-trip: re-parsed status", be._parse_status(after), "done")
    check("write-path round-trip: re-parsed column", be._parse_ticket(ticket)["column"], "done")
    print("--- rewritten ticket text ---")
    print(after)
    print("--- end ---")

if failures:
    print(f"\nFAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("\nALL GREEN")
sys.exit(0)

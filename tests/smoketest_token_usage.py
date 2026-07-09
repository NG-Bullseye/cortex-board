#!/usr/bin/env python3
"""Smoketest: token_usage.sample_window() splits a synthetic ~/.claude/projects
fixture correctly across the 4 verified mapping fallstricke (T-287, GH #580):
  - cwd 1:1 buckets (watchdog)
  - manager alias list (project-manager-agent + manager-agent -> "manager")
  - cerebellum tier2/tier3 model split (claude-opus-4-8 vs claude-sonnet-4-6,
    with a claude-sonnet-5 message in the same cwd correctly excluded from both)
  - morning_briefing / maintenance time-window split (05:05-05:20 local vs. rest)
  - DeepSeek / non-claude model messages are dropped entirely (T-178 hard constraint)

Self-contained, no framework, writes into a tempdir (CLAUDE_PROJECTS_DIR env
override), Exit 0 = green.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok:
        failures.append(label)


def usage_line(cwd: str, model: str, ts: str, total: int, branch: str = "develop") -> str:
    # separators=(",", ":") matches Claude Code's real compact JSONL format --
    # token_usage.py's cheap textual pre-filter relies on that exact spacing.
    return json.dumps(
        {
            "timestamp": ts,
            "cwd": cwd,
            "gitBranch": branch,
            "type": "assistant",
            "message": {
                "model": model,
                "usage": {
                    "input_tokens": total,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        },
        separators=(",", ":"),
    )


with tempfile.TemporaryDirectory() as td:
    projects = Path(td)
    os.environ["CLAUDE_PROJECTS_DIR"] = str(projects)

    # module reads PROJECTS_DIR at import time -> import AFTER setting env
    import token_usage as tu  # noqa: E402

    tu.PROJECTS_DIR = projects  # belt+braces in case of caching in a re-run

    day = "2026-07-09"

    def mk(dirname: str, fname: str, lines: list[str]) -> None:
        d = projects / dirname
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_text("\n".join(lines) + "\n", encoding="utf-8")

    # watchdog: plain 1:1 bucket
    mk(
        "-home-leona-repos-watchdog",
        "s1.jsonl",
        [usage_line("/home/leona/repos/watchdog", "claude-sonnet-5", f"{day}T10:00:00Z", 100)],
    )

    # manager alias list: old label + rename target both -> "manager"
    mk(
        "-home-leona-repos-project-manager-agent",
        "s1.jsonl",
        [usage_line("/home/leona/repos/project-manager-agent", "claude-sonnet-5", f"{day}T10:00:00Z", 50)],
    )
    mk(
        "-home-leona-repos-manager-agent",
        "s1.jsonl",
        [usage_line("/home/leona/repos/manager-agent", "claude-sonnet-5", f"{day}T10:00:00Z", 25)],
    )

    # cerebellum: tier3 (opus-4-8), tier2 (sonnet-4-6), and a plain sonnet-5 dev
    # message that must land in NEITHER tier line.
    mk(
        "-home-leona-repos-cerebellum",
        "s1.jsonl",
        [
            usage_line("/home/leona/repos/cerebellum", "claude-opus-4-8", f"{day}T10:00:00Z", 300),
            usage_line("/home/leona/repos/cerebellum", "claude-sonnet-4-6", f"{day}T10:00:00Z", 70),
            usage_line("/home/leona/repos/cerebellum", "claude-sonnet-5", f"{day}T10:00:00Z", 999),
        ],
    )

    # maintenance: one message inside the 05:05-05:20 local morning window, one
    # outside (hourly curator at 06:00 local) -> UTC is local-2h in July (CEST).
    mk(
        "-home-leona-repos-maintenance",
        "s1.jsonl",
        [
            usage_line("/home/leona/repos/maintenance", "claude-haiku-4-5-20251001", f"{day}T03:10:00Z", 40),  # 05:10 local
            usage_line("/home/leona/repos/maintenance", "claude-sonnet-5", f"{day}T04:00:00Z", 60),  # 06:00 local
        ],
    )

    # DeepSeek line in a claude-tracked repo must be fully dropped (T-178).
    mk(
        "-home-leona-cortex",
        "s1.jsonl",
        [
            usage_line("/home/leona/cortex", "deepseek-v4-pro", f"{day}T10:00:00Z", 123456),
            usage_line("/home/leona/cortex", "claude-opus-4-8", f"{day}T10:00:00Z", 10),
        ],
    )

    since = datetime(2026, 7, 9, 0, 0, 0, tzinfo=timezone.utc)
    until = datetime(2026, 7, 9, 23, 59, 59, tzinfo=timezone.utc)
    totals = tu.sample_window(since, until)

    check("watchdog 1:1", totals["watchdog"], 100)
    check("manager alias list sums both labels", totals["manager"], 75)
    check("cerebellum tier3 == opus-4-8 only", totals["cerebellum_tier3"], 300)
    check("cerebellum tier2 == sonnet-4-6 only", totals["cerebellum_tier2"], 70)
    check("morning_briefing == the 05:10-local message only", totals["morning_briefing"], 40)
    check("maintenance == the 06:00-local message only (window excludes it)", totals["maintenance"], 60)
    check("security stays 0 (no fixture data == no bucket, verified blind spot)", totals["security"], 0)
    check("cortex excludes the DeepSeek row, keeps the claude row", totals["cortex"], 10)

if failures:
    print(f"\nFAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("\nALL GREEN")
sys.exit(0)

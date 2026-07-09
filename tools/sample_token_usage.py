#!/usr/bin/env python3
"""
2h token-usage sampler (T-287, GH #580). Run by
systemd/cortex-board-token-sample.timer at 01,03,05,07,09,11,13,15,17,19,21,23
local -- deliberately hits 05:00 and 07:00 exactly (2h-Raster ab 01:00), so one
sample lands *before* the morning routines (05:00) and one *after* routines +
briefing (07:00), making the morning token-concentration visible as a jump.

Each run computes, per agent-line (see token_usage.LINES), the token total
consumed strictly since the previous sample (or the last 2h if this is the
first run ever) and appends one row to data/token_samples.jsonl:

    {"ts": "2026-07-09T07:00:00+02:00", "since": "...", "values": {"maintenance": 12345, ...}}

Self-contained: no MCP dependency (systemd timers don't run inside an agent
session), just stdlib + token_usage.py's direct JSONL read.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import token_usage as tu  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SAMPLES_FILE = DATA_DIR / "token_samples.jsonl"


def _last_sample_ts() -> datetime | None:
    if not SAMPLES_FILE.exists():
        return None
    last_line = None
    with SAMPLES_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                last_line = line
    if last_line is None:
        return None
    try:
        row = json.loads(last_line)
        return datetime.fromisoformat(row["ts"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def run(now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    prev = _last_sample_ts()
    since = prev.astimezone(timezone.utc) if prev else now - timedelta(hours=2)

    values = tu.sample_window(since, now)

    row = {
        "ts": now.astimezone(tu.LOCAL_TZ).isoformat(),
        "since": since.astimezone(tu.LOCAL_TZ).isoformat(),
        "values": values,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with SAMPLES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return row


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, ensure_ascii=False))

#!/usr/bin/env python3
"""
Token-usage aggregation for the Monitoring chart (T-287, GH #580).

Reads ~/.claude/projects/*/*.jsonl directly (same source + same repo-label
logic as the `repo-usage-mcp` MCP server — see ~/repos/repo-usage-mcp/src/usage.ts
for the reference algorithm this mirrors), but does its own line-level
timestamp filtering because the MCP tool only offers day-granularity
`since`/`until` and only runs *inside* an agent session (a systemd-timer
cron script has no MCP access at all — this module is therefore
self-contained, no dependency on that MCP server being up).

11 agents/lines Leo asked for, and the mapping fallstricke this ticket had
to resolve WITH REAL DATA (verified 2026-07-09, see PR body for the
full trail):

1. maintenance      -> cwd bucket "maintenance", 1:1, minus the morning-briefing
                        time window (see #3).
2. security          -> cwd bucket "security-stack". VERIFIED BLIND SPOT, not a
                        wiring bug: crowdsec_analyzer.py's systemd timer
                        (~/.config/systemd/user/crowdsec-analyzer.timer, every
                        15min) fires correctly and IS scoped to the right cwd
                        (WorkingDirectory=/home/leona/repos/security-stack in
                        the .service unit) -- but `claude -p` only runs when
                        >=MIN_ALERTS new CrowdSec alerts exist, and the journal
                        shows "no alerts fetched" on every single tick observed
                        (checked back multiple hours, 2026-07-09). The claude
                        subprocess has literally never fired yet, so
                        ~/.claude/projects/-home-leona-repos-security-stack/
                        doesn't exist yet. NOT rendered as a silent 0 -- see
                        SECURITY_BLIND_SPOT_NOTE below, surfaced by the API.
3. morning_briefing  -> same cwd bucket as maintenance ("maintenance", both
                        morning_agent.py and the hourly Sonnet curator run
                        there). Split by a TIME WINDOW: morning_agent.py's
                        timer fires at a fixed 05:05:00 local
                        (maintenance-morning-agent.timer, OnCalendar=05:05:00,
                        AccuracySec=2min) and historically finished within
                        05:05-05:15 (journalctl); recent runs (Jul 5-9) get
                        SIGTERM'd within seconds instead but still start at
                        05:05:00. MORNING_WINDOW below (05:05-05:20 local, 15min
                        buffer) claims that slice for morning_briefing; every
                        other maintenance-cwd message (hourly curator, prune,
                        board-mirror) stays in maintenance.
4. newsbot           -> cwd bucket "news-agent", 1:1.
5. manager           -> cwd bucket, ALIAS LIST not a single string: currently
                        "project-manager-agent", with "manager-agent" pre-wired
                        as the announced-but-not-yet-executed rename target (see
                        ~/.claude/CLAUDE.md Cortex-Mesh table + Leo's separate
                        rename thread) -- both map onto one canonical "manager"
                        line so the chart doesn't visually break when the
                        rename lands.
6. cortex a / cortex b -> VERIFIED NOT SEPARABLE with data available on this
                        host. Both cortexctl and cortex-bctl (~/.local/bin/)
                        launch `claude` with the *identical* DIR="/home/leona/cortex"
                        -- same cwd, so the repo-bucket dimension can never
                        split them. gitBranch doesn't work either: both lanes'
                        top-level orchestration turns sit on whatever branch
                        the shared ~/cortex checkout happens to have checked
                        out (almost always "develop" -- Task-tool worktree
                        agents get their own branch/cwd bucket and already
                        show up as separate rows, that's not the ambiguity).
                        sessionId *would* distinguish them in principle (each
                        launcher caches its own session-id file under
                        ~/.cache/cortex{,-b}/launcher/*.sid) but that cache
                        file goes stale/rotates on --resume fallback (verified:
                        the currently-cached cortex.sid has no matching .jsonl
                        file at all on this host right now) -- not a reliable
                        historical index. Rendered as ONE combined line
                        "cortex (a+b)" with the reason documented in the API
                        response (`notes.cortex`) and in the UI caption, not as
                        two identical/fake-split lines.
7. cerebellum tier3/2 -> VERIFIED clean proxy. ~/repos/cerebellum/cerebellum/config.py:
                        ArchitectConfig (Tier-3) hardcodes
                        model="claude-opus-4-8" (config.py:172); DreamConfig
                        (Tier-2) hardcodes model="claude-sonnet-4-6"
                        (config.py:190) -- both PINNED exact model strings, not
                        the generic "sonnet"/"opus" alias used by interactive
                        dev/orchestration sessions in the same cwd bucket
                        (those show up as claude-sonnet-5 / claude-haiku-4-5-*,
                        confirmed via get_repo_breakdown('cerebellum') and a
                        repo-wide grep for other model= assignments -- no other
                        cerebellum consumer uses claude-opus-4-8 or
                        claude-sonnet-4-6 literally). Filtering by exact model
                        id is therefore a clean, non-overlapping split.
8. coding-agent,
   watchdog          -> cwd bucket, 1:1, no problem.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9 not expected here
    ZoneInfo = None  # type: ignore

PROJECTS_DIR = Path(os.environ.get("CLAUDE_PROJECTS_DIR", str(Path.home() / ".claude" / "projects")))
LOCAL_TZ = ZoneInfo("Europe/Berlin") if ZoneInfo else timezone(timedelta(hours=2))

# morning_agent.py fires 05:05:00 local sharp (AccuracySec=2min) and has
# historically finished by ~05:15 (up to 05:20 with buffer); recent runs get
# killed within seconds but still start on time. 15min window from trigger.
MORNING_WINDOW_START = (5, 5)   # (hour, minute) local
MORNING_WINDOW_END = (5, 20)


def _in_morning_window(dt_local: datetime) -> bool:
    hm = (dt_local.hour, dt_local.minute)
    return MORNING_WINDOW_START <= hm < MORNING_WINDOW_END


@dataclass(frozen=True)
class LineSpec:
    """One chart line: which cwd-bucket(s) + optional extra filter it draws from."""

    key: str
    label: str
    cwd_labels: tuple[str, ...]  # basename(cwd) values that count toward this line
    model_equals: str | None = None  # exact message.model match, if set
    time_filter: Callable[[datetime], bool] | None = None  # local-time predicate on the message
    note: str | None = None  # surfaced to the API/UI when non-trivial


LINES: tuple[LineSpec, ...] = (
    LineSpec(
        key="maintenance",
        label="Maintenance",
        cwd_labels=("maintenance",),
        time_filter=lambda dt: not _in_morning_window(dt),
    ),
    LineSpec(
        key="morning_briefing",
        label="Morning Briefing",
        cwd_labels=("maintenance",),
        time_filter=_in_morning_window,
        note="Zeitfenster-Split 05:05-05:20 lokal aus dem geteilten maintenance-cwd (morning_agent.py "
        "vs. stuendlicher Curator) -- kein eigener cwd-Bucket vorhanden.",
    ),
    LineSpec(
        key="security",
        label="Security",
        cwd_labels=("security-stack",),
        note="Verifizierter Blindfleck: crowdsec-analyzer.timer feuert alle 15min korrekt "
        "(WorkingDirectory=~/repos/security-stack), aber der claude-Subprozess laeuft nur bei "
        ">=MIN_ALERTS neuen CrowdSec-Alerts -- Journal zeigt durchgehend 'no alerts fetched', der "
        "cwd-Bucket existiert deshalb noch nicht. Kein Wiring-Bug, echte Null mangels Trigger.",
    ),
    LineSpec(key="newsbot", label="Newsbot", cwd_labels=("news-agent",)),
    LineSpec(
        key="manager",
        label="Manager",
        cwd_labels=("project-manager-agent", "manager-agent"),
        note="Alias-Liste statt 1:1-String-Match: Rename project-manager-agent -> manager-agent "
        "steht bevor (separates Thema mit Leo); beide Label-Staende mappen auf eine kanonische Linie.",
    ),
    LineSpec(
        key="cortex",
        label="Cortex (a+b)",
        cwd_labels=("cortex",),
        note="cortex + cortex-b NICHT trennbar: beide Launcher (cortexctl/cortex-bctl) starten "
        "claude mit identischem cwd=/home/leona/cortex; gitBranch ebenfalls kein Diskriminator "
        "(beide Orchestrator-Sessions sitzen praktisch immer auf 'develop', Worktree-Subagents "
        "haben ohnehin eigene Buckets). sessionId waere die richtige Achse, ist aber ueber die "
        "aktuell verfuegbaren Tools nicht stabil rueckwirkend zuordenbar (verifiziert: der "
        "gecachte cortex.sid hat keine passende .jsonl mehr). Eine Linie, kombiniert.",
    ),
    LineSpec(key="coding_agent", label="Coding-Agent", cwd_labels=("coding-agent",)),
    LineSpec(
        key="cerebellum_tier3",
        label="Cerebellum Tier-3 (Architect)",
        cwd_labels=("cerebellum",),
        model_equals="claude-opus-4-8",
        note="Modell-Proxy verifiziert: ArchitectConfig pinnt model=claude-opus-4-8 exklusiv "
        "(cerebellum/config.py:172), kein anderer cerebellum-Consumer zieht dieses Modell.",
    ),
    LineSpec(
        key="cerebellum_tier2",
        label="Cerebellum Tier-2 (Dream)",
        cwd_labels=("cerebellum",),
        model_equals="claude-sonnet-4-6",
        note="Modell-Proxy verifiziert: DreamConfig pinnt model=claude-sonnet-4-6 exklusiv "
        "(cerebellum/config.py:190), getrennt vom generischen sonnet-Alias interaktiver Sessions.",
    ),
    LineSpec(key="watchdog", label="Watchdog", cwd_labels=("watchdog",)),
)

LINE_BY_KEY: dict[str, LineSpec] = {ln.key: ln for ln in LINES}


def _is_claude_model(model: object) -> bool:
    return isinstance(model, str) and model.startswith("claude")


def _usage_total(usage: dict) -> int:
    return (
        int(usage.get("input_tokens", 0) or 0)
        + int(usage.get("output_tokens", 0) or 0)
        + int(usage.get("cache_creation_input_tokens", 0) or 0)
        + int(usage.get("cache_read_input_tokens", 0) or 0)
    )


def _repo_from_cwd(cwd: object) -> str | None:
    if not isinstance(cwd, str) or not cwd:
        return None
    b = os.path.basename(cwd.rstrip("/"))
    return b or None


def sample_window(since_utc: datetime, until_utc: datetime) -> dict[str, int]:
    """Sum token totals per LINES key for messages with timestamp in
    (since_utc, until_utc]. Both bounds are timezone-aware UTC datetimes.

    Mirrors repo-usage-mcp's aggregate() (src/usage.ts) but adds per-message
    local-time + model filtering, and only reads lines whose raw timestamp
    prefix falls on a day that could possibly be in range (cheap textual
    pre-filter before the JSON parse -- the corpus is 370k+ lines across all
    sessions, most of which predate any 2h window).
    """
    totals: dict[str, int] = {ln.key: 0 for ln in LINES}
    if not PROJECTS_DIR.is_dir():
        return totals

    candidate_days = set()
    d = since_utc.date()
    end_d = until_utc.date()
    while d <= end_d:
        candidate_days.add(d.isoformat())
        d += timedelta(days=1)
    # Needle = the bare day string (not `"timestamp":"<day>` -- Claude Code's
    # real JSONL is compact/no-space, but pinning to that exact byte layout
    # would silently break the moment the writer's serialization changes; the
    # bare day string is a cheap, format-agnostic pre-filter and any rare
    # false positive just costs one extra json.loads, not a correctness bug).
    day_needles = tuple(candidate_days)

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jf in project_dir.glob("*.jsonl"):
            try:
                fh = jf.open("r", encoding="utf-8", errors="ignore")
            except OSError:
                continue
            with fh:
                for line in fh:
                    if not line.strip():
                        continue
                    if not any(needle in line for needle in day_needles):
                        continue  # cheap skip before JSON parse
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message")
                    if not isinstance(msg, dict):
                        continue
                    model = msg.get("model")
                    if not _is_claude_model(model):
                        continue
                    usage = msg.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    ts_raw = obj.get("timestamp")
                    if not isinstance(ts_raw, str):
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if not (since_utc < ts <= until_utc):
                        continue

                    repo = _repo_from_cwd(obj.get("cwd"))
                    if repo is None:
                        # fallback: decode encoded project dir name, same as usage.ts
                        parts = [p for p in project_dir.name.split("-") if p]
                        repo = parts[-1] if parts else "unknown"

                    total = _usage_total(usage)
                    ts_local = ts.astimezone(LOCAL_TZ)

                    for ln in LINES:
                        if repo not in ln.cwd_labels:
                            continue
                        if ln.model_equals is not None and model != ln.model_equals:
                            continue
                        if ln.time_filter is not None and not ln.time_filter(ts_local):
                            continue
                        totals[ln.key] += total

    return totals


def line_meta() -> list[dict]:
    return [
        {"key": ln.key, "label": ln.label, "note": ln.note}
        for ln in LINES
    ]

"""Quota view data (pma#333): tokens per consumer + RAM/swap per registry service.

One facade: `report() -> dict` (contract of GET /api/quota). Errors raise
`QuotaError(code, message)` with a stable code; the REST face maps it to 502.

- Tokens: the one measurement `token-usage report --days 7 --json` (monitor-mcp
  CLI facade), cached in-process for TOKEN_TTL_S because a run takes seconds.
- Memory: cgroup `MemoryCurrent`/`MemorySwapCurrent` of every service in
  ~/repos/monitor-mcp/registry.yaml with a `unit:`, one `systemctl show` per
  scope (user/system); templates (`x@.service`) summed over their instances;
  host totals from /proc/meminfo.
- Titles always come from registry.yaml.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

DAYS = 7
TOKEN_TTL_S = 300
REGISTRY = Path(os.environ.get("MONITOR_REGISTRY", str(Path.home() / "repos/monitor-mcp/registry.yaml")))
MEMINFO = Path("/proc/meminfo")
UNIT_NOTE = "neu = input+output+cache_write (ohne cache_read) · gesamt = neu + cache_read"

_token_cache: tuple[float, dict] | None = None


class QuotaError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _run(cmd: list[str], code: str) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QuotaError(code, f"{cmd[0]}: {exc}") from exc
    if proc.returncode != 0:
        raise QuotaError(code, f"{' '.join(cmd)} rc={proc.returncode}: {proc.stderr.strip()[-300:]}")
    return proc.stdout


def _services() -> dict:
    try:
        return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["services"]
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise QuotaError("registry_unreadable", f"{REGISTRY}: {exc}") from exc


def _token_report() -> dict:
    global _token_cache
    now = time.monotonic()
    if _token_cache and now - _token_cache[0] < TOKEN_TTL_S:
        return _token_cache[1]
    out = _run(["token-usage", "report", "--days", str(DAYS), "--json"], "token_usage_failed")
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise QuotaError("token_usage_failed", f"token-usage output is not JSON: {exc}") from exc
    _token_cache = (now, data)
    return data


def _tokens(services: dict) -> dict:
    data = _token_report()
    rows = [
        {
            "service": r["service"],
            "title": services.get(r["service"], {}).get("title") or r["service"],
            "kind": r["mode"],
            "sessions": r["calls"],
            "new": r["neu"],
            "total": r["gesamt"],
            "new_per_24h": r["neu_24h"],
        }
        for r in data["by_service"]
    ]
    unattributed = [
        {"cwd": u["cwd"], "kind": u["kind"], "sessions": u["calls"], "new": u["neu"], "total": u["gesamt"]}
        for u in data["unattributed"]
    ]
    return {
        "unit_note": UNIT_NOTE,
        "rows": sorted(rows, key=lambda r: r["new"], reverse=True),
        "unattributed": unattributed,
    }


def _cgroup_memory(units: list[str], scope: str) -> dict[str, tuple[int, int]]:
    """unit -> (memory, swap) bytes; units without a live cgroup are omitted.

    A template (`x@.service`) is rejected by `systemctl show`, so it is resolved
    to its loaded instances (`x@*.service`) and their cgroups are summed under it.
    """
    if not units:
        return {}
    base = ["systemctl"] + (["--user"] if scope == "user" else [])
    owner = {u: u for u in units if "@." not in u}
    templates = [u.replace("@.", "@*.") for u in units if "@." in u]
    if templates:
        listing = _run(base + ["list-units", "--plain", "--no-legend", "--all", *templates], "systemctl_failed")
        for line in listing.splitlines():
            inst = line.split()[0]
            owner[inst] = inst.split("@", 1)[0] + "@." + inst.rsplit(".", 1)[1]
    if not owner:
        return {}
    result: dict[str, tuple[int, int]] = {}
    cmd = base + ["show", "-p", "Id", "-p", "MemoryCurrent", "-p", "MemorySwapCurrent", *owner]
    for block in _run(cmd, "systemctl_failed").split("\n\n"):
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        mem, swap = props.get("MemoryCurrent", ""), props.get("MemorySwapCurrent", "")
        if mem.isdigit():
            unit = owner.get(props["Id"], props["Id"])
            prev_mem, prev_swap = result.get(unit, (0, 0))
            result[unit] = (prev_mem + int(mem), prev_swap + (int(swap) if swap.isdigit() else 0))
    return result


def _meminfo() -> dict[str, int]:
    kib = {}
    for line in MEMINFO.read_text().splitlines():
        key, _, rest = line.partition(":")
        kib[key] = int(rest.split()[0]) * 1024
    return kib


def _memory(services: dict) -> dict:
    by_scope: dict[str, list[tuple[str, dict]]] = {"user": [], "system": []}
    for sid, svc in services.items():
        if svc.get("unit"):
            by_scope["system" if svc.get("scope") == "system" else "user"].append((sid, svc))
    rows = []
    for scope, entries in by_scope.items():
        measured = _cgroup_memory([svc["unit"] for _, svc in entries], scope)
        for sid, svc in entries:
            if svc["unit"] in measured:
                mem, swap = measured[svc["unit"]]
                rows.append({"service": sid, "title": svc.get("title") or sid, "unit": svc["unit"],
                             "memory": mem, "swap": swap})
    mi = _meminfo()
    return {
        "ram": {"total": mi["MemTotal"], "used": mi["MemTotal"] - mi["MemAvailable"],
                "available": mi["MemAvailable"]},
        "swap": {"total": mi["SwapTotal"], "used": mi["SwapTotal"] - mi["SwapFree"]},
        "rows": sorted(rows, key=lambda r: r["memory"], reverse=True),
    }


def report() -> dict:
    services = _services()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "days": DAYS,
        "tokens": _tokens(services),
        "memory": _memory(services),
    }

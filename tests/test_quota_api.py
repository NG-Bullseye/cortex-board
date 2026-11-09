#!/usr/bin/env python3
"""
pma#333 (Leo 02.11.: „links Token je Verbraucher, rechts RAM und Swap je Dienst“)
— GET /api/quota serves both halves from one measurement each:

  1. tokens.rows come from `token-usage report --days 7 --json` (one call,
     cached), titled from registry.yaml, sorted by `new` descending.
  2. memory.rows come from one `systemctl show` per scope (user/system) for
     every registry service with a `unit:`; units without a cgroup are dropped.
  3. a failing token-usage run is a loud 502 `token_usage_failed`.
  4. the old /api/token-usage route is gone (404).

Mocked at the subprocess seam (`quota.subprocess.run`), registry from a tempfile.
Runs under pytest and standalone (exit 0 == green).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import quota  # noqa: E402

REGISTRY = """
services:
  bgllm_perception_judge:
    title: "Perception Judge"
    unit: perception-judge.service
  bgllm_bewusstsein:
    title: "Bewusstseinsschicht"
  cortex_claude_bridge:
    title: "Claude-Bruecke"
    unit: cortex-claude-bridge.service
    scope: system
  infra_some_timer:
    title: "Ein Timer"
    unit: some.timer
"""

TOKEN_REPORT = {
    "by_service": [
        {"service": "bgllm_bewusstsein", "mode": "transcript", "calls": 3, "neu": 100, "gesamt": 900, "neu_24h": 14},
        {"service": "bgllm_perception_judge", "mode": "transcript", "calls": 9, "neu": 500, "gesamt": 700, "neu_24h": 71},
    ],
    "unattributed": [{"cwd": "/home/leona/x", "kind": "interactive", "calls": 1, "neu": 42, "gesamt": 99}],
}

SHOW = {
    "user": "MemoryCurrent=1000\nMemorySwapCurrent=10\nId=perception-judge.service\n\n"
            "MemoryCurrent=[not set]\nMemorySwapCurrent=[not set]\nId=some.timer\n",
    "system": "MemoryCurrent=5000\nMemorySwapCurrent=[not set]\nId=cortex-claude-bridge.service\n",
}


class FakeRun:
    def __init__(self, token_rc: int = 0):
        self.calls: list[list[str]] = []
        self.token_rc = token_rc

    def __call__(self, cmd, **_kw):
        self.calls.append(cmd)
        if cmd[0] == "token-usage":
            return subprocess.CompletedProcess(cmd, self.token_rc, json.dumps(TOKEN_REPORT), "boom")
        scope = "user" if "--user" in cmd else "system"
        return subprocess.CompletedProcess(cmd, 0, SHOW[scope], "")


def _client(fake: FakeRun, tmp: Path) -> TestClient:
    reg = tmp / "registry.yaml"
    reg.write_text(REGISTRY)
    quota.REGISTRY = reg
    quota._token_cache = None
    quota.subprocess.run = fake
    return TestClient(api.app)


def test_quota_contract():
    fake = FakeRun()
    with tempfile.TemporaryDirectory() as d:
        client = _client(fake, Path(d))
        body = client.get("/api/quota").json()
        client.get("/api/quota")
    assert body["days"] == 7 and body["generated_at"]
    tok = body["tokens"]
    assert [r["title"] for r in tok["rows"]] == ["Perception Judge", "Bewusstseinsschicht"]
    assert tok["rows"][0] == {"service": "bgllm_perception_judge", "title": "Perception Judge", "kind": "transcript",
                              "sessions": 9, "new": 500, "total": 700, "new_per_24h": 71}
    assert tok["unattributed"] == [{"cwd": "/home/leona/x", "kind": "interactive", "sessions": 1, "new": 42, "total": 99}]
    assert "cache_read" in tok["unit_note"]
    assert [c[0] for c in fake.calls].count("token-usage") == 1, "token-usage must be cached between requests"
    mem = body["memory"]
    assert mem["rows"] == [
        {"service": "cortex_claude_bridge", "title": "Claude-Bruecke", "unit": "cortex-claude-bridge.service", "memory": 5000, "swap": 0},
        {"service": "bgllm_perception_judge", "title": "Perception Judge", "unit": "perception-judge.service", "memory": 1000, "swap": 10},
    ]
    assert set(mem["ram"]) == {"total", "used", "available"} and set(mem["swap"]) == {"total", "used"}


def test_token_usage_failure_is_loud():
    with tempfile.TemporaryDirectory() as d:
        resp = _client(FakeRun(token_rc=1), Path(d)).get("/api/quota")
    assert resp.status_code == 502 and resp.json()["error"] == "token_usage_failed"
    assert resp.headers["x-trace-id"] == resp.json()["trace_id"]


def test_old_route_gone():
    assert TestClient(api.app).get("/api/token-usage").status_code == 404


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("GREEN")

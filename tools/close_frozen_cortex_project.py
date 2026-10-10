#!/usr/bin/env python3
"""
close_frozen_cortex_project — check off the frozen GitHub->Todoist mirror (#144).

The Todoist sub-project `boards/cortex` is the frozen snapshot of the disabled
`tools/sync_github_todoist.py` sync: its only closing writer never runs, so
tasks of long-closed GitHub issues stay open. This tool closes exactly the
tasks named in a measured list (JSON, `--liste`) and nothing else.

Guards, per task, immediately before the write:
  * the list entry itself says project `cortex`,
  * a fresh GET shows the task in the Todoist project `boards/cortex`,
  * the task is still open (not checked, not deleted).
Anything else is skipped with a reason. All writes go through the one Todoist
writer of this repo (`todoist_backend.TodoistClient.close_task`).

    --dry-run   (default) only count what would be closed
    --apply     close, and write the protocol (way back) to --protokoll

Way back: POST tasks/<id>/reopen for every id in the protocol file.
The token comes from env TODOIST_API_KEY (see todoist_backend.resolve_token),
e.g.  set -a; . ~/cortex/.env; set +a   — it is never printed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from todoist_backend import TodoistClient, TodoistError, resolve_token  # noqa: E402

PARENT = "boards"
PROJECT = "cortex"
GROUPS = ("gruppe_A_issue_geschlossen", "gruppe_B_kein_existierendes_issue")
DEFAULT_PROTOKOLL = REPO / "state" / "closed-frozen-cortex-2026-10-10.json"


def load_candidates(liste: Path) -> tuple[list[dict], list[dict]]:
    """(candidates in project `cortex`, list entries left out by project)."""
    data = json.loads(liste.read_text(encoding="utf-8"))
    take: list[dict] = []
    left: list[dict] = []
    seen: set[str] = set()
    for g in GROUPS:
        for e in data.get(g, []):
            tid = e["todoist_task_id"]
            if e.get("projekt") != PROJECT:
                left.append(e)
            elif tid not in seen:
                seen.add(tid)
                take.append(e)
    return take, left


def find_project(client, name: str = PROJECT, parent: str = PARENT) -> tuple[str, dict]:
    """(id of `parent/name`, {project name: id} for parent + all its children)."""
    projects = client.list_projects()
    parents = [p for p in projects if p["name"] == parent and not p.get("parent_id")]
    if len(parents) != 1:
        raise TodoistError(f"expected exactly one top-level project {parent!r}, got {len(parents)}")
    pid = parents[0]["id"]
    family = {parent: pid}
    family.update({p["name"]: p["id"] for p in projects if p.get("parent_id") == pid})
    if name not in family:
        raise TodoistError(f"project {parent}/{name} not found")
    return family[name], family


def skip_reason(task: dict | None, project_id: str) -> str | None:
    """None == safe to close; otherwise why the task must not be touched."""
    if not task:
        return "task nicht gefunden"
    if task.get("project_id") != project_id:
        return f"liegt nicht im Projekt {PROJECT}"
    if task.get("is_deleted"):
        return "geloescht"
    if task.get("checked") or task.get("is_completed") or task.get("completed_at"):
        return "bereits erledigt"
    return None


def open_counts(client, family: dict) -> dict:
    return {name: len(client.list_tasks(pid)) for name, pid in sorted(family.items())}


def run(client, candidates: list[dict], project_id: str, apply: bool,
        pause: float = 0.0, on_closed=None) -> dict:
    """`on_closed(row)` fires right after each successful write, so the
    protocol survives an interrupted run (SIGKILL mid-loop)."""
    closed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for e in candidates:
        tid = e["todoist_task_id"]
        try:
            task = client.get_task(tid)
        except TodoistError as exc:
            if "HTTP 429" in str(exc):  # rate limit: stop, rerun later
                errors.append({"id": tid, "fehler": "Rate-Limit (HTTP 429) — Lauf abgebrochen, spaeter erneut starten"})
                break
            skipped.append({"id": tid, "grund": f"GET fehlgeschlagen: {exc}"})
            continue
        why = skip_reason(task, project_id)
        if why:
            skipped.append({"id": tid, "grund": why})
            continue
        row = {"id": tid, "content": task.get("content", ""), "issue": e.get("issue")}
        if apply:
            try:
                client.close_task(tid)
            except TodoistError as exc:
                errors.append({"id": tid, "fehler": str(exc)})
                if "HTTP 429" in str(exc):
                    break
                continue
            if on_closed:
                on_closed(row)
            if pause:
                time.sleep(pause)
        closed.append(row)
    return {"closed": closed, "skipped": skipped, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--liste", required=True, type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default")
    mode.add_argument("--apply", action="store_true")
    ap.add_argument("--protokoll", type=Path, default=DEFAULT_PROTOKOLL)
    args = ap.parse_args(argv)

    candidates, left = load_candidates(args.liste)
    client = TodoistClient(resolve_token())
    project_id, family = find_project(client)
    before = open_counts(client, family)
    print(f"Liste: {len(candidates)} Kandidaten im Projekt {PROJECT}, "
          f"{len(left)} Eintraege anderer Projekte bleiben unberuehrt")
    print(f"offen vorher:  {before}")

    prot = {
        "auftrag": "NG-Bullseye/project-manager-agent#144",
        "projekt": f"{PARENT}/{PROJECT}",
        "projekt_id": project_id,
        "rueckweg": "POST https://api.todoist.com/api/v1/tasks/<id>/reopen",
        "offen_vorher": before,
        "closed": [],
    }
    if args.apply and args.protokoll.exists():  # repeatable: keep earlier runs
        old = json.loads(args.protokoll.read_text(encoding="utf-8"))
        prot["closed"] = old.get("closed", [])
        prot["offen_vorher"] = old.get("offen_vorher", before)
    known = {r["id"] for r in prot["closed"]}

    def persist() -> None:
        prot["anzahl"] = len(prot["closed"])
        args.protokoll.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.protokoll.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(args.protokoll)

    def on_closed(row: dict) -> None:
        if row["id"] not in known:
            known.add(row["id"])
            prot["closed"].append(row)
        persist()

    res = run(client, candidates, project_id, apply=args.apply, pause=0.15,
              on_closed=on_closed if args.apply else None)
    verb = "geschlossen" if args.apply else "wuerde schliessen (dry-run)"
    print(f"{verb}: {len(res['closed'])} · uebersprungen: {len(res['skipped'])} "
          f"· Fehler: {len(res['errors'])}")
    reasons: dict[str, int] = {}
    for sk in res["skipped"]:
        reasons[sk["grund"]] = reasons.get(sk["grund"], 0) + 1
    for grund, n in sorted(reasons.items()):
        print(f"  SKIP {n} x {grund}")
    for er in res["errors"]:
        print(f"  ERR  {er['id']}: {er['fehler']}")

    if args.apply:
        prot["errors"] = res["errors"]
        persist()
        prot["offen_nachher"] = open_counts(client, family)
        persist()
        print(f"offen nachher: {prot['offen_nachher']}")
        print(f"Protokoll: {args.protokoll} ({prot['anzahl']} Task-IDs)")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())

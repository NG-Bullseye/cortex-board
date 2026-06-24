#!/usr/bin/env python3
"""
TodoistBackend — the Todoist persistence seam of the board (T-2 Phase 2a).

Same `BoardBackend` interface as `MarkdownBackend`, so server.py / api.py (and
the MCP tool surface) work unchanged whichever backend the facade picks. Where
the markdown backend projects `<ID>_slug.md` files under a tickets dir, this one
projects a Todoist **sub-project** (`config.todoist_project`, e.g. "cortex")
living under a **parent project** (`config.todoist_parent`, e.g. "boards"),
whose **Sections** are the board columns. A ticket is one Todoist task whose
*title carries the id prefix exactly like the markdown heading*: `"T-5 — Title"`.

Return contracts are byte-compatible with MarkdownBackend:
    read_board()   -> {columns, source, <col>: {column,rev,count,tickets[...]}}
                      card = {id,title,description,next_step}
    read_column()  -> one <col> dict (above)
    add_ticket()   -> {id,title,path,column}            (column always "new")
    move_ticket()  -> {id,to_column,path}
    update_ticket()-> {id,path}
    remove_ticket()-> {id,removed_path}
`rev` is the same content-hash over the column's ticket list as Markdown uses.
Where Markdown returns a filesystem `path`, Todoist returns `"todoist:<task_id>"`
under the same key (Todoist's REST create response carries no stable url).

HTTP uses stdlib urllib + json only — no new runtime dependency (`requests` is
not in the venv). The Todoist REST API v2 (`/rest/v2`) is deprecated (HTTP 410);
this targets the current **`/api/v1`** surface, whose list endpoints page via
`{results, next_cursor}` and whose section move goes through `/tasks/{id}/move`.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from config import BoardConfig

API = "https://api.todoist.com/api/v1"


def _rev(tickets: list[dict]) -> str:
    # identical canonicalization to backend._rev so the contract matches
    import hashlib

    canon = json.dumps(tickets, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def resolve_token() -> str:
    """env TODOIST_API_KEY, falling back to ~/.claude/mcp.json
    (mcpServers.todoist.env.TODOIST_API_KEY). Never logged / printed."""
    tok = os.environ.get("TODOIST_API_KEY")
    if tok:
        return tok.strip()
    mcp = Path.home() / ".claude" / "mcp.json"
    try:
        data = json.loads(mcp.read_text(encoding="utf-8"))
        tok = data["mcpServers"]["todoist"]["env"]["TODOIST_API_KEY"]
        if tok:
            return tok.strip()
    except Exception:
        pass
    raise RuntimeError(
        "TODOIST_API_KEY not found (env or ~/.claude/mcp.json mcpServers.todoist.env)"
    )


class TodoistError(RuntimeError):
    pass


class TodoistClient:
    """Thin stdlib HTTP client for the Todoist /api/v1 surface."""

    def __init__(self, token: str) -> None:
        self._token = token

    def _request(self, method: str, path: str, body: dict | None = None,
                 params: dict | None = None) -> dict | list | None:
        url = f"{API}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers = {"Authorization": f"Bearer {self._token}"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            # never echo the token; URL carries no secret
            raise TodoistError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise TodoistError(f"{method} {path} -> {e.reason}") from None

    def _paged(self, path: str, params: dict | None = None) -> list[dict]:
        """Collect all pages of a `{results, next_cursor}` list endpoint."""
        out: list[dict] = []
        p = dict(params or {})
        while True:
            resp = self._request("GET", path, params=p)
            if isinstance(resp, list):  # defensive: some endpoints may not page
                out.extend(resp)
                break
            results = (resp or {}).get("results", [])
            out.extend(results)
            cursor = (resp or {}).get("next_cursor")
            if not cursor:
                break
            p["cursor"] = cursor
        return out

    # ---- projects -----------------------------------------------------------
    def list_projects(self) -> list[dict]:
        return self._paged("projects")

    def add_project(self, name: str, parent_id: str | None = None) -> dict:
        body: dict = {"name": name}
        if parent_id:
            body["parent_id"] = parent_id
        return self._request("POST", "projects", body)  # type: ignore[return-value]

    def delete_project(self, project_id: str) -> None:
        self._request("DELETE", f"projects/{project_id}")

    # ---- sections -----------------------------------------------------------
    def list_sections(self, project_id: str) -> list[dict]:
        return self._paged("sections", params={"project_id": project_id})

    def add_section(self, name: str, project_id: str) -> dict:
        return self._request(  # type: ignore[return-value]
            "POST", "sections", {"name": name, "project_id": project_id}
        )

    # ---- tasks --------------------------------------------------------------
    def list_tasks(self, project_id: str) -> list[dict]:
        return self._paged("tasks", params={"project_id": project_id})

    def get_task(self, task_id: str) -> dict:
        return self._request("GET", f"tasks/{task_id}")  # type: ignore[return-value]

    def add_task(self, content: str, project_id: str, section_id: str,
                 description: str = "") -> dict:
        body = {"content": content, "project_id": project_id, "section_id": section_id}
        if description:
            body["description"] = description
        return self._request("POST", "tasks", body)  # type: ignore[return-value]

    def update_task(self, task_id: str, **fields) -> dict:
        return self._request("POST", f"tasks/{task_id}", fields)  # type: ignore[return-value]

    def move_task(self, task_id: str, section_id: str) -> dict:
        # section_id is NOT an updatable field on POST /tasks/{id} (error 42);
        # moving between sections must go through the dedicated /move endpoint.
        return self._request(  # type: ignore[return-value]
            "POST", f"tasks/{task_id}/move", {"section_id": section_id}
        )

    def delete_task(self, task_id: str) -> None:
        self._request("DELETE", f"tasks/{task_id}")


# `BoardBackend` (ABC) is imported lazily inside the class to avoid any import
# cycle and to keep backend.py free of a Todoist dependency.
from backend import BoardBackend  # noqa: E402


class TodoistBackend(BoardBackend):
    """Todoist-backed board: one task per ticket in a sub-project whose
    sections are the columns. Provisioning is idempotent (see `provision`)."""

    # how next_step is persisted into the task description so read_board can
    # recover it (and so the human Todoist UI stays readable).
    _NEXT_MARK = "\n\n---\nNext: "

    def __init__(self, config: BoardConfig, client: TodoistClient | None = None) -> None:
        self.config = config
        self._client = client or TodoistClient(resolve_token())
        # resolved lazily + cached: (project_id, {column: section_id})
        self._project_id: str | None = None
        self._sections: dict[str, str] = {}

    # ---- provisioning -------------------------------------------------------
    def provision(self) -> dict:
        """Idempotently ensure parent project -> sub-project -> one section per
        column exist; reuse what's already there. Safe to call repeatedly (no
        duplicates). Caches + returns {project_id, sections:{col:id}}."""
        cfg = self.config
        cl = self._client
        projects = cl.list_projects()

        def _find(name: str, parent_id: str | None) -> dict | None:
            for p in projects:
                if p.get("name") == name and (p.get("parent_id") or None) == parent_id:
                    return p
            return None

        parent = _find(cfg.todoist_parent, None)
        if parent is None:
            parent = cl.add_project(cfg.todoist_parent)
            projects.append(parent)
        sub = _find(cfg.todoist_project, parent["id"])
        if sub is None:
            sub = cl.add_project(cfg.todoist_project, parent_id=parent["id"])
            projects.append(sub)
        project_id = sub["id"]

        existing = {s["name"]: s["id"] for s in cl.list_sections(project_id)}
        sections: dict[str, str] = {}
        for col in cfg.columns:
            sid = existing.get(col)
            if sid is None:
                sid = cl.add_section(col, project_id)["id"]
                existing[col] = sid
            sections[col] = sid

        self._project_id = project_id
        self._sections = sections
        return {"project_id": project_id, "sections": sections}

    def _ensure(self) -> tuple[str, dict[str, str]]:
        if self._project_id is None:
            self.provision()
        assert self._project_id is not None
        return self._project_id, self._sections

    # ---- id / parse helpers (mirror MarkdownBackend semantics) --------------
    def _parse_id_title(self, content: str) -> tuple[str, str]:
        """Split a task title `T-5 — Title` into (id, title) using the same
        heading separator regex the markdown backend uses on the H1."""
        line = content.strip()
        m = self.config.heading_re.search(line)
        if m:  # tolerate a literal "# T-5 — Title" too
            line = m.group(1).strip()
        parts = self.config.sep_re.split(line, maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
        # no separator: whole thing is the id if it looks like one, else title
        if re.match(rf"^{re.escape(self.config.id_prefix)}-\d+", line):
            return line, ""
        return "", line

    def _split_desc(self, description: str) -> tuple[str, str]:
        """Recover (description, next_step) from the stored task description."""
        if self._NEXT_MARK in description:
            base, nxt = description.split(self._NEXT_MARK, 1)
            return base.strip(), nxt.strip()
        return description.strip(), ""

    def _compose_desc(self, description: str, next_step: str) -> str:
        desc = (description or "").strip()
        if next_step and next_step.strip():
            return f"{desc}{self._NEXT_MARK}{next_step.strip()}"
        return desc

    def _next_id(self) -> str:
        """Lowest unused <prefix>-NN among the sub-project's task titles.
        Cross-archive ids are markdown-only (archived md tickets), so for the
        Todoist projection the project scan is the full universe; reserved_ids
        are still respected."""
        cfg = self.config
        prefix = cfg.id_prefix
        used: set[int] = set()
        pid, _ = self._ensure()
        num_re = re.compile(rf"^{re.escape(prefix)}-(\d+)")
        for t in self._client.list_tasks(pid):
            tid, _title = self._parse_id_title(t.get("content", ""))
            m = num_re.match(tid)
            if m:
                used.add(int(m.group(1)))
        for rid in cfg.reserved_ids:
            m = num_re.match(rid)
            if m:
                used.add(int(m.group(1)))
        n = 1
        while n in used:
            n += 1
        return f"{prefix}-{n}"

    def _section_to_column(self, sections: dict[str, str]) -> dict[str, str]:
        return {sid: col for col, sid in sections.items()}

    def _find_task(self, ticket_id: str) -> dict | None:
        pid, _ = self._ensure()
        for t in self._client.list_tasks(pid):
            tid, _title = self._parse_id_title(t.get("content", ""))
            if tid == ticket_id:
                return t
        return None

    @staticmethod
    def _path(task_id: str) -> str:
        return f"todoist:{task_id}"

    # ---- BoardBackend: read -------------------------------------------------
    def read_board(self) -> dict:
        cfg = self.config
        pid, sections = self._ensure()
        sec_to_col = self._section_to_column(sections)
        buckets: dict[str, list[dict]] = {c: [] for c in cfg.columns}
        for t in self._client.list_tasks(pid):
            tid, title = self._parse_id_title(t.get("content", ""))
            if not tid:
                continue
            col = sec_to_col.get(t.get("section_id"), cfg.default_column)
            if col not in cfg.columns:
                col = cfg.default_column
            desc, nxt = self._split_desc(t.get("description", "") or "")
            display_title = f"{tid} — {title}" if title else tid
            buckets[col].append({
                "id": tid,
                "title": display_title,
                "description": desc,
                "next_step": nxt,
            })
        # stable ordering within a column (by id) so rev is deterministic
        for c in buckets:
            buckets[c].sort(key=lambda x: x["id"])
        out: dict = {"columns": list(cfg.columns), "source": f"todoist:{pid}"}
        for c in cfg.columns:
            tk = buckets[c]
            out[c] = {"column": c, "rev": _rev(tk), "count": len(tk), "tickets": tk}
        return out

    def read_column(self, column: str) -> dict:
        if column not in self.config.columns:
            raise KeyError(column)
        return self.read_board()[column]

    # ---- BoardBackend: mutations -------------------------------------------
    def add_ticket(self, title: str, description: str = "", next_step: str = "") -> dict:
        title = title.strip()
        if not title:
            raise ValueError("title required")
        pid, sections = self._ensure()
        tid = self._next_id()
        content = f"{tid} — {title}"
        task = self._client.add_task(
            content=content,
            project_id=pid,
            section_id=sections["new"],
            description=self._compose_desc(description, next_step),
        )
        return {"id": tid, "title": title, "path": self._path(task["id"]), "column": "new"}

    def move_ticket(self, ticket_id: str, to_column: str) -> dict:
        cfg = self.config
        if to_column not in cfg.columns:
            raise KeyError(to_column)
        _, sections = self._ensure()
        task = self._find_task(ticket_id)
        if not task:
            raise FileNotFoundError(f"ticket {ticket_id} not found in todoist:{cfg.todoist_project}")
        self._client.move_task(task["id"], sections[to_column])
        return {"id": ticket_id, "to_column": to_column, "path": self._path(task["id"])}

    def update_ticket(
        self,
        ticket_id: str,
        title: str | None = None,
        description: str | None = None,
        next_step: str | None = None,
    ) -> dict:
        task = self._find_task(ticket_id)
        if not task:
            raise FileNotFoundError(
                f"ticket {ticket_id} not found in todoist:{self.config.todoist_project}"
            )
        fields: dict = {}
        if title is not None and title.strip():
            fields["content"] = f"{ticket_id} — {title.strip()}"
        if description is not None or next_step is not None:
            # recompose the full description, preserving the untouched half
            cur_desc, cur_next = self._split_desc(task.get("description", "") or "")
            new_desc = cur_desc if description is None else description
            new_next = cur_next if next_step is None else next_step
            fields["description"] = self._compose_desc(new_desc, new_next)
        if fields:
            self._client.update_task(task["id"], **fields)
        return {"id": ticket_id, "path": self._path(task["id"])}

    def remove_ticket(self, ticket_id: str) -> dict:
        task = self._find_task(ticket_id)
        if not task:
            raise FileNotFoundError(
                f"ticket {ticket_id} not found in todoist:{self.config.todoist_project}"
            )
        self._client.delete_task(task["id"])
        return {"id": ticket_id, "removed_path": self._path(task["id"])}

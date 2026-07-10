#!/usr/bin/env python3
"""
GitHubBackend — GitHub Issues as the SSOT board backend.

Projects the board from GitHub Issues (via `gh` CLI), one issue == one ticket.
Status mapping uses dedicated `status:*` labels so the existing label taxonomy
(WD, bug, layer-*, …) is untouched. One issue carries exactly one status label;
issues without a status label default to the "new" column.

BoardBackend contract — same return shapes as MarkdownBackend:
    read_board()   -> {columns, source, <col>: {column,rev,count,tickets[...]}}
                      card = {id,title,description,next_step}
    read_column()  -> one <col> dict
    add_ticket()   -> {id,title,path,column}   (path = "gh:<issue_number>")
    move_ticket()  -> {id,to_column,path}
    update_ticket()-> {id,path}
    remove_ticket()-> {id,removed_path}
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from config import BoardConfig


def _rev(tickets: list[dict]) -> str:
    canon = json.dumps(tickets, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


# ---- Status label convention ------------------------------------------------
# One status:* label per issue. The backend strips these when projecting and
# adds/removes them on move. Existing labels (WD, bug, layer-*, …) pass through.
STATUS_LABELS = {
    "new": "status:new",
    # T-313: plan-review gate before the build starts, and code-review gate
    # after it finishes (before merge). Labels already exist on
    # NG-Bullseye/cortex (created out-of-band for #617) — _ensure_status_labels
    # is idempotent either way.
    "ready-for-plan-review": "status:ready-for-plan-review",
    "inprogress": "status:in_progress",
    "testing": "status:testing",
    "ready-for-review": "status:ready-for-review",
    "done": "status:done",
    "backlog": "status:parked",
}

# Reverse: label → column
LABEL_TO_COLUMN = {v: k for k, v in STATUS_LABELS.items()}


def _gh(*args: str, repo: str = "", stdin: str | None = None) -> str:
    """Run `gh` CLI, return stdout. Raises RuntimeError on failure."""
    cmd = ["gh"]
    if repo:
        cmd += ["-R", repo]
    cmd.extend(args)
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin,
            timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args)} -> rc={r.returncode}: {r.stderr.strip()[-300:]}")
        return r.stdout
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"gh {' '.join(args)} timed out") from None


def _gh_json(*args: str, repo: str = "") -> any:
    """Run `gh` with JSON output, parse and return."""
    out = _gh(*args, repo=repo)
    if not out.strip():
        return [] if "--jq" not in args else ""
    return json.loads(out)


class GitHubBackend:
    """GitHub Issues-backed board: one issue per ticket under a GitHub repo.

    Ticket IDs (T-NN, WD-NN) are embedded in the issue title as `ID — Title`.
    Status is a `status:*` label; exactly one per issue."""

    # how next_step is persisted into the issue body
    _NEXT_MARK = "\n\n---\n**Next:** "

    def __init__(self, config: BoardConfig) -> None:
        self.config = config
        self._repo = config.github_repo
        if not self._repo:
            raise ValueError(f"BoardConfig.github_repo required for GitHubBackend (board: {config.id_prefix})")
        # Cache: issue_number → {number, title, labels, body}
        self._cache: list[dict] | None = None
        self._cache_ts: float = 0.0

    def _list_issues(self, state: str = "open") -> list[dict]:
        """List all issues in the repo with JSON fields we need."""
        return _gh_json(
            "issue", "list",
            "--state", state,
            "--limit", "500",
            "--json", "number,title,labels,body,state",
            repo=self._repo,
        )

    def _cached_issues(self, force: bool = False) -> list[dict]:
        """Cached issue list, valid for the lifetime of one read_board call.
        Fetches open + closed issues so the done column is populated.
        Pass force=True to bypass cache (used after a mutation to ensure
        the next _find_issue or _next_id sees the new state)."""
        import time
        now = time.time()
        if force or self._cache is None or (now - self._cache_ts) > 2.0:
            open_issues = self._list_issues("open")
            closed_issues = _gh_json(
                "issue", "list", "--state", "closed", "--limit", "500",
                "--json", "number,title,labels,body,state",
                "--search", "sort:updated-desc",
                repo=self._repo,
            )
            seen = set()
            merged = []
            for issue in open_issues + closed_issues:
                n = issue["number"]
                if n not in seen:
                    seen.add(n)
                    merged.append(issue)
            self._cache = merged
            self._cache_ts = now
        return self._cache

    def _flush_cache(self) -> None:
        """Force the next _cached_issues call to refetch from GitHub."""
        self._cache = None
        self._cache_ts = 0.0

    # ---- Helpers -------------------------------------------------------------

    def _parse_id_title(self, title: str) -> tuple[str, str]:
        """Split issue title `T-5 — Title`, `WD-92: Title`, or `WD-81: text — 14` into (id, title).

        Priority: try ID-prefix regex first (most precise), then colon,
        then dash-separator. The ID portion is always `PREFIX-NN` at the start."""
        line = title.strip()

        # 1) ID-first: `T-NN` or `WD-NN` at the very beginning, followed by
        #    a separator (colon, space+dash, or whitespace).
        m = re.match(r"^((?:T|WD)-\d+[A-Za-z]?)\s*[:—–\-]\s*(.*)$", line)
        if m:
            return m.group(1), m.group(2)

        # 2) ID followed by plain whitespace (rare: `T-5 My title`)
        m = re.match(r"^((?:T|WD)-\d+[A-Za-z]?)\s+(.*)$", line)
        if m:
            return m.group(1), m.group(2)

        # 3) Fallback: try the config's sep_re (—/–/-)
        if self.config.sep_re.search(line):
            parts = self.config.sep_re.split(line, maxsplit=1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()

        return "", line

    def _match_id(self, title: str) -> str | None:
        """Extract ticket ID from an issue title, or None."""
        tid, _ = self._parse_id_title(title)
        if tid and re.match(rf"^({re.escape(self.config.id_prefix)}|WD)-\d+[A-Za-z]?$", tid):
            return tid
        return None

    def _find_issue(self, ticket_id: str) -> dict | None:
        """Find an issue by its ticket ID (T-NN / WD-NN). Searches cached issues
        (which already include both open and closed)."""
        for issue in self._cached_issues():
            if self._match_id(issue.get("title", "")) == ticket_id:
                return issue
        return None

    def _status_column(self, issue: dict) -> str:
        """Determine which board column an issue belongs to."""
        labels = {l["name"] for l in issue.get("labels", [])}
        for label_name, column in LABEL_TO_COLUMN.items():
            if label_name in labels:
                return column
        # Closed issues without status label → done
        if issue.get("state") == "CLOSED":
            return "done"
        # Open without status label → new
        return "new"

    def _current_status_label(self, issue: dict) -> str | None:
        """Return the current status:* label name of an issue, or None."""
        for label in issue.get("labels", []):
            if label["name"].startswith("status:"):
                return label["name"]
        return None

    def _split_desc(self, body: str) -> tuple[str, str]:
        """Recover (description, next_step) from issue body."""
        if not body:
            return "", ""
        if self._NEXT_MARK in body:
            base, nxt = body.split(self._NEXT_MARK, 1)
            return base.strip(), nxt.strip()
        return body.strip(), ""

    def _compose_desc(self, description: str, next_step: str) -> str:
        desc = (description or "").strip()
        if next_step and next_step.strip():
            return f"{desc}{self._NEXT_MARK}{next_step.strip()}"
        return desc

    def _extract_description(self, body: str) -> str:
        """First meaningful paragraph from the body for card display."""
        if not body:
            return ""
        # Body starts with `# ID — Title` heading — skip it
        lines = body.strip().splitlines()
        paras: list[str] = []
        skip_heading = True
        for line in lines:
            s = line.strip()
            if skip_heading and s.startswith("# "):
                skip_heading = False
                continue
            if s.startswith("#") or s.startswith("**Status:"):
                continue
            if not s:
                if paras:
                    break
                continue
            # Strip bold markers
            s = s.replace("**", "").replace("`", "")
            paras.append(s)
            if sum(len(x) for x in paras) > 300:
                break
        desc = " ".join(paras)
        if len(desc) > 260:
            desc = desc[:259].rstrip() + "…"
        return desc

    def _next_id(self) -> str:
        """Lowest unused <prefix>-NN across all open issues."""
        cfg = self.config
        prefix = cfg.id_prefix
        used: set[int] = set()
        num_re = re.compile(rf"^(?:{re.escape(prefix)}|WD)-(\d+)")
        for issue in self._cached_issues():
            tid, _ = self._parse_id_title(issue.get("title", ""))
            m = num_re.match(tid)
            if m:
                used.add(int(m.group(1)))
        # Also scan closed issues (archived tickets still consume their ID)
        closed = _gh_json(
            "issue", "list", "--state", "closed", "--limit", "500",
            "--json", "title", repo=self._repo,
        )
        for issue in closed:
            tid, _ = self._parse_id_title(issue.get("title", ""))
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

    @staticmethod
    def _path(issue_number: int) -> str:
        return f"gh:{issue_number}"

    # ---- BoardBackend: read -------------------------------------------------

    def read_board(self) -> dict:
        cfg = self.config
        buckets: dict[str, list[dict]] = {c: [] for c in cfg.columns}
        for issue in self._cached_issues():
            tid = self._match_id(issue.get("title", ""))
            if not tid:
                continue
            _, title = self._parse_id_title(issue.get("title", ""))
            col = self._status_column(issue)
            if col not in cfg.columns:
                col = cfg.default_column
            desc, nxt = self._split_desc(issue.get("body", "") or "")
            display_title = f"{tid} — {title}" if title else tid
            buckets[col].append({
                "id": tid,
                "title": display_title,
                "description": desc or self._extract_description(issue.get("body", "")),
                "next_step": nxt,
            })
        for c in buckets:
            buckets[c].sort(key=lambda x: x["id"])
        out: dict = {"columns": list(cfg.columns), "source": f"github:{self._repo}"}
        for c in cfg.columns:
            tk = buckets[c]
            out[c] = {"column": c, "rev": _rev(tk), "count": len(tk), "tickets": tk}
        return out

    def read_column(self, column: str) -> dict:
        if column not in self.config.columns:
            raise KeyError(column)
        return self.read_board()[column]

    # ---- BoardBackend: mutations --------------------------------------------

    def add_ticket(self, title: str, description: str = "", next_step: str = "") -> dict:
        title = title.strip()
        if not title:
            raise ValueError("title required")
        tid = self._next_id()
        issue_title = f"{tid} — {title}"
        body = self._compose_desc(description, next_step)
        new_label = STATUS_LABELS["new"]

        # Check if label exists; create if not
        self._ensure_status_labels()

        # gh issue create outputs the URL, not JSON. Parse the issue number from it.
        url = _gh(
            "issue", "create",
            "--title", issue_title,
            "--body", body,
            "--label", new_label,
            repo=self._repo,
        ).strip()
        # URL format: https://github.com/NG-Bullseye/cortex/issues/337
        number = int(url.rstrip("/").split("/")[-1])
        self._flush_cache()
        return {"id": tid, "title": title, "path": self._path(number), "column": "new"}

    def move_ticket(self, ticket_id: str, to_column: str) -> dict:
        cfg = self.config
        if to_column not in cfg.columns:
            raise KeyError(to_column)
        issue = self._find_issue(ticket_id)
        if not issue:
            raise FileNotFoundError(f"ticket {ticket_id} not found in github:{self._repo}")

        number = issue["number"]
        new_label = STATUS_LABELS[to_column]
        old_label = self._current_status_label(issue)

        self._ensure_status_labels()

        if old_label and old_label != new_label:
            _gh("issue", "edit", str(number),
                "--remove-label", old_label,
                "--add-label", new_label,
                repo=self._repo)
        elif not old_label:
            _gh("issue", "edit", str(number),
                "--add-label", new_label,
                repo=self._repo)

        # If moving to done and issue is open, close it
        if to_column == "done" and issue.get("state") == "OPEN":
            _gh("issue", "close", str(number), repo=self._repo)
        # If moving from done to another column, reopen
        elif to_column != "done" and issue.get("state") == "CLOSED":
            _gh("issue", "reopen", str(number), repo=self._repo)

        self._flush_cache()
        return {"id": ticket_id, "to_column": to_column, "path": self._path(number)}

    def update_ticket(
        self,
        ticket_id: str,
        title: str | None = None,
        description: str | None = None,
        next_step: str | None = None,
    ) -> dict:
        issue = self._find_issue(ticket_id)
        if not issue:
            raise FileNotFoundError(f"ticket {ticket_id} not found in github:{self._repo}")

        number = issue["number"]
        args = ["issue", "edit", str(number)]

        if title is not None and title.strip():
            args += ["--title", f"{ticket_id} — {title.strip()}"]
        if description is not None or next_step is not None:
            cur_desc, cur_next = self._split_desc(issue.get("body", "") or "")
            new_desc = cur_desc if description is None else description
            new_next = cur_next if next_step is None else next_step
            args += ["--body", self._compose_desc(new_desc, new_next)]

        if len(args) > 4:  # actual changes beyond base command
            _gh(*args, repo=self._repo)

        return {"id": ticket_id, "path": self._path(number)}

    def remove_ticket(self, ticket_id: str) -> dict:
        """Close the GitHub issue (equivalent to deleting an md file)."""
        issue = self._find_issue(ticket_id)
        if not issue:
            raise FileNotFoundError(f"ticket {ticket_id} not found in github:{self._repo}")

        number = issue["number"]
        if issue.get("state") == "OPEN":
            # Add status:done label and close
            self._ensure_status_labels()
            old_label = self._current_status_label(issue)
            edit_args = ["issue", "edit", str(number), "--add-label", STATUS_LABELS["done"]]
            if old_label and old_label != STATUS_LABELS["done"]:
                edit_args += ["--remove-label", old_label]
            _gh(*edit_args, repo=self._repo)
            _gh("issue", "close", str(number), repo=self._repo)

        self._flush_cache()
        return {"id": ticket_id, "removed_path": self._path(number)}

    # ---- Label provisioning -------------------------------------------------

    def _ensure_status_labels(self) -> None:
        """Idempotently create all status:* labels if they don't exist."""
        existing = set()
        try:
            labels = _gh_json("label", "list", "--json", "name", repo=self._repo)
            for l in labels:
                existing.add(l["name"])
        except RuntimeError:
            pass  # repo might not have labels yet

        for label_name in STATUS_LABELS.values():
            if label_name not in existing:
                try:
                    _gh("label", "create", label_name, repo=self._repo)
                except RuntimeError:
                    pass  # already exists or no permission — best-effort


# ---- Backward compatibility alias for tickets_source.py --------------------
# The BoardConfig.source field controls which backend is instantiated.
# When source == "github", tickets_source._make_board() returns a GitHubBackend.
GitHubBackendRef = GitHubBackend

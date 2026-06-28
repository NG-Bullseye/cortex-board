#!/usr/bin/env python3
"""
BoardBackend — the persistence seam of the board.

The generic board engine (read a board, add/move/update/remove a ticket) talks to
a `BoardBackend`; it never touches the filesystem itself. The cortex board uses
`MarkdownBackend`, which projects/edits `<ID>_slug.md` files under a tickets dir
(Leo's "einzige Ticket-Wahrheit"). Phase 2 (T-2) can hang a Todoist backend off
the same interface without changing the engine or the MCP tool surface.

Phase 1 is a pure refactor: `MarkdownBackend` reproduces, byte-for-byte, the
parsing, projection and atomic-write logic that used to live as free functions in
tickets_source.py. Same regexes (via BoardConfig), same dicts, same .md output.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from config import BoardConfig


def _rev(tickets: list[dict]) -> str:
    canon = json.dumps(tickets, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


class BoardBackend(ABC):
    """Storage-agnostic board operations. One instance == one board."""

    config: BoardConfig

    @abstractmethod
    def read_board(self) -> dict: ...

    @abstractmethod
    def read_column(self, column: str) -> dict: ...

    @abstractmethod
    def add_ticket(self, title: str, description: str = "", next_step: str = "") -> dict: ...

    @abstractmethod
    def move_ticket(self, ticket_id: str, to_column: str) -> dict: ...

    @abstractmethod
    def update_ticket(
        self,
        ticket_id: str,
        title: str | None = None,
        description: str | None = None,
        next_step: str | None = None,
    ) -> dict: ...

    @abstractmethod
    def remove_ticket(self, ticket_id: str) -> dict: ...


class MarkdownBackend(BoardBackend):
    """File-backed board: one markdown file per ticket under config.tickets_dir."""

    def __init__(self, config: BoardConfig) -> None:
        self.config = config

    # ---- IDs ----------------------------------------------------------------
    def _id_from_filename(self, name: str) -> str | None:
        m = self.config.file_re.match(name)
        return m.group("id") if m else None

    @staticmethod
    def _slugify(title: str, max_len: int = 50) -> str:
        s = re.sub(r"[^\w\s-]+", "", title.lower(), flags=re.UNICODE)
        s = re.sub(r"[\s-]+", "_", s).strip("_")
        return s[:max_len] or "ticket"

    def _next_id(self) -> str:
        """Lowest unused <prefix>-NN across active + extra (archive) globs."""
        cfg = self.config
        prefix = cfg.id_prefix
        used: set[int] = set()
        d = cfg.tickets_dir
        if d.is_dir():
            globs = [f"{prefix}-*.md", *cfg.extra_id_globs]
            paths: list[Path] = []
            for g in globs:
                paths += list(d.glob(g))
            num_re = re.compile(rf"^{re.escape(prefix)}-(\d+)")
            for p in paths:
                m = num_re.match(p.name)
                if m:
                    used.add(int(m.group(1)))
        # reserved ids (e.g. SC-00 for INDEX) are kept out of the pool
        for rid in cfg.reserved_ids:
            m = re.match(rf"^{re.escape(prefix)}-(\d+)", rid)
            if m:
                used.add(int(m.group(1)))
        n = 1
        while n in used:
            n += 1
        return f"{prefix}-{n}"

    # ---- Parse --------------------------------------------------------------
    def _parse_heading(self, text: str, fallback_id: str) -> tuple[str, str]:
        m = self.config.heading_re.search(text)
        if not m:
            return fallback_id, ""
        line = m.group(1).strip()
        parts = self.config.sep_re.split(line, maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
        return fallback_id, line

    def _parse_status(self, text: str) -> str:
        m = self.config.status_line_re.search(text)
        if not m:
            return ""
        raw = m.group(1).strip()
        raw = re.sub(r"[(),.\[\]]+$", "", raw)
        return raw.lower()

    @staticmethod
    def _extract_description(text: str, max_len: int = 260) -> str:
        """First non-metadata, non-heading paragraph after the H1."""
        para: list[str] = []
        skip_heading = True
        for raw_line in text.splitlines():
            s = raw_line.strip()
            if skip_heading and s.startswith("# "):
                skip_heading = False
                continue
            if s.startswith("#"):
                if para:
                    break
                continue
            if not s:
                if para:
                    break
                continue
            if s.startswith("**") and ":**" in s[:80]:
                continue
            if s.startswith(("- ", "* ")):
                s = s[2:]
            s = s.replace("**", "").replace("`", "")
            para.append(s)
            if sum(len(x) for x in para) > max_len + 80:
                break
        desc = " ".join(para)
        if len(desc) > max_len:
            desc = desc[: max_len - 1].rstrip() + "…"
        return desc

    def _iter_ticket_files(self) -> list[Path]:
        """Active tickets only (top-level files matching iter_glob; excludes
        reserved names/prefixes/ids and anything that isn't a valid ticket id)."""
        cfg = self.config
        if not cfg.tickets_dir.is_dir():
            return []
        out: list[Path] = []
        for p in cfg.tickets_dir.glob(cfg.iter_glob):
            if p.name in cfg.excluded_names:
                continue
            if any(p.name.startswith(pre) for pre in cfg.excluded_prefixes):
                continue
            fid = self._id_from_filename(p.name)
            if fid is None or fid in cfg.reserved_ids:
                continue
            out.append(p)
        return sorted(out, key=lambda p: p.name)

    def _parse_ticket(self, path: Path) -> dict | None:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
        fid = self._id_from_filename(path.name)
        if not fid:
            return None
        tid, title = self._parse_heading(text, fid)
        raw_status = self._parse_status(text)
        column = self.config.status_to_column.get(raw_status, self.config.default_column)
        desc = self._extract_description(text)
        display_title = f"{tid} — {title}" if title else tid
        return {
            "id": tid or fid,
            "title": display_title,
            "description": desc,
            "next_step": "",
            "status_raw": raw_status,
            "column": column,
            "path": str(path),
        }

    # ---- Write helpers ------------------------------------------------------
    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)

    def _find_by_id(self, ticket_id: str) -> Path | None:
        d = self.config.tickets_dir
        if not d.is_dir():
            return None
        for p in d.glob(f"{ticket_id}_*.md"):
            return p
        for g in self.config.archive_find_globs:
            for p in d.glob(g.format(id=ticket_id)):
                return p
        return None

    # ---- Read ---------------------------------------------------------------
    def read_board(self) -> dict:
        cfg = self.config
        buckets: dict[str, list[dict]] = {c: [] for c in cfg.columns}
        for p in self._iter_ticket_files():
            t = self._parse_ticket(p)
            if not t:
                continue
            col = t["column"] if t["column"] in cfg.columns else cfg.default_column
            buckets[col].append({
                "id": t["id"],
                "title": t["title"],
                "description": t["description"],
                "next_step": t["next_step"],
            })
        out: dict = {"columns": list(cfg.columns), "source": str(cfg.tickets_dir)}
        for c in cfg.columns:
            tk = buckets[c]
            out[c] = {"column": c, "rev": _rev(tk), "count": len(tk), "tickets": tk}
        return out

    def read_column(self, column: str) -> dict:
        if column not in self.config.columns:
            raise KeyError(column)
        return self.read_board()[column]

    # ---- Mutations ----------------------------------------------------------
    def add_ticket(self, title: str, description: str = "", next_step: str = "") -> dict:
        """Create a fresh <ID>_slug.md with `**Status:** new` and the body sections."""
        cfg = self.config
        title = title.strip()
        if not title:
            raise ValueError("title required")
        tid = self._next_id()
        slug = self._slugify(title)
        path = cfg.tickets_dir / f"{tid}_{slug}.md"
        body: list[str] = [
            f"# {tid} — {title}",
            "",
            "**Status:** new",
            f"**Erstellt:** {date.today().isoformat()}",
            "",
        ]
        if description.strip():
            body += ["## Kontext", "", description.strip(), ""]
        if next_step.strip():
            body += ["## Next", "", next_step.strip(), ""]
        self._atomic_write(path, "\n".join(body))
        return {"id": tid, "title": title, "path": str(path), "column": "new"}

    def move_ticket(self, ticket_id: str, to_column: str) -> dict:
        """Change a ticket's status by rewriting (or inserting) the `**Status:**` line."""
        cfg = self.config
        if to_column not in cfg.columns:
            raise KeyError(to_column)
        path = self._find_by_id(ticket_id)
        if not path:
            raise FileNotFoundError(f"ticket {ticket_id} not found in {cfg.tickets_dir}")
        text = path.read_text(encoding="utf-8")
        new_line = f"**Status:** {cfg.column_to_status[to_column]}"
        if cfg.status_replace_re.search(text):
            new_text = cfg.status_replace_re.sub(new_line, text, count=1)
        else:
            lines = text.splitlines()
            out: list[str] = []
            inserted = False
            for l in lines:
                out.append(l)
                if not inserted and l.startswith("# "):
                    out.append("")
                    out.append(new_line)
                    inserted = True
            new_text = "\n".join(out)
            if not new_text.endswith("\n"):
                new_text += "\n"
        self._atomic_write(path, new_text)
        return {"id": ticket_id, "to_column": to_column, "path": str(path)}

    def update_ticket(
        self,
        ticket_id: str,
        title: str | None = None,
        description: str | None = None,
        next_step: str | None = None,
    ) -> dict:
        """Rewrite the H1 heading if `title` is given. (Body edits stay manual.)"""
        path = self._find_by_id(ticket_id)
        if not path:
            raise FileNotFoundError(f"ticket {ticket_id} not found in {self.config.tickets_dir}")
        text = path.read_text(encoding="utf-8")
        if title:
            text = re.sub(
                r"^#\s+.+$", f"# {ticket_id} — {title.strip()}", text, count=1, flags=re.M
            )
        self._atomic_write(path, text)
        return {"id": ticket_id, "path": str(path)}

    def remove_ticket(self, ticket_id: str) -> dict:
        """Delete the ticket .md. For done items prefer `git mv` to archive/<YYYY-MM>/."""
        path = self._find_by_id(ticket_id)
        if not path:
            raise FileNotFoundError(f"ticket {ticket_id} not found in {self.config.tickets_dir}")
        target = str(path)
        path.unlink()
        return {"id": ticket_id, "removed_path": target}


class FindingsBackend(BoardBackend):
    """Read-only board fed by a maintenance `findings.json` (T-135).

    The maintenance scanner owns `config.findings_path` — a dict keyed by a
    stable `key`, each value carrying `severity` (critical|warn|info), `title`,
    `detail`, `suggestion`, `active` (bool), … This backend projects the
    *active* findings into the same board shape `MarkdownBackend.read_board`
    emits, bucketed by severity == column. A finding's board id is deterministic
    (`<id_prefix>-<sha1(key)[:8]>`) so a second mirror run re-recognizes the same
    Todoist task (round-trip via `TodoistBackend._parse_id_title`: the display
    title is `"MNT-<hash> — <title>"`, split on the standard ` — ` separator).

    READ-ONLY: it never writes findings.json (the scanner's single source).
    A missing/empty file yields an empty board (no crash). All mutation methods
    raise — this board is a mirror of an externally-maintained source.
    """

    def __init__(self, config: BoardConfig) -> None:
        self.config = config

    def _ticket_id(self, key: str) -> str:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
        return f"{self.config.id_prefix}-{h}"

    def _load_findings(self) -> list[dict]:
        path = self.config.findings_path
        if not path or not Path(path).is_file():
            return []
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, dict):
            return []
        return [v for v in data.values() if isinstance(v, dict) and v.get("active") is True]

    @staticmethod
    def _description(finding: dict) -> str:
        detail = (finding.get("detail") or "").strip()
        suggestion = (finding.get("suggestion") or "").strip()
        return f"{detail}\nFix: {suggestion}" if suggestion else detail

    def read_board(self) -> dict:
        cfg = self.config
        buckets: dict[str, list[dict]] = {c: [] for c in cfg.columns}
        for f in self._load_findings():
            key = f.get("key")
            if not key:
                continue
            sev = (f.get("severity") or "").strip().lower()
            col = sev if sev in cfg.columns else cfg.default_column
            tid = self._ticket_id(key)
            title = (f.get("title") or key).strip()
            buckets[col].append({
                "id": tid,
                "title": f"{tid} — {title}",
                "description": self._description(f),
                "next_step": "",
            })
        # stable order within a column (deterministic mirror diffs)
        out: dict = {"columns": list(cfg.columns), "source": str(cfg.findings_path)}
        for c in cfg.columns:
            tk = sorted(buckets[c], key=lambda t: t["id"])
            out[c] = {"column": c, "rev": _rev(tk), "count": len(tk), "tickets": tk}
        return out

    def read_column(self, column: str) -> dict:
        if column not in self.config.columns:
            raise KeyError(column)
        return self.read_board()[column]

    # ---- mutations: this board mirrors an external source, it never writes ---
    def _readonly(self) -> "NoReturn":  # type: ignore[name-defined]
        raise NotImplementedError(
            "FindingsBackend is read-only — findings.json is owned by the "
            "maintenance scanner; the board only mirrors it."
        )

    def add_ticket(self, title: str, description: str = "", next_step: str = "") -> dict:
        self._readonly()

    def move_ticket(self, ticket_id: str, to_column: str) -> dict:
        self._readonly()

    def update_ticket(
        self,
        ticket_id: str,
        title: str | None = None,
        description: str | None = None,
        next_step: str | None = None,
    ) -> dict:
        self._readonly()

    def remove_ticket(self, ticket_id: str) -> dict:
        self._readonly()

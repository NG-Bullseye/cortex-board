#!/usr/bin/env python3
"""
Project + write the Cortex board against ~/cortex/docs/tickets/*.md.

Per Leo's INDEX note (2026-05-21): docs/tickets is "die einzige Ticket-Wahrheit".
The board is therefore a *live projection* of those files — no second store, no
sync daemon, no migration job. Edit a ticket's `**Status:**` line, and the card
jumps to the right column on the next read.

Each ticket file is `T-NN_slug.md` or `WD-NN_slug.md` with:
    # ID — Title
    **Status:** <status>
    <body...>

Status normalization (the messy vocabulary in the existing 109 tickets is
straightened on the fly into the four-column flow):
    new / open / 🆕                  -> new
    in_progress / 🔄                 -> inprogress
    testing / TESTING / 🧪           -> testing
    done / DONE / closed / ✅ / 🟢   -> done
    wont-do / hw-block / parked      -> backlog (parked bucket)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path

TICKETS_DIR = Path(os.environ.get(
    "CORTEX_TICKETS_DIR", Path.home() / "cortex" / "docs" / "tickets"
))

COLUMNS = ("backlog", "new", "inprogress", "testing", "done")

STATUS_TO_COLUMN: dict[str, str] = {
    "new": "new", "open": "new", "🆕": "new",
    "in_progress": "inprogress", "in-progress": "inprogress", "inprogress": "inprogress",
    "🔄": "inprogress",
    "testing": "testing", "🧪": "testing",
    "done": "done", "closed": "done", "✅": "done", "🟢": "done",
    "wont-do": "backlog", "wontdo": "backlog",
    "hw-block": "backlog", "hwblock": "backlog", "blocked": "backlog",
    "deferred": "backlog", "parked": "backlog",
}

# Column -> canonical word written back into a .md when status changes.
COLUMN_TO_STATUS = {
    "new": "new",
    "inprogress": "in_progress",
    "testing": "testing",
    "done": "done",
    "backlog": "parked",
}

FILE_RE = re.compile(r"^(?P<id>(?:T|WD)-\d+[A-Za-z]?)_(?P<slug>.+)\.md$")
STATUS_LINE_RE = re.compile(r"^\*\*[Ss]tatus\s*:\*\*\s*([^\s(]+)", re.M)
STATUS_REPLACE_RE = re.compile(r"^\*\*[Ss]tatus\s*:\*\*[^\n]*$", re.M)
HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
SEP_RE = re.compile(r"\s+[—–\-]\s+")


# ---- IDs --------------------------------------------------------------------
def _id_from_filename(name: str) -> str | None:
    m = FILE_RE.match(name)
    return m.group("id") if m else None


def _slugify(title: str, max_len: int = 50) -> str:
    s = re.sub(r"[^\w\s-]+", "", title.lower(), flags=re.UNICODE)
    s = re.sub(r"[\s-]+", "_", s).strip("_")
    return s[:max_len] or "ticket"


def _next_t_id() -> str:
    """Lowest unused T-NN across active + archive."""
    used: set[int] = set()
    if TICKETS_DIR.is_dir():
        for p in list(TICKETS_DIR.glob("T-*.md")) + list(TICKETS_DIR.glob("archive/**/T-*.md")):
            m = re.match(r"^T-(\d+)", p.name)
            if m:
                used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"T-{n}"


# ---- Parse ------------------------------------------------------------------
def _parse_heading(text: str, fallback_id: str) -> tuple[str, str]:
    m = HEADING_RE.search(text)
    if not m:
        return fallback_id, ""
    line = m.group(1).strip()
    parts = SEP_RE.split(line, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return fallback_id, line


def _parse_status(text: str) -> str:
    m = STATUS_LINE_RE.search(text)
    if not m:
        return ""
    raw = m.group(1).strip()
    raw = re.sub(r"[(),.\[\]]+$", "", raw)
    return raw.lower()


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


def _iter_ticket_files() -> list[Path]:
    """Active tickets only (top-level *.md; excludes archive/, INDEX, README, EXECUTION_PLAN_*)."""
    if not TICKETS_DIR.is_dir():
        return []
    out: list[Path] = []
    for p in TICKETS_DIR.glob("*.md"):
        if p.name in {"INDEX.md", "README.md"}:
            continue
        if p.name.startswith("EXECUTION_PLAN_"):
            continue
        if _id_from_filename(p.name) is None:
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.name)


def _parse_ticket(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    fid = _id_from_filename(path.name)
    if not fid:
        return None
    tid, title = _parse_heading(text, fid)
    raw_status = _parse_status(text)
    column = STATUS_TO_COLUMN.get(raw_status, "backlog")
    desc = _extract_description(text)
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


def _rev(tickets: list[dict]) -> str:
    canon = json.dumps(tickets, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


# ---- Read -------------------------------------------------------------------
def read_board() -> dict:
    buckets: dict[str, list[dict]] = {c: [] for c in COLUMNS}
    for p in _iter_ticket_files():
        t = _parse_ticket(p)
        if not t:
            continue
        buckets[t["column"]].append({
            "id": t["id"],
            "title": t["title"],
            "description": t["description"],
            "next_step": t["next_step"],
        })
    out: dict = {"columns": list(COLUMNS), "source": str(TICKETS_DIR)}
    for c in COLUMNS:
        tk = buckets[c]
        out[c] = {"column": c, "rev": _rev(tk), "count": len(tk), "tickets": tk}
    return out


def read_column(column: str) -> dict:
    if column not in COLUMNS:
        raise KeyError(column)
    return read_board()[column]


# ---- Write helpers ----------------------------------------------------------
def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _find_by_id(ticket_id: str) -> Path | None:
    if not TICKETS_DIR.is_dir():
        return None
    for p in TICKETS_DIR.glob(f"{ticket_id}_*.md"):
        return p
    for p in TICKETS_DIR.glob(f"archive/**/{ticket_id}_*.md"):
        return p
    return None


def add_ticket(title: str, description: str = "", next_step: str = "") -> dict:
    """Create a fresh T-NN_slug.md with `**Status:** new` and the body sections."""
    title = title.strip()
    if not title:
        raise ValueError("title required")
    tid = _next_t_id()
    slug = _slugify(title)
    path = TICKETS_DIR / f"{tid}_{slug}.md"
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
    _atomic_write(path, "\n".join(body))
    return {"id": tid, "title": title, "path": str(path), "column": "new"}


def move_ticket(ticket_id: str, to_column: str) -> dict:
    """Change a ticket's status by rewriting (or inserting) the `**Status:**` line."""
    if to_column not in COLUMNS:
        raise KeyError(to_column)
    path = _find_by_id(ticket_id)
    if not path:
        raise FileNotFoundError(f"ticket {ticket_id} not found in {TICKETS_DIR}")
    text = path.read_text(encoding="utf-8")
    new_line = f"**Status:** {COLUMN_TO_STATUS[to_column]}"
    if STATUS_REPLACE_RE.search(text):
        new_text = STATUS_REPLACE_RE.sub(new_line, text, count=1)
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
    _atomic_write(path, new_text)
    return {"id": ticket_id, "to_column": to_column, "path": str(path)}


def update_ticket(
    ticket_id: str,
    title: str | None = None,
    description: str | None = None,
    next_step: str | None = None,
) -> dict:
    """Rewrite the H1 heading if `title` is given. (Body edits are out of scope —
    hand-edit the .md for the long-form fields; that's what they are for.)"""
    path = _find_by_id(ticket_id)
    if not path:
        raise FileNotFoundError(f"ticket {ticket_id} not found in {TICKETS_DIR}")
    text = path.read_text(encoding="utf-8")
    if title:
        text = re.sub(
            r"^#\s+.+$", f"# {ticket_id} — {title.strip()}", text, count=1, flags=re.M
        )
    _atomic_write(path, text)
    return {"id": ticket_id, "path": str(path)}


def remove_ticket(ticket_id: str) -> dict:
    """Delete the ticket .md. For done items prefer `git mv` to archive/<YYYY-MM>/."""
    path = _find_by_id(ticket_id)
    if not path:
        raise FileNotFoundError(f"ticket {ticket_id} not found in {TICKETS_DIR}")
    target = str(path)
    path.unlink()
    return {"id": ticket_id, "removed_path": target}


if __name__ == "__main__":
    b = read_board()
    print(json.dumps({c: b[c]["count"] for c in b["columns"]}))
    print(f"source: {b['source']}")

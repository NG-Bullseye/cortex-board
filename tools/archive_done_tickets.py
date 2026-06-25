#!/usr/bin/env python3
"""
archive_done_tickets — deterministic daily board housekeeping.

The cortex board's markdown tickets live git-tracked under `<repo>/docs/tickets`
(BoardConfig.tickets_dir). There was never a deterministic archive step, so
finished tickets piled up as Karteileichen instead of moving into the dated
`archive/<YYYY-MM>/` graveyard. This tool is that step — pure mechanics, no LLM:

  1. DRIFT-COMMIT first. Stage + commit the working-tree changes *under
     docs/tickets/* (modified + untracked board-MCP edits) so the archive runs
     on a clean tree and the board's own edits never get lost. Only the tickets
     dir is touched — never any other code/working-tree.
  2. ARCHIVE. Project the *active* tickets through the very same MarkdownBackend
     the live board uses; every ticket whose parsed status word is one of
     {done, closed, resolved, wont-do, wontfix} is `git mv`-ed into
     `<tickets_dir>/archive/<YYYY-MM>/` and the move committed.
  3. PUSH. `git push origin HEAD:develop` (PO-authorized deterministic board-DATA
     housekeeping exception — develop only, never main; robust to detached HEAD).

Reusable by config: a second board (maintenance/security) is just another
`--board` entry once its BoardConfig exists in config.py. Nothing here is
cortex-specific beyond the default config choice.

Guarantees
----------
- **Status truth = the backend.** Status is parsed via `MarkdownBackend`, not a
  re-invented regex, so "ONLINE — …" / "done (…)" parse exactly as the live
  board sees them.
- **Idempotent.** A second run with no new done tickets archives 0, commits 0.
- **Data-only.** Touches only `docs/tickets/` — no code, no σ/learning path.

Usage
-----
    python tools/archive_done_tickets.py --dry-run        # show plan, no write
    python tools/archive_done_tickets.py                  # real run (commit+push)
    python tools/archive_done_tickets.py --no-push        # commit, don't push
    python tools/archive_done_tickets.py --month 2026-06  # pin archive month
    python tools/archive_done_tickets.py --selftest       # temp-repo self test
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# repo root on path so `config` / `backend` import as on the live service
# (top-level imports, not a package).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfgmod  # noqa: E402
from backend import MarkdownBackend  # noqa: E402

# Status words that mean "finished, move me to the graveyard". Matched against
# the backend's parsed (lowercased, punctuation-stripped) status word.
DONE_STATUS = frozenset({"done", "closed", "resolved", "wont-do", "wontfix"})

# registry of archivable boards -> their BoardConfig. Adding maintenance/security
# later is one line here once their BoardConfig exists in config.py.
BOARDS = {
    "cortex": cfgmod.CORTEX_BOARD,
}

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# --------------------------------------------------------------------------- #
# git helpers — all scoped to the board repo and (for writes) to docs/tickets/ #
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo`, return stdout (raises on non-zero)."""
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return res.stdout


def _repo_root(path: Path) -> Path:
    """git toplevel that owns `path` (the board's tickets_dir lives in it)."""
    out = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(out)


def _rel(repo: Path, path: Path) -> str:
    """Path relative to repo root, as git wants it (posix)."""
    return path.resolve().relative_to(repo.resolve()).as_posix()


def _dirty_ticket_files(repo: Path, tickets_rel: str) -> list[str]:
    """Repo-relative paths under docs/tickets/ that are modified or untracked
    (the board-MCP edits we snapshot before archiving). Renames are listed by
    their new path. Excludes deletions of files that no longer exist.

    Uses `--porcelain -z`: NUL-delimited and NEVER c-quoted, so non-ASCII
    paths (Umlaut ticket names like T-91_…bedürfnis…md) pass through as raw
    bytes instead of `"…bed\\303\\274rfnis…"`. Quoted octal escapes were fed
    verbatim to `git add` and exploded the daily 05:00 housekeeping run with
    exit 128. With `-z` each record is `XY <path>\\0`; a rename/copy (R/C)
    emits a SECOND `<oldpath>\\0` record we skip."""
    out = _git(repo, "status", "--porcelain", "-z", "--", tickets_rel)
    records = out.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(records):
        rec = records[i]
        if not rec:
            i += 1
            continue
        # each record: 2-char XY status, a space, then the (unquoted) path
        xy, path = rec[:2], rec[3:]
        if xy and xy[0] in ("R", "C"):
            # rename/copy: the very next NUL field is the OLD path -> skip it
            i += 1
        if path:
            paths.append(path)
        i += 1
    return sorted(set(paths))


# --------------------------------------------------------------------------- #
# steps                                                                        #
# --------------------------------------------------------------------------- #
def _drift_commit(repo: Path, tickets_rel: str, dry_run: bool) -> list[str]:
    """Step 1: snapshot any working-tree changes under docs/tickets/."""
    dirty = _dirty_ticket_files(repo, tickets_rel)
    if dry_run or not dirty:
        return dirty
    _git(repo, "add", "--", *dirty)
    # only commit if staging actually produced a change (guard against a no-op)
    staged = _git(repo, "diff", "--cached", "--name-only", "--", tickets_rel).strip()
    if staged:
        _git(repo, "commit", "-m",
             "chore(board): daily working-tree snapshot vor Archivierung")
    return dirty


def _done_candidates(board_cfg, repo: Path) -> list[dict]:
    """Step 2 scan: active ticket files whose parsed status is a DONE_STATUS.
    Uses MarkdownBackend so status parsing matches the live board exactly."""
    md = MarkdownBackend(board_cfg)
    out: list[dict] = []
    for path in md._iter_ticket_files():  # active top-level tickets only
        t = md._parse_ticket(path)
        if not t:
            continue
        if t["status_raw"] in DONE_STATUS:
            out.append({
                "id": t["id"],
                "status": t["status_raw"],
                "path": Path(t["path"]),
            })
    return sorted(out, key=lambda c: c["path"].name)


def _archive(board_cfg, repo: Path, month: str, dry_run: bool) -> list[dict]:
    """Step 2: git mv every done ticket into archive/<month>/ and commit."""
    cands = _done_candidates(board_cfg, repo)
    if not cands or dry_run:
        return cands
    dest_dir = board_cfg.tickets_dir / "archive" / month
    dest_dir.mkdir(parents=True, exist_ok=True)
    for c in cands:
        src_rel = _rel(repo, c["path"])
        dst_rel = _rel(repo, dest_dir / c["path"].name)
        _git(repo, "mv", src_rel, dst_rel)
    _git(repo, "commit", "-m",
         f"chore(board): archive {len(cands)} done tickets -> archive/{month}/")
    return cands


def _push(repo: Path, dry_run: bool, no_push: bool) -> bool:
    """Step 3: push HEAD to develop (explicit refspec, detached-HEAD safe)."""
    if dry_run or no_push:
        return False
    _git(repo, "push", "origin", "HEAD:develop")
    return True


# --------------------------------------------------------------------------- #
# driver                                                                       #
# --------------------------------------------------------------------------- #
def run(board_key: str, month: str, dry_run: bool, no_push: bool) -> int:
    board_cfg = BOARDS[board_key]
    repo = _repo_root(board_cfg.tickets_dir)
    tickets_rel = _rel(repo, board_cfg.tickets_dir)

    print(f"=== archive_done_tickets  board={board_key}  month={month}  "
          f"dry_run={dry_run}  no_push={no_push} ===")
    print(f"repo:    {repo}")
    print(f"tickets: {board_cfg.tickets_dir}")

    drift = _drift_commit(repo, tickets_rel, dry_run)
    print(f"--- DRIFT ({'plan' if dry_run else 'committed'}): "
          f"{len(drift)} file(s) under {tickets_rel}/ ---")
    for p in drift:
        print(f"  drift  {p}")

    cands = _archive(board_cfg, repo, month, dry_run)
    print(f"--- ARCHIVE ({'plan' if dry_run else 'done'}): "
          f"{len(cands)} done ticket(s) -> archive/{month}/ ---")
    for c in cands:
        print(f"  archive  {c['id']:8s}  [{c['status']}]  {c['path'].name}")

    pushed = _push(repo, dry_run, no_push)
    print(f"--- PUSH: {'pushed HEAD:develop' if pushed else 'skipped'} ---")
    return 0


# --------------------------------------------------------------------------- #
# self-test — temp git repo, no live writes                                   #
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    import tempfile
    from dataclasses import replace

    print("=== SELFTEST (temp git repo, no live writes) ===")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        tickets = repo / "docs" / "tickets"
        (tickets / "archive").mkdir(parents=True)
        # fake tickets: new + parked stay, done/resolved/wont-do go
        fixtures = {
            "T-1_alpha.md":   "# T-1 — Alpha\n\n**Status:** new\n",
            "T-2_bravo.md":   "# T-2 — Bravo\n\n**Status:** done\n",
            "T-3_charlie.md": "# T-3 — Charlie\n\n**Status:** parked\n",
            "T-4_delta.md":   "# T-4 — Delta\n\n**Status:** resolved (verifiziert)\n",
            "T-5_echo.md":    "# T-5 — Echo\n\n**Status:** wont-do\n",
            "T-6_foxtrot.md": "# T-6 — Foxtrot\n\n**Status:** ONLINE — live grün\n",
            # non-ASCII (Umlaut) names — the real bug. T-8 is done (must archive),
            # T-9 is modified below (drift-commit must stage it without exit 128).
            "T-8_bedürfnis_done.md": "# T-8 — Bedürfnis\n\n**Status:** done\n",
            "T-9_realität_drift.md": "# T-9 — Realität\n\n**Status:** new\n",
            "INDEX.md":       "# Board Index\n\nnot a ticket\n",
            "README.md":      "# Readme\n\nnot a ticket\n",
        }
        for name, body in fixtures.items():
            (tickets / name).write_text(body, encoding="utf-8")

        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "selftest@cortex")
        _git(repo, "config", "user.name", "selftest")
        # commit everything EXCEPT one untracked drift file, to prove drift-commit
        # add everything (incl. the Umlaut files) so they are tracked & seeded
        _git(repo, "add", "--", "docs/tickets")
        _git(repo, "commit", "-q", "-m", "seed")
        # now create an untracked board-MCP edit (drift) + modify a tracked one
        # + modify the tracked Umlaut file (the path that c-quoting exploded on)
        (tickets / "T-7_golf.md").write_text(
            "# T-7 — Golf\n\n**Status:** new\n", encoding="utf-8")
        (tickets / "T-1_alpha.md").write_text(
            "# T-1 — Alpha\n\n**Status:** in_progress\n", encoding="utf-8")
        (tickets / "T-9_realität_drift.md").write_text(
            "# T-9 — Realität\n\n**Status:** in_progress\n", encoding="utf-8")

        # point a cortex-shaped BoardConfig at the temp tree
        cfg = replace(cfgmod.CORTEX_BOARD, tickets_dir=tickets)
        BOARDS["selftest"] = cfg

        rc = run("selftest", month="2026-06", dry_run=False, no_push=True)

        archive_dir = tickets / "archive" / "2026-06"
        moved = sorted(p.name for p in archive_dir.glob("*.md")) if archive_dir.is_dir() else []
        active = sorted(p.name for p in tickets.glob("*.md"))

        print("\n--- ASSERTIONS ---")
        ok = True

        def check(label: str, cond: bool) -> None:
            nonlocal ok
            ok = ok and cond
            print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

        # done/resolved/wont-do/ONLINE(=done col? no — ONLINE not in DONE_STATUS,
        # parses to 'online' which is NOT in our set) -> only explicit done set moves.
        check("T-2 (done) archived", "T-2_bravo.md" in moved)
        check("T-4 (resolved) archived", "T-4_delta.md" in moved)
        check("T-5 (wont-do) archived", "T-5_echo.md" in moved)
        check("T-8 (done, Umlaut name) archived", "T-8_bedürfnis_done.md" in moved)
        check("T-9 (Umlaut drift) stayed active", "T-9_realität_drift.md" in active)
        check("T-1 (new) stayed active", "T-1_alpha.md" in active)
        check("T-3 (parked) stayed active", "T-3_charlie.md" in active)
        check("T-6 (ONLINE — not in done-set) stayed active",
              "T-6_foxtrot.md" in active)
        check("T-7 (untracked drift) stayed active", "T-7_golf.md" in active)
        check("INDEX.md never touched", "INDEX.md" in active and "INDEX.md" not in moved)
        check("README.md never touched", "README.md" in active and "README.md" not in moved)

        # drift commit captured the untracked T-7 + modified T-1
        log = _git(repo, "log", "--oneline").strip()
        check("drift snapshot commit present",
              "daily working-tree snapshot vor Archivierung" in log)
        check("archive commit present",
              "archive 4 done tickets -> archive/2026-06/" in log)
        # T-7 is now tracked (drift-committed), tree clean of ticket dirt
        tracked = _git(repo, "ls-files", "docs/tickets/T-7_golf.md").strip()
        check("T-7 drift now tracked", tracked.endswith("T-7_golf.md"))
        # the Umlaut drift file (T-9) must be staged+committed too — exit-128 proof.
        # -z keeps the path raw (ls-files c-quotes non-ASCII without it).
        tracked9 = _git(repo, "ls-files", "-z", "--",
                        "docs/tickets/T-9_realität_drift.md").split("\0")
        check("T-9 (Umlaut) drift now tracked",
              "docs/tickets/T-9_realität_drift.md" in tracked9)
        dirty = _dirty_ticket_files(repo, "docs/tickets")
        check("working tree clean after run", dirty == [])

        # IDEMPOTENCY: a second run archives nothing, commits nothing
        before = _git(repo, "rev-parse", "HEAD").strip()
        run("selftest", month="2026-06", dry_run=False, no_push=True)
        after = _git(repo, "rev-parse", "HEAD").strip()
        check("second run idempotent (no new commit)", before == after)

        print(f"\n=== SELFTEST {'PASSED' if ok else 'FAILED'} ===")
        return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", default="cortex", choices=sorted(BOARDS),
                    help="which BoardConfig to housekeep (default: cortex)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show drift + archive plan, write/commit/push nothing")
    ap.add_argument("--no-push", action="store_true",
                    help="commit locally but do not push to develop")
    ap.add_argument("--month", default=None,
                    help="archive sub-dir YYYY-MM (default: current month)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the temp-repo self test (no live writes)")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    month = args.month or datetime.now().strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        ap.error(f"--month must be YYYY-MM, got {month!r}")
    return run(args.board, month, args.dry_run, args.no_push)


if __name__ == "__main__":
    raise SystemExit(main())

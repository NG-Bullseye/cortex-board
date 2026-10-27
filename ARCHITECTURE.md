# cortex-board — Architektur

## Deep Modules — Ticket lesen/schreiben → Board projizieren

> Stand 2026-10-27 · geprüft gegen 34d77c6

Der Flow: zwei Faces (MCP für Claude, REST für die App) rufen die Fassade `tickets_source.py`, die genau ein Backend wählt (`BOARD_BACKEND`, Default `github`). Es gibt keine Flow-Datei; die Sequenz lebt in `tickets_source.py::_make_board`. Jede Innenleben-Zelle ist `datei:zeile` und muss per `grep -n` treffen.

## Flow

> Stand 2026-10-27 · geprüft gegen 34d77c6

**Sequenz:**

| # | Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|---|
| 1 | MCP-Face | Tool-Call (stdio) | Aufruf Fassade | — | — | `server.py:82` |
| 1 | REST-Face + App-Host | HTTP `:8930` | Aufruf Fassade, `app/www` | Unit `cortex-board-api` | `CORTEX_BOARD_PORT`, `CORTEX_BOARD_WWW` | `api.py:41` |
| 2 | Fassade | Board-Operation | Backend-Instanz | — | `BOARD_BACKEND` | `tickets_source.py:49` |
| 3 | GitHub-Backend (Default) | Operation | Issue in `NG-Bullseye/cortex` via `gh` | `BOARD_BACKEND=github` | `config.py:343` | `github_backend.py:88` |
| 3 | Markdown-Backend (Legacy) | Operation | `.md`-Datei | `BOARD_BACKEND=markdown` | `CORTEX_TICKETS_DIR` | `backend.py:63` |
| 3 | Todoist-Backend | Operation | Todoist-Task | `BOARD_BACKEND=todoist` | — | `todoist_backend.py:182` |

**Parallel:**

| Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|
| GitHub→Todoist-Sync (abgeschaltet) | GitHub Issues | Todoist-Projekt `boards/cortex` | läuft nicht: Unit `sync-github-todoist.timer` ist `disabled` (nicht in diesem Repo); Projekt `cortex` am 10.10.2026 geleert (#144, `tools/close_frozen_cortex_project.py:129` über `todoist_backend.py:172` `close_task`), Rückweg `state/closed-frozen-cortex-2026-10-10.json` (je ID POST `tasks/<id>/reopen`) | — | `tools/sync_github_todoist.py:293` |
| Token-Usage-Sampler | Claude-Transkripte | Zähler-Sample | Timer `cortex-board-token-sample.timer` (2 h) | — | `token_usage.py:215` |
| Archivierung erledigter Tickets | Markdown-Board | `archive/` | manuell | — | `tools/archive_done_tickets.py:326` |
| Findings→Todoist-Mirror (Board `maintenance`) | `~/repos/maintenance/state/findings.json`, nur `active`, ohne `excluded_categories` (`pm-watchdog` = GitHub-Issue-Kopien, Leo 09.11.) | Todoist `boards/maintenance`, `MNT-<sha1(key)[:8]>`; trashes vor creates | `maintenance-board-mirror.timer` 05:00 (Unit im maintenance-Repo, davor `sync_todoist_closures.py`) | `config.py:294` `excluded_categories` | `backend.py:399`, `tools/sync_md_to_todoist.py:230` |

Verifiziert 2026-10-27: 12/12 Zellen treffen (1 berichtigt). Zeile Findings→Todoist-Mirror nachgezogen 2026-11-09 (Leo 09.11. „ja behebe das alles bitte“).

Verifiziert 2026-10-27: 12/12 Zellen treffen (1 berichtigt).

## Schnittstellen

> Stand 2026-10-27 · geprüft gegen 34d77c6

- Fassaden-Vertrag: Modul-Globals und Signaturen von `tickets_source.py` sind je Backend identisch (`tickets_source.py:47`) — `server.py`/`api.py` kennen kein Backend.
- Board-Konfiguration: `BoardConfig` in `config.py`, je Board eine Instanz (`GITHUB_CORTEX_BOARD`).

## Standard: Deep Modules + Flow

> Stand 2026-10-27 · geprüft gegen 34d77c6

Kanonisch in `~/repos/speech-engine/ARCHITECTURE.md` (R1–R5); hier nicht kopiert.

Weiteres: Betrieb und Board-Agent in `README.md`.

# cortex-board — Architektur

## Deep Modules — Ticket lesen/schreiben → Board projizieren

> Stand 2026-11-10 · geprüft gegen b2b05ec

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
| Quota-API (Stand 2026-11-10, pma#333) | `GET /api/quota` | Tokens je Verbraucher (`token-usage report --days 7 --json`, 5 min Prozess-Cache) + RAM/Swap je Registry-Dienst (`systemctl show` je scope; Template-Units `x@.service` über `systemctl list-units 'x@*.service'` auf Instanzen aufgelöst und summiert; `/proc/meminfo`); Titel aus `~/repos/monitor-mcp/registry.yaml`, nicht zugeordnete Sessions mit `title` = Agent-Name aus token-usage (`agent`), sonst cwd | je Request; Fehler 502 `token_usage_failed`/`systemctl_failed` | `MONITOR_REGISTRY` | `quota.py:156`, `api.py:92` |
| Archivierung erledigter Tickets | Markdown-Board | `archive/` | manuell | — | `tools/archive_done_tickets.py:326` |
| Findings→Todoist-Mirror (Board `maintenance`) | `~/repos/maintenance/state/findings.json`, nur `active`, ohne `excluded_categories` (`pm-watchdog` = GitHub-Issue-Kopien, Leo 09.11.) | Todoist `boards/maintenance`, `MNT-<sha1(key)[:8]>`; trashes vor creates | `maintenance-board-mirror.timer` 05:00 (Unit im maintenance-Repo, davor `sync_todoist_closures.py`) | `config.py:294` `excluded_categories` | `backend.py:399`, `tools/sync_md_to_todoist.py:230` |

Verifiziert 2026-10-27: 12/12 Zellen treffen (1 berichtigt). Zeile Findings→Todoist-Mirror nachgezogen 2026-11-09 (Leo 09.11. „ja behebe das alles bitte“). Token-Usage-Sampler (Timer, `token_usage.py`, `/api/token-usage`, Monitoring-Seite) 2026-11-09 entfernt, ersetzt durch Quota-API (pma#333).

Verifiziert 2026-10-27: 12/12 Zellen treffen (1 berichtigt).

## Schnittstellen

> Stand 2026-10-27 · geprüft gegen 34d77c6

- Fassaden-Vertrag: Modul-Globals und Signaturen von `tickets_source.py` sind je Backend identisch (`tickets_source.py:47`) — `server.py`/`api.py` kennen kein Backend.
- Board-Konfiguration: `BoardConfig` in `config.py`, je Board eine Instanz (`GITHUB_CORTEX_BOARD`).

## Standard: Deep Modules + Flow

> Stand 2026-10-27 · geprüft gegen 34d77c6

Kanonisch in `~/repos/speech-engine/ARCHITECTURE.md` (R1–R5); hier nicht kopiert.

Weiteres: Betrieb und Board-Agent in `README.md`.

<!-- graph:auto:start -->
## Graph-Auto (generated 2026-11-10 by `bin/arch_auto_block.py`, do not edit by hand)

**Deep Modules** (cross-file edges):
- `todoist_backend.py` — 31
- `config.py` — 27
- `backend.py` — 24
- `app/src/app/home/home.page.ts` — 20
- `app/www/runtime.8af056472c13eb28.js` — 19
- `tickets_source.py` — 18
- `app/src/app/board/board.page.ts` — 18
- `tools/sync_github_todoist.py` — 16

**Interfaces** (modules/symbols imported or called from other files):
- `app/www/runtime.8af056472c13eb28.js::a()` — used by 15 files
- `config.py` — used by 8 files
- `todoist_backend.py` — used by 7 files
- `backend.py` — used by 5 files
- `tickets_source.py` — used by 4 files
- `app/src/app/home/home.page.ts` — used by 3 files
- `github_backend.py` — used by 3 files
- `tickets_source.py::_make_board()` — used by 3 files
- `tools/sync_github_todoist.py` — used by 3 files
- `tools/sync_md_to_todoist.py` — used by 3 files

**Bus connections** (redis / route / http nodes of the house graph):
- `http:8765` ← `app/src/app/docs/docs.page.ts`
- `http:8900` ← `app/src/app/docs/docs.page.ts`
- `http:8903` ← `app/src/app/docs/docs.page.ts`
- `http:8930` ← `app/src/environments/environment.ts`
<!-- graph:auto:end -->

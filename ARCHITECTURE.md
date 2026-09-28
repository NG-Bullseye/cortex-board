# cortex-board — Architektur

## Deep Modules — Ticket lesen/schreiben → Board projizieren

Der Flow: zwei Faces (MCP für Claude, REST für die App) rufen die Fassade `tickets_source.py`, die genau ein Backend wählt (`BOARD_BACKEND`, Default `github`). Es gibt keine Flow-Datei; die Sequenz lebt in `tickets_source.py::_make_board`. Jede Innenleben-Zelle ist `datei:zeile` und muss per `grep -n` treffen.

## Flow

**Sequenz:**

| # | Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|---|
| 1 | MCP-Face | Tool-Call (stdio) | Aufruf Fassade | — | — | `server.py:82` |
| 1 | REST-Face + App-Host | HTTP `:8930` | Aufruf Fassade, `app/www` | Unit `cortex-board-api` | `CORTEX_BOARD_PORT`, `CORTEX_BOARD_WWW` | `api.py:41` |
| 2 | Fassade | Board-Operation | Backend-Instanz | — | `BOARD_BACKEND` | `tickets_source.py:49` |
| 3 | GitHub-Backend (Default) | Operation | Issue in `NG-Bullseye/cortex` via `gh` | `BOARD_BACKEND=github` | `config.py:343` | `github_backend.py:88` |
| 3 | Markdown-Backend (Legacy) | Operation | `.md`-Datei | `BOARD_BACKEND=markdown` | `CORTEX_TICKETS_DIR` | `backend.py:63` |
| 3 | Todoist-Backend | Operation | Todoist-Task | `BOARD_BACKEND=todoist` | — | `todoist_backend.py:178` |

**Parallel:**

| Modul | Eingang | Ausgang | Bedingung | Stellschraube | Innenleben |
|---|---|---|---|---|---|
| GitHub→Todoist-Sync | GitHub Issues | Todoist-Projekt | Unit `sync-github-todoist.timer` (5 min, nicht in diesem Repo) | — | `tools/sync_github_todoist.py:293` |
| Token-Usage-Sampler | Claude-Transkripte | Zähler-Sample | Timer `cortex-board-token-sample.timer` (2 h) | — | `token_usage.py:215` |
| Archivierung erledigter Tickets | Markdown-Board | `archive/` | manuell | — | `tools/archive_done_tickets.py:326` |

## Schnittstellen

- Fassaden-Vertrag: Modul-Globals und Signaturen von `tickets_source.py` sind je Backend identisch (`tickets_source.py:47`) — `server.py`/`api.py` kennen kein Backend.
- Board-Konfiguration: `BoardConfig` in `config.py`, je Board eine Instanz (`GITHUB_CORTEX_BOARD`).

## Standard: Deep Modules + Flow

Kanonisch in `~/repos/speech-engine/ARCHITECTURE.md` (R1–R5); hier nicht kopiert.

Weiteres: Betrieb und Board-Agent in `README.md`.

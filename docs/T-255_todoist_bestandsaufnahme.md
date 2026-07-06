# T-255 — Bestandsaufnahme Todoist-Board-Verwaltung (2026-07-06)

Konsolidierter Befund, kein Punktfix. Ground truth: `config.py` (BoardConfig-Registry),
live `systemctl --user`-Stand, echter Todoist-Projektbaum (`find-projects`), Journal-Logs.

## 1. Boards (`config.py::BOARDS`) — Ist-Zustand

| Board-Key | Quelle | Todoist-Projekt | Filter | Wer synct es |
|---|---|---|---|---|
| `cortex` (CORTEX_BOARD) | md `~/cortex/docs/tickets` | `coding-agent-a` | `title_tag_exclude="[cortex-b]"` | `maintenance-board-mirror.timer` (05:00 täglich) |
| `cortex-b` (CORTEX_B_BOARD) | md, gleiche Dateien | `coding-agent-b` | `title_tag="[cortex-b]"` | dito |
| `cerebellum` | md `~/repos/cerebellum/board/tickets` | `cerebellum` | — | dito |
| `maintenance` | `findings.json` (read-only) | `maintenance` | — | dito |
| `manager` (MANAGER_BOARD) | md `~/repos/project-manager-agent/docs/tickets` | `manager` | — | **NICHTS** — kein ExecStart in `maintenance-board-mirror.service` für `--board manager` |
| `cortex-github` (GITHUB_CORTEX_BOARD) | GitHub Issues `NG-Bullseye/cortex` | `cortex` | `title_tag_exclude="[cortex-b]"` | **NICHTS mehr** — `sync-github-todoist.timer` disabled (s. §3) |
| `cortex-b-github` (GITHUB_CORTEX_B_BOARD) | GitHub Issues, gleiches Repo | `coding-agent-b` | `title_tag="[cortex-b]"` | **NICHTS** — nirgends verdrahtet (Kommentar im Code: "NOT YET WIRED TO PRODUCTION") |
| — (`CORTEX_SCAN_BOARD`, SC-Tickets) | md `~/cortex/docs/scan-tickets` | `cortex` | — | **NICHTS** — kein `BOARDS`-Key, kein ExecStart überhaupt |

**Befund 1 — Lücke `manager`:** `MANAGER_BOARD` ist vollständig konfiguriert (Todoist-Projekt
`manager` existiert, ist im Baum sichtbar), aber `maintenance-board-mirror.service` hat keine
`ExecStart=... --board manager`-Zeile. Der Manager-Board-Sync läuft **nie automatisch** — nur
falls je manuell `sync_md_to_todoist.py --board manager` aufgerufen wurde. Das erklärt
vermutlich einen Teil des T-246-Musters ("auf dem richtigen Weg, aber nicht fertig").

**Befund 2 — zwei tote/nie verdrahtete Boards:** `GITHUB_CORTEX_B_BOARD` und
`CORTEX_SCAN_BOARD` sind vollständige `BoardConfig`-Objekte ohne jeden Aufrufer. Toter Code,
der bei jedem künftigen Board-Refactor mitgelesen/mitgepflegt werden muss, ohne je zu laufen —
Verwirrungsquelle Nr. 1 beim Draufschauen ("was synct wohin?").

## 2. Todoist-Projektbaum — echter Live-Stand (`find-projects`, 2026-07-06)

```
boards/
├── manager           (6h2pcgR9VMF8h9c5)
├── coding-agent-a     (6h2pcp9GqvRPH6Gq)
├── coding-agent-b     (6h2pcpww8hvxC95h)
├── cortex             (6gx6J22wGXrVP2MW)   ← Befund 3
├── security           (6h2pcvPRvfqhv269)   ← Befund 4
├── cerebellum         (6gxfmxGvP8mv6RH8)
└── maintenance        (6gxw5pJ6G932rwcG)
```

**Befund 3 — `cortex`-Projekt ist eine tote Leiche.** Zwei BoardConfigs zeigen (bzw. zeigten)
darauf: `CORTEX_SCAN_BOARD` und `GITHUB_CORTEX_BOARD` — beide ohne aktiven Sync-Aufrufer (s.
Befund 1/2, Timer disabled). Das Projekt bleibt als eingefrorener Snapshot vom letzten Lauf
vor der T-251-Konsolidierung stehen (u.a. das doppelte T-221 aus dem letzten Ticket). Niemand
räumt es auf, niemand schreibt mehr rein — reine Altlast, aber sichtbar in Leos App.

**Befund 4 — `security`-Projekt ist komplett verwaist.** Kein einziger `BoardConfig` in
`config.py` referenziert `todoist_project="security"` — weder aktiv noch dormant. Herkunft
nicht rekonstruierbar aus dem Code (vermutlich ein früherer manueller Test oder ein bereits
entfernter Board-Entwurf). Leo hatte über coding-agent explizit verlangt, dass "security"
NICHT von irgendeiner BoardConfig angefasst wird — das ist erfüllt, aber das Projekt selbst
liegt als Waise unter `boards` und sollte entweder gelöscht oder erklärt werden.

## 3. Sync-Prozesse/Timer — vollständige Liste

| Timer | Takt | Skript | Richtung | Status |
|---|---|---|---|---|
| `maintenance-board-mirror.timer` | täglich 05:00 | `archive_done_tickets.py` + `sync_md_to_todoist.py` (4× sequenziell: cortex, cortex-b, cerebellum, maintenance) | md/findings → Todoist (one-way, md bleibt SSOT) | **enabled, aktiv**, letzter Lauf 2026-07-06 09:58 (zusätzlich manuell getriggert), alle Schritte exit 0 |
| `sync-github-todoist.timer` | alle 5min | `sync_github_todoist.py` (kein `--board`-Arg → nur Lane A `cortex-github`) | GitHub Issues ↔ Todoist (bidirektional) | **disabled+stopped** (T-251 round 3) — war 1055/1055 Läufe in Folge mit HTTP 403 `MAX_ITEMS_LIMIT_REACHED` fehlgeschlagen, Reverse-Richtung nie funktional. Skript+Units bleiben liegen (dokumentiert-dormant), nicht gelöscht. |
| `watchdog-user-board.service` | dauerhaft (Type=simple, BLPOP-Loop) | `tools/user_board.py` | Todoist (Label `userboard`, EIGENER Projektbaum außerhalb `boards/`) ↔ Redis ↔ Telegram-Bot | Läuft, **völlig getrennter Consumer** — Leos private Lebens-Tasks, hat mit den Board-Todoist-Projekten nichts zu tun (kein `boards/`-Kind), aber verwendet dieselbe Todoist-API/denselben Account. Erwähnenswert nur weil "Todoist synct irgendwas" auf den ersten Blick wie ein weiterer Board-Sync aussieht. |

**Befund 5 — Mirror-Crash-am-Limit ist strukturell gefixt, aber fragil:** der `-` Prefix vor
jedem `sync_md_to_todoist.py`-ExecStart isoliert einen Todoist-`MAX_ITEMS_LIMIT_REACHED` (403)
pro Board — ein volles Projekt blockt die anderen nicht mehr. Aber: es gibt **keine Alarmierung**
bei so einem Fail — ein permanent 403endes Board würde bis heute niemand bemerken außer durch
Journal-Grep von Hand (wie beim toten `sync-github-todoist`-Timer, der 3 Tage unbemerkt lief).

## 4. Bekannte + neu gefundene Failure-Modes — Zusammenfassung

1. **Default-Fallback-Kollision (T-251, behoben):** vor der Lane-Remap teilten sich mehrere
   BoardConfigs implizit `todoist_project="cortex"` (Dataclass-Default). Jetzt tragen alle 7
   Instanzen den Wert explizit — verifiziert per AST-Walk.
2. **Toter dritter Sync-Timer (T-251, behoben):** `sync-github-todoist.timer`, 5-min-Takt,
   1055/1055 Fails, disabled. Siehe §3.
3. **Verwaiste Todoist-Projekte (neu, offen):** `cortex` (Befund 3) und `security` (Befund 4)
   — beide unter `boards/` sichtbar, beide ohne lebenden Schreiber.
4. **Nie verdrahtete Boards (neu, offen):** `manager` (Befund 1 — Lücke, sollte aber laufen)
   und `cortex-github`/`cortex-b-github`/`CORTEX_SCAN_BOARD` (Befund 2 — toter Code, absichtlich
   geparkt laut Kommentaren, aber nirgends als "geparkt" markiert außer im Docstring).
5. **Kein Alarming bei Sync-Fail (neu, offen):** Befund 5 — ein `-`-isolierter Fail ist unsichtbar,
   bis jemand von Hand ins Journal schaut. Kein Todoist-Sync-Fail erzeugt ein Watchdog-Finding.
6. **scan.py-Fehlklassifikation:** in `maintenance/scan.py` selbst findet keine Severity-Vergabe
   statt (`severity` wird nur aus `findings.json` durchgereicht, Zeile 94) — die Klassifikation
   passiert im separaten `maintenance-curate.timer` (`curate.py`, stündlich, Sonnet-Veredelung).
   Für eine belastbare Aussage zu falsch klassifizierten Findings bräuchte es ein eigenes,
   fokussiertes Ticket auf `curate.py`, nicht Teil dieser Board-Sync-Bestandsaufnahme.

## 5. Was tatsächlich fertig ist vs. was noch fehlt

**Fertig (T-251):** Lane-A/B-Split für den echten Produktionspfad (`sync_md_to_todoist.py` +
`maintenance-board-mirror.service`), alle 7 BoardConfigs mit explizitem `todoist_project`,
toter 5-min-Timer sauber stillgelegt (nicht gelöscht), live verifiziert (echter systemctl-Lauf,
kein Dry-Run).

**Offen, noch kein Ticket:**
- Manager-Board-Sync in `maintenance-board-mirror.service` verdrahten (`--board manager`
  ExecStart-Zeile fehlt schlicht) — 1-Zeilen-Fix, aber ohne den nichts synct.
- Entscheidung Leo: `cortex`- und `security`-Todoist-Projekt löschen oder als Archiv
  dokumentieren (destruktive Todoist-Aktion, daher nicht eigenmächtig gemacht).
- Entscheidung: `GITHUB_CORTEX_BOARD`/`GITHUB_CORTEX_B_BOARD`/`CORTEX_SCAN_BOARD` entweder aktiv
  verdrahten (GitHub-Issues-SSOT-Migration) oder als Code entfernen, wenn die Migration nicht
  mehr geplant ist — toter Code ohne Ablaufdatum ist selbst ein Failure-Mode.
- Kein Alarming bei isoliertem Sync-Fail (Befund 5).

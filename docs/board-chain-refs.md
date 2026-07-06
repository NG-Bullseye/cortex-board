# 3-Stufen-Board-Kette — Back-Ref-Konvention (T-260)

Bestätigte finale Kette (Leo): `Leo(Telegram) -> Manager-Board(MB) ->
Coding-Agent-Board(CA) -> Cortex-/Cortex-B-Board(T)`. Jede Stufe hat genau
EINEN Writer und genau EINEN Consumer; Übergabe ist immer copy-with-backref,
nie ein Move — jede Stufe behält ihre eigene Ticket-Historie.

## Boards (config.py)
| Stufe | Board-Key | ID-Prefix | tickets_dir | Writer | Consumer |
|---|---|---|---|---|---|
| 1 | `manager` | `MB` | `~/repos/project-manager-agent/docs/tickets/` | manager | coding-agent |
| 2 | `coding-agent` | `CA` | `~/repos/coding-agent/docs/tickets/` | coding-agent | cortex/cortex-b |
| 3 | `cortex`/`cortex-b` | `T`/`WD` | `~/cortex/docs/tickets/` | cortex/cortex-b | (Leo/watchdog) |

Alle drei teilen dieselbe Status-Vokabel/Spalten (`backlog/new/inprogress/
testing/done`) und denselben Markdown-Parser (`config.BoardConfig`,
`status_line_re`/`status_replace_re`) — keine Board-spezifische Parser-Logik.

## Back-Ref-Header (Freetext, KEIN Parser wertet das aus)
Beim Schneiden eines Tickets für die nächste Stufe trägt die neue Ticket-md
eine Kopfzeile, die auf den Ursprung zurückzeigt:

- CA-Ticket (aus einem MB-Ticket geschnitten): `Manager-Ref: MB-NN`
- T-/WD-Ticket (aus einem CA-Ticket geschnitten): `Coding-Agent-Ref: CA-NN`

Beispiel (Kopf eines CA-Tickets):

```markdown
# CA-07 — Welcome-Home Playlist Edge-Case

Manager-Ref: MB-14
**Status:** new
```

Reine Konvention für menschliche/LLM-Lesbarkeit (Nachvollziehbarkeit der
Kette beim Lesen einer Ticket-md) — kein Tool in diesem Repo parst, validiert
oder erzwingt das Feld. Ein fehlender/falscher Back-Ref bricht nichts.

## Sonderfall: `Cortex-Ref` (T-263, einmaliger Rückwärts-Backfill)

Die MB-/CA-Stufen (T-260) wurden gebaut, nachdem bereits 35 T-Tickets auf dem
Cortex-Board existierten. `Cortex-Ref: T-NN` markiert diese historischen
Backfill-Kopien (`MB-01`…`MB-35`, angelegt via
`tools/backfill_manager_board.py`) — Richtung ist umgekehrt zur normalen
Konvention (zeigt VOM Manager-Board ZURÜCK auf ein bereits existierendes
Cortex-Ticket, statt vom Kind auf den Elternteil, der es geschnitten hat).
Einmaliger Vorgang, kein wiederkehrender Sync-Mechanismus; künftige MB-Tickets
folgen wieder der normalen `Manager-Ref`/`Coding-Agent-Ref`-Kette.

## Sonderfall: `GitHub-Ref` (T-263 v2, Scope-Korrektur auf GitHub-Issues-SSOT)

coding-agent stellte fest: die eigentliche SSOT für den Cortex-/Watchdog-
Ticketbestand ist nicht das lokale `~/cortex/docs/tickets/T-*.md`-Verzeichnis,
sondern die GitHub Issues im Repo `NG-Bullseye/cortex` (T-NN **und** WD-NN
teilen sich dort ein Board). `GitHub-Ref: #NNN` markiert ein MB-Ticket, das
1:1 einer GitHub-Issue-Nummer entspricht — Richtung wie beim `Cortex-Ref`-
Sonderfall umgekehrt (zeigt VOM Manager-Board zurück auf eine bereits
existierende GitHub-Issue, nicht auf den schneidenden Elternteil). Status
(`backlog`/`done`) folgt direkt dem GitHub-Issue-Status (`OPEN`/`CLOSED`).

Dedup-Schlüssel für `tools/backfill_manager_board.py` ist ausschließlich
`GitHub-Ref: #NNN` (nicht Pfad, nicht MB-Nummer) — idempotent bei Re-Runs.
Die 35 aus dem v1-Backfill (`Cortex-Ref: T-NN`) behalten ihren Cortex-Ref
UND bekommen zusätzlich einen `GitHub-Ref`, per Titel-Match (`T-NN`-Substring
im Issue-Titel) aufgelöst, damit alle MB-Tickets ab jetzt einheitlich über
`GitHub-Ref` dedupliziert werden können. Wie beim `Cortex-Ref`-Fall: einmaliger
(wiederholbarer, aber nicht laufender) Backfill, kein Sync-Daemon — Status-
Drift zwischen GitHub und dem MB-Ticket wird nur bei einem erneuten manuellen
Lauf von `tools/backfill_manager_board.py` nachgezogen.

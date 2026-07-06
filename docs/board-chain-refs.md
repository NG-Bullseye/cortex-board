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

# AUD-03 dry run — offer_tape_2026-09-20.jsonl

**Date:** 2026-09-24. Read-only. `systemd-run --user --scope -p MemoryMax=4G`.
Webhook URL unset. No node signal. Artefact written under `/tmp`, not the
live derived tree. Exit 0.

File: `~/.local/share/breezy/catalog/quote_tape/decisions/offer_tape_2026-09-20.jsonl`
(60M, mode 0600). 63,208 JSON objects, every `climate_day` is `2026-09-20`.

| | count |
|---|---|
| `source=quote` | 31,534 |
| `source=depth` | 70 |
| `source=no_side_shadow` | 31,604 |
| `source=position_monitor` | 0 |
| other `source` | 0 |

Entry funnel (quote+depth only): **31,604 / 4,289 / 0 / 0 / 0 / 0**
(emitted, rung-resolved, cell-legal, priced, margin>0, orders).
Shadow, labelled not-orders: 31,604, same two reasons
(`observation_ambiguous` 27,315, `illegal_cell` 4,289).
Exit fired/refused: 0/0. Stalled inside the open window: **MDW only**
(LAX, MIA, SFO have entry rows). `no_side_calibration_unsafe` does not
appear in this file.

These are not the hand table in `DECISION_FUNNEL_2026-09-20.md`
(40,796 / 4,816 / 0 / 0 / 0 / 0). That note is also internally inconsistent
(table rung-resolved 4,816 vs prose `illegal_cell` 6,640). The sidecar on
disk today is a later snapshot: shadow rows exist one-for-one with the
entry reasons, and the entry total is 31,604, not 40,796. The digest
reports this file. The 40,796 table is pinned by the synthetic fixture in
`tests/unit/test_decision_funnel_daily_digest.py`, not by rewriting the
live sidecar.

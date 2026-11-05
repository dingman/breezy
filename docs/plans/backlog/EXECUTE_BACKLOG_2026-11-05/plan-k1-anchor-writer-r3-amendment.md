# K1-ANCHOR-WRITER r3 = r2 + this amendment (coordinator ruling after round-2 reviews)

Round-2 verdicts: python-reviewer HIGH (9/9/9/8/9/9); architect APPROVE (non-blocking #1-#6); prediction-market-reviewer REQUEST_CHANGES (one HIGH: cross-sha all-fault hole in `_writer_epoch_ns`).

## Ruling 1 — DROP THE READER CHANGE ENTIRELY (resolves pm HIGH; scope reduction)
Facts (r2 investigation 2, verified by python-reviewer): all 34 fill rows are 09-12..10-05; the earliest `exec_par/epoch` boot is 10-11; there are ZERO fills after 10-05. Therefore every historical fill already falls BEFORE `min(epoch boot_ts)` and the EXISTING control in `scripts/analysis/portfolio_roi_report.py:401-408` (every BUY fill with `ts_event >= min(epoch)` must have an anchor) passes on today's data. The reader returns `None` today ONLY because there are zero anchors (the "no anchors → None" branch), which the writer fixes.
Consequences:
- `_writer_epoch_ns`, the commit_sha rebase, the `[R.boot, min arm_ns)` window check, and tests R-a, R-c′, R-d, R-f, R-g, R-h are REMOVED from scope. `scripts/analysis/portfolio_roi_report.py` is touched ONLY for the docstring pin on `n_open_anchors_without_fill` (:338) — "anchors never filled, not live orders".
- The existing `min(epoch)` control is strictly fail-closed: ANY BUY fill at or after the first epoch that lacks an anchor → `None`. This closes the pm reviewer's cross-sha hole by construction (X's unanchored fill is after the first epoch → None), and the same-sha hole, with zero new logic (L-8, KISS, YAGNI).
- Accepted consequence: if a BUY fill lands between now and the deploy boot, the reader stays `None` until a separately reviewed, operator-visible exception keyed to that coid. Mitigation: deploy at the next 16:50Z daily boot (the node has had zero fills in a month; flat-orders check still required); record the pre-deploy fill count in docs/evidence/.
- Reader tests retained (all additive, production writers only): R-b anchor-no-fill → int; R-c post-epoch BUY fill without anchor → None; R-e no anchors → None (exists); R-i `^no` BUY fill without anchor → None; R-j shadow → None; NEW R-k: pre-epoch fills (ts < min epoch) with post-epoch anchored orders → int (pins that the existing control ignores pre-epoch fills, which is what makes today's data pass).
- The r1 premise "a writer alone leaves None forever" is WITHDRAWN as factually wrong.

## Ruling 2 — adopt architect r2 non-blocking #3, #4 (scope reduction)
- DROP trade.py change (a): `_today_by_station` is NOT refactored to call `pm_us_std_offset_of`. T11 pins parity against the registry offset instead. Boot must not import from an optional actor module (AC8 lets boot continue when the recorder fails to build).
- DROP the T13 AST caller-set pin (new exact-set contract, over-built). KEEP T13's behavioural half (`force_k1_unless_stage_eval_wired(latch, stage_eval_ports=None, …)` still pins K=1; `build_exec_watcher(1, …)` is `ExecRefusalAlertActor`). Put the "no K=1 reader of window/ledger_spend rows; K=1-era window rows are partial-day" fact in the recorder docstring and the PROGRESS K>1 handoff note. ADD (pm #4): a test asserting that if `force_k1_unless_stage_eval_wired` ever returns K>1 the test fails with that message — i.e. `test_k1_pin_guards_partial_day_window_rows`.

## Ruling 3 — adopt remaining non-blocking items
- Architect #1 (precondition): before Stage D, count BUY `OrderSubmitted` lines in the node log over the last 14 days (delegated, ≤15 lines back). Define BUILT = gate green + recorder registered at K=1 (W1) + pre-deploy reader returns `None` on a scratchpad copy of the production store. The live `int` is an EXTERNAL EVENT: record the wake condition ("first post-deploy BUY OrderSubmitted") and a wake time in PROGRESS.md (CLAUDE.md cycle rule 3). #7's consumption is scheduled after the first real fill; this item does NOT by itself unblock #7 (pm reviewer).
- Architect #2 (priority): the zero-fill month is itself a finding to surface in the cycle report; this item's urgency is lowered, scope unchanged.
- Architect #6 (path hygiene): all citations in the implementer brief use repo-root-relative paths (`src/breezy/adapters/polymarket_us/exec/reports.py:836-867`, `src/breezy/adapters/polymarket_us/leg_prices.py`, `src/breezy/adapters/polymarket_us/exec/submit_chain.py`, `src/breezy/adapters/polymarket_us/symbology.py:608`, `src/breezy/registry/sites.py:391,400-411`, `src/breezy/adapters/polymarket_us/exec/client.py:6701`, `tests/contract/test_node_composition_contract.py`).
- python #1: `pm_us_station_of_slug` raises on `parse_weather_slug(...) is None`, not only on an unregistered city; T5 covers both.
- python #2: `_on_submitted` raises `CounterAttributionError` when `order.has_price` is false → add test/assertion that the FQ entry is a priced limit order (read the FQ strategy's order factory via codegraph); if ever unpriced, every entry faults + alerts (acceptable, loud).
- python #4: AC3 wording states explicitly that the recorder forwards only `OrderSubmitted` (stricter than the watcher, which also handles OrderFilled/OrderDenied), and that K>1 enablement must forward fills.
- python #5: R-i fixture's fill row must carry the `^no` instrument id (the only leg marker).
- python #6: T8 asserts only "`_tick` runs on the loop thread" (timer callbacks may already arrive on the loop thread).
- python #3 / pm #1 compensating control: #7's brief must require an alert-sink check for `EXEC_PAR_ANCHOR_RECORDER_FAULT` since deploy before trusting an `int` (recorded in the PROGRESS #7 note). With Ruling 1 this is belt-and-braces, not the primary control.
- pm #3: terminal-close row becomes a HARD dependency of #7 in PROGRESS.md (not advisory); add a docstring-presence pin test for the "never filled" wording on `n_open_anchors_without_fill`.

## Resulting File-by-File (r3)
| Path | Kind | Change |
|---|---|---|
| src/breezy/runtime/exec_par_anchor_recorder.py | new | as r2 (≤170 lines) |
| src/breezy/app/trade.py | mod | ONLY (b) `_build_anchor_recorder(latch, stations)` + (c) actor-tuple append at :1358-1360; `_today_by_station` untouched; `build_exec_watcher` untouched |
| pyproject.toml | mod | mypy override entry :482-488 |
| scripts/analysis/portfolio_roi_report.py | mod | docstring pin ONLY (:338); no logic change |
| tests/unit/test_exec_par_anchor_recorder.py | new | T1-T12 + behavioural T13 + `test_k1_pin_guards_partial_day_window_rows` + priced-limit assertion |
| tests/unit/test_app_trade_anchor_recorder_wiring.py | new | W1-W3 |
| tests/unit/test_portfolio_roi_report.py | mod | R-b, R-c, R-i, R-j, R-k + docstring-presence pin; additive only; no existing `_anchor_case` re-pointed (no logic changed) |
| docs/core/PROGRESS.md | mod | row BUILT; deploy precondition; #7 hard deps (terminal-close row; alert-sink check); wake condition + time; zero-fill-month finding |
| docs/evidence/K1_ANCHOR_WRITER_<date>.md | new | pre-deploy: reader None, fill count, BUY OrderSubmitted count last 14 d; post-deploy: int + anchor count |

Stages: A1 (recorder + pyproject + tests) ∥ A2 (reader tests R-b/c/i/j/k + docstring pin; anchors via `write_order_anchor` on a real held latch) → B (trade.py wiring + W1-W3) → C (e2e through recorder; full gate) → D (review; merge; activate at next 16:50Z boot after flat-orders check; evidence).
Everything else in r2 stands (ACs 1-5, 7-9 with AC6/7 reader clauses reduced to the existing control; edge cases; LESSONS; invariants).

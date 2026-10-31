# Card A prereg r0 — merged blind review (prediction-market-reviewer + architect, 2026-10-31 ~14:10Z, HEAD 0c62697a)

Both VERDICT = REVISE. Coordinator merge; contradictions resolved inline. Every item below is binding for prereg r1.

## Blockers
- **K1 Frame construction (both).** Depth10 rows are per instrument (`forecast_cheap_screen_wp7.py:895-925`); r0 never says how one multi-rung frame is built, so a stale rung could sit beside fresh ones and manufacture a PASS. Rule: per rung, choose the row with the smallest |ts_event − 18:00:00Z| that is inside [17:30, 18:30) AND ≤ 60 s from 18:00:00Z; tie → earlier ts_event; selection by time only. Frame time = latest of the per-rung times. Any rung without a qualifying row → the day is MISSING. "First complete partition" = latest of the rungs' first ts_event (`wp7b:184-224` checks ids only); the ≥60 min rule applies to the frame time. Floor denominator = station-days with a selected valid frame; quiet books pushing the sample under 30 give INCONCLUSIVE, never KILL. Existing first-row selectors (`market_calibration_scan.py:354-359`, `wp7b:943-947`) are NOT to be used (design_r2:124).
- **K2 Leg 1 ask-present (pm).** `read_rung_tape` turns a zero pad into `ask=None` (`:918`). Leg 1 requires every rung ask present with scaled `ask_size_0 ≥ 1`; a missing ask drops leg 1 only. "Crossed" is defined only when both sides exist.
- **K3 Fee for q>1 (pm).** `fee_on_ask` rounds θ·p(1−p) per contract (`current_rung_hold/decision.py:319-326`), which is 0.00 for p<0.078 or p>0.922; the venue rounds once per fill θ·C·p(1−p) (`fees.py:314-315, 626-635`). The q=1 gate stays as is; prize(q) for q∈{5,10,25} recomputes one rounded fee per q-fill per leg; reword A5. Cite decision.py with its full path.
- **K4 Store reader must be read-only (arch, R6).** `SqliteStateStore` construction (`sqlite_store.py:117-126`) creates dirs, sets WAL, creates a table and commits on the live exec DB. Name a `mode=ro` reader on the models `trade_supervisor.py:640-642` or `labeling/fill_source.py:66`. Dry-run = zero writes includes zero store side effects.
- **K5 Own-order join (arch, R5).** Join on the base slug (`exec/client.py:7749, :7867-7870`; NO leg = slug+`^no`, `domain/instrument_leg.py:63-65`); an order on either leg excludes the market; first own order = min `created_ns` per slug. `slug` is optional on older K=1 records (`submit_intent.py:357-367`, likely the 09-13 taker families): resolve via `fill_by_fingerprint/<UTC day>:<fp>` → fill record `instrument_id` (`exec_par_durable_sources.py:360-375`); unresolvable → exit 2 before any write. Name the open-slot source: `CURRENT_INTENT_KEY` (`submit_intent.py:88`) through `all_intents` (`:804`).
- **K6 No second look on the same data (pm).** Drop `--force-new-look`; a second look requires a NEW prereg sha. Detect a prior look by `card_a_census.md` existing with this sha in its header (arch 9) and refuse.

## Should
- S1 Window, offsets, age caps, fee coefficient 0.0695 (`fee_coefficient` kwarg in `sum_ask_row`/`venue_fee`) are module constants asserted at startup; `--tape` is refused in census mode.
- S2 θ is per market from `instrument.info` (`fees.py:160-163`): check `feeCoefficient == 0.0695` per instrument, else that row is INCONCLUSIVE.
- S3 State that slippage (1 tick) + hurdle (−0.01·n) = 2 ticks per rung is intentional (design_r2:129, :274); a KILL means "no lock with 2 ticks/rung margin". Compare in integer cents, not float `<=` (`sum_ask_row` uses `math.fsum`, `wp7b:559-562`).
- S4 F4 H0 argument: "+0.05" is an empirical minimum from the earlier 64-partition run, not a theorem; it holds only given K1 and K2.
- S5 Prize table: normalize to 30 days (window is 40); count a frame for q only if min L0 size ≥ q; print the assumptions (full-size simultaneous taker fills, no leg risk, legs never both executed, voids out of scope, executable NO price may differ from 1 − YES bid per the SELL/BUY_SHORT representation).
- S6 Close J2: `_INSTRUMENT_RE` requires `high` (`h4_preliminary_economic_read.py:159-162`); low directories are skipped-and-noted per `forecast_cheap_screen_wp7.py:1011-1015`.
- S7 Unit line: `_fixed_scalars` is `forecast_cheap_screen_wp7.py:854-857`, unpack `wp7b:896`, divide ≈ `:917`; fix the off-by-one cites; size test uses L0 only.

## Notes
- N1 Second-runner guard: the flag branches in `main` before `collect` (`:1318`); reuses `read_rung_tape` (`wp7:860-923`), `_fixed_scalars`, `assert_complete_partition`, `fee_on_ask`, `SumAskRow`, `load_sites` (`wp7:995`); G1 imports the `maker_stage0_catalog_read` reader. Allowed new code: frame selector, own-order set, sha/freeze guard, atomic writer. Nothing else.
- N2 J4 (node-log reader) stays open and non-blocking: D6 "not performed" matches J5.
- N3 Citations verified correct by the architect (wp7b 505-512/537-565/888/893/854-857; fees.py; store 78-97/102/812-820); both catalog paths resolve, 09-21 has rows from 09-20 15:00Z.

## Card D G0 ruling (architect, Task B): stays BLOCKED pending a design amendment
The holdout seals DATES ≥ 2026-07-01 (`metar_routine_minute_probe.py:121-122`), not one product; Card D's window lies entirely inside it. Reading the 5-minute cache for those dates circumvents the seal, and types 1/2 (whole °C) measure a different quantity than routine type 3 (tenths). An amendment must state (a) the rule permitting in-holdout observation reads for this window and (b) the 5-minute product as the named source with its meaning. The 07-01..08-26 refresh is unnecessary for Card D (cache starts 08-27, before the window).

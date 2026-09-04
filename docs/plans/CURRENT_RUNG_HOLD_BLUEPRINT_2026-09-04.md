# `current_rung_hold` — implementation blueprint (2026-09-04) — DRAFT, under peer review

Authority: Grok rev 2 (`docs/evidence/grok_live_small_spec_rev2_2026-09-04.md`) over rev 1
§2–4, §7, §8; correction: the single trial per station-day is the FIRST EXECUTABLE snapshot
(`mb_current_rung_edge_study.py:545-551`: 0.05 < ask < 0.95 and size ≥ 1.0) to which the
taken test (`:632-644`) is applied once. Produced by code-architect, verified against source.

## 1. L-1 table (nautilus-trader 1.231.0)
| Need | Verdict | Evidence |
|---|---|---|
| Strategy base | NATIVE | `trading/strategy.pyx:109`, `on_start :222`, `submit_order :805` |
| Subscribe custom Data | NATIVE | `common/actor.pyx:1258`, `on_data :589`; factory `ingest/iem_observations.py:36-44` |
| Best ask/size | NATIVE push; cache pull DECLINED | `on_order_book_depth` + `strategy/depth10.market_quote_from_depth`; `cache.pyx:3061/3204` are pull-shaped |
| Instrument/theta/tick | NATIVE | `cache.pyx:3931`; `instrument.make_price`; theta `fees.py:227,242-284` |
| Marketable IOC limit, no post-only | NATIVE | `common/factories.pyx:312,318,320`; in-repo `cli_settlement_print_lock/strategy.py:926-934` |
| Halt via TradingState | NATIVE, DECLINED | `risk/engine.pyx:1137-1147` denies engine-wide; entry-only halt copies `running_extreme_lock/strategy.py:337-342` |
| Hold-to-settlement | NATIVE | `model/position.pyx:38,95,108`; no exit path (T-9) |
| LiveClock timers | NATIVE, DECLINED | event-driven only (L-16) |
| Running max | GAP in Nautilus, owned by `weather_common/running_extreme.py` | |
| Rung ladder | in-repo; `rung_containing` at `scripts/analysis/h4_preliminary_economic_read.py:268` is unimportable; use `WeatherBucketFacts.lower_f/upper_f` (`domain/weather_bucket_facts.py:57-88`) | |
| Durable per-station-day latch | Nautilus cache DB is Redis-only → DECLINED; use `runtime/sqlite_store.py:88 SqliteStateStore` with the L-22 locked-constructor shape of `runtime/submit_intent.py:489` | |

## 2. Files — `src/breezy/strategy/current_rung_hold/`
- `config.py`: `CurrentRungHoldConfig(StrategyConfig, frozen=True)`: `instrument_ids`, `station`, `std_utc_offset_hours`, `stale_observation_hours: float|None=None` (call site MUST set 0.75; ctor raises `MissingObservationBoundError` as `running_extreme_lock` does), risk overrides `min_liquidity_contracts=1.0`, `min_model_edge=0.0`, `allow_short=False` (never True), `stale_quote_minutes=15.0`, `min_hours_to_settlement=2.0`, `halt_hours_before_settlement=1.0`, `latch_db_path`, `latch_lock_path`. PINNED constants: window `[12:00,17:00)` LST, `ASK_QUALIFYING_LOW=0.05`/`HIGH=0.95`, `MIN_EXECUTABLE_SIZE=1.0`, `FEE_THETA_FOR_BE=0.06` (BE only; paid fee off instrument theta), `QUANTITY=1.0`, `L_EXTRA_NS=0`. NOT knobs: station set, lag arms (archive-study parameters).
- `archive_table.py`: GENERATED, FROZEN Part A `p_hold_lower[(station, season, hour_lst, width, m)]` with provenance header (study path, argv, corpus 2021-01-01..2025-12-31, git sha). No runtime load, no freshness refusal (the study emits Markdown, `scripts/` unimportable; precedent `MEASURED_MARGIN_MODEL_P`). Missing cell → `None` → dead-by-construction.
- `decision.py` (pure; no Nautilus, clock, I/O): `evaluate_snapshot(*, running_max, ladder, quote, r_receipt_ns, now, latched, table, cfg)`. Order: (1) in-window; (2) not latched; (3) missing/stale R → `observation_unavailable`; (4) rung: `exact_f` → containment; else lower/upper containment; mismatch/None → `observation_ambiguous` (never round, never midpoint, NEVER latch); (5) executable on a quote with `ts_event ≥ r_receipt_ns`: 0.05<ask<0.95, size≥1.0; fail → wait, no latch; (6) the day's ONE candidate → LATCH, then taken test once: legal cell (`interior m==0` or `open_upper`; never `m==1`, `open_lower`, `None`) and `p_hold_lower − (ask + 0.06·ask·(1−ask)) > 0`; fail → day consumed, `not_taken` tally; (7) pass → LONG_YES, qty 1, price = displayed level-0 ask.
- `trial_day_latch.py`: `open_trial_day_latch(store, lock_path)` sole constructor (L-22), exclusive flock for its lifetime, every method asserts held; keys `current_rung_hold/trial/{station}/{climate_day}` in `SqliteStateStore`; JSON `{latched_at_ns, instrument_id, ask, reason}`. Arm-before-submit, fail-closed: a crash between loses one trial (excluded from n), never double-sends.
- `strategy.py`: Nautilus wiring only. `on_start`: instruments, `WeatherBucketFacts` ladder (assert it partitions the integers), `subscribe_order_book_depth`, `subscribe_data(station_observation_data_type(), client_id=…)`, `RiskManager`, open latch. `on_data` → push → evaluate; `on_order_book_depth` → `market_quote_from_depth(include_ask_ladder=True)` → evaluate. Entry-only halt before every evaluation (return; no `_flatten`, no `close_all_positions`). `evaluate_order` with `SignalFreshness.observation(age from observed_at_ns)` (A6) and an ASK-ONLY `MarketQuote` (`bid=None`). Submit `order_factory.limit(BUY, price=instrument.make_price(ask), time_in_force=IOC, post_only=False)`; `working_orders` guard (T-1); never a SELL, never a remainder resend; IOC miss → logged `ioc_miss`, no retry.
- `__init__.py`.

## 3. Modify
- `risk.py:80-112` `COUNTED_REFUSAL_REASONS` += `"observation_ambiguous"` (decision-layer; widen once). Membership test mirroring `test_weather_common_risk.py:2096-2104`.
- `docs/evidence/PREREG_current_rung_hold_<D0>.md` before the first order (§6).

## 4. Dependencies
Seam A-2 (interval `RunningMax`) blocks `decision.py`; Seam B (publisher; NWS per A12) blocks `strategy.py` live tests; R-7 gives `_submit_order` a body — until then every live submit is refused by the standing refusal and the package must be green with that.

## 5. RED tests (by name)
`test_current_rung_hold_decision.py`: first executable snapshot is the only candidate even if a later ask is cheaper; a failed taken test consumes the station-day; a non-executable snapshot does not consume the day; an interval spanning two rungs → `observation_ambiguous`, never rounded; wholly-inside trades; an exact METAR value can never be ambiguous; an ambiguous snapshot does not set the latch; missing/stale R → `observation_unavailable`; a quote before the receipt of the R-setting observation is never priced; `m==1`/`open_lower`/missing cells dead by construction; break-even matches the study's at the published asks; no decision outside the window.
`test_current_rung_hold_trial_day_latch.py`: cannot construct without the lock; second opener fails closed; survives restart; crash between arm and submit consumes the day and never double-sends; resets on the next local-standard climate day.
`test_current_rung_hold_strategy.py` (TestClock harness): one IOC BUY of one contract at the displayed ask; never a SELL or flatten on any path; IOC miss not retried; entry-only halt returns without flattening; ask-only quote reaches `evaluate_order`; ctor raises when `stale_observation_hours` unset; `allow_short` False on the shipped config; every live submit refused by the standing refusal before R-7.
Barriers: `test_observation_ambiguous_is_within_the_counted_set`; `test_every_recorded_refusal_reason_is_within_the_counted_set` unmodified; strategy-module gate + `lint-imports`; `test_current_rung_hold_archive_table.py::test_the_frozen_table_reproduces_every_published_memo_row`.

## 6. Build order
1 widen `COUNTED_REFUSAL_REASONS` (today) · 2 `archive_table.py` + provenance pin (today) · 3 `trial_day_latch.py` (today) · 4 `config.py` · 5 `decision.py` (gated on Seam A-2) · 6 `strategy.py` (gated on 5 + Seam B) · 7 PREREG artefact · 8 live-small enablement (R-7; operator-only enablement + two caps).

## 7. Pre-registration artefact fields
D0 · stations LAX, MDW, MIA, SFO (NYC excluded, L-13) · window [12:00,17:00) LST · `L_extra=0` + archive arms 30 and 45 must agree · `stale_observation_hours=0.75` · ask band (0.05,0.95), depth ≥1.0, size 1, IOC, hold to settlement · interval precision rule · unit = one filled taken trial per station-day · `held=1` iff CLI FINAL `tmax_f` ∈ rung bought · `PnL = 1{held} − fill_px − fee` · `BE(ā)=ā+0.06·ā·(1−ā)` · Wilson z=1.959963984540054 · KILL n≥60 (upper < BE pooled or any n≥60 stratum) · SURVIVE n≥150 (lower > BE, no dead stratum, ΣPnL > 0) · UNDERPOWERED n<60 · structural dead (taken≈0 over ≥15 covered listed station-days) · frozen table sha · expected clock D0+22/D0+55 (optimistic) · standing refusal: no floor lowered, no post-hoc screen.

## 8. Least-confident decisions (peer review must settle)
1 width-based `is_ambiguous` vs ladder containment (containment chosen; A-2 helper advisory) · 2 latch store: `SqliteStateStore`+flock vs folding into R-7's store · 3 latch before the taken test (chosen, faithful to the study) · 4 frozen archive table vs runtime load (frozen chosen) · 5 ask-only `MarketQuote` path in `evaluate_order` (`risk.py:409-416`) unexecuted — RED test first · 6 Seam B feed must be NWS (A12) or `0.75 h` is miscalibrated; PREREG must name the feed.

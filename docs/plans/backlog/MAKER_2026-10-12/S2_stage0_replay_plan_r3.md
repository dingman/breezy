# S2 — Stage 0 exploratory maker replay (plan)

| Field | Value |
|---|---|
| ID / Title | S2 — Stage 0 exploratory maker replay: fill simulator + adverse-selection screen |
| Revision / Date / Status | **r3** (conformance revision of r2; supersedes it) / 2026-10-12 / **READY** |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` **v0.3**: §3, §6.0, §6.1, §6.5, §6.7 (queue stress only), §6.9. The run pins the spec sha256 |
| Emits | `docs/evidence/maker/STAGE0_REPLAY_<YYYY-MM-DD>.md` + sidecar dir `docs/evidence/maker/stage0_<YYYY-MM-DD>/` |

**Hard invariants** (binding on every WP and brief):
- Nautilus Trader is immutable (no patch, fork, bypass or reimplementation); `allow_short` stays `False`.
- Never weaken or delete a safety, settlement, contract or NO-SEND egress-firewall test. Exact-set barriers are WIDENED by one reviewed row, never relaxed (L-12).
- Never assign a value to an operator-reserved control (max daily budget, max per position); never touch live enablement or `BREEZY_ORDERS_ENABLED`; never edit a frozen `PREREG.json` or move a pre-registered date.
- **Stage 0 is EXPLORATORY and never promotion evidence; it never emits "GO".** The FQ-v2 NO-TRADE ruling stays in force; this is its T2 route.
- S2 touches only `scripts/analysis/` and `tests/unit/`: no `src/`, exec, strategy or `deploy/`. It fits nothing and never calls `open_holdout` (`src/breezy/analysis/nbp_calibration.py:353`).

## 1. Goal state (acceptance test)

Done when the evidence Markdown and its sidecar are committed and carry:
1. **Verdict** from the frozen table §1.1 (`NO-GO` / `NOT-KILLED` / `NOT-KILLED-UNSCREENED`), the exploratory banner, every failing condition, reason codes.
2. **Maker fill rate**, base (§6.1 rule) and stressed (2 × (size ahead + 1)), on the **station-day unit** and the **position unit** (station-day × rung), denominator = **all covered bid-bearing station-days** (§4.3 of this plan); never print-gated. Beside each: n, a Wilson interval, the gap-subtracted share of bid-live time, the share of episodes refused by the marketability guard, the share of episodes ended by a process cut, and implied days to 200 positions at MAX_RUNGS 2 and at the MAX_RUNGS 1 fallback.
3. **Bid-live hours** per station-day and per station, split into: forecast-valid hours, process-live hours, gap hours subtracted.
4. Realised bid histogram (1 ¢) on fills and on all episodes.
5. Win rate of fills next to the fills' mean model p_NO; climate-date cluster-bootstrap 95% CI with the cluster count; Clopper-Pearson sidecar. Point estimate and lower bound are separate numbers.
6. **§6.9** on the **pooled** filled set (decides): n filled, n unfilled, expected losses Σp, observed losses, both exact p-values, state (`PASS`/`FAIL`/`UNSCREENED`), analytic power line P(FAIL | k) for k = 1.5, 2, 3. The same numbers per stratum, descriptive only.
7. Descriptive net expectancy per fill, `w − (b + θ·b·(1−b))` at the market's taker θ (0.0695; the maker coefficient is unobservable offline, so taker θ is the conservative stand-in), with its one-sided 95% **upper** bound (climate-date cluster bootstrap). Unresolved past D+14 = LOSS; void = refund − fee with refund 0 until verified (§6.5). A negative value is reported, never a kill.
8. A tail-reliability table (WP5; report-only) and the holdout-touch disclosure line (§7).
9. **Pins** (WP1): `episodes.jsonl`, `scored_episodes.csv`, `process_schedule.json`, `tail_reliability.csv`, `pins.json`, `run_manifest.json` (argv, run_id, git commit, Python/Nautilus versions, seed 20260919 × 2000 iterations from `scoring_core.py:22,25`, `memory.peak`, wall time, free disk at start/end). `maker_stage0_stats --scored <csv>` recomputes every table.

### 1.1 Frozen verdict table (spec §6.0; frozen before any number exists)

First matching row sets the label; every failing row is printed.

| # | Condition | Verdict |
|---|---|---|
| V1 | base fill rate < 0.10 (point estimate, the stricter of the two units) | `NO-GO (fill)` |
| V2 | §6.9 `FAIL` | `NO-GO (adverse selection)` |
| V3 | stressed fill rate < 0.10 (stricter unit) | `NO-GO (stress)` — plan fill of a spec-table gap, Spec input 1 |
| V4 | §6.9 `UNSCREENED` | `NOT-KILLED-UNSCREENED` |
| V5 | otherwise (base and stressed ≥ 0.10, §6.9 `PASS`) | `NOT-KILLED` |

- **Quantity unit bracketed** (spec §6.0): if S1 delivers a USD bracket rather than one resolved unit, the replay runs under both hypotheses and the more severe verdict governs (order NO-GO > NOT-KILLED-UNSCREENED > NOT-KILLED); both are printed.
- `NOT-KILLED*` licenses only S4/S5 shadow work under the §7.9 holdout gate. It is not evidence of edge.
- Annotation (never changes the label): `TAIL-MISCALIBRATED` when the WP5 tail table fails its exact test at 0.05.
- With p_YES ≤ 0.06 the pooled 10-expected-loss minimum needs ≈ 170+ pooled fills, so on the pre-freeze tape the realistic outcomes are `NO-GO` or `NOT-KILLED-UNSCREENED`. The report says so; the power line shows it.

## 2. Entry criteria and STOP conditions

**Entry**
- **E1.** S1 has delivered the censused-day list and `TRADE_QUANTITY_UNIT` resolved **or bracketed**, both passed by path (`--census-days`, `--trade-unit`). Only censused (or SEARCH-declared) days are read.
- **E2.** The NBP store covers every replayed day (pre-step P2; r2 measured its end at `nbp_20260929_19z`; P2 re-checks).
- **E3.** One heavy job at a time on the host.
- **E4.** `df -B1 --output=avail $HOME` ≥ 10 GiB before P2, before every gate, the benchmark and the run. **Today 4.2 GB, so S2 is blocked**; freeing disk is the coordinator's job. S2 deletes only what it created.

**STOP**
- **S-1 (programme).** On any `NO-GO`, nothing is built and S4/S5 are not started.
- **S-2.** The WP0 direction check is inconclusive. Return to the spec.
- **S-3.** The S1 unit is `UNRESOLVED` and not even bracketed (spec §9.3).
- **S-4.** Zero covered bid-bearing station-days: no verdict is computable; report and stop (Spec input 2). A small but non-empty sample still gets a verdict, printed with its n and interval.
- **S-5.** The benchmark predicts > 6 h or > 4 GiB RSS. Fix the reader first.
- **S-6.** A WP2 verify-first check or the WP6 local-day assertion fails (window premise wrong). Return to the spec.

## 3. Simplest direct path

One read-only script replays every censused (station, climate day). For each one it reads the YES-leg Depth10, prints and gap/truncation rows; takes calibrated p_NO from the day-D NBP vectors; applies the §3 rule at every decision instant inside the simulated process schedule; credits fills with the §6.1 price-priority trade-through rule; and, only after all simulation, scores against CLI FINAL truth and applies the frozen table. No BacktestEngine, Strategy or persistence: the output is one label from a five-row table. The only machinery beyond that is what moves the label: the process schedule (R3), gap subtraction, the exact §6.9 tests, and leak-safe clock order.

**Scope.** Spec §6.0: first replayable climate day is 2026-09-18. Day D's bid window opens 16:50Z on D−1 (§3.1), so D = 09-18 needs the print feed recording from 09-17 16:50Z. WP0 measures the global first print instant; if it is later than 09-17 16:50Z, the first day is 09-19 and the report states the measurement. The last day is the last censused day with CLI FINAL truth. The pre-freeze census (≤ 09-25) gives ~8 dates × 4 stations; more needs S1's SEARCH declaration.

### 3.1 Bid-live window (STALE_H = 8, process schedule, binding on the sample)

Forecast side: `ForecastQuantileState` holds one climate day per cycle (`forecast_state.py:245-279`); v0.3 requires `vector.climate_day == S.day`, so day D's vectors are the **13Z D−1, 19Z D−1 and 01Z D** cycles (`nbp_backfill.py:127`, `CYCLES = (13, 19, 1)`); the 13Z D cycle targets D+1. Median `available_at − cycle` (2026-08/09, 60 cycles each, r2 measurement): 64 min (01Z, 13Z), 77 min (19Z); maxima 804 / 137 / 193 min. With STALE_H = 8 the vectors chain without a hole at p50: valid D−1 14:04Z → D 10:04Z (20.0 h).

Process side (code constants): daily `STOP_PRIOR_UTC` 16:40Z and `LAUNCH_UTC` 16:50Z (`trade_supervisor_core.py:37-38`); permit TTL 10 h (`adapters/polymarket_us/safety.py:172`), nominal window `[16:50Z, 02:50Z next day)` exactly as `permit_window_for_day` computes it (`scripts/analysis/nbp_shadow_parity_pure.py:151-155`); mid-day relaunches only in 17:10Z → 01:00Z (`trade_supervisor_core.py:1205-1209`, ≤ 3 attempts ≥ 5 min apart, `:58-59`) and never past the first-boot permit anchor (`:2349-2360`). GTD `expire_time = min(D 09:00 LST, permit expiry, end of booking UTC day)` cuts every rest at 00:00Z.

| Station (std offset) | Forecast-valid (p50) | Process-live (nominal) | Bid-live h | Episode cuts | Bids end (LST) | 09:00 LST cancel |
|---|---|---|---:|---|---|---|
| LAX, SFO (−8) | D−1 14:04Z → D 10:04Z | D−1 16:50Z → D 02:50Z | ≈ 10.0 | 00:00Z; price change at a release (~20:17Z, ~02:04Z) or book update; logged relaunches | 18:50 D−1 | never binds |
| MDW (−6) | same | same | ≈ 10.0 | same | 20:50 D−1 | never binds |
| MIA (−5) | same | same | ≈ 10.0 | same | 21:50 D−1 | never binds |

Consequences: the permit, not staleness, ends bidding; 7.2 h of forecast-valid time (02:50Z → 10:04Z) and 2.8 h before launch are dead; every bid rests before climate day D begins locally, so **the observation cancel cannot bind** (no observation of day D exists yet). WP6 asserts that no episode extends past local midnight starting D (else S-6) and therefore loads no observation data. WP6 reports the measured hours.

## 4. Nautilus null-hypothesis check

| Need | Native capability checked | Verdict |
|---|---|---|
| Read depth, prints, gaps, truncation, offset | `ParquetDataCatalog.query` (`persistence/catalog/base.py:158,176,221`; `parquet.py:1648`). Breezy records `QuoteTapeGap` (`tape_records.py:55`; `covers` :162; `resolved_gaps_by_seq` :536), `DepthTruncation` (:450), `VenueClockOffset` (:227-244) | **Reuse**, scoped per instrument and absolute ns |
| Maker queue fills | `BacktestVenueConfig.queue_position` / `trade_execution` (`backtest/config.py:114-124`) | **Not used.** The tape holds only the YES instrument (`parsing.py:936-938`), so a native resting NO bid is SELL YES at 1−b with no YES held, i.e. a short: `allow_short=False` (`strategy/ladder_ev/config.py:171`) and the kernel guard refuses it (`runtime/backtest_order_guard.py:118,284`). Neither the Q₀-reduction rule nor the 2× stress is a config knob |
| Point-in-time forecast | `ForecastQuantileState.push/value_at` (`forecast_state.py:245,310`; `climate_day` :224) | **Reuse** |
| Rung probability | `load_live_calibration` (`calibration_artefact.py:236`), `resolve` (:134), `rung_probability_interval` (`quantile_density.py:393`; `F(hi+.5)−F(lo−.5)`) | **Reuse** |
| Rung facts; column day | `bucket_facts_from_instrument_id` (`instrument_facts.py:72`); `max_column_lst_climate_day` (`nbm_quantile_parse.py:187`) | **Reuse** |
| Process schedule | `permit_window_for_day` (`nbp_shadow_parity_pure.py:151`); supervisor constants above | **Reuse** (imported, not copied) |
| Bootstrap; report rows | `bootstrap_cluster_draws` / `percentile_interval` / `SupportsClusterKey` (`scoring_core.py:216,246,199`); `GateResult` (`resting_bid_report.py:37`) | **Reuse** (descriptive intervals only) |
| Exact tests | `scipy.stats.binomtest` (library, already in the venv); Poisson-binomial tail by a 20-line DP | new, pure |

Genuinely new (spec §9.5/§9.6): the p_NO loader, the maker fill simulator, the §6.9 exact screen. FQ `evaluate` is barred by `NotDPlus1` (`decision.py:138`) and the F6 veto; neither applies offline, and Stage 0 authorises nothing live.

## 5. Work packages

**Conventions:** code in `scripts/analysis/maker_stage0_*.py` (absolute imports as in `fq_loss_taxonomy_reconstruct.py:27`); tests in `tests/unit/test_maker_stage0_*.py`; modules < 400 lines, functions < 50; pure modules do no I/O.

**Focused gate (every WP):** (1) E4 preflight. (2) `PYTHONPATH=<wt>/src scripts/ci/run_tests_no_egress.sh tests/unit/test_maker_stage0_*.py <firewall guards, import gates, test_autonomy_*, citation map> --basetemp ~/.cache/breezy-pytest/s2-<wp>` with the venv interpreter by exact path (never uv/pip). (3) Read EXIT, then `rm` the basetemp. (4) `cd <wt> && lint-imports` prints "N kept, 0 broken". (5) `ruff` on own files only; `git status` for strays. Full gate once after merge.

**Pre-steps (executor, not code)**
- **P1:** disk preflight (E4).
- **P2:** `BREEZY_LIVE=1 BREEZY_USER_AGENT=<monitored contact> <venv python> scripts/analysis/nbp_backfill.py --apply --start 2026-09-30 --end <last day> --request-budget <2×3×days>` (`--request-budget` mandatory with `--apply`, `nbp_backfill.py:553,614-625`); `--dry-run` first and record the item count; pin the post-backfill `_manifest.json` sha256. Count floor-governed availability rows (`nbp_derived_store.py:142-153`); if any exist, WP6 reports a +60 min availability stress (report-only).

### WP0 — Probe (`maker_stage0_probe.py`, read-only, ~2 h)

`probe(catalog_root, days, stations) -> ProbeReport` (frozen, `to_dict()`), pinned.
1. **Direction check (S-2).** Frozen thresholds: BUYER prints ≥ the prior YES mid, SELLER prints ≤ it; mid from the last gap-free frame before `ts_event`; undefined mids counted, never disagreement; n_defined ≥ 200 per side; agreement ≥ 0.9 fixes the mapping, ≤ 0.1 means inverted (recorded), between is S-2. Positive control: the SFO 10-0x sample.
2. **Coverage.** Global first print instant (sets the first replayable day, §3); per station-day: process-live window, gap-overlap hours.
3. **Census.** Re-assert 0 `NO_AGGRESSOR`, 0 duplicate `trade_id`, 0 opposite-side twins. Report truncated-frame share, the `VenueClockOffset` series and Δ = max |offset_ns|, ladder parity per station, listing instant per station-day (abstention if after D−1 12:00Z).
4. **Clocks.** Depth `ts_event` = venue `transactTime` (`parsing.py:777-779`); print `ts_event` = venue `tradeTime` (:971); forecast `available_at_ns` UTC-anchored.

RED first: `test_buyer_print_at_or_above_prior_mid_agrees`, `test_undefined_mid_is_counted_not_disagreeing`, `test_inconclusive_agreement_raises_stop_s2`, `test_open_gap_row_is_superseded_by_its_resolved_row`, `test_first_replayable_day_follows_first_print_instant`.

### WP1 — Inputs, pins, process schedule (`maker_stage0_inputs.py`, ~3 h)

- `load_census_days(path)`: schema-asserted; NYC filtered and counted.
- `load_trade_unit(path) -> TradeUnit`: `RESOLVED(one)` or `BRACKETED(usd_yes_notional, usd_taker_notional)`; refuses `UNRESOLVED`; `.hypotheses()` yields one or two converters `to_contracts(size, yes_price)`.
- `load_truth(csv, cross_check)`: FINAL only; a correction takes the final revision; the CSV is copied into the run dir and sha-pinned; the stale `settlement_truth.parquet` (≤ 09-28) is an overlap cross-check; any conflict raises.
- `load_model()`: path and sha from `deploy/families/pm_us_crh_fq_v1.json`, whose own sha is pinned.
- `process_schedule(days, node_log_dir) -> Mapping[date, tuple[Cut, ...]]`: base = the nominal schedule (`permit_window_for_day` + `STOP_PRIOR_UTC`, imported) plus UTC-midnight GTD cuts, overlaid with mid-day relaunch instants read from the node log files where they exist for that trading day (a relaunch is a cancel-on-stop and a new episode). Full-day node outages are **not** simulated (they make a station-day non-bid-bearing, a sample-clock fact, reported as a count). Written to `process_schedule.json` and pinned. Measured boot-to-permit latency is reported only.
- `pin_inputs(...)` hashes: census, unit, truth copy, artefact, deploy manifest, `uv.lock`, spec file, git commit, post-P2 NBP `_manifest.json` and the consumed `(cycle, raw_sha256)` set, the process schedule, and a catalog slice manifest (path, size, mtime, sha256 of every consumed parquet, hashed while read).

RED first: `test_unresolved_trade_unit_is_refused`, `test_bracketed_unit_yields_two_hypotheses`, `test_truth_conflict_between_sources_raises`, `test_artefact_sha_mismatch_refuses`, `test_nominal_schedule_is_1650z_to_0250z_with_midnight_cut`, `test_logged_relaunch_adds_a_cut`, `test_pins_cover_every_mutable_input`.

### WP2 — p_NO loader (`maker_stage0_pno.py`, ~3 h)

- `ForecastBook.from_store(nbp_root, stations, days)` pushes each cycle's **first** MAX column only, into the state for `(icao, max_column_lst_climate_day(row))`, with its own `available_at_ns`.
- `vector_at(icao, d, now_ns)` returns `None` (abstain `forecast_day_mismatch`) unless `climate_day == d`, the shifted vintage is strictly `< now_ns`, and age = `now − available_at` ≤ STALE_H = 8 h (else `forecast_stale`).
- `ladder_p_yes(vector, ladder, calibration, latitude) -> Mapping[str, PYes(point, lower, upper)]` via `rung_probability_interval` over `resolve(...).draws`; complement fallback when the ladder is not a complete partition; `p_no = 1 − point`; modal rung = argmax `point`. Unknown NBM era → `None`, counted, never pooled. Spec §3: the **point** estimate defines P_MIN, b_max, the strata and §6.9; bounds are recorded only.

**Verify-first STOP (S-6):** print `max_column_lst_climate_day` for one real 01Z/13Z/19Z cycle per station; assert it against `climate_day_for_txn` and one CLI FINAL day; print the vintage age at 16:50Z D−1, 00:00Z and 02:50Z D; it must match §3.1 within ±30 min.

RED first: `test_inclusive_band_uses_hi_plus_half_and_lo_minus_half`, `test_only_first_max_column_is_pushed`, `test_13z_day_d_cycle_never_feeds_day_d`, `test_vector_not_yet_available_is_invisible`, `test_vector_older_than_8h_is_stale`, `test_unknown_era_yields_none`.

### WP3 — §3 rule (`maker_stage0_rule.py`, pure, ~2 h)

- Constants pinned to spec v0.3 §3 by `test_constants_match_spec`: `P_MIN = 0.94`, `B_CAP = 0.80`, `E_MIN = 0.10`, `B_FLOOR = 0.70`, `STALE_H = 8`, `MAX_RUNGS = 2`, `CANCEL_LST = 09:00`; the pinned spec sha catches drift.
- `bid_price(p_no, best_no_bid, no_ask, theta)`: `b_max` = the largest 1 ¢ `b ≤ min(B_CAP, p_no − E_MIN − θ·b·(1−b))`; `None` if `b_max < B_FLOOR`; else `bid = min(b_max, best_no_bid + 0.01, no_ask − 0.01)` (never cross); `None` if `bid < B_FLOOR`. `best_no_bid = 1 − best YES ask`, size-0 pad ignored; `no_ask = 1 − best YES bid`. Empty NO bid side: `min(b_max, no_ask − 0.01)` (Spec input 3). Empty YES bid side: no `no_ask` clamp. In replay `best_no_bid` never contains our own order (the tape cannot), which is the intended live semantics (Spec input 4).
- `select_rungs(p_yes_by_rung, bids)`: at most `MAX_RUNGS` rungs, the lowest p_YES passing P_MIN, never the modal rung or adjacent to it, each with a bid ≥ B_FLOOR. `MAX_RUNGS1` subset = the first selected rung (report-only fallback).
- Cancels: `hard_cancel_ns` = D 09:00 LST integer ns; `gtd_expire_ns = min(hard_cancel_ns, permit_expiry_ns, next UTC midnight)`; `obs_cancel(upper_f, lower_edge_f)` when `upper_f ≥ A − 2` with integer-°C rows widened by 1.8 °F (pure and tested; cannot bind in Stage 0, §3.1); abstain if listed after D−1 12:00Z.

RED first: `test_bid_is_best_plus_one_cent_capped_at_b_max`, `test_bid_never_crosses_no_ask`, `test_bid_below_floor_after_clamp_cancels`, `test_b_max_below_floor_cancels`, `test_two_rung_bound_and_modal_adjacency`, `test_max_rungs_1_subset_is_lowest_p_yes`, `test_gtd_expire_is_min_of_lst_permit_and_utc_midnight`, `test_constants_match_spec`.

### WP4 — Fill simulator (`maker_stage0_fill.py`, pure, ~4 h)

**Events.** `Event(ts_ns, kind, seq, payload)`, frozen, totally ordered by `(ts_ns, kind.priority, seq)`; `seq` = source row order. Priority at equal timestamps: 0 `GAP_START`; 1 `CANCEL` (process cut, GTD expiry, stale, p_min, b_floor — cancels precede credits); 2 `PRINT` (a same-ts frame already reflects the trade); 3 `DEPTH`; 4 `GAP_END`; 5 `FORECAST_RELEASE`; 6 `DECIDE`.

**Clock.** Venue clock throughout. Forecast releases shift by +Δ (WP0); time-triggered cancels and process cuts shift by −Δ; staleness counts from the shifted release. Every cross-clock comparison errs leak-safe.

**Decision instants (spec §3).** Each forecast release, each depth frame, and each clock alert (process cut, GTD expiry). Same price → the episode continues; a new price → cancel-replace (`REPLACED`, new episode, queue reset).

**Episode.** One rest from `t0` to its end. End reasons: `FILLED`, `REPLACED`, `CANCEL_{PMIN,BFLOOR,STALE,DAYMISMATCH,HARD}`, `CANCEL_PROCESS` (stop, relaunch, permit expiry), `GTD_EXPIRY` (incl. 00:00Z). **Gaps are subtracted, not censored:** time inside a `QuoteTapeGap` is removed from the episode's live hours, no print inside a gap is credited, the episode continues, and the first fresh frame after `GAP_END` is a decision instant.

**Marketability guard at t0** (episode refused, counted, not placed; the next decision instant retries): the frame is stale (a gap covers `[frame_ts, t0]` or the frame predates the current recorder instance) or truncated (a same-`ts_event` `DepthTruncation` row); or the bid is marketable (`b ≥ no_ask`).

**Fill rule (spec §6.1, NO-price space).** A YES print at `p` has NO price `q = 1 − p`; only **YES-BUYER** prints count (direction per WP0); `NO_AGGRESSOR` is never credited; nothing is credited from an implied price. At `t0`: `A_gt` = displayed NO size at prices > b, `A_eq` = at exactly b (Σ YES-ask size at < / = `1 − b`); `Q0 = A_gt + A_eq + 1` (our own unit last). Remaining `R = Q0`, better-priced remainder `G = A_gt`. Per credited print of `v` contracts (`TradeUnit`), `t0 < ts`, outside gaps:
- `q > b`: it consumed better bids: `d = min(v, G)`; `G −= d`; `R −= d`.
- `q ≤ b`: it consumes the remaining queue: `R −= v`; `G = max(0, G − v)`.
- **FILLED** at the first print that drives `R ≤ 0`, i.e. cumulative consumption reaches Q0 including our own unit (Spec input 5 on "exceeds").
- **Stress** (gated in §1.1): the same pass with `Q0' = 2·(A_gt + A_eq + 1)`, `G' = 2·A_gt`.
After a fill the pair is held to settlement; no further bids on it.

**Episode record:** `station, climate_day, rung_id, t0_ns, end_ns, end_reason, bid, a_gt, a_eq, refused_reason, filled_ns_{base,stress}, gap_ns_subtracted, p_yes_point_live, p_yes_upper_live, cycle_runtime_ns, raw_sha256, nbm_era, available_at_ns, depth_ts_used_ns, unit_hypothesis`. "Live" = the vector in force at the fill instant; for an unfilled episode, the last vector it rested under.

**Leakage asserts** raise: `available_at_ns + Δ < t0_ns ≤ filled_ns`; `depth_ts_used_ns ≤ t0_ns`; every credited print has `t0 < ts < end`. Reads are scoped by instrument and absolute ns, never by hour-of-day.

RED first: `test_equal_timestamp_cancel_precedes_print`, `test_print_at_t0_is_never_credited`, `test_yes_seller_print_never_counts`, `test_better_priced_buyer_print_reduces_q0`, `test_print_at_or_below_b_consumes_remaining_q0`, `test_better_priced_reduction_capped_at_size_strictly_better`, `test_fill_when_own_unit_consumed`, `test_stress_needs_twice_size_ahead_plus_one`, `test_replace_resets_queue`, `test_process_cut_starts_new_episode_and_resets_queue`, `test_utc_midnight_gtd_cut_starts_new_episode`, `test_gap_interval_is_subtracted_episode_continues`, `test_stale_or_truncated_frame_refuses_episode`, `test_clock_shift_delays_forecast_and_advances_cancels`, `test_simulator_module_does_not_import_truth`.

### WP5 — Statistics and verdict (`maker_stage0_stats.py`, ~3 h)

**Coverage and denominator (spec §6.0).** A station-day is **covered** when depth frames for its instruments exist inside its process-live window (recorder coverage from depth + gap records only; print presence never enters). It is **bid-bearing** when the rule placed ≥ 1 episode. Every covered bid-bearing station-day is in the denominator, including print-less windows (unfilled, zero credited volume) and heavily gapped ones (gap share reported beside the rate). Position unit: filled pairs / bid-bearing pairs on those days. Station-day unit: days with ≥ 1 filled pair / covered bid-bearing days. The verdict uses the stricter (lower) rate.

**§6.9 (spec v0.3 as amended: exact, POOLED).** The verdict is computed on the pooled set of filled episodes (all strata and stations together). Strata by `p_NO = 1 − p_yes_point_live` (`[0.94,0.96)`, `[0.96,0.98)`, `[0.98,1]`) get the same two tests reported **descriptively only**; a stratum result never sets the state. Filled rows: the filled episode of each filled pair. Unfilled rows: the last episode of each never-filled pair (scored counterfactually). Losses = YES settlements on CLI FINAL; unresolved past D+14 = LOSS.
- **Minimum (pooled):** the screen is computed only if `E = Σ_{all filled} p_i ≥ 10`; else `UNSCREENED` (never PASS, never FAIL).
- **Test A (model):** `P(L ≥ l_obs)` under independent `Bernoulli(min(1, 1.5·p_i))` (Poisson-binomial DP); `< 0.05` → FAIL.
- **Test B (unfilled):** conditional exact rate-ratio test with the same 1.5 margin: given `L = L_f + L_u`, `L_f ~ Bin(L, π0)`, `π0 = 1.5·n_f / (1.5·n_f + n_u)` (Poisson approximation, valid at p ≤ 0.06); `binomtest(..., alternative="greater").pvalue < 0.05` → FAIL. `L = 0` cannot FAIL.
- **State:** `UNSCREENED` if `E < 10`; else `FAIL` if pooled Test A or pooled Test B fails (two tests, no correction: a harm screen); else `PASS`. Test B pools by Σ over all rows (`n_f`, `n_u`, `L_f`, `L_u`); the stratum-mix difference between filled and unfilled is reported beside it.
- **Power line (analytic):** for k ∈ {1.5, 2, 3}, P(Test A FAIL) under `Bernoulli(min(1, k·p_i))` at the exact critical count, plus pooled fills needed for `E ≥ 10`. No simulation.
- Descriptive sidecars (never decide): climate-date cluster-bootstrap interval of the filled-minus-unfilled loss difference, cluster counts.

**Tail reliability (report-only, optional if effort binds).** `tail_reliability(nbp, truth, days, stations, parity)` on 2026-07-01..09-17: every inclusive 2 °F band on the station's parity, for each of the 3 day-D vectors, with p_YES < 0.06; bins `[0,.02)`, `[.02,.04)`, `[.04,.06)` with n, dates, mean p, observed frequency, Clopper-Pearson CI; a pooled exact test sets `TAIL-MISCALIBRATED`.

`verdict(rates_by_unit_hypothesis, s69) -> Verdict` implements §1.1 exactly; `--scored` reproduces it.

RED first: `test_verdict_table_rows_v1_to_v5`, `test_stress_below_floor_is_no_go`, `test_bracketed_unit_takes_more_severe_verdict`, `test_denominator_is_covered_bid_bearing_days_not_print_days`, `test_printless_window_counts_as_unfilled`, `test_stricter_unit_decides`, `test_pooled_below_10_expected_losses_is_unscreened`, `test_stratum_results_never_set_the_state`, `test_unscreened_never_maps_to_not_killed`, `test_poisson_binomial_tail_matches_brute_force`, `test_rate_ratio_test_uses_1_5_margin`, `test_pooled_fail_is_fail`, `test_unresolved_past_d14_is_loss`, `test_power_line_is_monotone_in_k`, `test_point_estimate_and_lower_bound_are_separate`.

### WP6 — Driver, report, run (`maker_stage0_replay.py`, ~3 h + run)

**CLI:** `--census-days --trade-unit --catalog-root ~/.local/share/breezy/catalog/quote_tape/polymarket_us --nbp-root ~/.local/share/breezy/derived/nbp --truth PATH --node-log-dir PATH --out-dir ~/.local/share/breezy/derived/maker_stage0/<run_id> [--stations --days] [--tail-only]`.

**Flow:** (1) per station-day and unit hypothesis: build events (incl. process cuts), simulate base and stress, assert no episode extends past local midnight starting D, append to `episodes.jsonl`, write one `progress.jsonl` line; (2) only after every station-day: load truth and score in a separate function; (3) render the report, copy the sidecar.

RED first: `test_driver_scores_only_after_simulation_completes`, `test_episode_past_local_midnight_of_d_raises`, `test_report_has_verdict_pins_banner_and_holdout_line`, `test_stats_rerun_on_scored_csv_reproduces_tables`.

**Run plan** (avoid the 02:05Z nightly and the 10–24 GB study windows; one heavy job):
1. P1, then P2.
2. **Benchmark** on 8 station-days (2 per station, across 2 weeks): `systemd-run --user --unit maker-s0-bench -p MemoryMax=4G -p RuntimeMaxSec=1800 -p LimitNOFILE=524288 <venv python> -m scripts.analysis.maker_stage0_replay …`; read `memory.peak` and the slowest station-day.
3. **Full run** `maker-s0-full`: `RuntimeMaxSec` = 3× the extrapolation, capped at 6 h (S-5); `MemoryMax` = 2× the peak, capped at 4G; arm a Monitor on the `progress.jsonl` mtime in the launch turn, stall threshold = 3× the slowest benchmark station-day, minimum 10 min; wait until `ActiveState ∉ {active, activating}`.
4. `--tail-only` afterwards, as its own unit.
5. Read EXIT. Copy outputs to `docs/evidence/maker/`, re-check disk, commit by explicit paths, push per milestone policy.

## 6. Data and tooling dependencies

| Item | Path | State (2026-10-12) |
|---|---|---|
| Depth10 + prints (YES leg) | `…/quote_tape/polymarket_us/data/{order_book_depths,trade_tick}/` | present; prints from 09-17 |
| Gaps / truncation / offset | `…/data/custom_quote_tape_gap`, `custom_depth_truncation`, `custom_venue_clock_offset` | present |
| Fee θ | per-market `feeCoefficient` in the instrument defs | **UNVERIFIED** → 0.0695 |
| NBP store | `~/.local/share/breezy/derived/nbp/` + `_manifest.json` | needs P2 |
| Artefact | `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`; fit splits ≤ 2026-06-30 (`nbp_calibration.py:273-278`) | present |
| Truth | `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` (to 10-11) → copy and pin | present |
| Truth cross-check | `…/settlement-truth/settlement_truth.parquet` (≤ 09-28) | overlap only |
| Node logs (relaunch cuts) | node log files (Popen stdout), not journald | **UNVERIFIED** coverage → nominal schedule where absent |
| S1 outputs | census list, unit | **not delivered** (E1) |
| Disk | `$HOME` volume | **4.2 GB free, below the 10 GB floor** (E4) |

UNVERIFIED: `ParquetDataCatalog.query` kwargs in 1.231 (WP0 checks one instrument); whether a live actor sees a 07Z NBP cycle the backfill lacks (if so, the replay window is pessimistic).

## 7. Risks and guards

| Risk | Invariant / lesson | Guard |
|---|---|---|
| Look-ahead | "an implausible result is a leak" | strict `available_at + Δ < t0`; instrument + ns scoping; truth unreachable from the simulator (test); score only after simulation |
| Fill rate biased up by missing churn | spec §3 window paragraph | process schedule + UTC-midnight GTD cuts (tests); cut share reported |
| Fill rate biased by queue rule | spec §6.1 | v0.3 price-priority rule with Q₀ reduction as base; 2× stress gated |
| Denominator selection | spec §6.0 | coverage from depth/gap records only; print-less windows count as unfilled (test) |
| Gap or stale frame invents fills | correctness | gap subtraction; marketability guard; refusals counted |
| Equal-ts or clock-order leak | §7.6 | total order + Δ shift (tests) |
| Underpowered screen read as clean | "an underpowered verdict describes the sample" | 10-expected-loss minimum → UNSCREENED; power line; never "GO" |
| Frozen NBP holdout touched | `RULING_holdout_freeze_and_forward_window_2026-10-03` cl. 1 freezes [07-01, 10-02) | spec §6.0: read under cl. 3 as descriptive evidence; never `open_holdout`; disclosure line |
| Disk exhaustion | collectors refuse < 10 GB | E4 before every heavy step; basetemp under `~/.cache`; `rm` after EXIT |
| Shared venv or tree damage | no uv/pip from a worktree; no stash | exact interpreter; ruff on own files; commit by explicit path |
| Memory blow-up or stall | one heavy job; stall watch | MemoryMax, RuntimeMaxSec, progress Monitor |
| Egress | NO-SEND | replay makes no network calls; P2 is the existing allowlisted tool |

**Holdout line.** Tail days (07-01..09-17) and replay days through 10-01 fall inside the frozen holdout; spec v0.3 §6.0 admits them under ruling cl. 3 as descriptive evidence only, consistent with Stage 0 being exploratory. S2 fits nothing and prints the holdout-touch line.

S2 imports no exec, runtime-node or deploy code (the supervisor constants and `permit_window_for_day` are pure constants/functions), so it cannot violate `allow_short`, the caps or enablement. A test asserts no import from `breezy.adapters.polymarket_us.exec`.

## 8. Effort and artifact

| WP0 | WP1 | WP2 | WP3 | WP4 | WP5 | WP6 | Review fixes + gates | Total |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 3 | 3 | 2 | 4 | 3 | 3 | 2 | **≈ 22 agent-hours** |

Run wall time about 1–3 h after P2 and the benchmark. Artifact: `docs/evidence/maker/STAGE0_REPLAY_<date>.md` plus `stage0_<date>/` (files < 5 MB; larger gzipped and pinned).

## 9. Open questions for peer review (max 5)

1. **Process schedule source.** Is "nominal schedule + logged mid-day relaunches, full-day outages not simulated" the right base, or should observed full-day outages also enter (they remove days, not fills)?
2. **Test B form.** Is the conditional exact rate-ratio test with margin 1.5 the right reading of "exceeds the unfilled loss rate by the same test"?
3. **Coverage threshold.** Is "≥ 1 depth frame in the process-live window" an adequate covered definition, given that heavily gapped days stay in the denominator (conservative)?

## Spec inputs (gaps found while conforming; not fixed here)

1. §6.0 table has no row for base ≥ 0.10 and stressed < 0.10; this plan maps it to `NO-GO (stress)` (V3), the stricter reading.
2. §6.0 sets no minimum Stage 0 sample; this plan only stops on zero covered bid-bearing station-days (S-4).
3. §3 is silent on the empty NO-bid-side placement price; this plan uses `min(b_max, no_ask − 0.01)`.
4. §3 `best_bid + 0.01` must exclude our own resting order live, or the bid chases itself up to b_max (an S4/S5 concern; replay is unaffected).
5. §6.1 "FILLED when cumulative volume exceeds Q₀" with Q₀ including our own unit: read as "reaches Q₀" (strict `>` would require a phantom unit behind us).
6. §3 window paragraph: the 10 h permit (16:50Z → 02:50Z), not STALE_H, ends bidding; all bids rest before climate day D starts locally, so the observation cancel cannot bind before the shadow run changes the process schedule.

## r3 conformance table

| Verdict item (`reviews/S2-r2-final.md`) / brief | Change | Plan § |
|---|---|---|
| R1 [MAJOR] base fill rule | v0.3 price-priority rule with Q₀ reduction by better-priced BUYER prints is the base; stress 2·(Q₀); old rule, price-priority variant and `RULE-SENSITIVE` removed; RED tests added | WP4, §1.1 |
| R2 [MAJOR] STALE_H | 8 h pinned in `test_constants_match_spec`; §3.1 table recomputed; r2 Q5 and spec input 5 dropped | §3.1, WP2, WP3 |
| R3 [MAJOR] process schedule | `process_schedule` (nominal permit window, STOP_PRIOR, UTC-midnight GTD cut, logged relaunches), `CANCEL_PROCESS`/`GTD_EXPIRY`, cut-share report, tests | §3.1, WP1, WP4, §1 item 2 |
| R4 [MAJOR] verdict and §6.9 | exact tests on the POOLED filled set decide (coordinator amendment to v0.3 §6.9; strata descriptive); pooled 10-expected-loss minimum else UNSCREENED; FAIL only when screened; bootstrap/power descriptive; V3 stress row recorded as Spec input 1 | §1.1, WP5 |
| R5 [MAJOR] denominator | all covered bid-bearing station-days; coverage from depth/gap records; print-less windows unfilled; gaps subtracted not censored; start day 09-18 per spec, measured | §1 item 2, §3, WP4, WP5 |
| R6 [MINOR] holdout | Q1 and S-6 (holdout) closed by v0.3 §6.0; disclosure line kept | §7 |
| R7 [MINOR] cross-refs | goal items referenced as "§1 item n" | §1 |
| R8 [MINOR] spec inputs | list pruned to gaps v0.3 does not cover | Spec inputs |
| R9 [MINOR] simplicity | price-priority variant and power simulations dropped (analytic power); tail table optional; 23 → 22 h | WP5, §8 |
| Brief: v0.3 §3 | B_FLOOR 0.70, never-cross clamp, GTD expiry, MAX_RUNGS 2 with MAX_RUNGS 1 report-only subset, day-match abstention, listing-time abstention | WP2, WP3 |
| Brief: §6.0 unit bracket | run under both USD hypotheses, more severe verdict governs | §1.1, WP1 |
| Brief: §6.5 | unresolved past D+14 = LOSS; void = refund − fee | §1 item 7, WP5 |
| Brief: §6.2/§6.3/§6.6/§6.7/§7.3 | not Stage 0 objects (shadow evaluation, S5); Stage 0 gates only the §6.0 queue stress and reports no baselines; nothing here contradicts them | — |
| Dead text removed | RULE-SENSITIVE, EXACT-DISAGREES, NOT_COMPUTABLE row, 6 h tables, censored-episode rule, r1 disposition table (see r2) | throughout |

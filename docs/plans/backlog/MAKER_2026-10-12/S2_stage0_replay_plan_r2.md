# S2 — Stage 0 exploratory maker replay (plan)

| Field | Value |
|---|---|
| ID / Title | S2 — Stage 0 exploratory maker replay: fill simulator + adverse-selection screen |
| Revision / Date / Status | r2 (supersedes r1; dispositions at the end) / 2026-10-12 / **READY-FOR-REVIEW** |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` (working text, header v0.3): §3, §6.0, §6.1, §6.7 (2× only), §6.9. The run pins its sha256 |
| Emits | `docs/evidence/maker/STAGE0_REPLAY_<YYYY-MM-DD>.md` + sidecar dir `docs/evidence/maker/stage0_<YYYY-MM-DD>/` |

**Hard invariants** (binding on every WP and brief):
- Nautilus Trader is immutable (no patch, fork, bypass or reimplementation); `allow_short` stays `False`.
- Never weaken or delete a safety, settlement, contract or NO-SEND egress-firewall test. Exact-set barriers are WIDENED by one reviewed row, never relaxed (L-12).
- Never assign a value to an operator-reserved control (max daily budget, max per position); never touch live enablement or `BREEZY_ORDERS_ENABLED`; never edit a frozen `PREREG.json` or move a pre-registered date.
- **Stage 0 is EXPLORATORY and never promotion evidence.** The FQ-v2 NO-TRADE ruling stays in force; this is its T2 route.
- S2 touches only `scripts/analysis/` and `tests/unit/`: no `src/`, exec, strategy or `deploy/`. It fits nothing and never calls `open_holdout` (`src/breezy/analysis/nbp_calibration.py:353`).

## 1. Goal state (acceptance test)

Done when the evidence Markdown and its sidecar are committed and carry:
1. **Verdict** from the frozen table §1.1. Never "GO". It carries the exploratory banner, every failing condition, and reason codes.
2. **Fill rates** at the pair unit (station-day × rung = the position unit) and the station-day unit, each for the base rule, the 2× stress and the price-priority variant (WP4). Also: the episode-level rate (descriptive), the at-touch vs behind-touch regime split, the `q_censored` share, and implied days to 200 positions.
3. **Bid-live hours** per station-day and per station; the share of station-days with zero live hours; exposure-hours removed for gaps and for staleness, counted separately.
4. Realised bid histogram (1 ¢), on fills and on all episodes.
5. Win rate of fills next to the fills' mean model p_NO, with a climate-date cluster-bootstrap 95% CI, the cluster count and a Clopper-Pearson sidecar. Point estimate and lower bound are separate numbers.
6. **§6.9**: T1 and stratum-standardised T2. The pooled result decides; per-stratum results are descriptive. Each carries the bootstrap p, the dropped-degenerate-draw count, the exact sidecar p, a power line at k = 1.5/2/3, and expected vs observed YES counts.
7. Net expectancy per fill, `w − (b + θ·b·(1−b))` at θ = 0.0695, with a cluster CI. Descriptive only, a stress rather than an estimate.
8. A **tail-reliability table** on climate days 2026-07-01..09-18 (forecast + truth only, no tape; WP5) and the holdout-touch disclosure line (§7).
9. **Pins** (WP1). The sidecar holds: `episodes.jsonl` (ids + forecast provenance), `scored_episodes.csv`, `tail_reliability.csv`, `pins.json`; `run_manifest.json`: argv, run_id, git commit, Python/Nautilus versions, seed 20260919 × 2000 iterations (`scoring_core.py:22,25`), `memory.peak`, wall time, free disk at start and end.

   `maker_stage0_stats --scored <csv>` recomputes every table.

### 1.1 Frozen verdict table

The first matching row sets the label; every failing row is printed.

| # | Condition | Verdict |
|---|---|---|
| V1 | < 10 climate dates with ≥1 pair, or < 20 pairs | `NOT_COMPUTABLE` |
| V2 | base pair fill rate < 0.10 | `NO-GO (fill)`; annotated `RULE-SENSITIVE` if price-priority rate ≥ 0.10 |
| V3 | §6.9 FAIL: pooled T1 or T2 bootstrap one-sided p < 0.05 (the spec's rule) | `NO-GO (adverse selection)` |
| V4 | 2×-stressed pair fill rate < 0.10 | `NO-GO (stress)` |
| V5 | §6.9 INCONCLUSIVE: not FAIL, and any of P(FAIL \| k=2) < 0.80, filled episodes < 20, or defined-draw share < 0.90 | `NOT-KILLED-UNSCREENED` |
| V6 | otherwise | `NOT-KILLED` |

`NOT-KILLED*` licenses only S4/S5 shadow work under the §7.9 holdout gate. It is not evidence of edge.

Annotations never change the label: `TAIL-MISCALIBRATED` (the tail table fails a T1-style exact test at 0.05) and `EXACT-DISAGREES` (exact sidecar and bootstrap fall on opposite sides of 0.05).

## 2. Entry criteria and STOP conditions

**Entry**
- **E1.** S1 has delivered the censused-day list and a resolved `TRADE_QUANTITY_UNIT`, both passed by path (`--census-days`, `--trade-unit`).
- **E2.** The NBP store covers every replayed day (pre-step P2; today it ends at `nbp_20260929_19z`).
- **E3.** One heavy job at a time on the host.
- **E4.** `df -B1 --output=avail $HOME` ≥ 10 GiB before P2, before every gate, and before the benchmark and the run. **Today it is 4.7 GB (100 % used), so S2 is blocked.**; Freeing disk is the coordinator's job. S2 deletes only what it created. Also check whether collectors are already refusing.

**STOP**
- **S-1 (programme).** On `NO-GO`, nothing is built and S4/S5 are not started. A `RULE-SENSITIVE` NO-GO is still NO-GO; the rule question goes to Spec input 2.
- **S-2.** The WP0 direction check is inconclusive. Return to the spec.
- **S-3.** The S1 unit is still `UNRESOLVED` (spec §9.3).
- **S-4.** V1 holds.
- **S-5.** The benchmark predicts > 6 h or > 4 GiB RSS. Fix the reader first.
- **S-6.** The coordinator rules against reading days inside the frozen NBP holdout (§7, Q1). The tail table then uses the fallback window and the replay drops climate days before 2026-10-02. S-4 is then likely until about 10-21.

## 3. Simplest direct path

One read-only script replays every eligible (station, climate day). For each one it:
1. reads the YES-leg Depth10, prints, gaps and truncation rows;
2. takes calibrated p_NO from that day's first-MAX-column NBP vector;
3. applies §3 at each decision instant;
4. credits fills by the §6.1 trade-through rule, stated once in NO-price space;
5. scores against CLI FINAL truth with the repo's one cluster bootstrap.

The verdict table is frozen here, before any number exists. There is no BacktestEngine, Strategy or persistence, because the decision is binary. The only added rigour is where reviewers showed the verdict can flip: the queue-rule bracket, gaps, clock and tie order, and power.

**Measured scope (not the spec's 08-30).** Print dirs number 11 on 2026-09-17, 29 on 09-18, and a full 30/day from 09-19. Eligibility uses measured print coverage of each live window (WP0). Expected range: climate days 09-19 → min(last censused, last FINAL = 10-11), about 23 dates × 4 stations, ≤ 184 pairs.

**Bid-live window (binding on the sample).**
- `ForecastQuantileState` holds one climate day per cycle (`forecast_state.py:245-279`).
- The artefact is fit on the first-column lead, and v0.3 requires `vector.climate_day == S.day`.
- So day D's only vectors are the **13Z D−1, 19Z D−1 and 01Z D** cycles (`nbp_backfill.py:127`, `CYCLES = (13, 19, 1)`). The 13Z D cycle targets D+1, because the first MAX column is the cycle's LST date + 1.
- Median `available_at − cycle` over 2026-08/09 (60 cycles each): 64 min for 01Z and 13Z, 77 min for 19Z. Maxima: 804 / 137 / 193 min.

Under the 6 h staleness rule:

| Station | Live window (UTC, p50 lags) | Live h | Window ends (LST, D) | Dead h before the 09:00 LST cancel |
|---|---|---:|---|---:|
| LAX, SFO | D−1 14:04→20:04, 20:17→D 08:04 | ≈ 17.8 | 00:04 | ≈ 8.9 |
| MDW | same | ≈ 17.8 | 02:04 | ≈ 6.9 |
| MIA | same | ≈ 17.8 | 03:04 | ≈ 5.9 |

Consequences: the 09:00 LST hard cancel never binds; a 13-min hole around 20:04Z forces a daily cancel-replace (queue reset); listings precede 14:04Z D−1 (e.g. SFO 10-05 depth starts 10-04 10:00Z). WP6 reports the measured hours.

## 4. Nautilus null-hypothesis check

| Need | Native capability checked | Verdict |
|---|---|---|
| Read depth, prints, gaps, truncation, offset | `ParquetDataCatalog.query` (`persistence/catalog/base.py:158,176,221`; `parquet.py:1648`). Registered Breezy records: `QuoteTapeGap` (`tape_records.py:55`; `covers` :162; `resolved_gaps_by_seq` :536), `DepthTruncation` (:450; same `ts_event` as its frame), `VenueClockOffset` (:227-244) | **Reuse**, scoped per instrument and absolute ns |
| Maker queue fills | `BacktestVenueConfig.queue_position` / `trade_execution` (`backtest/config.py:114-124`) | **Not used.** Decisive reason: the tape holds only the YES instrument (`parsing.py:936-938`; 0 NO-leg dirs), so a native resting NO bid is **SELL YES at 1−b with no YES held, i.e. a short**. `allow_short=False` (`strategy/ladder_ev/config.py:171`), and the kernel guard refuses naked shorts (`runtime/backtest_order_guard.py:118,284`). A synthetic NO instrument would need the same inversion plus a full Strategy (S5's path). The 2× stress is also not a config knob. r1's NO_AGGRESSOR argument is dropped (0 such prints) |
| Point-in-time forecast | `ForecastQuantileState.push/value_at` (`forecast_state.py:245,310`; `climate_day` :224) | **Reuse**: one state per (ICAO, D), first-column cycles only |
| Rung probability | `load_live_calibration` (`calibration_artefact.py:236`), `resolve` (:134), `rung_probability_interval` (`quantile_density.py:393`; mean over draws :414-420; `F(hi+.5)−F(lo−.5)`) | **Reuse** |
| Rung facts; column day | `bucket_facts_from_instrument_id` (`instrument_facts.py:72`); `max_column_lst_climate_day` (`nbm_quantile_parse.py:187`) | **Reuse** |
| Bootstrap; obs running max; report rows | `bootstrap_cluster_draws` / `percentile_interval` / `SupportsClusterKey` (`scoring_core.py:216,246,199`); `RunningExtremeAccumulator` (`running_extreme.py:217,225,266`); `GateResult` (`resting_bid_report.py:37`) | **Reuse** |

Genuinely new (spec §9.5/§9.6): (1) the p_NO loader; (2) the maker fill simulator; (3) the §6.9 test with its exact sidecar and power line.

FQ `evaluate` is barred by the `NotDPlus1` class (`decision.py:138`) and the F6 veto. Neither applies offline, and Stage 0 authorises nothing live.

## 5. Work packages

**Conventions:** code in `scripts/analysis/maker_stage0_*.py` (absolute imports as in `fq_loss_taxonomy_reconstruct.py:27`); tests in `tests/unit/test_maker_stage0_*.py`; modules < 400 lines, functions < 50; pure modules do no I/O.

**Focused gate (every WP)**
1. E4 preflight.
2. `PYTHONPATH=<wt>/src scripts/ci/run_tests_no_egress.sh tests/unit/test_maker_stage0_*.py <firewall guards, import gates, test_autonomy_*, citation map> --basetemp ~/.cache/breezy-pytest/s2-<wp>`, with the venv interpreter by exact path (never uv/pip).
3. Read EXIT, then `rm` the basetemp.
4. `cd <wt> && lint-imports`; it must print "N kept, 0 broken".
5. `ruff` on own files only, then `git status` for strays.

Run the full gate once after merge.

**Pre-steps (executor, not code)**
- **P1:** disk preflight.
- **P2:** `BREEZY_LIVE=1 BREEZY_USER_AGENT=<monitored contact> <venv python> scripts/analysis/nbp_backfill.py --apply --start 2026-09-30 --end <last day> --request-budget <2×3×days>`. `--request-budget` is mandatory with `--apply` (`nbp_backfill.py:553,614-625`). Run `--dry-run` first and record the item count. Then pin the post-backfill `_manifest.json` sha256. Count floor-governed availability rows (`nbp_derived_store.py:142-153`). If any exist, WP6 reports a +60 min stress for them.

### WP0 — Probe (`maker_stage0_probe.py`, read-only, ~3 h)

`probe(catalog_root, days, stations) -> ProbeReport` (frozen, `to_dict()`), written to the derived dir and pinned.

1. **Direction check (S-2).** Thresholds are frozen now. BUYER prints should be ≥ the prior YES mid, and SELLER prints ≤ it. The mid comes from the last frame before `ts_event` with no gap in between. An undefined mid is counted, never treated as disagreement. Require n_defined ≥ 200 per side. Agreement ≥ 0.9 on both sides fixes the mapping. Agreement ≤ 0.1 means the mapping is inverted (recorded). Anything in between is S-2. Positive control: the SFO 10-0x sample.
2. **Coverage.** First print ts per station and overall. Per station-day: live window, gap-overlap hours, and whether prints cover the window.
3. **Census.**; Re-assert: 0 `NO_AGGRESSOR`, 0 duplicate `trade_id`, 0 opposite-side twins. Report: truncated-frame share; the `VenueClockOffset` series and Δ = max |offset_ns|; ladder parity per station; regime share (`b <` best NO bid). Name the obs source: the obs store, or the IEM cache of `current_rung_hold_resting_bid_study.py:222-262`.
4. **Clocks.**; Depth `ts_event` is the venue `transactTime` (`parsing.py:777-779`). Print `ts_event` is the venue `tradeTime` (:971). Forecast `available_at_ns` is UTC-anchored. Obs `received_at_ns` is the host clock.

RED first: `test_buyer_print_at_or_above_prior_mid_agrees`, `test_undefined_mid_is_counted_not_disagreeing`, `test_inconclusive_agreement_raises_stop_s2`, `test_open_gap_row_is_superseded_by_its_resolved_row`.

### WP1 — Inputs and pins (`maker_stage0_inputs.py`, ~2 h)

- `load_census_days(path)`: schema-asserted; NYC filtered and counted.
- `load_trade_unit(path) -> TradeUnit`: refuses `UNRESOLVED`; provides `.to_contracts(size, yes_price)`.
- `load_truth(csv, cross_check)`: FINAL only; a correction takes the final revision. The CSV is **copied into the run dir and sha-pinned**. The stale `settlement_truth.parquet` (≤ 09-28) is an overlap cross-check only; any conflict raises.
- `load_model()`: path and sha from `deploy/families/pm_us_crh_fq_v1.json`, whose own sha is pinned.
- `pin_inputs(...)` hashes: census, unit, truth copy, artefact, deploy manifest, `uv.lock`, spec file, git commit; the post-P2 NBP `_manifest.json` and the consumed `(cycle, raw_sha256)` set; a **catalog slice manifest**: every consumed parquet's path, size, mtime and sha256, hashed while it is read, because the recorder still appends.

RED first: `test_unresolved_trade_unit_is_refused`, `test_truth_conflict_between_sources_raises`, `test_artefact_sha_mismatch_refuses`, `test_pins_cover_every_mutable_input`.

### WP2 — p_NO loader (`maker_stage0_pno.py`, ~3 h)

- `ForecastBook.from_store(nbp_root, stations, days)` pushes each cycle's **first** MAX column only, into the state for `(icao, max_column_lst_climate_day(row))`, using its own `available_at_ns`.
- `vector_at(icao, d, now_ns)` asserts `climate_day == d` and that the shifted vintage is strictly `< now_ns`.
- `ladder_p_yes(vector, ladder, calibration, latitude) -> Mapping[str, PYes(point, lower, upper)]`: computed by `rung_probability_interval` over `resolve(...).draws`; falls back to the complement when the ladder is not a complete partition; `p_no = 1 − point`; the modal rung is argmax `point`.
- An unknown NBM era yields `None`, which is counted and never pooled.
- **Declared:** `point` (the mean over draws) defines `P_MIN`, the strata and T1. `upper` is recorded only.

**Verify-first STOP**
1. Print `max_column_lst_climate_day` for one real 01Z/13Z/19Z cycle per station.
2. Assert it against `climate_day_for_txn` and one CLI FINAL day.
3. Print the vintage age at 00/06/09 LST on D. It must match the §3 table within ±30 min, or STOP.

RED first: `test_inclusive_band_uses_hi_plus_half_and_lo_minus_half`, `test_only_first_max_column_is_pushed`, `test_13z_day_d_cycle_never_feeds_day_d`, `test_vector_not_yet_available_is_invisible`, `test_unknown_era_yields_none`.

### WP3 — §3 rule (`maker_stage0_rule.py`, pure, ~2 h)

- `select_rungs`: at most 2 rungs, the lowest p_YES that pass `P_MIN`, never adjacent to the modal rung.
- `bid_price(p_no, best_no_bid, theta)`, with `best_no_bid = 1 − best YES ask`: `b_max` = the largest 1 ¢ `b` with `b ≤ min(B_CAP, p_no − E_MIN − θ·b·(1−b))`; returns `None` if `b_max < B_FLOOR`; otherwise `min(b_max, best + 0.01)`, or `b_max` when the NO bid side is empty.
- `is_marketable(b, best_yes_bid)`: `b ≥ 1 − best_yes_bid`. A marketable t0 is **not placed** and is counted `MARKETABLE_AT_T0`. An empty YES bid side is never marketable.
- Cancels: `hard_cancel_ns` = D 09:00 LST, integer ns; `obs_cancel` when `upper_f ≥ A − 2`; `forecast_stale` when age > 6 h.
- Constants, from the v0.3 working text: `P_MIN = 0.94`, `B_CAP = 0.80`, `E_MIN = 0.10`, `B_FLOOR = 0.70`. A test pins them, and the pinned spec sha catches drift.

RED first: `test_bid_is_best_plus_one_cent_capped_at_b_max`, `test_empty_no_bid_side_places_at_b_max`, `test_marketable_t0_is_not_placed`, `test_b_max_below_floor_cancels`, `test_two_rung_bound_and_modal_adjacency`, `test_hard_cancel_is_0900_standard_time`, `test_constants_match_spec`.

### WP4 — Fill simulator (`maker_stage0_fill.py`, pure, ~4 h)

**Events.** `Event(ts_ns, kind, seq, payload)` is frozen and totally ordered by `(ts_ns, kind.priority, seq)`; `seq` is the source row order. Priority at equal timestamps:
0 `GAP_START`; 1 `CANCEL` (hard/obs/stale/p_min — cancels precede credits); 2 `PRINT` (a same-ts frame already reflects the trade); 3 `DEPTH`; 4 `GAP_END`; 5 `FORECAST_RELEASE`; 6 `DECIDE` (placement sees the same-ts frame).

**Clock.** Everything runs on the venue clock. Non-venue information (forecast releases, obs) shifts by +Δ (from WP0). The time-triggered hard cancel shifts by −Δ. Staleness counts from the shifted release. Every cross-clock comparison therefore errs leak-safe.

**Decision instants.** Each `FORECAST_RELEASE` for D, and the first fresh frame after a `GAP_END`. In between, the bid is static (§3: "at listing and at each forecast release"). A new price is a cancel-replace and starts a new episode.

**Episode.** One rest, from `t0` to its end. End reasons: `FILLED`, `REPLACED`, `CANCEL_{PMIN,BFLOOR,STALE,NOFORECAST,OBS,HARD}`, `TAPE_GAP`. A `TAPE_GAP` episode is censored: it is cut at the gap start, excluded from denominators, and its exposure-hours are counted.

**Placement guards at t0**
- The frame is the last one at or before `t0` with no gap covering `[frame_ts, t0]`. There is no age constant, because event-driven depth can be quiet.
- The bid must not be marketable.
- `q_censored` is set when a same-`ts_event` `DepthTruncation` row exists and the deepest displayed YES ask is ≤ `1 − b`.

**Fill rule, stated once in NO-price space.** A YES print at `p` has NO price `q = 1 − p`. A resting NO bid at `b` is filled only by **YES-BUYER** prints with `q ≤ b`, i.e. `p ≥ 1 − b` (direction per WP0).
- `Q0` = displayed NO size at ≥ `b` at `t0` = Σ YES-ask size at ≤ `1 − b`.
- `V(t)` = Σ contracts (`TradeUnit`) of credited prints with `t0 < ts ≤ t` and `q ≤ b`, outside gaps. It resets on every cancel-replace.
- **Base:** filled at the first `t` with `V(t) ≥ Q0 + 1`.
- **2× stress:** filled at the first `t` with `V(t) ≥ 2·(Q0 + 1)`.
- `NO_AGGRESSOR` prints are never credited, and no fill comes from an implied price.
- After a fill the position is held, with no further bids on the pair.

**Price-priority variant** (same pass; it only feeds `RULE-SENSITIVE`)
- Filled at the first credited print with `q < b`, or when `V_{q=b} ≥ Q0_{=b} + 1`, where `Q0_{=b}` is the YES-ask size at exactly `1 − b`.
- Every base fill is also a price-priority fill, so the two bracket the truth: base over-counts the queue behind the touch; price-priority ignores joiners and cancels ahead of us.
- Through fills and same-level fills are reported separately. Through fills are mechanically adverse.

**Episode record:** `station, climate_day, rung_id, t0_ns, end_ns, end_reason, bid, q0, q0_eq, q_censored, filled_ns_{base,stress,pp}, fill_kind, p_yes_point_live, p_yes_upper_live, cycle_runtime_ns, raw_sha256, nbm_era, source_host, available_at_ns, depth_ts_used_ns`. "Live" means the vector in force at the fill instant, or for an unfilled episode, the last vector it rested under.

**Leakage asserts** raise and are never logged-and-continued:
- `available_at_ns + Δ < t0_ns ≤ filled_ns`;
- `depth_ts_used_ns ≤ t0_ns`;
- every credited print has `t0 < ts < end`.

Reads are scoped by instrument and absolute ns, never by hour-of-day.

RED first: `test_equal_timestamp_cancel_precedes_print`, `test_print_at_t0_is_never_credited`, `test_yes_buyer_print_at_no_price_le_b_counts`, `test_yes_seller_print_never_counts`, `test_queue_ahead_plus_one_must_trade_through`, `test_replace_resets_volume_and_queue`, `test_stress_needs_twice_queue_plus_one`, `test_price_priority_through_print_fills_behind_touch`, `test_every_base_fill_is_a_price_priority_fill`, `test_episode_inside_gap_is_censored_not_unfilled`, `test_truncated_frame_flags_q_censored`, `test_clock_shift_delays_forecast_and_advances_hard_cancel`, `test_simulator_module_does_not_import_truth`.

### WP5 — Statistics and verdict (`maker_stage0_stats.py`, ~4 h)

**Units.** A pair counts if it has ≥ 1 uncensored episode and is filled if any episode filled; a station-day is filled if any of its pairs filled. The verdict uses the pair rate, the stricter of the two (station-day rate ≥ pair rate).

**§6.9 rows**
- Filled rows are filled episodes, at most one per pair.
- Unfilled rows are episodes of pairs that never filled. Unfilled episodes of later-filled pairs are dropped from both sides and counted.
- Stratum: `p_yes_point_live` → p_NO, binned `[0.94,0.96)`, `[0.96,0.98)`, `[0.98,1]`. Cluster key: `cluster_key("date")`.

**Statistics**
- `T1 = L_f − 1.5·mean(p_f)`.
- `T2 = Σ_s w_s (L_{f,s} − L_{u,s})`, with `w_s = n_{f,s}/n_f`, over strata non-empty on both sides.
- Bootstrap p is the share of *defined* draws with `T ≤ 0`. A draw is undefined with zero filled rows (T1), or with zero filled or zero unfilled rows in every stratum (T2). Undefined draws are dropped and counted.
- Exact sidecars, labelled as ignoring clustering: T1: Poisson-binomial `P(L ≥ l_obs)` under `Bernoulli(min(1, 1.5·p_i))`; T2: pooled one-sided Fisher.

**Power line.** For each k ∈ {1.5, 2, 3}: 400 parametric sims, seeded `BOOTSTRAP_SEED + k·1000`. Filled rows draw `Bernoulli(min(1, k·p_i))` and unfilled rows draw `Bernoulli(p_i)`. Each sim goes through the same bootstrap decision; the line reports P(FAIL).

**Tail reliability.** `tail_reliability(nbp, truth, days, stations, parity)` on 2026-07-01..09-18 (the truth CSV covers 2026-01-01..10-11).
- Rows: every inclusive 2 °F band `[A, A+1]` on the station's parity, for each of the 3 day-D vectors, with p_YES < 0.06.
- Bins `[0,.02)`, `[.02,.04)`, `[.04,.06)`, each with n, dates, mean p, observed frequency and a Clopper-Pearson CI.
- A pooled exact test sets `TAIL-MISCALIBRATED`.

`verdict(rates, s69) -> Verdict` implements §1.1 exactly. A `--scored` re-run reproduces it.

RED first: `test_verdict_table_rows_v1_to_v6`, `test_inconclusive_never_maps_to_not_killed`, `test_stress_below_floor_is_no_go`, `test_rule_sensitive_annotation_keeps_no_go`, `test_degenerate_draws_dropped_and_counted`, `test_t2_is_stratum_standardised`, `test_unfilled_episodes_of_filled_pairs_excluded`, `test_poisson_binomial_tail_matches_brute_force`, `test_power_line_is_seeded_and_monotone_in_k`, `test_bootstrap_clusters_by_climate_date`, `test_point_estimate_and_lower_bound_are_separate`.

### WP6 — Driver, report, run (`maker_stage0_replay.py`, ~3 h + run)

**CLI:** `--census-days --trade-unit --catalog-root ~/.local/share/breezy/catalog/quote_tape/polymarket_us --nbp-root ~/.local/share/breezy/derived/nbp --truth PATH --out-dir ~/.local/share/breezy/derived/maker_stage0/<run_id> [--stations --days] [--tail-only]`.

**Flow**
1. Per station-day: build events, simulate all three rules, append to `episodes.jsonl`, write one `progress.jsonl` line.
2. Only after every station-day: load truth and score, in a separate function.
3. Render the report and copy the sidecar.

RED first: `test_driver_scores_only_after_simulation_completes`, `test_report_has_verdict_pins_banner_and_holdout_line`, `test_stats_rerun_on_scored_csv_reproduces_tables`.

**Run plan.** Avoid the 02:05Z nightly and the 10–24 GB study windows. One heavy job at a time.
1. P1, then P2.
2. **Benchmark** on 8 station-days (2 per station, across 2 weeks):
   `systemd-run --user --unit maker-s0-bench -p MemoryMax=4G -p RuntimeMaxSec=1800 -p LimitNOFILE=524288 <venv python> -m scripts.analysis.maker_stage0_replay …`.
   Read `memory.peak` and the slowest station-day.
3. **Full run** `maker-s0-full`: `RuntimeMaxSec` = 3× the extrapolation, capped at 6 h (S-5); `MemoryMax` = 2× the peak, capped at 4G; arm a Monitor on the `progress.jsonl` mtime in the launch turn, with stall threshold = 3× the slowest benchmark station-day, minimum 10 min; wait until `ActiveState ∉ {active, activating}`.
4. `--tail-only` afterwards, as its own unit.
5. Read EXIT. Copy outputs to `docs/evidence/maker/`, re-check disk, commit by explicit paths, and push per milestone policy.

## 6. Data and tooling dependencies

| Item | Path | State (2026-10-12) |
|---|---|---|
| Depth10 + prints (YES leg) | `…/quote_tape/polymarket_us/data/{order_book_depths,trade_tick}/` | present; prints from 09-17 |
| Gaps / truncation / offset | `…/data/custom_quote_tape_gap` (1,215 dirs), `custom_depth_truncation` (1,248), `custom_venue_clock_offset` (90) | present |
| Fee θ | per-market `feeCoefficient` in the instrument defs | **UNVERIFIED** → 0.0695 |
| NBP store | `~/.local/share/breezy/derived/nbp/` + `_manifest.json` | ends 09-29 19z → P2 |
| Artefact | `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` (`9c0b6d6e…923a5e`); fit splits ≤ 2026-06-30 (`nbp_calibration.py:273-278`) | present |
| Truth | `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` (2026-01-01..10-11; refetched 10-12 → copy and pin) | present |
| Truth cross-check | `…/settlement-truth/settlement_truth.parquet` (≤ 09-28) | overlap only |
| Obs (cancel) | obs store or IEM cache | **UNVERIFIED** → WP0 |
| S1 outputs | census list, unit | **not delivered** (E1) |
| Lockfile / disk | `uv.lock` / `$HOME` volume | present / **4.7 GB free, below the 10 GB floor** (E4) |

UNVERIFIED: the `ParquetDataCatalog.query` kwargs in 1.231 (WP0 checks one instrument); whether a live actor would see a 07Z NBP cycle the backfill lacks (3 `CYCLES`) — if so, the replay window is pessimistic.

## 7. Risks and guards

| Risk | Invariant / lesson | Guard |
|---|---|---|
| Look-ahead | "implausible result is a leak" | strict `available_at + Δ < t0`; instrument + ns scoping; truth unreachable from the simulator (test); score only after simulation |
| Queue rule biases the kill | correctness | price-priority bracket; `RULE-SENSITIVE`; regime split |
| Gap or stale frame invents or hides fills | correctness | gap-censored episodes; gap-free frame rule; excluded hours reported |
| Equal-ts or clock-order leak | §7.6 no leakage | total order + Δ shift (tests) |
| Forkable verdict | "an underpowered verdict describes the sample" | §1.1 frozen; power line; never "GO" |
| **Frozen NBP holdout touched** | `RULING_holdout_freeze_and_forward_window_2026-10-03` cl. 1 freezes [07-01, 10-02); `DEFAULT_SPLITS.holdout_start` = 07-01 (`nbp_calibration.py:277`) | See the note below this table |
| Disk exhaustion | collectors refuse < 10 GB | E4 before every heavy step; basetemp under `~/.cache`; `rm` after EXIT |
| Shared venv or tree damage; strays | no uv/pip from a worktree; no stash | exact interpreter; ruff on own files only; commit by explicit path |
| Memory blow-up or stall | one heavy job; stall watch | MemoryMax, RuntimeMaxSec, progress Monitor |
| Egress | NO-SEND | replay makes no network calls; P2 is the existing allowlisted tool |

**Holdout note.** The tail days (07-01..09-18) and replay days 09-19..10-01 fall inside the frozen holdout. Ruling cl. 3 says the window was already touched by the September tape studies, and admits it as descriptive evidence only. S2 is descriptive only, fits nothing, never calls `open_holdout`, and prints a holdout-touch line. If the coordinator rules otherwise, S-6 applies (Q1), and the fallback tail window is the validate split 2025-05-28..2026-05-03, labelled in-sample and optimistic.

S2 imports no exec, runtime or deploy code, so it cannot violate `allow_short`, the caps or enablement. A test asserts no import from `breezy.adapters.polymarket_us.exec` or `breezy.runtime`.

## 8. Effort and artifact

| WP0 | WP1 | WP2 | WP3 | WP4 | WP5 | WP6 | Review fixes + gates | Total |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 2 | 3 | 2 | 4 | 4 | 3 | 2 | **≈ 23 agent-hours** |

Run wall time is about 1–3 h after P2 and the benchmark.

Artifact: `docs/evidence/maker/STAGE0_REPLAY_<date>.md` plus `stage0_<date>/`. Each file stays under 5 MB; larger files are gzipped and pinned.

## 9. Open questions for peer review (max 5)

1. **Holdout.** Are NBP + truth reads inside the frozen holdout [07-01, 10-02) admissible under cl. 3 as descriptive Stage 0 evidence? This covers both the tail table and replay days before 10-02. If not, S-6 applies.
2. **Fill rule for the verdict.** Spec base rule (as here, per the brief) or price-priority? The plan brackets both and annotates a `RULE-SENSITIVE` NO-GO.
3. **INCONCLUSIVE bar.** Is power ≥ 0.80 at k = 2, n_filled ≥ 20 and defined draws ≥ 90 % the right bar? On about 23 dates, `NOT-KILLED-UNSCREENED` is the likely outcome.
4. **T2 unfilled set.** Is it correct to drop episodes of later-filled pairs?
5. **Window.** Should Stage 0 also replay an amended staleness threshold? This plan does not, because that is a spec choice.

## Spec v0.3 inputs (defects surfaced by the reviews; not fixed here)

1. §6.1 precondition ("YES print ≤ 1−b, SELLER") contradicts its own NO-terms rule. It should read: a **YES BUYER at ≥ 1−b** (NO price ≤ b).
2. §6.1 counts better-priced NO size as queue but credits only prints at ≤ b. This biases the fill rate low behind the touch. Consider price-priority.
3. §6.0 kill semantics: base vs stressed rate; the labels NOT-KILLED / -UNSCREENED; never GO.
4. §6.9: exact vs bootstrap primacy at small counts; degenerate draws; T2 standardisation; minimum power; the unit under cancel-replace.
5. §3: with the 6 h staleness rule and the 13/19/01Z cadence, bidding ends at about 08:04Z D. The 09:00 LST cancel never binds, and there is a daily 13-min hole at about 20:04Z.
6. §3: whether `P_MIN` uses the point or the upper p. The live path forwards bounds (`calibration_artefact.py:95-101`).
7. §3: the marketable case, where `best+0.01 ≥` NO ask, is unspecified.
8. §6.0: the "2026-08-30 →" span is not replayable, because prints start 09-17/18.
9. The header says v0.3, but the §8 history ends at v0.2.
10. The relationship of Stage 0 and the shadow run to the frozen NBP holdout [07-01, 10-02).
11. A 10 h permit TTL vs a ≈ 17.8 h rest window (v0.3 `expire_time ≤ permit expiry`).
12. A net-expectancy upper bound < 0 is not a §6.0 kill; it is only reported descriptively.

## Review disposition

Where the brief and the reviewers conflict, this plan follows the brief: the base rule is spec §6.1; there is no GO label; a stressed rate < 0.10 is NO-GO (agrees with PM #3; replaces MLE's `GO-FRAGILE`).

| Review file | # | Disposition |
|---|---|---|
| S2-r1-prediction-market-reviewer | 1 | ACCEPTED-changed WP4: one NO-space rule, price-priority bracket, through/same-level split, regime split. Base rule kept per brief/spec; the bias goes to Spec input 2 |
| ″ | 2 | ACCEPTED-changed §1.1 (frozen, no GO); WP5 (power line, exact sidecar) |
| ″ | 3 | ACCEPTED-changed §1.1 V4; days-to-200 in §1.2 |
| ″ | 4 | ACCEPTED-changed WP4/WP5: point p at the fill instant; last live p for unfilled; episode unit plus pair and station-day rates |
| ″ | 5 | ACCEPTED-changed WP5: stratum-standardised T2; the mechanism is noted in the report |
| ″ | 6 | (i) REBUTTED: fit splits end 2026-06-30 (`nbp_calibration.py:273-278`), so replay days are out of the fit. (ii) ACCEPTED-changed: WP5 tail table |
| ″ | 7 | ACCEPTED-changed: §3 table; §1.3 |
| ″ | 8 | ACCEPTED-changed WP3/WP4: marketability, `q_censored`, gap-free frame rule |
| ″ | 9 | DEFERRED: at qty 1 the continuous fee is ≥ the quantised fee (0.0111 → 0.01), so it is conservative; bound ≤ 0.005/contract |
| ″ | 10 | ACCEPTED-changed WP0: n_defined ≥ 200; undefined ≠ disagree; gap-free frames |
| ″ | 11 | ACCEPTED-changed: P2 is now a pre-step, with a floor count and a stress |
| ″ | 12 | ACCEPTED-changed §1.5: cluster counts + Clopper-Pearson |
| S2-r1-mle-reviewer | 1 | ACCEPTED-changed §1.1: UNSCREENED label, degenerate-draw rule, power, exact p. `GO-FRAGILE` becomes NO-GO per the brief and PM #3 |
| ″ | 2 | ACCEPTED-changed §1.9: episodes, scored CSV, provenance, seed, manifest; stats re-runnable |
| ″ | 3 | ACCEPTED-changed WP1 `pin_inputs` |
| ″ | 4 | ACCEPTED-changed WP0/WP4: `resolved_gaps_by_seq` (`tape_records.py:536`), `DepthTruncation`, measured coverage |
| ″ | 5 | ACCEPTED-changed WP4: total order, Δ rule (`tape_records.py:227-244`; `parsing.py:777-779,971`) |
| ″ | 6 | ACCEPTED §4: naked-short reason (`backtest_order_guard.py:118,284`) and two variants. Third variant REBUTTED: price-priority is already the provable upper bracket, and Depth10 snapshots carry no per-level delete events, so it has no decision payoff |
| ″ | 7 | ACCEPTED-changed WP4/WP5: episode unit, one stratum rule, station-day unit |
| ″ | 8 | ACCEPTED-changed: tail table on 07-01..09-18 per the brief. REBUTTED in part: "sealed 05-05..06-30" is the `v5_fit_slice` (`nbp_calibration.py:276`); the frozen holdout is [07-01, 10-02) (ruling cl. 1), disclosed in §7/Q1 |
| ″ | 9 | ACCEPTED-changed: E4, gate step 1, manifest |
| ″ | 10 | ACCEPTED-changed P2 (`--request-budget`, env, start 09-30) |
| ″ | 11 | ACCEPTED-changed P2: floor count and +60 min stress |
| ″ | 12 | ACCEPTED-changed WP0: mid test, frozen thresholds, positive control |
| ″ | 13 | Point p declared (WP2). Upper-p sensitivity DEFERRED to Spec input 6: it doubles the tables without changing the frozen verdict |
| ″ | 14 | ACCEPTED-changed WP6: stratified benchmark; derived stall threshold |

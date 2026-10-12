# S5 — Prospective shadow run, evaluation and promotion-gate tooling

| Field | Value |
|---|---|
| ID | S5 |
| Revision | r2 (supersedes r1; folds `reviews/S5-r1-architect.md` + `reviews/S5-r1-prediction-market-reviewer.md`) |
| Date | 2026-10-12 |
| Status | READY-FOR-REVIEW |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` (working v0.3: climate-day match, age from `available_at`, `B_FLOOR` 0.70). Constants live in `config.py` only; the PREREG checker requires equality with the spec |
| Ruling context | T2 route of `docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md`. The NO-TRADE ruling stays in force throughout S5 |

**Invariants (binding on every WP).** Nautilus immutable (subclass `Strategy`; native clock and order factory only). `allow_short` stays `False`. Never weaken/delete a safety, settlement, contract or NO-SEND egress test; exact-sets are WIDENED by one reviewed row (L-12). Never assign an operator cap; never touch live enablement or `BREEZY_ORDERS_ENABLED` (orders-off drop-in untouched). Never edit a frozen PREREG or move a pre-registered date. Stage 0 is exploratory, never promotion evidence. Worktrees: `PYTHONPATH=<wt>/src`; no `uv`/`pip`/`git stash`; full gate after every merge, `--basetemp` under `~/.cache`, `rm` after reading EXIT; `lint-imports` from the tree root; one heavy job at a time; stall watch on long jobs.

## 1. Goal state (acceptance test)

S5 is done when exactly one of these exists, produced by the bot's tooling (never by Claude arithmetic):

- **PASS.** `docs/evidence/maker/S5_PROMOTION_GATE_REPORT.{json,md}`. The holdout is read once, the nine `CriterionRow`s are all true, and `assemble_outcome` returns `PROPOSAL`. The report says it arms nothing (`render_rationale` already prints "never arms", `analysis/promotion_criteria.py:651`). Activation stays manual and outside S5.
- **FAIL / STOP.** The same report with `NO_PROPOSAL` naming the failed gates; or `S5_SEQUENTIAL_STOP_<date>.md` (harm boundary); or `S5_INCONCLUSIVE_UNDERPOWERED_<date>.md` (outcome-blind power stop; not a refutation, still no PROPOSAL).

On the way: family code + a REGISTERED SHADOW manifest with no `live_orders_ruling`; `docs/evidence/maker/PREREG.json` frozen (introducing commit an ancestor of HEAD) **before** `holdout_start_date`; a daily counts-only progress file.

## 2. Entry criteria and STOP conditions

| # | Entry criterion (WP0 records evidence) | Evidence |
|---|---|---|
| E1 | S2 GO: §6.9 not FAIL, and the Stage 0 stressed (2×) fill rate `r_lo` satisfies the feasibility rule in §8: projected holdout station-days by `calendar_cap_date` ≥ 200 | `docs/evidence/maker/STAGE0_REPLAY_*.md` |
| E2 | S3 PASS: A1 floor not `unreachable_veto` for the maker mix | `docs/evidence/maker/A1_REACHABILITY_*.md` |
| E3 | `TRADE_QUANTITY_UNIT` resolved; YES→NO print inversion pinned (S1) | S1 evidence file |
| E4 | §6.1 fill simulator importable and unit-tested; signature recorded; S2 used the identical age-from-`available_at` and climate-day-match rule (else S2's rate is not the shadow's) | path + sha |
| E5 | `register_hypothesis` (`analysis/hypothesis_ledger.py:873`) returns a registered record (not `UNDERPOWERED_NOT_REGISTERED`, :226) for this design, by a pure dry call with the current ledger records | WP0 note |

**S4 (exec resting path) is no longer an entry criterion.** The shadow never submits, so it moves to G8 (§5 WP4).

**STOP conditions.**

| ID | Trigger | Outcome |
|---|---|---|
| S-1 | Any entry criterion unmet | Do not start; build nothing ahead of it |
| S-2 | WP0 shows the two NO rungs per station-day conflict under live `exclusive_bucket_conflict` and spec v0.3 has not ruled on it (§2 item 4 of WP0) | Do not freeze |
| S-3 | Harm boundary fires (WP5) | STOP only |
| S-4 | Holdout read, any gate false | `NO_PROPOSAL` |
| S-5 | Day-60 outcome-blind power check: projected holdout station-days or positions at `calendar_cap_date` fall below the read target, or `calendar_cap_date` is reached first | `INCONCLUSIVE_UNDERPOWERED`; the run ends early; the cap is never extended |

The r1 WS-cap STOP is removed (architect #5): subscriptions are per YES slug and the NO leg shares it; a NO-id depth subscribe is refused (`adapters/polymarket_us/data.py:1632-1656` via `instrument_id_to_slug`, `symbology.py:260-274`); the pool shards; discovery already subscribes every listed slug (`data.py:1453`). Replaced by the WP6 boot health check.

## 3. Simplest direct path

1. One `composition_kind`, `no_ladder_maker`: a thin Nautilus `Strategy` around a pure `decide()`. It never submits or cancels; it logs `SHADOW_BOOT`/`SHADOW_STOP`, a `SHADOW_FORECAST` line per vector (full quantile vector, `available_at_ns`, `climate_day`, θ, fee coefficient) and a `SHADOW_DECISION` per rest/cancel/abstain, to the node log and a JSONL sink; it uses native `clock.set_time_alert` for the 09:00 LST cancel and forecast expiry.
2. **The scored sample is an offline causal replay, not the live log.** One scorer replays the same `decide()` over the recorded Depth10/trade tape, using the live-logged (PIT) vectors, the node up-windows (BOOT→STOP), and §6.1-simulator fill state, so a filled rung stops resting and counts toward the 2-rung/8-position caps. The live JSONL is the PIT forecast record plus a parity check (replay vs live rests → G7). This one choice answers fill feedback (PM #4), restart semantics (architect #2), re-deciding stresses (PM #6) and late timed cancels (architect #3, scorer clamp).
3. Statistics reuse `scoring_core`, `boundary_for` and `assemble_outcome`.
4. **Zero planned revisions.** Stage 0 is the only development set. Every shadow day from `holdout_start_date` is holdout. Any parameter change is a new PREREG version (a fork with a new start date), never an edit. This removes the r1 60/40 split, purge and Holm machinery.

**Not built:** AUT-2/AUT-5b (nothing for one read-once go/no-go; AUT-5b is an enum); `hypothesis_triage` dashboard; `BacktestEngine`/`FillModel` (cannot express §6.1: YES-leg prints, last-in-queue vs displayed NO size, no `NO_AGGRESSOR` credit); an in-node fill simulator (the replay gives the same causality without `scripts/analysis` code in `src/`); a per-climate-day forecast accessor (§4); `RiskManager.evaluate_order` in shadow (nets against a portfolio shadow never populates, `risk.py:572-646`, so vacuous — architect #4).

## 4. Nautilus null-hypothesis check

| Need | Native / existing (evidence) | Verdict |
|---|---|---|
| Lifecycle, subscriptions | `Strategy` subclass; FQ precedent subscribes the YES slug and registers the NO book via the sibling (`strategy/forecast_quantile_ladder/strategy.py:356-361`) | REUSE the FQ shape exactly |
| Timed cancels | Nautilus `Clock.set_time_alert(name, alert_time, callback)` (`nautilus_trader/common/component.pyx:71,104`; repo uses the sibling `set_timer`, e.g. `ingest/nbm_quantile_actor.py:314`) | REUSE; no new scheduler |
| Would-be order | `Strategy.order_factory.limit(..., GTC, qty=1)`, built and logged, never submitted | REUSE |
| Family dispatch / manifest | `_compose_family` (`app/trade.py:929-978`); `FamilyManifest` (`persistence/family_manifest.py:214`), `parse_family_manifest` (:300), `_COMPOSITION_KINDS` (:119) | EXTEND: one kind (WIDENED row), no new keys |
| Forecast vector | `ForecastQuantileState.value_at` (`strategy/ladder_ev/forecast_state.py:310-325`): latest complete visible vector, visibility `available_at_ns <= now_ns` (:321), **climate-day-blind**; vector carries `climate_day` and `available_at_ns` (:281-298); age convention `now - available_at_ns` (:112-148) | REUSE. `decide` gets the vector's `climate_day` and abstains `forecast_day_mismatch` when it differs from the ladder's day. No new loader; D-day coverage is measured, not engineered (WP0 item 3) |
| p(rung) | `load_live_calibration` (`forecast_quantile_ladder/calibration_artefact.py:236`), `ArtefactBoundsProvider` (`artefact_bounds.py:38`) | REUSE; one pure `p_no_for_rung` adapter |
| Halt | family-halt row keyed per `family_id` (`current_rung_hold/family_id_arg.py:17-22`) | REUSE; read into `decide(halted=…)`; kind added to `HALTABLE_COMPOSITION_KINDS` (:20), **not** to `KINDS_WITH_EXIT_PATH` (:30) |
| Fee probe | `_build_fee_drift_probe` finds a slug via `config.instrument_ids` or `current_yes_instrument_slug()` (`app/trade.py:312-334`) | REUSE; the maker exposes `current_yes_instrument_slug()` |
| Structural limits | `RiskLimits` values (`weather_common/risk.py:181`, `allow_short` :224); `RefusalCounter` (`refusals.py:123`) | REUSE values and counter. Limits become pure checks in `decide`; no `evaluate_order` |
| Exclusive grouping | `SharedExposureView.mutually_exclusive_group` = same `event_key`, other instrument (`risk.py:433-442`); `exclusive_conflict` refuses any positive delta when a group member is held (:517-530) | VERIFIED rule. WP0 checks whether sibling NO legs share `event_key` (S-2) |
| Statistics | `LeakageError` :34, `ClusterCI` :176, `bootstrap_cluster_draws` :216, `percentile_interval` :246 (`analysis/stats/scoring_core.py`). Import explicitly; `nbp_calibration.py:1721` has a different `percentile_interval` | REUSE |
| Sequential boundary | `boundary_for` returns `(b_eff, b_fut)` (`analysis/stats/group_sequential_boundaries.py:163-170`); `one_sided_spend` :40 | REUSE the module function directly, harm = `b_fut`. **Not** `BoundaryArtefact` (`persistence/gs_boundary_artefact.py:269-272` hard-pins `i_max`/α) |
| Gate assembly | `CriterionRow` :95, `assemble_outcome` :613, `render_rationale` :640 (`analysis/promotion_criteria.py`) | REUSE. Build rows with explicit `tag=None, inert_reason, detail` (`_row` is private) |
| Freeze / read-once | `check_frozen_blob` and `_canonical` (`scripts/analysis/prereg_precommit_check.py:340`, :323); `check_freeze_introduction` :423, `_refuse_overwrite` :780, `_preflight_inputs` :875 (`scripts/analysis/no_longshot_pooled_test.py`, imported at sha `47d1b94c`, re-recorded in WP0) | REUSE by import |
| Win rate / drawdown / profit factor | `portfolio_roi_report.py` is keyed on `DurableFillRecord`; shadow has none | MISSING: small functions in one stats module |

**Built here:** `decide` + strategy, the `p_no_for_rung` adapter, the JSONL sink, the replay scorer, one stats module, the report, PREREG checker, tally and progress report.

## 5. Work packages

All WPs: focused tests first, keeping the RED→GREEN output. Every focused list includes the exec import pin, the NO-SEND egress tests, `test_shadow_only_false_is_only_the_gate_output.py`, `test_autonomy_*`, the import gates and the citation map. Then the full gate (`scripts/ci/run_tests_no_egress.sh`) and `lint-imports` ("N kept, 0 broken"). Run `ruff format` on touched files only, and `git status` checks for strays before every commit.

### WP0 — Entry verification and pre-freeze facts (no code; ~3 h)

Write `docs/evidence/maker/S5_ENTRY_<date>.md` with:

1. E1–E5 evidence paths and shas, the S2 simulator signature, and the imported sha of `no_longshot_pooled_test.py`.
2. **E5 dry call.** `register_hypothesis(...)` with this design's shape against the current ledger records. Record the allocated α (`alpha_family`) and the outcome.
3. **Resting coverage table (outcome-blind).** From the NBP derived store's `(available_at_ns, climate_day)` rows 2026-09-01..freeze−1: per (station, ladder day D vs D−1, UTC hour), hours where a vector targeting the ladder's day is visible, age ≤ 6 h, and before 09:00 LST. Settles the "D+1 MAX column" UTC-vs-LST ambiguity empirically. D-day mean < 1 h/day → record "D-day ≈ 0"; no code change (`decide` abstains on mismatch). Emit the coverage factor `c` used in §8.
4. **Exclusive grouping on NO legs.** How `MispricingContract.event_key` is formed for two NO legs of one ladder. If shared, live `exclusive_bucket_conflict` refuses the 2nd NO rung (`risk.py:517-530, 639-640`): spec §4 is self-contradictory → spec v0.3; S-2 holds until ruled; PREREG pins `MAX_RUNGS_PER_STATION_DAY` only after.
5. **`BREEZY_SENDING_FAMILY_ID` switch effects** (enumerate, verify each, mark retired/broken): FQ-only `FqDecisionFunnelActor`, F6 FQ-BRIDGE loss/parity veto and `FQ_VECTOR_COMPLETE`/NBP markers parsed by `analysis/capture_node_log_markers.py` stop (consumers: `nbp_shadow_parity.py`, `fq_loss_taxonomy_logs.py`, funnel digest, F13/AUT jobs); the fq_v1 halt row/timers stop governing (halt keys per `family_id`); fee probe registers only via `current_yes_instrument_slug()` (`app/trade.py:312-334, 428-436`); `LIVE_OBSERVATIONS=1` still required (`runtime/settings.py:865-872`); `replay_daily_runner._SUPPORTED_COMPOSITION_KINDS` (`scripts/analysis/replay_daily_runner.py:945-947`) refuses the kind if its armed manifest follows the sending family (check); whether `autonomy/resolver.py` resolves its family from the env var; whether M1-v3 forward-screen inputs depend on any FQ actor. Any "broken" consumer is a STOP until rehomed.
6. Reuse of the `StationObservation` interval for the integer-°C widening, from the CRH precedent test.

**Completion:** committed with GO or a named STOP. Spec defects found go to the coordinator; they are never edited here.

### WP1 — Pure decision core (~6 h)

Create `src/breezy/strategy/no_ladder_maker/{__init__,config,rung_probability,decision}.py`.

```python
# config.py — the only home of spec constants (PREREG checker imports them)
P_MIN, B_CAP, E_MIN, B_FLOOR, TICK, CANCEL_HOUR_LST, MAX_FORECAST_AGE_H, MAX_RUNGS_PER_STATION_DAY, MAX_SIMULTANEOUS, ORDER_QTY
class NoLadderMakerConfig(StrategyConfig, frozen=True): allow_short: bool = False   # no shadow_only field (YAGNI, architect #7)
# rung_probability.py
def p_no_for_rung(*, bounds: RungBounds, rung: Rung) -> float            # 1 - P(high in [A,B] inclusive)
# decision.py
@dataclass(frozen=True) class Rest:    station, climate_day, rung_id, instrument_id, bid, p_no, fee_est, best_no_bid,
                                       displayed_no_bid_size_at_or_above, forecast_available_ns, forecast_climate_day
@dataclass(frozen=True) class Cancel:  ..., reason: Literal["cancel_hour_lst","obs_within_one_rung","forecast_stale",
                                       "p_no_below_min","replace","node_stop"]
@dataclass(frozen=True) class Abstain: station, climate_day, reason: str   # incl. forecast_day_mismatch, halted, cap_reached
def decide(*, now_ns, station, climate_day, std_utc_offset_hours, ladder, vector: ForecastQuantileVector | None,
           p_no_by_rung, no_book, obs_interval_f, resting: Mapping[str, Decimal], filled: frozenset[str],
           open_positions_total: int, fee_coefficient: float, halted: bool, ambiguous_intent_open: bool,
           refusals: RefusalCounter) -> tuple[Rest | Cancel | Abstain, ...]
```

Rules beyond r1:
- Abstain `forecast_day_mismatch` when `vector.climate_day != climate_day`.
- Age = `now_ns − vector.available_at_ns`; > 6 h gives `Cancel(forecast_stale)`.
- Leakage is refused iff `vector.available_at_ns > now_ns`. The operator is `<=`-visible, matching `forecast_state.py:321`.
- `filled` rungs are never re-rested and count toward `MAX_RUNGS_PER_STATION_DAY`.
- `open_positions_total + resting ≥ MAX_SIMULTANEOUS` gives Abstain `cap_reached`.
- Every structural refusal is recorded in `refusals`.

**RED-first** tests in `tests/strategy/no_ladder_maker/test_decision.py`:

| Group | Tests |
|---|---|
| Kept from r1 | `test_rung_below_p_min_cancels_and_never_rests`, `test_bid_is_min_of_b_max_and_best_bid_plus_tick`, `test_empty_no_bid_side_rests_at_b_max_without_implied_price`, `test_b_max_below_floor_cancels`, `test_at_most_two_rungs_and_never_adjacent_to_modal`, `test_cancel_at_0900_lst_per_station_offset`, `test_integer_celsius_observation_widens_to_full_ambiguity_band`, `test_price_change_is_cancel_replace_with_new_t0`, `test_halt_or_ambiguous_intent_abstains_whole_station_day`, `test_inclusive_band_edges_match_bucket_facts_from_instrument_id` |
| New | `test_vector_for_other_climate_day_abstains`, `test_forecast_age_measured_from_available_at_not_cycle_runtime`, `test_vector_available_at_equal_to_now_is_visible_and_later_is_leakage`, `test_filled_rung_is_not_rerested_and_counts_toward_cap`, `test_simultaneous_cap_abstains_and_records_refusal`, `test_allow_short_false_never_produces_a_sell` |
| Elsewhere | `tests/strategy/no_ladder_maker/test_forbidden_imports.py::test_decision_imports_no_settlement_or_pnl` |

**Gate:** `pytest tests/strategy/no_ladder_maker` plus `lint-imports`.

**Completion:** green, with no edit outside the package.

### WP2 — Strategy, composition, manifest (SHADOW; ~9 h)

**Create**

- **`strategy.py` — `NoLadderMakerStrategy(Strategy)`.** FQ subscription shape (YES slug subscribed, NO book via `sibling_instrument_id`). On book/vector/obs events calls `decide` with `filled=frozenset()` (shadow cannot know fills; the replay supplies them). `clock.set_time_alert` per (station, D) at 09:00 LST and per vector at `available_at + 6 h`; each callback runs `decide` for that station. `on_start` → `SHADOW_BOOT {node_instance_id, ts, sha}`; `on_stop` → `SHADOW_STOP` + `Cancel(node_stop)` for every would-be rest: **restart contract = cancel-on-stop**, no rest survives a node instance. Each vector → `SHADOW_FORECAST` (q10..q90, mean, sd, `available_at_ns`, `cycle_runtime_ns`, `climate_day`, θ, fee coefficient). Builds `order_factory.limit(..., GTC, 1)` for the log only; exposes `current_yes_instrument_slug()`.
- **`shadow_sink.py` — `ShadowDecisionJsonlSink(output_dir)`**: append-only, one file per UTC day, `catalog_root.parent / "maker_shadow"`, explicit field serialisation.
- **`composition.py` — `build_no_ladder_maker_strategies(...)`** (r1 parameters).
- **`deploy/families/pm_us_no_ladder_maker_v1.json`** as r1 except `d0_climate_day` = `holdout_start_date`; stations LAX, MDW, MIA, SFO; no `live_orders_ruling`, no `exit_rule`.

**Modify** (each change is one reviewed WIDENED row):

| File | Change |
|---|---|
| `persistence/family_manifest.py:116-121` | kind added to `CompositionKind`/`_COMPOSITION_KINDS` |
| `app/trade.py:929-978` | `no_ladder_maker` branch: reuses `_open_halt_latch_preamble` and `_build_fee_drift_probe`; never calls `live_orders_authorized` |
| `persistence/autonomy/paths.py:28`, `strategy/autonomy/node_plugins.py`, `analysis/autonomy/offline_plugins.py` | `RefusingPlugin` parity rows (`tests/unit/test_autonomy_plugins.py:197-209`) |
| `strategy/current_rung_hold/family_id_arg.py:17-22` | add the kind to `HALTABLE_COMPOSITION_KINDS`. Amend the comment: "honours the row via `family_halt_submit_veto` *or*, for a non-submitting kind, via `decide(halted=…)`". Not added to `KINDS_WITH_EXIT_PATH` |

**RED-first tests**

| File | Tests |
|---|---|
| `tests/unit/test_family_manifest.py` | `test_no_ladder_maker_kind_loads_and_unknown_kind_still_refused` |
| `tests/unit/test_no_ladder_maker_composition.py` | `test_compose_family_dispatches_no_ladder_maker`, `test_maker_branch_never_calls_live_orders_gate`, `test_maker_manifest_with_live_orders_ruling_refuses_boot`, `test_fee_drift_probe_registers_for_maker` |
| `tests/strategy/no_ladder_maker/test_strategy_shadow.py` | `test_package_never_calls_order_mutation_api` (see below), `test_no_leg_book_received_via_yes_slug_subscription`, `test_cancel_fires_at_0900_lst_with_no_market_event` (TestClock), `test_forecast_expiry_alert_cancels_at_available_at_plus_6h`, `test_family_halt_row_abstains_maker_station_days`, `test_on_stop_writes_shadow_stop_and_node_stop_cancels`, `test_boot_line_carries_instance_id_and_sha`, `test_forecast_line_carries_full_quantile_vector_and_theta`, `test_jsonl_sink_round_trips_every_record_kind` |
| `tests/unit/test_autonomy_plugins.py` | widened rows |

`test_package_never_calls_order_mutation_api` is an AST scan over all of `src/breezy/strategy/no_ladder_maker/`. It bans calls to `submit_order`, `submit_order_list`, `modify_order`, `cancel_order`, `cancel_orders`, `cancel_all_orders`, `close_position` and `close_all_positions`.

`test_shadow_only_false_is_only_the_gate_output.py` must pass **unchanged**.

**Completion:** merged gate-green. The node is not switched yet.

### WP3 — Replay scorer (~10 h)

**`scripts/analysis/maker_shadow_scorer.py` (CLI)**

`--shadow-dir --tape --truth --prereg --out [--stress <name>]`

1. **Windows.** BOOT/STOP → node up-windows; a BOOT with no prior STOP closes the previous instance at its last logged line (conservative). Up-windows are outcome-blind and define `incomplete_day_rule` (no instance → no rests, whatever the outcome).
2. **Causal replay.** Walk tape (Depth10 + prints) and logged `SHADOW_FORECAST` vectors in event order inside up-windows; call `decision.decide` with `filled`/`open_positions_total` from §6.1 simulator state. Every rest ends at the earliest of cancel, replace, window end, 09:00 LST, `available_at + 6 h` — clamped independently of the live alert. Qty 1, so partial fills are moot.
3. **Parity.** Replay with fills disabled vs live `SHADOW_DECISION` rests → mismatch count to G7.
4. **Positions.** One row per filled (station, day, rung): bid, fee, fill ts, p_NO, outcome, lock hours; inclusive [A,B] via `bucket_facts_from_instrument_id` (`analysis/labeling/instrument_facts.py:72`) on CLI FINAL (wins any METAR conflict; lock to 11:00 ET). **Primary scoring:** unresolved past D+14 = LOSS (bid + fee); void = refund − fee (refund 0 until verified); both also counted separately.
5. **Unfilled counterfactuals** kept for §6.9.
6. **Baselines** (report-only unless spec v0.3 gates them): (a) taker at the NO ask at each first-rest t0; (b) forecast-only take. Units pinned: per eligible rung-day (unfilled = 0) and ROI on deployed capital, stricter used; n < 30 → `NOT_COMPARABLE`, never "beaten".
7. **Stress** (`--stress` re-runs 2–4 with one change): `fill_2x` re-fill+re-decide; `q_shift_±1F` and `theta_0_08` re-decide; `maker_coeff_eq_taker` re-cost; `loso_<STN>` re-aggregate; `by_month` re-aggregate, report-only.
8. **Refusals** (exit 3, no output): post-cap tape; missing/invalid PREREG; any vector with `available_at_ns > decision ts` (`LeakageError`); a rest before the frozen commit time.

**`scripts/analysis/maker_eval_stats.py`** (one pure module; r1's two merged, architect #11): `win_rate_ci`, `expectancy_lower_bound`, `profit_factor`, `max_drawdown_daily`, `turnover`, `exposure_by_station`, `return_on_deployed_capital`, `design_effect(cluster=...)`, `effective_n`, `station_day_n`, `adverse_selection_noninferiority(...)`, `power_projection(counts_by_day, cap_date)` (outcome-blind). Explicit `scoring_core` imports.

**RED-first tests**

| File | Tests |
|---|---|
| `tests/unit/test_maker_shadow_scorer.py` | `test_replace_resets_t0_and_queue_ahead`, `test_no_aggressor_prints_never_fill`, `test_filled_rung_stops_resting_and_third_fill_never_scored`, `test_rest_spanning_node_downtime_ends_at_last_line_of_instance`, `test_rest_clamped_to_0900_lst_even_without_live_cancel`, `test_rest_clamped_to_forecast_expiry`, `test_unresolved_past_deadline_scores_as_loss`, `test_void_scores_refund_minus_fee_and_is_counted`, `test_leakage_vector_refuses_run`, `test_inclusive_band_settlement`, `test_parity_counts_live_vs_replay_rest_mismatch`, `test_q_shift_stress_redecides_rest_set`, `test_baseline_below_min_n_is_not_comparable` |
| `tests/unit/test_maker_eval_stats.py` | `test_max_drawdown_of_daily_series`, `test_profit_factor_zero_losses_is_inf_flagged`, `test_ci_resamples_whole_blocks`, `test_design_effect_is_one_for_iid_clusters_of_one`, `test_power_projection_reads_no_outcome_field` (AST/field) |

**Completion:** merged; a synthetic 5-day dry run produces positions, outputs and every stress.

### WP4 — Nine-gate report (~6 h)

**`scripts/analysis/maker_promotion_report.py`**: loads the PREREG via `check_frozen_blob` + `check_freeze_introduction`; refuses before the read date and on a second read (`_refuse_overwrite`); builds nine `CriterionRow`s (machine value, threshold, input sha).

| Gate | Machine value(s) | Rule |
|---|---|---|
| G1 | observed win rate **and** block-bootstrap lower bound, as two fields | point ≥ 0.85 |
| G2 | position n, effective n (realised deff, 7-day blocks), station-day n | min(effective n, station-day n) ≥ 200 |
| G3 | expectancy lower bound, primary scoring (§WP3 step 4) | one-sided bound at `alpha_family` > 0 |
| G4 | `alpha_family`, revisions used (= 0) | revisions = 0 and α matches the ledger record |
| G5 | structural refusal counts; per-stress point estimates | no limit breach in the replay; every gated stress point estimate > 0; by-month report-only |
| G6 | leakage count, excluded-row count, mid-fill count, un-censused-day count | all = 0 |
| G7 | decode errors, parity mismatches, coverage | errors = 0; parity mismatch rate ≤ 0.01; up-window coverage of listed station-day resting hours ≥ 0.90 |
| G8 | S3 artefact sha; S4 merged sha + gate EXIT; credentials and permit evidence from node-log lines | S4 implements cancel-on-stop (or a stricter behaviour). Never reads or assigns `operator_max_*` (`order_enablement.py:211-217`) |
| G9 | §6.9 bound, achieved power | `AS_PASS` only; `INCONCLUSIVE` = false |

G3 method (PM #5a): the more conservative of (i) a cluster-robust Student-t bound over 7-day blocks, G−1 df, and (ii) a 7-day-block percentile bootstrap, B = 100 000; climate-date clusters reported beside; PREREG states the MDE at the read n. Then `assemble_outcome(rows, criteria_status="FROZEN_PREREG")` + `render_rationale`. No manifest write, no `runtime.settings` import, nothing under `deploy/`.

**RED-first** (`tests/unit/test_maker_promotion_report.py`): `test_any_false_gate_is_no_proposal`, `test_report_refuses_before_read_date`, `test_second_read_refuses_overwrite`, `test_report_never_writes_under_deploy_or_imports_settings` (AST), `test_g1_reports_point_and_lower_bound_separately`, `test_g3_uses_conservative_of_t_and_block_bootstrap`, `test_g8_false_without_s4_cancel_on_stop_evidence`, `test_inconclusive_adverse_selection_is_gate_false`.

**Completion:** merged, with one PROPOSAL fixture and one NO_PROPOSAL fixture.

### WP5 — PREREG, checker, tally, progress (frozen before `holdout_start_date`; ~6 h)

**`docs/evidence/maker/PREREG.json`** (pattern `docs/evidence/m1v3/PREREG.json`). Fields:

| Group | Fields |
|---|---|
| Identity | `hypothesis`, `spec_sha256`, `family_id`, `manifest_sha256`, `params` (= `config.py`), `stations` |
| Dates and windows | `holdout_start_date` (calendar date; a rest counts only if climate_day ≥ it **and** rest ts > frozen commit time, PM #12); `calendar_cap_date` (calendar date, §8); `revision_budget: 0` (a change is a new PREREG version file); `dev_set: "Stage 0 2026-08-30..<last censused>, exploratory, seen"` |
| Read target | `read_target`: holdout positions ≥ 300 (= 200 × the spec's deff ceiling of 1.5) **and** station-days ≥ 200, counted outcome-blind; read on the first date this holds with truth FINAL or past D+14, else on `calendar_cap_date` |
| Power stop | `power_stop`: day 60 of the holdout, `power_projection` < `read_target` at the cap → `INCONCLUSIVE_UNDERPOWERED` |
| Clustering | `cluster_unit_primary: "7-day calendar block"`, `cluster_unit_reported: "climate_date"`, `bootstrap_B: 100000`, seed |
| α | `alpha_family` from the WP0 ledger dry call; G3 one-sided at `alpha_family`; no Holm (one holdout p-value, PM #5b) |
| Sequential stop | `S_k = Σ(win−BE)/sqrt(1.5·Σ BE(1−BE))`. Variance inflated by the pinned deff ceiling (outcome-blind, cluster-aware; PM #7a). `BE_i = b_i + fee_i`. Harm iff `S_k ≤ b_fut` from `boundary_for` at α_stop = 0.025. α_stop is a type-II/calendar device, not drawn from RA-13 (PM #5c). Looks every 10 positions ordered by `(settlement_ts, climate_day, station, rung_id)`. `n_max` = projected positions at the cap. Output is CONTINUE/STOP only |
| Adverse selection (§6.9 as non-inferiority, PM #3) | Pooled over strata. PASS iff the upper one-sided 95% block-bootstrap bound of (filled loss rate − mean model p_YES) ≤ `as_margin` **and** the model-expected losses ≥ 10. Otherwise `INCONCLUSIVE`. Filled-vs-unfilled gets the same form; strata are report-only. `as_margin` is pinned from spec v0.3 |
| Other rules | `voids_rule`, `unresolved_rule` (= LOSS), `incomplete_day_rule` (up-windows), `leakage_operator: "available_at_ns <= decision_ts visible"`, `stress` (gated list), `baselines` (units, min n 30, report-only), `gates` (nine rows, thresholds as in WP4) |
| Disclosures | `b3_disclosure`; `season_note` (holdout spans winter–summer 2027; calibration artefact dated 2026-09-30 and frozen); `frozen_sha`; `status: FROZEN` |

**Tools:** `scripts/analysis/maker_prereg_check.py` (reuses `check_frozen_blob`/`_canonical`; equality with `config.py`; `holdout_start_date` > last Stage 0 truth date + 2 days, a purge longer than a position's life, PM #9); `maker_sequential_tally.py` (writes only `{look_n, t, verdict}`); `maker_progress_report.py` (counts, `power_projection`, days to cap; no outcome field).

**RED-first tests**

| File | Tests |
|---|---|
| `tests/unit/test_maker_prereg_check.py` | `test_param_mismatch_with_config_refuses`, `test_frozen_sha_must_introduce_blob`, `test_split_is_calendar_dates_not_fraction`, `test_revision_budget_nonzero_refuses` |
| `tests/unit/test_maker_sequential_tally.py` | `test_harm_uses_b_fut_and_output_has_no_rate`, `test_variance_inflated_by_pinned_deff`, `test_looks_ordered_by_settlement_ts_with_deterministic_ties` |
| `tests/unit/test_maker_progress_report.py` | `test_no_outcome_field_before_read_date`, `test_power_stop_fires_from_counts_only` |

**Completion:** PREREG committed as its own reviewed commit and gated like code (read the gate EXIT before any push); the checker exits 0; the manifest `d0_climate_day` equals `holdout_start_date`.

### WP6 — Start the shadow run (ops; ~3 h, then the calendar clock)

1. Only after WP0 item 5 shows nothing broken, and with orders off (drop-in untouched, no allowlist row): set `BREEZY_SENDING_FAMILY_ID=pm_us_no_ladder_maker_v1` as a reviewed supervisor-unit edit (on a branch until gates pass); restart the supervisor in 01:00–16:40Z.
2. **Boot health check** (replaces the r1 WS STOP). Node log must show: maker composition line; `SHADOW_BOOT`; `subscribed_slug_count` covering every listed maker slug; zero `silent_subscriptions` for maker slugs; the fee-drift-probe registration line; **no** live-orders/permit-mint line for the maker. Any miss → roll back the env edit and report.
3. **Timers.** `breezy-maker-shadow-score.timer` (scorer, progress, tally) with `RuntimeMaxSec`, `MemoryMax`, a no-progress event, subset benchmark first; outside the nightly study window.
4. **Liveness** = process + log mtime + JSONL advancing + tape advancing; LIVE only after the first scheduled success is seen.

**Completion:** first success seen, plus 7 days with decode errors = 0, leakage = 0 and parity mismatch ≤ 0.01. Then wait for the read, a stop, or the power stop.

## 6. Data and tooling dependencies

| Input | Path | Status |
|---|---|---|
| Depth10 + trade-print tape | quote-tape catalog under `~/.local/share/breezy/catalog` | exists; census after 2026-09-25 is S1's |
| Settlement truth | `~/.local/share/breezy/derived/settlement-truth/settlement_truth.parquet` | exists |
| NBP derived store (WP0 coverage) | `persistence/nbp_derived_store.py` partitions | exists |
| Calibration artefact | `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` | exists; tail calibration **UNVERIFIED** (S2 is the only evidence) |
| S2 simulator / S3 artefact | `scripts/analysis/<S2>` / `docs/evidence/maker/A1_REACHABILITY_*.md` | **UNVERIFIED** until WP0 |
| Shadow JSONL | `~/.local/share/breezy/maker_shadow/` | WP2 |

## 7. Risks and invariant guards

| # | Risk | Invariant | Guard |
|---|---|---|---|
| R-1 | Maker path sends or cancels a real order | NO-SEND / live enablement | package-wide AST ban (WP2); no allowlist row; orders-off drop-in kept; exec firewall tests in every focused list |
| R-2 | Widened exact-sets read as relaxed | L-12 | one row per set; equality asserts |
| R-3 | `allow_short` drift | allow_short False | config default test; NO bought as the NO instrument; `decide` never emits a sell |
| R-4 | Shadow counts positions live would refuse | gate-5 honesty | structural limits in `decide`; causal fill state in the replay; WP0 item 4 / S-2 on exclusive grouping |
| R-5 | Holdout peeked | read-once | counts-only progress; CONTINUE/STOP tally; `power_projection` field test |
| R-6 | RA-13 B-3 tape reads | RA-13 firewall | PREREG `b3_disclosure`, accepted in review before freeze |
| R-7 | Operator caps touched | reserved controls | G8 reads node-log evidence only; test that no maker file references `operator_max_*` |
| R-8 | PREREG edited or date moved | frozen PREREG | introducing-commit check; a change is a fork |
| R-9 | Exec client reformatted | exec byte pin | format only own files; stray check |
| R-10 | Silent stalls | ops | RuntimeMaxSec, no-progress event, subset benchmark |
| R-11 | Sending-family switch silently breaks an FQ or M1-v3 consumer | — | WP0 item 5; any "broken" consumer means STOP |
| R-12 | Shadow restart semantics diverge from live S4 | evidence validity | cancel-on-stop pinned here; G8 false otherwise |

## 8. Sample clock (stated, by calendar date)

These are inputs to the feasibility rule (E1) and to `calendar_cap_date`.

**Rate per day.** Rested rung-days/day ≈ 4 stations × 0.91 listed × 2 rungs × `c`, where `c` is the WP0 coverage factor (≈ 1 if D−1 resting dominates; it falls if D−1 windows are short). With c = 1, 7.3 rested rung-days/day; station-days with ≥ 1 position = 3.64 × (1 − (1 − r)²).

Start 2026-11-23 is an assumption (freeze after S1–S4 entry evidence); dates shift 1:1 with it.

| Fill rate r | Positions/day | Station-days/day | Days to 300 positions | Days to 200 station-days | Binding days | Read ≈ (start 2026-11-23) |
|---:|---:|---:|---:|---:|---:|---|
| 0.10 | 0.73 | 0.69 | 411 | 290 | **411** | 2028-01 (beyond any cap) |
| 0.25 | 1.82 | 1.59 | 165 | 126 | **165** | 2027-05-07 |
| 0.50 | 3.64 | 2.73 | 83 | 74 | **83** | 2027-02-14 |

**`calendar_cap_date`** = `holdout_start_date` + ceil(binding days at `r_lo`) + 14 truth days, pinned as a calendar date at freeze. If that lands after 2027-11-30, E1 fails (S-1) and nothing is frozen. In effect E1 needs `r_lo` ≳ 0.2.

**2027-01-25 horizon** (NO-TRADE review / RA-13 KILL backstop): no row reads before it; the earliest plausible read (r = 0.5) is mid-Feb 2027; the day-60 power stop (~2027-01-22) is the only S5 output before it and carries no outcome. The M1-v3 read (≥ 2026-12-07) falls inside the run; independent.

## 9. Effort and evidence artefact

Build: WP0 3 h · WP1 6 h · WP2 9 h · WP3 10 h · WP4 6 h · WP5 6 h · WP6 3 h + ≈ 8 h reviews/gates = **≈ 51 agent-hours**; calendar per §8. Single evidence artefact: `docs/evidence/maker/S5_PROMOTION_GATE_REPORT.{md,json}` (or the §1 STOP/INCONCLUSIVE file on an early end).

## 10. Spec v0.3 inputs (not fixed here; for the coordinator)

1. §3/§4: the 2-rung stacking conflicts with `exclusive_bucket_conflict` if sibling NO legs share `event_key` (`risk.py:433-442, 517-530`). Rule one of: 1 rung per station-day, or a reviewed `allow_overlapping_exclusive_yes=True` for this family.
2. §3 wording, "latest vector whose climate_day == S.day". The implementation uses `value_at` (latest overall) and abstains on mismatch. That is stricter when a newer cycle targets the next day while an older same-day vector is under 6 h old. Align the wording, or accept the stricter rule.
3. §6.2/§6.3: replace the 60/40 split and the 3 revisions with calendar `holdout_start_date`/`calendar_cap_date` and zero planned revisions (changes are forks). §7.4 then becomes "revisions = 0, α = ledger allocation", with no Holm.
4. §6.4: read target = 300 positions (200 × deff ceiling 1.5) and 200 station-days, outcome-blind. Gate 2 uses the realised effective n.
5. §6.5: unresolved past D+14 = LOSS in the primary calculation; void = refund minus fee (refund 0 until verified); CLI FINAL wins conflicts.
6. §6.6: baseline units (per eligible rung-day and per deployed capital), minimum n 30, and whether "beat both" is a gate. The plan treats it as report-only.
7. §6.7: by-month is report-only; the gated stresses are point estimates; name which stresses re-decide.
8. §6.9: non-inferiority form, `as_margin`, the minimum of 10 expected losses, and pooled strata.
9. §7.3: the CI level is one-sided at `alpha_family` with 7-day block clusters, not a "95% CI". Climate-date clusters are reported.
10. §7.6: the leakage operator is `available_at_ns <= decision_ts` visible (`forecast_state.py:321`), not "issue time < decision time".
11. §4: the sequential-stop variance carries the 1.5 deff inflation; α_stop is outside the RA-13 spend; looks are ordered by settlement ts.
12. §6.1: "partial fills aggregate" is moot at qty 1; delete it.
13. Restart contract: cancel-on-stop is the behaviour S4 must implement for the shadow evidence to transfer.

## 11. Open questions for peer review (max 5)

1. Is the 1.5× fixed variance inflation for the harm stop adequate, or should it use a running 7-day-block variance once there are ≥ 8 blocks?
2. Does `as_margin` derive from economics (e.g. half the mean p_NO − BE slack over filled bids, which is outcome-blind) or get pinned as a constant in v0.3?
3. If WP0 shows the D−1 resting coverage `c` ≪ 1 because of the 6 h age rule, is relaxing the age limit a spec change before freeze (allowed, blind to S5) or out of scope?
4. Is 7-day the right block length, given 2–5-day heat-event persistence?
5. Must the replay–live parity threshold (≤ 0.01) be tighter, given that parity is the only check that the replay describes the live strategy?

## 12. Review disposition

| Review | # | Disposition |
|---|---|---|
| architect | 1 MAJOR | ACCEPTED: §4 forecast row, WP1 `decide` (mismatch abstain, age from `available_at`, `<=`), WP0 item 3 coverage table, §8 `c` factor. D-day is dropped by mismatch, with no per-day accessor |
| architect | 2 MAJOR | ACCEPTED: WP2 BOOT/STOP + cancel-on-stop contract; WP3 step 1 + `test_rest_spanning_node_downtime_…`; G8 ties to S4 |
| architect | 3 MAJOR | ACCEPTED: WP2 `set_time_alert` for 09:00 LST and expiry; WP3 step 2 clamp; RED tests |
| architect | 4 MAJOR | ACCEPTED: no `evaluate_order`; limits in `decide` + `RefusalCounter`; WP0 item 4 + S-2 (grouping rule verified at `risk.py:433-442`) |
| architect | 5 MAJOR | ACCEPTED: r1 S-2 removed; WP6 boot health check; FQ YES-slug shape + RED test |
| architect | 6 MAJOR | ACCEPTED: S4 removed from entry; G8 |
| architect | 7 MINOR | ACCEPTED: package-wide AST ban list; `shadow_only` field dropped |
| architect | 8 MINOR | ACCEPTED: WP0 item 5; `current_yes_instrument_slug`; boot fee-probe line |
| architect | 9 MINOR | ACCEPTED: WP2 halt row + comment amendment; not in `KINDS_WITH_EXIT_PATH` |
| architect | 10 MINOR | ACCEPTED: `<=` throughout; spec input 10 |
| architect | 11 MINOR | ACCEPTED: single `maker_eval_stats.py`; explicit `CriterionRow` fields |
| architect | 12 MINOR | ACCEPTED: G8 uses S3 sha + node-log evidence; no operator env read |
| architect | 13 MINOR | ACCEPTED: sha `47d1b94c` recorded and re-checked in WP0 |
| architect | mismatches | FIXED: `FamilyManifest` :214, `_refuse_overwrite` :780, the NO-leg subscribe path |
| pm-reviewer | 1 BLOCKER | ACCEPTED: calendar `holdout_start_date`/`calendar_cap_date`, `revision_budget: 0`, forks only (WP5, §8) |
| pm-reviewer | 2 MAJOR | ACCEPTED: E1 feasibility rule on the stressed `r_lo`; day-60 power stop; `INCONCLUSIVE_UNDERPOWERED` label |
| pm-reviewer | 3 MAJOR | ACCEPTED: pooled non-inferiority, minimum expected losses, INCONCLUSIVE = gate false |
| pm-reviewer | 4 MAJOR | ACCEPTED: causal offline replay with fill state (§3, WP3 step 2); partial-fill clause dropped |
| pm-reviewer | 5 MAJOR | ACCEPTED: (a) G3 method pinned; (b) no Holm; (c) α_stop outside RA-13; (d) E5 dry call |
| pm-reviewer | 6 MAJOR | ACCEPTED: `SHADOW_FORECAST` logs the full vector + θ; per-stress re-decide/re-cost; by-month report-only |
| pm-reviewer | 7 MAJOR | ACCEPTED (a)(b)(c): deff-inflated variance, `b_fut`, ordered looks, no revisions. (d) Stop KEPT: spec §4 declares it binding, and it costs one small script. Dropping it is a spec decision |
| pm-reviewer | 8 MAJOR | ACCEPTED: unresolved = LOSS, void = refund − fee, CLI wins, up-window `incomplete_day_rule`, G7 coverage 0.90 |
| pm-reviewer | 9 MAJOR | ACCEPTED: 7-day block primary, climate-date reported, purge > position life, season note |
| pm-reviewer | 10 MAJOR | ACCEPTED: units pinned, `NOT_COMPARABLE` at n < 30; gate-vs-report goes to the spec (input 6) |
| pm-reviewer | 11–13 MINOR | ACCEPTED: age from `available_at` (and S2 must use the same rule; recorded in E4); rest ts > frozen commit time; G4/G6 machine values |
| pm-reviewer | mismatches | FIXED: `check_freeze_introduction` is in `no_longshot_pooled_test.py:423`; `scoring_core.percentile_interval` imported explicitly |

**Conflicts between reviewers.**
- On the sequential stop, PM #7d leans toward dropping it. It is kept for spec §4 fidelity, at negligible cost.
- On fill feedback, the architect's "simplest path" and PM #4 are reconciled by the offline causal replay, which needs no in-node simulator.

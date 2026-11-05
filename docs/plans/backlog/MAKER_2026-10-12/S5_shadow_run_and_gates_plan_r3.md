# S5 — Prospective shadow run, evaluation and promotion-gate tooling

| Field | Value |
|---|---|
| ID | S5 |
| Revision | r3 (conformance revision of r2; folds `reviews/S5-r2-final.md`) |
| Date | 2026-10-12 |
| Status | READY |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` **spec v0.3**. Constants (`P_MIN` 0.94, `B_CAP` 0.80, `E_MIN` 0.10, `B_FLOOR` 0.70, `STALE_H` 8, `MAX_RUNGS` 2 conditional / 1 fallback, `CANCEL_LST` 09:00) live in `config.py` only; the PREREG checker requires equality with the spec |
| Ruling context | T2 route of `docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md`. The NO-TRADE ruling stays in force throughout S5 |

**Invariants (binding on every WP).** Nautilus immutable (subclass `Strategy`; native clock and order factory only). `allow_short` stays `False`. Never weaken/delete a safety, settlement, contract or NO-SEND egress test; exact-sets are WIDENED by one reviewed row (L-12). Never assign an operator cap; never touch live enablement or `BREEZY_ORDERS_ENABLED` (orders-off drop-in untouched). Never edit a frozen PREREG or move a pre-registered date. Stage 0 is exploratory, never promotion evidence. Worktrees: `PYTHONPATH=<wt>/src`; no `uv`/`pip`/`git stash`; full gate after every merge, `--basetemp` under `~/.cache`, `rm` after reading EXIT; `lint-imports` from the tree root; one heavy job at a time; stall watch on long jobs.

## 1. Goal state (acceptance test)

S5 is done when exactly one of these exists, produced by the bot's tooling (never by Claude arithmetic):

- **PASS.** `docs/evidence/maker/S5_PROMOTION_GATE_REPORT.{json,md}`: the holdout read once, all nine `CriterionRow`s true, `assemble_outcome` returns `PROPOSAL`. The report arms nothing (`render_rationale` prints "never arms", `analysis/promotion_criteria.py:651`). Activation stays manual and outside S5.
- **FAIL / STOP.** The same report with `NO_PROPOSAL` naming the failed gates; or `S5_A1_STOP_<date>.md` (the spec §4 loss stop fired); or `S5_ADVERSE_SELECTION_FAIL_<date>.md` (§6.9 FAIL, terminal); or `S5_INCONCLUSIVE_UNDERPOWERED_<date>.md` / `S5_UNSCREENED_TERMINAL_<date>.md` (outcome-blind day-60 power stops; not refutations, still no PROPOSAL).

On the way: family code + a REGISTERED SHADOW manifest with no `live_orders_ruling`; `docs/evidence/maker/PREREG.json` frozen (introducing commit an ancestor of HEAD) **before** `holdout_start_date`; a daily counts-only progress file.

## 2. Entry criteria and STOP conditions

| # | Entry criterion (WP0 records evidence) | Evidence |
|---|---|---|
| E1 | S2 Stage 0 verdict **NOT-KILLED or NOT-KILLED-UNSCREENED** (spec §6.0; Stage 0 never emits GO). Explicitly: base fill rate ≥ 0.10 **and** stressed (2 × (size ahead + 1)) fill rate `r_lo` ≥ 0.10, denominator = all covered bid-bearing station-days, §6.9 not FAIL. UNSCREENED suffices because G9 re-screens on the holdout. Plus the §8 feasibility rule at `r_lo` | `docs/evidence/maker/STAGE0_REPLAY_*.md` |
| E2 | S3 PASS: A1 floor not `unreachable_veto` for the maker mix at the stressed fill rate; S3 artefact pins `(c, t_min, α_floor)` and the deff-1.5 variance inflation | `docs/evidence/maker/A1_REACHABILITY_*.md` |
| E3 | `TRADE_QUANTITY_UNIT` resolved or bracketed; YES-BUYER→NO print inversion pinned (S1) | S1 evidence file |
| E4 | §6.1 fill simulator importable and unit-tested against spec v0.3 §6.1 (price-priority trade-through, Q₀ reduced by better-priced BUYER prints, episodes, gap subtraction, marketability guard); signature recorded; S2 used the identical `STALE_H` 8, age-from-`available_at` and climate-day-match rule | path + sha |
| E5 | `register_hypothesis` (`analysis/hypothesis_ledger.py:873`) returns a registered record (not `UNDERPOWERED_NOT_REGISTERED`, :226) for this design, by a pure dry call against the current ledger records | WP0 note |

S4 (exec resting path) is not an entry criterion: the shadow never submits. It is gate G8 (§5 WP4).

**STOP conditions.**

| ID | Trigger | Outcome |
|---|---|---|
| S-1 | Any entry criterion unmet | Do not start; build nothing ahead of it |
| S-2 | WP0 item 4 / WP2 admission test: the reviewed per-family exclusive-conflict admission for sibling NO legs is refused or its test cannot be made green | **Not a stop.** `MAX_RUNGS` = 1 in `config.py`; the PREREG pins 1; §8 uses the MAX_RUNGS = 1 rows (clock doubles); E1 feasibility re-checked at `r_lo` on those rows |
| S-3 | The A1 loss floor fires on the station-day clock (spec §4; the only loss stop) | STOP; `S5_A1_STOP_<date>.md` |
| S-4 | Holdout read, any gate false | `NO_PROPOSAL` |
| S-5 | Day-60 outcome-blind power check: projected holdout positions or station-days at `calendar_cap_date` below the read target, or `calendar_cap_date` reached first | `INCONCLUSIVE_UNDERPOWERED`; the run ends; the cap is never extended |
| S-5b | Same day-60 check (spec §6.9): projected **pooled** expected losses m = Σ model p_YES over filled episodes (fills from tape, no outcome) cannot reach 10 by `calendar_cap_date` | `UNSCREENED-TERMINAL`; the run ends; `S5_UNSCREENED_TERMINAL_<date>.md` |
| S-6 | §6.9 FAIL at the read | Terminal for the hypothesis as stated (spec §6.9); `S5_ADVERSE_SELECTION_FAIL_<date>.md` |

There is no plan-owned sequential stop. The r2 Wilson-style `S_k` tally is deleted (spec §4: two stops would need two reachability proofs).

## 3. Simplest direct path

1. One `composition_kind`, `no_ladder_maker`: a thin Nautilus `Strategy` around a pure `decide()`. It never submits or cancels; it logs `SHADOW_BOOT`/`SHADOW_STOP`, a `SHADOW_FORECAST` line per vector (full quantile vector, `available_at_ns`, `climate_day`, θ, fee coefficient) and a `SHADOW_DECISION` per rest/cancel/abstain (with the would-be GTD `expire_time`), to the node log and a JSONL sink. Native `clock.set_time_alert` drives the 09:00 LST cancel, the forecast expiry at `available_at + STALE_H`, and the synthetic permit expiry.
2. **The scored sample is an offline causal replay, not the live log.** One scorer replays the same `decide()` over the recorded Depth10/trade tape, using the live-logged (PIT) vectors, the node up-windows (BOOT→STOP), the synthetic permit windows, and §6.1-simulator fill state, so a filled rung stops resting and counts toward `MAX_RUNGS` and the 8-rest cap. The live JSONL is the PIT forecast record plus a parity check (→ G7).
3. Statistics reuse `scoring_core`; the loss stop reuses the A1 clock (`fq_loss_stop_core`/`fq_loss_stop_clock`) exactly as S3 parameterises it; gates reuse `assemble_outcome`.
4. **Zero planned revisions** (spec §6.3). Stage 0 is the only development set. Every shadow day from `holdout_start_date` is holdout. Any change is a fork: a new PREREG version with its own start date and α allocation.

**Not built:** AUT-2/AUT-5b; `hypothesis_triage` dashboard; `BacktestEngine`/`FillModel` (cannot express §6.1: YES-leg prints, price-priority queue vs displayed NO size, no `NO_AGGRESSOR` credit); an in-node fill simulator; a per-climate-day forecast accessor (§4); `RiskManager.evaluate_order` in shadow (nets against a portfolio shadow never populates, `risk.py:572-646`); any second loss stop.

## 4. Nautilus null-hypothesis check

| Need | Native / existing (evidence) | Verdict |
|---|---|---|
| Lifecycle, subscriptions | `Strategy` subclass; FQ precedent subscribes the YES slug and registers the NO book via the sibling (`strategy/forecast_quantile_ladder/strategy.py:356-361`) | REUSE the FQ shape |
| Timed cancels | `Clock.set_time_alert(name, alert_time, callback)` (`nautilus_trader/common/component.pyx:71,104`) | REUSE; no new scheduler |
| Would-be order | `Strategy.order_factory.limit(..., time_in_force=GTD, expire_time=…, quantity=1)`, built and logged, never submitted | REUSE |
| Family dispatch / manifest | `_compose_family` (`app/trade.py:929-978`); `FamilyManifest` (`persistence/family_manifest.py:214`), `parse_family_manifest` (:300), `_COMPOSITION_KINDS` (:119) | EXTEND: one kind (WIDENED row) |
| Forecast vector | `ForecastQuantileState.value_at` (`strategy/ladder_ev/forecast_state.py:310-325`), visibility `available_at_ns <= now_ns` (:321), climate-day-blind; vector carries `climate_day`, `available_at_ns` (:281-298) | REUSE; `decide` abstains `forecast_day_mismatch` (spec §3) |
| p(rung) | `load_live_calibration` (`forecast_quantile_ladder/calibration_artefact.py:236`), `ArtefactBoundsProvider` (`artefact_bounds.py:38`) | REUSE; one pure `p_no_for_rung` adapter |
| Halt | family-halt row per `family_id` (`current_rung_hold/family_id_arg.py:17-22`) | REUSE via `decide(halted=…)`; kind in `HALTABLE_COMPOSITION_KINDS` (:20), not `KINDS_WITH_EXIT_PATH` (:30) |
| Fee probe | `_build_fee_drift_probe` via `current_yes_instrument_slug()` (`app/trade.py:312-334`) | REUSE |
| Structural limits | `RiskLimits` (`weather_common/risk.py:181`, `allow_short` :224, `allow_overlapping_exclusive_yes` :225); `RefusalCounter` (`refusals.py:123`) | REUSE; pure checks in `decide` |
| Exclusive grouping | `mutually_exclusive_group` = same `event_key` (`risk.py:433-442`); `exclusive_conflict` returns False when `limits.allow_overlapping_exclusive_yes` (:523-524), else refuses a positive delta when a group member is held (:525-530) | The per-family admission is this existing flag on the maker's `RiskLimits` (WP2), reviewed and test-verified (spec §3) |
| Loss stop (A1) | `normalise_station_day(station, buys: BuyFill…, settlements: LegSettlement…)` (`analysis/fq_loss_stop_core.py:153`; `BuyFill` :58, `LegSettlement` :85); `step_clock` (`analysis/fq_loss_stop_clock.py:114`, a tick iff variance > `VARIANCE_EPS`); `first_crossing(increments, c, t_min)`, crossing iff `S_t < −c√t` (:99-111) | REUSE through S3's parameterised entry point; S5 builds no stop maths |
| Statistics | `LeakageError` :34, `ClusterCI` :176, `bootstrap_cluster_draws` :216, `percentile_interval` :246 (`analysis/stats/scoring_core.py`; import explicitly) | REUSE |
| Gate assembly | `CriterionRow` :95, `assemble_outcome` :613, `render_rationale` :640 (`analysis/promotion_criteria.py`) | REUSE with explicit fields |
| Freeze / read-once | `check_frozen_blob`, `_canonical` (`scripts/analysis/prereg_precommit_check.py:340,323`); `check_freeze_introduction` :423, `_refuse_overwrite` :780, `_preflight_inputs` :875 (`scripts/analysis/no_longshot_pooled_test.py`, sha `47d1b94c`, re-recorded in WP0) | REUSE by import |
| Win rate / drawdown / PF / exact AS test | `portfolio_roi_report.py` keyed on `DurableFillRecord`; shadow has none | MISSING: one small stats module |

**Built here:** `decide` + strategy, `p_no_for_rung`, the JSONL sink, the replay scorer, one stats module, the report, the PREREG checker and the progress report (which hosts the A1 stop check).

## 5. Work packages

All WPs: focused tests first, keeping the RED→GREEN output. Every focused list includes the exec import pin, the NO-SEND egress tests, `test_shadow_only_false_is_only_the_gate_output.py`, `test_autonomy_*`, the import gates and the citation map. Then the full gate (`scripts/ci/run_tests_no_egress.sh`) and `lint-imports` ("N kept, 0 broken"). `ruff format` on touched files only; `git status` stray check before every commit.

### WP0 — Entry verification and pre-freeze facts (no code; ~3 h)

Write `docs/evidence/maker/S5_ENTRY_<date>.md` with:

1. E1–E5 evidence paths and shas, the S2 simulator signature, the S3 `(c, t_min, α_floor)` and its evaluator entry point, the imported sha of `no_longshot_pooled_test.py`.
2. **E5 dry call**: record `alpha_family` and the outcome.
3. **Resting coverage table (outcome-blind).** From the NBP derived store's `(available_at_ns, climate_day)` rows 2026-09-01..freeze−1: per (station, ladder day D vs D−1, UTC hour), hours where a vector targeting the ladder's day is visible, age ≤ `STALE_H` (8 h), inside a permit window (boot + permit TTL), and before 09:00 LST. Emit the coverage factor `c` used in §8. The permit TTL is read from the live permit module by codegraph (spec says 10 h), never retyped.
4. **Exclusive grouping on NO legs.** How `MispricingContract.event_key` is formed for two NO legs of one ladder. If shared, the second NO rung needs the admission (WP2 test). The coordinator obtains the review; a refusal triggers S-2 (MAX_RUNGS = 1), never a halt.
5. **`BREEZY_SENDING_FAMILY_ID` switch effects** (enumerate, verify, mark retired/broken): FQ-only `FqDecisionFunnelActor`, F6 FQ-BRIDGE veto and `FQ_VECTOR_COMPLETE`/NBP markers parsed by `analysis/capture_node_log_markers.py` (consumers `nbp_shadow_parity.py`, `fq_loss_taxonomy_logs.py`, funnel digest, F13/AUT jobs); fq_v1 halt row/timers; fee probe via `current_yes_instrument_slug()` (`app/trade.py:312-334, 428-436`); `LIVE_OBSERVATIONS=1` (`runtime/settings.py:865-872`); `replay_daily_runner._SUPPORTED_COMPOSITION_KINDS` (`scripts/analysis/replay_daily_runner.py:945-947`); `autonomy/resolver.py`; M1-v3 forward-screen inputs. Any "broken" consumer is a STOP until rehomed.
6. Reuse of the `StationObservation` interval for the integer-°C widening, from the CRH precedent test.

**Completion:** committed with GO or a named STOP. Spec defects go to the coordinator; never edited here.

### WP1 — Pure decision core (~6 h)

Create `src/breezy/strategy/no_ladder_maker/{__init__,config,rung_probability,decision}.py`.

```python
# config.py — the only home of spec constants (PREREG checker imports them)
P_MIN, B_CAP, E_MIN, B_FLOOR, TICK, CANCEL_HOUR_LST, STALE_H, MAX_RUNGS, MAX_SIMULTANEOUS, ORDER_QTY
class NoLadderMakerConfig(StrategyConfig, frozen=True): allow_short: bool = False
# rung_probability.py
def p_no_for_rung(*, bounds: RungBounds, rung: Rung) -> float            # 1 - P(high in [A,B] inclusive)
# decision.py
@dataclass(frozen=True) class Rest:    station, climate_day, rung_id, instrument_id, bid, p_no, fee_est, best_no_bid,
                                       best_no_ask, displayed_no_bid_size_at_or_above, expire_time_ns,
                                       forecast_available_ns, forecast_climate_day
@dataclass(frozen=True) class Cancel:  ..., reason: Literal["cancel_hour_lst","obs_within_one_rung","forecast_stale",
                                       "p_no_below_min","below_floor","replace","permit_expiry","node_stop","halt"]
@dataclass(frozen=True) class Abstain: station, climate_day, reason: str   # forecast_day_mismatch, halted, cap_reached, marketable
def decide(*, now_ns, station, climate_day, std_utc_offset_hours, ladder, vector: ForecastQuantileVector | None,
           p_no_by_rung, no_book, obs_interval_f, resting: Mapping[str, Decimal], filled: frozenset[str],
           open_positions_total: int, permit_expires_ns: int, fee_coefficient: float, halted: bool,
           ambiguous_intent_open: bool, refusals: RefusalCounter) -> tuple[Rest | Cancel | Abstain, ...]
```

Rules (spec v0.3 §3):
- `vector.climate_day != climate_day` → Abstain `forecast_day_mismatch` and Cancel any rest on S.
- Age = `now_ns − vector.available_at_ns`; > `STALE_H` (8 h) → Cancel `forecast_stale` for all bids on S.
- Leakage refused iff `vector.available_at_ns > now_ns` (`<=`-visible, `forecast_state.py:321`).
- `bid = min(b_max, best_bid + TICK, no_ask − TICK)`; never cross; `bid < B_FLOOR` → Cancel `below_floor`. No bid below 0.70 is ever emitted.
- `expire_time_ns = min(S.day 09:00 LST, permit_expires_ns, end of booking UTC day)` (GTD).
- At most `MAX_RUNGS` rungs (the two lowest-p_YES that pass P_MIN, never adjacent to the modal rung); `filled` rungs count toward it and are never re-rested.
- `open_positions_total + resting ≥ MAX_SIMULTANEOUS` (8) → Abstain `cap_reached`; every structural refusal recorded in `refusals`.

**RED-first** tests in `tests/strategy/no_ladder_maker/test_decision.py`: `test_rung_below_p_min_cancels_and_never_rests`, `test_bid_is_min_of_b_max_best_bid_plus_tick_and_ask_minus_tick`, `test_bid_never_crosses_no_ask`, `test_empty_no_bid_side_rests_at_b_max_without_implied_price`, `test_bid_below_floor_cancels_never_rests_sub_0_70`, `test_at_most_max_rungs_and_never_adjacent_to_modal`, `test_max_rungs_one_config_rests_single_rung`, `test_cancel_at_0900_lst_per_station_offset`, `test_gtd_expire_is_min_of_lst_permit_and_utc_day_end`, `test_integer_celsius_observation_widens_to_full_ambiguity_band`, `test_price_change_is_cancel_replace_with_new_t0`, `test_halt_or_ambiguous_intent_abstains_whole_station_day`, `test_inclusive_band_edges_match_bucket_facts_from_instrument_id`, `test_vector_for_other_climate_day_abstains_and_cancels`, `test_forecast_older_than_stale_h_8_cancels_all_bids`, `test_forecast_age_measured_from_available_at_not_cycle_runtime`, `test_vector_available_at_equal_to_now_is_visible_and_later_is_leakage`, `test_filled_rung_is_not_rerested_and_counts_toward_cap`, `test_simultaneous_cap_abstains_and_records_refusal`, `test_allow_short_false_never_produces_a_sell`; plus `test_forbidden_imports.py::test_decision_imports_no_settlement_or_pnl`.

**Gate:** `pytest tests/strategy/no_ladder_maker` plus `lint-imports`. **Completion:** green, no edit outside the package.

### WP2 — Strategy, composition, manifest, rung admission (SHADOW; ~9 h)

**Create**
- **`strategy.py` — `NoLadderMakerStrategy(Strategy)`.** FQ subscription shape. On book/vector/obs events calls `decide` with `filled=frozenset()` (the replay supplies fills). `clock.set_time_alert` per (station, D) at 09:00 LST, per vector at `available_at + STALE_H`, and at the synthetic permit expiry (boot + permit TTL, WP0 item 3); each callback runs `decide` for that station. `on_start` → `SHADOW_BOOT {node_instance_id, ts, sha, permit_expires_ns}`; `on_stop` → `SHADOW_STOP` + `Cancel(node_stop)` for every would-be rest (**cancel-on-stop restart contract**; a relaunch re-posts as a new episode). Each vector → `SHADOW_FORECAST` (q10..q90, mean, sd, `available_at_ns`, `cycle_runtime_ns`, `climate_day`, θ, fee coefficient). Builds `order_factory.limit(..., GTD, expire_time, 1)` for the log only; exposes `current_yes_instrument_slug()`.
- **`shadow_sink.py` — `ShadowDecisionJsonlSink(output_dir)`**: append-only, one file per UTC day, `catalog_root.parent / "maker_shadow"`.
- **`composition.py` — `build_no_ladder_maker_strategies(...)`**, building the family `RiskLimits` with `allow_short=False` and, iff MAX_RUNGS = 2, `allow_overlapping_exclusive_yes=True` (the reviewed admission).
- **`deploy/families/pm_us_no_ladder_maker_v1.json`**: `d0_climate_day` = `holdout_start_date`; stations LAX, MDW, MIA, SFO; no `live_orders_ruling`, no `exit_rule`.

**Modify** (each change one reviewed WIDENED row): `persistence/family_manifest.py:116-121` (kind); `app/trade.py:929-978` (`no_ladder_maker` branch reusing `_open_halt_latch_preamble` and `_build_fee_drift_probe`, never `live_orders_authorized`); `persistence/autonomy/paths.py:28`, `strategy/autonomy/node_plugins.py`, `analysis/autonomy/offline_plugins.py` (`RefusingPlugin` parity rows, `tests/unit/test_autonomy_plugins.py:197-209`); `strategy/current_rung_hold/family_id_arg.py:17-22` (kind in `HALTABLE_COMPOSITION_KINDS`, comment amended: honoured via `family_halt_submit_veto` *or*, for a non-submitting kind, `decide(halted=…)`).

**RED-first tests**

| File | Tests |
|---|---|
| `tests/unit/test_family_manifest.py` | `test_no_ladder_maker_kind_loads_and_unknown_kind_still_refused` |
| `tests/unit/test_no_ladder_maker_composition.py` | `test_compose_family_dispatches_no_ladder_maker`, `test_maker_branch_never_calls_live_orders_gate`, `test_maker_manifest_with_live_orders_ruling_refuses_boot`, `test_fee_drift_probe_registers_for_maker`, `test_maker_limits_admit_second_no_leg_of_one_ladder` (`RiskManager.exclusive_conflict` → False for the sibling NO leg under the family limits), `test_maker_limits_keep_allow_short_false`, `test_default_limits_still_refuse_exclusive_conflict` (existing behaviour unchanged) |
| `tests/strategy/no_ladder_maker/test_strategy_shadow.py` | `test_package_never_calls_order_mutation_api`, `test_no_leg_book_received_via_yes_slug_subscription`, `test_cancel_fires_at_0900_lst_with_no_market_event` (TestClock), `test_forecast_expiry_alert_cancels_at_available_at_plus_8h`, `test_permit_expiry_alert_cancels_all_rests`, `test_would_be_order_is_gtd_with_logged_expire_time`, `test_family_halt_row_abstains_maker_station_days`, `test_on_stop_writes_shadow_stop_and_node_stop_cancels`, `test_boot_line_carries_instance_id_sha_and_permit_expiry`, `test_forecast_line_carries_full_quantile_vector_and_theta`, `test_jsonl_sink_round_trips_every_record_kind` |
| `tests/unit/test_autonomy_plugins.py` | widened rows |

`test_package_never_calls_order_mutation_api`: AST scan over `src/breezy/strategy/no_ladder_maker/` banning `submit_order`, `submit_order_list`, `modify_order`, `cancel_order`, `cancel_orders`, `cancel_all_orders`, `close_position`, `close_all_positions`. `test_shadow_only_false_is_only_the_gate_output.py` passes **unchanged**.

**Admission review.** The `allow_overlapping_exclusive_yes=True` row gets its own reviewer sign-off before the PREREG freezes (spec §3). If refused: drop the row and its test, set `MAX_RUNGS = 1` (S-2). **Completion:** merged gate-green; node not switched yet.

### WP3 — Replay scorer (~10 h)

**`scripts/analysis/maker_shadow_scorer.py`** `--shadow-dir --tape --truth --prereg --out [--stress <name>] [--unit <hyp>]`

1. **Windows.** BOOT/STOP → node up-windows; a BOOT with no prior STOP closes the previous instance at its last logged line. Permit windows = [BOOT, `permit_expires_ns`]. Both are outcome-blind and define `incomplete_day_rule` (no instance → no rests).
2. **Causal replay.** Walk tape (Depth10 + prints) and logged `SHADOW_FORECAST` vectors in event order inside up- and permit windows; call `decision.decide` with `filled`/`open_positions_total` from simulator state. Every rest (episode, spec §6.1) ends at the earliest of cancel, replace, window end, permit expiry, 09:00 LST, `available_at + STALE_H`, end of UTC day — the GTD clamp, applied independently of the live alert. Fills use the S2 simulator unchanged: Q₀ = displayed NO size at prices ≥ b at t₀ + our 1; a YES-BUYER print at NO price > b reduces Q₀; a print at NO price ≤ b consumes the remaining Q₀; FILLED when cumulative volume exceeds Q₀; `NO_AGGRESSOR` never credited; empty NO bid side → no implied fill; stale/truncated frames refused (`DepthTruncation`); `custom_quote_tape_gap` spans subtracted. If the unit is bracketed, run both USD hypotheses; the conservative one governs every gate.
3. **Taker bucket** (spec §3, §6.8). A rest whose next book frame shows the NO ask ≤ bid before any print is a TAKER fill: in P&L, excluded from the maker win rate, counted `taker_filled`.
4. **Parity.** Replay with fills disabled vs live `SHADOW_DECISION` rests → mismatch count (G7).
5. **Positions.** One row per filled (station, day, rung): bid, fee, fill ts, p_NO, p_YES at the fill instant, outcome, lock hours; inclusive [A,B] via `bucket_facts_from_instrument_id` (`analysis/labeling/instrument_facts.py:72`) on CLI FINAL (wins any METAR conflict; lock to 11:00 ET). **Primary scoring (spec §6.5):** unresolved past D+14 = LOSS (bid + fee); void = refund − fee (refund 0 until verified); corrections reported separately.
6. **Fill rate** reported with denominator = all covered bid-bearing station-days (spec §6.0), never only print-eligible days.
7. **Unfilled counterfactual episodes** kept, scored, for §6.9.
8. **Baselines** (spec §6.6, report-only, never a gate): (a) taker at the NO ask at each first-rest t₀; (b) forecast-only take. Units: per eligible rung-day and per unit of deployed capital; n < 30 → `NOT_COMPARABLE`.
9. **Stress** (spec §6.7). Gated, point estimates, re-decided: `fill_2x` (Q₀ = 2 × (size ahead + 1), re-fill + re-decide), `q_shift_±1F` (re-decide p_NO and bids), `theta_0_08`, `maker_coeff_eq_taker` (re-cost). Report-only: `loso_<STN>`, `by_month`.
10. **Refusals** (exit 3, no output): post-cap tape; missing/invalid PREREG; any vector with `available_at_ns > decision ts` (`LeakageError`); a rest before the frozen commit time.

**`scripts/analysis/maker_eval_stats.py`** (one pure module): `win_rate_ci`, `expectancy_lower_bound`, `profit_factor`, `max_drawdown_daily`, `turnover`, `exposure_by_station`, `return_on_deployed_capital`, `design_effect(cluster=...)`, `effective_n`, `station_day_n`, `adverse_selection_screen(...)` (§6.9, below), `power_projection(counts_by_day, pooled_expected_loss_by_day, cap_date)` (outcome-blind).

**`adverse_selection_screen` (spec §6.9).** The VERDICT is computed on the **pooled** set of filled maker episodes (all p_NO strata, stations and dates together). With n filled episodes, k YES settlements, model p_YES,i at the fill instant:
- pooled expected losses m = Σ p_YES,i. **m < 10 → UNSCREENED** (never PASS).
- **Model test:** exact Poisson-binomial upper tail P(X ≥ k) under p'ᵢ = min(1, 1.5 · p_YES,i) (`as_margin` = 1.5×, fixed by the spec). p < 0.05 → FAIL.
- **Unfilled test:** exact binomial upper tail P(X ≥ k | n, min(1, 1.5 · r_u)), r_u = the pooled unfilled-episode YES rate; the comparator's sampling error is not propagated (stricter on the family; stated in the report). p < 0.05 → FAIL.
- **Verdict:** FAIL if either pooled test fails (terminal, S-6); else PASS iff m ≥ 10; else UNSCREENED.
- **Strata** (p_NO 0.94–0.96, 0.96–0.98, > 0.98): n, k, m, filled and unfilled rates reported **descriptively only**; they never set the verdict.

**RED-first tests**

| File | Tests |
|---|---|
| `tests/unit/test_maker_shadow_scorer.py` | `test_replace_resets_t0_and_queue_ahead`, `test_better_priced_buyer_print_reduces_q0`, `test_no_aggressor_prints_never_fill`, `test_filled_rung_stops_resting_and_over_cap_fill_never_scored`, `test_rest_spanning_node_downtime_ends_at_last_line_of_instance`, `test_rest_clamped_to_permit_expiry`, `test_rest_clamped_to_0900_lst_even_without_live_cancel`, `test_rest_clamped_to_available_at_plus_8h`, `test_taker_race_counted_separately_not_in_maker_win_rate`, `test_fill_rate_denominator_is_all_covered_bid_bearing_station_days`, `test_bracketed_unit_runs_both_and_conservative_governs`, `test_unresolved_past_deadline_scores_as_loss`, `test_void_scores_refund_minus_fee_and_is_counted`, `test_leakage_vector_refuses_run`, `test_inclusive_band_settlement`, `test_parity_counts_live_vs_replay_rest_mismatch`, `test_q_shift_stress_redecides_rest_set`, `test_loso_and_by_month_are_report_only`, `test_baseline_below_min_n_is_not_comparable` |
| `tests/unit/test_maker_eval_stats.py` | `test_max_drawdown_of_daily_series`, `test_profit_factor_zero_losses_is_inf_flagged`, `test_ci_resamples_whole_blocks`, `test_design_effect_is_one_for_iid_clusters_of_one`, `test_as_pooled_below_10_expected_losses_is_unscreened`, `test_as_exact_tail_fails_above_1_5x_model`, `test_as_fails_when_filled_exceeds_1_5x_unfilled`, `test_as_verdict_is_pooled_and_strata_are_descriptive_only`, `test_as_unscreened_is_never_pass`, `test_power_projection_reads_no_outcome_field` (AST/field) |

**Completion:** merged; a synthetic 5-day dry run produces positions, outputs and every stress.

### WP4 — Nine-gate report (~6 h)

**`scripts/analysis/maker_promotion_report.py`**: loads the PREREG via `check_frozen_blob` + `check_freeze_introduction`; refuses before the read date and on a second read (`_refuse_overwrite`); builds nine `CriterionRow`s (machine value, threshold, input sha).

| Gate | Machine value(s) | Rule |
|---|---|---|
| G1 | observed maker win rate **and** block-bootstrap lower bound, two fields | point ≥ 0.85 |
| G2 | position n, effective n (realised deff, 7-day blocks), station-day n | effective n ≥ 200 **and** station-day n ≥ 200 |
| G3 | expectancy and portfolio return, primary scoring | both > 0; one-sided lower bound on expectancy at `alpha_family`, 7-day block clusters, excludes 0 |
| G4 | `alpha_family`, revisions used | revisions = 0; α matches the ledger record |
| G5 | structural refusal counts; gated-stress point estimates | no limit breach in the replay; every gated §6.7 stress net-positive; loso/by-month report-only |
| G6 | leakage, selective-exclusion, mid-fill, un-censused-day counts | all = 0 |
| G7 | decode errors, parity mismatches, coverage | errors = 0; parity mismatch ≤ 0.01; up-window coverage of listed station-day resting hours ≥ 0.90 |
| G8 | S3 artefact sha (A1 reachability PASS); S4 merged sha + gate EXIT + S4 venue positive-control evidence (resting GTD accepted, cancel scoped); credentials/permit evidence from node-log lines | all present; S4 implements cancel-on-stop. Never reads or assigns `operator_max_*` (`order_enablement.py:211-217`) |
| G9 | §6.9 pooled verdict, pooled m; strata descriptive | PASS only; UNSCREENED and FAIL are false |

G3 method: the more conservative of (i) a cluster-robust Student-t bound over 7-day blocks, G−1 df, and (ii) a 7-day-block percentile bootstrap, B = 100 000; climate-date clusters reported beside; the PREREG states the MDE at the read n. Then `assemble_outcome(rows, criteria_status="FROZEN_PREREG")` + `render_rationale`. No manifest write, no `runtime.settings` import, nothing under `deploy/`.

**RED-first** (`tests/unit/test_maker_promotion_report.py`): `test_any_false_gate_is_no_proposal`, `test_report_refuses_before_read_date`, `test_second_read_refuses_overwrite`, `test_report_never_writes_under_deploy_or_imports_settings` (AST), `test_g1_reports_point_and_lower_bound_separately`, `test_g3_uses_conservative_of_t_and_block_bootstrap`, `test_g8_false_without_s4_positive_controls`, `test_g9_unscreened_is_gate_false`, `test_g9_fail_is_gate_false_and_flagged_terminal`.

**Completion:** merged, with one PROPOSAL and one NO_PROPOSAL fixture.

### WP5 — PREREG, checker, progress + A1 stop (frozen before `holdout_start_date`; ~6 h)

**`docs/evidence/maker/PREREG.json`** (pattern `docs/evidence/m1v3/PREREG.json`):

| Group | Fields |
|---|---|
| Identity | `hypothesis`, `spec_sha256` (v0.3), `family_id`, `manifest_sha256`, `params` (= `config.py`, incl. the resolved `MAX_RUNGS`), `stations`, `rung_admission` (review ref or "refused → MAX_RUNGS 1") |
| Dates | `holdout_start_date` (calendar; ≥ last Stage 0 climate day + 2, i.e. a one-calendar-day purge, spec §6.2; a rest counts only if climate_day ≥ it **and** rest ts > frozen commit time); `calendar_cap_date` (§8); `revision_budget: 0`; `dev_set: "Stage 0, exploratory, seen"` |
| Read target | holdout positions ≥ 300 (200 × deff ceiling 1.5) **and** station-days ≥ 200, counted outcome-blind; read once on the first date this holds with truth FINAL or past D+14, else on `calendar_cap_date` |
| Power stop | day 60 of the holdout: `power_projection` below the read target at the cap, → `INCONCLUSIVE_UNDERPOWERED`; projected **pooled** m (outcome-blind fill counts × model p_YES) < 10 at the cap → `UNSCREENED-TERMINAL` |
| Loss stop (spec §4) | `a1_stop`: the S3-certified A1 object verbatim — `(c, t_min, α_floor)`, station-day clock, σ inflated by √1.5 (deff ceiling), looks ordered by `(settlement_ts, climate_day, station)`. A harm stop outside the RA-13 efficacy spend. Output CONTINUE/STOP only |
| Clustering | `cluster_unit_primary: "7-day calendar block"`, `cluster_unit_reported: "climate_date"`, `bootstrap_B: 100000`, seed |
| α | `alpha_family` from the WP0 dry call; G3 one-sided at `alpha_family` |
| Adverse selection | §6.9 as in WP3: pooled verdict, strata descriptive, `as_margin: 1.5` (multiplicative), exact tails at α 0.05, `min_expected_losses_pooled: 10`, `power_check_day: 60`, PASS / FAIL / UNSCREENED, FAIL terminal |
| Other rules | `voids_rule`, `unresolved_rule` (= LOSS), `incomplete_day_rule`, `permit_window_rule`, `taker_fill_rule`, `leakage_operator: "available_at_ns <= decision_ts visible"`, `stress` (gated vs report-only), `baselines` (report-only, min n 30), `gates` (WP4) |
| Disclosures | `b3_disclosure`; `holdout_freeze_disclosure` (NBP holdout clause 3); `season_note`; `ra13_review_note` (2027-01-25 precedes any read); `frozen_sha`; `status: FROZEN` |

**Tools.** `scripts/analysis/maker_prereg_check.py` (reuses `check_frozen_blob`/`_canonical`; equality with `config.py` and the spec v0.3 constants; purge rule; `revision_budget == 0`). `scripts/analysis/maker_progress_report.py`: counts, `power_projection`, days to cap, no outcome field; plus `a1_stop_status(positions, a1)` which calls S3's parameterised evaluator (or composes `normalise_station_day` → `step_clock` → `first_crossing` with S3's frozen `(c, t_min)`, `BuyFill(side="no", qty=1, cost=bid, fee=fee_est, fee_reconciled=True)` — the shadow fee is the deterministic formula, disclosed), emitting CONTINUE/STOP and nothing else. No separate tally script.

**RED-first tests**

| File | Tests |
|---|---|
| `tests/unit/test_maker_prereg_check.py` | `test_param_mismatch_with_config_refuses`, `test_stale_h_must_equal_8`, `test_frozen_sha_must_introduce_blob`, `test_split_is_calendar_dates_not_fraction`, `test_holdout_start_respects_one_day_purge`, `test_revision_budget_nonzero_refuses` |
| `tests/unit/test_maker_progress_report.py` | `test_no_outcome_field_before_read_date`, `test_power_stop_fires_from_counts_only`, `test_unscreened_terminal_fires_on_projected_pooled_m_below_10`, `test_a1_stop_uses_s3_parameters_and_deff_inflated_sigma`, `test_a1_looks_ordered_by_settlement_ts_with_deterministic_ties`, `test_a1_output_is_continue_or_stop_only` |

**Completion:** PREREG committed as its own reviewed commit, gated like code (read the gate EXIT before any push); checker exits 0; manifest `d0_climate_day` = `holdout_start_date`.

### WP6 — Start the shadow run (ops; ~3 h, then the calendar clock)

1. Only after WP0 item 5 shows nothing broken, with orders off (drop-in untouched, no allowlist row): set `BREEZY_SENDING_FAMILY_ID=pm_us_no_ladder_maker_v1` as a reviewed supervisor-unit edit (on a branch until gates pass); restart the supervisor in 01:00–16:40Z.
2. **Boot health check.** Node log must show: maker composition line; `SHADOW_BOOT`; `subscribed_slug_count` covering every listed maker slug; zero `silent_subscriptions` for maker slugs; the fee-drift-probe line; **no** live-orders/permit-mint line for the maker. Any miss → roll back the env edit and report.
3. **Timers.** `breezy-maker-shadow-score.timer` (scorer + progress + A1 stop check) with `RuntimeMaxSec`, `MemoryMax`, a no-progress event, subset benchmark first; outside the nightly study window. An A1 STOP sets the family halt row and writes `S5_A1_STOP_<date>.md`.
4. **Liveness** = process + log mtime + JSONL advancing + tape advancing; LIVE only after the first scheduled success is seen.

**Completion:** first success seen, then 7 days with decode errors = 0, leakage = 0, parity mismatch ≤ 0.01. Then wait for the read, the A1 stop, or a day-60 power stop.

## 6. Data and tooling dependencies

| Input | Path | Status |
|---|---|---|
| Depth10 + trade-print tape | quote-tape catalog under `~/.local/share/breezy/catalog` | exists; census after 2026-09-25 is S1's |
| Settlement truth | `~/.local/share/breezy/derived/settlement-truth/settlement_truth.parquet` | exists |
| NBP derived store (WP0 coverage) | `persistence/nbp_derived_store.py` partitions | exists |
| Calibration artefact | `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` | exists; tail calibration **UNVERIFIED** (S2 is the only evidence) |
| S2 simulator / S3 artefact + evaluator | `scripts/analysis/<S2>` / `docs/evidence/maker/A1_REACHABILITY_*.md` | **UNVERIFIED** until WP0 |
| Permit TTL constant | live permit module (spec: 10 h) | **UNVERIFIED** location; WP0 item 3 |
| Shadow JSONL | `~/.local/share/breezy/maker_shadow/` | WP2 |

## 7. Risks and invariant guards

| # | Risk | Invariant | Guard |
|---|---|---|---|
| R-1 | Maker path sends or cancels a real order | NO-SEND / live enablement | package-wide AST ban; no allowlist row; orders-off drop-in kept; exec firewall tests in every focused list |
| R-2 | Widened exact-sets read as relaxed | L-12 | one row per set; equality asserts |
| R-3 | `allow_short` drift; the admission flag read as a short licence | allow_short False | `test_maker_limits_keep_allow_short_false`; NO bought as the NO instrument; `decide` never emits a sell; default-limits test unchanged |
| R-4 | Shadow counts positions live would refuse | gate-5 honesty | limits in `decide`; causal fill state; permit-window clamp; admission test or MAX_RUNGS 1 |
| R-5 | Holdout peeked | read-once | counts-only progress; A1 output CONTINUE/STOP; `power_projection` field test |
| R-6 | RA-13 B-3 tape reads | RA-13 firewall | PREREG `b3_disclosure`, accepted in review before freeze |
| R-7 | Operator caps touched | reserved controls | G8 reads node-log evidence only; no maker file references `operator_max_*` |
| R-8 | PREREG edited or date moved | frozen PREREG | introducing-commit check; a change is a fork |
| R-9 | Exec client reformatted | exec byte pin | format only own files; stray check |
| R-10 | Silent stalls | ops | RuntimeMaxSec, no-progress event, subset benchmark |
| R-11 | Sending-family switch breaks an FQ or M1-v3 consumer | — | WP0 item 5; "broken" means STOP |
| R-12 | Shadow restart/permit semantics diverge from live S4 | evidence validity | cancel-on-stop + permit clamp pinned; G8 false otherwise |
| R-13 | A second loss stop creeps back | spec §4 one stop | no tally script; `a1_stop` is the only stop field; PREREG checker refuses any other stop key |

## 8. Sample clock (stated, by calendar date)

Inputs to the E1 feasibility rule and `calendar_cap_date`. Station-days/day listed ≈ 4 × 0.91 = 3.64, times the WP0 coverage factor `c` (`STALE_H` 8 + permit TTL; c = 1 below; dates scale by 1/c).

- MAX_RUNGS = 2: positions/day = 7.28·c·r; station-days with ≥ 1 position/day = 3.64·c·(1 − (1 − r)²).
- MAX_RUNGS = 1: positions/day = station-days/day = 3.64·c·r (clock doubles).

Start 2026-11-23 is an assumption (freeze after S1–S4 entry evidence); dates shift 1:1.

| r | MAX_RUNGS | Positions/day | Station-days/day | Days to 300 pos | Days to 200 SD | Binding | Read ≈ |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0.10 | 2 | 0.73 | 0.69 | 412 | 289 | **412** | beyond cap |
| 0.115 | 2 | 0.84 | 0.79 | 359 | 253 | **359** | ≈ cap |
| 0.25 | 2 | 1.82 | 1.59 | 165 | 126 | **165** | 2027-05-07 |
| 0.50 | 2 | 3.64 | 2.73 | 83 | 74 | **83** | 2027-02-14 |
| 0.25 | 1 | 0.91 | 0.91 | 330 | 220 | **330** | 2027-10-19 |
| 0.50 | 1 | 1.82 | 1.82 | 165 | 110 | **165** | 2027-05-07 |

**`calendar_cap_date`** = `holdout_start_date` + ceil(binding days at `r_lo`/c) + 14 truth days, pinned at freeze; never later than 2027-11-30. From a 2026-11-23 start that leaves 358 binding days, so E1 feasibility needs `r_lo · c` ≳ 0.115 at MAX_RUNGS = 2 (positions bind) and ≳ 0.23 at MAX_RUNGS = 1. Below that, S-1: nothing is frozen.

**2027-01-25 horizon** (NO-TRADE review / RA-13 backstop): no read precedes it; the day-60 power check (~2027-01-22) carries no outcome. The M1-v3 read (≥ 2026-12-07) is independent.

## 9. Effort and evidence artefact

WP0 3 h · WP1 6 h · WP2 9 h · WP3 11 h · WP4 6 h · WP5 6 h · WP6 3 h + ≈ 8 h reviews/gates = **≈ 52 agent-hours**; calendar per §8. Single evidence artefact: `docs/evidence/maker/S5_PROMOTION_GATE_REPORT.{md,json}` (or the §1 STOP/FAIL/INCONCLUSIVE file on an early end).

## 10. r3 conformance table

| Verdict item | Spec v0.3 | Plan § changed |
|---|---|---|
| C1/R1 second sequential stop | §4 one loss stop | §2 S-3, §3.3, §4 loss-stop row, WP5 `a1_stop` + `a1_stop_status`, R-13; tally script and `boundary_for` use deleted |
| C2/R2 age 6 h | §3 `STALE_H` 8 | header, WP0.3, WP1 config/rule/tests, WP2 alert + test, WP3.2 clamp, WP5 checker test, §8 |
| C3/R3 "S2 GO" | §6.0 verdict table | E1 (NOT-KILLED / NOT-KILLED-UNSCREENED, base and stressed ≥ 0.10, denominator) |
| C4/R4 §6.9 form | §6.9 (amended: pooled verdict, strata descriptive, UNSCREENED-TERMINAL power check) | WP3 `adverse_selection_screen` + tests, WP4 G9, WP5 rows, S-5b, S-6; r2 open Q2 and r3 Q1 closed |
| C5/R5 MAX_RUNGS refusal = STOP | §3 MAX_RUNGS fallback | S-2, WP0.4, WP2 admission row + tests, WP5 identity, §8 rows |
| R6 "r_lo ≳ 0.2" | §9.15 | §8 (≈ 0.115 at c = 1; 0.23 at MAX_RUNGS 1) |
| C6 GTC | §3 GTD | WP1 `expire_time_ns`, WP2 would-be order + permit alert, WP3.2 clamp |
| C7 purge | §6.2 one-day purge | WP5 dates + checker test |
| C8 taker bucket | §3, §6.8 | WP3.3 + test |
| C9 loso report-only | §6.7 | WP3.9, G5, test |
| C10 G8 positive controls; stale §10 | §7.8 | G8 + test; this table replaces r2 §10 |
| Common | §6.0 denominator/process schedule, §6.1 rule, §6.5, §6.6, §7.3 | WP3.2/3.5/3.6/3.8, G3 |

Dead text removed: the Wilson/LD-OBF-style stop, 60/40 split, "S2 GO", 6 h age, sub-0.70 bids, r2 §10 inputs and r1 disposition table (all r1 items were verified present in `reviews/S5-r2-final.md`).

## 11. Open questions for peer review (max 5)

1. CLOSED: §6.9 power at the read target, resolved by the spec amendment (pooled verdict, ~12 expected losses at 300 positions; S-5b UNSCREENED-TERMINAL).
2. Is the replay's taker-race rule (next frame NO ask ≤ bid before any print) the right shadow proxy for a live crossing race?
3. Permit expiry in shadow is synthetic (boot + TTL). Should the scorer also model the mid-day relaunch schedule when the node log shows none?
4. Is 7-day the right block length, given 2–5-day heat-event persistence?
5. Should the parity threshold (≤ 0.01) be tighter, since parity is the only check that the replay describes the live strategy?

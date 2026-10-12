# S5 — Prospective shadow run, evaluation and promotion-gate tooling

| Field | Value |
|---|---|
| ID | S5 |
| Revision | r1 |
| Date | 2026-10-12 |
| Status | DRAFT (not peer-reviewed; must not start before its entry criteria) |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.2 (§3 rule, §4 risk, §6 evaluation, §7 gates, §9 gaps) |
| Ruling context | T2 route of `docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md`; the NO-TRADE ruling stays in force throughout S5 |

## 1. Goal state (acceptance test)

S5 is done when exactly one of these exists, produced by the bot's own tooling and not by Claude arithmetic:

- **PASS:** `docs/evidence/maker/S5_PROMOTION_GATE_REPORT.{json,md}`: the tool reads the holdout once, writes nine `CriterionRow`s, all `true`, and `assemble_outcome` returns `PROPOSAL`. The report states that it arms nothing. Activation stays a separate manual act: a `BREEZY_SENDING_FAMILY_ID` edit, a supervisor restart and a committed `live_orders_ruling`, plus an allowlist row in `persistence/live_orders_gate.py`. **S5 builds no auto-arm path.**
- **FAIL / STOP:** the same report with outcome `NO_PROPOSAL`, naming the failed gate(s). It can also be a sequential-stop report (`docs/evidence/maker/S5_SEQUENTIAL_STOP_<date>.md`) issued when the pre-registered loss boundary fires. The family stays at its last version and the programme ends (PROGRESS row 5).

On the way: (a) family code + a REGISTERED SHADOW manifest with no `live_orders_ruling`; (b) `docs/evidence/maker/PREREG.json` frozen (introducing commit, ancestor of HEAD) **before** the first shadow day; (c) a daily counts-only progress report under `~/.local/share/breezy/derived/maker_shadow/` with no holdout outcome.

## 2. Entry criteria and STOP conditions

**Entry criteria (all required; WP0 verifies them and records the evidence):**

| # | Criterion | Evidence |
|---|---|---|
| E1 | S2 verdict GO: Stage 0 fill rate ≥ 0.1 and §6.9 PASS (exploratory only) | `docs/evidence/maker/STAGE0_REPLAY_*.md` |
| E2 | S3 PASS: the A1 floor is not `unreachable_veto` for the maker mix at the S2 fill rate | `docs/evidence/maker/A1_REACHABILITY_*.md` |
| E3 | S4 merged and gate-green; the resting path exists and orders stay OFF (`fq-v1-halt-orders-off.conf` drop-in `BREEZY_ORDERS_ENABLED=0` untouched) | merge sha + gate EXIT=0 |
| E4 | `TRADE_QUANTITY_UNIT` resolved and the YES→NO print inversion pinned (S1) | S1 evidence file |
| E5 | The §6.1 maker fill simulator exists as an importable function in `scripts/analysis/`, unit-tested (spec §9.5) | path + sha recorded in WP0 |

**STOP conditions (each one ends S5 and the programme):**

- **S-1:** any entry criterion unmet. Do not start, and do not partially build ahead of it.
- **S-2:** WP0 shows that the maker family's Depth10 subscriptions do not fit the venue WS cap (10 subs per connection, shared MARKET_DATA + TRADE). If no native multiplexing exists, in-node shadow is infeasible. Report it and stop; do not build a second node.
- **S-3:** the pre-registered sequential loss boundary fires (§WP5). The output is STOP only.
- **S-4:** the holdout is read once and any of the nine gates is `false`.
- **S-5:** the calendar cap pinned in PREREG is reached before the holdout count target. Verdict is `UNDERPOWERED`, which equals gate 2 FAIL. The cap is never extended.

## 3. Simplest direct path

Add one new `composition_kind`, `no_ladder_maker`. It is a pure decision function inside a thin Nautilus `Strategy` that never calls `submit_order` (a literal `shadow_only=True`). It logs every rest, replace, cancel and abstain as a `SHADOW_DECISION` line and also writes the same line to a JSONL sink. The node runs it as the (still order-disabled) sending family.

A single `scripts/analysis` scorer does the evaluation. Each day it joins the JSONL against the recorded trade prints (the S2 fill simulator) and against `settlement_truth.parquet`. It reuses the existing cluster-bootstrap, Lan-DeMets and `assemble_outcome` code for the statistics and the nine gates.

**Heavier options, not built:**

- **AUT-2 labels / AUT-5b** would buy label minting, drift detectors and auto-promote. The decision is one read-once go/no-go plus manual activation, so none of it changes the verdict (and AUT-5b is an enum with no code path). **Not needed.**
- **`hypothesis_triage` / replay-daily integration** would buy a uniform dashboard. **Not needed:** one JSON per day suffices.
- **A native Nautilus backtest (`BacktestEngine` + `FillModel`)** cannot express §6.1 (YES-leg-only prints, last-in-queue vs displayed NO size, no `NO_AGGRESSOR` credit), so the S2 simulator stays the fill instrument.

## 4. Nautilus null-hypothesis check

| Need | Native / existing capability (evidence) | Verdict |
|---|---|---|
| Strategy lifecycle, timers, book subscriptions | `nautilus_trader.trading.strategy.Strategy` (imported `app/trade.py:33`); FQ precedent `ForecastQuantileLadderStrategy(Strategy)` (`strategy/forecast_quantile_ladder/strategy.py:128`) | REUSE: subclass only |
| Would-be order construction | Nautilus `OrderFactory.limit(..., time_in_force=GTC)` on `Strategy.order_factory`; built and logged, never submitted | REUSE |
| Family dispatch | `_compose_family` (`app/trade.py:929-977`) dispatches on `manifest.composition_kind`; unknown kind → `SettingsError` | EXTEND: one branch |
| Manifest schema | `FamilyManifest` / `parse_family_manifest` (`persistence/family_manifest.py:218-260, 300-382`); kinds exact-set `_COMPOSITION_KINDS` (`:119-121`) | EXTEND: one kind (WIDENED row); no new keys |
| Shadow-only guarantee | AST guard `tests/unit/test_shadow_only_false_is_only_the_gate_output.py` permits exactly one non-`True` `shadow_only` expression in `src/` (FQ branch) | REUSE unchanged: the maker branch passes literal `True` |
| Live-orders two-key gate | `live_orders_authorized` (`persistence/live_orders_gate.py:175-216`), allowlist `:80-88` | UNTOUCHED: no maker row is added by S5 |
| SHADOW_DECISION pattern | `ShadowDecisionLogLine` + `_emit_shadow_decision` (`forecast_quantile_ladder/strategy.py:112-126, 577-581`), sink-callable + log line | REUSE the pattern (own TypedDict) |
| Forecast distribution | `NbmQuantileActor` (`ingest/nbm_quantile_actor.py`; NBP cycles 13Z/19Z/01Z), `load_live_calibration` (`forecast_quantile_ladder/calibration_artefact.py:236`), `ArtefactBoundsProvider` (`artefact_bounds.py:38`) → `p_hat` per rung (`decision.py:331`) | REUSE; the missing piece is a pure `p_no_for_rung` adapter (spec §9.6), with no new loader |
| Halt latch, fee-drift probe | `_open_halt_latch_preamble` (`app/trade.py:~530-566`), `_build_fee_drift_probe` (`:365+`) | REUSE as the FQ branch does |
| Risk values | `RiskLimits` (`strategy/weather_common/risk.py:180-225`, `allow_short=False` `:224`), `RiskManager` (`:445`), refusal `exclusive_bucket_conflict` (`:159, :640`), `RefusalCounter` (`refusals.py:123`) | REUSE values and counter; see R-4 on `evaluate_order` fit |
| Exit | exit seam (`current_rung_hold/exit_decider.py`, `exit_wiring.py`) inert when the manifest has no `exit_rule` | REUSE as inert; hold to settlement (spec §3, §9.14) |
| Cluster bootstrap | `bootstrap_cluster_draws`, `percentile_interval`, `ClusterCI`, `LeakageError` (`analysis/stats/scoring_core.py:34, 176-256`) | REUSE |
| LD-OBF boundary | `boundary_for(t_history, alpha)` (`analysis/stats/group_sequential_boundaries.py:163`), `one_sided_spend` (`:40`) | REUSE; the CRH `CombinedDraw` path (`sequential_looks.py`) is not reused, because its type is CRH-specific |
| Gate assembly | `CriterionRow`, `assemble_outcome` (`analysis/promotion_criteria.py:613-637`), `render_rationale` (`:640`) | REUSE; the CRH predicates (`evaluate_c_kill` etc.) are not applicable |
| Freeze / read-once | `check_frozen_blob` (`scripts/analysis/prereg_precommit_check.py:340`), `check_freeze_introduction`, `_refuse_overwrite`, `_preflight_inputs` (`no_longshot_pooled_test.py:423-450, 784-795, 875+`) | REUSE by import |
| α allocation | `analysis/hypothesis_ledger.py` (AUD-18 programme ledger) | REUSE if `register_hypothesis` accepts the shape (Q5) |
| Win-rate / drawdown / PF / turnover | `portfolio_roi_report.py` (4821 lines) is keyed on exec-DB `DurableFillRecord`; shadow has none | Genuinely missing; a sibling function inside the scorer is smaller |

**Genuinely missing (built here):** the decision core and strategy; the `p_no_for_rung` adapter; the JSONL sink; the scorer join; design effect, purge/split, Holm, baselines/stress/§6.9; the nine gate rows; the maker PREREG field checks; the counts-only progress report.

## 5. Work packages

All WPs: worktree with `PYTHONPATH=<wt>/src` and the shared venv interpreter by exact path (never `uv`/`pip`); focused tests first, then the full gate after each merge (`scripts/ci/run_tests_no_egress.sh`, `--basetemp ~/.cache/breezy-gate-<wp>`, `rm` after reading EXIT); `lint-imports` from the tree root ("N kept, 0 broken"); `ruff format` on touched files only. Every focused list must include the firewall guards: the exec import pin, NO-SEND egress, `test_shadow_only_false_is_only_the_gate_output.py`, `test_autonomy_*`, and the import gates.

### WP0 — Entry verification (no code; ~1 h)

Record the following in `docs/evidence/maker/S5_ENTRY_<date>.md`:

1. E1–E5 evidence paths and shas.
2. The S2 fill-simulator import path and signature.
3. **Subscription count:** instruments the maker needs. That is D and D+1 ladders × 4 stations × 6 rungs, NO Depth10, versus how the FQ composition subscribes, versus the 10-sub cap. → S-2 if it does not fit.
4. **`RiskManager.evaluate_order` fit for a resting bid.** Its steps are taker-shaped (`available_ask_depth`, `max_bid_ask_spread`, `min_liquidity_contracts`). Decide between whole-call reuse and reusing the three named checks only (R-4).
5. **Consumers of the current sending family `pm_us_crh_fq_v1` shadow output:** `nbp_shadow_parity.py`, `fq_loss_taxonomy_logs.py`, decision-funnel digest. That family has `terminal_climate_day` 2026-10-05 (Q2).
6. The `StationObservation` interval fields used by CRH ambiguity (`tests/unit/test_current_rung_hold_strategy.py::test_an_interval_only_touching_this_instruments_upper_bound_is_counted_ambiguous`), to reuse for the integer-°C widening.

**Completion:** the file is committed with a GO, or with a named STOP.

### WP1 — Pure decision core (types first; ~5 h)

**Files to create** under `src/breezy/strategy/no_ladder_maker/`: `__init__.py`, `config.py`, `rung_probability.py`, `decision.py`.

**Interfaces:**

```python
# config.py — spec v0.2 §3/§4 constants; pinned by PREREG (checker imports them, no duplicated literals)
P_MIN = 0.94; B_CAP = 0.80; E_MIN = 0.10; B_FLOOR = 0.50; TICK = 0.01
CANCEL_HOUR_LST = 9; MAX_FORECAST_AGE_H = 6.0; MAX_RUNGS_PER_STATION_DAY = 2; ORDER_QTY = 1
class NoLadderMakerConfig(StrategyConfig, frozen=True):  # shadow_only: bool = True; allow_short: bool = False
# rung_probability.py
def p_no_for_rung(*, bounds: RungBounds, rung: Rung) -> float           # 1 - p_hat, inclusive [A,B]
# decision.py
@dataclass(frozen=True) class Rest:  station, climate_day, rung_id, instrument_id, bid, p_no, fee_est, best_no_bid, displayed_no_bid_size_at_or_above, forecast_cycle_runtime_ns, forecast_available_ns
@dataclass(frozen=True) class Cancel: ..., reason: Literal["cancel_hour_lst","obs_within_one_rung","forecast_stale","p_no_below_min","replace"]
@dataclass(frozen=True) class Abstain: station, climate_day, reason: str
def select_rungs(p_no_by_rung: Mapping[str, float], modal_rung_id: str, ladder: Sequence[Rung]) -> tuple[str, ...]
def decide(*, now_ns, station, climate_day, std_utc_offset_hours, ladder, p_no_by_rung, forecast_cycle_runtime_ns,
           no_book: Mapping[str, NoBookTop], obs_interval_f: tuple[float, float] | None, resting: Mapping[str, Decimal],
           fee_coefficient: float, halted: bool, ambiguous_intent_open: bool) -> tuple[Rest | Cancel | Abstain, ...]
```

`decide` imports no settlement, CLI or P&L module (same forbidden-imports rule as FQ). `fee_est` is computed with `venue_fee_prob` (`weather_common/costs.py`) at the wire θ.

**RED-first tests** (`tests/strategy/no_ladder_maker/test_decision.py`), written first:

- `test_rung_below_p_min_cancels_and_never_rests`
- `test_bid_is_min_of_b_max_and_best_bid_plus_tick`
- `test_empty_no_bid_side_rests_at_b_max_without_implied_price`
- `test_b_max_below_floor_cancels`
- `test_at_most_two_rungs_and_never_adjacent_to_modal`
- `test_cancel_at_0900_lst_per_station_offset`
- `test_integer_celsius_observation_widens_to_full_ambiguity_band`
- `test_forecast_age_over_six_hours_cancels_all`
- `test_price_change_is_cancel_replace_with_new_t0`
- `test_halt_or_ambiguous_intent_abstains_whole_station_day`
- `test_inclusive_band_edges_match_bucket_facts_from_instrument_id`

Also `tests/strategy/no_ladder_maker/test_forbidden_imports.py::test_decision_imports_no_settlement_or_pnl` and `tests/unit/test_no_ladder_maker_config.py::test_allow_short_default_false_and_shadow_only_default_true`.

**Gate:** `pytest tests/strategy/no_ladder_maker tests/unit/test_no_ladder_maker_config.py`, plus `lint-imports` (the new package sits under the existing `breezy.strategy` layer contracts).

**Completion:** all tests green with RED→GREEN output kept, and no edit outside the new package.

### WP2 — Strategy, composition, manifest (SHADOW; ~8 h)

**Create:**

- **`src/breezy/strategy/no_ladder_maker/strategy.py`:** `NoLadderMakerStrategy(Strategy)`. It subscribes to NO Depth10 for D and D+1 and to `ForecastPoint`/quantile vectors and observations. On each book, forecast or obs event it calls `decide` and keeps an in-memory `resting` map of *would-be* rests. For each `Rest` it builds the order with `self.order_factory.limit(..., time_in_force=GTC, quantity=1)` and logs it, and it never calls `submit_order`/`cancel_order`. It calls `_emit_shadow_decision`, which writes a `SHADOW_DECISION` log line and the JSONL sink. It applies the `RiskLimits` checks per WP0's R-4 decision, records them via `RefusalCounter`, and logs the verdict on the line.
- **`src/breezy/strategy/no_ladder_maker/shadow_sink.py`:** `ShadowDecisionJsonlSink(output_dir: Path)`. It writes append-only, one file per UTC day, under `catalog_root.parent / "maker_shadow"`. The `decisions/` sibling convention comes from `FqDecisionFunnelActor`. Serialisation is explicit field by field, never `dataclasses.asdict`.
- **`src/breezy/strategy/no_ladder_maker/composition.py`:** `build_no_ladder_maker_strategies(*, catalog_root, today_by_station, calibration_artefact_path, calibration_artefact_sha256, submit_veto, fee_verified, required_fee_coefficient) -> tuple[list[Strategy], NbmQuantileActor-compatible actor]`.
- **`deploy/families/pm_us_no_ladder_maker_v1.json`:**
  - `family_id` `pm_us_no_ladder_maker_v1`; `venue` `polymarket_us`; `trial_id_prefix` `no_ladder_maker/trial/pm_us_no_ladder_maker_v1/`.
  - `d0_climate_day` = first shadow day (freeze commit UTC date + 1, per WP5).
  - `stations` `[LAX, MDW, MIA, SFO]` (NYC excluded per spec §2).
  - `status` `REGISTERED`; `composition_kind` `no_ladder_maker`.
  - `boundary_artefact_path` `deploy/families/artefacts/not_applicable_boundary.json` + its sha (FQ precedent).
  - `density_artefact_path` the FQ calibration artefact `nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` + sha `9c0b6d6e…`.
  - `taker_fee_coefficient` `"0.0695"`.
  - **No `live_orders_ruling`, no `exit_rule`.**

**Modify (each a reviewed WIDENED row, never a relaxation):**

| File | Change |
|---|---|
| `src/breezy/persistence/family_manifest.py:116-121` | add `"no_ladder_maker"` to `CompositionKind` and `_COMPOSITION_KINDS` |
| `src/breezy/app/trade.py:929-977` | add a `no_ladder_maker` branch → `_compose_no_ladder_maker(...)`. It reuses `_open_halt_latch_preamble` (own key_prefix `NO_LADDER_MAKER_TRIAL_KEY_PREFIX`) and `_build_fee_drift_probe`, never calls `live_orders_authorized`, and passes no non-literal `shadow_only` |
| `src/breezy/persistence/autonomy/paths.py:28`, `src/breezy/strategy/autonomy/node_plugins.py`, `src/breezy/analysis/autonomy/offline_plugins.py` | register `RefusingPlugin` for the new kind. This is exact-set parity (`tests/unit/test_autonomy_plugins.py:197-209`) and explicitly not AUT integration |
| `src/breezy/strategy/current_rung_hold/family_id_arg.py:20` | add the kind to `HALTABLE_COMPOSITION_KINDS`, so the family-halt CLI can halt the maker family |

**RED-first tests:**

- `tests/unit/test_family_manifest.py::test_no_ladder_maker_kind_loads_and_unknown_kind_still_refused`
- `tests/unit/test_no_ladder_maker_composition.py::test_compose_family_dispatches_no_ladder_maker`
- `tests/unit/test_no_ladder_maker_composition.py::test_maker_branch_never_calls_live_orders_gate`
- `tests/unit/test_no_ladder_maker_composition.py::test_maker_manifest_with_live_orders_ruling_refuses_boot`
- `tests/strategy/no_ladder_maker/test_strategy_shadow.py::test_strategy_never_calls_submit_or_cancel` (AST + mock)
- `tests/strategy/no_ladder_maker/test_strategy_shadow.py::test_rest_line_carries_queue_ahead_and_forecast_times`
- `tests/strategy/no_ladder_maker/test_strategy_shadow.py::test_jsonl_sink_round_trips_every_decision_kind`
- `tests/strategy/no_ladder_maker/test_strategy_shadow.py::test_forecast_ref_ts_strictly_before_decision_ts` (the leakage assert from spec §7.6)
- The widened rows in `tests/unit/test_autonomy_plugins.py`.

The existing `test_shadow_only_false_is_only_the_gate_output.py` must pass **unchanged**.

**Gate:** focused list (above + firewall guards), then the full gate, then `lint-imports`.

**Completion:** merged gate-green. The node is not yet switched (that is WP6).

### WP3 — Shadow scorer (~8 h)

**Create:**

- **`scripts/analysis/maker_shadow_scorer.py` (CLI):**
  ```
  maker_shadow_scorer.py --shadow-dir <maker_shadow/> --tape <quote-tape catalog> --truth <settlement_truth.parquet> --prereg docs/evidence/maker/PREREG.json --out <derived/maker_shadow/scored/>
  ```
  - **Join.** It reads the JSONL and rebuilds the per-(station, day, rung) rest timeline (t0 resets on replace). It calls the S2 fill simulator with the logged queue-ahead and the post-t0 maker-side-matched prints. `NO_AGGRESSOR` prints are never credited, and an empty NO bid gives no implied fill.
  - **Positions.** The output is one row per completed station-day-rung position: bid, fee, fill ts, p_NO, win/loss/void/unresolved, and capital-lock hours (fill → D+1 08:00 ET, or 11:00 ET on CLI/METAR conflict). Settlement is labelled inclusive [A,B] via `bucket_facts_from_instrument_id` (`analysis/labeling/instrument_facts.py:72`). Voids and corrections are counted separately and excluded from the win count.
  - **Counterfactual unfilled rows** are kept for §6.9.
  - **Baselines.** It computes the spec §6.6 baselines from the Depth10 tape at the logged instants. (a) The price-matched taker buys NO at the NO ask at each first rest t0. (b) The forecast-only take buys at the NO ask at the first forecast release where `p_no ≥ P_MIN` and `p_no − ask − fee ≥ E_MIN`. The exact definitions are pinned in PREREG.
  - It refuses (exit 3, no output) on post-cap tape, a missing PREREG freeze, or any row with `forecast_available_ns ≥ decision ts`, which raises `LeakageError`.
- **`scripts/analysis/maker_outputs.py`:** standard outputs (spec §6.8; the brief's missing items):
  - `win_rate_ci(positions, cluster="climate_date") -> ClusterCI`
  - `expectancy_ci(...)`
  - `profit_factor(...)`
  - `max_drawdown_daily(pnl_by_day) -> Decimal`
  - `turnover(...)`
  - `exposure_by_station(...)`
  - `return_on_deployed_capital(...)`

  This is a sibling, not an edit of `portfolio_roi_report.py` (that file is DurableFillRecord-keyed and 4.8k lines).

**RED-first tests:**

- `tests/unit/test_maker_shadow_scorer.py::test_replace_resets_t0_and_queue_ahead`
- `tests/unit/test_maker_shadow_scorer.py::test_no_aggressor_prints_never_fill`
- `tests/unit/test_maker_shadow_scorer.py::test_void_and_correction_excluded_from_win_count_and_counted`
- `tests/unit/test_maker_shadow_scorer.py::test_unresolved_carried_as_exposure`
- `tests/unit/test_maker_shadow_scorer.py::test_leakage_row_refuses_run`
- `tests/unit/test_maker_shadow_scorer.py::test_inclusive_band_settlement`
- `tests/unit/test_maker_outputs.py::test_max_drawdown_of_daily_series`
- `tests/unit/test_maker_outputs.py::test_profit_factor_zero_losses_is_inf_flagged`
- `tests/unit/test_maker_outputs.py::test_win_rate_ci_resamples_whole_climate_dates`

**Gate:** focused + `lint-imports`; the full gate after merge.

**Completion:** merged. A dry run over ≥ 3 synthetic days produces positions plus outputs.

### WP4 — Evaluation statistics and nine-gate report (~8 h)

**Create:**

- **`scripts/analysis/maker_eval_stats.py`** (pure):
  - `design_effect(positions, cluster) -> float`, defined as cluster-bootstrap variance over iid variance of the mean.
  - `effective_n(...)`
  - `station_day_n(...)`
  - `chronological_split(days, *, dev_fraction=0.6, purge_days=1) -> (dev_days, holdout_days)`
  - `holm(pvalues, alpha) -> tuple[bool, ...]`
  - `stress_set(positions, tape, truth) -> dict[str, ExpectancyCI]`. It covers 2× fill rule, ±1 °F quantile shift, leave-one-station-out, by-month, θ = 0.08, and maker coefficient = taker.
  - `adverse_selection_test(filled, unfilled, *, strata=((.94,.96),(.96,.98),(.98,1.0)), ratio=1.5, alpha=0.05) -> AsVerdict`. It uses a one-sided climate-date cluster bootstrap.
- **`scripts/analysis/maker_promotion_report.py`:**
  - It loads the verified PREREG through `check_frozen_blob` and `check_freeze_introduction` (imported from the M1-v3 tool).
  - It refuses before the read date, and refuses to overwrite (`_refuse_overwrite` pattern).
  - It builds nine `CriterionRow`s, gates G1–G9 = spec §7.1–7.9. Each has `value`, `threshold` and `input_artefact` sha.
  - It calls `assemble_outcome(rows, criteria_status="FROZEN_PREREG")` and writes `S5_PROMOTION_GATE_REPORT.{json,md}` via `render_rationale`.
  - G1 reports the observed win rate and the cluster lower bound as **two separate fields**.
  - G7 consumes WP2 test results plus shadow-health counts: decode errors 0, leakage 0, coverage of listed station-days.
  - G8 cites the S3 artefact sha and checks that the permit/credentials/caps exist (presence only). It **never reads or assigns an operator cap value**.
  - **It writes no manifest, imports no `runtime.settings`, and writes nothing under `deploy/`.**

**RED-first tests:**

- `tests/unit/test_maker_eval_stats.py::test_purge_drops_one_day_between_dev_and_holdout`
- `tests/unit/test_maker_eval_stats.py::test_holm_matches_reference_values`
- `tests/unit/test_maker_eval_stats.py::test_design_effect_is_one_for_iid_clusters_of_one`
- `tests/unit/test_maker_eval_stats.py::test_adverse_selection_fails_when_filled_loss_rate_exceeds_1_5x_model`
- `tests/unit/test_maker_eval_stats.py::test_adverse_selection_fails_when_filled_exceeds_unfilled`
- `tests/unit/test_maker_promotion_report.py::test_any_false_gate_is_no_proposal`
- `tests/unit/test_maker_promotion_report.py::test_report_refuses_before_read_date`
- `tests/unit/test_maker_promotion_report.py::test_second_read_refuses_overwrite`
- `tests/unit/test_maker_promotion_report.py::test_report_never_writes_under_deploy_or_imports_settings` (AST)
- `tests/unit/test_maker_promotion_report.py::test_g1_reports_point_and_lower_bound_separately`

**Gate:** focused + full + `lint-imports`.

**Completion:** merged; a synthetic end-to-end run yields one PROPOSAL fixture and one NO_PROPOSAL fixture.

### WP5 — PREREG, checker, sequential tally (frozen BEFORE day 1; ~6 h)

**Create:**

- **`docs/evidence/maker/PREREG.json`** (pattern: `docs/evidence/m1v3/PREREG.json`). Keys:
  - `hypothesis`, `spec_sha256`, `family_id`, `manifest_sha256`, `params` (= `config.py` constants), `stations`, `first_shadow_day` = "utc_committer_date(frozen_sha)+1d".
  - `split` `{dev_fraction: 0.6, purge_days: 1, unit: "calendar day of the final revision's own run"}`.
  - `revision_budget: 3`. A revision redeploys and restarts the 60/40 clock; earlier days are dev-only.
  - `holdout_target_rule`: holdout effective n ≥ 200 × max(1, deff_dev if deff_dev > 1.5), counted outcome-blind. Station-day n is also ≥ 200.
  - `calendar_cap_date` (pinned at freeze from the S2 rate; never moved).
  - `read_date_rule`: first date where the target is met **and** every holdout position has CLI FINAL or is past `truth_deadline` = D+14.
  - `cluster_unit: climate_date`, `bootstrap_B: 10000`, `bootstrap_seed`; `alpha_programme: 0.025` (RA-13), `alpha_family` (Q5), `holm_over_revisions: true`.
  - `sequential_stop`, which holds:
    `S_k = Σ(win_i − BE_i)/sqrt(Σ BE_i(1−BE_i))` with `BE_i = b_i + fee_i`; Lan-DeMets OBF, one-sided harm; `look_step: 10` completed positions; `n_max` = projected positions at the cap; `alpha_stop`; output `CONTINUE|STOP` only.
  - `a1_floor` (S3 artefact path + sha + floor mode).
  - `baselines`, `stress`, `adverse_selection`, `gates` (9 rows with thresholds), `voids_rule`, `incomplete_day_rule`, `b3_disclosure` (Risk R-6), `frozen_sha`, `status: FROZEN`.
- **`scripts/analysis/maker_prereg_check.py`.** It reuses `check_frozen_blob`/`_canonical` from `prereg_precommit_check.py` with a maker `_FIELD_CHECKS`. It imports `no_ladder_maker.config` constants and requires equality (no duplicated literals).
- **`scripts/analysis/maker_sequential_tally.py`.** It calls `boundary_for` at the realised information fractions and writes only `{look_n, t, verdict: CONTINUE|STOP}`. It never writes a holdout win rate or expectancy.
- **`scripts/analysis/maker_progress_report.py`.** Counts only: rests, fills, positions by window, truth coverage, days to cap. No outcome field before the read date (M1-v3 R21 pattern).

**RED-first tests:**

- `tests/unit/test_maker_prereg_check.py::test_param_mismatch_with_config_refuses`
- `tests/unit/test_maker_prereg_check.py::test_frozen_sha_must_introduce_blob`
- `tests/unit/test_maker_sequential_tally.py::test_harm_boundary_stops_and_output_has_no_rate`
- `tests/unit/test_maker_sequential_tally.py::test_looks_fire_every_ten_completed_positions`
- `tests/unit/test_maker_progress_report.py::test_no_outcome_field_before_read_date`

**Completion:** the PREREG is its own reviewed commit and `frozen_sha` names it; the checker exits 0; the manifest `d0_climate_day` equals the derived first shadow day; the prereg commit is gated like code (read gate EXIT before push).

### WP6 — Start the shadow run (ops; ~2 h + ~230–320 calendar days)

1. With orders still off (the drop-in untouched; there is no maker allowlist row), set `BREEZY_SENDING_FAMILY_ID=pm_us_no_ladder_maker_v1`. This is a reviewed supervisor-unit edit, landed only after Q2 is ruled. Restart the supervisor in the 01:00–16:40Z window (`KillMode=process` caveat). The node boot log must show the maker composition and **no** live-orders line.
2. Arm the daily timers `breezy-maker-shadow-score.timer` (scorer + progress + sequential tally). Each has `RuntimeMaxSec`, `MemoryMax`, a no-progress stall event and a subset benchmark before the first full run. Only one heavy job at a time; slot it outside the nightly study window.
3. **Liveness** = process + log mtime + JSONL advancing + tape advancing. The first scheduled timer success must be *seen* before the run is called LIVE.

**Completion:** first scheduled success observed, plus a 7-day health check with zero decode errors and zero leakage refusals. Then wait for the read date or a STOP.

## 6. Data and tooling dependencies

| Input | Path | Status |
|---|---|---|
| Quote/Depth10 + trade-print tape | quote-tape catalog root (settings `QUOTE_TAPE_CATALOG_VAR`), under `~/.local/share/breezy/catalog` | exists; trade-print census coverage after 2026-09-25 is S1's |
| Settlement truth | `~/.local/share/breezy/derived/settlement-truth/settlement_truth.parquet` | exists (verified on disk) |
| Calibration artefact | `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` | exists. **UNVERIFIED** that it is calibrated in the p_NO ≥ 0.94 tail; S2's win-vs-p_NO table is the only evidence |
| S2 fill simulator | `scripts/analysis/<S2 module>` | **UNVERIFIED** until WP0 |
| S3 A1 artefact | `docs/evidence/maker/A1_REACHABILITY_*.md` | **UNVERIFIED** until WP0 |
| Shadow JSONL | `~/.local/share/breezy/maker_shadow/` (sibling of the catalog) | created by WP2 |
| Node log | Popen stdout log files (never journald) | existing convention |

## 7. Risks and invariant guards

| # | Risk | Invariant at stake | Guard |
|---|---|---|---|
| R-1 | Maker code path sends a real order | live enablement / NO-SEND | literal `shadow_only=True`; the unchanged AST guard; no allowlist row; `test_strategy_never_calls_submit_or_cancel`; the orders-off drop-in kept; exec firewall tests in every focused list |
| R-2 | Widening the kind exact-sets is mistaken for relaxing them | L-12 | one reviewed row per exact set; tests assert equality, never subset |
| R-3 | `allow_short` drift | allow_short False | config default test; NO bought as the NO instrument only |
| R-4 | `evaluate_order` is taker-shaped and mis-refuses or mis-admits bids | §4 limits (gate 5) | WP0 decides; refusals counted and logged; gate 5 reads them |
| R-5 | Holdout peeked via progress/tally output | read-once (§6.2) | counts-only progress; tally emits CONTINUE/STOP only; tests for both |
| R-6 | RA-13 B-3: any statistic on post-2026-09-25 tape spends H-ARCHIVE-RECAL CONFIRM days | RA-13 firewall | disclosed in PREREG `b3_disclosure`; peer review must accept it before freeze |
| R-7 | Operator caps touched | operator-reserved controls | G8 checks presence only; grep-based test that no maker file assigns a cap |
| R-8 | Frozen PREREG edited / date moved | never edit frozen PREREG | introducing-commit check; a revision means a new PREREG *version file*, never an edit |
| R-9 | Agents format whole dirs, or touch the byte-pinned exec client | exec byte pin | "format only your files"; `git status` stray check before commit |
| R-10 | Long daily jobs stall silently | ops | RuntimeMaxSec + no-progress event + subset benchmark |

## 8. Sample clock (stated honestly)

- **Positions per day.** 4 stations × ~0.91 listed × ≤ 2 rungs ≈ 7.3 rested rung-days/day. At a 0.3 fill rate that is **≈ 2.2 positions/day** (spec §9.15). Station-days with ≥ 1 position ≈ 3.64 × (1 − 0.7²) ≈ **1.9/day**.
- **The brief's "~100 days" reaches 200 positions *in total*, not 200 on the holdout.** §6.4 and gate 2 need ≥ 200 *effective* holdout positions and ≥ 200 holdout station-days. Holdout = 40% of days after a 1-day purge.
  - With deff ≈ 1.0–1.4 (≈ 2.2 positions per climate date), the holdout needs ≈ 105–130 days. The total run is then **≈ 230–320 days**: start ≈ late Nov 2026, read ≈ Jul–Oct 2027.
  - A fill rate of 0.15 doubles that. Any revision restarts the clock.
- **The run crosses 2027-01-25** (the NO-TRADE review / RA-13 KILL backstop) and the M1-v3 read (≥ 2026-12-07).
- **Read-date rule:** first date where the outcome-blind count target is met and truth is FINAL (or past the D+14 deadline). If not met by `calendar_cap_date` → UNDERPOWERED = FAIL.

## 9. Effort and evidence artefact

- **Build:** WP0 1 h · WP1 5 h · WP2 8 h · WP3 8 h · WP4 8 h · WP5 6 h · WP6 2 h, plus ≈ 8 h of reviews and gates: **≈ 46 agent-hours**. **Calendar:** ≈ 230–320 shadow days before a read.
- **Single evidence artefact:** `docs/evidence/maker/S5_PROMOTION_GATE_REPORT.md` (+ `.json`). On early stop it is replaced by `docs/evidence/maker/S5_SEQUENTIAL_STOP_<date>.md`.

## 10. Open questions for peer review (max 5)

1. **Sample clock vs spec.** Spec v0.2 §6.2/§6.4 (60/40 + ≥ 200 effective holdout) implies a ≈ 230–320-day shadow, not ~100. Accept that, or issue spec v0.3 (e.g. zero planned revisions → smaller dev fraction) **before** the freeze? It can never change after the freeze.
2. **Cardinality-1 sending slot.** The shadow run requires `BREEZY_SENDING_FAMILY_ID=pm_us_no_ladder_maker_v1`, which displaces the composition of `pm_us_crh_fq_v1` (terminal 2026-10-05, orders off). Is this a coordinator act, given that orders stay off by two independent keys? Does any FQ-v1 shadow consumer still need to run?
3. **Sequential stop vs read-once.** The harm-only LD-OBF stop looks at outcomes during the holdout calendar span. Does a CONTINUE/STOP-only output preserve the read-once holdout, or must the stop run on dev days only?
4. **Forecast-age cancel vs NBP cadence.** NBP cycles at 13Z/19Z/01Z leave a 12 h gap. With age > 6 h, every bid cancels ≈ 07Z–13Z. MIA's 09:00 LST cancel (14Z) leaves ≈ 1 h of D-morning resting. Should age be measured from `cycle_runtime` or `available_at`? Implement literally, and only report the effect?
5. **α allocation.** Register `alpha_family` via `hypothesis_ledger.register_hypothesis` (AUD-18 ledger), or pin it in PREREG with a ruling if the ledger's gates reject the maker shape? What share of the RA-13 0.025 does the maker family get, given that M1-v3 and the stop both draw on it?

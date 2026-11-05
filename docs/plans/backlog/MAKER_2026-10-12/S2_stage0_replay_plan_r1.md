# S2 — Stage 0 exploratory maker replay (plan)

| Field | Value |
|---|---|
| ID | S2 |
| Title | Stage 0 exploratory maker replay: fill simulator + adverse-selection screen |
| Revision | r1 |
| Date | 2026-10-12 |
| Status | DRAFT (needs peer review before any build) |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.2, §3, §6.0, §6.1, §6.7 (2× only), §6.9 |
| Emits | `docs/evidence/maker/STAGE0_REPLAY_<YYYY-MM-DD>.md` (single evidence artifact) |

Hard invariants (binding on every WP and every brief): Nautilus Trader is immutable (no patch, fork, bypass,
reimplementation). `allow_short` stays `False`. Never weaken or delete a safety, settlement, contract, or NO-SEND
egress-firewall test; exact-set barriers are WIDENED by one reviewed row, never relaxed (L-12). Never assign a value to
the operator-reserved controls (max daily budget, max per position). Never touch live-trading enablement or
`BREEZY_ORDERS_ENABLED`. Never edit a frozen `PREREG.json` or move a pre-registered date. **Stage 0 output is
EXPLORATORY and never promotion evidence.** The FQ-v2 NO-TRADE ruling stays in force; this is its T2 route.
S2 touches `scripts/analysis/` and `tests/unit/` only: no `src/`, no exec, no strategy, no `deploy/`.

## 1. Goal state (acceptance test)

Done when `docs/evidence/maker/STAGE0_REPLAY_<date>.md` exists, is committed, and carries all of these:

1. Inputs pinned by sha256: S1 census-day list, S1 `TRADE_QUANTITY_UNIT` resolution, the FQ v1 calibration artefact
   (`9c0b6d6e…923a5e`), the truth file, and the git commit of the replay code.
2. Station-day accounting: eligible, and excluded by named reason (not censused, print stream not covering the bid
   window, no forecast, no FINAL truth, not listed by D−1 12:00Z, NYC).
3. **Maker fill rate**, under the base §6.1 rule and under the **mandatory 2× displayed-size stress**.
4. Realised bid distribution (1-cent histogram), on fills and on all placed bids.
5. Win rate of simulated fills next to the fills' mean model p_NO, with a climate-date cluster-bootstrap 95% CI.
   Point estimate and lower bound reported as two separate numbers.
6. The §6.9 adverse-selection statistic (T1 and T2 below), per p_NO stratum and pooled, with one-sided
   cluster-bootstrap p-values and cluster counts.
7. Net expectancy per fill, `w − (b + θ·b·(1−b))` at taker θ, with a cluster CI (descriptive only).
8. A verdict line: `GO` / `NO-GO` per spec §6.0, with the exploratory label.

## 2. Entry criteria and STOP conditions

Entry (all must hold before WP1 starts):
- E1. S1 has delivered (a) a censused-day list and (b) a resolved `TRADE_QUANTITY_UNIT` with a conversion to contracts.
  Both are taken as **inputs with paths** (`--census-days`, `--trade-unit`); S2 never re-derives them.
- E2. The NBP derived store covers every replayed climate day (WP0 step 3; today it ends at cycle
  `nbp_20260929_19z`, verified on disk).
- E3. No other heavy job is running on the host (one heavy job at a time).

STOP conditions:
- S-1 (programme end, spec §6.0): base fill rate `< 0.10` **or** §6.9 FAIL ⇒ verdict `NO-GO`; the family stops at
  v0.2 with no build. S4/S5 are not started.
- S-2 (this step, before the run): WP0's aggressor-direction check is contradictory or inconclusive (Section 5, WP0).
  The fill rule cannot be stated. Stop and send it back to the spec instead of guessing a direction.
- S-3 (this step): the unit from S1 is still `UNRESOLVED`. Spec §9.3 blocks §6.1. Stop.
- S-4: fewer than 10 climate dates survive eligibility. Report `NOT_COMPUTABLE`. That is not `GO`, and S5 needs a ruling.
- S-5: the subset benchmark predicts a run longer than 6 h or peak RSS above 4 GiB. Fix the reader first, then run.

## 3. Simplest direct path

One read-only script replays every eligible (station, climate day). For each day it reads that day's YES-leg Depth10
frames and trade prints from the Nautilus catalog, takes the NBP vector visible at each instant (artefact-calibrated
p_NO per rung), applies the §3 bid rule, and credits fills under §6.1. Fills are then scored against NWS CLI FINAL
truth with the repo's existing cluster bootstrap. Five small modules hold the new logic: inputs, p_NO, the rule, the
fill simulator, and the statistics. A thin driver calls them.

Nothing heavier is justified: no Nautilus strategy, no BacktestEngine run, no new persistence. The decision this step
informs is binary (GO/NO-GO). The only added rigour is what spec §6.0 and §6.9 name, plus the leakage guards. Each
guard has a concrete payoff: lesson "an implausible result is a leak" says an hour-of-day window over a D−1..D+1 tape
manufactured a +0.55 per-take edge.

**Scope correction to spec §6.0 (measured, not assumed).** The spec says the replay covers "2026-08-30 → last
censused day". But trade prints exist only from **2026-09-17** (181 prints), 09-18 (4,223), and fully from 09-19.
The census is 303,686 prints in 2,808 parquet files, 30 rungs/day. Fills cannot be simulated without prints, so the
replayable sample is about **climate days 2026-09-19 → min(last censused day, last FINAL truth day = 2026-10-11)**:
roughly 23 days × 4 stations ≈ 92 station-days and ≤184 rung-bids. Depth-only days before 09-19 are not used.

## 4. Nautilus null-hypothesis check

| Need | Native capability checked | Verdict |
|---|---|---|
| Read Depth10 + trade prints | `ParquetDataCatalog` `order_book_depth10(...)` / `trade_ticks(...)` → `query(data_cls, identifiers, start, end)` (`nautilus_trader/persistence/catalog/base.py:158,176,221`; impl `parquet.py:1648`). The quote tape is a native catalog layout (`data/order_book_depths/<id>/…`, `data/trade_tick/<id>/…`). | **Reuse.** Every read is scoped to one instrument and an absolute-ns window. |
| Queue-position maker fills | `BacktestVenueConfig.queue_position` + `trade_execution` (`backtest/config.py:114-124`): "fill after the quantity ahead … traded through **or the price level is deleted**" | **Not used for Stage 0**, for evidence-based reasons: (a) the matching engine lets a `NO_AGGRESSOR` print match **both** sides (`backtest/engine.pyx:4689-4692`), but §6.1 says such prints are never credited; (b) a deleted level credits a fill, which is more optimistic than §6.1; (c) the 2× displayed-size stress is not a config parameter; (d) the tape records only the YES book and YES prints (`parsing.py` `parse_trade_tick` docstring; 0 NO-leg depth dirs on disk). An engine run would need a synthetic inverted NO instrument, i.e. the same transformation this plan writes, plus a full `Strategy`. That is S5's native path, not a one-shot screen. |
| Forecast visibility | `ForecastQuantileState.push/value_at` (`src/breezy/strategy/ladder_ev/forecast_state.py:245,310`): latest **complete** vector with vintage ≤ now | **Reuse** (Breezy extension, not Nautilus). One state per (ICAO, target climate day). |
| Calibrated rung probability | `load_live_calibration` (`forecast_quantile_ladder/calibration_artefact.py:236`, sha-pinned), `LiveCalibration.resolve` (`:134`), `rung_probability_interval` (`src/breezy/domain/quantile_density.py:393`, `P = F(hi+.5) − F(lo−.5)`, i.e. inclusive integer labels) | **Reuse.** |
| Rung facts / inclusive bands | `bucket_facts_from_instrument_id` (`src/breezy/analysis/labeling/instrument_facts.py:72`, `gte{A}lt{B}` → `[A,B]` inclusive) | **Reuse.** Never re-parse slugs. |
| MAX-column → climate day | `max_column_lst_climate_day` (`src/breezy/ingest/nbm_quantile_parse.py:187`) | **Reuse.** Never "nearest column" (memory: the nearest-column day assumption was wrong once). |
| Cluster bootstrap | `bootstrap_cluster_draws`, `percentile_interval`, `SupportsClusterKey` (`src/breezy/analysis/stats/scoring_core.py:216,246,199`) | **Reuse.** The repo's "ONE resampling loop". Records carry `cluster_key("date")`. |
| Lagged observations | `RunningExtremeAccumulator` (`weather_common/running_extreme.py:225,266`), `iem_asos_rows_to_station_observations`; pattern from `current_rung_hold_resting_bid_study.py:222-262` | **Reuse** for the §3 observation hard cancel. |
| Reporting pattern | `resting_bid_report.GateResult` / `render_markdown` (`scripts/analysis/resting_bid_report.py:36,165`) | **Reuse** `GateResult`. A new renderer (different tables). |

What rest_v5 did and lacked (`current_rung_hold_resting_bid_study.py`, `resting_bid_core.py`, `RESTING_BID_HUNT` §2.1–2.2):
- It simulated fills by a **crossing-event proxy** (ask transition through p*, × queue share s). It had **no trade prints**.
- Its adverse-selection estimator was a **lower bound** (lines 162-177).
- Its climate-day bootstrap was a hand-written loop (`_bootstrap_lower_bound`, `:293`), not the shared one.
- It priced p from the frozen archive table, not a forecast.

S2 replaces the proxy with print-based fills (the §2.2 "intended" re-run) and reuses only these parts: the
`leg_ask_price` leg-inversion convention (`resting_bid_core.py:274-297`, NO ask = 1 − YES best bid), the observation
lag pattern, and `GateResult`.

**Genuinely new (three things, as the spec §9.5/§9.6 says):**
1. **p_NO loader.** `P(high ∈ [A,B])` inclusive for an arbitrary rung at an arbitrary instant. The FQ `evaluate` path
   cannot be used: it returns `NotDPlus1` (`decision.py:277-281`) and the family is under the permanent F6 veto.
   **Stage 0 is offline analysis, so neither the D+1 gate nor the F6 veto applies.** That is stated in the evidence
   doc. It authorises nothing live.
2. **Maker fill simulator** (§6.1).
3. **§6.9 test.**

## 5. Work packages

Code location and conventions: `scripts/analysis/maker_stage0_*.py` (package imports `from scripts.analysis.… import`,
as in `fq_loss_taxonomy_reconstruct.py:27`), tests in `tests/unit/test_maker_stage0_*.py`. Each module stays under
400 lines and functions under 50 lines. Pure modules do no I/O.

Focused gate for every WP (run in the worktree, `PYTHONPATH=<wt>/src`, shared venv interpreter by exact path, never uv
or pip):
`scripts/ci/run_tests_no_egress.sh tests/unit/test_maker_stage0_*.py <firewall guards + import gates> --basetemp ~/.cache/breezy-pytest/s2-<wp>`.
Read EXIT, then `rm` the basetemp. Then `cd <wt> && lint-imports` (demand "N kept, 0 broken"). Then
`ruff check`/`ruff format` on **own files only**. Run the full gate once after merge.

### WP0 — Data readiness and the inversion check (read-only probe; result recorded, ~2 h)

Files: `scripts/analysis/maker_stage0_probe.py`; test `tests/unit/test_maker_stage0_probe.py`.
Interface: `probe(catalog_root: Path, days: Sequence[date], stations: Sequence[str]) -> ProbeReport` (frozen dataclass,
`to_dict()`).

1. **Aggressor-direction check (STOP S-2).** A resting NO bid at `b` is a virtual YES ask at `a = 1 − b`. A taker who
   sells NO into it is a YES buyer. So a matched print **should** be aggressor `BUYER` at YES price `≥ a`, i.e. NO
   price `≤ b`, which matches spec §6.1's NO-terms rule. Spec §6.1's precondition sentence ("YES print at price ≤ 1−b
   with aggressor SELLER") contradicts its own NO-terms rule; the plan treats it as a spec erratum. The probe decides
   empirically, per print, against the last Depth10 frame at or before `ts_event`:
   - `BUYER` prints should sit at ≥ the prior best YES ask, and `SELLER` prints at ≤ the prior best YES bid.
   - Report the agreement fraction per side.
   - If agreement ≥ 0.9 on both sides, the mapping is fixed. If agreement ≤ 0.1, the venue's convention is inverted
     and the mapping flips; record that. Anything in between triggers S-2.
2. Print census inside the replay window. Spot-measured today: BUYER 152,176 / SELLER 151,510, **zero
   `NO_AGGRESSOR`**, zero duplicate `trade_id`s, zero opposite-side twins in an SFO 10-0x sample. Re-assert all three
   on the replay window.
3. Data gaps, checked by assertion and fixed with existing tools only:
   - NBP store: run `scripts/analysis/nbp_backfill.py --apply --start 2026-09-29 --end <last day>`. This is an
     existing, manifest-idempotent tool; it fetches through the hardened allowlisted transport.
   - Truth: `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` (fresh through 2026-10-11). The
     `settlement-truth/settlement_truth.parquet` file is stale at 2026-09-28; it is used only as an overlap
     cross-check, and any disagreement is a STOP.
   - Observation rows for the §3 kill-switch: use the existing obs store, or else the IEM cache path used by the rest_v5
     study. The probe names which one.

RED tests first: `test_buyer_print_above_prior_best_ask_counts_as_ask_lift`, `test_inconclusive_agreement_returns_stop_s2`, `test_no_aggressor_prints_are_counted_not_dropped_silently`.

Done when: the `ProbeReport` JSON is written to the S2 scratch/derived dir, the mapping is fixed or S-2 is raised, and
the NBP and truth coverage assertions pass.

### WP1 — Inputs (`maker_stage0_inputs.py`, ~2 h)

Interfaces:
- `load_census_days(path: Path) -> frozenset[tuple[str, date]]`: schema-asserted; refuses unknown keys or an empty set.
- `load_trade_unit(path: Path) -> TradeUnit`: refuses `UNRESOLVED`. `TradeUnit.to_contracts(size: Decimal, yes_price: Decimal) -> Decimal`.
- `load_truth(csv: Path, cross_check: Path | None) -> Mapping[tuple[str, date], int]`: FINAL tmax only; corrected rows
  take the final revision; a conflict raises.
- `load_model() -> LiveCalibration`: path and sha read from `deploy/families/pm_us_crh_fq_v1.json`
  (`density_artefact_path`, `density_artefact_sha256`), through `load_live_calibration`.

RED tests first: `test_unresolved_trade_unit_is_refused`, `test_truth_conflict_between_sources_raises`, `test_census_list_with_nyc_is_filtered_and_counted`, `test_artefact_sha_mismatch_refuses`.

### WP2 — p_NO loader (`maker_stage0_pno.py`, new item 1, ~3 h)

Interfaces:
- `ForecastBook.from_store(nbp_root: Path, stations, days) -> ForecastBook`. Pushes each MAX-column row into a
  `ForecastQuantileState` keyed by `(icao, max_column_lst_climate_day(row))`, using the row's own `available_at_ns`.
- `ForecastBook.vector_at(icao, climate_day, now_ns) -> ForecastQuantileVector | None`.
- `ladder_p_yes(vector, ladder: Sequence[WeatherBucketFacts], calibration, latitude) -> Mapping[str, PYes]`, where
  `PYes(point, lower, upper)`. Built on `rung_probability_interval` over the station-day's **actual** ladder when it is
  a complete partition. Otherwise it falls back to a per-rung complement ladder (`target`/`below`/`above`, 8 lines,
  written locally because `fq_loss_taxonomy_reconstruct._complement_ladder` is private). Returns `p_no = 1 − point`.
- The modal rung (for the "never adjacent to modal" rule) is the argmax of `point` over the ladder.

Guards:
- `vector.available_at_ns < now_ns` is asserted, strictly.
- `vector.climate_day == instrument climate_day` is asserted.
- An unknown NBM era returns `None` (no bid) and is counted, never pooled.

**Verify-first STOP (in the brief):** before writing selection code, print `max_column_lst_climate_day` for one real
cycle per cycle hour, and assert it against `climate_day_for_txn` and one CLI FINAL day. Memory records that a
reviewer's ftime assumption was wrong once.

RED tests first: `test_inclusive_band_probability_uses_hi_plus_half_and_lo_minus_half`, `test_vector_not_yet_available_is_invisible`, `test_column_for_other_climate_day_is_never_selected`, `test_unknown_era_yields_no_reading_not_a_pooled_one`, `test_open_tail_rung_probability`.

### WP3 — §3 rule (`maker_stage0_rule.py`, pure, ~2 h)

Interfaces:
- `select_rungs(p_yes_by_rung, modal_rung, ladder_order) -> tuple[str, ...]`: ≤2 rungs with the lowest p_YES among
  those passing `P_MIN = 0.94`; never adjacent to modal.
- `bid_price(p_no, best_no_bid: Decimal | None, theta) -> Decimal | None`:
  - `b_max = min(0.80, p_no − 0.10 − θ·b·(1−b))`, solved on the 1-cent grid, taking the largest `b` that satisfies it;
  - `None` if `b_max < 0.50`;
  - `min(b_max, best+0.01)`; `b_max` when the NO bid side is empty.
- `hard_cancel_ns(climate_day, std_utc_offset_hours) -> int`: D 09:00 LST. Integer-ns arithmetic, same idiom as
  `replay_sufficiency.decision_window_ns`, which itself is **not** reused: its bounds are the taker `[12:00,17:00)`
  window, and the maker window ends at 09:00.
- `obs_cancel(running_max: RunningMax | None, rung_lower_f: int | None) -> bool`: cancel when
  `running_max.upper_f ≥ A − 2`. The interval upper end already carries the integer-°C 1.8 °F ambiguity.
- `forecast_stale(vector, now_ns) -> bool`: true when vintage age exceeds 6 h.

Constants: `P_MIN`, `B_CAP`, `E_MIN`, and `B_FLOOR` are module constants copied from the spec, with a test pinning
them to spec v0.2.

RED tests first: `test_bid_is_best_plus_one_cent_capped_at_b_max`, `test_empty_no_bid_side_places_at_b_max_not_an_implied_price`, `test_b_max_below_floor_cancels`, `test_two_rung_bound_and_modal_adjacency`, `test_hard_cancel_is_0900_standard_not_daylight_time`, `test_constants_match_spec_v0_2`.

### WP4 — Fill simulator (`maker_stage0_fill.py`, pure, new item 2, ~3 h)

Interface: `simulate(events: Sequence[Event], *, displayed_multiplier: int, unit: TradeUnit) -> tuple[BidEpisode, ...]`.
- Events are time-ordered depth, print, forecast-release, observation-visible, and cancel events for **one**
  (station-day, rung).
- `BidEpisode` holds: `t0_ns`, `bid`, `q0`, `filled_ns | None`, `cancel_reason`, `p_no_at_t0`, `p_yes_upper_at_t0`,
  `forecast_vintage_ns`, `depth_ts_used_ns`.

Rule (YES-book terms, direction fixed by WP0):
- Resting at `a = 1 − b`.
- `Q0` = Σ YES ask size at price ≤ `a` in the last frame at or before `t0` (the NO bids at ≥ b).
- `V` = Σ contracts of matched prints (aggressor per WP0, YES price ≥ `a`) with `t0 < ts < cancel`.
- Filled when `V ≥ m·(Q0 + 1)`, where `m = 1` is the base rule and `m = 2` is the mandatory stress.
- `NO_AGGRESSOR` is never credited.
- Any price change is a cancel-replace: a new `t0` and a new `Q0`.
- An empty NO bid side places at `b_max` and never credits an implied price.
- After a fill, the position is held: no further bids on that (station-day, rung).

Leakage asserts, raised and never logged-and-continued:
- `forecast_vintage_ns < t0_ns ≤ filled_ns`;
- `depth_ts_used_ns ≤ t0_ns`;
- every credited print satisfies `t0_ns < ts < hard_cancel_ns`.

Reads are scoped by **instrument (which encodes the climate date) AND absolute ns**, never by hour-of-day.

RED tests first: `test_queue_ahead_must_trade_through_before_fill`, `test_replace_resets_queue_and_t0`, `test_no_aggressor_print_never_fills`, `test_wrong_side_print_never_fills`, `test_print_after_hard_cancel_never_fills`, `test_double_displayed_stress_needs_twice_the_volume`, `test_forecast_vintage_after_t0_raises`, `test_simulator_module_does_not_import_truth` (an import-graph assertion: truth is unreachable from the simulator).

### WP5 — Statistics (`maker_stage0_stats.py`, new item 3, ~2 h)

Records: `ScoredBid(station, climate_day, rung, filled, bid, p_yes, stratum, yes_settled)` implements
`cluster_key("date") -> climate_day`, so it plugs into `bootstrap_cluster_draws`.

Metrics:
- **Fill rate**: filled episodes ÷ eligible (station-day, rung) pairs that had ≥1 resting bid.
- **Win rate**: per §3 table semantics.
- **Net expectancy**: `w − (b + θ·b·(1−b))` at the taker θ (0.0695). The maker coefficient is not on the wire; the
  taker coefficient is the conservative cost, and this is stated.

§6.9 test, with strata `[0.94,0.96)`, `[0.96,0.98)`, `[0.98,1]`:
- `T1 = L_filled − 1.5·mean(p_yes | filled)`.
- `T2 = L_filled − L_unfilled`. Unfilled bids are scored counterfactually on the same truth.
- One-sided p = share of cluster-bootstrap draws with `T ≤ 0`. **FAIL** if pooled p < 0.05 for T1 or T2.
- Per-stratum values are descriptive.
- With fewer than 2 filled losses overall, the result is **INCONCLUSIVE**. That is not FAIL and not PASS; it is
  printed as underpowered, with the expected count of YES settlements shown.

Verdict function: `verdict(fill_rate_base, s69) -> Literal["GO","NO-GO","NOT_COMPUTABLE"]`.

RED tests first: `test_t1_fails_on_gross_adverse_selection_fixture`, `test_t2_compares_filled_to_unfilled_in_same_stratum`, `test_bootstrap_clusters_by_climate_date_not_position`, `test_fill_rate_below_0_1_is_no_go`, `test_inconclusive_is_neither_pass_nor_fail`, `test_point_estimate_and_lower_bound_are_separate_fields`.

### WP6 — Driver and report (`maker_stage0_replay.py`, ~2 h, then the run)

CLI: `--census-days PATH --trade-unit PATH --catalog-root ~/.local/share/breezy/catalog/quote_tape/polymarket_us --nbp-root ~/.local/share/breezy/derived/nbp --truth PATH --out-dir ~/.local/share/breezy/derived/maker_stage0/<run_id> [--stations SFO --days N]`.

Flow:
- Per station-day: open the catalog, query depth and prints per rung for `[first frame, hard_cancel)`, build events,
  simulate (m = 1 and m = 2), and append episode JSONL.
- Write one progress line per station-day to `progress.jsonl`; this is the stall-watch signal.
- Score only after every station-day has been simulated, by a separate function. Truth is loaded only there.
- Render the evidence Markdown, with the exploratory banner and the input shas.

RED tests first: `test_driver_scores_only_after_simulation_completes`, `test_report_carries_input_shas_and_exploratory_banner`, `test_progress_line_per_station_day`.

**Run plan.** These are commands for the executor; nothing runs during planning. Use a quiet window: avoid the
02:05Z nightly and the 10–24 GB study windows. One heavy job only.

1. Subset benchmark: `--stations SFO --days 5`, under a transient unit:
   `systemd-run --user --unit maker-s0-bench -p MemoryMax=4G -p RuntimeMaxSec=1800 -p LimitNOFILE=524288 <venv python by exact path> -m scripts.analysis.maker_stage0_replay …`.
   Read `memory.peak` and wall time.
2. Extrapolate to the full set (≈92 station-days ≈ 18× the subset). Set `RuntimeMaxSec = 3×` the estimate, capped at
   6 h (S-5), and `MemoryMax = 2×` measured peak, capped at 4G.
3. Full run `maker-s0-full` with the same flags. Arm a Monitor in the launch turn that watches `progress.jsonl` mtime.
   No new line for 20 min means a stall: stop the unit and inspect. Wait on `ActiveState ∉ {active, activating}`,
   never `is-active`.
4. Read the exit status. Copy the rendered Markdown to `docs/evidence/maker/`. Commit the code plus evidence (explicit
   paths). Push per milestone policy.

## 6. Data and tooling dependencies

| Item | Path | State (checked 2026-10-12) |
|---|---|---|
| Depth10 (YES leg only) | `~/.local/share/breezy/catalog/quote_tape/polymarket_us/data/order_book_depths/<id>/` | present; 1,295 instrument dirs; 0 NO-leg dirs |
| Trade prints | `…/data/trade_tick/<id>/` | 2,808 files, 303,686 prints, 2026-09-17 → 10-12; 0 `NO_AGGRESSOR` |
| Instrument defs / fee θ | `…/data/binary_option/` | present; per-market `feeCoefficient` **UNVERIFIED** in defs → default 0.0695 (θ drift 09-17) |
| NBP derived store | `~/.local/share/breezy/derived/nbp/` | **ends 2026-09-29 19z** → WP0 backfill |
| Calibration artefact | `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json`, sha `9c0b6d6e…923a5e` | present |
| Truth (primary) | `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` | through 2026-10-11 |
| Truth (cross-check) | `~/.local/share/breezy/derived/settlement-truth/settlement_truth.parquet` | stale at 2026-09-28 |
| Observations (kill-switch) | obs collector store or IEM cache | **UNVERIFIED** → WP0 names it |
| S1 outputs | census list + unit resolution (paths from S1) | **not yet delivered** (E1) |

UNVERIFIED and flagged:
- Whether the FQ v1 artefact, fit on the D+1 nearest-column lead, is calibrated for D−1/D-morning leads and for the
  p_NO ≥ 0.94 tail. The report includes a p_NO reliability table over **all** placed bids, by lead bucket.
- Exact `ParquetDataCatalog.query` kwargs in 1.231 (`start`/`end` types): WP0 confirms them on one instrument.

## 7. Risks and guards

| Risk | Invariant or lesson at stake | Guard |
|---|---|---|
| Look-ahead via forecast or window | no leakage (§7.6); "implausible result is a leak" | strict vintage `< t0`; absolute-ns windows from instrument date; truth unreachable from simulator (test) |
| Wrong aggressor direction → fills invented or missed | correctness | WP0 empirical check + STOP S-2 |
| 2× stress vacuous when `Q0 = 0` (we are top-of-book) | §6.7 mandatory stress | stress is `V ≥ 2·(Q0+1)`, not `2·Q0` (open question 2) |
| Optimistic queue: other makers joining ahead after `t0` are ignored | bias direction | stated in report; 2× is the only mitigation the spec asks for |
| §6.9 underpowered (~4–7 expected YES settlements) | "underpowered verdict describes the sample" | INCONCLUSIVE label, expected-count line; never reported as PASS |
| Stage 0 numbers read as promotion evidence | Stage 0 never promotion evidence | banner + verdict text; no PREREG touched |
| Shared venv / tree damage | never uv/pip from worktree; no stash in the shared tree | exact interpreter path in briefs; commit by explicit path |
| Memory blow-up or silent stall | one heavy job; long runs need stall watch | per-instrument scoped reads; MemoryMax; RuntimeMaxSec; progress Monitor |
| Agent reformats whole dirs | lesson "agents run ruff format on whole dirs" | format own files only; check `git status` for strays |
| Egress | NO-SEND firewall | replay has no network; NBP backfill is a separate existing tool step |

S2 cannot violate `allow_short`, the operator caps, enablement, or the exec firewall: it imports no exec, runtime, or
deploy code. A test asserts that the S2 modules import nothing under `breezy.adapters.polymarket_us.exec` or
`breezy.runtime`.

## 8. Effort and artifact

WP0 2 · WP1 2 · WP2 3 · WP3 2 · WP4 3 · WP5 2 · WP6 2 · review fixes and gates 2; run wall ≈1–3 h after the benchmark.
Total is about 18 agent-hours. Single evidence artifact: `docs/evidence/maker/STAGE0_REPLAY_<date>.md`.

## 9. Open questions for peer review (max 5)

1. **Aggressor direction.** Spec §6.1's precondition sentence (SELLER, YES ≤ 1−b) contradicts its NO-terms rule (NO
   ≤ b ⇒ YES ≥ 1−b, taker = YES buyer). Is the WP0 empirical check against prior best bid/ask sufficient to fix the
   direction, and should the spec get a v0.3 erratum regardless?
2. **Stress definition.** `V ≥ m·(Q0+1)` versus the literal "traded ≥ 2× displayed". The literal form is vacuous
   when our best+1¢ bid has `Q0 = 0`, which is the common case. Accept `m·(Q0+1)`?
3. **Verdict input.** §6.0 says "fill rate < 0.1 ⇒ NO-GO" without saying base or stressed. The default is the base
   rule (as written), with the 2× rate printed beside it. Should NO-GO trigger on the stressed rate instead, given that
   base is optimistic by construction?
4. **§6.9 pooling.** Pooled T1/T2 decide; per-stratum is descriptive (strata have ~1–3 expected losses each). Is the
   INCONCLUSIVE ≠ FAIL treatment correct under §6.0, or should Stage 0 require a minimum count before a GO is allowed?
5. **Calibration transfer.** Is using the FQ v1 artefact (D+1 lead fit) for D−1/D-morning p_NO acceptable for a
   screen, given that the reliability-by-lead table is reported? Or must S2 first refit or verify tail calibration on
   the 2021–2026 NBP archive?

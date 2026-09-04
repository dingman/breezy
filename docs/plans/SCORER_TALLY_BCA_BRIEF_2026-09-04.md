# 6c settlement scorer + 6d nightly live-family tally + 6e BCa — build brief (2026-09-04) — DRAFT, under peer review

Produced by code-architect, verified against source at `2cf42e5`. Consumers: `docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md` build-order items 6c/6d. **6e (added by the coordinator):** the BCa bootstrap lower bound on realized ROI (`EXEC_SPINE_2026-09-01.md` §R-9, test 10, Wald refused) is the STOP-GATE quantity and is NOT BUILT; it must land before the live family can reach n≈150 (~2026-10-30), as a pure estimator over 6c's scored rows with `exit_guard.compute_trade_returns` as its input and an exclusion-fraction ceiling (`exit_guard.py:30-34`). It is independent of everything unlanded and is queued directly after 6c.

## 6c — settlement scorer (`held`, `pnl` per filled trial)

### L-1 verdicts (nautilus-trader 1.231.0, installed under `.venv/lib/python3.13/site-packages/nautilus_trader/`)
| Need | Verdict | Evidence |
|---|---|---|
| Fee-inclusive realized P&L per trade | **NATIVE EXISTS, DECLINED FOR THIS INCREMENT** — `Position.realized_pnl` seeds from `-fill.commission` (`model/position.pyx:902`) and accumulates (`:917-922`), `commissions()` at `:864`. Declined because it requires a live exec client and R-9's settlement close; `src/breezy/adapters/polymarket_us/exec/` is empty (EXEC_SPINE §"What blocks R-9") — i.e. unlanded. |
| Settlement close / expiry booking | NATIVE **absent live** — verified in EXEC_SPINE R-9 null-hypothesis (`backtest/engine.pyx:5934-5980` only). Not this increment's job. |
| Containment predicate | BREEZY-OWNED, EXISTS — `WeatherBucketFacts.contains` (`src/breezy/domain/weather_bucket_facts.py:64-73`); closed at both finite ends. **Reuse, do not re-derive.** |
| FINAL-vs-preliminary supersession | BREEZY-OWNED, EXISTS — `read_climate_day_including_corrections` (`src/breezy/persistence/catalog.py:620-625`) + `open_station_catalog` (`:391`); the three-condition grade test `is_settlement_grade` (`scripts/analysis/cli_basis_offer_gate_settlement.py:147-161`) and `settlement_outcome` (`:165-180`). Script-side and therefore **not importable from `src/`** — port the predicate into `src/breezy/settlement/`, and have the script's own tests keep pinning its copy (do not delete it). |
| Append-only row store | **GENUINE GAP for a queried table.** `SqliteStateStore` (`runtime/sqlite_store.py:88`) is key→BLOB with `get`/`set`/`close` only (`:155,168,178`) — no iteration, no aggregation; 6d must scan. Use plain pyarrow parquet (repo already depends on it) under `derived/`. `strict_arrow.py` is for `register_arrow` Nautilus `Data` types — not applicable. |

### Fill source — decision
**Neither the latch nor `Position` is the input today; the scorer's boundary is a Breezy-owned frozen record.**
- The trial latch (`current_rung_hold/trial/{station}/{climate_day}`, blueprint §2 + CONVERGED ¶1) is written **before** submit and stores the *quoted ask* — it structurally cannot know `fill_px`. It supplies **trial identity only** (`station`, `climate_day`, `instrument_id`).
- `Position.realized_pnl` is the correct **future** source of the fill price/fee (`avg_px_open`, `commissions()`), but it is fee-INCLUSIVE and unlanded. Depending on it would make 6c unbuildable now.
- Therefore: `FilledTrial` is an explicit input dataclass; the scorer is pure. A one-function adapter (`OrderFilled`→`FilledTrial`: `fill_px=fill.last_px`, `fee=fill.commission`, `filled_at_ns=fill.ts_event`) lands with R-7/R-8, **not here**.

### Fee double-counting rule (vs `settlement/exit_guard.py`)
`exit_guard.TradeReturnInput.realized_pnl` is documented as fee-inclusive and MUST come from `Position.realized_pnl` (`exit_guard.py:83-94`). The scorer's `pnl = 1{held} − fill_px − fee` is built from a fee-EXCLUSIVE price plus an explicit fee term. Binding rules: (1) `FilledTrial` has **no** `realized_pnl` field, so a fee-inclusive number cannot be fed in; (2) `fee` is the **entry-leg commission only** — the settlement leg is asserted zero-commission by R-9, never assumed here; (3) the two numbers are never summed. When R-9 lands, a reconciliation test asserts `pnl * qty ≈ Position.realized_pnl` (1-cent tolerance) and **flags** divergence — it never adds them.

### Files
- create `src/breezy/settlement/trial_scorer.py` — pure, no Nautilus, no I/O: `FilledTrial`, `ScoredTrial`, `ScoreRefusal`, `score_trial`, `score_trials`.
- create `src/breezy/settlement/settlement_truth.py` — `is_settlement_grade(record)` / `final_tmax_f(record) -> int | None` ported from the script predicate (single implementation for `src/`; the script keeps its own, pinned by its existing tests).
- create `src/breezy/settlement/scored_trial_store.py` — parquet writer/reader with an explicit `pa.schema`, one file per score run under `$BREEZY_DERIVED_DIR/scored_trials/scored_trials_<UTC ts>.parquet`; append-only (never rewrites a file; a re-score appends a new row).
- create `scripts/analysis/score_live_trials.py` — thin driver: read trial+fill records → `open_station_catalog`/`read_climate_day_including_corrections` → `score_trials` → write parquet.
- tests: `tests/unit/test_settlement_trial_scorer.py`, `tests/unit/test_scored_trial_store.py`.

### Data contracts
`FilledTrial` (frozen, slots, kw_only): `trial_id: str` · `station: str` · `climate_day: dt.date` · `instrument_id: str` · `bucket: WeatherBucketFacts` (rung bounds; resolved by the caller from `read_weather_bucket_facts`) · `fill_px: Decimal` · `fee: Decimal` (entry leg only) · `qty: Decimal` · `filled_at_ns: int` · `entry_ask: Decimal` (from the latch; carried for 6d's ask-band strata).
`ScoredTrial` (frozen): all `FilledTrial` identity fields + `settlement_tmax_f: int` · `held: bool` · `pnl: Decimal` · `revision_seq: int` · `raw_sha256: str` (the FINAL print's identity — the re-score key) · `scored_at_ns: int` · `score_seq: int` (0 for first score, +1 per re-score).
`ScoreRefusal` (frozen): `trial_id` · `reason: Literal["no_record","preliminary_only","superseded","sentinel_tmax","rung_unresolved","station_day_mismatch"]` · `detail: str`. `score_trials` returns `(scored, refused)` with `len(scored)+len(refused) == len(trials)` — the `TradeReturnSample` invariant (`exit_guard.py:100-108`).
Parquet schema (all non-null): `trial_id string`, `station string`, `climate_day date32`, `instrument_id string`, `lower_f int32` (nullable, open tail), `upper_f int32` (nullable), `fill_px string` (Decimal as text, never float), `fee string`, `entry_ask string`, `qty string`, `filled_at_ns int64`, `settlement_tmax_f int32`, `held bool`, `pnl string`, `revision_seq int32`, `raw_sha256 string`, `scored_at_ns int64`, `score_seq int32`.

### RED tests (by name)
`test_settlement_trial_scorer.py`: `test_a_final_print_inside_the_rung_scores_held_with_pnl_one_minus_price_minus_fee` · `test_a_final_print_outside_the_rung_scores_lost_with_pnl_negative_price_minus_fee` · `test_a_preliminary_only_day_is_refused_not_scored` · `test_a_superseded_final_is_refused_not_scored` · `test_a_sentinel_tmax_on_a_final_record_is_refused` · `test_a_correction_after_scoring_appends_a_re_score_and_keeps_the_prior_row` (CCA/CCB: new `raw_sha256`/`revision_seq` → `score_seq=1`, both rows readable) · `test_a_fill_whose_rung_cannot_be_resolved_is_refused` · `test_a_record_for_a_different_station_day_is_refused` · `test_pnl_is_decimal_and_never_float` · `test_scored_plus_refused_always_equals_the_input_count` · `test_containment_uses_weather_bucket_facts_on_both_closed_boundaries` (`lower_f` and `upper_f` both held) · `test_open_tail_rungs_score_on_one_bound` · `test_the_scorer_rejects_a_fee_inclusive_realized_pnl_input` (no such field / TypeError) · `test_zero_trials_returns_empty_scored_and_empty_refused`.
`test_scored_trial_store.py`: `test_a_written_run_round_trips_every_decimal_exactly` · `test_a_second_run_appends_a_file_and_never_rewrites_the_first` · `test_reading_an_empty_directory_returns_no_rows_not_an_error` · `test_the_schema_is_pinned_column_for_column`.

### Exit criterion
All the above green under `scripts/ci/run_tests_no_egress.sh`; `mypy`/`ruff` clean under the strict `scripts/analysis` + `src` paths (`pyproject.toml:155-164`); a fixture station-day scores end-to-end through `score_live_trials.py` into a parquet file readable by 6d; **no** existing settlement test weakened; `src/` carries exactly one containment predicate and one settlement-grade predicate.

### Depends on
Nothing unlanded. Consumes only `WeatherBucketFacts`, `persistence/catalog`, `NwsClimateDay` — all present. The `OrderFilled`→`FilledTrial` adapter and the latch join are explicitly OUT of scope (blocked on 6/R-7/R-8).

---

## 6d — nightly live-family tally

### L-1 verdicts
| Need | Verdict | Evidence |
|---|---|---|
| Wilson interval | BREEZY-OWNED, EXISTS — `archive_correction_probe.wilson_interval` (`scripts/analysis/archive_correction_probe.py:352`, `Z_95=1.959963984540054` at `:66`), which is exactly what the M_B study imports (`mb_current_rung_edge_study.py:74`). **Reuse the same import** — a second Wilson is a defect. |
| Stratum/verdict machinery | BREEZY-OWNED, EXISTS — `RealizedStratum` (`:700-724`), `build_realized_stratum` (`:726`), `break_even` (`:179`), `ASK_BANDS`/`classify_ask_band` (`:210,424-437`), `POOLED_KILL_N_MIN=60`/`STRATUM_KILL_N_MIN=60`/`SURVIVE_N_MIN=150` (`:204-206`). **Import them**; do not restate the thresholds. |
| BCa bootstrap ROI bound | **GENUINE GAP — verified absent.** Only `exit_guard.py` mentions BCa, and its own docstring says "R-9 proper (the future BCa bootstrap consumer) is not built here" (`:28-29`). Grep for `bca` across `src/` + `scripts/` returns only those comments. → print `BCa: NOT BUILT`; **never** a Wald interval (EXEC_SPINE R-9: "Not Wald… anticonservative exactly where the decision is made"; RED test 10 pairs `test_wald_interval_is_refused`). |
| Scheduling | NATIVE (systemd) — copy `breezy-mb-daily.{service,timer}` + `mb-daily-run.sh` shape verbatim: `Type=oneshot`, `UMask=0077`, no `[Install]` on the service, `Persistent=true`, staggered `OnCalendar`. |

### Files
- create `scripts/analysis/live_family_tally.py` — reads scored parquet, builds strata, renders Markdown, `--output`, `--as-of`.
- create `deploy/systemd/breezy-live-tally.service` / `.timer` / `live-tally-run.sh` (mirrors `mb-daily-run.sh`: log to `$OUT/live_tally.log`, `STAMP=$(date -u +%Y-%m-%d)`, exit status = OR of steps). Timer: a distinct **hour** from 13:30 (M_B), 22:30 (K1), 22:45 (offer-gate) — propose `*-*-* 14:30:00 UTC`, after M_B, no `[Install]` on the service.
- create `tests/unit/test_live_family_tally.py`.
- modify: `deploy/systemd/README.md` (unit inventory).

### Data contracts
Input: the 6c parquet dataset (highest `score_seq` per `trial_id` wins — a re-scored trial is counted **once**, at its latest score). Output `~/.local/share/breezy/derived/live_family_tally_<YYYY-MM-DD>.md`, section order and table columns **byte-comparable to the M_B live section** (`mb_current_rung_edge_study.py:1035-1048`): `| stratum | n | k | realized rate | mean ask | break-even | Wilson-lower | Wilson-upper | |`, rows = `pooled`, then per-station, then per ask band, then `**<OUTCOME>** -- <detail>`. Verdict: `KILL` if pooled `cell_dead` **or** any n≥60 stratum `cell_dead`; `SURVIVE` if pooled `n≥150` and `wilson_lower > break_even` and no dead stratum and `ΣPnL > 0`; else `UNDERPOWERED`. Additional line: `realized ROI = ΣPnL / Σcost` point estimate + `BCa 95% lower: NOT BUILT (EXEC_SPINE R-9; Wald refused)`. Header carries: source parquet paths, row count, `as_of`, git sha, and an explicit **"live trials only — archive trials are never pooled here (L-13)"** provenance line.

### RED tests (by name)
`test_live_family_tally.py`: `test_a_cheap_ask_band_stratum_with_sixty_trials_and_upper_below_break_even_kills` · `test_a_pooled_result_below_sixty_trials_is_underpowered_not_dead` · `test_survive_requires_n150_lower_above_break_even_no_dead_stratum_and_positive_total_pnl` · `test_a_positive_wilson_lower_with_negative_total_pnl_is_not_a_survive` · `test_zero_scored_trials_renders_underpowered_with_n_zero_and_no_crash` · `test_a_re_scored_trial_is_counted_once_at_its_latest_score_seq` · `test_the_report_never_prints_a_wald_interval_and_says_bca_not_built` · `test_archive_trials_are_never_pooled_into_the_live_tally` (a row tagged archive-provenance must be refused, not merged — L-13) · `test_the_stratum_table_columns_match_the_mb_report_header_exactly` · `test_wilson_z_is_the_shared_constant_not_a_local_literal` · `test_ask_bands_partition_the_taken_screen_with_no_gap_or_overlap` (delegates to `classify_ask_band`) · `test_break_even_uses_the_shared_helper_at_the_published_mean_ask`.
Deploy tests (mirror any existing unit-file test; if none, a shell lint): `test_the_tally_timer_does_not_share_an_hour_with_any_other_breezy_timer`.

### Exit criterion
Green under `run_tests_no_egress.sh`; `mypy --strict` clean (`scripts/analysis` is in the strict path); a fixture parquet renders all three verdicts deterministically; `systemd-analyze verify` passes on the two units; a dry run writes the dated file and the log line; the M_B live-section header string and the tally header string are asserted identical by test, not by eye.

### Depends on
6c only (its parquet schema). Independent of the strategy, R-7, R-8, R-9. `ΣPnL` comes from 6c's `pnl` column — never from `Position.realized_pnl`, which would double-count the fee.

---

## Least confident

1. **Store choice.** Parquet-under-`derived/` is my call because `SqliteStateStore` has no iteration API (`sqlite_store.py:155-178`) and 6d must aggregate. If the repo wants a real table, a purpose-built SQLite module is the alternative — but that is *new* durable-store code, and the L-11 honest form is "native exists (key-value), declined because it cannot be queried", not "no store exists".
2. **Porting the settlement-grade predicate into `src/`.** `is_settlement_grade`/`settlement_outcome` live in an unimportable script. I chose a port (single `src/` implementation, script copy left intact and still pinned). The competing choice — make the scorer a script too — keeps one implementation but puts settlement truth outside the typed package. Verify the script's tests still cover its copy before landing.
3. **Whether re-score-on-correction should also re-open the trade economically.** I specified re-score + history (`score_seq`), matching R-9's disagreement rule (flag, never delete). But R-9 additionally says a venue/NWS divergence beyond one cent **excludes** the trade from the edge sample; 6d currently has no exclusion column. If the operator wants that exclusion live from day one, `ScoredTrial` needs an `excluded_reason: str | None` and 6d an exclusion-fraction ceiling (`exit_guard.py:30-34` demands exactly that of the future BCa consumer).
4. **`entry_ask` provenance.** 6d's ask-band strata need the *decision-time* ask (latch), not `fill_px`, to stay comparable with the archive study's `entry_ask`. I carry both. If the two systematically differ (IOC filling inside the displayed level), the bands drift from the M_B definition — worth a diagnostic column in the tally before n reaches 60.
5. **Trial identity.** I assumed one trial per `(station, climate_day)` (kill amendment, "one trial per station-day") and made `trial_id` free-form. If the latch key is the canonical id, `trial_id` should be exactly `current_rung_hold/trial/{station}/{climate_day}` — cheap to pin, and I would pin it, but the latch module is unlanded so I did not hard-code its key format.
6. **BCa.** Printing `NOT BUILT` means the stop-gate quantity is unavailable at SURVIVE time. That is faithful to the plan's refusal of Wald, but it means a SURVIVE verdict cannot close the stop gate on its own — someone must schedule BCa before n≈150 (~2026-10-21 on the amendment's clock) or the survive lands with no ROI bound.

## Converged peer review (2026-09-04) — BINDING over the draft above

Reviewers: prediction-market-reviewer (BLOCK, 6 amendments + BCa spec), python-reviewer (ACCEPT-WITH-AMENDMENTS, 6). Symbol table verified line-accurate by both (off-by-≤4-line cites immaterial). Coordinator decisions below resolve every amendment; none is an operator question (no budget ceiling is touched).

1. **Venue fallback settlement (BLOCKER).** `VENUE_FACTS_2026-08-25.md:721`: if no NWS data is published within one week of scheduled release the contract settles at last fair market price. `ScoredTrial` gains `settlement_basis: Literal["nws_final","venue_last_fair_price_fallback"]`; a trial whose FINAL is absent 7 days after the scheduled release is scored ONLY when the venue's own settlement is recorded, stamped `venue_last_fair_price_fallback`, and is EXCLUDED from 6d strata and 6e by default (`excluded_reason="venue_settled_without_nws"`), never pooled with NWS-keyed rows. Until the venue settlement is recorded the trial stays `PENDING`. A FINAL that lands after the venue booked fallback cash does NOT re-score against NWS.
2. **`excluded_reason: str | None` lands in 6c** (not R-9). Values: `venue_settled_without_nws`, `divergence` (R-9 disagreement rule, stamped later), else `None`. 6d/6e compute the exclusion fraction from this column from day one.
3. **Provenance citation fixed.** The never-pool rule is NOT stated by L-13. Cite it as: "analogous to L-13 (cadence mismatch) and L-21 (archive vs realized); no lesson states this rule verbatim — it is a plan decision of this brief." Test name becomes `test_archive_trials_are_never_pooled_into_the_live_tally` with that docstring.
4. **Fee is per-contract.** `FilledTrial.fee` docstring: "per contract, entry leg only (venue charges at fill; settlement carries no fee — OQ8)". RED test: the adapter-side builder divides a total commission by `qty` before populating `fee`; a 1-cent reconciliation against `Position.realized_pnl` (fee-inclusive, `position.pyx:902`) is a second, separate test.
5. **SURVIVE is wider than the amendment's predicate.** State verbatim: "6d SURVIVE = `RealizedStratum.survives` (n≥150 AND Wilson lower > BE) **plus** a new ΣPnL > 0 guard; KILL is unchanged." The extra clause is RED-tested on a rate-survive/dollar-negative fixture.
6. **Basis split.** Ask-band classification, `break_even`, and `mean_ask` use `entry_ask` (decision-time, latch value — same basis as the archive). `pnl` uses `fill_px`. `slippage = fill_px − entry_ask` is a REQUIRED column in 6c, not optional.
7. **Instrument lookup source.** `bucket` is resolved from the persisted venue instrument definitions in the station catalog (row-wise ingest, commit `252918a`) by `instrument_id`; absence → `ScoreRefusal("instrument_unavailable")`. Name the reader function in the build return.
8. **Store.** Decimal-as-string parquet (repo idiom `Decimal(str(v))`, `parsing.py:382`; `pa.decimal128` rejected: fixed scale at schema time risks silent truncation). pyarrow is a transitive dependency of `nautilus-trader` — import directly, do NOT add a pin. Writer uses `tempfile.mkstemp(dir=target)` + `os.replace` (`runtime/health.py:322,330`). Readers dedupe by (`trial_id`, max `score_seq`). `trial_id` = the latch key `current_rung_hold/trial/{station}/{climate_day}`.
9. **systemd.** `systemd-analyze verify` is a documented manual step in `deploy/systemd/README.md`, not a pytest gate (no test shells to systemd today). The hour-clash test parses `OnCalendar=` lines of every `deploy/systemd/*.timer` as text.
10. **6e BCa — specification.** Statistic θ = ΣPnL_i / Σcost_i (ratio-of-sums ROI, `EXEC_SPINE_2026-09-01.md:889`), NOT the mean per-trade return; `compute_trade_returns` stays the diagnostic ledger. Paired bootstrap over trial indices, B = 10,000, seed pinned (`numpy.random.default_rng(20260904)`), z0 = Φ⁻¹(frac θ* < θ̂), acceleration from leave-one-out jackknife. Implementation: **`scipy.stats.bootstrap(method="BCa", paired=True)`** — scipy 1.18.1 is resident but only via the `backfill` extra; **promote `scipy` to a core dependency in `pyproject.toml` with a comment stating why** (L-1: reuse over hand-rolling a stop-gate quantity). A dev-only differential test pins the library's bound against a 20-line reference implementation on a fixture. Exclusion-fraction ceiling = **0.20** (coordinator decision; recorded in `exit_guard.py` as a named constant, overridable only downward). Output lines: `BCa: REFUSED — exclusion fraction {x:.3f} exceeds ceiling 0.20` (no bound computed on the remainder); `BCa: UNDERPOWERED (n<30)` below 30 scored, non-excluded trials; otherwise `BCa 95% lower bound on ROI: {lb}` with n, B, seed. Wald is never printed. Lives in `src/breezy/settlement/roi_bound.py`; 6d prints it once the column exists (until then the tally prints `BCa: NOT BUILT`).

Build order: 6c and 6e in parallel (6e's input is a sequence of (pnl, cost, excluded_reason) — no dependency on the store), then 6d.

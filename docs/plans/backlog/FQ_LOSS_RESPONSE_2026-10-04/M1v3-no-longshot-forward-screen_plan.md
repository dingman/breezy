# M1-v3 plan r1: pre-registered forward NO-side favourite-longshot test (draft, coordinator, 2026-10-06)

Source: the trading-bot-architect design for the coordinator, 2026-10-06. Context: under the operator directive "optimize for winners", M1 showed the NO ask 0.9–1.0 cells straddling zero:
- D-1 18Z: n=330, +0.4¢
- D_12Z: n=292, −1.4¢
- D_17Z: n=204, −0.1¢
- MDE 3.2–4.7¢

## Hypothesis
- **H1.** Buying NO at the Depth10 ask, where the NO ask is ≥ 0.90 (YES bid ≤ 0.10), has positive mean net EV per take.
- **Net EV formula.** Net EV = `hit − (ask + θ·ask·(1−ask) + s)`.
  - θ is `EVIDENCED_FEE_THETA` (0.0695), applied via `venue_fee` on the NO ask.
  - s = 1¢ is pre-registered. 0¢ and 2¢ are sensitivity runs only.

## Design
- **Windows.** One reference window per rung-day: D_12Z, pre-registered. Never sum windows on the same rung.
- **Pooling.** Pool across stations and rungs. Cluster by calendar day with a whole-day resample.
- **Confirmatory sample.** Only days ≥ `first_forward_day` (the day after the prereg freeze commit) are confirmatory. M1's 26 days are exploratory, labelled as such.
- **Holdout.** The 07-01 holdout seal applies to model scoring. M1-v3 is market-only, and the tape starts 08-30. Both facts are stated in the prereg.
- **Decision rule.**
  - K=1, α=0.05 one-sided.
  - **WINNER:** the one-sided 95% lower bound of mean net EV per take is > 0 under both the studentized and the BCa day-cluster bootstrap, AND n_days ≥ 40, AND loss count ≥ 30.
  - **UNDERPOWERED:** the floors are unmet at the pre-registered read date. That is a verdict, not a failure.
  - **NO-EDGE:** otherwise.
- **Power.** The architect's estimate is unverified: about 750 takes for an MDE of 2¢, roughly 55–70 days. The plan must compute the read date from a stated per-take SD with the arithmetic shown, or mark it as an estimate. The payoff ceiling is 1−ask (≤10¢ minus fee and slippage), so UNDERPOWERED is a likely outcome.

## Reporting rules
- Skipped observations (no NO ask because the YES bid side is empty) are counted as a denominator. An ask is never synthesised.
- Depth10 only, never QuoteTick.
- Depth available at size ≥ N is recorded as a descriptive field.

## Caveats
- **Netting.** The venue represents a NO buy as SELL/BUY_SHORT of YES, netted against YES holdings. The scan is execution-blind.
- **Correlation.** Rungs of one station-day are mutually exclusive. Weather regimes correlate across stations, which is handled by day clustering. A per-ladder aggregation runs as a sensitivity.

## Files
- **New:** `scripts/analysis/no_longshot_pooled_test.py`. It reuses `market_calibration_scan.py`, which is already 886 lines and must not be extended: `collect`, `no_ask`, `venue_fee`, `rung_outcome`, `assert_no_lookahead`, `load_truth_checked`, and the validity checks.
- **New:** `docs/evidence/m1v3/PREREG.json`, carrying:
  - freeze sha, first_forward_day, window, ask threshold, θ source, s, hit definition, cluster unit
  - bootstrap type/B/seed, K, α, winner rule, floors, read date, UNDERPOWERED rule
  - skipped-obs reporting, exploratory-days label
- **New:** `tests/unit/test_no_longshot_pooled_test.py`.

## Tests (RED first)
- `test_pooled_uses_single_window_per_rung_day`
- `test_forward_filter_excludes_pre_freeze_days`
- `test_net_ev_includes_fee_and_slippage`
- `test_no_ask_none_when_bid_side_empty_counted_not_synthesised`
- `test_day_cluster_bootstrap_resamples_whole_days`
- `test_verdict_underpowered_below_day_and_loss_floors`
- `test_winner_requires_lb_above_zero_both_bootstraps`
- `test_fee_theta_equals_evidenced_theta`
- `test_refuses_live_data_root`

## Out of scope
- Any live order, strategy, or arming change. A WINNER verdict only nominates a NO-longshot family for the existing peer-reviewed arming path.
- Operator caps are untouched.
# M1-v3 plan r2: pre-registered forward NO-longshot execution-structure screen (coordinator, 2026-10-06)

r2 applies round-1 reviews: prediction-market-reviewer REQUEST_CHANGES, architect REQUEST_CHANGES. Rulings M1V3-R1..R10 are BINDING over r1 (`plan_r1.md`, which is otherwise retained).

## Rulings

**M1V3-R1. Framing (operator 09-29 ruling: venues are execution cost only).**
- This is a model-free **Lane E** execution-structure screen under AUT-S r2 (`docs/plans/backlog/AUTONOMY_2026-10-03/AUT-S-winner-search_plan_r2.md:241-254`).
- It is adopted with **AS-R6**: its output never enters model-variant evidence and is never read by `screen.py`.
- It asks whether the venue's fee and tick structure plus favourite-longshot pricing leave NO at ≥ 0.90 positive after cost.
- A WINNER verdict nominates only an execution-side admissibility filter, applied on top of a weather-sourced NO decision. It is never a standalone signal.
- The arming path, live enablement and operator caps are untouched. The netting caveat (the venue nets a NO holding as short YES) travels with any nomination.

**M1V3-R2. Why L-9 does not apply.**
- L-9 refutes lock strategies triggered after information makes a rung near-certain (for example a FINAL CLI print), because those asks are never offered.
- This screen has no conditional-certainty trigger. It samples one fixed pre-resolution window (D0 12Z) unconditionally on weather state, and the M1 tape shows those asks exist (n=292 over 25 days).
- It tests the pricing of residual tail probability, not harvesting of resolved outcomes. The L-9 amendment (the cheap side is a lottery already lost) is the mirror image of this hypothesis. This screen tests whether that mirror is priced too cheaply after cost.

**M1V3-R3. Window, stated as a prior.**
- The primary window is D_12Z: the first D0 window after the overnight model-cycle repricing (memory "hunt window opens after repricing").
- M1 found D_12Z the worst of the three cells (−1.4¢). Choosing it after seeing that result is adverse, not favourable, selection, and it biases toward NO-EDGE. That is disclosed.
- D-1 18Z and D_17Z are reported as labelled sensitivities. Windows are never summed.
- **Expected outcome (stated):** NO-EDGE or UNDERPOWERED. The M1 three-window mean is about −0.3¢.

**M1V3-R4. Fee basis is conservative.**
- `venue_fee` rounds per contract, half-even, to the cent. That puts the fee at 0 for asks ≥ about 0.93, which could decide the verdict.
- **Primary cost:** `max(venue_fee(ask), θ·ask·(1−ask))` with θ = `EVIDENCED_FEE_THETA` imported, plus s = 1¢.
- **Sensitivities:** the rounded-only fee, the unrounded-only fee, s ∈ {0, 2}¢, and the ask band [0.90, 0.97].
- The report carries an ask-bin composition table (0.90–0.92, 0.93–0.95, 0.96–0.99).

**M1V3-R5. Population is pinned (L-28, L-34).**
- `collect(...)` is called with `windows=(D_12Z,)` explicitly.
- The forward-day filter is applied in `_index_directories` before any tape read. All denominators (takes, `no_bid_side`, `windows_without_depth`) come from that filtered population.
- **Selector, pinned verbatim:** the first Depth10 row in [12:00, 13:00) UTC, as `_first_row` does. NO ask = 1 − best YES bid. Ask ≥ 0.90 is **inclusive**.
- Incomplete days (no FINAL truth, or no Depth10 for any listed rung) are excluded whole-day and counted.

**M1V3-R6. Statistics, reusing existing code.**
- **Statistic:** ratio-of-sums mean net EV per take.
- **Primary lower bound:** the one-sided 95% percentile bound from M1's multinomial day-block `_bootstrap_stats`, imported, not rewritten.
- **Second lower bound:** `scipy.stats.bootstrap(method="BCa", paired=True)` on per-day (sum, n) pairs with the ratio statistic.
- `B_RESAMPLES` and `SEED` are imported from `breezy.settlement.roi_bound`.
- **WINNER requires both lower bounds > 0.** This lowers effective α and power, as the prereg states.
- **"Studentized" is dropped.** It is undefined at about 40 clusters.
- **FQ-R27 reconciliation:** with K=1 the Bonferroni bound equals the single bound, and the single-spec SPA one-sided p < 0.05 is equivalent to the primary lower bound being > 0. The dual rule is therefore met by construction, as the prereg states.
- A degenerate all-win sample, where BCa is undefined, is never WINNER.

**M1V3-R7. Power, floors and the single look (arithmetic stated).**
- **Inputs:**
  - Per-take SD = 0.20, from the M1 D_12Z cell: CI half-width 0.0226 gives a day-cluster SE of 0.0115, and 0.0115·√292 = 0.197. The Bernoulli cross-check at a 5.5% loss rate is about 0.22.
  - Rate = 11.7 takes/day (292/25).
- **Required takes:** n for a 2¢ MDE at α=0.05 one-sided and 80% power is ((1.645+0.842)·0.20/0.02)² = 619, so **min_takes = 620**.
- **Floors:** n_days ≥ 40, and **loss_days ≥ 15** (distinct days with at least one losing take). This replaces the raw loss count of 30.
  - At a 3.5% true loss rate, P(a day has a loss) = 1 − 0.965^11.7 ≈ 0.34, giving about 18 loss-days over 53 days, so the floor is reachable when an edge exists.
- **Read date:** first_forward_day + ceil(620/11.7) = 53 days, plus an 8-day truth lag, so **first_forward_day + 61 days**.
- **One look only, with no interim verdict.** If any floor is unmet at the read date, the verdict is UNDERPOWERED.

**M1V3-R8. Freeze is tamper-evident.**
- Import `check_frozen_blob` and `_canonical` from `scripts/analysis/prereg_precommit_check.py`. That file is not extended.
- **The tool refuses to run** unless:
  - the frozen blob matches; and
  - `frozen_sha` is an ancestor of HEAD.
- `first_forward_day` = (UTC commit date of `frozen_sha`) + 1, derived from git. The JSON value is checked against it and never trusted.
- Every row must satisfy `climate_day ≥ first_forward_day` and `ref_ts > freeze commit time`.
- **Pins are checked against imported constants:** θ against `EVIDENCED_FEE_THETA`, the window against `WINDOWS`, and B and SEED against `roi_bound`.
- **Before the read date** the tool emits a progress report only, with no verdict field.
- **The report embeds:**
  - `frozen_sha`
  - the HEAD sha
  - the truth CSV sha256
  - the sha256 of the catalog day list

**M1V3-R9. Reporting.**
- Per-day `no_bid_side` and `windows_without_depth`; these may be missing-not-at-random.
- A per-ladder aggregation is a **reported secondary**: within a ladder, at most one rung loses.
- Depth at the first-row bid is descriptive. The share of takes with depth ≥ 10 contracts is a descriptive screen; it is a fixed constant, unrelated to any operator cap.
- Look-ahead failure → verdict `INVALID` and a non-zero exit.

**M1V3-R10. Output paths.**
- The tool reads the live catalog read-only.
- It **refuses to write under `LIVE_DATA_ROOT`**. Output goes to `docs/evidence/m1v3/` or a `--out` path outside it.

## Files

| File | Status | Notes |
|---|---|---|
| `scripts/analysis/no_longshot_pooled_test.py` | new | Imports `scripts.analysis.market_calibration_scan` (`collect`, `_index_directories` filter hook or an argument, `no_ask`, `venue_fee`, `rung_outcome`, `assert_no_lookahead`, `load_truth_checked`, `_bootstrap_stats`, `_first_row`/`WINDOWS`) and `scripts.analysis.prereg_precommit_check` (`check_frozen_blob`, `_canonical`). If `collect` cannot take a day filter, the **smallest** change is a keyword-only `day_filter=None` parameter whose default leaves M1 output byte-identical; a test pins that. |
| `docs/evidence/m1v3/PREREG.json` | new | Fields per r1 §Files plus R3–R9 values. Frozen by a dedicated commit after review; that commit's sha is `frozen_sha`. |
| `tests/unit/test_no_longshot_pooled_test.py` | new | See the tests below. |
| Characterization tests for `venue_fee`, `no_ask`, `rung_outcome` | new, only if absent | Codegraph showed no tests near them. Verify first. |

## Tests (RED first)

**From r1:**
- `test_pooled_uses_single_window_per_rung_day`, which asserts `collect` is called with exactly one window and that the denominators share it
- `test_forward_filter_excludes_pre_freeze_days`
- `test_net_ev_includes_fee_and_slippage`
- `test_no_ask_none_when_bid_side_empty_counted_not_synthesised`
- `test_day_cluster_bootstrap_resamples_whole_days`
- `test_fee_theta_equals_evidenced_theta`

**Added in r2:**
- `test_fee_primary_is_max_of_rounded_and_unrounded`
- `test_fee_rounding_in_090_100_band`
- `test_ask_bin_composition_reported`
- `test_ask_090_boundary_inclusive`
- `test_verdict_underpowered_below_takes_days_or_loss_days_floor`
- `test_winner_requires_both_lbs_above_zero`
- `test_all_win_sample_never_winner`
- `test_refuses_when_frozen_blob_differs`
- `test_refuses_when_frozen_sha_not_ancestor`
- `test_first_forward_day_derived_from_git_not_json`
- `test_no_verdict_before_read_date`
- `test_lookahead_failure_is_invalid_nonzero_exit`
- `test_incomplete_day_excluded_whole_day`
- `test_per_ladder_secondary_computed`
- `test_refuses_to_write_under_live_data_root`
- `test_collect_default_output_unchanged` (only if `collect` gains `day_filter`)

## Gates

- **Focused gate:**
  - the new test file
  - all `tests/unit/test_market_calibration_scan*.py` (if present)
  - `test_mypy_ratchet`
  - the firewall/readonly guards
- **Tools:** run `cd <wt> && PYTHONPATH=$PWD/src lint-imports` and require "0 broken". mypy strict covers `scripts/analysis` and `tests`.
- **Then the full gate.**

## Out of scope

- Any live, strategy, arming or unit change.
- The operator caps.
- Any interim look.

## r3 amendments (round-2: prediction-market-reviewer APPROVE with three fixes). BINDING over R6 and R7.
- **M1V3-R6a.** The primary lower bound is the **5th percentile** of the `_bootstrap_stats` day-block draws of the ratio-of-sums mean. It is not the 2.5th percentile and not the p-value. Days with zero takes stay in the day vector for both bootstraps; ratio-of-sums makes them weight-zero in the numerator and the denominator. FQ-R27 is applied **by analogy at K=1**: M1's SPA uses studentized, recentered `_max_tests`, and no exact equivalence is claimed. This Lane E test is **not** counted in the AUT-S K=48 ledger (AS-R6).
- **M1V3-R7a.** `loss_days ≥ 10`, lowered from 15. The floor is a bootstrap-stability requirement (enough distinct loss days for the day-block draws to see the tail), not a power device. The report states loss_days and the loss rate either way. At a 2% loss rate the expected count is about 11 loss-days, so a strong edge is not mislabelled UNDERPOWERED.
- **M1V3-R11. Prior disclosed in PREREG.** The M1 D_12Z cell's CI upper bound is +0.79¢ before slippage. Under the stacked costs (D_12Z, 1¢ slippage, conservative fee), a true +2¢ net edge is already essentially excluded, and P(WINNER) is close to zero. This run is a **forward confirmation of NO-EDGE on the NO-longshot hypothesis**, which closes the 09-14 NO-side-hunting question for this cell. It is not discovery. Builder priority is LOW: it runs behind F6, F13-B0 and F7b.

## r3.1 amendments (round-2 architect REQUEST_CHANGES; each fix adopted as the reviewer stated it). BINDING over R4–R8, R6a, R7a.
- **M1V3-R12 (bound and α).** `_Boot.lo` is the 2.5th percentile, so it is **not** used.
  - The primary lower bound is `observed + percentile(centred_draws, 5)`, computed by the tool from the `_bootstrap_stats` draws at α=0.05 one-sided. That keeps min_takes=620 valid.
  - The BCa bound is `scipy.stats.bootstrap(..., method="BCa", paired=True, alternative="greater", confidence_level=0.95)`.
  - FQ-R27 is applied by analogy only. The rule is LB>0 on both bounds. `p_cell` is reported. It is not Hansen SPA.
- **M1V3-R13 (cost path).** The M1 cost path (`_day_matrices`/`excess()`: rounded fee, no slippage, decile ask bins) is **not** reused. The tool builds its own day×1 `s_mat`/`n_mat` from the R4 primary cost, then calls `_bootstrap_stats`. Test: `test_tool_builds_own_cost_matrix_not_m1_excess`.
- **M1V3-R14 (population; supersedes the R5 filter mechanism).**
  - M1 code is unchanged. `collect` is called **once per forward climate day**, with `truth` restricted to that day and `windows=(D_12Z,)`. It already scans only the (station, day) keys in `truth`. That yields per-day `skipped_no_bid_side` and `windows_without_depth` for R9.
  - The `day_filter` / `_index_directories` hook and `test_collect_default_output_unchanged` are dropped.
  - **Incomplete-day rule:** a station-day is excluded whole if **any** listed rung lacks Depth10 in the window. A climate day is excluded if no station-day survives.
- **M1V3-R15 (θ type).** Use the scan's Decimal `THETA`, with `test_fee_theta_equals_evidenced_theta` asserting `THETA == Decimal(str(EVIDENCED_FEE_THETA))`. No float/Decimal mixing.
- **M1V3-R16 (lookahead).**
  - A `LookAheadError` raised by `_scan_day`, or any failed lookahead observation recorded by `_observe_row`, maps to verdict INVALID with a non-zero exit.
  - Tests: `test_lookahead_raise_path_is_invalid` and `test_lookahead_failed_observation_is_invalid`.
- **M1V3-R17 (loss floor; supersedes R7 and R7a).**
  - At the 2¢ MDE the loss rate is about 1.7%, which gives about 9.6 loss-days in 53. Any floor near that number penalises a real edge.
  - So `loss_days ≥ 5` is a **degeneracy guard only**: below it the bootstrap tail is unsupported, and the verdict is UNDERPOWERED. The floor has no power role.
  - The floors are therefore min_takes ≥ 620, n_days ≥ 40 and loss_days ≥ 5. The report states loss_days and the loss rate.
- **M1V3-R18 (freeze date).** `first_forward_day` = UTC **committer** date (`git show -s --format=%cI <frozen_sha>`, converted to UTC) + 1 day. `check_frozen_blob` already enforces ancestry.

**STATUS: READY (2026-10-06).**
- Round 2: prediction-market-reviewer APPROVE; architect REQUEST_CHANGES, with every item resolved verbatim by R12–R18.
- Build priority is LOW (R11): it follows F6, F13-B0 and F7b.
- PREREG freeze is a dedicated commit after the build is gate-green. The forward clock starts at that commit.

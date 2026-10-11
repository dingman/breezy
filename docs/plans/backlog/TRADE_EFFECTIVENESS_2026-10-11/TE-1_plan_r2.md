# TE-1 plan r2: the bot reports its own live P&L for every family, including FQ

Status: r2 (revises r1 per `reviews/TE-1-r1-merge.md`, which is binding). Read-only author pass. New premises P17–P22 were checked by codegraph and by text search of code and artefacts. No Python was executed in this pass, so Stage 0 re-runs every data fact by execution.

## Changes from r1
| Finding | Where r2 addresses it |
|---|---|
| merge C-1 / codex F2 (P12 overclaim) | P12 reworded: the F2 AFOS check compares NWS CLI with NWS CLI and is not a venue check. Venue check UNAVAILABLE; status `SETTLED_NWS_IMPLIED` (R6, WP-B) |
| merge C-2 / arch A6 (score-live-trials change) | Dropped. Only `portfolio-roi-run.sh` changes (WP-C). Residual risk from P19 is recorded under Risks |
| arch A7 (ordering) | Accepted as stale-safe (R7). `fill_pnl` takes the legacy scored store first, and the marker gate expires at 26 h |
| merge C-3 / codex F1 / py F8 / arch P14 (label lag) | Ruled option (a), implemented in the wiring (R4). P14 restated. Option (b) rejected |
| py F1, dom F4, arch A5, merge 1–2 (accounting set) | R1 `accounting_rows` plus AST allow-list guard; `fill_pnl` fixed source order; overlap guard widened (WP-B) |
| arch A1 (D3) | R1, plus erratum E-TE1-a narrowing D3 to statistics (WP-B) |
| dom F5 (separate field) | R1 and R6: new `realised_pnl_accounting_total`; `realised_pnl_c2_total` stays admissible-only |
| P11 regression (r1 WP-B) | R6: statistic `roi` is gated by `GATED_ACCOUNTING_ONLY`; `roi_accounting` is published separately |
| dom F1/F2, merge 3 (fee-unreconciled) | R3, decided with evidence (P18); S0-4b added |
| dom F3, merge 4 (residual +0.08) | Explained in P19 (two offsetting MIA disagreements); S0-5 classifies each fill; `cli_final_check` column (WP-B) |
| py F4, merge 4 (no production join) | WP-A moves `dedupe_scored_trials` and helpers into `src/breezy/analysis/`, keeping re-exports |
| py F2, merge 8 (PRODUCER pin) | R2: new `aut2.label` pin, decided with evidence (P17) |
| py F3, merge 9 (schema) | WP-B: known-set at `portfolio_roi_report.py:2208`. Nine `== 4` assertions listed (not four). v5 strict-rejects missing keys |
| py F5, merge 10 (RED modes) | Every RED test states its failure mode; stubs come first; positive controls named |
| py F6, merge 11 (focused gate) | Focused gate names exact files |
| py F7, merge 12 (S0-1) | S0-1 uses `mode=ro`; `BUY` is post-normalisation |
| dom F6 (NO leg) | `test_no_leg_buy_pays_one_when_yes_false` (L-44) |
| dom F7, merge 13 | `n_ambiguous_no_fill` (S0-11, WP-B); `venue_positions_reconciled=false` |
| dom F8, merge 13 | S0-3 uses `read_climate_day_including_corrections` and records `correction_flag` |
| arch A2, codex F3, merge 5 (NO_INPUT) | R5 overdue-only rule; AUT-6 co-signs erratum E-TE1-b; every widened contract test listed, with positive controls |
| arch A3, merge 6 (rollback) | Rollback rewritten: WP-B is never reverted alone; labels root moved aside first |
| arch A4, merge 7 (activation) | WP-E: gate on branch, merge, link, preflight, reload, in one window that avoids all three bands |
| arch A8 | Peak measurement moved from Stage 0 into WP-D, which runs after WP-A (`label_run.py:892-894`) |
| arch A9, merge 14 | R8: POST_EPOCH switch added to AUT-1b acceptance; row 9 WP6-promote marked DONE-by-TE-1; reasons Needs 3 and 8 do not apply |
| arch A10, merge 15 | Selection and accounting logic go in `src/breezy/analysis/labeling/accounting.py`; the script only calls it |
| codex F3 | See arch A2 row |
| r1 S0-8 (venue reader) | Rejected as a build item: the merge rules the venue check UNAVAILABLE. S0-8 only proves that the wiring passes `venue_settlement_tmax_f=None` |

## Overview
TE-1 finishes F4 / AUT-2 r7 WP6-promote for pre-epoch fills. It adds the accounting view the planned path lacks.

**Option 1 re-scoped. Option 2 rejected.** Option 2 would rebuild `ForecastQuantileLadderScorer`, `score_trial`, the C2 store, the marker, the coverage identity and `assert_ledger_partition` as a parallel architecture.

The goal state: every one of the 34 ledger fills appears exactly once in a bot-written per-fill P&L table, totals reconcile to the audit, and a missing or overdue P&L alerts.

## Verified premises
| # | Premise | Evidence |
|---|---|---|
| P1 | When the sender is FQ, score-live-trials returns 2 before the CRH loop runs and writes only a skip marker | `deploy/systemd/score-live-trials-run.sh:185-189,202-217`; loop `:355-369` |
| P2 | portfolio-roi exits 1 when the marker is absent. The closed skip reason prints NO_INPUT and exits 0 | `portfolio-roi-run.sh:102-115` |
| P3 | Default `main` refuses `not_wired`; so does `--measure-peak` | `label_run.py:857-859,892-894` |
| P4 | The pipeline exists; only the deps are missing | `label_core.py:113-131` (`LabelRunDeps`), `:300-424` |
| P5 | No capture epoch exists, so every fill is PRE_EPOCH | Empty `evidence/capture/epoch/*` and `derived/capture_stream/*/*`; `epoch.py:108-110` |
| P6 | Pre-epoch bridge: latch key plus exactly one manifest | `attribution.py:209-258` |
| P7 | Memory gate inactive at `MemoryMax` ≤ 4 GiB | `memory_gate.py:128-129`; `constants.py:106` |
| P8 | `deliver_with_proof` and the outbox are live | `alert_proof.py:216`; `PROGRESS.md:76` |
| P9 | `breezy-autonomy-failed@` does not exist. Three AUT-6 units already reference it | `breezy-autonomy-alert-redeliver.service:10,13` |
| P10 | Pre-epoch FQ rows: UNATTRIBUTED, `admissible=False`, final. `realized_pnl` is None if unsettled or fee unreconciled. UNATTRIBUTED is decided before FEE_UNRECONCILED | `fq_scorer.py:352,421,451-452,457`; `completeness.py:52-61` |
| P11 | `c2_rows` is admissible-only, but capital counts every fill. When `_unlabelled_fq_fills` reaches 0, status becomes OK | `portfolio_roi_report.py:4068-4074,4109-4118,4216-4224,4347` |
| P12 | Settlement source is the NWS CLI final from the catalog. F2's AFOS check (`coverage.json catalog_disagreement:false`, through 10-10) compares two NWS CLI copies. **There is no venue-side cross-check** | `settlement_source.py:41-69`; audit `:7` |
| P13 | The label bwrap row binds no `evidence/alerts` | `autonomy_sandbox/table.py:305-324` |
| P14 | In the daily path the lag start is injected (`LabelRunDeps.lag_start_ns`). The intended rule is `verdicts.lag_start_ns` = min(first settlement record, deadline). Backlog fills labelled more than 24 h after that start FAIL and raise CRITICAL. `label_run.py:790` is the proof-window path only | `label_core.py:124,281-297`; `verdicts.py:179-197` |
| P15 | The AST guard bans `.storage_key` reads outside `attribution.py` only | `test_aut2_attribution.py:305-324` |
| P16 | Staged label units: `OnFailure=breezy-autonomy-failed@`, no `MemoryMax` | `tests/fixtures/aut2_units/breezy-label-outcomes.service:7-12` |
| P17 | `producer_code_sha` is a required `LabelRunDeps` field written into every recon and lag verdict. Its source is designed to be `PRODUCER_SOURCE_SHA256`. Only `aut6.health` is pinned, and its CLI refuses to run unpinned via `closure_sha256(ENTRY_MODULE)` | `label_core.py:125,262,291`; `verdicts.py:6`; `pins.py:19-21`; `closure_manifest.py:9-75`; `autonomy_health_cli.py:54,90-96`; `test_autonomy_pins.py:101,597` |
| P18 | The two fee-unreconciled fills (SFO 09-11 `gte70lt71`, MIA 09-13 `gte91lt92`) are the two RESIDUAL fills. Residual P&L is booked at the recorded fee; the modelled delta is a Markdown-only FU-3d disclosure. In the label run they become legacy rows (`scored=None`, so `realized_pnl=None`, UNATTRIBUTED, `LEGACY_SCORER_ID`) | `PRIVATE_portfolio_roi_2026-09-30.md:11,23`; exec store instrument ids; `portfolio_roi_report.py:656-756,1233`; `legacy_crh_scorer.py:128,135,138` |
| P19 | **The crh total of −0.46 matches the audit only by coincidence.** Scored MIA 09-15 NO `gte92lt93^no` is booked −0.09 (NO lost), but CLI final is 93, which by the recipe means NO won, +0.91. Residual +0.08 = −0.22 + 0.30 requires MIA 09-13 `gte91lt92` to have won, but CLI final is 92, a loss of −0.70. The two disagreements (+1.00 and −1.00) cancel | 09-30 JSON `trial_rows` `:286-293`; `.md:20`; `truth_cli_finals.csv:537,822,824` |
| P20 | Markers are write-once `marker_<now_ns>.json`, with ns in the file name. `--measure-peak` writes only under `output_root` | `label_store.py:523-551`; `label_run.py:639` |
| P21 | The schema known-set is `{1,2,3,4}` at `:2208`; the reader is optional-on-read for post-v1 keys. Nine test lines assert `== 4` | `portfolio_roi_report.py:2198,2208,3044-3082`; `test_portfolio_roi_report.py:283,423,2234,2295,4424,5165,5187,5909,5910` |
| P22 | The settlement deadline is native and reusable | `registry/settlement_clock.py:36`; `registry/sites.py:413` |

## Rulings (decided here; not deferred)
- **R1 Accounting set.** `accounting_rows(rows)` is a new function in `label_store.py`, beside `admissible_rows` (`:408`).
  - It selects rows with role ENTRY, `scorer_id ∉ {LEGACY_SCORER_ID}`, `is_final_row` true, and `excluded_reason ∈ {UNATTRIBUTED, None}`.
  - It excludes CANARY, DRILL, DUPLICATE_FILL, VOIDED_PAIR, SLIPPAGE_DEFECT and QTY_NOT_ONE.
  - `admissible_rows` stays the only selector for statistics.
  - An AST allow-list test permits importing `accounting_rows` only from `breezy.analysis.labeling.accounting`. Any other `src/` or `scripts/` importer fails, which covers every present and future AUT-3/4/5 module.
  - Erratum E-TE1-a (AUTONOMY errata ledger) narrows AUT-2 D3 ("the one selection rule for any P&L or ROI aggregate", `label_store.py:409`) to *statistics*. No verdict is built from accounting sums.
- **R2 PRODUCER pin: a new pin.**
  - Add `aut2.label` to `PRODUCER_SOURCE_SHA256`, with a closure entry for `breezy.analysis.labeling.label_run` regenerated by `scripts/ci/regen_closure_manifest.py`.
  - `unit_wiring.producer_pin_state()` mirrors `autonomy_health_cli.py:90-96`. If unpinned, `main` prints `LABEL_OUTCOMES REFUSED reason=producer_unpinned` and exits 2, which fires OnFailure.
  - Reviewed widening: `test_autonomy_pins.py:101` becomes `{"aut6.health","aut2.label"}`, plus a length-64 assertion. `:597` covers the new closure automatically.
  - "No pin" is rejected. `verdicts.py:6` designs the sha to come from the pin. Any other source, such as git HEAD, would be an unpinned identity in a C4 verdict that the pin mechanism exists to refuse.
  - Cost, accepted: a reviewed re-pin is needed whenever a label-closure module changes. Modules shared with `aut6.health` re-pin both.
- **R3 C2 vs FEE_UNRECONCILED.**
  - The only fee-unreconciled fills are the two residuals (P18). They are booked at the recorded fee by the legacy residual path (`:1233`), carry `fee_unverified=true` in `fill_pnl`, and the modelled delta stays Markdown-only (FU-3d AC4, `:656-661`).
  - Their label rows are legacy rows, which R1 excludes. C2 therefore never touches them.
  - For C2 (FQ) rows, a fee-unreconciled fill keeps `realized_pnl=None` (`fq_scorer.py:421`). Its `fill_pnl` status is UNSETTLED with `fee_unverified=true`. It is excluded from totals, counted in `n_null_pnl_final`, and alerted CRITICAL. It is never booked as zero and never at a modelled fee.
  - Booking it at the recorded fee is rejected: that bypasses the identity check at `fq_scorer.py:425-426` and changes scorer semantics.
  - S0-4 proves zero such FQ fills, so −4.63 reproduces.
- **R4 Label lag (option a).**
  - `unit_wiring.lag_start_ns(f)` = `verdicts.lag_start_ns(first_record_ts, deadline)`, except when `f.ts_event < activation_ns`. In that case it is `max(rule, activation_ns)`, and the run prints `AUT2 LAG_BACKLOG n=<k>`.
  - `activation_ns` = the oldest marker ns under the **live** labels root (new `oldest_marker_ns()` in `label_store.py`, names only), or `deps.now_ns` when none exists.
  - Fills after activation use the plain rule. Option (b) is rejected because it changes family semantics.
- **R5 NO_INPUT.** The report alerts `PORTFOLIO_ROI_NO_INPUT` and exits 1 only if some ledger fill has no booked P&L and `now > settlement_deadline_ns(fill) + LABEL_LAG_MAX_H` (P22, `constants.py:55`).
  - A pending fill inside its deadline never pages.
  - An absent score-live-trials marker still exits 1 in the wrapper.
  - AUT-6 co-signs erratum E-TE1-b against `AUT-6-drift-health_plan_r15.md:1471`.
- **R6 Two ROI fields.**
  - `realised_pnl_c2_total` and `roi`/`roi_minus_b0`/`roi_minus_b1` stay statistic-only.
  - When any capital-bearing fill's P&L reaches only the accounting total, `roi_status` = new `GATED_ACCOUNTING_ONLY`. It is added to `_LABEL_GATED_STATUSES` (`:2217`), so the sanctioned reader raises `UnsettledCapitalRoiError`.
  - New fields: `realised_pnl_accounting_total`, `roi_accounting`, `roi_accounting_status ∈ {OK, GATED_UNSETTLED_CAPITAL, GATED_IDENTITY}`.
- **R7 Stale-safety (A7).**
  - portfolio-roi reads labels only through `labels_consumable`, which goes stale at 26 h (`label_store.py:205`; `constants.py:59`).
  - `fill_pnl` takes the legacy scored store before any label row. A legacy fill labelled before its ScoredTrial lands therefore still books from the store.
  - No scorer-to-label ordering is enforced.
- **R8 Row 9 / Needs.**
  - Need 8 (AUT-1b) feeds only POST_EPOCH C1 rows; every fill is pre-epoch (P5).
  - Need 3 (ING-2-AMEND2, quote-tape ingest) does not apply: the pre-epoch wiring reads no quote-tape input (`venue_settlement_tmax_f=None`). A test pins this.
  - On merge, PROGRESS row 9 records WP6-promote DONE-by-TE-1. AUT-1b acceptance gains: "label unit switches to the POST_EPOCH path on the first epoch file, with test".

## Stage 0 (read-only; any failure STOPs TE-1 back to the coordinator)
Interpreter: `/home/jon/breezy/.venv/bin/python`. Never `uv`.
- **S0-1.** Read `exec/polymarket_us/fill/*` via `sqlite3.connect("file:…?mode=ro", uri=True)` plus `PRAGMA query_only`. Expect 34 rows, all `order_side=BUY` (post-normalisation: the three NO legs are `^no` instruments), qty 1, Σ cost 6.36, Σ fee 0.27. STOP otherwise.
- **S0-2.** All 25 FQ fills bridge to `pm_us_crh_fq_v1` alone (`latch_key_exists`, one manifest window). STOP on `no_backfill_family` or `backfill_disagreement`.
- **S0-3.** For every fill's instrument station-day, `read_climate_day_including_corrections` returns a FINAL tmax. Record `correction_flag` and the record ts. STOP if any is missing.
- **S0-4.** Every FQ fill has `fee_reconciled=True`. **S0-4b:** exactly two non-FQ fills are unreconciled, SFO 09-11 and MIA 09-13. Both are residual trial ids. STOP otherwise.
- **S0-5.** Map the 9 legacy fills to scored or residual. Expected: scored = the 7 `trial_rows`; residual = the two S0-4b fills.
  - Read the frozen ScoredTrial for MIA 09-15 (`settlement_tmax_f`, `revision_seq`, `held`). Run `_resolve_residual_settlements` read-only today for MIA 09-13.
  - Classify each disagreement in P19 as (i) a post-scoring NWS correction, (ii) a mismatch between `bucket_facts_from_instrument_id` band semantics and the recipe, or (iii) a catalog value that differs from `truth_cli_finals.csv`.
  - **(ii) is a STOP**: the bot or the audit has the band wrong, and it goes to the domain reviewer before any code.
  - (i) and (iii) proceed. Record the expected booked crh total and the per-fill deltas for live proof 2.
- **S0-6.** Removed (moved to WP-D, per A8).
- **S0-7.** Positive control for R4: with `lag_start_ns` = plain rule, a fixture-dated first run gives `aut2.label_lag` FAIL for `pm_us_crh_fq_v1`. With R4 it PASSes.
- **S0-8.** Confirm the wiring passes `venue_settlement_tmax_f=None`, i.e. the venue check is UNAVAILABLE for all rows.
- **S0-9.** Confirm the widening list in WP-C is complete. Run `/usr/bin/grep -rn` for `NO_INPUT -- upstream skipped`, `== 4`, `{"aut6.health"}` and `breezy-autonomy-failed@` across `tests/`.
- **S0-10.** Removed (the score-live-trials change is dropped).
- **S0-11.** Find the exec-store source for AMBIGUOUS intents with no fill (09-05 SFO, 09-23 MIA). If none exists, `n_ambiguous_no_fill` is reported as `UNKNOWN`, never 0.

## Work packages
Build route: Grok → Codex → Claude tdd-guide. Each brief restates the invariants:
- Nautilus is immutable; `allow_short=False`.
- No safety, settlement, contract or NO-SEND test is weakened (L-12: widen, never relax).
- No operator cap, enablement, arming or halt is touched.
- Format only your own files. `--basetemp` goes under `~/.cache`.

Order: WP-A ∥ WP-B → WP-D → WP-C → WP-E. Stubs first: every new symbol lands with a typed, neutral body (empty tuple, `None`), so each RED fails on an assertion, never on ImportError.

### WP-A: production label wiring
- **Files:**
  - NEW `src/breezy/analysis/labeling/unit_wiring.py`: the `UnitFactory`, `producer_pin_state`, the R4 `lag_start_ns`, and the deadline from P22. It reuses `attribute_fill`, `C1Epoch`, `latch_key_exists`, `settlement_source_for`, `StudiesFlock`, `deliver_with_proof` and `OFFLINE_PLUGINS`. It adds no attribution rule.
  - NEW `src/breezy/analysis/labeling/legacy_join.py`: fill → latch `trial_id` → frozen ScoredTrial (`read_scored_trials_pooled`), producing `LegacyFillInput`. Residuals get `scored=None`.
  - MOVE `dedupe_scored_trials`, `_scored_trial_economic_fingerprint`, `_SCORED_TRIAL_ECONOMIC_FIELDS`, `DuplicateScoredTrialEconomicsMismatchError` and `_default_scored_trials_dir` from `portfolio_roi_report.py:1264-1356,3606` to NEW `src/breezy/analysis/scored_trial_dedupe.py`. The script re-exports every name, so test aliases `_prr.*` stay valid. `admissible_scored_trials` is already in `src` (`realized_draws.py:187`).
  - `label_store.py`: `oldest_marker_ns`.
  - `label_run.py __main__`: default `unit_factory=unit_wiring.factory`.
  - `pins.py`, `closure_manifest.py` (regenerated), `test_autonomy_pins.py:101` widening, all in the same commit.
- **RED tests** (NEW `tests/unit/test_te1_label_wiring.py`; the failure mode under the stubs follows each name):
  - `test_planner_pre_epoch_fq_fill_bridges_to_v1`: the stub plan is empty, so no FQ input.
  - `test_planner_legacy_crh_fill_joins_frozen_scored_trial`: no legacy input.
  - `test_planner_residual_fill_gets_null_pnl_legacy_row_not_missing`: `missing_label` = 1.
  - `test_planner_unbridgeable_fill_is_unresolved` (positive control): the stub resolves it, so the test fails.
  - `test_wiring_settlements_is_nws_cli_final_for_polymarket_us`
  - `test_wiring_deliver_is_deliver_with_proof`
  - `test_wiring_memory_gate_holds_above_4gib_without_aut6_reading`
  - `test_wiring_proof_window_none_while_wp7_inactive`
  - `test_wiring_producer_sha_is_pinned_closure_sha`
  - `test_unpinned_producer_refuses_with_exit_2` (positive control)
  - `test_lag_backlog_fill_starts_at_first_activation`: FAILs under the plain rule.
  - `test_lag_post_activation_fill_still_lag_checked` (positive control): fails if the anchor is applied to every fill.
  - `test_lag_anchor_ignores_measure_output_root_markers`
  - `test_main_under_unit_runs_production_factory`: fails today on `not_wired` (L-55: the production default runs once).
  - `test_no_leg_buy_pays_one_when_yes_false` (L-44)
  - `test_pre_epoch_wiring_reads_no_quote_tape` (R8)
  - `test_moved_dedupe_reexported_by_script`
- **Acceptance:**
  - A fixture copy of the 34-fill shape gives LABELLED, `missing_label = unresolved = pending = 0`, `durable_fill_count = 34`.
  - Every FQ row is UNATTRIBUTED with `p_source` none and non-null `realized_pnl`.
  - `lint-imports` (cd into the tree) prints "N kept, 0 broken", including the "analysis never imports Nautilus" and autonomy-core contracts (L-46).

### WP-B: accounting P&L, `fill_pnl` and `family_pnl`, alerts (the TE-1 delta)
- **Files:**
  - NEW `src/breezy/analysis/labeling/accounting.py`. It is pure and gets inputs only from the script. It holds `build_fill_pnl(ledger, scored, residual, c2_accounting, cli_check)` with fixed source order legacy → residual → C2, `family_pnl` derived from `fill_pnl`, the overdue rule (R5), and `cli_final_check` (reusing `score_trial` with the corrections-aware read, disclosure only, never booked).
  - `label_store.py`: `accounting_rows`.
  - `portfolio_roi_report.py`:
    - `_LabelView.c2_rows` is unchanged (statistics); add `accounting_rows()`.
    - Widen the overlap guard (`:4206`) to `{accounting ∪ admissible}` trial ids.
    - Add the R6 fields, `GATED_ACCOUNTING_ONLY`, `PORTFOLIO_ROI_SCHEMA_VERSION = 5`, and known-set `{1..5}` (`:2208`).
    - v5 strictly requires the new keys.
    - The two events go through the existing `sink` / `emit_alert`.
- **`fill_pnl` row** (PRIVATE 0600 JSON only):
  - `fill_key`, `family_id`, `source ∈ {LEGACY, RESIDUAL, C2, NONE}`, `status ∈ {SETTLED_NWS_IMPLIED, OPEN, UNSETTLED, RESIDUAL_PENDING, EXIT, UNPRICED}`, `win`, `payout`, `cost`, `fee`, `net`.
  - `fee_unverified`, `cli_final_check ∈ {AGREE, DISAGREE, UNAVAILABLE}`, `venue_check=UNAVAILABLE`.
  - Pre-epoch rows group by `LabelRow.family_id` with `attribution_basis=pre_epoch_bridge` (P15 holds).
- **Disclosures:**
  - `n_fee_unverified`, `n_null_pnl_final`, `n_settlement_disagree`, `cli_final_net_total`, `n_entry_ask_unknown`.
  - `n_ambiguous_no_fill` (S0-11).
  - `venue_positions_reconciled=false`.
- **Exit and alerts:**
  - `len(fill_pnl) != n_ledger_rows` → FILL_COUNT_MISMATCH, exit 1.
  - R5 overdue → NO_INPUT, exit 1.
  - `n_null_pnl_final > 0` → CRITICAL.
  - `n_settlement_disagree > 0` → WARN, exit 0.
  - The journal line stays dimensionless (`portfolio-roi-run.sh:126-135`).
- **RED tests** (`tests/unit/test_te1_accounting.py` is NEW; `test_portfolio_roi_report.py` is extended):
  - `test_accounting_rows_selects_entry_nonlegacy_final_unattributed_or_none`: stub returns `()`.
  - `test_accounting_rows_excludes_each_final_non_accounting_reason`, parametrised over 6 reasons.
  - `test_accounting_rows_excludes_legacy_scorer_rows` (dom F4).
  - `test_accounting_rows_importers_allow_list`: RED by mutation (a planted importer must fail, L-33).
  - `test_fill_pnl_one_row_per_ledger_fill_fixed_source_order`
  - `test_legacy_fill_never_counted_twice_with_its_label_row`
  - `test_overlap_guard_covers_accounting_rows`
  - `test_family_pnl_sums_to_accounting_total`
  - `test_c2_total_stays_admissible_only`
  - `test_roi_gated_accounting_only_when_pnl_outside_admissible`: fails today on `:4216-4224`, status OK.
  - `test_roi_ok_when_all_pnl_admissible` (positive control)
  - `test_null_pnl_final_row_unsettled_alerted_not_zero` (positive control)
  - `test_c2_fee_unreconciled_not_booked_and_alerted` (R3)
  - `test_residual_fee_unverified_booked_at_recorded_fee` (R3)
  - `test_settlement_disagree_flagged_and_warned`
  - `test_overdue_unpriced_fill_alerts_no_input_exit_1`
  - `test_pending_inside_deadline_does_not_alert` (positive control, A2)
  - `test_fill_count_mismatch_alerts_exit_1`
  - `test_recipe_fixture_reproduces`: a synthetic 34-row fixture from the audit recipe, never live amounts.
  - `test_schema_v5_reader_accepts_1_to_5_and_rejects_v5_missing_keys`
  - `test_disclosures_ambiguous_unknown_not_zero_and_venue_positions_false`
  - `test_journal_line_dimensionless`
- **Reviewed widenings** (to 5, and known-set `{1,2,3,4,5}`): `test_portfolio_roi_report.py:283,423,2234,2295,4424,5165,5187,5909,5910`.
- **Errata filed with the merge:** E-TE1-a (D3, R1); E-TE1-b (NO_INPUT, R5, AUT-6 co-sign).

### WP-C: promotion as one change (F4-open-items steps 1, 2, 3, 6)
- **Files:**
  - `git mv tests/fixtures/aut2_units/breezy-label-outcomes.{service,timer}` → `deploy/systemd/`, adding `MemoryHigh`/`MemoryMax` from WP-D and `OnFailure=breezy-autonomy-failed@%n breezy-study-failed@%n`.
  - The slot guard lands with the label timer.
  - `table.py`: the label row binds `evidence/alerts` (P13).
  - `portfolio-roi-run.sh`: the closed reason `composition_kind_has_no_scorer` now says `PORTFOLIO ROI upstream skipped (composition_kind_has_no_scorer); running report` (no SKIPPED, no NO_INPUT token) and falls through to the report. An absent or unknown marker still exits 1.
  - `deploy/systemd/README.md`.
  - The score-live-trials files are **not** touched.
- **RED tests and reviewed widenings** (each test keeps a positive control):
  - `test_portfolio_roi_run_no_input.py:64-72`: replaced by `test_closed_skip_reason_runs_the_report` (stub capture exists). `:74-82`, `:85-92`, `:95-102` and `:105-112` are kept unchanged as positive controls.
  - `tests/contract/test_autonomy_units_programme.py`: remove the `NO_INPUT -- upstream skipped` alternative from `_BENIGN_SKIP` (`:38`). That narrows the allow-list, which is stricter. Replace `:260-268` with `test_portfolio_roi_closed_skip_reason_has_no_exit_before_report`.
  - `test_aut2_units_deploy.py:175-185`: a reviewed row for the `evidence/alerts` bind.
  - `test_label_unit_deployed_with_dual_onfailure`
  - `test_label_unit_memory_max_from_measured_peak` (WP-D artefact)
  - `test_no_deployed_file_references_slot_guard_run_until_promotion`: widened by one reviewed row.
  - `test_portfolio_roi_deploy.py`: the CLI contract is unchanged; the row is confirmed.
  - `test_unit_execstart_imports.py` covers the new ExecStart.
- **Acceptance:** before install, the gate reads EXIT=0 and the `NeedDaemonReload` preflight is clean.

### WP-D: sizing (coordinator; runs after WP-A, gates WP-C)
- Run `label_run --measure-peak --output-root <scratch>` in a transient `aut2-label-peak-<ts>` unit. That leaf is already accepted by `label_run.py:120-122`.
- Conditions: a quiet window, `MemAvailable ≥ 16 GiB`, one heavy job at a time, `-p LimitNOFILE=524288`.
- Settle the F4 item first: the peak is read from `/proc/self/cgroup` (`label_run.py:598-613`), which fails closed under a cgroup namespace. Confirm the measure run is not inside one.
- Commit the `aut2_memory_peak/v1` artefact together with WP-C.
- **Above 4 GiB: STOP** (FQ-R19 hold until AUT-6 publishes `aut6.memory_budget`).

### WP-E: activation (coordinator)
- **Window:** the same day, inside 04:30–13:55Z. That avoids 13:55–14:30Z, [16:30, 17:10)Z and [01:00, 04:30)Z, and finishes before the 14:15Z timer and the 17:40Z report.
- **Steps:**
  1. Run the full gate on the branch and read EXIT before merging.
  2. Fast-forward merge.
  3. `ln -s` the label pair into `~/.config/systemd/user` (README `:6,45`).
  4. `systemd-analyze --user verify` and the `NeedDaemonReload` preflight.
  5. `daemon-reload`.
  6. `enable --now breezy-label-outcomes.timer`.
- Then run the L-1 positive controls from F4-open-items.

## Focused gate (every slice; the full gate after every merge, EXIT read before any push)
- `scripts/ci/run_tests_no_egress.sh` with:
  - the new TE-1 tests;
  - `tests/unit/test_execution_egress_firewall_guard.py` (exec import pin: any new test importing `breezy.adapters.polymarket_us.exec` needs a WIDENED row);
  - every `tests/**/test_autonomy_*`;
  - `tests/contract/test_autonomy_units_programme.py`, `test_aut2_attribution.py`, `test_aut2_label_store.py`, `test_aut2_label_run.py`, `test_aut2_units_deploy.py`;
  - `test_portfolio_roi_report.py`, `test_portfolio_roi_run_no_input.py`, `test_portfolio_roi_deploy.py`;
  - `test_runtime_import_isolation.py`, `test_run_tests_no_egress_phases.py`, `test_unit_execstart_imports.py`.
- Then `cd <tree> && lint-imports`, requiring "N kept, 0 broken". In worktrees set `PYTHONPATH=<tree>/src`.

## Dependencies
- **DONE:** F4 WP0–3, 5, 6-build, 8; F2 truth (LIVE); AUT-6 WP1.
- **Conditional:** `aut6.memory_budget`, only if the peak exceeds 4 GiB.
- **Not required (R8):** AUT-6 notifier (`breezy-study-failed@` covers delivery until then); AUT-1b; AUT-5a; WP7; WP9 legs (INCONCLUSIVE, a known gap).
- **Forward compatibility:** the POST_EPOCH switch is an AUT-1b acceptance item. `entry_ask` is populated from C1 decisions (`fq_scorer.py:299-301`).

## Decision-time ask: a separate row, not TE-1
TE-1 reports only `n_entry_ask_unknown`. Add a cross-link on PROGRESS row 8 (AUT-1b). Open TE-4 only if AUT-1 r12 does not capture `ask_px` for FQ takes.

## Risks and mitigations
- **The legacy store is frozen while the sender is FQ** (P1, P19). If S0-5 finds a post-scoring correction, the legacy row stays stale, because the score-live-trials change is dropped per the binding ruling.
  - Mitigation: `cli_final_check` = DISAGREE plus a WARN alert every run.
  - The coordinator decides whether to open TE-1b (re-score under correction). Booked figures are never edited by hand.
- **Pre-epoch rows are final at first write** (P10). Mitigation: S0-3; null P&L is never zero (R3, `n_null_pnl_final`).
- **Re-pin churn from R2.** Mitigation: a reviewed re-pin commit; `:597` fails loudly.
- **Contract-test widenings.** Mitigation: every row is listed in WP-C and WP-B; each new behaviour is stricter.
- **Symlinked units.** Mitigation: one window, preflight before install; the wrapper goes live on merge, so WP-E runs the same day.
- **Memory and concurrency.** Mitigation: in-process studies flock; measured `MemoryMax`; exec store read only through a snapshot.

## Live proof (LIVE = the first scheduled success has been seen)
1. The first **timer-fired** `breezy-label-outcomes` run (14:15Z):
   - exits 0;
   - LABELLED marker, `durable_fill_count=34 pending=unresolved=missing_label=0`;
   - `aut2.label_lag` PASS for `pm_us_crh_fq_v1`, with an `AUT2 LAG_BACKLOG n=25` line;
   - verdicts carry the `aut2.label` pin sha.
2. The same day's **timer-fired** `breezy-portfolio-roi` run (17:40Z) exits 0. Its artefact shows:
   - `n_ledger_rows=34`, `len(fill_pnl)=34`, fees 0.27;
   - `cli_final_net_total` −4.63 with 2 wins; crh −0.46, `pm_us_crh_fq_v1` −4.17;
   - booked FQ −4.17;
   - booked crh = the S0-5 expected value. The identity `booked_total − cli_final_net_total = Σ listed DISAGREE deltas` must hold exactly;
   - `n_fee_unverified=2` (both RESIDUAL), `n_null_pnl_final=0`;
   - `roi_status=GATED_ACCOUNTING_ONLY`, `roi_accounting_status=OK`.

   Any other mismatch is a STOP and a diagnosis. Numbers are never tuned to match.
3. **Delivery drill:** a `--drill` run of the report against an isolated output root and an empty labels root produces NO_INPUT with a `deliver_with_proof` delivered record and `drill=true`.
4. **Second day:** the second scheduled pair also succeeds. Until then the status is "built, not LIVE".

## Rollback
1. `systemctl --user disable --now breezy-label-outcomes.timer`.
2. `git revert` WP-C, which restores `portfolio-roi-run.sh` and the units. Unlink the label pair from `~/.config/systemd/user`. Run the preflight, then `daemon-reload`.
3. **Never revert WP-B alone.** Pre-WP-B code reading FQ labels publishes the P11 wrong ROI with status OK. If WP-B must go: first `mv` the label store and marker dirs under the labels root (`portfolio_roi_report.py:3613`) to a dated sibling. Never delete them. Then revert WP-B; the reader still accepts v1–v4.
4. WP-A revert also reverts the `aut2.label` pin and closure entry in the same commit.
5. The exec store is never written.

## Explicit non-goals
- TE-2 (FQ 0/25 root cause) and TE-3 (NO-side hypothesis).
- Any re-arm, enablement, halt or cap change.
- Persisting the decision-time ask (AUT-1b).
- WP9 legs and venue-position reads.
- The proof window and the WP7 flip.
- AUT-3/4/5 label consumption and any change to `admissible`.
- Kalshi.
- KILL and tally semantics; reading M1-v3 data.
- Exec client, Nautilus or NO-SEND changes.
- Re-scoring the frozen legacy store (TE-1b, if S0-5 warrants it).

## Success criteria
- [ ] S0-1..S0-11 recorded, with the S0-5 classification and expected values written before WP-A briefs.
- [ ] RED → GREEN kept for WP-A, WP-B and WP-C. Full gate EXIT=0 after each merge. `lint-imports` "N kept, 0 broken".
- [ ] Errata E-TE1-a and E-TE1-b filed, with AUT-6 co-sign. PROGRESS row 9 and AUT-1b acceptance updated.
- [ ] Live proof 1–4 observed and cited (artefact paths, journal lines, SHAs) by a reviewer who did not build it.

Relevant paths:
- /home/jon/breezy/src/breezy/analysis/labeling/{label_run,label_core,fq_scorer,legacy_crh_scorer,attribution,completeness,verdicts,constants}.py
- /home/jon/breezy/src/breezy/persistence/autonomy/{label_store,pins,closure_manifest,closure}.py
- /home/jon/breezy/src/breezy/runtime/autonomy_health_cli.py
- /home/jon/breezy/src/breezy/runtime/autonomy_sandbox/table.py
- /home/jon/breezy/src/breezy/registry/settlement_clock.py
- /home/jon/breezy/scripts/analysis/portfolio_roi_report.py
- /home/jon/breezy/deploy/systemd/portfolio-roi-run.sh
- /home/jon/breezy/tests/fixtures/aut2_units/
- /home/jon/breezy/tests/unit/test_autonomy_pins.py
- /home/jon/breezy/tests/unit/test_portfolio_roi_run_no_input.py
- /home/jon/breezy/tests/contract/test_autonomy_units_programme.py
- /home/jon/.local/share/breezy/derived/PRIVATE_portfolio_roi_2026-09-30.{json,md}
- /home/jon/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv
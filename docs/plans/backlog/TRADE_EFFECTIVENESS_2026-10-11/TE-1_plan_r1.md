# TE-1 plan r1: the bot reports its own live P&L for every family, including FQ

## Overview
TE-1 finishes the path already planned in F4 / AUT-2 r7 WP6-promote, sized down to what live P&L needs. It also adds three deltas that the planned path is missing. Without them, the planned path would never reach the goal state:
- an accounting P&L view of every final label row, admissible or not;
- a P&L table per fill and per family, checked against the fill store by count;
- an alert when the report has no input or the fill count does not match.

The code shows that the "promote waits AUT-6" blocker is now conditional, not absolute (premises P7–P9).

**Decision: Option 1, re-scoped. Option 2 is rejected.**
- Option 2 would duplicate pieces that already exist and are tested: `ForecastQuantileLadderScorer`, `score_trial`, the C2 label store, the run marker, the coverage identity and `assert_ledger_partition`. That is a parallel architecture.
- Option 1 as it stands publishes a wrong ROI with `roi_status=OK` (premise P11). TE-1 is therefore Option 1 plus the deltas in WP-B.

## Verified premises (the coordinator re-verifies these before peer review)
| # | Premise | Evidence |
|---|---|---|
| P1 | score-live-trials skips every family whenever the sending family is FQ. It returns 2 before the CRH scorer loop runs. | `deploy/systemd/score-live-trials-run.sh:185-189`, `:202-217` (exit 0); loop at `:355-369` never reached; `derived/score_live_trials.log` 10-01..10-10 |
| P2 | portfolio-roi exits 1 when there is no success marker (10-01..10-08). The closed skip reason gives NO_INPUT with exit 0, which raises no alert (10-09, 10-10). | `deploy/systemd/portfolio-roi-run.sh:102-115`; `derived/portfolio_roi.log:46-55` |
| P3 | The label run's default mode refuses `not_wired`. No production `UnitFactory` exists. | `src/breezy/analysis/labeling/label_run.py:857-859`, docstring `:5-7` |
| P4 | The full label pipeline exists: read fills, plan, score, write, coverage, marker, alerts. Only the deps are missing. | `src/breezy/analysis/labeling/label_core.py:113-131` (`LabelRunDeps`), `:300-424` (`run_labels`) |
| P5 | There is no capture epoch file and no C1 capture stream on disk. As a result, every durable fill is PRE_EPOCH. | Glob `evidence/capture/epoch/*` and `derived/capture_stream/*/*` both empty; `src/breezy/analysis/labeling/epoch.py:108-110` |
| P6 | A pre-epoch fill gets a storage key from the bridge rule (latch key plus exactly one manifest). `champion_at` is optional. | `src/breezy/analysis/labeling/attribution.py:209-258`, `:251` |
| P7 | The memory gate is inactive when `MemoryMax` ≤ 4 GiB. AUT-6's `aut6.memory_budget` only matters above that. FQ-R19 says the same. | `src/breezy/analysis/labeling/memory_gate.py:128-129`; `constants.py:106`; plan r3 `:173` |
| P8 | `deliver_with_proof` and the outbox exist, and AUT-6 WP1 is merged and live. | `src/breezy/runtime/alert_proof.py:216`; `docs/core/PROGRESS.md:76` |
| P9 | The `breezy-autonomy-failed@` notifier does not exist. Three live AUT-6 units already ship that dangling `OnFailure=` line (X-3 precedent). | `deploy/systemd/breezy-autonomy-alert-redeliver.service:10,13`; no such file in `deploy/systemd/` |
| P10 | A pre-epoch FQ row is `excluded_reason=UNATTRIBUTED` and `admissible=False`. UNATTRIBUTED counts as final even when unsettled. `realized_pnl` = payoff − cost − fee, or `None` if unsettled or the fee is unreconciled. | `src/breezy/analysis/labeling/fq_scorer.py:451-452`, `:352`, `:417-427`; `completeness.py:52-61` |
| P11 | **This is the defect in the planned path.** portfolio_roi sums P&L over admissible rows only, while capital counts every fill. Once FQ v1 is labelled, `_unlabelled_fq_fills` → 0, so the status becomes OK and P&L ≈ −0.46 against cost 6.36, while the truth is −4.63. | `scripts/analysis/portfolio_roi_report.py:4068-4074`, `:4109-4118`, `:4216-4224`, `:4242`, `:4347` |
| P12 | The polymarket_us settlement source is the NWS CLI final from the catalog. F2 cross-checks it against AFOS with no disagreement, through 10-10. | `src/breezy/analysis/labeling/settlement_source.py:41-51,66-69`; `derived/fq-truth/coverage.json` (`catalog_disagreement:false`, `through_d_minus_1 2026-10-10`) |
| P13 | The label-unit bwrap row binds no `evidence/alerts`, so outbox delivery cannot write from inside the sandbox. | `src/breezy/runtime/autonomy_sandbox/table.py:295-324` |
| P14 | The label-lag clock starts at fill time. A backlog fill labelled more than 24 h later fails, and that raises a CRITICAL. | `src/breezy/analysis/labeling/verdicts.py:195-197`; `label_core.py:281-297`; `label_run.py:790` |
| P15 | The AST guard bans reads of `.storage_key` outside `attribution.py`. It does not ban grouping by `LabelRow.family_id`. | `tests/unit/test_aut2_attribution.py:305-322` |
| P16 | The staged label units declare `OnFailure=breezy-autonomy-failed@` and carry no `MemoryMax` until sizing is measured. | `tests/fixtures/aut2_units/breezy-label-outcomes.service:7-12`; `tests/fixtures/aut2_units/promote/README.md` |

**Is the planned path blocked?** Only under one condition that TE-1 cannot clear: if the measured label peak is above 4 GiB, WP6 holds until AUT-6 publishes `aut6.memory_budget` (FQ-R19). The notifier gap (P9) is not a blocker, because the AUT-6 units already ship the same dangling line. The delivery seam (P8) exists. AUT-1b and AUT-5a are not needed: every current fill is pre-epoch (P5, P6).

## Stage 0: verify first (read-only; a failed check STOPs TE-1 and comes back to the coordinator)
- **S0-1.** The fill store `exec/polymarket_us/fill/*` has 34 rows, all BUY, all qty 1, Σ fee 0.27. Use `/home/jon/breezy/.venv/bin/python` with sqlite in `PRAGMA query_only`. **STOP** if the count is not 34: the acceptance baseline would move.
- **S0-2.** All 25 FQ fills bridge to exactly one family. `latch_key_exists(<FQ latch db>, fq_trial_id(...))` is true for each. `pm_us_crh_fq_v1` is the only FQ manifest whose station and `[d0, terminal]` window covers 10-01..10-06. **STOP** on any `no_backfill_family` or `backfill_disagreement`: the result would be UNRESOLVED, which keeps the gate shut.
- **S0-3.** For each fill, `read_climate_day_including_corrections` returns a FINAL record with tmax for that fill's instrument station-day. **STOP** if any is missing.
- **S0-4.** Every FQ fill has `fee_reconciled=True`. Otherwise `realized_pnl` is None (P10).
- **S0-5.** Name the existing legacy CRH join: fill → `trial_id` → frozen `ScoredTrial`, including the 2 residual fills. If it lives only in `scripts/`, record that it must be extracted into `src/` (a move, not a copy; then `lint-imports`).
- **S0-6.** A dry-run label path under `--measure-peak` in a transient unit has a peak ≤ 4 GiB. **STOP** if it is above 4 GiB: that is the FQ-R19 hold, and TE-1 is blocked until AUT-6 publishes `aut6.memory_budget`. Settle the two plan defects from F4-open-items first (transient unit name vs bwrap grammar; peak read from outside the cgroup namespace).
- **S0-7.** Confirm P14 on real data: would the first run raise `aut2.label_lag` for `pm_us_crh_fq_v1` and keep raising it every day? If yes, the peer loop decides between two options (**no code until ruled**):
  - (a) a one-row erratum: the lag clock for fills labelled at first activation starts at activation (`lag_start_ns`), tagged `backlog`;
  - (b) mark FQ v1 `retired` in `families()` once the halt is terminal.
  The option chosen must not stop new fills from being lag-checked.
- **S0-8.** Find where `FqFillInput.venue_settlement_tmax_f` comes from. Does `reconcile.py` have a venue-YES reader that works on the quote-tape catalog for 10-01..10-06?
  - If not, the venue cross-check is UNAVAILABLE for every row (allowed, because the goal says "where the venue exposes it"), and the gap goes to WP9.
- **S0-9.** List every test that pins the current NO_INPUT, skip-marker and OnFailure behaviour: `test_portfolio_roi_run_no_input.py`, `test_score_live_trials_skip_marker.py`, `test_autonomy_units_programme.py`, `test_aut2_units_deploy.py`, `test_no_deployed_file_references_slot_guard_run_until_promotion`, `test_portfolio_roi_deploy.py`. Each one TE-1 must change is widened by one reviewed row. None is relaxed.
- **S0-10.** Check that score-live-trials' `FAMILY_MANIFESTS` loop would include REGISTERED FQ manifests (`score-live-trials-run.sh:111-129`). If so, WP-C must exclude them by `composition_kind`.

## Work packages
Build route: Grok → Codex → Claude tdd-guide. Each brief restates the invariants: Nautilus is immutable; `allow_short=False`; no safety, settlement, contract or NO-SEND test is weakened; no operator cap, enablement or arming is touched.
Every gate runs through `scripts/ci/run_tests_no_egress.sh`. The focused gates include the exec-import-pin and firewall guards, every `test_autonomy_*` and `lint-imports` (cd into the tree, and require the "N kept, 0 broken" line). Order: WP-A and WP-B run in parallel → WP-D → WP-C → WP-E.

### WP-A: production label wiring (F4-open-items step 4)
- **RED first**, in a NEW `tests/unit/test_te1_label_wiring.py`:
  - `test_planner_pre_epoch_fq_fill_bridges_to_v1_storage_key`
  - `test_planner_legacy_crh_fill_joins_frozen_scored_trial`
  - `test_planner_residual_crh_fill_labelled_with_null_pnl_not_missing`
  - `test_planner_unbridgeable_fill_is_unresolved_never_guessed`
  - `test_wiring_settlements_is_nws_cli_final_for_polymarket_us`
  - `test_wiring_deliver_is_deliver_with_proof_through_outbox`
  - `test_wiring_memory_gate_uses_measured_peak_and_missing_aut6_reading` (it holds above 4 GiB)
  - `test_wiring_proof_window_hook_is_none_while_wp7_inactive`
  - `test_main_under_unit_runs_wired_factory_not_not_wired`
  - `test_unattributed_unsettled_row_is_reported_not_zero_pnl` (P10)
- **Files:**
  - NEW `src/breezy/analysis/labeling/unit_wiring.py`: the `UnitFactory`. It reuses `attribute_fill`, `C1Epoch`, `latch_key_exists`, `settlement_source_for`, `StudiesFlock`, `deliver_with_proof` and `OFFLINE_PLUGINS`. It adds no new attribution rule.
  - `label_run.py` `__main__`: pass the factory.
  - A move-only extraction of the legacy join into `src/` if S0-5 requires it.
  - `PRODUCER_SOURCE_SHA256` pin, in the same commit.
- **Acceptance:**
  - On a fixture copy of the 34-fill shape, the run writes LABELLED with `missing_label = unresolved = pending = 0` and `durable_fill_count == 34`.
  - Every FQ row is UNATTRIBUTED, carries `p_source` none, and has non-null `realized_pnl`.
  - The default `__main__` no longer prints `not_wired`.

### WP-B: accounting P&L, the per-fill and per-family artefact, and the NO_INPUT / count-mismatch alert (the TE-1 delta)
- **Decision for the peer loop (recommended):**
  - Accounting is not a statistic. Realised P&L sums every final entry row with non-null `realized_pnl`, whatever its `admissible` value.
  - `admissible` stays the only gate for AUT-3, AUT-4 and AUT-5 consumers.
  - Pre-epoch rows are grouped by `LabelRow.family_id` and carry `attribution_basis=pre_epoch_bridge`. No code reads `.storage_key`, so P15 still holds.
  - No C4 verdict is built from these sums.
- **RED first**, in `tests/unit/test_portfolio_roi_report.py` and a NEW `tests/unit/test_te1_pnl_artefact.py`:
  - `test_c2_accounting_pnl_includes_final_non_admissible_rows` (it fails today on `:4068-4074`)
  - `test_unlabelled_fq_zero_but_pnl_absent_is_not_status_ok` (the P11 regression)
  - `test_per_fill_table_partitions_every_ledger_fill_exactly_once`
  - `test_per_family_totals_sum_to_portfolio_total`
  - `test_wins_fees_net_reproduce_recipe_fixture` (a synthetic 34-row fixture built from the audit recipe; it never contains live amounts)
  - `test_fill_count_mismatch_alerts_and_exits_nonzero`
  - `test_no_input_with_ledger_fills_alerts_and_exits_nonzero`
  - `test_null_realized_final_row_counted_unsettled_and_alerted`
  - `test_venue_crosscheck_disagree_alerts_unavailable_reported`
  - `test_legacy_and_c2_overlap_still_refused` (an existing guard, kept)
  - `test_schema_v5_reader_accepts_1_to_5`
- **Files:**
  - `scripts/analysis/portfolio_roi_report.py`: `c2_rows` is split into `c2_admissible_rows` (statistics) and `c2_accounting_rows` (P&L); a `fill_pnl` table and a `family_pnl` table are added; `PORTFOLIO_ROI_SCHEMA_VERSION` becomes 5, additive only; the two new alert events go through the existing `sink` / `emit_alert` ladder.
  - `scripts/analysis/current_rung_hold_exit_window_study.py`: the reader's known-version set.
- **Acceptance:**
  - `fill_pnl` has one row per ledger fill. Its status is one of SETTLED, OPEN, UNSETTLED or RESIDUAL_PENDING. It records win, payout, cost, fee, net and the venue check.
  - `len(fill_pnl) == n_ledger_rows`, or the run alerts FILL_COUNT_MISMATCH and exits 1.
  - Live fills exist but no P&L is published (gated, stale or absent marker) → it alerts NO_INPUT and exits 1. `OnFailure=breezy-study-failed@` then delivers a second time.
  - Amounts stay in the 0600 `PRIVATE_` JSON. The journal line stays dimensionless, which the wrapper's withholding (`portfolio-roi-run.sh:126-135`) already enforces.

### WP-C: the promotion, as one change (F4-open-items steps 1, 2, 3, 6; step 5 is excluded by design)
- **RED first:**
  - `test_label_unit_deployed_with_dual_onfailure` (`breezy-autonomy-failed@` plus `breezy-study-failed@`)
  - `test_label_unit_memory_max_from_measured_label_peak` (the WP6-size test, using WP-D's artefact)
  - `test_label_bwrap_row_binds_evidence_alerts_for_outbox` (one reviewed row widened; P13)
  - `test_score_live_trials_runs_crh_loop_when_sender_is_fq`
  - `test_score_live_trials_loop_excludes_fq_manifests`
  - `test_portfolio_roi_run_proceeds_on_closed_skip_reason`
  - `test_no_input_line_now_alerting_not_benign` (the `test_autonomy_units_programme.py` regex row is widened, not deleted)
- **Files:**
  - `git mv tests/fixtures/aut2_units/breezy-label-outcomes.{service,timer}` → `deploy/systemd/`, with the measured `MemoryHigh`/`MemoryMax` and the dual `OnFailure=` added.
  - The staged pair `promote/breezy-score-live-trials.{service,timer}` copied over the deployed pair.
  - `score-live-trials-run.sh`: when `resolve_rc=2`, run counter 1 and the non-FQ scorer loop; write only the skip marker (the tallies are unchanged).
  - `portfolio-roi-run.sh`: the closed skip reason runs the report.
  - `src/breezy/runtime/autonomy_sandbox/table.py` (the bwrap row).
  - `deploy/systemd/README.md`.
- **Acceptance:** before install, the gate reads EXIT=0 and the `NeedDaemonReload` preflight is clean.

### WP-D: sizing (coordinator; it gates WP-C)
- Run `label_run --measure-peak` in a quiet window, inside a transient unit whose name fits the bwrap grammar, with MemAvailable ≥ 16 GiB and one heavy job at a time.
- Commit the `aut2_memory_peak/v1` artefact together with WP-C.
- Above 4 GiB, STOP (S0-6).

### WP-E: activation and live proof (coordinator; activate on merge)
- Run `daemon-reload` and `systemctl --user enable --now breezy-label-outcomes.timer`, outside the launch window `[16:30Z, 17:10Z)` and outside the night `[01:00Z, 04:30Z)`.
- Run the L-1 positive controls from F4-open-items at the first live read.

## Dependencies
- **DONE:**
  - F4 WP0–3, 5, 6-build, 8 and plugins;
  - F2 truth fetch (LIVE);
  - AUT-6 WP1 (outbox, redeliver, `deliver_with_proof`).
- **Conditional:** AUT-6 `aut6.memory_budget`, only if the peak is above 4 GiB (FQ-R19).
- **Not required:**
  - AUT-6 WP4/WP7 notifier: the dangling line becomes live when it lands, and `breezy-study-failed@` covers delivery until then;
  - AUT-1b C1 wiring, AUT-5a C5 fold;
  - WP7 flip and the proof window (`WP7_ACTIVE=False` stays);
  - WP9 position and cash legs (they stay INCONCLUSIVE, a known F4 gap).
- **Needs a coordinator ruling:** WP6-promote runs as F4 / TE-1 scope ahead of AUTONOMY row 9, whose Needs 3 and 8 are OPEN. F4-open-items already treats promotion as F4 work.
- **Forward compatibility:** once AUT-1b writes the epoch, new fills take the POST_EPOCH C1 path unchanged, and `entry_ask` is filled in from the decision record (`fq_scorer.py:299-301`).

## Decision-time ask: a separate row, not TE-1
- Recommendation: keep it out of TE-1.
- `LabelRow.entry_ask` and `slippage` already populate from `Attribution.decision.ask_px` once C1 decisions exist (`fq_scorer.py:299-301,315`). That capture is AUT-1b's scope (AUT-1 score-3 includes "depth snapshot at decision time").
- TE-1 only reports `n_entry_ask_unknown` in the artefact.
- Add a cross-link on PROGRESS row 8 (AUT-1b). Open a new TE-4 row only if Stage 0 finds that AUT-1 r12 does not capture `ask_px` for FQ Take decisions.

## Risks and mitigations
- **The FQ label rows fix the history in one direction.**
  - Risk: pre-epoch rows are final at first write, even when they are unsettled (P10).
  - Mitigation: S0-3 and the WP-B UNSETTLED alert. A null P&L is never read as zero.
- **The label-lag CRITICAL repeats every day** (P14). Mitigation: S0-7 ruling before WP-A merges.
- **Accounting vs statistic semantics.** Mitigation: an explicit ruling in the peer loop; the AST guard is unchanged; no verdict is built from the accounting sums.
- **Changing the NO_INPUT behaviour touches AUT-6 WP3 contract tests.** Mitigation: rows are widened, never relaxed; the new behaviour is stricter.
- **Deployed units are symlinked.** Mitigation: one change, preflight before install, and the slot guard lands together with the label timer (F4-open-items).
- **The alert path.**
  - Risk: unit crashes before AUT-6's notifier exists.
  - Mitigation: dual `OnFailure=`; the report's own `emit_alert`; the outbox redeliver. Delivery is proven by the WP-E drill, not assumed.
- **Concurrency and memory.** Mitigation: studies flock in process, the measured `MemoryMax`, the exec store read only through a snapshot (`take_flock=False`).

## Live proof (LIVE = the first scheduled success has been seen)
1. The first **timer-fired** `breezy-label-outcomes` run (14:15Z) exits 0 with a LABELLED marker and `durable_fill_count=34 pending=unresolved=missing_label=0`.
2. That same day's **timer-fired** `breezy-portfolio-roi` run (17:40Z) exits 0, and its artefact shows:
   - `n_ledger_rows=34`, `len(fill_pnl)=34`, wins 2, net −4.63, fees 0.27;
   - family totals: crh families −0.46, `pm_us_crh_fq_v1` −4.17.

   Any mismatch with the audit is a STOP and a diagnosis. Never tune the numbers to match.
3. **Delivery drill:** one `--drill` invocation of the report, writing only to an isolated output root with labels pointed at an empty root, produces a NO_INPUT alert with a `deliver_with_proof` delivered record and `drill=true`.
4. **Second day:** the second scheduled pair also succeeds. Until then the status is "built, not LIVE".

## Rollback
1. `systemctl --user disable --now breezy-label-outcomes.timer`.
2. `git revert` the WP-C change, which restores the deployed score-live-trials pair and the wrappers, then `daemon-reload` after the preflight.
3. Revert WP-B; portfolio_roi returns to schema v4 and the reader still accepts v1–v4.
4. Label, marker and verdict files are write-once and additive. Leave them in place. Nothing reads them once WP-B is reverted.
5. The exec store is never written, so nothing there needs undoing.

## Explicit non-goals
- Root-causing FQ 0/25 (TE-2); the NO-side hypothesis (TE-3); any re-arm, enablement, halt-clear or cap change.
- Persisting the decision-time ask (AUT-1b).
- WP9 position and cash reconciliation legs; venue-positions reads.
- The proof window and the WP7 flip; AUT-4 / AUT-5 consumption of labels; any change to `admissible`.
- Kalshi settlement (TWC source stays refusing).
- KILL clock and tally semantics; reading M1-v3 data.
- Exec client, Nautilus, or NO-SEND changes.

## Success criteria
- [ ] Stage 0 S0-1..S0-10 recorded, and S0-7 ruled.
- [ ] RED → GREEN output kept for WP-A, WP-B and WP-C. The full gate reads EXIT=0 after each merge, and `lint-imports` reports "N kept, 0 broken".
- [ ] Live proof 1–4 observed, with artefact paths, journal lines and SHAs cited by a reviewer who did not build it.

Relevant paths:
- /home/jon/breezy/src/breezy/analysis/labeling/label_run.py
- /home/jon/breezy/src/breezy/analysis/labeling/label_core.py
- /home/jon/breezy/src/breezy/analysis/labeling/fq_scorer.py
- /home/jon/breezy/src/breezy/analysis/labeling/attribution.py
- /home/jon/breezy/src/breezy/analysis/labeling/memory_gate.py
- /home/jon/breezy/src/breezy/analysis/labeling/completeness.py
- /home/jon/breezy/src/breezy/runtime/autonomy_sandbox/table.py
- /home/jon/breezy/scripts/analysis/portfolio_roi_report.py
- /home/jon/breezy/deploy/systemd/score-live-trials-run.sh
- /home/jon/breezy/deploy/systemd/portfolio-roi-run.sh
- /home/jon/breezy/tests/fixtures/aut2_units/
- /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F4-open-items_2026-10-06.md
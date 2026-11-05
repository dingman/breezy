# AUT-2: outcome labeling (scoring, P&L, reconciliation). Plan r3

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-2 |
| Title | Outcome labeling: family-agnostic scorer, C2 label store, net-position and cash reconciliation |
| Round | r3 (2026-10-03). Disposes B1–B13 of `reviews/AUT-2-r2-merged.md` (§R3). r2 (`AUT-2-outcome-labeling_plan_r2.md`) is unchanged. |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 5**, snapshot `reviews/snapshots/ARCH_rev5.md` sha256 `5d2b75fa77e2c0abaaa478bd38d32e7e06ac98c8057ce50a5045f0dd0eff8403`. Rev 5 now carries W1, W8 (§4.4, post-STOP producer `breezy-autonomy-reconcile-poststop`, `POST_STOP_RECONCILE_RUNTIME_S ≤ 120`), W12 and W14 (`voided_pair` in C2). |
| Repo state read | `4b8347a6` on `feat/data-capture-and-risk`; live artefacts under `~/.local/share/breezy/` as of 2026-10-03 ~04:15Z |
| Current score | 1 (README) |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: `persistence/autonomy/` schemas, C6 Protocols, `RefusingPlugin`, `pins.py`); **the residual C2 widening (§10 C-1), a hard prerequisite for any label write**; AUT-1 (C1 `decision_id`, `DecisionRecord`, `OrderLink`, `SettlementRecord`; **a hard prerequisite for the proof-window start, B5**); AUT-6 (`deliver_with_proof`); AUT-5a (compose-time refusal, `app/trade.py:853`; the journaled STOP-completion signal, ARCH §4.4); AUT-5b (policy block) |
| Downstream | AUT-3 (C2 admissible `(p_at_decision, settled_outcome)`); AUT-4 (C2 admissible labels; champion slippage); AUT-5 (C4 `RECONCILIATION` daily, intraday and post-STOP; ATTEST inputs, W1; §4.4 pre-launch input, W8); AUT-6 (C4 `HEALTH aut2.label_lag`, `aut2.label_coverage`; drill rows readable for W12) |

---

## 1. Goal state

**README AUT-2 score-3 criterion (verbatim):**
- Scoring is a family-agnostic scorer contract. A family manifest cannot register or send without a scorer, enforced by a registration-time test.
- Every fill, entry or exit, YES or NO leg, is labelled automatically within 24 h of settlement with: the settled outcome, the realised P&L net of the reconciled fee, the forecast probability at decision, and the counterfactual hold result for exits.
- Labels are reconciled against venue settlement and balance evidence within a stated tolerance.
- Sign and leg conventions are pinned by tests: the venue nets a NO holding as short YES.
- No unit fails as a matter of expected behaviour.

**README AUT-2 live proof (verbatim):** "every live fill over 7 consecutive days is labelled, with reconciliation passing on each day, covering at least one NO-leg fill if one occurs and at least one exit if one occurs. All of it is run by the timers with no hand step."

**ARCH Rev 5 §10 AUT-2 obligations (verbatim, `ARCH_rev5.md:927-931`):** "the −0.37/+0.37 root cause with artefact evidence before any scorer change; the per-leg reconciliation tolerance; the intraday RECONCILIATION producer (cadence within the W1 invariant) and the post-STOP producer (§4.4: STOP signal, venue snapshot source, runtime bound); exclusion of `canary`, `drill` and `voided_pair` rows; the canary store's `Scorer` input (Z14); the label-lag alert; the measured rate of AMBIGUOUS intents open at 16:45Z (Z19)."

Section map: root cause §3.1 and WP1; per-leg tolerance §3.6; intraday producer §3.11 (cadence row and test); post-STOP producer §3.11 (STOP signal, live-node guard, snapshot source, runtime bound); canary, drill and voided-pair exclusion §3.4.2, §3.8; canary Scorer input §3.8; label lag §3.7.2; Z19 §3.9; completeness §3.12.

---

## 2. L-1 null hypothesis and reuse

Nautilus has no settlement scorer, no label store and no venue-versus-ledger reconciliation for an offline process. `Position.realized_pnl` covers only in-node lifetime and excludes settlement payouts that arrive after the node stops, so it is not a label source. Nautilus's in-memory same-side average also ignores partial exits (`adapters/polymarket_us/exec/client.py:208-220`), so it is not the exit-matching rule either (B4).

| New component | Checked against | Verdict |
|---|---|---|
| C2 label store `persistence/autonomy/label_store.py` | `scored_trial_store.py:24-31,60-89`; `ScoredTrial` (`trial_scorer.py:130-155`) | **Reuse the conventions, not the schema** (no `family_id`, leg, role, p, decision id). Parquet, atomic `os.replace`, `(id, max seq)` dedupe copied. |
| Settlement resolution, including the venue fallback (B3) | `score_trial` (`trial_scorer.py:167-231`); `_resolve_settlement_basis` (`:234-265`), whose fallback branch is exactly `final is None ∧ now_ns ≥ scheduled_release_at_ns + _SEVEN_DAYS_NS ∧ venue_settlement_tmax_f is not None` → `("venue_last_fair_price_fallback", "venue_settled_without_nws", venue_tmax, 0, "")` (`:247-255`); `_SEVEN_DAYS_NS` (`:56`); `read_climate_day_including_corrections` (`persistence/catalog.py:637`); `default_registry().settlement_site` (`score_live_trials.py:778`) | **Reuse unchanged.** AUT-2 never re-derives the fallback trigger; it maps the scorer's `excluded_reason` string (§3.5). |
| Venue settlement instant (label-lag clock; "open" test) | `default_registry().settlement_deadline(venue, city)` (`registry/sites.py:413`) and `settlement_deadline_ns(deadline, climate_day)` (`registry/settlement_clock.py:36`): 08:00 America/New_York on climate_day+1, with the conditional 11:00 ET delay stored, never computed (`registry/sites.toml:55-70`) | **Reuse.** No new clock arithmetic. |
| Rung facts from the slug | `_read_bucket_facts_by_instrument_id`, `_bucket_facts_from_instrument_id` (`score_live_trials.py:579,620`) | **Reuse** via a pure extraction into `analysis/labeling/instrument_facts.py`, re-imported by `score_live_trials.py` (byte-identical behaviour; L-46). |
| Leg netting | `leg_of_symbol` (`domain/instrument_leg.py:58`); `base_slug_of`, `leg_of` (`symbology.py:289-298`) | **Reuse.** `net_signed_qty` defined once in `persistence/autonomy/net_position.py`, shared with `entry_guard` (or imported from Wave 0 if it placed it there). |
| **Exit-to-entry cost matching (B4)** | `_entry_price_from_records` (`adapters/polymarket_us/exec/client.py:4495-4544`): `sum(signed cost) / sum(signed qty)` over every durable record per instrument, SELLs netted, chosen because it "conserves LIFETIME REALIZED PNL" (`:208-220`, worked example BUY 4@0.50, SELL 1@0.60 → lifetime 1.60). `reconcile_daily` is **matching-free**: capital at BUY `ts_event`, proceeds at receipt, SELLs excluded today (`exit_label_for_fill`, `portfolio_roi_report.py:445-468`; `_cash_between`, `:1043-1088`). `net_signed_qty` is quantity-only. | **Reuse the weighted-average cost rule** of the exec client (§4 WP4). The cash identity and `net_signed_qty` are invariant to the matching choice; the rule only allocates cost among labels, and lifetime Σ must equal the exec client's. `average_cost_basis` lives beside `net_signed_qty` in `net_position.py`, the single definition. |
| Durable fill reader | `DurableFillRecord.from_bytes` (`adapters/polymarket_us/exec/client.py:1004-1066`); `FILL_KEY_PREFIX` (`:408-415`); G6 `mode=ro` URI (`trial_day_latch.py:354-379`); `read_ledger_fills_with_counts` (`portfolio_roi_report.py:299`) | **Reuse `from_bytes`, the G6 URI and the counted reader** (counts feed the completeness denominator, §3.12). |
| Exec-store read with the node stopped (post-STOP slot) | `probe_open_intent` (`runtime/trade_supervisor.py:402-420`) reads the exec store only after `assert_no_live_node_before_intent_probe` (`runtime/trade_supervisor_core.py:554-560`), with the PID from `find_pid_by_argv(NODE_ARGV_ANCHOR)` (`trade_supervisor.py:531-548`; anchor `"breezy-trade$"`, `trade_supervisor_core.py:81`) | **Reuse both functions directly (B10).** `analysis` sits above `runtime` in the import-linter layers contract (`pyproject.toml:78-99`), so the import is permitted, and no live package imports `analysis` (`pyproject.toml:152-160`). No copy of the guard. |
| Legacy CRH fill coverage | `FillBucket`, `bucket_ledger_fills` (`portfolio_roi_report.py:536-597`); `_fee_unverified_fills_deduped` (`:650`); `read_filled_trials_state_db` (`analysis/prereg_admission.py:234`) | **Reuse** for the legacy partition. Not reusable for FQ (F4/F5). |
| Cash reconciliation, including legacy proceeds (B9) | `reconcile_daily` (`portfolio_roi_report.py:1618-1865`; identity `unexplained = Δbalance − proceeds + capital_deployed`); `capital_deployed_by_day` (`:1096`, every BUY fill, legacy included); `_fills_opened_count_by_day` (`:1110`); `settlement_payout` (`:1123`); `ResidualSettlement` (`:1146`, a plain `(payout, dated_at_ns)` cash record) and `residual_settlement` (`:1190`); `proceeds_by_day` (`:1341`, dated by `scored_at_ns`, `proceeds_date` `:1231`); `per_day_tolerance` (`:1390`); `cumulative_reconciliation` (`:1986`) | **Reuse unchanged.** C2 payouts, exit proceeds and netting offsets enter through the existing `residual_settlements` parameter as `ResidualSettlement` records with explicit `dated_at_ns`; legacy `ScoredTrial` and legacy residuals stay in their own parameters. No new parameter on `reconcile_daily`. |
| Venue position snapshot | `scripts/venue/polymarket_us_positions_value_capture.py` (`capture` `:191`, `redact_positions` `:148`, `run_capture` `:237`, pagination `eof`/`nextCursor`); `assert_get_only` (`polymarket_us_private_shape_probe.py:175`); capital-flow pull non-egress test (`test_polymarket_us_capital_flow_pull.py:378`) | **Extend, do not rebuild.** `scripts/venue/polymarket_us_positions_pull.py` adds cursor-following, the `venue_positions/v1` reduction and the snapshot writer. SDK fields `netPosition`, `expired`, `marketMetadata` (`sdk_snapshot/.../types/portfolio.py:21-34`). |
| Venue settlement and netting evidence | Tape `custom_venue_settlement_snapshot`; SDK `PositionResolution` activity (`types/portfolio.py:68-76`) read by the capital-flow pull's `account_activity.py` | **Reuse.** The fallback payout cross-check and the YES/NO netting event (B2) are read from the activity feed (**INFERRED** field use; WP5 L-1 (iv), (vii)). |
| p at decision (pre-C1 cross-check) | `SHADOW_DECISION` log line (`fq/strategy.py:577-581`; `decision_log_fields`, `fq/decision.py:178-213`) and Nautilus `OrderInitialized`/`OrderFilled` lines (verified: `breezy-trade-20261002T205521Z.log` lines 8359, 8361, 8393) | **Reuse the bot's own output.** p is never recomputed (L-2). After B5 the bridge is a backfill and cross-check path, not a proof-window source. |
| C4 writer, payload hygiene | Wave 0 C4 writer; `AlertPayload` hygiene (`registry/health_model.py:217-235`) | **Consume.** |
| Units | `score-live-trials-run.sh`, `portfolio-roi-run.sh` (studies flock, marker idiom); capital-flow pull unit | **Reuse the wrapper idioms.** |
| Monitor scoping (WP1) | `resolve_trial_family` (`position_monitor_nightly_report.py:132-165`) | **Reuse** as the filter predicate. |

---

## 3. Design

### 3.1 Root cause of −0.37 versus +0.37 (WP1 commits the evidence note)

1. Every 2026-10-02 monitor report (`position_monitor_report_2026-10-02_pm_us_crh_{v4,v2,cont,fq_v1}.md`) shows the same single row: `positions: 1 (settled 1)`, `SETTLED ... n=1 realized_pnl_total=-0.3700`.
2. That row is the v4 trial `continuous_rung_hold/trial/SFO/2026-09-21/tc-temp-sfohigh-2026-09-21-gte66lt67f.POLYMARKET_US` (YES; `pnl=-0.3700`) in `derived/scored_trials/pm_us_crh_v4/scored_trials_20260922T141816645708220Z.parquet`.
3. **Mechanism.** `main` passes all summaries and all pooled scored trials into `build_monitor_report` (`:862-925`); `--family-manifest` only stamps `RuleSeries.family` (`_exit_rule_series`, `:698-742`). Nothing filters by family, and the wrapper runs once per REGISTERED manifest (`position-monitor-report-run.sh:206-209`).
4. The v4 tally `total pnl 0.3700` is the sum of three v4 fills: MIA NO 09-21 −0.13, SFO YES 09-21 −0.37, MDW NO 09-22 +0.87.
5. **Why only 1 of the 3 v4 fills is a monitor row.** Report rows are monitor summaries: `_join` (`:539-586`) iterates summaries and settles each from a joined `ScoredTrial`; a scored trial with no summary never becomes a row. `read_monitor_summaries` (`monitor_store.py:262-278`) finds exactly one live summary file (`position_monitor_summaries_20260922T164011274098669Z.parquet`, the 09-22 16:40Z STOP flush), whose only 09-21/09-22 row is the SFO YES trial. MDW NO 09-22 filled in a later session that wrote no summary file. Why MIA NO 09-21 is absent from the 09-22 flush is **INFERRED** (NO-leg registration at that build, or no adoption at boot); WP1 records the verified mechanism.
6. **Verdict.** No sign error. The defect is attribution. FQ has zero scored fills (S7 branch skips the kind) and composes no `PositionMonitor`.

Further findings, each handled by a WP: F2 `portfolio-roi` exits 1 daily (WP1, WP6); F3 09-30 gross versus net (WP1, WP5); F4 FQ `trial_id_prefix` matches no key (WP2); F5 latch is not a fill join key (WP2); F6 exit fills never evaluated, and `reconcile_daily` excludes SELLs (`portfolio_roi_report.py:445-468`) (WP4, WP5); F7 11 durable FQ fills, 5 settled and unlabelled (WP3 backfill).

### 3.2 Package layout (analysis layer; never imported by a live package)

```
src/breezy/persistence/autonomy/            (Wave 0 owns schemas.py, plugin.py, pins.py)
    label_store.py      write_labels(), read_labels(), LABEL_V1_SCHEMA consumer        [AUT-2]
    net_position.py     net_signed_qty(fills), average_cost_basis(fills, at_ns) (B4)    [AUT-2 unless Wave 0 placed it]
    canary_store.py     CANARY_ROOT = derived/canary/, append_canary_fill(), read_canary_fills()   [AUT-2, Z14]
src/breezy/analysis/labeling/
    constants.py        LABEL_LAG_MAX_H=24, WINDOW_INCOMPLETE_MAX_H=48, RECON_DAILY_VALIDITY_H=26,
                        RECON_INTRADAY_VALIDITY_H=8, INTRADAY_PERIOD_MIN=30, SNAPSHOT_MAX_AGE_MIN=45,
                        INCONCLUSIVE_ALERT_DAYS=2, BRIDGE_TAKE_TO_INIT_MAX_S=2, BRIDGE_INIT_TO_FILL_MAX_S=300,
                        POSITION_SETTLE_GRACE_S=60 (B1), POST_STOP_RUNTIME_S=100 (≤ pins.POST_STOP_RECONCILE_RUNTIME_S)
    instrument_facts.py extracted from score_live_trials.py (pure move)
    fill_source.py      read_durable_fills(db_path) -> FillRead(fills, n_keys, n_undecodable)
    attribution.py      attribute_fill(fill, manifests, fold|None, c1|None) -> Attribution | Unattributed
    decision_link.py    DecisionLink from C1, or NodeLogBridge (backfill and cross-check)
    probability.py      p_of_bought_leg(p_hat_yes, side)
    fq_scorer.py        ForecastQuantileLadderScorer (C6 Scorer)
    exit_labels.py      label_exit(sell_fill, open_lots, settlement) -> LabelRow (average cost, B4)
    settlement_source.py SETTLEMENT_SOURCES: {polymarket_us: NwsCliFinal, kalshi: RefusingSettlementSource}
    completeness.py     coverage_partition(fills, labels, legacy) -> Coverage (B6)
    reconcile.py        reconcile_positions(), reconcile_settlement(), reconcile_cash(), cash_records()
    verdicts.py         build_reconciliation_verdict(mode), build_health_verdicts(mode)
    prelaunch_intents.py observe_intents_post_stop(), reconstruct_ambiguous_open_at() (Z19)
    delivery.py         deliver_or_fail(payload) -> raises AlertDeliveryFailed (B12)
    label_run.py        python -m breezy.analysis.labeling.label_run [--canary|--proof-window]
    recon_run.py        python -m breezy.analysis.labeling.recon_run --mode {intraday,post_stop}
src/breezy/analysis/plugins.py   OFFLINE_PLUGINS gains the FQ Scorer entry          [one line]
scripts/venue/polymarket_us_positions_pull.py   wraps positions_value_capture.capture(); cursor-following; snapshot writer
deploy/systemd/breezy-label-outcomes.{service,timer}, label-outcomes-run.sh
deploy/systemd/breezy-aut2-reconciliation.{service,timer}, aut2-reconciliation-run.sh     (intraday, W1)
deploy/systemd/breezy-autonomy-reconcile-poststop.{service,timer}                          (W8; ARCH §4.4 unit name; same wrapper, --mode post_stop)
```

Each reconciliation unit runs the positions pull, then the reconcile step, as sequential `ExecStart=` lines in one oneshot, so every snapshot is consumed by a verdict.

Stores (0700 dirs, 0600 files, atomic writes, ns-named files):
- Labels: `derived/labels/<family_id>/labels_<now_ns>.parquet` (C2). Canary labels: `derived/labels_canary/<family_id>/`.
- Snapshots: `evidence/venue_positions/<venue>/positions_<now_ns>.json` = `{schema: "venue_positions/v1", snapshot_ns, complete: bool, pages, rows: [{base_slug, net_qty, expired}]}`; no account, position or order ids.
- **Per-snapshot position comparisons (B1):** `evidence/aut2/position_compare_<YYYY-MM-DD>.jsonl`, one row per `(snapshot_ns, base_slug)`: `{snapshot_ns, snapshot_sha256, base_slug, venue_net_qty, ledger_net_qty, result ∈ {MATCH, MISMATCH, NOT_COMPARED_GRACE, NOT_COMPARED_INTENT, SETTLED_AWAY}}`; quantities only, no ids or amounts.
- Canary: `derived/canary/<venue>/canary_fills_<YYYY-MM-DD>.jsonl` (ARCH §5.3 path). Never opened by `fill_source.py`.
- Durable unattributed journal: `evidence/aut2/unattributed_<YYYY-MM-DD>.jsonl` (fill key, base slug, ts_event, rule outcomes; no amounts).
- Run marker: `derived/label_outcomes_ok_<YYYY-MM-DD>.json` (§3.12).

### 3.3 C6 `Scorer` and the registration gate

- `ForecastQuantileLadderScorer.label(capture_day, exec_fills, settlements) -> tuple[LabelRow, ...]` registered in `OFFLINE_PLUGINS[CompositionKind.forecast_quantile_ladder].scorer`; it declares `legs = {"yes","no"}`, `roles = {"entry","exit"}`. CRH kinds keep `RefusingPlugin`; their historical fills are covered by the frozen legacy store (§3.12).
- **Family-agnostic.** `label_run` iterates `OFFLINE_PLUGINS` over the family set defined in §3.4.2. No family literal.
- **Registration-time gate:** `tests/contract/test_aut2_scorer_registration.py::test_every_non_retired_manifest_kind_has_a_non_refusing_scorer`; `::test_new_manifest_without_scorer_cannot_register`; `::test_scorer_declares_both_legs_and_both_roles`.
- **Compose-time cross-plan acceptance test, owned by AUT-2:** `::test_armed_family_with_refusing_scorer_is_refused_at_compose` builds a REGISTERED armed fixture manifest whose kind's scorer is `RefusingPlugin`, calls the production `_compose_family` (`app/trade.py:853`, AUT-5a's file) and asserts refusal. AUT-2 never edits `app/trade.py`. Hard prerequisite: AUT-5a's compose-time refusal.

### 3.4 Fill source, attribution, decision link

#### 3.4.1 Universe
Every `DurableFillRecord` under `exec/polymarket_us/fill/` (G6 URI). Today 20 fills (11 FQ, 9 legacy CRH). The canary store is read only by the canary path (§3.8).

#### 3.4.2 Attribution by registration status at `ts_event`
In order:
- (a) **C1:** `client_order_id → OrderLink → decision_id → DecisionRecord.family_id`. Authoritative.
- (b) **C5 fold at `fill.ts_event`:** the family CHAMPION on the venue at that instant (G1). Must agree with (a). **Voided-pair (W14, now in Rev 5 C2):** if `ts_event` is inside a pair's effective-then-voided interval (Z8) and (a) names that pair's child, the fill is attributed to the child with `excluded_reason=voided_pair`. Any other disagreement leaves the fill unattributed and sets `FAILED_IDENTITY` (§3.12, B6).
- (c) **Pre-C1/C5 bridge:** base-slug grammar gives `(station, climate_day, rung, leg)`; the kind latch key must exist (FQ: `FORECAST_QUANTILE_TRIAL_KEY_PREFIX`, `persistent_latch.py:68`); the family is the unique manifest with `status == REGISTERED`, `composition_kind == kind`, matching venue, `station ∈ stations` and `d0_climate_day ≤ climate_day ≤ terminal_climate_day` (`family_manifest.py:388-405`).
- **Retired families keep being labelled.** The run's family set is every family non-RETIRED now plus every family with an attributed durable fill without a final label. Pinned by `test_retired_family_labelled_until_last_fill`. C6 conflict in §10 C-6.
- **Unattributed** (no rule yields exactly one family): no C2 row; a durable row in `evidence/aut2/unattributed_<date>.jsonl`; `HEALTH FAIL aut2.label_coverage` once the policy block exists; CRITICAL; the run outcome is `FAILED_IDENTITY` (§3.12).

#### 3.4.3 Identity
`trial_id = manifest.trial_id_prefix + "<STATION>/<day>/<rung_id>:<side>"` (F4). `label_id` = first 32 hex of `sha256("label/v1"|family_id|client_order_id|trade_id or ""|role)`; dedupe on `(label_id, max label_seq)`.

#### 3.4.4 Decision link and p of the bought leg
- **Post-C1 (authoritative, and the only proof-window source, B5):** `decision_id`, `p_hat`, `side`, `entry_ask = ask_px` from `DecisionRecord`.
- **Bridge (backfill before WP7; cross-check after WP7):** keyed on `client_order_id` within bounded windows: (1) the durable fill's `client_order_id` and `trade_id`; (2) the `OrderFilled` line with both (log line 8393); (3) the `OrderInitialized` line with the same `client_order_id` (line 8361) at most `BRIDGE_INIT_TO_FILL_MAX_S = 300 s` before; (4) exactly one `SHADOW_DECISION` line with `kind == 'Take'`, the same `instrument_id`, `now_ns ∈ [init_ts − 2 s, init_ts]` (lines 8359→8361). Zero or two → `pre_c1_log_unmatched`. Line adjacency is never used; the search covers the node log file spanning `ts_event` and its predecessor (never journald).
- **Probability conversion.** FQ's `Take.p_hat` is P(YES rung) in both side modes (`fq/decision.py:349`; `ladder_ev/scoring.py:70-87`), copied into C1 `DecisionRecord.p_hat`. `p_at_decision = p_hat if side == "yes" else 1 − p_hat`, applied identically in both modes, meaning "probability that the bought leg wins". A Take whose `side` disagrees with the fill's leg is `pre_c1_log_unmatched` (bridge) or CRITICAL plus `reconciled=False` (C1).
- No match: `p_at_decision = null`, `p_null_reason = pre_c1_log_unmatched`, counted in the `p_null_count` metric (B13, §3.7.1). The row is labelled for P&L and reconciliation, WARN; a proof day with `p_null_count > 0` fails (§6).
- **Bridge match rate (B5).** `bridge_match_rate = bridge-linked fills / fills with a bridge attempt`, computed every run and written to the RECONCILIATION metrics and the proof artefact. Before WP7 it is the p source for the backfill only; the expected rate is measured by the WP3 backfill over the 11 live FQ fills and recorded in its GREEN evidence (no expectation is assumed in advance). After WP7, every fill has a C1 `DecisionRecord`; the bridge result is compared to C1, and any disagreement is CRITICAL plus `reconciled=False`.

### 3.5 Entry labels (YES and NO legs)

| Quantity | YES leg (`<slug>.POLYMARKET_US`) | NO leg (`<slug>^no.POLYMARKET_US`) |
|---|---|---|
| Durable record | `orderSide BUY`, cost in YES units | `orderSide BUY` (adapter sends venue `SELL`/`BUY_SHORT`, G24), cost in NO units |
| `fill_px` | `cumulative_cost / cumulative_qty` | same, NO units |
| `p_at_decision` | `p_hat` | `1 − p_hat` (§3.4.4) |
| `settled_outcome` | `score_trial(...).held` | `score_trial(...).held` (leg-aware, `trial_scorer.py:207-209`) |
| `cost_basis` (fee-inclusive) | `cumulative_cost + fee_reconciled` | same |
| `realized_pnl` (held to settlement) | `qty·payoff − cost_basis` | same |
| Venue net on base slug | `+qty` | `−qty` (L-44; `parsing.py:277-279`) |

- `score_trial` supplies settlement fields; `realized_pnl == ScoredTrial.pnl × qty` is asserted, never smoothed.
- `fee_reconciled = cumulative_fee` only when `fee_reconciled is True`; else `excluded_reason = fee_unreconciled`. Every live `fee_unreconciled` fill alerts: WARN on first label, CRITICAL if still unreconciled after `LABEL_LAG_MAX_H`.
- **Slippage defect.** `slippage = fill_px − entry_ask`. A negative slippage beyond one tick writes `excluded_reason = slippage_defect` (C2 widening, §10 C-1) and a WARN. Until the enum lands, `write_labels` refuses (`LabelSchemaWideningMissing`): `test_label_store_refuses_without_widened_enum`.
- **Admissibility.** `admissible = reconciled ∧ source == live ∧ ¬drill ∧ excluded_reason is None ∧ p_at_decision is not null`. `window_complete` for `(family, climate_day)` = every attributed fill that day has a final settlement or a final exclusion; before that, rows carry `excluded_reason = window_incomplete` and are re-labelled with `label_seq+1`. A `window_incomplete` row older than `WINDOW_INCOMPLETE_MAX_H = 48 h` past the venue settlement instant is a `HEALTH FAIL aut2.label_lag`.
- **Final versus non-final reasons.** Final: `duplicate_fill`, `q≠1`, `fee_unreconciled` (after the lag horizon), `canary`, `drill`, `slippage_defect`, `voided_pair`, `venue_fallback_settlement`. Non-final: `window_incomplete`, `fee_unreconciled` (inside the horizon).
- **Venue fallback settlement (B3).** The trigger is exactly `score_trial`'s basis (`trial_scorer.py:240-255`): no NWS final, `now_ns ≥ scheduled_release_at_ns + _SEVEN_DAYS_NS`, and a venue settlement reading present. AUT-2 never evaluates its own condition. The mapping is literal and total:

  | `ScoredTrial.settlement_basis` / `excluded_reason` | C2 row |
  |---|---|
  | `nws_final` / `None` | normal settlement |
  | `venue_last_fair_price_fallback` / `venue_settled_without_nws` | `settled_outcome = held` and `realized_pnl = pnl × qty` from `score_trial`, `settlement_basis = venue_last_fair_price_fallback`, `excluded_reason = venue_fallback_settlement` (final, inadmissible) |
  | `ScoreRefusal` (no final yet; the 7 days not elapsed or no venue reading) | `window_incomplete` (pending) |
  | any other `excluded_reason` string | `write_labels` refuses (`UnmappedScorerReason`), CRITICAL; never passed through |

  The `PositionResolution` payout is a cash-leg cross-check (§3.6), not the P&L source. **The 7-day pending period raises `aut2.label_lag` by design**: the lag clock starts at the venue settlement instant (§3.7.2), so a fill waiting on the fallback is a `HEALTH FAIL aut2.label_lag` plus CRITICAL from +24 h until the fallback resolves. That is the intended signal (an NWS outage needs a human-visible alert), pinned by `test_fallback_pending_window_raises_label_lag_by_design`. Because the alert is expected in that situation, the HEALTH payload carries `cause=awaiting_venue_fallback` so it is distinguishable, never suppressed.
- **Settlement basis by venue:** `polymarket_us → NwsCliFinal`; `kalshi → RefusingSettlementSource("twc_reader_absent")`.

### 3.6 Reconciliation: three legs, per-leg tolerances (ARCH §10)

#### 3.6.1 Position leg (net; fence and grace, B1)

- **Compared set** = ledger slugs ∪ venue-page slugs. A venue slug with no ledger fill → FAIL (`venue_only_slug`). An open ledger slug absent from the page compares as venue 0. "Open" = `snapshot_ns < settlement_deadline_ns(climate_day)` and the slug has not appeared with `expired == true`. A ledger slug past its deadline and absent from the page is **settled-away** (L-52): not compared, covered by the settlement and cash legs.
- **Fence with a pinned grace.** Ledger side = `net_signed_qty(fills with ts_event ≤ snapshot_ns − POSITION_SETTLE_GRACE_S)`, with `POSITION_SETTLE_GRACE_S = 60` in `constants.py` (pinned by `test_position_settle_grace_pinned`). A slug with **any** fill in `(snapshot_ns − 60 s, snapshot_ns]` is `NOT_COMPARED_GRACE` in that snapshot: neither PASS nor mismatch, because the venue may or may not have applied the fill yet. A slug with an OPEN/AMBIGUOUS intent at snapshot time is `NOT_COMPARED_INTENT` → that verdict INCONCLUSIVE (L-52). Only `complete == true` snapshots are used; an incomplete snapshot is INCONCLUSIVE, never PASS.
- **Tolerance:** 0 contracts, exact Decimal, both legs (YES `+q`, NO `−q` on the base slug; YES and NO fills on one slug are summed with the leg sign).
- **Verdict per snapshot.** Any `MISMATCH` → that verdict's position leg FAIL, CRITICAL. Every comparison is journaled per snapshot (§3.2 store).
- **Label `reconciled` from the latest comparison.** A label's position component is recomputed on every run from the **latest** journaled comparison of its slug (`MATCH` or `MISMATCH`, ignoring `NOT_COMPARED_*`) taken before `settlement_deadline_ns`. If that differs from the stored row, the row is rewritten at `label_seq + 1`. So a transient mismatch (one snapshot MISMATCH, the next MATCH) clears on the next snapshot: the earlier verdict stays FAIL in the record and its CRITICAL is not retracted, but the label is no longer `reconciled=False`. The label stores `position_compared_snapshot_ns` and `position_compare_result` (C2 widening item, §10 C-1).
- **Daily RECONCILIATION position leg** = PASS iff, for every compared slug, its latest comparison is `MATCH`. Transient mismatches in the day are reported as the metric `position_mismatches_transient` and stay CRITICAL-alerted, but they do not fail the daily verdict once cleared. A mismatch still standing at the latest comparison fails it.
- **Coverage.** Every fill must reach a `MATCH`/`MISMATCH` comparison at least once before its settlement deadline (the grace only skips the first ≤ 60 s). `fills_never_position_compared > 0` fails the day. A missing or stale snapshot (`> SNAPSHOT_MAX_AGE_MIN = 45`) makes that verdict INCONCLUSIVE plus WARN. `INCONCLUSIVE_ALERT_DAYS = 2` consecutive INCONCLUSIVE daily verdicts → CRITICAL; the same holds for consecutive `BALANCE_UNKNOWN` days.

#### 3.6.2 Settlement leg

Label `settled_outcome` versus the venue settlement for the slug (tape `custom_venue_settlement_snapshot`; `PositionResolution`), exact equality. Disagreement → `reconciled=False`, CRITICAL `settlement_source_disagreement`; the venue value is never adopted. **Pending is INCONCLUSIVE (B8):** with no venue evidence yet, or a label in fallback pending (§3.5), the leg is `PENDING`. A day with any `PENDING` settlement-leg slug is INCONCLUSIVE, never PASS. No venue evidence 48 h after the CLI final → FAIL.

#### 3.6.3 Cash leg (cumulative net identity)

`reconcile_daily` over the union of all cash sources, through its existing parameters (B9):
- `fills` = **every** durable fill, legacy CRH and FQ (so `capital_deployed` is complete; `capital_deployed_by_day`, `:1096`, already counts every BUY).
- `scored_trials` = the frozen legacy CRH `ScoredTrial` stores, unchanged.
- `residual_settlements` = the legacy residuals (`_resolve_residual_settlements`, `:3769`) **plus** the `ResidualSettlement` records from `reconcile.cash_records(c2_labels)`, three kinds, each with an explicit `dated_at_ns`:
  1. a held-to-settlement payout `qty·payoff`, dated at `settlement_deadline_ns`;
  2. exit proceeds net of the exit fee, dated at the SELL's `ts_event` (`reconcile_daily` books no SELL today: `exit_label_for_fill`, `:445-468`; WP5 L-1 (v) closed);
  3. a **YES/NO netting offset (B2):** when both legs of one base slug are held at once, the venue nets them (L-44). `min(q_yes, q_no) × $1` is dated at the **venue netting event**, read from the activity feed (L-1 (vii)), and those contracts' settlement payouts are not booked again at settlement. If the netting event is not observable, every cash day from the offsetting fill through the slug's settlement is INCONCLUSIVE (`cash_unknown_netting_offset`), never FAIL. Per-leg labels are unaffected: Σ over the two legs is `$1 × min(q) − costs` either way.
- **Overlap is refused**: a fill key or `trial_id` present in both a legacy source and a C2 cash record → `CashSourceOverlap`, CRITICAL, the cash leg FAIL (`test_fill_in_both_sources_refused`).
- **Open cost held out**: an open fill's cost appears only as `capital_deployed` on its open day.
- **Pass** = `cumulative_reconciliation(...).settled_cumulative_passes_net` over days ≤ `settled_through` (the latest day all of whose fills have final labels or legacy coverage), with the window starting at the earliest known balance (legacy days included, so no cut-over seam exists).
- **Tolerance:** `per_day_tolerance(fills_opened_that_day)` (`:1390`, count from `_fills_opened_count_by_day`, `:1110`); cumulative tolerance = Σ over settled days.
- `BALANCE_UNKNOWN` or `external_flow_evidence_status != OK` → INCONCLUSIVE, never zero-coerced.

#### 3.6.4 Exit consistency and daily outcome

- Latch `exitPx/exitFee/exitAtNs` (`exit_wiring.py:227-236`) must equal the durable SELL; mismatch → `reconciled=False` on the exit label. The SELL record's `cumulative_cost` semantics are unverified (`portfolio_roi_report.py:445-468` docstring), so exit proceeds come from the latch and are cross-checked against the record and the balance delta (L-1 (vi)).
- **Daily outcome.** PASS only if all three legs PASS, coverage passes and the completeness identity holds with no `MISSING_LABEL` and no `UNATTRIBUTED` (§3.12). Any FAIL → FAIL. Any PENDING or INCONCLUSIVE leg (B8) → INCONCLUSIVE, which never satisfies §4.4 or ATTEST.

### 3.7 C4 producers (daily run)

#### 3.7.1 RECONCILIATION (daily, from `label_run`)
- Producer id `aut2_label_run`, pinned in `PRODUCER_SOURCE_SHA256` (pin update in the same commit).
- Per family in the §3.4.2 set: `subject_artefact_sha256` = bound artefact sha (Z1; pre-C5 the manifest's `density_artefact_sha256`); `detector = "aut2.reconciliation"`; `declared_action_class`, `prereg_ruling_sha256` only from the pinned `autonomy-policy/v1` block; `n` = slugs + days compared, `n_min` reason `deterministic_equality_check`.
- `metrics` (pre-registered names): `position_slugs_compared, venue_only_slugs, position_mismatches, position_mismatches_transient, not_compared_grace, settlement_mismatches, settlement_pending, cash_days_failed, cash_days_inconclusive, unknown_slugs, fills_never_position_compared, durable_fill_count, labelled_final, excluded_final, legacy_covered, open, pending, unattributed, missing_label, p_null_count (B13), bridge_match_rate (B5), ambiguous_open_at_prelaunch_7d, ambiguous_unknown_7d`.
- `valid_until_ns = produced_at_ns + 26 h`. Daily runs at 14:15Z and 05:00Z.
- Before the policy block exists: no C4 file; alerts, journals and `reconciled=False` still operate.

#### 3.7.2 HEALTH `aut2.label_lag` and `aut2.label_coverage`
- **Lag clock.** `lag_start_ns = settlement_deadline_ns(venue, city, climate_day)`; `label_lag = first_final_label_ns − lag_start_ns`, where the first final label is the first row that is admissible or carries a final excluded_reason. A `window_incomplete` row never stops the clock.
- **Horizon pinned.** `test_label_lag_horizon_pinned_under_max_verdict_validity` asserts `LABEL_LAG_MAX_H == 24 ≤ pins.MAX_VERDICT_VALIDITY_H (26)` and `WINDOW_INCOMPLETE_MAX_H == 48`.
- Any live fill with `now − lag_start_ns > 24 h` and no final label → `HEALTH FAIL aut2.label_lag` + CRITICAL (`test_no_cli_final_fails_label_lag_at_24h_from_venue_settlement`); fallback-pending fills carry `cause=awaiting_venue_fallback` (§3.5). Unattributed or missing-label fills → `HEALTH FAIL aut2.label_coverage`.

#### 3.7.3 Delivery and exit codes (B12)
- Every CRITICAL goes through `deliver_with_proof` (AUT-6), journaled to `evidence/alerts/delivery_<date>.jsonl`, via `delivery.deliver_or_fail`.
- **A `deliver_with_proof` failure (no `delivered=true` proof) exits non-zero** in `label_run` and both `recon_run` modes (exit 4, line `AUT2 DELIVERY_FAILED event=<name>`), after all labels, verdicts and the marker are durably written. The non-zero exit trips `OnFailure=breezy-study-failed@%n`, an independent second path. Tests: `test_label_run_delivery_failure_exits_nonzero`, `test_recon_run_delivery_failure_exits_nonzero`.
- Exit-code table (one table for all three units):

  | Condition | Exit | Marker | Notes |
  |---|---|---|---|
  | Run ok; outcome `LABELLED`/`PENDING`/`NO_INPUT`; every CRITICAL delivered | 0 | written | a lag or coverage FAIL is a detected data condition, alerted |
  | `FAILED_IDENTITY` (§3.12), CRITICAL delivered | 0 | written with `run_outcome=FAILED_IDENTITY` | consumers gate (§3.12) |
  | Unreadable or undecodable store, manifest or snapshot | 1 | none | never NO_INPUT |
  | Post-STOP lock contention (B11) | 3 | n/a | CRITICAL first |
  | `deliver_with_proof` failed for any CRITICAL (B12) | 4 | written if the run itself succeeded | `OnFailure=` backup path |

### 3.8 Canary store (Z14) and drill

- **Path** `derived/canary/<venue>/` (ARCH §5.3). Writer: `label_run --canary`, only on a UTC day with zero real attributed fills. C1-shaped synthetic records, `source=canary`.
- **Canary Scorer input.** The same `ForecastQuantileLadderScorer.label(...)` reads `read_canary_fills()` and a synthetic canary venue snapshot; output to `derived/labels_canary/`. Never enters `derived/labels/`, any RECONCILIATION input, any `n`, `portfolio-roi`, `entry_guard`, or the completeness identity.
- **Canary-day verdict.** A canary day qualifies iff (i) every canary fill of that day has a canary label with non-null `p_at_decision` and canary reconciliation PASS against the synthetic snapshot, and (ii) the day's real RECONCILIATION verdict is PASS. A canary never satisfies "every live fill labelled": the proof artefact records `real_fills=0, canary_fills=k, live_fill_check="vacuous"`. Canary fills never count toward the ≥ 5 real fills.
- **Tests (`tests/unit/test_aut2_canary_isolation.py`):** `::test_reconciliation_never_reads_canary_store`; `::test_entry_guard_never_reads_canary_store`; `::test_canary_labels_are_never_admissible`; `::test_canary_rows_excluded_from_verdict_n_and_completeness`; positive controls `::test_canary_ast_scanner_flags_planted_reader` and `::test_runtime_canary_guard_trips_on_planted_open`.
- **Drill.** `drill=true` (Z2 fold) → `excluded_reason=drill`, inadmissible; drill fills are real venue fills, so they are position- and cash-reconciled and in the completeness identity. Drill rows are written so AUT-6 detectors and the AUT-5 drawdown limit include them (W12). Tests: `test_drill_fill_labelled_reconciled_but_inadmissible`, `test_drill_fill_after_resume_still_drill`.

### 3.9 Z19: AMBIGUOUS intent open at 16:45Z

- **Direct observation.** The post-STOP run (§3.11) first passes the live-node guard (B10), then reads `exec/polymarket_us/intent/current` read-only, as `probe_open_intent` does. Between STOP (16:40Z) and LAUNCH (16:50Z) no node runs, so the state at 16:41Z equals the state at 16:45Z. It emits `ambiguous_open_at_prelaunch(d) ∈ {true, false}`.
- **`unknown`** when the post-STOP run did not complete, or the live-node guard found a live node (B10), or the STOP-completion signal was absent. A historical backfill uses `reconstruct_ambiguous_open_at()` over `intent/history/*` and reports `unknown` whenever `created_ns` preservation is unproven.
- Output: 7-day counts in RECONCILIATION metrics and the journal line `Z19 ambiguous_open_at_1645Z days=<k>/<n> unknown=<u>`.
- Until AUT-5a's supervisor journaling exists, `unknown` is a metric only (`test_z19_unknown_is_metric_not_alert`). A live node at 16:41Z is a separate CRITICAL (B10, §3.11), not a Z19 alert.

### 3.10 Consumers rewired; no expected failures

| Unit | Today | After AUT-2 |
|---|---|---|
| `breezy-score-live-trials` (14:15Z) | FQ: S7 `exit 0`, no marker | WP1: S7 writes `score_live_trials_noinput_$STAMP`. WP6: moves to 13:55Z; frozen CRH stores only; disabled once every CRH family is RETIRED (reviewed unit change). |
| `breezy-portfolio-roi` (17:40Z) | exit 1 daily (F2) | **WP1 (B7):** accepts `ok` or `noinput`. On `noinput`, the report counts durable fills that no source covers (the legacy `UNRECONCILED` bucket of `bucket_ledger_fills`, `:573-597`, which is where FQ fills land today). If that count is > 0, the report sets `roi_status=GATED_UNLABELLED_FQ`, prints `PORTFOLIO_ROI GATED_UNLABELLED_FQ unlabelled=<n>`, publishes no ROI figure, and exits 0. Only with count 0 is the status `OK`. No silent exit 0 over unlabelled fills. **WP6:** gates on `label_outcomes_ok_<date>.json`: `run_outcome=FAILED_IDENTITY` or `pending + unattributed + missing_label > 0` → `roi_status=GATED_UNSETTLED_CAPITAL` or `GATED_IDENTITY`, exit 0; P&L = C2 ∪ legacy (overlap refused); net pass flag. |
| `breezy-family-tally@pm_us_crh_{v2,v4}` | SKIPPED | Unchanged semantics; never non-zero as expected behaviour (WP6 test). |
| `breezy-position-monitor-report` | Unscoped | WP1: family-scoped; `NO_MONITOR_FOR_KIND forecast_quantile_ladder`. |
| `breezy-replay-daily` | FQ SKIPPED | Unchanged (AUT-4). |
| New `breezy-label-outcomes` | n/a | `OnCalendar=*-*-* 14:15:00 UTC` and `*-*-* 05:00:00 UTC`; `flock -w 600` on `breezy-studies.lock`, `breezy-studies.slice`; `MemoryMax=1G`; `RuntimeMaxSec=1200` (ends ≤ 14:45Z < 16:30Z); `OnFailure=breezy-study-failed@%n`; `EnvironmentFile=-%h/.config/breezy/alerts.env`; stall line every 60 s. |
| New `breezy-aut2-reconciliation` (W1) | n/a | `OnCalendar=*-*-* *:05,35:00 UTC`; own lock `~/.local/share/breezy/locks/aut2-reconciliation.lock` (`flock -w 30`), never the studies flock; `MemoryMax=512M`; `RuntimeMaxSec=240`; `OnFailure=`; alerts env; venue credentials per the capital-flow pull unit. `ExecStart` 1 = positions pull, `ExecStart` 2 = `recon_run --mode intraday`. The 16:35Z fire ends by 16:35:00 + 30 s + 240 s = 16:39:30Z, before the post-STOP slot (`test_intraday_1635_fire_releases_lock_before_post_stop`). Intraday lock contention: exit 0 with `AUT2_RECON SKIPPED reason=lock` and a WARN (the next fire is 30 min later, inside the 8 h validity). |
| New `breezy-autonomy-reconcile-poststop` (W8; ARCH §4.4 name) | n/a | `OnCalendar=*-*-* 16:41:00 UTC`; same lock with `flock -w 20`; `RuntimeMaxSec=100` (16:41:00 + 20 s + 100 s ≤ 16:43:00Z, ≤ `POST_STOP_RECONCILE_RUNTIME_S` 120); `MemoryMax=512M`; same wrapper with `--mode post_stop`. **Lock contention here is CRITICAL** (B11, §3.11). |

**Slot rationale.** PM.us settles at 08:00 ET (12:00Z EDT, 13:00Z EST from 11-02); western CLI finals arrive ~09:30–10:30Z; 14:15Z is the primary label run, 05:00Z the catch-up. ARCH §5.2 lets AUT-n plans fix the rows; the 30-min intraday cadence meets ARCH §5.2's "intraday HEALTH and RECONCILIATION verdicts at least hourly".

### 3.11 Intraday and post-STOP producers (W1, W8)

- **Producer id** `aut2_recon_run`, pinned in `PRODUCER_SOURCE_SHA256` with `aut2_label_run`.
- **Intraday mode (W1), every 30 min.** (1) A complete positions snapshot. (2) The position leg over ledger ∪ page with the fence and grace (§3.6.1). (3) Carry forward the newest daily RECONCILIATION: intraday PASS only if the position leg passes and the newest daily verdict is PASS and younger than 26 h; a daily FAIL → FAIL; daily INCONCLUSIVE, absent or expired → INCONCLUSIVE. The cited daily sha is an `inputs` entry (`path_role=daily_reconciliation_verdict`). (4) HEALTH `aut2.label_lag` and `aut2.label_coverage` recomputed read-only. `valid_until_ns = produced_at_ns + 8 h`.
- **ATTEST invariant (W1), AUT-2's row.** `ATTEST_PERIOD_MAX_H (6) + INTRADAY_PERIOD_MIN (0.5 h) + RuntimeMaxSec (≤ 0.07 h) ≤ RECON_INTRADAY_VALIDITY_H (8)`; `test_intraday_recon_cadence_fits_attest_invariant` over AUT-2's own schedule; AUT-5 owns the joint test.
- **Post-STOP mode (W8), in this order:**
  1. **Lock.** `flock -w 20` on the reconciliation lock. **Contention (B11)** means the intraday run overran its bound or something else holds the lock. It is not expected behaviour, and it makes the day's pre-launch pass SWAP_CANCEL. Response: CRITICAL `aut2.post_stop_lock_contention` via `deliver_with_proof`, line `AUT2_RECON POST_STOP_SKIPPED reason=lock`, exit 3. The wrapper emits the CRITICAL itself, before exiting, through `python -m breezy.analysis.labeling.recon_run --emit-lock-contention`, which takes no lock.
  2. **STOP signal (ARCH §4.4).** Proceed only after AUT-5a's journaled STOP completion for day D (signal name supplied by AUT-5a, consumed through C4/AUT-5 interface). Absent → INCONCLUSIVE, Z19 `unknown`, WARN (the incumbent launches unchanged).
  3. **Live-node guard (B10).** `pid = find_pid_by_argv(NODE_ARGV_ANCHOR)`, then `assert_no_live_node_before_intent_probe(pid)` (both imported from `breezy.runtime`, §2). On `PreLaunchProbeInvariantError`: no exec-store or intent read; verdict INCONCLUSIVE; Z19 `unknown`; CRITICAL `aut2.post_stop_live_node` (a node alive after STOP is itself an anomaly); exit 0 after delivery. The guard runs again immediately before the intent read (TOCTOU narrowing, same order as `probe_open_intent`).
  4. **Snapshot source (ARCH §4.4 "AUT-2 names it").** A fresh `venue_positions/v1` pull in this unit's `ExecStart` 1, accepted only if `snapshot_ns ≥ stop_completed_ns + POSITION_SETTLE_GRACE_S` and `snapshot_ns ≥` the last durable fill's `ts_event` + `POSITION_SETTLE_GRACE_S`. So every slug is compared (no `NOT_COMPARED_GRACE` is possible post-STOP). If the pull lands earlier, the run re-pulls once after the gap; if it is still early, or the pull fails, the verdict is INCONCLUSIVE. Pinned by `test_post_stop_snapshot_after_stop_plus_grace_compares_every_slug`.
  5. Position leg, carry-forward and HEALTH as in intraday mode; Z19 observation (§3.9).
  6. **§4.4 horizon supplied to AUT-5:** the pre-launch pass accepts a RECONCILIATION only if `produced_at_ns ≥ STOP_ns(D)`, produced by `aut2_recon_run --mode post_stop`, outcome PASS. Anything else → SWAP_CANCEL; the incumbent launches unchanged, so a dead producer cannot deadlock launch.
- Before the policy block: no C4 file; snapshot, journal lines and alerts still run.

### 3.12 Completeness identity, marker and NO_INPUT (B6)

- **Partition.** `completeness.coverage_partition` places every durable fill read by `fill_source` (count `n_keys`) in exactly one bucket:
  - `C2_FINAL`: a C2 row, admissible or with a final excluded_reason;
  - `C2_NONFINAL`: only non-final rows; `open` if `now < settlement_deadline_ns`, else `pending`;
  - `LEGACY_COVERED`: a legacy CRH fill in the `SCORED` or `RESIDUAL` bucket of `bucket_ledger_fills`, or listed by `_fee_unverified_fills_deduped`;
  - `UNATTRIBUTED`: no rule yields exactly one family (includes the legacy `UNRECONCILED` bucket);
  - **`MISSING_LABEL` (B6):** attributed to a family, not legacy-covered, and with **no** C2 row after this run's write. This is where the delete-one-label control lands: a fill whose row vanished is attributed but unlabelled. Because every attributed fill receives at least a `window_incomplete` row on the run after it appears, a non-zero count is always a defect (a lost write, a deleted file, a dedupe bug), never a timing state.
- **Identity asserted every run and in the proof artefact:** `C2_FINAL + C2_NONFINAL + LEGACY_COVERED + UNATTRIBUTED + MISSING_LABEL == durable_fill_count`, with **`UNATTRIBUTED == 0`, `MISSING_LABEL == 0`** and `n_undecodable == 0`. Any breach is an **identity breach**: `RECONCILIATION FAIL`, CRITICAL, and `run_outcome = FAILED_IDENTITY`.
- **RED tests (`tests/unit/test_aut2_completeness.py`):** `::test_labelled_plus_excluded_equals_durable_count`; positive control `::test_deleting_one_label_fails_identity` (remove one row through the real writer's dedupe path → that fill lands in `MISSING_LABEL`, the identity reports a breach, `run_outcome=FAILED_IDENTITY`); `::test_missing_label_bucket_counts_as_failure`; `::test_legacy_crh_fills_counted_in_denominator`; `::test_unattributed_fill_fails_identity`; `::test_c1_fold_disagreement_sets_failed_identity`.
- **Marker.** `derived/label_outcomes_ok_<date>.json` = `{schema: "label_outcomes_marker/v1", run_outcome ∈ {LABELLED, PENDING, NO_INPUT, FAILED_IDENTITY}, durable_fill_count, labelled_final, excluded_final, legacy_covered, open, pending, unattributed, missing_label, p_null_count}`; written last, after labels and verdicts, whenever the run read every store successfully (never on exit 1).
- **NO_INPUT** only when the run wrote zero rows and `pending == unattributed == missing_label == 0`. Zero rows with `pending > 0` is `PENDING` (line `LABEL_OUTCOMES PENDING pending=<n>`). `FAILED_IDENTITY` overrides every other outcome.
- **Consumer rule (one rule for portfolio-roi, AUT-3 and AUT-4, §5):** GATED iff `run_outcome == FAILED_IDENTITY` **or** `pending + unattributed + missing_label > 0`, or the marker is absent or older than 26 h. Pinned by `test_consumer_gate_rule_is_shared` (the single predicate `labels_consumable(marker)` in `label_store.py`, imported by portfolio-roi).
- **Unreadable store.** Any failure to open or decode the exec store, the label store, a manifest or a snapshot → CRITICAL, exit 1, no marker. RED: `test_unreadable_exec_store_exits_nonzero_without_marker`, `test_undecodable_fill_is_store_corruption_not_skip`, `test_unreadable_label_store_exits_nonzero`.

---

## 4. Work packages

Gate for every WP, from the tree root, exact interpreter, never `uv`/`pip` (L-51):
- `scripts/ci/run_tests_no_egress.sh` (full gate after **every** merge, L-43; under a unit `-p LimitNOFILE=524288`).
- `cd <tree> && .venv/bin/lint-imports` must print `N kept, 0 broken`.
- `.venv/bin/mypy src/breezy/analysis/labeling src/breezy/persistence/autonomy scripts/venue/polymarket_us_positions_pull.py`: 0 errors, no new `# type: ignore`.
- In a worktree, `PYTHONPATH=<worktree>/src`.
RED→GREEN output is kept per WP. Every injectable seam has a production-default test (L-55); every store-reading gate test writes fixtures through the real writer (L-42).

### AUT-2.WP1: root cause; monitor scoping; portfolio-roi expected failure removed (no Wave 0 dependency; start now)
- **Scope.** Evidence note `docs/evidence/AUT-2_rc_monitor_pnl_2026-10-03.md` (§3.1; H3 verified from `PRIVATE_portfolio_roi_2026-09-30.json`, classification only; the summary-only row mechanism and the verified MIA NO reason). Family filter, `NO_MONITOR_FOR_KIND`, `noinput` marker, **`GATED_UNLABELLED_FQ` (B7)**.
- **Files.** `scripts/analysis/position_monitor_nightly_report.py`; `deploy/systemd/score-live-trials-run.sh`; `deploy/systemd/portfolio-roi-run.sh`; `scripts/analysis/portfolio_roi_report.py` (`roi_status` field and the uncovered-fill count only).
- **RED first:** `tests/unit/test_position_monitor_nightly_report.py::test_bound_report_excludes_other_family_summaries`; `::test_bound_report_keeps_own_family_rows`; `::test_fq_kind_reports_no_monitor_for_kind`; `::test_unbound_report_unchanged_golden`; `::test_scored_trial_without_summary_is_not_a_row`; `tests/unit/test_score_live_trials_deploy.py::test_fq_champion_writes_noinput_marker_and_exits_zero`; `tests/unit/test_portfolio_roi_deploy.py::test_noinput_marker_admits_run`; `::test_absent_markers_still_refuse`; **`tests/unit/test_portfolio_roi_report.py::test_noinput_with_unlabelled_fills_reports_gated_unlabelled_fq` (B7: fixture ledger with one FQ fill in `UNRECONCILED`, a noinput marker → `roi_status=GATED_UNLABELLED_FQ`, no ROI figure, exit 0, the line printed); `::test_noinput_with_zero_uncovered_fills_reports_ok`; `::test_gated_unlabelled_fq_publishes_no_roi_figure`.**
- **GREEN.** 10-04 FQ report `positions: 0` + `NO_MONITOR_FOR_KIND`; v4 report still −0.37; 10-04 17:40Z `portfolio-roi` exits 0 with `roi_status=GATED_UNLABELLED_FQ unlabelled=11` (or more), never `OK`, until WP6.
- **Activation.** Immediate; scripts are read at each fire. Verify in the journal after the first fire.

### AUT-2.WP2: C2 store, fill source, attribution, completeness (Wave 1; after ARCH-0 and the residual C2 widening)
- **Files.** `persistence/autonomy/{label_store,net_position}.py`; `analysis/labeling/{constants,fill_source,attribution,instrument_facts,completeness}.py`; `scripts/analysis/score_live_trials.py` (import only).
- **RED first:** `tests/unit/test_aut2_label_store.py::test_schema_is_exact_label_v1`; `::test_dedupe_keeps_max_label_seq`; `::test_unknown_schema_version_refused`; `::test_atomic_write_no_partial_file`; `::test_money_columns_are_string_decimal`; `::test_label_store_refuses_without_widened_enum`; `::test_unmapped_scorer_reason_refused` (B3); `::test_consumer_gate_rule_is_shared` (B6); `::test_labels_consumable_false_on_failed_identity_or_missing_label` (B6); `tests/unit/test_aut2_fill_source.py::test_reads_every_fill_through_ro_uri`; `::test_undecodable_fill_is_store_corruption_not_skip`; `::test_fill_source_reads_wal_store_after_writer_exit`; `::test_real_default_reader_against_tmp_store`; `tests/unit/test_aut2_attribution.py::test_fq_fill_attributed_via_kind_latch_not_manifest_prefix`; `::test_latch_without_fill_is_not_a_label`; `::test_two_candidate_families_unattributed`; `::test_c1_and_fold_disagreement_unattributed`; `::test_voided_pair_fill_attributed_to_child_with_voided_pair`; `::test_attribution_uses_status_at_ts_event_not_now`; `::test_retired_family_labelled_until_last_fill`; `::test_unattributed_writes_durable_journal_row`; `::test_trial_id_uses_manifest_prefix`; `tests/unit/test_aut2_net_position.py::test_no_fill_offsets_yes_holding_to_netted_venue_qty`; `::test_each_leg_terminal_state`; `::test_sell_nets_against_long`; `::test_average_cost_basis_matches_exec_client_rule` (B4: BUY 4@0.50, SELL 1@0.60 → lifetime realized 1.60 at settlement 1.00, the `client.py:211-216` worked example); the six `test_aut2_completeness.py` tests (§3.12).
- **GREEN.** Dry run over the live store: 11 FQ fills attributed to `pm_us_crh_fq_v1`, 9 CRH fills `LEGACY_COVERED`, identity holds with `UNATTRIBUTED == MISSING_LABEL == 0`. Any legacy fill in `UNATTRIBUTED` is a finding resolved before WP6 activation, never waived.
- **Activation.** Library; lands live through WP6.

### AUT-2.WP3: FQ Scorer, entry labels, decision link, settlement sources, backfill
- **Files.** `analysis/labeling/{fq_scorer,decision_link,probability,settlement_source}.py`; `OFFLINE_PLUGINS` entry.
- **RED first:** `tests/unit/test_aut2_fq_scorer.py::test_yes_win_and_yes_loss_pnl_net_of_reconciled_fee`; `::test_no_leg_win_and_no_leg_loss_pnl`; `::test_realized_pnl_equals_score_trial_pnl_times_qty`; `::test_fee_unreconciled_excluded_and_alerted`; `::test_preliminary_cli_never_settles`; `::test_correction_relabels_with_next_label_seq`; `::test_window_incomplete_until_all_fills_settle`; `::test_window_incomplete_older_than_48h_fails_label_lag`; `::test_negative_slippage_beyond_tick_persists_slippage_defect`; **`::test_fallback_trigger_is_score_trial_basis` (B3: 6 d 23 h with a venue reading → pending; 7 d without a venue reading → pending; 7 d with a venue reading → `venue_fallback_settlement`; the test drives `score_trial` itself and asserts AUT-2 computes no time arithmetic); `::test_venue_settled_without_nws_maps_to_venue_fallback_settlement`; `::test_fallback_pending_window_raises_label_lag_by_design` (B3: at +24 h a pending-fallback fill is `HEALTH FAIL aut2.label_lag`, `cause=awaiting_venue_fallback`, CRITICAL)**; `::test_canary_and_drill_rows_never_admissible`; `tests/unit/test_aut2_probability.py::test_yes_take_p_is_p_hat`; `::test_no_take_p_is_one_minus_p_hat_bridge_mode`; `::test_no_take_p_is_one_minus_p_hat_c1_mode`; `::test_take_side_disagreeing_with_fill_leg_unmatched`; `tests/unit/test_aut2_decision_link.py::test_bridge_joins_on_client_order_id_not_adjacency`; `::test_bridge_window_bounds_enforced`; `::test_two_takes_in_window_unmatched`; `::test_take_after_init_is_not_linked`; `::test_unmatched_fill_null_p_with_reason`; `::test_unmatched_fill_increments_p_null_count` (B13); `::test_bridge_match_rate_reported` (B5); `::test_c1_record_overrides_log_line`; `::test_real_default_log_reader_on_tmp_file`; `tests/unit/test_aut2_settlement_source.py::test_kalshi_settlement_source_refuses_until_twc_reader`; `::test_polymarket_uses_nws_cli_final_latest_revision`.
- **GREEN.** Backfill dry run labels the 5 settled 10-02 FQ fills and the 6 10-03 fills after their finals; P&L equals the per-fill `score_trial` sum. The measured `bridge_match_rate` over the 11 fills is recorded in the RED→GREEN artefact (B5).
- **Activation.** Through WP6.

### AUT-2.WP4: exit labels (F6; average cost, B4)
- **Semantics (fee-inclusive weighted-average cost, the exec client's rule).** Within `(family_id, instrument_id)`, open lots before the exit have `Q = Σ q_i` and `C = Σ (cumulative_cost_i + fee_i)` over BUY records with `ts_event < exit.ts_event`, less the cost basis already released by prior exits. `avg = C / Q`. An exit of `q_x`: `cost_basis(q_x) = avg · q_x`; `realized_pnl_exit = proceeds − exit_fee − cost_basis(q_x)`; `counterfactual_hold_pnl = payoff(settled_outcome)·q_x − cost_basis(q_x)`. The remaining `Q − q_x` keep basis `avg·(Q − q_x)`, apportioned to the remaining entry labels pro rata by quantity. This is the same signed-sum `Σcost/Σqty` as `_entry_price_from_records` (`client.py:4495-4544`), extended fee-inclusively. **Identity:** Σ realized over every label of an instrument = cash moved on it = the exec client's lifetime realized P&L. FIFO is not used: no Breezy component uses it, and it would disagree per label with the exec client's basis.
- **RED first:** `tests/unit/test_aut2_exit_labels.py::test_yes_exit_realized_and_counterfactual`; `::test_no_leg_exit_signs`; `::test_partial_no_leg_exit_pro_rata_fee_inclusive` (`q_e=3`, `q_x=1`); `::test_counterfactual_includes_entry_fee`; **`::test_two_entries_one_partial_exit_average_cost` (B4: BUY 1@0.30 fee 0.02, BUY 1@0.40 fee 0.02, SELL 1@0.55 fee 0.02 → exit basis 0.37, realized 0.16; remainder basis 0.37 split across the two entry labels at 0.185 each; lifetime Σ equals the cash identity in both the win and lose cases); `::test_exit_matching_uses_shared_average_cost_basis` (AST: `exit_labels.py` imports `average_cost_basis` from `persistence.autonomy.net_position` and defines no matching of its own)**; `::test_slug_pnl_identity_entry_plus_exit`; `::test_record_exit_latch_mismatch_unreconciles`; `::test_exit_without_entry_unattributed`.
- **GREEN.** Fixture identities hold for both legs. Live exits occur only if an exit-capable family is CHAMPION (G17).
- **Activation.** Through WP6.

### AUT-2.WP5: reconciliation core, positions pull, verdict builders, Z19
- **Files.** `scripts/venue/polymarket_us_positions_pull.py`; `analysis/labeling/{reconcile,verdicts,prelaunch_intents,delivery}.py`. `portfolio_roi_report.py` is **not** edited here: C2 cash enters through `reconcile_daily`'s existing `residual_settlements` parameter (§3.6.3).
- **L-1 steps before RED:** (i) the archived `PRIVATE_v1_portfolio_positions_open_positions_20260916.positions.json` holds one negative `netPosition` among four rows; map it to its ledger NO fill to confirm "NO = negative on the YES slug"; if it does not map, the first live pull is the positive control and the leg rule waits. (ii) `submit_intent.py` retire path and `created_ns` (backfill only). (iii) `find_execution_egress_modules` does not flag a GET-only module. (iv) `PositionResolution` carries the fallback payout; if not, the fallback cash cross-check is INCONCLUSIVE (never FAIL) and the label stays final from `score_trial`. (v) **Closed:** `_cash_between` books no SELL proceeds (`portfolio_roi_report.py:1043-1088`, `:445-468`); `cash_records` supplies them. (vi) SELL `cumulative_cost` semantics against the latch `exitPx`, at the first fixture-replayed or live exit. (vii) **(B2)** whether the activity feed exposes a netting event when YES and NO of one slug are both held (event type, timestamp). If not, §3.6.3's INCONCLUSIVE path applies, and the plan records "netting event unobservable".
- **RED first:** `tests/unit/test_aut2_positions_pull.py::test_not_an_execution_egress_module`; `::test_get_only_reuses_assert_get_only`; `::test_follows_cursor_to_eof_else_incomplete`; `::test_snapshot_has_no_account_or_order_ids`; `tests/unit/test_aut2_reconcile.py::test_position_leg_exact_equality_both_legs`; `::test_compared_set_is_ledger_union_page`; `::test_venue_slug_without_ledger_fill_fails`; `::test_open_ledger_slug_missing_from_page_compares_as_zero`; `::test_settled_away_slug_not_compared`; `::test_incomplete_snapshot_inconclusive`; `::test_open_intent_at_snapshot_is_unknown_not_pass`; `::test_fills_after_snapshot_fenced_out`; **`::test_position_settle_grace_pinned` (B1: `POSITION_SETTLE_GRACE_S == 60`); `::test_fill_inside_grace_not_compared` (B1: fill at `snapshot_ns − 30 s`; venue already shows it → `NOT_COMPARED_GRACE`, not MISMATCH; venue does not show it → also `NOT_COMPARED_GRACE`); `::test_transient_mismatch_clears_on_next_snapshot` (B1: snapshot k MISMATCH → verdict FAIL, CRITICAL, label `reconciled=False` at seq n; snapshot k+1 MATCH → label rewritten at seq n+1 with `reconciled=True`, `position_compared_snapshot_ns = k+1`, the daily position leg PASS with `position_mismatches_transient=1`); `::test_standing_mismatch_fails_daily`; `::test_per_snapshot_compare_results_journaled`** (B1); `::test_every_fill_position_compared_before_settlement_else_fail`; `::test_stale_snapshot_inconclusive_and_alerts`; `::test_two_consecutive_inconclusive_days_alert_critical`; `::test_two_consecutive_balance_unknown_days_alert_critical`; `::test_settlement_disagreement_unreconciles_and_never_adopts_venue`; **`::test_pending_settlement_leg_is_inconclusive_not_pass` (B8); `::test_fallback_pending_settlement_leg_is_inconclusive` (B8)**; `::test_cash_leg_mixed_day_open_settled_exit` (perturb one `realized_pnl` by 0.02 → FAIL); `::test_cash_tolerance_counts_fills_opened_not_settled`; `::test_balance_unknown_day_inconclusive`; **`::test_yes_and_no_same_rung_cash_timing` (B2: YES 1 held, NO 1 bought on the same base slug; a netting activity at t_n → offset $1 dated at t_n, no second payout at settlement, cash PASS on both days; without the netting activity → the days from the NO fill through settlement INCONCLUSIVE, never FAIL); `::test_cash_leg_unions_legacy_proceeds_and_capital` (B9: a legacy CRH fill with a legacy `ScoredTrial` payout and an FQ fill with a C2 payout on overlapping days → PASS; drop the legacy payout → FAIL; drop the C2 payout → FAIL); `::test_fill_in_both_sources_refused` (B9); `::test_exit_proceeds_enter_cash_at_sell_ts_event`**; `tests/unit/test_aut2_verdicts.py::test_daily_reconciliation_valid_26h`; `::test_subject_sha_is_bound_artefact_sha`; `::test_action_class_read_from_policy_block_only`; `::test_no_verdict_without_policy_block_but_alert_fires`; `::test_no_cli_final_fails_label_lag_at_24h_from_venue_settlement`; `::test_lag_clock_stops_only_on_final_label`; `::test_label_lag_horizon_pinned_under_max_verdict_validity`; `::test_unattributed_fill_health_fail`; `::test_missing_label_health_fail` (B6); `::test_metrics_include_p_null_count_and_bridge_match_rate` (B13, B5); `::test_payload_hygiene_scan_covers_aut2_writers`; `tests/unit/test_aut2_delivery.py::test_deliver_or_fail_raises_without_delivered_proof` (B12); `tests/unit/test_aut2_prelaunch_intents.py::test_post_stop_observation_counts_ambiguous`; `::test_missing_post_stop_run_reports_unknown`; `::test_rewritten_created_ns_reports_unknown`; `::test_z19_unknown_is_metric_not_alert`.
- **GREEN.** Dry run: position PASS on open 10-03 slugs; settlement PASS on 10-02; cash PASS on the net identity over legacy ∪ C2 since the earliest known balance; completeness identity holds.
- **Activation.** Library; live through WP6 and WP9.

### AUT-2.WP6: label run unit and consumer rewiring
- **Files.** `analysis/labeling/label_run.py`; `deploy/systemd/breezy-label-outcomes.{service,timer}`, `label-outcomes-run.sh`; `portfolio-roi-run.sh`, `portfolio_roi_report.py` (marker gate via `labels_consumable`, P&L union, net flag); `breezy-score-live-trials.timer` (13:55Z); `deploy/systemd/README.md`.
- **RED first:** `tests/unit/test_aut2_label_run.py::test_iterates_offline_plugins_not_family_list`; `::test_refusing_plugin_for_non_retired_family_fails_run_no_marker`; `::test_no_input_only_when_pending_unattributed_missing_zero` (B6); `::test_zero_rows_with_pending_is_pending_not_no_input`; **`::test_identity_breach_writes_failed_identity_marker` (B6)**; `::test_marker_carries_counts`; `::test_marker_written_last`; `::test_unreadable_exec_store_exits_nonzero_without_marker`; `::test_unreadable_label_store_exits_nonzero`; `::test_label_lag_fail_exits_zero_with_verdict_and_critical`; **`::test_label_run_delivery_failure_exits_nonzero` (B12)**; `::test_stdout_carries_label_outcomes_summary_line`; `::test_real_default_paths_on_tmp_home`; `tests/unit/test_label_outcomes_deploy.py::test_unit_has_memorymax_runtimemaxsec_onfailure_alerts_env`; `::test_runtime_bound_ends_before_1630Z`; `::test_two_oncalendar_slots`; `tests/unit/test_portfolio_roi_report.py::test_pnl_source_union_labels_and_legacy`; `::test_pass_flag_is_net`; `::test_pending_gt_zero_gates_roi`; **`::test_failed_identity_marker_gates_roi` (B6); `::test_unattributed_or_missing_label_gates_roi` (B6)**; `tests/unit/test_outcome_units_no_expected_failure.py::test_every_outcome_wrapper_exits_zero_on_no_input` (parametrised: score-live-trials, portfolio-roi, family-tally@v2/v4, position-monitor-report, label-outcomes, aut2-reconciliation, replay-daily); `::test_every_outcome_wrapper_exits_nonzero_on_genuine_failure`.
- **GREEN.** First 14:15Z run labels the 10-02 FQ fills, marker `run_outcome=LABELLED, pending=0, missing_label=0`; 17:40Z `portfolio-roi` `roi_status=OK`.
- **Activation.** Immediate on merge; the coordinator installs and enables the timer. No node or supervisor restart.

### AUT-2.WP7: C1 switch-over, registration gate, compose cross-plan test (Wave 2; after AUT-1 C1 live and AUT-5a compose refusal)
- **Scope.** Rule (a) and C1 p authoritative; bridge demoted to a cross-check (disagreement → CRITICAL + `reconciled=False`); optional `SettlementRecord` with `raw_sha256` equality. **The proof window cannot open before this WP is active (B5).**
- **RED first:** `tests/contract/test_aut2_scorer_registration.py` (three §3.3 tests) plus `::test_armed_family_with_refusing_scorer_is_refused_at_compose`; `tests/unit/test_aut2_decision_link.py::test_c1_and_log_p_disagree_unreconciles`; `::test_c1_decision_id_join_every_tagged_fill`; `::test_post_wp7_p_null_count_zero_when_c1_present` (B13); `tests/unit/test_aut2_fq_scorer.py::test_settlement_record_sha_must_match_cli_raw`.
- **GREEN.** 100% of post-switch fills carry C1 `decision_id`; `p_null_count == 0` on the first full post-switch day; the compose test is green against AUT-5a's merged code.
- **Activation.** Immediate (offline).

### AUT-2.WP8: canary store and canary path (Z14)
- **Files.** `persistence/autonomy/canary_store.py`; `label_run --canary`; proof-window canary-day rule.
- **RED first:** the six §3.8 tests; `::test_canary_written_only_on_zero_real_fill_day`; `::test_portfolio_roi_never_reads_canary`; `tests/unit/test_aut2_proof_window.py::test_canary_day_qualifies_only_with_real_recon_pass`; `::test_canary_never_satisfies_live_fill_check`; **`::test_proof_window_refuses_start_before_wp7` (B5); `::test_proof_day_fails_on_p_null_count_gt_zero` (B13); `::test_proof_artefact_records_bridge_match_rate` (B5)**.
- **GREEN.** A synthetic zero-fill day produces `labels_canary/` rows, no change to `labels/`, verdict `n` or completeness counts.
- **Activation.** Immediate.

### AUT-2.WP9: intraday and post-STOP reconciliation producers (W1, W8)
- **Files.** `analysis/labeling/recon_run.py`; `deploy/systemd/breezy-aut2-reconciliation.{service,timer}`, `breezy-autonomy-reconcile-poststop.{service,timer}`, `aut2-reconciliation-run.sh`; `PRODUCER_SOURCE_SHA256` entry.
- **RED first:** `tests/unit/test_aut2_recon_run.py::test_intraday_verdict_valid_8h`; `::test_intraday_pass_requires_daily_pass_younger_than_26h`; `::test_intraday_inherits_daily_fail`; `::test_intraday_inconclusive_without_daily`; `::test_intraday_emits_health_label_lag_and_coverage`; `::test_post_stop_verdict_produced_after_stop_and_tagged_mode`; `::test_post_stop_records_z19_observation`; `::test_post_stop_reads_exec_store_with_node_stopped`; **`::test_post_stop_live_node_is_inconclusive_and_z19_unknown` (B10: `find_pid_by_argv` seam returns a PID → no store read (the store fixture raises if opened), verdict INCONCLUSIVE, Z19 `unknown`, CRITICAL `aut2.post_stop_live_node`); `::test_post_stop_uses_runtime_guard_not_a_copy` (B10: AST, imports `assert_no_live_node_before_intent_probe` and `find_pid_by_argv` from `breezy.runtime`); `::test_post_stop_real_default_pid_probe_on_tmp` (L-55 production default); `::test_post_stop_without_stop_signal_inconclusive`; `::test_post_stop_snapshot_after_stop_plus_grace_compares_every_slug` (B1)**; `::test_intraday_lock_contention_skips_with_line_exit_zero`; **`::test_post_stop_lock_contention_raises_critical_and_exits_nonzero` (B11); `::test_recon_run_delivery_failure_exits_nonzero` (B12)**; `tests/unit/test_aut2_recon_deploy.py::test_intraday_cadence_fits_attest_invariant`; `::test_post_stop_slot_ends_before_1645Z` (16:41 + `flock -w` + `RuntimeMaxSec` ≤ 16:43:00Z and `RuntimeMaxSec ≤ pins.POST_STOP_RECONCILE_RUNTIME_S`); `::test_intraday_1635_fire_releases_lock_before_post_stop`; **`::test_post_stop_wrapper_emits_critical_on_flock_timeout` (B11: wrapper script parsed and executed against a held lock in tmp)**; `::test_recon_units_use_own_lock_not_studies_flock`; `::test_recon_units_memorymax_within_own_lock_budget`.
- **GREEN.** First day: 48 intraday verdicts (or journal lines pre-policy-block), one post-STOP verdict before 16:43Z with `live_node=false`, Z19 line.
- **Activation.** Immediate on merge; the coordinator installs both timers. No node or supervisor restart.

---

## 5. Association

**Consumed:**

| Contract | From | What AUT-2 uses | Fallback before it lands |
|---|---|---|---|
| C2 schema, C4 writer, C6 Protocols, `RefusingPlugin`, `OFFLINE_PLUGINS`, `pins.py` (`MAX_VERDICT_VALIDITY_H`, `POST_STOP_RECONCILE_RUNTIME_S`) | ARCH-0 | Types, registry, verdict writer, pins | WP1 needs none; WP2+ wait |
| **Residual C2 widening (§10 C-1)** | ARCH (next revision) | `slippage_defect`, `venue_fallback_settlement`; `p_source`, `p_null_reason`; `position_compared_snapshot_ns`, `position_compare_result` | **None: no label write until it lands** |
| C1 records | AUT-1 | Attribution (a), p, settlement sha; **proof-window start (B5)** | Bridge for backfill only; the proof window waits |
| C5 fold at `ts_event`, bound sha, voided intervals | AUT-5 | Attribution (b), voided pairs, verdict subject | Manifest intervals; manifest sha |
| Compose-time refusal; journaled STOP-completion signal | AUT-5a | WP7 cross-plan test; post-STOP step 2 | WP7 does not merge; post-STOP verdicts INCONCLUSIVE (SWAP_CANCEL, incumbent unchanged) |
| `autonomy-policy/v1` | AUT-5b | action class, ruling sha, horizons 26 h / 8 h, post-STOP acceptance rule | No verdict file; alerts and journals run |
| `deliver_with_proof` | AUT-6 | CRITICAL delivery; failure exits non-zero (B12) | Interim `emit_alert` + `OnFailure=`; not score-3 evidence |

**Provided:**

| Contract | To | Guarantee |
|---|---|---|
| C2 labels `derived/labels/<family_id>/` | AUT-3, AUT-4 | Written by 14:45Z; consumers call `labels_consumable(marker)` (GATED on `FAILED_IDENTITY` or `pending + unattributed + missing_label > 0`, B6); only `admissible=True` counts; `p_at_decision` = P(bought leg wins) |
| C4 `RECONCILIATION` daily (26 h) | AUT-5 (PROMOTE-time checks; ATTEST input) | INCONCLUSIVE (including any PENDING leg, B8) never passes |
| C4 `RECONCILIATION` + `HEALTH` intraday (8 h, every 30 min) | AUT-5 ATTEST (W1) | Cadence row satisfying the invariant |
| C4 `RECONCILIATION` post-STOP | AUT-5 pre-launch pass (W8) | Produced 16:41–16:43Z after STOP and a passed live-node guard; `produced_at_ns ≥ STOP_ns(D)` |
| C4 `HEALTH` `aut2.label_lag`, `aut2.label_coverage` | AUT-6, AUT-5 | Daily and intraday |
| Drill rows (`drill=true`) in C2 | AUT-6 detectors, AUT-5 drawdown (W12) | Present, never dropped |
| `net_signed_qty`, `average_cost_basis` | AUT-5 `entry_guard` | One netting rule, one cost rule |
| Z19 metric | AUT-5 policy review | Direct 16:41Z observation |

**Order and parallelism.** WP1 now. After Wave 0 + the residual C2 widening: WP2 → WP3 → {WP4, WP5, WP8} → {WP6, WP9}. WP7 after AUT-1 C1 and AUT-5a. File ownership disjoint from Wave 1 siblings: AUT-2 never edits `app/trade.py`, `settings.py`, `trade_supervisor*.py` (it imports two functions from them read-only).

---

## 6. Live-proof protocol

- **Artefact.** `evidence/aut2_live_proof/window_<start>_<end>.json`, written by `label_run --proof-window` from the stores. Per qualifying day: real attributed fill count; final-labelled count (must equal); completeness identity counts with `unattributed == missing_label == 0`; `p_null_count` (must be 0, B13); `bridge_match_rate` and C1/bridge disagreement count (must be 0) (B5); daily RECONCILIATION verdict id and PASS; post-STOP verdict id and PASS; intraday verdict count and any non-PASS ids; `position_mismatches_transient`; max label lag (≤ 24 h); `fills_never_position_compared == 0`; canary fields per §3.8. Window totals: real fills (≥ 5), NO-leg fills, exits; marker files and systemd invocation ids.
- **Window rule.** A day qualifies with ≥ 1 real fill, or as a canary day under §3.8. Zero-fill non-canary days extend. Canary and drill fills never count toward ≥ 5. **A day with `p_null_count > 0` fails and restarts the window (B13).** **Start (B5):** the first UTC day after WP1–WP9 are all active, **including WP7 (C1 live)**, and AUT-6 delivery is live. `label_run --proof-window` refuses to open a window whose start precedes WP7 activation (`test_proof_window_refuses_start_before_wp7`), so the bridge is never a proof-window p source.
- **NO leg and exit.** "If one occurs": listed, or `no_leg_fills=0`, `exit_fills=0` with capability shown (FQ has no exit, G17).
- **ETA.** ~5 FQ fills/day. Wave 0 + the C2 widening by ~10-08; WP2–WP6, WP8, WP9 by ~10-14; AUT-1 C1 live (Wave 1) and WP7 by ~10-18 (an AUT-1 dependency, not under AUT-2's control); window 10-19..10-25; last settlements 10-27 12:00Z, labelled 14:15Z → **earliest 2026-10-27; plan 2026-11-06**. DST 11-02 moves settlement to 13:00Z, still covered by 14:15Z. KILL 2027-01-25 is far beyond.
- **Evidence class.** "Machinery proven, edge unproven."

---

## 7. Score-3 verification checklist

| Criterion | Check |
|---|---|
| (a) unattended | `journalctl --user -u breezy-label-outcomes.service -u breezy-aut2-reconciliation.service -u breezy-autonomy-reconcile-poststop.service --since <window>`: only timer starts. Invocation ids in the artefact. `git log --since <window> -- src/breezy/analysis/labeling deploy/systemd/*label* deploy/systemd/*aut2* deploy/systemd/*reconcile-poststop*` empty. |
| (b) family-agnostic | `scripts/ci/run_tests_no_egress.sh -k "aut2_scorer_registration or iterates_offline_plugins or family_plugin_exact_set"` passes (includes the compose test). `/usr/bin/grep -n "pm_us_" src/breezy/analysis/labeling/*.py` → 0 hits. |
| (c) fails closed | Tests `refusing_plugin_for_non_retired_family_fails_run_no_marker`, `unreadable_exec_store_exits_nonzero_without_marker`, `deleting_one_label_fails_identity`, `missing_label_bucket_counts_as_failure`, `identity_breach_writes_failed_identity_marker`, `venue_slug_without_ledger_fill_fails`, `every_fill_position_compared_before_settlement_else_fail`, `incomplete_snapshot_inconclusive`, `pending_settlement_leg_is_inconclusive_not_pass`, `post_stop_live_node_is_inconclusive_and_z19_unknown`, `post_stop_lock_contention_raises_critical_and_exits_nonzero`, `label_run_delivery_failure_exits_nonzero`, `noinput_with_unlabelled_fills_reports_gated_unlabelled_fq`, `every_outcome_wrapper_exits_nonzero_on_genuine_failure`, `absent_markers_still_refuse`. |
| (d) detected, alerted, delivered | `evidence/alerts/delivery_<date>.jsonl` holds `delivered=true` for an injected `aut2.label_lag` (WP5 drill: tmp HOME fill past the venue settlement instant with no CLI final, production entrypoint, real endpoint). |
| (e) RED→GREEN | Per-WP artefacts; gate EXIT=0 after each merge; `lint-imports` `kept, 0 broken`. |
| (f) live proof | `evidence/aut2_live_proof/window_*.json`: 7 qualifying days starting after WP7, ≥ 5 real fills, identity holds with `unattributed == missing_label == 0` daily, `p_null_count == 0` daily, every daily and post-STOP verdict PASS; ids resolve under `derived/verdicts/pm_us_crh_fq_v1/<date>/`. |
| Horizons | `test_label_lag_horizon_pinned_under_max_verdict_validity`, `test_intraday_cadence_fits_attest_invariant`, `test_post_stop_slot_ends_before_1645Z`, `test_position_settle_grace_pinned`, `test_fallback_pending_window_raises_label_lag_by_design`. |
| Root cause | `docs/evidence/AUT-2_rc_monitor_pnl_2026-10-03.md`; FQ monitor report `positions: 0`, `NO_MONITOR_FOR_KIND`. |
| No expected failures | `systemctl --user list-units --state=failed 'breezy-*'`: no outcome unit in the window; both `test_outcome_units_no_expected_failure` tests pass. |
| Z14 / Z19 | `test_aut2_canary_isolation` (with positive controls); journal line `Z19 ambiguous_open_at_1645Z days=` from each post-STOP run. |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| Positions pull races trading | Fence `ts_event ≤ snapshot_ns − 60 s`; slugs with a fill inside the grace are `NOT_COMPARED_GRACE`; OPEN/AMBIGUOUS intent → UNKNOWN; post-STOP snapshot is taken ≥ 60 s after STOP completion and the last fill (B1). |
| Grace too short for venue propagation | A too-short grace shows as transient mismatches that clear next snapshot; `position_mismatches_transient` is a daily metric and each one is CRITICAL, so a systematic propagation delay is visible within a day. The constant changes only by a reviewed commit that updates the pin test. |
| Transient-mismatch clearing hides a real break | Only the label is rewritten; the FAIL verdict and its CRITICAL stay on record, and a mismatch standing at the latest comparison fails the daily verdict. |
| YES/NO netting event unobservable (B2) | INCONCLUSIVE cash days (never FAIL, never PASS); two consecutive → CRITICAL; same-rung YES+NO holdings are rare (the scorer refuses the hedge, `current_rung_hold_v2.py:112-121`). |
| Legacy proceeds omitted or double-counted (B9) | Union through `reconcile_daily`'s existing parameters; overlap refused; drop-either-source tests fail. |
| Bridge mislinks a Take | `client_order_id` + `trade_id` join with bounded windows; exactly one Take; after B5 the bridge never feeds the proof window. |
| Proof ETA hostage to AUT-1 (B5) | Accepted: a proof window on a measured-but-imperfect bridge would be weaker evidence. The ETA states the dependency. |
| Pagination truncates the page | Cursor to `eof`; `complete=false` → INCONCLUSIVE. |
| Settled position leaves the page (L-52) | Settled-away slugs compared only on settlement and cash legs; the coverage rule guarantees a pre-settlement comparison. |
| Venue rate limit from 49 GETs/day + pages | Reuses the capture's `quota_key`; a 429 → INCONCLUSIVE for that slot; never retried in a loop. |
| Post-STOP producer late, dead, contended or facing a live node | SWAP_CANCEL; incumbent unaffected (§4.4); CRITICAL for contention (B11) and a live node (B10); `OnFailure=` for crashes. |
| Alert delivery fails silently | Exit 4 trips `OnFailure=` (B12); the delivery journal lacks `delivered=true`, which AUT-6's `alerts_undeliverable` reads. |
| Exec-store read with node stopped | Runtime guard reused (B10); `test_fill_source_reads_wal_store_after_writer_exit`; a read failure is exit 1. |
| C2 widening slips | Label writes blocked; WP1 still lands; the proof ETA moves. |
| Retired-family scorer conflict with C6 YAGNI | §10 C-6; until resolved, retiring the last FQ family with unlabelled fills fails the gate loudly (CRITICAL). |
| Memory (30 GiB host) | Label run precedent 137 MB, `MemoryMax=1G` studies flock; reconciliation units 512M own lock (never overlapping: same lock). No heavy job 01:00–04:30Z. |
| Shared venv | Briefs name `/home/jon/breezy/.venv/bin/python`; no `uv`, `pip`, `uv run` (L-51). |
| Concurrent agents | Disjoint file ownership; per-agent scratchpads; no `git stash`; worktrees fast-forwarded first. |
| Gross/net split hides a cash loss | Net flag needs flows `OK`; otherwise INCONCLUSIVE; two consecutive → CRITICAL. |
| Statistical capacity | Not an AUT-2 claim; ≥ 5 real fills in ~1–2 days. |
| KILL 2027-01-25 | After TERMINAL KILL: labels continue for remaining settlements, NO_INPUT runs exit 0, proof window pauses. ETA 10-27..11-06 is well before. |
| NWS outage / late final | Rows pending; HEALTH FAIL at 24 h with `cause=awaiting_venue_fallback` (B3); no nearby-station substitution. |
| Kalshi family admitted | TWC source refuses; gate fails until a reviewed TWC reader exists. |

---

## 9. Binding-constraint compliance

- **Nautilus immutability.** No Nautilus file touched; native `ClientOrderId`/`TradeId` joins and its event log lines are only read.
- **The two caps.** Never read, written or derived; `test_autonomy_never_reads_or_writes_operator_controls` covers `analysis/labeling/`.
- **`allow_short=False`.** Untouched; "short YES" is the venue's reporting convention, read only.
- **NO-SEND.** Label and recon analysis make no network call. The positions pull is GET-only through the existing capture and `assert_get_only`, pinned by `test_not_an_execution_egress_module`. `test_execution_egress_firewall_guard` is not edited.
- **Master enablement and permit.** Never read or written; offline units; no supervisor or node change. The post-STOP guard only reads a PID and refuses; it never signals a process.
- **PREREG via ruling.** No statistical semantics defined; horizons and action classes enter the verdicts only from the AUT-5 policy block.
- **Safety tests never weakened.** `absent_markers_still_refuse` kept; every settlement, contract and NO-SEND test unchanged; `trial_scorer.py` and `reconcile_daily` unchanged; new positive controls and fail-closed tests only add strength.

---

## 10. Contradictions with ARCH (for the next ARCH revision)

- **C-1 (residual C2 widening, L-12; hard prerequisite).** Rev 5 C2 (`ARCH_rev5.md:150-157`) adds `voided_pair` but still lacks: `excluded_reason` values `slippage_defect` and `venue_fallback_settlement` (B3: the mapped name of the scorer's `venue_settled_without_nws`); a reason column for null `p_at_decision` (`p_null_reason ∈ {pre_c1_log_unmatched}`) and `p_source ∈ {c1_decision_record, node_log_take_line}`; and **(B1)** `position_compared_snapshot_ns` (int64, nullable until first comparison) plus `position_compare_result ∈ {MATCH, MISMATCH}`. The state that `p_at_decision` is P(bought leg wins) also needs adding. r2's request for nullable `settled_outcome`/`realized_pnl` is **withdrawn**: under B3 the fallback row takes both from `score_trial`.
- **C-2 (slot).** ARCH §5.2's indicative 05:00Z label slot cannot label the prior day; 14:15Z primary, 05:00Z catch-up.
- **C-3 (producer scope).** ARCH §5 gives AUT-2 only C4 `RECONCILIATION`; C2's invariant and W1 require AUT-2 `HEALTH` (`aut2.label_lag`, `aut2.label_coverage`).
- **C-4 (Z19 source).** Resolved by the post-STOP direct observation.
- **C-5 (F4).** The FQ manifest's `trial_id_prefix` matches no stored key; scorers must not use it for discovery.
- **C-6 (C6 YAGNI versus retired-family labeling).** C6 swaps a kind with no non-RETIRED family to `RefusingPlugin`, which would leave live fills unlabelled after the last FQ family retires. Request: the `Scorer` member stays real while any family of the kind has an attributed fill without a final label.
- **C-7 (W8 wording).** Rev 5 §4.4 now separates the sender-change horizon (produced after STOP) from intraday RESUME (`ARCH_rev5.md:672-675`). **Resolved**; no request.
- **C-8 (new; label-lag clock under the fallback).** ARCH C2 says "within 24 h of its `SettlementRecord`"; with a 7-day venue fallback, an NWS outage makes `label_lag` FAIL for up to ~6 days. AUT-2 keeps the FAIL as the intended signal (B3) with `cause=awaiting_venue_fallback`. The next ARCH revision should state that a fallback-pending lag FAIL is expected-and-alerted, so that AUT-5 policy does not treat it as an INTEGRITY freeze.

---

## 11. Self-score (author's estimate; not evidence)

| Axis | Max | Score | Note |
|---|---:|---:|---|
| Fidelity | 20 | 19 | Rev 5 §10 obligations quoted and mapped, including the post-STOP STOP signal, snapshot source and runtime bound; ARCH unit name adopted; deviations C-1..C-8 declared. |
| Correctness | 20 | 18 | B3 trigger, B4 cost rule, B9 cash path and B10 guard each verified in code (`trial_scorer.py:247-255`, `client.py:4495-4544`, `portfolio_roi_report.py:1043-1088,1146`, `trade_supervisor_core.py:554`). B2 netting observability and the fallback payout field remain **INFERRED** behind L-1 (vii)/(iv), each with an INCONCLUSIVE fallback. |
| Specificity | 15 | 14 | Grace, exit codes, buckets, marker fields, consumer predicate, slots and test names explicit. |
| Acceptance | 20 | 18 | Every B-item has a named RED test and a checklist row; score 3 depends on the residual C2 widening, AUT-1 C1, AUT-5a and AUT-6, all named. |
| Autonomy-safety | 15 | 15 | Fails closed on identity, pending legs, live node, lock contention and delivery failure; no caps, permit or firewall surface. |
| Reuse | 10 | 10 | `score_trial`, `reconcile_daily` via existing parameters, `ResidualSettlement`, exec-client cost rule, runtime guard, positions capture, node log. |
| **Total** | **100** | **94** | r2 was reviewer-scored 90 with 0 CRITICAL/HIGH; r3 closes all 13 MEDIUM items. |

---

## §R3 Disposition (review `reviews/AUT-2-r2-merged.md`)

The r2 disposition of A1–A18 and W1/W8/W12/W14 is in `AUT-2-outcome-labeling_plan_r2.md` § "§R2 Disposition" (18/18 FIXED); r3 keeps all of those fixes.

| ID | Status | Where / evidence |
|---|---|---|
| B1 | FIXED | §3.6.1: fence `ts_event ≤ snapshot_ns − POSITION_SETTLE_GRACE_S`, pinned at 60 s (`constants.py`, `test_position_settle_grace_pinned`); fills inside the grace are `NOT_COMPARED_GRACE`; label `reconciled` recomputed from the latest journaled comparison and rewritten at `label_seq+1`; per-snapshot results journaled (§3.2) and `position_compared_snapshot_ns`/`position_compare_result` requested as a C2 widening (§10 C-1); post-STOP snapshot ≥ STOP + grace (§3.11 step 4). Tests `test_fill_inside_grace_not_compared`, `test_transient_mismatch_clears_on_next_snapshot`, `test_standing_mismatch_fails_daily`, `test_per_snapshot_compare_results_journaled` (WP5), `test_post_stop_snapshot_after_stop_plus_grace_compares_every_slug` (WP9). |
| B2 | FIXED | §3.6.3 item 3: when both legs of a base slug are held, the `min(q) × $1` offset is dated at the venue netting event, with no second settlement payout; an unobservable event → INCONCLUSIVE cash days, never FAIL; L-1 (vii) (WP5); `test_yes_and_no_same_rung_cash_timing`. |
| B3 | FIXED | §3.5: the trigger is exactly `_resolve_settlement_basis`'s branch (`trial_scorer.py:247-255`: no final ∧ `now ≥ scheduled_release + _SEVEN_DAYS_NS` ∧ venue reading); the literal mapping `venue_settled_without_nws → venue_fallback_settlement`; unmapped reasons refused; the 7-day pending period raises `aut2.label_lag` by design with `cause=awaiting_venue_fallback`. Tests `test_fallback_trigger_is_score_trial_basis`, `test_venue_settled_without_nws_maps_to_venue_fallback_settlement`, `test_fallback_pending_window_raises_label_lag_by_design` (WP3), `test_unmapped_scorer_reason_refused` (WP2); §10 C-8. |
| B4 | FIXED | §2 row and WP4: neither `net_signed_qty` (quantity-only) nor `reconcile_daily` (matching-free; SELLs excluded, `portfolio_roi_report.py:445-468`) defines a cost rule. The only Breezy cost rule is the exec client's weighted average (`client.py:4495-4544`, lifetime-P&L-conserving, `:208-220`), so labels use fee-inclusive average cost via one shared `average_cost_basis` in `net_position.py`. Tests `test_two_entries_one_partial_exit_average_cost`, `test_exit_matching_uses_shared_average_cost_basis` (WP4), `test_average_cost_basis_matches_exec_client_rule` (WP2). |
| B5 | FIXED | §6 window rule: the proof window starts only after WP7 (C1 live), enforced by `test_proof_window_refuses_start_before_wp7`; `bridge_match_rate` in the metrics (§3.7.1) and the proof artefact (§6), measured over the 11 live fills in the WP3 backfill (§3.4.4); ETA updated (earliest 10-27, plan 11-06). |
| B6 | FIXED | §3.12: `MISSING_LABEL` bucket counts as failure (the delete-one-label control lands there); `run_outcome=FAILED_IDENTITY`; one shared consumer predicate `labels_consumable` = GATED on `FAILED_IDENTITY` or `pending + unattributed + missing_label > 0` (§3.10, §5). Tests `test_missing_label_bucket_counts_as_failure`, `test_deleting_one_label_fails_identity`, `test_identity_breach_writes_failed_identity_marker`, `test_failed_identity_marker_gates_roi`, `test_consumer_gate_rule_is_shared`. |
| B7 | FIXED | §3.10 portfolio-roi row and WP1: `noinput` admits a run only with an explicit `roi_status=GATED_UNLABELLED_FQ` (and no ROI figure) whenever any durable fill is uncovered (legacy `UNRECONCILED` bucket); `OK` only at zero. Tests `test_noinput_with_unlabelled_fills_reports_gated_unlabelled_fq`, `test_noinput_with_zero_uncovered_fills_reports_ok`, `test_gated_unlabelled_fq_publishes_no_roi_figure`. |
| B8 | FIXED | §3.6.2 and §3.6.4: a PENDING settlement leg (no venue evidence yet, or fallback pending) makes the day INCONCLUSIVE, never PASS. Tests `test_pending_settlement_leg_is_inconclusive_not_pass`, `test_fallback_pending_settlement_leg_is_inconclusive` (WP5). |
| B9 | FIXED | §3.6.3: union option chosen. `fills` = all durable fills (legacy capital already counted, `:1096`), `scored_trials` = legacy stores, `residual_settlements` = legacy residuals ∪ C2 cash records (`ResidualSettlement`, `:1146`); overlap refused; window from the earliest known balance, so there is no cut-over seam. Tests `test_cash_leg_unions_legacy_proceeds_and_capital`, `test_fill_in_both_sources_refused`. |
| B10 | FIXED | §3.11 post-STOP step 3: `find_pid_by_argv(NODE_ARGV_ANCHOR)` + `assert_no_live_node_before_intent_probe` reused from `breezy.runtime` (`trade_supervisor.py:531`, `trade_supervisor_core.py:554`; layering permits it, `pyproject.toml:78-99`); a live node → INCONCLUSIVE, Z19 `unknown`, CRITICAL, no store read (§3.9). Tests `test_post_stop_live_node_is_inconclusive_and_z19_unknown`, `test_post_stop_uses_runtime_guard_not_a_copy`, `test_post_stop_real_default_pid_probe_on_tmp`. |
| B11 | FIXED | §3.11 post-STOP step 1 and §3.7.3: post-STOP lock contention → CRITICAL via `deliver_with_proof` emitted by the wrapper, exit 3; the 16:35Z intraday fire is bounded to release by 16:39:30Z. Tests `test_post_stop_lock_contention_raises_critical_and_exits_nonzero`, `test_post_stop_wrapper_emits_critical_on_flock_timeout`, `test_intraday_1635_fire_releases_lock_before_post_stop`. |
| B12 | FIXED | §3.7.3: `delivery.deliver_or_fail`; any `deliver_with_proof` failure exits 4 (non-zero) in `label_run` and both `recon_run` modes after durable writes, tripping `OnFailure=`. Tests `test_deliver_or_fail_raises_without_delivered_proof`, `test_label_run_delivery_failure_exits_nonzero`, `test_recon_run_delivery_failure_exits_nonzero`. |
| B13 | FIXED | §3.7.1 metric `p_null_count`, in the marker (§3.12) and proof artefact (§6); `p_null_count > 0` fails the proof day and restarts the window. Tests `test_unmatched_fill_increments_p_null_count` (WP3), `test_metrics_include_p_null_count_and_bridge_match_rate` (WP5), `test_proof_day_fails_on_p_null_count_gt_zero` (WP8), `test_post_wp7_p_null_count_zero_when_c1_present` (WP7). |

Counts: 13 of 13 B-items FIXED, 0 REJECTED.

# AUT-2: outcome labeling (scoring, P&L, reconciliation). Plan r2

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-2 |
| Title | Outcome labeling: family-agnostic scorer, C2 label store, net-position and cash reconciliation |
| Round | r2 (2026-10-03). Disposes A1–A18 of `reviews/AUT-2-r1-merged.md` (§R2) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 4**, scored snapshot sha256 `175310117eec39b22fc8229788a7d6182c6395438db23ec65ceb78b964dd508e`, plus the pending Rev 5 deltas W1–W16 (`reviews/ARCH-r4-merged.md`), treated as applied. W1 (intraday RECONCILIATION/HEALTH, 8 h validity) and W8 (post-STOP RECONCILIATION producer, §4.4 horizon) are owned here; W12 and W14 are consumed. |
| Repo state read | `4b8347a6` on `feat/data-capture-and-risk`; live artefacts under `~/.local/share/breezy/` as of 2026-10-03 ~04:15Z |
| Current score | 1 (README) |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: `persistence/autonomy/` schemas, C6 Protocols, `RefusingPlugin`, `pins.py`); **ARCH Rev 5 C2 widening (§10 C-1), a hard prerequisite for any label write (A7)**; AUT-1 (C1 `decision_id`, `DecisionRecord`, `OrderLink`, `SettlementRecord`); AUT-6 (`deliver_with_proof`); AUT-5a (compose-time refusal, `app/trade.py:853`; hard prerequisite for WP7's cross-plan test, A10); AUT-5b (policy block) |
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

**ARCH §10 AUT-2 obligations (Rev 4, verbatim):** "the −0.37/+0.37 root cause with artefact evidence before any scorer change; the per-leg reconciliation tolerance; the RECONCILIATION verdict horizon used by §4.4; exclusion of `canary` and `drill` rows; the canary store's `Scorer` input (Z14); the label-lag alert; the measured rate of AMBIGUOUS intents open at 16:45Z (Z19)."
**Rev 5 additions owned here:** W1 (intraday HEALTH and RECONCILIATION verdicts, 8 h validity, feeding a ≤ 6 h ATTEST cadence); W8 (post-STOP RECONCILIATION producer at 16:41–16:43Z, own lock, bounded runtime; §4.4 horizon = "produced after STOP that day"). W14 (voided-pair fills labelled `excluded_reason=voided_pair`) is consumed.

Section map: root cause §3.1 and WP1; per-leg tolerance §3.6; verdict horizons §3.7 (daily), §3.11 (intraday W1, post-STOP W8); canary and drill §3.8; canary Scorer input §3.8; label lag §3.7.2; Z19 §3.9; completeness §3.12.

---

## 2. L-1 null hypothesis and reuse

Nautilus has no settlement scorer, no label store and no venue-versus-ledger reconciliation for an offline process. `Position.realized_pnl` covers only in-node lifetime and excludes settlement payouts that arrive after the node stops, so it is not a label source.

| New component | Checked against | Verdict |
|---|---|---|
| C2 label store `persistence/autonomy/label_store.py` | `scored_trial_store.py:24-31,60-89`; `ScoredTrial` (`trial_scorer.py:131-155`) | **Reuse the conventions, not the schema** (G8: no `family_id`, leg, role, p, decision id). Parquet, atomic `os.replace`, `(id, max seq)` dedupe copied. |
| Settlement resolution | `score_trial`, `_resolve_settlement_basis` (`trial_scorer.py:167-265`); `read_climate_day_including_corrections` (`k1_cheap_open_settlement.py:976`); `default_registry().settlement_site` (`score_live_trials.py:778`) | **Reuse unchanged** (nws-cli-settlement: final-only, latest revision, LST climate day). |
| Venue settlement instant (label-lag clock, A2; "open" test, A6) | `default_registry().settlement_deadline(venue, city)` (`registry/sites.py:413`) and `settlement_deadline_ns(deadline, climate_day)` (`registry/settlement_clock.py:36`): 08:00 America/New_York on climate_day+1, with the conditional 11:00 ET delay stored, never computed (`registry/sites.toml:55-70`) | **Reuse.** No new clock arithmetic. |
| Rung facts from the slug | `_read_bucket_facts_by_instrument_id`, `_bucket_facts_from_instrument_id` (`score_live_trials.py:579,620`) | **Reuse** via a pure extraction into `analysis/labeling/instrument_facts.py`, re-imported by `score_live_trials.py` (byte-identical behaviour; L-46). |
| Leg netting | `leg_of_symbol` (`domain/instrument_leg.py:58`); `base_slug_of`, `leg_of` (`symbology.py:289-298`) | **Reuse.** `net_signed_qty` defined once in `persistence/autonomy/net_position.py`, shared with `entry_guard` (or imported from Wave 0 if it placed it there). |
| Durable fill reader | `DurableFillRecord.from_bytes` (`exec/client.py:1004-1066`); `FILL_KEY_PREFIX` (`:408-415`); G6 `mode=ro` URI (`trial_day_latch.py:354-379`); `read_ledger_fills_with_counts` (`portfolio_roi_report.py:299`) | **Reuse `from_bytes`, the G6 URI and the counted reader** (its counts feed the completeness denominator, §3.12). |
| Exec-store read with the node stopped (W8 16:41Z slot) | `probe_open_intent` (`trade_supervisor.py:402-420`) already reads the exec store **only when no node PID is live** (`assert_no_live_node_before_intent_probe`) at every LAUNCH | **Reuse the precedent.** r1's risk row ("`mode=ro` needs the writer alive") was wrong for the exec store: ARCH Y5 is about the registry's 0500 directory; the exec-store directory is user-writable, so SQLite can open the WAL file read-only after the writer exits. Pinned by `test_fill_source_reads_wal_store_after_writer_exit` (§4 WP2). |
| Legacy CRH fill coverage (A1) | `FillBucket`, `bucket_ledger_fills` (`portfolio_roi_report.py:536-597`: every ledger fill lands in exactly one bucket); `_fee_unverified_fills_deduped` (`:650`); `read_filled_trials_state_db` (`analysis/prereg_admission.py:234`, CRH latches) | **Reuse** for the legacy partition. Not reusable for FQ (F4/F5). |
| Cash reconciliation | `reconcile_daily` (`portfolio_roi_report.py:1618`; identity `unexplained(D) = Δbalance(D) − proceeds(D) + capital_deployed(D)`); `capital_deployed_by_day` (`:1096`); `_fills_opened_count_by_day` (`:1110`); `per_day_tolerance(fills_opened_that_day)` (`:1390`); `cumulative_reconciliation` → `settled_cumulative_passes_net` (`:1986-2040`); `persistence/external_capital_flows` | **Reuse.** C2 rows replace `ScoredTrial` as the proceeds source through a thin adapter; tolerance argument is **fills opened that day** (A8 fix; r1 passed settled count). |
| Venue position snapshot | `scripts/venue/polymarket_us_positions_value_capture.py` (`capture` `:191`, `redact_positions` `:148`, `run_capture` `:237`, pagination fields `eof`/`nextCursor`); `assert_get_only` (`polymarket_us_private_shape_probe.py:175`, allowlist imported from `signing.py`); capital-flow pull non-egress test (`test_polymarket_us_capital_flow_pull.py:378`) | **Extend, do not rebuild.** r1 proposed a new signing client; r2 wraps the existing GET-only capture (`analysis`-free script) in `scripts/venue/polymarket_us_positions_pull.py`, which adds only cursor-following, the `venue_positions/v1` reduction and the snapshot writer. SDK fields `netPosition`, `expired`, `marketMetadata` (`sdk_snapshot/.../types/portfolio.py:21-34`). |
| Venue settlement evidence | Tape `custom_venue_settlement_snapshot`; SDK `PositionResolution` activity (`types/portfolio.py:68-76`) read by the capital-flow pull's `account_activity.py` | **Reuse.** Fallback-settlement payout (A9) is read from the `PositionResolution` activity (INFERRED field use; WP5 L-1). |
| p at decision (pre-C1) | `SHADOW_DECISION` log line (`fq/strategy.py:577-581`; fields from `decision_log_fields`, `fq/decision.py:178-213`), plus Nautilus `OrderInitialized`/`OrderFilled` event lines carrying `client_order_id` and `trade_id` (verified: `breezy-trade-20261002T205521Z.log` lines 8359, 8361, 8393) | **Reuse the bot's own output.** p is never recomputed (L-2). |
| C4 writer, payload hygiene | Wave 0 C4 writer; `AlertPayload` hygiene (`registry/health_model.py:217-235`) | **Consume.** |
| Units | `score-live-trials-run.sh`, `portfolio-roi-run.sh` (studies flock, marker idiom); capital-flow pull unit (light GET, no studies lock) | **Reuse the wrapper idioms.** |
| Monitor scoping (WP1) | `resolve_trial_family` (`position_monitor_nightly_report.py:132-165`) | **Reuse** as the filter predicate. |

---

## 3. Design

### 3.1 Root cause of −0.37 versus +0.37 (WP1 commits the evidence note)

1. Every 2026-10-02 monitor report (`position_monitor_report_2026-10-02_pm_us_crh_{v4,v2,cont,fq_v1}.md`) shows the same single row: `positions: 1 (settled 1)`, `SETTLED ... n=1 realized_pnl_total=-0.3700`.
2. That row is the v4 trial `continuous_rung_hold/trial/SFO/2026-09-21/tc-temp-sfohigh-2026-09-21-gte66lt67f.POLYMARKET_US` (YES; `pnl=-0.3700`) in `derived/scored_trials/pm_us_crh_v4/scored_trials_20260922T141816645708220Z.parquet`.
3. **Mechanism.** `main` passes all summaries and all pooled scored trials into `build_monitor_report` (`:862-925`); `--family-manifest` only stamps `RuleSeries.family` (`_exit_rule_series`, `:698-742`). Nothing filters by family, and the wrapper runs once per REGISTERED manifest (`position-monitor-report-run.sh:206-209`).
4. The v4 tally `total pnl 0.3700` is the sum of three v4 fills: MIA NO 09-21 −0.13, SFO YES 09-21 −0.37, MDW NO 09-22 +0.87.
5. **Why only 1 of the 3 v4 fills is a monitor row (A17).** Report rows are **monitor summaries**, not scored trials: `_join` (`:539-586`) iterates summaries and only settles each from a joined `ScoredTrial`; a scored trial with no summary never becomes a row. Summaries are written only by the monitor's stop flush, and `read_monitor_summaries` (`monitor_store.py:262-278`) finds exactly **one** live summary file, `catalog/quote_tape/monitor/summaries/position_monitor_summaries_20260922T164011274098669Z.parquet` (the 09-22 16:40Z STOP flush), whose only 09-21/09-22 row is the SFO YES trial (read 2026-10-03). MDW NO 09-22 filled in a later session that wrote no summary file (no later file exists). Why MIA NO 09-21 is absent from the 09-22 flush is **INFERRED**: either the monitor did not register NO-leg positions at that build, or the position was not adopted at boot. WP1 resolves it from the monitor's registration path and records the verified mechanism in the note. Either way the number shown is a v4 row, not an FQ row.
6. **Verdict.** No sign error. The defect is attribution. FQ has zero scored fills (S7 branch skips the kind) and composes no `PositionMonitor`.

Further findings (unchanged from r1, each handled by a WP): F2 `portfolio-roi` exits 1 daily (WP1, WP6); F3 09-30 gross versus net (WP1, WP5); F4 FQ `trial_id_prefix` matches no key (WP2); F5 latch is not a fill join key, 14 latches against 11 fills (WP2); F6 exit fills never evaluated (WP4); F7 11 durable FQ fills, 5 settled and unlabelled (WP3 backfill).

### 3.2 Package layout (analysis layer, G15; never imported by a live package)

```
src/breezy/persistence/autonomy/            (Wave 0 owns schemas.py, plugin.py, pins.py)
    label_store.py      write_labels(), read_labels(), LABEL_V1_SCHEMA consumer        [AUT-2]
    net_position.py     net_signed_qty(fills) -> Mapping[base_slug, Decimal]            [AUT-2 unless Wave 0 placed it]
    canary_store.py     CANARY_ROOT = derived/canary/, append_canary_fill(), read_canary_fills()   [AUT-2, Z14]
src/breezy/analysis/labeling/
    constants.py        LABEL_LAG_MAX_H=24, WINDOW_INCOMPLETE_MAX_H=48, RECON_DAILY_VALIDITY_H=26,
                        RECON_INTRADAY_VALIDITY_H=8, INTRADAY_PERIOD_MIN=30, SNAPSHOT_MAX_AGE_MIN=45,
                        INCONCLUSIVE_ALERT_DAYS=2, BRIDGE_TAKE_TO_INIT_MAX_S=2, BRIDGE_INIT_TO_FILL_MAX_S=300
    instrument_facts.py extracted from score_live_trials.py (pure move)
    fill_source.py      read_durable_fills(db_path) -> FillRead(fills, n_keys, n_undecodable)
    attribution.py      attribute_fill(fill, manifests, fold|None, c1|None) -> Attribution | Unattributed
    decision_link.py    DecisionLink from C1, or NodeLogBridge (pre-C1)
    probability.py      p_of_bought_leg(p_hat_yes, side) (A5)
    fq_scorer.py        ForecastQuantileLadderScorer (C6 Scorer)
    exit_labels.py      label_exit(sell_fill, entry_label, settlement) -> LabelRow
    settlement_source.py SETTLEMENT_SOURCES: {polymarket_us: NwsCliFinal, kalshi: RefusingSettlementSource}
    completeness.py     coverage_partition(fills, labels, legacy) -> Coverage (A1)
    reconcile.py        reconcile_positions(), reconcile_settlement(), reconcile_cash()
    verdicts.py         build_reconciliation_verdict(mode), build_health_verdicts(mode)
    prelaunch_intents.py observe_intents_post_stop(), reconstruct_ambiguous_open_at() (Z19)
    label_run.py        python -m breezy.analysis.labeling.label_run [--canary|--proof-window]
    recon_run.py        python -m breezy.analysis.labeling.recon_run --mode {intraday,post_stop}  (W1, W8)
src/breezy/analysis/plugins.py   OFFLINE_PLUGINS gains the FQ Scorer entry          [one line]
scripts/venue/polymarket_us_positions_pull.py   wraps positions_value_capture.capture(); cursor-following; snapshot writer
deploy/systemd/breezy-label-outcomes.{service,timer}, label-outcomes-run.sh
deploy/systemd/breezy-aut2-reconciliation.{service,timer}, aut2-reconciliation-run.sh     (intraday, W1)
deploy/systemd/breezy-aut2-reconciliation-poststop.{service,timer}                         (W8; same wrapper, --mode post_stop)
```

r1's separate `breezy-venue-positions-pull` unit is folded into the two reconciliation units (pull, then reconcile, sequential `ExecStart=` lines in one oneshot), so every snapshot is consumed by a verdict.

Stores (0700 dirs, 0600 files, atomic writes, ns-named files):
- Labels: `derived/labels/<family_id>/labels_<now_ns>.parquet` (C2). Canary labels: `derived/labels_canary/<family_id>/`.
- Snapshots: `evidence/venue_positions/<venue>/positions_<now_ns>.json` = `{schema: "venue_positions/v1", snapshot_ns, complete: bool, pages, rows: [{base_slug, net_qty, expired}]}`; no account, position or order ids.
- Canary: `derived/canary/<venue>/canary_fills_<YYYY-MM-DD>.jsonl` (**ARCH §5.3 path**; r1's `state/canary/` corrected). Never opened by `fill_source.py`.
- Durable unattributed journal (A7): `evidence/aut2/unattributed_<YYYY-MM-DD>.jsonl` (fill key, base slug, ts_event, rule outcomes; no amounts).
- Run marker: `derived/label_outcomes_ok_<YYYY-MM-DD>.json` (§3.12).

### 3.3 C6 `Scorer` and the registration gate

- `ForecastQuantileLadderScorer.label(capture_day, exec_fills, settlements) -> tuple[LabelRow, ...]` registered in `OFFLINE_PLUGINS[CompositionKind.forecast_quantile_ladder].scorer`; it declares `legs = {"yes","no"}`, `roles = {"entry","exit"}`. CRH kinds keep `RefusingPlugin`; their historical fills are covered by the frozen legacy store (§3.12).
- **Family-agnostic.** `label_run` iterates `OFFLINE_PLUGINS` over the family set defined in §3.4.2 (non-RETIRED, plus RETIRED with unlabelled fills, A13). No family literal.
- **Registration-time gate:** `tests/contract/test_aut2_scorer_registration.py::test_every_non_retired_manifest_kind_has_a_non_refusing_scorer`; `::test_new_manifest_without_scorer_cannot_register`; `::test_scorer_declares_both_legs_and_both_roles`.
- **Compose-time cross-plan acceptance test (A10), owned by AUT-2:** `tests/contract/test_aut2_scorer_registration.py::test_armed_family_with_refusing_scorer_is_refused_at_compose`. It builds a REGISTERED fixture manifest with `live_orders_ruling` set (armed) and a kind whose `OFFLINE_PLUGINS` scorer is a `RefusingPlugin`, calls the production `_compose_family` (`app/trade.py:853`, AUT-5a's file) and asserts refusal with no strategy composed. AUT-2 never edits `app/trade.py`. **Hard prerequisite:** AUT-5a's compose-time refusal; WP7 merges only after AUT-5a, and score 3 is not claimed without this test green.

### 3.4 Fill source, attribution, decision link

#### 3.4.1 Universe
Every `DurableFillRecord` under `exec/polymarket_us/fill/` (G6 URI). Today 20 fills (11 FQ, 9 legacy CRH). The canary store is read only by the canary path (§3.8).

#### 3.4.2 Attribution by registration status at `ts_event` (A13)
In order:
- (a) **C1:** `client_order_id → OrderLink → decision_id → DecisionRecord.family_id`. Authoritative.
- (b) **C5 fold at `fill.ts_event`:** the family that was CHAMPION on the venue at that instant (G1). Must agree with (a). **Voided-pair exception (W14):** if the fold shows `ts_event` inside a pair's effective-then-voided interval (SWAP_CANCEL, Z8) and (a) names that pair's child, the fill is attributed to the child with `excluded_reason=voided_pair` (not unattributed). Any other disagreement leaves the fill unattributed.
- (c) **Pre-C1/C5 bridge:** base-slug grammar gives `(station, climate_day, rung, leg)`; the kind latch key must exist (FQ: `FORECAST_QUANTILE_TRIAL_KEY_PREFIX`, `persistent_latch.py:68`); the family is the unique manifest with `status == REGISTERED`, `composition_kind == kind`, matching venue, `station ∈ stations` and `d0_climate_day ≤ climate_day ≤ terminal_climate_day` (the optional upper bound, `family_manifest.py:388-405`). This is the pre-C5 proxy for "registered at `ts_event`".
- **Retired families keep being labelled.** The run's family set is: every family non-RETIRED now, **plus** every family (any status) that has an attributed durable fill without a final label. A family leaves the set only when its last fill has a final label. Pinned by `test_retired_family_labelled_until_last_fill` (RED: retire the fixture family after its fill; the fill must still be labelled). See §10 C-6 for the C6 YAGNI conflict this creates.
- **Unattributed** (no rule yields exactly one family): no C2 row (a `family_id` is never guessed); a durable row in `evidence/aut2/unattributed_<date>.jsonl` (A7); a C4 `HEALTH FAIL aut2.label_coverage` when the policy block exists; CRITICAL alert; `unattributed > 0` fails the completeness identity (§3.12).

#### 3.4.3 Identity
`trial_id = manifest.trial_id_prefix + "<STATION>/<day>/<rung_id>:<side>"` (F4). `label_id` = first 32 hex of `sha256("label/v1"|family_id|client_order_id|trade_id or ""|role)`; dedupe on `(label_id, max label_seq)`.

#### 3.4.4 Decision link and p of the bought leg (A5, A16)
- **Post-C1:** `decision_id`, `p_hat`, `side`, `entry_ask = ask_px` from `DecisionRecord`.
- **Pre-C1 bridge, keyed on `client_order_id` within bounded windows (A16):**
  1. From the durable fill take `client_order_id` and `trade_id`.
  2. Find the `OrderFilled` line with that `client_order_id` and `trade_id` (verified shape, log line 8393).
  3. Find the `OrderInitialized` line with the same `client_order_id` (line 8361) at most `BRIDGE_INIT_TO_FILL_MAX_S = 300 s` before the `OrderFilled`.
  4. Find the `SHADOW_DECISION` line with `kind == 'Take'`, the same `instrument_id`, and `now_ns ∈ [init_ts − BRIDGE_TAKE_TO_INIT_MAX_S, init_ts]` (observed gap 0.13 s from `now_ns` and 0.4 ms of log time, lines 8359→8361). Exactly one such Take is required; zero or two give `pre_c1_log_unmatched`.
  - Line adjacency is never used. Log files are the node log files (never journald); the search covers the file whose span contains `ts_event` and its predecessor (relaunch rotation).
  - `decision_id` is computed with the C1 formula from recorded fields (`eval_ns := now_ns`).
- **Probability conversion (A5).** FQ's `Take.p_hat` is the probability that the **YES rung** wins in both side modes: the NO EV uses `ev_net_no(p_upper)`, whose `model_p = 1.0 − p_upper` (`fq/decision.py:349`; `ladder_ev/scoring.py:70-87`). The same field is copied into C1 `DecisionRecord.p_hat`. Therefore `p_at_decision = p_of_bought_leg(p_hat, side) = p_hat if side == "yes" else 1 − p_hat`, applied identically in the bridge and C1 modes, and pinned as the C2 meaning "probability that the bought leg wins", consistent with `settled_outcome` = bought leg's win. A Take whose `side` disagrees with the fill's leg (`leg_of_symbol`) is `pre_c1_log_unmatched` in bridge mode and CRITICAL plus `reconciled=False` in C1 mode.
- No match: `p_at_decision = null`, `p_null_reason = pre_c1_log_unmatched` (C2 widening, §10 C-1). Row labelled for P&L and reconciliation; WARN; does not count toward the proof window.

### 3.5 Entry labels (YES and NO legs)

| Quantity | YES leg (`<slug>.POLYMARKET_US`) | NO leg (`<slug>^no.POLYMARKET_US`) |
|---|---|---|
| Durable record | `orderSide BUY`, cost in YES units | `orderSide BUY` (adapter sends venue `SELL`/`BUY_SHORT`, G24), cost in NO units |
| `fill_px` | `cumulative_cost / cumulative_qty` | same, NO units |
| `p_at_decision` | `p_hat` | `1 − p_hat` (§3.4.4) |
| `settled_outcome` | `bucket.contains(tmax_f)` | `not bucket.contains(tmax_f)` |
| `cost_basis` (fee-inclusive, A11) | `cumulative_cost + fee_reconciled` | same |
| `realized_pnl` (held) | `qty·payoff − cost_basis` | same |
| Venue net on base slug | `+qty` | `−qty` (L-44; `parsing.py:277-279`) |

- `score_trial` supplies settlement fields; `realized_pnl == ScoredTrial.pnl × qty` is asserted, never smoothed.
- `fee_reconciled = cumulative_fee` only when `fee_reconciled is True`; else `excluded_reason = fee_unreconciled`. **Every live `fee_unreconciled` fill alerts** (A2): WARN on first label, CRITICAL if still unreconciled after `LABEL_LAG_MAX_H`.
- **Slippage defect (A7).** `slippage = fill_px − entry_ask`. A negative slippage beyond one tick writes `excluded_reason = slippage_defect` as a **persisted column value** (C2 widening, §10 C-1) and a WARN alert. Until Rev 5 lands that enum, `write_labels` refuses (`LabelSchemaWideningMissing`) and no label is written at all: `test_label_store_refuses_without_widened_enum`. This is why the C2 widening is a hard prerequisite of WP2.
- **Admissibility.** `admissible = reconciled ∧ source == live ∧ ¬drill ∧ excluded_reason is None ∧ p_at_decision is not null`. `window_complete` for `(family, climate_day)` = every attributed fill on that day has a final settlement or a final exclusion. Before that, rows carry `excluded_reason = window_incomplete` (a non-final reason) and are re-labelled with `label_seq+1`. A `window_incomplete` row older than `WINDOW_INCOMPLETE_MAX_H = 48 h` past the venue settlement instant is a `HEALTH FAIL aut2.label_lag` (A2).
- **Final versus non-final reasons.** Final: `duplicate_fill`, `q≠1`, `fee_unreconciled` (after the lag horizon), `canary`, `drill`, `slippage_defect`, `voided_pair`, `venue_fallback_settlement` (after payout read). Non-final: `window_incomplete`, `fee_unreconciled` (inside the horizon).
- **Venue fallback settlement (A9).** When the venue settles at "last fair market price" (polymarket-us-integration skill; `settlement_basis == venue_last_fair_price_fallback`), the row gets `settled_outcome = null`, `realized_pnl = null`, `excluded_reason = window_incomplete` (pending) until the payout is read from the `PositionResolution` activity; then `realized_pnl = payout − cost_basis`, `excluded_reason = venue_fallback_settlement` (final, inadmissible for p-versus-outcome consumers), `reconciled` per the cash leg. RED: `test_venue_fallback_pending_until_payout_then_final`.
- **Settlement basis by venue:** `polymarket_us → NwsCliFinal`; `kalshi → RefusingSettlementSource("twc_reader_absent")` (Kalshi settles on The Weather Company).

### 3.6 Reconciliation: three legs, per-leg tolerances (ARCH §10)

| Leg | Compared set and comparison | Evidence | Tolerance | On breach |
|---|---|---|---|---|
| **Position (net)** | **Compared set = ledger slugs ∪ venue-page slugs (A6)**. For each base slug: venue `net_qty` versus `net_signed_qty(ledger fills with ts_event ≤ snapshot_ns)`. A **venue slug with no ledger fill → FAIL** (`venue_only_slug`). A **ledger slug that is open and absent from the page compares as venue 0**. "Open" = `snapshot_ns < settlement_deadline_ns(climate_day)` (venue clock, `settlement_clock.py:36`) **and** the slug has not appeared with `expired == true`. A ledger slug past its deadline and absent from the page is **settled-away** (L-52): not compared on this leg, covered by the settlement and cash legs. | `venue_positions/v1` snapshot; only `complete == true` snapshots (all pages to `eof`) are used | **0 contracts, exact Decimal**, both legs | `reconciled=False` on the slug's labels, CRITICAL, `RECONCILIATION FAIL`. A slug with an OPEN/AMBIGUOUS intent at snapshot time is UNKNOWN → INCONCLUSIVE (L-52). An incomplete snapshot is INCONCLUSIVE, never PASS. |
| **Settlement** | Label `settled_outcome` (NWS CLI final) versus venue settlement for the slug | tape `custom_venue_settlement_snapshot`; `PositionResolution` | exact outcome equality | `reconciled=False`, CRITICAL `settlement_source_disagreement`; the venue value is never adopted. Fallback: §3.5 (A9). No venue evidence 24 h after the CLI final: pending; 48 h: FAIL. |
| **Cash (cumulative net identity, A8)** | `reconcile_daily` over C2: `unexplained(D) = Δbalance_net(D) − proceeds(D) + capital_deployed(D)`, where `capital_deployed(D)` = Σ fee-inclusive cost of BUY fills opened on D (`capital_deployed_by_day`, `:1096`), and `proceeds(D)` = Σ settlement payouts (`qty·payoff`) dated at the venue settlement instant plus exit proceeds net of exit fee at the SELL's `ts_event`. **Open cost is held out**: an open fill's cost appears only as `capital_deployed` on its open day and is never booked as realized P&L. Pass = `cumulative_reconciliation(...).settled_cumulative_passes_net` over days ≤ `settled_through` (the latest day all of whose fills have final labels). | node-log balance lines + `capital_flows/` (net path, F3) | `per_day_tolerance(fills_opened_that_day)` (`:1390`), with the count from `_fills_opened_count_by_day` (`:1110`); the cumulative tolerance is Σ over settled days | `RECONCILIATION FAIL`, CRITICAL. `BALANCE_UNKNOWN` or `external_flow_evidence_status != OK` → INCONCLUSIVE, never zero-coerced. |

- **Exit consistency:** latch `exitPx/exitFee/exitAtNs` (`exit_wiring.py:227-236`) must equal the durable SELL; mismatch → `reconciled=False` on the exit label.
- **Coverage of the position leg (A4).** Every fill must be position-compared at least once before its settlement. A label's `position_compared_snapshot_ns` = the **last complete snapshot at or after `ts_event` and before `settlement_deadline_ns`** in which its slug was compared. The intraday unit (§3.11) snapshots every 30 min, so a typical FQ fill (filled ~21:00–02:00Z, settling ~12:00/13:00Z the day after next) has ~60 candidate snapshots. **No such snapshot → coverage FAIL** (`fills_never_position_compared > 0` fails the day's RECONCILIATION), not UNKNOWN. A missing or stale snapshot (`> SNAPSHOT_MAX_AGE_MIN = 45` at verdict time) makes that verdict INCONCLUSIVE plus a WARN alert. `INCONCLUSIVE_ALERT_DAYS = 2` consecutive INCONCLUSIVE daily verdicts → CRITICAL; the same rule applies to consecutive `BALANCE_UNKNOWN` days.
- **Daily outcome.** PASS only if all three legs pass, coverage passes and the completeness identity holds (§3.12). Any FAIL → FAIL. Else INCONCLUSIVE, which never satisfies §4.4 or ATTEST.

### 3.7 C4 producers (daily run)

#### 3.7.1 RECONCILIATION (daily, from `label_run`)
- Producer id `aut2_label_run`, pinned in `PRODUCER_SOURCE_SHA256` (§4.3 closure; pin update in the same commit).
- Per family in the §3.4.2 set: `subject_artefact_sha256` = bound artefact sha (Z1; pre-C5 the manifest's `density_artefact_sha256`); `detector = "aut2.reconciliation"`; `declared_action_class`, `prereg_ruling_sha256` read only from the pinned `autonomy-policy/v1` block; `n` = slugs + days compared, `n_min` reason `deterministic_equality_check`.
- `metrics` (pre-registered names): `position_slugs_compared, venue_only_slugs, position_mismatches, settlement_mismatches, cash_days_failed, unknown_slugs, fills_never_position_compared, durable_fill_count, labelled_final, excluded_final, legacy_covered, pending, unattributed, ambiguous_open_at_prelaunch_7d, ambiguous_unknown_7d`.
- `valid_until_ns = produced_at_ns + RECON_DAILY_VALIDITY_H (26 h)`, equal to `MAX_VERDICT_VALIDITY_H` ceiling (§4.5). Daily runs at 14:15Z and 05:00Z (max gap 15 h).
- Before the policy block exists (AUT-5b): no C4 file; alerts, journals and `reconciled=False` still operate.

#### 3.7.2 HEALTH `aut2.label_lag` and `aut2.label_coverage` (A2, A15)
- **Lag clock (A2).** For each live fill, `lag_start_ns = settlement_deadline_ns(venue, city, climate_day)` (08:00 ET on climate_day+1; never the CLI ingest time). `label_lag = first_final_label_ns − lag_start_ns`, where `first_final_label_ns` is the `labelled_at_ns` of the first row that is **admissible or carries a final excluded_reason**. A `window_incomplete` row never stops the clock.
- **Horizon pinned numerically (A15).** `LABEL_LAG_MAX_H = 24` (README) in `analysis/labeling/constants.py`; `test_label_lag_horizon_pinned_under_max_verdict_validity` asserts `LABEL_LAG_MAX_H == 24` and `LABEL_LAG_MAX_H ≤ pins.MAX_VERDICT_VALIDITY_H` (26), and `WINDOW_INCOMPLETE_MAX_H == 48`.
- Any live fill with `now − lag_start_ns > 24 h` and no final label → `HEALTH FAIL aut2.label_lag` + CRITICAL. RED: `test_no_cli_final_fails_label_lag_at_24h_from_venue_settlement` (fixture: fill settled by venue clock, no CLI final; at +23 h59 m PASS, at +24 h FAIL). Unattributed fills → `HEALTH FAIL aut2.label_coverage`.
- **Exit code.** A lag or coverage FAIL is a detected data condition: the unit exits 0 after the verdict and CRITICAL are written (exit code means "the labeller ran correctly"); an unreadable store is a genuine failure and exits non-zero (§3.12).

#### 3.7.3 Delivery
Every CRITICAL goes through `deliver_with_proof` (AUT-6), journaled to `evidence/alerts/delivery_<date>.jsonl`. Interim `emit_alert` + `OnFailure=` is not score-3 evidence.

### 3.8 Canary store (Z14) and drill

- **Path** `derived/canary/<venue>/` (ARCH §5.3). Writer: `label_run --canary`, invoked by the label unit only on a UTC day with zero real attributed fills. C1-shaped synthetic records, `source=canary`.
- **Canary Scorer input.** The same `ForecastQuantileLadderScorer.label(...)` reads `read_canary_fills()` and a synthetic canary venue snapshot; output to `derived/labels_canary/`. Never enters `derived/labels/`, any RECONCILIATION input, any `n`, `portfolio-roi`, `entry_guard`, or the completeness identity.
- **Canary-day verdict, explicit (A12).** ARCH §5.3 lets a canary day qualify. A canary day qualifies iff: (i) every canary fill of that day has a canary label with non-null `p_at_decision` and canary reconciliation PASS against the synthetic snapshot; **and** (ii) the day's real RECONCILIATION verdict is PASS (zero real fills that day, but open prior-day holdings, settlements and cash are still reconciled). A canary **never** satisfies "every live fill labelled": the proof artefact computes that check over real fills only and records `real_fills=0, canary_fills=k, live_fill_check="vacuous"` for the day. Canary fills never count toward the ≥ 5 real fills.
- **Tests (`tests/unit/test_aut2_canary_isolation.py`):** `::test_reconciliation_never_reads_canary_store`; `::test_entry_guard_never_reads_canary_store`; `::test_canary_labels_are_never_admissible`; `::test_canary_rows_excluded_from_verdict_n_and_completeness`; **positive controls (A14):** `::test_canary_ast_scanner_flags_planted_reader` (a fixture module that opens `CANARY_ROOT` must be flagged by the same scanner the two isolation tests use) and `::test_runtime_canary_guard_trips_on_planted_open` (a monkeypatched reader that opens `CANARY_ROOT` makes the runtime guard raise).
- **Drill.** `drill=true` (Z2 fold) → `excluded_reason=drill`, inadmissible; drill fills are real venue fills, so they are position- and cash-reconciled and appear in the completeness identity. Drill rows are written (never dropped) so AUT-6 detectors and the AUT-5 drawdown limit can include them (W12). Tests: `test_drill_fill_labelled_reconciled_but_inadmissible`, `test_drill_fill_after_resume_still_drill`.

### 3.9 Z19: AMBIGUOUS intent open at 16:45Z (A18)

- **Direct observation (new in r2).** The post-STOP run (§3.11, 16:41Z) reads `exec/polymarket_us/intent/current` read-only, as `probe_open_intent` does. Between STOP (16:40Z) and LAUNCH (16:50Z) no node runs, so no process writes intents (G22, G30), and the state at 16:41Z equals the state at 16:45Z. It emits `ambiguous_open_at_prelaunch(d) ∈ {true, false}` from this observation.
- `unknown` only when the post-STOP run did not complete that day. A historical backfill uses `reconstruct_ambiguous_open_at()` over `intent/history/*` and reports `unknown` whenever `created_ns` preservation is unproven (WP5 L-1 (ii)).
- Output: 7-day counts in RECONCILIATION metrics and the journal line `Z19 ambiguous_open_at_1645Z days=<k>/<n> unknown=<u>`.
- **A18.** Until AUT-5a's supervisor journaling exists, `unknown` is a **metric only, never alerted** (`test_z19_unknown_is_metric_not_alert`). `true` is not an AUT-2 alert either (§4.4 already cancels the swap); it is a finding for AUT-5 policy review.

### 3.10 Consumers rewired; no expected failures

| Unit | Today | After AUT-2 |
|---|---|---|
| `breezy-score-live-trials` (14:15Z) | FQ: S7 `exit 0`, no marker | WP1: S7 writes `score_live_trials_noinput_$STAMP`. WP6: moves to 13:55Z; frozen CRH stores only; disabled once C5 bootstrap marks every CRH family RETIRED (a reviewed unit change). |
| `breezy-portfolio-roi` (17:40Z) | exit 1 daily (F2) | WP1: accepts `ok` or `noinput`. WP6: gates on `label_outcomes_ok_<date>.json`; **`pending > 0` → `roi_status=GATED_UNSETTLED_CAPITAL`, exit 0** (A3); P&L = C2 ∪ legacy (overlap refused); net pass flag. |
| `breezy-family-tally@pm_us_crh_{v2,v4}` | SKIPPED | Unchanged semantics; never non-zero as expected behaviour (WP6 test). |
| `breezy-position-monitor-report` | Unscoped | WP1: family-scoped; `NO_MONITOR_FOR_KIND forecast_quantile_ladder`. |
| `breezy-replay-daily` | FQ SKIPPED | Unchanged (AUT-4). |
| New `breezy-label-outcomes` | n/a | `OnCalendar=*-*-* 14:15:00 UTC` and `*-*-* 05:00:00 UTC`; `flock -w 600` on `breezy-studies.lock`, `breezy-studies.slice`; `MemoryMax=1G`; `RuntimeMaxSec=1200` (ends ≤ 14:45Z < 16:30Z); `OnFailure=breezy-study-failed@%n`; `EnvironmentFile=-%h/.config/breezy/alerts.env`; stall line every 60 s. |
| New `breezy-aut2-reconciliation` (W1) | n/a | `OnCalendar=*-*-* *:05,35:00 UTC`; own lock `~/.local/share/breezy/locks/aut2-reconciliation.lock` (`flock -w 30`), never the studies flock; `MemoryMax=512M` (within the 4G own-lock budget, §5.2); `RuntimeMaxSec=240`; `OnFailure=`; alerts env; venue credentials per the capital-flow pull unit. `ExecStart` 1 = positions pull, `ExecStart` 2 = `recon_run --mode intraday`. Skips (exit 0, `AUT2_RECON SKIPPED window=stop_launch`) at the 16:35Z fire only if it would overlap the post-STOP slot's lock; the post-STOP unit supersedes it. |
| New `breezy-aut2-reconciliation-poststop` (W8) | n/a | `OnCalendar=*-*-* 16:41:00 UTC`; same lock with `flock -w 20`; `RuntimeMaxSec=100` (16:41:00 + 20 s + 100 s ends ≤ 16:43:00Z, before the 16:45Z pre-launch pass); `MemoryMax=512M`; same wrapper with `--mode post_stop`. |

**Slot rationale.** PM.us settles at 08:00 ET (12:00Z EDT, 13:00Z EST from 11-02); western CLI finals arrive ~09:30–10:30Z; 14:15Z is the primary label run, 05:00Z the catch-up (11:00 ET delayed settlements, corrections). ARCH §5.2 says "AUT-n plans fix the rows".

### 3.11 Intraday and post-STOP producers (W1, W8)

- **Producer id** `aut2_recon_run` (`breezy.analysis.labeling.recon_run`), pinned in `PRODUCER_SOURCE_SHA256` with `aut2_label_run`.
- **Intraday mode (W1), every 30 min.** Steps: (1) complete positions snapshot; (2) position leg over ledger ∪ page (§3.6); (3) carry forward the newest daily RECONCILIATION outcome (settlement and cash legs, completeness): the intraday verdict is **PASS only if the position leg passes and the newest daily RECONCILIATION is PASS and younger than 26 h**; daily FAIL → intraday FAIL; daily INCONCLUSIVE/absent/expired → intraday INCONCLUSIVE. The cited daily verdict's sha is an `inputs` entry (`path_role=daily_reconciliation_verdict`). (4) HEALTH `aut2.label_lag` and `aut2.label_coverage` recomputed from the label store and the fill set (read only; no relabel). `valid_until_ns = produced_at_ns + RECON_INTRADAY_VALIDITY_H (8 h)`.
- **ATTEST invariant (W1), AUT-2's row.** `ATTEST_PERIOD_MAX_H (6, AUT-5) + INTRADAY_PERIOD_MIN (0.5 h) + RuntimeMaxSec (≤ 0.07 h) ≤ RECON_INTRADAY_VALIDITY_H (8)`, margin ≈ 1.4 h. AUT-2 provides `test_intraday_recon_cadence_fits_attest_invariant` over its own schedule table (`constants.py` plus the timer file parsed); AUT-5 owns `test_attest_cadence_has_no_expiry_gap` over the joint table and consumes these constants.
- **Post-STOP mode (W8).** Same steps at 16:41Z with the node stopped (the best moment for exact equality: no in-flight fills). Also records Z19 (§3.9). **§4.4 horizon definition supplied to AUT-5:** the pre-launch pass accepts a RECONCILIATION only if `produced_at_ns ≥ STOP_ns(D)` (16:40Z of day D) and it was produced by `aut2_recon_run --mode post_stop`, outcome PASS. A missing, late or non-PASS post-STOP verdict makes the pre-launch preconditions fail → `SWAP_CANCEL`; the incumbent launches unchanged (§4.4: preconditions gate only a change of sender), so a dead producer cannot deadlock launch.
- Before the policy block: no C4 file; the snapshot, journal lines and alerts still run.

### 3.12 Completeness identity, marker and NO_INPUT (A1, A3)

- **Partition.** `completeness.coverage_partition` places every durable fill read by `fill_source` (count `n_keys` from `read_ledger_fills_with_counts`) in exactly one bucket:
  - `C2_FINAL` (a C2 row admissible or with a final excluded_reason);
  - `C2_NONFINAL` (only non-final rows; split into `open` if `now < settlement_deadline_ns`, else `pending`);
  - `LEGACY_COVERED` (a legacy CRH fill in the `SCORED` or `RESIDUAL` bucket of `bucket_ledger_fills`, or listed by `_fee_unverified_fills_deduped`);
  - `UNATTRIBUTED` (includes the legacy `UNRECONCILED` bucket).
- **Identity asserted every run and in the proof artefact:** `C2_FINAL + C2_NONFINAL + LEGACY_COVERED + UNATTRIBUTED == durable_fill_count`, **with `UNATTRIBUTED == 0`** and `n_undecodable == 0`. Equivalently `labelled + explicitly-excluded == durable count` once pending drains. A breach → `RECONCILIATION FAIL` + CRITICAL. Every new fill gets at least a `window_incomplete` C2 row on the first run after it appears, so a fill can never be silently absent.
- **RED tests:** `tests/unit/test_aut2_completeness.py::test_labelled_plus_excluded_equals_durable_count`; positive control `::test_deleting_one_label_fails_identity` (remove one label file row through the real writer's dedupe path → FAIL); `::test_legacy_crh_fills_counted_in_denominator`; `::test_unattributed_fill_fails_identity`.
- **Marker (A3).** `derived/label_outcomes_ok_<date>.json` = `{schema: "label_outcomes_marker/v1", run_outcome ∈ {LABELLED, PENDING, NO_INPUT}, durable_fill_count, labelled_final, excluded_final, legacy_covered, open, pending, unattributed}`; written last, only after a successful run.
- **NO_INPUT** is allowed only when the run wrote zero rows **and** `pending == 0` **and** `unattributed == 0`. Zero rows with `pending > 0` is `PENDING` (exit 0, marker written, line `LABEL_OUTCOMES PENDING pending=<n>`). **Consumers go GATED when `pending > 0`** (portfolio-roi §3.10; AUT-3/AUT-4 contract §5).
- **Unreadable store.** Any failure to open or decode the exec store, the label store, a manifest or a snapshot → CRITICAL, exit 1, no marker; never NO_INPUT, never exit 0. RED: `test_unreadable_exec_store_exits_nonzero_without_marker`, `test_undecodable_fill_is_store_corruption_not_skip`, `test_unreadable_label_store_exits_nonzero`.

---

## 4. Work packages

Gate for every WP, from the tree root, exact interpreter, never `uv`/`pip` (L-51):
- `scripts/ci/run_tests_no_egress.sh` (full gate after **every** merge, L-43; under a unit `-p LimitNOFILE=524288`).
- `cd <tree> && .venv/bin/lint-imports` must print `N kept, 0 broken`.
- `.venv/bin/mypy src/breezy/analysis/labeling src/breezy/persistence/autonomy scripts/venue/polymarket_us_positions_pull.py`: 0 errors, no new `# type: ignore`.
- In a worktree, `PYTHONPATH=<worktree>/src`.
RED→GREEN output is kept per WP. Every injectable seam has a production-default test (L-55); every store-reading gate test writes fixtures through the real writer (L-42).

### AUT-2.WP1: root cause; monitor scoping; portfolio-roi expected failure removed (no Wave 0 dependency; start now)
- **Scope.** Evidence note `docs/evidence/AUT-2_rc_monitor_pnl_2026-10-03.md` (§3.1 facts; H3 verified to the cent from `PRIVATE_portfolio_roi_2026-09-30.json`, classification only; **A17: the summary-only row mechanism and the verified reason MIA NO 09-21 is absent**). Family filter, `NO_MONITOR_FOR_KIND`, `noinput` marker.
- **Files.** `scripts/analysis/position_monitor_nightly_report.py`; `deploy/systemd/score-live-trials-run.sh`; `deploy/systemd/portfolio-roi-run.sh`.
- **RED first:** `tests/unit/test_position_monitor_nightly_report.py::test_bound_report_excludes_other_family_summaries`; `::test_bound_report_keeps_own_family_rows`; `::test_fq_kind_reports_no_monitor_for_kind`; `::test_unbound_report_unchanged_golden`; `::test_scored_trial_without_summary_is_not_a_row` (A17); `tests/unit/test_score_live_trials_deploy.py::test_fq_champion_writes_noinput_marker_and_exits_zero`; `tests/unit/test_portfolio_roi_deploy.py::test_noinput_marker_admits_run`; `::test_absent_markers_still_refuse`.
- **GREEN.** 10-04 FQ report `positions: 0` + `NO_MONITOR_FOR_KIND`; v4 report still −0.37; 10-04 17:40Z `portfolio-roi` exits 0.
- **Activation.** Immediate; scripts are read at each fire. Verify in the journal after the first fire.

### AUT-2.WP2: C2 store, fill source, attribution, completeness (Wave 1; after ARCH-0 **and** the Rev 5 C2 widening)
- **Files.** `persistence/autonomy/{label_store,net_position}.py`; `analysis/labeling/{constants,fill_source,attribution,instrument_facts,completeness}.py`; `scripts/analysis/score_live_trials.py` (import only).
- **RED first:** `tests/unit/test_aut2_label_store.py::test_schema_is_exact_label_v1`; `::test_dedupe_keeps_max_label_seq`; `::test_unknown_schema_version_refused`; `::test_atomic_write_no_partial_file`; `::test_money_columns_are_string_decimal`; `::test_label_store_refuses_without_widened_enum` (A7); `tests/unit/test_aut2_fill_source.py::test_reads_every_fill_through_ro_uri`; `::test_undecodable_fill_is_store_corruption_not_skip`; `::test_fill_source_reads_wal_store_after_writer_exit` (W8 precondition); `::test_real_default_reader_against_tmp_store`; `tests/unit/test_aut2_attribution.py::test_fq_fill_attributed_via_kind_latch_not_manifest_prefix`; `::test_latch_without_fill_is_not_a_label`; `::test_two_candidate_families_unattributed`; `::test_c1_and_fold_disagreement_unattributed`; `::test_voided_pair_fill_attributed_to_child_with_voided_pair` (W14); `::test_attribution_uses_status_at_ts_event_not_now` (A13); `::test_retired_family_labelled_until_last_fill` (A13); `::test_unattributed_writes_durable_journal_row` (A7); `::test_trial_id_uses_manifest_prefix`; `tests/unit/test_aut2_net_position.py::test_no_fill_offsets_yes_holding_to_netted_venue_qty`; `::test_each_leg_terminal_state`; `::test_sell_nets_against_long`; the four `test_aut2_completeness.py` tests (§3.12).
- **GREEN.** Dry run over the live store: 11 FQ fills attributed to `pm_us_crh_fq_v1`, 9 CRH fills `LEGACY_COVERED`, identity holds with `UNATTRIBUTED == 0`. If any legacy fill lands in `UNATTRIBUTED`, that is a finding resolved before WP6 activation, never waived.
- **Activation.** Library; lands live through WP6.

### AUT-2.WP3: FQ Scorer, entry labels, decision link, settlement sources, backfill
- **Files.** `analysis/labeling/{fq_scorer,decision_link,probability,settlement_source}.py`; `OFFLINE_PLUGINS` entry.
- **RED first:** `tests/unit/test_aut2_fq_scorer.py::test_yes_win_and_yes_loss_pnl_net_of_reconciled_fee`; `::test_no_leg_win_and_no_leg_loss_pnl`; `::test_realized_pnl_equals_score_trial_pnl_times_qty`; `::test_fee_unreconciled_excluded_and_alerted` (A2); `::test_preliminary_cli_never_settles`; `::test_correction_relabels_with_next_label_seq`; `::test_window_incomplete_until_all_fills_settle`; `::test_window_incomplete_older_than_48h_fails_label_lag` (A2); `::test_negative_slippage_beyond_tick_persists_slippage_defect` (A7); `::test_venue_fallback_pending_until_payout_then_final` (A9); `::test_canary_and_drill_rows_never_admissible`; `tests/unit/test_aut2_probability.py::test_yes_take_p_is_p_hat`; `::test_no_take_p_is_one_minus_p_hat_bridge_mode` (A5); `::test_no_take_p_is_one_minus_p_hat_c1_mode` (A5); `::test_take_side_disagreeing_with_fill_leg_unmatched`; `tests/unit/test_aut2_decision_link.py::test_bridge_joins_on_client_order_id_not_adjacency` (A16: interleave another instrument's lines between Take and fill); `::test_bridge_window_bounds_enforced` (Take 3 s before init → unmatched; init 301 s before fill → unmatched); `::test_two_takes_in_window_unmatched`; `::test_take_after_init_is_not_linked`; `::test_unmatched_fill_null_p_with_reason`; `::test_c1_record_overrides_log_line`; `::test_real_default_log_reader_on_tmp_file`; `tests/unit/test_aut2_settlement_source.py::test_kalshi_settlement_source_refuses_until_twc_reader`; `::test_polymarket_uses_nws_cli_final_latest_revision`.
- **GREEN.** Backfill dry run labels the 5 settled 10-02 FQ fills (p from Take lines via `client_order_id`), and the 6 10-03 fills after their finals; P&L equals the per-fill `score_trial` sum.
- **Activation.** Through WP6.

### AUT-2.WP4: exit labels (F6, A11)
- **Semantics (fee-inclusive, pro rata).** For an exit of `q_x` from an entry of `q_e` with entry `cost_basis_e = cumulative_cost + fee`: `cost_basis(q_x) = cost_basis_e · q_x / q_e`; `realized_pnl_exit = proceeds − exit_fee − cost_basis(q_x)`; `counterfactual_hold_pnl = payoff(settled_outcome)·q_x − cost_basis(q_x)`; the entry label's remainder is `payoff·(q_e − q_x) − cost_basis(q_e − q_x)`. Identity: Σ realized per slug = cash moved on the slug.
- **RED first:** `tests/unit/test_aut2_exit_labels.py::test_yes_exit_realized_and_counterfactual`; `::test_no_leg_exit_signs`; `::test_partial_no_leg_exit_pro_rata_fee_inclusive` (A11: `q_e=3`, `q_x=1`); `::test_counterfactual_includes_entry_fee` (A11); `::test_slug_pnl_identity_entry_plus_exit`; `::test_record_exit_latch_mismatch_unreconciles`; `::test_exit_without_entry_unattributed`.
- **GREEN.** Fixture identity holds for both legs. Live exits only if an exit-capable family is CHAMPION (G17).
- **Activation.** Through WP6.

### AUT-2.WP5: reconciliation core, positions pull, verdict builders, Z19
- **Files.** `scripts/venue/polymarket_us_positions_pull.py`; `analysis/labeling/{reconcile,verdicts,prelaunch_intents}.py`; `portfolio_roi_report.py` (expose a C2 proceeds adapter for `reconcile_daily`; its own report unchanged).
- **L-1 steps before RED:** (i) the archived `PRIVATE_v1_portfolio_positions_open_positions_20260916.positions.json` holds one negative `netPosition` among four rows (sign read 2026-10-03, values not printed); WP5 maps it to its ledger NO fill to confirm "NO = negative on the YES slug"; if it does not map, the first live pull is the positive control and the leg rule waits. (ii) `submit_intent.py` retire path and `created_ns` (backfill only, §3.9). (iii) `find_execution_egress_modules` does not flag a GET-only module. (iv) `PositionResolution` carries the fallback payout (A9); if not, the fallback row stays pending and alerts at the lag horizon. (v) Whether `_cash_between` already books SELL proceeds; if not, the C2 adapter supplies them.
- **RED first:** `tests/unit/test_aut2_positions_pull.py::test_not_an_execution_egress_module`; `::test_get_only_reuses_assert_get_only`; `::test_follows_cursor_to_eof_else_incomplete`; `::test_snapshot_has_no_account_or_order_ids`; `tests/unit/test_aut2_reconcile.py::test_position_leg_exact_equality_both_legs`; `::test_compared_set_is_ledger_union_page` (A6); `::test_venue_slug_without_ledger_fill_fails` (A6); `::test_open_ledger_slug_missing_from_page_compares_as_zero` (A6); `::test_settled_away_slug_not_compared` (A6, L-52); `::test_incomplete_snapshot_inconclusive`; `::test_open_intent_at_snapshot_is_unknown_not_pass`; `::test_fills_after_snapshot_fenced_out`; `::test_every_fill_position_compared_before_settlement_else_fail` (A4); `::test_stale_snapshot_inconclusive_and_alerts` (A4); `::test_two_consecutive_inconclusive_days_alert_critical` (A4); `::test_two_consecutive_balance_unknown_days_alert_critical` (A4); `::test_settlement_disagreement_unreconciles_and_never_adopts_venue`; `::test_cash_leg_mixed_day_open_settled_exit` (A8: one fill opened and open, one prior fill settling, one exit on the same day; passes; perturb one `realized_pnl` by 0.02 → FAIL); `::test_cash_tolerance_counts_fills_opened_not_settled` (A8); `::test_balance_unknown_day_inconclusive`; `tests/unit/test_aut2_verdicts.py::test_daily_reconciliation_valid_26h`; `::test_subject_sha_is_bound_artefact_sha`; `::test_action_class_read_from_policy_block_only`; `::test_no_verdict_without_policy_block_but_alert_fires`; `::test_no_cli_final_fails_label_lag_at_24h_from_venue_settlement` (A2); `::test_lag_clock_stops_only_on_final_label` (A2); `::test_label_lag_horizon_pinned_under_max_verdict_validity` (A15); `::test_unattributed_fill_health_fail`; `::test_payload_hygiene_scan_covers_aut2_writers`; `tests/unit/test_aut2_prelaunch_intents.py::test_post_stop_observation_counts_ambiguous`; `::test_missing_post_stop_run_reports_unknown`; `::test_rewritten_created_ns_reports_unknown`; `::test_z19_unknown_is_metric_not_alert` (A18).
- **GREEN.** Dry run: position PASS on open 10-03 slugs (ledger ∪ page), settlement PASS on 10-02, cash PASS on the net identity, completeness identity holds.
- **Activation.** Library; live through WP6 and WP9.

### AUT-2.WP6: label run unit and consumer rewiring
- **Files.** `analysis/labeling/label_run.py`; `deploy/systemd/breezy-label-outcomes.{service,timer}`, `label-outcomes-run.sh`; `portfolio-roi-run.sh`, `portfolio_roi_report.py` (marker JSON gate, GATED on pending, P&L union, net flag); `breezy-score-live-trials.timer` (13:55Z); `deploy/systemd/README.md`.
- **RED first:** `tests/unit/test_aut2_label_run.py::test_iterates_offline_plugins_not_family_list`; `::test_refusing_plugin_for_non_retired_family_fails_run_no_marker`; `::test_no_input_only_when_pending_zero` (A3); `::test_zero_rows_with_pending_is_pending_not_no_input` (A3); `::test_marker_carries_counts` (A3); `::test_marker_written_last_only_on_success`; `::test_unreadable_exec_store_exits_nonzero_without_marker` (A3); `::test_unreadable_label_store_exits_nonzero`; `::test_label_lag_fail_exits_zero_with_verdict_and_critical`; `::test_stdout_carries_label_outcomes_summary_line`; `::test_real_default_paths_on_tmp_home`; `tests/unit/test_label_outcomes_deploy.py::test_unit_has_memorymax_runtimemaxsec_onfailure_alerts_env`; `::test_runtime_bound_ends_before_1630Z`; `::test_two_oncalendar_slots`; `tests/unit/test_portfolio_roi_report.py::test_pnl_source_union_labels_and_legacy`; `::test_fill_in_both_sources_refused`; `::test_pass_flag_is_net`; `::test_pending_gt_zero_gates_roi` (A3); `tests/unit/test_outcome_units_no_expected_failure.py::test_every_outcome_wrapper_exits_zero_on_no_input` (parametrised: score-live-trials, portfolio-roi, family-tally@v2/v4, position-monitor-report, label-outcomes, aut2-reconciliation, replay-daily); **`::test_every_outcome_wrapper_exits_nonzero_on_genuine_failure` (A14: same parametrisation, with an unreadable store or a raising entrypoint; each wrapper must exit non-zero and write no success marker).**
- **GREEN.** First 14:15Z run labels the 10-02 FQ fills, marker `run_outcome=LABELLED, pending=0`; 17:40Z `portfolio-roi` `roi_status=OK`.
- **Activation.** Immediate on merge; coordinator installs and enables the timer. No node or supervisor restart.

### AUT-2.WP7: C1 switch-over, registration gate, compose cross-plan test (Wave 2; after AUT-1 C1 live **and** AUT-5a compose refusal)
- **Scope.** Rule (a) and C1 p authoritative; bridge demoted to a cross-check (disagreement → CRITICAL + `reconciled=False`); optional `SettlementRecord` with `raw_sha256` equality.
- **RED first:** `tests/contract/test_aut2_scorer_registration.py` (three §3.3 tests) **plus `::test_armed_family_with_refusing_scorer_is_refused_at_compose` (A10)**; `tests/unit/test_aut2_decision_link.py::test_c1_and_log_p_disagree_unreconciles`; `::test_c1_decision_id_join_every_tagged_fill`; `tests/unit/test_aut2_fq_scorer.py::test_settlement_record_sha_must_match_cli_raw`.
- **GREEN.** 100% of post-switch fills carry C1 `decision_id`; the compose test is green against AUT-5a's merged code.
- **Activation.** Immediate (offline).

### AUT-2.WP8: canary store and canary path (Z14, A12, A14)
- **Files.** `persistence/autonomy/canary_store.py` (`derived/canary/`); `label_run --canary`; proof-window canary-day rule.
- **RED first:** the six §3.8 tests (including both positive controls); `::test_canary_written_only_on_zero_real_fill_day`; `::test_portfolio_roi_never_reads_canary`; `tests/unit/test_aut2_proof_window.py::test_canary_day_qualifies_only_with_real_recon_pass` (A12); `::test_canary_never_satisfies_live_fill_check` (A12).
- **GREEN.** A synthetic zero-fill day produces `labels_canary/` rows, no change to `labels/`, verdict `n` or completeness counts.
- **Activation.** Immediate.

### AUT-2.WP9: intraday and post-STOP reconciliation producers (W1, W8)
- **Files.** `analysis/labeling/recon_run.py`; `deploy/systemd/breezy-aut2-reconciliation{,-poststop}.{service,timer}`, `aut2-reconciliation-run.sh`; `PRODUCER_SOURCE_SHA256` entry.
- **RED first:** `tests/unit/test_aut2_recon_run.py::test_intraday_verdict_valid_8h`; `::test_intraday_pass_requires_daily_pass_younger_than_26h`; `::test_intraday_inherits_daily_fail`; `::test_intraday_inconclusive_without_daily`; `::test_intraday_emits_health_label_lag_and_coverage`; `::test_post_stop_verdict_produced_after_stop_and_tagged_mode`; `::test_post_stop_records_z19_observation`; `::test_post_stop_reads_exec_store_with_node_stopped` (fixture: writer closed); `::test_lock_contention_skips_with_line_exit_zero`; `tests/unit/test_aut2_recon_deploy.py::test_intraday_cadence_fits_attest_invariant` (W1); `::test_post_stop_slot_ends_before_1645Z` (16:41 + `flock -w` + `RuntimeMaxSec` ≤ 16:43:00Z, W8); `::test_recon_units_use_own_lock_not_studies_flock`; `::test_recon_units_memorymax_within_own_lock_budget`.
- **GREEN.** First day: 48 intraday verdicts (or journal lines pre-policy-block), one post-STOP verdict before 16:43Z, Z19 line.
- **Activation.** Immediate on merge; coordinator installs both timers. No node or supervisor restart.

---

## 5. Association

**Consumed:**

| Contract | From | What AUT-2 uses | Fallback before it lands |
|---|---|---|---|
| C2 schema, C4 writer, C6 Protocols, `RefusingPlugin`, `OFFLINE_PLUGINS`, `pins.py` | ARCH-0 | Types, registry, verdict writer, `MAX_VERDICT_VALIDITY_H` | WP1 needs none; WP2+ wait |
| **C2 widening (Rev 5, §10 C-1)** | ARCH Rev 5 | `slippage_defect`, `voided_pair`, `venue_fallback_settlement`; `p_source`, `p_null_reason`; nullable `settled_outcome`/`realized_pnl` for pending fallback | **None: no label write until it lands (A7)** |
| C1 records | AUT-1 | Attribution (a), p, settlement sha | Pre-C1 bridge (§3.4.4) |
| C5 fold at `ts_event`, bound sha, voided intervals | AUT-5 | Attribution (b), voided pairs, verdict subject | Manifest intervals (§3.4.2 (c)); manifest sha |
| Compose-time refusal | AUT-5a | WP7 cross-plan test (A10) | WP7 does not merge |
| `autonomy-policy/v1` | AUT-5b | action class, ruling sha, horizons 26 h / 8 h, post-STOP acceptance rule | No verdict file; alerts and journals run |
| `deliver_with_proof` | AUT-6 | CRITICAL delivery | Interim; not score-3 evidence |

**Provided:**

| Contract | To | Guarantee |
|---|---|---|
| C2 labels `derived/labels/<family_id>/` | AUT-3, AUT-4 | Written by 14:45Z; consumers gate on `label_outcomes_ok_<date>.json` and **treat `pending > 0` as GATED**; only `admissible=True` counts; `p_at_decision` = P(bought leg wins) |
| C4 `RECONCILIATION` daily (26 h) | AUT-5 (§4.4 for PROMOTE-time checks; ATTEST input) | INCONCLUSIVE never passes |
| C4 `RECONCILIATION` + `HEALTH` intraday (8 h, every 30 min) | AUT-5 ATTEST (W1) | Cadence row satisfying the invariant (§3.11) |
| C4 `RECONCILIATION` post-STOP | AUT-5 pre-launch pass (W8) | Produced 16:41–16:43Z, `produced_at_ns ≥ STOP_ns(D)` |
| C4 `HEALTH` `aut2.label_lag`, `aut2.label_coverage` | AUT-6, AUT-5 | Daily and intraday |
| Drill rows (`drill=true`) in C2 | AUT-6 detectors, AUT-5 drawdown (W12) | Present, never dropped |
| `net_signed_qty` | AUT-5 `entry_guard` | One netting rule |
| Z19 metric | AUT-5 policy review | Direct 16:41Z observation |

**Order and parallelism.** WP1 now. After Wave 0 + Rev 5 C2 widening: WP2 → WP3 → {WP4, WP5, WP8} → {WP6, WP9}. WP7 after AUT-1 C1 and AUT-5a. File ownership disjoint from Wave 1 siblings: AUT-2 never edits `app/trade.py`, `settings.py`, `trade_supervisor*.py`.

---

## 6. Live-proof protocol

- **Artefact.** `evidence/aut2_live_proof/window_<start>_<end>.json`, written by `label_run --proof-window` from the stores (never by hand). Per qualifying day: real attributed fill count; final-labelled count (must equal); completeness identity counts with `unattributed == 0`; non-null C1 `p_at_decision` count (equal after WP7); daily RECONCILIATION verdict id and PASS; post-STOP verdict id and PASS; intraday verdict count and any non-PASS ids; max label lag (≤ 24 h); `fills_never_position_compared == 0`; canary fields per §3.8. Window totals: real fills (≥ 5), NO-leg fills, exits; marker files and systemd invocation ids.
- **Window rule.** A day qualifies with ≥ 1 real fill, or as a canary day under §3.8 (A12). Zero-fill non-canary days extend. Canary and drill fills never count toward ≥ 5. Start: first UTC day after WP1–WP6, WP8, WP9 active **and** AUT-6 delivery live. A day with any `pre_c1_log_unmatched` fill does not qualify and restarts the window.
- **NO leg and exit.** "If one occurs": listed, or `no_leg_fills=0`, `exit_fills=0` with capability shown (FQ has no exit, G17).
- **ETA.** ~5 FQ fills/day. Wave 0 + Rev 5 by ~10-08; WP2–WP6, WP8, WP9 by ~10-14; window 10-15..10-21; last settlements 10-23 12:00Z, labelled 14:15Z → **earliest 2026-10-23; plan 2026-10-30**. DST 11-02 moves settlement to 13:00Z, still covered.
- **Evidence class.** "Machinery proven, edge unproven."

---

## 7. Score-3 verification checklist

| Criterion | Check |
|---|---|
| (a) unattended | `journalctl --user -u breezy-label-outcomes.service -u breezy-aut2-reconciliation.service -u breezy-aut2-reconciliation-poststop.service --since <window>`: only timer starts. Invocation ids in the artefact. `git log --since <window> -- src/breezy/analysis/labeling deploy/systemd/*label* deploy/systemd/*aut2*` empty. |
| (b) family-agnostic | `scripts/ci/run_tests_no_egress.sh -k "aut2_scorer_registration or iterates_offline_plugins or family_plugin_exact_set"` passes (includes A10 compose test). `/usr/bin/grep -n "pm_us_" src/breezy/analysis/labeling/*.py` → 0 hits. |
| (c) fails closed | Tests `refusing_plugin_for_non_retired_family_fails_run_no_marker`, `unreadable_exec_store_exits_nonzero_without_marker`, `deleting_one_label_fails_identity`, `venue_slug_without_ledger_fill_fails`, `every_fill_position_compared_before_settlement_else_fail`, `incomplete_snapshot_inconclusive`, `every_outcome_wrapper_exits_nonzero_on_genuine_failure`, `absent_markers_still_refuse`. |
| (d) detected, alerted, delivered | `evidence/alerts/delivery_<date>.jsonl` holds `delivered=true` for an injected `aut2.label_lag` (WP5 drill: tmp HOME fill past the venue settlement instant with no CLI final, production entrypoint, real endpoint). |
| (e) RED→GREEN | Per-WP artefacts; gate EXIT=0 after each merge; `lint-imports` `kept, 0 broken`. |
| (f) live proof | `evidence/aut2_live_proof/window_*.json`: 7 qualifying days, ≥ 5 real fills, identity holds with `unattributed == 0` daily, every daily and post-STOP verdict PASS; ids resolve under `derived/verdicts/pm_us_crh_fq_v1/<date>/`. |
| Horizons | `test_label_lag_horizon_pinned_under_max_verdict_validity`, `test_intraday_cadence_fits_attest_invariant`, `test_post_stop_slot_ends_before_1645Z`. |
| Root cause | `docs/evidence/AUT-2_rc_monitor_pnl_2026-10-03.md` (incl. A17); FQ monitor report `positions: 0`, `NO_MONITOR_FOR_KIND`. |
| No expected failures | `systemctl --user list-units --state=failed 'breezy-*'`: no outcome unit in the window; both `test_outcome_units_no_expected_failure` tests pass. |
| Z14 / Z19 | `test_aut2_canary_isolation` (with positive controls); journal line `Z19 ambiguous_open_at_1645Z days=` from each post-STOP run. |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| Bridge mislinks a Take | `client_order_id` + `trade_id` join with bounded windows (A16); exactly one Take; else unmatched (null p, day does not qualify). Retired to a cross-check in WP7. |
| Positions pull races trading | `ts_event ≤ snapshot_ns` fencing; OPEN/AMBIGUOUS intent → UNKNOWN; post-STOP snapshot has no node running. |
| Pagination truncates the page (false venue-only/zero) | Cursor to `eof`; `complete=false` → INCONCLUSIVE, never compared. |
| Settled position leaves the page (L-52) | Settled-away slugs compared only on settlement and cash legs; coverage rule (A4) guarantees a pre-settlement comparison. |
| Venue rate limit from 49 GETs/day + pages | Reuses the capture's `quota_key`; a 429 is a recorded outcome → INCONCLUSIVE for that slot, alert after the INCONCLUSIVE rule; never retried in a loop. |
| Post-STOP producer late or dead | Pre-launch preconditions fail → SWAP_CANCEL; incumbent unaffected (§4.4); CRITICAL via `OnFailure=`. |
| Exec-store read with node stopped | Precedent `probe_open_intent`; RED `test_fill_source_reads_wal_store_after_writer_exit`; a read failure is exit 1, never NO_INPUT. |
| C2 widening slips | Label writes blocked (A7). WP1 still lands; the proof ETA moves; no workaround that writes reasons into logs. |
| Retired-family scorer conflict with C6 YAGNI | §10 C-6 raised for Rev 5; until resolved, no FQ family can be RETIRED with unlabelled fills without the gate failing loudly (CRITICAL), never silently. |
| Memory (30 GiB host) | Label run measured precedent 137 MB, `MemoryMax=1G` studies flock; reconciliation units 512M own lock (two of them never overlap: same lock). No heavy job 01:00–04:30Z. |
| Shared venv | Briefs name `/home/jon/breezy/.venv/bin/python`; no `uv`, `pip`, `uv run` (L-51). |
| Concurrent agents | Disjoint file ownership; per-agent scratchpads; no `git stash`; worktrees fast-forwarded first. |
| Gross/net split hides a cash loss | Net flag needs flows `OK`; otherwise INCONCLUSIVE; two consecutive → CRITICAL (A4). |
| Statistical capacity | Not an AUT-2 claim; ≥ 5 real fills in ~1–2 days. |
| KILL 2027-01-25 | After TERMINAL KILL: labels continue for remaining settlements, NO_INPUT runs exit 0, proof window pauses. ETA 10-23..10-30 is well before. |
| NWS outage / late final | Rows pending; label lag measured from the venue settlement instant → HEALTH FAIL at 24 h (A2); no nearby-station substitution. |
| Kalshi family admitted | TWC source refuses; gate fails until a reviewed TWC reader exists. |

---

## 9. Binding-constraint compliance

- **Nautilus immutability.** No Nautilus file touched; native `ClientOrderId`/`TradeId` joins and its event log lines are only read.
- **The two caps.** Never read, written or derived; `test_autonomy_never_reads_or_writes_operator_controls` covers `analysis/labeling/`.
- **`allow_short=False`.** Untouched; "short YES" is the venue's reporting convention, read only.
- **NO-SEND.** Label and recon analysis make no network call. The positions pull is GET-only through the existing capture and `assert_get_only` (allowlist imported from `signing.py`), pinned by `test_not_an_execution_egress_module`. `test_execution_egress_firewall_guard` is not edited.
- **Master enablement and permit.** Never read or written; offline units; no supervisor or node change.
- **PREREG via ruling.** No statistical semantics defined; horizons and action classes enter the verdicts only from the AUT-5 policy block.
- **Safety tests never weakened.** `absent_markers_still_refuse` kept; every settlement, contract and NO-SEND test unchanged; legacy store and barrier tests untouched; new positive controls strengthen the canary and wrapper tests.

---

## 10. Contradictions with ARCH (for the Rev 5 merge)

- **C-1 (C2 widening, L-12; hard prerequisite).** C2's `excluded_reason` lacks `slippage_defect` (A7), `voided_pair` (W14 needs it, but Rev 4 C2 does not list it), `venue_fallback_settlement` (A9); C2 says `p_at_decision` is "nullable only with a reason" but names no reason column. Request: add the three enum values; add `p_null_reason ∈ {pre_c1_log_unmatched}` and `p_source ∈ {c1_decision_record, node_log_take_line}`; allow null `settled_outcome`/`realized_pnl` only with `excluded_reason = window_incomplete` and `settlement_basis = venue_last_fair_price_fallback`; state that `p_at_decision` is P(bought leg wins). `unattributed` is **not** requested as an enum value: an unattributed fill has no family and writes a durable journal row plus HEALTH instead (A7).
- **C-2 (slot).** ARCH §5.2's indicative 05:00Z label slot cannot label the prior day; 14:15Z primary, 05:00Z catch-up (§3.10).
- **C-3 (producer scope).** ARCH §5 gives AUT-2 only C4 `RECONCILIATION`; C2's invariant and W1 require AUT-2 `HEALTH` (`aut2.label_lag`, `aut2.label_coverage`), daily and intraday. Rev 5 should add `HEALTH` to AUT-2's §5 row.
- **C-4 (Z19 source).** Resolved in r2 by the post-STOP direct observation (§3.9); only the backfill depends on `created_ns`.
- **C-5 (F4).** The FQ manifest's `trial_id_prefix` matches no stored key; scorers must not use it for discovery.
- **C-6 (new; C6 YAGNI versus retired-family labeling, A13).** C6 says "a kind with no non-RETIRED family registers `RefusingPlugin`", and the gate requires `OFFLINE_PLUGINS` to refuse for such kinds. A13 requires labelling a RETIRED family until its last fill is labelled. When the last FQ family retires with settlements outstanding (e.g. after the 2027-01-25 KILL), C6 would swap the FQ Scorer for `RefusingPlugin` and leave live fills unlabelled. Request: `RefusingPlugin`'s refusal covers compose, mint, `Evaluator` and `Refitter`, while the `Scorer` member stays the kind's real scorer as long as any family of that kind has an attributed durable fill without a final label; the gate test becomes "every kind with an unlabelled fill resolves to a non-refusing `Scorer`". Today's CRH kinds are unaffected (legacy store coverage, §3.12).
- **C-7 (W8 wording).** ARCH §4.4 says "an accepted RECONCILIATION PASS within its horizon"; W8 defines the pre-launch horizon as "produced after STOP that day". Rev 5 should state that this rule applies to the pre-launch pass only, and that PROMOTE-time checks at 15:30Z use the daily (26 h) or intraday (8 h) horizons.

---

## 11. Self-score (author's estimate; not evidence)

| Axis | Max | Score | Note |
|---|---:|---:|---|
| Fidelity | 20 | 18 | Every README bullet, §10 obligation, Z14/Z19 and W1/W8/W12/W14 mapped; deviations declared (C-1..C-7). |
| Correctness | 20 | 17 | A5 conversion, A8 tolerance argument and the exec-store post-STOP read verified in code; A17 partly INFERRED (the MIA NO absence) and A9 payout source INFERRED, each behind an L-1 step. r1's positions-pull rebuild and canary path were wrong and are corrected. |
| Specificity | 15 | 14 | Constants, slots, locks, limits, paths, test names and the completeness partition are explicit. |
| Acceptance | 20 | 17 | Checklist commands exist; score 3 depends on the Rev 5 C2 widening, AUT-5a and AUT-6, all named as prerequisites. |
| Autonomy-safety | 15 | 14 | Fails closed; post-STOP producer cannot deadlock launch; no caps, permit or firewall surface; positive controls added. |
| Reuse | 10 | 9 | `score_trial`, settlement clock, `reconcile_daily`, `bucket_ledger_fills`, positions capture, `probe_open_intent` precedent, node log. |
| **Total** | **100** | **89** | Reviewer-scored r1 was 80; r2 closes every r1 finding but adds new ARCH dependencies (C-1, C-6). |

---

## §R2 Disposition (review `reviews/AUT-2-r1-merged.md`)

| ID | Status | Where / evidence |
|---|---|---|
| A1 | FIXED | §3.12 completeness partition and identity with `UNATTRIBUTED == 0`; legacy CRH fills counted via `bucket_ledger_fills` (`portfolio_roi_report.py:573`); `test_labelled_plus_excluded_equals_durable_count` + positive control `test_deleting_one_label_fails_identity` (WP2); daily metric and proof field (§3.7.1, §6). |
| A2 | FIXED | §3.7.2: lag clock starts at `settlement_deadline_ns` (`registry/settlement_clock.py:36`), stops only on an admissible or final-excluded label; `window_incomplete` > 48 h → FAIL (§3.5); every live `fee_unreconciled` alerts (§3.5); `test_no_cli_final_fails_label_lag_at_24h_from_venue_settlement` (WP5). |
| A3 | FIXED | §3.12: NO_INPUT only with `pending == 0`; PENDING outcome; marker carries counts; consumers GATED on `pending > 0` (§3.10, §5); unreadable store → exit 1, no marker; WP6 tests. |
| A4 | FIXED | §3.6 coverage rule (last complete snapshot after fill and before settlement; none → FAIL); 30-min snapshots (§3.11); stale snapshot → INCONCLUSIVE + alert; `fills_never_position_compared` metric; 2 consecutive INCONCLUSIVE or BALANCE_UNKNOWN days → CRITICAL; WP5 tests. |
| A5 | FIXED | §3.4.4: `p_hat` is P(YES rung) in both side modes (`fq/decision.py:349`, `ladder_ev/scoring.py:82`); `p_at_decision = 1 − p_hat` for NO; NO-leg tests in bridge and C1 modes (WP3). |
| A6 | FIXED | §3.6 position leg: compared set = ledger ∪ page; venue-only slug FAIL; open ledger slug missing → venue 0; "open" from `settlement_deadline_ns` and `expired` (SDK `types/portfolio.py:30`); cursor-complete snapshots; WP5 tests. |
| A7 | FIXED | §3.5 `slippage_defect` persisted as `excluded_reason`; `write_labels` refuses until the Rev 5 enum lands (§10 C-1, hard prerequisite in §0/§5); unattributed → durable journal + HEALTH (§3.4.2). |
| A8 | FIXED | §3.6 cash leg: cumulative net identity via `reconcile_daily`/`cumulative_reconciliation`, open cost held out; tolerance argument = fills **opened** (`per_day_tolerance(fills_opened_that_day)`, `:1390`; `_fills_opened_count_by_day`, `:1110`); mixed-day test (WP5). |
| A9 | FIXED | §3.5 fallback: null `realized_pnl`, pending until the `PositionResolution` payout is read, then final `venue_fallback_settlement`; WP3 test; L-1 (iv). |
| A10 | FIXED | §3.3 and WP7: `test_armed_family_with_refusing_scorer_is_refused_at_compose`, owned by AUT-2, hard prerequisite AUT-5a (§0, §5). |
| A11 | FIXED | §3.5 fee-inclusive `cost_basis`; WP4 pro-rata formulas and `test_partial_no_leg_exit_pro_rata_fee_inclusive`. |
| A12 | FIXED | §3.8 explicit canary-day verdict (canary PASS + real RECONCILIATION PASS); a canary never satisfies the live-fill check (`live_fill_check="vacuous"`); WP8 tests; §6. |
| A13 | FIXED | §3.4.2 attribution by status at `ts_event` (fold, or manifest `[d0, terminal]` pre-C5); retired families stay in the run set until their last fill is labelled; RED tests in WP2; C6 conflict raised as §10 C-6. |
| A14 | FIXED | §3.8 AST and runtime positive controls; WP6 `test_every_outcome_wrapper_exits_nonzero_on_genuine_failure`. |
| A15 | FIXED | §3.7.2 `LABEL_LAG_MAX_H = 24` in `constants.py`; `test_label_lag_horizon_pinned_under_max_verdict_validity` asserts ≤ `MAX_VERDICT_VALIDITY_H` (26). |
| A16 | FIXED | §3.4.4 bridge keyed on `client_order_id` + `trade_id`, bounded windows (2 s, 300 s), verified on log lines 8359/8361/8393; adjacency never used; WP3 tests. |
| A17 | FIXED | §3.1 item 5: rows are monitor summaries (`_join`, `:539-586`); one live summary file holds only SFO YES; MDW NO filled in a session with no summary file; MIA NO absence INFERRED and resolved in WP1's note; `test_scored_trial_without_summary_is_not_a_row`. |
| A18 | FIXED | §3.9: Z19 `unknown` is a metric only until AUT-5a journaling; `test_z19_unknown_is_metric_not_alert` (WP5). |
| W1 (ARCH) | FIXED | §3.11 intraday mode, 8 h validity, 30-min cadence, carry-forward of the daily verdict, invariant row and test; WP9; §5. |
| W8 (ARCH) | FIXED | §3.11 post-STOP mode at 16:41Z, own lock, ends ≤ 16:43Z; §4.4 horizon "produced after STOP that day"; no-deadlock behaviour; WP9; §10 C-7. |
| W12, W14 (consumed) | FIXED | §3.8 drill rows retained for detectors and drawdown; §3.4.2 voided-pair attribution with `voided_pair`. |

Counts: 18 of 18 A-items FIXED, 0 REJECTED; ARCH deltas W1, W8 FIXED; W12, W14 absorbed.

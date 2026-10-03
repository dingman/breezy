# AUT-2: outcome labeling (scoring, P&L, reconciliation). Plan r4

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-2, delivered as **AUT-2a** (Wave 1) and **AUT-2b** (Wave 2) per ARCH §5.1, plus one Wave 0 egress dependency (WP0) |
| Title | Outcome labeling: family-agnostic scorer, C2 label store, net-position and cash reconciliation |
| Round | r4 (2026-10-03). This round is the final rebase. It disposes Q1–Q4 of `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-2-r3-merged.md` and the rebase changes RB-1..RB-16 (§R4). r3 (`docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r3.md`) is unchanged. |
| ARCH consumed | **FROZEN Rev 9.2**, `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`, sha256 **`1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`** (re-hashed 2026-10-03 and matched to the README Items table), plus `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md` (E-1..E-4). No AUT-2 obligation changes under E-1, E-2 or E-4. The plan reads Rev 9.2 change tags as `R9.2-Z1…Z9` (E-3). No older snapshot is cited. |
| Coordinator decisions | `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/{HOLDOUT,ALPHA,ROLLBACK-FAILURE}-decision.md`, all binding. See §9. |
| Repo state read | `4b8347a6` on `feat/data-capture-and-risk`; live artefacts under `/home/jon/.local/share/breezy/` as of 2026-10-03 |
| Current score | 1 (README) |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: `src/breezy/persistence/autonomy/` schemas including C2 `label/v1`, the C6 Protocols, `RefusingPlugin`, `pins.py` with `MAX_VERDICT_VALIDITY_H`, `ATTEST_VERDICT_VALIDITY_H`, `INTRADAY_ATTEST_VERDICT_PERIOD_MIN`, `POST_STOP_RECONCILE_RUNTIME_S`, `POSTSTOP_POSITIONS_MAX_PAGES`); **AUT-1a** (C1 library and reader, `capture_epoch.py`, the settlement writer); **AUT-1b** (node C1 writes and the `capture_epoch_start` write: **gates WP7 and the proof window**, Q4); AUT-6 (`deliver_with_proof`, `src/breezy/runtime/alert_delivery.py`); AUT-5a (compose-time refusal at `src/breezy/app/trade.py:853`; the journaled STOP-completion signal; the C5 fold); AUT-5b (the `autonomy-policy/v1` block) |
| Downstream | AUT-3 (C2 rows with `admissible ∧ p_source=c1_decision`); AUT-4 (the same, plus champion slippage); AUT-5 (C4 `RECONCILIATION` daily, intraday and post-STOP; ATTEST inputs, W1; §4.4 pre-launch input, W8; `net_signed_qty` for `entry_guard`); AUT-6 (C4 `HEALTH label_lag`; C2 drill and voided-pair rows, W12; the portfolio-roi scorer status for its unit-exit semantics, P6-9) |

---

## 1. Goal state

**README AUT-2 score-3 criterion (verbatim, `docs/plans/backlog/AUTONOMY_2026-10-03/README.md:92-97`):**
- Scoring is a family-agnostic scorer contract. A family manifest cannot register or send without a scorer, enforced by a registration-time test.
- Every fill, entry or exit, YES or NO leg, is labelled automatically within 24 h of settlement with: the settled outcome, the realised P&L net of the reconciled fee, the forecast probability at decision, and the counterfactual hold result for exits.
- Labels are reconciled against venue settlement and balance evidence within a stated tolerance.
- Sign and leg conventions are pinned by tests: the venue nets a NO holding as short YES.
- No unit fails as a matter of expected behaviour.

**README AUT-2 live proof (verbatim):** "every live fill over 7 consecutive days is labelled, with reconciliation passing on each day, covering at least one NO-leg fill if one occurs and at least one exit if one occurs. All of it is run by the timers with no hand step."

**ARCH Rev 9.2 §10 AUT-2 obligations (verbatim, `ARCH_rev9_2.md:1204-1211`):** "the −0.37/+0.37 root cause with artefact evidence before any scorer change; the per-leg reconciliation tolerance; the intraday RECONCILIATION producer (cadence within the W1 invariant) and the post-STOP producer (§4.4: STOP signal, venue snapshot source, runtime bound); exclusion of `canary`, `drill` and `voided_pair` rows; the canary store's `Scorer` input (Z14); the label-lag alert; the measured rate of AMBIGUOUS intents open after STOP, from the post-STOP producer (Z19, P2-4); attribution via C1 only (P2-5); `p_source`; the 14:15Z and 05:00Z slots (P2-2); the `portfolio-roi` scorer (P6-9); bought-leg `p_at_decision` (P3-9); the retired kinds' real `Scorer` until their last fill is labelled (P2-6); `TimeoutStartSec` on its oneshots (r3 lists `RuntimeMaxSec`) and the §5.2 reconcile-lock rows; the post-STOP GET-only positions read and its Wave 0 egress review (V13, U4), also the intraday venue-net source (U5)."

**Section map.**

| Obligation | Where |
|---|---|
| Root cause | §3.1, WP1 |
| Per-leg tolerance | §3.6 |
| Intraday producer and W1 cadence | §3.11, WP9 |
| Post-STOP producer (STOP signal, snapshot source, runtime bound) | §3.11 steps 1–6, WP9 |
| `canary`, `drill`, `voided_pair` exclusion | §3.5, §3.8 |
| Canary `Scorer` input | §3.8, WP8 |
| Label-lag alert | §3.7.2 |
| Z19 | §3.9 |
| Attribution via C1 only | §3.4.2 |
| `p_source` and `p_raw_at_decision` | §3.4.4 |
| Slots | §3.10 |
| portfolio-roi scorer | §3.10, WP1, WP6 |
| Bought-leg p | §3.4.4 |
| Retired kinds' real `Scorer` | §3.3 |
| `TimeoutStartSec` and the reconcile-lock rows | §3.10, WP6, WP9 |
| GET-only positions read and its Wave 0 review | §3.2.1, WP0 |
| Intraday venue-net source | §3.6.1, §3.11 |

---

## 2. L-1 null hypothesis and reuse

Nautilus has no settlement scorer, no label store and no venue-versus-ledger reconciliation for an offline process. `Position.realized_pnl` covers only the node's in-process lifetime and misses settlement payouts that arrive after the node stops, so it is not a label source. The exec client's netted entry price is the net remaining cost (`src/breezy/adapters/polymarket_us/exec/client.py:4495-4549`). It conserves lifetime P&L but is not a per-label cost basis (Q3, §4 WP4).

| New component | Checked against | Verdict |
|---|---|---|
| C2 label store, `src/breezy/persistence/autonomy/label_store.py` | `src/breezy/persistence/scored_trial_store.py:24-31,60-89`; `ScoredTrial` (`src/breezy/settlement/trial_scorer.py:131-160`); ARCH C2 `label/v1` | **Implement ARCH's pinned `label/v1`** using the G8 conventions: parquet, atomic `os.replace`, `(label_id, max label_seq)` dedupe. AUT-2 adds no column. |
| Settlement resolution, including the venue fallback | `score_trial` (`trial_scorer.py:167-231`); `_resolve_settlement_basis` (`:234-265`, fallback branch `:247-255`); `_SEVEN_DAYS_NS` (`:56`); `read_climate_day_including_corrections` (`src/breezy/persistence/catalog.py:637`) | **Reuse unchanged.** AUT-2 maps the scorer's `settlement_basis` and `excluded_reason` and never evaluates the trigger itself (§3.5). |
| Venue settlement instant | `default_registry().settlement_deadline(venue, city)` (`src/breezy/registry/sites.py:413`); `settlement_deadline_ns` (`src/breezy/registry/settlement_clock.py:36`) | **Reuse.** No new clock arithmetic. |
| `SettlementRecord` | ARCH C1; AUT-1a settlement writer, `decisions/settlement_<YYYY-MM-DD>.jsonl` | **Consume** for the label-lag clock (§3.7.2) and for the `raw_sha256` cross-check (WP7). |
| Rung facts from the slug | `_read_bucket_facts_by_instrument_id`, `_bucket_facts_from_instrument_id` (`scripts/analysis/score_live_trials.py:579,620`) | **Reuse** through a pure move into `src/breezy/analysis/labeling/instrument_facts.py`, re-imported by the script with byte-identical behaviour (L-46). |
| Leg netting | `leg_of_symbol` (`src/breezy/domain/instrument_leg.py:58`); `base_slug_of`, `leg_of` (`src/breezy/adapters/polymarket_us/symbology.py:289-298`) | **Reuse.** `net_signed_qty` is defined once in `src/breezy/persistence/autonomy/net_position.py` and imported by AUT-5 `entry_guard` (ARCH C5 W6). It imports no `breezy.adapters` (contract `persistence.autonomy ↛ adapters`). |
| `trial_id` (P2-5) | `TrialDayLatch._trial_key` (`src/breezy/strategy/current_rung_hold/trial_day_latch.py:775`); FQ composite key `_composite_key` (`src/breezy/strategy/forecast_quantile_ladder/persistent_latch.py:87-94`) under `FORECAST_QUANTILE_TRIAL_KEY_PREFIX` (`:68`); G28, G35 | **Reuse.** `trial_id` is the stored latch key read through the G6 URI and is never built from `trial_id_prefix`. |
| Per-label cost basis (Q3) | `_entry_price_from_records` (`exec/client.py:4495-4549`): Σ signed cost / Σ signed qty with SELL records netted, i.e. **net remaining cost**, which conserves lifetime realized P&L (`:208-220` worked example: BUY 4@0.50, SELL 1@0.60, lifetime 1.60 at a 1.00 payoff); `reconcile_daily` is matching-free (`scripts/analysis/portfolio_roi_report.py:445-468,1043-1088`) | **New, minimal:** `average_cost_basis` uses the standard weighted-average cost method. Its per-label basis intentionally differs from the exec client's `avg_px_open`. Lifetime identity pinned (§4 WP4). |
| Durable fill reader | `DurableFillRecord.from_bytes` (`exec/client.py:1004-1066`); `FILL_KEY_PREFIX` (`:408-415`); G6 `mode=ro` URI (`trial_day_latch.py:354-379`) | **Reuse** in `src/breezy/analysis/labeling/fill_source.py`; the analysis layer may import adapters (G15). AUT-5's `FillReader` (ARCH C5 W6) is exact-key only and has no scan, so it is not usable for a full-universe read. |
| Exec-store read with the node stopped | `probe_open_intent` (`src/breezy/runtime/trade_supervisor.py:402-420`) after `assert_no_live_node_before_intent_probe` (`src/breezy/runtime/trade_supervisor_core.py:554-560`); `find_pid_by_argv(NODE_ARGV_ANCHOR)` (`trade_supervisor.py:531-548`; anchor `trade_supervisor_core.py:81`) | **Reuse both by import** (analysis sits above runtime, `pyproject.toml:78-99`). No copy. |
| **Venue positions read (RB-2)** | ARCH §4.4: `src/breezy/runtime/venue_positions_read.py`; `PolymarketUSHttpClient.get_authenticated` (`src/breezy/adapters/polymarket_us/http.py:152`), `PERMITTED_METHODS = {"GET"}` (`http.py:69`); `PolymarketUSReadTransport` with no method parameter (`src/breezy/adapters/polymarket_us/transport.py:168-177`); `PORTFOLIO_POSITIONS_PATH` (`src/breezy/adapters/polymarket_us/exec/endpoints.py:97`); `_validate_endpoint` (`scripts/venue/polymarket_us_shape_capture.py:573`); `config_from_env` (`src/breezy/adapters/polymarket_us/factories.py:241`); `load_polymarket_us_credentials` (`src/breezy/adapters/polymarket_us/env.py:94`); capture pattern `scripts/venue/polymarket_us_positions_value_capture.py:191-279` | **New module as ARCH specifies** (WP0, Wave 0). It is a reviewed egress dependency that reuses the existing GET-only client. It never uses the capture script's operator-only `prepare`. r3's `scripts/venue/polymarket_us_positions_pull.py` is withdrawn. |
| Legacy CRH fills and cash | `bucket_ledger_fills` (`portfolio_roi_report.py:536-597`); `_fee_unverified_fills_deduped` (`:650`); `reconcile_daily` (`:1618-1865`); `capital_deployed_by_day` (`:1096`); `ResidualSettlement` (`:1146`); `proceeds_by_day` (`:1341`); `per_day_tolerance` (`:1390`); `cumulative_reconciliation` (`:1986`); frozen CRH `ScoredTrial` stores | **Reuse unchanged** for cash. C2 cash enters through the existing `residual_settlements` parameter. CRH kinds get a real `Scorer` that maps the frozen `ScoredTrial` records into C2 rows (P2-6; §3.3). |
| Venue settlement and netting evidence | Tape `custom_venue_settlement_snapshot`; SDK `PositionResolution` (`sdk_snapshot/.../types/portfolio.py:68-76`) read by the existing capital-flow pull's `account_activity.py` | **Reuse** the existing artefacts. Field use is **INFERRED** behind WP5 L-1 (iv) and (vii). |
| Pre-epoch p (backfill only) | `SHADOW_DECISION` line (`src/breezy/strategy/forecast_quantile_ladder/strategy.py:577-581`; `decision_log_fields`, `fq/decision.py:178-213`); Nautilus `OrderInitialized`/`OrderFilled` lines (verified in `breezy-trade-20261002T205521Z.log` lines 8359, 8361, 8393) | **Reuse the bot's own output** (L-2). Rows are written as `p_source=artefact_recompute` and are never admissible (§3.4.4). |
| C4 writer, payload hygiene | Wave 0 C4 writer; `AlertPayload` (`src/breezy/registry/health_model.py:217-235`) | **Consume.** |
| CRITICAL delivery | `deliver_with_proof(sink, payload) -> DeliveryProof` (ARCH §4.6, AUT-6) | **Consume.** No second delivery path. |
| Units | `deploy/systemd/score-live-trials-run.sh`, `deploy/systemd/portfolio-roi-run.sh` (studies flock and marker idioms); `deploy/systemd/breezy-score-live-trials.service:76` (`TimeoutStartSec` precedent, G32) | **Reuse the idioms** in the AUT-2 wrappers. AUT-2 does not edit those two wrappers; AUT-6 owns them (RB-11). |
| Monitor scoping (WP1) | `resolve_trial_family` (`scripts/analysis/position_monitor_nightly_report.py:132-165`) | **Reuse** as the filter predicate. |

---
## 3. Design

### 3.1 Root cause of −0.37 versus +0.37 (WP1 commits the evidence note)

1. Every 2026-10-02 monitor report shows the same single row: `positions: 1 (settled 1)` and `SETTLED ... n=1 realized_pnl_total=-0.3700`. The reports are `position_monitor_report_2026-10-02_pm_us_crh_{v4,v2,cont,fq_v1}.md`.
2. That row is the v4 trial `continuous_rung_hold/trial/SFO/2026-09-21/tc-temp-sfohigh-2026-09-21-gte66lt67f.POLYMARKET_US` (YES; `pnl=-0.3700`) in `/home/jon/.local/share/breezy/derived/scored_trials/pm_us_crh_v4/scored_trials_20260922T141816645708220Z.parquet`.
3. **Mechanism.**
   - `main` passes every summary and every pooled scored trial into `build_monitor_report` (`scripts/analysis/position_monitor_nightly_report.py:862-925`).
   - `--family-manifest` only stamps `RuleSeries.family` (`_exit_rule_series`, `:698-742`).
   - Nothing filters by family, and the wrapper runs once per REGISTERED manifest (`deploy/systemd/position-monitor-report-run.sh:206-209`).
4. The v4 tally's `total pnl 0.3700` is the sum of three v4 fills: MIA NO 09-21 −0.13, SFO YES 09-21 −0.37 and MDW NO 09-22 +0.87.
5. **Why only one of the three v4 fills is a monitor row.**
   - Report rows are monitor summaries. `_join` (`:539-586`) iterates the summaries and settles each one from a joined `ScoredTrial`, so a scored trial with no summary never becomes a row.
   - `read_monitor_summaries` (`src/breezy/persistence/monitor_store.py:262-278`) finds exactly one live summary file, the 09-22 16:40Z STOP flush. Its only 09-21/09-22 row is the SFO YES trial.
   - MDW NO 09-22 filled in a later session that wrote no summary.
   - Why MIA NO 09-21 is absent from that flush is **INFERRED**; WP1 records the verified mechanism.
6. **Verdict.** There is no sign error; the defect is attribution. FQ has zero scored fills and composes no `PositionMonitor`.

**Further findings, each handled by a WP:**
- F2: `portfolio-roi` exits 1 every day. Unit exit semantics belong to AUT-6 (P6-9). AUT-2 supplies the scorer status (WP1, WP6).
- F3: 09-30 gross versus net (WP1, WP5).
- F4: FQ `trial_id_prefix` matches no stored key (G35; §3.4.3).
- F5: the latch is not a fill join key (WP2).
- F6: exit fills are never evaluated, and `reconcile_daily` excludes SELLs (WP4, WP5).
- F7: 11 durable FQ fills, 5 of them settled and unlabelled (WP3 backfill).

### 3.2 Package layout (analysis layer, never imported by a live package; one runtime read module)

```
src/breezy/runtime/
    venue_positions_read.py  read_venue_positions(), validate_endpoint() (moved public), POSITIONS_LITERAL   [AUT-2 WP0, Wave 0; ARCH §4.4]
src/breezy/persistence/autonomy/            (Wave 0 owns schemas.py, plugin.py, pins.py)
    label_store.py      write_labels(), read_labels(), labels_consumable(marker)                      [AUT-2]
    net_position.py     net_signed_qty(fills), average_cost_basis(fills, at_ns)                       [AUT-2; imported by AUT-5 entry_guard]
    canary_store.py     CANARY_ROOT, append_canary_fill(), read_canary_fills()                        [AUT-2, Z14]
src/breezy/analysis/labeling/
    constants.py        LABEL_LAG_MAX_H=24, WINDOW_INCOMPLETE_MAX_H=48, RECON_DAILY_VALIDITY_H=26,
                        RECON_INTRADAY_VALIDITY_H=8, INTRADAY_PERIOD_MIN=30, SNAPSHOT_MAX_AGE_MIN=45,
                        INCONCLUSIVE_ALERT_DAYS=2, BRIDGE_TAKE_TO_INIT_MAX_S=2, BRIDGE_INIT_TO_FILL_MAX_S=300,
                        POSITION_SETTLE_GRACE_S=60,
                        LABEL_FLOCK_WAIT_S=600, LABEL_TIMEOUT_START_S=1800,
                        RECON_INTRADAY_FLOCK_WAIT_S=30, RECON_INTRADAY_TIMEOUT_START_S=240,
                        POST_STOP_FLOCK_WAIT_S=20, POST_STOP_TIMEOUT_START_S=100        (Q1)
    instrument_facts.py extracted from scripts/analysis/score_live_trials.py (pure move)
    fill_source.py      read_durable_fills(db_path) -> FillRead(fills, n_keys, n_undecodable)
    epoch.py            fill_epoch_class(fill, epoch_reader) -> POST_EPOCH | PRE_EPOCH   (reads AUT-1 capture_epoch_start)
    attribution.py      attribute_post_epoch(fill, c1) -> Attribution | Unresolved      (C1 only, P2-5)
                        backfill_family(fill, manifests, fold|None) -> FamilyId | Unresolved  (pre-epoch storage only)
    decision_link.py    C1Link (authoritative); NodeLogBridge (pre-epoch backfill only)
    probability.py      bought_leg_p(p_yes, side), bought_leg_p_raw(p_raw_yes, side)
    fq_scorer.py        ForecastQuantileLadderScorer (C6 Scorer)
    legacy_crh_scorer.py LegacyCrhScorer (C6 Scorer for current_rung_hold, continuous_rung_hold; P2-6)
    exit_labels.py      label_exit(sell_fill, open_lots, settlement) -> LabelRow (weighted-average cost)
    settlement_source.py SETTLEMENT_SOURCES: {polymarket_us: NwsCliFinal, kalshi: RefusingSettlementSource}
    completeness.py     coverage_partition(fills, labels) -> Coverage
    reconcile.py        reconcile_positions(), reconcile_settlement(), reconcile_cash(), cash_records()
    verdicts.py         build_reconciliation_verdict(mode), build_label_lag_verdict(mode)
    prelaunch_intents.py observe_open_intent_post_stop(), reconstruct_open_intent_at() (Z19 backfill)
    delivery.py         deliver_or_fail(payload) -> raises AlertDeliveryFailed
    label_run.py        python -m breezy.analysis.labeling.label_run [--canary|--proof-window]
    recon_run.py        python -m breezy.analysis.labeling.recon_run --mode {intraday,post_stop} [--emit-lock-contention]
src/breezy/analysis/plugins.py   OFFLINE_PLUGINS: FQ Scorer and the two CRH Scorer entries
scripts/analysis/portfolio_roi_report.py   roi_status, --status-only, labels_consumable gate, P&L union   [the portfolio-roi scorer, P6-9]
deploy/systemd/breezy-label-outcomes.{service,timer}, deploy/systemd/label-outcomes-run.sh
deploy/systemd/breezy-aut2-reconciliation.{service,timer}, deploy/systemd/aut2-reconciliation-run.sh      (intraday, W1)
deploy/systemd/breezy-autonomy-reconcile-poststop.{service,timer}                                     (W8; ARCH §4.4 unit name; same wrapper)
deploy/systemd/breezy-score-live-trials.timer                                                         (moves to 13:55Z; the wrapper stays AUT-6's)
```

Each reconciliation unit has **one** `ExecStart=`: the wrapper takes the reconcile flock and runs `recon_run`. `recon_run` performs the positions read in-process through `venue_positions_read`, which sits inside the `aut2_recon_run` §4.3 pin closure, as ARCH §4.4 requires. A snapshot is therefore always consumed by the verdict that read it. The unit-level `TimeoutStartSec` bounds the whole start phase, including the flock wait, the read and the reconcile (Q1).

#### 3.2.1 `src/breezy/runtime/venue_positions_read.py` (ARCH §4.4, V13, U4, U5)
- **Transport.** It builds `PolymarketUSHttpClient` (GET-only by `PERMITTED_METHODS`, over the method-less `PolymarketUSReadTransport`) and calls only `get_authenticated`, with `quota_key="portfolio"`.
- **Endpoint.** The single literal `POSITIONS_LITERAL = "/v1/portfolio/positions"` is passed through `validate_endpoint`. That function is the private `_validate_endpoint` moved from `scripts/venue/polymarket_us_shape_capture.py:573` and renamed public, with the script re-importing it byte-identically. A test asserts the literal equals `PORTFOLIO_POSITIONS_PATH` (`exec/endpoints.py:97`), but the module never imports `exec/` (no order-path import).
- **Pagination.** The only query parameter is `cursor`, looped until `eof=true` under `pins.POSTSTOP_POSITIONS_MAX_PAGES` (≤ 20). Reaching the page cap without `eof` gives `complete=false`.
- **Credentials.** `/home/jon/.config/breezy/polymarket.env` via `EnvironmentFile=-%h/.config/breezy/polymarket.env`, then `config_from_env` and `load_polymarket_us_credentials`. Never `operator.env`, never the capture script's `prepare`.
- **Output.** `VenuePositionsRead(snapshot_ns, complete, pages, rows=((base_slug, net_qty, expired), ...))`, carrying no account, position or order ids.
- **Errors.** A 429 (`VenueRateLimitError`) becomes `QUOTA_REFUSED`, and any other venue error becomes `READ_FAILED`. Neither is retried inside a slot.
- **Egress review.** The module joins `test_execution_egress_firewall_guard`'s coverage; that test is not edited, only its covered set grows. `test_poststop_venue_read_is_get_only` (ARCH §4.7) pins the one call attribute, the literal, the `cursor`-only queries and the page cap. AUT-2 files this as the reviewed egress dependency in Wave 0, before AUT-2a, and it is never a NO-SEND relaxation.

#### 3.2.2 Stores (directories 0700, files 0600, write-once unless stated; ARCH §3 one-writer-lock rule, RB-8)
All paths below are under `/home/jon/.local/share/breezy/`:
- **Labels.** `derived/labels/<family_id>/labels_<now_ns>.parquet` (C2), written once per run. Canary labels go to `derived/labels_canary/<family_id>/`.
- **Snapshots.** `evidence/venue_positions/polymarket_us/positions_<snapshot_ns>_<mode>.json` = `{schema: "venue_positions/v1", snapshot_ns, mode, complete, pages, read_status ∈ {OK, QUOTA_REFUSED, READ_FAILED}, rows: [{base_slug, net_qty, expired}]}`.
- **Position comparisons.** `evidence/aut2/position_compare/<YYYY-MM-DD>/<snapshot_ns>_<mode>.json`, one write-once file per snapshot. It holds `{snapshot_ns, snapshot_sha256, rows: [{base_slug, venue_net_qty, ledger_net_qty, result ∈ {MATCH, MISMATCH, NOT_COMPARED_GRACE, NOT_COMPARED_INTENT, SETTLED_AWAY}}]}`: quantities only.
- **Unresolved-identity journal.** `evidence/aut2/unresolved/<YYYY-MM-DD>/<now_ns>_label_run.json` (fill-key sha, base slug, `ts_event`, epoch class, rule outcomes; no amounts).
- **Run marker.** `derived/label_outcomes/<YYYY-MM-DD>/marker_<now_ns>.json`, written once per run. Consumers read the newest.
- **Canary.** `derived/canary/<venue>/canary_fills_<YYYY-MM-DD>.jsonl` (ARCH §5.3). Its only writer is `label_run --canary` under the studies flock, and `fill_source.py` never opens it.
- **Locks.** `locks/aut2-reconciliation.lock` is the reconcile lock. Its holders are the two `recon_run` modes, one binary.
- `test_autonomy_files_have_one_writer` gains every row above, as path pattern → lock → writer process types.

### 3.3 C6 `Scorer`, the registration gate and retired kinds (P2-6)

- **FQ.** `ForecastQuantileLadderScorer.label(capture_day, exec_fills, settlements) -> tuple[LabelRow, ...]` is registered in `OFFLINE_PLUGINS[CompositionKind.forecast_quantile_ladder].scorer`. It declares `legs = {"yes","no"}` and `roles = {"entry","exit"}`.
- **CRH kinds (P2-6).** `current_rung_hold` and `continuous_rung_hold` keep `RefusingPlugin` for mint and compose, but their `Scorer` member is the real `LegacyCrhScorer`.
  - It maps each frozen CRH `ScoredTrial` joined to a durable fill into one C2 row: `decision_id=null`, `excluded_reason=unattributed`, `p_source=none`, and P&L equal to `ScoredTrial.pnl × qty`.
  - Their cash stays in the legacy `reconcile_daily` parameters (§3.6.3), so these rows emit no cash record.
  - `forecast_ladder` has no fill, so its `Scorer` may refuse at once.
  - Test: `test_retired_kind_keeps_scorer_until_last_fill_labelled` (the ARCH §4.7 name). Every attributed fill of a kind must have a final C2 row before that kind's `Scorer` may refuse.
- **Family-agnostic.** `label_run` iterates `OFFLINE_PLUGINS` over the run's family set (§3.4.2). It contains no family literal.
- **Registration-time gate** (`tests/contract/test_aut2_scorer_registration.py`):
  - `::test_every_non_retired_manifest_kind_has_a_non_refusing_scorer`
  - `::test_new_manifest_without_scorer_cannot_register`
  - `::test_scorer_declares_both_legs_and_both_roles`
  - The gate tests run with ARCH's `test_family_plugin_exact_set`.
- **Compose-time cross-plan test, owned by AUT-2:** `::test_armed_family_with_refusing_scorer_is_refused_at_compose`.
  - It drives the production `_compose_family` (`src/breezy/app/trade.py:853`, an AUT-5a file).
  - AUT-2 never edits `src/breezy/app/trade.py`.
  - Hard prerequisite: AUT-5a's compose refusal.

### 3.4 Fill source, epoch, attribution and decision link

#### 3.4.1 Universe
- Every `DurableFillRecord` under `exec/polymarket_us/fill/`, read through the G6 URI. Today that is 20 fills (11 FQ, 9 legacy CRH).
- The canary store is read only by the canary path (§3.8).

#### 3.4.2 Attribution via C1 only (P2-5, Q2)
- **Epoch class.** `epoch.fill_epoch_class` reads AUT-1's write-once `capture_epoch_start` for the venue's sender family through AUT-1a's reader.
  - A fill is **POST_EPOCH** iff `ts_event ≥ capture_epoch_start` **and** its `client_order_id` has a C1 `OrderLink`.
  - An absent epoch file makes every fill PRE_EPOCH.
  - A fill with `ts_event ≥ capture_epoch_start` and no `OrderLink` is **UNRESOLVED**. This is C1 invariant (ii) broken, never a backfill candidate.
- **POST_EPOCH attribution.** The only path is `client_order_id → OrderLink → decision_id → DecisionRecord.family_id`. No other rule is consulted.
  - `drill` comes from the C1 record's own `drill` field (Z2).
  - `voided_pair` is set when the C1 `family_id`'s pair is voided and `ts_event` lies inside its effective-then-voided interval in the C5 fold (Z8). The record keeps that `family_id`, per ARCH C1.
  - A C1 `DecisionRecord` for a Take with null `p_hat` is refused by the writer. The fill becomes UNRESOLVED, CRITICAL.
- **PRE_EPOCH fills (backfill only).** These are written as C2 rows with `decision_id=null`, `excluded_reason=unattributed` (final), `admissible=False` and `p_source ∈ {artefact_recompute, none}`.
  - Their `family_id` is a **storage key**, never an attribution any consumer may use. It comes from `backfill_family`, in order:
    1. **(b)** the C5 fold CHAMPION on the venue at `ts_event`, where a fold exists.
    2. **(c)** the bridge: base-slug grammar gives `(station, climate_day, rung, leg)`, the kind's stored latch key must exist (`FORECAST_QUANTILE_TRIAL_KEY_PREFIX`), and exactly one manifest matches on kind, venue, station and the `d0_climate_day..terminal_climate_day` range (`src/breezy/persistence/family_manifest.py:388-405`).
  - (b) and (c) disagreeing, or neither yielding exactly one family, makes the fill UNRESOLVED.
  - Tests: `test_pre_epoch_fill_never_admissible` (Q2) and `test_scorer_never_attributes_by_trial_id_prefix` (P2-5; AST plus a behaviour fixture in which a prefix match and the C1 family differ, and C1 wins).
- **Non-attributing consistency check.** For a POST_EPOCH fill, a C5 fold CHAMPION that differs from the C1 `family_id` raises the metric `c1_fold_disagreements` and a CRITICAL. The label keeps the C1 `family_id`. Test: `test_c1_fold_disagreement_alerts_but_never_reattributes`.
- **Family set.** The run's family set is every family that is non-RETIRED now, plus every family with an attributed fill that lacks a final label (P2-6). Pinned by `test_retired_family_labelled_until_last_fill`.
- **UNRESOLVED.** Such a fill gets no C2 row. It gets a durable journal row (§3.2.2), a CRITICAL, a RECONCILIATION FAIL and `run_outcome = FAILED_IDENTITY` (§3.12).

#### 3.4.3 Identity
- `trial_id` is the **stored latch key** (P2-5, G28, G35):
  - FQ: `forecast_quantile_ladder/trial/<STATION>/<day>/<rung_id>:<side>`, as written by `TrialDayLatch._trial_key` with the `_composite_key` instrument id.
  - CRH: the `ScoredTrial.trial_id`.
  - The key is read back through the G6 URI. A missing latch key is a WARN plus the metric `latch_key_missing`, and the row still carries the computed key.
- `test_trial_id_is_stored_latch_key` replaces r3's prefix test.
- `label_id` is the first 32 hex characters of `sha256("label/v1"|family_id|client_order_id|trade_id or ""|role)`. Dedupe is on `(label_id, max label_seq)`.

#### 3.4.4 Bought-leg probability and `p_source` (P3-9, P2-1, Q2)
- **`c1_decision` (POST_EPOCH, the only admissible source).**
  - `p_at_decision = p_hat` for a YES buy and `1 − p_hat` for a NO buy.
  - `p_raw_at_decision = p_hat_raw` for a YES buy and `1 − p_hat_raw` for a NO buy.
  - `p_hat` and `p_hat_raw` are taken from the joined `DecisionRecord`, along with `decision_id`, `side` and `entry_ask = ask_px`.
  - FQ's `p_hat` is P(YES rung) in both side modes (`fq/decision.py:349`; `src/breezy/analysis/ladder_ev/scoring.py:70-87`).
  - A `side` that disagrees with the fill's leg is CRITICAL with `reconciled=False`.
  - Test: `test_p_at_decision_is_bought_leg_probability` (ARCH §4.7).
- **`artefact_recompute` (PRE_EPOCH backfill only).**
  - Meaning: the p the bound artefact produced at decision time, recovered from the node's own `SHADOW_DECISION` output. It is never a fresh offline computation (L-2).
  - The bridge keys on `client_order_id` within bounded windows:
    1. the durable fill's `client_order_id` and `trade_id`;
    2. the `OrderFilled` line with both;
    3. the `OrderInitialized` line with the same `client_order_id`, at most `BRIDGE_INIT_TO_FILL_MAX_S = 300 s` earlier;
    4. exactly one `SHADOW_DECISION` line with `kind == 'Take'`, the same `instrument_id` and `now_ns ∈ [init_ts − 2 s, init_ts]`.
  - Line adjacency is never used. The search reads the node log **files**, never journald.
  - `p_raw_at_decision` equals `p_at_decision` only when the bound artefact's `recalibration == "none"`, verified from the artefact by manifest sha. G11 makes this true for every live FQ artefact. Otherwise both fields are null and `p_source=none`.
- **`none`.** No bridge match, CRH rows, and exit-role rows (§3.5). Both p fields are null, and the reason is the pair (`p_source=none`, `excluded_reason` or `role=exit`).
- **Metrics.**
  - `p_null_count`: rows with `p_source=none` among entry rows.
  - `non_c1_post_epoch_count`: must be 0, since a POST_EPOCH entry row is always `c1_decision`.
  - `bridge_match_rate`: backfill only, reported for the WP3 backfill over the 11 live FQ fills.
- **The bridge is backfill only (Q2).** It is never a proof-window source, and r3's post-WP7 cross-check is withdrawn. Pinned by `test_bridge_never_runs_on_post_epoch_fills`.

### 3.5 Entry labels (YES and NO legs)

| Quantity | YES leg (`<slug>.POLYMARKET_US`) | NO leg (`<slug>^no.POLYMARKET_US`) |
|---|---|---|
| Durable record | `orderSide BUY`, cost in YES units | `orderSide BUY` (adapter sends venue `SELL`/`BUY_SHORT`, G24), cost in NO units |
| `fill_px` | `cumulative_cost / cumulative_qty` | same, NO units |
| `p_at_decision` / `p_raw_at_decision` | `p_hat` / `p_hat_raw` | `1 − p_hat` / `1 − p_hat_raw` (§3.4.4) |
| `settled_outcome` | `score_trial(...).held` | `score_trial(...).held` (leg-aware, `trial_scorer.py:207-209`) |
| Cost basis (fee-inclusive) | `cumulative_cost + fee_reconciled` | same |
| `realized_pnl` (held to settlement) | `qty·payoff − cost basis` | same |
| Venue net on base slug | `+qty` | `−qty` (L-44; `src/breezy/adapters/polymarket_us/parsing.py:277-279`) |

- `realized_pnl == ScoredTrial.pnl × qty` is asserted and never smoothed.
- **Fees.** `fee_reconciled = cumulative_fee` only when the record's `fee_reconciled is True`; otherwise `excluded_reason = fee_unreconciled`. Alerting is WARN on the first label and CRITICAL if the fee is still unreconciled after `LABEL_LAG_MAX_H`.
- **Slippage.** `slippage = fill_px − entry_ask`. A fill better than the ask by more than one tick gives `excluded_reason = slippage_defect` (in ARCH C2) and a WARN.
- **Reconciliation columns (ARCH C2).**
  - `reconciliation_source = venue_get` when the governing comparison came from `venue_positions_read`; else `node_belief`, which never makes `reconciled=True`.
  - `reconciliation_delta = venue_net − ledger_net` at the governing comparison (§3.6.1).
  - `net_position_key` = the base slug.
- **Admissibility.** `admissible = reconciled ∧ source == live ∧ ¬drill ∧ role == entry ∧ excluded_reason is None ∧ p_source == c1_decision ∧ settlement_basis == nws_final ∧ window_complete`.
- **`window_complete` for `(family, climate_day)`.** It holds once every attributed fill that day has a final settlement or a final exclusion. Until then, rows carry `excluded_reason = window_incomplete` and are re-labelled at `label_seq + 1`. A `window_incomplete` row older than `WINDOW_INCOMPLETE_MAX_H = 48` past the venue settlement instant makes `HEALTH FAIL label_lag`.
- **Final versus non-final reasons.** Final: `duplicate_fill`, `q≠1`, `fee_unreconciled` (after the horizon), `canary`, `drill`, `voided_pair`, `slippage_defect`, `unattributed`. Non-final: `window_incomplete`, and `fee_unreconciled` inside the horizon.
- **Venue fallback settlement (RB-5).** The trigger is exactly `score_trial`'s basis (`trial_scorer.py:247-255`); AUT-2 evaluates no condition of its own. The mapping is total:

  | `ScoredTrial.settlement_basis` / `excluded_reason` | C2 row |
  |---|---|
  | `nws_final` / `None` | normal settlement |
  | `venue_last_fair_price_fallback` / `venue_settled_without_nws` | `settled_outcome = held` and `realized_pnl = pnl × qty` from `score_trial`; `settlement_basis = venue_last_fair_price_fallback`; **`admissible=False` by the `settlement_basis == nws_final` term**; final for the lag clock; `excluded_reason` stays null until ARCH widens C2 with `venue_fallback_settlement` (§9A N-1, non-blocking), after which the row is rewritten at `label_seq + 1` |
  | `ScoreRefusal` (no final yet) | `window_incomplete` (pending) |
  | any other reason | `write_labels` refuses (`UnmappedScorerReason`), CRITICAL |

  - The 7-day fallback pending period raises `label_lag` by design, with `cause=awaiting_venue_fallback` in the HEALTH metrics. An NWS outage needs a human-visible alert. Pinned by `test_fallback_pending_window_raises_label_lag_by_design`.
  - `test_fallback_basis_never_admissible` pins the interim rule.
- **Settlement source by venue:** `polymarket_us → NwsCliFinal`; `kalshi → RefusingSettlementSource("twc_reader_absent")`.
- **Pre-epoch drill.** No pre-epoch row is ever `drill=true`, because no DRILL_PROMOTE precedes AUT-5b. This is asserted.

### 3.6 Reconciliation: three legs, per-leg tolerances (ARCH §10)

#### 3.6.1 Position leg (net; fence and grace; venue-net source rules U5, Z5)

- **Source rules (ARCH C2, RB-3).**
  - Venue net is read **only** through `venue_positions_read` (`reconciliation_source=venue_get`).
  - Intraday reads happen only at the :05 and :35 slots: at least 30 min apart and at most 2 reads an hour against the `portfolio` quota that the node's exec client shares.
  - The post-STOP read (§3.11) runs with the node down, so it shares the quota with no consumer. It allows at most 2 reads: the first and one re-pull.
  - `QUOTA_REFUSED`, `READ_FAILED` or `complete=false` makes that verdict INCONCLUSIVE, never PASS, and the read is never retried inside the slot.
  - A node `PositionMark` (`reconciliation_source=node_belief`) is never a comparison input. It alone gives INCONCLUSIVE.
  - The daily RECONCILIATION (§3.7.1) uses only the journaled `venue_get` comparisons.
  - Tests: `test_quota_refusal_is_inconclusive_never_pass`, `test_node_belief_alone_is_inconclusive`, `test_intraday_reads_at_most_two_per_hour`.
- **Compared set.** The compared set is ledger slugs ∪ venue-page slugs.
  - A venue slug with no ledger fill is a FAIL (`venue_only_slug`).
  - An open ledger slug absent from the page compares as venue 0. "Open" means `snapshot_ns < settlement_deadline_ns(climate_day)` and the slug has not appeared with `expired == true`.
  - A ledger slug past its deadline and absent from the page is **settled-away** (L-52). It is not compared, because the settlement and cash legs cover it.
- **Fence and grace.**
  - The ledger side is `net_signed_qty(fills with ts_event ≤ snapshot_ns − POSITION_SETTLE_GRACE_S)`, with the grace pinned at 60 s (`test_position_settle_grace_pinned`).
  - A slug with any fill in `(snapshot_ns − 60 s, snapshot_ns]` is `NOT_COMPARED_GRACE` for that snapshot.
  - A slug with an OPEN or AMBIGUOUS intent at snapshot time is `NOT_COMPARED_INTENT`, which makes that verdict INCONCLUSIVE.
- **Tolerance.** 0 contracts, exact Decimal, both legs. YES counts `+q` and NO counts `−q` on the base slug, summed with the leg sign.
- **Verdict per snapshot.** Any `MISMATCH` fails that verdict's position leg, with a CRITICAL. Every comparison is written once per snapshot (§3.2.2).
- **Label `reconciled` from the governing comparison (RB-4).**
  - A label's position component is recomputed on every run from the **governing comparison**: the newest journaled `MATCH`/`MISMATCH` for its `net_position_key` with `snapshot_ns < settlement_deadline_ns`.
  - That comparison sets `reconciled`, `reconciliation_delta` and `reconciliation_source=venue_get`. A change rewrites the row at `label_seq + 1`.
  - The governing comparison is reproducible from the write-once journal, so C2 needs no snapshot-id column. r3's two position-compare columns are withdrawn.
  - A transient mismatch clears on the next MATCH. The earlier verdict stays FAIL on record, and its CRITICAL is not retracted.
- **Daily position leg.** It passes iff every compared slug's governing comparison is `MATCH`. Transient mismatches are reported as `position_mismatches_transient`.
- **Coverage.**
  - Every fill must reach a `MATCH`/`MISMATCH` comparison before its deadline; `fills_never_position_compared > 0` fails the day.
  - A missing or stale snapshot (`> SNAPSHOT_MAX_AGE_MIN = 45`) makes that verdict INCONCLUSIVE plus a WARN.
  - `INCONCLUSIVE_ALERT_DAYS = 2` consecutive INCONCLUSIVE daily verdicts, or 2 consecutive `BALANCE_UNKNOWN` days, raise a CRITICAL.

#### 3.6.2 Settlement leg
- **Comparison.** The label's `settled_outcome` is compared for exact equality with the venue settlement for the slug, from the tape `custom_venue_settlement_snapshot` and `PositionResolution`.
- **Disagreement.** `reconciled=False`, a CRITICAL `settlement_source_disagreement` and a FAIL. The venue value is never adopted.
- **PENDING.** With no venue evidence yet, or a label in fallback pending, the slug is PENDING. A day with any PENDING slug is INCONCLUSIVE, never PASS.
- **Missing evidence.** No venue evidence 48 h after the CLI final is a FAIL.

#### 3.6.3 Cash leg (cumulative net identity)
`reconcile_daily` runs over the union of all cash sources through its existing parameters:
- **`fills`.** Every durable fill, legacy CRH and FQ.
- **`scored_trials`.** The frozen legacy CRH `ScoredTrial` stores, unchanged.
- **`residual_settlements`.** The legacy residuals (`_resolve_residual_settlements`, `portfolio_roi_report.py:3769`), plus the `ResidualSettlement` records from `reconcile.cash_records(c2_rows)`. `cash_records` skips rows whose fill key is in a legacy cash source, which covers every `LegacyCrhScorer` row. It emits three kinds of record, each with an explicit `dated_at_ns`:
  1. a held-to-settlement payout `qty·payoff`, dated at `settlement_deadline_ns`;
  2. exit proceeds net of the exit fee, dated at the SELL's `ts_event`;
  3. a **YES/NO netting offset**: when both legs of one base slug are held, `min(q_yes, q_no) × $1` is dated at the venue netting event from the activity feed (L-1 (vii)), and those contracts' payouts are not booked again. If the netting event is unobservable, every cash day from the offsetting fill through settlement is INCONCLUSIVE (`cash_unknown_netting_offset`), never FAIL.
- **Overlap refused.** A fill key in both a legacy source and a C2 cash record raises `CashSourceOverlap`, a CRITICAL and a cash-leg FAIL (`test_fill_in_both_sources_refused`).
- **Pass.** The leg passes on `cumulative_reconciliation(...).settled_cumulative_passes_net` over days ≤ `settled_through`. The window starts at the earliest known balance.
- **Tolerance.** `per_day_tolerance(fills_opened_that_day)` (`:1390`, count from `_fills_opened_count_by_day`, `:1110`). The cumulative tolerance is the Σ over settled days.
- **Unknown balance.** `BALANCE_UNKNOWN`, or `external_flow_evidence_status != OK`, gives INCONCLUSIVE, never coerced to zero.

#### 3.6.4 Exit consistency and daily outcome
- **Exit consistency.** The latch `exitPx/exitFee/exitAtNs` (`src/breezy/strategy/current_rung_hold/exit_wiring.py:227-236`) must equal the durable SELL. A mismatch sets `reconciled=False` on the exit label. The SELL's `cumulative_cost` semantics stay behind L-1 (vi).
- **Daily outcome.** PASS only if all three legs pass, coverage passes, and the completeness identity holds with `UNRESOLVED == MISSING_LABEL == 0` (§3.12).
- Any FAIL makes the day FAIL. Any PENDING or INCONCLUSIVE leg makes it INCONCLUSIVE, which never satisfies §4.4 or ATTEST.

### 3.7 C4 producers

#### 3.7.1 RECONCILIATION (daily, from `label_run`)
- **Producer.** Producer id `aut2_label_run`, pinned in `PRODUCER_SOURCE_SHA256` over its import closure. The pin update lands in the same commit.
- **Per-family fields.** One verdict per family in the §3.4.2 set:
  - `subject_artefact_sha256` is the bound artefact sha (Z1). Before C5 exists it is the manifest's `density_artefact_sha256`.
  - `detector = "aut2.reconciliation"`.
  - `declared_action_class` and `policy_ruling_sha256` come only from the pinned `autonomy-policy/v1` block. Without one, the verdict carries `assumptions ∋ no_policy_ruling` and the restrictive fallback (ARCH C4).
  - `n` counts the slugs and days compared; `n_min` carries the reason `deterministic_equality_check`.
- **`metrics`** (pre-registered names):
  - Position: `position_slugs_compared, venue_only_slugs, position_mismatches, position_mismatches_transient, not_compared_grace, fills_never_position_compared, read_status`.
  - Settlement and cash: `settlement_mismatches, settlement_pending, cash_days_failed, cash_days_inconclusive, unknown_slugs`.
  - Completeness: `durable_fill_count, labelled_final, unattributed_pre_epoch, legacy_labelled, open, pending, unresolved, missing_label`.
  - Probability and identity: `p_null_count, non_c1_post_epoch_count, bridge_match_rate, c1_fold_disagreements, latch_key_missing`.
  - Z19: `open_intent_at_poststop_7d, open_intent_unknown_7d`.
- **Coverage folded in (RB-7).** ARCH §5 gives AUT-2 C4 `RECONCILIATION` and `HEALTH label_lag` only, so r3's separate `label_coverage` HEALTH detector is withdrawn. Coverage failure (`unresolved`, `missing_label`) is a RECONCILIATION FAIL.
- **Validity and slots.** `valid_until_ns = produced_at_ns + 26 h` (≤ `pins.MAX_VERDICT_VALIDITY_H`). It runs at the 14:15Z and 05:00Z slots.
- **Before the policy block.** With no policy block, the verdict is written with `no_policy_ruling`. Alerts, journals and `reconciled=False` operate regardless.

#### 3.7.2 HEALTH `label_lag` (detector id `aut2.label_lag`)
- **Lag clock (RB-7).** `lag_start_ns = min(first SettlementRecord.ts_ns for (station, climate_day), settlement_deadline_ns(venue, city, climate_day))`.
  - This is ARCH C2's "within 24 h of its `SettlementRecord`", made fail-closed: a missing `SettlementRecord` (an NWS outage, or the AUT-1a writer absent) still starts the clock at the venue settlement instant.
  - `label_lag = first_final_label_ns − lag_start_ns`. A `window_incomplete` row never stops the clock.
- **Horizon pinned.** `test_label_lag_horizon_pinned_under_max_verdict_validity` asserts `LABEL_LAG_MAX_H == 24 ≤ pins.MAX_VERDICT_VALIDITY_H` and `WINDOW_INCOMPLETE_MAX_H == 48`.
- **Breach.** Any live fill with `now − lag_start_ns > 24 h` and no final label gives `HEALTH FAIL` plus a CRITICAL (`test_no_cli_final_fails_label_lag_at_24h`). Fallback-pending fills carry `cause=awaiting_venue_fallback`.
- **Producers.** The daily run produces it, and the intraday run produces it read-only (§3.11).

#### 3.7.3 Delivery and exit codes
- **Delivery.** Every CRITICAL goes through `deliver_with_proof` via `delivery.deliver_or_fail`. Each attempt writes AUT-6's write-once record under `/home/jon/.local/share/breezy/evidence/alerts/<date>/` (ARCH §4.6, RB-13).
- **Delivery failure exits non-zero.** A `deliver_with_proof` failure exits 4 in `label_run` and both `recon_run` modes, with the line `AUT2 DELIVERY_FAILED event=<name>`. The exit happens after every durable write and trips `OnFailure=breezy-study-failed@%n`.

| Condition | Exit | Marker | Notes |
|---|---|---|---|
| Run ok; `LABELLED`/`PENDING`/`NO_INPUT`; every CRITICAL delivered | 0 | written | a lag FAIL is a detected data condition, alerted |
| `FAILED_IDENTITY`, CRITICAL delivered | 0 | written, `run_outcome=FAILED_IDENTITY` | consumers gate (§3.12) |
| Label-run studies-flock timeout | 0 | none | `LABEL_OUTCOMES SKIPPED reason=lock`, WARN; 2 consecutive slots → CRITICAL; label lag backstops |
| Unreadable or undecodable store, manifest or snapshot file | 1 | none | never NO_INPUT |
| Post-STOP lock contention | 3 | n/a | CRITICAL first |
| `deliver_with_proof` failed | 4 | written if the run succeeded | `OnFailure=` backup |

### 3.8 Canary store (Z14) and drill

- **Path and writer.** `/home/jon/.local/share/breezy/derived/canary/<venue>/` (ARCH §5.3). The writer is `label_run --canary`, and only on a UTC day with zero real attributed fills. It writes C1-shaped synthetic records with `source=canary`.
- **Canary Scorer input.**
  - The same `ForecastQuantileLadderScorer.label(...)` reads `read_canary_fills()` and a synthetic canary snapshot, and writes to `derived/labels_canary/`.
  - It never reads `venue_positions_read`.
  - Its output never enters `derived/labels/`, any RECONCILIATION input, any `n`, `portfolio-roi`, `entry_guard`, or the completeness identity.
- **Canary-day verdict.** A canary day qualifies iff both hold:
  1. every canary fill has a canary label with non-null `p_at_decision` and passes canary reconciliation;
  2. the day's real RECONCILIATION is PASS.
- A canary never satisfies "every live fill labelled". The artefact records `real_fills=0, canary_fills=k, live_fill_check="vacuous"`.
- **Tests** (`tests/unit/test_aut2_canary_isolation.py`):
  - `::test_reconciliation_and_entry_guard_never_read_canary_store` (the ARCH §4.7 name)
  - `::test_canary_labels_are_never_admissible`
  - `::test_canary_rows_excluded_from_verdict_n_and_completeness`
  - positive controls `::test_canary_ast_scanner_flags_planted_reader` and `::test_runtime_canary_guard_trips_on_planted_open`
- **Drill.**
  - `drill=true` comes from the C1 record. Such a row gets `excluded_reason=drill` and is inadmissible.
  - Drill fills are real, so they are position- and cash-reconciled and are in the completeness identity.
  - Drill rows stay present for AUT-6 detectors and the AUT-5 drawdown limit (W12).
  - Tests: `test_drill_fill_labelled_reconciled_but_inadmissible`, `test_drill_fill_after_resume_still_drill`, `test_voided_pair_fills_excluded_from_all_n` (ARCH name).

### 3.9 Z19: open intent after STOP (P2-4)
- **Direct observation.** The post-STOP run passes the live-node guard, then reads `exec/polymarket_us/intent/current` read-only (G6 URI), as `probe_open_intent` does. The node is down from 16:40Z, so the state at 16:41Z equals the state at 16:45Z (ARCH §4.4).
- **Metric.** The run writes `open_intent_at_poststop ∈ {none, OPEN, AMBIGUOUS, unknown}` into the post-STOP verdict's metrics (the ARCH name, RB-12). No supervisor log line is needed.
- **`unknown`** applies when the run did not complete, a live node was found, or the STOP signal was absent.
- **Backfill.** `reconstruct_open_intent_at()` over `intent/history/*` reports `unknown` whenever `created_ns` preservation is unproven.
- **Output.** 7-day counts go into the daily metrics, with the journal line `Z19 open_intent_at_poststop days=<k>/<n> ambiguous=<a> unknown=<u>`.
- **Alerting.** Until AUT-5a's STOP journaling exists, `unknown` is a metric only (`test_z19_unknown_is_metric_not_alert`).

### 3.10 Units, slots and consumers (Q1: `TimeoutStartSec` throughout)

Every AUT-2 unit is `Type=oneshot` and bounded by a **unit-level `TimeoutStartSec`**. For a oneshot, that bound covers the whole start phase: every `ExecStart=` line, plus the flock wait inside the wrapper. No AUT-2 unit sets `RuntimeMaxSec`, which is a no-op on a oneshot (G32, host systemd 259).

The launch-window arithmetic is additive and conservative: `start + flock -w + TimeoutStartSec`. It matches the ARCH §5.2 table.

| Unit | Schedule | Lock (`flock -w`) | `TimeoutStartSec` | Worst-case end | Other settings |
|---|---|---|---|---|---|
| `breezy-label-outcomes` (study) | `*-*-* 14:15:00 UTC`, `*-*-* 05:00:00 UTC` | `breezy-studies.lock`, `LABEL_FLOCK_WAIT_S=600` | `LABEL_TIMEOUT_START_S=1800` | 14:15 + 600 + 1800 → **14:55:00Z** (< 16:30Z); 05:00 → **05:40:00Z** | `breezy-studies.slice`; `MemoryMax=1G` (r3 precedent 137 MB, re-measured before enabling, V14); `OnFailure=breezy-study-failed@%n`; `EnvironmentFile=-%h/.config/breezy/alerts.env`; stall line every 60 s |
| `breezy-aut2-reconciliation` (intraday, W1) | `*-*-* *:05,35:00 UTC` | `locks/aut2-reconciliation.lock`, `RECON_INTRADAY_FLOCK_WAIT_S=30` | `RECON_INTRADAY_TIMEOUT_START_S=240` | 16:35 → **16:39:30Z** (< STOP 16:40); 17:05 → **17:09:30Z**; both are the ARCH §5.2 rows | own lock, never the studies flock; `MemoryMax=512M`; `EnvironmentFile=-%h/.config/breezy/polymarket.env` and alerts env; `OnFailure=` |
| `breezy-autonomy-reconcile-poststop` (W8) | `*-*-* 16:41:00 UTC` | same reconcile lock, `POST_STOP_FLOCK_WAIT_S=20` | `POST_STOP_TIMEOUT_START_S=100` | 16:41 + 20 + 100 → **16:43:00Z** (< pre-launch 16:45); W + T = 120 ≤ `pins.POST_STOP_RECONCILE_RUNTIME_S` | as intraday; `--mode post_stop` |
| `breezy-score-live-trials.timer` | moves 14:15Z → **13:55Z** | studies flock (unchanged wrapper, AUT-6) | unchanged (`breezy-score-live-trials.service:76`) | asserted by test < 16:30Z | timer file only; AUT-2 owns the tally scorer, AUT-6 the wrapper |

**Q1 tests** (`tests/unit/test_aut2_units_deploy.py`):
- `::test_no_aut2_oneshot_sets_runtime_max_sec` parses every AUT-2 unit file and fails on any `RuntimeMaxSec=`. It has a positive control: a planted unit file containing `RuntimeMaxSec=` makes it fail.
- `::test_aut2_oneshots_set_timeout_start_sec_equal_to_constants`
- `::test_label_slots_clear_launch_window`: for 14:15Z and 05:00Z, `[start, start + LABEL_FLOCK_WAIT_S + LABEL_TIMEOUT_START_S]` does not meet `[16:30Z, 17:10Z)`.
- `::test_intraday_fires_inside_window_match_arch_rows`: only 16:35 and 17:05 fall inside the window, each ending by 16:39:30 and 17:09:30.
- `::test_post_stop_slot_ends_before_1645Z`: `16:41 + 20 + 100 ≤ 16:43:00` and `W + T ≤ pins.POST_STOP_RECONCILE_RUNTIME_S`.
- `::test_score_live_trials_slot_clears_launch_window`
- `::test_intraday_1635_fire_releases_lock_before_post_stop`
- `::test_recon_units_use_own_lock_not_studies_flock`

These tests also feed ARCH's `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec` and `test_no_unit_overlaps_launch_window`, whose sweep covers the AUT-2 units.

**Slot rationale.** PM.us settles at 08:00 ET (12:00Z EDT; 13:00Z EST from 11-02). Western CLI finals arrive around 09:30–10:30Z. So 14:15Z is the primary label run and 05:00Z the catch-up (ARCH C2, P2-2). The 30-min intraday cadence is within ARCH §5.2's "at least hourly" and within the W1 `L_max` bound (§3.11).

**Consumers.**

| Unit | Today | After AUT-2 |
|---|---|---|
| `breezy-score-live-trials` | FQ skipped, no marker | **AUT-6** adds the skip marker to the wrapper (AUT-6 r3, P6-9). **AUT-2** WP6 moves the timer to 13:55Z. The tally then covers only the frozen CRH stores, and the unit is disabled once every CRH family is RETIRED and labelled (P2-6; reviewed unit change). |
| `breezy-portfolio-roi` | exit 1 daily (F2) | **Exit semantics: AUT-6** (`portfolio-roi-run.sh`, `NO_INPUT` on the skip marker). **Scorer: AUT-2**, in `scripts/analysis/portfolio_roi_report.py`. WP1 adds `roi_status ∈ {OK, GATED_UNLABELLED_FQ}` and `--status-only`: that entry prints `PORTFOLIO_ROI GATED_UNLABELLED_FQ unlabelled=<n>` and publishes no ROI figure whenever any durable fill is in the legacy `UNRECONCILED` bucket (`:573-597`), exiting 0. AUT-2 offers it to AUT-6's NO_INPUT branch (§5). WP6 gates the report on `labels_consumable(newest marker)` (`GATED_IDENTITY`, `GATED_UNSETTLED_CAPITAL`), unions the P&L as C2 ∪ legacy with overlap refused, and adds the net pass flag. |
| `breezy-family-tally@pm_us_crh_{v2,v4}` | SKIPPED | Semantics unchanged; never non-zero as expected behaviour. |
| `breezy-position-monitor-report` | Unscoped | WP1 scopes it by family and prints `NO_MONITOR_FOR_KIND forecast_quantile_ladder`. |
| `breezy-replay-daily` | FQ SKIPPED | Unchanged (AUT-4). |

### 3.11 Intraday and post-STOP RECONCILIATION producers (W1, W8)

- **Producer id.** `aut2_recon_run`, pinned in `PRODUCER_SOURCE_SHA256`. Its import closure includes `src/breezy/runtime/venue_positions_read.py` (ARCH §4.4).
- **Intraday mode (W1), at :05 and :35.**
  1. One `venue_positions_read`. A `complete=false` page set, or a `read_status` other than `OK`, gives INCONCLUSIVE.
  2. The position leg over ledger ∪ page, with the fence and grace (§3.6.1).
  3. Carry forward the newest daily RECONCILIATION. Intraday is PASS only if the position leg passes and the newest daily verdict is PASS and younger than 26 h. A daily FAIL gives FAIL. A daily INCONCLUSIVE, absent or expired verdict gives INCONCLUSIVE. The cited daily verdict's sha is an `inputs` entry (`path_role=daily_reconciliation_verdict`).
  4. HEALTH `label_lag`, recomputed read-only.
  - `valid_until_ns = produced_at_ns + RECON_INTRADAY_VALIDITY_H (8 h)`.
- **ATTEST fit (W1, RB-9).** The intraday verdicts are the `(RECONCILIATION, aut2.reconciliation)` and `(HEALTH, aut2.label_lag)` rows that AUT-5's `attest_required_detectors` lists. Tests:
  - `test_intraday_recon_validity_within_attest_validity`: `RECON_INTRADAY_VALIDITY_H ≤ pins.ATTEST_VERDICT_VALIDITY_H`.
  - `test_intraday_recon_period_within_attest_lmax`: `INTRADAY_PERIOD_MIN (30) ≤ pins.INTRADAY_ATTEST_VERDICT_PERIOD_MIN (≤ 60)`.
  - AUT-5 owns the joint `test_attest_cadence_has_no_expiry_gap`.
- **Post-STOP mode (W8), in this order:**
  1. **Lock.** `flock -w 20` on the reconcile lock.
     - Contention means something abnormal holds the lock, and it leads to a SWAP_CANCEL.
     - The wrapper itself sends the CRITICAL `aut2.post_stop_lock_contention` via `recon_run --emit-lock-contention`, which takes no lock.
     - Then it prints `AUT2_RECON POST_STOP_SKIPPED reason=lock` and exits 3.
  2. **STOP signal (ARCH §4.4).** The run proceeds only after the supervisor's journaled STOP completion for day D. AUT-5 names the signal; AUT-2 consumes it through the AUT-5 interface. Absent by 16:41Z → INCONCLUSIVE, Z19 `unknown`, a WARN; the incumbent launches unchanged.
  3. **Live-node guard.**
     - `pid = find_pid_by_argv(NODE_ARGV_ANCHOR)`, then `assert_no_live_node_before_intent_probe(pid)`, both imported from `breezy.runtime`.
     - On a live node: no exec-store read, INCONCLUSIVE, Z19 `unknown`, CRITICAL `aut2.post_stop_live_node`, exit 0 after delivery.
     - The guard runs again immediately before the intent read.
  4. **Venue snapshot source (ARCH §4.4).**
     - One `venue_positions_read`, accepted only if `snapshot_ns ≥ stop_completed_ns + POSITION_SETTLE_GRACE_S` and `≥` the last durable fill's `ts_event + POSITION_SETTLE_GRACE_S`. With that bound no `NOT_COMPARED_GRACE` can occur.
     - An early read is re-pulled once after the gap (at most 2 reads).
     - Still early, a failed read or an incomplete page set → INCONCLUSIVE.
     - Pinned by `test_post_stop_snapshot_after_stop_plus_grace_compares_every_slug`.
  5. The position leg, the carry-forward and HEALTH run as in intraday mode. Then the Z19 observation (§3.9).
  6. **The §4.4 horizon supplied to AUT-5.** The pre-launch pass accepts a RECONCILIATION only if `produced_at_ns ≥ STOP_ns(D)`, the producer mode is `post_stop`, and the outcome is PASS. Anything else gives SWAP_CANCEL and the incumbent launches unchanged (`test_prelaunch_requires_post_stop_reconciliation`, AUT-5).
- **Before the policy block.** Verdicts carry `no_policy_ruling`. Snapshots, journals and alerts run regardless.

### 3.12 Completeness identity, marker and NO_INPUT

- **Partition.** `completeness.coverage_partition` places every durable fill read by `fill_source` (`n_keys`) in exactly one bucket:
  - `C2_FINAL`: a C2 row that is admissible or carries a final `excluded_reason`. This includes the pre-epoch `unattributed` rows and the `LegacyCrhScorer` rows, counted separately as `unattributed_pre_epoch` and `legacy_labelled`.
  - `C2_NONFINAL`: only non-final rows. It is `open` while `now < settlement_deadline_ns`, else `pending`.
  - `UNRESOLVED`: §3.4.2. These are post-epoch fills without a unique C1 join, and pre-epoch fills with no unique backfill family.
  - `MISSING_LABEL`: resolved, with no C2 row after this run's write. Every resolved fill gets at least a `window_incomplete` row on the run after it appears, so a non-zero count is always a defect.
- **Identity, asserted every run and in the proof artefact:**
  - `C2_FINAL + C2_NONFINAL + UNRESOLVED + MISSING_LABEL == durable_fill_count`
  - `UNRESOLVED == 0`, `MISSING_LABEL == 0`, `n_undecodable == 0`
  - Any breach gives a RECONCILIATION FAIL, a CRITICAL and `run_outcome = FAILED_IDENTITY`.
- **RED tests** (`tests/unit/test_aut2_completeness.py`):
  - `::test_labelled_plus_excluded_equals_durable_count`
  - `::test_deleting_one_label_fails_identity` (positive control)
  - `::test_missing_label_bucket_counts_as_failure`
  - `::test_legacy_crh_fills_labelled_by_legacy_scorer`
  - `::test_unresolved_fill_fails_identity`
  - `::test_post_epoch_fill_without_order_link_is_unresolved`
- **Marker.** `derived/label_outcomes/<date>/marker_<now_ns>.json` holds `{schema: "label_outcomes_marker/v1", run_outcome ∈ {LABELLED, PENDING, NO_INPUT, FAILED_IDENTITY}, durable_fill_count, labelled_final, unattributed_pre_epoch, legacy_labelled, open, pending, unresolved, missing_label, p_null_count, non_c1_post_epoch_count}`. It is written last, and never on exit 1.
- **NO_INPUT** applies only when the run wrote zero rows and `pending == unresolved == missing_label == 0`. Zero rows with `pending > 0` is `PENDING`. `FAILED_IDENTITY` overrides every other outcome.
- **Consumer rule.** One shared predicate `labels_consumable(marker)` in `label_store.py` serves portfolio-roi, AUT-3 and AUT-4. It is GATED iff:
  - `run_outcome == FAILED_IDENTITY`, or
  - `pending + unresolved + missing_label > 0`, or
  - the newest marker is absent or older than 26 h.
  - Pinned by `test_consumer_gate_rule_is_shared`.
- **Unreadable store.** Any failure to open or decode an input gives a CRITICAL, exit 1 and no marker.

---

## 4. Work packages

**Gate for every WP.** Run from the tree root with the exact interpreter `/home/jon/breezy/.venv/bin/python`, never `uv` or `pip` (L-51):
- `scripts/ci/run_tests_no_egress.sh`: the full gate after **every** merge (L-43). Under a unit, add `-p LimitNOFILE=524288`.
- `cd <tree> && .venv/bin/lint-imports`, which must print `N kept, 0 broken`. The contracts include `persistence.autonomy ↛ adapters`.
- `.venv/bin/mypy src/breezy/analysis/labeling src/breezy/persistence/autonomy src/breezy/runtime/venue_positions_read.py`: 0 errors and no new `# type: ignore` (mypy ratchet).
- In a worktree, set `PYTHONPATH=<worktree>/src`.

RED→GREEN output is kept per WP. Every injectable seam has a production-default test (L-55), and every store-reading gate test writes its fixtures through the real writer (L-42).

**Slice map (ARCH §5.1).**
- Wave 0: WP0.
- AUT-2a (Wave 1): WP1, WP2, WP3, WP5, WP6, WP8, WP9.
- AUT-2b (Wave 2): WP4 and WP7.
- NO-leg and exit labels become *admissible* only in AUT-2b. In AUT-2a, every row, NO legs included, is a pre-epoch `unattributed` row.

### AUT-2.WP0: `venue_positions_read`, the reviewed egress dependency (Wave 0, before AUT-2a; RB-2)
- **Files.**
  - `src/breezy/runtime/venue_positions_read.py`
  - `scripts/venue/polymarket_us_shape_capture.py` (re-import `validate_endpoint`; byte-identical behaviour)
  - `tests/unit/test_venue_positions_read.py`
  - The coverage list of `test_execution_egress_firewall_guard` grows by one module, and its assertions are unchanged.
- **RED first** (`tests/unit/test_venue_positions_read.py`):
  - `::test_poststop_venue_read_is_get_only` (ARCH §4.7: one call attribute `get_authenticated`, the literal, `cursor`-only queries, the page cap)
  - `::test_literal_equals_portfolio_positions_path`
  - `::test_module_imports_no_order_path`
  - `::test_follows_cursor_to_eof_else_incomplete`
  - `::test_page_cap_is_pins_poststop_max_pages`
  - `::test_quota_refusal_maps_to_quota_refused`
  - `::test_output_has_no_account_or_order_ids`
  - `::test_credentials_from_polymarket_env_never_operator_env`
  - `::test_validate_endpoint_moved_byte_identical`
  - `::test_real_default_client_on_fake_transport` (L-55)
- **GREEN.** All of the above pass, and the egress guard passes with the module in its covered set. The independent security review of the egress dependency is recorded in the WP evidence before AUT-2a starts.
- **Activation.** It is a library; it goes live with WP9.

### AUT-2.WP1: root cause, monitor scoping, portfolio-roi scorer status (AUT-2a; no Wave 0 dependency; start now)
- **Scope.**
  - The evidence note `docs/evidence/AUT-2_rc_monitor_pnl_2026-10-03.md` (§3.1, with H3 verified from `PRIVATE_portfolio_roi_2026-09-30.json`, classification only).
  - The family filter and `NO_MONITOR_FOR_KIND`.
  - `roi_status` and `--status-only` in the report (the scorer, P6-9).
  - It never edits `deploy/systemd/portfolio-roi-run.sh` or `deploy/systemd/score-live-trials-run.sh` (AUT-6; RB-11).
- **Files.** `scripts/analysis/position_monitor_nightly_report.py`; `scripts/analysis/portfolio_roi_report.py` (the `roi_status` field, the uncovered-fill count and `--status-only` only).
- **RED first:**
  - `tests/unit/test_position_monitor_nightly_report.py`: `::test_bound_report_excludes_other_family_summaries`, `::test_bound_report_keeps_own_family_rows`, `::test_fq_kind_reports_no_monitor_for_kind`, `::test_unbound_report_unchanged_golden`, `::test_scored_trial_without_summary_is_not_a_row`.
  - `tests/unit/test_portfolio_roi_report.py`: `::test_status_only_reports_gated_unlabelled_fq_when_uncovered_fills`, `::test_status_only_ok_at_zero_uncovered`, `::test_gated_unlabelled_fq_publishes_no_roi_figure`.
- **GREEN.**
  - The 10-04 FQ monitor report shows `positions: 0` plus `NO_MONITOR_FOR_KIND`, and the v4 report still shows −0.37.
  - `portfolio_roi_report.py --status-only` prints `GATED_UNLABELLED_FQ unlabelled=11` (or more), never `OK`, until WP6.
- **Activation.** Immediate. Scripts are read at each fire; verify in the journal after the first fire.

### AUT-2.WP2: C2 store, fill source, epoch, attribution, completeness (AUT-2a; after ARCH-0)
- **Files.**
  - `src/breezy/persistence/autonomy/{label_store,net_position}.py`
  - `src/breezy/analysis/labeling/{constants,fill_source,epoch,attribution,instrument_facts,completeness}.py`
  - `scripts/analysis/score_live_trials.py` (import only)
- **RED first:**
  - `tests/unit/test_aut2_label_store.py`:
    - `::test_schema_is_exact_arch_label_v1` (column for column against the Wave 0 pinned schema, including `p_raw_at_decision`, `p_source`, `reconciliation_source`, `reconciliation_delta`, `net_position_key`)
    - `::test_p_source_enum_is_exact` (`{c1_decision, artefact_recompute, none}`)
    - `::test_dedupe_keeps_max_label_seq`
    - `::test_unknown_schema_version_refused`
    - `::test_atomic_write_no_partial_file`
    - `::test_money_columns_are_string_decimal`
    - `::test_unmapped_scorer_reason_refused`
    - `::test_c1_source_with_null_p_refused`
    - `::test_consumer_gate_rule_is_shared`
    - `::test_labels_consumable_false_on_failed_identity_unresolved_or_missing_label`
    - `::test_label_files_are_write_once`
  - `tests/unit/test_aut2_fill_source.py`: `::test_reads_every_fill_through_ro_uri`, `::test_undecodable_fill_is_store_corruption_not_skip`, `::test_fill_source_reads_wal_store_after_writer_exit`, `::test_real_default_reader_against_tmp_store`.
  - `tests/unit/test_aut2_epoch.py`: `::test_absent_epoch_makes_every_fill_pre_epoch`, `::test_post_epoch_requires_order_link`, `::test_post_epoch_fill_without_order_link_is_unresolved`.
  - `tests/unit/test_aut2_attribution.py`:
    - `::test_scorer_never_attributes_by_trial_id_prefix` (Q2, ARCH §4.7)
    - `::test_post_epoch_attribution_is_c1_family_only`
    - `::test_pre_epoch_fill_never_admissible` (Q2)
    - `::test_pre_epoch_family_is_storage_key_only` (AST: no consumer reads `family_id` of a `decision_id=null` row for any statistic)
    - `::test_backfill_rules_never_run_post_epoch`
    - `::test_backfill_disagreement_is_unresolved`
    - `::test_c1_fold_disagreement_alerts_but_never_reattributes`
    - `::test_voided_pair_c1_family_labelled_voided_pair`
    - `::test_drill_flag_taken_from_c1_record`
    - `::test_retired_family_labelled_until_last_fill`
    - `::test_unresolved_writes_write_once_journal_row`
    - `::test_trial_id_is_stored_latch_key`
  - `tests/unit/test_aut2_net_position.py`: `::test_no_fill_offsets_yes_holding_to_netted_venue_qty`, `::test_each_leg_terminal_state`, `::test_sell_nets_against_long`, `::test_net_position_imports_no_adapters`.
  - The six `tests/unit/test_aut2_completeness.py` tests (§3.12).
- **GREEN.**
  - A dry run over the live store (pre-epoch) attributes all 11 FQ fills as `unattributed` rows stored under `pm_us_crh_fq_v1`, and the 9 CRH fills as `legacy_labelled` once WP3 lands.
  - The identity holds with `UNRESOLVED == MISSING_LABEL == 0`. Any UNRESOLVED fill is a finding resolved before WP6 activation, never waived.
- **Activation.** It is a library; it lands live through WP6.

### AUT-2.WP3: FQ and legacy CRH Scorers, entry labels, settlement sources, pre-epoch backfill (AUT-2a)
- **Files.**
  - `src/breezy/analysis/labeling/{fq_scorer,legacy_crh_scorer,decision_link,probability,settlement_source}.py`
  - the `OFFLINE_PLUGINS` entries in `src/breezy/analysis/plugins.py`
- **RED first:**
  - `tests/unit/test_aut2_fq_scorer.py`:
    - `::test_yes_win_and_yes_loss_pnl_net_of_reconciled_fee`
    - `::test_no_leg_win_and_no_leg_loss_pnl`
    - `::test_realized_pnl_equals_score_trial_pnl_times_qty`
    - `::test_fee_unreconciled_excluded_and_alerted`
    - `::test_preliminary_cli_never_settles`
    - `::test_correction_relabels_with_next_label_seq`
    - `::test_window_incomplete_until_all_fills_settle`
    - `::test_window_incomplete_older_than_48h_fails_label_lag`
    - `::test_fill_better_than_ask_persists_slippage_defect`
    - `::test_fallback_trigger_is_score_trial_basis` (6 d 23 h with a venue reading → pending; 7 d without one → pending; 7 d with one → the fallback row; AUT-2 computes no time arithmetic)
    - `::test_fallback_basis_never_admissible`
    - `::test_fallback_pending_window_raises_label_lag_by_design`
    - `::test_canary_and_drill_rows_never_admissible`
  - `tests/unit/test_aut2_legacy_crh_scorer.py`:
    - `::test_retired_kind_keeps_scorer_until_last_fill_labelled` (ARCH §4.7)
    - `::test_legacy_rows_are_unattributed_with_p_source_none`
    - `::test_legacy_rows_emit_no_cash_record`
    - `::test_forecast_ladder_scorer_may_refuse_with_no_fills`
  - `tests/unit/test_aut2_probability.py`:
    - `::test_p_at_decision_is_bought_leg_probability` (ARCH §4.7)
    - `::test_p_raw_at_decision_is_bought_leg_raw_probability`
    - `::test_artefact_recompute_p_raw_equals_p_only_when_recalibration_none`
    - `::test_take_side_disagreeing_with_fill_leg_unmatched`
  - `tests/unit/test_aut2_decision_link.py`:
    - `::test_bridge_joins_on_client_order_id_not_adjacency`
    - `::test_bridge_window_bounds_enforced`
    - `::test_two_takes_in_window_unmatched`
    - `::test_take_after_init_is_not_linked`
    - `::test_unmatched_fill_p_source_none`
    - `::test_unmatched_fill_increments_p_null_count`
    - `::test_bridge_match_rate_reported_for_backfill`
    - `::test_bridge_never_runs_on_post_epoch_fills` (Q2)
    - `::test_real_default_log_reader_on_tmp_file`
  - `tests/unit/test_aut2_settlement_source.py`: `::test_kalshi_settlement_source_refuses_until_twc_reader`, `::test_polymarket_uses_nws_cli_final_latest_revision`.
- **GREEN.**
  - The backfill dry run labels the 5 settled 10-02 FQ fills, and the 10-03 fills after their finals, as `unattributed` rows with `p_source ∈ {artefact_recompute, none}`. The P&L equals the per-fill `score_trial` sum.
  - The measured `bridge_match_rate` over the 11 fills is recorded in the artefact.
  - The 9 CRH fills get `LegacyCrhScorer` rows.
- **Activation.** Through WP6.

### AUT-2.WP4: exit labels (AUT-2b; F6; standard weighted-average cost, Q3)
- **Semantics.** The method is the **standard weighted-average cost method**, fee-inclusive. Within `(family_id, instrument_id)`:
  - The open lots before an exit have `Q = Σ q_i` and `C = Σ (cumulative_cost_i + fee_i)` over BUY records with `ts_event < exit.ts_event`, less the basis already released by prior exits. Then `avg = C / Q`.
  - An exit of `q_x` releases `basis(q_x) = avg · q_x`, giving `realized_pnl_exit = proceeds − exit_fee − basis(q_x)` and `counterfactual_hold_pnl = payoff(settled_outcome)·q_x − basis(q_x)`.
  - The remaining `Q − q_x` keep basis `avg·(Q − q_x)`, apportioned to the remaining entry labels pro rata by quantity.
  - **The per-label basis intentionally differs from the exec client's `avg_px_open`.** `_entry_price_from_records` (`src/breezy/adapters/polymarket_us/exec/client.py:4495-4549`) nets SELL records into the cost, so it reports the **net remaining cost** of the open position. AUT-2 needs a per-label realized figure, which the net remaining cost does not give.
  - **Lifetime identity.** Σ realized over every label of an instrument, at settlement, equals the cash moved on it. That also equals the exec client's lifetime realized P&L, because both methods conserve lifetime cash (the `client.py:208-220` example: 1.60).
  - FIFO is not used.
- **RED first** (`tests/unit/test_aut2_exit_labels.py`):
  - `::test_yes_exit_realized_and_counterfactual`
  - `::test_no_leg_exit_signs`
  - `::test_partial_no_leg_exit_pro_rata_fee_inclusive` (`q_e=3`, `q_x=1`)
  - `::test_counterfactual_includes_entry_fee`
  - `::test_two_entries_one_partial_exit_average_cost`: BUY 1@0.30 fee 0.02 and BUY 1@0.40 fee 0.02, then SELL 1@0.55 fee 0.02. The exit basis is 0.37 and realized is 0.16; the remainder basis 0.37 is split 0.185 per entry label.
  - `::test_average_cost_lifetime_identity_equals_cash_moved` (Q3): win and lose cases, plus BUY 4@0.50, SELL 1@0.60 → lifetime 1.60 at a 1.00 payoff, equal to the exec client figure.
  - `::test_per_label_basis_differs_from_exec_client_net_remaining_cost` (Q3): in the same example, AUT-2's remaining basis is 0.50 per contract and the exec client's `avg_px_open` is 0.4667. The test documents the intended difference.
  - `::test_exit_matching_uses_shared_average_cost_basis` (AST: one definition, in `net_position.py`)
  - `::test_slug_pnl_identity_entry_plus_exit`
  - `::test_record_exit_latch_mismatch_unreconciles`
  - `::test_exit_without_entry_unresolved`
  - `::test_exit_rows_p_source_none_and_inadmissible` (§9A N-3)
- **GREEN.** The fixture identities hold for both legs. Live exits occur only if an exit-capable family is CHAMPION, and today none can be (G17; §9 item 7).
- **Activation.** Through WP6.

### AUT-2.WP5: reconciliation core, verdict builders, Z19 (AUT-2a)
- **Files.** `src/breezy/analysis/labeling/{reconcile,verdicts,prelaunch_intents,delivery}.py`. `portfolio_roi_report.py` is not edited here: C2 cash enters through `reconcile_daily`'s existing `residual_settlements`.
- **L-1 steps before RED:**
  - (i) The archived `PRIVATE_v1_portfolio_positions_open_positions_20260916.positions.json` holds one negative `netPosition` among four rows. Map it to its ledger NO fill to confirm "NO = negative on the YES slug". If it does not map, the first live `venue_positions_read` is the positive control, and the leg rule waits.
  - (ii) The `src/breezy/runtime/submit_intent.py` retire path and `created_ns`, for the backfill only.
  - (iii) **Closed by WP0:** the egress guard covers the GET-only module.
  - (iv) Whether `PositionResolution` carries the fallback payout. If not, the fallback cash cross-check is INCONCLUSIVE, never FAIL.
  - (v) **Closed:** `_cash_between` books no SELL proceeds (`portfolio_roi_report.py:1043-1088,445-468`).
  - (vi) The SELL `cumulative_cost` semantics against the latch `exitPx`.
  - (vii) Whether the activity feed exposes a YES/NO netting event. If not, §3.6.3's INCONCLUSIVE path applies.
- **RED first:**
  - `tests/unit/test_aut2_reconcile.py`, position leg:
    - `::test_position_leg_exact_equality_both_legs`
    - `::test_compared_set_is_ledger_union_page`
    - `::test_venue_slug_without_ledger_fill_fails`
    - `::test_open_ledger_slug_missing_from_page_compares_as_zero`
    - `::test_settled_away_slug_not_compared`
    - `::test_incomplete_snapshot_inconclusive`
    - `::test_quota_refusal_is_inconclusive_never_pass`
    - `::test_node_belief_alone_is_inconclusive`
    - `::test_open_intent_at_snapshot_is_unknown_not_pass`
    - `::test_fills_after_snapshot_fenced_out`
    - `::test_position_settle_grace_pinned`
    - `::test_fill_inside_grace_not_compared`
    - `::test_transient_mismatch_clears_on_next_snapshot`: snapshot k MISMATCH → FAIL, CRITICAL, label `reconciled=False`, `reconciliation_delta≠0` at seq n. Snapshot k+1 MATCH → the row is rewritten at seq n+1 with `reconciled=True`, `reconciliation_delta=0`, `reconciliation_source=venue_get`, and the daily leg passes with `position_mismatches_transient=1`.
    - `::test_governing_comparison_reproducible_from_journal`
    - `::test_standing_mismatch_fails_daily`
    - `::test_per_snapshot_compare_results_written_once`
    - `::test_every_fill_position_compared_before_settlement_else_fail`
    - `::test_stale_snapshot_inconclusive_and_alerts`
    - `::test_two_consecutive_inconclusive_days_alert_critical`
    - `::test_two_consecutive_balance_unknown_days_alert_critical`
  - `tests/unit/test_aut2_reconcile.py`, settlement and cash legs:
    - `::test_settlement_disagreement_unreconciles_and_never_adopts_venue`
    - `::test_pending_settlement_leg_is_inconclusive_not_pass`
    - `::test_fallback_pending_settlement_leg_is_inconclusive`
    - `::test_cash_leg_mixed_day_open_settled_exit` (perturb one `realized_pnl` by 0.02 → FAIL)
    - `::test_cash_tolerance_counts_fills_opened_not_settled`
    - `::test_balance_unknown_day_inconclusive`
    - `::test_yes_and_no_same_rung_cash_timing`
    - `::test_cash_leg_unions_legacy_proceeds_and_capital`
    - `::test_fill_in_both_sources_refused`
    - `::test_exit_proceeds_enter_cash_at_sell_ts_event`
  - `tests/unit/test_aut2_verdicts.py`:
    - `::test_daily_reconciliation_valid_26h`
    - `::test_subject_sha_is_bound_artefact_sha`
    - `::test_action_class_read_from_policy_block_only`
    - `::test_no_policy_ruling_assumption_without_block`
    - `::test_no_cli_final_fails_label_lag_at_24h`
    - `::test_label_lag_clock_starts_at_min_of_settlement_record_and_venue_instant`
    - `::test_lag_clock_stops_only_on_final_label`
    - `::test_label_lag_horizon_pinned_under_max_verdict_validity`
    - `::test_unresolved_and_missing_label_fail_reconciliation`
    - `::test_metrics_include_p_null_and_non_c1_counts`
    - `::test_autonomy_payload_hygiene_scan_covers_aut2_writers`
  - `tests/unit/test_aut2_delivery.py::test_deliver_or_fail_raises_without_delivered_proof`.
  - `tests/unit/test_aut2_prelaunch_intents.py`: `::test_post_stop_observation_records_open_intent_at_poststop`, `::test_missing_post_stop_run_reports_unknown`, `::test_rewritten_created_ns_reports_unknown`, `::test_z19_unknown_is_metric_not_alert`.
- **GREEN.** The dry run shows position PASS on the open 10-03 slugs against a fixture-replayed read, settlement PASS on 10-02, and cash PASS on legacy ∪ C2 since the earliest known balance. The identity holds.
- **Activation.** It is a library; it goes live through WP6 and WP9.

### AUT-2.WP6: label run unit and portfolio-roi scorer rewiring (AUT-2a)
- **Files.**
  - `src/breezy/analysis/labeling/label_run.py`
  - `deploy/systemd/breezy-label-outcomes.{service,timer}`, `deploy/systemd/label-outcomes-run.sh`
  - `scripts/analysis/portfolio_roi_report.py` (the `labels_consumable` gate, the P&L union, the net flag)
  - `deploy/systemd/breezy-score-live-trials.timer` (13:55Z)
  - `deploy/systemd/README.md`
- **RED first:**
  - `tests/unit/test_aut2_label_run.py`:
    - `::test_iterates_offline_plugins_not_family_list`
    - `::test_refusing_plugin_for_non_retired_family_fails_run_no_marker`
    - `::test_no_input_only_when_pending_unresolved_missing_zero`
    - `::test_zero_rows_with_pending_is_pending_not_no_input`
    - `::test_identity_breach_writes_failed_identity_marker`
    - `::test_marker_carries_counts`
    - `::test_marker_written_last_and_write_once`
    - `::test_unreadable_exec_store_exits_nonzero_without_marker`
    - `::test_unreadable_label_store_exits_nonzero`
    - `::test_label_lag_fail_exits_zero_with_verdict_and_critical`
    - `::test_label_run_delivery_failure_exits_nonzero`
    - `::test_label_flock_timeout_skips_exit_zero_and_second_consecutive_is_critical`
    - `::test_stdout_carries_label_outcomes_summary_line`
    - `::test_real_default_paths_on_tmp_home`
  - The Q1 deploy tests in `tests/unit/test_aut2_units_deploy.py` (§3.10) for the label unit and the score-live-trials timer.
  - `tests/unit/test_portfolio_roi_report.py`: `::test_pnl_source_union_labels_and_legacy`, `::test_pass_flag_is_net`, `::test_pending_gt_zero_gates_roi`, `::test_failed_identity_marker_gates_roi`, `::test_unresolved_or_missing_label_gates_roi`.
  - `tests/unit/test_aut2_units_no_expected_failure.py`, parametrised over AUT-2's own units (label-outcomes, aut2-reconciliation, reconcile-poststop, position-monitor-report, family-tally@v2/v4): `::test_every_aut2_unit_exits_zero_on_no_input` and `::test_every_aut2_unit_exits_nonzero_on_genuine_failure`. The portfolio-roi and score-live-trials wrappers are AUT-6's tests.
- **GREEN.**
  - The first 14:15Z run labels the 10-02 FQ fills, with a marker showing `run_outcome=LABELLED, pending=0, unresolved=0, missing_label=0`.
  - The 17:40Z `portfolio-roi` report computes from C2 ∪ legacy and reports `roi_status=OK` behind `labels_consumable`.
  - The unit's measured memory peak is recorded before the timer is enabled (V14).
- **Activation.** Immediate on merge. The coordinator installs and enables the timer and records `daemon-reload` in the evidence. No node or supervisor restart.

### AUT-2.WP7: C1 switch-over, registration gate, compose cross-plan test (AUT-2b, Wave 2; Q4)
- **Prerequisites (Q4).**
  - The **code** needs AUT-1a's C1 library and reader (capture core, `capture_epoch.py`), so it can merge as soon as AUT-1a is merged.
  - The **activation** and the proof window need **AUT-1b**: specifically AUT-1b WP7 (FQ strategy hooks writing `DecisionRecord`/`OrderLink`) and AUT-1b WP8 (the lifecycle actor and the `capture_epoch_start` write at the first LAUNCH of the tagged build). AUT-1b itself starts only after AUT-5a merges (ARCH §5.1, P1-7).
  - The optional `SettlementRecord` `raw_sha256` check needs AUT-1a WP5 (the settlement writer). It is not on the critical path.
  - The compose test needs AUT-5a's compose refusal.
- **Scope.**
  - POST_EPOCH fills switch to C1-only attribution with `p_source=c1_decision`. This is the first admissible row, including the first admissible NO-leg row (1 − `p_hat`, against live C1 NO fills).
  - The registration gate and the compose cross-plan test.
- **RED first:**
  - `tests/contract/test_aut2_scorer_registration.py`: the three §3.3 tests plus `::test_armed_family_with_refusing_scorer_is_refused_at_compose`.
  - `tests/unit/test_aut2_decision_link.py`: `::test_c1_decision_id_join_every_post_epoch_fill`, `::test_post_epoch_p_source_is_c1_decision_for_every_entry_row`, `::test_no_leg_c1_row_p_is_one_minus_p_hat_and_p_raw_one_minus_p_hat_raw`.
  - `tests/unit/test_aut2_fq_scorer.py::test_settlement_record_sha_must_match_cli_raw`.
- **GREEN.** On the first full post-epoch day:
  - 100% of the fills carry a C1 `decision_id`;
  - `non_c1_post_epoch_count == 0` and `p_null_count == 0`;
  - the compose test is green against AUT-5a's merged code.
- **Activation.** Immediate (offline). It takes effect for fills after `capture_epoch_start`, which AUT-1b writes at the 16:50Z LAUNCH on which AUT-1b WP8 activates.

### AUT-2.WP8: canary store and canary path (AUT-2a; Z14)
- **Files.** `src/breezy/persistence/autonomy/canary_store.py`; `label_run --canary`; the proof-window canary-day rule.
- **RED first:**
  - the §3.8 tests
  - `::test_canary_written_only_on_zero_real_fill_day`
  - `::test_portfolio_roi_never_reads_canary`
  - `tests/unit/test_aut2_proof_window.py`:
    - `::test_canary_day_qualifies_only_with_real_recon_pass`
    - `::test_canary_never_satisfies_live_fill_check`
    - `::test_proof_window_refuses_start_before_capture_epoch_and_wp7`
    - `::test_proof_day_fails_on_any_non_c1_entry_row`
    - `::test_proof_window_excludes_pre_epoch_days`
- **GREEN.** A synthetic zero-fill day produces `labels_canary/` rows and no change to `labels/`, the verdict `n` or the completeness counts.
- **Activation.** Immediate.

### AUT-2.WP9: intraday and post-STOP RECONCILIATION producers (AUT-2a; W1, W8)
- **Files.**
  - `src/breezy/analysis/labeling/recon_run.py`
  - `deploy/systemd/breezy-aut2-reconciliation.{service,timer}`, `deploy/systemd/breezy-autonomy-reconcile-poststop.{service,timer}`, `deploy/systemd/aut2-reconciliation-run.sh`
  - the `PRODUCER_SOURCE_SHA256` entry (closure includes `venue_positions_read`)
- **RED first:**
  - `tests/unit/test_aut2_recon_run.py`, intraday mode:
    - `::test_intraday_verdict_valid_8h`
    - `::test_intraday_recon_validity_within_attest_validity`
    - `::test_intraday_recon_period_within_attest_lmax`
    - `::test_intraday_pass_requires_daily_pass_younger_than_26h`
    - `::test_intraday_inherits_daily_fail`
    - `::test_intraday_inconclusive_without_daily`
    - `::test_intraday_emits_health_label_lag`
    - `::test_intraday_reads_venue_net_only_through_venue_positions_read`
    - `::test_intraday_reads_at_most_two_per_hour`
    - `::test_intraday_lock_contention_skips_with_line_exit_zero`
  - `tests/unit/test_aut2_recon_run.py`, post-STOP mode:
    - `::test_post_stop_verdict_produced_after_stop_and_tagged_mode`
    - `::test_post_stop_records_open_intent_at_poststop`
    - `::test_post_stop_reads_exec_store_with_node_stopped`
    - `::test_post_stop_live_node_is_inconclusive_and_z19_unknown` (the PID seam returns a PID; the store fixture raises if opened)
    - `::test_post_stop_uses_runtime_guard_not_a_copy` (AST)
    - `::test_post_stop_real_default_pid_probe_on_tmp` (L-55)
    - `::test_post_stop_without_stop_signal_inconclusive`
    - `::test_post_stop_snapshot_after_stop_plus_grace_compares_every_slug`
    - `::test_post_stop_at_most_two_reads`
    - `::test_post_stop_lock_contention_raises_critical_and_exits_nonzero`
    - `::test_recon_run_delivery_failure_exits_nonzero`
  - `tests/unit/test_aut2_units_deploy.py` (§3.10): `::test_post_stop_slot_ends_before_1645Z`, `::test_intraday_fires_inside_window_match_arch_rows`, `::test_intraday_1635_fire_releases_lock_before_post_stop`, `::test_post_stop_wrapper_emits_critical_on_flock_timeout` (the wrapper is executed against a lock held in tmp), `::test_recon_units_use_own_lock_not_studies_flock`, `::test_recon_units_load_polymarket_env_not_operator_env`, `::test_no_aut2_oneshot_sets_runtime_max_sec`.
- **GREEN.**
  - First day: 48 intraday verdicts (`no_policy_ruling` before the block), each citing a `venue_get` snapshot.
  - One post-STOP verdict before 16:43Z, with no live node and an `open_intent_at_poststop` metric.
  - The measured memory peaks are recorded before the timers are enabled.
- **Activation.** Immediate on merge. The coordinator installs both timers. No node or supervisor restart.

---

## 5. Association

**Consumed:**

| Contract | From | What AUT-2 uses | Fallback before it lands |
|---|---|---|---|
| C2 `label/v1` schema, C4 writer, C6 Protocols, `RefusingPlugin`, `OFFLINE_PLUGINS`, `pins.py` | ARCH-0 | Types, registry, verdict writer, ceilings | WP0 and WP1 need none; WP2 onward wait |
| §4.4 positions-read egress review | ARCH-0 review (filed by AUT-2 WP0) | `venue_positions_read` | WP9 does not merge |
| C1 library, reader, `capture_epoch.py`, `SettlementRecord` | **AUT-1a** | WP7 code; the lag clock's `SettlementRecord` term | The lag clock uses the venue instant (§3.7.2) |
| C1 node writes, `capture_epoch_start` | **AUT-1b** (WP7, WP8) | POST_EPOCH attribution, `c1_decision` p, the proof-window start (Q4) | Every fill is PRE_EPOCH (`unattributed`); the proof window waits |
| C5 fold at `ts_event`, bound sha, voided intervals | AUT-5 | Voided pairs, the consistency check, the verdict subject, pre-epoch storage (b) | Manifest sha; rule (c) |
| Compose refusal; journaled STOP-completion signal | AUT-5a | WP7 cross-plan test; post-STOP step 2 | WP7 does not merge; post-STOP INCONCLUSIVE (SWAP_CANCEL) |
| `autonomy-policy/v1`, `attest_required_detectors` | AUT-5b | Action classes, ruling sha | Verdicts carry `no_policy_ruling`; the restrictive fallback |
| `deliver_with_proof` | AUT-6 | Delivery of every CRITICAL; failure → exit 4 | Interim `emit_alert` + `OnFailure=`; not score-3 evidence |
| Unit-exit semantics of `portfolio-roi` and `score-live-trials` | AUT-6 (P6-9) | The skip marker and `NO_INPUT` | — |

**Provided:**

| Contract | To | Guarantee |
|---|---|---|
| C2 labels `derived/labels/<family_id>/` | AUT-3, AUT-4 | Written by 14:55Z. Consumers call `labels_consumable(marker)`. Only `admissible ∧ p_source=c1_decision` rows count. `p_at_decision` and `p_raw_at_decision` are bought-leg probabilities. |
| C4 `RECONCILIATION` daily (26 h) | AUT-5 | INCONCLUSIVE, including any PENDING leg, never passes |
| C4 `RECONCILIATION` + `HEALTH label_lag` intraday (8 h, :05/:35) | AUT-5 ATTEST (W1) | Validity ≤ `ATTEST_VERDICT_VALIDITY_H`; period ≤ `INTRADAY_ATTEST_VERDICT_PERIOD_MIN` |
| C4 `RECONCILIATION` post-STOP | AUT-5 pre-launch (W8) | 16:41–16:43Z, after STOP and a passed live-node guard; `venue_get` source; `open_intent_at_poststop` |
| Drill and voided-pair C2 rows | AUT-6 detectors, AUT-5 drawdown (W12) | Present, never dropped |
| `net_signed_qty` | AUT-5 `entry_guard` | One netting rule (C2 leg sign) |
| `portfolio_roi_report.py --status-only` | AUT-6 (`portfolio-roi-run.sh` NO_INPUT branch, optional) | `GATED_UNLABELLED_FQ unlabelled=<n>` or `OK`, exit 0. If AUT-6 does not adopt it, unlabelled fills stay visible through the AUT-2 RECONCILIATION and `label_lag` verdicts. |
| Z19 metric | AUT-5 policy review | `open_intent_at_poststop`, directly observed at 16:41Z |

**Order and parallelism.**
- Wave 0: WP0.
- WP1 starts now.
- After ARCH-0: WP2 → WP3 → {WP5, WP8} → {WP6, WP9}, all AUT-2a.
- AUT-2b: WP4 (after WP3) and WP7 (code after AUT-1a; activation after AUT-1b WP8).
- File ownership is disjoint from the siblings. AUT-2 never edits `src/breezy/app/trade.py`, `src/breezy/runtime/settings.py`, `src/breezy/runtime/trade_supervisor*.py` (it imports two functions read-only), `deploy/systemd/portfolio-roi-run.sh` or `deploy/systemd/score-live-trials-run.sh`.

---

## 6. Live-proof protocol

- **Artefact.** `/home/jon/.local/share/breezy/evidence/aut2_live_proof/window_<start>_<end>.json`, written by `label_run --proof-window` from the stores.
- **Per qualifying day it records:**
  - the real attributed fill count, and the final-labelled count, which must be equal;
  - the identity counts, with `unresolved == missing_label == 0`;
  - `non_c1_post_epoch_count == 0` and `p_null_count == 0`;
  - the daily RECONCILIATION verdict id (PASS), the post-STOP verdict id (PASS) and the intraday verdict count with any non-PASS ids;
  - `position_mismatches_transient`, max label lag (≤ 24 h) and `fills_never_position_compared == 0`;
  - the canary fields (§3.8).
- **Window totals:** real fills (≥ 5), NO-leg fills, exits, the marker files and the systemd invocation ids.
- **Window rule.**
  - A day qualifies with ≥ 1 real fill, or as a canary day.
  - Zero-fill non-canary days extend the window.
  - Canary and drill fills never count toward the ≥ 5.
  - Any entry row with `p_source ≠ c1_decision` on a window day fails that day and restarts the window.
- **Window start (Q2, Q4).** The window starts on the first UTC day that satisfies all of:
  - fully after `capture_epoch_start`, so every window fill is POST_EPOCH;
  - WP0–WP3, WP5, WP6, WP7, WP8 and WP9 are active;
  - AUT-6 `deliver_with_proof` is live.
- `label_run --proof-window` refuses an earlier start (`test_proof_window_refuses_start_before_capture_epoch_and_wp7`). The bridge and pre-epoch rows can never be proof-window evidence.
- **NO leg and exit.** "If one occurs": each is listed, or the artefact records `no_leg_fills=0` and `exit_fills=0` with the capability shown. FQ has no exit (G17), so WP4 is fixture-proven.
- **ETA (Q4, recomputed).**
  - Assumptions: about 5 FQ fills a day (README; AUT-1 measured 2–3 takes a day, and ≥ 5 in 7 days holds either way).
  - WP0 lands with Wave 0, about 10-08. AUT-2a lands by about 10-14.
  - AUT-1b WP8 writes `capture_epoch_start` at the **10-14 LAUNCH**. This is AUT-1 r3 §6's estimate, assuming AUT-1a by about 10-10 and AUT-5a by about 10-13. WP7 is merged beforehand and takes effect at the epoch.
  - The first full post-epoch day is 10-15, so the window runs 10-15..10-21. The last settlements fall at 10-22 12:00Z and are labelled at 14:15Z.
  - **Earliest: 2026-10-22.**
  - **Plan: 2026-10-30.** This carries AUT-1's own 7-day planning slack on the epoch, which is AUT-2's critical path, and absorbs one window restart.
  - r3's 10-27/11-06 is superseded: the C2-widening prerequisite is gone (RB-5), and the dependency is now the AUT-1b epoch rather than "AUT-1 C1 live".
  - The plan date is before DST (11-02) and far before the KILL (2027-01-25).
- **Evidence class.** "Machinery proven, edge unproven."

---

## 7. Score-3 verification checklist

| Criterion | Check |
|---|---|
| (a) unattended | `journalctl --user -u breezy-label-outcomes.service -u breezy-aut2-reconciliation.service -u breezy-autonomy-reconcile-poststop.service --since <window>` shows only timer starts, and the invocation ids are in the artefact. `git log --since <window> -- src/breezy/analysis/labeling src/breezy/runtime/venue_positions_read.py deploy/systemd/*label* deploy/systemd/*aut2* deploy/systemd/*reconcile-poststop*` is empty. |
| (b) family-agnostic | `scripts/ci/run_tests_no_egress.sh -k "aut2_scorer_registration or iterates_offline_plugins or family_plugin_exact_set or retired_kind_keeps_scorer"` passes, including the compose test. `/usr/bin/grep -n "pm_us_" src/breezy/analysis/labeling/*.py` gives 0 hits. |
| (c) fails closed | These tests pass: `refusing_plugin_for_non_retired_family_fails_run_no_marker`, `unreadable_exec_store_exits_nonzero_without_marker`, `deleting_one_label_fails_identity`, `missing_label_bucket_counts_as_failure`, `unresolved_fill_fails_identity`, `post_epoch_fill_without_order_link_is_unresolved`, `pre_epoch_fill_never_admissible`, `scorer_never_attributes_by_trial_id_prefix`, `venue_slug_without_ledger_fill_fails`, `incomplete_snapshot_inconclusive`, `quota_refusal_is_inconclusive_never_pass`, `node_belief_alone_is_inconclusive`, `pending_settlement_leg_is_inconclusive_not_pass`, `post_stop_live_node_is_inconclusive_and_z19_unknown`, `post_stop_lock_contention_raises_critical_and_exits_nonzero`, `label_run_delivery_failure_exits_nonzero`, `every_aut2_unit_exits_nonzero_on_genuine_failure`, `no_aut2_oneshot_sets_runtime_max_sec`. |
| (d) detected, alerted, delivered | `/home/jon/.local/share/breezy/evidence/alerts/<date>/` holds a `delivered=true` record for an injected `label_lag`. The drill: a tmp-HOME fill past the venue instant with no CLI final, run through the production entrypoint against the real endpoint. |
| (e) RED→GREEN | Per-WP artefacts; gate EXIT=0 after each merge; `lint-imports` prints `kept, 0 broken`. |
| (f) live proof | `evidence/aut2_live_proof/window_*.json`: 7 qualifying post-epoch days and ≥ 5 real fills. Daily: identity holds with `unresolved == missing_label == 0`, `non_c1_post_epoch_count == 0`, and every daily and post-STOP verdict is PASS. The ids resolve under `/home/jon/.local/share/breezy/derived/verdicts/pm_us_crh_fq_v1/<date>/`. |
| Horizons and units | `test_label_lag_horizon_pinned_under_max_verdict_validity`, `test_intraday_recon_validity_within_attest_validity`, `test_intraday_recon_period_within_attest_lmax`, `test_post_stop_slot_ends_before_1645Z`, `test_label_slots_clear_launch_window`, `test_position_settle_grace_pinned`, `test_fallback_pending_window_raises_label_lag_by_design`; `systemctl --user cat breezy-label-outcomes.service breezy-aut2-reconciliation.service breezy-autonomy-reconcile-poststop.service` shows `TimeoutStartSec=` and no `RuntimeMaxSec=`. |
| Egress | `test_poststop_venue_read_is_get_only`; `test_execution_egress_firewall_guard` with `venue_positions_read` in its coverage. |
| Root cause | `docs/evidence/AUT-2_rc_monitor_pnl_2026-10-03.md`; FQ monitor report `positions: 0` with `NO_MONITOR_FOR_KIND`. |
| No expected failures | `systemctl --user list-units --state=failed 'breezy-*'` shows no AUT-2 unit in the window; both `test_aut2_units_no_expected_failure` tests pass. |
| Z14 / Z19 | `test_aut2_canary_isolation` passes, with its positive controls; each post-STOP verdict carries `open_intent_at_poststop`, and the line `Z19 open_intent_at_poststop days=` appears. |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| Positions read races trading | Fence `ts_event ≤ snapshot_ns − 60 s`; grace slugs are not compared; an open intent gives INCONCLUSIVE; the post-STOP read is taken ≥ 60 s after STOP and after the last fill. |
| `portfolio` quota shared with the node | ≤ 2 intraday reads an hour at :05 and :35; a 429 gives INCONCLUSIVE for that slot with no retry; two consecutive INCONCLUSIVE days raise a CRITICAL (U5, Z5). |
| Egress surface grows | One GET-only module reusing the existing GET-only client, method-less transport and quota key, under the NO-SEND guard; its own test pins the call; it is reviewed in Wave 0 (WP0). |
| Grace too short | It shows as transient mismatches, each a CRITICAL. The constant changes only through a reviewed commit that updates the pin test. |
| Transient clearing hides a real break | Only the label is rewritten. The FAIL verdict and its CRITICAL stay on record, and a standing mismatch fails the day. |
| YES/NO netting event unobservable | INCONCLUSIVE cash days, never FAIL or PASS; two consecutive raise a CRITICAL. |
| Legacy cash omitted or double-counted | Union through the existing parameters; `LegacyCrhScorer` rows emit no cash record; overlap is refused; drop-either-source tests. |
| Pre-epoch rows leak into statistics | `unattributed`, `admissible=False`, `p_source ≠ c1_decision`; `test_pre_epoch_family_is_storage_key_only`; AUT-3 and AUT-4 consume only `c1_decision`. |
| Proof ETA hostage to AUT-1b and AUT-5a | Accepted and stated (Q4); the machinery runs pre-epoch anyway. |
| C2 fallback widening never lands | Non-blocking: fallback rows are inadmissible through `settlement_basis` (§3.5). |
| Post-STOP producer late, dead, contended, or facing a live node | SWAP_CANCEL with the incumbent unaffected (§4.4); CRITICAL on contention or a live node; `OnFailure=` on a crash. |
| Oneshot overruns | A unit-level `TimeoutStartSec` on every AUT-2 oneshot, `RuntimeMaxSec` refused by test (Q1); additive window arithmetic. |
| Alert delivery fails silently | Exit 4 trips `OnFailure=`; AUT-6's `alerts_undeliverable` reads the delivery records. |
| Exec-store read with the node stopped | Runtime guard reused; WAL-after-writer-exit test; a read failure exits 1. |
| Memory (30 GiB host; the template's 31 GB) | Label run `MemoryMax=1G` under the studies flock (precedent 137 MB). Reconcile units 512M on their own lock, never concurrent with each other, within ARCH's ≤ 4G own-lock budget. Peaks are measured before enabling (V14). Nothing heavy runs 01:00–04:30Z. |
| Shared venv | Briefs name `/home/jon/breezy/.venv/bin/python`; no `uv`, `pip` or `uv run` (L-51). |
| Concurrent agents | Disjoint file ownership, including the AUT-6 wrappers; per-agent scratchpads; no `git stash`; worktrees fast-forwarded first. |
| Statistical capacity | Not an AUT-2 claim; ≥ 5 real fills in about 1–2 days. |
| KILL 2027-01-25 | After a TERMINAL KILL, labels continue for the remaining settlements, NO_INPUT runs exit 0, and the proof window pauses. |
| NWS outage | Rows stay pending; HEALTH FAIL at 24 h with `cause=awaiting_venue_fallback`; no nearby-station substitution. |
| Kalshi family admitted | The TWC source refuses, and the gate fails until a reviewed reader exists. |

---

## 9. Binding-constraint compliance

- **Nautilus immutability.** No Nautilus file is touched. Native `ClientOrderId`/`TradeId` joins and its log lines are only read.
- **The two caps.** Never read, written or derived. `test_autonomy_never_reads_or_writes_operator_controls` covers `src/breezy/analysis/labeling/` and `src/breezy/runtime/venue_positions_read.py`. Credentials come from `polymarket.env`, never `operator.env`.
- **`allow_short=False`.** Untouched. "Short YES" is the venue's reporting convention and is only read.
- **NO-SEND.** The analysis code makes no network call. `venue_positions_read` is GET-only and covered by `test_execution_egress_firewall_guard`, which is not weakened, and by `test_poststop_venue_read_is_get_only`.
- **Master enablement and permit.** Never read or written. The units are offline; no supervisor or node change. The post-STOP guard reads a PID and refuses; it never signals a process.
- **PREREG via ruling.** No statistical semantics are defined. Action classes and the ruling sha come only from the AUT-5 policy block, or the `no_policy_ruling` restrictive fallback.
- **Safety tests never weakened.** Every settlement, contract and NO-SEND test is unchanged. `trial_scorer.py` and `reconcile_daily` are unchanged. The new tests and positive controls only add strength. Wrapper tests owned by AUT-6 are not touched.
- **Coordinator decisions.**
  - HOLDOUT: AUT-2 labels every climate day; holdout and forward-window selection belong to the consumers under `RULING_holdout_freeze_and_forward_window_2026-10-03`, and AUT-2 restates no version of it.
  - ALPHA: AUT-2's verdicts are deterministic equality checks with `n_min` reason `deterministic_equality_check`; they charge no α and carry no `k_life`.
  - ROLLBACK-FAILURE: AUT-2 writes no C5 row and introduces no `cause_code`.
- **Paths.** Every path in this plan is absolute or repo-root-relative.

### 9A. Residual notes for ARCH (non-blocking; the plan already conforms)
- **N-1** (r3 C-1, reduced; Q2). This is the only remaining C2 widening request: the `excluded_reason` value `venue_fallback_settlement`. Until it lands, fallback rows are `admissible=False` through `settlement_basis` (§3.5), so nothing waits on it. r3's request for the two position-compare columns is withdrawn, because conforming to `reconciliation_delta`, `reconciliation_source` and the write-once journal covers it (RB-4). `p_null_reason` is withdrawn in favour of `p_source=none`.
- **N-2.** `artefact_recompute` in AUT-2 means "the bound artefact's own decision-time p, recovered from the node's log". It is never a fresh offline computation (L-2). The enum is unchanged, and such rows are never admissible.
- **N-3.** Exit-role rows carry `p_source=none` and are inadmissible by role. No exit-capable kind can be CHAMPION today (G17; ARCH §9 item 7).
- **N-4** (r3 C-8). The label-lag clock is the earlier of `SettlementRecord` and the venue instant, which is stricter than C2. A fallback-pending lag FAIL is expected and alerted; AUT-5's policy should map `label_lag` to a non-freezing class. That is a policy-ruling matter, not an ARCH change.

---

## 10. Self-score (author's estimate; not evidence)

| Axis | Max | Score | Note |
|---|---:|---:|---|
| Fidelity | 20 | 19 | Rev 9.2 §10 obligations quoted and mapped one-for-one. C2 implemented without added columns. ARCH test names and unit names adopted. r3 C-items resolved or reduced to non-blocking notes. |
| Correctness | 20 | 18 | Positions-read transport, the literal, credentials and the cost rule verified in code (`http.py:69,152`, `transport.py:168-177`, `endpoints.py:97`, `env.py:94`, `factories.py:241`, `client.py:4495-4549`). Netting observability and the fallback payout stay **INFERRED** behind L-1 (iv)/(vii), each with an INCONCLUSIVE fallback. |
| Specificity | 15 | 14 | Constants, unit timings, exit codes, buckets, marker fields, the consumer predicate and test names are explicit. |
| Acceptance | 20 | 19 | Each Q-item has named RED tests and checklist rows. The proof start is tied to `capture_epoch_start`. Score 3 depends on AUT-1b, AUT-5a and AUT-6, all named with fallbacks. |
| Autonomy-safety | 15 | 15 | Fails closed on identity, the epoch, pending legs, quota refusal, a live node, lock contention and delivery failure. No cap, permit or firewall surface; the egress addition is reviewed and GET-only. |
| Reuse | 10 | 9 | `score_trial`, `reconcile_daily` through existing parameters, `ResidualSettlement`, the runtime guard, the GET-only client and the node log. Two new minimal pieces, the positions module and `LegacyCrhScorer`, are ARCH-mandated. |
| **Total** | **100** | **94** | r3 was reviewer-scored 80 (3 HIGH). r4 closes Q1–Q4 and rebases onto frozen Rev 9.2. |

---

## §R4 Disposition (review `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-2-r3-merged.md`; rebase onto FROZEN ARCH Rev 9.2, sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`)

The r3 disposition of B1–B13 (13/13 FIXED) is in `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r3.md` § "§R3 Disposition". r4 keeps every one of those fixes, except where a rebase change below supersedes one (B4 wording by Q3, B5 bridge cross-check by Q2, B7 wrapper edits by RB-11, B1 columns by RB-4).

| ID | Status | Where / evidence |
|---|---|---|
| **Q1** | FIXED | §3.10: every AUT-2 oneshot uses a unit-level `TimeoutStartSec` covering every `ExecStart=` and the flock wait. The constants are `LABEL_TIMEOUT_START_S=1800`, `RECON_INTRADAY_TIMEOUT_START_S=240`, `POST_STOP_TIMEOUT_START_S=100` and the `*_FLOCK_WAIT_S` set (§3.2). `RuntimeMaxSec` is removed from §3.2, §3.10, §3.11, WP6, WP9, the tests and the constant names. Tests: `test_no_aut2_oneshot_sets_runtime_max_sec` (with a positive control), `test_aut2_oneshots_set_timeout_start_sec_equal_to_constants`, `test_label_slots_clear_launch_window` (14:15Z → 14:55Z and 05:00Z → 05:40Z, both clear of [16:30Z, 17:10Z)), `test_intraday_fires_inside_window_match_arch_rows`, `test_post_stop_slot_ends_before_1645Z`, `test_score_live_trials_slot_clears_launch_window`. |
| **Q2** | FIXED | §3.4.2–§3.4.4, §3.5, §3.12, WP2, WP3, WP7. `trial_id` is the stored latch key (`test_trial_id_is_stored_latch_key`). Attribution is C1 `family_id` only (`test_scorer_never_attributes_by_trial_id_prefix`). The `p_source` enum is `{c1_decision, artefact_recompute, none}` (`test_p_source_enum_is_exact`), and `p_raw_at_decision` is emitted (`test_p_raw_at_decision_is_bought_leg_raw_probability`). Rules (b)/(c) and the log bridge are backfill-only storage paths (`test_backfill_rules_never_run_post_epoch`, `test_bridge_never_runs_on_post_epoch_fills`). Pre-`capture_epoch_start` fills are `unattributed`, inadmissible, `p_source ∈ {artefact_recompute, none}` (`test_pre_epoch_fill_never_admissible`). C-1 is cut further than requested: only `venue_fallback_settlement` remains, and it is non-blocking (§9A N-1, RB-4, RB-5). |
| **Q3** | FIXED | WP4 and the §2 row: the method is "the standard weighted-average cost method", and the claim "same rule as the exec client" is removed. The plan states that the per-label basis intentionally differs from the exec client's `avg_px_open` (net remaining cost, `client.py:4495-4549`). The lifetime identity is kept (`test_average_cost_lifetime_identity_equals_cash_moved`), and the difference is documented (`test_per_label_basis_differs_from_exec_client_net_remaining_cost`). |
| **Q4** | FIXED | WP7 "Prerequisites" and §6 ETA: WP7's code needs AUT-1a (C1 library and reader, `capture_epoch.py`). Its activation and the proof window need **AUT-1b** WP7 and WP8 (strategy hooks plus the `capture_epoch_start` write, after AUT-5a). The optional `SettlementRecord` check needs AUT-1a WP5. Recomputed ETA: epoch at the 10-14 LAUNCH, window 10-15..10-21, earliest 2026-10-22, plan 2026-10-30. |
| RB-1 | APPLIED | §0 cites Rev 9.2 by full sha, plus errata E-1..E-4. §1 re-quotes the Rev 9.2 §10 obligations verbatim, with a one-for-one section map. |
| RB-2 | APPLIED | §2, §3.2.1, WP0: `src/breezy/runtime/venue_positions_read.py` (GET-only, `portfolio` quota, literal `/v1/portfolio/positions`, `cursor` to `eof` under `POSTSTOP_POSITIONS_MAX_PAGES`, `polymarket.env`). It is a reviewed Wave 0 egress dependency. r3's `scripts/venue/polymarket_us_positions_pull.py` and its two-`ExecStart` design are withdrawn. |
| RB-3 | APPLIED | §3.6.1 source rules: `venue_get` only; :05/:35, ≤ 2 reads an hour; quota refusal → INCONCLUSIVE; `node_belief` alone → INCONCLUSIVE. Tests in WP5 and WP9. |
| RB-4 | APPLIED | §3.5, §3.6.1: `reconciled`, `reconciliation_delta`, `reconciliation_source`, `net_position_key` from ARCH C2. The governing comparison is reproducible from the write-once journal (`test_governing_comparison_reproducible_from_journal`). The two position-compare columns are withdrawn. |
| RB-5 | APPLIED | §3.5: the fallback is inadmissible through `settlement_basis == nws_final` (`test_fallback_basis_never_admissible`). No label write waits on an ARCH revision. Upstream no longer lists a C2 widening. |
| RB-6 | APPLIED | §3.3, WP3: `LegacyCrhScorer` gives CRH kinds a real `Scorer` until their last fill is labelled (P2-6; `test_retired_kind_keeps_scorer_until_last_fill_labelled`). r3's `LEGACY_COVERED` bucket becomes C2 rows (`legacy_labelled`). Cash stays legacy (`test_legacy_rows_emit_no_cash_record`). |
| RB-7 | APPLIED | §3.7.1–§3.7.2: the separate `label_coverage` HEALTH detector is withdrawn, and coverage is a RECONCILIATION FAIL (ARCH §5 AUT-2 writes). The label-lag clock is `min(SettlementRecord.ts_ns, venue instant)` (`test_label_lag_clock_starts_at_min_of_settlement_record_and_venue_instant`). |
| RB-8 | APPLIED | §3.2.2: snapshots, comparisons, unresolved journals and markers are write-once, and the reconcile lock is named. Rows are added to `test_autonomy_files_have_one_writer`. |
| RB-9 | APPLIED | §3.11: intraday validity ≤ `pins.ATTEST_VERDICT_VALIDITY_H`; period ≤ `pins.INTRADAY_ATTEST_VERDICT_PERIOD_MIN`. Two tests replace r3's ad hoc invariant. |
| RB-10 | APPLIED | §0, §4 slice map: Wave 0 WP0; AUT-2a WP1/2/3/5/6/8/9; AUT-2b WP4/WP7 (decision_id join, admissible NO-leg and exit labels), per ARCH §5.1. |
| RB-11 | APPLIED | §3.10, WP1, WP6, §5: `portfolio-roi-run.sh` and `score-live-trials-run.sh` exit semantics belong to AUT-6 (P6-9). AUT-2 keeps the scorer (`roi_status`, `--status-only`, `labels_consumable`, P&L union) and the score-live-trials timer move. r3's wrapper tests are dropped from AUT-2. |
| RB-12 | APPLIED | §3.9, §3.11: the Z19 metric `open_intent_at_poststop`, the ARCH name. |
| RB-13 | APPLIED | §3.7.3: delivery records live under `evidence/alerts/<date>/` through `deliver_with_proof` (ARCH §4.6). |
| RB-14 | APPLIED | §9: HOLDOUT, ALPHA and ROLLBACK-FAILURE stated, none restated differently. |
| RB-15 | APPLIED | Every path is absolute or repo-root-relative (`src/breezy/...`, `/home/jon/.local/share/breezy/...`, `docs/plans/backlog/AUTONOMY_2026-10-03/...`). |
| RB-16 | APPLIED | r3 §10: C-1 reduced to N-1; C-2 resolved (ARCH C2 P2-2 slots); C-3 resolved by conforming (RB-7); C-4 resolved (ARCH §4.4 Z19); C-5 resolved (G35, P2-5); C-6 resolved (ARCH C6 P2-6, RB-6); C-7 resolved; C-8 becomes N-4, a policy note. |

Counts: 4 of 4 Q-items FIXED, 0 REJECTED; 16 rebase changes APPLIED. Every contradiction with frozen ARCH Rev 9.2 is resolved by conforming the plan; no ARCH deviation remains, only the non-blocking notes N-1..N-4.

# AUT-2: outcome labeling (scoring, P&L, reconciliation). Plan r1

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-2 |
| Title | Outcome labeling: family-agnostic scorer, C2 label store, net-position and cash reconciliation |
| Round | r1 (2026-10-03) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` Rev 3, snapshot sha256 `66002f49ca33515e3515102d9dbb4134935e0573f85a98a5c41f1352f91361af`, plus the pending Rev 4 deltas Z1–Z20 (`reviews/ARCH-r3-merged.md`), treated as applied. Z14 (canary store) and Z19 (AMBIGUOUS at 16:45Z) are owned here. |
| Repo state read | `4b8347a6` on `feat/data-capture-and-risk`; live artefacts under `~/.local/share/breezy/` as of 2026-10-03 ~04:00Z |
| Current score | 1 (README) |
| Target | 3 |
| Upstream | ARCH-0 (Wave 0: `persistence/autonomy/` schemas, C6 Protocols, `RefusingPlugin`, `pins.py`); AUT-1 (C1 `decision_id` tag, `DecisionRecord`, `OrderLink`, `SettlementRecord`); AUT-6 (`deliver_with_proof`, Z13); AUT-5 (policy block: `detector → action_class`, `prereg_ruling_sha256`, bound artefact sha per Z1) |
| Downstream | AUT-3 (C2 `(p_at_decision, settled_outcome)` for `rung_recalibration`); AUT-4 (C2 admissible labels for `LIVE_SEQUENTIAL`, champion slippage for `FORWARD_SHADOW`); AUT-5 (C4 `RECONCILIATION` for §4.4 preconditions and ATTEST, Z5); AUT-6 (C4 `HEALTH label_lag` and label-coverage events) |

---

## 1. Goal state

**README AUT-2 score-3 criterion (verbatim):**
- Scoring is a family-agnostic scorer contract. A family manifest cannot register or send without a scorer, enforced by a registration-time test.
- Every fill, entry or exit, YES or NO leg, is labelled automatically within 24 h of settlement with: the settled outcome, the realised P&L net of the reconciled fee, the forecast probability at decision, and the counterfactual hold result for exits.
- Labels are reconciled against venue settlement and balance evidence within a stated tolerance.
- Sign and leg conventions are pinned by tests: the venue nets a NO holding as short YES.
- No unit fails as a matter of expected behaviour.

**README AUT-2 live proof (verbatim):** "every live fill over 7 consecutive days is labelled, with reconciliation passing on each day, covering at least one NO-leg fill if one occurs and at least one exit if one occurs. All of it is run by the timers with no hand step."

**ARCH §10 AUT-2 obligations (verbatim):** "the −0.37/+0.37 root cause with artefact evidence before any scorer change; the per-leg reconciliation tolerance; the RECONCILIATION verdict horizon used by §4.4; exclusion of `canary` and `drill` rows; the label-lag alert."
Rev 4 additions: **Z14** canary fills live in a separate canary store with its own Scorer input, and a test proves reconciliation and `entry_guard` never read it. **Z19** AUT-2 measures how often an AMBIGUOUS intent is still open at 16:45Z.

Section map: root cause §3.1 and WP1; per-leg tolerance §3.6; verdict horizon §3.7; canary and drill exclusion §3.4, §3.8 and WP8; label lag §3.7; Z19 §3.9.

---

## 2. L-1 null hypothesis and reuse

Rule: each new component names the capability it was checked against, with file:line, and a verdict. Nautilus is the first candidate. Nautilus has no settlement scorer, no label store and no venue-versus-ledger reconciliation for an offline process. Its `Position.realized_pnl` covers only in-node lifetime and excludes settlement payouts that arrive after the node stops, so it is not a label source.

| New component | Checked against | Verdict |
|---|---|---|
| C2 label store `persistence/autonomy/label_store.py` | `scored_trial_store.py:24-31,60-89` (append-only parquet, `(trial_id, max score_seq)` dedupe); `ScoredTrial` (`trial_scorer.py:131-155`) | **Reuse the conventions, not the schema.** `ScoredTrial` has no `family_id`, leg, role, probability, decision id or reconciliation columns (G8), and ARCH C2 keeps the scored-trial store untouched. The writer copies the parquet, atomic `os.replace` and dedupe idiom. |
| Settlement resolution | `score_trial` and `_resolve_settlement_basis` (`trial_scorer.py:167-265`); `read_climate_day_including_corrections` (used at `k1_cheap_open_settlement.py:976`); `default_registry().settlement_site(venue, city)` (`score_live_trials.py:778`); `WeatherBucketFacts.contains` | **Reuse unchanged.** Entry labels call `score_trial` on a `FilledTrial` built by the new fill source, so final-only, latest-revision, LST climate-day and correction handling stay in the one pure, already-tested function (nws-cli-settlement skill). |
| Rung resolution from the slug | `_read_bucket_facts_by_instrument_id` and `_bucket_facts_from_instrument_id` (`score_live_trials.py:579,620`) | **Reuse.** Moved into `breezy.analysis.labeling.instrument_facts` by a pure extraction (L-46: grep the containment tests first), and re-imported by `score_live_trials.py` so its behaviour stays byte-identical. |
| Leg and base-slug netting | `leg_of_symbol` (`domain/instrument_leg.py:58`); `base_slug_of` and `leg_of` (`symbology.py:289-298`); `PolymarketUSExecutionClient._durable_net_qty` (`exec/client.py:3442`) | **Reuse `leg_of_symbol`** (domain layer, importable from analysis). The netting rule is one function, `net_signed_qty(fills)`, defined once in `persistence/autonomy/net_position.py` and used by both the AUT-2 reconciler and ARCH's `entry_guard.rung_has_net_position`. If Wave 0 has already placed it in `entry_guard.py`, AUT-2 imports it from there and adds nothing. The exec client's method is node-bound (instance state) and is not callable offline. |
| Durable fill reader | `DurableFillRecord.from_bytes` (`exec/client.py:1004-1066`); `FILL_KEY_PREFIX` and `FILL_BY_DAY_KEY_PREFIX` (`:408-415`); the read-only URI reader `read_family_halt_rows_readonly` (`trial_day_latch.py:354-379`, G6); `read_filled_trials_state_db` (`analysis/prereg_admission.py:234`) | **Reuse `from_bytes` and the G6 `mode=ro` URI.** `read_filled_trials_state_db` is **not reusable for FQ**: it starts from CRH `TrialDayRecord` latches under the manifest's `trial_id_prefix` and expects `venueOrderId` on the latch. The FQ latch has neither (finding F4). The new reader starts from durable fills, which is the right direction for "every fill is labelled". |
| Cash reconciliation | `per_day_tolerance` (`portfolio_roi_report.py:1390-1397`); the net path `settled_cumulative_passes_net` (`:2015-2040`); external capital flows (`persistence/external_capital_flows`, `breezy-capital-flow-pull`) | **Reuse.** The cash leg is the existing per-day cash identity on the **net** (external-flow-explained) path, fed by C2 `realized_pnl` instead of `ScoredTrial.pnl`. No new tolerance arithmetic. |
| Venue position snapshot | Nautilus `generate_position_status_reports` in the node (`exec/client.py`), node-bound; `PORTFOLIO_POSITIONS_PATH = "/v1/portfolio/positions"` (`exec/endpoints.py:97`); the offline GET precedent `scripts/venue/polymarket_us_capital_flow_pull.py` plus `account_activity.py`, pinned non-egress by `test_polymarket_us_capital_flow_pull.py::test_not_an_execution_egress_module` (`:378`) | **Extend the precedent.** A sibling read-only pull, `scripts/venue/polymarket_us_positions_pull.py`, uses the same signing client and the same host, GET only, and carries the same non-egress test. Reading positions inside the node would put an analysis consumer in the order process (rejected; ARCH C1 rejects `StreamingConfig` on the node for the same reason). |
| Venue settlement evidence | Tape custom type `custom_venue_settlement_snapshot` (quote-tape ingest, catalog `polymarket_us`); `FilledTrial.venue_settlement_tmax_f` (consumed in `score_live_trials.py:888`) | **Reuse.** Its value is cross-checked against the NWS CLI outcome. Nothing new is captured. |
| Probability at decision (pre-C1 bridge) | `SHADOW_DECISION {... 'kind': 'Take', 'p_hat', 'p_lower', 'p_upper', 'ev_net', 'now_ns' ...}`, logged by `fq/strategy.py:581` into `~/.local/share/breezy/logs/breezy-trade-*.log` (verified on `breezy-trade-20261002T205521Z.log`, SFO 83_84 take at 21:01:16Z) | **Reuse the bot's own output.** p is never recomputed (memory note "the bot trades, Claude builds the bot"; L-2). Once C1 is live, `DecisionRecord.p_hat` is authoritative, and the log bridge only cross-checks it. |
| RECONCILIATION verdict writer | C4 writer (Wave 0, `persistence/autonomy/`); `AlertPayload` hygiene list (`registry/health_model.py:217-235`) | **Consume.** AUT-2 implements only the producer logic. |
| Label-run unit | `deploy/systemd/score-live-trials-run.sh` and `portfolio-roi-run.sh` (studies flock, `say`, the dated-marker pattern) | **Reuse the wrapper idiom.** One new unit pair replaces the FQ-blind scorer role. |
| Monitor family scoping (WP1) | `resolve_trial_family` (`position_monitor_nightly_report.py:132-165`), which today flags ambiguity only | **Reuse** as the filter predicate. No new attribution logic. |

---

## 3. Design

### 3.1 Root cause of −0.37 versus +0.37 (evidence gathered for this plan; WP1 commits it)

All values come from read-only reads on 2026-10-03.

1. Every 2026-10-02 position-monitor report shows **the same single row** under four different family labels: `position_monitor_report_2026-10-02_pm_us_crh_{v4,v2,cont,fq_v1}.md` each read `positions: 1 (settled 1)` and `SETTLED ... n=1 realized_pnl_total=-0.3700`.
2. That row is the CRH v4 trial `continuous_rung_hold/trial/SFO/2026-09-21/tc-temp-sfohigh-2026-09-21-gte66lt67f.POLYMARKET_US` (YES leg; fill 0.35, fee 0.02, `held=False`, `pnl=-0.3700`), stored in `derived/scored_trials/pm_us_crh_v4/scored_trials_20260922T141816645708220Z.parquet`.
3. **Mechanism.** `main` passes every summary from `read_monitor_summaries(args.summaries_dir)` and every pooled scored trial (`read_scored_trials_pooled`) into `build_monitor_report` (`position_monitor_nightly_report.py:862-925`). `--family-manifest` only stamps `RuleSeries.family` in `_exit_rule_series` (`:699-735`). Nothing filters by family. The wrapper runs once per REGISTERED manifest (`position-monitor-report-run.sh:206-209`), so each run re-reports the whole universe under a new label.
4. The v4 tally's `total pnl 0.3700` (`family_tally_v2_pm_us_crh_v4_2026-09-30.md`) is the sum of three v4 fills: MIA NO 09-21 at −0.13, SFO YES 09-21 at −0.37, and MDW NO 09-22 at +0.87.
5. **Verdict.** There is no sign error. Both numbers are correct for what they compute. The defect is attribution: FQ is shown a v4 row. **FQ has zero scored fills** (score-live-trials skips the kind by design: `score-live-trials-run.sh` S7 branch, log `SCORE LIVE TRIALS SKIPPED -- composition_kind=forecast_quantile_ladder` at 10-01 and 10-02 14:15Z), and FQ composes no `PositionMonitor`.

Further findings from the same reads, each handled by a WP:

| # | Finding | Evidence | WP |
|---|---|---|---|
| F2 | `portfolio-roi` exits 1 every day. This is a gating defect, not an expected outcome. | The S7 branch returns 2, the wrapper `exit 0`s **without** writing `score_live_trials_ok_$STAMP`, and `portfolio-roi-run.sh` then logs `PORTFOLIO ROI SKIPPED -- no score-live-trials success marker` and exits 1 (journal 10-01 and 10-02 17:40Z). | WP1, WP6 |
| F3 | 09-30 `settled_cumulative_passes=False` is the **gross** metric. | `PRIVATE_portfolio_roi_2026-09-30.json`: `settled_cumulative_unexplained` 39.98 (gross) versus `_net` −0.02, `settled_cumulative_passes_net=True`, `n_explained_external_flow_days=1`. Hypothesis H3: the gap is one explained external deposit that the gross path does not net. WP1 verifies it to the cent from the PRIVATE file's settled rows and records only the classification (no amounts) in the evidence note. | WP1, WP5 |
| F4 | The FQ manifest's `trial_id_prefix` (`forecast_quantile_ladder/trial/pm_us_crh_fq_v1/`) matches **no** stored key. FQ latches are kind-scoped (`forecast_quantile_ladder/trial/<STATION>/<day>/<rung>:<side>`, G28). | Exec-store key census: 16 FQ latch keys, none containing `pm_us_crh_fq_v1`. Any prefix-based scorer finds 0 FQ trials. | WP2 |
| F5 | The FQ latch is not a fill join key. | Latch value: `ask "0"`, `fee null`, `venueOrderId null`, internal `instrument_id "LAX:89_90:yes"` (`persistent_latch.py:156-166`). There are 14 latches for 10-02/10-03 against 11 fills: a latch is a take attempt, not a fill. | WP2 |
| F6 | Exit fills are never evaluated. | `record_exit` writes `exitPx/exitFee/exitAtNs` into the CRH latch (`exit_wiring.py:227-236`). No consumer reads them, and `portfolio-roi` reports `n_exit_fills=0` without labels. | WP4 |
| F7 | Pending FQ outcomes. | 11 FQ fills are durable: 5 for climate day 10-02 (LAX×2, MDW×3, all YES BUY, fee reconciled) are settled today and unlabelled; 6 for 10-03 settle 10-04. | WP3 backfill |

### 3.2 Package layout (analysis layer, G15; never imported by a live package)

```
src/breezy/persistence/autonomy/            (Wave 0 owns schemas.py, plugin.py, pins.py)
    label_store.py      write_labels(), read_labels(), LABEL_V1_SCHEMA consumer   [AUT-2]
    net_position.py     net_signed_qty(fills) -> Mapping[base_slug, Decimal]       [AUT-2, unless Wave 0 placed it in entry_guard.py]
    canary_store.py     CANARY_ROOT, append_canary_fill(), read_canary_fills()     [AUT-2, Z14]
src/breezy/analysis/labeling/
    __init__.py
    instrument_facts.py extracted from score_live_trials.py (pure move)
    fill_source.py      read_durable_fills(db_path) -> tuple[DurableFillRecord, ...] (G6 mode=ro URI, fill/ + fill_by_day/ walk)
    attribution.py      attribute_fill(fill, manifests, registry_fold|None) -> Attribution | Unattributed
    decision_link.py    DecisionLink from C1 (OrderLink+DecisionRecord) or NodeLogTakeLine (pre-C1 bridge)
    fq_scorer.py        ForecastQuantileLadderScorer (C6 Scorer for CompositionKind.forecast_quantile_ladder)
    exit_labels.py      label_exit(sell_fill, entry_label, settlement) -> LabelRow
    settlement_source.py SETTLEMENT_SOURCES: {polymarket_us: NwsCliFinal, kalshi: RefusingSettlementSource("twc_reader_absent")}
    reconcile.py        reconcile_positions(), reconcile_settlement(), reconcile_cash()
    verdicts.py         build_reconciliation_verdict(), build_label_lag_verdict()
    prelaunch_intents.py ambiguous_open_at(ts) census for Z19
    label_run.py        entrypoint: python -m breezy.analysis.labeling.label_run
src/breezy/analysis/plugins.py (Wave 0 registry OFFLINE_PLUGINS) gains the FQ Scorer entry   [AUT-2 edits one line]
scripts/venue/polymarket_us_positions_pull.py   read-only GET /v1/portfolio/positions snapshot
deploy/systemd/breezy-label-outcomes.{service,timer}, label-outcomes-run.sh
deploy/systemd/breezy-venue-positions-pull.{service,timer}, venue-positions-pull-run.sh
```

Stores (ARCH common rules: 0700 directories, 0600 files, atomic writes, ns-named files):
- Labels: `~/.local/share/breezy/derived/labels/<family_id>/labels_<now_ns>.parquet` (C2).
- Positions snapshots: `~/.local/share/breezy/evidence/venue_positions/<venue>/positions_<now_ns>.json`. Each snapshot holds `{schema: "venue_positions/v1", snapshot_ns, rows: [{base_slug, net_qty}]}`, with no account id and no order ids.
- Canary: `~/.local/share/breezy/state/canary/<venue>/canary_fills_<YYYY-MM-DD>.jsonl` (Z14). It is not under `state/exec_*` and is never opened by `fill_source.py`.
- Verdicts: C4 paths, owned by Wave 0.
- Run marker: `~/.local/share/breezy/derived/label_outcomes_ok_<YYYY-MM-DD>`, written only at the end of a successful run, including a `NO_INPUT` run.

### 3.3 C6 `Scorer` implementation and the registration gate

- **`ForecastQuantileLadderScorer.label(capture_day, exec_fills, settlements) -> tuple[LabelRow | Exclusion, ...]`**, registered in `OFFLINE_PLUGINS[CompositionKind.forecast_quantile_ladder].scorer`. The kinds `current_rung_hold`, `continuous_rung_hold` and `forecast_ladder` keep Wave 0's `RefusingPlugin` (ARCH C6 YAGNI: no non-RETIRED family). Their historical fills stay readable through the frozen legacy scored-trial store (§3.10).
- **Family-agnostic by construction.** `label_run` iterates `OFFLINE_PLUGINS` for every family that is non-RETIRED in the C5 fold, or in REGISTERED manifests before C5 exists. It never iterates a hard-coded family list. A family whose kind resolves to a `RefusingPlugin` while non-RETIRED is a refusal: CRITICAL alert, the run exits non-zero, and no marker is written. That is a genuine failure, not an expected one.
- **Registration-time gate (AUT-2 tests on top of Wave 0's `test_family_plugin_exact_set`):**
  - `tests/contract/test_aut2_scorer_registration.py::test_every_non_retired_manifest_kind_has_a_non_refusing_scorer`: parses every `deploy/families/*.json` with `status == REGISTERED` through `load_family_manifest` and asserts `OFFLINE_PLUGINS[kind].scorer` is not a `RefusingPlugin`.
  - `::test_new_manifest_without_scorer_cannot_register`: a temp manifest of an unregistered kind fails the gate.
  - `::test_scorer_declares_both_legs_and_both_roles`: the Scorer declares `legs = {"yes", "no"}` and `roles = {"entry", "exit"}`, so a scorer that silently drops a leg fails (L-44).
  - The compose-time refusal (`_compose_family`, `app/trade.py:853`) belongs to AUT-5a (Wave 1 file ownership). AUT-2 consumes it and does not edit `app/trade.py`.

### 3.4 Fill source, attribution and the decision link

1. **Universe.** Every `DurableFillRecord` under `exec/polymarket_us/fill/` (G6 read-only URI), plus the canary store when, and only when, the run is the canary invocation (§3.8). Today that is 20 fills.
2. **Attribution (`attribute_fill`), in order:**
   - (a) **C1 (post-AUT-1):** `fill.client_order_id` → `OrderLink.client_order_id` → `decision_id` → `DecisionRecord.family_id`. This is authoritative.
   - (b) **C5 fold (post-AUT-5a):** the family that was CHAMPION on the venue at `fill.ts_event` (G1: one sender per node). This must agree with (a) when both exist. A disagreement leaves the fill unattributed.
   - (c) **Pre-C1/C5 bridge:** the base slug grammar gives `(station, climate_day, rung, leg)`. The kind latch key `<kind latch prefix><STATION>/<day>/<rung_id>:<side>` must exist; for FQ that is `FORECAST_QUANTILE_TRIAL_KEY_PREFIX` (`persistent_latch.py:68`). The family is then the unique manifest with `status == REGISTERED`, `composition_kind == kind`, `venue` matching, `station ∈ stations` and `climate_day ≥ d0_climate_day`.
   - If no rule yields exactly one family, the fill is **unattributed**. No label row is written (a `family_id` is never guessed), a `HEALTH FAIL label_coverage` event is raised, and the run alerts CRITICAL.
3. **Trial id (F4).** `label.trial_id = manifest.trial_id_prefix + "<STATION>/<day>/<rung_id>:<side>"`. Family-scoped trial ids therefore satisfy the existing barrier `family_barrier.assert_family_only` without any manifest edit.
4. **`label_id`** = first 32 hex characters of `sha256("label/v1" | family_id | client_order_id | trade_id or "" | role)`. Dedupe is on `(label_id, max label_seq)`, so a re-label (late correction, conflict branch, window completion) increments `label_seq` and never rewrites a file.
5. **Decision link (`decision_link.py`):**
   - Post-C1: `decision_id`, `p_at_decision = DecisionRecord.p_hat`, and `entry_ask = DecisionRecord.ask_px`.
   - Pre-C1 bridge: the latest `SHADOW_DECISION` line with `kind == 'Take'`, the same `instrument_id` and `climate_day`, and `now_ns ≤ fill.ts_event`, read from the node log file covering `ts_event`. The link also requires the immediately following `OrderFilled` line for the same `client_order_id`. That line gives `p_at_decision = p_hat` and `entry_ask` from the line's ask where it is present.
   - `decision_id` is then computed with the **C1 formula** from recorded fields (`family_id | manifest_sha256 | artefact_sha256 | station | climate_day | rung_id | side | now_ns`). This is the C1 recomputation rule, not an invented id.
   - No matching line: `p_at_decision = null` and `decision_id = null`, with the nullability reason `pre_c1_log_unmatched` (see contradiction C-1). The row stays labelled for P&L and reconciliation, the run alerts WARN, and the row does not count toward the live-proof window (§6).

### 3.5 Entry label computation (YES and NO legs)

The leg table below is also required in the `fq_scorer.py` module docstring (L-44).

| Quantity | YES leg (instrument `<slug>.POLYMARKET_US`) | NO leg (instrument `<slug>^no.POLYMARKET_US`) |
|---|---|---|
| Durable record | `orderSide BUY`, `cumulativeCost` in YES price units | `orderSide BUY` (the adapter sends venue `SELL`/`BUY_SHORT`, G24), `cumulativeCost` in NO price units (09-15 MIA `^no` fill 0.09) |
| `fill_px` | `cumulative_cost / cumulative_qty` | same, in NO units |
| `settled_outcome` (bought leg wins) | `bucket.contains(tmax_f)` | `not bucket.contains(tmax_f)` |
| Payoff per contract | 1 if won, else 0 | 1 if won, else 0 |
| `realized_pnl` (held to settlement) | `qty·payoff − cumulative_cost − fee_reconciled` | same formula, NO units |
| Venue net on the base slug | `+qty` | `−qty` (L-44; `parsing.py:277-279`) |

- `score_trial` (reused) supplies the settlement fields. Its `pnl` is per contract with the fee included. AUT-2 asserts `realized_pnl == ScoredTrial.pnl × qty`; any mismatch is an error, never smoothed over.
- `fee_reconciled = DurableFillRecord.cumulative_fee` only when `fee_reconciled is True`. Otherwise the row gets `excluded_reason = fee_unreconciled` (09-12 and 09-13 legacy fills).
- `slippage = fill_px − entry_ask`. A negative slippage beyond one tick is a defect signature (L-25): the row is labelled with `admissible=False` and a WARN alert. C2's enum has no `slippage_defect` value, so the row reuses `q≠1`'s sibling path: the alert fires and AUT-4 sees `admissible=False` with the reason held in the run log (see C-1 widening request).
- **Admissibility.** `admissible = reconciled ∧ source == live ∧ ¬drill ∧ excluded_reason is None ∧ window_complete`. `window_complete` for `(family, climate_day)` means every attributed fill on that day has a final CLI value and a venue settlement snapshot, or an explicit exclusion. Rows written before that point get `excluded_reason = window_incomplete` and are re-labelled when the window closes (memory note "census rows include open windows").
- **Settlement basis by venue (`settlement_source.py`):** `polymarket_us → NwsCliFinal` (latest revision, final-only, LST climate day; the reused reader). `kalshi → RefusingSettlementSource` (Kalshi settles on The Weather Company, and no TWC reader exists). A Kalshi family therefore cannot get labels and cannot pass the §3.3 gate, so it fails closed. Pinned by `test_kalshi_settlement_source_refuses_until_twc_reader`.

### 3.6 Reconciliation: three legs, per-leg tolerances (ARCH §10 obligation)

| Leg | What is compared | Evidence | Tolerance | On breach |
|---|---|---|---|---|
| **Position (net)** | For every base slug **open** at snapshot time, venue `net_qty` versus `net_signed_qty(ledger fills with ts_event ≤ snapshot_ns)`. YES fills count +, NO fills count − (§3.5). | `venue_positions/v1` snapshot at 14:05Z, which reads open markets only (L-52: a settled market leaves the page, so settled slugs are never compared here). | **0 contracts, exact Decimal equality, both legs.** Orders are qty 1 and there is no rounding path. | `reconciled=False` on every label of that slug, CRITICAL, `RECONCILIATION FAIL`. A slug with an OPEN or AMBIGUOUS intent at snapshot time is **UNKNOWN**, never PASS or FAIL (L-52), and gives `INCONCLUSIVE`. |
| **Settlement** | Label `settled_outcome` from the NWS CLI final versus the venue settlement snapshot for the slug. | `custom_venue_settlement_snapshot` rows (tape catalog). | **Exact outcome equality.** | `reconciled=False`, CRITICAL `settlement_source_disagreement`, and the venue value is never adopted. A venue fallback settlement ("last fair market price", polymarket-us-integration skill) is not binary: it becomes `reconciled=False` with detail `venue_fallback_settlement`. No snapshot within 24 h of the CLI final means the row stays pending; after 48 h it is FAIL. |
| **Cash (daily)** | Σ C2 `realized_pnl` settled on day d versus the balance delta net of external flows. | The existing net path in `portfolio_roi_report.py`: balance lines from node logs plus `capital_flows/`. | **`per_day_tolerance(n_fills_settled_that_day) = $0.01 × n`** (`:1390`). The pass flag is `settled_cumulative_passes_net`; the gross flag is diagnostic only (F3). | `RECONCILIATION FAIL` on that day, CRITICAL. A `BALANCE_UNKNOWN` day is `INCONCLUSIVE`, never coerced to zero (existing F3 behaviour). |

- **Exit consistency** (a sub-check of the position leg): the latch values `exitPx/exitFee/exitAtNs` written by `record_exit` must equal the durable SELL record (`cumulative_cost/qty`, `cumulative_fee`, `ts_event`). A mismatch gives `reconciled=False` on the exit label.
- **Daily outcome.** PASS only if all three legs pass for every slug and day evaluated. Any FAIL gives FAIL. Otherwise (any UNKNOWN or INCONCLUSIVE, no FAIL) the outcome is INCONCLUSIVE, which never satisfies §4.4.

### 3.7 C4 producers: RECONCILIATION and HEALTH label_lag (the horizon obligation)

- **Producer id** `aut2_label_run`, entry module `breezy.analysis.labeling.label_run`, pinned in `PRODUCER_SOURCE_SHA256` by the §4.3 closure test. A pin update ships in the same commit as any edit to the closure.
- **RECONCILIATION verdict per non-RETIRED family per run:**
  - `subject_artefact_sha256` is the family's **bound** artefact sha (Z1: from its BOOTSTRAP or MINT row; before C5, the manifest's `density_artefact_sha256`).
  - `detector = "aut2.reconciliation"`; `declared_action_class` and `prereg_ruling_sha256` are read only from the pinned `autonomy-policy/v1` block (single-read rule).
  - `n` = slugs plus days compared, and `n_min` carries the literal reason `deterministic_equality_check`.
  - `metrics = {position_slugs_compared, position_mismatches, settlement_mismatches, cash_days_failed, unknown_slugs, ambiguous_open_at_prelaunch_7d}`.
  - `inputs` = `{path_role, sha256}` for the labels file, the snapshot and the exec-store fill-set hash (no paths).
- **Horizon (§4.4).** `valid_until_ns = produced_at_ns + 26 h`, at or under Z4's `MAX_VERDICT_VALIDITY_H` (24 h plus slack). Runs at 14:15Z and 05:00Z mean an accepted PASS is always under 15 h old at the 15:30Z daily engine and the 16:45Z pre-launch pass. The policy ruling (AUT-5) must name 26 h as the RECONCILIATION horizon. That is a handoff, not an AUT-2 decision of policy.
- **Before the policy block exists** (AUT-5b), no C4 verdict is written: the acceptance rules would make it `ERROR` anyway. The CRITICAL alerts and `reconciled=False` labels still operate. The verdict path is RED-tested against a fixture block from day one.
- **HEALTH `label_lag`** (C2 invariant): for every live fill whose `SettlementRecord`, or before C1 the CLI final ingest time, is older than 24 h with no label at `label_seq ≥ 0`, emit `HEALTH FAIL detector="aut2.label_lag"` and a CRITICAL alert. `label_coverage` (unattributed fills) uses the same path.
- **Delivery.** Every CRITICAL goes through `deliver_with_proof` (AUT-6, Z13), journaled to `evidence/alerts/delivery_<date>.jsonl`. Until AUT-6 merges, `emit_alert` plus `OnFailure=breezy-study-failed@` is the interim. Score 3 is not claimed on the interim.

### 3.8 Canary store (Z14) and drill exclusion

- `canary_store.py` writes C1-shaped synthetic records with `source=canary`. The only writer is `label_run --canary`, invoked by the same unit **only on a UTC day with zero real attributed fills**, so the day can qualify under §5.3.
- **Reads.** The canary rows run through `fq_scorer.label(...)` and `reconcile_positions(...)` against a **synthetic canary venue snapshot** written alongside them. The output goes to `derived/labels_canary/<family_id>/` and never to `derived/labels/`. It never enters the RECONCILIATION verdict, any `n`, `portfolio-roi`, or `entry_guard`.
- **Tests.** `tests/unit/test_aut2_canary_isolation.py`:
  - `::test_reconciliation_never_reads_canary_store` (AST plus runtime: `fill_source.read_durable_fills` and `reconcile.reconcile_*` never open `CANARY_ROOT`);
  - `::test_entry_guard_never_reads_canary_store` (AST over `persistence/autonomy/entry_guard.py`);
  - `::test_canary_labels_are_never_admissible` and `::test_canary_rows_excluded_from_verdict_n`.
- **Drill.** C1 `drill=true` (the fold from DRILL_PROMOTE through ROLLBACK, Z2) gives `excluded_reason=drill` and `admissible=False`. Drill fills are real venue fills, so they **are** reconciled in the position and cash legs (money moved). They are excluded only from statistics. Tests: `test_drill_fill_labelled_reconciled_but_inadmissible` and `test_drill_fill_after_resume_still_drill` (Z2).

### 3.9 Z19: AMBIGUOUS intent open at 16:45Z

- `prelaunch_intents.py` reads `exec/polymarket_us/intent/current` and `intent/history/*` (G6 URI) and reconstructs each intent's open interval `[created_ns, retired_ns)` with its state. For each UTC day d it emits `ambiguous_open_at_prelaunch(d) ∈ {true, false, unknown}` at `d 16:45:00Z`.
- Output: a 7-day count in the RECONCILIATION `metrics` and a line `Z19 ambiguous_open_at_1645Z days=<k>/<n> unknown=<u>` on the unit's stdout (journal; L-52 amendment).
- **INFERRED, with an L-1 step in WP5.** Every one of the 25 records read today has `created_ns == retired_ns`. This is consistent with instant accept-with-fill, but it could also mean retire rewrites `created_ns`. WP5 first reads the retire path in `runtime/submit_intent.py`. If `created_ns` is not preserved for AMBIGUOUS retirements, the metric reports `unknown` (never `false`), and the fallback source is the supervisor's existing read-only `probe_open_intent` result at LAUNCH (`trade_supervisor.py:402`). If that result is not journaled, the logging line belongs to AUT-5a's supervisor file ownership and is handed over as a request (C-4).

### 3.10 Consumers rewired; no expected failures (README fifth bullet)

| Unit | Today | After AUT-2 |
|---|---|---|
| `breezy-score-live-trials` (14:15Z) | FQ: S7 `exit 0`, no marker | Retained for the frozen CRH stores only (all CRH families RETIRED). WP1: the S7 branch writes a distinct `score_live_trials_noinput_$STAMP` marker and logs `NO_INPUT`. WP6: the label unit takes the 14:15Z slot and this unit moves to 13:55Z. It is disabled once C5 bootstrap marks every CRH family RETIRED and the legacy store is frozen (a reviewed unit change). |
| `breezy-portfolio-roi` (17:40Z) | exit 1 daily (F2) | WP1: accepts `ok` **or** `noinput`. WP6: gates on `label_outcomes_ok_$STAMP`, and the P&L source becomes the union of C2 labels and legacy `ScoredTrial` rows for pre-cutover CRH fills. An overlap (one fill in both) is a refusal. The pass flag is net. |
| `breezy-family-tally@pm_us_crh_{v2,v4}` | SKIPPED, exit 0 (10-02); exit 1 on 10-01 | No change of semantics (PREREG v2/v3 tallies over frozen stores). The FQ live tally is AUT-4's `LIVE_SEQUENTIAL` over C2. Neither instance may exit non-zero as expected behaviour (WP6 test). |
| `breezy-position-monitor-report` | Unscoped (§3.1) | WP1: family-scoped, plus `NO_MONITOR_FOR_KIND forecast_quantile_ladder` for kinds that compose no monitor. |
| `breezy-replay-daily` | FQ SKIPPED, exit 0 | Unchanged by AUT-2 (forward shadow and replay belong to AUT-4). Listed so the scorer does not over-claim. |
| New `breezy-label-outcomes` | n/a | `OnCalendar=*-*-* 14:15:00 UTC` and `*-*-* 05:00:00 UTC`; `flock -w 600` on `breezy-studies.lock` in `breezy-studies.slice`; `MemoryMax=1G`; `RuntimeMaxSec=1200` (14:15 + 10 + 20 min ends 14:45Z, before 16:30Z); `OnFailure=breezy-study-failed@%n`; `EnvironmentFile=-%h/.config/breezy/alerts.env` (G27); a no-progress stall line every 60 s. A no-input run exits 0 with `LABEL_OUTCOMES NO_INPUT` and still writes the marker. |
| New `breezy-venue-positions-pull` | n/a | `OnCalendar=*-*-* 14:05:00 UTC`; no studies lock (a light GET, the capital-flow-pull precedent); `MemoryMax=256M`; `RuntimeMaxSec=120`; exits 0 with `POSITIONS_PULL OK rows=<n>` or `WITHHELD`; exits 1 on an HTTP or auth error, which is a genuine failure. |

**Slot rationale (differs from the ARCH §5.2 indicative 05:00Z label slot).** PM.us settles at 08:00 ET (12:00Z EDT, 13:00Z EST from 11-02), and western CLI finals arrive around 09:30–10:30Z. A 05:00Z-only run labels nothing for the prior climate day. 14:15Z is the primary run. 05:00Z is the catch-up run for conflict-branch settlements (11:00 ET), corrections and late finals. Both runs fall inside the 24 h label horizon. ARCH §5.2 states that "AUT-n plans fix the rows".

---

## 4. Work packages

Gate for every WP, run from the tree root with the exact interpreter and never `uv` (L-51; memory note "never uv sync the shared venv"):
- `scripts/ci/run_tests_no_egress.sh` (the full gate after **every** merge, L-43; under a unit, pass `-p LimitNOFILE=524288`).
- `cd <tree> && .venv/bin/lint-imports` must print `N kept, 0 broken` (`python -m importlinter` is a no-op).
- mypy strict ratchet: `.venv/bin/mypy src/breezy/analysis/labeling src/breezy/persistence/autonomy scripts/venue/polymarket_us_positions_pull.py`, with 0 errors and no new `# type: ignore`.
- In a worktree, `PYTHONPATH=<worktree>/src`.

Each RED test is written first, and its RED→GREEN output is kept as the change artefact. Every injectable seam has one test that runs the production default (L-55). Every store-reading gate test writes its fixture through the real writer (L-42).

### AUT-2.WP1: root cause committed; monitor scoping; portfolio-roi expected failure removed (no Wave 0 dependency, start now)
- **Scope.** The evidence note `docs/evidence/AUT-2_rc_monitor_pnl_2026-10-03.md`, holding the §3.1 facts with file paths and parquet names, and H3 verified to the cent from `PRIVATE_portfolio_roi_2026-09-30.json`. The note records the classification only and carries no account amounts. Plus the family filter in the monitor report and the `noinput` marker.
- **Files.** `scripts/analysis/position_monitor_nightly_report.py` (filter `summaries` and `scored_trials` to `resolve_trial_family(...) == family_manifest.family_id` when bound; the unbound run is unchanged; `NO_MONITOR_FOR_KIND` line); `deploy/systemd/score-live-trials-run.sh` (S7 writes `score_live_trials_noinput_$STAMP`); `deploy/systemd/portfolio-roi-run.sh` (accepts either marker).
- **RED first:**
  - `tests/unit/test_position_monitor_nightly_report.py::test_bound_report_excludes_other_family_summaries` (a v4 summary plus an FQ manifest gives `positions: 0`);
  - `::test_bound_report_keeps_own_family_rows`;
  - `::test_fq_kind_reports_no_monitor_for_kind`;
  - `::test_unbound_report_unchanged_golden`;
  - `tests/unit/test_score_live_trials_deploy.py::test_fq_champion_writes_noinput_marker_and_exits_zero`;
  - `tests/unit/test_portfolio_roi_deploy.py::test_noinput_marker_admits_run`;
  - `::test_absent_markers_still_refuse` (fail-closed kept).
- **GREEN.** The 10-04 15:00Z FQ report shows `positions: 0` and `NO_MONITOR_FOR_KIND`, and the v4 report still shows −0.37. The 10-04 17:40Z `portfolio-roi` exits 0 (expect `roi_status=GATED_UNSETTLED_CAPITAL` once the 10-02 FQ fills pass the horizon unlabelled; exit 0 per D9).
- **Activation.** Immediate. The scripts are read at each timer fire, so no restart is needed. Verify in the journal after the first live fire (L-52 amendment).

### AUT-2.WP2: C2 label store, durable-fill source, attribution (Wave 1, after ARCH-0 schemas)
- **Files.** `persistence/autonomy/label_store.py`, `persistence/autonomy/net_position.py` (unless already in `entry_guard.py`), `analysis/labeling/{fill_source,attribution,instrument_facts}.py`; `scripts/analysis/score_live_trials.py` (import-only change after the extraction).
- **RED first:**
  - `tests/unit/test_aut2_label_store.py::test_schema_is_exact_label_v1`;
  - `::test_dedupe_keeps_max_label_seq`;
  - `::test_unknown_schema_version_refused`;
  - `::test_atomic_write_no_partial_file`;
  - `::test_money_columns_are_string_decimal`;
  - `tests/unit/test_aut2_fill_source.py::test_reads_every_fill_through_ro_uri`;
  - `::test_undecodable_fill_is_store_corruption_not_skip`;
  - `::test_real_default_reader_against_tmp_store` (L-55);
  - `tests/unit/test_aut2_attribution.py::test_fq_fill_attributed_via_kind_latch_not_manifest_prefix` (F4);
  - `::test_latch_without_fill_is_not_a_label` (F5);
  - `::test_two_candidate_families_unattributed`;
  - `::test_c1_and_fold_disagreement_unattributed`;
  - `::test_trial_id_uses_manifest_prefix`;
  - `tests/unit/test_aut2_net_position.py::test_no_fill_offsets_yes_holding_to_netted_venue_qty` (C2 RED);
  - `::test_each_leg_terminal_state` (L-44);
  - `::test_sell_nets_against_long`.
- **GREEN.** A dry run over the live store attributes all 11 FQ fills to `pm_us_crh_fq_v1` and every CRH fill to the legacy path, with 0 unattributed.
- **Activation.** None alone (a library). It lands live through WP6.

### AUT-2.WP3: FQ Scorer, entry labels for both legs, decision link, settlement sources, backfill
- **Files.** `analysis/labeling/{fq_scorer,decision_link,settlement_source}.py`; the `OFFLINE_PLUGINS` entry.
- **RED first:**
  - `tests/unit/test_aut2_fq_scorer.py::test_yes_win_and_yes_loss_pnl_net_of_reconciled_fee`;
  - `::test_no_leg_win_and_no_leg_loss_pnl` (L-44, both terminal states);
  - `::test_realized_pnl_equals_score_trial_pnl_times_qty`;
  - `::test_fee_unreconciled_excluded`;
  - `::test_preliminary_cli_never_settles` (nws-cli-settlement two-issuance trap);
  - `::test_correction_relabels_with_next_label_seq`;
  - `::test_window_incomplete_until_all_fills_settle`;
  - `::test_negative_slippage_beyond_tick_inadmissible_and_alerts` (L-25);
  - `::test_canary_and_drill_rows_never_admissible`;
  - `tests/unit/test_aut2_decision_link.py::test_take_line_supplies_p_hat_and_c1_decision_id`;
  - `::test_take_after_fill_ts_is_not_linked`;
  - `::test_unmatched_fill_null_p_with_reason`;
  - `::test_c1_record_overrides_log_line`;
  - `::test_real_default_log_reader_on_tmp_file` (L-55);
  - `tests/unit/test_aut2_settlement_source.py::test_kalshi_settlement_source_refuses_until_twc_reader`;
  - `::test_polymarket_uses_nws_cli_final_latest_revision`.
- **GREEN.** A backfill dry run labels the 5 settled 10-02 FQ fills, each with `p_at_decision` from its Take line, and the 6 10-03 fills after 10-04's CLI finals. The P&L sum equals the per-fill `score_trial` sum.
- **Activation.** Through WP6.

### AUT-2.WP4: exit labels (F6)
- **Files.** `analysis/labeling/exit_labels.py`; Scorer `roles` includes `exit`.
- **Semantics.** A SELL durable fill on an instrument with a prior BUY for the same family gives `role=exit`.
  - `realized_pnl = proceeds − exit_fee − cost_basis(exited qty)`.
  - `counterfactual_hold_pnl = payoff(settled_outcome)·qty − cost_basis(exited qty)`.
  - The entry label's held quantity drops by the exited quantity, so the identity "Σ `realized_pnl` per slug = cash moved on the slug" holds.
- **RED first:**
  - `tests/unit/test_aut2_exit_labels.py::test_yes_exit_realized_and_counterfactual`;
  - `::test_no_leg_exit_signs` (a NO SELL nets +qty on the base slug);
  - `::test_slug_pnl_identity_entry_plus_exit`;
  - `::test_record_exit_latch_mismatch_unreconciles` (the `exit_wiring.py:227` fields versus the durable SELL);
  - `::test_exit_without_entry_unattributed`.
- **GREEN.** The fixture identity holds for both legs. Live, an exit occurs only if an exit-capable family is CHAMPION (G17: only `pm_us_crh_exit_v4`, DRAFT), so the live proof cites "no exit occurred" unless one does.
- **Activation.** Through WP6.

### AUT-2.WP5: reconciliation, positions pull, RECONCILIATION and label_lag verdicts, Z19
- **Files.** `scripts/venue/polymarket_us_positions_pull.py`; `analysis/labeling/{reconcile,verdicts,prelaunch_intents}.py`; `portfolio_roi_report.py` (expose the net cash identity as a pure function taking C2 rows, with no behaviour change to its own report).
- **L-1 steps before RED** (premise checks, each stated in the brief):
  - (i) `GET /v1/portfolio/positions` returns a NO holding as a negative quantity on the YES slug, verified on an archived evidence payload under `docs/evidence/venue/polymarket_us/`. If no archive shows it, the first live pull is the positive control, and the leg rule waits on it.
  - (ii) The `submit_intent.py` retire path preserves `created_ns` (§3.9).
  - (iii) `find_execution_egress_modules` does not flag a GET-only module, as already proven for capital-flow-pull.
- **RED first:**
  - `tests/unit/test_aut2_positions_pull.py::test_not_an_execution_egress_module`;
  - `::test_get_only_no_post_put_delete_in_module_ast`;
  - `::test_snapshot_has_no_account_or_order_ids` (hygiene);
  - `tests/unit/test_aut2_reconcile.py::test_position_leg_exact_equality_both_legs`;
  - `::test_settled_slug_absent_from_page_not_compared` (L-52);
  - `::test_open_intent_at_snapshot_is_unknown_not_pass`;
  - `::test_fills_after_snapshot_fenced_out`;
  - `::test_settlement_disagreement_unreconciles_and_never_adopts_venue`;
  - `::test_venue_fallback_settlement_unreconciled`;
  - `::test_cash_leg_uses_net_path_and_per_day_tolerance`;
  - `::test_balance_unknown_day_inconclusive`;
  - `tests/unit/test_aut2_verdicts.py::test_reconciliation_verdict_valid_26h`;
  - `::test_subject_sha_is_bound_artefact_sha` (Z1);
  - `::test_action_class_read_from_policy_block_only`;
  - `::test_no_verdict_without_policy_block_but_alert_fires`;
  - `::test_label_lag_health_fail_after_24h`;
  - `::test_unattributed_fill_health_fail`;
  - `::test_payload_hygiene_scan_covers_aut2_writers`;
  - `tests/unit/test_aut2_prelaunch_intents.py::test_ambiguous_spanning_1645Z_counted`;
  - `::test_rewritten_created_ns_reports_unknown`.
- **GREEN.** A dry run over today's state gives position PASS on the open 10-03 slugs, settlement PASS on the 10-02 slugs, and cash PASS on the net path.
- **Activation.** Install `breezy-venue-positions-pull.{service,timer}` immediately on merge (`systemctl --user daemon-reload && systemctl --user enable --now breezy-venue-positions-pull.timer`, done by the coordinator per the unit-install convention; never by an agent). Verify the first 14:05Z journal line.

### AUT-2.WP6: the label run unit and consumer rewiring
- **Files.** `analysis/labeling/label_run.py`; `deploy/systemd/breezy-label-outcomes.{service,timer}`, `label-outcomes-run.sh`; `portfolio-roi-run.sh` (gate on the label marker) and `portfolio_roi_report.py` (P&L source = labels ∪ legacy, overlap refused, net pass flag); `breezy-score-live-trials.timer` (moved to 13:55Z); `deploy/systemd/README.md` entries.
- **RED first:**
  - `tests/unit/test_aut2_label_run.py::test_iterates_offline_plugins_not_family_list`;
  - `::test_refusing_plugin_for_non_retired_family_fails_run_no_marker`;
  - `::test_no_input_exits_zero_with_marker_and_line`;
  - `::test_marker_written_last_only_on_success`;
  - `::test_stdout_carries_label_outcomes_summary_line` (asserted on stdout, not caplog; L-52 amendment);
  - `::test_real_default_paths_on_tmp_home` (L-55);
  - `tests/unit/test_label_outcomes_deploy.py::test_unit_has_memorymax_runtimemaxsec_onfailure_alerts_env`;
  - `::test_runtime_bound_ends_before_1630Z`;
  - `::test_two_oncalendar_slots`;
  - `tests/unit/test_portfolio_roi_report.py::test_pnl_source_union_labels_and_legacy`;
  - `::test_fill_in_both_sources_refused`;
  - `::test_pass_flag_is_net`;
  - `tests/unit/test_outcome_units_no_expected_failure.py::test_every_outcome_wrapper_exits_zero_on_no_input`. This is parametrised over `score-live-trials`, `portfolio-roi`, `family-tally@v2/v4`, `position-monitor-report`, `label-outcomes` and `replay-daily`, with an FQ champion and no fills.
- **GREEN.** The first 14:15Z run labels the 10-02 FQ fills, writes the marker, and the 17:40Z `portfolio-roi` reports `roi_status=OK` with the FQ P&L included.
- **Activation.** Immediate on merge. The coordinator installs and enables the timer. No node or supervisor restart is needed (offline units; memory note "activate code immediately").

### AUT-2.WP7: C1 switch-over and the C6 registration gate (Wave 2, after AUT-1 tags are live)
- **Scope.** Attribution rule (a) and `DecisionRecord` p become authoritative. The log bridge is demoted to a cross-check: disagreement means CRITICAL plus `reconciled=False`. Optionally, AUT-1's `SettlementRecord` replaces the direct CLI read, with `raw_sha256` equality asserted. The registration tests from §3.3 are added.
- **RED first:**
  - `tests/contract/test_aut2_scorer_registration.py` (three tests, §3.3);
  - `tests/unit/test_aut2_decision_link.py::test_c1_and_log_p_disagree_unreconciles`;
  - `::test_c1_decision_id_join_every_tagged_fill`;
  - `tests/unit/test_aut2_fq_scorer.py::test_settlement_record_sha_must_match_cli_raw`.
- **GREEN.** 100% of post-switch fills carry `decision_id` from C1.
- **Activation.** Immediate (offline).

### AUT-2.WP8: canary store and canary path (Z14)
- **Files.** `persistence/autonomy/canary_store.py`; `label_run --canary`.
- **RED first.** The four §3.8 tests, plus `tests/unit/test_aut2_canary_isolation.py::test_canary_written_only_on_zero_real_fill_day` and `::test_portfolio_roi_never_reads_canary`.
- **GREEN.** A synthetic zero-fill day produces `labels_canary/` rows and no change to `labels/` or verdict `n`.
- **Activation.** Immediate.

---

## 5. Association

**Consumed:**

| Contract | From | What AUT-2 uses | Fallback before it lands |
|---|---|---|---|
| C2 schema (`LABEL_V1_SCHEMA`), C4 writer, C6 Protocols, `RefusingPlugin`, `OFFLINE_PLUGINS`, `pins.py` | ARCH-0 | Types, registry and verdict writer | WP1 needs none. WP2+ wait for Wave 0. |
| C1 `decision_id`, `OrderLink`, `DecisionRecord`, `SettlementRecord`, `drill`, `source` | AUT-1 | Attribution (a), p, settlement sha | The pre-C1 bridge (§3.4), with `drill=false` and `source=live` implied for pre-C1 fills (no drill can occur before AUT-7b) |
| C5 fold, bound artefact sha (Z1) | AUT-5 | Attribution (b), verdict subject | Manifest `density_artefact_sha256` |
| `autonomy-policy/v1` block | AUT-5b | `declared_action_class`, `prereg_ruling_sha256`, the 26 h horizon entry | No verdict file; alerts and labels still operate |
| `deliver_with_proof` | AUT-6 | CRITICAL delivery proof | `emit_alert` plus `OnFailure` (not score-3 evidence) |

**Provided:**

| Contract | To | Guarantee |
|---|---|---|
| C2 labels `derived/labels/<family_id>/` | AUT-3 (`rung_recalibration` fits on admissible `(p_at_decision, settled_outcome)`); AUT-4 (`LIVE_SEQUENTIAL` over admissible labels grouped by station-day, L-40; champion slippage for `FORWARD_SHADOW`) | Written by 14:45Z daily. Consumers gate on `label_outcomes_ok_<date>`. Only `admissible=True` rows count. |
| C4 `RECONCILIATION` | AUT-5 (§4.4 preconditions; a required ATTEST verdict kind, Z5) | Fresh within 26 h at 15:30Z and 16:45Z. INCONCLUSIVE never passes. |
| C4 `HEALTH` (`aut2.label_lag`, `aut2.label_coverage`) | AUT-6 detector catalogue; AUT-5 policy map | Daily |
| `net_signed_qty` | AUT-5 `entry_guard.rung_has_net_position` | One netting rule shared by both |
| Z19 metric | AUT-5 policy review (promotion-starvation risk) | A 7-day count in the verdict metrics and the journal |

**Order and parallelism.** WP1 starts now, in parallel with ARCH Rev 4 and Wave 0. After Wave 0, WP2 → WP3 → {WP4, WP5, WP8 in parallel} → WP6. WP7 follows AUT-1's C1 activation. File ownership is disjoint from Wave 1 siblings: AUT-2 never edits `app/trade.py`, `settings.py` or `trade_supervisor*.py` (AUT-5a). It edits `position_monitor_nightly_report.py`, `portfolio_roi_report.py`, `score_live_trials.py` (import only) and its own new files.

---

## 6. Live-proof protocol

- **Artefact.** `~/.local/share/breezy/evidence/aut2_live_proof/window_<start>_<end>.json`, written by `label_run --proof-window` from the stores. Nobody writes it by hand. Its fields:
  - per qualifying day: the attributed live fill count; labelled count (must be equal); the count with non-null `p_at_decision` from C1 (must be equal for days after WP7); the RECONCILIATION verdict id and outcome (must be PASS); and the label-lag maximum (must be ≤ 24 h);
  - window totals: real fills (≥ 5); NO-leg fills; exits;
  - the `label_outcomes_ok_*` markers and the systemd invocation ids for each run, which prove there was no hand step.
- **Window rule (README / ARCH §5.3).** A day counts only with ≥ 1 real fill, or a `source=canary` fill through §3.8. Zero-fill days extend the window. Canary and drill fills never count toward the ≥ 5 real fills.
  - The window starts on the first UTC day after WP1–WP6 and WP8 are active **and** AUT-6's `deliver_with_proof` is live.
  - A day whose fills are linked only through the log bridge is acceptable (bot-produced p). A day with any `pre_c1_log_unmatched` fill does not qualify and restarts the window.
- **NO leg and exit.** "If one occurs": the artefact lists the NO-leg and exit fills in the window. If there are none, it states `no_leg_fills=0` and `exit_fills=0`, with the family's capability shown (FQ has no exit, G17). The RED tests for both remain the gate evidence.
- **ETA.** About 5 FQ fills a day (11 fills over 10-01..10-03). Assumptions: ARCH Rev 4 plus Wave 0 by about 10-08; WP2–WP6 and WP8 by about 10-14; AUT-6 delivery by about 10-14. A 7-qualifying-day window of 10-15..10-21 has its last fills (climate day 10-22) settle at 12:00Z on 10-23 and labelled at 14:15Z, so the **earliest proof is about 2026-10-23**. With slippage for zero-fill days or Wave 0 delay, plan on **2026-10-30**. The DST change on 11-02 moves venue settlement to 13:00Z, which the 14:15Z slot still covers.
- **Evidence class.** "Machinery proven, edge unproven." Labels and reconciliation make no claim about edge.

---

## 7. Score-3 verification checklist (for an independent scorer)

| Criterion | Check |
|---|---|
| (a) unattended | `journalctl --user -u breezy-label-outcomes.service --since <window>` shows only timer-triggered starts, two a day. The proof artefact lists invocation ids. `git log --since <window> -- src/breezy/analysis/labeling deploy/systemd/*label*` is empty (no commit inside the window). |
| (b) family-agnostic | `scripts/ci/run_tests_no_egress.sh -k "aut2_scorer_registration or iterates_offline_plugins or family_plugin_exact_set"` passes. Code read: `label_run.py` iterates `OFFLINE_PLUGINS` and has no family literal (`/usr/bin/grep -n "pm_us_" src/breezy/analysis/labeling/*.py` returns 0 hits). |
| (c) fails closed | Tests `refusing_plugin_for_non_retired_family_fails_run_no_marker`, `two_candidate_families_unattributed`, `open_intent_at_snapshot_is_unknown_not_pass`, `no_verdict_without_policy_block_but_alert_fires`, `absent_markers_still_refuse` |
| (d) detected, alerted, delivered | `~/.local/share/breezy/evidence/alerts/delivery_<date>.jsonl` holds `delivered=true` for an injected `aut2.label_lag` or `RECONCILIATION FAIL` (a WP5 drill: one fixture fill with no settlement in a tmp HOME through the production entrypoint, with real delivery to the configured endpoint) |
| (e) RED→GREEN | The WP change artefacts (RED output, then GREEN output) attached to each merge commit message or PROGRESS entry. The full gate shows EXIT=0 after each merge. `lint-imports` prints `kept, 0 broken`. |
| (f) live proof | `evidence/aut2_live_proof/window_*.json`: 7 qualifying days, ≥ 5 real fills, labelled = attributed every day, every verdict PASS. Each `verdict_id` resolves under `derived/verdicts/pm_us_crh_fq_v1/<date>/`. |
| Root cause | `docs/evidence/AUT-2_rc_monitor_pnl_2026-10-03.md`; the 10-04+ `position_monitor_report_*_pm_us_crh_fq_v1.md` reads `positions: 0` and `NO_MONITOR_FOR_KIND` |
| No expected failures | `systemctl --user list-units --state=failed 'breezy-*'` shows no outcome unit across the window. The `test_outcome_units_no_expected_failure` parametrisation passes. |
| Z14 / Z19 | The `test_aut2_canary_isolation` suite passes. The journal shows the line `Z19 ambiguous_open_at_1645Z days=` every run. |

---

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| The log bridge mislinks a Take to a fill (two takes on one instrument; log rotation at relaunch) | Requires a matching `client_order_id` `OrderFilled` line after the Take, and `now_ns ≤ ts_event`. Otherwise the fill is unmatched (null p, does not qualify). The node log is a file, never journald (memory note "trade node dies with the session"). The bridge retires to a cross-check in WP7. |
| Positions pull races live trading | ts-fencing (`ts_event ≤ snapshot_ns`), and an OPEN or AMBIGUOUS intent means UNKNOWN (L-52) |
| A settled position leaves the page (L-52) | Settled slugs are reconciled only on the settlement and cash legs, never the position leg |
| The exec store read fails when the node is down (WAL `mode=ro` needs the writer alive, ARCH Y5) | Both slots fall inside the node's 16:50Z–16:40Z life. A read failure means run ERROR, CRITICAL, no marker and a genuine unit failure. It is never an empty-store `NO_INPUT`. |
| Memory on the 30 GiB host | Measured `score-live-trials` peak is 137 MB. `MemoryMax=1G` under the studies flock. One flock holder at a time (§5.2). The run does not start 01:00–04:30Z. |
| The shared venv | Briefs name `/home/jon/breezy/.venv/bin/python`. No `uv`, no `pip`, never `uv run` (L-51). |
| Concurrent agents | Disjoint file ownership (§5). Per-agent scratchpads. No `git stash` (the hook blocks it). Each worktree is fast-forwarded onto `feat/data-capture-and-risk` first (memory note "agent worktrees start stale"). |
| The gross/net split hides a real cash loss | The net flag needs external flows `OK`. `external_flow_evidence_status != OK` or a mismatch day gives `INCONCLUSIVE`, never PASS (existing FU-13b labels). |
| Statistical capacity | Not an AUT-2 claim. Labels feed AUT-4. The ≥ 5 real fill floor is met in about 1–2 days at the current rate. |
| KILL 2027-01-25 | After a TERMINAL KILL the venue has no sender. Labels continue for remaining settlements, `NO_INPUT` runs exit 0, and the live-proof window pauses (ARCH §5.3). AUT-2's proof (ETA 10-23..10-30) is well before the KILL. |
| NWS outage or late final (2025 shutdown precedent) | Rows stay pending. Label lag over 24 h raises a HEALTH FAIL and an alert. Nearby-station substitution is never used (nws-cli-settlement skill). |
| A Kalshi family is admitted | The TWC settlement source refuses, so the gate fails until a reviewed TWC reader exists |

---

## 9. Binding-constraint compliance

- **Nautilus immutability.** No Nautilus file is touched. Reuse covers native `ClientOrderId`/`TradeId` joins and `Order.tags` (through C1). Everything AUT-2 adds is offline analysis.
- **The two caps.** Never read, written or derived. `test_autonomy_never_reads_or_writes_operator_controls` (ARCH §4.7) covers `analysis/labeling/`.
- **`allow_short=False`.** Untouched. AUT-2 only reads venue nets, and "short YES" is a reporting convention of the venue, not an order.
- **NO-SEND.** The label run makes no network call. The positions pull is GET-only on the existing host and pinned by `test_not_an_execution_egress_module` plus a GET-only AST test. `test_execution_egress_firewall_guard` is not edited.
- **Master enablement and permit.** Never read or written. Offline units only. No supervisor or node change.
- **PREREG via ruling.** No sequential or statistical semantics are defined here. The v2/v4 tallies are unchanged. The verdict action class and horizon come only from the AUT-5 policy ruling's pinned block.
- **Safety tests never weakened.** WP1 keeps `absent_markers_still_refuse`, and every existing settlement, contract and NO-SEND test stays as is. The legacy scored-trial store and its barrier tests are untouched.

---

## 10. Contradictions with ARCH (for the Rev 4 merge)

- **C-1 (C2 widening request, L-12).** C2 does not state whether `decision_id` is nullable. The `excluded_reason` enum lacks `slippage_defect` and `unattributed`, and there is no `p_source` column. Request: `decision_id` nullable only with `p_null_reason ∈ {pre_c1_log_unmatched}`; add `p_source ∈ {c1_decision_record, node_log_take_line}`; add `slippage_defect` to `excluded_reason`. Until then AUT-2 uses the closest existing semantics stated in §3.4–§3.5.
- **C-2 (slot).** ARCH §5.2's indicative label slot of 05:00Z cannot label the prior day (CLI finals arrive about 09:30–10:30Z; venue settlement is 12:00/13:00Z). This plan uses 14:15Z as primary and 05:00Z as catch-up (§3.10).
- **C-3 (producer scope).** The ARCH §5 table gives AUT-2 only C4 `RECONCILIATION`, but the C2 invariant requires a `HEALTH label_lag` FAIL. This plan has AUT-2 produce `HEALTH` with detector ids `aut2.label_lag` and `aut2.label_coverage`.
- **C-4 (Z19 source).** The intent history may not preserve `created_ns` (INFERRED). The fallback needs a supervisor journal line, which is AUT-5a's file.
- **C-5 (F4).** ARCH G28 notes the kind-scoped latch, but C6/C2 do not note that the FQ manifest's declared `trial_id_prefix` matches no key. Scorers must not rely on the prefix for discovery.

---

## 11. Self-score (author's estimate; not evidence)

| Axis | Max | Score | Note |
|---|---:|---:|---|
| Fidelity | 20 | 18 | Every README bullet and §10 obligation is mapped, plus Z14 and Z19. Slot and contract deviations are declared, not hidden. |
| Correctness | 20 | 17 | The root cause is proven from artefacts. Two premises remain INFERRED (venue NO-as-short on the positions page; intent `created_ns`), each gated by an L-1 step. |
| Specificity | 15 | 14 | Modules, functions, units, slots, limits and paths are named |
| Acceptance | 20 | 17 | The checklist has commands and paths. The live proof depends on AUT-6 delivery. |
| Autonomy-safety | 15 | 14 | Fails closed throughout. No caps, permit or firewall surface. Canary and drill are isolated. |
| Reuse | 10 | 9 | `score_trial`, CLI reader, ROI net path, capital-flow precedent, node Take log |
| **Total** | **100** | **89** | |

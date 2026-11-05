# AUTONOMY_ARCHITECTURE — umbrella architecture for AUT-1..AUT-7 (2026-10-03, FREEZE CANDIDATE Rev 8)

**Status:** FREEZE CANDIDATE Rev 8 (earlier revisions under `reviews/snapshots/`; §R8 disposes P7-7…P7-11, P1-8…P1-12,
P5-9…P5-11 and ROLLBACK-FAILURE). Nothing here is implemented. **Parent:** [README.md](README.md) (scale, score-3
criteria, binding constraints). **Ruling:** `docs/evidence/RULING_operator_full_autonomy_2026-10-03.md`. **Scope.** This
document defines the shared contracts C1–C6, the autonomy safety envelope and its invariants, the area boundaries, the
build order, the reuse map and the risks. Area procedure (drill steps, slot rows, detector catalogues, unit lists) is
not defined here: §10 lists what each AUT-n plan must specify. Each plan consumes the contracts and never redefines
them; a contract change is a change to this file, re-reviewed. **Evidence tags.** `file:line` was checked at `4b8347a6`.
**INFERRED** is unverified against running code and clears its L-1 check before the slice that relies on it starts.

## 1. Goal state

One unattended closed loop per venue. **Capture** (AUT-1): every decision, refusal, intent, order, fill, cancel, mark
and settlement, joined on one `decision_id`. **Label** (AUT-2): every fill scored against settlement and reconciled at
net position within 24 h. **Refit** (AUT-3): lineage-complete candidates from rolling external weather plus own labels.
**Evaluate** (AUT-4): offline and forward-shadow scoring against champion and market baseline, plus PREREG sequential
tests, each a C4 verdict. **Promote or demote** (AUT-5): an engine executes one pre-registered policy ruling into
hash-chained C5 transitions, picked up with no commit. **Drift** (AUT-6): node-local entry vetoes or C4 verdicts mapped
to halt, demote, self-heal or alert. **Rollback** (AUT-7): restore the last rollback-eligible champion at a
byte-identical sha, or halt.

Every area reaches score 3 by the same two levers:
- **Family-agnosticism by construction.** C6 makes a plug-in mandatory at registration, so no family can compose or send
  without one. A kind with no live family carries a `RefusingPlugin`.
- **Fail-closed by contract.** Every consumer of C1–C5 treats a missing, stale, unparseable, unknown-version or
  unverifiable record as the restrictive outcome: no promotion, an entry stop, an alert.

All of this happens inside the operator's two caps and the already-enabled live envelope (§4).

## 2. Ground truth the design rests on (verified)

| # | Fact | Evidence |
|---|---|---|
| G1 | Each node composes exactly one sending family, chosen by `BREEZY_SENDING_FAMILY_ID` (currently `pm_us_crh_fq_v1`). | `runtime/settings.py:106,116-125`; `app/trade.py:930-962`; `breezy-trade-supervisor.service:128` |
| G2 | The supervisor forwards its environment to the child unchanged. The child loads `deploy/families/<id>.json` relative to the CWD. | `runtime/trade_supervisor.py:849-876`; `app/trade.py:122,962` |
| G3 | Manifests are strict exact-set; the sha256 is over raw bytes read once; artefact paths are confined to `deploy/families` with `resolve()`, `..` and absolute refusals. | `persistence/family_manifest.py:122-137,266-282,285-296` |
| G4 | Real orders need a code-committed allowlist triple `(family_id, ruling_id, ruling_sha256)` plus a ruling file whose sha is re-verified at every boot. | `persistence/live_orders_gate.py:76-84,130-190` |
| G5 | A family halt is a durable exec-store key, "first cause wins", cleared only by the operator CLI. It vetoes in the exec client and the exit seam. | `trial_day_latch.py:1155-1191,1246-1314`; `crh/composition.py:221-254` |
| G6 | Halt writes need the submit-intent flock, which the node holds for its life. Readers use a lock-free `mode=ro` URI. | `trial_day_latch.py:354-379`; `app/trade.py:983-986` |
| G7 | `SqliteStateStore` is a thread-confined KV BLOB store, `journal_mode=WAL`, `synchronous=FULL`, no iteration API. | `runtime/sqlite_store.py:117-176` (pragmas `:123-124`) |
| G8 | Scored trials are append-only parquet, deduped on `(trial_id, max score_seq)`, with no `family_id`, leg or probability. | `persistence/scored_trial_store.py:24-31,60-89` |
| G9 | FQ submits with no `Order.tags`. Exit orders carry authorisation in native `Order.tags`. | `fq/strategy.py:681-688`; `persistence/exit_tags.py:1-25` |
| G10 | The FQ funnel records counts only. The CRH offer tape is per-decision JSONL with a byte-capped sidecar. | `fq/decision_funnel.py:1-24`; `crh/offer_tape.py:335-412` |
| G11 | The live calibration loader refuses any `recalibration` other than `none`. | `fq/calibration_artefact.py:281-295` |
| G12 | `nbp_learning_nightly` scores a frozen artefact and does not fit. The fitters live in `nbp_calibration`. | `nbp_learning_nightly.py:921-1023`; `analysis/nbp_calibration.py:1166,1280` |
| G13 | Candidate artefacts must live outside the repo. | `nbp_learning_nightly.py:688-735` |
| G14 | The promotion generator is advisory only; its criteria are PROVISIONAL. | `promotion_proposal.py:96-104`; `promotion_criteria.py:46-73` |
| G15 | `analysis` sits above `strategy`. Live packages never import `breezy.analysis`. `persistence` is importable by both. | `pyproject.toml:74-101,152-160` |
| G16 | In-node `Actor`s with clock timers already halt or alert. The fee probe calls `record_policy_halt` in-process. | `app/trade.py:442-484`; `fee_drift_probe.py:255,543` |
| G17 | Exit capability is a code allowlist containing only `pm_us_crh_exit_v4`. FQ has no exit. | `persistence/exit_gate.py:55-89` |
| G18 | The caps are read only from the environment, never defaulted, and pinned by an assignment scan. | `operator_controls.py:130-180`; `test_operator_control_assignment_scan.py` |
| G19 | **Only FQ composition calls the live-orders gate.** `current_rung_hold` and `continuous_rung_hold` hand `sending_permit` straight to their strategies. | `app/trade.py:546-571,575-673` vs `:740` |
| G20 | Exec-store halt reasons: `duplicate_fill` (`:1054`), `ambiguous_exit` (`:1144`), `policy_halt` (`:1182`; written by the fee probe with detail `fee_schedule_drift`, `app/trade.py:271,465`, and by the A1 set-halt CLI, `set_family_halt_cli.py:503`); plus the legacy key, pinned to v4 or `halts_all`. | `trial_day_latch.py:292-351` |
| G21 | The daily budget stop is **venue-scoped** (`exec/polymarket_us/budget_exhausted/<day>`), seeded from durable fills at boot. | `exec/client.py:399,566-575,2242-2270` |
| G22 | Supervisor cycle: STOP 16:40Z, LAUNCH 16:50Z, launch window closes 17:00Z. **All four spawn sites forward the supervisor's own environment, never the child's** (P5-3): LAUNCH (`:1289`), boot relaunch (`:1379`) and boot retry (`:1631`) pass `os.environ`; the mid-day relaunch passes a copy plus the existing `BREEZY_PERMIT_EXPIRY_CEILING_NS` (`:1977-1982`). | `trade_supervisor_core.py:37-59,131`; `trade_supervisor.py:1209-1301,1379,1631,1977-1982` |
| G23 | FQ `try_submit` runs `submit_veto` (the family-halt veto), and the same callable reaches the exec client. An entry-only veto needs its own slot. | `fq/strategy.py:629-643`; `app/trade.py:709-713,846-853` |
| G24 | A NO buy is `OrderSide.BUY` on a composite NO-leg `InstrumentId`; the adapter translates it to venue `SELL`/`BUY_SHORT`. Every entry is a BUY; exits are SELLs; OMS is `NETTING`. | `fq/strategy.py:682`; `symbology.py:289-295`; `leg_prices.py:41-48`; `exit_wiring.py:59-66`; `exec/client.py:1672` |
| G25 | `emit_alert` returns `None` and swallows every `BaseException`. `TeeAlertSink.emit` routes **each branch** through `emit_alert`, so a tee-level emit can never report a failure. `WebhookAlertSink.emit` raises on non-2xx (`raise_for_status`). The branches are exposed read-only. | `runtime/health.py:479-510`; `:366-369`; `:297-299`; `:362-364` |
| G26 | `breezy-check-alerts` calls `sink.emit` directly (not `emit_alert`) to prove delivery, but on the sink from `resolve_alert_sink`, which is a tee when configured, so its "not delivered" exit looks unreachable in production (**INFERRED**, AUT-6 RED-tests it first). | `check_alerts_cli.py:19-23,126,141`; `health.py:419-423` |
| G27 | Alert egress convention: one dedicated single-key `~/.config/breezy/alerts.env` (0600), loaded by `EnvironmentFile=-` in each unit that alerts; the only key is `BREEZY_ALERT_WEBHOOK_URL`. | `deploy/systemd/README.md:679-694`; `breezy-trade-supervisor.service:89`; `health.py:116` |
| G28 | The FQ persistent latch namespace is **kind-scoped** (`forecast_quantile_ladder/trial/`), keyed `(station, climate_day, rung_id, side)`, so a same-kind successor sees the same latch, but a YES latch does not block a NO entry on the same slug. | `fq/persistent_latch.py:68,87-94,124-136` |
| G29 | No unit under `deploy/` sets `RuntimeMaxSec` (`/usr/bin/grep -rn RuntimeMaxSec deploy/`: 0 hits); all 20 `Type=oneshot` units under `deploy/systemd` set `TimeoutStartSec` (recursive grep, 10-03; P1-11, P5-9). The host has 30 GiB RAM (`free -g`). | grep; `free -g` |
| G30 | The supervisor's `probe_open_intent` reads the exec store for an OPEN intent read-only but **asserts no live node** first, so it runs only with the node down (P7-6). The node repairs or keeps an OPEN intent at startup (`reconcile_at_startup`). | `trade_supervisor.py:400-418`; `runtime/submit_intent.py:441-483` |
| G31 | The fee-drift probe **is** wired for FQ (lazy slug), live since 10-02 (P6-1). FQ's positive feed lines exist: `NBM_NBP_PUBLISHED`, `FQ_VECTOR_COMPLETE` (P1-1). The WS idle timeout is 600 s, not 60 s (P1-2). | `app/trade.py:828-844`; `nbm_quantile_actor.py:543-551`; `forecast_subscriber.py:216-220`; `polymarket_us/config.py:293` |
| G32 | `RuntimeMaxSec` has no effect on `Type=oneshot` units (systemd.service(5); host systemd 259). 20 units under `deploy/systemd` are oneshot; existing bounds use `TimeoutStartSec` (P6-2). | `systemctl --version`; `breezy-score-live-trials.service:76` |
| G33 | `SubmitIntent` holds `intent_id` (UUID4) and `fingerprint` = `intent_fingerprint(order)`, a pure sha256 over instrument, side, qty, price, TIF and `client_order_id`; fills are indexed `fill_by_fingerprint/<day>:<fp>`. The exec client is byte-pinned (P1-3). | `submit_intent.py:37,391-411`; `submit_chain.py:242-253`; `exec/client.py:431-447`; `test_forecast_quantile_ladder_manifest_and_markers.py:114` |
| G34 | `_assert_artefact_path_contained` resolves against `manifest_dir / "deploy/families"`, i.e. `deploy/families/deploy/families`, which does not exist; `resolve()` of a missing path is lexical, so the symlink defence is vacuous, while the bytes are read CWD-relative (G2). fq_v1's artefact is a mutable repo file; no content-addressed copy exists (P7-5). | `family_manifest.py:169,262-282`; `deploy/families/artefacts/` |
| G35 | fq_v1 cites `RULING_operator_fq_live_real_orders_2026-10-01`, the sole `_LIVE_ORDERS_ALLOWLIST` entry (P7-1). Its `trial_id_prefix` `forecast_quantile_ladder/trial/pm_us_crh_fq_v1/` matches no stored latch key; those are kind-scoped (G28; P2-5). | `deploy/families/pm_us_crh_fq_v1.json`; `live_orders_gate.py:76-84` |
| G36 | `run_sequential_looks`, the group-sequential boundaries, the calibration leg, the market baseline and `check_drift`/`check_freshness` live under `scripts/analysis/`, outside every `breezy.*` import closure, so §4.3 pins cannot cover them (P4-4). | `scripts/analysis/{family_tally_v2,crh_group_sequential_boundaries,forecast_conditional_scoring,wp7b_market_as_forecaster,nbp_learning_nightly}.py` |
| G37 | `DEFAULT_SPLITS` sets `holdout_start=2026-07-01` and **no end**, so the sealed holdout grows forward forever (P3-1, P4-1). | `analysis/nbp_calibration.py:273-278` |
| G38 | The FQ node loads its artefact **by path**: it passes `manifest.density_artefact_path` and the manifest sha to `load_live_calibration`, which reads once, hashes and parses that one buffer and refuses a mismatch, following symlinks (P7-10). | `app/trade.py:788-789`; `calibration_artefact.py:236-256` |
| G39 | `is_fee_verified` is node memory only: unset at every boot, set only on AGREE, no store key (P7-11). Each probe outcome is logged. | `fee_drift_probe.py:290-295,543-564`; `app/trade.py:314-339` |
| G40 | The supervisor schedule poll is 60 s (P5-11). The recorder rotate unit uses `systemctl --user try-restart`, a no-op on a deliberately stopped unit (P1-10). | `trade_supervisor_core.py:1866`; `breezy-quote-tape-rotate.service:47-55` |

**L-1 null hypothesis per new component.**
- Nautilus has no artefact registry, champion/challenger state, promotion engine or scheduled restart
  (`WORK_BREAKDOWN:288`; `trade_supervisor.py:15-21`).
- Reused Nautilus features: `Order.tags` (G9); `ClientOrderId`/`TradeId` for the order-to-fill join
  (`exec/client.py:400-412`); `Actor` plus `clock.set_timer` (G16); `ParquetDataCatalog` for tape-shaped capture.
- **`TradingState.REDUCING` is insufficient; the custom entry veto is retained.**
  `nautilus_trader/risk/engine.pyx:1150-1163` denies a BUY only when `is_net_long(instrument)`. Every Breezy entry is a
  BUY into a usually **flat** instrument (G24), which REDUCING admits, and REDUCING is node-global, so it cannot express
  per-family state. (`account_presence_halt.py:171` sets `HALTED`, not REDUCING.) The veto uses the native `try_submit`
  guard slot, an extension.

## 3. Shared contracts

**Common rules (apply to C1–C5):**
- Every record carries `schema: "<contract>/v<N>"`. Readers accept only allowlisted versions and refuse anything else.
  Schemas are exact-set and grow only by L-12 widening with their readers.
- Serialisation is explicit (no `dataclasses.asdict`). Writes are atomic (`mkstemp` + `os.replace`;
  `runtime/health.py:322,330`), append-only, named by content hash or `now_ns`. Timestamps are integer ns UTC from the
  injected clock. Money is a string-decimal.
- **One writer per file (L-50; P1-6, P6-6).** Every autonomy file is either write-once (named by content hash, or
  `now_ns` plus writer id, never rewritten) or has exactly **one writer process type**, serialised by its own flock or
  by the exec submit-intent flock (G6). Two writer types on one file is a defect (`test_autonomy_files_have_one_writer`:
  a table of path pattern → writer unit).
- Stores live under `~/.local/share/breezy/{state,derived,registry,evidence}/`, never in the repo, plus the one existing
  `decisions/` sibling of the quote-tape catalog root (`crh/composition.py:568-575`), retention-managed, which holds C1
  (P1-5). Directories 0700, files 0600, content-addressed files 0444.
- **Single-read rule (Y4, Z16).** Every consumer of a C3 artefact, C3 lineage, C4 verdict, C5 export, registry child
  manifest, drill marker, restrictive-demand file, engine or health heartbeat file, engine input journal, capture
  payload or alert-delivery record opens it with `O_NOFOLLOW` (a symlink anywhere on the path is refused), reads it
  **once** through one descriptor, and hashes and parses those same bytes.
- **Payload hygiene.** Alerts, C1 records and C4 verdicts carry no absolute paths, env values, account or venue order
  ids, or credentials; venue order ids appear only as `sha256`. Reuses the `AlertPayload` forbidden-content list
  (`registry/health_model.py:217-235`). A scan test covers every autonomy writer.
- Python types live in one new package, `src/breezy/persistence/autonomy/`, importable by node and analysis (G15). Grep
  the containment tests first (L-46).

### C1 — Decision id and capture schema (producer AUT-1; consumers AUT-2, AUT-4, AUT-6)

**`decision_id`** = the first 32 hex characters of `sha256(family_id | manifest_sha256 | artefact_sha256
| station | climate_day | rung_id | side | eval_ns)`.
- `eval_ns` is the Nautilus `clock.timestamp_ns()` at decision, **recorded** in the `DecisionRecord`; the recorded value
  is authoritative. Recomputation uses the record's own fields and never re-derives `eval_ns` (a test recomputes the id
  from a stored record).
- It travels as the native order tag `breezy:decision_id=<id>`, defined next to the exit prefixes
  (`persistence/exit_tags.py`), set at each kind's one `order_factory.limit` call (`fq/strategy.py:681`; CRH
  `_maybe_submit`).
- **Exit decisions (P1-8).** An exit order carries its four native exit tags (`exit_tags.py`) instead of a `decision_id`
  tag; its id is the first 32 hex of a pure sha256 over those values (AUT-1 pins it), recorded as
  `DecisionRecord(kind=Exit)`, `depth_ref` nullable for `Exit` only (`test_every_exit_fill_joins`).

**Record types.** All share `schema`, `decision_id`, `family_id`, `ts_ns`, `node_boot_id`, `build_sha`, `registry_seq`,
`drill` (bool, Y2) and `source` (`live` \| `canary`).

| Type | Fields | Writer |
|---|---|---|
| `DecisionRecord` | `kind` (`Take` \| `Refuse` \| `NotExecutable` \| `NotDPlus1` \| `TrySubmit` \| `EntryVeto` \| `Exit`, P1-8); `reason`; `eval_ns`; `station`, `climate_day`, `rung_id`, `side`, `instrument_id`; `ask_px`; `depth_ref` (sha256 of the Depth10 payload, L-35); `p_hat`, `p_hat_raw` (pre-recalibration, P3-3), `p_lower`, `p_upper` (the kind's YES-leg values, as FQ computes them, `fq/decision.py:331,349`), `ev_net`; `forecast_input_sha256`; `artefact_sha256`; `manifest_sha256` | node, via the C6 `CaptureAdapter` |
| `OrderLink` | `client_order_id`; `venue_order_id_sha256: str\|None`; `instrument_id`, `side`, `qty`, `px`, `time_in_force` (the G33 fingerprint inputs) | node `on_order_*` |
| `LifecycleEvent` | `event` (`SUBMITTED` … `AMBIGUOUS`); `client_order_id`; `trade_id`; `qty`, `px`, `fee` | node |
| `PositionMark` | `instrument_id`; `leg`; `net_qty` (signed, venue convention, C2); `mark_px`; `source` | node or position monitor |
| `DetectorEvent` | `detector` (C6 id); `observation_sha256`; `state` (`AGREE` \| `DISAGREE` \| `UNKNOWN`) | in-node detectors |
| `SettlementRecord` | `station`, `climate_day`, `settlement_tmax_f`, `basis`, `raw_sha256` | offline settlement unit (own file) |

`drill` is true for every record of a family inside a **drill episode** (Z2): the fold interval from its `DRILL_PROMOTE`
taking effect through the `ROLLBACK` pair that closes it. Fills after the drill's DEMOTE and RESUME are still drill
fills (`test_drill_flag_spans_promote_to_rollback`). Records of a family whose pair was voided post-launch (Z8) keep
that `family_id` and are labelled `voided_pair` (C2, W14).

**Storage.** A daily file `decisions/capture_<family_id>_<YYYY-MM-DD>.jsonl`, following the `OfferTape` and
`FqDecisionFunnelActor` convention (`crh/composition.py:568-602`; `app/trade.py:763-775`); the existing retention unit
compresses it. Its only writer is the node, serialised by the submit-intent flock (G6).
- **Settlements (P1-6).** `SettlementRecord`s go to their own daily file `decisions/settlement_<YYYY-MM-DD>.jsonl`,
  written only by the offline settlement unit under its own lock.
- **Payload store (P1-4).** `depth_ref` and `forecast_input_sha256` name write-once, content-addressed payloads at
  `derived/capture_payloads/{depth10,forecast_input}/<sha256>.json` (0444, schema `payload/v1`, `mkstemp` + `os.link`,
  so an existing name is never replaced). The node writes a payload only with the C1 record citing it (write-on-change,
  L-29); a missing payload marks the record `capture_gap`. AUT-1 measures the volume; retention archives payloads with
  the daily file and never drops one a C3 lineage cites.
- **The join without editing the exec client (P1-3).** The exec client stays byte-pinned (G33) and no C1 field needs it.
  The join key is the Nautilus `client_order_id`, present in every `DurableFillRecord`. The audit links intents offline:
  it recomputes the pure `intent_fingerprint` (G33) from the OrderLink fields and matches
  `fill_by_fingerprint/<day>:<fp>`, the `SubmitIntent` singleton and the resolver contexts (`exec/client.py:449-454`),
  all through the G6 read-only URI. `intent_id` is not a C1 field.
- **No silent cap.** A write failure or byte cap increments a counter, raises a CRITICAL alert and marks the day
  `CAPTURE_INCOMPLETE`.
- A `Refuse` or `EntryVeto` is written when `(key, reason)` changes, not on every tick (L-29). Every `Take` and
  `TrySubmit` is written.
- **Rejected:** `StreamingConfig` on the trade node (memory and flush risk); reopened only by L-1 proof.

**Invariants.** (i) Every submitted entry order carries exactly one `decision_id` tag, and every exit order its four
exit tags (a test per composable kind). (ii) Every durable fill (`exec/client.py:408-447`) joins to exactly one
`DecisionRecord` through `client_order_id`. (iii) The daily audit requires decisions ⋈ links ⋈ fills ⋈ settlements =
100% for every settled live fill. (ii) and (iii) bind from `capture_epoch_start`, the first LAUNCH of the tagged build
(recorded by AUT-1); earlier fills are C2 `unattributed` (P2-1).

**Failure behaviour.** A missing or malformed tag refuses an entry submit (`capture_untagged`, a C5 `VetoReason`; P1-9).
A write error raises a CRITICAL alert and makes the day inadmissible for AUT-4. A join gap is a `HEALTH` FAIL.

### C2 — Scored-outcome label (producer AUT-2; consumers AUT-3, AUT-4, AUT-6)

**Schema `label/v1`.** One parquet file per run at `derived/labels/<family_id>/labels_<now_ns>.parquet`, append-only,
deduped on `(label_id, max label_seq)` (the G8 conventions). The scored-trial store stays untouched. The pyarrow schema
is pinned column for column.

Fields: identity (`label_id`, `decision_id` (nullable, P2-1), `family_id`, `trial_id`, `client_order_id`, `trade_id`);
market (`station`, `climate_day`, `instrument_id`, `rung_id`, `leg`, `role` `entry`\|`exit`); fill (`qty`, `fill_px`,
`entry_ask`, `fee_reconciled`, `slippage`, str-decimal); `p_at_decision` and `p_raw_at_decision` (float64, the **bought
leg's** win probability: C1 `p_hat`/`p_hat_raw` for a YES buy, 1 − those for a NO buy, matching `settled_outcome`;
nullable only with a reason; P3-3, P3-9; `test_p_at_decision_is_bought_leg_probability`); `p_source` (`c1_decision` \|
`artefact_recompute` \| `none`; P2-1); settlement (`settled_outcome` = the bought leg's win, `settlement_tmax_f`,
`settlement_basis`); P&L (`realized_pnl` net of reconciled fee; `counterfactual_hold_pnl` for exits); reconciliation
(`reconciled`, `reconciliation_delta`, `reconciliation_source`, `net_position_key` = base slug); admissibility
(`admissible`; `excluded_reason` ∈ `duplicate_fill`, `q≠1`, `fee_unreconciled`, `window_incomplete`, `canary`, `drill`,
`voided_pair`, `slippage_defect` (fill better than the ask, L-25), `unattributed` (null `decision_id`)); run metadata
(`labelled_at_ns`, `label_seq`, `scorer_id` = C6 id plus producer code sha).
- **`trial_id` (P2-5)** is the stored latch key itself (kind-scoped for FQ, G28, G35). Family attribution comes only
  from C1 `family_id` through `decision_id`, never from a `trial_id_prefix` match
  (`test_scorer_never_attributes_by_trial_id_prefix`).
- Only `p_source=c1_decision` rows feed AUT-3 own-outcome fits or any AUT-4 statistic; a null `decision_id` row is never
  `admissible`.

**Invariants.**
- **Net-position reconciliation.** "Reconciled" means **the venue's net signed position per base instrument equals the
  ledger's** (Y15), not that the position is flat. A NO holding nets as short YES on the same slug (L-44;
  `parsing.py:277-279`), so YES and NO fills on one slug are summed with the leg sign before comparison. RED tests: a NO
  fill offsetting a YES holding reconciles to the netted venue quantity; each leg's terminal state.
- Only `window_complete` rows are scored or counted.
- Every live fill is labelled within 24 h of its `SettlementRecord`, else a `HEALTH` FAIL (`label_lag`), which AUT-2
  produces (P2-3). Primary labelling is 14:15Z, once the prior climate day has settled; 05:00Z is the catch-up slot
  (P2-2).
- `reconciled=False`, `source=canary`, `drill=true` and `excluded_reason=voided_pair` (W14) are never `admissible` and
  never count toward any production or drill n, any live-sequential look or the KILL clock (Y2). Drill and voided-pair
  fills are real money, so they **do** feed the DRIFT detectors, the drawdown limit and the venue daily budget (W12;
  `test_detectors_and_drawdown_include_drill_fills`, `test_voided_pair_fills_excluded_from_all_n`).
- "Nothing to score" exits 0 with a `NO_INPUT` line. No unit exits non-zero as expected behaviour.

**Failure behaviour.** A fill that cannot be labelled becomes an `excluded_reason` row; a score is never fabricated
(`trial_scorer.py:158`). Reconciliation outside tolerance: `reconciled=False`, a CRITICAL alert and a `RECONCILIATION`
FAIL.

### C3 — Artefact lineage manifest (producer AUT-3; consumers AUT-4, AUT-5, AUT-7)

**Storage.** Content-addressed and immutable: `derived/artefacts/<model_class>/<artefact_sha256>/{artefact.json,
lineage.json}`. Files 0444, directories 0500, single-read rule. The layout generalises the G13 candidate root; the
artefact bytes use the existing writer (`nbp_calibration.py:2643`).

**Schema `lineage/v1`.**
- `artefact_sha256`; `model_class` (`composition_kind:component`); `lineage_root_family_id`; `parent_artefact_sha256`;
  `code_git_sha`, `build_sha`, `producer_code_sha` (§4.3); `params`; `seed`; `fit_status` (`OK` only); `data_windows`
  (`{source, start_utc, end_exclusive_utc, rows, content_sha256}`).
- Own-outcome use: `own_outcome_label_set_sha256` (str \| null) records the C2 label set used;
  `ablation_artefact_sha256` is the same refit with that set left out, and the writer refuses the lineage if it is
  non-null and equals `artefact_sha256`.
- **The C2-consuming model class** is `forecast_quantile_ladder:rung_recalibration`, fitted on C2 `(p_raw_at_decision,
  settled_outcome)`, the pre-recalibration probability, so own-outcome refits continue once a recalibrated champion
  exists (P3-3). It needs the G11 loader widening with parity tests, which re-points (never deletes) the existing
  loader-refusal test at the forms outside the widened set (P3-8). `forecast_quantile_ladder:density_table` consumes
  external weather only. **No FQ class consumes execution data** (fill, slippage, refusal); those feed AUT-4 evaluation,
  which the README AUT-3 clause "where the model class consumes them" permits (P3-7).
- **Own-outcome effect (P3-4).** A sha difference from the ablation can be vacuous (metadata only), so the lineage
  records `own_outcome_max_abs_delta_p`, the maximum |Δp| between artefact and ablation over a pinned grid; the writer
  refuses a non-null own-outcome lineage unless it is > 0 (`test_own_outcome_effect_not_vacuous`).
- Evaluation windows: `train_end_exclusive_utc`, `forward_eval_start_utc` (≥ `created_at`).
- `leakage_assertions`: `{name, passed}`, including `ref_ts_lt_take_ts`, `train_end_lt_forward_eval_start` and
  `no_sealed_holdout_rows_in_train` (the frozen C4.1 window).
- `recalibration` and `correction_form` are members of the live loader's accepted set (G11).
- Run metadata: `created_at_ns`; `runtime_s`; `peak_rss_bytes`.

**Invariants.** `sha256(artefact.json) == artefact_sha256`. A scheduled rerun from `lineage.json` on a sampled subset
reproduces the sha; a mismatch is a `HEALTH` FAIL. A lineage with a failed assertion is never written.

**No-new-lineage children (Y2).** A child whose `artefact_sha256` equals an existing artefact (the drill child) gets
**no new C3 record**: its MINT row cites the existing content-addressed directory, the C3 writer is not invoked, and no
`lineage_counters` entry increments.

**Bootstrap roots (P7-5).** A committed root has no `lineage.json`. BOOTSTRAP reads the committed manifest and its
artefact once, verifies the artefact against the manifest's `density_artefact_sha256`, and copies the bytes to
`derived/artefacts/<model_class>/<sha>/artefact.json` (0444) with `root.json` (`root/v1`: `family_id`,
`manifest_sha256`, `artefact_sha256`, `committed_path`) in place of a lineage. A root is authorised by its commit and
G4, not by C3, so "ineligible above SHADOW" does not apply to it. The resolver reads **every** family's artefact from
this store, so ROLLBACK to `fq_v1` restores the BOOTSTRAP-row sha even if the repo file changes
(`test_rollback_to_root_reads_content_addressed_copy`).

**Run record `refit_run/v1` (P3-6).** Every refit run writes one write-once file
`evidence/refit/<model_class>/<now_ns>.json`: `run_id`, `lineage_root_family_id`, `model_class`, `outcome` (`MINTED` \|
`NO_CHANGE` \| `REFUSED` \| `MINT_REFUSED_CEILING` \| `ERROR`), `reason`, `artefact_sha256` (null unless MINTED),
`data_windows`, `own_outcome_label_set_sha256`, `runtime_s`, `peak_rss_bytes`, `producer_code_sha`. AUT-3's live proof
counts these; a scheduled run with no record is a `HEALTH` FAIL. `MINT_REFUSED_CEILING` is written only when
`MAX_MINTS_PER_LINEAGE_PER_DAY` refuses; there is no `NO_CHANGE(k_max_reached)`, because K_LIFETIME limits nominations,
not mints (ALPHA amendment).

**Failure behaviour.** A missing or mismatched lineage makes the artefact ineligible above SHADOW. A rollback
re-verifies the target's bytes; a mismatch makes that target ineligible, never a venue freeze (C5 Failed rollback).

### C4 — Verdict (producers AUT-2, AUT-4, AUT-6; consumer AUT-5, plus AUT-7 triggers)

**Storage.** `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json`; directories 0700; files append-only;
`verdict_id` = sha256 of the canonical body **minus `verdict_id` and `produced_at_ns`** (P4-11); `valid_until_ns` is
slot-anchored and stays in it, so a recompute dedupes, and the store refuses a different body under an existing id
(`test_differing_body_same_id_refused`). Producers run as their own oneshot units, separate from the engine unit and the
node.

**Schema `verdict/v1`.**
- Identity: `verdict_id`; `kind` (`OFFLINE_CHALLENGER` \| `FORWARD_SHADOW` \| `LIVE_SEQUENTIAL` \| `DRIFT` \| `HEALTH`
  \| `RECONCILIATION`); `subject_family_id`; `subject_artefact_sha256`; `comparator_family_id`.
- Outcome: `outcome` (`PASS` \| `FAIL` \| `UNDERPOWERED` \| `INCONCLUSIVE` \| `ERROR`); `detector` (C6 id);
  `declared_action_class` (`NONE` \| `ALERT` \| `SELF_HEAL` \| `DEMOTE` \| `HALT`).
- Measurement: `metrics` (pre-registered names only); `n` and `n_min` **in the unit the ruling names for that kind**
  (independent station-days for `FORWARD_SHADOW`, Y14); `power`; `mde`; `eta_to_verdict_days`; `alpha_spent`
  (cumulative, lineage-level); for `FORWARD_SHADOW` also `k_life`, `alpha_k`, `n_min_eff` and `n_cap` (ALPHA; null on
  other kinds).
- Provenance: `inputs` (`{path_role, sha256}`, no paths); `policy_ruling_sha256` (null only with `assumptions ∋
  no_policy_ruling`) and `family_prereg_sha256` (`LIVE_SEQUENTIAL` only: the family's registered boundary ruling; null
  otherwise) (P4-10); `produced_at_ns`; `valid_until_ns`; `producer_code_sha`; `assumptions` (closed enum:
  `slippage_champion_proxy`, `slippage_floor_aud12a`, `fill_survivorship_unmodelled`, `no_policy_ruling`, `drill`;
  P4-12).

**Evaluation protocol.**
- `OFFLINE_CHALLENGER` is the **screening** stage: every candidate is scored against the champion on external weather at
  the ruling's fixed thresholds with the pinned bootstrap (`roi_bound.py:93-100`), on forward days (≥ 2026-10-02) after
  its training end, never on the frozen holdout (C4.1). It charges no α. The frozen holdout opens at most once, for the
  one confirmatory use C4.1 names (`holdout_opens`).
- `FORWARD_SHADOW` evaluates the challenger prospectively on post-mint days. It requires all of: (a) traded-rung Brier
  beats the **market-implied baseline** (reusing `wp7b_market_as_forecaster`, relocated per G36); (b) EV net of
  reconciled fee and slippage; (c) the traded-rung calibration leg is **non-inferior to the champion's** on the same
  station-days within the ruling's margin (`forecast_conditional_scoring.py:392`); an absolute leg pass is reported, not
  required, because it false-fails good models (P4-6); and (d) `n ≥ n_min` in **independent station-days**: takes within
  one `(station, climate_day)` form one cluster and count once (Y14).
  - **Admissible inputs (Y12).** Only tape days that pass the replay-sufficiency check (memory note
    `quote-tape-is-not-replay-sufficient`) are inputs; AUT-4 r1 measured 80 of 80 closed station-days passing, about
    3.64 a day (P4-3; INFERRED until the feasibility record). Other days are excluded by name.
  - **Slippage source (Y12).** Slippage comes from C2 champion fills against the same Depth10 rows. Using the champion's
    slippage for a challenger with a different policy is an assumption: the verdict must carry `assumptions:
    [slippage_champion_proxy]`, and the policy ruling must state whether it accepts that assumption for the challenger's
    policy class. Without that statement, such a verdict is `INCONCLUSIVE`.
- **Multiple testing (Y13, W7, P4-5, P3-2, P4-8, ALPHA as amended).** Screening and confirmation are split. Candidates
  are minted at ≤ 1 MINT per lineage per day **across all model classes** (a MINT's artefact may change any component,
  so the classes share the slot; a per-class ceiling adds mints, not testable α) and screened without α; a mint that is
  never nominated spends no α. α is charged only by a **nomination**: the SHADOW→CHALLENGER PROMOTE that starts a
  confirmatory `FORWARD_SHADOW`. Forward windows tumble per lineage from the block's `forward_window_anchor_date`
  (`forward_window_days` within §4.5); a nominee uses only forward days after its nomination inside its window, so
  windows never overlap and screening days are never confirmation days.
  - **Two limits, one index.** The store refuses a nomination when the window already holds one
    (`MAX_NOMINATIONS_PER_FORWARD_WINDOW` = 1) or the lineage's α-charging nominations reach **K_LIFETIME** (≤ 4; named
    K_max in Rev 6 and the area plans). `k_life`, assigned at nomination and stored in the row's verdict metrics, counts
    α-charging nominations and **never resets** across windows or epochs; nominee k is tested at α_k =
    α_total·2^−k_life, so Σα ≤ α_total per lineage, and k_life ≤ K_LIFETIME by construction (P4-8). Two pending nominees
    never share a k. Only a new lineage root, a reviewed commit, starts a fresh budget. Drill rows are never
    nominations. The ruling states the MDE at α_K = α_total·2^−K_LIFETIME.
  - **No `k_exceeded` in operation (P3-10).** ARCH fixes the limits, so no verdict with k_life > K_LIFETIME is ever
    produced; a verdict whose `k_life` differs from the registry's index for its nominee is `ERROR` (`k_exceeded` in the
    engine journal) and a defect alert.
  - **Window-cap rule (ALPHA 3).** Each nomination fixes `n_min_eff` (from the pinned σ and the ruling's MDE) and `n_cap
    = stations·window_days·uptime_floor`. If n_min_eff > n_cap, every `FORWARD_SHADOW` for that nominee is
    `INCONCLUSIVE(window_cap_below_n_min)` **by construction**, decided at nomination and immutable. A test that can
    never reject spends no type-I error, so such a nomination charges **no α and no K_LIFETIME** (`alpha_k = 0`,
    `k_life` unchanged, `infeasible_nominations` incremented) but still uses the window's slot. Under today's σ and X
    this is every candidate (n_min 403–605 > n_cap ≤ 480), consistent with `promote_enabled=false`: the verdicts flow
    and exercise the machinery; no promotable path is claimed (machinery proven, edge unproven).
  - **Draw cap (ALPHA 2).** Bootstrap and permutation draws stop at `BOOTSTRAP_B_MAX`, with an exact or analytic tail
    beyond. Tests `test_nomination_refused_past_k_max_lifetime`, `test_alpha_index_never_resets`,
    `test_mint_unlimited_by_k_max_but_one_per_day`, `test_two_pending_nominees_get_distinct_k`,
    `test_window_cap_below_n_min_is_inconclusive`, `test_infeasible_nomination_charges_no_alpha`.
- `LIVE_SEQUENTIAL` reuses `run_sequential_looks` (`family_tally_v2.py:625`) and its boundaries
  (`crh_group_sequential_boundaries.py:243`), never defines a new α-spend, counts admissible labels only (no canary, no
  drill), and is used mainly to demote. A family with no registered boundary (FQ today: none is registered and its fills
  predate any pre-registration; P4-2) gets `INCONCLUSIVE(no_registered_boundary)`, which never acts; other DEMOTE paths
  are unaffected. AUT-4 drafts the FQ boundary ruling, counting only fills after its filing, for peer review by about
  11-10. All C4 statistics run from `src/breezy` (G36, §4.3).

**Invariants.** Every verdict states `n_min` or the literal reason it has none.

**Engine acceptance.** The engine acts on a verdict only if: `producer_code_sha` is in the committed producer pin set
(§4.3); every `inputs[].sha256` resolves under that role's root; `policy_ruling_sha256` equals the policy ruling's, and
for `LIVE_SEQUENTIAL` `family_prereg_sha256` equals the family's registered boundary ruling; `declared_action_class`
equals the ruling's `detector → action_class` entry; `valid_until_ns − produced_at_ns` ≤ `MAX_VERDICT_VALIDITY_H`, or ≤
`ATTEST_VERDICT_VALIDITY_H` for a verdict an ATTEST cites (§4.5, Z4, W1); and **`subject_artefact_sha256` equals the
subject family's bound artefact sha** (Z1): the `artefact_sha256` of its BOOTSTRAP or MINT row. A family id is bound to
one immutable artefact; the store refuses any later row for that family carrying a different `artefact_sha256`, so rows
that carry none (ATTEST, SUPERSEDE, DISPLACED, DEMOTE, RESUME) never move the comparison. Any mismatch makes the verdict
`ERROR`, with an alert; it never acts. Tests `test_verdict_accepted_after_attest`,
`test_family_artefact_binding_immutable`. **Restrictive fallback (P4-10; AUT-5 M10).** With no filed or verifiable
policy ruling the engine runs restrictive-only: it accepts a FAIL carrying `no_policy_ruling` only for DEMOTE or HALT,
with the class taken from the literal `DEFAULT_RESTRICTIVE_CLASS[detector]` in `pins.py`, never for a widening row
(`test_demotion_never_requires_policy_and_is_immediate`, `test_no_policy_fail_demotes_never_widens`).

**Failure behaviour.** A verdict past `valid_until_ns` is `ERROR`. `ERROR`, `INCONCLUSIVE` and `UNDERPOWERED` never
promote. An accepted `FAIL` mapped to `DEMOTE` or `HALT` always acts. Champion staleness is enforced node-side (C5 watch
actor), independent of the engine (Y3).

### C4.1 — `RULING_holdout_freeze_and_forward_window_2026-10-03` (ARCH-owned text; P3-1, P4-1)

Filed verbatim under `docs/evidence/` in Wave 0 after peer review (not an operator decision). AUT-3 and AUT-4 cite it by
name and never restate a variant.
1. **Freeze.** The NBP archive holdout is frozen at **[2026-07-01, 2026-10-02)**. `DEFAULT_SPLITS` (G37) gains
   `holdout_end_exclusive = 2026-10-02` by a reviewed L-12 widening (AUT-3), with a RED test that no fitter or screener
   reads a row inside it. It stays sealed for **one** final confirmatory use under the existing single-look marker
   (`nbp_calibration.py:330-345`).
2. **Forward data.** Days on or after 2026-10-02 are forward data. AUT-3 trains only on days before each candidate's
   `forward_eval_start_utc` (`train_end_lt_forward_eval_start`). AUT-4 evaluates on a rolling forward holdout of
   post-training days under the C4 α-spend.
3. **Contamination disclosure.** The September tape studies (WP-7b, AUD-02, the 09-20 terminal finding) touched
   [2026-07-01, 2026-10-01). S2 on that window is descriptive evidence only, never a confirmatory input.
4. A conflicting split in any AUT plan is void; changing this text is an ARCH change, re-reviewed.

### C5 — Registry, state machine and transition audit (owner AUT-5; AUT-7 co-writes through the same API)

**Storage and isolation.**
- SQLite at `~/.local/share/breezy/registry/registry.sqlite`, dir 0700, file 0600. It is not the exec store, because of
  the flock (G6) and no iteration (G7).
- **Journal mode (Y5): `journal_mode=DELETE`, `synchronous=FULL`**, unlike G7's WAL: the writer is a oneshot that exits,
  SQLite removes `-wal`/`-shm`, and a `mode=ro` reader on a read-only directory cannot recreate them. A hot journal from
  a crashed engine fails the read-only open → `registry_unreadable` (fail-closed until the engine rolls it back). RED
  test `test_registry_readonly_open_engine_stopped` (dir 0500, `mode=ro` open plus chain verify).
- **Single writer:** `breezy-autonomy-engine.service` in its daily, intraday and pre-launch modes, one binary
  (`ReadWritePaths=` registry and evidence only, `ProtectSystem=strict`, memory cap), serialised by
  `registry/engine.lock` (`flock -w` per mode, §5.2 table), never the studies flock (Y23). AUT-7 runs inside it; operator tools write
  through the same API (`decided_by=operator_cli`). **Readers** use the `mode=ro` URI (`trial_day_latch.py:354-379`);
  the node's spawn carries `ReadOnlyPaths=` on the registry directory.
- **Residual risk, stated:** a same-uid writer could rewrite the chain (or forge a heartbeat or demand file)
  consistently. Chain, export and HWM give tamper *evidence*; *resistance* is in code: a row selects only among
  candidates the committed allowlists and sha-pinned rulings authorise (§4.2); a forged heartbeat still meets H.

**One chain per venue (Y20).** Each venue has its own hash chain, CAS counter and genesis `sha256("registry/v1|" +
venue)`. The global `seq` only orders rows; it never links them. Lineage counters are venue-independent.

**Tables (`registry/v1`).**
- `transitions` is the only source of truth. Columns: `seq` PK; `venue`; `venue_seq` (UNIQUE with `venue`);
  `transition_id` UNIQUE; `family_id`; `family_prior_seq` (the `venue_seq` of this family's previous row, or 0);
  `paired_transition_id` (set on the partner of an atomic pair; null on the PROMOTE side, whose id is computed first,
  and on unpaired rows; Z20); `from_state`; `to_state`; `kind`; `cause_verdict_ids` (JSON); `cause_code`,
  `halt_cause_class` and, on a `rollback_failed` HALT, `trigger_cause_class` (DEMOTE and HALT only; closed enums in
  `pins.py`); `voids_transition_ids` (JSON, `SWAP_CANCEL` only); `manifest_sha256`, `artefact_sha256`,
  `lineage_root_family_id` (**required** on BOOTSTRAP, MINT, PROMOTE, DRILL_PROMOTE, ROLLBACK, ACTIVATE; Y6);
  `attest_valid_until_ns` (ATTEST only); `hwm_from`, `hwm_to` (HWM_RESET only); `drill` (bool) and
  `drill_clause_sha256`; `policy_ruling_id`; `policy_ruling_sha256`; `decided_by`; `invocation_id`; `engine_code_sha`;
  `expected_prior_seq`; `effective_launch_date` (null means immediate); `ts_ns`; `prev_transition_hash`;
  `transition_hash`. Triggers `BEFORE UPDATE` and `BEFORE DELETE ON transitions` → `RAISE(ABORT)`.
- `families` and `projection` are **derived caches**, rebuilt in the same transaction and **never read by the node, the
  supervisor or the resolver** (Y4). They exist for the engine and humans.
- `lineage_counters`: `holdout_opens`, `nominations` (lifetime, α-charging, = max `k_life`; P4-5),
  `infeasible_nominations` (ALPHA 3), `alpha_spent`, `mints` and `promotions` (timestamped), `rollbacks`,
  `terminal_frozen` (Y10), and a separate drill budget (`drill_admits`, `drill_promotes`, `drill_resumes`,
  `drill_rollbacks`; Y2), and the venue-level `infra_resumes` (Z10).

**Hash chain.** `transition_hash = sha256(canonical row ‖ prev_transition_hash)` within the venue chain. A daily export
`evidence/registry/registry_<venue>_<date>.jsonl` (0444) holds every new row, the chain head and a monotone
`export_seq`. Readers verify against the **newest** export (highest `export_seq`; an HWM_RESET export supersedes, W4)
and refuse a chain whose prefix disagrees with it. Exports are never deleted.

**Engine input journal `engine_input/v1` (P4-9).** Writer the engine; schema and contract test owned by AUT-4. One
write-once JSONL per pass, `evidence/engine_inputs/<venue>/<date>/<mode>_<ts_ns>.jsonl` (0444), one row per verdict
read: `pass_id`, `pass_mode`, `verdict_id`, `kind`, `subject_family_id`, `detector`, `acceptance`, `reject_reason`
(closed: `expired`, `unpinned_producer`, `sha_mismatch`, `no_ruling`, `action_class_mismatch`, `subject_unbound`,
`k_exceeded`, `input_unresolved`), `acted`, `transition_id`. Every verdict valid at pass start for a family in the fold
appears exactly once; every `cause_verdict_ids` entry appears with `acted=true`; a pass that cannot write its journal
writes no widening row (`test_every_live_verdict_journaled_once_per_daily_pass`,
`test_cause_verdict_ids_subset_of_acted_rows`).

**Effective-time fold (Y8).** `resolve_champion(venue, now)` is a pure function of the verified chain and the clock. It
is the **only** source of state, of the X8 invariant and of "pending":
- A row with `effective_launch_date = D` is **pending** before LAUNCH on D (16:50Z, G22).
- At LAUNCH on D a pending pair takes effect **only if** an `ACTIVATE` row for that pair was written in [16:40Z, LAUNCH)
  on D by the pre-launch pass (§4.4). Otherwise the pair **lapses**: it never takes effect, the incumbent stays
  champion, and the engine must propose afresh.
- A `SWAP_CANCEL` row voids the pending rows it lists. **Post-launch cancel (Z8):** a SWAP_CANCEL written in [LAUNCH,
  17:00Z) on D that cites the pair which took effect at D's LAUNCH voids it retroactively; the fold restores the
  incumbent, the watch actor vetoes the voided family (`registry_not_champion`) on its next tick, and the supervisor,
  still inside its launch-window retry, stops that child and launches the resolved incumbent. From 17:00Z an effective
  pair is never voided; a cause then takes the DEMOTE path. Test `test_post_launch_swap_cancel_restores_incumbent`.
- A lapsed or voided pair is never charged to any §4.5 counter (Z3).
- The invariant **each venue has at most one family in {CHAMPION, HALTED}** is evaluated on the fold at `now`. `next_*`
  in the cache is only a rendering of pending rows.

**States.** `SHADOW` (offline only), `CHALLENGER` (passed the offline gate, never sends), `CHAMPION` (the single sender
per venue), `HALTED` (champion with entries stopped for cause), `RETIRED` (terminal).

**Allowed transitions.** This is the whole set; the store refuses any other pair or kind.

| From → To | Kind | Allowed when | Effective |
|---|---|---|---|
| ∅ → CHAMPION, ∅ → RETIRED | BOOTSTRAP (P5-2) | Genesis transaction of an empty venue chain only, ids in the literal `pins.BOOTSTRAP_SEED` (CHAMPION: `pm_us_crh_fq_v1`; RETIRED: v4, cont, v2), with the C3 root copy | now |
| ∅ → SHADOW | BOOTSTRAP / MINT | Committed root, or a child passing §4.2 equality and C3 (or the C3 no-new-lineage rule), complete C6; mint-rate ceiling | now |
| SHADOW → CHALLENGER | PROMOTE (nomination) | Accepted `OFFLINE_CHALLENGER` PASS; no nomination yet in the window and α-charging nominations < K_LIFETIME (C4) | now |
| SHADOW → CHALLENGER | DRILL_ADMIT (Z2) | Drill clause active; the incumbent folds **CHAMPION** (not HALTED) and is not `demoted_for_cause` (W2); the C3 no-new-lineage equality holds (artefact sha, and manifest modulo §4.2, equal the incumbent's); no α, nomination or K_LIFETIME charge; drill budget | now |
| CHALLENGER → CHAMPION | PROMOTE | Accepted `OFFLINE_CHALLENGER` **and** `FORWARD_SHADOW` PASS; policy `promote_enabled` (§4.2); lineage not `terminal_frozen`; §4.4; rate limit | pending → next LAUNCH |
| CHALLENGER → CHAMPION | DRILL_PROMOTE (Y2) | Drill clause active, its sha pinned in the policy block; the incumbent folds **CHAMPION** and is not `demoted_for_cause` (W2); the child's `artefact_sha256` **and** manifest (modulo the §4.2 key allowlist) equal the incumbent's; drill budget; §4.4 | pending → next LAUNCH |
| CHALLENGER → CHAMPION | ROLLBACK | Target `rollback_eligible`, never `demoted_for_cause`, not `target_integrity`-ineligible; left CHAMPION ≤ `ROLLBACK_TARGET_MAX_AGE_D` ago; `ROLLBACK_MIN_DWELL_H` met (P7-7); fee verified by AUT-6 verdict (P7-11); lineage not `terminal_frozen`; bytes re-verified; §4.4; rollback budget; the pre-launch pass may write it with its ACTIVATE in one transaction (P7-4) | pending → next LAUNCH |
| CHAMPION → CHALLENGER | SUPERSEDE | The atomic partner of an incoming →CHAMPION; sets `rollback_eligible=true`, except on the drill-episode family, which means **the minted drill child only**: the incumbent a DRILL_PROMOTE supersedes (`fq_v1`) becomes eligible, so the drill's closing ROLLBACK to it is admitted (W3) | pending → next LAUNCH |
| HALTED → CHALLENGER | DISPLACED | The atomic partner of an incoming →CHAMPION; `rollback_eligible` stays false | pending → next LAUNCH |
| CHALLENGER → CHALLENGER | ACTIVATE | Pre-launch pass, §4.4 re-verified on the incoming family, cites the pending pair | confirms the pair |
| CHALLENGER → CHALLENGER | SWAP_CANCEL | Restrictive: §4.4 failed at pre-launch, a DEMOTE or HALT cause on either family of a pending pair, or an engine-detected inconsistency. **Always permitted, never capped** | now (voids the pair) |
| CHAMPION → CHAMPION | ATTEST (Y3, W1) | **Intraday** engine pass: cites, for **every** `(kind, detector)` pair in `attest_required_detectors` (intraday `HEALTH` and `RECONCILIATION` producers only; P4-7, Z5), its newest accepted verdict as a PASS within `ATTEST_VERDICT_VALIDITY_H`; a daily (26 h) verdict is never citable (`test_attest_requires_every_listed_detector`); `attest_valid_until_ns` = their minimum `valid_until_ns`, refused above `ts_ns + H` (Z4); at most one per venue per `ATTEST_PERIOD_H`, under the §4.5 cadence invariant; non-widening, never counted | now |
| CHAMPION → HALTED | DEMOTE / HALT | Accepted FAIL mapped to DEMOTE or HALT; an exec-store halt mirrored; or a **failed rollback** (P7-3, ROLLBACK-FAILURE): HALT, `cause_code=rollback_failed`, non-freezing class `ROLLBACK_FAILED`, `trigger_cause_class` = the trigger's class. Clears `rollback_eligible`, sets `demoted_for_cause`. A pending pair naming this family is voided by a `SWAP_CANCEL` in the same transaction, and this family is **never superseded** by it. **Always permitted, never capped** | now |
| HALTED → CHAMPION | RESUME | `halt_cause_class` ∈ {RECOVERABLE_MODEL, RECOVERABLE_INFRA, DRILL}, or `ROLLBACK_FAILED` with such a `trigger_cause_class` (charged to it); cause verdict now PASSes; the fold names this family; **no pending pair on the venue** (Y8); cooldown and the budget of its own cause class only (§4.5, Z10, W2); §4.4; **written only by the 16:45Z pre-launch pass** (P7-9) | now |
| HALTED → RETIRED | RETIRE | TERMINAL cause, or the RECOVERABLE_MODEL resume budget is exhausted. S_k and n are frozen (`WORK_BREAKDOWN:423`). An exhausted INFRA or DRILL budget never retires (Z10, W2) | now |
| SHADOW, CHALLENGER → RETIRED | RETIRE | Policy (age, failed gate, lineage superseded) | now |
| any → same state | HWM_RESET (Z17, W4) | Operator CLI only (`decided_by=operator_cli`), node stopped; restored chain verifies as a prefix of the newest export; post-reset fold at least as restrictive as the export's (C5 HWM reset); records `hwm_from`/`hwm_to` and `carried_counters`; non-widening, never counted | now |

**Pending-swap rules (Y8).** A DEMOTE or HALT cause on the **incoming** family writes `SWAP_CANCEL`; the incoming family
stays CHALLENGER with `demoted_for_cause=true`, so it is never promotable or a rollback target in this lineage until a
fresh `FORWARD_SHADOW` PASS post-dating the cause. A cause on the **outgoing** champion writes `SWAP_CANCEL` and
CHAMPION→HALTED in one transaction; the incoming must be re-proposed through DISPLACED. Tests:
`test_demote_during_pending_swap_incoming`, `test_demote_during_pending_swap_outgoing`,
`test_resume_refused_while_swap_pending`, `test_unactivated_pair_lapses_at_launch`.

**Terminal lineage freeze (Y10).** A TERMINAL cause (a `policy_halt` mirror, fee drift, A1, or an exhausted resume
budget) sets `terminal_frozen` on the lineage. PROMOTE, DRILL_PROMOTE and ROLLBACK into **any** family of that lineage
are refused; only a new lineage root (a reviewed commit) recovers. Test `test_terminal_halt_freezes_lineage`.

**Failed rollback (P7-3; `reviews/ROLLBACK-FAILURE-decision.md`, binding).** **Target integrity:** selection re-verifies
each candidate's stored bytes against its BOOTSTRAP or MINT row; a mismatch makes the target ineligible
(`rollback_eligible=false`, `cause=target_integrity`, in the rollback journal; cleared only as AUT-7 specifies, never by
an operator), with a CRITICAL, and selection moves on; it was never loaded, so nothing freezes
(`test_target_byte_mismatch_ineligible_without_freeze`). **Failure** (no eligible target, rollback budget exhausted,
pair lapsed or SWAP_CANCELled): the engine writes HALT `cause_code=rollback_failed`, class `ROLLBACK_FAILED`, on the
champion if it still folds CHAMPION, with a CRITICAL through `deliver_with_proof`; it halts only that family (no venue
freeze, `terminal_frozen`, RETIRE or budget charge; never `RECOVERABLE_INFRA`, P7-8), and the daily or pre-launch pass
retries daily, a success displacing it (`test_failed_rollback_halts_champion`,
`test_rollback_failed_never_freezes_venue`). **Champion's own bytes** are re-verified at every load (artefact handoff);
a mismatch is INTEGRITY with the existing freeze (`test_champion_own_artefact_mismatch_at_load_is_integrity`). **Fee
verified (P7-11):** `is_fee_verified` is node memory (G39), so selection and the drill start gate read the newest
accepted AUT-6 `DRIFT` verdict for `fee_schedule` (from the probe's `DetectorEvent`s), a PASS within
`ATTEST_VERDICT_VALIDITY_H`; none means unverified (`test_rollback_fee_check_uses_verdict_not_node_memory`).

**Idempotency (Y9).**
- `transition_id` = sha256 of `(venue, family_id, family_prior_seq, from, to, kind, sorted cause_verdict_ids,
  paired_transition_id, policy_ruling_sha256)`. The venue-wide `expected_prior_seq` is excluded, so a crash-and-retry
  before commit reproduces the id, while a later, legitimate repeat of the same transition for the same family has a new
  `family_prior_seq` and a new id. In a pair, the PROMOTE-side id is computed first and the partner cites it.
- Each write is one `BEGIN IMMEDIATE` transaction. If `transition_id` exists, the write is a logged no-op. Otherwise:
  (1) the CAS `max(venue_seq) == expected_prior_seq` must hold; (2) the row is inserted, extending the venue chain; (3)
  the caches are re-folded.
- Non-restrictive writes: on a CAS failure, re-read, re-evaluate, retry once, then alert.
- **Restrictive writes (DEMOTE, HALT, SWAP_CANCEL; Y19)** retry until committed: bounded backoff for up to 60 s within
  the pass, then again on every intraday pass. If the first attempt fails, the engine immediately writes a
  **restrictive-demand file** (Z11), write-once per (venue, family, ts, writer):
  `registry/demand/<venue>/<family_id>_<ts_ns>_<writer>.json` (atomic, 0444, schema `demand/v1`, exact-set, ≤
  `DEMAND_FILE_MAX_BYTES`). The watch actor reads each under the single-read rule and honours it as
  `registry_restrictive_pending` for that family until the chain shows the family HALTED, RETIRED or not CHAMPION at a
  row later than the demand's `ts_ns`; the engine then moves it (atomic rename) to `evidence/demand/<venue>/` and never
  unlinks it (W16; `test_retired_demand_file_archived`). An unparseable, oversized or symlinked file, or more than
  `DEMAND_FILES_MAX` per venue, vetoes **every** family on the venue. A demand can only stop entries, so it needs no
  authentication. Tests `test_restrictive_commit_failure_sets_node_veto`, `test_bad_demand_file_vetoes_venue`.
- **Second writer, restrictive only (P6-12).** A producer in the literal `DEMAND_WRITER_PRODUCER_IDS` (`pins.py`;
  initially AUT-6's INTEGRITY floor in `aut6.intraday`) may write a demand file through the same `demand/v1` writer,
  with `reason=integrity_floor` and its `verdict_id`, beside its verdict; its unit gets `ReadWritePaths=` on
  `registry/demand/` only. Only the engine archives demands; no producer renames, edits or deletes one, so a producer
  can add a stop but never lift one (`test_producer_demand_write_is_restrictive_only`).
- Tests: `test_registry_cas_and_idempotent_replay`, `test_repeat_supersede_same_family_is_not_replay`.

**Pickup.**
1. **Activation, at LAUNCH.** The supervisor (`_do_launch`, `trade_supervisor.py:1209`; G22), the node
   (`app/trade.py:905-990`) and the settings validator (`settings.py:183,366-388`) all call one resolver in
   `persistence/autonomy/resolver.py`.
   - It verifies the venue chain from genesis, checks the export prefix and the node high-water mark, folds at `now`,
     and returns a `ResolvedFamily`: family id, `registry_seq`, chain head, and manifest and artefact bytes and shas,
     each under the single-read rule.
   - **Byte binding (Y6).** The resolver compares the single-read manifest and artefact bytes against the
     `manifest_sha256` and `artefact_sha256` on the authorising row; takes the root from the child-id regex
     `<root>_r<NNNN>` and requires it to equal the row's `lineage_root_family_id`; and checks §4.2 manifest equality
     against the **committed** `deploy/families/<root>.json`, never a registry copy.
   - `_validate_sending_family_manifest` and `_compose_family` consume that object and never re-read the manifest.
   - **Artefact handoff (P7-10).** The live loader re-reads the artefact, today by manifest path (G38); the node instead
     passes the resolver's content-addressed store path and the row's `artefact_sha256`, so the loader's one-buffer
     read-hash-parse (`calibration_artefact.py:250-256`, widened to `O_NOFOLLOW`) re-verifies by sha at load. A mismatch
     refuses composition (CRITICAL `registry_boot_load_failed`) and is the champion's own-artefact INTEGRITY event,
     whose HALT the engine's next pass writes (`test_node_loads_artefact_from_store_by_row_sha`).
   - `BREEZY_FAMILY_SOURCE` ∈ {unset, `registry_shadow`, `registry`}, fixed in
     `deploy/systemd/breezy-trade-supervisor.service`; a scan test proves no autonomy code reads or writes it except the
     resolver. Only `registry` binds.
   - **Shadow stage (P5-7).** `registry_shadow` resolves against the separate root
     `~/.local/share/breezy/registry-shadow/`: the supervisor logs `registry_resolve_shadow agree=<bool>` and spawns the
     env family unchanged; the watch actor logs `entry_veto_shadow` and never refuses, and keeps its HWM in memory only,
     so shadow rows never arm Y7 (`test_registry_shadow_logs_agreement_and_spawns_env_family`,
     `test_shadow_never_vetoes_or_arms_hand_relaunch_rule`).
   - **Env handoff (P5-3).** The supervisor resolves **once** per LAUNCH and keeps that state. One pure
     `build_child_env(base, state)` in `trade_supervisor_core.py`, called at **all four** spawn sites (G22), sets
     `BREEZY_SENDING_FAMILY_ID` and `BREEZY_RESOLVED_REGISTRY_SEQ` from it and passes every other key, the existing
     permit ceiling included, byte-identically (`test_child_env_touches_only_registry_keys`). These are build-side
     values, not operator controls. Relaunches reuse the LAUNCH state, so nothing swaps mid-day.
   - **Relaunch rule (Z7).** The node re-resolves and compares the **family id only**, and checks that the passed seq is
     a prefix of the verified chain (≤ head, chain verifies through it). It refuses boot only if the fold at `now` names
     this family neither CHAMPION nor HALTED. A HALTED family boots with only entries vetoed (`registry_halted`), so its
     exit seam and reconciliation stay live. Hand relaunches use the supervisor-provided registry-aware helper
     `breezy-trade-relaunch` (§10 AUT-5), which resolves exactly as LAUNCH does; it replaces the hand `systemd-run`
     runbook. Its write-once relaunch request is valid for `RELAUNCH_REQUEST_TTL_S` = 120 s, two 60 s schedule polls
     (G40, P5-11); the supervisor unlinks it before handling and dedupes on `request_id`
     (`test_request_ttl_covers_two_schedule_polls`). Tests `test_node_relaunch_rule_family_id_and_seq_prefix`,
     `test_halted_family_boots_entries_vetoed_exits_live`.
   - **Hand-relaunch bypass closed (Y7).** Once the production registry has any row, or the node-local high-water mark
     exists, the node **refuses boot to a sending family** unless `BREEZY_FAMILY_SOURCE=registry` **and** the resolved
     id equals `BREEZY_SENDING_FAMILY_ID`. A hand relaunch that mirrors a stale environment is therefore refused, not
     trusted. Test `test_hand_relaunch_without_registry_source_refused`.
   - **Resolver refusals** give "no champion" for: a `composition_kind` outside `LIVE_GATE_ROUTED_KINDS` (today
     `{forecast_quantile_ladder}`, G19); a child whose `live_orders_ruling` is not the policy ruling, or whose root is
     not in `_LINEAGE_POLICY_ALLOWLIST`; a ruling sha mismatch; a broken chain or export; a high-water-mark regression;
     an authorising `engine_code_sha` outside the pin set (§4.3); a byte-binding or §4.2 equality breach.
   - **Root exemption (P7-1).** A root (BOOTSTRAP row; manifest bytes equal the committed `deploy/families/<id>.json`)
     is authorised as today, by its own triple in `_LIVE_ORDERS_ALLOWLIST` (G4, G35); the policy-ruling rule binds
     children only. `fq_v1` resolves, and a ROLLBACK to it uses the same rule
     (`test_root_resolves_under_live_orders_allowlist`).
2. **Deactivation, immediate: `RegistryWatchActor`.** A native `Actor` with `clock.set_timer` (the fee-probe pattern,
   G16), 60 s tick. Its contract:
   - **Thread contract (Z16, L-1 verified).** The `LiveClock` callback runs on a Rust `_DummyThread` with no running
     loop (`ingest/nws_actor.py:27-31,67-80`; `tests/contract/test_live_timer_thread_affinity.py:90-119`), not on the
     thread that built the exec `SqliteStateStore`, whose `_check_thread` raises on a foreign thread
     (`runtime/sqlite_store.py:117-136`). The callback only submits `tick_once()` with
     `asyncio.run_coroutine_threadsafe` (the `FeeDriftProbeActor` bridge, `fee_drift_probe.py:358-372`). Every registry
     read, fold, HWM write and veto update runs on the loop thread, which also runs `try_submit`, so the veto state
     needs no lock. Test `test_watch_actor_store_touches_stay_on_loop_thread`, with a negative control.
   - **It never reads `projection` (Y4).** Each tick it reads the transitions with `venue_seq` above its last verified
     row, verifies the hash links from its stored head, re-checks that the row at the last verified seq still has the
     stored hash, and folds in memory.
   - **High-water mark (Y4).** The node keeps `(registry_seq, chain_head)` per venue at the exec-store key
     `autonomy/registry_hwm/<venue>`, written under the flock it already holds (G6); the registry never writes the exec
     store. A lower seq, or a different head at the same seq, gives `registry_regressed` and a CRITICAL. The HWM
     advances only after a verified read. The halt mirror reads only exact keys under `continuous_rung_hold/`
     (`trial_day_latch.py:291-295,354-379`), so `autonomy/` keys are never mirrored
     (`test_autonomy_exec_keys_disjoint_from_halt_prefixes`).
   - **HWM reset (Z17, W4).** A legitimate restore uses the operator CLI `breezy-registry-hwm-reset`, node stopped (it
     needs the exec flock). In order it: (1) verifies the restored chain as a prefix of the newest export; (2)
     re-applies, as new `decided_by=operator_cli` rows, the restrictive effect of every dropped row (DEMOTE, HALT,
     SWAP_CANCEL, RETIRE, `demoted_for_cause`, `terminal_frozen`, INTEGRITY freeze), and DEMOTEs (RECOVERABLE_INFRA) any
     family that would fold less restrictive than in the export; (3) **refuses** unless, per family and lineage, the
     post-reset fold is at least as restrictive (RETIRED > HALTED > CHALLENGER/SHADOW > CHAMPION; flags ⊇); (4) appends
     `HWM_RESET` with `carried_counters`, applied as floors, so no budget is refunded; (5) writes a new export (next
     `export_seq`); (6) sets the node HWM; (7) writes `evidence/registry/hwm_reset_<ts>.json` citing the replaced
     export's sha and the dropped `transition_id`s, with a CRITICAL through `deliver_with_proof`. Tests
     `test_hwm_reset_cli_journals_alerts_and_chains`, `…_cannot_unhalt`, `…_never_refunds_counters`,
     `test_resolver_resolves_after_hwm_reset`.
   - **Entry-veto contract (Y1, Y3, Y16, W10).** `entry_veto(instrument_id) -> VetoReason | None`, wired into a **new,
     separate `entry_veto` slot** in each strategy's `try_submit`, never into `submit_veto` (G23), so exits stay open.
     The slot is a **required, non-Optional** constructor parameter with no default
     (`test_compose_refuses_without_entry_veto_slot`, one case per composable kind). Reasons (closed enum):
     - registry: `registry_not_champion`, `registry_halted`, `registry_unreadable`, `registry_regressed`,
       `registry_restrictive_pending`;
     - dead-engine (Y3, Z4, Z5): `registry_attest_expired` (now past the family's newest ATTEST `attest_valid_until_ns`;
       armed for a family only once the chain holds an ATTEST for it, until then `registry_chain_stale` bounds it);
       `registry_engine_heartbeat_stale` (the intraday engine pass atomically rewrites
       `registry/heartbeat/<venue>.json`, 0444, with `ts_ns`, `invocation_id`, `engine_code_sha` and the verified chain
       head; the veto fires past `ENGINE_HEARTBEAT_STALE_S` ≈ 1 h, or when the named head is not on the verified chain);
       `registry_chain_stale` (chain-head age past H = 30 h, the backstop);
     - transient, node-local (Y1, Z13): `feed_stale`, `recorder_stale`, `permit_lapsed`, `capture_gap`, each from an
       in-node observation; `capture_untagged` (P1-9: the untagged entry itself is refused, C1;
       `test_capture_untagged_is_a_veto_reason`); `alerts_undeliverable` (W13, P6-6: scans today's and yesterday's UTC
       delivery-record directories by name; vetoes unless the newest `delivered=true` record, canary or CRITICAL, is
       younger than `ALERT_CANARY_MAX_AGE_H`; both absent or unreadable vetoes);
     - position (Y16, W6): `rung_net_position_held`, from `rung_has_net_position(base_slug)` in
       `persistence/autonomy/entry_guard.py`: durable exec-store fills netted with the leg sign (C2), covering the
       opposite leg and a successor family, which the kind-scoped latch (G28) does not. **Exact-key reads only** (G7),
       through the G6 read-only URI, on existing indexes (`exec/client.py:408-447`): `fill_index/<instrument_id>` lists
       venue order ids; `fill/<venue_order_id>` holds the `DurableFillRecord` (`:923`); the day-keyed `fill_by_day/`
       (`:429`) is unused. It reads the YES and composite NO-leg (G24) indexes, then each record; no new index.
       **Layering (W6, P5-4):** `persistence` sits below `adapters`, so the guard takes an injected `FillReader`
       Protocol, implemented in `adapters/polymarket_us/exec/fill_reader.py` over these exact keys and wired by
       `app/trade.py`; contract `breezy.persistence.autonomy ↛ breezy.adapters`. **Hot path:** a per-tick cache per
       slug, dropped every tick and on each own fill. An unreadable index or missing record vetoes (`_read_fill_index`,
       `:4712`). Tests `test_entry_guard_exact_key_reads_only`, `…_cache_invalidated_on_fill`,
       `…_unreadable_index_vetoes`.
   - **Fail-closed start (Z6).** `entry_veto` returns `registry_unreadable` from construction until the first verified
     tick, and at call time whenever `last_verified_tick_age > WATCH_TICK_STALE_S` (3 × 60 s). Test
     `test_entry_veto_closed_before_first_tick_and_on_stale_tick`.
   - Every reason except `registry_not_champion` and `registry_halted` **auto-clears** on the next good observation;
     `registry_unreadable` and `registry_regressed` clear **only after a verified read**; `registry_not_champion` and
     `registry_halted` clear on the **first verified tick whose fold names the family CHAMPION**, so a RESUME needs no
     relaunch (W5; `test_resume_clears_registry_halted_without_relaunch`). A node-local veto writes no registry row,
     sets no HALTED state and spends no damping budget (Y1). It writes a C1 `EntryVeto` record and alerts on the
     transition.
   - The timer never raises (L-16); an exception sets `registry_unreadable`.
3. **Registry children** live at `~/.local/share/breezy/registry/families/<id>.json` (0444, single read), with artefacts
   content-addressed beside them. This takes one reviewed L-12 widening of the containment at four sites
   (`family_manifest.py:169,266-282`, `app/trade.py:122`, `settings.py:183`, `settings.py:366-388`), keeping `resolve()`
   and the `..` and absolute refusals, adding `lstat`/`O_NOFOLLOW` with a symlink RED test. It also fixes the phantom
   base (G34): containment is checked against the directory the bytes are read from (repo `deploy/families`, or the
   registry root), with a RED test refusing a symlinked `artefacts/`. Child ids `<root>_r<NNNN>` match both id regexes
   (`settings.py:115`; `trial_day_latch.py:301`).

**Demotion latency (Y1).** Two paths, two SLOs:
- **Transient, node-local:** the in-node observation to `entry_veto` is at most one detector period plus one 60 s tick
  (≤ 2 min).
- **Verdict-driven:** an intraday producer (`breezy-autonomy-producer-intraday`, its own oneshot, 5 min timer) turns
  `DetectorEvent` records into C4 verdicts; the **intraday engine pass** (5 min timer, offset 150 s after the
  producer's; no `.path` unit, because one does not watch the nested `derived/verdicts/<family>/<date>/` leaves; Z12)
  runs in a **restrictive-only mode** that can write only DEMOTE, HALT, SWAP_CANCEL and the non-widening ATTEST
  (code-enforced; W1), and stamps the heartbeat; the watch actor picks the row up on its next tick. SLO: DetectorEvent
  to entry veto ≤ 15 min. If the engine is dead, the heartbeat veto bounds exposure at about 1 h and H is the backstop.
- `test_demotion_latency_slo` drives both paths under a fake clock; `test_intraday_engine_is_restrictive_only`.

**Exec-store halt mirror.** The engine mirrors exec-store halts read-only. Fixed mapping:

| Exec-store reason (G20) | Cause class | Registry effect |
|---|---|---|
| `duplicate_fill`, `ambiguous_exit` | INTEGRITY | HALTED; the venue is frozen for PROMOTE, RESUME and ROLLBACK until build-side incident handling clears it (W15, below; L-48) |
| legacy key `halts_all` | INTEGRITY | Same, for every family on the venue |
| legacy key `attributable_to_v4` | (none; v4 is seeded RETIRED) | No venue freeze |
| `policy_halt`, detail `fee_schedule_drift` | TERMINAL | HALTED → RETIRED; lineage `terminal_frozen`. θ is part of the estimand and §4.2 forbids a child from changing it |
| `policy_halt`, any other detail (A1 CLI) | TERMINAL | HALTED → RETIRED; lineage `terminal_frozen` |
| A read failure or an unknown payload | INTEGRITY | No non-restrictive transition that run; persisting past H, HALTED/INTEGRITY |

- **RECOVERABLE causes never use the exec-store halt.** Transient conditions are node-local vetoes (above). RECOVERABLE
  registry DEMOTEs are verdict-driven: a `DRIFT` or `HEALTH` FAIL the policy maps to DEMOTE, including a transient
  condition that persists past its policy horizon. Fee drift stays exec-store-halting, unchanged.
- **Cause classes (Z10, W2).** `RECOVERABLE_MODEL` (forecast and calibration drift, fill-rate and slippage, live
  sequential) consumes `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` and escalates to TERMINAL. `RECOVERABLE_INFRA`
  (freshness, permit and process liveness, unit health, capture, delivery) never consumes it; its own
  `MAX_INFRA_RESUMES_PER_VENUE_7D`, once exhausted, ends in HALTED with an INTEGRITY freeze and a CRITICAL, never RETIRE
  or `terminal_frozen`. `DRILL` (only `DRILL_INJECT` and `DRILL_INJECT_HALT`) charges only the drill budget; an
  exhausted drill budget leaves the child HALTED for the ROLLBACK, never RETIRE or `terminal_frozen`. `ROLLBACK_FAILED`
  (P7-8) is a separate non-freezing class, never `RECOVERABLE_INFRA`, so an exhausted infra budget can never turn a
  rollback failure into an INTEGRITY freeze; it resumes only under its `trigger_cause_class`. The policy block maps each
  detector to one class (`test_infra_cause_never_retires`, `test_drill_resume_never_charges_model_budget`).
- **Clearing an INTEGRITY freeze (W15)** is build-side incident handling, never an operator decision: the build
  coordinator evidences the root cause under `docs/incident-reports/`, has it peer-reviewed, then clears through the
  existing halt CLI (G5) and the registry CLI on the C5 API (`operator_cli` names the tool, not the decider). There is
  no autonomous clear; the venue stays frozen until then (accepted residual, §7).

**Relationship to existing controls.** A node sends only if the resolver says CHAMPION, `entry_veto` is clear, the
exec-store halt is clear (G5), the live-orders gate passes (G4), a permit exists, and the caps admit the order. The
registry adds vetoes; only PROMOTE, DRILL_PROMOTE, RESUME and ROLLBACK widen, within §4.2; it never writes the exec
store. The daily budget stays **venue-scoped** (G21), seeded from durable fills at boot; drill fills spend it and a
sender change never resets it (Z18; `test_swap_cannot_exceed_daily_budget_across_namespaces`,
`test_drill_fills_spend_venue_budget`).

**Failure behaviour.** Any registry failure gives an entry veto and **no permit-bearing composition**, with **no
fallback to the lineage root**: at LAUNCH no sending family is composed, the supervisor raises CRITICAL
`REGISTRY_UNAVAILABLE` and retries until 17:00Z, and C1 marks the day `CAPTURE_INCOMPLETE(registry_unavailable)`; tape
capture continues (`test_registry_unavailable_mints_no_permit`).

**Bootstrap.** Genesis BOOTSTRAP rows (with the C3 root copy) from `pins.BOOTSTRAP_SEED` (P5-2): `pm_us_crh_fq_v1` →
CHAMPION; `pm_us_crh_v4`, `pm_us_crh_cont` and `pm_us_crh_v2` → RETIRED (never HALTED, so they cannot freeze the venue).
DRAFT manifests are not seeded. A later committed root enters at SHADOW (`test_bootstrap_seed_genesis_only`).

### C6 — Family plug-in contract (owned here; implemented per kind by AUT-1, 2, 4 and 6)

Protocols in `persistence/autonomy/plugin.py`:

| Member | Layer | Signature (sketch) | Output |
|---|---|---|---|
| `CaptureAdapter` | strategy | `decision_record(decision, ctx)`; `order_tags(decision_id)` | C1 |
| `Scorer` | analysis | `label(capture_day, exec_fills, settlements)` | C2 |
| `Evaluator` | analysis | `offline(candidate, champion)`; `forward_shadow(candidate, champion, tape)`; `live(labels)` | C4 |
| `DriftDetectors` | both | `tuple[Detector, ...]`, each with `id`, `kind` (`NODE_LOCAL` \| `VERDICT`) and `evaluate(...)` | `EntryVeto` or C4 |
| `Refitter` | analysis | `refit(windows) -> (artefact, Lineage)`, or `NOT_FITTABLE` | C3 |

- **Registries:** `NODE_PLUGINS` (strategy layer) and `OFFLINE_PLUGINS` (analysis layer), keyed by `CompositionKind`
  (`family_manifest.py:115-121`).
- **YAGNI.** A kind with no non-RETIRED family registers `RefusingPlugin`, which refuses mint and compose: today
  `current_rung_hold`, `continuous_rung_hold`, `forecast_ladder`. **Its `Scorer` stays real until the kind's last fill
  is labelled** (P2-6; retired CRH kinds hold fills), then may refuse
  (`test_retired_kind_keeps_scorer_until_last_fill_labelled`). A kind gets full plug-ins in the same change that admits
  it to `LIVE_GATE_ROUTED_KINDS`.
- **Gate tests:** `set(NODE_PLUGINS) == set(OFFLINE_PLUGINS) == _COMPOSITION_KINDS`; every non-RETIRED manifest resolves
  to full plug-ins; a `RefusingPlugin` kind never reaches SHADOW.
- **Runtime:** `_compose_family` (`app/trade.py:853`) refuses boot when the plug-in is missing or refusing; the engine
  refuses ∅→SHADOW and any →CHAMPION with incomplete or refusing plug-ins.
- **Required detector classes per kind:** freshness, forecast drift, calibration drift, fill-rate and slippage, fee and
  shape drift, permit and process liveness, unit health. Removing one fails the gate. A `VERDICT` detector's action
  class comes from the policy map, never from the detector. A `NODE_LOCAL` detector's action is fixed in code as
  `ENTRY_VETO` (restrictive only; the policy may escalate a persisting condition through a `VERDICT` detector, never
  loosen it).
- **`DRILL_INJECT` (Y2)** is a dedicated `VERDICT` detector id. A pinned detector reads the drill marker
  `registry/drill/marker.json` (written only by the engine under the active drill clause, single-read rule). It emits
  FAIL while the marker exists and **PASS when it is absent** (Z2); the engine removes the marker once the DEMOTE row
  commits, so the cause verdict PASSes and RESUME can follow. The policy maps `DRILL_INJECT → DEMOTE` with cause class
  `DRILL` (W2) **only while the drill clause is active**; outside it the engine treats the verdict as `ERROR`.
- **`DRILL_INJECT_HALT` (P6-4).** A second dedicated `VERDICT` id, read from the same marker (`detector:
  DRILL_INJECT_HALT`), mapped `→ HALT` with cause class `DRILL`, only under the drill clause. The engine writes a
  registry `HALT` row; it never writes the exec store, sets `terminal_frozen` or an INTEGRITY freeze, and charges only
  the drill budget (`test_drill_halt_never_freezes_or_writes_exec_store`). It settles D-HALT: a RECOVERABLE drill HALT
  on its own id (one action class per detector), RESUME-eligible as DRILL. This is the HALT class's live
  producer→engine→watch-actor proof. The exec-store HALT writers (fee probe, `duplicate_fill`, `ambiguous_exit`) and the
  TERMINAL/INTEGRITY mirror stay **gate-proven** (RED→GREEN): a live injection would freeze the lineage or the venue.

## 4. Autonomy safety envelope

### 4.1 Allowed and forbidden

**The bot may, on its own:** mint SHADOW children of an allowlisted root; refit, evaluate and detect; write C1–C4; make
the C5 transitions; veto entries, demote or halt at any time; and promote, resume or roll back only under §4.2–§4.5.

**The bot never touches:** (1) the two caps (G18); (2) master enablement (`breezy-trade-supervisor.service:120-121`);
(3) the permit mechanism and its minting authority; (4) the NO-SEND firewall; (5) `allow_short=False`; (6) the code
allowlists, ceilings and sha pins; (7) the policy ruling; (8) unit files and their environment (Y21). Items 6–8 change
only through a reviewed commit or a ruling under `docs/evidence/`, never through the engine. Of all these, only the caps
are an operator decision.

### 4.2 Authorisation without a commit per promotion
- **One reviewed widening (L-12).** `live_orders_gate.py` gains a committed `_LINEAGE_POLICY_ALLOWLIST` of
  `(root_family_id, policy_ruling_id, policy_ruling_sha256)`; both allowlists are literal-only
  (`test_lineage_policy_allowlist_is_literal_only`). Each LAUNCH re-hashes the deploy copy under
  `deploy/families/rulings/` (as G4) and refuses on mismatch.
- **Manifest equality.** A child equals its committed root on **every** key except: `family_id`, `trial_id_prefix`,
  `d0_climate_day`, `density_artefact_path`, `density_artefact_sha256` and `live_orders_ruling` (which must name the
  policy ruling). That covers every size and price knob, `stations`, `taker_fee_coefficient`, `exit_rule`, `no_leg_exit`
  and the boundary artefact. Recalibration forms live in the artefact, bounded by the loader (G11). `exit_gate.py` (G17)
  stays code-only (`test_exit_gate_stays_code_only`).
- **Live-gate routing.** Only kinds in `LIVE_GATE_ROUTED_KINDS` can be CHAMPION, through both the resolver and the
  engine (`test_registry_champion_requires_live_orders_gate_for_every_kind`).
- **The policy ruling** pre-registers every threshold (WP-26 criteria 1–6 as the base), the C4 forward-shadow predicates
  and their units, α_total, K_LIFETIME, the `detector → action_class` map, the `RECOVERABLE_MODEL`, `RECOVERABLE_INFRA`
  and TERMINAL cause classes and their horizons, `attest_required_detectors`, the drawdown limit (producer AUT-5), rate
  limits, damping (§4.5), the accepted C4 `assumptions`, and the drill clause. It explicitly supersedes D11 for
  allowlisted lineages, as the parent ruling §3 permits.
- **Machine-readable block (Y22).** The ruling contains exactly one fenced block tagged `autonomy-policy/v1` (strict
  JSON, exact-set keys). It is inside the file, so the pinned `policy_ruling_sha256` covers it. The engine reads values
  only from this block in the sha-pinned copy. `test_policy_block_not_looser_than_code_ceilings` parses the deploy copy
  and rejects any value looser than a `pins.py` ceiling (§4.5) or any unknown key.
- **Forward-shadow feasibility (Y12).** The block's feasibility record: `n_min` (independent station-days), the measured
  replay-sufficient qualifying station-days per day and source, MDE at α_K, `n_min_eff` ≤ `n_cap` or the window-cap
  INCONCLUSIVE (C4), `eta_date`. `promote_enabled` (CHALLENGER→CHAMPION by PROMOTE) may be `true` only if `eta_date` is
  before the 2027-01-25 KILL (tested); else PROMOTE is **machinery-proven by the drill only** (§7). DRILL_ADMIT,
  DRILL_PROMOTE, ROLLBACK, RESUME and all restrictive transitions are unaffected.

### 4.3 Code identity pins (Y17)
- `persistence/autonomy/pins.py` holds literal-only sets: `ENGINE_SOURCE_SHA256` and
  `PRODUCER_SOURCE_SHA256[producer_id]`.
- Each pin is the sha256 over the sorted `(module_name, bytes)` of the **transitive `breezy.*` import closure** of that
  component's entry module, excluding `pins.py`. The gate test computes the closure from the import graph (grimp, the
  engine behind `lint-imports`), so an edit to any imported helper forces a reviewed pin update in the same commit.
- The engine and each producer compute their own closure hash at start, refuse to run if unpinned, and stamp it into
  every transition or verdict. The node checks the authorising row's `engine_code_sha` at LAUNCH.
- **Append-only (Z9).** A rotation adds the new sha and keeps the old ones, so historical rows still verify. Removing a
  pin is a revocation (rows it authorised stop resolving), done only by moving it to the literal `REVOKED_SOURCE_SHA256`
  in the same reviewed commit (`test_engine_pin_history_retained`).

### 4.4 Promotion preconditions and launch (Y15)
**Preconditions.** PROMOTE, DRILL_PROMOTE, SUPERSEDE, DISPLACED, ACTIVATE, RESUME and ROLLBACK all require: no OPEN or
AMBIGUOUS submit intent in the exec store (read-only, the G30 probe); an accepted `RECONCILIATION` PASS within its
horizon (venue net equals ledger per base slug, C2); and no INTEGRITY freeze on the venue. **Horizon (W8, P2-7, P5-10,
P7-9):** "produced after that day's STOP" binds **only** the 16:45Z pre-launch pass (ACTIVATE, a ROLLBACK pair with its
ACTIVATE, RESUME) and the LAUNCH re-check that reuses its verdict. The 15:30Z daily pass writes pending pairs on the
newest accepted **intraday** RECONCILIATION PASS within `ATTEST_VERDICT_VALIDITY_H`; the post-STOP verdict is required
at ACTIVATE, never at the pending write (`test_pending_write_uses_intraday_reconciliation`). **RESUME is written only by
the 16:45Z pass** (AUT-7 K6): the intraday pass is restrictive-only and the daily pass never resumes, so no intraday
RESUME horizon exists (`test_resume_written_only_at_prelaunch`). Flatness is **not** required: a demoted or superseded
family holds its positions to settlement (FQ has no exit, G17; autonomy never widens the exit allowlist), and the
successor is protected by `rung_net_position_held` (C5).

**Post-STOP reconciliation (W8).** `breezy-autonomy-reconcile-poststop` (oneshot, 16:41Z, its own lock, `flock -w` W
plus `TimeoutStartSec` with W + `TimeoutStartSec` ≤ `POST_STOP_RECONCILE_RUNTIME_S`, G32, so it ends by 16:43Z) produces
the day's sender-change RECONCILIATION verdict with the node down. It proceeds only after the supervisor's journaled
STOP completion for the day (AUT-5 names the signal) and reads the exec store through the G6 read-only URI. Venue net
comes from the newest venue position snapshot timestamped at or after the last durable fill's `ts_event` (source
**INFERRED**, AUT-2 names it; a new venue read is a reviewed egress change, never a NO-SEND relaxation). No STOP signal,
a stale snapshot or an overrun gives `INCONCLUSIVE`, so the 16:45Z pass writes SWAP_CANCEL
(`test_prelaunch_requires_post_stop_reconciliation`). It also records `open_intent_at_poststop` in its metrics: AUT-2's
Z19 measurement, with no supervisor log line (P2-4); the node is down from 16:40Z, so the state at 16:41Z equals
16:45Z's.

**Re-check at launch without a deadlock.**
- The **pre-launch engine pass** (16:45Z, after STOP, when no node runs) re-runs the preconditions for any pair pending
  for today's LAUNCH. Pass → `ACTIVATE`; fail → `SWAP_CANCEL`. A pair with neither lapses at LAUNCH (C5 fold), so a dead
  engine also leaves the incumbent in place. It may also write a ROLLBACK pair **with** its ACTIVATE in one transaction,
  so a trigger accepted before 16:45Z takes effect at that LAUNCH (P7-4;
  `test_prelaunch_writes_rollback_and_activate_atomically`).
- The daily pass (15:30Z, node up) checks open intents **advisorily** through the G6 read-only URI, because
  `probe_open_intent` asserts no live node (G30); the 16:45Z pass and the LAUNCH re-check are authoritative (P7-6).
- The supervisor re-runs the same read-only checks at LAUNCH. If they fail while an ACTIVATE stands, it raises CRITICAL,
  launches nothing and journals `launch_precheck_failed` (AUT-5 names the signal); it makes **no `systemctl` call**
  (P5-5). The intraday timer guarantees two passes in [16:50Z, 17:00Z) (16:52:30, 16:57:30;
  `test_two_intraday_passes_inside_launch_window`); the first to see the signal writes the `SWAP_CANCEL` that voids the
  pair retroactively (Z8), and the supervisor's resolve retry launches the restored incumbent before 17:00Z. If neither
  commits, no sender runs that day (fail-closed) and the cause takes the DEMOTE path.
- Preconditions gate **only a change of sender**, never the incumbent's own boot: an incumbent with an AMBIGUOUS intent
  boots through today's path unchanged (G30; `reconcile_at_startup`), so no new launch-deadlock surface. Tests
  `test_promotion_requires_reconciled_state` (net equals ledger, non-flat allowed);
  `test_ambiguous_intent_cancels_swap_not_incumbent_launch`.

### 4.5 Damping and code ceilings (Y13, Y18, Y21)
All ceilings are literal constants in `pins.py`, changed only by a reviewed commit. The policy block may be stricter,
never looser (Y22 test).

| Constant | Ceiling |
|---|---|
| `RESUME_COOLDOWN_H` | ≥ 24 |
| `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` | ≤ 2 RECOVERABLE_MODEL resumes, then the cause becomes TERMINAL |
| `MAX_INFRA_RESUMES_PER_VENUE_7D` (Z10) | ≤ 3, then HALTED/INTEGRITY with a CRITICAL, never RETIRE |
| `MAX_ROLLBACKS_PER_VENUE_30D` | ≤ 2, then a rollback trigger HALTs as `ROLLBACK_FAILED` (non-freezing; C5) |
| `ROLLBACK_MIN_DWELL_H` (P7-7) | ≥ 24: a ROLLBACK takes effect only ≥ 24 h after the venue's previous sender change or RESUME took effect (effective instant to effective instant; a ROLLBACK's is its LAUNCH); it delays, never refuses; drill ROLLBACKs included |
| `ROLLBACK_TARGET_MAX_AGE_D` (P7-7) | ≤ 30: a target that left CHAMPION longer ago is ineligible |
| `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` (P7-7) | ≥ 0.5 (a floor; the policy may only raise it): a drill starts only if the newest accepted drawdown verdict, drill fills included, shows `drawdown_used_frac` ≤ 1 − value; a risk value, never an operator cap |
| `RELAUNCH_REQUEST_TTL_S` (P5-11) | = 120 (≥ 2 × the 60 s schedule poll, G40) |
| `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` (Z3) | ≤ 2 logical changes (counting rule below) |
| `MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE` (M) | ≥ 14 |
| `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` (K_LIFETIME, Rev 6 K_max; P4-5, ALPHA); `MAX_NOMINATIONS_PER_FORWARD_WINDOW` | ≤ 4 α-charging nominations over the lifetime; ≤ 1 per forward window (C4) |
| `BOOTSTRAP_B_MAX` (ALPHA 2) | literal draw cap; exact or analytic tail beyond |
| `BOOTSTRAP_SEED`; `DEMAND_WRITER_PRODUCER_IDS`; `DEFAULT_RESTRICTIVE_CLASS` (P5-2, P6-12, P4-10) | literal genesis ids; literal producer ids (restrictive demand only); literal detector → DEMOTE\|HALT map for the no-policy fallback |
| `MAX_MINTS_PER_LINEAGE_PER_DAY` | ≤ 1 |
| `DRILL_BUDGET_PER_VENUE_30D` | ≤ 1 drill (one DRILL_PROMOTE, one `DRILL_INJECT` DEMOTE and its DRILL RESUME, one `DRILL_INJECT_HALT`, one DRILL rollback); separate from production counters |
| `DEADMAN_HORIZON_H` (H) | ≤ 30 (24 h engine period + 6 h slack) |
| `MAX_VERDICT_VALIDITY_H` (Z4) | ≤ 26 (24 h + 2 h slack); the engine rejects longer verdicts as `ERROR` |
| `ATTEST_PERIOD_H`; `ATTEST_VERDICT_VALIDITY_H`; `ATTEST_MARGIN_H` (W1) | ≤ 6; ≤ 8; ≥ 0.5. **Invariant (gate-tested):** `ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H ≤ ATTEST_VERDICT_VALIDITY_H`, with `L_max` = `INTRADAY_ATTEST_VERDICT_PERIOD_MIN` (≤ 60) + the 150 s engine offset: 6 + 1.04 + 0.5 ≤ 8, so a newly cited verdict outlives the next ATTEST by ≥ 0.46 h (≈ 5 retried passes) |
| `forward_window_days` bounds (W7) | 28 ≤ value ≤ 120 (shorter would spend α faster; longer delays verdicts past the KILL) |
| `POST_STOP_RECONCILE_RUNTIME_S` (W8) | ≤ 120 |
| `ALERT_DELIVERY_TIMEOUT_S`; `ALERT_OUTBOX_MAX` (W9) | ≤ 10; ≤ 256 |
| `CANARY_RETRY_PERIOD_MIN` (W13) | ≤ 60 |
| `ENGINE_HEARTBEAT_STALE_S` (Z4) | ≤ 3600 |
| `WATCH_TICK_STALE_S` (Z6) | ≤ 180 (3 × 60 s tick) |
| `ALERT_CANARY_MAX_AGE_H` (Z13) | ≤ 26 |
| `DEMAND_FILE_MAX_BYTES`; `DEMAND_FILES_MAX` (Z11) | ≤ 4096; ≤ 64 per venue |
| `SELF_HEAL_RESTARTABLE_UNITS` | literal tuple of unit names; never the supervisor, the trade node or the engine; `try-restart` only (G40, P1-10), no unit-file or env edits |
| `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` (Z15, W11) | ≤ 3, then alert only; counted per **trading day** [16:45Z, next 16:45Z), so an overnight exhaustion resets before LAUNCH (P1-12), from write-once records in `evidence/selfheal/<trading_date>/` (the UTC date of the window's 16:45Z start) |

**Counting (Z3).** One logical change of sender (the →CHAMPION row, its SUPERSEDE or DISPLACED partner and its ACTIVATE)
counts 1; a RESUME counts 1. MINT, SHADOW→CHALLENGER, ATTEST, HWM_RESET and restrictive rows never count. Drill-episode
rows (DRILL_ADMIT, the DRILL_PROMOTE pair, the episode's RESUME, HALT and ROLLBACK) count only against the drill budget.
Every counter (daily cap, M, rollbacks, resumes, drill budget) is charged when the change **takes effect**; the engine
treats pending pairs as reservations when it proposes, and a lapsed or cancelled pair is never charged.

Never a rollback to a `demoted_for_cause` family. Tests: `test_damping_ceilings` (pins the counting rule),
`test_attest_cadence_has_no_expiry_gap` (over the schedule table under a fake clock, 48 h: no instant past the newest
ATTEST's `attest_valid_until_ns` while producers pass), `test_self_heal_unit_allowlist_is_literal_and_excludes_trade`
(AST: the restart call site takes only members of the tuple, as an argv list
`["systemctl", "--user", "try-restart", unit]`, never `shell=True`, within the per-unit daily count; the tuple contains
no `breezy-trade*` or `breezy-autonomy-engine*` name; no autonomy module writes under `~/.config/systemd` or
`~/.config/breezy`). **Self-heal counter (W11, L-50):** one write-once record per restart,
`evidence/selfheal/<trading_date>/<ts_ns>_<unit>.json`, counted before every restart; an unreadable directory means no
restart and an alert (`test_self_heal_cap_survives_process_restart`, `test_restart_window_resets_before_launch`).

### 4.6 External watch and delivery proof (Y3, Y11)
- **Dead-man (owner AUT-5; P6-5).** `breezy-autonomy-deadman.timer` (every 30 min), its own unit and lock, reads the
  engine heartbeat, AUT-6's health heartbeat `evidence/unit_health/heartbeat.json` (P6-13) and the per-venue chain-head
  age, and raises CRITICAL past `ENGINE_HEARTBEAT_STALE_S`, past H, and on a health heartbeat older than 1800 s. The
  node enforces the same horizon independently (`registry_chain_stale`, `registry_attest_expired`). AUT-6 supplies its
  CRITICAL path (`deliver_with_proof`), unit-health coverage of it and the off-host canary; it builds no second
  dead-man.
- **Action executors (P6-7).** ENTRY_VETO: `RegistryWatchActor` (AUT-5). DEMOTE, HALT: the intraday engine pass (AUT-5).
  SELF_HEAL: AUT-6's `breezy-autonomy-health` oneshot (a C4 producer pinned as `aut6.health`, P6-13), the **only**
  autonomy caller of the restart site (AUT-1 supplies recorder and feed observations and names their units). ALERT: the
  producing unit, through `deliver_with_proof` (CRITICAL) or `emit_alert`. Until the policy ruling is filed the health
  unit is alert-only, so SELF_HEAL live clocks start at filing.
- **Delivery-proof API (AUT-6).** `deliver_with_proof(sink, payload) -> DeliveryProof` in `runtime/alert_delivery.py`.
  It calls `emit` **directly on the webhook branch** (via `TeeAlertSink.sinks`), never through `emit_alert` or the tee,
  because both swallow failure (G25). Proof is an HTTP 2xx (`WebhookAlertSink.emit` raises otherwise). Each attempt
  writes one write-once record `evidence/alerts/<date>/<ts_ns>_<writer>_<d|f>.json` (`event`, `ts_ns`, `delivered`,
  `status_class`; no URL, no exception message); node worker, engine, producers and dead-man never share a file (L-50,
  P6-6). It uses the existing `alerts.env` key only (G27); no new egress host. **Every CRITICAL** (Z13), from autonomy
  writers and from the existing node CRITICAL sites that AUT-6 migrates and lists, goes through it; WARNING and INFO
  keep `emit_alert`. The node-local `alerts_undeliverable` veto (C5) reads these records.
- **Off the trading loop (W9).** In the node, `deliver_with_proof` never runs on the event loop: CRITICAL sites enqueue
  into a bounded outbox (`ALERT_OUTBOX_MAX`) drained by one dedicated worker thread that touches no exec-store state,
  each attempt under a hard `ALERT_DELIVERY_TIMEOUT_S`. Enqueue never blocks; an overflow writes a `delivered=false`,
  `status_class=outbox_overflow` record instead of waiting (`test_try_submit_latency_independent_of_webhook_latency`).
- **Off-host heartbeat.** A daily 15:45Z `autonomy_canary` goes through `deliver_with_proof` to the same endpoint, whose
  absence rule pages if none arrives by 16:15Z (dead host or broken egress). Receiver support is **INFERRED**; AUT-6
  proves it live by suppressing one canary. Otherwise a new heartbeat endpoint is a reviewed alert-egress change
  re-pinning `test_autonomy_alert_egress_not_widened`.
- A failed delivery of a CRITICAL is retried on the next tick; a failed canary is retried every
  `CANARY_RETRY_PERIOD_MIN` until delivered (W13), each attempt recorded, and a `DeliveryProof` failure on the canary is
  itself a `HEALTH` FAIL.

### 4.7 Envelope tests (RED first, in the gate)

**Existing tests, unweakened:** `test_operator_control_assignment_scan`, `test_execution_egress_firewall_guard`,
`test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`,
`test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`.

| New test | Pins |
|---|---|
| `test_autonomy_never_reads_or_writes_operator_controls`; `test_autonomy_never_touches_enablement_permit_or_firewall`; `test_autonomy_never_imports_order_path`; `test_autonomy_alert_egress_not_widened` | AST scan, tokens from `OPERATOR_RESERVED_CONTROL_ENV_VARS`; §4.1 |
| `test_registry_transition_table_is_exact`; `test_registry_cas_and_idempotent_replay`; `test_registry_hash_chain_and_triggers`; `test_repeat_supersede_same_family_is_not_replay`; `test_registry_readonly_open_engine_stopped`; `test_resolver_binds_bytes_to_row`; `test_verdict_subject_sha_must_match_row` | C5 table, Y9, Y20; Y5, Y6 |
| `test_hand_relaunch_without_registry_source_refused`; `test_family_source_fixed_in_unit`; `test_terminal_halt_freezes_lineage`; `test_demote_during_pending_swap_incoming`; `…_outgoing`; `test_resume_refused_while_swap_pending`; `test_unactivated_pair_lapses_at_launch` | Y7, Y10; Y8 |
| `test_watch_actor_never_reads_projection`; `test_registry_hwm_refuses_regression`; `test_registry_unreadable_veto_clears_only_after_verified_read`; `test_attest_expiry_and_chain_staleness_veto_entries`; `test_demotion_latency_slo`; `test_intraday_engine_is_restrictive_only`; `test_transient_veto_writes_no_transition`; `test_restrictive_commit_failure_sets_node_veto` | Y4, Y3; Y1, Y19 |
| `test_drill_promote_refuses_non_champion_sha`; `test_drill_inject_mapped_only_in_clause`; `test_drill_fills_excluded_from_n_and_kill_clock`; `test_drill_budget_separate`; `test_rung_net_position_veto_crosses_legs_and_families`; `test_code_identity_pins_cover_import_closure`; `test_lineage_policy_allowlist_is_literal_only` | Y2; Y16, Y17, §4.2 |
| `test_policy_block_not_looser_than_code_ceilings`; `test_promote_disabled_when_eta_after_kill`; `test_damping_ceilings`; `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` | Y22, Y12; Y18, Y21 |
| `test_candidate_cap_and_mint_rate`; `test_deliver_with_proof_reports_non_2xx_through_tee`; `test_promotion_requires_reconciled_state`; `test_ambiguous_intent_cancels_swap_not_incumbent_launch` | Y13, Y11; Y15 |
| `test_child_manifest_equals_committed_root_except_allowlist`; `test_exit_gate_stays_code_only`; `test_registry_paths_refuse_symlinks`; `test_verify_and_load_share_bytes`; `test_registry_unavailable_mints_no_permit`; `test_swap_cannot_exceed_daily_budget_across_namespaces` | §4.2, single read; C5 failure, G21 |
| `test_verdict_acceptance_rules`; `test_halt_reason_class_map_is_exact`; `test_mirror_read_failure_is_integrity`; `test_autonomy_payload_hygiene_scan`; `test_verdict_accepted_after_attest`; `test_family_artefact_binding_immutable`; `test_attest_veto_armed_after_first_attest`; `test_engine_heartbeat_stale_vetoes`; `test_verdict_validity_ceiling` | C4, mirror, hygiene; Z1, Z4, Z5 |
| `test_drill_flag_spans_promote_to_rollback`; `test_drill_admit_charges_only_drill_budget`; `test_drill_inject_passes_when_marker_absent`; `test_entry_veto_closed_before_first_tick_and_on_stale_tick`; `test_watch_actor_store_touches_stay_on_loop_thread`; `test_autonomy_exec_keys_disjoint_from_halt_prefixes` | Z2; Z6, Z16 |
| `test_node_relaunch_rule_family_id_and_seq_prefix`; `test_halted_family_boots_entries_vetoed_exits_live`; `test_post_launch_swap_cancel_restores_incumbent`; `test_engine_pin_history_retained`; `test_infra_cause_never_retires`; `test_bad_demand_file_vetoes_venue`; `test_hwm_reset_cli_journals_alerts_and_chains` | Z7, Z8; Z9, Z10, Z11, Z17 |
| `test_critical_alerts_use_delivery_proof`; `test_alerts_undeliverable_veto`; `test_reconciliation_and_entry_guard_never_read_canary_store`; `test_drill_fills_spend_venue_budget`; `test_demotion_never_requires_policy_and_is_immediate`; `test_registry_veto_leaves_exit_seam_open`; `test_family_plugin_exact_set`; `test_rollback_restores_byte_identical_artefact` | Z13, Z14, Z18; Entry-only demotion, C6, AUT-7 |
| `test_attest_cadence_has_no_expiry_gap`; `test_prelaunch_requires_post_stop_reconciliation`; `test_nomination_refused_past_k_max_lifetime`; `test_drill_resume_never_charges_model_budget`; `test_drill_refused_over_halted_incumbent`; `test_drill_rollback_to_superseded_incumbent_admitted`; `test_detectors_and_drawdown_include_drill_fills` | W1, W8, W7; W2, W3, W12 |
| `test_hwm_reset_cannot_unhalt`; `test_hwm_reset_never_refunds_counters`; `test_resolver_resolves_after_hwm_reset`; `test_resume_clears_registry_halted_without_relaunch`; `test_entry_guard_exact_key_reads_only`; `test_entry_guard_cache_invalidated_on_fill`; `test_entry_guard_unreadable_index_vetoes`; `test_compose_refuses_without_entry_veto_slot`; lint-imports contract `persistence.autonomy ↛ adapters` | W4, W5; W6, W10 |
| `test_try_submit_latency_independent_of_webhook_latency`; `test_self_heal_cap_survives_process_restart`; `test_alerts_undeliverable_reads_two_days`; `test_voided_pair_fills_excluded_from_all_n`; `test_retired_demand_file_archived` | W9, W11, W13, W14, W16 |
| `test_p_at_decision_is_bought_leg_probability`; `test_differing_body_same_id_refused`; `test_two_pending_nominees_get_distinct_k`; `test_window_cap_below_n_min_is_inconclusive`; `test_infeasible_nomination_charges_no_alpha`; `test_no_policy_fail_demotes_never_widens`; `test_every_live_verdict_journaled_once_per_daily_pass`; `test_cause_verdict_ids_subset_of_acted_rows`; `test_bootstrap_seed_genesis_only`; `test_child_env_touches_only_registry_keys`; `test_registry_shadow_logs_agreement_and_spawns_env_family`; `test_shadow_never_vetoes_or_arms_hand_relaunch_rule`; `test_two_intraday_passes_inside_launch_window`; `test_producer_demand_write_is_restrictive_only`; `test_retired_kind_keeps_scorer_until_last_fill_labelled`; `test_attest_requires_every_listed_detector`; `test_drawdown_producer_handshake_with_labels` | Rev 7: P3-9, P4-11, P4-8, ALPHA, P4-10, P4-9, P5-2, P5-3, P5-7, P5-5, P6-12, P2-6, P4-7, P5-6 |
| `test_autonomy_files_have_one_writer`; `test_scorer_never_attributes_by_trial_id_prefix`; `test_own_outcome_effect_not_vacuous`; `test_alpha_index_never_resets`; `test_mint_unlimited_by_k_max_but_one_per_day`; `test_root_resolves_under_live_orders_allowlist`; `test_rollback_to_root_reads_content_addressed_copy`; `test_failed_rollback_halts_champion`; `test_prelaunch_writes_rollback_and_activate_atomically`; `test_drill_halt_never_freezes_or_writes_exec_store` | P1-6, P2-5, P3-4, P4-5, P7-1, P7-5, P7-3, P7-4, P6-4 |
| `test_every_exit_fill_joins`; `test_capture_untagged_is_a_veto_reason`; `test_restart_window_resets_before_launch`; `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`; `test_no_unit_overlaps_launch_window`; `test_launch_path_units_end_before_next_fixed_point`; `test_pending_write_uses_intraday_reconciliation`; `test_resume_written_only_at_prelaunch`; `test_request_ttl_covers_two_schedule_polls`; `test_node_loads_artefact_from_store_by_row_sha`; `test_rollback_fee_check_uses_verdict_not_node_memory`; `test_rollback_failed_never_freezes_venue`; `test_target_byte_mismatch_ineligible_without_freeze`; `test_champion_own_artefact_mismatch_at_load_is_integrity`; `test_rollback_dwell_age_and_drill_headroom_ceilings` | Rev 8: P1-8, P1-9, P1-12, P1-11/P5-9, window sweep, P5-10, P7-9, P5-11, P7-10, P7-11, ROLLBACK-FAILURE, P7-7 |

## 5. Area boundaries, sequencing and live proof

| Area | Owns | Writes |
|---|---|---|
| AUT-1 | `CaptureAdapter` per kind, the `decision_id` tag, link and lifecycle writers, `DetectorEvent`, the payload store, the settlement writer, the completeness audit, recorder and feed stall observations (AUT-6 restarts) | C1; C4 `HEALTH` |
| AUT-2 | `Scorer` per kind; the label store; net-position reconciliation; the −0.37/+0.37 root cause; tallies and the `portfolio-roi` scorer (P6-9) | C2; C4 `RECONCILIATION`, `HEALTH label_lag` (P2-3) |
| AUT-3 | `Refitter` per kind; refit timers; the C3 writer; leakage, ablation and reproducibility checks; the G11 widening | C3 |
| AUT-4 | `Evaluator` per kind: offline screening, forward shadow, live sequential; nomination and α accounting (`k_life`, window cap); feasibility measurement; moving the G36 statistics into `src/breezy/analysis/stats/` (P4-4) | C4 |
| AUT-5 | The C5 store, chain, fold and resolver; the engine (daily, intraday, pre-launch); the policy ruling and block; `RegistryWatchActor` and `entry_guard`; supervisor and node wiring; the allowlist widening; pins; the dead-man (P6-5); bootstrap and the C3 root copy; the drawdown producer (P5-6) | C5; C4 `DRIFT` (drawdown) |
| AUT-6 | `DriftDetectors` per kind (node-local and verdict); the intraday producer; liveness; unit health and the six failing units; `deliver_with_proof`, canary and off-host heartbeat; the SELF_HEAL and ALERT executors (P6-7); `TimeoutStartSec` on every oneshot unit (G32); the `fee_schedule` DRIFT verdict (P7-11); unit exit semantics, `portfolio-roi`'s included (P6-9); the INTEGRITY-floor demand write (P6-12) | C4 `DRIFT`, `HEALTH`; `demand/v1` (restrictive) |
| AUT-7 | Rollback-target selection and ROLLBACK through the C5 API; the failed-rollback HALT (`ROLLBACK_FAILED`, P7-3) and target-integrity ineligibility; the gate drill (AUT-7a); the live drill (AUT-7b) | C5 through the engine |

### 5.1 Build sequence
- **Wave 0 (ARCH-0, serial).** `persistence/autonomy/`: schemas, the C5 store (chain, triggers, CAS, fold, rollback
  journal), the resolver, `entry_guard`, `pins.py` with ceilings, the C6 Protocols and `RefusingPlugin`. All §4.7 tests
  start RED. `lint-imports` must report "N kept, 0 broken" (console script, run from the tree). Size M, independent
  review. The C4.1 holdout ruling is filed alongside, before any AUT-3 fit or AUT-4 screen.
- **Wave 1 (parallel, against the stubs only):** AUT-1a (offline: audit, payload store, settlement writer,
  `CaptureAdapter` per kind); AUT-4a (the G36 move: functions moved byte-identically, scripts kept as thin CLI wrappers,
  a test pinning the moved source); AUT-6; AUT-5a (store wiring, watch actor, resolver at LAUNCH, bootstrap, intraday
  engine (restrictive plus ATTEST) and heartbeat, dead-man, relaunch helper); AUT-7a; AUT-2a (FQ scorer over the exec
  store, the root cause, the intraday and post-STOP RECONCILIATION producers). `app/trade.py`, `settings.py` and
  `trade_supervisor*.py` belong to AUT-5a alone; **AUT-1b** (the `app/trade.py` wiring and the
  `try_submit`/`submit_order` capture hooks) starts after AUT-5a merges (P1-7).
  - **Bootstrap of the dead-engine vetoes (Z5).** Until a family's first ATTEST row, `registry_attest_expired` is
    unarmed for it and `registry_chain_stale` bounds it (`test_attest_veto_armed_after_first_attest`).
    `alerts_undeliverable` is enabled only after AUT-6's canary has written its first `delivered=true` record, because
    absent records veto.
- **Wave 2:** AUT-2b (`decision_id` join, NO-leg and exit labels); AUT-3 (external refits may start in Wave 1;
  `rung_recalibration` follows C2); AUT-4 live sequential.
- **Wave 3:** AUT-4 offline and forward shadow with the feasibility record; AUT-5b (policy ruling peer-reviewed and
  filed, allowlist widening, then DRILL_ADMIT/DRILL_PROMOTE, RESUME, ROLLBACK, and PROMOTE only if `promote_enabled`);
  AUT-7b.
- **Gate discipline:** full gate after every merge (L-43), `scripts/ci/run_tests_no_egress.sh`, exact interpreter, never
  `uv` (L-51).

### 5.2 Scheduling rules (Y23)
- **Locks.** Studies (label, detectors, refit, rerun, evaluation) take `breezy-studies.lock` (`flock -w <W>`) in
  `breezy-studies.slice` with `OnFailure=breezy-study-failed@` and a no-progress stall event. Engine (all modes),
  intraday producer and dead-man take their own locks, never the studies flock, so a long study never delays a demotion.
- **Runtime bound (G32; P6-2, P1-11, P5-9).** Every `Type=oneshot` unit, autonomy or existing (AUT-6 converts the
  studies), uses `TimeoutStartSec`, never `RuntimeMaxSec` (a no-op there); `Type=notify` units (AUT-3 refit) add
  `RuntimeMaxSec` and `WatchdogSec` (`test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`). No `.path`
  triggers (blind to nested verdict writes); staggered timers only (Z12, P6-8).
- **Launch window (P6-3).** Outside the table below, no unit's [start, start + `W` + `TimeoutStartSec` (+
  `RuntimeMaxSec`)] meets [16:30Z, 17:10Z) for any firing or retry (`test_no_unit_overlaps_launch_window`); a canary
  retry or SELF_HEAL restart that would is deferred to 17:10Z and journaled; the daily engine pass (15:30Z, `-w` ≤ 120
  s, ≤ 900 s) ends ≤ 15:47Z. The **launch-path units** are the STOP/LAUNCH machinery and alone run inside, each ending
  before its next fixed point (`test_launch_path_units_end_before_next_fixed_point`); an intraday engine pass timing out
  on the lock writes restrictive-demand files for its accepted FAILs (C5) and exits 0:

| Unit (lock) | Starts in the window | `flock -w` | `TimeoutStartSec` | Ends by | Before |
|---|---|---|---|---|---|
| Intraday RECONCILIATION producer (AUT-2, reconcile lock) | 16:35, 17:05 | ≤ 30 s | ≤ 240 s | 16:39:30 | STOP 16:40; post-STOP (same lock) |
| Post-STOP reconcile (reconcile lock) | 16:41 | ≤ 20 s | W + T ≤ 120 s | 16:43 | pre-launch 16:45 |
| Pre-launch engine pass (engine lock) | 16:45 | ≤ 60 s | ≤ 180 s | 16:49 | LAUNCH 16:50 |
| Intraday producer (own lock) | every 5 min (:00) | ≤ 10 s | ≤ 120 s | start + 130 s | its engine pass (+150 s) |
| Intraday engine pass (engine lock) | every 5 min (+150 s): 16:52:30, 16:57:30 | ≤ 20 s | ≤ 120 s | start + 140 s (16:59:50) | next producer; 17:00Z close |
| Dead-man; `aut6.health` (own locks) | 16:30, 17:00; per AUT-6 | ≤ 10 s | ≤ 60 s; ≤ 120 s | before the next run | read-only; restarts deferred |

- **Memory.** On the 30 GiB host (G29): one studies-flock holder at a time, `MemoryMax ≤ 16G`; own-lock autonomy units
  together ≤ 4G; ≥ 10G left for trade node, recorder and OS. A study needing more runs outside the live window and stops
  for the node, never the reverse. "Heavy" (> 4G) jobs never start 01:00–04:30Z (`WORK_BREAKDOWN:512`). The arithmetic
  uses each unit's **effective** `MemoryMax`, drop-ins included; uncommitted host drop-ins (14G, found 10-03) are
  committed through review or removed, and AUT-6's daily `HEALTH` verdict compares effective limits with this budget
  (P6-10).
- Indicative slots (AUT-n plans fix the rows): label 14:15 (primary) and 05:00 (catch-up; P2-2), offline detectors
  05:30, refit 06:00 (16G), reproducibility rerun on a 10% sample 09:30 (12G), offline and forward shadow 11:00 (12G),
  live sequential 14:45, daily engine 15:30 (writes pending pairs), canary 15:45 (retry ≤ hourly on failure), post-STOP
  reconciliation 16:41Z (≤ 120 s, own lock, not a study), pre-launch pass 16:45, intraday producer every 5 min (intraday
  HEALTH and RECONCILIATION verdicts at least hourly) with the intraday engine 150 s after it (Z12; ATTEST every
  `ATTEST_PERIOD_H`, W1), dead-man every 30 min.

### 5.3 Live-proof evidence rules
- **Qualifying days.** A day counts toward any 7-day window only with at least 1 real fill, or a `source=canary`
  synthetic fill traversing the production capture and label code. Zero-fill days extend the window. Every window also
  needs **at least 5 real fills**; canary and drill fills never count toward that, any n, any live-sequential look or
  the KILL clock; drill fills still feed the DRIFT detectors, the drawdown limit and the venue budget (C2, W12; P6-11).
- **Canary store (Z14).** Canary fills live in `derived/canary/`, never the exec store, with their own `Scorer` input;
  reconciliation and `entry_guard` never read it (`test_reconciliation_and_entry_guard_never_read_canary_store`).
- **Honest evidence class.** Each DONE claim states "machinery proven, edge unproven" unless a pre-registered edge
  verdict passed.
- **AUT-7b drill contract (Y2).** The drill runs through the production engine under the policy's pinned drill clause
  and proves DRILL_ADMIT, DRILL_PROMOTE, DEMOTE (through `DRILL_INJECT` and the live producer→engine→watch-actor path),
  RESUME, HALT (through `DRILL_INJECT_HALT`) and ROLLBACK (displacing the halted child) with the sha re-verified, using
  a byte-identical child (C3 no-new-lineage rule). That one sequence is AUT-5's live PROMOTE/DEMOTE/RESUME proof and
  AUT-6's DEMOTE and HALT class proof (P6-4). It spends only the drill budget; its fills, from DRILL_PROMOTE through the
  closing ROLLBACK, carry `drill=true` and are excluded from live-sequential n and the KILL clock, but feed the
  detectors and the drawdown limit and spend the venue daily budget (Z18, W12). The permit may be live or withheld, and
  its authority is untouched. Clock: 5–6 trading days (`RESUME_COOLDOWN_H` ≥ 24, RESUME only at the 16:45Z pass,
  `ROLLBACK_MIN_DWELL_H` ≥ 24; P5-8, P7-7). Steps and timing: §10.
- **After the 2027-01-25 KILL.** If it fires TERMINAL, the champion RETIREs, the lineage is `terminal_frozen`, and the
  venue has no sender until a reviewed commit adds a lineage root. Capture, labels, refits and evaluation continue;
  fill-dependent windows pause and extend.

## 6. Reuse map (extend these, never rebuild them)

| Need | Reuse | Where |
|---|---|---|
| Manifest strictness, raw-byte sha; Real-order authorisation | `load_family_manifest` (widen containment only); `live_orders_authorized` (add the lineage allowlist) | `family_manifest.py:285-296`; `live_orders_gate.py:130-190` |
| Integrity halt; read-only reader; Entry guard slot | `record_*`, `family_halt_state`, `read_family_halt_rows_readonly`; `try_submit` (add `entry_veto` beside `submit_veto`) | `trial_day_latch.py:1004,1118,1155,1193,354`; `fq/strategy.py:629-643` |
| In-node periodic actor; Order tags; order→fill join; position guard (W6) | `FeeDriftProbeActor` pattern; exit tag prefixes; `FILL_*` and `fill_index/` exact keys | `app/trade.py:442-484`; `exit_tags.py`; `exec/client.py:400-447` |
| Open-intent probe; Decision JSONL and retention | `probe_open_intent`; `decisions/`, `OfferTape`, funnel actor | `trade_supervisor.py:402`; `crh/composition.py:568-602` |
| Label store and scoring; Bootstrap, sequential looks | `scored_trial_store`; `ScoredTrial`, `ScoreRefusal`; `roi_bound` constants; `run_sequential_looks` | `scored_trial_store.py:24-31`; `trial_scorer.py:131-160`; `roi_bound.py:93-100`; `family_tally_v2.py:625` |
| Promotion predicates; Fitters and holdout | `evaluate_c_*`, `assemble_outcome`; `fit_calibration`, `open_holdout`, `compute_n_min`, `write_artefact` | `promotion_criteria.py:195-613`; `nbp_calibration.py:1280,353,309,2643` |
| Market baseline; calibration leg; Drift and freshness | `wp7b_market_as_forecaster`; `evaluate_calibration_leg`; `check_freshness`, `check_drift` | `scripts/analysis/…:1128`; `forecast_conditional_scoring.py:392`; `nbp_learning_nightly.py:286,342` |
| Alerts; delivery proof | `resolve_alert_sink`, `emit_alert`, `AlertPayload`; the `check_alerts_cli` direct-emit pattern on the webhook branch | `health.py:392,479,362`; `check_alerts_cli.py:19-23` |

## 7. Risks

| Risk | Mitigation built into the contracts |
|---|---|
| **Statistical capacity.** About 5 fills a day, admissible n = 0; a child restarts its clock (L-34). | Promotion rests on offline evidence plus a forward shadow counted in independent station-days, never on a child's live n. Live sequential demotes. |
| **Forward shadow may be unreachable before the KILL (Y12).** AUT-4 r1 measured 80/80 closed station-days replay-sufficient (≈ 3.64 a day; P4-3), so `n_min` against the KILL binds, not tape. | The feasibility record gates `promote_enabled`. If `eta_date` ≥ 2027-01-25, **PROMOTE is machinery-proven by the drill only**: the AUT-5 live proof stands on DRILL_PROMOTE, and no edge-based promotion is claimed. |
| **Slippage proxy** | Champion slippage for a different policy is a declared assumption; without the ruling's acceptance the verdict is INCONCLUSIVE. |
| **Forecast edge closed (09-20).** | Promotion requires beating the market-implied baseline on the traded rung, net of fee and slippage. |
| **Multiple testing under daily refit (Y13)** | Screening without α; confirmation on fresh forward days; frozen holdout used once (C4.1); lifetime α_k halving (Σα ≤ α_total); K_LIFETIME, per-window and mint-rate ceilings; window-cap INCONCLUSIVE; MDE at α_K stated. |
| **Train/serve skew; leakage** | `forecast_input_sha256` per decision; a parity verdict maps to DEMOTE; C3 assertions refuse a lineage write. |
| **Demotion latency (Y1, Z12)** | Node-local vetoes ≤ 2 min; verdict-driven ≤ 15 min; a dead engine is bounded by the heartbeat veto (~1 h), H the backstop. |
| **Halt strands positions** | Entry-only demotion; the exec-store halt is reserved for INTEGRITY and TERMINAL; a demoted family holds to settlement. |
| **Registry tamper, revert or SPOF** | Per-venue chain, triggers, export, node HWM, byte binding, pins; any failure gives no sender, never a fallback. |
| **Alerts reach nobody** | Delivery proof by 2xx; off-host absence rule on the canary. |
| **Oscillation; drill contamination** | §4.5 ceilings and counting rule; separate drill budget; drill fills excluded. |
| **Promotion starvation (Z19).** An AMBIGUOUS intent open at 16:45Z cancels the day's swap (§4.4). | AUT-2 measures how often one is open at 16:45Z; a high rate is a finding for the AMBIGUOUS-resolution path, never a relaxation of §4.4. |
| **False-positive DRIFT (Z20).** A spurious `RECOVERABLE_MODEL` DEMOTE can exhaust the resume budget and freeze a lineage. | **Accepted cost**: fail-closed over availability. Recovery is a reviewed new lineage root. |
| **Rollback failure (P7-8)** | `ROLLBACK_FAILED` halts one family and never freezes; daily retry; a corrupt target is skipped, never loaded; only the champion's own bytes at load are INTEGRITY. |
| **INTEGRITY freeze has no autonomous clear (W15)** | Accepted residual: build-side incident handling clears it (C5); the venue stays fail-closed until then. |
| **Concurrent agents; venv; memory** | Disjoint Wave 1 ownership, per-agent scratchpads, no `git stash`, no `uv`, re-gate per merge; §5.2 memory budget and own locks. |

## 8. Open decisions

OD-1..OD-5 stay settled (INTEGRITY freeze until CLI clear; activation at next LAUNCH; fee drift TERMINAL; challengers
judged offline and by forward shadow; refusals written on transition). **Left to the AUT-5 policy ruling's peer review,
not the operator:** α_total, K_LIFETIME (≤ 4), `BOOTSTRAP_B_MAX`, `uptime_floor`, M, forward-day and station-day
minimums, drawdown limit, the calibration non-inferiority margin, per-detector horizons and cause classes, the drill
window, `forward_window_days`, the ATTEST cadence and the §4.5 staleness values, each within its code bound.

## 9. Contradictions found (README and rulings versus code)

(1) The nightly fits nothing (G12): AUT-3 starts from the fitters. (2) "Demotion is fail-safe" holds only for entry-only
demotion; the exec-store halt blocks exits (G5). (3) Commit-free promotion needs the one-time lineage allowlist widening
(§4.2, G4). (4) The policy ruling must supersede D11 for allowlisted lineages. (5) One sender per node (G1): challengers
are measured by forward shadow. (6) Rollback needs the containment widening (C5). (7) CRH kinds send with no live-orders
gate (G19), so they are never CHAMPION until routed through it. (8) `breezy-check-alerts` likely reports "delivered" on
a failed webhook, emitting through the tee (G26); proof targets the webhook branch. (9) The README's "fee probe unwired"
and "no NBP positive line" were stale (G31); the gaps are absence detectors. (10) `RuntimeMaxSec` cannot bound a oneshot
(G32). (11) The holdout had no end (G37).

## 10. Area plan obligations

Each AUT-n plan must specify the following, consuming C1–C6 and §4 unchanged.

- **AUT-1:** the `CaptureAdapter` call sites per composable kind; measured C1 volume per day; the `EntryVeto` record
  writer; the node-local observations behind `feed_stale`, `recorder_stale`, `capture_gap` (source, period, clear
  condition); the recorder and feed stall observations, naming each unit AUT-6 may restart; the daily join audit with
  offline intent linkage (P1-3); the payload store and volume (P1-4); the settlement writer (P1-6);
  `capture_epoch_start`; with AUT-4, the live-vs-batch parity take divergence (38 vs 35); the `Exit` id function and
  record (P1-8); the `capture_untagged` refusal (P1-9); restarts only via AUT-6 (P1-10, P1-12).
- **AUT-2:** the −0.37/+0.37 root cause with artefact evidence before any scorer change; the per-leg reconciliation
  tolerance; the intraday RECONCILIATION producer (cadence within the W1 invariant) and the post-STOP producer (§4.4:
  STOP signal, venue snapshot source, runtime bound); exclusion of `canary`, `drill` and `voided_pair` rows; the canary
  store's `Scorer` input (Z14); the label-lag alert; the measured rate of AMBIGUOUS intents open after STOP, from the
  post-STOP producer (Z19, P2-4); attribution via C1 only (P2-5); `p_source`; the 14:15Z and 05:00Z slots (P2-2); the
  `portfolio-roi` scorer (P6-9); bought-leg `p_at_decision` (P3-9); the retired kinds' real `Scorer` until their last
  fill is labelled (P2-6); `TimeoutStartSec` on its oneshots (r3 lists `RuntimeMaxSec`) and the §5.2 reconcile-lock
  rows.
- **AUT-3:** the refit cadence and windows; the mint path honouring `MAX_MINTS_PER_LINEAGE_PER_DAY` across model classes
  (P3-2); the ablation and leakage assertions; the reproducibility sample; the G11 widening with parity tests and the
  re-pointed refusal test (P3-8); the C4.1 split end; `own_outcome_max_abs_delta_p` (P3-4); `refit_run/v1` with
  `MINT_REFUSED_CEILING`, no `k_max_reached` (ALPHA); its unit's `MemoryMax`, `TimeoutStartSec` (notify: §5.2), flock
  wait.
- **AUT-4:** the replay-sufficiency check that admits forward-shadow tape days; station-day clustering; the measured
  qualifying station-days per day; the feasibility record (`n_min`, MDE at α_K, `eta_date`) handed to the policy ruling;
  lifetime nomination and α accounting (`k_life`, `alpha_k`, `n_min_eff`, `n_cap`, the window-cap rule,
  `BOOTSTRAP_B_MAX`; C4); the `engine_input/v1` schema and contract test (P4-9); `verdict_id` without `produced_at_ns`
  (P4-11); the two ruling-sha fields (P4-10) and the five `assumptions` tags (P4-12); the calibration non-inferiority
  margin and measured false-fail rate (P4-6); the FQ boundary ruling draft (P4-2); the slippage source and its
  `assumptions` tag; the live-sequential producer over admissible labels; `TimeoutStartSec` on its oneshots.
- **AUT-5:** the policy ruling and its `autonomy-policy/v1` block (every key, every value within bounds, drill clause
  and window, `forward_window_days` and anchor, `attest_required_detectors`, detector cause classes); the pinned
  drawdown producer with its label handshake and H0 calibration tests (P5-6, review M6); `BOOTSTRAP_SEED` genesis rows
  (P5-2); `build_child_env` at four sites (P5-3); `registry_shadow` and the shadow root (P5-7); the
  `launch_precheck_failed` signal and two-pass timer (P5-5); the engine input journal writer (P4-9);
  `DEFAULT_RESTRICTIVE_CLASS` (P4-10); the dead-man's health-heartbeat read (P6-13); the `FillReader` (P5-4); the
  engine's daily, intraday (restrictive plus ATTEST, heartbeat) and pre-launch modes, staggered timers and lock; the
  ATTEST cadence meeting the §4.5 invariant (W1); the watch actor (loop-thread bridge); `entry_guard` with its exact-key
  read path, the injected `FillReader`, the lint-imports contract and the per-tick cache, plus the required `entry_veto`
  slot per kind (W6, W10); HWM key handling and the `breezy-registry-hwm-reset` CLI (restrictiveness check, counter
  carry, export supersession; W4); the demand directory and its archive (W16); the supervisor's journaled
  STOP-completion signal (W8); supervisor env handoff, the relaunch rule, the post-launch SWAP_CANCEL relaunch and the
  registry-aware `breezy-trade-relaunch` helper replacing the hand `systemd-run` runbook; the dead-man (P6-5); bootstrap
  with the root copy and exemption (P7-1, P7-5); the G34 base fix; the 15 min SLO test harness; the §5.2 per-mode engine
  bounds; pre-launch-only RESUME (P7-9); the artefact handoff (P7-10); the relaunch-request TTL (P5-11).
- **AUT-6:** the detector catalogue per kind, split `NODE_LOCAL` / `VERDICT`, each with horizon, policy action class and
  escalation path; the intraday producer and its HEALTH verdicts cited by ATTEST; `deliver_with_proof`, its per-attempt
  records (P6-6), the node outbox worker and deadline (W9), and the RED test proving G26; the migration of every
  CRITICAL site to it and the two-day `alerts_undeliverable` read (W13); the canary, its retry cadence, the receiver's
  absence rule and its live proof; the six failing units (adding `run-p814078`); `TimeoutStartSec` for every oneshot
  study (G32); the effective-`MemoryMax` check (P6-10); the SELF_HEAL executor (P6-7); `SELF_HEAL_RESTARTABLE_UNITS`
  membership, the persisted per-unit restart cap (W11) and the argv-only restart call site; the `aut6.health` producer
  pin and health heartbeat (P6-13); the INTEGRITY-floor demand writer (P6-12); `try-restart`, the trading-day restart
  window and launch-window deferral (P1-10, P1-12); the `fee_schedule` DRIFT verdict (P7-11).
- **AUT-7:** rollback-target selection (most recent `rollback_eligible`, not `terminal_frozen`, bytes re-verified); the
  C5 failed-rollback rules (`ROLLBACK_FAILED`, `target_integrity`), no new `cause_code` (ROLLBACK-FAILURE); the three
  P7-7 values; fee via the AUT-6 verdict (P7-11); the advisory 15:30Z intent check (P7-6); the gate drill (AUT-7a); the
  live drill steps for AUT-7b — with `fq_v1` CHAMPION and not `demoted_for_cause` (W2), mint the byte-identical child
  `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage), DRILL_ADMIT it, DRILL_PROMOTE at LAUNCH (`fq_v1` superseded and
  rollback-eligible, W3), write the drill marker so `DRILL_INJECT` demotes it through the live path, remove the marker
  so the verdict PASSes, RESUME (DRILL class), write the `DRILL_INJECT_HALT` marker so it HALTs, ROLLBACK to `fq_v1`
  (child DISPLACED; P6-4) — with dates, the drill budget, and the evidence (chain, export, node log, delivery records);
  clock 5–6 trading days (P5-8).

## §R8 Disposition (`reviews/ARCH-planner-feedback.md`; `reviews/ROLLBACK-FAILURE-decision.md`)

Rev 7 text and §R7 (24 FIXED, 2 sub-parts REJECTED) are kept in `reviews/snapshots/ARCH_rev7.md`. **Rev 8: 13 items,
13 FIXED, 0 REJECTED; ROLLBACK-FAILURE applied (3 parts); both sweeps done.** No README score criterion changed; no cap,
enablement, permit, NO-SEND or `allow_short` surface is touched; Nautilus is unmodified.

| Id | Disp. | Where / evidence |
|---|---|---|
| ROLLBACK-FAILURE 1–3 | FIXED | C5 HALT row, Failed rollback, cause classes, columns `cause_code`/`halt_cause_class`/`trigger_cause_class`: `rollback_failed` in non-freezing `ROLLBACK_FAILED`, family-only, daily retry, CRITICAL via `deliver_with_proof`; target mismatch → `target_integrity` ineligible, no freeze (C3, C5); champion's own bytes at load stay INTEGRITY (artefact handoff); §10 AUT-7: no new `cause_code` |
| P7-7, P7-8 | FIXED | §4.5 `ROLLBACK_MIN_DWELL_H` ≥ 24 (effective-to-effective, delays only), `ROLLBACK_TARGET_MAX_AGE_D` ≤ 30, `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` ≥ 0.5; `ROLLBACK_FAILED` never `RECOVERABLE_INFRA`, no budget, no freeze |
| P7-9, P5-10 | FIXED | §4.4, C5 RESUME row: RESUME only at the 16:45Z pass; the 15:30Z pending write uses the newest intraday RECONCILIATION, the post-STOP verdict binds ACTIVATE only |
| P7-10, P7-11 | FIXED | G38, C5 artefact handoff (store path + row sha; loader `calibration_artefact.py:250-256` re-verifies at load; `O_NOFOLLOW`); G39, C5 Fee verified (AUT-6 `fee_schedule` verdict) |
| P1-8, P1-9 | FIXED | C1 `kind += Exit` (id over four exit tags, invariant (i) split); C5 `VetoReason += capture_untagged` |
| P1-10, P1-12, P5-11 | FIXED | G40; §4.5 `try-restart` only, restart cap per trading day [16:45Z, +24 h); `RELAUNCH_REQUEST_TTL_S` = 120 (C5 relaunch rule) |
| P1-11, P5-9; sweeps | FIXED (verified); DONE | Rev 7 already used `TimeoutStartSec`; G29: all 20 oneshots carry it; `RuntimeMaxSec` remains only as the no-op fact and the notify allowance. §5.2: units outside the launch-path table never meet [16:30Z, 17:10Z) with W + `TimeoutStartSec`; the launch-path units must act inside it (§4.4, P5-5), so each is bounded to end before its next fixed point |

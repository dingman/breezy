# AUTONOMY_ARCHITECTURE — umbrella architecture for AUT-1..AUT-7 (2026-10-03, Rev 4)

**Status:** PLANNING, Rev 4 (Rev 1 scored 68, Rev 2 76, Rev 3 81; §R4 disposes Z1–Z20). Nothing here
is implemented.
**Parent:** [README.md](README.md) (scale, score-3 criteria, binding constraints).
**Ruling:** `docs/evidence/RULING_operator_full_autonomy_2026-10-03.md`.
**Scope and layering.** This document defines the shared contracts C1–C6, the autonomy safety
envelope and its invariants, the area boundaries, the build order, the reuse map and the risks.
Area-specific procedure (drill steps, slot rows, detector catalogues, unit lists) is not defined
here: §10 lists, per AUT-n, what that area's plan must specify. Each AUT-n plan consumes the
contracts and must not redefine them. A change to a contract is a change to this file, and it is
re-reviewed.
**Evidence tags.** `file:line` was checked at `4b8347a6`. **INFERRED** is unverified against running
code, and each such item clears its L-1 check before the slice that relies on it starts.

## 1. Goal state

One unattended closed loop per venue. **Capture** (AUT-1): every decision, refusal, intent, order,
fill, cancel, mark and settlement, joined on one `decision_id`. **Label** (AUT-2): every fill scored
against settlement and reconciled at net position within 24 h. **Refit** (AUT-3): lineage-complete
candidates from rolling external weather plus own labels. **Evaluate** (AUT-4): offline and
forward-shadow scoring against champion and market baseline, plus PREREG sequential tests, each a
C4 verdict. **Promote or demote** (AUT-5): an engine executes one pre-registered policy ruling into
hash-chained C5 transitions, picked up with no commit. **Drift** (AUT-6): node-local entry vetoes
or C4 verdicts mapped to halt, demote, self-heal or alert. **Rollback** (AUT-7): restore the last
rollback-eligible champion at a byte-identical sha, or halt.

Every area reaches score 3 by the same two levers:
- **Family-agnosticism by construction.** C6 makes a plug-in mandatory at registration, so no family
  can compose or send without one. A kind with no live family carries a `RefusingPlugin`.
- **Fail-closed by contract.** Every consumer of C1–C5 treats a missing, stale, unparseable,
  unknown-version or unverifiable record as the restrictive outcome: no promotion, an entry stop, an
  alert.

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
| G22 | Supervisor cycle: STOP 16:40Z, LAUNCH 16:50Z, launch window closes 17:00Z. Mid-day relaunches reuse the child's environment. | `trade_supervisor_core.py:37-59` |
| G23 | FQ `try_submit` runs `submit_veto` (the family-halt veto), and the same callable reaches the exec client. An entry-only veto needs its own slot. | `fq/strategy.py:629-643`; `app/trade.py:709-713,846-853` |
| G24 | A NO buy is `OrderSide.BUY` on a composite NO-leg `InstrumentId`; the adapter translates it to venue `SELL`/`BUY_SHORT`. Every entry is a BUY; exits are SELLs; OMS is `NETTING`. | `fq/strategy.py:682`; `symbology.py:289-295`; `leg_prices.py:41-48`; `exit_wiring.py:59-66`; `exec/client.py:1672` |
| G25 | `emit_alert` returns `None` and swallows every `BaseException`. `TeeAlertSink.emit` routes **each branch** through `emit_alert`, so a tee-level emit can never report a failure. `WebhookAlertSink.emit` raises on non-2xx (`raise_for_status`). The branches are exposed read-only. | `runtime/health.py:479-510`; `:366-369`; `:297-299`; `:362-364` |
| G26 | `breezy-check-alerts` calls `sink.emit` directly (not `emit_alert`) to prove delivery, but on the sink from `resolve_alert_sink`, which is a tee when configured, so its "not delivered" exit looks unreachable in production (**INFERRED**, AUT-6 RED-tests it first). | `check_alerts_cli.py:19-23,126,141`; `health.py:419-423` |
| G27 | Alert egress convention: one dedicated single-key `~/.config/breezy/alerts.env` (0600), loaded by `EnvironmentFile=-` in each unit that alerts; the only key is `BREEZY_ALERT_WEBHOOK_URL`. | `deploy/systemd/README.md:679-694`; `breezy-trade-supervisor.service:89`; `health.py:116` |
| G28 | The FQ persistent latch namespace is **kind-scoped** (`forecast_quantile_ladder/trial/`), keyed `(station, climate_day, rung_id, side)`, so a same-kind successor sees the same latch, but a YES latch does not block a NO entry on the same slug. | `fq/persistent_latch.py:68,87-94,124-136` |
| G29 | No unit under `deploy/` sets `RuntimeMaxSec` today (`/usr/bin/grep -rn RuntimeMaxSec deploy/`: 0 hits). The host has 30 GiB RAM (`free -g`). | grep; `free -g` |
| G30 | The supervisor already probes the exec store for an OPEN intent read-only, and the node repairs or keeps an OPEN intent at startup (`reconcile_at_startup`). | `trade_supervisor.py:402`; `runtime/submit_intent.py:441-483` |

**L-1 null hypothesis per new component.**
- Nautilus has no artefact registry, champion/challenger state, promotion engine or scheduled restart
  (`WORK_BREAKDOWN:288`; `trade_supervisor.py:15-21`).
- Reused Nautilus features: `Order.tags` (G9); `ClientOrderId`/`TradeId` for the order-to-fill join
  (`exec/client.py:400-412`); `Actor` plus `clock.set_timer` (G16); `ParquetDataCatalog` for
  tape-shaped capture.
- **`TradingState.REDUCING` is insufficient; the custom entry veto is retained.**
  `nautilus_trader/risk/engine.pyx:1150-1163` denies a BUY only when `is_net_long(instrument)`.
  Every Breezy entry is a BUY into a usually **flat** instrument (G24), which REDUCING admits, and
  REDUCING is node-global, so it cannot express per-family state. (`account_presence_halt.py:171`
  sets `HALTED`, not REDUCING.) The veto uses the native `try_submit` guard slot, an extension.

## 3. Shared contracts

**Common rules (apply to C1–C5):**
- Every record carries `schema: "<contract>/v<N>"`. Readers accept only allowlisted versions and
  refuse anything else. Schemas are exact-set and grow only by L-12 widening with their readers.
- Serialisation is explicit (no `dataclasses.asdict`). Writes are atomic (`mkstemp` + `os.replace`;
  `runtime/health.py:322,330`), append-only, named by content hash or `now_ns` (L-50). Timestamps
  are integer ns UTC from the injected clock. Money is a string-decimal.
- Stores live under `~/.local/share/breezy/{state,derived,registry,evidence}/`, never in the repo.
  Directories 0700, files 0600, content-addressed artefacts 0444.
- **Single-read rule (Y4, Z16).** Every consumer of a C3 artefact, C3 lineage, C4 verdict, C5
  export, registry child manifest, drill marker, restrictive-demand file, engine-heartbeat file or
  alert-delivery journal opens it with `O_NOFOLLOW` (a symlink anywhere on the path is refused),
  reads it **once** through one descriptor, and hashes and parses those same bytes.
- **Payload hygiene.** Alerts, C1 records and C4 verdicts carry no absolute paths, env values,
  account or venue order ids, or credentials; venue order ids appear only as `sha256`. Reuses the
  `AlertPayload` forbidden-content list (`registry/health_model.py:217-235`). A scan test covers
  every autonomy writer.
- Python types live in one new package, `src/breezy/persistence/autonomy/`, importable by node and
  analysis (G15). Grep the containment tests first (L-46).

### C1 — Decision id and capture schema (producer AUT-1; consumers AUT-2, AUT-4, AUT-6)

**`decision_id`** = the first 32 hex characters of
`sha256(family_id | manifest_sha256 | artefact_sha256 | station | climate_day | rung_id | side | eval_ns)`.
- `eval_ns` is the Nautilus `clock.timestamp_ns()` at decision, **recorded** in the
  `DecisionRecord`; the recorded value is authoritative. Recomputation uses the record's own fields
  and never re-derives `eval_ns` (a test recomputes the id from a stored record).
- It travels as the native order tag `breezy:decision_id=<id>`, defined next to the exit prefixes
  (`persistence/exit_tags.py`), set at each kind's one `order_factory.limit` call
  (`fq/strategy.py:681`; CRH `_maybe_submit`).

**Record types.** All share `schema`, `decision_id`, `family_id`, `ts_ns`, `node_boot_id`,
`build_sha`, `registry_seq`, `drill` (bool, Y2) and `source` (`live` \| `canary`).

| Type | Fields | Writer |
|---|---|---|
| `DecisionRecord` | `kind` (`Take` \| `Refuse` \| `NotExecutable` \| `NotDPlus1` \| `TrySubmit` \| `EntryVeto`); `reason`; `eval_ns`; `station`, `climate_day`, `rung_id`, `side`, `instrument_id`; `ask_px`; `depth_ref` (sha256 of the Depth10 row, L-35); `p_hat`, `p_lower`, `p_upper`, `ev_net`; `forecast_input_sha256`; `artefact_sha256`; `manifest_sha256` | node, via the C6 `CaptureAdapter` |
| `OrderLink` | `client_order_id`; `venue_order_id_sha256: str\|None`; `intent_id` | node `on_order_*` |
| `LifecycleEvent` | `event` (`SUBMITTED` … `AMBIGUOUS`); `client_order_id`; `trade_id`; `qty`, `px`, `fee` | node |
| `PositionMark` | `instrument_id`; `leg`; `net_qty` (signed, venue convention, C2); `mark_px`; `source` | node or position monitor |
| `DetectorEvent` | `detector` (C6 id); `observation_sha256`; `state` (`AGREE` \| `DISAGREE` \| `UNKNOWN`) | in-node detectors |
| `SettlementRecord` | `station`, `climate_day`, `settlement_tmax_f`, `basis`, `raw_sha256` | offline |

`drill` is true for every record of a family inside a **drill episode** (Z2): the fold interval
from its `DRILL_PROMOTE` taking effect through the `ROLLBACK` pair that closes it. Fills after the
drill's DEMOTE and RESUME are still drill fills (`test_drill_flag_spans_promote_to_rollback`).

**Storage.** A daily file `decisions/capture_<family_id>_<YYYY-MM-DD>.jsonl`, following the
`OfferTape` and `FqDecisionFunnelActor` convention (`crh/composition.py:568-602`;
`app/trade.py:763-775`); the existing retention unit compresses it.
- **No silent cap.** A write failure or byte cap increments a counter, raises a CRITICAL alert and
  marks the day `CAPTURE_INCOMPLETE`.
- A `Refuse` or `EntryVeto` is written when `(key, reason)` changes, not on every tick (L-29). Every
  `Take` and `TrySubmit` is written.
- **Rejected alternative:** `StreamingConfig` on the trade node (memory and flush risk in the order
  process). Reopened only with a measured L-1 proof.

**Invariants.** (i) Every submitted order carries exactly one `decision_id` tag (a test per
composable kind). (ii) Every durable fill (`exec/client.py:408-447`) joins to exactly one
`DecisionRecord` through `client_order_id`. (iii) The daily audit requires decisions ⋈ links ⋈ fills
⋈ settlements = 100% for every settled live fill.

**Failure behaviour.** A missing tag refuses the submit (`capture_untagged`). A write error raises a
CRITICAL alert and makes the day inadmissible for AUT-4. A join gap is a `HEALTH` FAIL.

### C2 — Scored-outcome label (producer AUT-2; consumers AUT-3, AUT-4, AUT-6)

**Schema `label/v1`.** One parquet file per run at
`derived/labels/<family_id>/labels_<now_ns>.parquet`, append-only, deduped on
`(label_id, max label_seq)` (the G8 conventions). The scored-trial store stays untouched. The
pyarrow schema is pinned column for column.

Fields: identity (`label_id`, `decision_id`, `family_id`, `trial_id`, `client_order_id`,
`trade_id`); market (`station`, `climate_day`, `instrument_id`, `rung_id`, `leg`, `role`
`entry`\|`exit`); fill (`qty`, `fill_px`, `entry_ask`, `fee_reconciled`, `slippage`, str-decimal);
`p_at_decision` (float64, nullable only with a reason); settlement (`settled_outcome` = the bought
leg's win, `settlement_tmax_f`, `settlement_basis`); P&L (`realized_pnl` net of reconciled fee;
`counterfactual_hold_pnl` for exits); reconciliation (`reconciled`, `reconciliation_delta`,
`reconciliation_source`, `net_position_key` = base slug); admissibility (`admissible`;
`excluded_reason` ∈ `duplicate_fill`, `q≠1`, `fee_unreconciled`, `window_incomplete`, `canary`,
`drill`); run metadata (`labelled_at_ns`, `label_seq`, `scorer_id` = C6 id plus producer code sha).

**Invariants.**
- **Net-position reconciliation.** "Reconciled" means **the venue's net signed position per base
  instrument equals the ledger's** (Y15), not that the position is flat. A NO holding nets as short
  YES on the same slug (L-44; `parsing.py:277-279`), so YES and NO fills on one slug are summed with
  the leg sign before comparison. RED tests: a NO fill offsetting a YES holding reconciles to the
  netted venue quantity; each leg's terminal state.
- Only `window_complete` rows are scored or counted.
- Every live fill is labelled within 24 h of its `SettlementRecord`, else a `HEALTH` FAIL
  (`label_lag`).
- `reconciled=False`, `source=canary` and `drill=true` are never `admissible` and never count toward
  any n, any live-sequential look or the KILL clock (Y2).
- "Nothing to score" exits 0 with a `NO_INPUT` line. No unit exits non-zero as expected behaviour.

**Failure behaviour.** A fill that cannot be labelled becomes an `excluded_reason` row; a score is
never fabricated (`trial_scorer.py:158`). Reconciliation outside tolerance: `reconciled=False`, a
CRITICAL alert and a `RECONCILIATION` FAIL.

### C3 — Artefact lineage manifest (producer AUT-3; consumers AUT-4, AUT-5, AUT-7)

**Storage.** Content-addressed and immutable:
`derived/artefacts/<model_class>/<artefact_sha256>/{artefact.json, lineage.json}`. Files 0444,
directories 0500, single-read rule. The layout generalises the G13 candidate root; the artefact
bytes use the existing writer (`nbp_calibration.py:2643`).

**Schema `lineage/v1`.**
- `artefact_sha256`; `model_class` (`composition_kind:component`); `lineage_root_family_id`;
  `parent_artefact_sha256`; `code_git_sha`, `build_sha`, `producer_code_sha` (§4.3); `params`;
  `seed`; `fit_status` (`OK` only); `data_windows` (`{source, start_utc, end_exclusive_utc, rows,
  content_sha256}`).
- Own-outcome use: `own_outcome_label_set_sha256` (str \| null) records the C2 label set used;
  `ablation_artefact_sha256` is the same refit with that set left out, and the writer refuses the
  lineage if it is non-null and equals `artefact_sha256`.
- **The C2-consuming model class** is `forecast_quantile_ladder:rung_recalibration`, fitted on C2
  `(p_at_decision, settled_outcome)`; it needs the G11 loader widening with parity tests.
  `forecast_quantile_ladder:density_table` consumes external weather only.
- Evaluation windows: `train_end_exclusive_utc`, `forward_eval_start_utc` (≥ `created_at`).
- `leakage_assertions`: `{name, passed}`, including `ref_ts_lt_take_ts`,
  `train_end_lt_forward_eval_start` and `no_sealed_holdout_rows_in_train`.
- `recalibration` and `correction_form` are members of the live loader's accepted set (G11).
- Run metadata: `created_at_ns`; `runtime_s`; `peak_rss_bytes`.

**Invariants.** `sha256(artefact.json) == artefact_sha256`. A scheduled rerun from `lineage.json`
on a sampled subset reproduces the sha; a mismatch is a `HEALTH` FAIL. A lineage with a failed
assertion is never written.

**No-new-lineage children (Y2).** A child whose `artefact_sha256` equals an existing artefact (the
drill child) gets **no new C3 record**: its MINT row cites the existing content-addressed
directory, the C3 writer is not invoked, and no `lineage_counters` entry increments.

**Failure behaviour.** A missing or mismatched lineage makes the artefact ineligible above SHADOW.
A rollback re-verifies the bytes.

### C4 — Verdict (producers AUT-2, AUT-4, AUT-6; consumer AUT-5, plus AUT-7 triggers)

**Storage.** `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json`; directories 0700;
files append-only; `verdict_id` = sha256 of the canonical body. Producers run as their own oneshot
units, separate from the engine unit and the node.

**Schema `verdict/v1`.**
- Identity: `verdict_id`; `kind` (`OFFLINE_CHALLENGER` \| `FORWARD_SHADOW` \| `LIVE_SEQUENTIAL` \|
  `DRIFT` \| `HEALTH` \| `RECONCILIATION`); `subject_family_id`; `subject_artefact_sha256`;
  `comparator_family_id`.
- Outcome: `outcome` (`PASS` \| `FAIL` \| `UNDERPOWERED` \| `INCONCLUSIVE` \| `ERROR`); `detector`
  (C6 id); `declared_action_class` (`NONE` \| `ALERT` \| `SELF_HEAL` \| `DEMOTE` \| `HALT`).
- Measurement: `metrics` (pre-registered names only); `n` and `n_min` **in the unit the ruling names
  for that kind** (independent station-days for `FORWARD_SHADOW`, Y14); `power`; `mde`;
  `eta_to_verdict_days`; `alpha_spent` (cumulative, lineage-level).
- Provenance: `inputs` (`{path_role, sha256}`, no paths); `prereg_ruling_sha256`; `produced_at_ns`;
  `valid_until_ns`; `producer_code_sha`; `assumptions` (closed enum, e.g. `slippage_champion_proxy`).

**Evaluation protocol.**
- `OFFLINE_CHALLENGER` scores the candidate against the champion on historical external weather,
  using the sealed-holdout rules (`nbp_calibration.py:334-420`) and the pinned bootstrap
  (`roi_bound.py:93-100`). The sealed `DEFAULT_SPLITS` holdout is opened **at most once per
  lineage** (`holdout_opens`). Routine selection uses a **rolling forward holdout**: only days on or
  after the candidate's `forward_eval_start_utc`.
- `FORWARD_SHADOW` evaluates the challenger prospectively on post-mint days. It requires all of:
  (a) traded-rung Brier beats the **market-implied baseline** (reusing
  `scripts/analysis/wp7b_market_as_forecaster.py`); (b) EV net of reconciled fee and slippage;
  (c) the traded-rung calibration leg passes (`forecast_conditional_scoring.py:392`); and
  (d) `n ≥ n_min` in **independent station-days**: takes within one `(station, climate_day)` form
  one cluster and count once (Y14).
  - **Admissible inputs (Y12).** Only tape days that pass the replay-sufficiency check (memory note
    `quote-tape-is-not-replay-sufficient`) are inputs. Other days are excluded by name, never
    imputed.
  - **Slippage source (Y12).** Slippage comes from C2 champion fills against the same Depth10 rows.
    Using the champion's slippage for a challenger with a different policy is an assumption: the
    verdict must carry `assumptions: [slippage_champion_proxy]`, and the policy ruling must state
    whether it accepts that assumption for the challenger's policy class. Without that statement,
    such a verdict is `INCONCLUSIVE`.
- **Multiple testing (Y13).** The k-th candidate evaluated in a lineage against an overlapping
  forward window is tested at α_k = α_total·2^−k. At most `K_max` candidates per lineage per
  forward window may be evaluated, and at most one MINT per lineage per day (code ceilings,
  §4.5). The policy ruling states the MDE at α_K = α_total·2^−K_max for its `n_min`. The registry
  counts `candidates_evaluated`, and the engine refuses verdict k > K_max as `ERROR`.
- `LIVE_SEQUENTIAL` reuses `run_sequential_looks` (`family_tally_v2.py:625`) and its boundaries
  (`crh_group_sequential_boundaries.py:243`), never defines a new α-spend, counts admissible
  labels only (no canary, no drill), and is used mainly to demote.

**Invariants.** Every verdict states `n_min` or the literal reason it has none.

**Engine acceptance.** The engine acts on a verdict only if: `producer_code_sha` is in the committed
producer pin set (§4.3); every `inputs[].sha256` resolves under that role's root; `prereg_ruling_sha256`
equals the policy ruling's; `declared_action_class` equals the ruling's `detector → action_class`
entry; `valid_until_ns − produced_at_ns ≤ MAX_VERDICT_VALIDITY_H` (§4.5, Z4); and
**`subject_artefact_sha256` equals the subject family's bound artefact sha** (Z1): the
`artefact_sha256` of its BOOTSTRAP or MINT row. A family id is bound to one immutable artefact; the
store refuses any later row for that family carrying a different `artefact_sha256`, so rows that
carry none (ATTEST, SUPERSEDE, DISPLACED, DEMOTE, RESUME) never move the comparison. Any mismatch
makes the verdict `ERROR`, with an alert; it never acts. Tests `test_verdict_accepted_after_attest`,
`test_family_artefact_binding_immutable`.

**Failure behaviour.** A verdict past `valid_until_ns` is `ERROR`. `ERROR`, `INCONCLUSIVE` and
`UNDERPOWERED` never promote. An accepted `FAIL` mapped to `DEMOTE` or `HALT` always acts. Champion
staleness is enforced node-side (C5 watch actor), independent of the engine (Y3).

### C5 — Registry, state machine and transition audit (owner AUT-5; AUT-7 co-writes through the same API)

**Storage and isolation.**
- SQLite at `~/.local/share/breezy/registry/registry.sqlite`, dir 0700, file 0600. It is not the
  exec store, because of the flock (G6) and no iteration (G7).
- **Journal mode (Y5): `journal_mode=DELETE`, `synchronous=FULL`**, deliberately unlike G7's WAL:
  the registry writer is a oneshot that exits, SQLite then removes `-wal`/`-shm`, and a `mode=ro`
  reader on a read-only directory cannot recreate them; a rollback journal needs no side files. A
  hot journal from a crashed engine fails the read-only open → `registry_unreadable` (fail-closed,
  cleared by the next verified read after the engine rolls it back). RED test
  `test_registry_readonly_open_engine_stopped` (writer commits and exits, dir 0500, `mode=ro` open
  plus full chain verify succeeds).
- **Single writer:** `breezy-autonomy-engine.service` and its intraday and pre-launch modes, all one
  binary (`ReadWritePaths=` the registry and evidence dirs only, `ProtectSystem=strict`, memory
  cap), serialised by their own lock `~/.local/share/breezy/registry/engine.lock` (`flock -w 60`),
  never the studies flock (Y23). AUT-7 runs inside it. Any operator registry tool writes through the
  same API and chain (`decided_by=operator_cli`).
- **Readers** (node, supervisor, timers) use the `mode=ro` URI (`trial_day_latch.py:354-379`). The
  node's spawn carries `ReadOnlyPaths=` on the registry directory.
- **Residual risk, stated:** a same-uid writer could rewrite the chain (or forge a heartbeat or
  demand file) consistently. Chain, export and node HWM give tamper *evidence*; *resistance* is in
  code: a row selects only among candidates the committed allowlists and sha-pinned rulings already
  authorise (§4.2), re-derived by the node from bytes; a forged heartbeat still meets H.

**One chain per venue (Y20).** Each venue has its own hash chain, CAS counter and genesis
`sha256("registry/v1|" + venue)`. The global `seq` only orders rows; it never links them. Lineage
counters are venue-independent.

**Tables (`registry/v1`).**
- `transitions` is the only source of truth. Columns: `seq` PK; `venue`; `venue_seq` (UNIQUE with
  `venue`); `transition_id` UNIQUE; `family_id`; `family_prior_seq` (the `venue_seq` of this
  family's previous row, or 0); `paired_transition_id` (set on the partner of an atomic pair; null
on the PROMOTE side, whose id is computed first, and on unpaired rows; Z20);
  `from_state`; `to_state`; `kind`; `cause_verdict_ids` (JSON); `voids_transition_ids` (JSON,
  `SWAP_CANCEL` only); `manifest_sha256`, `artefact_sha256`, `lineage_root_family_id` (**required**
  on BOOTSTRAP, MINT, PROMOTE, DRILL_PROMOTE, ROLLBACK, ACTIVATE; Y6); `attest_valid_until_ns`
  (ATTEST only); `hwm_from`, `hwm_to` (HWM_RESET only); `drill` (bool) and `drill_clause_sha256`;
  `policy_ruling_id`;
  `policy_ruling_sha256`; `decided_by`; `invocation_id`; `engine_code_sha`; `expected_prior_seq`;
  `effective_launch_date` (null means immediate); `ts_ns`; `prev_transition_hash`;
  `transition_hash`. Triggers `BEFORE UPDATE` and `BEFORE DELETE ON transitions` → `RAISE(ABORT)`.
- `families` and `projection` are **derived caches**, rebuilt in the same transaction and **never
  read by the node, the supervisor or the resolver** (Y4). They exist for the engine and humans.
- `lineage_counters`: `holdout_opens`, `candidates_evaluated`, `alpha_spent`, `mints` and
  `promotions` (timestamped), `rollbacks`, `terminal_frozen` (Y10), and a separate drill budget
  (`drill_admits`, `drill_promotes`, `drill_resumes`, `drill_rollbacks`; Y2), and the venue-level
  `infra_resumes` (Z10).

**Hash chain.** `transition_hash = sha256(canonical row ‖ prev_transition_hash)` within the venue
chain. A daily export `evidence/registry/registry_<venue>_<date>.jsonl` (0444) holds every new row
plus the chain head; a reader refuses a chain whose prefix disagrees with the latest export.

**Effective-time fold (Y8).** `resolve_champion(venue, now)` is a pure function of the verified
chain and the clock. It is the **only** source of state, of the X8 invariant and of "pending":
- A row with `effective_launch_date = D` is **pending** before LAUNCH on D (16:50Z, G22).
- At LAUNCH on D a pending pair takes effect **only if** an `ACTIVATE` row for that pair was written
  in [16:40Z, LAUNCH) on D by the pre-launch pass (§4.4). Otherwise the pair **lapses**: it never
  takes effect, the incumbent stays champion, and the engine must propose afresh.
- A `SWAP_CANCEL` row voids the pending rows it lists. **Post-launch cancel (Z8):** a SWAP_CANCEL
  written in [LAUNCH, 17:00Z) on D that cites the pair which took effect at D's LAUNCH voids it
  retroactively; the fold restores the incumbent, the watch actor vetoes the voided family
  (`registry_not_champion`) on its next tick, and the supervisor, still inside its launch-window
  retry, stops that child and launches the resolved incumbent. From 17:00Z an effective pair is
  never voided; a cause then takes the DEMOTE path. Test
  `test_post_launch_swap_cancel_restores_incumbent`.
- A lapsed or voided pair is never charged to any §4.5 counter (Z3).
- The invariant **each venue has at most one family in {CHAMPION, HALTED}** is evaluated on the fold
  at `now`. `next_*` in the cache is only a rendering of pending rows.

**States.** `SHADOW` (offline only), `CHALLENGER` (passed the offline gate, never sends), `CHAMPION`
(the single sender per venue), `HALTED` (champion with entries stopped for cause), `RETIRED`
(terminal).

**Allowed transitions.** This is the whole set; the store refuses any other pair or kind.

| From → To | Kind | Allowed when | Effective |
|---|---|---|---|
| ∅ → SHADOW | BOOTSTRAP / MINT | Committed root, or a child passing §4.2 equality and C3 (or the C3 no-new-lineage rule), complete C6; mint-rate ceiling | now |
| SHADOW → CHALLENGER | PROMOTE | Accepted `OFFLINE_CHALLENGER` PASS | now |
| SHADOW → CHALLENGER | DRILL_ADMIT (Z2) | Drill clause active; the C3 no-new-lineage equality holds (artefact sha, and manifest modulo §4.2, equal the incumbent champion's); no α and no `candidates_evaluated` charge; drill budget | now |
| CHALLENGER → CHAMPION | PROMOTE | Accepted `OFFLINE_CHALLENGER` **and** `FORWARD_SHADOW` PASS; policy `promote_enabled` (§4.2); lineage not `terminal_frozen`; §4.4; rate limit | pending → next LAUNCH |
| CHALLENGER → CHAMPION | DRILL_PROMOTE (Y2) | Drill clause active, its sha pinned in the policy block; the child's `artefact_sha256` **and** manifest (modulo the §4.2 key allowlist) equal the incumbent champion's; drill budget; §4.4 | pending → next LAUNCH |
| CHALLENGER → CHAMPION | ROLLBACK | Target `rollback_eligible`, never `demoted_for_cause`; lineage not `terminal_frozen`; bytes re-verified; §4.4; rollback budget | pending → next LAUNCH |
| CHAMPION → CHALLENGER | SUPERSEDE | The atomic partner of an incoming →CHAMPION; sets `rollback_eligible=true` (never for a drill-episode family) | pending → next LAUNCH |
| HALTED → CHALLENGER | DISPLACED | The atomic partner of an incoming →CHAMPION; `rollback_eligible` stays false | pending → next LAUNCH |
| CHALLENGER → CHALLENGER | ACTIVATE | Pre-launch pass, §4.4 re-verified on the incoming family, cites the pending pair | confirms the pair |
| CHALLENGER → CHALLENGER | SWAP_CANCEL | Restrictive: §4.4 failed at pre-launch, a DEMOTE or HALT cause on either family of a pending pair, or an engine-detected inconsistency. **Always permitted, never capped** | now (voids the pair) |
| CHAMPION → CHAMPION | ATTEST (Y3) | Daily pass: cites an accepted PASS of every kind in the block's `attest_required_verdict_kinds` (e.g. `HEALTH`, `RECONCILIATION`; Z5); `attest_valid_until_ns` = their minimum `valid_until_ns`, refused above `ts_ns + H` (Z4); at most one per venue per day; non-widening, never counted | now |
| CHAMPION → HALTED | DEMOTE / HALT | Accepted FAIL mapped to DEMOTE or HALT, or an exec-store halt mirrored. Clears `rollback_eligible`, sets `demoted_for_cause`. A pending pair naming this family is voided by a `SWAP_CANCEL` in the same transaction, and this family is **never superseded** by it. **Always permitted, never capped** | now |
| HALTED → CHAMPION | RESUME | `halt_cause_class` ∈ {RECOVERABLE_MODEL, RECOVERABLE_INFRA}; cause verdict now PASSes; the fold names this family; **no pending pair on the venue** (Y8); cooldown and the budget of its cause class (§4.5, Z10); §4.4 | now |
| HALTED → RETIRED | RETIRE | TERMINAL cause, or the RECOVERABLE_MODEL resume budget is exhausted. S_k and n are frozen (`WORK_BREAKDOWN:423`). An exhausted INFRA budget never retires (Z10) | now |
| SHADOW, CHALLENGER → RETIRED | RETIRE | Policy (age, failed gate, lineage superseded) | now |
| any → same state | HWM_RESET (Z17) | Operator CLI only (`decided_by=operator_cli`), node stopped; restored chain verifies as a prefix of the latest export; records `hwm_from`/`hwm_to`; non-widening, never counted | now |

**Pending-swap rules (Y8).** A DEMOTE or HALT cause on the **incoming** family writes
`SWAP_CANCEL`; the incoming family stays CHALLENGER with `demoted_for_cause=true`, so it is never
promotable or a rollback target in this lineage until a fresh `FORWARD_SHADOW` PASS post-dating
the cause. A cause on the **outgoing** champion writes `SWAP_CANCEL` and CHAMPION→HALTED in one
transaction; the incoming must be re-proposed through DISPLACED. Tests:
`test_demote_during_pending_swap_incoming`, `test_demote_during_pending_swap_outgoing`,
`test_resume_refused_while_swap_pending`, `test_unactivated_pair_lapses_at_launch`.

**Terminal lineage freeze (Y10).** A TERMINAL cause (a `policy_halt` mirror, fee drift, A1, or an
exhausted resume budget) sets `terminal_frozen` on the lineage. PROMOTE, DRILL_PROMOTE and ROLLBACK
into **any** family of that lineage are refused; only a new lineage root (a reviewed commit)
recovers. Test `test_terminal_halt_freezes_lineage`.

**Idempotency (Y9).**
- `transition_id` = sha256 of `(venue, family_id, family_prior_seq, from, to, kind, sorted
  cause_verdict_ids, paired_transition_id, policy_ruling_sha256)`. The venue-wide
  `expected_prior_seq` is excluded, so a crash-and-retry before commit reproduces the id, while a
  later, legitimate repeat of the same transition for the same family has a new
  `family_prior_seq` and a new id. In a pair, the PROMOTE-side id is computed first and the partner
  cites it.
- Each write is one `BEGIN IMMEDIATE` transaction. If `transition_id` exists, the write is a logged
  no-op. Otherwise: (1) the CAS `max(venue_seq) == expected_prior_seq` must hold; (2) the row is
  inserted, extending the venue chain; (3) the caches are re-folded.
- Non-restrictive writes: on a CAS failure, re-read, re-evaluate, retry once, then alert.
- **Restrictive writes (DEMOTE, HALT, SWAP_CANCEL; Y19)** retry until committed: bounded backoff
  for up to 60 s within the pass, then again on every intraday pass. If the first attempt fails,
  the engine immediately writes a **restrictive-demand file** (Z11), one per (venue, family, ts):
  `registry/demand/<venue>/<family_id>_<ts_ns>.json` (atomic, 0444, schema `demand/v1`, exact-set,
  ≤ `DEMAND_FILE_MAX_BYTES`). The watch actor reads each under the single-read rule and honours it
  as `registry_restrictive_pending` for that family until the chain shows the family HALTED,
  RETIRED or not CHAMPION at a row later than the demand's `ts_ns`; the engine then unlinks it. An
  unparseable, oversized or symlinked file, or more than `DEMAND_FILES_MAX` per venue, vetoes
  **every** family on the venue. A demand can only stop entries, so it needs no authentication.
  Tests `test_restrictive_commit_failure_sets_node_veto`, `test_bad_demand_file_vetoes_venue`.
- Tests: `test_registry_cas_and_idempotent_replay`, `test_repeat_supersede_same_family_is_not_replay`.

**Pickup.**
1. **Activation, at LAUNCH.** The supervisor (`trade_supervisor_core.py:884-895`), the node
   (`app/trade.py:905-990`) and the settings validator (`settings.py:183,366-388`) all call one
   resolver in `persistence/autonomy/resolver.py`.
   - It verifies the venue chain from genesis, checks the export prefix and the node high-water
     mark, folds at `now`, and returns a `ResolvedFamily`: family id, `registry_seq`, chain head,
     and manifest and artefact bytes and shas, each under the single-read rule.
   - **Byte binding (Y6).** The resolver compares the single-read manifest and artefact bytes
     against the `manifest_sha256` and `artefact_sha256` on the authorising row; takes the root
     from the child-id regex `<root>_r<NNNN>` and requires it to equal the row's
     `lineage_root_family_id`; and checks §4.2 manifest equality against the **committed**
     `deploy/families/<root>.json`, never a registry copy.
   - `_validate_sending_family_manifest` and `_compose_family` consume that object and never
     re-read the files.
   - Only when the committed supervisor unit sets `BREEZY_FAMILY_SOURCE=registry`. The value is
     fixed in `deploy/systemd/breezy-trade-supervisor.service`; a scan test proves no autonomy
     code reads or writes it except the resolver.
   - The supervisor resolves **once** per LAUNCH and sets, in the child's forwarded environment
     (G2), `BREEZY_SENDING_FAMILY_ID` to the resolved id, plus `BREEZY_RESOLVED_REGISTRY_SEQ`.
     These are build-side values, not operator controls. A mid-day relaunch keeps them, so nothing
     swaps mid-day.
   - **Relaunch rule (Z7).** The node re-resolves and compares the **family id only**, and checks
     that the passed seq is a prefix of the verified chain (≤ head, chain verifies through it). It
     refuses boot only if the fold at `now` names this family neither CHAMPION nor HALTED. A
     HALTED family boots with only entries vetoed (`registry_halted`), so its exit seam and
     reconciliation stay live. Hand relaunches use the supervisor-provided registry-aware helper
     `breezy-trade-relaunch` (§10 AUT-5), which resolves exactly as LAUNCH does; it replaces the
     hand `systemd-run` runbook. Tests `test_node_relaunch_rule_family_id_and_seq_prefix`,
     `test_halted_family_boots_entries_vetoed_exits_live`.
   - **Hand-relaunch bypass closed (Y7).** Once the registry exists with any row, or the node-local
     high-water mark exists, the node **refuses boot to a sending family** unless
     `BREEZY_FAMILY_SOURCE=registry` **and** the resolved id equals `BREEZY_SENDING_FAMILY_ID`.
     A hand relaunch that mirrors a stale environment is therefore refused, not trusted. Test
     `test_hand_relaunch_without_registry_source_refused`.
   - **Resolver refusals** give "no champion" for: a `composition_kind` outside
     `LIVE_GATE_ROUTED_KINDS` (today `{forecast_quantile_ladder}`, G19); a `live_orders_ruling`
     that is not the policy ruling; a root not in `_LINEAGE_POLICY_ALLOWLIST`; a ruling sha
     mismatch; a broken chain or export; a high-water-mark regression; an authorising
     `engine_code_sha` outside the pin set (§4.3); a byte-binding or §4.2 equality breach.
2. **Deactivation, immediate: `RegistryWatchActor`.** A native `Actor` with `clock.set_timer` (the
   fee-probe pattern, G16), 60 s tick. Its contract:
   - **Thread contract (Z16, L-1 verified).** The `LiveClock` callback runs on a Rust
     `_DummyThread` with no running loop (`ingest/nws_actor.py:27-31,67-80`; pinned by
     `tests/contract/test_live_timer_thread_affinity.py:90-119`), not on the thread that built the
     exec `SqliteStateStore`, whose `_check_thread` raises on any foreign-thread call
     (`runtime/sqlite_store.py:117-136`). The callback therefore only submits `tick_once()` with
     `asyncio.run_coroutine_threadsafe` and returns (the `FeeDriftProbeActor` bridge,
     `fee_drift_probe.py:358-372`, whose loop coroutine already writes `record_policy_halt` to the
     exec store). Every registry read, fold, HWM write and veto-state update runs in that coroutine
     on the loop thread, which also runs `try_submit`, so the veto state needs no lock. Test
     `test_watch_actor_store_touches_stay_on_loop_thread`, with a negative control.
   - **It never reads `projection` (Y4).** Each tick it reads the transitions with `venue_seq`
     above its last verified row, verifies the hash links from its stored head, re-checks that the
     row at the last verified seq still has the stored hash, and folds in memory.
   - **High-water mark (Y4).** The node keeps `(registry_seq, chain_head)` per venue in
     node-local durable state: the exec-store key `autonomy/registry_hwm/<venue>`, written by the
     node under the flock it already holds (G6). The registry still never writes the exec store.
     A lower seq, or a different head at the same seq, gives `registry_regressed` and a CRITICAL
     alert. The HWM only advances after a verified read. The engine's exec-store halt mirror reads
     only exact keys under `continuous_rung_hold/` (`trial_day_latch.py:291-295,354-379`) and no
     reader iterates (G7), so `autonomy/` keys are never mirrored
     (`test_autonomy_exec_keys_disjoint_from_halt_prefixes`).
   - **HWM reset (Z17).** A legitimate registry restore uses the operator CLI
     `breezy-registry-hwm-reset`: node stopped (it needs the exec flock), the restored chain
     verified as a prefix of the latest export, a journal `evidence/registry/hwm_reset_<ts>.json`, a
     CRITICAL through `deliver_with_proof`, and an `HWM_RESET` chain row
     (`test_hwm_reset_cli_journals_alerts_and_chains`).
   - **Entry-veto contract (Y1, Y3, Y16).** `entry_veto(instrument_id) -> VetoReason | None`. It is
     wired into a **new, separate `entry_veto` slot** in each strategy's `try_submit`, never into
     `submit_veto` (G23), so exits stay open. Reasons (closed enum):
     - registry: `registry_not_champion`, `registry_halted`, `registry_unreadable`,
       `registry_regressed`, `registry_restrictive_pending`;
     - dead-engine (Y3, Z4, Z5): `registry_attest_expired` (now past the family's newest ATTEST
       `attest_valid_until_ns`; armed for a family only once the chain holds an ATTEST for it,
       until then `registry_chain_stale` bounds it); `registry_engine_heartbeat_stale` (the
       intraday engine pass atomically rewrites `registry/heartbeat/<venue>.json`, 0444, with
       `ts_ns`, `invocation_id`, `engine_code_sha` and the verified chain head; the veto fires past
       `ENGINE_HEARTBEAT_STALE_S` ≈ 1 h, or when the named head is not on the verified chain);
       `registry_chain_stale` (chain-head age past H = 30 h, the backstop);
     - transient, node-local (Y1, Z13): `feed_stale`, `recorder_stale`, `permit_lapsed`,
       `capture_gap`, each from an in-node observation; `alerts_undeliverable` (no `delivered=true`
       canary row in the delivery journal within `ALERT_CANARY_MAX_AGE_H`; an absent or unreadable
       journal vetoes);
     - position (Y16): `rung_net_position_held`, from the predicate
       `rung_has_net_position(base_slug)` in `persistence/autonomy/entry_guard.py`, which reads
       durable exec-store fills read-only (G6 URI) and nets them with the leg sign (C2). It covers
       what the kind-scoped latch (G28) does not: the opposite leg and a successor family.
   - **Fail-closed start (Z6).** `entry_veto` returns `registry_unreadable` from construction until
     the first verified tick, and at call time whenever `last_verified_tick_age >
     WATCH_TICK_STALE_S` (3 × 60 s). Test `test_entry_veto_closed_before_first_tick_and_on_stale_tick`.
   - Every reason except `registry_not_champion` and `registry_halted` **auto-clears** on the next
     good observation;
     `registry_unreadable` and `registry_regressed` clear **only after a verified read**. A
     node-local veto writes no registry row, sets no HALTED state and spends no damping budget (Y1).
     It writes a C1 `EntryVeto` record and alerts on the transition.
   - The timer never raises (L-16); an exception sets `registry_unreadable`.
3. **Registry children** live at `~/.local/share/breezy/registry/families/<id>.json` (0444, single
   read), with artefacts content-addressed beside them. This takes one reviewed L-12 widening of
   the containment at four sites (`family_manifest.py:169,266-282`, `app/trade.py:122`,
   `settings.py:183`, `settings.py:366-388`), keeping `resolve()` and the `..` and absolute
   refusals, adding `lstat`/`O_NOFOLLOW` with a symlink RED test. Child ids `<root>_r<NNNN>` match
   both id regexes (`settings.py:115`; `trial_day_latch.py:301`).

**Demotion latency (Y1).** Two paths, two SLOs:
- **Transient, node-local:** the in-node observation to `entry_veto` is at most one detector period
  plus one 60 s tick (≤ 2 min).
- **Verdict-driven:** an intraday producer (`breezy-autonomy-producer-intraday`, its own oneshot,
  5 min timer) turns `DetectorEvent` records into C4 verdicts; the **intraday engine pass** (5 min
  timer, offset 150 s after the producer's; no `.path` unit, because one does not watch the nested
  `derived/verdicts/<family>/<date>/` leaves; Z12) runs in a **restrictive-only mode** that can write
  only DEMOTE, HALT and SWAP_CANCEL (code-enforced), and stamps the heartbeat; the watch actor picks
  the row up on its next tick. SLO: DetectorEvent to entry veto ≤ 15 min. If the engine is dead, the
  heartbeat veto bounds exposure at about 1 h and H is the backstop.
- `test_demotion_latency_slo` drives both paths under a fake clock; `test_intraday_engine_is_restrictive_only`.

**Exec-store halt mirror.** The engine mirrors exec-store halts read-only. Fixed mapping:

| Exec-store reason (G20) | Cause class | Registry effect |
|---|---|---|
| `duplicate_fill`, `ambiguous_exit` | INTEGRITY | HALTED; the venue is frozen for PROMOTE, RESUME and ROLLBACK until the operator CLI clears it (L-48) |
| legacy key `halts_all` | INTEGRITY | Same, for every family on the venue |
| legacy key `attributable_to_v4` | (none; v4 is seeded RETIRED) | No venue freeze |
| `policy_halt`, detail `fee_schedule_drift` | TERMINAL | HALTED → RETIRED; lineage `terminal_frozen`. θ is part of the estimand and §4.2 forbids a child from changing it |
| `policy_halt`, any other detail (A1 CLI) | TERMINAL | HALTED → RETIRED; lineage `terminal_frozen` |
| A read failure or an unknown payload | INTEGRITY | No non-restrictive transition that run; persisting past H, HALTED/INTEGRITY |

- **RECOVERABLE causes never use the exec-store halt.** Transient conditions are node-local vetoes
  (above). RECOVERABLE registry DEMOTEs are verdict-driven: a `DRIFT` or `HEALTH` FAIL the policy
  maps to DEMOTE, including a transient condition that persists past its policy horizon, and the
  drill's `DRILL_INJECT`. Fee drift stays exec-store-halting, unchanged.
- **Cause classes (Z10).** `RECOVERABLE_MODEL` (forecast and calibration drift, fill-rate and
  slippage, live sequential, `DRILL_INJECT`) consumes `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D`
  and escalates to TERMINAL. `RECOVERABLE_INFRA` (freshness, permit and process liveness, unit
  health, capture, delivery) never consumes it; its own `MAX_INFRA_RESUMES_PER_VENUE_7D`, once
  exhausted, ends in HALTED with an INTEGRITY freeze and a CRITICAL, never RETIRE or
  `terminal_frozen`. The policy block maps each detector to one class
  (`test_infra_cause_never_retires`).

**Relationship to existing controls.** A node may send only if all hold: the resolver says
CHAMPION, `entry_veto` is clear, the exec-store halt is clear (G5), the live-orders gate passes
(G4), a permit exists, and the caps admit the order. The registry adds vetoes. Only PROMOTE,
DRILL_PROMOTE, RESUME and ROLLBACK widen, only within §4.2. The registry never writes the exec
store. The daily budget stays **venue-scoped** (G21), seeded from durable fills at boot; drill fills
spend the same budget, and a change of sender never resets it (Z18;
`test_swap_cannot_exceed_daily_budget_across_namespaces`, `test_drill_fills_spend_venue_budget`).

**Failure behaviour.** Any registry failure gives an entry veto and **no permit-bearing
composition**; there is **no fallback to the lineage root**. At LAUNCH the node composes no sending
family, the supervisor raises a CRITICAL `REGISTRY_UNAVAILABLE` alert and retries the resolve until
17:00Z, and C1 marks the day `CAPTURE_INCOMPLETE(registry_unavailable)`. Tape capture is a separate
unit and continues. `test_registry_unavailable_mints_no_permit` pins this.

**Bootstrap.** BOOTSTRAP rows from the committed manifests: `pm_us_crh_fq_v1` → CHAMPION;
`pm_us_crh_v4`, `pm_us_crh_cont` and `pm_us_crh_v2` → RETIRED (never HALTED, so they cannot freeze
the venue). DRAFT manifests are not seeded.

### C6 — Family plug-in contract (owned here; implemented per kind by AUT-1, 2, 4 and 6)

Protocols in `persistence/autonomy/plugin.py`:

| Member | Layer | Signature (sketch) | Output |
|---|---|---|---|
| `CaptureAdapter` | strategy | `decision_record(decision, ctx)`; `order_tags(decision_id)` | C1 |
| `Scorer` | analysis | `label(capture_day, exec_fills, settlements)` | C2 |
| `Evaluator` | analysis | `offline(candidate, champion)`; `forward_shadow(candidate, champion, tape)`; `live(labels)` | C4 |
| `DriftDetectors` | both | `tuple[Detector, ...]`, each with `id`, `kind` (`NODE_LOCAL` \| `VERDICT`) and `evaluate(...)` | `EntryVeto` or C4 |
| `Refitter` | analysis | `refit(windows) -> (artefact, Lineage)`, or `NOT_FITTABLE` | C3 |

- **Registries:** `NODE_PLUGINS` (strategy layer) and `OFFLINE_PLUGINS` (analysis layer), keyed by
  `CompositionKind` (`family_manifest.py:115-121`).
- **YAGNI.** A kind with no non-RETIRED family registers `RefusingPlugin`, which refuses mint and
  compose: today `current_rung_hold`, `continuous_rung_hold`, `forecast_ladder`. A kind gets full
  plug-ins in the same change that admits it to `LIVE_GATE_ROUTED_KINDS`.
- **Gate tests:** `set(NODE_PLUGINS) == set(OFFLINE_PLUGINS) == _COMPOSITION_KINDS`; every
  non-RETIRED manifest resolves to full plug-ins; a `RefusingPlugin` kind never reaches SHADOW.
- **Runtime:** `_compose_family` (`app/trade.py:853`) refuses boot when the plug-in is missing or
  refusing; the engine refuses ∅→SHADOW and any →CHAMPION with incomplete or refusing plug-ins.
- **Required detector classes per kind:** freshness, forecast drift, calibration drift, fill-rate
  and slippage, fee and shape drift, permit and process liveness, unit health. Removing one fails
  the gate. A `VERDICT` detector's action class comes from the policy map, never from the detector.
  A `NODE_LOCAL` detector's action is fixed in code as `ENTRY_VETO` (restrictive only; the policy
  may escalate a persisting condition through a `VERDICT` detector, never loosen it).
- **`DRILL_INJECT` (Y2)** is a dedicated `VERDICT` detector id. A pinned detector reads the drill
  marker `registry/drill/marker.json` (written only by the engine under the active drill clause,
  single-read rule). It emits FAIL while the marker exists and **PASS when it is absent** (Z2); the
  engine removes the marker once the DEMOTE row commits, so the cause verdict PASSes and RESUME can
  follow. The policy maps `DRILL_INJECT → DEMOTE` **only while the drill clause is active**; outside
  it the engine treats the verdict as `ERROR`.

## 4. Autonomy safety envelope

### 4.1 Allowed and forbidden

**The bot may, on its own:** mint SHADOW children of an allowlisted root; refit, evaluate and
detect; write C1–C4; make the C5 transitions; veto entries, demote or halt at any time; and promote,
resume or roll back only under §4.2–§4.5.

**The bot never touches:** (1) the two caps (G18); (2) master enablement
(`breezy-trade-supervisor.service:120-121`); (3) the permit mechanism and its minting authority;
(4) the NO-SEND firewall; (5) `allow_short=False`; (6) the code allowlists, ceilings and sha pins;
(7) the policy ruling; (8) unit files and their environment (Y21). Items 6–8 change only through a
reviewed commit or a ruling under `docs/evidence/`, never through the engine. Of all these, only
the caps are an operator decision.

### 4.2 Authorisation without a commit per promotion
- **One reviewed widening (L-12).** `live_orders_gate.py` gains a code-committed
  `_LINEAGE_POLICY_ALLOWLIST` of `(root_family_id, policy_ruling_id, policy_ruling_sha256)`
  triples. `test_lineage_policy_allowlist_is_literal_only` pins both allowlists as literal-only
  tuples of string constants. At every LAUNCH the node re-hashes the deploy copy under
  `deploy/families/rulings/` (as G4 does) and refuses on mismatch.
- **Manifest equality.** A child equals its committed root on **every** key except: `family_id`,
  `trial_id_prefix`, `d0_climate_day`, `density_artefact_path`, `density_artefact_sha256` and
  `live_orders_ruling` (which must name the policy ruling). That covers every size and price knob,
  `stations`, `taker_fee_coefficient`, `exit_rule`, `no_leg_exit` and the boundary artefact.
  Recalibration forms live in the artefact, bounded by the loader (G11). `exit_gate.py` (G17) stays
  code-only (`test_exit_gate_stays_code_only`).
- **Live-gate routing.** Only kinds in `LIVE_GATE_ROUTED_KINDS` can be CHAMPION, through both the
  resolver and the engine (`test_registry_champion_requires_live_orders_gate_for_every_kind`).
- **The policy ruling** pre-registers every threshold (WP-26 criteria 1–6 as the base), the C4
  forward-shadow predicates and their units, α_total, K_max, the `detector → action_class` map,
  the RECOVERABLE and TERMINAL classes and their horizons, the drawdown limit, rate limits, damping
  (§4.5), the accepted C4 `assumptions`, and the drill clause. It explicitly supersedes D11 for
  allowlisted lineages, as the parent ruling §3 permits.
- **Machine-readable block (Y22).** The ruling contains exactly one fenced block tagged
  `autonomy-policy/v1` (strict JSON, exact-set keys). It is inside the file, so the pinned
  `policy_ruling_sha256` covers it. The engine reads values only from this block in the sha-pinned
  copy. `test_policy_block_not_looser_than_code_ceilings` parses the deploy copy and rejects any
  value looser than a `pins.py` ceiling (§4.5) or any unknown key.
- **Forward-shadow feasibility (Y12).** The block carries a feasibility record: `n_min` (in
  independent station-days), the measured rate of replay-sufficient qualifying station-days per day
  and its source, the MDE at α_K, and `eta_date`. `promote_enabled` (CHALLENGER→CHAMPION by
  PROMOTE) may be `true` only if `eta_date` is before the 2027-01-25 KILL; the test enforces this.
  Otherwise `promote_enabled=false`, and PROMOTE is **machinery-proven by the drill only** (§7).
  DRILL_PROMOTE, ROLLBACK, RESUME and all restrictive transitions are unaffected.

### 4.3 Code identity pins (Y17)
- `persistence/autonomy/pins.py` holds literal-only sets: `ENGINE_SOURCE_SHA256` and
  `PRODUCER_SOURCE_SHA256[producer_id]`.
- Each pin is the sha256 over the sorted `(module_name, bytes)` of the **transitive `breezy.*`
  import closure** of that component's entry module, excluding `pins.py`. The gate test computes
  the closure from the import graph (grimp, the engine behind `lint-imports`), so an edit to any
  imported helper forces a reviewed pin update in the same commit.
- The engine and each producer compute their own closure hash at start, refuse to run if unpinned,
  and stamp it into every transition or verdict. The node checks the authorising row's
  `engine_code_sha` at LAUNCH.
- **Append-only (Z9).** A rotation adds the new sha and keeps the old ones, so historical rows still
  verify. Removing a pin is a revocation (rows it authorised stop resolving), done only by moving it
  to the literal `REVOKED_SOURCE_SHA256` in the same reviewed commit
  (`test_engine_pin_history_retained`).

### 4.4 Promotion preconditions and launch (Y15)
**Preconditions.** PROMOTE, DRILL_PROMOTE, SUPERSEDE, DISPLACED, ACTIVATE, RESUME and ROLLBACK all
require: no OPEN or AMBIGUOUS submit intent in the exec store (read-only, the G30 probe); an
accepted `RECONCILIATION` PASS within its horizon (venue net equals ledger per base slug, C2); and
no INTEGRITY freeze on the venue. Flatness is **not** required: a demoted or superseded family holds
its positions to settlement (FQ has no exit, G17; autonomy never widens the exit allowlist), and the
successor is protected by `rung_net_position_held` (C5).

**Re-check at launch without a deadlock.**
- The **pre-launch engine pass** (16:45Z, after STOP, when no node runs) re-runs the preconditions
  for any pair pending for today's LAUNCH. Pass → `ACTIVATE`; fail → `SWAP_CANCEL`. A pair with
  neither lapses at LAUNCH (C5 fold), so a dead engine also leaves the incumbent in place.
- The supervisor re-runs the same read-only checks at LAUNCH. If they fail while an ACTIVATE stands,
  it raises CRITICAL, launches nothing, triggers the intraday engine pass (its `SWAP_CANCEL` voids
  the pair retroactively, Z8), and retries the resolve until 17:00Z, launching the restored incumbent.
- Preconditions gate **only a change of sender**, never the incumbent's own boot: an incumbent with
  an AMBIGUOUS intent boots through today's path unchanged (G30; `reconcile_at_startup`), so no new
  launch-deadlock surface. Tests `test_promotion_requires_reconciled_state` (net equals ledger,
  non-flat allowed); `test_ambiguous_intent_cancels_swap_not_incumbent_launch`.

### 4.5 Damping and code ceilings (Y13, Y18, Y21)
All ceilings are literal constants in `pins.py`, changed only by a reviewed commit. The policy block
may be stricter, never looser (Y22 test).

| Constant | Ceiling |
|---|---|
| `RESUME_COOLDOWN_H` | ≥ 24 |
| `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` | ≤ 2 RECOVERABLE_MODEL resumes, then the cause becomes TERMINAL |
| `MAX_INFRA_RESUMES_PER_VENUE_7D` (Z10) | ≤ 3, then HALTED/INTEGRITY with a CRITICAL, never RETIRE |
| `MAX_ROLLBACKS_PER_VENUE_30D` | ≤ 2, then a rollback trigger HALTs |
| `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` (Z3) | ≤ 2 logical changes (counting rule below) |
| `MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE` (M) | ≥ 14 |
| `MAX_CANDIDATES_PER_LINEAGE_PER_FORWARD_WINDOW` (K_max) | ≤ 4 |
| `MAX_MINTS_PER_LINEAGE_PER_DAY` | ≤ 1 |
| `DRILL_BUDGET_PER_VENUE_30D` | ≤ 1 drill (one DRILL_PROMOTE, one DRILL resume, one DRILL rollback); separate from production counters |
| `DEADMAN_HORIZON_H` (H) | ≤ 30 (24 h engine period + 6 h slack) |
| `MAX_VERDICT_VALIDITY_H` (Z4) | ≤ 26 (24 h + 2 h slack); the engine rejects longer verdicts as `ERROR` |
| `ENGINE_HEARTBEAT_STALE_S` (Z4) | ≤ 3600 |
| `WATCH_TICK_STALE_S` (Z6) | ≤ 180 (3 × 60 s tick) |
| `ALERT_CANARY_MAX_AGE_H` (Z13) | ≤ 26 |
| `DEMAND_FILE_MAX_BYTES`; `DEMAND_FILES_MAX` (Z11) | ≤ 4096; ≤ 64 per venue |
| `SELF_HEAL_RESTARTABLE_UNITS` | literal tuple of unit names; never the supervisor, the trade node or the engine; restart only, no unit-file or env edits |
| `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` (Z15) | ≤ 3, then alert only |

**Counting (Z3).** One logical change of sender (the →CHAMPION row, its SUPERSEDE or DISPLACED
partner and its ACTIVATE) counts 1; a RESUME counts 1. MINT, SHADOW→CHALLENGER, ATTEST, HWM_RESET
and restrictive rows never count. Drill-episode rows (DRILL_ADMIT, the DRILL_PROMOTE pair, the
episode's RESUME and ROLLBACK) count only against the drill budget. Every counter (daily cap, M,
rollbacks, resumes, drill budget) is charged when the change **takes effect**; the engine treats
pending pairs as reservations when it proposes, and a lapsed or cancelled pair is never charged.

Never a rollback to a `demoted_for_cause` family. Tests: `test_damping_ceilings` (pins the counting
rule), `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` (AST: the restart call site
takes only members of the tuple, as an argv list `["systemctl", "--user", "restart", unit]`, never
`shell=True`, within the per-unit daily count; the tuple contains no `breezy-trade*` or
`breezy-autonomy-engine*` name; no autonomy module writes under `~/.config/systemd` or
`~/.config/breezy`).

### 4.6 External watch and delivery proof (Y3, Y11)
- **Dead-man.** `breezy-autonomy-deadman.timer` (every 30 min), its own unit and lock, reads the
  heartbeat file and the per-venue chain-head age and raises CRITICAL past
  `ENGINE_HEARTBEAT_STALE_S` and again past H. The node enforces
  the same horizon independently (`registry_chain_stale`, `registry_attest_expired`).
- **Delivery-proof API (AUT-6).** `deliver_with_proof(sink, payload) -> DeliveryProof` in
  `runtime/alert_delivery.py`. It calls `emit` **directly on the webhook branch** (via
  `TeeAlertSink.sinks`), never through `emit_alert` or the tee, because both swallow failure (G25).
  Proof is an HTTP 2xx (`WebhookAlertSink.emit` raises otherwise). Each attempt is journaled to
  `evidence/alerts/delivery_<date>.jsonl` (`event`, `ts_ns`, `delivered`, `status_class`; no URL,
  no exception message). It uses the existing `alerts.env` key only (G27); no new egress host.
  **Every CRITICAL** (Z13), from autonomy writers and from the existing node CRITICAL sites that
  AUT-6 migrates and lists, goes through it; WARNING and INFO keep `emit_alert`. The node-local
  `alerts_undeliverable` veto (C5) reads this journal.
- **Off-host heartbeat.** A daily 15:45Z `autonomy_canary` goes through `deliver_with_proof` to the
  same endpoint, whose absence rule pages if none arrives by 16:15Z (dead host or broken egress).
  Receiver support is **INFERRED**; AUT-6 proves it live by suppressing one canary. Otherwise a new
  heartbeat endpoint is a reviewed alert-egress change re-pinning `test_autonomy_alert_egress_not_widened`.
- A failed delivery of a CRITICAL is retried on the next tick and journaled; a `DeliveryProof`
  failure on the canary is itself a `HEALTH` FAIL.

### 4.7 Envelope tests (RED first, in the gate)

**Existing tests, unweakened:** `test_operator_control_assignment_scan`,
`test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`,
`test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`,
`test_risk_engine_ordering_enforcement`.

| New test | Pins |
|---|---|
| `test_autonomy_never_reads_or_writes_operator_controls` | AST scan, tokens from `OPERATOR_RESERVED_CONTROL_ENV_VARS` |
| `test_autonomy_never_touches_enablement_permit_or_firewall`; `test_autonomy_never_imports_order_path`; `test_autonomy_alert_egress_not_widened` | §4.1 |
| `test_registry_transition_table_is_exact`; `test_registry_cas_and_idempotent_replay`; `test_registry_hash_chain_and_triggers`; `test_repeat_supersede_same_family_is_not_replay` | C5 table, Y9, Y20 |
| `test_registry_readonly_open_engine_stopped`; `test_resolver_binds_bytes_to_row`; `test_verdict_subject_sha_must_match_row` | Y5, Y6 |
| `test_hand_relaunch_without_registry_source_refused`; `test_family_source_fixed_in_unit`; `test_terminal_halt_freezes_lineage` | Y7, Y10 |
| `test_demote_during_pending_swap_incoming`; `…_outgoing`; `test_resume_refused_while_swap_pending`; `test_unactivated_pair_lapses_at_launch` | Y8 |
| `test_watch_actor_never_reads_projection`; `test_registry_hwm_refuses_regression`; `test_registry_unreadable_veto_clears_only_after_verified_read`; `test_attest_expiry_and_chain_staleness_veto_entries` | Y4, Y3 |
| `test_demotion_latency_slo`; `test_intraday_engine_is_restrictive_only`; `test_transient_veto_writes_no_transition`; `test_restrictive_commit_failure_sets_node_veto` | Y1, Y19 |
| `test_drill_promote_refuses_non_champion_sha`; `test_drill_inject_mapped_only_in_clause`; `test_drill_fills_excluded_from_n_and_kill_clock`; `test_drill_budget_separate` | Y2 |
| `test_rung_net_position_veto_crosses_legs_and_families`; `test_code_identity_pins_cover_import_closure`; `test_lineage_policy_allowlist_is_literal_only` | Y16, Y17, §4.2 |
| `test_policy_block_not_looser_than_code_ceilings`; `test_promote_disabled_when_eta_after_kill` | Y22, Y12 |
| `test_damping_ceilings`; `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` | Y18, Y21 |
| `test_candidate_cap_and_mint_rate`; `test_deliver_with_proof_reports_non_2xx_through_tee` | Y13, Y11 |
| `test_promotion_requires_reconciled_state`; `test_ambiguous_intent_cancels_swap_not_incumbent_launch` | Y15 |
| `test_child_manifest_equals_committed_root_except_allowlist`; `test_exit_gate_stays_code_only`; `test_registry_paths_refuse_symlinks`; `test_verify_and_load_share_bytes` | §4.2, single read |
| `test_registry_unavailable_mints_no_permit`; `test_swap_cannot_exceed_daily_budget_across_namespaces` | C5 failure, G21 |
| `test_verdict_acceptance_rules`; `test_halt_reason_class_map_is_exact`; `test_mirror_read_failure_is_integrity`; `test_autonomy_payload_hygiene_scan` | C4, mirror, hygiene |
| `test_verdict_accepted_after_attest`; `test_family_artefact_binding_immutable`; `test_attest_veto_armed_after_first_attest`; `test_engine_heartbeat_stale_vetoes`; `test_verdict_validity_ceiling` | Z1, Z4, Z5 |
| `test_drill_flag_spans_promote_to_rollback`; `test_drill_admit_charges_only_drill_budget`; `test_drill_inject_passes_when_marker_absent` | Z2 |
| `test_entry_veto_closed_before_first_tick_and_on_stale_tick`; `test_watch_actor_store_touches_stay_on_loop_thread`; `test_autonomy_exec_keys_disjoint_from_halt_prefixes` | Z6, Z16 |
| `test_node_relaunch_rule_family_id_and_seq_prefix`; `test_halted_family_boots_entries_vetoed_exits_live`; `test_post_launch_swap_cancel_restores_incumbent` | Z7, Z8 |
| `test_engine_pin_history_retained`; `test_infra_cause_never_retires`; `test_bad_demand_file_vetoes_venue`; `test_hwm_reset_cli_journals_alerts_and_chains` | Z9, Z10, Z11, Z17 |
| `test_critical_alerts_use_delivery_proof`; `test_alerts_undeliverable_veto`; `test_reconciliation_and_entry_guard_never_read_canary_store`; `test_drill_fills_spend_venue_budget` | Z13, Z14, Z18 |
| `test_demotion_never_requires_policy_and_is_immediate`; `test_registry_veto_leaves_exit_seam_open`; `test_family_plugin_exact_set`; `test_rollback_restores_byte_identical_artefact` | Entry-only demotion, C6, AUT-7 |

## 5. Area boundaries, sequencing and live proof

| Area | Owns | Writes |
|---|---|---|
| AUT-1 | `CaptureAdapter` per kind, the `decision_id` tag, link and lifecycle writers, `DetectorEvent`, the completeness audit, recorder and feed stall self-heal (restart via the allowlist) | C1; C4 `HEALTH` |
| AUT-2 | `Scorer` per kind; the label store; net-position reconciliation; the −0.37/+0.37 root cause; tallies and ROI | C2; C4 `RECONCILIATION` |
| AUT-3 | `Refitter` per kind; refit timers; the C3 writer; leakage, ablation and reproducibility checks; the G11 widening | C3 |
| AUT-4 | `Evaluator` per kind: offline, forward shadow, live sequential; α and K_max accounting; feasibility measurement | C4 |
| AUT-5 | The C5 store, chain, fold and resolver; the engine (daily, intraday, pre-launch); the policy ruling and block; `RegistryWatchActor` and `entry_guard`; supervisor and node wiring; the allowlist widening; pins; the dead-man; bootstrap | C5 |
| AUT-6 | `DriftDetectors` per kind (node-local and verdict); the intraday producer; liveness; unit health and the five failing units; `deliver_with_proof`, canary and off-host heartbeat; `RuntimeMaxSec` on every study | C4 `DRIFT`, `HEALTH` |
| AUT-7 | Rollback-target selection and ROLLBACK through the C5 API; the gate drill (AUT-7a); the live drill (AUT-7b) | C5 through the engine |

### 5.1 Build sequence
- **Wave 0 (ARCH-0, serial).** `persistence/autonomy/`: schemas, the C5 store (chain, triggers, CAS,
  fold, rollback journal), the resolver, `entry_guard`, `pins.py` with ceilings, the C6 Protocols
  and `RefusingPlugin`. All §4.7 tests start RED. `lint-imports` must report "N kept, 0 broken"
  (console script, run from the tree). Size M, independent review.
- **Wave 1 (parallel, against the stubs only):** AUT-1; AUT-6; AUT-5a (store wiring, watch actor,
  resolver at LAUNCH, bootstrap, restrictive-only engine and heartbeat, ATTEST, dead-man, relaunch
  helper); AUT-7a; AUT-2a (FQ scorer over the exec store, plus the root cause). `app/trade.py`,
  `settings.py` and `trade_supervisor*.py` belong to AUT-5a alone.
  - **Bootstrap of the dead-engine vetoes (Z5).** Until a family's first ATTEST row,
    `registry_attest_expired` is unarmed for it and `registry_chain_stale` bounds it
    (`test_attest_veto_armed_after_first_attest`). `alerts_undeliverable` is enabled only after
    AUT-6's canary has journaled its first `delivered=true` row, because an absent journal vetoes.
- **Wave 2:** AUT-2b (`decision_id` join, NO-leg and exit labels); AUT-3 (external refits may start
  in Wave 1; `rung_recalibration` follows C2); AUT-4 live sequential.
- **Wave 3:** AUT-4 offline and forward shadow with the feasibility record; AUT-5b (policy ruling
  peer-reviewed and filed, the allowlist widening, then DRILL_PROMOTE, RESUME, ROLLBACK, and PROMOTE
  only if `promote_enabled`); AUT-7b.
- **Gate discipline:** the full gate after every merge (L-43), `scripts/ci/run_tests_no_egress.sh`
  with the exact interpreter. Never `uv` (L-51).

### 5.2 Scheduling rules (Y23)
- **Locks.** Studies (label, detectors, refit, rerun, evaluation) take `breezy-studies.lock`
  (`flock -w <W>`) in `breezy-studies.slice` with `OnFailure=breezy-study-failed@` and a
  no-progress stall event. Engine (all modes), intraday producer and dead-man take their own locks,
  never the studies flock, so a long study never delays a demotion.
- **Runtime bound.** Every study sets `RuntimeMaxSec` such that scheduled start + `W` +
  `RuntimeMaxSec` ends before 16:30Z, so no study can run into STOP/LAUNCH. G29: no unit sets it
  today; AUT-6 adds it to every existing study unit as well.
- **Memory.** On the 30 GiB host (G29): one studies-flock holder at a time, `MemoryMax ≤ 16G`;
  own-lock autonomy units together ≤ 4G; ≥ 10G left for trade node, recorder and OS. A study needing
  more runs outside the live window and stops for the node, never the reverse. "Heavy" (> 4G) jobs
  never start 01:00–04:30Z (`WORK_BREAKDOWN:512`).
- Indicative slots (AUT-n plans fix the rows): label 05:00, offline detectors 05:30, refit 06:00
  (16G), reproducibility rerun on a 10% sample 09:30 (12G), offline and forward shadow 11:00 (12G),
  live sequential 14:45, daily engine 15:30 (writes pending pairs and ATTEST), canary 15:45,
  pre-launch pass 16:45, intraday producer every 5 min with the intraday engine 150 s after it
  (Z12), dead-man every 30 min.

### 5.3 Live-proof evidence rules
- **Qualifying days.** A day counts toward any 7-day window only with at least 1 real fill, or a
  `source=canary` synthetic fill traversing the production capture and label code. Zero-fill days
  extend the window. Every window also needs **at least 5 real fills**; canary and drill fills never
  count toward that or any statistic.
- **Canary store (Z14).** Canary fills live in `derived/canary/`, never the exec store, with their
  own `Scorer` input; reconciliation and `entry_guard` never read it
  (`test_reconciliation_and_entry_guard_never_read_canary_store`).
- **Honest evidence class.** Each DONE claim states "machinery proven, edge unproven" unless a
  pre-registered edge verdict passed.
- **AUT-7b drill contract (Y2).** The drill runs through the production engine under the policy's
  pinned drill clause and proves DRILL_ADMIT, DRILL_PROMOTE, DEMOTE (through `DRILL_INJECT` and the live
  producer→engine→watch-actor path), RESUME and ROLLBACK with the sha re-verified, using a
  byte-identical child (C3 no-new-lineage rule). It spends only the drill budget; its fills, from
  DRILL_PROMOTE through the closing ROLLBACK, carry `drill=true` and are excluded from
  live-sequential n and the KILL clock, but spend the venue daily budget (Z18). The permit may be live or
  withheld, and its authority is untouched. Clock: at least 4 trading days. Steps and timing: §10.
- **After the 2027-01-25 KILL.** If it fires TERMINAL, the champion RETIREs, the lineage is
  `terminal_frozen`, and the venue has no sender until a reviewed commit adds a lineage root.
  Capture, labels, refits and evaluation continue; fill-dependent windows pause and extend.

## 6. Reuse map (extend these, never rebuild them)

| Need | Reuse | Where |
|---|---|---|
| Manifest strictness, raw-byte sha | `load_family_manifest` (widen containment only) | `family_manifest.py:285-296` |
| Real-order authorisation | `live_orders_authorized` (add the lineage allowlist) | `live_orders_gate.py:130-190` |
| Integrity halt; read-only reader | `record_*`, `family_halt_state`, `read_family_halt_rows_readonly` | `trial_day_latch.py:1004,1118,1155,1193,354` |
| Entry guard slot | `try_submit` (add `entry_veto` beside `submit_veto`) | `fq/strategy.py:629-643` |
| In-node periodic actor | `FeeDriftProbeActor` pattern | `app/trade.py:442-484` |
| Order tags; order→fill join | exit tag prefixes; `FILL_*` keys | `exit_tags.py`; `exec/client.py:400-447` |
| Open-intent probe | `probe_open_intent` | `trade_supervisor.py:402` |
| Decision JSONL and retention | `decisions/`, `OfferTape`, funnel actor | `crh/composition.py:568-602` |
| Label store and scoring | `scored_trial_store`; `ScoredTrial`, `ScoreRefusal` | `scored_trial_store.py:24-31`; `trial_scorer.py:131-160` |
| Bootstrap, sequential looks | `roi_bound` constants; `run_sequential_looks` | `roi_bound.py:93-100`; `family_tally_v2.py:625` |
| Promotion predicates | `evaluate_c_*`, `assemble_outcome` | `promotion_criteria.py:195-613` |
| Fitters and holdout | `fit_calibration`, `open_holdout`, `compute_n_min`, `write_artefact` | `nbp_calibration.py:1280,353,309,2643` |
| Market baseline; calibration leg | `wp7b_market_as_forecaster`; `evaluate_calibration_leg` | `scripts/analysis/…:1128`; `forecast_conditional_scoring.py:392` |
| Drift and freshness | `check_freshness`, `check_drift` | `nbp_learning_nightly.py:286,342` |
| Alerts; delivery proof | `resolve_alert_sink`, `emit_alert`, `AlertPayload`; the `check_alerts_cli` direct-emit pattern on the webhook branch | `health.py:392,479,362`; `check_alerts_cli.py:19-23` |

## 7. Risks

| Risk | Mitigation built into the contracts |
|---|---|
| **Statistical capacity.** About 5 fills a day, admissible n = 0; a child restarts its clock (L-34). | Promotion rests on offline evidence plus a forward shadow counted in independent station-days, never on a child's live n. Live sequential demotes. |
| **Forward shadow may be unreachable before the KILL (Y12).** Replay-sufficient tape days are scarce (memory note `quote-tape-is-not-replay-sufficient`). | The feasibility record gates `promote_enabled`. If `eta_date` ≥ 2027-01-25, **PROMOTE is machinery-proven by the drill only**: the AUT-5 live proof stands on DRILL_PROMOTE, and no edge-based promotion is claimed. |
| **Slippage proxy** | Champion slippage for a different policy is a declared assumption; without the ruling's acceptance the verdict is INCONCLUSIVE. |
| **Forecast edge closed (09-20).** | Promotion requires beating the market-implied baseline on the traded rung, net of fee and slippage. |
| **Multiple testing under daily refit (Y13)** | Rolling forward holdout; sealed holdout once per lineage; α_k halving; K_max and mint-rate ceilings; MDE at α_K stated. |
| **Train/serve skew; leakage** | `forecast_input_sha256` per decision; a parity verdict maps to DEMOTE; C3 assertions refuse a lineage write. |
| **Demotion latency (Y1)** | Node-local vetoes ≤ 2 min; verdict-driven ≤ 12 min; a dead engine is bounded at H by node-side vetoes. |
| **Halt strands positions** | Entry-only demotion; the exec-store halt is reserved for INTEGRITY and TERMINAL; a demoted family holds to settlement. |
| **Registry tamper, revert or SPOF** | Per-venue chain, triggers, export, node HWM, byte binding, pins; any failure gives no sender, never a fallback. |
| **Alerts reach nobody** | Delivery proof by 2xx; off-host absence rule on the canary. |
| **Oscillation; drill contamination** | §4.5 ceilings and counting rule; separate drill budget; drill fills excluded. |
| **Promotion starvation (Z19).** An AMBIGUOUS intent open at 16:45Z cancels the day's swap (§4.4). | AUT-2 measures how often one is open at 16:45Z; a high rate is a finding for the AMBIGUOUS-resolution path, never a relaxation of §4.4. |
| **False-positive DRIFT (Z20).** A spurious `RECOVERABLE_MODEL` DEMOTE can exhaust the resume budget and freeze a lineage. | **Accepted cost**: fail-closed over availability. Recovery is a reviewed new lineage root. |
| **Concurrent agents; venv; memory** | Disjoint Wave 1 ownership, per-agent scratchpads, no `git stash`, no `uv`, re-gate per merge; §5.2 memory budget and own locks. |

## 8. Open decisions

OD-1..OD-5 stay settled (INTEGRITY freeze until CLI clear; activation at next LAUNCH; fee drift
TERMINAL; challengers judged offline and by forward shadow; refusals written on transition). **Left
to the AUT-5 policy ruling's peer review, not the operator:** α_total, K_max, M, forward-day and
station-day minimums, drawdown limit, per-detector horizons and cause classes, the drill window and
the §4.5 staleness values, each within its code ceiling.

## 9. Contradictions found (README and rulings versus code)

(1) The nightly fits nothing (G12): AUT-3 starts from the fitters. (2) "Demotion is fail-safe" holds
only for entry-only demotion; the exec-store halt blocks exits (G5). (3) Commit-free promotion
needs the one-time lineage allowlist widening (§4.2, G4). (4) The policy ruling must supersede D11
for allowlisted lineages. (5) One sender per node (G1): challengers are measured by forward shadow.
(6) Rollback needs the containment widening (C5). (7) CRH kinds send with no live-orders gate
(G19), so they are never CHAMPION until routed through it. (8) `breezy-check-alerts` likely reports
"delivered" on a failed webhook, emitting through the tee (G26); proof targets the webhook branch.

## 10. Area plan obligations

Each AUT-n plan must specify the following, consuming C1–C6 and §4 unchanged.

- **AUT-1:** the `CaptureAdapter` call sites per composable kind; measured C1 volume per day; the
  `EntryVeto` record writer; the node-local observations behind `feed_stale`, `recorder_stale`,
  `capture_gap` (source, period, clear condition); the recorder and feed self-heal restart, naming
  each unit it adds to `SELF_HEAL_RESTARTABLE_UNITS`; the daily join audit.
- **AUT-2:** the −0.37/+0.37 root cause with artefact evidence before any scorer change; the
  per-leg reconciliation tolerance; the RECONCILIATION verdict horizon used by §4.4; exclusion of
  `canary` and `drill` rows; the canary store's `Scorer` input (Z14); the label-lag alert; the
  measured rate of AMBIGUOUS intents open at 16:45Z (Z19).
- **AUT-3:** the refit cadence and windows; the mint path honouring `MAX_MINTS_PER_LINEAGE_PER_DAY`;
  the ablation and leakage assertions; the reproducibility sample; the G11 widening with parity
  tests; its unit's `MemoryMax`, `RuntimeMaxSec` and flock wait.
- **AUT-4:** the replay-sufficiency check that admits forward-shadow tape days; station-day
  clustering; the measured qualifying station-days per day; the feasibility record (`n_min`, MDE at
  α_K, `eta_date`) handed to the policy ruling; K_max accounting; the slippage source and its
  `assumptions` tag; the live-sequential producer over admissible labels.
- **AUT-5:** the policy ruling and its `autonomy-policy/v1` block (every key, every value within
  ceilings, drill clause and window, `attest_required_verdict_kinds`, detector cause classes); the
  engine's daily, intraday (restrictive-only, heartbeat) and pre-launch modes, staggered timers and
  lock; ATTEST cadence; the watch actor (loop-thread bridge) and `entry_guard` wiring per kind; HWM
  key handling and the `breezy-registry-hwm-reset` CLI; the demand directory; supervisor env
  handoff, the relaunch rule, the post-launch SWAP_CANCEL relaunch and the registry-aware
  `breezy-trade-relaunch` helper replacing the hand `systemd-run` runbook; the dead-man;
  bootstrap; the 15 min SLO test harness.
- **AUT-6:** the detector catalogue per kind, split `NODE_LOCAL` / `VERDICT`, each with horizon,
  policy action class and escalation path; the intraday producer; `deliver_with_proof`, its journal
  and the RED test proving G26; the migration of every CRITICAL site to it and the
  `alerts_undeliverable` observation; the canary, the receiver's absence rule and its live proof; the
  five failing units; `RuntimeMaxSec` for every study unit (G29); `SELF_HEAL_RESTARTABLE_UNITS`
  membership, the per-unit restart cap and the argv-only restart call site.
- **AUT-7:** rollback-target selection (most recent `rollback_eligible`, not `terminal_frozen`,
  bytes re-verified); failed rollback → HALT; the gate drill (AUT-7a); the live drill steps for
  AUT-7b — mint the byte-identical child `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage), DRILL_ADMIT
  it to CHALLENGER, DRILL_PROMOTE at LAUNCH, write the drill marker so `DRILL_INJECT` demotes it
  through the live path, remove the marker so the verdict PASSes, RESUME, ROLLBACK to `fq_v1` —
  with dates, the drill budget, and the evidence (chain, export, node log, delivery journal).

## §R4 Defect disposition (review `reviews/ARCH-r3-merged.md`)

Earlier rounds: X-ids in Rev 2 §R2 (snapshot `…/scratchpad/ARCH_rev2_8a9c89b7.md`); Y1–Y23 in Rev 3
§R3, 23 FIXED (snapshot `…/scratchpad/ARCH_rev3.md`, sha256 `66002f49…361af`), where `…` is
`/tmp/claude-1000/-home-jon-breezy/2a769d76-4e5c-4b60-a17d-c8cdb8a404e5`. **Z1–Z20: 20 FIXED,
0 REJECTED.** No README criterion changed.

| Z | Disposition | Where fixed / evidence |
|---|---|---|
| Z1 | FIXED | C4 engine acceptance: bound artefact sha from BOOTSTRAP/MINT, immutable per family id; tests |
| Z2 | FIXED | C5 `DRILL_ADMIT` row and counter; C6 `DRILL_INJECT` PASS on absent marker, engine removes it; C1 drill episode through the closing ROLLBACK; §4.5 counting; §5.3; §10 AUT-7 step |
| Z3 | FIXED | §4.5 `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` and counting rule (pair+ACTIVATE = 1; MINT, ATTEST, restrictive excluded; drill budget only; charged on effect); C5 fold |
| Z4 | FIXED | §4.5 `MAX_VERDICT_VALIDITY_H`, `ENGINE_HEARTBEAT_STALE_S`; C4 acceptance; ATTEST row refuses `> ts_ns + H`; heartbeat file and `registry_engine_heartbeat_stale`; H is the backstop |
| Z5 | FIXED | ATTEST row cites `attest_required_verdict_kinds`; `registry_attest_expired` armed after a family's first ATTEST (C5, §5.1); test |
| Z6 | FIXED | C5 fail-closed start and `WATCH_TICK_STALE_S`; test |
| Z7 | FIXED | C5 relaunch rule (family id, seq prefix, CHAMPION or HALTED; HALTED boots entries-vetoed, `registry_halted`); `breezy-trade-relaunch` in §10 AUT-5; tests |
| Z8 | FIXED | C5 fold post-launch SWAP_CANCEL; supervisor relaunch in the window; test |
| Z9 | FIXED | §4.3 append-only pins, `REVOKED_SOURCE_SHA256`; test |
| Z10 | FIXED | C5 cause classes; `MAX_INFRA_RESUMES_PER_VENUE_7D` → HALTED/INTEGRITY, never RETIRE; RESUME and RETIRE rows; test |
| Z11 | FIXED | C5 demand files per (venue, family, ts), single read, size cap, schema, venue-wide veto on a bad file, engine unlinks; §4.5 caps; test |
| Z12 | FIXED | C5 latency: `.path` unit dropped (does not watch nested leaves), staggered timers, SLO 15 min; §5.2; §10 |
| Z13 | FIXED | §4.6 every CRITICAL through `deliver_with_proof`; C5 `alerts_undeliverable` (26 h); §5.1 enable order; §10 AUT-6 |
| Z14 | FIXED | §5.3 separate canary store; C2 `Scorer` input in §10 AUT-2; test |
| Z15 | FIXED | §4.5 `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY`; argv-only restart under the AST test |
| Z16 | FIXED | Single-read list widened. **L-1 verdict: the timer does NOT run on the store's owning thread** (`_DummyThread`, `test_live_timer_thread_affinity.py:90-119`; `_check_thread` raises, `sqlite_store.py:128-135`), so C5 mandates the `run_coroutine_threadsafe` bridge (`fee_drift_probe.py:358-372`) and a loop-thread test. Mirror reads exact `continuous_rung_hold/` keys only (`trial_day_latch.py:291-295,354-379`): `autonomy/` ignored; test |
| Z17 | FIXED | C5 `HWM_RESET` row and `breezy-registry-hwm-reset` CLI (journal, CRITICAL, chain row); test |
| Z18 | FIXED | C5 relationship to existing controls: venue-scoped, seeded at boot, drill fills spend it; §5.3; test |
| Z19 | FIXED | §7 promotion-starvation risk; §10 AUT-2 measurement |
| Z20 | FIXED | C5 `paired_transition_id` null on the PROMOTE side; §7 accepted false-positive DRIFT cost |

# AUTONOMY_ARCHITECTURE — umbrella architecture for AUT-1..AUT-7 (2026-10-03, Rev 2)

**Status:** PLANNING, Rev 2 (Rev 1 scored 68; §R2 disposes X1–X29). Nothing here is implemented.
**Parent:** [README.md](README.md) (scale, score-3 criteria, binding constraints).
**Ruling:** `docs/evidence/RULING_operator_full_autonomy_2026-10-03.md`.
**Scope.** This document defines the shared contracts C1–C6, the autonomy safety envelope, the area
boundaries, the build order, the reuse map and the risks. Each AUT-n plan consumes the contracts
defined here and must not redefine them. A change to a contract is a change to this file, and it is
re-reviewed.
**Evidence tags.** `file:line` was checked at `4b8347a6`. **INFERRED** is unverified against running
code, and each such item clears its L-1 check before the slice that relies on it starts.

---

## 1. Goal state

Breezy runs one closed loop per venue, unattended. **Capture** (AUT-1) writes every decision,
refusal, intent, order, fill, cancel, mark and settlement for every family, joined on one
`decision_id`. **Label** (AUT-2) scores every fill against settlement and reconciles it at net
position within 24 h. **Refit** (AUT-3) mints lineage-complete candidates from rolling external
weather plus the bot's own labels. **Evaluate** (AUT-4) scores every candidate offline and on a
forward shadow against the champion and the market-implied baseline, and tests every live family
daily with the PREREG sequential tests, each result a C4 verdict. **Promote or demote** (AUT-5): a
policy engine executes one pre-registered policy ruling over those verdicts and writes hash-chained
C5 transitions, which the supervisor and node pick up with no commit. **Drift** (AUT-6) detectors
emit C4 verdicts that the policy maps to halt, demote, self-heal or alert. **Rollback** (AUT-7)
restores the last rollback-eligible champion at a byte-identical artefact sha, or halts the family.

Every area reaches score 3 by the same two levers:
- **Family-agnosticism by construction.** C6 makes a plug-in mandatory at registration, so no family
  can compose or send without one. A kind with no live family carries a `RefusingPlugin`, which
  refuses to mint or compose.
- **Fail-closed by contract.** Every consumer of C1–C5 treats a missing, stale, unparseable,
  unknown-version or unverifiable record as the restrictive outcome: no promotion, an entry stop, an
  alert.

All of this happens inside the operator's two caps and the already-enabled live envelope (§4).

---

## 2. Ground truth the design rests on (verified)

| # | Fact | Evidence |
|---|---|---|
| G1 | Each node composes exactly one sending family, chosen by `BREEZY_SENDING_FAMILY_ID` (currently `pm_us_crh_fq_v1`). | `runtime/settings.py:106,116-125`; `app/trade.py:930-962`; `breezy-trade-supervisor.service:128` |
| G2 | The supervisor forwards its environment to the child unchanged. The child loads `deploy/families/<id>.json` relative to the CWD. | `runtime/trade_supervisor.py:849-876`; `app/trade.py:122,962` |
| G3 | Manifests are strict exact-set. The manifest sha256 is taken over raw bytes read once. Artefact paths are confined to `deploy/families` with `resolve()`, `..` and absolute refusals. | `persistence/family_manifest.py:122-137,266-282,285-296` |
| G4 | Real orders need a code-committed allowlist triple `(family_id, ruling_id, ruling_sha256)` plus a ruling file whose sha is re-verified at every boot. | `persistence/live_orders_gate.py:76-84,130-190` |
| G5 | A family halt is a durable exec-store key. It is set "first cause wins" and cleared only by the operator CLI. It vetoes in the exec client and the exit seam. | `trial_day_latch.py:1155-1191,1246-1314`; `crh/composition.py:221-254` |
| G6 | Halt writes need the submit-intent flock, which the node holds for its life. Readers use a lock-free `mode=ro` URI. | `trial_day_latch.py:354-379`; `app/trade.py:983-986` |
| G7 | `SqliteStateStore` is a thread-confined KV BLOB store (WAL, `synchronous=FULL`) with no iteration. | `runtime/sqlite_store.py:117-176` |
| G8 | Scored trials are append-only parquet, deduped on `(trial_id, max score_seq)`. Rows carry no `family_id`, leg or probability. | `persistence/scored_trial_store.py:24-31,60-89` |
| G9 | FQ submits with no `Order.tags`. Exit orders carry authorisation in native `Order.tags`. | `fq/strategy.py:681-688`; `persistence/exit_tags.py:1-25` |
| G10 | The FQ funnel records counts only. The CRH offer tape is per-decision JSONL with a byte-capped sidecar. | `fq/decision_funnel.py:1-24`; `crh/offer_tape.py:335-412` |
| G11 | The live calibration loader refuses any `recalibration` other than `none`. | `fq/calibration_artefact.py:281-295` |
| G12 | `nbp_learning_nightly` scores a frozen artefact and does not fit. The fitters live in `nbp_calibration`. | `nbp_learning_nightly.py:921-1023`; `analysis/nbp_calibration.py:1166,1280` |
| G13 | Candidate artefacts must live outside the repo. | `nbp_learning_nightly.py:688-735` |
| G14 | The promotion generator is advisory only, and its criteria are PROVISIONAL. | `promotion_proposal.py:96-104`; `promotion_criteria.py:46-73` |
| G15 | `analysis` sits above `strategy`. Live packages never import `breezy.analysis`. `persistence` is importable by both. | `pyproject.toml:74-101,152-160` |
| G16 | In-node `Actor`s with clock timers already halt or alert. The fee probe calls `record_policy_halt` in-process. | `app/trade.py:442-484`; `fee_drift_probe.py:255,543` |
| G17 | Exit capability is a code allowlist containing only `pm_us_crh_exit_v4`. FQ has no exit. | `persistence/exit_gate.py:55-89` |
| G18 | The caps are read only from the environment, never defaulted, and pinned by an assignment scan. | `operator_controls.py:130-180`; `test_operator_control_assignment_scan.py` |
| G19 | **Only FQ composition calls the live-orders gate.** `current_rung_hold` and `continuous_rung_hold` hand `sending_permit` straight to their strategies. | `app/trade.py:546-571,575-673` (no gate call) vs `:740` |
| G20 | Exec-store halt payload reasons: `duplicate_fill` (`:1054`), `ambiguous_exit` (`:1144`) and `policy_halt` (`:1182`). `policy_halt` is written by the fee probe (detail `fee_schedule_drift`, `app/trade.py:271,465`) and by the set-halt CLI (A1, `set_family_halt_cli.py:503`). There is also the legacy key, pinned to v4 or `halts_all`. | `trial_day_latch.py:292-351` |
| G21 | The daily budget stop is **venue-scoped**, not family-scoped (`exec/polymarket_us/budget_exhausted/<day>`), and its ledger is seeded from durable fills at boot. | `exec/client.py:399,566-575,2242-2270` |
| G22 | The supervisor's daily cycle: STOP 16:40Z, LAUNCH 16:50Z, launch window closes 17:00Z. Mid-day relaunches reuse the child's environment. | `trade_supervisor_core.py:37-59` |
| G23 | FQ `try_submit` runs `submit_veto` (the family-halt veto), and the same callable also reaches the exec client. An entry-only veto therefore needs its own slot. | `fq/strategy.py:629-643`; `app/trade.py:709-713,846-853` |
| G24 | A NO buy is a Nautilus `OrderSide.BUY` on a composite NO-leg `InstrumentId`. The adapter translates it to venue `SELL`/`BUY_SHORT`. Every entry is a BUY, and exits are SELLs. OMS is `NETTING`. | `fq/strategy.py:682`; `symbology.py:289-295`; `leg_prices.py:41-48`; `exit_wiring.py:59-66`; `exec/client.py:1672` |

**L-1 null hypothesis per new component.**
- Nautilus has no artefact registry, champion/challenger state, promotion engine or scheduled restart
  (`WORK_BREAKDOWN:288`; `trade_supervisor.py:15-21`).
- The design reuses these Nautilus features: `Order.tags` (G9); `ClientOrderId`/`TradeId` for the
  order-to-fill join (`exec/client.py:400-412`); `Actor` plus `clock.set_timer` (G16);
  `ParquetDataCatalog` for tape-shaped capture.
- **L-1 verdict on `TradingState.REDUCING` (X21): insufficient; the custom entry veto is retained.**
  The installed `nautilus_trader/risk/engine.pyx:1150-1163` denies a BUY only when
  `portfolio.is_net_long(instrument)` and a SELL only when `is_net_short`. Every Breezy entry is a
  BUY, NO buys included (G24), and nearly every entry is into a **flat** instrument (a new rung or
  climate day), which REDUCING admits. The venue's NO-as-short-YES netting happens below Nautilus
  (`leg_prices.py:14-18`): Nautilus sees a long on the NO-leg id, so exits (SELL on net long) pass
  correctly, but so do new entries. REDUCING is also node-global, so it cannot express per-family
  state. Premise correction: `account_presence_halt.py:171` sets `HALTED`, not REDUCING. The veto
  uses the native `try_submit` guard slot, an extension rather than a reimplementation.

---

## 3. Shared contracts

**Common rules (apply to C1–C5):**
- Every record carries `schema: "<contract>/v<N>"`. Readers accept only their allowlisted versions
  and refuse anything else. Schemas are exact-set and grow only by L-12 widening with their readers.
- Serialisation is explicit (no `dataclasses.asdict`). Writes are atomic (`mkstemp` +
  `os.replace`; `runtime/health.py:322,330`) and append-only, named by content hash or `now_ns`
  (L-50). Timestamps are integer ns UTC from the injected clock. Money is a string-decimal.
- Stores live under `~/.local/share/breezy/{state,derived,registry,evidence}/`, never in the repo.
  Directories are 0700, files 0600, and content-addressed artefacts 0444.
- **Payload hygiene (X25).** Alerts, C1 records and C4 verdicts carry no absolute paths, env values,
  account or venue order ids, or credentials. Venue order ids appear only as `sha256`. The rule
  reuses the `AlertPayload` forbidden-content list (`registry/health_model.py:217-235`). A scan test
  covers every autonomy writer.
- Python types live in one new package, `src/breezy/persistence/autonomy/`, which both node and
  analysis may import (G15). Grep the containment tests first (L-46).

### C1 — Decision id and capture schema (producer AUT-1; consumers AUT-2, AUT-4, AUT-6)

**`decision_id`** = the first 32 hex characters of
`sha256(family_id | manifest_sha256 | artefact_sha256 | station | climate_day | rung_id | side | eval_ns)`.
- `eval_ns` is the Nautilus `clock.timestamp_ns()` at decision. It is **recorded** in the
  `DecisionRecord`, and the recorded value is authoritative (X18).
- Recomputation (batch parity, audit) uses the record's own fields and never re-derives `eval_ns`.
  A test recomputes the id from a stored record.
- It travels as the native order tag `breezy:decision_id=<id>`, defined next to the exit prefixes
  (`persistence/exit_tags.py`). It is set at each kind's one `order_factory.limit` call
  (`fq/strategy.py:681`; CRH `_maybe_submit`).

**Record types.** All share `schema`, `decision_id`, `family_id`, `ts_ns`, `node_boot_id`,
`build_sha` and `source` (`live` \| `canary`).

| Type | Fields | Writer |
|---|---|---|
| `DecisionRecord` | `kind` (`Take` \| `Refuse` \| `NotExecutable` \| `NotDPlus1` \| `TrySubmit`); `reason`; `eval_ns: int`; `station`, `climate_day`, `rung_id`, `side` (`yes` \| `no`), `instrument_id`; `ask_px`; `depth_ref` (sha256 of the Depth10 row, L-35); `p_hat`, `p_lower`, `p_upper`, `ev_net`; `forecast_input_sha256`; `artefact_sha256`; `manifest_sha256`; `registry_seq` | node, via the C6 `CaptureAdapter` |
| `OrderLink` | `client_order_id`; `venue_order_id_sha256: str\|None`; `intent_id` | node `on_order_*` |
| `LifecycleEvent` | `event` (`SUBMITTED` … `AMBIGUOUS`); `client_order_id`; `trade_id`; `qty`, `px`, `fee` | node |
| `PositionMark` | `instrument_id`; `leg`; `net_qty` (signed, venue convention, C2); `mark_px`; `source` | node or position monitor |
| `DetectorEvent` | `detector` (C6 id); `observation_sha256`; `state` (`AGREE` \| `DISAGREE` \| `UNKNOWN`) | in-node detectors (fee probe, liveness) |
| `SettlementRecord` | `station`, `climate_day`, `settlement_tmax_f`, `basis`, `raw_sha256` | offline |

**Storage.** A daily file `decisions/capture_<family_id>_<YYYY-MM-DD>.jsonl`, following the
`OfferTape` and `FqDecisionFunnelActor` convention (`crh/composition.py:568-602`;
`app/trade.py:763-775`). The existing retention unit compresses it.
- **No silent cap.** A write failure or a byte cap increments a counter, raises a CRITICAL alert and
  marks the day `CAPTURE_INCOMPLETE`.
- A `Refuse` is written when `(key, reason)` changes, not on every tick (L-29). Every `Take` and
  `TrySubmit` is written. AUT-1 measures the volume (INFERRED until then).
- **Rejected alternative:** `StreamingConfig` on the trade node, because of memory and flush risk in
  the order process. It may be reopened only with a measured L-1 proof.

**Invariants.** (i) Every submitted order carries exactly one `decision_id` tag (a test per
composable kind). (ii) Every durable fill (`exec/client.py:408-447`) joins to exactly one
`DecisionRecord` through `client_order_id`. (iii) The daily audit requires decisions ⋈ links ⋈ fills
⋈ settlements = 100% for every settled live fill.

**Failure behaviour.** A missing tag refuses the submit (`capture_untagged`). A write error raises a
CRITICAL alert and makes the day inadmissible for AUT-4. A join gap is a `HEALTH` FAIL.

### C2 — Scored-outcome label (producer AUT-2; consumers AUT-3, AUT-4, AUT-6)

**Schema `label/v1`.** One parquet file per run at
`derived/labels/<family_id>/labels_<now_ns>.parquet`. It is append-only and deduped on
`(label_id, max label_seq)`, the scored-trial conventions (G8). The scored-trial store stays
untouched. The pyarrow schema is pinned column for column.

Fields: identity (`label_id`, `decision_id`, `family_id`, `trial_id`, `client_order_id`,
`trade_id`); market (`station`, `climate_day`, `instrument_id`, `rung_id`, `leg`, `role`
`entry`\|`exit`); fill (`qty`, `fill_px`, `entry_ask`, `fee_reconciled`, `slippage`, str-decimal);
`p_at_decision` (float64, nullable only with a reason); settlement (`settled_outcome` = the bought
leg's win, `settlement_tmax_f`, `settlement_basis`); P&L (`realized_pnl` net of reconciled fee for
the bought-leg holder; `counterfactual_hold_pnl` for exits); reconciliation (`reconciled`,
`reconciliation_delta`, `reconciliation_source`, `net_position_key` = base slug); admissibility
(`admissible`; `excluded_reason` ∈ `duplicate_fill`, `q≠1`, `fee_unreconciled`, `window_incomplete`,
`canary`); run metadata (`labelled_at_ns`, `label_seq`, `scorer_id` = C6 id plus producer code sha).

**Invariants.**
- **Net-position reconciliation (X16).** Reconciliation compares the venue balance against the
  **net signed position per base instrument**. A NO holding nets as short YES on the same slug
  (L-44; `parsing.py:277-279`), so YES and NO fills on one slug are summed with the leg sign before
  comparison.
  - A RED test: a NO fill offsetting an existing YES holding reconciles to the netted venue
    quantity.
  - Each leg's terminal state has its own RED test.
- **First AUT-2 step:** root-cause the FQ "SETTLED −0.37" versus tally "+0.37" conflict with
  artefact evidence before any scorer change. The finding goes into the AUT-2 plan.
- Only `window_complete` rows are scored or counted (memory note `census-rows-include-open-windows`).
- Every live fill is labelled within 24 h of its `SettlementRecord`. Otherwise a `HEALTH` FAIL
  (`label_lag`) is raised.
- `reconciled=False` is never `admissible`. `source=canary` is never admissible and never counts
  toward any n.
- "Nothing to score" exits 0 with a `NO_INPUT` line. No unit exits non-zero as expected behaviour.

**Failure behaviour.**
- A fill that cannot be labelled becomes an `excluded_reason` row. A score is never fabricated
  (`trial_scorer.py:158`).
- Reconciliation outside tolerance: `reconciled=False`, a CRITICAL alert and a `RECONCILIATION`
  FAIL.

### C3 — Artefact lineage manifest (producer AUT-3; consumers AUT-4, AUT-5, AUT-7)

**Storage.** Content-addressed and immutable:
`derived/artefacts/<model_class>/<artefact_sha256>/{artefact.json, lineage.json}`.
- Files are 0444 and directories 0500. Each file is opened with `O_NOFOLLOW`, and a symlink anywhere
  on the path is refused (X10).
- The layout generalises the G13 candidate root. The artefact bytes use the existing writer
  (`nbp_calibration.py:2643`).

**Schema `lineage/v1`.**
- `artefact_sha256`; `model_class` (`composition_kind:component`); `lineage_root_family_id`;
  `parent_artefact_sha256`; `code_git_sha`, `build_sha`, `producer_code_sha` (§4.3); `params`;
  `seed`; `fit_status` (`OK` only); `data_windows` (`{source, start_utc, end_exclusive_utc, rows,
  content_sha256}`).
- Own-outcome use (X22):
  - `own_outcome_label_set_sha256` (str \| null) records the C2 label set used.
  - `ablation_artefact_sha256` is the sha of the same refit with that label set left out. The
    writer refuses the lineage if it is not null and equals `artefact_sha256`, because the labels
    would then have had no effect.
- **The model class that consumes C2** is `forecast_quantile_ladder:rung_recalibration`.
  - It is a traded-rung recalibration map fitted on C2 `(p_at_decision, settled_outcome)`.
  - It needs the G11 loader widening, together with parity tests.
  - `forecast_quantile_ladder:density_table` consumes external weather only.
- Evaluation windows: `train_end_exclusive_utc` and `forward_eval_start_utc` (equal to or after
  `created_at`; see C4).
- `leakage_assertions`: `{name, passed}`, including `ref_ts_lt_take_ts`,
  `train_end_lt_forward_eval_start` and `no_sealed_holdout_rows_in_train`.
- `recalibration` and `correction_form` must be members of the live loader's accepted set (G11).
- Run metadata: `created_at_ns`; `runtime_s`; `peak_rss_bytes`.

**Invariants.**
- `sha256(artefact.json) == artefact_sha256`.
- A scheduled rerun from `lineage.json`, on a **sampled subset** (§5 slot table), reproduces the sha.
  A mismatch is a `HEALTH` FAIL.
- A lineage with a failed assertion is never written.
- Verify and load read the bytes **once** through one file descriptor, then hash and parse those
  same bytes (X10).

**Failure behaviour.** A missing or mismatched lineage makes the artefact ineligible above SHADOW.
A rollback re-verifies the bytes.

### C4 — Verdict (producers AUT-2, AUT-4, AUT-6; consumer AUT-5, plus AUT-7 triggers)

**Storage.** `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json`.
- Directories are 0700, and files are append-only. `verdict_id` is the sha256 of the canonical body.
- Producers run as their own oneshot units, separate from the engine unit and the node (X24).

**Schema `verdict/v1`.**
- Identity: `verdict_id`; `kind` (`OFFLINE_CHALLENGER` \| `FORWARD_SHADOW` \| `LIVE_SEQUENTIAL` \|
  `DRIFT` \| `HEALTH` \| `RECONCILIATION`); `subject_family_id`; `subject_artefact_sha256`;
  `comparator_family_id`.
- Outcome: `outcome` (`PASS` \| `FAIL` \| `UNDERPOWERED` \| `INCONCLUSIVE` \| `ERROR`); `detector`
  (C6 id); `declared_action_class` (`NONE` \| `ALERT` \| `SELF_HEAL` \| `DEMOTE` \| `HALT`).
- Measurement: `metrics` (pre-registered names only); `n`; `n_min`; `power`;
  `eta_to_verdict_days`; `alpha_spent` (cumulative, lineage-level; see below).
- Provenance: `inputs` (a list of `{path_role, sha256}` with no paths); `prereg_ruling_sha256`;
  `produced_at_ns`; `valid_until_ns`; `producer_code_sha`.

**Evaluation protocol (X4, X5).**
- `OFFLINE_CHALLENGER` scores the candidate against the champion on historical external weather,
  using the sealed-holdout rules (`nbp_calibration.py:334-420`) and the pinned bootstrap
  (`roi_bound.py:93-100`).
  - The sealed `DEFAULT_SPLITS` holdout may be opened **at most once per lineage**. The registry
    counts `holdout_opens`, and the engine refuses a verdict whose lineage would open it a second
    time.
  - Routine selection uses a **rolling forward holdout**: only days on or after the candidate's
    `forward_eval_start_utc`, which no fit has touched.
- `FORWARD_SHADOW` evaluates the challenger prospectively on post-mint days, using the C1-captured
  live tape and Depth10. It requires all three of:
  - (a) Brier on the **traded rung** beats the **market-implied baseline**, reusing
    `scripts/analysis/wp7b_market_as_forecaster.py`;
  - (b) EV net of the reconciled fee **and observed slippage**, where slippage is drawn from C2
    champion fills against the same Depth10 rows;
  - (c) the traded-rung calibration leg passes (`forecast_conditional_scoring.py:392`).
  - It also needs a pre-registered minimum of forward days and evaluated takes.
- **Multiple testing.** The k-th candidate evaluated in a lineage against an overlapping forward
  window is tested at α_k = α_total·2^−k (pre-registered α_total). `alpha_spent` accumulates per
  lineage, and the registry counts candidates evaluated.
- `LIVE_SEQUENTIAL` reuses `run_sequential_looks` (`family_tally_v2.py:625`) and its boundaries
  (`crh_group_sequential_boundaries.py:243`). It never defines a new α-spend, and it is used mainly
  to demote.

**Invariants.** Every verdict states `n_min`, or the literal reason it has none.

**Engine acceptance (X20, X24).** The engine acts on a verdict only if `producer_code_sha` is in the
committed producer pin set (§4.3), every `inputs[].sha256` resolves under that role's expected root,
`prereg_ruling_sha256` equals the policy ruling's, and `declared_action_class` equals the ruling's
`detector id → action_class` entry. Any mismatch makes it `ERROR`, with an alert, and it never acts.

**Failure behaviour.** A verdict past `valid_until_ns` is `ERROR`. A champion with no verdict past
its horizon gets a synthetic `HEALTH` FAIL (`verdict_stale`). `ERROR` and `UNDERPOWERED` never
promote. An accepted `FAIL` mapped to `DEMOTE` or `HALT` always acts.

### C5 — Registry, state machine and transition audit (owner AUT-5; AUT-7 co-writes through the same API)

**Storage and isolation (X3).**
- SQLite at `~/.local/share/breezy/registry/registry.sqlite` (WAL, `synchronous=FULL`; dir 0700,
  file 0600). It is not the exec store, because of the flock (G6) and no iteration (G7).
- **Single writer:** `breezy-autonomy-engine.service`, its own oneshot unit (`ReadWritePaths=` the
  registry and evidence dirs only, `ProtectSystem=strict`, memory cap). AUT-7 runs inside it. Any
  operator registry tool writes through the same API and chain (`decided_by=operator_cli`).
- **Readers** (node, supervisor, timers) use the `mode=ro` URI (`trial_day_latch.py:354-379`). The
  node's spawn carries `ReadOnlyPaths=` on the registry directory.
- **Residual risk, stated:** a same-uid writer could rewrite the chain consistently. The chain and
  export give tamper *evidence*. *Resistance* comes from code: a row can select only among
  candidates the committed allowlists and sha-pinned rulings already authorise (§4.2), and the node
  re-derives that authority instead of trusting the row.

**Tables (`registry/v1`).**
- `transitions` is the only source of truth.
  - Columns: `seq` PK; `transition_id` UNIQUE; `family_id`; `from_state`; `to_state`; `kind`;
    `cause_verdict_ids` (JSON); `policy_ruling_id`; `policy_ruling_sha256`; `decided_by`;
    `invocation_id` (systemd `INVOCATION_ID`); `engine_code_sha`; `expected_prior_seq`;
    `effective_launch_date` (null means immediate); `ts_ns`; `prev_transition_hash`;
    `transition_hash`.
  - SQLite triggers `BEFORE UPDATE` and `BEFORE DELETE ON transitions` → `RAISE(ABORT)`.
- `families` and `projection` are **derived caches**, rebuilt in the same transaction and never
  trusted by readers.
  - `families` holds identity, `venue`, `composition_kind`, `lineage_root_family_id`, manifest and
    artefact shas, `state`, `rollback_eligible`, `halt_cause_class`, `resume_count` and
    `demoted_for_cause`.
  - `projection` has one row per venue: `champion_family_id`, `next_champion_family_id`,
    `next_effective_launch_date`, `entries_suspended`, `registry_seq` and `chain_head`.
- `lineage_counters` holds per-lineage counts: `holdout_opens`, `candidates_evaluated`,
  `alpha_spent`, `promotions` (with timestamps) and `rollbacks`.

**Hash chain.**
- `transition_hash = sha256(canonical row ‖ prev_transition_hash)`, starting from the genesis hash
  `sha256("registry/v1|" + venue)`.
- At LAUNCH, `resolve_champion` verifies the whole chain, re-folds the transitions into a
  projection and compares it with the cache. Any mismatch counts as "registry unavailable".
- A daily export, `evidence/registry/registry_<date>.jsonl` (0444), holds every new row plus the
  chain head. The resolver refuses a chain whose prefix disagrees with the latest export.

**States.** `SHADOW` (offline only), `CHALLENGER` (passed the offline gate, never sends), `CHAMPION`
(the single sender per venue), `HALTED` (champion with entries stopped for cause), `RETIRED`
(terminal).

**Invariant (X8):** each venue has **at most one** family in {CHAMPION, HALTED}, and it is
`projection.champion_family_id`.

**Allowed transitions.** This is the whole set. Any other pair is refused by the store.

| From → To | Kind | Allowed when | Effective |
|---|---|---|---|
| ∅ → SHADOW | BOOTSTRAP / MINT | Committed root, or a child passing the §4.2 manifest-equality and C3 checks, with complete C6 | now |
| SHADOW → CHALLENGER | PROMOTE | Accepted `OFFLINE_CHALLENGER` PASS | now |
| CHALLENGER → CHAMPION | PROMOTE | Accepted `OFFLINE_CHALLENGER` **and** `FORWARD_SHADOW` PASS (an offline PASS alone is never enough); §4.4 preconditions; rate limit | next LAUNCH |
| CHALLENGER → CHAMPION | ROLLBACK | Target `rollback_eligible`, never `demoted_for_cause`; bytes re-verified; §4.4 preconditions; rollback budget | next LAUNCH |
| CHAMPION → CHALLENGER | SUPERSEDE | Atomic with another family's →CHAMPION. Sets `rollback_eligible=true` | next LAUNCH |
| HALTED → CHALLENGER | DISPLACED | Atomic with another family's →CHAMPION. `rollback_eligible` stays false | next LAUNCH |
| CHAMPION → HALTED | DEMOTE / HALT | Accepted FAIL mapped to DEMOTE or HALT, or an exec-store halt mirrored (§C5 mirror). Clears `rollback_eligible`, sets `demoted_for_cause`, cancels a pending `next_*` naming this family. **Always permitted, never capped** | now (entry stop) |
| HALTED → CHAMPION | RESUME | `halt_cause_class=RECOVERABLE`; cause verdict now PASSes; `projection.champion_family_id` equals this family; cooldown and resume budget (§4.5); §4.4 preconditions | now (same family and namespaces) |
| HALTED → RETIRED | RETIRE | TERMINAL cause, or the resume budget is exhausted. S_k and n are frozen (`WORK_BREAKDOWN:423`) | now |
| SHADOW, CHALLENGER → RETIRED | RETIRE | Policy (age, failed gate, lineage superseded) | now |

**Activation without a dead zone (X7).**
- PROMOTE, SUPERSEDE, DISPLACED and ROLLBACK write `next_champion_family_id` with
  `next_effective_launch_date`, the next 16:50Z LAUNCH (G22). `resolve_champion(venue, now)` is a
  pure function of the verified chain and the clock, so the current champion sends until that
  instant and activation needs no write.
- The supervisor polls the projection every tick and acts on a pending swap **only inside the
  declared safe window**, 16:40–17:00Z (`trade_supervisor_core.py:37-44`). A mid-day relaunch keeps
  the resolved `(family_id, registry_seq)`, so nothing swaps mid-day.
- The supervisor resolves **once** per LAUNCH and passes `BREEZY_RESOLVED_FAMILY_ID` and
  `BREEZY_RESOLVED_REGISTRY_SEQ` through the forwarded environment (G2); these are build-side, not
  operator controls. The node re-resolves and refuses boot on disagreement, or if a restrictive
  transition for that family follows the passed seq.
- **Budget across a swap.** The daily stop is venue-scoped and seeded from all durable fills (G21),
  so a swap cannot reset it.
  - `test_swap_cannot_exceed_daily_budget_across_namespaces` pins this against both latch namespaces
    and the budget namespace.
  - `test_swap_cannot_double_take_rung` refuses a successor's entry on a rung where the venue
    already holds a net position (exec-store fills keyed by base slug).

**Idempotency (X23).**
- `transition_id` = sha256 of `(family_id, from, to, kind, sorted cause_verdict_ids,
  policy_ruling_sha256)`. It does **not** include `expected_prior_seq`.
- Each write is one `BEGIN IMMEDIATE` transaction. If `transition_id` already exists, the write is
  a logged no-op. Otherwise:
  1. the CAS `projection.registry_seq == expected_prior_seq` must hold;
  2. the row is inserted, extending the chain;
  3. the caches are re-folded.
- On a CAS failure the engine re-reads, re-evaluates and retries once, then alerts. A CAS conflict
  never changes what the node composes.

**Pickup.**
1. **Activation, at LAUNCH.** The supervisor (`trade_supervisor_core.py:884-895`), the node
   (`app/trade.py:905-990`) and the settings validator (`settings.py:183,366-388`) all call one
   resolver in `persistence/autonomy/resolver.py`.
   - It returns a `ResolvedFamily`: the family id, the manifest bytes and sha, and the artefact
     bytes and sha, each read once through one descriptor.
   - Both `_validate_sending_family_manifest` and `_compose_family` consume that object, so they
     never re-read the manifest or artefact (X10).
   - This applies only when the committed supervisor unit sets `BREEZY_FAMILY_SOURCE=registry` (X13).
     The value is fixed in `deploy/systemd/breezy-trade-supervisor.service`, and a scan test proves
     no autonomy code reads or writes it except the resolver's read. Without the flag, behaviour is
     byte-identical to today.
   - **Resolver refusals (X1, X3)** give "no champion" for: a `composition_kind` outside the code
     constant `LIVE_GATE_ROUTED_KINDS` (today `{forecast_quantile_ladder}`, the only kind whose
     composition calls the gate, G19); a `live_orders_ruling` that is not the policy ruling; a
     root not in `_LINEAGE_POLICY_ALLOWLIST`; a ruling sha mismatch; a broken chain; an
     authorising `engine_code_sha` outside the pin set (§4.3); or a §4.2 equality breach.
2. **Deactivation, immediate.** A native `RegistryWatchActor` (an `Actor` with `clock.set_timer`,
   the fee-probe pattern, G16) reads the projection every 60 s.
   - It exposes `entry_veto()`, which returns `registry_not_champion`,
     `registry_entries_suspended` or `registry_unreadable`.
   - The veto is wired into a **new, separate `entry_veto` slot** in each strategy's `try_submit`.
     It is never added to `submit_veto`, which also reaches the exec client (G23), so exits stay
     open.
   - The timer never raises (L-16). An exception sets `registry_unreadable`, which **clears on the
     next good read** (a test covers this).
3. **Registry children** live at `~/.local/share/breezy/registry/families/<id>.json` (0444, never a
   symlink), with artefacts content-addressed beside them.
   - This takes one reviewed L-12 widening of the containment at four sites:
     `family_manifest.py:169,266-282`, `app/trade.py:122`, `settings.py:183` and
     `settings.py:366-388`.
   - The widening keeps `resolve()` and the `..` and absolute refusals, and adds `lstat`/
     `O_NOFOLLOW` symlink refusal with a symlink RED test.
   - Child ids are `<root>_r<NNNN>`, which matches both id regexes (`settings.py:115`;
     `trial_day_latch.py:301`).

**Exec-store halt mirror (X9, X26).** The engine mirrors exec-store halts read-only. The mapping is
fixed:

| Exec-store reason (G20) | Cause class | Registry effect |
|---|---|---|
| `duplicate_fill`, `ambiguous_exit` | INTEGRITY | HALTED; the venue is frozen for PROMOTE, RESUME and ROLLBACK until the operator CLI clears it (L-48) |
| legacy key `halts_all` | INTEGRITY | Same, for every family on the venue |
| legacy key `attributable_to_v4` | (none; v4 is seeded RETIRED) | No venue freeze |
| `policy_halt` with detail `fee_schedule_drift` | TERMINAL | HALTED → RETIRED. θ is part of the estimand, and §4.2 forbids a child from changing θ. Recovery needs a new lineage root (a reviewed commit) |
| `policy_halt` with any other detail (A1 CLI) | TERMINAL | HALTED → RETIRED |
| A read failure or an unknown payload | INTEGRITY | That run makes no non-restrictive transition. If the failure persists past the staleness horizon, the champion goes HALTED/INTEGRITY |

- **RECOVERABLE causes never use the exec-store halt.** They are registry DEMOTEs, which stop
  entries only: verdict staleness, feed or recorder staleness, permit lapse, capture gap,
  `registry_unreadable`, and unit health.
- AUT-6 self-heal and AUT-5 RESUME are reachable through these causes. Fee drift stays
  exec-store-halting, unchanged, so no safety test is touched.

**Relationship to existing controls.**
- A node may send only if all of these hold: the resolver says CHAMPION, the entry veto is clear,
  the exec-store halt is clear (G5), the live-orders gate passes (G4), a permit exists, and the caps
  admit the order.
- The registry adds vetoes. Only PROMOTE, RESUME and ROLLBACK widen, and only within §4.2.
- The registry never writes the exec store.

**Failure behaviour (X13).** Any registry failure gives an entry veto and **no permit-bearing
composition**. There is **no fallback to the lineage root**. Failures include a missing or unreadable
DB, an unknown version, a chain or export mismatch, a sha mismatch or a refusal.
- At LAUNCH: the node composes no sending family, the supervisor raises a CRITICAL
  `REGISTRY_UNAVAILABLE` alert and retries the resolve inside the launch window, and C1 marks the
  day `CAPTURE_INCOMPLETE(registry_unavailable)`.
- Tape capture is a separate unit and continues.
- `test_registry_unavailable_mints_no_permit` pins this.

**Bootstrap (X8).** BOOTSTRAP transitions from the committed manifests: `pm_us_crh_fq_v1` →
CHAMPION; `pm_us_crh_v4` → RETIRED (A1 disposition; never HALTED, so it cannot freeze the venue);
`pm_us_crh_cont` and `pm_us_crh_v2` → RETIRED. DRAFT manifests are not seeded.

### C6 — Family plug-in contract (owned here; implemented per kind by AUT-1, 2, 4 and 6)

Protocols live in `persistence/autonomy/plugin.py`:

| Member | Layer | Signature (sketch) | Output |
|---|---|---|---|
| `CaptureAdapter` | strategy | `decision_record(decision, ctx)`; `order_tags(decision_id)` | C1 |
| `Scorer` | analysis | `label(capture_day, exec_fills, settlements)` | C2 |
| `Evaluator` | analysis | `offline(candidate, champion)`; `forward_shadow(candidate, champion, tape)`; `live(labels)` | C4 |
| `DriftDetectors` | both | `tuple[Detector, ...]`, each with `id`, `kind` and `evaluate(...)` | C4 |
| `Refitter` | analysis | `refit(windows) -> (artefact, Lineage)`, or `NOT_FITTABLE` | C3 |

- **Registries:** `NODE_PLUGINS` (strategy layer) and `OFFLINE_PLUGINS` (analysis layer), keyed by
  `CompositionKind` (`family_manifest.py:115-121`).
- **YAGNI (X28).** A kind with no non-RETIRED family registers `RefusingPlugin`, which refuses mint
  and compose. Today that covers `current_rung_hold`, `continuous_rung_hold` and `forecast_ladder`.
  Only `forecast_quantile_ladder` gets full plug-ins in Wave 1. A kind gets full plug-ins in the
  same change that admits it to `LIVE_GATE_ROUTED_KINDS`.
- **Gate tests:**
  - `set(NODE_PLUGINS) == set(OFFLINE_PLUGINS) == _COMPOSITION_KINDS`;
  - every non-RETIRED manifest resolves to full plug-ins;
  - a `RefusingPlugin` kind can never reach SHADOW.
- **Runtime:** `_compose_family` (`app/trade.py:853`) refuses boot when the plug-in is missing or
  refusing. The engine refuses ∅→SHADOW and any →CHAMPION with incomplete or refusing plug-ins.
- **Required detectors per kind:** freshness, forecast drift, calibration drift, fill-rate and
  slippage, fee and shape drift, permit and process liveness, unit health. Removing one fails the
  gate. Each detector's action class comes from the policy ruling map (C4), never from the
  detector.

---

## 4. Autonomy safety envelope

### 4.1 Allowed and forbidden

**The bot may, on its own:** mint SHADOW children of an allowlisted root; refit, evaluate and
detect; write C1–C4; make the C5 transitions; demote or halt at any time; and promote, resume or
roll back only under §4.2–§4.5.

**The bot never touches:** (1) the two caps (G18); (2) master enablement
(`breezy-trade-supervisor.service:120-121`); (3) the permit mechanism and its minting authority;
(4) the NO-SEND firewall; (5) `allow_short=False`; (6) the code allowlists and sha pins; (7) the
policy ruling. Items 6 and 7 change only through a reviewed commit or a ruling under
`docs/evidence/`, never through the engine. Of all these, only the caps are an operator decision.

### 4.2 Authorisation without a commit per promotion (X2, X11)
- **One reviewed widening (L-12).** `live_orders_gate.py` gains a code-committed
  `_LINEAGE_POLICY_ALLOWLIST` of `(root_family_id, policy_ruling_id, policy_ruling_sha256)` triples.
  - An AST test (`test_lineage_policy_allowlist_is_literal_only`) pins both allowlists as
    literal-only tuples of string constants.
  - At every LAUNCH the node re-hashes the deploy copy under `deploy/families/rulings/`, as G4
    already does, and refuses on any mismatch.
- **Manifest equality.** A child must equal its root on **every** key except this explicit
  allowlist: `family_id`, `trial_id_prefix`, `d0_climate_day`, `density_artefact_path`,
  `density_artefact_sha256` and `live_orders_ruling` (which must name the policy ruling).
  - The equality covers every size and price knob, `stations`, `taker_fee_coefficient`,
    `exit_rule`, `no_leg_exit`, and the boundary artefact.
  - Recalibration and correction forms live in the artefact and remain bounded by the loader (G11).
  - `exit_gate.py` (G17) stays code-only, pinned by `test_exit_gate_stays_code_only`.
- **Live-gate routing (X1).** Only kinds in `LIVE_GATE_ROUTED_KINDS` can be CHAMPION, through both
  the resolver and the engine.
  - `test_registry_champion_requires_live_orders_gate_for_every_kind` drives every composition kind
    and asserts one of two things: the kind calls `live_orders_authorized` before a permit reaches
    its strategy, or it is excluded from `LIVE_GATE_ROUTED_KINDS` and refused as CHAMPION.
- **The policy ruling pre-registers** every threshold (WP-26 criteria 1–6 as the base) and the C4
  forward-shadow predicates, α_total, the `detector id → action_class` map, the RECOVERABLE and
  TERMINAL classes, the drawdown limit, staleness horizons, rate limit, damping (§4.5) and the
  AUT-7b drill clause (§5.3). The engine reads them only from the sha-pinned copy.
- The policy ruling explicitly supersedes D11 for allowlisted lineages, as the parent ruling §3
  permits.

### 4.3 Code identity pins (X2, X24)
- `persistence/autonomy/pins.py` holds literal-only sets: `ENGINE_SOURCE_SHA256` and
  `PRODUCER_SOURCE_SHA256[producer_id]`.
- Each pin is the sha256 over the sorted bytes of that component's modules, excluding `pins.py`, so
  the definition is not self-referential.
- The engine and each producer compute their own hash at start and refuse to run if it is not
  pinned. They stamp it into every transition or verdict.
- A gate test recomputes each hash, so any edit to the engine or a producer forces a reviewed pin
  update in the same commit.
- The node checks the authorising transition's `engine_code_sha` at LAUNCH (C5 refusals).

### 4.4 Promotion preconditions (X6)
PROMOTE (→CHAMPION), SUPERSEDE, DISPLACED, RESUME and ROLLBACK all require: no OPEN or AMBIGUOUS
submit intent in the exec store (read-only); an accepted `RECONCILIATION` PASS within its horizon;
no unreconciled leg-signed net position (C2); and no INTEGRITY freeze on the venue.

A demoted or superseded family **holds its positions to settlement**. FQ has no exit capability
(G17), and autonomy never widens the G17 exit allowlist.

### 4.5 Damping (X12)
Pre-registered in the policy ruling, which may be stricter than these code ceilings, never looser:
a RESUME cooldown of at least 24 h; at most 2 RECOVERABLE resumes per lineage per 14 days, after
which the cause becomes TERMINAL; at most 2 ROLLBACKs per venue per 30 days, after which a rollback
trigger HALTs; never a rollback to a `demoted_for_cause` family (DEMOTE and HALT clear
`rollback_eligible`); the code constant `MAX_NONRESTRICTIVE_TRANSITIONS_PER_VENUE_PER_DAY = 2` in
`pins.py`, changed only by a reviewed commit, with DEMOTE and HALT never capped; and at most 1
PROMOTE per lineage per M days.

### 4.6 External watch (X14)
`breezy-autonomy-deadman.timer` (every 30 min), independent of the engine, reads the engine
heartbeat and the chain-head age and raises a CRITICAL alert past the horizon. A daily 15:45Z
`autonomy_canary` INFO alert proves delivery, with the sink's acknowledgement journaled.

### 4.7 Envelope tests (RED first, in the gate)

**Existing tests, unweakened:** `test_operator_control_assignment_scan`,
`test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`,
`test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`,
`test_risk_engine_ordering_enforcement`.

**New tests:**

| Test | Pins |
|---|---|
| `test_autonomy_never_reads_or_writes_operator_controls` | AST scan, with tokens from `OPERATOR_RESERVED_CONTROL_ENV_VARS` |
| `test_autonomy_never_touches_enablement_permit_or_firewall` | No enablement vars, permit issuance or firewall modules referenced |
| `test_autonomy_never_imports_order_path` (X27) | An import-linter contract plus AST: autonomy code never imports the exec client or the `submit_order` path |
| `test_autonomy_alert_egress_not_widened` (X27) | Alerts use only `resolve_alert_sink`. The firewall allowlist set is unchanged |
| `test_registry_transition_table_is_exact` | The pairs equal the C5 table, and the one-champion-per-venue invariant holds |
| `test_registry_cas_and_idempotent_replay` | Replay is a no-op, a concurrent writer is refused, there are never two in {CHAMPION, HALTED}, and DISPLACED is atomic |
| `test_registry_hash_chain_and_triggers` | UPDATE and DELETE abort, and a tampered row, chain or export makes the resolver refuse |
| `test_registry_champion_requires_live_orders_gate_for_every_kind` | X1 |
| `test_lineage_policy_allowlist_is_literal_only`; `test_code_identity_pins` | X2 |
| `test_child_manifest_equals_root_except_allowlist`; `test_exit_gate_stays_code_only` | X11 |
| `test_registry_paths_refuse_symlinks`; `test_verify_and_load_share_bytes` | X10 |
| `test_registry_unavailable_mints_no_permit`; `test_registry_unreadable_veto_clears`; `test_family_source_fixed_in_unit` | X13 |
| `test_promotion_requires_flat_reconciled_state` | X6 |
| `test_swap_cannot_exceed_daily_budget_across_namespaces`; `test_swap_cannot_double_take_rung`; `test_node_refuses_resolved_seq_mismatch` | X7 |
| `test_damping_ceilings` | X12 |
| `test_verdict_acceptance_rules` | X20, X24 |
| `test_halt_reason_class_map_is_exact`; `test_mirror_read_failure_is_integrity` | X9, X26 |
| `test_autonomy_payload_hygiene_scan` | X25 |
| `test_demotion_never_requires_policy_and_is_immediate`; `test_registry_veto_leaves_exit_seam_open` | Entry-only demotion |
| `test_family_plugin_exact_set`; `test_rollback_restores_byte_identical_artefact` | C6, AUT-7 |

---

## 5. Area boundaries, sequencing and live proof

| Area | Owns | Writes |
|---|---|---|
| AUT-1 | `CaptureAdapter` per kind, the `decision_id` tag, link and lifecycle writers, `DetectorEvent`, the daily completeness audit, recorder and feed stall self-heal (a systemd restart, not a new daemon) | C1; C4 `HEALTH` |
| AUT-2 | `Scorer` per kind; the label store; net-position reconciliation; the −0.37/+0.37 root cause; family-agnostic tallies and ROI | C2; C4 `RECONCILIATION` |
| AUT-3 | `Refitter` per kind; refit timers; the C3 writer; leakage, ablation and reproducibility checks; the G11 widening with parity tests | C3 |
| AUT-4 | `Evaluator` per kind: offline, forward shadow, live sequential; α accounting | C4 |
| AUT-5 | The C5 store, chain and resolver; the engine unit; the policy ruling; `RegistryWatchActor`; supervisor and node wiring; the allowlist widening; pins; the dead-man; bootstrap | C5 |
| AUT-6 | `DriftDetectors` per kind (fee and shape for every kind); liveness; unit health; clearing the five failing units | C4 `DRIFT`, `HEALTH` |
| AUT-7 | Rollback-target selection and the ROLLBACK transition through the C5 API; the gate drill (AUT-7a); the live drill (AUT-7b) | C5 through the engine |

### 5.1 Build sequence
- **Wave 0 (ARCH-0, serial).** The `persistence/autonomy/` package: schemas, the C5 store (chain,
  triggers, CAS), the resolver, `pins.py`, the C6 Protocols and `RefusingPlugin`.
  - All §4.7 tests start RED.
  - `lint-imports` must report "N kept, 0 broken", run from the tree via the console script.
  - Size M, with an independent review.
- **Wave 1 (parallel, against the stubs only):** AUT-1; AUT-6; AUT-5a (store wiring, watch actor,
  resolver at LAUNCH, bootstrap, demotion-only engine, dead-man); AUT-7a; AUT-2a (FQ scorer over
  the exec store, plus the root cause). File ownership is disjoint; `app/trade.py`, `settings.py`
  and `trade_supervisor*.py` belong to AUT-5a alone.
- **Wave 2:** AUT-2b (`decision_id` join, NO-leg and exit labels); AUT-3 (external refits may start
  in Wave 1; `rung_recalibration` follows C2); AUT-4 live sequential.
- **Wave 3:** AUT-4 offline and forward shadow; AUT-5b (policy ruling peer-reviewed and filed, then
  the allowlist widening, then promotion, resume and rollback enabled); AUT-7b.
- **Gate discipline:** run the full gate after every merge (L-43), using
  `scripts/ci/run_tests_no_egress.sh` with the exact interpreter. Never `uv` (L-51).

### 5.2 Slot table (X17)
Every autonomy job takes the studies flock `breezy-studies.lock` (`flock -w 5400`, a serialised
queue) in `breezy-studies.slice`, with `OnFailure=breezy-study-failed@`, `RuntimeMaxSec` and a
no-progress stall event. "Heavy" means `MemoryMax` above 4G. The `WORK_BREAKDOWN:512` blackout means
"no **heavy** job starts 01:00–04:30Z" (it protects the 03:00Z `mb-daily`). The 02:05Z nightly is
light (`MemoryMax=4G`, `breezy-nbp-learning-nightly.service:17`), so there is no clash, and the flock
serialises it anyway. In the live window (16:50–01:00Z), stop the study, never the node.

| UTC | Job (unit) | Class | MemoryMax |
|---|---|---|---|
| 05:00 | AUT-2 label and reconcile | light | 4G |
| 05:30 | AUT-6 offline detectors | light | 4G |
| 06:00 | AUT-3 refit | heavy | 16G |
| 08:00 | AUT-3 reproducibility rerun on a 10% sampled subset of windows | heavy | 12G |
| 10:00 | AUT-4 offline challenger and forward shadow | heavy | 12G |
| 14:45 | AUT-4 live sequential (after the 14:15 scoring run) | light | 4G |
| 15:30 | AUT-5 engine (writes `next_*` before the 16:40 STOP) | light | 2G |
| 15:45 | Canary alert; dead-man every 30 min | tiny | 256M |

### 5.3 Live-proof evidence rules (X15, X19)
- **Qualifying days.** A day counts toward any 7-day window only if it has at least 1 real fill, or
  a `source=canary` synthetic fill that traverses the production capture→label→reconcile path.
  - Zero-fill days do not count, and the window extends.
  - Every window also needs **at least 5 real fills**. Canary fills never count toward that figure
    or toward any statistic.
- **Honest evidence class.** Each DONE claim states "machinery proven, edge unproven" unless a
  pre-registered edge verdict passed.
- **AUT-7b, its own item and clock.** The live drill runs through the production engine under the
  policy's drill clause: (1) mint `pm_us_crh_fq_v1_r0001`, a byte-identical child of `fq_v1`; (2)
  PROMOTE it, effective at LAUNCH; (3) inject a RECOVERABLE `HEALTH` FAIL through the live detector
  path, which DEMOTEs it; (4) RESUME; (5) ROLLBACK to `fq_v1` with the sha re-verified. The permit
  may be live or withheld, and its authority is untouched. The clause admits only a child whose
  artefact sha equals the champion's, and it counts against the rate and rollback budgets. The
  clock is at least 4 trading days and covers AUT-5's PROMOTE, DEMOTE and RESUME proof and AUT-7's
  rollback proof.
- **After the 2027-01-25 KILL.** If it fires TERMINAL, the champion RETIREs and
  `champion_family_id` becomes null: no sender. Capture, labels, refits and evaluation continue. An
  allowlisted-lineage CHALLENGER may be promoted only under the policy; otherwise the venue stays
  sender-less until a reviewed commit adds a lineage root. Fill-dependent windows pause and extend.

---

## 6. Reuse map (extend these, never rebuild them)

| Need | Reuse | Where |
|---|---|---|
| Manifest strictness, raw-byte sha | `load_family_manifest` (widen containment only) | `family_manifest.py:285-296` |
| Real-order authorisation | `live_orders_authorized` (add the lineage allowlist) | `live_orders_gate.py:130-190` |
| Integrity halt | `record_*`, `family_halt_state`, read-only reader | `trial_day_latch.py:1004,1118,1155,1193,354` |
| Entry guard slot | `try_submit` (add an `entry_veto` slot beside `submit_veto`) | `fq/strategy.py:629-643` |
| In-node periodic actor | `FeeDriftProbeActor` pattern | `app/trade.py:442-484` |
| Order tags; order→fill join | exit tag prefixes; `FILL_*` keys | `exit_tags.py`; `exec/client.py:400-447` |
| Decision JSONL and retention | `decisions/`, `OfferTape`, funnel actor | `crh/composition.py:568-602` |
| Label store and scoring | `scored_trial_store`; `ScoredTrial`, `ScoreRefusal` | `scored_trial_store.py:24-31`; `trial_scorer.py:131-160` |
| Bootstrap, sequential looks | `roi_bound` constants; `run_sequential_looks` | `roi_bound.py:93-100`; `family_tally_v2.py:625` |
| Promotion predicates | `evaluate_c_*`, `assemble_outcome` | `promotion_criteria.py:195-613` |
| Fitters and holdout | `fit_calibration`, `open_holdout`, `compute_n_min`, `write_artefact` | `nbp_calibration.py:1280,353,309,2643` |
| Market baseline; calibration leg | `wp7b_market_as_forecaster`; `evaluate_calibration_leg` | `scripts/analysis/…:1128`; `forecast_conditional_scoring.py:392` |
| Drift and freshness | `check_freshness`, `check_drift` | `nbp_learning_nightly.py:286,342` |
| Alerts | `resolve_alert_sink`, `emit_alert`, `AlertPayload` | `runtime/health.py:392,479`; `health_model.py:217` |

---

## 7. Risks

| Risk | Mitigation built into the contracts |
|---|---|
| **Statistical capacity.** About 5 fills a day and admissible n = 0; a child restarts its clock (L-34). | Promotion rests on offline evidence plus a forward shadow (large n from the tape), never on a child's live n. Live sequential demotes. Rate limit, α-spend and `n_min`/`eta` are on every verdict. |
| **Forecast edge closed (09-20).** | Promotion requires beating the market-implied baseline on the traded rung, net of fee and slippage (C4 (a)–(c)). |
| **Adaptive overfit to holdout** | Rolling forward holdout; the sealed holdout opened once per lineage; α_k halving (C4). |
| **Train/serve skew** | `forecast_input_sha256` per decision; a parity verdict (`_evaluate_independently`) maps to DEMOTE; the loader accepts only parity-tested forms. |
| **Leakage** | C3 assertions refuse a lineage write, and the forward window is disjoint from training. |
| **Halt strands positions** | Entry-only registry demotion. The exec-store halt is reserved for INTEGRITY and TERMINAL causes. A demoted family holds to settlement. |
| **Registry tamper or SPOF** | Hash chain, triggers, export, code pins, node re-derivation. Any failure gives no sender, never a fallback. Dead-man. |
| **Oscillation** | §4.5 damping with code ceilings. |
| **Concurrent agents; venv; memory; PROGRESS** | Disjoint Wave 1 ownership, per-agent scratchpads, no `git stash`, no `uv`, re-gate per merge; §5.2 caps; status in this README. |

---

## 8. Open decisions

Rev 1's OD-1 to OD-5 are settled, none as an operator decision. **OD-1:** INTEGRITY freezes the
venue until the CLI clear (L-48), and RECOVERABLE causes no longer use it. **OD-2:** activation is
at the next LAUNCH inside the safe window. **OD-3:** fee drift is TERMINAL. **OD-4:** challengers are
judged offline and by forward shadow (G1). **OD-5:** refusals are written on transition.

**Remaining choice for the AUT-5 policy ruling's own peer review, not for the operator:** the
numeric values of α_total, M, the forward-day minimum and the drawdown limit.

---

## 9. Contradictions found (README and rulings versus code)

1. The nightly fits nothing (G12), so AUT-3 starts from the fitters. 2. "Demotion is fail-safe"
holds only for the entry-only registry demotion, because the exec-store halt blocks exits (G5). 3.
Commit-free promotion needs the one-time lineage allowlist widening (§4.2, G4). 4. The policy ruling
must supersede D11 explicitly for allowlisted lineages. 5. With one sender per node (G1), challengers
are measured by forward shadow. 6. A rollback needs the containment widening (C5). 7. **New:** the
CRH kinds send with no live-orders gate (G19), so the registry never names them CHAMPION until they
route through the gate.


## §R2 Defect disposition (review `reviews/ARCH-r1-merged.md`)

All 29 FIXED, 0 REJECTED. Partial premise corrections are noted against the code.

| X | Disposition | Where fixed / evidence |
|---|---|---|
| X1 | FIXED | G19 (`app/trade.py:546-673` vs `:740`); `LIVE_GATE_ROUTED_KINDS` in the C5 resolver and §4.2; test named |
| X2 | FIXED | §4.2 literal-only AST test and LAUNCH re-hash; §4.3 `engine_code_sha` committed pins |
| X3 | FIXED | C5 storage, hash chain, triggers, export, `decided_by`/`invocation_id`, engine unit, `ReadOnlyPaths`, node re-derivation |
| X4 | FIXED | C4 `FORWARD_SHADOW` (a)–(c); C5 table: an offline PASS alone never reaches CHAMPION |
| X5 | FIXED | C4 rolling forward holdout, sealed holdout opened once per lineage, α_k spend; C5 `lineage_counters` |
| X6 | FIXED | §4.4 preconditions; a demoted family holds to settlement; G17 exit allowlist never widened |
| X7 | FIXED | C5 activation (`next_*`, 16:40–17:00Z safe window, `(family_id, seq)` env handoff, boot refusal); G21 budget tests |
| X8 | FIXED | C5 one-in-{CHAMPION,HALTED} invariant, DISPLACED, RESUME guard, v4 seeded RETIRED; CAS test |
| X9 | FIXED | C5 exec-store halt mirror table (G20); fee drift TERMINAL; RECOVERABLE causes are registry DEMOTEs, so self-heal and RESUME are reachable |
| X10 | FIXED | C5 pickup 1 and 3 (four widening sites incl. `settings.py:183,366-388`); C3 `O_NOFOLLOW`, 0444, single read |
| X11 | FIXED | §4.2 manifest equality with an explicit key allowlist; `exit_gate.py` code-only test |
| X12 | FIXED | §4.5 damping with code ceilings; DEMOTE/HALT clear `rollback_eligible` |
| X13 | FIXED | C5 failure behaviour (no lineage-root fallback, no permit-bearing composition); flag fixed in the unit; veto clears on a good read |
| X14 | FIXED | §4.6 dead-man timer and daily canary |
| X15 | FIXED | §5.3 AUT-7b drill (PROMOTE, DEMOTE, RESUME, ROLLBACK) with its own clock; post-KILL state; README AUT-5/AUT-7 |
| X16 | FIXED | C2 net-position reconciliation, NO-offsets-YES RED test, −0.37/+0.37 root cause first, `window_complete` only |
| X17 | FIXED | §5.2 slot table, flock queue, `MemoryMax` per job, sampled rerun; the blackout is a heavy-job rule and the 02:05Z nightly is 4G |
| X18 | FIXED | C1 `eval_ns` is recorded and authoritative; recompute test |
| X19 | FIXED | §5.3 qualifying days, ≥5 real fills, tagged canary fills, evidence-class line; README scale rule |
| X20 | FIXED | C4 engine acceptance against the policy `detector → action_class` map |
| X21 | FIXED | §2 L-1 verdict: REDUCING insufficient (`risk/engine.pyx:1150-1163`; G24). `account_presence_halt.py:171` sets HALTED, not REDUCING |
| X22 | FIXED | C3 `ablation_artefact_sha256` must differ; `forecast_quantile_ladder:rung_recalibration` named |
| X23 | FIXED | C5 idempotency: no `expected_prior_seq` in the id, replay is a logged no-op, the CAS-conflict→shadow row is dropped |
| X24 | FIXED | C4 acceptance (producer pins, input roots, ruling sha); verdict dirs 0700; producers are separate units |
| X25 | FIXED | §3 payload hygiene; `venue_order_id_sha256`; scan test |
| X26 | FIXED | C5 mirror table: a read failure is INTEGRITY for that run, then HALTED/INTEGRITY past the horizon |
| X27 | FIXED | §4.7 `test_autonomy_never_imports_order_path`, `test_autonomy_alert_egress_not_widened` |
| X28 | FIXED | C6 `RefusingPlugin` for kinds with no non-RETIRED family |
| X29 | FIXED | This document is within the 750-line cap |

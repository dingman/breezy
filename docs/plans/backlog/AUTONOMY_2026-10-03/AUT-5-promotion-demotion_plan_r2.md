# AUT-5 — Automated promotion and demotion: registry, policy engine, pre-registered policy ruling (plan r2)

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-5 |
| Title | Automated promotion and demotion (C5 registry, engine, `RegistryWatchActor`, drawdown producer, policy ruling) |
| Round | r2 (2026-10-03). r1 (`AUT-5-promotion-demotion_plan_r1.md`) is kept unchanged. r1 review: `reviews/AUT-5-r1-merged.md` (security 82, trading 70, final 70, NOT READY). Every M1–M23 is disposed in §R2. |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 5**, frozen copy `reviews/snapshots/ARCH_rev5.md`, sha256 `5d2b75fa77e2c0abaaa478bd38d32e7e06ac98c8057ce50a5045f0dd0eff8403` (equal to the live file at writing). Code facts checked at repo `4b8347a6`. |
| Current score | 1 (README "Current scores") |
| Target | 3 |
| Upstream | AUT-2 (C2 labels incl. `drill`/`voided_pair`/`slippage_defect`/`unattributed`; C4 intraday and post-STOP `RECONCILIATION`; `health.label_lag`), AUT-4 (C4 `OFFLINE_CHALLENGER`, `FORWARD_SHADOW` incl. the paired predicate, `LIVE_SEQUENTIAL` `live.sequential`/`live.kill_clock`, feasibility record), AUT-6 (C4 `DRIFT`/`HEALTH`, intraday producer, `deliver_with_proof`, delivery journal, canary, `drill.inject` detector), AUT-1 (C1 `EntryVeto` writer, `health.capture_join`), AUT-3 (C3 candidates, K_max MINTs per window) |
| Downstream | AUT-7 (co-writes C5 through the engine API; AUT-7b drill is this area's live proof), AUT-1 (reads `registry_seq` and `drill` from the fold), AUT-6 (veto and alert surface), AUT-2 (consumes the STOP-completion signal) |
| Status | PLANNING. Nothing here is implemented. Plan only: no commit, stash, `uv`/`pip` or `systemctl` action was taken to write it. |

## 1. Goal state

**README score-3 criterion (verbatim).**
> - A durable registry of families and artefacts with the state machine SHADOW → CHALLENGER → CHAMPION → RETIRED.
> - An automated policy engine executes a **pre-registered promotion policy ruling**:
>   - It promotes a challenger to live-send, or swaps an artefact, when that policy's evidence thresholds are met.
>   - It demotes or halts automatically on a negative sequential verdict, a drawdown limit, drift (AUT-6) or a failed health check.
>   - Every action stays within the operator caps and inside the enabled envelope.
> - Every transition is audited, alerted with delivery, and idempotent across restarts.
> - The supervisor and node pick up a transition with no code change and no human commit.

**README live proof (verbatim).**
> PROMOTE, DEMOTE and RESUME each carried out live end to end through the production engine with no human or agent commit, with evidence in the registry chain, the export and the node log. The AUT-7b drill (ARCH §5.3: a byte-identical child of the champion promoted, demoted by an injected RECOVERABLE fault through the live detector path, resumed, then rolled back) satisfies this. An injected fault counts only if it runs through the live code path.

**ARCH Rev 5 §10 AUT-5 obligations (verbatim).**
> the policy ruling and its `autonomy-policy/v1` block (every key, every value within bounds, drill clause and window, `forward_window_days` and anchor, `attest_required_verdict_kinds`, detector cause classes); the engine's daily, intraday (restrictive plus ATTEST, heartbeat) and pre-launch modes, staggered timers and lock; the ATTEST cadence meeting the §4.5 invariant (W1); the watch actor (loop-thread bridge); `entry_guard` with its exact-key read path, the injected `FillKeySchema`, the lint-imports contract and the per-tick cache, plus the required `entry_veto` slot per kind (W6, W10); HWM key handling and the `breezy-registry-hwm-reset` CLI (restrictiveness check, counter carry, export supersession; W4); the demand directory and its archive (W16); the supervisor's journaled STOP-completion signal (W8); supervisor env handoff, the relaunch rule, the post-launch SWAP_CANCEL relaunch and the registry-aware `breezy-trade-relaunch` helper replacing the hand `systemd-run` runbook; the dead-man; bootstrap; the 15 min SLO test harness.

**Obligation → WP map.**

| Obligation | WP |
|---|---|
| Policy ruling and block (every key, drill clause and window, `forward_window_days` + anchor, ATTEST keys, cause classes incl. `DRILL`) | WP3 |
| Engine daily / intraday (restrictive + ATTEST, heartbeat) / pre-launch; staggered timers; phase-scoped lock (M4) | WP4 |
| ATTEST cadence meeting the §4.5 invariant | WP4 (`test_attest_cadence_has_no_expiry_gap`) |
| Watch actor (loop-thread bridge, `busy_timeout`, per-tick cache) | WP5 |
| `entry_guard` exact-key path, `FillKeySchema`, lint-imports contract | WP1 (contract), WP2 (guard) |
| Required `entry_veto` slot per kind | WP5 |
| HWM key; `breezy-registry-hwm-reset` (restrictiveness, counter carry, export supersession) | WP5 (key), WP8 (CLI) |
| Demand directory and archive | WP4 |
| Supervisor journaled STOP-completion signal; post-STOP reconcile unit wrapper | WP6 (signal), WP4 (unit files) |
| Env handoff, relaunch rule, post-launch SWAP_CANCEL relaunch | WP6 |
| `breezy-trade-relaunch` | WP7 |
| Dead-man | WP8 |
| Bootstrap | WP4 (`--mode bootstrap`), WP10 (run) |
| 15 min SLO harness incl. the daily-lock case | WP5 + WP4 |
| Drawdown producer (M6; ARCH names no producer) | WP11 |
| Lineage allowlist widening; widening-stage flag flip | WP9 |
| Staged activation and live proof | WP10 |

## 2. L-1 null hypothesis and reuse

| New component | Nautilus / existing Breezy capability checked | Verdict |
|---|---|---|
| C5 registry (store, chain, fold) | Nautilus: no artefact registry, champion/challenger state or promotion engine (ARCH §2 L-1; `WORK_BREAKDOWN:288`). Breezy: `SqliteStateStore` (`runtime/sqlite_store.py:117-176`) is a thread-confined KV with WAL and no iteration (G7); the exec store's flock is node-held (G6). `FamilyManifest` exact-set (`family_manifest.py:122-137`). | **Build**, as ARCH C5 mandates (`journal_mode=DELETE`). Reuse the exact-set and raw-byte-sha conventions of `load_family_manifest` (`family_manifest.py:285-296`) and the `mode=ro` URI reader (`trial_day_latch.py:354-379`, which already passes `timeout=busy_timeout_s`, default 1.0 s). |
| Policy engine | `promotion_criteria.py`: `evaluate_c_kill` (`:195-281`), `evaluate_c_n` (`:486-497`), `evaluate_c_estimator` (`:526-556`), `assemble_outcome` (`:613-637`). The proposal generator is advisory only (G14). | **Build the engine; reuse the predicates** through AUT-4's producers. The engine never recomputes statistics. |
| Drawdown producer (M6) | No existing drawdown statistic over labels. `realized_pnl` is a C2 field (AUT-2). `run_sequential_looks` (`family_tally_v2.py:625`) is a sequential test, not a drawdown. | **Build a small producer** in `analysis/autonomy_producers/drawdown.py`: a pure fold over C2 rows (cumulative realised P&L ÷ cumulative cost, peak-to-trough). No new statistic semantics beyond the ruling's named formula. |
| Commit-free promotion authorisation | `live_orders_authorized` with a literal allowlist plus re-hash (`live_orders_gate.py:76-84,130-189`). | **Extend.** One reviewed row in `_LINEAGE_POLICY_ALLOWLIST` (WP9). The re-hash path is reused unchanged. |
| Engine policy identity before WP9 (M3) | None: in r1 the engine took the sha from `_LINEAGE_POLICY_ALLOWLIST`, which does not exist until WP9 (after L1), so stages S and L1 had no policy. | **Build** `pins.POLICY_RULING_PIN`, a literal `(ruling_id, sha256)` committed in WP3's filing commit; WP9 asserts equality with the allowlist row. |
| Entry-only demotion | Nautilus `TradingState.REDUCING` (`risk/engine.pyx:1150-1163`) denies a BUY only when net long and is node-global (ARCH §2). FQ `try_submit` guard chain (`fq/strategy.py:629-645`). | **Extend the native guard slot.** A separate required `entry_veto` slot; `submit_veto` reaches the exec client (G23), so it is not reused. |
| In-node registry watch | `FeeDriftProbeActor` timer → `asyncio.run_coroutine_threadsafe` (`fee_drift_probe.py:358-372`); `LiveClock` callbacks on `_DummyThread` (`tests/contract/test_live_timer_thread_affinity.py:90-119`). | **Reuse the pattern**; no new threading primitive. |
| Rung net-position guard | Exec-store exact keys `fill_index/<instrument_id>` and `fill/<venue_order_id>` (`adapters/polymarket_us/exec/client.py:408-447`), `DurableFillRecord` with signed `order_side` and `cumulative_qty` (`:923-966`), decoder `DurableFillRecord.from_bytes` (`:1004-1066`). Nautilus `Portfolio.net_position` depends on unverified composite-leg netting (L-44). | **Reuse the durable fills** through an injected `FillKeySchema` (ARCH W6); the adapter implements it; `app/trade.py` injects it. |
| Spend continuity across a sender change (M8) | `DailySpendLedger` is process-local and in memory (`operator_controls.py:264-305`), seeded once per process by `_seed_spend_from_durable_fills` (`exec/client.py:2216-2243`) from the venue store, walking provider instruments **plus today's day index** (`:2213`); the budget-exhausted key is venue-scoped (`exec/client.py:399`, G21). | **Reuse unchanged.** §3.12 states the inheritance argument; the named test pins it. No new ledger. |
| Supervisor pickup and STOP signal | `_do_launch` (`trade_supervisor.py:1209-1300`) and spawns at `:1289`, `:1379`, `:1631`, `:1982` forward `os.environ`. `_do_stop_prior` (`:1131-1190`) logs `stop_prior_noop` / `stop_prior_sigterm` / `stop_prior_refused` / `stop_prior_race_refused` and polls `intent_lock_free` (`:1185-1188`), but writes **no** durable completion record. Schedule poll 60 s, relaunch-check poll 15 s (`trade_supervisor_core.py:1866,1874`). | **Extend.** One pure `build_child_env`, a resolver port, and a STOP-completion file written only when the intent lock is verified free. No new scheduler. |
| Relaunch helper | Hand runbook (memory note `hand-relaunch-mechanics`). | **Replace with a supervisor-executed request file** (§3.7). |
| Halt mirror | `read_family_halt_rows_readonly`, `decode_family_halt_state` (`trial_day_latch.py:354`, G20). | **Reuse read-only**; contingent move-only extraction to `persistence/autonomy/halt_rows.py` if the engine closure would otherwise pull `breezy.strategy.*`. |
| Alert delivery | `deliver_with_proof` (AUT-6, `runtime/alert_delivery.py`, ARCH §4.6). | **Consume.** AUT-5 never writes its own sink. |
| Import-closure hash at runtime (M16) | grimp is the engine behind `lint-imports`; building its graph at every 5-minute oneshot start costs seconds and hundreds of MB. | **Gate-time grimp, runtime manifest.** A committed module-list manifest, verified against grimp in the gate; runtime hashes file bytes only. |
| Operator halt tools | `breezy-set-family-halt` / `breezy-clear-family-halt`. | **Unchanged.** Mirrored read-only. |

## 3. Design

### 3.1 Package layout and layers

Layer rule (`pyproject.toml:74-101`): `app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain`. Live packages never import `breezy.analysis` (`:128-151`).

| Module | Layer | Contents |
|---|---|---|
| `src/breezy/persistence/autonomy/__init__.py` | persistence | Public names only. |
| `…/autonomy/canonical.py` | persistence | `canonical_json(obj) -> bytes` (sorted keys, no NaN, explicit serialisers, never `dataclasses.asdict`); `sha256_hex(b)`. |
| `…/autonomy/single_read.py` | persistence | `read_once_nofollow(path, *, root, max_bytes) -> bytes`: `lstat` walk refusing any symlink component, `os.open(O_RDONLY\|O_NOFOLLOW)`, one read, size cap; `SingleReadRefused(reason)`. |
| `…/autonomy/schemas.py` | persistence | Frozen dataclasses and enums: `State`; `Kind` (BOOTSTRAP, MINT, PROMOTE, DRILL_ADMIT, DRILL_PROMOTE, ROLLBACK, SUPERSEDE, DISPLACED, ACTIVATE, SWAP_CANCEL, ATTEST, DEMOTE, HALT, RESUME, RETIRE, HWM_RESET); `CauseClass` (RECOVERABLE_MODEL, RECOVERABLE_INFRA, **DRILL**, TERMINAL, INTEGRITY); `ActionClass`; `WriterMode` (DAILY, INTRADAY, PRELAUNCH, BOOTSTRAP, OPERATOR_CLI); `TransitionRow` (every C5 column incl. `carried_counters` on HWM_RESET); `Verdict`; `DemandRecord`; `Heartbeat`; `StopComplete` (`stop_complete/v1`); `RelaunchRequest`; `ResolvedFamily`. |
| `…/autonomy/transitions.py` | persistence | `ALLOWED` (ARCH C5 table plus the two genesis BOOTSTRAP rows, X2); `KIND_MASK: Final[Mapping[WriterMode, frozenset[Kind]]]` (§3.2, M12); `WIDENING_KINDS`; `validate(fold, row, *, mode) -> None \| RefusalReason`. |
| `…/autonomy/registry_store.py` | persistence | `RegistryStore` (rw) and `RegistryReader` (`mode=ro`, `busy_timeout` parameter). DDL, triggers, CAS, chain, mask and stage-flag enforcement, K_max-per-window enforcement, export writer with `export_seq`, cache refold. |
| `…/autonomy/fold.py` | persistence | Pure `fold(rows, venue, now_ns) -> FoldResult` (states, pending, lapse, post-launch voiding, counters on effect, `carried_counters` floors, `drill_episode`, `rollback_eligible`, `demoted_for_cause`, `terminal_frozen`, INTEGRITY freeze, forward-window MINT counts). |
| `…/autonomy/replay.py` | persistence | `replay_full(rows, *, verdict_root, artefact_root) -> ReplayResult` (M13): re-runs `transitions.validate` row by row over the growing fold, resolves `cause_verdict_ids` of every widening row to a file whose sha equals the id, and checks that artefact bytes equal each binding row's `artefact_sha256`. |
| `…/autonomy/resolver.py` | persistence | `resolve_sending_family(...) -> ResolvedFamily \| ResolverRefusal`. Calls `replay_full`. The only reader of `BREEZY_FAMILY_SOURCE`. |
| `…/autonomy/policy.py` | persistence | `load_policy_block(repo_root, pin) -> PolicyBlock \| PolicyUnavailable`: single read of the deploy copy, sha equal to `pins.POLICY_RULING_PIN`, exactly one fenced `autonomy-policy/v1` block, strict JSON, exact-set keys, every value within `pins` ceilings. |
| `…/autonomy/pins.py` | persistence | Literal ceilings (ARCH §4.5); `ENGINE_SOURCE_SHA256`; `PRODUCER_SOURCE_SHA256`; `REVOKED_SOURCE_SHA256`; `LIVE_GATE_ROUTED_KINDS`; `BOOTSTRAP_SEED`; **`POLICY_RULING_PIN`** (M3); **`ENABLED_WIDENING_KINDS`** (M11); **`FALLBACK_RESTRICTIVE_MAP`** (M10); `ENGINE_LOCK_MAX_HOLD_S = 60` (M4); `RELAUNCH_REQUEST_TTL_S = 120` (M14); `WATCH_BUSY_TIMEOUT_MS = 250` (M17). |
| `…/autonomy/closure_manifest.py` | persistence | `CLOSURE_MODULES: Final[Mapping[str, tuple[str, ...]]]`, keyed by component (`engine`, each producer id). Literal, regenerated by `scripts/ci/regen_closure_manifest.py` (M16). |
| `…/autonomy/closure.py` | persistence | `closure_sha256(component) -> str`: for each module in the manifest, `importlib.util.find_spec(m).origin`, one `read_once_nofollow`, sorted `(module, bytes)`; excludes `pins` and `closure_manifest`. No grimp at runtime. `closure_from_grimp(entry)` is gate-only. |
| `…/autonomy/entry_guard.py` | persistence | `FillKeySchema` Protocol (`index_key(instrument_id) -> str`, `record_key(venue_order_id) -> str`, `decode_index(raw) -> tuple[str, ...]`, `decode(raw) -> tuple[str, Decimal]`); `rung_has_net_position(base_slug, *, store_path, schema, legs) -> bool \| GuardUnreadable` (exact keys only through `mode=ro`, leg-signed netting per C2). |
| `…/autonomy/plugin.py` | persistence | C6 Protocols plus `RefusingPlugin`. |
| `src/breezy/strategy/autonomy/node_plugins.py` | strategy | `NODE_PLUGINS` (FQ full; three `RefusingPlugin`s). |
| `src/breezy/analysis/autonomy/offline_plugins.py` | analysis | `OFFLINE_PLUGINS` (same key set). |
| `src/breezy/strategy/autonomy/registry_watch_actor.py` | strategy | `RegistryWatchActor(Actor)`, `RegistryWatchConfig`, `VetoReason` (ARCH closed enum), per-tick guard cache. |
| `src/breezy/adapters/polymarket_us/exec/fill_key_schema.py` | adapters | `PolymarketUsFillKeySchema`: implements `FillKeySchema` with the existing prefix constants and `DurableFillRecord.from_bytes`; no new key is written. |
| `src/breezy/analysis/autonomy_engine/{__init__,cli,phases,daily,intraday,prelaunch,bootstrap,acceptance,fallback,mirror,demand,heartbeat,attest,mint,drill,export,alert_ledger}.py` | analysis | The engine (§3.3). Console script `breezy-autonomy-engine`. |
| `src/breezy/analysis/autonomy_producers/drawdown.py` | analysis | The `live.drawdown` producer (§3.11). Console script `breezy-autonomy-producer-drawdown`. |
| `src/breezy/runtime/autonomy_deadman.py` | runtime | `breezy-autonomy-deadman`. |
| `src/breezy/runtime/registry_hwm_reset_cli.py` | runtime | `breezy-registry-hwm-reset` (Rev 5 rule). |
| `src/breezy/runtime/registry_verify_cli.py` | runtime | `breezy-registry-verify`. |
| `src/breezy/runtime/trade_relaunch_cli.py` | runtime | `breezy-trade-relaunch`. |

`entry_guard` sits in `persistence` as ARCH names it; the adapter-owned key prefixes and decoder arrive through `FillKeySchema` (ARCH W6), pinned by the forbidden contract `breezy.persistence.autonomy ↛ breezy.adapters`.

### 3.2 C5 store

- **Path and mode.** `~/.local/share/breezy/registry/registry.sqlite`, dir 0700, file 0600, `journal_mode=DELETE`, `synchronous=FULL`. Shadow stage: `~/.local/share/breezy/registry-shadow/`, identical layout.
- **DDL.** `transitions` holds every ARCH C5 column. `UNIQUE(venue, venue_seq)`, `UNIQUE(transition_id)`. `BEFORE UPDATE` / `BEFORE DELETE` triggers `RAISE(ABORT,'append-only')`. Derived caches `families`, `projection`, `lineage_counters`. `meta(schema='registry/v1')`.
- **Write path.** `RegistryStore.append(rows, *, expected_prior_seq, mode: WriterMode) -> AppendResult`. One `BEGIN IMMEDIATE`. If every `transition_id` exists: logged no-op. Otherwise, **inside the store and before insert** (M12, M11, W7):
  1. every row's kind ∈ `KIND_MASK[mode]`, else `KindRefused(mode, kind)`;
  2. every widening row's kind ∈ `pins.ENABLED_WIDENING_KINDS`, else `WideningNotEnabled(kind)`;
  3. a non-drill MINT is refused once the lineage's current forward window (`forward_window_days` from `forward_window_anchor_date`, store limits from the loaded policy, clamped by the `pins` ceiling K_max ≤ 4) already holds K_max MINTs, and once one MINT exists for the lineage that UTC day (`MintRefused(k_max_in_window|per_day)`). Drill MINTs (C3 no-new-lineage) are not counted;
  4. CAS `max(venue_seq) == expected_prior_seq`;
  5. `transitions.validate` against `fold(prior ∪ new)`;
  6. insert, extend chain, refold caches, `COMMIT`.
- **`KIND_MASK` (literal).**

| `WriterMode` | Kinds |
|---|---|
| `INTRADAY` | DEMOTE, HALT, SWAP_CANCEL, ATTEST |
| `PRELAUNCH` | ACTIVATE, SWAP_CANCEL |
| `DAILY` | MINT, PROMOTE, DRILL_ADMIT, DRILL_PROMOTE, ROLLBACK, SUPERSEDE, DISPLACED, SWAP_CANCEL, DEMOTE, HALT, RESUME, RETIRE |
| `BOOTSTRAP` | BOOTSTRAP |
| `OPERATOR_CLI` | HWM_RESET, DEMOTE, HALT, SWAP_CANCEL, RETIRE (the Rev 5 restrictive re-application) |

- **`WIDENING_KINDS`** = {PROMOTE (→CHAMPION), DRILL_PROMOTE, ROLLBACK, RESUME, ACTIVATE, SUPERSEDE, DISPLACED, DRILL_ADMIT}. ATTEST and every restrictive kind are never masked by the stage flag.
- **`pins.ENABLED_WIDENING_KINDS` by stage** (each change is a reviewed commit, made before the stage starts, never inside the drill's no-commit window):
  - WP1 to stage S: `frozenset()`.
  - Stage L1: `frozenset({RESUME})`. RESUME restores the already-bootstrapped incumbent (no new sender, no new artefact), and without it a RECOVERABLE_INFRA DEMOTE in L1 would strand the venue until L2.
  - Stage L2 (flipped in WP9's commit): `WIDENING_KINDS`.
- **Chain.** `genesis = sha256(b"registry/v1|" + venue)`; `transition_hash = sha256(canonical_row ‖ prev_transition_hash)`.
- **Bootstrap (X2, carried as P5-1/P5-2).** The ARCH table allows only `∅ → SHADOW` for BOOTSTRAP, yet ARCH Bootstrap seeds CHAMPION and RETIRED. Two rows are legal **only in the genesis transaction of a venue chain** and only for ids in `pins.BOOTSTRAP_SEED`: `∅ → CHAMPION` for `pm_us_crh_fq_v1` (its committed `_LIVE_ORDERS_ALLOWLIST` triple stands, the fq_v1 bootstrap exemption, X1), and `∅ → RETIRED` for `pm_us_crh_v4`, `pm_us_crh_cont`, `pm_us_crh_v2`. Each carries the committed manifest and artefact sha256. Pinned by `test_registry_transition_table_is_exact` and `test_bootstrap_rows_only_in_genesis_transaction`.
- **Exports.** The daily pass writes `~/.local/share/breezy/evidence/registry/registry_<venue>_<YYYY-MM-DD>.jsonl` (0444): every row since the previous export plus `{"chain_head", "venue_seq", "export_seq"}` with `export_seq` monotone. Written once per date (L-50). Readers verify the chain prefix against the export with the **highest `export_seq`**, so an HWM_RESET export supersedes (W4).
- **Directories.** `registry/families/` (0444 child manifests), `registry/families/artefacts/<sha>.json` (0444), `registry/demand/<venue>/`, `registry/heartbeat/<venue>.json`, `registry/drill/marker.json` (root-relative, §3.10), `registry/alert_ledger/<date>.jsonl`, `registry/engine.lock`. Archive: `evidence/demand/<venue>/` (W16). All writes atomic through `mkstemp` + `os.replace`.

### 3.3 Engine (`breezy-autonomy-engine --mode {daily,intraday,prelaunch,bootstrap}`)

**Common start, in order** (none of it under the lock):
1. `closure_sha256("engine")` (manifest-based, M16). Refuse (exit 2, CRITICAL `AUTONOMY_ENGINE_UNPINNED`) unless it is in `ENGINE_SOURCE_SHA256` and not in `REVOKED_SOURCE_SHA256`.
2. `policy.load_policy_block(repo_root, pins.POLICY_RULING_PIN)`. On `PolicyUnavailable` (pin empty, file missing, sha mismatch, parse failure, value looser than a ceiling) the run continues in **restrictive fallback** (§3.3.2) and raises CRITICAL `AUTONOMY_POLICY_UNAVAILABLE` once per UTC day.
3. Read the verified chain through `RegistryReader` and fold. Read and accept verdicts (§3.3.3). Compute the candidate rows for each phase.

Every transition carries `engine_code_sha`, `invocation_id` (uuid4), `decided_by="engine"`, `policy_ruling_id` and `policy_ruling_sha256` (in fallback: the pin's values, or empty strings when the pin is empty).

#### 3.3.1 Phase-scoped locking (M4)

The daily pass no longer holds `engine.lock` for its whole run. `phases.run_phase(name, build_rows, *, mode)`:
- acquires `registry/engine.lock` with `flock -w` (daily 120 s, intraday 90 s, prelaunch 60 s);
- re-reads only the chain delta above the head it folded, re-validates the phase's candidate rows (re-building them if the delta touched the same family), calls `RegistryStore.append(..., mode=...)`, and releases;
- refuses to call `append` if the hold has exceeded `ENGINE_LOCK_MAX_HOLD_S = 60` (it releases and defers the phase to the next pass, logging `engine_phase_deferred phase=<n>`). All I/O-heavy work (C3 reads, verdict acceptance, artefact copies, export rendering) happens **before** acquiring.

Daily phase order, each its own lock hold: **R** (exec-store mirror plus accepted FAIL → DEMOTE/HALT/SWAP_CANCEL) → RETIRE → MINT → SHADOW→CHALLENGER PROMOTE → CHALLENGER→CHAMPION PROMOTE (only if `promote_enabled`, §3.9) → RESUME → AUT-7 rollback selector (`engine.rollback.propose(fold)`) → drill steps → export → heartbeat. The restrictive phase is first, so the longest wait an intraday pass can see is one phase hold (≤ 60 s) plus margin, which is below its 90 s wait.

**Intraday on lock timeout.** If `flock -w 90` still fails, the intraday pass writes a restrictive-demand file (§3.3.5) for every accepted FAIL it computed, which needs no lock and only stops entries. It logs `engine_lock_timeout demand_written=<n>`, raises a WARNING and exits 0. The watch actor honours the demand on its next tick, so the 15 min SLO holds under lock contention. Tests: `test_restrictive_slo_met_while_daily_holds_lock` and `test_daily_lock_hold_never_exceeds_max_hold`.

#### 3.3.2 Restrictive fallback (M10)

When the policy is unavailable, the engine runs restrictive-only in every mode:
- It writes only DEMOTE, HALT and SWAP_CANCEL (the store's `KIND_MASK` still applies; the engine additionally refuses any other kind).
- The exec-store halt mirror runs unchanged; it needs no policy.
- Verdict acceptance replaces the policy-dependent checks with code: `prereg_ruling_sha256` must equal `pins.POLICY_RULING_PIN[1]` (when the pin is empty, **no** verdict is accepted and only the mirror acts); `declared_action_class` and the cause class come from `pins.FALLBACK_RESTRICTIVE_MAP`, a literal map holding only DEMOTE/HALT entries for the C6 required detector classes (`freshness.persist`, `liveness.permit_process`, `health.capture_join`, `health.alert_canary`, `reconciliation.net_position`, `reconciliation.post_stop`, `drift.forecast_input`, `drift.calibration_live`, `drift.fill_rate_slippage`, `parity.train_serve`, `live.sequential`, `live.kill_clock`, `live.drawdown`); validity ceilings come from `pins`.
- No ATTEST is written, so `registry_attest_expired` vetoes entries within `ATTEST_VERDICT_VALIDITY_H` (ARCH Y3). This is the intended fail-closed outcome.
- `test_policy_map_not_looser_than_fallback_map`: the filed block may not map any fallback detector to a weaker action class. This makes `test_demotion_never_requires_policy_and_is_immediate` consistent with policy-driven acceptance. The test now asserts that, with the policy file removed or tampered, an accepted FAIL from a fallback detector commits a DEMOTE in the same intraday pass, and that no non-restrictive row is written.

#### 3.3.3 Verdict acceptance (`acceptance.py`, ARCH C4 order)

1. `verdict/v1` exact-set.
2. `producer_code_sha ∈ PRODUCER_SOURCE_SHA256[producer_id]`.
3. Every `inputs[].sha256` resolves under that role's root.
4. `prereg_ruling_sha256 ==` the policy sha (fallback: the pin sha).
5. `declared_action_class ==` the map's entry for `detector` (policy map, or fallback map).
6. `valid_until_ns − produced_at_ns ≤ MAX_VERDICT_VALIDITY_H`, or ≤ `ATTEST_VERDICT_VALIDITY_H` for a verdict an ATTEST cites (W1); and `now < valid_until_ns`.
7. `subject_artefact_sha256 ==` the subject family's bound sha (Z1).
8. For `OFFLINE_CHALLENGER`: the candidate is within the lineage's K_max MINTs for its forward window (store-enforced, W7).

Any failure → `ERROR`, WARNING `AUTONOMY_VERDICT_ERROR`, no action.

#### 3.3.4 Modes, timers, units (M16: `TimeoutStartSec`, never `RuntimeMaxSec`)

All units are `Type=oneshot`. `RuntimeMaxSec=` has no effect on `Type=oneshot` (systemd.service(5): the runtime limit starts after activation, which a oneshot never leaves). Every bound below is `TimeoutStartSec=` (X9).

| Mode | Timer (UTC) | Bound | `MemoryMax` | Mask (`WriterMode`) | Work |
|---|---|---|---|---|---|
| `daily` | `OnCalendar=*-*-* 15:30:00` | `TimeoutStartSec=900` (ends ≤ 15:45Z) | 1G | `DAILY` | §3.3.1 phases. |
| `intraday` | `OnCalendar=*-*-* *:02/5:30` (150 s after AUT-6's `*:00/5` producer) | `TimeoutStartSec=120` | 512M | `INTRADAY` | Halt mirror; accepted FAIL → DEMOTE/HALT; SWAP_CANCEL for any pair effective today while `now ∈ [16:50Z, 17:00Z)` whose §4.4 re-check fails; **ATTEST** (§3.3.6); demand archive; drill-marker removal after the drill DEMOTE commits; heartbeat. |
| `prelaunch` | `OnCalendar=*-*-* 16:45:00` | `TimeoutStartSec=180` (ends ≤ 16:48Z) | 512M | `PRELAUNCH` | For each pair pending for today's LAUNCH: §4.4 with the sender-change horizon (§3.3.7). Pass → ACTIVATE; fail → SWAP_CANCEL. |
| `bootstrap` | manual `breezy-autonomy-engine@bootstrap.service` | `TimeoutStartSec=120` | 256M | `BOOTSTRAP` | Refuses (exit 2) if the venue chain is non-empty. |

- **Engine unit.** `deploy/systemd/breezy-autonomy-engine@.service` (template, `%i` = mode): `ProtectSystem=strict`, `ReadWritePaths=%h/.local/share/breezy/registry %h/.local/share/breezy/evidence`, `ReadOnlyPaths=%h/.local/share/breezy/derived %h/.local/share/breezy/state %h/breezy`, `EnvironmentFile=-%h/.config/breezy/alerts.env` (G27 only), `OnFailure=breezy-study-failed@%n.service`, **no** operator.env and **no** venue env files.
- **Post-STOP reconcile wrapper (M2).** `deploy/systemd/breezy-autonomy-reconcile-poststop.{service,timer}`: `OnCalendar=*-*-* 16:41:00`, `Type=oneshot`, `TimeoutStartSec=120` (= `POST_STOP_RECONCILE_RUNTIME_S`, ends ≤ 16:43Z), own lock `%h/.local/share/breezy/state/reconcile-poststop.lock`, `MemoryMax=512M`, `ReadOnlyPaths=%h/.local/share/breezy/state`, `ReadWritePaths=%h/.local/share/breezy/derived/verdicts`, the same env-file rule as the engine. `ExecStart` runs AUT-2's console script `breezy-autonomy-reconcile-poststop`. AUT-2 owns the producer and the verdict; AUT-5 owns the unit pair, the STOP signal it consumes (§3.6) and the pre-launch requirement.
- **Engine lock is never the studies flock** (Y23). Own-lock autonomy units together: engine 1G + producer-drawdown 512M + poststop 512M + dead-man 128M ≤ 4G (ARCH §5.2).

#### 3.3.5 Demand files (ARCH Y19, Z11, W16)

On the first failed append of a restrictive row, or on an intraday lock timeout, the engine writes `registry/demand/<venue>/<family_id>_<ts_ns>.json` (0444, `demand/v1`, ≤ `DEMAND_FILE_MAX_BYTES`), retries with bounded backoff for ≤ 60 s, then again every intraday pass. When the fold shows the family HALTED, RETIRED or not CHAMPION at a row later than `ts_ns`, the engine **moves** the file to `evidence/demand/<venue>/` by atomic rename and never unlinks it (`test_retired_demand_file_archived`).

#### 3.3.6 ATTEST cadence (M1/W1)

- **Writer.** The intraday pass, at most one ATTEST per venue per `ATTEST_PERIOD_H = 6`, for the CHAMPION (and for a HALTED family nothing is attested).
- **Citations.** One accepted PASS of each kind in `attest_required_verdict_kinds = ["HEALTH","RECONCILIATION"]`, from the cited detectors `liveness.permit_process` (AUT-6, intraday HEALTH) and `reconciliation.net_position` (AUT-2, intraday RECONCILIATION). Both producers run at least every `INTRADAY_ATTEST_VERDICT_PERIOD_MIN = 60`. Each cited verdict has `valid_until_ns − produced_at_ns ≤ ATTEST_VERDICT_VALIDITY_H = 8 h`.
- **Validity.** `attest_valid_until_ns = min(valid_until_ns)`, refused above `ts_ns + H`.
- **Invariant (ARCH §4.5).** `ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H ≤ ATTEST_VERDICT_VALIDITY_H`: 6 + (60 min + 150 s ≈ 1.04 h) + 0.5 = 7.54 ≤ 8. If one intraday pass is missed, the next one (5 min later) re-attempts. The 0.46 h of slack covers about 5 retried passes.
- **Tests.** `test_attest_cadence_has_no_expiry_gap` (fake clock, 48 h, the schedule table of every producer and engine timer: no instant past the newest ATTEST's `attest_valid_until_ns` while producers pass) and `test_attest_cites_required_kinds_and_caps_validity`.

#### 3.3.7 §4.4 horizons (M2; X10)

- **Sender change** (→CHAMPION rows, SUPERSEDE/DISPLACED partners, ACTIVATE, the supervisor's LAUNCH re-check):
  - ACTIVATE and the LAUNCH re-check need an accepted `reconciliation.post_stop` PASS with `produced_at_ns` later than **today's** STOP-completion file `ts_ns` (§3.6).
  - The 15:30Z daily pass writes the pending pair **before** today's STOP. It needs the post-STOP PASS of the **most recent completed** STOP (yesterday's), plus the newest intraday RECONCILIATION PASS within `reconciliation_horizon_h`. The authoritative check is ACTIVATE at 16:45Z (X10).
  - No STOP file, a stale file (`trading_day` ≠ today) or an INCONCLUSIVE post-STOP verdict means no ACTIVATE. The pre-launch pass writes SWAP_CANCEL (`test_prelaunch_requires_post_stop_reconciliation`).
- **RESUME** (non-sender-change, written by the daily pass): the newest intraday `reconciliation.net_position` PASS within `reconciliation_horizon_h = 8` (≤ `ATTEST_VERDICT_VALIDITY_H`). `reconciliation_horizon_h` applies to RESUME only.
- All §4.4 checks also require no OPEN or AMBIGUOUS intent (G30 read-only probe) and no INTEGRITY freeze.

#### 3.3.8 Alerts (M21)

- **Order.** Every alert is sent **after** `COMMIT`. Delivery failure never raises into the append path, never rolls back a row and never blocks the next phase.
- **Ledger.** Each `AUTONOMY_TRANSITION kind=<k> family=<id> seq=<n>` (CRITICAL for restrictive kinds, else INFO) goes through `deliver_with_proof`. The returned `DeliveryProof` is recorded in `registry/alert_ledger/<date>.jsonl` (0600, append-only: `{transition_id, attempt, delivered, status_class}`).
- **Retry.** Every engine pass re-sends transitions from today's and yesterday's ledger that lack `delivered=true`, at most `ALERT_OUTBOX_MAX` per pass.
- **Codes.** `AUTONOMY_TRANSITION`, `AUTONOMY_ENGINE_UNPINNED`, `AUTONOMY_POLICY_UNAVAILABLE`, `AUTONOMY_VERDICT_ERROR`, `AUTONOMY_ENGINE_LOCK_TIMEOUT`, `AUTONOMY_ENGINE_HEARTBEAT_STALE`, `AUTONOMY_CHAIN_STALE`, `REGISTRY_UNAVAILABLE`, `REGISTRY_REGRESSED`, `REGISTRY_HWM_RESET`, `TRADE_RELAUNCH_REQUEST`, `TRADE_RELAUNCH_OUTCOME`, `AUTONOMY_DRAWDOWN_INCONCLUSIVE`.
- **Tests.** `test_alert_failure_never_blocks_or_rolls_back_commit` and `test_autonomy_alert_payload_hygiene[<code>]`, parametrised over every code above. The second test builds each payload through its real constructor and runs the `AlertPayload` forbidden-content list (`registry/health_model.py:217-235`): no absolute path, env value, account or order id, or credential.

#### 3.3.9 Heartbeat

Every daily and intraday pass atomically rewrites `registry/heartbeat/<venue>.json` (0444): `{schema:"heartbeat/v1", ts_ns, invocation_id, engine_code_sha, chain_head, venue_seq}`.

### 3.4 Node wiring (`app/trade.py`, `settings.py`, FQ `strategy.py`, FQ `composition.py`)

- **`BREEZY_FAMILY_SOURCE`.** Unset, `registry_shadow` (stage S only, X7) or `registry`. Fixed in `deploy/systemd/breezy-trade-supervisor.service`; read only by `resolver.py` (`test_family_source_fixed_in_unit`).
- **Boot (`run`, `app/trade.py:905`) with source `registry`.** `resolve_sending_family` (full replay, §3.5). Refuse boot (`EXIT_CONFIG_ERROR`) unless the resolved id equals `BREEZY_SENDING_FAMILY_ID`, `BREEZY_RESOLVED_REGISTRY_SEQ` is a verified prefix, and the fold names the family CHAMPION or HALTED (Z7). The manifest comes from `parse_family_manifest(raw, *, origin)` (read/parse split of `load_family_manifest`, identical validation); `_validate_sending_family_manifest` (`settings.py:366`) takes the same object.
- **Y7 refusal.** Any registry row, or the exec-store key `autonomy/registry_hwm/<venue>`, with source ≠ `registry` while a sending family is set → `registry_source_required`.
- **Containment widening (L-12, four sites).** `family_manifest.py:169,266-282`, `app/trade.py:122`, `settings.py:183`, `settings.py:366-388` accept `~/.local/share/breezy/registry/families` only through `read_once_nofollow`; the `resolve()`, `..` and absolute refusals stay.
- **Required `entry_veto` slot (W10).** `ForecastQuantileLadderStrategy.__init__` gains a **keyword-only, required, non-Optional** `entry_veto: Callable[[InstrumentId], VetoReason | None]` with no default. The single production constructor (`fq/composition.py:246`) receives it from `_compose_forecast_quantile_ladder` (`app/trade.py:676`). `try_submit` order: permit → `entry_veto(take.instrument_id)` → `submit_veto` → `fee_verified` (`fq/strategy.py:629-645`); `submit_veto` and the exit seam untouched.
  - **Test call sites.** Five existing test files construct the strategy directly: `tests/strategy/forecast_quantile_ladder/test_strategy.py`, `test_sl13_wiring.py`, `test_sl13_s6_wiring.py`, `test_sl13b_tick_loop.py`, `test_d1_cache_union.py`. Each gains the one keyword argument `entry_veto=_never_veto` (a shared fixture returning `None`). No assertion is changed or removed; the diff is reviewed as mechanical.
  - **CRH kinds.** CRH kinds carry `RefusingPlugin` and are never composed as a registry sending family. Their constructors are untouched.
  - **Tests.** `test_compose_refuses_without_entry_veto_slot` is parametrised over `LIVE_GATE_ROUTED_KINDS`. It asserts a `TypeError` when the slot is omitted and that composition always wires it. A second case asserts that every kind outside `LIVE_GATE_ROUTED_KINDS` is refused at compose by its `RefusingPlugin` when the source is `registry`.
- **`RegistryWatchActor`** (composed into `extra_actors`).
  - `on_start`: `clock.set_timer("registry_watch", 60 s)`. The callback only schedules `self._tick_once()` with `asyncio.run_coroutine_threadsafe`, wrapped never to raise (L-16).
  - `_tick_once` (loop thread):
    - Opens `RegistryReader` with `timeout = WATCH_BUSY_TIMEOUT_MS / 1000 = 0.25` (M17), so a writer holding the rollback-journal lock blocks the loop for at most about 250 ms. On `SQLITE_BUSY` the tick is **not verified**: the state is unchanged and `last_verified_tick_age` keeps growing, so 3 busy ticks give `registry_unreadable`.
    - Reads the rows above its HWM, verifies the links from the stored head and re-checks the stored-head hash.
    - **Replays `transitions.validate`** on each new row against the in-memory fold (M13). A widening row (PROMOTE, DRILL_PROMOTE, ROLLBACK, RESUME, ACTIVATE) must also have every `cause_verdict_id` resolve to a file under `derived/verdicts/` whose sha equals the id (single read, cached by `transition_id` once verified). A widening row that fails gives `registry_unreadable` and a CRITICAL `REGISTRY_REGRESSED`, and the HWM does not advance. A restrictive row is always applied, because it can only stop entries.
    - Reads the heartbeat, demand files and today's plus yesterday's AUT-6 delivery journals (W13).
    - Updates veto state and writes `autonomy/registry_hwm/<venue>` only after a verified read.
    - It never reads `projection` or `families`.
  - **Per-tick guard cache (W6).** `dict[base_slug, bool | GuardUnreadable]`, cleared at the start of every tick and on every own `on_order_filled` for that slug, so `try_submit` walks a slug at most once per tick (`test_entry_guard_cache_invalidated_on_fill`).
  - **Veto API.** `entry_veto(instrument_id) -> VetoReason | None` (loop thread only, lock-free). It returns `registry_unreadable` before the first verified tick and whenever `last_verified_tick_age > WATCH_TICK_STALE_S`. `registry_halted` / `registry_not_champion` clear on the first verified tick that folds the family CHAMPION, so a RESUME needs no relaunch (W5). A reason change calls the injected `on_veto_transition(reason, cleared)`: AUT-1 wires the C1 `EntryVeto` record and AUT-6 the alert.
- **Per-kind rule.** Every kind in `LIVE_GATE_ROUTED_KINDS` passes `entry_veto` (`test_registry_champion_requires_live_orders_gate_for_every_kind` also asserts the slot is wired).

### 3.5 Same-uid threat model and full-fold replay (M13)

- **Threat model, stated.** Every Breezy process runs as one uid. A process with that uid can rewrite the registry, the exec store, unit files and the repo. AUT-5 does **not** defend against a malicious same-uid actor, which could also edit the code. It defends against bugs, crashes, stale state, hand relaunches and accidental edits, and it gives tamper evidence: per-venue chain, append-only triggers, 0444 exports with `export_seq`, and the node HWM in the node-held exec store. Its tamper resistance is that a forged row can only select among candidates the committed allowlists and sha-pinned rulings already authorise. The node re-derives that from bytes: committed root manifest equality, byte-identical artefact, a pinned `engine_code_sha` and a pinned policy sha.
- **Resolver (at every LAUNCH and relaunch).** `replay.replay_full` from genesis does three things. It re-runs `transitions.validate` row by row over the growing fold, so a row the store would have refused (for example a CHAMPION without a legal predecessor) gives `ResolverRefusal(replay_invalid)`. It resolves the `cause_verdict_ids` of every PROMOTE, DRILL_PROMOTE, ROLLBACK and RESUME to a verdict file whose sha256 equals the id, whose `kind` matches the row kind's requirement, and whose `subject_artefact_sha256` equals the row's binding (`replay_cause_unresolved`). It checks that the bytes under `registry/families/artefacts/<sha>.json` and the committed root artefact hash to the binding row's `artefact_sha256` (`replay_artefact_mismatch`).
- **Watch actor.** It runs the same checks incrementally per new row (§3.4), because the prefix is already verified by HWM.
- **Tests.** `test_resolver_replays_validate_over_full_fold`, `test_forged_promote_without_resolvable_cause_refused`, `test_artefact_bytes_must_equal_row_sha_at_resolve`, `test_watch_actor_rejects_widening_row_failing_replay`, `test_watch_actor_applies_restrictive_row_even_if_replay_fails`.

### 3.6 Supervisor wiring (`trade_supervisor.py`, `trade_supervisor_core.py`)

- **Port.** `SupervisorPorts.resolve_registry_family`; default `resolver.resolve_sending_family` with the production roots.
- **State.** `DaySchedulerState.resolved_family_id`, `resolved_registry_seq`, `resolved_at`; pure `record_registry_resolved`.
- **`build_child_env(base, state, *, permit_ceiling_ns)`** in `trade_supervisor_core.py`. It copies `base`. When the source is `registry`, it sets `BREEZY_SENDING_FAMILY_ID` and `BREEZY_RESOLVED_REGISTRY_SEQ`. When a ceiling is given, it sets `BREEZY_PERMIT_EXPIRY_CEILING_NS`. It touches nothing else (`test_child_env_touches_only_three_keys`, an AST scan for operator-control tokens). All four spawn sites call it (X3).
- **STOP-completion signal (M2, W8).** At the end of `_do_stop_prior` (`trade_supervisor.py:1131-1190`), after the SIGTERM poll loop (`:1185-1188`) or on `StopPriorAction.NOOP`, the supervisor checks `ports.intent_lock_free(lock_path)` once more. Only if the lock is free does it atomically write `~/.local/share/breezy/state/supervisor/stop_complete_<trading_day>.json` (0444, `stop_complete/v1`: `{schema, trading_day, ts_ns, outcome: "STOPPED"|"NOOP", intent_lock_free: true, supervisor_invocation_id}`, no pid, no path, no env) and log `stop_prior_complete day=<d> outcome=<o>`.
  - On `REFUSE_ALERT`, on `StopPriorRaceRefused`, or with the lock still held after the poll, it writes no file and logs `stop_prior_incomplete reason=<r>`.
  - A write failure logs the same line plus a CRITICAL through `deliver_with_proof` and never blocks LAUNCH. The incumbent launches as today. Only a sender change is cancelled, because the post-STOP producer then emits INCONCLUSIVE.
  - New port `write_stop_complete`. The unit's write access to `state/supervisor/` is asserted by `test_supervisor_unit_can_write_stop_signal_dir`.
  - Tests: `test_stop_completion_signal_written_only_when_lock_free` and `test_stop_signal_absent_on_refused_or_race`.
- **LAUNCH.** `_do_launch` resolves once, before the existing lock and intent checks. On `ResolverRefusal`: CRITICAL `REGISTRY_UNAVAILABLE` on the first refusal of the window, `done=False`, re-resolve each poll until 17:00Z, never a fallback. On success: `build_child_env(os.environ, state, permit_ceiling_ns=None)`.
- **§4.4 at LAUNCH.** If an ACTIVATE stands for today's pair, the supervisor re-runs the read-only preconditions with the sender-change horizon (§3.3.7). On failure: CRITICAL, no spawn, `done=False`. The intraday passes at 16:52:30Z and 16:57:30Z write the SWAP_CANCEL and the next re-resolve returns the incumbent. The supervisor starts no unit (X5).
- **Post-launch SWAP_CANCEL.** `_do_relaunch_check` (`:1304`) re-resolves each 15 s poll while `now < 17:00Z`. If the resolved id differs: `terminate_after_toctou_recheck`, wait for DISPOSED and lock release, `record_registry_resolved`, spawn the incumbent on the existing launch budget, log `registry_swap_voided_relaunch from=<a> to=<b>`.
- **Midday relaunch and boot retry** pass the latched id and seq (Z7).
- **Self-check.** `resolve_sending_family_id()` returns `state.resolved_family_id` under source `registry`.
- **Shadow source.** The supervisor resolves against the shadow root, logs `registry_resolve_shadow agree=<bool> env=<id> resolved=<id> seq=<n>`, and spawns the env family unchanged.

### 3.7 `breezy-trade-relaunch` (M14)

- **Interface.** `breezy-trade-relaunch --reason {venue_outage,node_wedged,operator_requested}`. No family or env argument.
- **Request.** It writes `~/.local/share/breezy/state/relaunch/request_<request_id>.json` (0600, atomic, `relaunch_request/v1`: `{ts_ns, reason, request_id}` with `request_id` a uuid4), then waits up to 600 s for `response_<request_id>.json`. Exit codes: 0 `RELAUNCHED`, 3 `REFUSED`, 4 timeout, 5 `EXPIRED`.
- **Validity and replay (M14).** The supervisor handler (`Phase.RELAUNCH_REQUEST`, checked each poll outside [16:40Z, 17:10Z)):
  1. reads each request with the single-read rule, and **unlinks it immediately** (before acting), whatever the outcome;
  2. ignores and answers `EXPIRED` any request with `now − ts_ns > RELAUNCH_REQUEST_TTL_S` (`test_stale_request_ignored`);
  3. deduplicates by `request_id` against `state/relaunch/handled_<date>.json` (atomic, 0600, today's and yesterday's ids). A replayed id gets `REFUSED duplicate` and no second spawn (`test_duplicate_request_id_handled_once`).
  - **TTL value: 120 s, not 60 s.** The schedule poll is 60 s (`trade_supervisor_core.py:1866`). With a 60 s TTL, a request written just after a poll would expire before the next one and be dropped. 120 s = two polls is the smallest TTL that guarantees pickup (`test_request_ttl_covers_two_schedule_polls`, asserted against the imported constant).
- **Handler recipe (in process).** Tracked pid holds the flock → no unterminated `SubmitOrder` in the log tail → `terminate_after_toctou_recheck` → DISPOSED and lock release → `probe_open_intent` (open → REFUSED `intent_open`) → under source `registry`, re-resolve with the LAUNCH family-id rule (else REFUSED `registry_disagrees`) → `spawn_node(env=build_child_env(os.environ, state, permit_ceiling_ns=state.first_boot_permit_expires_at_ns))`.
- **Budget and alerts.** `RELAUNCH_REQUESTS_MAX_PER_DAY = 3`. Every request and every outcome raises INFO through `deliver_with_proof`.
- **Why a request.** Nothing is copied from `/proc/<pid>/environ`, so the caps never leave the supervisor process. The child is the supervisor's own (Popen retained, reaped).

### 3.8 Dead-man, HWM reset, verify

- **`breezy-autonomy-deadman`.** `.timer` `OnCalendar=*:00/30`; `Type=oneshot`, `TimeoutStartSec=60`; own lock `registry/deadman.lock`; `MemoryMax=128M`. It reads the heartbeat (single read) and the chain-head age. It raises CRITICAL `AUTONOMY_ENGINE_HEARTBEAT_STALE` past `ENGINE_HEARTBEAT_STALE_S` and `AUTONOMY_CHAIN_STALE` past H, both through `deliver_with_proof`. Otherwise it logs `deadman ok age_s=<n>`.
- **`breezy-registry-hwm-reset --venue <v>` (M9, ARCH Rev 5 C5 HWM reset, W4).** Preconditions: no node holds the exec flock, and it can take the engine lock. In order:
  1. Verify the restored chain as a prefix of the export with the highest `export_seq`.
  2. Compute `dropped` = rows in that export not in the restored chain. Re-apply, as new rows (`decided_by=operator_cli`, `mode=OPERATOR_CLI`), the restrictive effect of every dropped DEMOTE, HALT, SWAP_CANCEL and RETIRE, plus `demoted_for_cause`, `terminal_frozen` and the INTEGRITY freeze. DEMOTE (RECOVERABLE_INFRA) any family that would otherwise fold less restrictive than in the export, for example a superseded champion revived by a dropped PROMOTE.
  3. **Refuse** unless, per family and lineage, the post-reset fold is at least as restrictive as the export's (order RETIRED > HALTED > CHALLENGER/SHADOW > CHAMPION; flag and freeze sets ⊇).
  4. Append `HWM_RESET` carrying `carried_counters`: every per-lineage and venue counter of the export with its charge time. The fold applies them as floors, so **no budget is refunded**.
  5. Write a new export (restored prefix + re-applied rows + reset row, next `export_seq`).
  6. Set the node HWM to the new head under the exec flock.
  7. Journal `evidence/registry/hwm_reset_<ts>.json` citing the replaced export's sha and the dropped `transition_id`s, then send CRITICAL `REGISTRY_HWM_RESET` through `deliver_with_proof`.
  - **Tests.** `test_hwm_reset_cli_journals_alerts_and_chains`, `test_hwm_reset_cannot_unhalt`, `test_hwm_reset_never_refunds_counters`, `test_resolver_resolves_after_hwm_reset`, `test_hwm_reset_refuses_with_live_node`, `test_hwm_reset_refuses_non_prefix_chain`.
- **`breezy-registry-verify --venue <v> [--registry-root <p>] [--at <iso>] [--rows]`.** Read-only. It prints `chain_ok`, `head`, `venue_seq`, `export_seq`, `export_prefix_ok`, `replay_ok`, `champion`, `state`, `pending`. It is the scorer's tool.

### 3.9 Policy ruling (WP3): DRAFT, values proposed here and settled by peer review

**File.** `docs/evidence/RULING_autonomy_promotion_policy_v1_<filing-date>.md`, with a byte-identical deploy copy at `deploy/families/rulings/` (pattern G4; `test_no_module_under_src_reads_docs_evidence` respected). The filing commit also sets `pins.POLICY_RULING_PIN = ("RULING_autonomy_promotion_policy_v1_<date>", "<sha256>")` (M3). That pin is the engine's only source of policy identity in every stage. WP9's allowlist row must equal it (`test_lineage_allowlist_row_equals_policy_pin`).

**Supersessions.** It supersedes D11 for allowlisted lineages (parent ruling §3). It lifts AUD-10 PROVISIONAL only for the `OFFLINE_CHALLENGER`/`FORWARD_SHADOW` predicates it names. It never touches the caps, master enablement, the permit or NO-SEND.

**Feasibility (ARCH §4.2 Y12, C4 W7; inputs cited).**
- σ_d = 0.132 per station-day (paired traded-rung Brier difference, `RULING_nbp_pmus_leg_infeasible_node4_2026-09-30` A-3, CI [0.127, 0.138]); MDE δ = 0.0152.
- n_min = ((z₁₋α_K + z₀.₈)·σ_d/δ)². At α = 0.025 this reproduces that ruling's 592 (formula check).
- α_total = 0.025, K_max = 2 ⇒ α_K = 0.00625, z = 2.498 ⇒ **n_min = 841 independent station-days**. Sensitivity: K_max 1 → 717; 4 → 1087; δ 0.025 → 311.
- Qualifying rate upper bound **4.55 station-days/day** (5 cities HIGH only; about 9% venue skips; replay-sufficiency can only lower it). AUT-4 replaces it with the measured value.
- **Window capacity (new, W7).** `forward_window_days = 120` (the §4.5 maximum) ⇒ capacity ≤ 120 × 4.55 = 546 < 841. **n_min is unreachable inside one window**, which ARCH C4 requires for promotion.
- **ETA.** From `forward_eval_start_utc` 2026-11-02: 841 / 4.55 = 185 days ⇒ `eta_date` 2027-05-06, after the 2027-01-25 KILL.
- **Consequence.** `promote_enabled = false` on two independent grounds: window capacity, and ETA after the KILL (`test_promote_disabled_when_eta_after_kill`, `test_promote_disabled_when_n_min_exceeds_window_capacity`). PROMOTE (CHALLENGER→CHAMPION) is proven by DRILL_PROMOTE only (ARCH §7). The PROMOTE code path is still tested end to end with an injected policy (M7, `test_promote_executes_when_enabled_and_evidence_met`).

**Inert in v1 (M22).** With `promote_enabled = false`, three keys never bind any transition in v1: `min_days_between_promotes_per_lineage` (M = 30; drill rows never count toward M, ARCH Z3), `forward_shadow.min_calendar_days` (60) and `forward_shadow.n_min_station_days` (841). They are filed so that a later revision changes only `promote_enabled` and the feasibility record. `k_max`, `forward_window_days` and the anchor **are live in v1**, because the store enforces MINT limits on them (§3.2).

**Values and justification.**

| Key | Proposed | Ceiling (pins) | Justification |
|---|---|---|---|
| `alpha_total` | 0.025 | ruling | Same α as PREREG v2 and the node-4 ruling. |
| `k_max` | 2 | ≤ 4 | n_min 1.42× the single-test n; K = 4 costs +29% for no capacity gain. |
| `forward_window_days` | 120 | 28–120 | The longest window gives the largest within-window capacity (still < n_min). A shorter window would spend α faster, for no feasibility gain. |
| `forward_window_anchor_date` | `2026-10-02` | n/a | The first forward day under `RULING_holdout_freeze_and_forward_window_2026-10-03` (holdout frozen [2026-07-01, 2026-10-02)). Windows tumble from it: [10-02, 2027-01-30), … |
| `min_days_between_promotes_per_lineage` (M) | 30 | ≥ 14 | Inert in v1. 30 ≈ 15 LD-OBF looks at about 5 fills/day. |
| `forward_shadow.min_calendar_days` | 60 | n/a | Inert in v1 (stop-gate power note, memory `stop-gate-is-live-small`). |
| `forward_shadow.n_min_station_days` | 841 | n/a | Computed above; inert in v1. |
| `forward_shadow.predicates` | 4 market predicates + `challenger_beats_champion_paired_brier` (M18) | n/a | The paired predicate: per independent station-day, d = Brier(champion) − Brier(challenger) on the traded rung, same Depth10 rows. It is a one-sided test of mean(d) > 0 at the candidate's α_k, with n counted in independent station-days (Y14). A challenger must beat the **champion** as well as the market, so a swap can never trade a better-than-market champion for a worse one. AUT-4 produces it inside the `FORWARD_SHADOW` verdict as metric `paired_brier_diff_ci_lower`. |
| `forward_shadow.accepted_assumptions` | `[]` | n/a | `slippage_champion_proxy` is not accepted ⇒ INCONCLUSIVE. |
| `live.drawdown.*` | §3.11 | n/a | Calibrated in WP3 (M5). |
| `reconciliation_horizon_h` | 8 | ≤ `ATTEST_VERDICT_VALIDITY_H` | RESUME only (§3.3.7, M2). |
| `attest.ATTEST_PERIOD_H` / `ATTEST_VERDICT_VALIDITY_H` / `ATTEST_MARGIN_H` / `INTRADAY_ATTEST_VERDICT_PERIOD_MIN` | 6 / 8 / 0.5 / 60 | ≤ 6 / ≤ 8 / ≥ 0.5 / ≤ 60 | At the ceilings. The invariant 7.54 ≤ 8 holds (§3.3.6). |
| `attest_required_verdict_kinds` | `["HEALTH","RECONCILIATION"]` | n/a | ARCH Z5/W1. |
| `post_stop.POST_STOP_RECONCILE_RUNTIME_S` | 120 | ≤ 120 | Ends by 16:43Z. |
| damping keys | as r1 (`RESUME_COOLDOWN_H` 24; `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` 2; `MAX_INFRA_RESUMES_PER_VENUE_7D` 3; `MAX_ROLLBACKS_PER_VENUE_30D` 2; `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` 1; `MAX_MINTS_PER_LINEAGE_PER_DAY` 1; `DRILL_BUDGET_PER_VENUE_30D` 1) | ARCH §4.5 | At or stricter than the ceilings. |
| staleness keys | `DEADMAN_HORIZON_H` 30; `MAX_VERDICT_VALIDITY_H` 26; `ENGINE_HEARTBEAT_STALE_S` 1800; `WATCH_TICK_STALE_S` 180; `ALERT_CANARY_MAX_AGE_H` 26; `DEMAND_FILE_MAX_BYTES` 4096; `DEMAND_FILES_MAX` 16 | ARCH §4.5 | `ENGINE_HEARTBEAT_STALE_S` 1800 cannot trip on a phase-scoped daily pass (every phase hold ≤ 60 s; intraday heartbeats continue). |
| `alerting.*` (AUT-6 consumes) | `ALERT_DELIVERY_TIMEOUT_S` 10; `ALERT_OUTBOX_MAX` 256; `CANARY_RETRY_PERIOD_MIN` 60; `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` 3 | ≤ 10 / ≤ 256 / ≤ 60 / ≤ 3 | At the ceilings. Filed here because ARCH §8 places §4.5 values in this ruling. |

**Detector → action map and cause classes.** NODE_LOCAL vetoes stay `ENTRY_VETO` in code. The VERDICT ids are below. Changes from r1: `live.drawdown` producer is **AUT-5** (M6); `drill.inject` cause class is **DRILL** (W2); `reconciliation.post_stop` added (W8). Every row with action DEMOTE/HALT is also in `pins.FALLBACK_RESTRICTIVE_MAP` (M10).

| Detector id | Producer | Kind | Action | Cause class | Horizon |
|---|---|---|---|---|---|
| `freshness.persist` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_INFRA | `feed_stale`/`recorder_stale` ≥ 6 h |
| `liveness.permit_process` | AUT-6 | HEALTH | DEMOTE | RECOVERABLE_INFRA | `permit_lapsed` ≥ 2 h or liveness FAIL; hourly PASS cited by ATTEST |
| `health.capture_join` | AUT-1 | HEALTH | DEMOTE | RECOVERABLE_INFRA | `capture_gap` ≥ 1 h or join < 100% |
| `health.alert_canary` | AUT-6 | HEALTH | DEMOTE | RECOVERABLE_INFRA | canary FAIL |
| `health.label_lag` | AUT-2 | HEALTH | ALERT | RECOVERABLE_INFRA | label > 24 h after settlement |
| `health.unit` | AUT-6 | HEALTH | ALERT | RECOVERABLE_INFRA | failed autonomy or study unit |
| `health.reproducibility` | AUT-3 | HEALTH | ALERT | RECOVERABLE_MODEL | C3 rerun sha mismatch |
| `reconciliation.net_position` | AUT-2 | RECONCILIATION | DEMOTE | RECOVERABLE_INFRA | intraday (≤ hourly); PASS cited by ATTEST and RESUME |
| `reconciliation.post_stop` | AUT-2 | RECONCILIATION | DEMOTE | RECOVERABLE_INFRA | 16:41Z with node down; PASS required for ACTIVATE |
| `drift.forecast_input` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `drift.calibration_live` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `drift.fill_rate_slippage` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `parity.train_serve` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `drift.venue_shape` | AUT-6 | DRIFT | ALERT | RECOVERABLE_INFRA | the node refuses per order already |
| `drift.fee_schedule` | exec-store mirror | (mirror) | HALT | TERMINAL | immediate |
| `live.sequential` | AUT-4 | LIVE_SEQUENTIAL | HALT | TERMINAL | LD-OBF boundary crossed |
| `live.kill_clock` | AUT-4 (`evaluate_c_kill`) | LIVE_SEQUENTIAL | HALT | TERMINAL | `structural_dead` or 2027-01-25 |
| `live.drawdown` | **AUT-5 (WP11)** | LIVE_SEQUENTIAL | HALT | TERMINAL | §3.11 |
| `drill.inject` | AUT-6 (pinned marker detector) | DRIFT | DEMOTE | **DRILL** | only while `drill_clause` is active; else ERROR |

**Drill clause (M15).** The r1 window (filing + 7 d to filing + 28 d, about 10-24 to 11-14) **did not cover the 2026-11-19 planning date**. Widened:

```json
{"drill_child_id": "pm_us_crh_fq_v1_r0001", "root_family_id": "pm_us_crh_fq_v1",
 "active_from_utc": "<filing date + 7 d>", "active_until_utc": "2027-01-11",
 "max_episodes": 1, "start_rule": "first_daily_pass_in_window_with_widening_enabled_and_preconditions_met",
 "inject_at": "daily_pass_on_first_effective_day_plus_1", "resume_after_h": 24,
 "marker_registry_root": "registry"}
```

- The window runs from about 10-24 to 2027-01-11. That covers the planning date plus more than 7 weeks of slack, and ends 2 weeks before the KILL.
- `max_episodes = 1` and the drill budget of 1 per 30 days bound exposure, so the long window adds no extra drills.
- A missed window needs a ruling revision. **Re-pin cost, stated:** a new ruling sha means a peer review round, a new `POLICY_RULING_PIN` commit and a new `_LINEAGE_POLICY_ALLOWLIST` row (still one row: replaced, not added). That is about 2 working days, with the full gate after each merge.
- `drill_clause_sha256` = sha256(canonical_json(clause)), stored in the block and on every drill row.

**Machine-readable block (DRAFT filed verbatim; `<…>` only in this DRAFT, refused by `test_policy_block_exact_set_keys`).**

```autonomy-policy/v1
{
  "schema": "autonomy-policy/v1",
  "policy_ruling_id": "RULING_autonomy_promotion_policy_v1_<filing-date>",
  "venues": ["polymarket_us"],
  "lineage_roots": ["pm_us_crh_fq_v1"],
  "promote_enabled": false,
  "feasibility": {"n_min_unit": "independent_station_days", "n_min": 841, "sigma_d": 0.132,
    "mde_brier": 0.0152, "alpha_k": 0.00625, "power": 0.80,
    "qualifying_station_days_per_day": 4.55, "qualifying_rate_source": "upper_bound_pending_AUT-4",
    "window_capacity_station_days": 546, "n_min_reachable_in_window": false,
    "earliest_forward_eval_start_utc": "2026-11-02", "eta_date": "2027-05-06", "kill_date": "2027-01-25"},
  "alpha_total": 0.025, "alpha_spending": "halving_per_candidate", "k_max": 2,
  "forward_window_days": 120, "forward_window_anchor_date": "2026-10-02",
  "min_days_between_promotes_per_lineage": 30,
  "offline_challenger": {"holdout_opens_max_per_lineage": 1, "rolling_forward_holdout": true},
  "forward_shadow": {"min_calendar_days": 60, "n_min_station_days": 841,
    "predicates": ["traded_rung_brier_beats_market_baseline", "ev_net_fee_slippage_ci_lower_gt_0",
                   "traded_rung_calibration_leg_pass", "n_ge_n_min",
                   "challenger_beats_champion_paired_brier"],
    "accepted_assumptions": []},
  "live": {"drawdown": {"statistic": "peak_to_trough_cum_realized_pnl_over_cum_cost",
                        "scope": "lineage_real_money_fills", "limit": "<calibrated>",
                        "min_settled_real_money_fills": "<calibrated, >= 10>",
                        "h0_trip_prob_max": 0.05, "h0_horizon_end_utc": "2027-01-25",
                        "h0_seed": 20260904}},
  "reconciliation_horizon_h": 8,
  "attest": {"ATTEST_PERIOD_H": 6, "ATTEST_VERDICT_VALIDITY_H": 8, "ATTEST_MARGIN_H": 0.5,
             "INTRADAY_ATTEST_VERDICT_PERIOD_MIN": 60},
  "attest_required_verdict_kinds": ["HEALTH", "RECONCILIATION"],
  "attest_cited_detectors": {"HEALTH": "liveness.permit_process", "RECONCILIATION": "reconciliation.net_position"},
  "post_stop": {"POST_STOP_RECONCILE_RUNTIME_S": 120},
  "detector_map": {
    "freshness.persist": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 6},
    "liveness.permit_process": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 2},
    "health.capture_join": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 1},
    "health.alert_canary": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "health.label_lag": {"action_class": "ALERT", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 24},
    "health.unit": {"action_class": "ALERT", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "health.reproducibility": {"action_class": "ALERT", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "reconciliation.net_position": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "reconciliation.post_stop": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "drift.forecast_input": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "drift.calibration_live": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "drift.fill_rate_slippage": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "parity.train_serve": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "drift.venue_shape": {"action_class": "ALERT", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "drift.fee_schedule": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "live.sequential": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "live.kill_clock": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "live.drawdown": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "drill.inject": {"action_class": "DEMOTE", "cause_class": "DRILL", "horizon_h": 0}},
  "damping": {"RESUME_COOLDOWN_H": 24, "MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D": 2,
    "MAX_INFRA_RESUMES_PER_VENUE_7D": 3, "MAX_ROLLBACKS_PER_VENUE_30D": 2,
    "MAX_SENDER_CHANGES_PER_VENUE_PER_DAY": 1, "MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE": 30,
    "MAX_CANDIDATES_PER_LINEAGE_PER_FORWARD_WINDOW": 2, "MAX_MINTS_PER_LINEAGE_PER_DAY": 1,
    "DRILL_BUDGET_PER_VENUE_30D": 1},
  "staleness": {"DEADMAN_HORIZON_H": 30, "MAX_VERDICT_VALIDITY_H": 26, "ENGINE_HEARTBEAT_STALE_S": 1800,
    "WATCH_TICK_STALE_S": 180, "ALERT_CANARY_MAX_AGE_H": 26, "DEMAND_FILE_MAX_BYTES": 4096,
    "DEMAND_FILES_MAX": 16},
  "alerting": {"ALERT_DELIVERY_TIMEOUT_S": 10, "ALERT_OUTBOX_MAX": 256, "CANARY_RETRY_PERIOD_MIN": 60,
    "SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY": 3},
  "drill_clause": {"drill_child_id": "pm_us_crh_fq_v1_r0001", "root_family_id": "pm_us_crh_fq_v1",
    "active_from_utc": "<filing+7d>", "active_until_utc": "2027-01-11", "max_episodes": 1,
    "start_rule": "first_daily_pass_in_window_with_widening_enabled_and_preconditions_met",
    "inject_at": "daily_pass_on_first_effective_day_plus_1", "resume_after_h": 24,
    "marker_registry_root": "registry"},
  "drill_clause_sha256": "<sha256 of canonical drill_clause, computed at filing>"
}
```

`MAX_CANDIDATES_PER_LINEAGE_PER_FORWARD_WINDOW` must equal `k_max` (`test_policy_block_exact_set_keys` asserts it).

### 3.10 Drill timeline (steps are AUT-7b's; mechanics are AUT-5's)

| Day | Engine action (15:30Z daily unless stated) | Registry rows |
|---|---|---|
| D−1 | MINT `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage; not counted toward K_max); DRILL_ADMIT; DRILL_PROMOTE pair pending for D (the incumbent folds CHAMPION and is not `demoted_for_cause`, W2). 16:41Z post-STOP PASS → 16:45Z ACTIVATE. | MINT, DRILL_ADMIT, DRILL_PROMOTE + SUPERSEDE(fq_v1, `rollback_eligible=true`, W3), ACTIVATE |
| D | 16:50Z LAUNCH resolves r0001; the drill episode starts (C1 `drill=true`). | (fold) |
| D+1 | 15:30Z: write `<registry_root>/drill/marker.json` with `{schema:"drill_marker/v1", registry_root:"registry", venue, drill_clause_sha256, ts_ns}`. AUT-6 producer (`*:00/5`) → `drill.inject` FAIL. Intraday pass ≤ 5 min later → DEMOTE (cause class DRILL, charging `drill_resumes` only on the later RESUME). Watch actor vetoes `registry_halted` on its next tick (SLO ≤ 15 min). The intraday pass removes the marker after commit; the next producer run emits PASS. | DEMOTE (drill) |
| D+2 | 15:30Z: RESUME **refused**: the cooldown runs until the DEMOTE ts + 24 h (about 15:40Z D+2), later than the 15:30Z pass. 16:50Z LAUNCH: r0001 boots HALTED, entries vetoed, exits live (Z7). | none |
| D+3 | 15:30Z: RESUME (cooldown met, cause PASS, no pending pair, §4.4 RESUME horizon; charges the drill budget only, W2). Then, in a later phase of the same pass, the ROLLBACK to fq_v1 is proposed pending for D+4. 16:41Z post-STOP PASS → 16:45Z ACTIVATE. | RESUME, ROLLBACK + SUPERSEDE(r0001), ACTIVATE |
| D+4 | 16:50Z LAUNCH restores fq_v1 at a byte-identical sha; the episode closes. | (fold) |

- **Marker root-keying (M20).** The engine writes the marker under the registry root it runs against. AUT-6's detector unit reads the marker only under its own configured root. The detector refuses a marker whose `registry_root` field differs from its root, or whose `drill_clause_sha256` is not the active clause. So a shadow detector never trips on the production marker, and the reverse also holds (`test_shadow_detector_ignores_production_marker`, `test_production_detector_ignores_shadow_marker`).
- **Cooldown timing (M23).** `test_drill_resume_refused_d2_admitted_d3` runs the fake-clock timeline above. It asserts that RESUME is refused at D+2 15:30Z with reason `cooldown` and admitted at D+3 15:30Z, and that RESUME precedes the ROLLBACK proposal in the same pass.
- **Clock.** 6 trading days from MINT to restoration, which satisfies ARCH's "at least 4" (X8).

### 3.11 Drawdown producer (WP11; M5, M6)

- **Ownership (M6).** AUT-5 owns `live.drawdown`. Producer `breezy-autonomy-producer-drawdown` (`analysis/autonomy_producers/drawdown.py`), its own oneshot unit `deploy/systemd/breezy-autonomy-producer-drawdown.{service,timer}`: `OnCalendar=*-*-* 14:50:00` (after AUT-4's 14:45 live sequential, before the 15:30 daily pass), `TimeoutStartSec=300`, `MemoryMax=512M`, own lock `derived/verdicts/.drawdown.lock`, not the studies flock (a HALT producer must not wait on a study). It is pinned in `PRODUCER_SOURCE_SHA256["live.drawdown"]` and listed in `closure_manifest`.
- **Scope and statistic (M5).** Subject = the venue's current CHAMPION. The statistic runs over **every real-money fill of the subject's lineage** since the lineage's BOOTSTRAP row, so a drill child or a voided pair cannot escape it.
  - **Included C2 rows:** `admissible = true`, plus `excluded_reason ∈ {drill, voided_pair, slippage_defect, q≠1, fee_unreconciled}` (real money, W12).
  - **Excluded C2 rows:** `canary` (not money), `duplicate_fill` (the same money twice) and `window_incomplete` (unsettled).
  - **`unattributed`:** attributed to the family the fold names sender at the fill's `ts_event` (fail-closed: charged to the sender).
  - **Formula:** `peak_to_trough_cum_realized_pnl_over_cum_cost` = max over t of (peak cumulative realised P&L up to t − cumulative realised P&L at t) ÷ cumulative cost at t, using reconciled fees (the labelled `realized_pnl`).
  - **Failures:** an unknown `excluded_reason` (exact-set) or a missing `realized_pnl` on an included row gives `outcome=INCONCLUSIVE`, a WARNING `AUTONOMY_DRAWDOWN_INCONCLUSIVE`, and `health.label_lag` covers persistence.
  - **Outcome:** FAIL when the statistic exceeds `limit` with at least `min_settled_real_money_fills` included settled fills; PASS otherwise. It never reads either operator cap.
- **Handshake with AUT-2 (M6).** `tests/unit/test_drawdown_producer.py::test_drawdown_reads_label_v1_handshake` builds its fixture parquet **through AUT-2's real label writer** and its pinned pyarrow schema (L-42), and asserts column-for-column agreement with the producer's reader. Until AUT-2's writer merges it is a strict-xfail owned by AUT-2 and listed in the placeholder ledger (§4, M19).
- **H0 calibration (M5)** in `scripts/analysis/autonomy_drawdown_h0.py`. It uses a deterministic seed (20260904), runs under `MemoryMax=2G` via `systemd-run --user --scope`, never inside 01:00–04:30Z, and is run by the coordinator, never `uv`.
  - **Null model.** It reproduces the registered null exactly (L-41): zero edge (each fill wins with probability equal to its ask), asks drawn from the champion's empirical ask distribution on the durable-fill store, mutually exclusive rungs (L-40), and the venue fee θ = 0.0695.
  - **Horizon.** From stage-L1 start to 2027-01-25 at 5 fills/day.
  - **Search.** For each `min_settled_real_money_fills ∈ {10, 15, 20, 30, 50}`, the smallest `limit ∈ (0, 1.0]` on a 0.01 grid with P(trip by 2027-01-25 | H0) ≤ 0.05. The filed pair is the smallest m that has a feasible limit, together with that limit. If no m in the set has a limit ≤ 1.0, `min_settled_real_money_fills` is raised further. **The limit is never made vacuous** (limit > 1.0 or m > the horizon's expected fill count is refused).
  - **Tests.** `tests/unit/test_autonomy_drawdown_h0.py::test_h0_reproduces_registered_null` (positive control), `::test_h0_calibration_has_feasible_limit` (some m ≤ expected fills has a limit ≤ 1.0), `::test_filed_drawdown_limit_meets_h0_bound` (re-simulates the filed pair: trip probability ≤ 0.05 within MC error at 20 000 paths), `::test_drawdown_limit_has_power_under_negative_edge` (EV −0.05 per $ cost ⇒ trip probability ≥ 0.5, so the limit is not vacuous).
- **Fallback after a false-positive TERMINAL (M5).** A TERMINAL drawdown HALT retires the champion and sets `terminal_frozen` on the lineage (ARCH Y10). The venue then has **no sender**; capture, labels, refits and evaluation continue. There is no autonomous path back, by design (ARCH Z20). Recovery is build-side and never an operator decision, mirroring W15:
  1. An incident report under `docs/incident-reports/` shows the trip was a false positive (or not).
  2. It is peer-reviewed.
  3. A reviewed change adds a new lineage root: a committed manifest, its `_LIVE_ORDERS_ALLOWLIST` row under a new ruling, a revision of this policy naming the new root in `lineage_roots`, and the `_LINEAGE_POLICY_ALLOWLIST` row replaced. Each allowlist changes by one reviewed row.
  4. A fresh BOOTSTRAP is impossible on a non-empty chain, so the new root enters as `∅ → SHADOW` and is promoted only by the policy path. With `promote_enabled = false`, that means **no sender until a ruling revision**.
  - This cost (about 2 working days, possibly longer) is accepted, and the H0 bound caps its probability at ≤ 0.05 over the horizon. If it fires before the drill completes, AUT-5 reports "blocked: lineage frozen" and re-runs the drill on the new root; the proof is never fudged.

### 3.12 Budget across namespaces (M8)

- **What persists.** The daily-budget state that survives a process is the **venue-scoped exec store** `~/.local/share/breezy/state/exec_polymarket_us.sqlite`. It holds the durable fill records (`fill/<venue_order_id>`, `fill_index/<instrument_id>`, `fill_by_day/<UTC day>`; `exec/client.py:408-447`) and the venue-scoped exhaustion key `exec/polymarket_us/budget_exhausted/<day>` (`:399`, G21). None of these keys contains a family id.
- **What does not persist.** `DailySpendLedger` is process-local and in memory (`operator_controls.py:264-276`: "a restart forgets the day's spending").
- **Inheritance.** At every node boot, `_seed_spend_from_durable_fills` (`exec/client.py:2216-2243`) sums today's `cumulative_cost` over the provider's instruments **and today's day index** (`:2213`, `candidate_ids.extend(day_indexed)`), de-duplicated per venue order. It books the sum once (`seed_spent`, `operator_controls.py:307-334`, never lowering a higher total).
  - A sender change at LAUNCH, a post-launch SWAP_CANCEL relaunch, a midday relaunch and a `breezy-trade-relaunch` are all new node processes against the same venue store. Each re-seeds with every fill of the UTC day, whichever family or instrument set produced it, and sees the same exhaustion key.
  - Drill fills are ordinary durable fills, so they spend the same budget (Z18).
  - Autonomy code never reads, passes or computes a cap value; `build_child_env` forwards the supervisor's environment, where the caps already are, unchanged.
- **Residual, stated.** The day index is the cross-family link. A fill recorded without its day-index entry would be counted only if its instrument is loaded by the successor. The test therefore drives fills through the real `record_fill` path (L-42), which writes both.
- **Tests (WP5).**
  - `test_swap_cannot_exceed_daily_budget_across_namespaces`: family A records fills through the real exec-client path. A client for family B, with a disjoint instrument set, then boots against the same store. It asserts that B's `spent_today_usd` equals A's spend and that B's order beyond the remaining test-fixture budget is refused. The cap is a test-fixture value, as in `tests/unit/test_edge2_ac6b_cross_process_fill_budget.py`, never a production assignment.
  - `test_drill_fills_spend_venue_budget`.
  - `test_relaunch_and_swap_cancel_inherit_spend`.

## 4. Work packages

**Gate commands for every WP, after every merge (L-43).** Exact interpreter, never `uv` (L-51). In a worktree, set `PYTHONPATH=<worktree>/src` (memory `worktree-needs-pythonpath`).
- Focused: `scripts/ci/run_tests_no_egress.sh <test paths>`.
- Full: `scripts/ci/run_tests_no_egress.sh` (includes `tests/unit/test_mypy_ratchet.py`).
- Imports: `cd <tree root> && .venv/bin/lint-imports`, which must print "N kept, 0 broken".
- Read the exit code explicitly (memory `pytest-q-doubles-into-qq`).

**Owner-RED placeholder ledger (M19).** Envelope tests whose GREEN belongs to another area are created as `pytest.mark.xfail(strict=True, reason="owner AUT-n WPk")`.
- **Ledger.** `tests/unit/autonomy_owner_placeholders.py` holds `OWNER_PLACEHOLDERS: Final[frozenset[tuple[str, str]]]` (node id, owner).
- **Gate test 1.** `tests/unit/test_autonomy_owner_placeholders.py::test_owner_placeholder_ledger_matches_markers` (AST scan of `tests/`): the set of strict-xfail markers whose reason starts with `owner AUT-` equals the ledger. A marker can be neither added nor removed silently, and an owner removing one deletes its ledger row in the same commit.
- **Gate test 2.** `::test_l2_widening_requires_empty_placeholder_ledger`: if `pins.ENABLED_WIDENING_KINDS` contains any kind beyond `{RESUME}`, the ledger must be empty. The L2 stage flip in WP9 therefore cannot merge while any placeholder remains; the gate itself tracks this.
- **Initial ledger.**

| Placeholder | Owner |
|---|---|
| `tests/unit/test_autonomy_cross_area.py::test_deliver_with_proof_reports_non_2xx_through_tee` | AUT-6 |
| `::test_critical_alerts_use_delivery_proof` | AUT-6 |
| `::test_self_heal_unit_allowlist_is_literal_and_excludes_trade` | AUT-6 |
| `::test_drill_inject_passes_when_marker_absent` | AUT-6 |
| `::test_shadow_detector_ignores_production_marker` / `::test_production_detector_ignores_shadow_marker` | AUT-6 |
| `::test_drill_fills_excluded_from_n_and_kill_clock` | AUT-2 + AUT-4 |
| `::test_voided_pair_fills_excluded_from_all_n` | AUT-2 |
| `::test_reconciliation_and_entry_guard_never_read_canary_store[reconciliation]` | AUT-2 |
| `::test_post_stop_producer_inconclusive_without_stop_signal` | AUT-2 |
| `::test_rollback_restores_byte_identical_artefact` / `::test_drill_rollback_to_superseded_incumbent_admitted` | AUT-7 |
| `tests/unit/test_drawdown_producer.py::test_drawdown_reads_label_v1_handshake` | AUT-2 |
| `tests/unit/test_registry_watch_actor.py::test_alerts_undeliverable_veto` (journal through AUT-6's writer) | AUT-6 |

### AUT-5.WP1: Foundation (ARCH Wave 0)

- **Scope.** §3.1 modules `canonical`, `single_read`, `schemas`, `transitions` (incl. `KIND_MASK`, `WIDENING_KINDS`), `registry_store` (mask, stage flag, K_max window, `export_seq`), `fold` (incl. `carried_counters` floors, DRILL class), `replay`, `pins` (incl. empty `POLICY_RULING_PIN = ()`, `ENABLED_WIDENING_KINDS = frozenset()`, `FALLBACK_RESTRICTIVE_MAP`), `closure_manifest`, `closure`, `policy` (parser), `plugin`, `entry_guard` (Protocol only), node and offline plug-in registries; the envelope scans; the placeholder ledger; `scripts/ci/regen_closure_manifest.py`.
- **Files.** New: the modules above. Tests: `tests/unit/test_registry_store.py`, `test_registry_fold.py`, `test_registry_replay.py`, `test_autonomy_pins.py`, `test_autonomy_envelope.py`, `test_autonomy_plugins.py`, `test_autonomy_owner_placeholders.py`, `test_autonomy_closure.py`. Modified: `pyproject.toml` (forbidden contract `breezy.persistence.autonomy ↛ breezy.adapters, breezy.runtime, breezy.strategy, nautilus_trader`).
- **RED first.**
  - Envelope: `tests/unit/test_autonomy_envelope.py::test_autonomy_never_reads_or_writes_operator_controls`, `::test_autonomy_never_touches_enablement_permit_or_firewall`, `::test_autonomy_never_imports_order_path`, `::test_autonomy_alert_egress_not_widened`, `::test_autonomy_payload_hygiene_scan`.
  - Store: `tests/unit/test_registry_store.py::test_registry_transition_table_is_exact`, `::test_bootstrap_rows_only_in_genesis_transaction`, `::test_registry_cas_and_idempotent_replay`, `::test_registry_hash_chain_and_triggers`, `::test_repeat_supersede_same_family_is_not_replay`, `::test_registry_readonly_open_engine_stopped`, `::test_family_artefact_binding_immutable`, `::test_store_enforces_kind_mask_per_mode` (M12: e.g. `mode=INTRADAY` with a PROMOTE row raises `KindRefused` even when called directly), `::test_daily_refuses_widening_before_stage_flag` (M11), `::test_mint_refused_past_k_max_in_window` (W7), `::test_mint_refused_second_in_one_day`, `::test_drill_mint_not_counted_toward_k_max`, `::test_export_seq_monotone_and_newest_wins`.
  - Fold: `tests/unit/test_registry_fold.py::test_terminal_halt_freezes_lineage`, `::test_demote_during_pending_swap_incoming`, `::test_demote_during_pending_swap_outgoing`, `::test_resume_refused_while_swap_pending`, `::test_unactivated_pair_lapses_at_launch`, `::test_drill_promote_refuses_non_champion_sha`, `::test_drill_refused_over_halted_incumbent` (W2), `::test_drill_budget_separate`, `::test_drill_admit_charges_only_drill_budget`, `::test_drill_resume_never_charges_model_budget` (W2), `::test_drill_flag_spans_promote_to_rollback`, `::test_infra_cause_never_retires`, `::test_damping_ceilings`, `::test_lapsed_pair_never_charged`, `::test_carried_counters_are_floors`.
  - Replay: `tests/unit/test_registry_replay.py::test_resolver_replays_validate_over_full_fold`, `::test_forged_promote_without_resolvable_cause_refused`, `::test_artefact_bytes_must_equal_row_sha_at_resolve`.
  - Pins and closure: `tests/unit/test_autonomy_pins.py::test_code_identity_pins_cover_import_closure`, `::test_engine_pin_history_retained`, `::test_closure_manifest_equals_grimp_closure` (M16), `::test_policy_map_not_looser_than_fallback_map` (skips with an explicit reason until the deploy copy exists; becomes binding in WP3), `tests/unit/test_autonomy_closure.py::test_closure_hash_runtime_under_budget` (M16: `closure_sha256("engine")` in ≤ 5 s wall and ≤ 128 MB peak RSS, measured with `resource.getrusage`, against the 120 s / 512M intraday bound; the function never imports grimp, asserted through `sys.modules`).
  - Plug-ins: `tests/unit/test_autonomy_plugins.py::test_family_plugin_exact_set`.
  - Ledger: `tests/unit/test_autonomy_owner_placeholders.py::test_owner_placeholder_ledger_matches_markers`, `::test_l2_widening_requires_empty_placeholder_ledger`.
  - The strict-xfail placeholders in the ledger.
- **GREEN.** Every AUT-5-owned test passes and every placeholder XFAILs strictly. Mutation evidence (L-33): deleting the UPDATE trigger turns `test_registry_hash_chain_and_triggers` red, and removing the `KIND_MASK` check turns `test_store_enforces_kind_mask_per_mode` red. The RED→GREEN logs are kept.
- **Activation.** None: library only, no runtime caller.

### AUT-5.WP2: Resolver, manifest single-read and containment widening, `entry_guard`, fill-key schema

- **Scope.** `resolver.py` (with `replay_full`); the `parse_family_manifest` split; the four-site L-12 widening; `entry_guard.rung_has_net_position`; `adapters/polymarket_us/exec/fill_key_schema.py`.
- **Files.** `src/breezy/persistence/family_manifest.py`, `src/breezy/runtime/settings.py`, `src/breezy/app/trade.py` (manifest load site only), the new modules. Tests: `tests/unit/test_registry_resolver.py`, `tests/unit/test_entry_guard.py`.
- **RED first.** `tests/unit/test_registry_resolver.py::test_resolver_binds_bytes_to_row`, `::test_registry_paths_refuse_symlinks`, `::test_verify_and_load_share_bytes`, `::test_child_manifest_equals_committed_root_except_allowlist`, `::test_exit_gate_stays_code_only`, `::test_registry_champion_requires_live_orders_gate_for_every_kind`, `::test_resolver_refusals_give_no_champion` (parametrised over every ARCH refusal plus `replay_invalid`, `replay_cause_unresolved`, `replay_artefact_mismatch`), `::test_root_row_accepts_committed_live_orders_triple` (X1); `tests/unit/test_entry_guard.py::test_rung_net_position_veto_crosses_legs_and_families` (fixture via the real exec-client `record_fill`, L-42), `::test_entry_guard_exact_key_reads_only` (a recording connection asserts only `key = ?` / `key IN (…)` statements, never `LIKE`, range or full scan), `::test_entry_guard_unreadable_index_vetoes` (missing record, unreadable index, decode error each veto), `::test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]`, `::test_fill_key_schema_production_default_runs_once` (L-55).
- **GREEN.** All pass. `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_probe_containment` and every `family_manifest` test pass **unmodified**. `lint-imports` shows the new forbidden contract kept.
- **Activation.** Inert until `BREEZY_FAMILY_SOURCE` is set. The single-read manifest path is live at the next 16:50Z LAUNCH, with byte-identical behaviour proven by the unchanged tests.

### AUT-5.WP3: Policy ruling DRAFT → H0 calibration → peer review → filing → `POLICY_RULING_PIN`

- **Scope.** The ruling text on §3.9; drawdown H0 calibration (§3.11) filling `limit` and `min_settled_real_money_fills`; peer review; filing; deploy copy; **the `POLICY_RULING_PIN` commit** (M3).
- **Peer review** (dispatched by the coordinator, never the operator): `prediction-market-reviewer` (α, n_min, window capacity, paired predicate, drawdown H0 against L-40/L-41), `trading-bot-architect` (detector map, DRILL class, drill window, ATTEST cadence), `security-reviewer` (supersession scope, fallback map, no cap or permit language). The lowest score wins. Values move only inside the code ceilings.
- **Files.** New: the evidence and deploy ruling files; `scripts/analysis/autonomy_drawdown_h0.py`; tests `tests/unit/test_autonomy_policy_block.py`, `tests/unit/test_autonomy_drawdown_h0.py`. Modified: `src/breezy/persistence/autonomy/pins.py` (`POLICY_RULING_PIN` only).
- **RED first.** `tests/unit/test_autonomy_policy_block.py::test_policy_block_not_looser_than_code_ceilings`, `::test_promote_disabled_when_eta_after_kill`, `::test_promote_disabled_when_n_min_exceeds_window_capacity`, `::test_policy_block_exact_set_keys`, `::test_policy_ruling_deploy_copy_matches_evidence`, `::test_policy_pin_matches_deploy_copy_sha`, `::test_detector_map_covers_required_classes`, `::test_drill_clause_sha_matches_canonical_clause`, `::test_drill_window_covers_planning_date_and_precedes_kill`, `::test_feasibility_n_min_reproduces_formula`, `::test_attest_constants_meet_cadence_invariant`; `tests/unit/test_autonomy_drawdown_h0.py::test_h0_reproduces_registered_null`, `::test_h0_calibration_has_feasible_limit`, `::test_filed_drawdown_limit_meets_h0_bound`, `::test_drawdown_limit_has_power_under_negative_edge`. `test_policy_map_not_looser_than_fallback_map` (WP1) becomes binding.
- **GREEN.** Tests pass against the filed copy. Review records sit under `reviews/AUT-5-ruling-*.md`, with the final lowest score recorded in the ruling.
- **Activation.** Binding on the engine as soon as the pin commit merges, so stages S and L1 run on the filed block. WP9 reuses the same sha for the node's allowlist row.

### AUT-5.WP4: Engine (phase-scoped lock, restrictive fallback, ATTEST in intraday, prelaunch with post-STOP horizon), demand archive, alert ledger, units

- **Scope.** §3.3, §3.5 (engine side), §3.10 mechanics; `breezy-autonomy-engine@.service` and three timers; the post-STOP reconcile unit pair (wrapper only); the pins update.
- **Files.** New: `src/breezy/analysis/autonomy_engine/*`; `deploy/systemd/breezy-autonomy-engine@.service`, `breezy-autonomy-engine@{daily,intraday,prelaunch}.timer`, `breezy-autonomy-reconcile-poststop.{service,timer}`. Modified: `pyproject.toml` (console script), `deploy/systemd/README.md`, `pins.py` (engine row), `closure_manifest.py`. Contingent move-only: `persistence/autonomy/halt_rows.py`. Tests: `tests/unit/test_autonomy_engine.py`, `tests/unit/test_autonomy_engine_promote_e2e.py`, `tests/unit/test_autonomy_units.py`, `tests/integration/test_engine_lock_slo.py`.
- **RED first.**
  - `tests/unit/test_autonomy_engine.py::test_verdict_acceptance_rules`, `::test_verdict_subject_sha_must_match_row`, `::test_verdict_accepted_after_attest`, `::test_verdict_validity_ceiling`, `::test_halt_reason_class_map_is_exact`, `::test_mirror_read_failure_is_integrity`, `::test_autonomy_exec_keys_disjoint_from_halt_prefixes`, `::test_intraday_engine_is_restrictive_only` (incl. ATTEST allowed, PROMOTE refused by both engine and store), `::test_drill_inject_mapped_only_in_clause`, `::test_candidate_cap_and_mint_rate`, `::test_promotion_requires_reconciled_state`, `::test_demotion_never_requires_policy_and_is_immediate` (M10 semantics, §3.3.2), `::test_fallback_accepts_nothing_when_pin_empty`, `::test_engine_refuses_when_unpinned`, `::test_attest_cites_required_kinds_and_caps_validity`, `::test_attest_cadence_has_no_expiry_gap` (W1), `::test_prelaunch_requires_post_stop_reconciliation` (W8), `::test_activate_refused_on_stale_or_absent_stop_signal`, `::test_demand_file_written_on_first_restrictive_failure`, `::test_retired_demand_file_archived` (W16), `::test_promote_refused_when_promote_enabled_false`, `::test_alert_failure_never_blocks_or_rolls_back_commit` (M21), `::test_autonomy_alert_payload_hygiene` (parametrised per code, M21), `::test_cli_has_no_policy_override_argument`.
  - `tests/unit/test_autonomy_engine_promote_e2e.py::test_promote_executes_when_enabled_and_evidence_met` (M7). It injects a `PolicyBlock` fixture (`promote_enabled=true`, test-only sha, through the `run_daily(policy=…)` library seam that the CLI never exposes) and fixture verdicts written to a temp `derived/verdicts/` with a pinned test producer sha: an accepted `OFFLINE_CHALLENGER` PASS, then `FORWARD_SHADOW` PASS incl. the paired predicate, then post-STOP RECONCILIATION PASS. It drives MINT → SHADOW→CHALLENGER → CHALLENGER→CHAMPION + SUPERSEDE pending → prelaunch ACTIVATE → fold at LAUNCH naming the challenger CHAMPION, and checks that `resolve_sending_family` returns it under the test allowlist. Companion: `::test_promote_e2e_refused_without_paired_predicate`.
  - `tests/integration/test_engine_lock_slo.py::test_restrictive_slo_met_while_daily_holds_lock` (M4: a daily phase holds the lock for `ENGINE_LOCK_MAX_HOLD_S`; an intraday pass with an accepted FAIL commits the DEMOTE after release, or writes a demand on timeout; DetectorEvent → watch veto ≤ 15 min under the fake clock), `::test_daily_lock_hold_never_exceeds_max_hold`, `::test_intraday_lock_timeout_writes_demand`.
  - `tests/unit/test_autonomy_units.py::test_engine_units_carry_no_operator_env_or_venue_env`, `::test_engine_timers_staggered_150s_after_producer`, `::test_intraday_schedule_has_two_runs_in_launch_window`, `::test_engine_runtime_bounds_end_before_launch`, `::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec` (M16: every autonomy unit with `Type=oneshot` has `TimeoutStartSec=` and no `RuntimeMaxSec=`), `::test_poststop_unit_runs_1641_and_ends_by_1643`, `::test_own_lock_autonomy_units_memory_total_le_4g`.
- **GREEN.** All pass. `test_code_identity_pins_cover_import_closure` and `test_closure_manifest_equals_grimp_closure` pass with the engine pin. The engine closure excludes `breezy.app`, `breezy.runtime.trade_supervisor*` and `breezy.adapters.*.exec.client` (asserted).
- **Activation.** Units are installed at WP10 stage S, against the shadow root. Technical reason for not activating on merge: Y7 makes any production-root row binding on the node, so the production root is only bootstrapped at L1.

### AUT-5.WP5: Node (watch actor, required `entry_veto` slot, guard cache, HWM, boot path, Y7, SLO harness, spend inheritance)

- **Scope.** §3.4, §3.12 tests.
- **Files.** New: `src/breezy/strategy/autonomy/registry_watch_actor.py`. Modified: `src/breezy/strategy/forecast_quantile_ladder/strategy.py` (required keyword + one `try_submit` line), `src/breezy/strategy/forecast_quantile_ladder/composition.py` (pass-through), `src/breezy/app/trade.py` (`run`, `_compose_forecast_quantile_ladder`, `FillKeySchema` injection), `src/breezy/runtime/settings.py`. Mechanical keyword addition in the five FQ test files named in §3.4. Tests: `tests/unit/test_registry_watch_actor.py`, `tests/contract/test_watch_actor_thread_contract.py`, `tests/integration/test_demotion_latency_slo.py`, `tests/unit/test_registry_boot.py`.
- **RED first.**
  - `tests/unit/test_registry_watch_actor.py::test_watch_actor_never_reads_projection`, `::test_registry_hwm_refuses_regression`, `::test_registry_unreadable_veto_clears_only_after_verified_read`, `::test_attest_expiry_and_chain_staleness_veto_entries`, `::test_attest_veto_armed_after_first_attest`, `::test_engine_heartbeat_stale_vetoes`, `::test_entry_veto_closed_before_first_tick_and_on_stale_tick`, `::test_bad_demand_file_vetoes_venue`, `::test_restrictive_commit_failure_sets_node_veto` (demand from WP4's writer, L-42), `::test_transient_veto_writes_no_transition`, `::test_resume_clears_registry_halted_without_relaunch` (W5), `::test_entry_guard_cache_invalidated_on_fill` (W6), `::test_watch_actor_busy_timeout_bounded_under_writer_lock` (M17: a writer process holds `BEGIN EXCLUSIVE`; `_tick_once` returns within 400 ms, leaves the state unverified, and after 3 such ticks `entry_veto` returns `registry_unreadable`), `::test_watch_actor_rejects_widening_row_failing_replay`, `::test_watch_actor_applies_restrictive_row_even_if_replay_fails`, `::test_alerts_undeliverable_reads_two_days` (W13), `::test_alerts_undeliverable_veto` (placeholder, AUT-6), `::test_timer_callback_never_raises`.
  - `tests/contract/test_watch_actor_thread_contract.py::test_watch_actor_store_touches_stay_on_loop_thread` (negative control included).
  - `tests/unit/test_registry_boot.py::test_hand_relaunch_without_registry_source_refused`, `::test_node_relaunch_rule_family_id_and_seq_prefix`, `::test_halted_family_boots_entries_vetoed_exits_live`, `::test_registry_unavailable_mints_no_permit`, `::test_registry_veto_leaves_exit_seam_open`, `::test_compose_refuses_without_entry_veto_slot` (W10), `::test_entry_veto_precedes_submit_veto_in_try_submit`, `::test_swap_cannot_exceed_daily_budget_across_namespaces` (M8), `::test_drill_fills_spend_venue_budget`, `::test_relaunch_and_swap_cancel_inherit_spend` (M8).
  - `tests/integration/test_demotion_latency_slo.py::test_demotion_latency_slo` (both paths: node-local ≤ 2 min; DetectorEvent → producer stub → intraday → tick ≤ 15 min; dead engine → heartbeat veto ≤ `ENGINE_HEARTBEAT_STALE_S` + 60 s).
- **GREEN.** All pass. `test_shadow_only_false_is_only_the_gate_output`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`, `test_execution_egress_firewall_guard` pass **unmodified**. The five FQ test files' diffs contain only the added keyword and the shared fixture import (reviewer checks).
- **Activation.** At the next 16:50Z LAUNCH after merge. With the source unset, the actor is composed in a permissive no-registry mode that returns only node-local reasons and `rung_net_position_held`. The registry reasons stay inert until stage S sets `registry_shadow`.

### AUT-5.WP6: Supervisor (resolve at LAUNCH, `build_child_env` at four sites, STOP-completion signal, post-launch SWAP_CANCEL relaunch, §4.4 re-check, unit source)

- **Scope.** §3.6.
- **Files.** `src/breezy/runtime/trade_supervisor.py` (`_do_stop_prior`, `_do_launch`, `_do_relaunch_check`, spawns at `:1631`, `:1982`, `resolve_sending_family_id`, `default_ports`); `src/breezy/runtime/trade_supervisor_core.py`; `deploy/systemd/breezy-trade-supervisor.service` (source line branch-parked). Tests: `tests/unit/test_supervisor_registry_launch.py`, `tests/unit/test_supervisor_stop_signal.py`.
- **RED first.** `tests/unit/test_supervisor_registry_launch.py::test_family_source_fixed_in_unit`, `::test_child_env_built_from_resolved_family_at_every_spawn_site` (AST), `::test_child_env_touches_only_three_keys`, `::test_registry_unavailable_retries_until_window_close_no_fallback`, `::test_post_launch_swap_cancel_restores_incumbent`, `::test_ambiguous_intent_cancels_swap_not_incumbent_launch`, `::test_midday_relaunch_keeps_latched_family`, `::test_self_check_keys_on_resolved_family`, `::test_registry_shadow_logs_agreement_and_spawns_env_family`; `tests/unit/test_supervisor_stop_signal.py::test_stop_completion_signal_written_only_when_lock_free` (M2), `::test_stop_signal_absent_on_refused_or_race`, `::test_stop_signal_write_failure_never_blocks_launch`, `::test_stop_signal_payload_hygiene`, `::test_supervisor_unit_can_write_stop_signal_dir`.
- **GREEN.** All pass. `tests/unit/test_trade_supervisor.py`, `test_ct08_supervisor_contract_surface.py`, `test_trade_supervisor_core_r32.py`, `test_ct13_supervisor_crash_readopt.py` pass unmodified.
- **Activation.** A supervisor restart in 01:00–16:40Z (`KillMode=process` keeps the node; memory `supervisor-changes-need-a-supervisor-restart`). The STOP signal is live from the next 16:40Z STOP. With the source unset, `build_child_env` equals `dict(os.environ)` plus the ceiling (RED test). The source line stays on a branch (symlinked unit, memory `supervisor-unit-is-symlinked-into-the-repo`) until stage S.

### AUT-5.WP7: `breezy-trade-relaunch`

- **Scope.** §3.7.
- **Files.** New `src/breezy/runtime/trade_relaunch_cli.py`. Modified: `trade_supervisor.py` (handler), `trade_supervisor_core.py` (phase, budget, TTL), `pyproject.toml`, `deploy/systemd/README.md` (runbook replacing the hand `systemd-run` recipe). Tests: `tests/unit/test_trade_relaunch_helper.py`.
- **RED first.** `::test_helper_accepts_no_family_or_env_arguments`, `::test_request_refused_inside_launch_window`, `::test_request_refused_when_intent_open`, `::test_request_refused_when_registry_disagrees`, `::test_request_spawns_with_build_child_env_and_permit_ceiling`, `::test_request_budget_three_per_day`, `::test_helper_never_reads_proc_environ` (AST), `::test_request_outcomes_alert_through_delivery_proof`, `::test_stale_request_ignored` (M14), `::test_request_unlinked_before_handling` (M14), `::test_duplicate_request_id_handled_once` (M14), `::test_request_ttl_covers_two_schedule_polls`.
- **GREEN.** All pass; the WP6 suite is still green.
- **Activation.** At the same supervisor restart as WP6.

### AUT-5.WP8: Dead-man, `breezy-registry-hwm-reset` (Rev 5 rule), `breezy-registry-verify`

- **Scope.** §3.8.
- **Files.** New: `src/breezy/runtime/autonomy_deadman.py`, `registry_hwm_reset_cli.py`, `registry_verify_cli.py`; `deploy/systemd/breezy-autonomy-deadman.{service,timer}`. Modified: `pyproject.toml`. Tests: `tests/unit/test_autonomy_deadman.py`, `tests/unit/test_registry_hwm_reset.py`.
- **RED first.** `tests/unit/test_autonomy_deadman.py::test_deadman_critical_past_heartbeat_stale`, `::test_deadman_critical_past_chain_horizon`, `::test_deadman_ok_line_when_fresh`, `::test_deadman_own_lock_not_engine_or_studies`; `tests/unit/test_registry_hwm_reset.py::test_hwm_reset_cli_journals_alerts_and_chains`, `::test_hwm_reset_cannot_unhalt` (M9), `::test_hwm_reset_never_refunds_counters` (M9), `::test_resolver_resolves_after_hwm_reset` (M9), `::test_hwm_reset_refuses_with_live_node`, `::test_hwm_reset_refuses_non_prefix_chain`, `::test_hwm_reset_refuses_less_restrictive_fold`, `::test_hwm_reset_new_export_supersedes`.
- **GREEN.** All pass. Mutation: removing step 3 (the restrictiveness refusal) turns `test_hwm_reset_cannot_unhalt` red.
- **Activation.** The dead-man timer is enabled at stage S against the shadow root.

### AUT-5.WP9: Lineage-policy allowlist widening (one reviewed row) and the L2 stage flag

- **Scope.** `live_orders_gate.py` gains `_LINEAGE_POLICY_ALLOWLIST: Final[frozenset[tuple[str,str,str]]]` with **exactly one row**, `("pm_us_crh_fq_v1", POLICY_RULING_PIN[0], POLICY_RULING_PIN[1])`, written as literals. A child `<root>_r\d{4}` is accepted only when its `live_orders_ruling` equals that ruling id and the root matches (existing re-hash path). Roots keep their `_LIVE_ORDERS_ALLOWLIST` triple (X1). No new `LiveOrdersReason` member. **Separate second commit:** `pins.ENABLED_WIDENING_KINDS = WIDENING_KINDS` (L2).
- **Files.** `src/breezy/persistence/live_orders_gate.py`; `src/breezy/persistence/autonomy/pins.py` (flag commit). Tests: `tests/unit/test_fq_live_orders_gate.py` (additions only), `tests/unit/test_lineage_policy_allowlist.py`.
- **RED first.** `tests/unit/test_lineage_policy_allowlist.py::test_lineage_policy_allowlist_is_literal_only`, `::test_lineage_policy_allowlist_has_exactly_one_row`, `::test_lineage_allowlist_row_equals_policy_pin` (M3), `::test_child_requires_lineage_triple_and_policy_ruling`, `::test_child_with_operator_ruling_refused`, `::test_root_keeps_own_ruling`, `::test_tampered_policy_ruling_refuses_child`.
- **GREEN.** All pass. Every existing test in `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py` and `test_live_orders_ruling_deploy_copy_matches_evidence.py` passes unmodified. The flag commit is green only with an empty placeholder ledger (`test_l2_widening_requires_empty_placeholder_ledger`).
- **Activation.** The allowlist row is merged after L1 exit. Technical reason: no child exists before then, which keeps the widening's blast radius at zero during the restrictive stage. The flag commit is the L2 entry, merged before D−1 15:00Z so it falls outside the drill's no-commit window.

### AUT-5.WP10: Staged activation (shadow → live restrictive → live widening) and live proof

| Stage | Entry condition | Actions (coordinator-run; reversible) | Exit criterion |
|---|---|---|---|
| **S (shadow)** | WP1–WP8 and WP11 merged, full gate green after each; WP3 filed and `POLICY_RULING_PIN` merged | Install the engine, post-STOP wrapper, producer-drawdown and dead-man units with `--registry-root %h/.local/share/breezy/registry-shadow`; run `breezy-autonomy-engine@bootstrap` on the shadow root; supervisor unit `BREEZY_FAMILY_SOURCE=registry_shadow` (branch-parked until the gate passes, then a restart in 01:00–16:40Z). The watch actor logs `entry_veto_shadow reason=…` and never refuses. `ENABLED_WIDENING_KINDS = ∅`. | ≥ 5 trading days, each with all of: ≥ 1 intraday ATTEST per 6 h on the shadow chain, with no expiry gap; heartbeat age ≤ 1800 s at every dead-man run; a `stop_prior_complete` line and a `reconciliation.post_stop` verdict each day; zero `registry_resolve_shadow agree=false`; every `entry_veto_shadow` explained in the stage log; and one shadow DEMOTE through the real producer → intraday → watch path from a shadow-root drill marker. |
| **L1 (live restrictive)** | S exit met; pins commit `ENABLED_WIDENING_KINDS = {RESUME}` | Supervisor restart with `BREEZY_FAMILY_SOURCE=registry`; bootstrap on the **production** root before the next LAUNCH; units repointed to it. `alerts_undeliverable` enabled after AUT-6's first `delivered=true` canary row (Z5). | ≥ 3 trading days with `registry_resolved family=pm_us_crh_fq_v1 seq=<n>` at each LAUNCH, ATTEST every ≤ 6 h, zero unexplained vetoes, `deadman ok` every 30 min. |
| **L2 (live widening)** | L1 exit; WP9 row merged; empty placeholder ledger; WP9 flag commit merged; AUT-7 rollback selector merged; AUT-2 intraday and post-STOP RECONCILIATION live; AUT-6 `drill.inject` live | The drill clause window is active; the engine executes §3.10 with no human step. | The §6 artefacts are present. |

- **Rollback of activation.** Before any production-root row exists: unset the source and restart the supervisor. After L1, Y7 binds, so the reversal is `breezy-registry-hwm-reset` plus a reviewed commit, announced with a one-line heads-up (Pre-Auth floor). Reverting a stage flag is itself a reviewed pins commit, and it can only narrow.
- **Close step.** Update memory `hand-relaunch-mechanics` to point at `breezy-trade-relaunch`; record a lesson if any stage diverged.

### AUT-5.WP11: Drawdown producer (M5, M6)

- **Scope.** §3.11 producer, unit and timer, pin row, manifest entry.
- **Files.** New: `src/breezy/analysis/autonomy_producers/{__init__,drawdown}.py`; `deploy/systemd/breezy-autonomy-producer-drawdown.{service,timer}`. Modified: `pyproject.toml` (console script), `pins.py` (`PRODUCER_SOURCE_SHA256["live.drawdown"]`), `closure_manifest.py`. Tests: `tests/unit/test_drawdown_producer.py`.
- **RED first.** `tests/unit/test_drawdown_producer.py::test_detectors_and_drawdown_include_drill_fills` (W12: identical P&L paths with and without the drill and voided-pair rows give different statistics; canary and duplicate rows never change it), `::test_drawdown_scope_is_lineage_since_bootstrap`, `::test_drawdown_unattributed_charged_to_sender_at_fill_time`, `::test_drawdown_unknown_excluded_reason_is_inconclusive`, `::test_drawdown_fail_requires_min_fills`, `::test_drawdown_never_reads_operator_controls`, `::test_drawdown_verdict_schema_and_pins`, `::test_drawdown_reads_label_v1_handshake` (placeholder, AUT-2), `::test_producer_unit_own_lock_timeout_start_sec`.
- **GREEN.** All AUT-5-owned tests pass. A fixture verdict produced by it is accepted by WP4's acceptance and maps to HALT/TERMINAL.
- **Activation.** The unit is installed at stage S (shadow root). Before AUT-2 labels exist it emits `NO_INPUT` and exits 0 (ARCH C2 rule).

## 5. Association

**Consumed.**

| From | Contract | What AUT-5 needs | Needed by |
|---|---|---|---|
| ARCH | C5 amendments | X1, X2, X7 (carried); X9 (`TimeoutStartSec`), X10 (proposal-time horizon), X3, X5, X6 (drawdown producer = AUT-5) for Rev 6 | before WP1 merge (X2), before WP4 (X9, X10) |
| AUT-2 | C2 `label/v1` incl. `drill`, `voided_pair`, `slippage_defect`, `unattributed`; C4 `reconciliation.net_position` (intraday ≤ hourly) and `reconciliation.post_stop` (console script `breezy-autonomy-reconcile-poststop`, consuming `stop_complete/v1`, INCONCLUSIVE without it); `health.label_lag` | The label writer for the drawdown handshake | S (post-STOP), L1 (intraday recon for ATTEST), L2 |
| AUT-4 | C4 `OFFLINE_CHALLENGER`, `FORWARD_SHADOW` incl. `paired_brier_diff_ci_lower` (M18), `live.sequential`, `live.kill_clock`; feasibility record | The measured qualifying rate (lower keeps `promote_enabled=false`) | L1 (restrictive); never needed for the drill |
| AUT-6 | `deliver_with_proof`, delivery journal (two-day read), canary, intraday producer `*:00/5`, `liveness.permit_process` hourly PASS, `drill.inject` detector reading a root-keyed marker (M20), every DRIFT/HEALTH id in §3.9 | Exact detector ids or a joint DRAFT revision | S (producer, API); L2 (`drill.inject`) |
| AUT-1 | C1 `EntryVeto` writer bound to `on_veto_transition(reason, cleared)`; `health.capture_join` | Callback signature | L1 |
| AUT-3 | C3 candidates; mints limited by the store's K_max-per-window and per-day refusals | `lineage_root_family_id ∈ policy.lineage_roots` | none for the drill |
| AUT-7 | `engine.rollback.propose(fold)` inside the engine closure (pinned); AUT-7b steps | Rollback selection; failed rollback → HALT | L2 |

**Provided.**

| To | Contract | Interface |
|---|---|---|
| all | C5 | `RegistryReader`, `fold`, `replay_full`, `resolve_sending_family`, `breezy-registry-verify` |
| AUT-2 | W8 | `~/.local/share/breezy/state/supervisor/stop_complete_<trading_day>.json` (`stop_complete/v1`), written only with the intent lock verified free; the post-STOP unit pair |
| AUT-1 | C5 → C1 | `fold(...).drill_episode(...)`, `ResolvedFamily.registry_seq` |
| AUT-7 | C5 write API | `RegistryStore.append(..., mode=DAILY)` only through the engine process and lock |
| AUT-6 | veto surface; drill marker | `VetoReason`, `on_veto_transition`, NODE_LOCAL fixed to ENTRY_VETO; marker `drill_marker/v1` with `registry_root` |
| AUT-4 | policy | `PolicyBlock.k_max`, `alpha_total`, `forward_window_days`, `forward_window_anchor_date`, `forward_shadow.*`; `lineage_counters` (read-only) |

**Order and parallelism.**
- Serial: WP1 → WP2 → (WP4 ∥ WP5 ∥ WP6 ∥ WP8 ∥ WP11) → WP7 (after WP6) → S → L1 → WP9 row → WP9 flag → L2.
- WP3 runs in parallel with WP1–WP8 and must have its pin merged before S.
- `app/trade.py`, `settings.py`, `trade_supervisor*.py` belong to AUT-5 alone (ARCH §5.1). WP5 and WP6 touch disjoint files, so they run in separate worktrees, each fast-forwarded first (memory `agent-worktrees-start-stale`).

## 6. Live-proof protocol

- **Artefacts proving score 3.**
  1. `~/.local/share/breezy/evidence/registry/registry_polymarket_us_<D-1..D+4>.jsonl`, together holding MINT, DRILL_ADMIT, DRILL_PROMOTE + SUPERSEDE, ACTIVATE, DEMOTE (cause class DRILL; `cause_verdict_ids` naming a `drill.inject` verdict), RESUME, ROLLBACK + SUPERSEDE, ACTIVATE. Every row has `decided_by="engine"`, a pinned `engine_code_sha`, the pinned policy sha and `drill=true` where it applies.
  2. `breezy-registry-verify --venue polymarket_us` prints `chain_ok=True export_prefix_ok=True replay_ok=True`.
  3. Node logs `~/.local/share/breezy/logs/breezy-trade-<stamp>.log`:
     - D: `registry_resolved family=pm_us_crh_fq_v1_r0001`, `boot_family id=pm_us_crh_fq_v1_r0001`, `fq_live_orders … ruling=RULING_autonomy_promotion_policy_v1_…`.
     - D+1: `entry_veto reason=registry_halted` within ≤ 900 s of the verdict's `produced_at_ns`.
     - D+3: `entry_veto_cleared reason=registry_halted` **without a relaunch** (W5).
     - D+4: `registry_resolved family=pm_us_crh_fq_v1` with the D−1 root artefact sha.
  4. Supervisor log `stop_prior_complete` on D−1 and D+3, and the matching `stop_complete_<day>.json` files.
  5. `~/.local/share/breezy/evidence/alerts/delivery_<date>.jsonl` and `registry/alert_ledger/<date>.jsonl` with `delivered=true` for every `AUTONOMY_TRANSITION`.
  6. `git log --since=<D-1 15:00Z> --until=<D+4 17:10Z> -- deploy/ src/ docs/evidence/` is empty (no human or agent commit in the loop).
- **Where.** `docs/evidence/AUT-5_live_proof_<date>.md` cites paths, lines and shas. It is scored by an independent reviewer, never self-scored.
- **ETA.**
  - Build: WP1 ≈ 7 working days (≈ 2026-10-13); WP2 + WP4–WP8 + WP11 ≈ 9 days in parallel (≈ 10-23); WP3 filing and pin ≈ 10-17.
  - Stages: S 5 trading days (≈ 10-24 to 10-29); L1 3 trading days (≈ 10-30 to 11-03); drill D−1 ≈ 11-04 to D+4 ≈ 11-09.
  - **Earliest live proof 2026-11-09. Planning date 2026-11-19.** The drill window runs to 2027-01-11, covering the planning date plus more than 7 weeks.
  - Hard bound: before the 2027-01-25 KILL.
- **Fills.** The drill needs no fills; about 5 fills/day matters only for AUT-2 and AUT-4 windows. Drill fills carry `drill=true`, spend the venue budget, feed drift and the drawdown, and never count toward any n.
- **Natural events.** A natural restrictive event also counts as DEMOTE evidence; none is required.
- **Evidence class.** **"Machinery proven, edge unproven."** `promote_enabled=false`. PROMOTE is shown live by DRILL_PROMOTE (ARCH §7) and in the gate by `test_promote_executes_when_enabled_and_evidence_met`.

## 7. Score-3 verification checklist

| Criterion | Exact check |
|---|---|
| (a) unattended, no commit in the loop | The §6 item 6 `git log` is empty. `journalctl --user -u 'breezy-autonomy-engine@*' --since <D-1>` shows only timer-started runs. `breezy-registry-verify --venue polymarket_us --rows` shows `decided_by=engine` on every drill row. |
| (b) family-agnostic, cannot send without it | `scripts/ci/run_tests_no_egress.sh tests/unit/test_autonomy_plugins.py::test_family_plugin_exact_set tests/unit/test_registry_resolver.py::test_registry_champion_requires_live_orders_gate_for_every_kind tests/unit/test_registry_boot.py::test_hand_relaunch_without_registry_source_refused tests/unit/test_registry_boot.py::test_compose_refuses_without_entry_veto_slot` passes. `Environment=BREEZY_FAMILY_SOURCE=registry` is in `deploy/systemd/breezy-trade-supervisor.service`. |
| (c) fails closed | `test_registry_unavailable_mints_no_permit`, `test_entry_veto_closed_before_first_tick_and_on_stale_tick`, `test_bad_demand_file_vetoes_venue`, `test_registry_unavailable_retries_until_window_close_no_fallback`, `test_demotion_never_requires_policy_and_is_immediate`, `test_prelaunch_requires_post_stop_reconciliation`, `test_watch_actor_busy_timeout_bounded_under_writer_lock` pass. |
| (d) detected and alerted with delivery proven | Delivery journal rows `delivered=true` for the D+1 CRITICAL `AUTONOMY_TRANSITION kind=DEMOTE`; `test_critical_alerts_use_delivery_proof` passes with no xfail; `deadman ok` every 30 min across the drill; `test_restrictive_slo_met_while_daily_holds_lock` passes. |
| (e) RED→GREEN in the gate | RED→GREEN logs per WP in the PR bodies. `scripts/ci/run_tests_no_egress.sh` exits 0 on the merge commit. `test_owner_placeholder_ledger_matches_markers` passes with an empty `OWNER_PLACEHOLDERS`. `/usr/bin/grep -rn 'reason="owner AUT-' tests/` returns 0 lines. `.venv/bin/lint-imports` prints "0 broken". |
| (f) live proof | The §6 artefacts 1–5 exist. The D+1 node-log veto timestamp minus the verdict `produced_at_ns` is ≤ 900 s. The D+4 resolved artefact sha equals the D−1 root sha. |
| Envelope invariants | `git diff <pre-AUT-5>..HEAD --` on the files of `test_operator_control_assignment_scan`, `test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement` is empty. The diff of `_LIVE_ORDERS_ALLOWLIST` is empty, and `_LINEAGE_POLICY_ALLOWLIST` has one row. |

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Statistical capacity** (≈ 5 fills/day; n_min 841 > window capacity 546 and ETA after the KILL) | `promote_enabled=false` on two computed grounds (§3.9 tests). The PROMOTE path is proven by the e2e test plus DRILL_PROMOTE live. The evidence class is stated. |
| **KILL 2027-01-25 / false-positive TERMINAL** | Drawdown H0 ≤ 0.05 by construction (§3.11). Fallback stated: no sender, build-side new root; "blocked: lineage frozen" is reported, never a fudged proof. Planning date 11-19 leaves about 9 weeks of margin. |
| **Restrictive latency under contention** | Phase-scoped lock (≤ 60 s holds), restrictive phase first, intraday `-w 90`, demand on timeout (§3.3.1); tests. |
| **Policy file broken or missing** | Restrictive fallback with a code map (§3.3.2); ATTEST lapses ⇒ node vetoes within 8 h. |
| **Memory on the 30 GiB host** | `MemoryMax`: engine daily 1G, intraday and prelaunch 512M, poststop 512M, producer-drawdown 512M, dead-man 128M (own-lock total ≤ 4G, tested). H0 calibration ≤ 2G once, outside 01:00–04:30Z. The closure hash needs no grimp at runtime (≤ 128 MB, tested). The watch actor reads only rows above its HWM. |
| **Loop-thread blocking by SQLite** | `busy_timeout` 250 ms, busy tick unverified, stale after 180 s (§3.4). |
| **Shared venv** | Never `uv`/`pip`. Exact interpreter in every brief (L-51). Console scripts are installed only by the coordinator's existing editable-install path, and any reinstall is flagged as a production change. |
| **Concurrent agents** | WP5 and WP6 in separate worktrees; no `git stash` (hook-blocked); per-agent scratchpads; full gate after every merge. |
| **Pin churn** | Narrow engine closure (asserted exclusions); runtime manifest regenerated by script and verified in the gate; append-only pins (Z9). |
| **Supervisor unit symlinked** | Activation lines branch-parked until the gate passes (WP6, WP10). |
| **STOP signal never written** (lock held, refusal) | Fail-closed: post-STOP INCONCLUSIVE ⇒ SWAP_CANCEL; the incumbent launches unchanged (§3.6). |
| **Relaunch request abuse** | 120 s TTL, unlink-before-handle, `request_id` dedupe, ≤ 3/day, outside the launch window, resolved family only. |
| **Detector-id mismatch across blind plans** | Ids are part of the ruling's peer review. Acceptance refuses an unknown id (ERROR, alert). `test_detector_map_covers_required_classes`. |
| **Same-uid tamper** | Stated out of scope for resistance (§3.5); tamper evidence plus selection only among authorised candidates; full replay at resolve. |
| **Drill marker cross-talk (shadow vs production)** | Root-keyed marker plus detector root check (M20). |
| **Stage flag forgotten or flipped early** | The L2 flag cannot merge with a non-empty placeholder ledger. Restrictive kinds are never masked. |

## 9. Binding-constraint compliance

- **Nautilus immutable:** only native extension points (`Actor`, `clock.set_timer`, the `try_submit` guard slot). Nothing is patched.
- **Operator caps:** never read, assigned, derived or bypassed. `test_autonomy_never_reads_or_writes_operator_controls` and the unmodified `test_operator_control_assignment_scan` pin this. The drawdown is cost-normalised from labels and never reads a cap. `build_child_env` touches three non-cap keys. Spend inheritance reuses the existing venue-scoped ledger seed unchanged (§3.12). The relaunch helper copies no environment.
- **`allow_short=False`:** untouched; no autonomy module writes strategy config.
- **NO-SEND:** untouched; `test_execution_egress_firewall_guard` unmodified. Autonomy egress is the `alerts.env` webhook only (`test_autonomy_alert_egress_not_widened`).
- **Master enablement and permit:** untouched (`test_autonomy_never_touches_enablement_permit_or_firewall`). The registry selects only among allowlisted families.
- **PREREG via ruling:** every threshold is in the sha-pinned block. The fallback map is a stricter-only code floor, never a new semantics (`test_policy_map_not_looser_than_fallback_map`).
- **Safety tests never weakened; one reviewed row:** `_LINEAGE_POLICY_ALLOWLIST` gets exactly one row; `_LIVE_ORDERS_ALLOWLIST` and `exit_gate` are unchanged. The five FQ test files gain a keyword argument only, with no assertion removed.

## 10. Self-score

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | Rebased on Rev 5. Every §10 obligation is mapped. Every Rev 5 test is placed in a WP. Six ARCH contradictions are stated, two of them new (X9, X10). |
| Correctness | 20 | 16 | The budget, STOP-site and poll-interval facts are verified at `4b8347a6`. The drawdown limit is still uncalibrated. The phase-scoped lock and the fallback mode are new, unreviewed designs. The 120 s TTL deviates from the review's 60 s, with evidence. |
| Specificity | 15 | 14 | Modules, masks, flags, units (`TimeoutStartSec`), file schemas and the full block are given. |
| Acceptance | 20 | 17 | RED tests are named per WP. The placeholder ledger is gate-tracked. The PROMOTE e2e test exists. Upstream readiness (AUT-2, AUT-6, AUT-7) stays on the critical path. |
| Autonomy-safety | 15 | 12 | Store-side masks, the stage flag, the fallback and full replay are all added. The same-uid residual remains, and a false-positive TERMINAL leaves no sender until a ruling revision. |
| Reuse | 10 | 8 | Predicates, gate, bridge, ro reader, halt readers, supervisor functions and the spend seed are reused. New builds: the store, the request file, the drawdown producer and the closure manifest. |
| **Total** | 100 | **85** | Down from r1's self-score of 90, which the review showed was over-scored (final 70). |

**Contradictions with ARCH Rev 5, for the reviewer (and the Rev 6 author).**
- **X1 (carried).** The resolver refuses "a `live_orders_ruling` that is not the policy ruling", yet the BOOTSTRAP champion and ROLLBACK target `pm_us_crh_fq_v1` names the operator ruling. Fix: the policy ruling applies to `_rNNNN` children only; roots keep their committed triple (the fq_v1 bootstrap exemption, P5-1).
- **X2 (carried).** The C5 table allows only `∅→SHADOW` for BOOTSTRAP; ARCH Bootstrap seeds CHAMPION and RETIRED. Fix: genesis-only `∅→CHAMPION` / `∅→RETIRED` rows from `BOOTSTRAP_SEED` (P5-2).
- **X3 (carried).** G22 says mid-day relaunches reuse the child's env; all four spawn sites forward the supervisor's `os.environ` (`trade_supervisor.py:1289,1379,1631,1982`). C5 Pickup 1 cites `trade_supervisor_core.py:884-895`, which is not the launch site.
- **X5 (carried).** §4.4: "triggers the intraday engine pass" is replaced by the schedule guarantee (two intraday runs in [16:50Z, 17:00Z)); the supervisor makes no `systemctl` call.
- **X6 (updated).** ARCH names no `live.drawdown` producer; AUT-5 owns it (WP11, M6). §5 "AUT-5 Writes" should add C4 `LIVE_SEQUENTIAL` (drawdown only).
- **X7 (carried).** The shadow stage needs `BREEZY_FAMILY_SOURCE=registry_shadow` and a shadow root, because Y7 binds on any production-root row.
- **X9 (new).** §4.4 gives the post-STOP unit `RuntimeMaxSec`, and §5.2 requires `RuntimeMaxSec` on every study. Both are `Type=oneshot`, where `RuntimeMaxSec=` has no effect. The bound must be `TimeoutStartSec=`. G29's grep therefore measures the wrong key.
- **X10 (new).** §4.4 W8 requires a sender-change RECONCILIATION "produced after that day's STOP", but the DRILL_PROMOTE/PROMOTE pair and its partner are written by the 15:30Z daily pass, about 70 min **before** that day's 16:40Z STOP. Fix adopted: proposal rows cite the most recent completed STOP's post-STOP PASS plus a fresh intraday PASS; ACTIVATE and the LAUNCH re-check require today's (§3.3.7).
- X4 and X8 are resolved by Rev 5 (`FillKeySchema`; "at least 4" days).

## §R2 Disposition (review `reviews/AUT-5-r1-merged.md`)

**23 FIXED, 0 REJECTED.**

| M | Disposition | Where fixed / evidence |
|---|---|---|
| M1 | FIXED | Header (Rev 5 sha `5d2b75fa…`). Every listed Rev 5 test placed RED-first: HWM ×3 → WP8; `entry_guard` exact-key and unreadable → WP2, cache → WP5; `compose_refuses…` → WP5; `prelaunch_requires_post_stop…` and `attest_cadence…` → WP4; `resume_clears…` → WP5; `mint_refused_past_k_max…` and `drill_refused_over_halted…` and `drill_resume_never_charges_model_budget` → WP1; `detectors_and_drawdown_include_drill_fills` → WP11. W1 ATTEST in intraday, period 6 h, validity 8 h, `INTRADAY` mask includes ATTEST (§3.2, §3.3.6). W7 window keys and anchor (§3.9), K_max store enforcement (§3.2). W8 → M2. W4 → M9. |
| M2 | FIXED | §3.3.4 (post-STOP unit pair 16:41Z, `TimeoutStartSec=120`, own lock); §3.6 (STOP-completion file written only with the lock verified free, at `_do_stop_prior`, `trade_supervisor.py:1131-1190`); §3.3.7 (ACTIVATE needs a post-STOP PASS after today's signal; `reconciliation_horizon_h=8` is RESUME-only); WP4/WP6 tests; AUT-2 produces the verdict (§5). |
| M3 | FIXED | `pins.POLICY_RULING_PIN` (slot in WP1, value in the WP3 filing commit), engine reads it (§3.3 step 2); WP9 `test_lineage_allowlist_row_equals_policy_pin`. |
| M4 | FIXED | §3.3.1 phase-scoped lock (restrictive phase first, ≤ 60 s holds, intraday `-w 90`, demand on timeout); `tests/integration/test_engine_lock_slo.py::test_restrictive_slo_met_while_daily_holds_lock` (WP4). |
| M5 | FIXED | §3.11: lineage scope incl. drill and voided-pair fills; `test_detectors_and_drawdown_include_drill_fills`; H0 search with `test_h0_calibration_has_feasible_limit`, `test_filed_drawdown_limit_meets_h0_bound`, a power test against vacuity, raising `min_settled_real_money_fills` (renamed from `…_admissible_…`, because the scope is no longer admissible-only); fallback after a false-positive TERMINAL stated. |
| M6 | FIXED | AUT-5 owns `live.drawdown` (WP11, §3.11, detector table); `test_drawdown_reads_label_v1_handshake` through AUT-2's writer; X6 updated. |
| M7 | FIXED | WP4 `test_promote_executes_when_enabled_and_evidence_met` (injected policy, end-to-end fold to resolver) plus a negative companion; the CLI has no override (`test_cli_has_no_policy_override_argument`). |
| M8 | FIXED | §3.12, verified: `DailySpendLedger` in-memory (`operator_controls.py:264-276`); seed `_seed_spend_from_durable_fills` (`exec/client.py:2216`, the review's `:2214` is the preceding line) incl. the day index (`:2213`); venue-scoped exhaustion key (`:399`). Tests in WP5. |
| M9 | FIXED | §3.8 seven-step Rev 5 rule; WP8 `test_hwm_reset_cannot_unhalt`, `…_never_refunds_counters`, `test_resolver_resolves_after_hwm_reset`, plus a mutation. |
| M10 | FIXED | §3.3.2 restrictive fallback with `pins.FALLBACK_RESTRICTIVE_MAP`; `test_demotion_never_requires_policy_and_is_immediate` redefined consistently; `test_policy_map_not_looser_than_fallback_map`; `test_fallback_accepts_nothing_when_pin_empty`. |
| M11 | FIXED | `pins.ENABLED_WIDENING_KINDS` (∅ → {RESUME} at L1 → all at L2), enforced in `RegistryStore.append` (§3.2); `test_daily_refuses_widening_before_stage_flag` (WP1). |
| M12 | FIXED | `append(..., mode=WriterMode)` with literal `KIND_MASK` checked inside the store (§3.2); `test_store_enforces_kind_mask_per_mode` plus a mutation (WP1). |
| M13 | FIXED | §3.5 threat model; `replay_full` in the resolver and incremental replay in the watch actor (cause verdicts resolve by sha, artefact bytes equal the row sha); five tests (WP1/WP2/WP5). |
| M14 | FIXED (value adjusted) | §3.7: unlink before handling, `request_id` dedupe, TTL enforced, `test_stale_request_ignored`. The TTL is **120 s, not 60 s**: the schedule poll is 60 s (`trade_supervisor_core.py:1866`), so a 60 s TTL drops requests written just after a poll. Pinned by `test_request_ttl_covers_two_schedule_polls`. |
| M15 | FIXED | §3.9 drill window `active_until_utc = 2027-01-11` (covers 11-19 plus more than 7 weeks, 2 weeks before the KILL); re-pin cost stated; `test_drill_window_covers_planning_date_and_precedes_kill`. |
| M16 | FIXED | `closure_manifest.py` verified against grimp in the gate (`test_closure_manifest_equals_grimp_closure`); runtime hashes file bytes only; `test_closure_hash_runtime_under_budget` (≤ 5 s, ≤ 128 MB vs 120 s/512M); all oneshots use `TimeoutStartSec` (`test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`); X9. |
| M17 | FIXED | §3.4 `RegistryReader(timeout=0.25)` (the existing ro reader already takes `timeout`, `trial_day_latch.py:354-366`); busy tick unverified; `test_watch_actor_busy_timeout_bounded_under_writer_lock`. |
| M18 | FIXED | §3.9 predicate `challenger_beats_champion_paired_brier` in the block; AUT-4 metric `paired_brier_diff_ci_lower` (§5); used by the M7 e2e test and its negative companion. |
| M19 | FIXED | §4 ledger `OWNER_PLACEHOLDERS` with `test_owner_placeholder_ledger_matches_markers` and `test_l2_widening_requires_empty_placeholder_ledger`; §7 (e). |
| M20 | FIXED | §3.10 marker `<registry_root>/drill/marker.json` carrying `registry_root` and the clause sha; detector root check; two tests (AUT-6 placeholders). |
| M21 | FIXED | §3.3.8 alert after COMMIT, own alert ledger with retry, never blocks or rolls back; `test_alert_failure_never_blocks_or_rolls_back_commit`, `test_autonomy_alert_payload_hygiene[<code>]` over 13 codes. |
| M22 | FIXED | §3.9 "Inert in v1": M = 30, 60-day minimum and 841 bind nothing while `promote_enabled=false`; K_max and the window are live. |
| M23 | FIXED | §3.10 `test_drill_resume_refused_d2_admitted_d3` (fake clock: refused D+2 15:30Z for cooldown, admitted D+3 before the ROLLBACK proposal). |

**Planner-contradiction notes carried (review §Other):** the fq_v1 bootstrap exemption and the `∅→CHAMPION` / `∅→RETIRED` rows are kept (X1, X2; §3.2). The C2 widening (`voided_pair`, `slippage_defect`, `unattributed`) is consumed by the drawdown scope (§3.11). Systemd bounds use `TimeoutStartSec` (§3.3.4, X9).

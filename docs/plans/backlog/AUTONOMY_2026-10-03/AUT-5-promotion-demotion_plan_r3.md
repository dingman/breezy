# AUT-5 — Automated promotion and demotion: registry, policy engine, pre-registered policy ruling (plan r3)

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-5 |
| Title | Automated promotion and demotion (C5 registry, engine, `RegistryWatchActor`, drawdown producer, dead-man, policy ruling) |
| Round | r3 (2026-10-03), the final rebase. r1 and r2 (`AUT-5-promotion-demotion_plan_r1.md`, `…_r2.md`) are kept unchanged. r2 disposed review r1 M1–M23 (its §R2 stands in the r2 file). This round rebases r2 from ARCH Rev 5 onto Rev 9.2; every change is listed in §R3. |
| ARCH consumed | `docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md` **FROZEN Rev 9.2**, frozen copy `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`, **sha256 `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`** (recomputed at writing), plus the binding errata `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md` (E-1 to E-4). Change tags Z1–Z9 from Rev 9.2 are written `R9.2-Z1…Z9` (E-3); earlier Z labels keep their meaning. Code facts were checked at repo `4b8347a6` through codegraph. |
| Coordinator decisions | `reviews/ALPHA-decision.md` (as amended: α per nomination, K_LIFETIME, 1 nomination per window, 1 mint per lineage per day), `reviews/HOLDOUT-decision.md` (consumed through C4.1), `reviews/ROLLBACK-FAILURE-decision.md` (`ROLLBACK_FAILED`, target ineligibility). All binding. |
| Current score | 1 (README "Current scores") |
| Target | 3 |
| Upstream | AUT-2 (C2 labels incl. `drill`/`voided_pair`/`slippage_defect`/`unattributed`; C4 intraday RECONCILIATION at :05/:35 and the post-STOP producer and its unit; `health.label_lag`), AUT-4 (C4 `OFFLINE_CHALLENGER`, `FORWARD_SHADOW` incl. nomination fields, `LIVE_SEQUENTIAL`; the `engine_input/v1` schema; the feasibility record), AUT-6 (C4 `DRIFT`/`HEALTH` incl. the `fee_schedule` verdict; the intraday producer; `deliver_with_proof`, the outbox drain and its claim order (E-1); the `DRILL_INJECT` and `DRILL_INJECT_HALT` detectors; the health heartbeat; the INTEGRITY-floor demand writer), AUT-1 (C1 `EntryVeto` writer, `health.capture_join`), AUT-3 (C3 candidates under the 1-per-day mint ceiling), AUT-7 (rollback selection, failed-rollback HALT and `TARGET_INELIGIBLE` rules, drill steps) |
| Downstream | AUT-7 (co-writes C5 through the engine API; AUT-7b is this area's live proof), AUT-1 (reads `registry_seq` and `drill` from the fold), AUT-6 (veto and alert surface), AUT-2 (consumes the STOP-completion signal), AUT-4 (reads the nomination columns and `lineage_counters`) |
| Status | PLANNING. Nothing here is implemented. Plan only: no commit, stash, `uv`/`pip` or `systemctl` action was taken to write it. |
| Path convention | Repo paths are repo-root-relative (`src/…`, `deploy/…`, `tests/…`, `docs/…`). Runtime paths are absolute under the data root **`/home/jon/.local/share/breezy/`**; a runtime path written `registry/…`, `derived/…`, `evidence/…` or `state/…` is relative to that absolute root. Units write it as `%h/.local/share/breezy/`. |

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

**ARCH Rev 9.2 §10 AUT-5 obligations (verbatim).**
> the policy ruling and its `autonomy-policy/v1` block (every key, every value within bounds, drill clause and window, `forward_window_days` and anchor, `attest_required_detectors`, detector cause classes); the pinned drawdown producer with its label handshake and H0 calibration tests (P5-6, review M6); `BOOTSTRAP_SEED` genesis rows (P5-2); `build_child_env` at four sites (P5-3); `registry_shadow` and the shadow root (P5-7); the `launch_precheck_failed` signal and two-pass timer (P5-5); the engine input journal writer (P4-9); `DEFAULT_RESTRICTIVE_CLASS` (P4-10); the dead-man's health-heartbeat read (P6-13); the `FillReader` (P5-4); the engine's daily, intraday (restrictive plus ATTEST, heartbeat) and pre-launch modes, staggered timers and lock; the ATTEST cadence meeting the §4.5 invariant (W1); the watch actor (loop-thread bridge); `entry_guard` with its exact-key read path, the injected `FillReader`, the lint-imports contract and the per-tick cache, plus the required `entry_veto` slot per kind (W6, W10); HWM key handling and the `breezy-registry-hwm-reset` CLI (restrictiveness check, counter carry, export supersession; W4); the demand directory and its archive (W16); the supervisor's journaled STOP-completion signal (W8); supervisor env handoff, the relaunch rule, the post-launch SWAP_CANCEL relaunch and the registry-aware `breezy-trade-relaunch` helper replacing the hand `systemd-run` runbook; the dead-man (P6-5); bootstrap with the root copy and exemption (P7-1, P7-5); the G34 base fix; the 15 min SLO test harness; the §5.2 per-mode engine bounds; pre-launch-only RESUME (P7-9); the artefact handoff (P7-10); the relaunch-request TTL (P5-11); V4–V7, V18, V19, U1, U2, U13, U14 as C5, §4.2, §4.4 and §5.2 state them (ROOT_ADMIT, nomination columns, ATTEST arming, the 16:52:30 slot and 16:47:30 lock case, `relaunch/v1` and cut-over, the `eta_date` bound); the §5.3 drill timeline, unchanged (P7-14).

**Obligation → WP map.**

| Obligation | WP |
|---|---|
| Policy ruling and block (every key; drill clause incl. sequence, 27 d start rule, `drill_max_episode_days`; `forward_window_days` + anchor; `attest_required_detectors`; cause classes incl. `DRILL`, `ROLLBACK_FAILED` handling; `root_admit_enabled`) | WP3 |
| Drawdown producer, label handshake, H0 tests | WP11 (producer), WP3 (H0 calibration) |
| `BOOTSTRAP_SEED` genesis rows; root copy; root exemption | WP1 (store), WP4 (`--mode bootstrap`), WP2 (resolver exemption) |
| `build_child_env` at four sites; env handoff; relaunch rule; post-launch SWAP_CANCEL relaunch | WP6 |
| `registry_shadow` and the shadow root | WP2 (resolver), WP5 (actor), WP6 (supervisor), WP10 (stage S) |
| `launch_precheck_failed` signal and two-pass timer (16:52:30 guaranteed, 16:57:30 best-effort) | WP6 (signal), WP4 (timer) |
| Engine input journal writer | WP4 |
| `DEFAULT_RESTRICTIVE_CLASS` | WP1 (pin), WP4 (fallback) |
| Dead-man incl. health-heartbeat read and outbox drain | WP8 |
| `FillReader`, `entry_guard`, lint-imports contract, per-tick cache | WP1 (contract), WP2 (guard, reader), WP5 (cache) |
| Engine modes, staggered timers, lock, §5.2 per-mode bounds, 16:47:30 lock case | WP4 |
| ATTEST cadence (§4.5 invariant), ATTEST arming (V5) | WP4 (writer), WP5 (veto arming) |
| Watch actor (loop-thread bridge); required `entry_veto` slot | WP5 |
| HWM key; `breezy-registry-hwm-reset` | WP5 (key), WP8 (CLI) |
| Demand directory, INTEGRITY slots, producer restrictive writes, archive | WP1 (writer), WP4 (engine use and archive), WP5 (actor read) |
| STOP-completion signal | WP6 |
| `breezy-trade-relaunch`, `relaunch/v1`, TTL | WP7 |
| G34 base fix; containment widening | WP2 |
| 15 min SLO harness | WP4 + WP5 |
| Pre-launch-only RESUME; ROLLBACK + ACTIVATE atomic; ROOT_ADMIT | WP4 |
| Artefact handoff | WP5 |
| Nomination columns (V4); d0 rule (U1, R9.2-Z1) | WP1 |
| ROOT_ADMIT (V6, U2, R9.2-Z2/Z3, E-2) | WP1 (table), WP4 (pre-launch writer), WP3 (`root_admit_enabled=false`) |
| `eta_date` bound and drill cost (V19) | WP3 |
| §5.3 drill timeline (P7-14) | WP4 (mechanics), WP10 (run) |
| Lineage allowlist widening; widening-stage flag | WP9 |
| Staged activation, cut-over (V18) and live proof | WP10 |

## 2. L-1 null hypothesis and reuse

| New component | Nautilus / existing Breezy capability checked | Verdict |
|---|---|---|
| C5 registry (store, chain, fold) | Nautilus has no artefact registry, champion/challenger state or promotion engine (ARCH §2 L-1; `WORK_BREAKDOWN:288`). `SqliteStateStore` (`src/breezy/runtime/sqlite_store.py:117-176`) is a thread-confined WAL KV with no iteration (G7); the exec store's flock is node-held (G6). | **Build**, as ARCH C5 mandates (`journal_mode=DELETE`). Reuse the exact-set and raw-byte-sha conventions of `load_family_manifest` (`src/breezy/persistence/family_manifest.py:285-296`) and the `mode=ro` URI reader `read_family_halt_rows_readonly` (`src/breezy/strategy/current_rung_hold/trial_day_latch.py:354-379`, which already passes `timeout=busy_timeout_s`, default 1.0 s; verified by codegraph). |
| Policy engine | `promotion_criteria.py` predicates (`evaluate_c_kill` `:195-281`, `evaluate_c_n` `:486-497`, `evaluate_c_estimator` `:526-556`, `assemble_outcome` `:613-637`); the proposal generator is advisory only (G14). | **Build the engine; reuse the predicates** through AUT-4's producers. The engine never recomputes a statistic. |
| Drawdown producer | No drawdown statistic over labels exists. `run_sequential_looks` (`family_tally_v2.py:625`) is a sequential test. | **Build a small producer** (`src/breezy/analysis/autonomy_producers/drawdown.py`): a pure fold over C2 rows. ARCH §5 assigns it to AUT-5 as C4 `DRIFT` (P5-6). |
| Commit-free promotion authorisation | `live_orders_authorized` with a literal allowlist plus re-hash (`src/breezy/persistence/live_orders_gate.py:76-84,130-190`). | **Extend** with one reviewed row in `_LINEAGE_POLICY_ALLOWLIST` (WP9). Roots keep their own triple (P7-1). |
| Engine policy identity before WP9 | None. | **Build** `pins.POLICY_RULING_PIN`, a literal `(ruling_id, sha256)` set in WP3's filing commit; WP9 asserts the allowlist row equals it. |
| Entry-only demotion | Nautilus `TradingState.REDUCING` (`risk/engine.pyx:1150-1163`) denies a BUY only when net long and is node-global (ARCH §2). FQ `try_submit` guard chain (`src/breezy/strategy/forecast_quantile_ladder/strategy.py:629-645`). | **Extend the native guard slot** with a separate required `entry_veto` slot; `submit_veto` reaches the exec client (G23), so it is not reused. |
| In-node registry watch | `FeeDriftProbeActor` timer → `asyncio.run_coroutine_threadsafe` (`fee_drift_probe.py:358-372`); `LiveClock` callbacks on `_DummyThread` (`tests/contract/test_live_timer_thread_affinity.py:90-119`). | **Reuse the pattern**; no new threading primitive. |
| Rung net-position guard | Exec-store exact keys `fill_index/<instrument_id>` and `fill/<venue_order_id>` (`src/breezy/adapters/polymarket_us/exec/client.py:408-447`), `DurableFillRecord.from_bytes` (`:1004-1066`). `Portfolio.net_position` depends on unverified composite-leg netting (L-44). | **Reuse the durable fills** through an injected **`FillReader`** Protocol (ARCH W6, P5-4), implemented in `src/breezy/adapters/polymarket_us/exec/fill_reader.py` and wired by `src/breezy/app/trade.py`. |
| Spend continuity across a sender change | `DailySpendLedger` is process-local (`operator_controls.py:264-305`), seeded once per process by `_seed_spend_from_durable_fills` (`exec/client.py:2216-2275`, verified by codegraph: walks the provider's instruments plus today's day index, `:2213`, de-duplicated per venue order, fail-closed on a dangling index); the exhaustion key is venue-scoped (`:399`, G21). | **Reuse unchanged** (§3.12). No new ledger. |
| Supervisor pickup and STOP signal | `_do_launch` (`src/breezy/runtime/trade_supervisor.py:1209-1301`, spawn `env=os.environ` at `:1289-1291`, verified) and spawns at `:1379`, `:1631`, `:1977-1982` (G22). `_do_stop_prior` (`:1131-1190`, verified) logs `stop_prior_noop`/`stop_prior_refused`/`stop_prior_race_refused`/`stop_prior_sigterm` and polls `intent_lock_free` (`:1185-1188`) but writes no durable completion record. Schedule poll 60 s (`trade_supervisor_core.py:1866`, G40). | **Extend.** One pure `build_child_env(base, state)`, a resolver port, a write-once STOP-completion file and write-once launch-event records. No new scheduler. |
| Relaunch helper | Hand runbook (memory note `hand-relaunch-mechanics`). | **Replace** with a supervisor-executed write-once `relaunch/v1` request (§3.7). |
| Halt mirror | `read_family_halt_rows_readonly`, `decode_family_halt_state` (`trial_day_latch.py:354`, G20). | **Reuse read-only**; contingent move-only extraction to `src/breezy/persistence/autonomy/halt_rows.py` if the engine closure would otherwise pull `breezy.strategy.*`. |
| Artefact handoff | `load_live_calibration(path, *, expected_sha256)` (`src/breezy/strategy/forecast_quantile_ladder/calibration_artefact.py:236-256`, verified): one `read_bytes`, sha check, parse of the same buffer; follows symlinks. | **Widen** the single read to `O_NOFOLLOW` (L-12) and pass the resolver's content-addressed store path plus the row sha (P7-10). |
| Alert delivery, outbox drain | `deliver_with_proof` and the outbox drain are AUT-6's (`src/breezy/runtime/alert_delivery.py`, ARCH §4.6; claim order per errata E-1). | **Consume.** AUT-5 writes no sink, no ledger file and no drain of its own. |
| Import-closure hash at runtime | grimp is the engine behind `lint-imports`; building its graph at every 5 min oneshot start costs seconds and hundreds of MB. | **Gate-time grimp, runtime manifest** (a committed module list verified against grimp in the gate; runtime hashes file bytes). |
| Operator halt tools | `breezy-set-family-halt` / `breezy-clear-family-halt`. | **Unchanged.** Mirrored read-only. |

## 3. Design

### 3.1 Package layout and layers

Layer rule (`pyproject.toml:74-101`): `app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain`. Live packages never import `breezy.analysis` (`pyproject.toml:128-151`, G15).

| Module | Layer | Contents |
|---|---|---|
| `src/breezy/persistence/autonomy/__init__.py` | persistence | Public names only. |
| `src/breezy/persistence/autonomy/canonical.py` | persistence | `canonical_json(obj) -> bytes` (sorted keys, no NaN, explicit serialisers, never `dataclasses.asdict`); `sha256_hex(b)`. |
| `src/breezy/persistence/autonomy/single_read.py` | persistence | `read_once_nofollow(path, *, root, max_bytes) -> bytes` (`lstat` walk refusing any symlink component, `O_RDONLY\|O_NOFOLLOW`, one read, size cap); `read_once_at(dirfd, name, *, max_bytes)` (`openat` with `O_NOFOLLOW` on an `O_DIRECTORY\|O_NOFOLLOW`, `fstat`-checked dir descriptor, U7); `write_once(path, data, *, mode)` (`mkstemp` + `os.link`, refusing an existing name; fsync file and directory). `SingleReadRefused(reason)`. |
| `src/breezy/persistence/autonomy/schemas.py` | persistence | Frozen dataclasses and enums: `State`; `Kind` (BOOTSTRAP, MINT, PROMOTE, DRILL_ADMIT, DRILL_PROMOTE, ROLLBACK, ROOT_ADMIT, SUPERSEDE, DISPLACED, ACTIVATE, SWAP_CANCEL, TARGET_INELIGIBLE, ATTEST, DEMOTE, HALT, RESUME, RETIRE, HWM_RESET); `CauseClass` (RECOVERABLE_MODEL, RECOVERABLE_INFRA, DRILL, TERMINAL, INTEGRITY, ROLLBACK_FAILED); `CauseCode` (closed, from `pins.CAUSE_CODES`, incl. `rollback_failed`, `target_integrity`); `WriterMode` (DAILY, INTRADAY, PRELAUNCH, BOOTSTRAP, OPERATOR_CLI); `TransitionRow` (every C5 column, §3.2); `Verdict`; `DemandRecord` (`demand/v1`); `Heartbeat` (`heartbeat/v1`); `StopComplete` (`stop_complete/v1`); `LaunchEvent` (`launch_event/v1`); `HaltMirrorRecord` (`halt_mirror/v1`); `DrillMarker` (`drill_marker/v1`); `RelaunchRequest` (`relaunch/v1`); `ResolvedFamily`. |
| `src/breezy/persistence/autonomy/transitions.py` | persistence | `ALLOWED` (the ARCH C5 table verbatim, incl. the BOOTSTRAP genesis rows, ROOT_ADMIT and TARGET_INELIGIBLE); `KIND_MASK: Final[Mapping[WriterMode, frozenset[Kind]]]` (§3.2); `WIDENING_KINDS`; `RESTRICTIVE_KINDS`; `validate(fold, row, *, mode, now_ns) -> None \| RefusalReason`. |
| `src/breezy/persistence/autonomy/registry_store.py` | persistence | `RegistryStore` (rw) and `RegistryReader` (`mode=ro`, `busy_timeout` parameter). DDL, triggers, CAS, chain, mask and stage-flag enforcement, nomination and mint-rate enforcement, d0 check, export writer with `export_seq`, cache refold. |
| `src/breezy/persistence/autonomy/fold.py` | persistence | Pure `fold(rows, venue, now_ns) -> FoldResult` (states; pending, lapse and post-launch voiding; counters charged on effect; `carried_counters` floors; `drill_episode`; `rollback_eligible`; `target_ineligible`; `demoted_for_cause`; `terminal_frozen`; INTEGRITY freeze; standing causes per family for first-cause-wins and RESUME; nomination index `k_life` and window slots; drill counters). |
| `src/breezy/persistence/autonomy/replay.py` | persistence | `replay_full(rows, *, verdict_root, artefact_root) -> ReplayResult`: re-runs `transitions.validate` row by row over the growing fold, resolves the `cause_verdict_ids` of every widening row to a file whose sha equals the id, and checks artefact bytes against each binding row's `artefact_sha256`. |
| `src/breezy/persistence/autonomy/resolver.py` | persistence | `resolve_sending_family(...) -> ResolvedFamily \| ResolverRefusal`. Calls `replay_full`. The only reader of `BREEZY_FAMILY_SOURCE` besides `build_child_env` (U14). |
| `src/breezy/persistence/autonomy/policy.py` | persistence | `load_policy_block(repo_root, pin) -> PolicyBlock \| PolicyUnavailable`: single read of the deploy copy, sha equal to `pins.POLICY_RULING_PIN`, exactly one fenced `autonomy-policy/v1` block, strict JSON, exact-set keys, every value within `pins` ceilings. |
| `src/breezy/persistence/autonomy/pins.py` | persistence | Literal §4.5 ceilings; `ENGINE_SOURCE_SHA256`; `PRODUCER_SOURCE_SHA256`; `REVOKED_SOURCE_SHA256`; `LIVE_GATE_ROUTED_KINDS`; `BOOTSTRAP_SEED`; `DEFAULT_RESTRICTIVE_CLASS` (P4-10); `DEMAND_WRITER_PRODUCER_IDS = ("aut6.intraday",)`; `DEMAND_REASONS`; `CAUSE_CODES`; `ROOT_ADMIT_ENABLED_CEILING = False`; `POLICY_RULING_PIN`; `ENABLED_WIDENING_KINDS`; `ENGINE_LOCK_MAX_HOLD_S = 15`; `RELAUNCH_REQUEST_TTL_S = 120`; `WATCH_BUSY_TIMEOUT_MS = 250`. |
| `src/breezy/persistence/autonomy/closure_manifest.py` | persistence | `CLOSURE_MODULES: Final[Mapping[str, tuple[str, ...]]]` keyed by component (`engine`, each producer id); regenerated by `scripts/ci/regen_closure_manifest.py`. |
| `src/breezy/persistence/autonomy/closure.py` | persistence | `closure_sha256(component) -> str` (manifest modules, `find_spec(m).origin`, one `read_once_nofollow` each, sorted `(module, bytes)`, excluding `pins` and `closure_manifest`; no grimp at runtime). `closure_from_grimp(entry)` is gate-only. |
| `src/breezy/persistence/autonomy/demand.py` | persistence | The one `demand/v1` writer and reader (C5 Z11, V9, U13): engine files `<family_id>_<ts_ns>_<writer>.json`; producer files `<family_id>_<reason>_<verdict_id>_<producer>.json` only for ids in `DEMAND_WRITER_PRODUCER_IDS`, one unarchived file per `(family, reason)`, idempotent on `verdict_id`; producer files other than `reason=integrity_floor` capped at `DEMAND_FILES_MAX − DEMAND_INTEGRITY_RESERVED` per venue; `archive(path, *, reject_reason=None)` callable only with the engine's `WriterMode`. Write-once through `single_read.write_once`. |
| `src/breezy/persistence/autonomy/entry_guard.py` | persistence | `FillReader` Protocol (`fill_index(instrument_id) -> tuple[str, ...]`, `fill_record(venue_order_id) -> tuple[str, Decimal]` (signed side, cumulative qty); raises `GuardUnreadable`); `rung_has_net_position(base_slug, *, reader, legs) -> bool \| GuardUnreadable` (exact keys only, leg-signed netting per C2). |
| `src/breezy/persistence/autonomy/plugin.py` | persistence | C6 Protocols plus `RefusingPlugin`. |
| `src/breezy/strategy/autonomy/node_plugins.py` | strategy | `NODE_PLUGINS` (FQ full; three `RefusingPlugin`s). |
| `src/breezy/analysis/autonomy/offline_plugins.py` | analysis | `OFFLINE_PLUGINS` (same key set). |
| `src/breezy/strategy/autonomy/registry_watch_actor.py` | strategy | `RegistryWatchActor(Actor)`, `RegistryWatchConfig`, `VetoReason` (the ARCH closed enum), per-tick guard cache. |
| `src/breezy/adapters/polymarket_us/exec/fill_reader.py` | adapters | `PolymarketUsFillReader`: implements `FillReader` over the existing prefix constants and `DurableFillRecord.from_bytes` through the G6 `mode=ro` URI; writes no key. |
| `src/breezy/analysis/autonomy_engine/{__init__,cli,phases,daily,intraday,prelaunch,bootstrap,acceptance,input_journal,fallback,mirror,demand_io,heartbeat,attest,mint,nominate,drill,root_admit,launch_events,export,alerts}.py` | analysis | The engine (§3.3). Console script `breezy-autonomy-engine`. AUT-7's `engine/rollback/` package runs inside this closure. |
| `src/breezy/analysis/autonomy_producers/drawdown.py` | analysis | The `live.drawdown` producer (§3.11). Console script `breezy-autonomy-producer-drawdown`. |
| `src/breezy/runtime/autonomy_deadman.py` | runtime | `breezy-autonomy-deadman` (§3.8). |
| `src/breezy/runtime/registry_hwm_reset_cli.py` | runtime | `breezy-registry-hwm-reset`. |
| `src/breezy/runtime/registry_verify_cli.py` | runtime | `breezy-registry-verify`. |
| `src/breezy/runtime/trade_relaunch_cli.py` | runtime | `breezy-trade-relaunch`. |

`entry_guard` sits in `persistence` as ARCH names it; the adapter-owned keys and decoder arrive through `FillReader`, pinned by the forbidden contract `breezy.persistence.autonomy ↛ breezy.adapters` (`lint-imports`, run from the tree root).

### 3.2 C5 store

- **Path and mode.** `/home/jon/.local/share/breezy/registry/registry.sqlite`, dir 0700, file 0600, `journal_mode=DELETE`, `synchronous=FULL` (Y5). Shadow stage: `/home/jon/.local/share/breezy/registry-shadow/`, identical layout (P5-7).
- **DDL.** `transitions` holds exactly the ARCH C5 columns: `seq`, `venue`, `venue_seq`, `transition_id`, `family_id`, `family_prior_seq`, `paired_transition_id`, `from_state`, `to_state`, `kind`, `cause_verdict_ids`, `cause_code` (DEMOTE, HALT, SWAP_CANCEL, TARGET_INELIGIBLE), `halt_cause_class`, `trigger_cause_class` (a `rollback_failed` HALT only), `voids_transition_ids` (SWAP_CANCEL only), `manifest_sha256`, `artefact_sha256`, `lineage_root_family_id` (**required** on BOOTSTRAP, MINT, PROMOTE, DRILL_PROMOTE, ROLLBACK, ROOT_ADMIT, ACTIVATE), `attest_valid_until_ns` (ATTEST only), the **C5 nomination columns** `k_life`, `alpha_k`, `n_min_eff`, `n_cap`, `nomination_feasible` (**required** on SHADOW→CHALLENGER PROMOTE, null elsewhere, V4), `hwm_from`, `hwm_to` (HWM_RESET only), `drill`, `drill_clause_sha256`, `policy_ruling_id`, `policy_ruling_sha256`, `decided_by`, `invocation_id`, `engine_code_sha`, `expected_prior_seq`, `effective_launch_date`, `ts_ns`, `prev_transition_hash`, `transition_hash`; plus `carried_counters` on HWM_RESET (C5 HWM reset). `UNIQUE(venue, venue_seq)`, `UNIQUE(transition_id)`. `BEFORE UPDATE` / `BEFORE DELETE` triggers `RAISE(ABORT,'append-only')`. Derived caches `families`, `projection`, `lineage_counters`, never read by the node, supervisor or resolver (Y4). `meta(schema='registry/v1')`.
- **`lineage_counters`** (C5): `holdout_opens`, `nominations` (= max `k_life`), `infeasible_nominations`, `alpha_spent`, `mints` and `promotions` (timestamped), `rollbacks`, `terminal_frozen`, the drill budget `drill_admits`, `drill_promotes`, **`drill_demotes`**, `drill_resumes`, **`drill_halts`**, `drill_rollbacks` (each ≤ 1 per `DRILL_BUDGET_PER_VENUE_30D` window and refused above, V15), and the venue-level `infra_resumes`.
- **Write path.** `RegistryStore.append(rows, *, expected_prior_seq, mode: WriterMode) -> AppendResult`. One `BEGIN IMMEDIATE`. If every `transition_id` exists: logged no-op. Otherwise, inside the store and before insert:
  1. every row's kind ∈ `KIND_MASK[mode]`, else `KindRefused(mode, kind)`;
  2. every widening row's kind ∈ `pins.ENABLED_WIDENING_KINDS`, else `WideningNotEnabled(kind)`; a ROOT_ADMIT additionally needs `pins.ROOT_ADMIT_ENABLED_CEILING` and the block's `root_admit_enabled` (§4.2);
  3. **nomination limits (C4, ALPHA as amended):** a SHADOW→CHALLENGER PROMOTE is refused when the lineage's current forward window (tumbling from `forward_window_anchor_date` by `forward_window_days`) already holds one nomination (`MAX_NOMINATIONS_PER_FORWARD_WINDOW` = 1), or when α-charging nominations have reached K_LIFETIME; its `k_life` must equal the fold's next index when `nomination_feasible = true` (and the fold's current index, unchanged, with `alpha_k = 0`, when false); two pending nominees never share a k. The k checks read the nomination columns only (`test_nomination_columns_required_and_read_by_k_check`);
  4. **mint rate:** a MINT is refused once the lineage holds one counted MINT that UTC day across all model classes (`MintRefused(per_day)`); a no-new-lineage drill MINT increments no counter (C3 Y2) and is not counted;
  5. **d0 and identity (U1, R9.2-Z1):** on a family's first →CHAMPION row (PROMOTE CHALLENGER→CHAMPION or DRILL_PROMOTE) the child manifest's `d0_climate_day` must be ≥ that row's `effective_launch_date` and > every earlier d0 in the lineage, and `trial_id_prefix` must equal `f"{composition_kind}/trial/{child_id}/"`; ROLLBACK, RESUME and ROOT_ADMIT are exempt;
  6. CAS `max(venue_seq) == expected_prior_seq`;
  7. `transitions.validate` against `fold(prior ∪ new)`;
  8. insert, extend chain, refold caches, `COMMIT`.
- **`KIND_MASK` (literal).**

| `WriterMode` | Kinds |
|---|---|
| `INTRADAY` | DEMOTE, HALT, SWAP_CANCEL, TARGET_INELIGIBLE, ATTEST (restrictive plus the non-widening ATTEST; TARGET_INELIGIBLE is restrictive and is how the next intraday pass answers a first-LAUNCH target failure, V11) |
| `PRELAUNCH` | ACTIVATE, SWAP_CANCEL, TARGET_INELIGIBLE, RESUME, ROLLBACK, SUPERSEDE, DISPLACED, ROOT_ADMIT, DEMOTE, HALT |
| `DAILY` | MINT, PROMOTE, DRILL_ADMIT, DRILL_PROMOTE, ROLLBACK, SUPERSEDE, DISPLACED, SWAP_CANCEL, TARGET_INELIGIBLE, DEMOTE, HALT, RETIRE (**no RESUME**, P7-9) |
| `BOOTSTRAP` | BOOTSTRAP |
| `OPERATOR_CLI` | HWM_RESET, DEMOTE, HALT, SWAP_CANCEL, RETIRE (the restrictive re-application) |

- **`WIDENING_KINDS`** = {PROMOTE (→CHAMPION), DRILL_PROMOTE, ROLLBACK, RESUME, ROOT_ADMIT, ACTIVATE, SUPERSEDE, DISPLACED, DRILL_ADMIT}. ATTEST, TARGET_INELIGIBLE and every restrictive kind are never masked by the stage flag. **Only PROMOTE, DRILL_PROMOTE, RESUME, ROLLBACK and ROOT_ADMIT widen sending** (C5 Relationship to existing controls); the partners and ACTIVATE are masked with them.
- **`pins.ENABLED_WIDENING_KINDS` by stage** (each change a reviewed commit, made before its stage, never inside a drill episode's no-commit window):
  - WP1 to stage S: `frozenset()`.
  - Stage L1: `frozenset({RESUME})`. RESUME restores the bootstrapped incumbent (no new sender, no new artefact); without it a RECOVERABLE_INFRA DEMOTE in L1 would strand the venue until L2.
  - Stage L2 (WP9's second commit): `WIDENING_KINDS`.
- **Chain.** `genesis = sha256(b"registry/v1|" + venue)`; `transition_hash = sha256(canonical_row ‖ prev_transition_hash)`; one chain, CAS counter and genesis per venue (Y20).
- **Bootstrap (P5-2, P7-5).** Genesis transaction of an empty venue chain only, ids in `pins.BOOTSTRAP_SEED`: `∅ → CHAMPION` for `pm_us_crh_fq_v1` and `∅ → RETIRED` for `pm_us_crh_v4`, `pm_us_crh_cont`, `pm_us_crh_v2`. For each, the engine reads the committed manifest and artefact once, verifies the artefact against `density_artefact_sha256`, and copies the bytes to `derived/artefacts/<model_class>/<sha>/artefact.json` (0444) with `root.json` (`root/v1`). Tests `test_registry_transition_table_is_exact`, `test_bootstrap_seed_genesis_only`.
- **Exports.** The daily pass writes `evidence/registry/registry_<venue>_<YYYY-MM-DD>.jsonl` (0444, write-once, L-50): every row since the previous export plus `{"chain_head","venue_seq","export_seq"}`, `export_seq` monotone. An HWM_RESET export is written once as `registry_<venue>_<YYYY-MM-DD>_hwm<export_seq>.jsonl`. Readers verify against the export with the **highest `export_seq`** (W4). Exports are never deleted.
- **Directories and writers** (rows for `test_autonomy_files_have_one_writer`, V17):

| Path (under the data root) | Lock or write-once | Writer process types |
|---|---|---|
| `registry/registry.sqlite` | `registry/engine.lock` | engine (all modes), `breezy-registry-hwm-reset` |
| `registry/families/<id>.json`, `registry/families/artefacts/<sha>.json` | write-once (content hash) | engine |
| `registry/demand/<venue>/*.json` | write-once (`ts_ns` + writer, or `verdict_id` + producer) | engine; producers in `DEMAND_WRITER_PRODUCER_IDS` |
| `evidence/demand/<venue>/` (archive by rename) | `registry/engine.lock` | engine |
| `registry/heartbeat/<venue>.json` | `registry/engine.lock` | engine (daily, intraday) |
| `registry/drill/marker.json` | `registry/engine.lock` | engine (write in daily, removal in intraday) |
| `evidence/engine_inputs/<venue>/<date>/<mode>_<ts_ns>.jsonl` | write-once | engine |
| `evidence/halt_mirror/<venue>/<date>/<ts_ns>_<mode>.json` | write-once | engine |
| `evidence/registry/*.jsonl`, `evidence/registry/hwm_reset_<ts>.json` | write-once | engine (daily), `breezy-registry-hwm-reset` |
| `state/supervisor/stop_complete_<trading_day>.json` | write-once | supervisor |
| `state/supervisor/launch_events/<ts_ns>_<writer>.json` | write-once | supervisor, node |
| `state/relaunch/request_<request_id>.json` | write-once | `breezy-trade-relaunch` |
| `state/relaunch/response_<request_id>.json`, `state/relaunch/handled/<request_id>` | write-once | supervisor |
| `registry/deadman.lock`, `derived/verdicts/.drawdown.lock` | lock files | dead-man; drawdown producer |

All writes are atomic (`mkstemp` + `os.replace`, or `os.link` for write-once). Engine alert delivery records are AUT-6's write-once `evidence/alerts/<date>/<ts_ns>_engine_<d|f>.json`; the r2 `registry/alert_ledger` file is dropped (§3.3.8).

### 3.3 Engine (`breezy-autonomy-engine --mode {daily,intraday,prelaunch,bootstrap}`)

**Common start, in order** (none of it under the lock):
1. `closure_sha256("engine")`. Refuse (exit 2, CRITICAL `AUTONOMY_ENGINE_UNPINNED`) unless it is in `ENGINE_SOURCE_SHA256` and not in `REVOKED_SOURCE_SHA256`.
2. `policy.load_policy_block(repo_root, pins.POLICY_RULING_PIN)`. On `PolicyUnavailable` (pin empty, file missing, sha mismatch, parse failure, value looser than a ceiling) the run continues in **restrictive fallback** (§3.3.2) and raises CRITICAL `AUTONOMY_POLICY_UNAVAILABLE` once per UTC day.
3. Read the verified chain through `RegistryReader` and fold at `now`. Read and judge every verdict valid at pass start for a family in the fold (§3.3.3). Compute the candidate rows for each phase.

Every transition carries `engine_code_sha`, `invocation_id` (uuid4), `decided_by="engine"`, `policy_ruling_id` and `policy_ruling_sha256` (in fallback: the pin's values, or empty strings when the pin is empty).

#### 3.3.1 Locks and phases (§5.2)

- **One lock**, `registry/engine.lock`, never the studies flock (Y23). Waits are the §5.2 values: daily `flock -w 120`, intraday `-w 20`, pre-launch `-w 60`, bootstrap `-w 10`.
- **Daily: phase-scoped holds.** `phases.run_phase(name, build_rows, *, mode)` acquires the lock, re-reads only the chain delta above the head it folded, re-validates (re-building if the delta touched the same family), calls `RegistryStore.append(..., mode=DAILY)` and releases. It refuses to append past `ENGINE_LOCK_MAX_HOLD_S = 15` (it releases and defers the phase to the next pass, logging `engine_phase_deferred phase=<n>`). I/O-heavy work (C3 reads, verdict acceptance, artefact copies, export rendering) runs **before** acquiring. 15 s < the intraday 20 s wait, so an intraday pass waits at most one daily phase.
- **Daily phase order:** **R** (exec-store mirror; accepted FAIL → DEMOTE/HALT, with SWAP_CANCEL of a pending pair; TARGET_INELIGIBLE from selection-time re-verification) → RETIRE (incl. the drill child at D+4) → MINT → nomination PROMOTE (SHADOW→CHALLENGER) → CHALLENGER→CHAMPION PROMOTE (only if `promote_enabled`, §3.9) → AUT-7 rollback selector (`engine.rollback.propose(fold)`, pending ROLLBACK pair, or the failed-rollback HALT retry) → drill steps (§3.10) → export → engine input journal → heartbeat. **The daily pass never writes RESUME** (P7-9).
- **Pre-launch: one hold for the whole pass** (it ends ≤ 16:49Z by its bound). Order: own halt-mirror read and record (§3.3.10) → post-STOP verdict check → for each pair pending for today's LAUNCH: §4.4 plus manifest and artefact sha re-verification (V11) → ACTIVATE, or SWAP_CANCEL (+ TARGET_INELIGIBLE on a byte failure) → RESUME candidates → a ROLLBACK pair **with** its ACTIVATE in one transaction for a trigger accepted since the last pass (P7-4) → failed-rollback HALT → ROOT_ADMIT **with** its ACTIVATE (only when enabled) → journal → heartbeat. At most one logical sender change per venue per day (`MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` in the block, §3.9).
- **Intraday: one hold.** On lock timeout it writes a restrictive-demand file for every accepted FAIL it computed (§3.3.5), logs `engine_lock_timeout demand_written=<n>`, raises WARNING `AUTONOMY_ENGINE_LOCK_TIMEOUT` and exits 0. The **16:47:30Z** firing meets the pre-launch hold (≤ 16:49Z), times out by 16:47:50Z and takes this path (V7; `test_intraday_pass_yields_to_prelaunch_lock`).
- Tests: `test_restrictive_slo_met_while_daily_holds_lock`, `test_daily_lock_hold_never_exceeds_max_hold`, `test_intraday_lock_timeout_writes_demand`, `test_intraday_pass_yields_to_prelaunch_lock`.

#### 3.3.2 Restrictive fallback (P4-10)

When the policy is unavailable the engine runs restrictive-only in every mode:
- It writes only DEMOTE, HALT, SWAP_CANCEL and TARGET_INELIGIBLE (the store's `KIND_MASK` still applies; the engine additionally refuses every other kind).
- The exec-store halt mirror runs unchanged.
- Acceptance follows ARCH C4 "Restrictive fallback": a FAIL is accepted **only** for DEMOTE or HALT, with action and cause class taken from the literal `pins.DEFAULT_RESTRICTIVE_CLASS[detector]`, never for a widening row. The verdict must carry `policy_ruling_sha256` equal to the pin's sha (pin set) or `null` with `assumptions ∋ no_policy_ruling`; producer pin, input resolution, subject binding and validity ceilings still apply.
- `DEFAULT_RESTRICTIVE_CLASS` holds the DEMOTE/HALT detectors of §3.9: `freshness.persist`, `liveness.permit_process`, `health.capture_join`, `health.alert_canary`, `reconciliation.net_position`, `reconciliation.post_stop` (DEMOTE, RECOVERABLE_INFRA); `drift.forecast_input`, `drift.calibration_live`, `drift.fill_rate_slippage`, `parity.train_serve` (DEMOTE, RECOVERABLE_MODEL); `live.sequential` (HALT, RECOVERABLE_MODEL); `live.kill_clock`, `live.drawdown` (HALT, TERMINAL). `DRILL_INJECT` and `DRILL_INJECT_HALT` are **not** in it: outside an active clause they are `ERROR`.
- No ATTEST is written (no PASS is accepted without a policy), so `registry_attest_expired` vetoes entries within `ATTEST_VERDICT_VALIDITY_H` (Y3). This is the intended fail-closed outcome.
- Tests: `test_demotion_never_requires_policy_and_is_immediate` (policy file removed or tampered: an accepted FAIL from a `DEFAULT_RESTRICTIVE_CLASS` detector commits a DEMOTE in the same intraday pass, and no non-restrictive row is written), `test_no_policy_fail_demotes_never_widens`, `test_policy_map_not_looser_than_fallback_map` (the filed block maps no fallback detector to a weaker action).

#### 3.3.3 Verdict acceptance and the engine input journal (ARCH C4, P4-9)

Acceptance (`acceptance.py`), in ARCH order; the first failure names the `reject_reason`:
1. `verdict/v1` exact-set.
2. `producer_code_sha ∈ PRODUCER_SOURCE_SHA256[producer_id]` (else `unpinned_producer`).
3. Every `inputs[].sha256` resolves under that role's root (else `input_unresolved`).
4. `policy_ruling_sha256 ==` the policy sha (fallback: §3.3.2); for `LIVE_SEQUENTIAL`, `family_prereg_sha256 ==` the family's registered boundary ruling (else `no_ruling`).
5. `declared_action_class ==` the map's entry for `detector` (else `action_class_mismatch`).
6. `valid_until_ns − produced_at_ns ≤ MAX_VERDICT_VALIDITY_H`, or ≤ `ATTEST_VERDICT_VALIDITY_H` for a verdict an ATTEST cites; and `now < valid_until_ns` (else `expired`).
7. `subject_artefact_sha256 ==` the subject family's bound sha, from its BOOTSTRAP or MINT row (else `subject_unbound`/`sha_mismatch`).
8. `FORWARD_SHADOW`: its `k_life` equals the registry's index for its nominee (else `k_exceeded`, a defect alert, P3-10).

`ERROR`, `INCONCLUSIVE` and `UNDERPOWERED` never promote. An accepted FAIL mapped to DEMOTE or HALT always acts. Any rejection is a WARNING `AUTONOMY_VERDICT_ERROR` and no action.

**Engine input journal (`input_journal.py`).** One write-once JSONL per pass, `evidence/engine_inputs/<venue>/<date>/<mode>_<ts_ns>.jsonl` (0444), one row per verdict read: `pass_id`, `pass_mode`, `verdict_id`, `kind`, `subject_family_id`, `detector`, `acceptance`, `reject_reason` (the closed set above), `acted`, `transition_id`. AUT-4 owns the schema and its contract test. Every verdict valid at pass start for a family in the fold appears once; every `cause_verdict_ids` entry appears with `acted=true`; **a pass that cannot write its journal writes no widening row** (restrictive rows still commit). Tests `test_every_live_verdict_journaled_once_per_daily_pass`, `test_cause_verdict_ids_subset_of_acted_rows`.

#### 3.3.4 Modes, timers, units (`TimeoutStartSec`; §5.2 launch-window table)

Every unit is `Type=oneshot` and bounded by `TimeoutStartSec=`; none sets `RuntimeMaxSec=` (a no-op on oneshot, G32; programme rule; `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec` fails on any autonomy oneshot carrying it). Each unit's [start, start + `flock -w` + `TimeoutStartSec`] is checked against [16:30Z, 17:10Z) by `test_no_unit_overlaps_launch_window`; only the launch-path rows of §5.2 run inside, each ending before its next fixed point (`test_launch_path_units_end_before_next_fixed_point`).

| Unit (lock) | Timer (UTC) | `flock -w` | `TimeoutStartSec` | Ends by | `MemoryMax` | Mask | Work |
|---|---|---|---|---|---|---|---|
| `breezy-autonomy-engine@daily` (engine) | `*-*-* 15:30:00` | 120 s | 900 s | 15:47Z | 1G | `DAILY` | §3.3.1 phases; writes pending pairs |
| `breezy-autonomy-engine@intraday` (engine) | `*-*-* *:02/5:30` (150 s after AUT-6's `*:00/5` producer) | 20 s | 120 s | start + 140 s (16:39:50 < STOP; 16:44:50 < pre-launch; 16:59:50) | 512M | `INTRADAY` | Halt mirror; accepted FAIL → DEMOTE/HALT (+ SWAP_CANCEL of a pending or just-effective pair; post-launch voiding only in [16:50Z, 17:00Z)); first-LAUNCH target integrity → SWAP_CANCEL + TARGET_INELIGIBLE; INTEGRITY HALT on a champion's own load failure; **ATTEST** (§3.3.6); demand archive; drill-marker removal after the drill DEMOTE or HALT commits; heartbeat |
| `breezy-autonomy-engine@prelaunch` (engine) | `*-*-* 16:45:00` | 60 s | 180 s | 16:49Z | 512M | `PRELAUNCH` | §3.3.1 pre-launch order |
| `breezy-autonomy-engine@bootstrap` (engine) | none (manual; once per root) | 10 s | 60 s | start + 70 s | 256M | `BOOTSTRAP` | Refuses (exit 2) if the venue chain is non-empty |
| `breezy-autonomy-producer-drawdown` (own) | `*-*-* 14:50:00` | 10 s | 300 s | 14:55:10Z | 512M | n/a | §3.11 |
| `breezy-autonomy-deadman` (own) | `*:00/30` (16:30, 17:00 in the window) | 10 s | 60 s | start + 70 s | 128M | n/a | §3.8; read-only except the outbox drain |

- **The two launch-window intraday passes (P5-5, V7).** 16:52:30Z is the **guaranteed** slot: its SWAP_CANCEL commits by 16:54:50Z and the supervisor's next 60 s resolve retry launches the restored incumbent before 17:00Z. 16:57:30Z is **best-effort**: a SWAP_CANCEL after the last launch-window poll still voids the pair (the watch actor vetoes the child) but no incumbent may relaunch; that day is recorded as a lost live day (V19). Tests `test_two_intraday_passes_inside_launch_window`, `test_intraday_schedule_has_two_runs_in_launch_window`.
- **Engine unit.** `deploy/systemd/breezy-autonomy-engine@.service` (template, `%i` = mode): `ProtectSystem=strict`, `ReadWritePaths=%h/.local/share/breezy/registry %h/.local/share/breezy/evidence`, `ReadOnlyPaths=%h/.local/share/breezy/derived %h/.local/share/breezy/state %h/breezy`, `EnvironmentFile=-%h/.config/breezy/alerts.env` (G27 only), `OnFailure=breezy-study-failed@%n.service`, **no** `operator.env` and **no** venue env file.
- **Post-STOP reconcile unit: AUT-2's.** `breezy-autonomy-reconcile-poststop` (16:41Z, reconcile lock, W + T ≤ 120 s, ends 16:43Z, venue credentials through `polymarket.env`) and its §5.2 reconcile-lock rows belong to AUT-2 (ARCH §10 AUT-2, §4.4). AUT-5 owns the STOP-completion signal it consumes (§3.6) and the pre-launch requirement for its PASS (§3.3.7). r2's unit-pair ownership is withdrawn.
- **Memory (V14).** AUT-5's own-lock units peak together at ≤ 2.14G (daily 1G overlapping one intraday 512M; drawdown 512M ends before the daily pass; dead-man 128M). The cross-area sum ≤ 4G is AUT-6's `HEALTH` check (`test_health_memory_sum_within_memavailable`); AUT-5's `test_own_lock_autonomy_units_memory_total_le_4g` sums every committed autonomy own-lock unit's `MemoryMax`.

#### 3.3.5 Demand files (C5 Z11, V9, U13, W16)

- **Engine writes.** On the first failed append of a restrictive row (Y19), or on an intraday lock timeout, the engine writes `registry/demand/<venue>/<family_id>_<ts_ns>_engine.json` (0444, `demand/v1`, ≤ `DEMAND_FILE_MAX_BYTES`, `reason` ∈ `DEMAND_REASONS`) through `persistence/autonomy/demand.py`, then retries the append with bounded backoff for ≤ 60 s and again every intraday pass.
- **Reserved INTEGRITY slots.** Of `DEMAND_FILES_MAX` per venue, `DEMAND_INTEGRITY_RESERVED` slots take only engine files and producer files with `reason=integrity_floor`. Engine files always fit in the reserved slots.
- **Restrictive writes from pinned producers.** Only ids in `pins.DEMAND_WRITER_PRODUCER_IDS` (initially `aut6.intraday`) may write, through the same writer, one unarchived file per `(family, reason)`, idempotent on `verdict_id`; a capped producer writes no file, raises a CRITICAL through `deliver_with_proof` and still writes its verdict. A producer never renames, edits or deletes a demand, so it can add a stop but never lift one.
- **Archive.** When the fold shows the family HALTED, RETIRED or not CHAMPION at a row later than the demand's `ts_ns`, the engine **moves** the file to `evidence/demand/<venue>/` (atomic rename) and never unlinks it. A producer demand whose verdict the engine rejects is archived with its `reject_reason`.
- Tests: `test_demand_file_written_on_first_restrictive_failure`, `test_retired_demand_file_archived`, `test_producer_demand_flood_cannot_exhaust_integrity_slot`, `test_producer_demand_write_is_restrictive_only`, `test_rejected_producer_demand_archived_with_reason`.

#### 3.3.6 ATTEST cadence (W1, V5)

- **Writer.** The intraday pass only, at most one ATTEST per venue per `ATTEST_PERIOD_H = 6`, for the CHAMPION (a HALTED family is never attested). The **first** ATTEST for a family after its latest →CHAMPION or RESUME row is cadence-exempt and is what arms `registry_attest_expired` for it (V5).
- **Citations.** For **every** `(kind, detector)` pair in `attest_required_detectors` (§3.9: `HEALTH`/`liveness.permit_process` from AUT-6, `RECONCILIATION`/`reconciliation.net_position` from AUT-2 at its :05/:35 slots), the newest accepted verdict as a PASS within `ATTEST_VERDICT_VALIDITY_H = 8`. A daily (26 h) verdict is never citable.
- **Validity.** `attest_valid_until_ns = min(valid_until_ns)` of the cited verdicts, refused above `ts_ns + H`.
- **Invariant (§4.5).** `ATTEST_PERIOD_H + L_max + ATTEST_MARGIN_H ≤ ATTEST_VERDICT_VALIDITY_H`: 6 + (60 min + 150 s ≈ 1.04 h) + 0.5 = 7.54 ≤ 8. A missed pass is retried 5 min later; the 0.46 h of slack covers about 5 retried passes. The 16:47:30Z yield (§3.3.1) costs one pass.
- **Tests.** `test_attest_cadence_has_no_expiry_gap` (fake clock, 48 h, the full schedule table incl. the 16:47:30 yield), `test_attest_requires_every_listed_detector`, `test_attest_cites_required_kinds_and_caps_validity`, `test_first_attest_after_champion_or_resume_is_cadence_exempt`.

#### 3.3.7 §4.4 preconditions and horizons (W8, P5-10, P7-9)

- **Common to every widening write** (PROMOTE, DRILL_PROMOTE, SUPERSEDE, DISPLACED, ACTIVATE, RESUME, ROLLBACK, ROOT_ADMIT): no OPEN or AMBIGUOUS submit intent (the G30 read-only probe; at 15:30Z it is **advisory** through the G6 read-only URI because `probe_open_intent` asserts no live node, P7-6), an accepted RECONCILIATION PASS within its horizon, and no INTEGRITY freeze on the venue.
- **15:30Z pending writes** (the →CHAMPION row, its SUPERSEDE or DISPLACED partner, a pending ROLLBACK pair): the newest accepted **intraday** RECONCILIATION PASS within `ATTEST_VERDICT_VALIDITY_H`. The post-STOP verdict is **never** required at the pending write (`test_pending_write_uses_intraday_reconciliation`).
- **16:45Z only** (ACTIVATE, a ROLLBACK pair with its ACTIVATE, RESUME, ROOT_ADMIT with its ACTIVATE) and the supervisor's LAUNCH re-check that reuses its verdict: an accepted `reconciliation.post_stop` PASS with `produced_at_ns` later than **today's** STOP-completion file `ts_ns` (§3.6). No STOP file, a stale one (`trading_day` ≠ today), or an INCONCLUSIVE/FAIL post-STOP verdict means no ACTIVATE, RESUME or ROOT_ADMIT; a pending pair gets SWAP_CANCEL (`test_prelaunch_requires_post_stop_reconciliation`, `test_activate_refused_on_stale_or_absent_stop_signal`).
- **RESUME is written only by the 16:45Z pass** (`test_resume_written_only_at_prelaunch`). Its gates (C5 RESUME row): `halt_cause_class` ∈ {RECOVERABLE_MODEL, RECOVERABLE_INFRA, DRILL}, or `ROLLBACK_FAILED` with such a `trigger_cause_class` (charged to it); the cause verdict now PASSes, as does every DEMOTE/HALT-mapped FAIL accepted for the family since its halt row; no exec-store halt stands (`test_resume_requires_every_cause_cleared`); the fold names this family; no pending pair on the venue; cooldown and the budget of its own cause class only.
- Flatness is never required; the successor is protected by `rung_net_position_held`.

#### 3.3.8 Alerts

- **Order.** Every alert is sent **after** `COMMIT`. A delivery failure never raises into the append path, never rolls back a row and never blocks the next phase.
- **Delivery.** Each `AUTONOMY_TRANSITION kind=<k> family=<id> seq=<n> tid=<transition_id[:16]>` (CRITICAL for restrictive kinds and TARGET_INELIGIBLE, else INFO) and every CRITICAL goes through AUT-6's `deliver_with_proof`, which writes its own write-once attempt record with writer `engine`. The engine runs off the node, so it calls `deliver_with_proof` directly; the node outbox (§4.6) is not involved.
- **Retry.** Each engine pass re-sends at most `ALERT_OUTBOX_MAX` transitions of today's and yesterday's chain rows that have no `delivered=true` engine record naming their `tid` (one-writer rule: no ledger file is rewritten).
- **Codes.** `AUTONOMY_TRANSITION`, `AUTONOMY_ENGINE_UNPINNED`, `AUTONOMY_POLICY_UNAVAILABLE`, `AUTONOMY_VERDICT_ERROR`, `AUTONOMY_ENGINE_LOCK_TIMEOUT`, `AUTONOMY_ENGINE_HEARTBEAT_STALE`, `AUTONOMY_HEALTH_HEARTBEAT_STALE`, `AUTONOMY_CHAIN_STALE`, `AUTONOMY_ROLLBACK_FAILED`, `AUTONOMY_TARGET_INELIGIBLE`, `AUTONOMY_DEMAND_CAPPED`, `REGISTRY_UNAVAILABLE`, `REGISTRY_REGRESSED`, `REGISTRY_HWM_RESET`, `REGISTRY_BOOT_LOAD_FAILED`, `TRADE_LAUNCH_PRECHECK_FAILED`, `TRADE_RELAUNCH_REQUEST`, `TRADE_RELAUNCH_OUTCOME`, `AUTONOMY_DRAWDOWN_INCONCLUSIVE`.
- **Tests.** `test_alert_failure_never_blocks_or_rolls_back_commit`; `test_autonomy_alert_payload_hygiene[<code>]` over every code (real constructors through the `AlertPayload` forbidden-content list, `registry/health_model.py:217-235`).

#### 3.3.9 Heartbeat

Every intraday and daily pass atomically rewrites `registry/heartbeat/<venue>.json` (0444, under `engine.lock`): `{schema:"heartbeat/v1", ts_ns, invocation_id, engine_code_sha, chain_head, venue_seq}`. The node vetoes past `ENGINE_HEARTBEAT_STALE_S` or when the named head is not on its verified chain.

#### 3.3.10 ROOT_ADMIT (V6, U2, R9.2-Z2, R9.2-Z3, errata E-2)

- **Purpose.** Recovery after the KILL or a TERMINAL event: SHADOW → CHAMPION for a committed root (a later BOOTSTRAP/MINT `∅ → SHADOW` row with its C3 root copy) carrying its **own** `_LIVE_ORDERS_ALLOWLIST` triple.
- **Writer.** Only the 16:45Z pre-launch pass, in one transaction with its ACTIVATE (SHADOW → SHADOW); effective at that day's LAUNCH; counted as one sender change.
- **Gates, all required:** the venue fold names no CHAMPION or HALTED family; lineage not `terminal_frozen`; the block's `root_admit_enabled = true` **and** `pins.ROOT_ADMIT_ENABLED_CEILING = True` (committed `False`, so ROOT_ADMIT is inert in v1); ≥ `ROOT_ADMIT_COOLDOWN_H` after the venue's latest TERMINAL event; an accepted AUT-6 `drift.fee_schedule` PASS within `ATTEST_VERDICT_VALIDITY_H`; §4.4 (16:45Z horizon); **halt-mirror fail-closed rule:** the pass first reads the exec-store halt rows itself and writes `evidence/halt_mirror/<venue>/<date>/<ts_ns>_prelaunch.json` (`halt_mirror/v1`); ROOT_ADMIT proceeds only if that record has `ts_ns` ≥ this pass's start and age ≤ `HALT_MIRROR_MAX_AGE_S` (180 s) and shows **no standing** operator halt (an uncleared `policy_halt` key with detail ≠ `fee_schedule_drift` on any family of the venue). A record absent, unreadable, older, or written before this pass started (for example around the 16:41Z reconcile; E-2) refuses.
- **d0.** A ROOT_ADMIT root is exempt from the child d0 rule (its d0 is committed; R9.2-Z1).
- Tests: `test_root_admit_only_when_venue_has_no_sender`, `test_root_admit_requires_own_allowlist_triple`, `test_root_admit_refused_after_operator_halt_within_cooldown`, `test_root_admit_refused_on_stale_halt_mirror`, `test_root_admit_inert_while_ceiling_false`.

#### 3.3.11 Rollback execution, failure and target integrity (ROLLBACK-FAILURE decision, V11, P7-3)

AUT-7 owns selection and the rules; AUT-5's engine runs AUT-7's pinned code and its store enforces the table.
- **ROLLBACK** (CHALLENGER → CHAMPION) requires the target `rollback_eligible`, never `demoted_for_cause`, not `target_integrity`-ineligible, left CHAMPION ≤ `ROLLBACK_TARGET_MAX_AGE_D` ago, `ROLLBACK_MIN_DWELL_H` met (effective instant to effective instant; it delays, never refuses), fee verified by the newest accepted `drift.fee_schedule` PASS (not node memory, G39), lineage not `terminal_frozen`, manifest and artefact shas re-verified, §4.4, rollback budget. Pending from 15:30Z, or with its ACTIVATE at 16:45Z.
- **`TARGET_INELIGIBLE`** (CHALLENGER → CHALLENGER, `cause_code=target_integrity`): a byte mismatch at selection, ACTIVATE or the first LAUNCH of a new pair. Restrictive, never capped, never counted, never cleared by an operator; nothing freezes, because the target was never loaded.
- **First LAUNCH of a new pair.** A byte-binding failure on the incoming family where its pair takes effect: the supervisor launches nothing and writes the launch event `launch_target_integrity` (§3.6); the next intraday pass (16:52:30Z) writes SWAP_CANCEL (`cause_code=target_integrity`) and TARGET_INELIGIBLE in one transaction, restoring the incumbent.
- **Failed rollback** (no eligible target, rollback budget exhausted, pair lapsed or SWAP_CANCELled): HALT on the champion if it still folds CHAMPION, `cause_code=rollback_failed`, class **`ROLLBACK_FAILED`** (non-freezing), `trigger_cause_class` = the trigger's class, CRITICAL `AUTONOMY_ROLLBACK_FAILED` through `deliver_with_proof`. No venue freeze, `terminal_frozen`, RETIRE or budget charge; never `RECOVERABLE_INFRA`. The daily or pre-launch pass retries daily; a success displaces it.
- **Champion's own bytes** are re-verified at every load. Past its first LAUNCH a mismatch makes the node refuse composition (CRITICAL `REGISTRY_BOOT_LOAD_FAILED`, launch event `registry_boot_load_failed`), and the engine's next pass writes HALT, class INTEGRITY, with the existing venue freeze.
- Tests (engine side): `test_failed_rollback_halts_champion`, `test_rollback_failed_never_freezes_venue`, `test_target_byte_mismatch_ineligible_without_freeze`, `test_target_manifest_mismatch_marks_ineligible`, `test_champion_own_artefact_mismatch_at_load_is_integrity`, `test_prelaunch_writes_rollback_and_activate_atomically`, `test_rollback_dwell_age_and_drill_headroom_ceilings`.

### 3.4 Node wiring (`src/breezy/app/trade.py`, `src/breezy/runtime/settings.py`, FQ `strategy.py`, `composition.py`, `calibration_artefact.py`)

- **`BREEZY_FAMILY_SOURCE`** ∈ {unset, `registry_shadow`, `registry`}, fixed in `deploy/systemd/breezy-trade-supervisor.service`; a scan test proves no autonomy code reads or writes it except `resolver.py` and `build_child_env` (U14; `test_family_source_fixed_in_unit`).
- **Boot (`run`, `app/trade.py:905`) with source `registry`.** `resolve_sending_family` (full replay, §3.5). Refuse boot (`EXIT_CONFIG_ERROR`) unless the resolved id equals `BREEZY_SENDING_FAMILY_ID`, `BREEZY_RESOLVED_REGISTRY_SEQ` is a verified prefix, and the fold names the family CHAMPION or HALTED (Z7). `registry` on an empty chain resolves no champion (`test_family_source_registry_requires_bootstrap`). The manifest comes from `parse_family_manifest(raw, *, origin)` (read/parse split of `load_family_manifest`, identical validation); `_validate_sending_family_manifest` (`settings.py:366`) and `_compose_family` take that object and never re-read.
- **Artefact handoff (P7-10).** The node passes the resolver's content-addressed store path `derived/artefacts/<model_class>/<sha>/artefact.json` and the row's `artefact_sha256` to `load_live_calibration` (`calibration_artefact.py:236`), whose single read (`:250`) is widened to `O_NOFOLLOW` (L-12) and still hashes and parses one buffer. A mismatch refuses composition with CRITICAL `REGISTRY_BOOT_LOAD_FAILED` and a write-once launch event `state/supervisor/launch_events/<ts_ns>_node.json` (`launch_event/v1`, `kind=registry_boot_load_failed`, family id, registry seq; no path). Test `test_node_loads_artefact_from_store_by_row_sha`; the existing calibration-artefact tests pass unmodified.
- **Y7 refusal.** Any production-registry row, or the exec-store key `autonomy/registry_hwm/<venue>`, with source ≠ `registry` while a sending family is set → `registry_source_required` (`test_hand_relaunch_without_registry_source_refused`).
- **Containment widening and G34 base fix (L-12, four sites).** `family_manifest.py:169,266-282`, `app/trade.py:122`, `settings.py:183`, `settings.py:366-388` accept `registry/families` only through `read_once_nofollow`; the `resolve()`, `..` and absolute refusals stay. Containment is checked against the directory the bytes are read from (repo `deploy/families`, or the registry root), not the phantom `deploy/families/deploy/families` base (G34), with a RED test refusing a symlinked `artefacts/` (`test_containment_checks_read_directory_not_phantom_base`).
- **Required `entry_veto` slot (W10).** `ForecastQuantileLadderStrategy.__init__` gains a keyword-only, required, non-Optional `entry_veto: Callable[[InstrumentId], VetoReason | None]` with no default. The production constructor (`fq/composition.py:246`) receives it from `_compose_forecast_quantile_ladder` (`app/trade.py:676`). `try_submit` order: permit → `entry_veto(take.instrument_id)` → `submit_veto` → `fee_verified` (`fq/strategy.py:629-645`); `submit_veto` and the exit seam untouched.
  - **Test call sites.** Five test files construct the strategy directly (`tests/strategy/forecast_quantile_ladder/test_strategy.py`, `test_sl13_wiring.py`, `test_sl13_s6_wiring.py`, `test_sl13b_tick_loop.py`, `test_d1_cache_union.py`). Each gains only `entry_veto=_never_veto` (a shared fixture returning `None`); no assertion changes.
  - **CRH kinds** carry `RefusingPlugin` and are never composed as a registry sending family; their constructors are untouched.
  - **Tests.** `test_compose_refuses_without_entry_veto_slot` (one case per composable kind in `LIVE_GATE_ROUTED_KINDS`; plus every other kind refused at compose by its `RefusingPlugin` under source `registry`), `test_entry_veto_precedes_submit_veto_in_try_submit`.
- **`RegistryWatchActor`** (composed into `extra_actors`).
  - `on_start`: `clock.set_timer("registry_watch", 60 s)`. The callback only schedules `self._tick_once()` with `asyncio.run_coroutine_threadsafe`, wrapped never to raise (L-16); an exception sets `registry_unreadable`.
  - `_tick_once` (loop thread):
    - Opens `RegistryReader` with `timeout = WATCH_BUSY_TIMEOUT_MS / 1000 = 0.25`. On `SQLITE_BUSY` the tick is **not verified** (state unchanged, `last_verified_tick_age` grows), so 3 busy ticks reach `registry_unreadable` (`WATCH_TICK_STALE_S` = 180).
    - Reads rows above its HWM, verifies the links from the stored head and re-checks the stored-head hash.
    - Replays `transitions.validate` on each new row against the in-memory fold. A widening row (PROMOTE, DRILL_PROMOTE, ROLLBACK, RESUME, ROOT_ADMIT, ACTIVATE) must also have every `cause_verdict_id` resolve under `derived/verdicts/` to a file whose sha equals the id (single read, cached per `transition_id`). A failing widening row gives `registry_unreadable` and CRITICAL `REGISTRY_REGRESSED`, and the HWM does not advance. A restrictive row (incl. TARGET_INELIGIBLE) is always applied.
    - Reads the heartbeat, every demand file under `registry/demand/<venue>/` (single read; an unparseable, oversized or symlinked file, a `family_id` not in the venue fold, a `reason` outside `DEMAND_REASONS`, or more than `DEMAND_FILES_MAX` files vetoes **every** family on the venue; U13), and today's plus yesterday's AUT-6 delivery-record directories (W13).
    - Writes `autonomy/registry_hwm/<venue>` only after a verified read, under the flock the node holds (G6). It never reads `projection` or `families`.
  - **Shadow source (P5-7).** Under `registry_shadow` the actor resolves against the shadow root, logs `entry_veto_shadow reason=…`, never refuses, and keeps its HWM in memory only, so shadow rows never arm Y7 (`test_shadow_never_vetoes_or_arms_hand_relaunch_rule`).
  - **Per-tick guard cache (W6).** `dict[base_slug, bool | GuardUnreadable]`, cleared at every tick and on each own `on_order_filled` for that slug (`test_entry_guard_cache_invalidated_on_fill`).
  - **Veto API.** `entry_veto(instrument_id) -> VetoReason | None` (loop thread, lock-free), the ARCH closed enum: `registry_not_champion`, `registry_halted`, `registry_unreadable`, `registry_regressed`, `registry_restrictive_pending`, `registry_attest_expired` (armed only by an ATTEST dated after the family's latest →CHAMPION or RESUME row; until then `registry_chain_stale` bounds it; V5), `registry_engine_heartbeat_stale`, `registry_chain_stale`, `feed_stale`, `recorder_stale`, `permit_lapsed`, `capture_gap`, `capture_untagged`, `alerts_undeliverable` (enabled only after AUT-6's first `delivered=true` canary record), `rung_net_position_held`. It returns `registry_unreadable` from construction until the first verified tick and whenever `last_verified_tick_age > WATCH_TICK_STALE_S` (Z6). `registry_halted`/`registry_not_champion` clear on the first verified tick whose fold names the family CHAMPION (W5). A reason change calls the injected `on_veto_transition(reason, cleared)`: AUT-1 wires the C1 `EntryVeto` record and AUT-6 the alert.
- **Per-kind rule.** Every kind in `LIVE_GATE_ROUTED_KINDS` passes `entry_veto` (`test_registry_champion_requires_live_orders_gate_for_every_kind` also asserts the slot is wired).

### 3.5 Same-uid threat model and full-fold replay

- **Threat model, stated.** Every Breezy process runs as one uid; such a process can rewrite the registry, the exec store, unit files and the repo. AUT-5 does **not** defend against a malicious same-uid actor. It defends against bugs, crashes, stale state, hand relaunches and accidental edits, and gives tamper evidence (per-venue chain, append-only triggers, 0444 exports with `export_seq`, the node HWM in the node-held exec store). Tamper resistance is that a forged row can only select among candidates the committed allowlists and sha-pinned rulings authorise; the node re-derives that from bytes (committed root manifest equality, byte-identical artefact, a pinned `engine_code_sha` and a pinned policy sha).
- **Resolver (every LAUNCH, relaunch and settings validation).** `replay_full` from genesis: re-runs `transitions.validate` row by row (`replay_invalid`); resolves the `cause_verdict_ids` of every PROMOTE, DRILL_PROMOTE, ROLLBACK, RESUME and ROOT_ADMIT to a verdict file whose sha equals the id, whose `kind` fits the row, and whose `subject_artefact_sha256` equals the row's binding (`replay_cause_unresolved`); checks the content-addressed artefact bytes against the binding row (`replay_artefact_mismatch`). It also applies the ARCH resolver refusals: kind outside `LIVE_GATE_ROUTED_KINDS`; a child whose `live_orders_ruling` is not the policy ruling or whose root is not in `_LINEAGE_POLICY_ALLOWLIST`; a ruling sha mismatch; broken chain or export; HWM regression; an `engine_code_sha` outside the pins; a byte-binding, §4.2 equality or d0 breach. **Root exemption (P7-1):** a root (BOOTSTRAP row, manifest bytes equal to the committed `deploy/families/<id>.json`) is authorised by its own `_LIVE_ORDERS_ALLOWLIST` triple; a ROLLBACK to `pm_us_crh_fq_v1` uses the same rule and reads its content-addressed copy (`test_root_resolves_under_live_orders_allowlist`, `test_rollback_to_root_reads_content_addressed_copy`).
- **Watch actor.** The same checks incrementally per new row (§3.4).
- **Tests.** `test_resolver_replays_validate_over_full_fold`, `test_forged_promote_without_resolvable_cause_refused`, `test_artefact_bytes_must_equal_row_sha_at_resolve`, `test_watch_actor_rejects_widening_row_failing_replay`, `test_watch_actor_applies_restrictive_row_even_if_replay_fails`.

### 3.6 Supervisor wiring (`src/breezy/runtime/trade_supervisor.py`, `src/breezy/runtime/trade_supervisor_core.py`)

- **Port.** `SupervisorPorts.resolve_registry_family`; default `resolver.resolve_sending_family` with the production roots.
- **State.** `DaySchedulerState.resolved_family_id`, `resolved_registry_seq`, `resolved_source`, `resolved_at`; pure `record_registry_resolved`.
- **`build_child_env(base, state)`** in `trade_supervisor_core.py` (P5-3, V18, U14), called at **all four** spawn sites (LAUNCH `:1289`, boot relaunch `:1379`, boot retry `:1631`, mid-day relaunch `:1977-1982`). Under source `registry` it first **drops** any inbound `BREEZY_SENDING_FAMILY_ID`, `BREEZY_RESOLVED_REGISTRY_SEQ` and `BREEZY_FAMILY_SOURCE`, then sets all three from `state` (the source pinned to the one the supervisor resolved with), and passes every other key byte-identically — including the existing `BREEZY_PERMIT_EXPIRY_CEILING_NS`, which the mid-day site keeps adding to `base` as today. Under source unset or `registry_shadow` it returns `dict(base)` (the env family is spawned unchanged). These are build-side values, never operator controls. Tests `test_child_env_touches_only_registry_keys` (AST scan for operator-control tokens), `test_child_env_drops_inbound_registry_keys`, `test_child_env_built_from_resolved_family_at_every_spawn_site` (AST).
- **STOP-completion signal (W8).** At the end of `_do_stop_prior` (`trade_supervisor.py:1131-1190`), after the SIGTERM poll loop (`:1185-1188`) or on `StopPriorAction.NOOP` (`:1155-1157`), the supervisor checks `ports.intent_lock_free(lock_path)` once more. Only if the lock is free does it write, write-once, `state/supervisor/stop_complete_<trading_day>.json` (0444, `stop_complete/v1`: `{schema, trading_day, ts_ns, outcome: "STOPPED"|"NOOP", intent_lock_free: true, supervisor_invocation_id}`; no pid, path or env) and log `stop_prior_complete day=<d> outcome=<o>`.
  - On `REFUSE_ALERT` (`:1159`), on `StopPriorRaceRefused` (`:1175`), or with the lock still held after the poll: no file, log `stop_prior_incomplete reason=<r>`.
  - A write failure logs the same line plus a CRITICAL through `deliver_with_proof` and never blocks LAUNCH: the incumbent launches as today; only a sender change is cancelled, because the post-STOP producer then emits INCONCLUSIVE.
  - New port `write_stop_complete`; `test_supervisor_unit_can_write_stop_signal_dir`.
  - Tests: `test_stop_completion_signal_written_only_when_lock_free`, `test_stop_signal_absent_on_refused_or_race`, `test_stop_signal_write_failure_never_blocks_launch`, `test_stop_signal_payload_hygiene`.
- **LAUNCH.** `_do_launch` resolves once, before the existing lock and intent checks. On `ResolverRefusal`: CRITICAL `REGISTRY_UNAVAILABLE` on the first refusal of the window, `done=False`, re-resolve each 60 s poll until 17:00Z, never a fallback; C1 marks the day `CAPTURE_INCOMPLETE(registry_unavailable)`. On success: `spawn(env=build_child_env(os.environ, state))`.
- **§4.4 re-check at LAUNCH (P5-5).** If an ACTIVATE stands for today's pair, the supervisor re-runs the read-only preconditions with the 16:45Z horizon (reusing that pass's post-STOP verdict). On failure: CRITICAL `TRADE_LAUNCH_PRECHECK_FAILED`, no spawn, `done=False`, and the journaled signal **`launch_precheck_failed`**: a log line plus a write-once `state/supervisor/launch_events/<ts_ns>_supervisor.json` (`launch_event/v1`, `kind=launch_precheck_failed`). The 16:52:30Z intraday pass writes the SWAP_CANCEL and the next re-resolve returns the incumbent. The supervisor makes **no `systemctl` call**.
- **First-LAUNCH target integrity (V11).** A resolver or load byte-binding failure on the incoming family of a pair taking effect at this LAUNCH: launch nothing, write the launch event `launch_target_integrity`, CRITICAL; the 16:52:30Z pass answers it (§3.3.11).
- **Post-launch SWAP_CANCEL (Z8).** `_do_relaunch_check` (`:1304`) re-resolves on each poll while `now < 17:00Z`. If the resolved id differs: `terminate_after_toctou_recheck`, wait for DISPOSED and lock release, `record_registry_resolved`, spawn the incumbent through `build_child_env` on the existing launch budget, log `registry_swap_voided_relaunch from=<a> to=<b>`. The restored incumbent inherits the voided child's venue-scoped OPEN or AMBIGUOUS intent (G41): it boots, refuses entries until the existing AMBIGUOUS path retires that intent, and keeps exits live (`test_incumbent_boot_survives_child_ambiguous_intent`). Preconditions gate only a change of sender, never the incumbent's own boot (`test_ambiguous_intent_cancels_swap_not_incumbent_launch`).
- **Mid-day relaunch and boot retry** reuse the LAUNCH state (Z7), so nothing swaps mid-day.
- **Self-check.** `resolve_sending_family_id()` returns `state.resolved_family_id` under source `registry`.
- **Shadow source.** The supervisor resolves against the shadow root, logs `registry_resolve_shadow agree=<bool> env=<id> resolved=<id> seq=<n>`, and spawns the env family unchanged (`test_registry_shadow_logs_agreement_and_spawns_env_family`).
- **Cut-over (V18).** Genesis BOOTSTRAP on the production root precedes enabling `registry`, in the same STOP→LAUNCH gap (WP10 L1).

### 3.7 `breezy-trade-relaunch` (`relaunch/v1`, P5-11, V18)

- **Interface.** `breezy-trade-relaunch --reason {venue_outage,node_wedged,operator_requested}`. No family or env argument.
- **Request.** A write-once `state/relaunch/request_<request_id>.json` (0600, schema **`relaunch/v1`**, exact-set `{schema, ts_ns, reason, request_id}`, `request_id` a uuid4; extra or missing keys refuse, `test_relaunch_request_schema_exact_set`). It waits up to 600 s for `response_<request_id>.json`. Exit codes: 0 `RELAUNCHED`, 3 `REFUSED`, 4 timeout, 5 `EXPIRED`.
- **Supervisor handler** (`Phase.RELAUNCH_REQUEST`, checked each 60 s poll outside [16:40Z, 17:10Z)):
  1. single-read each request and **unlink it immediately**, whatever the outcome (`test_request_unlinked_before_handling`);
  2. answer `EXPIRED` to any request with `now − ts_ns > RELAUNCH_REQUEST_TTL_S` = 120 s, two 60 s schedule polls (G40; `test_stale_request_ignored`, `test_request_ttl_covers_two_schedule_polls`);
  3. dedupe by `request_id` through write-once markers `state/relaunch/handled/<request_id>` (O_EXCL); a replayed id gets `REFUSED duplicate` and no second spawn (`test_duplicate_request_id_handled_once`).
- **Recipe (in process).** Tracked pid holds the flock → no unterminated `SubmitOrder` in the log tail → `terminate_after_toctou_recheck` → DISPOSED and lock release → `probe_open_intent` (open → REFUSED `intent_open`) → under source `registry`, re-resolve with the LAUNCH family-id rule (else REFUSED `registry_disagrees`) → `spawn_node(env=build_child_env(base, state))`, where `base` is the supervisor's environment plus the existing permit ceiling exactly as the mid-day site builds it.
- **Budget and alerts.** `RELAUNCH_REQUESTS_MAX_PER_DAY = 3`. Every request and outcome raises INFO through `deliver_with_proof`.
- **Why a request.** Nothing is copied from `/proc/<pid>/environ`, so the caps never leave the supervisor process (`test_helper_never_reads_proc_environ`).

### 3.8 Dead-man, HWM reset, verify

- **`breezy-autonomy-deadman` (owner AUT-5; P6-5).** `deploy/systemd/breezy-autonomy-deadman.{service,timer}`, `OnCalendar=*:00/30`, `Type=oneshot`, `flock -w 10` on `registry/deadman.lock`, `TimeoutStartSec=60`, `MemoryMax=128M`, `EnvironmentFile=-%h/.config/breezy/alerts.env`. Each run:
  1. reads each venue's engine heartbeat and chain-head age (single read) and raises CRITICAL `AUTONOMY_ENGINE_HEARTBEAT_STALE` past `ENGINE_HEARTBEAT_STALE_S` and `AUTONOMY_CHAIN_STALE` past H;
  2. reads AUT-6's health heartbeat `evidence/unit_health/heartbeat.json` (P6-13) and raises CRITICAL `AUTONOMY_HEALTH_HEARTBEAT_STALE` when it is older than 1800 s or unreadable;
  3. drains the node outbox through AUT-6's drain function: entries older than `ALERT_OUTBOX_STALE_S` and `claimed/*` entries whose claim time is older than `ALERT_CLAIM_STALE_S`, claimed in the **errata E-1 order** (first `os.utime` stamps the claim time on the entry, then the atomic rename into `outbox/claimed/deadman/`; the losing renamer gets ENOENT; never rename then utime), with delivery records written as writer `deadman`;
  4. the 17:00Z run reports a failed, retry-suppressed 16:45Z canary from AUT-6's records (§4.6);
  5. otherwise logs `deadman ok age_s=<n>`.
  Every CRITICAL goes through `deliver_with_proof`. AUT-6 builds no second dead-man.
- **`breezy-registry-hwm-reset --venue <v>` (Z17, W4).** Preconditions: no node holds the exec flock; it can take `engine.lock`. In order:
  1. verify the restored chain as a prefix of the export with the highest `export_seq`;
  2. compute `dropped` = rows in that export not in the restored chain; re-apply as new rows (`decided_by=operator_cli`, `mode=OPERATOR_CLI`) the restrictive effect of every dropped DEMOTE, HALT, SWAP_CANCEL and RETIRE, plus `demoted_for_cause`, `terminal_frozen`, `target_ineligible` and the INTEGRITY freeze; DEMOTE (RECOVERABLE_INFRA) any family that would otherwise fold less restrictive than in the export;
  3. **refuse** unless, per family and lineage, the post-reset fold is at least as restrictive as the export's (RETIRED > HALTED > CHALLENGER/SHADOW > CHAMPION; flag and freeze sets ⊇);
  4. append `HWM_RESET` with `hwm_from`, `hwm_to` and `carried_counters` (every per-lineage, venue and drill counter with its charge time, nomination index and `alpha_spent` included), applied as floors, so no budget is refunded;
  5. write the new export (`…_hwm<export_seq>.jsonl`);
  6. set the node HWM under the exec flock;
  7. write `evidence/registry/hwm_reset_<ts>.json` citing the replaced export's sha and the dropped `transition_id`s, then CRITICAL `REGISTRY_HWM_RESET` through `deliver_with_proof`.
  - **Tests.** `test_hwm_reset_cli_journals_alerts_and_chains`, `test_hwm_reset_cannot_unhalt`, `test_hwm_reset_never_refunds_counters`, `test_resolver_resolves_after_hwm_reset`, `test_hwm_reset_refuses_with_live_node`, `test_hwm_reset_refuses_non_prefix_chain`, `test_hwm_reset_refuses_less_restrictive_fold`, `test_hwm_reset_new_export_supersedes`.
- **`breezy-registry-verify --venue <v> [--registry-root <p>] [--at <iso>] [--rows]`.** Read-only. Prints `chain_ok`, `head`, `venue_seq`, `export_seq`, `export_prefix_ok`, `replay_ok`, `champion`, `state`, `pending`, the drill counters and `k_life` per lineage. It is the scorer's tool.

### 3.9 Policy ruling (WP3): DRAFT, values proposed here and settled by peer review

**File.** `docs/evidence/RULING_autonomy_promotion_policy_v1_<filing-date>.md`, with a byte-identical deploy copy at `deploy/families/rulings/` (pattern G4; `test_no_module_under_src_reads_docs_evidence` respected). The filing commit also sets `pins.POLICY_RULING_PIN = ("RULING_autonomy_promotion_policy_v1_<date>", "<sha256>")`, the engine's only source of policy identity in every stage; WP9's allowlist row must equal it (`test_lineage_allowlist_row_equals_policy_pin`).

**Supersessions.** It supersedes D11 for allowlisted lineages (parent ruling §3). It lifts AUD-10 PROVISIONAL only for the `OFFLINE_CHALLENGER`/`FORWARD_SHADOW` predicates it names. It cites `RULING_holdout_freeze_and_forward_window_2026-10-03` (C4.1) by name and restates no split. It never touches the caps, master enablement, the permit or NO-SEND.

**Feasibility (ARCH §4.2 Y12, V19; C4 nomination rules, ALPHA as amended).**
- σ_d = 0.132 per station-day (paired traded-rung Brier difference, `RULING_nbp_pmus_leg_infeasible_node4_2026-09-30` A-3, CI [0.127, 0.138]); MDE δ = 0.0152; power 0.80.
- n_min(α) = ((z₁₋α + z₀.₈)·σ_d/δ)². At α = 0.025 this reproduces that ruling's 592 (formula check).
- **α per nomination.** α is charged only by a SHADOW→CHALLENGER nomination, at α_k = α_total·2^−k_life with the lifetime index `k_life` that never resets (Σα ≤ α_total per lineage). α_total = 0.025, K_LIFETIME = 2 (ceiling ≤ 4) ⇒ α_1 = 0.0125 (n_min_eff 717), α_2 = α_K = 0.00625 (n_min 841, z = 2.498). The ruling states the MDE at α_K. Sensitivity of n at α_K: K_LIFETIME 1 → 717; 3 → 964; 4 → 1087; δ 0.025 → 311.
- **Window cap.** `n_cap = stations · forward_window_days · uptime_floor = 5 · 120 · 0.8 = 480`. Every nominee has `n_min_eff ≥ 717 > 480`, so each nomination is `INCONCLUSIVE(window_cap_below_n_min)` **by construction**, charges no α and no K_LIFETIME (`alpha_k = 0`, `k_life` unchanged, `nomination_feasible = false`, `infeasible_nominations` incremented), and still uses the window's one slot.
- **Qualifying rate.** ≈ 3.64 replay-sufficient station-days per day (AUT-4 r1: 80 of 80 closed station-days; **INFERRED** until AUT-4's feasibility record replaces it; 4.55 is the 5-city upper bound).
- **ETA.** From `earliest_forward_eval_start_utc` 2026-11-02: ⌈841 / 3.64⌉ = 232 days ⇒ 2027-06-22, plus the drill's **3 lost live days** per episode (V19; 6 with one retry) ⇒ **`eta_date` 2027-06-25** (2027-06-28 with a retry).
- **Bound (V19).** `promote_enabled` may be true only if `eta_date ≤ KILL − forward_window_days` = 2027-01-25 − 120 d = **2026-09-27**. Even the shortest legal window (28 d) gives 2026-12-28, still before the ETA.
- **Consequence.** `promote_enabled = false` on two independent grounds: the window cap, and `eta_date` after the bound (`test_promote_disabled_when_eta_after_kill`, `test_promote_disabled_when_n_min_exceeds_window_cap`). PROMOTE (CHALLENGER→CHAMPION) is machinery-proven by DRILL_PROMOTE only (ARCH §7); the PROMOTE code path is tested end to end with an injected policy (`test_promote_executes_when_enabled_and_evidence_met`).

**Inert in v1.** With `promote_enabled = false` and `root_admit_enabled = false`: `MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE` (30; drill rows never count, Z3), `forward_shadow.min_calendar_days` (60), `forward_shadow.n_min_station_days` (841) and `ROOT_ADMIT_COOLDOWN_H` bind no transition. Filed so that a later revision changes only the enabling flags and the feasibility record. **Live in v1:** the nomination limits (1 per window, K_LIFETIME), the mint rate, `forward_window_days` and its anchor, because the store enforces them (§3.2).

**Values and justification.**

| Key | Proposed | Ceiling (`pins`) | Justification |
|---|---|---|---|
| `alpha_total` | 0.025 | ruling | Same α as PREREG v2 and the node-4 ruling. |
| `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` (K_LIFETIME) | 2 | ≤ 4 | n at α_K is 1.42× the single-test n; K = 4 costs +29% n for no feasibility gain. |
| `MAX_NOMINATIONS_PER_FORWARD_WINDOW` | 1 | ≤ 1 | ARCH C4. |
| `MAX_MINTS_PER_LINEAGE_PER_DAY` | 1 | ≤ 1 | Across all model classes (C4). |
| `forward_window_days` | 120 | 28–120 | The largest `n_cap`; a shorter window spends nomination slots faster for no feasibility gain. |
| `forward_window_anchor_date` | `2026-10-02` | n/a | First forward day under C4.1. Windows tumble from it: [2026-10-02, 2027-01-30), … |
| `uptime_floor` | 0.8 | ruling (ARCH §8) | Gives n_cap 480, ARCH's "n_cap ≤ 480". |
| `BOOTSTRAP_B_MAX` | AUT-4's literal | `pins` literal | Draw cap with analytic tail (ALPHA 2). |
| `MIN_CALIBRATION_BUCKETS`; calibration non-inferiority margin | AUT-4's measured floor and margin | ≥ the `pins` floor | V16, P4-6; the policy may only raise the floor. |
| `MIN_GATE_DECISIONS_CHANGED` | the README X22 floor (≥ 1) | ≥ 1 | V2. |
| `MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE` (M) | 30 | ≥ 14 | Inert in v1. |
| `forward_shadow.min_calendar_days`; `forward_shadow.n_min_station_days` | 60; 841 | n/a | Inert in v1. |
| `forward_shadow.predicates` | the C4 (a)–(d) set plus `challenger_beats_champion_paired_brier` | n/a | (c) is the relative, one-sided calibration non-inferiority test (V16). The paired predicate (per independent station-day, d = Brier(champion) − Brier(challenger) on the traded rung, one-sided at the nominee's α_k) keeps a swap from trading a better-than-market champion for a worse one; AUT-4 reports `paired_brier_diff_ci_lower`. |
| `forward_shadow.accepted_assumptions` | `[]` | n/a | `slippage_champion_proxy` not accepted ⇒ INCONCLUSIVE (Y12). |
| `promote_enabled`; `root_admit_enabled` | false; false | `root_admit_enabled` ≤ `ROOT_ADMIT_ENABLED_CEILING` (committed `False`) | Feasibility above; ROOT_ADMIT only after a reviewed recovery commit (§3.11). |
| `live.drawdown.*` | §3.11 | n/a | Calibrated in WP3. |
| `attest.*` | `ATTEST_PERIOD_H` 6, `ATTEST_VERDICT_VALIDITY_H` 8, `ATTEST_MARGIN_H` 0.5, `INTRADAY_ATTEST_VERDICT_PERIOD_MIN` 60 | ≤ 6 / ≤ 8 / ≥ 0.5 / ≤ 60 | Invariant 7.54 ≤ 8 (§3.3.6). |
| `attest_required_detectors` | `HEALTH`/`liveness.permit_process`, `RECONCILIATION`/`reconciliation.net_position` | intraday producers only | Z5, P4-7. |
| `post_stop.*` | `POST_STOP_RECONCILE_RUNTIME_S` 120, `POSTSTOP_POSITIONS_MAX_PAGES` 20 | ≤ 120; ≤ 20 | Ends 16:43Z (AUT-2's unit). |
| damping | `RESUME_COOLDOWN_H` 24; `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` 2; `MAX_INFRA_RESUMES_PER_VENUE_7D` 3; `MAX_ROLLBACKS_PER_VENUE_30D` 2; `ROLLBACK_MIN_DWELL_H` 24; `ROLLBACK_TARGET_MAX_AGE_D` 30; `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` 0.5; `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` 1; `DRILL_BUDGET_PER_VENUE_30D` 1; `ROOT_ADMIT_COOLDOWN_H` 24 | ARCH §4.5 | At or stricter than the ceilings (the three P7-7 values at AUT-7's proposal; sender changes 1 ≤ 2). |
| staleness | `DEADMAN_HORIZON_H` 30; `MAX_VERDICT_VALIDITY_H` 26; `ENGINE_HEARTBEAT_STALE_S` 1800; `WATCH_TICK_STALE_S` 180; `ALERT_CANARY_MAX_AGE_H` 26; `HALT_MIRROR_MAX_AGE_S` 180; `DEMAND_FILE_MAX_BYTES` 4096; `DEMAND_FILES_MAX` 16; `DEMAND_INTEGRITY_RESERVED` 8 | ARCH §4.5 | 1800 ≤ 3600; the heartbeat is rewritten every 5 min. Reserved 8 of 16 leaves producers 8. |
| `alerting.*` (AUT-6 consumes) | `ALERT_DELIVERY_TIMEOUT_S` 10; `ALERT_OUTBOX_MAX` 256; `ALERT_OUTBOX_STALE_S` 300; `ALERT_CLAIM_STALE_S` 30; `CANARY_RETRY_PERIOD_MIN` 60; `SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY` 3 | ≤ 10 / ≤ 256 / ≤ 300 / ≥ 3×10 / ≤ 60 / ≤ 3 | At the ceilings. |

**Detector → action map and cause classes.** NODE_LOCAL vetoes stay `ENTRY_VETO` in code. Every DEMOTE/HALT row except the two drill ids is also in `pins.DEFAULT_RESTRICTIVE_CLASS`. Detector ids other than AUT-5's are proposals settled with AUT-6/AUT-2/AUT-4 in this ruling's peer review (acceptance refuses an unknown id).

| Detector id | Producer | Kind | Action | Cause class | Horizon |
|---|---|---|---|---|---|
| `freshness.persist` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_INFRA | `feed_stale`/`recorder_stale` ≥ 6 h |
| `liveness.permit_process` | AUT-6 | HEALTH | DEMOTE | RECOVERABLE_INFRA | `permit_lapsed` ≥ 2 h or liveness FAIL; hourly PASS cited by ATTEST |
| `health.capture_join` | AUT-1 | HEALTH | DEMOTE | RECOVERABLE_INFRA | `capture_gap` ≥ 1 h or join < 100% |
| `health.alert_canary` | AUT-6 | HEALTH | DEMOTE | RECOVERABLE_INFRA | canary FAIL |
| `health.label_lag` | AUT-2 | HEALTH | ALERT | RECOVERABLE_INFRA | label > 24 h after settlement |
| `health.unit` | AUT-6 | HEALTH | ALERT | RECOVERABLE_INFRA | failed autonomy or study unit |
| `health.reproducibility` | AUT-3 | HEALTH | ALERT | RECOVERABLE_MODEL | C3 rerun sha mismatch |
| `reconciliation.net_position` | AUT-2 | RECONCILIATION | DEMOTE | RECOVERABLE_INFRA | intraday :05/:35; PASS cited by ATTEST and the 15:30Z pending writes |
| `reconciliation.post_stop` | AUT-2 | RECONCILIATION | DEMOTE | RECOVERABLE_INFRA | 16:41Z, node down; PASS required at 16:45Z |
| `drift.forecast_input` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `drift.calibration_live` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `drift.fill_rate_slippage` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `parity.train_serve` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `drift.venue_shape` | AUT-6 | DRIFT | ALERT | RECOVERABLE_INFRA | the node already refuses per order |
| `drift.fee_schedule` | AUT-6 (P7-11) | DRIFT | ALERT | RECOVERABLE_INFRA | its PASS is the fee-verified input for ROLLBACK, ROOT_ADMIT and the drill start; the HALT itself comes from the exec-store mirror (`policy_halt`/`fee_schedule_drift` → TERMINAL) |
| `live.sequential` | AUT-4 | LIVE_SEQUENTIAL | HALT | RECOVERABLE_MODEL | LD-OBF boundary crossed; FQ today `INCONCLUSIVE(no_registered_boundary)`, never acts (P4-2) |
| `live.kill_clock` | AUT-4 (`evaluate_c_kill`) | LIVE_SEQUENTIAL | HALT | TERMINAL | `structural_dead` or 2027-01-25 |
| `live.drawdown` | **AUT-5 (WP11)** | **DRIFT** | HALT | TERMINAL | §3.11 |
| `DRILL_INJECT` | AUT-6 (pinned marker detector) | DRIFT | DEMOTE | DRILL | only while `drill_clause` is active; else ERROR |
| `DRILL_INJECT_HALT` | AUT-6 (same marker) | DRIFT | HALT | DRILL | only while `drill_clause` is active; else ERROR; never writes the exec store, never freezes |

`ROLLBACK_FAILED` and INTEGRITY are not detector classes: the first comes from AUT-7's failed-rollback rule, the second from the exec-store mirror and the champion's own load failure (§3.3.11).

**Drill clause.**

```json
{"drill_child_ids": ["pm_us_crh_fq_v1_r0001", "pm_us_crh_fq_v1_r0002"], "root_family_id": "pm_us_crh_fq_v1",
 "active_from_utc": "<filing+7d>", "active_until_utc": "2027-01-11", "max_episodes": 2,
 "sequence": ["MINT", "DRILL_ADMIT", "DRILL_PROMOTE+SUPERSEDE", "ACTIVATE", "DEMOTE:DRILL_INJECT", "RESUME",
              "HALT:DRILL_INJECT_HALT", "ROLLBACK+DISPLACED+ACTIVATE", "RETIRE"],
 "arm_at": "D_daily_pass", "start_min_days_after_newest_charged_drill_row": 27,
 "inject_demote_at": "D+1_daily_pass", "resume_at": "D+2_prelaunch_pass", "inject_halt_at": "D+3_daily_pass",
 "rollback_at": "D+3_prelaunch_pass", "retire_child_at": "D+4_daily_pass",
 "drill_max_episode_days": 6, "marker_registry_root": "registry"}
```

- The window (about 10-24 to 2027-01-11) covers the planning date 2026-11-19 and a retry ≥ 27 d after a first episode, and ends 2 weeks before the KILL. `max_episodes = 2` (one retry); each episode is bounded by `DRILL_BUDGET_PER_VENUE_30D` = 1 and every drill counter ≤ 1.
- A retry mints `…_r0002`: a lapsed or aborted first episode cannot reuse `r0001`, whose d0 is already pinned to its first planned effective date (§3.2 step 5).
- A missed window needs a ruling revision. **Re-pin cost:** a peer-review round, a new `POLICY_RULING_PIN` commit and a replaced (not added) `_LINEAGE_POLICY_ALLOWLIST` row, about 2 working days with the full gate after each merge.
- `drill_clause_sha256` = sha256(canonical_json(clause)), stored in the block and on every drill row.

**Machine-readable block (DRAFT; `<…>` only in this DRAFT, refused by `test_policy_block_exact_set_keys`).**

```autonomy-policy/v1
{
  "schema": "autonomy-policy/v1",
  "policy_ruling_id": "RULING_autonomy_promotion_policy_v1_<filing-date>",
  "venues": ["polymarket_us"],
  "lineage_roots": ["pm_us_crh_fq_v1"],
  "promote_enabled": false,
  "root_admit_enabled": false,
  "feasibility": {"n_min_unit": "independent_station_days", "n_min": 841, "sigma_d": 0.132,
    "mde_brier": 0.0152, "alpha_K": 0.00625, "power": 0.80,
    "qualifying_station_days_per_day": 3.64, "qualifying_rate_source": "AUT-4_r1_80_of_80_INFERRED_pending_feasibility_record",
    "stations": 5, "uptime_floor": 0.8, "n_cap": 480, "n_min_eff_by_k_life": {"1": 717, "2": 841},
    "nomination_feasible": false, "earliest_forward_eval_start_utc": "2026-11-02",
    "drill_lost_live_days": 3, "eta_date": "2027-06-25", "kill_date": "2027-01-25",
    "promote_bound_date": "2026-09-27"},
  "alpha_total": 0.025, "alpha_spending": "halving_per_nomination_lifetime_index",
  "forward_window_days": 120, "forward_window_anchor_date": "2026-10-02",
  "holdout_ruling": "RULING_holdout_freeze_and_forward_window_2026-10-03",
  "offline_challenger": {"holdout_opens_max_per_lineage": 1, "forward_days_from": "2026-10-02",
    "min_gate_decisions_changed": "<README X22 floor, >= 1>", "bootstrap_b_max": "<AUT-4 literal>"},
  "forward_shadow": {"min_calendar_days": 60, "n_min_station_days": 841,
    "predicates": ["traded_rung_brier_beats_market_baseline", "ev_net_fee_slippage_ci_lower_gt_0",
                   "traded_rung_calibration_noninferior_to_champion", "n_ge_n_min",
                   "challenger_beats_champion_paired_brier"],
    "calibration_noninferiority_margin": "<AUT-4 measured>", "min_calibration_buckets": "<AUT-4 floor>",
    "accepted_assumptions": []},
  "live": {"drawdown": {"verdict_kind": "DRIFT", "statistic": "peak_to_trough_cum_realized_pnl_over_cum_cost",
                        "scope": "lineage_real_money_fills", "limit": "<calibrated>",
                        "min_settled_real_money_fills": "<calibrated, >= 10>",
                        "h0_trip_prob_max": 0.05, "h0_horizon_end_utc": "2027-01-25",
                        "h0_seed": 20260904}},
  "attest": {"ATTEST_PERIOD_H": 6, "ATTEST_VERDICT_VALIDITY_H": 8, "ATTEST_MARGIN_H": 0.5,
             "INTRADAY_ATTEST_VERDICT_PERIOD_MIN": 60},
  "attest_required_detectors": [{"kind": "HEALTH", "detector": "liveness.permit_process"},
                                {"kind": "RECONCILIATION", "detector": "reconciliation.net_position"}],
  "post_stop": {"POST_STOP_RECONCILE_RUNTIME_S": 120, "POSTSTOP_POSITIONS_MAX_PAGES": 20},
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
    "drift.fee_schedule": {"action_class": "ALERT", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "live.sequential": {"action_class": "HALT", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "live.kill_clock": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "live.drawdown": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "DRILL_INJECT": {"action_class": "DEMOTE", "cause_class": "DRILL", "horizon_h": 0},
    "DRILL_INJECT_HALT": {"action_class": "HALT", "cause_class": "DRILL", "horizon_h": 0}},
  "damping": {"RESUME_COOLDOWN_H": 24, "MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D": 2,
    "MAX_INFRA_RESUMES_PER_VENUE_7D": 3, "MAX_ROLLBACKS_PER_VENUE_30D": 2,
    "ROLLBACK_MIN_DWELL_H": 24, "ROLLBACK_TARGET_MAX_AGE_D": 30, "DRILL_MIN_DRAWDOWN_HEADROOM_FRAC": 0.5,
    "MAX_SENDER_CHANGES_PER_VENUE_PER_DAY": 1, "MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE": 30,
    "MAX_NOMINATIONS_PER_LINEAGE_LIFETIME": 2, "MAX_NOMINATIONS_PER_FORWARD_WINDOW": 1,
    "MAX_MINTS_PER_LINEAGE_PER_DAY": 1, "DRILL_BUDGET_PER_VENUE_30D": 1, "ROOT_ADMIT_COOLDOWN_H": 24},
  "staleness": {"DEADMAN_HORIZON_H": 30, "MAX_VERDICT_VALIDITY_H": 26, "ENGINE_HEARTBEAT_STALE_S": 1800,
    "WATCH_TICK_STALE_S": 180, "ALERT_CANARY_MAX_AGE_H": 26, "HALT_MIRROR_MAX_AGE_S": 180,
    "DEMAND_FILE_MAX_BYTES": 4096, "DEMAND_FILES_MAX": 16, "DEMAND_INTEGRITY_RESERVED": 8},
  "alerting": {"ALERT_DELIVERY_TIMEOUT_S": 10, "ALERT_OUTBOX_MAX": 256, "ALERT_OUTBOX_STALE_S": 300,
    "ALERT_CLAIM_STALE_S": 30, "CANARY_RETRY_PERIOD_MIN": 60, "SELF_HEAL_MAX_RESTARTS_PER_UNIT_PER_DAY": 3},
  "drill_clause": {"drill_child_ids": ["pm_us_crh_fq_v1_r0001", "pm_us_crh_fq_v1_r0002"],
    "root_family_id": "pm_us_crh_fq_v1", "active_from_utc": "<filing+7d>", "active_until_utc": "2027-01-11",
    "max_episodes": 2,
    "sequence": ["MINT", "DRILL_ADMIT", "DRILL_PROMOTE+SUPERSEDE", "ACTIVATE", "DEMOTE:DRILL_INJECT", "RESUME",
                 "HALT:DRILL_INJECT_HALT", "ROLLBACK+DISPLACED+ACTIVATE", "RETIRE"],
    "arm_at": "D_daily_pass", "start_min_days_after_newest_charged_drill_row": 27,
    "inject_demote_at": "D+1_daily_pass", "resume_at": "D+2_prelaunch_pass", "inject_halt_at": "D+3_daily_pass",
    "rollback_at": "D+3_prelaunch_pass", "retire_child_at": "D+4_daily_pass",
    "drill_max_episode_days": 6, "marker_registry_root": "registry"},
  "drill_clause_sha256": "<sha256 of canonical drill_clause, computed at filing>"
}
```

`test_policy_block_exact_set_keys` asserts the key set, that `feasibility.n_cap == stations · forward_window_days · uptime_floor`, and that `promote_enabled` is false whenever `eta_date > promote_bound_date = kill_date − forward_window_days`.

### 3.10 Drill timeline (ARCH §5.3 P7-14, unchanged; steps AUT-7's, mechanics AUT-5's)

**Start gates at D's 15:30Z daily pass (all required):** the drill clause is active and `max_episodes` not used up; the arm instant is ≥ the newest **charged** drill row's `ts_ns` + 27 d (start rule), so a retry never strands a closing ROLLBACK in the 30 d budget; `pins.ENABLED_WIDENING_KINDS` is L2; `pm_us_crh_fq_v1` folds CHAMPION and is not `demoted_for_cause` (W2); no pending pair; no exec-store halt and no accepted non-DRILL DEMOTE/HALT FAIL standing (V12); every drill counter is 0 in the 30 d window; the newest accepted `live.drawdown` verdict is a PASS with `metrics.drawdown_used_frac ≤ 1 − DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` (an INCONCLUSIVE blocks); fee verified by the newest accepted `drift.fee_schedule` PASS within `ATTEST_VERDICT_VALIDITY_H` (P7-11); the §4.4 15:30Z horizon.

| Day / pass | Engine action | Registry rows | Counted against |
|---|---|---|---|
| D 15:30 daily | MINT `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage: cites the existing content-addressed directory; d0 = D, `trial_id_prefix` = `forecast_quantile_ladder/trial/pm_us_crh_fq_v1_r0001/`); DRILL_ADMIT; DRILL_PROMOTE + SUPERSEDE(`fq_v1`, `rollback_eligible=true`, W3), pending for D | MINT, DRILL_ADMIT, DRILL_PROMOTE + SUPERSEDE | `drill_admits`; `drill_promotes` on effect |
| D 16:45 pre-launch | §4.4 with the post-STOP PASS after today's STOP file; manifest and artefact re-verified → ACTIVATE | ACTIVATE | — |
| D 16:50 LAUNCH | resolves r0001; `drill=true` from here (C1 Z2) | (fold) | — |
| D+1 15:30 daily | writes `registry/drill/marker.json` (`drill_marker/v1`: `{schema, registry_root:"registry", venue, drill_clause_sha256, detector:"DRILL_INJECT", ts_ns}`) | — | — |
| D+1 ≈ 15:37:30 intraday | AUT-6's `*:00/5` producer → `DRILL_INJECT` FAIL; this pass → DEMOTE (class DRILL); removes the marker after commit; the watch actor vetoes `registry_halted` on its next tick (SLO ≤ 15 min) | DEMOTE (drill) | `drill_demotes` |
| D+1 16:50 LAUNCH | r0001 boots HALTED: entries vetoed `registry_halted`, exits live (Z7) | (fold) | — |
| D+2 16:45 pre-launch | RESUME (DEMOTE ts + 24 h cooldown met, `DRILL_INJECT` PASS since the marker is absent, every cause cleared, no pending pair, post-STOP PASS) | RESUME (drill) | `drill_resumes` only (W2) |
| D+3 15:30 daily | writes the marker with `detector:"DRILL_INJECT_HALT"` | — | — |
| D+3 ≈ 15:37:30 intraday | `DRILL_INJECT_HALT` FAIL → registry HALT (class DRILL; never the exec store, never a freeze); marker removed after commit | HALT (drill) | `drill_halts` |
| D+3 16:45 pre-launch | AUT-7 ROLLBACK to `fq_v1` + DISPLACED(r0001 HALTED → CHALLENGER) + ACTIVATE in one transaction; dwell from D 16:50 (and the D+2 16:45 RESUME) to D+3 16:50 = 24 h 05 min ≥ `ROLLBACK_MIN_DWELL_H` | ROLLBACK + DISPLACED + ACTIVATE | `drill_rollbacks` on effect |
| D+3 16:50 LAUNCH | restores `fq_v1` at its BOOTSTRAP-row sha from the content-addressed copy; the episode closes (`drill=false`) | (fold) | — |
| D+4 15:30 daily | RETIRE r0001 (CHALLENGER → RETIRED, policy: drill child after its episode) | RETIRE | — |

- **Clock.** ≥ 4 trading days D…D+3 (P5-8, P7-7); abort bound `drill_max_episode_days` = 6. If a step slips (for example the D+1 DEMOTE commits too late for a D+2 RESUME), each later step runs at its first eligible pass of the same kind; past the abort bound the engine stops injecting and AUT-7 closes the episode by its ROLLBACK rule.
- **Cost (V19).** `drill=true` from D 16:50 to D+3 16:50: 3 live days of n and KILL-clock evidence per episode, added to `eta_date` (§3.9).
- **Marker root-keying.** The engine writes the marker under the registry root it runs against (via `single_read` dir-descriptor `openat`). AUT-6's detector reads only under its own configured root through a verified directory descriptor (U7), refuses a marker whose `registry_root` or `drill_clause_sha256` differs, emits PASS **only** on `ENOENT` of the marker (ENOENT of the directory is ERROR), and ERROR on any other read failure, which never satisfies a RESUME (V12). So a shadow detector never trips on the production marker and the reverse (`test_shadow_detector_ignores_production_marker`, `test_production_detector_ignores_shadow_marker`, `test_drill_marker_read_error_never_resumes`).
- **Tests (AUT-5 side).** `test_drill_timeline_matches_aut7_sequence` (fake clock over the table above, incl. the start rule and the dwell), `test_drill_start_rule_27_days`, `test_drill_start_requires_drawdown_headroom_and_fee_pass`, `test_drill_halt_never_freezes_or_writes_exec_store`, `test_drill_demote_and_halt_counters_capped`, `test_drill_marker_removed_after_drill_row_commits`.

### 3.11 Drawdown producer (WP11; P5-6)

- **Ownership.** AUT-5 owns `live.drawdown`, a C4 **`DRIFT`** verdict (ARCH §5). Producer `breezy-autonomy-producer-drawdown` (`src/breezy/analysis/autonomy_producers/drawdown.py`), unit `deploy/systemd/breezy-autonomy-producer-drawdown.{service,timer}`: `OnCalendar=*-*-* 14:50:00` (after AUT-4's 14:45 live sequential, before the 15:30 daily pass), `flock -w 10` on `derived/verdicts/.drawdown.lock` (never the studies flock: a HALT producer must not wait on a study), `TimeoutStartSec=300` (ends 14:55:10Z), `MemoryMax=512M`. Pinned in `PRODUCER_SOURCE_SHA256["live.drawdown"]` and listed in `closure_manifest`. Its measured peak RSS is recorded before its timer is enabled (V14).
- **Scope and statistic.** Subject = the venue's current CHAMPION; statistic over **every real-money fill of the subject's lineage** since the lineage's BOOTSTRAP row, so neither a drill child nor a voided pair escapes it.
  - **Included C2 rows:** `admissible = true`, plus `excluded_reason ∈ {drill, voided_pair, slippage_defect, q≠1, fee_unreconciled}` (real money, W12).
  - **Excluded:** `canary` (not money), `duplicate_fill` (the same money twice), `window_incomplete` (unsettled).
  - **`unattributed`:** charged to the family the fold names sender at the fill's `ts_event` (fail-closed).
  - **Formula:** max over t of (peak cumulative realised P&L up to t − cumulative realised P&L at t) ÷ cumulative cost at t, on the labelled `realized_pnl` (net of reconciled fee).
  - **Metrics:** `statistic`, `limit`, `drawdown_used_frac = statistic / limit` (read by the drill start gate, §3.10), `included_settled_fills`.
  - **Failures:** an unknown `excluded_reason` (exact-set) or a missing `realized_pnl` on an included row → `INCONCLUSIVE` and WARNING `AUTONOMY_DRAWDOWN_INCONCLUSIVE`; with nothing to evaluate → `INCONCLUSIVE` with `metrics.day_status=NO_INPUT` (C4 invariant, U10), exit 0.
  - **Outcome:** FAIL when the statistic exceeds `limit` with ≥ `min_settled_real_money_fills` included settled fills; PASS otherwise. It never reads either operator cap.
  - **Before the ruling is filed** it writes `policy_ruling_sha256 = null` with `assumptions ∋ no_policy_ruling`, which the engine accepts only through `DEFAULT_RESTRICTIVE_CLASS` (HALT, TERMINAL).
- **Handshake with AUT-2.** `tests/unit/test_drawdown_producer.py::test_drawdown_producer_handshake_with_labels` builds its fixture parquet through AUT-2's real label writer and pinned pyarrow schema (L-42) and asserts column-for-column agreement with the producer's reader. Strict-xfail placeholder owned by AUT-2 until its writer merges (§4 ledger).
- **H0 calibration** (`scripts/analysis/autonomy_drawdown_h0.py`; deterministic seed 20260904; run by the coordinator under `MemoryMax=2G`, never inside 01:00–04:30Z, never through `uv`).
  - **Null model.** Reproduces the registered null exactly (L-41): zero edge (each fill wins with probability equal to its ask), asks drawn from the champion's empirical ask distribution on the durable-fill store, mutually exclusive rungs (L-40), venue fee θ = 0.0695.
  - **Horizon.** Stage-L1 start to 2027-01-25 at 5 fills/day.
  - **Search.** For each `min_settled_real_money_fills ∈ {10, 15, 20, 30, 50}`, the smallest `limit ∈ (0, 1.0]` on a 0.01 grid with P(trip by 2027-01-25 | H0) ≤ 0.05; the filed pair is the smallest m with a feasible limit. The limit is never vacuous (limit > 1.0, or m > the horizon's expected fill count, is refused).
  - **Tests.** `tests/unit/test_autonomy_drawdown_h0.py::test_h0_reproduces_registered_null`, `::test_h0_calibration_has_feasible_limit`, `::test_filed_drawdown_limit_meets_h0_bound` (20 000 paths), `::test_drawdown_limit_has_power_under_negative_edge` (EV −0.05 per $ cost ⇒ trip probability ≥ 0.5).
- **After a false-positive TERMINAL (Y10, V6, W15).** A TERMINAL drawdown HALT retires the champion and sets `terminal_frozen` on the lineage; the venue has **no sender**; capture, labels, refits and evaluation continue; there is no autonomous path back (Z20). Recovery is build-side, never an operator decision:
  1. an incident report under `docs/incident-reports/` shows whether the trip was a false positive;
  2. it is peer-reviewed;
  3. a reviewed change adds a new lineage root (committed manifest plus its own `_LIVE_ORDERS_ALLOWLIST` row under a new ruling: one reviewed row), revises this policy (`root_admit_enabled = true`, the new root in `lineage_roots`) and flips `pins.ROOT_ADMIT_ENABLED_CEILING`; if children of the new root are wanted, the `_LINEAGE_POLICY_ALLOWLIST` row is replaced (still one row);
  4. the new root enters at SHADOW (`∅ → SHADOW`, committed root) and is seated by **ROOT_ADMIT** at a 16:45Z pass ≥ `ROOT_ADMIT_COOLDOWN_H` after the TERMINAL event, with its gates (§3.3.10).
  - Accepted cost about 2+ working days; the H0 bound caps its probability at ≤ 0.05 over the horizon. If it fires before the drill completes, AUT-5 reports "blocked: lineage frozen" and re-runs the drill on the new root; the proof is never fudged.

### 3.12 Budget across namespaces (Z18, G21)

- **What persists.** The venue-scoped exec store `state/exec_polymarket_us.sqlite`: durable fills (`fill/<venue_order_id>`, `fill_index/<instrument_id>`, `fill_by_day/<UTC day>`; `exec/client.py:408-447`) and the venue-scoped `exec/polymarket_us/budget_exhausted/<day>` (`:399`). No key contains a family id.
- **What does not.** `DailySpendLedger` is process-local (`operator_controls.py:264-276`).
- **Inheritance.** At every node boot `_seed_spend_from_durable_fills` (`exec/client.py:2216-2275`) sums today's `cumulative_cost` over the provider's instruments **and today's day index**, de-duplicated per venue order, books it once and fails closed on a dangling index. A sender change at LAUNCH, a post-launch SWAP_CANCEL relaunch, a mid-day relaunch and a `breezy-trade-relaunch` are all new processes on the same store: each re-seeds with every fill of the UTC day, whichever family produced it, and sees the same exhaustion key. Drill fills are ordinary durable fills and spend the same budget. Autonomy code never reads, passes or computes a cap; `build_child_env` passes the supervisor's environment, where the caps already are, byte-identically.
- **Residual, stated.** The day index is the cross-family link; the tests drive fills through the real `record_fill` path (L-42), which writes both.
- **Tests (WP5).** `test_swap_cannot_exceed_daily_budget_across_namespaces` (fixture cap as in `tests/unit/test_edge2_ac6b_cross_process_fill_budget.py`, never a production assignment), `test_drill_fills_spend_venue_budget`, `test_relaunch_and_swap_cancel_inherit_spend`.

## 4. Work packages

**Gate commands for every WP, after every merge (L-43).** Exact interpreter `/home/jon/breezy/.venv/bin/python`, never `uv`/`pip` (L-51). In a worktree set `PYTHONPATH=<worktree>/src` (memory `worktree-needs-pythonpath`).
- Focused: `scripts/ci/run_tests_no_egress.sh <test paths>`.
- Full: `scripts/ci/run_tests_no_egress.sh` (includes `tests/unit/test_mypy_ratchet.py`, the mypy ratchet).
- Imports: `cd <tree root> && .venv/bin/lint-imports`, which must print "N kept, 0 broken" (`python -m importlinter` is a no-op).
- Read the exit code explicitly (memory `pytest-q-doubles-into-qq`).
- **Activation.** Immediately on merge unless a technical reason is stated in the WP (memory `activate-code-immediately`).

**Owner-RED placeholder ledger.** Envelope tests whose GREEN belongs to another area are `pytest.mark.xfail(strict=True, reason="owner AUT-n WPk")`.
- **Ledger.** `tests/unit/autonomy_owner_placeholders.py`: `OWNER_PLACEHOLDERS: Final[frozenset[tuple[str, str]]]` (node id, owner).
- **Gate test 1.** `tests/unit/test_autonomy_owner_placeholders.py::test_owner_placeholder_ledger_matches_markers` (AST scan of `tests/`): the strict-xfail markers whose reason starts `owner AUT-` equal the ledger; an owner removing one deletes its row in the same commit.
- **Gate test 2.** `::test_l2_widening_requires_empty_placeholder_ledger`: if `pins.ENABLED_WIDENING_KINDS` holds any kind beyond `{RESUME}`, the ledger must be empty.
- **Initial ledger** (all in `tests/unit/test_autonomy_cross_area.py` unless named):

| Placeholder | Owner |
|---|---|
| `::test_deliver_with_proof_reports_non_2xx_through_tee`, `::test_critical_alerts_use_delivery_proof`, `::test_detector_and_failure_mode_alerts_use_delivery_proof` | AUT-6 |
| `::test_critical_survives_sigkill`, `::test_concurrent_drainers_send_at_most_once_per_claim_window` (E-1 claim order) | AUT-6 |
| `::test_self_heal_unit_allowlist_is_literal_and_excludes_trade` | AUT-6 |
| `::test_drill_inject_passes_when_marker_absent`, `::test_drill_marker_read_error_never_resumes`, `::test_shadow_detector_ignores_production_marker`, `::test_production_detector_ignores_shadow_marker` | AUT-6 |
| `::test_fee_schedule_verdict_feeds_fee_verified_checks` | AUT-6 |
| `::test_drill_fills_excluded_from_n_and_kill_clock` | AUT-2 + AUT-4 |
| `::test_voided_pair_fills_excluded_from_all_n`, `::test_reconciliation_and_entry_guard_never_read_canary_store[reconciliation]`, `::test_post_stop_producer_inconclusive_without_stop_signal`, `::test_poststop_venue_read_is_get_only` | AUT-2 |
| `::test_window_cap_below_n_min_is_inconclusive`, `::test_infeasible_nomination_charges_no_alpha[verdict]` | AUT-4 |
| `::test_rollback_restores_byte_identical_artefact`, `::test_drill_rollback_to_superseded_incumbent_admitted`, `::test_rollback_fee_check_uses_verdict_not_node_memory` | AUT-7 |
| `tests/unit/test_drawdown_producer.py::test_drawdown_producer_handshake_with_labels` | AUT-2 |
| `tests/unit/test_registry_watch_actor.py::test_alerts_undeliverable_veto` (records through AUT-6's writer) | AUT-6 |
| `tests/unit/test_autonomy_engine.py::test_drill_timeline_matches_aut7_sequence` (needs AUT-7's step module in the closure) | AUT-7 |

### AUT-5.WP1: Foundation (ARCH Wave 0)

- **Scope.** §3.1 modules `canonical`, `single_read`, `schemas`, `transitions` (`ALLOWED` incl. ROOT_ADMIT and TARGET_INELIGIBLE, `KIND_MASK`, `WIDENING_KINDS`), `registry_store` (mask, stage flag, nomination and mint-rate limits, d0 check, `export_seq`), `fold` (`carried_counters` floors, DRILL and ROLLBACK_FAILED classes, `target_ineligible`, drill counters), `replay`, `demand` (writer with INTEGRITY slots), `pins` (empty `POLICY_RULING_PIN = ()`, `ENABLED_WIDENING_KINDS = frozenset()`, `DEFAULT_RESTRICTIVE_CLASS`, `DEMAND_WRITER_PRODUCER_IDS`, `DEMAND_REASONS`, `CAUSE_CODES`, `ROOT_ADMIT_ENABLED_CEILING = False`, every §4.5 ceiling), `closure_manifest`, `closure`, `policy` (parser), `plugin`, `entry_guard` (Protocol only), node and offline plug-in registries; the envelope scans; the placeholder ledger; `scripts/ci/regen_closure_manifest.py`.
- **Files.** New: the modules above. Tests: `tests/unit/test_registry_store.py`, `test_registry_fold.py`, `test_registry_replay.py`, `test_autonomy_pins.py`, `test_autonomy_envelope.py`, `test_autonomy_plugins.py`, `test_autonomy_owner_placeholders.py`, `test_autonomy_closure.py`, `test_autonomy_demand.py`, `test_autonomy_files_one_writer.py`. Modified: `pyproject.toml` (forbidden contract `breezy.persistence.autonomy ↛ breezy.adapters, breezy.runtime, breezy.strategy, nautilus_trader`).
- **RED first.**
  - Envelope: `tests/unit/test_autonomy_envelope.py::test_autonomy_never_reads_or_writes_operator_controls`, `::test_autonomy_never_touches_enablement_permit_or_firewall`, `::test_autonomy_never_imports_order_path`, `::test_autonomy_alert_egress_not_widened`, `::test_autonomy_payload_hygiene_scan`, `::test_family_source_read_only_by_resolver_and_child_env` (U14).
  - Store: `tests/unit/test_registry_store.py::test_registry_transition_table_is_exact`, `::test_bootstrap_seed_genesis_only`, `::test_registry_cas_and_idempotent_replay`, `::test_registry_hash_chain_and_triggers`, `::test_repeat_supersede_same_family_is_not_replay`, `::test_registry_readonly_open_engine_stopped`, `::test_family_artefact_binding_immutable`, `::test_store_enforces_kind_mask_per_mode` (e.g. `mode=DAILY` with a RESUME raises `KindRefused`), `::test_daily_refuses_widening_before_stage_flag`, `::test_nomination_columns_required_and_read_by_k_check`, `::test_nomination_refused_past_k_max_lifetime`, `::test_nomination_refused_second_in_window`, `::test_alpha_index_never_resets`, `::test_two_pending_nominees_get_distinct_k`, `::test_infeasible_nomination_charges_no_alpha` (store side: `k_life` unchanged, slot used), `::test_mint_unlimited_by_k_max_but_one_per_day`, `::test_drill_mint_not_counted`, `::test_child_d0_and_trial_prefix_pinned`, `::test_rollback_to_earlier_child_passes_d0_rule`, `::test_resume_not_subject_to_d0_rule`, `::test_root_admit_exempt_from_d0_rule`, `::test_export_seq_monotone_and_newest_wins`.
  - Fold: `tests/unit/test_registry_fold.py::test_terminal_halt_freezes_lineage`, `::test_demote_during_pending_swap_incoming`, `::test_demote_during_pending_swap_outgoing`, `::test_resume_refused_while_swap_pending`, `::test_unactivated_pair_lapses_at_launch`, `::test_post_launch_swap_cancel_voids_pair_only_before_1700`, `::test_drill_promote_refuses_non_champion_sha`, `::test_drill_refused_over_halted_incumbent`, `::test_drill_row_refused_while_non_drill_cause_stands` (V12), `::test_drill_budget_separate`, `::test_drill_admit_charges_only_drill_budget`, `::test_drill_resume_never_charges_model_budget`, `::test_drill_demote_and_halt_counters_capped`, `::test_drill_flag_spans_promote_to_rollback`, `::test_infra_cause_never_retires`, `::test_resume_requires_every_cause_cleared`, `::test_rollback_failed_never_freezes_venue`, `::test_rollback_failed_resumes_only_under_trigger_class`, `::test_target_ineligible_never_counted_or_operator_cleared`, `::test_root_admit_only_when_venue_has_no_sender`, `::test_damping_ceilings` (pins the counting rule incl. ROOT_ADMIT = 1), `::test_lapsed_pair_never_charged`, `::test_carried_counters_are_floors`.
  - Replay: `tests/unit/test_registry_replay.py::test_resolver_replays_validate_over_full_fold`, `::test_forged_promote_without_resolvable_cause_refused`, `::test_artefact_bytes_must_equal_row_sha_at_resolve`.
  - Demand: `tests/unit/test_autonomy_demand.py::test_producer_demand_flood_cannot_exhaust_integrity_slot`, `::test_producer_demand_write_is_restrictive_only`, `::test_demand_writer_refuses_unlisted_producer`, `::test_producer_demand_idempotent_on_verdict_id`.
  - One writer: `tests/unit/test_autonomy_files_one_writer.py::test_autonomy_files_have_one_writer` (AUT-5's rows of §3.2).
  - Pins and closure: `tests/unit/test_autonomy_pins.py::test_code_identity_pins_cover_import_closure`, `::test_engine_pin_history_retained`, `::test_closure_manifest_equals_grimp_closure`, `::test_rollback_dwell_age_and_drill_headroom_ceilings`, `::test_root_admit_ceiling_committed_false`, `::test_policy_map_not_looser_than_fallback_map` (skips with an explicit reason until the deploy copy exists; binding in WP3), `tests/unit/test_autonomy_closure.py::test_closure_hash_runtime_under_budget` (≤ 5 s wall, ≤ 128 MB peak RSS, no grimp in `sys.modules`).
  - Plug-ins: `tests/unit/test_autonomy_plugins.py::test_family_plugin_exact_set`.
  - Ledger: `tests/unit/test_autonomy_owner_placeholders.py::test_owner_placeholder_ledger_matches_markers`, `::test_l2_widening_requires_empty_placeholder_ledger`; plus the strict-xfail placeholders.
- **GREEN.** Every AUT-5-owned test passes and every placeholder XFAILs strictly. Mutation evidence (L-33): deleting the UPDATE trigger turns `test_registry_hash_chain_and_triggers` red; removing the `KIND_MASK` check turns `test_store_enforces_kind_mask_per_mode` red; removing the window-slot check turns `test_nomination_refused_second_in_window` red. RED→GREEN logs kept.
- **Activation.** None: library only, no runtime caller (technical reason: nothing imports it until WP2–WP5).

### AUT-5.WP2: Resolver, manifest single read, containment widening and G34 fix, `entry_guard`, `FillReader`

- **Scope.** `resolver.py` (with `replay_full`, root exemption, d0 check at the first →CHAMPION row); the `parse_family_manifest` split; the four-site L-12 widening with the G34 base fix; `entry_guard.rung_has_net_position`; `src/breezy/adapters/polymarket_us/exec/fill_reader.py`.
- **Files.** `src/breezy/persistence/family_manifest.py`, `src/breezy/runtime/settings.py`, `src/breezy/app/trade.py` (manifest load site only), the new modules. Tests: `tests/unit/test_registry_resolver.py`, `tests/unit/test_entry_guard.py`.
- **RED first.** `tests/unit/test_registry_resolver.py::test_resolver_binds_bytes_to_row`, `::test_registry_paths_refuse_symlinks`, `::test_containment_checks_read_directory_not_phantom_base` (G34), `::test_verify_and_load_share_bytes`, `::test_child_manifest_equals_committed_root_except_allowlist`, `::test_exit_gate_stays_code_only`, `::test_registry_champion_requires_live_orders_gate_for_every_kind`, `::test_resolver_refusals_give_no_champion` (parametrised over every ARCH refusal plus `replay_invalid`, `replay_cause_unresolved`, `replay_artefact_mismatch`, `d0_breach`), `::test_root_resolves_under_live_orders_allowlist`, `::test_rollback_to_root_reads_content_addressed_copy`, `::test_family_source_registry_requires_bootstrap`; `tests/unit/test_entry_guard.py::test_rung_net_position_veto_crosses_legs_and_families` (fixture via the real `record_fill`, L-42), `::test_entry_guard_exact_key_reads_only` (a recording connection sees only `key = ?` / `key IN (…)`), `::test_entry_guard_unreadable_index_vetoes`, `::test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]`, `::test_fill_reader_production_default_runs_once` (L-55).
- **GREEN.** All pass. `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_probe_containment` and every `family_manifest` test pass **unmodified**. `lint-imports` shows the new forbidden contract kept.
- **Activation.** Inert until `BREEZY_FAMILY_SOURCE` is set; the single-read manifest path is live at the next 16:50Z LAUNCH, proven byte-identical by the unchanged tests.

### AUT-5.WP3: Policy ruling DRAFT → H0 calibration → peer review → filing → `POLICY_RULING_PIN`

- **Scope.** The ruling text on §3.9; drawdown H0 calibration (§3.11) filling `limit` and `min_settled_real_money_fills`; AUT-4's literals (`BOOTSTRAP_B_MAX`, calibration margin and bucket floor, measured qualifying rate) copied from its feasibility record; peer review; filing; deploy copy; the `POLICY_RULING_PIN` commit.
- **Peer review** (dispatched by the coordinator, never the operator): `prediction-market-reviewer` (α per nomination, K_LIFETIME, n_cap and `uptime_floor`, the `eta_date` bound with drill days, the paired predicate, drawdown H0 against L-40/L-41), `trading-bot-architect` (detector map, DRILL and drill-clause sequence, 27 d start rule, ATTEST cadence, ROOT_ADMIT gating), `security-reviewer` (supersession scope, `DEFAULT_RESTRICTIVE_CLASS`, no cap or permit language). The lowest score wins; values move only inside the code ceilings.
- **Files.** New: the evidence and deploy ruling files; `scripts/analysis/autonomy_drawdown_h0.py`; tests `tests/unit/test_autonomy_policy_block.py`, `tests/unit/test_autonomy_drawdown_h0.py`. Modified: `src/breezy/persistence/autonomy/pins.py` (`POLICY_RULING_PIN` only).
- **RED first.** `tests/unit/test_autonomy_policy_block.py::test_policy_block_not_looser_than_code_ceilings`, `::test_promote_disabled_when_eta_after_kill` (the V19 bound with drill days), `::test_promote_disabled_when_n_min_exceeds_window_cap`, `::test_root_admit_enabled_not_above_ceiling`, `::test_policy_block_exact_set_keys`, `::test_policy_ruling_deploy_copy_matches_evidence`, `::test_policy_pin_matches_deploy_copy_sha`, `::test_detector_map_covers_required_classes`, `::test_drill_detectors_map_only_drill_class`, `::test_drill_clause_sha_matches_canonical_clause`, `::test_drill_window_covers_planning_date_retry_and_precedes_kill`, `::test_feasibility_n_min_reproduces_formula`, `::test_attest_constants_meet_cadence_invariant`, `::test_attest_required_detectors_are_intraday_producers`; `tests/unit/test_autonomy_drawdown_h0.py::test_h0_reproduces_registered_null`, `::test_h0_calibration_has_feasible_limit`, `::test_filed_drawdown_limit_meets_h0_bound`, `::test_drawdown_limit_has_power_under_negative_edge`. `test_policy_map_not_looser_than_fallback_map` (WP1) becomes binding.
- **GREEN.** Tests pass against the filed copy. Review records sit under `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-5-ruling-*.md`; the final lowest score is recorded in the ruling.
- **Activation.** Binding on the engine as soon as the pin commit merges, so stages S and L1 run on the filed block; WP9 reuses the same sha.

### AUT-5.WP4: Engine (modes, locks, fallback, acceptance and input journal, ATTEST, pre-launch RESUME/ROLLBACK/ROOT_ADMIT, rollback failure classes, launch events, demand archive, alerts, units)

- **Scope.** §3.3, §3.5 (engine side), §3.10 mechanics; `breezy-autonomy-engine@.service` and three timers; the pins engine row.
- **Files.** New: `src/breezy/analysis/autonomy_engine/*`; `deploy/systemd/breezy-autonomy-engine@.service`, `breezy-autonomy-engine@{daily,intraday,prelaunch}.timer`. Modified: `pyproject.toml` (console script), `deploy/systemd/README.md`, `src/breezy/persistence/autonomy/pins.py` (engine row), `closure_manifest.py`. Contingent move-only: `src/breezy/persistence/autonomy/halt_rows.py`. Tests: `tests/unit/test_autonomy_engine.py`, `tests/unit/test_autonomy_engine_promote_e2e.py`, `tests/unit/test_autonomy_units.py`, `tests/integration/test_engine_lock_slo.py`.
- **RED first.**
  - `tests/unit/test_autonomy_engine.py::test_verdict_acceptance_rules`, `::test_verdict_subject_sha_must_match_row`, `::test_verdict_accepted_after_attest`, `::test_verdict_validity_ceiling`, `::test_forward_shadow_k_life_mismatch_is_k_exceeded`, `::test_halt_reason_class_map_is_exact`, `::test_mirror_read_failure_is_integrity`, `::test_autonomy_exec_keys_disjoint_from_halt_prefixes`, `::test_intraday_engine_is_restrictive_only` (ATTEST and TARGET_INELIGIBLE allowed; PROMOTE and RESUME refused by engine and store), `::test_drill_inject_mapped_only_in_clause`, `::test_candidate_cap_and_mint_rate`, `::test_promotion_requires_reconciled_state`, `::test_pending_write_uses_intraday_reconciliation`, `::test_prelaunch_requires_post_stop_reconciliation`, `::test_activate_refused_on_stale_or_absent_stop_signal`, `::test_resume_written_only_at_prelaunch`, `::test_prelaunch_writes_rollback_and_activate_atomically`, `::test_failed_rollback_halts_champion`, `::test_target_byte_mismatch_ineligible_without_freeze`, `::test_target_manifest_mismatch_marks_ineligible`, `::test_champion_own_artefact_mismatch_at_load_is_integrity`, `::test_root_admit_requires_own_allowlist_triple`, `::test_root_admit_refused_after_operator_halt_within_cooldown`, `::test_root_admit_refused_on_stale_halt_mirror` (incl. a record written before the pass started, E-2), `::test_root_admit_inert_while_ceiling_false`, `::test_demotion_never_requires_policy_and_is_immediate`, `::test_no_policy_fail_demotes_never_widens`, `::test_engine_refuses_when_unpinned`, `::test_attest_cites_required_kinds_and_caps_validity`, `::test_attest_requires_every_listed_detector`, `::test_first_attest_after_champion_or_resume_is_cadence_exempt`, `::test_attest_cadence_has_no_expiry_gap`, `::test_every_live_verdict_journaled_once_per_daily_pass`, `::test_cause_verdict_ids_subset_of_acted_rows`, `::test_no_widening_row_without_input_journal`, `::test_demand_file_written_on_first_restrictive_failure`, `::test_retired_demand_file_archived`, `::test_rejected_producer_demand_archived_with_reason`, `::test_promote_refused_when_promote_enabled_false`, `::test_drill_start_rule_27_days`, `::test_drill_start_requires_drawdown_headroom_and_fee_pass`, `::test_drill_halt_never_freezes_or_writes_exec_store`, `::test_drill_marker_removed_after_drill_row_commits`, `::test_drill_timeline_matches_aut7_sequence` (placeholder until AUT-7's step module merges), `::test_alert_failure_never_blocks_or_rolls_back_commit`, `::test_autonomy_alert_payload_hygiene` (per code), `::test_cli_has_no_policy_override_argument`.
  - `tests/unit/test_autonomy_engine_promote_e2e.py::test_promote_executes_when_enabled_and_evidence_met`: injects a `PolicyBlock` fixture (`promote_enabled=true`, test-only sha, through the `run_daily(policy=…)` library seam the CLI never exposes) and fixture verdicts with a pinned test producer sha (accepted `OFFLINE_CHALLENGER` PASS; a feasible nomination with its columns; `FORWARD_SHADOW` PASS incl. the paired predicate; intraday RECONCILIATION PASS; post-STOP PASS after a fixture STOP file); drives MINT → nomination → CHALLENGER→CHAMPION + SUPERSEDE pending → 16:45 ACTIVATE → fold at LAUNCH naming the challenger CHAMPION, resolved under the test allowlist. Companion `::test_promote_e2e_refused_without_paired_predicate`.
  - `tests/integration/test_engine_lock_slo.py::test_restrictive_slo_met_while_daily_holds_lock` (a daily phase holds the lock for `ENGINE_LOCK_MAX_HOLD_S`; an intraday pass with an accepted FAIL commits the DEMOTE after release, or writes demand on timeout; DetectorEvent → watch veto ≤ 15 min under the fake clock), `::test_daily_lock_hold_never_exceeds_max_hold`, `::test_intraday_lock_timeout_writes_demand`, `::test_intraday_pass_yields_to_prelaunch_lock`.
  - `tests/unit/test_autonomy_units.py::test_engine_units_carry_no_operator_env_or_venue_env`, `::test_engine_timers_staggered_150s_after_producer`, `::test_two_intraday_passes_inside_launch_window`, `::test_intraday_schedule_has_two_runs_in_launch_window`, `::test_engine_runtime_bounds_match_launch_window_table` (each unit's `flock -w` and `TimeoutStartSec` equal §3.3.4), `::test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`, `::test_no_unit_overlaps_launch_window`, `::test_launch_path_units_end_before_next_fixed_point`, `::test_own_lock_autonomy_units_memory_total_le_4g`.
- **GREEN.** All pass. `test_code_identity_pins_cover_import_closure` and `test_closure_manifest_equals_grimp_closure` pass with the engine pin. The engine closure excludes `breezy.app`, `breezy.runtime.trade_supervisor*` and `breezy.adapters.*.exec.client` (asserted).
- **Activation.** Units installed at WP10 stage S against the shadow root. Technical reason for not activating on merge: Y7 makes any production-root row binding on the node, so the production root is bootstrapped only at the L1 cut-over.

### AUT-5.WP5: Node (watch actor, required `entry_veto` slot, guard cache, HWM, boot path, artefact handoff, Y7, SLO harness, spend inheritance)

- **Scope.** §3.4, §3.12 tests.
- **Files.** New: `src/breezy/strategy/autonomy/registry_watch_actor.py`. Modified: `src/breezy/strategy/forecast_quantile_ladder/strategy.py` (required keyword + one `try_submit` line), `src/breezy/strategy/forecast_quantile_ladder/composition.py` (pass-through), `src/breezy/strategy/forecast_quantile_ladder/calibration_artefact.py` (`O_NOFOLLOW` single read only), `src/breezy/app/trade.py` (`run`, `_compose_forecast_quantile_ladder`, `FillReader` injection, store-path artefact handoff, boot-load launch event), `src/breezy/runtime/settings.py`. Mechanical keyword addition in the five FQ test files of §3.4. Tests: `tests/unit/test_registry_watch_actor.py`, `tests/contract/test_watch_actor_thread_contract.py`, `tests/integration/test_demotion_latency_slo.py`, `tests/unit/test_registry_boot.py`.
- **RED first.**
  - `tests/unit/test_registry_watch_actor.py::test_watch_actor_never_reads_projection`, `::test_registry_hwm_refuses_regression`, `::test_registry_unreadable_veto_clears_only_after_verified_read`, `::test_attest_expiry_and_chain_staleness_veto_entries`, `::test_attest_veto_armed_after_first_attest`, `::test_attest_veto_rearmed_only_after_post_swap_attest`, `::test_engine_heartbeat_stale_vetoes`, `::test_entry_veto_closed_before_first_tick_and_on_stale_tick`, `::test_bad_demand_file_vetoes_venue` (incl. unknown `reason`, unknown family, over `DEMAND_FILES_MAX`), `::test_restrictive_commit_failure_sets_node_veto` (demand from WP1's writer, L-42), `::test_transient_veto_writes_no_transition`, `::test_resume_clears_registry_halted_without_relaunch`, `::test_entry_guard_cache_invalidated_on_fill`, `::test_watch_actor_busy_timeout_bounded_under_writer_lock` (a writer holds `BEGIN EXCLUSIVE`; `_tick_once` returns within 400 ms unverified; after 3 such ticks `registry_unreadable`), `::test_watch_actor_rejects_widening_row_failing_replay`, `::test_watch_actor_applies_restrictive_row_even_if_replay_fails`, `::test_shadow_never_vetoes_or_arms_hand_relaunch_rule`, `::test_alerts_undeliverable_reads_two_days`, `::test_alerts_undeliverable_veto` (placeholder, AUT-6), `::test_capture_untagged_is_a_veto_reason`, `::test_timer_callback_never_raises`.
  - `tests/contract/test_watch_actor_thread_contract.py::test_watch_actor_store_touches_stay_on_loop_thread` (with a negative control).
  - `tests/unit/test_registry_boot.py::test_hand_relaunch_without_registry_source_refused`, `::test_node_relaunch_rule_family_id_and_seq_prefix`, `::test_halted_family_boots_entries_vetoed_exits_live`, `::test_registry_unavailable_mints_no_permit`, `::test_registry_veto_leaves_exit_seam_open`, `::test_compose_refuses_without_entry_veto_slot`, `::test_entry_veto_precedes_submit_veto_in_try_submit`, `::test_node_loads_artefact_from_store_by_row_sha`, `::test_boot_load_failure_writes_launch_event`, `::test_swap_cannot_exceed_daily_budget_across_namespaces`, `::test_drill_fills_spend_venue_budget`, `::test_relaunch_and_swap_cancel_inherit_spend`.
  - `tests/integration/test_demotion_latency_slo.py::test_demotion_latency_slo` (node-local ≤ 2 min; DetectorEvent → producer stub → intraday → tick ≤ 15 min; dead engine → heartbeat veto ≤ `ENGINE_HEARTBEAT_STALE_S` + 60 s).
- **GREEN.** All pass. `test_shadow_only_false_is_only_the_gate_output`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`, `test_execution_egress_firewall_guard` and the existing `tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py` pass **unmodified**. The five FQ test files' diffs contain only the added keyword and the shared fixture import.
- **Activation.** At the next 16:50Z LAUNCH after merge. With the source unset the actor runs in a permissive no-registry mode returning only node-local reasons and `rung_net_position_held`; registry reasons stay inert until stage S sets `registry_shadow`.

### AUT-5.WP6: Supervisor (resolve at LAUNCH, `build_child_env` at four sites, STOP-completion signal, launch events, post-launch SWAP_CANCEL relaunch, §4.4 re-check, unit source)

- **Scope.** §3.6.
- **Files.** `src/breezy/runtime/trade_supervisor.py` (`_do_stop_prior`, `_do_launch`, `_do_relaunch_check`, spawns at `:1379`, `:1631`, `:1977-1982`, `resolve_sending_family_id`, `default_ports`); `src/breezy/runtime/trade_supervisor_core.py` (`build_child_env`, state); `deploy/systemd/breezy-trade-supervisor.service` (source line, branch-parked). Tests: `tests/unit/test_supervisor_registry_launch.py`, `tests/unit/test_supervisor_stop_signal.py`.
- **RED first.** `tests/unit/test_supervisor_registry_launch.py::test_family_source_fixed_in_unit`, `::test_child_env_built_from_resolved_family_at_every_spawn_site` (AST), `::test_child_env_touches_only_registry_keys`, `::test_child_env_drops_inbound_registry_keys`, `::test_child_env_identity_when_source_unset_or_shadow`, `::test_child_env_keeps_permit_ceiling_byte_identical`, `::test_registry_unavailable_retries_until_window_close_no_fallback`, `::test_launch_precheck_failed_signal_and_no_spawn`, `::test_launch_target_integrity_signal_and_no_spawn`, `::test_post_launch_swap_cancel_restores_incumbent`, `::test_incumbent_boot_survives_child_ambiguous_intent`, `::test_ambiguous_intent_cancels_swap_not_incumbent_launch`, `::test_midday_relaunch_keeps_latched_family`, `::test_self_check_keys_on_resolved_family`, `::test_registry_shadow_logs_agreement_and_spawns_env_family`; `tests/unit/test_supervisor_stop_signal.py::test_stop_completion_signal_written_only_when_lock_free`, `::test_stop_signal_absent_on_refused_or_race`, `::test_stop_signal_write_failure_never_blocks_launch`, `::test_stop_signal_payload_hygiene`, `::test_supervisor_unit_can_write_stop_signal_dir`.
- **GREEN.** All pass. `tests/unit/test_trade_supervisor.py`, `test_ct08_supervisor_contract_surface.py`, `test_trade_supervisor_core_r32.py`, `test_ct13_supervisor_crash_readopt.py` pass unmodified.
- **Activation.** A supervisor restart in 01:00–16:40Z (`KillMode=process` keeps the node; memory `supervisor-changes-need-a-supervisor-restart`). The STOP signal is live from the next 16:40Z STOP. With the source unset `build_child_env` is the identity (RED test). The source line stays on a branch (symlinked unit, memory `supervisor-unit-is-symlinked-into-the-repo`) until stage S.

### AUT-5.WP7: `breezy-trade-relaunch`

- **Scope.** §3.7.
- **Files.** New `src/breezy/runtime/trade_relaunch_cli.py`. Modified: `trade_supervisor.py` (handler), `trade_supervisor_core.py` (phase, budget, TTL), `pyproject.toml`, `deploy/systemd/README.md` (runbook replacing the hand `systemd-run` recipe). Tests: `tests/unit/test_trade_relaunch_helper.py`.
- **RED first.** `::test_helper_accepts_no_family_or_env_arguments`, `::test_relaunch_request_schema_exact_set`, `::test_request_refused_inside_launch_window`, `::test_request_refused_when_intent_open`, `::test_request_refused_when_registry_disagrees`, `::test_request_spawns_with_build_child_env_and_permit_ceiling`, `::test_request_budget_three_per_day`, `::test_helper_never_reads_proc_environ` (AST), `::test_request_outcomes_alert_through_delivery_proof`, `::test_stale_request_ignored`, `::test_request_unlinked_before_handling`, `::test_duplicate_request_id_handled_once`, `::test_request_ttl_covers_two_schedule_polls`.
- **GREEN.** All pass; the WP6 suite stays green.
- **Activation.** At the same supervisor restart as WP6.

### AUT-5.WP8: Dead-man, `breezy-registry-hwm-reset`, `breezy-registry-verify`

- **Scope.** §3.8.
- **Files.** New: `src/breezy/runtime/autonomy_deadman.py`, `registry_hwm_reset_cli.py`, `registry_verify_cli.py`; `deploy/systemd/breezy-autonomy-deadman.{service,timer}`. Modified: `pyproject.toml`. Tests: `tests/unit/test_autonomy_deadman.py`, `tests/unit/test_registry_hwm_reset.py`.
- **RED first.** `tests/unit/test_autonomy_deadman.py::test_deadman_critical_past_heartbeat_stale`, `::test_deadman_critical_past_chain_horizon`, `::test_deadman_reads_health_heartbeat_and_alerts_past_1800s`, `::test_deadman_drains_outbox_with_utime_before_rename` (E-1, through AUT-6's drain function; the order is asserted on a recording filesystem), `::test_deadman_reports_failed_1645_canary`, `::test_deadman_ok_line_when_fresh`, `::test_deadman_own_lock_not_engine_or_studies`, `::test_deadman_unit_bounds_match_launch_window_table`; `tests/unit/test_registry_hwm_reset.py::test_hwm_reset_cli_journals_alerts_and_chains`, `::test_hwm_reset_cannot_unhalt`, `::test_hwm_reset_never_refunds_counters` (incl. nomination index and drill counters), `::test_resolver_resolves_after_hwm_reset`, `::test_hwm_reset_refuses_with_live_node`, `::test_hwm_reset_refuses_non_prefix_chain`, `::test_hwm_reset_refuses_less_restrictive_fold`, `::test_hwm_reset_new_export_supersedes`.
- **GREEN.** All pass. Mutation: removing step 3 (the restrictiveness refusal) turns `test_hwm_reset_cannot_unhalt` red.
- **Activation.** The dead-man timer is enabled at stage S against the shadow root (its outbox drain is live from AUT-6's outbox merge).

### AUT-5.WP9: Lineage-policy allowlist widening (one reviewed row) and the L2 stage flag

- **Scope.** `live_orders_gate.py` gains `_LINEAGE_POLICY_ALLOWLIST: Final[frozenset[tuple[str,str,str]]]` with **exactly one row**, `("pm_us_crh_fq_v1", POLICY_RULING_PIN[0], POLICY_RULING_PIN[1])`, written as literals. A child `<root>_r\d{4}` is accepted only when its `live_orders_ruling` equals that ruling id and the root matches (existing re-hash path). Roots keep their `_LIVE_ORDERS_ALLOWLIST` triple (P7-1). No new `LiveOrdersReason` member. **Separate second commit:** `pins.ENABLED_WIDENING_KINDS = WIDENING_KINDS` (L2).
- **Files.** `src/breezy/persistence/live_orders_gate.py`; `src/breezy/persistence/autonomy/pins.py` (flag commit). Tests: `tests/unit/test_fq_live_orders_gate.py` (additions only), `tests/unit/test_lineage_policy_allowlist.py`.
- **RED first.** `tests/unit/test_lineage_policy_allowlist.py::test_lineage_policy_allowlist_is_literal_only`, `::test_lineage_policy_allowlist_has_exactly_one_row`, `::test_lineage_allowlist_row_equals_policy_pin`, `::test_child_requires_lineage_triple_and_policy_ruling`, `::test_child_with_operator_ruling_refused`, `::test_root_keeps_own_ruling`, `::test_tampered_policy_ruling_refuses_child`.
- **GREEN.** All pass. Every existing test in `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py` and `test_live_orders_ruling_deploy_copy_matches_evidence.py` passes unmodified. The flag commit is green only with an empty placeholder ledger.
- **Activation.** The allowlist row merges after L1 exit (technical reason: no child exists before then, which keeps the widening's blast radius zero in the restrictive stage). The flag commit is the L2 entry, merged before D's 15:00Z so it falls outside the drill's no-commit interval.

### AUT-5.WP10: Staged activation (shadow → live restrictive → live widening) and live proof

| Stage | Entry condition | Actions (coordinator-run; reversible) | Exit criterion |
|---|---|---|---|
| **S (shadow)** | WP1–WP8 and WP11 merged, full gate green after each; WP3 filed and `POLICY_RULING_PIN` merged; AUT-2's post-STOP unit installed | Install the engine, producer-drawdown and dead-man units with `--registry-root %h/.local/share/breezy/registry-shadow`; run `breezy-autonomy-engine@bootstrap` on the shadow root outside [16:30Z, 17:10Z); supervisor unit `BREEZY_FAMILY_SOURCE=registry_shadow` (branch-parked until the gate passes, then a restart in 01:00–16:40Z). The watch actor logs `entry_veto_shadow` and never refuses. `ENABLED_WIDENING_KINDS = ∅`. | ≥ 5 trading days, each with: ≥ 1 intraday ATTEST per 6 h on the shadow chain with no expiry gap; heartbeat age ≤ 1800 s at every dead-man run; a `stop_prior_complete` line and a `reconciliation.post_stop` verdict; zero `registry_resolve_shadow agree=false`; every `entry_veto_shadow` explained in the stage log; one shadow DEMOTE through the real producer → intraday → watch path from a shadow-root marker. |
| **L1 (live restrictive) — cut-over (V18)** | S exit met; pins commit `ENABLED_WIDENING_KINDS = {RESUME}` merged | In one STOP→LAUNCH gap: `breezy-autonomy-engine@bootstrap` against the **production** root at 16:40:05Z (`flock -w 10`, `TimeoutStartSec=60`, ends ≤ 16:41:15Z, disjoint from the 16:37:30 and 16:42:30 intraday passes on `engine.lock`); then the supervisor restart with `BREEZY_FAMILY_SOURCE=registry` once `stop_prior_complete` is logged (≤ 16:44Z; the node is down, so `KillMode` is moot); units repointed to the production root. `alerts_undeliverable` enabled after AUT-6's first `delivered=true` canary record. | ≥ 3 trading days with `registry_resolved family=pm_us_crh_fq_v1 seq=<n>` at each LAUNCH, an ATTEST every ≤ 6 h, zero unexplained vetoes, `deadman ok` every 30 min. |
| **L2 (live widening)** | L1 exit; WP9 row merged; empty placeholder ledger; WP9 flag commit merged; AUT-7 rollback selector and failed-rollback rules merged; AUT-2 intraday and post-STOP RECONCILIATION and labels live; AUT-6 `DRILL_INJECT`, `DRILL_INJECT_HALT` and `drift.fee_schedule` live; an accepted `live.drawdown` PASS with headroom | The drill clause window is active; the engine runs §3.10 with no human step. | The §6 artefacts are present. |

- **Rollback of activation.** Before any production-root row: unset the source and restart the supervisor. If the cut-over fails before 16:48Z on L1 day, the coordinator moves the production registry directory aside by rename (reversible, one-line heads-up, never a deletion), reverts the source line and restarts the supervisor before LAUNCH. After the first registry LAUNCH Y7 binds, so the reversal is `breezy-registry-hwm-reset` plus a reviewed commit, announced with a one-line heads-up. Reverting a stage flag is a reviewed pins commit and can only narrow.
- **Close step.** Update memory `hand-relaunch-mechanics` to point at `breezy-trade-relaunch`; record a lesson if any stage diverged.

### AUT-5.WP11: Drawdown producer (P5-6)

- **Scope.** §3.11 producer, unit and timer, pin row, manifest entry.
- **Files.** New: `src/breezy/analysis/autonomy_producers/{__init__,drawdown}.py`; `deploy/systemd/breezy-autonomy-producer-drawdown.{service,timer}`. Modified: `pyproject.toml`, `pins.py` (`PRODUCER_SOURCE_SHA256["live.drawdown"]`), `closure_manifest.py`. Tests: `tests/unit/test_drawdown_producer.py`.
- **RED first.** `tests/unit/test_drawdown_producer.py::test_detectors_and_drawdown_include_drill_fills` (identical P&L paths with and without the drill and voided-pair rows give different statistics; canary and duplicate rows never change it), `::test_drawdown_scope_is_lineage_since_bootstrap`, `::test_drawdown_unattributed_charged_to_sender_at_fill_time`, `::test_drawdown_unknown_excluded_reason_is_inconclusive`, `::test_drawdown_no_input_is_inconclusive_exit_0`, `::test_drawdown_fail_requires_min_fills`, `::test_drawdown_emits_used_frac`, `::test_drawdown_verdict_is_drift_kind`, `::test_drawdown_never_reads_operator_controls`, `::test_drawdown_verdict_schema_and_pins`, `::test_drawdown_producer_handshake_with_labels` (placeholder, AUT-2), `::test_producer_unit_own_lock_timeout_start_sec`.
- **GREEN.** All AUT-5-owned tests pass. A fixture verdict from it is accepted by WP4 and maps to HALT/TERMINAL.
- **Activation.** Installed at stage S (shadow root). Before AUT-2 labels exist it writes `INCONCLUSIVE` with `day_status=NO_INPUT` and exits 0.

## 5. Association

**Consumed.**

| From | Contract | What AUT-5 needs | Needed by |
|---|---|---|---|
| ARCH Rev 9.2 + errata | C1–C6, §4 | Consumed unchanged; no open contradiction (§R3) | all WPs |
| AUT-2 | C2 `label/v1` incl. `drill`, `voided_pair`, `slippage_defect`, `unattributed`; C4 `reconciliation.net_position` (:05/:35) and `reconciliation.post_stop` (its unit at 16:41Z, consuming `stop_complete/v1`, INCONCLUSIVE without it); `health.label_lag` | The label writer for the drawdown handshake | S (post-STOP unit), L1 (intraday recon for ATTEST and pending writes), L2 |
| AUT-4 | C4 `OFFLINE_CHALLENGER`, `FORWARD_SHADOW` with `k_life`, `alpha_k`, `n_min_eff`, `n_cap` and `paired_brier_diff_ci_lower`, `live.sequential`, `live.kill_clock`; `engine_input/v1` schema and contract test; feasibility record (measured rate, `BOOTSTRAP_B_MAX`, calibration margin and bucket floor) | WP3 literals | WP3, L1 |
| AUT-6 | `deliver_with_proof`; per-attempt records (two-day read); outbox drain function with the E-1 claim order; canary; intraday producer `*:00/5`; `liveness.permit_process` hourly PASS; `drift.fee_schedule` verdict; `DRILL_INJECT` and `DRILL_INJECT_HALT` detectors (directory-descriptor read, ERROR rule); health heartbeat; `aut6.intraday` INTEGRITY-floor demands through AUT-5's writer; every DRIFT/HEALTH id in §3.9 | Exact ids or a joint ruling revision | S (producer, API, heartbeat); L2 (drill detectors, fee verdict) |
| AUT-1 | C1 `EntryVeto` writer bound to `on_veto_transition(reason, cleared)`; `health.capture_join`; `capture_untagged` | Callback signature | L1 |
| AUT-3 | C3 candidates; mints under the 1-per-day ceiling (`MINT_REFUSED_CEILING`) | `lineage_root_family_id ∈ policy.lineage_roots` | none for the drill |
| AUT-7 | `engine.rollback.propose(fold)` and the failed-rollback and `TARGET_INELIGIBLE` rules inside the engine closure (pinned); the three P7-7 values; AUT-7b steps | Rollback selection | L2 |

**Provided.**

| To | Contract | Interface |
|---|---|---|
| all | C5 | `RegistryReader`, `fold`, `replay_full`, `resolve_sending_family`, `breezy-registry-verify` |
| AUT-2 | W8 | `state/supervisor/stop_complete_<trading_day>.json` (`stop_complete/v1`), written once and only with the intent lock verified free |
| AUT-1 | C5 → C1 | `fold(...).drill_episode(...)`, `ResolvedFamily.registry_seq` |
| AUT-7 | C5 write API | `RegistryStore.append(..., mode=DAILY\|PRELAUNCH\|INTRADAY)` only through the engine process and lock |
| AUT-6 | veto surface; drill marker; demand writer | `VetoReason`, `on_veto_transition`, NODE_LOCAL fixed to ENTRY_VETO; `drill_marker/v1` with `registry_root` and `detector`; `persistence/autonomy/demand.py` for `DEMAND_WRITER_PRODUCER_IDS` |
| AUT-4 | policy; nomination index | `PolicyBlock` values; nomination columns and `lineage_counters` (read-only) |

**Order and parallelism.**
- Serial: WP1 → WP2 → (WP4 ∥ WP5 ∥ WP6 ∥ WP8 ∥ WP11) → WP7 (after WP6) → S → L1 → WP9 row → WP9 flag → L2.
- WP3 runs in parallel with WP1–WP8 and must have its pin merged before S.
- `app/trade.py`, `settings.py` and `trade_supervisor*.py` belong to AUT-5 alone (ARCH §5.1; AUT-1b starts after AUT-5a merges). WP5 and WP6 touch disjoint files and run in separate worktrees, each fast-forwarded first (memory `agent-worktrees-start-stale`).

## 6. Live-proof protocol

- **Artefacts proving score 3.**
  1. `/home/jon/.local/share/breezy/evidence/registry/registry_polymarket_us_<D..D+4>.jsonl`, together holding MINT, DRILL_ADMIT, DRILL_PROMOTE + SUPERSEDE, ACTIVATE (D); DEMOTE (class DRILL, `cause_verdict_ids` naming a `DRILL_INJECT` verdict; D+1); RESUME (D+2 16:45Z pass); HALT (class DRILL, `DRILL_INJECT_HALT`; D+3); ROLLBACK + DISPLACED + ACTIVATE (D+3 16:45Z pass); RETIRE (D+4). Every row has `decided_by="engine"`, a pinned `engine_code_sha`, the pinned policy sha, the `drill_clause_sha256`, and `drill=true` where it applies.
  2. `breezy-registry-verify --venue polymarket_us` prints `chain_ok=True export_prefix_ok=True replay_ok=True`, each drill counter = 1.
  3. Node logs `/home/jon/.local/share/breezy/logs/breezy-trade-<stamp>.log`:
     - D 16:50: `registry_resolved family=pm_us_crh_fq_v1_r0001`, `boot_family id=pm_us_crh_fq_v1_r0001`, `fq_live_orders … ruling=RULING_autonomy_promotion_policy_v1_…`.
     - D+1: `entry_veto reason=registry_halted` ≤ 900 s after the `DRILL_INJECT` verdict's `produced_at_ns`; D+1 16:50 boot HALTED with entries vetoed and exits live.
     - D+2 16:50: r0001 boots CHAMPION with no registry veto (the RESUME took effect at 16:45Z while the node was down; W5's no-relaunch clear is gate-proven by `test_resume_clears_registry_halted_without_relaunch`).
     - D+3: `entry_veto reason=registry_halted` ≤ 900 s after the `DRILL_INJECT_HALT` verdict.
     - D+3 16:50: `registry_resolved family=pm_us_crh_fq_v1` with the BOOTSTRAP-row artefact sha.
  4. Supervisor log `stop_prior_complete` on D, D+2 and D+3, with the matching `stop_complete_<day>.json` files.
  5. AUT-6 delivery records `evidence/alerts/<date>/…_engine_d.json` with `delivered=true` for every `AUTONOMY_TRANSITION` of the episode.
  6. Engine input journals for every pass that wrote a drill row, each cause verdict `acted=true`.
  7. `git log --since=<D 15:00Z> --until=<D+4 17:10Z> -- deploy/ src/ docs/evidence/` is empty (no human or agent commit in the loop).
- **Where.** `docs/evidence/AUT-5_live_proof_<date>.md`, citing paths, lines and shas; scored by an independent reviewer, never self-scored.
- **ETA.**
  - Build: WP1 ≈ 7 working days (≈ 2026-10-13); WP2 + WP4–WP8 + WP11 ≈ 9 days in parallel (≈ 10-23); WP3 filing and pin ≈ 10-17.
  - Stages: S 5 trading days (≈ 10-24 to 10-30); L1 3 trading days (≈ to 11-03); drill D ≈ 11-04 to D+4 ≈ 11-08.
  - **Earliest live proof 2026-11-08.** A retry is allowed from D + 27 d (≈ 12-01, ending ≈ 12-05). Both precede the clause end 2027-01-11 and the 2027-01-25 KILL.
- **Fills.** The drill needs no fills; about 5 fills a day matter only to AUT-2/AUT-4 windows. Drill fills carry `drill=true`, spend the venue budget, feed drift and the drawdown, and never count toward any n or the KILL clock; the episode costs 3 live days of n (V19), already in `eta_date`.
- **Natural events.** A natural restrictive event also counts as DEMOTE evidence; none is required.
- **Evidence class.** **"Machinery proven, edge unproven."** `promote_enabled=false`; PROMOTE is shown live by DRILL_PROMOTE (ARCH §7) and in the gate by `test_promote_executes_when_enabled_and_evidence_met`. ROOT_ADMIT is gate-proven only (inert in v1). The TERMINAL/INTEGRITY exec-store halt paths stay gate-proven; the HALT class is proven live by `DRILL_INJECT_HALT`.

## 7. Score-3 verification checklist

| Criterion | Exact check |
|---|---|
| (a) unattended, no commit in the loop | The §6 item 7 `git log` is empty. `journalctl --user -u 'breezy-autonomy-engine@*' --since <D>` shows only timer-started runs. `breezy-registry-verify --venue polymarket_us --rows` shows `decided_by=engine` on every drill row. |
| (b) family-agnostic, cannot send without it | `scripts/ci/run_tests_no_egress.sh tests/unit/test_autonomy_plugins.py::test_family_plugin_exact_set tests/unit/test_registry_resolver.py::test_registry_champion_requires_live_orders_gate_for_every_kind tests/unit/test_registry_boot.py::test_hand_relaunch_without_registry_source_refused tests/unit/test_registry_boot.py::test_compose_refuses_without_entry_veto_slot` passes. `Environment=BREEZY_FAMILY_SOURCE=registry` is in `deploy/systemd/breezy-trade-supervisor.service`. |
| (c) fails closed | `test_registry_unavailable_mints_no_permit`, `test_entry_veto_closed_before_first_tick_and_on_stale_tick`, `test_bad_demand_file_vetoes_venue`, `test_registry_unavailable_retries_until_window_close_no_fallback`, `test_demotion_never_requires_policy_and_is_immediate`, `test_prelaunch_requires_post_stop_reconciliation`, `test_root_admit_refused_on_stale_halt_mirror`, `test_watch_actor_busy_timeout_bounded_under_writer_lock` pass. |
| (d) detected and alerted with delivery proven | Delivery records `delivered=true` for the D+1 and D+3 CRITICAL `AUTONOMY_TRANSITION`s; `test_critical_alerts_use_delivery_proof` passes with no xfail; `deadman ok` every 30 min across the episode; `test_restrictive_slo_met_while_daily_holds_lock` passes. |
| (e) RED→GREEN in the gate | RED→GREEN logs per WP in the PR bodies. `scripts/ci/run_tests_no_egress.sh` exits 0 on the merge commit. `OWNER_PLACEHOLDERS` is empty and `test_owner_placeholder_ledger_matches_markers` passes. `/usr/bin/grep -rn 'reason="owner AUT-' tests/` returns 0 lines. `.venv/bin/lint-imports` prints "0 broken". `/usr/bin/grep -rn RuntimeMaxSec deploy/systemd/breezy-autonomy-*` returns 0 lines. |
| (f) live proof | The §6 artefacts 1–6 exist. Each veto timestamp minus its verdict `produced_at_ns` is ≤ 900 s. The D+3 16:50 resolved artefact sha equals `fq_v1`'s BOOTSTRAP-row sha. |
| Envelope invariants | `git diff <pre-AUT-5>..HEAD --` on the files of `test_operator_control_assignment_scan`, `test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement` is empty. The diff of `_LIVE_ORDERS_ALLOWLIST` is empty; `_LINEAGE_POLICY_ALLOWLIST` has one row; `ROOT_ADMIT_ENABLED_CEILING` is `False`. |

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Statistical capacity** (≈ 5 fills/day; n_min 841 at α_K, n_cap 480; `eta_date` 2027-06-25 > bound 2026-09-27) | `promote_enabled=false` on two computed grounds (§3.9 tests); infeasible nominations charge no α; PROMOTE proven by the e2e test plus DRILL_PROMOTE live; evidence class stated. |
| **KILL 2027-01-25 / false-positive TERMINAL** | Drawdown H0 ≤ 0.05 by construction (§3.11). Recovery via a reviewed new root and ROOT_ADMIT, never an operator decision; "blocked: lineage frozen" is reported, never a fudged proof. Earliest proof 11-08 leaves ≈ 11 weeks; a retry fits by 12-05. |
| **Restrictive latency under contention** | Daily phase holds ≤ 15 s < intraday 20 s wait; restrictive phase first; demand files on timeout; the 16:47:30 yield is designed and tested. |
| **Policy file broken or missing** | Restrictive fallback through `DEFAULT_RESTRICTIVE_CLASS`; ATTEST lapses ⇒ node vetoes within 8 h. |
| **Launch-window overlap** | Every AUT-5 unit is in the §5.2 table or outside [16:30Z, 17:10Z) by `TimeoutStartSec` + wait; `test_no_unit_overlaps_launch_window`; the one-time L1 cut-over bootstrap is a manual firing at 16:40:05Z with its arithmetic stated (§R3 reading R-1). |
| **Memory on the 30 GiB host** | AUT-5 own-lock peak ≤ 2.14G; cross-area ≤ 4G checked by AUT-6 HEALTH; H0 calibration ≤ 2G once, outside 01:00–04:30Z; the closure hash needs no grimp (≤ 128 MB, tested); the watch actor reads only rows above its HWM. |
| **Loop-thread blocking by SQLite** | `busy_timeout` 250 ms, busy tick unverified, stale after 180 s. |
| **Shared venv** | Never `uv`/`pip`; exact interpreter in every brief (L-51); console scripts installed only by the coordinator's existing editable-install path, any reinstall flagged as a production change. |
| **Concurrent agents** | WP5 and WP6 in separate worktrees; no `git stash` (hook-blocked); per-agent scratchpads; full gate after every merge. |
| **Pin churn** | Narrow engine closure (asserted exclusions); runtime manifest regenerated by script and verified in the gate; append-only pins (Z9). |
| **Supervisor unit symlinked** | Activation lines branch-parked until the gate passes (WP6, WP10). |
| **STOP signal never written** | Fail-closed: post-STOP INCONCLUSIVE ⇒ SWAP_CANCEL, no RESUME; the incumbent launches unchanged. |
| **Post-launch SWAP_CANCEL after 16:57:30** | No incumbent relaunch that day (best-effort slot); recorded as a lost live day (V19). |
| **Rollback failure** | `ROLLBACK_FAILED` halts one family, never freezes, retries daily; a corrupt target becomes `TARGET_INELIGIBLE`, never loaded. |
| **Relaunch request abuse** | 120 s TTL, unlink-before-handle, write-once `request_id` dedupe, ≤ 3/day, outside the launch window, resolved family only. |
| **Producer demand flood** | Reserved INTEGRITY slots; producer cap; restrictive-only producer writes. |
| **Detector-id mismatch across plans** | Ids settled in the ruling's peer review; acceptance refuses an unknown id; `test_detector_map_covers_required_classes`. |
| **Same-uid tamper** | Out of scope for resistance (§3.5); tamper evidence plus selection only among authorised candidates; full replay at resolve. |
| **Drill marker cross-talk** | Root-keyed marker plus the detector's root and clause checks. |
| **Stage flag forgotten or flipped early** | The L2 flag cannot merge with a non-empty ledger; restrictive kinds are never masked. |

## 9. Binding-constraint compliance

- **Nautilus immutable:** only native extension points (`Actor`, `clock.set_timer`, the `try_submit` guard slot). Nothing is patched.
- **Operator caps:** never read, assigned, derived upward or bypassed. `test_autonomy_never_reads_or_writes_operator_controls` and the unmodified `test_operator_control_assignment_scan` pin this. The drawdown is cost-normalised from labels; `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC` is a risk value, never a cap. `build_child_env` touches only the three registry keys. Spend inheritance reuses the venue-scoped seed unchanged. The relaunch helper copies no environment.
- **`allow_short=False`:** untouched; no autonomy module writes strategy config.
- **NO-SEND:** untouched; `test_execution_egress_firewall_guard` unmodified. Autonomy egress is the `alerts.env` webhook only (`test_autonomy_alert_egress_not_widened`). The post-STOP GET-only venue read is AUT-2's reviewed dependency, not in any AUT-5 unit.
- **Master enablement and permit:** untouched (`test_autonomy_never_touches_enablement_permit_or_firewall`). The registry selects only among allowlisted families.
- **PREREG via ruling:** every threshold is in the sha-pinned block; `DEFAULT_RESTRICTIVE_CLASS` is a stricter-only code floor (`test_policy_map_not_looser_than_fallback_map`).
- **Safety tests never weakened; one reviewed row per allowlist:** `_LINEAGE_POLICY_ALLOWLIST` gets exactly one row; `_LIVE_ORDERS_ALLOWLIST` and `exit_gate` are unchanged (a post-TERMINAL root would add one reviewed row under its own ruling); the five FQ test files gain one keyword argument each.

## 10. Self-score

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 19 | Rebased on frozen Rev 9.2 (sha cited) plus errata; every §10 obligation mapped; X1–X10 deleted as resolved; all three coordinator decisions applied. |
| Correctness | 20 | 17 | Code facts re-verified by codegraph at `4b8347a6`; feasibility recomputed (n 717/841, n_cap 480, `eta_date` 2027-06-25, bound 2026-09-27). The drawdown limit is still uncalibrated; the cut-over bootstrap firing is a stated reading. |
| Specificity | 15 | 14 | Modules, masks, columns, units with waits and bounds, file schemas and the full block are given. |
| Acceptance | 20 | 17 | RED tests per WP incl. every Rev 9–9.2 test AUT-5 owns; ledger gate-tracked; upstream readiness (AUT-2, AUT-6, AUT-7) remains on the critical path. |
| Autonomy-safety | 15 | 13 | Store masks, stage flag, fallback, full replay, ROOT_ADMIT ceiling and fail-closed mirror. Same-uid residual and no-sender-after-TERMINAL remain by design. |
| Reuse | 10 | 8 | Predicates, gate, bridge, ro reader, halt readers, supervisor functions, spend seed, AUT-6 delivery and drain reused; new: store, request file, drawdown producer, closure manifest. |
| **Total** | 100 | **88** | |

## §R3 Rebase disposition (r2 on ARCH Rev 5 → r3 on FROZEN ARCH Rev 9.2, sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`, plus errata E-1 to E-4)

**40 conforming changes (R3-1 … R3-40) and 8 resolved contradictions deleted (X1, X2, X3, X5, X6, X7, X9, X10; X4 and X8 were already closed in r2).** Every conflict was resolved by conforming the plan to ARCH; no ARCH text is contested. No cap, enablement, permit, NO-SEND or `allow_short` surface changed; Nautilus is untouched.

| # | Rev 9.2 item | r2 state | r3 disposition (where) |
|---|---|---|---|
| R3-1 | Frozen basis, errata, decisions | Rev 5 sha `5d2b75fa…` | Rev 9.2 sha `1b288d0e…` and errata cited (§0); ALPHA, HOLDOUT, ROLLBACK-FAILURE decisions applied; programme rules of `PLAN_TEMPLATE.md` applied (R3-21, R3-40). |
| R3-2 | §10 AUT-5 obligations | Rev 5 text | Rev 9.2 text quoted verbatim and mapped to WPs (§1). |
| R3-3 | `DRILL_INJECT_HALT` (P6-4) | absent | Detector map, `DEFAULT_RESTRICTIVE_CLASS` exclusion, marker `detector` field, registry HALT class DRILL, never the exec store or a freeze (§3.9, §3.10; `test_drill_halt_never_freezes_or_writes_exec_store`). |
| R3-4 | Drill sequence DEMOTE→RESUME→HALT→ROLLBACK (P7-14) | D−1 … D+4 with ROLLBACK after RESUME, RESUME at D+3 daily | §3.10 rewritten to the ARCH §5.3 timeline: D pair, D+1 DEMOTE, D+2 16:45 RESUME, D+3 HALT, D+3 16:45 ROLLBACK + DISPLACED + ACTIVATE (dwell 24 h 05 min), D+4 RETIRE; `test_drill_timeline_matches_aut7_sequence`. r2's `test_drill_resume_refused_d2_admitted_d3` is withdrawn. |
| R3-5 | 27-day start rule | absent | Start gate at D 15:30 (§3.10); clause key `start_min_days_after_newest_charged_drill_row` (§3.9); `test_drill_start_rule_27_days`. |
| R3-6 | Drill counters `drill_demotes`, `drill_halts` (V15) | absent | `lineage_counters` (§3.2); `test_drill_demote_and_halt_counters_capped`. |
| R3-7 | `ROLLBACK_FAILED` class (P7-3, P7-8) | absent | `CauseClass`, `trigger_cause_class`, non-freezing HALT, daily retry, RESUME under the trigger's class (§3.1, §3.3.7, §3.3.11). |
| R3-8 | `TARGET_INELIGIBLE` (V11, P7-13) | absent | Kind, `cause_code=target_integrity`, masks, first-LAUNCH path via the 16:52:30 pass, never counted or operator-cleared (§3.2, §3.3.11, §3.6). |
| R3-9 | ROOT_ADMIT with `root_admit_enabled`, cooldown, fee PASS, halt-mirror fail-closed (V6, U2, R9.2-Z2/Z3, E-2) | absent; post-TERMINAL recovery via `∅→SHADOW` + PROMOTE | §3.3.10 (16:45Z only, with ACTIVATE, pass-own mirror record ≤ 180 s, "standing" A1 halt refuses); `ROOT_ADMIT_ENABLED_CEILING=False`; §3.11 recovery re-pointed to ROOT_ADMIT. |
| R3-10 | d0 rule tied to the first →CHAMPION row (U1, R9.2-Z1) | absent | Store step 5, resolver `d0_breach`, ROOT_ADMIT/ROLLBACK/RESUME exempt, drill child d0 = D, retry child `r0002` (§3.2, §3.9, §3.10). |
| R3-11 | Dead-man owned by AUT-5 (P6-5, P6-13) | heartbeat and chain only | Adds the AUT-6 health-heartbeat read, the outbox drain and the failed-16:45-canary report (§3.8, WP8). |
| R3-12 | `build_child_env(base, state)` (P5-3, V18, U14) | `build_child_env(base, state, *, permit_ceiling_ns)` setting the ceiling | Drops inbound registry keys then sets all three; ceiling passed byte-identically from `base`; identity when unset or shadow (§3.6); ARCH test names. |
| R3-13 | `relaunch/v1` (V18) | `relaunch_request/v1`, rewritten `handled_<date>.json` | Exact-set `relaunch/v1`; write-once dedupe markers (§3.7). |
| R3-14 | Outbox claim order (errata E-1) | n/a | The dead-man drain uses `os.utime` then rename, never the reverse (§3.8; `test_deadman_drains_outbox_with_utime_before_rename`). |
| R3-15 | Reserved INTEGRITY demand slots; restrictive writes from pinned producers (V9, U13) | engine-only demand files | `persistence/autonomy/demand.py`, naming per ARCH, `DEMAND_WRITER_PRODUCER_IDS`, `DEMAND_REASONS`, cap and reserved slots, archive with `reject_reason` (§3.1, §3.3.5, §3.4). |
| R3-16 | 15:30 pending writes vs 16:45 ACTIVATE | pending write needed yesterday's post-STOP PASS plus `reconciliation_horizon_h` | Pending writes use the newest intraday RECONCILIATION PASS within `ATTEST_VERDICT_VALIDITY_H`; key `reconciliation_horizon_h` deleted (§3.3.7, §3.9). |
| R3-17 | Post-STOP reconciliation at 16:45 only (P5-10) and pre-launch-only RESUME (P7-9) | RESUME written by the daily pass | RESUME moved to `PRELAUNCH`; `DAILY` mask has no RESUME (§3.2, §3.3.1, §3.3.7). |
| R3-18 | `eta_date ≤ KILL − forward_window_days` with drill days (V19) | ETA vs KILL only | Bound 2026-09-27; `eta_date` 2027-06-25 incl. 3 drill days (§3.9). |
| R3-19 | α per nomination (ALPHA as amended) | K_max MINTs per window, `MAX_CANDIDATES_PER_LINEAGE_PER_FORWARD_WINDOW` | Nomination limits (1 per window, K_LIFETIME = 2), lifetime `k_life`, infeasible nominations charge nothing, mint 1/day across classes, `n_cap` with `uptime_floor` (§3.2, §3.9). |
| R3-20 | Launch-window table (§5.2, V7) | intraday `flock -w 90`, daily ending 15:45, phase hold 60 s | Waits and bounds equal the table; `ENGINE_LOCK_MAX_HOLD_S` 15; the 16:47:30 yield; 16:52:30 guaranteed and 16:57:30 best-effort (§3.3.1, §3.3.4). |
| R3-21 | `TimeoutStartSec` (G32; programme rule) | carried as contradiction X9 | Every unit bounded by `TimeoutStartSec`; `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec` and `test_no_unit_overlaps_launch_window` (WP4). |
| R3-22 | C5 nomination columns (V4) | absent | DDL and store step 3 (§3.2); `test_nomination_columns_required_and_read_by_k_check`. |
| R3-23 | `FillReader` (P5-4) | `FillKeySchema` | Renamed Protocol and adapter module `fill_reader.py` (§3.1, WP2). |
| R3-24 | `DEFAULT_RESTRICTIVE_CLASS`, fallback acceptance (P4-10) | `FALLBACK_RESTRICTIVE_MAP`; nothing accepted with an empty pin | Renamed; a `no_policy_ruling` FAIL is accepted for DEMOTE/HALT only (§3.3.2); `test_fallback_accepts_nothing_when_pin_empty` replaced by `test_no_policy_fail_demotes_never_widens`. |
| R3-25 | Drawdown as C4 `DRIFT` (ARCH §5) | kind `LIVE_SEQUENTIAL` | Kind DRIFT; `drawdown_used_frac` for the drill gate; NO_INPUT INCONCLUSIVE (§3.11). |
| R3-26 | Cause classes (Z10) | `live.sequential` TERMINAL | `RECOVERABLE_MODEL`, as ARCH defines that class (§3.9). |
| R3-27 | `attest_required_detectors`, ATTEST arming (Z5, V5) | `attest_required_verdict_kinds` | `(kind, detector)` pairs; first ATTEST after →CHAMPION/RESUME exempt and arming (§3.3.6, §3.4). |
| R3-28 | Engine input journal writer (P4-9) | absent | §3.3.3; no widening row without a journal. |
| R3-29 | Post-STOP unit ownership (§10 AUT-2) | AUT-5 owned the unit pair | Moved to AUT-2; AUT-5 keeps the signal and the 16:45 requirement (§3.3.4). |
| R3-30 | One writer lock per file (V17) | appended `registry/alert_ledger/<date>.jsonl` | Dropped; retries read AUT-6's write-once records; one-writer rows listed (§3.2, §3.3.8). |
| R3-31 | `launch_precheck_failed` signal (P5-5) | log line only | Write-once `launch_event/v1` records incl. `launch_target_integrity` and the node's `registry_boot_load_failed` (§3.4, §3.6). |
| R3-32 | Artefact handoff (P7-10) | absent | Store path plus row sha into `load_live_calibration`, `O_NOFOLLOW` (§3.4, WP5). |
| R3-33 | G34 base fix | absent | Containment against the read directory (§3.4, WP2). |
| R3-34 | Cut-over (V18) | bootstrap "before the next LAUNCH" | Bootstrap and source flip in one STOP→LAUNCH gap (WP10 L1). |
| R3-35 | §4.5 ceilings added in Rev 6–9.2 | missing keys | Block gains `ROLLBACK_MIN_DWELL_H`, `ROLLBACK_TARGET_MAX_AGE_D`, `DRILL_MIN_DRAWDOWN_HEADROOM_FRAC`, `ROOT_ADMIT_COOLDOWN_H`, `HALT_MIRROR_MAX_AGE_S`, `DEMAND_INTEGRITY_RESERVED`, `ALERT_OUTBOX_STALE_S`, `ALERT_CLAIM_STALE_S`, `POSTSTOP_POSITIONS_MAX_PAGES`, `uptime_floor`, `BOOTSTRAP_B_MAX`, `MIN_CALIBRATION_BUCKETS`, `MIN_GATE_DECISIONS_CHANGED` (§3.9). |
| R3-36 | Qualifying rate (P4-3) | 4.55 upper bound | 3.64 measured (INFERRED), 4.55 kept as the bound (§3.9). |
| R3-37 | Detector ids (C6, P7-11) | `drill.inject`; `drift.fee_schedule` as mirror | `DRILL_INJECT`, `DRILL_INJECT_HALT`; `drift.fee_schedule` is AUT-6's verdict feeding the fee checks, the HALT stays the mirror's (§3.9). |
| R3-38 | Drill clause shape | `max_episodes` 1, single child | `max_episodes` 2 under the 27 d rule, two child ids, `drill_max_episode_days` (§3.9). |
| R3-39 | Live-proof evidence | D+3 "veto cleared without relaunch" | RESUME now lands at 16:45 with the node down; W5 is gate-proven; the D+1 HALTED boot (Z7) and both drill vetoes are the live evidence (§6). |
| R3-40 | Test names and paths | Rev 5 names; `~/` paths | ARCH test names adopted (`test_bootstrap_seed_genesis_only`, `test_root_resolves_under_live_orders_allowlist`, `test_drawdown_producer_handshake_with_labels`, `test_child_env_touches_only_registry_keys`, …); placeholder ledger updated; all paths absolute or repo-root-relative (§0). |

**Resolved contradictions, deleted from the plan.**

| r2 id | Resolved by Rev 9.2 | Plan now |
|---|---|---|
| X1 (root vs policy-ruling refusal) | C5 root exemption (P7-1) | §3.5 |
| X2 (BOOTSTRAP genesis rows) | C5 table `∅→CHAMPION`, `∅→RETIRED` (P5-2) | §3.2 |
| X3 (env at four spawn sites) | G22 and the Env handoff (P5-3) | §3.6 |
| X5 (no `systemctl` from the supervisor) | §4.4 two-pass rule (P5-5, V7) | §3.3.4, §3.6 |
| X6 (drawdown producer owner) | ARCH §5 AUT-5 writes C4 `DRIFT` (drawdown) (P5-6) | §3.11 |
| X7 (shadow source and root) | C5 shadow stage (P5-7) | §3.4, §3.6, WP10 |
| X9 (`RuntimeMaxSec` on oneshot) | G32, §5.2 | R3-21 |
| X10 (pending write before STOP) | §4.4 P5-10, conformed the ARCH way (R3-16): the post-STOP PASS is required only at 16:45 | §3.3.7 |

**Readings where ARCH is silent (not contradictions; flagged for the reviewer).**
- **R-1.** The one-time L1 cut-over bootstrap (V18 requires the STOP→LAUNCH gap) is a manual firing at 16:40:05Z, ending ≤ 16:41:15Z, disjoint from both neighbouring intraday passes on `engine.lock`; it has no timer, so `test_no_unit_overlaps_launch_window` is unaffected. If the reviewers read §5.2 as covering manual firings, this is the only item needing an ARCH errata row.
- **R-2.** `INTRADAY` includes TARGET_INELIGIBLE: C5's latency text lists DEMOTE, HALT, SWAP_CANCEL and ATTEST, while V11 has the next intraday pass write TARGET_INELIGIBLE; it is restrictive, so the restrictive-only rule holds.
- **R-3.** The ROOT_ADMIT halt-mirror record is the pre-launch pass's own write-once record, so only that pass's read qualifies (E-2, `HALT_MIRROR_MAX_AGE_S` = 180).
- **R-4.** `live.drawdown` is mapped TERMINAL by this ruling's choice (ARCH leaves the class to the policy); the H0 bound limits a false trip to ≤ 0.05.

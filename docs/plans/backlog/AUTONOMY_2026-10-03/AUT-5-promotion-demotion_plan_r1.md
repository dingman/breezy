# AUT-5 — Automated promotion and demotion: registry, policy engine, pre-registered policy ruling (plan r1)

## 0. Header

| Field | Value |
|---|---|
| ID | AUT-5 |
| Title | Automated promotion and demotion (C5 registry, engine, `RegistryWatchActor`, policy ruling) |
| Round | r1 (2026-10-03) |
| ARCH consumed | `AUTONOMY_ARCHITECTURE.md` **Rev 4**, frozen copy `…/scratchpad/ARCH_rev4.md`, sha256 `175310117eec39b22fc8229788a7d6182c6395438db23ec65ceb78b964dd508e`; code facts checked at repo `4b8347a6` |
| Current score | 1 (README "Current scores") |
| Target | 3 |
| Upstream | AUT-2 (C2, C4 `RECONCILIATION`), AUT-4 (C4 `OFFLINE_CHALLENGER`, `FORWARD_SHADOW`, `LIVE_SEQUENTIAL`, feasibility record), AUT-6 (C4 `DRIFT`/`HEALTH`, intraday producer, `deliver_with_proof`, canary journal, `DRILL_INJECT` detector), AUT-1 (C1 `EntryVeto` writer, `HEALTH`), AUT-3 (C3 candidates) |
| Downstream | AUT-7 (co-writes C5 through the engine API; AUT-7b drill is this area's live proof), AUT-1 (reads `registry_seq` and `drill` from the fold for C1), AUT-6 (consumes the veto/alert surface) |
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

**ARCH §10 AUT-5 obligations (verbatim).**
> the policy ruling and its `autonomy-policy/v1` block (every key, every value within ceilings, drill clause and window, `attest_required_verdict_kinds`, detector cause classes); the engine's daily, intraday (restrictive-only, heartbeat) and pre-launch modes, staggered timers and lock; ATTEST cadence; the watch actor (loop-thread bridge) and `entry_guard` wiring per kind; HWM key handling and the `breezy-registry-hwm-reset` CLI; the demand directory; supervisor env handoff, the relaunch rule, the post-launch SWAP_CANCEL relaunch and the registry-aware `breezy-trade-relaunch` helper replacing the hand `systemd-run` runbook; the dead-man; bootstrap; the 15 min SLO test harness.

Obligation → WP map: policy ruling and block → WP3; engine modes, timers, lock, ATTEST, demand directory, bootstrap → WP4; watch actor, loop-thread bridge, `entry_guard` wiring, HWM key → WP2 + WP5; supervisor env handoff, relaunch rule, post-launch SWAP_CANCEL relaunch → WP6; `breezy-trade-relaunch` → WP7; dead-man, `breezy-registry-hwm-reset` → WP8; lineage allowlist widening → WP9; 15 min SLO harness → WP5 (`test_demotion_latency_slo`); staged activation and live proof → WP10.

## 2. L-1 null hypothesis and reuse

| New component | Nautilus / existing Breezy capability checked | Verdict |
|---|---|---|
| C5 registry (store, chain, fold) | Nautilus: no artefact registry, champion/challenger state or promotion engine (ARCH §2 L-1; `WORK_BREAKDOWN:288`). Breezy: `SqliteStateStore` (`runtime/sqlite_store.py:117-176`) is a thread-confined KV with WAL and no iteration (G7); the exec store's flock is node-held (G6). `FamilyManifest` exact-set shape (`family_manifest.py:122-137`). | **Build**, as ARCH C5 mandates: a separate SQLite file in `journal_mode=DELETE`. Reuse the exact-set and raw-byte-sha conventions of `load_family_manifest` (`family_manifest.py:285-296`), and the `mode=ro` URI reader pattern (`trial_day_latch.py:354-379`). |
| Policy engine | `promotion_criteria.py` already holds `evaluate_c_kill` (`:195-281`), `evaluate_c_n` (`:486-497`), `evaluate_c_estimator` (`:526-556`) and `assemble_outcome` (`:613-637`). The proposal generator is advisory only (G14). | **Build the engine; reuse the predicates.** The engine never recomputes statistics. It consumes C4 verdicts whose producers (AUT-4) call these predicates. `C-KILL` stays the producer of the `live.kill_clock` verdict, routed through AUT-4. |
| Promotion authorisation without a commit per promotion | `live_orders_authorized` with a literal 3-tuple allowlist plus a ruling sha re-hash (`live_orders_gate.py:76-84,130-189`). | **Extend.** One reviewed widening adds `_LINEAGE_POLICY_ALLOWLIST` beside `_LIVE_ORDERS_ALLOWLIST` (WP9). The re-hash code path is reused unchanged. |
| Entry-only demotion | Nautilus `TradingState.REDUCING` (`risk/engine.pyx:1150-1163`) denies a BUY only when the instrument is net long, and it is node-global (ARCH §2). FQ `try_submit` already has a guard chain (`fq/strategy.py:629-645`): permit, `submit_veto`, `fee_verified`. | **Extend the native guard slot.** Add a separate `entry_veto` slot to `try_submit`. `submit_veto` is not reused, because it also reaches the exec client (G23). |
| In-node registry watch | `FeeDriftProbeActor` timer → `asyncio.run_coroutine_threadsafe` bridge (`fee_drift_probe.py:358-372`); `LiveClock` callbacks run on `_DummyThread` (`tests/contract/test_live_timer_thread_affinity.py:90-119`). | **Reuse the pattern.** `RegistryWatchActor` copies the bridge shape and adds no new threading primitive. |
| Rung net-position guard | Nautilus `Portfolio.net_position(instrument_id)` is account-wide, but after a restart it depends on the venue position-report translation (a NO holding nets as short YES, L-44), which is unverified for composite leg ids. The exec store keeps `FILL_INDEX_KEY_PREFIX` per instrument (`exec/client.py:410`) plus durable fill records (`:406`). | **Reuse the durable fills**, as the ARCH contract specifies. The reader lives in `adapters/` (layer contract, §3.4) and is injected. The Nautilus portfolio is rejected as the sole source until an L-1 probe proves its leg netting. |
| Supervisor pickup | `_do_launch` (`trade_supervisor.py:1209-1300`) and three relaunch spawns (`:1379`, `:1631`, `:1982`) all forward `os.environ` or `dict(os.environ)` as-is. `resolve_sending_family_id` reads `os.environ` (`:514-524`). | **Extend.** Add one pure `build_child_env` used at all four spawn sites, and a resolver port. No new scheduler: the phases stay those of `trade_supervisor_core.py:37-59`. |
| Relaunch helper | Hand runbook (memory note `hand-relaunch-mechanics`, 10-02 recipe). It already imports `probe_open_intent`, `spawn_node`, `terminate_after_toctou_recheck` and `node_log_path`, and copies `/proc/<pid>/environ` by hand. | **Replace with a supervisor-executed request** (§3.7). Reuse the same supervisor functions inside the supervisor process, so no environment is ever copied out of `/proc`. |
| Halt mirror | `read_family_halt_rows_readonly` and `decode_family_halt_state` (`trial_day_latch.py:354`, G20). | **Reuse read-only.** If the engine's import closure (pins, §4.3) pulls in `breezy.strategy.*` beyond `trial_day_latch`'s decode, WP4 first does a move-only extraction of the two functions into `persistence/autonomy/halt_rows.py`, re-exported from `trial_day_latch` with no behaviour change. |
| Alert delivery | `deliver_with_proof` is AUT-6's API (`runtime/alert_delivery.py`, ARCH §4.6). | **Consume.** AUT-5 never writes its own sink. |
| Operator halt tools | `breezy-set-family-halt` / `breezy-clear-family-halt` (`set_family_halt_cli.py`, `clear_family_halt_cli.py`). | **Unchanged.** The engine mirrors them read-only (TERMINAL for `policy_halt`, INTEGRITY for `duplicate_fill`/`ambiguous_exit`). |

## 3. Design

### 3.1 Package layout and layers

Layer rule (`pyproject.toml:74-101`): `app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain`. Live packages never import `breezy.analysis` (`:128-151`).

| Module | Layer | Contents |
|---|---|---|
| `src/breezy/persistence/autonomy/__init__.py` | persistence | Public names only. |
| `…/autonomy/canonical.py` | persistence | `canonical_json(obj) -> bytes` (sorted keys, no NaN, explicit serialisers, never `dataclasses.asdict`); `sha256_hex(b)`. |
| `…/autonomy/single_read.py` | persistence | `read_once_nofollow(path: Path, *, root: Path, max_bytes: int) -> bytes`: `lstat` walk from `root` refusing any symlink component, `os.open(O_RDONLY\|O_NOFOLLOW)`, one `read`, size cap. Raises `SingleReadRefused(reason)`. |
| `…/autonomy/schemas.py` | persistence | Frozen dataclasses and enums: `State` (SHADOW, CHALLENGER, CHAMPION, HALTED, RETIRED); `Kind` (BOOTSTRAP, MINT, PROMOTE, DRILL_ADMIT, DRILL_PROMOTE, ROLLBACK, SUPERSEDE, DISPLACED, ACTIVATE, SWAP_CANCEL, ATTEST, DEMOTE, HALT, RESUME, RETIRE, HWM_RESET); `CauseClass` (RECOVERABLE_MODEL, RECOVERABLE_INFRA, TERMINAL, INTEGRITY); `TransitionRow` (every C5 column); `Verdict` (verdict/v1 reader, exact-set); `DemandRecord` (demand/v1); `Heartbeat` (heartbeat/v1); `ResolvedFamily`. |
| `…/autonomy/transitions.py` | persistence | `ALLOWED: Final[frozenset[tuple[State\|None, State, Kind]]]`, the literal ARCH C5 table plus the bootstrap rows (§3.2, contradiction X2); `validate(fold, row) -> None \| RefusalReason`. |
| `…/autonomy/registry_store.py` | persistence | `RegistryStore` (rw; engine and operator CLIs only) and `RegistryReader` (`file:…?mode=ro` URI). DDL, triggers, CAS write, chain verify, export writer, cache refold. |
| `…/autonomy/fold.py` | persistence | `fold(rows, venue, now_ns) -> FoldResult`: pure. States, pending pairs, lapse at LAUNCH without ACTIVATE, post-launch SWAP_CANCEL voiding in [16:50Z, 17:00Z), counters charged on effect, `drill_episode(family, ts_ns) -> bool`, `rollback_eligible`, `demoted_for_cause`, `terminal_frozen`, INTEGRITY freeze. |
| `…/autonomy/resolver.py` | persistence | `resolve_sending_family(*, venue, now_ns, registry_root, repo_root, hwm) -> ResolvedFamily \| ResolverRefusal` (ARCH C5 pickup 1). The only reader of `BREEZY_FAMILY_SOURCE`. |
| `…/autonomy/policy.py` | persistence | `load_policy_block(repo_root, ruling_id, expected_sha) -> PolicyBlock`: single read of `deploy/families/rulings/<id>.md`, sha check, extracts exactly one fenced `autonomy-policy/v1` block, strict JSON, exact-set keys. |
| `…/autonomy/pins.py` | persistence | Literal ceilings (ARCH §4.5), `ENGINE_SOURCE_SHA256`, `PRODUCER_SOURCE_SHA256`, `REVOKED_SOURCE_SHA256`, `LIVE_GATE_ROUTED_KINDS = frozenset({"forecast_quantile_ladder"})`, `BOOTSTRAP_SEED` (§3.2). |
| `…/autonomy/closure.py` | persistence | `import_closure_sha256(entry_module) -> str`: grimp graph, sorted `(module, bytes)`, excluding `pins.py`. |
| `…/autonomy/entry_guard.py` | persistence | `FillReader` Protocol; `rung_has_net_position(base_slug, reader) -> bool` (leg-signed netting, C2). |
| `…/autonomy/plugin.py` | persistence | C6 Protocols plus `RefusingPlugin`. |
| `src/breezy/strategy/autonomy/node_plugins.py` | strategy | `NODE_PLUGINS: Mapping[CompositionKind, NodePlugin]` (FQ full; three `RefusingPlugin`s). |
| `src/breezy/analysis/autonomy/offline_plugins.py` | analysis | `OFFLINE_PLUGINS` (same key set). |
| `src/breezy/strategy/autonomy/registry_watch_actor.py` | strategy | `RegistryWatchActor(Actor)`, `RegistryWatchConfig`, `VetoReason` (closed enum). |
| `src/breezy/adapters/polymarket_us/exec/fill_reader.py` | adapters | `ReadOnlyExecFillReader(store_path)`: G6 `mode=ro` URI; reads `FILL_INDEX_KEY_PREFIX` and `FILL_KEY_PREFIX` exactly (no scan), decoding with the exec client's existing durable-fill decoder. |
| `src/breezy/analysis/autonomy_engine/{__init__,cli,daily,intraday,prelaunch,bootstrap,acceptance,mirror,demand,heartbeat,attest,mint,drill,export}.py` | analysis | The engine (§3.3). Console script `breezy-autonomy-engine = "breezy.analysis.autonomy_engine.cli:main"`. |
| `src/breezy/runtime/autonomy_deadman.py` | runtime | `breezy-autonomy-deadman` (§3.8). |
| `src/breezy/runtime/registry_hwm_reset_cli.py` | runtime | `breezy-registry-hwm-reset` (§3.8). |
| `src/breezy/runtime/registry_verify_cli.py` | runtime | `breezy-registry-verify`: read-only chain verify plus fold print, used by the §7 checklist. |
| `src/breezy/runtime/trade_relaunch_cli.py` | runtime | `breezy-trade-relaunch` (§3.7). |

`entry_guard` sits in `persistence` as ARCH names it, but the exec fill keys and decoder live in `adapters/polymarket_us/exec/client.py`, which `persistence` cannot import. The predicate therefore takes an injected `FillReader` (contradiction X4). The same split makes it portable to Kalshi.

### 3.2 C5 store (consumed unchanged except where flagged)

- **Path and mode.** `~/.local/share/breezy/registry/registry.sqlite`, dir 0700, file 0600, `journal_mode=DELETE`, `synchronous=FULL`. Shadow stage (WP10 S): `~/.local/share/breezy/registry-shadow/` with the identical layout.
- **DDL.** `transitions` holds every ARCH C5 column. `UNIQUE(venue, venue_seq)`, `UNIQUE(transition_id)`. `CREATE TRIGGER transitions_no_update BEFORE UPDATE ON transitions BEGIN SELECT RAISE(ABORT,'append-only'); END;` and the same for DELETE. Derived caches: `families`, `projection`, `lineage_counters`. Version table `meta(schema='registry/v1')`.
- **Write path.** `RegistryStore.append(rows: Sequence[TransitionRow], *, expected_prior_seq: int) -> AppendResult`. One `BEGIN IMMEDIATE`. If every `transition_id` already exists, the call is a logged no-op (`registry_replay_noop`). Otherwise: CAS `max(venue_seq)==expected_prior_seq`; `transitions.validate` against `fold(rows_so_far ∪ new)`; insert; extend the chain; refold the caches; `COMMIT`. A pair is one call, with the PROMOTE-side id computed first.
- **Chain.** `genesis = sha256(b"registry/v1|" + venue)`; `transition_hash = sha256(canonical_row ‖ prev_transition_hash)`.
- **Bootstrap (contradiction X2).** The ARCH table allows only `∅ → SHADOW` for BOOTSTRAP, yet ARCH Bootstrap seeds CHAMPION and RETIRED. This plan adds two rows that are legal **only in the genesis transaction of a venue chain (`venue_seq` 1..n, chain empty before the call)** and only for ids in `pins.BOOTSTRAP_SEED`:
  - `∅ → CHAMPION` BOOTSTRAP for `pm_us_crh_fq_v1`.
  - `∅ → RETIRED` BOOTSTRAP for `pm_us_crh_v4`, `pm_us_crh_cont` and `pm_us_crh_v2`.
  - Each row carries the committed manifest sha256 and artefact sha256 read from `deploy/families/<id>.json`.
  - Pinned by `test_registry_transition_table_is_exact`. This needs an ARCH table amendment (§5).
- **Exports.** The daily pass writes `~/.local/share/breezy/evidence/registry/registry_<venue>_<YYYY-MM-DD>.jsonl` (0444), holding every row since the previous export plus `{"chain_head":…, "venue_seq":…}`. It is written once per date, never rewritten (L-50). Readers verify that the chain prefix equals the newest export.
- **Directories.** `registry/families/` (child manifests, 0444), `registry/families/artefacts/<sha>.json` (0444), `registry/demand/<venue>/`, `registry/heartbeat/<venue>.json`, `registry/drill/marker.json`, `registry/engine.lock`. All are written atomically through `mkstemp` + `os.replace`.

### 3.3 Engine (`breezy-autonomy-engine --mode {daily,intraday,prelaunch,bootstrap}`)

Common to every mode, in order:
1. Compute its own `import_closure_sha256("breezy.analysis.autonomy_engine.cli")`. Refuse (exit 2, CRITICAL `AUTONOMY_ENGINE_UNPINNED`) unless the result is in `ENGINE_SOURCE_SHA256` and not in `REVOKED_SOURCE_SHA256`.
2. `flock -w` on `registry/engine.lock`: 60 s for daily, 30 s for intraday and prelaunch.
3. Load the policy block through `policy.load_policy_block`, with the sha from `_LINEAGE_POLICY_ALLOWLIST`.
4. Verify the chain from genesis against the newest export.
5. Fold.

Every transition carries `engine_code_sha`, `invocation_id` (uuid4), `decided_by="engine"`, `policy_ruling_id` and `policy_ruling_sha256`.

| Mode | Timer (UTC) | Writes | Order of work |
|---|---|---|---|
| `daily` | `OnCalendar=*-*-* 15:30:00`; `RuntimeMaxSec=900`; `MemoryMax=1G` | Any C5 kind except HWM_RESET; the export; ATTEST | (1) Exec-store halt mirror (§3.5). (2) Restrictive transitions from accepted FAILs. (3) RETIRE rules. (4) MINT from AUT-3 candidates under `derived/artefacts/` for allowlisted roots, ≤ `MAX_MINTS_PER_LINEAGE_PER_DAY`, writing the child manifest to `registry/families/`. (5) SHADOW→CHALLENGER PROMOTE on an accepted `OFFLINE_CHALLENGER` PASS. (6) CHALLENGER→CHAMPION PROMOTE **only if `promote_enabled`** (false in v1, §3.9). (7) RESUME where eligible. (8) The AUT-7 rollback selector, called through `engine.rollback.propose(fold) -> Proposal \| None`, which AUT-7 implements. (9) Drill steps per the active clause (§3.9). (10) ATTEST per CHAMPION. (11) Export. (12) Heartbeat. |
| `intraday` | `OnCalendar=*-*-* *:02/5:30` (150 s after AUT-6's `*:00/5` producer); `RuntimeMaxSec=120`; `MemoryMax=512M` | **DEMOTE, HALT, SWAP_CANCEL only.** The writer refuses any other kind with `IntradayKindRefused`, code-enforced in `intraday.py` before `RegistryStore.append`. | Halt mirror; accepted FAIL → DEMOTE/HALT; the §4.4 re-check of any pair effective today while `now ∈ [16:50Z, 17:00Z)` → SWAP_CANCEL; satisfied-demand unlink; drill marker removal once the DRILL_INJECT DEMOTE has committed; heartbeat. |
| `prelaunch` | `OnCalendar=*-*-* 16:45:00`; `RuntimeMaxSec=180`; finishes by 16:48:30Z | ACTIVATE, SWAP_CANCEL | For each pair pending for today's LAUNCH: §4.4 preconditions (no OPEN or AMBIGUOUS intent through the read-only G30 probe; an accepted `RECONCILIATION` PASS inside `reconciliation_horizon_h`; no INTEGRITY freeze). Pass → ACTIVATE; fail → SWAP_CANCEL. |
| `bootstrap` | Manual oneshot `breezy-autonomy-engine@bootstrap.service`, run once per stage (WP10) | Genesis BOOTSTRAP rows only | Refuses (exit 2) if the venue chain is non-empty. |

- **Units.** `deploy/systemd/breezy-autonomy-engine@.service` (template, `%i` = mode), with `ProtectSystem=strict`, `ReadWritePaths=%h/.local/share/breezy/registry %h/.local/share/breezy/evidence`, `ReadOnlyPaths=%h/.local/share/breezy/derived %h/.local/share/breezy/state %h/breezy`, `EnvironmentFile=-%h/.config/breezy/alerts.env` (G27 only), `OnFailure=breezy-study-failed@%n.service`, and **no** operator.env and **no** venue env files. Timers: `breezy-autonomy-engine@daily.timer`, `@intraday.timer`, `@prelaunch.timer`.
- **The engine lock is never the studies flock** (Y23).
- **Verdict acceptance** (`acceptance.py`, ARCH C4, checked in this order):
  1. Schema `verdict/v1` exact-set.
  2. `producer_code_sha ∈ PRODUCER_SOURCE_SHA256[producer_id]`.
  3. Every `inputs[].sha256` resolves under that role's root.
  4. `prereg_ruling_sha256 ==` the policy sha.
  5. `declared_action_class == policy.detector_map[detector].action_class`.
  6. `valid_until_ns − produced_at_ns ≤ MAX_VERDICT_VALIDITY_H` and `now < valid_until_ns`.
  7. `subject_artefact_sha256 ==` the bound sha of the subject family (BOOTSTRAP or MINT row).
  8. For `OFFLINE_CHALLENGER`, the lineage's `candidates_evaluated < k_max`.

  Any failure → `ERROR`, a WARNING alert (`AUTONOMY_VERDICT_ERROR`), and no action.
- **Demand files** (`demand.py`). If the first `append` of a restrictive row fails, the engine writes `registry/demand/<venue>/<family_id>_<ts_ns>.json` (0444, `demand/v1`, ≤ `DEMAND_FILE_MAX_BYTES`), retries with bounded backoff for ≤ 60 s, then retries again on every intraday pass. It unlinks the file when the fold shows the family HALTED, RETIRED or not CHAMPION at a row later than `ts_ns`.
- **Heartbeat** (`heartbeat.py`). Every daily and intraday pass atomically rewrites `registry/heartbeat/<venue>.json` (0444) with `{schema:"heartbeat/v1", ts_ns, invocation_id, engine_code_sha, chain_head, venue_seq}`.
- **ATTEST cadence.** Once per venue per day, in the 15:30Z pass, for the CHAMPION. It cites one accepted PASS of each kind in `attest_required_verdict_kinds`. `attest_valid_until_ns = min(valid_until_ns)`, refused above `ts_ns + H`.
- **Alerts.** Every engine CRITICAL goes through `deliver_with_proof`. Every committed transition sends one INFO alert `AUTONOMY_TRANSITION kind=<k> family=<id> seq=<n>` through `deliver_with_proof`, so delivery is proven per transition (README "alerted with delivery"). Restrictive transitions are sent as CRITICAL.

### 3.4 Node wiring (`app/trade.py`, `settings.py`, `fq/strategy.py`)

- **`BREEZY_FAMILY_SOURCE` values.** Unset, `registry_shadow` (WP10 stage S only, contradiction X7) or `registry`. Fixed in `deploy/systemd/breezy-trade-supervisor.service`; read only by `resolver.py` (`test_family_source_fixed_in_unit`).
- **Boot (`run`, `app/trade.py:905`).** When the source is `registry`:
  - Call `resolve_sending_family`.
  - Refuse boot (`EXIT_CONFIG_ERROR`) unless the resolved id equals `BREEZY_SENDING_FAMILY_ID`, `BREEZY_RESOLVED_REGISTRY_SEQ` is a verified prefix, and the fold names the family CHAMPION or HALTED (Z7).
  - The manifest object comes from `parse_family_manifest(raw: bytes, *, origin: Path)`, a new split of `load_family_manifest` into read + parse. The load path becomes `read_once` + parse, with identical validation, so the file is never re-read.
  - `_validate_sending_family_manifest` (`settings.py:366`) takes the same resolved object when the source is `registry`.
- **Y7 refusal.** If `registry.sqlite` holds any row, or the exec-store key `autonomy/registry_hwm/<venue>` exists, and the source is not `registry` while a sending family is set, boot is refused with `registry_source_required`.
- **Containment widening (L-12, one reviewed change at four sites).** `family_manifest.py:169,266-282`, `app/trade.py:122`, `settings.py:183` and `settings.py:366-388` accept a second root, `~/.local/share/breezy/registry/families`, only through `read_once_nofollow`. The resolve(), `..` and absolute refusals are kept.
- **`RegistryWatchActor`.** Composed in `_compose_forecast_quantile_ladder` (`app/trade.py:676`) into `extra_actors`.
  - `on_start`: `clock.set_timer("registry_watch", 60 s)`. The callback only calls `asyncio.run_coroutine_threadsafe(self._tick_once(), loop)` and returns, wrapped so it never raises (L-16).
  - `_tick_once` runs on the loop thread. It reads `transitions WHERE venue=? AND venue_seq > last` through `RegistryReader`, verifies each link from the stored head, re-checks the hash of the stored-head row, folds in memory, reads the heartbeat and demand files (single read), reads the AUT-6 delivery journal's newest canary row, updates the veto state, and writes the HWM key `autonomy/registry_hwm/<venue>` to the node's exec store **only after a verified read**.
  - It never reads `projection` or `families`.
- **Veto API.** `entry_veto(instrument_id) -> VetoReason | None` is synchronous and lock-free (loop thread only). It returns `registry_unreadable` before the first verified tick and whenever `last_verified_tick_age > WATCH_TICK_STALE_S`. The closed reason enum is ARCH C5's. `rung_net_position_held` comes from `entry_guard.rung_has_net_position(base_slug(instrument_id), ReadOnlyExecFillReader)`. A change of veto reason invokes the injected `on_veto_transition(reason, cleared: bool)`: AUT-1 wires the C1 `EntryVeto` record and AUT-6 the alert.
- **FQ strategy slot.** `ForecastQuantileLadderStrategy.__init__` gains `entry_veto: Callable[[InstrumentId], str | None] | None = None`. `try_submit` order becomes: permit → `entry_veto(take.instrument_id)` → `submit_veto` → `fee_verified` (`fq/strategy.py:629-645`). `submit_veto` and the exit seam are untouched.
- **Per-kind rule.** Every kind in `LIVE_GATE_ROUTED_KINDS` must pass `entry_veto` (`test_registry_champion_requires_live_orders_gate_for_every_kind` also asserts the slot is wired). Today that is FQ only; the CRH kinds carry `RefusingPlugin` and cannot be CHAMPION.

### 3.5 Exec-store halt mirror (consumed from ARCH, implemented in `mirror.py`)

- Read-only through `read_family_halt_rows_readonly` with exact keys (`continuous_rung_hold/` prefix family-halt keys for every non-RETIRED registry family, plus the legacy key). The mapping is ARCH C5's table literally (`test_halt_reason_class_map_is_exact`).
- A read failure or an unknown payload → INTEGRITY; no non-restrictive transition that run (`test_mirror_read_failure_is_integrity`).
- `autonomy/` keys are never in the mirror's key set (`test_autonomy_exec_keys_disjoint_from_halt_prefixes`).

### 3.6 Supervisor wiring (`trade_supervisor.py`, `trade_supervisor_core.py`)

- **New port.** `SupervisorPorts.resolve_registry_family: Callable[[int], ResolvedFamily | ResolverRefusal]`. Default: `resolver.resolve_sending_family` with the production roots.
- **New state.** `DaySchedulerState.resolved_family_id: str | None`, `resolved_registry_seq: int | None`, `resolved_at: datetime | None`, plus pure `record_registry_resolved(state, now, resolved)`.
- **New pure helper.** `build_child_env(base: Mapping[str,str], state, *, permit_ceiling_ns: int | None) -> dict[str,str]` in `trade_supervisor_core.py`. It copies `base` and, when the source is `registry`, sets `BREEZY_SENDING_FAMILY_ID` and `BREEZY_RESOLVED_REGISTRY_SEQ` from `state`. It sets `BREEZY_PERMIT_EXPIRY_CEILING_NS` when the ceiling is given. It never touches any other key (`test_child_env_touches_only_three_keys`, an AST scan for operator-control tokens). **All four spawn sites** (`trade_supervisor.py:1289`, `:1379`, `:1631`, `:1982`) call it. Today they forward the supervisor's `os.environ`, not the child's (contradiction X3).
- **LAUNCH.** `_do_launch`, before the existing lock and intent checks, resolves once (`resolved_at` latched).
  - On `ResolverRefusal`: CRITICAL `REGISTRY_UNAVAILABLE` via `deliver_with_proof` on the first refusal of the window, `done=False`, re-resolve each poll until `LAUNCH_WINDOW_END_UTC` (17:00Z), never a fallback to the env id or to the root.
  - On success, the existing launch path runs with `build_child_env(os.environ, state, permit_ceiling_ns=None)`.
- **§4.4 at LAUNCH.** If an ACTIVATE stands for today's pair, the supervisor re-runs the read-only preconditions (`probe_open_intent`; a RECONCILIATION verdict inside its horizon; no INTEGRITY freeze in the fold). On failure: CRITICAL, no spawn, `done=False`. The intraday engine passes at 16:52:30Z and 16:57:30Z write the SWAP_CANCEL, and the next re-resolve returns the incumbent. The supervisor does **not** start any unit (contradiction X5; `test_intraday_schedule_has_two_runs_in_launch_window`).
- **Post-launch SWAP_CANCEL.** In `_do_relaunch_check` (`trade_supervisor.py:1304`), while `now < 17:00Z`, it re-resolves each poll. If the resolved id differs from `state.resolved_family_id`: `terminate_after_toctou_recheck(tracked_pid)`, wait for the DISPOSED line and lock release, `record_registry_resolved`, spawn the incumbent on the existing launch budget (`MAX_RELAUNCH_ATTEMPTS`), and log `registry_swap_voided_relaunch from=<a> to=<b>`.
- **Midday relaunch and boot retry** never re-resolve the family. They pass the latched id and seq. The node applies Z7, and a family DEMOTEd intraday boots HALTED with entries vetoed.
- **Self-check.** `resolve_sending_family_id()` returns `state.resolved_family_id` when the source is `registry`, so the continuous-family self-check block keys on the resolved id.
- **Shadow source.** With `registry_shadow`, the supervisor resolves against the shadow root, logs `registry_resolve_shadow agree=<bool> env=<id> resolved=<id> seq=<n>`, and spawns with the env id unchanged.

### 3.7 `breezy-trade-relaunch` (replaces the hand `systemd-run` runbook)

- **Interface.** `breezy-trade-relaunch --reason <token>`, where `token ∈ {venue_outage, node_wedged, operator_requested}`. No family argument and no environment argument exist.
- **Request.** It writes `~/.local/share/breezy/state/relaunch_request.json` (0600, atomic, schema `relaunch_request/v1`: `{ts_ns, reason, request_id}`), then waits up to 600 s for `relaunch_response_<request_id>.json`. It exits 0 on `{"outcome":"RELAUNCHED"}`, 3 on `{"outcome":"REFUSED","reason":…}`, and 4 on a timeout.
- **Supervisor handler.** A new `Phase.RELAUNCH_REQUEST` is checked each poll outside [16:40Z, 17:10Z). It runs the 10-02 recipe **in-process**:
  1. The tracked pid holds the intent flock.
  2. No unterminated `SubmitOrder` in the log tail.
  3. `terminate_after_toctou_recheck`.
  4. Wait for `TradingNode: DISPOSED` in the post-signal bytes, then the lock release.
  5. `probe_open_intent`; if an intent is open, REFUSED `intent_open`.
  6. When the source is `registry`, re-resolve **with the same rule as LAUNCH for the family id**: a CHAMPION or HALTED family equal to the latched one, else REFUSED `registry_disagrees`.
  7. `spawn_node(env=build_child_env(os.environ, state, permit_ceiling_ns=state.first_boot_permit_expires_at_ns))`.
- **Budget and alert.** `RELAUNCH_REQUESTS_MAX_PER_DAY = 3`. Every request and outcome raises an INFO alert through `deliver_with_proof`.
- **Why a request and not a direct spawn.** Nothing is copied from `/proc/<pid>/environ`, so the caps never leave the supervisor process. No `systemd-run` scope is needed, because the child is the supervisor's own (Popen retained, reaped).
- **Memory note.** `hand-relaunch-mechanics` is superseded on activation; the update happens in WP10's close step.

### 3.8 Dead-man, HWM reset, verify

- **`breezy-autonomy-deadman`.** `.timer` `OnCalendar=*:00/30`; own lock `registry/deadman.lock`; `MemoryMax=128M`. It reads `heartbeat/<venue>.json` (single read) and the chain-head age through `RegistryReader`. It raises CRITICAL `AUTONOMY_ENGINE_HEARTBEAT_STALE` past `ENGINE_HEARTBEAT_STALE_S` and `AUTONOMY_CHAIN_STALE` past H, both through `deliver_with_proof`. When neither applies it exits 0 with `deadman ok age_s=<n>`.
- **`breezy-registry-hwm-reset --venue <v> --to-export <date>`.**
  - Preconditions: no node holds the exec flock (the `assert_no_live_node_before_intent_probe` pattern), and it can take the engine lock.
  - It verifies the restored chain as a prefix of the named export, writes `evidence/registry/hwm_reset_<ts>.json`, appends an `HWM_RESET` row through `RegistryStore` (`decided_by=operator_cli`), rewrites the exec-store HWM key under the exec flock, and raises CRITICAL through `deliver_with_proof`.
- **`breezy-registry-verify --venue <v> [--registry-root <p>] [--at <iso>]`.** Read-only. It prints `chain_ok=<bool> head=<h> venue_seq=<n> export_prefix_ok=<bool> champion=<id> state=<s> pending=<…>`. It is the scorer's tool (§7).

### 3.9 Policy ruling (WP3) — DRAFT, values proposed here and settled by peer review

**File.** `docs/evidence/RULING_autonomy_promotion_policy_v1_<filing-date>.md`, with a byte-identical deploy copy at `deploy/families/rulings/` (pattern G4; containment test `test_no_module_under_src_reads_docs_evidence` respected).

**Supersessions.** The ruling supersedes D11 (`WORK_BREAKDOWN` §D11) for allowlisted lineages, as `RULING_operator_full_autonomy_2026-10-03.md` §3 permits. It lifts the AUD-10 PROVISIONAL tag **only** for the `OFFLINE_CHALLENGER`/`FORWARD_SHADOW` predicates it names, which are AUT-4's producers. It never touches the caps, master enablement, the permit or NO-SEND.

**Feasibility calculation (ARCH §4.2 Y12; inputs cited).**
- **σ_d and MDE.** σ_d = 0.132 per station-day, the paired traded-rung Brier difference, measured on validation (`RULING_nbp_pmus_leg_infeasible_node4_2026-09-30`, A-3, CI [0.127, 0.138]). MDE δ = 0.0152 Brier, the pre-registered threshold of that ruling.
- **n_min formula and anchor.** n_min = ((z₁₋α_K + z₀.₈)·σ_d/δ)². At α = 0.025 this reproduces that ruling's 592, which validates the formula.
- **Proposed α and K_max.** α_total = 0.025 one-sided, K_max = 2 ⇒ α_K = 0.025·2⁻² = 0.00625, z = 2.498 ⇒ **n_min = 841 independent station-days**. Sensitivity: K_max = 1 gives 717; K_max = 4 gives 1087; δ = 0.025 at K_max = 2 gives 311.
- **Qualifying rate.** PM.us lists 5 cities, HIGH only (memory note `polymarket-us-surface-is-5-cities-high-only`). The replay census over `window_complete` rows found 10/10 SUFFICIENT on closed post-freeze days, so ≤ 5/day (`census-rows-include-open-windows`). The venue skips about 9% of station-days (`venue-skips-station-days`). Upper bound: **4.55 qualifying station-days per day**. AUT-4 replaces this with its measured value. The measured value can only be lower, because tape days that fail replay-sufficiency are excluded.
- **Earliest forward-evaluation start.** The first AUT-3 candidate cannot be minted before Wave 2. Taking `forward_eval_start_utc` = 2026-11-02 as the optimistic case: 841 / 4.55 = 185 days ⇒ **`eta_date` = 2027-05-06**, after the 2027-01-25 KILL. Even starting today (2026-10-03) the ETA is 2027-04-06.
- **Capacity bound.** Forward capacity before the KILL from 2026-11-02 is 84 days × 4.55 ≈ 382 station-days. That would need δ ≥ 0.0225 at α_K = 0.00625, a Brier gain on the traded rung against the **market** baseline that the 09-20 finding ("market resolution 1.98× the forecast's", memory note `forecast-edge-closed-pmus-rungs`) makes implausible.
- **Consequence.** `promote_enabled = false`. PROMOTE (CHALLENGER→CHAMPION) is proven by the DRILL_PROMOTE drill only, and no edge-based promotion is claimed (ARCH §7). A later ruling revision (for example a Kalshi venue with 24 stations) may set it true only with a new feasibility record.

**Other proposed values and justification.**

| Key | Proposed | Ceiling | Justification |
|---|---|---|---|
| `alpha_total` | 0.025 | n/a (ruling) | Same α as PREREG v2 (memory note `prereg-v2-sequential-ruling-2026-09-04`) and the node-4 ruling, so verdicts are comparable. |
| `k_max` | 2 | ≤ 4 | Daily refits create many candidates; K = 2 keeps n_min within 1.42× of the single-test n (841 vs 592). K = 4 costs +29% more for no capacity gain. |
| `min_days_between_promotes_per_lineage` (M) | 30 | ≥ 14 | WP-26 criterion (4) INFERRED 30. It also equals one LD-OBF look spacing at about 10 fills per 2 days ≈ 5 fills/day × 30 days ÷ 10 = 15 looks, so a promoted child accrues at least 15 looks before a successor. |
| `forward_shadow.min_calendar_days` (forward-day minimum) | 60 | n/a | The stop-gate power note: about 300 station-days ≈ 60 clean calendar days at σ/μ ≈ 8 (memory note `stop-gate-is-live-small`). This also guarantees ≥ 2 M-windows of forward evidence. |
| `forward_shadow.n_min_station_days` | 841 | n/a | Computed above. |
| `forward_shadow.accepted_assumptions` | `[]` | n/a | `slippage_champion_proxy` is **not** accepted. Any verdict carrying it is INCONCLUSIVE (ARCH C4 Y12). A challenger with a different execution policy cannot borrow champion slippage. |
| `live.drawdown.statistic` | `peak_to_trough_cum_realized_pnl_over_cum_cost` | n/a | Cost-normalised and computed from C2 admissible labels only (no canary, no drill). It **never reads either operator cap**, so it is neither derived upward nor downward from them. |
| `live.drawdown.limit` | 0.40 | n/a | The proposed starting value. WP3 RED/GREEN calibrates it with a Monte-Carlo H0 that reproduces the registered null exactly (L-41): zero edge, the champion's empirical ask distribution, mutually exclusive rungs (L-40). The limit is chosen so that P(trip before 2027-01-25 under H0) ≤ 0.05. If calibration yields a different value, the DRAFT is revised before peer review closes. |
| `live.drawdown.min_settled_admissible_fills` | 10 | n/a | Below 10 fills the statistic is dominated by one 1-contract loss. |
| `reconciliation_horizon_h` | 26 | ≤ `MAX_VERDICT_VALIDITY_H` | One daily RECONCILIATION run plus 2 h of slack. |
| `attest_required_verdict_kinds` | `["HEALTH","RECONCILIATION"]` | n/a | ARCH Z5 example. A dead labeller or capture therefore stops entries within H. |
| `damping.RESUME_COOLDOWN_H` | 24 | ≥ 24 | At the ceiling. |
| `damping.MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D` | 2 | ≤ 2 | At the ceiling. |
| `damping.MAX_INFRA_RESUMES_PER_VENUE_7D` | 3 | ≤ 3 | At the ceiling. |
| `damping.MAX_ROLLBACKS_PER_VENUE_30D` | 2 | ≤ 2 | At the ceiling. |
| `damping.MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` | 1 | ≤ 2 | Stricter. One logical change per day keeps attribution clean. Drill rows count against the drill budget only. |
| `damping.MAX_MINTS_PER_LINEAGE_PER_DAY` | 1 | ≤ 1 | At the ceiling. |
| `damping.DRILL_BUDGET_PER_VENUE_30D` | 1 | ≤ 1 | At the ceiling. |
| `staleness.DEADMAN_HORIZON_H` (H) | 30 | ≤ 30 | At the ceiling. |
| `staleness.MAX_VERDICT_VALIDITY_H` | 26 | ≤ 26 | At the ceiling. |
| `staleness.ENGINE_HEARTBEAT_STALE_S` | 1800 | ≤ 3600 | Stricter: 6 missed 5-minute passes. A daily pass holding the engine lock ≤ 15 min cannot trip it. |
| `staleness.WATCH_TICK_STALE_S` | 180 | ≤ 180 | At the ceiling. |
| `staleness.ALERT_CANARY_MAX_AGE_H` | 26 | ≤ 26 | At the ceiling. |
| `staleness.DEMAND_FILE_MAX_BYTES` / `DEMAND_FILES_MAX` | 4096 / 16 | ≤ 4096 / ≤ 64 | Stricter on count: one venue with at most a few families. |

**Detector → action map and cause classes.** The VERDICT detector ids are proposed here. AUT-6, AUT-4 and AUT-2 must emit exactly these ids, or the DRAFT is revised at association (§5). NODE_LOCAL vetoes (`feed_stale`, `recorder_stale`, `permit_lapsed`, `capture_gap`, `alerts_undeliverable`) are fixed `ENTRY_VETO` in code. Their persistence escalates through the VERDICT ids below.

| Detector id | Producer | Kind | Action | Cause class | Horizon |
|---|---|---|---|---|---|
| `freshness.persist` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_INFRA | `feed_stale`/`recorder_stale` continuous ≥ 6 h |
| `liveness.permit_process` | AUT-6 | HEALTH | DEMOTE | RECOVERABLE_INFRA | `permit_lapsed` ≥ 2 h, or node process/log liveness FAIL |
| `health.capture_join` | AUT-1 | HEALTH | DEMOTE | RECOVERABLE_INFRA | `capture_gap` ≥ 1 h, or a daily join audit < 100% |
| `health.alert_canary` | AUT-6 | HEALTH | DEMOTE | RECOVERABLE_INFRA | canary `DeliveryProof` FAIL |
| `health.label_lag` | AUT-2 | HEALTH | ALERT | RECOVERABLE_INFRA | label > 24 h after settlement (ATTEST then lapses through `attest_required_verdict_kinds`) |
| `health.unit` | AUT-6 | HEALTH | ALERT | RECOVERABLE_INFRA | any failed autonomy or study unit |
| `health.reproducibility` | AUT-3 | HEALTH | ALERT | RECOVERABLE_MODEL | C3 rerun sha mismatch (the artefact also becomes ineligible above SHADOW, per C3) |
| `reconciliation.net_position` | AUT-2 | RECONCILIATION | DEMOTE | RECOVERABLE_INFRA | venue net ≠ ledger outside tolerance |
| `drift.forecast_input` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | per the AUT-6 threshold, one daily verdict |
| `drift.calibration_live` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `drift.fill_rate_slippage` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `parity.train_serve` | AUT-6 | DRIFT | DEMOTE | RECOVERABLE_MODEL | daily |
| `drift.venue_shape` | AUT-6 | DRIFT | ALERT | RECOVERABLE_INFRA | the node already refuses per order (`_EXECUTION_DRIFT_ALLOWED_KEYS`) |
| `drift.fee_schedule` | exec-store mirror | (mirror) | HALT | TERMINAL | immediate (ARCH mirror table) |
| `live.sequential` | AUT-4 | LIVE_SEQUENTIAL | HALT | TERMINAL | an LD-OBF boundary crossed (PREREG v2; S_k and n frozen) |
| `live.kill_clock` | AUT-4 (via `evaluate_c_kill`) | LIVE_SEQUENTIAL | HALT | TERMINAL | `structural_dead` true, or 2027-01-25 reached |
| `live.drawdown` | AUT-4 | LIVE_SEQUENTIAL | HALT | TERMINAL | `live.drawdown.limit` crossed with ≥ 10 fills. TERMINAL because a halted family accrues no fills, so the verdict could never return PASS for a RESUME. A false positive costs a new lineage root (accepted, ARCH Z20). |
| `drill.inject` | AUT-6 (pinned marker detector) | DRIFT | DEMOTE | RECOVERABLE_MODEL | **only while `drill_clause` is active**; otherwise ERROR |

**Drill clause.**

```json
{"drill_child_id": "pm_us_crh_fq_v1_r0001", "root_family_id": "pm_us_crh_fq_v1",
 "active_from_utc": "<filing date + 7 d>", "active_until_utc": "<active_from + 21 d>",
 "max_episodes": 1, "inject_at": "daily_pass_on_first_effective_day", "resume_after_h": 24}
```

`drill_clause_sha256` = sha256(canonical_json(clause)). It is stored in the block and on every drill row. The dates are concrete at filing and covered by peer review. A missed window needs a ruling revision; it never extends silently.

**Machine-readable block, the DRAFT that is filed verbatim inside the ruling.**

```autonomy-policy/v1
{
  "schema": "autonomy-policy/v1",
  "policy_ruling_id": "RULING_autonomy_promotion_policy_v1_<filing-date>",
  "venues": ["polymarket_us"],
  "lineage_roots": ["pm_us_crh_fq_v1"],
  "promote_enabled": false,
  "feasibility": {"n_min_unit": "independent_station_days", "n_min": 841, "sigma_d": 0.132,
    "mde_brier": 0.0152, "alpha_k": 0.00625, "power": 0.80,
    "qualifying_station_days_per_day": 4.55, "earliest_forward_eval_start_utc": "2026-11-02",
    "eta_date": "2027-05-06", "kill_date": "2027-01-25"},
  "alpha_total": 0.025, "alpha_spending": "halving_per_candidate", "k_max": 2,
  "min_days_between_promotes_per_lineage": 30,
  "offline_challenger": {"holdout_opens_max_per_lineage": 1, "rolling_forward_holdout": true},
  "forward_shadow": {"min_calendar_days": 60, "n_min_station_days": 841,
    "predicates": ["traded_rung_brier_beats_market_baseline", "ev_net_fee_slippage_ci_lower_gt_0",
                   "traded_rung_calibration_leg_pass", "n_ge_n_min"],
    "accepted_assumptions": []},
  "live": {"drawdown": {"statistic": "peak_to_trough_cum_realized_pnl_over_cum_cost",
                        "limit": 0.40, "min_settled_admissible_fills": 10}},
  "reconciliation_horizon_h": 26,
  "attest_required_verdict_kinds": ["HEALTH", "RECONCILIATION"],
  "detector_map": {"freshness.persist": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 6},
    "liveness.permit_process": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 2},
    "health.capture_join": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 1},
    "health.alert_canary": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "health.label_lag": {"action_class": "ALERT", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 24},
    "health.unit": {"action_class": "ALERT", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "health.reproducibility": {"action_class": "ALERT", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "reconciliation.net_position": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "drift.forecast_input": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "drift.calibration_live": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "drift.fill_rate_slippage": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "parity.train_serve": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0},
    "drift.venue_shape": {"action_class": "ALERT", "cause_class": "RECOVERABLE_INFRA", "horizon_h": 0},
    "drift.fee_schedule": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "live.sequential": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "live.kill_clock": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "live.drawdown": {"action_class": "HALT", "cause_class": "TERMINAL", "horizon_h": 0},
    "drill.inject": {"action_class": "DEMOTE", "cause_class": "RECOVERABLE_MODEL", "horizon_h": 0}},
  "damping": {"RESUME_COOLDOWN_H": 24, "MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D": 2,
    "MAX_INFRA_RESUMES_PER_VENUE_7D": 3, "MAX_ROLLBACKS_PER_VENUE_30D": 2,
    "MAX_SENDER_CHANGES_PER_VENUE_PER_DAY": 1, "MIN_DAYS_BETWEEN_PROMOTES_PER_LINEAGE": 30,
    "MAX_CANDIDATES_PER_LINEAGE_PER_FORWARD_WINDOW": 2, "MAX_MINTS_PER_LINEAGE_PER_DAY": 1,
    "DRILL_BUDGET_PER_VENUE_30D": 1},
  "staleness": {"DEADMAN_HORIZON_H": 30, "MAX_VERDICT_VALIDITY_H": 26, "ENGINE_HEARTBEAT_STALE_S": 1800,
    "WATCH_TICK_STALE_S": 180, "ALERT_CANARY_MAX_AGE_H": 26, "DEMAND_FILE_MAX_BYTES": 4096,
    "DEMAND_FILES_MAX": 16},
  "drill_clause": {"drill_child_id": "pm_us_crh_fq_v1_r0001", "root_family_id": "pm_us_crh_fq_v1",
    "active_from_utc": "<filing+7d>", "active_until_utc": "<filing+28d>", "max_episodes": 1,
    "inject_at": "daily_pass_on_first_effective_day", "resume_after_h": 24},
  "drill_clause_sha256": "<sha256 of canonical drill_clause, computed at filing>"
}
```

Placeholders `<…>` exist only in this DRAFT. The filed copy is strict JSON with concrete values, and `test_policy_block_exact_set_keys` refuses any `<`.

### 3.10 Drill timeline the engine must support (steps are AUT-7b's; mechanics are AUT-5's)

| Day | Engine action (15:30Z daily unless stated) | Registry rows |
|---|---|---|
| D−1 | MINT `pm_us_crh_fq_v1_r0001` (C3 no-new-lineage: artefact bytes copied to `registry/families/artefacts/<sha>.json`; manifest equal to the root except the §4.2 keys, with `live_orders_ruling` = the policy ruling); DRILL_ADMIT; DRILL_PROMOTE pair pending for D. At 16:45Z prelaunch: ACTIVATE. | MINT, DRILL_ADMIT, DRILL_PROMOTE + SUPERSEDE(fq_v1, `rollback_eligible=true`), ACTIVATE |
| D | 16:50Z LAUNCH: the resolver returns r0001 and the drill episode starts (C1 `drill=true`). | (fold) |
| D+1 | 15:30Z: write `registry/drill/marker.json`. AUT-6 producer (`*:00/5`) → `drill.inject` FAIL verdict. Intraday pass (≤ 5 min later) → DEMOTE. The watch actor vetoes on its next tick (`registry_halted`); the SLO is ≤ 15 min. The intraday pass removes the marker after commit; the next producer run emits PASS. | DEMOTE (drill) |
| D+2 | 16:50Z LAUNCH: r0001 boots HALTED, entries vetoed, exits live (Z7). No RESUME yet: the cooldown is 24 h from the DEMOTE at about 15:40Z on D+1. | none |
| D+3 | 15:30Z: RESUME (cooldown met, cause PASS, no pending pair, §4.4). The same pass proposes ROLLBACK to fq_v1 pending for D+4. 16:45Z: ACTIVATE. | RESUME, ROLLBACK + SUPERSEDE(r0001), ACTIVATE |
| D+4 | 16:50Z LAUNCH restores fq_v1 at a byte-identical sha; the episode closes. | (fold) |

Clock: 6 trading days from MINT to restoration. That satisfies ARCH's "at least 4" (contradiction X8 notes ARCH's implied 4). In the timeline above, the marker is written on D+1 rather than D so that the drill child trades one full day as CHAMPION before demotion. The policy can move `inject_at` to D, which saves one day.

## 4. Work packages

Gate commands, run for **every** WP after merge (L-43). Exact interpreter, never `uv` (L-51). In a worktree, `PYTHONPATH=<worktree>/src` must be set (memory note `worktree-needs-pythonpath`).
- **Focused:** `scripts/ci/run_tests_no_egress.sh <test paths>`.
- **Full:** `scripts/ci/run_tests_no_egress.sh` (includes `tests/unit/test_mypy_ratchet.py`).
- **Imports:** `cd <tree root> && .venv/bin/lint-imports`, which must print "N kept, 0 broken" (memory note `python-m-importlinter-is-a-noop`).
- **Exit code:** read it explicitly (memory note `pytest-q-doubles-into-qq`).

Envelope tests whose GREEN belongs to another area are created in WP1 as `pytest.mark.xfail(strict=True, reason="owner AUT-n WPk")`. The owner removes the marker as its GREEN. Stage L2 (WP10) requires zero such markers left.

### AUT-5.WP1 — Foundation (ARCH Wave 0): store, chain, fold, transitions, pins, policy parser, C6 protocols

- **Scope.** §3.1 modules `canonical`, `single_read`, `schemas`, `transitions`, `registry_store`, `fold`, `pins`, `closure`, `policy` (parser), `plugin`, `strategy/autonomy/node_plugins.py`, `analysis/autonomy/offline_plugins.py`; envelope scans; the cross-area strict-xfail placeholders.
- **Files.** New: the modules above. New tests: `tests/unit/test_registry_store.py`, `test_registry_fold.py`, `test_autonomy_pins.py`, `test_autonomy_envelope.py`, `test_autonomy_plugins.py`. Modified: `pyproject.toml` (one forbidden contract: `breezy.persistence.autonomy` never imports `breezy.adapters`, `breezy.runtime`, `breezy.strategy` or `nautilus_trader`).
- **RED first.**
  - `tests/unit/test_autonomy_envelope.py::test_autonomy_never_reads_or_writes_operator_controls`
  - `…::test_autonomy_never_touches_enablement_permit_or_firewall`
  - `…::test_autonomy_never_imports_order_path`
  - `…::test_autonomy_alert_egress_not_widened`
  - `…::test_autonomy_payload_hygiene_scan`
  - `tests/unit/test_registry_store.py::test_registry_transition_table_is_exact` (includes the two genesis BOOTSTRAP rows)
  - `…::test_registry_cas_and_idempotent_replay`
  - `…::test_registry_hash_chain_and_triggers`
  - `…::test_repeat_supersede_same_family_is_not_replay`
  - `…::test_registry_readonly_open_engine_stopped`
  - `…::test_family_artefact_binding_immutable`
  - `…::test_bootstrap_rows_only_in_genesis_transaction`
  - `tests/unit/test_registry_fold.py::test_terminal_halt_freezes_lineage`
  - `…::test_demote_during_pending_swap_incoming`
  - `…::test_demote_during_pending_swap_outgoing`
  - `…::test_resume_refused_while_swap_pending`
  - `…::test_unactivated_pair_lapses_at_launch`
  - `…::test_drill_promote_refuses_non_champion_sha`
  - `…::test_drill_budget_separate`
  - `…::test_drill_admit_charges_only_drill_budget`
  - `…::test_drill_flag_spans_promote_to_rollback`
  - `…::test_infra_cause_never_retires`
  - `…::test_damping_ceilings`
  - `…::test_lapsed_pair_never_charged`
  - `tests/unit/test_autonomy_pins.py::test_code_identity_pins_cover_import_closure`
  - `…::test_engine_pin_history_retained`
  - `tests/unit/test_autonomy_plugins.py::test_family_plugin_exact_set`
  - Strict-xfail placeholders:
    - `tests/unit/test_autonomy_cross_area.py::test_deliver_with_proof_reports_non_2xx_through_tee` (AUT-6)
    - `::test_critical_alerts_use_delivery_proof` (AUT-6)
    - `::test_self_heal_unit_allowlist_is_literal_and_excludes_trade` (AUT-6)
    - `::test_drill_inject_passes_when_marker_absent` (AUT-6)
    - `::test_drill_fills_excluded_from_n_and_kill_clock` (AUT-2 with AUT-4)
    - `::test_reconciliation_and_entry_guard_never_read_canary_store[reconciliation]` (AUT-2)
    - `::test_rollback_restores_byte_identical_artefact` (AUT-7)
- **GREEN.**
  - Every AUT-5-owned test above passes.
  - Each placeholder XFAILs strictly.
  - Mutation evidence (L-33) for the store: deleting the UPDATE trigger turns `test_registry_hash_chain_and_triggers` red, and the RED→GREEN log is kept as the artefact.
- **Activation.** None needed: no runtime caller yet. Library-only, merged when green.

### AUT-5.WP2 — Resolver, manifest single-read and containment widening, `entry_guard`, fill reader

- **Scope.** `resolver.py`; the `parse_family_manifest` split; the four-site L-12 containment widening; `entry_guard.py`; `adapters/polymarket_us/exec/fill_reader.py`.
- **Files.** `src/breezy/persistence/family_manifest.py`, `src/breezy/runtime/settings.py`, `src/breezy/app/trade.py` (manifest load site only), and the new modules. Tests: `tests/unit/test_registry_resolver.py`, `tests/unit/test_entry_guard.py`.
- **RED first.**
  - `tests/unit/test_registry_resolver.py::test_resolver_binds_bytes_to_row`
  - `…::test_registry_paths_refuse_symlinks`
  - `…::test_verify_and_load_share_bytes`
  - `…::test_child_manifest_equals_committed_root_except_allowlist`
  - `…::test_exit_gate_stays_code_only`
  - `…::test_registry_champion_requires_live_orders_gate_for_every_kind`
  - `…::test_resolver_refusals_give_no_champion` (parametrised over every ARCH refusal)
  - `…::test_root_row_accepts_committed_live_orders_triple` (contradiction X1)
  - `tests/unit/test_entry_guard.py::test_rung_net_position_veto_crosses_legs_and_families` (fixture written through the real exec-client `record_fill` path, L-42)
  - `…::test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]`
  - `…::test_fill_reader_production_default_runs_once` (L-55)
- **GREEN.**
  - All of the above pass.
  - The existing tests `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_probe_containment` and every `family_manifest` test pass **unmodified**.
- **Activation.** The code is inert until `BREEZY_FAMILY_SOURCE` is set (WP10). The manifest single-read path is live at the next 16:50Z LAUNCH, with byte-identical behaviour proven by the unchanged existing tests.

### AUT-5.WP3 — Policy ruling DRAFT → peer review → filing (document WP plus its tests)

- **Scope.** The ruling text, using §3.9 verbatim as its base. The drawdown H0 Monte-Carlo calibration. Peer review. Filing at `docs/evidence/`. The byte-identical deploy copy.
- **Peer review.** Dispatched by the coordinator, never the operator: `prediction-market-reviewer` (α, n_min, drawdown H0, L-40/L-41), `trading-bot-architect` (detector map, cause classes, drill clause), `security-reviewer` (supersession scope, no cap or permit language). Lowest score wins. It converges on α_total, K_max, M, the forward-day minimum, the drawdown limit and every horizon. Values move only inside the code ceilings.
- **Files.**
  - New: `docs/evidence/RULING_autonomy_promotion_policy_v1_<date>.md`; `deploy/families/rulings/RULING_autonomy_promotion_policy_v1_<date>.md`.
  - New: `scripts/analysis/autonomy_drawdown_h0.py` (calibration, deterministic seed 20260904, capped `MemoryMax=2G` run).
  - Tests: `tests/unit/test_autonomy_policy_block.py`.
- **RED first.**
  - `tests/unit/test_autonomy_policy_block.py::test_policy_block_not_looser_than_code_ceilings`
  - `…::test_promote_disabled_when_eta_after_kill`
  - `…::test_policy_block_exact_set_keys`
  - `…::test_policy_ruling_deploy_copy_matches_evidence`
  - `…::test_detector_map_covers_required_classes` (every C6 required class has ≥ 1 VERDICT id)
  - `…::test_drill_clause_sha_matches_canonical_clause`
  - `…::test_feasibility_n_min_reproduces_formula` (recomputes 841 from σ_d, δ, α_K, power)
  - `tests/unit/test_autonomy_drawdown_h0.py::test_h0_reproduces_registered_null` (L-41 positive control)
- **GREEN.**
  - Tests pass against the filed deploy copy.
  - The peer-review records sit under `docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-5-ruling-*.md`.
  - The final lowest score is recorded in the ruling's review trail.
- **Activation.** The ruling becomes binding when WP9's allowlist row pins its sha. Filing happens before WP10 stage S, so the shadow engine runs on the real block.

### AUT-5.WP4 — Engine: daily, intraday (restrictive-only, heartbeat), prelaunch, bootstrap; acceptance; mirror; demand; ATTEST; MINT; export; units

- **Scope.** §3.3, §3.5 and §3.10 mechanics; `deploy/systemd/breezy-autonomy-engine@.service` and its 3 timers; pins update.
- **Files.**
  - New: `src/breezy/analysis/autonomy_engine/*`, `deploy/systemd/breezy-autonomy-engine@.service`, `breezy-autonomy-engine@{daily,intraday,prelaunch}.timer`.
  - Modified: `pyproject.toml` (console script), `deploy/systemd/README.md` (unit table), `persistence/autonomy/pins.py` (the `ENGINE_SOURCE_SHA256` row).
  - Contingent move-only: `persistence/autonomy/halt_rows.py`.
  - Tests: `tests/unit/test_autonomy_engine.py`, `tests/unit/test_autonomy_units.py`.
- **RED first.**
  - `tests/unit/test_autonomy_engine.py::test_verdict_acceptance_rules`
  - `…::test_verdict_subject_sha_must_match_row`
  - `…::test_verdict_accepted_after_attest`
  - `…::test_verdict_validity_ceiling`
  - `…::test_halt_reason_class_map_is_exact`
  - `…::test_mirror_read_failure_is_integrity`
  - `…::test_autonomy_exec_keys_disjoint_from_halt_prefixes`
  - `…::test_intraday_engine_is_restrictive_only`
  - `…::test_drill_inject_mapped_only_in_clause`
  - `…::test_candidate_cap_and_mint_rate`
  - `…::test_promotion_requires_reconciled_state`
  - `…::test_demotion_never_requires_policy_and_is_immediate`
  - `…::test_engine_refuses_when_unpinned`
  - `…::test_attest_cites_required_kinds_and_caps_validity`
  - `…::test_demand_file_written_on_first_restrictive_failure`
  - `…::test_promote_refused_when_promote_enabled_false`
  - `tests/unit/test_autonomy_units.py::test_engine_units_carry_no_operator_env_or_venue_env`
  - `…::test_engine_timers_staggered_150s_after_producer`
  - `…::test_intraday_schedule_has_two_runs_in_launch_window`
  - `…::test_engine_runtime_bounds_end_before_launch`
- **GREEN.**
  - All pass.
  - `test_code_identity_pins_cover_import_closure` passes with the new engine pin.
  - The engine closure excludes `breezy.app`, `breezy.runtime.trade_supervisor*` and `breezy.adapters.*.exec.client` (asserted).
- **Activation.** The units are installed at WP10 stage S, after WP3 filing, pointing at the shadow root. Technical reason for not activating immediately: the engine needs the filed policy block, and Y7 makes any production-root row binding on the node.

### AUT-5.WP5 — Node: `RegistryWatchActor`, `entry_veto` slot, HWM, registry boot path, Y7, SLO harness

- **Scope.** §3.4.
- **Files.**
  - New: `src/breezy/strategy/autonomy/registry_watch_actor.py`.
  - Modified: `src/breezy/strategy/forecast_quantile_ladder/strategy.py` (`__init__` keyword plus a `try_submit` line), `src/breezy/app/trade.py` (`run`, `_compose_forecast_quantile_ladder`), `src/breezy/runtime/settings.py`.
  - Tests: `tests/unit/test_registry_watch_actor.py`, `tests/contract/test_watch_actor_thread_contract.py`, `tests/integration/test_demotion_latency_slo.py`, `tests/unit/test_registry_boot.py`.
- **RED first.**
  - `tests/unit/test_registry_watch_actor.py::test_watch_actor_never_reads_projection`
  - `…::test_registry_hwm_refuses_regression`
  - `…::test_registry_unreadable_veto_clears_only_after_verified_read`
  - `…::test_attest_expiry_and_chain_staleness_veto_entries`
  - `…::test_attest_veto_armed_after_first_attest`
  - `…::test_engine_heartbeat_stale_vetoes`
  - `…::test_entry_veto_closed_before_first_tick_and_on_stale_tick`
  - `…::test_bad_demand_file_vetoes_venue`
  - `…::test_restrictive_commit_failure_sets_node_veto` (demand written by WP4's writer, L-42)
  - `…::test_transient_veto_writes_no_transition`
  - `…::test_alerts_undeliverable_veto` (journal fixture through AUT-6's writer once it lands; until then strict-xfail owned by AUT-6)
  - `…::test_timer_callback_never_raises`
  - `tests/contract/test_watch_actor_thread_contract.py::test_watch_actor_store_touches_stay_on_loop_thread` (with a negative control that touches the store from the timer thread and must raise)
  - `tests/unit/test_registry_boot.py::test_hand_relaunch_without_registry_source_refused`
  - `…::test_node_relaunch_rule_family_id_and_seq_prefix`
  - `…::test_halted_family_boots_entries_vetoed_exits_live`
  - `…::test_registry_unavailable_mints_no_permit`
  - `…::test_registry_veto_leaves_exit_seam_open`
  - `…::test_swap_cannot_exceed_daily_budget_across_namespaces`
  - `…::test_drill_fills_spend_venue_budget`
  - `…::test_entry_veto_precedes_submit_veto_in_try_submit`
  - `tests/integration/test_demotion_latency_slo.py::test_demotion_latency_slo`: the fake clock drives both paths. Node-local is ≤ 2 min. DetectorEvent → AUT-6 producer stub → intraday engine → watch tick is ≤ 15 min. A dead engine yields the heartbeat veto at ≤ `ENGINE_HEARTBEAT_STALE_S` + 60 s.
- **GREEN.**
  - All pass.
  - The existing `test_shadow_only_false_is_only_the_gate_output`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement` and `test_execution_egress_firewall_guard` pass **unmodified**.
- **Activation.** At the next 16:50Z LAUNCH after merge. With the source unset the actor is not composed, so it is a no-op until WP10 stage S sets `registry_shadow`.

### AUT-5.WP6 — Supervisor: resolve at LAUNCH, `build_child_env` at four sites, post-launch SWAP_CANCEL relaunch, §4.4 re-check, unit source

- **Scope.** §3.6.
- **Files.** `src/breezy/runtime/trade_supervisor.py` (`_do_launch`, `_do_relaunch_check`, the boot-retry spawn at `:1631`, the midday spawn at `:1982`, `resolve_sending_family_id`, `default_ports`); `src/breezy/runtime/trade_supervisor_core.py` (`DaySchedulerState` fields, `build_child_env`, `record_registry_resolved`); `deploy/systemd/breezy-trade-supervisor.service`. Tests: `tests/unit/test_supervisor_registry_launch.py`.
- **RED first.**
  - `tests/unit/test_supervisor_registry_launch.py::test_family_source_fixed_in_unit`
  - `…::test_child_env_built_from_resolved_family_at_every_spawn_site` (AST: every `ports.spawn(` call passes `env=build_child_env(...)`)
  - `…::test_child_env_touches_only_three_keys`
  - `…::test_registry_unavailable_retries_until_window_close_no_fallback`
  - `…::test_post_launch_swap_cancel_restores_incumbent`
  - `…::test_ambiguous_intent_cancels_swap_not_incumbent_launch`
  - `…::test_midday_relaunch_keeps_latched_family`
  - `…::test_self_check_keys_on_resolved_family`
  - `…::test_registry_shadow_logs_agreement_and_spawns_env_family`
- **GREEN.**
  - All pass.
  - `tests/unit/test_trade_supervisor.py`, `test_ct08_supervisor_contract_surface.py`, `test_trade_supervisor_core_r32.py` and `test_ct13_supervisor_crash_readopt.py` pass unmodified.
- **Activation.** Supervisor code loads once (memory note `supervisor-changes-need-a-supervisor-restart`), so a supervisor restart is needed in 01:00–16:40Z (`KillMode=process` keeps the node). The unit file is symlinked into the repo (memory note `supervisor-unit-is-symlinked-into-the-repo`), so the `BREEZY_FAMILY_SOURCE` line is parked on a branch until the gate passes. The code merge itself activates at the next supervisor restart, with the source still unset. That is behaviour-identical: `build_child_env` without registry source equals `dict(os.environ)` plus the ceiling, which the RED test pins.

### AUT-5.WP7 — `breezy-trade-relaunch`

- **Scope.** §3.7.
- **Files.** New: `src/breezy/runtime/trade_relaunch_cli.py`. Modified: `trade_supervisor.py` (`Phase.RELAUNCH_REQUEST` handler), `trade_supervisor_core.py` (phase, budget), `pyproject.toml`. Docs: `deploy/systemd/README.md` runbook section replacing the hand `systemd-run` recipe. Tests: `tests/unit/test_trade_relaunch_helper.py`.
- **RED first.**
  - `tests/unit/test_trade_relaunch_helper.py::test_helper_accepts_no_family_or_env_arguments`
  - `…::test_request_refused_inside_launch_window`
  - `…::test_request_refused_when_intent_open`
  - `…::test_request_refused_when_registry_disagrees`
  - `…::test_request_spawns_with_build_child_env_and_permit_ceiling`
  - `…::test_request_budget_three_per_day`
  - `…::test_helper_never_reads_proc_environ` (AST)
  - `…::test_request_outcomes_alert_through_delivery_proof`
- **GREEN.** All pass, and the WP6 suite is still green.
- **Activation.** At the same supervisor restart as WP6.

### AUT-5.WP8 — Dead-man, `breezy-registry-hwm-reset`, `breezy-registry-verify`

- **Scope.** §3.8.
- **Files.** New: `src/breezy/runtime/autonomy_deadman.py`, `registry_hwm_reset_cli.py`, `registry_verify_cli.py`; `deploy/systemd/breezy-autonomy-deadman.{service,timer}`. Modified: `pyproject.toml`. Tests: `tests/unit/test_autonomy_deadman.py`, `tests/unit/test_registry_hwm_reset.py`.
- **RED first.**
  - `tests/unit/test_autonomy_deadman.py::test_deadman_critical_past_heartbeat_stale`
  - `…::test_deadman_critical_past_chain_horizon`
  - `…::test_deadman_ok_line_when_fresh`
  - `…::test_deadman_own_lock_not_engine_or_studies`
  - `tests/unit/test_registry_hwm_reset.py::test_hwm_reset_cli_journals_alerts_and_chains`
  - `…::test_hwm_reset_refuses_with_live_node`
  - `…::test_hwm_reset_refuses_non_prefix_chain`
- **GREEN.** All pass.
- **Activation.** The dead-man timer is enabled at WP10 stage S, against the shadow root first.

### AUT-5.WP9 — Lineage-policy allowlist widening (one reviewed row)

- **Scope.** `live_orders_gate.py` gains `_LINEAGE_POLICY_ALLOWLIST: Final[frozenset[tuple[str,str,str]]]`, a literal-only frozenset with **exactly one row**: `("pm_us_crh_fq_v1", "RULING_autonomy_promotion_policy_v1_<date>", "<filed sha256>")`.
  - `live_orders_authorized` accepts a child `<root>_r\d{4}` only when its `live_orders_ruling` equals the lineage row's ruling id and the root matches, reusing the existing re-hash code.
  - A root keeps its own `_LIVE_ORDERS_ALLOWLIST` triple (contradiction X1).
  - `LiveOrdersReason` and `_REFUSES_BOOT` gain no new member: a child failure reuses `not_allowlisted`.
- **Files.** `src/breezy/persistence/live_orders_gate.py`. Tests: `tests/unit/test_fq_live_orders_gate.py` (additions only), `tests/unit/test_lineage_policy_allowlist.py`.
- **RED first.**
  - `tests/unit/test_lineage_policy_allowlist.py::test_lineage_policy_allowlist_is_literal_only`
  - `…::test_lineage_policy_allowlist_has_exactly_one_row`
  - `…::test_child_requires_lineage_triple_and_policy_ruling`
  - `…::test_child_with_operator_ruling_refused`
  - `…::test_root_keeps_own_ruling`
  - `…::test_tampered_policy_ruling_refuses_child`
- **GREEN.** All pass. Every existing test in `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py` and `test_live_orders_ruling_deploy_copy_matches_evidence.py` passes unmodified.
- **Activation.** At the first LAUNCH that resolves a child, which is the drill (WP10 L2). Merged only after WP10 L1 is clean. Technical reason: until then no child exists, and this ordering keeps the widening's blast radius at zero for the restrictive-only stage.

### AUT-5.WP10 — Staged activation (shadow → live restrictive → live widening) and live proof

| Stage | Entry condition | Actions (coordinator-run; reversible) | Exit criterion |
|---|---|---|---|
| **S (shadow)** | WP1–WP8 merged, full gate green after each merge; WP3 filed | Install the engine and dead-man units with `--registry-root %h/.local/share/breezy/registry-shadow`; run `breezy-autonomy-engine@bootstrap` against the shadow root; supervisor unit `BREEZY_FAMILY_SOURCE=registry_shadow` (branch-parked until the gate passes, then a restart in 01:00–16:40Z). The watch actor runs in shadow and logs `entry_veto_shadow reason=…`; it never refuses. | ≥ 5 trading days. Each day has: an ATTEST row in the shadow chain, heartbeat age ≤ 1800 s at every dead-man run, zero `registry_resolve_shadow agree=false`, every `entry_veto_shadow` explained in the stage log, and one shadow DEMOTE produced through the real producer → intraday → watch path from a shadow-root drill marker (a shadow DEMOTE never affects trading). |
| **L1 (live restrictive)** | S exit met | Supervisor restart with `BREEZY_FAMILY_SOURCE=registry`, then `breezy-autonomy-engine@bootstrap` against the **production** root before the next LAUNCH. The units are repointed to the production root. `alerts_undeliverable` is enabled only after AUT-6's first `delivered=true` canary row (Z5). | ≥ 3 trading days. The node log shows `registry_resolved family=pm_us_crh_fq_v1 seq=<n>` at each LAUNCH, ATTEST is daily, and there are zero unexplained vetoes. |
| **L2 (live widening)** | L1 exit; WP9 merged; AUT-7 rollback selector merged; AUT-2 RECONCILIATION verdicts live; AUT-6 `drill.inject` detector live; zero strict-xfail markers in AUT-5 test files | The drill clause window is active; the engine executes §3.10 with no human step. | The §6 artefacts are present. |

- **Rollback of activation.** Unset `BREEZY_FAMILY_SOURCE` with a supervisor restart. This is valid only before any production-root row exists, because Y7 then binds. After L1, the reversal is `breezy-registry-hwm-reset` plus a reviewed commit, announced with a one-line heads-up (Pre-Auth floor).
- **Close step.** Update memory `hand-relaunch-mechanics` to point at `breezy-trade-relaunch`; record a lesson if any stage diverged.

## 5. Association

**Consumed.**

| From | Contract | What AUT-5 needs | Needed by |
|---|---|---|---|
| ARCH | C5 amendments | X1 (root rulings), X2 (genesis BOOTSTRAP rows), X7 (`registry_shadow` value) accepted into ARCH Rev 5 | before WP1 merge |
| AUT-2 | C4 `RECONCILIATION` (detector `reconciliation.net_position`), C4 `HEALTH` (`health.label_lag`), C2 admissible labels (for `live.drawdown`) | Daily verdicts with `valid_until_ns − produced_at_ns ≤ 26 h` | L2 (§4.4 and ATTEST) |
| AUT-4 | C4 `OFFLINE_CHALLENGER`, `FORWARD_SHADOW`, `LIVE_SEQUENTIAL` (`live.sequential`, `live.kill_clock`, `live.drawdown`), the feasibility record | The measured qualifying station-days per day, replacing 4.55 in the ruling (a lower value keeps `promote_enabled=false`). **Ownership of the `live.drawdown` producer is assigned to AUT-4 here; ARCH names no producer (X6).** | L1 for restrictive; never needed for the drill |
| AUT-6 | `deliver_with_proof` (`runtime/alert_delivery.py`), the delivery journal, the canary, the intraday producer `*:00/5`, the `drill.inject` detector, every DRIFT/HEALTH id in §3.9 | Exact detector ids, or a joint DRAFT revision | S (producer and API); L2 (`drill.inject`) |
| AUT-1 | C1 `EntryVeto` writer bound to `on_veto_transition`; `health.capture_join` | The callback signature `(reason: VetoReason, cleared: bool) -> None` | L1 |
| AUT-3 | C3 candidates under `derived/artefacts/` | `lineage_root_family_id ∈ policy.lineage_roots` | none for the drill |
| AUT-7 | `engine.rollback.propose(fold) -> Proposal \| None` implemented inside the engine closure (pinned); the AUT-7b drill steps | Rollback-target selection and failed-rollback → HALT | L2 |

**Provided.**

| To | Contract | Interface |
|---|---|---|
| all | C5 | `RegistryReader`, `fold`, `resolve_sending_family`, `breezy-registry-verify` |
| AUT-1 | C5 → C1 | `fold(...).drill_episode(family, ts_ns)` and `ResolvedFamily.registry_seq` for record stamping |
| AUT-7 | C5 write API | `RegistryStore.append` reached only through the engine process and lock; the ROLLBACK and SUPERSEDE validation in `transitions.py` |
| AUT-6 | veto surface | `VetoReason` enum, `on_veto_transition`, `NODE_LOCAL` ids fixed to ENTRY_VETO |
| AUT-4 | policy | `PolicyBlock.k_max`, `alpha_total`, `forward_shadow.*`, and `lineage_counters.candidates_evaluated` (read-only) |

**Order and parallelism.**
- **Serial:** WP1 → WP2 → (WP4 ∥ WP5 ∥ WP6 ∥ WP8) → WP7 (after WP6) → WP10 S → L1 → WP9 → L2.
- **Parallel:** WP3 runs alongside WP1–WP8. It is a document plus calibration and must be filed before S.
- `app/trade.py`, `settings.py` and `trade_supervisor*.py` are touched only by AUT-5 WPs (ARCH §5.1). WP5 and WP6 touch disjoint files, so they run in parallel in separate worktrees, each fast-forwarded onto the feature branch first (memory note `agent-worktrees-start-stale`).

## 6. Live-proof protocol

- **Artefacts proving score 3.**
  1. `~/.local/share/breezy/evidence/registry/registry_polymarket_us_<D-1..D+4>.jsonl`, together containing MINT, DRILL_ADMIT, DRILL_PROMOTE + SUPERSEDE, ACTIVATE, DEMOTE (with `cause_verdict_ids` naming a `drill.inject` verdict), RESUME, ROLLBACK + SUPERSEDE, ACTIVATE. Every row has `decided_by="engine"`, a pinned `engine_code_sha`, the policy sha and `drill=true` where it applies.
  2. `breezy-registry-verify --venue polymarket_us` output `chain_ok=True export_prefix_ok=True`.
  3. Node logs `~/.local/share/breezy/logs/breezy-trade-<stamp>.log`:
     - D: `registry_resolved family=pm_us_crh_fq_v1_r0001`, `boot_family id=pm_us_crh_fq_v1_r0001`, `fq_live_orders … ruling=RULING_autonomy_promotion_policy_v1_…`.
     - D+1: `entry_veto reason=registry_halted` within ≤ 15 min of the verdict's `produced_at_ns`.
     - D+3: `entry_veto_cleared reason=registry_halted`.
     - D+4: `registry_resolved family=pm_us_crh_fq_v1` with an artefact sha equal to D−1's root sha.
  4. `~/.local/share/breezy/evidence/alerts/delivery_<date>.jsonl` with `delivered=true` for every `AUTONOMY_TRANSITION` alert.
  5. `git log --since=<D-1> -- deploy/ src/` showing no commit touching the registry, manifests, rulings or units between D−1 15:00Z and D+4 17:10Z (no human or agent commit in the loop).
- **Where.** The merged evidence index `docs/evidence/AUT-5_live_proof_<date>.md`, written after the drill. It cites paths, log lines and SHAs. It is never a self-score: an independent reviewer scores it.
- **ETA.**
  - Build: WP1 ≈ 6 working days (to about 2026-10-12); WP2 + WP4–WP8 ≈ 8 days in parallel (to about 2026-10-21); WP3 filing about 2026-10-17.
  - Stage S: 5 trading days, about 10-22 to 10-27. Stage L1: 3 trading days, about 10-28 to 10-30. Drill D−1 = 10-31 to D+4 = 11-05.
  - **Earliest live proof 2026-11-05.** **Planning date 2026-11-19** (two weeks of slack for upstream AUT-2, AUT-6 and AUT-7 readiness, which are on the critical path through §4.4 and the drill).
  - **Hard bound: before 2027-01-25.** A KILL firing TERMINAL first freezes the fq_v1 lineage, and the drill then becomes impossible until a reviewed new root exists.
- **Fills.** The drill transitions need no fills. The ≈ 5 fills/day rate matters only for the AUT-2/AUT-4 windows. Drill fills carry `drill=true`, spend the venue daily budget (Z18) and never count toward any n.
- **Natural events.** A natural restrictive event (for example `reconciliation.net_position` FAIL) also counts as DEMOTE evidence if one occurs. None is required.
- **Evidence class.** **"Machinery proven, edge unproven."** `promote_enabled=false`, so no edge-based PROMOTE is claimed. PROMOTE is demonstrated through DRILL_PROMOTE, as ARCH §7 provides.

## 7. Score-3 verification checklist

| Criterion | Exact check |
|---|---|
| (a) unattended, no commit in the loop | The §6 `git log` command shows no commit touching `deploy/`, `src/` or the units between D−1 15:00Z and D+4 17:10Z. `journalctl --user -u 'breezy-autonomy-engine@*' --since <D-1>` shows only timer-started runs. Every chain row has `decided_by=engine` (`breezy-registry-verify … --rows`). |
| (b) family-agnostic, cannot send without it | `scripts/ci/run_tests_no_egress.sh tests/unit/test_autonomy_plugins.py::test_family_plugin_exact_set tests/unit/test_registry_resolver.py::test_registry_champion_requires_live_orders_gate_for_every_kind tests/unit/test_registry_boot.py::test_hand_relaunch_without_registry_source_refused` all pass. Unit line `Environment=BREEZY_FAMILY_SOURCE=registry` is present in `deploy/systemd/breezy-trade-supervisor.service`. |
| (c) fails closed | `…::test_registry_unavailable_mints_no_permit`, `test_entry_veto_closed_before_first_tick_and_on_stale_tick`, `test_bad_demand_file_vetoes_venue`, `test_registry_unavailable_retries_until_window_close_no_fallback` pass. |
| (d) detected and alerted with delivery proven | Delivery journal rows `delivered=true` for `AUTONOMY_TRANSITION` on D+1 (DEMOTE, severity CRITICAL); `test_critical_alerts_use_delivery_proof` passes with no xfail; dead-man journal line `deadman ok` every 30 min across the drill. |
| (e) RED→GREEN in the gate | RED→GREEN logs per WP kept in the PR bodies. `scripts/ci/run_tests_no_egress.sh` exits 0 on the merge commit. `/usr/bin/grep -rn "xfail(strict=True" tests/unit/test_autonomy_cross_area.py tests/unit/test_registry_watch_actor.py` returns 0 lines. `.venv/bin/lint-imports` prints "0 broken". |
| (f) live proof | The §6 artefacts 1–4 exist. The D+1 node-log veto timestamp minus the verdict `produced_at_ns` is ≤ 900 s. The D+4 resolved artefact sha equals the D−1 root sha. |
| Envelope invariants | `test_operator_control_assignment_scan`, `test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`: `git diff <pre-AUT-5>..HEAD -- <these files>` is empty. |

## 8. Risks and failure modes

| Risk | Mitigation |
|---|---|
| **Statistical capacity** (≈ 5 fills/day; forward n_min 841 cannot be reached before the KILL) | `promote_enabled=false` is computed, not assumed (§3.9, `test_promote_disabled_when_eta_after_kill`). The live proof rests on the drill, with the evidence class stated. |
| **KILL 2027-01-25** fires TERMINAL before the drill | Planning date 11-19 leaves more than 9 weeks of margin. If the KILL fires first, the area reports "blocked: lineage frozen", never a fudged proof. |
| **Memory on the 30 GiB host** | Engine units `MemoryMax`: 1G daily, 512M intraday and prelaunch, 128M dead-man; ≤ 2G total including the drawdown calibration (run once, outside 01:00–04:30Z). The watch actor reads only rows above its HWM, so it stays O(new rows). |
| **Shared venv** | Never `uv`/`pip`; the exact interpreter in every brief (L-51); console scripts are added via `pyproject.toml` but installed only by the coordinator's existing editable install path. Any reinstall is flagged as a production change. |
| **Concurrent agents** | WP5 and WP6 run in separate worktrees with disjoint files; no `git stash` (hook-blocked); per-agent scratchpads; the full gate after every merge. |
| **Pin churn** (every helper edit forces a pin bump) | The engine closure is kept narrow (asserted exclusions, contingent `halt_rows.py` move). Pins are append-only (Z9). |
| **Supervisor unit is symlinked** | Activation lines are branch-parked until the gate passes (WP6, WP10). |
| **False-positive DRIFT freezes a lineage** | Accepted (ARCH Z20). Recovery is a reviewed new root. MODEL-class detectors are daily, not tick-level. |
| **Promotion starvation** (AMBIGUOUS intent at 16:45Z) | The drill can slip a day. AUT-2 measures the rate (Z19), and §4.4 is never relaxed. |
| **Shadow stage blind spot** (shadow vetoes never enforce) | Bounded to ≥ 5 days, with an exit criterion that requires a shadow DEMOTE through the real path. The L1 stage then enforces restrictive-only before any widening. |
| **Request-file relaunch abuse** | It can only relaunch the resolved family and only at a ≤ 3/day budget, outside the launch window. It never widens. |
| **Detector-id mismatch across blind plans** | §5 makes the ids part of the ruling's peer review. `test_detector_map_covers_required_classes` and engine acceptance (unknown id → ERROR, alert) fail loudly, never silently. |

## 9. Binding-constraint compliance

- **Nautilus immutable:** only native extension points are used (`Actor`, `clock.set_timer`, the `try_submit` guard slot, `Order.tags` untouched). Nothing is patched.
- **Operator caps:** never read, assigned or derived. `test_autonomy_never_reads_or_writes_operator_controls` and the existing `test_operator_control_assignment_scan` are unmodified. The drawdown is cost-normalised from labels. `build_child_env` touches only three non-cap keys. The relaunch helper never copies the environment.
- **`allow_short=False`:** untouched. No autonomy module writes strategy config.
- **NO-SEND firewall:** untouched. `test_execution_egress_firewall_guard` is unmodified. Autonomy egress is the `alerts.env` webhook only (`test_autonomy_alert_egress_not_widened`).
- **Master enablement and permit:** `BREEZY_TRADING_ENABLED`/`BREEZY_ORDERS_ENABLED` and permit minting are untouched (`test_autonomy_never_touches_enablement_permit_or_firewall`). The registry only selects among already-allowlisted families.
- **PREREG via ruling:** every threshold lives in the sha-pinned `autonomy-policy/v1` block of a filed ruling (WP3). The engine never computes new statistical semantics.
- **Safety tests never weakened; exact allowlists widened by one reviewed row:** `_LINEAGE_POLICY_ALLOWLIST` gets exactly one row (WP9, `test_lineage_policy_allowlist_has_exactly_one_row`). `_LIVE_ORDERS_ALLOWLIST` and `exit_gate` are unchanged.

## 10. Self-score

| Axis | Max | Score | Note |
|---|---|---|---|
| Fidelity | 20 | 18 | Every ARCH §10 obligation is mapped to a WP. Eight contradictions are stated rather than silently resolved (X1–X8). |
| Correctness | 20 | 17 | Code sites verified at `4b8347a6`. The feasibility formula reproduces the filed 592. Drawdown calibration is still to run. |
| Specificity | 15 | 14 | Modules, functions, units, timers, schemas and the full block are given. |
| Acceptance | 20 | 18 | RED tests are named for every §4.7 test. The checklist gives commands and lines. Upstream readiness stays a dependency. |
| Autonomy-safety | 15 | 14 | Restrictive-only staging; one allowlist row; no cap or environment exposure. |
| Reuse | 10 | 9 | Predicates, gate, bridge, halt readers and supervisor functions are reused. Two new builds are justified (C5 store, request-file relaunch). |
| **Total** | 100 | **90** | |

**Contradictions with ARCH Rev 4, for the reviewer (also listed in the return):**
- **X1.** The resolver refuses "a `live_orders_ruling` that is not the policy ruling", yet the BOOTSTRAP champion (and the ROLLBACK target) `pm_us_crh_fq_v1` names the operator ruling. Proposed fix: the policy ruling is required for `_rNNNN` children only; roots keep their committed `_LIVE_ORDERS_ALLOWLIST` triple.
- **X2.** The C5 transition table allows only `∅→SHADOW` for BOOTSTRAP, while ARCH Bootstrap seeds CHAMPION and RETIRED. Proposed fix: genesis-only rows from `BOOTSTRAP_SEED`.
- **X3.** G22 says mid-day relaunches reuse the child's environment. In fact all four spawn sites forward the supervisor's `os.environ` (`trade_supervisor.py:1289,1379,1631,1982`). The cited pickup site `trade_supervisor_core.py:884-895` is the `Phase` enum; the launch is `trade_supervisor.py:1209`.
- **X4.** `entry_guard` in `persistence` cannot import the adapter fill keys and decoder. Proposed fix: an injected `FillReader`.
- **X5.** The supervisor's "trigger the intraday pass" is replaced by a schedule guarantee (two intraday runs inside [16:50Z, 17:00Z)), so the supervisor makes no `systemctl` call.
- **X6.** ARCH names no producer for the drawdown verdict. Assigned to AUT-4.
- **X7.** The shadow stage needs `BREEZY_FAMILY_SOURCE=registry_shadow` and a shadow root, because Y7 binds on any production-root row.
- **X8.** With `RESUME_COOLDOWN_H=24` and a 15:30Z daily pass, the drill takes 5–6 trading days, not ARCH's implied 4. That still satisfies "at least 4".

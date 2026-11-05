# ARCH-0 seam A: persistence core build plan, r3

**Round.** r3, dated 2026-10-03. It revises r2 (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r2.md`) and resolves every finding in `reviews/ARCH-0-seamA-r2-security.md` (findings 1–11) and `reviews/ARCH-0-seamA-r2-architect.md` (findings 1–16). It follows the binding coordinator rulings A-R1 to A-R6 and A3-R1 to A3-R6 in `reviews/ARCH-0-r1-merged.md`. The disposition is in §R3.

**Basis.** Plan facts come from FROZEN ARCH Rev 9.2, sha256 `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`, re-hashed on 10-03, and from errata E-1 to E-13. E-14 is requested in §ERRATA-REQUEST. Code facts were checked on the tree at `d231497d` with codegraph, `sed` and read-only probes. The probes used `/home/jon/breezy/.venv/bin/python`, with scratch under `/tmp/claude-1000/a0r3/`. No repo file was written and no state was changed.

**Verified facts.** V1 to V10 come from r2. They were re-checked where they are used, and the corrections are marked.
- **V1.** `import breezy.domain.instrument_leg` loads 120 `nautilus_trader*` modules. The cause is `src/breezy/domain/__init__.py:16-53`.
- **V2.** On a scratch copy whose `persistence/__init__.py` imports nothing, `import breezy.persistence.live_orders_gate` loads 0 Nautilus modules and 15 `pyarrow*` modules. The chain is `family_manifest.py:88` → `mechanism_test_guard.py:14` (`import pyarrow.parquet`).
- **V3, re-verified.** The facade at `src/breezy/persistence/__init__.py:9-53` re-exports 20 `catalog` names.
  - All 22 `from breezy.persistence import X` statements in `src/`, `tests/` and `scripts/` import submodules.
  - No file contains `from breezy import persistence` or a bare `import breezy.persistence`.
- **V4.** On SQLite 3.50.4:
  - REPLACE bypasses `BEFORE DELETE` while `recursive_triggers=0`.
  - `ON CONFLICT DO UPDATE` fires the UPDATE trigger.
- **V5.** The data root is 0700. Repo files are 0664 under umask 0002.
- **V6.** In `src/breezy/runtime/trade_supervisor_core.py:37-44`: STOP_PRIOR 16:40, LAUNCH 16:50, SELF_CHECK 17:05, window end 17:00.
- **V7.** `src/breezy/adapters/polymarket_us/exec/client.py` has sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4` (re-hashed). It is pinned at `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:36`.
- **V8.** `live_orders_authorized` is at `src/breezy/persistence/live_orders_gate.py:130-189`. The ruling checks are at `:163-182`, and the `ruling_missing` message embeds an absolute path (`:175-177`). The permit check comes last (`:184-189`).
- **V9.** In `family_manifest.py`, `load_family_manifest` is at `:285`. Its prereg guard `if path.parent.exists():` is at `:293-294` and `read_bytes` at `:295`. The containment helper at `:262-282` resolves through `path.resolve().parent`.
- **V10.** `exec/client.py` has no `DELETE FROM` site and no `.delete(` site, so `fill_index/` keys are never pruned.
- **V11 (new; architect F3).** The probe is `/tmp/claude-1000/a0r3/trig.py`.
  - The r2 trigger `WHEN NEW.venue_seq <> (SELECT max(venue_seq) …)+1` **accepts `venue_seq=7` as a venue's first row**, because the max over zero rows is NULL.
  - The `COALESCE((SELECT max(venue_seq) FROM transitions WHERE venue=NEW.venue),0)+1` form refuses 7 and accepts 1, then 2. It refuses a gap (4 after 2) and accepts another venue's first row of 1.
  - `NOT NULL` refuses a NULL `venue_seq` before the trigger compares anything.
- **V12 (new; corrects r2 AC 12; architect F5).** The probe is `/tmp/claude-1000/a0r3/hj2.py`, a `mode=ro` reader with `query_only=ON`. Python 3.13 exposes `sqlite_errorname`.
  - A live writer holding the lock gives `OperationalError` `SQLITE_BUSY`.
  - A writer killed after its cache spilled leaves a hot journal (1,151,504 bytes), and the reader gets `SQLITE_READONLY_ROLLBACK`.
  - A writer killed before spilling leaves a journal that is not hot, and the reader returns the committed state.
  - **Busy and hot journal are therefore distinguishable.** r2's "cannot tell it from a writer mid-commit" is withdrawn.
- **V13 (new; security F7).** In `exec/client.py`:
  - The prefix is `FILL_INDEX_KEY_PREFIX = "exec/polymarket_us/fill_index/"` (`:399`, `:412`).
  - Every key site is `f"{FILL_INDEX_KEY_PREFIX}{instrument_id}"`. The write site is at `:4645`. The read sites are at `:2198`, `:2302`, `:3457`, `:4693` and `:4827`, plus `src/breezy/strategy/current_rung_hold/trial_day_latch.py:1385`.
  - `_read_fill_index` (`:4712-4729`) returns `[]` for an absent key and `None` for an unreadable one.
  - The ids come from `symbology.slug_to_instrument_id` (`src/breezy/adapters/polymarket_us/symbology.py:254`) and `no_leg_instrument_id` (`:277-286`). The probe printed `exec/polymarket_us/fill_index/<slug>.POLYMARKET_US` and `exec/polymarket_us/fill_index/<slug>^no.POLYMARKET_US`.
- **V14 (new; architect F12, security F9).** In `tests/unit/test_runtime_import_isolation.py`:
  - The helpers are at `:158-216`. `_entry_modules_from_pyproject_scripts` and `_entry_modules_from_systemd` are generic. `_entry_modules_from_scripts_importing_runtime` hard-codes `breezy.runtime` (`:192-216`).
  - They use the module constants `REPO_ROOT`, `PYPROJECT_PATH`, `DEPLOY_SYSTEMD_DIR` and `SCRIPTS_DIR` (`:55-60`).
  - The three sources give 12, 5 and 18 modules, 34 in their union. 39 `scripts/**` files import `breezy.persistence*`.
- **V15 (new; security F4).** Nautilus keeps arrow registrations in `nautilus_trader/serialization/arrow/serializer.py:75-78` (`_SCHEMAS`, `_ARROW_ENCODERS` and others). With today's facade, importing `breezy.persistence.live_orders_gate` registers 60 schemas and importing `breezy.app.trade` registers 68. The per-entry dump works (`/tmp/claude-1000/a0r3/dump.py`).
- **V16 (new; neither review caught this).** r2's contract (b), "core list ↛ pyarrow with `allow_indirect_imports=false`", **cannot be met**. `resolver`, `replay`, `family_bytes` and `registry_store` import `family_manifest`, which statically reaches pyarrow (V2). r3 splits the contract (AC 1).
- **V17 (new; L-54 pin search).** `tests/unit/test_mypy_ratchet.py:352-364` sets per-package error ceilings, including `"tests/support": 2`. A ceiling the code falls below **fails** with "lower the ceiling". The other two files that reference `tests/support`, `test_probe_containment.py:63` and `test_real_tree_write_guard.py:17`, import other support modules and pin no file list.
- **V18 (new).** `assert_prereg_directory_eligible` (`src/breezy/persistence/mechanism_test_guard.py:27-45`) returns silently when the directory is absent. That makes the `exists()` guard at `family_manifest.py:293` redundant for absence.
- **V19 (correction).** The settings family pattern is `src/breezy/runtime/settings.py:114`, `^[a-z0-9_:]+$`; r2 cited `settings.py:115`. The trial-day-latch pattern is `trial_day_latch.py:301`, `^[A-Za-z0-9_-]{1,64}\Z`. Their intersection is `[a-z0-9_]{1,64}`.
- **V20 (new).** `pm_us_crh_v4` and `pm_us_crh_cont` are both `continuous_rung_hold` with `density_artefact_sha256 = 247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65`. This is the E-14 collision.
- **V21 (new).** ARCH C5 places the following:
  - the `ResolvedFamily` fields at `:557-558`;
  - Y6 (root from the child regex must equal the row's `lineage_root_family_id`) at `:560-563`;
  - the shadow in-memory HWM at `:576-579`;
  - the root exemption at `:605-608`;
  - the HWM and Y4 mid-chain re-check at `:618-624`;
  - the HWM-reset CLI at `:626-634`, whose step 6 sets the node HWM.

  AUT-5 r7 places the WP9 RED list at `:927`, the L1 cut-over at `:937`, the watch actor at `src/breezy/strategy/autonomy/registry_watch_actor.py` (`:122`), and `_tick_once` at `:420-423`.

**Residual risk, stated once.** Pins, chain, HWM, exports and the DB are all one same-uid trust domain (ARCH C5 residual; R14). The only external anchors are four:
- the committed allowlists;
- the committed `deploy/families/<id>.json` bytes (A3-R1);
- `live_orders_gate`;
- the reviewed code in `pins.py` and `transitions._ADMISSION_IMPLEMENTED`.

Every control below exists so that a row, a rebinding or a missing verifier cannot bypass one of these anchors.

## Acceptance Criteria (numbered, testable)

1. **Package and contracts (V16).** `src/breezy/persistence/autonomy/` holds exactly the modules in the File-by-File Plan. `cd /home/jon/breezy && .venv/bin/lint-imports` prints "N kept, 0 broken". N includes three new contracts, all with `allow_indirect_imports=false`:
   - (a) `breezy.persistence.autonomy ↛ breezy.adapters` (ARCH §4.7).
   - (b) **The core list ↛ `nautilus_trader`, `breezy.domain`.** The core list is the package plus the 27 modules `canonical, wire, single_read, paths, pins, veto, plugin, closure_manifest, closure, schemas, stage_policy, verdict, lineage, label_schema, demand, drill_marker, rollback_journal, fold, transitions, chain, family_bytes, registry_store, hwm, replay, net_position, entry_guard, resolver`.
   - (c) **The pyarrow-free core ↛ `pyarrow`.** This is the core list minus `PYARROW_REACHING = {label_schema, family_bytes, registry_store, replay, resolver}`.

   `include_external_packages = true` is already set (`pyproject.toml:72`).
2. **Module classification.** `test_every_autonomy_module_is_classified` places every module in exactly one set: contract (b)'s `source_modules`, parsed from `pyproject.toml`, or `NAUTILUS_PERMITTED` (the AUT-1 `capture_*` set from E-12, empty at ARCH-0). It also asserts that (b) − (c) equals `PYARROW_REACHING` exactly. A planted module serves as the positive control.
3. **Runtime import weight.** `test_autonomy_core_modules_nautilus_free_at_runtime` imports each core module in a fresh subprocess and asserts 0 `nautilus_trader*` modules and 0 `breezy.domain*` modules. It allows `pyarrow*` only for the five `PYARROW_REACHING` modules.
4. **Import-free `persistence/__init__.py`.** The 20-name facade is deleted. The precedent is NOTIFIER-IMPORT-ISOLATION (`src/breezy/runtime/__init__.py:15-25`), and the facade has zero consumers (V3).
   - **Permanent tests:**
     - `test_persistence_init_has_no_import_nodes`;
     - `test_persistence_has_no_facade_consumers` (AST over `src/`, `tests/` and `scripts/`; it also refuses `mock.patch("breezy.persistence.<facade name>")`);
     - `test_persistence_entry_module_imports_cleanly[<entry>]` (one fresh process per entry: pyproject scripts, systemd `ExecStart`, and `scripts/**` importing `breezy.persistence`; budget ≤ 60 s in total, measured in WP-1a).
   - **One-time WP-1a evidence (architect F10c, security F4), kept in the merge evidence log and not in the gate:**
     - (i) grimp reachability. For every entry, the set of reachable `register_arrow` modules (`domain/*.py`, `monitor_records.py:249`, `tape_records.py:629-637`) is identical with and without a simulated `persistence → catalog` edge.
     - (ii) the runtime arrow registry. For every entry, a fresh process imports the entry and dumps the sorted `serializer._SCHEMAS` keys (V15). This runs on the old tree and on a scratch tree with the new `__init__`, and the two sets must be equal.

     Any entry that differs is listed with a reviewed reason, or WP-1a stops.
5. **Explicit serialisation.** Every wire record has `to_wire() -> dict` and `from_wire(payload) -> Self`. The records are: C2 schema, `lineage/v1`, `root/v1`, `refit_run/v1`, `verdict/v1`, the C5 row, the export trailer, `demand/v1`, `drill_marker/v1`, `journal/v1` and `Hwm`.

   `wire.parse_json_exact` refuses duplicate keys (`object_pairs_hook`), NaN and Infinity (`parse_constant`), and any float token (`parse_float`). It also refuses missing or unknown keys, wrong types, bool-as-int, and a `schema` value outside `ACCEPTED_SCHEMAS`. All refusals raise `WireRefused(reason: WireRefusalReason)`, a closed StrEnum. An AST test bans `dataclasses.asdict` and `astuple` in the package.
6. **Canonical bytes.** `canonical_json(x)` is `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False)`, encoded as UTF-8.
   - `CanonicalTypeError` is raised on a non-`str` key, a `float`, a lone surrogate, or any type outside `None|bool|int|str|list|tuple|dict|Decimal`.
   - `decimal_str(d)` refuses NaN and infinities. It refuses more than `DECIMAL_MAX_DIGITS = 38` digits and `|adjusted()| > DECIMAL_MAX_ABS_EXPONENT = 18`. Every zero is written as `"0"`; any other value is written as `format(d.normalize(), "f")`.
   - Golden values: `-0`→`"0"`, `0E-10`→`"0"`, `1E+2`→`"100"`, `1.50`→`"1.5"`, plus three record goldens.
7. **Single read and write, TOCTOU-free.**
   - `open_root(root)` takes an absolute path and opens it `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`.
   - `walk_dirs(rootfd, rel, *, create, mode=0o700)` runs one `openat` per component with `O_DIRECTORY|O_NOFOLLOW`. It refuses `""`, `.`, `..`, NUL and `/`. Each component must pass an `fstat` S_ISDIR check with `st_uid == geteuid()`.
   - `read_once_at(dirfd, name, *, max_bytes, policy)` opens `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC` and requires S_ISREG and the owner uid. Under `ReadPolicy.STRICT` it refuses group-write and other-write bits. It reads `max_bytes+1` to detect oversize.
   - `ReadPolicy.REPO` drops the mode check for git files (V5); the sha binding supplies their integrity.
   - `write_once(path, data, *, root, mode)`:
     - **First** runs `read_once_at` on the destination. Equal bytes → `EXISTS_EQUAL`, with no temp file created, so this works in a 0500 directory (E-14 rule 6). Different bytes or a symlink → `EXISTS_DIFFERENT`. ENOENT → it proceeds.
     - Then it creates `.tmp.<secrets.token_hex(8)>` through the parent dirfd with `O_CREAT|O_EXCL|O_NOFOLLOW`, runs `fchmod`, writes, `fsync`s, and calls `os.link(src_dir_fd=, dst_dir_fd=, follow_symlinks=False)`.
     - EEXIST at link time re-compares through `read_once_at`.
     - EPERM, EXDEV, EOPNOTSUPP and EMLINK give `SingleReadRefused(LINK_UNSUPPORTED)`. There is never a rename fallback.
     - The temp file is always unlinked and the directory fd `fsync`ed.
   - `replace_atomic` follows the same pattern with `os.replace` through dirfds.
   - AST tests: these are the only `os.link`, `os.replace` and write-mode `open` sites. Every ARCH-0 reader uses them, except one **named, reviewed exemption**: `live_orders_gate._verify_ruling_file`, a move-only extraction that keeps `resolve()` + `read_bytes()` (architect F15).
8. **Store DDL.** `transitions` has exactly the AUT-5 r7 §3.2 column set (`AUT-5-promotion-demotion_plan_r7.md:138`), with `venue` and `venue_seq` declared `NOT NULL`, plus `UNIQUE(venue, venue_seq)` and `UNIQUE(transition_id)`.
   - `BEFORE UPDATE` and `BEFORE DELETE` triggers raise `RAISE(ABORT,'append-only')`.
   - The `BEFORE INSERT` trigger refuses an existing `NEW.seq`, a duplicate `(venue, venue_seq)`, and `NEW.venue_seq IS NOT COALESCE((SELECT max(venue_seq) FROM transitions WHERE venue=NEW.venue),0)+1` (V11).
   - `meta(schema='registry/v1')`, `PRAGMA user_version=1`, `application_id=0x42524759`.
   - The directory is 0700 and the file 0600.
   - The derived caches (`families`, `projection`, `lineage_counters`) are **not** created; they belong to AUT-5 WP4.
9. **Writer connection.** `isolation_level=None` with an explicit `BEGIN IMMEDIATE`. Pragmas: `journal_mode=DELETE`, `synchronous=FULL`, `recursive_triggers=ON`, `trusted_schema=OFF`, each read back by a test. An AST test bans `OR REPLACE`, `OR IGNORE`, `REPLACE INTO` and `executescript` in `registry_store.py`.
10. **Append path.** `RegistryStore.append(rows, *, expected_prior_seq, mode: WriterMode, now_ns: int)` delegates to the private `_append(..., stage=stage_policy.STAGE)`. Inside one `BEGIN IMMEDIATE`, in order:
    1. If every id is already present, it is a logged no-op. If only some are present, `PartialReplay`.
    2. `mode` must be a concrete `WriterMode`; `None` is refused.
    3. `KIND_MASK[mode]`.
    4. For each widening row: kind ∈ `stage.enabled_widening_kinds`, else `WideningNotEnabled`. Then kind ∈ `stage.admission_implemented`, else `AdmissionPending`.
    5. SHADOW→CHALLENGER PROMOTE → `NominationRequiresPolicy`. HWM_RESET → `RuleSetPending`.
    6. `|row.ts_ns − now_ns| ≤ ROW_TS_MAX_SKEW_S` (300), and `ts_ns` is monotone over the head.
    7. CAS: `max(venue_seq) == expected_prior_seq`.
    8. `transitions.validate(fold(prior), rows, mode=mode, now_ns=now_ns, stage=stage, manifests=family_bytes reader)`.
    9. Insert, then COMMIT.

    Any failure rolls back completely.
11. **Chain.**
    - The genesis is `sha256(b"registry/v1|"+venue)`.
    - `canonical_row` hashes every column except `seq`, `prev_transition_hash` and `transition_hash`, so `venue` and `venue_seq` are hashed (asserted).
    - `transition_id` hashes the C5 Y9 tuple without `expected_prior_seq`.
    - `verify_venue_chain(rows, venue)` requires `venue_seq` to run contiguously from 1 to n, every row to be on `venue`, monotone `ts_ns`, and unbroken hashes.
12. **Reader (V12; architect F5).** `RegistryReader(paths, *, busy_timeout_ms).read_venue_rows(venue, after_seq=0)` works as follows.
    - It opens `file:<percent-quoted>?mode=ro` with `query_only=ON` and `trusted_schema=OFF`, using one connection per call.
    - Inside one `BEGIN` it checks `meta.schema`, `user_version` and `application_id`, and that `sqlite_master` (type, name, sql) **equals** the DDL constants. It then selects an explicit column list ordered by `venue_seq`.
    - Failures raise `RegistryUnreadable(reason: UnreadableReason)`, a closed StrEnum:

      | Reason | Cause |
      |---|---|
      | `busy` | `sqlite_errorname` ∈ {`SQLITE_BUSY`, `SQLITE_LOCKED`} or one of their extended codes |
      | `hot_journal` | `SQLITE_READONLY_ROLLBACK` |
      | `schema_mismatch` | meta, `user_version`, `application_id` or `sqlite_master` differs |
      | `io` | `OSError`, `SQLITE_IOERR*` or `SQLITE_CANTOPEN*` |
      | `sqlite_error` | any other `sqlite3.Error` |

    - A hot journal is rolled back by the engine's next read-write open under `engine.lock` (AUT-5a).
13. **Validated kinds, plus the shared admissibility predicate.** `transitions.validate` is pure and implements every fold-decidable C5 rule for every kind:
    - V12 DRILL-row refusal while a non-DRILL cause stands;
    - DRILL_PROMOTE requires the champion sha; no drill over a HALTED incumbent; drill counters ≤ 1 per `DRILL_BUDGET_PER_VENUE_30D` (V15);
    - Z3 counting and `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY`;
    - RESUME needs every standing cause cleared, `RESUME_COOLDOWN_H`, and the RECOVERABLE_MODEL and RECOVERABLE_INFRA ceilings; ROLLBACK_FAILED resumes only under `trigger_cause_class`;
    - the five E-5 `drill_close_restore` conditions, at most 1 per venue per day;
    - d0 and `trial_id_prefix` at the first →CHAMPION row (ROLLBACK, RESUME and ROOT_ADMIT are exempt);
    - ROOT_ADMIT only when the venue has no sender, with `lineage_root_family_id == family_id`; BOOTSTRAP likewise (security F8);
    - the mint rate; BOOTSTRAP genesis and seed (E-6); ATTEST cadence; SWAP_CANCEL voids ⊆ pending;
    - the single-sender invariant at `now` and at the next LAUNCH;
    - HWM_RESET `carried_counters` ≥ export counters (B9).

    `_ADMISSION_IMPLEMENTED: Final[frozenset[Kind]] = frozenset()` lives in `transitions.py`.

    **New (architect F4):** `transitions.rows_admissible(rows, *, stage: StageView) -> RefusalReason | None` returns `widening_kind_not_enabled` or `admission_pending` for any row whose kind is outside the stage sets. It is the **only** place either set is compared against rows. `test_admissibility_predicate_has_one_home` is an AST test: outside `transitions.py`, `schemas.py` and `stage_policy.py`, no `src/` module reads `.enabled_widening_kinds` or `.admission_implemented`. `_resolve` must call `rows_admissible`, and the `[watch_actor]` half is carried to AUT-5a.
14. **Fold.** `fold(rows, venue, now_ns) -> FoldResult` is pure. It computes:
    - states, pending pairs, ACTIVATE in [16:40Z, LAUNCH), lapse at LAUNCH;
    - SWAP_CANCEL voiding, including the [LAUNCH, 17:00Z) post-launch void;
    - `demoted_for_cause`, `rollback_eligible`, `target_ineligible` and `terminal_frozen`; the venue INTEGRITY freeze; `drill_episode` intervals;
    - tallies charged on effect, with HWM_RESET `carried_counters` applied as floors;
    - the invariant of at most one {CHAMPION, HALTED} family per venue.

    `FamilyView` carries `origin: Literal["root","child"]` and `lineage_root_family_id`, both taken from the row that **introduced** the family. A BOOTSTRAP or ROOT_ADMIT row with `lineage_root_family_id == family_id` gives `root`; a MINT gives `child`. An AST test bans `time.time`, `time.time_ns`, `datetime.now`, `datetime.utcnow` and `time.monotonic` in the core list.
15. **Stage policy is frozen and cannot be constructed in `src/` (security F5; architect F14).**
    - The `StagePolicy` frozen slotted dataclass and the `StageView` Protocol live in `schemas.py`. `stage_policy.py` builds `STAGE: Final[StagePolicy]` once, through a private `_build()`, from `pins` and `transitions._ADMISSION_IMPLEMENTED`. There is no public `from_pins`. The import order is `schemas ← transitions ← stage_policy`, with no cycle (`test_autonomy_package_import_graph_is_acyclic`, AST).
    - `test_autonomy_policy_not_mutable_from_src` uses AST over `src/` to refuse each of the following. Each item has a planted positive control:
      - assignment, `setattr`, `delattr`, `__dict__`, `object.__setattr__`, `importlib.reload`, `mock.patch`, `monkeypatch`, and `globals()`/`vars()` writes that target `pins`, `stage_policy`, `transitions`, `live_orders_gate` or `family_manifest`;
      - rebinding a name imported from those modules;
      - **`StagePolicy(...)` construction, `dataclasses.replace(...)` or `copy.copy`/`deepcopy` of a `StagePolicy`, or `stage_policy._build`**, anywhere outside `stage_policy.py`;
      - references to `_append`, `_resolve`, `_replay_full`, `_lineage_policy_authorized` or `_verify_ruling_file` outside their defining module.

      Tests may construct fixture stages.
16. **HWM is tri-state, checked mid-chain, absence-refusing (security F2, F3; architect F2).** `hwm.py` provides `Hwm(venue, venue_seq, chain_head, export_seq)`, `HwmReading = HwmAbsent | HwmPresent | HwmUnreadable`, `REGISTRY_HWM_KEY_PREFIX = "autonomy/registry_hwm/"` and `hwm_key(venue)`.
    - **`hwm_reading_from_bytes(raw: bytes | None) -> HwmReading` is the only decoder.** `None` gives `HwmAbsent`; any decode or wire error gives `HwmUnreadable`. An AST test bans `HwmAbsent(` construction outside `hwm.py`.
    - `hwm_check(chain: VerifiedVenueChain, reading, *, newest_export_seq) -> RefusalReason | None` returns:
      - `hwm_unreadable` for an Unreadable reading or a foreign venue;
      - **`hwm_absent` for an Absent reading on any non-empty chain**. There is no genesis exception: the L1 cut-over writes the first HWM (binding note 6);
      - `hwm_regressed` when `hwm.venue_seq > head`, **or when `rows[hwm.venue_seq].transition_hash != hwm.chain_head` for any `hwm.venue_seq ≤ head`**, or when `hwm.export_seq > newest_export_seq`.
    - `next_hwm(chain, *, export_seq) -> Hwm` is the pure value that the node and tools write.
17. **Sending resolver.** `resolve_sending_family(*, venue, paths, repo_root, now_ns, hwm: HwmReading) -> ResolvedFamily | ResolverRefusal` delegates to `_resolve(..., stage, lineage_gate, hwm_mode=ENFORCE)`. It runs these steps in order:
    1. It refuses `paths_role_mismatch` when `paths` is a shadow root.
    2. It verifies the chain from genesis and checks the clock (`now_ns` is an int > 0 and ≥ head `ts_ns` − skew).
    3. It runs `hwm_check`.
    4. Exports: the exports directory is opened and listed. **A listing or open error, including a missing `evidence/registry/`, gives `export_unreadable`.** With no export file, `export_check = not_yet_due` only when `hwm.export_seq == 0` and `now_ns − genesis_ts_ns < EXPORT_FIRST_DUE_H`; otherwise `export_unreadable`. With an export, the export prefix is verified.
    5. `transitions.rows_admissible`.
    6. `replay_full`.
    7. More than one CHAMPION/HALTED family gives `engine_inconsistency`.
    8. **Root or child is decided from `FamilyView.origin`, never from the name (security F8).**
    9. **Root (A3-R1):** the manifest is read from `deploy/families/<family_id>.json` under `ReadPolicy.REPO` only; its sha must equal `row.manifest_sha256`, else `manifest_sha_mismatch`. The E-14 root record is checked. The root triple goes through `live_orders_authorized(..., permit_present=False)`, and only `reason == "permit_absent"` is accepted. `CHILD_FAMILY_ID_RE` is not consulted.
    10. **Child:** the manifest is read from `registry/families/<id>.json` (STRICT) with a sha check. `CHILD_FAMILY_ID_RE.fullmatch(id).group("root")` must equal `view.lineage_root_family_id`, else `child_root_mismatch` (ARCH Y6 consistency). There is §4.2 equality against the committed root (REPO) over `dataclasses.fields(FamilyManifest) − ALLOWLIST − {"manifest_sha256"}`, then `lineage_policy_authorized(child, view.lineage_root_family_id, repo_root)`, then d0 and the prefix at the first →CHAMPION row.
    11. Common to both: the manifest's `venue`, `composition_kind` and `family_id` must equal the row's; `LIVE_GATE_ROUTED_KINDS` is checked on the manifest's kind; the engine pins are checked; the artefact is read from `derived/artefacts/<model_class>/<sha>/artefact.json` (STRICT) and its sha must equal `row.artefact_sha256`.
18. **Shadow resolver (architect F2a).** `resolve_shadow_family(*, venue, paths, repo_root, now_ns) -> ShadowResolution | ResolverRefusal` runs `_resolve(..., hwm_mode=SKIP_SHADOW)`. It refuses `paths_role_mismatch` unless `paths` is an `AutonomyPaths.shadow(...)` root.
    - Every other check in AC 17 applies, including exports.
    - `ShadowResolution(family_id, state, registry_seq, chain_head)` is a separate frozen dataclass. It is not a subclass of `ResolvedFamily`, shares no base, and has no `family_bytes`, `entries_allowed`, `manifest` or artefact field.
    - `test_shadow_resolution_ignores_hwm_and_cannot_send` checks four things: it resolves an ATTEST-bearing chain with no HWM; `resolve_sending_family` on the same chain gives `hwm_absent`; `ShadowResolution` lacks every `ResolvedFamily`-only field; and an AST check finds `resolve_shadow_family` called from no `src/` module outside `SHADOW_CALL_SITES`, a literal set that is empty at ARCH-0. AUT-5a adds the supervisor shadow branch and the watch actor.
19. **`ResolvedFamily` carries the ARCH C5 pickup fields (architect F1).** The fields are:
    - `family_id`, `state: Literal[CHAMPION, HALTED]`, `entries_allowed: bool`, `origin`;
    - **`registry_seq: int`**, the verified head `venue_seq`, and **`chain_head: str`**;
    - `authorising_seq: int`;
    - **`family_bytes: FamilyBytes`**, which holds `manifest: FamilyManifest`, `manifest_raw: bytes`, `manifest_sha256`, `manifest_source: Literal["deploy","registry"]`, `artefact_raw: bytes`, `artefact_sha256`, and `artefact_store_relpath` (relative to the data root, `derived/artefacts/<model_class>/<sha>/artefact.json`);
    - `export_check: Literal["verified","not_yet_due"]`.

    It has no `enabled` field and no permit field. `test_resolved_family_carries_arch_c5_pickup_fields` pins the set (ARCH `:558`; AUT-5 r7 `:410`, `:441`, `:971`; AUT-1 r12 `:329`).
20. **Lineage-policy gate (WP-8a).** `live_orders_gate.py` gains:
    - `_LINEAGE_POLICY_ALLOWLIST: Final[frozenset[tuple[str,str,str]]] = frozenset()`;
    - `CHILD_FAMILY_ID_RE = re.compile(r"\A(?P<root>[a-z0-9_]{1,58})_r[0-9]{4}\Z", re.ASCII)`;
    - `_verify_ruling_file(repo_root, ruling_id, expected_sha256)`, a move-only extraction of `:163-182` with identical reasons and messages;
    - `lineage_policy_authorized(child, root_family_id, repo_root) -> LineagePolicyDecision(ruling_id, ruling_sha256)`, which delegates to `_lineage_policy_authorized(..., allowlist)`. It raises `LiveOrdersGateRefusedError` and uses existing `LiveOrdersReason` members only.

    `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py` and `test_live_orders_ruling_deploy_copy_matches_evidence.py` pass **unmodified**. **Coverage evidence (security F6):** the three refusal sites (`ruling_outside_evidence`, `ruling_missing`, `ruling_sha_mismatch`) reach 100% branch coverage under `test_verify_ruling_file_extraction_keeps_reasons_and_messages` before and after the extraction.
21. **`parse_family_manifest` split, proven byte-equivalent (security F6).** `parse_family_manifest(raw: bytes, *, path: Path, allow_draft: bool = False)` is `family_manifest.py:296-460` moved verbatim. `load_family_manifest` keeps `:293-295` verbatim, including the `if path.parent.exists():` guard, and then calls the new function. The work is three gated commits:
    - **WP-1b (unsplit code).** `tests/fixtures/family_manifest_golden/` holds the 7 committed `deploy/families/*.json`, their `artefacts/` files, and mutated invalid manifests. The corpus is **sized until coverage, not a number, says it is enough**. `expected.json` records, per input, either `(exception type, message with the path replaced by <PATH>)` or `(dump_family_manifest output, manifest_sha256)`. One case, `symlink_escape`, is built by the test inside a `tmp_path` copy (an artefact path whose subtree component is a symlink pointing outside), so no symlink is committed. **Gate:** `coverage run --branch` gives 100% of the lines and branches in `family_manifest.py:262-282` and `:285-460` under the corpus. The report is part of the merge evidence.
    - **WP-1c (split).** The same test passes unmodified.
    - **Callers.** `family_bytes` opens the source directory with `walk_dirs`. A missing directory gives `manifest_unreadable`; it is never skipped. It then **always** calls `assert_prereg_directory_eligible(dir)` before parsing. `test_autonomy_never_passes_allow_draft_true` is an AST test over `src/`.
22. **Entry guard (security F7; architect F8).**
    - `net_position.LegFill(leg: Literal["yes","no"], side: Literal["BUY","SELL"], qty: Decimal, ts_event_ns: int)` is frozen. `test_leg_fill_fields_frozen` pins the names and types.
    - `net_signed_qty(fills) -> Decimal`: YES BUY is +q, YES SELL −q, NO BUY −q and NO SELL +q. Any other value gives `UnknownSide`.
    - `entry_guard.leg_instrument_ids(base_slug, *, venue_suffix) -> tuple[str, str]` returns `<base><venue_suffix>` and `<base>^no<venue_suffix>`.
    - `FillReader` Protocol:
      - `open_intent_blocks() -> bool`;
      - `fill_index(instrument_id: str) -> tuple[str, ...] | FillIndexAbsent`;
      - `fill_record(venue_order_id) -> FillRow(order_side, cumulative_qty, ts_event_ns)`.
    - `rung_has_net_position(base_slug, *, reader, venue_suffix) -> GuardResult{HELD, FLAT, UNREADABLE}`:
      - Its whole body is inside `try / except Exception → UNREADABLE`.
      - Its **first** call is `open_intent_blocks()`; True gives UNREADABLE. The docstring states the deliberate **venue-global** scope: one stale OPEN or AMBIGUOUS intent vetoes every rung, a known availability trap, and the fail-closed choice.
      - An empty or invalid slug, or one containing `.` or `^`, gives UNREADABLE.
      - An existing empty index gives UNREADABLE. `FillIndexAbsent` reads as no fills.
      - `net != 0` gives HELD.
    - `guard_veto_reason` maps HELD and UNREADABLE to `rung_net_position_held` and FLAT to `None`.
    - **Key contract (V13), `test_fill_index_key_matches_exec_client_writer`:**
      - (i) For a corpus of real slugs, `leg_instrument_ids(slug, venue_suffix=".POLYMARKET_US")` equals `(str(slug_to_instrument_id(slug)), str(no_leg_instrument_id(slug)))`.
      - (ii) An AST read of the pinned `exec/client.py` asserts that `FILL_INDEX_KEY_PREFIX` is `STATE_KEY_NAMESPACE + "fill_index/"`, and that every `FILL_INDEX_KEY_PREFIX` f-string joins the prefix with one instrument-id expression.

      This closes the "absent means flat" key-drift residual on the ARCH-0 side. The reader half, which prepends the imported prefix, is `[adapter_reader]` (AUT-5a).
    - `net_position.py` and `entry_guard.py` do not import `breezy.domain`. `test_leg_suffix_equals_instrument_leg` asserts `"^no" == instrument_leg.INSTRUMENT_SEPARATOR + NO_LEG_SUFFIX` (`instrument_leg.py:35-40`).
23. **Veto.** `VetoReason` has exactly the 15 ARCH C5 members (`AUTONOMY_ARCHITECTURE.md:642-662`):
    - registry: `registry_not_champion`, `registry_halted`, `registry_unreadable`, `registry_regressed`, `registry_restrictive_pending`;
    - dead engine: `registry_attest_expired`, `registry_engine_heartbeat_stale`, `registry_chain_stale`;
    - transient: `feed_stale`, `recorder_stale`, `permit_lapsed`, `capture_gap`, `capture_untagged`, `alerts_undeliverable`;
    - position: `rung_net_position_held`.

    There is no `EntryVeto` alias. `compose_entry_vetoes(checks)` returns the first veto, and any exception gives `registry_unreadable`.
24. **Records.**
    - **C4 verdict.**
      - `verdict_id = sha256(canonical body − {verdict_id, produced_at_ns})`.
      - Path: `derived/verdicts/<family>/<UTC date of valid_until_ns>/<id>.json`, 0600, write-once.
      - The same id with a body that is equal apart from `produced_at_ns` is a no-op. Any other difference gives `VerdictIdCollision`.
      - Validity above `MAX_VERDICT_VALIDITY_H` is refused.
    - **Demand.**
      - Writer: exact-set `demand/v1`, at most `DEMAND_FILE_MAX_BYTES`, gated by `DEMAND_WRITER_PRODUCER_IDS`, one file per (family, reason), idempotent on `verdict_id`, with producer cap `DEMAND_FILES_MAX − DEMAND_INTEGRITY_RESERVED`. Its docstring states that `producer_id` is advisory, not authentication.
      - Reader: any bad file or more than `DEMAND_FILES_MAX` files gives `venue_veto=True`.
      - There is no archive API.
    - **Journal.** `append_journal(paths, kind, venue, record, *, ts_ns) -> JournalHead` writes a write-once (0444) `journal/v1` envelope linked by `prev_sha256`. Kinds are bare names (`\A[a-z][a-z0-9_]{0,47}\Z`), and a record's `schema` carries `/vN`. `JOURNAL_KINDS = frozenset()`. `read_journal_chain` returns entries or `JournalUnverified`.
    - **C3.** `Lineage`, `RootRecord`, `RefitRun` and `model_class_of(kind, component)`.
    - **Drill marker.** AUT-7 r5's 12-key `drill_marker/v1`. ENOENT on the marker gives `MarkerAbsent`; ENOENT on the directory gives `MarkerError`.
    - **C2.** `LABEL_V1_ARROW_SCHEMA`, column for column.
    - Every path component is validated (Edge Cases).
25. **Pins.** `pins.py` holds literals only and imports nothing:
    - every ARCH §4.5 ceiling as amended by E-11 (no `SELF_HEAL_*`);
    - `ENGINE_SOURCE_SHA256 = frozenset()`, `PRODUCER_SOURCE_SHA256 = MappingProxyType({})`, `REVOKED_SOURCE_SHA256 = frozenset()`;
    - `ENABLED_WIDENING_KINDS = frozenset()`, `POLICY_RULING_PIN = ()`, `ROOT_ADMIT_ENABLED_CEILING = False`;
    - `LIVE_GATE_ROUTED_KINDS = frozenset({"forecast_quantile_ladder"})`;
    - `BOOTSTRAP_SEED`, `DEMAND_WRITER_PRODUCER_IDS = ("aut6.intraday",)`, `DEMAND_REASONS`, `CAUSE_CODES`, `HALT_REASON_CLASS_MAP` and `DEFAULT_RESTRICTIVE_CLASS`;
    - `SCHEDULE_{STOP,LAUNCH,LAUNCH_WINDOW_END}_UTC`, test-equal to V6;
    - `ENGINE_LOCK_MAX_HOLD_S = 15`, `RELAUNCH_REQUEST_TTL_S = 120`, `WATCH_BUSY_TIMEOUT_MS = 250`, `WATCH_TICK_STALE_S = 180`;
    - `DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY = 1`, `DRAWDOWN_INERT_ALERT_CEILING = "0.5"`, `DRAWDOWN_INERT_ALERT_MIN_FILLS = 10`;
    - `ROW_TS_MAX_SKEW_S = 300`, `EXPORT_FIRST_DUE_H = 26`, `ROOT_ARTEFACT_COMPONENT = "density_table"`.

    Kind sets are `frozenset[str]` and are validated against `Kind`. Mapping pins use `MappingProxyType`.
26. **C6.** `plugin.py` defines the `CaptureAdapter`, `Scorer`, `Evaluator`, `Detector`/`DriftDetectors` and `Refitter` Protocols, with `@property` attribute members, plus `RefusingPlugin`. `NODE_PLUGINS` (strategy) and `OFFLINE_PLUGINS` (analysis) each hold exactly the four `_COMPOSITION_KINDS` keys (`family_manifest.py:118-120`), written as literal `MappingProxyType` entries with every value `RefusingPlugin`. `test_family_plugin_exact_set` passes.
27. **Placeholder ledger.**
    - Rows have the shape `(node_id, owner, owner_symbol "mod:attr", blocks_kinds)`. Carried bodies are fixture-free stubs: `require_owner_symbol(...)` plus a docstring citing the ARCH pin, under `xfail(strict=True, raises=OwnerPending)`.
    - `require_owner_symbol` raises `OwnerPending` only in two cases: a `ModuleNotFoundError` whose `.name` is the declared module or one of its `breezy.` ancestors, or an `AttributeError` for the declared attribute. Every other error propagates.
    - Gate tests:
      - markers equal the ledger (decorator and `pytest.param(marks=…)` forms, each with a positive control);
      - `test_owner_placeholder_symbol_absent`, `test_owner_ids_exist_in_plan_docs` and `test_envelope_manifest_equals_frozen_arch`;
      - `test_every_envelope_node_id_collected_and_unskipped`, `test_widening_kind_enabled_only_when_its_placeholders_cleared` and `test_blocks_kinds_never_below_floor`;
      - AUT-5's `test_l2_widening_requires_empty_placeholder_ledger`.
28. **Root copies (E-14; security F11).** `family_bytes.write_root_copy(paths, *, record: RootRecord, artefact_raw: bytes) -> RootCopyResult{WRITTEN, EXISTS_EQUAL}` writes `artefact.json` and then `roots/<family_id>.json` through `write_once`. EXISTS_DIFFERENT on either file raises `RootCopyIntegrity`. Tests:
    - `test_two_roots_sharing_sha_write_identical_artefact_json` (byte compare);
    - `test_root_copy_exists_different_is_integrity`;
    - `test_root_copy_rerun_after_chmod_0500_is_exists_equal`, which asserts by `list_dir_at` that no temp file is created.
29. **Gate.**
    - `scripts/ci/run_tests_no_egress.sh` exits 0 **after every seam commit** (L-43); no gated unit exceeds about 1,000 changed lines (architect F13).
    - `lint-imports` passes.
    - The mypy ratchet passes. New files have 0 errors. A ceiling that the code falls below is **lowered** in the same commit; ceilings are never raised (V17).
    - RED→GREEN logs exist for each real test, with mutation evidence where listed.
30. **Live-path mixed-version safety (security F10).** `test_live_path_modules_import_set_pinned` pins the `breezy.*` import set of `family_manifest.py` (`{breezy.persistence.mechanism_test_guard}`) and of `live_orders_gate.py` (`{breezy.persistence.family_manifest}`). The WP-1 and WP-8a commits add no new cross-module import. Each new function's callers live in the same file, and `FamilyManifest` is unchanged. A long-running process that lazily imports one changed module beside an older loaded module therefore cannot hit an ImportError or a signature mismatch.

## Edge Cases & NFRs (fail-closed, one-writer, symlink refusal, atomicity, thread-affinity)

**Fail-closed.** Every failure gives the restrictive outcome.

| Input or condition | Result |
|---|---|
| Unknown `schema`; unknown, missing or duplicate key; bool as int; float token; NaN or Inf; oversize | `WireRefused(reason)`, which becomes a resolver refusal, a demand venue veto, or `VerdictUnreadable` (the engine treats it as ERROR) |
| Empty chain under `BREEZY_FAMILY_SOURCE=registry` | `empty_chain` |
| `RegistryUnreadable(busy \| hot_journal \| schema_mismatch \| io \| sqlite_error)` | Resolver: `registry_unreadable`, with the reason as an enum detail. Watch actor: `busy` means the tick is not verified; the others veto at once (binding note) |
| `venue_seq` gap, renumbering, foreign venue, decreasing ts | `chain_broken` |
| `now_ns` not an int, ≤ 0, or < head ts − skew | `clock_invalid` / `clock_before_head` |
| HWM `Unreadable` or foreign venue | `hwm_unreadable` |
| HWM `Absent` with any row | `hwm_absent`. There is no genesis exception (AC 16). Recovery is `breezy-registry-hwm-reset` (L-48 row) |
| HWM above head; hash at `hwm.venue_seq` ≠ `hwm.chain_head` (covers same-seq and mid-chain rewrites); `hwm.export_seq` above the newest export | `hwm_regressed` |
| Exports directory missing or unreadable, or a listing error | `export_unreadable` |
| No export file | `not_yet_due` only if `hwm.export_seq == 0` and `now − genesis_ts < 26 h`; otherwise `export_unreadable` |
| Any row of a widening kind outside enabled or admission-implemented | `widening_kind_not_enabled` / `admission_pending`, even for rows inserted outside `append` (hand-forged chain, L-24) |
| More than one CHAMPION/HALTED family | `engine_inconsistency` |
| `resolve_sending_family` on a shadow root, or `resolve_shadow_family` on a production root | `paths_role_mismatch` |
| Root manifest bytes at `deploy/families/<id>.json` hash ≠ row | `manifest_sha_mismatch` (A3-R1). A tampered `registry/families` copy is never read for a root |
| Root named like a child (`x_r0001`) | Resolved as a root by `origin`. The child path is never taken (`test_root_named_like_child_is_not_routed_as_child`) |
| Child whose regex root ≠ `lineage_root_family_id` | `child_root_mismatch` |
| Manifest draft, unpinned, unreadable, invalid, prereg-ineligible, or source directory missing | `manifest_draft` / `manifest_unpinned` / `manifest_unreadable` / `manifest_invalid` / `prereg_ineligible`. Returned values carry no path |
| Manifest identity ≠ row; kind not routed | `manifest_identity_mismatch` / `kind_not_live_gate_routed` |
| Root record missing, mismatched, or `committed_path` ≠ `deploy/families/<family_id>.json` | `root_record_mismatch` |
| Engine sha unpinned or revoked | `engine_code_unpinned` / `engine_code_revoked`. At ARCH-0 every production resolution refuses here, by design |
| Child: no lineage triple, ruling sha mismatch, or ruling ≠ policy ruling | `root_not_lineage_allowlisted` / `ruling_refused` / `ruling_not_policy` |
| Guard: reader raises, empty index, open or corrupt intent, bad slug, unknown side | `GuardResult.UNREADABLE` → veto |
| Demand directory unreadable, bad file, unknown family or reason, more than max | `venue_veto=True` |
| Journal link broken | `JournalUnverified`. Restrictive writes are never blocked (L-48) |
| `write_once` without hard links | `LINK_UNSUPPORTED`. There is no rename fallback |

**One writer (L-50).** `tests/unit/autonomy_writer_table.py` is data, and Wave 1 owners extend it. The AST scan fails on any write site outside `single_read.{write_once, replace_atomic, ensure_dir}` and `registry_store`, which is the only sqlite writer.

| Path | Writer process types |
|---|---|
| `registry/registry.sqlite` | Under `registry/engine.lock`: the engine and the HWM-reset CLI |
| `evidence/registry/registry_<venue>_<date>[_hwm<k>].jsonl` | Write-once: the engine and the HWM-reset CLI |
| `derived/verdicts/**` | Write-once: producers |
| `registry/demand/<venue>/*` | Write-once: the engine and `DEMAND_WRITER_PRODUCER_IDS` |
| `evidence/journal/<venue>/<kind>/<seq>.json` | Write-once: the engine |
| `derived/artefacts/<model_class>/<sha>/{artefact.json, roots/<family_id>.json}` | Write-once through `write_root_copy`: engine bootstrap mode; AUT-3 refit writes `artefact.json` and `lineage.json` |
| Exec-store key `autonomy/registry_hwm/<venue>` | The node (under its flock); the L1 cut-over script and the HWM-reset CLI with the node down. This is not an ARCH-0 file, and the row is recorded for AUT-5a |

**Symlink refusal and path components.** Every path is built by an `AutonomyPaths(root)` builder, and `AutonomyPaths.shadow(root)` is a distinct root type. Each builder validates its components with `re.ASCII` `\A…\Z` patterns:

| Component | Pattern |
|---|---|
| venue | `[a-z0-9_]{1,32}` |
| family | `[a-z0-9_]{1,64}`, the intersection from V19. A test asserts that both existing patterns accept every accepted id |
| model_class | `<kind ∈ _COMPOSITION_KINDS>:[a-z_]{1,48}` |
| sha or verdict id | `[0-9a-f]{64}` |
| date | `[0-9]{4}-[0-9]{2}-[0-9]{2}`, checked with `date.fromisoformat` |
| journal kind | bare name (AC 24) |
| seq | int ≥ 1, formatted `%010d` |

All I/O goes through the AC 7 openat walk. Each builder has a traversal-vector test.

**Atomicity.**
- A multi-row append is one transaction. `test_store_multirow_append_is_atomic` proves it with SWAP_CANCEL + TARGET_INELIGIBLE.
- A crash in `write_once` leaves at most a `.tmp.` file, which the owner engine sweeps. A crash in `replace_atomic` leaves the old bytes.
- Root copies are written before the genesis COMMIT, and a rerun is idempotent (E-14 rule 6).

**Thread affinity, clock, hygiene.**
- No connection is held across calls, and there are no threads, timers or asyncio (AST).
- There is no module-level mutable state; only `Final` frozensets, tuples and `MappingProxyType` are allowed.
- `now_ns` is always explicit.
- Refusals carry enums and role names, never paths. `test_autonomy_payload_hygiene_scan` plants a tmp path through `family_manifest` and `live_orders_gate` failures and asserts it appears in no `str`, `repr` or field of the returned refusal.

**Size and performance.**
- 10,000 synthetic rows resolve in ≤ 2 s.
- `closure_sha256` runs in ≤ 5 s and ≤ 128 MB, without grimp.
- The resolver's runtime closure carries about 48 MB of pyarrow (V2). This is accepted against AUT-5's 4 G own-lock budget.

**Root permission.** The gate may run under `unshare -r` as uid 0. Mode assertions therefore use `stat().st_mode`, and read-only behaviour relies on SQLite `mode=ro`, which does not depend on uid.

## Architecture & Data Flow (modules, public API signatures, storage layout + paths, layering vs import-linter layers app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain)

**Layering.**
- `persistence`, `registry` and `normalize` are independent siblings (`pyproject.toml:97`).
- `persistence.autonomy` imports only stdlib, `persistence` and `settlement`. `breezy.domain` is barred by contract (b).
- `NODE_PLUGINS` sits in strategy and `OFFLINE_PLUGINS` in analysis (ARCH C6). The watch actor, which is AUT-5a's, is `src/breezy/strategy/autonomy/registry_watch_actor.py`.

**Modules and public API.** Every module uses `from __future__ import annotations` and mypy strict. ★ marks a change in r3.

```text
src/breezy/persistence/__init__.py         docstring only; no import nodes
src/breezy/persistence/family_manifest.py  + parse_family_manifest(raw: bytes, *, path: Path, allow_draft: bool = False) -> FamilyManifest
src/breezy/persistence/live_orders_gate.py + _LINEAGE_POLICY_ALLOWLIST; CHILD_FAMILY_ID_RE; _verify_ruling_file (move-only);
       LineagePolicyDecision; lineage_policy_authorized(child, root_family_id, repo_root); _lineage_policy_authorized(..., *, allowlist)
src/breezy/persistence/autonomy/
  canonical.py     canonical_json; sha256_hex; decimal_str; CanonicalTypeError
  wire.py          parse_json_exact; require_exact_keys/str/int/bool/sha256/enum/decimal_str/ns; WireRefusalReason; WireRefused; SHA256_RE; FAMILY_ID_RE
  single_read.py ★ ReadPolicy; open_root; walk_dirs; read_once_at; read_once_nofollow; write_once (pre-read EXISTS_EQUAL); replace_atomic;
                   ensure_dir; list_dir_at; SingleReadRefused(reason)
  paths.py ★       AutonomyPaths(root), AutonomyPaths.shadow(root) -> ShadowPaths; is_shadow; validated builders; root_record(model_class, sha,
                   family_id) [WP-6c, after E-14]; default_data_root() (entry points only, AST)
  pins.py          literals only (AC 25)
  veto.py          VetoReason (15); compose_entry_vetoes
  plugin.py        C6 Protocols (@property members); RefusingPlugin; is_complete
  closure_manifest.py  CLOSURE_MODULES = MappingProxyType({})
  closure.py       closure_sha256(component); closure_from_grimp(entry) (gate-only, lazy grimp)
  schemas.py ★     State, Kind, CauseClass, CauseCode, WriterMode, DecidedBy; TransitionRow; ExportTrailer; StagePolicy (frozen) + StageView
                   Protocol; RefusalReason; ResolverRefusal(reason, detail: UnreadableReason | LiveOrdersReason | None); ResolvedFamily;
                   ShadowResolution; FamilyBytes; ManifestFacts; UnreadableReason
  stage_policy.py ★ STAGE: Final[StagePolicy] = _build()
  verdict.py       C4 types; verdict_id; write_verdict; read_verdict
  lineage.py       Lineage, RootRecord, RefitRun, RefitOutcome; model_class_of; root_model_class(composition_kind)
  label_schema.py  LABEL_SCHEMA_ID; LABEL_V1_ARROW_SCHEMA; ExcludedReason; PSource; LabelRole
  demand.py        DemandRecord; write_engine_demand; write_producer_demand -> DemandWrite; scan_demands -> DemandScan
  drill_marker.py  DrillMarker (12 keys); read_marker_at -> DrillMarker | MarkerAbsent | MarkerError
  rollback_journal.py  JOURNAL_KINDS; JournalEntry; JournalHead(seq, sha256); append_journal; read_journal_chain
  fold.py ★        fold(rows, venue, now_ns) -> FoldResult; resolve_champion; FoldResult; FamilyView(+origin, lineage_root_family_id);
                   LineageView; LineageTallies
  transitions.py ★ ALLOWED; KIND_MASK; WIDENING_KINDS; RESTRICTIVE_KINDS; PAIR_KINDS; _ADMISSION_IMPLEMENTED; is_widening; transition_id;
                   validate(prior, rows, *, mode: WriterMode | None, now_ns, stage: StageView, manifests: ManifestFactsReader,
                   export_counters: CounterSet | None = None) -> RefusalReason | None; rows_admissible(rows, *, stage) -> RefusalReason | None
  chain.py         genesis; transition_hash; VerifiedVenueChain; verify_venue_chain; verify_extension; seq_is_verified_prefix; verify_against_export
  family_bytes.py ★ read_manifest_facts; verify_family_bytes(row, *, paths, repo_root, origin) -> FamilyBytes | ByteBindingFailure;
                   write_root_copy(paths, *, record, artefact_raw) -> RootCopyResult
  registry_store.py ★ RegistryStore.initialise; RegistryStore(paths).append(rows, *, expected_prior_seq, mode, now_ns) -> AppendResult; _append;
                   write_export(venue, *, date, now_ns, journal_heads) -> ExportTrailer; RegistryReader; RegistryUnreadable(reason);
                   newest_export(paths, venue) -> (ExportTrailer, rows) | ExportUnreadable | ExportAbsent; DDL constants
  hwm.py ★         Hwm; HwmAbsent/HwmPresent/HwmUnreadable; REGISTRY_HWM_KEY_PREFIX; hwm_key; hwm_reading_from_bytes; hwm_check; next_hwm
  replay.py        replay_full(chain, *, paths, repo_root) -> ReplayOk | ReplayInvalid | ReplayCauseUnresolved | ReplayArtefactMismatch; _replay_full
  net_position.py ★ LegFill(leg, side, qty, ts_event_ns); net_signed_qty; UnknownSide
  entry_guard.py ★ GuardResult; FillIndexAbsent; FillRow(order_side, cumulative_qty, ts_event_ns); FillReader; leg_instrument_ids;
                   rung_has_net_position; guard_veto_reason
  resolver.py ★    FamilySource; read_family_source(env); resolve_sending_family; resolve_shadow_family; SHADOW_CALL_SITES = frozenset();
                   _resolve(..., stage, lineage_gate, hwm_mode); manifest_equal_modulo_allowlist
src/breezy/strategy/autonomy/node_plugins.py     NODE_PLUGINS
src/breezy/analysis/autonomy/offline_plugins.py  OFFLINE_PLUGINS
```

**Closed `RefusalReason`.** `test_resolver_refusals_give_no_champion` asserts by AST that the members equal its params. The members are: `registry_unreadable`, `empty_chain`, `chain_broken`, `clock_invalid`, `clock_before_head`, `hwm_unreadable`, `hwm_absent`, `hwm_regressed`, `export_unreadable`, `export_prefix_mismatch`, `widening_kind_not_enabled`, `admission_pending`, `replay_invalid`, `replay_cause_unresolved`, `replay_artefact_mismatch`, `engine_inconsistency`, `no_sender`, `paths_role_mismatch`, `engine_code_unpinned`, `engine_code_revoked`, `manifest_unreadable`, `manifest_invalid`, `manifest_draft`, `manifest_unpinned`, `prereg_ineligible`, `manifest_sha_mismatch`, `manifest_identity_mismatch`, `kind_not_live_gate_routed`, `artefact_unreadable`, `artefact_sha_mismatch`, `root_record_mismatch`, `child_root_mismatch`, `child_not_equal_root`, `root_not_lineage_allowlisted`, `ruling_not_policy`, `ruling_refused`, `no_live_orders_ruling`, `d0_breach`, `trial_prefix_mismatch`.

**Storage layout.** All paths are under `/home/jon/.local/share/breezy/`. Directories are created 0700 and explicitly chmodded, whatever the umask (V5). Files are 0600, or 0444 when content-addressed.
- `registry/registry.sqlite` and `registry/engine.lock`. The lock belongs to the AUT-5a engine unit.
- `registry/families/<id>.json` (0444), `registry/demand/<venue>/`, `registry/heartbeat/<venue>.json`, `registry/drill/marker.json`. Their writers are AUT-5a and AUT-7; ARCH-0 ships the paths, types and readers.
- `evidence/registry/registry_<venue>_<YYYY-MM-DD>.jsonl` (0444). Each line is a `TransitionRow.to_wire()`, and the last line is the trailer `{"schema":"registry_export/v1","venue","venue_seq","chain_head","export_seq","evidence_journal_heads"}`. The HWM-reset variant is `_hwm<export_seq>.jsonl`.
- `evidence/journal/<venue>/<kind>/<seq:010d>.json` (0444).
- `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json`.
- `derived/artefacts/<composition_kind>:<component>/<sha>/artefact.json` (0444); root records go in `derived/artefacts/<kind>:density_table/<sha>/roots/<family_id>.json` (E-14).
- `registry-shadow/` has the same layout and is a distinct `ShadowPaths` root.

**Data flow.**
- Producers (AUT-2, AUT-4, AUT-6) call `write_verdict` into `derived/verdicts`.
- The engine (AUT-5a) reads through `RegistryReader` and `fold`, then calls `append(rows, CAS, mode, now_ns)` → store, `write_export`, `append_journal`, `write_engine_demand` and, in bootstrap mode, `write_root_copy`.
- `aut6.intraday` calls `write_producer_demand`.
- `resolve_sending_family` is called by the supervisor, the settings validator and the node (AUT-5a). It reads `RegistryReader`, `newest_export`, `hwm_check`, `rows_admissible`, `replay_full` (which calls `read_verdict`) and `family_bytes.verify_family_bytes`. That last call reads `deploy/families/` for roots and `registry/families/` plus `derived/artefacts/` for children, then calls `live_orders_authorized` or `lineage_policy_authorized`.
- `resolve_shadow_family` is called by the supervisor shadow branch and the watch actor (AUT-5a, shadow root).
- The watch actor (AUT-5a) runs `read_venue_rows`, `verify_extension`, `rows_admissible`, `validate`, `fold`, `scan_demands`, `hwm_check`, `next_hwm`, and `rung_has_net_position(FillReader)`.
- `store.append` calls `family_bytes.read_manifest_facts` for d0 and identity.

## Stub Surface for Wave 1 (table: symbol | consumer plan + section | ARCH-0 delivers real or stub)

"Real" means implemented and tested. "Owner" means the item is outside ARCH-0 (A-R6).

| Symbol / item | Consumer (plan § / line) | ARCH-0 |
|---|---|---|
| `VetoReason` (15), `compose_entry_vetoes` | AUT-1 r12 `:1237`; AUT-5 r7 §3.1 | Real; no `EntryVeto` alias |
| `NODE_PLUGINS`, `OFFLINE_PLUGINS`, C6 Protocols, `RefusingPlugin` | AUT-1, AUT-2, AUT-3, AUT-4, AUT-6 | Real; every kind is `RefusingPlugin` |
| Every pin in AC 25 | AUT-1 to AUT-7 | Real; `SELF_HEAL_*` is not shipped (E-11) |
| Code-identity pins, `closure_sha256` | AUT-5 WP4, AUT-4, AUT-6 | Real machinery with empty pins |
| `StagePolicy`/`StageView` (schemas), `STAGE`, `_ADMISSION_IMPLEMENTED`, `rows_admissible` | AUT-5 WP1b, WP5, WP9, WP10 | Real; `admission_implemented` is empty |
| `verdict.*`, `decimal_str` | AUT-2 `:943`; AUT-4 `:450`; AUT-6 `:512` | Real |
| `label_schema.*`, `lineage.*`, `drill_marker.*` | AUT-2, AUT-3, AUT-6, AUT-7 | Real |
| `demand.write_producer_demand`, `scan_demands`, `write_engine_demand` | AUT-6 WP5b; AUT-5 WP4, WP5 | Real |
| `append_journal`, `read_journal_chain`, `JournalHead` | AUT-7 r5 `:91`, `:506` | Real envelope; `JOURNAL_KINDS` is empty |
| `RegistryStore.append`, `KIND_MASK`, `WriterMode`, `transitions.validate` | AUT-7 r5 `:703`; AUT-5 WP4 | Real; widening kinds are refused |
| `RegistryReader`, `RegistryUnreadable(reason)`, `verify_*`, `fold`, `resolve_champion`, `LineageTallies` | AUT-3, AUT-4 (tallies replace the `lineage_counters` read), AUT-5, AUT-7; **AUT-6 r15 `:1474` consumes the fold** (corrects r2's AUT-6 WP6 citation) | Real |
| `resolve_sending_family`, `ResolvedFamily` (AC 19), `FamilyBytes`, `HwmReading`, `hwm_reading_from_bytes`, `hwm_check`, `next_hwm` | AUT-5 WP5, WP6, WP8, WP10; AUT-1 r12 `:15`, `:329` (`registry_seq`) | Real |
| `resolve_shadow_family`, `ShadowResolution` | AUT-5 WP5, WP6, WP10 (stage S) | Real; `SHADOW_CALL_SITES` is empty |
| `family_bytes.verify_family_bytes(row, *, paths, repo_root, origin)`, `write_root_copy` | AUT-7 r5 `:56`, `:703`; AUT-5a bootstrap | Real |
| `parse_family_manifest`, `lineage_policy_authorized`, `_LINEAGE_POLICY_ALLOWLIST` (empty) | resolver; AUT-5 WP9 | Real |
| `entry_guard.*`, `GuardResult`, `FillReader`, `LegFill(ts_event_ns)` | AUT-5 WP2, WP5; AUT-2 r7 `:335` | Real; the adapter reader is AUT-5a's |
| **Owner rows** | | |
| Nomination k-checks, policy-stricter bounds, HWM_RESET store admission, per-kind `_ADMISSION_IMPLEMENTED` | AUT-5 WP1b | Owner |
| `policy.load_policy_block` | AUT-5 WP3 | Owner |
| `demand.archive` and its 3 tests | AUT-5 WP4 | Owner |
| Derived caches (`families`, `projection`, `lineage_counters`) and the reader's DDL set | AUT-5 WP4 | Owner |
| `halt_rows.py`, `src/breezy/runtime/submit_intent_record.py` and 3 tests | AUT-5a; AUT-6 aliases them | Owner |
| E-8a snapshot helper | ARCH-0 seam B | Other seam |
| `heartbeat/v1`, `halt_mirror/v1`, `stop_complete/v1`, `launch_event/v1`, `relaunch/v1`, `drawdown_control_active` | AUT-5a WP4, WP6, WP7, WP11 | Owner |
| Child artefact location and the four-site containment widening (`test_containment_checks_read_directory_not_phantom_base`) | AUT-5a | Owner |
| `PolymarketUsFillReader` | AUT-5a | Owner |
| `_LINEAGE_POLICY_ALLOWLIST` row and the child routing inside `live_orders_authorized` | AUT-5 WP9 | Owner |
| `net_position.average_cost_basis` | AUT-2 WP2 | Owner |
| `JOURNAL_KINDS` members, `verify_journal_chain` | AUT-7 | Owner |
| `sample_size.py`, `nomination.py` | AUT-4 | Owner |
| `capture_*.py` | AUT-1a (E-12) | Owner; joins `NAUTILUS_PERMITTED` |
| C4.1 holdout ruling filing; AUT-2 Wave-0 egress review | Coordinator; AUT-2a | Owner |

**Frozen signatures (architect F10b).** The WP-6 to WP-8 surfaces above are frozen from the moment this plan is approved: names, parameter lists and return unions. A later change needs a coordinator erratum. Wave 1 builds against them before they merge.

## File-by-File Plan (absolute path | new|modified | exact content | deps)

| Absolute path | | Content | Deps |
|---|---|---|---|
| `/home/jon/breezy/src/breezy/persistence/__init__.py` | mod | Docstring only, citing the NOTIFIER-IMPORT-ISOLATION precedent | — |
| `/home/jon/breezy/src/breezy/persistence/family_manifest.py` | mod | AC 21; `__all__` gains 1 name | — |
| `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py` | mod | AC 20 | family_manifest |
| `/home/jon/breezy/src/breezy/persistence/autonomy/__init__.py` | new | Docstring only | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/canonical.py` | new | AC 6 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/wire.py` | new | AC 5 | canonical |
| `/home/jon/breezy/src/breezy/persistence/autonomy/single_read.py` | new | AC 7 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/paths.py` | new | Builders; `root_record` is added in WP-6c | wire |
| `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py` | new | AC 25 | none |
| `/home/jon/breezy/src/breezy/persistence/autonomy/veto.py` | new | AC 23 | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/plugin.py` | new | AC 26 | veto |
| `/home/jon/breezy/src/breezy/persistence/autonomy/closure_manifest.py` | new | Empty mapping | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/closure.py` | new | `closure_sha256`; lazy grimp | single_read, closure_manifest |
| `/home/jon/breezy/src/breezy/persistence/autonomy/schemas.py` | new | C5 enums and records, `StagePolicy`, refusal and result types | wire, canonical, rollback_journal |
| `/home/jon/breezy/src/breezy/persistence/autonomy/stage_policy.py` | new | `STAGE` | pins, transitions, schemas |
| `/home/jon/breezy/src/breezy/persistence/autonomy/verdict.py` | new | AC 24 | wire, canonical, single_read, paths, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/lineage.py` | new | AC 24 | wire |
| `/home/jon/breezy/src/breezy/persistence/autonomy/label_schema.py` | new | C2 arrow schema | pyarrow |
| `/home/jon/breezy/src/breezy/persistence/autonomy/demand.py` | new | AC 24 | wire, single_read, paths, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/drill_marker.py` | new | AC 24 | wire, single_read |
| `/home/jon/breezy/src/breezy/persistence/autonomy/rollback_journal.py` | new | AC 24 | wire, single_read, paths |
| `/home/jon/breezy/src/breezy/persistence/autonomy/fold.py` | new | AC 14 | schemas, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/transitions.py` | new | AC 13 | schemas, pins, fold |
| `/home/jon/breezy/src/breezy/persistence/autonomy/chain.py` | new | AC 11 | canonical, schemas |
| `/home/jon/breezy/src/breezy/persistence/autonomy/family_bytes.py` | new | AC 17, 21, 28 | single_read, paths, lineage, schemas, family_manifest, mechanism_test_guard |
| `/home/jon/breezy/src/breezy/persistence/autonomy/registry_store.py` | new | AC 8 to AC 12 | chain, transitions, fold, stage_policy, family_bytes, single_read, paths |
| `/home/jon/breezy/src/breezy/persistence/autonomy/hwm.py` | new | AC 16 | wire, schemas, chain |
| `/home/jon/breezy/src/breezy/persistence/autonomy/replay.py` | new | Row-by-row `validate(mode=None)`; each widening row's `cause_verdict_ids` resolve through `read_verdict` | transitions, fold, verdict, chain, family_bytes |
| `/home/jon/breezy/src/breezy/persistence/autonomy/net_position.py` | new | AC 22 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/entry_guard.py` | new | AC 22 | net_position, veto |
| `/home/jon/breezy/src/breezy/persistence/autonomy/resolver.py` | new | AC 17 to AC 19 | everything above, plus live_orders_gate |
| `/home/jon/breezy/src/breezy/strategy/autonomy/__init__.py` | new | Docstring | — |
| `/home/jon/breezy/src/breezy/strategy/autonomy/node_plugins.py` | new | `NODE_PLUGINS` literal | plugin |
| `/home/jon/breezy/src/breezy/analysis/autonomy/__init__.py` | new | Docstring | — |
| `/home/jon/breezy/src/breezy/analysis/autonomy/offline_plugins.py` | new | `OFFLINE_PLUGINS` literal | plugin |
| `/home/jon/breezy/pyproject.toml` | mod | Contracts (a), (b) and (c) (AC 1). Lists grow as modules land. Comment: owners append; `capture_*` goes to `NAUTILUS_PERMITTED` | — |
| `/home/jon/breezy/scripts/ci/regen_closure_manifest.py` | new | Deterministic, literal output. `test_regen_output_is_literal_and_reproducible` | grimp |
| `/home/jon/breezy/tests/support/entry_points.py` | new | `REPO_ROOT`, `PYPROJECT_PATH`, `DEPLOY_SYSTEMD_DIR`, `SCRIPTS_DIR`. `_entry_modules_from_pyproject_scripts` and `_entry_modules_from_systemd` are moved **byte-identical** from `/home/jon/breezy/tests/unit/test_runtime_import_isolation.py:158-190`. `_entry_modules_from_scripts_importing(package: str)` is `:192-216` with **one parameter** replacing the literal `"breezy.runtime"` | — |
| `/home/jon/breezy/tests/unit/test_runtime_import_isolation.py` | mod | Import-block hunk only: it imports the three helpers and binds `_entry_modules_from_scripts_importing_runtime = functools.partial(_entry_modules_from_scripts_importing, "breezy.runtime")`. The helper definitions are removed. **No `def test_*` body and no assertion changes** | entry_points |
| `/home/jon/breezy/tests/unit/test_mypy_ratchet.py` | mod only if needed | Lower a ceiling that the code falls below (V17); never raise one | — |
| `/home/jon/breezy/tests/support/autonomy_owner.py` | new | `OwnerPending`, `require_owner_symbol` | — |
| `/home/jon/breezy/tests/unit/autonomy_owner_placeholders.py` | new | `OWNER_PLACEHOLDERS` (4-tuples), `OWNER_REGISTRY` | — |
| `/home/jon/breezy/tests/unit/autonomy_blocks_kinds_floor.py` | new | `BLOCKS_KINDS_FLOOR` | — |
| `/home/jon/breezy/tests/unit/autonomy_envelope_manifest.py` | new | `ARCH_FREEZE_SHA256`; `E11_RENAMES` (3 rows: `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` → `test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine`; `test_self_heal_cap_survives_process_restart` → `test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all`; `test_restart_window_resets_before_launch` → `test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical`); `ENVELOPE_NODE_IDS` | — |
| `/home/jon/breezy/tests/unit/autonomy_writer_table.py` | new | One-writer rows | — |
| `/home/jon/breezy/tests/fixtures/family_manifest_golden/` | new | Corpus, `artefacts/`, `expected.json` (AC 21) | — |
| `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` | **never edited** | Byte pin V7; read-only AST reads only | — |

## Test Strategy (file | test names | unit/contract | which §4.7 rows are real-GREEN in ARCH-0 vs carried strict-xfail with owner)

**Carrying mechanism.** Carrying works as AC 27 describes.
- Pytest 9.1.1 fails a non-matching exception and fails a strict XPASS.
- A test that is half real and half owned elsewhere uses literal `pytest.param(..., id=...)` ids.
- `test_every_envelope_node_id_collected_and_unskipped` cross-checks AST ids against one `--collect-only -q` subprocess over the autonomy test files. It fails on any skip mark or call.

**Real-GREEN in ARCH-0.** Each test has a RED log; mutation evidence (L-33) is in brackets.

| File | Tests | Type |
|---|---|---|
| `/home/jon/breezy/tests/unit/test_persistence_import_free.py` | `test_persistence_init_has_no_import_nodes`; `test_persistence_has_no_facade_consumers` [a planted `from breezy.persistence import write_records` turns it red]; `test_persistence_entry_module_imports_cleanly[*]`; `test_live_path_modules_import_set_pinned` | contract |
| `/home/jon/breezy/tests/unit/test_family_manifest_split_golden.py` | `test_parse_split_matches_presplit_golden`; `test_load_family_manifest_keeps_prereg_check` | contract |
| `/home/jon/breezy/tests/unit/test_lineage_policy_allowlist.py` (AUT-5 WP9 file) | `test_lineage_policy_allowlist_is_literal_only`; `test_child_requires_lineage_triple_and_policy_ruling`; `test_child_with_operator_ruling_refused`; `test_tampered_policy_ruling_refuses_child`; `test_lineage_gate_refuses_missing_ruling_file`; `test_lineage_gate_refuses_ruling_symlinked_outside_subtree`; `test_lineage_gate_refuses_child_id_outside_root_lineage` (including a Unicode-digit id); `test_lineage_decision_carries_no_permit_semantics`; `test_verify_ruling_file_extraction_keeps_reasons_and_messages` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_canonical.py`, `/home/jon/breezy/tests/unit/test_autonomy_wire.py` | golden bytes; the four decimal goldens; NaN, Inf and exponent; non-str key; float; lone surrogate; duplicate key; bool-as-int | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_single_read.py` | `test_walk_refuses_symlinked_intermediate_dir`; `test_read_refuses_fifo_without_blocking`; `test_read_refuses_group_writable_under_strict`; `test_write_once_symlink_at_destination_with_equal_bytes_is_different`; `test_write_once_final_mode_by_stat`; `test_write_once_link_unsupported_fails_closed`; `test_write_once_exists_equal_creates_no_temp`; `test_replace_atomic_writes_temp_in_target_dir_fsyncs_and_replaces`; `test_read_size_cap`; `test_read_uses_one_fd` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_paths.py` | a traversal vector per builder; `test_family_component_accepted_by_both_existing_id_patterns`; `test_shadow_paths_is_distinct_type` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_contracts.py` | `test_every_autonomy_module_is_classified`; `test_autonomy_core_modules_nautilus_free_at_runtime`; `test_autonomy_policy_not_mutable_from_src` (planted controls, including `StagePolicy(`, `dataclasses.replace`, `copy.deepcopy`); `test_autonomy_package_import_graph_is_acyclic`; `test_admissibility_predicate_has_one_home` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_envelope.py` | `test_autonomy_never_reads_or_writes_operator_controls` (tokens from `operator_controls.py:142`); `test_autonomy_never_touches_enablement_permit_or_firewall`; `test_autonomy_never_imports_order_path`; `test_autonomy_alert_egress_not_widened`; `test_autonomy_payload_hygiene_scan`; `test_family_source_read_only_by_resolver_and_child_env`; `test_no_asdict_in_autonomy`; `test_no_wall_clock_in_core`; `test_no_threads_or_asyncio_in_core`; `test_autonomy_never_passes_allow_draft_true`; `test_exec_client_never_edited` (reads the pin at `:36`). Each scan has a planted control and a minimum judged-module count | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_pins.py` | `test_pins_ceilings_within_arch_bounds`; `test_damping_ceilings[ceilings]`; `test_rollback_dwell_age_and_drill_headroom_ceilings`; `test_attest_cadence_has_no_expiry_gap[pins_invariant]`; `test_request_ttl_covers_two_schedule_polls`; `test_root_admit_ceiling_committed_false`; `test_halt_reason_class_map_is_exact`; `test_schedule_constants_equal_supervisor`; `test_code_identity_pins_cover_import_closure`; `test_engine_pin_history_retained`; `test_closure_manifest_equals_grimp_closure`; `test_enabled_widening_kinds_subset_of_widening_kinds`; `test_enabled_widening_kinds_subset_of_admission_implemented`; `test_root_admit_enabled_requires_ceiling_true`; `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[pins]`; `test_regen_output_is_literal_and_reproducible`; `/home/jon/breezy/tests/unit/test_autonomy_closure.py::test_closure_hash_runtime_under_budget` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_plugins.py` | `test_family_plugin_exact_set`; `test_refusing_plugin_refuses_every_member`; `test_capture_untagged_is_a_veto_reason`; `test_veto_reason_closed_set_equals_arch`; `test_compose_entry_vetoes_exception_is_registry_unreadable` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_owner_placeholders.py` | the 8 gate tests of AC 27; `test_require_owner_symbol_propagates_broken_owner_module` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_files_one_writer.py` | `test_autonomy_files_have_one_writer` | contract |
| `/home/jon/breezy/tests/unit/test_launch_window_table.py` | `test_no_unit_overlaps_launch_window[existing_units]`; `test_launch_path_units_end_before_next_fixed_point[existing_units]`. Verify `breezy-quote-tape-ingest-frequent` `TimeoutStartSec` first (R13) | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_verdict.py` | `test_differing_body_same_id_refused`; `test_verdict_id_excludes_produced_at`; `test_recompute_same_slot_same_inputs_same_verdict_id`; `test_verdict_validity_ceiling[writer]`; `test_verdict_exact_set_and_closed_enums`; `test_decimal_fields_canonical_strings` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_records.py` | exact-set and golden tests for lineage, root and refit_run; `test_label_arrow_schema_pinned_column_for_column`; `test_drill_marker_exact_set_and_absent_vs_dir_missing`; `test_two_roots_sharing_sha_write_identical_artefact_json`; `test_root_copy_exists_different_is_integrity`; `test_root_copy_rerun_after_chmod_0500_is_exists_equal` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_demand.py` | `test_producer_demand_flood_cannot_exhaust_integrity_slot`; `test_producer_demand_write_is_restrictive_only[writer_api]`; `test_demand_writer_refuses_unlisted_producer`; `test_producer_demand_idempotent_on_verdict_id`; `test_bad_demand_file_vetoes_venue[reader]` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_journal.py` | `test_journal_envelope_write_once_linked`; `test_journal_unknown_kind_refused`; `test_journal_seq_collision_fails_closed` | unit |
| `/home/jon/breezy/tests/unit/test_entry_guard.py` | `test_rung_net_position_veto_crosses_legs_and_families[double]`; `test_entry_guard_unreadable_index_vetoes`; `test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]`; `test_net_signed_qty_no_leg_is_short_yes` (each leg's terminal state); `test_negative_net_vetoes`; `test_empty_index_is_unreadable`; `test_open_intent_is_unreadable_and_checked_first`; `test_bad_slug_is_unreadable`; `test_guard_body_exception_is_unreadable`; `test_leg_suffix_equals_instrument_leg`; `test_leg_fill_fields_frozen`; `test_fill_index_key_matches_exec_client_writer` [a changed suffix or prefix turns it red]; `test_autonomy_exec_keys_disjoint_from_halt_prefixes` | unit |
| `/home/jon/breezy/tests/unit/test_registry_store.py` | `test_registry_transition_table_is_exact`; `test_bootstrap_seed_genesis_only`; `test_store_refuses_second_bootstrap_per_venue`; `test_registry_cas_and_idempotent_replay`; `test_registry_hash_chain_and_triggers` [deleting the UPDATE trigger turns it red]; `test_repeat_supersede_same_family_is_not_replay[arch0]`; `test_registry_readonly_open_engine_stopped`; `test_registry_reader_mode_ro_query_only` [`query_only=OFF` turns it red]; `test_family_artefact_binding_immutable`; `test_store_enforces_kind_mask_per_mode` [removing the mask turns it red]; `test_daily_refuses_widening_before_stage_flag`; `test_mint_unlimited_by_k_max_but_one_per_day`; `test_drill_mint_not_counted`; `test_nomination_columns_required_and_read_by_k_check[columns_required]`; `test_export_seq_monotone_and_newest_wins`; `test_drill_close_restore_at_most_one_per_venue_per_day`; `test_drill_close_restore_refused_for_drill_child`; `test_store_multirow_append_is_atomic`; `test_insert_or_replace_refused` [dropping the INSERT trigger and the pragma turns it red]; `test_on_conflict_do_update_refused`; `test_venue_seq_gap_refused_by_trigger`; **`test_first_row_venue_seq_must_be_one`** [removing `COALESCE` turns it red]; `test_partial_replay_refused`; `test_append_requires_concrete_mode`; `test_row_ts_skew_and_monotonicity_refused`; `test_writer_pragmas_read_back`; `test_store_sql_has_no_replace_or_ignore`; `test_admission_pending_refused_when_enabled_but_unimplemented`; `test_reader_refuses_foreign_ddl` [dropping one trigger in the fixture turns it red]; `test_reader_maps_every_sqlite_error`; **`test_reader_distinguishes_busy`** (live writer gives `busy`; spilled-then-killed writer gives `hot_journal`; unspilled killed writer reads committed rows; V12); `test_child_d0_and_trial_prefix_pinned[store]`; `test_hwm_reset_store_refuses_carried_counters_below_export[validate]` | unit |
| `/home/jon/breezy/tests/unit/test_registry_fold.py` | the whole AUT-5 r7 WP1 fold list (crosswalk); `test_post_launch_swap_cancel_voids_pair_only_before_1700`; `test_post_launch_swap_cancel_restores_incumbent[fold]`; `test_family_origin_from_introducing_row`; the promoted list below | unit |
| `/home/jon/breezy/tests/unit/test_registry_hwm.py` | `test_hwm_reading_from_bytes_maps_none_to_absent_and_garbage_to_unreadable`; `test_hwm_absent_construction_only_in_hwm_module`; `test_hwm_mid_chain_hash_mismatch_regressed` (rewritten prefix, longer head); `test_registry_hwm_refuses_regression`; `test_hwm_export_seq_above_newest_regressed`; `test_next_hwm_is_head_and_verified_export` | unit |
| `/home/jon/breezy/tests/unit/test_registry_replay.py` | `test_resolver_replays_validate_over_full_fold`; `test_forged_promote_without_resolvable_cause_refused`; `test_artefact_bytes_must_equal_row_sha_at_resolve`; `test_replay_refuses_carried_counters_below_prior_fold` | unit |
| `/home/jon/breezy/tests/unit/test_registry_resolver.py` | `test_resolver_binds_bytes_to_row`; `test_registry_paths_refuse_symlinks`; `test_verify_and_load_share_bytes[resolver]`; `test_child_manifest_equals_committed_root_except_allowlist`; `test_exit_gate_stays_code_only`; `test_registry_champion_requires_live_orders_gate_for_every_kind[resolver]`; `test_resolver_refusals_give_no_champion`; `test_root_resolves_under_live_orders_allowlist`; `test_rollback_to_root_reads_content_addressed_copy`; `test_family_source_registry_requires_bootstrap`; `test_node_relaunch_rule_family_id_and_seq_prefix[resolver]`; `test_child_d0_and_trial_prefix_pinned[resolver]`; `test_rollback_to_earlier_child_passes_d0_rule`; `test_resume_not_subject_to_d0_rule`; `test_root_admit_requires_own_allowlist_triple[resolver]`; `test_resolver_under_budget`; `test_resolver_refuses_chain_with_unenabled_widening_row` (hand-forged chain); `test_hwm_absent_with_rows_refuses`; `test_hwm_absent_on_genesis_only_chain_refuses`; `test_hwm_unreadable_refuses`; `test_export_absent_after_hwm_saw_export_refuses`; `test_export_dir_listing_error_is_export_unreadable`; `test_clock_before_head_refuses`; `test_two_senders_is_engine_inconsistency`; `test_manifest_identity_must_match_row`; `test_live_gate_routing_reads_manifest_kind`; `test_equality_covers_new_manifest_fields`; `test_halted_sender_resolves_with_entries_disallowed`; `test_resolver_never_returns_enabled_or_permit`; `test_draft_or_unpinned_manifest_refused`; `test_resolver_runs_prereg_check_on_source_dir`; `test_missing_manifest_dir_is_manifest_unreadable`; `test_root_record_identity_checked`; **`test_root_manifest_must_equal_committed_bytes`**; **`test_root_named_like_child_is_not_routed_as_child`**; `test_child_regex_root_must_equal_lineage_root`; **`test_resolved_family_carries_arch_c5_pickup_fields`**; **`test_shadow_resolution_ignores_hwm_and_cannot_send`**; `test_paths_role_mismatch_both_directions`; `test_admissibility_predicate_shared[resolver]` | unit |

**Promoted to real** (A-R3): `test_drill_promote_refuses_non_champion_sha`, `test_drill_refused_over_halted_incumbent`, `test_drill_budget_separate`, `test_drill_demote_and_halt_counters_capped`, `test_drill_row_refused_while_non_drill_cause_stands`, `test_resume_requires_every_cause_cleared`, `test_rollback_failed_resumes_only_under_trigger_class`, `test_drill_close_restore_at_most_one_per_venue_per_day`, `test_drill_close_restore_refused_for_drill_child`, `test_drill_close_restore_charges_no_drill_or_production_budget`, `test_drill_close_restore_refused_after_non_drill_cause`, `test_damping_ceilings[counting_rule]`, `test_carried_counters_are_floors`, `test_root_admit_exempt_from_d0_rule`, `test_root_admit_only_when_venue_has_no_sender[validate]`.

**AUT-5 r7 WP1 and WP2 crosswalk.** WP1 has 85 tests and WP2 has 16.

| AUT-5 r7 list (count) | ARCH-0 real | Split (real half / owner half) | Moved (owner) |
|---|---|---|---|
| WP1 envelope (6) | 6 | — | — |
| WP1 store (26) | 17 (the store list above) | 4: `test_repeat_supersede_same_family_is_not_replay` [arch0 / store→WP1b]; `test_nomination_columns_required_and_read_by_k_check` [columns_required / k_check→WP1b]; `test_child_d0_and_trial_prefix_pinned` [all real]; `test_hwm_reset_store_refuses_carried_counters_below_export` [validate / store→WP8] | 5 → WP1b: `test_nomination_refused_past_k_max_lifetime`, `test_nomination_refused_second_in_window`, `test_alpha_index_never_resets`, `test_two_pending_nominees_get_distinct_k`, `test_infeasible_nomination_charges_no_alpha[store]` |
| WP1 fold (25) | 24 | 1: `test_root_admit_only_when_venue_has_no_sender` [validate / engine→WP4] | — |
| WP1 replay (4) | 4 | — | — |
| WP1 demand (7) | 3 | 1: `test_producer_demand_write_is_restrictive_only` [writer_api / aut6_producer_ast→AUT-6] | 3 → WP4: `test_demand_archive_crash_between_copy_and_unlink_is_idempotent`, `test_demand_archive_differing_bytes_is_integrity`, `test_demand_archive_tmpfile_fallback_sweeps_named_temp` |
| WP1 single read, writer, plug-ins, ledger (5) | 5 | — | — |
| WP1 pins and closure (8) | 6 | 1: `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key` [pins / policy→WP3] | 1 → WP3: `test_policy_map_not_looser_than_fallback_map` |
| WP1 E-7/E-8 (4) | 1: `test_registry_reader_mode_ro_query_only` | — | 3 → AUT-5a: `test_submit_intent_record_extraction_is_move_only`, `test_classify_current_intent_states`, `test_submit_intent_record_module_has_no_file_io` |
| **WP1 total 85** | **66** | **7** | **12** |
| WP2 resolver (11) | 8 | 2: `test_verify_and_load_share_bytes` [resolver / loader→WP5]; `test_registry_champion_requires_live_orders_gate_for_every_kind` [resolver / engine→WP4] | 1 → AUT-5a: `test_containment_checks_read_directory_not_phantom_base` |
| WP2 entry guard (5) | 2 | 1: `test_rung_net_position_veto_crosses_legs_and_families` [double / adapter_reader→AUT-5a] | 2 → AUT-5a: `test_entry_guard_exact_key_reads_only`, `test_fill_reader_production_default_runs_once` |
| **WP2 total 16** | **10** | **3** | **3** |

AUT-5 r7 WP9's RED list has 7 tests. **4 ship green in ARCH-0**: `test_lineage_policy_allowlist_is_literal_only`, `test_child_requires_lineage_triple_and_policy_ruling`, `test_child_with_operator_ruling_refused` and `test_tampered_policy_ruling_refuses_child`. WP9 keeps `test_lineage_policy_allowlist_has_exactly_one_row`, `test_lineage_allowlist_row_equals_policy_pin` and `test_root_keeps_own_ruling`.

**Carried strict-xfail stubs** go in `/home/jon/breezy/tests/unit/test_autonomy_cross_area.py` unless a file is named. `[blocks]` is in brackets.

| Owner | Tests [blocks] |
|---|---|
| AUT-5 WP1b | the 5 moved nomination tests and `test_nomination_columns_required_and_read_by_k_check[k_check]` [PROMOTE]; `test_repeat_supersede_same_family_is_not_replay[store]` [SUPERSEDE, PROMOTE]; `test_prelaunch_writes_rollback_and_activate_atomically[store_atomic]` [ROLLBACK, ACTIVATE]; `test_resume_admission_reads_policy_block_bounds` [RESUME] |
| AUT-5 WP3 | `test_policy_block_not_looser_than_code_ceilings`; `test_promote_disabled_when_eta_after_kill`; `test_policy_map_not_looser_than_fallback_map`; `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[policy]` [PROMOTE] |
| AUT-5 WP4 | `test_verdict_acceptance_rules`, `test_verdict_accepted_after_attest`, `test_verdict_subject_sha_must_match_row`, `test_verdict_validity_ceiling[engine]`, `test_no_policy_fail_demotes_never_widens`, `test_demotion_never_requires_policy_and_is_immediate[engine]`, `test_intraday_engine_is_restrictive_only[engine]`, `test_resume_written_only_at_prelaunch[engine]`, `test_pending_write_uses_intraday_reconciliation[engine]`, `test_promotion_requires_reconciled_state`, `test_ambiguous_intent_cancels_swap_not_incumbent_launch`, `test_prelaunch_requires_post_stop_reconciliation`, `test_two_intraday_passes_inside_launch_window`, `test_intraday_pass_yields_to_prelaunch_lock`, `test_mirror_read_failure_is_integrity`, `test_root_admit_only_when_venue_has_no_sender[engine]`, `test_root_admit_requires_own_allowlist_triple[engine]`, `test_root_admit_refused_after_operator_halt_within_cooldown`, `test_root_admit_refused_on_stale_halt_mirror` [ROOT_ADMIT]; `test_attest_requires_every_listed_detector`, `test_attest_cadence_has_no_expiry_gap[schedule]`, `test_every_live_verdict_journaled_once_per_daily_pass`, `test_cause_verdict_ids_subset_of_acted_rows`, `test_retired_demand_file_archived`, the 3 `test_demand_archive_*`, `test_registry_champion_requires_live_orders_gate_for_every_kind[engine]`, `test_prelaunch_writes_rollback_and_activate_atomically[prelaunch]` [ACTIVATE] |
| AUT-5a (WP2, WP5 to WP8, WP10) | `test_hand_relaunch_without_registry_source_refused`, `test_family_source_fixed_in_unit`, `test_watch_actor_never_reads_projection`, `test_registry_unreadable_veto_clears_only_after_verified_read`, `test_attest_expiry_and_chain_staleness_veto_entries`, `test_demotion_latency_slo`, `test_transient_veto_writes_no_transition`, `test_restrictive_commit_failure_sets_node_veto`, `test_attest_veto_armed_after_first_attest`, `test_attest_veto_rearmed_only_after_post_swap_attest`, `test_engine_heartbeat_stale_vetoes`, `test_entry_veto_closed_before_first_tick_and_on_stale_tick`, `test_watch_actor_store_touches_stay_on_loop_thread`, `test_node_relaunch_rule_family_id_and_seq_prefix[node]`, `test_halted_family_boots_entries_vetoed_exits_live`, `test_resume_clears_registry_halted_without_relaunch`, `test_compose_refuses_without_entry_veto_slot`, `test_registry_veto_leaves_exit_seam_open`, `test_registry_unavailable_mints_no_permit`, `test_verify_and_load_share_bytes[loader]`, `test_node_loads_artefact_from_store_by_row_sha`, `test_champion_own_artefact_mismatch_at_load_is_integrity`, `test_swap_cannot_exceed_daily_budget_across_namespaces`, `test_drill_fills_spend_venue_budget`, `test_child_env_touches_only_registry_keys`, `test_child_env_drops_inbound_registry_keys`, `test_registry_shadow_logs_agreement_and_spawns_env_family`, `test_shadow_never_vetoes_or_arms_hand_relaunch_rule`, `test_relaunch_request_schema_exact_set`, `test_incumbent_boot_survives_child_ambiguous_intent`, `test_entry_guard_exact_key_reads_only`, `test_fill_reader_production_default_runs_once`, `test_entry_guard_cache_invalidated_on_fill`, `test_rung_net_position_veto_crosses_legs_and_families[adapter_reader]`, `test_bad_demand_file_vetoes_venue[actor]`, `test_post_launch_swap_cancel_restores_incumbent[supervisor]`, `test_containment_checks_read_directory_not_phantom_base`, the 3 `submit_intent_record` tests; **new in r3:** `test_admissibility_predicate_shared[watch_actor]`, `test_node_writes_hwm_at_boot_before_first_entry`, `test_watch_actor_busy_tick_is_unverified_not_veto`, `test_shadow_resolution_cannot_reach_build_child_env`, `test_l1_cutover_writes_initial_hwm_under_exec_flock`; HWM-reset: `test_hwm_reset_cli_journals_alerts_and_chains`, `test_hwm_reset_cannot_unhalt`, `test_hwm_reset_never_refunds_counters`, `test_resolver_resolves_after_hwm_reset`, `test_hwm_reset_store_refuses_carried_counters_below_export[store]`, **`test_hwm_absent_after_attest_clears_via_reset_cli`** [HWM_RESET] |
| AUT-5 WP11 + AUT-2 | `test_drawdown_producer_handshake_with_labels`; `/home/jon/breezy/tests/unit/test_drawdown_producer.py::test_drawdown_gates_on_labels_consumable`; `test_detectors_and_drawdown_include_drill_fills[drawdown]` |
| AUT-6 | `test_deliver_with_proof_reports_non_2xx_through_tee`, `test_critical_alerts_use_delivery_proof`, `test_detector_and_failure_mode_alerts_use_delivery_proof`, `test_critical_survives_sigkill`, `test_concurrent_drainers_send_at_most_once_per_claim_window`, `test_try_submit_latency_independent_of_webhook_latency`, `test_alerts_undeliverable_veto`, `test_alerts_undeliverable_reads_two_days`, `test_drill_inject_passes_when_marker_absent`, `test_drill_marker_read_error_never_resumes`, `test_drill_inject_mapped_only_in_clause`, `test_health_memory_sum_within_memavailable`, `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`, the three E-11 tests (new names), `test_producer_demand_write_is_restrictive_only[aut6_producer_ast]`, `test_detectors_and_drawdown_include_drill_fills[detectors]`, `test_shadow_detector_ignores_production_marker`, `test_production_detector_ignores_shadow_marker`, `test_fee_schedule_verdict_feeds_fee_verified_checks`, `test_shadow_probe_marker_accepted_only_under_shadow_root` |
| AUT-2 | `test_p_at_decision_is_bought_leg_probability`, `test_scorer_never_attributes_by_trial_id_prefix`, `test_voided_pair_fills_excluded_from_all_n`, `test_reconciliation_and_entry_guard_never_read_canary_store[reconciliation]`, `test_poststop_venue_read_is_get_only`, `test_retired_kind_keeps_scorer_until_last_fill_labelled`, `test_post_stop_producer_inconclusive_without_stop_signal`, `test_drill_fills_excluded_from_n_and_kill_clock` (with AUT-4) |
| AUT-4 | `test_window_cap_below_n_min_is_inconclusive`, `test_infeasible_nomination_charges_no_alpha[verdict]`, `test_calibration_leg_relative_inconclusive_below_min_buckets` |
| AUT-3 | `test_own_outcome_effect_not_vacuous`, `test_own_outcome_refused_below_min_gate_decisions` |
| AUT-1 (and scorer, evaluator, detectors, refitter) | `test_every_exit_fill_joins`, `test_decision_id_unique_per_take`, `/home/jon/breezy/tests/unit/test_autonomy_plugins.py::test_every_non_retired_manifest_resolves_to_full_plugins` with params `[capture]` AUT-1, `[scorer]` AUT-2, `[evaluator]` AUT-4, `[detectors]` AUT-6, `[refitter]` AUT-3 |
| AUT-7 | `test_rollback_restores_byte_identical_artefact`, `test_failed_rollback_halts_champion`, `test_drill_rollback_to_superseded_incumbent_admitted`, `test_rollback_fee_check_uses_verdict_not_node_memory`, `test_target_manifest_mismatch_marks_ineligible`, `test_target_byte_mismatch_ineligible_without_freeze[selection]`, `test_drill_halt_never_freezes_or_writes_exec_store[exec_store]`, `test_drill_timeline_matches_aut7_sequence`, `test_failed_drill_close_restored_at_next_prelaunch` [ROLLBACK; RESUME for the last] |

**Existing tests that pass unmodified after every seam commit:** `test_operator_control_assignment_scan`, `test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`, `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py`, `test_family_manifest.py`, `test_runtime_import_isolation.py` (its test bodies), and `test_forecast_quantile_ladder_manifest_and_markers.py`. Coverage is reported per WP. No threshold is invented.

## Work Packages (split into 2–4 commit-sized, independently-gated WPs with order; each ≤ ~800 changed lines)

**Sizing (A-R5, A3-R5).** The total is about 11,500 changed lines: about 4,500 in `src/` and about 7,000 in tests, fixtures and stubs.
- There are 8 WPs and 23 seam commits. **Each seam commit is merged on its own, followed by the full gate (L-43). No gated unit exceeds about 1,000 lines** (architect F13).
- Merges are serial and run in linear dependency order.
- At about 23 to 25 minutes of gate per merge, Wave 0 is about 23 gated merges. The early-start points below let Wave 1 overlap with it.

**Binding invariants block (I-1 to I-9).** The coordinator pastes this block verbatim into every WP brief. It is restated in each brief below.

> I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).

| WP / seam | Content | Imports (ARCH-0) | Est. lines | Activation |
|---|---|---|---|---|
| **WP-1a** | Delete the facade; `tests/support/entry_points.py`; import-free tests; one-time evidence (AC 4 (i) and (ii)) | — | 150 + 450 | **Live** (below) |
| **WP-1b** | Golden corpus and test on **unsplit** code; coverage evidence | — | 0 + 700 | Test only |
| **WP-1c** | `parse_family_manifest` split; `test_live_path_modules_import_set_pinned` | — | 120 + 80 | **Live** |
| WP-2a | `canonical`, `wire`; contracts (a), (b) and (c) seeded | canonical ← — ; wire ← canonical | 400 + 450 | None (library) |
| WP-2b | `single_read`; classification and runtime-import tests | — | 350 + 450 | None |
| WP-3a | `paths` (without `root_record`), `pins`, `veto`, `plugin`, `closure_manifest`, `closure`, regen script, `node_plugins`, `offline_plugins` | paths ← wire; closure ← single_read | 600 + 500 | None |
| WP-3b | `net_position`, `entry_guard`, key contract test | entry_guard ← net_position, veto | 250 + 450 | None |
| WP-4a | `autonomy_owner`, ledger, floor, envelope manifest, writer table, gate tests, envelope scans, launch-window test | pins | 0 + 900 | None |
| WP-4b | Carried stubs with no ARCH-0 symbol | — | 0 + 700 | None |
| WP-5a | `verdict`, `lineage`, `label_schema` | wire, canonical, single_read, paths, pins | 450 + 500 | None |
| WP-5b | `demand`, `drill_marker`, `rollback_journal` | same | 400 + 450 | None |
| WP-6a | `schemas` (including `StagePolicy`), `chain` | schemas ← wire, canonical, rollback_journal; chain ← canonical, schemas | 450 + 400 | None |
| WP-6b | Structural `fold` types plus kinds; `transitions` (ALLOWED, mask, structural validate, `rows_admissible`); `stage_policy` | fold ← schemas, pins; transitions ← fold; stage_policy ← transitions | 500 + 500 | None |
| WP-6c | `family_bytes`, `paths.root_record`, `write_root_copy`. **Precondition: E-14 filed** | single_read, paths, lineage, family_manifest | 300 + 450 | None |
| WP-6d | `registry_store` (DDL, triggers, append, reader, export) | chain, transitions, stage_policy, family_bytes | 600 + 700 | None |
| WP-7a | Full `fold` | schemas, pins | 450 + 550 | None |
| WP-7b | `validate` rule set (AC 13) | fold | 500 + 600 | None |
| WP-7c | `hwm` | wire, schemas, chain | 150 + 300 | None |
| **WP-8a** | `live_orders_gate` extraction and lineage gate | family_manifest | 120 + 450 | **Live** (below) |
| WP-8b | `replay` | transitions, fold, verdict, chain, family_bytes | 250 + 400 | None |
| WP-8c | `resolver` (sending and shadow); final contract lists | everything + live_orders_gate | 500 + 900 | None until AUT-5a sets `BREEZY_FAMILY_SOURCE` |

**Live-path activation (WP-1a, WP-1c, WP-8a).**
- Merge outside [16:30Z, 17:10Z).
- The node picks up the change at its next 16:50Z LAUNCH. The supervisor restarts in 01:00 to 16:40Z; `KillMode=process` keeps the node.
- Recorder and ingest pick it up at their next natural start. There is a technical reason, with evidence, not to force those restarts: AC 4's per-entry smoke and arrow-registry evidence prove that behaviour is unchanged, and a forced recorder restart costs capture continuity.
- AC 30 shows a mixed-version process is safe in the meantime (security F10).
- Revert is one file per seam.

**Early-start points (A3-R5; architect F10b).**

| Wave-1 area | May start building against frozen signatures after | Each consuming WP may merge only after |
|---|---|---|
| AUT-1a | WP-5b | WP-5b (veto, plugin, pins); `ResolvedFamily.registry_seq` reads after WP-8c |
| AUT-2a | WP-5b | WP-5b; the `LegFill` use after WP-3b |
| AUT-3a | WP-5b | WP-5b; fold reads after WP-7a |
| AUT-4a | WP-5b | WP-5b; `LineageTallies` reads after WP-7a |
| AUT-6 | WP-5b | WP-5b (demand, verdict); fold consumption after WP-7a |
| AUT-5a | WP-8c | WP-8c; WP1b work after WP-7b |
| AUT-7a | WP-8c | WP-8c (`verify_family_bytes`, `append`, journal) |

### WP briefs

Each brief below is the coordinator's dispatch skeleton, and each one restates I-1 to I-9.

- **WP-1 (1a, 1b, 1c): live-path prep.**
  - **I-1 to I-9 apply verbatim.**
  - RED first: `test_persistence_has_no_facade_consumers` (planted control), `test_parse_split_matches_presplit_golden` (green on unsplit code, then unchanged), `test_live_path_modules_import_set_pinned`.
  - Evidence:
    - the grimp reachability diff and the per-entry `_SCHEMAS` diff (old vs scratch);
    - `coverage run --branch` showing 100% of `family_manifest.py:262-282` and `:285-460`;
    - `diff` of the moved helpers against `git show d231497d:tests/unit/test_runtime_import_isolation.py` lines 158-190, which must be empty, plus exactly the one parameter hunk for `:192-216`;
    - `git diff` of `test_runtime_import_isolation.py` touching only imports and helper removal;
    - the `test_entry_module_list_covers_every_entry_point` and `test_mypy_ratchet` outputs.
  - Stop if any entry's arrow set differs without a reviewed reason.
- **WP-2 (2a, 2b): bytes and I/O.**
  - **I-1 to I-9 apply verbatim.**
  - RED: the wire and canonical goldens, `test_read_refuses_fifo_without_blocking`, `test_write_once_exists_equal_creates_no_temp`.
  - `lint-imports` shows contracts (a), (b) and (c) kept.
- **WP-3 (3a, 3b): pins, plug-ins, guard.**
  - **I-1 to I-9 apply verbatim.**
  - RED: `test_veto_reason_closed_set_equals_arch`, `test_fill_index_key_matches_exec_client_writer` (mutation: change `"^no"`), `test_leg_fill_fields_frozen`.
  - The exec client is read by AST only.
- **WP-4 (4a, 4b): ledger and envelope.**
  - **I-1 to I-9 apply verbatim.**
  - Verify R13 (`TimeoutStartSec`) first.
  - RED: `test_owner_placeholder_ledger_matches_markers` with a planted mismatch, and `test_every_envelope_node_id_collected_and_unskipped` with a planted skip.
- **WP-5 (5a, 5b): records.**
  - **I-1 to I-9 apply verbatim.**
  - Check the ARCH C4 fields for any non-integer JSON number first. If one exists, stop and raise it.
  - RED: `test_differing_body_same_id_refused` (mutation: drop the EEXIST compare).
- **WP-6 (6a to 6d): store core.**
  - **I-1 to I-9 apply verbatim.**
  - 6c waits for E-14 to be filed.
  - RED: `test_first_row_venue_seq_must_be_one` (mutation: drop COALESCE), `test_reader_distinguishes_busy`, `test_autonomy_policy_not_mutable_from_src` (planted `StagePolicy(`), `test_two_roots_sharing_sha_write_identical_artefact_json`.
- **WP-7 (7a, 7b, 7c): fold, rules, HWM.**
  - **I-1 to I-9 apply verbatim.**
  - RED: the promoted list, `test_hwm_mid_chain_hash_mismatch_regressed`, `test_hwm_reading_from_bytes_maps_none_to_absent_and_garbage_to_unreadable`.
- **WP-8 (8a, 8b, 8c): lineage gate, replay, resolver.**
  - **I-1 to I-9 apply verbatim.**
  - 8a is live-path and needs the coverage evidence for the three ruling sites.
  - RED: `test_root_manifest_must_equal_committed_bytes`, `test_root_named_like_child_is_not_routed_as_child`, `test_resolved_family_carries_arch_c5_pickup_fields`, `test_shadow_resolution_ignores_hwm_and_cannot_send`, `test_hwm_absent_on_genesis_only_chain_refuses`, `test_export_dir_listing_error_is_export_unreadable`, `test_resolver_refuses_chain_with_unenabled_widening_row` (hand-forged chain).

## Binding note for the AUT-5a brief

The coordinator copies this section into the AUT-5a brief verbatim.

1. **WP1b (admission completion)** is a named AUT-5a WP, scheduled before AUT-5 WP10 L1. Its scope:
   - (a) thread the filed policy block's stricter values into `transitions.validate`; the ceilings stay the bound;
   - (b) nomination k-checks, replacing `NominationRequiresPolicy`;
   - (c) HWM_RESET store admission, jointly with WP8 (the B9 export-floor read inside `append` plus a restrictiveness check), replacing `RuleSetPending`;
   - (d) a per-kind completeness review against ARCH C5 and AUT-5 r7 §3.2;
   - (e) each kind is added to `_ADMISSION_IMPLEMENTED` **in the same commit** that clears its `blocks_kinds` rows.
2. **The RESUME subset merges before the L1 pins commit `ENABLED_WIDENING_KINDS = {RESUME}`.** It covers:
   - the policy-threaded `RESUME_COOLDOWN_H`, `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D`, `MAX_INFRA_RESUMES_PER_VENUE_7D` and `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` (`test_resume_admission_reads_policy_block_bounds`);
   - a re-review of the rules that are already real (every standing cause cleared, ROLLBACK_FAILED only under the trigger class, E-5 restore including `test_failed_drill_close_restored_at_next_prelaunch`, swap-pending refusal, terminal and INTEGRITY freezes, the PRELAUNCH-only mask);
   - then `_ADMISSION_IMPLEMENTED = {RESUME}`.

   Every other widening kind needs WP1b complete before the L2 flag commit.
3. **`_ADMISSION_IMPLEMENTED` is code, not a pin.** It is read only through `stage_policy.STAGE`. `StagePolicy` is never constructed or replaced in `src/` (AC 15).
4. **Narrowing.** Narrowing `ENABLED_WIDENING_KINDS` below a kind that already has production rows makes the resolver and the watch actor refuse, so there is no sender. The rollback lever is `breezy-registry-hwm-reset` plus a reviewed commit, never a narrowing commit.
5. **`_tick_once` calls `transitions.rows_admissible(new_rows, stage=STAGE)` before `validate`.** A refusal gives `registry_unreadable` plus CRITICAL `REGISTRY_REGRESSED`, and the HWM does not advance. This keeps launch and runtime admissibility identical (`test_admissibility_predicate_shared[watch_actor]`).
6. **HWM obligations (A3-R2).**
   - (a) **Decoding.** HWM bytes from the exec store (read-only, G6) are decoded only through `hwm_reading_from_bytes`. A missing key gives `HwmAbsent`; any error gives `HwmUnreadable`.
   - (b) **Node boot write.** Right after a successful `resolve_sending_family` and **before the entry-veto slot opens**, the node writes `next_hwm(chain, export_seq=<verified>)` under the exec flock. A failed write keeps entries vetoed (`registry_unreadable`) until a tick writes it (`test_node_writes_hwm_at_boot_before_first_entry`).
   - (c) **Ticks.** The watch actor writes only `next_hwm` values after a verified read, and never moves the HWM backward.
   - (d) **L1 cut-over.** `/home/jon/breezy/scripts/ops/autonomy_l1_cutover.py` writes the **initial HWM** (the genesis head, `export_seq=0`) under the exec flock while the node is down. This runs after the 16:40:05 bootstrap has exited and before 16:50Z LAUNCH (`test_l1_cutover_writes_initial_hwm_under_exec_flock`). From then on, `HwmAbsent` with any row always refuses.

     The cut-over **creates `evidence/registry/`** with the bootstrap. A missing directory gives `export_unreadable`. The cut-over's own rollback, before LAUNCH, deletes the key it wrote (a reversible step with a one-line heads-up), because Y7 refuses a non-registry boot while the key exists.
   - (e) **Clearing path (L-48).** `breezy-registry-hwm-reset` (AUT-5 WP8) is the named recovery for `hwm_absent` and `hwm_regressed`. It must also handle the case before the first export, verifying from genesis with `export_seq=0` (`test_hwm_absent_after_attest_clears_via_reset_cli`).
7. **Shadow source.** Under `registry_shadow`, the supervisor and the watch actor call **`resolve_shadow_family`** on the `AutonomyPaths.shadow` root, and they are added to `SHADOW_CALL_SITES` in the same commit. `ShadowResolution` is only logged (`agree=<bool>` on `family_id`) and never reaches `build_child_env`, which is typed on `ResolvedFamily` (`test_shadow_resolution_cannot_reach_build_child_env`). The shadow HWM stays in memory.
8. **`RegistryUnreadable.reason`.**
   - Watch actor: `busy` means the tick is not verified and state is unchanged, so three busy ticks reach `registry_unreadable` through `WATCH_TICK_STALE_S`. `hot_journal`, `schema_mismatch`, `io` and `sqlite_error` set `registry_unreadable` immediately (`test_watch_actor_busy_tick_is_unverified_not_veto`).
   - Supervisor: it may retry a `busy` resolve once within its own bounded LAUNCH budget, and refuses otherwise.
   - The engine's read-write open under `engine.lock` rolls back a hot journal.
9. **Bootstrap root copies (E-14).** Bootstrap calls `family_bytes.write_root_copy` for each seed **before** the genesis COMMIT, and chmods the directories to 0500 after the last copy. A rerun is EXISTS_EQUAL.
10. **Other obligations.**
    - Import `VetoReason` from `persistence/autonomy/veto.py`.
    - The callable `entry_veto` type is defined in strategy.
    - Drop the package-wide Nautilus ban (AUT-5 r7 `:841`) in favour of contracts (b) and (c) plus classification.
    - `append` requires `now_ns`.
    - The E-8 decoders belong to AUT-5a, and AUT-6 aliases them.
    - The derived-caches DDL belongs to WP4.
    - The `PolymarketUsFillReader` prefixes ids with the imported `FILL_INDEX_KEY_PREFIX` and returns `FillIndexAbsent` only for a missing key.
    - The guard cache type is `dict[base_slug, GuardResult]`.
    - The node, supervisor and settings consume `ResolvedFamily.family_bytes`, `registry_seq` and `chain_head`, and never re-read the manifest.

## Risk Register

| # | Risk | Evidence | Mitigation / owner |
|---|---|---|---|
| R1 | Root-copy collision | V20 | E-14 as amended. WP-6c waits for it. Fail-closed either way |
| R2 | Contract (b) vs E-12, and the unsatisfiable pyarrow clause | AUT-1 r12 `:229-238`; V16 | Split contracts (b) and (c); classification (AC 1, AC 2) |
| R3 | `EntryVeto` name collision | AUT-1 r12 `:433` | No alias |
| R4 | Double extraction of the halt decoder | AUT-6 r15 `:1664` | Closed by A-R6 |
| R5 | `drill_marker/v1` field sets | AUT-7 r5 `:363` | AUT-7's 12 keys |
| R6 | `net_position` weight; AUT-2 needs a timestamp | V1; AUT-2 r7 `:335` | No domain import; `LegFill.ts_event_ns` frozen |
| R7 | Facade removal drops an eager `register_arrow` side effect | V15 | One-time static and runtime evidence per entry; permanent smoke; revert is one file |
| R8 | WP sizes | estimates | 23 seam commits ≤ ~1,000 lines, each gated |
| R9 | Stale or wrongly-failing carried test | — | Narrow `OwnerPending`; staleness and owner-id tests |
| R10 | Early widening via a pins commit | memories | Stage flag, `_ADMISSION_IMPLEMENTED`, the resolver and watch-actor `rows_admissible`, and the construction ban |
| R11 | Concurrent agents | L-51 | Per-WP worktree; re-gate before merge |
| R12 | `unshare -r` runs as uid 0 | `run_tests_no_egress.sh:45-50` | Modes via `stat`; SQLite `mode=ro` |
| R13 | Orphaned ingest timer row | AUT-6 r15 `:1656` | Verify first in WP-4a |
| R14 | **Same-uid consistent forgery** (security F3) | ARCH C5 | Accepted residual, with the windows stated. **W1:** a restrictive row appended while no node watches (16:40 to 16:50Z, or any node-down period) and before the next export can be rewritten back to the prior head undetected. The node boot HWM write narrows W1 to the interval before the first resolve. **W2:** r2's genesis-only `HwmAbsent` window (about 26 h) is **closed** in r3, because Absent always refuses. A wholesale consistent forgery of chain, HWM and exports remains possible. The E-14 0500 chmod is hygiene, not a control. The external anchors are the committed `deploy/families` bytes, the allowlists, `live_orders_gate`, and the reviewed code |
| R15 | Demand-flood DoS until AUT-5 WP4's archive exists | security L2 | Fail-closed and restrictive only |
| R16 | Narrowing after rows exist refuses resolution | — | Binding note 4; a shared predicate, so launch and runtime agree |
| R17 | Resolver closure carries about 48 MB of pyarrow | V2 | Accepted against the 4 G budget |
| R18 | `pins.py` is outside `closure_sha256` | security L3 | `live_proof_paths()` (AUT-5 WP4); reviewed commits |
| R19 | Live-path WPs (1a, 1c, 8a) | security F10 | Merge window; AC 30 import pin; supervisor restart window |
| R20 | `HwmAbsent` refusal blocks LAUNCH if the cut-over HWM write fails (L-48) | AC 16 | Restrictive, with no sender. Clearing paths: re-run the cut-over HWM step with the node down, or `breezy-registry-hwm-reset` (binding note 6e) |
| R21 | Venue-global intent veto deadlock | node memory (terminal-leaves deadlock) | Documented scope; the existing intent-retirement path clears it; AUT-6 alerts on a standing veto |
| R22 | Entry-point smoke cost | V14 (about 55 entries) | Budget ≤ 60 s, measured in WP-1a. Above that, restrict to entries whose closure reaches `catalog`, using the evidence |

## LESSONS Compliance

Every number was checked against its `docs/core/LESSONS.md` header on 10-03.

| Lesson | How the plan complies |
|---|---|
| L-1 | Null-hypothesis table below |
| L-12 | Exact sets; the split is a pure move proven by a golden plus coverage; the allowlist ships empty; the HWM is a refinement, not a relaxation |
| L-14 | `RefusalReason`, `VetoReason` and `UnreadableReason` are derived from ARCH and probes; the AST enum equals the params |
| L-16 | No timers; an exception in a veto composer is `registry_unreadable` |
| L-19 | The facade removal is simulated statically and at runtime (V2, V15) |
| L-22 | Frozen `STAGE`, the construction ban and private seams |
| L-24 | Hand-forged chains for the resolver widening and HWM tests |
| L-29 | No diagnostics buffers; no module-level mutable state |
| L-33 | Mutation evidence per guard test |
| L-39 | No operator-control environment-variable names; scan tokens come from `operator_controls.py:142` |
| L-42 | Guard fixtures use the real `DurableFillRecord` shape; the key contract against the real writer (V13) |
| L-43 | Full gate after every seam commit |
| L-44 | Netting tested at each leg's terminal state |
| L-46 | Contract tests grepped first: archive contract, probe containment, exec pin, mypy ceilings (V17) |
| L-47 | Every new code fact carries a file:line or a probe (V11 to V21); r2's wrong claims are corrected (V12, V16, V19) |
| L-48 | Every refusing latch has a named clearing path: `hwm_absent` and `hwm_regressed` → reset CLI or cut-over step; intent veto → intent retirement; restrictive writes never blocked |
| L-50 | Writer table plus write-once |
| L-51 | Exact interpreter; no `uv`, `pip` or `stash` |
| L-54 | Pin search done (V17); `tests/support/entry_points.py` is extracted with one stated parameter; the mypy ceiling is only lowered |
| L-55 | `[adapter_reader]` runs the production `FillReader` once (AUT-5a) |

**L-1 null-hypothesis rows.** Each row records the existing capability checked and the verdict.
- C5 store: SQLite with triggers (V4, V11) → **native SQLite**.
- Exact-set records: stdlib `json` hooks → **reuse**.
- Atomic files: `os.link` and `os.replace` through dirfds → **stdlib**.
- Single read: none in Nautilus → **build** (small).
- `mode=ro` reader: SQLite URI → **reuse**.
- Resolver checks: `live_orders_authorized` and `load_family_manifest` → **reuse** by extraction and split.
- Netting: `DurableFillRecord` semantics (`client.py:923-1066`) → **restate**, contract-tested (V13).
- C6: Protocols → **build**.
- Closure: grimp → **reuse**, gate-only.
- Journal → **build** on write-once.
- Import isolation: the `runtime/__init__.py` precedent → **reuse**.
- Arrow-registry evidence: Nautilus `_SCHEMAS` (V15) → **reuse** read-only.

## Trade-offs (options considered, evidence, choice)

| Decision | Options | Choice and evidence |
|---|---|---|
| `persistence/__init__` | lazy PEP 562; delete | **Delete** (V3; precedent) |
| Reachability proof | a grimp test in the gate; one-time evidence plus smoke | **One-time static and runtime evidence, plus permanent smoke** (architect F10c, security F4) |
| `HwmAbsent` on genesis | allow (r2); always refuse with the cut-over writing the HWM | **Always refuse** (A3-R2). Closes the 26 h W2 window; the clearing paths are named |
| Shadow resolution | an HWM flag on one function; a separate function and type | **Separate function and type**, so it cannot satisfy the sending port (A3-R2) |
| Root or child | regex; chain `origin` | **Chain origin**, with the regex only as a Y6 consistency check (security F8) |
| Root manifest source | either directory; committed only | **`deploy/families` only, REPO policy** (A3-R1) |
| Entry-guard key | ARCH-0 owns the full key; ARCH-0 owns ids and the adapter prefixes them | **Ids in ARCH-0 plus an AST contract on the writer**; keeps AUT-5 r7 `:116`'s `fill_index(instrument_id)` and venue portability |
| `StagePolicy` location | `stage_policy.py`; `schemas.py` | **`schemas.py`** (no cycle; architect F14) |
| Contract (b) | one list ↛ nautilus, domain, pyarrow; split | **Split into (b) and (c)** (V16) |
| Helper extraction | duplicate; extract with a parameter | **Extract with one stated parameter**, plus diff evidence (architect F12, security F9) |
| AUT-4 tally source | `lineage_counters` cache (WP4); pure fold `LineageTallies` | **Fold tallies.** No WP4 dependency; same data |
| Lineage gate placement | WP-1; just before the resolver | **WP-8a** (architect F10a). The live surface of WP-1 stays minimal |
| Fold-decidable rules | defer; implement | **Implement** (A-R3) |
| Derived caches | ARCH-0; WP4 | **WP4** (YAGNI) |

## Confidence Self-Assessment (HIGH|MEDIUM|LOW + explicit unknowns)

**HIGH for design, MEDIUM-HIGH for schedule.** Every r2 finding is closed with code-level enforcement or a test, and the new code claims are probed. The unknowns are:
1. E-14 must be filed before WP-6c.
2. The entry-point smoke time is measured in WP-1a (R22).
3. The golden corpus may need more mutations than the 16 in r2 to reach 100% branch coverage. Coverage, not a count, decides.
4. The initial `CAUSE_CODES` and `DEMAND_REASONS` are closed choices, widened only by a reviewed L-12 change.
5. The ingest `TimeoutStartSec` is verified first in WP-4a.
6. A C4 non-integer JSON field, if one exists, stops WP-5a.
7. AUT-5a must accept binding notes 5 to 9, including the cut-over HWM write and its rollback deletion.

## §R3 Disposition

**r2 findings.**

| Finding | Disposition | Where |
|---|---|---|
| sec 1 (HIGH) root manifest anchor | FIXED: a root reads `deploy/families/<id>.json` under REPO; sha == row; `test_root_manifest_must_equal_committed_bytes`; E-14 rule 3 `committed_path` exact | AC 17; Edge Cases; E-14 |
| sec 2 (HIGH) HWM at head only | FIXED: hash check at `hwm.venue_seq`; `hwm_reading_from_bytes` is the only decoder; `HwmAbsent` construction banned elsewhere | AC 16; WP-7c |
| sec 3 rollback windows | FIXED: W1 and W2 stated; node boot HWM write; listing error → `export_unreadable`; W2 closed by always refusing Absent | AC 16, 17; R14; binding note 6 |
| sec 4 runtime arrow-registry equivalence | FIXED as one-time per-entry `_SCHEMAS` evidence (V15) plus permanent smoke (per architect F10c) | AC 4 |
| sec 5 `StagePolicy` rebuild | FIXED: construction, `replace`, copy and `_build` banned outside `stage_policy.py`, each with a planted control | AC 15 |
| sec 6 corpus sufficiency | FIXED: 100% branch-coverage gate including containment; artefact and symlink-escape fixtures; ruling-site coverage; the `exists()` semantics stated (load keeps it; callers refuse a missing directory) | AC 20, 21 |
| sec 7 guard fail-opens | FIXED: key contract against the pinned client (V13); `open_intent_blocks` called first with a global-scope docstring; R21 | AC 22 |
| sec 8 child-ness by name | FIXED: `FamilyView.origin`; the regex is a consistency check; `test_root_named_like_child_is_not_routed_as_child` | AC 14, 17 |
| sec 9 shared contract test file | FIXED: byte-diff evidence; one stated parameter; assertions unchanged | File plan; WP-1 brief |
| sec 10 live-node merge | FIXED: AC 30 import-set pin and the mixed-version argument | AC 30; R19 |
| sec 11 shared-sha roots | FIXED: three root-copy tests | AC 28 |
| arch 1 (HIGH) `ResolvedFamily` fields | FIXED: `registry_seq`, `chain_head`, `FamilyBytes`; pickup test | AC 19 |
| arch 2 (HIGH) stage S and Absent liveness | FIXED: `resolve_shadow_family` and `ShadowResolution`; cut-over HWM write; reset CLI named | AC 18; binding notes 6, 7 |
| arch 3 NULL first row | FIXED: COALESCE plus NOT NULL, probed (V11); `test_first_row_venue_seq_must_be_one` | AC 8 |
| arch 4 launch/runtime split | FIXED: `rows_admissible` shared; binding note 5 | AC 13 |
| arch 5 BUSY lumped | FIXED: `UnreadableReason` (5 members); V12 shows hot journal is distinguishable, so r2's claim is withdrawn | AC 12 |
| arch 6 amendment list incomplete | FIXED: full list | §ERRATA (b) |
| arch 7 AUT-6 citation | FIXED: AUT-6 r15 `:1474` consumes the fold, not the resolver | Stub table |
| arch 8 `LegFill` | FIXED: `ts_event_ns`, frozen test | AC 22 |
| arch 9 E-14 scope and order | FIXED: rule 3 applies to roots only; rule 6 write order and idempotence | E-14 |
| arch 10a/b/c schedule | FIXED: lineage gate is WP-8a; early-start table; one-time grimp evidence | WPs |
| arch 11 `root_record` placement | FIXED: added in WP-6c | WPs |
| arch 12 entry_points not move-only | FIXED: one parameter stated; pin search (V17) | File plan |
| arch 13 WP vs gate unit | FIXED: per-seam gating ≤ ~1,000 lines | WPs; AC 29 |
| arch 14 cycle | FIXED: `StagePolicy` in `schemas`; acyclic test | AC 15 |
| arch 15 single-read exemption | FIXED: named exemption | AC 7 |
| arch 16 chatter line | FIXED | — |
| New: V16 unsatisfiable pyarrow contract | FIXED: contracts (b) and (c) | AC 1 |

**r1 findings carried forward from §R2.** All remain FIXED in r3:
- python B1–B5 and P-n1–P-n13: AC 1–3, 5–12, 23–29. P-n5 accepted; P-n7 fixed differently (facade deleted).
- security H1–H7: AC 13, 15, 16, 17, 20, 21, 22.
  - H2 `permit_present` parameter: REJECTED (M7).
  - H4 node-marker variant: REJECTED (a same-uid file); superseded by the r3 always-refuse rule.
- security M1–M11 and L1–L5: AC 5, 10–12, 17, 24, 30; R15, R18. M6 role-label path: REJECTED (`path` drives containment, V9).
- architect H1–H6, M1–M6 and L1–L5: AC 2, 4, 13, 23, 25, 27; crosswalk; stub owner rows; binding note. L3 moot.
- security observation (defer records): REJECTED (ARCH §5.1 assigns them).
- A-R4 and A-R6: E-14 and the owner rows.

## §ERRATA-REQUEST

**(a) E-14, final text, to be filed verbatim:**

> **E-14 (coordinator, 2026-10-03; from ARCH-0 seam A r1–r3 and the r1/r2 architect and security reviews): per-family root records.**
> - **Defect.** ARCH C3 "Bootstrap roots" (line 261) writes one `root.json` per `derived/artefacts/<model_class>/<sha>/`. `pm_us_crh_v4` and `pm_us_crh_cont` are both `continuous_rung_hold` with `density_artefact_sha256 = 247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65` (the `not_applicable_density.json` placeholder) and both are RETIRED seeds (line 738). Their `root/v1` bodies differ in `family_id` and `manifest_sha256`, so the second write-once returns EXISTS_DIFFERENT and the genesis BOOTSTRAP cannot complete.
> - **Rule.**
>   1. A root copy is written to `derived/artefacts/<model_class>/<sha>/artefact.json` (0444) and `derived/artefacts/<model_class>/<sha>/roots/<family_id>.json` (0444, `root/v1`, fields unchanged). This replaces `<sha>/root.json` in ARCH C3 line 261, AUT-5 r7 §3.2 lines 172 and 180, and AUT-7 r5 line 41 and `test_rollback_to_root_reads_content_addressed_copy` (line 569).
>   2. A root copy's model class is `f"{composition_kind}:{ROOT_ARTEFACT_COMPONENT}"` with `pins.ROOT_ARTEFACT_COMPONENT = "density_table"`; a root's artefact is its manifest's density artefact.
>   3. **Scope: families whose introducing row is BOOTSTRAP or ROOT_ADMIT with `lineage_root_family_id == family_id` ("roots"), whatever the authorising kind (BOOTSTRAP, ROOT_ADMIT, ROLLBACK, RESUME).** For a root the resolver (a) reads the manifest only from `deploy/families/<family_id>.json` in the repo (never a registry copy) and refuses `manifest_sha_mismatch` unless its sha256 equals `row.manifest_sha256`; (b) reads `roots/<row.family_id>.json` and refuses `root_record_mismatch` unless `record.family_id == row.family_id`, `record.manifest_sha256 == row.manifest_sha256`, `record.artefact_sha256 == row.artefact_sha256`, and `record.committed_path == "deploy/families/" + family_id + ".json"` exactly. Children are out of scope: a Y2 no-new-lineage child resolves `artefact.json` in the existing `<sha>/` directory and has no `roots/` record; a new-lineage child is bound by its C3 `lineage.json`.
>   4. A second root sharing a `<sha>` directory writes `artefact.json` as an EXISTS_EQUAL no-op. EXISTS_DIFFERENT on `artefact.json` or on a `roots/<family_id>.json` is INTEGRITY.
>   5. The `<sha>/` and `roots/` directories become 0500 after the genesis transaction's last copy. This is hygiene, not a control (same-uid residual, R14).
>   6. **Order and idempotence.** Every copy is written before the genesis BOOTSTRAP COMMIT. A crash and rerun is idempotent: an existing file with equal bytes is EXISTS_EQUAL, decided by reading it before any temp file is created, so a rerun succeeds even after the rule-5 chmod.
> - **Consumption.** ARCH-0 seam A (`paths.root_record`, `family_bytes.write_root_copy`, resolver); AUT-5a bootstrap; AUT-7 r5 root reads. Fail-closed until filed: BOOTSTRAP refuses and nothing goes live.

**(b) The complete list of ARCH and plan text that r3 amends.** The coordinator records these alongside E-14.

**ARCH C5**
1. Resolver, "checks the export prefix and the node high-water mark": refined (L-12) to a tri-state HWM with mid-chain hash verification; `HwmAbsent` refuses on any non-empty chain; `Hwm` gains `export_seq`; a listing error is `export_unreadable`.
2. Shadow stage: resolution goes through `resolve_shadow_family` and `ShadowResolution`.
3. Y6: root and child status comes from the chain's introducing row. The regex root is a consistency check on top.

**AUT-5 r7**
4. §3.1 `__init__` "Public names only" → docstring only.
5. §3.1 `single_read` "`lstat` walk" → openat walk with an EXISTS_EQUAL pre-read.
6. §3.1 `VetoReason` defined in `registry_watch_actor` → imported from `persistence/autonomy/veto.py`.
7. §3.1 `schemas.py` records → owner rows. `StagePolicy` lives in `schemas.py`.
8. `:116` `entry_guard`: `legs` → `venue_suffix`; `bool | GuardUnreadable` → `GuardResult`; `FillReader.fill_index` returns `tuple | FillIndexAbsent`; adds `open_intent_blocks()`; `FillRow` gains `ts_event_ns`.
9. `:410` `parse_family_manifest(raw, *, origin)` → `(raw, *, path, allow_draft=False)`. The node consumes `ResolvedFamily.family_bytes`.
10. `:421` busy handling keyed on `RegistryUnreadable.reason == busy`.
11. `:423` `_tick_once` calls `transitions.rows_admissible` before `validate`.
12. `:425` adds the node boot HWM write before the entry slot opens. `:426` shadow → `resolve_shadow_family`.
13. `:427` guard cache `bool | GuardUnreadable` → `GuardResult`.
14. `:441` `resolved_registry_seq` = `ResolvedFamily.registry_seq`, the verified head.
15. `:480-488` `breezy-registry-hwm-reset` handles the case before the first export, and is the named clearing path for `hwm_absent`.
16. WP1 Files `:841` package-wide Nautilus ban → contracts (b) and (c) plus classification.
17. §3.2 DDL: `NOT NULL` on `venue` and `venue_seq`; the COALESCE gap trigger; `user_version` and `application_id`.
18. §3.2 append: `PartialReplay`; required `now_ns`; ts skew; `AdmissionPending`; caches deferred to WP4.
19. §3.2 export trailer gains `schema`, `venue` and `evidence_journal_heads`.
20. §3.2 lines 172 and 180 → E-14.
21. §4 ledger: tuple gains `owner_symbol` and `blocks_kinds`; `raises=OwnerPending`; E-11 rename at `:825`.
22. WP1 and WP2 RED lists → the crosswalk.
23. WP9 RED list `:927`: 4 of 7 ship in ARCH-0. WP9 keeps `test_lineage_policy_allowlist_has_exactly_one_row`, `test_lineage_allowlist_row_equals_policy_pin` and `test_root_keeps_own_ruling`, adds the single row, and routes child manifests.
24. WP10 L1 cut-over `:937` gains (i) creating `evidence/registry/` and (ii) the initial HWM write under the exec flock between the bootstrap exit and 16:50Z, with deletion of that key in the pre-LAUNCH rollback.

**AUT-7 r5**
25. `:56`, `:703` `verify_family_bytes(row)` → `(row, *, paths, repo_root, origin)`.
26. `:91`, `:506`, `:703` `append_journal(paths, kind, venue, record, *, ts_ns)`; bare kind names, with `schema` set to `rollback_decision/v1`; `append(..., now_ns)`.
27. `:41`, `:569` → E-14.

**AUT-4 r11**
28. `:18`, `:404`, `:1372` (AH5) lazy `__init__` → facade deleted. The closure-test outcome is identical.
29. `:431`, `:563` read `lineage_counters` → read `fold(...).lineages[*].tallies` (`LineageTallies`, pure), so there is no dependency on AUT-5 WP4.

**AUT-2 r7**
30. `:68`, `:116`, `:631` `net_position.py` is created by ARCH-0 and modified by AUT-2; it imports no `breezy.domain`.
31. `:335` netting uses `LegFill.ts_event_ns`.

**AUT-6 r15**
32. `:2254` is stale; the ER-2 name at `:1746` wins.
33. `:512` the verdict date comes from `write_verdict`.
34. `:1474` consumes the fold, which is correct. No change, but the r2 stub-table citation is corrected.

**AUT-1 r12**
35. `:1237` `SELF_HEAL_RESTARTABLE_UNITS` is stale (E-11). `EntryVeto` names only the C1 record.
36. `:329` `DecisionRecord.registry_seq` = `ResolvedFamily.registry_seq`.
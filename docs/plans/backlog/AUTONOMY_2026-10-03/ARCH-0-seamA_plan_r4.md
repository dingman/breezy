# ARCH-0 seam A: persistence core build plan, r4

**Round.** r4, dated 2026-10-03. It revises r3 (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r3.md`) and resolves every finding in `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamA-r3-security.md` (APPROVE, findings 1–9) and `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamA-r3-architect.md` (REQUEST_CHANGES, findings 1–15). It follows every binding coordinator ruling in `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-r1-merged.md`: A-R1 to A-R6, A3-R1 to A3-R6, and A4-R1 to A4-R11. The disposition is in §R4.

**Basis.** Plan facts come from FROZEN ARCH Rev 9.2 (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md`, sha256 `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`, re-hashed 10-03) and from errata E-1 to E-13 (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`). E-14 is requested in §ERRATA-REQUEST.

Code facts were checked on the tree at `d231497d` (HEAD; `src/`, `tests/` and `pyproject.toml` are clean) using codegraph, `sed`, `grep` and read-only probes. The probes ran under `/home/jon/breezy/.venv/bin/python`, with scratch under `/tmp/claude-1000/a0r3/` and `/tmp/claude-1000/a0r4/`. No repo file was written and no state was changed.

## Verified facts

V1 to V21 come from r3. They were re-checked where they are used. V22 to V31 are new in r4.

**r3 facts, condensed:**
- **V1.** `import breezy.domain.instrument_leg` loads 120 `nautilus_trader*` modules (`src/breezy/domain/__init__.py:16-53`).
- **V2.** With an import-free `persistence/__init__.py`, `breezy.persistence.live_orders_gate` loads 0 Nautilus modules and 15 `pyarrow*` modules. The chain is `family_manifest.py:88` → `mechanism_test_guard.py:14` (`import pyarrow.parquet as pq`).
- **V3.** The facade at `src/breezy/persistence/__init__.py:9-53` re-exports 20 `catalog` names and has zero consumers.
- **V4.** On SQLite 3.50.4, REPLACE bypasses `BEFORE DELETE` while `recursive_triggers=0`, and `ON CONFLICT DO UPDATE` fires the UPDATE trigger.
- **V5.** The data root is 0700. Repo files are 0664 under umask 0002.
- **V6.** In `src/breezy/runtime/trade_supervisor_core.py:37-44`: STOP_PRIOR 16:40, LAUNCH 16:50, SELF_CHECK 17:05, window end 17:00.
- **V7.** `src/breezy/adapters/polymarket_us/exec/client.py` has sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4` (re-hashed in r4). It is pinned at `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:36`.
- **V8.** `live_orders_authorized` is at `src/breezy/persistence/live_orders_gate.py:130-189`. The ruling checks are at `:163-182`, and the permit check comes last (`:184-189`).
- **V9.** `load_family_manifest` is at `family_manifest.py:285`, with the guard at `:293-294` and `read_bytes` at `:295`. The containment helper is at `:262-282`.
- **V10.** The exec client never deletes `fill_index/` keys.
- **V11.** The COALESCE genesis trigger refuses a first row whose `venue_seq` is not 1 (probe `/tmp/claude-1000/a0r3/trig.py`).
- **V12.** A `mode=ro` reader distinguishes `SQLITE_BUSY` from `SQLITE_READONLY_ROLLBACK` (probe `hj2.py`).
- **V13, corrected in r4.** In `exec/client.py`:
  - `STATE_KEY_NAMESPACE = "exec/polymarket_us/"` is at `:399`, and `FILL_INDEX_KEY_PREFIX = f"{STATE_KEY_NAMESPACE}fill_index/"` is at `:412`.
  - Every key site is `f"{FILL_INDEX_KEY_PREFIX}{instrument_id}"`. The write site is `:4645`. The reads are at `:2198`, `:2302`, `:3457`, `:4693` and `:4827`, plus `trial_day_latch.py:1385`.
  - `_read_fill_index` (`:4712-4729`) returns `[]` for an absent key and `None` for an unreadable one.
- **V14.** In `tests/unit/test_runtime_import_isolation.py`, the entry-module helpers are at `:158`, `:165` and `:192`, and the constants at `:55-60`.
- **V15.** The Nautilus arrow registry is `serializer.py:75-78`.
- **V16.** A single "core list ↛ pyarrow" contract is unsatisfiable. That is the reason for the (b)/(c) split.
- **V17.** `tests/unit/test_mypy_ratchet.py:352-364` sets per-package mypy ceilings and fails when the code falls below a ceiling.
- **V18.** `assert_prereg_directory_eligible` (`mechanism_test_guard.py:27-45`) returns silently when the directory is absent (`:35-36`).
- **V19.** The family patterns are `settings.py:114` (`^[a-z0-9_:]+$`) and `trial_day_latch.py:301`. Their intersection is `[a-z0-9_]{1,64}`.
- **V20.** `pm_us_crh_v4` and `pm_us_crh_cont` share density sha `247f6363…a65`. This is the E-14 collision.
- **V21.** ARCH C5 places the `ResolvedFamily` fields at `:557-558`, Y6 at `:560-563`, the shadow HWM at `:576-579`, the root exemption at `:605-608`, the HWM mid-chain check at `:618-624`, and the reset CLI at `:626-634`.

**New in r4:**
- **V22 (architect F1, security F2a; probe `/tmp/claude-1000/a0r4/gen.py`).** The probe copied `src/` to scratch, generated the autonomy modules with exactly the import edges of the File-by-File Plan, and ran `lint-imports` with contracts (b) and (c) under `include_external_packages = true`:
  - **r4 layout** (resolver types in `resolver.py`, `FamilyBytes` in `family_bytes.py`, `schemas` importing only `wire`, `canonical` and `rollback_journal`): "Contracts: 2 kept, 0 broken".
  - **r3 layout** (`schemas` importing `live_orders_gate` and `family_manifest`): (c) BROKEN for `chain`, `fold`, `hwm`, `schemas`, `stage_policy` and `transitions`.
  - **Planted control** (`if TYPE_CHECKING: import breezy.persistence.live_orders_gate` in `schemas`): (c) BROKEN. `pyproject.toml` has no `exclude_type_checking_imports` (grep rc=1), so `TYPE_CHECKING` imports count.
- **V23 (new; neither review caught it).** Import-linter treats a **package** named in `source_modules` as including all of its descendants. With `breezy.persistence.autonomy` in (c)'s source list, (c) broke on `label_schema` and `family_bytes`, which are pyarrow-reaching by design. The same rule would break (b) when AUT-1a adds a `NAUTILUS_PERMITTED` `capture_*` module. Contracts (b) and (c) therefore name **modules only**. The package `__init__` is covered by an AST test (AC 1).
- **V24 (architect F4).** The ARCH counters:
  - ARCH `:431-434` lists `lineage_counters` as `holdout_opens`, `nominations`, `infeasible_nominations`, `alpha_spent`, `mints`, `promotions` (both timestamped), `rollbacks`, `terminal_frozen`, `drill_admits`, `drill_promotes`, `drill_demotes`, `drill_resumes`, `drill_halts`, `drill_rollbacks`, and the venue-level `infra_resumes`.
  - AUT-5 r7 `:139` adds the venue-level `drill_close_restores` (E-5).
  - No `transitions` column or kind records a holdout open: ARCH `:306-307` and the AUT-5 r7 `:138` column list.
- **V25 (architect F12; corrects the review's citation).** `_RECORD_SIGNS` is defined at `exec/client.py:668-671` as `{LONG_ONLY_SIDE: Decimal(1), "SELL": Decimal(-1)}`, with `LONG_ONLY_SIDE: Final[str] = "BUY"` at `:663`. `:3442-3455` is the `_durable_net_qty` docstring, and the uses are at `:3470-3472`, `:4090-4093` and `:4517-4528`. `DurableFillRecord` is at `:923` and `record_fill` at `:4593`.
- **V26.** `LiveOrdersReason` is a `typing.Literal` with 7 members (`live_orders_gate.py:62-70`): `no_ruling`, `not_allowlisted`, `ruling_missing`, `ruling_outside_evidence`, `ruling_sha_mismatch`, `permit_absent` and `ok`. The module imports `FamilyManifest` at `:53`.
- **V27 (architect F10).** The exec intent flock is `<exec store>.intent.lock` (`trade_supervisor.py:306-307`, `submit_intent.py:558`). Timing:
  - E-8 step 6 releases it by 16:48:00 (`test_exec_snapshot_releases_by_164800`).
  - AUT-5 r7 `:937` step 3 ends by 16:44:50, and its reload gap rule is "≤ 16:44:55".
  - The bootstrap ends by 16:41:15.
- **V28 (architect F6).** ARCH `:263-264` says a ROLLBACK to `fq_v1` restores the BOOTSTRAP sha "even if the repo file changes". `terminal_climate_day` is an optional manifest key (`family_manifest.py:43`, `:152`, `:252`). There are 7 committed `deploy/families/*.json`.
- **V29 (security F8).** `REPO_ROOT = Path(__file__).resolve().parents[2]` (`test_runtime_import_isolation.py:55`) gives the same repo root from `tests/support/entry_points.py`. The four constants can therefore move byte-identical.
- **V30 (security F9; not probed).** `unshare -r` is refused in this sandbox (`write failed /proc/self/uid_map`), so it is unverified whether uid 0 in the gate's user namespace gets a DAC override on a 0500 directory. As a normal uid, `O_CREAT` in a 0500 directory gives errno 13. AC 7 therefore refuses by **mode bit**, which does not depend on uid.
- **V31 (architect F4).** `nominations`, `infeasible_nominations` and `alpha_spent` can be derived from the C5 nomination columns on SHADOW→CHALLENGER PROMOTE rows (`k_life`, `alpha_k`, `nomination_feasible`; AUT-5 r7 `:138`). AUT-4 r11 `:1458` asserts `alpha_spent == 0.025·(1 − 2^−nominations)`, which equals Σ`alpha_k`.

**Residual risk, stated once.** Pins, chain, HWM, exports and the DB are all one same-uid trust domain (ARCH C5 residual; R14). There are only four external anchors:
1. the committed allowlists;
2. the committed `deploy/families/<id>.json` bytes, frozen after bootstrap (A3-R1; E-14 rule 7);
3. `live_orders_gate`;
4. the reviewed code in `pins.py` and `transitions._ADMISSION_IMPLEMENTED`.

Every control below exists so that a row, a rebinding or a missing verifier cannot bypass one of these anchors.

## Acceptance Criteria (numbered, testable)

1. **Package and contracts (V16, V22, V23).** `/home/jon/breezy/src/breezy/persistence/autonomy/` holds exactly the modules in the File-by-File Plan. `cd /home/jon/breezy && .venv/bin/lint-imports` prints "N kept, 0 broken". N includes three new contracts, all with `allow_indirect_imports = false`:
   - (a) `breezy.persistence.autonomy ↛ breezy.adapters` (ARCH §4.7). The package as source is intended here.
   - (b) **The 27 core modules, named one by one and never the package (V23), ↛ `nautilus_trader`, `breezy.domain`.** The modules are `canonical, wire, single_read, paths, pins, veto, plugin, closure_manifest, closure, schemas, stage_policy, verdict, lineage, label_schema, demand, drill_marker, rollback_journal, fold, transitions, chain, family_bytes, registry_store, hwm, replay, net_position, entry_guard, resolver`.
   - (c) **(b) minus `PYARROW_REACHING = {label_schema, family_bytes, registry_store, replay, resolver}` ↛ `pyarrow`.**

   Lists grow as modules land, because import-linter refuses an absent source module. `include_external_packages = true` is already set (`pyproject.toml:72`). `test_autonomy_init_has_no_import_nodes` asserts that `persistence/autonomy/__init__.py` has no import nodes, since the package is in neither list.
2. **Module classification.**
   - `test_every_autonomy_module_is_classified` places every module in exactly one set: (b)'s `source_modules`, parsed from `pyproject.toml`, or `NAUTILUS_PERMITTED` (AUT-1 `capture_*`, E-12; empty at ARCH-0). It also asserts (b) − (c) == `PYARROW_REACHING` ∩ existing modules. A planted unclassified module turns it red.
   - **New (A4-R1):** `test_contract_c_refuses_planted_pyarrow_reach[canonical|schemas]` (`heavy`) copies `src/` to `tmp_path` and writes a temporary `pyproject.toml` holding contract (c). The unplanted copy must print "1 kept". It then plants `if TYPE_CHECKING: from breezy.persistence.live_orders_gate import LiveOrdersReason` into the target module, and the planted copy must print "BROKEN". This mirrors V22.
3. **Runtime import weight.** `test_autonomy_core_modules_nautilus_free_at_runtime` imports each core module in a fresh subprocess. It asserts 0 `nautilus_trader*` and 0 `breezy.domain*` modules, and allows `pyarrow*` only for `PYARROW_REACHING`.
4. **Import-free `persistence/__init__.py`.** The 20-name facade is deleted (precedent: NOTIFIER-IMPORT-ISOLATION, `src/breezy/runtime/__init__.py:15-25`).
   - Permanent tests:
     - `test_persistence_init_has_no_import_nodes`;
     - `test_persistence_has_no_facade_consumers` (AST over `src/`, `tests/` and `scripts/`, including `mock.patch("breezy.persistence.<name>")`);
     - `test_persistence_entry_module_imports_cleanly[<entry>]`: one fresh process per pyproject script, systemd `ExecStart` and `scripts/**` importing `breezy.persistence`; total ≤ 60 s, measured in WP-1a.
   - One-time WP-1a evidence, kept in the merge evidence log:
     - (i) the per-entry grimp `register_arrow` reachability is identical with and without a simulated `persistence → catalog` edge;
     - (ii) the per-entry sorted `serializer._SCHEMAS` keys are equal on the old tree and on the scratch tree (V15).

     Any entry that differs is listed with a reviewed reason, or WP-1a stops.
5. **Explicit serialisation.** Every wire record has `to_wire() -> dict` and `from_wire(payload) -> Self`. The records are: C2 schema, `lineage/v1`, `root/v1`, `refit_run/v1`, `verdict/v1`, the C5 row, the export trailer, `demand/v1`, `drill_marker/v1`, `journal/v1` and `Hwm`.
   - `wire.parse_json_exact` refuses duplicate keys, NaN and Infinity, any float token, missing or unknown keys, wrong types, bool-as-int, and a `schema` value outside `ACCEPTED_SCHEMAS`.
   - Every refusal raises `WireRefused(reason: WireRefusalReason)`, a closed StrEnum.
   - An AST test bans `dataclasses.asdict` and `astuple` in the package.
6. **Canonical bytes.** `canonical_json(x)` is `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False)` encoded as UTF-8.
   - `CanonicalTypeError` is raised on a non-`str` key, a `float`, a lone surrogate, or any type outside `None|bool|int|str|list|tuple|dict|Decimal`.
   - `decimal_str` refuses NaN, Inf, more than 38 digits, and `|adjusted()| > 18`. Every zero is written `"0"`; any other value is `format(d.normalize(), "f")`.
   - Goldens: `-0`→`"0"`, `0E-10`→`"0"`, `1E+2`→`"100"`, `1.50`→`"1.5"`, plus three record goldens.
7. **Single read and write, TOCTOU-free.**
   - `open_root(root)` opens an absolute path `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`.
   - `walk_dirs(rootfd, rel, *, create, mode=0o700)` runs one `openat` per component with `O_DIRECTORY|O_NOFOLLOW`. It refuses `""`, `.`, `..`, NUL and `/`. Each component must pass an `fstat` S_ISDIR check with `st_uid == geteuid()`.
   - `read_once_at(dirfd, name, *, max_bytes, policy)` opens `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC` and requires S_ISREG and the owner uid. `STRICT` refuses group-write and other-write bits; `REPO` drops the mode check (V5). It reads `max_bytes+1` to detect oversize.
   - `write_once(path, data, *, root, mode)`:
     - (1) pre-reads the destination: equal bytes → `EXISTS_EQUAL` with no temp file; different bytes or a symlink → `EXISTS_DIFFERENT`; ENOENT → step 2;
     - (2) **new (security F9, V30):** `fstat(parent dirfd)`, and `st_mode & S_IWUSR == 0` → `SingleReadRefused(DIR_NOT_WRITABLE)` before any temp file. This is a mode-bit check, so it does not depend on uid;
     - (3) `.tmp.<token_hex(8)>` with `O_CREAT|O_EXCL|O_NOFOLLOW`, `fchmod`, write, `fsync`, then `os.link(src_dir_fd=, dst_dir_fd=, follow_symlinks=False)`;
     - EEXIST re-compares; EPERM, EXDEV, EOPNOTSUPP and EMLINK give `LINK_UNSUPPORTED`; there is never a rename fallback;
     - the temp file is always unlinked and the directory fd `fsync`ed.
   - `replace_atomic` follows the same pattern with `os.replace`.
   - AST: these are the only `os.link`, `os.replace` and write-mode `open` sites. The one named, reviewed exemption is `live_orders_gate._verify_ruling_file`, a move-only extraction that keeps `resolve()` + `read_bytes()`.
8. **Store DDL.** `transitions` has exactly the AUT-5 r7 §3.2 columns (`:138`).
   - `venue` and `venue_seq` are `NOT NULL`, with `UNIQUE(venue, venue_seq)` and `UNIQUE(transition_id)`.
   - `BEFORE UPDATE` and `BEFORE DELETE` triggers raise `RAISE(ABORT,'append-only')`.
   - `BEFORE INSERT` refuses an existing `NEW.seq`, a duplicate `(venue, venue_seq)`, and `NEW.venue_seq IS NOT COALESCE((SELECT max(venue_seq) FROM transitions WHERE venue=NEW.venue),0)+1` (V11).
   - `meta(schema='registry/v1')`, `user_version=1`, `application_id=0x42524759`. The directory is 0700 and the file 0600.
   - No derived caches are created (AUT-5 WP4).
9. **Writer connection.** `isolation_level=None` and `BEGIN IMMEDIATE`. Pragmas: `journal_mode=DELETE`, `synchronous=FULL`, `recursive_triggers=ON`, `trusted_schema=OFF`, each read back by a test. AST bans `OR REPLACE`, `OR IGNORE`, `REPLACE INTO` and `executescript` in `registry_store.py`.
10. **Append path.** `RegistryStore.append(rows, *, expected_prior_seq, mode: WriterMode, now_ns: int)` delegates to `_append(..., stage=stage_policy.STAGE, _fixture_stage=False)`. Inside one `BEGIN IMMEDIATE`, in order:
    1. **(A4-R5)** `stage is stage_policy.STAGE` unless `_fixture_stage=True`; otherwise it raises `StageNotCanonical`. Only tests can pass `_fixture_stage`, because AC 15 bans `_append` references outside the module.
    2. If every id is already present, it is a logged no-op. If only some are present, `PartialReplay`.
    3. `mode` must be a concrete `WriterMode`.
    4. `KIND_MASK[mode]`.
    5. **(A4-R2)** `adm = transitions.rows_admissible(rows, stage=stage)`. If `adm.reason == widening_kind_not_enabled`, raise `WideningNotEnabled(reason=adm.reason)`. If `adm.reason == admission_pending`, raise `AdmissionPending(reason=adm.reason)`. The whole batch is refused, because append is atomic, so the engine appends restrictive rows in their own batch. The store keeps no second copy of the predicate.
    6. SHADOW→CHALLENGER PROMOTE → `NominationRequiresPolicy`. HWM_RESET → `RuleSetPending`.
    7. `|row.ts_ns − now_ns| ≤ ROW_TS_MAX_SKEW_S` (300), and `ts_ns` is monotone over the head.
    8. CAS: `max(venue_seq) == expected_prior_seq`.
    9. `transitions.validate(fold(prior), rows, mode=mode, now_ns=now_ns, stage=stage, manifests=family_bytes.read_manifest_facts)`.
    10. Insert, then COMMIT.

    Any failure rolls back completely. Every append exception carries `.reason: RefusalReason`.
11. **Chain.**
    - The genesis is `sha256(b"registry/v1|"+venue)`.
    - `canonical_row` hashes every column except `seq`, `prev_transition_hash` and `transition_hash`.
    - `transition_id` hashes the C5 Y9 tuple without `expected_prior_seq`.
    - `verify_venue_chain(rows, venue) -> VerifiedVenueChain` requires contiguous `venue_seq` from 1 to n, a single venue, monotone `ts_ns`, and unbroken hashes.
12. **Reader (V12).** `RegistryReader(paths, *, busy_timeout_ms).read_venue_rows(venue, after_seq=0)`:
    - opens `file:<percent-quoted>?mode=ro` with `query_only=ON` and `trusted_schema=OFF`, one connection per call;
    - inside one `BEGIN`, checks `meta.schema`, `user_version` and `application_id`, and that `sqlite_master` equals the DDL constants, then selects an explicit column list ordered by `venue_seq`;
    - raises `RegistryUnreadable(reason: UnreadableReason)` with these reasons:

      | Reason | Cause |
      |---|---|
      | `busy` | `SQLITE_BUSY` or `SQLITE_LOCKED`, including extended codes |
      | `hot_journal` | `SQLITE_READONLY_ROLLBACK` |
      | `schema_mismatch` | meta, `user_version`, `application_id` or `sqlite_master` differs |
      | `io` | `OSError`, `SQLITE_IOERR*` or `SQLITE_CANTOPEN*` |
      | `sqlite_error` | any other `sqlite3.Error` |

    A hot journal is rolled back by the engine's next read-write open under `engine.lock`.
13. **Validated kinds and the shared admissibility predicate.**
    - `transitions.validate` is pure and implements every fold-decidable C5 rule for every kind:
      - V12 DRILL-row refusal while a non-DRILL cause stands;
      - DRILL_PROMOTE requires the champion sha; no drill over a HALTED incumbent; drill counters ≤ 1 per `DRILL_BUDGET_PER_VENUE_30D`;
      - Z3 and `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY`;
      - RESUME (every cause cleared, cooldown, RECOVERABLE_MODEL and RECOVERABLE_INFRA ceilings; ROLLBACK_FAILED only under `trigger_cause_class`);
      - the five E-5 `drill_close_restore` conditions, at most 1 per venue per day;
      - d0 and `trial_id_prefix` at the first →CHAMPION row (ROLLBACK, RESUME and ROOT_ADMIT are exempt);
      - ROOT_ADMIT and BOOTSTRAP only when the venue has no sender, with `lineage_root_family_id == family_id`;
      - the mint rate; BOOTSTRAP genesis and seed (E-6); ATTEST cadence; SWAP_CANCEL voids ⊆ pending;
      - single sender at `now` and at the next LAUNCH;
      - HWM_RESET `carried_counters` ≥ export counters (B9).
    - **New (A4-R6):** a row whose `family_id` is unknown to the prior fold must have `from_state = ∅` and kind ∈ {BOOTSTRAP, ROOT_ADMIT, MINT}. Otherwise `validate` returns `family_not_introduced`. A BOOTSTRAP or ROOT_ADMIT row with `lineage_root_family_id != family_id` returns `root_lineage_mismatch`.
    - `_ADMISSION_IMPLEMENTED: Final[frozenset[Kind]] = frozenset()` lives in `transitions.py`.
    - **`rows_admissible(rows, *, stage: StageView) -> AdmissibilityResult(admitted: int, reason: RefusalReason | None)`** (A4-R2, architect F11) walks the rows **in chain order** and stops at the first widening row whose kind is outside `stage.enabled_widening_kinds` (→ `widening_kind_not_enabled`) or outside `stage.admission_implemented` (→ `admission_pending`). `admitted` is the index of that row, so `rows[:admitted]`, which includes every restrictive row before it, is admissible. `reason is None` means `admitted == len(rows)`.
    - `rows_admissible` is the **only** place either set is compared against rows. `test_admissibility_predicate_has_one_home` is an AST test: outside `transitions.py`, `schemas.py` and `stage_policy.py`, no `src/` module reads `.enabled_widening_kinds` or `.admission_implemented`.
    - Consumers: the store (AC 10.5), the resolver (AC 17.5, where any reason refuses), and the watch actor (binding note 5). `test_admissibility_predicate_shared[store|resolver]` is real; `[watch_actor]` is carried to AUT-5a.
14. **Fold.** `fold(rows, venue, now_ns) -> FoldResult | FoldInvalid` is pure.
    - It computes:
      - states, pending pairs, ACTIVATE in [16:40Z, LAUNCH), lapse at LAUNCH;
      - SWAP_CANCEL voiding, including the [LAUNCH, 17:00Z) post-launch void;
      - `demoted_for_cause`, `rollback_eligible`, `target_ineligible` and `terminal_frozen`; the venue INTEGRITY freeze; `drill_episode` intervals;
      - tallies charged on effect, with HWM_RESET `carried_counters` applied as floors;
      - at most one {CHAMPION, HALTED} family per venue.
    - `FamilyView` carries `origin: Literal["root","child"]` and `lineage_root_family_id`, both from the family's **introducing row**. BOOTSTRAP or ROOT_ADMIT with `lineage_root_family_id == family_id` gives `root`; MINT gives `child`.
    - **(A4-R6, security F4)** `FoldInvalid(reason: FoldInvalidReason)` is returned when a family's introducing row is any other kind (`family_introduced_by_other_kind`) or when a BOOTSTRAP/ROOT_ADMIT row has `lineage_root_family_id != family_id` (`root_lineage_mismatch`). It is never classified as "child". The resolver maps it to `replay_invalid`; the watch actor maps it to `registry_unreadable`.
    - **`LineageTallies` is frozen (A4-R7; V24, V31).** These fields are fold-derived, with HWM_RESET `carried_counters` applied as floors:
      - `nominations` = max `k_life` over feasible SHADOW→CHALLENGER PROMOTE rows;
      - `infeasible_nominations` = count where `nomination_feasible = false`;
      - `alpha_spent: Decimal` = Σ `alpha_k`;
      - `mints: tuple[int, ...]` and `promotions: tuple[int, ...]` (`ts_ns`);
      - `rollbacks`, `terminal_frozen: bool`;
      - `drill_admits`, `drill_promotes`, `drill_demotes`, `drill_resumes`, `drill_halts`, `drill_rollbacks` (`drill = true` rows, by kind).

      `VenueTallies` holds `infra_resumes` and `drill_close_restores` (E-5). **`holdout_opens` cannot be derived** (no column or kind records it) and is excluded. AUT-4 reads it from the AUT-5 WP4 cache (Stub table, owner row).
    - `test_lineage_tallies_fields_equal_arch_counters_minus_non_derivable` asserts `fields(LineageTallies) ∪ fields(VenueTallies) == ARCH_C5_COUNTERS − {"holdout_opens"}`. `ARCH_C5_COUNTERS` is a literal in the test, copied from ARCH `:431-434` plus AUT-5 r7 `:139`.
    - AST bans `time.time`, `time.time_ns`, `datetime.now`, `datetime.utcnow` and `time.monotonic` in the core list.
15. **Stage policy: frozen, not constructible in `src/` (A4-R5, security F3).**
    - The `StagePolicy` frozen slotted dataclass and the `StageView` Protocol live in `schemas.py`. `stage_policy.py` builds `STAGE: Final[StagePolicy]` once through a private `_build()` from `pins` and `transitions._ADMISSION_IMPLEMENTED`. The import order is `schemas ← transitions ← stage_policy` (`test_autonomy_package_import_graph_is_acyclic`).
    - `test_autonomy_policy_not_mutable_from_src`, with a planted positive control per form, refuses:
      - (i) over all of `src/`: assignment, `setattr`, `delattr`, `__dict__`, `object.__setattr__`, `importlib.reload`, `mock.patch`, `monkeypatch`, and `globals()`/`vars()` writes targeting `pins`, `stage_policy`, `transitions`, `live_orders_gate` or `family_manifest`; rebinding an imported name; and references to `_append`, `_resolve`, `_replay_full`, `_lineage_policy_authorized`, `_verify_ruling_file` or `stage_policy._build` outside their defining module;
      - (ii) **(new)** in `src/breezy/persistence/autonomy/`, `src/breezy/strategy/autonomy/` and `src/breezy/analysis/autonomy/`, outside `stage_policy.py`: **any** call to `dataclasses.replace`, `copy.copy` or `copy.deepcopy` (AST cannot see argument types, so every call is banned); `<expr>.__class__(...)`; `type(<expr>)(...)`; `object.__new__(...)`; and `StagePolicy(...)` reached through any import alias (`from …schemas import StagePolicy as SP`, `schemas.StagePolicy`, or `import …schemas as s; s.StagePolicy`), resolved per module. Exemptions are a literal set in the test, empty at ARCH-0.
    - Defence in depth against a duck-typed `StageView`: `_append` (AC 10.1) and `_resolve` (AC 17.0) require `stage is stage_policy.STAGE` unless `_fixture_stage=True`. Tests: `test_append_refuses_non_canonical_stage` and `test_resolve_refuses_non_canonical_stage`. Tests may construct fixture stages.
16. **HWM is tri-state, mid-chain checked, absence-refusing, and strictly indexed (A3-R2, A4-R3, security F1).**
    - `hwm.py` provides `Hwm(venue, venue_seq, chain_head, export_seq)`, `HwmReading = HwmAbsent | HwmPresent | HwmUnreadable`, `REGISTRY_HWM_KEY_PREFIX = "autonomy/registry_hwm/"` and `hwm_key(venue)`.
    - **Domain.** `Hwm.__post_init__` and `Hwm.from_wire` require:
      - `venue` matching the venue pattern;
      - `venue_seq: int ≥ 1`;
      - `export_seq: int ≥ 0`;
      - `chain_head` matching `\A[0-9a-f]{64}\Z`;
      - bool is refused as int.
    - **`hwm_reading_from_bytes(raw: bytes | None) -> HwmReading` is the only decoder.** `None` gives `HwmAbsent`, and any error gives `HwmUnreadable`. AST bans `HwmAbsent(` construction outside `hwm.py`.
    - `hwm_check(chain: VerifiedVenueChain, reading, *, newest_export_seq: int) -> RefusalReason | None` checks, in order:
      1. a `reading` that is none of `HwmAbsent`, `HwmPresent` or `HwmUnreadable`, or an `HwmUnreadable` → `hwm_unreadable`;
      2. `HwmAbsent` on any non-empty chain → `hwm_absent`. There is no genesis exception;
      3. a foreign venue, or `venue_seq < 1` (defence in depth) → `hwm_unreadable`;
      4. `venue_seq > head` → `hwm_regressed`;
      5. **`chain.rows[venue_seq − 1].transition_hash != chain_head` → `hwm_regressed`**. `venue_seq` is 1-based and `rows` is 0-based, so `venue_seq == head` compares the last row;
      6. `export_seq > newest_export_seq` → `hwm_regressed`.
    - `newest_export_seq` is **0 when there is no export file**.
    - `next_hwm(chain, *, export_seq: int) -> Hwm` is pure. It requires a non-empty chain and `export_seq ≥ 0`, and returns `Hwm(venue, head, rows[-1].transition_hash, export_seq)`.
    - Tests: `test_hwm_seq_zero_and_negative_refused`, `test_hwm_at_head_compares_last_row`, `test_hwm_check_unknown_reading_type_is_unreadable`.
17. **Sending resolver.** `resolve_sending_family(*, venue, paths, repo_root, now_ns, hwm: HwmReading) -> ResolvedFamily | ResolverRefusal` delegates to `_resolve(..., stage=STAGE, lineage_gate, hwm_mode=ENFORCE)`. Steps, in order:
    0. **(A4-R5)** `stage is STAGE` unless a fixture, else `stage_not_canonical`. **(security F7)** `(hwm_mode is HwmMode.SKIP_SHADOW) == paths.is_shadow`, else `paths_role_mismatch`.
    1. `paths.is_shadow` is True → `paths_role_mismatch`. This reads the attribute and never uses `isinstance`.
    2. Verify the chain from genesis; `now_ns` is an int > 0 and ≥ head `ts_ns` − skew.
    3. **Exports, before the HWM (A4-R4):**
       - open and list `evidence/registry/`; any open or listing error, including a missing directory, gives `export_unreadable`;
       - no export file: `newest_export_seq = 0`, with `export_check = not_yet_due` only if `now_ns − genesis_ts_ns < EXPORT_FIRST_DUE_H`, else `export_unreadable`;
       - otherwise verify the export prefix and set `newest_export_seq` to the newest export's `export_seq`, with `export_check = verified`.
    4. `hwm_check(chain, hwm, newest_export_seq=newest_export_seq)`. An HWM that saw an export which is now absent gives `hwm_regressed`.
    5. `transitions.rows_admissible(chain.rows, stage=stage)`; any reason refuses.
    6. `replay_full`. Its fold, including `FoldInvalid`, maps to `replay_invalid`.
    7. More than one CHAMPION/HALTED family → `engine_inconsistency`.
    8. Root or child is decided from `FamilyView.origin`, never from the name.
    9. **Root (A3-R1):**
       - read `deploy/families/<family_id>.json` under `ReadPolicy.REPO` only; its sha must equal `row.manifest_sha256`, else `manifest_sha_mismatch`;
       - check the E-14 root record;
       - call `live_orders_authorized(..., permit_present=False)` and accept only `reason == "permit_absent"`. `no_ruling` gives `no_live_orders_ruling`. A raised `LiveOrdersGateRefusedError` gives `ruling_refused` with `detail = LiveOrdersRefusal(<reason>)`, and `ok` gives `ruling_refused` with `detail = LiveOrdersRefusal.ok`.
    10. **Child:**
        - read `registry/families/<id>.json` (STRICT) with a sha check;
        - `CHILD_FAMILY_ID_RE.fullmatch(id).group("root") == view.lineage_root_family_id`, else `child_root_mismatch`;
        - §4.2 equality with the committed root (REPO) over `fields(FamilyManifest) − ALLOWLIST − {"manifest_sha256"}`;
        - `lineage_policy_authorized(...)`;
        - d0 and the prefix at the first →CHAMPION row.
    11. **Common to both:**
        - the manifest's `venue`, `composition_kind` and `family_id` equal the row's;
        - `LIVE_GATE_ROUTED_KINDS` is checked on the manifest's kind;
        - the engine pins are checked;
        - the artefact `derived/artefacts/<model_class>/<sha>/artefact.json` (STRICT) has sha == `row.artefact_sha256`.
    12. Return `ResolvedFamily` with `verified_export_seq = newest_export_seq` and `hwm = next_hwm(chain, export_seq=newest_export_seq)`.
18. **Shadow resolver.** `resolve_shadow_family(*, venue, paths, repo_root, now_ns) -> ShadowResolution | ResolverRefusal` runs `_resolve(..., hwm_mode=SKIP_SHADOW)`.
    - It refuses `paths_role_mismatch` unless `paths.is_shadow`. `ShadowPaths` is **not** a subclass of `AutonomyPaths` (security F7).
    - Step 4 is skipped. **Step 3 applies unchanged (architect F9):** with no export, `newest_export_seq = 0`, and `not_yet_due` holds only within 26 h of shadow genesis (`test_shadow_day2_without_export_refuses`).
    - `ShadowResolution(family_id, state, registry_seq, chain_head)` is a separate frozen dataclass in `resolver.py`. It shares no base with `ResolvedFamily` and has none of the `family_bytes`, `entries_allowed`, `manifest`, artefact or `hwm` fields.
    - `test_shadow_resolution_ignores_hwm_and_cannot_send` checks four things: it resolves an ATTEST-bearing chain with no HWM; the sending resolver on the same chain gives `hwm_absent`; `ShadowResolution` has none of the `ResolvedFamily`-only fields; and AST finds no `resolve_shadow_family` call outside `SHADOW_CALL_SITES` (empty).
    - `test_resolve_private_rejects_skip_hwm_on_production_paths` exercises the AC 17.0 assertion.
19. **`ResolvedFamily` carries the ARCH C5 pickup fields (A3-R3, A4-R4).** It is defined in `resolver.py` and has these fields:
    - `family_id`, `state: Literal[CHAMPION, HALTED]`, `entries_allowed: bool`, `origin`;
    - `registry_seq: int` (the verified head) and `chain_head: str`;
    - `authorising_seq: int`;
    - `family_bytes: FamilyBytes` (from `family_bytes.py`: `manifest`, `manifest_raw`, `manifest_sha256`, `manifest_source: Literal["deploy","registry"]`, `artefact_raw`, `artefact_sha256`, `artefact_store_relpath`);
    - `export_check: Literal["verified","not_yet_due"]`;
    - **`verified_export_seq: int`** (0 when `not_yet_due`);
    - **`hwm: Hwm`**.

    It has no `enabled` field and no permit field.
    - `test_resolved_family_carries_arch_c5_pickup_fields` pins the field set (ARCH `:558`; AUT-5 r7 `:410`, `:441`, `:971`; AUT-1 r12 `:329`).
    - `test_resolved_family_hwm_equals_next_hwm` asserts `rf.hwm == next_hwm(verify_venue_chain(rows, venue), export_seq=rf.verified_export_seq)` and `rf.hwm.venue_seq == rf.registry_seq`.
    - `ResolverRefusal(reason: RefusalReason, detail: UnreadableReason | LiveOrdersRefusal | None)` lives in `resolver.py`.
20. **Lineage-policy gate (WP-8a).** `live_orders_gate.py` gains:
    - `_LINEAGE_POLICY_ALLOWLIST: Final[frozenset[tuple[str,str,str]]] = frozenset()`;
    - `CHILD_FAMILY_ID_RE = re.compile(r"\A(?P<root>[a-z0-9_]{1,58})_r[0-9]{4}\Z", re.ASCII)`;
    - `_verify_ruling_file(repo_root, ruling_id, expected_sha256)`, a move-only extraction of `:163-182` with identical reasons and messages;
    - `lineage_policy_authorized(child, root_family_id, repo_root) -> LineagePolicyDecision(ruling_id, ruling_sha256)`, which delegates to `_lineage_policy_authorized(..., allowlist)`, raises `LiveOrdersGateRefusedError`, and uses existing `LiveOrdersReason` members only.

    `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py` and `test_live_orders_ruling_deploy_copy_matches_evidence.py` pass **unmodified**. The three ruling refusal sites reach 100% branch coverage before and after the extraction.
21. **`parse_family_manifest` split, proven byte-equivalent.** `parse_family_manifest(raw: bytes, *, path: Path, allow_draft: bool = False)` is `family_manifest.py:296-460` moved verbatim. `load_family_manifest` keeps `:293-295` verbatim and then calls it.
    - **WP-1b** runs on unsplit code:
      - `/home/jon/breezy/tests/fixtures/family_manifest_golden/` holds the 7 committed manifests, their artefacts and mutated invalid manifests;
      - the corpus is sized by coverage, not by count;
      - `expected.json` records, per input, either `(exception type, message with <PATH>)` or `(dump, sha)`;
      - `symlink_escape` is built inside `tmp_path`;
      - **gate:** `coverage run --branch` gives 100% of the lines and branches in `:262-282` and `:285-460`.
    - **WP-1c** splits the code, and the same test passes unmodified.
    - **Callers:** `family_bytes` opens the source directory with `walk_dirs`, where a missing directory gives `manifest_unreadable`. It always calls `assert_prereg_directory_eligible(dir)` before parsing. `test_autonomy_never_passes_allow_draft_true` enforces the draft ban.
22. **Entry guard.**
    - **`net_position.LegFill(leg: Literal["yes","no"], side: Literal["BUY","SELL"], qty: Decimal, ts_event_ns: int)` is frozen and netting-only (A4-R8).** Its docstring says so. AUT-2's `average_cost_basis` takes an AUT-2-owned `CostedFill` added to the same module. `test_leg_fill_fields_frozen` pins the names and types.
    - `net_signed_qty(fills) -> Decimal`: YES BUY +q, YES SELL −q, NO BUY −q, NO SELL +q; anything else gives `UnknownSide`.
    - `entry_guard.leg_instrument_ids(base_slug, *, venue_suffix)` returns `<base><venue_suffix>` and `<base>^no<venue_suffix>`.
    - `FillReader`:
      - `open_intent_blocks() -> bool`;
      - `fill_index(instrument_id) -> tuple[str, ...] | FillIndexAbsent`;
      - `fill_record(venue_order_id) -> FillRow(order_side: Literal["BUY","SELL"], cumulative_qty, ts_event_ns)`.
    - `rung_has_net_position(base_slug, *, reader, venue_suffix) -> GuardResult{HELD, FLAT, UNREADABLE}`:
      - the whole body is wrapped in `try / except Exception → UNREADABLE`;
      - its first call is `open_intent_blocks()`, and True gives UNREADABLE. The docstring states the venue-global scope;
      - a bad slug (empty, `.`, `^`) gives UNREADABLE;
      - an existing empty index gives UNREADABLE; `FillIndexAbsent` reads as no fills;
      - `net != 0` gives HELD.
    - `guard_veto_reason` maps HELD and UNREADABLE to `rung_net_position_held`.
    - **Key contract (V13), `test_fill_index_key_matches_exec_client_writer`:**
      - (i) for real slugs, `leg_instrument_ids(slug, venue_suffix=".POLYMARKET_US") == (str(slug_to_instrument_id(slug)), str(no_leg_instrument_id(slug)))`;
      - (ii) an AST read of the pinned client asserts `FILL_INDEX_KEY_PREFIX` is `STATE_KEY_NAMESPACE + "fill_index/"` (`:412`), and that every prefix f-string joins one instrument-id expression.
    - **New (architect F12, V25): `test_fill_row_side_vocabulary_matches_exec_record_signs`.** An AST read of the pinned client resolves `_RECORD_SIGNS` (`:668-671`) and `LONG_ONLY_SIDE` (`:663`). It asserts that the key set `{"BUY","SELL"}` equals `get_args` of `FillRow.order_side` and `LegFill.side`, and that the signs are BUY +1 and SELL −1.
    - `net_position.py` and `entry_guard.py` import no `breezy.domain`. `test_leg_suffix_equals_instrument_leg` asserts `"^no" == INSTRUMENT_SEPARATOR + NO_LEG_SUFFIX`.
23. **Veto.** `VetoReason` has exactly the 15 ARCH C5 members (`:642-662`):
    - registry: `registry_not_champion`, `registry_halted`, `registry_unreadable`, `registry_regressed`, `registry_restrictive_pending`;
    - dead engine: `registry_attest_expired`, `registry_engine_heartbeat_stale`, `registry_chain_stale`;
    - transient: `feed_stale`, `recorder_stale`, `permit_lapsed`, `capture_gap`, `capture_untagged`, `alerts_undeliverable`;
    - position: `rung_net_position_held`.

    There is no `EntryVeto` alias. `compose_entry_vetoes` returns the first veto, and any exception gives `registry_unreadable`.
24. **Records.**
    - **C4 verdict.**
      - `verdict_id = sha256(canonical body − {verdict_id, produced_at_ns})`;
      - path `derived/verdicts/<family>/<UTC date of valid_until_ns>/<id>.json`, 0600, write-once;
      - the same id with a body equal apart from `produced_at_ns` is a no-op; any other difference gives `VerdictIdCollision`;
      - validity above `MAX_VERDICT_VALIDITY_H` is refused.
    - **Demand.**
      - The writer: exact-set `demand/v1`, ≤ `DEMAND_FILE_MAX_BYTES`, gated by `DEMAND_WRITER_PRODUCER_IDS`, one file per (family, reason), idempotent on `verdict_id`, with producer cap `DEMAND_FILES_MAX − DEMAND_INTEGRITY_RESERVED`. `producer_id` is advisory.
      - The reader: any bad file, or more than the maximum number of files, gives `venue_veto=True`.
      - There is no archive API.
    - **Journal.**
      - `append_journal(paths, kind, venue, record, *, ts_ns) -> JournalHead` writes a write-once (0444) `journal/v1` envelope linked by `prev_sha256`.
      - Kinds are bare names (`\A[a-z][a-z0-9_]{0,47}\Z`); `JOURNAL_KINDS = frozenset()`.
      - `read_journal_chain` returns entries or `JournalUnverified`.
    - **C3:** `Lineage`, `RootRecord`, `RefitRun`, `model_class_of`.
    - **Drill marker:** AUT-7 r5's 12-key `drill_marker/v1`. ENOENT on the marker gives `MarkerAbsent`; ENOENT on the directory gives `MarkerError`.
    - **C2:** `LABEL_V1_ARROW_SCHEMA`, column for column.
    - Every path component is validated.
25. **Pins.** `pins.py` holds literals only and imports nothing:
    - every ARCH §4.5 ceiling as amended by E-11, with no `SELF_HEAL_*`;
    - `ENGINE_SOURCE_SHA256 = frozenset()`, `PRODUCER_SOURCE_SHA256 = MappingProxyType({})`, `REVOKED_SOURCE_SHA256 = frozenset()`;
    - `ENABLED_WIDENING_KINDS = frozenset()`, `POLICY_RULING_PIN = ()`, `ROOT_ADMIT_ENABLED_CEILING = False`;
    - `LIVE_GATE_ROUTED_KINDS = frozenset({"forecast_quantile_ladder"})`;
    - `BOOTSTRAP_SEED`, `DEMAND_WRITER_PRODUCER_IDS = ("aut6.intraday",)`, `DEMAND_REASONS`, `CAUSE_CODES`, `HALT_REASON_CLASS_MAP` and `DEFAULT_RESTRICTIVE_CLASS`;
    - `SCHEDULE_{STOP,LAUNCH,LAUNCH_WINDOW_END}_UTC`, test-equal to V6;
    - `ENGINE_LOCK_MAX_HOLD_S = 15`, `RELAUNCH_REQUEST_TTL_S = 120`, `WATCH_BUSY_TIMEOUT_MS = 250`, `WATCH_TICK_STALE_S = 180`;
    - `DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY = 1`, `DRAWDOWN_INERT_ALERT_CEILING = "0.5"`, `DRAWDOWN_INERT_ALERT_MIN_FILLS = 10`;
    - `ROW_TS_MAX_SKEW_S = 300`, `EXPORT_FIRST_DUE_H = 26`, `ROOT_ARTEFACT_COMPONENT = "density_table"`;
    - **new:** `BOOTSTRAPPED_ROOT_MANIFEST_SHA256 = MappingProxyType({})` (AC 31).

    Kind sets are `frozenset[str]` validated against `Kind`. Mapping pins use `MappingProxyType`.
26. **C6.** `plugin.py` defines the `CaptureAdapter`, `Scorer`, `Evaluator`, `Detector`/`DriftDetectors` and `Refitter` Protocols with `@property` members, plus `RefusingPlugin`. `NODE_PLUGINS` (strategy) and `OFFLINE_PLUGINS` (analysis) each hold exactly the four `_COMPOSITION_KINDS` keys (`family_manifest.py:118-120`) as literal `MappingProxyType` entries, every value `RefusingPlugin`.
27. **Placeholder ledger.**
    - Rows have the shape `(node_id, owner, owner_symbol "mod:attr", blocks_kinds)`. Carried bodies are fixture-free stubs (`require_owner_symbol(...)` plus a docstring citing the ARCH pin) under `xfail(strict=True, raises=OwnerPending)`.
    - `OwnerPending` is raised only for a `ModuleNotFoundError` on the declared module or one of its `breezy.` ancestors, or for an `AttributeError` on the declared attribute. Every other error propagates.
    - The gate tests are:
      - markers equal the ledger (decorator and `pytest.param` forms, each with a positive control);
      - `test_owner_placeholder_symbol_absent`, `test_owner_ids_exist_in_plan_docs`, `test_envelope_manifest_equals_frozen_arch`;
      - `test_every_envelope_node_id_collected_and_unskipped`, `test_widening_kind_enabled_only_when_its_placeholders_cleared`, `test_blocks_kinds_never_below_floor`;
      - AUT-5's `test_l2_widening_requires_empty_placeholder_ledger`.
28. **Root copies (E-14).** `family_bytes.write_root_copy(paths, *, record: RootRecord, artefact_raw: bytes) -> RootCopyResult{WRITTEN, EXISTS_EQUAL}` writes `artefact.json` and then `roots/<family_id>.json` through `write_once`. EXISTS_DIFFERENT on either file raises `RootCopyIntegrity`. Tests:
    - `test_two_roots_sharing_sha_write_identical_artefact_json`;
    - `test_root_copy_exists_different_is_integrity`;
    - `test_root_copy_rerun_after_chmod_0500_is_exists_equal`, which asserts by `list_dir_at` that no temp file is created;
    - **new (security F9):** `test_refit_into_root_sha_dir_fails_closed`. After the rule-5 chmod, `write_once(<sha>/lineage.json)` gives `DIR_NOT_WRITABLE` and writes nothing. AUT-3 refits write into a fresh `<sha>/` only (E-14 rule 5 note).
29. **Gate.**
    - `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` exits 0 **after every seam commit** (L-43).
    - **Every seam is ≤ 1,000 changed lines; the largest is 950 (WP table).**
    - `lint-imports` passes.
    - The mypy ratchet passes. New files have 0 errors; a ceiling the code falls below is lowered in the same commit and never raised (V17).
    - RED→GREEN logs exist for each real test, with mutation evidence where listed.
30. **Live-path mixed-version safety.**
    - `test_live_path_modules_import_set_pinned` pins the `breezy.*` import sets of `family_manifest.py` (`{breezy.persistence.mechanism_test_guard}`) and of `live_orders_gate.py` (`{breezy.persistence.family_manifest}`).
    - WP-1a, WP-1c and WP-8a add no cross-module import. Each new function's callers are in the same file, and `FamilyManifest` is unchanged.
    - **Merge order (architect F14):** WP-8c, which adds the first external caller of `lineage_policy_authorized`, merges only after the node has relaunched at a 16:50Z LAUNCH following the WP-8a merge. The evidence is a boot line timestamped after the 8a merge. Until AUT-5a, no live process imports `resolver`.
31. **Bootstrapped root manifests are frozen (E-14 rule 7, A4-R9).**
    - `test_bootstrapped_root_manifests_unchanged`: for every `(family_id, sha)` in `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256`, `sha256(/home/jon/breezy/deploy/families/<family_id>.json) == sha`. An edit fails CI instead of failing LAUNCH.
    - `test_bootstrapped_root_pin_is_append_only` compares against `git show <merge-base>:src/breezy/persistence/autonomy/pins.py`, parsed by AST: rows are never removed or changed.
    - `test_bootstrapped_root_pin_covers_bootstrap_seed_once_nonempty`.
    - The pin is empty at ARCH-0. It is filled by binding note 11.

## Edge Cases & NFRs (fail-closed, one-writer, symlink refusal, atomicity, thread-affinity)

**Fail-closed.** Every failure gives the restrictive outcome.

| Input or condition | Result |
|---|---|
| Unknown `schema`; unknown, missing or duplicate key; bool as int; float; NaN or Inf; oversize | `WireRefused(reason)`, which becomes a resolver refusal, a demand venue veto, or `VerdictUnreadable` (engine ERROR) |
| Empty chain under `BREEZY_FAMILY_SOURCE=registry` | `empty_chain` |
| `RegistryUnreadable(busy \| hot_journal \| schema_mismatch \| io \| sqlite_error)` | Resolver: `registry_unreadable` with an enum detail. Watch actor: binding note 8 |
| `venue_seq` gap, renumbering, foreign venue, decreasing ts | `chain_broken` |
| Family introduced by a kind other than BOOTSTRAP/ROOT_ADMIT/MINT; root kind with foreign `lineage_root_family_id` | `validate`: `family_not_introduced` / `root_lineage_mismatch`. Fold: `FoldInvalid`, which becomes `replay_invalid` (resolver) or `registry_unreadable` (watch actor) |
| `now_ns` not an int, ≤ 0, or < head ts − skew | `clock_invalid` / `clock_before_head` |
| HWM Unreadable, unknown reading type, foreign venue, `venue_seq < 1` | `hwm_unreadable` |
| HWM Absent with any row | `hwm_absent`. The clearing path is the reset CLI (binding note 6e) |
| HWM above head; hash at `rows[venue_seq−1]` ≠ `chain_head`; `export_seq` > newest (0 when none) | `hwm_regressed` |
| Exports directory missing or unreadable, or a listing error | `export_unreadable` |
| No export file | `not_yet_due` only within 26 h of genesis, for sending and shadow alike; otherwise `export_unreadable` |
| A widening row outside enabled or admission-implemented | `widening_kind_not_enabled` / `admission_pending`, even on a hand-forged chain (L-24). The store refuses the whole batch; the watch actor applies `rows[:admitted]` and vetoes |
| `stage is not STAGE` outside a fixture | `StageNotCanonical` (store) / `stage_not_canonical` (resolver) |
| More than one CHAMPION/HALTED family | `engine_inconsistency` |
| Role mismatch on public or private entry | `paths_role_mismatch` |
| Root manifest bytes ≠ row | `manifest_sha_mismatch`. A committed edit is caught earlier by AC 31 |
| Root named like a child | Resolved as a root by `origin` |
| Child regex root ≠ `lineage_root_family_id` | `child_root_mismatch` |
| Manifest draft, unpinned, unreadable, invalid, prereg-ineligible, directory missing | `manifest_draft` / `manifest_unpinned` / `manifest_unreadable` / `manifest_invalid` / `prereg_ineligible`, with no path in the value |
| Identity ≠ row; kind not routed | `manifest_identity_mismatch` / `kind_not_live_gate_routed` |
| Root record missing, mismatched or wrong `committed_path` | `root_record_mismatch` |
| Engine sha unpinned or revoked | `engine_code_unpinned` / `engine_code_revoked`. At ARCH-0 every production resolution refuses here by design |
| Root ruling: `no_ruling` / raised refusal / `ok` | `no_live_orders_ruling` / `ruling_refused` with `LiveOrdersRefusal` detail |
| Child: no triple, ruling sha mismatch, ruling ≠ policy | `root_not_lineage_allowlisted` / `ruling_refused` / `ruling_not_policy` |
| Guard: reader raises, empty index, open or corrupt intent, bad slug, unknown side | `UNREADABLE` → veto |
| Demand directory unreadable, bad file, unknown family or reason, over the maximum | `venue_veto=True` |
| Journal link broken | `JournalUnverified`; restrictive writes are never blocked (L-48) |
| `write_once` without hard links, or new file in an owner-read-only directory | `LINK_UNSUPPORTED` / `DIR_NOT_WRITABLE`; there is no rename fallback |

**One writer (L-50).** `/home/jon/breezy/tests/unit/autonomy_writer_table.py` is data, and Wave 1 owners extend it. The AST scan fails on any write site outside `single_read.{write_once, replace_atomic, ensure_dir}` and `registry_store`, which is the only sqlite writer.

| Path | Writer |
|---|---|
| `registry/registry.sqlite` | Under `registry/engine.lock`: the engine and the HWM-reset CLI |
| `evidence/registry/registry_<venue>_<date>[_hwm<k>].jsonl` | Write-once: the engine and the reset CLI |
| `derived/verdicts/**` | Write-once: producers |
| `registry/demand/<venue>/*` | Write-once: the engine and `DEMAND_WRITER_PRODUCER_IDS` |
| `evidence/journal/<venue>/<kind>/<seq>.json` | Write-once: the engine |
| `derived/artefacts/<model_class>/<sha>/{artefact.json, roots/<family_id>.json}` | `write_root_copy` (engine bootstrap). AUT-3 refits write `artefact.json` and `lineage.json` into a fresh `<sha>/` only |
| Exec-store key `autonomy/registry_hwm/<venue>` | The node (under the intent flock); the L1 cut-over and the reset CLI with the node down (AUT-5a row) |

**Paths.** Every path is built by `AutonomyPaths(root)` or by `ShadowPaths` (a distinct class with no shared base; each has a class-level `is_shadow: Final[bool]`). Components use `re.ASCII` `\A…\Z` patterns:

| Component | Pattern |
|---|---|
| venue | `[a-z0-9_]{1,32}` |
| family | `[a-z0-9_]{1,64}` (V19, tested against both existing patterns) |
| model_class | `<kind ∈ _COMPOSITION_KINDS>:[a-z_]{1,48}` |
| sha or verdict id | `[0-9a-f]{64}` |
| date | `date.fromisoformat` |
| journal kind | bare name |
| seq | int ≥ 1, `%010d` |

All I/O goes through the AC 7 openat walk. Each builder has a traversal-vector test.

**Atomicity.**
- A multi-row append is one transaction (`test_store_multirow_append_is_atomic`).
- A crash in `write_once` leaves at most a `.tmp.` file, which the engine sweeps. A crash in `replace_atomic` leaves the old bytes.
- Root copies are written before the genesis COMMIT, and a rerun is idempotent.

**Threads, clock, hygiene.**
- No connection is held across calls, and there are no threads, timers or asyncio (AST).
- There is no module-level mutable state.
- `now_ns` is always explicit.
- Refusals carry enums, never paths (`test_autonomy_payload_hygiene_scan`).

**Size and performance.**
- 10,000 synthetic rows resolve in ≤ 2 s.
- `closure_sha256` runs in ≤ 5 s and ≤ 128 MB.
- The resolver closure carries about 48 MB of pyarrow (V2), accepted against AUT-5's 4 G budget.

**Root permission.** The gate may run as uid 0 under `unshare -r`. Modes are asserted with `stat`. SQLite `mode=ro` is used, and the directory-writability refusal is by mode bit (V30).

## Architecture & Data Flow (modules, public API signatures, storage layout + paths, layering vs import-linter layers app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain)

**Layering.**
- `persistence`, `registry` and `normalize` are independent siblings (`pyproject.toml:97`).
- `persistence.autonomy` imports only stdlib, `persistence` and `settlement`. `breezy.domain` is barred by (b).
- **Pyarrow-reaching types live only in `PYARROW_REACHING` modules (A4-R1, V22).**
- `NODE_PLUGINS` sits in strategy and `OFFLINE_PLUGINS` in analysis. The watch actor (AUT-5a) is `/home/jon/breezy/src/breezy/strategy/autonomy/registry_watch_actor.py`.

**Modules and public API.** Every module uses `from __future__ import annotations` and mypy strict. ★ marks a change in r4.

```text
src/breezy/persistence/__init__.py          docstring only
src/breezy/persistence/family_manifest.py   + parse_family_manifest(raw: bytes, *, path: Path, allow_draft: bool = False) -> FamilyManifest
src/breezy/persistence/live_orders_gate.py  + _LINEAGE_POLICY_ALLOWLIST; CHILD_FAMILY_ID_RE; _verify_ruling_file; LineagePolicyDecision;
                                              lineage_policy_authorized(child, root_family_id, repo_root); _lineage_policy_authorized(..., *, allowlist)
src/breezy/persistence/autonomy/
  __init__.py       docstring only (AST: no import nodes) ★
  canonical.py      canonical_json; sha256_hex; decimal_str; CanonicalTypeError
  wire.py           parse_json_exact; require_*; WireRefusalReason; WireRefused; SHA256_RE; FAMILY_ID_RE
  single_read.py ★  ReadPolicy; open_root; walk_dirs; read_once_at; read_once_nofollow; write_once (pre-read, then DIR_NOT_WRITABLE);
                    replace_atomic; ensure_dir; list_dir_at; SingleReadRefused(reason)
  paths.py ★        AutonomyPaths(root); ShadowPaths(root) (no shared base); is_shadow; builders; root_record(model_class, sha,
                    family_id) [WP-6d]; default_data_root() (entry points only)
  pins.py ★         literals only (AC 25), + BOOTSTRAPPED_ROOT_MANIFEST_SHA256
  veto.py           VetoReason (15); compose_entry_vetoes
  plugin.py         C6 Protocols; RefusingPlugin; is_complete
  closure_manifest.py  CLOSURE_MODULES = MappingProxyType({})
  closure.py        closure_sha256(component); closure_from_grimp(entry) (gate-only, lazy grimp)
  schemas.py ★      State, Kind, CauseClass, CauseCode, WriterMode, DecidedBy, RefusalReason, UnreadableReason, LiveOrdersRefusal (7),
                    FoldInvalidReason; TransitionRow; ExportTrailer; StagePolicy (frozen) + StageView; ManifestFacts (primitives only) +
                    ManifestFactsReader Protocol; AdmissibilityResult(admitted, reason)   -- imports wire, canonical, rollback_journal only
  stage_policy.py   STAGE: Final[StagePolicy] = _build()
  verdict.py        C4 types; verdict_id; write_verdict; read_verdict
  lineage.py        Lineage, RootRecord, RefitRun, RefitOutcome; model_class_of; root_model_class(composition_kind)
  label_schema.py   LABEL_SCHEMA_ID; LABEL_V1_ARROW_SCHEMA; ExcludedReason; PSource; LabelRole
  demand.py         DemandRecord; write_engine_demand; write_producer_demand -> DemandWrite; scan_demands -> DemandScan
  drill_marker.py   DrillMarker (12 keys); read_marker_at -> DrillMarker | MarkerAbsent | MarkerError
  rollback_journal.py  JOURNAL_KINDS; JournalEntry; JournalHead(seq, sha256); append_journal; read_journal_chain
  fold.py ★         fold(rows, venue, now_ns) -> FoldResult | FoldInvalid; resolve_champion; FamilyView(origin, lineage_root_family_id);
                    LineageView; LineageTallies (13 fields); VenueTallies(infra_resumes, drill_close_restores)
  transitions.py ★  ALLOWED; KIND_MASK; WIDENING_KINDS; RESTRICTIVE_KINDS; PAIR_KINDS; _ADMISSION_IMPLEMENTED; is_widening; transition_id;
                    validate(prior, rows, *, mode, now_ns, stage: StageView, manifests: ManifestFactsReader, export_counters=None)
                    -> RefusalReason | None; rows_admissible(rows, *, stage) -> AdmissibilityResult
  chain.py          genesis; transition_hash; VerifiedVenueChain; verify_venue_chain; verify_extension; seq_is_verified_prefix; verify_against_export
  family_bytes.py ★ FamilyBytes; ByteBindingFailure; RootCopyResult; RootCopyIntegrity; read_manifest_facts -> ManifestFacts;
                    verify_family_bytes(row, *, paths, repo_root, origin) -> FamilyBytes | ByteBindingFailure; write_root_copy
  registry_store.py ★ RegistryStore.initialise; RegistryStore(paths).append(rows, *, expected_prior_seq, mode, now_ns) -> AppendResult;
                    _append(..., stage, _fixture_stage=False); StageNotCanonical; WideningNotEnabled; AdmissionPending; write_export;
                    RegistryReader; RegistryUnreadable(reason); newest_export(paths, venue) -> (ExportTrailer, rows) | ExportUnreadable | ExportAbsent
  hwm.py ★          Hwm (validated); HwmAbsent/HwmPresent/HwmUnreadable; REGISTRY_HWM_KEY_PREFIX; hwm_key; hwm_reading_from_bytes; hwm_check; next_hwm
  replay.py         replay_full(chain, *, paths, repo_root) -> ReplayOk | ReplayInvalid | ReplayCauseUnresolved | ReplayArtefactMismatch; _replay_full
  net_position.py ★ LegFill(leg, side, qty, ts_event_ns) (netting-only); net_signed_qty; UnknownSide
  entry_guard.py    GuardResult; FillIndexAbsent; FillRow(order_side, cumulative_qty, ts_event_ns); FillReader; leg_instrument_ids;
                    rung_has_net_position; guard_veto_reason
  resolver.py ★     ResolvedFamily (AC 19); ShadowResolution; ResolverRefusal(reason, detail); HwmMode; FamilySource; read_family_source(env);
                    resolve_sending_family; resolve_shadow_family; SHADOW_CALL_SITES = frozenset(); _resolve(..., stage, lineage_gate, hwm_mode,
                    _fixture_stage=False); manifest_equal_modulo_allowlist
src/breezy/strategy/autonomy/node_plugins.py     NODE_PLUGINS
src/breezy/analysis/autonomy/offline_plugins.py  OFFLINE_PLUGINS
```

**Closed `RefusalReason`.** `test_resolver_refusals_give_no_champion` asserts by AST that the members equal its params. The members are: `registry_unreadable`, `empty_chain`, `chain_broken`, `clock_invalid`, `clock_before_head`, `hwm_unreadable`, `hwm_absent`, `hwm_regressed`, `export_unreadable`, `export_prefix_mismatch`, `widening_kind_not_enabled`, `admission_pending`, `replay_invalid`, `replay_cause_unresolved`, `replay_artefact_mismatch`, `engine_inconsistency`, `no_sender`, `paths_role_mismatch`, `stage_not_canonical`★, `family_not_introduced`★, `root_lineage_mismatch`★, `engine_code_unpinned`, `engine_code_revoked`, `manifest_unreadable`, `manifest_invalid`, `manifest_draft`, `manifest_unpinned`, `prereg_ineligible`, `manifest_sha_mismatch`, `manifest_identity_mismatch`, `kind_not_live_gate_routed`, `artefact_unreadable`, `artefact_sha_mismatch`, `root_record_mismatch`, `child_root_mismatch`, `child_not_equal_root`, `root_not_lineage_allowlisted`, `ruling_not_policy`, `ruling_refused`, `no_live_orders_ruling`, `d0_breach`, `trial_prefix_mismatch`.

`test_live_orders_refusal_mirrors_live_orders_reason` asserts `{m.value for m in LiveOrdersRefusal} == set(get_args(LiveOrdersReason))` (V26). The test may import both; `src/` code in `schemas` may not.

**Storage layout.** All paths are under `/home/jon/.local/share/breezy/`. Directories are 0700, explicitly chmodded. Files are 0600, or 0444 when content-addressed.
- `registry/registry.sqlite` and `registry/engine.lock` (AUT-5a).
- `registry/families/<id>.json` (0444), `registry/demand/<venue>/`, `registry/heartbeat/<venue>.json`, `registry/drill/marker.json`.
- `evidence/registry/registry_<venue>_<YYYY-MM-DD>.jsonl` (0444). The trailer is `{"schema":"registry_export/v1","venue","venue_seq","chain_head","export_seq","evidence_journal_heads"}`; the reset variant is `_hwm<export_seq>.jsonl`.
- `evidence/journal/<venue>/<kind>/<seq:010d>.json` (0444).
- `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json`.
- `derived/artefacts/<kind>:<component>/<sha>/artefact.json` (0444); root records go in `…/<kind>:density_table/<sha>/roots/<family_id>.json`.
- `registry-shadow/` has the same layout and is a `ShadowPaths` root.

**Data flow.**
- Producers (AUT-2, AUT-4, AUT-6) call `write_verdict`.
- The engine (AUT-5a) runs `RegistryReader` → `fold` → `append(rows, CAS, mode, now_ns)` → `write_export`, `append_journal`, `write_engine_demand`, and in bootstrap mode `write_root_copy`.
- `aut6.intraday` calls `write_producer_demand`.
- `resolve_sending_family` (supervisor, settings validator, node) runs `RegistryReader` → `verify_venue_chain` → `newest_export` (→ `newest_export_seq`) → `hwm_check` → `rows_admissible` → `replay_full` (`read_verdict`) → `verify_family_bytes`. Roots read `deploy/families/` and children read `registry/families/` plus `derived/artefacts/`. The gate is `live_orders_authorized` or `lineage_policy_authorized`, and the result is `ResolvedFamily` with `hwm`.
- `resolve_shadow_family` is called by the supervisor shadow branch and the watch actor (AUT-5a, shadow root).
- The watch actor (AUT-5a) runs `read_venue_rows` → `verify_extension` → `rows_admissible` → `validate` → `fold` → `scan_demands` → `hwm_check(newest_export_seq=<carried>)` → `next_hwm(export_seq=<carried>)` → `rung_has_net_position(FillReader)`. **Its `export_seq` starts from the `ResolvedFamily.hwm.export_seq` it booted with, is carried forward unchanged, changes only when the actor calls `newest_export` and verifies it, and is never lowered (architect F3).**
- `store.append` calls `family_bytes.read_manifest_facts`.

## Stub Surface for Wave 1 (table: symbol | consumer plan + section | ARCH-0 delivers real or stub)

"Real" means implemented and tested. "Owner" means outside ARCH-0 (A-R6). **The module named is the frozen import location.**

| Symbol (module) | Consumer | ARCH-0 |
|---|---|---|
| `VetoReason`, `compose_entry_vetoes` (`veto`) | AUT-1 r12 `:1237`; AUT-5 r7 §3.1 | Real; no `EntryVeto` alias |
| `NODE_PLUGINS`, `OFFLINE_PLUGINS`, C6 Protocols, `RefusingPlugin` | AUT-1, 2, 3, 4, 6 | Real; every kind refuses |
| Every pin in AC 25, including `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` (`pins`) | AUT-1 to AUT-7; AUT-5a bootstrap | Real; the new pin is empty |
| Code-identity pins, `closure_sha256` | AUT-5 WP4, AUT-4, AUT-6 | Real machinery, empty pins |
| `StagePolicy`, `StageView`, `RefusalReason`, `LiveOrdersRefusal`, `ManifestFacts`, `AdmissibilityResult` (`schemas`); `STAGE` (`stage_policy`); `_ADMISSION_IMPLEMENTED`, `rows_admissible` (`transitions`) | AUT-5 WP1b, WP5, WP9, WP10 | Real; `admission_implemented` is empty |
| `verdict.*`, `decimal_str` | AUT-2 `:943`; AUT-4 `:450`; AUT-6 `:512` | Real |
| `label_schema.*`, `lineage.*`, `drill_marker.*` | AUT-2, 3, 6, 7 | Real |
| `demand.*` | AUT-6 WP5b; AUT-5 WP4, WP5 | Real |
| `append_journal`, `read_journal_chain`, `JournalHead` | AUT-7 r5 `:91`, `:506` | Real; `JOURNAL_KINDS` is empty |
| `RegistryStore.append`, `KIND_MASK`, `WriterMode`, `transitions.validate` | AUT-7 r5 `:703`; AUT-5 WP4 | Real; widening kinds refused |
| `RegistryReader`, `RegistryUnreadable`, `verify_*`, `fold`, `FoldInvalid`, `resolve_champion`, `LineageTallies`, `VenueTallies` (`fold`) | AUT-3, AUT-4 (tallies except `holdout_opens`), AUT-5, AUT-7; AUT-6 r15 `:1474` | Real |
| `resolve_sending_family`, `ResolvedFamily`, `ResolverRefusal`, `HwmMode` (`resolver`); `FamilyBytes` (`family_bytes`); `Hwm`, `HwmReading`, `hwm_reading_from_bytes`, `hwm_check`, `next_hwm` (`hwm`) | AUT-5 WP5, WP6, WP8, WP10; AUT-1 r12 `:15`, `:329` | Real |
| `resolve_shadow_family`, `ShadowResolution` (`resolver`) | AUT-5 WP5, WP6, WP10 | Real; `SHADOW_CALL_SITES` is empty |
| `verify_family_bytes(row, *, paths, repo_root, origin)`, `write_root_copy` (`family_bytes`) | AUT-7 r5 `:56`, `:703`; AUT-5a | Real |
| `parse_family_manifest`, `lineage_policy_authorized`, `_LINEAGE_POLICY_ALLOWLIST` | resolver; AUT-5 WP9 | Real |
| `entry_guard.*`, `GuardResult`, `FillReader`, `FillRow`; `LegFill` (netting-only), `net_signed_qty` (`net_position`) | AUT-5 WP2, WP5; AUT-2 r7 `:335` | Real |
| **Owner rows** | | |
| Nomination k-checks, policy-stricter bounds, HWM_RESET admission, per-kind `_ADMISSION_IMPLEMENTED` | AUT-5 WP1b | Owner |
| `policy.load_policy_block` | AUT-5 WP3 | Owner |
| `demand.archive` and its 3 tests | AUT-5 WP4 | Owner |
| Derived caches (`families`, `projection`, `lineage_counters`) **including `holdout_opens` and its writer** (V24) | AUT-5 WP4; read by AUT-4 r11 `:431` | Owner |
| `halt_rows.py`, `submit_intent_record.py` and 3 tests | AUT-5a; AUT-6 aliases them | Owner |
| E-8a snapshot helper | Seam B | Other seam |
| `heartbeat/v1`, `halt_mirror/v1`, `stop_complete/v1`, `launch_event/v1`, `relaunch/v1`, `drawdown_control_active` | AUT-5a WP4, 6, 7, 11 | Owner |
| Child artefact location; four-site containment widening | AUT-5a | Owner |
| `PolymarketUsFillReader` | AUT-5a | Owner |
| `_LINEAGE_POLICY_ALLOWLIST` row; child routing in `live_orders_authorized` | AUT-5 WP9 | Owner |
| `net_position.CostedFill`, `average_cost_basis(fills: Sequence[CostedFill], at_ns)` | AUT-2 WP2/WP4 | Owner |
| `JOURNAL_KINDS` members, `verify_journal_chain` | AUT-7 | Owner |
| `sample_size.py`, `nomination.py` | AUT-4 | Owner |
| `capture_*.py` | AUT-1a (E-12) | Owner; joins `NAUTILUS_PERMITTED` |
| C4.1 holdout ruling; AUT-2 Wave-0 egress review | Coordinator; AUT-2a | Owner |

**Frozen signatures.** The surfaces above (names, modules, parameter lists, return unions) are frozen from approval. A later change needs a coordinator erratum. Wave 1 builds against them before they merge.

## File-by-File Plan (absolute path | new|modified | exact content | deps)

| Absolute path | | Content | Deps (ARCH-0 edges, as probed in V22) |
|---|---|---|---|
| `/home/jon/breezy/src/breezy/persistence/__init__.py` | mod | Docstring only (NOTIFIER-IMPORT-ISOLATION precedent) | — |
| `/home/jon/breezy/src/breezy/persistence/family_manifest.py` | mod | AC 21; `__all__` +1 | — |
| `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py` | mod | AC 20 | family_manifest |
| `/home/jon/breezy/src/breezy/persistence/autonomy/__init__.py` | new | Docstring only | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/canonical.py` | new | AC 6 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/wire.py` | new | AC 5 | canonical |
| `/home/jon/breezy/src/breezy/persistence/autonomy/single_read.py` | new | AC 7 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/paths.py` | new | Builders; `root_record` in WP-6d | wire |
| `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py` | new | AC 25 | none |
| `/home/jon/breezy/src/breezy/persistence/autonomy/veto.py` | new | AC 23 | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/plugin.py` | new | AC 26 | veto |
| `/home/jon/breezy/src/breezy/persistence/autonomy/closure_manifest.py` | new | Empty mapping | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/closure.py` | new | `closure_sha256`; lazy grimp | single_read, closure_manifest |
| `/home/jon/breezy/src/breezy/persistence/autonomy/rollback_journal.py` | new | AC 24 | wire, single_read, paths |
| `/home/jon/breezy/src/breezy/persistence/autonomy/schemas.py` | new | Pyarrow-free enums and records only (Modules list) | wire, canonical, rollback_journal |
| `/home/jon/breezy/src/breezy/persistence/autonomy/stage_policy.py` | new | `STAGE` | pins, transitions, schemas |
| `/home/jon/breezy/src/breezy/persistence/autonomy/verdict.py` | new | AC 24 | wire, canonical, single_read, paths, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/lineage.py` | new | AC 24 | wire |
| `/home/jon/breezy/src/breezy/persistence/autonomy/label_schema.py` | new | C2 arrow schema | pyarrow |
| `/home/jon/breezy/src/breezy/persistence/autonomy/demand.py` | new | AC 24 | wire, single_read, paths, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/drill_marker.py` | new | AC 24 | wire, single_read |
| `/home/jon/breezy/src/breezy/persistence/autonomy/fold.py` | new | AC 14 | schemas, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/transitions.py` | new | AC 13 | schemas, pins, fold |
| `/home/jon/breezy/src/breezy/persistence/autonomy/chain.py` | new | AC 11 | canonical, schemas |
| `/home/jon/breezy/src/breezy/persistence/autonomy/family_bytes.py` | new | AC 17, 21, 28; `FamilyBytes` | single_read, paths, lineage, schemas, family_manifest, mechanism_test_guard |
| `/home/jon/breezy/src/breezy/persistence/autonomy/registry_store.py` | new | AC 8–12 | chain, transitions, fold, stage_policy, family_bytes, single_read, paths, schemas |
| `/home/jon/breezy/src/breezy/persistence/autonomy/hwm.py` | new | AC 16 | wire, schemas, chain |
| `/home/jon/breezy/src/breezy/persistence/autonomy/replay.py` | new | Row-by-row `validate(mode=None)`; causes via `read_verdict` | transitions, fold, verdict, chain, family_bytes |
| `/home/jon/breezy/src/breezy/persistence/autonomy/net_position.py` | new | AC 22 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/entry_guard.py` | new | AC 22 | net_position, veto |
| `/home/jon/breezy/src/breezy/persistence/autonomy/resolver.py` | new | AC 17–19; resolver result types | all of the above + live_orders_gate, hwm |
| `/home/jon/breezy/src/breezy/strategy/autonomy/__init__.py`, `/home/jon/breezy/src/breezy/strategy/autonomy/node_plugins.py` | new | Docstring; `NODE_PLUGINS` | plugin |
| `/home/jon/breezy/src/breezy/analysis/autonomy/__init__.py`, `/home/jon/breezy/src/breezy/analysis/autonomy/offline_plugins.py` | new | Docstring; `OFFLINE_PLUGINS` | plugin |
| `/home/jon/breezy/pyproject.toml` | mod | Contracts (a), (b) and (c); **module names only in (b) and (c)** (V23); lists grow per seam; comment: owners append, `capture_*` → `NAUTILUS_PERMITTED` | — |
| `/home/jon/breezy/scripts/ci/regen_closure_manifest.py` | new | Deterministic literal output | grimp |
| `/home/jon/breezy/tests/support/entry_points.py` | new | **Owns** `REPO_ROOT`, `PYPROJECT_PATH`, `DEPLOY_SYSTEMD_DIR` and `SCRIPTS_DIR`, moved byte-identical from `test_runtime_import_isolation.py:55-60` (V29). The two helpers from `:158-190` are moved byte-identical. `_entry_modules_from_scripts_importing(package: str)` is `:192-216` with one parameter replacing `"breezy.runtime"` | — |
| `/home/jon/breezy/tests/unit/test_runtime_import_isolation.py` | mod | **Imports the four constants and three helpers from `entry_points`** (security F8) and binds `_entry_modules_from_scripts_importing_runtime = functools.partial(…, "breezy.runtime")`. The constant definitions and helper bodies are removed. `git diff` must show only import-block, constant-removal and helper-removal hunks, with **no `def test_*` line and no `assert` line changed** | entry_points |
| `/home/jon/breezy/tests/unit/test_mypy_ratchet.py` | mod only if needed | Lower a ceiling only (V17) | — |
| `/home/jon/breezy/tests/support/autonomy_owner.py` | new | `OwnerPending`, `require_owner_symbol` | — |
| `/home/jon/breezy/tests/unit/autonomy_owner_placeholders.py`, `/home/jon/breezy/tests/unit/autonomy_blocks_kinds_floor.py`, `/home/jon/breezy/tests/unit/autonomy_writer_table.py` | new | Ledger 4-tuples; `BLOCKS_KINDS_FLOOR`; writer rows | — |
| `/home/jon/breezy/tests/unit/autonomy_envelope_manifest.py` | new | `ARCH_FREEZE_SHA256`; `E11_RENAMES` (the 3 E-11 rows: `…allowlist_is_literal_and_excludes_trade` → `test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine`; `…cap_survives_process_restart` → `test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all`; `test_restart_window_resets_before_launch` → `test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical`); `ENVELOPE_NODE_IDS` | — |
| `/home/jon/breezy/tests/fixtures/family_manifest_golden/` | new | Corpus, `artefacts/`, `expected.json` | — |
| `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` | **never edited** | V7 byte pin; AST reads only | — |

## Test Strategy (file | test names | unit/contract | which §4.7 rows are real-GREEN in ARCH-0 vs carried strict-xfail with owner)

**Carrying mechanism.** As in AC 27.
- Pytest 9.1.1 fails a non-matching exception and fails a strict XPASS.
- Half-real tests use literal `pytest.param(..., id=...)` ids.
- `test_every_envelope_node_id_collected_and_unskipped` cross-checks AST ids against one `--collect-only -q` subprocess.

**Real-GREEN in ARCH-0.** Each test has a RED log; mutation evidence (L-33) is in brackets. **The Seam column gives the commit that adds each test.** Where a file spans seams, the tests are grouped by seam (architect F8).

| File | Seam | Tests | Type |
|---|---|---|---|
| `/home/jon/breezy/tests/unit/test_persistence_import_free.py` | 1a | `test_persistence_init_has_no_import_nodes`; `test_persistence_has_no_facade_consumers` [planted `from breezy.persistence import write_records`]; `test_persistence_entry_module_imports_cleanly[*]` | contract |
| same | 1c | `test_live_path_modules_import_set_pinned` | contract |
| `/home/jon/breezy/tests/unit/test_family_manifest_split_golden.py` | 1b | `test_parse_split_matches_presplit_golden`; `test_load_family_manifest_keeps_prereg_check` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_canonical.py`, `/home/jon/breezy/tests/unit/test_autonomy_wire.py` | 2a | goldens; decimals; NaN/Inf/exponent; non-str key; float; surrogate; duplicate key; bool-as-int | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_contracts.py` | 2a | `test_autonomy_init_has_no_import_nodes` | contract |
| same | 2b | `test_every_autonomy_module_is_classified` [planted module]; `test_autonomy_core_modules_nautilus_free_at_runtime`; `test_contract_c_refuses_planted_pyarrow_reach[canonical]` | contract |
| same | 6a | `test_contract_c_refuses_planted_pyarrow_reach[schemas]`; `test_autonomy_package_import_graph_is_acyclic` | contract |
| same | 6c | `test_autonomy_policy_not_mutable_from_src` [planted: `StagePolicy(`, aliased `SP(`, `dataclasses.replace`, `copy.copy`, `copy.deepcopy`, `x.__class__(`, `type(x)(`, `object.__new__`, `stage_policy._build`]; `test_admissibility_predicate_has_one_home` [planted read in a fake module] | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_single_read.py` | 2b | `test_walk_refuses_symlinked_intermediate_dir`; `test_read_refuses_fifo_without_blocking`; `test_read_refuses_group_writable_under_strict`; `test_write_once_symlink_at_destination_with_equal_bytes_is_different`; `test_write_once_final_mode_by_stat`; `test_write_once_link_unsupported_fails_closed`; `test_write_once_exists_equal_creates_no_temp`; **`test_write_once_new_file_in_owner_readonly_dir_refused`** [drop the mode check]; `test_replace_atomic_writes_temp_in_target_dir_fsyncs_and_replaces`; `test_read_size_cap`; `test_read_uses_one_fd` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_paths.py` | 3a | traversal vector per builder; `test_family_component_accepted_by_both_existing_id_patterns`; `test_shadow_paths_is_distinct_type` (no shared base; `is_shadow`) | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_pins.py` | 3a | `test_pins_ceilings_within_arch_bounds`; `test_damping_ceilings[ceilings]`; `test_rollback_dwell_age_and_drill_headroom_ceilings`; `test_attest_cadence_has_no_expiry_gap[pins_invariant]`; `test_request_ttl_covers_two_schedule_polls`; `test_root_admit_ceiling_committed_false`; `test_halt_reason_class_map_is_exact`; `test_schedule_constants_equal_supervisor`; `test_enabled_widening_kinds_subset_of_widening_kinds`; `test_root_admit_enabled_requires_ceiling_true`; `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[pins]`; **`test_bootstrapped_root_manifests_unchanged`** [plant a pin row with a wrong sha]; **`test_bootstrapped_root_pin_is_append_only`**; **`test_bootstrapped_root_pin_covers_bootstrap_seed_once_nonempty`** | unit |
| same | 3b | `test_code_identity_pins_cover_import_closure`; `test_engine_pin_history_retained`; `test_closure_manifest_equals_grimp_closure`; `test_regen_output_is_literal_and_reproducible`; `/home/jon/breezy/tests/unit/test_autonomy_closure.py::test_closure_hash_runtime_under_budget` | unit |
| same | 6c | `test_enabled_widening_kinds_subset_of_admission_implemented` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_plugins.py` | 3a/3b | 3a: `test_veto_reason_closed_set_equals_arch`, `test_capture_untagged_is_a_veto_reason`, `test_compose_entry_vetoes_exception_is_registry_unreadable`. 3b: `test_family_plugin_exact_set`, `test_refusing_plugin_refuses_every_member` | unit |
| `/home/jon/breezy/tests/unit/test_entry_guard.py` | 3c | `test_rung_net_position_veto_crosses_legs_and_families[double]`; `test_entry_guard_unreadable_index_vetoes`; `test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]`; `test_net_signed_qty_no_leg_is_short_yes`; `test_negative_net_vetoes`; `test_empty_index_is_unreadable`; `test_open_intent_is_unreadable_and_checked_first`; `test_bad_slug_is_unreadable`; `test_guard_body_exception_is_unreadable`; `test_leg_suffix_equals_instrument_leg`; `test_leg_fill_fields_frozen`; `test_fill_index_key_matches_exec_client_writer` [change `"^no"`]; **`test_fill_row_side_vocabulary_matches_exec_record_signs`** [add `"BUY_SHORT"` to a fixture copy]; `test_autonomy_exec_keys_disjoint_from_halt_prefixes` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_owner_placeholders.py` | 4a | the 8 AC 27 gate tests; `test_require_owner_symbol_propagates_broken_owner_module` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_files_one_writer.py` | 4a | `test_autonomy_files_have_one_writer` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_envelope.py` | 4a | `test_autonomy_never_reads_or_writes_operator_controls` (tokens from `operator_controls.py:142`); `test_autonomy_never_touches_enablement_permit_or_firewall`; `test_autonomy_never_imports_order_path`; `test_autonomy_alert_egress_not_widened`; `test_autonomy_payload_hygiene_scan`; `test_family_source_read_only_by_resolver_and_child_env`; `test_no_asdict_in_autonomy`; `test_no_wall_clock_in_core`; `test_no_threads_or_asyncio_in_core`; `test_autonomy_never_passes_allow_draft_true`; `test_exec_client_never_edited`. Each scan has a planted control and a minimum judged-module count | contract |
| `/home/jon/breezy/tests/unit/test_launch_window_table.py` | 4a | `test_no_unit_overlaps_launch_window[existing_units]`; `test_launch_path_units_end_before_next_fixed_point[existing_units]` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_verdict.py` | 5a | `test_differing_body_same_id_refused` [drop the EEXIST compare]; `test_verdict_id_excludes_produced_at`; `test_recompute_same_slot_same_inputs_same_verdict_id`; `test_verdict_validity_ceiling[writer]`; `test_verdict_exact_set_and_closed_enums`; `test_decimal_fields_canonical_strings` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_records.py` | 5a/5b/6d | 5a: lineage, root and refit_run exact-set and goldens; `test_label_arrow_schema_pinned_column_for_column`. 5b: `test_drill_marker_exact_set_and_absent_vs_dir_missing`. 6d: `test_two_roots_sharing_sha_write_identical_artefact_json`, `test_root_copy_exists_different_is_integrity`, `test_root_copy_rerun_after_chmod_0500_is_exists_equal`, **`test_refit_into_root_sha_dir_fails_closed`** | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_demand.py` | 5b | `test_producer_demand_flood_cannot_exhaust_integrity_slot`; `test_producer_demand_write_is_restrictive_only[writer_api]`; `test_demand_writer_refuses_unlisted_producer`; `test_producer_demand_idempotent_on_verdict_id`; `test_bad_demand_file_vetoes_venue[reader]` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_journal.py` | 5b | `test_journal_envelope_write_once_linked`; `test_journal_unknown_kind_refused`; `test_journal_seq_collision_fails_closed` | unit |
| `/home/jon/breezy/tests/unit/test_registry_schemas_chain.py` (new) | 6a | `test_canonical_row_hashes_venue_and_venue_seq`; `test_transition_id_excludes_expected_prior_seq`; `test_verify_venue_chain_requires_contiguous_seq_single_venue_monotone_ts`; **`test_live_orders_refusal_mirrors_live_orders_reason`**; **`test_schemas_holds_no_pyarrow_reaching_type`** (AST: `schemas` imports none of `live_orders_gate`, `family_manifest`, `mechanism_test_guard`, `family_bytes`, `resolver`, including under `TYPE_CHECKING`) | unit |
| `/home/jon/breezy/tests/unit/test_registry_fold.py` | 6b | structural fold (states, pending pairs, ACTIVATE window, lapse); **`test_rows_admissible_stops_at_first_refused_widening_row`** (restrictive rows before it are counted in `admitted`) | unit |
| same | 7a | the AUT-5 r7 WP1 fold list (crosswalk); `test_post_launch_swap_cancel_voids_pair_only_before_1700`; `test_post_launch_swap_cancel_restores_incumbent[fold]` | unit |
| same | 7b | `test_family_origin_from_introducing_row`; **`test_family_introduced_by_other_kind_is_invalid[ROLLBACK,RESUME,PROMOTE,ACTIVATE,DRILL_ADMIT]`**; **`test_root_kind_with_foreign_lineage_root_is_invalid[BOOTSTRAP,ROOT_ADMIT]`**; **`test_lineage_tallies_fields_equal_arch_counters_minus_non_derivable`**; `test_tallies_alpha_spent_equals_sum_alpha_k`; `test_carried_counters_are_floors`; `test_drill_demote_and_halt_counters_capped` | unit |
| `/home/jon/breezy/tests/unit/test_registry_store.py` | 6e | `test_registry_transition_table_is_exact`; `test_bootstrap_seed_genesis_only`; `test_store_refuses_second_bootstrap_per_venue`; `test_registry_cas_and_idempotent_replay`; `test_registry_hash_chain_and_triggers` [delete the UPDATE trigger]; `test_repeat_supersede_same_family_is_not_replay[arch0]`; `test_family_artefact_binding_immutable`; `test_store_enforces_kind_mask_per_mode` [remove the mask]; `test_daily_refuses_widening_before_stage_flag`; `test_nomination_columns_required_and_read_by_k_check[columns_required]`; `test_store_multirow_append_is_atomic`; `test_insert_or_replace_refused`; `test_on_conflict_do_update_refused`; `test_venue_seq_gap_refused_by_trigger`; `test_first_row_venue_seq_must_be_one` [remove COALESCE]; `test_partial_replay_refused`; `test_append_requires_concrete_mode`; `test_row_ts_skew_and_monotonicity_refused`; `test_writer_pragmas_read_back`; `test_store_sql_has_no_replace_or_ignore`; `test_admission_pending_refused_when_enabled_but_unimplemented`; **`test_admissibility_predicate_shared[store]`** (a spy on `rows_admissible` is called and its result decides); **`test_append_refuses_non_canonical_stage`** | unit |
| same | 6f | `test_registry_readonly_open_engine_stopped`; `test_registry_reader_mode_ro_query_only` [`query_only=OFF`]; `test_reader_refuses_foreign_ddl`; `test_reader_maps_every_sqlite_error`; `test_reader_distinguishes_busy` (V12); `test_export_seq_monotone_and_newest_wins` | unit |
| same | 7c | `test_child_d0_and_trial_prefix_pinned[store]`; `test_drill_close_restore_at_most_one_per_venue_per_day`; `test_drill_close_restore_refused_for_drill_child`; `test_drill_mint_not_counted` | unit |
| same | 7d | `test_mint_unlimited_by_k_max_but_one_per_day`; `test_hwm_reset_store_refuses_carried_counters_below_export[validate]`; **`test_validate_refuses_family_not_introduced`** | unit |
| `/home/jon/breezy/tests/unit/test_registry_hwm.py` | 7e | `test_hwm_reading_from_bytes_maps_none_to_absent_and_garbage_to_unreadable`; `test_hwm_absent_construction_only_in_hwm_module`; `test_hwm_mid_chain_hash_mismatch_regressed` [compare head only]; `test_registry_hwm_refuses_regression`; `test_hwm_export_seq_above_newest_regressed`; `test_next_hwm_is_head_and_verified_export`; **`test_hwm_seq_zero_and_negative_refused`**; **`test_hwm_at_head_compares_last_row`** [index `rows[venue_seq]`]; **`test_hwm_check_unknown_reading_type_is_unreadable`** | unit |
| `/home/jon/breezy/tests/unit/test_lineage_policy_allowlist.py` (AUT-5 WP9 file) | 8a | `test_lineage_policy_allowlist_is_literal_only`; `test_child_requires_lineage_triple_and_policy_ruling`; `test_child_with_operator_ruling_refused`; `test_tampered_policy_ruling_refuses_child`; `test_lineage_gate_refuses_missing_ruling_file`; `test_lineage_gate_refuses_ruling_symlinked_outside_subtree`; `test_lineage_gate_refuses_child_id_outside_root_lineage`; `test_lineage_decision_carries_no_permit_semantics`; `test_verify_ruling_file_extraction_keeps_reasons_and_messages` | unit |
| `/home/jon/breezy/tests/unit/test_registry_replay.py` | 8b | `test_resolver_replays_validate_over_full_fold`; `test_forged_promote_without_resolvable_cause_refused`; `test_artefact_bytes_must_equal_row_sha_at_resolve`; `test_replay_refuses_carried_counters_below_prior_fold`; `test_replay_maps_fold_invalid_to_replay_invalid` | unit |
| `/home/jon/breezy/tests/unit/test_registry_resolver.py` | 8c | `test_resolver_binds_bytes_to_row`; `test_registry_paths_refuse_symlinks`; `test_verify_and_load_share_bytes[resolver]`; `test_child_manifest_equals_committed_root_except_allowlist`; `test_exit_gate_stays_code_only`; `test_registry_champion_requires_live_orders_gate_for_every_kind[resolver]`; `test_resolver_refusals_give_no_champion`; `test_root_resolves_under_live_orders_allowlist`; `test_rollback_to_root_reads_content_addressed_copy`; `test_family_source_registry_requires_bootstrap`; `test_node_relaunch_rule_family_id_and_seq_prefix[resolver]`; `test_child_d0_and_trial_prefix_pinned[resolver]`; `test_rollback_to_earlier_child_passes_d0_rule`; `test_resume_not_subject_to_d0_rule`; `test_root_admit_requires_own_allowlist_triple[resolver]`; `test_resolver_under_budget`; `test_resolver_refuses_chain_with_unenabled_widening_row`; `test_hwm_absent_with_rows_refuses`; `test_hwm_absent_on_genesis_only_chain_refuses`; `test_hwm_unreadable_refuses`; `test_export_absent_after_hwm_saw_export_refuses` (now `hwm_regressed`); `test_export_dir_listing_error_is_export_unreadable`; **`test_no_export_means_newest_export_seq_zero`**; `test_clock_before_head_refuses`; `test_two_senders_is_engine_inconsistency`; `test_manifest_identity_must_match_row`; `test_live_gate_routing_reads_manifest_kind`; `test_equality_covers_new_manifest_fields`; `test_halted_sender_resolves_with_entries_disallowed`; `test_resolver_never_returns_enabled_or_permit`; `test_draft_or_unpinned_manifest_refused`; `test_resolver_runs_prereg_check_on_source_dir`; `test_missing_manifest_dir_is_manifest_unreadable`; `test_root_record_identity_checked`; `test_root_manifest_must_equal_committed_bytes`; `test_root_named_like_child_is_not_routed_as_child`; `test_child_regex_root_must_equal_lineage_root`; `test_resolved_family_carries_arch_c5_pickup_fields`; **`test_resolved_family_hwm_equals_next_hwm`**; `test_admissibility_predicate_shared[resolver]`; **`test_resolve_refuses_non_canonical_stage`**; `test_root_ruling_reasons_map_to_live_orders_refusal` | unit |
| same | 8d | `test_shadow_resolution_ignores_hwm_and_cannot_send`; `test_paths_role_mismatch_both_directions`; **`test_shadow_day2_without_export_refuses`**; **`test_resolve_private_rejects_skip_hwm_on_production_paths`** | unit |

**Promoted to real (A-R3).** Seam 7c:
- `test_drill_promote_refuses_non_champion_sha`, `test_drill_refused_over_halted_incumbent`, `test_drill_budget_separate`, `test_drill_row_refused_while_non_drill_cause_stands`;
- `test_resume_requires_every_cause_cleared`, `test_rollback_failed_resumes_only_under_trigger_class`;
- `test_drill_close_restore_charges_no_drill_or_production_budget`, `test_drill_close_restore_refused_after_non_drill_cause`;
- `test_root_admit_exempt_from_d0_rule`.

Seam 7d: `test_damping_ceilings[counting_rule]` and `test_root_admit_only_when_venue_has_no_sender[validate]`.

Seam 7b: `test_carried_counters_are_floors` and `test_drill_demote_and_halt_counters_capped`.

**AUT-5 r7 WP1/WP2 crosswalk** (unchanged in r4). WP1 has 85 tests: 66 real, 7 split and 12 moved. WP2 has 16: 10 real, 3 split and 3 moved.

| AUT-5 r7 list (count) | Real | Split (real half / owner half) | Moved |
|---|---|---|---|
| WP1 envelope (6) | 6 | — | — |
| WP1 store (26) | 17 | 4: `test_repeat_supersede_same_family_is_not_replay` [arch0 / store→WP1b]; `test_nomination_columns_required_and_read_by_k_check` [columns_required / k_check→WP1b]; `test_child_d0_and_trial_prefix_pinned` [all real]; `test_hwm_reset_store_refuses_carried_counters_below_export` [validate / store→WP8] | 5 → WP1b: `test_nomination_refused_past_k_max_lifetime`, `test_nomination_refused_second_in_window`, `test_alpha_index_never_resets`, `test_two_pending_nominees_get_distinct_k`, `test_infeasible_nomination_charges_no_alpha[store]` |
| WP1 fold (25) | 24 | 1: `test_root_admit_only_when_venue_has_no_sender` [validate / engine→WP4] | — |
| WP1 replay (4) | 4 | — | — |
| WP1 demand (7) | 3 | 1: `test_producer_demand_write_is_restrictive_only` [writer_api / aut6_producer_ast] | 3 → WP4: the `test_demand_archive_*` tests |
| WP1 single read, writer, plug-ins, ledger (5) | 5 | — | — |
| WP1 pins and closure (8) | 6 | 1: `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key` [pins / policy→WP3] | 1 → WP3: `test_policy_map_not_looser_than_fallback_map` |
| WP1 E-7/E-8 (4) | 1 | — | 3 → AUT-5a: the `submit_intent_record` tests |
| WP2 resolver (11) | 8 | 2: `test_verify_and_load_share_bytes` [resolver / loader→WP5]; `test_registry_champion_requires_live_orders_gate_for_every_kind` [resolver / engine→WP4] | 1 → AUT-5a: `test_containment_checks_read_directory_not_phantom_base` |
| WP2 entry guard (5) | 2 | 1: `test_rung_net_position_veto_crosses_legs_and_families` [double / adapter_reader] | 2 → AUT-5a: `test_entry_guard_exact_key_reads_only`, `test_fill_reader_production_default_runs_once` |

AUT-5 r7 WP9's RED list has 7 tests. 4 ship green in 8a: `…_is_literal_only`, `test_child_requires_lineage_triple_and_policy_ruling`, `test_child_with_operator_ruling_refused` and `test_tampered_policy_ruling_refuses_child`. WP9 keeps `test_lineage_policy_allowlist_has_exactly_one_row`, `test_lineage_allowlist_row_equals_policy_pin` and `test_root_keeps_own_ruling`.

**Carried strict-xfail stubs** go in `/home/jon/breezy/tests/unit/test_autonomy_cross_area.py` (seam 4b) unless another file is named. `[blocks]` is in brackets.

| Owner | Tests [blocks] |
|---|---|
| AUT-5 WP1b | the 5 moved nomination tests and `test_nomination_columns_required_and_read_by_k_check[k_check]` [PROMOTE]; `test_repeat_supersede_same_family_is_not_replay[store]` [SUPERSEDE, PROMOTE]; `test_prelaunch_writes_rollback_and_activate_atomically[store_atomic]` [ROLLBACK, ACTIVATE]; `test_resume_admission_reads_policy_block_bounds` [RESUME] |
| AUT-5 WP3 | `test_policy_block_not_looser_than_code_ceilings`; `test_promote_disabled_when_eta_after_kill`; `test_policy_map_not_looser_than_fallback_map`; `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[policy]` [PROMOTE] |
| AUT-5 WP4 | `test_verdict_acceptance_rules`, `test_verdict_accepted_after_attest`, `test_verdict_subject_sha_must_match_row`, `test_verdict_validity_ceiling[engine]`, `test_no_policy_fail_demotes_never_widens`, `test_demotion_never_requires_policy_and_is_immediate[engine]`, `test_intraday_engine_is_restrictive_only[engine]`, `test_resume_written_only_at_prelaunch[engine]`, `test_pending_write_uses_intraday_reconciliation[engine]`, `test_promotion_requires_reconciled_state`, `test_ambiguous_intent_cancels_swap_not_incumbent_launch`, `test_prelaunch_requires_post_stop_reconciliation`, `test_two_intraday_passes_inside_launch_window`, `test_intraday_pass_yields_to_prelaunch_lock`, `test_mirror_read_failure_is_integrity`, `test_root_admit_only_when_venue_has_no_sender[engine]`, `test_root_admit_requires_own_allowlist_triple[engine]`, `test_root_admit_refused_after_operator_halt_within_cooldown`, `test_root_admit_refused_on_stale_halt_mirror` [ROOT_ADMIT]; `test_attest_requires_every_listed_detector`, `test_attest_cadence_has_no_expiry_gap[schedule]`, `test_every_live_verdict_journaled_once_per_daily_pass`, `test_cause_verdict_ids_subset_of_acted_rows`, `test_retired_demand_file_archived`, the 3 `test_demand_archive_*`, `test_registry_champion_requires_live_orders_gate_for_every_kind[engine]`, `test_prelaunch_writes_rollback_and_activate_atomically[prelaunch]`, **`test_holdout_opens_cache_has_named_writer`** (new, V24) [ACTIVATE] |
| AUT-5a (WP2, WP5–WP8, WP10) | `test_hand_relaunch_without_registry_source_refused`, `test_family_source_fixed_in_unit`, `test_watch_actor_never_reads_projection`, `test_registry_unreadable_veto_clears_only_after_verified_read`, `test_attest_expiry_and_chain_staleness_veto_entries`, `test_demotion_latency_slo`, `test_transient_veto_writes_no_transition`, `test_restrictive_commit_failure_sets_node_veto`, `test_attest_veto_armed_after_first_attest`, `test_attest_veto_rearmed_only_after_post_swap_attest`, `test_engine_heartbeat_stale_vetoes`, `test_entry_veto_closed_before_first_tick_and_on_stale_tick`, `test_watch_actor_store_touches_stay_on_loop_thread`, `test_node_relaunch_rule_family_id_and_seq_prefix[node]`, `test_halted_family_boots_entries_vetoed_exits_live`, `test_resume_clears_registry_halted_without_relaunch`, `test_compose_refuses_without_entry_veto_slot`, `test_registry_veto_leaves_exit_seam_open`, `test_registry_unavailable_mints_no_permit`, `test_verify_and_load_share_bytes[loader]`, `test_node_loads_artefact_from_store_by_row_sha`, `test_champion_own_artefact_mismatch_at_load_is_integrity`, `test_swap_cannot_exceed_daily_budget_across_namespaces`, `test_drill_fills_spend_venue_budget`, `test_child_env_touches_only_registry_keys`, `test_child_env_drops_inbound_registry_keys`, `test_registry_shadow_logs_agreement_and_spawns_env_family`, `test_shadow_never_vetoes_or_arms_hand_relaunch_rule`, `test_relaunch_request_schema_exact_set`, `test_incumbent_boot_survives_child_ambiguous_intent`, `test_entry_guard_exact_key_reads_only`, `test_fill_reader_production_default_runs_once`, `test_entry_guard_cache_invalidated_on_fill`, `test_rung_net_position_veto_crosses_legs_and_families[adapter_reader]`, `test_bad_demand_file_vetoes_venue[actor]`, `test_post_launch_swap_cancel_restores_incumbent[supervisor]`, `test_containment_checks_read_directory_not_phantom_base`, the 3 `submit_intent_record` tests, `test_admissibility_predicate_shared[watch_actor]`, `test_node_writes_hwm_at_boot_before_first_entry`, `test_watch_actor_busy_tick_is_unverified_not_veto`, `test_shadow_resolution_cannot_reach_build_child_env`, `test_l1_cutover_writes_initial_hwm_under_exec_flock`; **new in r4:** `test_l1_cutover_hwm_write_slot_ends_by_164455`, `test_watch_actor_applies_admitted_prefix_then_vetoes`, `test_watch_actor_export_seq_never_lowered`, `test_supervisor_busy_retry_only_at_launch`, `test_adapter_reader_fixtures_written_through_record_fill`; HWM-reset: `test_hwm_reset_cli_journals_alerts_and_chains`, `test_hwm_reset_cannot_unhalt`, `test_hwm_reset_never_refunds_counters`, `test_resolver_resolves_after_hwm_reset`, `test_hwm_reset_store_refuses_carried_counters_below_export[store]`, `test_hwm_absent_after_attest_clears_via_reset_cli`, **`test_hwm_reset_requires_expected_head`** [HWM_RESET] |
| AUT-5 WP11 + AUT-2 | `test_drawdown_producer_handshake_with_labels`; `/home/jon/breezy/tests/unit/test_drawdown_producer.py::test_drawdown_gates_on_labels_consumable`; `test_detectors_and_drawdown_include_drill_fills[drawdown]` |
| AUT-6 | `test_deliver_with_proof_reports_non_2xx_through_tee`, `test_critical_alerts_use_delivery_proof`, `test_detector_and_failure_mode_alerts_use_delivery_proof`, `test_critical_survives_sigkill`, `test_concurrent_drainers_send_at_most_once_per_claim_window`, `test_try_submit_latency_independent_of_webhook_latency`, `test_alerts_undeliverable_veto`, `test_alerts_undeliverable_reads_two_days`, `test_drill_inject_passes_when_marker_absent`, `test_drill_marker_read_error_never_resumes`, `test_drill_inject_mapped_only_in_clause`, `test_health_memory_sum_within_memavailable`, `test_oneshot_units_use_timeout_start_sec_not_runtime_max_sec`, the three E-11 tests (new names), `test_producer_demand_write_is_restrictive_only[aut6_producer_ast]`, `test_detectors_and_drawdown_include_drill_fills[detectors]`, `test_shadow_detector_ignores_production_marker`, `test_production_detector_ignores_shadow_marker`, `test_fee_schedule_verdict_feeds_fee_verified_checks`, `test_shadow_probe_marker_accepted_only_under_shadow_root` |
| AUT-2 | `test_p_at_decision_is_bought_leg_probability`, `test_scorer_never_attributes_by_trial_id_prefix`, `test_voided_pair_fills_excluded_from_all_n`, `test_reconciliation_and_entry_guard_never_read_canary_store[reconciliation]`, `test_poststop_venue_read_is_get_only`, `test_retired_kind_keeps_scorer_until_last_fill_labelled`, `test_post_stop_producer_inconclusive_without_stop_signal`, `test_drill_fills_excluded_from_n_and_kill_clock` (with AUT-4) |
| AUT-4 | `test_window_cap_below_n_min_is_inconclusive`, `test_infeasible_nomination_charges_no_alpha[verdict]`, `test_calibration_leg_relative_inconclusive_below_min_buckets` |
| AUT-3 | `test_own_outcome_effect_not_vacuous`, `test_own_outcome_refused_below_min_gate_decisions`, **`test_refit_writes_only_fresh_sha_dir`** (new) |
| AUT-1 and the plug-in owners | `test_every_exit_fill_joins`, `test_decision_id_unique_per_take`, `/home/jon/breezy/tests/unit/test_autonomy_plugins.py::test_every_non_retired_manifest_resolves_to_full_plugins` with params `[capture]` AUT-1, `[scorer]` AUT-2, `[evaluator]` AUT-4, `[detectors]` AUT-6, `[refitter]` AUT-3 |
| AUT-7 | `test_rollback_restores_byte_identical_artefact`, `test_failed_rollback_halts_champion`, `test_drill_rollback_to_superseded_incumbent_admitted`, `test_rollback_fee_check_uses_verdict_not_node_memory`, `test_target_manifest_mismatch_marks_ineligible`, `test_target_byte_mismatch_ineligible_without_freeze[selection]`, `test_drill_halt_never_freezes_or_writes_exec_store[exec_store]`, `test_drill_timeline_matches_aut7_sequence`, `test_failed_drill_close_restored_at_next_prelaunch` [ROLLBACK; RESUME for the last] |

**Existing tests that pass unmodified after every seam commit:**
- `test_operator_control_assignment_scan`, `test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`;
- `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`;
- `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py`, `test_family_manifest.py`;
- `test_runtime_import_isolation.py` (its test bodies), `test_forecast_quantile_ladder_manifest_and_markers.py`.

Coverage is reported per seam. No threshold is invented.

## Work Packages (split into 2–4 commit-sized, independently-gated WPs with order; each seam ≤ ~1,000 changed lines)

**Sizing (A-R5, A4-R10). Every figure below is summed from the table rows.**
- **8 WPs, 27 seam commits.**
- **≈ 6,640 changed lines in `src/` + ≈ 12,300 in tests, fixtures and stubs = ≈ 18,940 total.**
- **Largest seam: 950 (5a, 8c); every seam is ≤ 1,000.**

Compared with r3, this corrects r3's mislabelled totals: r3 claimed 23 seams and about 11.5k lines, but its own table summed to 21 seams and about 17.4k. It splits 3a, 6d, 7b and 8c (+6 seams), and adds about 1.5k lines of new r4 tests. Every seam is merged on its own, followed by the full gate (L-43). Merges are serial, in the table's order.

**Wave-0 wall clock.** 27 merges × 23–25 min of gate = **621–675 min (10.4–11.3 h) of serial gate time**. This is the floor. Build and review time is added per seam and overlaps with the gate of the previous seam. The three live seams (1a, 1c, 8a) also have to fall outside [16:30Z, 17:10Z). Wave 1 overlaps through the early-start points below.

**Binding invariants block (I-1 to I-9).** The coordinator pastes this block verbatim into every WP brief, and each brief below restates it.

> I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).

| Seam | Content | Imports (ARCH-0) | src + test | Activation |
|---|---|---|---|---|
| **1a** | Delete the facade; `entry_points.py` (owns the constants); import-free tests; AC 4 evidence | — | 150 + 450 = 600 | **Live** |
| 1b | Golden corpus on **unsplit** code; coverage evidence | — | 0 + 700 = 700 | Test only |
| **1c** | `parse_family_manifest` split; import-set pin | — | 120 + 80 = 200 | **Live** |
| 2a | `canonical`, `wire`, autonomy `__init__`; contracts (a), (b) and (c) seeded with module names | wire ← canonical | 400 + 450 = 850 | None |
| 2b | `single_read` (including `DIR_NOT_WRITABLE`); classification, runtime and planted-(c) tests | — | 360 + 480 = 840 | None |
| 3a | `paths` (without `root_record`), `pins` (including the root pin), `veto` | paths ← wire | 350 + 350 = 700 | None |
| 3b | `plugin`, `closure_manifest`, `closure`, regen script, `node_plugins`, `offline_plugins` | plugin ← veto; closure ← single_read | 250 + 250 = 500 | None |
| 3c | `net_position`, `entry_guard`; key and side-vocabulary contracts | entry_guard ← net_position, veto | 260 + 520 = 780 | None |
| 4a | Ledger, floor, envelope manifest, writer table, gate tests, envelope scans, launch-window test | pins | 0 + 900 = 900 | None |
| 4b | Carried stubs | — | 0 + 700 = 700 | None |
| 5a | `verdict`, `lineage`, `label_schema` | wire, canonical, single_read, paths, pins | 450 + 500 = 950 | None |
| 5b | `demand`, `drill_marker`, `rollback_journal` | same | 400 + 450 = 850 | None |
| 6a | `schemas` (pyarrow-free only), `chain` | schemas ← wire, canonical, rollback_journal; chain ← canonical, schemas | 400 + 450 = 850 | None |
| 6b | Structural `fold`; structural `transitions` + `rows_admissible` | fold ← schemas, pins; transitions ← fold | 400 + 450 = 850 | None |
| 6c | `stage_policy`; construction ban; one-home predicate test | stage_policy ← transitions, pins, schemas | 80 + 420 = 500 | None |
| 6d | `family_bytes` (+ `FamilyBytes`), `paths.root_record`, `write_root_copy`. **Precondition: E-14 filed** | single_read, paths, lineage, schemas, family_manifest | 320 + 470 = 790 | None |
| 6e | `registry_store`: DDL, triggers, writer, `append`/`_append` | chain, transitions, fold, stage_policy, family_bytes | 380 + 520 = 900 | None |
| 6f | `registry_store`: `RegistryReader`, `write_export`, `newest_export` | same module | 220 + 380 = 600 | None |
| 7a | Full `fold`: states, pairs, voiding, freezes, drill episodes | schemas, pins | 300 + 400 = 700 | None |
| 7b | `LineageTallies`/`VenueTallies`; `origin`; `FoldInvalid` | same | 200 + 350 = 550 | None |
| 7c | `validate` I: drill, RESUME, E-5, d0/prefix | fold | 280 + 380 = 660 | None |
| 7d | `validate` II: Z3, ROOT_ADMIT/BOOTSTRAP, introducers, mint, ATTEST, SWAP_CANCEL, single-sender, HWM_RESET floors | fold | 240 + 420 = 660 | None |
| 7e | `hwm` | wire, schemas, chain | 160 + 380 = 540 | None |
| **8a** | `live_orders_gate` extraction and lineage gate | family_manifest | 120 + 450 = 570 | **Live** |
| 8b | `replay` | transitions, fold, verdict, chain, family_bytes | 250 + 400 = 650 | None |
| 8c | Sending resolver; `ResolvedFamily`, `ResolverRefusal`. **Merges after the node relaunches post-8a (AC 30)** | all + live_orders_gate, hwm | 400 + 550 = 950 | None until AUT-5a |
| 8d | Shadow resolver, `ShadowResolution`, private-entry role assertion; final contract lists | resolver | 150 + 450 = 600 | None |

**Live-path activation (1a, 1c, 8a).**
- Merge outside [16:30Z, 17:10Z).
- The node picks up the change at its next 16:50Z LAUNCH. The supervisor restarts in 01:00 to 16:40Z; `KillMode=process` keeps the node.
- Recorder and ingest pick it up at their next natural start. The stated technical reason for not forcing those restarts: the AC 4 evidence proves behaviour is unchanged, and a recorder restart costs capture continuity.
- AC 30 covers mixed versions.
- Revert is one file per seam.

**Early-start points (A3-R5).**

| Wave-1 area | May build against frozen signatures after | Consuming WP may merge only after |
|---|---|---|
| AUT-1a | 5b | 5b (veto, plugin, pins); `ResolvedFamily.registry_seq` reads after 8c |
| AUT-2a | 5b | 5b; `LegFill` (netting) after 3c; AUT-2's own `CostedFill` lands in AUT-2 |
| AUT-3a | 5b | 5b; fold reads after 7a; refits into a fresh `<sha>/` only (E-14 rule 5) |
| AUT-4a | 5b | 5b; **`LineageTallies` reads after 7b (now valid, architect F15, because F4 is resolved by AC 14)**; `holdout_opens` only after AUT-5 WP4 |
| AUT-6 | 5b | 5b (demand, verdict); fold consumption after 7a |
| AUT-5a | 8d | 8d; WP1b work after 7d |
| AUT-7a | 8d | 8d (`verify_family_bytes`, `append`, journal) |

### WP briefs

Each brief is the coordinator's dispatch skeleton. It is seeded with the matching agent and skill and the stated `projectPath`.

- **WP-1 (1a, 1b, 1c): live-path prep.**
  > I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).
  - RED: `test_persistence_has_no_facade_consumers` (planted control), `test_parse_split_matches_presplit_golden` (green on unsplit code, then unchanged), `test_live_path_modules_import_set_pinned`.
  - Evidence:
    - the grimp and per-entry `_SCHEMAS` diffs;
    - `coverage run --branch` at 100% of `family_manifest.py:262-282` and `:285-460`;
    - an empty `diff` of the moved constants and helpers against `git show d231497d:tests/unit/test_runtime_import_isolation.py` lines 55-60 and 158-190, plus the single parameter hunk for `:192-216`;
    - a `git diff` of `test_runtime_import_isolation.py` with no `def test_*` and no `assert` line changed;
    - the `test_mypy_ratchet` output.
  - Stop if any entry's arrow set differs without a reviewed reason.
- **WP-2 (2a, 2b): bytes and I/O.**
  > I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).
  - RED: the goldens, `test_read_refuses_fifo_without_blocking`, `test_write_once_exists_equal_creates_no_temp`, `test_write_once_new_file_in_owner_readonly_dir_refused`, `test_contract_c_refuses_planted_pyarrow_reach[canonical]`.
  - Contract source lists name modules only (V23). `lint-imports` shows (a), (b) and (c) kept.
- **WP-3 (3a, 3b, 3c): pins, plug-ins, guard.**
  > I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).
  - RED: `test_veto_reason_closed_set_equals_arch`, `test_bootstrapped_root_manifests_unchanged` (planted wrong sha), `test_fill_index_key_matches_exec_client_writer` (mutation: change `"^no"`), `test_fill_row_side_vocabulary_matches_exec_record_signs`, `test_leg_fill_fields_frozen`.
  - The exec client is read by AST only (`:412`, `:663`, `:668-671`).
- **WP-4 (4a, 4b): ledger and envelope.**
  > I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).
  - Verify R13 (`TimeoutStartSec`) first.
  - RED: `test_owner_placeholder_ledger_matches_markers` (planted mismatch), `test_every_envelope_node_id_collected_and_unskipped` (planted skip).
- **WP-5 (5a, 5b): records.**
  > I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).
  - First check the ARCH C4 fields for any non-integer JSON number. If one exists, stop and raise it.
  - RED: `test_differing_body_same_id_refused` (mutation: drop the EEXIST compare).
- **WP-6 (6a to 6f): store core.**
  > I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).
  - **`schemas` imports only `wire`, `canonical` and `rollback_journal` (V22), never `live_orders_gate`, `family_manifest`, `family_bytes` or `resolver`, including under `TYPE_CHECKING`.**
  - 6d waits for E-14 to be filed.
  - RED: `test_contract_c_refuses_planted_pyarrow_reach[schemas]`, `test_schemas_holds_no_pyarrow_reaching_type`, `test_rows_admissible_stops_at_first_refused_widening_row`, `test_autonomy_policy_not_mutable_from_src` (every planted form), `test_admissibility_predicate_shared[store]`, `test_first_row_venue_seq_must_be_one` (mutation: drop COALESCE), `test_reader_distinguishes_busy`, `test_refit_into_root_sha_dir_fails_closed`.
- **WP-7 (7a to 7e): fold, tallies, rules, HWM.**
  > I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).
  - RED: the promoted list, `test_family_introduced_by_other_kind_is_invalid`, `test_lineage_tallies_fields_equal_arch_counters_minus_non_derivable`, `test_hwm_at_head_compares_last_row` (mutation: index `rows[venue_seq]`), `test_hwm_seq_zero_and_negative_refused`, `test_hwm_mid_chain_hash_mismatch_regressed`.
- **WP-8 (8a to 8d): lineage gate, replay, resolver.**
  > I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).
  - 8a is live-path and needs the ruling-site coverage evidence.
  - 8c merges only after a post-8a node relaunch (AC 30).
  - RED: `test_root_manifest_must_equal_committed_bytes`, `test_root_named_like_child_is_not_routed_as_child`, `test_resolved_family_carries_arch_c5_pickup_fields`, `test_resolved_family_hwm_equals_next_hwm`, `test_no_export_means_newest_export_seq_zero`, `test_shadow_resolution_ignores_hwm_and_cannot_send`, `test_shadow_day2_without_export_refuses`, `test_resolve_private_rejects_skip_hwm_on_production_paths`, `test_hwm_absent_on_genesis_only_chain_refuses`, `test_resolver_refuses_chain_with_unenabled_widening_row` (hand-forged chain).

## Binding note for the AUT-5a brief

The coordinator copies this section into the AUT-5a brief verbatim.

1. **WP1b (admission completion)** is a named AUT-5a WP, scheduled before AUT-5 WP10 L1. Its scope:
   - (a) thread the policy block's stricter values into `validate`; the ceilings stay the bound;
   - (b) nomination k-checks, replacing `NominationRequiresPolicy`. These must agree with the fold-derived `LineageTallies.nominations`, `infeasible_nominations` and `alpha_spent` (AC 14); a semantic change needs an erratum;
   - (c) HWM_RESET store admission, with WP8, replacing `RuleSetPending`;
   - (d) a per-kind completeness review against ARCH C5 and AUT-5 r7 §3.2;
   - (e) each kind joins `_ADMISSION_IMPLEMENTED` in the same commit that clears its `blocks_kinds` rows.
2. **The RESUME subset merges before the L1 pins commit `ENABLED_WIDENING_KINDS = {RESUME}`.** It covers:
   - the policy-threaded RESUME bounds (`test_resume_admission_reads_policy_block_bounds`);
   - a re-review of the rules that are already real;
   - then `_ADMISSION_IMPLEMENTED = {RESUME}`.

   Every other widening kind needs WP1b complete before the L2 flag commit.
3. **`_ADMISSION_IMPLEMENTED` is code, not a pin.** It is read only through `STAGE`. `StagePolicy` is never constructed, replaced, copied or re-typed in `src/` (AC 15). `_append` and `_resolve` refuse a non-canonical stage.
4. **Narrowing.** Narrowing `ENABLED_WIDENING_KINDS` below a kind that already has rows makes resolution refuse. The lever is `breezy-registry-hwm-reset` plus a reviewed commit, never a narrowing commit.
5. **`_tick_once`** calls `adm = transitions.rows_admissible(new_rows, stage=STAGE)` before `validate`, evaluated row by row in chain order (architect F11). On a refusal:
   - it applies `new_rows[:adm.admitted]`, so every restrictive row before the refused row takes effect in the in-memory fold;
   - it sets `registry_unreadable`, raises CRITICAL `REGISTRY_REGRESSED`, and does **not** advance the HWM (`test_watch_actor_applies_admitted_prefix_then_vetoes`, `test_admissibility_predicate_shared[watch_actor]`).

   The engine appends restrictive rows in batches separate from widening rows, because the store refuses a whole batch.
6. **HWM obligations.**
   - (a) **Decoding.** HWM bytes are decoded only through `hwm_reading_from_bytes`.
   - (b) **Node boot.** After `resolve_sending_family` and before the entry-veto slot opens, the node writes **`ResolvedFamily.hwm`** under the intent flock (`<exec store>.intent.lock`, V27). It never recomputes the chain or exports. A failed write keeps entries vetoed until a tick writes (`test_node_writes_hwm_at_boot_before_first_entry`).
   - (c) **Ticks.** The actor's `export_seq` starts at `ResolvedFamily.hwm.export_seq`. It is carried forward unchanged, changed only by a verified `newest_export` call, and never lowered. Ticks write only `next_hwm` values after a verified read and never move the HWM backward (`test_watch_actor_export_seq_never_lowered`).
   - (d) **L1 cut-over slot (architect F10).** `/home/jon/breezy/scripts/ops/autonomy_l1_cutover.py` writes the initial HWM (genesis head, `export_seq = 0`) under `flock -w 5` on `<exec store>.intent.lock` (LOCK_EX). The slot opens when the 16:40:05 bootstrap has exited (≤ 16:41:15) and the node is down (`stop_prior_complete`), and **the write must finish by 16:44:55**. That is before the 16:45:00 pre-launch firing, whose E-8 snapshot holds the same flock until at most 16:48:00. If the deadline is missed, the script never writes in [16:44:55, 16:50:00). It aborts the cut-over through the pre-LAUNCH rollback instead: production registry moved aside by rename, the key deleted if written, the source reverted, and the supervisor restarted, each with a one-line heads-up (`test_l1_cutover_hwm_write_slot_ends_by_164455`, `test_l1_cutover_writes_initial_hwm_under_exec_flock`). The cut-over creates `evidence/registry/` with the bootstrap.
   - (e) **Clearing path (L-48).** `breezy-registry-hwm-reset` (AUT-5 WP8) is the named recovery for `hwm_absent` and `hwm_regressed`, including the case before the first export (`test_hwm_absent_after_attest_clears_via_reset_cli`). **New (security F5):** the CLI
     - prints the head hash and every standing DEMOTE and HALT row it is about to accept;
     - **requires `--expect-head <hash>`**, obtained out of band from the last delivered `REGISTRY_*` alert or export, and refuses on mismatch;
     - refuses when the proposed fold is less restrictive than the fold at the last HWM recorded in a delivered alert (`test_hwm_reset_requires_expected_head`).
7. **Shadow source.** Under `registry_shadow`, the supervisor and the watch actor call `resolve_shadow_family` on the `ShadowPaths` root, and they are added to `SHADOW_CALL_SITES` in the same commit. `ShadowResolution` is only logged and never reaches `build_child_env` (`test_shadow_resolution_cannot_reach_build_child_env`). The shadow HWM stays in memory, and the shadow's no-export day 2 refuses (AC 18).
8. **`RegistryUnreadable.reason`.**
   - Watch actor: `busy` means the tick is not verified and state is unchanged, so three busy ticks reach `registry_unreadable` through `WATCH_TICK_STALE_S` (180 s). The other reasons veto immediately.
   - Supervisor: it may retry a `busy` resolve once, **only at LAUNCH**, within its LAUNCH budget (`test_supervisor_busy_retry_only_at_launch`).
   - The engine's read-write open rolls back a hot journal.
   - R14 records the up to 180 s DEMOTE-visibility latency under a held lock.
9. **Bootstrap root copies (E-14).**
   - `write_root_copy` runs per seed before the genesis COMMIT, then the directories are chmodded 0500. A rerun is EXISTS_EQUAL.
   - The **pins commit that fills `BOOTSTRAPPED_ROOT_MANIFEST_SHA256`** for every `BOOTSTRAP_SEED` id merges **before the first bootstrap on any root** (stage S shadow included). A ROOT_ADMIT adds its row in the same commit as its allowlist triple (E-14 rule 7).
10. **Other obligations.**
    - Import `VetoReason` from `veto.py`; the `entry_veto` callable type is defined in strategy.
    - Drop the package-wide Nautilus ban (AUT-5 r7 `:841`) in favour of contracts (b) and (c), which list modules only (V23), plus classification.
    - `append` requires `now_ns`.
    - The E-8 decoders belong to AUT-5a and AUT-6 aliases them. The derived-caches DDL belongs to WP4, which **must name the writer of `holdout_opens`** (V24; `test_holdout_opens_cache_has_named_writer`).
    - `PolymarketUsFillReader` prefixes ids with the imported `FILL_INDEX_KEY_PREFIX` and returns `FillIndexAbsent` only for a missing key.
    - **The `[adapter_reader]` test writes its fixtures through `record_fill` (`client.py:4593`), never by hand (L-42; architect F13; `test_adapter_reader_fixtures_written_through_record_fill`).**
    - The guard cache type is `dict[base_slug, GuardResult]`.
    - The node, supervisor and settings consume `ResolvedFamily.family_bytes`, `registry_seq`, `chain_head` and `hwm`, and never re-read anything.
    - `ResolvedFamily` and `ShadowResolution` are imported from `resolver`, and `FamilyBytes` from `family_bytes`.

## Risk Register

| # | Risk | Evidence | Mitigation / owner |
|---|---|---|---|
| R1 | Root-copy collision | V20 | E-14; 6d waits for it; fail-closed either way |
| R2 | Contract (b) vs E-12; pyarrow reach; package-as-source | V16, V22, V23 | Split (b)/(c); module-only lists; classification; planted controls |
| R3 | `EntryVeto` name collision | AUT-1 r12 `:433` | No alias |
| R4 | Double halt-decoder extraction | AUT-6 r15 `:1664` | A-R6 |
| R5 | `drill_marker/v1` field sets | AUT-7 r5 `:363` | AUT-7's 12 keys |
| R6 | `net_position` weight; AUT-2 cost basis | V1; AUT-2 r7 `:116`, `:722` | No domain import; `LegFill` netting-only; AUT-2 owns `CostedFill` |
| R7 | Facade removal drops a `register_arrow` side effect | V15 | One-time evidence; smoke; one-file revert |
| R8 | WP sizes | Table | 27 seams, each ≤ 1,000 (max 950), each gated |
| R9 | Stale carried test | — | Narrow `OwnerPending`; staleness tests |
| R10 | Early widening via pins | memories | Stage flag; `_ADMISSION_IMPLEMENTED`; shared `rows_admissible`; construction ban; `stage is STAGE` |
| R11 | Concurrent agents | L-51 | Per-WP worktree; re-gate before merge |
| R12 | Gate as uid 0 | `run_tests_no_egress.sh:45-50`; V30 | `stat` modes; `mode=ro`; mode-bit `DIR_NOT_WRITABLE` |
| R13 | Orphaned ingest timer | AUT-6 r15 `:1656` | Verify first in 4a |
| R14 | **Same-uid consistent forgery** | ARCH C5 | Accepted residual. **W1:** a restrictive row appended while no node watches can be rewritten before the next export; the boot HWM write narrows this. **W2 is closed:** Absent always refuses. **`hwm_absent` is a tripwire against accidental deletion, not a control against a same-uid writer** (security F5). Such a writer can also write a low HWM at `venue_seq = 1`, or delete the HWM before the first export and drive the reset CLI. `--expect-head` (binding note 6e) makes that a deliberate act. **Demotion latency:** a held lock delays DEMOTE visibility by up to 180 s; restrictive by timeout (security F6). 0500 is hygiene. The anchors are listed at the top |
| R15 | Demand-flood DoS before WP4's archive | security L2 | Fail-closed, restrictive only |
| R16 | Narrowing after rows exist | — | Binding note 4 |
| R17 | Resolver carries about 48 MB of pyarrow | V2 | Accepted |
| R18 | `pins.py` outside `closure_sha256` | security L3 | `live_proof_paths()` (AUT-5 WP4) |
| R19 | Live-path seams 1a, 1c, 8a | security F10 | Merge window; AC 30; 8c after the post-8a relaunch |
| R20 | `HwmAbsent` blocks LAUNCH if the cut-over write fails | AC 16 | Restrictive. The cut-over aborts before 16:44:55 with its rollback; recovery is a re-run or the reset CLI |
| R21 | Venue-global intent-veto deadlock | node memory | Documented scope; intent retirement; AUT-6 alert |
| R22 | Entry-point smoke cost | V14 | ≤ 60 s measured in 1a; else restrict by evidence |
| **R23** | **A committed edit to a bootstrapped root leaves no sender** (architect F6) | V28 | E-14 rule 7: pinned bytes + CI test. Clearing: revert the edit, or ROOT_ADMIT a new root. L-48 row |
| **R24** | **`holdout_opens` has no C5 row source** | V24 | Excluded from tallies; AUT-5 WP4 owns the cache and must name its writer. If WP4 cannot, a coordinator erratum is owed. AUT-4's single confirmatory open is not blocked by ARCH-0 |

## LESSONS Compliance

Every number was checked against its `/home/jon/breezy/docs/core/LESSONS.md` header on 10-03.

| Lesson | Compliance |
|---|---|
| L-1 | Null-hypothesis rows below |
| L-12 | Exact sets; the split is a pure move proven by golden + coverage; empty allowlists; HWM refinement |
| L-14 | `RefusalReason`, `VetoReason`, `UnreadableReason`, `LiveOrdersRefusal` and `LineageTallies` are derived from ARCH, code and probes, with AST/`get_args` equality tests |
| L-16 | No timers; a veto composer exception is `registry_unreadable` |
| L-19 | Facade removal simulated statically and at runtime |
| L-22 | Frozen `STAGE`, construction ban, identity check, private seams |
| L-24 | Hand-forged chains for the resolver, HWM and introducing-row tests |
| L-29 | No diagnostics buffers; no module-level mutable state |
| L-33 | Mutation evidence per guard test |
| L-39 | No operator-control env names; scan tokens from `operator_controls.py:142` |
| L-42 | Key and side-vocabulary contracts read the real writer by AST (V13, V25). **The `[adapter_reader]` fixtures are written through `record_fill` (binding note 10)**, which replaces r3's weaker "real shape" claim |
| L-43 | Full gate after each of the 27 seams |
| L-44 | Netting tested at each leg's terminal state |
| L-46 | Contract tests grepped first: archive, probe containment, exec pin, mypy ceilings |
| L-47 | Every new code fact has a file:line or a probe (V22–V31). The architect's `_RECORD_SIGNS` citation is corrected (V25). V30 is marked unprobed |
| L-48 | Every refusing latch has a clearing path: `hwm_absent`/`hwm_regressed` → reset CLI (`--expect-head`) or the cut-over abort; intent veto → retirement; **root-manifest edit → revert or ROOT_ADMIT (E-14 rule 7)**; restrictive writes are never blocked |
| L-50 | Writer table plus write-once |
| L-51 | Exact interpreter; no `uv`, `pip` or `stash` |
| L-54 | Pin search done (V17); `entry_points.py` owns the constants with byte-diff evidence; ceilings only lowered |
| L-55 | `[adapter_reader]` runs the production `FillReader` once (AUT-5a) |

**L-1 null-hypothesis rows.**

| Need | Existing capability | Verdict |
|---|---|---|
| C5 store | SQLite + triggers (V4, V11) | Native |
| Exact-set records | stdlib `json` hooks | Reuse |
| Atomic files | `os.link`/`os.replace` via dirfds | Stdlib |
| Single read | Nothing in Nautilus | Build (small) |
| Read-only reader | SQLite `mode=ro` | Reuse |
| Resolver checks | `live_orders_authorized`, `load_family_manifest` | Reuse by extraction and split |
| Netting | `DurableFillRecord` + `_RECORD_SIGNS` | Restate, contract-tested (V13, V25) |
| C6 | Protocols | Build |
| Closure | grimp | Reuse, gate-only |
| Journal | write-once | Build |
| Import isolation | `runtime/__init__` precedent | Reuse |
| Arrow evidence | Nautilus `_SCHEMAS` | Reuse, read-only |
| Contract checks | import-linter (V22, V23) | Reuse |

## Trade-offs (options considered, evidence, choice)

| Decision | Options | Choice and evidence |
|---|---|---|
| `persistence/__init__` | lazy PEP 562; delete | **Delete** (V3) |
| Reachability proof | grimp gate test; one-time evidence + smoke | **One-time evidence + permanent smoke** |
| `HwmAbsent` on genesis | allow; always refuse | **Always refuse**, with named clearing paths |
| Shadow resolution | flag; separate function and type | **Separate function and type**, plus the private-entry assertion |
| Root or child | regex; chain `origin` | **Chain origin**; the regex is a Y6 check; any other introducer is invalid |
| Root manifest source | either directory; committed only | **`deploy/families` only, REPO**, frozen after bootstrap (rule 7) |
| Entry-guard key | ARCH-0 full key; ids + adapter prefix | **Ids + AST contracts** on the prefix and side vocabulary |
| Pyarrow-reaching result types | `schemas` + `TYPE_CHECKING`; `ManifestFacts` Protocol only; move to pyarrow-reaching modules | **Move** to `resolver`/`family_bytes`, with a local `LiveOrdersRefusal` in `schemas` (A4-R1). `TYPE_CHECKING` still counts (V22) |
| Contract source lists | package; module names | **Module names** (V23) |
| `StagePolicy` location | `stage_policy.py`; `schemas.py` | **`schemas.py`** (no cycle) |
| Store admission check | inline; shared predicate | **Shared `rows_admissible`** (A4-R2) |
| HWM export seq source | node re-reads; `ResolvedFamily.hwm` | **`ResolvedFamily.hwm` + `verified_export_seq`** (A4-R4) |
| AUT-4 tally source | WP4 cache; fold | **Fold for 13 + 2 fields; `holdout_opens` from the WP4 cache** (A4-R7, V24) |
| `LegFill` cost | add cost/fee; netting-only + AUT-2 `CostedFill` | **Netting-only** (A4-R8); AUT-2 keeps one `average_cost_basis` |
| Root manifest edits | allow; freeze by pin + CI | **Freeze** (A4-R9) |
| 0500 directory writes | rely on EACCES; mode-bit check | **Mode bit** (V30; deterministic under uid 0) |
| Lineage-gate placement | WP-1; before resolver | **8a** |
| Fold-decidable rules | defer; implement | **Implement** (A-R3) |
| Derived caches | ARCH-0; WP4 | **WP4** (YAGNI) |

## Confidence Self-Assessment (HIGH|MEDIUM|LOW + explicit unknowns)

**HIGH for design; MEDIUM-HIGH for schedule.** The r3 HIGH is closed by a probe that runs the actual contract over the r4 import edges (V22). The probe also surfaced, and r4 fixes, a second contract defect that no review caught (V23).

Unknowns:
1. E-14, including rule 7, must be filed before 6d.
2. The entry-point smoke time is measured in 1a.
3. Corpus size is decided by coverage, not by count.
4. `CAUSE_CODES` and `DEMAND_REASONS` are closed choices.
5. Ingest `TimeoutStartSec` is checked in 4a.
6. A C4 non-integer JSON field stops 5a.
7. AUT-5a must accept binding notes 5 to 11.
8. The `holdout_opens` writer is unnamed (R24).
9. uid-0 DAC behaviour is unprobed (V30). The design does not depend on it.
10. The `test_contract_c_refuses_planted_pyarrow_reach` runtime is unmeasured; it is marked `heavy`.

## §R4 Disposition

**r3 security review (APPROVE, 1–9).**

| # | Finding | Disposition | Where |
|---|---|---|---|
| 1 | HWM seq indexing (MED) | FIXED (A4-R3): domain checks, `rows[venue_seq−1]`, unknown → `hwm_unreadable`, three tests | AC 16; 7e |
| 2a | `schemas` breaks (c) (MED) | FIXED (A4-R1): types moved, local `LiveOrdersRefusal`, planted control; proven by probe (V22) | AC 1, 2, 19; Modules; 6a |
| 2b | AC 10.4 second predicate (MED) | FIXED (A4-R2): store calls `rows_admissible`; `[store]` param | AC 10.5, 13 |
| 3 | StagePolicy AST precision (MED) | FIXED (A4-R5): forms banned in the three autonomy packages, alias resolution, planted controls, `stage is STAGE` | AC 15, 10.1, 17.0 |
| 4 | Origin for other introducers (MED) | FIXED (A4-R6): `FoldInvalid`; `validate` refusals; tests | AC 13, 14 |
| 5 | Reset CLI before first export (LOW) | FIXED as an AUT-5a obligation (`--expect-head`, restrictiveness check, test); R14 tripwire wording | Binding note 6e; R14 |
| 6 | Lock delays DEMOTE (LOW) | FIXED: R14 latency residual; supervisor busy retry only at LAUNCH | R14; binding note 8 |
| 7 | Shadow split only at public entries (LOW) | FIXED: `_resolve` role assertion; `ShadowPaths` has no shared base; `is_shadow`; test | AC 17.0, 18 |
| 8 | Helper-move hunk contradiction (LOW) | FIXED: `entry_points.py` owns the constants (V29); diff evidence shows no test or assert line changed | File plan; WP-1 |
| 9 | 0500 vs refit (LOW) | FIXED: `DIR_NOT_WRITABLE` by mode bit (V30); `test_refit_into_root_sha_dir_fails_closed`; AUT-3 fresh `<sha>/` note | AC 7, 28; E-14 rule 5 |

**r3 architect review (REQUEST_CHANGES, 1–15).**

| # | Finding | Disposition | Where |
|---|---|---|---|
| 1 | (HIGH) `schemas` breaks (c) | FIXED = security 2a; probed (V22); also found and fixed V23 | AC 1, 2, 19 |
| 2 | AC 10.4 vs one-home rule | FIXED = security 2b | AC 10.5 |
| 3 | HWM pickup | FIXED (A4-R4): `ResolvedFamily.hwm` + `verified_export_seq`; steps 3 and 4 swapped; no export = 0; tick carry-forward | AC 16, 17, 19; data flow; note 6b/c |
| 4 | Tallies, `holdout_opens` | FIXED (A4-R7): frozen fields with derivability (V24, V31); `holdout_opens` → WP4; test; (b) item 29 corrected | AC 14; Stub table; R24 |
| 5 | `LegFill` vs AUT-2 | FIXED (A4-R8): netting-only; AUT-2 `CostedFill`; (b) item 30 | AC 22; (b) |
| 6 | E-14 liveness trap | FIXED (A4-R9): rule 7, pin, CI tests, clearing paths, L-48, R23 | AC 31; E-14 |
| 7 | Sizing | FIXED (A4-R10): 27 seams, totals summed from rows, max 950, gate floor 10.4–11.3 h, header fixed | WP table |
| 8 | Store tests vs 7b | FIXED: Seam column; tests regrouped into 6e, 6f, 7c, 7d | Test Strategy |
| 9 | Shadow `not_yet_due` | FIXED: same 26 h rule; test | AC 18 |
| 10 | Cut-over lock timing | FIXED: intent flock named (V27), slot ends 16:44:55, abort rather than late write, test | Note 6d; (b) 24 |
| 11 | Batch vs restrictive row | FIXED: per-row prefix `admitted`; actor applies the prefix | AC 13; note 5 |
| 12 | Fill-side vocabulary | FIXED: AST test against `_RECORD_SIGNS`. The review's citation `:3442-3455` is corrected to `:668-671` (V25) | AC 22 |
| 13 | L-42 overstated | FIXED: fixtures through `record_fill` | Note 10; LESSONS |
| 14 | AC 30 merge order | FIXED: 8c after the post-8a relaunch | AC 30; WP table |
| 15 | AUT-4a early start | FIXED: cross-referenced to AC 14 | Early-start table |
| — | Self-found: package-as-source in (b)/(c) | FIXED: module-only lists; AST test on autonomy `__init__` | V23; AC 1 |

**r2 findings (§R3, condensed); all remain FIXED in r4.**
- **Security 1–11:**
  - 1: root anchor (A3-R1);
  - 2: HWM mid-chain, single decoder;
  - 3: windows; listing error → `export_unreadable`;
  - 4: arrow-registry evidence;
  - 5: StagePolicy ban (strengthened in r4);
  - 6: corpus coverage gate;
  - 7: guard key contract; `open_intent_blocks` first;
  - 8: origin-based child-ness (completed in r4);
  - 9: helper extraction (completed in r4);
  - 10: AC 30 import pin (merge order added in r4);
  - 11: shared-sha root tests.
- **Architect 1–16:**
  - 1: `ResolvedFamily` fields (completed in r4);
  - 2: shadow function and Absent liveness;
  - 3: COALESCE;
  - 4: shared predicate (store added in r4);
  - 5: `UnreadableReason`;
  - 6: amendment list;
  - 7: AUT-6 `:1474`;
  - 8: `LegFill.ts_event_ns` (netting-only in r4);
  - 9: E-14 scope and order;
  - 10: schedule and early start;
  - 11: `root_record` (now 6d);
  - 12: entry_points parameter;
  - 13: per-seam gating (honest in r4);
  - 14: no cycle;
  - 15: named single-read exemption;
  - 16: no chatter.
- **New in r3:** V16 (contract split).

**r1 findings (§R2, condensed); all remain FIXED.**
- python B1–B5 and P-n1–P-n13 (AC 1–3, 5–12, 23–29; P-n5 accepted; P-n7 fixed by deleting the facade).
- security H1–H7 (AC 13, 15–17, 20–22; H2 `permit_present` parameter REJECTED; H4 node marker REJECTED and superseded by always-refuse).
- security M1–M11 and L1–L5 (AC 5, 10–12, 17, 24, 30; R15, R18; M6 REJECTED because `path` drives containment, V9).
- architect H1–H6, M1–M6 and L1–L5 (AC 2, 4, 13, 23, 25, 27; crosswalk; owner rows; binding note; L3 moot).
- The defer-records observation REJECTED (ARCH §5.1).
- A-R4 and A-R6 (E-14; owner rows).

## §ERRATA-REQUEST

**(a) E-14, final text, to be filed verbatim:**

> **E-14 (coordinator, 2026-10-03; from ARCH-0 seam A r1–r4 and the r1–r3 architect and security reviews): per-family root records.**
> - **Defect.** ARCH C3 "Bootstrap roots" (line 261) writes one `root.json` per `derived/artefacts/<model_class>/<sha>/`. `pm_us_crh_v4` and `pm_us_crh_cont` are both `continuous_rung_hold` with `density_artefact_sha256 = 247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65` (the `not_applicable_density.json` placeholder) and both are RETIRED seeds (line 738). Their `root/v1` bodies differ in `family_id` and `manifest_sha256`, so the second write-once returns EXISTS_DIFFERENT and the genesis BOOTSTRAP cannot complete. Separately, ARCH lines 263-264 expect the committed root file to change after bootstrap, which, once the resolver binds a root to its committed bytes, leaves the venue without a sender at the next LAUNCH.
> - **Rule.**
>   1. A root copy is written to `derived/artefacts/<model_class>/<sha>/artefact.json` (0444) and `derived/artefacts/<model_class>/<sha>/roots/<family_id>.json` (0444, `root/v1`, fields unchanged). This replaces `<sha>/root.json` in ARCH C3 line 261, AUT-5 r7 §3.2 lines 172 and 180, and AUT-7 r5 line 41 and `test_rollback_to_root_reads_content_addressed_copy` (line 569).
>   2. A root copy's model class is `f"{composition_kind}:{ROOT_ARTEFACT_COMPONENT}"` with `pins.ROOT_ARTEFACT_COMPONENT = "density_table"`; a root's artefact is its manifest's density artefact.
>   3. **Scope: families whose introducing row is BOOTSTRAP or ROOT_ADMIT with `lineage_root_family_id == family_id` ("roots"), whatever the authorising kind (BOOTSTRAP, ROOT_ADMIT, ROLLBACK, RESUME).** A family introduced by any other kind, or a BOOTSTRAP/ROOT_ADMIT row with `lineage_root_family_id != family_id`, invalidates the chain. For a root the resolver (a) reads the manifest only from `deploy/families/<family_id>.json` in the repo (never a registry copy) and refuses `manifest_sha_mismatch` unless its sha256 equals `row.manifest_sha256`; (b) reads `roots/<row.family_id>.json` and refuses `root_record_mismatch` unless `record.family_id == row.family_id`, `record.manifest_sha256 == row.manifest_sha256`, `record.artefact_sha256 == row.artefact_sha256`, and `record.committed_path == "deploy/families/" + family_id + ".json"` exactly. Children are out of scope: a Y2 no-new-lineage child resolves `artefact.json` in the existing `<sha>/` directory and has no `roots/` record; a new-lineage child is bound by its C3 `lineage.json`.
>   4. A second root sharing a `<sha>` directory writes `artefact.json` as an EXISTS_EQUAL no-op. EXISTS_DIFFERENT on `artefact.json` or on a `roots/<family_id>.json` is INTEGRITY.
>   5. The `<sha>/` and `roots/` directories become 0500 after the genesis transaction's last copy. This is hygiene, not a control (same-uid residual). A new file in a 0500 directory is refused by mode bit (`DIR_NOT_WRITABLE`), so AUT-3 refits write `artefact.json` and `lineage.json` into a fresh `<sha>/` only, never into a root's directory.
>   6. **Order and idempotence.** Every copy is written before the genesis BOOTSTRAP COMMIT. A crash and rerun is idempotent: an existing file with equal bytes is EXISTS_EQUAL, decided by reading it before any temp file is created, so a rerun succeeds even after the rule-5 chmod.
>   7. **Frozen committed root bytes.** Once a root is bootstrapped or root-admitted on any registry root (production or shadow), its `deploy/families/<family_id>.json` bytes are frozen. `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256` (a `MappingProxyType` of `family_id → sha256`, empty until the reviewed pins commit that precedes the first bootstrap, which lists every `BOOTSTRAP_SEED` id; a ROOT_ADMIT adds its row in the same commit as its allowlist triple) pins them. Rows are append-only. `test_bootstrapped_root_manifests_unchanged` fails CI on any edit, so the failure lands at merge rather than at LAUNCH. Superseding a bootstrapped root, including setting `terminal_climate_day`, is done in the registry (RETIRE) or by a new root (a new `family_id` through ROOT_ADMIT), never by editing the committed file. **Clearing path (L-48)** if an edit reaches a running tree anyway (resolver `manifest_sha_mismatch`, no sender, entries vetoed): a reviewed revert restoring the pinned bytes, or ROOT_ADMIT of a new root. ARCH lines 263-264 ("even if the repo file changes") are refined accordingly: ROLLBACK to a root still reads the store artefact, but the root's committed manifest bytes must equal the row.
> - **Consumption.** ARCH-0 seam A (`paths.root_record`, `family_bytes.write_root_copy`, the resolver, `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256`, `single_read` `DIR_NOT_WRITABLE`); AUT-5a bootstrap and the pre-bootstrap pins commit; AUT-7 r5 root reads; AUT-3 refit destinations. Fail-closed until filed: BOOTSTRAP refuses and nothing goes live.

**(b) The complete list of ARCH and plan text that r4 amends.** The coordinator records these alongside E-14. ★ marks items new or changed in r4.

**ARCH**
1. C5 resolver, "checks the export prefix and the node high-water mark": refined (L-12) to a tri-state HWM with mid-chain hash verification at `rows[venue_seq−1]`, domain `venue_seq ≥ 1` and `export_seq ≥ 0`, `HwmAbsent` refusing on any non-empty chain, `Hwm.export_seq`, a listing error → `export_unreadable`, and exports evaluated before the HWM (no export = `newest_export_seq` 0). ★
2. C5 shadow stage: `resolve_shadow_family` and `ShadowResolution`, with the same 26 h no-export rule. ★
3. Y6: root and child status come from the introducing row; any other introducer, or a root kind with a foreign lineage root, invalidates the chain; the regex is a consistency check. ★
4. ★ C3 lines 263-264: E-14 rule 7.
5. ★ C5 lines 431-434: `holdout_opens` has no row source. The fold derives every other counter (`LineageTallies`, `VenueTallies`); `holdout_opens` stays an AUT-5 WP4 cache field whose writer WP4 names.

**AUT-5 r7**
6. §3.1 `__init__` "Public names only" → docstring only.
7. §3.1 `single_read` "`lstat` walk" → openat walk, EXISTS_EQUAL pre-read, `DIR_NOT_WRITABLE`. ★
8. §3.1 `VetoReason` → imported from `veto.py`.
9. §3.1 `schemas.py` records → owner rows. `StagePolicy` lives in `schemas`. ★ `ResolvedFamily`, `ShadowResolution` and `ResolverRefusal` live in `resolver`, and `FamilyBytes` in `family_bytes`.
10. `:116` `entry_guard`: `legs` → `venue_suffix`; `GuardResult`; `FillIndexAbsent`; `open_intent_blocks()`; `FillRow.ts_event_ns`; ★ `FillRow.order_side: Literal["BUY","SELL"]`, contract-tested against `_RECORD_SIGNS`.
11. `:410` `parse_family_manifest(raw, *, path, allow_draft=False)`; the node consumes `ResolvedFamily.family_bytes`.
12. `:421` busy handling keyed on `RegistryUnreadable.reason`; ★ the supervisor retries busy only at LAUNCH.
13. `:423` `_tick_once` calls `rows_admissible` before `validate`; ★ per row, applying the admitted prefix and leaving the HWM unadvanced on refusal.
14. `:425` the node boot HWM write ★ writes `ResolvedFamily.hwm`. `:426` shadow → `resolve_shadow_family`. ★ The tick `export_seq` is carried forward and never lowered.
15. `:427` guard cache → `GuardResult`.
16. `:441` `resolved_registry_seq` = `ResolvedFamily.registry_seq`.
17. `:480-488` the reset CLI handles the case before the first export and is the clearing path for `hwm_absent`; ★ it gains `--expect-head`, prints standing DEMOTE and HALT rows, and refuses a fold less restrictive than the last alerted HWM.
18. WP1 Files `:841` Nautilus ban → contracts (b) and (c) ★ listing module names only, plus classification.
19. §3.2 DDL: `NOT NULL` on `venue` and `venue_seq`; COALESCE trigger; `user_version`, `application_id`.
20. §3.2 append: `PartialReplay`; `now_ns`; ts skew; `AdmissionPending`; ★ admission through `rows_admissible`; `StageNotCanonical`; caches deferred to WP4.
21. §3.2 export trailer gains `schema`, `venue` and `evidence_journal_heads`.
22. §3.2 lines 172 and 180 → E-14.
23. §4 ledger tuple gains `owner_symbol` and `blocks_kinds`; `raises=OwnerPending`; E-11 rename at `:825`.
24. WP1 and WP2 RED lists → the crosswalk.
25. WP9 RED list `:927`: 4 of 7 ship in ARCH-0.
26. WP10 L1 cut-over `:937`: creates `evidence/registry/`; ★ the initial HWM write runs under `flock -w 5` on `<exec store>.intent.lock` between the bootstrap exit (≤ 16:41:15) and **16:44:55**, never in [16:44:55, 16:50:00). A missed deadline aborts through the pre-LAUNCH rollback, including deleting the key it wrote.
27. ★ WP4 `lineage_counters`: names the `holdout_opens` writer (`test_holdout_opens_cache_has_named_writer`).
28. ★ The pre-bootstrap pins commit fills `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` (stage S included).

**AUT-7 r5**
29. `:56`, `:703` `verify_family_bytes(row, *, paths, repo_root, origin)`.
30. `:91`, `:506`, `:703` `append_journal(paths, kind, venue, record, *, ts_ns)`; bare kinds; `append(..., now_ns)`.
31. `:41`, `:569` → E-14.

**AUT-4 r11**
32. `:18`, `:404`, `:1372` lazy `__init__` → facade deleted.
33. ★ `:431` (corrected from r3 item 29): `nominations`, `infeasible_nominations` and `alpha_spent` are read from `fold(...).lineages[*].tallies` (`LineageTallies`, pure, after seam 7b). **`holdout_opens` remains a read of the AUT-5 WP4 `lineage_counters` cache.** `:563` and `:567`: `lineage_counters.nominations` → `LineageTallies.nominations`, with the same meaning (max feasible `k_life`).

**AUT-2 r7**
34. ★ `:68`, `:116`, `:631`: `net_position.py` is created by ARCH-0 with `LegFill` (netting-only) and `net_signed_qty`, and it imports no `breezy.domain`. AUT-2 adds `CostedFill` and `average_cost_basis(fills: Sequence[CostedFill], at_ns)` to the same module, so `:736`'s single-definition test is unchanged and `LegFill` is never edited.
35. `:335` netting uses `LegFill.ts_event_ns`.

**AUT-6 r15**
36. `:2254` is stale; the ER-2 name at `:1746` wins.
37. `:512` the verdict date comes from `write_verdict`.
38. `:1474` consumes the fold; no change.

**AUT-1 r12**
39. `:1237` `SELF_HEAL_RESTARTABLE_UNITS` is stale (E-11); `EntryVeto` names only the C1 record.
40. `:329` `DecisionRecord.registry_seq` = `ResolvedFamily.registry_seq`.

**AUT-3 r6**
41. ★ Refit outputs go to a fresh `derived/artefacts/<model_class>/<sha>/` only (E-14 rule 5); `test_refit_writes_only_fresh_sha_dir` is carried to AUT-3.
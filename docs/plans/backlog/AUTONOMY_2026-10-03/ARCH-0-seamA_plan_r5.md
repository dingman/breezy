# ARCH-0 seam A: persistence core build plan, r5

**Round r5**, dated 2026-10-03. This round only consolidates text. It revises r4 (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r4.md`) and applies the coordinator rulings A5-R1 to A5-R11 (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-r1-merged.md`, section "Seam A round 4"). Those rulings answer the non-blocking findings of two reviews, both of which approved r4:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamA-r4-security.md` (APPROVE, N1–N4);
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamA-r4-architect.md` (APPROVE, N1–N7).

The earlier rulings (A-R1 to A-R6, A3-R1 to A3-R6, A4-R1 to A4-R11) remain binding and remain applied.

r5 makes no design change beyond those rulings and adds no new module or scope. The disposition is in §R5.

**Basis.**
- Plan facts come from FROZEN ARCH Rev 9.2 (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md`, sha256 `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`) and from errata E-1 to E-13 (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`).
- E-14 is requested in §ERRATA-REQUEST. The architect adopted it in r4. r5 adds one clarifying sentence to rule 7, required by A5-R3.

**How code facts were checked.**
- The tree is at `d231497d` (HEAD), and `src/`, `tests/` and `pyproject.toml` are clean.
- Tools: codegraph, `sed`, `grep`, and read-only probes under `/home/jon/breezy/.venv/bin/python`.
- Probe scratch is under `/tmp/claude-1000/a0r3/`, `/tmp/claude-1000/a0r4/` and `/tmp/claude-1000/a0r5/`.
- No repo file was written and no state was changed.

## Verified facts

V1 to V21 come from r3, and V22 to V31 from r4. All were re-checked where they are used. V32 to V36 are new in r5.

**r3 facts, condensed:**
- **V1.** `import breezy.domain.instrument_leg` loads 120 `nautilus_trader*` modules (`src/breezy/domain/__init__.py:16-53`).
- **V2.** With an import-free `persistence/__init__.py`, `breezy.persistence.live_orders_gate` loads 0 Nautilus modules and 15 `pyarrow*` modules. The chain is `family_manifest.py:88` → `mechanism_test_guard.py:14`.
- **V3.** The facade at `src/breezy/persistence/__init__.py:9-53` re-exports 20 `catalog` names and has zero consumers.
- **V4.** On SQLite 3.50.4, REPLACE bypasses `BEFORE DELETE` while `recursive_triggers=0`. `ON CONFLICT DO UPDATE` fires the UPDATE trigger.
- **V5.** The data root is 0700. Repo files are 0664 under umask 0002.
- **V6.** In `src/breezy/runtime/trade_supervisor_core.py:37-44`: STOP_PRIOR is 16:40, LAUNCH 16:50, SELF_CHECK 17:05, and the window ends at 17:00.
- **V7.** `src/breezy/adapters/polymarket_us/exec/client.py` has sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`. It is pinned at `tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:36`.
- **V8.** `live_orders_authorized` is at `live_orders_gate.py:130-189`. The ruling checks are at `:163-182`, and the permit check comes last (`:184-189`).
- **V9.** `load_family_manifest` is at `family_manifest.py:285`. The guard is at `:293-294`, `read_bytes` at `:295`, and the containment helper at `:262-282`.
- **V10.** The exec client never deletes `fill_index/` keys.
- **V11.** The COALESCE genesis trigger refuses a first row whose `venue_seq` is not 1.
- **V12.** A `mode=ro` reader distinguishes `SQLITE_BUSY` from `SQLITE_READONLY_ROLLBACK`.
- **V13.** Exec-client keys:
  - `STATE_KEY_NAMESPACE` is at `:399` and `FILL_INDEX_KEY_PREFIX` at `:412`.
  - The key write is at `:4645`. The reads are at `:2198`, `:2302`, `:3457`, `:4693` and `:4827`, plus `trial_day_latch.py:1385`.
  - `_read_fill_index` (`:4712-4729`) returns `[]` for an absent key and `None` for an unreadable one.
- **V14.** In `tests/unit/test_runtime_import_isolation.py`, the entry-module helpers are at `:158`, `:165` and `:192`, and the constants at `:55-60`.
- **V15.** The Nautilus arrow registry is at `serializer.py:75-78`.
- **V16.** A single "core list ↛ pyarrow" contract cannot be satisfied. That is why the contract is split into (b) and (c).
- **V17.** `tests/unit/test_mypy_ratchet.py:352-364` sets a mypy ceiling per package and fails when the code falls below a ceiling.
- **V18.** `assert_prereg_directory_eligible` (`mechanism_test_guard.py:27-45`) returns silently when the directory is absent (`:35-36`).
- **V19.** The intersection of the family patterns (`settings.py:114`, `trial_day_latch.py:301`) is `[a-z0-9_]{1,64}`.
- **V20.** `pm_us_crh_v4` and `pm_us_crh_cont` share density sha `247f6363…a65`. This is the E-14 collision.
- **V21.** ARCH C5 line anchors:
  - `ResolvedFamily` fields at `:557-558`;
  - Y6 at `:560-563`;
  - the shadow HWM at `:576-579`;
  - the root exemption at `:605-608`;
  - the HWM mid-chain check at `:618-624`;
  - the reset CLI at `:626-634`.

**r4 facts, condensed:**
- **V22.** The probe `/tmp/claude-1000/a0r4/gen.py` checked contracts (b) and (c) against the File-plan import edges:
  - the r4 layout prints "2 kept, 0 broken";
  - the r3 layout breaks (c);
  - a planted `TYPE_CHECKING` import breaks (c). `pyproject.toml` has no `exclude_type_checking_imports`.
- **V23.** Import-linter treats a package in `source_modules` as including all its descendants. Contracts (b) and (c) therefore list module names only.
- **V24.** ARCH `:431-434` lists the counters. AUT-5 r7 `:139` adds the venue-level `drill_close_restores` (E-5). No column or kind records a holdout open (ARCH `:306-307`; AUT-5 r7 `:138`).
- **V25.** In `exec/client.py`: `_RECORD_SIGNS` is at `:668-671` and `LONG_ONLY_SIDE = "BUY"` at `:663`. The uses are at `:3470-3472`, `:4090-4093` and `:4517-4528`. `DurableFillRecord` is at `:923` and `record_fill` at `:4593`.
- **V26.** `LiveOrdersReason` is a `typing.Literal` with 7 members (`live_orders_gate.py:62-70`). `FamilyManifest` is imported at `:53`.
- **V27.** The exec intent flock is `<exec store>.intent.lock` (`trade_supervisor.py:306-307`; `submit_intent.py:558`). Timing:
  - E-8 releases it by 16:48:00;
  - AUT-5 r7 `:937` step 3 ends by 16:44:50, and its reload gap is ≤ 16:44:55;
  - the bootstrap ends by 16:41:15.
- **V28.** ARCH `:263-264` says a ROLLBACK restores the BOOTSTRAP sha "even if the repo file changes". `terminal_climate_day` is an optional key. There are 7 committed `deploy/families/*.json`.
- **V29.** `REPO_ROOT = Path(__file__).resolve().parents[2]` (`test_runtime_import_isolation.py:55`) gives the same root from `tests/support/entry_points.py`.
- **V30.** Not probed: `unshare -r` is refused in this sandbox. As a normal uid, `O_CREAT` in a 0500 directory gives errno 13. AC 7 therefore refuses by mode bit.
- **V31.** `nominations`, `infeasible_nominations` and `alpha_spent` can be derived from the C5 nomination columns. AUT-4 r11 `:1458` asserts `alpha_spent == Σ alpha_k`.

**New in r5:**
- **V32 (A5-R6; export naming confirmed).** AUT-5 r7 names the files in `evidence/registry/` as follows:
  - `:173`: the daily export is `registry_<venue>_<YYYY-MM-DD>.jsonl`, and the HWM_RESET export is `registry_<venue>_<YYYY-MM-DD>_hwm<export_seq>.jsonl`. `:485` repeats this (`…_hwm<export_seq>.jsonl`).
  - `:189`, writer row: `evidence/registry/*.jsonl` and `evidence/registry/hwm_reset_<ts>.json`.
  - `:487`, step 7: writes `evidence/registry/hwm_reset_<ts>.json`.

  The ruling's regex `\Aregistry_<venue>_\d{4}-\d{2}-\d{2}(_hwm\d+)?\.jsonl\Z` matches this naming exactly, so r5 uses it unchanged. AUT-5 r7 does not pin the `<ts>` format, so the known-and-ignored reset pattern is `\Ahwm_reset_.+\.json\Z`.

  **Side effect, flagged for coordinator:** AC 7's `write_once` creates `.tmp.<16 hex>` in the target directory for a moment, and a crash can leave one behind until the engine sweeps. Under A5-R6 that name falls under "any other name" and gives `export_unreadable`. This fails closed, but it can block resolution, so it is recorded as R25. r5 does not change the design.
- **V33 (A5-R3; base ref).**
  - `git rev-parse --verify origin/feat/data-capture-and-risk` gives `d231497d`.
  - `git rev-parse --is-shallow-repository` gives `false`.
  - `git merge-base HEAD origin/feat/data-capture-and-risk` gives `d231497d`.
  - Existing tests already call `git` through a subprocess: `tests/unit/test_operator_control_assignment_scan.py:354` and `tests/unit/test_wp11b_active_family_registry.py:267`.
- **V34 (A5-R9; ban collateral).**
  - AUT-3 r6 `:137` plans `dataclasses.replace(row, split="v5_fit_slice")`. AUT-3 r6 `:21` defines `AR/` as `src/breezy/analysis/autonomy_refit/`. That is a sibling package, not under `src/breezy/analysis/autonomy/`, so the AC 15(ii) scope as written does **not** cover it. r5 records the (b) item the ruling asks for, but states this discrepancy rather than widening the ban (that would be a design change). Flagged for coordinator.
  - AUT-4 r11 builds in `src/breezy/analysis/autonomy/` (for example `:507-512`), and AUT-6 r15 in `src/breezy/persistence/autonomy/` (`detector_catalog`). Both are in scope.
  - A grep finds no `dataclasses.replace` or `copy.` call text in AUT-4 r11 or AUT-6 r15.
- **V35 (A5-R1/A5-R2; probe `/tmp/claude-1000/a0r5/flk.py`).** With LOCK_EX held on one fd, a second `flock(LOCK_EX|LOCK_NB)` on a fresh fd of the same file in the same process gives EWOULDBLOCK. A helper that took the intent flock itself would therefore conflict with a caller that already holds it. That is why `write_monotone` takes a held-lock argument (binding note 6f).
- **V36 (A5-R5; placement audit).** Against AUT-5 r7 `:844-845` and the module landing seams, five more tests sat before their code landed:
  - `test_enabled_widening_kinds_subset_of_widening_kinds` (3a) reads `transitions.WIDENING_KINDS`, which lands in 6b;
  - `test_autonomy_exec_keys_disjoint_from_halt_prefixes` (3c) checks the `autonomy/` exec keys (AUT-5 r1 `:157`), and `REGISTRY_HWM_KEY_PREFIX` lands in 7e;
  - `test_autonomy_package_import_graph_is_acyclic` (6a) pins the `transitions ← stage_policy` edge, which lands in 6c;
  - `test_drill_demote_and_halt_counters_capped` (7b) exercises the drill-counter cap in `validate`, which lands in 7c;
  - r4 put the whole "AUT-5 r7 WP1 fold list" in 7a, but it includes tally, RESUME and validate rules. It is now split by name across 7a–7d.

**Residual risk, stated once.** Pins, chain, HWM, exports and the DB are all one same-uid trust domain (ARCH C5 residual; R14). There are only four external anchors:
1. the committed allowlists;
2. the committed `deploy/families/<id>.json` bytes, frozen after bootstrap (A3-R1; E-14 rule 7);
3. `live_orders_gate`;
4. the reviewed code in `pins.py` and `transitions._ADMISSION_IMPLEMENTED`.

## Acceptance Criteria (numbered, testable)

1. **Package and contracts (V16, V22, V23).** `/home/jon/breezy/src/breezy/persistence/autonomy/` holds exactly the File-plan modules. `cd /home/jon/breezy && .venv/bin/lint-imports` prints "N kept, 0 broken". There are three new contracts, all with `allow_indirect_imports = false`:
   - (a) `breezy.persistence.autonomy ↛ breezy.adapters`. Here the source is the package, as intended.
   - (b) The 27 core modules, named one by one and never as the package, ↛ `nautilus_trader` and `breezy.domain`: `canonical, wire, single_read, paths, pins, veto, plugin, closure_manifest, closure, schemas, stage_policy, verdict, lineage, label_schema, demand, drill_marker, rollback_journal, fold, transitions, chain, family_bytes, registry_store, hwm, replay, net_position, entry_guard, resolver`.
   - (c) (b) minus `PYARROW_REACHING = {label_schema, family_bytes, registry_store, replay, resolver}` ↛ `pyarrow`.

   The lists grow as modules land. `include_external_packages = true` is already set (`pyproject.toml:72`). `test_autonomy_init_has_no_import_nodes` covers the package `__init__`.
2. **Module classification.**
   - `test_every_autonomy_module_is_classified` puts every module in exactly one of two sets: (b)'s `source_modules`, or `NAUTILUS_PERMITTED` (which is empty at ARCH-0). It also asserts that (b) − (c) == `PYARROW_REACHING` ∩ existing modules. It has a planted control.
   - `test_contract_c_refuses_planted_pyarrow_reach[canonical|schemas]` (`heavy`): the unplanted copy prints "1 kept", and the copy with a planted `TYPE_CHECKING` import prints "BROKEN".
3. **Runtime import weight.** `test_autonomy_core_modules_nautilus_free_at_runtime` checks each module in a fresh subprocess. It requires 0 `nautilus_trader*` and 0 `breezy.domain*` modules, and allows `pyarrow*` only for `PYARROW_REACHING`.
4. **Import-free `persistence/__init__.py`.** The 20-name facade is deleted (precedent: NOTIFIER-IMPORT-ISOLATION).
   - Permanent tests:
     - `test_persistence_init_has_no_import_nodes`;
     - `test_persistence_has_no_facade_consumers` (AST over `src/`, `tests/` and `scripts/`, including `mock.patch` strings);
     - `test_persistence_entry_module_imports_cleanly[<entry>]` (total ≤ 60 s, measured in 1a).
   - One-time WP-1a evidence:
     - (i) per-entry grimp `register_arrow` reachability is identical with and without a simulated `persistence → catalog` edge;
     - (ii) the per-entry `serializer._SCHEMAS` keys are equal (V15).

     Any entry that differs is listed with a reviewed reason, or WP-1a stops.
5. **Explicit serialisation.** Every wire record has `to_wire()` and `from_wire()`. This covers the C2 schema, `lineage/v1`, `root/v1`, `refit_run/v1`, `verdict/v1`, the C5 row, the export trailer, `demand/v1`, `drill_marker/v1`, `journal/v1` and `Hwm`.
   - `wire.parse_json_exact` refuses: duplicate keys; NaN and Infinity; any float token; missing or unknown keys; wrong types; bool used as int; and a `schema` outside `ACCEPTED_SCHEMAS`.
   - Refusals raise `WireRefused(reason: WireRefusalReason)`.
   - AST bans `dataclasses.asdict` and `astuple`.
6. **Canonical bytes.** `canonical_json` is `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False)` encoded as UTF-8.
   - `CanonicalTypeError` is raised for a non-`str` key, a `float`, a lone surrogate, or any type outside `None|bool|int|str|list|tuple|dict|Decimal`.
   - `decimal_str` refuses NaN, Inf, more than 38 digits, and `|adjusted()| > 18`. Zero is written `"0"`; anything else is `format(d.normalize(), "f")`.
   - Goldens: `-0`→`"0"`, `0E-10`→`"0"`, `1E+2`→`"100"`, `1.50`→`"1.5"`, plus three record goldens.
7. **Single read and write, TOCTOU-free.**
   - `open_root(root)` opens with `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`.
   - `walk_dirs(rootfd, rel, *, create, mode=0o700)` runs one `openat` per component with `O_DIRECTORY|O_NOFOLLOW`. It refuses `""`, `.`, `..`, NUL and `/`. Each component must pass `fstat` S_ISDIR with `st_uid == geteuid()`.
   - `read_once_at(dirfd, name, *, max_bytes, policy)` opens with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC` and requires S_ISREG and the owner uid. `STRICT` refuses group-write and other-write bits. `REPO` drops the mode check (V5). It reads `max_bytes+1` to detect oversize.
   - `write_once(path, data, *, root, mode)`:
     - (1) pre-reads the destination: equal bytes → `EXISTS_EQUAL` with no temp file; different bytes or a symlink → `EXISTS_DIFFERENT`; ENOENT → step 2;
     - (2) `fstat(parent dirfd)`, and `st_mode & S_IWUSR == 0` → `SingleReadRefused(DIR_NOT_WRITABLE)` before any temp file (a mode-bit check; V30);
     - (3) `.tmp.<token_hex(8)>` with `O_CREAT|O_EXCL|O_NOFOLLOW`, `fchmod`, write, `fsync`, then `os.link(src_dir_fd=, dst_dir_fd=, follow_symlinks=False)`;
     - EEXIST re-compares. EPERM, EXDEV, EOPNOTSUPP and EMLINK give `LINK_UNSUPPORTED`. There is no rename fallback;
     - the temp file is always unlinked and the directory fd `fsync`ed.
   - `replace_atomic` follows the same pattern with `os.replace`.
   - AST: these are the only `os.link`, `os.replace` and write-mode `open` sites. The single named exemption is `live_orders_gate._verify_ruling_file` (a move-only extraction).
8. **Store DDL.** `transitions` has exactly the AUT-5 r7 §3.2 columns (`:138`).
   - `venue` and `venue_seq` are `NOT NULL`, with `UNIQUE(venue, venue_seq)` and `UNIQUE(transition_id)`.
   - `BEFORE UPDATE` and `BEFORE DELETE` triggers raise `RAISE(ABORT,'append-only')`.
   - `BEFORE INSERT` refuses an existing `NEW.seq`, a duplicate `(venue, venue_seq)`, and a COALESCE genesis or gap (V11).
   - `meta(schema='registry/v1')`, `user_version=1`, `application_id=0x42524759`. The directory is 0700 and the file 0600.
   - No derived caches are created (AUT-5 WP4).
9. **Writer connection.** `isolation_level=None` and `BEGIN IMMEDIATE`. Pragmas: `journal_mode=DELETE`, `synchronous=FULL`, `recursive_triggers=ON`, `trusted_schema=OFF`, each read back by a test. AST bans `OR REPLACE`, `OR IGNORE`, `REPLACE INTO` and `executescript`.
10. **Append path.** `RegistryStore.append(rows, *, expected_prior_seq, mode: WriterMode, now_ns: int)` delegates to `_append(..., stage=stage_policy.STAGE, _fixture_stage=False)`. Inside one `BEGIN IMMEDIATE`, in order:
    1. `stage is stage_policy.STAGE` unless `_fixture_stage=True`; otherwise `StageNotCanonical`.
    2. Every id already present → logged no-op. Some present → `PartialReplay`.
    3. `mode` must be a concrete `WriterMode`.
    4. `KIND_MASK[mode]`.
    5. `adm = transitions.rows_admissible(rows, stage=stage)`. `widening_kind_not_enabled` → `WideningNotEnabled`; `admission_pending` → `AdmissionPending`. The whole batch is refused. The store keeps no second copy of the predicate.
    6. SHADOW→CHALLENGER PROMOTE → `NominationRequiresPolicy`. HWM_RESET → `RuleSetPending`.
    7. `|row.ts_ns − now_ns| ≤ ROW_TS_MAX_SKEW_S` (300), and `ts_ns` is monotone over the head.
    8. CAS: `max(venue_seq) == expected_prior_seq`.
    9. `transitions.validate(fold(prior), rows, mode=mode, now_ns=now_ns, stage=stage, manifests=family_bytes.read_manifest_facts)`.
    10. Insert, then COMMIT.

    Any failure rolls back completely. Every exception carries `.reason: RefusalReason`.
11. **Chain.**
    - The genesis is `sha256(b"registry/v1|"+venue)`.
    - `canonical_row` hashes every column except `seq`, `prev_transition_hash` and `transition_hash`.
    - `transition_id` hashes the Y9 tuple without `expected_prior_seq`.
    - `verify_venue_chain(rows, venue) -> VerifiedVenueChain` requires contiguous `venue_seq` from 1 to n, a single venue, monotone `ts_ns`, and unbroken hashes.
12. **Reader (V12).** `RegistryReader(paths, *, busy_timeout_ms).read_venue_rows(venue, after_seq=0)`:
    - opens `file:<percent-quoted>?mode=ro` with `query_only=ON` and `trusted_schema=OFF`, one connection per call;
    - inside one `BEGIN`, checks meta, `user_version`, `application_id`, and that `sqlite_master` equals the DDL constants, then runs an explicit column select;
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
    - `transitions.validate` is pure and implements every fold-decidable C5 rule:
      - V12 DRILL-row refusal while a non-DRILL cause stands;
      - DRILL_PROMOTE needs the champion sha; no drill over a HALTED incumbent; drill counters ≤ 1 per `DRILL_BUDGET_PER_VENUE_30D`;
      - Z3 and `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY`;
      - RESUME: every cause cleared, cooldown, the RECOVERABLE_MODEL and RECOVERABLE_INFRA ceilings, and ROLLBACK_FAILED only under `trigger_cause_class`;
      - the five E-5 `drill_close_restore` conditions, at most 1 per venue per day;
      - d0 and `trial_id_prefix` at the first →CHAMPION row (ROLLBACK, RESUME and ROOT_ADMIT are exempt);
      - ROOT_ADMIT and BOOTSTRAP only when the venue has no sender, with `lineage_root_family_id == family_id`;
      - the mint rate; BOOTSTRAP genesis and seed (E-6); ATTEST cadence; SWAP_CANCEL voids ⊆ pending;
      - a single sender at `now` and at the next LAUNCH;
      - HWM_RESET `carried_counters` ≥ export counters (B9).
    - A family unknown to the prior fold must have `from_state = ∅` and kind ∈ {BOOTSTRAP, ROOT_ADMIT, MINT}, else `family_not_introduced`. A BOOTSTRAP or ROOT_ADMIT row with `lineage_root_family_id != family_id` gives `root_lineage_mismatch`.
    - `_ADMISSION_IMPLEMENTED: Final[frozenset[Kind]] = frozenset()` lives in `transitions.py`.
    - `rows_admissible(rows, *, stage: StageView) -> AdmissibilityResult(admitted, reason)` walks the rows in chain order. It stops at the first widening row whose kind is outside `stage.enabled_widening_kinds` (`widening_kind_not_enabled`) or outside `stage.admission_implemented` (`admission_pending`). `rows[:admitted]` is admissible, and `reason is None` means `admitted == len(rows)`.
    - `rows_admissible` is the only place either set is compared against rows (`test_admissibility_predicate_has_one_home`).
    - Its consumers are the store (AC 10.5), the resolver (AC 17.5) and the watch actor (binding note 5). `test_admissibility_predicate_shared[store|resolver]` is real; `[watch_actor]` is carried to AUT-5a.
14. **Fold.** `fold(rows, venue, now_ns) -> FoldResult | FoldInvalid` is pure.
    - It computes:
      - states, pending pairs, ACTIVATE in [16:40Z, LAUNCH), and lapse at LAUNCH;
      - SWAP_CANCEL voiding, including the [LAUNCH, 17:00Z) post-launch void;
      - `demoted_for_cause`, `rollback_eligible`, `target_ineligible` and `terminal_frozen`; the venue INTEGRITY freeze; `drill_episode` intervals;
      - tallies charged on effect, with HWM_RESET `carried_counters` applied as floors;
      - at most one {CHAMPION, HALTED} family per venue.
    - `FamilyView.origin` and `lineage_root_family_id` come from the introducing row. BOOTSTRAP or ROOT_ADMIT with `lineage_root_family_id == family_id` gives `root`; MINT gives `child`.
    - `FoldInvalid(reason)` is returned for `family_introduced_by_other_kind` and `root_lineage_mismatch`. The resolver maps it to `replay_invalid` and the watch actor to `registry_unreadable`.
    - **`LineageTallies` is frozen (V24, V31).** These fields are fold-derived, with carried counters as floors:
      - `nominations` = max `k_life` over feasible SHADOW→CHALLENGER PROMOTE rows. Binding note 1b records an open question against ARCH's "max `k_life`".
      - `infeasible_nominations`;
      - `alpha_spent: Decimal` = Σ`alpha_k`;
      - `mints` and `promotions` (tuples of `ts_ns`);
      - `rollbacks`, `terminal_frozen`;
      - `drill_admits`, `drill_promotes`, `drill_demotes`, `drill_resumes`, `drill_halts`, `drill_rollbacks`.
    - `VenueTallies` holds `infra_resumes` and `drill_close_restores`. `holdout_opens` is excluded (no row source) and comes from the AUT-5 WP4 cache.
    - `test_lineage_tallies_fields_equal_arch_counters_minus_non_derivable` pins the field set.
    - AST bans the wall clock and `time.monotonic` in the core list.
15. **Stage policy: frozen, and not constructible in `src/`.**
    - `StagePolicy` (a frozen slotted dataclass) and the `StageView` Protocol live in `schemas.py`. `stage_policy.py` builds `STAGE: Final[StagePolicy]` once through `_build()`. The import order is `schemas ← transitions ← stage_policy` (`test_autonomy_package_import_graph_is_acyclic`, seam 6c).
    - `test_autonomy_policy_not_mutable_from_src` has a planted positive control per form. It refuses:
      - (i) across all of `src/`, any write that targets `pins`, `stage_policy`, `transitions`, `live_orders_gate` or `family_manifest`: assignment, `setattr`, `delattr`, `__dict__`, `object.__setattr__`, `importlib.reload`, `mock.patch`, `monkeypatch`, and `globals()`/`vars()` writes; rebinding an imported name; and any reference to `_append`, `_resolve`, `_replay_full`, `_lineage_policy_authorized`, `_verify_ruling_file` or `stage_policy._build` outside its defining module;
      - (ii) in every package under `src/breezy/` with a dotted-path component starting with `autonomy` (derived by walking `src/breezy/`; A6-R2), outside `stage_policy.py`: **any** call to `dataclasses.replace`, `copy.copy` or `copy.deepcopy`; `<expr>.__class__(...)`; `type(<expr>)(...)`; `object.__new__(...)`; and `StagePolicy(...)` reached through any import alias, resolved per module.
    - **Exemptions (A5-R9).** The ban stays blanket, as written. An AST check cannot see argument types, so narrowing it would reopen security r3 F3. An exemption is a reviewed literal row `(module, lineno-free call description, reason)` in the test's exemption set, added in the consumer's own commit. The set is empty at ARCH-0. Consumers that need `dataclasses.replace` or `copy.*` on their own records use an exemption row (§ERRATA (b) items 42–44).
    - Defence in depth: `_append` (AC 10.1) and `_resolve` (AC 17.0) require `stage is stage_policy.STAGE` unless a fixture is passed. Tests: `test_append_refuses_non_canonical_stage` and `test_resolve_refuses_non_canonical_stage`.
16. **HWM is tri-state, mid-chain checked, absence-refusing, strictly indexed and monotone on write.**
    - `hwm.py` provides `Hwm(venue, venue_seq, chain_head, export_seq)`, `HwmReading = HwmAbsent | HwmPresent | HwmUnreadable`, `REGISTRY_HWM_KEY_PREFIX = "autonomy/registry_hwm/"` and `hwm_key(venue)`.
    - **Domain.** `venue` matches the venue pattern; `venue_seq: int ≥ 1`; `export_seq: int ≥ 0`; `chain_head` matches `\A[0-9a-f]{64}\Z`; bool is refused as int.
    - `hwm_reading_from_bytes(raw: bytes | None) -> HwmReading` is the only decoder. `None` gives `HwmAbsent` and any error gives `HwmUnreadable`. AST bans `HwmAbsent(` outside `hwm.py`.
    - `hwm_check(chain, reading, *, newest_export_seq) -> RefusalReason | None` checks, in order:
      1. an unknown reading type or `HwmUnreadable` → `hwm_unreadable`;
      2. `HwmAbsent` on any non-empty chain → `hwm_absent`;
      3. a foreign venue or `venue_seq < 1` → `hwm_unreadable`;
      4. `venue_seq > head` → `hwm_regressed`;
      5. `chain.rows[venue_seq − 1].transition_hash != chain_head` → `hwm_regressed`;
      6. `export_seq > newest_export_seq` → `hwm_regressed`.
    - `newest_export_seq` is 0 when there is no export file.
    - `next_hwm(chain, *, export_seq) -> Hwm` is pure and returns `Hwm(venue, head, rows[-1].transition_hash, export_seq)`.
    - **New (A5-R2, security N2): the monotone write decision.** `HwmWriteDecision` is a closed StrEnum {`WRITE`, `SKIP`, `REFUSE`}. `write_monotone_decision(current: HwmReading, new: Hwm) -> HwmWriteDecision` is pure. It is the decision part of AUT-5a's sole writer API `hwm.write_monotone` (binding note 6f), and it decides in order:
      1. `HwmAbsent` → `WRITE`;
      2. `HwmUnreadable` or an unknown reading type → `REFUSE`;
      3. a foreign venue → `REFUSE`;
      4. `new.venue_seq == cur.venue_seq` with `new.chain_head != cur.chain_head` → `REFUSE`;
      5. `new.venue_seq ≥ cur.venue_seq` and `new.export_seq ≥ cur.export_seq`: identical values → `SKIP`, otherwise `WRITE`;
      6. `new.venue_seq ≤ cur.venue_seq` and `new.export_seq ≤ cur.export_seq` → `SKIP` (a stale writer; the stored HWM is already at least as advanced);
      7. otherwise (one axis higher and the other lower) → `REFUSE`.

      A writer never lowers either sequence.
    - Tests:
      - `test_hwm_seq_zero_and_negative_refused`;
      - `test_hwm_at_head_compares_last_row`;
      - `test_hwm_check_unknown_reading_type_is_unreadable`;
      - **`test_hwm_write_never_lowers`** (seam 7e; parametrised over rules 1–7; mutation: drop the `export_seq` comparison).
17. **Sending resolver.** The public entry is `resolve_sending_family(*, venue, paths, repo_root, now_ns, hwm: HwmReading) -> ResolvedFamily | ResolverRefusal`.

    Step 1 (public sending entry only; A5-R7): if `paths.is_shadow` is True, refuse with `paths_role_mismatch`. This reads the attribute and never uses `isinstance`.

    The entry then delegates to `_resolve(..., stage=STAGE, lineage_gate, hwm_mode=ENFORCE)`. `_resolve` runs steps 0 and 2–12, in order (step 1 is not part of `_resolve`):
    0. `stage is STAGE` unless a fixture, else `stage_not_canonical`. `(hwm_mode is HwmMode.SKIP_SHADOW) == paths.is_shadow`, else `paths_role_mismatch`. This is the only role check inside `_resolve`.
    2. Verify the chain from genesis. `now_ns` is an int > 0 and ≥ head `ts_ns` − skew.
    3. **Exports, before the HWM (A4-R4; A5-R6):**
       - open and list `evidence/registry/`. Any open or listing error, including a missing directory, gives `export_unreadable`;
       - `newest_export` classifies every name, with `re.ASCII`, `\A…\Z` and the venue `re.escape`d:
         - **this venue's export:** `registry_<venue>_\d{4}-\d{2}-\d{2}(_hwm\d+)?\.jsonl`. This is a candidate;
         - **known and ignored:** `hwm_reset_.+\.json` (AUT-5 r7 `:189`, `:487`; V32), the `write_once` temp name `\.tmp\.[0-9a-f]{16}` (A6-R1), and another venue's export `registry_(?P<v>[a-z0-9_]{1,32})_\d{4}-\d{2}-\d{2}(_hwm\d+)?\.jsonl` with `v != venue`;
         - **any other name** (an unmatched `.tmp.` name included) → `export_unreadable`, which fails closed;
       - no candidate: `newest_export_seq = 0`. `export_check = not_yet_due` holds only if `now_ns − genesis_ts_ns < EXPORT_FIRST_DUE_H`; otherwise `export_unreadable`;
       - otherwise verify the export prefix. `newest_export_seq` is the highest `export_seq` among the candidates, and `export_check = verified`.
    4. `hwm_check(chain, hwm, newest_export_seq=newest_export_seq)`.
    5. `transitions.rows_admissible(chain.rows, stage=stage)`. Any reason refuses.
    6. `replay_full`. Its fold, including `FoldInvalid`, maps to `replay_invalid`.
    7. More than one CHAMPION/HALTED family → `engine_inconsistency`.
    8. Root or child is decided from `FamilyView.origin`.
    9. **Root:**
       - read `deploy/families/<family_id>.json` under `ReadPolicy.REPO`; its sha must equal `row.manifest_sha256`, else `manifest_sha_mismatch`;
       - check the E-14 root record;
       - call `live_orders_authorized(..., permit_present=False)` and accept only `permit_absent`. `no_ruling` gives `no_live_orders_ruling`. A raised refusal or `ok` gives `ruling_refused` with a `LiveOrdersRefusal` detail.
    10. **Child:**
        - read `registry/families/<id>.json` (STRICT) with a sha check;
        - `CHILD_FAMILY_ID_RE` root == `view.lineage_root_family_id`, else `child_root_mismatch`;
        - §4.2 equality with the committed root, over `fields(FamilyManifest) − ALLOWLIST − {"manifest_sha256"}`;
        - `lineage_policy_authorized(...)`;
        - d0 and the prefix.
    11. **Common to both:** the manifest's `venue`, `composition_kind` and `family_id` equal the row's; `LIVE_GATE_ROUTED_KINDS`; the engine pins; the artefact (STRICT) sha == `row.artefact_sha256`.
    12. Return `ResolvedFamily` with `verified_export_seq = newest_export_seq` and `hwm = next_hwm(chain, export_seq=newest_export_seq)`.
18. **Shadow resolver.** The public entry is `resolve_shadow_family(*, venue, paths, repo_root, now_ns) -> ShadowResolution | ResolverRefusal`.
    - The public entry refuses `paths_role_mismatch` unless `paths.is_shadow`. It then runs `_resolve(..., hwm_mode=SKIP_SHADOW)`. `ShadowPaths` is not a subclass of `AutonomyPaths`.
    - **The shadow step set is explicit (A5-R7):**
      - steps 0, 2, 3, 5, 6, 7 and 8 run;
      - step 4 is skipped;
      - steps 9–12 do not run, because `ShadowResolution` carries no bytes: no manifest, artefact, ruling or HWM.

      Step 3 applies unchanged, so `not_yet_due` holds only within 26 h of shadow genesis (`test_shadow_day2_without_export_refuses`). Every bootstrap creates `evidence/registry/` (binding note 9; A5-R10).
    - `ShadowResolution(family_id, state, registry_seq, chain_head)` is a separate frozen dataclass in `resolver.py`. It shares no base with `ResolvedFamily`.
    - `test_shadow_resolution_ignores_hwm_and_cannot_send` checks five things:
      - (i) an ATTEST-bearing chain with no HWM resolves;
      - (ii) the sending resolver on the same chain gives `hwm_absent`;
      - (iii) `ShadowResolution` has none of the `ResolvedFamily`-only fields;
      - (iv) no `resolve_shadow_family` call exists outside `SHADOW_CALL_SITES` (empty);
      - **(v) a spy records exactly steps {0, 2, 3, 5, 6, 7, 8}.**
    - `test_resolve_private_rejects_skip_hwm_on_production_paths` exercises AC 17.0.
19. **`ResolvedFamily` carries the ARCH C5 pickup fields.** It is defined in `resolver.py`:
    - `family_id`, `state: Literal[CHAMPION, HALTED]`, `entries_allowed: bool`, `origin`;
    - `registry_seq`, `chain_head`, `authorising_seq`;
    - `family_bytes: FamilyBytes` (from `family_bytes.py`);
    - `export_check: Literal["verified","not_yet_due"]`;
    - `verified_export_seq: int`;
    - `hwm: Hwm`.

    It has no `enabled` or permit field.
    - `test_resolved_family_carries_arch_c5_pickup_fields` (ARCH `:558`; AUT-5 r7 `:410`, `:441`, `:971`; AUT-1 r12 `:329`).
    - `test_resolved_family_hwm_equals_next_hwm`.
    - `ResolverRefusal(reason, detail: UnreadableReason | LiveOrdersRefusal | None)` lives in `resolver.py`.
20. **Lineage-policy gate (WP-8a).** `live_orders_gate.py` gains:
    - `_LINEAGE_POLICY_ALLOWLIST = frozenset()`;
    - `CHILD_FAMILY_ID_RE = re.compile(r"\A(?P<root>[a-z0-9_]{1,58})_r[0-9]{4}\Z", re.ASCII)`;
    - `_verify_ruling_file`, a move-only extraction of `:163-182`;
    - `lineage_policy_authorized(child, root_family_id, repo_root) -> LineagePolicyDecision`, which uses existing `LiveOrdersReason` members only.

    `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py` and `test_live_orders_ruling_deploy_copy_matches_evidence.py` pass **unmodified**. The ruling refusal sites reach 100% branch coverage before and after the extraction.
21. **`parse_family_manifest` split, proven byte-equivalent.** `parse_family_manifest(raw, *, path, allow_draft=False)` is `family_manifest.py:296-460` moved verbatim. `load_family_manifest` keeps `:293-295`.
    - **WP-1b** runs on unsplit code:
      - the golden corpus is at `/home/jon/breezy/tests/fixtures/family_manifest_golden/`;
      - `expected.json` records the result for each input;
      - `symlink_escape` is built in `tmp_path`;
      - **gate:** `coverage run --branch` gives 100% of `:262-282` and `:285-460`.
    - **WP-1c** splits the code, and the same test passes unmodified.
    - **Callers:** `family_bytes` uses `walk_dirs` (a missing directory gives `manifest_unreadable`) and always calls `assert_prereg_directory_eligible(dir)`. `test_autonomy_never_passes_allow_draft_true` enforces the draft ban.
22. **Entry guard.**
    - `net_position.LegFill(leg, side: Literal["BUY","SELL"], qty: Decimal, ts_event_ns: int)` is frozen and netting-only (`test_leg_fill_fields_frozen`). AUT-2 owns `CostedFill`.
    - `net_signed_qty`: YES BUY +q, YES SELL −q, NO BUY −q, NO SELL +q; anything else gives `UnknownSide`.
    - `entry_guard.leg_instrument_ids(base_slug, *, venue_suffix)`.
    - `FillReader`: `open_intent_blocks()`, `fill_index(...)`, `fill_record(...) -> FillRow(order_side: Literal["BUY","SELL"], cumulative_qty, ts_event_ns)`.
    - `rung_has_net_position(...) -> GuardResult{HELD, FLAT, UNREADABLE}`:
      - the body is wrapped in `try/except → UNREADABLE`;
      - `open_intent_blocks()` is called first (venue-global scope, stated in the docstring);
      - a bad slug or an empty index gives UNREADABLE;
      - `FillIndexAbsent` reads as no fills;
      - `net != 0` gives HELD.
    - `guard_veto_reason` maps HELD and UNREADABLE to `rung_net_position_held`.
    - `test_fill_index_key_matches_exec_client_writer` (V13) and `test_fill_row_side_vocabulary_matches_exec_record_signs` (V25) read the pinned client by AST only.
    - `net_position.py` and `entry_guard.py` import no `breezy.domain`. `test_leg_suffix_equals_instrument_leg`.
23. **Veto.** `VetoReason` has exactly the 15 ARCH C5 members (`:642-662`):
    - registry: `registry_not_champion`, `registry_halted`, `registry_unreadable`, `registry_regressed`, `registry_restrictive_pending`;
    - dead engine: `registry_attest_expired`, `registry_engine_heartbeat_stale`, `registry_chain_stale`;
    - transient: `feed_stale`, `recorder_stale`, `permit_lapsed`, `capture_gap`, `capture_untagged`, `alerts_undeliverable`;
    - position: `rung_net_position_held`.

    There is no `EntryVeto` alias. `compose_entry_vetoes` returns the first veto, and an exception gives `registry_unreadable`.
24. **Records.**
    - **C4 verdict:**
      - `verdict_id = sha256(canonical body − {verdict_id, produced_at_ns})`;
      - path `derived/verdicts/<family>/<UTC date of valid_until_ns>/<id>.json`, 0600, write-once;
      - the same id with a body differing only in `produced_at_ns` is a no-op; any other difference gives `VerdictIdCollision`;
      - validity above `MAX_VERDICT_VALIDITY_H` is refused.
    - **Demand:**
      - the writer: exact-set `demand/v1`, ≤ `DEMAND_FILE_MAX_BYTES`, gated by `DEMAND_WRITER_PRODUCER_IDS`, one file per (family, reason), idempotent on `verdict_id`, producer cap `DEMAND_FILES_MAX − DEMAND_INTEGRITY_RESERVED`;
      - the reader: a bad file, or too many files, gives `venue_veto=True`;
      - there is no archive API.
    - **Journal:**
      - `append_journal(paths, kind, venue, record, *, ts_ns) -> JournalHead` writes a write-once (0444) `journal/v1` envelope linked by `prev_sha256`;
      - kinds are bare names, and `JOURNAL_KINDS = frozenset()`;
      - `read_journal_chain` returns the entries or `JournalUnverified`.
    - **C3:** `Lineage`, `RootRecord`, `RefitRun`, `model_class_of`.
    - **Drill marker:** AUT-7 r5's 12-key `drill_marker/v1`. ENOENT on the marker gives `MarkerAbsent`; ENOENT on the directory gives `MarkerError`.
    - **C2:** `LABEL_V1_ARROW_SCHEMA`, column for column.
    - Every path component is validated.
25. **Pins.** `pins.py` holds literals only and imports nothing:
    - every ARCH §4.5 ceiling as amended by E-11, with no `SELF_HEAL_*`;
    - `ENGINE_SOURCE_SHA256 = frozenset()`, `PRODUCER_SOURCE_SHA256 = MappingProxyType({})`, `REVOKED_SOURCE_SHA256 = frozenset()`;
    - `ENABLED_WIDENING_KINDS = frozenset()`, `POLICY_RULING_PIN = ()`, `ROOT_ADMIT_ENABLED_CEILING = False`;
    - `LIVE_GATE_ROUTED_KINDS = frozenset({"forecast_quantile_ladder"})`;
    - `BOOTSTRAP_SEED`, `DEMAND_WRITER_PRODUCER_IDS = ("aut6.intraday",)`, `DEMAND_REASONS`, `CAUSE_CODES`, `HALT_REASON_CLASS_MAP`, `DEFAULT_RESTRICTIVE_CLASS`;
    - `SCHEDULE_{STOP,LAUNCH,LAUNCH_WINDOW_END}_UTC`;
    - `ENGINE_LOCK_MAX_HOLD_S = 15`, `RELAUNCH_REQUEST_TTL_S = 120`, `WATCH_BUSY_TIMEOUT_MS = 250`, `WATCH_TICK_STALE_S = 180`;
    - `DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY = 1`, `DRAWDOWN_INERT_ALERT_CEILING = "0.5"`, `DRAWDOWN_INERT_ALERT_MIN_FILLS = 10`;
    - `ROW_TS_MAX_SKEW_S = 300`, `EXPORT_FIRST_DUE_H = 26`, `ROOT_ARTEFACT_COMPONENT = "density_table"`;
    - `BOOTSTRAPPED_ROOT_MANIFEST_SHA256 = MappingProxyType({})`.

    Kind sets are `frozenset[str]`, validated against `Kind` (the test sits in 6b; V36). Mapping pins use `MappingProxyType`.
26. **C6.** `plugin.py` defines the `CaptureAdapter`, `Scorer`, `Evaluator`, `Detector`/`DriftDetectors` and `Refitter` Protocols, plus `RefusingPlugin`. `NODE_PLUGINS` and `OFFLINE_PLUGINS` each hold exactly the four `_COMPOSITION_KINDS` keys (`family_manifest.py:118-120`), every value `RefusingPlugin`.
27. **Placeholder ledger.**
    - Rows are `(node_id, owner, owner_symbol, blocks_kinds)`. Carried bodies are fixture-free stubs under `xfail(strict=True, raises=OwnerPending)`.
    - `OwnerPending` is raised only for a `ModuleNotFoundError` on the declared module or its `breezy.` ancestors, or for an `AttributeError` on the declared attribute.
    - The gate tests:
      - markers equal the ledger (both forms, with positive controls);
      - `test_owner_placeholder_symbol_absent`, `test_owner_ids_exist_in_plan_docs`, `test_envelope_manifest_equals_frozen_arch`;
      - `test_every_envelope_node_id_collected_and_unskipped`, `test_widening_kind_enabled_only_when_its_placeholders_cleared`, `test_blocks_kinds_never_below_floor`;
      - AUT-5's `test_l2_widening_requires_empty_placeholder_ledger`.
28. **Root copies (E-14).** `family_bytes.write_root_copy(paths, *, record, artefact_raw) -> RootCopyResult{WRITTEN, EXISTS_EQUAL}`. EXISTS_DIFFERENT raises `RootCopyIntegrity`. Tests:
    - `test_two_roots_sharing_sha_write_identical_artefact_json`;
    - `test_root_copy_exists_different_is_integrity`;
    - `test_root_copy_rerun_after_chmod_0500_is_exists_equal`;
    - `test_refit_into_root_sha_dir_fails_closed`.
29. **Gate.**
    - `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` exits 0 after every seam commit (L-43).
    - Every seam is ≤ 1,000 changed lines; the largest is 950.
    - `lint-imports` passes.
    - The mypy ratchet passes, and ceilings are only ever lowered (V17).
    - RED→GREEN logs exist, with mutation evidence where listed.
30. **Live-path mixed-version safety.**
    - `test_live_path_modules_import_set_pinned` pins the `breezy.*` import sets of `family_manifest.py` and `live_orders_gate.py`.
    - WP-1a, WP-1c and WP-8a add no cross-module import.
    - **Merge order:** WP-8c merges only after a node relaunch at a 16:50Z LAUNCH that follows the WP-8a merge. The evidence is a boot line timestamped after the 8a merge. Until AUT-5a, no live process imports `resolver`.
31. **Bootstrapped root manifests are frozen (E-14 rule 7; A4-R9, A5-R3).**
    - `test_bootstrapped_root_manifests_unchanged`: for every `(family_id, sha)` in `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256`, `sha256(entry_points.REPO_ROOT / "deploy/families" / f"{family_id}.json") == sha`.
      - It hashes through `tests/support/entry_points.REPO_ROOT` (V29) and **never through an absolute path**, so a worktree hashes its own files (arch N4a).
      - An edit fails CI instead of failing LAUNCH.
    - `test_bootstrapped_root_pin_is_append_only` (arch N4b, security N3):
      - **Base ref:** `git merge-base HEAD origin/feat/data-capture-and-risk`, run with `cwd=REPO_ROOT` (V33).
      - If that ref is unavailable, the merge-base fails, or `git rev-parse --is-shallow-repository` prints `true`, the test **FAILS**. It never skips.
      - `git ls-tree <merge-base> -- src/breezy/persistence/autonomy/pins.py` decides presence. Empty output means `pins.py` is absent at the base (seam 3a itself), which is treated as an empty mapping. A non-zero exit is a FAIL.
      - Otherwise `git show <merge-base>:src/breezy/persistence/autonomy/pins.py` is parsed by AST, and no row may be removed or changed.
    - `test_bootstrapped_root_pin_covers_bootstrap_seed_once_nonempty`.
    - **Scope statement (A5-R3).**
      - The append-only test is **CI hygiene, not a control**. When the merge-base is HEAD (a direct commit onto the integration branch), it compares the pins against themselves.
      - The runtime anchor is the resolver's `manifest_sha_mismatch` (AC 17.9), which fails closed.
      - **Until ROOT_ADMIT is enabled (it is not at L1), the only clearing path for an edited root is a reviewed revert.**
      - **From the stage-S bootstrap onward, the live `forecast_quantile_ladder` root manifest is frozen.**
    - The pin is empty at ARCH-0. The pins commit in binding note 9 fills it. (r4 said "binding note 11", which does not exist; corrected.)

## Edge Cases & NFRs (fail-closed, one-writer, symlink refusal, atomicity, thread-affinity)

**Fail-closed.** Every failure gives the restrictive outcome.

| Input or condition | Result |
|---|---|
| Unknown `schema`; unknown, missing or duplicate key; bool as int; float; NaN or Inf; oversize | `WireRefused(reason)`, which becomes a resolver refusal, a demand venue veto, or `VerdictUnreadable` |
| Empty chain under `BREEZY_FAMILY_SOURCE=registry` | `empty_chain` |
| `RegistryUnreadable(busy \| hot_journal \| schema_mismatch \| io \| sqlite_error)` | Resolver: `registry_unreadable` with an enum detail. Watch actor: binding note 8 |
| `venue_seq` gap, renumbering, foreign venue, decreasing ts | `chain_broken` |
| Family introduced by a kind other than BOOTSTRAP/ROOT_ADMIT/MINT; root kind with a foreign lineage root | `validate`: `family_not_introduced` / `root_lineage_mismatch`. Fold: `FoldInvalid` → `replay_invalid` / `registry_unreadable` |
| `now_ns` invalid, or before head − skew | `clock_invalid` / `clock_before_head` |
| HWM Unreadable, unknown type, foreign venue, `venue_seq < 1` | `hwm_unreadable` |
| HWM Absent with any row | `hwm_absent`. Clearing path: the reset CLI |
| HWM above head; hash mismatch at `rows[venue_seq−1]`; `export_seq` > newest | `hwm_regressed` |
| Exports directory missing or unreadable, or a listing error | `export_unreadable` |
| **Exports directory holds a name that is neither this venue's export, another venue's export, nor `hwm_reset_*.json`, other than a `write_once` temp name `\A\.tmp\.[0-9a-f]{16}\Z` (A5-R6; A6-R1)** | **`export_unreadable`** |
| **`hwm_reset_*.json`, another venue's export, or a `.tmp.<16 hex>` name in `evidence/registry/`** | **Ignored** |
| No export file | `not_yet_due` only within 26 h of genesis, for sending and shadow alike; otherwise `export_unreadable` |
| **HWM write where neither sequence exceeds the stored HWM (stale writer)** | **`SKIP` (no write)** |
| **HWM write with the same `venue_seq` but a different head; a mixed direction; Unreadable; a foreign venue** | **`REFUSE`, treated as a failed write (binding note 6f)** |
| Widening row outside enabled or admission-implemented | `widening_kind_not_enabled` / `admission_pending`. The store refuses the batch. The watch actor applies `rows[:admitted]` recomputed from the last verified seq, then vetoes |
| `stage is not STAGE` outside a fixture | `StageNotCanonical` / `stage_not_canonical` |
| More than one CHAMPION/HALTED family | `engine_inconsistency` |
| Role mismatch on a public or private entry | `paths_role_mismatch` |
| Root manifest bytes ≠ row | `manifest_sha_mismatch` (AC 31 catches a committed edit earlier) |
| Root named like a child | Resolved as a root by `origin` |
| Child regex root ≠ lineage root | `child_root_mismatch` |
| Manifest draft, unpinned, unreadable, invalid, prereg-ineligible, directory missing | The matching `manifest_*` / `prereg_ineligible` reason, with no path in the value |
| Identity ≠ row; kind not routed | `manifest_identity_mismatch` / `kind_not_live_gate_routed` |
| Root record mismatch | `root_record_mismatch` |
| Engine sha unpinned or revoked | `engine_code_unpinned` / `engine_code_revoked`. At ARCH-0 every production resolution refuses here by design |
| Root ruling: `no_ruling` / raised / `ok` | `no_live_orders_ruling` / `ruling_refused` |
| Child: no triple, sha mismatch, ruling ≠ policy | `root_not_lineage_allowlisted` / `ruling_refused` / `ruling_not_policy` |
| Guard: reader raises, empty index, intent open or corrupt, bad slug, unknown side | `UNREADABLE` → veto |
| Demand directory unreadable, bad file, unknown family or reason, over the maximum | `venue_veto=True` |
| Journal link broken | `JournalUnverified`; restrictive writes are never blocked |
| `write_once` without hard links; new file in an owner-read-only directory | `LINK_UNSUPPORTED` / `DIR_NOT_WRITABLE` |

**One writer (L-50).** `/home/jon/breezy/tests/unit/autonomy_writer_table.py` is data, and Wave 1 owners extend it. The AST scan fails on any write site outside `single_read.{write_once, replace_atomic, ensure_dir}` and `registry_store`.

| Path | Writer |
|---|---|
| `registry/registry.sqlite` | Under `registry/engine.lock`: the engine and the HWM-reset CLI |
| `evidence/registry/registry_<venue>_<date>[_hwm<k>].jsonl` | Write-once: the engine and the reset CLI |
| `evidence/registry/hwm_reset_<ts>.json` | Write-once: the reset CLI (AUT-5 r7 `:189`; ignored by `newest_export`) |
| `derived/verdicts/**` | Write-once: producers |
| `registry/demand/<venue>/*` | Write-once: the engine and `DEMAND_WRITER_PRODUCER_IDS` |
| `evidence/journal/<venue>/<kind>/<seq>.json` | Write-once: the engine |
| `derived/artefacts/<model_class>/<sha>/{artefact.json, roots/<family_id>.json}` | `write_root_copy` (engine bootstrap); AUT-3 refits write into a fresh `<sha>/` only |
| Exec-store key `autonomy/registry_hwm/<venue>` | **Values are written only through `hwm.write_monotone` under the intent flock:** the node (boot and ticks) and the L1 cut-over (onto Absent). **The reset CLI is the only bypass.** The cut-over's in-hold abort delete is the only delete outside the reset CLI (A5-R1/A5-R2; AUT-5a row) |

**Paths.** Every path is built by `AutonomyPaths(root)` or by `ShadowPaths`. They are distinct classes, each with a class-level `is_shadow: Final[bool]`. Components use `re.ASCII` `\A…\Z` patterns:

| Component | Pattern |
|---|---|
| venue | `[a-z0-9_]{1,32}` |
| family | `[a-z0-9_]{1,64}` (V19) |
| model_class | `<kind ∈ _COMPOSITION_KINDS>:[a-z_]{1,48}` |
| sha or verdict id | `[0-9a-f]{64}` |
| date | `date.fromisoformat` |
| journal kind | bare name |
| seq | int ≥ 1, `%010d` |

All I/O goes through the AC 7 openat walk, and each builder has a traversal-vector test.

**Atomicity.**
- A multi-row append is one transaction.
- A crash in `write_once` leaves at most a `.tmp.` file, which the engine sweeps. In `evidence/registry/` such a file is ignored by `newest_export` (A6-R1).
- A crash in `replace_atomic` leaves the old bytes.
- Root copies are written before the genesis COMMIT, and a rerun is idempotent.

**Threads, clock, hygiene.** No connection is held across calls. There are no threads, timers or asyncio, and no module-level mutable state. `now_ns` is always explicit. Refusals carry enums, never paths.

**Size and performance.**
- 10,000 synthetic rows resolve in ≤ 2 s.
- `closure_sha256` runs in ≤ 5 s and ≤ 128 MB.
- The resolver closure carries about 48 MB of pyarrow, which is accepted.

**Root permission.** The gate may run as uid 0 under `unshare -r`. Modes are asserted with `stat`, SQLite uses `mode=ro`, and `DIR_NOT_WRITABLE` refuses by mode bit (V30).

## Architecture & Data Flow (modules, public API signatures, storage layout + paths, layering vs import-linter layers app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain)

**Layering.**
- `persistence`, `registry` and `normalize` are independent siblings (`pyproject.toml:97`).
- `persistence.autonomy` imports only stdlib, `persistence` and `settlement`.
- Types that reach pyarrow live only in `PYARROW_REACHING` modules.
- `NODE_PLUGINS` is in strategy and `OFFLINE_PLUGINS` in analysis. The watch actor (AUT-5a) is `/home/jon/breezy/src/breezy/strategy/autonomy/registry_watch_actor.py`.

**Modules and public API.** Every module uses `from __future__ import annotations` and mypy strict. ☆ marks a change in r5.

```text
src/breezy/persistence/__init__.py          docstring only
src/breezy/persistence/family_manifest.py   + parse_family_manifest(raw: bytes, *, path: Path, allow_draft: bool = False) -> FamilyManifest
src/breezy/persistence/live_orders_gate.py  + _LINEAGE_POLICY_ALLOWLIST; CHILD_FAMILY_ID_RE; _verify_ruling_file; LineagePolicyDecision;
                                              lineage_policy_authorized(child, root_family_id, repo_root); _lineage_policy_authorized(..., *, allowlist)
src/breezy/persistence/autonomy/
  __init__.py       docstring only (AST: no import nodes)
  canonical.py      canonical_json; sha256_hex; decimal_str; CanonicalTypeError
  wire.py           parse_json_exact; require_*; WireRefusalReason; WireRefused; SHA256_RE; FAMILY_ID_RE
  single_read.py    ReadPolicy; open_root; walk_dirs; read_once_at; read_once_nofollow; write_once; replace_atomic; ensure_dir;
                    list_dir_at; SingleReadRefused(reason)
  paths.py          AutonomyPaths(root); ShadowPaths(root); is_shadow; builders; root_record(model_class, sha, family_id) [6d];
                    default_data_root() (entry points only)
  pins.py           literals only (AC 25)
  veto.py           VetoReason (15); compose_entry_vetoes
  plugin.py         C6 Protocols; RefusingPlugin; is_complete
  closure_manifest.py  CLOSURE_MODULES = MappingProxyType({})
  closure.py        closure_sha256(component); closure_from_grimp(entry) (gate-only, lazy grimp)
  schemas.py        State, Kind, CauseClass, CauseCode, WriterMode, DecidedBy, RefusalReason, UnreadableReason, LiveOrdersRefusal (7),
                    FoldInvalidReason; TransitionRow; ExportTrailer; StagePolicy + StageView; ManifestFacts + ManifestFactsReader;
                    AdmissibilityResult   -- imports wire, canonical, rollback_journal only
  stage_policy.py   STAGE: Final[StagePolicy] = _build()
  verdict.py        C4 types; verdict_id; write_verdict; read_verdict
  lineage.py        Lineage, RootRecord, RefitRun, RefitOutcome; model_class_of; root_model_class(composition_kind)
  label_schema.py   LABEL_SCHEMA_ID; LABEL_V1_ARROW_SCHEMA; ExcludedReason; PSource; LabelRole
  demand.py         DemandRecord; write_engine_demand; write_producer_demand -> DemandWrite; scan_demands -> DemandScan
  drill_marker.py   DrillMarker (12 keys); read_marker_at -> DrillMarker | MarkerAbsent | MarkerError
  rollback_journal.py  JOURNAL_KINDS; JournalEntry; JournalHead(seq, sha256); append_journal; read_journal_chain
  fold.py           fold(rows, venue, now_ns) -> FoldResult | FoldInvalid; resolve_champion; FamilyView(origin, lineage_root_family_id);
                    LineageView; LineageTallies (13 fields); VenueTallies(infra_resumes, drill_close_restores)
  transitions.py    ALLOWED; KIND_MASK; WIDENING_KINDS; RESTRICTIVE_KINDS; PAIR_KINDS; _ADMISSION_IMPLEMENTED; is_widening; transition_id;
                    validate(prior, rows, *, mode, now_ns, stage, manifests, export_counters=None) -> RefusalReason | None;
                    rows_admissible(rows, *, stage) -> AdmissibilityResult
  chain.py          genesis; transition_hash; VerifiedVenueChain; verify_venue_chain; verify_extension; seq_is_verified_prefix; verify_against_export
  family_bytes.py   FamilyBytes; ByteBindingFailure; RootCopyResult; RootCopyIntegrity; read_manifest_facts;
                    verify_family_bytes(row, *, paths, repo_root, origin) -> FamilyBytes | ByteBindingFailure; write_root_copy
  registry_store.py ☆ RegistryStore.initialise; RegistryStore(paths).append(rows, *, expected_prior_seq, mode, now_ns) -> AppendResult;
                    _append(..., stage, _fixture_stage=False); StageNotCanonical; WideningNotEnabled; AdmissionPending; write_export;
                    RegistryReader; RegistryUnreadable(reason); newest_export(paths, venue) -> (ExportTrailer, rows) | ExportUnreadable | ExportAbsent
                    (venue-scoped name filter; hwm_reset_*.json and other-venue exports ignored; any other name -> ExportUnreadable)
  hwm.py ☆          Hwm; HwmAbsent/HwmPresent/HwmUnreadable; REGISTRY_HWM_KEY_PREFIX; hwm_key; hwm_reading_from_bytes; hwm_check; next_hwm;
                    HwmWriteDecision{WRITE, SKIP, REFUSE}; write_monotone_decision(current: HwmReading, new: Hwm) -> HwmWriteDecision
                    [AUT-5a adds write_monotone(store, new, *, held_lock) here; stdlib only]
  replay.py         replay_full(chain, *, paths, repo_root) -> ReplayOk | ReplayInvalid | ReplayCauseUnresolved | ReplayArtefactMismatch; _replay_full
  net_position.py   LegFill(leg, side, qty, ts_event_ns) (netting-only); net_signed_qty; UnknownSide
  entry_guard.py    GuardResult; FillIndexAbsent; FillRow(order_side, cumulative_qty, ts_event_ns); FillReader; leg_instrument_ids;
                    rung_has_net_position; guard_veto_reason
  resolver.py ☆     ResolvedFamily; ShadowResolution; ResolverRefusal(reason, detail); HwmMode; FamilySource; read_family_source(env);
                    resolve_sending_family (step 1 lives here); resolve_shadow_family; SHADOW_CALL_SITES = frozenset();
                    _resolve(..., stage, lineage_gate, hwm_mode, _fixture_stage=False) (steps 0, 2-12; shadow 0, 2, 3, 5-8);
                    manifest_equal_modulo_allowlist
src/breezy/strategy/autonomy/node_plugins.py     NODE_PLUGINS
src/breezy/analysis/autonomy/offline_plugins.py  OFFLINE_PLUGINS
```

**Closed `RefusalReason`.** It is unchanged from r4. `test_resolver_refusals_give_no_champion` checks the members by AST. The members are:
- `registry_unreadable`, `empty_chain`, `chain_broken`, `clock_invalid`, `clock_before_head`;
- `hwm_unreadable`, `hwm_absent`, `hwm_regressed`, `export_unreadable`, `export_prefix_mismatch`;
- `widening_kind_not_enabled`, `admission_pending`;
- `replay_invalid`, `replay_cause_unresolved`, `replay_artefact_mismatch`;
- `engine_inconsistency`, `no_sender`, `paths_role_mismatch`, `stage_not_canonical`, `family_not_introduced`, `root_lineage_mismatch`;
- `engine_code_unpinned`, `engine_code_revoked`;
- `manifest_unreadable`, `manifest_invalid`, `manifest_draft`, `manifest_unpinned`, `prereg_ineligible`, `manifest_sha_mismatch`, `manifest_identity_mismatch`, `kind_not_live_gate_routed`;
- `artefact_unreadable`, `artefact_sha_mismatch`, `root_record_mismatch`;
- `child_root_mismatch`, `child_not_equal_root`, `root_not_lineage_allowlisted`, `ruling_not_policy`, `ruling_refused`, `no_live_orders_ruling`;
- `d0_breach`, `trial_prefix_mismatch`.

`test_live_orders_refusal_mirrors_live_orders_reason` covers V26. `HwmWriteDecision` is a separate enum and is not a refusal reason.

**Storage layout.** All paths are under `/home/jon/.local/share/breezy/`. Directories are 0700, files 0600, or 0444 when content-addressed.
- `registry/registry.sqlite` and `registry/engine.lock`.
- `registry/families/<id>.json`, `registry/demand/<venue>/`, `registry/heartbeat/<venue>.json`, `registry/drill/marker.json`.
- `evidence/registry/registry_<venue>_<YYYY-MM-DD>.jsonl` (0444). The trailer is `{"schema":"registry_export/v1","venue","venue_seq","chain_head","export_seq","evidence_journal_heads"}`. The reset variant is `_hwm<export_seq>.jsonl`. The reset record is `hwm_reset_<ts>.json`, which `newest_export` ignores. **Every bootstrap (production and shadow) creates this directory (A5-R10).**
- `evidence/journal/<venue>/<kind>/<seq:010d>.json` (0444).
- `derived/verdicts/<family_id>/<YYYY-MM-DD>/<verdict_id>.json`.
- `derived/artefacts/<kind>:<component>/<sha>/artefact.json`, with root records at `…/roots/<family_id>.json`.
- `registry-shadow/` has the same layout and is a `ShadowPaths` root.

**Data flow.**
- Producers call `write_verdict`.
- The engine (AUT-5a) runs `RegistryReader` → `fold` → `append` → `write_export`, `append_journal` and `write_engine_demand`. In bootstrap mode, production or shadow, it also runs `write_root_copy` and creates `evidence/registry/`.
- `aut6.intraday` calls `write_producer_demand`.
- `resolve_sending_family` runs: public step 1 → `RegistryReader` → `verify_venue_chain` → `newest_export` (filtered) → `hwm_check` → `rows_admissible` → `replay_full` → `verify_family_bytes` → gate → `ResolvedFamily` with `hwm`.
- `resolve_shadow_family` runs: public role check → steps 0, 2, 3, 5–8 → `ShadowResolution`.
- The watch actor (AUT-5a) runs `read_venue_rows(after_seq=<last verified>)` → `verify_extension` → `rows_admissible` → `validate` → `fold` → `scan_demands` → `hwm_check(newest_export_seq=<carried>)` → `next_hwm(export_seq=<carried>)` → `write_monotone` → `rung_has_net_position`. Its `export_seq` starts from `ResolvedFamily.hwm.export_seq`, is carried forward, and changes only after a verified `newest_export` call. It is never lowered.
- The node boot writes `ResolvedFamily.hwm` through `write_monotone` under the intent flock.
- `store.append` calls `family_bytes.read_manifest_facts`.

## Stub Surface for Wave 1 (table: symbol | consumer plan + section | ARCH-0 delivers real or stub)

"Real" means implemented and tested. "Owner" means outside ARCH-0. The module named is the frozen import location.

| Symbol (module) | Consumer | ARCH-0 |
|---|---|---|
| `VetoReason`, `compose_entry_vetoes` (`veto`) | AUT-1 r12 `:1237`; AUT-5 r7 §3.1 | Real; no alias |
| `NODE_PLUGINS`, `OFFLINE_PLUGINS`, C6 Protocols, `RefusingPlugin` | AUT-1, 2, 3, 4, 6 | Real; every kind refuses |
| Every AC 25 pin (`pins`) | AUT-1 to AUT-7; AUT-5a bootstrap | Real; the root pin is empty |
| Code-identity pins, `closure_sha256` | AUT-5 WP4, AUT-4, AUT-6 | Real machinery, empty pins |
| `StagePolicy`, `StageView`, `RefusalReason`, `LiveOrdersRefusal`, `ManifestFacts`, `AdmissibilityResult` (`schemas`); `STAGE`; `_ADMISSION_IMPLEMENTED`, `rows_admissible` | AUT-5 WP1b, WP5, WP9, WP10 | Real |
| `verdict.*`, `decimal_str` | AUT-2 `:943`; AUT-4 `:450`; AUT-6 `:512` | Real |
| `label_schema.*`, `lineage.*`, `drill_marker.*` | AUT-2, 3, 6, 7 | Real |
| `demand.*` | AUT-6 WP5b; AUT-5 WP4, WP5 | Real |
| `append_journal`, `read_journal_chain`, `JournalHead` | AUT-7 r5 `:91`, `:506` | Real; `JOURNAL_KINDS` empty |
| `RegistryStore.append`, `KIND_MASK`, `WriterMode`, `transitions.validate` | AUT-7 r5 `:703`; AUT-5 WP4 | Real; widening refused |
| `RegistryReader`, `RegistryUnreadable`, `newest_export` (filtered), `verify_*`, `fold`, `FoldInvalid`, `resolve_champion`, `LineageTallies`, `VenueTallies` | AUT-3, AUT-4, AUT-5, AUT-7; AUT-6 r15 `:1474` | Real |
| `resolve_sending_family`, `ResolvedFamily`, `ResolverRefusal`, `HwmMode`; `FamilyBytes`; `Hwm`, `HwmReading`, `hwm_reading_from_bytes`, `hwm_check`, `next_hwm`, ☆ `HwmWriteDecision`, `write_monotone_decision` (`hwm`) | AUT-5 WP5, WP6, WP8, WP10; AUT-1 r12 `:15`, `:329` | Real |
| `resolve_shadow_family`, `ShadowResolution` | AUT-5 WP5, WP6, WP10 | Real; `SHADOW_CALL_SITES` empty |
| `verify_family_bytes`, `write_root_copy` | AUT-7 r5 `:56`, `:703`; AUT-5a | Real |
| `parse_family_manifest`, `lineage_policy_authorized`, `_LINEAGE_POLICY_ALLOWLIST` | resolver; AUT-5 WP9 | Real |
| `entry_guard.*`, `GuardResult`, `FillReader`, `FillRow`; `LegFill`, `net_signed_qty` | AUT-5 WP2, WP5; AUT-2 r7 `:335` | Real |
| **Owner rows** | | |
| Nomination k-checks, policy-stricter bounds, HWM_RESET admission, per-kind `_ADMISSION_IMPLEMENTED` | AUT-5 WP1b | Owner |
| ☆ `hwm.write_monotone(store, new, *, held_lock)` and its `HwmKeyStore` Protocol (store binding of the A5-R2 decision) | AUT-5a | Owner |
| `policy.load_policy_block` | AUT-5 WP3 | Owner |
| `demand.archive` and its 3 tests | AUT-5 WP4 | Owner |
| Derived caches, including `holdout_opens` and its writer | AUT-5 WP4; AUT-4 r11 `:431` | Owner |
| `halt_rows.py`, `submit_intent_record.py` and 3 tests | AUT-5a; AUT-6 aliases | Owner |
| E-8a snapshot helper | Seam B | Other seam |
| `heartbeat/v1`, `halt_mirror/v1`, `stop_complete/v1`, `launch_event/v1`, `relaunch/v1`, `drawdown_control_active` | AUT-5a WP4, 6, 7, 11 | Owner |
| Child artefact location; four-site containment widening | AUT-5a | Owner |
| `PolymarketUsFillReader` | AUT-5a | Owner |
| `_LINEAGE_POLICY_ALLOWLIST` row; child routing in `live_orders_authorized` | AUT-5 WP9 | Owner |
| `net_position.CostedFill`, `average_cost_basis` | AUT-2 | Owner |
| `JOURNAL_KINDS` members, `verify_journal_chain` | AUT-7 | Owner |
| `sample_size.py`, `nomination.py` | AUT-4 | Owner |
| `capture_*.py` | AUT-1a (E-12) | Owner; joins `NAUTILUS_PERMITTED` |
| C4.1 holdout ruling; AUT-2 Wave-0 egress review | Coordinator; AUT-2a | Owner |

**Frozen signatures.** The surfaces above are frozen from approval, and a later change needs a coordinator erratum. Wave 1 may build against them before they merge.

## File-by-File Plan (absolute path | new|modified | exact content | deps)

The plan is unchanged from r4 except for the two content notes marked ☆.

| Absolute path | | Content | Deps (V22 edges) |
|---|---|---|---|
| `/home/jon/breezy/src/breezy/persistence/__init__.py` | mod | Docstring only | — |
| `/home/jon/breezy/src/breezy/persistence/family_manifest.py` | mod | AC 21; `__all__` +1 | — |
| `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py` | mod | AC 20 | family_manifest |
| `/home/jon/breezy/src/breezy/persistence/autonomy/__init__.py` | new | Docstring only | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/canonical.py` | new | AC 6 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/wire.py` | new | AC 5 | canonical |
| `/home/jon/breezy/src/breezy/persistence/autonomy/single_read.py` | new | AC 7 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/paths.py` | new | Builders; `root_record` in 6d | wire |
| `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py` | new | AC 25 | none |
| `/home/jon/breezy/src/breezy/persistence/autonomy/veto.py` | new | AC 23 | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/plugin.py` | new | AC 26 | veto |
| `/home/jon/breezy/src/breezy/persistence/autonomy/closure_manifest.py` | new | Empty mapping | — |
| `/home/jon/breezy/src/breezy/persistence/autonomy/closure.py` | new | `closure_sha256`; lazy grimp | single_read, closure_manifest |
| `/home/jon/breezy/src/breezy/persistence/autonomy/rollback_journal.py` | new | AC 24 | wire, single_read, paths |
| `/home/jon/breezy/src/breezy/persistence/autonomy/schemas.py` | new | Pyarrow-free enums and records | wire, canonical, rollback_journal |
| `/home/jon/breezy/src/breezy/persistence/autonomy/stage_policy.py` | new | `STAGE` | pins, transitions, schemas |
| `/home/jon/breezy/src/breezy/persistence/autonomy/verdict.py` | new | AC 24 | wire, canonical, single_read, paths, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/lineage.py` | new | AC 24 | wire |
| `/home/jon/breezy/src/breezy/persistence/autonomy/label_schema.py` | new | C2 arrow schema | pyarrow |
| `/home/jon/breezy/src/breezy/persistence/autonomy/demand.py` | new | AC 24 | wire, single_read, paths, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/drill_marker.py` | new | AC 24 | wire, single_read |
| `/home/jon/breezy/src/breezy/persistence/autonomy/fold.py` | new | AC 14 | schemas, pins |
| `/home/jon/breezy/src/breezy/persistence/autonomy/transitions.py` | new | AC 13 | schemas, pins, fold |
| `/home/jon/breezy/src/breezy/persistence/autonomy/chain.py` | new | AC 11 | canonical, schemas |
| `/home/jon/breezy/src/breezy/persistence/autonomy/family_bytes.py` | new | AC 17, 21, 28 | single_read, paths, lineage, schemas, family_manifest, mechanism_test_guard |
| `/home/jon/breezy/src/breezy/persistence/autonomy/registry_store.py` | new | AC 8–12; ☆ `newest_export` name filter (AC 17.3) | chain, transitions, fold, stage_policy, family_bytes, single_read, paths, schemas |
| `/home/jon/breezy/src/breezy/persistence/autonomy/hwm.py` | new | AC 16; ☆ `HwmWriteDecision`, `write_monotone_decision` | wire, schemas, chain |
| `/home/jon/breezy/src/breezy/persistence/autonomy/replay.py` | new | Row-by-row `validate(mode=None)` | transitions, fold, verdict, chain, family_bytes |
| `/home/jon/breezy/src/breezy/persistence/autonomy/net_position.py` | new | AC 22 | stdlib |
| `/home/jon/breezy/src/breezy/persistence/autonomy/entry_guard.py` | new | AC 22 | net_position, veto |
| `/home/jon/breezy/src/breezy/persistence/autonomy/resolver.py` | new | AC 17–19 | all of the above + live_orders_gate, hwm |
| `/home/jon/breezy/src/breezy/strategy/autonomy/__init__.py`, `/home/jon/breezy/src/breezy/strategy/autonomy/node_plugins.py` | new | Docstring; `NODE_PLUGINS` | plugin |
| `/home/jon/breezy/src/breezy/analysis/autonomy/__init__.py`, `/home/jon/breezy/src/breezy/analysis/autonomy/offline_plugins.py` | new | Docstring; `OFFLINE_PLUGINS` | plugin |
| `/home/jon/breezy/pyproject.toml` | mod | Contracts (a), (b), (c); module names only (V23) | — |
| `/home/jon/breezy/scripts/ci/regen_closure_manifest.py` | new | Deterministic literal output | grimp |
| `/home/jon/breezy/tests/support/entry_points.py` | new | Owns `REPO_ROOT`, `PYPROJECT_PATH`, `DEPLOY_SYSTEMD_DIR`, `SCRIPTS_DIR` (byte-identical from `:55-60`), the two helpers from `:158-190`, and `_entry_modules_from_scripts_importing(package)` | — |
| `/home/jon/breezy/tests/unit/test_runtime_import_isolation.py` | mod | Imports the constants and helpers from `entry_points`; `functools.partial` for the runtime helper; no `def test_*` or `assert` line changed | entry_points |
| `/home/jon/breezy/tests/unit/test_mypy_ratchet.py` | mod only if needed | Lower a ceiling only | — |
| `/home/jon/breezy/tests/support/autonomy_owner.py` | new | `OwnerPending`, `require_owner_symbol` | — |
| `/home/jon/breezy/tests/unit/autonomy_owner_placeholders.py`, `/home/jon/breezy/tests/unit/autonomy_blocks_kinds_floor.py`, `/home/jon/breezy/tests/unit/autonomy_writer_table.py` | new | Ledger, floor, writer rows | — |
| `/home/jon/breezy/tests/unit/autonomy_envelope_manifest.py` | new | `ARCH_FREEZE_SHA256`; `E11_RENAMES` (the 3 E-11 rows); `ENVELOPE_NODE_IDS` | — |
| `/home/jon/breezy/tests/fixtures/family_manifest_golden/` | new | Corpus, `artefacts/`, `expected.json` | — |
| `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` | **never edited** | V7 byte pin; AST reads only | — |

## Test Strategy (file | test names | unit/contract | which §4.7 rows are real-GREEN in ARCH-0 vs carried strict-xfail with owner)

**Carrying mechanism.** As in AC 27.
- Pytest 9.1.1 fails a non-matching exception and fails a strict XPASS.
- Half-real tests use literal `pytest.param` ids.
- `test_every_envelope_node_id_collected_and_unskipped` cross-checks AST ids against one `--collect-only -q` subprocess.

**Placement rule (A5-R5, re-audited in r5).**
- A test sits in the seam that lands the last code it exercises, so it is RED in that seam before the code and GREEN after it, and never red at an earlier gate.
- For AST and scan tests, the code exercised is the scanner and its planted control. Those tests sit where the scanner lands and then guard later seams.
- r5 moves eight tests:
  - three named in the ruling: `test_bootstrap_seed_genesis_only` and `test_store_refuses_second_bootstrap_per_venue` from 6e to 7d, and `test_drill_mint_not_counted` from 7c to 7d;
  - five found by the audit (V36): `test_enabled_widening_kinds_subset_of_widening_kinds` 3a → 6b; `test_autonomy_exec_keys_disjoint_from_halt_prefixes` 3c → 7e; `test_autonomy_package_import_graph_is_acyclic` 6a → 6c; `test_drill_demote_and_halt_counters_capped` 7b → 7c; and the AUT-5 r7 WP1 fold list, now split by name across 7a–7d.
- `test_family_artefact_binding_immutable` stays in 6e. AUT-5 r7 gives only its name. The WP-6 brief STOP rule applies to it.

**Real-GREEN in ARCH-0.** Mutation evidence is in brackets.

| File | Seam | Tests | Type |
|---|---|---|---|
| `/home/jon/breezy/tests/unit/test_persistence_import_free.py` | 1a | `test_persistence_init_has_no_import_nodes`; `test_persistence_has_no_facade_consumers` [planted `from breezy.persistence import write_records`]; `test_persistence_entry_module_imports_cleanly[*]` | contract |
| same | 1c | `test_live_path_modules_import_set_pinned` | contract |
| `/home/jon/breezy/tests/unit/test_family_manifest_split_golden.py` | 1b | `test_parse_split_matches_presplit_golden`; `test_load_family_manifest_keeps_prereg_check` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_canonical.py`, `/home/jon/breezy/tests/unit/test_autonomy_wire.py` | 2a | goldens; decimals; NaN/Inf/exponent; non-str key; float; surrogate; duplicate key; bool-as-int | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_contracts.py` | 2a | `test_autonomy_init_has_no_import_nodes` | contract |
| same | 2b | `test_every_autonomy_module_is_classified` [planted module]; `test_autonomy_core_modules_nautilus_free_at_runtime`; `test_contract_c_refuses_planted_pyarrow_reach[canonical]` | contract |
| same | 6a | `test_contract_c_refuses_planted_pyarrow_reach[schemas]` | contract |
| same | 6c | ☆ `test_autonomy_package_import_graph_is_acyclic` (from 6a); `test_autonomy_policy_not_mutable_from_src` [planted: `StagePolicy(`, aliased `SP(`, `dataclasses.replace`, `copy.copy`, `copy.deepcopy`, `x.__class__(`, `type(x)(`, `object.__new__`, `stage_policy._build`; ☆ an exemption-row positive control]; `test_admissibility_predicate_has_one_home` [planted read] | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_single_read.py` | 2b | `test_walk_refuses_symlinked_intermediate_dir`; `test_read_refuses_fifo_without_blocking`; `test_read_refuses_group_writable_under_strict`; `test_write_once_symlink_at_destination_with_equal_bytes_is_different`; `test_write_once_final_mode_by_stat`; `test_write_once_link_unsupported_fails_closed`; `test_write_once_exists_equal_creates_no_temp`; `test_write_once_new_file_in_owner_readonly_dir_refused` [drop the mode check]; `test_replace_atomic_writes_temp_in_target_dir_fsyncs_and_replaces`; `test_read_size_cap`; `test_read_uses_one_fd` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_paths.py` | 3a | traversal vector per builder; `test_family_component_accepted_by_both_existing_id_patterns`; `test_shadow_paths_is_distinct_type` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_pins.py` | 3a | `test_pins_ceilings_within_arch_bounds`; `test_damping_ceilings[ceilings]`; `test_rollback_dwell_age_and_drill_headroom_ceilings`; `test_attest_cadence_has_no_expiry_gap[pins_invariant]`; `test_request_ttl_covers_two_schedule_polls`; `test_root_admit_ceiling_committed_false`; `test_halt_reason_class_map_is_exact` (against the ARCH C5 table literal); `test_schedule_constants_equal_supervisor`; `test_root_admit_enabled_requires_ceiling_true`; `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[pins]`; `test_bootstrapped_root_manifests_unchanged` [wrong-sha pin row] ☆ (via `REPO_ROOT`); `test_bootstrapped_root_pin_is_append_only` ☆ (named base ref, fail-not-skip, absent-at-base → empty) [unavailable ref → FAIL]; `test_bootstrapped_root_pin_covers_bootstrap_seed_once_nonempty` | unit |
| same | 3b | `test_code_identity_pins_cover_import_closure`; `test_engine_pin_history_retained`; `test_closure_manifest_equals_grimp_closure`; `test_regen_output_is_literal_and_reproducible`; `/home/jon/breezy/tests/unit/test_autonomy_closure.py::test_closure_hash_runtime_under_budget` | unit |
| same | 6b | ☆ `test_enabled_widening_kinds_subset_of_widening_kinds` (from 3a; V36) | unit |
| same | 6c | `test_enabled_widening_kinds_subset_of_admission_implemented` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_plugins.py` | 3a/3b | 3a: `test_veto_reason_closed_set_equals_arch`, `test_capture_untagged_is_a_veto_reason`, `test_compose_entry_vetoes_exception_is_registry_unreadable`. 3b: `test_family_plugin_exact_set`, `test_refusing_plugin_refuses_every_member` | unit |
| `/home/jon/breezy/tests/unit/test_entry_guard.py` | 3c | `test_rung_net_position_veto_crosses_legs_and_families[double]`; `test_entry_guard_unreadable_index_vetoes`; `test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]`; `test_net_signed_qty_no_leg_is_short_yes`; `test_negative_net_vetoes`; `test_empty_index_is_unreadable`; `test_open_intent_is_unreadable_and_checked_first`; `test_bad_slug_is_unreadable`; `test_guard_body_exception_is_unreadable`; `test_leg_suffix_equals_instrument_leg`; `test_leg_fill_fields_frozen`; `test_fill_index_key_matches_exec_client_writer` [change `"^no"`]; `test_fill_row_side_vocabulary_matches_exec_record_signs` [add `"BUY_SHORT"`] | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_owner_placeholders.py` | 4a | the 8 AC 27 gate tests; `test_require_owner_symbol_propagates_broken_owner_module` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_files_one_writer.py` | 4a | `test_autonomy_files_have_one_writer` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_envelope.py` | 4a | `test_autonomy_never_reads_or_writes_operator_controls` (tokens from `operator_controls.py:142`); `test_autonomy_never_touches_enablement_permit_or_firewall`; `test_autonomy_never_imports_order_path`; `test_autonomy_alert_egress_not_widened`; `test_autonomy_payload_hygiene_scan`; `test_family_source_read_only_by_resolver_and_child_env`; `test_no_asdict_in_autonomy`; `test_no_wall_clock_in_core`; `test_no_threads_or_asyncio_in_core`; `test_autonomy_never_passes_allow_draft_true`; `test_exec_client_never_edited`. Each has a planted control and a minimum judged-module count | contract |
| `/home/jon/breezy/tests/unit/test_launch_window_table.py` | 4a | `test_no_unit_overlaps_launch_window[existing_units]`; `test_launch_path_units_end_before_next_fixed_point[existing_units]` | contract |
| `/home/jon/breezy/tests/unit/test_autonomy_verdict.py` | 5a | `test_differing_body_same_id_refused` [drop the EEXIST compare]; `test_verdict_id_excludes_produced_at`; `test_recompute_same_slot_same_inputs_same_verdict_id`; `test_verdict_validity_ceiling[writer]`; `test_verdict_exact_set_and_closed_enums`; `test_decimal_fields_canonical_strings` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_records.py` | 5a/5b/6d | 5a: lineage, root and refit_run exact-set and goldens; `test_label_arrow_schema_pinned_column_for_column`. 5b: `test_drill_marker_exact_set_and_absent_vs_dir_missing`. 6d: `test_two_roots_sharing_sha_write_identical_artefact_json`, `test_root_copy_exists_different_is_integrity`, `test_root_copy_rerun_after_chmod_0500_is_exists_equal`, `test_refit_into_root_sha_dir_fails_closed` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_demand.py` | 5b | `test_producer_demand_flood_cannot_exhaust_integrity_slot`; `test_producer_demand_write_is_restrictive_only[writer_api]`; `test_demand_writer_refuses_unlisted_producer`; `test_producer_demand_idempotent_on_verdict_id`; `test_bad_demand_file_vetoes_venue[reader]` | unit |
| `/home/jon/breezy/tests/unit/test_autonomy_journal.py` | 5b | `test_journal_envelope_write_once_linked`; `test_journal_unknown_kind_refused`; `test_journal_seq_collision_fails_closed` | unit |
| `/home/jon/breezy/tests/unit/test_registry_schemas_chain.py` | 6a | `test_canonical_row_hashes_venue_and_venue_seq`; `test_transition_id_excludes_expected_prior_seq`; `test_verify_venue_chain_requires_contiguous_seq_single_venue_monotone_ts`; `test_live_orders_refusal_mirrors_live_orders_reason`; `test_schemas_holds_no_pyarrow_reaching_type` | unit |
| `/home/jon/breezy/tests/unit/test_registry_fold.py` | 6b | structural fold (states, pending pairs, ACTIVATE window, lapse); `test_rows_admissible_stops_at_first_refused_widening_row` | unit |
| same | 7a | ☆ (fold structure, named explicitly) `test_terminal_halt_freezes_lineage`; `test_demote_during_pending_swap_incoming`; `test_demote_during_pending_swap_outgoing`; `test_unactivated_pair_lapses_at_launch`; `test_post_launch_swap_cancel_voids_pair_only_before_1700`; `test_post_launch_swap_cancel_restores_incumbent[fold]`; `test_drill_flag_spans_promote_to_rollback`; `test_infra_cause_never_retires`; `test_rollback_failed_never_freezes_venue` | unit |
| same | 7b | `test_family_origin_from_introducing_row`; `test_family_introduced_by_other_kind_is_invalid[ROLLBACK,RESUME,PROMOTE,ACTIVATE,DRILL_ADMIT]`; `test_root_kind_with_foreign_lineage_root_is_invalid[BOOTSTRAP,ROOT_ADMIT]`; `test_lineage_tallies_fields_equal_arch_counters_minus_non_derivable`; `test_tallies_alpha_spent_equals_sum_alpha_k`; `test_carried_counters_are_floors`; ☆ `test_drill_admit_charges_only_drill_budget`; ☆ `test_lapsed_pair_never_charged`; ☆ `test_target_ineligible_never_counted_or_operator_cleared` | unit |
| same | 7c | ☆ (validate I, fold-file tests) `test_drill_promote_refuses_non_champion_sha`; `test_drill_refused_over_halted_incumbent`; `test_drill_budget_separate`; `test_drill_row_refused_while_non_drill_cause_stands`; `test_drill_demote_and_halt_counters_capped` (from 7b); `test_drill_resume_never_charges_model_budget`; `test_resume_refused_while_swap_pending`; `test_resume_requires_every_cause_cleared`; `test_rollback_failed_resumes_only_under_trigger_class`; `test_drill_close_restore_charges_no_drill_or_production_budget`; `test_drill_close_restore_refused_after_non_drill_cause` | unit |
| same | 7d | ☆ `test_root_admit_only_when_venue_has_no_sender[validate]`; `test_damping_ceilings[counting_rule]` | unit |
| `/home/jon/breezy/tests/unit/test_registry_store.py` | 6e | `test_registry_transition_table_is_exact`; `test_registry_cas_and_idempotent_replay`; `test_registry_hash_chain_and_triggers` [delete the UPDATE trigger]; `test_repeat_supersede_same_family_is_not_replay[arch0]`; `test_family_artefact_binding_immutable`; `test_store_enforces_kind_mask_per_mode` [remove the mask]; `test_daily_refuses_widening_before_stage_flag`; `test_nomination_columns_required_and_read_by_k_check[columns_required]`; `test_store_multirow_append_is_atomic`; `test_insert_or_replace_refused`; `test_on_conflict_do_update_refused`; `test_venue_seq_gap_refused_by_trigger`; `test_first_row_venue_seq_must_be_one` [remove COALESCE]; `test_partial_replay_refused`; `test_append_requires_concrete_mode`; `test_row_ts_skew_and_monotonicity_refused`; `test_writer_pragmas_read_back`; `test_store_sql_has_no_replace_or_ignore`; `test_admission_pending_refused_when_enabled_but_unimplemented`; `test_admissibility_predicate_shared[store]`; `test_append_refuses_non_canonical_stage` | unit |
| same | 6f | `test_registry_readonly_open_engine_stopped`; `test_registry_reader_mode_ro_query_only` [`query_only=OFF`]; `test_reader_refuses_foreign_ddl`; `test_reader_maps_every_sqlite_error`; `test_reader_distinguishes_busy`; `test_export_seq_monotone_and_newest_wins`; ☆ **`test_newest_export_name_filter[daily_export,hwm_export,hwm_reset_record_ignored,other_venue_export_ignored,unknown_name_unreadable,tmp_16hex_ignored,tmp_non_hex_unreadable]`** [ignore unknown names] | unit |
| same | 7c | `test_child_d0_and_trial_prefix_pinned[store]`; `test_drill_close_restore_at_most_one_per_venue_per_day`; `test_drill_close_restore_refused_for_drill_child`; `test_root_admit_exempt_from_d0_rule` | unit |
| same | 7d | ☆ `test_bootstrap_seed_genesis_only` (from 6e); ☆ `test_store_refuses_second_bootstrap_per_venue` (from 6e); ☆ `test_drill_mint_not_counted` (from 7c); `test_mint_unlimited_by_k_max_but_one_per_day`; `test_hwm_reset_store_refuses_carried_counters_below_export[validate]`; `test_validate_refuses_family_not_introduced` | unit |
| `/home/jon/breezy/tests/unit/test_registry_hwm.py` | 7e | `test_hwm_reading_from_bytes_maps_none_to_absent_and_garbage_to_unreadable`; `test_hwm_absent_construction_only_in_hwm_module`; `test_hwm_mid_chain_hash_mismatch_regressed` [compare head only]; `test_registry_hwm_refuses_regression`; `test_hwm_export_seq_above_newest_regressed`; `test_next_hwm_is_head_and_verified_export`; `test_hwm_seq_zero_and_negative_refused`; `test_hwm_at_head_compares_last_row` [index `rows[venue_seq]`]; `test_hwm_check_unknown_reading_type_is_unreadable`; ☆ **`test_hwm_write_never_lowers`** [drop the `export_seq` comparison]; ☆ `test_autonomy_exec_keys_disjoint_from_halt_prefixes` (from 3c; V36) | unit |
| `/home/jon/breezy/tests/unit/test_lineage_policy_allowlist.py` (AUT-5 WP9 file) | 8a | `test_lineage_policy_allowlist_is_literal_only`; `test_child_requires_lineage_triple_and_policy_ruling`; `test_child_with_operator_ruling_refused`; `test_tampered_policy_ruling_refuses_child`; `test_lineage_gate_refuses_missing_ruling_file`; `test_lineage_gate_refuses_ruling_symlinked_outside_subtree`; `test_lineage_gate_refuses_child_id_outside_root_lineage`; `test_lineage_decision_carries_no_permit_semantics`; `test_verify_ruling_file_extraction_keeps_reasons_and_messages` | unit |
| `/home/jon/breezy/tests/unit/test_registry_replay.py` | 8b | `test_resolver_replays_validate_over_full_fold`; `test_forged_promote_without_resolvable_cause_refused`; `test_artefact_bytes_must_equal_row_sha_at_resolve`; `test_replay_refuses_carried_counters_below_prior_fold`; `test_replay_maps_fold_invalid_to_replay_invalid` | unit |
| `/home/jon/breezy/tests/unit/test_registry_resolver.py` | 8c | unchanged from r4: `test_resolver_binds_bytes_to_row`; `test_registry_paths_refuse_symlinks`; `test_verify_and_load_share_bytes[resolver]`; `test_child_manifest_equals_committed_root_except_allowlist`; `test_exit_gate_stays_code_only`; `test_registry_champion_requires_live_orders_gate_for_every_kind[resolver]`; `test_resolver_refusals_give_no_champion`; `test_root_resolves_under_live_orders_allowlist`; `test_rollback_to_root_reads_content_addressed_copy`; `test_family_source_registry_requires_bootstrap`; `test_node_relaunch_rule_family_id_and_seq_prefix[resolver]`; `test_child_d0_and_trial_prefix_pinned[resolver]`; `test_rollback_to_earlier_child_passes_d0_rule`; `test_resume_not_subject_to_d0_rule`; `test_root_admit_requires_own_allowlist_triple[resolver]`; `test_resolver_under_budget`; `test_resolver_refuses_chain_with_unenabled_widening_row`; `test_hwm_absent_with_rows_refuses`; `test_hwm_absent_on_genesis_only_chain_refuses`; `test_hwm_unreadable_refuses`; `test_export_absent_after_hwm_saw_export_refuses`; `test_export_dir_listing_error_is_export_unreadable`; `test_no_export_means_newest_export_seq_zero`; `test_clock_before_head_refuses`; `test_two_senders_is_engine_inconsistency`; `test_manifest_identity_must_match_row`; `test_live_gate_routing_reads_manifest_kind`; `test_equality_covers_new_manifest_fields`; `test_halted_sender_resolves_with_entries_disallowed`; `test_resolver_never_returns_enabled_or_permit`; `test_draft_or_unpinned_manifest_refused`; `test_resolver_runs_prereg_check_on_source_dir`; `test_missing_manifest_dir_is_manifest_unreadable`; `test_root_record_identity_checked`; `test_root_manifest_must_equal_committed_bytes`; `test_root_named_like_child_is_not_routed_as_child`; `test_child_regex_root_must_equal_lineage_root`; `test_resolved_family_carries_arch_c5_pickup_fields`; `test_resolved_family_hwm_equals_next_hwm`; `test_admissibility_predicate_shared[resolver]`; `test_resolve_refuses_non_canonical_stage`; `test_root_ruling_reasons_map_to_live_orders_refusal` | unit |
| same | 8d | `test_shadow_resolution_ignores_hwm_and_cannot_send` (☆ adds check (v), the step set); `test_paths_role_mismatch_both_directions`; `test_shadow_day2_without_export_refuses`; `test_resolve_private_rejects_skip_hwm_on_production_paths` | unit |

**AUT-5 r7 WP1/WP2 crosswalk.** The counts are unchanged; r5 only moves tests between ARCH-0 seams. WP1 has 85 tests: 66 real, 7 split and 12 moved. WP2 has 16: 10 real, 3 split and 3 moved.

| AUT-5 r7 list (count) | Real | Split (real half / owner half) | Moved |
|---|---|---|---|
| WP1 envelope (6) | 6 | — | — |
| WP1 store (26) | 17 | 4: `test_repeat_supersede_same_family_is_not_replay` [arch0 / store→WP1b]; `test_nomination_columns_required_and_read_by_k_check` [columns_required / k_check→WP1b]; `test_child_d0_and_trial_prefix_pinned` [all real]; `test_hwm_reset_store_refuses_carried_counters_below_export` [validate / store→WP8] | 5 → WP1b: `test_nomination_refused_past_k_max_lifetime`, `test_nomination_refused_second_in_window`, `test_alpha_index_never_resets`, `test_two_pending_nominees_get_distinct_k`, `test_infeasible_nomination_charges_no_alpha[store]` |
| WP1 fold (25) | 24 (☆ 9 in 7a, 4 in 7b, 11 in 7c); the split's real half `[validate]` is in 7d | 1: `test_root_admit_only_when_venue_has_no_sender` [validate / engine→WP4] | — |
| WP1 replay (4) | 4 | — | — |
| WP1 demand (7) | 3 | 1: `test_producer_demand_write_is_restrictive_only` [writer_api / aut6_producer_ast] | 3 → WP4: `test_demand_archive_*` |
| WP1 single read, writer, plug-ins, ledger (5) | 5 | — | — |
| WP1 pins and closure (8) | 6 | 1: `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key` [pins / policy→WP3] | 1 → WP3: `test_policy_map_not_looser_than_fallback_map` |
| WP1 E-7/E-8 (4) | 1 | — | 3 → AUT-5a: the `submit_intent_record` tests |
| WP2 resolver (11) | 8 | 2: `test_verify_and_load_share_bytes` [resolver / loader→WP5]; `test_registry_champion_requires_live_orders_gate_for_every_kind` [resolver / engine→WP4] | 1 → AUT-5a: `test_containment_checks_read_directory_not_phantom_base` |
| WP2 entry guard (5) | 2 | 1: `test_rung_net_position_veto_crosses_legs_and_families` [double / adapter_reader] | 2 → AUT-5a: `test_entry_guard_exact_key_reads_only`, `test_fill_reader_production_default_runs_once` |

AUT-5 r7 WP9's RED list has 7 tests. Four ship green in 8a. WP9 keeps `test_lineage_policy_allowlist_has_exactly_one_row`, `test_lineage_allowlist_row_equals_policy_pin` and `test_root_keeps_own_ruling`.

**Carried strict-xfail stubs** go in `/home/jon/breezy/tests/unit/test_autonomy_cross_area.py` (seam 4b) unless another file is named. `[blocks]` is in brackets.

| Owner | Tests [blocks] |
|---|---|
| AUT-5 WP1b | the 5 moved nomination tests and `test_nomination_columns_required_and_read_by_k_check[k_check]` [PROMOTE]; `test_repeat_supersede_same_family_is_not_replay[store]` [SUPERSEDE, PROMOTE]; `test_prelaunch_writes_rollback_and_activate_atomically[store_atomic]` [ROLLBACK, ACTIVATE]; `test_resume_admission_reads_policy_block_bounds` [RESUME] |
| AUT-5 WP3 | `test_policy_block_not_looser_than_code_ceilings`; `test_promote_disabled_when_eta_after_kill`; `test_policy_map_not_looser_than_fallback_map`; `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[policy]` [PROMOTE] |
| AUT-5 WP4 | unchanged from r4 (the 33 engine and verdict tests, the 3 `test_demand_archive_*`, `test_holdout_opens_cache_has_named_writer`) [ROOT_ADMIT; ACTIVATE] |
| AUT-5a (WP2, WP5–WP8, WP10) | everything in r4's AUT-5a row, unchanged (including `test_l1_cutover_hwm_write_slot_ends_by_164455`, `test_l1_cutover_writes_initial_hwm_under_exec_flock`, `test_node_writes_hwm_at_boot_before_first_entry`, `test_watch_actor_applies_admitted_prefix_then_vetoes`, `test_watch_actor_export_seq_never_lowered`, `test_supervisor_busy_retry_only_at_launch`, `test_adapter_reader_fixtures_written_through_record_fill`, `test_admissibility_predicate_shared[watch_actor]`), **plus, new in r5:** `test_l1_cutover_lock_acquired_at_164454_aborts`, `test_l1_cutover_late_write_completion_aborts`, `test_l1_cutover_abort_leaves_no_key_and_no_registry` (A5-R1); `test_write_monotone_skips_stale_boot_write_after_tick` (A5-R2 store binding); `test_watch_actor_refused_ticks_idempotent` (A5-R4); `test_shadow_bootstrap_creates_export_dir` (A5-R10). HWM-reset group, unchanged: `test_hwm_reset_cli_journals_alerts_and_chains`, `test_hwm_reset_cannot_unhalt`, `test_hwm_reset_never_refunds_counters`, `test_resolver_resolves_after_hwm_reset`, `test_hwm_reset_store_refuses_carried_counters_below_export[store]`, `test_hwm_absent_after_attest_clears_via_reset_cli`, `test_hwm_reset_requires_expected_head` [HWM_RESET] |
| AUT-5 WP11 + AUT-2 | `test_drawdown_producer_handshake_with_labels`; `/home/jon/breezy/tests/unit/test_drawdown_producer.py::test_drawdown_gates_on_labels_consumable`; `test_detectors_and_drawdown_include_drill_fills[drawdown]` |
| AUT-6 | unchanged from r4 (22 tests, including the three E-11 renamed tests) |
| AUT-2 | unchanged from r4 (8 tests) |
| AUT-4 | `test_window_cap_below_n_min_is_inconclusive`, `test_infeasible_nomination_charges_no_alpha[verdict]`, `test_calibration_leg_relative_inconclusive_below_min_buckets` |
| AUT-3 | `test_own_outcome_effect_not_vacuous`, `test_own_outcome_refused_below_min_gate_decisions`, `test_refit_writes_only_fresh_sha_dir` |
| AUT-1 and the plug-in owners | `test_every_exit_fill_joins`, `test_decision_id_unique_per_take`, `/home/jon/breezy/tests/unit/test_autonomy_plugins.py::test_every_non_retired_manifest_resolves_to_full_plugins` with params `[capture]` AUT-1, `[scorer]` AUT-2, `[evaluator]` AUT-4, `[detectors]` AUT-6, `[refitter]` AUT-3 |
| AUT-7 | unchanged from r4 (9 tests) [ROLLBACK; RESUME for the last] |

**Existing tests that pass unmodified after every seam commit:**
- `test_operator_control_assignment_scan`, `test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`;
- `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring`, `test_risk_engine_ordering_enforcement`;
- `test_fq_live_orders_gate.py`, `test_fq_s8_registration_artefacts.py`, `test_family_manifest.py`;
- `test_runtime_import_isolation.py` (its test bodies), `test_forecast_quantile_ladder_manifest_and_markers.py`.

Coverage is reported per seam. No threshold is invented.

## Work Packages (split into 2–4 commit-sized, independently-gated WPs with order; each seam ≤ ~1,000 changed lines)

**Sizing (A-R5, A4-R10, re-summed in r5 from the table rows).**
- 8 WPs, 27 seam commits.
- About 6,710 changed lines in `src/` plus 12,485 in tests, fixtures and stubs, about 19,195 in total.
- The largest seams are 950 lines (5a, 8c), and every seam is ≤ 1,000.

The r4 → r5 changes:
- `src/` +70: 6f +30 for the export-name filter; 7e +40 for `write_monotone_decision`.
- Tests +185 net: 3a +10, 3c −20, 4b +60, 6a −20, 6b +15, 6c +20, 6e −60, 6f +50, 7a −100, 7b +40, 7c +35, 7d +75, 7e +80.

**Wave-0 wall clock.** The schedule is unchanged. 27 merges × 23–25 min of gate is 621–675 min (10.4–11.3 h) of serial gate time, which is the floor. The live seams 1a, 1c and 8a also have to fall outside [16:30Z, 17:10Z).

| Seam | Content | Imports (ARCH-0) | src + test | Activation |
|---|---|---|---|---|
| **1a** | Delete the facade; `entry_points.py`; import-free tests; AC 4 evidence | — | 150 + 450 = 600 | **Live** |
| 1b | Golden corpus on unsplit code; coverage evidence | — | 0 + 700 = 700 | Test only |
| **1c** | `parse_family_manifest` split; import-set pin | — | 120 + 80 = 200 | **Live** |
| 2a | `canonical`, `wire`, autonomy `__init__`; contracts (a), (b), (c) | wire ← canonical | 400 + 450 = 850 | None |
| 2b | `single_read`; classification, runtime and planted-(c) tests | — | 360 + 480 = 840 | None |
| 3a ☆ | `paths` (without `root_record`), `pins`, `veto`; AC 31 tests via `REPO_ROOT` and the named base ref | paths ← wire | 350 + 360 = 710 | None |
| 3b | `plugin`, `closure_manifest`, `closure`, regen script, `node_plugins`, `offline_plugins` | plugin ← veto; closure ← single_read | 250 + 250 = 500 | None |
| 3c ☆ | `net_position`, `entry_guard`; key and side contracts | entry_guard ← net_position, veto | 260 + 500 = 760 | None |
| 4a | Ledger, floor, envelope manifest, writer table, gate and envelope scans, launch-window test | pins | 0 + 900 = 900 | None |
| 4b ☆ | Carried stubs (+6 AUT-5a) | — | 0 + 760 = 760 | None |
| 5a | `verdict`, `lineage`, `label_schema` | wire, canonical, single_read, paths, pins | 450 + 500 = 950 | None |
| 5b | `demand`, `drill_marker`, `rollback_journal` | same | 400 + 450 = 850 | None |
| 6a ☆ | `schemas`, `chain` | schemas ← wire, canonical, rollback_journal; chain ← canonical, schemas | 400 + 430 = 830 | None |
| 6b ☆ | Structural `fold`, `transitions` + `rows_admissible` | fold ← schemas, pins; transitions ← fold | 400 + 465 = 865 | None |
| 6c ☆ | `stage_policy`; construction ban (with exemption-row control); one-home test; acyclic test | stage_policy ← transitions, pins, schemas | 80 + 440 = 520 | None |
| 6d | `family_bytes`, `paths.root_record`, `write_root_copy`. **Precondition: E-14 filed** | single_read, paths, lineage, schemas, family_manifest | 320 + 470 = 790 | None |
| 6e ☆ | `registry_store`: DDL, triggers, writer, `append`/`_append` | chain, transitions, fold, stage_policy, family_bytes | 380 + 460 = 840 | None |
| 6f ☆ | `registry_store`: `RegistryReader`, `write_export`, `newest_export` with the name filter | same module | 250 + 430 = 680 | None |
| 7a ☆ | Full `fold`: states, pairs, voiding, freezes, drill episodes | schemas, pins | 300 + 300 = 600 | None |
| 7b ☆ | `LineageTallies`/`VenueTallies`; `origin`; `FoldInvalid` | same | 200 + 390 = 590 | None |
| 7c ☆ | `validate` I: drill, RESUME, E-5, d0/prefix | fold | 280 + 415 = 695 | None |
| 7d ☆ | `validate` II: Z3, ROOT_ADMIT/BOOTSTRAP, introducers, mint, ATTEST, SWAP_CANCEL, single sender, HWM_RESET floors | fold | 240 + 495 = 735 | None |
| 7e ☆ | `hwm`, including `write_monotone_decision` | wire, schemas, chain | 200 + 460 = 660 | None |
| **8a** | `live_orders_gate` extraction and lineage gate | family_manifest | 120 + 450 = 570 | **Live** |
| 8b | `replay` | transitions, fold, verdict, chain, family_bytes | 250 + 400 = 650 | None |
| 8c | Sending resolver (step 1 in the public entry); `ResolvedFamily`, `ResolverRefusal`. Merges after the post-8a node relaunch | all + live_orders_gate, hwm | 400 + 550 = 950 | None until AUT-5a |
| 8d | Shadow resolver (explicit step set), `ShadowResolution`, private-entry assertion; final contract lists | resolver | 150 + 450 = 600 | None |

**Live-path activation (1a, 1c, 8a).**
- Merge outside [16:30Z, 17:10Z).
- The node picks up the change at its next 16:50Z LAUNCH. The supervisor restarts in 01:00–16:40Z, and `KillMode=process` keeps the node.
- Recorder and ingest pick it up at their next natural start. The stated technical reason for not forcing those restarts: the AC 4 evidence proves behaviour is unchanged, and a recorder restart costs capture continuity.
- AC 30 covers mixed versions. Revert is one file per seam.

**Early-start points (A3-R5).** Unchanged from r4.

| Wave-1 area | May build against frozen signatures after | Consuming WP may merge only after |
|---|---|---|
| AUT-1a | 5b | 5b; `ResolvedFamily.registry_seq` reads after 8c |
| AUT-2a | 5b | 5b; `LegFill` after 3c; AUT-2's `CostedFill` lands in AUT-2 |
| AUT-3a | 5b | 5b; fold reads after 7a; refits into a fresh `<sha>/` only |
| AUT-4a | 5b | 5b; `LineageTallies` reads after 7b; `holdout_opens` only after AUT-5 WP4 |
| AUT-6 | 5b | 5b; fold consumption after 7a |
| AUT-5a | 8d | 8d; WP1b work after 7d; ☆ `write_monotone` after 7e |
| AUT-7a | 8d | 8d (`verify_family_bytes`, `append`, journal) |

### WP brief invariants (prepend verbatim to every WP brief)

> I-1 Nautilus Trader is immutable: never modified, patched, forked or bypassed. I-2 Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code; no brief or code names their environment variables (L-39). I-3 Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched; the resolver never yields permit semantics (no `enabled` field, `permit_present=False`, only `permit_absent` accepted). I-4 `allow_short` stays `False`. I-5 No safety, settlement or contract test is weakened or deleted; listed tests pass unmodified; mypy ceilings are only lowered. I-6 `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (sha256 `76784ce814797bfb5480487ff0dad47cbe9c0b1727aef9ad1c7461cc33aa68a4`) is never edited. I-7 Interpreter `/home/jon/breezy/.venv/bin/python` only; never `uv`, `pip` or any installer; never `git stash`; in a worktree set `PYTHONPATH=<worktree>/src`, fast-forward onto `feat/data-capture-and-risk` first, and snapshot untracked files to your own scratchpad. I-8 `cd <tree> && .venv/bin/lint-imports` must print "N kept, 0 broken"; run `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh` and read its exit code explicitly before any push. I-9 Commit by explicit path only, one seam per commit, RED→GREEN logs attached; codegraph first (`projectPath=/home/jon/breezy`).

### WP briefs

Each brief is the coordinator's dispatch skeleton. It is seeded with the matching agent and skill and with `projectPath=/home/jon/breezy`, and the invariant block above is prepended verbatim.

**Placement STOP rule (A5-R5), common to WP-2 to WP-8.** Before writing a test, confirm that the code it exercises lands in this seam or an earlier one. If it does not, stop and report it. The coordinator then moves the test to the seam that lands that code.

- **WP-1 (1a, 1b, 1c): live-path prep.**
  - RED: `test_persistence_has_no_facade_consumers` (planted control), `test_parse_split_matches_presplit_golden` (green on unsplit code, then unchanged), `test_live_path_modules_import_set_pinned`.
  - Evidence:
    - the grimp and per-entry `_SCHEMAS` diffs;
    - `coverage run --branch` at 100% of `family_manifest.py:262-282` and `:285-460`;
    - an empty `diff` of the moved constants and helpers against `git show d231497d:tests/unit/test_runtime_import_isolation.py` lines 55-60 and 158-190, plus the single parameter hunk for `:192-216`;
    - a `git diff` with no `def test_*` and no `assert` line changed;
    - the `test_mypy_ratchet` output.
  - Stop if any entry's arrow set differs without a reviewed reason.
- **WP-2 (2a, 2b): bytes and I/O.**
  - RED: the goldens, `test_read_refuses_fifo_without_blocking`, `test_write_once_exists_equal_creates_no_temp`, `test_write_once_new_file_in_owner_readonly_dir_refused`, `test_contract_c_refuses_planted_pyarrow_reach[canonical]`.
  - Contract source lists name modules only (V23).
- **WP-3 (3a, 3b, 3c): pins, plug-ins, guard.**
  - RED: `test_veto_reason_closed_set_equals_arch`, `test_bootstrapped_root_manifests_unchanged` (planted wrong sha), ☆ `test_bootstrapped_root_pin_is_append_only` (unavailable base ref FAILS; absent-at-base reads as empty), `test_fill_index_key_matches_exec_client_writer` (mutation: change `"^no"`), `test_fill_row_side_vocabulary_matches_exec_record_signs`, `test_leg_fill_fields_frozen`.
  - ☆ AC 31 tests hash through `entry_points.REPO_ROOT`, never an absolute path.
  - The exec client is read by AST only (`:412`, `:663`, `:668-671`).
- **WP-4 (4a, 4b): ledger and envelope.**
  - Verify R13 (`TimeoutStartSec`) first.
  - RED: `test_owner_placeholder_ledger_matches_markers` (planted mismatch), `test_every_envelope_node_id_collected_and_unskipped` (planted skip).
  - ☆ 4b carries the six new AUT-5a stubs.
- **WP-5 (5a, 5b): records.**
  - First check the ARCH C4 fields for any non-integer JSON number. If one exists, stop and raise it.
  - RED: `test_differing_body_same_id_refused` (mutation: drop the EEXIST compare).
- **WP-6 (6a to 6f): store core.**
  - `schemas` imports only `wire`, `canonical` and `rollback_journal`, including under `TYPE_CHECKING`.
  - 6d waits for E-14 to be filed.
  - RED: `test_contract_c_refuses_planted_pyarrow_reach[schemas]`, `test_schemas_holds_no_pyarrow_reaching_type`, `test_rows_admissible_stops_at_first_refused_widening_row`, `test_autonomy_policy_not_mutable_from_src` (every planted form), `test_admissibility_predicate_shared[store]`, `test_first_row_venue_seq_must_be_one` (mutation: drop COALESCE), `test_reader_distinguishes_busy`, `test_refit_into_root_sha_dir_fails_closed`, ☆ `test_newest_export_name_filter` (mutation: ignore unknown names).
  - ☆ The bootstrap tests are **not** in 6e (A5-R5). Apply the STOP rule to `test_family_artefact_binding_immutable`.
- **WP-7 (7a to 7e): fold, tallies, rules, HWM.**
  - RED: the explicit 7a–7d lists, `test_family_introduced_by_other_kind_is_invalid`, `test_lineage_tallies_fields_equal_arch_counters_minus_non_derivable`, `test_hwm_at_head_compares_last_row` (mutation: index `rows[venue_seq]`), `test_hwm_seq_zero_and_negative_refused`, `test_hwm_mid_chain_hash_mismatch_regressed`, ☆ `test_bootstrap_seed_genesis_only`, `test_store_refuses_second_bootstrap_per_venue` and `test_drill_mint_not_counted` (7d), ☆ `test_hwm_write_never_lowers` (7e; mutation: drop the `export_seq` comparison).
- **WP-8 (8a to 8d): lineage gate, replay, resolver.**
  - 8a is live-path and needs the ruling-site coverage evidence.
  - 8c merges only after a post-8a node relaunch (AC 30).
  - ☆ Step 1 is coded in `resolve_sending_family`, not in `_resolve`. The 8d shadow step set is {0, 2, 3, 5, 6, 7, 8}.
  - RED: `test_root_manifest_must_equal_committed_bytes`, `test_root_named_like_child_is_not_routed_as_child`, `test_resolved_family_carries_arch_c5_pickup_fields`, `test_resolved_family_hwm_equals_next_hwm`, `test_no_export_means_newest_export_seq_zero`, `test_shadow_resolution_ignores_hwm_and_cannot_send` (☆ including the step-set spy), `test_shadow_day2_without_export_refuses`, `test_resolve_private_rejects_skip_hwm_on_production_paths`, `test_hwm_absent_on_genesis_only_chain_refuses`, `test_resolver_refuses_chain_with_unenabled_widening_row` (hand-forged chain).

## Binding note for the AUT-5a brief

The coordinator copies this section into the AUT-5a brief verbatim. ☆ marks r5 changes.

1. **WP1b (admission completion)** is a named AUT-5a WP, scheduled before AUT-5 WP10 L1. Its scope:
   - (a) thread the policy block's stricter values into `validate`; the ceilings stay the bound;
   - (b) nomination k-checks, replacing `NominationRequiresPolicy`. These must agree with the fold-derived `LineageTallies.nominations`, `infeasible_nominations` and `alpha_spent` (AC 14); a semantic change needs an erratum.
     - ☆ **Open question (A5-R8, arch N5):** the plan defines `nominations` as max `k_life` over **feasible** SHADOW→CHALLENGER PROMOTE rows, while ARCH `:431` says "max `k_life`". WP1b decides whether `k_life` also counts infeasible nominations. If the two definitions differ, a coordinator erratum is owed before WP1b merges.
   - (c) HWM_RESET store admission, with WP8, replacing `RuleSetPending`;
   - (d) a per-kind completeness review against ARCH C5 and AUT-5 r7 §3.2;
   - (e) each kind joins `_ADMISSION_IMPLEMENTED` in the same commit that clears its `blocks_kinds` rows.
2. **The RESUME subset merges before the L1 pins commit `ENABLED_WIDENING_KINDS = {RESUME}`.** It covers the policy-threaded RESUME bounds (`test_resume_admission_reads_policy_block_bounds`) and a re-review of the rules that are already real, and then sets `_ADMISSION_IMPLEMENTED = {RESUME}`. Every other widening kind needs WP1b complete before the L2 flag commit.
3. **`_ADMISSION_IMPLEMENTED` is code, not a pin.** It is read only through `STAGE`. `StagePolicy` is never constructed, replaced, copied or re-typed in `src/` (AC 15). `_append` and `_resolve` refuse a non-canonical stage.
4. **Narrowing.** Narrowing `ENABLED_WIDENING_KINDS` below a kind that already has rows makes resolution refuse. The lever is `breezy-registry-hwm-reset` plus a reviewed commit, never a narrowing commit.
5. **`_tick_once`** calls `adm = transitions.rows_admissible(new_rows, stage=STAGE)` before `validate`, row by row in chain order. On a refusal:
   - it applies `new_rows[:adm.admitted]`, so every restrictive row before the refused row takes effect in the in-memory fold;
   - it sets `registry_unreadable`, raises CRITICAL `REGISTRY_REGRESSED`, and does not advance the HWM (`test_watch_actor_applies_admitted_prefix_then_vetoes`, `test_admissibility_predicate_shared[watch_actor]`).
   - ☆ **Re-read rule (A5-R4, security N4).** Each tick re-reads from the **last verified seq**. The in-memory fold for a tick is always recomputed from the fold at that seq plus the admitted prefix. It is never accumulated on top of a previous refused tick, so the prefix is never applied twice and the refused row is re-evaluated. Use a pure recompute, never `copy.*`, which the AC 15(ii) ban covers. Two consecutive refused ticks over the same rows produce an identical in-memory fold (`test_watch_actor_refused_ticks_idempotent`).

   The engine appends restrictive rows in batches separate from widening rows.
6. **HWM obligations.**
   - (a) **Decoding.** HWM bytes are decoded only through `hwm_reading_from_bytes`.
   - (b) **Node boot.** After `resolve_sending_family` and before the entry-veto slot opens, the node writes `ResolvedFamily.hwm` ☆ **through `hwm.write_monotone` (binding note 6f)**, holding the intent flock (`<exec store>.intent.lock`, V27). It never recomputes the chain or exports.
     - ☆ `SKIP` counts as success, because the stored HWM is already at least as advanced.
     - `REFUSE`, or a failed write, keeps entries vetoed until a tick writes (`test_node_writes_hwm_at_boot_before_first_entry`).
   - (c) **Ticks.** The actor's `export_seq` starts at `ResolvedFamily.hwm.export_seq`, is carried forward unchanged, changes only after a verified `newest_export` call, and is never lowered. Ticks write only `next_hwm` values after a verified read, ☆ always through `write_monotone` under the intent flock (`test_watch_actor_export_seq_never_lowered`).
   - (d) ☆ **L1 cut-over slot (A5-R1, security N1; architect r3 F10).** `/home/jon/breezy/scripts/ops/autonomy_l1_cutover.py`:
     1. **One deadline.** At start, the script reads the wall clock once and computes one monotonic deadline equal to that day's 16:44:55Z. If no time remains, it aborts before taking any lock, so there is no key to delete.
     2. **Slot.** The slot opens when the 16:40:05 bootstrap has exited (≤ 16:41:15) and the node is down (`stop_prior_complete`).
     3. **Bounded acquire.** It takes LOCK_EX on `<exec store>.intent.lock` with a wait of `min(5, deadline − now)` seconds, the same semantics as `flock -w`. On timeout it aborts; the lock was never acquired, so there is no key to delete.
     4. **Re-check after acquire.** After acquiring and before writing, it re-checks the clock against the deadline. If the deadline has passed, it aborts and releases the lock without writing.
     5. **Write onto Absent only.** It reads the key with `hwm_reading_from_bytes`. Any reading other than `HwmAbsent` aborts; the clearing path is the reset CLI (6e). It then writes the initial HWM (genesis head, `export_seq = 0`) through `write_monotone`, inside the same hold.
     6. **Late completion is an abort.** After the write completes, it re-checks the clock. A write that completes after the deadline is an abort.
     7. **Abort delete (carve-out).** On abort after its own write, the script deletes the key **while still holding the lock that wrote it**, then releases. This in-hold delete is the only HWM mutation allowed at or after 16:44:55, and the only delete of the key outside the reset CLI. It returns the key to the Absent state the cut-over found. The 16:45:00 E-8 snapshot, which takes the same flock and releases by 16:48:00, can at worst wait for that delete.
     8. **Rest of the abort, outside the lock:** the production registry is moved aside by rename, the source is reverted, and the supervisor is restarted, each with a one-line heads-up.
     9. **Window rule.** The script never writes an HWM value in [16:44:55, 16:50:00). Step 7 is the single named exception.
     10. **Failed delete.** If the abort delete itself fails, the leftover HWM makes the next cut-over abort at step 5. That fails closed, and the reset CLI clears it.
     11. **Export directory.** The cut-over bootstrap creates `evidence/registry/` (see 9).
     12. **Tests:** `test_l1_cutover_hwm_write_slot_ends_by_164455`, `test_l1_cutover_writes_initial_hwm_under_exec_flock`, ☆ `test_l1_cutover_lock_acquired_at_164454_aborts`, ☆ `test_l1_cutover_late_write_completion_aborts`, ☆ `test_l1_cutover_abort_leaves_no_key_and_no_registry`.
   - (e) **Clearing path (L-48).** `breezy-registry-hwm-reset` (AUT-5 WP8) is the named recovery for `hwm_absent` and `hwm_regressed`, including the case before the first export (`test_hwm_absent_after_attest_clears_via_reset_cli`). The CLI:
     - prints the head hash and every standing DEMOTE and HALT row it is about to accept;
     - requires `--expect-head <hash>`, obtained out of band from the last delivered `REGISTRY_*` alert or export, and refuses on mismatch;
     - refuses when the proposed fold is less restrictive than the fold at the last HWM recorded in a delivered alert (`test_hwm_reset_requires_expected_head`).

     ☆ **It is the only writer that bypasses `write_monotone` (A5-R2).** Its record `evidence/registry/hwm_reset_<ts>.json` is ignored by `newest_export` (AC 17.3).
   - (f) ☆ **Monotone writer (A5-R2, security N2).** AUT-5a adds `write_monotone(store, new, *, held_lock)` to `hwm.py`.
     - It uses stdlib only. `store` is a `HwmKeyStore` Protocol (get, put and delete bytes by key) that the node passes in. Contracts (b) and (c) still apply to `hwm.py`.
     - It requires a held-lock token for `<exec store>.intent.lock` and never takes the lock itself. A second `flock` from the same process on a fresh fd blocks (V35). This also lets the cut-over's write, clock re-check and abort delete share one hold.
     - It re-reads the key through `hwm_reading_from_bytes`, applies ARCH-0's `write_monotone_decision` (AC 16), and writes only on `WRITE`.
     - It is the sole value-writer API for node boot, ticks and the cut-over. The reset CLI is the only bypass.
     - The AUT-5a commit updates the writer-table row.
     - Test: `test_write_monotone_skips_stale_boot_write_after_tick`, which is security's race: a tick writes a higher HWM between the node's resolve and its boot write, and the stale boot write must not lower it.
7. **Shadow source.** Under `registry_shadow`, the supervisor and the watch actor call `resolve_shadow_family` on the `ShadowPaths` root, and they are added to `SHADOW_CALL_SITES` in the same commit. `ShadowResolution` is only logged and never reaches `build_child_env` (`test_shadow_resolution_cannot_reach_build_child_env`). The shadow HWM stays in memory. ☆ The shadow resolver runs steps {0, 2, 3, 5–8} (AC 18).
8. **`RegistryUnreadable.reason`.**
   - Watch actor: `busy` means the tick is unverified and state is unchanged, so three busy ticks reach `registry_unreadable` through `WATCH_TICK_STALE_S` (180 s). The other reasons veto immediately.
   - Supervisor: it may retry a `busy` resolve once, only at LAUNCH, within its LAUNCH budget (`test_supervisor_busy_retry_only_at_launch`).
   - The engine's read-write open rolls back a hot journal.
   - R14 records the up to 180 s DEMOTE-visibility latency under a held lock.
9. **Bootstrap root copies and export directory (E-14; ☆ A5-R10).**
   - `write_root_copy` runs per seed before the genesis COMMIT, then the directories are chmodded 0500. A rerun is EXISTS_EQUAL.
   - ☆ **Every bootstrap, production and shadow (stage S), creates `evidence/registry/` (0700) on its root before the genesis COMMIT** (`test_shadow_bootstrap_creates_export_dir`). Without it, the shadow root gets `export_unreadable` on day 1.
   - The pins commit that fills `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` for every `BOOTSTRAP_SEED` id merges before the first bootstrap on any root, stage S shadow included. A ROOT_ADMIT adds its row in the same commit as its allowlist triple (E-14 rule 7).
   - ☆ From that commit on, the live `forecast_quantile_ladder` root manifest is frozen. Until ROOT_ADMIT is enabled, a reviewed revert is the only clearing path (AC 31).
10. **Other obligations.**
    - Import `VetoReason` from `veto.py`; the `entry_veto` callable type is defined in strategy.
    - Drop the package-wide Nautilus ban (AUT-5 r7 `:841`) in favour of contracts (b) and (c), which list modules only, plus classification.
    - `append` requires `now_ns`.
    - The E-8 decoders belong to AUT-5a, and AUT-6 aliases them.
    - The derived-caches DDL belongs to WP4, which must name the writer of `holdout_opens` (`test_holdout_opens_cache_has_named_writer`).
    - `PolymarketUsFillReader` prefixes ids with the imported `FILL_INDEX_KEY_PREFIX` and returns `FillIndexAbsent` only for a missing key.
    - The `[adapter_reader]` test writes its fixtures through `record_fill` (`client.py:4593`), never by hand (`test_adapter_reader_fixtures_written_through_record_fill`).
    - The guard cache type is `dict[base_slug, GuardResult]`.
    - The node, supervisor and settings consume `ResolvedFamily.family_bytes`, `registry_seq`, `chain_head` and `hwm`, and never re-read.
    - `ResolvedFamily` and `ShadowResolution` are imported from `resolver`, and `FamilyBytes` from `family_bytes`.

## Risk Register

| # | Risk | Evidence | Mitigation / owner |
|---|---|---|---|
| R1 | Root-copy collision | V20 | E-14; 6d waits for it; fail-closed either way |
| R2 | Contract (b) vs E-12; pyarrow reach; package as source | V16, V22, V23 | (b)/(c) split; module-only lists; classification; planted controls |
| R3 | `EntryVeto` name collision | AUT-1 r12 `:433` | No alias |
| R4 | Double halt-decoder extraction | AUT-6 r15 `:1664` | A-R6 |
| R5 | `drill_marker/v1` field sets | AUT-7 r5 `:363` | AUT-7's 12 keys |
| R6 | `net_position` weight; AUT-2 cost basis | V1; AUT-2 r7 `:116`, `:722` | No domain import; `LegFill` netting-only |
| R7 | Facade removal drops a `register_arrow` side effect | V15 | One-time evidence; smoke; one-file revert |
| R8 | WP sizes | Table | 27 seams, each ≤ 1,000 (max 950), each gated; ☆ re-summed to about 19,195 lines |
| R9 | Stale carried test | — | Narrow `OwnerPending`; staleness tests |
| R10 | Early widening via pins | memories | Stage flag; `_ADMISSION_IMPLEMENTED`; shared `rows_admissible`; construction ban; `stage is STAGE` |
| R11 | Concurrent agents | L-51 | Per-WP worktree; re-gate before merge |
| R12 | Gate as uid 0 | `run_tests_no_egress.sh:45-50`; V30 | `stat` modes; `mode=ro`; mode-bit `DIR_NOT_WRITABLE` |
| R13 | Orphaned ingest timer | AUT-6 r15 `:1656` | Verify first in 4a |
| R14 | **Same-uid consistent forgery** | ARCH C5 | Accepted residual. **W1:** a restrictive row appended while no node watches can be rewritten before the next export. The boot HWM write narrows this, and ☆ `write_monotone` stops a stale writer from lowering the HWM (A5-R2). **W2 is closed:** Absent always refuses. **`hwm_absent` is a tripwire against accidental deletion, not a control against a same-uid writer**, which can still write raw bytes or drive the reset CLI. `--expect-head` makes that deliberate. **Demotion latency:** up to 180 s under a held lock |
| R15 | Demand-flood DoS before WP4's archive | security L2 | Fail-closed, restrictive only |
| R16 | Narrowing after rows exist | — | Binding note 4 |
| R17 | Resolver carries about 48 MB of pyarrow | V2 | Accepted |
| R18 | `pins.py` outside `closure_sha256` | security L3 | `live_proof_paths()` (AUT-5 WP4) |
| R19 | Live-path seams 1a, 1c, 8a | security F10 | Merge window; AC 30; 8c after the post-8a relaunch |
| R20 | `HwmAbsent` blocks LAUNCH if the cut-over write fails | AC 16 | Restrictive. ☆ The cut-over computes one deadline, bounds its lock wait, re-checks the clock after acquire and after the write, and aborts with an in-hold key delete (binding note 6d). A failed delete makes the next cut-over abort; recovery is a re-run or the reset CLI |
| R21 | Venue-global intent-veto deadlock | node memory | Documented scope; intent retirement; AUT-6 alert |
| R22 | Entry-point smoke cost | V14 | ≤ 60 s measured in 1a; otherwise restrict by evidence |
| R23 | A committed edit to a bootstrapped root leaves no sender | V28 | E-14 rule 7: pinned bytes plus CI test, ☆ hashed via `REPO_ROOT`, with a named base ref that fails rather than skips. ☆ The test is CI hygiene, and the runtime anchor is `manifest_sha_mismatch`. ☆ Until ROOT_ADMIT is enabled, the only clearing path is a revert; from the stage-S bootstrap on, the live fq manifest is frozen. L-48 row |
| R24 | `holdout_opens` has no C5 row source | V24 | Excluded from tallies; AUT-5 WP4 owns the cache and names its writer, or a coordinator erratum is owed |
| **R25** ☆ | **A `.tmp.<16 hex>` leftover from `write_once` in `evidence/registry/` gives `export_unreadable` under the A5-R6 "any other name" rule, so every sending resolve refuses until the engine sweeps it** | V32; AC 7, AC 17.3 | Fail-closed (restrictive). Clearing path: the engine's `.tmp.` sweep at its next pass (L-48). The ruling is applied as written. **Flagged for the r5 text-verification pass:** whether `.tmp.` names should be known-and-ignored is a coordinator call, not a planner change | **CLOSED by A6-R1.**
| **R26** ☆ | **AC 15(ii) does not reach AUT-3's `analysis/autonomy_refit/`** | V34 | Recorded in (b) item 42. Flagged for coordinator; r5 does not widen the scope | **CLOSED by A6-R2.**

## LESSONS Compliance

Every number was checked against its `/home/jon/breezy/docs/core/LESSONS.md` header on 10-03 (r4). r5 cites no new L-number.

| Lesson | Compliance |
|---|---|
| L-1 | Null-hypothesis rows below |
| L-12 | Exact sets; pure-move split proven by golden + coverage; empty allowlists; HWM refinement; ☆ the export-name filter is an exact set with fail-closed default |
| L-14 | Closed enums derived from ARCH, code and probes, with equality tests; ☆ `HwmWriteDecision` is closed |
| L-16 | No timers; a veto composer exception is `registry_unreadable` |
| L-19 | Facade removal simulated statically and at runtime |
| L-22 | Frozen `STAGE`, construction ban, identity check, private seams; ☆ exemptions only by a reviewed literal row |
| L-24 | Hand-forged chains for the resolver, HWM and introducing-row tests |
| L-29 | No diagnostics buffers; no module-level mutable state |
| L-33 | Mutation evidence per guard test; ☆ `test_hwm_write_never_lowers`, `test_newest_export_name_filter` |
| L-39 | No operator-control env names |
| L-42 | Key and side contracts read the real writer by AST; `[adapter_reader]` fixtures go through `record_fill` |
| L-43 | Full gate after each of the 27 seams; ☆ tests placed so no seam gate is red as written (A5-R5) |
| L-44 | Netting tested at each leg's terminal state |
| L-46 | Contract tests grepped first |
| L-47 | Every new fact has a file:line or a probe (☆ V32–V36; V35 probed). V30 is marked unprobed |
| L-48 | Every refusing latch has a clearing path: `hwm_absent`/`hwm_regressed` → reset CLI or cut-over abort; intent veto → retirement; root-manifest edit → revert (ROOT_ADMIT only once enabled); ☆ `.tmp.<16 hex>` names ignored (A6-R1); ☆ HWM `REFUSE` → reset CLI |
| L-50 | Writer table plus write-once; ☆ HWM value writes only through `write_monotone` |
| L-51 | Exact interpreter; no `uv`, `pip` or `stash` |
| L-54 | Pin search done; `entry_points.py` owns the constants; ceilings only lowered |
| L-55 | `[adapter_reader]` runs the production `FillReader` once (AUT-5a) |

**L-1 null-hypothesis rows.** Unchanged from r4.

| Need | Existing capability | Verdict |
|---|---|---|
| C5 store | SQLite + triggers (V4, V11) | Native |
| Exact-set records | stdlib `json` hooks | Reuse |
| Atomic files | `os.link`/`os.replace` via dirfds | Stdlib |
| Single read | Nothing in Nautilus | Build (small) |
| Read-only reader | SQLite `mode=ro` | Reuse |
| Resolver checks | `live_orders_authorized`, `load_family_manifest` | Reuse by extraction and split |
| Netting | `DurableFillRecord` + `_RECORD_SIGNS` | Restate, contract-tested |
| C6 | Protocols | Build |
| Closure | grimp | Reuse, gate-only |
| Journal | write-once | Build |
| Import isolation | `runtime/__init__` precedent | Reuse |
| Arrow evidence | Nautilus `_SCHEMAS` | Reuse, read-only |
| Contract checks | import-linter | Reuse |
| ☆ HWM write serialisation | Existing exec intent flock (V27) | Reuse; no new lock |

## Trade-offs (options considered, evidence, choice)

| Decision | Options | Choice and evidence |
|---|---|---|
| `persistence/__init__` | lazy PEP 562; delete | **Delete** (V3) |
| Reachability proof | grimp gate test; one-time evidence + smoke | **One-time evidence + permanent smoke** |
| `HwmAbsent` on genesis | allow; always refuse | **Always refuse**, with named clearing paths |
| Shadow resolution | flag; separate function and type | **Separate function and type**; ☆ explicit step set |
| Root or child | regex; chain `origin` | **Chain origin** |
| Root manifest source | either directory; committed only | **`deploy/families` only, REPO**, frozen after bootstrap |
| Entry-guard key | full key; ids + adapter prefix | **Ids + AST contracts** |
| Pyarrow-reaching result types | `schemas` + `TYPE_CHECKING`; Protocol only; move | **Move** to `resolver`/`family_bytes` |
| Contract source lists | package; module names | **Module names** (V23) |
| `StagePolicy` location | `stage_policy.py`; `schemas.py` | **`schemas.py`** |
| Store admission check | inline; shared predicate | **Shared `rows_admissible`** |
| HWM export seq source | node re-reads; `ResolvedFamily.hwm` | **`ResolvedFamily.hwm` + `verified_export_seq`** |
| AUT-4 tally source | WP4 cache; fold | **Fold for 13 + 2 fields; `holdout_opens` from WP4** |
| `LegFill` cost | add cost; netting-only | **Netting-only** |
| Root manifest edits | allow; freeze | **Freeze** |
| 0500 directory writes | rely on EACCES; mode bit | **Mode bit** |
| ☆ HWM writer ordering | last-writer-wins; monotone helper | **Monotone helper**; pure decision in ARCH-0, store binding in AUT-5a (A5-R2) |
| ☆ Lock ownership for HWM writes | helper takes the lock; caller holds the lock | **Caller holds** (V35); one hold covers the cut-over write, re-check and abort delete |
| ☆ Export listing | fail on any unknown name; venue-scoped filter with known ignores | **Venue-scoped filter**; reset records and other venues ignored; anything else fail-closed (A5-R6) |
| ☆ StagePolicy ban vs consumers | narrow by type; blanket + reviewed exemption rows | **Blanket + exemption rows** (A5-R9; AST cannot see types) |
| Lineage-gate placement | WP-1; before resolver | **8a** |
| Fold-decidable rules | defer; implement | **Implement** |
| Derived caches | ARCH-0; WP4 | **WP4** |

## Confidence Self-Assessment (HIGH|MEDIUM|LOW + explicit unknowns)

**HIGH for design; MEDIUM-HIGH for schedule.**
- r5 applies A5-R1 to A5-R11 as text. It makes no design change beyond them.
- The architect's feasibility score of 7 was driven by arch N1 (tests placed before their code). A5-R5 fixes that, and the r5 audit found and fixed five more misplacements (V36).
- Under A5-R11, the scope score of 6 is accepted as structural, because scope is fixed by frozen ARCH §5.1 Wave 0. r5 gets a single text-verification pass, not a full review.

Unknowns:
1. E-14, including rule 7 and its r5 clarification, must be filed before 6d.
2. The entry-point smoke time is measured in 1a.
3. Corpus size is decided by coverage, not by count.
4. `CAUSE_CODES` and `DEMAND_REASONS` are closed choices.
5. Ingest `TimeoutStartSec` is checked in 4a.
6. A C4 non-integer JSON field stops 5a.
7. AUT-5a must accept binding notes 1 to 10. (r4 said "5 to 11"; note 11 does not exist.)
8. The `holdout_opens` writer is unnamed (R24).
9. uid-0 DAC behaviour is unprobed (V30). The design does not depend on it.
10. The runtime of `test_contract_c_refuses_planted_pyarrow_reach` is unmeasured; it is marked `heavy`.
11. ☆ R25: CLOSED by A6-R1 (`.tmp.<16 hex>` ignored).
12. ☆ R26/V34: CLOSED by A6-R2 (scope covers every `autonomy*` package).
13. ☆ The subject of `test_family_artefact_binding_immutable` is not specified in AUT-5 r7 beyond its name. It stays in 6e under the WP-6 STOP rule.
14. ☆ The WP1b `nominations` definition question (binding note 1b).

## §R5 Disposition

| Finding | Ruling | Disposition | Where |
|---|---|---|---|
| Security N1 (MED): cut-over can lock and write after 16:44:55; abort delete is a late write | A5-R1 | FIXED: one monotonic deadline; `min(5, remaining)` wait; clock re-check after acquire and before the write; late completion aborts; in-hold delete carve-out; never acquired means no key; three tests | Binding note 6d; carried AUT-5a stubs; (b) 26; R20 |
| Security N2 (MED): boot HWM write not monotone | A5-R2 | FIXED: pure `write_monotone_decision` + `HwmWriteDecision` in 7e (`test_hwm_write_never_lowers`); `write_monotone(store, new, *, held_lock)` is an AUT-5a obligation and the sole writer API; the reset CLI is the only bypass; the cut-over writes onto Absent. Reconciled with A5-R1: the cut-over's in-hold abort delete is the single named delete | AC 16; binding note 6b, 6c, 6d, 6e, 6f; writer table; Stub owner row; Modules; (b) 14, 17, 26; R14 |
| Security N3 (LOW): append-only test only as strong as its base | A5-R3 | FIXED: named base ref `origin/feat/data-capture-and-risk` merge-base (V33); unavailable or shallow FAILS; absent at base → empty; CI hygiene, not a control; runtime anchor `manifest_sha_mismatch` | AC 31; R23; WP-3 brief |
| Security N4 (LOW): tick re-read after refusal | A5-R4 | FIXED: re-read from the last verified seq; pure recompute; `test_watch_actor_refused_ticks_idempotent` | Binding note 5; carried stub; (b) 13 |
| Architect N1 (MED): tests placed before their code | A5-R5 | FIXED: the three named moves to 7d, plus five audit moves (V36); 7a–7d fold lists made explicit; placement STOP rule in the briefs | Test Strategy; WP table; WP briefs |
| Architect N2 (MED): export listing filter unspecified | A5-R6 | FIXED: venue-scoped regex as ruled, confirmed against AUT-5 r7 `:173`, `:189`, `:485`, `:487` (V32); `hwm_reset_*.json` and other-venue exports ignored; any other name → `export_unreadable`; 6f test; `.tmp.` side effect flagged (R25) | AC 17.3; Modules; Edge table; writer table; (b) 45 |
| Architect N3 (LOW): step 1 vs shadow | A5-R7 | FIXED: step 1 lives in the public sending entry only; AC 18 states the shadow step set {0, 2, 3, 5–8} with 4 skipped and 9–12 not run; spy check (v) | AC 17, 18; Modules; WP-8 brief |
| Architect N4a/b/c (LOW): AC 31 absolute path, base ref, liveness | A5-R3 | FIXED = security N3; `entry_points.REPO_ROOT`; revert-only until ROOT_ADMIT; fq manifest frozen from stage S | AC 31; binding note 9; E-14 rule 7 (r5 sentence); R23; L-48 |
| Architect N5 (LOW): `nominations` vs ARCH "max `k_life`" | A5-R8 | RECORDED as a WP1b question; erratum owed if they differ | Binding note 1b; AC 14 |
| Architect N6 (MED): ban collateral for consumers | A5-R9 | FIXED: blanket ban kept; exemption = reviewed literal row in the consumer's commit; (b) items for AUT-3, AUT-4, AUT-6. AUT-3 `:137` sits outside the scope as written (V34), flagged | AC 15; (b) 42–44; R26 |
| Architect N7 (LOW): shadow root has no export directory | A5-R10 | FIXED: every bootstrap creates `evidence/registry/`; `test_shadow_bootstrap_creates_export_dir` | Binding notes 6d, 9; Storage layout; Data flow; (b) 26 |
| Architect scores (scope 6, feasibility 7) | A5-R11 | ACCEPTED as structural; feasibility driver fixed by A5-R5; a single text-verification pass is next | Confidence |
| Text corrections (self-found) | — | AC 31 "binding note 11" → 9; Confidence "notes 5 to 11" → "1 to 10" | AC 31; Confidence |

**Earlier rounds, condensed. All remain applied.**
- **§R4 (r3 reviews → r4):** security 1–9 and architect 1–15 FIXED under A4-R1 to A4-R11, plus self-found V23 (module-only contract lists).
- **§R3 (r2 reviews → r3):** security 1–11 and architect 1–16 FIXED under A3-R1 to A3-R6, plus self-found V16 (contract split).
- **§R2 (r1 reviews → r2):** python B1–B5 and P-n1–P-n13; security H1–H7, M1–M11, L1–L5; architect H1–H6, M1–M6, L1–L5. All FIXED under A-R1 to A-R6, except H2 `permit_present`, H4 node marker, M6, and the defer-records observation, which were REJECTED with reasons.

## §ERRATA-REQUEST

**(a) E-14, final text, to be filed verbatim.** The architect adopted it in r4. r5 adds one sentence at the end of rule 7, marked [r5].

> **E-14 (coordinator, 2026-10-03; from ARCH-0 seam A r1–r5 and the r1–r4 architect and security reviews): per-family root records.**
> - **Defect.** ARCH C3 "Bootstrap roots" (line 261) writes one `root.json` per `derived/artefacts/<model_class>/<sha>/`. `pm_us_crh_v4` and `pm_us_crh_cont` are both `continuous_rung_hold` with `density_artefact_sha256 = 247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65` (the `not_applicable_density.json` placeholder) and both are RETIRED seeds (line 738). Their `root/v1` bodies differ in `family_id` and `manifest_sha256`, so the second write-once returns EXISTS_DIFFERENT and the genesis BOOTSTRAP cannot complete. Separately, ARCH lines 263-264 expect the committed root file to change after bootstrap, which, once the resolver binds a root to its committed bytes, leaves the venue without a sender at the next LAUNCH.
> - **Rule.**
>   1. A root copy is written to `derived/artefacts/<model_class>/<sha>/artefact.json` (0444) and `derived/artefacts/<model_class>/<sha>/roots/<family_id>.json` (0444, `root/v1`, fields unchanged). This replaces `<sha>/root.json` in ARCH C3 line 261, AUT-5 r7 §3.2 lines 172 and 180, and AUT-7 r5 line 41 and `test_rollback_to_root_reads_content_addressed_copy` (line 569).
>   2. A root copy's model class is `f"{composition_kind}:{ROOT_ARTEFACT_COMPONENT}"` with `pins.ROOT_ARTEFACT_COMPONENT = "density_table"`; a root's artefact is its manifest's density artefact.
>   3. **Scope: families whose introducing row is BOOTSTRAP or ROOT_ADMIT with `lineage_root_family_id == family_id` ("roots"), whatever the authorising kind (BOOTSTRAP, ROOT_ADMIT, ROLLBACK, RESUME).** A family introduced by any other kind, or a BOOTSTRAP/ROOT_ADMIT row with `lineage_root_family_id != family_id`, invalidates the chain. For a root the resolver (a) reads the manifest only from `deploy/families/<family_id>.json` in the repo (never a registry copy) and refuses `manifest_sha_mismatch` unless its sha256 equals `row.manifest_sha256`; (b) reads `roots/<row.family_id>.json` and refuses `root_record_mismatch` unless `record.family_id == row.family_id`, `record.manifest_sha256 == row.manifest_sha256`, `record.artefact_sha256 == row.artefact_sha256`, and `record.committed_path == "deploy/families/" + family_id + ".json"` exactly. Children are out of scope: a Y2 no-new-lineage child resolves `artefact.json` in the existing `<sha>/` directory and has no `roots/` record; a new-lineage child is bound by its C3 `lineage.json`.
>   4. A second root sharing a `<sha>` directory writes `artefact.json` as an EXISTS_EQUAL no-op. EXISTS_DIFFERENT on `artefact.json` or on a `roots/<family_id>.json` is INTEGRITY.
>   5. The `<sha>/` and `roots/` directories become 0500 after the genesis transaction's last copy. This is hygiene, not a control (same-uid residual). A new file in a 0500 directory is refused by mode bit (`DIR_NOT_WRITABLE`), so AUT-3 refits write `artefact.json` and `lineage.json` into a fresh `<sha>/` only, never into a root's directory.
>   6. **Order and idempotence.** Every copy is written before the genesis BOOTSTRAP COMMIT. A crash and rerun is idempotent: an existing file with equal bytes is EXISTS_EQUAL, decided by reading it before any temp file is created, so a rerun succeeds even after the rule-5 chmod.
>   7. **Frozen committed root bytes.** Once a root is bootstrapped or root-admitted on any registry root (production or shadow), its `deploy/families/<family_id>.json` bytes are frozen. `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256` (a `MappingProxyType` of `family_id → sha256`, empty until the reviewed pins commit that precedes the first bootstrap, which lists every `BOOTSTRAP_SEED` id; a ROOT_ADMIT adds its row in the same commit as its allowlist triple) pins them. Rows are append-only. `test_bootstrapped_root_manifests_unchanged` fails CI on any edit, so the failure lands at merge rather than at LAUNCH. Superseding a bootstrapped root, including setting `terminal_climate_day`, is done in the registry (RETIRE) or by a new root (a new `family_id` through ROOT_ADMIT), never by editing the committed file. **Clearing path (L-48)** if an edit reaches a running tree anyway (resolver `manifest_sha_mismatch`, no sender, entries vetoed): a reviewed revert restoring the pinned bytes, or ROOT_ADMIT of a new root. ARCH lines 263-264 ("even if the repo file changes") are refined accordingly: ROLLBACK to a root still reads the store artefact, but the root's committed manifest bytes must equal the row. **[r5]** Until ROOT_ADMIT is enabled (it is not at L1), the reviewed revert is the only clearing path, and from the stage-S bootstrap onward the live `forecast_quantile_ladder` root manifest is frozen; the CI pin test is hygiene, and the runtime anchor is the resolver's `manifest_sha_mismatch`.
> - **Consumption.** ARCH-0 seam A (`paths.root_record`, `family_bytes.write_root_copy`, the resolver, `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256`, `single_read` `DIR_NOT_WRITABLE`); AUT-5a bootstrap and the pre-bootstrap pins commit; AUT-7 r5 root reads; AUT-3 refit destinations. Fail-closed until filed: BOOTSTRAP refuses and nothing goes live.

**(b) The complete list of ARCH and plan text that ARCH-0 amends.** The coordinator records these alongside E-14. Items 1–41 keep their r4 numbers. ☆ marks items new or changed in r5.

**ARCH**
1. ☆ C5 resolver, "checks the export prefix and the node high-water mark", is refined (L-12):
   - the HWM is tri-state, with mid-chain hash verification at `rows[venue_seq−1]`;
   - domain: `venue_seq ≥ 1`, `export_seq ≥ 0`;
   - `HwmAbsent` refuses on any non-empty chain;
   - `Hwm.export_seq`; a listing error → `export_unreadable`;
   - exports are evaluated before the HWM, and no export means `newest_export_seq` 0;
   - ☆ the export listing is venue-scoped, with reset records and other-venue exports ignored and any other name fail-closed;
   - ☆ HWM writes are monotone.
2. ☆ C5 shadow stage: `resolve_shadow_family` and `ShadowResolution`, with the same 26 h no-export rule; ☆ the step set is {0, 2, 3, 5–8}.
3. Y6: root and child status come from the introducing row. Any other introducer, or a root kind with a foreign lineage root, invalidates the chain. The regex is a consistency check.
4. ☆ C3 lines 263-264: E-14 rule 7, including the r5 sentence.
5. C5 lines 431-434: `holdout_opens` has no row source. The fold derives every other counter; `holdout_opens` stays an AUT-5 WP4 cache field.

**AUT-5 r7**
6. §3.1 `__init__` "Public names only" → docstring only.
7. §3.1 `single_read` "`lstat` walk" → openat walk, EXISTS_EQUAL pre-read, `DIR_NOT_WRITABLE`.
8. §3.1 `VetoReason` → imported from `veto.py`.
9. §3.1 `schemas.py` records → owner rows. `StagePolicy` is in `schemas`. `ResolvedFamily`, `ShadowResolution` and `ResolverRefusal` are in `resolver`, and `FamilyBytes` in `family_bytes`.
10. `:116` `entry_guard`: `legs` → `venue_suffix`; `GuardResult`; `FillIndexAbsent`; `open_intent_blocks()`; `FillRow.ts_event_ns`; `FillRow.order_side: Literal["BUY","SELL"]`, contract-tested.
11. `:410` `parse_family_manifest(raw, *, path, allow_draft=False)`; the node consumes `ResolvedFamily.family_bytes`.
12. `:421` busy handling keyed on `RegistryUnreadable.reason`; the supervisor retries busy only at LAUNCH.
13. ☆ `:423` `_tick_once` calls `rows_admissible` before `validate`, per row, applying the admitted prefix and leaving the HWM unadvanced on refusal. ☆ Each tick re-reads from the last verified seq and recomputes, so refused ticks are idempotent.
14. ☆ `:425` the node boot HWM write writes `ResolvedFamily.hwm` ☆ through `write_monotone` under the intent flock (a held-lock argument); `SKIP` is success. `:426` shadow → `resolve_shadow_family`. The tick `export_seq` is carried forward and never lowered; ☆ ticks write through `write_monotone`.
15. `:427` guard cache → `GuardResult`.
16. `:441` `resolved_registry_seq` = `ResolvedFamily.registry_seq`.
17. ☆ `:480-488` the reset CLI handles the case before the first export and is the clearing path for `hwm_absent`. It requires `--expect-head`, prints standing DEMOTE and HALT rows, and refuses a fold less restrictive than the last alerted HWM. ☆ It is the only writer that bypasses `write_monotone`, and its `hwm_reset_<ts>.json` record is ignored by `newest_export`.
18. WP1 Files `:841` Nautilus ban → contracts (b) and (c), listing module names only, plus classification.
19. §3.2 DDL: `NOT NULL` on `venue` and `venue_seq`; COALESCE trigger; `user_version`, `application_id`.
20. §3.2 append: `PartialReplay`; `now_ns`; ts skew; `AdmissionPending`; admission through `rows_admissible`; `StageNotCanonical`; caches deferred to WP4.
21. §3.2 export trailer gains `schema`, `venue` and `evidence_journal_heads`.
22. §3.2 lines 172 and 180 → E-14.
23. §4 ledger tuple gains `owner_symbol` and `blocks_kinds`; `raises=OwnerPending`; E-11 rename at `:825`.
24. WP1 and WP2 RED lists → the crosswalk.
25. WP9 RED list `:927`: 4 of 7 ship in ARCH-0.
26. ☆ WP10 L1 cut-over `:937`:
    - ☆ every bootstrap, production and shadow, creates `evidence/registry/`;
    - the initial HWM write runs between the bootstrap exit (≤ 16:41:15) and 16:44:55, under one monotonic deadline computed at start;
    - ☆ the lock wait is `min(5, remaining)` s on `<exec store>.intent.lock`;
    - ☆ the clock is re-checked after acquire and before the write;
    - ☆ the write goes through `write_monotone` onto Absent only;
    - ☆ a write completing after the deadline is an abort;
    - ☆ the abort deletes the key only while holding the lock that wrote it; if the lock was never acquired there is no key;
    - no HWM value is written in [16:44:55, 16:50:00), the in-hold delete being the single exception;
    - a missed deadline aborts through the pre-LAUNCH rollback.
27. WP4 `lineage_counters` names the `holdout_opens` writer (`test_holdout_opens_cache_has_named_writer`).
28. The pre-bootstrap pins commit fills `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` (stage S included).

**AUT-7 r5**
29. `:56`, `:703` `verify_family_bytes(row, *, paths, repo_root, origin)`.
30. `:91`, `:506`, `:703` `append_journal(paths, kind, venue, record, *, ts_ns)`; bare kinds; `append(..., now_ns)`.
31. `:41`, `:569` → E-14.

**AUT-4 r11**
32. `:18`, `:404`, `:1372` lazy `__init__` → facade deleted.
33. `:431`: `nominations`, `infeasible_nominations` and `alpha_spent` are read from `fold(...).lineages[*].tallies`. `holdout_opens` remains a read of the AUT-5 WP4 `lineage_counters` cache. `:563` and `:567`: `lineage_counters.nominations` → `LineageTallies.nominations` (max feasible `k_life`; see binding note 1b).

**AUT-2 r7**
34. `:68`, `:116`, `:631`: `net_position.py` is created by ARCH-0 with `LegFill` and `net_signed_qty`. AUT-2 adds `CostedFill` and `average_cost_basis` to the same module.
35. `:335` netting uses `LegFill.ts_event_ns`.

**AUT-6 r15**
36. `:2254` is stale; the ER-2 name at `:1746` wins.
37. `:512` the verdict date comes from `write_verdict`.
38. `:1474` consumes the fold; no change.

**AUT-1 r12**
39. `:1237` `SELF_HEAL_RESTARTABLE_UNITS` is stale (E-11); `EntryVeto` names only the C1 record.
40. `:329` `DecisionRecord.registry_seq` = `ResolvedFamily.registry_seq`.

**AUT-3 r6**
41. Refit outputs go to a fresh `derived/artefacts/<model_class>/<sha>/` only (E-14 rule 5); `test_refit_writes_only_fresh_sha_dir` is carried to AUT-3.
42. ☆ (A5-R9, A6-R2) `:137` `dataclasses.replace(row, split="v5_fit_slice")` sits in `src/breezy/analysis/autonomy_refit/` (`:21`), which is inside the AC 15(ii) scope (every `autonomy*` package under `src/breezy/`). The call therefore needs a reviewed literal exemption row `(module, lineno-free call description, reason)` in `test_autonomy_policy_not_mutable_from_src`'s exemption set, added in AUT-3's own commit; any other banned call AUT-3 adds follows the same rule.

**AUT-4 r11 (continued)**
43. ☆ (A5-R9) AUT-4 builds in `src/breezy/analysis/autonomy/` (for example `:507-512`), so the AC 15(ii) blanket ban applies to every module it adds there. Any `dataclasses.replace` or `copy.*` on AUT-4's own records needs a reviewed literal exemption row in AUT-4's own commit. The set is empty at ARCH-0.

**AUT-6 r15 (continued)**
44. ☆ (A5-R9) AUT-6 builds in `src/breezy/persistence/autonomy/` (`detector_catalog`, `pins`), so the AC 15(ii) blanket ban applies. Exemptions follow the same reviewed-literal-row procedure, in AUT-6's own commit.

**AUT-5 r7 (continued)**
45. ☆ (A5-R6) `:173`, `:189`, `:485`, `:487`: readers select exports with the venue-scoped filter `\Aregistry_<venue>_\d{4}-\d{2}-\d{2}(_hwm\d+)?\.jsonl\Z`. `hwm_reset_<ts>.json` and other-venue exports are known and ignored. Any other name in `evidence/registry/` is `export_unreadable`. The engine's `.tmp.` sweep is the clearing path for a leftover temp file (R25).
46. ☆ (A5-R2) The HWM writers (node boot, ticks, cut-over) use `hwm.write_monotone(store, new, *, held_lock)`, delivered by AUT-5a in `hwm.py` on top of ARCH-0's pure `write_monotone_decision`. The writer-table row is updated in the same commit.
## Coordinator amendments to r5 (binding; rulings A6-R1, A6-R2 in reviews/ARCH-0-r1-merged.md)

These override any conflicting r5 text above.

- **A6-R1 (closes R25).** AC 17 step 3 `newest_export`: the known-and-ignored set gains exactly `\A\.tmp\.[0-9a-f]{16}\Z`. `write_once` publishes only via `os.link` to the final name, so a temp name is never an export. Every other unknown name remains `export_unreadable`. Seam 6f adds `test_newest_export_ignores_write_once_temp_name` with a control (`.tmp.x` still refuses). (b) item 45: "The engine's `.tmp.` sweep is the clearing path" is replaced by "write_once temp names are ignored". Unknown 11 is closed.
- **A6-R2 (closes R26).** AC 15(ii) scope: every package under `src/breezy/` with a dotted-path component starting with `autonomy`, derived by walking `src/breezy/` in the test (a planted `src/breezy/x/autonomy_new/` module with a `copy.copy` call is the positive control). This covers AUT-3's `analysis/autonomy_refit/`. (b) item 42: AUT-3 r6 `:137`'s `dataclasses.replace(row, split="v5_fit_slice")` is inside the ban and needs a reviewed exemption row in AUT-3's own commit. Unknown 12 is closed.

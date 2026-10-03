I have what I need. Here is the complete r2 plan.

# ARCH-0 seam A: persistence core build plan, r2

**Round:** r2 (2026-10-03). This revises r1 (`ARCH-0-seamA_plan_r1.md`) and closes every finding in the three r1 reviews (`reviews/ARCH-0-seamA-r1-{python,security,architect}.md`). It follows the binding coordinator rulings A-R1…A-R6 in `reviews/ARCH-0-r1-merged.md`. The disposition table is in §R2.

**Basis.** Plan facts come from FROZEN ARCH Rev 9.2 (sha `1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42`, re-hashed 10-03) and errata E-1…E-13. Code facts were checked on the tree at `d231497d` through codegraph, `sed` and read-only probes. The probes used `/home/jon/breezy/.venv/bin/python` with scratch under `/tmp/claude-1000/a0r2/`. No repo file was written and no state was changed.

**New facts verified in r2.** Each is cited where it is used.
- (V1) A fresh `import breezy.domain.instrument_leg` loads 120 `nautilus_trader*` modules, because `domain/__init__.py:16-53` imports every record module eagerly.
- (V2) `import breezy.persistence.live_orders_gate` loads 126 Nautilus modules today. On a scratch copy with an import-free `persistence/__init__.py` it loads 0 Nautilus modules and 15 `pyarrow*` modules, and max RSS is 61 MB against a 13 MB bare interpreter. The pyarrow comes from `family_manifest.py:88` → `mechanism_test_guard.py:14`.
- (V3) `persistence/__init__.py` re-exports 20 names. No `src/`, `tests/` or `scripts/` site uses any of them by name. All 22 `from breezy.persistence import X` statements import submodules.
- (V4) SQLite 3.50.4 behaves as follows:
  - `INSERT OR REPLACE` bypasses a `BEFORE DELETE` trigger while `recursive_triggers=0`.
  - A `BEFORE INSERT … WHEN EXISTS(…)` trigger refuses REPLACE, gaps and duplicates whatever that pragma says.
  - `ON CONFLICT DO UPDATE` fires the UPDATE trigger.
- (V5) The data root is 0700. `derived/` is 0775. Repo directories are 0775 and manifests 0664. The host umask is 0002.
- (V6) `trade_supervisor_core.py:37-44`: STOP_PRIOR 16:40, LAUNCH 16:50, SELF_CHECK 17:05, RELAUNCH_CUTOFF = LAUNCH_WINDOW_END 17:00.
- (V7) The exec client is byte-pinned at `76784ce8…aa68a4` (`tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:36`). ARCH-0 never edits it.
- (V8) `live_orders_authorized` (`live_orders_gate.py:130-189`) contains the ruling containment and sha check inline (`:163-182`), and its messages embed absolute paths.
- (V9) `load_family_manifest` (`family_manifest.py:285-460`) uses `path` both for messages and for artefact containment (`_assert_artefact_path_contained`, `:262-282`, `path.resolve().parent`).
- (V10) `exec/client.py` has no `.delete(` or `DELETE FROM` site, so a `fill_index/` key is never pruned.

**Residual, stated once (security L5).** Pins, chain, HWM, exports and the DB are one same-uid trust domain (ARCH C5 "Residual risk", R14). The external anchors are only the committed allowlists, `live_orders_gate`, and the reviewed code in `pins.py` and `transitions._ADMISSION_IMPLEMENTED`. H1, H2 and H3 below exist to keep those anchors from being bypassed by a row, a rebinding or a missing verifier.

## Acceptance Criteria (numbered, testable)

1. **Package and contracts.** `src/breezy/persistence/autonomy/` holds exactly the modules in the File-by-File Plan. `cd /home/jon/breezy && .venv/bin/lint-imports` prints "N kept, 0 broken", where N includes:
   - (a) `breezy.persistence.autonomy ↛ breezy.adapters` (ARCH §4.7), with `allow_indirect_imports=false`.
   - (b) the **core list** (25 modules, File plan) ↛ `nautilus_trader`, `pyarrow`, `breezy.domain`, with `allow_indirect_imports=false`. `include_external_packages = true` already exists at `pyproject.toml:72`.
2. **Module classification (architect H5, python P-n9).** `test_every_autonomy_module_is_classified` places every module under `breezy.persistence.autonomy` in one of three sets:
   - contract (b)'s `source_modules`, parsed from `pyproject.toml`;
   - `PYARROW_PERMITTED = {label_schema}`;
   - `NAUTILUS_PERMITTED`, the AUT-1 `capture_*` set (E-12), empty at ARCH-0.

   The test has a planted-module positive control.
3. **Runtime import weight (python B1 = architect H3, python P-n13).** `test_autonomy_core_modules_nautilus_free_at_runtime` imports each core module in a fresh subprocess and asserts:
   - 0 `nautilus_trader*` modules;
   - 0 `breezy.domain*` modules;
   - `pyarrow*` only for `{family_bytes, registry_store, replay, resolver}`, the measured `family_manifest → mechanism_test_guard` cost (V2). `label_schema` is the fifth pyarrow module.

   r1's claim that "pyarrow is only in `label_schema`" is withdrawn.
4. **Import-free `persistence/__init__.py` (architect H2, security M9, python P-n7).** The 20-name facade is **deleted**, not made lazy, following the NOTIFIER-IMPORT-ISOLATION precedent at `runtime/__init__.py:15-25`. That precedent's rationale applies here: the facade has zero consumers (V3). The tests:
   - `test_persistence_init_has_no_import_nodes`;
   - `test_persistence_has_no_facade_consumers`, an AST check of `src/`, `tests/` and `scripts/` that also refuses `mock.patch("breezy.persistence.<non-submodule>")`;
   - `test_persistence_init_preserves_register_arrow_reachability`. This is a grimp graph with synthetic module→ancestor edges, run per entry module (pyproject scripts, systemd ExecStart, and `scripts/**` importing `breezy.persistence`). It asserts that the `register_arrow` modules (`domain/*.py`, `monitor_records.py:249`, `tape_records.py:629-637`) reachable after the change equal those reachable with the old `persistence → catalog` edge simulated back in. Any difference fails, unless the entry sits in a literal reviewed exemption with a reason;
   - `test_persistence_entry_module_imports_cleanly[<entry>]`, a fresh-process smoke per entry.
5. **Explicit serialisation.** Every wire record has `to_wire() -> dict` and `from_wire(payload) -> Self`. The records are: C2 schema, C3 `lineage/v1`, `root/v1`, `refit_run/v1`, C4 `verdict/v1`, C5 row, export trailer, `demand/v1`, `drill_marker/v1`, `journal/v1` and `Hwm`. Bytes are parsed by `wire.parse_json_exact`, which:
   - refuses duplicate keys (`object_pairs_hook`), NaN and Infinity (`parse_constant`), and any float token (`parse_float`);
   - refuses missing or unknown keys, wrong types, bool-as-int, and a `schema` value outside `ACCEPTED_SCHEMAS`;
   - raises `WireRefused(reason: WireRefusalReason)`, a closed StrEnum (security M6).

   An AST test finds no `dataclasses.asdict`/`astuple` in the package.
6. **Canonical bytes (python B3).** `canonical_json(x)` = `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False)` encoded as UTF-8. It raises `CanonicalTypeError` for any of these: a non-`str` key, a `float`, a lone surrogate (the `UnicodeEncodeError` is wrapped), or any type outside `None|bool|int|str|list|tuple|dict|Decimal`. `decimal_str(d)`:
   - refuses `is_nan()` and `is_infinite()`;
   - refuses more than `DECIMAL_MAX_DIGITS = 38` digits or `|d.adjusted()| > DECIMAL_MAX_ABS_EXPONENT = 18`;
   - writes every zero, including `-0` and `0E-10`, as `"0"`;
   - otherwise writes `format(d.normalize(), "f")`.

   Golden fixtures: `-0`→`"0"`, `0E-10`→`"0"`, `1E+2`→`"100"`, `1.50`→`"1.5"`, plus three record goldens.
7. **Single read and write, TOCTOU-free (python B5 = security H5, python P-n1).**
   - `open_root(root)` requires an absolute path and opens `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`.
   - `walk_dirs(rootfd, rel, *, create)` runs `openat` per component with `O_DIRECTORY|O_NOFOLLOW`. It refuses `""`, `.`, `..`, NUL and `/`, checks `fstat` S_ISDIR with `st_uid == geteuid()`, and never re-opens a string path.
   - `read_once_at(dirfd, name, *, max_bytes, policy)` opens `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, so a FIFO never blocks. It requires `fstat` S_ISREG and owner uid. Under `ReadPolicy.STRICT` it also refuses any group- or other-write bit. It reads `max_bytes+1` to detect growth.
   - `ReadPolicy.REPO` drops the mode-bit check for git-checked-out files, which are 0664 under umask 0002 (V5). Integrity for those files comes from the sha binding.
   - `read_once_nofollow(path, *, root, max_bytes, policy)` composes these. **No `lstat` pre-walk exists.**
   - `write_once(path, data, *, root, mode)` creates `.tmp.<secrets.token_hex(8)>` through the parent dirfd (`O_CREAT|O_EXCL|O_NOFOLLOW`), then `fchmod(mode)`, write, `fsync`, and `os.link(..., src_dir_fd=, dst_dir_fd=, follow_symlinks=False)`.
     - On EEXIST it compares through `read_once_at`, so a symlink at the destination gives ELOOP → `EXISTS_DIFFERENT`.
     - EPERM, EXDEV, EOPNOTSUPP and EMLINK give `SingleReadRefused(LINK_UNSUPPORTED)`. There is never a rename fallback.
     - The temp is always unlinked through the dirfd, followed by a dirfd `fsync`.
   - `replace_atomic` follows the same path with `os.replace(..., src_dir_fd=, dst_dir_fd=)`.
   - AST tests: every ARCH-0 reader goes through these functions, and they are the only `os.link`/`os.replace`/write-mode `open` sites in the package.
8. **Store DDL (python B2, security M1/M4).** `transitions` has exactly the AUT-5 r7 §3.2 column set, plus `UNIQUE(venue, venue_seq)` and `UNIQUE(transition_id)`.
   - `BEFORE UPDATE` and `BEFORE DELETE` triggers raise `RAISE(ABORT,'append-only')`.
   - A `BEFORE INSERT` trigger refuses `NEW.seq` already present, a duplicate `(venue, venue_seq)`, and `NEW.venue_seq ≠ max(venue_seq | venue)+1` (V4).
   - `meta(schema='registry/v1')`, `PRAGMA user_version=1`, `application_id=0x42524759`.
   - Directory 0700, file 0600.
   - The derived caches (`families`, `projection`, `lineage_counters`) are **not** created. They belong to AUT-5 WP4 (stub table), and no production DB exists before AUT-5a.
9. **Writer connection (python P-n3).** `isolation_level=None` with an explicit `BEGIN IMMEDIATE`. On every writer connection: `journal_mode=DELETE`, `synchronous=FULL`, `recursive_triggers=ON`, `trusted_schema=OFF`. A test reads each pragma back. An AST test bans `OR REPLACE`, `OR IGNORE`, `REPLACE INTO` and `executescript` in `registry_store.py`.
10. **Append path (security M2/M3, H3; architect H1).** The public `RegistryStore.append(rows, *, expected_prior_seq, mode: WriterMode, now_ns: int)` delegates to the private `_append(..., stage: StagePolicy)` with `stage_policy.STAGE`. One `BEGIN IMMEDIATE` runs these steps in order:
    1. All ids already present → logged no-op. Partial presence → `PartialReplay`.
    2. `mode` must be a concrete `WriterMode`. `None` is refused by type and at run time.
    3. `KIND_MASK[mode]`.
    4. For each widening row: kind ∈ `stage.enabled_widening_kinds`, else `WideningNotEnabled`. Then kind ∈ `stage.admission_implemented`, else `AdmissionPending`.
    5. A SHADOW→CHALLENGER PROMOTE → `NominationRequiresPolicy`. HWM_RESET → `RuleSetPending`.
    6. `|row.ts_ns − now_ns| ≤ pins.ROW_TS_MAX_SKEW_S` (300 s), and ts is monotone non-decreasing over the head.
    7. CAS: `max(venue_seq) == expected_prior_seq`.
    8. `transitions.validate(fold(prior), rows, mode=mode, now_ns, stage, manifests)`.
    9. Insert, then COMMIT.

    Any failure rolls back completely.
11. **Chain (security M1).**
    - Genesis is `sha256(b"registry/v1|"+venue)`.
    - `canonical_row` holds every column except `seq` (the local rowid), `prev_transition_hash` and `transition_hash`. `venue` and `venue_seq` are therefore hashed, which a test asserts.
    - `transition_id` hashes the C5 Y9 tuple, with `expected_prior_seq` excluded.
    - `verify_venue_chain(rows, venue)` requires `venue_seq == 1..n` contiguous, every `row.venue == venue`, monotone `ts_ns` and an unbroken hash chain. It detects any edit, reorder, deletion, splice, renumbering or gap.
12. **Reader (security M4, python P-n4).** `RegistryReader(paths, *, busy_timeout_ms).read_venue_rows(venue, after_seq=0)`:
    - opens `file:<percent-quoted path>?mode=ro` plus `PRAGMA query_only=ON` and `trusted_schema=OFF`, one connection per call, never shared;
    - reads inside one `BEGIN`;
    - checks `meta.schema`, `user_version` and `application_id`, and that `sqlite_master` (type, name, sql) **equals** the DDL constants exactly;
    - selects an explicit column list `ORDER BY venue_seq`.

    `sqlite3.Error` and `OSError` → `RegistryUnreadable`. A hot journal from a killed writer → `RegistryUnreadable`; the reader cannot tell it from a writer mid-commit. The engine's next rw open under `engine.lock` rolls it back (AUT-5a).
13. **Validated kinds.** `transitions.validate` is pure and implements every fold-decidable C5 rule for **every** kind. This includes the rules security Q5 requires to be real:
    - V12: DRILL-class row refused while a non-DRILL cause stands;
    - DRILL_PROMOTE requires the champion's artefact sha;
    - drill refused over a HALTED incumbent;
    - drill counters ≤ 1 per `DRILL_BUDGET_PER_VENUE_30D` (V15);
    - Z3 counting and `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY`;
    - RESUME: every standing cause cleared, `RESUME_COOLDOWN_H`, the RECOVERABLE_MODEL/INFRA resume ceilings, and ROLLBACK_FAILED resumes only under `trigger_cause_class`;
    - all five E-5 `drill_close_restore` conditions, at most 1 per venue per day;
    - d0 and `trial_id_prefix` at the first →CHAMPION row, with ROLLBACK, RESUME and ROOT_ADMIT exempt;
    - ROOT_ADMIT only with no sender;
    - mint rate;
    - BOOTSTRAP genesis and seed (E-6);
    - ATTEST cadence;
    - SWAP_CANCEL voids ⊆ pending;
    - the single-sender invariant at `now` and at the next LAUNCH;
    - HWM_RESET `carried_counters` ≥ export counters (B9; `export_counters` is required).

    Pins ceilings are the bounds. A stricter policy block is WP1b's job. **Admission** of widening kinds into the store stays closed. `_ADMISSION_IMPLEMENTED: Final[frozenset[Kind]] = frozenset()` lives in `transitions.py`, and only an owner WP adds to it. Gate tests:
    - `test_enabled_widening_kinds_subset_of_admission_implemented`;
    - `test_enabled_widening_kinds_subset_of_widening_kinds`;
    - `test_root_admit_enabled_requires_ceiling_true` (security H3).
14. **Fold.** `fold(rows, venue, now_ns)` is pure, as in r1 AC 13. A test checks that the HWM_RESET floors (`carried_counters`) are applied. The AST test bans `time.time`, `time.time_ns`, `datetime.now`, `datetime.utcnow` and `time.monotonic` in the core list.
15. **Stage policy is frozen (security H3).** `stage_policy.STAGE: Final[StagePolicy]` is a frozen slotted dataclass built once at import from `pins` and `transitions._ADMISSION_IMPLEMENTED`. Production entry points take no policy parameter. `test_autonomy_policy_not_mutable_from_src` uses AST over `src/` and refuses all of the following:
    - attribute assignment, `setattr`/`delattr`, `__dict__` access, `importlib.reload`, `mock.patch`/`monkeypatch`, and `globals()`/`vars()` writes, all targeting `pins`, `stage_policy`, `transitions`, `live_orders_gate` or `family_manifest`;
    - a rebinding of any name imported from those modules;
    - a reference to `_append`, `_resolve`, `_replay_full`, `_lineage_policy_authorized` or `_verify_ruling_file` from outside its defining module. Tests may reference them.

    Each pattern has a planted positive control.
16. **Resolver (security H1, H4, M7, M8).** `resolve_sending_family(*, venue, paths, repo_root, now_ns, hwm: HwmReading) -> ResolvedFamily | ResolverRefusal` delegates to `_resolve(..., stage, lineage_gate)`. It refuses every member of the closed `RefusalReason` enum (Architecture). It:
    - verifies the chain from genesis;
    - checks clock sanity: `now_ns` must be an int > 0 and ≥ head `ts_ns` − skew;
    - applies the tri-state HWM and the export rules (Edge Cases);
    - **refuses `widening_kind_not_enabled` / `admission_pending` when any chain row has a widening kind outside `stage.enabled_widening_kinds` / `stage.admission_implemented`**;
    - runs `replay_full`;
    - refuses `engine_inconsistency` on more than one CHAMPION/HALTED family;
    - binds manifest, artefact and the E-14 root record to the authorising row, including manifest `venue`, `composition_kind` and `family_id` equal to the row;
    - checks `LIVE_GATE_ROUTED_KINDS` on the **manifest's** kind;
    - checks §4.2 equality over `dataclasses.fields(FamilyManifest) − ALLOWLIST − {"manifest_sha256"}`;
    - verifies the root triple with `live_orders_authorized(..., permit_present=False)` and accepts only `reason == "permit_absent"`;
    - verifies the child lineage with `lineage_policy_authorized`;
    - checks child d0 and prefix at the first →CHAMPION row.

    `ResolvedFamily(family_id, state: Literal[CHAMPION, HALTED], entries_allowed: bool, authorising_seq, manifest_sha256, artefact_sha256, export_check)` has every field required. It has **no** `enabled` and no permit field (M7).
17. **Lineage-policy gate (security H2).** `live_orders_gate.py` gains:
    - `_LINEAGE_POLICY_ALLOWLIST: Final[frozenset[tuple[str,str,str]]] = frozenset()`;
    - `CHILD_FAMILY_ID_RE = re.compile(r"\A(?P<root>[a-z0-9_]{1,58})_r[0-9]{4}\Z", re.ASCII)`;
    - the private `_verify_ruling_file(repo_root, ruling_id, expected_sha256)`, **extracted move-only** from `live_orders_authorized:163-182` with identical reasons and messages;
    - `lineage_policy_authorized(child, root_family_id, repo_root) -> LineagePolicyDecision(ruling_id, ruling_sha256)`, which delegates to `_lineage_policy_authorized(..., allowlist)`. It raises `LiveOrdersGateRefusedError` using **existing** `LiveOrdersReason` members only (AUT-5 r7 WP9: "No new `LiveOrdersReason` member").

    The existing `test_fq_live_orders_gate.py` and `test_live_orders_ruling_deploy_copy_matches_evidence.py` pass **unmodified**.
18. **`parse_family_manifest` split, proven byte-equivalent (security H6, python P-n11).** `parse_family_manifest(raw: bytes, *, path: Path, allow_draft: bool = False)` is the body of `load_family_manifest` after `read_bytes()`, moved verbatim. `load_family_manifest` becomes the prereg check, then `read_bytes`, then `parse_family_manifest`. The proof is `tests/unit/test_family_manifest_split_golden.py::test_parse_split_matches_presplit_golden`, built in two commits:
    - Commit 1, on the **unsplit** code: a frozen corpus `tests/fixtures/family_manifest_golden/`, holding copies of the 7 committed `deploy/families/*.json` plus 16 mutated invalid manifests, and `expected.json`, recording per input `(exception type, message with the path replaced by <PATH>)` or `(dump_family_manifest output, manifest_sha256)`. The test is GREEN.
    - Commit 2, the split: the same test stays GREEN unmodified.

    Every resolver and store caller of `parse_family_manifest` first runs `assert_prereg_directory_eligible(dir)` on the directory the bytes came from (`deploy/families` or `registry/families`). `test_autonomy_never_passes_allow_draft_true` scans `src/` with AST.
19. **Entry guard (security H7).** `rung_has_net_position(base_slug, *, reader: FillReader, venue_suffix) -> GuardResult{HELD, FLAT, UNREADABLE}`:
    - `FillReader.fill_index` returns `tuple[str,...] | FillIndexAbsent`. `FillIndexAbsent` means the key was never written; (V10) shows no pruning path exists. An existing **empty** index → UNREADABLE.
    - `FillReader.open_intent_blocks() -> bool` → UNREADABLE when True.
    - A `base_slug` containing `.` or `^`, or empty → UNREADABLE.
    - `net != 0` → HELD; a negative net also vetoes.
    - The whole body is wrapped `except Exception → UNREADABLE`.
    - `guard_veto_reason(result)` maps HELD and UNREADABLE → `rung_net_position_held`, and FLAT → `None`. The match is exhaustive.

    `net_position.py` and `entry_guard.py` do **not** import `breezy.domain`. The NO suffix `"^no"` is restated and `test_leg_suffix_equals_instrument_leg` asserts equality with `instrument_leg.INSTRUMENT_SEPARATOR + NO_LEG_SUFFIX` (`instrument_leg.py:35-40`).
20. **Veto (architect M4).** `VetoReason` holds exactly the 15 ARCH C5 members (`AUTONOMY_ARCHITECTURE.md:642-662`):
    - 5 registry: `registry_not_champion`, `registry_halted`, `registry_unreadable`, `registry_regressed`, `registry_restrictive_pending`;
    - 3 dead-engine: `registry_attest_expired`, `registry_engine_heartbeat_stale`, `registry_chain_stale`;
    - 6 transient: `feed_stale`, `recorder_stale`, `permit_lapsed`, `capture_gap`, `capture_untagged`, `alerts_undeliverable`;
    - 1 position: `rung_net_position_held`.

    **No `EntryVeto` alias**, because it collides with AUT-1 r12's C1 record at `:433`; the callable type is AUT-5a's, in strategy. `compose_entry_vetoes(checks: Sequence[Callable[[], VetoReason | None]]) -> VetoReason | None` returns the first veto. Any exception → `registry_unreadable`, as ARCH says: "an exception sets `registry_unreadable`".
21. **Verdict, demand, journal, marker, lineage and label records** are as in r1 AC 16–18, with these changes:
    - Path components are validated (security M5).
    - Journal kinds are bare names (`\A[a-z][a-z0-9_]{0,47}\Z`), and the record's own `schema` carries `/vN`.
    - The demand writer's docstring states that `producer_id` is advisory, not authentication (security L1).
22. **Pins.** `pins.py` holds literals only and imports nothing. It contains everything in r1 AC 19, plus:
    - the AUT-5 r7 §3.1 pins (architect L2): `ENGINE_LOCK_MAX_HOLD_S = 15`, `RELAUNCH_REQUEST_TTL_S = 120`, `WATCH_BUSY_TIMEOUT_MS = 250`, `DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY = 1`, `DRAWDOWN_INERT_ALERT_CEILING = "0.5"` (decimal string), `DRAWDOWN_INERT_ALERT_MIN_FILLS = 10`;
    - `ROW_TS_MAX_SKEW_S = 300` and `EXPORT_FIRST_DUE_H = 26`;
    - `ROOT_ARTEFACT_COMPONENT = "density_table"` (E-14 amendment 2).

    Kind sets are `frozenset[str]` and validated against `Kind` by test. Mapping pins are `MappingProxyType({})`, never `{}` (architect L1). `SCHEDULE_*` are test-equal to V6.
23. **C6.** As r1 AC 20. Protocol attribute members are `@property` (python P-n10).
24. **Placeholder ledger (architect H6, M2, M3; security M10).**
    - Ledger rows are `(node_id, owner, owner_symbol "mod:attr", blocks_kinds)`.
    - Carried bodies are **stubs**: `require_owner_symbol(...)` plus a docstring citing the ARCH pin, marked `xfail(strict=True, raises=OwnerPending)` and fixture-free.
    - `require_owner_symbol` raises `OwnerPending` **only** in two cases: `ModuleNotFoundError` whose `.name` is the declared module or one of its `breezy.` ancestors, or `AttributeError` for the declared attribute on a cleanly imported module. Every other exception propagates.
    - Gate tests: markers equal the ledger, reading both decorators and `pytest.param(marks=…)` (positive control for each form); `test_owner_placeholder_symbol_absent` (stale rows fail); `test_owner_ids_exist_in_plan_docs`; `test_envelope_manifest_equals_frozen_arch`; `test_every_envelope_node_id_collected_and_unskipped`; `test_widening_kind_enabled_only_when_its_placeholders_cleared`; `test_blocks_kinds_never_below_floor`; and AUT-5's `test_l2_widening_requires_empty_placeholder_ledger`.
25. **Gate.** `scripts/ci/run_tests_no_egress.sh` exits 0 after **every** WP merge (L-43). `lint-imports` passes. The mypy ratchet passes, and every new file has 0 errors (python P-n10). RED→GREEN logs exist for each real test, with mutation evidence where listed.

## Edge Cases & NFRs (fail-closed, one-writer, symlink refusal, atomicity, thread-affinity)

**Fail-closed.** Every failure produces the restrictive outcome, never a default.

| Input or condition | Result |
|---|---|
| Unknown `schema`; unknown, missing or duplicate key; bool as int; float token; NaN/Inf; oversize file | `WireRefused(WireRefusalReason)` → resolver refusal / demand venue veto / `VerdictUnreadable` (the engine treats it as ERROR) |
| Empty chain under `BREEZY_FAMILY_SOURCE=registry` | `empty_chain` |
| Hot journal, locked DB, any `sqlite3.Error`/`OSError`, `sqlite_master` ≠ DDL, wrong `user_version`/`application_id`/`meta.schema` | `RegistryUnreadable` → `registry_unreadable`. Never "no rows" |
| `venue_seq` gap, renumbering, foreign venue, ts decreasing | `chain_broken` |
| `now_ns` not an int, ≤ 0, or < head `ts_ns` − `ROW_TS_MAX_SKEW_S` | `clock_invalid` / `clock_before_head` |
| **HWM `Unreadable`** | `hwm_unreadable` |
| **HWM `Absent`** | Accepted only when the chain is exactly the genesis BOOTSTRAP transaction (every row is BOOTSTRAP) **and** no export file exists for the venue. Otherwise `hwm_absent` (`test_hwm_absent_with_rows_refuses`) |
| HWM `Present`: seq above head, same seq with a different head, or `hwm.export_seq` above the newest export's `export_seq` | `hwm_regressed` |
| Export absent | `export_unreadable` unless **all** hold: no export file, `hwm.export_seq == 0` (or HWM absent-eligible), and `now_ns − genesis_ts_ns < EXPORT_FIRST_DUE_H`. Then `export_check = not_yet_due`. Monotone ts plus `head.ts ≤ now + skew` bound how far a forged genesis ts can move this. A wholesale consistent forgery remains R14 |
| Any row with a widening kind ∉ enabled / ∉ admission_implemented | `widening_kind_not_enabled` / `admission_pending`, even when the row was inserted outside `append` (`test_resolver_refuses_chain_with_unenabled_widening_row`, using a hand-forged valid-hash chain, L-24) |
| More than one CHAMPION/HALTED on the venue | `engine_inconsistency`. Never an assert or an arbitrary pick |
| Manifest `DRAFT_NOT_REGISTERED`, all-zero sha, unreadable, invalid, or prereg-ineligible directory | `manifest_draft` / `manifest_unpinned` / `manifest_unreadable` / `manifest_invalid` / `prereg_ineligible`. `FamilyManifestError` and `LiveOrdersGateRefusedError` are mapped to the enum, and the refusal is a **returned value**, so no exception chain carries a path (M6) |
| Manifest `venue`, `composition_kind` or `family_id` ≠ the row; kind ∉ `LIVE_GATE_ROUTED_KINDS` | `manifest_identity_mismatch` / `kind_not_live_gate_routed` |
| Root record missing, or `record.family_id`/`manifest_sha256`/`artefact_sha256` ≠ the row (E-14 amendment 3) | `root_record_mismatch` |
| `engine_code_sha` ∉ `ENGINE_SOURCE_SHA256` or ∈ `REVOKED` | `engine_code_unpinned` / `engine_code_revoked`. The pins are empty at ARCH-0, so every production resolution refuses; that is intended |
| Child with no lineage triple, a ruling sha mismatch, or `live_orders_ruling` ≠ the policy ruling | `root_not_lineage_allowlisted` / `ruling_refused(<LiveOrdersReason>)` / `ruling_not_policy` |
| Guard: reader raises, empty index, open/corrupt intent, bad slug, unknown side | `GuardResult.UNREADABLE` → veto |
| Demand directory unreadable, bad file, family ∉ fold, reason ∉ `DEMAND_REASONS`, > `DEMAND_FILES_MAX` | `DemandScan.venue_veto=True` |
| Journal link broken | `JournalUnverified`. Restrictive writes are never blocked (L-48) |
| `write_once` on a filesystem without hard links | `SingleReadRefused(LINK_UNSUPPORTED)`. No rename fallback |

**One writer (L-50).** As in r1. `tests/unit/autonomy_writer_table.py` is data that Wave 1 owners extend. The AST scan fails on any write site outside `single_read.{write_once, replace_atomic, ensure_dir}` and `registry_store`, which is the only sqlite writer. The root-copy row becomes `derived/artefacts/<model_class>/<sha>/{artefact.json, roots/<family_id>.json}`, pending E-14.

**Symlink refusal.** Every path is built from an `AutonomyPaths(root)` value whose builders validate each component with `re.ASCII` `\A…\Z` patterns (security M5):

| Component | Pattern |
|---|---|
| venue | `[a-z0-9_]{1,32}` |
| family | `[a-z0-9_]{1,64}`, the intersection of `trial_day_latch.py:301` and `settings.py:115`; a test asserts both existing patterns accept every accepted id |
| model_class | `<kind ∈ _COMPOSITION_KINDS>:[a-z_]{1,48}` |
| sha / verdict id | `[0-9a-f]{64}` |
| date | `[0-9]{4}-[0-9]{2}-[0-9]{2}`, plus `date.fromisoformat` |
| journal kind | bare name (AC 21) |
| seq | int ≥ 1, formatted `%010d` |

`/`, `..` and NUL are refused. Each builder has a traversal-vector test. All I/O is the openat walk of AC 7.

**Atomicity.** A multi-row append is one SQLite transaction. ARCH-0 proves it with the restrictive pair SWAP_CANCEL + TARGET_INELIGIBLE (`test_store_multirow_append_is_atomic`). The ROLLBACK + ACTIVATE `[store_atomic]` case moves to WP1b (architect H1d). A crash inside `write_once` leaves at most a `.tmp.` file, which the owner engine sweeps. A crash in `replace_atomic` leaves the old bytes.

**Thread affinity, clock, hygiene.** As in r1:
- no held connections;
- no threads, timers or asyncio (AST);
- no module-level mutable state (AST; `Final` frozensets, tuples and `MappingProxyType` only);
- `now_ns` is always explicit;
- refusals carry enums and role names, never paths.

`test_autonomy_payload_hygiene_scan` plants a tmp path through `family_manifest` and `live_orders_gate` failures and asserts it appears nowhere in `str`, `repr` or the fields of the returned refusal (M6).

**Size and performance.** As in r1: 10,000 synthetic rows resolve in ≤ 2 s; `closure_sha256` runs in ≤ 5 s and ≤ 128 MB with no grimp. The resolver's runtime closure carries pyarrow at about 48 MB RSS (V2). That is accepted and named against AUT-5's own-lock 4 G budget (ARCH §5.2, V14).

**Root permission.** Mode assertions use `stat().st_mode`. The read-only test relies on SQLite `mode=ro`, which is uid-independent (python P-n5; R12).

## Architecture & Data Flow (modules, public API signatures, storage layout + paths, layering vs import-linter layers app > analysis > strategy > runtime > adapters > ingest > persistence|registry|normalize > settlement > domain)

**Layering (python P-n8 corrected).**
- `persistence`, `registry` and `normalize` are **independent siblings** (`pyproject.toml:97`). `persistence.autonomy` imports only `persistence` (its own layer), `settlement` and `domain` by the layers contract. Contract (b) then forbids `domain` for the core list.
- `NODE_PLUGINS` (strategy) and `OFFLINE_PLUGINS` (analysis) are placed where ARCH C6 puts them.
- `persistence/__init__.py` becomes import-free (AC 4). `persistence.live_orders_gate` stays in `persistence`, and `resolver` imports it downward-sideways within the layer.

**Modules and public API** (all `from __future__ import annotations`, mypy strict; changes from r1 marked ★):

```text
persistence/__init__.py ★ docstring only, no import nodes (facade deleted; AC 4)
persistence/family_manifest.py ★ + parse_family_manifest(raw: bytes, *, path: Path, allow_draft: bool = False) -> FamilyManifest
persistence/live_orders_gate.py ★ + _LINEAGE_POLICY_ALLOWLIST; CHILD_FAMILY_ID_RE; _verify_ruling_file(...) (move-only);
        LineagePolicyDecision(ruling_id, ruling_sha256); lineage_policy_authorized(child: FamilyManifest, root_family_id: str,
        repo_root: Path) -> LineagePolicyDecision; _lineage_policy_authorized(..., *, allowlist)
persistence/autonomy/
  __init__.py        docstring only
  canonical.py       canonical_json(obj) -> bytes; sha256_hex(b) -> str; decimal_str(d) -> str; CanonicalTypeError
  wire.py ★          parse_json_exact(raw: bytes) -> dict; require_exact_keys/require_str/int/bool/sha256/enum/decimal_str/ns;
                     WireRefusalReason(StrEnum); WireRefused(reason: WireRefusalReason); SHA256_RE; FAMILY_ID_RE
  single_read.py ★   ReadPolicy(STRICT|REPO); open_root(root) -> int; walk_dirs(rootfd, rel, *, create=False, mode=0o700) -> int;
                     read_once_at(dirfd, name, *, max_bytes, policy) -> bytes; read_once_nofollow(path, *, root, max_bytes, policy);
                     write_once(path, data, *, root, mode) -> WriteOnceResult; replace_atomic(path, data, *, root, mode) -> None;
                     ensure_dir(path, *, root, mode=0o700) -> None; list_dir_at(dirfd) -> tuple[str, ...];
                     SingleReadRefused(reason: SingleReadReason)
  paths.py ★         AutonomyPaths(root) (validated builders; + root_record(model_class, sha, family_id), held to E-14) ; default_data_root()
  pins.py ★          literals only, no imports (AC 22)
  veto.py ★          VetoReason (15); compose_entry_vetoes(checks) -> VetoReason | None
  plugin.py          as r1 (Protocols with @property members; RefusingPlugin; is_complete)
  closure_manifest.py CLOSURE_MODULES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({})
  closure.py         closure_sha256(component) -> str; closure_from_grimp(entry) -> tuple[str, ...] (gate-only, lazy grimp)
  schemas.py         State, Kind, CauseClass, CauseCode, WriterMode, DecidedBy; TransitionRow; ExportTrailer;
                     ResolvedFamily ★(required state/entries_allowed); ResolverRefusal(reason: RefusalReason) ★; ManifestFacts ★
  stage_policy.py ★  StagePolicy (frozen: enabled_widening_kinds, admission_implemented, engine_source_sha256, revoked_source_sha256,
                     live_gate_routed_kinds, root_admit_enabled_ceiling); STAGE: Final[StagePolicy] = StagePolicy.from_pins()
  verdict.py         as r1 (C4 types, verdict_id, write_verdict, read_verdict)
  lineage.py         as r1 + ROOT model_class helper root_model_class(composition_kind) -> str ★
  label_schema.py    as r1 (only module importing pyarrow directly)
  demand.py          as r1 (no archive)
  drill_marker.py    as r1 (AUT-7 r5 12-key set)
  rollback_journal.py ★ JournalHead(seq, sha256) defined HERE; JOURNAL_KINDS = frozenset(); append_journal(paths, kind, venue, record,
                     *, ts_ns) -> JournalHead; read_journal_chain(paths, kind, venue) -> tuple[JournalEntry, ...] | JournalUnverified
  fold.py            fold(rows, venue, now_ns) -> FoldResult; resolve_champion(chain, now_ns); FoldResult, FamilyView, LineageView, LineageTallies
  transitions.py ★   ALLOWED; KIND_MASK; WIDENING_KINDS; RESTRICTIVE_KINDS; PAIR_KINDS; _ADMISSION_IMPLEMENTED; is_widening(row) -> bool;
                     transition_id(row) -> str; validate(prior: FoldResult, rows, *, mode: WriterMode | None, now_ns, stage,
                     manifests: ManifestFactsReader, export_counters: CounterSet | None = None) -> RefusalReason | None
  chain.py ★         genesis; transition_hash; VerifiedVenueChain; verify_venue_chain (contiguity, venue, monotone ts); verify_extension;
                     seq_is_verified_prefix; verify_against_export
  family_bytes.py ★  read_manifest_facts(paths, repo_root, family_id, manifest_sha256) -> ManifestFacts | FamilyBytesFailure;
                     verify_family_bytes(row, *, paths, repo_root) -> FamilyBytes | ByteBindingFailure  (AUT-7 API; single home for
                     prereg check + single read + parse_family_manifest + E-14 root record checks)
  registry_store.py ★ RegistryStore.initialise(paths); RegistryStore(paths).append(rows, *, expected_prior_seq, mode, now_ns) -> AppendResult;
                     _append(..., stage); write_export(venue, *, date, now_ns, journal_heads) -> ExportTrailer; RegistryReader;
                     newest_export(paths, venue) -> (ExportTrailer, rows) | ExportUnreadable | ExportAbsent; DDL constants
  hwm.py ★           Hwm(venue, venue_seq, chain_head, export_seq); HwmReading = HwmAbsent | HwmPresent | HwmUnreadable;
                     REGISTRY_HWM_KEY_PREFIX = "autonomy/registry_hwm/"; hwm_key(venue); Hwm.to_bytes/from_bytes; hwm_check(...)
  replay.py          replay_full(chain, *, paths, repo_root) -> ReplayOk | ReplayInvalid | ReplayCauseUnresolved | ReplayArtefactMismatch;
                     _replay_full(..., stage)
  net_position.py ★  LegFill; net_signed_qty(fills) -> Decimal  (no breezy.domain import)
  entry_guard.py ★   GuardResult; FillIndexAbsent; FillRow; FillReader Protocol (fill_index, fill_record, open_intent_blocks);
                     rung_has_net_position(base_slug, *, reader, venue_suffix) -> GuardResult; guard_veto_reason(result)
  resolver.py ★      FamilySource; read_family_source(env); resolve_sending_family(...) ; _resolve(..., stage, lineage_gate);
                     manifest_equal_modulo_allowlist(child, root, *, fields_of=dataclasses.fields) -> tuple[str, ...]
strategy/autonomy/node_plugins.py     NODE_PLUGINS
analysis/autonomy/offline_plugins.py  OFFLINE_PLUGINS
```

**Closed `RefusalReason`** (security M8; `test_resolver_refusals_give_no_champion` asserts by AST that the enum members equal the test params):

`registry_unreadable, empty_chain, chain_broken, clock_invalid, clock_before_head, hwm_unreadable, hwm_absent, hwm_regressed, export_unreadable, export_prefix_mismatch, widening_kind_not_enabled, admission_pending, replay_invalid, replay_cause_unresolved, replay_artefact_mismatch, engine_inconsistency, no_sender, engine_code_unpinned, engine_code_revoked, manifest_unreadable, manifest_invalid, manifest_draft, manifest_unpinned, prereg_ineligible, manifest_sha_mismatch, manifest_identity_mismatch, kind_not_live_gate_routed, artefact_unreadable, artefact_sha_mismatch, root_record_mismatch, child_not_equal_root, root_not_lineage_allowlisted, ruling_not_policy, ruling_refused, no_live_orders_ruling, d0_breach, trial_prefix_mismatch`.

**Storage layout.** As in r1 under `/home/jon/.local/share/breezy/`. Directories are created 0700 and **explicitly** chmodded, so the result does not depend on umask 0002 (V5). Files are 0600, or 0444 when content-addressed. Changes from r1:
- Root copies use `derived/artefacts/<kind>:density_table/<sha>/{artefact.json, roots/<family_id>.json}` (E-14). Both directories go to 0500 only after the genesis transaction's last copy. That chmod is the AUT-5a bootstrap's.
- The export trailer is `{"schema":"registry_export/v1","venue","venue_seq","chain_head","export_seq","evidence_journal_heads"}`. It widens AUT-5 r7 §3.2's three-key trailer; see §ERRATA-REQUEST (b).

**Data flow.** As in r1's diagram, plus:
- `store.append → family_bytes.read_manifest_facts`, for d0 and identity;
- `resolver → live_orders_gate.lineage_policy_authorized`;
- `resolver → family_bytes.verify_family_bytes`.

## Stub Surface for Wave 1 (table: symbol | consumer plan + section | ARCH-0 delivers real or stub)

"Real" means implemented and tested. "Stub" means the signature exists and fails closed with the owner named. "Owner" means the item is not in ARCH-0 at all (A-R6).

| Symbol / item | Consumer (plan § / line) | ARCH-0 |
|---|---|---|
| `VetoReason` (15), `compose_entry_vetoes` | AUT-1 r12 `:1237`; AUT-5 r7 §3.1 (re-points to an import) | Real. **No `EntryVeto` alias**: AUT-5a defines the callable type in strategy |
| `NODE_PLUGINS`, `OFFLINE_PLUGINS`, C6 Protocols, `RefusingPlugin` | AUT-1/2/3/4/6 | Real; every kind `RefusingPlugin` |
| Every `pins.*` in AC 22 | AUT-1/2/3/4/6/7 | Real. `SELF_HEAL_*` not shipped (E-11) |
| `ENGINE/PRODUCER/REVOKED_SOURCE_SHA256`, `closure_sha256` | AUT-5 WP4, AUT-4, AUT-6 | Real machinery, empty pins; owners add their own |
| `StagePolicy`, `STAGE`, `_ADMISSION_IMPLEMENTED` | AUT-5 WP1b, WP9, WP10 | Real, **empty** (`admission_implemented = ∅`) |
| `verdict.*`, `decimal_str` | AUT-2 `:943`; AUT-4 `:450`; AUT-6 `:512` | Real |
| `label_schema.*`, `lineage.*`, `drill_marker.*` | AUT-2/3/6/7 | Real |
| `demand.write_producer_demand`, `scan_demands`, `write_engine_demand` | AUT-6 WP5b; AUT-5 WP4/5 | Real |
| `rollback_journal.append_journal`, `read_journal_chain`, `JournalHead` | AUT-7 r5 `:91,:506` | Real envelope; `JOURNAL_KINDS = ∅` |
| `RegistryStore.append`, `KIND_MASK`, `WriterMode`, `transitions.validate` (every fold-decidable rule) | AUT-7 `:703`; AUT-5 WP4 | Real; widening kinds refused (`WideningNotEnabled`/`AdmissionPending`) |
| `RegistryReader`, `verify_*`, `fold`, `resolve_champion`, tallies | AUT-3/4/5/7 | Real |
| `resolve_sending_family`, `ResolvedFamily`, `HwmReading`, `hwm_*` | AUT-5 WP5/6/8; AUT-1 `:15`; AUT-6 WP6 | Real |
| `family_bytes.verify_family_bytes` | AUT-7 r5 `:703` (E10) | Real |
| `parse_family_manifest`, `lineage_policy_authorized`, `_LINEAGE_POLICY_ALLOWLIST` (empty) | resolver; AUT-5 WP9 | Real |
| `entry_guard.*`, `GuardResult`, `FillReader` | AUT-5 WP2/WP5 | Real (the adapter is AUT-5a's) |
| **Owner rows (moved items, A-R6, architect M6)** | | |
| Nomination k-checks, policy-stricter bounds, HWM_RESET store admission, per-kind `_ADMISSION_IMPLEMENTED` entries | AUT-5 **WP1b** (binding note) | Owner. Carried rows with `blocks_kinds` |
| `policy.load_policy_block` | AUT-5 WP3 | Owner |
| `demand.archive` and the 3 `test_demand_archive_*` | AUT-5 WP4 (bwrap EXDEV test, E-7a) | Owner |
| Derived caches `families`, `projection`, `lineage_counters` (DDL widening plus the reader's expected-DDL set) | AUT-5 WP4, before stage-S bootstrap | Owner |
| `halt_rows.py`, `runtime/submit_intent_record.py` (E-8 decoders) and their 3 tests | **AUT-5a**; AUT-6 aliases them (R4 closed by A-R6) | Owner |
| E-8a snapshot helper (bytes only) | ARCH-0 seam B | Other seam |
| AUT-5 r7 `schemas.py` records: `heartbeat/v1`, `halt_mirror/v1` (WP4); `stop_complete/v1`, `launch_event/v1` (WP6); `relaunch/v1` (WP7); `drawdown_control_active` (WP11) | AUT-5a WPs | Owner |
| Child artefact location and the four-site containment widening with the G34 fix (`test_containment_checks_read_directory_not_phantom_base`) | AUT-5a (AUT-5 WP2) | Owner. The resolver refuses children before reaching it (`widening_kind_not_enabled`) |
| `PolymarketUsFillReader` (exact keys, `open_intent_blocks` via E-8 decoders) | AUT-5a (AUT-5 WP2) | Owner |
| `_LINEAGE_POLICY_ALLOWLIST` row and the child routing inside `live_orders_authorized` | AUT-5 WP9 | Owner |
| `net_position.average_cost_basis` | AUT-2 WP2 (modifies the file) | Owner |
| `JOURNAL_KINDS` members, `verify_journal_chain` | AUT-7 | Owner |
| `sample_size.py`, `nomination.py` | AUT-4 (I-2) | Owner |
| `capture_*.py` | AUT-1a (E-12) | Owner; joins `NAUTILUS_PERMITTED` |
| C4.1 holdout ruling filing | Coordinator, Wave 0, alongside ARCH-0 (ARCH :379-393) | Owner (not code) |
| AUT-2 Wave-0 egress review | AUT-2a (ARCH :866-871; A-R6) | Owner |

## File-by-File Plan (absolute path | new|modified | exact content | deps)

| Absolute path | | Content | Deps |
|---|---|---|---|
| `/home/jon/breezy/src/breezy/persistence/__init__.py` | mod | Docstring only, citing NOTIFIER-IMPORT-ISOLATION (`runtime/__init__.py:15-25`) and the reachability test | — |
| `/home/jon/breezy/src/breezy/persistence/family_manifest.py` | mod | `parse_family_manifest` = `:296-460` moved verbatim. `load_family_manifest` = `:293-295` + call. `__all__` += 1 | — |
| `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py` | mod | AC 17. `live_orders_authorized` calls `_verify_ruling_file`, a move-only extraction of `:163-182` | family_manifest |
| `/home/jon/breezy/src/breezy/persistence/autonomy/{__init__,canonical,wire,single_read,paths,pins,veto,plugin,closure_manifest,closure,schemas,stage_policy,verdict,lineage,label_schema,demand,drill_marker,rollback_journal,fold,transitions,chain,family_bytes,registry_store,hwm,replay,net_position,entry_guard,resolver}.py` | new | As in Architecture; dependencies in the WP table | see WP table |
| `/home/jon/breezy/src/breezy/strategy/autonomy/{__init__,node_plugins}.py`, `/home/jon/breezy/src/breezy/analysis/autonomy/{__init__,offline_plugins}.py` | new | As r1, `MappingProxyType` literals | plugin |
| `/home/jon/breezy/pyproject.toml` | mod | Contracts (a) and (b) (AC 1). (b) lists core modules as they land. Comment: owners append engine-closure modules; `capture_*` are classified `NAUTILUS_PERMITTED` | — |
| `/home/jon/breezy/scripts/ci/regen_closure_manifest.py` | new | Deterministic, literal-only output. `test_regen_output_is_literal_and_reproducible` checks it with `ast.literal_eval` and a re-run byte-compare (security L4) | grimp |
| `/home/jon/breezy/tests/support/autonomy_owner.py` | new | `OwnerPending`; `require_owner_symbol` (AC 24) | — |
| `/home/jon/breezy/tests/support/entry_points.py` | new | The three `_entry_modules_from_*` helpers moved verbatim from `tests/unit/test_runtime_import_isolation.py:158-216` and re-imported there (move-only; that file's assertions are unchanged) | — |
| `/home/jon/breezy/tests/unit/autonomy_owner_placeholders.py` | new | `OWNER_PLACEHOLDERS` (4-tuples), `OWNER_REGISTRY` (owner id → plan file + anchor string) | — |
| `/home/jon/breezy/tests/unit/autonomy_blocks_kinds_floor.py` | new | `BLOCKS_KINDS_FLOOR` (separate file so a reviewer sees any lowering) | — |
| `/home/jon/breezy/tests/unit/autonomy_envelope_manifest.py` | new | `ARCH_FREEZE_SHA256`; `E11_RENAMES` (3 rows: `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` → `test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine`; `test_self_heal_cap_survives_process_restart` → `test_watchdog_unit_config_declares_notify_watchdog_restart_startlimit_and_notifyaccess_all`; `test_restart_window_resets_before_launch` → `test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical`, the ER-2 adopted name); `ENVELOPE_NODE_IDS` (full ids with params) | — |
| `/home/jon/breezy/tests/unit/autonomy_writer_table.py` | new | One-writer rows | — |
| `/home/jon/breezy/tests/fixtures/family_manifest_golden/` | new | 23-input corpus plus `expected.json` (AC 18) | — |
| Test files | new | See Test Strategy | — |
| `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` | **never edited** | byte pin V7 | — |

## Test Strategy (file | test names | unit/contract | which §4.7 rows are real-GREEN in ARCH-0 vs carried strict-xfail with owner)

**Carrying mechanism.** As AC 24.
- Pytest 9.1.1 behaviour was verified by python P-n6: a non-matching exception FAILs, and a strict XPASS FAILs.
- A test that is half real and half owner-held is parametrised with literal ids, `pytest.param(..., id="arch0")`.
- `test_every_envelope_node_id_collected_and_unskipped` has two halves. AST-derived ids are cross-checked by one `--collect-only -q` subprocess over the autonomy test files only. The test fails on any `skip`/`skipif`/`importorskip` mark or call on an envelope id (architect M3, security M10).

**Real-GREEN in ARCH-0.** Each test gets a RED log before implementation. Mutation evidence (L-33) is in brackets.

| File | Tests | Type |
|---|---|---|
| `tests/unit/test_persistence_import_free.py` | `test_persistence_init_has_no_import_nodes`; `test_persistence_has_no_facade_consumers`; `test_persistence_init_preserves_register_arrow_reachability` [re-adding no edge to the simulated graph makes it red]; `test_persistence_entry_module_imports_cleanly[*]` | contract |
| `tests/unit/test_family_manifest_split_golden.py` | `test_parse_split_matches_presplit_golden`; `test_load_family_manifest_keeps_prereg_check` | contract |
| `tests/unit/test_lineage_policy_allowlist.py` (AUT-5 WP9 file) | `test_lineage_policy_allowlist_is_literal_only` (ARCH); `test_child_requires_lineage_triple_and_policy_ruling`; `test_child_with_operator_ruling_refused`; `test_tampered_policy_ruling_refuses_child`; `test_lineage_gate_refuses_missing_ruling_file`; `test_lineage_gate_refuses_ruling_symlinked_outside_subtree`; `test_lineage_gate_refuses_child_id_outside_root_lineage` (incl. a Unicode-digit id); `test_lineage_decision_carries_no_permit_semantics`; `test_verify_ruling_file_extraction_keeps_reasons_and_messages` (golden over the existing refusal fixtures) | unit |
| `tests/unit/test_autonomy_canonical.py`, `test_autonomy_wire.py` | golden bytes; `-0`/`0E-10`/`1E+2`/`1.50`; NaN/Inf/exponent refusals; non-str key; float; lone surrogate; duplicate key; bool-as-int | unit |
| `tests/unit/test_autonomy_single_read.py` | `test_walk_refuses_symlinked_intermediate_dir`; `test_read_refuses_fifo_without_blocking`; `test_read_refuses_group_writable_under_strict`; `test_write_once_symlink_at_destination_with_equal_bytes_is_different`; `test_write_once_final_mode_by_stat` (0444, 0600); `test_write_once_link_unsupported_fails_closed`; `test_replace_atomic_writes_temp_in_target_dir_fsyncs_and_replaces`; size cap; one fd | unit |
| `tests/unit/test_autonomy_paths.py` | traversal vector per builder; `test_family_component_accepted_by_both_existing_id_patterns` | unit |
| `tests/unit/test_autonomy_contracts.py` | `test_every_autonomy_module_is_classified`; `test_autonomy_core_modules_nautilus_free_at_runtime`; `test_autonomy_policy_not_mutable_from_src` (with planted controls) | contract |
| `tests/unit/test_autonomy_envelope.py` | as r1, plus `test_autonomy_never_passes_allow_draft_true`; `test_exec_client_never_edited` reads the pin at `:36` | contract |
| `tests/unit/test_autonomy_pins.py` | as r1, plus `test_enabled_widening_kinds_subset_of_widening_kinds`; `test_enabled_widening_kinds_subset_of_admission_implemented`; `test_root_admit_enabled_requires_ceiling_true`; `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key[pins]`; `test_request_ttl_covers_two_schedule_polls`; `test_engine_pin_history_retained` and `test_code_identity_pins_cover_import_closure`, each with a fixture positive control (security M8); `test_regen_output_is_literal_and_reproducible` | unit |
| `tests/unit/test_autonomy_plugins.py` | as r1, plus `test_veto_reason_closed_set_equals_arch` (15); `test_compose_entry_vetoes_exception_is_registry_unreadable` | unit |
| `tests/unit/test_autonomy_owner_placeholders.py` | the 8 gate tests of AC 24, plus `test_require_owner_symbol_propagates_broken_owner_module` (planted) | contract |
| `tests/unit/test_autonomy_files_one_writer.py`, `test_launch_window_table.py` | as r1 | contract |
| `tests/unit/test_autonomy_verdict.py`, `test_autonomy_records.py`, `test_autonomy_demand.py`, `test_autonomy_journal.py` | as r1; demand `[writer_api]` | unit |
| `tests/unit/test_entry_guard.py` | `test_rung_net_position_veto_crosses_legs_and_families[double]`; `test_entry_guard_unreadable_index_vetoes`; `test_reconciliation_and_entry_guard_never_read_canary_store[entry_guard]`; `test_net_signed_qty_no_leg_is_short_yes` (each leg's terminal state, L-44); `test_negative_net_vetoes`; `test_empty_index_is_unreadable`; `test_open_intent_is_unreadable`; `test_bad_slug_is_unreadable`; `test_guard_body_exception_is_unreadable`; `test_leg_suffix_equals_instrument_leg`; `test_autonomy_exec_keys_disjoint_from_halt_prefixes` | unit |
| `tests/unit/test_registry_store.py` | as r1, minus `[store_atomic]` and `test_repeat_supersede…[store]`. Plus: `test_repeat_supersede_same_family_is_not_replay[arch0]` (transition_id); `test_store_multirow_append_is_atomic`; `test_insert_or_replace_refused` [dropping the INSERT trigger and the pragma makes it red]; `test_on_conflict_do_update_refused`; `test_venue_seq_gap_refused_by_trigger`; `test_partial_replay_refused`; `test_append_requires_concrete_mode`; `test_row_ts_skew_and_monotonicity_refused`; `test_writer_pragmas_read_back`; `test_store_sql_has_no_replace_or_ignore` (AST); `test_admission_pending_refused_when_enabled_but_unimplemented`; `test_reader_refuses_foreign_ddl` [dropping one trigger in the fixture DB makes it red]; `test_reader_maps_every_sqlite_error`; `test_reader_after_killed_writer_is_unreadable`; `test_child_d0_and_trial_prefix_pinned[store]` (via `_append` with a fixture stage); `test_hwm_reset_store_refuses_carried_counters_below_export[validate]` | unit |
| `tests/unit/test_registry_fold.py` | r1 list, plus every fold or validate test in the "promoted" list below | unit |
| `tests/unit/test_registry_replay.py` | r1, plus `test_replay_refuses_carried_counters_below_prior_fold` | unit |
| `tests/unit/test_registry_resolver.py` | r1 list, plus `test_resolver_refuses_chain_with_unenabled_widening_row` (hand-forged chain, L-24); `test_hwm_absent_with_rows_refuses`; `test_hwm_unreadable_refuses`; `test_export_absent_after_hwm_saw_export_refuses`; `test_clock_before_head_refuses`; `test_two_senders_is_engine_inconsistency`; `test_manifest_identity_must_match_row`; `test_live_gate_routing_reads_manifest_kind`; `test_equality_covers_new_manifest_fields` (synthetic field); `test_halted_sender_resolves_with_entries_disallowed`; `test_resolver_never_returns_enabled_or_permit`; `test_draft_or_unpinned_manifest_refused`; `test_resolver_runs_prereg_check_on_source_dir`; `test_root_record_identity_checked` (E-14) | unit |

**Promoted to real in ARCH-0** (r1 carried them; A-R3 and security Q5):
- `test_drill_promote_refuses_non_champion_sha`
- `test_drill_refused_over_halted_incumbent`
- `test_drill_budget_separate`
- `test_drill_demote_and_halt_counters_capped`
- `test_drill_row_refused_while_non_drill_cause_stands`
- `test_resume_requires_every_cause_cleared`
- `test_rollback_failed_resumes_only_under_trigger_class`
- the four E-5 tests: `test_drill_close_restore_at_most_one_per_venue_per_day`, `…_refused_for_drill_child`, `…_charges_no_drill_or_production_budget`, `…_refused_after_non_drill_cause`
- `test_child_d0_and_trial_prefix_pinned[store]` (`[validate]` and `[resolver]` are new or kept)
- `test_damping_ceilings[counting_rule]`
- `test_carried_counters_are_floors`

Newly added real tests:
- `test_root_admit_exempt_from_d0_rule`
- `test_root_admit_only_when_venue_has_no_sender[validate]`
- `test_post_launch_swap_cancel_voids_pair_only_before_1700`
- `test_post_launch_swap_cancel_restores_incumbent[fold]`
- `test_hwm_reset_store_refuses_carried_counters_below_export[validate]`
- `test_replay_refuses_carried_counters_below_prior_fold`
- `test_resolver_refuses_chain_with_unenabled_widening_row`
- the lineage-gate sha tests
- `test_hwm_absent_with_rows_refuses`

**AUT-5 r7 WP1/WP2 RED-test crosswalk (architect M1).** WP1 lists 85 tests and WP2 lists 16. The rows below sum to those counts.

| AUT-5 r7 list (count) | ARCH-0 real | Split: real half / owner half | Moved (owner) |
|---|---|---|---|
| WP1 envelope (6) | all 6 | — | — |
| WP1 store (26) | 17: `transition_table_is_exact`, `bootstrap_seed_genesis_only`, `cas_and_idempotent_replay`, `hash_chain_and_triggers`, `readonly_open_engine_stopped`, `family_artefact_binding_immutable`, `store_enforces_kind_mask_per_mode`, `daily_refuses_widening_before_stage_flag`, `mint_unlimited_by_k_max_but_one_per_day`, `drill_mint_not_counted`, `rollback_to_earlier_child_passes_d0_rule`, `resume_not_subject_to_d0_rule`, `root_admit_exempt_from_d0_rule`, `export_seq_monotone_and_newest_wins`, `store_refuses_second_bootstrap_per_venue`, `drill_close_restore_at_most_one_per_venue_per_day`, `drill_close_restore_refused_for_drill_child` | 4: `repeat_supersede…` [arch0 / store→WP1b]; `nomination_columns…` [columns_required / k_check→WP1b]; `child_d0_and_trial_prefix_pinned` [validate, store, resolver all real]; `hwm_reset_store_refuses_carried_counters_below_export` [validate / store→WP8] | 5 → AUT-5 WP1b: `nomination_refused_past_k_max_lifetime`, `…_second_in_window`, `alpha_index_never_resets`, `two_pending_nominees_get_distinct_k`, `infeasible_nomination_charges_no_alpha[store]` |
| WP1 fold (25) | 24, the whole list except the split | 1: `root_admit_only_when_venue_has_no_sender` [validate / engine→WP4] | — |
| WP1 replay (4) | all 4 | — | — |
| WP1 demand (7) | 3: flood, unlisted, idempotent | 1: `producer_demand_write_is_restrictive_only` [writer_api / aut6_producer_ast→AUT-6] | 3 → AUT-5 WP4: `demand_archive_*` |
| WP1 single read, one writer, plug-ins, ledger (5) | all 5 | — | — |
| WP1 pins and closure (8) | 6 | 1: `drawdown_inert_ceiling_is_pins_literal_not_policy_key` [pins / policy→WP3] | 1 → WP3: `policy_map_not_looser_than_fallback_map` |
| WP1 E-7/E-8 (4) | 1: `registry_reader_mode_ro_query_only` | — | 3 → AUT-5a: `submit_intent_record_*` |
| **WP1 total 85** | **66** | **7** | **12** |
| WP2 resolver (11) | 8: `binds_bytes_to_row`, `registry_paths_refuse_symlinks`, `child_manifest_equals…`, `exit_gate_stays_code_only`, `refusals_give_no_champion`, `root_resolves…`, `rollback_to_root_reads…`, `family_source_registry_requires_bootstrap` | 2: `verify_and_load_share_bytes` [resolver / loader→WP5]; `registry_champion_requires_live_orders_gate…` [resolver / engine→WP4] | 1 → AUT-5a: `containment_checks_read_directory_not_phantom_base` |
| WP2 entry guard (5) | 2: `unreadable_index_vetoes`, `…canary_store[entry_guard]` | 1: `rung_net_position_veto…` [double / adapter_reader→AUT-5a] | 2 → AUT-5a: `entry_guard_exact_key_reads_only`, `fill_reader_production_default_runs_once` |
| **WP2 total 16** | **10** | **3** | **3** |

**Carried strict-xfail stubs.** These live in `tests/unit/test_autonomy_cross_area.py` unless named. Each row is a stub with an `owner_symbol`; `[blocks]` is given where applicable. r1's carried table stands with these r2 changes:
- (a) every test promoted above is removed from it;
- (b) E-11 renames are applied to the carried AUT-5 r7 rows: `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` → `test_watchdog_units_are_literal_and_exclude_trade_supervisor_engine` (owner AUT-6);
- (c) the r1 wildcard `test_drill_close_restore_*` row is gone, because all four are real;
- (d) the AUT-5 WP1b rows are now: the 5 nomination tests and `…[k_check]` [PROMOTE]; `test_repeat_supersede_same_family_is_not_replay[store]` [SUPERSEDE, PROMOTE]; `test_prelaunch_writes_rollback_and_activate_atomically[store_atomic]` [ROLLBACK, ACTIVATE]; `test_resume_admission_reads_policy_block_bounds` [RESUME]; `test_hwm_reset_store_refuses_carried_counters_below_export[store]` (owner AUT-5 WP8) [HWM_RESET];
- (e) the 7 AUT-5 r7 ledger rows that are not §4.7 names are added (architect M2):
  - AUT-6: `test_shadow_detector_ignores_production_marker`, `test_production_detector_ignores_shadow_marker`, `test_fee_schedule_verdict_feeds_fee_verified_checks`, `test_shadow_probe_marker_accepted_only_under_shadow_root`;
  - AUT-2: `test_post_stop_producer_inconclusive_without_stop_signal`;
  - AUT-2 + AUT-5 WP11: `tests/unit/test_drawdown_producer.py::test_drawdown_gates_on_labels_consumable`;
  - AUT-7: `test_failed_drill_close_restored_at_next_prelaunch` [RESUME];
- (f) moved items: `test_policy_map_not_looser_than_fallback_map` and `…[policy]` (WP3); `test_demand_archive_*` ×3 (WP4); `test_post_launch_swap_cancel_restores_incumbent[supervisor]` (WP6); `test_submit_intent_record_*` ×3 and `test_containment_checks_read_directory_not_phantom_base`, `test_entry_guard_exact_key_reads_only`, `test_fill_reader_production_default_runs_once` (AUT-5a).

Every existing envelope test passes **unmodified** after every WP: `test_operator_control_assignment_scan`, `test_execution_egress_firewall_guard`, `test_shadow_only_false_is_only_the_gate_output`, `test_live_orders_ruling_deploy_copy_matches_evidence`, `test_native_order_cap_wiring` and `test_risk_engine_ordering_enforcement`. So do `test_fq_live_orders_gate.py`, `test_family_manifest.py`, `test_runtime_import_isolation.py` and `test_forecast_quantile_ladder_manifest_and_markers.py`. Coverage is reported per WP; no threshold is invented.

## Work Packages (split into 2–4 commit-sized, independently-gated WPs with order; each ≤ ~800 changed lines)

**Honest sizing (A-R5, python B4, architect H6c).** The total is about 11,000 changed lines: about 4,300 src and about 6,700 tests, fixtures and stubs. That cannot fit into 2–4 WPs of 800 lines. The plan has **8 WPs**, each with a named split seam, so up to 15 commits. Order is **linear** (1→…→8). Merges are serial with the full gate after each (L-43). The dependency table shows that linear is also the true order (architect H4). Carried stubs land with the WP that ships their nearest ARCH-0 symbol. Stubs with no ARCH-0 symbol land in WP-4.

| WP | Modules / files | Imports (ARCH-0 modules) | Est. lines (src + tests) | Split seam | Activation |
|---|---|---|---|---|---|
| **WP-1 Live-path prep** | `persistence/__init__`; `family_manifest` split + golden corpus; `live_orders_gate` (extraction, lineage gate, empty allowlist); `tests/support/entry_points.py`; import-free, golden and lineage tests | none (existing modules only) | 200 + 1,100 | 1a = init + split; 1b = `live_orders_gate` | **Live.** Merge outside [16:30Z, 17:10Z) (M11). Node: next 16:50Z LAUNCH. Supervisor: restart in 01:00–16:40Z (`KillMode=process` keeps the node). Recorder and ingest pick it up at their next natural start. Technical reason for not forcing those restarts: no behaviour change, proven by the per-entry smoke and the reachability audit, and a forced recorder restart costs capture continuity |
| **WP-2 Bytes and I/O** | `canonical`, `wire`, `single_read`; contracts (a)/(b) seeded; classification and runtime-import tests | canonical ← —; wire ← canonical; single_read ← — | 650 + 750 | 2b = `single_read` | None (library; no caller until AUT-5a) |
| **WP-3 Pins, plug-ins, guard** | `paths`, `pins`, `veto`, `plugin`, `closure_manifest`, `closure`, regen script, `node_plugins`, `offline_plugins`, `net_position`, `entry_guard` | paths ← wire; closure ← single_read, closure_manifest; plugin ← veto; entry_guard ← net_position, veto | 900 + 900 | 3b = `net_position` + `entry_guard` | None |
| **WP-4 Ledger and envelope** | `tests/support/autonomy_owner.py`, ledger, floor, envelope manifest, writer table, gate tests, envelope scans, launch-window test, stubs with no ARCH-0 symbol | pins (blocks_kinds) | 0 + 1,500 | 4b = ledger + stubs | None |
| **WP-5 Records** | `verdict`, `lineage`, `label_schema`, `demand`, `drill_marker`, `rollback_journal` (with `JournalHead`) | all ← wire, canonical, single_read, paths, pins | 800 + 900 | 5b = `demand` + `drill_marker` + `rollback_journal` | None |
| **WP-6 Store core** | `schemas`, `stage_policy`, `chain`, `transitions` (ALLOWED, mask, structural validate), `family_bytes`, `registry_store` (DDL, triggers, append, reader, export); store tests | schemas ← wire, canonical, rollback_journal; stage_policy ← pins, transitions; chain ← canonical, schemas; family_bytes ← single_read, paths, family_manifest, mechanism_test_guard, lineage; registry_store ← all of these + a stub fold | 1,000 + 1,000 | 6b = export writer/reader | None |
| **WP-7 Fold and rule set** | full `fold`; the `validate` rule set (AC 13); `hwm`; fold and rule tests | fold ← schemas, pins; transitions ← fold; hwm ← wire, schemas, chain | 900 + 1,100 | 7b = rule set + hwm | None |
| **WP-8 Replay and resolver** | `replay`, `resolver`; final contract (b) list; resolver and replay tests | replay ← transitions, fold, verdict, chain, family_bytes; resolver ← all + live_orders_gate | 700 + 1,100 | 8b = resolver | None until AUT-5a sets `BREEZY_FAMILY_SOURCE` |

**Every WP brief restates these binding invariants verbatim:**
1. Nautilus Trader is immutable: never modified, patched, forked or bypassed.
2. Operator-reserved controls (max daily budget, max per position) are never assigned, read, passed or computed by autonomy code. No brief or code names their environment variables (L-39).
3. Live-trading enablement, the order-submission permit and the NO-SEND execution-egress firewall are untouched. The resolver never yields permit semantics: no `enabled` field, `permit_present=False`, and only `permit_absent` is accepted.
4. `allow_short` stays `False`.
5. No safety, settlement or contract test is weakened or deleted. The listed existing tests pass unmodified. The `parse_family_manifest` split is proven byte-equivalent by the pre-split golden. The `_verify_ruling_file` extraction keeps reasons and messages.
6. `src/breezy/adapters/polymarket_us/exec/client.py` is byte-pinned (`76784ce8…`) and is never edited.
7. Use the exact interpreter `/home/jon/breezy/.venv/bin/python`. Never `uv`, `pip` or any installer. Never `git stash`. In a worktree, `PYTHONPATH=<wt>/src`. Run `cd <tree> && .venv/bin/lint-imports` and get "N kept, 0 broken". Read the gate exit code explicitly. Commit by explicit path only.

## Binding note for the AUT-5a brief

The coordinator copies this section into the AUT-5a brief. It answers architect H1 and A-R1.

1. **AUT-5 WP1b ("admission completion") is a named AUT-5a work package.** It is scheduled before AUT-5 WP10 stage L1. Its scope:
   - (a) thread the filed policy block's stricter values into `transitions.validate` (the policy block comes from WP3's parser, and the ceilings remain the bound);
   - (b) nomination k-checks and window slots for SHADOW→CHALLENGER PROMOTE, replacing `NominationRequiresPolicy`;
   - (c) HWM_RESET store admission, jointly with WP8: the B9 export-floor read inside `append` plus a step-3 restrictiveness check, replacing `RuleSetPending`;
   - (d) a per-kind completeness review of `validate` against ARCH C5 and AUT-5 r7 §3.2 steps 1–9;
   - (e) adding each kind to `transitions._ADMISSION_IMPLEMENTED` **in the same commit** that clears its `blocks_kinds` ledger rows. `test_owner_placeholder_symbol_absent` and `test_widening_kind_enabled_only_when_its_placeholders_cleared` enforce this.
2. **RESUME subset, merged before the L1 pins commit `ENABLED_WIDENING_KINDS = {RESUME}`:**
   - policy-threaded `RESUME_COOLDOWN_H`, `MAX_RECOVERABLE_RESUMES_PER_LINEAGE_14D`, `MAX_INFRA_RESUMES_PER_VENUE_7D` and `MAX_SENDER_CHANGES_PER_VENUE_PER_DAY` (`test_resume_admission_reads_policy_block_bounds`);
   - the ARCH-0 rules already real, re-reviewed: every standing cause cleared; ROLLBACK_FAILED only under the trigger class; E-5 `drill_close_restore` (including AUT-7's `test_failed_drill_close_restored_at_next_prelaunch`); swap-pending refusal; terminal and INTEGRITY freezes; the PRELAUNCH-only mask;
   - then `_ADMISSION_IMPLEMENTED = {RESUME}`.

   `test_enabled_widening_kinds_subset_of_admission_implemented` makes the L1 pins commit red without it. **All other widening kinds** need WP1b to be complete before the L2 flag commit (AUT-5 WP9's second commit).
3. **`_ADMISSION_IMPLEMENTED` is code, not a pin.** Only the WP that implements a kind's admission adds it. It is read through the frozen `stage_policy.STAGE`, never rebound (AC 15).
4. **Narrowing semantics.** Once rows of a kind exist on a production chain, narrowing `ENABLED_WIDENING_KINDS` below that kind makes the resolver refuse `widening_kind_not_enabled`, which means no sender. WP10's activation rollback after Y7 binds must re-enable through a reviewed commit, or use `breezy-registry-hwm-reset` per ARCH. A narrowing commit is never the rollback lever.
5. **HWM is tri-state.** The supervisor and node read `autonomy/registry_hwm/<venue>` from the exec store read-only (G6). They pass `HwmAbsent` only for a missing key and `HwmUnreadable` for any read or decode error. The watch actor writes `Hwm.export_seq` = the export it verified.
6. **Other obligations:**
   - import `VetoReason` from `persistence/autonomy/veto.py`, do not define it;
   - the callable `entry_veto` type lives in strategy (`Callable[[InstrumentId], VetoReason | None]`);
   - drop the package-wide Nautilus ban (AUT-5 r7 `:841`) in favour of contract (b) plus classification;
   - `append` takes the extra required `now_ns`;
   - E-8 decoders (`halt_rows.py`, `submit_intent_record.py`) are AUT-5a's, and AUT-6 aliases them;
   - the derived caches DDL is AUT-5 WP4's, before the stage-S bootstrap.

## Risk Register

| # | Risk | Evidence | Mitigation / owner |
|---|---|---|---|
| R1 | Root-copy collision (`pm_us_crh_v4`/`_cont` share kind and sha `247f6363…`) | ARCH :261; deploy manifests (verified) | E-14 as amended (§ERRATA-REQUEST). WP-5/6 hold `paths.root_record` and its tests until filed. Fail-closed either way |
| R2 | Contract (b) vs E-12 | AUT-1 r12 :229-238 | Explicit list plus the classification test (AC 2) |
| R3 | `VetoReason` location / `EntryVeto` name collision | AUT-5 r7 §3.1; AUT-1 r12 :433 | `veto.py`, no alias (AC 20) |
| R4 | Halt-decode double extraction | AUT-5 r7 :117; AUT-6 r15 :1664 | **Closed by A-R6**: AUT-5a owns, AUT-6 aliases |
| R5 | `drill_marker/v1` field sets differ | AUT-5 r7 :692; AUT-7 r5 :363 | Ship AUT-7's 12 keys |
| R6 | `net_position` ordering and domain weight | AUT-2 r7 :68,:116; V1 | ARCH-0 creates it without a domain import; AUT-2 modifies it under contract (b) |
| R7 | Removing the persistence facade drops an eager `register_arrow` side effect | `runtime/__init__.py:27-44` precedent | Grimp reachability test per entry plus a fresh-process smoke; revert is one file |
| R8 | WP sizes | estimates | 8 WPs, a named seam each |
| R9 | A carried test xfails for the wrong reason or goes stale | — | Narrow `OwnerPending` (AC 24), stale-symbol test, owner-id doc check |
| R10 | Early widening through a pins commit merged without a gate run | memories `supervisor-unit-is-symlinked…`, `activate-code-immediately` | Three code-level locks: stage flag, `_ADMISSION_IMPLEMENTED` and the resolver refusal (H1). Gate tests are a fourth, not the only one |
| R11 | Concurrent agents in one tree | L-51 | Per-WP worktree from the feature head; re-gate before merge |
| R12 | `unshare -r` runs as uid 0 | `run_tests_no_egress.sh:45-50` | Modes asserted by `stat`; SQLite `mode=ro` |
| R13 | Orphaned ingest timer row in the launch-window test | AUT-6 r15 :1656 | Verify-first in WP-4 (read `TimeoutStartSec`), then a data-path row or an owner row |
| R14 | Same-uid consistent forgery | ARCH C5 | Accepted residual. H1/H2/H3 keep the external anchors honest |
| R15 | **Demand-flood DoS**: any same-uid writer causes a venue veto until AUT-5 WP4's archive exists | security L2 | Fail-closed and accepted; restrictive only |
| R16 | **Narrowing the stage flag after rows exist refuses resolution** | H1 fix | Binding note 4 |
| R17 | Resolver closure carries pyarrow (about 48 MB) | V2 | Accepted against the 4 G own-lock budget |
| R18 | `pins.py` is excluded from `closure_sha256` by ARCH design, so the enable flags are not covered by the engine code hash | security L3 | Covered instead by `live_proof_paths()` (AUT-5 WP4) and the reviewed-commit rule |
| R19 | WP-1 is live-path | M11 | Merge window and supervisor restart window stated in the WP table |

## LESSONS Compliance

Every number below was checked against its `docs/core/LESSONS.md` header on 10-03. r1's L-25 citation is dropped: its header is about fills better than the displayed ask, which does not apply here.

| Lesson | How the plan complies |
|---|---|
| L-1 | Null-hypothesis table below |
| L-12 | Exact-set schemas; the manifest split is a pure move proven by a golden; the lineage allowlist ships empty; `CAUSE_CODES` grows only by a reviewed widening |
| L-14 | `RefusalReason` and `VetoReason` are derived from ARCH's closed lists; AST enum = params |
| L-16 | No timer code; the library returns values, and an exception in a veto composer is `registry_unreadable` |
| L-19 | The facade removal's blast radius was simulated on a scratch copy (V2) and the reachability audit is a test |
| L-22 | Frozen `STAGE` and private seams make the exclusions unforgeable rather than offered |
| L-24 | The resolver H1 test uses a hand-forged chain that bypasses `append` |
| L-29 | No diagnostics buffers; module-level mutables are banned |
| L-33 | Mutation evidence per guard test |
| L-39 | No plan text or code names an operator-control environment variable; scan tokens come from `operator_controls.py:142` |
| L-42 | Guard fixtures use the real `DurableFillRecord` shape; the real-writer leg is AUT-5a's `[adapter_reader]` |
| L-43 | Full gate after every WP merge |
| L-44 | `net_signed_qty` is tested at each leg's terminal state |
| L-46 | Contract tests grepped first: archive contract (`pyproject.toml:137-141`), probe containment, exec pin |
| L-47 | Every new code fact carries a file:line or a probe (V1–V10) |
| L-48 | Journal and demand failures never block restrictive writes |
| L-50 | Writer table plus write-once |
| L-51 | Exact interpreter; no `uv`, `pip` or `stash` |
| L-54 | No conftest or shared-config edit; `tests/support/entry_points.py` is a move-only extraction |
| L-55 | `[adapter_reader]` runs the production `FillReader` once (AUT-5a) |

**L-1 null-hypothesis rows.** r1's rows stand. They were verified and no reviewer disputed them: C5 store; exact-set records; atomic files; single read; `mode=ro` reader; resolver checks; netting; C6; closure; journal. r2 adds:

| Component | Native / existing checked | Verdict |
|---|---|---|
| Lineage ruling verification | `live_orders_authorized:163-182` | **Reuse** by move-only extraction (`_verify_ruling_file`) |
| Package import isolation | `runtime/__init__.py` precedent; `test_runtime_import_isolation.py` | **Reuse** the method and helpers (moved to `tests/support`) |
| Append-only enforcement | SQLite triggers (V4) | **Native SQLite**: a BEFORE INSERT trigger plus `recursive_triggers` |
| Strict JSON parsing | stdlib `json` hooks | **Reuse** stdlib (`object_pairs_hook`, `parse_constant`, `parse_float`) |

## Trade-offs (options considered, evidence, choice)

| Decision | Options | Choice and evidence |
|---|---|---|
| `persistence/__init__` | lazy PEP 562 (r1, AUT-4 AH5); delete the facade | **Delete.** Zero consumers (V3). Repo precedent rejected a lazy facade for exactly this reason (`runtime/__init__.py:15-25`). Failures surface at import, not first use (M9). AUT-4's closure goal is met identically |
| Lineage ruling check | new code; reuse by extraction | **Extraction** (DRY; security H2 "reuses the same checks"). Live-path risk is covered by unmodified tests plus a message golden |
| Policy-ruling decision shape | security's `permit_present` parameter; no permit | **No permit parameter** (M7). WP9 combines with the node's permit |
| Fold-decidable rules | defer to WP1b (r1); implement in ARCH-0 | **Implement** (A-R3). WP1b keeps policy-dependent and engine-dependent admission |
| Unenabled widening rows | store-only (r1); resolver also refuses | **Both** (H1), accepting the narrowing semantics (R16) |
| Derived caches | ARCH-0; AUT-5 WP4 | **WP4** (YAGNI; never read by node, supervisor or resolver; no production DB before AUT-5a) |
| Mode bits on read | strict everywhere; per-policy | **STRICT for autonomy data, REPO for git files** (V5: 0664 under umask 0002) |
| WP count | 4 (r1); 8 | **8** (honest sizing, A-R5) |
| Scope deferral of records without a registry-path consumer (security observation) | defer `label_schema`, `lineage`, journal, marker | **Keep in ARCH-0**: ARCH §5.1 assigns them and Wave 1 consumers need them |

## Confidence Self-Assessment (HIGH|MEDIUM|LOW + explicit unknowns)

**MEDIUM-HIGH.** Every HIGH finding is closed with code-level enforcement and verified facts. Remaining unknowns:
1. E-14 needs filing before WP-5/6 merge `paths.root_record`.
2. WP-7's rule-set size may use its seam.
3. The initial `CAUSE_CODES` and `DEMAND_REASONS` members are a closed choice. AUT-5 WP4 may widen them through a reviewed L-12 change.
4. The quote-tape-ingest `TimeoutStartSec` is verified first in WP-4 (R13).
5. AUT-5a must accept the binding note, and the coordinator must append WP1b to its brief.
6. The ARCH C4 field list is checked in WP-5 for any JSON-number non-integer field. If one exists, the WP stops and raises it to the coordinator (the float-refusal rule).
7. The grimp reachability test's run time in the gate is not yet measured. The budget is ≤ 10 s; otherwise it moves to a one-time Stage 0 measurement plus T9-style smoke tests, following the precedent.

## §R2 Disposition

| Finding | Disposition | Plan section |
|---|---|---|
| python B1 = architect H3 (domain loads Nautilus; pyarrow claim) | FIXED: no domain import; contract (b) forbids domain and pyarrow; per-module runtime test; pyarrow cost measured and accepted | AC 1, 3, 19; R6, R17 |
| python B2 (REPLACE bypass) | FIXED: BEFORE INSERT trigger, `recursive_triggers=ON`, AST ban, RED tests; chain verification is the backstop | AC 8, 9, 11 |
| python B3 (decimal and canonical holes) | FIXED | AC 5, 6 |
| python B4 = architect H6c (carried bodies unbudgeted) | FIXED: stubs of about 5 lines, assigned per WP; 8 honest WPs | Test Strategy; WPs |
| python B5 = security H5 (TOCTOU) | FIXED: openat walk, dirfd `write_once`, fchmod, nofollow EEXIST compare, `O_NONBLOCK` | AC 7 |
| python P-n1 (`write_once` mode, link fallback) | FIXED | AC 7 |
| python P-n2 = security M3 (partial replay, `mode=None`) | FIXED | AC 10 |
| python P-n3 (isolation level, pragmas) | FIXED | AC 9 |
| python P-n4 = security M4 (hot journal) | FIXED and documented | AC 12 |
| python P-n5 (uid 0) | Accepted as sound; kept | Edge Cases; R12 |
| python P-n6 (xfail fixture caveat) | FIXED: stubs are fixture-free | AC 24 |
| python P-n7 (lazy-init tests, `mock.patch`) | FIXED differently: facade deleted, no-consumer AST test covers `mock.patch` | AC 4 |
| python P-n8 (layers prose) | FIXED | Architecture |
| python P-n9 = architect H5 (classification, pyarrow) | FIXED | AC 1, 2 |
| python P-n10 (mypy, `@property`) | FIXED | AC 23, 25 |
| python P-n11 = security H6 (prereg dropped) | FIXED: callers keep the check, plus golden and `allow_draft` scan | AC 18 |
| python P-n12 (LESSONS) | Passed; L-25 dropped on re-check | LESSONS |
| python P-n13 (per-module subprocess test) | FIXED | AC 3 |
| security H1 (resolver honours unenabled widening) | FIXED | AC 16; Edge Cases |
| security H2 (no policy-ruling verifier) | FIXED: `lineage_policy_authorized`, private seam, negative cases. `permit_present` parameter REJECTED (M7) | AC 17 |
| security H3 (mutable pins) | FIXED: frozen `STAGE`, private seams, extended AST, subset gates | AC 13, 15 |
| security H4 (HWM and export bypass by absence) | FIXED: tri-state, genesis-only Absent, `export_seq` anchor, monotone ts. The node-marker variant REJECTED: a marker is another same-uid file; the genesis-only rule is stricter | Edge Cases; binding note 5 |
| security H6 | FIXED (see P-n11) | AC 18 |
| security H7 (guard fail-open) | FIXED: `GuardResult`, Absent vs empty, intent hook, `net != 0`, catch-all, composer | AC 19, 20 |
| security M1 (`venue_seq` hashed, contiguity) | FIXED | AC 11 |
| security M2 (`ts_ns` writer-supplied) | FIXED: skew, monotone, resolver clock check | AC 10, 11, 16 |
| security M4 | FIXED: schema/DDL equality, `trusted_schema`, explicit columns, snapshot, URI quoting | AC 12 |
| security M5 (path components) | FIXED, including `[0-9]{4}` with `re.ASCII` | Edge Cases; AC 17 |
| security M6 (hygiene leaks) | FIXED: enum reasons and value returns. "Role-label `path`" REJECTED: `path` drives containment (V9), so it would break byte-equivalence | AC 5, 16; Edge Cases |
| security M7 (`permit_present`) | FIXED | AC 16 |
| security M8 (unenumerated refusals) | FIXED: closed enum, `fields()`-driven equality, HALTED field, positive controls | AC 16; Architecture |
| security M9 (boot vs runtime failure) | FIXED: facade deleted plus per-entry smoke | AC 4 |
| security M10 / Q5 (param deletion; ledger self-consistency; real list) | FIXED: node ids with params, floor file, owner-id check, promoted list | AC 24; Test Strategy |
| security M11 (WP-D activation window) | FIXED, now WP-1 | WP table |
| security L1–L5 | FIXED: docstring (AC 21), R15, R18, regen test, residual in header | as cited |
| security observation (defer records) | REJECTED: ARCH §5.1 assigns them; Wave 1 consumers | Trade-offs |
| architect H1 (WP1b slot; test-only enforcement) | FIXED: binding note, `_ADMISSION_IMPLEMENTED`, subset test, atomicity via the restrictive pair | AC 13; binding note |
| architect H2 (register_arrow audit) | FIXED | AC 4 |
| architect H3 | FIXED (= python B1) | AC 1, 3 |
| architect H4 (hidden WP dependencies) | FIXED: `hwm` to WP-7, `JournalHead` in WP-5, linear order, dependency table | WPs |
| architect H5 | FIXED (= P-n9) | AC 2 |
| architect H6a/b/c | FIXED: narrow `OwnerPending`, stubs with `owner_symbol`, stale test, per-WP assignment | AC 24 |
| architect M1 (crosswalk) | FIXED: 85/16 rows reconciled | Test Strategy |
| architect M2 (ledger contents) | FIXED: E-11 renames, no wildcards, ER-2 name pinned, 7 rows added | Test Strategy; §ERRATA (b) |
| architect M3 (envelope list hand-copied) | FIXED: derived from the frozen ARCH sha; collected ids; skip ban | AC 24 |
| architect M4 (`veto.py`) | FIXED: 15 members, no alias | AC 20 |
| architect M5 (E-14) | FIXED: text with the five amendments | §ERRATA-REQUEST |
| architect M6 (unowned items) | FIXED: owner rows | Stub Surface |
| architect L1 (dict literals) | FIXED (`MappingProxyType`) | AC 22 |
| architect L2 (omitted pins) | FIXED | AC 22 |
| architect L3 (`__getattr__` typing) | Moot: no `__getattr__` (facade deleted) | AC 4 |
| architect L4 (trailer widening acknowledgement) | FIXED: requested as an amendment | §ERRATA (b) |
| architect L5 (verdict date verify-first) | FIXED: AUT-4 r11 :450 consistent (slot-anchored `valid_until`); AUT-6 r15 :512 has an unspecified date and must call `write_verdict` | §ERRATA (b) |
| A-R4 (WP holds `root_record`) | FIXED | R1 |
| A-R6 (out of scope) | FIXED | Stub Surface |

## §ERRATA-REQUEST

**(a) E-14, ready to file verbatim:**

> **E-14 (coordinator, 2026-10-03; from ARCH-0 seam A r1/r2 and the r1 architect review M5): per-family root records.**
> - **Defect.** ARCH C3 "Bootstrap roots" (line 261) writes one `root.json` per `derived/artefacts/<model_class>/<sha>/`. `pm_us_crh_v4` and `pm_us_crh_cont` are both `continuous_rung_hold` with `density_artefact_sha256 = 247f6363…` (the `not_applicable_density.json` placeholder) and are both RETIRED seeds (line 738). Their `root/v1` bodies differ in `family_id` and `manifest_sha256`, so the second write-once returns EXISTS_DIFFERENT and the genesis BOOTSTRAP cannot complete.
> - **Rule.**
>   1. A root copy is written to `derived/artefacts/<model_class>/<sha>/artefact.json` (0444) and `derived/artefacts/<model_class>/<sha>/roots/<family_id>.json` (0444, `root/v1`, unchanged fields). This replaces `…/<sha>/root.json` in ARCH C3 line 261, in AUT-5 r7 §3.2 line 172 (Bootstrap) and line 180 (one-writer row), and in the AUT-7 r5 root-read rows (line 41 and `test_rollback_to_root_reads_content_addressed_copy`, line 569).
>   2. The model class of a root copy is `f"{composition_kind}:{ROOT_ARTEFACT_COMPONENT}"` with the literal `pins.ROOT_ARTEFACT_COMPONENT = "density_table"`. A root's artefact is its manifest's density artefact.
>   3. The resolver reads `roots/<row.family_id>.json` and refuses (`root_record_mismatch`) unless `record.family_id == row.family_id`, `record.manifest_sha256 == row.manifest_sha256`, `record.artefact_sha256 == row.artefact_sha256`, and `committed_path` is repo-relative.
>   4. A second root sharing a `<sha>` directory writes `artefact.json` as an EXISTS_EQUAL no-op. EXISTS_DIFFERENT on `artefact.json` or on a `roots/<family_id>.json` is INTEGRITY.
>   5. The `<sha>/` and `roots/` directories become 0500 only after the genesis transaction's last copy has been written.
> - **Consumption.** ARCH-0 seam A (paths, `family_bytes`, resolver); AUT-5a bootstrap; AUT-7 r5 root reads. Fail-closed either way: until filed, BOOTSTRAP refuses and nothing goes live.

**(b) Other ARCH or plan text that r2 contradicts or amends.** The coordinator should record these alongside E-14:
- **AUT-5 r7 §3.1** `__init__` "Public names only" → docstring only.
- **AUT-5 r7 §3.1** `single_read`'s "`lstat` walk" → openat walk (AC 7).
- **AUT-5 r7 §3.1** `VetoReason` in `registry_watch_actor` → `persistence/autonomy/veto.py`.
- **AUT-5 r7 §3.1** the `schemas.py` record list → owner rows (Stub Surface).
- **AUT-5 r7 §3.1** `entry_guard` returning `bool | GuardUnreadable` with a raising `FillReader` → `GuardResult`, `FillIndexAbsent`, `open_intent_blocks`.
- **AUT-5 r7 WP1 Files (:841)** package-wide `↛ nautilus_trader` → contract (b) list plus classification.
- **AUT-5 r7 §3.2 append:** `PartialReplay`; required `now_ns`; ts skew; `AdmissionPending`; caches deferred to WP4.
- **AUT-5 r7 §3.2 export trailer:** adds `schema`, `venue` and `evidence_journal_heads`. AUT-5 and AUT-7 acknowledgement requested; AUT-7 r5 T7 already consumes the heads.
- **AUT-5 r7 §4 ledger:** the tuple gains `owner_symbol` and `blocks_kinds`; `raises=OwnerPending`; `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` (ledger :825) → its E-11 name.
- **AUT-5 r7 WP1/WP2 RED lists:** per the crosswalk.
- **AUT-5 r7 WP9:** the verifier now ships in ARCH-0. WP9 adds the single row and routes child manifests in `live_orders_authorized` to `lineage_policy_authorized`.
- **AUT-7 r5 :91, :506, :703:** `append_journal(paths, kind, venue, record, *, ts_ns)`; journal kinds are bare names (`rollback_decision`), and records carry `schema: "rollback_decision/v1"`; `append(..., now_ns)`.
- **AUT-4 r11 :18, :404, :1372 (AH5):** "lazy PEP 562 `__init__`, `__all__` unchanged" → import-free `__init__` with the facade deleted. The `hypothesis_ledger` closure test outcome is identical.
- **AUT-2 r7 :68, :116, :631:** `net_position.py` is created by ARCH-0 and modified by AUT-2, and must not import `breezy.domain` (contract (b)).
- **AUT-6 r15 :2254:** stale; the ER-2 adopted name (:1746) wins.
- **AUT-6 r15 :512:** the verdict path date comes from `write_verdict` (the `valid_until_ns` UTC date).
- **AUT-1 r12 :1237:** `pins.SELF_HEAL_RESTARTABLE_UNITS` is stale per E-11, and `EntryVeto` names only the C1 record.
- **ARCH C5 Resolver ("checks the export prefix and the node high-water mark")** → refined by the tri-state HWM and the `export_seq` anchor. This is a refinement, not a relaxation (L-12).
**Verdict: REQUEST_CHANGES**

Scores (1–10):

| Criterion | Score |
|---|---|
| Correctness vs ARCH | 7 |
| Security | 5 |
| Test coverage | 7 |
| Risk mitigation | 6 |
| Scope minimality | 5 |
| Feasibility | 6 |

The structure is sound. The empty-pins default, the strict-xfail carrying with `raises=OwnerPending`, and the no-wall-clock and no-`asdict` AST tests are good. But the "widening is unreachable until a reviewed commit" guarantee is enforced at the store only, not at the resolver. The policy-ruling hash check has no owner. Several fail-open paths are unspecified.

I read the plan, `live_orders_gate.py`, `load_family_manifest` and ARCH §4.2 and the resolver text. I did not read the codegraph for the other modules.

## Findings

### CRITICAL
None. At ARCH-0 the pins are empty, so the resolver refuses everything. The findings below are about what the first pin addition would expose.

### HIGH

**H1. Stage flag guards only `append`; the resolver would honour a widening row it never could have written (AC 8, 12, 14; Test Strategy "replay").**
- Problem:
  - `ENABLED_WIDENING_KINDS` is checked only inside `RegistryStore.append`.
  - The resolver calls `validate(mode=None)` over the whole fold and `fold` applies PROMOTE and the other widening kinds.
  - The admission rules for those kinds are deferred to AUT-5 WP1b.
  - A row inserted directly into SQLite (INSERT is not trigger-blocked) by a same-uid process, or by any future writer that bypasses `append`, would fold to CHAMPION.
  - The only remaining barrier is `engine_code_sha ∈ ENGINE_SOURCE_SHA256`, and that value is a string the forger writes into the row.
  - The first commit that adds an engine pin, which AUT-5 WP4 must do, silently arms this path while the stage flag is still empty.
- Fix:
  - Make `resolve_sending_family` and `replay_full` refuse with `widening_kind_not_enabled` when any row on the chain has a kind in `WIDENING_KINDS` that is not in `ENABLED_WIDENING_KINDS`.
  - Also refuse any →CHAMPION effect that comes from a kind whose validator is a stub.
  - Add `test_resolver_refuses_chain_with_unenabled_widening_row`, built from a hand-forged valid-hash chain that bypasses `append`.
  - This must be real in ARCH-0.

**H2. The policy-ruling hash check has no owner (AC 14; File plan, `live_orders_gate.py` "No logic change").**
- Problem:
  - The existing `live_orders_authorized` verifies only `_LIVE_ORDERS_ALLOWLIST` triples against the `manifest.live_orders_ruling` file hash, keyed by `family_id`.
  - A child's `family_id` is never in that list.
  - AC 14 lists "root_not_lineage_allowlisted" but never says the resolver re-hashes `deploy/families/rulings/<policy_ruling_id>.md` against the third element of the `_LINEAGE_POLICY_ALLOWLIST` triple (ARCH §4.2: "each LAUNCH re-hashes").
  - The allowlist therefore ships as an empty frozenset with no verifier.
  - When AUT-5 WP9 adds the one row, that row is verified by new, unreviewed resolver code.
  - That is the "later edit widens" case.
- Fix:
  - Add `lineage_policy_authorized(child_manifest, root_family_id, repo_root, *, permit_present)` in `live_orders_gate.py`, next to `_LINEAGE_POLICY_ALLOWLIST`.
  - It reuses the same path-containment, file and sha checks as `live_orders_authorized`.
  - Test it in ARCH-0 against a fixture allowlist injected through a private parameter.
  - Add negative cases: wrong sha, missing file, symlinked ruling, ruling id not the child's `live_orders_ruling`.
  - Add a case that the child's `live_orders_ruling` is checked to equal the policy ruling id.

**H3. Monkeypatchable stage flag and pins (AC 8, 19; File plan `registry_store.py`).**
- Problem:
  - The plan deliberately reads `pins.ENABLED_WIDENING_KINDS` as an attribute "so tests can monkeypatch it".
  - Any in-process code, including a future plugin in `NODE_PLUGINS`, can rebind it.
  - The AST test `test_no_src_module_assigns_pins` catches only `pins.X = …`.
  - It misses `setattr(pins, …)`, `pins.__dict__[...]`, `importlib.reload`, `mock.patch` in `src/`, `from pins import X` rebinding, and the same on `live_orders_gate._LINEAGE_POLICY_ALLOWLIST` and `_LIVE_ORDERS_ALLOWLIST`.
  - The resolver will be tested by monkeypatching `ENGINE_SOURCE_SHA256` and `_LINEAGE_POLICY_ALLOWLIST`, which makes a mutable seam the tested path.
- Fix:
  - Production entry points (`RegistryStore.append`, `resolve_sending_family`) take no policy parameter.
  - They delegate to private `_append(..., policy)` and `_resolve(..., policy)`, where `policy` is a frozen dataclass built from the pins at import time.
  - Tests call the private functions.
  - Add an AST test that no `src/` module references an underscore-private `_append`/`_resolve`, outside the defining module.
  - Extend the AST scan to the patterns listed above, and to `live_orders_gate` and `family_manifest` module attributes.
  - Add `ENABLED_WIDENING_KINDS ⊆ WIDENING_KINDS`, and `ROOT_ADMIT ∈ ENABLED ⇒ ROOT_ADMIT_ENABLED_CEILING is True`, as a gate test.

**H4. HWM/export checks can be bypassed by absence (Edge cases, resolver; AC 14).**
- Problem:
  - `resolve_sending_family(..., hwm: Hwm | None)` gives no defined behaviour for `None`.
  - Deleting the HWM key together with the registry directory, or replacing the DB with an older prefix, gives `hwm=None`.
  - That would roll the chain back past a DEMOTE or HALT, which is the most security-relevant attack on this registry.
  - `export … not_yet_due` is keyed on row `ts_ns`, which the forger controls.
  - Exports are 0444 files in a directory the same uid can delete from.
- Fix:
  - Make HWM tri-state: `Absent | Present(h) | Unreadable`.
  - In registry mode, `Unreadable` refuses.
  - `Absent` is accepted only when the chain has ≤ N rows and the node's own first-boot marker says "no registry boot has occurred".
  - Otherwise refuse with `hwm_absent`.
  - Key `not_yet_due` on the earliest of {export existence, HWM existence, `now − BOOTSTRAP ts`} and require `ts_ns` to be monotone non-decreasing along the chain and ≤ `now_ns + skew`.
  - Document that this remains inside the same-uid residual (R14).

**H5. TOCTOU in `read_once_nofollow` / `write_once` (AC 5, 6; Symlink refusal).**
- Problem:
  - `read_once_nofollow` is specified as an `lstat` walk followed by `O_NOFOLLOW` on the final component.
  - An intermediate directory can be swapped for a symlink between the lstat walk and the open.
  - `write_once` does the same with `mkstemp` on a string path, then `os.link`. The parent can be swapped between the lstat walk and `mkstemp` or `link`.
  - `EXISTS_EQUAL` must not be decided by a plain read. A symlink at the destination pointing at equal bytes would pass.
  - `mkstemp` creates 0600. A final mode of 0444 needs `fchmod` before the link.
  - Opening a FIFO without `O_NONBLOCK` blocks the resolver.
- Fix:
  - Implement `read_once_nofollow` on top of `open_dir_nofollow` plus `openat` per component, each with `O_DIRECTORY|O_NOFOLLOW`. Use no lstat pre-check and no string-path reopen.
  - Walk from a root dirfd opened `O_DIRECTORY|O_NOFOLLOW` after verifying `root` is absolute.
  - Reject `..` and empty components.
  - Final `open` uses `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, then `fstat`. Require `S_ISREG`, `st_uid == geteuid()`, no group or other write bits, and size ≤ `max_bytes`. Then read `max_bytes + 1` to detect growth.
  - `write_once` works through the parent dirfd:
    - temp file: `os.open(..., O_CREAT|O_EXCL, dir_fd)` under a random `.tmp.` name;
    - `fchmod`, write, `fsync`;
    - `os.link(src, dst, src_dir_fd=, dst_dir_fd=)`;
    - on EEXIST, compare via `read_once_at(dirfd, name)`, so a symlink at the destination gives `EXISTS_DIFFERENT`;
    - unlink the temp, `fsync` the dirfd.
  - Add a test with a symlink at the destination whose target has equal bytes, expecting refusal.

**H6. The `parse_family_manifest` split drops `assert_prereg_directory_eligible` for resolver loads (File plan `family_manifest.py`; AC 14).**
- Problem:
  - Today `load_family_manifest` calls `assert_prereg_directory_eligible(path.parent)` before reading.
  - The split moves only the post-`read_bytes` body into `parse_family_manifest`.
  - The resolver calls `parse_family_manifest` on bytes from `registry/families/` or `deploy/families/`.
  - It therefore skips the prereg-directory gate that every other manifest load passes.
  - `allow_draft` defaults to False, but nothing says the resolver must never pass True.
  - "No behaviour change" is argued only from the existing tests, which may match loosely.
- Fix:
  - The resolver explicitly runs the same directory-eligibility check on the committed root directory. If that check is intentionally dropped for registry copies, document why and test it.
  - Add a gate test that no `src/` call passes `allow_draft=True` from `persistence/autonomy`.
  - Add a golden-corpus test. Run every `deploy/families/*.json` plus about 15 mutated invalid manifests through the pre-split commit's `load_family_manifest` and the post-split one. Compare the exception type and the message after replacing the path with a placeholder.

**H7. Entry-guard fail-open paths (AC 15; `entry_guard.py`).**
- Problem:
  - The return type `bool | GuardUnreadable` can be misused: a caller writing `if not guard(...)` or `is True` gets it wrong.
  - `UnknownSide` and any other exception from `net_signed_qty` are not mapped to `GuardUnreadable`.
  - An empty `fill_index` is indistinguishable from "reader lost the index", for example after retention pruning. The plan distinguishes a missing record from an unreadable index, but not a missing index key from an empty one.
  - Veto must be `net != 0`, not `> 0`. A negative (short-YES) net must also veto.
  - A held position with no durable record (an AMBIGUOUS or OPEN submit intent whose fill was never recorded, resolver-residual fills) produces no veto.
  - `EntryVeto = Callable[[str], VetoReason | None]` has `None` meaning "permit". An exception inside a veto callable is fail-open if the composer catches broadly.
- Fix:
  - Return a three-member enum `GuardResult{HELD, FLAT, UNREADABLE}`. Never return a truthy or falsy object whose meaning depends on how it is tested.
  - Wrap the whole body in `except Exception → UNREADABLE`.
  - `FillReader.fill_index` must return `Absent | tuple` explicitly, with `Absent` legitimate only for a never-written index.
  - Add a parameter or a documented contract that an OPEN or AMBIGUOUS intent on the rung returns `UNREADABLE`. AUT-5a supplies it, but the Protocol must carry it.
  - Add tests: net −q vetoes; instrument id that fails `instrument_leg` parsing gives `UNREADABLE`.
  - Add a test that a veto callable raising yields a veto in the composer helper. Put that helper in `veto.py`.

### MEDIUM

**M1. `venue_seq` may not be inside the hash (AC 9).**
- Problem: `canonical_row` excludes `seq`, `prev_transition_hash` and `transition_hash`. If `seq` is the autoincrement id, `venue_seq` should be hashed and is not stated.
- Impact: renumbering, gaps or duplicates then break neither the chain nor `UNIQUE(venue, venue_seq)`, and the HWM compares only numbers.
- Fix: include `venue` and `venue_seq` in the hashed row. `verify_venue_chain` requires `venue_seq == 1..n` contiguous and `venue` equal to the requested venue.

**M2. Row `ts_ns` is writer-supplied (AC 8, 11).**
- Problem: the rate cap (≤ 1 counted MINT per lineage per UTC day), ROOT_ADMIT cooldown and ATTEST validity all use row `ts_ns`.
- Impact: a back-dated or future-dated row bypasses them.
- Fix:
  - `append` requires `|ts_ns − now_ns| ≤ SKEW` and `ts_ns ≥ previous row's ts_ns`.
  - `verify_venue_chain` enforces monotone ts.
  - Add tests.

**M3. Partial-idempotent append and `mode=None` (AC 8).**
- Problem: "all ids already present → no-op" does not define behaviour when only some ids are present. `mode=None` is a legal `validate` value and must not be a legal `append` value.
- Fix:
  - Partial presence gives `PartialReplay` refusal.
  - `append` requires a concrete `WriterMode`.
  - Add tests.

**M4. Reader against a hot journal and a swapped DB (AC 10).**
- Problem:
  - A killed writer leaves `registry.sqlite-journal`. A `mode=ro` reader cannot roll it back and raises `OperationalError` or `DatabaseError` with `SQLITE_READONLY_RECOVERY` or `SQLITE_READONLY_ROLLBACK`.
  - The plan says "RegistryUnreadable", which is right. But the mapping must cover every `sqlite3.Error`, not only `DatabaseError`. `OperationalError` and `IntegrityError` are in that family.
  - The reader does not check that the schema is the expected one. A swapped DB can lack triggers or carry extra objects.
- Fix:
  - Catch `sqlite3.Error` and `OSError` and map them to `RegistryUnreadable`.
  - After open, assert `meta.schema == 'registry/v1'`, `PRAGMA user_version`/`application_id`, and that `sqlite_master` contains exactly the expected table, index and trigger SQL (compare the DDL text).
  - Set `PRAGMA trusted_schema=OFF`.
  - Select with an explicit column list `ORDER BY venue_seq`, never `*`.
  - Wrap the read in a single `BEGIN` snapshot.
  - Percent-quote the path in the `file:` URI (`?`, `#` and `%` in a path otherwise change its meaning).
  - Add a test that kills a writer mid-transaction and expects `RegistryUnreadable` and not "no rows".

**M5. Path components are not validated (Paths; AC 16–18).**
- Problem: `AutonomyPaths` builders take `venue`, `family`, `kind`, `model_class` and `sha`. Demand and verdict records carry a `family_id` from file content. Nothing states that each component is checked before the join. `model_class` has a colon (`kind:component`).
- Fix:
  - Every builder validates every component against a closed `\A…\Z` regex with `re.ASCII`, and refuses `/`, `..` and NUL.
  - The child-id regex `<root>_r<NNNN>` must use `[0-9]{4}`, not `\d`, which matches Unicode digits.
  - Add a traversal-vector test per builder.

**M6. Hygiene leaks through passed-through exceptions (Hygiene).**
- Problem:
  - `LiveOrdersGateRefusedError("ruling_missing", f"ruling file missing: {ruling_path}")` embeds an absolute path.
  - `FamilyManifestValidationError` messages embed `{path}`.
  - The resolver calls both. The hygiene test covers only the plan's own refusal classes and `to_wire`.
  - `WireRefused(reason: str)` is free text.
- Fix:
  - The resolver catches both exceptions, maps them to an enum `RefusalReason`, and raises or returns `from None`.
  - Pass a role label (`Path("manifest")`) to `parse_family_manifest(path=)`.
  - `WireRefused.reason` becomes an enum or a closed literal.
  - Extend `test_autonomy_payload_hygiene_scan` to plant a tmp-path-bearing failure through the gate and the manifest parser and assert that the path string appears nowhere in `str(exc)`, `repr`, `__cause__`, or the refusal object.

**M7. `permit_present` argument undefined (AC 14).**
- Problem: `live_orders_authorized(manifest, root, *, permit_present)` needs a value. The invariant says the permit is untouched. Passing `True` fabricates permit knowledge and returns `enabled=True`. Passing `False` returns `permit_absent`.
- Fix:
  - Pin it. The resolver passes `permit_present=False`, treats only `reason in {"ok","permit_absent"}` as pass, and never exposes `enabled`.
  - The resolver result carries no permit semantics.
  - Add a test that the resolver cannot yield an `enabled=True` decision object.

**M8. Resolver fail-open conditions not enumerated (AC 14).** The following should be explicit refusals with parametrised tests:
- `now_ns` is non-int, ≤ 0, or earlier than the head's `ts_ns`.
- The fold has more than one `CHAMPION`/`HALTED` family on the venue. This must be `engine_inconsistency`, not an assert or an arbitrary pick.
- The manifest's venue, `composition_kind` or family id differs from the authorising row. `LIVE_GATE_ROUTED_KINDS` is checked on the manifest's kind, not on a row field.
- The sender is HALTED but `ResolvedFamily` lacks a mandatory `entries_allowed=False` field. Make the state a required field, so a caller using only `family_id` cannot trade silently.
- The §4.2 equality compares fields of the parsed manifest. It must iterate `dataclasses.fields(FamilyManifest)` minus the six allowlisted, so a later new manifest field is compared automatically. Add a test that adds a synthetic field and expects a mismatch.
- A `status` of `DRAFT_NOT_REGISTERED` or an all-zero boundary sha.
- The `engine_code_sha` retention test is vacuous with empty pins, so add a positive control against a git-history fixture.

**M9. Lazy `persistence/__init__` shifts import failure from boot to runtime (R7).**
- Problem:
  - Identity is preserved. Submodule imports (`live_orders_gate`) do not pass through the facade, so the gate sees the same objects.
  - But an import error or import-time side effect in `catalog` now surfaces on first use, in a live node, not at process start.
- Fix:
  - Add a boot-time `breezy.persistence.catalog` eager touch, or a test that imports each of the 21 names in the node and supervisor entry points at startup.
  - Confirm that no `mock.patch("breezy.persistence.X")` call site silently patches a facade copy.

**M10. Carried-test integrity (Q5, details below).** Param-level deletion is not caught by `test_every_envelope_test_exists`.

**M11. `WP-D` activation timing.** `parse_family_manifest` goes live at the next 16:50Z LAUNCH. Merge and restart it outside 16:40–17:00Z with the full gate green, and state the window in the WP brief.

### LOW

- **L1.** `DEMAND_WRITER_PRODUCER_IDS` is gated by a caller-supplied `producer_id` string. That is advisory only, and demand is restrictive-only, so say so in the docstring and don't count it as authentication.
- **L2.** Demand-flood DoS by any same-uid process causes a venue veto with no archive until AUT-5 WP4. This is fail-closed and acceptable, but record it in the risk register.
- **L3.** `closure_sha256` excludes `pins.py` by ARCH design. Note that the enable flags are therefore not covered by the engine code hash.
- **L4.** `scripts/ci/regen_closure_manifest.py` writes a Python module. Ensure the output is deterministic and literal-only.
- **L5.** The R14 same-uid residual is accepted per ARCH. Say it again in the plan summary: pins, chain, HWM, exports and the DB are one trust domain, and the committed allowlists plus `live_orders_gate` are the only external anchors. This is why H1 and H2 matter.

## Answers to the focus questions

**(1) Widening without a reviewed commit.** Yes, in three ways:
- (a) A forged widening row that bypasses `append` and is honoured by the resolver (H1).
- (b) A mutable stage flag and pins, plus an incomplete AST scan (H3).
- (c) The policy-ruling hash check lands only with the first allowlist row (H2).

The `parse_family_manifest` split is not itself a widening, but it drops the prereg-directory gate for resolver loads (H6). The lazy `__init__` does not change which objects the gate sees (M9 covers the boot-timing change).

**(2) Integrity.** `venue_seq` is not hashed and `ts_ns` is unconstrained (M1, M2). The reader does not verify the schema or triggers (M4). The TOCTOU and symlink-at-destination problems are in H5. HWM absence is a bypass (H4).

**(3) Inputs or conditions that give a champion or a non-veto instead of a refusal.**
- `hwm=None` or an absent export, then a rollback past a DEMOTE or HALT (H4).
- A widening row inserted outside `append` (H1).
- A child's policy-ruling sha never checked (H2).
- `HALTED` returned without a mandatory entries-vetoed flag (M8).
- More than one `CHAMPION`/`HALTED` family on the venue (M8).
- `now_ns` out of range (M8).
- An unknown fill side, an empty-vs-absent fill index, and a negative net treated as "no veto" (H7).
- A hot journal mapped only from `DatabaseError` (M4).
- Partial idempotent replay (M3).
- An absent or truthy `GuardUnreadable` (H7).
- `\d` matching Unicode digits in the child-id regex (M5).

**(4) Hygiene.** The plan's own refusal classes are enum-based and good. The leaks are exceptions passed through from `live_orders_gate` and `family_manifest`, which embed absolute paths, and the free-text `WireRefused.reason` (M6).

**(5) Carried strict-xfail.**
- The mechanism is acceptable. Each carried test calls the ARCH-named API through `require_owner_symbol`, so `raises=OwnerPending` can only fire on a missing symbol.
- It is nonetheless a way to ship ARCH-0 with an envelope test disabled, in two ways:
  - `test_every_envelope_test_exists` checks function names, not parametrised ids. Deleting the `[engine]` param of `test_registry_champion_requires_live_orders_gate_for_every_kind` while keeping `[resolver]` passes it.
  - The ledger and the markers are edited together in the same commit as a `pins.py` change, so the "ledger clears" test proves only internal consistency.
- Fixes:
  - Make `ENVELOPE_TEST_NAMES` carry full node ids with params, and check them.
  - Freeze a minimum `blocks_kinds` map in a separate small file. The `pins.py` widening test imports it, so a change needs a reviewer to see it.
  - Require `owner` to be a plan or WP id that exists in the docs.
- **These must be real in ARCH-0, not carried:**
  - **Everything the ARCH-0 resolver or `replay` path depends on:** the V12 DRILL-class-row rule (`test_drill_row_refused_while_non_drill_cause_stands`), `test_drill_promote_refuses_non_champion_sha`, `test_drill_refused_over_halted_incumbent`, `test_child_d0_and_trial_prefix_pinned[store]`. The plan says `validate` implements the V12 rule but carries its test.
  - **Counting and ceilings that the fold's tallies make real:** `test_damping_ceilings[counting_rule]`, `test_drill_budget_separate`, `test_drill_demote_and_halt_counters_capped`, `test_carried_counters_are_floors`. The tallies are claimed real, so the tests belong with them.
  - **Resolver-side rules:** `test_resume_requires_every_cause_cleared`, `test_rollback_failed_resumes_only_under_trigger_class`, `test_root_admit_requires_own_allowlist_triple[engine]` as its resolver half (the `[resolver]` param is already real), `test_target_byte_mismatch_ineligible_without_freeze[selection]` where the fold half is real.
  - **New and mandatory:** `test_resolver_refuses_chain_with_unenabled_widening_row` (H1), the policy-ruling sha tests (H2), and `test_hwm_absent_with_rows_refuses` (H4).
- It is fine to leave carried the tests whose subject code lives in AUT-5a, AUT-6, AUT-7 or AUT-2, such as engine, watch actor, node, supervisor and alert delivery.

## Other observations

- **Scope:** about 3,500 lines across four WPs, plus the strategy and analysis plugin packages, `label_schema` (pyarrow), `drill_marker`, `rollback_journal` and `demand`. All are ARCH-assigned. Still, `label_schema`, `lineage`, `rollback_journal`, `drill_marker` and the plugin Protocols have no ARCH-0 consumer in the registry path. If scope must shrink, defer those to their owners. I did not make that a finding.
- **Consistency:** the plan treats `ENABLED_WIDENING_KINDS = frozenset()` as the single lever, which is a sound choice. H1 and H3 make it hold at the resolver too.

Plan reviewed: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r1.md`. Code read: `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py`, `/home/jon/breezy/src/breezy/persistence/family_manifest.py`, and ARCH §4.2 and the resolver text in `AUTONOMY_ARCHITECTURE.md`.
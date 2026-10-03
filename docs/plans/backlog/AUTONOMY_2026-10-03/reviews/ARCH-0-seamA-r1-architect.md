**Verdict: REQUEST_CHANGES.** There are no CRITICAL findings, 6 HIGH, 6 MEDIUM and 5 LOW.

**E-14 verdict: AMEND, then ADOPT.** The collision is real. The fix (`roots/<family_id>.json`) is right but needs five small amendments (M5).

**Scores**

| Axis | Score |
|---|---|
| Correctness | 7 |
| Architecture fit | 8 |
| Test coverage | 7 |
| Risk mitigation | 7 |
| Scope minimality | 7 |
| Feasibility | 6 |

The plan is well researched, the layering is right, and the strict-xfail plus ledger mechanism is the READY AUT-5 r7 approach, improved. Six HIGH gaps stop it as written. One is a contract break with AUT-5's stage L1. Two import-weight claims don't hold at runtime. The WP dependency graph is wrong. Contract (b) defaults to allow. One case in the owner-placeholder mechanism hides defects.

---

## Answers to the six questions

**Q1. Fidelity to §5.1 Wave 0, and the WP1b deferral**
- Everything §5.1 names is present: schemas, C5 store (chain, triggers, CAS, fold, rollback journal), resolver, `entry_guard`, `pins.py` with ceilings, C6 Protocols and `RefusingPlugin`, and `lint-imports` "N kept, 0 broken".
- Nothing is invented beyond §5.1 except the lazy `persistence/__init__` and the export-trailer widening (L4). Both are justified, but each needs one extra safeguard (H2 for the lazy `__init__`, L4 for the trailer).
- Deferring the widening-kind admission rules behind `ENABLED_WIDENING_KINDS=∅` is acceptable in principle. It fails closed, and those rules are first needed in Wave 3 (AUT-5b).
- It does break AUT-5 r7 as written, though:
  - AUT-5 r7 §3.2 (line 169) sets stage L1 to `ENABLED_WIDENING_KINDS = {RESUME}`.
  - AUT-5's own gate test exempts RESUME (line 818).
  - Seam A's ledger now blocks RESUME on WP1b rows: `test_resume_requires_every_cause_cleared`, `test_rollback_failed_resumes_only_under_trigger_class`, the E-5 restore tests, and `test_damping_ceilings[counting_rule]` "[all widening]".
  - "AUT-5 WP1b" is in no READY WP list or schedule (line 977).
  - So L1 is blocked, or someone gets pushed to delete ledger rows to unblock it. See H1.

**Q2. Is strict-xfail(raises=OwnerPending) plus the ledger a faithful "start RED"?**
- Yes. It is the READY AUT-5 r7 §4 mechanism, made stricter by `raises=` and by the existence test.
- Four holes remain:
  - `require_owner_symbol` can swallow an owner's broken import (H6a).
  - Speculative bodies can guess the wrong symbol and stay xfail forever (H6b).
  - Pre-E-11 names and a wildcard row are in the ledger (M2).
  - The envelope name list is hand-copied, and skip markers are not banned (M3).

**Q3. E-14** — see M5.

**Q4. Contract (b), VetoReason, net_position**
- Contract (b) with an explicit module list is right in substance. AUT-1 r12's capture modules make the whole-package ban in AUT-5 r7 (line 841) unbuildable. But as an allow-list it is a silent drift trap (H5). It also can't see package-`__init__` edges (H3).
- Moving `VetoReason` into `persistence/autonomy/veto.py` is sound and needed, because AUT-1's persistence-layer consumer can't import strategy. The member set and the `EntryVeto` alias need fixing (M4).
- Creating `net_position.py` first, with AUT-2 later modifying it, is sound. AUT-2 r7's WP brief must change from "new" to "modified", and the module must not import `breezy.domain` (H3).

**Q5. Where seam B's wrapper and snapshot helper should live**
- Keep both in `src/breezy/runtime/autonomy_sandbox/`, but drop the "392 ms" rationale: once the lazy `__init__` lands, it no longer applies.
- The real reasons:
  1. The E-8 helper opens its copy read-write and runs `quick_check`. Seam A's AST write-site scan of `persistence.autonomy`, and E-7 rule 3's "`sqlite3.connect` without `mode=ro`" lint, would both flag it there and need an exception. An exception is a guard weakening (L-46).
  2. Every caller sits at runtime level or above: the engine in `analysis/autonomy_engine`, AUT-6 node-up readers in strategy or analysis. None is in persistence.
  3. The bwrap table and wrapper are deployment and process configuration (E-7a rule 1 names `deploy/systemd/breezy-autonomy-bwrap`), not records. That is runtime's responsibility.
  4. `runtime/__init__.py` is already import-free (NOTIFIER-IMPORT-ISOLATION), so the placement costs nothing.
- Seam B should enforce "stdlib-only" with a forbidden contract, `breezy.runtime.autonomy_sandbox ↛ nautilus_trader, breezy.adapters, breezy.strategy` with `allow_indirect_imports=false`, plus a fresh-subprocess import test. Today the claim is only a comment.
- The helper may import the halt and intent decoders downward (runtime → persistence is legal), which fits either answer to R4.

**Q6. Sequencing, sizes, hidden dependencies** — see H4, H6c and M1.

---

## Findings

### HIGH

**H1. AUT-5 has no scheduled slot for the deferred admission rules, and enforcement is test-only** (§Trade-offs row 2, AC 12, R10, Confidence 6)
- Problem:
  - Stage L1 needs RESUME; RESUME's admission rules are now in an unscheduled "WP1b".
  - The only thing blocking an early widening is a gate *test*. A `pins.py` commit merged without a gate run goes live (memories `supervisor-unit-is-symlinked`, `activate-code-immediately`).
  - Tests that monkeypatch the stage flag (`test_repeat_supersede…`, `test_prelaunch_writes_rollback_and_activate_atomically[store_atomic]`) drive a store that has no admission rules.
- Fix:
  - (a) In this plan, define WP1b's scope and order as a binding note for the AUT-5a brief: "WP1b merges before the L1 pins commit (RESUME subset) and before L2 (all)". Name the RESUME subset.
  - (b) Add a code-level `transitions._ADMISSION_IMPLEMENTED: Final[frozenset[Kind]]`, which ships as `frozenset()`. The store refuses with `AdmissionPending(kind)` when a kind is in `ENABLED_WIDENING_KINDS` but not in that set. Only an owner WP adds to it.
  - (c) Add `test_enabled_widening_kinds_subset_of_admission_implemented`.
  - (d) Prove atomicity in ARCH-0 with the restrictive pair SWAP_CANCEL + TARGET_INELIGIBLE. Move `[store_atomic]` for ROLLBACK+ACTIVATE into WP1b.

**H2. The lazy `persistence/__init__` needs the precedent's register_arrow reachability audit** (AC 2, File plan row 1, R7, WP-A Activation)
- Problem:
  - The eager import chain `persistence/__init__` → `catalog` → `domain.nws_climate_day` / `nws_raw_product` runs module-scope `register_arrow(`.
  - Making it lazy removes that side effect from every process that imports any `breezy.persistence.*`: node, supervisor, ingest, recorder, studies.
  - The repo's own precedent (`runtime/__init__.py:27-44`, NOTIFIER-IMPORT-ISOLATION r3) required a grimp reachability check with synthetic module→ancestor edges, over every `[project.scripts]`, every `deploy/systemd` ExecStart and every `scripts/**`, plus a fresh-process `sys.modules` smoke test per entry. Without it, the change was not accepted.
  - "Facade identity test plus full gate" covers neither.
  - A missing registration raises (`TypeError`/`KeyError`) at catalog read time, so in the live process it is an outage, not a silent error.
- Fix:
  - WP-A ships `test_persistence_lazy_init_preserves_register_arrow_reachability`, reusing the method in `tests/unit/test_runtime_import_isolation.py`, plus the per-entry smoke test.
  - Also grep for attribute access `breezy.persistence.<submodule>` that relied on the eager submodule binding. `__getattr__` raises for names outside `__all__`.
  - Activation evidence: name the restart order per `activate-code-immediately` (supervisor window 01:00–16:40Z).

**H3. Nautilus and pyarrow can still load through ancestor `__init__` files** (AC 1(b), AC 2, Layering para 4, File plan for `net_position` and `entry_guard`)
- Problem:
  - `src/breezy/domain/__init__.py:16-53` eagerly imports `forecast_point`, `nws_climate_day` and others. Seven domain modules import `nautilus_trader`.
  - So `net_position` and `entry_guard` (both `import breezy.domain.instrument_leg`) load Nautilus at runtime.
  - grimp models no ancestor-package edges, so contract (b) with `allow_indirect_imports=false` stays green while the property is false.
  - Separately, the claim "pyarrow by placing it only in `label_schema.py`" is false: resolver → `family_manifest:88` → `mechanism_test_guard:14` imports `pyarrow.parquet`.
- Fix:
  - (a) `net_position` and `entry_guard` must not import `breezy.domain`. Restate the YES and NO leg-id suffix rule as a literal, test-asserted equal to `instrument_leg.py:35-73`. This is the same idiom the plan already uses for `FAMILY_ID_RE`.
  - (b) Widen AC 2: every module in contract (b)'s list, imported in a fresh subprocess, loads 0 `nautilus_trader*` modules (`test_autonomy_core_modules_nautilus_free_at_runtime`).
  - (c) Correct the pyarrow claim: either measure and accept it in the resolver closure, or state it as a known cost against AUT-5's closure RSS budget.

**H4. Hidden WP dependencies make "B ∥ C" and the WP-A contents wrong** (§Work Packages, File plan rows `hwm.py`, `registry_store.py`)
- Problem:
  - `hwm.py` sits in WP-A but depends on `chain.VerifiedVenueChain` (WP-C).
  - `RegistryStore.write_export(…, journal_heads)` and `ExportTrailer.evidence_journal_heads` need `rollback_journal.JournalHead` (WP-B). So C depends on B.
  - `replay` (WP-D) needs `verdict` (WP-B), which is fine.
- Fix:
  - Move `hwm.py` and its tests to WP-C, or WP-D.
  - Either move `JournalHead` into `schemas.py` (WP-C) and have `rollback_journal` import it, or make the order A → B → C → D.
  - Restate the order as a dependency table: module → WP → imports.

**H5. Contract (b) is an allow-list, so new modules escape the Nautilus ban silently** (AC 1(b), R2, pyproject row)
- Problem: AUT-4 (`sample_size.py`, `nomination.py`), AUT-5 (`policy.py`, `halt_rows.py`) and later owners will add core modules. Each one escapes the ban until someone remembers to append it.
- Fix: add `test_every_autonomy_module_is_nautilus_classified`. Every module under `breezy.persistence.autonomy` must be either in contract (b)'s `source_modules` (parsed from `pyproject.toml`) or in a literal `NAUTILUS_PERMITTED_MODULES` (the AUT-1 `capture_*` set, E-12). Ship a planted-module positive control.

**H6. Owner placeholders: one case hides defects, one stays carried forever, and the sizing is wrong** (§Test Strategy "How later-owned tests are carried", the `autonomy_owner.py` row)
- (a) Problem: `require_owner_symbol` raising `OwnerPending` on any `ImportError` would hide an owner module that exists but is broken.
  Fix: `OwnerPending` only for `ModuleNotFoundError` whose `.name` equals the declared module, or for `AttributeError` on the declared attribute of a module that imported cleanly. Everything else propagates. Add a positive-control test with a planted broken module.
- (b) Problem: real bodies "written now" against APIs the owners haven't designed guess at symbol names. If the guess is wrong, the test xfails indefinitely after the owner lands. Rows with no `blocks_kinds` are never forced closed before L2.
  Fix: carried bodies become stubs: `require_owner_symbol` plus a docstring citing the ARCH pin. The owner writes the body. Add the declared `owner_symbol` as a ledger column. Add `test_owner_placeholder_symbol_absent`: if a ledger row's declared symbol now resolves, the row is stale and fails. Every owner WP's DoD includes "my ledger rows = ∅".
- (c) Problem: about 160 carried test bodies are budgeted to no WP. WP-A's ~850 lines can't hold them as real bodies.
  Fix: with stubs (b) they cost about 5 lines each. Assign each carried row to the WP that ships its nearest ARCH-0 symbol.

### MEDIUM

**M1. No crosswalk from AUT-5 r7 WP1/WP2 RED tests to their new homes** (§Test Strategy, R8)
- These AUT-5 r7 WP1/WP2 test names appear nowhere in seam A, neither as real tests nor as carried ones:
  - `test_root_admit_exempt_from_d0_rule`
  - `test_drill_close_restore_at_most_one_per_venue_per_day`, `…_refused_for_drill_child`, `…_charges_no_drill_or_production_budget`, `…_refused_after_non_drill_cause`
  - `test_hwm_reset_store_refuses_carried_counters_below_export`, `test_replay_refuses_carried_counters_below_prior_fold` (B9)
  - the three `test_demand_archive_*` tests
  - `test_drawdown_inert_ceiling_is_pins_literal_not_policy_key`
  - `test_policy_map_not_looser_than_fallback_map`
  - `test_containment_checks_read_directory_not_phantom_base` (G34; the AUT-5 WP2 four-site widening is not in WP-D)
  - `test_fill_reader_production_default_runs_once`
- Fix: add a table mapping every AUT-5 r7 WP1/WP2 RED test to one of: ARCH-0 real | carried (owner WP) | moved to WP1b/WP2/WP3/WP4 | seam B. Its rows must sum to the AUT-5 lists.

**M2. Ledger contents are inconsistent** (§Carried strict-xfail)
- "The AUT-5 r7 ledger carried unchanged" includes `test_self_heal_unit_allowlist_is_literal_and_excludes_trade` (r7:825), which E-11 renames.
- The row `test_drill_close_restore_*` is a wildcard, so it can never equal a marker.
- AUT-6 r15 contradicts itself: ER-2 (:1746) says `test_watchdog_kill_paged_once_via_notifier_marker_else_fallback_critical`, but :2254 says `…_restart_paged_once_via_stop_hook_record_else_fallback_critical`.
- Fix:
  - Apply the E-11 renames to the carried AUT-5 rows.
  - Enumerate every wildcard.
  - Pin the ER-2 (adopted) name and file a coordinator note that AUT-6 r15:2254 is stale.
  - Also carry the AUT-5 r7 rows that are not §4.7 names, with owners: `test_shadow_detector_ignores_production_marker`, `test_production_detector_ignores_shadow_marker`, `test_fee_schedule_verdict_feeds_fee_verified_checks`, `test_post_stop_producer_inconclusive_without_stop_signal`, `test_drawdown_gates_on_labels_consumable`, `test_failed_drill_close_restored_at_next_prelaunch`, `test_shadow_probe_marker_accepted_only_under_shadow_root`.

**M3. The envelope name list is hand-copied, and skips are not banned** (`autonomy_envelope_manifest.py` row, gate test 3)
- Fix:
  - `test_envelope_manifest_equals_frozen_arch`: read `AUTONOMY_ARCHITECTURE.md`, check its sha equals the errata freeze `1b288d0e…`, extract the §4.7 backticked `test_*` names, apply a literal E-11 rename map, and assert equality with `ENVELOPE_TEST_NAMES`.
  - Gate test 3 must check *collected* node ids, and must fail on any `skip`/`skipif` mark or `pytest.param(..., marks=skip)` on an envelope id.
  - The ledger AST scan must read `pytest.param(marks=…)` as well as decorators, with a positive control for each form.

**M4. `veto.py` disagrees with ARCH** (File plan row `veto.py`, Stub table row 1)
- ARCH C5 lines 642-656 list **15** reasons; the plan says 18. The plan's description also omits `permit_lapsed`.
- `EntryVeto = Callable[[str], …]` has two problems:
  - It collides with AUT-1 r12's `EntryVeto` capture record, which lands in the same package (r12:433).
  - It diverges from AUT-5 r7:414 `Callable[[InstrumentId], …]`.
- Fix:
  - List the members literally, citing ARCH or errata for each. Any member beyond the 15 needs a cited source, or comes out.
  - Rename the alias to `EntryVetoFn`, or leave the callable type to AUT-5a in strategy, where `InstrumentId` is legal.

**M5. E-14: AMEND, then ADOPT** (R1)
- I verified the collision:
  - `deploy/families/pm_us_crh_v4.json` and `pm_us_crh_cont.json` are both `continuous_rung_hold`, both have `density_artefact_sha256 = 247f6363…` (the `not_applicable_density.json` placeholder), and both are RETIRED seeds (ARCH :737-738).
  - Their `root/v1` bodies differ in `family_id` and `manifest_sha256`. So under ARCH :261, the second `write_once` returns EXISTS_DIFFERENT and the genesis BOOTSTRAP fails.
  - `pm_us_crh_v2` shares the sha but is `current_rung_hold`, so it lands in a different directory (assuming `model_class` keys on kind).
- Amendments:
  1. The erratum text covers ARCH :261, AUT-5 r7 §3.2 :172/:180 and the AUT-7 r5 root-read rows.
  2. Pin the root `component` literal used in `model_class_of` for root copies. Today the collision analysis depends on an unstated value.
  3. The resolver reads `roots/<row.family_id>.json` and refuses unless `record.family_id == row.family_id` and `record.manifest_sha256 == row.manifest_sha256`.
  4. A shared `artefact.json` with EXISTS_EQUAL is the expected no-op; EXISTS_DIFFERENT is INTEGRITY.
  5. The `<sha>/` and `roots/` directories go to 0500 only after the genesis transaction's last copy (ARCH C3 dirs are 0500).
- Also: WP-B should not ship the known-defective `root.json` path as a fallback. Hold WP-B's `paths.root_record` until the ruling. It is one function.

**M6. Wave 0 or AUT-5 WP1 items with no named owner** (§Stub Surface)
- The C4.1 holdout ruling filing (§5.1 "filed alongside").
- AUT-2's Wave 0 egress review (ARCH :869-871).
- The `policy` parser, moved from AUT-5 WP1 to WP3.
- `demand.archive`, moved to WP4.
- AUT-5 r7's `schemas.py` records: `heartbeat/v1`, `stop_complete/v1`, `launch_event/v1`, `halt_mirror/v1`, `relaunch/v1`, `drawdown_control_active`.
- Fix: list each in the stub table with its owner WP. The coordinator must get these moves into the AUT-5a brief.

### LOW

- **L1 (AC 19 vs Thread affinity).** `PRODUCER_SOURCE_SHA256 = {}` and `CLOSURE_MODULES = {}` are dict literals, which the plan's own module-level-mutable AST ban rejects. Use `MappingProxyType({})`.
- **L2 (AC 19).** Enumerate the AUT-5 r7 §3.1 pins that seam A omits: `ENGINE_LOCK_MAX_HOLD_S = 15`, `RELAUNCH_REQUEST_TTL_S = 120`, `WATCH_BUSY_TIMEOUT_MS = 250`, `DRILL_CLOSE_RESTORES_PER_VENUE_PER_DAY = 1`, `DRAWDOWN_INERT_ALERT_CEILING`/`_MIN_FILLS`. `test_request_ttl_covers_two_schedule_polls` is real in ARCH-0 and needs the TTL.
- **L3 (File plan row 1).** Define `__getattr__`/`__dir__` under `if not TYPE_CHECKING:`. Otherwise mypy types any `from breezy.persistence import <typo>` through the module `__getattr__` instead of reporting an error.
- **L4 (Storage layout, exports).** `schema` and `evidence_journal_heads` widen AUT-5 r7 §3.2's trailer set. Record the AUT-5 and AUT-7 owner acknowledgements in the plan (L-12 says widen deliberately).
- **L5 (Test Strategy, verdict path).** The `valid_until_ns` date directory is a reasoned choice. Verify-first that the AUT-2/4/6 writer briefs (AUT-4 :450/:458, AUT-6 :512) don't assume the `produced_at` date.

---

## Checks that passed
- **LESSONS:** I checked every cited L-number against the header (L-1, 12, 16, 25, 29, 33, 42, 43, 44, 46, 48, 50, 51, 55); none is misattributed.
  - L-42 is met only indirectly: the `[double]` guard test uses a fake `FillReader`, and the real-writer leg is the carried `[adapter_reader]` row. Acceptable as long as H6b keeps that row from going stale.
- **Errata:** E-7 rule 3 (`mode=ro` plus `query_only`), the E-7a rule 3 exclusion for a DELETE-mode registry, E-6 (second BOOTSTRAP refused), E-11 (no `SELF_HEAL_*` pins) and E-12 (contract (b) scoping) are all consistent.
- **Layering:** the plan's reading of `pyproject.toml:78-100` is correct. Restating the fsync is justified by `pyproject.toml:137-141`, since `archive_cache` is forbidden to strategy.
- **Path hygiene:** paths are absolute or repo-relative; the briefs use the exact interpreter, never `uv`, and never `git stash`.

## Files
- Plan reviewed: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r1.md`
- E-14 evidence: `/home/jon/breezy/deploy/families/pm_us_crh_v4.json`, `/home/jon/breezy/deploy/families/pm_us_crh_cont.json`, `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md` (:224-265, :737-740)
- H2 precedent: `/home/jon/breezy/src/breezy/runtime/__init__.py`
- H3 evidence: `/home/jon/breezy/src/breezy/domain/__init__.py`, `/home/jon/breezy/src/breezy/persistence/mechanism_test_guard.py`
- H1 and M1 evidence: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md` (§3.2 :140-172, §4 :815-836, WP1 :838-854)
- M2 evidence: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-drift-health_plan_r15.md` (:1746 vs :2254)
- Errata: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
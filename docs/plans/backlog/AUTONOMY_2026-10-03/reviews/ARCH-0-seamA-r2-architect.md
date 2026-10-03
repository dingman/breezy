**Verdict: REQUEST_CHANGES.** There is no CRITICAL finding. There are 2 HIGH, 6 MEDIUM and 8 LOW. Both HIGHs are text-level fixes, so r3 should converge in one round.

**E-14: AMEND, then ADOPT.** The collision is real and the five r1 amendments are all in. Two scope clarifications are still needed (finding 9).

**Method.** I checked every r1 architect and python finding against the r2 text itself, not the disposition table. Code facts were verified with codegraph, Read and Grep at `d231497d`. I had no shell tool, so I ran no Python probes. The one SQLite claim (finding 3) rests on standard SQL NULL rules and is marked as such.

## Scores

| Axis | Score |
|---|---|
| Correctness | 7 |
| Architecture fit | 8 |
| Test coverage | 8 |
| Risk mitigation | 7 |
| Scope minimality | 6 |
| Feasibility | 7 |

## r1 findings: fixed in the text?

- **Architect H1–H6, M1–M6, L1–L5:** all are present in the text.
  - H1: AC 13 and AC 15, plus the binding note.
  - H2: AC 4.
  - H3: AC 1, AC 3 and AC 19.
  - H4: WP table.
  - H5: AC 2.
  - H6: AC 24.
  - M1: the crosswalk sums to 85 and 16.
  - M2: Test Strategy (b) and (e).
  - M3: AC 24.
  - M4: AC 20.
  - M5: §ERRATA.
  - M6: Stub table.
  - L1 and L2: AC 22.
  - L3 is moot. L4 and L5 are covered in (b).
  - One residue: H4's dependency table creates a new `transitions` ↔ `stage_policy` cycle (finding 14).
- **Python B1–B5 and P-n1–P-n13:** all are present in the text.
  - One residue: B2's new INSERT trigger has a NULL hole on a venue's first row (finding 3).
  - P-n11 was fixed differently (callers keep the prereg check). That is acceptable.

## 1. Fidelity to §5.1 and scope growth

- Everything §5.1 lists is there, and A-R1…A-R6 are honoured.
- The growth from "size M" to about 11k lines is mostly **relocation, not new scope**. The crosswalk moves 76 of AUT-5 r7's 101 WP1/WP2 RED tests into ARCH-0, and A-R3 requires the fold-decidable rules to be real. AUT-5a shrinks by the same amount. I would not cut anything back to WP1b, because A-R3 binds and WP1b already keeps everything policy- or engine-dependent.
- My concrete recommendations are about re-placing and scheduling work, not cutting it (finding 10).

## 2. Deleting the facade, and the reachability audit

**Deleting the facade is sound, and I verified "zero consumers" myself.**
- `src/breezy/persistence/__init__.py:9-53` re-exports 20 `catalog` names.
- Repo-wide, every `from breezy.persistence import X` imports a submodule: `catalog`, `filesystem_probe`, `archive_cache`, `family_manifest`, `feather_preflight` and so on.
- No string `"breezy.persistence.<facade name>"` exists, and no `from breezy import persistence` exists.
- No pyproject `ignore_imports` entry names the `breezy.persistence → catalog` edge, so removing it cannot trigger import-linter's unmatched-ignore error.
- The precedent at `runtime/__init__.py:15-50` applies word for word. That includes the point that a missing registration fails loudly (TypeError/KeyError), never silently.

**The reachability test as specified has two flaws:**
- The helper the plan calls "moved verbatim" hard-codes `breezy.runtime` (`test_runtime_import_isolation.py:192-215`). It cannot discover `scripts/**` that import `breezy.persistence` without a `prefix` parameter, so it is not a move-only extraction (finding 12).
- The precedent ran the grimp reachability check once, as Stage-0 evidence, and kept only per-entry fresh-process smoke tests in the gate. r2's own unknown #7 says the gate cost is unmeasured (finding 10c).

## 3. Binding note and amendment list (b): consumer breaks not listed

These are folded into findings 1, 2 and 5–8 below.

## Findings

**1. [HIGH] `ResolvedFamily` drops ARCH C5 fields that consumers read** (AC 16; Stub table)
- **Problem:** ARCH :558 requires the resolver to return a `ResolvedFamily` with: family id, `registry_seq`, chain head, and the manifest and artefact bytes and shas. r2's fields are `(family_id, state, entries_allowed, authorising_seq, manifest_sha256, artefact_sha256, export_check)`. Consumers that break:
  - the supervisor's `resolved_registry_seq` and `BREEZY_RESOLVED_REGISTRY_SEQ` (AUT-5 r7 :441, ARCH :582);
  - the node's Z7 prefix check (r7 :410);
  - AUT-1 r12's `DecisionRecord.registry_seq` (:329, via r7 :971);
  - Y6/P7-10, under which `_validate_sending_family_manifest` and `_compose_family` "never re-read" (ARCH :564; r7 :410-411).
- `authorising_seq` is not the head seq.
- **Fix:**
  - Add `registry_seq: int` (the verified head), `chain_head: str`, and either the single-read `manifest: FamilyManifest` plus `artefact_store_path` (repo-relative), or a `FamilyBytes` handle.
  - Add `test_resolved_family_carries_arch_c5_pickup_fields`.
  - If any field is deliberately left out, list it in (b).

**2. [HIGH] Stage S breaks: the genesis-only `HwmAbsent` rule refuses every shadow LAUNCH from day 2** (Edge Cases, HWM rows; binding note 5)
- **Problem:** Under `registry_shadow`, the watch actor keeps its HWM **in memory only** (ARCH :577; r7 :426). So the supervisor's shadow resolve sees `HwmAbsent` against a chain that has ATTEST rows → `hwm_absent` → `agree=false`. WP10's S exit requires "zero `registry_resolve_shadow agree=false`" (r7 :936). r2 never mentions the shadow source.
- **Related liveness gap (L-48):** in production, a node crash after the 16:52:30 ATTEST and before the first verified tick writes the HWM leaves `HwmAbsent` with rows → no sender. The only way out is `breezy-registry-hwm-reset`, and no plan text names it.
- **Fix:**
  - (a) Add a separate public `resolve_shadow_family(...)` that skips the HWM check and returns a distinct `ShadowResolution` type, which cannot satisfy the supervisor's sending port (type plus AST test). Add `test_shadow_resolution_ignores_hwm_and_cannot_send`.
  - (b) Binding note 5: either the L1 cut-over script writes the initial HWM (genesis head) under the exec flock while the node is down, after which `HwmAbsent` with any row always refuses; or name `breezy-registry-hwm-reset` as the clearing path, with `test_hwm_absent_after_attest_clears_via_reset_cli`.

**3. [MEDIUM] The BEFORE INSERT gap trigger lets a venue's first row through** (AC 8)
- **Problem:** `NEW.venue_seq ≠ max(venue_seq | venue)+1`: on an empty venue, `max` is NULL, so the right side is NULL and the WHEN clause is NULL, i.e. false. Genesis can then start at any `venue_seq`. `verify_venue_chain` catches this on read, but AC 8 claims the trigger refuses it. This rests on SQL semantics; I did not probe it.
- **Fix:** use `COALESCE((SELECT max(venue_seq) FROM transitions WHERE venue=NEW.venue),0)+1`, and add `test_first_row_venue_seq_must_be_one` with mutation evidence.

**4. [MEDIUM] Narrowing creates a launch/runtime split** (binding note 4; R16)
- **Problem:** The resolver refuses chains that hold unenabled widening rows. The running node's watch actor (r7 :423) replays only `transitions.validate`. After a narrowing commit, LAUNCH refuses but a live node keeps accepting.
- **Fix:**
  - Export one predicate, `chain.rows_admissible(rows, stage) -> RefusalReason | None`, used by both `_resolve` and the watch actor.
  - Binding note: AUT-5a's `_tick_once` must call it.
  - Add `test_watch_actor_and_resolver_share_admissibility_predicate` (AST).

**5. [MEDIUM] `RegistryUnreadable` lumps SQLITE_BUSY together with real faults** (AC 12)
- **Problem:** AUT-5 r7 :421 treats BUSY as "tick not verified, state unchanged", so 3 busy ticks reach `registry_unreadable`. A single reason makes the first BUSY an immediate veto.
- **Fix:**
  - Give `RegistryUnreadable(reason: Literal["busy","hot_journal","schema_mismatch","io","sqlite_error"])`, and add `test_reader_distinguishes_busy`.
  - Note in (b) that the hot-journal case cannot be told apart from a writer mid-commit (BUSY), as r2 already says.

**6. [MEDIUM] The amendment list (b) is incomplete.** Add:
- AUT-5 r7 :410 `parse_family_manifest(raw, *, origin)` → `(raw, *, path, allow_draft=False)`.
- AUT-7 r5 :56/:703 `verify_family_bytes(row)` → `(row, *, paths, repo_root)`.
- AUT-5 r7 :427 guard cache `bool | GuardUnreadable` → `GuardResult`.
- AUT-5 r7 :116 parameter `legs` → `venue_suffix`.
- AUT-5 r7 WP9 RED list: 4 of its 7 tests now ship GREEN in ARCH-0. WP9 keeps `has_exactly_one_row`, `row_equals_policy_pin` and `root_keeps_own_ruling`.
- AUT-4 r11 :431/:563: they read `lineage_counters` from the DB, but the cache is deferred to AUT-5 WP4. Either AUT-4 reads `fold(...)` `LineageTallies` (pure), or it states that WP4 is a dependency.
- Finding 1's fields.

**7. [MEDIUM] Unverified citation (L-47)** (Stub table)
- **Problem:** The row "`resolve_sending_family` … AUT-6 WP6" has no match. AUT-6 r15 contains no `resolve_sending_family`, `HwmReading`, `registry_hwm` or `ResolvedFamily`.
- **Fix:** correct the consumer, or drop it.

**8. [MEDIUM] `LegFill` fields are unspecified** (Architecture `net_position.py`)
- **Problem:** AUT-2 r7 :335 nets `fills with ts_event ≤ snapshot_ns − grace`. A `LegFill` without a timestamp would force AUT-2 to change a contract-(b) module's record type.
- **Fix:** freeze `LegFill(leg: Literal["yes","no"], side, qty: Decimal, ts_event_ns: int)` now, and pin it in a test.

**9. [MEDIUM] E-14: two amendments** (§ERRATA (a))
- (i) Rule 3 should apply only when the authorising row's family is a BOOTSTRAP-seeded root (BOOTSTRAP, ROOT_ADMIT, ROLLBACK or RESUME to a root). A Y2 no-new-lineage child resolves `artefact.json` in the root's `<sha>/` directory and has no `roots/<child>.json`. Otherwise drill children fail with `root_record_mismatch` once AUT-7b lands.
- (ii) State the order: copies are written before the genesis COMMIT. A crash-rerun is idempotent, with EXISTS_EQUAL on every file, including after the rule-5 chmod to 0500.
- With these two, file it verbatim.

**10. [MEDIUM] Scope and schedule: re-place work rather than cut it** (§Work Packages)
- **(a)** Move WP-1b (the `live_orders_gate` extraction and the lineage gate) to land just before WP-8, its only consumer. WP-1 then carries the minimum live-path surface (init plus split). The lineage verifier is dead code until WP-8, and live code until WP9.
- **(b)** Coordinator note: §5.1's "Wave 0 serial, size M" is now about 15 gated merges at roughly 23–25 min of gate each. ARCH says Wave 1 works "against the stubs only". Declare early-start points: AUT-1a, AUT-2a, AUT-4a and AUT-6 after WP-5; AUT-5a and AUT-7a after WP-8. This needs WP-6…8 signatures frozen in the stub table first, which findings 1, 6 and 8 complete.
- **(c)** Make the grimp reachability check a one-time WP-1 evidence artefact, as the precedent did. Keep `test_persistence_entry_module_imports_cleanly[*]` and the no-consumer AST test as the permanent guards. This removes unknown #7.

**11. [LOW] `paths.root_record` placement contradicts itself.** R1 says "WP-5/6 hold `paths.root_record`", but `paths.py` lands in WP-3. Fix: add `root_record` to `paths.py` in WP-6, together with `family_bytes`, after E-14 is filed.

**12. [LOW] `tests/support/entry_points.py` is not move-only.** The helper needs a `package_prefix` parameter (finding 2 above). State it as "extracted with one parameter; `test_entry_module_list_covers_every_entry_point` passes unmodified". Also run the L-54 pin search on `tests/support/`: `test_mypy_ratchet`, `test_probe_containment` and `test_real_tree_write_guard` all reference it.

**13. [LOW] WP size vs the gate unit.** WP-3 and WP-6…8 run 1,800–2,000 lines. Say explicitly that each split-seam commit is merged and gated on its own (L-43), so no gated unit exceeds about 1,000 lines.

**14. [LOW] `transitions` ↔ `stage_policy` cycle.** `stage_policy` imports `transitions._ADMISSION_IMPLEMENTED`, and `validate(..., stage)` types `StagePolicy`. Fix: put the `StagePolicy` type (or a `StageView` Protocol) in `schemas.py`, and have `stage_policy` build the instance. Add a no-cycle test.

**15. [LOW] Single-read rule vs the lineage gate.** `_verify_ruling_file` keeps `resolve()` + `read_bytes()` (`live_orders_gate.py:164-176`), not the openat path. That is acceptable as move-only, but name it as a reviewed exemption in the "every ARCH-0 reader" AST test, so the test isn't vacuous or red.

**16. [LOW] Path hygiene.** Line 1 of the plan file is agent chatter ("I have what I need. Here is the complete r2 plan."). Delete it before the plan is filed.

## 4. E-14
AMEND (finding 9), then ADOPT.

## 5. Order, activation, tests, LESSONS

- **Order:** linear 1→8 is the true dependency order, apart from finding 10a. I found no other hidden dependency. Two edges check out:
  - `schemas ← rollback_journal` (JournalHead) lands in WP-5, before WP-6.
  - `hwm ← chain` sits in WP-7, after WP-6.
- **WP-1 activation:** sound.
  - It gives the merge window, the supervisor restart window with `KillMode=process`, and natural restarts for recorder and ingest.
  - The technical reason for not forcing restarts is stated with evidence, which satisfies the "activate code immediately" memory.
- **Missing tests:** the tests named in findings 1–5, 8 and 14.
- **LESSONS:** every cited L-number matches its header in `docs/core/LESSONS.md`.
  - L-48 needs a row for finding 2's clearing path.
  - I found no LESSONS violation beyond finding 2b.

## Files
- Plan under review: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r2.md`
- Finding 1 evidence:
  - `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md` (:558, :564, :582, :587)
  - `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md` (:410, :411, :441, :971)
  - `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md` (:329)
- Finding 2 evidence: `AUTONOMY_ARCHITECTURE.md` (:577); `AUT-5-promotion-demotion_plan_r7.md` (:426, :936)
- Facade and `live_orders_gate` checks:
  - `/home/jon/breezy/src/breezy/persistence/__init__.py`
  - `/home/jon/breezy/src/breezy/runtime/__init__.py`
  - `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py` (:130-189; permit check last, so accepting only `permit_absent` is sound)
- Entry-point helper: `/home/jon/breezy/tests/unit/test_runtime_import_isolation.py` (:192-215)
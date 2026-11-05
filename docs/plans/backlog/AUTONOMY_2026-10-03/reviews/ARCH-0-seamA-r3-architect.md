**Verdict: REQUEST_CHANGES.** There is one HIGH, six MEDIUM and eight LOW findings. All of them are text-level fixes. The HIGH has to be fixed before approval because §Stub Surface freezes signatures at approval. I expect r4 to converge.

**E-14: AMEND, then ADOPT.** It needs one addition (finding 6). The r2 F9 scope and order amendments are present and correct.

**Method.** I checked each r2 finding against the r3 text. I verified code with codegraph (`live_orders_gate.py:50-70`, `family_manifest.py:212-295`, `exec/client.py:3442-4731`) and by grepping `pyproject.toml`, ARCH, AUT-2 r7, AUT-4 r11, AUT-5 r7 and the LESSONS headers. Bash was disabled, so I ran no Python probes. Every L-number the plan cites matches its header.

## Scores
| Axis | Score |
|---|---|
| Correctness | 7 |
| Architecture fit | 8 |
| Test coverage | 8 |
| Risk mitigation | 8 |
| Scope minimality | 7 |
| Feasibility | 7 |

## r2 findings 1–16, checked against the r3 text
All 16 are fixed in the text, and A3-R1 to A3-R6 are honoured. Three fixes still leave something behind:
- **F1** (`ResolvedFamily` fields) is fixed in AC 19, but the type cannot carry what binding note 6b needs (finding 3).
- **F4** (shared admissibility predicate) is fixed in AC 13, but AC 10 contradicts it (finding 2).
- **F13** (WP size vs gate unit) is claimed fixed, but the WP table breaks the new cap (finding 7).

The other 13 are clean:
- F2: AC 18 and binding notes 6 and 7.
- F3: AC 8 and V11.
- F5: AC 12 and V12.
- F6: §ERRATA (b) items 1–36.
- F7: stub table.
- F8: AC 22.
- F9: E-14 rules 3 and 6.
- F10: lineage gate moved to WP-8a, early-start table, AC 4 one-time evidence.
- F11: `root_record` lands in WP-6c.
- F12: File plan.
- F14: AC 15.
- F15: AC 7.
- F16: the chatter line is gone.

## Findings

**1. [HIGH] `schemas.py` breaks contract (c), which makes WP-6a red and invalidates the frozen signatures** (AC 1(c); Modules `schemas.py`; File plan deps)
- **Problem:** `schemas.py` defines three types that pull pyarrow into the pyarrow-free core:
  - `ResolverRefusal(detail: UnreadableReason | LiveOrdersReason | None)`. `LiveOrdersReason` lives in `live_orders_gate.py:62`, which imports `family_manifest` (`:53`) → `mechanism_test_guard` → `pyarrow` (V2).
  - `FamilyBytes.manifest: FamilyManifest`.
  - `ResolvedFamily`, which holds `FamilyBytes`.
- `pyproject.toml` has no `exclude_type_checking_imports`, so grimp counts imports under `TYPE_CHECKING` too.
- `schemas` is not in `PYARROW_REACHING`. Neither is anything that imports it: `fold`, `transitions`, `chain`, `hwm`, `stage_policy`. Contract (c), with `allow_indirect_imports=false`, therefore fails at the first `lint-imports` that runs with these types in `schemas.py` (WP-6a, per the WP table), and it fails on the core list.
- **Fix:**
  - Move `FamilyBytes`, `ResolvedFamily`, `ShadowResolution` and `ResolverRefusal` into `resolver.py` or `family_bytes.py`, both of which are already pyarrow-reaching. Alternatively, give `schemas` a local closed `LiveOrdersRefusal` StrEnum that the resolver maps to, and type `FamilyBytes.manifest` through a `ManifestFacts` Protocol.
  - Update the stub table and the frozen-signature module locations to match.
  - Add a planted control to `test_every_autonomy_module_is_classified` that imports `LiveOrdersReason` into a core module and turns it red.

**2. [MEDIUM] AC 10 step 4 contradicts AC 13's one-home rule** (AC 10.4 vs AC 13 `test_admissibility_predicate_has_one_home`)
- **Problem:** `registry_store._append` compares `kind` against `stage.enabled_widening_kinds` and `stage.admission_implemented`. The AST test forbids any `src/` read of either attribute outside `transitions.py`, `schemas.py` and `stage_policy.py`. Built as written, either the test goes red or the store gets a second home for the predicate. That second home is exactly the launch/runtime drift that F4 closed.
- **Fix:** AC 10 step 4 becomes `r = transitions.rows_admissible(widening_rows, stage=stage)`, mapping `widening_kind_not_enabled` to `WideningNotEnabled` and `admission_pending` to `AdmissionPending`. Add a `[store]` parameter to `test_admissibility_predicate_shared`.

**3. [MEDIUM] Binding note 6b/6c cannot be implemented from the frozen `ResolvedFamily`** (AC 16, AC 19, binding note 6)
- **Problem:** The node must write `next_hwm(chain, export_seq=<verified>)`, but `resolve_sending_family` returns only `ResolvedFamily`. That type has no `VerifiedVenueChain` and no export seq (`export_check` is a Literal). The node would have to re-verify the chain and exports itself, which breaks "never re-read".
- The watch actor (Data flow) calls `hwm_check(newest_export_seq=…)` and `next_hwm`, but never `newest_export`. Nothing says where its `export_seq` comes from.
- AC 17 also runs step 3 (`hwm_check`) before step 4 (exports), yet step 3 needs step 4's `newest_export_seq`. The meaning of `newest_export_seq` when there are no exports is not stated.
- **Fix:**
  - Add `verified_export_seq: int` (0 when `not_yet_due`) to `ResolvedFamily`, or add a pure `hwm: Hwm` field equal to `next_hwm(...)`. Extend the pickup test to cover it.
  - Swap AC 17 steps 3 and 4, and define "no export" as `newest_export_seq = 0`.
  - Binding note 6c: the tick carries `export_seq` forward unchanged unless it calls `newest_export`, and it never lowers it.

**4. [MEDIUM] "Fold tallies, same data" is false for `holdout_opens`, and `LineageTallies` is unspecified** (§ERRATA (b) 29; Trade-offs row; AC 14)
- **Problem:**
  - AUT-4 r11 `:431` reads `lineage_counters.{nominations, infeasible_nominations, alpha_spent, holdout_opens}`.
  - ARCH `:431-434` lists `holdout_opens`, but no `transitions` column or row kind records a holdout open (ARCH `:306-307`). It cannot be derived from the fold.
  - `nominations`, `infeasible_nominations` and `alpha_spent` are derivable from the PROMOTE nomination columns. But WP1b owns the k-check semantics, and AC 14 never lists the `LineageTallies` fields, even though the WP-6 to WP-8 signatures are declared frozen.
- **Fix:**
  - Freeze the `LineageTallies` field set in AC 14, derived from ARCH `:431-434`, and mark each field as fold-derived or not derivable.
  - Item 29: AUT-4's `holdout_opens` read stays a WP4 (cache) dependency, or the owner of the counter is named.
  - Add `test_lineage_tallies_fields_equal_arch_counters_minus_non_derivable`.

**5. [MEDIUM] Freezing `LegFill` without cost or fee breaks AUT-2's shared function** (AC 22; (b) 30–31)
- **Problem:** AUT-2 r7 `:116` puts `average_cost_basis(fills, at_ns)` in the **same** `net_position.py`, over the same `fills`. It needs `cumulative_cost` and `fee` per BUY record (`:722`), and `:736` asserts a single definition. `test_leg_fill_fields_frozen` pins `(leg, side, qty, ts_event_ns)`, so AUT-2 must either edit a pinned contract record or add a second fill type.
- **Fix:** Either add `cost: Decimal | None` and `fee: Decimal | None` to `LegFill` now, or state in AC 22 and (b) 30 that `average_cost_basis` takes an AUT-2-owned `CostedFill` and that `LegFill` is netting-only. Amend AUT-2 `:116` to match.

**6. [MEDIUM] E-14 rule 3(a) adds an unstated liveness trap: any committed edit to a root manifest leaves no sender** (§ERRATA (a) rule 3; L-48)
- **Problem:** A3-R1, which binds, ties a root to the byte-exact `deploy/families/<id>.json`. ARCH `:263-264` explicitly expects the repo file to change after bootstrap. `family_manifest.py:249-252` documents setting `terminal_climate_day` "when a family is superseded", which is an ordinary edit. After such an edit, the root, or a ROLLBACK or RESUME to it, refuses `manifest_sha_mismatch` at the next LAUNCH, and nothing catches this before merge.
- **Fix (amend E-14):**
  - Add rule 7: once a root is bootstrapped, its committed manifest bytes are frozen. Back this with a pins literal `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` and `test_bootstrapped_root_manifests_unchanged`, so an edit fails CI instead of failing LAUNCH.
  - Name the clearing path: a reviewed revert of the edit, or a new root through ROOT_ADMIT.
  - Add an L-48 row.

**7. [MEDIUM] Sizing is still not honest (A-R5)** (§Work Packages)
- **Problem:**
  - The table has **21** seams (1a–1c, 2a–2b, 3a–3b, 4a–4b, 5a–5b, 6a–6d, 7a–7c, 8a–8c), not the 23 claimed.
  - Its line estimates add up to about 6,540 src lines and 10,880 test lines (about 17.4k), not about 4.5k + 7k = 11.5k.
  - Four seams exceed the plan's own ~1,000-line gate unit (AC 29): 3a (1,100), 6d (1,300), 7b (1,100) and 8c (1,400). The section header still says "≤ ~800".
- **Fix:**
  - Split 6d into DDL, triggers and append, then reader and export.
  - Split 8c into the sending resolver, then the shadow resolver plus contract lists.
  - Trim or split 3a and 7b.
  - Restate the seam count, the totals and the Wave-0 wall-clock figure.

**8. [LOW] Some store tests depend on WP-7b but sit in the WP-6d file** (Test Strategy `test_registry_store.py`)
- **Problem:** `test_mint_unlimited_by_k_max_but_one_per_day`, `test_drill_mint_not_counted` and `test_drill_close_restore_*` exercise AC 13 rules that land in 7b, but the file lands in 6d.
- **Fix:** Add a test-to-seam column, or state that these tests are added in 7b.

**9. [LOW] Shadow `not_yet_due` is undefined** (AC 18)
- **Problem:** The AC 17.4 rule keys on `hwm.export_seq == 0`, but `SKIP_SHADOW` has no HWM.
- **Fix:** Under `SKIP_SHADOW`, treat it as `export_seq = 0` with the same 26 h genesis bound, and add a test for shadow day 2 with no export.

**10. [LOW] The cut-over HWM write has no lock-timing relation to E-8** (binding note 6d vs AUT-5 r7 `:937`)
- **Problem:** The write runs "after bootstrap exit, before 16:50Z" under the exec flock. The 16:45 pre-launch E-8 snapshot holds the intent flock until 16:48:00 (`test_exec_snapshot_releases_by_164800`).
- **Fix:** Pin the slot. Either run it in step (3)'s window, at or before 16:44:55, or after pre-launch has exited, using `flock -w` with a stated bound. Name which flock is meant.

**11. [LOW] Batch `rows_admissible` vs "a restrictive row is always applied"** (binding note 5 vs r7 `:423`)
- **Problem:** A batch refusal also holds back a later restrictive row in the same batch. Entries are vetoed, so this fails closed, but the fold lags.
- **Fix:** Evaluate per row in chain order, stop at the first refused widening row, and state that the restrictive rows before it still apply.

**12. [LOW] No contract test on the fill-side vocabulary** (AC 22)
- **Problem:** `FillRow.order_side` is mapped to `LegFill.side` with no contract against the writer's `_RECORD_SIGNS` (`client.py:3442-3455`). Vocabulary drift would make the veto permanent (UNREADABLE), though it fails closed.
- **Fix:** Add `test_fill_row_side_vocabulary_matches_exec_record_signs`, an AST read of the pinned client.

**13. [LOW] The L-42 claim overstates what the plan does** (LESSONS table)
- **Problem:** L-42 requires fixtures written **through the real writer**. "Real `DurableFillRecord` shape" is weaker.
- **Fix:** Binding note 10: the AUT-5a `[adapter_reader]` test writes its fixtures through `record_fill`.

**14. [LOW] `AC 30` names the import set but not the merge order** (non-blocking)
- **Problem:** The sentence "Each new function's callers live in the same file" also holds for WP-8a only if WP-8c, which adds the first external caller of `lineage_policy_authorized`, merges after the node has picked up 8a.
- **Fix:** Add one sentence saying so.

**15. [LOW] Early-start table, AUT-4a row** (non-blocking)
- **Fix:** Its "`LineageTallies` reads after WP-7a" entry is valid only once finding 4 is resolved, so cross-reference it.

## Questions asked
1. **Fidelity to the rulings:** all six rulings are met. A3-R1's side effect is handled in finding 6.
2. **Consistency with the consumer plans:**

| Item | Result |
|---|---|
| L1 cut-over HWM write | Consistent with Y7 and r7 `:937`/`:940`; timing gap in finding 10 |
| Shadow resolution | Consistent with ARCH `:575-579`; gap in finding 9 |
| `rows_admissible` in `_tick_once` | Consistent with r7 `:423`; findings 2 and 11 |
| `ResolvedFamily` pickup fields | Consistent with ARCH `:557-558`, r7 `:410`/`:441`/`:971` and AUT-1 `:329`; missing field in finding 3 |
| `LegFill` | Conflicts with AUT-2 `:116`/`:722` (finding 5) |
| `lineage_counters` → fold tallies | Partly false (finding 4) |

3. **E-14:** AMEND (finding 6), then ADOPT.
4. **WP plan:**
   - The dependency order is sound, and the early-start points are sound apart from AUT-4a (finding 15).
   - The live seams 1a, 1c and 8a are sound: same-file callers, the AC 30 import pin, the merge window, a supervisor restart under `KillMode=process`, and one-file reverts.
   - The size and count claims are not (finding 7).
5. **Hidden dependencies, tests, LESSONS, path hygiene:**
   - Hidden dependencies: findings 1, 3 and 10.
   - Missing tests: findings 4, 6, 8 and 12.
   - LESSONS: L-42 is overstated (finding 13). L-48 needs a row for finding 6.
   - Path hygiene: clean. Paths are absolute and the probe scratch is under `/tmp/claude-1000/a0r3/`.

## Files
- Plan: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r3.md`
- Evidence:
  - `/home/jon/breezy/src/breezy/persistence/live_orders_gate.py` (`:53`, `:62-70`)
  - `/home/jon/breezy/src/breezy/persistence/family_manifest.py` (`:249-252`, `:293-295`)
  - `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (`:3442-3455`, `:4645`, `:4712-4731`)
  - `/home/jon/breezy/pyproject.toml` (`:61-72`, no `exclude_type_checking_imports`)
  - `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md` (`:255-264`, `:306-307`, `:431-434`, `:553-608`, `:618-637`)
  - `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md` (`:410-428`, `:936-940`, `:974`)
  - `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r11.md` (`:431`, `:563-568`)
  - `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md` (`:116`, `:335`, `:722`, `:736`)
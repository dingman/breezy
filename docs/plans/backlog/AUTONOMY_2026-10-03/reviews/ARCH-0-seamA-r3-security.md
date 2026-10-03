**Verdict: APPROVE**

Findings 1 and 2 are small text amendments to fold in before the WP-6a and WP-7c briefs are dispatched. Neither is a blocking design flaw. I found no CRITICAL or HIGH issues, no new widening path inside ARCH-0, and no new fail-open path inside ARCH-0. There is no rollback-past-DEMOTE path inside ARCH-0 beyond the stated R14 windows. One such path sits in the AUT-5a reset CLI (finding 5).

I read the full r3 text against my r2 findings and did not use the disposition table. For code facts I read `live_orders_gate.py:100-190`, `exec/client.py:920-1000`, `leg_prices.py`, the `pyproject.toml` import-linter settings and the head of `family_manifest.py`. I ran no probes.

## Scores

| Criterion | Score |
|---|---|
| Correctness vs ARCH | 8 |
| Security | 8 |
| Test coverage | 8 |
| Risk mitigation | 8 |
| Scope minimality | 6 |
| Feasibility | 7 |

Scope minimality is 6 because the plan is about 11,500 changed lines across 23 gated merges. A-R3 already ruled that scope in, so I only note it.

## r2 findings checked against the r3 text

| r2 finding | Result | Where in r3 |
|---|---|---|
| 1 root anchor (HIGH) | CLOSED. A root reads only `deploy/families/<id>.json` under REPO, the sha must equal `row.manifest_sha256`, and `CHILD_FAMILY_ID_RE` is not consulted. E-14 rule 3 pins `committed_path` exactly. | AC 17 step 9, E-14 rule 3 |
| 2 HWM mid-chain (HIGH) | CLOSED, with an indexing gap (finding 1). Hash at `hwm.venue_seq`, one decoder `hwm_reading_from_bytes`, `HwmAbsent(` construction banned outside `hwm.py`. | AC 16 |
| 3 rollback windows | CLOSED. W1 is stated in R14. W2 is closed because Absent always refuses. A listing error gives `export_unreadable`. The node boot HWM write is in binding note 6b. | R14, AC 17 step 4, note 6 |
| 4 arrow registry | CLOSED. One-time per-entry `_SCHEMAS` diff plus a permanent fresh-process smoke test. | AC 4 |
| 5 `StagePolicy` rebuild | CLOSED in intent, with an AST precision gap (finding 3). | AC 15 |
| 6 corpus sufficiency | CLOSED. Coverage gate, symlink-escape built in `tmp_path`, ruling-site coverage, and the missing-directory semantics stated (the loader keeps its guard; callers refuse a missing directory). | AC 20, 21 |
| 7 guard fail-opens | CLOSED. `open_intent_blocks` is called first and documented as venue-global. The key contract test covers ids and the AST of the pinned client. The adapter-prefix half is carried to AUT-5a. | AC 22 |
| 8 child-ness by name | CLOSED, with a gap on other introducing kinds (finding 4). | AC 14, 17 |
| 9 shared contract test file | CLOSED. Byte-diff evidence and one stated parameter. | File plan, WP-1 brief |
| 10 mixed-version live node | CLOSED. The import-set pin and the "callers live in the same file" argument hold. | AC 30 |
| 11 shared-sha roots | CLOSED. Three tests. | AC 28 |

The r3 text confirms that `live_orders_authorized` returns `no_ruling` when the manifest has no ruling, and that `permit_absent` is reached only after the allowlist, path and sha checks. Accepting only `permit_absent` is therefore fail-closed.

`DurableFillRecord.order_side` is the Nautilus instrument-leg side, which is not the venue side. The venue reports a NO buy as SELL, but the record keeps BUY. The `net_signed_qty` signs (NO BUY is −q) are correct, and I found no sign-flip fail-open.

## New r3 items scrutinised

- **HwmAbsent always refuses, with the L1 cut-over writing the initial HWM.** Sound. Clearing paths are named, and R20 states the cost as a restrictive refusal.
- **Shadow resolver as a separate type.** Sound. `ShadowResolution` shares no base with `ResolvedFamily`, and `SHADOW_CALL_SITES` is empty. See finding 7 for a defence-in-depth gap.
- **`rows_admissible` as a shared predicate.** The design is sound, but AC 10 step 4 contradicts it (finding 2).
- **StagePolicy construction ban.** Sound in intent, with AST precision gaps (finding 3).
- **Root/child decided by fold `origin`.** Sound for BOOTSTRAP, ROOT_ADMIT and MINT. Other introducing kinds are unspecified (finding 4).
- **Root manifest read only from `deploy/families`.** Sound.
- **Entry-guard key contract test.** Sound. `FillIndexAbsent` reads as flat only if the adapter prefix matches, which AUT-5a owns. Binding note 10 covers it.
- **Contracts (b) and (c) split.** The split is right, but a layering clash will break (c) (finding 2).
- **Per-seam live-path activation (WP-1a, WP-1c, WP-8a).** Sound. The merge window, the AC 30 import-set pin and the "one file per seam" revert all hold.

## Findings

**1. MEDIUM, AC 16 `hwm_check` and `Hwm.from_wire`: the HWM seq indexing is unspecified, which allows an off-by-one or a bypass.**
- The text says `rows[hwm.venue_seq].transition_hash` for any `venue_seq ≤ head`. `venue_seq` is 1-based and `rows` is a 0-based list.
- A literal reading raises IndexError at `venue_seq == head`.
- An `Hwm(venue_seq=0)` has no row to compare, so it would pass all three `hwm_regressed` tests and never be Absent. A negative value would index from the end of the list in Python.
- Fix: add the following to AC 16.
  - `Hwm.from_wire` requires `venue_seq ≥ 1`, `export_seq ≥ 0` and a 64-hex `chain_head`.
  - `hwm_check` refuses `venue_seq < 1` as `hwm_unreadable`.
  - The compared row is `rows[venue_seq − 1]`.
  - Any non-`HwmAbsent`/`HwmPresent`/`HwmUnreadable` input maps to `hwm_unreadable`.
  - Add `test_hwm_seq_zero_and_negative_refused` and `test_hwm_at_head_compares_last_row`.

**2. MEDIUM, AC 1 contract (c) versus `schemas.py` and AC 10 step 4: two contradictions.**
- (a) `FamilyBytes` (holding `manifest: FamilyManifest`) and `ResolvedFamily` live in `schemas.py`, which is in the pyarrow-free core.
  - `family_manifest` reaches pyarrow through `mechanism_test_guard` (V2).
  - `pyproject.toml` has no `exclude_type_checking_imports`, so even a `TYPE_CHECKING` import counts.
  - Contract (c) would fail at WP-6a for `schemas`, `fold`, `transitions`, `chain`, `hwm` and `stage_policy`.
  - Fix: move `FamilyBytes` and `ResolvedFamily` to `family_bytes.py` and `resolver.py`, which are already in `PYARROW_REACHING`, and keep only pyarrow-free types in `schemas`. Add a WP-6a RED check that (c) is kept with a planted pyarrow import.
- (b) AC 10 step 4 has the store compare `kind ∈ stage.enabled_widening_kinds` and `admission_implemented` itself.
  - That contradicts the AC 13 AST test `test_admissibility_predicate_has_one_home`.
  - It also uses exception names, `WideningNotEnabled` and `AdmissionPending`, that are not `RefusalReason` members.
  - Fix: step 4 becomes "call `transitions.rows_admissible(rows, stage=stage)` and map its `RefusalReason` to the `append` error".
  - Add `test_append_uses_shared_admissibility_predicate`.

**3. MEDIUM, AC 15: the AST ban cannot resolve argument types, and the `stage=` parameters are duck-typed.**
- "`dataclasses.replace` or `copy.*` of a `StagePolicy`" cannot be decided by AST.
- `StagePolicy` can also be rebuilt through `type(stage)(...)`, `stage.__class__(...)`, `object.__new__`, an import alias (`from schemas import StagePolicy as SP`), or any object with the two attributes passed as a `StageView`.
- Impact is limited. The store and resolver use `stage_policy.STAGE` through the private `_append` and `_resolve`, so the exposure is pre-checks only.
- Fix:
  - Ban every `dataclasses.replace`, `copy.copy`, `copy.deepcopy`, `__class__` call, `type(<expr>)(...)` and `object.__new__` call across `persistence/autonomy`, `strategy/autonomy` and `analysis/autonomy` outside the homes.
  - Resolve import aliases when scanning for `StagePolicy`.
  - Plant a positive control for each form.
  - Have `_append` and `_resolve` assert `stage is stage_policy.STAGE` unless called under a test-only seam, so a duck-typed stage cannot enter the sending path.

**4. MEDIUM, AC 14: `FamilyView.origin` is undefined for a family introduced by any other kind.**
- AC 14 defines origin only for BOOTSTRAP, ROOT_ADMIT and MINT. A family first appearing via ROLLBACK, RESUME or PROMOTE has no defined origin.
- Fix: say that fold marks the chain invalid (`chain_broken`/`replay_invalid`) for any family whose introducing row is not one of those three. Also state that a BOOTSTRAP or ROOT_ADMIT row with `lineage_root_family_id != family_id` is invalid, never "child". Add `test_family_introduced_by_other_kind_is_invalid`.

**5. LOW (non-blocking, AUT-5a scope), binding note 6e: the reset CLI is a rollback-past-DEMOTE path before the first export.**
- Before the first export there is no external anchor. A same-uid actor can delete the HWM, which forces `hwm_absent`.
- The only recovery is then `breezy-registry-hwm-reset` verifying from genesis, which blesses whatever chain is on disk. That could be a chain with a DEMOTE or HALT removed.
- Fix:
  - The CLI must print the head hash and every standing DEMOTE or HALT row it is accepting.
  - It must require an out-of-band `--expect-head <hash>` argument.
  - It must refuse if the proposed state is less restrictive than the last HWM known to the operator alerts.
  - Add `test_hwm_reset_requires_expected_head`.
  - R14 should say that Absent-refusal is a tripwire against accidental deletion, not a control against a writer. A same-uid actor can also write a low HWM at `venue_seq=1`.

**6. LOW (non-blocking), binding note 8: a held lock delays DEMOTE visibility.**
- A held lock makes the reader return `busy` for up to `WATCH_TICK_STALE_S` (180 s). During that time the watch actor keeps the last verified state.
- This is restrictive-by-timeout and acceptable. Record it in R14 as a demotion-latency residual, and bound the `busy` retry count in the supervisor to LAUNCH only.

**7. LOW (non-blocking), AC 17 and AC 18: the shadow/sending split is enforced only at the two public entry points.**
- Fix: add a defence-in-depth assertion in `_resolve` that `(hwm_mode is SKIP_SHADOW) == paths.is_shadow`.
- State that `ShadowPaths` is not a subclass of `AutonomyPaths`. The step 1 check must use `is_shadow`, not `isinstance`.
- Add `test_resolve_private_rejects_skip_hwm_on_production_paths`.

**8. LOW (non-blocking), File plan, `test_runtime_import_isolation.py`: the stated hunk contradicts itself.**
- The plan says "import-block hunk only", but the module constants at `:55-60` that the helpers use must either stay in the test file or be imported from `entry_points`.
- Fix: state which. The simplest is that `entry_points.py` owns the constants and the test imports them. The `git diff` evidence must then show that no assertion line changed.

**9. LOW (non-blocking), E-14 rule 5: the 0500 chmod can break a Y2 child refit.**
- A refit that wants to add `lineage.json` into a root's `<sha>/` directory would hit EACCES. That fails closed.
- Add a one-line note that AUT-3 refits write into a fresh `<sha>/` only, and a test `test_refit_into_root_sha_dir_fails_closed`.

## E-14 verdict: ADOPT

- Per-family `roots/<family_id>.json` fixes the EXISTS_DIFFERENT deadlock fail-closed.
- Rule 3 now carries my r2 amendment: `committed_path == "deploy/families/<id>.json"` exactly, with bytes read under REPO and checked against `manifest_sha256`.
- Rule 6 (pre-read EXISTS_EQUAL before any temp file) makes the rerun idempotent after the 0500 chmod.
- Rule 5 is correctly labelled hygiene and not counted as an anchor.
- Residual: item 9 is a minor interaction, not a blocker.

## Amendment list (b)

I agree with items 1 to 3 and 24. Items 8 and 9 need the wording from findings 1 and 2.

## Invariants

All hold.

| Invariant | Evidence |
|---|---|
| Operator-reserved controls never assigned or read | `test_autonomy_never_reads_or_writes_operator_controls`; tokens from `operator_controls.py:142` |
| Enablement, permit and NO-SEND untouched | `permit_present=False` is the only call form, only `permit_absent` is accepted, `ResolvedFamily` has no `enabled` or permit field, and `ENGINE_SOURCE_SHA256` is empty so production resolution refuses by design |
| `allow_short` stays False | Not touched. A negative net position vetoes as HELD. |
| No safety, settlement or contract test weakened | Listed tests pass unmodified; the one helper move has byte-diff evidence (finding 8) |
| Exec client byte-pinned | Read by AST only, with `test_exec_client_never_edited` |

Plan reviewed: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r3.md`
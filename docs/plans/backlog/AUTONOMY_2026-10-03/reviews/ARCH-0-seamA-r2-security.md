**Verdict: REQUEST_CHANGES**

| Criterion | Score |
|---|---|
| Correctness vs ARCH | 7 |
| Security | 7 |
| Test coverage | 8 |
| Risk mitigation | 7 |
| Scope minimality | 5 |
| Feasibility | 6 |

All r1 HIGHs are fixed in the text except where finding 1 and finding 2 below reopen part of H1/H4. The big structural fixes hold up: frozen `STAGE`, the resolver-side widening refusal, the BEFORE INSERT trigger, the openat walk, `GuardResult`, and the golden corpus built on unsplit code first. The remaining gaps are specification holes in the two controls that are meant to be the external anchors. I read the r2 plan in full, `live_orders_gate.py:100-190`, `family_manifest.py:255-335`, `persistence/__init__.py`, and ARCH C5 `:557-636`. I ran two greps for facade consumers. I ran no code probes.

## r1 finding verification

Fixed, verified against the r2 text rather than the disposition table:
- **H1:** AC 16 plus the edge-case row refuse any chain row outside `enabled`/`admission_implemented`. The forged-chain test exists.
- **H2:** `lineage_policy_authorized` and `_verify_ruling_file` are in AC 17 with the negative cases. `permit_present` is correctly not a parameter.
- **H3:** frozen `STAGE`, private seams, a broad AST scan and subset gates. One gap remains (finding 5).
- **H5:** the openat walk, dirfd `write_once` with `fchmod`, a nofollow EEXIST compare, and `O_NONBLOCK`.
- **H6:** the callers' prereg check, the `allow_draft` scan, and the golden corpus. One sufficiency gap remains (finding 6).
- **H7:** `GuardResult`, Absent versus empty, and the catch-all are in. Two residual fail-open paths are in finding 7.
- **M1-M11, L1-L5:** closed in the text. Q5 is closed too: node ids with params, a floor file, and the promoted list.

Rejected items, judged on their reasons:
- **H4 node-marker variant: reason sound.** A marker is another same-uid file. The genesis-only rule is stricter. This is accepted, but the HWM comparison is under-specified (finding 2).
- **M6 role-label path: reason sound.** `path` drives `_assert_artefact_path_contained` (`family_manifest.py:276`), so relabelling would break byte-equivalence. The returned-value enum plus the hygiene scan is the right fix. The scan must also cover `repr(__context__)`. It cannot, because the refusal is a returned value, so this holds.

## Findings

### HIGH

**1. Root manifest authority is not anchored to the committed file (AC 16, AC 18, E-14 rule 3).**
- `live_orders_authorized` pins `(family_id, ruling_id, ruling_sha)`. It does not pin manifest bytes (`live_orders_gate.py:148-162`).
- The ARCH root exemption (`AUTONOMY_ARCHITECTURE.md:605-606`) makes "manifest bytes equal the committed `deploy/families/<id>.json`" the actual external anchor.
- r2 says only that `family_bytes` reads from `deploy/families` or `registry/families`. It never states that a root's bytes must equal the committed file.
- A root manifest read from the writable `registry/families` copy could name an allowlisted `family_id` and ruling with arbitrary other content.
- Fix:
  - AC 16 and `family_bytes`: for a BOOTSTRAP or ROOT_ADMIT authorising row, read `deploy/families/<row.family_id>.json` under `ReadPolicy.REPO`. Require `sha256 == row.manifest_sha256`. Refuse `manifest_sha_mismatch` otherwise.
  - Add `test_root_manifest_must_equal_committed_bytes`, where a `registry/families` copy with an altered body but an allowlisted id is refused.
  - E-14 rule 3 gains: `committed_path == f"deploy/families/{family_id}.json"` exactly, not just "repo-relative".

**2. HWM comparison is specified only at the head (Edge Cases, HWM rows; AC 16).**
- The text says "seq above head, same seq with a different head". ARCH Y4 (`:618-620`) re-checks that the row at the last verified seq still carries the stored hash.
- If the resolver compares only `hwm.chain_head` to the head when `hwm.seq == head.seq`, a rewritten history passes.
  - Example: drop the DEMOTE at seq 5, recompute the hashes, and append two rows to reach seq 7. With `hwm.seq = 5`, this passes.
- Fix:
  - `hwm_check` must require `rows[hwm.venue_seq].transition_hash == hwm.chain_head` for every `hwm.venue_seq ≤ head.seq`.
  - Add `test_hwm_mid_chain_hash_mismatch_regressed`, using a rewritten prefix with a longer head.
  - Add `hwm_reading_from_bytes(raw: bytes | None) -> HwmReading` in `hwm.py` (None → `HwmAbsent`, decode error → `HwmUnreadable`) and unit-test it.
  - Binding note 5 currently leaves that Absent/Unreadable mapping to each AUT-5a caller. A caller that maps a decode error to `HwmAbsent` makes the genesis-only rule trivially bypassable.

### MEDIUM

**3. Rollback-past-DEMOTE is still possible in two windows (Edge Cases; binding note 5; R14).**
- The HWM advances only after a verified read by the node (ARCH `:621-624`). A DEMOTE or HALT appended during a prelaunch window with no node watching is covered by no HWM and no export until the next export. A rewrite back to the prior head is therefore undetectable. This is a same-uid action (R14), but it is the very attack H4 targeted.
- The genesis-only Absent window is about 26 hours. HWM deleted, chain truncated to the genesis BOOTSTRAP rows, and no export file yet.
- State both windows explicitly in the R14 row.
- Add a binding-note obligation: the node writes its HWM at boot immediately after a successful resolve and before any entry. This narrows the first window to the interval before the first resolve.
- The Absent rule must also require that listing the exports directory itself succeeded. A listing error must give `export_unreadable`, not "no export file".

**4. Facade deletion: the reachability proof is static only (AC 4, R7).**
- My greps found no facade consumers. They also found no string-form importable paths (`"breezy.persistence:X"` or `breezy.persistence.<Name>`) in `src`, `scripts`, `deploy` or `tests`. V3 holds.
- `register_arrow` is a runtime side effect. The grimp test models imports, not the registry state.
- Fix: add `test_persistence_init_preserves_arrow_registry_per_entry`. For each entry module, in a fresh subprocess, import the entry and dump the registered Nautilus arrow class set. Compare it to the same dump from a scratch copy that keeps the old `__init__`. Any difference fails, unless the entry sits in a reviewed exemption. This is cheap and directly proves "what runs today is unchanged".

**5. `StagePolicy` can still be rebuilt in `src/` (AC 15).**
- The AST bans cover mutation and the private functions.
- `transitions.validate(..., stage=...)` and `fold`/`replay` take a policy parameter. Nothing bans `StagePolicy(...)` construction, `StagePolicy.from_pins()` or `dataclasses.replace(STAGE, ...)` outside `stage_policy.py`.
- Today that only affects pre-checks, since the store and resolver use `_append`/`_resolve`. It is one future import away from a widening seam.
- Fix: extend `test_autonomy_policy_not_mutable_from_src` to refuse all three forms outside `stage_policy.py`. Add a planted control for each.

**6. Golden-corpus sufficiency (AC 18).**
- The corpus is 7 committed manifests plus 16 mutations. Nothing proves that it reaches every raise site of the moved body (`family_manifest.py:296-460`) or the three raise sites of `_verify_ruling_file`.
- The artefact-containment branch needs artefact files and a symlink-escape fixture inside the corpus directory. `_assert_artefact_path_contained` resolves relative to `path.resolve().parent` (`:276`).
- The prereg guard is `if path.parent.exists()` (`:293`). The plan's resolver check does not say it keeps the `exists()` condition.
- Fix:
  - Commit 1 gains a gate: branch coverage of the pre-split `load_family_manifest` body is 100% under the corpus. Record the coverage report as the artefact.
  - Add the same for the three `live_orders_authorized` refusal sites (`ruling_outside_evidence`, `ruling_missing`, `ruling_sha_mismatch`).
  - The corpus directory carries its artefact files and one symlink-escape case.
  - Resolver and store callers keep the identical `if dir.exists()` guard, or refuse a missing directory as `manifest_unreadable`. State which.

**7. Entry guard residual fail-opens (AC 19).**
- `FillIndexAbsent → FLAT` is the one remaining fail-open. A key-format mismatch between the reader and the writer (suffix, slug form) reads as "never written". The real-writer check is carried to AUT-5a (`[adapter_reader]`).
  - Add in ARCH-0 a read-only contract test. It derives the key through the same builder that `exec/client.py` uses and asserts equality with the reader's key. Reading the pinned client is allowed. It also catches a `^no` suffix drift.
- `open_intent_blocks()` takes no argument. One stale OPEN or AMBIGUOUS intent anywhere vetoes every rung. That is fail-closed, but it is an availability trap. The node memory shows a prior launch deadlock of this kind.
  - Say that this is the deliberate global scope in the docstring. Order the call first inside the try block.

**8. Child-ness must come from the chain, not the name (AC 17, AC 16).**
- `CHILD_FAMILY_ID_RE` matches any id ending `_rNNNN`. A root named `x_r0001` would route as a child of `x`, and the `x` allowlist row would apply to it.
- Fix: the resolver decides root versus child from the authorising row's kind and lineage (a BOOTSTRAP or ROOT_ADMIT row means root). `root_family_id` passed to `lineage_policy_authorized` comes from the fold's lineage root. The regex is only a consistency check on top (`regex group == fold root`).
- Add `test_root_named_like_child_is_not_routed_as_child`.

### LOW

**9. WP-1 touches a shared contract test file (File plan).**
- `tests/support/entry_points.py` is a "move-only" extraction from `test_runtime_import_isolation.py`. The invariant bars weakening a contract test.
- Add a gate step that diffs the moved helper bodies byte-for-byte against the pre-move text. Keep `test_runtime_import_isolation.py`'s assertions unchanged.

**10. WP-1 merge against a live node (WP table).**
- The install is editable and the node runs all day. The stated merge window is [16:30Z, 17:10Z).
- State that WP-1 adds no new cross-module dependency from an already-loaded module to a changed one. Alternatively, merge only when the node process is down.

**11. `ROOT_ARTEFACT_COMPONENT = "density_table"` is also used for roots whose "density" artefact is the `not_applicable_density.json` placeholder.**
- That is fine because of rule 4's EXISTS_EQUAL.
- Add a test that two roots sharing a sha produce an identical `artefact.json` byte compare.
- Add a test that EXISTS_DIFFERENT raises INTEGRITY.

## Answers to the new-focus questions

1. **WP-1 live-path changes:** no change to what trades today, provided findings 4 and 6 land.
   - Facade removal: there are no consumers, and no string-form import paths exist. The residual is the runtime `register_arrow` equivalence (finding 4).
   - `parse_family_manifest` split: a pure move, but corpus sufficiency is unproven (finding 6).
   - `_verify_ruling_file`: a sound extraction, and the existing fixtures are unmodified.
   - New `lineage_policy_authorized` is unreachable today. The allowlist is empty, and no caller exists until the resolver, which itself refuses at ARCH-0 because the pins are empty.
   - Golden corpus: sufficient for the split only with the coverage gate from finding 6.
2. **STAGE / `_ADMISSION_IMPLEMENTED`:** the store and resolver are locked on both sides. One residual widening seam exists (finding 5). R16's narrowing effect is fail-closed, so I consider it acceptable.
3. **HWM and `export_seq`:** the absence bypass is closed, but mid-chain hash verification is missing (finding 2) and two time windows remain (finding 3). Rollback past a DEMOTE is therefore still possible inside R14 unless findings 2 and 3 are applied.
4. **GuardResult and `FillReader.open_intent_blocks`:** correct as an enum and exhaustive. See finding 7.
5. **New findings:** 1 (root anchor), 8 (child by name), 9, 10, 11.

## E-14 verdict (security angle)

**ADOPT WITH AMENDMENT.** The per-family `roots/<family_id>.json` design is sound. It fixes the EXISTS_DIFFERENT deadlock fail-closed. The record-versus-row checks in rule 3 are right. Add to rule 3:
- `committed_path == "deploy/families/<family_id>.json"`.
- The bytes at that path hash to `manifest_sha256` and are read under `ReadPolicy.REPO`. This is finding 1.

The 0500 chmod in rule 5 is hygiene only, not a control, since the owner can chmod back. Do not count it as an anchor in the risk register.

## Required before approval

Findings 1 and 2 are exact-text changes to AC 16, AC 18, the HWM edge-case rows, `hwm.py` and E-14 rule 3. Findings 3 to 8 are tests and clarifications. After they land, I expect APPROVE.

Plan reviewed: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r2.md`.
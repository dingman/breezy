# AUD-10 — Review record (Round 7, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 7bfea8e92b7a6e822b200122c8706cbcbd81571ac0f021329eb1ec3398ee4f2f (coordinator recorded
  7bfea8e92b7a6e822b200122c8706cbcbd81571ac0f021329eb1ec3398ee4f2f)
- Round: 7 (delta) · Reviewer: architect (module boundaries, versioned inter-stage contracts,
  idempotency, import layering, exchange portability, YAGNI)
- Total: 100/100 · Readiness: READY

## Round-6 disposition, verified against the plan body and against the sections it cites

| R6 defect | Claimed | Verified? |
|---|---|---|
| **10-8 (MINOR)** — two cross-references in the newly written §11 pointed at sections that did not carry the claim: (1) *"Both `INERT`s … tested by C17(g)"* — C17(g) tests only the `C-KILL` inert, `C-PAIRED`'s is pinned by C14; (2) *"Both are out of this item's scope (§5)"* — §5 excluded the `--family-manifest` dependency but carried **no bullet** for standing up a champion-scoped KILL clock, so §5, the exclusions list an implementer reads, was incomplete on the dependency that makes the plan's central predicate inert | ACCEPTED, both parts | **FIXED, both, and part (2) was taken in the order I recommended — completing §5 rather than weakening §11.** **(1)** §11 now reads *"…recorded in **C8**, tested by **C14** (`C-PAIRED`) and **C17(g)** (`C-KILL`), excluded from this item's scope by the two §5 dependency bullets, and named with owners in §12"*. Checked against the criteria themselves: **C14** pins `C-PAIRED` as literal `INERT` with `inert_reason="NO_CHALLENGER_REPLAY_PATH"`, never `false`, plus the run-wide `PROPOSAL` bar — so the attribution is exact; **C17(g)** pins the `C-KILL` inert by `manifest_sha256` identity *and* the evaluation order (a wrong-family file that is also stale still reports `INERT`, not `KILL_CLOCK_STALE`) — also exact. **C8** does record both as the expected steady state, and **§12** does name both with owners. Every clause of the revised sentence is now true of the section it names. **(2)** A new §5 bullet sits **directly after** the `--family-manifest` bullet: *"**Standing up a champion-scoped KILL clock.** No change to `deploy/systemd/score-live-trials-run.sh` or its hard-coded `FAMILY_MANIFEST` (`:47`), and no second counter invocation — the dependency `C-KILL` would need. Named as a dependency (§6b.3, §11, §12; owner PROGRESS R-4 / AUD-05), not taken here."* It is correct at source (`score-live-trials-run.sh:47` is `FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"`, which I verified in round 5 and which §6b.3 item 1 and §12 both cite), it parallels the neighbouring bullet's form and closing phrase, it is consistent with §6b.3's recorded rejection of option (b) (a self-computed counter inside a 3G/4G cgroup), and it carries the owner. **As a side effect it also repairs the second, identical occurrence** I had folded into the same defect: the COMPOUND-limit paragraph's *"Both are out of this item's scope (§5)"* is now literally true, because two such bullets exist. |

## Regression sweep

- **§5** — all eight bullets intact and in order (arming; writing into `deploy/families/`;
  `SUPPORTED_STATIONS` / frozen archive table; `current_rung_hold_paper_replay.py`; **new** KILL
  clock; PREREG v3 semantics and fee pins; manifest-validation refusals; the exactly-one-sending-
  family invariant). Nothing was displaced or reworded.
- **§11** — all four paragraphs intact: the opening (both `INERT`s with their literal `inert_reason`s
  and the deployed cause), *Plausible stated as plausible*, the **COMPOUND limit** (both
  dependencies, both owners, PROGRESS R-4 at `docs/core/PROGRESS.md:73`, AUD-05 by id only with the
  non-assertion, "no change to this plan", and the "machine-checked REFUSAL WITH REASONS, not a
  working promotion path" statement), and the **re-gated abandonment criterion** with its
  override-by-construction reasoning. Unchanged apart from the one sentence.
- **§6b.3** — the `C-KILL` binding table and *Whose KILL clock is it?* re-read in full: the MAX-AGE
  rule, the champion-scope rule evaluated FIRST on `manifest_sha256`
  (`family_manifest.py:185,220`; `structural_dead_stop.py:349`), the provenance rule correctly
  re-framed as a post-match integrity cross-check with the `:152-160` "mirror" claim still explicitly
  withdrawn, and the permissive-trap row. Untouched.
- **§12, C8, C14, C17, C19** — untouched; only their line numbers shift by the four lines the new
  bullet adds, and no citation in this plan is to its own line numbers.
- **Cross-plan** — the §6b.4 property sentence and AUD-09's B18 copy are unaffected by these edits,
  so the coupling verified in round 6 still holds.

## Defects found in revision 7

**None.** Both edits are exactly the two required changes, correct against every section they cite
and against source, and neither introduced a new claim.

Two **non-scoring notes**, offered rather than required — I considered each as a deduction and
rejected it, so the judgement is auditable rather than silent:
- The new bullet's phrase *"and no second counter invocation"* could, read in isolation, appear to
  bar **C17's fixture recipe**, which generates two arms by invoking
  `structural_dead_stop.py --family-manifest` against the v4 and v2 manifests. It does not: the
  bullet's subject is standing up a *deployed* clock (its first clause names the unit wrapper, its
  last clause names the dependency `C-KILL` would need), and §7 step 12 and C17's evidence column
  both instruct the fixture generation explicitly. If the coordinator wants the ambiguity gone, the
  one-word fix is "no second **deployed** counter invocation".
- §13 carries no Round-6 row, so the file's own tail still reads *"Latest score: 94 (revision 6
  self-score)"* and *"Readiness: NOT READY — round 6 delta review pending"*. I do **not** score this:
  writing the round-N disposition row and refreshing the status lines is the coordinator's closing
  step, which by construction happens after this record is filed — the same reason I left the §13
  quote mismatch unscored in round 6. It should be updated when the cycle closes.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 10a closes REG-1 across all six `SUPPORTED_STATIONS` sites and closes the zero-strategy boot path it would have opened; 10b binds all eight predicates to real artefacts, and §11 now states the compound limit and names the deliverable as a machine-checked refusal, so no section presents the item as a working promotion path. G-07's "promotion is a unit-file commit" half is a human gate by design — a blocker, not a deduction. |
| Technical correctness and evidence grounding | 20 | 20 | The round-6 deduction is discharged: both cross-references are now true of the sections they name, and the new bullet's `:47` citation is exact. Everything else I have verified across rounds 3–6 stands (`score-live-trials-run.sh:40-47,62,115-129,157`; `structural_dead_stop.py:111-132,297-330,347-349`; `fill_time_count.py:101-118`; `family_manifest.py:185,220`; `current_rung_hold_v2.py:184,230,237,269-292,318-336`; `pm_us_crh_v2.json:5` vs `pm_us_crh_v4.json:5`; `docs/core/PROGRESS.md:73`). |
| Implementation specificity and feasibility | 15 | 15 | The `C-KILL` binding is decided to the line — artefact, keys, reader, max-age, identity test, evaluation order, the `evaluable`-before-`structural_dead` rule, and a deployment-generated fixture recipe; 10a is specified to the per-site edit and the call reorder; and §5 now tells an implementer exactly which two upstream changes are not theirs to make. |
| Acceptance criteria and validation quality | 20 | 20 | C1–C19 objective and testable; C17's seven arms are the right seven and none is permissive; C8 is two-way and reachable against deployment; C14/C15/C16/C18/C19 unchanged; the re-gated abandonment rule is decidable from `criteria.json`. |
| Autonomous operation, failure handling, recovery | 15 | 15 | `INERT` is non-permissive by construction and can never be read as a verdict; absent / stale / not-evaluable / wrong-family are four named outcomes with a stated precedence; content-hash idempotency; read-only on both KILL inputs; generator failure surfaces through the host unit, whose stall mode AUD-09's B19 covers. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Zero-ROI honesty; the correctness benefit named as correctness and not counted as return; both strategy-lead blockers kept verbatim; both externally-owned dependencies now excluded in §5, named in §6b.3/§11/§12 with owners, and cited by id only; arming, live enablement, the two reserved caps and the NO-SEND path untouched, with no code in this item reading or proposing a value for them. |
| **Total** | **100** | **100** | |

## Required changes
None. This closes every defect I have raised across rounds 3–6 (10-1 … 10-8).

## Blockers and notes (recorded separately; not scored)
- **Strategy lead — 10b cannot be judged *correct* without a ruling:** R5-7/R5-8 were written for
  `pm_us_crh_fc_v1` under a programme ruled terminally CLOSED; whether they transfer to a
  `continuous_rung_hold` family, and what champion/challenger means at admissible n = 0, is a ruling.
  Correctly transcribed rather than adapted, and tagged `SOURCE=FORECAST_FAMILY_R5`.
- **Strategy lead:** whether a `MECHANISM_ONLY` row may feed any criterion (default taken: no, via
  `C-VALIDITY`).
- **Externally-owned dependency (1):** a deployed wrapper counting the armed family — PROGRESS R-4;
  owner = the live-tally / `score-live-trials` owner. `C-KILL` stays `INERT` until then and the plan
  needs no edit when it lands.
- **Externally-owned dependency (2):** `--family-manifest` on the replay driver; `C-PAIRED` stays
  `INERT` until then. Mirrored in AUD-09 §5/§12.
- **Operator:** arming, live-trading enablement, the two reserved caps — named, untouched.
- **Knowingly-accepted residuals (agreed, unscored):** no alerting independent of the host unit
  (duplicative of AUD-08/AUD-14's mechanism); `C-ESTIMATOR`'s block-bootstrap resample count unstated
  **because** pinning it would adapt R5-7, which the strategy-lead blocker forbids; `C-KILL`'s happy
  path fixture-only while the deployed clock is v2-scoped.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._

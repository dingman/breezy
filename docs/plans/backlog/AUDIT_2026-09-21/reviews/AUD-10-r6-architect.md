# AUD-10 — Review record (Round 6, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: b4b90dc4c3f5a9e0c14f9b5b59d3ffdb0388c20e14d819f60fea2162424d62c9 (coordinator recorded b4b90dc4…)
- Round: 6 (delta) · Reviewer: architect (code-architect lens)
- Total: 99/100 · Readiness: READY (one one-line MINOR outstanding, documentation-only)

## Round-5 dispositions, verified against the plan body

| R5 defect | Claimed | Verified? |
|---|---|---|
| **10-7 (MATERIAL)** — §11 was never revised alongside the `INERT` decision: (1) the `NO_PROPOSAL` reason list omitted `C-KILL` and "C1–C16" was stale; (2) the **conjunction** of the two dependencies was never stated in one place; (3) the abandonment criterion would retire a correct gate for an upstream cause | ACCEPTED IN FULL, all three parts | **FIXED, all three, and §11 is now consistent with the sections I checked it against.** **(1)** The opening paragraph records **both** `INERT`s with the same literal `inert_reason` strings the rest of the plan uses — `NO_CHALLENGER_REPLAY_PATH` (matches C14, §6b.3) and `NO_CHAMPION_SCOPED_KILL_CLOCK` (matches C17(g), §6b.3, §12) — and states the deployed cause with its citation (`score-live-trials-run.sh:47`, which I verified at source in round 5 hard-codes `pm_us_crh_v2.json`). "C1–C16" → **"C1–C19"**, now matching the evidence-artefact line. **(2)** The new COMPOUND-limit paragraph states it once and plainly: each `INERT` bars `PROPOSAL` on its own (C14), the two are independent, so **no run can emit `PROPOSAL` until BOTH externally-owned dependencies land** — the champion-scoped KILL clock (owner: the live-tally / `score-live-trials` owner; **PROGRESS R-4**, `docs/core/PROGRESS.md:73`, whose text I read and which says exactly that the v3 tally must receive its own `--family-manifest` count and that no unit runs it today; **AUD-05 by id only**, with the non-assertion repeated) and `--family-manifest` on the replay driver (owner per §12) — both evaluable *with no change to this plan*, and **"until both land, this item's deliverable is a machine-checked REFUSAL WITH REASONS, not a working promotion path"**. That is the sentence I said was missing, and the closing line ("a standing, self-describing bar — worth having, and honestly less than a promotion path") is the right register. **(3)** The abandonment criterion is **re-gated** to "promotion decisions on which EVERY predicate was evaluable — no `INERT` anywhere in the run", with the override-by-construction reasoning stated. **Soundness and testability, judged as asked:** sound — it now measures the criteria's quality rather than an upstream unit's absence; and testable — `criteria.json` carries every predicate's verdict per row (C15) and `INERT` is a literal verdict (C14), so "no `INERT` in the run" is mechanically decidable from the artefact that accompanies each decision. |
| **c1 (MINOR)** — the "character-identical in AUD-09 §6b.3" claim did not hold for the paragraph | ACCEPTED, first option | **FIXED, and now literally true.** §6b.4's heading is scoped to the bolded property sentence and qualified as *"identical word for word … (compare after whitespace normalisation: the two copies differ only in indentation and line-wrap, normalised sha256 ce5b6d1d…a26263)"*, with the lead-in and closing expressly excluded. I re-compared the two sentences token by token (AUD-10 `:546-550` vs AUD-09 `:558-561`): word-for-word identical; the only differences are this copy's bullet indent and wrap points. **The property sentence is unchanged**, so C19 and AUD-09's B18 still assert the same invariant. |

## "Nothing else moved" — checked

I re-read §4, §5, §6b.3's `C-KILL` binding table and *Whose KILL clock is it?*, §6b.4, §9, §10, §12
and C8/C14/C17/C19, and all are byte-consistent with what I verified in round 5; the only changes are
§11 and the one §6b.4 heading line. §13's Round-5 entry states my findings accurately (including that
my verdict was "honest everywhere **but** §11"), records the declined alternative with a reason, and
holds the **Revision 6 self-score at 94, deliberately unchanged** — correctly argued: 10-7 and c1 were
accuracy defects in the plan's own prose, and closing them does not move the author's own residuals.

## Defects found in revision 6

**10-8 (MINOR, NEW) — two cross-references in the newly written §11 point at sections that do not
carry what the sentence claims.** Both are in prose a reader acts on, and both are one clause:
1. *"Both `INERT`s are the expected steady state recorded in **C8**, tested by **C17(g)**, and named
   with owners in §12."* C8 records both ✓ and §12 names both with owners ✓, but **C17(g) tests only
   the `C-KILL` inert**. `C-PAIRED`'s `INERT` is tested by **C14** (which pins the literal verdict,
   the `inert_reason` and the `PROPOSAL` bar) plus C7 and §7 step 10. A reader who checks C17(g) to
   confirm "both are tested" finds one, and may conclude the other is unpinned when it is not.
2. *"Both are out of this item's scope (§5)."* §5 excludes dependency (2) explicitly — *"Any change
   to `current_rung_hold_paper_replay.py`, including the `--family-manifest` flag `C-PAIRED` would
   need"* (`:135-136`) — but carries **no bullet for dependency (1)**: standing up a champion-scoped
   KILL clock, i.e. any change to `deploy/systemd/score-live-trials-run.sh` or a new counter
   invocation. That exclusion lives only in §6b.3 and §12. So §5, the list an implementer reads to
   learn what not to touch, is incomplete on the very dependency that makes the plan's central
   predicate inert.
REQUIRED: (a) attribute the tests correctly — e.g. *"…recorded in C8, barred by C14, and tested by
C14 (`C-PAIRED`) and C17(g) (`C-KILL`)"*; and (b) add one §5 exclusion bullet — *"Standing up a
champion-scoped KILL clock: no change to `deploy/systemd/score-live-trials-run.sh` or its hard-coded
`FAMILY_MANIFEST` (`:47`), and no second counter invocation. Named as a dependency (§6b.3, §11, §12),
not taken here."* — which also makes §11's "(§5)" true. Fixing (b) is the better of the two orders,
because it completes §5 rather than weakening §11's claim.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | The round-5 deduction is discharged: §11 now states the compound limit and names the deliverable as a machine-checked refusal, so no section presents the item as a working promotion path. 10a closes REG-1 across all six sites and the zero-strategy boot path. G-07's "promotion is a unit-file commit" half is a human gate by design — a blocker, not a deduction. |
| Technical correctness and evidence grounding | 20 | 19 | Every substantive citation in the new §11 checks out (the `inert_reason` strings, `score-live-trials-run.sh:47`, PROGRESS R-4 at `docs/core/PROGRESS.md:73`, AUD-05 by id only, the C14 bar). −1 for 10-8: two cross-references that do not support the claim as worded. |
| Implementation specificity and feasibility | 15 | 15 | The `C-KILL` binding is decided to the line — artefact, keys, reader, max-age, champion-scope identity test, evaluation **order**, the `evaluable`-before-`structural_dead` rule, and a fixture recipe generated from the shipped script. |
| Acceptance criteria and validation quality | 20 | 20 | C1–C19 objective; C17's seven arms are the right seven and none is permissive; C8 is two-way and reachable against deployment; C14/C15/C16/C18/C19 unchanged and sound; and the re-gated abandonment rule is decidable from `criteria.json`. |
| Autonomous operation, failure handling, recovery | 15 | 15 | `INERT` is non-permissive by construction and cannot be reached as a verdict; absent / stale / not-evaluable / wrong-family are four named outcomes with a stated precedence; content-hash idempotency; read-only on both KILL inputs; generator failure surfaces through the host unit, whose stall mode AUD-09's B19 now covers. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | The round-5 deduction is discharged: the abandonment criterion no longer retires a correct gate for an upstream cause, and the reasoning for the re-gating is stated. Zero-ROI honesty; correctness named as correctness; both strategy-lead blockers verbatim; dependencies owned and cited by id only; arming, the two reserved caps and NO-SEND untouched. |
| **Total** | **100** | **99** | |

## Required changes to reach 100
1. §11: attribute `C-PAIRED`'s `INERT` test to C14 (C17(g) covers `C-KILL` only), and add the §5
   exclusion bullet for standing up a champion-scoped KILL clock so "(§5)" is true (10-8).

## Blockers and notes (recorded separately; not scored)
- **Externally-owned dependency (no plan change resolves it):** a deployed wrapper counting the armed
  family — PROGRESS R-4; owner = the live-tally / `score-live-trials` owner. `C-KILL` is `INERT`
  until then and the plan needs no edit when it lands.
- **Deferred change with a named owner:** `--family-manifest` on the replay driver; `C-PAIRED` is
  `INERT` until then. Mirrored in AUD-09 §12.
- **Strategy lead:** whether R5-7/R5-8 transfer to a `continuous_rung_hold` family (the criteria are
  transcribed, not adapted, and tagged `SOURCE=FORECAST_FAMILY_R5`); and whether a `MECHANISM_ONLY`
  row may feed any criterion (default: no).
- **Operator:** arming, live enablement, the two reserved caps — named, untouched, no value proposed.
- **Author-identified residuals I considered and do not score.** `C-ESTIMATOR`'s block-bootstrap
  resample count is unstated **because** pinning it would adapt R5-7, which the strategy-lead blocker
  forbids — blocker-scoped, correctly left alone. `KILL_CLOCK_MAX_AGE_SECONDS`'s home module is named
  by behaviour rather than by file; I read that section in rounds 4 and 5 and scored specificity full
  both times, the home (`promotion_criteria.py`, the pure core that evaluates the predicate) is
  unambiguous, and raising it now as a new deduction would be late deflation rather than a finding.
- **Note (optional, unscored):** §13's round-5 row quotes the new §6b.4 heading as
  "character-identical", the intermediate wording, while the live text says "identical word for word
  … after whitespace normalisation". §13 is a dated historical record no implementer acts on; quote
  the final wording if the record is to be perfectly self-consistent.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._

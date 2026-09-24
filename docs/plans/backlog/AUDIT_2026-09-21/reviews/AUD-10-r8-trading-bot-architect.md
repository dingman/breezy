# AUD-10 — Review record (Round 8, ruling-driven revision, delta)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 28f740577f72ff8c1d92b53a7fb7215c2f687c6dd2fb552c349a1023d65e0a64
- Round: 8 · Reviewer: trading-bot-architect (promotion-gate/risk-architecture lens)
- Total: 94/100 (readiness/self-score text ignored per instruction)

## Scope of this round

Applies `RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` (Revision 2, Q2/Q3/
Q4) plus two related endorsed rulings cited by path: `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
and `RULING_live_family_tally_scope_2026-09-21.md`. I read all three rulings and checked every plan
claim against them and against source.

## Q3 (R5-7/R5-8 adaptation) and Q2 (MECHANISM_ONLY) — faithfully applied

The adapted R5-7/R5-8 text in §6b.3 is quoted verbatim against the ruling (`fit_date`→`d0_climate_day`,
the unchanged shared estimator/bootstrap, R5-8's champion=`sending_family_id` framing) — I compared
both blocks word-for-word and found no drift. The line-citation correction (ruling's `:213-222` →
plan's `:214-224`) is itself accurate: I re-read `roi_bound.py` and confirmed `result = bootstrap(` at
`:214`, `n_resamples=B_RESAMPLES` at `:219`, `random_state=np.random.default_rng(SEED)` at `:220`,
`method="BCa"` at `:223`, closing at `:224`; `B_RESAMPLES` (`:93`) and `SEED` (`:97`) also confirmed.
New **C20** correctly RED-tests the parameter-exactness and the tag. Q2's permanent §9 exclusion and
conditional promotion-criteria exclusion are both restated correctly and match the ruling's items 1–3.

## Q4 (ownership) — faithfully applied, consistently, everywhere

`C-KILL`'s dependency → **AUD-05 exclusively**; `C-PAIRED`'s → **AUD-19**, gated on the `trial_id` fix.
I grepped every occurrence of "owned by AUD-19"/"owned by AUD-05"/"Owner: AUD-19"/"Owner: AUD-05" in
the file: seven sites (§4, §5 ×2, §6b.3 ×2, §11, §12 ×2) all agree, all cited by id only, none asserts
content about AUD-05/AUD-19 beyond what the ruling states.

## PROVISIONAL / "reads as settled authority" — the specific check requested, and a real gap found

The tagging rule (§6b.3) is correct as far as it goes: every adapted-R5 predicate's `criteria.json` row
carries `STATUS=PROVISIONAL...`, and `RATIONALE.md` states PROVISIONAL on **both** `PROPOSAL` and
`NO_PROPOSAL` verdicts — so a settled-looking bare `PROPOSAL` cannot occur *while the plan's own rule is
followed*. But the **lifting condition itself is ambiguous on the one run that matters most**: "PROVISIONAL
lifts automatically the first time a run completes with every predicate evaluable... regardless of that
run's verdict." This does not state whether **that same triggering run's own artefact** is still tagged
PROVISIONAL, or already reads as lifted. If the latter, the first-ever run in which every predicate
happens to be evaluable — which could itself be a `PROPOSAL` — would emit as already-settled despite the
adapted criteria never having been exercised in any *prior* run, which is exactly the risk the tagging
rule exists to prevent. **C20**'s test only asserts the tag is "not dropped while any predicate in the
run is `INERT`" — it does not test the boundary case (the first no-`INERT` run tagging itself). This is
a genuine specification gap, not a hypothetical one: today both `C-KILL` and `C-PAIRED` are `INERT`, so
the first run in which they are not is, by construction, also the run that could legitimately be a
`PROPOSAL`.
REQUIRED: state explicitly that PROVISIONAL is a property of **accumulated history** — "has any run
*prior to this one* completed with no `INERT` anywhere" — never of the current run's own outcome, so the
triggering run is itself still tagged PROVISIONAL and only *subsequent* runs read as lifted; and extend
C20 (or add a new criterion) with a fixture where every predicate is true on the very first exercised
run, asserting that run's own `criteria.json`/`RATIONALE.md` still carries the tag.

## §9's new "halted champion" bullet — one overclaimed reason, conclusion unaffected

The new bullet correctly cites `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` and states the
generator's output is unchanged (`NO_PROPOSAL`) "for reasons that do not depend on the halt." But
reason (i) — *"A halted champion accrues no new live fills, so admissible n cannot grow"* — **does**
depend on the halt being enforced, and the cited ruling's own status line says the opposite: *"UNENFORCED
until AUD-02b lands and the halt is set"*, and its §4 states in the present tense, *"nothing in the repo
prevents `pm_us_crh_v4` from placing an order the moment pricing legalizes... Writing this ruling does
not, by itself, stop the family."* So (i) overclaims a guarantee the plan's own cited source explicitly
disclaims today. The overall conclusion survives regardless — (ii) `C-VALIDITY` and (iii) both `INERT`
predicates under `C14` are genuinely halt-independent and each alone is sufficient — so this does not
change any test, criterion, or design decision; it is a factual accuracy defect in the rationale text.
REQUIRED: reword (i) to state the true, halt-independent reason n stays flat today (the accidental
zero-decisions-reach-pricing state, per `RULING_A1` §3.1, and the pre-existing fee-refusal barrier), or
drop (i) and rely on (ii)/(iii) alone, which the text's own framing ("reasons that do not depend on the
halt") already shows are sufficient.

## No regression — 10a, C15, C18, C19, C10==B10, and the mirrored property sentence

10a's six-site disposition table, the `:319` guard-domain narrowing, C15's seven-refusal-shape base-
class catch with `__bases__` pinned, and C18's boot-log pin are all unchanged (the diff does not touch
these regions; I re-read them in full to confirm). **C19** is byte-identical to what was verified in
round 7. The "bolded property sentence... identical word for word in AUD-09 §6b.3" paragraph is
unchanged from round 7 (same normalised-hash citation, `ce5b6d1d…a26263`); AUD-09's own file was
re-reviewed this session at round 7 and its mirror of the same sentence is unaffected by AUD-09's own
round-7 edits (which touched only unrelated sections). No regression found anywhere else in the file.

## Defects

1. **MATERIAL** — the PROVISIONAL-lifting condition does not specify whether the triggering (first
   no-`INERT`) run's own artefact is itself still tagged PROVISIONAL, creating a path for a `PROPOSAL`
   to read as settled authority on its very first exercise. Required change above; C20 needs a new
   fixture.
2. **MINOR** — §9's new halted-champion bullet, reason (i), overclaims the halt's current enforcement
   against its own cited ruling's explicit "UNENFORCED" status. Required change above; text-only, no
   test or design impact.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Every ruling-mandated text change applied faithfully; the PROVISIONAL boundary-case gap is a real, if narrow, incompleteness against the tagging rule's own stated purpose. |
| Technical correctness and evidence grounding | 20 | 18 | Every citation I re-checked (roi_bound.py line ranges, ownership text, adapted R5-7/R5-8 quotation) is exact. −2 for the halt-enforcement overclaim (defect 2), which contradicts its own cited source. |
| Implementation specificity and feasibility | 15 | 14 | Ownership, tagging, and the adapted criteria are all decided to the field. −1: the lifting condition leaves the triggering run's own tag status to the implementer to infer (defect 1). |
| Acceptance criteria and validation quality | 20 | 18 | C20 is real and tests the parameter-exactness and the non-INERT-dropping case. −2: it does not test the specific boundary case that matters most for "never reads as settled" (defect 1). |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged; both `INERT` predicates remain non-permissive by construction, `C14` unchanged, both ownership dependencies correctly recorded as non-blocking to the build. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Both strategy-lead blockers are now RULED; the halted-champion consequence is correctly recorded as not reopening any exclusion; no operator-cap or enablement content introduced. |
| **Total** | **100** | **94** | |

## Required changes to reach 100

1. State that PROVISIONAL is a property of runs *prior to* the current one, never of the current run's
   own outcome; extend C20 with a first-no-`INERT`-run fixture (defect 1).
2. Reword or drop §9's reason (i) so it does not overclaim the halt's current enforcement (defect 2).

## Blockers (recorded, not scored)

- **Externally owned, by id:** AUD-05 (champion-scoped KILL clock), AUD-19 (`--family-manifest`,
  itself gated on AUD-09's Q1 `trial_id` fix).
- **Operator:** arming, live enablement, the two reserved caps — untouched, no value proposed.
- **Unenforced today, per `RULING_A1`:** the champion's "may not SEND orders" disposition has no
  live code enforcement until AUD-02b's `breezy-set-family-halt` CLI lands and is run — this does not
  change AUD-10's own conclusions (see defect 2) but is a real, external gap this item does not own.

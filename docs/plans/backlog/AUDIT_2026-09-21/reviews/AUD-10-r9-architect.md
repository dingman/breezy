# AUD-10 — Review record (Round 9, delta)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: a980ce3214ea2731b799e80373d69d7dcbfa01aea982b836dc69e2732ac63f0e (coordinator recorded a980ce32…)
- Round: 9 · Reviewer: architect (code-architect lens)
- Total: 99/100 · Readiness: READY on plan quality (one one-line MINOR)

## Round-8 disposition (mine), verified in place

| R8 defect | Claimed | Verified? |
|---|---|---|
| **10-9 (MINOR)** — R-4 cited bare, so a reader following the plan's own authority reaches `PROGRESS.md:73`'s literal `--family-manifest pm_us_crh_cont.json` instruction, which would scope the counter to a **retired** family — the wrong-family trap the ruling exists to close | FIXED | **CONFIRMED in both mandated places.** §6b.3's R-4 quotation and §12's KILL-clock bullet now each carry: *"R-4's literal `pm_us_crh_cont.json` naming is **SUPERSEDED** … `pm_us_crh_cont` is retired, `terminal_climate_day: "2026-09-19"`: the count must follow `sending_family_id` **dynamically**, never a manifest filename baked into spec text."* Both facts check out — I read `PROGRESS.md:73` (it does name `pm_us_crh_cont.json` verbatim) and `deploy/families/pm_us_crh_cont.json:5` (`terminal_climate_day: "2026-09-19"`) in earlier rounds. Ownership text (AUD-05 exclusively, by id only) is unchanged, as required. |

## The two edits from the other reviewer, verified against the rulings

**(1) "The generator never lifts the tag itself."** Verified at source. The ruling
(`RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md:405-412`) reads: *"PROVISIONAL
lifts **automatically** the first time a promotion-proposal run completes with every predicate
evaluable — no `INERT` anywhere in the run … regardless of that run's verdict … **Until lifted**,
`PROPOSAL` and `NO_PROPOSAL` verdicts alike **must carry** the `PROVISIONAL` tag in the human-readable
`RATIONALE.md`."*

**Direct answer to the question put to me: this refines the ruling conservatively; it does not
contradict it — with one recording gap (10-10).** The reasoning, stated so the coordinator can check
it rather than take it:
- The ruling's **binding output requirement** is at `:410-412`: while un-lifted, every verdict must
  carry the tag. The plan's rule keeps the tag on **strictly more** artefacts (`criteria.json`,
  `RATIONALE.md` *and* any `PROPOSAL`, versus the ruling's `RATIONALE.md`) for **strictly longer**
  (until a separate ruling exists). **It can never drop the tag earlier than the ruling permits**, so
  it cannot violate `:410-412` in any run.
- What it narrows is the *transition*, not the requirement: the ruling's word is "automatically", and
  the plan makes the lift require a separate `docs/evidence/` ruling read by pinned path + sha256.
  That is strictly less permissive, and in the safe direction for a promotion gate.
- The substantive argument is correct and is the same one I would make: a run cannot certify that its
  own criteria were end-to-end exercised **on the strength of its own outcome**. Under the literal
  reading, the very first no-`INERT` run's `PROPOSAL` would be the first artefact ever emitted
  untagged — i.e. the first-ever proposal produced by never-exercised criteria would read as settled
  authority. The plan forecloses exactly that, and keeps the triggering run's own artefact tagged.
- The failure handling is right and testable: absent / unreadable / sha256-mismatched ruling artefact
  ⇒ `criteria_status: "PROVISIONAL"`, **never a silent lift and never a crash** — the same fail-closed
  posture `C-KILL` already uses, and the sha256 pin makes a hand-edited "lifting ruling" ineffective.
- It does not disturb anything upstream: `C14` is explicitly unchanged, a PROVISIONAL `PROPOSAL` is
  declared **advisory input to the human unit-file promotion commit** (consistent with §11 and with §5's
  arming exclusion), and the no-`INERT` gate remains the same gate §11's abandonment criterion uses.
- **C20 is extended in place, no renumbering**, with three REDs that pin exactly the boundary:
  (a) first no-`INERT` run still emits `PROVISIONAL` in its own three artefacts; (b) lift only on
  present **and** sha256-matching pinned artefact; (c) missing/unreadable/tampered ⇒ PROVISIONAL.
  These are objective and fixture-constructible today. My round-8 judgement that the ruling's
  "add the lifting condition to the `criteria.json` schema description" was satisfied in substance
  still holds — and is now strengthened, because the status is a first-class field
  (`criteria_status`) rather than only prose.

**(2) §9's halt correction.** Verified verbatim against `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`:
`:3` is *"UNENFORCED until AUD-02b lands and the halt is set"* ✓, and `:273-278` reads *"this ruling is
UNENFORCED until the missing SET path lands and is actually run. Today, nothing in the repo prevents
`pm_us_crh_v4` from placing an order the moment pricing legalizes — the zero-take state remains the same
accidental by-product of Gate 1/Gate 2 described in §5, not a designed control. Writing this ruling does
not, by itself, stop the family."* ✓ The previous text ("a halted champion accrues no new live fills")
**did** assume enforcement, so this is a real correction, not a cosmetic one. Reason (i) is now
re-grounded on the enforcement-independent fact and, importantly, the bullet adds that (i), (ii) and
(iii) are **each independently sufficient** — which is what makes the conclusion durable: (i) rests on
an *accidental* by-product the ruling itself says could lapse "the moment pricing legalizes", but
(ii) `C-VALIDITY` and (iii) both `INERT`s under `C14` survive that lapse. Good argument hygiene: the
fragile ground is labelled as fragile and the conclusion does not rest on it.

## Regression / scope check

- **§6b.4's property sentence and C19's three-script set are untouched** — neither falls inside any of
  the six diff hunks (which land at ~§6b.3's tagging paragraph, §6b.3's R-4 quotation, the C20 row,
  §9's halt bullet, §12's KILL bullet, and §13). The AUD-09 B18 mirror and the normalised-hash anchor
  therefore still hold.
- **C1–C20 consistent**: C20 extended in place, no renumbering; §8's evidence artefact ("C1–C20") and
  §11's "How it will be evaluated" ("C1–C20") are context lines, unchanged and still correct; §7 step
  10/12 continue to reference C20 as the home of the tagging REDs.
- `C-KILL`/`C-PAIRED` remain `INERT` with their `inert_reason`s; `C14`, C15, C17's seven arms, C18 and
  the `C-KILL` binding table are all unchanged; 10a is untouched.

## Defects found in revision 9

**10-10 (MINOR, NEW) — the plan is deliberately stricter than a ruled instruction and does not record
the departure, so the authority trail cannot be audited.** §6b.3 characterises the ruling's condition as
*"necessary, but … not self-certifying"* — a fair characterisation of the *logic* — but the ruling's
actual words at `:405-406` are *"PROVISIONAL lifts **automatically** the first time a run completes
with every predicate evaluable"*, and the plan replaces that automatic transition with a separate,
sha256-pinned ruling artefact. A reader diffing plan against ruling finds a discrepancy with no recorded
rationale for the departure, and cannot tell whether it is a considered refinement (it is) or drift.
Every other place this plan departs from a source — the withdrawn `:152-160` "mirror", the R-4
supersession, the ruling's `:213-222` bootstrap range — says so explicitly; this one does not.
REQUIRED: one clause in §6b.3, e.g. *"The ruling's word is **automatically** (`:405-406`); this plan is
deliberately **stricter**, because a run may not self-certify. The stricter rule only ever keeps the tag
on longer and never drops it earlier, so it cannot conflict with the ruling's binding requirement that
every un-lifted verdict carry the tag (`:410-412`)."*

**Non-scoring observation (not a defect).** The supersession clause cites *"RULING Q4 item 3,
`:483-491`"*. Lines `:483-491` are Q4's **Evidence** reconciliation bullet, which states the proposition
verbatim (*"R-4's literal text … is SUPERSEDED, not authoritative as written"*) — so the cited range
**does** support the claim; the numbered "item 3" itself lives at `:557-561` and says the same. Unlike
round 6's `C17(g)` case, nothing here points at text that fails to support the claim, so I do not score
it; tighten the label to ":483-491 (evidence) / :557-561 (RULING item 3)" if you want it exact.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Every ruled obligation remains applied, and the two new edits close a real specification gap (who may lift the tag) and a real overclaim (an unenforced halt read as a control) without touching design, scope or 10a. Being stricter than the ruling on a safety property is the correct direction for a promotion gate. |
| Technical correctness and evidence grounding | 20 | 19 | Everything I re-checked is exact: the ruling's lifting text `:405-412`, `RULING_A1:3` and `:273-278` quoted verbatim and used correctly, R-4's superseded literal with the retired-family evidence, and the earlier-verified `roi_bound.py:93,97,214-224`. −1 for the unrecorded departure from the ruling's "automatically" (10-10). |
| Implementation specificity and feasibility | 15 | 15 | `criteria_status` is a named field with a stated default, the lift has a named mechanism (pinned path + sha256), and the three failure modes are enumerated with their outcome. Nothing is left for the implementer to decide. |
| Acceptance criteria and validation quality | 20 | 20 | C20's three new REDs pin the exact boundary that was unspecified, including the adversarial case (tampered artefact) and the self-certification case (first no-`INERT` run). All three are constructible as fixtures today, unlike the criteria they guard. C1–C19 unchanged and consistent. |
| Autonomous operation, failure handling, recovery | 15 | 15 | The lift is fail-closed in all three failure modes and cannot crash the nightly run; §9's halt bullet now rests on three independently-sufficient grounds rather than on one enforcement assumption; `INERT` remains non-permissive with a stated evaluation order. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | A PROVISIONAL `PROPOSAL` is explicitly advisory to the human promotion commit, never auto-promotion; arming, the two reserved caps and NO-SEND untouched; AUD-05/AUD-19/AUD-02b all cited by id only with no schedule dependency; no ROI claimed for text-accuracy work. |
| **Total** | **100** | **99** | |

## Required changes to reach 100
1. §6b.3: record the deliberate departure from the ruling's "lifts automatically", with the
   one-line justification that the stricter rule can only ever keep the tag on longer (10-10).

## Blockers and dependencies (recorded separately; not scored)
- **AUD-05** (by id): champion-scoped KILL clock — `C-KILL` `INERT` until it lands.
- **AUD-19** (by id), gated on the replay-`trial_id` fix: `--family-manifest` — `C-PAIRED` `INERT`.
- **A future lifting ruling** under `docs/evidence/`: required before the criteria read as unqualified;
  unreachable until the two above land and a no-`INERT` run exists. Correctly stated as a dependency,
  not as work this item performs.
- **AUD-02b** (by id, via `RULING_A1`): the champion's halt is RULED but **UNENFORCED** until the SET
  path lands. Correctly recorded, and the plan's conclusion does not depend on it.
- **Operator:** arming, live enablement, the two reserved caps — named, untouched, no value proposed.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._

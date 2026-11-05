# AUD-10 — Review record (Round 8, ruling-intake delta)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 28f740577f72ff8c1d92b53a7fb7215c2f687c6dd2fb552c349a1023d65e0a64 (coordinator recorded 28f74057…)
- Round: 8 · Reviewer: architect (code-architect lens)
- Total: 99/100 · Readiness: READY on plan quality (one one-line MINOR)

## Ruling application, checked against the ruling's own "Consequences — AUD-10"

| Ruling obligation | Applied? |
|---|---|
| §6b.3: replace the `SOURCE=FORECAST_FAMILY_R5` transcription with the **adapted** R5-7/R5-8 text, tagged PROVISIONAL, plus the lifting condition (Q3) | **YES, and pinned as block quotes rather than paraphrased.** `fit_date` → `d0_climate_day` with the reason carried (`continuous_rung_hold` manifests have no `fit_date`; `pm_us_crh_v4.json:9`'s `density_artefact_path` is `not_applicable_density.json`; `:5` d0 = `2026-09-20`). Estimator/bootstrap stated as **existing shared code, unmodified**. The `STATUS=PROVISIONAL, SOURCE=FORECAST_FAMILY_R5, ADAPTED_BY=RULING_…2026-09-21` tag is mandated in every adapted predicate's `criteria.json` row **and** in `RATIONALE.md` on *both* verdicts. The lifting condition is stated exactly as the ruling gives it — first run with **no `INERT` anywhere**, regardless of verdict — and, importantly, the plan states that a run blocked by an `INERT` does **not** lift it, and that the condition is unreachable until AUD-05's and AUD-19's artefacts exist. Champion/challenger at n = 0 is recorded with the right consequence (`C-N`/`C-PAIRED` speak first; R5-7 never runs on an empty champion; C14 unchanged). Every predicate's `source` column is re-tagged "**adapted, PROVISIONAL**", and the `C-PAIRED` row and the `CombinedDraw` bookkeeping paragraph both switch `fit_date` → `d0_climate_day` — no stale occurrence left behind. |
| §12 R5-7/R5-8 blocker → RULED (Q3) | **YES**, with the honest closing line that what remains "is not authorial". |
| §12 `C-PAIRED` bullet → Owner AUD-19, gated on the Q1 fix | **YES**, by id only, with "round 8 named the owner, it did not produce the artefact" — the right register. |
| §12 KILL-clock bullet → Owner AUD-05 exclusively (Q4) | **YES on ownership; one mandated clause missing — see 10-9.** |
| §11 COMPOUND paragraph → both owner clauses updated | **YES**, both, by id only, with the "no change to this plan when they land" property preserved. |
| Q2 → `C-VALIDITY` confirmed unmodified, §9-bar recorded | **YES**, in both §6b.3 and §12, including the permanence and the "reversible only by a separate ruling" clause. `C-VALIDITY`'s text is untouched, which is what "confirmed unmodified" requires. |

**The resample residual is genuinely closed, and the reviser's correction of the RULING is right.** I
re-read `src/breezy/settlement/roi_bound.py` myself: `B_RESAMPLES: Final[int] = 10_000` at **`:93`**,
`SEED: Final[int] = 20260904` at **`:97`**, `result = bootstrap(` at **`:214`**, `n_resamples=B_RESAMPLES`
`:219`, `random_state=np.random.default_rng(SEED)` `:220`, `method="BCa"` `:223` — so the call is
**`:214-224`**, and the ruling's `:213-222` is off by one at both ends. The plan corrects it explicitly,
says only the range moves and the substance does not, and pins the parameters to the shipped call via
**C20** plus a §7 step 10 RED clause ("defines no local resample count or seed"). That closes the
`C-ESTIMATOR` residual carried since revision 4 — correctly, by *pinning to shipped code* rather than by
inventing a number, which is exactly why I never scored it as a defect.

**No regression.** §6b.4's property sentence and **C19**'s three-script set do not appear in the diff —
byte-unchanged, so AUD-09 B18's mirror and the normalised-hash anchor still hold. `C-KILL` and `C-PAIRED`
remain `INERT` with their `inert_reason`s; **C14** is untouched and still bars `PROPOSAL`; C17's seven
arms, C15's seven refusal shapes, C18 and the `C-KILL` binding table are unchanged. Numbering is
consistent: C20 is additive, the evidence artefact moves to **C1–C20**, and §11's "How it will be
evaluated" moves to **C1–C20** — both places I flagged as staleness risks in round 5 are correct this
time. §9's new halted-champion bullet is sound and, correctly, argues the output is unchanged **for
reasons independent of the halt** (n = 0 at `C-N`; `C-VALIDITY`; both `INERT`s under C14); both rulings
it cites exist on disk (`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`,
`RULING_live_family_tally_scope_2026-09-21.md`) and it asserts nothing further about the tally store.

## Defects found in revision 8

**10-9 (MINOR, NEW) — the R-4 pointer is left stale: the ruling's mandated supersession clause is not
carried, so a reader following the plan's own citation reaches instruction that would reproduce the
wrong-family error.** The ruling's Consequences for AUD-10 §12 require the KILL-clock bullet to read
"Owner: AUD-05 exclusively … **reconciling R-4's stale literal `pm_us_crh_cont.json` text with the
retired-family hand-down by resolving the champion dynamically from `sending_family_id`**". The plan
applies the ownership half but keeps the R-4 citation bare: §12 still reads "*The repo already tracks
that question as **PROGRESS R-4** (`docs/core/PROGRESS.md:73`)*" and §6b.3 quotes R-4's text, with **no
mention that it is SUPERSEDED**. I read `PROGRESS.md:73`: it names `--family-manifest pm_us_crh_cont.json`
verbatim — a **retired** family (`terminal_climate_day: "2026-09-19"`). So an implementer who follows the
plan's pointer to its authority is told to scope the counter to the retired family, which the ruling
itself calls out as re-creating "the identical wrong-family error this whole backlog exists to close".
The plan carries the citation's authority without its correction.
REQUIRED: one clause in §12's KILL-clock bullet (and ideally in §6b.3's quotation of R-4) — *"R-4's
literal `pm_us_crh_cont.json` naming is **SUPERSEDED** (RULING Q4 item 3): the count must follow
`sending_family_id` dynamically, never a manifest filename baked into the spec text."*

Also checked and **not** a defect: the ruling's "add the PROVISIONAL lifting condition to the
`criteria.json` schema description" is satisfied in substance — the tag is mandated per-row in
`criteria.json`, the status is mandated in `RATIONALE.md` on both verdicts, and C20 tests both plus the
"tag not dropped while any predicate is `INERT`" property.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Every mandated consequence is applied and nothing is over-applied: the criteria are now *adapted and pinned* rather than transcribed, the two owners are named by id, and the plan is explicit that naming an owner produced no artefact — `C-KILL`/`C-PAIRED` stay `INERT` and `PROPOSAL` stays unreachable. 10a is untouched and remains buildable. |
| Technical correctness and evidence grounding | 20 | 19 | The adapted text matches the ruling; `d0_climate_day` propagated everywhere `fit_date` appeared; `combine_station_day:298` and `roi_bound.py:93,97,214-224` all verified by me at source, including the reviser's ±1 correction of the ruling, which is right. −1: R-4's superseded literal is cited without the supersession (10-9). |
| Implementation specificity and feasibility | 15 | 15 | The bootstrap is now pinned to the shipped call with constants and line numbers, the tag string is literal, the lifting condition is mechanical, and the `C-KILL` binding remains decided to the line. Nothing material is left to the implementer. |
| Acceptance criteria and validation quality | 20 | 20 | C20 is objective and tests three distinct properties (pairing field, bootstrap parameterisation, tag presence **and** non-dropping while `INERT`); C1–C19 unchanged and consistent; both enumerations (§8 artefact, §11 evaluation) correctly updated to C1–C20; §7 step 10 carries the matching RED clause. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged and still complete; the halted-champion case is added as a reasoned `NO_PROPOSAL` with three independent grounds, and it explicitly refuses to read a halt as a reason to promote around the champion. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | AUD-05/AUD-19 cited strictly by id with no schedule dependency; PROVISIONAL status is surfaced to the human reader on both verdicts rather than buried; arming, the two reserved caps and NO-SEND untouched; no ROI claimed for a ruling that removed a cap rather than a defect. |
| **Total** | **100** | **99** | |

## Required changes to reach 100
1. Add the R-4 supersession clause to §12's KILL-clock bullet (and §6b.3's R-4 quotation) (10-9).

## Blockers and dependencies (recorded separately; not scored)
- **AUD-05** (by id): champion-scoped KILL clock. `C-KILL` stays `INERT` until it lands; no change to
  this plan when it does.
- **AUD-19** (by id), gated on the replay-`trial_id` fix: `--family-manifest`. `C-PAIRED` stays `INERT`.
- **Consequence, stated in-plan and correct:** with both `INERT`, no run can emit `PROPOSAL`, and the
  adapted R5 criteria stay **PROVISIONAL** because the lifting condition (no `INERT` anywhere) is
  unreachable until those two artefacts exist. That is a dependency, not a deduction — and the plan says
  so in §6b.3, §11 and §12 rather than implying a working promotion path.
- **Operator:** arming, live enablement, the two reserved caps — named, untouched, no value proposed.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._

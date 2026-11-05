# AUD-05 review — round 4 (FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-05-live-family-tally-unit.md
sha256: 9aeef125f525e1a78b7b464db3c50035f19245642215fe6143738c54981963ca
Round: 4

## Claims verified (unchanged from the initial round-4 pass)

- `any_cell_dead` (`scripts/analysis/family_tally_v2.py:655`) is passed as `cell_dead=` into
  `terminal_look` (`:728`, `:792`) and `look_verdict` (`:753`); `look_verdict`
  (`src/breezy/settlement/current_rung_hold_v2.py:440-465`) implements `KILL <=> S <= b_fut OR
  cell_dead OR structural_fired`; the result reaches `FamilyTallyV2.verdict` (`:822`) — CONFIRMED.
  Round 3's "non-gating, report-diagnostic only" framing is REFUTED; only `_fmt_stratum_row`'s `:831`
  is report-only.
- `E[held_i] = BE_i` on both sides, independently re-derived against
  `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §3/§7 — CONFIRMED correct.
- AC#11/#12 correctly test the withholding behaviour (no fabricated `cell_dead=False`, no published
  verdict on an unruled basis) — CONFIRMED.
- Exit-0 design is sound because the withheld verdict is made visible via an explicit WARN alert
  (`FAMILY_TALLY_STRATA_RULING_PENDING`) independent of the exit code, not via systemd's `OnFailure`
  path — CONFIRMED consistent with D-F's own stated design ("a systemd `failed` unit state remains the
  secondary signal, never the only one").

## Reconciliation

**Fidelity to the gap and completeness — withheld 3/20 originally.** The sole reason given ("the
§7-frozen strata element is now surfaced as BLOCKER-3... R-4 stays deferred to BLOCKER-2") names two
open operator/strategy-lead rulings. Per the reconciliation rule, a shortfall no plan-text change could
fix — an operator/PREREG ruling this plan correctly may not make unilaterally — is a BLOCKER, not a
deduction. The plan does everything available to it short of the ruling: ships the provably inert half,
files the frozen half as an explicit blocker with a recommended, source-derived disposition, and keeps
the unit running safely in the meantime.
**Disposition: AWARD in full.** **Blockers recorded below (BLOCKER-2, BLOCKER-3), not deducted.**
→ **20/20**

**Technical correctness and evidence grounding — withheld 3/20 originally.** One named reason ("that
[E[held_i]=BE_i] identity is still a derivation from field semantics, not a registered formula... the
premise BLOCKER-3's recommendation rests on") is again BLOCKER-3-external — no plan text can make a
derivation "registered" without the ruling; awarded.
**A second, genuine defect found on this re-reading, not previously named:** §6's rejection of
side-partitioning states the `mean_ask` homogeneity concern is "handled by labelling the rendered
column, not by repartitioning a registered stratum" (line 207) — but this claim is never made concrete
anywhere else in the plan. No AC, no §7 step, and no named test specifies what the label actually says,
where it is rendered, or that a mixed-side `mean_ask` is distinguishable from a homogeneous one in the
output a human or a downstream reader consumes. This is a load-bearing claim (it is the stated
justification for withdrawing the side-partition) with no corresponding specification — exactly the
"prose promises a control; nothing in §7/§8 builds or tests it" pattern this backlog's own discipline
(D7's schema-version refusal, the shared alert ladder) otherwise closes with a named mechanism.
**Disposition: keep 1 point withheld. Required change:** specify the `_fmt_stratum_row` rendering
change concretely (e.g. a `side_mix` annotation column or footnote on `mean_ask` whenever a stratum's
rows are not all the same side) and add a RED test asserting the label appears once mixed-side rows are
admitted (post-BLOCKER-3), so the "labelling" commitment is a checked artefact, not a sentence.
→ **19/20**

**Implementation specificity and feasibility — withheld 3/15 originally.** "D-B's root cause remains two
hypotheses pending step 0, correctly sequenced" is inherent to RED-first diagnosis and is awarded.
**The mean_ask-labelling gap above also bears on this criterion** (the withholding branch's rendering
surface is under-specified in exactly the same way): keep 1 point withheld here too, same required
change as above (the concrete rendering mechanism is an implementation-specificity gap as much as a
correctness one). The remaining point is awarded: the withheld-verdict widening of the verdict literal
and the reuse of the existing `range(0)` skip mechanism are both concretely specified.
**Disposition: award 2, keep 1 withheld.** → **13/15**

**Acceptance criteria and validation quality — withheld 4/20 originally.** "AC#1's three-day clock" and
"AC#4's live half remaining an OPEN observation" are honest, unavoidable properties of a
multi-day-observation control and a corpus with no NO-leg fills yet — both awarded (2 points).
"No AC can exercise the post-ruling `cell_dead` behaviour until BLOCKER-3 is answered" is
BLOCKER-3-external — awarded (1 point). **The fourth point is kept**, tied to the same mean_ask-labelling
gap: no AC requires the rendered-column label the plan promises in §6, so an implementer could withdraw
the partition (correctly) but never add the disclosure that made withdrawing it safe, and nothing in §8
would catch that.
**Disposition: award 3, keep 1 withheld. Required change:** same as above — a new AC requiring the
`mean_ask` mixed-side label with a corresponding test. → **17/20**

**Autonomous operation, failure handling, recovery — withheld 2/15 originally.** On re-reading my own
prior text, no defect was actually named against these 2 points ("D-F's alert closes the silent-failure
gap; the withheld-verdict WARN and the orphan-reaccumulation guard are both real and independently
verified" — this is a description of what works, not a gap). Per the reconciliation rule, an unnamed
deduction is not actionable.
**Disposition: AWARD in full.** → **15/15**

**Portfolio objective alignment, scope, dependencies — already 10/10.** No change.

## Final per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20**
- Technical correctness and evidence grounding (20): **19**
- Implementation specificity and feasibility (15): **13**
- Acceptance criteria and validation quality (20): **17**
- Autonomous operation, failure handling, recovery (15): **15**
- Portfolio objective alignment, scope, dependencies (10): **10**

**Total: 94/100**

## Remaining defect and required change

1. **MINOR.** §6's rejection of side-partitioning rests on the claim that a mixed-side `mean_ask` is
   "handled by labelling the rendered column" — but no AC, test, or implementation step specifies what
   that label is, where it appears, or how it is verified. **Required change:** specify the concrete
   rendering mechanism (e.g. a `side_mix` annotation on `_fmt_stratum_row`'s `mean_ask` column whenever
   a stratum is not single-sided) and add a RED test (exercised once BLOCKER-3 is ruled and
   `station_strata`/`ask_band_strata` admit NO rows) asserting the label is present.

## Blockers

- **BLOCKER-1 (strategy-lead / PREREG authority):** `trial_id_prefix` collision — unchanged, genuine.
- **BLOCKER-2 (same authority):** whether `pm_us_crh_cont` is retired — unchanged, genuine. Not a
  plan-text deduction (Fidelity/Technical correctness above).
- **BLOCKER-3 (strategy-lead / PREREG authority):** whether NO-side rows enter the `cell_dead`-bearing
  `station_strata`/`ask_band_strata` at all — `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §7 lists
  "Strata" as a registered, unchanged element (independently confirmed at line 186). The plan's
  recommended disposition (`pi = mean(BE_i)`, unpartitioned) is independently re-derived and correct in
  this review; the authority to adopt it, not the math, is missing. Not a plan-text deduction.

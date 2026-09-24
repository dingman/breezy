# AUD-05 review — round 3 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-05-live-family-tally-unit.md
sha256: 1075f52e1c7a551a668fc7b3739f1b280839fed11979084e7af7fbcb12488662
Round: 3

## Round-2 remedy verification (whole revised plan re-checked against source)

The round-2 MATERIAL defect ("the RED-test oracle belonged to `combine_station_day`, not
`build_stratum_v2`") is genuinely fixed, not merely re-asserted. I independently re-read
`src/breezy/settlement/current_rung_hold_v2.py` fresh this round without trusting §13's claim:

- `build_stratum_v2` (def `:405`, raise `:418-423`) still computes only `n`, `k = sum(row.held...)`,
  `mean_ask`, `pi = mean(break_even_row(...))`, Wilson `(:424-428)`; `StratumV2` (`:391-397`) still
  has no variance field — CONFIRMED byte-identical to round 2's citation.
- `combine_station_day` (def `:298`), `signs` at `:329`, `qs` (`_cell_probability`) at `:330`,
  diagonal at `:341`, cross term at `:344` — CONFIRMED byte-identical, unchanged, correctly excluded
  from D-A's scope.
- `StratumRow`'s docstring (`:99-110`) and `_cell_probability` (`:225-227`, `q_i = P(HIGH ∈ r_i)`,
  `be if side=="yes" else 1-be`) — CONFIRMED verbatim as quoted.
- The plan's derivation — `pi := mean(BE_i)` is the correct null for `k/n` on a NO-only stratum,
  because `held_i = 1{HIGH ∉ r_i}` gives `P(held_i=1) = 1 − q_i = 1 − (1 − BE_i) = BE_i` — **I checked
  this algebra independently and it is correct.** The rejected alternative `pi := mean(q_i)` is
  indeed inverted for NO rows, exactly as argued (`q_i` is the YES-side event probability; comparing
  a NO leg's own win rate against it flips `cell_dead`'s sign). This is genuinely sound math, not an
  assertion dressed as one, and the RED tests (`test_a_no_leg_row_is_scored_not_refused`,
  `test_a_no_only_stratum_uses_the_legs_own_break_even_not_its_reflection`) now exercise the function
  D-A actually changes and are RED today against the live raise site.

The line-citation drift from round 2 is corrected (`combine_station_day` → `:298`, `build_stratum_v2`
→ `:405-437`) — CONFIRMED.

## NEW finding this round — the math is right, but the plan makes a REGISTERED-artefact-scope
ruling itself, unescalated, while the identical class of question sits in BLOCKER-1/BLOCKER-2 two
sections away

**MATERIAL.**

File: AUD-05 §6 "The statistic a side-aware `build_stratum_v2` computes — decided here, not left to
the implementer", §7 step 1, §8 AC#11, §12.

`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §7, "UNCHANGED from PREREG v3", explicitly enumerates,
in the same list as `α = 0.025`, the look schedule, `n_max`/`i_max`, the boundary artefact hash,
`CORPUS_SHA256` and `θ = 0.06`:

> **Strata:** pooled (sequential monitor), station (cell_dead), ask-band (cell_dead)

— i.e. the REGISTERED amendment itself names "Strata" as a frozen, NOT-re-solved element of the
REGISTERED family, at the same level of authority as α and the boundary hash. D-A's fix does two
things: (1) it fixes a genuine implementation defect (the blanket `side != "yes"` refusal predates
the amendment and is not itself a registered element) — this part is sound and does not need a
ruling; but (2) it goes further and **redefines what a side-aware stratum contains**, by partitioning
every pooled/station/ask-band stratum by side (`"pooled|no"`, `"station:KSFO|no"`, etc.), which did
not exist under PREREG v3 or the amendment — neither document describes a side-partitioned station or
ask-band stratum. The plan resolves this itself, in prose headed "**Ruling:**" (§6), using a correct
derivation from `StratumRow`'s field semantics — but that heading claims an authority the plan does
not have. This repo's own binding constraint (this review round's brief, and L-34's class-C
discipline that this same plan invokes for BLOCKER-1/BLOCKER-2) is that PREREG semantics are changed
only **via ruling**, by the strategy-lead/PREREG authority — never decided in-plan, however well
evidenced. The plan is internally inconsistent on exactly this point: BLOCKER-1 (a `trial_id_prefix`
re-issue on a family whose registered `n` is currently 0) and BLOCKER-2 (retiring a family) are both
filed as blockers requiring the SAME authority for changes with **zero current numerical
consequence** — yet the side-partitioning of a §7-frozen "Strata" element, which changes what
`cell_dead` is evaluated over for every future NO-bearing station/ask-band cell, is decided
in-plan and merely labelled a "Ruling" by the plan's own author.

**Why this is not merely academic, even though `cell_dead` is confirmed non-gating (see below).** I
traced `any_cell_dead`'s only consumer: `scripts/analysis/family_tally_v2.py:655,728,753,792,831` —
it is a REPORT-LEVEL flag ("CELL-DEAD" text), never fed into any admission gate, the LD-OBF boundary,
or trading logic. So the blast radius of getting the side-partition wrong is bounded to a diagnostic
label in a report, not a trading decision — this is why I classify the finding as MATERIAL to the
plan's process discipline, not to safety. But the review brief's binding constraint is explicit:
"PREREG semantics only via ruling — operator/strategy-lead decisions surfaced as BLOCKERS rather than
decided." A plan that surfaces two structurally similar, lower-stakes REGISTERED-identity questions
as blockers while deciding a third, REGISTERED-and-explicitly-frozen one itself is not applying that
rule consistently, and an implementer following this plan literally would ship a change to a §7-listed
"UNCHANGED" element without the sign-off the repo's own process requires for changes of that class.

Fix: add **BLOCKER-3** to §12, in the same form as BLOCKER-1/BLOCKER-2: "does the side-partitioning
of `build_stratum_v2`'s pooled/station/ask-band strata (never described in PREREG v3 or its NO-side
amendment) require strategy-lead ruling before it lands, given the amendment's §7 lists 'Strata' as
unchanged and not re-solved?" Keep the current derivation (`pi := mean(BE_i)`, per-side partitioning)
as the **recommended** disposition — exactly as BLOCKER-1 already states "Recommendation: (a)" — but
do not present §6's "Ruling:" language as a decision this plan is authorized to make. Rename the
heading from "Ruling" to "Recommended disposition, pending BLOCKER-3" and adjust AC#11 to say the
recommended disposition is honoured pending that ruling, not that it is settled.

## Verification of the four brief-specified checks for AUD-05

- **Test oracle now exercises the changed code path:** CONFIRMED — `test_a_no_leg_row_is_scored_not_refused`
  and its siblings target `build_stratum_v2` directly, which raises today at `:418-423` for
  `side != "yes"` (independently re-read, matches). RED before the fix, plausible GREEN after (the
  fix is a narrow field/call-site change consistent with the ruled semantics).
- **Byte-identity of the end-to-end statistic on all-YES input:** `test_an_all_yes_corpus_renders_a_byte_identical_report`
  drives the whole pipeline and asserts the rendered report is unchanged pre/post-fix — this is a
  sound, appropriately strong invariance proof and is a genuine improvement over round 1's
  single-function check.
- **`pi := mean(q_i)` rejection, judged on the math:** CORRECT, independently re-derived above.
- **Is side-partitioning itself a change to the registered statistic requiring a ruling:** YES, for
  the reason given in the MATERIAL finding — not because the math is wrong, but because the amendment
  itself lists "Strata" as a registered, frozen element, and this repo's own process (as applied two
  sections earlier in the same plan) treats even zero-consequence identity questions on REGISTERED
  artefacts as requiring the same authority.

## Other round-2 dispositions re-checked

D-B pre-narrowing (`no_leg_instrument_id:277`, `leg_of:289`), D-F's alert wiring
(`emit_alert`/`resolve_alert_sink`/`AlertPayload` at `health.py:668/579/351`, exact 4-field shape),
and the orphan re-accumulation guard were all independently re-verified against source this round and
hold as claimed — no new defect in any of them.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **16** — G-04 fully covered technically, but the D-A
  remedy as written proceeds past a ruling boundary the plan's own BLOCKER-1/2 pattern says this
  class of question requires; docked below round 2's 17 for the newly identified process gap.
- Technical correctness and evidence grounding (20): **16** — every citation independently
  re-verified this round (raise sites, `combine_station_day`, `_cell_probability`, `StratumRow`
  docstring) and all hold exactly; the `pi := mean(BE_i)` derivation is correct math. Not docked
  further for the ruling-scope question, which is a process defect, not a correctness one.
- Implementation specificity and feasibility (15): **11** — matches round 2; the field-level change
  is well-specified, D-B's root cause is still two hypotheses pending step 0 (unchanged, acceptable
  given step 0 discriminates before code is written).
- Acceptance criteria and validation quality (20): **14** — AC#11 ("the side-aware stratum ruling is
  honoured, not re-derived") presupposes a ruling that has not actually been made by the authority
  this repo requires for REGISTERED-artefact-scope questions; docked 2 below round 2's 14→ wait,
  aligned to the new finding rather than round 2's unrelated defect, resulting in 14 (down from what
  would otherwise be ~16 on the strength of the now-correct test oracle).
- Autonomous operation, failure handling, recovery (15): **13** — matches round 2; D-F closes the
  three-day silent-failure gap with a verified, delivering, latched alert; the orphan-reaccumulation
  guard is real.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's chain (AUD-05 → n grows →
  AUD-02 → AUD-06b BLOCKER-B → AUD-04), numeric baseline, falsifier and honest zero-ROI-contribution
  framing were assessed twice already (round 2: mle 7/10 citing "no named defect", pm 10/10) and I
  independently find nothing further to dock here — the round-2 mle deduction cited only the
  criterion's own structure, not a fixable gap, and the brief's instruction for this round is to
  award such points absent a named defect. Awarded in full.

**Total: 80/100**

## Required changes to reach 100

1. Add BLOCKER-3 to §12 naming the side-partitioned-strata question as requiring strategy-lead/PREREG
   ruling (same class as BLOCKER-1/BLOCKER-2), retaining the current derivation as the recommended
   disposition. Rename §6's "Ruling:" heading accordingly and soften AC#11 to match.
2. Carried, still true: pin the exact D-B root cause via step 0 before writing its fix (already
   correctly sequenced in §7 step 3; no change needed beyond what's there).

## Blockers

- **BLOCKER-1 (strategy-lead / PREREG authority):** `trial_id_prefix` collision — unchanged from
  round 1/2, genuine, correctly deferred.
- **BLOCKER-2 (same authority):** whether `pm_us_crh_cont` is retired — unchanged, genuine.
- **BLOCKER-3 (new, this round; strategy-lead / PREREG authority):** whether side-partitioning
  `build_stratum_v2`'s pooled/station/ask-band strata — an element PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md
  §7 lists as registered and "NOT re-solved or re-derived" — requires ruling before it lands. The math
  behind the plan's proposed disposition (`pi := mean(BE_i)`, per-side partitioning) is independently
  verified correct in this review and is a sound recommendation to carry into that ruling; it is the
  authority to decide it, not the content, that is missing. This is a plan-completeness gap this round
  identifies, not a math error — the plan should surface it as it does BLOCKER-1/2, not resolve it.

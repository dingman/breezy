# AUD-06a review — round 1 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06a-r11-boundary-revalidation.md
sha256: efb219f8319ebf6ab53843007456e11480527ba3b396fa3cebffbb50a03a6fda
Round: 1

## Claims verified
- PREREG v3 (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:5,45,191,208,314`) registers LD-OBF, two one-sided α=0.025, `I_max=40`, `n_max=160`, `look_step=10` (looks every 10 fills) — CONFIRMED.
- `tests/unit/test_multi_position_validation_2026_09_14.py:161-189` carries the strict `xfail` the plan targets, with reason text reproducing the plan's cited figures almost verbatim: "~0.059 at seed 20260914/5000 reps (0.0592) and seed 20260914/2000 reps (0.058)... A qty=1-only control... measures ~0.011-0.013" — CONFIRMED, matches R-11's 0.059 vs 0.012 figures and AC#1's reproduce-first gate is well-founded (the artefact already has the seed and rep counts recorded).
- The registered `Var_H0` formula the plan quotes in §6 matches `MULTI_POSITION_PER_STATION_2026-09-14.md:130-132` — CONFIRMED by the file excerpt in the plan and cross-checked against the same plan file's own text.

## Defects

**MATERIAL — the plan's diagnosis hypothesis does not engage with the mechanistic diagnosis the codebase already carries.**
File: AUD-06a-r11-boundary-revalidation.md §6 "Diagnosis obligation"
Issue: The plan states the "leading hypothesis is that unequal weights lower the effective number of independent draws so the asymptotic normal approximation underlying LD-OBF degrades at the early looks," and proposes evaluating "raise the first look's n" as a remedy. But `test_multi_position_validation_2026_09_14.py:161-179`'s own xfail reason — the artefact this exact plan step 1 is instructed to reproduce — already gives a considerably more specific, already-measured mechanism: "higher qty pushes a station-day's variance up to 9x a single Bernoulli term, so I saturates far faster than the artefact's n_k/n_max=0.25-per-draw schedule assumes, and the realised-t boundary interpolation undershoots at that faster accrual." This is a schedule/interpolation-undershoot mechanism, not a small-sample normal-approximation failure, and it does not obviously predict that raising the first look's n helps (if variance inflation itself, not just the number of looks, drives the faster-than-assumed information accrual, an earlier first look still hits the same undershoot sooner, just at a different `t`). The plan does not cite or reconcile with this existing diagnosis anywhere, and proposes running a fresh, differently-motivated investigation that could waste analysis effort chasing the wrong lever, or worse, publish a remedy that treats a symptom the documented mechanism contradicts.
Fix: Before step 1 of §7, read and cite the exact xfail-reason mechanism (schedule mismatch / boundary interpolation undershoot from variance inflation) as the leading hypothesis, and either (a) show computationally that "raise the first look's n" mitigates that specific mechanism, or (b) drop it as a remedy and reason instead about whether an envelope (bounding qty so variance inflation stays within the schedule's assumed accrual rate) is the only lever consistent with the documented cause.

**MATERIAL — no re-validation trigger for the published envelope once it can go stale.**
File: AUD-06a-r11-boundary-revalidation.md §9 "Envelope derived on the wrong `BE` prior"
Issue: §9 reports sensitivity to the `BE` prior at publication time but defines no ongoing check. Once `Q_MAX_VALIDATED` is baked into AUD-06b's sizing code as a module constant, nothing re-examines whether the live ask distribution the envelope was validated against still holds — an envelope computed once from historical asks could license sizing indefinitely against a qty distribution the boundary was, in the current live ask regime, never actually validated for. This is the same class of drift the audit already caught once (AUD-04's own evidence: the exit-window study drifted from its Rev2 baseline without anyone noticing until this audit).
Fix: Name a concrete re-validation trigger — e.g., a scheduled or gate-triggered comparison of the live ask distribution's summary statistics against the ones used to derive the envelope, with a stated tolerance beyond which `Q_MAX_VALIDATED` must be re-derived before AUD-06b sizing continues to rely on it. (This need not run on a timer per §9's own "no autonomy required" stance — it can be a gate AUD-06b's re-run-the-sweep step checks — but the plan currently names none.)

## Per-criterion points
- Fidelity to gap and completeness: 16/20
- Technical correctness and evidence grounding: 12/20 (material dock for the unreconciled diagnosis above — this is the plan's single highest-value analytical output and it is currently pointed at the wrong hypothesis without acknowledging the better-evidenced one)
- Implementation specificity and feasibility: 11/15
- Acceptance criteria and validation quality: 17/20
- Autonomous operation, failure handling, recovery: 9/15 (docked below the author's 11 — the missing re-validation trigger is a genuine gap in a measurement-engineering sense, not merely a nice-to-have)
- Portfolio objective alignment, scope, dependencies: 5/10

**Total: 70/100**

## Required changes to reach 100
1. Cite and reconcile with `test_multi_position_validation_2026_09_14.py`'s existing xfail-reason diagnosis before proposing an independent hypothesis; re-justify or drop the "raise the first look" remedy against that specific mechanism.
2. Name a concrete re-validation trigger for the envelope against `BE`-prior drift.
3. Author-named: pin replication count, `Var(S)≈1` tolerance, and the CI method for the crossing rate.
4. Author-named: justify the `q_max ≥ 2` threshold in AC#3 rather than asserting it.

## Blockers
None requiring operator/strategy-lead ruling — the plan correctly self-certifies that no operator-reserved value enters the analysis (§12).

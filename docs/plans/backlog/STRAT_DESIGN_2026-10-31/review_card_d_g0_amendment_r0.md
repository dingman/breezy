# Card D G0 amendment r0 — merged blind review (architect + prediction-market-reviewer), 2026-10-31 19:50Z

Verdict: **REVISE** (both). Card D is NOT moot. Coordinator merge of two independent returns; contradictions none.

## Rulings
- Holdout scope (architect, overrules `review_card_a_r0.md:28`): the seal limits what may be FITTED, FOLDED or
  SCORED on post-07-01 rows, not what may be read. Controlling text is
  `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md`: cl.1 freezes the holdout at
  [07-01, 10-02) against any fitter/screener; cl.2 makes every day ≥ 10-02 forward data; cl.3 permits tape studies
  touching the window as descriptive evidence with disclosure; cl.4 makes any change an architect change. Code:
  `multisource_blend_features.py:41-42, :380-391`, `F13_prereg_blend_v1.json:13`, `lamp_archive_runs.py:58-60`.
  The probe/store guards (`metar_routine_minute_probe.py:121-122, :390-393`) only limit the FB-R13 feature fetch.
- Consequence: Card A/E reads were permitted (cl.3). **Card E lacks the cl.3 disclosure line** → follow-up.
  cl.1's end date never landed in code (`DEFAULT_SPLITS`, `nbp_calibration.py:273-278`; `holdout_end_exclusive` 0 hits).
- Q2 (pm, measured, counts only): 5-min cache rows DO carry a T-group: KSFO 98.6%, KLAX 99.6%, KMDW 99.8%,
  KMIA 97.9%, KNYC 98.1% (08-27..09-20); ~91% on 5-min marks; KNYC hourly at :51. Cache spans 2020-12-31 → 10-31
  (≈590k rows/non-NYC station), not "08-27 onward". Q3: CLI products cache as `.zip`; loader globs `*.txt` and
  station-filters (`cli_basis_offer_gate_scan.py:523, :529`) → low risk, but assert the IEM ASOS header per file.
- Q4: HIGH only; KNYC excluded from the pooled gate (report separately). Q5: ≤ 30-line local guard; `wp7b_census.py` stays byte-unchanged.
- Q6 (pm): G0 as written is a near-certain PASS (~13 T-group rows/hour) → fold into the bid prereg as a precondition
  (per-station ≥ 70% over 00:00..10:30 LST, since the bid test needs the running max VALID at 10:30 LST, not any row
  in the hour). Arithmetic confirmed: PT 18Z / CT 16Z / ET 15Z standard offsets; 40 days → 200 station-days (160 w/o KNYC).

## Blockers for r1
1. Rebuild §1/§3 on the 10-03 RULING: split 09-21..10-01 (frozen holdout, cl.3 descriptive + disclosure) from
   10-02..10-30 (forward data); restate the output bar as cl.3 "never a confirmatory input"; disclosure line in the artefact header.
2. Drop the standalone G0 prereg/freeze; merge as a coverage precondition inside the bid prereg (one freeze, one look).
3. Correct the cache coverage claim and replace the "UNVERIFIED" row with the measured shares; fix the two loose cites
   (Q4 ":237-240" → `cli_basis_offer_gate_scan.py`; `metar_routine_store.py` span is at `:10`).
4. Dry run AND look: every contributing `.txt` must carry the IEM ASOS header, else exit 2; dry run prints the count only.
5. Q2 characterisation runs BEFORE the freeze (reader drops T-group-less rows, `settlement_alignment_study.py:251-253`).

## Prize (pm, binding for the decision)
The bid test (band below the 10:30 LST running max) has no plausible positive prize: expected median YES bid ≤ 0.03
(`design_r2.md` §4.D expected KILL); a NO at ≥ 0.97 nets < 1 ¢ after θ = 0.0695 rounding; even the 0.10 PASS nets
≈ 0.09/contract at qty 1 on a few station-days a month; consistent with `design_r2.md` §1 ("D dead band: $0") and the
10-22 audit (maker 17/17 LB 0.84 < 0.875). A KILL is still an informative, cheap result (one flag, one look).

## Coordinator decision
Card D continues as a folded bid prereg r1 (blockers 1–5) at the next cycle, explicitly framed as expected-KILL with
prize ≈ $0 at qty 1; the operator size lever remains the only route to a non-trivial prize. Follow-ups: Card E
disclosure line; `DEFAULT_SPLITS` end-date gap (architect change, cl.4).

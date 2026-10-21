# MAKER sharp v1 — leakage audit and robustness (2026-10-21)
Family candidate `pm_us_no_maker_sharp_v1`: resting BUY NO qty 1, Stage 0 rule with P_MIN 0.97, E_MIN 0.04, B_FLOOR 0.75, B_CAP 0.89, MAX_RUNGS 2, no listing abstention, LAX/MDW/MIA/SFO, design tape 2026-09-18..10-13 (skip 10-01), 92 station-days. Driver `scripts/analysis/maker_design_nobid.py` (branch design/maker-nobid-2026-10-21: eac99bd6, 1713c8bf, 0d6b4c59; merged as C0 at 6b8407a4 up to 1713c8bf). Positive control: shipped-rule arm reproduces the Stage 0 verdict table exactly (88 station-days, 44 bid-bearing, 7 stressed fills).

## Leakage review (prediction-market-reviewer, plan r1 review, 2026-10-21)
No look-ahead found: NBP backfill `available_at_ns` from Last-Modified with a 60-min floor; look-ahead guard `chain.at(decision−1)`; pinned cycles 13Z/19Z D-1 and 01Z D (first MAX column); calibration artefact sha 9c0b6d6e fit on 05-04..06-30 (no overlap with the design window); truth read only after simulation; flagged/corrected CLI rows raise; win = NOT contains(tmax), inclusive bands. Fill model is the stress pass (queue ×2, gaps ×2; 17 vs 20 base fills) with slip 0.01 — pessimistic for a maker.

## Disclosures
- `sharp` was chosen after six arms on the same 92 station-days (control, control_noabst, nbp_deep, spike_bid, sharp, sharp_cap84): a nomination, not a confirmatory result.
- 17/17 wins: one-sided 95% lower bound on win rate 0.84 < break-even w* ≈ 0.875 (mean bid 0.865 + fee 0.01): zero edge is NOT excluded. n_eff 13.5 < 30: UNDERPOWERED.
- Departures from the shipped Stage 0 rule: no listing abstention; maker fee charged at taker θ; Δ (clock offset) 0 in the primary run.

## Robustness reruns (pre-declared threshold, plan r3 R3) — PASS
| arm | fills | wins | mean X | n_eff | LB(α .00625) |
|---|---|---|---|---|---|
| sharp Δ=0 | 17 | 17 | 0.1153 | 13.50 | +0.099 |
| sharp Δ=±600 s (sim applies |Δ|) | 18 | 18 | 0.1094 | 13.67 | +0.096 |
| sharp MAX_RUNGS 1 | 5 | 5 | 0.1040 | 4.33 | +0.090 |
Δ=±600 s vs Δ=0: +LAX 09-26 gte77lt78f @0.89, +MDW 10-06 gte76lt77f @0.89, −MDW 10-02 gte67lt68f @0.81; Jaccard 16/19 = 0.84 ≥ 0.8; no new losing fill; mean X 0.109 ≥ 0.04 → PASS → ship MAX_RUNGS 2 (k1 keeps 5/17).
Late-listed vs on-time (census first_seen vs D-1 12:00Z): 9 fills Σ X 1.08 (mean 0.120) vs 8 fills Σ X 0.88 (mean 0.110) — edge not a late-listing artefact.
Outputs: `~/.local/share/breezy/derived/replay/design/maker_nobid_{full,sharp,robust}/`.

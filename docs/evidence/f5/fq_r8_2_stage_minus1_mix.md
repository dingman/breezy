# FQ-R8-2 Stage -1: pin the mix (is M-yes structurally excluded by the frozen v2 design?)

Date: 2026-10-08
Role: domain reviewer (prediction-market-reviewer), read-only. Plan: FQ-R8-2-UNDER-VETO_plan_r2.md step 5 and r2.1 row C-13.

## Inputs (only these)
| Input | Sha |
|---|---|
| `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_design.json`, frozen | 072ab026 (freeze commit). Last touched by 19dbcfaa, which only stamps `frozen_sha`. `git diff 072ab026 -- <file>` shows exactly that one line. Every other key is byte-identical to the freeze. |
| `.../F5-pin-request_r3.md` (A1 r3 spec) | blob 77101415 at HEAD d6a339ce |
| `.../F5_prereg_v2_amendment_A1.json` (frozen A1) | blob cde3e7c5 at HEAD d6a339ce |
| `scripts/analysis/fq_loss_floor_mc_rows.py` (`apply_mix`) | last commit 747da3a4 |
| `src/breezy/analysis/autonomy/eprocess.py` (`m_cap`), `scripts/analysis/fq_mc_livedata.py` (`ask_floor`) | Used only to resolve what a design key means. Neither is a pin. |

Tape, decision logs and fills were not used.

## M-yes definition
`scripts/analysis/fq_loss_floor_mc_rows.py:249-256`:
- `M-pool` returns the day unchanged.
- `M-yes` and `M-no` keep only the legs on one side (`leg.side == side`) and rebuild the day with netting 0.0.
- M-yes is therefore the station-days whose legs are all YES, with no same-rung pairs. Its side share is 100% YES. M-no is the mirror image.
- The A1 r3 §4.5 "three mixes" rows use the same scenarios.

## Frozen design keys that bear on side or price
| Key (value) | Excludes M-yes? | Why |
|---|---|---|
| (no `side` key) | No | The design has no side restriction, so a YES-only take set is admissible (plan F-16). |
| `ask_floor` (0.05) | No | A lower bound on the executable ask, the same on both sides. It removes only legs priced below 0.05. It shrinks the YES set; it does not empty it or fix a mix. |
| `haircut` (0.01) | No | A symmetric price shift. |
| `theta` (0.0695) | No | The venue fee, symmetric in p(1-p). |
| `rounding` | No | A formula for BE. It does not choose a side. |
| `take_rate_lower` (0.25) | No | A rate floor. It carries no side information. |
| `m_cap` (2) | No | Pins the e-process denominator and the counted takes per day (`eprocess.py:231-246`). Extra takes are uncounted, not refused, so two YES legs still make a valid M-yes day. |
| `x_max`, `lambda_max`, `mu_max`, `betting_rule_*`, `delta_h`, test-design and parity keys | No | Bet, e-process and test design. None of them filters legs. |

A1 r3 / amendment A1 side rules also fail to exclude M-yes:
- Same-rung netting and the opposite-sides refusal govern mixed-side pairs only.
- "Sum of NO q > 1 refuses" does not apply to a YES-only day.
- The shrink is YES-first.
- A1 itself ran M-yes as the failing mix (G3(-0.16) = 0.2104), so the frozen A1 treats M-yes as reachable.

## Implementation choices that do not count
Strategy-level side and price behaviour (NO-side hunting, config ask bounds) is outside the frozen design JSON, so it cannot be structural exclusion. Tape shares would be corroboration only.

## Verdict
MIXSET = {M-pool, M-yes, M-no} (no structural exclusion)

This was written before Stage 0 ran.

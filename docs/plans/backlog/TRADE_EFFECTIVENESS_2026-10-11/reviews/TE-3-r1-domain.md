VERDICT: READY-WITH-CHANGES (the INFEASIBLE verdict holds, but its framing is overstated)
SCORE: 84/100

I did not read any M1-v3 outcome data. I read only the `ask_threshold` entry in `docs/evidence/m1v3/PREREG.json`, which is the band constant you allowed.

**Findings**

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| S1 | HIGH | "Structural, independent of the rate" (§0, §8) is false. The ceiling of 420 only beats n_min = 445 at δ=0.04, α=0.05, p0=0.12. Under the same normal approximation, δ=0.05 needs 290 and δ=0.06 needs 205, both below 420. At p0=0.07 and δ=0.04, n=292. The binding constraint is n_avail, which does depend on λ. The margin over the ceiling is only 6% (exact binomial n is 464 vs 445). | §6 table | Reword: "infeasible for δ ≤ ~0.05 at the observed rate range; the ceiling is not binding". Quote the minimum detectable effect at n_avail instead. |
| S2 | HIGH | The 0.04 plausibility bound is a K-ledger rule from the H-NO-SIDE ruling. §5 declares TE-3 Lane E, outside the ledger and at α=0.05, like M1-v3. §6 then rejects δ=0.08 (n=119 < central n_avail of 151) because it is "above the 0.04 bound". That applies a ledger rule to a non-ledger lane. | §5 vs §6 levers table | Either drop the lane-E claim, or reject δ=0.08 on prior grounds only (adverse fair-odds, SEARCH-picked band). A reviewer could contest the current wording. |
| S3 | MED | Central MDE is stated as 0.077. My figure is 0.071 at n=151, with 0.051 at n=287 and 0.042 at n=420 (binomial, p0=0.12, α=0.05). The 0.075 at n=420 is the ledger figure, which uses the pinned variance 0.25 (sd 0.5). That is about 2.4 times the Bernoulli variance at p=0.12, so the two MDEs are not comparable. | §6 | Label the two MDE families separately. |
| S4 | MED | The single p0=0.12 is not the band's break-even. The fee is `ROUND_HALF_EVEN` to the cent, so it is 0 for asks 0.06–0.07 and 0.01 for 0.08–0.12. Break-even with s=0.01 therefore runs from 0.07 to 0.14, and 0.12 corresponds to an ask of 0.10 only. n_min runs from 292 at p0=0.07 to 500 at p0=0.14 (δ=0.04). | `decision.py:320-327` | Give the n_min range. The verdict is unchanged at p0 ≥ 0.09 and is knife-edge at p0 = 0.07. |
| S5 | LOW | The band is inconsistent. The prose says NO ask 0.07–0.12 (YES bid 0.88–0.93), but the census uses [0.06, 0.12] (YES bid 0.88–0.94). | §1 vs §4 WP-1 | Pick one. |
| S6 | LOW | Dates are off by one day or by month. Central is 2027-07-08, not 07-09. The ledger n=1485 central date is 2029-02-05, not "2029-01". | recomputed | Fix the dates. |
| S7 | LOW | Same-day correlation across the 5 stations (shared weather regime) shrinks the effective n under the calendar-day cluster bootstrap. This strengthens INFEASIBLE, and the plan is silent on it. | §5 | Add one sentence. |

**Recomputed numbers**
- **n_min table (normal approximation):** matches all 12 cells within rounding. Rounded up, the plan's cells are 445, 290, 205, 119 (α=0.05), 559, 364, 257, 149 (α=0.025) and 672, 437, 308, 178 (α=0.0125). Exact one-sided binomial (n at which power ≥ 0.8) is larger: 464, 307, 219, 127 at α=0.05. The 0.0125 row is 705, 461, 331, 191. The plan should say its figures are approximations.
- **Ledger n of 1485:** correct. It uses α=0.0125 (0.05 over 4 slots), z-sum 3.0830 and sd 0.5, giving 1485.2.
- **MDE at 420:** 0.0752 on the ledger formula, so "0.075" is correct.
- **Exact Poisson CI for 9 events in 4 days:** [1.029, 4.271] per day, correct.
- **n_avail:** 151, 69 and 287 are correct (with κ=0.8, T=84).
- **Verdict dates:** 2027-07-08 central, 2027-03-13 high, and low is 2028-04-26. The ledger n at the high rate gives 2028-01-11.
- **P(≥2 of 3 | p=0.12):** 0.03974, so "0.040" is correct.

**Robustness of INFEASIBLE**
- **Sequential design:** group-sequential LD-OBF with Wilson at α=0.025 and looks every 10 fills (the PREREG v2 ruling) cuts expected n under H1 by roughly 10–20%, with a slightly larger maximum n. It cannot bridge 445 against 287 or 151. It rescues only large effects (δ ≥ 0.07), which the prior excludes.
- **Pooling with the PREREG v3a NO leg:** no benefit. `cont` and `v4` are halted and there is no new flow. The ledger counts with-takes station-days, and H-NO-SIDE is already `UNDERPOWERED_NOT_REGISTERED`.
- **Conclusion:** the verdict is robust for δ ≤ 0.05 and for the ledger path. It is contestable only through the S2 inconsistency, and the plan should state it that way.

**Disjointness from M1-v3**
- **Price bands:** a single row cannot satisfy both NO ≥ 0.90 inclusive and NO ≤ 0.12, so the bands are disjoint.
- **Station-days:** the same station-day can host an M1-v3 NO favourite on another rung and a TE-3 entry on the current rung. Their outcomes are dependent, so the two samples must never be pooled. The plan already bans this.
- **Windows:** the M1-v3 forward window starts after the freeze commit and the TE-3 census is pre-09-25, so they do not overlap.

**Premises checked**
- P1 (NO price = 1 − YES bid): CONFIRMED. `decision.py:455-496` and `market_calibration_scan.py:242` use it. Per the venue API note in the venue-represents-no-buy-as-sell-buy-short memory, a NO buy is a SELL of YES that consumes the bid side. Executable size is the bid size. The empty-bid case returns None rather than being synthesised.
- P2 (fee formula θ·a(1−a), banker's-rounded to the cent): CONFIRMED.
- P3 (ledger constants VARIANCE_BOUND=0.25 and `recompute_mde`): CONFIRMED (`hypothesis_ledger.py:196,859`).
- P4 (break-even p0=0.12): PARTLY. It is correct only for an ask of 0.10 (see S4).
- P5 (M1-v3 `ask_threshold` 0.90 inclusive): CONFIRMED.

I did not independently re-verify the offer-tape census (9 rungs in 4 days) or the 5-city PM.us surface.
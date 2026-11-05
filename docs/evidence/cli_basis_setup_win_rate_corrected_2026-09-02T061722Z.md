# CLI-basis candidate #2 -- corrected, hour-restricted `P(win | setup)` (Item 3, resolved)

Generated 2026-09-02T061722Z from
`scripts/analysis/cli_basis_hourly_profile_study.py`, pre-registered in
`scripts/analysis/pre_registration_2026-09-02T061500Z.md`. This document
**resolves the ⚠ challenge** on
`cli_basis_setup_win_rate_2026-09-02T060103Z.md` (see that file's own banner,
now replaced with a pointer here).

## Per-hour diagnostic (produced FIRST, before any rule was chosen)

`P(win | setup)` (margins {1, 2} pooled, `n`/rate/Wilson bounds) and
`P(R_h == R_23)` (the running max at hour `h` already equals its end-of-day
value), both by local-standard hour, per dense station:

| station | hour | n (win-rate) | rate | Wilson lower | Wilson upper | n (convergence) | P(R_h == R_23) |
|---|---:|---:|---:|---:|---:|---:|---:|
| SFO | 0 | 3596 | 98.2759% | 97.7960% | 98.6527% | 1798 | 1.5017% |
| SFO | 1 | 3594 | 97.9132% | 97.3922% | 98.3319% | 1797 | 1.7807% |
| SFO | 2 | 3596 | 97.7753% | 97.2398% | 98.2088% | 1798 | 1.8910% |
| SFO | 3 | 3594 | 97.7462% | 97.2076% | 98.1829% | 1797 | 1.8920% |
| SFO | 4 | 3596 | 97.6363% | 97.0866% | 98.0843% | 1798 | 2.0022% |
| SFO | 5 | 3598 | 97.5820% | 97.0270% | 98.0355% | 1799 | 2.0567% |
| SFO | 6 | 3598 | 97.4986% | 96.9354% | 97.9605% | 1799 | 2.1679% |
| SFO | 7 | 3596 | 97.3304% | 96.7509% | 97.8088% | 1798 | 2.3359% |
| SFO | 8 | 3596 | 96.8854% | 96.2657% | 97.4051% | 1798 | 2.6140% |
| SFO | 9 | 3596 | 94.5495% | 93.7589% | 95.2451% | 1798 | 4.5050% |
| SFO | 10 | 3596 | 87.0133% | 85.8750% | 88.0727% | 1798 | 10.6229% |
| SFO | 11 | 3598 | 70.6782% | 69.1692% | 72.1430% | 1799 | 26.6259% |
| SFO | 12 | 3596 | 50.1947% | 48.5611% | 51.8278% | 1798 | 50.3893% |
| SFO | 13 | 3598 | 31.2674% | 29.7733% | 32.8014% | 1799 | 73.4853% |
| SFO | 14 | 3598 | 19.6776% | 18.4112% | 21.0087% | 1799 | 88.5492% |
| SFO | 15 | 3598 | 13.9522% | 12.8584% | 15.1229% | 1799 | 96.9427% |
| SFO | 16 | 3596 | 12.6251% | 11.5793% | 13.7507% | 1798 | 98.7208% |
| **SFO** | **17** | 3598 | 12.3680% | 11.3322% | 13.4840% | 1799 | 99.2218% |
| SFO | 18 | 3598 | 12.3124% | 11.2788% | 13.4264% | 1799 | 99.3330% |
| SFO | 19 | 3598 | 12.1734% | 11.1452% | 13.2824% | 1799 | 99.4441% |
| SFO | 20 | 3598 | 12.0901% | 11.0650% | 13.1959% | 1799 | 99.5553% |
| SFO | 21 | 3598 | 12.0623% | 11.0383% | 13.1671% | 1799 | 99.6109% |
| SFO | 22 | 3596 | 11.9299% | 10.9109% | 13.0302% | 1798 | 99.7219% |
| SFO | 23 | 3598 | 11.7843% | 10.7713% | 12.8788% | 1799 | 100.0000% |
| MIA | 0 | 3624 | 98.6755% | 98.2484% | 98.9995% | 1812 | 1.3797% |
| MIA | 1 | 3624 | 98.6203% | 98.1858% | 98.9519% | 1812 | 1.3797% |
| MIA | 2 | 3622 | 98.5367% | 98.0911% | 98.8795% | 1811 | 1.4357% |
| MIA | 3 | 3624 | 98.5375% | 98.0921% | 98.8801% | 1812 | 1.4349% |
| MIA | 4 | 3622 | 98.4815% | 98.0288% | 98.8315% | 1811 | 1.4357% |
| MIA | 5 | 3626 | 98.4556% | 97.9999% | 98.8087% | 1813 | 1.4892% |
| MIA | 6 | 3624 | 98.4547% | 97.9988% | 98.8081% | 1812 | 1.4901% |
| MIA | 7 | 3626 | 98.2625% | 97.7834% | 98.6396% | 1813 | 1.5996% |
| MIA | 8 | 3622 | 97.0182% | 96.4126% | 97.5243% | 1811 | 2.6505% |
| MIA | 9 | 3622 | 90.4473% | 89.4467% | 91.3621% | 1811 | 7.1231% |
| MIA | 10 | 3622 | 72.9155% | 71.4445% | 74.3379% | 1811 | 22.9707% |
| MIA | 11 | 3624 | 51.6004% | 49.9726% | 53.2249% | 1812 | 48.0684% |
| MIA | 12 | 3624 | 33.0574% | 31.5445% | 34.6062% | 1812 | 71.1921% |
| MIA | 13 | 3626 | 21.0425% | 19.7467% | 22.3995% | 1813 | 88.1412% |
| MIA | 14 | 3626 | 15.6922% | 14.5447% | 16.9123% | 1813 | 96.3596% |
| MIA | 15 | 3626 | 13.7066% | 12.6255% | 14.8644% | 1813 | 99.3933% |
| MIA | 16 | 3626 | 13.4859% | 12.4127% | 14.6364% | 1813 | 99.7794% |
| **MIA** | **17** | 3626 | 13.4584% | 12.3861% | 14.6079% | 1813 | 99.8345% |
| MIA | 18 | 3624 | 13.4382% | 12.3664% | 14.5874% | 1812 | 99.8344% |
| MIA | 19 | 3626 | 13.4584% | 12.3861% | 14.6079% | 1813 | 99.8345% |
| MIA | 20 | 3624 | 13.4658% | 12.3930% | 14.6159% | 1812 | 99.8344% |
| MIA | 21 | 3624 | 13.4382% | 12.3664% | 14.5874% | 1812 | 99.8896% |
| MIA | 22 | 3622 | 13.3352% | 12.2668% | 14.4812% | 1811 | 100.0000% |
| MIA | 23 | 3624 | 13.3278% | 12.2600% | 14.4733% | 1812 | 100.0000% |
| MDW | 0 | 3652 | 89.7043% | 88.6765% | 90.6486% | 1826 | 9.6933% |
| MDW | 1 | 3652 | 89.3209% | 88.2776% | 90.2816% | 1826 | 10.1314% |
| MDW | 2 | 3652 | 89.1292% | 88.0783% | 90.0980% | 1826 | 10.4600% |
| MDW | 3 | 3650 | 88.8767% | 87.8155% | 89.8562% | 1825 | 10.6301% |
| MDW | 4 | 3650 | 88.7945% | 87.7301% | 89.7773% | 1825 | 10.6849% |
| MDW | 5 | 3650 | 88.5753% | 87.5025% | 89.5670% | 1825 | 11.0685% |
| MDW | 6 | 3650 | 88.0822% | 86.9908% | 89.0935% | 1825 | 11.5068% |
| MDW | 7 | 3650 | 87.4521% | 86.3379% | 88.4875% | 1825 | 12.0000% |
| MDW | 8 | 3652 | 86.3910% | 85.2406% | 87.4649% | 1826 | 13.0887% |
| MDW | 9 | 3652 | 83.3516% | 82.1085% | 84.5246% | 1826 | 15.5531% |
| MDW | 10 | 3652 | 76.6977% | 75.2990% | 78.0403% | 1826 | 20.9200% |
| MDW | 11 | 3652 | 65.3614% | 63.8028% | 66.8878% | 1826 | 31.5444% |
| MDW | 12 | 3652 | 47.4808% | 45.8648% | 49.1022% | 1826 | 48.3571% |
| MDW | 13 | 3652 | 28.8609% | 27.4141% | 30.3521% | 1826 | 70.2629% |
| MDW | 14 | 3652 | 17.5520% | 16.3525% | 18.8197% | 1826 | 85.7065% |
| MDW | 15 | 3652 | 12.9244% | 11.8752% | 14.0515% | 1826 | 93.2640% |
| MDW | 16 | 3652 | 11.5279% | 10.5323% | 12.6044% | 1826 | 95.3998% |
| **MDW** | **17** | 3652 | 10.7612% | 9.7971% | 11.8078% | 1826 | 96.4951% |
| MDW | 18 | 3652 | 10.5148% | 9.5611% | 11.5515% | 1826 | 96.8784% |
| MDW | 19 | 3652 | 10.2683% | 9.3252% | 11.2949% | 1826 | 97.2070% |
| MDW | 20 | 3652 | 9.8302% | 8.9064% | 10.8384% | 1826 | 97.7547% |
| MDW | 21 | 3652 | 9.4195% | 8.5143% | 10.4100% | 1826 | 98.1928% |
| MDW | 22 | 3652 | 8.5706% | 7.7057% | 9.5226% | 1826 | 98.9595% |
| MDW | 23 | 3652 | 8.0230% | 7.1854% | 8.9488% | 1826 | 100.0000% |
| LAX | 0 | 3640 | 98.9286% | 98.5388% | 99.2152% | 1820 | 0.8791% |
| LAX | 1 | 3640 | 98.8462% | 98.4441% | 99.1452% | 1820 | 0.9341% |
| LAX | 2 | 3640 | 98.7912% | 98.3812% | 99.0983% | 1820 | 0.9341% |
| LAX | 3 | 3640 | 98.7088% | 98.2873% | 99.0276% | 1820 | 1.0440% |
| LAX | 4 | 3640 | 98.6538% | 98.2249% | 98.9802% | 1820 | 1.0989% |
| LAX | 5 | 3640 | 98.5440% | 98.1005% | 98.8851% | 1820 | 1.2088% |
| LAX | 6 | 3638 | 98.4882% | 98.0374% | 98.8366% | 1819 | 1.2644% |
| LAX | 7 | 3640 | 98.1044% | 97.6080% | 98.4994% | 1820 | 1.4835% |
| LAX | 8 | 3640 | 93.8187% | 92.9892% | 94.5558% | 1820 | 4.6154% |
| LAX | 9 | 3640 | 81.2637% | 79.9634% | 82.4982% | 1820 | 16.4286% |
| LAX | 10 | 3640 | 60.2473% | 58.6474% | 61.8255% | 1820 | 38.9011% |
| LAX | 11 | 3636 | 38.1738% | 36.6080% | 39.7646% | 1818 | 64.8515% |
| LAX | 12 | 3638 | 24.1341% | 22.7714% | 25.5514% | 1819 | 84.3321% |
| LAX | 13 | 3636 | 17.7118% | 16.5051% | 18.9866% | 1818 | 94.3894% |
| LAX | 14 | 3640 | 15.3571% | 14.2225% | 16.5649% | 1820 | 98.1319% |
| LAX | 15 | 3638 | 14.8708% | 13.7517% | 16.0640% | 1819 | 98.8455% |
| LAX | 16 | 3640 | 14.5604% | 13.4520% | 15.7436% | 1820 | 99.2308% |
| **LAX** | **17** | 3638 | 14.4860% | 13.3797% | 15.6671% | 1819 | 99.3953% |
| LAX | 18 | 3638 | 14.3760% | 13.2735% | 15.5537% | 1819 | 99.5052% |
| LAX | 19 | 3636 | 14.2189% | 13.1215% | 15.3919% | 1818 | 99.6700% |
| LAX | 20 | 3640 | 14.1484% | 13.0539% | 15.3184% | 1820 | 99.7802% |
| LAX | 21 | 3640 | 14.0659% | 12.9743% | 15.2333% | 1820 | 99.8901% |
| LAX | 22 | 3640 | 14.0385% | 12.9478% | 15.2049% | 1820 | 99.9451% |
| LAX | 23 | 3640 | 14.0110% | 12.9213% | 15.1766% | 1820 | 100.0000% |

**Reading the table**: at hour 0, `P(win | setup)` is 87-99% (station-
dependent) while `P(R_h == R_23)` is only 1-10% -- the day is not over, and
"win" mostly means ordinary diurnal warming reached the strike. Both curves
move together and flatten around hour 16-17, where `P(R_h == R_23)` has
saturated to 95-100% and `P(win | setup)` has settled onto its stable floor
(bold rows mark hour 17, the registered admissibility floor). The pooled
53% headline in the challenged study was an average dominated by the
early-hour, pre-convergence cells.

## Registered admissibility rule

`is_admissible_hour(hour) = hour >= 17`
(`cli_basis_hourly_profile_study.ADMISSIBLE_HOUR_FLOOR`), reusing
`cli_basis_boundary_study.STUDY_HOURS[0]` rather than re-deriving it, so this
corrected number sits on the same window the already-PASSED boundary study
measured. See `pre_registration_2026-09-02T061500Z.md` for the full
candidate comparison: a realized-peak-based rule was explicitly REJECTED as
un-implementable live (lookahead); a stall-length live proxy was recorded as
a legitimate future refinement, not adopted here.

## Corrected `P(win | setup)`, `h >= 17`, margins {1, 2} pooled

| Station | n | k | Wilson 95% lower | Wilson 95% upper |
|---|---:|---:|---:|---:|
| LAX | 25,472 | 3,615 | 0.1377 | 0.1463 |
| MIA | 25,370 | 3,404 | 0.1300 | 0.1384 |
| SFO | 25,184 | 3,048 | 0.1171 | 0.1251 |
| MDW | 25,564 | 2,461 | 0.0927 | 0.0999 |

## Pooled (4 dense stations, h >= 17)

n = 101,590, k = 12,528, Wilson 95% lower = 0.1213, Wilson 95% upper = 0.1254

**PASS.** Pooled `n` clears `n >= 100` by three orders of magnitude. The
pooled Wilson 95% lower bound (0.1213) clears the 0.06285 break-even by
~1.9x -- not the ~8.4x the challenged pooled figure claimed, but still a
genuine clearance. Every station clears independently; MDW is the weakest
at 0.0927, still ~1.5x break-even.

**This is a real correction, not a cosmetic one: the corrected pooled lower
bound (0.1213) is roughly 4.4x SMALLER than the challenged study's (0.5284).**
The number does not fall below break-even, so this does not by itself kill
the family -- but the challenge was right that the original figure was
inflated by roughly the factor it named, and a sizing decision built on
0.53 rather than 0.12 would have been wrong by the same factor.

## What this does and does not establish (unchanged from the challenged study)

Same caveat as before, restated: this measures whether the bet is good
GIVEN a setup occurs at an admissible hour, never whether the venue offers
it. See Task 2 below (adverse selection) and the offer-gate scan's own
unchanged `n >= 50` availability gate, still the binding constraint.

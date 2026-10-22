# P2 r1 review — Grok (meteorology / verification)

I'll review the plan read-only against the code and the two evidence notes, and check each factual claim before judging fairness, thresholds, and what to cut.The Murphy identity checks out. Next I’ll pin the forecast path, the calibration window, and the on-disk stores the plan treats as fixed.**VERDICT = REQUEST-CHANGES**

The paired resolution difference is the right statistic. This draft is not yet a fair deletion test.

Checked and true: `PNoStore` reads only 13Z and 19Z of D−1 and 01Z of D, first MAX column (`pno_store.py:147`, `:150–153`); `site()` refuses NYC (`:49`, `:128–130`); `VectorChain.at` keeps `available_at_ns ≤ t` (`:286–288`); `LiveCalibration.resolve` adds the day-length correction (`calibration_artefact.py:152–165`) and `ladder_p_yes` averages the draws. Artefact sha `9c0b6d6e…` matches; `recalibration=none`, correction `linear_lst_day_length`, `cdf_method=normal`. The fit window 2021-01-01..2026-06-30 is `DEFAULT_SPLITS` (`nbp_calibration.py:273–278`), not a field in the JSON. Derived NBP files end at `nbp_20261012_19z`. Truth CSV runs through 2026-10-21; `rung_outcome` is inclusive `lo ≤ tmax ≤ hi` (`market_calibration_scan.py:213–217`). `BS = REL − RES + UNC + W − C` is exact (`brier_decomposition.py:39`, `:155–164`); 0.13200 = 0.00865 − 0.01554 + 0.13889 against the ask-forecast Brier 0.13090. Seed 20260929, B=2000, 10 equal-width bins (`nbp_calibration.py:450–451`, `:2004`).

**Required changes**

1. Drop instant (b), or STOP. The cited METAR `2026.csv` files end 2026-06-30 for KLAX, KMDW, KMIA and KSFO, and `read_routine_metar` refuses any window past 2026-07-01 (`metar_routine_store.py:10–13`; `HOLDOUT_START` in `metar_routine_minute_probe.py:122`). The score window starts about 2026-08-30, and the plan forbids a fetch. As written, (b) is empty and lines 77–78 still let (a) alone FAIL.
2. A CI lower bound below +0.005 is not a negative result. The 09-20 ask interval was about 0.028 wide at 64 clusters (`RULING_forecast_edge_programme_closes_2026-09-20.md:44–45`), so this bar deletes an underpowered test. FQ v1 trades D+1 only (`decision.py:251–280`; `composition.py:86–93`); D0 09:00 LST gives the mid morning observations the D+1 market did not have. Report D and the CI. Do not delete, and do not list the analysis scripts (plan lines 85–90) as the taker.
3. The book rule is not WP-7b. `first_liftable_at_or_after` (`wp7b_market_as_forecaster.py:232–248`) has no 10-minute cap and accepts a one-sided ask; `decision_instant_ns` is 09:00 civil local, DST-aware (`forecast_cheap_screen_wp7.py:248–257`). Pin 09:00 LST, first two-sided L0 in that same snapshot, within 10 minutes, else drop the rung.

Instant (a) is the same events and has no look-ahead, but the unconditioned forecast is not the mid’s information set. That handicap is acceptable only once deletion is off the table. The (b) formula — renormalize on T≥R, score only live rungs, clock at receipt = observation + 10 min (`running_extreme.py:7–11`) — is the right conditional question, and only on days that actually cross a rung. It is a selected subset, so it must not be a second PASS bite, and it needs an obs source inside the window.

**Cut:** the live-parity log replay, the 5-bin sensitivity, mean |p−mid| versus 0.021, fee plus half-spread, the full-partition subset, the synthetic positive control, and the systemd/mtime watch. Keep the sha pin, the identity check, the null `p = mid` check, and `min(day) > 2026-06-30`.

**Confidence: 84.**

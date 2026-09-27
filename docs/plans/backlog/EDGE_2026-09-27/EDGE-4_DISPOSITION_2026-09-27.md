# EDGE-4 disposition: FOLDED into AUD-18a, not built (2026-09-27)

The r1 plan is `EDGE-4_live_feed_calibration_parity_plan_r1_2026-09-27.md`. It was reviewed by the architect (REJECT as a standalone build; fold into AUD-18 §6.3), python (REQUEST_CHANGES) and domain (REQUEST_CHANGES). All three reviews point to the same outcome, so no r2 is written.

## Why it is not built
1. **The plan measured against the wrong bar.** The binding bar for this hypothesis class is `H-ARCHIVE-RECAL-2026-09` (`pm_us_crh_v4_archive_recalibration`, k_variants=1). It requires `min_station_days=600`, pooled, and counts confirmatory draws only if they fall strictly after the freeze commit on 2026-09-25. Sources: `docs/evidence/RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md` and `AUD-18a_register_archive_recal_plan_r1_2026-09-26.md`. The r1 plan instead counted 87 rows against the per-cell N_MIN=90. Under the correct bar, PARKED is the only possible result for months.
2. **The corpus is frozen.** The decision tape holds only 09-16/17 and 09-19..23, about 20 station-days at most. It stopped growing when the A1 halt was set. Any rebuild has to replay quote tape plus obs (the AUD-09a corpus), not decision JSONL.
3. **Running it would spend confirmatory days (binding).** The SEARCH/CONFIRM firewall binds on the *corpus*, not on the statistic (ruling §0). Computing any statistic over post-2026-09-25 tape station-days reclassifies those days as SEARCH and pushes the 600-day confirmatory bar further out.
4. **Design defects that must be fixed if it is revived:**
   - the module must live in `breezy.analysis`, not `breezy.domain`;
   - the proposed import-linter contract references a non-module in `scripts/`;
   - there is no ladder source;
   - the counts are row counts, not station-day clusters;
   - the tests do not check `ref.ts < take.ts` leakage or date+hour scoping;
   - the study slice, flock and MemoryMax are missing;
   - two citations are fabricated or mis-attributed (`mb_current_rung_edge_study.py` "≤800 lines"; `finals_by_city` location).

## What carries forward
- **A binding rule for every EDGE/AUD-18 study:** no exploratory statistic may read tape station-days after the 2026-09-25 freeze unless that corpus is explicitly declared SEARCH for H-ARCHIVE-RECAL-2026-09, with the cost recorded in both plans.
- **A settled fact (T0 resolved):** `running_max_lower/upper` are populated on every offer-tape row, refused rows included (`continuous_strategy.py:2231-2266`). The only null rows are `exit_refused:family_not_exit_registered` position-monitor rows from 09-21.
- **Revival trigger, owned by AUD-18a/`hypothesis_triage.py`:** post-freeze confirmatory station-days for H-ARCHIVE-RECAL-2026-09 reach at least 50% of 600. At that point, re-plan within AUD-18 §6.3 using the replay corpus, with the defects above fixed.
- **Refusal-rate observability:** the existing digest already reports refusals by reason (`decision_funnel_daily_digest.py:280-351`). No new build is needed.

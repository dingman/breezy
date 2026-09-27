# RA-13-FW: post-freeze tape firewall audit (2026-09-27)

**Authority:** `RULING_RA-13_programme_kill_2026-09-27.md` §7 B-7.
**Auditor:** prediction-market-reviewer, working blind and read-only.
**Firewall:** the README binding rule at `README.md:18` and `EDGE-4_DISPOSITION_2026-09-27.md:15` bind the corpus, not the statistic. Outcome-blind counts count (RA-13 B-3).

## Result: CLEAN on both named items

| Item | Reads post-freeze tape? | Standing |
|---|---|---|
| AUD-05 v4 tally (`family_tally_v2.py`, `live_family_tally.py`, `family-tally-v2-run.sh:379-457`) | NO. There is no catalog import; it reads a counter JSON and the exec-state sqlite. | Clean |
| AUD-07 m1c sweep (`aud07_live_rule_crossing_sim.py:36-44`, `aud06a_qty_envelope_sweep.py`) | NO. It is a synthetic Monte Carlo (`random.Random` / `default_rng`) with no real corpus. | Clean |
| AUD-09a census (`replay_sufficiency_census.py:130,388-405`) | YES. It computes an outcome-blind sufficiency statistic. | Carved out: it is the sanctioned EDGE-4 revival counter (`RULING_RA-13:26`, `EDGE-4_DISPOSITION:21`) |
| replay-daily (`breezy-replay-daily.service:14-16`) | YES. It runs in MECHANISM_ONLY mode and can never feed a live decision. | Carved out (`RULING_RA-13:26`) |
| hypothesis_triage (`breezy-hypothesis-triage.service:7`) | NO. It does no tape scan and consumes the census and replay outputs. | Clean |
| portfolio-ROI / funnel digest / position-monitor report / score-live-trials | NO. There is no catalog or Depth10 import. The digest reads decision-log JSONL. | Clean |
| **exit-window study** (`current_rung_hold_exit_window_study.py`, `breezy-exit-window-study.service` 15:20Z) | YES. It reads catalog Depth10 rows for the exit windows of filled live positions. | **Not covered by any prior ruling.** See the coordinator ruling below. |

No SEARCH cost is incurred by AUD-05 or AUD-07.

## Coordinator ruling on the exit-window study (decided under the standing grant; conservative)

1. **What it measures.** The study's estimand is exit mechanics per live fill, meaning when to sell identified losers (the operator ruling of 2026-09-16). That is not H-ARCHIVE-RECAL's entry-side estimand.
2. **Its output is barred.** Output from this study may never be cited toward any H-ARCHIVE-RECAL verdict, or toward any other registered hypothesis's CONFIRM leg.
3. **Station-days count as SEARCH.** Every post-freeze station-day whose Depth10 rows the study reads is **declared SEARCH, meaning forfeited for CONFIRM**. This is conservative: it can only shrink the CONFIRM corpus, never contaminate it.
   - While the A1 halt is SET, no new fills occur. The study then touches only exit windows of fills made on or before 2026-09-24 [INFERRED: those windows close by settlement, roughly 2026-09-25].
   - **RA-13-FW2 VERIFIED (coordinator, 2026-09-27):** the latest run that wrote output was `derived/exit_window_study/2026-09-25_nightly/`, covering 8 positions. The newest date anywhere in its output is **2026-09-22**, which is before the freeze. The 09-26 15:20Z run was SKIPPED (the studies lock was held).
   - **Forfeiture to date: 0 post-freeze station-days.** The SEARCH declaration applies from the first run that reads a climate day of 2026-09-26 or later. That happens only after new fills, which require the A1 halt to be cleared.
4. **The study keeps running.** It is the evidence base for the UNARMED exit seam.

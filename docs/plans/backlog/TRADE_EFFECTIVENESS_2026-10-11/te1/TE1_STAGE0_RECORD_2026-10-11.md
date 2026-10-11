# TE-1 Stage 0 record (2026-10-11, prediction-market-reviewer, read-only)

Verdict: **STOP at S0-2** (5/25 FQ fills, climate day 2026-10-06, do not bridge: `deploy/families/pm_us_crh_fq_v1.json` terminal_climate_day=2026-10-05, cebaab49; `attribution._bridge_family` attribution.py:209-236 rejects). Plan r3.4 delta owed.

```
S0-1  n=34 BUY qty1; cost 6.3600; fee 0.2700; TOTAL 4 wins / -2.63
      SEP 9/2/-0.46 | FQ 25/2/-2.17 (wins MIA 10-03 gte86lt87 +0.88; MIA 10-05 gte89lt90 +0.50)
      NO 3/1/+0.65 (MDW 09-22 +0.87) | YES 31/3/-3.28 | n_undecodable=0
S0-2  STOP: bridge 20/25; latch keys 25/25; misses = SFO 81_82, MDW lt_69, MDW 70_71, LAX lt_91, SFO 83_84 (climate_day 2026-10-06)
S0-3  21 station-days; all final; correction_flag false; superseded false
S0-4  FQ fee_reconciled 25/25; unreconciled non-FQ = SFO 2026-09-11, MIA 2026-09-13 (RESIDUAL)
S0-5  buckets 7 SCORED / 2 RESIDUAL; tmax AGREE 9/9; SCORED -0.54; RESIDUAL +0.08; crh -0.46
      whole-store total_realised_pnl_all_settled = -0.5400 == SCORED sum: TRUE (WP-B uses equal-totals form)
      scored trials with no ledger fill: NONE
      controls: MIA 09-13 YES +0.30 WIN (tmax 92); MIA 09-15 NO -0.09 LOSS (tmax 93)
      trial-id: 9/9 agree; SFO 09-11 latch row has null venueOrderId -> legacy_join must join by instrument_id/day
S0-7  plain=FAIL (25/25 lagging); R4=PASS (simulated; R4 not built); k=25
S0-8  no wiring yet; FqFillInput.venue_settlement_tmax_f defaults None (fq_scorer.py:105); re-check after WP-A
S0-9  all patterns as expected; extra in-scope hits for breezy-autonomy-failed@: service:2, promote/README.md:6, test_aut2_units_deploy.py:37,135
S0-11 source exec/polymarket_us/intent/history + resolver/*; SFO 09-05 ac87b697 OPERATOR_CLEARED; MIA 09-23 5e50e0d9 ZERO_FILL_TERMINAL;
      +3 zero-fill (SFO 10-02, MDW 10-03, MIA 10-04); n_no_fill_intents=5; strict n_ambiguous_no_fill=UNKNOWN
S0-12 P36 families (manifests + BOOTSTRAP_SEED; registry dir empty); n=25 only if the 10-06 fills get kind FQ, else 20
```
Scratch evidence: session scratchpad te1-s0/main.out.

## S0-2b (coordinator, read-only git, 2026-10-11 ~20:05Z) — PASS
- `git show -s --format=%cI cebaab49` = 2026-10-06T01:42:30Z.
- `4ba7f10cd1f6:deploy/families/pm_us_crh_fq_v1.json` sha256 8e1217fd2037ca4e… (= logged boot manifest), 0 `terminal_climate_day` keys.
- Fill ts_event (UTC): SFO gte81lt82 10-05T16:50:50Z; MDW lt70 16:51:00Z; MDW gte70lt71 16:51:15Z; LAX lt92 16:51:19Z; SFO gte83lt84 19:31:03Z — all < 2026-10-06T00:00Z.

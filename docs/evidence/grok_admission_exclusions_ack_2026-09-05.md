# Strategy-lead acknowledgement — two new fill-admission exclusions + the v1 stop window (2026-09-05)

**Provenance.** Grok CLI (grok-build bridge 0.2.1, `--sandbox read-only`, cwd = repo),
brief in the coordinator's scratchpad (`grok_task.txt`), stdout verbatim below with
tool chatter removed. Read-only ruling; no file edited, no bot run. Governing texts
cited by Grok: PREREG v1 §4/§6, PREREG v2 §8/§13, `grok_v2_registration_ack_2026-09-05.md`
C3, `docs/core/LESSONS.md` L-25, A13, `_admit_fill` in `scripts/analysis/score_live_trials.py`.

## Ruling (verbatim)

**Q1.** E1 is the live counterpart of L-25, not a v1 scoring change. `score_trial` / 17-col
`ScoredTrial.excluded_reason` stay untouched (`excluded_reason` is the venue-fallback stamp).
Widen driver-local `_admit_fill` only: `fill_px < entry_ask − Decimal("0.01")` →
`fill_below_ask` before `score_trial`. Equality at `entry_ask − 0.01` is admitted. `0.01` is
the observed PM.us `orderPriceMinTickSize`, not a Kalshi/generic tick. Paper replay keeps
zero tolerance (`ImpossibleFillPriceError`: same book as the decision). Gate is
outcome-independent (fill record + latch only). Adverse `fill_px > entry_ask` is scored
(v1 §4 slippage column; pessimistic, never inflates ROI).
**ACKNOWLEDGE**

**Q2.** Unattested fee cannot enter `pnl = 1{held} − fill_px − fee` (A13: no computed fee
wearing venue grammar; L-25: fee of zero on a real fill is a bug). Same `_admit_fill` layer
as Q1: `fee_reconciled=False` → `fee_unverified`; JSONL default `True` is fixture-only;
live `--fill-source` passes the durable flag and never defaults it. Re-admission is only a
venue-sourced `record_fill` cumulative UPDATE (same `venue_order_id`) that independently
satisfies both identities (Σ fill-type `lastShares` = `cumQuantity` AND order total =
per-leg fill-type sum). Scorer/operator never patch `feeReconciled`. Coverage table uses
the latest durable record per `venue_order_id` (append-only jsonl is evidence, not the
count). Until that snapshot exists, fail closed. Halt latch is independent of scoring.
**ACKNOWLEDGE**

**Q3.** v1 §4 identity is `score_trials(pairs)`: `len(scored)+len(refused)==len(pairs)`.
E1/E2 never become pairs, matching Q1's `partial_fill`/`multi_fill` placement. They are not
`ScoreRefusal`s and not `ScoredTrial` rows. C3: 𝒜={i: q_i=1} and now also E1/E2-clean;
while excluded, Δn=Δk=ΔI=ΔS=0; coverage table by reason/station/climate_day.
Re-admission (Q2) is a later attested trial entering 𝒜, not a silent statistic edit.
v1 tally code unmodified.
**ACKNOWLEDGE**

**Q4.** One window start: `d0_climate_day = 2026-09-05` (v1 §6 earliest D0; v2 manifest
`pm_us_crh_v2.json` REGISTERED — the only machine-readable pin; do not author
`pm_us_crh_v1.json`). Structural-dead numerator (`--fill-since-climate-day`) and
denominator (`--fetch-start`) take that same string; never `ASOS_FETCH_START=2026-08-30`.
09-04 shakedown (refusals only) is in neither — including it in the denominator only
would manufacture a faster KILL. Scorer `since_climate_day=d0` so pre-D0 live rows are
never written; v1 Wilson and v2 sequential therefore see the same admitted live set (zero
fills to date, so v2 §8 "pre-D0 is v1-only" is vacuous). v2 whole-tally guards (provenance
sidecar, `held==(pnl>0)`) stay v2-only as registered.
**ACKNOWLEDGE**

RULING: Q1–Q4 ACKNOWLEDGE; E1/E2 are driver-local pre-scoring exclusions; v1 §4 / tally
unmodified; D0=2026-09-05 is the single structural-dead window; `allow_short=False` and
NO-SEND stand.

## Coordinator dispositions (carried into the plan, Rev 4+)

- Q2 re-admission: no record-update path exists today (`record_fill` writes once per
  `venue_order_id`); a re-admission mechanism is I4 territory and is NOT built here. Until
  then a `fee_unverified` fill stays excluded and visible. Nothing patches `feeReconciled`.
- Q2 coverage count: the v2 coverage table (I3c) counts ONE entry per `venue_order_id`
  (latest line by `scored_run_utc`) and drops any exclusion whose `trial_id` has a scored
  row in the store — a later attested trial leaves the exclusion count automatically.
- Q4 scorer window: the scoring wrapper passes `since_climate_day = d0` from the v2
  manifest to the scorer as well as to both v1 stop flags — three consumers, one string.

# AUD-11 review (round 2, mle-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
sha256: 3d687c044dec146fa9980c26e680071c0bdc03e8c8473af83fb2612812b18314
Round: 2
Reviewer: mle-reviewer (backtesting / statistical-validation lens)

## Round-1 defect disposition (verified, not just read from §13)

- MATERIAL (already-consumed-artefact question) — FIX VERIFIED IN BODY, not
  just claimed. §2 new bullet and §12 "Resolved this round" quote
  `docs/evidence/grok_forecast_family_verdict_2026-09-02.md` verbatim:
  "Existing backtests use a synthetic snapshot. Those numbers are void twice:
  wrong sigma, and no real forecast." I independently opened the verdict file
  and CONFIRM this exact sentence exists (line 38 of that doc, inside the
  brief-answer body). The plan's companion claim — the verdict's T-11 pin
  example cites `test_forecast_sigma_uses_issuance_lead.py` (a unit test),
  not this script's numeric output — also CONFIRMED (verdict line 19: "T-11
  pin (verified in `test_forecast_sigma_uses_issuance_lead.py`)"). The
  `_SequenceForecastSource`-is-the-only-non-test-`ForecastSource`-implementer
  claim, sourced to `docs/evidence/grok_armed_validation_2026-09-03.md:53`,
  is also CONFIRMED verbatim ("The only non-test implementer is
  `_SequenceForecastSource` in `scripts/analysis/run_weather_strategy_backtests.py`.").
  The round-1 defect is genuinely closed: the KILL verdict voided this
  script's output on independent, prior grounds and did not rely on its
  (possibly look-ahead-tainted) numbers. Good, careful read-only work.
- MINOR (`ts_init` provenance column) — FIX VERIFIED: §6 item 4 and §8 now
  require a provenance column; §7 step 1 requires classifying it.
- MINOR (data.pyx line-anchor) — FIX VERIFIED: §6 item 1 now cites `:30-49`
  with the correct sub-spans.

No round-1 rejection to re-litigate; both reviewers' defects were accepted
and the fixes are real, not cosmetic.

## Fresh round-2 defect (new, this session, read-only source check)

**MINOR** — §2/§6 item 2/§12 mischaracterise `_load_climate_day_records`'s
current usage. The plan states it is "currently used only to print a 'REAL:'
diagnostic block, not wired into the `BacktestEngine` feed." This is
factually wrong: I read `scripts/analysis/run_weather_strategy_backtests.py`
directly (`_run_live_capture`, lines 1527-1682) and confirmed
`_load_climate_day_records`'s output (`records`, loaded at line 1559) is
converted via `as_backtest_data` into `weather_data` (line 1582) and IS fed
into a live `BacktestEngine` run through `_run_one(..., weather_data=weather_data,
...)` at line 1611-1621, for the `cli_settlement_print_lock` strategy (not
the forecast/weather strategies `main()` restamps). `_run_one` reports real
`orders_submitted`/`fills` from that run, so this is a genuine, already-proven
engine feed, not merely a print statement. The plan's evidence claim is
inaccurate — but the inaccuracy cuts in the plan's OWN favour: it
under-claims how de-risked the proposed re-wiring of `main()` is (there is
already a working precedent of `_load_climate_day_records` + `BacktestEngine`
running cleanly). It does not change the required fix, any acceptance
criterion, or the RED-test plan. Classified MINOR because it is a citation-
accuracy defect that inflates apparent risk rather than concealing it, same
class as round 1's data.pyx line-anchor MINOR.
Required change: correct §2/§6 item 2/§12 to state `_load_climate_day_records`
is already wired into a `BacktestEngine` feed via `_run_live_capture`/`_run_one`
(a different function/strategy than the one this item targets), and cite that
as additional, existing evidence the re-wiring pattern is safe — strengthening,
not weakening, §7 step 4's confidence claim.

No other defect found. The `ts_init`/`ts_event` semantics, the restamp
location (`_restamp_climate_day` at line 784, invoked from `main` at
~line 1772-1780), the existing point-in-time guards
(`_assert_no_foreign_market_data`, `ImpossibleFillPriceError`), and the
`whole_tape_paper_replay.py` `LOOK_AHEAD_CAVEAT`/`mechanism_test_only` design
are all consistent with what this session independently re-read.

## Per-criterion points (out of 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 19/20 — the already-consumed-
  artefact question is now closed with a citable, independently-verified
  finding; survey execution remains deferred to the implementer (unavoidable
  for an evidence-collection-first item).
- Technical correctness and evidence grounding: 18/20 — every load-bearing
  citation this round checked out exactly EXCEPT the `_load_climate_day_records`
  "diagnostic-only" mischaracterisation above (a real, if favourable-to-the-plan,
  inaccuracy).
- Implementation specificity and feasibility: 15/15 — the guard shape, error
  type, and reuse target are concrete; the fresh finding above, if anything,
  makes this stronger than the plan itself claims.
- Acceptance criteria and validation quality: 19/20 — equality-boundary case
  and `ts_init` provenance column are both structural; CI-enforcement question
  is honestly left open by design.
- Autonomous operation, failure handling, recovery: 13/15 — unchanged; "table
  drifts out of date" is a named, accepted, stated limitation.
- Portfolio alignment, scope, dependencies: 9/10 — unchanged, clear
  precondition relationship, no invented ROI number.

**Total: 93/100.**

## Required changes to reach 100

1. Correct the `_load_climate_day_records` usage claim in §2/§6 item 2/§12 to
   note it is already wired into a `BacktestEngine` feed via
   `_run_live_capture`/`_run_one` (the print-lock strategy), not merely a
   diagnostic print — and use that as additional evidence for §7 step 4's
   confidence claim rather than an unexamined "described but not pre-written"
   risk.

No other change required.

## Blockers

None requiring an operator/strategy-lead ruling. The one fresh defect is a
citation-accuracy correction within existing build authority.

## Score

93/100 — APPROVE WITH WARNINGS. Round-1 defects genuinely fixed in the plan
body (verified independently, not merely trusted from §13). One new MINOR
citation-accuracy defect found this round; it does not block the guard
mechanism, the RED-test plan, or any acceptance criterion.

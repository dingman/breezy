# AUD-11 — Round 1 — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
SHA256: 61c137589dc2216640023d012c0c22bd3cba229e26ee13d5bc5dee80e89d434d
Round: 1
Reviewer: prediction-market-reviewer (independent, blind)
Lens: prediction-market mechanics — point-in-time discipline for fills/edge inputs.

## Claims verified

- `run_weather_strategy_backtests.py`'s restamp — CONFIRMED. `_restamp_climate_day`
  (line 784) is called from `main` (invocation at line ~1780,
  `restamped_ns = tape_start_ns - _ONE_SECOND_NS`), matching the plan's
  description exactly ("CONSTRUCTED: restamping {station} NwsClimateDay
  retrieved_at_ns {X} -> {restamped_ns}...").
- `is_final=False` gate claim — plausible from the script's own inline comment
  at line ~65-69 ("strategies gate flatten-on-observation on `is_final`
  (`False` here)... restamping has no effect on trading behaviour"); this
  session did not re-derive the strategy-side gate logic itself, so the
  "behavioural coincidence, not a structural guard" framing is accepted on
  the plan's own citation, not independently re-traced through the strategy
  code this round.
- `_assert_no_foreign_market_data` / `ImpossibleFillPriceError` — CONFIRMED to
  exist and do what the plan says (`paper_replay.py:131,228-254`): they gate
  quote/depth/close records against the capture window and refuse a fill
  priced better than `entry_ask`. **Confirms the plan's scoping claim that
  quote/depth-for-fills is ALREADY covered and only weather/forecast records
  are the gap** — this is the correct domain read: fill-price point-in-time
  discipline (the CRITICAL "No-Lookahead Bias" concern for cost/edge
  computation) is not being left open by this plan; it is being correctly
  left alone because it is already enforced elsewhere.
- `ts_init` vs `ts_event` semantics — CONFIRMED against
  `nws_raw_product.py:206-209` and the plan's Nautilus citation is consistent
  with `ts_init` as "ingestion/availability instant".
- `whole_tape_paper_replay.py` `LOOK_AHEAD_CAVEAT` — not independently
  re-opened this round (file not read); plan's own citation is internally
  consistent with `ladder_ev_peer_review_2026-09-07.md`'s "MECHANISM TEST —
  NO VERDICT" framing, which this session did not re-verify.

## Defects

**MINOR** — §6 item 2 / §7 step 4 do not mention that the same file already
contains a non-restamping loader, `_load_climate_day_records` (line 1349,
docstring: "at its REAL ts_init... NOT restamped"), currently used only to
print a "REAL:" diagnostic block, not wired into the engine feed. This is the
exact function option (i) asks the implementer to build. Citing and reusing
it (rather than writing new record-construction code) is lower-risk and
should be named explicitly in the implementation step — a specificity
improvement, not a defect in the plan's direction.

**MINOR** — the guard's stated rule (`ts_init > decision_ts_init_ns` raises)
is directionally correct but the plan never states the boundary behaviour at
equality; trivial to add as a one-line RED-test assertion in step 2.

No MATERIAL defect found in this plan's point-in-time-guard design, scope, or
exclusions. The scope boundary (leave `whole_tape_paper_replay.py`'s scoring
rule and quote/depth guards untouched; only weather/forecast restamping and
an unclassified-script survey are new work) matches what the codebase
actually needs — the CRITICAL no-lookahead risk in a bot whose backtest
output is the only evidence path to promotion is correctly triaged.

## Per-criterion points

- Fidelity to audit gap and completeness: 17/20 — survey-first is
  appropriate for an UNVERIFIED gap; true count of affected scripts unknown
  at plan time (author's own honest deduction, confirmed reasonable).
- Technical correctness and evidence grounding: 19/20 — every load-bearing
  claim checked this round matched the artefact exactly; small deduction for
  not naming the existing REAL-ts_init loader.
- Implementation specificity and feasibility: 13/15 — concrete; slightly
  understates how cheap the fix already is (see MINOR above).
- Acceptance criteria and validation quality: 17/20 — RED-first, tied to two
  real defect instances; CI-enforcement question honestly left open.
- Autonomous operation, failure handling, recovery: 13/15 — correctly
  offline-only, no runtime blast radius.
- Portfolio alignment, scope, dependencies: 9/10 — clean precondition
  relationship to POST_FORECAST_PHASE's C2/A1(iii).

**Total: 88/100.**

## Required changes to reach 100

- Name `_load_climate_day_records` as the reusable REAL-ts_init source when
  wiring §6 item 2's fix.
- Add an equality-boundary RED-test case for the guard.

## Blockers

None. This item requires no operator/strategy-lead ruling; it is read-only
survey plus a native, in-scope code/test fix.

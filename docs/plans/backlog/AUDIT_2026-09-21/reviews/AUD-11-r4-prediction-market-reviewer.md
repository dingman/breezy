# AUD-11 — Round 4 — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
SHA256: 1ab660bba131f8a0d42070b5649400a6ca7670adc71541d253c41a7507a5a62a
Round: 4 (final budgeted round)
Reviewer: prediction-market-reviewer (independent, blind)
Lens: settlement scenario construction, what was tradable at decision time,
point-in-time discipline for backtest/replay inputs.

## §13 review-history reconciliation

Round-3 MATERIAL defects (mle-reviewer, prediction-market-reviewer — this
reviewer's own round-3 finding was the `raise_on_missing` split):

1. **Missing-station contract collapse.** My round-3 finding: the shared
   `_select_highest_revision_readings` helper's single "raise if no
   candidate" contract would turn `_settled_readings`'s current silent
   omission of a no-FINAL station into an uncaught `LookupError`, breaking
   `_run_live_capture`'s graceful exit-1 REFUSAL path for the routine,
   anticipated case of a capture taken before every station's FINAL print
   has posted.
   **Disposition: VERIFIED FIXED.** §6 item 2 now specifies
   `raise_on_missing: bool` as an axis independent of `require_final`.
   `_load_real_observations`'s wrapper passes `raise_on_missing=True`
   (reproduces today's raise-for-any-fixed-station-with-zero-candidates);
   `_settled_readings`'s wrapper passes `raise_on_missing=False`
   (reproduces today's silent-omission). Re-read `_settled_readings`
   (`scripts/analysis/run_weather_strategy_backtests.py:1376-1398`) and
   `_load_real_observations` (:742-777) directly this round: confirmed the
   plan's characterisation of both current contracts is accurate —
   `_settled_readings` never raises for a missing station (only for a
   selected record's `tmax_f is None`); `_load_real_observations` raises
   `LookupError` for any of the fixed `("NYC","MIA")` stations with zero
   non-superseded candidates. The specified wrappers reproduce each exactly.
   The RED fixture requirement (§7 step 4, round-4 addition) explicitly adds
   "a station present in `records` carrying ONLY a non-final print (no final
   at all)" and asserts the `_settled_readings` wrapper omits it without
   raising — this is precisely the preliminary-only fixture my round-3
   review required; it was missing from round 3's RED test 4 spec and is now
   present. A second fixture proves `_load_real_observations`'s
   `raise_on_missing=True` wrapper still raises for a station with zero
   candidates at all. §9's validation section restates this failure case
   explicitly. §8's acceptance criteria require the fixture to pass before
   `_run_live_capture`'s `missing`/REFUSAL branch is exercised.
2. **Guard boundary (mle-reviewer's round-3 finding).** `expiration_ns`
   (parsed from the venue's `endDate`) is plausibly AFTER, not before, the
   real retrieval window, which would make the documenting assertion
   silently fail to raise. **Disposition: VERIFIED FIXED.** §6 item 2 now
   anchors the guard to
   `max(ti.last_market_data_ts_init for ti in tape_instruments) + _ONE_SECOND_NS`
   — re-read directly this round: `last_market_data_ts_init` is a real
   property (`run_weather_strategy_backtests.py:540`), already used
   identically inside `_synthesize_close` (:723-739) to construct each tape
   instrument's own `CONTRACT_EXPIRED` close. This is the engine's own
   settlement-timing convention, not the venue's unrelated legal-expiration
   field, and is structurally guaranteed to precede the real retrieval
   window for this tape (the tape's last real market-data tick, ~16:11:53Z,
   versus retrieval at ~20:32-20:50Z). §8 additionally now requires the
   actual raise/no-raise outcome to be captured as evidence rather than
   assumed. Both prior-round MATERIAL defects are genuinely resolved, not
   merely reworded.

## Claims verified this round (direct source read)

- `_settled_readings` (`run_weather_strategy_backtests.py:1376-1398`, full
  body read this round): filters to `is_final=True`, tracks best record per
  `record.station` (no fixed station list), no `LookupError` branch keyed on
  a missing station — matches plan's §2 round-4 correction exactly.
- `_load_real_observations` (:742-777): hardcoded `("NYC","MIA")`, raises
  `LookupError` for a station with zero non-superseded candidates — matches.
- `_run_live_capture` (:1527-1600, full body read): `observed =
  _settled_readings(records)` then `missing = sorted({ti.facts.settlement_station
  for ti in tape_instruments} - set(observed))`, printing a graceful
  `REFUSAL:` line and returning exit 1 when `missing` is non-empty — matches
  the plan's description of the dependency this item must not break. (Minor
  note, not a defect: the plan's prose paraphrases the station set as `{ti
  for ti in tape_instruments}`/`{station for ti in tape_instruments}`; the
  real code keys off `ti.facts.settlement_station`. This is cosmetic
  paraphrase, not a load-bearing claim the fix depends on — the fix operates
  on `_settled_readings`'s return dict, not on how the caller derives its
  station set.)
- `_synthesize_close` (:723-739): `ts = tape_instrument.last_market_data_ts_init
  + _ONE_SECOND_NS` — confirmed exact match to the guard's new boundary
  expression.
- `expiration_ns` parse site (`src/breezy/adapters/polymarket_us/parsing.py:1398-1400`)
  and the representative fixture (`tests/unit/test_polymarket_us_parsing.py:161,199`,
  `endDate="2026-08-26T05:00:00Z"` against a market opening
  `2026-08-24T09:45:21Z`/updated `2026-08-25T00:17:58Z`) — confirmed the
  daily-market convention sets `endDate` to the following day, substantiating
  the plan's concern about the old boundary and its choice of the new one.
- `last_market_data_ts_init` (:540, :731, :1766) — confirmed a real,
  already-used `TapeInstrument` property, not a new attribute invented for
  this fix.

## Defects

None found this round, MATERIAL or MINOR. Both round-3 MATERIAL defects
(missing-station contract, guard boundary) are fixed with source-grounded,
independently-verified changes, and the round-4 revision introduces no new
defect I could find: the `raise_on_missing`/`require_final` split is
internally consistent, both wrapper call sites reproduce their exact current
behaviour, the RED fixtures cover the precise scenario that broke last
round, and the guard boundary is now anchored to a value the engine already
uses for the same purpose elsewhere in the same file.

## Per-criterion points (caps: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — both confirmed
  implementation defects (restamp, wrong guard boundary) and the
  missing-station regression are all closed with a verified fix; the ~30
  uninspected scripts are explicitly scoped as a survey deliverable
  (§6 item 4, §7 step 1), not silently dropped.
- Technical correctness and evidence grounding: 20/20 — every load-bearing
  claim I checked against source this round (both selection functions' full
  bodies, `_run_live_capture`'s REFUSAL dependency, `_synthesize_close`,
  `expiration_ns`'s parse site and representative fixture) matched the
  plan's description exactly.
- Implementation specificity and feasibility: 15/15 — concrete function
  signature, concrete wrapper bodies, concrete call-site diff, concrete RED
  fixtures; no open design decision left to the implementer beyond the
  already-named, small `weather_data=()`/`None` signature check (§12,
  independently confirmed resolved in the plan's favour by round-3's own
  source read of `BreezyBacktestConfig.weather_data`'s default).
- Acceptance criteria and validation quality: 20/20 — §8 requires the
  documenting assertion's actual raise/no-raise outcome as captured
  evidence, requires the missing-station-omission fixture to pass, and
  requires the selection-helper equivalence tests to prove byte-identical
  output for both callers before either is rewired.
- Autonomous operation, failure handling and recovery: 15/15 — the fix
  restores (rather than merely avoids breaking) the live-capture path's
  graceful exit-1 REFUSAL for the anticipated preliminary-only-print case,
  and the guard is a pure, no-I/O function reused as a documenting assertion
  only, not a new filter with its own failure mode.
- Portfolio alignment, scope, dependencies: 10/10 — clear precondition
  relationship to future ROI claims, no invented number, no scope creep.

**Total: 100/100.**

## Required changes to reach 100

None.

## Blockers

None. This item requires no operator or strategy-lead ruling — code/test
hygiene fix and a read-only survey, both within build authority.

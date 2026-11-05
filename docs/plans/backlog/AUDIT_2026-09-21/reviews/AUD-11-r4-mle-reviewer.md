# AUD-11 — round 4 review (mle-reviewer)

Plan file: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
SHA256: 1ab660bba131f8a0d42070b5649400a6ca7670adc71541d253c41a7507a5a62a
Round: 4
Reviewer: mle-reviewer (independent, blind to other reviewers)

## Round-3 defect dispositions — verified fixed against source, not §13

1. **Guard boundary (round-3 MATERIAL, both reviewers).** Plan now anchors
   `assert_available_before_decision`'s `decision_ts_init_ns` to
   `max(ti.last_market_data_ts_init for ti in tape_instruments) + _ONE_SECOND_NS`
   instead of `instrument.expiration_ns`. Confirmed against source:
   `_synthesize_close` (`scripts/analysis/run_weather_strategy_backtests.py:723-739`)
   literally computes `ts = tape_instrument.last_market_data_ts_init + _ONE_SECOND_NS`
   — the plan's corrected boundary is exactly this value. `expiration_ns` is
   parsed from `endDate` at `src/breezy/adapters/polymarket_us/parsing.py:1399-1400`
   (confirmed verbatim) and the cited fixture
   (`tests/unit/test_polymarket_us_parsing.py:161,199`, `endDate="2026-08-26T05:00:00Z"`)
   confirms the plan's claim that this convention plausibly falls after the
   real retrieval window — the round-3 concern was real and is now
   structurally avoided rather than argued around. **CONFIRMED FIXED.** §8
   also now requires the actual raise/no-raise outcome for the known tape to
   be captured as evidence rather than assumed — confirmed present.

2. **Shared helper's missing-station contract (round-3 MATERIAL, both
   reviewers).** Plan now specifies `_select_highest_revision_readings(...,
   require_final: bool, raise_on_missing: bool)` as two independent axes.
   Confirmed against source: `_settled_readings`
   (`run_weather_strategy_backtests.py:1376-1398`, re-read in full) filters to
   `is_final=True` and tracks a per-station best record with **no raise
   branch keyed on a missing station** — a station with zero final
   candidates is simply absent from the returned dict. `_run_live_capture`
   (lines 1572-1580, re-read) depends on exactly this: `missing =
   {ti.facts.settlement_station for ti in tape_instruments} - set(observed)`
   then a graceful `"REFUSAL: no FINAL print..."` / exit 1. `_load_real_observations`
   (lines 742-780, re-read) is fixed to `("NYC","MIA")` and raises
   `LookupError` when a station has no non-superseded candidate — a genuinely
   different contract. The plan's `raise_on_missing=True`/`raise_on_missing=False`
   split reproduces both exactly, and §7 step 4's round-4 fixtures test both
   directions. **CONFIRMED FIXED**, no regression to `_run_live_capture`'s
   REFUSAL path.

## Fresh, whole-plan review this round

- `_load_climate_day_records` signature (`weather_catalog_root, *, stations,
  climate_day`) matches every call site the plan specifies verbatim
  (confirmed at `run_weather_strategy_backtests.py:709-731`).
- The restamp call site (`real_observed, real_records =
  _load_real_observations(...)`, the restamp loop, `weather_data =
  as_backtest_data([_restamp_climate_day(...) for record in
  real_records.values()])`) is confirmed at lines ~1762-1780. `real_records`
  has no other use in the file (grepped) — deleting the restamp block cleanly
  removes the only two use sites, no dangling reference.
- `_run_one`'s `weather_data: list[Any]` parameter (not `Optional`, line 889)
  — passing `[]` for the default branch's calls is mechanically fine; the
  plan's "verify at implementation time" hedge on this point is unnecessary
  caution, not a defect.
- `tests/unit/test_runtime_backtest_feed.py`, `tests/contract/test_backtest_harness_stop_gate.py`,
  `tests/integration/test_forecast_edge_backtest.py` (§7 step 8) all exist.
- No LESSONS.md violation, no touch to `assert_settlement_invariants`/
  `_assert_no_foreign_market_data`/`ImpossibleFillPriceError` beyond the
  stated byte-identical routing, no Nautilus modification (guard is a pure
  function over materialised `Data`), no operator-cap value assigned, no
  PREREG semantics change, no `allow_short` touch.

## Defects

**MINOR — exception-aggregation semantics of `assert_available_before_decision`
left unspecified, but the call site's log message implies aggregation.**
§6 item 2 describes catching `LookAheadRecordError` and logging "CONFIRMED: N
climate-day record(s) excluded from the engine feed" — this requires either
(a) the guard collects every violating record before raising one exception
carrying the count, or (b) the call site independently re-filters `records`
for violations to compute N itself, decoupled from the guard's own raise
semantics. §6 item 1's guard spec ("raising `LookAheadRecordError` ... for
any record whose `ts_init` is `>` decision_ts_init_ns") does not say which.
Neither choice threatens correctness or the acceptance criteria (which only
requires the guard to raise, not a specific message shape), but it is a
genuine small design decision left to the implementer.
**Required change:** add one sentence to §6 item 1 or item 2 stating whether
the guard aggregates all violations into one exception (and exposes a count)
or the call site derives N by its own filter over `records` in the `except`
block.

No other defects found. Both round-3 MATERIAL defects are genuinely fixed
against direct source reads (`_synthesize_close`, `expiration_ns`'s parse
site and fixture, `_settled_readings`'s full body, `_run_live_capture`'s
`missing` computation, `_load_real_observations`'s raise branch). The revised
plan does not introduce any new correctness or scope regression.

## Per-criterion points (caps 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — survey, shared guard,
  ineligibility marker, and the actual default-branch fix are all present and
  concretely specified; both round-3 gaps closed.
- Technical correctness and evidence grounding: 20/20 — every load-bearing
  citation checked against source this round (`_synthesize_close`,
  `_settled_readings`, `_load_real_observations`, `_load_climate_day_records`,
  `_run_live_capture`, `parsing.py:1399-1400`, the `endDate` fixture) and all
  confirmed accurate.
- Implementation specificity and feasibility: 14/15 — one MINOR
  exception-aggregation ambiguity (above); everything else (signatures,
  wrapper bodies, call-site wiring, deletion scope) is fully concrete.
- Acceptance criteria and validation quality: 20/20 — RED→GREEN required for
  three test files including the round-4 missing-station fixtures; the
  documenting assertion's actual raise/no-raise outcome must be captured as
  evidence, not assumed; byte-identical refactor proof required.
- Autonomous operation, failure handling, recovery: 15/15 — offline-only, no
  runtime/permit/execution-path change; the preliminary-only-print failure
  case is explicitly covered by a new RED fixture and validation criterion.
- Portfolio objective alignment, scope, dependencies: 10/10 — correctly
  framed as a precondition for every future ROI claim, no invented number.

**Total: 99/100.**

## Blockers

None. This item requires no operator/strategy-lead ruling; it is read-only
survey plus a code/test hygiene fix within build authority.

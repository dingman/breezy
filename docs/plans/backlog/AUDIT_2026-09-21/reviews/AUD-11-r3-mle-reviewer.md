# AUD-11 round-3 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
SHA256: 30fe08d69fbd940836a64194527f0b3c81c7db7661cf576ec600e11f6e881c4b
Round: 3
Reviewer: mle-reviewer

## Round-2 defect disposition check
- Round-2 prediction-market-reviewer MATERIAL defect (`_load_climate_day_records` not
  a drop-in for `main`'s default branch) — CONFIRMED FIXED. §6 item 2 now specifies a
  concrete `_select_highest_revision_readings` extraction, thin wrappers for
  `_load_real_observations`/`_settled_readings`, and an explicit non-feeding of the
  late record into `weather_data`. Verified against source this round (see below).
- Round-2 mle-reviewer MINOR (wrong-subcommand mischaracterisation) — remains fixed,
  §2 now correctly attributes `_load_climate_day_records` to `_run_live_capture`.

## Claims verified against source (this round)
- `_load_real_observations` (line 742): confirmed — hardcoded `("NYC","MIA")`, filters
  `climate_day==CLIMATE_DAY and not is_superseded` per-station via own catalog read,
  `max(key=revision_seq)`, raises `LookupError` on no-candidate or `tmax_f is None`,
  no `is_final` filter → CONFIRMED.
- `_load_climate_day_records` (line 1349): confirmed — flat list, no per-station
  selection, no null check, sorted by `ts_init`, docstring "NOT restamped" →
  CONFIRMED.
- `_run_live_capture` (1527-1682): confirmed — `records = _load_climate_day_records(...)`
  (1559) → `weather_data = as_backtest_data(list(records))` (1582) → fed to `_run_one`
  (1611-1621) for `cli_settlement_print_lock`, a real engine feed, not diagnostic-only
  → CONFIRMED, this round's §2 claim is accurate.
- `main`'s default-branch restamp call site (1772-1780): confirmed byte-for-byte —
  `restamped_ns = tape_start_ns - _ONE_SECOND_NS`, `_restamp_climate_day` applied to
  every `real_records.values()`, fed into `weather_data` at 1779-1781 → CONFIRMED.
- `_settled_readings` (1376): confirmed — filters `is_final` only, tracks best per
  `record.station` (no explicit station list, no "no-candidate" raise — a station
  with zero final records is simply absent from the returned dict, not an error) →
  CONFIRMED, and this is the source of a fresh defect below.
- Tape window ~16:05-16:11 UTC, real observation retrieval ~20:32-20:50 UTC, module
  docstring lines 1-135 read directly → CONFIRMED consistent with plan's §2 narrative.
- `_synthesize_close` (723-739): confirmed `ts = tape_instrument.last_market_data_ts_init + _ONE_SECOND_NS`
  — i.e. the actual last-decision-instant boundary is the tape's last real market-data
  tick + 1s (~16:11:54Z), NOT `instrument.expiration_ns`.
- `instrument.expiration_ns` is parsed from the venue's `endDate` field
  (`src/breezy/adapters/polymarket_us/parsing.py:1399-1400`). A representative fixture
  (`tests/unit/test_polymarket_us_parsing.py:161,199`, `endDate="2026-08-26T05:00:00Z"`)
  shows this daily-market convention sets `endDate` to ~05:00Z the *next* day, i.e.
  hours *after* the ~20:32-20:50Z CLI retrieval window this tape's observations were
  pulled in, not before it.

## Defects

**MATERIAL — the specified "documenting assertion" boundary is very likely the wrong
timestamp and contradicts the plan's own stated expectation (§6 item 2, §7 step 5).**
§6 item 2 specifies:
`assert_available_before_decision(records, decision_ts_init_ns=max(ti.instrument.expiration_ns for ti in tape_instruments), ...)`
and asserts "today it is expected to raise for every record in `records` (their real
`ts_init` is after every instrument's expiration)". But `expiration_ns` is the venue's
`endDate` (contract legal expiration), not the tape's last-decision-instant. Per the
representative fixture above, this venue's daily weather-market `endDate` convention
is set to ~05:00Z the *following* day — i.e. plausibly *after* the ~20:32-20:50Z real
retrieval time of the climate-day records this item is trying to guard. If that holds
for this tape's instruments (not independently confirmed this session — the actual
`endDate` value for this specific 2026-08-30 NYC/MIA tape was not read from the
catalog), the guard as specified will **not raise**, directly contradicting the plan's
own claim and defeating the stated purpose ("converts the previously-implicit
'restamping has no effect on trading behaviour' claim into a structural, machine-
checked fact" — it would instead silently confirm nothing). Worse, the plan's own
text states "the guard's absence-of-raise is itself the signal that such a record is
now a candidate for inclusion in `weather_data`" — meaning a non-raise here would, by
the plan's own stated semantics, flag these records as decision-time-eligible, while
§6 item 2 elsewhere *hardcodes* their omission from `weather_data` regardless. This is
an internal contradiction traceable to a boundary-choice error: the correct boundary
consistent with the plan's own rationale ("there is no honest ts_init at which these
records could be fed into the engine and have any opportunity to influence a decision
in this tape window") is the last real market-data ts_init / synthesized-close ts
(`_synthesize_close`'s `last_market_data_ts_init + _ONE_SECOND_NS`, ~16:11:54Z), not
`expiration_ns`.
**Required change:** either (a) call the guard with
`decision_ts_init_ns=max(ti.last_market_data_ts_init for ti in tape_instruments) + _ONE_SECOND_NS`
(or equivalently the synthesized closes' `ts`), matching the plan's own prose and the
actual point past which no decision can occur on this tape; or (b) if `expiration_ns`
is retained, add a step-1/step-5 requirement to actually read and log the real
`endDate` value for this tape's instruments and confirm which side of the real
`ts_init` it falls on, rather than asserting the outcome as a given. §8's acceptance
criteria currently contain no check that the "documenting assertion" actually raises
(or is confirmed not to) — this must be added so a silently-wrong boundary cannot ship
undetected.

**MATERIAL — the generalised `_select_highest_revision_readings(require_final=True)`
wrapper changes `_settled_readings`'s behaviour for the "no final print at all for a
station" case, which is exactly the scenario the existing REFUSAL branch exists to
handle.** Verified: today, `_settled_readings` silently *omits* a station from its
returned dict when that station has zero `is_final=True` records (no exception) — the
caller (`_run_live_capture`, 1572-1580) then computes `missing = ... - set(observed)`
and prints a graceful `"REFUSAL: no FINAL print for station(s) ..."` before returning
1. §6 item 2 specifies the unified helper as: "raise `LookupError` if no candidate ...
(identical error messages/shape to today's `_load_real_observations` and
`_settled_readings`, so existing tests asserting on those messages stay green)". But
`_load_real_observations` DOES raise on no-candidate and `_settled_readings` does NOT
— these are genuinely different control-flow behaviours for the same input shape, not
just different message text, and a single `require_final`-gated raise-or-not policy
cannot reproduce both. As specified, a station present in `records` but with only
preliminary (non-final) prints would now raise `LookupError` from inside
`_settled_readings`'s new thin wrapper — a crash — instead of the current graceful
REFUSAL print-and-return-1 path. This is exactly the routine, anticipated scenario the
existing code was built to handle gracefully (climate-day data arrives progressively,
preliminary before final), not a rare edge case. No test currently exercises this path
(`grep` for `_settled_readings`/`no FINAL print` in `tests/` finds none), so neither
the plan's RED test 4 (which only tests the case of "a set containing both a
preliminary and a final print", not a set with *zero* finals for a station) nor the
"full existing suite stays green" criterion would catch this regression before it
ships.
**Required change:** the unified helper's "no candidate" behaviour must be
parameterised (or `_settled_readings`'s wrapper must catch and re-derive the previous
silent-omission semantics) so that `require_final=True` with zero final candidates for
a station does NOT raise from within `_settled_readings`'s call — it must reproduce
the exact current behaviour (station absent from the dict, no exception) so
`_run_live_capture`'s existing `missing`/REFUSAL branch is unchanged. Add a RED test
fixture reproducing "records present for a station, none `is_final`" and assert
`_settled_readings` returns a dict without that station's key (not an exception).

**MINOR — §6 item 2's helper contract for `_load_real_observations`'s wrapper drops an
important pre-existing distinction without saying so.** The current
`_load_real_observations` raises `LookupError` per-station only for stations in its
own hardcoded `("NYC","MIA")` loop; the new `_select_highest_revision_readings` is
described generically as operating over "each station in `stations`" — this is
consistent for the `require_final=False`/`_load_real_observations` caller (same
`stations` tuple passed through), so this is not itself a behaviour change; flagged
only because the shared helper's docstring/tests should make explicit that the
"raise on no-candidate" branch is exercised by the `_load_real_observations` path and
deliberately NOT by the `_settled_readings` path once the MATERIAL defect above is
fixed — otherwise a future reader of the shared function could reasonably assume
uniform raise semantics.

## Per-criterion scoring
- Fidelity to audit gap and completeness: 17/20 — the core G-08 fix is now concretely
  specified and no longer a reused-function claim that doesn't hold; the two MATERIAL
  defects above (wrong boundary value, `_settled_readings` behaviour break) sit
  directly in the fix this item exists to deliver, costing 3 points.
- Technical correctness and evidence grounding: 14/20 — most claims re-verified clean
  against source this round (loader bodies, wiring, restamp call site all exact); the
  `expiration_ns`-vs-real-`ts_init` ordering claim ("expected to raise") is very likely
  incorrect per a representative fixture, and the `_settled_readings` unification
  claim ("identical error messages/shape... existing tests stay green") is
  demonstrably false for the no-final-at-all case — both are load-bearing correctness
  claims in the plan's central proposed fix.
- Implementation specificity and feasibility: 12/15 — signatures and call sites remain
  concrete, but the two MATERIAL defects mean an implementer following §6 item 2
  literally would ship either a silently-inert regression assertion or a new crash in
  a previously-graceful refusal path.
- Acceptance criteria and validation quality: 15/20 — §8 has no criterion requiring
  confirmation of whether the documenting assertion actually raises, and RED test 4
  does not cover the zero-final-records-for-a-station case, so both MATERIAL defects
  above could pass every stated acceptance criterion and still ship.
- Autonomous operation, failure handling, recovery: 13/15 — unchanged from round 2;
  no new defect in this dimension specifically.
- Portfolio alignment, scope, dependencies: 9/10 — unchanged, no invented ROI number,
  clear precondition relationship.

**Total: 80/100** (17+14+12+15+13+9)

## Required changes to reach 100
1. Fix the guard boundary in §6 item 2 to use the last real market-data ts_init (or
   the synthesized close ts) instead of `expiration_ns`, or add an explicit step
   confirming the real `endDate` value's ordering relative to the real observation's
   `ts_init` before asserting the outcome; add an acceptance criterion checking which
   state (raise/no-raise) actually occurs.
2. Fix the `_settled_readings` unification so a station with zero final records is
   still silently omitted (not raised), matching current behaviour exactly; add a RED
   test for that specific case.

## Blockers
None requiring an operator/strategy ruling — both required changes are within build
authority (spec-precision fixes to the plan itself before implementation).

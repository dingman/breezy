# AUD-11 — Round 3 — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
SHA256: 30fe08d69fbd940836a64194527f0b3c81c7db7661cf576ec600e11f6e881c4b
Round: 3
Reviewer: prediction-market-reviewer (independent, blind)
Lens: settlement scenario construction, what was tradable at decision time,
point-in-time discipline for backtest/replay inputs.

## §13 review-history reconciliation

- Round-2 MATERIAL (both reviewers): `_load_climate_day_records` is not a
  drop-in fix for `main`'s default branch (different function, different
  return shape than `_load_real_observations`). Plan's §6 item 2 now
  specifies a concrete replacement: extract `_select_highest_revision_readings`,
  rewire the default branch through `_load_climate_day_records` +
  the new helper, and stop feeding the late-arriving record into
  `weather_data` at all. VERIFIED against source this round (see below) —
  the default-branch half of this fix is correct and does resolve the
  round-2 defect. **However**, the SAME §6 item 2 change reaches into
  `_settled_readings` (the function that already, correctly, feeds
  `_run_live_capture`'s live engine run) and changes its semantics in a way
  the plan does not intend and does not test for — see the fresh MATERIAL
  defect below.
- Round-2 MINOR (prediction-market-reviewer): §8's diff-review criterion
  should require `real_observed_by_station` reconstruction review, not just
  restamp-block removal. VERIFIED FIXED: §8 now states this explicitly
  ("(ii) `real_observed_by_station`'s values are byte-identical pre/post-change
  ... the reconstruction path via the new shared helper must be reviewed").

## Claims verified this round (direct source read)

- `_load_real_observations` (scripts/analysis/run_weather_strategy_backtests.py:741-777,
  read this session): hardcoded `("NYC","MIA")`, per-station `max(candidates,
  key=revision_seq)`, raises `LookupError` if a station has **no candidates
  at all** among a FIXED station list, or if the selected record's `tmax_f`
  is `None`. Matches the plan's §2/§6 item 2 description exactly.
- `_load_climate_day_records` (line ~708, read this session): flat
  `list[NwsClimateDay]`, no selection, no per-station dict, docstring "NOT
  restamped." Matches plan's description exactly.
- `_settled_readings` (line ~1376, read this session): **confirmed to
  silently OMIT a station from its output `dict[str, int]` when that
  station has zero `is_final=True` records among the records passed in** —
  it never raises for a missing station, only for a selected record whose
  `tmax_f is None`. This is a DIFFERENT missing-station contract than
  `_load_real_observations`'s (which raises `LookupError` for a station
  absent from a fixed list).
- `_run_live_capture` (line ~1527-1576, read this session): calls
  `observed = _settled_readings(records)`, then explicitly computes
  `missing = sorted({station for ti in tape_instruments} - set(observed))`
  and, if `missing` is non-empty, prints `"REFUSAL: no FINAL print for
  station(s) {missing}..."` and returns exit code 1 — a graceful,
  already-correct refusal path that depends structurally on
  `_settled_readings` never raising for a missing station. This is exactly
  the live, already-proven engine-feed path (`cli_settlement_print_lock`)
  that round 3's own §2/§5 text calls "already correct... reused, not
  modified."
- Default-branch main() call site (lines ~1762-1815, read this session):
  confirmed `real_observed, real_records = _load_real_observations(...)`
  feeds `build_settlement_scenarios(real_observed_by_station=real_observed, ...)`
  (line 1805) and JSON output (`"real_observed_by_station": real_observed`);
  `real_records` is used ONLY by the restamp print block and the
  `weather_data = as_backtest_data([_restamp_climate_day(...) ...])`
  construction — both slated for deletion per §6 item 2 — matching the
  plan's design.
- `BreezyBacktestConfig.weather_data: Sequence[Data] = field(default_factory=tuple)`
  (src/breezy/runtime/backtest_harness.py:416) and `if config.weather_data:
  ... engine.add_data(...)` (line 788) — CONFIRMED an empty tuple/list is
  already accepted with no signature change needed; §12's "assumption, new
  round 3" about `_run_one` accepting empty/`None` `weather_data` is
  resolved in the plan's favour (its own `weather_data: list[Any]` parameter
  already accepts `[]`/`()`  without further change).
- `instrument.expiration_ns` — CONFIRMED an existing, already-used attribute
  (lines 1436, 1556, 1790) — the guard call's `decision_ts_init_ns=max(ti.instrument.expiration_ns
  for ti in tape_instruments)` argument is well-formed against real code.
- `assert_settlement_invariants`/`_assert_no_foreign_market_data`/
  `ImpossibleFillPriceError` — unchanged from rounds 1-2, re-confirmed
  untouched by this revision's diff scope (§5 exclusions).
- No existing test under `tests/` references `_settled_readings` or exercises
  a missing-final-station fixture for `_run_live_capture` (`grep -rn
  "_settled_readings" tests/` returns zero hits) — the "existing tests
  staying green" assurance in §5 cannot, in fact, detect the regression
  described below.

## Defects

**MATERIAL (new, round 3) — §6 item 2's shared helper collapses two
functions with genuinely different missing-station contracts into one,
breaking `_run_live_capture`'s existing REFUSAL path.**
`_select_highest_revision_readings` is specified to, "for each station in
`stations`: filter... select the max by `revision_seq`, **raise `LookupError`
if no candidate**... (identical error messages/shape to today's
`_load_real_observations` **and** `_settled_readings`)." This is incorrect
for `_settled_readings`: today, a station with zero `is_final=True` records
is silently OMITTED from the output dict, never raised — and
`_run_live_capture` depends on exactly that behaviour to compute its own
`missing` set and print a graceful `"REFUSAL: no FINAL print for
station(s)..."` message with exit code 1. Under the plan's proposed thin
wrapper (`_settled_readings` calling the shared helper with
`require_final=True`), a station present in `records` with only a
preliminary (non-final) print — the exact scenario `_run_live_capture`'s own
REFUSAL branch exists to handle, e.g. captured mid-morning before every
station's FINAL has posted — would make the shared helper raise
`LookupError` instead of omitting that station. The `missing` check and its
REFUSAL message become unreachable; an uncaught `LookupError` propagates out
of a live-capture CLI run that round 3's own evidence (§2, corrected this
round) establishes is **already wired into a live, proven `BacktestEngine`
run** with real submitted orders and fills — i.e. this defect risks breaking
the one already-correct path this item explicitly promises not to modify
except by a "byte-identical-output refactor." §7 step 4's RED test 4, as
specified, does not catch this: it constructs "a set containing both a
preliminary and a final print" for `require_final=True`, which never
exercises the missing-final-entirely case where the two functions'
contracts diverge. §5's "existing tests staying green" assurance is also
false comfort here — no test in the repo currently exercises
`_settled_readings`'s missing-station path (confirmed via grep), so nothing
would catch this at implementation time short of a live-capture run against
a real partial-final tape.

**Required change:** give the shared helper a parameter that separates "no
FINAL among candidates" handling from "no candidate at all," e.g. a
`raise_on_missing: bool` distinct from `require_final`, with
`_load_real_observations`'s wrapper passing `raise_on_missing=True` (today's
behaviour: raise for any of the fixed NYC/MIA stations with zero
candidates) and `_settled_readings`'s wrapper passing
`raise_on_missing=False` (today's behaviour: silently omit a station with no
final candidate, preserving `_run_live_capture`'s `missing`/REFUSAL logic
downstream). Add a RED test 4 fixture with a station present in `records`
carrying ONLY a non-final print (no final at all) and assert the
`_settled_readings` wrapper OMITS that station from its output rather than
raising, while the `_load_real_observations` wrapper (fixed station list,
same missing case) still raises `LookupError` — proving the two contracts
are preserved, not merged.

No other new defects found. The default-branch fix itself (restamp
deletion, `weather_data` omission, the documenting `assert_available_before_decision`
call, the survey deliverable design, the `whole_tape_paper_replay.py`
ineligibility marker) all check out against source as described.

## Per-criterion points (caps: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 17/20 — the round-2 defect (default
  branch) is genuinely fixed; the same fix's generalisation reaches into and
  changes behaviour on the already-correct live-capture path it claims to
  leave untouched.
- Technical correctness and evidence grounding: 14/20 — the plan's own
  claim that the shared helper reproduces "identical error messages/shape to
  today's `_load_real_observations` **and** `_settled_readings`" is refuted
  by a direct read of both functions' current missing-station handling.
- Implementation specificity and feasibility: 11/15 — concrete everywhere
  else, but the shared helper's single "raise if no candidate" contract is
  underspecified for two callers with materially different current
  behaviour; following the spec literally introduces a live-path regression.
- Acceptance criteria and validation quality: 14/20 — RED test 4 as
  specified does not include the fixture (station with a preliminary-only
  print, no final) that would surface this defect; §5's "existing tests
  staying green" claim cannot substitute since no test covers that path
  today.
- Autonomous operation, failure handling and recovery: 11/15 — converts an
  existing graceful, exit-code-1 REFUSAL on the live-capture CLI into a
  potential uncaught exception for a plausible operational case (a capture
  taken before every station's FINAL print has posted).
- Portfolio alignment, scope, dependencies: 9/10 — unaffected by this
  defect; dependency/priority framing remains accurate.

**Total: 76/100.**

## Required changes to reach 100

- Split the shared helper's missing-candidate handling per caller
  (`raise_on_missing` or equivalent), preserving `_load_real_observations`'s
  raise-on-missing-station behaviour and `_settled_readings`'s
  omit-on-missing-station behaviour exactly.
- Add the missing-final-only RED test 4 fixture described above, proving
  `_run_live_capture`'s `missing`/REFUSAL path still fires correctly through
  the refactored `_settled_readings` wrapper.
- State explicitly in §5/§6 item 2 that `_settled_readings`'s refactor is
  byte-identical-output ONLY if the missing-station contract is preserved —
  not merely that "existing tests stay green," since no existing test
  currently exercises that contract.

## Blockers

None new. This remains a code/test hygiene fix within build authority; no
operator or strategy-lead ruling is required to correct the defect above.

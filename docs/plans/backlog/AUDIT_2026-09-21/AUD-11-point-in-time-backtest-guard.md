# AUD-11 — Enforce a point-in-time (no-look-ahead) invariant across every backtest/replay/study entrypoint

## 1. ID and actionable title

**AUD-11** — Point-in-time discipline audit + shared guard for all backtest,
paper-replay and offline-study entrypoints under `scripts/analysis/` and
`src/breezy/runtime/`.

## 2. Source finding

Gap **G-08** (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:68-72`), verdict
**FALSE for one runner, UNVERIFIED elsewhere**, folded with gap **G-15(e)**
(`:94-99`, "look-ahead status of remaining study paths (see G-08)").

Evidence, all (V) coordinator-verified against source this round (Revision 3
unless marked Round 4):

- `scripts/analysis/run_weather_strategy_backtests.py` (`main`'s default
  branch, restamp call site confirmed at lines ~1772-1780) restamps the real
  NYC/MIA preliminary CLI observations, whose actual retrieval time
  (~20:32-20:50Z 09-08-30) is AFTER the tape window ends (~16:11:53Z), to
  "just before the tape window starts" (module docstring, "CONSTRUCTED"
  section, `_restamp_climate_day` at line 784) so they are available as
  context for the whole run. The docstring argues this "has no effect on
  trading behaviour" only because every strategy config used by the script
  defaults `flatten-on-observation`'s `is_final` gate to `False` and the fed
  record carries `is_final=False` — a behavioural coincidence, not a
  structural guard.
- `scripts/analysis/whole_tape_paper_replay.py:59,449,457,479,591,626-627`
  carries a module-level `LOOK_AHEAD_CAVEAT` constant, written into every
  output artefact. It scores against the **highest-revision FINAL** CLI print
  regardless of when that revision was retrieved relative to the scored
  decision — a *deliberate and disclosed* divergence from the sibling
  `ladder_ev` driver's rule (C11, `docs/strategies/breezy_strategy_ladder_ev_2026-09-07.md:293,522`):
  "pin to the CLI FINAL that was **available at the venue's settlement
  time**". `docs/evidence/ladder_ev_peer_review_2026-09-07.md:41` records the
  same divergence and labels every run of this driver "MECHANISM TEST — NO
  VERDICT". The caveat is visible in output, but nothing in code stops a
  future caller from feeding a `whole_tape_paper_replay` number into a PREREG
  tally or a promotion decision.
- Guards that DO enforce point-in-time discipline exist and were re-read this
  session: `assert_settlement_invariants`'s ORDERING check
  (`src/breezy/runtime/backtest_harness.py`, the `out_of_order` block) refuses
  any `InstrumentClose` whose `ts_init` does not strictly follow that
  instrument's last market-data `ts_init`. `paper_replay.py`'s
  `_assert_no_foreign_market_data` refuses any non-`InstrumentClose` record
  whose `ts_init` falls outside the converted capture window, and
  `ImpossibleFillPriceError` refuses a fill priced better than the
  decision-instant `entry_ask` (the L-25 defect class). These three guards do
  not cover WEATHER/forecast records injected into a run, and no shared
  module applies the same rule across every script.
- The remaining ~30 scripts under `scripts/analysis/` were **not inspected
  this session** — the evidence-collection survey (§7 step 1) is the first
  check.
- **(Round 2, resolved, retained.)** `docs/evidence/grok_forecast_family_verdict_2026-09-02.md`
  (the memo that KILLED the forecast family) disregards ALL existing backtest
  output, including this script's, as inadmissible for reasons independent
  of and prior to the restamp defect: "Existing backtests use a synthetic
  snapshot. Those numbers are void twice: wrong sigma, and no real forecast."
  (line 38, independently re-confirmed by both round-2 reviewers). Its
  companion doc `docs/evidence/grok_armed_validation_2026-09-03.md:53`
  confirms `run_weather_strategy_backtests.py`'s `_SequenceForecastSource` is
  the only non-test `ForecastSource` implementer, and the verdict's T-11 pin
  example cites `test_forecast_sigma_uses_issuance_lead.py` (a unit test),
  not this script's numeric output. The KILL verdict did not rely on this
  script's numbers.
- **(Round 3, corrects a round-2 MATERIAL defect confirmed by both
  reviewers via direct source read this round.)** `_load_climate_day_records`
  (module scope, line 1349, docstring: "Every non-superseded `NwsClimateDay`
  for `climate_day`, at its REAL ts_init. NOT restamped.") is **already
  wired into a live `BacktestEngine` run** — but through a **different
  function and a different CLI subcommand** than the one this item must fix.
  Read directly, `_run_live_capture` (lines 1527-1682): `records =
  _load_climate_day_records(...)` (line 1559) feeds `weather_data =
  as_backtest_data(list(records))` (line 1582), passed to `_run_one(...,
  weather_data=weather_data, ...)` (lines 1611-1621) for the
  `cli_settlement_print_lock` strategy under `--tape-instance-id`. This is a
  real, already-proven engine feed (real `orders_submitted`/`fills`
  reported), not a diagnostic print — the round-2 plan's "currently used only
  to print a 'REAL:' diagnostic block" claim was **wrong**; both round-2
  reviews (mle-reviewer, prediction-market-reviewer) independently traced
  this and it is corrected here.
  **However** — and this is the round-2 MATERIAL defect the
  prediction-market-reviewer found and this round independently confirmed by
  direct read — `_load_climate_day_records` is NOT wired into `main`'s
  DEFAULT branch (no `--tape-instance-id`, the branch that actually contains
  the restamp defect, call site line ~1772-1780). That branch calls a
  **different** loader, `_load_real_observations` (line 742), which:
  - is hardcoded to `("NYC", "MIA")`;
  - selects, per station, the **single highest-`revision_seq`
    non-superseded** record (no `is_final` filter — this session confirms it
    accepts a preliminary reading), raising `LookupError` if a station has no
    candidate or the selected record's `tmax_f` is `None`;
  - returns `tuple[dict[str, int], dict[str, NwsClimateDay]]` — the first
    element, `real_observed`, is a per-station `tmax_f` dict consumed at line
    1805 by `build_settlement_scenarios(real_observed_by_station=real_observed, ...)`
    (the settlement-scenario sweep) and again at line 1849 (JSON output).
  `_load_climate_day_records` returns a flat `list[NwsClimateDay]` — every
  non-superseded record, no selection, no `tmax_f`-null validation, no
  per-station dict. It supplies no equivalent to `real_observed`. A
  same-named sibling, `_settled_readings` (line 1376, used inside
  `_run_live_capture`), performs a **different** selection rule again
  (highest-revision, but requires `is_final=True` — settlement-grade truth,
  correct for the live-capture path where a FINAL print is expected; wrong
  for the default branch's 08-30 tape, where only a preliminary,
  `is_final=False`, print exists). Confirmed by direct read this round;
  `_load_real_observations`'s selection is intentionally more permissive
  (accepts non-final) than `_settled_readings`'s. §6 item 2 below specifies
  the actual fix, generalising both selection rules into one shared helper
  rather than treating either as a drop-in replacement for the other.
- **(Round 4, corrects two round-3 MATERIAL defects, one found independently
  by both reviewers and one found by mle-reviewer, both re-confirmed against
  source this round.)**
  - **Missing-station contract.** `_settled_readings` (line 1376, re-read
    this round): filters to `is_final=True` only, tracks the best record per
    `record.station` with no fixed station list and **no raise when a
    station ends up with zero final candidates — that station is simply
    absent from the returned dict**, confirmed by re-reading the full body
    (lines 1376-1398, no `LookupError` branch keyed on a missing station, only
    on a selected record's `tmax_f is None`). `_run_live_capture`
    (lines 1572-1580, re-read this round) depends on exactly this silent
    omission: it computes `missing = {station for ti in tape_instruments} -
    set(observed)` from `_settled_readings`'s output and prints a graceful
    `"REFUSAL: no FINAL print for station(s) ..."` / exit 1 for this case —
    the routine, anticipated scenario of a capture taken before every
    station's FINAL print has posted. `_load_real_observations` (line 742,
    re-read this round) is different: it raises `LookupError` for any of its
    fixed `("NYC","MIA")` stations with zero non-superseded candidates. Round
    3's §6 item 2 specified one `require_final`-gated helper whose
    "raise `LookupError` if no candidate" branch was described as producing
    "identical error messages/shape to today's `_load_real_observations` and
    `_settled_readings`" — false for `_settled_readings`'s missing-station
    case, which never raises today. §6 item 2 below adds a `raise_on_missing`
    parameter, independent of `require_final`, so each wrapper reproduces its
    own current contract exactly.
  - **Guard boundary.** `_synthesize_close` (lines 723-739, re-read this
    round): `ts = tape_instrument.last_market_data_ts_init + _ONE_SECOND_NS`
    — the tape's actual last-decision-instant is the last real market-data
    tick + one second (~16:11:54Z), used to construct the tape's own
    `CONTRACT_EXPIRED` close. `instrument.expiration_ns` is a *different*
    value, parsed from the venue's `endDate` field
    (`src/breezy/adapters/polymarket_us/parsing.py:1399-1400`, re-read this
    round) — a representative fixture
    (`tests/unit/test_polymarket_us_parsing.py:161,199`,
    `endDate="2026-08-26T05:00:00Z"`) shows this daily-market convention sets
    `endDate` to ~05:00Z the *following* day, i.e. plausibly AFTER, not
    before, the ~20:32-20:50Z real retrieval window this item is trying to
    guard against (the specific `endDate` for this exact 2026-08-30 NYC/MIA
    tape's instruments was not independently re-read from the catalog this
    round). Round 3's §6 item 2 called the guard with
    `decision_ts_init_ns=max(ti.instrument.expiration_ns for ti in
    tape_instruments)` and asserted this "is expected to raise" — if
    `expiration_ns` in fact falls after the real retrieval time for this
    tape, the guard would silently NOT raise, contradicting the plan's own
    stated expectation and defeating its purpose. §6 item 2 below switches
    the boundary to the last real market-data `ts_init` (equivalently, the
    synthesized close's `ts`), consistent with both the plan's own rationale
    ("there is no honest ts_init at which these records could be fed into
    the engine...") and the engine's own settlement-timing convention.

**Class:** verification gap (for the ~30 uninspected paths) compounding one
confirmed **implementation defect** (`run_weather_strategy_backtests.py`'s
restamp in `main`'s default branch, currently inert only by a config
coincidence) and one **documented, intentional design divergence**
(`whole_tape_paper_replay.py`'s `LOOK_AHEAD_CAVEAT`) with no code-level
barrier against misuse.

## 3. Current behaviour, required behaviour, concrete gap

**Current:** point-in-time discipline is enforced ad hoc, per-driver
(`assert_settlement_invariants`, `_assert_no_foreign_market_data`,
`ImpossibleFillPriceError`). No shared primitive exists. `main`'s default
branch in `run_weather_strategy_backtests.py` manufactures data availability
earlier than it really occurred, defended only by an incidental
`is_final=False` config default — and the loader that already avoids
restamping (`_load_climate_day_records`) is wired into a *different*
subcommand (`_run_live_capture`) with a *different* selection contract, not
into the branch that needs fixing. `whole_tape_paper_replay.py` intentionally
relaxes point-in-time scoring for a stated, narrower purpose but carries no
code-level fence against its numbers leaking into a promotion or PREREG
decision. ~30 scripts have never been classified.

**Required:** every entrypoint that feeds a decision engine (Nautilus
`BacktestEngine`/`BacktestNode`) or scores a decision against an outcome
states, in one auditable table, which of three regimes it is in — (a)
**decision-time-only**: every record's availability time strictly precedes
every decision it can influence, enforced by a shared guard; (b) **evidence
diagnostic**: point-in-time is intentionally relaxed for a named, narrower
purpose and its output is machine-marked ineligible for PREREG/promotion
consumption; (c) **not applicable**. A shared guard function enforces (a)
wherever claimed. A record whose true (real, unrestamped) availability time
falls after the decision window it would otherwise be fed into **must not be
fed to that engine run's decision stream at all** — it may be used only for
post-hoc settlement-scenario construction, never restamped earlier to
manufacture in-window availability. RED tests reproduce the two known cases
(the restamp, and a synthetic "record retrieved after its claimed
availability") plus an equality-boundary case. Every record's `ts_init`
provenance is itself classified (real capture timestamp vs. harness-assigned
with no real-world referent).

**Gap:** no shared guard exists; the default branch's restamp is
config-coincidental, not structural; the existing REAL-ts_init loader is
wired into the wrong subcommand for this fix and cannot be swapped in
verbatim because its return shape differs from what the default branch's
settlement-scenario sweep needs; `whole_tape_paper_replay.py`'s caveat is
output-only; ~30 drivers are unclassified.

## 4. Priority, rationale, dependencies, execution order

**P1.** Backtest/replay output is the only evidence path by which any future
family gets promoted (`docs/core/PROGRESS.md` REG-1, `docs/plans/POST_FORECAST_PHASE_2026-09-20.md`
WP-D1/A0/C2). A silent look-ahead in that path would corrupt the very
decision the rest of the backlog exists to protect, and the bot is currently
untraded (G-01/G-02) — this is the cheapest possible moment to fix it.

**Dependencies:** none upstream. **Downstream:** `POST_FORECAST_PHASE_2026-09-20.md`'s
C2 and any future A1(iii) re-registration must cite this item's
classification table before their own numbers are trusted.

**Execution order:** run after any item already in flight that touches
`backtest_harness.py`/`paper_replay.py` signatures (none currently open);
otherwise first in cluster D.

## 5. Scope and explicit exclusions

**In scope:** (1) evidence-collection survey of every script under
`scripts/analysis/` and every backtest/replay entrypoint under
`src/breezy/runtime/`, classified (a)/(b)/(c), including a `ts_init`
provenance column; (2) a shared point-in-time guard, reused by
`run_weather_strategy_backtests.py`'s default branch and any (a)-classified
script found in the survey; (3) extraction of one shared per-station
"highest-revision reading" selection helper (§6 item 2) so the default
branch's settlement-scenario input is derivable directly from
`_load_climate_day_records`'s REAL-ts_init records without restamping; (4) a
machine-readable ineligibility marker for (b)-classified outputs; (5) RED
tests from the two known cases plus an equality-boundary case, plus the
missing-station-contract case added in round 4 (§7 step 4).

**Excluded:** re-deriving or re-running any prior study's numbers; changing
`whole_tape_paper_replay.py`'s scoring rule itself; any change to
`assert_settlement_invariants`, `_assert_no_foreign_market_data`, or
`ImpossibleFillPriceError`'s existing behaviour (reused, not touched, except
routing through the shared primitive as a byte-identical refactor); any
PREREG/family-manifest semantics change; deleting any prior artefact;
changing `_run_live_capture`'s existing wiring of `_load_climate_day_records`
(it is already correct and is reused, not modified, except that
`_settled_readings` is refactored per §6 item 2 to call the new shared
helper — a byte-identical-output refactor proven by existing tests staying
green and by the new RED test's missing-station fixture).

## 6. Proposed changes, grounded in inspected code/config/data flows

1. **New shared module** `src/breezy/runtime/point_in_time_guard.py` (native
   extension, no Nautilus modification): one function,
   `assert_available_before_decision(records: Sequence[Data], *, decision_ts_init_ns: int, context: str) -> None`,
   raising `LookAheadRecordError` (new, alongside `ForeignReplayDataError`/
   `SettlementInvariantError`) for any record whose `ts_init` is `>
   decision_ts_init_ns` (strict; equal is available, not look-ahead — see §7
   step 2's equality-boundary test). **Aggregation semantics:** the guard
   scans every record in `records` in one pass and, if any violate, raises
   a single `LookAheadRecordError` carrying `offending_records: tuple[Data, ...]`
   (every violating record, input order preserved) rather than raising on
   the first — this keeps the function pure (one return path, no early
   exit tied to iteration order) and lets a caller derive an exact
   violation count via `len(exc.offending_records)` without independently
   re-filtering `records` (see §6 item 2's call site). Reuses Nautilus's own `Data.ts_init`
   semantics verbatim, confirmed at
   `.venv/lib/python3.13/site-packages/nautilus_trader/core/data.pyx:30-49`
   (`ts_event` "when the data event occurred" ~31-38, `ts_init` "UNIX
   timestamp (nanoseconds) when the instance was created" ~43-49). Breezy's
   own `src/breezy/domain/nws_raw_product.py:206-209` already treats
   `ts_init` as "UNIX nanoseconds Breezy received the product"
   (`retrieved_at_ns`), so this guard formalises an existing convention.
2. **Extract a shared selection helper and re-wire `main`'s default branch —
   the actual fix, specified concretely (round 4, resolves two round-3
   MATERIAL defects, independently confirmed by both reviewers via direct
   source read):**
   - New module-scope function, next to `_load_real_observations`:
     `_select_highest_revision_readings(records: Sequence[NwsClimateDay], *, stations: Sequence[str], require_final: bool, raise_on_missing: bool) -> tuple[dict[str, int], dict[str, NwsClimateDay]]`.
     Body: for each station in `stations`, filter `records` to that station's
     non-superseded entries (further filtered to `is_final=True` when
     `require_final=True`), select the max by `revision_seq`. If no candidate
     survives the filter for a given station: when `raise_on_missing=True`,
     raise `LookupError` (message identical to today's
     `_load_real_observations`); when `raise_on_missing=False`, silently
     OMIT that station from both returned dicts — no exception, identical to
     today's `_settled_readings`. Independently of `raise_on_missing`, a
     candidate whose `tmax_f is None` always raises `LookupError` (both
     current functions already raise on this case for a selected candidate;
     unchanged). `require_final` and `raise_on_missing` are two independent
     axes: `require_final` controls which records are eligible candidates;
     `raise_on_missing` controls what happens when a station ends up with
     zero eligible candidates. Collapsing them into one flag (round 3's
     specification) is what produced the round-3 MATERIAL defect — see §13.
   - `_load_real_observations` becomes a thin wrapper:
     `return _select_highest_revision_readings(_load_climate_day_records(weather_catalog_root, stations=("NYC","MIA"), climate_day=CLIMATE_DAY), stations=("NYC","MIA"), require_final=False, raise_on_missing=True)`
     — `raise_on_missing=True` reproduces today's exact behaviour (raises
     `LookupError` if either fixed station has no non-superseded candidate)
     — same signature, same return shape, same values (both paths already
     read the same station catalog via `open_station_catalog`/
     `read_climate_days`), pure refactor.
   - `_settled_readings` becomes a thin wrapper:
     `observed, _records = _select_highest_revision_readings(records, stations=sorted({r.station for r in records}), require_final=True, raise_on_missing=False); return observed`
     — `raise_on_missing=False` reproduces today's exact behaviour: a station
     with zero `is_final=True` candidates is silently absent from the
     returned dict, never an exception. This is load-bearing:
     `_run_live_capture` (lines 1572-1580) computes `missing = {station for
     ti in tape_instruments} - set(observed)` from this dict and prints a
     graceful `"REFUSAL: no FINAL print for station(s) ..."` / exit 1 for
     exactly this case; `raise_on_missing=True` here would turn that
     graceful refusal into an uncaught `LookupError` for the routine,
     anticipated scenario of a station with only a preliminary (non-final)
     print — climate-day data arrives progressively, preliminary before
     final. Existing `_run_live_capture` callers are unchanged.
   - **In `main`'s default branch:** replace the current
     `real_observed, real_records = _load_real_observations(args.weather_catalog_root)`
     call with:
     `records = _load_climate_day_records(args.weather_catalog_root, stations=("NYC", "MIA"), climate_day=CLIMATE_DAY)`
     followed by
     `real_observed, real_records = _select_highest_revision_readings(records, stations=("NYC", "MIA"), require_final=False, raise_on_missing=True)`
     — `real_observed` feeds `build_settlement_scenarios` and the JSON output
     exactly as today, with byte-identical values (same underlying data, same
     selection rule, now reached through the REAL-ts_init loader instead of a
     duplicate read).
   - **Delete the restamp entirely.** Remove the `_restamp_climate_day` call
     and its surrounding `CONSTRUCTED: restamping...` print block (lines
     ~1772-1780). **Do not feed `records`/`real_records` into `weather_data`
     at all in the default branch** — per this item's own required behaviour
     (§3): the real preliminary observations' true retrieval time
     (~20:32-20:50Z) is strictly after every tape instrument's synthesized
     `CONTRACT_EXPIRED` close (`_synthesize_close`, one second after the last
     real market-data `ts_init`, ~16:11:54Z) — there is no honest ts_init at
     which these records could be fed into the engine and have any
     opportunity to influence a decision in this tape window. `weather_data`
     is therefore omitted from the default branch's `_run_one` calls (pass
     `weather_data=()`  or `None` per `_run_one`'s existing parameter
     contract — verify at implementation time which the signature already
     accepts), and `real_observed`/`real_records` are used *only* for
     `build_settlement_scenarios`'s post-hoc sweep, matching the brief's
     "not fed to decisions ... may only be used for settlement scenario
     construction" rule exactly.
   - Call `assert_available_before_decision(records, decision_ts_init_ns=max(ti.last_market_data_ts_init for ti in tape_instruments) + _ONE_SECOND_NS, context="run_weather_strategy_backtests.main default branch")`
     — **round 4: boundary corrected from `expiration_ns` (both reviewers'
     round-3 MATERIAL defect).** `expiration_ns` is parsed from the venue's
     `endDate` field (`src/breezy/adapters/polymarket_us/parsing.py:1399-1400`),
     which for this daily-market convention is set to ~05:00Z the FOLLOWING
     day (`tests/unit/test_polymarket_us_parsing.py:161,199`,
     `endDate="2026-08-26T05:00:00Z"`) — i.e. plausibly AFTER, not before,
     the ~20:32-20:50Z real retrieval window this item is trying to guard
     against, which would make the guard silently fail to raise and defeat
     its stated purpose. The corrected boundary,
     `max(ti.last_market_data_ts_init for ti in tape_instruments) + _ONE_SECOND_NS`,
     is exactly the value `_synthesize_close` (`run_weather_strategy_backtests.py:723-739`)
     already uses to construct each tape instrument's own `CONTRACT_EXPIRED`
     close — the guard is now anchored to the engine's own settlement-timing
     convention, not the venue's unrelated legal-expiration field. Called
     immediately after loading `records`, **as a documenting/regression
     assertion, not a filter**: today it is expected to raise for every
     record in `records` (their real `ts_init`, ~20:32-20:50Z, is after the
     last real market-data `ts_init`/synthesized close, ~16:11:54Z) — the
     call site catches `LookAheadRecordError` and logs "CONFIRMED: N
     climate-day record(s) excluded from the engine feed — real ts_init is
     after the last decision instant", where `N = len(exc.offending_records)`
     (the guard's own aggregated count per §6 item 1 — the call site does
     NOT independently re-filter `records`), rather than propagating — this
     converts the previously-implicit "restamping has no effect on trading
     behaviour" claim into a structural, machine-checked fact instead of an
     assumption defended only by an `is_final` config default. §8 now
     requires this raise (or its absence) to be captured as evidence rather
     than assumed — see §8. If a future capture ever contains a climate-day
     record whose real `ts_init` genuinely falls inside the decision window,
     the guard's absence-of-raise is itself the signal that such a record is
     now a candidate for inclusion in `weather_data` — a case this item does
     not need to handle today (no such record exists in the current tape,
     and the assertion is expected to raise for it) but the guard call makes
     detectable rather than silently missed.
3. **Ineligibility marker for (b)-classified drivers**: extend
   `whole_tape_paper_replay.py`'s existing `LOOK_AHEAD_CAVEAT` file-drop
   (`:457,627`) with a machine-checkable sibling — a `mechanism_test_only:
   true` field in the same metadata dict already being written (`:449,479`)
   — and a new contract test asserting any code path that reads
   `PREREG`/`family_manifest`/tally inputs refuses a directory carrying that
   field.
4. **Survey deliverable**: `docs/evidence/POINT_IN_TIME_CLASSIFICATION_2026-09-21.md`,
   one row per entrypoint found under `scripts/analysis/` and
   `src/breezy/runtime/`, columns: entrypoint, decision engine used,
   classification (a/b/c), evidence (file:line), guard applied (yes/no/n-a),
   `ts_init` provenance (real capture timestamp / harness-assigned with no
   real-world referent).

## 7. Ordered implementation or verification steps

1. **Survey** (read-only): for every file in `scripts/analysis/` and every
   `run_backtest`/replay entrypoint under `src/breezy/runtime/`, `grep` for
   `BacktestEngine(`, `add_data(`, `run_backtest(`, `ts_init=`, and any
   timestamp-construction call near weather/forecast/settlement data.
   Classify per §3, determine `ts_init` provenance. Produce the table in §6
   item 4.
2. **RED test 1** (`tests/unit/test_point_in_time_guard.py`, new file):
   construct a minimal `Data`-like fixture with `ts_init` after a
   `decision_ts_init_ns`; assert `assert_available_before_decision` raises
   `LookAheadRecordError`. Add a second fixture at exact equality asserting
   it does NOT raise. Add a third fixture mixing several violating and
   non-violating records; assert the raised exception's `offending_records`
   contains exactly the violating records (input order preserved) and
   `len(offending_records)` matches the violation count — proving the
   guard's aggregation semantics (§6 item 1), not just first-raise.
3. **RED test 2**, built from the KNOWN case: a fixture reconstructing the
   default branch's exact real-vs-decision-window gap (observation retrieved
   hours after the tape window's last decision instant) — assert the guard
   raises when fed at the real `ts_init`, matching the documenting-assertion
   call in step 4 below.
4. **RED test 3** (`tests/unit/test_run_weather_strategy_backtests_selection.py`,
   new file): fixture proving `_select_highest_revision_readings` with
   `require_final=False, raise_on_missing=True` reproduces
   `_load_real_observations`'s exact current output (byte-identical dict
   values, and raises `LookupError` on the same fixed-station-with-no-candidate
   case) on a small synthetic record set, and with `require_final=True,
   raise_on_missing=False` reproduces `_settled_readings`'s exact current
   output on a set containing both a preliminary and a final print. Fails
   before the helper exists (the current inline duplication has no shared
   function to import).
   **Round 4 addition (resolves both reviewers' round-3 MATERIAL defect on
   the missing-station contract):** a further fixture with a station present
   in `records` carrying ONLY a non-final print (no final at all) — assert
   the `_settled_readings` wrapper (`require_final=True,
   raise_on_missing=False`) returns a dict OMITTING that station, no
   exception raised; and, on a separate fixture where a station in the fixed
   `("NYC","MIA")` list has zero candidates at all, assert the
   `_load_real_observations` wrapper (`raise_on_missing=True`) still raises
   `LookupError`. Both fixtures must pass before `_run_live_capture`'s
   `missing`/REFUSAL branch (§9) is exercised, proving the two callers'
   current contracts are preserved, not merged.
5. **Wire** the guard and the new selection helper into
   `run_weather_strategy_backtests.py` per §6 item 2: extract
   `_select_highest_revision_readings`, refactor `_load_real_observations`
   and `_settled_readings` into thin wrappers, remove the restamp block and
   the `weather_data` feed from `main`'s default branch, add the documenting
   `assert_available_before_decision` call with the corrected boundary. Run
   the script against the same captured tape and confirm (a)
   `real_observed`/scenario output is byte-identical to the pre-change run
   (proving the refactor is pure), (b) `weather_data`'s removal produces
   identical `naive`/`realistic` per-strategy trading results (proving the
   restamped record was, as claimed, causally inert) — this run is the
   proof, not an assumption — and (c) the documenting assertion's actual
   raise/no-raise outcome for this tape is captured verbatim in the survey
   deliverable (§6 item 4) rather than assumed from the plan's prose.
6. **Add the ineligibility marker** to `whole_tape_paper_replay.py` (§6 item
   3) and its contract test.
7. **For every (a)-classified script found in step 1 that constructs or
   restamps a timestamp near a decision boundary**: wire the same guard. If
   step 1 finds none beyond the two already known, this step closes with the
   survey table as evidence, not new code.
8. Full targeted suite: `pytest tests/unit/test_point_in_time_guard.py tests/unit/test_run_weather_strategy_backtests_selection.py tests/unit/test_runtime_backtest_feed.py tests/contract/test_backtest_harness_stop_gate.py tests/integration/test_forecast_edge_backtest.py -q`, then the broader suite per §8 of the operating contract.

## 8. Measurable acceptance criteria and required evidence

- `docs/evidence/POINT_IN_TIME_CLASSIFICATION_2026-09-21.md` exists, covers
  every file under `scripts/analysis/` and every backtest/replay entrypoint
  under `src/breezy/runtime/`, no row left unclassified, every row carries a
  `ts_init` provenance value.
- RED→GREEN output for all three new/extended test files (guard,
  equality-boundary, selection-helper equivalence — including the round-4
  missing-station-contract fixtures), captured verbatim.
- `run_weather_strategy_backtests.py`'s default branch no longer restamps a
  record's `ts_init` and no longer feeds the climate-day record into
  `weather_data`/`BacktestEngine` at all; a diff-level review confirms (i)
  the restamp block is removed, (ii) `real_observed_by_station`'s values are
  byte-identical pre/post-change (not merely that the restamp call is gone —
  the reconstruction path via the new shared helper must be reviewed, not
  assumed correct because the diff is small), and (iii) `weather_data` is
  absent (or empty) from the default branch's `_run_one` calls.
- **(Round 4, new.)** The documenting `assert_available_before_decision` call
  (§6 item 2, §7 step 5) is confirmed, with captured evidence, to actually
  raise `LookAheadRecordError` for the known 2026-08-30 NYC/MIA tape — i.e.
  the late observation IS rejected from the decision feed at the corrected
  (`last_market_data_ts_init`-based) boundary. If it does not raise for this
  tape, that is itself a finding to report, not silently absorbed — the
  survey deliverable (§6 item 4) records the actual outcome. The logged
  count N is confirmed to equal `len(exc.offending_records)` (the guard's
  own aggregate, per §6 item 1 — never a call-site re-filter) and, for
  this tape, to equal `len(records)` (every record is expected to violate).
- **(Round 4, new.)** A test asserts `_settled_readings`, called with a
  station present in the input but carrying only a non-final print,
  continues to omit that station from its output (no exception) — proving
  `_run_live_capture`'s `missing`/REFUSAL branch (§9) still fires correctly
  through the refactored wrapper.
- `whole_tape_paper_replay.py`'s output metadata carries `mechanism_test_only: true`
  and a new contract test proves a PREREG/tally reader refuses a directory
  carrying it — this test must fail RED before the marker exists.
- Full existing suite for `backtest_harness.py`/`paper_replay.py`/
  `run_weather_strategy_backtests.py` stays green, byte-identical pass/fail
  set to pre-change.

## 9. Validation: failure cases, integration behaviour, autonomous operation

- **Failure case:** a future script restamps a record earlier than its true
  `ts_init` without calling the guard — caught only if that script is
  (a)-classified in the survey and wired; the survey table is the living
  contract, and any NEW backtest/replay entrypoint added after this item must
  add itself to the table (a stated follow-on convention, not CI-enforced in
  this item's scope).
- **Failure case (round 4, new):** a capture taken before every station's
  FINAL print has posted — a station present in the tape's records with only
  a preliminary print. `_run_live_capture`'s `missing`/REFUSAL path (exit 1,
  no crash) must still fire through the refactored `_settled_readings`
  wrapper; this is the exact scenario the round-3 MATERIAL defect would have
  turned into an uncaught `LookupError`, and it is now covered by RED test 3's
  round-4 fixture (§7 step 4) and the §8 acceptance criterion above.
- **Integration behaviour:** the guard is a pure function over
  already-materialised `Data` sequences — no I/O, no Nautilus internals
  touched. The selection-helper refactor is behaviour-preserving by
  construction (RED test 3 proves output equivalence, including the
  missing-station contract per caller, before any caller is switched).
- **Autonomous operation:** none of this runs on the live node; offline-only.
  No runtime, permit, or execution-path change.

## 10. Deployment, observability, rollback

No deployment — analysis tooling, not a runtime unit. Observability: the
classification doc is the observability artefact; `LookAheadRecordError`
messages name the offending record's `ts_init` and the decision boundary.
Rollback: revert the touched files (`run_weather_strategy_backtests.py`,
`whole_tape_paper_replay.py`) and delete the new guard module; no state,
schema, or persisted artefact is migrated — plain git revert.

## 11. Relationship to portfolio-level ROI and how it will be evaluated

Directly gates every future ROI claim: `POST_FORECAST_PHASE_2026-09-20.md`'s
C2 readout and any A1(iii) re-registration both depend on backtest/replay
output being decision-time-honest. This item produces no ROI number itself —
it is a precondition for trusting any that follow. Evaluated by: the
classification table being cited (by id) in every future plan that consumes a
backtest/replay artefact as evidence.

## 12. Assumptions, unresolved questions, blockers

- **Resolved round 2, retained:** the restamp defect does not taint
  `docs/evidence/grok_forecast_family_verdict_2026-09-02.md` (the KILL
  verdict) — that verdict voided this script's output on independent, prior
  grounds and never relied on its numbers. See §2.
- **Resolved round 3, retained:** `_load_climate_day_records` is not a
  drop-in fix for the default branch — it is wired into a different
  subcommand (`_run_live_capture`) with a different downstream consumer. §6
  item 2 specifies the actual fix: a shared selection helper extracted from
  the two existing, slightly different selection rules.
- **Resolved round 4 (was the round-3 MATERIAL defect on the shared
  helper's missing-station contract, found independently by both round-3
  reviewers):** the shared helper now takes an independent
  `raise_on_missing` parameter so `_load_real_observations`'s
  raise-on-missing-station behaviour and `_settled_readings`'s
  omit-on-missing-station behaviour are each preserved exactly, with a RED
  fixture proving it. See §6 item 2, §7 step 4.
- **Resolved round 4 (was the round-3 MATERIAL defect on the guard's
  boundary value, found independently by both round-3 reviewers):** the
  documenting `assert_available_before_decision` call now uses the last real
  market-data `ts_init` (equivalently the synthesized close's `ts`) instead
  of `instrument.expiration_ns`, and §8 requires the actual raise/no-raise
  outcome for the known tape to be captured as evidence rather than assumed.
  See §6 item 2, §8.
- **Assumption:** the survey (step 1) finds no additional restamping beyond
  the two known cases; if it does, those findings feed step 7 without
  re-scoping the item.
- **Unresolved:** whether a CI-enforced "every new backtest entrypoint must
  appear in the classification table" gate is wanted — named as a possible
  follow-up, not decided here.
- **Assumption, retained from round 3:** `_run_one`'s existing signature
  accepts an empty/`None` `weather_data` argument for the default branch's
  calls without further change; if it does not, adding that accommodation is
  a small, in-scope signature change discovered at step 5, not a new
  blocker.
- **No blockers.** This item requires no operator or strategy-lead ruling —
  it is a code/test hygiene fix and a read-only survey, both within build
  authority.

## 13. Review history

**Baseline self-score (out of 100): 87/100.** (See prior revisions for
detail; superseded by rounds below.)

**Round 1:**
- mle-reviewer: 86/100 (APPROVE WITH WARNINGS). Defects: (1) MATERIAL —
  already-consumed-artefact taint of the KILL verdict, unexamined —
  **ACCEPTED**, resolved. (2) MINOR — no `ts_init` provenance classification
  — **ACCEPTED**. (3) MINOR — `data.pyx` line-anchor imprecision —
  **ACCEPTED**.
- prediction-market-reviewer: 88/100. Defects: (1) MINOR —
  `_load_climate_day_records` not named as reuse target — **ACCEPTED**. (2)
  MINOR — guard equality-boundary behaviour unstated — **ACCEPTED**.

**Revision 2 total: 95/100.** (Both round-1 reviewers' defects fixed; see
round-2 review for the fresh defects those "fixes" introduced.)

**Round 2:**
- mle-reviewer: 93/100 (APPROVE WITH WARNINGS). Round-1 defect dispositions
  independently re-verified as genuinely fixed (KILL-verdict quotes,
  provenance column, line-anchor — all confirmed against source, not merely
  trusted from §13). Fresh MINOR defect: `_load_climate_day_records`
  mischaracterised as "diagnostic-only, not wired into `BacktestEngine`" when
  it is already wired via `_run_live_capture`/`_run_one` for the print-lock
  strategy — flagged as under-claiming risk (favourable-to-the-plan
  inaccuracy) rather than concealing it. **ACCEPTED**, corrected in §2.
- prediction-market-reviewer: 83/100 (APPROVE WITH WARNINGS, lowest of round
  2). Fresh **MATERIAL** defect: the round-2 plan's central claim — that
  wiring `_load_climate_day_records` into the default branch is "only
  re-wiring, no new record-construction code" — is refuted by source.
  **ACCEPTED** — fixed via the shared `_select_highest_revision_readings`
  helper. Also MINOR: §8's diff-review criterion did not require reviewing
  `real_observed_by_station` reconstruction — **ACCEPTED**.

**Revision 3 total: 90/100.**

**Round 3:**
- mle-reviewer: 80/100 (APPROVE WITH WARNINGS). Round-2 defect dispositions
  independently re-verified as genuinely fixed (both loader bodies, wiring,
  restamp call site all re-confirmed against source). Fresh **MATERIAL**
  defect 1: the documenting assertion's boundary (`expiration_ns`) is very
  likely the wrong timestamp — the venue's `endDate` convention is typically
  ~05:00Z the *following* day, plausibly after the real retrieval window,
  which would make the guard silently fail to raise, contradicting the
  plan's own stated expectation. **ACCEPTED** — boundary corrected to the
  last real market-data `ts_init`/synthesized close (§6 item 2), and §8 now
  requires the actual raise/no-raise outcome to be captured as evidence.
  Fresh **MATERIAL** defect 2: the generalised
  `_select_highest_revision_readings(require_final=True)` wrapper changes
  `_settled_readings`'s missing-station behaviour from silent omission to a
  crash, breaking `_run_live_capture`'s existing graceful REFUSAL path.
  **ACCEPTED** — the helper now takes an independent `raise_on_missing`
  parameter (§6 item 2), with a RED fixture (§7 step 4) and a validation
  case (§9) proving the REFUSAL path still fires. Also MINOR: the helper's
  contract docstring should state explicitly which callers exercise the
  raise branch — **ACCEPTED**, made explicit in §6 item 2's prose on
  `require_final`/`raise_on_missing` being independent axes.
- prediction-market-reviewer: 76/100 (APPROVE WITH WARNINGS, lowest score to
  date). Independently found the SAME missing-station-contract MATERIAL
  defect as mle-reviewer (different framing: "collapses two functions with
  genuinely different missing-station contracts into one, breaking
  `_run_live_capture`'s existing REFUSAL path") — **ACCEPTED**, same fix
  (`raise_on_missing` parameter, §6 item 2; RED fixture, §7 step 4). No fresh
  defect beyond the shared one; confirmed the default-branch half of the
  round-3 fix (restamp deletion, `weather_data` omission, survey deliverable,
  `whole_tape_paper_replay.py` marker) checks out against source as
  described.

**Rejected (round 3):** none. Both reviewers' MATERIAL defects were
independently confirmed this round via direct source reads (re-reading
`_settled_readings`, `_run_live_capture`, `_synthesize_close`,
`instrument.expiration_ns`'s parse site, and the `endDate` fixture) and
neither softened scope or an acceptance criterion.

**Revision 4 self-score (out of 100), conservative — round-3 scores (80, 76)
are the lowest yet, so this round is graded against what a round-4 reviewer
will most plausibly re-check, not assumed clean (caps 20/20/15/20/15/10):**
- Fidelity to audit gap and completeness: 18/20 — both round-3 MATERIAL
  defects sit directly in the fix this item exists to deliver and are now
  addressed with source-grounded, verified changes (helper contract split;
  boundary corrected to the engine's own settlement-timing convention);
  survey execution remains deferred to the implementer, unavoidable for an
  evidence-collection-first item, so not 20/20.
- Technical correctness and evidence grounding: 17/20 — the boundary fix and
  the `raise_on_missing` split were both independently re-verified against
  source this round (`_synthesize_close`, `expiration_ns`'s parse site and a
  representative `endDate` fixture, `_settled_readings`'s full body,
  `_run_live_capture`'s `missing` computation); held below 18/20 because the
  actual `endDate` value for THIS 2026-08-30 tape's specific instruments was
  not read from the catalog this round (round 3 flagged the same gap) — the
  representative-fixture inference is strong but not a direct read of this
  tape's own value, and the boundary fix sidesteps rather than closes that
  specific residual uncertainty (which no longer matters for correctness
  since `expiration_ns` is no longer used, but the fixture-based reasoning
  itself is one inferential step removed from this tape's ground truth).
- Implementation specificity and feasibility: 14/15 — both fixes are fully
  concrete (parameter split, wrapper call sites, corrected boundary
  expression); the `_run_one` empty-`weather_data` open item remains a
  step-5 discovery, unchanged from round 3.
- Acceptance criteria and validation quality: 18/20 — §8 now requires
  capturing the documenting assertion's actual raise/no-raise outcome as
  evidence (closing round 3's gap) and requires the missing-station-omission
  fixture to pass (closing the other round-3 gap); not 20/20 because neither
  criterion has been executed in this session — both are specified, not yet
  run.
- Autonomous operation, failure handling, recovery: 14/15 — the round-4
  fixture adds an explicit failure-case validation (§9) for the
  preliminary-only-print scenario, a small improvement over round 3's
  unchanged 13/15; "table drifts out of date" remains a named, accepted
  limitation.
- Portfolio alignment, scope, dependencies: 9/10 — unchanged, clear
  precondition relationship, no invented ROI number.

**Revision 4 total: 90/100.**

**Round 4:**
- prediction-market-reviewer: 100/100 (APPROVE). No defects found; both
  round-3 MATERIAL defects independently re-confirmed fixed against
  source.
- mle-reviewer: 99/100 (APPROVE WITH WARNINGS). Both round-3 MATERIAL
  defect dispositions independently re-verified fixed against direct
  source reads (`_synthesize_close`, `expiration_ns`'s parse site and
  fixture, `_settled_readings`'s full body, `_run_live_capture`'s
  `missing` computation, `_load_real_observations`'s raise branch). Fresh
  MINOR defect: `assert_available_before_decision`'s exception-aggregation
  semantics were unspecified, though the call site's "N record(s)
  excluded" log message implied N is derivable. **ACCEPTED** — §6 item 1
  now states the guard aggregates every violation into one
  `LookAheadRecordError` carrying `offending_records`, §6 item 2's call
  site now derives N as `len(exc.offending_records)` (never an
  independent re-filter), §7 step 2 adds an aggregation fixture, and §8
  now requires N to be confirmed equal to `len(exc.offending_records)`
  for the known tape. No other defects found; no scope or acceptance
  criterion softened.

**Rejected (round 4):** none.

**Revision 5 self-score (out of 100), against round 4's own rubric (caps 20/20/15/20/15/10):**
- Fidelity to audit gap and completeness: 20/20 — matches prediction-market-reviewer's 20/20 and mle-reviewer's 20/20; the sole
  round-4 defect was a specificity gap, not a fidelity gap.
- Technical correctness and evidence grounding: 20/20 — matches both
  reviewers' 20/20; the aggregation semantics chosen (collect-all, one
  raise) is consistent with the guard remaining a pure function and with
  the default branch's own requirement that `records` stay wholly
  separate from `weather_data` (§6 item 2), so no contradiction was
  introduced.
- Implementation specificity and feasibility: 15/15 — the sole
  outstanding MINOR (exception-aggregation semantics) is now fully
  specified: guard collects, exposes `offending_records`, call site
  derives N from it, never re-filters.
- Acceptance criteria and validation quality: 20/20 — §7 step 2's new
  aggregation fixture and §8's N-equals-`len(offending_records)`
  criterion make the chosen semantics independently testable, closing
  the one gap mle-reviewer identified.
- Autonomous operation, failure handling, recovery: 15/15 — unchanged
  from round 4's 15/15; no runtime/permit/execution-path change, and the
  aggregation choice adds no new failure surface (still a pure, in-memory
  scan).
- Portfolio objective alignment, scope, dependencies: 10/10 — unchanged
  from round 4's 10/10.

**Revision 5 total: 100/100.**
**Readiness status: READY.**

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `4b6c4d03b734106ebef25147cf5a906a34cc986d2209a33a63085f3cc38ed603`
- **Baseline self-score:** 87/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 5: 100/100 — `reviews/AUD-11-r5-mle-reviewer.md`
  - `prediction-market-reviewer` round 5: 100/100 — `reviews/AUD-11-r5-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None.
- **Full review history:** 10 records, `reviews/AUD-11-r*-*.md`
- Planning only. Nothing in this plan has been implemented.

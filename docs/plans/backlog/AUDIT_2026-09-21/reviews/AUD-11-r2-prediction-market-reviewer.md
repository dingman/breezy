# AUD-11 — Round 2 — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
SHA256: 3d687c044dec146fa9980c26e680071c0bdc03e8c8473af83fb2612812b18314
Round: 2
Reviewer: prediction-market-reviewer (independent, blind)
Lens: prediction-market mechanics — point-in-time discipline for fills/edge
inputs; this round also re-verifies the round-1 fix claims against source.

## §13 review-history reconciliation

- R1 mle-reviewer MATERIAL (already-consumed-artefact taint of the KILL
  verdict) — plan claims resolved via a new §2/§12 bullet citing
  `grok_forecast_family_verdict_2026-09-02.md` and its companion validation
  doc. VERIFIED this round: both documents were re-read; the verdict text
  does say "Existing backtests use a synthetic snapshot. Those numbers are
  void twice: wrong sigma, and no real forecast," and the companion doc does
  cite `test_forecast_sigma_uses_issuance_lead.py` (a unit test) for its T-11
  example, not this script's output. The reconciliation is accurate — CONFIRMED.
- R1 prediction-market-reviewer MINOR #1 (name `_load_climate_day_records` as
  the reuse target) — claimed accepted in §2/§6 item 2/§7 step 4. See below:
  the function is now named, but the plan's claim about what reusing it
  requires is not accurate (new MATERIAL defect, this round).
- R1 prediction-market-reviewer MINOR #2 (equality-boundary case) — §6 item 1
  and §7 step 2 now state strict `>` and add the boundary fixture. VERIFIED
  against the plan text — present.

## Claims verified this round (fresh read of the whole revised plan)

- `_load_climate_day_records` exists at `scripts/analysis/run_weather_strategy_backtests.py:1349`,
  docstring "at its REAL ts_init... NOT restamped" — CONFIRMED verbatim.
- **REFUTED (new MATERIAL defect):** the plan's central round-2 claim — that
  wiring this loader into the engine feed is "only re-wiring... no new
  record-construction code is required" and "not a material design decision
  left to the implementer" (§6 item 2) — does not hold up against the source.
  `_load_climate_day_records` is called ONLY inside `_run_live_capture`
  (line 1527, the `--tape-instance-id` LIVE-CAPTURE subcommand), where its
  output feeds `as_backtest_data(list(records))` directly (line 1582) — it is
  NOT "used only to print a 'REAL:' diagnostic block" as the plan's §2/§4
  bullet states; it is already wired into that subcommand's engine feed. The
  restamp defect itself lives in a *different* function entirely: `main`'s
  DEFAULT branch (no `--tape-instance-id`, line ~1763) calls
  `_load_real_observations` (line 742), not `_load_climate_day_records`.
  These two loaders are not interchangeable:
  - `_load_real_observations` is hardcoded to `("NYC", "MIA")`, selects the
    SINGLE highest-`revision_seq` non-superseded record per station, raises
    `LookupError` if a station has no candidate or the selected record's
    `tmax_f` is `None`, and returns a `(dict[str, int], dict[str, NwsClimateDay])`
    pair — the first element, `real_observed`, is a per-station tmax_f dict.
  - `_load_climate_day_records` returns a flat `list[NwsClimateDay]` of
    EVERY non-superseded record (no highest-revision selection, no per-station
    dict, no `tmax_f`-null validation).
  - `real_observed` (not `real_records`) is a load-bearing input consumed
    downstream at lines 1805 (`build_settlement_scenarios(real_observed_by_station=real_observed, ...)`,
    which sweeps multiple settlement scenarios from it) and 1849 (JSON output).
    `_load_climate_day_records` supplies no equivalent value — an implementer
    following §7 step 4 literally ("re-point the engine feed at
    `_load_climate_day_records`") would still have to write new selection/
    validation code to reconstruct `real_observed`, which is exactly the "new
    record-construction code" the plan says is not required. If instead they
    swap only the `weather_data` feed and leave `real_observed` sourced from
    `_load_real_observations` (a plausible partial reading), the run now
    mixes a restamped-observation source for scenarios with an unrestamped
    source for the engine feed's record identity — a second inconsistency the
    plan does not anticipate.
  **Required change:** §2, §4, §6 item 2, and §7 step 4 must state plainly
  that `_load_climate_day_records` is not currently wired into ANY
  BacktestEngine feed in the restamping (default) code path — it is wired
  into the separate LIVE-CAPTURE subcommand only, where it already behaves
  as intended — and that fixing the default path's restamp requires (a)
  replacing `_load_real_observations`'s record source (straightforward reuse)
  AND (b) writing the per-station "single highest-revision tmax_f, raise if
  missing" selection that currently lives inside `_load_real_observations`
  but has no equivalent in `_load_climate_day_records` (e.g., extracting
  `_settled_readings`-style or `_load_real_observations`-style selection into
  a shared helper both loaders can call). This is genuinely a small, bounded
  fix — but it is NOT "no new code," and the current wording could lead an
  implementer to either break `build_settlement_scenarios`'s input or produce
  an inconsistent record source between the weather feed and the scenario
  sweep, silently reintroducing a look-ahead-adjacent inconsistency in the
  very item meant to close one.
- `run_weather_strategy_backtests.py`'s restamp call site (`main`, not
  `_run_live_capture`) — CONFIRMED at line 1772/1780 (`_restamp_climate_day`
  invoked from the default branch, matching the plan's §2 first bullet,
  independent of the defect above).
- `_load_climate_day_records`'s own docstring — CONFIRMED to explicitly
  distinguish itself from "the legacy path" by SCENARIO ("on a live capture
  that spans the morning final prints they fall INSIDE it"), which is further
  evidence the two loaders are not drop-in equivalents for the same use case;
  the plan's own cited docstring undercuts its "precisely the fix" framing
  rather than supporting it.
- `assert_settlement_invariants`/`_assert_no_foreign_market_data`/
  `ImpossibleFillPriceError` — unchanged from R1, not re-touched this round;
  re-confirmed present and untouched by the plan's exclusions (§5).
- `ts_init`/`ts_event` Nautilus semantics citation (`data.pyx:30-49`) —
  unchanged from R1, re-spot-checked, still accurate.

## Defects

**MATERIAL** (see above) — the plan's round-2 "resolved" claim about
`_load_climate_day_records` being a ready-made, no-new-code fix for the
restamp defect conflates two different loader functions serving two
different subcommands with different return shapes and different downstream
consumers (`real_observed` vs `records`). This is the plan's single
load-bearing correction from round 1 and it does not hold under a direct
source read.

**MINOR** — §8's acceptance bullet ("a diff-level review confirms the
restamp block is removed... replaced by the existing `_load_climate_day_records`
loader, not merely bypassed") inherits the same imprecision — it should also
require confirming `real_observed_by_station`'s reconstruction is covered by
the diff, not just the restamp block's removal, since a diff that removes the
restamp but silently drops or mishandles `real_observed` would pass this
criterion's literal wording while breaking `build_settlement_scenarios`.

No new defects found in the survey deliverable design (§6 item 4), the
shared guard module design (§6 item 1), or the `whole_tape_paper_replay.py`
ineligibility marker (§6 item 3) — all three remain sound and unchanged from
round 1's assessment.

## Per-criterion points (caps: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 17/20 — the already-consumed-
  artefact resolution is solid, but the plan's central round-2 fix claim for
  the confirmed implementation defect (G-08's core finding) does not
  accurately describe what closing it requires.
- Technical correctness and evidence grounding: 15/20 — a direct,
  file:line-level check refutes the plan's own "not a material design
  decision," "no new code" claim about the two loader functions' equivalence.
- Implementation specificity and feasibility: 12/15 — the wiring point is
  named but the actual diff needed (reconstructing `real_observed`) is
  understated to the point of being wrong, which is worse for feasibility
  than leaving it as an open implementation step would have been.
- Acceptance criteria and validation quality: 17/20 — RED tests for the guard
  itself (equality boundary, restamp refusal) remain sound; the "diff-level
  review" criterion for the fix does not catch the `real_observed` gap.
- Autonomous operation, failure handling, recovery: 13/15 — unaffected by
  this defect; unchanged from round 1 (offline-only, no runtime blast
  radius, "table drifts" limitation still honestly named).
- Portfolio alignment, scope, dependencies: 9/10 — unaffected by this defect;
  unchanged from round 1.

**Total: 83/100.**

## Required changes to reach 100

- Correct §2/§4/§6 item 2/§7 step 4 to state that `_load_climate_day_records`
  is already wired into `_run_live_capture`'s engine feed (not merely a
  diagnostic-only function) and is a DIFFERENT function from
  `_load_real_observations`, which is what the default (restamping) branch
  actually calls.
- Specify the actual fix for the default branch: either (a) extract the
  per-station "highest non-superseded revision, raise if `tmax_f` missing"
  selection logic that `_load_real_observations` currently performs inline
  into a small shared helper both branches can call, feeding `_load_climate_day_records`'s
  broader query through it to derive both `real_observed` and the weather
  records, or (b) some other concrete plan the implementer does not have to
  invent — but not "no new code."
- Tighten §8's diff-level acceptance criterion to explicitly require
  `real_observed_by_station`'s construction be reviewed as part of the same
  diff, not only the restamp block's removal.

## Blockers

None new. This item still requires no operator/strategy-lead ruling; the
defect above is a technical-correctness fix within build authority, not a
ruling or missing-evidence blocker.

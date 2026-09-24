# AUD-11 review (round 1, mle-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
sha256: 61c137589dc2216640023d012c0c22bd3cba229e26ee13d5bc5dee80e89d434d
Round: 1
Reviewer: mle-reviewer (backtesting / statistical-validation lens)

## Claims verified against source (this session, direct reads)

- `Data.ts_init` = "UNIX timestamp (nanoseconds) when the instance was created"
  (availability/ingestion instant), `Data.ts_event` = "when the data event
  occurred" — CONFIRMED verbatim,
  `.venv/lib/python3.13/site-packages/nautilus_trader/core/data.pyx:30,42`
  (docstrings at ~31-38 and ~43-49; plan's `:41-49` citation is off by ~1 line
  but the quoted text is exact). The plan picks the RIGHT timestamp
  (`ts_init`, availability) over `ts_event` (occurrence) for a point-in-time
  guard — this is the correct Nautilus semantic to enforce against.
- `src/breezy/domain/nws_raw_product.py:206-209` — CONFIRMED: `ts_init` is
  `retrieved_at_ns` ("UNIX nanoseconds Breezy received the product"), and the
  class asserts `ts_event <= ts_init` at construction (lines ~193-199,
  "bytes cannot be received before they were issued"). The domain convention
  the plan says it "formalises" is real and already enforced at that layer.
- `src/breezy/runtime/paper_replay.py:228-254` (`_assert_no_foreign_market_data`)
  — CONFIRMED: checks `record.ts_init` against `capture_window_ns`, exempts
  only `type(record) is InstrumentClose`. `ImpossibleFillPriceError`
  (`:131-143`) and its use in `filled_trials_from_engine` (`:340-346`) —
  CONFIRMED, refuses `fill_px < ctx.entry_ask`, matches plan's description
  exactly.
- `src/breezy/runtime/backtest_harness.py` `assert_settlement_invariants` and
  its ORDERING/`out_of_order` block — present, 27 in-file callers, real test
  coverage (`tests/unit/test_runtime_backtest_settlement_gate.py` et al.) —
  CONFIRMED to exist as described (not read line-by-line for the exact
  ordering assertion in this round, but the guard and its test suite are
  real, not fabricated).
- `run_weather_strategy_backtests.py`'s "CONSTRUCTED" restamp — CONFIRMED
  present (`grep` hit at lines 20, 1775, 1784: "CONSTRUCTED: restamping
  {station} NwsClimateDay retrieved_at_ns"). Matches the plan's description.
- `whole_tape_paper_replay.py`'s `LOOK_AHEAD_CAVEAT` — not re-opened this
  round; plan's line citations (`:59,449,457,479,591,626-627`) are
  consistent with prior-session sourcing style used throughout; no
  contradiction found.
- Downstream consumption risk (NOT addressed by the plan): `grep` across
  `docs/evidence/` shows `run_weather_strategy_backtests.py` output was cited
  as evidence in `docs/evidence/backtest_rerun_2026-09-03.md` and is named in
  `docs/evidence/grok_armed_validation_2026-09-03.md`, which itself points at
  `docs/evidence/grok_forecast_family_verdict_2026-09-02.md` — the verdict
  that KILLED the forecast family. That verdict is a real, decision-grade
  artefact potentially built on this script's output while the restamp
  defect was live.

## Defects

**MATERIAL** — Look-ahead-tainted artefacts already consumed by a promotion/kill
decision are not addressed. §5 explicitly excludes "re-deriving or re-running
any prior study's numbers," and §12's "no blockers" stance never asks whether
`grok_forecast_family_verdict_2026-09-02.md` (which KILLED the forecast
family) relied on `run_weather_strategy_backtests.py` output produced while
the restamp was live, nor whether that verdict's safety-by-coincidence
(`is_final=False` in every config used) held for every historical run that
fed it, not just today's. The plan's own §6 item 2 proof step re-runs the
script "against the same captured tape" to confirm identical output for
non-`is_final`-dependent branches AFTER the fix — but never checks whether
that was ALSO true for the specific runs that already fed a KILL verdict.
This is the exact "what happens to artefacts already produced with
look-ahead" gap the review brief flags, and it is currently unexamined, not
merely deferred with reasoning.
Required change: add one verification step (read-only, no re-derivation) —
confirm the KILL-verdict-feeding run(s) used the same `is_final=False`
config posture the fix's proof step relies on, and state that finding in
§12 (either "confirmed inert historically too" or "unresolved, named as a
follow-up to the family verdict's own confidence").

**MINOR** — Data whose true availability time was never recorded is not
handled. The guard (`assert_available_before_decision`) is a pure comparison
over `ts_init`; it is only as good as the assumption that every fed record's
`ts_init` reflects a REAL, non-synthetic availability instant. The plan fixes
the one KNOWN case of a falsified `ts_init` (the restamp) but states no rule
for a record that was never captured with a real retrieval timestamp at all
(e.g. a forecast value computed offline post hoc with no historical
`retrieved_at_ns`) — such a record could carry an arbitrary/default
`ts_init` and pass the guard trivially while still being decision-unsafe.
The survey (§7 step 1) greps for restamp PATTERNS (`datetime`, `+ timedelta`,
hardcoded ns literals) but has no step that asks "was this ts_init ever a
real capture time, or was it assigned at harness-construction time with no
historical grounding." Required change: add one classification question to
the survey template (§6 item 4's table) — "ts_init provenance: real capture
timestamp / harness-assigned with no real-world referent" — so a record in
the second bucket is flagged even if it happens to pass the numeric
before/after check.

**MINOR** — Line-citation drift: `.venv/.../data.pyx:41-49` vs. the actual
docstring span (~31-38 for `ts_event`, ~43-49 for `ts_init`); the quoted text
is exact, only the line anchor is imprecise. Not load-bearing.

## Per-criterion points

- Fidelity to audit gap and completeness: 16/20 — survey-first approach is a
  legitimate response to an UNVERIFIED gap, but the already-consumed-artefact
  question (a direct instance of what the gap protects against) is not asked.
- Technical correctness and evidence grounding: 19/20 — `ts_init` vs
  `ts_event` semantics correctly chosen and verified against installed
  source; domain convention correctly cited; one line-anchor imprecision.
- Implementation specificity and feasibility: 13/15 — guard shape, error
  type, and wiring points are concrete and minimal; matches the plan's own
  self-assessment.
- Acceptance criteria and validation quality: 16/20 — RED tests are concrete
  and evidence-grounded; the "byte-identical pass/fail set" criterion is
  good; no acceptance criterion touches the already-consumed-artefact
  question, so a reader cannot tell from §8 alone whether that risk was ever
  checked.
- Autonomous operation, failure handling, recovery: 13/15 — correctly scoped
  offline-only with no runtime blast radius; the "table drifts out of date"
  gap is named, not solved, same as the plan's own self-score reasoning.
- Portfolio alignment, scope, dependencies: 9/10 — clear precondition
  relationship to POST_FORECAST_PHASE C2/A1(iii); no invented ROI number.

**Total: 86/100.**

## Required changes to reach 100

1. Add a read-only verification step: did the run(s) behind
   `grok_forecast_family_verdict_2026-09-02.md` share the same
   `is_final=False` inertness the fix's proof step relies on? State the
   answer (or the residual doubt) in §12, not silently excluded via "no
   re-deriving prior numbers."
2. Add a `ts_init` provenance column to the survey table (§6 item 4):
   real-capture vs. harness-assigned-with-no-real-referent, so records with
   no recorded true availability time are flagged even when numerically
   compliant.
3. Fix the `data.pyx` line-anchor citation (cosmetic).

## Blockers

None requiring an operator/strategy-lead ruling. Both required changes are
read-only verification/documentation work within existing build authority.

## Score

86/100 — APPROVE WITH WARNINGS (no defect blocks the guard mechanism itself
or violates a binding constraint; the two required changes are scoped,
concrete, and do not require new capture or a ruling).

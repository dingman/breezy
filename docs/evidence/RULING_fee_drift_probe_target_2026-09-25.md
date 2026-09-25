# RULING — AUD-12b fee-drift probe: reference target and alert dedupe

**Slug:** `fee_drift_probe_target` · **Date:** 2026-09-25 · **Author:** prediction-market-reviewer (domain peer)

## Defect

`src/breezy/app/trade.py`'s `_build_fee_drift_probe` (~242-337) built the
`FeeDriftProbeActor` without `documented_fee_coefficient`, so the probe
compared the wire-observed theta to the module-level
`DOCUMENTED_TAKER_FEE_COEFFICIENT` (`fees.py:92`, pinned at `0.06`). The
live family `pm_us_crh_v4` is registered at `taker_fee_coefficient = 0.0695`
(`deploy/families/pm_us_crh_v4.json`) — the value the venue has served since
2026-09-17 and the exact value `current_rung_hold/decision.py:342`'s own
per-order check already compares against. Result: the probe DISAGREEs every
fire (every 2 hours) forever, emits a CRITICAL alert every time, and any
deliberate operator clear of the family halt (e.g. to let an exit order
through) is re-vetoed within at most 2 hours.

## Target

Compare the wire read to the RUNNING family's own registered theta
(`FamilyManifest.taker_fee_coefficient`) — the exact source the composed
strategies' `required_fee_coefficient` already comes from
(`trade.py` ~457/503). `fees.py:92`'s `DOCUMENTED_TAKER_FEE_COEFFICIENT` is
never edited; it remains the Actor's own constructor default, used only by
tests and by any family that never overrides it.

## Alerting

Deduped per distinct wire value, per process:

- A wire value never seen before (or different from the last one alerted)
  always alerts `fee_drift_probe_mismatch` (CRITICAL) immediately.
- The SAME wire value is suppressed for 24h, measured on the node's own
  clock (`self.clock.timestamp_ns()`), never wall time.
- After >= 24h with the same wire value still live, exactly ONE
  `fee_drift_probe_mismatch_persisting` (CRITICAL) reminder fires, which
  re-arms its own 24h window (so a second reminder can fire 24h after that,
  and so on).
- A new distinct wire value always alerts immediately regardless of any
  prior value's suppression window.
- `UNKNOWN` outcomes are unchanged: still alerted, still never halt.

## Halt

`set_family_halted` stays unconditional on every DISAGREE, deduped or not —
dedupe shapes only the alert stream. `record_policy_halt` is idempotent and
first-cause-wins, so a repeated, suppressed DISAGREE calling it again is
harmless.

## Change

`_build_fee_drift_probe(..., registered_fee_coefficient: Decimal)` — a new
required keyword parameter, sourced at the call site from the already-loaded
`manifest.taker_fee_coefficient` (the same manifest object the
`continuous_rung_hold` branch already threads into
`build_continuous_rung_hold_strategies`'s own `required_fee_coefficient`) —
passed through to `FeeDriftProbeActor(documented_fee_coefficient=...)`. The
Actor's own constructor parameter name (`documented_fee_coefficient`) is
UNCHANGED: an existing test
(`test_documented_fee_coefficient_default_is_byte_identical_to_the_pin`)
pins its default to `DOCUMENTED_TAKER_FEE_COEFFICIENT`, and no caller or test
needed the rename, so the minimal diff keeps the name. Dedupe state
(`_last_mismatch_wire_fee`, `_last_mismatch_alert_ts_ns`) is added to
`FeeDriftProbeActor.__init__`.

## Invariants held

- Nautilus Trader is immutable: the dedupe window is timed via the Actor's
  own public `self.clock.timestamp_ns()` (the SAME native clock
  `on_start`/`_arm_timer` already use), never a new clock or wall time.
- No operator-reserved control (budget, per-position cap) is touched or
  assigned.
- The NO-SEND execution-egress firewall is untouched; only the alert
  event-name surface (X1) is widened, exactly as AUD-12b's own alerting
  additions were.
- No safety, settlement, or contract test was weakened, skipped, or deleted.
  Three pre-existing tests that exercise a DISAGREE
  (`test_probe_once_disagrees_alerts_critical_and_halts`,
  `test_probe_once_never_raises_when_the_halt_set_write_itself_fails`,
  `test_disagree_persists_the_halt_through_a_real_trial_day_latch_and_the_veto_then_refuses`
  in `tests/unit/test_fee_drift_probe.py`, plus
  `test_disagree_reaches_the_same_latch_the_submit_veto_reads_and_alerts_once`
  in `tests/unit/test_app_trade_fee_drift_probe_wiring.py`) were updated to
  register a `TestClock` before calling `probe_once()` directly, because the
  new dedupe logic reads `self.clock` — their assertions are unchanged and
  no strictness was removed.

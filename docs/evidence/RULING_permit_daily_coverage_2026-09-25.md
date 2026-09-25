# RULING — bound cumulative daily live-trading permit coverage (A-1)

**Slug:** `permit_daily_coverage` · **Date:** 2026-09-25 · **Author:** security-reviewer, adjusted per trading-bot-architect design review (same date, pre-implementation)

Status: IMPLEMENTED 2026-09-25 on branch `backlog/permit-daily-ceiling-2026-09-25`. Not yet enforced against a live node (the family remains halted per the 09-24 A1 ruling); this closes the A-1 defect so a future halt-lift does not reintroduce it.

## 1. The defect

`docs/plans/POST_FORECAST_PHASE_2026-09-20.md:103-118` (Amendment A, A-1)
requires that any second daily process carry "cumulative daily permit
coverage <= `PERMIT_TTL_NS` + spawn grace." The mid-day relaunch
(`docs/plans/MIDDAY_RELAUNCH_2026-09-15.md:100`, merge `eed0f4c`) admits "no
durable per-day singleton latch blocking re-issue": `_do_midday_watch`
(`src/breezy/runtime/trade_supervisor.py`) spawns a fresh node on a
transient mid-day failure, and that fresh node mints a fresh, full
`PERMIT_TTL_NS` (10 h) permit at `app/trade.py:main()` ->
`issue_live_trading_permit` (`safety.py`), with no anchor to the day's
first boot. Worst case (a boot near the start of the mid-day window plus
repeated relaunches) approaches ~18-20 h of cumulative coverage in a single
trading day — the TTL constant survives literally while the property it
exists to enforce (bounded unattended spend authority) is voided.

## 2. Remedy

A mid-day-relaunched child's permit is now **clamped**, never re-minted
fresh:

- `safety.py::issue_live_trading_permit` gains `max_expires_at_ns: int |
  None = None` (keyword-only, tightening-only). When set,
  `expires_at_ns = min(issued_at_ns + PERMIT_TTL_NS, max_expires_at_ns)`.
  A `max_expires_at_ns` at or before the sampled `issued_at_ns` **raises**
  `LiveTradingPermissionError` rather than truncating to a past or
  zero-length expiry — the permit is refused, not minted lapsed, so
  self-check's `FAIL_SHADOW_MODE_NO_PERMIT` detector fires exactly as it
  would for any other refused permit. This function still takes no `env`
  parameter and reads no environment variable itself; the ceiling is
  resolved by the caller only.
- `app/trade.py::main()` resolves `BREEZY_PERMIT_EXPIRY_CEILING_NS` (a
  supervisor-injected env var, strict non-negative-integer parse) and
  passes it as `max_expires_at_ns`. Absent -> `None` (byte-identical prior
  behaviour: the 16:50Z daily boot). Malformed -> the SAME
  `LiveTradingPermissionError` refusal/shadow-mode/WARN-alert path every
  other mint precondition already uses.
- `trade_supervisor_core.DaySchedulerState` gains a **distinct** field,
  `first_boot_permit_expires_at_ns`, with its own first-seen-wins latch
  function `record_first_boot_permit_seen` (same `_for_day`/idempotent
  shape as the existing `record_permit_issued_seen`). It is deliberately
  **not** included in any `replace(...)` call inside `record_child_adopted`
  or the relaunch recorders that reuse it (`record_relaunch_attempt`,
  `record_midday_relaunch_attempt`), so it survives every mid-day relaunch
  unchanged for the rest of the trading day. It resets only at the
  `_for_day` trading-day boundary, identically to every other field on
  `DaySchedulerState` (verified for the 00:00-16:40Z case in §4 below).
- `_do_midday_watch` carries an explicit fail-closed gate, checked FIRST
  and unconditionally — before `decide_midday_relaunch` and before
  `ports.spawn`, independent of the attempt-budget/window decision: if
  `state.first_boot_permit_expires_at_ns is None`, the relaunch is
  declined, a CRITICAL `MIDDAY_RELAUNCH_CEILING_UNKNOWN` alert fires
  (gated to once per day via `midday_ceiling_unknown_alert_sent`), and
  `tracked_pid` is returned unchanged (never `None`, matching this
  function's existing decline contract). When the anchor IS known, the
  spawned child's environment is a **copy** of `os.environ` with
  `BREEZY_PERMIT_EXPIRY_CEILING_NS` set to the anchor — `os.environ` itself
  is never mutated.
- `_do_launch` (the 16:50Z daily boot) is unchanged: it still forwards
  `env=os.environ` as-is, so it never carries a ceiling, pinned by a new
  regression test (`test_daily_boot_launch_spawn_env_carries_no_ceiling`).

## 3. Fail-closed choice for an unknown first-boot anchor

Two options were on the table: (a) decline the relaunch outright, or (b)
relaunch with `max_expires_at_ns = now` so the child boots but its permit
is immediately refused (shadow mode). **Chosen: (a), decline outright.**
The ruling's own language — "do not relaunch a sending node without a
ceiling" — is closer to a literal instruction than a preference, and (a) is
strictly smaller: it spawns no process at all (no intent-lock contention,
no exec-client construction, no observation-actor subscriptions) rather
than a full node that boots, subscribes, and only then discovers it holds
no permit. (a) is also simpler to reason about and test: one guard clause
ahead of the existing decision/spawn code, versus threading a synthetic
"now" timestamp through the spawn path and then verifying by inference that
the safety-layer refusal actually fires downstream.

## 4. Accepted failure surfaces (explicit, not defects)

- **Anchor race:** if the FIRST child of the day dies between writing its
  `live-trading permit issued ...` log line and the supervisor's next poll
  observing it, `first_boot_permit_expires_at_ns` never latches for that
  trading day. Every mid-day relaunch for the rest of that day is then
  declined fail-closed (§2's gate), with exactly one CRITICAL alert. This
  is accepted: a day that cannot prove a coverage anchor gets a "no
  automated mid-day self-healing" day, not an unbounded one. The operator
  is alerted and can hand-relaunch (see below) if the situation warrants
  it.
- **Hand-launched nodes carry no ceiling.** A node started by
  `docs/plans/R8_OPERATOR_RUNBOOK.md` §(viii)'s hand-relaunch recipe
  (`systemd-run`/manual `subprocess.Popen` mirroring `spawn_node()`) is
  operator-attended and outside A-1's automated-relaunch threat model — the
  operator is a human in the loop at the moment of the decision, which is
  the control A-1 substitutes for automated relaunches. `R8_OPERATOR_RUNBOOK.md`
  is updated with one sentence noting that repeated hand relaunches in a
  single trading day reproduce the same cumulative-coverage gap A-1 closes
  for the automated path, and are the operator's own call.
- **Self-check liveness is unaffected.** `_do_self_check`'s permit-lapse
  detection reads a child's OWN latched `permit_issued_seen_expires_at_ns`
  (the pre-existing per-child field), never the new day-level anchor — no
  change to that logic was needed or made.
- **`_do_relaunch_check` (boot-window relaunch, before readiness) spawns
  without a ceiling.** Only `_do_midday_watch` injects
  `BREEZY_PERMIT_EXPIRY_CEILING_NS`; a bounded boot-window relaunch
  (<=`MAX_RELAUNCH_ATTEMPTS`=2, >=`MIN_RELAUNCH_GAP`=3 min apart, never
  at/after `RELAUNCH_CUTOFF_UTC`=17:00Z) still mints a fresh, unclamped,
  full-`PERMIT_TTL_NS` permit, and can be the child whose permit line
  latches `first_boot_permit_expires_at_ns` for the day if it is the
  first to log one. **Accepted:** every boot-window relaunch attempt
  occurs within minutes of the original 16:50Z boot and before
  17:00Z — so any two candidate anchors from this window are, at most,
  ~10 minutes apart. Cumulative daily coverage from this window therefore
  *clusters* around one ~10 h expiry rather than *stacking* additional
  ~10 h windows the way an unbounded mid-day relaunch would (the actual
  defect A-1 closes) — a few minutes of anchor jitter is not a material
  widening of daily coverage. Closing this fully would mean threading a
  ceiling through `_do_relaunch_check` too; deferred as out of scope for
  this change, and named here so a future reviewer does not mistake the
  omission for an oversight.

## 5. Follow-up (2026-09-25): daily-ceiling expiry is distinguishable from a refusal

silent-failure-hunter review: a relaunched child whose CLAMPED permit
expires shortly after boot (little headroom left under the ceiling)
produced the same `SelfCheckResult.FAIL_SHADOW_MODE_NO_PERMIT` /
`AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT` as a genuine refusal —
an operator paged on either would misdiagnose A-1's clamp working exactly
as designed as a broken permit path.

**Remedy (smallest change consistent with the existing closed
`SelfCheckResult`/`AlertDetail` vocabulary):** one new member on each enum,
`FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING` /
`SELF_CHECK_FAIL_SHADOW_MODE_PERMIT_EXPIRED_AT_DAILY_CEILING`, mapped in
`SELF_CHECK_ALERT_DETAIL` — it still alerts on every path the generic
member did, never silenced. `self_check()` gains one keyword-only
`permit_expiry_at_daily_ceiling: bool = False` (default preserves
byte-identical behaviour for every existing caller); when a would-be
`FAIL_SHADOW_MODE_NO_PERMIT` also has `permit_issued=True` and the caller
has determined the flag is set, the distinct result is returned instead.

`_do_self_check` computes the flag as: the observed (latched-or-live)
permit expiry equals `state.first_boot_permit_expires_at_ns` **and**
`state.relaunch_attempts > 0`. The `relaunch_attempts > 0` guard is
necessary, not cosmetic: for the ORIGINAL, never-relaunched boot child its
own permit expiry always equals the anchor too (the anchor is latched FROM
that very permit), so equality alone cannot distinguish "this permit IS
the anchor's source, and genuinely expired" (a real bug, still reported as
`FAIL_SHADOW_MODE_NO_PERMIT`) from "this permit was CLAMPED to a
pre-existing anchor" (A-1 working as designed) — a clamped permit's log
line is byte-identical in shape to a fresh one, so `relaunch_attempts` is
the only available signal. Tested at both the pure-`self_check()` level
(ceiling-match true/false) and the `_do_self_check` wiring level (a
never-relaunched child's genuinely expired permit still alerts the
generic detail; a relaunched child's ceiling-matched expiry alerts the
distinct one).

## 5. Tests (RED before GREEN, all passing after implementation)

- `tests/unit/test_polymarket_us_permit_issuance.py`: no-ceiling
  byte-identical behaviour; a ceiling before natural expiry clamps it; a
  ceiling after natural expiry never extends it; a ceiling at/before
  issuance refuses (raises), never mints a lapsed permit. The pre-existing
  signature-pin test (`test_no_issuer_parameter_can_supply_a_ceiling_or_an_
  environment`) is updated, not deleted, to name `max_expires_at_ns`
  explicitly as the one authorized, tightening-only exception.
- `tests/unit/test_app_trade_main_permit_logging.py`: a valid
  `BREEZY_PERMIT_EXPIRY_CEILING_NS` clamps the minted permit to exactly
  that value; a malformed value refuses the permit through the existing
  WARN-alert/shadow-mode path, never an unhandled exception.
- `tests/unit/test_trade_supervisor.py` (`TestFirstBootPermitAnchor`): the
  anchor survives three simulated mid-day relaunches unchanged even though
  each relaunched child logs a different, later permit expiry; an unknown
  anchor declines every relaunch and alerts exactly once (never re-alerts
  on a later poll); a permit line observed at 00:30Z anchors to the
  PREVIOUS trading day's state, not the new calendar date; the mid-day
  spawn environment carries the ceiling equal to the first-boot expiry
  (and is a copy, not a mutation, of `os.environ`); the 16:50Z daily boot
  spawn environment carries no ceiling at all. Five existing
  `TestDoMiddayWatch`/`TestWp0aLiveFamilyMiddayWatchAndReap` tests were
  updated to seed a first-boot anchor in their fixture setup (a new,
  correct precondition for a scenario they were not testing), not to
  remove or weaken any assertion.

## 6. Scope discipline

No change was made to Nautilus Trader, `allow_short`, live-trading
enablement, the operator-reserved caps, or the NO-SEND execution-egress
firewall. `issue_live_trading_permit` gained exactly one keyword-only
parameter that can only clamp an expiry earlier or refuse; every existing
call site that omits it is byte-identical to before this change (pinned by
`test_no_ceiling_is_byte_identical_to_prior_behaviour`).

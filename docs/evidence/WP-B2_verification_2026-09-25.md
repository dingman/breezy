# WP-B2 verification — 2026-09-25

Verified: commit `a49c7b4` (`feat(wp-b2)`), tip `2fa5274`. Ancestor check:
`git merge-base --is-ancestor a49c7b4 HEAD` → exit 0.

## Tests pass
`BREEZY_PYTHON=.venv/bin/python scripts/ci/run_tests_no_egress.sh
tests/unit/test_runtime_order_guard_permit_expiry.py -q` →
`..............` 14 passed, incl. A-5's
`test_the_exec_chokepoint_still_refuses_an_expired_permit_with_this_guard_passing`
(`tests/unit/test_runtime_order_guard_permit_expiry.py:315`).
No other WP-B2 test file found (`grep -rl "PermitExpiredRefusedError\|order_guard_permit_expiry"`).

## Refusal counting path
`BacktestOrderGuard.on_order_event` (`src/breezy/runtime/backtest_order_guard.py:282-297`)
increments `self.refusal_counts[name]` on `PermitExpiredRefusedError`. This is
**not** `strategy.weather_common.refusals.RefusalCounter`/`RefusalAlerter`
(the plan's phrasing) — confirmed by import-linter's layers contract
(`pyproject.toml` `[[tool.importlinter.contracts]]` "…layer direction",
`strategy` above `runtime`, "Runtime never imports strategy"), and the class
docstring at `backtest_order_guard.py:224-230` states this explicitly. On the
live path the refusal is surfaced via `_order_guard_reporter`
(`trade_cli.py:322-339`): stderr `FATAL` line, `record_fatal_exec_fault`, and
`logger.error`, identical to `PostOnlyRefusedError`/`NakedShortRefusedError`.
Correction: cite `refusal_counts` + `_order_guard_reporter`, not RefusalCounter.

## safety.py chokepoint test untouched
`git log --oneline a49c7b4..HEAD -- tests/unit/test_runtime_order_guard_permit_expiry.py`
→ empty (the chokepoint test lives in this file, not a separate `safety.py`
test file). `git log --oneline a49c7b4..HEAD -- src/breezy/adapters/polymarket_us/safety.py`
→ also empty. Untouched confirmed.

## A-6 — PINNED (plan cites a stale method name)
`ContinuousRungHoldBacktestStrategy._has_order_submission_permit` does not
exist anywhere in the tree (`grep -rn "_has_order_submission_permit"` hits
only a docstring in the test file, describing behaviour). The actual
override is `_submission_armed`
(`src/breezy/strategy/current_rung_hold/continuous_backtest_only.py:154-155`),
gated by `self._backtest_submit_enabled` — no permit object.
`test_the_backtest_strategy_override_stays_permit_object_free`
(`tests/unit/test_runtime_order_guard_permit_expiry.py:437-450`) asserts over
`inspect.getsource(ContinuousRungHoldBacktestStrategy)` (whole class, so it
covers `_submission_armed` too) that `"expires_at_ns"` and `"_PermitWithExpiry"`
never appear and `order_submission_permit=None` is passed to `super().__init__`;
ran green above. Verdict: **A-6 PINNED**, not unpinned.

## Live wiring — non-None permit confirmed
`app/trade.py::main` (2026-09-25 review): `order_submission_permit` stays
`None` unless `settings.orders_enabled_requested`; when requested,
`OrderSubmissionPermit.issue(...)` (`app/trade.py:695`) either returns a real
permit (`expires_at_ns` set) or raises `OrderSubmissionRefused`, which is
FATAL (`return EXIT_RUNTIME_ERROR`, `app/trade.py:701-703`) — `run()` is never
reached with a "requested but None" permit. `app/trade.py::run` threads it
through `phase1_sending_permit` (`strategy/current_rung_hold/composition.py:231-262`):
returns `permit` unchanged unless `phase0_shadow` is True. The result
(`sending_permit`) reaches `trade_cli.run(..., order_submission_permit=sending_permit)`
at `app/trade.py:566`, then `trade_cli._run_node` →
`install_live_order_guard(..., order_submission_permit=order_submission_permit,
clock=node.kernel.clock)` at `trade_cli.py:535-541`. **Only** live path with a
`None` permit at the guard is shadow mode (`orders_enabled_requested=False` or
`phase0_shadow=True`) — safe, because shadow strategies are constructed with
`order_submission_permit=None` and `phase0_permit_guard=True`
(`Phase0PermitForbiddenError` fail-closed), so nothing is armed to submit an
order in the first place; the expiry rule being inert has nothing to guard.

Verdict: VERIFIED (python-reviewer, read-only, 2026-09-25). Plan wording corrections: refusal routes via BacktestOrderGuard.refusal_counts + trade_cli._order_guard_reporter (not RefusalCounter/RefusalAlerter); A-6's method is `_submission_armed` (pinned by test_the_backtest_strategy_override_stays_permit_object_free).

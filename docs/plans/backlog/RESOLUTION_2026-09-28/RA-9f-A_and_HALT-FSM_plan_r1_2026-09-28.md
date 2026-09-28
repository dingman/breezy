<!-- Codex read-only output, rollout rollout-2026-09-28T17-36-00-01a0e916-7e7c-7811-83c2-516d1b47c309.jsonl -->

Premise correction: the host clock read `2026-09-28T17:39:29Z`, so the brief’s “about 15:30Z” is stale. The item facts still verify, so plans below.

**Plan A: RA-9f-A**
1. Verified problem: Backlog marks RA-9f-A BUILD for zero-look `UNDERPOWERED_NOT_REGISTERED` and forbids flipping `HORIZON_TOLLING_LANDED` ([PROGRESS.md](/home/jon/breezy/docs/core/PROGRESS.md:53)). The ruling fixes `H-OFFWINDOW-T4-2026-09` / `pm_us_crh_offwindow_price_only` ([RULING_RA-9](/home/jon/breezy/docs/evidence/RULING_RA-9_trigger4_offwindow_2026-09-27.md:108)) and says MDE `0.0964 > 0.04`, expected `UNDERPOWERED_NOT_REGISTERED` ([RULING_RA-9](/home/jon/breezy/docs/evidence/RULING_RA-9_trigger4_offwindow_2026-09-27.md:121)). Existing CLI only registers NO-side and archive-recal underpowered ids ([hypothesis_register.py](/home/jon/breezy/scripts/analysis/hypothesis_register.py:341)). Live ledger has 3 lines and no off-window id; observed via read-only grep on `/home/jon/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl`.

2. L-1 verdict: NATIVE insufficient/not applicable. Nautilus has no hypothesis registrar surface; the existing Breezy ledger is the right local mechanism. Ledger core already permits v3 zero-look UNDERPOWERED without the tolling flag ([hypothesis_ledger.py](/home/jon/breezy/src/breezy/analysis/hypothesis_ledger.py:1127), [hypothesis_ledger.py](/home/jon/breezy/src/breezy/analysis/hypothesis_ledger.py:1157)); the gap is the registrar/CLI dispatch.

3. Design: add an off-window registrar mirroring `register_no_side_underpowered`, with constants from the ruling, `programme_alpha_override=0.025`, `min_station_days=300`, MDE `0.0964`, bound `0.04`, fee `0.0695`, slippage `0.01`, qty `1`, statistic `MEAN_EXCESS_PER_TAKE`, and `require_status="UNDERPOWERED_NOT_REGISTERED"`. Do not modify `HORIZON_TOLLING_LANDED=False` ([hypothesis_ledger.py](/home/jon/breezy/src/breezy/analysis/hypothesis_ledger.py:157)). Prefer deriving `freeze_commit` from clean `git rev-parse HEAD` at one-time append, because the ruling wants the commit that lands the call ([RULING_RA-9](/home/jon/breezy/docs/evidence/RULING_RA-9_trigger4_offwindow_2026-09-27.md:119)).

4. Files/functions touched: `scripts/analysis/hypothesis_register.py`: constants, `register_offwindow_t4_underpowered`, `_UNDERPOWERED_REGISTRATIONS`, CLI validation. `tests/unit/test_hypothesis_register.py`: off-window tests only.

5. RED tests: `test_offwindow_t4_constants_match_ruling_lines`: pins id/class/MDE/bound/alpha text. `test_register_underpowered_offwindow_t4_writes_zero_look_record`: asserts status, zero alpha/slot, qty/statistic/fee/slippage. `test_offwindow_t4_duplicate_cli_leaves_file_bytes_unchanged`: second run leaves bytes unchanged. `test_offwindow_t4_unexpected_registered_status_leaves_bytes_unchanged`: monkeypatch bound high and assert refusal before write. `test_offwindow_t4_does_not_flip_horizon_tolling`: asserts imported flag remains False.

6. Acceptance: 1. New id appears in CLI choices. 2. First tmp-path append writes one zero-look record. 3. Duplicate leaves bytes unchanged. 4. Live append is run once by the coordinator/operator after merge; verify grep finds exactly one id and `sha256sum` before/after duplicate attempt is unchanged. 5. No flag flip.

7. Risks/blast radius: accidental Path B admission if `require_status` omitted; stale/wrong freeze commit; weakening duplicate/refusal tests. Do not relax existing exact-set ledger tests.

8. Rollout: code is available wherever the checkout is used; the one-time ledger append is manual, not node-managed. No live node kill. `breezy-hypothesis-triage.service` later reads the ledger, but append is a coordinator/operator command.

9. Open questions: freeze commit source. Recommended: derive current clean HEAD at append time and test it, rather than hardcoding an unknowable future commit.

**Plan B: HALT-FSM**
1. Verified problem: log shows four `InvalidStateTrigger('STOPPED -> START_COMPLETED')` entries. Code calls `self.stop()` inside `on_start` when the never-arm walk fails ([continuous_strategy.py](/home/jon/breezy/src/breezy/strategy/current_rung_hold/continuous_strategy.py:883)); family halt logs and records `family_halt_at_start` ([continuous_strategy.py](/home/jon/breezy/src/breezy/strategy/current_rung_hold/continuous_strategy.py:903)). Nautilus `start()` calls `_start`, then unconditionally triggers `START_COMPLETED` ([component.pyx](/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/common/component.pyx:1956)); `STOPPED -> START_COMPLETED` is not a valid transition ([component.pyx](/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/common/component.pyx:1628)).

2. L-1 verdict: NATIVE sufficient with a small Breezy use-site change. Do not patch Nautilus. Use native clock alert/timer API ([component.pyx](/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/common/component.pyx:373)) to defer `self.stop()` until after start returns RUNNING.

3. Design: replace `self.stop()` in startup-decline branches with `_request_deferred_startup_stop()`: log/record exactly as today, return from `on_start`, arm one one-shot alert at `now + small_delay_ns`, callback catches/logs exceptions and calls `self.stop()` only if running. `manage_stop` default is False ([config.py](/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/trading/config.py:61)), so stop does not market-exit by default.

4. Files/functions touched: `src/breezy/strategy/current_rung_hold/continuous_strategy.py`: `on_start`, new private helper/callback/constants. Tests in `tests/unit/test_continuous_rung_hold_fill_wiring.py` or `test_continuous_rung_hold_strategy.py`.

5. RED tests: `test_family_halt_start_defers_stop_without_invalid_state_trigger`: start halted strategy, fire TestClock alert, assert stopped, no `InvalidStateTrigger`, event count 1. `test_deferred_startup_stop_never_submits`: spy `submit_order`, halted start plus alert, assert no calls. `test_startup_stop_alert_is_one_shot`: repeated failing start path arms one alert name, not a timer loop.

6. Acceptance: 1. Halted boot still logs family halt. 2. `family_halt_at_start` still recorded. 3. No arm/submit. 4. No `STOPPED -> START_COMPLETED`. 5. Existing safety/NO-SEND tests unchanged.

7. Risks/blast radius: using synchronous `MessageBus.send` would reproduce the same lifecycle bug ([component.pyx](/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/common/component.pyx:2592)). Timer callback raises can be swallowed live per L-16, so callback must catch/log.

8. Rollout: next natural node/unit respawn loads it. Do not kill the live node. The active loader is `breezy-trade-supervisor.service`, not `breezy-trade.service`; it runs from `/home/jon/breezy` and starts the supervisor ([breezy-trade-supervisor.service](/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service:56), [breezy-trade-supervisor.service](/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service:139)).

9. Open questions: delay length. Recommended: 1 second for LiveClock safety, while tests fire it deterministically with `TestClock.advance_time`.
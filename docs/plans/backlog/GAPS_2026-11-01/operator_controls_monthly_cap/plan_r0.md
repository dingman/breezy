OPERATOR-CONTROLS-MONTHLY-CAP — r0, DRAFT  
Author: Codex. Proposed reviewers: python-reviewer and prediction-market-reviewer; reviews pending.

1. Objective + ROI mechanism

Add `BREEZY_MAX_MONTHLY_BUDGET_USD` as the third operator-reserved cap. It is the operator’s monthly loss bound that lets everything else be automated, using the existing pre-fee, gross-entry USD-cost unit—not net P&L. Existing cost calculation: [operator_controls.py:281](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:281).
The operator decides only DAY, POSITION and MONTH caps; sizing, family lifecycle and venue decisions belong to the bot. This supersedes older operator-only clauses: [PROGRESS.md:58](/home/jon/breezy/docs/core/PROGRESS.md:58).

2. Preconditions / dependencies

Build backlog #11 before any arm; it supplies the safety boundary for SIZE-UNDER-CAPS, AUTO-PROMOTE-RETIRE and KALSHI-ADAPTER. No ROI-LEDGER dependency or new service is needed: [PROGRESS.md:59](/home/jon/breezy/docs/core/PROGRESS.md:59).
The operator contract already names three controls, but implementation inventory contains two: [PROGRESS.md:19](/home/jon/breezy/docs/core/PROGRESS.md:19), [operator_controls.py:155](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:155).

3. Scope

Production files: `src/breezy/adapters/polymarket_us/operator_controls.py`, `src/breezy/adapters/polymarket_us/exec/client.py`, `src/breezy/runtime/order_enablement.py`, `src/breezy/app/trade.py`.
Supporting files: `operator.env.example`, `scripts/operator/print_operator_controls.py`, `docs/plans/R8_OPERATOR_RUNBOOK.md`, applicable tests and reviewed pin records.
Reuse the existing ledger, durable fill records/indexes, injected clock and lock. No new ledger, monetary unit, database, systemd unit, sizing policy or live-state change. Nautilus stays immutable; `allow_short=False`; NO-SEND barriers remain intact.

4. Implementation steps — builder; sequential RED → implementation → review → gates

A. Add the monthly NAME constant, inventory entry and zero-argument reader through `_read_operator_money`; never assign, infer, default or propose a cap value. Source remains the operator-owned gitignored `operator.env`, passed by reference through the existing supervisor environment: [supervisor.service:113](/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service:113).
Use the existing missing/blank/malformed/nonpositive refusal policy: [safety.py:526](/home/jon/breezy/src/breezy/adapters/polymarket_us/safety.py:526), [safety.py:545](/home/jon/breezy/src/breezy/adapters/polymarket_us/safety.py:545).
B. Read all three caps before applying ceilings on every entry authorization. Under the existing lock, deny when current UTC-calendar-month spend plus the candidate cost exceeds MONTH; equality passes. Keep daily/per-position comparisons, rounding and exception behavior unchanged: [operator_controls.py:535](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:535).
C. Extend `DailySpendLedger` with bounded daily spend buckets for the current UTC month; sum those buckets at authorization. Feed them through existing authorize/release/true-up/settle paths exactly once. Midnight resets daily accounting only; UTC month rollover expires prior-month totals. Preserve clock-rewind refusal and atomic check-and-book.
Do not sum `spent_today_usd()` across dates: it returns zero outside its active day, and day rollover discards prior bookings: [operator_controls.py:492](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:492), [operator_controls.py:688](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:688).
D. Extend boot recovery to walk existing day indexes from month-start through today plus the existing provider walk; deduplicate venue order IDs and restore monthly BUY spend. Keep today’s daily/permit seed unchanged; monthly historical spend must not debit today’s session allowance. Current recovery filters to today: [client.py:3009](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:3009), [client.py:3095](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:3095).
Preserve fail-closed index/record handling and idempotent seeding. Reconcile outstanding/ambiguous BUY exposure across midnight, restart and month-end without freeing unfilled risk or double-counting seeded partials; reuse existing registry/settlement hooks: [operator_controls.py:844](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:844).
E. Monthly exhaustion raises `LiveTradingPermissionError` naming only the control; it must not raise `DailyBudgetExhausted` or write a daily-exhaustion marker. Existing submit catches deny before dispatch; exits retain their current bypass and never replenish spend: [client.py:7852](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:7852).
F. Add monthly validation beside the startup cap checks: [order_enablement.py:211](/home/jon/breezy/src/breezy/runtime/order_enablement.py:211). After successful validation, emit an adjacent value-free startup line confirming DAY/POSITION/MONTH validation; preserve the existing permit-issued line and parser.
The inventory-driven presence report must include MONTH, with `<set>`/`<unset>` only: [print_operator_controls.py:45](/home/jon/breezy/scripts/operator/print_operator_controls.py:45). Add only an `<unset>` template entry; update runbook wording and correct stale contract references.

5. Frozen acceptance / PASS–KILL

PASS requires missing/unparseable MONTH to refuse startup and entry authorization; exact-cap admission; over-cap denial before sender invocation; no denied-order debit; no daily marker on monthly refusal; correct month/day/year/leap boundaries; restart-safe totals and outstanding exposure.
Daily/per-position regression behavior and session-ceiling derivations remain unchanged: [safety.py:569](/home/jon/breezy/src/breezy/adapters/polymarket_us/safety.py:569).
KILL delivery if history cannot establish conservative month headroom, any lifecycle path undercounts, or passing requires weakening a safety/pin/NO-SEND assertion. Cumulative records overwrite per order; never fabricate cross-month fill splits: [client.py:1051](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:1051).

6. RED-first tests and gate route

Add these tests before implementation; names below are proposed:
- `test_operator_reserved_controls.py`: `test_monthly_control_missing_or_invalid_refuses`, `test_monthly_budget_accumulates_across_utc_days`, `test_monthly_budget_exact_limit_and_over_limit`, `test_monthly_budget_resets_only_at_utc_month_boundary`, `test_concurrent_authorizations_never_overspend_month`.
- `test_daily_spend_ledger_open_exposure.py`: `test_monthly_release_true_up_and_cross_boundary_settle_count_once`, `test_month_roll_carries_unresolved_buy_exposure`.
- `test_polymarket_us_exec_client.py`: `test_restart_restores_month_spend_without_changing_daily_seed`, `test_month_seed_deduplicates_and_refuses_corrupt_history`, `test_cross_month_cumulative_fill_never_understates_headroom_usage`.
- `test_operator_caps_through_the_live_composition.py`: `test_monthly_exhaustion_denies_before_sender_without_daily_marker`; include an admitted sender-control case.
- `test_order_submission_permit_issuance.py`, `test_operator_env_file.py`, `test_app_trade_main_permit_logging.py`: monthly refusal, three-name presence/template coverage, value-free startup evidence.
Extend assignment-scan planted mutations, no-default readers and redaction matrices to MONTH. Tokens derive automatically, but existing planted forms/readers cover only two controls: [assignment_scan.py:390](/home/jon/breezy/tests/unit/test_operator_control_assignment_scan.py:390), [assignment_scan.py:756](/home/jon/breezy/tests/unit/test_operator_control_assignment_scan.py:756).
Synthetic cap values use only the existing whitelisted test seam; no global fallback fixture. Run focused files through `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/monthly-cap-focused`, then the full gate with a distinct in-tree basetemp. Record RED → GREEN → monthly-check mutation fails → restored GREEN; read actual EXIT and both phase results before push: [gate:210](/home/jon/breezy/scripts/ci/run_tests_no_egress.sh:210).

7. Pins / isolation / risks

Whole-file pins that will move:
- `operator_controls.py`, `exec/client.py`, `runtime/order_enablement.py`: [maker closure JSON:86](/home/jon/breezy/tests/unit/data/maker_stage0_c7_closure_pins.json:86), [JSON:73](/home/jon/breezy/tests/unit/data/maker_stage0_c7_closure_pins.json:73), [JSON:193](/home/jon/breezy/tests/unit/data/maker_stage0_c7_closure_pins.json:193); enforced by `test_verdict_closure_bytes_match_the_commit1_pin`: [test:82](/home/jon/breezy/tests/unit/test_maker_stage0_c7_scope.py:82).
- `exec/client.py`: `_EXEC_CLIENT_SHA256` at [manifest test:49](/home/jon/breezy/tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:49); checked at [test:173](/home/jon/breezy/tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:173) and consumed by [test_autonomy_envelope.py:934](/home/jon/breezy/tests/unit/test_autonomy_envelope.py:934).
The three source files also change `aut2.label`’s import-closure digest: [closure_manifest.py:22](/home/jon/breezy/src/breezy/persistence/autonomy/closure_manifest.py:22), [pins.py:45](/home/jon/breezy/src/breezy/persistence/autonomy/pins.py:45), enforced by [test_autonomy_pins.py:599](/home/jon/breezy/tests/unit/test_autonomy_pins.py:599). Recompute affected closures; do not blindly repin health.
Review digest changes explicitly; preserve exact equality, closure membership and EXEMPT sets. Generated records come from their writer.
Landing this plan’s literal control name requires a separately reviewed exact prose-census entry, including its matching equality assertion: [assignment_scan.py:625](/home/jon/breezy/tests/unit/test_operator_control_assignment_scan.py:625), [assignment_scan.py:650](/home/jon/breezy/tests/unit/test_operator_control_assignment_scan.py:650). No directory exemption.
Existing ownership is process-local; retain the current single-owner execution boundary. Do not claim a cross-process or cross-venue portfolio bound.

8. Operator decisions

Only the three cap values. MONTH remains unset until supplied by the operator; code and agents neither choose nor suggest it. All engineering choices and bot decisions proceed within those caps.

9. Unverified / execution limits

Codegraph and Sequential Thinking tools were unavailable; citations above were verified by direct read-only source inspection.
No implementation, tests, gate runs, live checks or file writes occurred. Proposed test names do not yet exist.
Historical month completeness and cross-month cumulative-fill attribution remain to be proved by the specified RED tests.

Codex session ID: 01a199a7-0e4a-7e13-8ea0-d47e4ff896d4
Resume in Codex: codex resume 01a199a7-0e4a-7e13-8ea0-d47e4ff896d4

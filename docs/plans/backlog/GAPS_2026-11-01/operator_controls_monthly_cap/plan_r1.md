| Finding → | Resolution |
|---|---|
| Security 1 — daily seed is one-shot | §4D adds independent, one-shot `seed_month_spent(buckets)` with conservative `max` semantics; daily seeding never also increments MONTH. |
| Security 2 — missing historical indexes | §4D walks day and per-instrument indexes, deduplicates orders, attributes whole cumulative cost by `ts_event`, and refuses incomplete month coverage. |
| Security 3 — reader order/error inheritance | §4B and §6 require three-cap validation before comparisons and a monthly exception outside `DailyBudgetExhausted`. |
| Security 4 — permit scope/pins | §3 excludes `safety.py` and permit payload changes. §4E names validation and logging edits; §7 checks `trade.py` impact without inventing closure membership. |
| Security 5 — supervisor propagation | §4A cites whole-file environment forwarding; §6 adds an isolated supervisor-child refusal test with MONTH absent. |
| Security 6 — ownership/locking | §4C uses the same ledger instance and lock for DAY and MONTH. |
| Security LOW — late costs/accessor/isolation | §5 limits the guarantee to admission accounting; §6 covers accessor guards. Public true-up rejects costs above authorization; later settlement discovery remains a separate risk. |
| Python 1 — commit order/pin membership | §7 requires code first, then one reviewed `chore(pins)` commit; records current C7/manifest exclusions and requires graph confirmation. |
| Python 2 — accumulator/cross-day settle | §4C uses one monthly accumulator; dated buckets exist only during recovery. Prior-day registered settlements use separate month accounting, preserving the daily booking guard. |
| Python 3 — invalid values/boundaries | §6 names parameterized invalid-input tests and nanosecond, leap-year and year-boundary cases, written RED-first. |
| Python 4 — exact edit sites/messages | §4D corrects constructor assignment to `client.py:2210`, distinguishes boot invocation from seed implementation, and §4E names message/log sites and affected tests. |
| Python 5 — stale citations | Direct reads checked authorization at `operator_controls.py:535`, settlement at `:844`, derivation at `safety.py:569`, and gate phase initialization at `run_tests_no_egress.sh:210`; required graph verification remains open. |
| Python 6 — gate discipline | §6 requires distinct in-tree basetemps, separate execution/readout, both phase results and EXIT before push, then exact-directory cleanup. |
| Python LOW — precedence/isolation/census | §4B freezes DAY-before-MONTH precedence; §6 includes both isolation guards; §7 separates the reviewed prose-census commit. |

**OPERATOR-CONTROLS-MONTHLY-CAP — r1, DRAFT; reconciles security-reviewer and python-reviewer reviews; reapproval pending.**
Read-only planning result: no files changed, created or staged; no tests or live actions executed. Codegraph and Sequential Thinking are unavailable; code references below are direct-read evidence with graph verification outstanding.

**1. Objective + ROI mechanism**
GOAL STATE: every BUY authorization validates DAY, POSITION and MONTH and conservatively accounts for current-month entry commitments before dispatch.
MONTH is a UTC-calendar-month gross-entry premium admission ceiling, using cent-up `price × quantity`; it is neither net P&L nor a fee-inclusive realized-loss guarantee. Unit reference: [operator_controls.py:281](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:281).
ROI mechanism: constrain capital consumption while enabling SIZE-UNDER-CAPS and AUTO-PROMOTE-RETIRE to turn independently demonstrated edges into dollars; this change establishes no edge or profitability.

**2. Preconditions / dependencies**
Build backlog #11 before any arm; downstream consumers are #5 SIZE-UNDER-CAPS, #7 AUTO-PROMOTE-RETIRE and #8 KALSHI-ADAPTER. #11 has no ROI-LEDGER dependency: [PROGRESS.md:58](/home/jon/breezy/docs/core/PROGRESS.md:58).
Before implementation, restore required graph access, verify every referenced symbol/caller and closure, complete Sequential Thinking analysis and plan review, and obtain the two reviewer approvals.
Preserve the existing harness boundary; any necessary exception is resolved through the engineering peer loop, never converted into another operator decision.

**3. Scope**
Edit `src/breezy/adapters/polymarket_us/operator_controls.py`, `src/breezy/adapters/polymarket_us/exec/client.py`, `src/breezy/runtime/order_enablement.py`, and the adjacent startup logging in `src/breezy/app/trade.py`.
Supporting scope: `operator.env.example`, `docs/plans/R8_OPERATOR_RUNBOOK.md`, focused tests, exact prose-census records and reviewed generated pins. Keep `scripts/operator/print_operator_controls.py` behavior inventory-driven; edit only stale wording if needed.
Do not edit `safety.py`, alter permit payload v2 or add MONTH to permit-ceiling derivations; existing derivations remain at [safety.py:569](/home/jon/breezy/src/breezy/adapters/polymarket_us/safety.py:569).
Reuse the ledger, registry, durable records, clock and lock. No new ledger, database, unit, service, sizing policy, live enablement change or sender/firewall change.

**4. Implementation steps — builder; A→E, RED before each behavior change**
A. Add the NAME `BREEZY_MAX_MONTHLY_BUDGET_USD`, inventory membership and zero-argument reader through `_read_operator_money`; never assign, default, infer or propose its value. Reader/inventory extension points: [operator_controls.py:155](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:155), [operator_controls.py:198](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:198).
The sole production source is operator-owned gitignored `operator.env`, forwarded by reference, never written by the bot. Direct reads show whole-file loading at [supervisor.service:113](/home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service:113) and unfiltered child forwarding at [trade_supervisor.py:1133](/home/jon/breezy/src/breezy/runtime/trade_supervisor.py:1133).
B. Read DAY, POSITION and MONTH before any cap comparison on every entry authorization. Retain POSITION-first and existing clock/DAY checks; then check MONTH before booking. If DAY and MONTH both breach, DAY wins; a MONTH-only breach must never mark daily exhaustion.
Under the same lock, admit equality and deny `month_spent + uncharged_month_exposure + candidate > MONTH`; unknown exposure refuses. No candidate debit occurs on denial. Preserve existing daily exposure checks: [operator_controls.py:535](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:535).
Use `MonthlyBudgetExhausted(LiveTradingPermissionError)`, explicitly outside the `DailyBudgetExhausted` inheritance tree; its message names only the control. Existing typed submit catches are at [client.py:7873](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:7873).
C. Add one `(month_key, month_spent_usd)` accumulator to the existing `DailySpendLedger`, using its existing lock. Recovery buckets are transient inputs, not persistent daily buckets or another ledger: [operator_controls.py:446](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:446).
Book MONTH at authorization; reverse an unspent reservation on confirmed release; replace its charged contribution on true-up/settlement exactly once. Preserve sufficient per-open-entry monthly charge/seed metadata to distinguish amounts already counted from remaining exposure.
UTC midnight resets DAY only. Month rollover resets historical MONTH spend, while unresolved BUY exposure remains conservatively included in monthly admission until reconciled; never clear unknown/AMBIGUOUS risk to create headroom.
Keep `_require_open_booking`'s daily restriction intact. For a registered prior-day settlement in the same month, adjust its retained monthly contribution under the same lock through a month-specific helper; do not pass it through the daily booking helper: [operator_controls.py:573](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:573).
Settlement computes daily and monthly deltas before mutation; every validation failure leaves both totals and registry unchanged. Preserve exactly-once terminal handling and clock high-water rules: [operator_controls.py:844](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:844).
D. Extend `_seed_spend_from_durable_fills` at [client.py:3047](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:3047), invoked during boot at [client.py:2743](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:2743); constructor assignment is [client.py:2210](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:2210).
Walk month-start through today’s `FILL_BY_DAY` indexes plus the existing provider per-instrument `FILL_INDEX` walk. Deduplicate by venue order ID; include monthly BUY records; attribute each whole `cumulative_cost` to its `ts_event` UTC day. Preserve today’s existing daily/permit seed computation.
Add `seed_month_spent(buckets, now_ns)` with its own successful-once flag, strict bucket validation and `max(current, recovered)` semantics. Today contributes once to MONTH through this method; `seed_spent` remains DAY-only. Recovery is completed before entry admission.
Require demonstrable day-index coverage back to month start. Missing historical coverage, unreadable indexes or missing/corrupt referenced records means KILL/refuse-to-arm; absence is never evidence of zero spend. Existing index reads collapse absence to `[]`: [client.py:6715](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:6715).
The provider walk supplements coverage; it does not prove completeness for unloaded historical instruments. If the existing durable data cannot establish coverage, stop delivery and report the evidence gap; never fabricate empty indexes or authorize a reset.
Track monthly seeded partials separately from daily seeded partials when restoring open intents; subtract only amounts actually included in the relevant accumulator: [client.py:2934](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:2934).
Cumulative records do not provide exact cross-month fill splits. Charge the whole cumulative cost to its recorded event month conservatively, retain prior-month charges, and refuse if lifecycle/restart equivalence cannot be proved: [client.py:1051](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:1051).
E. Add MONTH validation in `OrderSubmissionPermit.issue`; change the refusal to “all three operator-reserved caps must be present and positive”: [order_enablement.py:211](/home/jon/breezy/src/breezy/runtime/order_enablement.py:211).
Add an adjacent value-free “operator caps validated DAY/POSITION/MONTH” startup line only after successful validation; preserve the existing permit-issued line and parser at [trade.py:1527](/home/jon/breezy/src/breezy/app/trade.py:1527).
Cover the changed refusal in `test_operator_caps_absent_refuses` and `test_operator_caps_and_rung_hold_messages_name_no_value`: [permit tests:180](/home/jon/breezy/tests/unit/test_order_submission_permit_issuance.py:180), [permit tests:298](/home/jon/breezy/tests/unit/test_order_submission_permit_issuance.py:298).
Add only an `<unset>` template entry; presence output remains `<set>`/`<unset>` through inventory iteration: [print_operator_controls.py:45](/home/jon/breezy/scripts/operator/print_operator_controls.py:45).
Timing/output: builder records elapsed time per A–E and produces diff plus RED/GREEN evidence; reviewers assess accounting and isolation before the full gate.

**5. Frozen acceptance / PASS–KILL**
PASS requires startup and entry refusal for absent/invalid MONTH; exact-cap admission; over-cap refusal before sender invocation; no denied-candidate debit; no daily marker for MONTH-only exhaustion; conservative recovery and unresolved-risk accounting.
Require correct day/month/year/leap transitions, duplicate recovery/settlement safety, unchanged daily/position and session-ceiling behavior, unchanged SELL bypass and no replenishment from exit proceeds: [client.py:7852](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:7852).
Admission is the proved boundary. Public true-up rejects realized cost above authorization ([operator_controls.py:662](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:662)); later discovered uncharged settlement cost can exceed a previously observed ceiling ([operator_controls.py:901](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:901)). Record it and deny further entries; never hide it or claim a hard realized-loss bound.
KILL delivery on incomplete historical coverage, underestimated exposure, inconsistent restart accounting, or any requirement to weaken safety, settlement, contract, pin or NO-SEND assertions.

**6. Tests — proposed additions, RED-first; characterizations require mutation evidence**
In `tests/unit/test_operator_reserved_controls.py`, parameterize MONTH refusal over missing, empty, whitespace, nonnumeric, negative and zero; cover three-reader-before-comparison behavior, exact/over limit, simultaneous DAY/MONTH precedence and concurrent admission.
Add `test_month_rolls_at_utc_midnight_of_the_first`: Jan 31 23:59:59.999999999 versus Feb 1 00:00:00 UTC; include leap-February and December/January boundaries.
Test same-month day rollover, clock rewind refusal and monthly accessor returning zero outside its active month without mutation; parallel the existing daily accessor contract: [operator_controls.py:492](/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py:492).
In `test_daily_spend_ledger_open_exposure.py`, cover release/true-up, prior-day same-month settlement, month-crossing OPEN/AMBIGUOUS exposure, seeded partials, duplicate settlement and atomic failure.
In `test_polymarket_us_exec_client.py`, cover one-shot monthly seed/max semantics, today counted once, unchanged daily/session seed, BUY-only monthly recovery, duplicate indexes, missing pre-AC6b coverage, unloaded historical instruments, corrupt records and cross-month cumulative attribution.
In `test_operator_caps_through_the_live_composition.py`, prove MONTH-only denial reaches neither sender nor daily-marker writer; include an admitted sender positive control and DAY+MONTH precedence.
Use the real supervisor spawn seam in an isolated child test: synthetic operator-file input lacks MONTH; startup/first-order attempt refuses without dispatch. Do not launch or restart the production supervisor.
Extend `test_order_submission_permit_issuance.py`, `test_operator_env_file.py` and `test_app_trade_main_permit_logging.py` for three-control validation, unchanged legacy parser, value-free logging and no success line on refusal.
Extend MONTH assignment mutations, zero-argument reader checks and redaction matrices; synthetic cap inputs use only the existing whitelisted test seam, never a global fallback fixture: [assignment scan:390](/home/jon/breezy/tests/unit/test_operator_control_assignment_scan.py:390), [assignment scan:756](/home/jon/breezy/tests/unit/test_operator_control_assignment_scan.py:756).
Run focused files and both isolation guards, `test_polymarket_us_readonly_guard.py` and `test_execution_egress_firewall_guard.py`, through `scripts/ci/run_tests_no_egress.sh` with in-tree basetemp `/home/jon/breezy/.pytest-tmp/monthly-cap-focused`.
Record RED → GREEN → monthly-check mutation fails → restored GREEN. Then run `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/monthly-cap-full`.
Run gate and readout separately, never chained; require actual EXIT and phase1/phase2 success before push. Phase2 starts at line 210; combined reporting is line 212: [gate:210](/home/jon/breezy/scripts/ci/run_tests_no_egress.sh:210).
After reading results, remove only the exact task basetemp directories. Record remaining failures individually; a deferred phase is not a completed gate.

**7. Pins / isolation / risks**
Code commit first; then ONE separately reviewed `chore(pins)` commit for affected digests, citing the 2026-11-02 ruling and [L-12’s 2026-10-20 addendum](/home/jon/breezy/docs/core/LESSONS.md:64).
Named pins: C7 JSON entries for client/operator-controls/order-enablement at [JSON:73](/home/jon/breezy/tests/unit/data/maker_stage0_c7_closure_pins.json:73), [JSON:86](/home/jon/breezy/tests/unit/data/maker_stage0_c7_closure_pins.json:86), [JSON:193](/home/jon/breezy/tests/unit/data/maker_stage0_c7_closure_pins.json:193); `_EXEC_CLIENT_SHA256` at [manifest test:49](/home/jon/breezy/tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py:49); `aut2.label` at [pins.py:45](/home/jon/breezy/src/breezy/persistence/autonomy/pins.py:45).
Direct inspection finds neither `app/trade.py` nor `print_operator_controls.py` in the committed C7 JSON or closure manifest. `test_app_trade_main_permit_logging.py` supplies behavioral assertions, not a discovered byte pin; graph verification and repository-wide pin census remain required.
Recompute all affected closures, explicitly including impact checks for `trade.py` and the print script. Do not add them to `aut2.label` by assumption or blindly repin health; manifest source is [closure_manifest.py:9](/home/jon/breezy/src/breezy/persistence/autonomy/closure_manifest.py:9).
Preserve exact closure membership, digest equality and EXEMPT sets: [C7 test:82](/home/jon/breezy/tests/unit/test_maker_stage0_c7_scope.py:82), [autonomy test:599](/home/jon/breezy/tests/unit/test_autonomy_pins.py:599). Regenerate machine-written records through their writers.
Land literal-name prose-census changes in their own reviewed commit, including matching equality assertions for every newly named path; no directory exemptions: [assignment scan:625](/home/jon/breezy/tests/unit/test_operator_control_assignment_scan.py:625), [assignment scan:650](/home/jon/breezy/tests/unit/test_operator_control_assignment_scan.py:650).
Maintain one process owner, one ledger instance and one lock. This item proves no cross-process or cross-venue portfolio bound; #8 must integrate shared consumption before enabling another venue.
Nautilus immutable; `allow_short=False`; existing harness only; Kelly banned; PREREG/holdout rulings unchanged; no live-state/firewall changes, credentials/order IDs in committed evidence, or `iem_cli_fetch.fetch` calls.

**8. Operator decisions**
Exactly three cap values: max USD per DAY, per POSITION and per MONTH, supplied only in gitignored `operator.env`. Code and agents never assign, default or propose them.
The bot decides sizing within caps, family lifecycle, venue enablement and everything else, subject to tested safety gates. Missing MONTH means refusal, never another approval question or a suggested value.

**9. Citations not verified / execution limits**
Required `mcp__codegraph__codegraph_explore(projectPath=/home/jon/breezy)` is unavailable; every code citation above remains graph-unverified despite direct inspection.
Complete pin/closure blast radius, historical month coverage and conservative cross-month recovery remain unproved; failure to establish them blocks implementation acceptance.
Sequential Thinking analysis/review could not run; no implementation, tests, mutations, gate runs or live verification occurred. All new test names and behavior are proposals.

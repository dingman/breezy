# T-4 — `_equity()` is unobserved, and nothing says so

Design plan, 2026-09-02. **Revision 2.** No source edits. Nautilus 1.231.0 immutable. Baseline `dbd91d9`. `weather_common/risk.py` is edited concurrently (T-3); its line numbers are provisional and re-resolved at implementation time.

**Changelog (R1 -> R2).** (1) **Both new refusals — and the whole equity block — are gated `signed_qty_delta > 0`**; R1 would have gagged the exit (§D2, and see the interaction in §1 note). (2) §0 severity **corrected downward and re-derived**: `contract_size = 1.0`, so the cap is in contracts, and `max_position_contracts` dominates above E = $3,125; real live-small cost is **2.6x, not 8.3x**. (3) "a correct measurement of ruin" **withdrawn** — `currentBalance` vs `assetNotional` is UNVERIFIED (§4). (4) Census corrected to **89/40/49**; two missed sites named (§3). (5) D1's backtest asymmetry upgraded from argued to **measured**. (6) mypy stated plainly as **partial** enforcement, with a guard test (RED-12). (7) RED-9/10/11/12 added; one candidate demoted to a pin. (8) D4's staleness bound promoted to a **go-live precondition**. (9) L-12 widening **verified** at the barrier; equity gate is `risk.py:557`.

## 0. Verdict on severity — real, bounded, and smaller than the finding said

**HIGH as a go-live precondition, not a live hole.** All three live node configs pass `strategies=[]` (`node_config.py:229, 480, 699`) and `RiskManager` has zero occurrences under `runtime/`/`cli/`. Nothing here can trade today; it blocks R-7/go-live and nothing else.

**Corrected magnitude.** `contract_size = 1.0`, so `order_notional` is a **contract count / max payout, not cash**. The cap is `0.08 x equity` *contracts*, and `max_position_contracts = 250` dominates it above **E = $3,125**. At the fabricated $10,000 the equity cap is 800 contracts and therefore **inert** — the operator cap binds. The damage lives entirely *below* $3,125, which is exactly live-small territory: at a true $1,200 the cap authorises 250 against an intended 96, **2.6x**. Cash bite is price-dependent — 250 contracts at a 5c ask is $12.50, at 0.90 it is $225 — so the harm is real, bounded, and worst at high asks. (Supersedes the finding's 8.3x, already corrected there.)

**The two mechanisms are not equal.** *Fabricated* is bounded on live: `_connect` publishes the account, `_confirm_account_registered` (`exec/client.py:703`) bounded-waits for it in the cache and latches a node-global refusal otherwise, and `Portfolio.account` is cache-backed (`portfolio.pyx:816-832`) — the event satisfying that wait is the one `_equity()` reads. *Stale* is bounded by nothing: `Portfolio.update_order` returns at `portfolio.pyx:502` before touching a balance when `calculate_account_state` is false, and `QueryAccount` has one framework-wide emitter, `Strategy.query_account` (`trading/strategy.pyx:1492-1524`), called by no Breezy strategy.

**A third mechanism the finding missed.** At `risk.py:557`, `if portfolio.equity > 0 and order_notional > limits.max_equity_fraction * portfolio.equity` — at `equity == 0.0` the cap **evaporates**: no clip, no refusal, full size. R1 called that "a correct measurement of ruin"; **withdrawn** — see §4. What survives is narrower and sufficient: **zero cash must refuse a new BUY**, whatever zero cash means. Fourth: `PortfolioSnapshot` carries its own `equity: float = 10_000.0` default (`risk.py:174`), so 49 sites fabricate equity without going near a strategy.

Diagnosis, unchanged and approved: **`float` cannot express "unobserved", and the policy treats every float as a measurement.**

## 1. Decisions

### D1 — `_equity()` returns `float | None`; `starting_equity` is deleted

The trailing `return self._config.starting_equity` becomes `return None`. `starting_equity` is dead — nothing in `src/`, `scripts/` or `tests/` sets it — and is deleted from all five configs (`forecast_mispricing/config.py:100`, `calibration_mean_reversion:116`, `forecast_revision:113`, `running_extreme_lock:125`, `cli_settlement_print_lock:223`) with their docstring entries.

**Backtest does not need it — now MEASURED, not argued.** `BacktestEngine._run` calls `exchange.initialize_account()` (`backtest/engine.pyx:1605`) before data streaming, and `BacktestExecClient.__init__` calls `AccountFactory.register_calculated_account(...)` whenever `frozen_account` is false (`backtest/execution_client.pyx:83-84`; Breezy's `add_venue` never sets it). `calculate_account_state` is **True** in backtest; the full-suite simulation with calculated accounts confirms the balance is live there. **Backtest already observes; live is frozen at connect.** That asymmetry is the whole of T-4, and it is why a live-correct fix cannot break the harness.

*Rejected — keep it "backtest only"* (not needed there either; a live-reachable constant a config can re-enable is the defect). *Rejected — return `0.0`* (a real balance, and the value that disables the cap).

### D2 — `equity: float | None = None`; unobserved refuses, **buy side only**

`PortfolioSnapshot.equity` becomes `float | None`, default `None` = never observed. **The entire equity block at `risk.py:556-563` is gated `signed_qty_delta > 0`**, and inside it: `equity is None` -> `equity_unobserved`; `equity <= 0` -> `equity_nonpositive`. Both are added to `COUNTED_REFUSAL_REASONS` (`risk.py:61`) — a **widening**, which [[L-12]] requires and which the barrier permits: `test_weather_common_risk.py:1371` and `:1726` are both `<=`, `:1603` is membership, and `test_cage_rule_constants_are_pinned.py` says nothing about the set. **Verified.**

**Why buy-side-only, and why it must be the whole block, not just the refusals.** With `allow_short=False`, any sell surviving `risk.py:505-513` is *reducing*. Refusing it is the trap `:570-577` explicitly declines to create for the depth clip — "clipping an exit to that would trap positions the close-only guard exists to let out" — and `:578` is the buy-side-only precedent this follows. Gating only the refusals is not enough: the existing clip's own predicate is `portfolio.equity > 0`, which raises `TypeError` on `None`, so a sell would still die at the gate. Gating the whole block is therefore **required for correctness**, not a stylistic extension.

**It also closes a pre-existing exit trap, and that is a real behaviour change.** Today `signed_qty_delta = clipped if signed_qty_delta > 0 else -clipped` (`risk.py:563`) clips **sells too**: a reducing sell of 200 against an observed equity of $10 is clipped to 0.8 and then refused `equity_fraction`. That is the same failure class as `:570-577`, pre-existing and not created by T-4. It is in scope because the `None` guard cannot be added without touching the same predicate. It is also the one part of T-4 that can legitimately move a backtest — see the §3 gate.

**Predicted consequence for `test_calibration_mean_reversion_shorts_disabled_alert.py:193`:** its order is a **SELL** with `allow_short=True`, so under buy-side gating it skips the block entirely and is **predicted to need no change at all** — unlike the ungated simulation, where it failed on `refusals.total() == 0 -> 1` and `len(orders) == 1 -> 0`. Measure this; do not assume it. If it still fails, fix it with a stub venue account. **Relaxing either assertion is prohibited** — it is the control proving the shorts-disabled alert tracks the permission and not the market.

*Rejected — clip to a conservative floor* (trades on a number with no referent). *Rejected — required field, no default* (forces all 49 sites to change even where the value is never read).

### D3 — where the shared reader lives

New `src/breezy/strategy/weather_common/equity.py`: `observed_equity(cache, portfolio, nt_ids) -> float | None`. The five byte-identical bodies (`forecast_mispricing:441-452`, `calibration_mean_reversion:467-478`, `forecast_revision:463-474`, `running_extreme_lock:452-463`, `cli_settlement_print_lock:986-997`) are deleted and call it. T-1 D2's rejected alternatives are adopted, not re-derived: **not `risk.py`** (pure policy over a snapshot, imports no cache); **not a `WeatherStrategyBase` mixin** (speculative, no base exists). Additionally **not `inflight.py`** — its subject is working orders.

### D4 — refresh: deferred as an increment, but the staleness bound is a GO-LIVE PRECONDITION

Not wired in T-4. `query_account` is fire-and-forget (`strategy.pyx:1516-1524` -> `engine.pyx:1237-1238` -> `create_task`, `live/execution_client.py:329-333`), so per-tick calling yields last tick's balance; it needs an `AccountId`, so it cannot fix the fabricated case; and it puts a venue REST read (`ACCOUNT_BALANCES_PATH`, `exec/client.py:743`) on the decision path at an UNVERIFIED rate limit.

**But deferral is not indefinite.** A connect-time balance read days later is byte-identical to a fresh one, and §0 shows drift only matters below **E = $3,125** — i.e. throughout live-small. So go-live requires a bounded staleness rule: an observation timestamp on the snapshot, a bound on it, and a periodic `self.clock.set_timer` refresh. That is a second increment and a **precondition on R-7**, not an optional follow-up.

### D5 — `calculate_account_state=True` on live: REJECTED

Reconciled positions book at fabricated prices — 0.00 for an unpriced forward, or a cached `ask_price` (`live/execution_engine.py:2871-2877`) — so a locally-derived balance inherits that fabrication and is *confidently wrong* rather than merely stale (`exec/client.py`, invariant 2). Venue-reported balances stay authoritative. Secondary: `AccountFactory` registration is process-global by issuer (`accounting/factory.pyx:25, 78, 128`), not a per-client switch.

### D6 — refusal ordering stays; and the type change is PARTIAL enforcement

The new refusals sit at the existing gate position. Hoisting them would change which reason is recorded for an order violating two rules, silently redefining every `RefusalCounter` assertion.

**Say plainly what mypy does and does not buy.** Verified: an unguarded read in another method *is* caught — but `portfolio.equity or 0.0` **type-checks clean** and silently restores the exact fabrication T-4 removes, and mypy flags **zero** of the 49 default-reliant sites. The type change is a real but partial control, so the invariant is pinned by a guard test (RED-12), not by the annotation.

## 2. RED list — every entry can fail on today's tree, under the D2 gating

- **RED-1 / RED-2** (D1, x5 strategies) — `portfolio.account(venue)` is `None`; and account present but `balance_total` returns `None` (`accounting/accounts/base.pyx:226-260` returns `None`, never zero). Assert `None`. *Today:* `10_000.0`.
- **RED-3** (D2) — `PortfolioSnapshot().equity is None`. *Today:* literal `10_000.0` at `risk.py:174`.
- **RED-4 / 5 / 6** (D2, **BUY**) — `equity=None` -> `equity_unobserved`; `equity=0.0` and `equity=-1.0` -> `equity_nonpositive`. *Today:* `None > 0` raises `TypeError`; `0.0`/`-1.0` skip the cap and pass at full size.
- **RED-7** (D1, structural; precedent `test_backtest_harness_prose_guard.py`) — no `starting_equity` field or equity-fallback constant survives in the five configs. *Today:* present five times.
- **RED-8** (D2) — both reasons are in `COUNTED_REFUSAL_REASONS`, **and both are driven by `test_weather_common_risk.py:1214`**, whose header at `:1207-1211` claims it reaches every refusal branch — leaving them undriven makes that comment false.
- **RED-9** (§5 falsifier) — an `equity_unobserved` refusal logs its tick timestamp. *Today:* no such refusal exists; without it the §5 falsifier is unrunnable.
- **RED-10** (D2, **SELL**, exit not gagged) — settled long, `allow_short=False`, reducing sell, `equity=None`; assert no equity refusal and the order survives. *Today:* `None > 0` raises `TypeError`.
- **RED-11** (D2, **SELL**, exit trap) — settled long 200, reducing sell, observed `equity=10.0`, `max_equity_fraction=0.08`; assert the sell is neither clipped nor refused. *Today:* clipped to 0.8, then refused `equity_fraction` at `:561`.
- **RED-12** (D6 guard) — an AST guard over `risk.py` rejecting **both** a cap guarded by `equity > 0` (today's fail-open) and any `or`/truthiness-defaulted read of `equity` (tomorrow's regression). *Today:* the first pattern is present at `:557`.

**Listed and explicitly NOT RED — cannot fail today, so they are pins, not tests of the fix.** (a) A **SELL with `equity=0.0`** already passes today, because the cap is inert at zero; it pins D2's gating and nothing more. (b) The **backtest characterization** (`starting_balances=1_000` yields `1000.0`) — D1 is now measured, so this passes today by construction; it is the §3 regression gate.

## 3. Scope, sequencing, merge gate

Baseline: **5206 passed, 1 skipped, 4 deselected, 3 xfailed** (`scripts/ci/run_tests_no_egress.sh`).

0. **Land after T-3** — both edit `risk.py` and `test_weather_common_risk.py`.
1. `weather_common/equity.py` + tests (RED-1, RED-2).
2. `PortfolioSnapshot.equity -> float | None = None` (RED-3).
3. `risk.py`: gate the block `signed_qty_delta > 0`, add both refusals, widen `COUNTED_REFUSAL_REASONS`, drive both in `:1214` (RED-4..6, 8, 9, 10, 11, 12).
4. **Widen the no-equity constructions.** Census at `dbd91d9`: **89 sites / 40 with `equity=` / 49 without** (46 in `test_weather_common_risk.py`; one each in `test_cli_settlement_print_lock_decision.py`, `test_weather_strategy_backtest_lib.py`, `test_runtime_backtest_harness.py`). Only those reaching the equity gate need a value — **measure which**. Never delete or skip one.
5. **Two sites the census does not catch, both named explicitly.** (a) `tests/unit/test_weather_strategy_quote_staleness.py:99` — a strategy double whose `_portfolio_snapshot` returns `PortfolioSnapshot(equity=10_000.0)`, **re-fabricating the constant by hand**. It passes `equity`, so RED-3 and RED-7 both miss it, and it bypasses `observed_equity` entirely. Restate it as a named test constant with a comment saying it exercises no reader. (b) `tests/unit/test_calibration_mean_reversion_shorts_disabled_alert.py:193` — predicted to need no change under D2's gating; **measure, and if it fails, fix with a stub account, never by relaxing `refusals.total() == 0` or `len(orders) == 1`.**
6. **Widen the two in-flight harnesses.** `_SettledPositionPortfolio` (`test_weather_strategy_inflight_orders.py:143`, `test_forecast_mispricing_inflight_orders.py:104`) returns `account -> None` *specifically* to reach the fallback. Give it a stub account with a stated balance, preserving what T-1's tests measure.
7. Replace `_equity()` in all five strategies; delete `starting_equity` x5 (RED-7).

**MERGE GATE.** (a) Every RED green. (b) Total moves by exactly the tests added; `1 skipped / 4 deselected / 3 xfailed` unchanged; no pre-existing test flips except the widenings in steps 4-6. (c) **Integration backtest results byte-identical** across `tests/integration/*_backtest*.py` and `tests/contract/test_multi_instrument_weather_strategy.py`. **Disambiguation, because two changes can move this:** D1 is measured, so a move is *expected* to mean the newly-ungated sell path — a reducing sell that the two-sided clip was previously throttling. Confirm that by diffing sell-side clips before concluding anything; a move traceable to a **buy** falsifies D1 and the plan is re-argued on measured numbers. A moved count is never reconciled by weakening an assertion.

**Must not change:** `.venv/**/nautilus_trader/`; `allow_short`; any value of `max_daily_budget` or `max_position_contracts` (read-only, operator-reserved); `exec/client.py` behaviour (at most a cross-reference comment — its invariant-2 note cites `forecast_mispricing/strategy.py:419`, which moves); `calculate_account_state` anywhere; the NO-SEND execution-egress firewall and every barrier file; live-trading enablement; `net_qty`/`settled_qty`/`pending_qty` semantics; `starting_balances` in any fixture; edge, fee and break-even math. **No new egress path, no timer, no venue read** — D4 adds none of it here. **No Breezy-side equity ledger.**

## 4. Verification status

Verified: the five `_equity()` bodies and five `starting_equity` defaults; `balance_total`'s `None`-not-zero contract; `portfolio.pyx:502`; the single `QueryAccount` emitter; `Portfolio.account` cache-backed; `register_calculated_account` plus `initialize_account`-before-streaming (and D1 measured end-to-end); the `equity > 0` fail-open at `:557`; the two-sided clip at `:563`; the `10_000.0` snapshot default; the 89/40/49 census; the L-12 widening at `:1371`, `:1726`, `:1603`; `contract_size = 1.0` and the `max_position_contracts` dominance above $3,125.

`UNVERIFIED`, recorded rather than asserted: **whether `currentBalance` includes position value.** `balance_total` is the venue's `currentBalance` on an `AccountType.CASH` account; `assetNotional` is a separate field nothing in Breezy reads. So `equity == 0.0` is at least as plausibly "fully deployed and solvent" as "drained", and R1's "measurement of ruin" is withdrawn. Refusing a new BUY at zero cash is right under either reading, which is why D2 survives the uncertainty. Also UNVERIFIED: venue rate limits on `/v1/account/balances`; whether R-7's submit path will consult the refusal latch (§0's "bounded" claim is true today only because R-4 refuses unconditionally); which of the 49 sites reach the gate.

## 5. Least-confident decision, and one state worth naming

**D2's fail-closed choice**, now narrowed by the gating to: *refusing new BUYs when equity is unobserved or non-positive.* Evidence that it will not block trading is structural — backtest always observes, and on live an unobserved equity co-occurs with a latched refusal — not measured, and unmeasurable until a strategy runs live. **Falsifier:** the first live-small session logs every `equity_unobserved` refusal with its tick timestamp (RED-9). Clustering anywhere but a start-up window falsifies D2, and the answer becomes D4's bounded refresh promoted ahead of a refusal.

**Pushback on the state the gating creates, since you asked.** Buy-refused / sell-allowed is **reduce-only mode**, and it is the correct terminal behaviour, not a hole: with `allow_short=False` every permitted sell is reducing, so the state is monotonically de-risking and cannot open exposure. The genuine defect in it is **observability, not direction** — reduce-only entered silently is indistinguishable from a bot that saw no opportunity, which is T-4's own diagnosis recurring one level up. RED-9's per-refusal timestamped log is the minimum fix and is sufficient; a persistent mode flag is a speculative second state machine and is **rejected**. Name the state in the log line so an operator reading the journal sees "reduce-only", not a silence.

Second: **deleting `starting_equity`** (D1). Verified dead, but a public config field — a future `ImportableStrategyConfig` YAML naming it would fail construction rather than be ignored. A loud failure beats a silent fabricated denominator; a judgement, not a proof.

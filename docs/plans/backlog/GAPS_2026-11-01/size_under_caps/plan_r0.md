# SIZE-UNDER-CAPS + stage 2 COMPOUND-WITHIN-CAPS
Status: r0, DRAFT; reviewers: architect + prediction-market-reviewer, both pending. Read-only planning; no implementation or tests executed.

## 1 Objective + ROI mechanism

GOAL STATE: a deterministic sizing proposal respects executable depth, realised available capital and every exposure limit; only an operator-authorised, preregistered family may consume it.

ROI mechanism: after a family proves positive net edge, increasing eligible filled quantity can increase expected net dollars approximately as filled quantity × net edge. Stage 1 supplies bounded quantity proposals; stage 2 lets those proposals follow reconciled realised bankroll, increasing after realised gains and decreasing after losses or withdrawals until depth or existing caps bind. Sizing creates no edge, guarantees no fills or profit, and cannot justify scaling a failed family. Report incremental capital committed and realised net portfolio ROI against the frozen baseline; larger dollar P&L alone is insufficient evidence of better ROI.

## 2 Preconditions/dependencies

- Stage 1 fixture development can proceed independently; consumption requires GAP-4 REGISTERED-FAMILY evidence and its operator-approved successor PREREG.
- Forecast eligibility inherits GAP-1 → GAP-2 → GAP-3 → GAP-4; execution eligibility inherits GAP-5. Kalshi consumption additionally requires GAP-6 GO and KALSHI-ADAPTER.
- Stage 2 depends on ROI-LEDGER: opening allocation, reconciled realised net P&L, explicit capital flows, locked capital and working-order reservations.
- Resolve the architecture conflict before implementation: §6.1 bans Kelly, but §6.2.1 derives a boundary allocation using Kelly (`docs/plans/TRADING_SYSTEM_ARCHITECTURE.md:974-1063`). This item adopts §6.2.2’s clipping sequence without Kelly arithmetic anywhere.
- Freeze an operator-approved allocation policy, fee envelope, epsilon, quantity units and report contract before running evidence. No policy fraction, cap value or concrete quantity is proposed here.
- GAP-6’s illustrative size table supplies no sizing evidence; its removal and transfer here are explicit (`docs/plans/backlog/GAPS_2026-11-01/gap6_sample_and_size/plan_r3_delta.md:10-21`).

## 3 Scope

Proposed files; new paths below are implementation targets:
- NEW `src/breezy/strategy/weather_common/sizing.py`: immutable input types and pure `size`.
- NEW `src/breezy/persistence/sizing_proposal.py`: strict proposal report serializer/reader; I/O stays outside `size`.
- Extend `src/breezy/adapters/polymarket_us/operator_controls.py` with a read-only headroom snapshot; retain existing authorisation and reservation semantics.
- Extend `scripts/analysis/portfolio_roi_report.py` with optional `--sizing-inputs PATH` for offline proposals using the same serializer.
- Stage 2 opt-in plumbing: `src/breezy/persistence/family_manifest.py`, `src/breezy/app/trade.py`, and `src/breezy/strategy/forecast_quantile_ladder/{config,composition,decision,strategy}.py`.
- NEW `tests/unit/test_cap_depth_sizing.py`, `test_sizing_proposal.py`, `test_sizing_opt_in.py`; extend existing portfolio-report and family-manifest tests.
- No new service, timer, backtest harness, venue adapter, cap control, live ruling or enablement change.
- Preserve the existing maker family: qty 1 is fixed at `src/breezy/strategy/no_ladder_maker/strategy.py:159-160`, submitted at `:678-685`, and also subtracted from its own displayed rests at `:513-531`. Changing its order quantity alone would leave inconsistent depth accounting.
- Native verdict: NATIVE EXISTS, DECLINED for this policy. `FixedRiskSizer` computes stop-distance risk sizing; that arithmetic differs from settlement-loss cap-and-depth sizing (`.venv/lib/python3.13/site-packages/nautilus_trader/risk/sizing.pyx:181-200`). Keep native order construction.

## 4 Steps (inputs, outputs, who, time)

1. S0 — implementer, 0.5 day: architect + domain reviewer resolve §6.2.1 conflict and freeze the following contract; output reviewed policy/PREREG, without changing any active trial.
2. S1 — implementer, 1 day: RED-first pure function and properties; output reviewed code plus attributable test evidence.
3. S2 — implementer, 0.5 day: report writer/reader and offline fixture integration; output reproducible proposal reports, with no execution consumer enabled.
4. S3 — ROI-LEDGER owner, dependency-gated: provide the durable bankroll snapshot and reconcile its identities; output a versioned, timestamped, provenance-pinned input.
5. S4 — implementer, 1 day after S3: wire only a newly preregistered eligible family; output shadow consumption evidence through the existing harness.
6. S5 — reviewers/operator, after gates: review the concrete report and consumption evidence. Operator alone decides family authorisation and any later arming; this item ends ready for that decision.

Stage 1 — SIZE-UNDER-CAPS:
- Signature: `size(edge_lb, price, depth_at_price, bankroll_from_ledger, caps) -> Decimal proposed_qty`.
- Freeze units: `edge_lb = p_lb - price - fee_hi_unit`, net USD/contract for the purchased leg; `p_lb` is settlement-adjusted. Reject reconstructed `p_lb >= 1`, invalid probabilities, floats and non-finite inputs.
- `price` is the executable bought-leg price for the supplied depth, bounded by the order limit. This version uses one price level; never extrapolate deeper liquidity.
- `caps` is an immutable resolved snapshot: remaining position/daily USD, cluster/city-day/day contract headrooms, remaining portfolio allocation, available cash, fee envelope, epsilon, size increment and minimum quantity.
- Only two operator dollar controls exist in the inventory (`src/breezy/adapters/polymarket_us/operator_controls.py:143-158`). Other headrooms are derived exposure-policy limits, without new operator environment controls.
- Resolve remaining position premium after held and working exposure; resolve daily headroom after spend/reservations and uncharged exposure, counting each commitment once.
- Existing premium cost rounds UP to cents (`src/breezy/adapters/polymarket_us/operator_controls.py:281-295`); daily admission also includes uncharged open exposure and refuses unknown notionals (`:727-746`).
- Use an immutable market-specific fee envelope covering rounding and permitted partial-fill patterns. No unverified rebate credit; missing fee evidence refuses.
- Preserve fee ownership: authoritative instrument fees read the market coefficient and round the total (`src/breezy/adapters/polymarket_us/fees.py:314-353`). The estimate helper documents a fixed documented taker coefficient (`:419-432`); do not substitute it for market-specific evidence.
- Let `B` be supplied bankroll, `a` the frozen non-Kelly allocation fraction, and `H_bank = max(0, min(a*B - already_allocated_risk, available_cash))`.
- Define `M(H,c) = floor_to_increment(floor_to_cent(max(0,H)) / c)`.
- Gate first: `edge_lb <= epsilon` returns zero, with `epsilon >= 0`. Thus `p_lb <= price + fee_hi_unit` always returns zero, including equality.
- Compute `raw = min(depth_at_price, M(position_remaining,price), M(daily_remaining,price), M(H_bank,price+fee_hi_unit), cluster_remaining, city_day_remaining, day_remaining, portfolio_remaining_contracts)`.
- Floor `raw` to the instrument increment; below minimum returns zero. Never round up or borrow unused capacity from another limit.
- Recheck fee-inclusive affordability and the edge gate at the resulting price/quantity; failure returns zero. No search for a marginally passing price.
- Above the gate, edge magnitude does not scale quantity. No Kelly formula, fractional Kelly, optimisation or policy tuning from outcomes.

Stage 2 — COMPOUND-WITHIN-CAPS:
- ROI-LEDGER supplies `B = opening_allocated_bankroll + authorised_net_capital_flows + cumulative_reconciled_realised_net_PnL`, plus separately reconciled available cash and commitments.
- Include realised losses and fees; credit gains only when proceeds are reconciled and available. Exclude mark-to-market gains, forecast payouts and foreign/manual-account profits.
- Durable records are cumulative per order, so repeated partial-fill snapshots must not be summed (`src/breezy/adapters/polymarket_us/exec/client.py:1051-1084`).
- The current report emits schema-v5 accounting rows (`scripts/analysis/portfolio_roi_report.py:2125-2129`, `:2870-2875`). Those rows can be `SETTLED_NWS_IMPLIED` with unavailable venue checks; that status can pass accounting checks (`src/breezy/analysis/labeling/accounting.py:244-265`, `:671-698`, `:722-742`). Their totals alone do not authorise compounding.
- At the existing family evaluation event, collect one coherent snapshot, call `size`, atomically write and validate the proposal report, then permit the opted family to consume it.
- Report: schema/policy/code hashes, family + PREREG hash, decision/market/side, as-of/expiry, source watermarks, bankroll basis, inputs, proposed quantity, binding constraint and refusal reason. Private money reports stay outside git; committed evidence contains no credentials or order IDs.
- The family PREREG must name the sizing rule, version/hash, report contract, bankroll basis and consumption policy. Add explicit optional manifest references; unknown keys currently refuse (`src/breezy/persistence/family_manifest.py:162-164`, `:320-326`).
- Consumer checks identity, provenance, freshness and current depth/headroom; any changed input requires a new report. Missing/invalid proposals refuse for opted families.
- Apply sizing before the take latch: forecast decisions currently latch before returning fixed quantity (`src/breezy/strategy/forecast_quantile_ladder/decision.py:333-364`); order construction consumes `take.qty` (`src/breezy/strategy/forecast_quantile_ladder/strategy.py:680-688`).
- Retain final in-lock authorisation against both operator controls (`src/breezy/adapters/polymarket_us/operator_controls.py:504-571`), reached by BUY submission (`src/breezy/adapters/polymarket_us/exec/client.py:7864-7877`). A report grants no reservation or permission.
- Realised gains never replenish same-day gross-entry budget; exit proceeds already do not replenish that headroom (`src/breezy/adapters/polymarket_us/exec/client.py:7852-7857`).

## 5 Acceptance / PASS-KILL frozen

- PASS-1: valid inputs produce deterministic, finite, non-negative increment-aligned quantity bounded by depth and every individual remaining limit.
- PASS-2: inclusive break-even/epsilon refusal, minimum-quantity refusal and final fee-inclusive bankroll checks hold.
- PASS-3: fixed other inputs give non-decreasing size with depth or bankroll; tightening any headroom cannot increase size. Additional edge above the gate leaves size unchanged.
- PASS-4: realised profit/loss fixtures increase/decrease affordable proposals before limits bind; profits cannot increase caps or restore daily spending capacity.
- PASS-5: only explicitly preregistered families consume reports; report creation cannot arm a family. Existing family behavior remains pinned.
- KILL/revise implementation on any invariant violation. Missing bankroll provenance, unresolved architecture ruling, fee/depth evidence or eligible family means BLOCKED consumption, never a guessed input.
- Engineering PASS establishes machinery only. Economic PASS/KILL remains the family’s frozen forward rule; quantity and partial fills do not create extra independent trials.

## 6 Tests RED-first + gate

- Hypothesis: generate finite Decimals across prices, increments, minima, edge boundaries, headrooms, bankroll and depth; independently check money rounding and all inequalities above.
- Add zero/exhausted limits, tiny positive edge, exact equality, invalid/missing values, `p_lb=1`, fee-rounding boundaries and insufficient depth.
- Integration: cumulative partial updates, restarts, duplicate reports, stale watermarks, withdrawals, locked capital, concurrent proposals, tightened caps and UTC rollover.
- Assert no I/O/environment/clock access or mutation inside `size`; proposals cannot bypass authorisation, set controls or alter enablement.
- Prove barrier tests fail under deliberate clamp removal, inclusive-gate reversal and PREREG-check removal; restore and rerun GREEN.
- Run focused tests through the existing wrapper, then `scripts/ci/run_tests_no_egress.sh --basetemp /home/jon/breezy/.pytest-tmp/size-under-caps` and `.venv/bin/lint-imports`; read EXIT before any requested push.
- Use isolated HOME/data roots and fixtures. No live order or network probe is required.

## 7 Pins/isolation/risks

Nautilus immutable; `allow_short=False`; safety/settlement/contract/pin/NO-SEND tests never weakened; live enablement and egress firewall untouched. Existing harness only under the 10-21 ruling unless an exact operator exception is recorded. Freeze PREREG before runs, ONE look under L-34; retain holdout clauses 1–4. L-12 widen-never-relax, separately reviewed pin changes; L-75 writer-produced evidence with notes only in sidecars; basetemp inside the tree; never call `iem_cli_fetch.fetch`. Depth disappearance and concurrent spending can still deny a valid proposal; deny rather than enlarge size or limits.

## 8 Operator decisions

Approve the non-Kelly allocation policy and bankroll attribution; authorise a new family PREREG naming report consumption. Select any concrete quantity authority personally. Caps remain operator-owned: the bot never sets, raises or proposes either cap. Arming remains a separate operator act.

## 9 Citations not verified

- ROI-LEDGER’s future spendable-bankroll fields, settlement/cash-credit reconciliation and atomic snapshot contract are dependencies, not verified existing capabilities.
- No currently approved family PREREG was verified to authorise this sizing rule; allocation policy, fee envelope and consumption freshness limits remain unapproved.
- Executable depth and fee envelopes for scaled quantities require instrument-specific evidence; displayed passive queue depth is insufficient.
- Codegraph and Sequential Thinking MCP tools were unavailable; citations above came from direct source reads. Independent reviews and executable acceptance evidence remain pending.

Codex session ID: 01a19961-2a1f-7420-aed6-6e23f851c9f2
Resume in Codex: codex resume 01a19961-2a1f-7420-aed6-6e23f851c9f2

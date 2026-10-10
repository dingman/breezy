# EXEC-PAR WP0 recorded verifications (2026-10-10)

Tree: ff of `feat/data-capture-and-risk` (b86ebf37) plus WP1 `breezy.domain.exec_slots.admit` (12d7ae78).
Line numbers are in this tree and may differ from the plan's earlier citations.
Data rule: every simulation input is dated before 2026-10-07 and the tool refuses anything else.

## 1. Cash account `free` update timing and AMBIGUOUS lock behaviour

- The exec client registers a CASH account (`exec/client.py:1805-1808`, `AccountType.CASH`, `OmsType.NETTING`).
- Nautilus recomputes balances only on `OrderAccepted | OrderCanceled | OrderExpired | OrderRejected | OrderUpdated | OrderFilled`
  (`nautilus_trader/portfolio/portfolio.pyx:87-94, 505-506`).
- `free` falls on `OrderFilled` through `update_balances` (`portfolio.pyx:527-536`).
- A lock is taken only for open passive orders (`portfolio.pyx:562-577`).
- "Open" means ACCEPTED, TRIGGERED, PENDING_CANCEL, PENDING_UPDATE or PARTIALLY_FILLED (`model/orders/base.pyx:421-429`).
  A SUBMITTED order is not open.
- Breezy never emits `OrderAccepted` (no `generate_order_accepted` in `exec/client.py`).
  It emits only submitted (`client.py:5926-5928`), filled (`:3473`, `:6481`), canceled (`:3256`, `:6560`) and rejected (`:4097`, `:6572`).
- **Conclusion:** an AMBIGUOUS order holds NO buying power in-process.
  `free` drops only when the fill is booked, which is the resolver accept-fill time.
  Arm A (reduce at accepted-fill time) is therefore the production-faithful arm.
  Arm B (an AMBIGUOUS order also holds buying power for its stuck lifetime) is a conservative stress.
  The stop rule uses the worse arm, as the plan specifies.
- The RiskEngine denial is per order against `balance_free` (`risk/engine.pyx:696, 949-952`).

## 2. `subscribe_trades` is off on the trade node

- The field defaults to `False` (`adapters/polymarket_us/config.py:334`).
- Its only `True` is the quote-tape node builder (`runtime/node_config.py:609`, inside `build_quote_tape_node_config`).
- The trade node passes its `data_client_config` through unchanged (`node_config.py:1032`).
- A repo-wide search for `subscribe_trades` finds no other setter.
- `runtime/backtest_harness.py:744` records "the trade node publishes no TradeTick".

## 3. `fill_time_count.py` reads no singleton

- `src/breezy/analysis/fill_time_count.py` opens the exec-state store read-only (`:84-95`) and runs `SELECT key, value FROM state` (`:123`).
- It keeps only keys with `FILL_KEY_PREFIX` (`:131`).
- It has no reference to `CURRENT_INTENT_KEY`, `SubmitIntent`, `current_open` or `is_latched`.
- `scripts/analysis/fill_time_count.py` is a re-export shim.

## 4. `base_slug_of(order.instrument_id)` equals the wire slug

- The wire `marketSlug` is `instrument.raw_symbol` (`exec/submit_chain.py:359, 370`).
- `raw_symbol=Symbol(slug)` for the YES leg (`adapters/polymarket_us/parsing.py:1435`) and the NO leg (`:1514`).
- Checked on all 389 pre-window candidate instruments (main4 plus NYC), each with its NO sibling from `no_leg_instrument_id`.
  For each, `base_slug_of(yes) == base_slug_of(no) == directory slug == sim.slug_of(...)`.
  `leg_of` returned yes/no correctly.
  Result: 389 checked, 0 mismatches.
  Example NO id: `tc-temp-miahigh-2026-10-06-gte93f^no.POLYMARKET_US`.

## 5. `L_feed` (positions-feed lag)

- **Result: 300 s default.** No pre-window measurement exists.
- `src/breezy/domain/position_reporting_lag.py` documents the lag as UNVERIFIED until a live fill is confirmed.
- A search of `~/.local/share/breezy` `*.log` for `position_reporting_lag|PositionReportingLag|position_lag` found no producer lines.
  Only filenames were listed; no log content was read.
- `positions_feed_lag_bound(None)` returns 300.0, and the results JSON carries `L_feed_s: 300.0`.

## 6. Hold constants against the exec client (AST, not imported)

| Constant | Value | Source |
|---|---|---|
| `_RESOLVER_POLL_INTERVAL_SECS` | 5.0 | `exec/client.py:588` |
| `_RESOLVER_ZERO_FILL_MIN_AGE_NS` | 120 s | `exec/client.py:1596` |
| `_RESOLVER_NO_ID_MIN_AGE_NS` | 300 s | `exec/client.py:1604` |

- Simulated holds:
  - fill: 0.3 s;
  - AMBIGUOUS fast: 5 s (the poll), w.p. 0.2;
  - AMBIGUOUS slow: 150 s (at least floor plus poll = 125 s);
  - no-id: 305 s.
- `assert_hold_constants_current()` runs on every simulation run.

## 7. Candidate re-extraction cross-check

- `exec_parallel_dhat.py --extract` re-ran the dmix rule with instrument ids.
  Bounds are 2026-08-30..2026-10-06, the first 12:00-13:00Z depth row, NO ask >= 0.90.
- Counts equal the triage run: rungs 1085, norow 96, nobid 169, 389 candidates.
- The `(ts_ns, station)` set matches `stage_minus1_triage_cands.json` on every day.
- The universe that reproduces the plan's K=1 p90 of 0.491 is **main4 (LAX, MDW, MIA, SFO)**: 0.4909.
  With NYC added it is 0.5364.

## Deviations and judgement calls (also in the return note)

1. **Free balance: F0 = 1.0 daily budget** (tightest plausible funding; the balance is not read).
   - Filled orders deplete it, so a daily-budget stop shows up as a `free_balance` drop.
   - The sensitivities (unbounded; 3 budgets) are in `variants.sensitivity`.
2. **The daily-budget stop is not otherwise modelled.**
   - Consequence: the first-5 s deployed budget fraction (telemetry only) can exceed 1.0.
   - The ledger would clip such cases.
3. **Stop metric: the day-level p90.** The CI is a 95% percentile interval of a 2,000-resample day-clustered bootstrap.
   The gate reads the upper bound of the worse free-balance arm.
4. **The gate arm is the id arm** (p_amb = 0.33, one stuck slot, throttle, bound, worse arm).
   The no-id arm is reported as a variant, not folded into the gate.
5. **Ordering of the gates is admit -> throttle -> free balance -> bound.**
   The throttle counts only orders the latch admitted.
6. **Every AMBIGUOUS order is assumed to end as a fill** (conservative for budget and free balance).
7. **`cost_budget_bucket()` does not exist in this tree (WP3).**
   - The optional flag takes a `module:callable` reader. It is OFF by default and was not used.
   - The script imports no `operator_controls` and prints only a ladder label.
   - The bucket is therefore unknown, so the table is reported only. There is no worst-bucket fallback.

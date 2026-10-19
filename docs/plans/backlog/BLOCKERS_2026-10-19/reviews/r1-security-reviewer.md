# Review: BLOCKERS plan r1 — security-reviewer
Verdict: APPROVE (B6a LEAVE signed), with 4 minimal edits; B6a's stated reasoning must be corrected, the decision stands.

## B6a — LEAVE vs change (answers open question 4): SIGNED LEAVE
Verified in code (read-only):
- Mint: `issue_live_trading_permit` needs only `BREEZY_TRADING_ENABLED == "1"`, derivable session ceilings, operator id (`safety.py:710-720`). `app/trade.py:1323` mints it unconditionally, BEFORE settings load, regardless of orders flag. So yes: with unit `:120` =1 and the drop-in setting only ORDERS=0, a LiveTradingPermit mints (assuming caps + operator id are in the unit env; UNVERIFIED, not observable: the "live-trading permit issued" log line is emitted only on the orders-requested branch, `trade.py:1384-1390`; orders-off logs "order submission permit not minted: orders not requested", `:1397`).
- OrderSubmissionPermit does NOT mint: `trade.py:1367` skips `issue` when `orders_enabled_requested` is false; `order_submission_permit=None`. It also would refuse at `order_enablement.py:193`.
- Can the live permit reach a POST without the order permit? The exec client holds ONLY the LiveTradingPermit (`exec/client.py:1893`, used at `:7052` via `assert_live_order_submission_permitted`). `_submit_order` checks `permit_is_missing(self._permit)` (the LIVE permit), not the order permit. The module docstring (`client.py:21-24`) claims an OrderSubmissionPermit is checked; the code does not. `WRITE_CANONICAL_STRING_VERIFIED` is True (`write_transport.py:52`), so that gate is open.
- The real order-permit barrier is strategy-side: `forecast_quantile_ladder/strategy.py:636` returns `phase0_permit_absent` when the permit is None; `phase1_sending_permit` hands strategies None. The kernel guard is NOT a second barrier: `backtest_order_guard.py:315-317` returns (allows) when the permit is None; it only checks expiry. So the plan's "no order permit, so the first refusal is outside_permit_window" is imprecise: the refusal that stops a send is the strategy gate; the exec client would POST anything that reaches `submit_order` while the live permit is unexpired (10 h TTL), subject to latch/veto/halt/budget gates.
- Net: a strategy-gated defence, not a structural one. Today that is sufficient: the only sending composition is gated, the exit seam is UNARMED (`exit_manifest` absent -> `_EXIT_MANIFEST_ABSENT_REASON`, `client.py:~6965`), and the supervisor self-check fails closed on ORDERS env != "0" (`trade_supervisor_core.py:404-430`).
- Cost of changing: drop-in bytes are sha-pinned (`health_dropins.py:51`, allowed set `:57`). Any edit = new sha row + directive-set code change in a module that must name no other trading gate (`:3-5`) + CRITICAL page until deployed. Not a one-liner; the gain (belt-and-braces in a state with no armed sender) does not justify it.
- Decision: LEAVE. Conditions to record in the PROGRESS line (so the latent permit is not forgotten): (1) the ONLY thing stopping a send is orders=0 + strategy `phase0_permit_absent`; (2) any new strategy/exit-seam arming, or removal of the drop-in, must treat the live permit as already minted; (3) do not rely on `backtest_order_guard` for a None permit.
- Correct the plan text: replace "There is no order permit, so the first refusal is `outside_permit_window`" with the strategy-gate statement above; drop "probably mints ... inferred" to "mints iff caps + operator id are in the unit env (UNVERIFIED)".

## B6 other
- Missing calendar item (MED): the allowlist row expires 2026-12-31 (`health_dropins.py:55`) but the ruling's review/KILL horizon is 2027-01-25. After expiry the unchanged drop-in no longer matches and pages CRITICAL `allowlist_mismatch` daily. Add a calendar row "extend or retire the drop-in row before 2026-12-31" (a reviewed code row, not this plan's scope, but it must be on the calendar; same family as B4 calendar rows).
- B6b: no secrets exposure. Proposed `BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG` is a path, not a credential. Deferral correct (no trigger edit mid-block). README note should list paths only.
- B6c: no action, agreed (charset is fail-closed).

## B5 — dry call side effects
- `register_hypothesis` is pure per plan; `read_hypothesis_ledger` (`hypothesis_ledger.py:1372-1395`) is read-only (`path.open("r")`, no lock, no mkdir). The write function is `write_hypothesis_ledger` (`:1350`, mkdir + temp + os.replace) and MUST NOT be imported or reachable in the script.
- MED: the plan builds the path via `ledger_path(default_derived_root())`, which lives in `scripts/analysis/hypothesis_register.py:256,264`. Importing that script module drags a CLI module that also holds append/write code. Simpler and safer: hardcode the ledger path, `cp` the file to the agent scratchpad, read the COPY with `read_hypothesis_ledger`, record the sha256 of the original before and after. That satisfies "mtime unchanged" with evidence, and removes any write path from the process.
- Run with `-I`; set no `HOME`-derived writes (`mkdir` in `default_derived_root` callers). No network, no credentials needed.
- Outcome-blindness (L-34): bound pinned before the call from spec numbers only is the right order; require the pin file's commit to precede the call evidence note (git timestamps).

## B2 / B4 / B1 / B3 (security scope only)
- B2: NOTE and `git show 2380042f:...` expose only repo paths/shas; no secrets. APPROVE.
- B1/B3/B4: governance/docs; no enablement touched. APPROVE. B4's YES-shell must keep "activation is the manual trio" verbatim; confirm it does not name `BREEZY_ORDERS_ENABLED` as a value to set by an agent.

## Cross-cutting
- No invariant breach found: no edit to drop-in, allowlist, `BREEZY_ORDERS_ENABLED`, PREREG, or dates.
- Over-engineering: none from a security standpoint; the plan correctly refuses new tooling.

## Required edits
1. Replace B6a's "first refusal is outside_permit_window / no order permit" reasoning with the strategy-gate (`strategy.py:636`) statement and note the kernel guard allows a None permit (`backtest_order_guard.py:315`).
2. Add the three latent-permit conditions to the PROGRESS decision line for B6a, naming v2 resume / F9 / any exit-seam arming.
3. Add a calendar row for the drop-in allowlist expiry 2026-12-31 (`health_dropins.py:55`) vs the 2027-01-25 horizon.
4. In B5, read a scratchpad COPY of the ledger via `read_hypothesis_ledger` with a hardcoded path and before/after sha256; do not import `hypothesis_register.py`.

## UNVERIFIED
- Whether the supervisor unit env carries the operator caps and operator id (decides if the live permit actually mints today).
- Actual runtime behaviour of the exit seam in a node booted orders-off with a live permit (read statically only; no tests run).
- Whether the allowlist expiry semantic is a hard mismatch alert on day after 2026-12-31 (read from the module docstring and row, not exercised).
- Docstring-vs-code gap at `exec/client.py:21-24` (order permit "checked") is observed statically; no test run.

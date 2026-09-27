# RULING — AUD-12a: slippage allowance (2026-09-27)

**Decision: RETAIN the 0.01 slippage placeholder as a ruled, deliberately conservative allowance.** It applies in every MDE, CONFIRMED and positive-EV computation for **qty-1 IOC PM.us weather-rung entry fills** (`current_rung_hold` families). This closes AUD-12a.
The coordinator decides this under standing pre-authorization after a two-peer loop. It touches no operator cap.

## Peer loop
| Peer | Verdict |
|---|---|
| Codex (read-only) | ENDORSE-WITH-CONDITIONS |
| prediction-market-reviewer | ENDORSE-WITH-CONDITIONS |

## Basis (verified by both peers)
1. **Replay cannot measure slippage.** `src/breezy/runtime/paper_replay.py:157-169`: `ImpossibleFillPriceError` is raised at `:405-407` when `fill_px < entry_ask`. Replay BUY IOC fills at the displayed ask by construction.
2. **Live qty-1 slippage is 0 on every fill.** `docs/evidence/MEASURED_SLIPPAGE_2026-09-24.md:11-30`: all 8 fills have `fill_px == decision_ask`.
3. **Positive slippage is structurally near-impossible for this order shape.**
   - `order_quantity` is pinned to 1 (`strategy/current_rung_hold/config.py:263`).
   - `_is_executable` (`decision.py:386-395`) REFUSES, rather than walks the book, when displayed size is below `minimum_displayed_size`.
   - The order is a marketable limit at the decision ask.
4. **The circularity.** Only live fills measure slippage, live fills require a re-arm, and a re-arm requires AUD-12. So a "retain as conservative" ruling is the only non-circular closure.
5. **AUD-12's own acceptance already allows it.** `docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md` §8 and :226-233 / :382-403 keep the placeholder byte-unchanged unless the measurement doc argues it is unsafe-low. It does not.
   - Hygiene note: §8 names `MEASURED_SLIPPAGE_2026-09-21.md` with 6 fills. The artifact is actually `…_2026-09-24.md` with n=8.

## Where 0.01 lives (corrected citations)
- `scripts/analysis/hypothesis_register.py:144` `NO_SIDE_SLIPPAGE_ALLOWANCE`, and `:177` `ARCHIVE_RECAL_SLIPPAGE_ALLOWANCE`. These are consumed at `:289` and `:328`.
- Independent 0.01 defaults that are NOT governed by this ruling:
  - `strategy/ladder_ev/config.py:153`
  - `strategy/cli_settlement_print_lock/strategy.py:181` (`ABSOLUTE_SLIPPAGE_FLOOR_PROB`)
- `promotion_criteria.py:427` and `hypothesis_triage.py:548-551` carry NO 0.01. They are the C-VALIDITY gate (below).

## Scope limits (binding)
- **This is NOT evidence for other sizes.** The book-walk statistics in `costs.py:284-290` and `ladder.py:50-55` (36% exceed the floor, p90 0.137, p99 0.661) were measured for a $24.53-notional multi-contract order under `ladder_ev` / `cli_settlement_print_lock`. They do not support, and must never be cited for, the qty-1 claim. The qty-1 claim rests on the n=8 fills alone.
- **Fee rounding is a separate risk** (`fees.py:215-229`). It is not hidden inside this slippage allowance.
- **This does NOT land AUD-12.**
  - `REPLAY_VALIDITY = "MECHANISM_ONLY"` (`src/breezy/analysis/replay_results.py:56`) stays untouched.
  - AUD-12 as a whole lands only when AUD-12b (EDGE-1, the fee-probe fix) is live AND the RA-3 validity condition (`AUD11_AND_AUD12_LANDED`, `replay_daily_runner.py`) is flipped by its own ruling.

## Re-estimate triggers (any one reopens AUD-12a)
- Any live fill with `fill_px − decision_ask > 0.01`.
- A measured mean ≥ 0.01, or a pre-specified one-sided upper bound above 0.01.
- Any change to order size, limit construction, or `minimum_displayed_size`.

## Tracked follow-up (separate from AUD-12a)
**THIN-BOOK-REFUSAL.** The winning rung's median level-0 size is 0.58 contracts (`ladder.py:53-55`), below the qty-1 requirement more than half the time. That is a fill-rate / opportunity-cost risk. It is not slippage, and this allowance must not be framed as absorbing it.

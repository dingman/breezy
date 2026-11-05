# TRADE-ROW-DRIFT plan: an unreadable TRADE row makes the activities read INCOMPLETE

**Headline:** the hazard is real. Today, any TRADE row whose `trade`, `aggressor`, `passive` or `id` drifted counts as "not ours". An end-of-feed read with zero matches then lets the resolver retire an AMBIGUOUS order as a false ZERO_FILL. The fix below adds no new callee, keeps the existing `(): ` pin at equal or greater strength, and three test fixtures need a realistic second leg.

## Findings
- F1. Today these row shapes silently count as "not a trade for this order" (`account_activity.py:400-414`):
  - (a) a list element that is not an object (401-402);
  - (b) `type` missing, not a string, or renamed, e.g. `"TRADE"` (403);
  - (c) `trade` missing, not an object, or renamed, which becomes `{}` (405-406);
  - (d) `aggressor` or `passive` missing, not an object, or renamed, which becomes `{}` (407-410). Our order can be the passive leg (resting bids), so one renamed leg is enough to lose it;
  - (e) a leg `id` missing, renamed, `""`, or not a string (411-412);
  - (f) the id keeps its name but changes meaning. This cannot be detected from structure.
  - A page whose `activities` is not a list returns `()` (397-398), but the caller already stops on that (`client.py:3235-3241`).
- F2. Why this is the dangerous direction:
  - If the page reached `eof`, the join comes back `complete=True, trade_count=0` (`client.py:3276-3278`).
  - `trade_found` is then False (2761).
  - The completeness gate at 2793 passes, and the order is retired at 2849 (`_resolve_terminal_zero`) = false ZERO_FILL.
  - The same-day holdings check (2823-2841) is the only remaining backstop, and it is skipped for past-day instruments (2818).
- F3. Real row shape: every captured TRADE row carries both `trade.aggressor.id` and `trade.passive.id`. This holds for all 5 rows in `AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json` (e.g. :592/:642) and in `..._MIA/PRIVATE_activities_types_trade.json:249,329`. The rows also carry a matching copy of each id at `aggressorExecution.order.id` / `passiveExecution.order.id` (MIA :27 equals :250, :133 equals :330).
- F4. The SDK snapshot `Trade` type (`sdk_snapshot/.../types/portfolio.py:53-65`) has no `aggressor`/`passive` at all, so it cannot be trusted for this. Its `ActivityType` list (8-16) names 1 trade type and 6 non-trade types.
- F5. Firewall: `trade_rows_for_order`, `trade_refs.extend` and `self._log.warning` are already allowed (`test_execution_egress_firewall_guard.py:2240-2241, 2113-2114`). Reading an attribute is not a call. A separate pin requires exactly two `[k for k in page]` comprehensions (`test_current_rung_hold_ambiguous_resolver.py:4742`), so the new warning must not add a third.
- F6. `trade_rows_for_order` has only one caller (`client.py:3242`).

## Options
- **A (pick).** `trade_rows_for_order` returns a frozen `TradeRowScan(refs: tuple[TradeActivityRef, ...], uninterpretable_rows: int)`. The caller extends with `scan.refs`, then stops the read if `scan.uninterpretable_rows` is non-zero. One classifier, no new callee, no allowlist change.
- B. A second pure function `uninterpretable_trade_rows(page, id)`. Rejected: it needs a new allowlist entry and two classifiers that can drift apart.
- C. Raise inside the pure function. Rejected: it would throw away trades already found on earlier pages, which breaks T7 (4644-4709).

## Classification rules (Question 2)
- **TRADE row, `type == "ACTIVITY_TYPE_TRADE"`:**
  - If either well-formed leg's id equals ours → count it as a trade, even if the other leg is malformed. Qty and timestamp keep degrading as they do today (309-323).
  - Otherwise the row is uninterpretable if `trade` is not an object, or either leg is not an object with a non-empty string `id`. Both legs are required because F3 shows both are always present.
- **Known non-trade type (the 6 in F4, as a constant in `account_activity.py`):** ignore.
- **(c) Type missing or not a string:** uninterpretable. This is structural damage, not a routine addition.
- **(c) Unknown type string:** uninterpretable only if the row has a `trade` key; otherwise ignore. A brand-new activity type is routine drift (L-37, `LESSONS.md:1338-1344`) and must not stall every read.
- **List element that is not an object:** uninterpretable.
- **Page whose `activities` is not a list:** `TradeRowScan((), 1)`.

## File-by-file
1. `src/breezy/adapters/polymarket_us/account_activity.py`:
   - add `TradeRowScan`, the known-non-trade-type constant and a `_leg_id` helper;
   - rewrite 396-422 to the rules above;
   - update the docstrings (384-395) and `__all__` (~58).
2. `src/breezy/adapters/polymarket_us/exec/client.py:3242`:
   - `scan = trade_rows_for_order(...)`, then `trade_refs.extend(scan.refs)`. Extend first, so a matched trade on the same page still raises the contradiction CRITICAL.
   - If `scan.uninterpretable_rows` is non-zero: log a warning with the count (no `[k for k in page]`), then `break`. `reached_eof` stays False.
   - Update the docstring at 3198-3206.
3. Firewall and the cage constants pin: no change. Confirm by running the guard.

## Tests (RED against today's code)
Each item is marked as either new behaviour or a fixture change.

**Pure function, `tests/unit/test_account_activity_parse.py`:**
- T1 (new). Five pages, each with one foreign row. The drifts are:
  - `passive` renamed to `passiveOrder`;
  - `trade` renamed;
  - leg id is an int;
  - leg id is `""`;
  - element is the string `"x"`.
  - Each must give `uninterpretable_rows == 1` with empty refs.
  - RED: today all five return `()`, i.e. silently not ours.
- T2 (new). Type missing → 1. Unknown type with a `trade` key → 1. Unknown type without one → 0.
  - RED: the first two are ignored today.
- T3 (new). A matching aggressor plus a malformed passive → refs length 1, uninterpretable 0.
  - Guards against flagging too much.
- **Pin at 326-328 (evolved, not weakened).**
  - Both calls now assert `== aa.TradeRowScan(refs=(), uninterpretable_rows=1)`.
  - This is strictly stronger: refs must still be empty, and the page is now also flagged.
- Other existing tests:
  - 276-281, 320-323: now use `.refs`, and additionally assert `uninterpretable_rows == 0`.
  - 306: asserts `TradeRowScan((), 0)`, so known types never poison the read.
  - 296: gets a foreign passive id so the row is realistic; asserts `((), 0)`.

**Resolver, `tests/unit/test_current_rung_hold_ambiguous_resolver.py`:**
- T4 (new, key test). GET reports terminal zero, positions empty, one `eof=True` page with a foreign aggressor and the passive leg renamed. Reuse the retire harness from ~4767.
  - Must: intent stays OPEN and no retirement.
  - RED: today it retires as a false ZERO_FILL.
- T5 (new). The same page with a well-formed foreign row still retires.
  - Liveness positive control.
- T6 (new). Page 1 has a matching trade plus a drifted row → `complete=False, trade_count=1`, and the contradiction CRITICAL fires.
- Fixtures 4414 and 4572 (changes):
  - Add `"passive": {"id": "SOME-OTHER-PASSIVE"}`, the real shape (F3). Their assertions are unchanged.
  - Without this, under the new rule both would stop on page 1: 4442 (`% 20`) and 4597 (`len == 2`) would fail.
  - This is a fixture realism fix, not a weakening; the commit must say so.

## Mutants (each killed by)
| Mutant | Killed by |
|---|---|
| M1: caller `break` removed | T4 |
| M2: `break` placed before `extend` | T6 |
| M3: flag only when BOTH legs are bad | T1 (renamed passive) |
| M4: matched row also flagged | T3 |
| M5: known types flagged | test 306 |
| M6: unknown type without `trade` flagged | T2 |
| M7: unknown type with `trade` ignored | T2 |
| M8: missing type ignored | T2 |
| M9: non-object element skipped | T1 |
| M10: `""` id accepted | T1 |
| M11: int id accepted | T1 |
| M12: `eof` read before the flag check | T4 |
| M13: non-list page reports 0 | evolved pin 326-328 |

## Risk register
- R1 (fails SAFE, liveness). The venue legitimately drops the counterparty leg → every read is incomplete → the OPEN intent blocks all orders.
  - Mitigation: the warning carries the count; F3 shows both legs on every captured row.
- R2 (fails DANGEROUS, residual). `type` AND the `trade` key renamed together → classed as an unknown type and ignored.
  - Mitigation: needs two drifts at once; the same-day holdings check at 2823 still applies.
- R3 (fails DANGEROUS, residual). The id keeps its name but changes meaning, e.g. `aggressor.id` becomes an execution id.
  - Suggested follow-up: treat `aggressor.id != aggressorExecution.order.id` (when both are present) as uninterpretable. This works because the two agree in F3.
- R4 (neutral). The fixture edits at 4414/4572 could be misread as weakening. Mitigation: T5 plus an explicit rationale in the commit.
- R5 (fails SAFE). The venue moves to the SDK shape (F4) → every trade row is uninterpretable → stays AMBIGUOUS.
- R6 (fails SAFE). In the fill branch, an incomplete join cannot confirm a fill (2854-2856) → stays AMBIGUOUS unless `long_state` is True.

## Confidence
- Findings: 0.9.
- Plan: 0.85. The main open question is the R1 liveness cost of requiring both legs.
- Invariants: unresolved orders stay AMBIGUOUS; Nautilus, `allow_short` and operator caps are untouched; no safety or firewall test is weakened.
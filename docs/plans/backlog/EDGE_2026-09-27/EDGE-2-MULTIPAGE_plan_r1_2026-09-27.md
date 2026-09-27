# EDGE-2-MULTIPAGE: plan r1

## Findings
- **Q2, does it paginate? Yes.** `_order_trade_activity` (`client.py:3167-3237`) sends `limit=100` and `sortOrder=DESC`, passes `nextCursor` through unchanged (`:3194-3195`, `:3219-3222`) and stops after 20 pages (`:1485-1487`). A read is `complete` only when `eof` is reached (`:3216-3218`; the docstring at `:1517-1530` says the same). The `min(createTime)<createdNs` shortcut does not exist in the code: the value is computed for logging only (`account_activity.py:455-484`), and the test at `test_current_rung_hold_ambiguous_resolver.py:4369` pins that it is not used. Existing tests: cursor passed through (`:4017`), missing cursor means incomplete (`:4062`), hitting the page cap means incomplete (`:4095`).
- **Q1, dangerous direction (false ZERO_FILL).** To retire a zero-fill today, three things must all hold: the order GET says terminal with `cum=0` (L-36, `LESSONS.md:1333`), the activities read is complete with 0 trades (`client.py:2779`), and the order is at least 120 s old (`:1496`, `:2787`). Same-day orders also need the holdings baseline check (e) (`:2809-2827`). Two defects can make the activities read look complete when it is not:
  - **D1:** `bool(page.get("eof"))` (`:3216`). Any truthy value that is not the boolean `true`, such as the string `"false"` or `1`, marks the read complete. The positions read (`:4101`) and open-orders read (`reports.py:1810`) already require `is True`, so this check is out of step with its siblings.
  - **D2:** a page whose `activities` field is missing or not a list returns `()` without any warning (`account_activity.py:396-398`). The loop then carries on to a later `eof` and reports a complete read with 0 trades. The rows on that page are lost.
  - **D3 (unobserved, part of the schema question):** if the cursor is offset-based, rows that drop out or get reordered between two page reads could be skipped. Duplicated rows are harmless: they only raise `trade_count`, which blocks the zero-fill (`:2747`, `:2753`), and `join.qty` has no consumer.
- **Q1, safe direction (stuck AMBIGUOUS).** An account with more than 20×100 = 2000 activities will never reach `eof` within the cap, so every zero-fill stays AMBIGUOUS. The `open_intent_stale` CRITICAL alert makes this visible (`:2513-2536`). Today's history is 35 rows over 08-05 to 09-27 (README `:92-94`), so this is decades away at the current rate. It is closer if the venue quietly returns fewer than 100 rows per page; its real page size is only known to be at least 35.
- **Q3, schema evidence.**
  - The SDK snapshot declares `cursor`, `limit` and `sortOrder` as request parameters and `nextCursor: str`, `eof: bool` in the response (`sdk_snapshot/.../types/portfolio.py:104-119`).
  - Every captured activities body is a single page with `"nextCursor": ""` and `"eof": true`: MIA `PRIVATE_activities_desc_r1_p0.json:8433-8434` (same in `_r2_p0`, `_asc_p0`, `_types_trade:6338-6339`) and SFO `activities_p0.json:2166-2167` and `activities_slug.json:140-141`.
  - **Never observed:** a non-empty `nextCursor`, `eof:false`, whether `limit` is honoured, the server's maximum page size, what a cursor encodes, or whether ordering holds across a page boundary. The README says the same (`:48-60`, `:221-228`).
  - **What would settle it:** a GET-only probe with `limit=10` over the existing 35-row history, which forces at least 4 pages. Run it descending twice at least 5 minutes apart, then ascending. The joined id sequence must equal the single-page capture `PRIVATE_activities_desc_r1_p0.json`, plus any newer rows at the head. If `limit=10` still returns all 35 rows with `eof=true`, the venue ignores `limit` and the question stays open.

## Options
- **A (picked):** fix D1 and D2 in the code and keep completeness EOF-only. This makes a false ZERO_FILL harder regardless of what the schema turns out to be. It needs no venue evidence and can merge on its own.
- **B (picked, as a separate step):** the `limit=10` probe above, to re-check ordering stability across a real page boundary. It produces evidence only and changes no code.
- **C (rejected):** enable the `min(createTime)<createdNs` branch. It fixes only the stuck-AMBIGUOUS direction, which is safe and decades away, and it adds a new way to get a false ZERO_FILL if D3 is real. It should come back only if the cap is actually hit (a `complete=False trade_count=0` log line together with `open_intent_stale`), and only after B returns STABLE.

## File-by-file (Step 1 = A)
- `src/breezy/adapters/polymarket_us/exec/client.py:3210-3218`:
  - (i) Before `extend`: if `page.get("activities")` is not a list, log a warning and `return None`. L-37 wants the refusal to name the keys it saw; if the egress firewall guard rejects the call needed to list them, log `type(...).__name__` instead, which is already used at `:3201`.
  - (ii) Change `bool(page.get("eof"))` to `page.get("eof") is True`.
  - Add no new callees. `isinstance` and `.get` are already used in this body; `_order_trade_activity` is scanned by the firewall (`test_execution_egress_firewall_guard.py:1847`, `:2090`, `:2236`). Run the guard unmodified.
- Same file, `:1517-1530` and `account_activity.py:458-469`: update the docstrings to cite D1/D2 and to state that the boundary is still unlicensed until B runs.
- Do not change `account_activity.trade_rows_for_order`: it stays pure, and the decision to refuse a page belongs to the caller.
- Tests go in `tests/unit/test_current_rung_hold_ambiguous_resolver.py`. The pin at `:4369` stays byte-unchanged.

## Step 2 (= B, evidence only)
- Copy `docs/evidence/.../MIA/edge2_ambiguous_order_probe.py.txt` to `scripts/venue/`. Its page size is fixed at 100 (`probe.py.txt:129`); add a `--limit` flag. Run it once as a read-only systemd oneshot, following the README `:19-21` procedure, then remove the script from `scripts/venue/` so the read-only guards B1-B6 stay clean.
- Write a new README under `docs/evidence/venue/polymarket_us/EDGE-2-MULTIPAGE_<date>/` covering page count, the cursor values (redacted), limit honoured yes/no, and Q2s across the boundary. Add a pointer from MIA README `:58` and `:225`.
- Note: the probe's own `pages_reached_eof` has the same `bool()` flaw (`probe.py.txt:315`). Fix it in the copy used for this run.

## Tests (RED reasons)
- **T1** `eof_non_bool_truthy_is_incomplete`, parametrized over `"false"`, `"true"`, `1`, `"0"`, plus a control with `True`. RED today: `bool("false")` is true, so the read comes back complete. The `True` control is complete.
- **T2** `page_without_activities_list_is_refused`: page 1 is `{"eof":False,"nextCursor":"c1"}` with no `activities`, page 2 is `{"activities":[],"eof":True}`. RED today: `complete=True, trade_count=0`. Expected: `None`.
- **T3** `terminal_zero_with_malformed_eof_never_retires`, end to end with min age and baseline satisfied. RED today: it retires `STATUS_REPORT_ZERO_FILL_TERMINAL`. Expected: intent stays OPEN.
- **T4** (pin, GREEN) `trade_on_page_two_is_found`: 100 non-matching rows on page 1, the matching TRADE on page 2 with `eof`. Expected: `trade_count=1`. With a terminal-zero GET this must raise a contradiction and stay AMBIGUOUS.
- **T5** (pin, GREEN) `duplicate_row_across_boundary_blocks_zero_fill`.
- **T6** (pin, GREEN) `trade_found_on_incomplete_read_still_contradicts`: page 1 has the trade, then the page cap is hit.
- Gate: `scripts/ci/run_tests_no_egress.sh`, the firewall guard, and lint-imports, with PYTHONPATH set when run from a worktree.

## Mutants (the test that kills each)
- M1: `is True` changed back to `bool()`. Killed by T1 and T3.
- M2: the `activities` list guard deleted. Killed by T2.
- M3: `eof` check moved before `extend`. Killed by T4.
- M4: `cursor` no longer forwarded. Killed by existing `:4017`.
- M5: a cap hit returns `complete=True`. Killed by existing `:4095`.
- M6: `trade_found` also requires `join.complete`. Killed by T6.
- M7: the `min(createTime)` shortcut enabled. Killed by existing `:4369`.

## Risk register
| Risk | Direction | Mitigation |
|---|---|---|
| D1/D2 lead to a false ZERO_FILL | Dangerous | Step 1; T1-T3 |
| D3 cursor skips rows | Dangerous; unobserved; also needs a GET `cum=0` and the 120 s age | Step 2 probe; C stays rejected |
| Venue ignores `limit` or has a small page size | Safe (stuck AMBIGUOUS) | Stale alert; Step 2 measures it |
| History exceeds 2000 rows | Safe | Trigger to revisit C |
| A new callee trips the egress firewall | Build failure (safe) | Inline checks; guard run unmodified |
| NO-side trades match by id only, side never consulted (r2 M-6) | Observed, not dangerous | A real captured `ACTIVITY_TYPE_TRADE` row DOES carry the NO-side (SELL/BUY_SHORT) leg's `id`: `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/activities_p0.json`, `activities[4]`/`[5]`/`[7]`/`[8]`, `passive.side="ORDER_SIDE_SELL"`, `passive.intent="ORDER_INTENT_BUY_SHORT"`, `passive.id` present (scrubbed). `trade_rows_for_order` (`account_activity.py:411-413`) matches `aggressor.id`/`passive.id` only, which this fixture shows is structurally sufficient for a NO-side leg too -- side is redundant for matching, not a gap in it. |

**Invariants:** Nautilus, operator caps, live enablement, the NO-SEND firewall and `allow_short` are untouched, and no safety test is weakened. An unresolved read ends up as `None` or incomplete, which means the order stays AMBIGUOUS.

**Confidence:** HIGH that D1/D2 are real and the fix is correct (every claim above is traced to code). MEDIUM on what the Step 2 probe will show, because whether `limit` is honoured is unknown. Nothing is known about the pagination schema beyond the SDK types and the single-page captures.
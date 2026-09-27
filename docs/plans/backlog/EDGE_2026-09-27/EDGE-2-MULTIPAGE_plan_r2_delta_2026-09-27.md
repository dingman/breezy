# EDGE-2-MULTIPAGE plan r2: DELTA over r1 (BINDING; overrides r1 where they conflict)

Round-1 reviews (all blind):
- architect: REQUEST_CHANGES, 3 blocking items. All claims verified, including that the firewall allowlist admits the inline checks.
- domain: ENDORSE-WITH-CHANGES.
- python: C9 I8 T7 R8 S9 F9, no blockers.

The reviewers do not contradict each other. Coordinator merge below.

## M-1. Malformed page: stop and return INCOMPLETE, never `None` and never complete
This merges architect NB1 and python NB1.

On any malformed page, the loop stops and returns `TradeJoin(complete=False, trade_count=<rows found so far>)`. A malformed page is either of:
- `activities` is not a list;
- `eof` is present and is not a bool. This is stricter than `is True` and matches the refusal at `reports.py:1810`.

This is the same shape as a page-cap hit (`:4095`). Why this shape:
- The dangerous direction stays closed. Incomplete blocks retirement (`client.py:2779`).
- A trade already found on an earlier page still raises the CRITICAL contradiction on the same pass. A `None` return would have discarded that evidence (python NB1).

Missing `eof` behaves as before: it counts as not-EOF, so the loop continues to the cap and the result is incomplete.

## M-2. The warning names the keys it saw (architect B1, L-37)
- Log the keys with `[k for k in page]` inside the f-string. This adds no new call. `sorted`, `list` and `.keys` are NOT on the allowlist (`test_execution_egress_firewall_guard.py:2101-2254`).
- The keys are names only; no values are logged.
- The unmodified firewall guard run confirms this. If the guard rejects it, stop and report. Do not substitute `type()`. This closes python NB2.

## M-3. Multi-page reads are visible (architect B3)
- When a read traverses more than one page, log at INFO (or higher) with the page count. `_page_index` is already in scope, so no new callee is needed.
- Step 2 (the probe) is triggered when EITHER that INFO line appears OR the account's activity count reaches 80 or more.

## M-4. Step 2 is DEFERRED (architect ruling)
- Merge Step 1 alone.
- When the trigger fires, run the probe as follows:
  1. Fix the archived `probe.py.txt` itself: add `--limit`, and replace `bool()` with `is True`.
  2. Add pure tests for it in `tests/unit/test_edge2_ambiguous_order_probe.py`, written first (architect B2).
  3. Copy it into a dedicated worktree, never into the primary tree's `scripts/venue/`, so the B1–B6 guards stay clean for other agents.
  4. Run it once as a `systemd-run` oneshot.
- No part of Step 2 is done now.

## M-5. Tests (added or amended)
- **T1:** add a rationale comment. JSON decodes only `true`/`false` to `bool`, so any non-bool `eof` is venue schema drift. Parametrize over `"false"`, `"true"`, `1`, `"0"`, `0`, `None` (a present null), plus a `True` control. Expected for each case:
  - non-bool present → incomplete;
  - `True` → complete.
- **T2** (activities is not a list, on page 1) and **T2b** (well-formed non-matching page 1, malformed page 2; domain item 2): both return incomplete.
  - If the test harness's `_log` is an observable fake, assert that the warning names the keys it saw.
  - If it is not observable (the Nautilus logger is read-only), prove key naming by a source-level AST assertion in the same file.
- **T7:** a trade on page 1 followed by a malformed page 2, where the order GET returns terminal-zero. Expect the contradiction path: stays AMBIGUOUS, CRITICAL raised. This pins M-1.
- **T8:** a two-page read produces the multi-page INFO signal. Assert it by the same mechanism as T2.
- **M8** (`if not page.get("activities")`) is killed by the existing test at `:4017`. List it.
- **M9** (the guard placed before the loop, so only page 1 is checked) is killed by T2b.
- **M10** (return `None` instead of incomplete) is killed by T7.

## M-6. Threat-model additions (domain item 1)
- **NO-side trades.** Order-id matching compares `aggressor.id` / `passive.id` only (`account_activity.py:411-413`); side is never consulted. The implementer must cite a captured fixture containing a real SELL/BUY_SHORT trade row that carries those ids.
  - If no such fixture exists, record this in the risk register as UNOBSERVED, alongside D3.
- **Clock skew is not a factor.** `age_ns` is computed from two reads of the same local clock (`client.py:2726,2786`), so there is no cross-clock skew to consider.

## M-7. New follow-up to file: TRADE-ROW-DRIFT (architect NB2)
A trade row with malformed or renamed `trade`, `aggressor` or `passive` fields is treated as not matching (`account_activity.py:405-414`). Under field drift (L-37), that is a more likely route to a false ZERO_FILL than D1 is. It is out of scope for this item. Add it to the PROGRESS follow-ups.

**Confidence after r2:** HIGH. Every blocking item has a reviewer-specified fix. The implementation review must confirm M-1 through M-3 against the unmodified firewall guard.

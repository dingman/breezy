# S4 r4 delta rev 3: security review, round 3 (final)

Date: 2026-10-14. Reviewer: security-reviewer (blind). Scope: `S4_exec_resting_order_path_plan_r4_delta.md` rev 3 (259 lines) vs round-2 `S4-r4-security-review-round2.md`.
Code facts (codegraph, HEAD): `client.py:6559-6606` (`calculate_commission`, MAKER -> `_refuse`, no order id), `:7587-7610` (`_cancel_order` refuses, `_cancel_all_orders` raises), `endpoints.py:125-140` (`order_by_id_path`: denylist `/?#\` + whitespace), `write_transport.py:160-175` (`post_cancel_all` bodiless, no `src/` caller).

## Verdict: APPROVE (no CRITICAL/HIGH). Three MEDIUM text edits (E1-E3) must land in the plan before the WP4/WP5 briefs; no further review round needed.

## Round-2 disposition
| Finding | Status | Evidence (rev 3) |
|---|---|---|
| N-1 commission readers | RESOLVED | l.133: `recognised_commission` feeds `cumulative_fee` AND native `OrderFilled.commission` (covers `Position.realized_pnl`); raw only in existing `venue_fee_raw`; two-sided static scan l.134. Reusing `venue_fee_raw` (`:968`, written `:7295`) is sound: no second raw field |
| N-2 alert age | RESOLVED | l.123 P16 + l.156-157: alert at first_refused+600; latch >= first_refused+660 (floor term), so alert strictly precedes latch for all inputs; property test l.182 |
| N-3 id denylist | RESOLVED, see E2 | l.119, l.140 allowlist `^[A-Za-z0-9_-]{1,64}$` in builder + transport; `market_slug` via `parse_weather_slug`; `json.dumps` |
| N-4 context overwrite | RESOLVED | l.71 threads `resting` through all 3 `_note_ambiguous_open` writes; post-HOLD assertion l.71, l.181 |
| N-5 N5 matching | RESOLVED | l.113 substring, `src/`+`scripts/`, one sha constant for N5+B4, planted import |
| R-1 sweep ruling | ADOPTED (l.143, 208). Attribution exception narrowed to ADOPT path: acceptable (stricter than my ruling) |

## New findings (rev 3 departures)
**E1 MEDIUM (l.87, CC-1): slug-keyed carve-out is a partial bypass.** Keying on "slug has a ledger row/context" suppresses the unintended-MAKER refusal for EVERY maker reconciliation fill on that slug while a rest exists, including a foreign/manual order or a second unintended maker fill, not just our bound order. Fail-open for the alarm it exists to preserve, though cash is priced at taker. Fix: carve out only when `last_px == ledger row price` AND `last_qty <= row remaining qty` AND the row is not yet retired (all available as hook params: `last_px`, `last_qty`, `instrument`); otherwise refuse as today. Also WARN-log (slug only) every carve-out use. Add RED `test_maker_fill_on_ledger_slug_with_foreign_price_or_qty_still_refuses`. If store enumeration (UNVERIFIED l.38) is unavailable at build, the carve-out defaults OFF (refuse), never on. The method must still never raise: enumeration errors map to "not in ledger".
**E2 MEDIUM (l.81, l.119, l.142): id regex refusal inside the retry loop, and sentinel ids.** (a) `cancel_order_path`/transport raise `ValueError` for an id outside the allowlist; `_cancel_resting_order` loops forever on retry or dies silently. Specify: an id that fails the allowlist is validated at BIND time (fail -> HOLD, never bound) and, if met in the loop, is treated as terminal-unconfirmable: CRITICAL alert + `resting_cancel_unconfirmed` latch immediately, no retry, no raise out of the coroutine. (b) Key enumeration for cancel/ledger ids must exclude contexts whose `venue_order_id == NO_VENUE_ORDER_ID` (pre-POST no-id context, `resting=True`): they are not cancellable until ADOPT supplies an id. Test both.
**E3 MEDIUM (l.74): binder clears the GLOBAL AMBIGUOUS refusal.** Same inline pattern as A3, but the plan does not state A3's predicate. Fix: the clear runs only when the bound intent is the sole open AMBIGUOUS intent (store scan, same predicate as `:4046-4065`); another unresolved AMBIGUOUS context (e.g. a no-id taker intent) keeps the refusal. RED `test_resolver_bind_does_not_clear_refusal_while_another_intent_ambiguous`.
**L1 LOW (l.116, P7): prefer the fallback.** `V2_ORDER_READ_PATH_ALLOWLIST` is a READ allowlist; adding a write-path literal to it is a semantic widening even with a plant. Use `order_by_id_path(id) + CANCEL_SUFFIX` (no V2 literal, no widening) as the PRIMARY; T3 string-equality plus the regex already pin the path. If the literal route is kept, the plan must show the V2 write-path test still trips on every other write path (l.116 build check) before merge.
**L2 LOW (l.134, hygiene): log hygiene for `venue_fee_raw`/`commission_sign`.** State that neither is logged above sign class (+/0/-) and never in alerts; `BpsDrift` already value-free.

## Departures checked (item 2)
- Slug-keyed carve-out: see E1. Taker fills never reach the MAKER branch; the carve-out does not touch the budget ledger (`settle` = qty*avgPx, commission-free).
- Empty-slug cancel-all: not reachable. `_cancel_all_orders` loops ledger ids via `_cancel_resting_order` (never `post_cancel_all`); `post_cancel_all` single-referenced (N3/N5), transport refuses empty/non-weather, pin False disables the helper, WP6 bans negative control. PASS.
- Cap/spend ledger and arm gate: slot+budget held on HOLD/RETRY, settle once on terminal; no new path to `authorize_order_cost`/`settle`; unbound orders keep the arm gate refusing (P14 own-row exclusion is r3). PASS.
- Retry loop inside `_cancel_resting_order`, GET-only `_confirm_cancel_terminal`: firewall rows N1/N2 keep GET sets GET-only; one send callee. PASS.

## UNVERIFIED list (item 4)
| Item | Fail-closed? |
|---|---|
| `cancel_order` runs in own task (l.34) | NO as written: if inline, a 60 s sleep blocks the exec command queue. Make it a WP4 gate with named fallback (spawn via the client's native task helper, still no timer) before N2 merges |
| `write_transport` import cycle | YES (lint-imports + named fallback) |
| I1b refusal on `fee_reconciled=False` (l.36) | YES (latch NEW rests only) |
| Id charset (l.37) | YES (allowlist refuses); see E2 for the failure handling |
| Store key enumeration (l.38) | NO unless E1 default-off and "empty ledger = zero POSTs" are stated; add both |
| `strategy.pyx:1734-1748` | YES (re-check; GTD cancel simply routes to `_cancel_order`) |
| `scripts/` fee readers | PARTLY: make enumeration a precondition to merging the poll booking, not a step inside it |

## Invariant checklist
| Invariant | Result |
|---|---|
| Exact sets only widen; own commit + plant each (FW/P/N/T/CC rows) | PASS (T2 forced edit is labelled and planted; L1 on P7) |
| `allow_short` False, BUY only | PASS |
| No live enablement / `BREEZY_ORDERS_ENABLED`; family SHADOW | PASS (pins flip only by reviewed commits) |
| Operator caps untouched | PASS |
| NO-SEND firewall / banned-word ban unedited | PASS |
| Nautilus immutable | PASS |
| Secrets/log hygiene incl. `venue_fee_raw`, `commission_sign` | PASS with L2 |

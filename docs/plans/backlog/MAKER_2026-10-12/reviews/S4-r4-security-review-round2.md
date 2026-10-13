# S4 r4 delta rev 2: security review, round 2

Date: 2026-10-13. Reviewer: security-reviewer (blind). Scope: `S4_exec_resting_order_path_plan_r4_delta.md` rev 2 (232 lines) vs round-1 `S4-r4-security-review.md`.
Code facts (codegraph + regex on HEAD): `write_transport.py:160-175`, `operator_controls.py:281,504-571`, `exit_wiring.py:231`, `continuous_strategy.py:2933`, `exit_guard.py:90-110`, `exec_par_counter_ingest.py:354-363,454`, probe `:325-335,459,655`, `client.py:7587,7609`.

## Verdict: REQUEST_CHANGES (narrow)
No CRITICAL, no new HIGH. Round-1 H1, H4a-c resolved; H2, H3, H4d partly. Four MEDIUM text-level gaps (N-1..N-4) in the commission scan, retry-age definition, id validation and context overwrite. Fix as plan edits, then APPROVE without another full round.

## Round-1 disposition
| Finding | Status | Evidence (rev 2) |
|---|---|---|
| H1 slug scope unverified | RESOLVED | l.125 pin `SLUG_SCOPED_CANCEL_ALL_VERIFIED=False`, helper returns UNSCOPED_UNVERIFIED without sending; l.105 P16; l.82 WP6 own-orders-only two-slug proof |
| H2 raw negative reaches spend readers | PARTLY | l.117 accessor `max(raw,0)` + scan. Ledger path verified commission-free (`authorize_order_cost` = price*qty; `settle` = qty*avgPx; `operator_controls.py` and `safety.py` have no commission/realized_pnl reader). Scan scope misses real readers: N-1 |
| H3 RETRY unbounded | PARTLY | l.139-141 backoff, alert, latch after `expire_time`. Age bound tied to goodTillTime: N-2 |
| H4a existing tests | RESOLVED | l.101-102 T1 unedited + companion, T2 tightened not deleted |
| H4b body built in transport | RESOLVED | l.124 body built inside, re-parsed, empty/dup/non-daily refused |
| H4c probe / tree scan | RESOLVED with condition | l.100 N5 scans `src/`+`scripts/`, probe sha256-pinned; R-3 |
| H4d per-order path/id | PARTLY | l.103 T3 path equality, shared builder; id check is a denylist, charset UNVERIFIED: N-3 |
| M1 shared callee set | RESOLVED | l.98 N3 plants (`_submit_order` must not reference cancel helpers) |
| M2 one row per commit | RESOLVED | l.88-111 names listed, commit order |
| M3 FILLED_ANY via taker path | RESOLVED | l.77, l.205, test l.170 |
| M4 cross-check before bind | RESOLVED | l.59 `resting_echo_matches` incl. tif GTD |
| M5 slot/budget at deadline | RESOLVED | l.67, l.136 |
| M6 regex duplicate | RESOLVED (conditional) | l.151 single grammar source, registry-city raise, zero-parsed alert |
| M7 id/slug-only logging | RESOLVED | l.128 |
| L1 / L2 / L3 | RESOLVED | l.151, l.116 (`commission_sign`), l.128 |

## New findings (ranked)
**N-1 MEDIUM (l.117, 170): commission scan misses the actual readers.** Scan targets "`FillReport.commission` or `commission_raw`". HEAD readers of the native booking use `OrderFilled.commission` (`event.commission`): `strategy/current_rung_hold/exit_wiring.py:231` and `continuous_strategy.py:2933` (feed `latch.record_exit(exit_fee=...)`, a loss-stop/ROI input), `runtime/exec_par_counter_ingest.py:454` (fee-drag counter), `strategy/harness_probe.py:245`. `settlement/exit_guard.py:90-110` REQUIRES `Position.realized_pnl`, which Nautilus seeds from `-commission`; an unverified negative maker commission raises realized PnL feeding the kill/return gate. A name-scan on `FillReport.commission` passes while all of these see the raw sign. Ledger readers (budget, per-position, `settle`) are NOT exposed; the plan says so correctly. Fix: (a) widen the scan to `\.commission\b`, `commission_raw`, `realized_pnl` over `src/` and `scripts/` (not only `scripts/analysis/`); (b) allowlist the readers above with one disposition each; (c) simplest single point: while `MAKER_COMMISSION_SIGN_VERIFIED` is False, book `max(raw,0)` natively on the resting path (round-1 Q1 fallback) and keep raw only in durable `commission_raw`; this removes the whole reader class including `Position.realized_pnl`.

**N-2 MEDIUM (l.140, P16): retry alert age tied to goodTillTime.** `max(goodTillTime+grace, 30 min)` is later than the `expire_time` latch (l.141); the alert fires after the latch, so a halted cancel can fail silently for the whole GTD life. Fix: age from the first refused cancel, short constant (e.g. 10 min) independent of GTD, re-alert every `RETRY_WHEN_OPEN_REALERT_S`; test alert precedes latch.

**N-3 MEDIUM (l.103, l.33): order-id validation is a denylist.** Charset UNVERIFIED; refusing `/ ? # % .. whitespace` leaves `\`, control chars, `;`, unicode. Fix: fail-closed allowlist default `^[A-Za-z0-9_-]{1,64}$` in BOTH `cancel_order_path` and the transport; if WP0 evidence ids violate it, widen by one reviewed evidence-cited row, never fall back to a denylist. Also state that `post_cancel_order` validates `market_slug` with `parse_weather_slug` and builds the body via `json.dumps` (l.124 says only "the same way").

**N-4 MEDIUM (l.21, 66, 168): context overwrite after HOLD.** `_note_ambiguous_open` overwrites the pre-POST context for the same key and has no `resting` field at HEAD. Step (1) writes `resting=True`, but the HOLD fall-through then overwrites it; the resolver bind branch would never see `resting=True`, leaving an accepted rest AMBIGUOUS-held (fail-closed but strands the cancel path). Fix: `_note_ambiguous_open` must carry `resting` forward; assert `context.resting is True` AFTER the HOLD branch in the crash/resolver test.

**N-5 LOW (l.100): N5 matching.** Specify substring match (catches `_signed_post_cancel_all`, `_CANCEL_ALL_PATH`) and a plant importing the probe helper from a new script. Concatenated paths evade literals; covered by N3 single-reference.

## Rulings
**R-1 Sweep with pin False (l.127).** Leave-and-refuse is ACCEPTABLE and the right default: an unbound id may be an operator's manual order, and l.126 keeps the cancel set ledger-bound (no ids from an open-orders reply). Conditions: (a) arm-gate refusal raises one CRITICAL alert via existing delivery; (b) exception: an unbound order positively attributed by the r3 WP5 no-id attribution (slug, side, price, qty, window match a durable no-id AMBIGUOUS intent) MAY be cancelled by id, as provably ours; (c) test `unbound_unattributed_order_never_cancelled_by_sweep`.
**R-2 Commission accessor:** see N-1. `authorize_order_cost`, `settle`, `operator_controls.py`, `safety.py` clean at HEAD.
**R-3 Legacy probe (l.100):** sha256 exemption is acceptable for S4 (no `src/` reach; WP6 forbids reuse, l.82). Recommend neutralising `_signed_post_cancel_all` in a separate reviewed commit after S4 lands (the 09-04 control is done); then N5 drops the exemption.
**R-4 T1/T2/T3:** adequate; add the N-3 allowlist.

## Invariant checklist
| Invariant | Result |
|---|---|
| Firewall exact sets only widen, one row per commit + plant (L-12/L-46) | PASS (l.88-111; keyword-free names leave the banned-word loop unedited) |
| `allow_short` False, BUY only | PASS (l.11) |
| No live enablement / `BREEZY_ORDERS_ENABLED` | PASS; pin flips need reviewed commits |
| Operator caps untouched | PASS (ledger commission-free); N-1 covers PnL-side readers |
| Family SHADOW | PASS (l.8) |
| Nautilus immutable | PASS |
| Secrets / log hygiene | PASS: ids+slug only, `BpsDrift` value-free; `commission_raw` is a financial value stored as exact string (no float); keep out of INFO logs beyond sign class |
| Empty-slug cancel-all reachable | NO: transport refusal + pin False + choke point + N5; WP6 bans even a negative control |
| Inline confirm | PASS: NEW-only, context before await, intent held in `_post_in_flight_intent_ids`, all else HOLD (subject to N-4) |

## §11 answer
Leave unbound open orders and keep refusing arming (R-1), with a CRITICAL alert. Permit a by-id cancel only for an unbound order the no-id attribution path positively identifies as ours. Never auto-cancel an unattributed order, and never take ids from an open-orders reply for a blanket cancel.

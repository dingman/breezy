# S4 r4 delta (rev 1) — architect review — 2026-10-13

Verdict: REQUEST_CHANGES. (Recorded by the coordinator verbatim from the reviewer's return; the reviewer had no write tool.)

## The three verifications (read from the code)
- **V1 `_submit_order` with an async 200 + id.** No executions → the classifier falls through to AMBIGUOUS with `venue_order_id` set (`submit_chain.py:1324-1338`). `_submit_order` then calls `_refuse(AMBIGUOUS_REASON, instrument="")`; at K=1 that is a global, durable refusal with an alert (`client.py:7516-7521`), then emits submitted and writes the with-id context (`:7543-7583`). The with-id resolver applies no age floor to NEW: it logs "neither terminal nor a fill" and polls every 5 s (`:3391`, `:589`). The 120 s floor guards only terminal-zero and needs a complete activities join (`:3498-3513`); the 300 s floor is no-id only (`:4304`). The delta's "the with-id resolver after its floor decides (NEW…)" (l.115) is wrong.
- **V2 `write_transport` may import `parse_weather_slug`.** No import-linter contract forbids it: both modules sit in the `adapters` layer (`pyproject.toml:74-106`); the write-transport tests pin only who imports `write_transport`. `lint-imports` must still print "N kept, 0 broken" at build.
- **V3 open-orders envelope.** The SDK declares only `{orders}`. `parse_open_orders` already defines completeness: a missing `eof` counts as complete, `eof != True` is refused, other unknown envelope keys are only recorded (`reports.py:1640-1643`, `:1790-1797`).

## HIGH
1. **l.101 completeness rule would block every sweep.** "Cannot prove completeness = UNREADABLE" never certifies because the venue returns `{orders: []}` with no `eof`; every boot with a ledger slug would latch. Fix: reuse `parse_open_orders` and additionally require the recorded unknown envelope keys to be empty (a future `nextCursor` refuses).
2. **l.73/75 unlisted firewall pins.** `test_execution_egress_firewall_guard.py:3374-3381` bans any callee containing "read" or "post" except `post_order`, and its docstring says the ban stays unweakened. `self._post_slug_cancel_all` and `self._confirm_resting_by_read` both trip it. `ORDER_SENDER_REFERENCE_PERMITTED_SCOPES` (`:4374`) also lacks the new helper. Both need named exact-set rows with plant tests (L-12, L-46).
3. **l.110-115 inline confirm goes too far.** It retires TERMINAL_ZERO and books FILLED_ANY inline, skipping the 120 s floor and the trade-join evidence (L-36, L-52). Fix: inline confirm acts on NEW only; anything else stays HOLD and goes to the resolver. The branch must sit before `_refuse` and `mark_ambiguous`; l.46 must say "AMBIGUOUS with id", not "anything but ACCEPT_FILL" (a 4xx REJECT or ZERO_FILL would otherwise enter the confirm loop).
4. **l.46-47 vs l.150 crash test cannot go green.** During confirm the on-disk context is still the no-id pre-POST one, so a crash resolves through the sweep and the no-id path. Fix: write the with-id `resting=True` context before awaiting confirm, and keep the intent in `_post_in_flight_intent_ids` (`client.py:4299`, `:7180`) so the resolver cannot bind it twice.
5. **l.129 discovery hardening contradicts an existing test.** `test_polymarket_us_discovery.py:653-664` requires a non-`tc-temp` slug with a weather question to raise. The raise fires only when the question matches `... on `, and the recorder has been discovering all 71 listed markets, so the fault is latent. Make step 0 a characterisation test on a 71-market fixture; change code only if it goes red (L-32, YAGNI).

## MED / LOW
- `classify_resting_order_state` duplicates native `parse_order_status_report` / `ORDER_STATE_TO_ORDER_STATUS` (`reports.py:441`, `:1124`); branch on `OrderStatus.ACCEPTED` with `filled_qty == 0`.
- `_confirm_resting_by_read` has no callee pin of its own.
- Nautilus PnL books a negative commission natively regardless of the sign-verified gate; state what `settle(realized_usd)` includes.
- `taker_fee_bound` is an unverified name.
- l.51: request signatures do not cover the body (`build_canonical_path_without_query`), so "refuses before any byte is signed" is wrong; the transport-side body check is the last control before the wire.
- The daily-prefix regex duplicates `_WEATHER_SLUG_RE`.
- Tests that cannot fail before the change (four-key drift pin, `unsolicitedCancelReason` refusal, taker-fill refusal, IOC key set, classifier source hash, never-reads-bps, discovery still-raises/never-raises pins): label characterisation, require mutation evidence (L-33).

## Pin rows
Every exact set stays `==` against HEAD. P5 reshape fine. P3 avoidable. P23 dropped and P11 no-change correct. Gaps: HIGH-2.

## Open questions
1. Book the raw value, never refuse (refusing holds K=1 until WP6, which itself needs an own passive fill booked: deadlock, L-48).
2. Keep the raise for daily-prefix slugs; WARN is enough as the sighting; see HIGH-5 first.
3. Drop `_read_market_state` and P3: the data client already publishes native `InstrumentStatus` carrying raw `marketData.state` (`parsing.py:1035-1060`). Use "refused, or still NEW" as the proxy; latch only once `expire_time` has passed.
4. Inline confirm on NEW only (HIGH-3).
5. Unfiltered read is fine at this volume with the HIGH-1 completeness rule.

## Sequencing
Tolerance audit + characterisation tests may be built now (independent of S2/S3, no exec code). No provider code change merges unless the fixture test goes red; if it does, it is a live fault: full gate, recorder + node restart in the 01:00–16:40Z window.

## LESSONS
HIGH-2 → L-12/L-46 rows. HIGH-4/HIGH-5 → L-47/L-32 premise failures. Characterisation tests → L-33. Inline terminal-zero → L-36/L-52. Refuse-on-negative → L-48.

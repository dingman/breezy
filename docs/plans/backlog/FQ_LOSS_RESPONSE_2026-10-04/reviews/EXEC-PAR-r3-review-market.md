**Overall verdict: NOT-READY (79/100).** r3 resolves all my r2 findings in design. Two new defects remain, both in code paths I checked directly, and both are small to fix.

**WP-DR verdict (budget correctness, standalone): READY, conditional (84/100).** It never double-counts, and it is strictly better than today's behaviour. Two spec edits are required before the build (W-1 and W-2 below).

## New findings

**HIGH-1. The duplicate detector's `qty_est` is wrong on the NO leg, the target population.**
- Evidence:
  - §3.6 sets `qty_est = notional_usd / Decimal(wire_price)`.
  - `submit_chain.py:363-372` says the wire `price.value` is always the YES-side price, "identity on the YES leg, `1 - price` on the NO leg". `AmbiguousResolverContext.wire_price` stores `body["price"]["value"]` (`client.py:6313`).
  - `notional_usd` is built from the instrument price (`order_price_decimal`), not the wire price.
- Failure: a NO buy at 0.92 has wire price 0.08. `qty_est = 0.92q / 0.08 = 11.5q`. The test `venue_leg_qty − baseline > qty_est` would need an 11.5× position to fire. A doubled NO position is invisible, and the breaker's duplicate trigger is dead for exactly the NO≥0.90 population the plan exists for.
- Answer to open question 2: `qty_est` is not adequate. Add a trailing-optional `wire_quantity` to `AmbiguousResolverContext` (AR-N6 pattern), taken from the order quantity at the pre-POST write, and use it directly. If that is rejected, compute `notional / instrument_price` via `leg_prices`. Never divide by the wire price.
- Add a RED test with a NO-leg 0.92 intent and a doubled holding that must trip.

**HIGH-2. The uncharged-settle predicate "created today" contradicts how fills are bucketed, so it undercounts.**
- Evidence:
  - Resolver-path fills are stamped `ts_event=now_ns`, the discovery time, by deliberate design (`client.py:3372-3383`: "booked into the discovery day's seed ... conservative: the discovery day's ledger and permit budget see this spend").
  - §3.5 settle adds realized cost only if the entry "was created today". A boot-registered or day-roll-converted intent was created yesterday, so settle adds nothing.
  - The fill record is stamped today, so the next restart's seed (which filters on `ts_event` day) counts it.
- Failure: in-process, the realized cost R vanishes from today's spend while headroom is released. After a restart it reappears. The undercount is up to R ≤ one per-order cap per midnight-crossing fill, and K × cap when K slots are stuck across the roll. That is the stuck population by construction.
- Correction to my r2 answer on open question 4: I accepted ignoring cross-day fills for budget, assuming the fill timestamp is the order time. The code stamps discovery time, so my answer was wrong for the resolver path.
- Required change: settle adds `max(R − seeded_partial, 0)` whenever the fill record's `ts_event` day is the current day. That is the same predicate the seed uses, so in-process matches post-restart. Drop "created today". Add a property test that in-process spend equals seed-after-restart spend over the day-roll interleavings. The exactly-once claim, including partials, is otherwise sound (below).

## Verified resolved from r2
- **HIGH-1 (permit waste):** the read-only pre-check now precedes the permit spend (§3.3 step 4), with six pre-spend tests asserting the permit, booking and day-stop marker are untouched.
- **HIGH-2 (permit seeding):** unchanged, durable fills only. I verified `seed_permit_budget_from_prior_spend` (`safety.py:799-841`) is called only from the fill seed.
- **HIGH-3:** the bound applies to `mark_ambiguous` notional only, with a c/B sweep in the stop rule.
- **HIGH-4:** `f_breaker = 0.25 < f_adm = 0.50`, so the trigger is live. CONTRADICTION is sticky.
- **MEDIUM-1:** the cool-off is durable (see LOW-2 for a residual).
- **MEDIUM-2:** `_roll_locked` and per-key `_unknown_keys` are specified and tested.
- **MEDIUM-3:** both free-balance arms are modelled and the stop rule uses the worse one.
- **MEDIUM-4:** D-PREREG content mostly complete (MEDIUM-3 below).

## WP-DR detail
- **Never double-counts.** A prior-day booking sits on an accumulator that is already reset or about to be, so skipping its true-up or release only avoids a raise. The permit restore on zero-fill is session-scoped and correct.
- **W-1 (required): do not swallow genuine same-day accounting errors.** The `except LiveTradingPermissionError: log ERROR, continue` also swallows `true_up_booking`'s "a fill cannot cost more than authorized" (`operator_controls.py:509-513`), which the ledger documents as "surface, never absorb". Swallowed, the booking stays at its smaller authorized cost and the realized spend is undercounted. Skipping on `booking.day != today` already fixes the midnight case, so the wrapper is unnecessary there. Drop it, or restrict it so the over-authorization and clock-rewind errors raise a visible alert. Open question 6 (health surface) should be answered yes: log-only is not enough, and an alert avoids the 25-site `_refuse` pin if it uses an existing channel.
- **W-2 (required): fix the test premise.** `test_fill_timestamped_before_midnight_resolved_after_is_not_counted_in_new_day` is wrong for resolver fills, which are stamped with discovery time (`client.py:3383`). State the real behaviour, and add a test naming the accepted undercount (R ≤ one cap per crossing fill at K=1, as the in-process figure until restart). It is bounded and strictly better than today's raise-and-leave-OPEN deadlock. If you would rather close the gap in WP-DR itself, the HIGH-2 predicate applied there would require an additive ledger method, and it can wait for WP3.
- Verify with the firewall guard that the new `utc_day_for_ns` call and `INFO` log in the three helper bodies need no allowlist row, as the plan asserts.

## Requested checks
- **§3.5 exactly-once with partials:** sound. The seed counts partial P, registration adds N − P, and settle adds R − P, so P + (R − P) = R. While open, the total is N (conservative). The boot interleave follows from F15 (fill handlers are synchronous and fall wholly before or after the seed span). Only the "created today" predicate fails (HIGH-2).
- **§3.6 breaker numbers:** stuck at 720 s (with-id) and 900 s (no-id), trip at ≥2 stuck, `f_breaker = 0.25`, and sticky CONTRADICTION are sensible. Only the detector is broken (HIGH-1).
  - Residual: a duplicate that fills no more than one order's quantity is undetectable. Exposure there is still bounded by the cap, so it is acceptable.
  - Specify the watcher latency, which should be at most one resolver poll (5 s), or evaluate `ambiguous_total > f_breaker × budget` inline in the admission pre-check.
- **Open question 1 (durable entry-halt key):** acceptable, and better than the veto signature change. Halting exits during a suspected double position would hurt. Cost is one `get` per admission.
- **Open question 3:** `f_adm = 0.50` as a backstop above `f_breaker = 0.25` is fine.
- **Open question 4 (synthetic boot cool-off):** apply it to every slug that had an OPEN slot at boot, not only those the first pass retired. It is conservative and cheap.
- **Open question 5 (lag guard):** require a measured positions-feed lag bound from WP0 where the pre-10-07 data allows it. Otherwise default the guard age to 300 s, not 120 s.

## MEDIUM
- **MEDIUM-1. §7 stop rule: the unreadable-caps fallback is unsound.** "Worst bucket if unreadable" is c/B = 0.50. With `f_adm = 0.50`, one AMBIGUOUS order then blocks every later entry, so the plan would STOP on an unknowable.
  - Use realized order cost over B, not the per-position cap, as the sweep variable (orders are about 1 contract at ≤ $1).
  - Report K per bucket. Make the stop rule apply at the actual bucket, and gate activation on re-running it once the ratio bucket is known.
- **MEDIUM-2. WP5a/§3.1 residual:** an arm at 0→1 writes a fresh v1 record. State and test that it preserves unexpired `cooloff` entries for other slugs (`test_arm_from_empty_preserves_unexpired_cooloff`).
- **MEDIUM-3. D-PREREG gaps.** Add:
  - the operator-reset procedure and conditions for the entry-halt;
  - a statement that parallel-execution fills do not feed back into the M1-v3 verdict statistic or its look schedule;
  - the frozen WP0 artefact hash and the chosen K's CI;
  - the per-slug cool-off scope (entries only);
  - the detector definition, now including `wire_quantity`.

## LOW
- **LOW-1:** the pre-check reports "headroom held" as a WAIT without marking the day stop. That is right. If it reports plain `spent + cost > budget`, consider also marking the day, so the strategy's re-arm gate stops hunting.
- **LOW-2:** the entry-halt reset CLI should require an acknowledgement that held positions were reviewed.

Files checked:
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r3.md`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py` (:3372-3429, :6313)
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/submit_chain.py` (:363-372, :685)
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/operator_controls.py`
- `/home/jon/breezy/src/breezy/adapters/polymarket_us/safety.py`

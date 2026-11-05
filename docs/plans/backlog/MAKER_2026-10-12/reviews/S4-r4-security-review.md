# S4 r4 delta (rev 1): security review

Date: 2026-10-13. Reviewer: security-reviewer (blind). Scope: `S4_exec_resting_order_path_plan_r4_delta.md` on top of r3.
Code facts checked (codegraph, projectPath /home/jon/breezy): `write_transport.py:160-175`, `reports.py:291,333`, `provider.py:255-262`, `symbology.py:173-183,608-640`, firewall guard `:4385`, probe `scripts/venue/polymarket_us_write_signing_probe.py:325-336`.

## Verdict: REQUEST_CHANGES
The design direction is sound and strictly safer than r3 on the cancel path. No CRITICAL. Four HIGH items need text changes before build. None needs a redesign.

## Ground truth at HEAD that the delta must account for
- `PolymarketUSWriteTransport.post_cancel_all` today is BODILESS (the existing `post_cancel_all(api_base_url, *, headers)`), so it is ALREADY an account-wide cancel at the venue (docs: empty/missing slugs = cancel all). Nothing in `src/` calls it yet. The delta's fix (required non-empty `slugs`) is correct and removes a latent loaded gun.
- Two existing tests pin the old shape and the delta does not list them: `test_the_write_callable_has_no_method_query_or_body_parameter` (asserts `body`/`params` not in the signature) and `test_it_issues_exactly_one_post_to_the_one_pinned_path` (asserts call keys == {url, headers, keys}). They WILL go red. Editing them is a contract-test change (CLAUDE.md: never weaken). See H4.
- `scripts/venue/polymarket_us_write_signing_probe.py:_signed_post_cancel_all` sends `body={}` to `/v1/orders/open/cancel`: a deliberate account-wide cancel, outside the transport. The "post_cancel_all appears in ONE body in the whole tree" claim (P25) is false as written for `scripts/`.

## Findings

### HIGH
- H1 (delta l.65, 99, 117-118; evidence row (d), S-2): slug-scoped cancel-all scoping is UNVERIFIED (`slugs` honoured is observed nowhere; cf. the inert `activities?marketSlug`). If the filter is inert, `_post_slug_cancel_all(slug)` is an account-wide cancel, defeating all four layers (they only guard what is SENT). The escalation path (l.118) and sweep are built before WP6 proves S-2. Fix: add RulePin `SLUG_SCOPED_CANCEL_ALL_VERIFIED: Final[bool] = False` (same discipline as `MAKER_COMMISSION_SIGN_VERIFIED`); `_post_slug_cancel_all` refuses (returns UNSCOPED_UNVERIFIED, falls to per-order cancel + latch) while False; flipped only by a reviewed commit citing the WP6 two-slug artifact. WP6 two-slug test must be run with only own probe orders resting.
- H2 (l.58, 90-91, 160): the negative-commission gate covers only "analytics consumers". The raw negative value is also booked to native `FillReport.commission` (Nautilus account/portfolio), which feeds balance, realised PnL and any budget/headroom reader. An unverified sign therefore CAN change cap/spend computation. Fix: enumerate every reader of commission for spend/cap/daily-budget/per-position and route them all through ONE accessor `recognised_commission(record)` = `max(raw, 0)` while unverified; add a RED test that the budget/stop code never reads `FillReport.commission` or `commission_raw` directly (static scan). Persist raw for audit as designed.
- H3 (l.117, 124, 164): RETRY-WHEN-OPEN has no alert, no latch, no age bound, and its only bound is GTD/venue expiry, both UNVERIFIED (S-6, (g)). An order can sit un-cancelled and budget-held indefinitely with a WARN only; node-down means no retries until next boot. A detector without delivery is not a control (readiness audit lesson). Fix: age-bound the state (`RETRY_WHEN_OPEN_MAX_AGE_S`, RulePin, e.g. max(goodTillTime+grace, 30 min)); past it raise a non-latching CRITICAL alert through existing delivery, re-alert on a fixed interval; add retry backoff (not "every poll tick") to protect the rate quota. Test: `test_retry_when_open_alerts_after_age_bound_without_latching`.
- H4 (l.51, 98, 55, 82): the transport change and P25 scope are under-specified. (a) List and reshape the two tests above as a reviewed WIDEN: still no `method/query/params/timeout_secs/body-bytes`, permit exactly `slugs: Sequence[str]`, call keys == {url, headers, body, keys}, path equality kept; do not delete the assertions, tighten them. (b) The cancel-all body must be BUILT inside the transport from `slugs` (never accept caller bytes), then re-parsed. (c) State P25's tree scan covers `src/` and `scripts/`, and either route the probe's `_signed_post_cancel_all` through a dedicated pinned exemption (named, with its preflight) or add a plant proving the scan sees it; WP6 must not reuse that probe function (it sends `{}`). (d) Per-order cancel `/v1/order/{id}/cancel` is a SECOND write path with a venue-supplied id interpolated into the URL and no pin row: pin the path template by equality, validate the id against a strict pattern (`^[A-Za-z0-9]{6,32}$`), and add it to the pyo3-member / write-method pins.

### MED
- M1 (l.73, 76): P1 swaps `post_cancel_all` for `self._post_slug_cancel_all` in a set shared by the order coroutines. If `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` governs `_submit_order` too, the submit coroutine may now legally call the cancel-all helper. Net: removing the raw transport call is safer, but the permitted name is a wider reach. Fix: a per-coroutine test that only `_cancel_order` (and the sweep through P24) references `_post_slug_cancel_all`; `_submit_order` must not.
- M2 (l.73-76): P1 adds six callees, P4 two, P5 two, P24 and P25 new in one delta. L-12 says ONE reviewed row per step with its own non-vacuity plant. Fix: one commit per row, each with a plant that trips; "names fixed at build" is not acceptable for a firewall set, list them now.
- M3 (l.38, 113, 119): `FILLED_ANY` "existing fill paths ... reported with taker fills". If that routes through `parse_fill_report`/`_assert_taker_fill`, a maker-style (negative commission) fill is REFUSED and the fill goes unbooked: exposure exists, bot does not know. Fix: FILLED_ANY from the resting confirm and poll MUST use `resting_commission_total`; add `test_filled_any_with_negative_commission_is_booked_not_refused`.
- M4 (l.38, 111): `classify_resting_order_state` is over state only. Bind `NEW` only after cross-checking the GET Order's `marketSlug`, side, price, quantity, tif/GTD against the intent (the existing `_known_order` slug check partly does this); mismatch = UNREADABLE (HOLD), not bind.
- M5 (l.46, 115): inline 5 s confirm. Fail-closed as designed (deadline, GET error, UNREADABLE all keep AMBIGUOUS-with-id HOLD). Make explicit that the K=1 slot and budget are NOT released at deadline expiry, only on a terminal read; test it. A stop/shutdown during the window must leave the pre-POST resolver context intact.
- M6 (l.129): the "daily-shaped" tripwire regex is a second copy of the grammar. A 4-letter city code, renamed measure, or a separator change fails to match and is silently skipped (fail-safe for trading, but silent universe shrinkage). Fix: derive the prefix from `symbology._WEATHER_SLUG_RE` (one source); additionally keep the raise when `city_name` is non-None AND resolves to a configured registry city whose slug fails to parse; alert if a configured city yields zero parsed markets in a cycle.
- M7 (l.102): slug cancel-all also cancels unbound/manual operator orders on that slug. Documented, acceptable; add the id-only WARN and ensure the unfiltered re-read log emits ids and marketSlug only (no prices, no sizes).

### LOW
- L1 (l.130): dedupe set for sighting WARNs is venue-influenced; cap its size (slugs are `assert_valid_slug`-bounded at 128 chars so log injection is constrained).
- L2 (l.60): the commission envelope uses `abs()`; keep, but also bound the NEGATIVE side to the same envelope (it does) and log only the sign class.
- L3 (l.101): completeness of the unfiltered re-read is undocumented; see Q5.

## Layer-by-layer answer to the cancel question
Reachability of an empty/missing `slugs` from the wire, given H1/H4 are fixed: transport (non-empty, parse-valid, duplicates refused, body built inside and re-parsed) -> choke point (scalar, ledger-bound) -> call sites (ledger-derived only) -> P25 single-reference scan. The boot sweep and resolver reach the transport only through `_post_slug_cancel_all`; an empty ledger sends zero POSTs. Remaining holes are: the probe script (H4c), tests calling the transport directly (they construct a fake client, no wire; acceptable, but P25 must say tests are exempt only with a recording client), and venue non-honouring of the filter (H1, not a code path but a venue behaviour). `parse_weather_slug` is strictly stronger than the prefix check: it requires city[a-z]{3}, high|low, a valid calendar date, and 1-2 bound tokens ending in `f`, and rejects `tc-temp-sjc-dec-lt40`. It does not authenticate the slug as ours, which is why the ledger check (layer 2) is load-bearing.

## Async create + confirm (focus 2)
No silent-exposure path found with a create id: bind happens only on a GET `NEW`; every ambiguity (200 without id, transport error, deadline, unreadable) holds AMBIGUOUS and the pre-POST resolver context covers crashes. Residual: a 5xx/timeout with no id leaves an order that may rest; that is the existing no-id attribution path (r3 WP5), unchanged. The reverse case (bot believes resting, venue refused) cannot occur because accept requires a GET `NEW`. 5 s deadline is fail-closed provided M5.

## Invariant checklist
| Invariant | Result |
|---|---|
| NO-SEND firewall exact sets only WIDEN by one reviewed row, no `==` relax | CONDITIONAL PASS: no row removed or relaxed (the P1 `post_cancel_all` removal drops an r3 PROPOSAL, not an HEAD entry; P23 drop is an unchanged-hash anchor). Needs M2 (one row per commit) and H4a (existing transport tests tightened, not deleted) |
| P1 / P4 / P5 / P24 reshape is WIDEN not RELAX | PASS (all add names, none turned into issubset); net safer than r3 provided M1 |
| P25 single-body claim | FAIL as written (probe script, H4c); PASS after fix |
| `post_cancel_all` empty slugs never on the wire | CONDITIONAL (H1, H4) |
| `allow_short` False / BUY only | PASS (restated l.11; no change to shape admission) |
| No live enablement / `BREEZY_ORDERS_ENABLED` touch | PASS |
| Operator caps untouched / no assignment of reserved values | PASS (H2 protects cap inputs) |
| Family stays SHADOW | PASS (l.8, 11) |
| Nautilus immutable | PASS |
| Secrets / log hygiene | PASS (WARN carries public slug; BpsDrift is value-free; raw commission is a financial value not a secret; ids only) |

## Open questions
1. Do not refuse and strand the fill (an unbooked real fill is worse). Book the fill; persist raw; native booking may carry the raw sign for balance fidelity, but ALL spend/cap/budget readers use `max(raw,0)` via one accessor (H2). If the native booking cannot be separated, book `max(raw,0)` natively and keep raw in the durable record.
2. Keep the raise for daily-shaped slugs, with M6 hardening (single grammar source, registry-city raise, zero-parsed-city alert). A structured WARN suffices as the sighting; no AUD-08 schema extension.
3. Reuse an existing public-read seam if one exists; otherwise add `_read_market_state` under P3 (GET-only, plant test). Refusal-plus-still-NEW is NOT an acceptable proxy (a 400 or 500 would be misread as halt and suppress escalation). Read failure = not halted (fail toward cancelling), as drafted.
4. Inline bounded confirm, with M5 (no release at deadline). Deferring to the resolver widens the window where a resting order is un-bound, which is the worse failure.
5. Acceptable at <= 8 own orders. Absent a documented completeness signal, treat "returned count below the requested page limit and no next-page token" as complete; otherwise UNREADABLE (fail-closed). Verify the envelope in WP6; log ids only.

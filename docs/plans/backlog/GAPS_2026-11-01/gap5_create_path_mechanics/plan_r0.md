# GAP-5 CREATE-PATH-MECHANICS — plan r0
Status: r0, peer review pending (architect + security-reviewer). Read-only until the operator lifts the 11-01 19:55Z build pause (PROGRESS.md:69).

## 1 Objective
Stop a resting maker order from blocking every other order and from being replaced before it can rest, so a fill can happen and be scored. This gap does not create a winning edge (GAP-1/3/4 own that). It removes a mechanical cap on fills: on 11-01, 46 of 69 posts were denied with "submit intent is already OPEN" (P4_LIVE_READ_2026-11-01.md:20-21).

## 1a The brief's hypothesis does not match the code (verified by codegraph)
- `client.py:7971-8012`: a resting create already takes its own path. A 200 response with an order id gets `kind=ambiguous` from `classify_create_order_outcome` (`submit_chain.py:1887-1901`, the residual case). The with-id context is written with `resting=True`. Then `_confirm_resting_order` (`client.py:8449-8522`) polls `GET /v1/order/{id}` for up to `RESTING_CONFIRM_DEADLINE_S=5` s (`submit_chain.py:164-172`). `NEW_VERIFIED` → `_bind_resting_order` → retire `ACCEPTED_RESTING` + OrderAccepted (`client.py:8084-8104`). Any other result → HOLD → the intent stays OPEN until the with-id resolver decides.
- So for a GTD order, an empty-executions 200 is already handled as "accepted, waiting for the confirm GET". Changing the label to ACCEPTED-RESTING at create time would change nothing in how orders run.
- It would also break a binding ruling. `gl1_gl4_order_state_ruling_2026-09-10.md` GL-1 = HOLD (200 + id + no executions stays AMBIGUOUS). Its falsifier 3 ("GET 404 on an id create just returned → HARDEN this hold") happened on 11-01: 6 transient 404s (D-B, PROGRESS.md:66). Rejected: no create-time relabel for any TIF, and IOC stays untouched.
- What actually needs fixing is why a rest stays OPEN after the confirm. There are four hypotheses, and the 11-01 log lines tell them apart:
  - H1 (confirm too slow): the 404 retries use up the 5 s deadline → "deadline reached without a NEW; holding".
  - H2 (echo drift): "not a clean matching NEW; holding". The venue added Order fields on 10-28, so `resting_echo_matches` may be rejecting a good order.
  - H3 (state mapping): "a non-NEW state (filled, partial or terminal); holding". A venue pending state may map outside `_RESTING_CONFIRM_PENDING_STATUSES` = {INITIALIZED, SUBMITTED} (`client.py:1773-1775`).
  - H4 (one-slot serialisation): the confirm does bind, but with K=1 every other rung the maker posts during the up-to-5 s POST+confirm window gets `OPEN_INTENT_WAIT_REASON` (`submit_chain.py:90-92`). In that case the denials are the ladder bursting, not wrong classification. SEL-2 (`reconcile.py:74-75` uses up a slot on a refused post, PROGRESS.md:64) adds to this.
- Churn site: `no_ladder_maker/reconcile.py:65-66` cancels REPLACED whenever `bid_cents` changes for any rung in `live`. Per the docstring (`:49`), `live` includes in-flight rests that are not yet confirmed. So a rest can be replaced before it is ever OrderAccepted (22/29).

## 2 Preconditions and dependencies
- The operator lifts the build pause (§8). Step 1 is read-only and allowed now.
- Not dependent on GAP-1..4 or GAP-6. GAP-4's live-small sequential design needs this gap closed: n only grows through the create path.

## 3 Scope
In scope:
- `src/breezy/adapters/polymarket_us/exec/client.py`: `_confirm_resting_order` and `_RESTING_CONFIRM_PENDING_STATUSES`, only where the evidence points.
- `submit_chain.py`: `RESTING_CONFIRM_DEADLINE_S`/`_POLL_S` (RulePins) and `resting_echo_matches`, again only where the evidence points.
- `src/breezy/strategy/no_ladder_maker/reconcile.py` `plan_actions` and its caller `strategy.py:_decide` (`:535`).

Not in scope:
- `classify_create_order_outcome` and the IOC/ZERO_FILL table (`submit_chain.py:352-358`, `:1866-1885`).
- GL-1, the with-id resolver's GET-based retire, and the latch (`runtime/submit_intent.py`).
- The NO-SEND firewall, the E0-NOSEND log allow-list (`client.py:8055-8057`), and the x1 egress set (no new endpoint: the GET is already used).
- `allow_short`, operator caps, permit/enablement, K (`max_slots`), and the sim twin `maker_stage0_fill_pass.Pass._decide` unless §8-D2 says otherwise.

## 4 Steps
1. **Evidence, read-only.** Sub-agent; `journalctl --user` on the trade-node unit for 10-31 and 11-01; output `docs/evidence/gap5/create_path_census_2026-11-01.md` plus a machine JSON (L-75); about 1 h.
   - Join each `create-order classified kind=ambiguous … body_kind=empty-executions` line by client_order_id to the next of: confirm verdict line, `resting bind`, OrderAccepted, resolver retire (reason + delay in s), REPLACED cancel (delay in s).
   - Also join each `OrderDenied … already OPEN` to the OPEN intent it waited on.
   - Count GET 404/refused lines per create.
   - Values only, no order ids in the repo: hash the ids.
2. **Venue schema check.** Sub-agent; 20 min. Read `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py` (`Order`, `Execution`, `CreateOrderResponse`) and any create-response notes under `docs/evidence/venue/polymarket_us/`. Confirm whether the GTD create blocks up to `maxBlockTime` or returns at once, and which `OrderState` values come before NEW.
3. **Decision against the frozen table in §5** (coordinator). No build without a winning hypothesis.
4. **Fix, one per confirmed hypothesis.** tdd-guide; Grok/Codex if the route probe passes; about 2–4 h each.
   - H1: widen `RESTING_CONFIRM_DEADLINE_S` (RulePin; one pin commit).
   - H2: fix the echo comparison for the observed field.
   - H3: add the observed pre-NEW state to `_RESTING_CONFIRM_PENDING_STATUSES`.
   - H4: the maker posts its ladder one rung at a time: the next post goes out only after the previous intent retires or is denied. It does not re-post on `OPEN_INTENT_WAIT_REASON` inside the same decide pass.
5. **Churn fix** (step 1 must show ≥ 1 REPLACED before OrderAccepted). `plan_actions` gets `unconfirmed: frozenset[str]`. A rung in `unconfirmed` is never cancelled REPLACED (it can still be dropped when it is no longer wanted). The caller supplies it from `RestState`.
6. **Pin re-computation** in its own commit (§7), then the gate, reviews, merge, and relaunch per "activate immediately".

## 5 Acceptance, frozen before step 1 reads any log
- A hypothesis is CONFIRMED if its signature line appears on ≥ 50% of the HOLD creates across the two days. H4 is CONFIRMED if ≥ 50% of the OPEN denials fall inside the in-flight window of a create that later bound NEW within ≤ 6 s.
- KILL the relabel framing outright (already done in §1a).
- If no hypothesis reaches 50%, report UNEXPLAINED and build nothing.
- Post-deploy acceptance on the first full live day:
  - OPEN-gate denials ≤ 10% of posts.
  - OrderAccepted ≥ 90% of creates.
  - Median time-to-REPLACED ≥ the first confirm, with 0 REPLACED before OrderAccepted.
  - 0 change in IOC classification counts.
  - This is a descriptive read, not a strategy look.

## 6 Tests (RED first)
- `tests/unit/test_polymarket_us_resting_confirm_gap5.py`:
  - `test_confirm_binds_new_after_transient_404s_within_deadline` (H1)
  - `test_confirm_accepts_echo_with_extra_venue_order_fields` (H2)
  - `test_confirm_polls_through_observed_pre_new_state` (H3)
  - `test_ioc_empty_executions_still_classifies_ambiguous` (guard; must stay GREEN throughout)
- `tests/strategy/no_ladder_maker/test_reconcile_gap5.py`:
  - `test_unconfirmed_rung_is_not_replaced_on_bid_change`
  - `test_unconfirmed_rung_is_still_cancelled_when_dropped`
  - `test_confirmed_rung_is_replaced_on_bid_change`
  - (H4) `test_ladder_posts_one_rung_per_open_intent`
- The existing `test_polymarket_us_resting_reconciliation.py`, `_resting_robustness.py`, `test_strategy_parity.py`, `test_cage_rule_constants_are_pinned.py` and the CT-1 AMBIGUOUS test must stay unchanged. Only a pin value may move, in its own commit, with a citation.
- Gate: `scripts/ci/run_tests_no_egress.sh` on the primary tree (binding). Basetemp goes inside the tree. Run `lint-imports` from the tree root. Read EXIT before any push.

## 7 Pins, isolation, risks
- Byte pins: re-compute the three byte-pin sites the brief names, plus the x1 exec import set, in ONE commit after the logic commit. Candidates, unverified: the cage-rule constants pin, the aut2.label and aut6.health byte pins (PROGRESS.md:66), and the E0-NOSEND scanned-body pin for `_submit_order`/`_confirm_resting_order`. The implementer lists them via codegraph first. New test files must not import exec in a way that breaks the x1 set-equality check (memory: focused gates miss the exec import pin).
- Risk HIGH: widening the deadline lengthens the K=1 in-flight window. That makes H4 worse unless the H4 fix ships together with it.
- Risk MED: a live-only `unconfirmed` guard makes the live maker differ from the sim twin and breaks the parity test (§8-D2).
- Risk MED: an echo relaxation could bind an order that is not ours. The comparison may only add tolerance for new fields. Every field we sent (slug, leg, action, price, qty, tif, goodTillTime) must still match exactly (L-12, widen never relax).
- Security review is mandatory: this is the exec path, the confirm GET runs against a venue account shared with manual trading, and the log lines must stay value-free with no credentials.

## 8 Operator decisions
- D1: lift the build pause for GAP-5 steps 4–6. Step 1–2 are read-only and need no decision.
- D2: whether to apply the churn guard to the sim twin as well. If yes, maker backtests change. If no, the parity test gets a documented carve-out, which needs reviewer approval.
- No caps or size are proposed.

## 9 Citations not verified
- The `no_ladder_maker/strategy.py:28-30` cancel/replace trigger (not read).
- With-id resolver cadence and retire delay (not traced).
- The exact three byte-pin sites and the x1 set test name.
- `CreateOrderResponse` schema fields and GTD `maxBlockTime` behaviour.
- The "34/34 creates" figure (PROGRESS.md:69) vs "23 + 18" (P4_LIVE_READ_2026-11-01.md:21): which is right is not resolved.

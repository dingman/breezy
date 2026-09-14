# NO-side execution — slice S5 (Rev 1, 2026-09-14)

Parent plan: `docs/plans/NO_SIDE_EDGE_2026-09-14.md` (Rev 3). Shipped before this slice (live 09-14 16:05Z): S1, S2 (+YES-only
composition filter), S2b, S3, S3b (shadow: `NO_SIDE_SHADOW_ONLY = True`), S4, S6a; S6b on the base branch (c564602, adjudicated
NULL_CORRECT). This slice lifts barrier X3 and turns shadow NO takes into real BUY orders on the NO leg.

## §1 Preconditions / exit criteria (all three before S5 merges)

**(a) NO-side preview capture.** `docs/evidence/venue/polymarket_us/capture_no_side_preview.py.draft` is venue-touching by C4/C5
(`test_polymarket_us_readonly_guard.py:47-63`) and carries `POST` (V1), `/v1/order/preview` (V2) and `.post` (V3). Census edits,
additive, one commit: (1) `git mv` the draft to `scripts/analysis/capture_no_side_preview.py` (not `scripts/venue/`, keeping it out
of the venue-smoke surface); (2) add the exact path to `B4_EXEMPT_PATHS` (`test_polymarket_us_readonly_guard.py:266-271`, 2 → 3);
`CAGE_EXEMPTIONS` (`test_cage_rule_constants_are_pinned.py:882`) is derived from it, so its length pin moves 3 → 4 in the same
commit, and any `RulePin` labelled for it moves its expected/widened/narrowed; (3) pin the script's restated `ORDER_BODY_KEYS`
equal to `submit_chain.ORDER_BODY_KEYS` (`submit_chain.py:78-91`).
RED: `test_the_no_preview_script_is_exempt_and_nothing_else_is`; `test_the_capture_script_body_keys_equal_the_live_order_body_keys`;
`test_the_capture_script_is_the_only_new_venue_write_path`.
Acceptance: 2xx; response `order.outcomeSide == OUTCOME_SIDE_NO` (not remapped); previewed price is the NO price; the paired
`GET /v1/markets/{slug}/book` shows whether NO is a separate book or exactly `1 − YES_bid`. A separate NO book WITHDRAWS S2's
inversion and halts S5 (parent §5 item 5, N2-9).

**(b) X3 ruling signed off.** `docs/evidence/RULING_x3_no_outcome_token_2026-09-14.md` §7 sign-off block is empty; a security review
signs the exact diff of §2.

**(c) S6b cited.** `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` carries the c564602 numbers with both caveats; the S5
commit body cites it by sha.

## §2 The X3 commit (ONE commit, parent R3-3)

- `BANNED_EXEC_DIRECTION_TOKENS` (`test_execution_egress_firewall_guard.py:252`): `{"_SHORT","OUTCOME_SIDE_NO"}` →
  `{"_SHORT","BUY_SHORT","SELL_"}`.
- `RulePin` at `test_cage_rule_constants_are_pinned.py:862-869`: `expected={"_SHORT","BUY_SHORT","SELL_"}`,
  `widened={"_SHORT","BUY_SHORT","SELL_","_LAY"}`, `narrowed={"_SHORT","BUY_SHORT"}` (drops a token the NEW set introduces);
  `why` cites the ruling path. Label unchanged (the label-set test at :930 forbids a second pin).
- Module docstring `submit_chain.py:5-6` replaced in the same commit.
- **Pre-flight (blocker if it fires):** the scan is raw text (`:1295`, `token in source`). Run `scan_exec_direction_vocabulary()`
  with the new set BEFORE writing code: `"SELL_"` must not already appear under `exec/` (`_ORDER_SIDES` in `reports.py` maps
  `ORDER_SIDE_SELL`, safe; any `ORDER_SIDE_SELL_*`/`SELL_SHORT` literal is not). If it fires, the ruling's token set is wrong.
- `_is_one` widening (parent R3-4, guard test :1261-1275): accept an `ast.Name` bound at module level to `Decimal(1)`/`1`/
  `Decimal("1")`, resolved from the same tree, never a name allowlist.
RED: `test_the_exec_direction_scan_refuses_a_planted_ONE_minus_price` (planted in source text, not on disk);
`..._refuses_a_planted_BUY_SHORT`; `..._refuses_a_planted_SELL_underscore`; `..._admits_OUTCOME_SIDE_NO_in_the_order_body`;
`test_the_literal_one_minus_form_still_trips_after_the_widening`.

## §3 Submit chain

`_outcome_token` (`submit_chain.py:244-254`) becomes leg-keyed: `leg_of(instrument.id)` → `"yes"` → `_OUTCOME_SIDE_YES`,
`"no"` → `_OUTCOME_SIDE_NO`, else `None`. **Key on `leg_of(instrument_id)`, never on the outcome string** (free-text venue prose,
`parsing.py:1211-1221`; the current `casefold()=="yes"` fold is exactly the parse the parent forbids). The instrument id is the
identity every money surface keys on: `intent_fingerprint` hashes it (:229), `_note_ambiguous_open` persists it (`client.py:2981`),
the resolver re-resolves from it (`client.py:1564`); `leg_of` is total and pure, so create and GET paths derive the same leg from
the same datum. `info["leg"]` is a cross-check that must agree — disagreement is a refusal, never a fallback.
`unmappable_order_reason` (:257-294): SELL refusal at :268-269 byte-unchanged; only the :292-293 message changes.
`build_order_body` (:297-318): key set unchanged, only the `outcomeSide` value varies. `intent_fingerprint` unchanged.
RED: `test_a_no_leg_instrument_maps_to_outcome_side_no`; `test_the_order_body_key_set_is_identical_on_both_legs`;
`test_a_sell_on_the_no_leg_is_still_unmappable`; `test_an_instrument_whose_info_leg_contradicts_its_id_is_refused`;
`test_the_outcome_string_is_never_read_for_the_token`.

## §4 Fill/GET leg attribution (parent R3-2)

Mechanism exists: `AmbiguousResolverContext.instrument_id` written at `client.py:2978-2990`, read at `client.py:1564`. No new
durable field. RED: `test_a_no_order_persists_the_no_instrument_id_in_its_resolver_context`;
`test_a_resolved_fill_books_to_the_context_instrument_not_a_slug_lookup` (both legs share `raw_symbol`, so
`_assert_market_matches` (`reports.py:721-736`) passes for either leg — this test is the only thing distinguishing them);
`test_the_create_path_books_to_the_orders_own_instrument`.
Drift (L-37, declare-then-refuse): once the capture shows `marketMetadata.outcome` on a NO execution, declare it and cross-check
against `instrument.outcome`, refusing on contradiction with the full names-only key tree (`reports.py:1149-1154`). Until captured
it stays undeclared and refused — no pre-emptive allowlisting.
Spend: `_seed_spend_from_durable_fills` (`client.py:1276-1344`) walks per instrument id over `list_all()`, so a NO fill sums into
the one ledger provided the NO leg is in the provider list (it is, since S2). RED: `test_a_no_leg_fill_seeds_the_ledger_at_its_premium`.

## §5 Flip `NO_SIDE_SHADOW_ONLY` → False (`continuous_strategy.py:113`)

On a NO `Take` surviving the four S4 gates (`_evaluate_no_side_shadow`): mirror the YES arm block (:1024-1040) keyed on `no_iid` —
record the decision ask by station-day, `set_inflight(..., key_instrument_id=no_iid)`, `record_attempt` + `rearm:` line, then
`_maybe_submit(no_iid, no_decision)` (already builds `OrderSide.BUY`/IOC/post_only=False, :1598-1605, no side branch). Clear
IN_FLIGHT when unarmed. Day-budget stays a WAIT (the NO refuse at :1168-1170 becomes the existing diagnostic path, not a refusal);
the daily budget and the per-order cap (`order_notional_usd = price × qty`) bind unchanged — on the NO leg that product is the premium.
Two joins must learn NO ids: `_run_never_arm_walk` iterates `self._facts` (:531, YES legs only) and must also decide the sibling NO
id (flat/LONG/UNKNOWN) before arming it; `_join_fill_to_station_day`/`on_order_filled` (:1447) must resolve a NO id via
`base_slug_of`, or a real NO fill lands in `_unjoinable_fill_instruments` and halts the instrument.
RED: `test_a_no_take_arms_consumes_and_submits_on_the_no_instrument`; `test_the_never_arm_walk_decides_both_legs`;
`test_a_no_fill_joins_to_its_station_day`; `test_the_day_budget_is_a_wait_not_a_refusal_on_the_no_leg`;
`test_flipping_the_flag_changes_no_yes_path_behaviour` (all existing decision tests unedited).
**PREREG residual.** "Residual" is declared today, not coded (resolver fills are residual by ruling). The FIRST live NO create-path
order carries the same marking until its request/response shape is captured, implemented as data: `TrialDayRecord.reason` gets a
distinct value the tally excludes, RED `test_the_first_no_create_path_trial_is_marked_residual`. PREREG-visible: named in the
amendment before coding.

## §6 Backtest/replay parity (S7 minimum)

`ContinuousRungHoldBacktestStrategy` (:389-403) must submit a NO BUY through `BacktestOrderGuard` without tripping
`_refuse_naked_short` (`backtest_order_guard.py:234-282`) — the NO instrument must be in cache and portfolio so `_net_long` is
per leg. RED: `test_a_backtest_no_buy_passes_the_order_guard`; `test_the_guard_message_names_the_no_leg_instrument` (drop the
stale "price inversion" hint at :259-261). Paper-replay driver: replay a NO take off the YES Depth10 tape and reproduce the live
decision byte-for-byte — the only test exercising the `^` composite id through `catalog.quote_ticks` on the execution path.

## §7 Risks / NOT changed

Highest: the raw-text `"SELL_"` ban colliding with existing exec source (§2 pre-flight). Second: the NO leg absent from
`list_all()` silently under-seeding spend (§4). Third: `_assert_market_matches` cannot tell the legs apart — leg attribution
rests entirely on the context/order instrument id.
NOT changed: Nautilus; `allow_short=False`; NO stays a BUY; the NO-SEND firewall, its allowlist and the E0 barrier; both operator
caps; the account-wide submit-intent latch; `ORDER_BODY_KEYS`; `CORPUS_SHA256`; θ=0.06; the `float()` ban under `exec/`; B6/B7;
the `1 − x` AST control (widened, never removed).

## §8 Operator-only

Whether the daily budget and the per-order cap stay as-is once NO roughly doubles the eligible surface, or a new ceiling is supplied.

---

## Rev 2 dispositions (2026-09-14, after adversarial round 1: architect / market-math / safety — all REVISE)

- **E2-1 (CRITICAL, architect; merged with market-math CRITICAL "undecidable first order").** Venue positions are mapped by
  slug onto the YES instrument only: `_find_instrument` (`client.py:2436-2446`) uses the YES-only bijection, `_map_position`
  (`:2354-2434`) emits one `PositionStatusReport` per slug, and a non-LONG sign is refused at `:2415-2420`. No code path can ever
  attribute a NO position to the NO instrument, so the never-arm walk has no evidence to decide the NO side, and a NO position
  cannot be captured without a NO fill. **Disposition: accepted, restructured as a bounded first-order protocol.**
  (i) New durable key `exec/polymarket_us/no_side/first_live_order` written atomically under the existing submit flock at the
  moment the first NO create-path order is submitted (payload: instrument id, venue order id when known, ts). While that key
  exists and `exec/polymarket_us/no_side/position_shape_captured` is absent, the strategy REFUSES to arm any further NO take
  account-wide (closed-set reason `no_side_first_order_pending`), so exposure is bounded to one NO premium. This makes "first"
  decidable across restarts and concurrent stations (RED: two concurrent NO takes → exactly one submits, the other refused).
  (ii) Exit criterion §1(d): after that first fill, capture the venue position payload for the slug (via the existing position
  GET path, under the permit) and the SDK snapshot's position type; rule whether the venue reports per-outcome positions (then
  `_map_position` splits by the outcome field → `no_leg_instrument_id(slug)`) or nets across outcomes on one slug (then a
  ruling defines the mapping of a non-LONG-signed slug position to a LONG on the NO leg). Only that ruling, recorded as the
  `position_shape_captured` key by a CLI (never by the node), re-enables NO arming. Until then the never-arm walk treats a NO id
  as UNKNOWN for arming NO only — it must never block the YES sibling (RED test).
  (iii) The residual marking (market-math CRITICAL 1): "residual" is derived from the durable first-order key by
  `score_live_trials._admit_fill`/`FillExclusion` reading that key (the real read path), not from `TrialDayRecord.reason`
  alone; RED test proves the tally drops that trial from n and the looks. The marking ENDS at the `position_shape_captured`
  ruling; trials after it are admissible.
- **E2-2 (HIGH, market-math).** The amendment's "residual classification unchanged" contradicts this. **Accepted**: the
  amendment gains a clause registering the first-NO-order residual trigger and its durable end condition BEFORE S5 code.
- **E2-3 (HIGH, market-math).** Day-budget WAIT needs a submit-suppression test. **Accepted**: RED
  `test_no_order_is_submitted_on_the_no_leg_after_the_day_stop` asserts `_maybe_submit` is never called post-exhaustion.
- **E2-4 (MEDIUM, market-math ×3).** Accepted as RED tests: `test_a_partial_no_fill_is_excluded_not_tallied_as_qty_one`
  (existing qty≠1 exclusion is leg-agnostic — prove it); `test_a_no_order_prices_itself_at_the_no_ask_not_the_yes_ask`;
  §1(a) acceptance adds the venue fee field on the NO preview matching θ·p·(1−p) on the NO price.
- **E2-5 (MEDIUM, architect).** X3-alone safety is asserted. **Accepted**: the §2 commit carries
  `test_x3_alone_without_leg_keyed_submit_chain_never_emits_no` (with §3 not yet applied, `_outcome_token` on a NO id returns
  None and the order is unmappable); §2 and §3 stay separate commits, §2 gated by that test.
- **E2-6 (MEDIUM, architect).** `_candidate_instrument_ids()` (:610-619) is NO-aware via the cache while the arming loop is
  not — stated explicitly; the arming loop gains the NO sibling only under E2-1's protocol. §6's parity claim is scoped to the
  DECISION path; position reconciliation parity is out of scope until E2-1(ii).
- **E2-7 (MEDIUM, safety).** `test_the_cage_grants_exactly_three_exemptions` (`test_cage_rule_constants_are_pinned.py:1004`)
  must be RENAMED to `..._four_exemptions` with its docstring attributing the fourth slot to the capture script — a non-additive
  edit inside §1(a); listed explicitly so the sign-off covers it.
- **E2-8 (INFO→rule, safety).** The raw-text scan is re-run at COMMIT time, not plan time; `test_an_instrument_whose_info_leg_
  contradicts_its_id_is_refused` asserts refusal in BOTH directions (id NO/info YES and id YES/info NO). Safety confirmed the
  X3 widening is the minimal correct change (injection from outside exec/ would split the chokepoint) and that the residual
  marking cannot gate spend (ledger seed walks fills by instrument id).
- **Confirmed clean:** §2 pre-flight scan has zero `SELL_`/`BUY_SHORT` hits under exec/ at b81d696; `leg_of` is total and
  defaults to YES; the draft script reaches only preview and book GET, imports nothing under exec/.

### Exit criteria after Rev 2
§1(a) preview + book + fee capture; §1(b) X3 sign-off; §1(c) amendment cites S6b AND registers the first-NO-order residual
trigger (E2-2); §1(d) the first-order protocol keys and CLI exist with RED tests BEFORE the flag flips; §1(e) position-shape
ruling is a post-first-fill gate that re-enables NO arming.

---

## Rev 3 dispositions (2026-09-14, after round 2 — all three REVISE)

- **E3-1 (CRITICAL, architect).** After a NO fill the venue position lands on the YES id (`_map_position`/`_find_instrument`,
  `client.py:2354-2446`), and `_run_never_arm_walk` (`continuous_strategy.py:477-530`) sees a LONG on a YES id with no YES fill
  record — its fail-closed case — and halts YES on that station. E2-1's "UNKNOWN on the NO id" answered the wrong failure.
  **Disposition:** the walk, on finding LONG-on-YES-id with no YES fill, consults the sibling NO id's fill index
  (`iter_fill_records([sibling_instrument_id(yes_id)])`); a NO fill for that slug accounts for the LONG (sibling exclusion
  forbids YES+NO on one instrument-day, so the attribution is unambiguous) — log `never_arm: accounted_by_no_leg` and continue
  arming YES. No fill on either leg → halt as today. RED: (a) NO fill + slug LONG → YES arms; (b) LONG with no fill either leg
  → halt; (c) YES fill + LONG → unchanged. NO arming itself stays gated by E2-1 until the position-shape ruling.
- **E3-2 (HIGH, architect).** Gate placement for `no_side_first_order_pending`: checked in `_evaluate_no_side_shadow`
  IMMEDIATELY after `is_intent_open` and BEFORE `set_inflight`/`record_attempt`/decision-ask recording, mirroring the
  `is_intent_open` pre-filter precedent (`trial_day_latch.py:514-533`); plus a synchronous re-check inside `_submit_order`'s
  no-await prefix (SAFETY C1, `client.py:3011-3024`) as defence in depth. RED: a second concurrent NO take never calls
  `set_inflight`.
- **E3-3 (HIGH, market-math).** `_admit_fill` (`score_live_trials.py:379`) is pure; the read happens in
  `read_filled_trials_state_db` (opens the live exec DB read-only under `node_store_path_check`), which reads both keys and threads
  `no_side_residual_by_trial_id` into `_admit_fill` as a new keyword exactly like `fee_reconciled_by_trial_id`.
  `FillExclusionReason` gains `no_side_first_order_residual`, added to `RESIDUAL_EXCLUSION_REASONS` (:307-328) — additive
  widening. RED through `read_filled_trials_state_db` on a temp state DB, asserting n and the look index exclude the trial.
- **E3-4 (market-math).** `test_a_no_order_prices_itself_at_the_no_ask_not_the_yes_ask` binds to
  `tick_eval.evaluate_both_sides` → `_maybe_submit`: the submitted order's price equals the NO decision's price (`1 − YES_bid`).
- **E3-5 (HIGH, market-math).** During the pending window the hunt stays observable: `_evaluate_no_side_shadow` keeps
  evaluating and logs `no_take_shadow: … pending=1` for takes that would have submitted; only submission is refused. RED test.
- **E3-6 (safety 1/3/6).** Reason `no_side_first_order_pending` joins `LATCH_GATE_REFUSAL_REASONS` (trial_day_latch.py, the
  closed set where the other NO gates live), additive with its pin test; NOT `decision.REFUSAL_REASONS`. Key constants
  `NO_SIDE_FIRST_LIVE_ORDER_KEY = "exec/polymarket_us/no_side/first_live_order"` and
  `NO_SIDE_POSITION_SHAPE_CAPTURED_KEY = "exec/polymarket_us/no_side/position_shape_captured"` live in a new I/O-free module
  `exec/no_side_keys.py` (importable by client, strategy via the existing injection pattern, and the CLI; lint-imports must stay
  green). No key-prefix census exists in the repo (safety verified) — the constants are pinned by E3-7's structural test.
  The CLI mirrors `clear_submit_intent_cli.py` (implementer locates its module and console-script entry in pyproject):
  `breezy-mark-no-side-position-captured`, writing only the captured key with the ruling path and sha as payload, with its own
  test file and census entry if the CLI census requires one.
- **E3-7 (safety 2).** Structural test: an AST scan over `src/` and `scripts/` asserting `NO_SIDE_POSITION_SHAPE_CAPTURED_KEY`
  appears as a `.set(`/write target ONLY in the CLI module (mirroring B4's write-egress scan shape); the node can read it, never
  write it.
- **E3-8 (safety 4).** Boot reconcile rule: in `_connect` after `_seed_spend_from_durable_fills`, any NO-leg
  `DurableFillRecord` found with `NO_SIDE_FIRST_LIVE_ORDER_KEY` absent → write the key (fail closed toward "pending") before the
  resolver runs. RED test on a temp store.
- **Closed:** E2-5 implementable (`_outcome_token` returns None for a NO id today); E2-7 exact; `_consume_trial_from_fill_record`
  keys the NO instrument-day only; the crash-race is serialised by the C1 synchronous prefix plus E3-8.

### Exit criteria after Rev 3 (unchanged list; E3-1/E3-2/E3-8 are in-slice RED items)
§1(a)–(e) as after Rev 2; the amendment §8 (first-NO-order residual protocol) is written.

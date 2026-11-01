# GAP-5 CREATE-PATH-MECHANICS — plan r1
Status: r1 — for re-review by architect + security-reviewer. Read-only until the operator lifts the 11-01 19:55Z build pause (PROGRESS.md:69).

## 0 Finding → resolution
| # | Sev | Resolution (evidence) |
|---|---|---|
| A-1 | HIGH | H5 added (resolver lag). Verified: the resolver binds a resting context with NO age floor (`client.py:3739-3754`). It serves ONE OPEN slot per pass (`next_open_for_resolution`, `:3357`). The base interval is 5 s (`_RESOLVER_POLL_INTERVAL_SECS`, `:707`). Backoff doubles on consecutive failures up to 300 s (`:711`, `:3290-3298`). So N OPEN slots plus repeated 404s can hold a rest OPEN for minutes. H5 is now in the step-1 join and in §5. |
| A-2 | HIGH | Non-hypothesis HOLD exits are separate signatures, X1–X3: GET timeout (`:8494`), allowlist fail (`:8468`), bind raised (`:8099`). They are counted apart and never credited to H1. |
| A-3 | MED | Accepted. H1 = one or more "GET refused (HTTP status 404); retrying" lines (`:8497-8499`) followed by "deadline reached" (`:8520`). Extend `tests/unit/test_polymarket_us_resting_order_get_404.py` (exists) instead of adding a new H1 test. |
| A-4 | MED | Accepted. The pending set applies to the Nautilus `OrderStatus` after `parse_order_status_report` (`:8485-8512`). H3 = an observed raw venue state that maps to a non-pending, non-ACCEPTED status. See §4 H3 for the layer rule. |
| A-5 | MED | Accepted. An OPEN-gate denial is a WAIT (`submit_chain.py:85-92`). §5 now accepts on wanted rungs eventually sent and on time-to-OrderAccepted. Denial share is reported, not gated. |
| A-6 | MED | Accepted. §8-D2 now covers both the churn guard and H4 one-rung posting. |
| A-7 | MED | Verified. `strategy.py:552-559` passes `live = {all ladder.rests}`. A rest is `RestState.SUBMITTED` at post (`:410`) and flips to ACCEPTED only on OrderAccepted (`:877-878`). Unconfirmed rests are therefore in `live`. Step 5 still requires ≥1 REPLACED-before-OrderAccepted in the census. |
| A-8 | LOW | Accepted. Pin sites named in §7 (verified paths and lines). |
| S-1 | MED | Accepted. Added to the must-match list: `manualOrderIndicator == AUTOMATIC` (`submit_chain.py:818`). `:807-819` is untouchable. RED-first test: MANUAL or absent stays False. |
| S-2 | MED | Verified and accepted. `resting_echo_matches` reads only named keys (`:803-834`), so extra fields cannot cause False. H2 is redefined as "which sub-clause fails" (value-free field name from step 1). Any "ignore this clause" fix is forbidden. Note: the SDK `Order` TypedDict (`types/orders.py:70-92`) has no `manualOrderIndicator`. If the census shows that clause failing, the outcome is a venue question and an operator report, never a relaxation. |
| S-3 | MED | Accepted. Per-create ordinals (c001…) with no id-to-ordinal map in the repo. No venue ids, no raw journal lines, `position_id=` stripped. A regex scan (ids, `Bearer`, key material, account numbers) must pass before commit. |
| S-4 | MED | Accepted. The `unconfirmed` guard is bounded by `posted_ns` + `UNCONFIRMED_GUARD_S` (new RulePin), or ends at GTD expiry, whichever comes first. Added `test_unconfirmed_guard_expires`. |
| S-5 | MED | Accepted. `RESTING_CONFIRM_DEADLINE_S` ceiling ≤ 15 s. The per-read budget is derived (`client.py:8475`), so it moves with the deadline. `_MAX_BLOCK_TIME="5"` (`submit_chain.py:380`) is unchanged. A watchdog/heartbeat check is required before the pin commit. H1 and H4 ship in the same commit set. |
| S-6 | LOW | Accepted. `_confirm_resting_order` is scanned; any H3 change uses plain comparisons and adds no callee. The callee lists are named in §7 before step 4. |
| S-7 | LOW | Accepted. Only census-observed pre-ACCEPTED states may be added. Never FILLED or terminal. `ACCEPTED && filled_qty == 0` is kept (`:8505-8506`). |
| S-8 | LOW | Accepted. The census sets the denominator before any threshold is applied. P4 read `:21` gives 23 (11-01, by that hour) + 18 (10-31). The PROGRESS "34/34" is a later count, so the census decides. |

## 1 Objective
Stop a resting maker order from blocking every other order and from being replaced before it can rest, so a fill can happen and be scored. This gap creates no edge; GAP-1/3/4 own that. It removes a mechanical cap on fills. On 11-01, 46 posts got "submit intent is already OPEN" (P4_LIVE_READ_2026-11-01.md:21).

## 1a Corrected framing (verified)
- A 200 + id + empty executions is already classified `kind=ambiguous` with `resting=True` (`client.py:7971-8012`, `submit_chain.py:1887-1901`). The bounded confirm GET (`_confirm_resting_order`, `client.py:8449-8522`; 5 s, 0.5 s poll) then binds on a clean NEW. Otherwise it HOLDs, and the with-id resolver can still bind later (`client.py:3739-3754`).
- A create-time relabel is rejected for every TIF. It would change nothing (the rest path already exists) and would breach GL-1 HOLD (`gl1_gl4_order_state_ruling_2026-09-10.md:34-35`; falsifier 3 fired on 11-01 with 6 transient 404s). IOC is untouched.
- Hypotheses for "OPEN for minutes":
  - H1 404s use up the confirm deadline.
  - H2 an echo sub-clause fails.
  - H3 a pre-ACCEPTED venue state maps outside {INITIALIZED, SUBMITTED}.
  - H4 K=1 serialisation of the ladder burst.
  - H5 resolver lag after a HOLD (round-robin with exponential backoff).
  - Non-hypothesis exits X1–X3.
- Churn: `reconcile.py:65-66` cancels REPLACED for any rung in `live`, and `live` includes SUBMITTED rests (`strategy.py:554`).

## 2 Preconditions and dependencies
- The operator lifts the build pause for steps 4–6 (§8-D1). Steps 1–2 are read-only and allowed now.
- Independent of GAP-1..4 and GAP-6. GAP-4's live-small design needs this closed, because n grows only through the create path.

## 3 Scope
In scope, each item only where the census points:
- `client.py`: `_confirm_resting_order`, `_RESTING_CONFIRM_PENDING_STATUSES` (`:1773-1775`).
- `submit_chain.py`: `RESTING_CONFIRM_DEADLINE_S`/`_POLL_S` (`:164-165`, RulePins).
- `client.py` with-id resolver: H5 only, and only via the existing `_resolver_poll_interval_secs` cadence or slot-serving order. No new callee.
- `no_ladder_maker/reconcile.py::plan_actions` and its caller `strategy.py::_decide` (`:535-563`).

Not in scope:
- `classify_create_order_outcome`, the IOC/ZERO_FILL table, GL-1, the latch (`runtime/submit_intent.py`).
- `resting_echo_matches:807-819` (S-1).
- `parse_order_status_report` mapping (see H3 rule).
- NO-SEND firewall, E0-NOSEND allow-list, x1 egress set (no new endpoint).
- `allow_short`, operator caps, permit/enablement, K (`max_slots`).
- The sim twin, unless D2 says so.

## 4 Steps
1. **Census, read-only.** Sub-agent, ~1 h. Source: `journalctl --user` for the trade-node unit, 10-31 and 11-01.
   - Output: `docs/evidence/gap5/create_path_census_2026-11-01.json` (machine, L-75), with a `.md` render.
   - Per create ordinal (cNNN), join the `kind=ambiguous … body_kind=empty-executions` line to:
     - its confirm-exit signature (NEW / H1 / H2 / H3 / X1 / X2 / X3);
     - count of 404/refused lines;
     - for HOLDs, the resolver bind/retire and its delay in s, plus resolver backoff lines in between (H5);
     - REPLACED cancel and its delay;
     - OrderAccepted delay.
   - Join each OPEN-gate WAIT to the OPEN ordinal it waited on.
   - Per wanted rung: sent eventually (y/n) and time to send.
   - Hygiene (S-3): ordinals only, no id map, `position_id=` stripped, no raw lines. The regex scan must pass.
   - The census fixes the denominator (S-8).
2. **Venue schema check.** Sub-agent, 20 min. Source: `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py` plus create-response notes.
   - The `OrderState` values that come before ACCEPTED.
   - Whether `manualOrderIndicator` is documented.
   - Where `parse_order_status_report` maps venue state to `OrderStatus` (cite the file and line).
3. **Decision against §5** (coordinator). No build without a CONFIRMED hypothesis.
4. **Fix, one per confirmed hypothesis.** tdd-guide; Grok/Codex if the route probe passes; 2–4 h each.
   - H1: widen `RESTING_CONFIRM_DEADLINE_S`, ≤ 15 s, after the watchdog check. Ships in the same commit set as the H4 fix.
   - H2: fix only the failing sub-clause where our parse is wrong (e.g. the `report` side). Never drop a clause. Indicator failure → stop and report.
   - H3: if the observed state maps to a pending-type status, add that status to the set (module constant, outside the scanned body). If it maps to a terminal or REJECTED status, that is a mapping bug outside scope → stop and report.
   - H4: post one rung per decide pass while an intent is OPEN. No re-post inside the same pass after a WAIT.
   - H5: change the existing slot-serving order or cadence so that resting contexts are served first (plain comparisons only). No new callee in `_resolve_ambiguous_intents`.
5. **Churn fix.** Precondition: the census shows ≥ 1 REPLACED before OrderAccepted.
   - `plan_actions` gets `unconfirmed: frozenset[str]`. The caller passes rests with `state is SUBMITTED` and `now < posted_ns + UNCONFIRMED_GUARD_S`.
   - An unconfirmed rung is never REPLACED. It is still cancelled when no longer wanted.
   - `UNCONFIRMED_GUARD_S` = census p95 of create→OrderAccepted, capped at 60 s. The value is frozen in the pin commit with that citation.
6. **Pins, gate, merge.** Pin re-computation in its own commit (§7). Then the gate, the architect + security reviews, merge, and relaunch per "activate immediately".

## 5 Acceptance, frozen before step 1 reads any log
- Denominator = census HOLD creates (10-31 + 11-01).
- H1/H2/H3/X CONFIRMED if their exit signature is on ≥ 50% of HOLDs.
- H5 CONFIRMED if ≥ 50% of HOLDs that later bound took > 30 s from HOLD to bind.
- H4 CONFIRMED if ≥ 50% of WAITs fall inside the in-flight window of a create that bound NEW in ≤ 6 s.
- If X1–X3 dominate, or nothing reaches 50%: UNEXPLAINED, build nothing.
- Post-deploy acceptance, first full live day (descriptive read, not a strategy look):
  - ≥ 90% of wanted rungs eventually sent.
  - Median create→OrderAccepted ≤ 15 s.
  - OrderAccepted ≥ 90% of creates.
  - 0 REPLACED before OrderAccepted inside the guard.
  - 0 change in IOC classification counts.
  - WAIT share reported, not gated.

## 6 Tests (RED first)
- `tests/unit/test_polymarket_us_resting_order_get_404.py`, extended: `test_confirm_binds_new_after_transient_404s_within_deadline` (H1).
- `tests/unit/test_polymarket_us_resting_confirm_gap5.py`:
  - `test_echo_failing_subclause_<name>_is_fixed` (H2; named from census)
  - `test_manual_or_absent_indicator_stays_false` (S-1)
  - `test_confirm_polls_through_observed_pre_accepted_state` (H3)
  - `test_filled_or_terminal_never_pending` (S-7)
  - `test_resolver_serves_resting_context_first` (H5)
  - `test_ioc_empty_executions_still_classifies_ambiguous` (guard, GREEN throughout)
- `tests/strategy/no_ladder_maker/test_reconcile_gap5.py`:
  - `test_unconfirmed_rung_is_not_replaced_on_bid_change`
  - `test_unconfirmed_rung_is_still_cancelled_when_dropped`
  - `test_confirmed_rung_is_replaced_on_bid_change`
  - `test_unconfirmed_guard_expires` (S-4)
  - `test_ladder_posts_one_rung_per_open_intent` (H4)
- New test files must not import the exec package except where X1 allows it (memory: focused gates miss the exec import pin).
- Unchanged: `test_polymarket_us_resting_reconciliation.py`, `_resting_robustness.py`, `test_strategy_parity.py` (unless D2 carve-out), the CT-1 AMBIGUOUS test, the firewall tests. Only pin values move, in their own commit, with citations.
- Gate: `scripts/ci/run_tests_no_egress.sh` on the primary tree (binding). Basetemp inside the tree. `lint-imports` from the tree root. Read EXIT before any push.

## 7 Pins, isolation, risks
- Pin sites (verified):
  - `tests/unit/test_cage_rule_constants_are_pinned.py:1016, :1272` (DEADLINE_S); `:356/:593/:703` (`_confirm_resting_order` refs).
  - `tests/unit/test_resting_path_firewall_delta.py:100` `EXEC_RESTING_CONFIRM_PERMITTED_CALLEES` (`:42` caller map).
  - `tests/unit/test_execution_egress_firewall_guard.py:1965` `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`, `:2188` `EXEC_RESOLVER_PERMITTED_CALLEES` (H5 must keep a zero delta).
  - X1: `tests/contract/test_us_source_ingest_egress_guard.py:685`.
  - `UNCONFIRMED_GUARD_S` is a new RulePin; it gets its pin row in the same pin commit.
- Risk HIGH: a longer deadline widens the K=1 window. Mitigation: H1 and H4 ship together, under the ≤ 15 s ceiling.
- Risk MED: a stale-priced unconfirmed rest. Mitigation: bounded guard (S-4).
- Risk MED: binding a foreign order. Mitigation: `:807-819` untouched; S-1 test.
- Risk MED: live/sim divergence (D2).
- Security review is mandatory: exec path, shared manual-trading account, value-free logs, no credentials.

## 8 Operator decisions
- D1: lift the build pause for GAP-5 steps 4–6.
- D2: apply the churn guard AND H4 one-rung posting to the sim twin `maker_stage0_fill_pass.Pass._decide`? Yes → maker backtests change. No → the parity test gets a documented carve-out, approved by a reviewer.
- No caps or size are proposed.

## 9 Citations
Verified (r1):
- `client.py:707, :711, :1773-1775, :3290-3298, :3357, :3739-3754, :8449-8522, :8475, :8494, :8497-8499, :8520, :8524-8542`
- `submit_chain.py:164-167, :380, :782-843`
- `strategy.py:410, :552-559, :877-878`
- `reconcile.py:49, :60-67`
- `ladder_state.py:47-67`
- SDK `Order` TypedDict `:70-92`
- the four pin-test paths in §7
- P4 read `:21`

Not verified:
- `client.py:8099` "resting bind raised" (reviewer-cited).
- `submit_chain.py:85-92` WAIT semantics (reviewer-cited).
- Location of the venue→`OrderStatus` mapping in `parse_order_status_report`.
- The supervisor watchdog/heartbeat interval (needed for the S-5 ceiling check).
- Whether X1 at `:685` is set-equality or superset (the test name says superset).

---
Still-unverified citations:
- `client.py:8099` resting-bind-raised HOLD exit.
- `submit_chain.py:85-92` OPEN_INTENT_WAIT_REASON = no permit/latch/refusal.
- `parse_order_status_report` venue-state mapping file:line.
- Supervisor heartbeat/watchdog interval vs a ≤ 15 s confirm deadline.
- X1 pin semantics (`test_exec_import_pin_x1_is_superset_of_recorded_baseline`) vs the memory's "set-equality".

# FU-1d plan: routing NO-leg marks from the YES sibling book, plus an explicit NO-leg exit gate

## Acceptance Criteria
- AC1: every YES `OrderBookDepth10` frame is evaluated first for the YES position, exactly as today. The same frame then goes to the sibling NO position, which is evaluated with `leg="NO"` through the unchanged `walk_exit_vwap`. That position gets `mark_source="depth_walk"` and `mark_vwap = 1 − walked YES ask VWAP`.
- AC2: a NO position that exists in the cache but was never registered (for example after a restart) is registered lazily from its YES sibling's frame with `entry_context="reconciled"`. This closes the MED residual at FU-1 r2:43.
- AC3: `decide_exit` refuses any NO-leg evidence with the new reason `no_leg_exit_not_declared` unless `family_declares_no_leg_exit(manifest)` is True. Today that is True for no family.
- AC4: the new optional manifest key `no_leg_exit` is backward compatible. Every committed manifest loads with no change to its bytes or `manifest_sha256`. A missing key means False.
- AC5: nothing changes in these places:
  - `monitor_evidence.py`, `continuous_strategy.py`, symbology, adapters, `exec/`, Nautilus.
  - The depth subscriptions.
  - Any member of `_EXIT_RULE_REGISTERED_FAMILIES`, or any `deploy/families/*.json`.
- AC6: every exit family stays UNARMED, `allow_short` stays False, and no value is operator-reserved.
- AC7: the gate passes `scripts/ci/run_tests_no_egress.sh`, the full pytest suite, `lint-imports`, ruff and mypy. Each run uses PYTHONPATH set to the worktree.

## Edge cases
| Case | Behaviour |
|---|---|
| NO held, YES not held or not registered | The YES `_ensure_registered` returns None and must **no longer return early**. Routing to the NO sibling still runs. |
| Both legs held | Two independent evaluations of one frame. YES walks the bids, NO walks the asks, and each has its own `last_depth`, `last_book_ts_ns` and `held_qty`. No netting: FU-1c stays parked. |
| Stale frame | Each position's `last_book_ts_ns` is stamped from the same frame. A later `on_observation` re-uses the cached YES book for NO, so staleness grows and `_book_is_fresh` refuses. This is the same behaviour YES already has. |
| Book with bids only | NO gets `(None, False)` and stays `missing`, which is correct because nobody is selling YES. YES is marked. |
| Book with asks only | NO is marked and YES is `missing`. `spread` is None for both, as today. |
| qty larger than displayed asks | `(None, False)`. Never a partial or interpolated VWAP (existing `walk_exit_vwap` behaviour). |
| Frame keyed by a `^no` id (should never happen: the subscribe path refuses it) | `sibling_for` returns None for a NO id, so the frame is never re-routed. There is no YES↔NO ping-pong. |
| Malformed or foreign-venue id | `sibling_for` returns None, so there is no routing and no monitor_error. |
| NO evaluation raises | It runs under its own `_guarded("on_depth_sibling", …)`. It is counted separately and cannot suppress or alter the YES evaluation. |

## Architecture
- **Routing by injection, not import.** Add `sibling_for: Callable[[str], str | None] | None = None` to `PositionMonitor` and a 9th field `sibling_for` to `MonitorCallables`.
  - Keeps the monitor's pure/stub-testable design (D3), keeps it portable to Kalshi, and adds no new import to `position_monitor.py`.
  - Trade-off: one more field at 3 call sites, against making the monitor depend on the PM.us symbology. The default of None keeps old constructions byte-identical.
- **Gate placement.** Placed in `decide_exit` directly after `family_declares_exit_rule`, before `_select_rule`, so it refuses unconditionally with `rule=None`.
  - Trade-off: after `_select_rule` the refusal would keep the rule label. Before is stricter and simpler, and the thesis state is already recorded on the offer-tape row. Ruling (c) still holds because the family gate fires first.
- **Gate semantics.** `family_declares_no_leg_exit(m) = family_declares_exit_rule(m) and m.no_leg_exit`.
  - It only ever adds to the existing gate. It can never grant an exit on its own.
  - Its code-registered half is inherited from the frozenset. That satisfies L-22 (a safety exclusion must be unforgeable) for the family, and the ruling makes the manifest declaration itself a reviewed arming-change artifact.
- **Schema.** `no_leg_exit` only accepts the literal JSON `true`. `false`, `1` and `"true"` are refused with the message "omit the key". `true` without `exit_rule` is refused as incoherent.
  - This matches the narrow-grammar precedent of `taker_fee_coefficient`: one spelling per meaning.
  - `dump_family_manifest` leaves the key out when it is False.
- **Enforcement point.** The seam is not duplicated into `exec/submit_chain.unmappable_exit_order_reason` (an E0 egress surface). That keeps FU-1d out of the firewall-scanned exec package. Re-review at arming, per the ruling's re-open trigger.
- **Import layers are unchanged.**
  - strategy→adapters: `monitor_wiring` already imports symbology.
  - strategy→persistence: `exit_decider` already imports `exit_gate`.
  - No runtime imports are added.
- **Egress firewall.** None of the touched modules is under `_EGRESS_PATH_PREFIXES`, in `_EGRESS_MODULE_BASENAMES`, or in the E2 lists. No function takes an E3 name; `submit_exit` stays an injected param.

## File-by-File
1. `src/breezy/persistence/family_manifest.py`
   - Add `no_leg_exit` to `_OPTIONAL_KEYS`.
   - Add the field `no_leg_exit: bool = False` after `terminal_climate_day`.
   - Add the loader validation described under Schema.
   - Add a `_field_getters` entry that returns `True` or `None`, so it is omitted when False.
2. `src/breezy/persistence/exit_gate.py`
   - Add `family_declares_no_leg_exit` and put it in `__all__`.
   - Update the module docstring: two deliberate gates guard a NO exit, and the refusal must never come from missing data.
3. `src/breezy/strategy/current_rung_hold/exit_decider.py`
   - Add `_REASON_NO_LEG_EXIT_NOT_DECLARED = "no_leg_exit_not_declared"`.
   - Add the refusal branch when `evidence.leg == "NO"` (~8 lines).
4. `src/breezy/strategy/current_rung_hold/position_monitor.py`
   - Add the `sibling_for` param.
   - Split `on_depth` into the YES `_guarded` (body unchanged) plus a `_guarded("on_depth_sibling")` that calls the new `_on_sibling_depth(depth, now_ns)`.
   - `_on_sibling_depth`: `sib = sibling_for(iid)`, then None→return, then `_ensure_registered(sib)`, then `_evaluate(m, sib, now_ns, depth=depth)`.
   - Under 20 lines in total.
5. `src/breezy/strategy/current_rung_hold/monitor_wiring.py`
   - Add `_sibling_for(iid)`: `from_str` (ValueError→None); `leg_of=="no"`→None; `str(sibling_instrument_id(...))` (VenuePayloadError→None).
   - Add the matching field to `MonitorCallables`.
   - Add an L-44 row to the docstring table: NO mark source = the YES sibling's frame, walking the asks.
6. Pass `sibling_for=callables.sibling_for` at these call sites:
   - `composition.py:776`
   - `scripts/analysis/current_rung_hold_paper_replay.py:1131`
   - `tests/contract/test_position_monitor_trial_id_join_contract.py:71`
   - the `_wire_monitor` helpers in `tests/unit/test_current_rung_hold_position_monitor.py` (:466 and :892)
7. No change to `monitor_evidence.py`, `continuous_strategy.py`, symbology, `exec/`, `deploy/families/*`, or the Nautilus configuration.

## Test Strategy (RED first; RED→GREEN output kept as the artifact)
In `tests/unit/test_current_rung_hold_position_monitor.py`:
- (a) `test_no_leg_position_receives_a_mark_from_its_yes_siblings_depth_frame` — RED because it stays `missing`.
- (b) `test_no_leg_mark_equals_one_minus_walked_yes_ask_vwap`. Fixture:
  - asks (0.30×2, 0.34×3), qty 4, so walked ask VWAP 0.32 (2@0.30 + 2 of 3@0.34) and the expected mark is `Decimal("0.68")`.
  - bids at 0.90 as a decoy, to prove the bids are ignored.
  - The expected value is computed by the bot, never written in the test by hand.
- `test_no_leg_registers_from_sibling_frame_when_yes_is_not_held`, and `…_reconciled_after_restart` (AC2).
- `test_both_legs_held_are_each_marked_from_one_frame`.
- `test_bid_only_frame_leaves_no_leg_missing`.
- `test_no_leg_qty_beyond_displayed_asks_is_missing_never_partial`.
- `test_stale_cached_sibling_book_refuses_book_stale_for_no`.
- `test_a_no_leg_frame_is_never_rerouted`.
- `test_sibling_evaluation_error_is_counted_and_yes_record_is_unchanged`.
- (e) `test_yes_leg_records_are_identical_with_and_without_sibling_routing`: one YES frame/observation script run with `sibling_for=None` and again with it set. Assert that the `PositionMarkRecord` list, the offer-tape rows and `counters` are equal. All existing YES tests stay unedited and green.

In `tests/unit/test_current_rung_hold_exit_decider.py`:
- (c) `test_no_leg_exit_still_refuses_at_family_gate_today`, using the real committed `pm_us_crh_exit_v4` manifest, which has no `exit_rule`.
- (d) `test_no_leg_refuses_at_no_leg_gate_when_family_armed_but_undeclared`: exit_rule set, no `no_leg_exit`, a `depth_walk` mark present, DEAD state → `no_leg_exit_not_declared`.
- (f) `test_declared_no_leg_with_missing_mark_still_refuses_book_not_executable`. The declaration is built in the test fixture only; this proves the downstream block is still there.
- `test_yes_leg_ignores_the_no_leg_gate`.

Manifest and gate tests:
- In `tests/unit/test_persistence_exit_gate.py` / manifest tests:
  - `test_every_committed_manifest_loads_unchanged_and_declares_no_no_leg_exit`, iterating over `deploy/families/*.json` and comparing the sha before and after.
  - `test_no_leg_exit_accepts_only_literal_true`.
  - `test_no_leg_exit_without_exit_rule_is_refused`.
  - `test_dump_omits_no_leg_exit_when_false_and_round_trips_true`.
  - `test_family_declares_no_leg_exit_requires_the_exit_gate`.
- `tests/unit/test_current_rung_hold_monitor_wiring.py`: `test_sibling_for_maps_yes_to_no_and_refuses_no_malformed_foreign`.

Existing FU-1 tests that are affected (reviewer sign-off required):
- `test_no_leg_dead_with_an_armed_family_refuses_book_not_executable_while_no_marks_exist` (:1196) now refuses at the new gate. Retarget it to `…refuses_no_leg_exit_not_declared` rather than weakening it: the refusal and the `submit_calls==[]` assertion both stay. (f) preserves the old book-gate assertion.
- `test_no_leg_position_is_evaluated_on_observation_with_mark_source_missing` (:955) is observation-only, so it should stay green. Verify it is unedited.

Re-run:
- `test_current_rung_hold_composition.py`, `test_current_rung_hold_paper_replay.py`, `test_position_monitor_nightly_report.py`, `test_polymarket_us_exit_submit_chain_2026_09_16.py`, `test_no_side_calibration_gate_manifest.py`, `test_execution_egress_firewall_guard.py`, `test_cage_rule_constants_are_pinned.py`
- the full no-egress gate
- `lint-imports`

## Risks
- [MED] A test contract changes: the :1196 reason code. Mitigation: the ruling explicitly replaces this gate, the refusal is still pinned, and (f) keeps the book gate covered. Name it in the review brief so it is not silently accepted.
- [MED] The shadow evidence population shifts. NO positions start showing up in `PositionMarkRecord`, the nightly `_one_sided_book` rate and the digest `mark_missing` counters. Mitigation: record the FU-1d deploy SHA in the digest or PROGRESS so a step change is not read as a change in the market.
- [LOW] One more `positions_open(no_iid)` cache read per YES frame. It is an in-memory Nautilus cache read, bounded by the subscribed instruments.
- [LOW] Offer-tape and mark-buffer growth for NO positions. Already bounded by `should_emit` throttling and `_maybe_decide_exit` state gating (L-29).
- [LOW] Some contract test may pin the manifest key set (L-46). Grep `tests/` for the enumeration of `_OPTIONAL_KEYS` before placing the key; only the `_FLAG` check at `test_no_side_calibration_gate_manifest.py:26` was found, and it is unaffected.
- [LOW] Walked-ask VWAP versus realized NO fills is unvalidated. That is the ruling's re-open trigger and is out of scope here.

## LESSONS compliance (headers grepped)
| Lesson | How the plan complies |
|---|---|
| L-1, L-11 | No new infrastructure: the native frame is re-routed and `walk_exit_vwap` is reused. |
| L-2 | The mark is in the NO-leg price unit (1 − ask), consistent with the `1 − YES` wire convention. |
| L-12, L-14 | The new gate only adds to the existing one. It never relaxes it, and it is derived from "what would refuse a NO exit". |
| L-22 | The family half of the gate is still the code frozenset. |
| L-24 | (e) runs a real driver both ways instead of relying on a fixture that always satisfies the invariant. |
| L-29 | No new unbounded buffers. |
| L-43 | The full gate runs after the merge. |
| L-44 | Each leg's terminal state is tested ((c), (d), (f) and the YES-ignores-gate test). |
| L-46 | Check contract tests for key-set pins before adding the key. |
| L-51 | No `uv sync` or `git stash`; PYTHONPATH is set per worktree in every brief. |

## Confidence
HIGH (~88%). The one uncertainty is whether every NO fill is attributed to the `^no` InstrumentId in the Nautilus cache. FU-1 r2's T3/T4 already rely on that, and (a) and AC2 re-verify it against a real `positions_open`.

## r1.1 (coordinator, 2026-09-26): domain review HIGH, one fix applied
- **Fixture arithmetic corrected.** `walk_exit_vwap` clips each level to the remaining qty: 2@0.30 + 2@0.34 = 1.28 over 4, so the walked ask VWAP is **0.32** and the NO mark is **0.68**. The earlier 0.405/0.595 summed the full level-2 size, which is wrong. The test still computes the expected value through the real function.
- **Fee note.** `exit_fee` uses the NO-leg price (1 − ask). θ·p·(1−p) is symmetric under p↔1−p, which is intentional; do not "fix" it into an asymmetry.
- **Added risk [MED].** Per-leg marks and P&L are SHADOW evidence for a hedged pair. No digest, report or dashboard may sum `unrealized_pnl`/`recoverable_value` across YES+NO of the same station-day until FU-1c netting exists. Add a test that the nightly report does not aggregate across legs, or record it as a residual if no aggregation exists today.

## r1.2 (coordinator, 2026-09-26): architect REQUEST_CHANGES resolved

**(e) replaces the r1 test (e) [HIGH].** The r1 version was either vacuous or impossible.
- The replacement is `test_yes_leg_evidence_is_unchanged_by_no_sibling_routing`.
- It holds BOTH legs in BOTH runs: `sibling_for=None` and `sibling_for=_sibling_for`.
- Assert equal:
  - the YES-only `PositionMarkRecord` rows;
  - the YES-only offer-tape rows;
  - the YES `_MonitoredPosition` summary (state, `last_book_ts_ns`, `held_qty`, `mark_vwap`).
- Assert explicitly that the NO-driven counter deltas (`evaluations`, `emitted`) grow by exactly the NO rows emitted.
- Add `test_shared_mark_buffer_eviction_with_no_rows_is_counted`. With a small `maxlen` `MarkBuffer` (`monitor_store.py:170-180`), NO rows can evict YES rows. Assert eviction increments `monitor_marks_dropped` and never raises. This states and bounds the coupling. Also add it to Risks as **[MED] shared `MarkBuffer` capacity is now split across legs**, and check that `maxlen` has headroom at the live instrument count.

**AC2 authority [LOW].** Lazy registration of a reconciled NO position is authorised by `FU-1_plan_r2_2026-09-25.md:43` (MED residual), not by the ruling. Double registration is impossible because `_ensure_registered` and `_on_position_opened` both key on `self._positions`. Exposure of a position that is "not ours" matches YES today.

**Schema [MED].** The loader checks `payload.get("no_leg_exit") is True` (identity). A `== True` or `isinstance(bool)` check would let `1` through. Add a test case: `1` → refused.

**Existing test at :1196.**
- Retarget it AND rename it to `test_no_leg_threatened_with_an_armed_family_refuses_no_leg_exit_not_declared` (the helper drives THREATENED, not DEAD).
- Keep "no depth pushed", every-offer-row == the new reason, and `submit_calls == []`.

**Test helpers.**
- `_wire_monitor` and `_build_position_monitor_via_callables` default `sibling_for=None`, so existing YES tests stay byte-unedited. Only the new tests pass `sibling_for`.
- Extend the wiring test `test_build_monitor_callables_returns_all_eight_named_fields` to nine fields and rename it to `..._all_nine_named_fields`.

**Paper replay [LOW].** Any count or golden pin in `test_current_rung_hold_paper_replay.py` that grows by NO rows is an EXPECTED reviewed change. The implementer lists each pin changed, with before and after values. Never loosen a pin to a range.

**Re-open list additions (on any exit-family arming).**
- (i) `_station_day_exit_counts` (`position_monitor.py:547,584`) is shared by both legs, so a NO exit would consume the YES cap. Decide per-leg vs shared at arming.
- (ii) Add defence in depth: the NO-leg declaration check in `exec/submit_chain.unmappable_exit_order_reason` (`:464-487`), which today checks only the family gate.
- (iii) Walked-ask VWAP vs realised NO fills (from the ruling).

## r1.3: architect confirmation APPROVE, with a counter-semantics fix
- **(e) assertions.**
  - `Δevaluations == number of NO evaluations`: it increments per evaluation that passes facts/running_max, `position_monitor.py:496`.
  - `Δemitted == number of NO rows`, per `should_emit`, `:510`/`:623`.
  - Positive controls: YES mark rows are non-empty, YES offer-tape rows are non-empty, and there is at least 1 NO row.
  - Keep total rows below both `maxlen` and the 256 flush threshold, so there is no eviction or flush before the comparison.
- **The eviction test** builds `PositionMonitor` directly with `MarkBuffer(maxlen=3)`, like test :171, or adds a `buffer=` override to the helpers with default `MarkBuffer()`.
- **Risk wording:** the MarkBuffer coupling can bite only under sustained flush failure. maxlen is 2048, flush happens at 256, and a flush is retried on every emit.

**STATUS: CONVERGED.** Domain reviewer HIGH; architect APPROVE (r1.2 plus this fix).

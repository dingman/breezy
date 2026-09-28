# FAILURE-KIND-PERSIST plan

I pick option E: persist nothing, and publish the stale alert one pass later after a restart. That needs no change to any allowlist, cage pin or schema, and it also fixes the sticky kind.

## Findings that shape the plan
- The stale check runs at the top of each pass (client.py:2535-2558). The failure kinds are only written later in that pass (:2605, :2631, :2670, :2774). So the first pass after a restart always reads an empty dict and falls back to "none" (:2546).
- The boot pass is a one-shot pass run from `_connect` (`first_pass_immediate`, :2415-2417). It is always "pass 1" after a restart, and background passes follow about 5 s later (:2427).
- The runtime layer dedupes by intent_id and emits on the first sighting (component_health_watch.py:201-224). Changing the detail after it has been published never reaches the operator, so the kind must be right when the detail first appears.
- The kind is never reset. A GET that maps only resets the backoff counter (:2682). Several paths that block resolution set no kind at all: unmappable body (:2646), non-terminal status (:2710), positions read (:2720), undetermined position (:2741), incomplete join (:2809), minimum age (:2817).
- The firewall walks `ast.Call` nodes only (test_execution_egress_firewall_guard.py:2436-2444). Dict subscript assignment and `frozenset | {...}` are invisible to it. `self._store_set`, `context.to_bytes` and `replace` are not in the allowlist (:2101-2254).

## Options
| # | Option | Verdict |
|---|---|---|
| A | Add a kind field to `AmbiguousResolverContext` and rewrite it from the resolver | Reject. Needs `self._store_set` and `to_bytes`, i.e. new callees and allowlist growth, which requires security review. It also rewrites the record that drives resolution (`created_ns`) from inside the loop. |
| B | Store it on the SubmitIntent latch record (submit_intent.py:235-290, exact v1 pin :277) | Reject. Needs a new latch method, which is a new callee. It also writes to the order gate. |
| C | Piggyback on `_write_startup_position_evidence` (already allowed, :2195) | Reject. That record feeds the re-arm gate (:4709-4756). Carrying the kind there would use an allowed name for a new meaning. |
| D | Re-read activities at the top of the pass | Reject. Duplicates the whole GET → positions → join chain (:2626-2768) before the kind is even meaningful. |
| **E** | **Wait one pass after a restart; reset the kind on each GET that maps** | **Pick.** The kind is re-derived from this process's own evidence reads, at zero allowlist delta. |

## Semantics (answers Q2)
- Change `last_failure_kind` to mean "why the most recent pass did not resolve". Set "none" when the GET mapped and no classified failure followed.
- Keep no history per intent. The WARN/ERROR log lines at each site already record it (:2610, :2632, :2671). A history is YAGNI.
- The operator sees the cause as of the pass before the alert. After a restart that is the boot pass's evidence, so `activities_uninterpretable` comes back if the drift is still there. If a transient cause has gone away, the alert correctly no longer reports it.

## File-by-file (all in src/breezy/adapters/polymarket_us/exec/client.py; no other src changes)
1. **:1778.** Add `self._resolver_stale_observed_intent_ids: frozenset[str] = frozenset()`, with a comment on the whole-value reassignment rule.
2. **:2536-2558.** When the intent is stale and not yet alerted, publish only if one of these holds:
   - `context.intent_id in self._resolver_last_failure_kind` (this process has recorded a kind), or
   - the id is already in the observed set (fail-safe: a future `continue` that forgets to set a kind can delay the CRITICAL by one pass, never suppress it).
   Otherwise add the id to the observed set with `x = x | {id}`. No new callees.
3. **:2682.** Next to `consecutive_failures = 0`, add `self._resolver_last_failure_kind[context.intent_id] = "none"`. It is a subscript assignment, not a call. The `activities_uninterpretable` write at :2774 still runs after it.
4. **:5112 (`_retire`).** Remove the id from the observed set, the same way as `_resolver_stale_alerted_intent_ids`. `_retire` is not a scanned coroutine (:2082-2092).
5. **Docstrings.** Update the `stale_ambiguous_intent_alerts` docstring (:2304-2326) with the one-pass delay and the new meaning of "none".

## Tests (tests/unit/test_current_rung_hold_ambiguous_resolver.py; RED reason in brackets)
- **T1 restart.** Arm an intent, drift the activities, backdate the context, `_disconnect`, then build a fresh client over the same store (reuse the construction in test_edge2_ac6b_cross_process_fill_budget.py). Assert the boot pass publishes no alert and the next pass shows `activities_uninterpretable`. [Today the first pass publishes "none".]
- **T2 reset.** Pass 1 raises on the GET (`get_exception`). Pass 2 maps an `ORDER_STATE_NEW` GET. Backdate, run pass 3, assert the kind is "none". [Today it stays `get_exception`.]
- **T3 fail-safe.** Fresh store. The GET returns an unmappable body (a list, :2646) on every pass, so no kind is ever set. Assert an alert appears by pass 2 with "none". [Guards against the fail-safe arm being dropped.]
- **T4.** Extend :608 with `current.intent_id not in client._resolver_stale_observed_intent_ids` after retirement. [Leak.]
- **Unchanged, must stay green.** G7 (:5729), :5250 and :608 already record a kind before their stale pass. I traced all three through the new logic and they pass. None of them is weakened.
- **Gates.** Run the firewall guard and cage pin unmodified. Run the full gate with `scripts/ci/run_tests_no_egress.sh`, then lint-imports.

## Mutants the tests must kill
| Mutant | Killed by |
|---|---|
| M1: always publish on first stale sighting (no deferral) | T1 |
| M2: drop the observed fail-safe arm | T3 |
| M3: delete the reset at :2682 | T2 |
| M4: move the reset to the top of the pass | G7, :5250 |
| M5: `_retire` does not clear the observed set | T4 |
| M6: put the reset after the :2774 write | :5250 |
| M7: publish on the observed arm alone (drop the in-dict arm) | G7, and a single-pass-then-stale `get_exception` case |

## Risks
- **Alert delay.** At most one pass (5 s, or the backoff after a failed boot pass, capped at `_RESOLVER_BACKOFF_CAP_SECS`, :2435), against a threshold of about 15 minutes. Low.
- **"none" is ambiguous** for waiting states (non-terminal, minimum age, incomplete join). A follow-up could add plain-assignment kinds at :2710, :2720, :2809 and :2817. I left that out as out of scope.
- **The unmappable-body path (:2646) sets no kind and does not bump the backoff.** This is existing behaviour. T3 deliberately uses it as the fixture for the fail-safe arm, so if someone later adds a kind there, T3 needs a new fixture.
- **Firewall.** Delta is zero: no new `ast.Call`, no cage-pin method added (test_cage_rule_constants_are_pinned.py:332). Any implementation that reaches for `.add`, `.get`, `min` or `_store_set` has broken the plan and must be flagged for security review.
- **Invariants.** AMBIGUOUS is untouched. Only alert bookkeeping changes, and no retire or resolution path is edited.

## Q3: do it now?
Yes. It is about 10 lines and no allowlist changes. It restores the TRADE-ROW-DRIFT cause after the daily restart and mid-day relaunch, and the durable options (A/B) cost security reviews for no extra operator value.

## Confidence
- 0.85 overall.
- The main unverified point is the restart harness for T1. I did not open the cross-process test to confirm its helper names.
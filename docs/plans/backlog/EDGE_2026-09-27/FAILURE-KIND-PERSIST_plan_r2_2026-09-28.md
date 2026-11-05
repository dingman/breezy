# FAILURE-KIND-PERSIST plan, r2

**Result:** the candidate works, with one required change to `component_health_watch.py`. As written, (ii) never reaches the operator. The watch keys both its dedupe set and its forget step on the entry's `intent_id` field, not on the dict key (component_health_watch.py:216, :220-223). A follow-up that carries the same `intent_id` is skipped, whatever its dict key is. Allowlist delta is zero; security should still confirm the watch-module edit.

## Design
- **(i) CRITICAL unchanged.** The stale block at client.py:2535-2558 stays byte-identical. It publishes on the first stale sighting in every process, and the r1 observed-set deferral is dropped.
- **(iii) Follow-up only when the cause changed.** Insert one block after :2558. It writes `self._resolver_stale_alert_details[f"{id}:cause"]` only when all of these hold:
  - the id is in `_resolver_stale_alerted_intent_ids`;
  - the id is in `_resolver_last_failure_kind` and its kind is not `"none"`;
  - that kind differs from `self._resolver_stale_alert_details[id]["last_failure_kind"]`;
  - `f"{id}:cause"` is not already in the dict (at most once per intent per process, so a flapping kind cannot spam).
- **Follow-up entry contents.** The same fields as the stale entry, plus `"alert_key": f"{id}:cause"` and `"followup": "cause"`. It uses only `in`, `!=`, subscripts, an f-string and dict unpacking. Those are not calls, so the firewall sees no new callee (its walk scans `ast.Call` only, per the r1 finding, test_execution_egress_firewall_guard.py:2436-2444).
- **Event and severity.** The follow-up goes out as CRITICAL `open_intent_stale`, which the watch hardcodes anyway (:227-229). It is the same still-open condition with better information. This adds no new event constant and no routing change.
- **Timing.** The follow-up arrives one pass after the cause is recorded (5 s, or the backoff capped at `_RESOLVER_BACKOFF_CAP_SECS`, :2435). The CRITICAL itself is never delayed.
- **Rejected: set the follow-up's `intent_id` to `"<id>:cause"`.** That would need no watch change, but it corrupts a field the detail text renders as an intent id (:145, :150).
- **ARCH B1 reset:**
  - At :2682, set `"none"` only when the id is not in the kind dict, or its kind is not `"activities_uninterpretable"`.
  - After the join at :2768-2776, add: if `join is not None and not join.uninterpretable_rows`, set `"none"`.
  - This adds no calls.

## File-by-file changes
1. **client.py:1779.** Update the comment: the dict now also holds `"<id>:cause"` keys, still mutated by reassignment only.
2. **client.py, after :2558.** The follow-up block described above.
3. **client.py:2682 and :2769.** The guarded reset and the clean-join clear.
4. **client.py:5115 (`_retire`).** Add `self._resolver_stale_alert_details.pop(f"{intent_id}:cause", None)`. `_retire` is not a scanned coroutine, and it already calls `.pop` at :5115 and :5119.
5. **client.py:2304-2326.** Update the docstring: two entries per intent are possible, plus the new meaning of `"none"`.
6. **component_health_watch.py:**
   - Add `_alert_key = lambda a: a.get("alert_key", a.get("intent_id", ""))`. Use it at BOTH :216 (`current_ids`) and :220. If only one site changes, the follow-up is forgotten on every poll and re-emitted forever.
   - `_stale_intent_detail` (:144-153) appends "; cause identified after the first alert" when `followup == "cause"`.
   - Update the Notes at :193-198.
7. **trade_cli.py:424-444.** No change. The reader passes the tuple through unchanged.

## Tests (resolver tests in tests/unit/test_current_rung_hold_ambiguous_resolver.py; watch tests in tests/unit/test_component_health_watch_stale_intent_alert.py)
- **T1 restart and cause.**
  - Process A: `_arm_one_ambiguous_intent` (~:266), drift the activities, `_disconnect`, then `first_latch_cm.__exit__`.
  - Backdate `created_ns` through the durable store.
  - Process B: build with `_build_client_with_custom_loader` (~:2884), following test_edge2_ac6b_cross_process_fill_budget.py:608-653, then `_connect`.
  - Assert the boot pass shows the stale entry with `"none"`. Run exactly one pass with `_run_exactly_one_pass` (~:419) and assert the `:cause` entry carries `activities_uninterpretable`.
  - Flip the GET to raise, run one more pass, and assert the `:cause` entry is unchanged.
  - RED: today no follow-up entry exists.
- **T2 crash loop.** Three fresh processes in a row over one backdated store. Each runs only the boot pass from `_connect`, then disconnects. Each process's surface must contain the stale entry, and a per-process `install_stale_intent_alert` driven like :5444-5480 must record one CRITICAL.
  - This is GREEN today on purpose: it locks in current behaviour and is RED under the r1 deferral (M1).
- **T3 reset.** Pass 1 raises on the GET; pass 2 maps a NEW order. Backdate, run pass 3, and expect `"none"`. RED: today the kind stays `get_exception`.
- **T5 (ARCH B1).** Pass 1 is uninterpretable; pass 2's GET maps but the activities read raises, so join is None (~3244-3255). Backdate, run pass 3; the alert must carry `activities_uninterpretable`. It passes today and is RED under M8.
- **T6 clean clear.** Pass 1 is uninterpretable; pass 2's join is clean but incomplete (:2809). Expect `"none"`. RED: today the kind is sticky.
- **T7 same cause.** `get_exception` is recorded before the stale pass, and the stale pass is also `get_exception`. Expect exactly one entry.
- **T8 no "none" follow-up.** The GET maps NEW every pass. Expect no `:cause` entry, ever.
- **T9 retire.** Extend :608: after retirement, `f"{id}:cause"` is not in `_resolver_stale_alert_details`.
- **W1.** Two entries with the same `intent_id` and different `alert_key` produce two emits.
- **W2.** Three polls still produce two emits in total.
- **W3.** A legacy entry without `alert_key` still dedupes by `intent_id`.
- **W4.** The follow-up detail carries the cause marker.
- **Unchanged, must stay green:** G7 (:5729), :5250, :608, the firewall guard and the cage pin. Run the full gate with `scripts/ci/run_tests_no_egress.sh`, then lint-imports.

## Mutants
| Mutant | Killed by |
|---|---|
| M1: defer the CRITICAL on first sighting | T2, T1 |
| M2: no follow-up block | T1 |
| M3: no reset | T3 |
| M4: reset moved between :2527 and :2535 (before the stale check) | G7, :5250 |
| M5: `_retire` does not pop `:cause` | T9 |
| M6: drop the "differs from first kind" check | T7 |
| M7: drop the "not none" check | T8 |
| M8: unconditional reset | T5 |
| M9: no clean-join clear | T6 |
| M10: watch keys `current_ids` on `intent_id` | W2 |
| M11: watch keys the emit dedupe on `intent_id` | W1 |
| M12: follow-up overwritten every pass | T1 flip step |

## Risks
- **Crash loop faster than one pass.** The operator gets the CRITICAL (showing `"none"`) on every restart but never the follow-up. This meets the hard requirement. The cause still reaches the WARN/ERROR log lines (:2610, :2632, :2671).
- **Alert volume.** At most two CRITICALs per intent per process. Low.
- **Paths that set no kind.** `_note_resolver_error` (:2739, :2844), the positions read (:2720), the undetermined position (:2741) and the unmappable body (:2646) still set no kind, so they get no follow-up. That matches today; adding kinds there is a separate change.
- **Security review of the watch edit.** The change touches the runtime watch module, which is outside the exec firewall's scope. It adds no import and no egress; security-reviewer should confirm.
- **Invariants.** No resolve or retire decision changes, so an unresolved order stays AMBIGUOUS. No allowlist or cage-pin delta, and no safety test is weakened.

## Confidence
- 0.8 overall.
- **Watch dedupe finding:** verified directly (component_health_watch.py:216-223).
- **Least certain point:** whether any watch or trade_cli test asserts that the stale surface has exactly one entry per intent. The places to check are tests/unit/test_trade_cli.py:403-420 and test_component_health_watch_repoll_timer.py:184.
## r3 amendments (round 2, BINDING: they override r2 where the two conflict)
**Round-2 verdicts:**
- security: APPROVE. The crash-loop suppression is closed, the allowlist delta is zero, and the watch dedupe has no spam or loss path.
- architect: REQUEST_CHANGES, 3 blocking items, each with a precise fix (adopted below). Its scope ruling: the follow-up IS worth building.

**Rejected design:** r1 option E (deferral) is REJECTED. The CRITICAL is never deferred.

- **R3-1. Rebuild T8 (M7).**
  1. Pass 1: the GET raises (`get_exception`). Then backdate.
  2. Pass 2: the alert fires with `get_exception`. The GET maps to NEW, so the kind resets to "none".
  3. Pass 3: no `:cause` entry.
- **R3-2. Rebuild T9 (M5)**, all in one process:
  1. Pass 1 maps NEW, so the kind is "none". Then backdate.
  2. Pass 2: the alert fires with "none". The GET raises.
  3. Pass 3 writes `:cause`. Assert it is present.
  4. Make the GET terminal and retire. Assert `stale_ambiguous_intent_alerts == ()`.
- **R3-3. Change T1's flip step (M12).**
  - Run TWO passes after the flip.
  - Assert the kind dict holds `get_exception`, and that `:cause` still says `activities_uninterpretable`.
  - Drive the boot pass with `_run_exactly_one_pass`.
- **R3-4. M4 kill list.** Only G7 (test file ~5791; assert ~5828) kills M4. :5250 does not.
- **R3-5. Small fixes:**
  - `_alert_key` must be a `def`, not a lambda (ruff E731).
  - The follow-up's `age_minutes` is derived from `stale_age_ns`.
  - Update `docs/plans/R8_OPERATOR_RUNBOOK.md:537` and the property docstring at client.py ~2321, because an operator can now see two CRITICALs for one intent.
- **R3-6. Pre-merge check (security residual).** Confirm that no existing test asserts one entry per intent in a scenario that now writes `:cause`. The architect checked :5309, :5827, test_trade_cli.py:1415 and repoll_timer:189-202: all legacy, all unaffected.

**Confidence after round 2: HIGH.**

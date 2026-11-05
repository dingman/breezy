**Verdict: NOT-READY, 84/100.** One new HIGH item remains. The rest is confirmed.

## Confirmed
- **r4 H1 (self-heal):** resolved for the resolver accept-fill path (§3.5). It reads the booking with `.get` and pops it only after `settle` returns. `settle` is atomic, with validation before mutation. On an integrity raise the handler sets `registered=False` and `booking=None`, and abandons the entry with `settle(key, booking=None, realized_usd=None)`. That call adds no spend. It then falls through to `_retire` and the single existing UNBUDGETED producer at `client.py:3466`. I found no later pass that adds the realized cost, so it cannot self-heal. The end state is today's: retired plus a global halt. The deviation from "abort before the check" is accepted (§9 question 1, answered below).
- **r4 H2 (test sweep):** I swept `tests/` for `UNBUDGETED` and `unbudgeted`. These tests assert the latch:
  - `test_edge2_ac6b_cross_process_fill_budget.py` at :236, :276, :324 and :579;
  - `test_ambig_no_id_resolver.py:612`.
  - §3.7 maps all five to named successors with retained unregistered variants. I found no sixth.
  - `test_ambig_latch_resume.py:493` calls `_refuse` directly and is unaffected. The `:456` "not in" assertion stays green.
  - `test_polymarket_us_exec_client.py:4735` pins `ts_event` equal to the discovery clock. The shared-stamp change (M5) should leave it green under an injected fixed clock, but it is not listed. Add it to the WP4 focused list.
- **M1–M5:** all resolved.
  - M1: the pre-check returns None when plain `spent + cost > budget`.
  - M2: `seeded_partial` has a day filter, no-id gives 0, and there are four tests.
  - M3: the evidence dump is 0600 and fsynced, with file and directory (r5 :137).
  - M4: the breaker record carries `resolver_pass_ns` with a 600 s bound, and a supervisor-side dead-watcher check exists (r5 :321-331).
  - M5: one fresh clock read serves `ts_event`, `fill_ts_ns` and `settle`.
- **§9 question 1:** accept the deviation. Aborting would leave the intent OPEN, holding the slot of a held position. It would also make the existing producer unreachable without a new `_refuse` site, which moves the 25-site pin. Retire-plus-latch in one pass ends where today's code ends.

## New HIGH

**1. `settle` at the zero-fill and no-id sites contradicts the `_retire` chokepoint (§3.5).**
- At these two sites the existing order is `_retire` first, then the ledger call (`client.py:3223-3231`, `:4070-4072`).
- §3.5 line 238 says `_retire` calls an idempotent `settle(key, booking=None, realized=None)`, "after a handler's settle". The zero-fill and no-id sites call it before the handler's settle.
- The `_retire` call removes the charged entry without releasing its stored booking. The handler's `settle(key, booking=b, realized=0)` then hits an unregistered key carrying a booking. By the plan's own rule (line 238) that raises.
- Result:
  - Every in-process zero-fill or no-fill raises after `_retire`.
  - It skips the permit restore, the `generate_order_canceled` call and the AMBIGUOUS clear (:3274). That is the WP-DR defect class.
  - It also never releases headroom, which contradicts the plan's own claim that zero-fill releases headroom.
- Line 292 describes the zero-fill and no-id raise as an unusual case ("a raise propagates exactly as today"). With the ordering above it is the normal case.
- **Plan change** (any one):
  - Call `settle` before `_retire` at all six sites.
  - Remove the `_retire`-time `settle`.
  - Make `settle(key, booking=None, realized=None)` on a charged entry release the stored booking as zero realized.
  - Add `test_zero_fill_and_no_id_retire_order_settle_then_cancel_no_raise` and a test that headroom is released.

## Non-blocking note
- The create-path accept-fill at `:6467` has no defined failure path. A settle raise there escapes the task, as today. The plan should say so, or apply the same abandon-and-retire pattern.

Relevant files:
- /home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/EXEC-PAR-parallel-intents_plan_r5.md
- /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py
- /home/jon/breezy/tests/unit/test_edge2_ac6b_cross_process_fill_budget.py
- /home/jon/breezy/tests/unit/test_ambig_no_id_resolver.py
- /home/jon/breezy/tests/unit/test_polymarket_us_exec_client.py

# AUT-1 r2: merged review (coordinator). silent-failure-hunter 83 (1 HIGH), trading-bot-architect 81 (2 HIGH). Final 81, NOT READY.
**Rebase on ARCH Rev 6** (`/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev6.md`). Duplicates are merged and there are no contradictions.

## HIGH
- **D1 [ops D1, sf N1]: re-baseline on Rev 6 C1.**
  - `OrderLink(instrument_id, side, qty, px, time_in_force)` with no `intent_id`; the join is on `client_order_id`.
  - Payload store `derived/capture_payloads/{depth10,forecast_input}/<sha>.json`, written with `os.link`.
  - Settlements go to `decisions/settlement_<date>.jsonl`. Delete N6.
  - The `DecisionRecord` fields are `ask_px`, `p_hat`, `p_hat_raw`, `p_lower`, `p_upper` and `ev_net`.
  - Invariants bind from `capture_epoch_start`.
  - Split into AUT-1a and AUT-1b.
  - The self-heal counter uses write-once records in `evidence/selfheal/<date>/`.
  - Use `TimeoutStartSec`, not `RuntimeMaxSec`.
- **D2 [ops D2]: quote-triggered Takes.** Pass `source` in ctx. For a `quote_tick` Take, store a quote preimage (ask, bid, ts_event), or refuse it with a named reason. Test it.
- **D3 [sf N-HIGH]: heartbeat activation.** Add an `AWAITING_HEARTBEAT` state, INFO only, until the first heartbeat or the first rotate after merge. After 26 h it raises a CRITICAL. It never triggers a restart. Test it.

## MEDIUM
- **D4 [ops D3]: capture bypass.**
  - Add an AST test that every `submit_order` call site under `strategy/` is either in a guarded class or unreachable from the `app/trade.py` composition.
  - Name where armed CRH exits are captured, or declare the CRH kinds RefusingPlugin and unreachable for sending.
  - Guard `submit_order_list` too [sf N9].
- **D5 [ops D4]: decision_id plumbing.**
  - Cover `evaluate_snapshot`, `_emit_shadow_decision` and `_evaluate_instrument_update` through to `_maybe_submit`.
  - Take `eval_ns` = `ts_event` (venue time) while TrySubmit uses the wall clock. Pin this in the R1 test.
- **D6 [ops D5, ops C10]: refused-after-TrySubmit.** Add the classification `refused_after_trysubmit`, tied to the same-id `EntryVeto`. A leg asserts that TrySubmit(submitted) implies a link or that veto. Replace "the log stops before the next event" with a testable boot-ended condition.
- **D7 [ops C6]**: Budget and benchmark the full Take-to-IOC path (Take fsync, 2 blob puts, TrySubmit fsync, link fsync), not only the guard's steps 1–4.
- **D8 [ops C9, sf N4]: quiet-hours stalls.**
  - WP0 measures quiet-hour silence too, and the multiplier is derived from it.
  - The writer-stall event floor scales with time, removing the 1–49 events gap.
  - Add a positive-control test.
- **D9 [sf N2]**: R2 replays the log lines through the same on-change rule and compares the resulting sequence with the capture records.
- **D10 [sf N3]**: A NO_INPUT day writes `capture_join_completeness` with `outcome=NO_INPUT`.
- **D11 [sf N5]: short writes.** Add a `needs_newline` flag that prefixes `"\n"` on the next write. When `AlertOutbox.offer()` returns False, count the drop and write the marker.
- **D12 [sf N6]: untagged SELL.** Refuse BUY only. For a SELL, write the OrderLink and a DetectorEvent, then submit.
- **D13 [sf N7]: log-parser positive control.** If any boot overlapped D, require at least one `SHADOW_DECISION` line and a present funnel file; otherwise the day is ERROR. Define what happens when the funnel file is missing.
- **D14 [sf N8]**: State which trigger paths can reach the per-instrument veto, test them, and add quiet-hours treatment.

## LOW
- **D15 [sf N10]**: Classify `journalctl` failures as ERROR. Test an unparseable `extend_dedupe:` line. Pin the `custom_depth_truncation` type name. Re-audit INCONCLUSIVE days, and alert after 8 days.
- **D16**: Re-score honestly.

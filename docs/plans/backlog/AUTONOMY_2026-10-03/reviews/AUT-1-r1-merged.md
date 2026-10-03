# AUT-1 r1: merged review (coordinator). trading-bot-architect 81, silent-failure-hunter 76. Final 76, NOT READY.
Duplicates merged; no contradictions.

## HIGH
- **C1 [sf1, ops2]: independent audit denominators.**
  - Reconcile the per-day Take, TrySubmit and refusal counts against an independent source: the funnel JSONL (`decision_funnel.py`) or the node `SHADOW_DECISION` and `FQ_VECTOR_COMPLETE` log lines.
  - Reconcile EVERY exec-store order record (not only fills) against OrderLinks.
  - Add `test_funnel_vs_capture_count_mismatch_fails` and a test that deleting a capture record makes the day fail.
  - Add a periodic mark source that does not depend on the node.
- **C2 [sf2]: audit self-failure.**
  - Positive control: the `fill_by_day` count equals the number of `FILL_` keys, and agrees with the node `OrderFilled` log lines.
  - A missing audit file for an elapsed day with fills is a FAIL.
  - An exec-store open error or key-schema drift is never NO_INPUT.
  - Dead-man: no audit verdict within 26 h raises a CRITICAL through `deliver_with_proof`.
  - `OnFailure` delivery is proven (G25: `emit_alert` swallows failures).
- **C3 [sf3]: stall detection.**
  - WP0 measures the live byte-growth cadence and the recorder-side silence p99.9.
  - Add an independent `WRITER_STALL` state: counters rising while bytes stay flat for N minutes.
  - Add RED tests with positive controls (a healthy fixture does not trigger; a frozen-writer fixture does).
- **C4 [sf4]: the INCOMPLETE signal must not be best-effort.**
  - Derive it from the independent reconciliation in C1.
  - Journal to a second location (the evidence dir), log `CAPTURE_WRITE_FAILED` to the node log, and check short writes.
  - Add `test_marker_write_failure_still_fails_day`.
- **C5 [ops1]: the stall drill window.** The drill cannot run at 09:10–09:20Z: the rotate at 09:00Z resets the instance age, and that is the empty-listing hole. Move it to a window at least 1 h after rotate and outside the hole (for example Sunday 12:30Z), chosen with WP0 evidence.
- **C6 [ops3; ARCH W9]: hot-path latency.**
  - Do the sha and blob work after the on-change check.
  - Node-side CRITICAL delivery goes through a bounded outbox off the loop. Add `test_try_submit_latency_independent_of_webhook`.
  - Set a measured p99 budget for the fsync path, benchmarked in WP2.

## MEDIUM
- **C7 [ops4]**: Exits get a deterministic `decision_id` (derived from the exit rule and `client_order_id`, using the exit tag prefix). A legitimate exit raises no CRITICAL, and every exit fill joins.
- **C8 [ops5]**: Composing without a writer fails boot closed. Test `CaptureGuardedStrategy` with no writer. Add `capture_untagged` to the VetoReason set.
- **C9 [ops6]**: STALLED is gated to live-window hours, or uses a quiet-hours multiplier. Overnight exhaustion of the restart cap resets before LAUNCH.
- **C10 [ops7]**: Add a `never_submitted` classification for a crash between the OrderLink write and submit, with a crash-injection test.
- **C11 [ops8]**: Canary days follow one rule: they are dropped from the window, or count only as tagged canaries, as the ARCH and README X19 rule says. Name the canary producer (AUT-2 owns the canary store, AUT-6 owns delivery).
- **C12 [ops9; ARCH W11]**: The restart counter is persisted and survives a process restart.
- **C13 [sf5]**: Track feed freshness per subscribed instrument, with a veto when more than a literal, tested fraction is silent.
- **C14 [sf6]**: The audit reads the `extend_dedupe:` summary line. `flat_root != none` or a non-zero `custom_depth_truncation` means a tape-incomplete CRITICAL. Test it.
- **C15 [sf7]**: Add `test_reason_is_closed_enum` and `test_utc_rollover_open_failure_is_loud`, and state the availability cost of a cap hit (`health.ok=False` refuses entries until UTC midnight).
- **C16 [sf8]**: Add `test_refused_order_never_reaches_cache`, `test_duplicate_or_malformed_tag_refused` and `test_capture_refused_log_has_entryveto_record`. WP2 is gated explicitly on the WP0 Python-override dispatch premise.
- **C17 [sf9]**: The audit includes an NBP cycle census leg (`NBM_NBP_PUBLISHED` and `FQ_VECTOR_COMPLETE` per cycle).

## LOW
- **C18 [ops10]**: Add a watch-liveness alert that does not depend on the node.
- **C19 [sf10, ops11]**: Re-score honestly.

## ARCH deltas to absorb
/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-r4-merged.md (W6 entry_guard read path, W9, W10, W11, W12, W13). Systemd: `RuntimeMaxSec` does nothing on oneshot; use `TimeoutStartSec`.

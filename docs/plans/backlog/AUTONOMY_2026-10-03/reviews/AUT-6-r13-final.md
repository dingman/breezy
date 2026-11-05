# AUT-6 r13: final verdict
**READY.** Both reviewers (TBA and SFH) scored it 95, with zero CRITICAL and zero HIGH findings. Both flagged readings are accepted:
- D-1 is anchored on the verdict's `slot_start_ns`.
- INTEGRITY means a delivered CRITICAL, not a HALT.

The items below are binding on the WP briefs.

## MEDIUM
- **Backlog verdicts (SFH):** #16 selects the newest `eval_replay_path` verdict whose tape day equals D-1. It never takes the plain max `slot_start_ns` over backlog verdicts. Add a test with a backlog verdict present.
- **No-admitted-day branch (SFH):** evaluate the no-admitted-day branch before the tape-day check, or pin the tape-day metric as always present. A routine venue-skip day must never page.
- **Metric names (TBA):** the tape-day and parity metric names are "to be pinned from AUT-4's catalogue". **AUT-4 build item:** register those names in `metric_registry` before go-live.

## LOW
- **Champion swap:** after a champion swap, exempt `eval_replay_path_subject` and `c4_directory_missing` for 26 h.
- **WARN frequency:** a WARN with k<3 fires once per UTC day.
- **Double page:** a parity mismatch double-pages, through #16 and through AUT-4's ALERT. Either state that this is intended or dedupe on the closure sha.
- **Producer-live marker:** the marker latches on the first `eval_offline` verdict, including ERROR. Note this.
- **E-7c (2026-10-03):** the shared bwrap wrapper provides a private `--tmpfs /tmp` with TMPDIR; see ARCH-ERRATA E-7c. Binding build item.

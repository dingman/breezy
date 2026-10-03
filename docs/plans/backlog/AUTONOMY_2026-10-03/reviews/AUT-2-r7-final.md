# AUT-2 r7 final: READY. PM 96, SFH 95, zero CRITICAL or HIGH.

The following are binding on the WP briefs:

**MEDIUM**
- **V8 deadline.** The delivery worker thread runs with `daemon=True`. After the fsync of the durable writes, the process exits with `os._exit(4)`. The hung-sink test asserts wall-clock exit under the budget.
- **Budget clock.** Every budget is measured from the process's monotonic start, against `TimeoutStartSec − TIMEOUT_STOP_S`. Test this with a slow pre-read step.

**LOW**
- `--measure-peak` skips `memory_gate` and `--proof-window`. Add a test.
- Delete the uncapped `MemoryHigh = 0.9×` sentence (WP6, line 849).
- For V4, count only days on or after the unit's first journaled run.
- Add the label slots to the catch-up tally deny set, or state the memory-sum bound.
- Use one shared dedup key for the post-STOP lock-contention CRITICAL and its OnFailure notifier.
- The first label hold is CRITICAL-bearing.
- Add `LABEL_FLOCK_WAIT_S` to the slot_guard term if the tally becomes a flock member.
- Consume ARCH errata E-7/E-8 (unit-sandbox enforcement) once adopted. The architect determines the per-plan consumption.
- **E-7/E-8 (adopted 2026-10-03):** consume per the table in ARCH-ERRATA-rev9_2.md 'E-7/E-8 consumption by plan' (binding build item).
- **E-9 (adopted 2026-10-03):** any multi-command oneshot bounds each command and sums the bounds (ARCH-ERRATA E-9). Binding build item.
- **E-7a (adopted 2026-10-03):** universal bwrap through the shared wrapper and table; WAL reads via the snapshot helper; AST check is a lint. See ARCH-ERRATA E-7a. Binding build item.
- **AUT-NATIVE (2026-10-03):** native pressure test PASS; binding build items in reviews/AUT-NATIVE-pressure-test-2026-10-03.md.
- **E-7c (2026-10-03):** the shared bwrap wrapper provides a private `--tmpfs /tmp` with TMPDIR; see ARCH-ERRATA E-7c. Binding build item.

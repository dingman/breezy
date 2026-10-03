# DEFER-STREAK-LOAD r2: APPROVED (sha b0c1d178…)

- **Scores:** python-reviewer 96, silent-failure-hunter 95. Zero CRITICAL or HIGH findings, so the plan meets the bar (≥95, 0 CRIT/HIGH).
- **SFH verdict:** SFH wrote "not approved" because it read the bar as stricter. Under the programme rule a 95 passes.

## Binding build items
**MEDIUM (SFH)**
- Map `UnicodeDecodeError` to `UNPARSEABLE`.
- Also catch `RecursionError` from deeply nested JSON, which must not crash-loop.
- Add a T12 case for each.

**LOW**
- Drop or soften the T15(c) prose pin.
- Make `save_state` cleanup use `contextlib.suppress(OSError)` and re-raise the original error.
- Add a parity test between every `EXIT_*` constant and `_QUOTE_TAPE_INGEST_EXIT_NAMES`.
- Update the unit comment at lines 117-119 to include exit 5.
- Make the WARN print `field=-` for non-BAD_FIELD reasons.
- Add these notes to §8:
  - A save failure on a non-pending run can produce a false exit 4 on the next pending run. This is loud, not silent.
  - Exit 3 or 4 masks exit 5 in the notifier name, but both lines still reach the journal.

# AUT-1 r11 — merged blind review (2026-10-03)

| Reviewer | Score | CRIT/HIGH |
|---|---|---|
| trading-bot-architect | 95 | 0 |
| silent-failure-hunter | 93 | 0 |

The lower score is 93, so the plan goes to r12. Every item below is a targeted edit.

## Already verified

- The rotate arithmetic is right:
  - max start = 180 + 3900 + 300 + 120 = 4500
  - rotate bound = ⌈4662/60⌉×60 = 4680
- The single-constant derivation is right.
- Per-write checks are sound under concurrency and under rotation.
- GM3's use of `config.json` as the boot count is sound.
- The ~38 h blind window is acceptable.

## Owed in r12

1. **[MED, SFH] First write to a lazily created custom table.** `writer.py:240-249` creates the table before `serialize_batch` (`:259`), so a drop on the first write still looks like a success.
   - Fix: if the table key was absent before the call, require `size > 0` after it.
   - Add this case to V-19's mutation set.
2. **[LOW, SFH] Deferral vs start budget.** The X-3 pre-READY deferral can run past `QUOTE_TAPE_MAX_START_SECS`, up to 17:10Z. Cap pre-READY deferral at the max-start constant.
   - Recommended: stop the deferral before READY, so the start times out and restarts normally.
   - Otherwise, state the interaction and have AUT-6's activating tolerance read the deferral state.
   - Either way, state the choice in §3.10.2.
3. **[LOW, SFH] Rename and test the restart counter.** Rename `recorder_restarts_unexplained` to `recorder_boots` (or document it as "unexplained boots") and state that it counts all restarts. Add a test with a venue-outage fixture.
4. **[LOW, TBA] Use the `config.json` mtime.** Count by the `config.json` mtime. Directory mtime is only a pre-filter. WP0 V-21 asserts this.
5. **[LOW, TBA] Check for units that touch `live/<instance_id>`.** Add a WP0 line recording whether any unit moves or compresses `live/<instance_id>` directories. Undercounting is safe, but record it.
6. **[LOW, TBA] Cross-plan note.** AUT-6's `test_rotate_bound_covers_member_stop_stoppost_and_ready` computes from the unit files and the constant, never from a literal. AUT-6 r15-final item 7 is already updated to 4500/4680 via the constant.
7. **ER-9 text.** Make sure §ERRATA-REQUEST carries the architect's ER-9 replacement text verbatim.

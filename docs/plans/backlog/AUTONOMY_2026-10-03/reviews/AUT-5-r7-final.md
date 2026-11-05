# AUT-5 r7: final review
**Verdict: READY.** TBA scored 96 and security 95, with zero CRITICAL or HIGH findings.

The following are binding on the WP briefs.

## MEDIUM (security)
- At the time of the transition, embed `drawdown_inert=true` in the DRILL_ADMIT/L2 evidence note. Use an existing free-text field. If C5 has no such field, raise an errata item for a physical column.
- Do not derive this flag only at read time.

## LOW
- Set the bootstrap `TimeoutStartSec` to the literal 60 (E-10a). Drop reading R7-1 and update the test.
- Reconcile the WARN count for a malformed row on an inert block. Either state that it produces two WARNs, or suppress the INCONCLUSIVE one.
- **Ceiling backstop:**
  - Raise a WARN or CRITICAL when the block is inert and the ceiling cannot be evaluated for N days (labels GATED).
  - The backstop stays silent without error when labels are unavailable. Test this.
  - Finalise the 0.5 ceiling in WP3.
- The 16:48:01 timeout end is recorded as E-10b.

## E-7a
Consume E-7a once it is adopted: universal bwrap, and the AST check demoted to a lint.
- **E-7a (adopted 2026-10-03):** universal bwrap through the shared wrapper and table; WAL reads via the snapshot helper; AST check is a lint. See ARCH-ERRATA E-7a. Binding build item.
- **E-8a (2026-10-03):** `exec_snapshot` gains `cache_dir` and `take_flock` parameters. Only the 16:45 pass flocks; node-up reads are advisory. Binding build item, with a test per mode.
- **AUT-NATIVE (2026-10-03):** native pressure test PASS; two §2 rejection rows owed (reviews/AUT-NATIVE-pressure-test-2026-10-03.md).
- **E-7c (2026-10-03):** the shared bwrap wrapper provides a private `--tmpfs /tmp` with TMPDIR; see ARCH-ERRATA E-7c. Binding build item.

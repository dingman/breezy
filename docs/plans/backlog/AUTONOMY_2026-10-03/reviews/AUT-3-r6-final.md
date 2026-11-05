# AUT-3 r6 final: READY. MLE 96, PM 95, zero CRITICAL or HIGH.
Carried into implementation, binding on the WP briefs:
- **MEDIUM:** a `Persistent=true` catch-up must defer if it would fire inside [16:30Z, 17:10Z) or 01:00–04:30Z. Add a test for the catch-up case.
- **LOWs:**
  - Count timer jitter in the worst-end figures.
  - The AM fit margin is 1.3× or includes an extract allowance.
  - Force-sample rung_recalibration when density is `not_claimed`.
  - Assert the `REFIT_PROGRESS` lines in a test.
- **E-7/E-8 (adopted 2026-10-03):** consume per the table in ARCH-ERRATA-rev9_2.md 'E-7/E-8 consumption by plan' (binding build item).
- **E-9 (adopted 2026-10-03):** any multi-command oneshot bounds each command and sums the bounds (ARCH-ERRATA E-9). Binding build item.
- **E-7a (adopted 2026-10-03):** universal bwrap through the shared wrapper and table; WAL reads via the snapshot helper; AST check is a lint. See ARCH-ERRATA E-7a. Binding build item.
- **AUT-NATIVE (2026-10-03):** native pressure test PASS; binding build items in reviews/AUT-NATIVE-pressure-test-2026-10-03.md.
- **E-7c (2026-10-03):** the shared bwrap wrapper provides a private `--tmpfs /tmp` with TMPDIR; see ARCH-ERRATA E-7c. Binding build item.

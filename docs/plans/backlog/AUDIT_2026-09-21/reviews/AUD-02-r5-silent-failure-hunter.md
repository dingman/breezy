# AUD-02 round 5 review — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: 99bcc4abdd830b7c2e36b59475adb88f35e33886af9bd9dde243320a79adfd3c
Round: 5. Reviewer: silent-failure-hunter (independent, blind).

## Round-4 MATERIAL defects: re-verified FIXED
1. Store-path mismatch: `node_store_path_check` (`exec_state_db_path.py:142-182`) now mandatory
   inside the set CLI, refusing unless `MATCH`/`NO_NODE` — same accept-set as `main` (`:62-66,212-214`),
   CONFIRMED via source. Before/after tokens in §7 step 0c, RED test (8), §8(g). Closed.
2. Vacuous verification: §7 step 0d replaced with a read-only `--status` (reads the SAME bytes
   `is_family_halted`/the veto read, `trial_day_latch.py:1002`→`composition.py:195-228`, CONFIRMED)
   plus a test-harness forced-submit refusal under the no-egress gate. Market-activity-independent.
   RED tests (9)-(10), §8(h),(k). Closed.

## New claims (round 5): verified against source
- Exit seam also vetoed: `exit_wiring.submit_exit` checks `is_family_halted()` FIRST (`:269-275`) —
  CONFIRMED, independent of the entry-path veto (own read of the latch, not a shared call site).
- Self-check ordering: `self_check` (`trade_supervisor_core.py:499-553`) returns
  `FAIL_CONTINUOUS_FAMILY_HALTED` LAST — after child/flock/log/subscribed/permit AND after
  `phase0_clean`/`startup_evidence_valid` (`:534-552`) — CONFIRMED byte-for-byte; a genuine failure
  always wins over the halted branch. `SELF_CHECK_UTC = 17:05`/window closes `:45`/`mark_phase_fired`
  latches once-daily (`:34,45,765,777`), single call site `trade_supervisor.py:1485` — CONFIRMED. The
  "repeatedly, each tick" premise the r4 review attributed was indeed wrong; this round's correction
  is accurate, not merely asserted.
- No downstream detector found that keys specifically on the daily self-check PASS token beyond the
  alert-egress path itself (searched); the stated cost ("no daily PASS token while halted, offset by
  `halt_enforced`/`--status`") is not shown to silently degrade any other liveness check.

## MATERIAL defect (new, round 5 — the pre-set open-position check has an unaddressed staleness hole)
`StartupPositionEvidence` is written ONLY "at the END of `_connect`" (`client.py:3102-3133`,
`_refresh_startup_position_evidence`'s own docstring, CONFIRMED) — i.e. at boot/reconnect, not
continuously. `STARTUP_EVIDENCE_KEY`'s comment (`:397-401`) confirms it is "the most recent evidence,
never a history" with no freshness contract. A node that stays connected all day never rewrites this
record; a fill or exit that occurs AFTER the last connect is therefore invisible to it. §6.5's
pre-set open-position check (preference order (1) this evidence, (2) live GET) reads `ts_ns` but
never BOUNDS its age against "now" or cross-checks it against the latch's own live-updated fill
record (`record_duplicate_fill`/`record_ambiguous_exit`, which ARE written at fill/exit time). A
node boot hours or days before deploy time, with a same-day fill after that boot and no intervening
reconnect, would report `eof_complete=True, position_read_refused=False, net_position=0` (stale)
and the tool would proceed to SET the halt over what is actually an open, un-exited position — the
exact failure mode §6.5 was added to close, reopened by its own preferred data source. Required
change: (1) reject/treat-as-UNKNOWN when `ts_ns` is older than a stated bound (e.g., the current
trading day's launch, or N minutes); (2) or make option (2), the live GET, the DEFAULT rather than
the fallback, since it costs one request and removes the staleness question entirely; (3) add a RED
test for "flat evidence, but stale" refusing rather than proceeding.

## Per-criterion (cap/points)
fidelity 20: 18 · technical correctness 20: 17 · implementation specificity 15: 13 ·
acceptance criteria/validation 20: 15 (tests 8-12 do not cover a stale-but-flat evidence case) ·
autonomous/failure handling 15: 11 (§9's failure-case catalog omits evidence staleness) ·
portfolio alignment 10: 10.

**Total: 84/100.**

## Blockers
None operator/strategy-lead-side; the staleness gap is buildable within AUD-02b's own scope.

# AUD-19 — round 5 — silent-failure-hunter

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-19-family-manifest-flag-on-replay-driver.md
sha256: e71328be8c7d2ff92812a4736904994ba8ead45fae75f0a3189ca286cb021708
Reviewer: silent-failure-hunter (blind, independent)

## Round-4 finding (D6) — verified fixed
§6 E3's "any other exit code" branch now specifies the row write instead of asserting behaviour in
prose: the runner (still alive; only its driver child died) appends exactly one
`append_replay_result` row, `outcome="FAILED"` (AUD-09's closed set, confirmed at `:702`), the literal
`UNCLASSIFIED_DRIVER_EXIT_<returncode>` in the field AUD-09's FAILED path already uses for the
exception type (no new row key — schema `:698-702` re-confirmed untouched), unit exits non-zero, day
leaves the row-presence queue. D6 moved from FLAGGED/deferred to DECIDED; 22-pre now only re-verifies
the field name. New RED test (`test_an_unclassified_driver_exit_appends_one_FAILED_row_and_leaves_
the_queue`, signal-killed stub) asserts exactly one row, its contents, the next-pass queue absence, no
`record_blocked` call, and B19's run reset (not advanced). A14/A17 extended; A17 now requires the
dispatch to be total over `int`, swept `{-9,-15,4,75,137,255}`.

## Citations verified against source
`:655-657` — "If the parquet is unreadable it appends `outcome="FAILED"` with the exception type,
exits non-zero, and the day leaves the queue — it never re-selects the same dead day nightly" —
CONFIRMED verbatim. `:688-692` — `MemoryHigh=3G`/`MemoryMax=4G`, "being OOM-killed in its own cgroup
is the intended, loud outcome" — CONFIRMED. `:693` — "No `Restart=` — a missed day is not an
incident" — CONFIRMED. `:903-905` — "OOM: killed in its own 4 GB cgroup, unit fails, node untouched"
— CONFIRMED. `:923-928` — "Autonomous operation... failures land in the unit's failed state...
inherits G-14's weakness for the failed-unit path... alerting (shipped `f97c26f`)" — CONFIRMED. B19's
reset-on-`FAILED` rule — CONFIRMED against the text read in round 4 ("a `COMPLETED`/`RECOVERED`/
`FAILED` row... resets the run so the next three re-arm it").

## Judgment requested: permanent day-loss on transient OOM, and loudness
**Follows AUD-09, does not contradict it.** AUD-09 itself already treats an OOM-killed run as a
deliberate, accepted, non-retried outcome for the exact same cgroup — `:693` states no-retry as
general policy ("a missed day is not an incident") and `:691-692`/`:903-905` state OOM specifically
as "the intended, loud outcome" with no distinction for transience. AUD-19's D6 applies this same
policy to a driver *subprocess* dying inside the runner's own cgroup (which systemd's `MemoryHigh`/
`MemoryMax` already scope to the whole cgroup, children included, per `:688-692`'s own framing of
"a single-day replay reaching 4 GB") rather than inventing a stricter or looser rule. **Loud, not
silent:** the runner exits non-zero on this branch (stated in §6 E3's table and §9's new bullet),
which puts the runner's own systemd unit into the failed state AUD-09 §9 (`:923-928`) already relies
on for G-14 alerting — the same escalation path every other crash class in this plan uses. No new
silent corner is introduced.

## Sweep
No new defect found in this round's diff. The row-write specification, the RED test's assertions
(exact row count, exact contents, queue-absence on next pass, B19 non-advancement, no `record_blocked`
call), and A17's totality sweep together close the round-4 gap completely: every `int` return from the
driver now provably terminates in exactly one row, with no path that logs-and-returns silently.

## Per-criterion (cap)
Fidelity 20/20 · Technical correctness 20/20 · Implementation specificity 15/15 (D6 fully specified) ·
Acceptance criteria 20/20 (A14/A17 close the round-4 gap with a concrete RED test and a totality
sweep) · Autonomous operation/failure handling 15/15 (loud, fail-closed, consistent with AUD-09's own
no-retry/OOM policy, escalation path verified reachable) · Portfolio alignment 10/10.
**Total: 100/100.**

## Blockers
None. No MATERIAL defect remains from this reviewer's lens across five rounds.

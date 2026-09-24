# AUD-15 round-6 delta review — trading-bot-architect

Plan: AUD-15-failing-study-units-fix-or-retire-and-alert.md
SHA256: 45f00e04d057ee4810c659619cb75c26d07c50d69f5f74b9ef1223f4c7d69618
Round: 6 (ruling-application delta, FINAL for this cluster)
Reviewer: trading-bot-architect (blind)

## Verified against source

- `breezy-mb-daily.timer:30` → `OnCalendar=*-*-* 13:30:00 UTC` CONFIRMED — this is the exact slot
  the plan claims mb-daily's retirement vacates and the new `breezy-asos-refresh.timer` claims.
- `deploy/systemd/README.md:936-938` → `P = [16:45Z, 01:15Z)`, no-start rule
  `[16:35Z, 01:15Z)` CONFIRMED. `13:30Z` is well outside this window — no protected-window
  collision.
- `breezy-position-monitor-report.service:13` → *"It holds no venue credential and opens no
  socket"* CONFIRMED verbatim — the plan's stated reason for rejecting it as a re-home host
  (an outbound IEM HTTP GET would invert that invariant) is accurate.
- `breezy-exit-window-study.timer:20` → `15:20:00 UTC`, after `breezy-position-monitor-report
  .timer:21` → `15:00:00 UTC` CONFIRMED — the plan's "runs after the earlier consumer" rejection
  reason for that candidate host is accurate.
- `Slice=breezy-studies.slice` confirmed on `breezy-position-monitor-report.service:43`,
  `breezy-exit-window-study.service:42`, `breezy-mb-daily.service:48` — the new unit's slice
  choice matches the existing pattern. `flock -n 9 || ... exit 0` confirmed at
  `mb-daily-run.sh:81` — the plan's flock-idiom citation for the new wrapper is accurate.
- `tests/unit/test_deploy_timer_hours.py`'s collision model (`test_no_two_timers_share_an
  _hour_minute_tick`) scans `deploy/systemd/*.timer` **present in the tree at test time**, not a
  frozen list — so a same-commit retire-and-reclaim of the 13:30 tick is structurally the correct
  shape (the same pattern this test file already uses for WP-11b's per-family-tally retirement).

## Defect found — a real, unaddressed test regression

**`test_every_timer_file_is_parsed_by_this_test` (`test_deploy_timer_hours.py:107-117`) hard-pins
`assert "breezy-mb-daily.timer" in names` (`:116`).** The plan's own step 7d deletes
`breezy-mb-daily.timer` in the retirement commit. That assertion is not descriptive text or a
comment — it is a live, executed pytest assertion — so the retirement commit, exactly as
specified, makes this existing test fail RED. Nothing in §7 (steps 7a-7f), §8 (items 1-12,
including item 8's "Full gate... green"), or the round-6 revision table names this test file at
all. This is the same class of gap the coordinator's brief asked me to check for directly
("the tick-collision rule") and it is real: the plan verifies there is no *new* collision at
13:30Z (correctly — mb-daily's own tick is what's being vacated and reclaimed) but never checks
that an *existing* test elsewhere pins the *timer file's name*, not merely its tick, and that
pin breaks on deletion regardless of what tick the replacement claims. §8 item 8's "Full gate
green" is not achievable as the plan is currently scoped, without this fix.

**Required change:** add one step to §7 (e.g. 7d or a new 7d-bis) updating
`test_every_timer_file_is_parsed_by_this_test`'s sanity pin — replacing
`assert "breezy-mb-daily.timer" in names` with an assertion against a surviving timer (e.g.
`breezy-asos-refresh.timer` or another already-present name), in the **same** retirement commit,
and add it as a named acceptance item alongside §8 item 8. This is a small, mechanical fix, but it
is currently missing and the plan's own "full gate green" claim depends on it.

No other regression found across the six hunks: the WITHDRAWN-BY-RULING strikeouts are internally
consistent (nothing references the removed fix-path machinery from a surviving section), the
module-exclusion list (offer-gate scan, M_A, M_B scripts) is correctly carried into both scope and
the new negative `git diff` acceptance item, the anchor non-fork claim is mechanically pinned
(imported, not copied) rather than asserted by comment, and the freshness-vs-existence distinction
in the new alert is applied consistently in both the build-time pin and the runtime WARN.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Both units' retirement, the binding re-home condition, and the narrower A1 re-home scope (fixed-window only, not the rolling invocation) are all applied faithfully to every section the ruling touches. |
| Technical correctness and evidence grounding | 20 | 18 | Every citation checked against source this session (timers, protected window, candidate-host postures, slice/flock pattern) and correct. Deducted 2 for the test-regression gap above — a real, freshly-introduced technical fact about the tree this revision did not check. |
| Implementation specificity and feasibility | 15 | 13 | The re-home is fully literal (unit name, slot, slice, ceilings, timeout, flock idiom, anchor-import mechanism, three new RED tests). Deducted 2: the missing `test_deploy_timer_hours.py` fix means the specified step sequence does not actually reach a green full gate as written. |
| Acceptance criteria and validation quality | 20 | 18 | Twelve items, with the pin/mtime-advance/delivered-alert triad correctly distinguishing build-time from runtime proof. Deducted 2: item 8 ("Full gate green") is not achievable without the missing test-file fix, and nothing in §8 names it as a required update. |
| Autonomous operation, failure handling and recovery | 15 | 15 | The silent-stale failure mode is closed on two independent legs (build-time pin, runtime WARN); the fail-soft exit-0 shortfall path is correctly routed around `OnFailure=` to the new alert instead. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Cost avoidance correctly reclassified from plausible to realised on the units' own measured figures; the one surviving value (the live-path cache) is preserved by the binding same-commit condition; new-unit-over-reuse is justified against YAGNI with both alternative hosts rejected on their own declared posture, not merely on convenience. |
| **Total** | **100** | **94** | |

## Required changes

One: add an explicit step updating `test_every_timer_file_is_parsed_by_this_test`
(`test_deploy_timer_hours.py:116`) to stop pinning the now-deleted `breezy-mb-daily.timer` by
name, in the same retirement commit, with a corresponding acceptance item.

## Blockers

None. Both fix-or-retire rulings (RULING 1, items 1-2) are RULED and peer-ENDORSED, with the
Revision 2 addendum (§A1) correctly narrowing and superseding the re-home scope. 15a was never
blocked.

# AUD-18 — Round 2 review (prediction-market-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
SHA256: 8d64da2403183c32bb8db8c5ea336f6e32070856100df9ce473c7e9f1c10b54d
Round: 2 (blind re-review of the whole revised plan; prior round-1 record at reviews/AUD-18-r1-prediction-market-reviewer.md)

## Round-1 defects re-verified against source

1. **B18/C19 fourth-invocation contradiction — GENUINELY FIXED.** §5/§6.4/§6.4b withdraw the fourth-`"$PY"`-invocation idea entirely; AUD-18 now ships its own `breezy-hypothesis-triage.{service,timer}` + `hypothesis-triage-run.sh`, `After=breezy-replay-daily.service`, on the SAME `$LOCK_DIR/breezy-studies.lock` via `flock -n` skip-not-kill. Verified against the real wrapper precedent (`deploy/systemd/offer-gate-daily-run.sh:55-70`): lock-dir resolution, `mkdir -p`, `exec 9>>`, `flock -n 9` skip-not-kill all match. `MemoryHigh=1G`/`MemoryMax=2G` vs the sibling units' `12G`/`16G` (`breezy-offer-gate-daily.service`) is confirmed an order of magnitude smaller. AUD-09/AUD-10 are independently confirmed closed at 100/100 (`AUD-09...md:1164`, `AUD-10...md:1064`), so "do not edit a closed item" is the correct call. §7 step 5's new RED (assert `replay-daily-run.sh`'s invocation set is exactly AUD-09's three scripts, does not contain `hypothesis_triage.py`) is a real non-regression test, not a restatement.
2. **External strategy-lead blocker — GENUINELY FIXED.** §7 step 8 is now a concrete two-peer dispatch (author + adversarial reviewer) producing a dated `docs/evidence/RULING_<id>_horizon_<date>.md` before registration and before data is opened, fixing n/stopping-rule/alpha-share/KILL-criterion, touching no operator cap. Matches the pattern this repo already used for `RULING_A1`.
3. **Stale "operator budget ceiling" blocker — GENUINELY FIXED.** §12 now correctly states the budget ceiling is already established and out of scope; only live-trading enablement of a new family remains operator-only, stated with no value assigned.

## New citations verified

`BoundaryArtefact.boundary_for/.alpha_spent/.remaining_alpha` (`gs_boundary_artefact.py:~183,201,211`), `information_fraction` (`current_rung_hold_v2.py:367`), `load_realized_draws` (`persistence/realized_draws.py:249`, corrected from the wrong prior citation), `resolve_alert_sink`/`emit_alert` (`runtime/health.py:579,668`) — all CONFIRMED verbatim against source. The `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` Revision-3 "ENDORSED — no required change" claim is CONFIRMED against `docs/evidence/reviews/RULING_A1_review_2026-09-21.md`'s own Revision-3 delta ("Verdict: ENDORSE — no required change").

## New defects (both MINOR — not blocking)

**MINOR — stale status label in §13's own revision log.** §13's round-2 log entry (last line) still calls the A1 ruling "the PROPOSED `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`", while §12 (correctly) now says "peer-ENDORSED ruling (Revision 3)... ENDORSED by independent peer review with no required change." Internally inconsistent within the same document. Required change: update §13's log line to match §12's (accurate) ENDORSED status.

**MINOR — timer schedule left as constraints only.** §6.4b's `.timer` states `OnCalendar` must sit outside the protected window and after AUD-09's slot but gives no concrete value (sibling units like `breezy-offer-gate-daily.timer` state one, e.g. `02:05:00 UTC`). Required change: name a concrete `OnCalendar` value (or state it is chosen at implementation time against whatever slot AUD-09 lands on, explicitly deferred).

No other new defects found; no duplication of AUD-09/AUD-10 content (the new §6.4b cites their wrapper pattern by path/line rather than restating their design); length grew to 638 lines but the growth is load-bearing (sequential-design spec, own scheduling unit, peer-ruling step) not padding.

## Scoring (20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 19/20 — mid-programme Holm-withdrawal treatment remains explicitly open (§12, acceptably deferred, not a fix required this round).
- Technical correctness and evidence grounding: 19/20 — all citations re-verified accurate; docked for the §13/§12 PROPOSED/ENDORSED inconsistency.
- Implementation specificity and feasibility: 14/15 — docked for the unspecified concrete `OnCalendar` value.
- Acceptance criteria and validation quality: 20/20 — D1-D11 objective, testable, and D5/D6/D9-D11 close every round-1 gap.
- Autonomous operation, failure handling, recovery: 15/15 — own unit, ordered, lock-serialized, memory-capped, alerts on failure via the shipped sink; no external dependency left unconverted.
- Portfolio alignment, scope and dependencies: 10/10 — dependencies clean, no edits to closed items, scope held.

**Total: 97/100.**

## Blockers

None. Both prior blockers were converted to in-plan steps (round-1 finding, re-confirmed fixed); no unavailable evidence or operator/strategy ruling stands between this plan and execution.

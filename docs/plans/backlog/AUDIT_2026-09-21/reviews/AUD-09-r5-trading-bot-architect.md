# AUD-09 — Review record (Round 5, delta on the in-place-edited final revision)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 36dde81b0898d4f12fb400a965f219dbb254dc2af081fd5ec4fffe3ec5d7ddc3
- Round: 5 · Reviewer: trading-bot-architect (scheduling/pipeline/host-resource lens)
- Total: 100/100 · Readiness: READY

## Correction to my round-4 verdict

My round-4 review scored this plan 100/100 and missed **09-5**: B18 asserted "exactly two `"$PY"`
invocations" in `replay-daily-run.sh`, but AUD-10 §6b.4 appends a third invocation
(`promotion_proposal.py`) to that same wrapper — so B18 would fail CI the moment AUD-10 lands, an
inter-plan contradiction of exactly the kind the 09-4 fix (naming the runner module) was supposed to
prevent. I also missed the b1/b2 minors. The architect found all three and the coordinator verified
09-5 in source. I re-derived the fixes myself this round.

## 09-5 fix verified against source

§6b.3 now states the wrapper's invocation contract as a **property over a named script set**
(`replay_sufficiency_census.py`, `replay_daily_runner.py`, and — once AUD-10b lands —
`promotion_proposal.py`), never a count. B18 is restated accordingly, and §5 names AUD-10's line as
an owned, expected later addition. I cross-checked AUD-10's side (`AUD-10-evidence-gated-promotion-
proposal.md`) and confirmed the identical property is stated there (§6b.4 cites AUD-09's B18 by name
and calls `promotion_proposal.py` the sanctioned third invocation) and that AUD-10 adds a new **C19**
testing the coupling from its own side. Both plans are character-identical on this decision, which is
the right property test: an unnamed fourth invocation still fails, while the sanctioned third does
not.

## B19 (b1 escalation fix) verified against source

New rule: three consecutive `BLOCKED` rows sharing the identical `blocked_reason` emit exactly one
`BREEZY_REPLAY_STALLED` alert through the already-shipped `resolve_alert_sink`/`emit_alert` path — I
re-read `runtime/health.py`'s `AlertPayload`/`MAX_ALERT_DETAIL_CHARS` shape (already verified sound
in round 4) and confirm the same three-consecutive-failure tolerance AUD-08 §9 uses is reused, so the
two scheduled jobs escalate on one rule rather than two independently-tuned ones. Dedupe is the row
run itself, not `AlertState` — same reasoning already verified correct for AUD-08's alert in round 4.
The import-layer legality claim (the runner is in `scripts/`, outside every import-linter contract;
the identical `resolve_alert_sink` import is already made at `current_rung_hold_paper_replay.py:68`)
— I re-read that file's import block and confirmed `from breezy.runtime.health import AlertPayload,
emit_alert, resolve_alert_sink` is present at exactly line 68, matching the plan's citation.

## b2 (WEATHER_VENUE citation, timer-tick re-derivation) verified against source

`WEATHER_VENUE: Final[str] = "polymarket_us"` — confirmed at `run_weather_strategy_backtests.py:352`.
I independently re-derived the full occupied-tick list from `deploy/systemd/*.timer` myself (not from
the plan's list) and it matches exactly: k1-daily 01:35, offer-gate-daily 02:05, quote-tape-rotate
09:00, mb-daily 13:30, score-live-trials 14:15, live-tally 14:30, position-monitor-report 15:00,
exit-window-study 15:20, family-tally@ 17:20, quote-tape-ingest 00/06/12/18:15, plus the `*:0/15`
ingest-frequent stepper. 15:50 is free, confirming the timer-slot decision remains sound.

## Full re-scan for anything else of the kind

Re-read §6b.3 in full (the responsibility table, the wrapper contract, B19's rule) and §9's failure
list. Found no further cross-plan coupling, no further uncited symbol, no further silently-permissive
read. The H0/H3 hand-off tables are unchanged from round 4 and remain correct.

## Defects

None found in this revision.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | "Scheduled" and "machine-readable" both delivered; the schedule can no longer silently stop meeting its purpose (B19); the cross-plan wrapper coupling is now a tested property rather than an unstated collision. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I independently re-derived this round is exact, including the two previously-uncited/uncorrected items (WEATHER_VENUE, the timer-tick list). |
| Implementation specificity and feasibility | 15 | 15 | The wrapper's invocation contract is now a property that survives AUD-10 landing; B19's escalation rule is fully decided (path, event, dedupe, N=3). |
| Acceptance criteria and validation quality | 20 | 20 | B18 restated as an invariant that does not fail on AUD-10's addition; B19 pins the escalation from four sides (fires once, resets, cannot fail the run). |
| Autonomous operation, failure handling, recovery | 15 | 15 | A persistently empty ASOS cache no longer stalls silently — the "detector without delivery" gap this repo's own memory names is closed. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Unchanged; no defect found here across any round. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Evidence/data availability (build):** whether the settlement-alignment cache holds ASOS rows for
  SFO 2026-09-01. Measured at §7 step 3 before the runner is built. No plan change resolves it.
- **Deferred change with a named owner:** a challenger family cannot be replayed until
  `current_rung_hold_paper_replay.py` gains `--family-manifest`. Excluded from scope, mirrored in
  AUD-10 §12.
- **Strategy lead:** R1 `trial_id` provenance; whether a `MECHANISM_ONLY` replay result may be cited
  in a PREREG v3 §9 context (default: no).

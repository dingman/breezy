# AUD-09 — Review record (Round 5, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 36dde81b0898d4f12fb400a965f219dbb254dc2af081fd5ec4fffe3ec5d7ddc3 (coordinator recorded 36dde81b…)
- Round: 5 (delta) · Reviewer: architect (code-architect lens)
- Total: 99/100 · Readiness: READY (one one-line MINOR outstanding)

## Round-4 dispositions, verified against the plan body AND against source

| R4 defect | Claimed | Verified? |
|---|---|---|
| **09-5 (MATERIAL)** — B18's "exactly two `"$PY"` invocations" would fail the moment AUD-10 appends its emission line to the same wrapper | ACCEPTED | **FIXED, and fixed as a property rather than by bumping a number.** §6b.3's contract now reads: *every* `"$PY"` invocation in `deploy/systemd/replay-daily-run.sh` is one of the named scripts — `replay_sufficiency_census.py`, `replay_daily_runner.py`, and, once AUD-10b lands, `promotion_proposal.py` — and the wrapper contains no JSONL parsing and no `record_blocked`. **B18** asserts exactly that (§8), §7 step 10 asserts it, and **§5 names AUD-10's addition as expected and sanctioned, owned by AUD-10, with "nothing else may be appended without amending B18's named set"**. I diffed the normative sentence against AUD-10 §6b.4: **character-identical**, so the binding cannot drift. AUD-10 carries **C19** testing the same property from its side. An unnamed fourth invocation still fails — the property keeps the guard's teeth. |
| **b1 (MINOR)** — a persistently `BLOCKED` schedule never escalates | ACCEPTED | **FIXED, and carefully.** **B19**: three consecutive `BLOCKED` rows under the *identical* `blocked_reason` emit exactly one `BREEZY_REPLAY_STALLED` through the already-shipped `resolve_alert_sink` (`runtime/health.py:579`) / `emit_alert` (`:668`) path, `severity="warning"`, `detail` naming the reason and the act it implies. The design decisions around it are the right ones and are all tested: a fourth row emits none; an intervening `COMPLETED` or a *different* `blocked_reason` resets; a raising sink leaves the exit code 0; an unset webhook degrades to `LoggingAlertSink` so escalation never converts a healthy `BLOCKED` day (exit 0, day stays queued) into a unit failure. §9 and §10 both carry it, and §9 now states precisely the right thing: this is the one failure mode unit state can never express. |
| **b2 (MINOR)** — `WEATHER_VENUE` uncited; tick list carried | ACCEPTED | **FIXED, and I re-derived the tick list myself.** `WEATHER_VENUE: Final[str] = "polymarket_us"` is cited to `run_weather_strategy_backtests.py:352` — confirmed, and it is already reached by cross-script import from both replay drivers, so the helper needs no new import path. I re-read every `deploy/systemd/*.timer` `OnCalendar=` line this round: 01:35, 02:05, 09:00, 13:30, 14:15, 14:30, 15:00, 15:20, 17:20, `00,06,12,18:15`, plus the `*:0/15` stepper. That is exactly the plan's list, **15:50 is free**, and it is not a multiple of 15 so the frequent-ingest stepper does not collide either. Discharged. |

Everything from round 3 is unchanged and still correct: the runner module + responsibility table, H0's
Reader and H3's Writer naming the module, B17 against the module's vector builder, the
`climate_day_utc_bounds` helper (`sites.py:135-148,403-414`; `structural_dead_stop.py:148-155`;
`paper_replay.py:181`), the corrected mypy justification, and the IEM-map bound in §6c step 6/§12.
C10 == B10 is unchanged and the §6 layers/contract text still matches AUD-10 §6 substantively.

## Defects found in revision 5

**b1 (MINOR, NEW) — the paragraph claims character-identity with AUD-10 that does not hold, which
weakens the drift guard the plans rely on.** §6b.3's heading says *"this paragraph is
character-identical in AUD-10 §6b.4"*, and AUD-10 §6b.4 says the same of AUD-09. They are **not**:
the two paragraphs have different lead-ins (AUD-09: *"Revision 4 asserted 'exactly two…', and AUD-10
§6b.4 appends a third to this same wrapper"*; AUD-10: *"AUD-09 revision 4 asserted that wrapper
carries 'exactly two…' and pinned it in B18; this line is a third"*) and different closings (AUD-10
adds *"an unnamed fourth still fails. This item carries C19…"*). **The normative bolded property
sentence IS identical** — I compared it word for word — so no contract drifts; but a future reader
who diffs the paragraphs (which is exactly what these self-identity claims exist to invite, as with
`C10 == B10` and the §6c tables) finds a difference and cannot tell whether it is benign.
REQUIRED: scope the claim to what is actually identical — e.g. *"the bolded property sentence below is
character-identical in AUD-10 §6b.4"* — or make the two paragraphs identical. One line, in both plans.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | The census, the scheduled runner, the machine-readable result and the missing ASOS producer are all in scope and specified; SP-4 is folded **with** its blocker; §6c bounds the item to step 6. The two remaining gaps — the family dimension (blocked on a driver change explicitly owned elsewhere) and `run_weather_strategy_backtests.py` (AUD-11's scope) — are blocker/other-item scope and are not deducted. |
| Technical correctness and evidence grounding | 20 | 19 | Every claim I re-checked this round is exact, including the tick list I re-derived independently and `WEATHER_VENUE`'s definition site. −1 for the false character-identity claim (b1). |
| Implementation specificity and feasibility | 15 | 15 | The runner is a named, strict-typed module with a responsibility table; `record_blocked` and `climate_day_utc_bounds` are functions with homes; the command block carries every `required=True` flag; the wrapper's contract is a property over a named set that an implementer can satisfy unambiguously. |
| Acceptance criteria and validation quality | 20 | 20 | B1–B19 objective; B18 is now future-proof against the sanctioned third invocation and is duplicated from AUD-10's side (C19); B19 pins the stall escalation including its reset and its no-fail-on-raise property; B17/B14/B16/B9 unchanged and sound. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Every failure branch owned in Python and unit-testable; `ASOS_CACHE_EMPTY` keeps the day queued; unreadable-work-list ≠ empty queue; crash recovery, duplicate-key hard error, skip-not-kill flock, own-cgroup OOM, timer gated on a non-`BLOCKED` row — **and the one mode unit state cannot express now escalates on its own (B19)**. The round-4 deduction is fully discharged. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Mechanism-vs-edge separation on two independent grounds; the deferred driver change and the IEM-map constraint named with owners and mirrored; PREREG barrier, permit path and NO-SEND untouched; abandonment criterion with a stated adjustment. |
| **Total** | **100** | **99** | |

## Required changes to reach 100
1. Scope the "character-identical" claim to the bolded property sentence, or make the two paragraphs
   identical (b1) — one line, mirrored in AUD-10.

## Blockers (recorded separately; not scored)
- **Evidence/data availability (build):** whether the settlement-alignment cache holds ASOS rows for
  the target climate day. Measured at §7 step 3 before the runner is built, both outcomes pre-defined,
  timer gated on a non-`BLOCKED` row.
- **Deferred change with a named owner:** `--family-manifest` on the replay driver; until it exists no
  challenger can be replayed. Mirrored identically in AUD-10 §12.
- **Strategy lead:** R1 `trial_id` provenance; and whether a `MECHANISM_ONLY` result may be cited in a
  PREREG v3 §9 context (default: no). Both block a statistical reading, not the build.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._

# AUD-09 — Review record (Round 4, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 2812b8b0e02901516d043b198ed308e2a5cf140ab5155a6fa8ceece054d8d3f6 (filled by coordinator at save time)
- Round: 4 · Reviewer: architect (code-architect lens)
- Total: 95/100 · Readiness: NOT READY (one material cross-plan defect, author-resolvable)

## Round-3 dispositions, verified against the plan body AND against source

| R3 defect | Claimed | Verified? |
|---|---|---|
| **09-4** — the runner has no module; H0/H3 name a shell script as the caller of Python functions; `record_blocked` is an undefined shell helper; B17 parses the wrapper | ACCEPTED IN FULL | **FIXED, and fixed structurally rather than editorially.** §6b.3 opens with **`scripts/analysis/replay_daily_runner.py`** and a seven-row responsibility table that puts every decision I named in Python: the H0 read with B14's refusals, target selection under the full key, both `subprocess.run(..., shell=False)` invocations, the `RECOVERED`/`FAILED` branch, `record_blocked(reason)` **as a function**, the `append_replay_result` duplicate-key hard error, and the summary line. The wrapper is reduced to `flock`/`say()`/env resolution and two `"$PY"` calls, modelled on `mb-daily-run.sh`. **H0's Reader row and H3's Writer row now name the module** (H3 additionally states all four outcome paths share the one writer). **B17 is retargeted** to the module's vector builder and **B18** pins the split from both sides. §7 steps 8–10 target the module. This is a complete fix. |
| **b1** — output set ≠ emptiness predicate; no window helper | ACCEPTED | **FIXED, and the reasoning is sourced.** `--out` is now windowed, so the two sets are one. `climate_day_utc_bounds` composes `ClimateDayWindow.std_utc_offset_hours` (`sites.py:135-148` — the docstring pins "NEVER DST-aware … local-standard midnight to midnight all year", exactly as quoted; accessor `:403-414`) with `standard_time_zone`, the identical pair `structural_dead_stop._afternoon_window_ns` composes at `:148-155` (re-read: confirmed). Choosing midnight-to-midnight over `AFTERNOON_WINDOW_*` is argued from `load_replay_observations` (`paper_replay.py:181`, confirmed) consuming the whole replayed day at `received_at_ns = observed_at_ns + lag`. Correct, and the "widen one helper with its own test" escape is the right shape. |
| **b2** — false mypy-coverage justification | ACCEPTED | **FIXED and now true.** Re-read `pyproject.toml:159-189`: the list is `adapters, normalize, registry, settlement, domain, ingest, persistence, runtime, strategy` + `scripts/venue`, `scripts/analysis`, `scripts/archive`, `tests` — `src/breezy/app` and `src/breezy/features` are indeed absent. The change stands; the replacement reason (the analysis cores hold the H0/H3 signatures AUD-10b reads) is narrower and correct. |
| **b3** — the hardcoded five-entry `IEM_ASOS_IDS` bounds the portability claim | ACCEPTED | **FIXED, and widened beyond what I asked.** Recorded at the resolution site (§6b.1), in §12 with an owner, and in **§6c step 6** with the consequence I had not drawn: the same `load_sites()` is called by `count_covered_listed_station_days_from_catalog` (`structural_dead_stop.py:237`, confirmed), so a sixth site breaks AUD-08's sufficiency computation **and** the KILL clock, not just this producer. |
| **TRIVIAL** — `load_sites` range | ACCEPTED | Corrected; §6c step 3 also re-pathed to `src/breezy/registry/sites.toml` for cross-plan consistency. |

The layers/forbidden-contract decision, the armed-family decision, H0's seven rows and the timer-slot
reasoning are unchanged and remain correct (`importlinter/contracts/forbidden.py:72,131-143`;
`pyproject.toml:68,71-101,116-121`). `WEATHER_VENUE`, used uncited by the new helper, does exist
(`run_weather_strategy_backtests.py:352`) and is already imported cross-script by both replay drivers —
no defect, but see b2 below.

## Defects found in revision 4

**09-5 (MATERIAL, NEW — the 09-4 fix introduced a cross-plan contradiction: B18 will FAIL the moment
AUD-10 lands).**
§6b.3 now specifies the wrapper as carrying "**two** `"$PY"` invocations", and **B18** asserts it
literally: *"`deploy/systemd/replay-daily-run.sh` contains … exactly two `"$PY"` invocations (the
census and the runner module)"*. But **AUD-10 §6b.4 emits the promotion proposal from this same
wrapper** — *"appended to the AUD-09b wrapper (`replay-daily-run.sh`), inside the same host-wide
`breezy-studies.lock`, after the replay"* — restated in AUD-10 §10 (*"10b is one extra line in the
AUD-09b wrapper"*) and executed at AUD-10 §7 step 13 (*"GREEN the script + wrapper line"*). That is a
third `"$PY"` invocation of `scripts/analysis/promotion_proposal.py`. So either B18 fails CI once
AUD-10 lands, or AUD-10's emission has no home — and whichever way it is resolved, the implementer of
the second item must resolve a design decision the plans do not. This is exactly the class of defect
the 09-4 fix was for (an inter-item binding stated in one plan and contradicted in another); the count
is the wrong invariant to assert.
REQUIRED: restate B18's third clause as a **property rather than a count** — e.g. "every `"$PY"`
invocation in the wrapper is one of the named scripts (census, runner module, and — once AUD-10 lands —
`promotion_proposal.py`), and the wrapper contains no JSONL parsing and no `record_blocked`" — and name
AUD-10's appended line in §5 or §12 as an expected later addition, with the same sentence in AUD-10.

**b1 (MINOR, NEW) — a persistently empty ASOS cache is a permanently quiet failure, and the fix is
demonstrably available in-repo.** §9 makes `ASOS_CACHE_EMPTY` a first-class outcome that keeps the day
queued and exits 0 — correct — but the plan concedes (self-score, autonomy row) that a *persistently*
empty cache "yields a quiet nightly `BLOCKED` row with no escalation of its own". The unit never fails,
so G-14's alerting over unit state never fires, and the item's whole purpose (a schedule that actually
replays) silently stops being met. This is the "detector without delivery" shape memory
`readiness-audit-2026-09-12` prices, and the sibling plan proves the remedy is one call: AUD-08 §6b.4
escalates through the already-shipped `resolve_alert_sink`/`emit_alert` path (`runtime/health.py:579,668`).
REQUIRED: after N consecutive `BLOCKED` rows under the same `blocked_reason` (N stated), emit one alert
through the shipped sink, with a criterion — or state the acceptance of a silent stall explicitly as a
bounded, owned residual.

**b2 (MINOR, NEW) — two load-bearing symbols in the new helper are uncited, and one carried claim was
not re-verified.** `climate_day_utc_bounds` uses `WEATHER_VENUE` with no file:line (it is
`run_weather_strategy_backtests.py:352` and reaches the replay drivers by cross-script import —
grounded, but the plan's own standard is to cite), and the self-score concedes the timer-tick list
(the basis for the 15:50 slot and for `test_deploy_timer_hours.py` staying green) is carried from an
earlier round rather than re-read.
REQUIRED: cite `WEATHER_VENUE`'s definition site and re-derive the occupied-tick list this round.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | "Scheduled" and "machine-readable" both covered; the census, the runner and the missing ASOS producer are all in scope; SP-4 is folded **with** its blocker; §6c bounds the item to step 6. The two remaining completeness gaps — the family dimension (blocked on a driver change explicitly scoped to another owner) and `run_weather_strategy_backtests.py` (AUD-11's scope) — are **blockers/other-item scope, so not deducted** per the rubric; both are named with owners. |
| Technical correctness and evidence grounding | 20 | 19 | Every round-3 correction verified at source this round (`pyproject.toml:159-189` omissions; `sites.py:135-148,403-414`; `structural_dead_stop.py:148-155,237`; `paper_replay.py:181`; `settlement_alignment_study.py:65-71,646-649`; `forbidden.py:72,131-143`). −1 for b2 (uncited `WEATHER_VENUE`, un-re-derived tick list). |
| Implementation specificity and feasibility | 15 | 14 | The runner is a named, strict-typed module with a responsibility table; `record_blocked` has a home; the window has one named helper; the command block carries every `required=True` flag. −1: the wrapper's invocation contract collides with AUD-10's emission, leaving a real cross-item decision unresolved (09-5). |
| Acceptance criteria and validation quality | 20 | 18 | B1–B18 objective; B17 now targets the component that builds the vector; B18 pins the split from both sides; B9 is two-way; B14/B16 are real contracts. −2: **B18 as written will fail once AUD-10 lands** (09-5). |
| Autonomous operation, failure handling, recovery | 15 | 14 | Every failure branch now has an owner in Python and is unit-testable; `ASOS_CACHE_EMPTY` keeps the day queued; unreadable-work-list ≠ empty-queue; crash recovery, duplicate-key hard error, skip-not-kill flock, own-cgroup OOM, timer gated on a non-`BLOCKED` row. −1: a persistently empty cache never escalates although the shipped path is one call away (b1). |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Mechanism-vs-edge separation on two independent grounds; deferred driver change named with an owner and mirrored in AUD-10; PREREG barrier, permit path and NO-SEND untouched; abandonment criterion with a stated adjustment; the IEM-map constraint recorded as a dependency rather than absorbed. No defect found. |
| **Total** | **100** | **95** | |

## Required changes to reach 100
1. Restate B18's invocation clause as a property and name AUD-10's appended wrapper line, identically
   in both plans (09-5).
2. Escalate N consecutive `BLOCKED` rows through the shipped alert sink, with a criterion — or accept
   the stall explicitly with an owner (b1).
3. Cite `WEATHER_VENUE` and re-derive the timer-tick list (b2).

## Blockers (recorded separately; not scored)
- **Evidence/data availability (build):** whether the settlement-alignment cache holds ASOS rows for
  the target climate day (`DEFAULT_LOOKBACK_DAYS = 3`). Correctly measured at §7 step 3 *before* the
  runner is built, both outcomes pre-defined, timer gated on a non-`BLOCKED` row. No plan change
  resolves it.
- **Deferred change with a named owner:** a challenger family cannot be replayed until
  `current_rung_hold_paper_replay.py` gains `--family-manifest`. Correctly excluded and mirrored in
  AUD-10 §12. This is why G-06's downstream half is not closed here.
- **Strategy lead:** R1 `trial_id` provenance; and whether a `MECHANISM_ONLY` replay result may be
  cited in a PREREG v3 §9 context (default taken: no). Both block a statistical reading, not the
  build.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._

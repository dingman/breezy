# AUD-09 — Review record (Round 6, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md
- Plan file sha256: 778a016cc21f73a15c5ebdf3e58c6b112db4059a4c638ab95352f4be6c531b08 (coordinator recorded 778a016c…)
- Round: 6 (delta) · Reviewer: architect (code-architect lens)
- Total: 100/100 · Readiness: READY

## Round-5 disposition, verified against the plan body and by literal comparison

| R5 defect | Claimed | Verified? |
|---|---|---|
| **b1 (MINOR, = AUD-10 c1)** — §6b.3 claimed the wrapper-contract *paragraph* was character-identical in AUD-10 §6b.4; it is not (different lead-ins and closings), and a self-identity claim that fails a literal diff devalues the drift-detection mechanism these plans rely on | ACCEPTED, first option | **FIXED, and the reviser's own check made it *more* correct than I asked.** §6b.3's heading is now scoped to the sentence, and — because a literal comparison showed the two copies are not byte-identical (AUD-10's sits inside a bullet, so it is indented and wraps differently) — the wording is *"the bolded property sentence below is identical **word for word** in AUD-10 §6b.4 (compare after whitespace normalisation: the two copies differ only in indentation and line-wrap, normalised sha256 ce5b6d1d…a26263) — the lead-in and closing around it are not, and are not claimed to be"*. **I re-compared the two sentences token by token myself** (AUD-09 `:558-561` vs AUD-10 `:546-550`): from *"every `"$PY"` invocation in `deploy/systemd/replay-daily-run.sh` is one of the named scripts"* through *"and the wrapper contains no JSONL parsing and no `record_blocked`."* they are word-for-word identical, and the only differences are the two-space bullet indent and the resulting wrap points. **The claim as now worded is literally true**, the qualification is verifiable by the stated procedure, and the normalised-hash anchor makes it re-checkable mechanically — which is strictly better than the prose claim I required. The property sentence itself is untouched, so **B18's binding did not move**. |

## "Nothing else moved" — checked

I re-read the regions around every edit and compared them against what I verified in round 5:
§6b.3's responsibility table and the two-step wrapper description (`:546-547`), the property sentence
and its closing (`:555-563`), §5's note naming AUD-10's sanctioned addition (`:159-165`), B18 and B19
(§8), §7 steps 8/10, §9's stall case and §10's push observable. All byte-consistent with revision 5
apart from the single scoped heading. §13 gained an accurate Round 5 / Revision 6 entry, and the
Revision 6 self-score is **deliberately unchanged at 95** with the reasoning stated — the right call:
a scoped documentation claim is a correction, not an improvement in capability, and scoring it higher
would be inflation. The five residuals it lists are all ones I have already classified as
blocker/other-item scope or as knowingly-bounded.

## Defects found in revision 6

**None.** I looked specifically for a regression from the edit (a heading that over- or under-claims,
a property sentence silently reworded, a B18 that no longer matches AUD-10's C19) and found none.

One **non-scoring note**, offered rather than required: §13's round-5 disposition row quotes the new
heading as *"character-identical"*, i.e. the intermediate wording, while the live §6b.3 text says
*"identical word for word … after whitespace normalisation"*. I do **not** score this, and the
asymmetry with the deduction I take in AUD-10 is deliberate: §13 is a dated historical narrative that
no implementer acts on, the plans carry a standing convention of leaving those rows as written, and
the binding text is quoted in full one page earlier. AUD-10's deduction is for a **live** cross-
reference that sends a reader to sections which do not support the claim. If the coordinator wants
the record perfectly self-consistent, the one-line fix is to quote the final wording in both §13 rows.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | The census, the scheduled runner, the machine-readable result and the ASOS producer are all in scope and specified; SP-4 folded **with** its blocker; §6c bounds the item to step 6. The two residual gaps (family dimension; `run_weather_strategy_backtests.py`) are other-item scope with named owners — blockers, not deductions. |
| Technical correctness and evidence grounding | 20 | 20 | The round-5 deduction is discharged: the identity claim is now literally true as worded, verified by my own token-level comparison. Everything else I checked across rounds 3–5 remains exact (`pyproject.toml:68,159-189`; `sites.py:135-148,403-414`; `structural_dead_stop.py:148-155,237`; `paper_replay.py:181`; `settlement_alignment_study.py:65-71,646-649`; `run_weather_strategy_backtests.py:352`; the per-unit timer tick list, which I re-derived independently). |
| Implementation specificity and feasibility | 15 | 15 | The runner is a named strict-typed module with a responsibility table; `record_blocked` and `climate_day_utc_bounds` have homes; every `required=True` flag is in the vector; the wrapper's contract is a property over a named set, so the AUD-10 implementer has no decision left to resolve. |
| Acceptance criteria and validation quality | 20 | 20 | B1–B19 objective. B18 survives AUD-10 landing and still fails an unnamed fourth invocation; B19 pins the stall escalation from four sides (fires once, does not repeat, resets, cannot fail the run); B14/B16/B17/B9 unchanged and sound. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Every failure branch owned in Python and unit-testable; `ASOS_CACHE_EMPTY` keeps the day queued; unreadable-work-list ≠ empty queue; crash recovery, duplicate-key hard error, skip-not-kill flock, own-cgroup OOM, timer gated on a non-`BLOCKED` row; and the one mode unit state cannot express now escalates on its own. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Mechanism-vs-edge separation on two independent grounds; deferred driver change and IEM-map constraint named with owners and mirrored; AUD-10's wrapper line named as scope owned elsewhere rather than absorbed; PREREG barrier, permit path and NO-SEND untouched. |
| **Total** | **100** | **100** | |

## Required changes
None.

## Blockers and notes (recorded separately; not scored)
- **Evidence/data availability (build):** whether the settlement-alignment cache holds ASOS rows for
  the target climate day — measured at §7 step 3 before the runner is built, both outcomes
  pre-defined, timer gated on a non-`BLOCKED` row. No plan change resolves it.
- **Deferred change with a named owner:** `--family-manifest` on the replay driver; mirrored in
  AUD-10 §12 and now also in AUD-10 §11's compound-limit paragraph.
- **Strategy lead:** R1 `trial_id` provenance; and whether a `MECHANISM_ONLY` result may be cited in
  a PREREG v3 §9 context (default: no). Both block a statistical reading, not the build.
- **Knowingly bounded residual (agreed):** a 30-day stall produces one `BREEZY_REPLAY_STALLED` alert
  rather than a standing signal. Stated in the plan; a standing-signal design is AUD-14's territory,
  not this item's.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._

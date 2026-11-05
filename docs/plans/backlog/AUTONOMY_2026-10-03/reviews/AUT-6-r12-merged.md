# AUT-6 r12 merged review (coordinator)

Scores: TBA 95 (READY), SFH 91 with one HIGH. The final score is 91, so the plan goes to r13.

## HIGH

### AG1: #16 input (SFH H1, TBA M)
**Coordinator ruling.** #16 consumes AUT-4's existing C4 HEALTH verdict `eval_replay_path` on the champion. AUT-4 r6 defines it in §3.11 and at lines 111, 274 and 370. It carries admitted days, exclusions by reason, parity results and the closure sha, and it is written on every `eval_offline` run (line 151). Do not read a D-1 report file; AUT-4 does not produce one.

**Before AUT-4 is live.** `NO_INPUT` is expected until the AUT-4 `eval_offline` producer is live. ETA: AUT-4 r6, earliest 2026-11-23.

**Escalation**
- Escalate if no `eval_replay_path` verdict newer than 26 h exists once either condition holds:
  - the C4 store holds any `eval_offline` verdict (the producer is live); or
  - `AUT4_REPLAY_EXPECTED_BY` (a pinned date, the AUT-4 ETA plus 7 days) has passed.
- The escalation path is WARN, then CRITICAL after 3 days.
- A missing C4 directory after the producer has gone live is INTEGRITY.

**Staleness (SFH M1).** The verdict's tape day must equal D-1, and its subject sha must equal the current champion. Otherwise the result is `input_unreadable`.

Remove the D-1 report artefact and the contract request it implied.

## MEDIUM

### AG2: M4 symbol table (TBA M)
Name every symbol `evaluate_calibration_leg` pulls in: `Trial`, `ReliabilityBucket`, `reliability`, `CalibrationLeg`, `RELIABILITY_EPSILON`, `LEG_PASS`/`LEG_FAIL`, `MODEL_*`/`CLUSTER_*`, and anything else the read-only closure shows. Add an M1-style table with identity tests.

### AG3: episode binding (SFH M2)
The health pass binds a stage delivery record only when the record's `ts_ns` is at or after the episode's `first_ns`. The stage resets its record on a clean `deadline_hit=0` pass. Add a test.

### AG4: snapshot clustering (SFH M3)
WP6 verify-first (11) also records the maximum consecutive-unsettled run and gates on it: the maximum run must be below N.

## LOW
- **Advisory PASS suppression:** the suppression is bounded to one pass. State this.
- **`outbox_pending` fallback:** the dead-man is the cover. Cite it.
- **Unreadable journal date or InvocationID:** the fallback pages again. Add this as a test case.
- **M3 logger name:** `quantile_density` changes logger name; keep the old name as a literal. Note that M4 code moves under strict mypy.
- **M3 load timing:** M3 loads at the 16:50Z launch. State this.

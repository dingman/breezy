# AUT-5 r4: merged review (coordinator)

- Security scored it 91 (1 HIGH); TBA scored it 86 (2 HIGH). Final score 86, so the plan goes to r5.

## HIGH
- **Z1** [sec H, TBA H1, arch ruling]: the engine's 16:45 exec-store read.
  - Replace §3.3.12, R4-1 and every `immutable=1` and `probe_open_intent` use in the engine with the adopted errata **E-8** copy-snapshot. Also adopt **E-7**: the engine runs under bwrap, with the bind set, the credentials tmpfs and the positive and negative self-probe.
  - The engine never constructs `SqliteStateStore` or calls `probe_open_intent`/`intent_lock_is_free`.
  - Blocking states are OPEN or Corrupt. AMBIGUOUS does not exist; fix every reference to it.
  - The crash case with stale sidecars is now handled through WAL recovery on the copy. Remove the r4 INTEGRITY strand.
  - Add the E-8 and E-7 tests. Extend `test_engine_unit_sandbox_covers_every_writer` into a real bwrap probe and rename the parse-only part to `*_config_*`.
- **Z2** [TBA H2]: drawdown H0.
  - Exclude the partial day 2026-10-01 (first fill at 16:02Z).
  - Calibrate the limit at the upper 95% rate, using a day-level bootstrap or negative binomial (overdispersion). Run the power and inert checks at the lower bound.
  - State the outcome when no feasible limit exists for any m: refuse the pair and state in the ruling that HALT is inert.
  - Re-measure from the durable store at ruling time, never from a constant.

## MEDIUM
- **Z3** [coordinator ruling, cross-plan consistency with READY AUT-7]: the E-5 restorative RESUME **does** apply `RESUME_COOLDOWN_H`.
  - Reason: ARCH C5's RESUME row requires the cooldown, and E-5 waives budgets only. AUT-7 r5 applies it, and its outage bound is ≤48h00m.
  - Fix R4-2 and its tests.
- **Z4** [TBA]: the 27-day rule versus the 30-day all-zero start gate.
  - Define the window semantics so the two are consistent. For example, the start gate counts only rows older than the 27-day rule.
  - Fix the §6 ETA.
- **Z5** [TBA]: the dwell boundary.
  - Pin the instant definition (effective to effective) and the comparison (`>=`), and give it a non-zero margin. Otherwise define the dwell as ≥24h00 from the RESUME LAUNCH.
  - Add a boundary test.
- **Z6** [sec M]: no torn reads. E-8's fingerprint before and after the copy, under the flock, covers this. Add a test with a racing writer and assert that an INTEGRITY result never comes with a silent miss.

## LOW
- WP10: check the gap of about 10 s between step 3 exiting and the 16:45 pass; the flock must be released by 16:48:00 (E-8).
- Document that a same-day `stop_complete` survives a later same-day relaunch, and that this is intended.
- Run the sandbox tests in a real bwrap namespace, not on a scratch db alone.

# AUT-5 r5 — merged review (coordinator)

Scores: TBA 92 (1 HIGH), security 91 (1 HIGH). Final score 91, so the plan goes to r6.

## HIGH

### AB1 [security, verified by experiment: EXDEV under bwrap]
Demand-file archiving crosses two bind mounts (`registry/demand/` → `evidence/demand/`), so it fails under bwrap.

**Coordinator ruling:** keep the ARCH archive location (`evidence/demand/`), which AUT-6 reads. Archive by these steps:
1. Copy to `evidence/demand/.<name>.tmp`.
2. fsync, rename within `evidence/`, then fsync the directory.
3. Verify the archived bytes equal the source.
4. Unlink the source, then fsync `registry/demand/`.

Crash handling: if a crash lands between steps 3 and 4, the next pass finds an identical archive and unlinks the source, so the operation is idempotent. If the bytes differ, raise INTEGRITY.

Tests:
- `test_demand_archive_runs_inside_bwrap_namespace`, run in a real bwrap namespace.
- A crash-between-copy-and-unlink test.

### AB2 [TBA]
When the drawdown pair is infeasible or inert, handle it the way the zero-fill case is handled (coordinator ruling, consistent with the D1 precedent):
- The verdict is PASS, with `day_status=HALT_INERT` and `drawdown_used_frac=0`.
- The start gate admits it.
- A delivered daily WARNING is raised.
- The ruling states explicitly that the drawdown HALT is disabled.
- `policy.py` accepts null `limit`/`min_settled_real_money_fills` only when `halt_inert=true`, with a test.

## MEDIUM

- **AB3 [TBA]:** define "enough" as ≥14 complete days AND ≥`H0_MIN_RATE_FILLS` (=30) settled fills. A thinner sample is HALT_INERT under AB2. Re-run calibration weekly, with a decision date before stage S.
- **AB4 [TBA]:** the drawdown producer gates on AUT-2 `labels_consumable(marker)`, or moves to ≥15:00 and stays before 15:30. Add a test.
- **AB5 [security]:** set `AccuracySec=1s` on every launch-path and autonomy timer, with a unit test. This matches AUT-6 R-e.

## LOW

- **Write-authority table:** add the rows for `mkstemp`+`os.replace` writers (heartbeat, drill marker) and AUT-6's `deliver_with_proof` record writer. Use a shared `replace_atomic` helper.
- **`cache/` directory:** create it explicitly with mode 0700, not with `mkdir -p -m`.
- **E-5 wording:** align with AUT-7 r5 — C+2 only; outage measured from the C 16:50 LAUNCH as ≤48h00m; cite AUT-7's one-per-episode and `target_load_failed` predicates.
- **ETA instant:** pin which instant the start rule uses for the ETA. A charge-on-effect row at 16:50 is the recommendation.

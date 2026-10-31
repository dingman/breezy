# OPS-4 plan r2.1 — D15 delta (architect ruling 2026-10-31 ~14:05Z, HEAD 0c62697a)

Trigger: `breezy-quote-tape-ingest-frequent.timer` fires every 15 min (MemoryMax=6G, peaks to 4 GiB /
495 s at 09:45Z, 1.2–1.4 GiB at 20:15/20:45Z 10-30), so a literal D15 ("no heavy fire within
RuntimeMaxSec") has no feasible window on any day (only gap ≥1800 s is 16:15–17:15Z, inside
`CATCHUP_DENY_UTC` 16:07:30–17:10, constants.py:114-117, and against the 16:50Z boot).

Findings (architect, read-only): the measured peak is the unit's own cgroup `memory.peak`
(label_run.py:599-614, :641; `is_measure_unit` :430-438, refusal :913-915) — a concurrent ingest
cannot raise it. The `+ RSS` seam is 0 on the live host (:679), so the floor is a flat
MemAvailable ≥ 16 GiB read once at start (:917-920). 16 GiB is a plan number (constants.py:110,
`# V3`), not a measurement. Overlap can only lengthen wall time (false STOP, never false pass) and is
the production condition (14:15Z label slot overlaps ingest too).

## D15 (r3) — replaces plan_r2.md line 60

- Launch window 18:01–18:05Z, after the 17:40Z ROI/scorer run has EXITED and the 18:00Z ingest fire
  has exited; one window per day, ends ≤ 18:35Z (clear of the 20:15/20:45 outliers and 22:30 slots).
  Ingest fires MAY overlap (per-cgroup peak).
- Launch adds `-p MemoryMax=8G` (no MemoryHigh — it would throttle and hold the peak down). 8G is
  > 3× the 2.67 GiB D12-passing peak; an OOM kill or peak ≥ 7.2 GiB is a STOP either way.
- Headroom rule: MemAvailable ≥ 8 (label cap) + 6 (ingest MemoryMax) + 2 margin = the existing
  16 GiB floor. Read by hand after 17:45Z. Keep the lock, exit-window and disk ≥ 10 GB checks; DROP
  "no heavy fire within RuntimeMaxSec". Do NOT use the 16:15–17:15Z hole.
- Wall time (D16): record start/exit and the ids of overlapping ingest runs in the artefact. If STOP
  trips (1800 < 1.75 × wall) and an overlapping ingest ran > 90 s, rerun once the next day before
  re-deriving TimeoutStartSec. Two STOPs in a row is binding.
- Fallback: MemAvailable < 16 GiB at 18:00Z → S0 BLOCKED-ON-HEADROOM; smallest legitimate change is a
  V3 re-derivation of the floor (8 + 6 + margin) via a reviewed plan item. Never edit the constant
  or stop timers to make room.

Measured 13:42Z 10-31: MemAvailable 16.76 GiB, node RSS 448 MiB, / 610 G free, /mnt/storage 3.0 T free.
First candidate: 18:01Z 2026-10-31 (inside the 17:08Z cycle).

# MAKER-S2 W1 — feather bytes measurement (2026-10-20)

Coordinator measurement. Read-only, stat-only (no block-2 bytes read). Taken 2026-10-20, one day before the plan's 10-21 slot (a plan target, not a frozen date). S, E, E_max unchanged. No operator control involved.

## Procedure sources

- W1 procedure: `docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md:366-374`.
- C7 rule: `docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md:341`.
- Baseline: `docs/evidence/maker/STAGE0_REPLAY_2026-10-16.md:22` (preamble ≈7,800 s; scoring ≈7,400 s for 96 station-days).

## Catalog and instance walk

- Catalog root: `~/.local/share/breezy/catalog/quote_tape/polymarket_us` → `/mnt/storage/breezy/catalog/quote_tape/polymarket_us`.
- Instance = directory under `live/` (`src/breezy/persistence/feather_preflight.py:108` DEFAULT_SUBDIRECTORY, `:512` list_instance_ids).
- Bytes = recursive `*.feather` (`iter_feather_files`, `feather_preflight.py:497`).

## Labels (10-19 census, trigger `logs/check.log`, 90 instances)

- CLEAN 78.
- CORRUPT 5: 3543b049, 70261a13, 7f353f94, 887d2005, c230f4fc.
- EMPTY 6.
- LIVE 1: 3d5e9b3e (excluded).

## Bytes

- Cutoff epoch for B_run1: 2026-10-16T02:07:00Z = 1792116420.
- B_now = 375,678,316,568 B over 78 CLEAN.
- B_run1 = 331,347,335,632 B over 73 CLEAN (newest mtime ≤ cutoff).
- CLEAN instances past the cutoff (5):
  - eeb84acd 14.80 GB (10-16 09:00Z)
  - 8aec371e 13.84 GB (10-17 09:00Z)
  - 36dfb1ec 14.20 GB (10-18 09:00Z)
  - 0e82bf30 0.87 GB (10-19 06:33Z)
  - feab1995 0.63 GB (10-19 09:00Z)
- Caveat: B_run1 is reconstructed from today's CLEAN set. Run 1's own CLEAN set was not logged.

## Projection

- PREAMBLE_S = 7,800 × 375,678,316,568 / 331,347,335,632 = 7,800 × 1.133790 = 8,843.6 s.
- Stall alert = 1.5 × PREAMBLE_S = 13,265.3 s.
- Pace 1.6 n_eff/day; 34 / 1.6 = 21.25 → 22 dates from S=10-14; 4 stations.

| E | n_sd | SCORE_S | PROJ |
|---|---|---|---|
| 11-04 | 88 | 6,783.3 s | 15,626.9 s |
| 11-06 | 96 | 7,400.0 s | 16,243.6 s |
| E_max 11-15 | 132 | 10,175.0 s | **19,018.6 s** |

SCORE_S = 7,400 × n_sd / 96. PROJ = PREAMBLE_S + SCORE_S.

## Sensitivity (coordinator's, not the plan formula)

- Bytes grow ≈14.28 GB/day ≈ +336.2 s preamble/day.
- Run date E+3: 11-07 ≈ 22,015 s; 11-09 ≈ 23,304 s; 11-18 ≈ 29,105 s. All > 21,600 s.
- The Doc A §8 bench exception is therefore expected to be in play at the Doc B FINAL re-measure.

## DECISION (C7, taken 2026-10-20, ahead of the 10-24 slot)

- Rule: "project to 11-15" → PROJ 19,018.6 s > 0.8 × 21,600 = 17,280 s → **C7 must land**.
- Preceded by the W2(a) split (`scripts/analysis/maker_stage0_probe.py` = 398/400 lines).
- Build via TDD in worktree branch `backlog/s2-c7-prefilter-2026-10-20`.
- Full gate before merge.
- CODE_SHA re-record at Doc B FINAL with pre/post shas and bench numbers (delta §2.17).

## Invariants

- No block-2 bytes read (stat only).
- S, E, E_max unchanged.
- No operator control involved.

## Premise P check (2026-10-20)

Counts-only (`trigger_rows.jsonl`, `first_seen_ns`) and stat-only (newest `*.feather` mtime per instance under `live/`). No block-2 bytes read. Cutoff = 2026-10-12T12:00:00Z (epoch 1791806400), the value in delta r3.2 (`S2_second_look_plan_r3_delta_coordinator.md` §2 row 2.21). Assumption: `ts_init` ≤ the file's last write, so an instance last written before the cutoff cannot hold a definition or print listed after it. Clock skew is the only failure mode.

Trigger rows (16 = 4 stations × 4 days, S..10-17; all `reason = COVERED`):

| climate_day | station | first_seen_ns (ISO, UTC) | ≥ cutoff |
|---|---|---|---|
| 10-14 | LAX | 2026-10-13T10:00:13.336253Z | yes |
| 10-14 | MDW | 2026-10-13T10:00:13.335475Z | yes |
| 10-14 | MIA | 2026-10-13T10:00:13.334700Z | yes |
| 10-14 | SFO | 2026-10-13T10:00:13.337123Z | yes |
| 10-15 | LAX | 2026-10-14T10:00:13.859508Z | yes |
| 10-15 | MDW | 2026-10-14T10:00:13.858013Z | yes |
| 10-15 | MIA | 2026-10-14T10:00:13.857277Z | yes |
| 10-15 | SFO | 2026-10-14T10:00:13.860259Z | yes |
| 10-16 | LAX | 2026-10-15T10:00:13.929676Z | yes |
| 10-16 | MDW | 2026-10-15T10:00:13.928117Z | yes |
| 10-16 | MIA | 2026-10-15T10:00:13.927330Z | yes |
| 10-16 | SFO | 2026-10-15T10:00:13.930460Z | yes |
| 10-17 | LAX | 2026-10-16T10:00:13.998695Z | yes |
| 10-17 | MDW | 2026-10-16T10:00:13.996970Z | yes |
| 10-17 | MIA | 2026-10-16T10:00:13.996150Z | yes |
| 10-17 | SFO | 2026-10-16T10:00:13.999540Z | yes |

Result: earliest first_seen = 2026-10-13T10:00:13.334700Z, 22.0 h after the cutoff. All 16 rows are ≥ cutoff + 22 h.

Instances (`live/`, 90 directories):

- CLEAN post-cutoff (8; newest mtime ≥ cutoff): 47e3d9d7 (10-13 09:00Z), 0d5f0044 (10-14 09:00Z), 2b9746e1 (10-15 09:00Z), eeb84acd (10-16 09:00Z), 8aec371e (10-17 09:00Z), 36dfb1ec (10-18 09:00Z), 0e82bf30 (10-19 06:33Z), feab1995 (10-19 09:00Z).
- CLEAN pre-cutoff: 70 of 78 (78 − 8). The 78 CLEAN label is the 10-19 census (W1 :19); the 70 is by subtraction, not re-derived.
- CORRUPT pre-cutoff (4): 3543b049, 7f353f94, 887d2005, c230f4fc (mtimes 09-10 to 09-28). Excluded from the census regardless.
- CORRUPT post-cutoff (1): 70261a13 (10-19 03:22Z, 8.70 GB).
- EMPTY (6): 04a83cc0, 10551246, 1744b9cf, 1cdca371, 578e6ce1, 8a4b92e8. All pre-cutoff, 0 feather bytes.
- LIVE (1): 3d5e9b3e (10-20 00:37Z, 7.58 GB, post-cutoff, excluded).

Verdict: P HOLDS for CLEAN (70 of 70 pre-cutoff CLEAN instances precede every first_seen observed). Limit: the evidence covers the 16 rows S..10-17 only. Licensed days through E_max 11-15 are not yet observed, so C2 must refuse any pinned licensed row with first_seen < cutoff.

## Post-C7 projection (coordinator formula, recomputed 2026-10-20)

Prefilter keeps instances with newest mtime ≥ cutoff, all labels. At 10-20 that is 10 instances: 78.73 GB CLEAN (8) + 8.70 GB CORRUPT (70261a13) + 7.58 GB LIVE (3d5e9b3e) = 95.01 GB, i.e. 0.287 × B_run1 (331.35 GB, W1 :28). PREAMBLE_S = 7,800 × kept / B_run1; kept grows only through post-cutoff instances (pre-cutoff instances are rotated and immutable). SCORE_S = 7,400 × n_sd / 96 (W1 :49).

Growth rate: CLEAN bytes written since the B_run1 cutoff (10-16 02:07Z) = B_now − B_run1 = 375,678,316,568 − 331,347,335,632 = 44.33 GB over 3.93 days (to 10-20 00:19Z) = **11.29 GB/day**. The W1 rate of 14.28 GB/day (W1 :53) does not reproduce from these byte totals.

| rate (GB/day) | run (E) | n_sd | kept (GB) | PREAMBLE_S (s) | PROJ (s) |
|---|---|---|---|---|---|
| 11.29 | 11-09 (11-06) | 96 | 320.8 | 7,552 | 14,952 |
| 11.29 | 11-18 (11-15) | 132 | 422.4 | 9,944 | 20,119 |
| 14.28 | 11-09 (11-06) | 96 | 380.6 | 8,960 | 16,360 |
| 14.28 | 11-18 (11-15) | 132 | 509.1 | 11,985 | 22,160 |

Post-C7 sentence: at the observed rate, PROJ at E_max is ≈ 20,119 s (< 21,600 s), so C7 may suffice even for E_max; at the W1 rate it is ≈ 22,160 s (> 21,600 s). The delta's 16,800 s / 22,600 s figures are not reproduced by this formula. The E_max conclusion is rate-dependent and is settled by the Doc B FINAL re-measure, not by this projection.

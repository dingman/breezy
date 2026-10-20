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

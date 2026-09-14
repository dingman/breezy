# Archive table `P_HOLD_UPPER` beside `P_HOLD_LOWER` — S1 calibration (2026-09-14)

Spec: `docs/plans/NO_SIDE_EDGE_2026-09-14.md` §2, §4 S1, N2-4, R3-9.

## What changed

`scripts/analysis/mb_current_rung_edge_study.py`'s `ArchiveCell` gained a
`p_hold_upper` property, and `scripts/analysis/generate_current_rung_hold_archive_table.py`
now emits a second frozen map, `P_HOLD_UPPER`, beside the existing
`P_HOLD_LOWER` in `src/breezy/strategy/current_rung_hold/archive_table.py`.
Neither `P_HOLD_LOWER`'s values nor `CORPUS_SHA256` changed; `STUDY_GIT_SHA`
was regenerated against the commit that added `p_hold_upper`. No live path
(`decision.py` or any strategy code) was touched.

## Generator command

```
python scripts/analysis/generate_current_rung_hold_archive_table.py
```

Run from the repo root inside the worktree venv (`.venv/bin/python`), reading
the on-disk archive corpus at
`~/.local/share/breezy/archive/settlement-alignment-cache` (unchanged path,
unchanged corpus).

## Identity used

`P_HOLD_UPPER[k]` is the Wilson 95% UPPER bound on the same cell as
`P_HOLD_LOWER[k]`, computed from the SAME `wilson_interval(hold_count, n)`
call inside `ArchiveCell.p_hold_lower`/`.p_hold_upper` (one raw float pair per
cell, `archive_correction_probe.wilson_interval`), then quantised with the
same `Decimal(f"{v:.4f}")` rule used for the lower bound. A cell below
`N_MIN=90` (or otherwise illegal) is `None` in BOTH maps, since both
properties share the same `if self.n < N_MIN: return None` guard.

## Key counts and spread

- Key count (both maps): 240
- Defined cells (both maps): 240 of 240 — the current dense-station /
  archive-hour / width-margin grid has no below-`N_MIN` cell in this corpus
  (co-occurrence of `None` cells is additionally pinned on a synthetic
  `n=89` cell in `tests/unit/test_archive_table_upper_bound_2026_09_14.py`,
  independent of whether the real corpus contains one).
- `P_HOLD_UPPER[k] − P_HOLD_LOWER[k]` over the 240 defined cells:
  - min: 0.0420
  - median: 0.07585
  - max: 0.0922

## Shas

- `CORPUS_SHA256` (unchanged): `3b410fb9c0c9208c5afb5cd8de05789077aca93c71fd540ddae0607ad6f04d48`
- `STUDY_GIT_SHA` (new, the commit that added `ArchiveCell.p_hold_upper`):
  `c81052c7645a66d371e809cd3f0aecf628b88e1f`

## Diff shape

`git diff` on the regenerated `archive_table.py` touches only:
`STUDY_GIT_SHA`, the `Generated at (UTC):` timestamp, the module docstring
(documenting `P_HOLD_UPPER`), `__all__` (adding `"P_HOLD_UPPER"`), and the
new `P_HOLD_UPPER` block itself. No `P_HOLD_LOWER` entry and no
`CORPUS_SHA256` line is touched — verified by `git diff ... | grep '^-'`
showing no removed `P_HOLD_LOWER` key/value line.

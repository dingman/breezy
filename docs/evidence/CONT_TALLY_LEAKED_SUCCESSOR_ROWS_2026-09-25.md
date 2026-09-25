# pm_us_crh_cont family tally RUN FAILED — leaked pm_us_crh_v4 successor rows

**Date:** 2026-09-25
**Family:** `pm_us_crh_cont` (PREREG v3, continuous rung hold)
**Symptom:** `family-tally-v2-run.sh pm_us_crh_cont` logged `RUN FAILED` daily
(`family_tally_v2.log`), root cause an uncaught `FamilyBarrierRefusal` from
`breezy.settlement.family_barrier.assert_family_only` (`family_tally_v2.py`).

## Causes A/B — already fixed by `a693f54`

`family_tally_v2.py`'s three-part barrier (trial_id prefix, `climate_day >=
d0`, station census) does not bound the UPPER end of a row's `climate_day`.
Before commit `a693f54` ("feat(aud-05): score mixed-side family tallies and
scope the live counter", 2026-09-24 21:09:49 +0000), `score_live_trials.py`
wrote every REGISTERED family's own store subdirectory on each daily run
without bounding the write to that family's own `terminal_climate_day`
(`score_live_trials.py` ~1798, ~728). `a693f54` closed this by scoping the
write with `until_climate_day=manifest.terminal_climate_day`. Causes A and B
(the write-path defect) are therefore already remediated in code; this
document addresses the residual DATA left behind by pre-fix runs (cause C).

## Cause C — pre-fix runs already leaked successor-family rows into cont's store

`pm_us_crh_cont`'s own terminal climate day is 2026-09-19. `pm_us_crh_v4`
shares the same `trial_id_prefix` (`continuous_rung_hold/trial/`) as cont and
is the REGISTERED successor family (`d0_climate_day: 2026-09-20`). Three
daily score runs on 2026-09-22 and 2026-09-23 — all before `a693f54` landed
— wrote a v4-scoped row into `scored_trials/pm_us_crh_cont/` instead of (or
in addition to) `scored_trials/pm_us_crh_v4/`. Each such row's
`climate_day` (2026-09-21 or 2026-09-22) is after cont's terminal day, so
`assert_family_only` correctly refused the whole tally the instant it read
one of those rows — the barrier is CORRECT, uncaught defensive code, not a
bug to weaken.

## Read-only census (before remediation)

Directory: `~/.local/share/breezy/derived/scored_trials/pm_us_crh_cont/`

| file | rows | min day | max day | rows >2026-09-19 | rows <2026-09-12 (d0) |
|---|---:|---|---|---:|---:|
| scored_trials_20260916T152100393198478Z.parquet | 2 | 2026-09-15 | 2026-09-15 | 0 | 0 |
| scored_trials_20260916T152103088611358Z.parquet | 1 | 2026-09-15 | 2026-09-15 | 0 | 0 |
| scored_trials_20260917T141539174141881Z.parquet | 1 | 2026-09-15 | 2026-09-15 | 0 | 0 |
| scored_trials_20260922T141813262725103Z.parquet | 1 | 2026-09-21 | 2026-09-21 | **1** | 0 |
| scored_trials_20260922T141815297330996Z.parquet | 1 | 2026-09-21 | 2026-09-21 | **1** | 0 |
| scored_trials_20260923T141808170651261Z.parquet | 1 | 2026-09-22 | 2026-09-22 | **1** | 0 |

All three commit-`a693f54`-predating files consist of **exactly one row
each**, and that row's `climate_day` is strictly after cont's terminal day
(2026-09-19). No file contains a mix of in-window and post-terminal rows.
Every one of the three post-terminal rows was found, by content, in the
SEPARATE `pm_us_crh_v4/` store directory — same `trial_id`, `climate_day`,
`score_seq`, `pnl`, `settlement_basis`:

| leaked trial_id | cont file | v4 file it also lives in | pnl |
|---|---|---|---:|
| `continuous_rung_hold/trial/MIA/2026-09-21/...gte88lt89f^no.POLYMARKET_US` | scored_trials_20260922T141813262725103Z.parquet | pm_us_crh_v4/scored_trials_20260922T141814624599343Z.parquet | -0.1300 |
| `continuous_rung_hold/trial/SFO/2026-09-21/...gte66lt67f.POLYMARKET_US` | scored_trials_20260922T141815297330996Z.parquet | pm_us_crh_v4/scored_trials_20260922T141816645708220Z.parquet | -0.3700 |
| `continuous_rung_hold/trial/MDW/2026-09-22/...gte62lt63f^no.POLYMARKET_US` | scored_trials_20260923T141808170651261Z.parquet | pm_us_crh_v4/scored_trials_20260923T141809551895303Z.parquet | 0.8700 |

Since each leaked file's entire content is post-terminal and duplicated by
content in v4's own store, this satisfies option (a) of the remediation
decision: whole-file quarantine, no hand-edit of any row.

## Concurrency check

`systemctl --user list-units 'breezy-score*' 'breezy-family*'` showed only
the three `.timer` units in `waiting` state before the move — no
`breezy-score-live-trials.service` or `breezy-family-tally@*.service` was
active. The `mv` was executed under `flock -w 600
"$XDG_RUNTIME_DIR/breezy-studies.lock"`; it queued behind an unrelated
long-running nightly study already holding that lock and ran once the lock
was released, atomically, with no writer touching the `pm_us_crh_cont` store
concurrently.

## Remediation: quarantine (option a)

Moved (via `mv`, never deleted) to
`~/.local/share/breezy/derived/scored_trials_quarantine/pm_us_crh_cont_2026-09-25/`,
with a `README.txt` there giving this reason, the source path, sha256 of
each file, and a restore command:

| file | sha256 |
|---|---|
| scored_trials_20260922T141813262725103Z.parquet | `a99d1d4bc512e4b946e316db6688506e7057cd63f39fac3900decb8b280b8a83` |
| scored_trials_20260922T141815297330996Z.parquet | `29698e4711d89b36e6e20dc000ca27b3ea596304b815d191f2fa54bbf5c32bdd` |
| scored_trials_20260923T141808170651261Z.parquet | `03c8a9edd9024579189e718da5e5fe18e27cde1c3d99f3efde5e4c9f5e466736` |

Restore command (README.txt, verbatim):

```
mv ~/.local/share/breezy/derived/scored_trials_quarantine/pm_us_crh_cont_2026-09-25/scored_trials_20260922T141813262725103Z.parquet \
   ~/.local/share/breezy/derived/scored_trials/pm_us_crh_cont/scored_trials_20260922T141813262725103Z.parquet
mv ~/.local/share/breezy/derived/scored_trials_quarantine/pm_us_crh_cont_2026-09-25/scored_trials_20260922T141815297330996Z.parquet \
   ~/.local/share/breezy/derived/scored_trials/pm_us_crh_cont/scored_trials_20260922T141815297330996Z.parquet
mv ~/.local/share/breezy/derived/scored_trials_quarantine/pm_us_crh_cont_2026-09-25/scored_trials_20260923T141808170651261Z.parquet \
   ~/.local/share/breezy/derived/scored_trials/pm_us_crh_cont/scored_trials_20260923T141808170651261Z.parquet
```

`pm_us_crh_v4`'s own store directory was not touched — the duplicate rows
remain there in their correct family home.

## Post-check

Re-ran `scripts/analysis/family_tally_v2.py` for `pm_us_crh_cont` exactly as
`deploy/systemd/family-tally-v2-run.sh` invokes it (`--family --store-dir
--as-of --output --covered-listed-station-days --fill-source
--fill-since-climate-day`), reading the real (now-clean) store but writing
`--output` only to scratch, under `systemd-run --user --scope -q -p
MemoryMax=4G`:

```
--covered-listed-station-days 10   (from covered_listed_station_days_2026-09-23.json, most recent available;
                                     no *_champion_*.json artefact exists yet -- that naming was only introduced
                                     by a693f54 on 2026-09-24 and has not yet had a 14:15Z run produce one)
--fill-source ~/.local/share/breezy/state/exec_polymarket_us.sqlite
--fill-since-climate-day 2026-09-12
```

**Exit code: 0.**

Result: `row count: 4 (excluded: 1)` → admissible **n = 3**, pooled `k=0`,
mean ask `0.2633`, mean BE `0.2733`, Wilson `[0.0000, 0.5615]`. Verdict:
**CONTINUE** (fewer than one completed look so far). Structural-dead stop:
10 covered-listed station-days, 8 filled Takes, evaluable and not fired.

The 1 excluded row is `continuous_rung_hold/trial/MIA/2026-09-15/...
gte92lt93f^no.POLYMARKET_US`, excluded as a residual/scored contradiction
per the pre-existing, unrelated ruling
`docs/evidence/RULING_v3_admissibility_divergence_2026-09-20.md` (R1/R4) —
not part of this remediation.

### Comparison against the last successful 2026-09-16 artefact

`~/.local/share/breezy/derived/family_tally_v2_pm_us_crh_cont_2026-09-16.md`:
`row count: 3 (excluded: 0)`, pooled `n=3, k=0`, mean ask `0.2633`, mean BE
`0.2733`, Wilson `[0.0000, 0.5615]`, verdict **CONTINUE**.

The pooled statistics (n, k, mean ask, mean BE, Wilson bounds) are
**byte-identical** between 09-16 and today's post-quarantine run — the three
admissible rows are the same MDW(×2)/SFO(×1) 2026-09-15 fills in both. The
09-25 report additionally shows 1 row now excluded (raising `row count` from
3 to "4 (excluded 1)"), which is the unrelated 2026-09-20 residual-ruling
exclusion, not a quarantine artefact. **Conclusion: the quarantine removed
the three leaked post-terminal rows with zero effect on cont's legitimate
admissible sample or verdict**, and the tally now exits 0 instead of raising
`FamilyBarrierRefusal`.

### v4 cross-check

Also re-ran `pm_us_crh_v4`'s tally into scratch under the same
`systemd-run` sandbox (`--fill-since-climate-day 2026-09-20`, v4's own D0).
**Exit code: 0.** v4's own store (unaffected by this remediation) still
contains its rows, including the three that duplicate the quarantined cont
rows by content.

## Files touched by this change

- Quarantine move only (no repo source file modified):
  `~/.local/share/breezy/derived/scored_trials_quarantine/pm_us_crh_cont_2026-09-25/{*.parquet,README.txt}`
- This document.

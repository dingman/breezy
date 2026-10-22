# P1 latency preflight

Run date: 2026-10-22. Plan: `docs/plans/backlog/AUDIT_PATH_2026-10-22/P1_plan_r2.md` (r2.1 pins). Thresholds were not moved after the rows were read. The slip-0.02 cells were not compared to 1.96.

## Inputs

- New run (finished 2026-10-22): `/home/jon/.local/share/breezy/derived/replay/design/p1_latency/` (`summary.json`, arms `sharp`, `sharp_l1`, `sharp_l5`). `code_sha` `8de5ebd42aecc1a46a1e7f4da761b19afaf02b24`.
- Baseline: `/home/jon/.local/share/breezy/derived/replay/design/maker_nobid_sharp/sharp/positions.csv` and that run's `summary.json` (`code_sha` `eac99bd62baf75453ac129a3fea8f931931ea879`).
- Row filter: `stress_pass and win is not None` (`maker_design_score.py` `arm_stats`). A loser is `win is False` on any filled row, base (`filled`) or stress (`stress_pass`). `win is None` is counted, not treated as a non-loser.
- Markout tape: `/mnt/storage/breezy/catalog/quote_tape/polymarket_us/data/order_book_depths/<rung>`, read with `forecast_cheap_screen_wp7.read_rung_tape`. No other catalog parsing.

## G0

Same stress-pass set at (station, day, rung). Count 17. `sum_x` in `x_t0.0695_s0.01` is 1.96. Set diff is empty. Bid and X match on every shared key. The three base-only fills match the plan (MIA 2026-09-27 `gte91f`, MDW 2026-10-06 `gte76lt77f`, LAX 2026-10-11 `gte78f`).

| | baseline | sharp (L=0) |
|---|---:|---:|
| stress-pass and win not None | 17 | 17 |
| wins among those | 17 | 17 |
| sum_x `x_t0.0695_s0.01` | 1.96 | 1.96 |
| keys only on this side | 0 | 0 |
| shared keys with a different bid or X | — | 0 |

`code_sha` in the new `summary.json`: `8de5ebd42aecc1a46a1e7f4da761b19afaf02b24`.

## G1

| check | sharp_l1 | gate |
|---|---:|---|
| stress-pass and win not None | 17 | at least 10 |
| wins among those | 17 | — |
| sum_x `x_t0.0695_s0.01` | 2.01 | not a gate |
| filled rows, base or stress, with win False | 0 | none |
| rows with win None (all / filled base or stress / stress-pass) | 0 / 0 / 0 | counted |

No L=1 fill is outside the L=0 set. Stress keys: 17 shared, 0 added, 0 removed. Base keys: the same 20, including the same 3 base-only fills.

The sets match. X differs on two shared rows, and that is the whole 1.96 → 2.01 gap (+0.04 and +0.01). The position X uses the base-filled episode's bid.

| station day rung | L=0 bid | L=0 X | L=1 bid | L=1 X | what changed |
|---|---:|---:|---:|---:|---|
| MIA 2026-09-23 `gte90f` | 0.83 | 0.15 | 0.79 | 0.19 | The 0.054 s fill at 83¢ does not happen. Base fills later at 79¢ (6.554 s). Stress fills on a different episode at 76¢ (8.446 s). The cell uses 79¢. |
| MIA 2026-09-30 `lt82f` | 0.88 | 0.10 | 0.87 | 0.11 | The 0.498 s fill at 88¢ moves to 55.477 s at 87¢. Base and stress are that same episode. |

The other 15 stress rows are unchanged in bid and X.

## Survivors among the 4 sub-10 s base fills

`filled_ns_base − t0_ns < 10 s` on L=0. Same four episodes as the baseline, minimum 0.054 s. All four keys are in the 17. All four still stress-pass at L=1 (17 of 17 remain).

| fill | L=0 | at L=1 s | at L=5 s |
|---|---|---|---|
| MIA 2026-09-23 `gte90f` | 0.054 s, 83¢, base and stress | rung survives; the 0.054 s print does not (see G1) | same as L=1 |
| MIA 2026-09-30 `lt82f` | 0.498 s, 88¢, base and stress | rung survives at 55.477 s, 87¢ | same as L=1 |
| MDW 2026-10-07 `gte80lt81f` | 1.461 s base fill at 85¢; stress is a later episode at 924 s, also 85¢ | unchanged | the 1.461 s episode is gone; the 924 s episode fills base and stress. Rung still stress-passes |
| MDW 2026-09-27 `gte73lt74f` | 4.911 s, 81¢, base and stress | unchanged | dies (not base, not stress) |

## L=5 s and markout (report-only)

sharp_l5: 16 stress-pass rows with win not None, 16 wins, sum_x 1.84, mean X 0.115. Filled rows with win False: 0. win None: 0 / 0 / 0. Base fills: 19. The one stress key that leaves the L=0 set is MDW 2026-09-27 `gte73lt74f` (X 0.17). No new key. The same two MIA bid changes as L=1 are present.

Markout, L=1 stress fills only. YES mid is `(bid_0 + ask_0) / 2` on that rung's own Depth10. Start: last snapshot with `ts < filled_ns_stress`. End: last snapshot with `ts <= filled_ns_stress + 10 min` (the book in force; 0.4–84 s short of the stamp). A one-sided book (missing bid or ask on either snapshot) is dropped and counted.

| | |
|---|---:|
| stress fills | 17 |
| used | 17 |
| one-sided, dropped | 0 |
| missing book | 0 |
| mean YES-mid change | +0.941¢ |
| mean X of these 17 | 11.82¢ |

(The L=0 cell mean is 11.53¢.) Nine marks are up, five flat, three down (−3.0¢ to +8.5¢). This mean is biased adverse by construction: a fill is a buyer sweep print, so the mid is pushed up at the fill. Descriptive only. No p-value. Not a selection measure against X.

## Verdict

**PASS.** G0 and G1 both hold. P4 may start. G1 did not fail, so this screen does not end the maker programme.

## Risks

1. The model ignores queue growth during L, so the L=1 survivor count can be overstated. L=5 s and the markout are context only.
3. A PASS only says the fills are not a feed-skew artefact. The edge is tested only in P4.

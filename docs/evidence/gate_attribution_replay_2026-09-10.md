# Gate attribution — why current_rung_hold does not take (2026-09-10)

Whole-tape paper replay over 26 station-days with the per-gate diagnostics shipped in
`7627313`. Throwaway latch store (`work_catalog/latch.db`), never the live exec-state DB.
Replay drives the running max from lagged IEM ASOS while live uses NWS, so this is
NOT a faithful proxy for WHICH quote becomes the trial (replay: 6 takes / 26 days,
6/6 filled; live: 8 listed afternoons, 1 take, 0 fills; live SFO 09-05 took
`gte73lt74f` @0.28 where replay latched `illegal_cell` on `gte71lt72f` @0.33).
It IS the first measurement of which gate stops evaluation.

## Trial-layer outcomes (one latch per station-day)

| Outcome | Days |
|---|---|
| never reached `evaluate_decision` | 6 |
| **`illegal_cell`** | **11** |
| taken | 6 |
| `edge_below_break_even` | 3 |
| `observation_ambiguous` / `observation_unavailable` | 0 |

`in_window_no_running_max_yet` never fired: the strategy is not short of observations.

## Tick layer

Of in-window quotes failing the executable predicate (`0.05 < ask < 0.95` and
`size >= 1`, one boolean at `strategy.py` `raw_executable`), an analysis-side split
over 282,664 in-window quotes: **58.4% fail the size floor only** (empty/sub-lot
asks), 38.7% fail the price band only, 2.8% both. Empty asks, not the price band,
are the majority of non-executability.

## `illegal_cell` root cause — NOT a table gap; the registered take rule

Of the 11: **9 are interior width=0, m=1 cells** and **2 are open_lower (width=2)**.

- Interior m=1: the archive table `P_HOLD_LOWER` **has** `(0,1)` calibrated on every
  complete day (`_ARCHIVE_PROXY_CELLS`); PREREG v1 §2:38-40 pins that m=1 never
  trades live. The same derivation formula produces Takes on interior m=0 and
  open_upper, so this is not a slug/fencepost bug. MIA 09-06 lag-30 refused
  `illegal_cell` while lag-45 TOOK the same `gte90lt91f` @0.42 — lagged R toggling m.
- Open_lower: never built by the study (`generate_current_rung_hold_archive_table.py`
  :281-282, p_hold ≈ 0 by construction); live derives width=2 and refuses.
- Calibration population vs live: same stations (registry minus NYC), same hours
  (12..16 LST); dates 2021-01-01..2025-12-31 on proxy rungs vs live 2026-08-31..09-08
  on real ladders.

`illegal_cell` CONSUMES the latch (GL-3 ruling; `strategy.py` consume site), so each of
these 11 burned its station-day. Refusing is fail-closed by design (L-22).

## Bounded prize

Making `illegal_cell` a "normal decision" adds **0** trials — these 11 already are
trials. If m=1 were legalised (the table supports it): at most **9** additional Takes
on this sample (9/20 not-taken = 45% upper bound); whether any clears break-even at
the actual hour is **UNVERIFIED** (`hour_lst` is not in the latch). Open_lower cannot
become Takes without a new table AND a rule change. Rate on this sample: ≈1.6 illegal
station-days per calendar day, already spent.

Any change to what consumes, or to m=1 legality, is class (C) against `pm_us_crh_v2`
(L-34; v2 §2 freezes the take rule; the 240-cell table is sha-pinned). It belongs to
the v3 family under design, as an explicit registered hypothesis.

## UNVERIFIED
Logged `m_code`/`hour_lst`/`running_max` on the 9 interiors (m=1 inferred from 0
ambiguous); break-even clearance of those 9; replay-vs-live take identity (IEM vs NWS).

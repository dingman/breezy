# Card D G0 — design amendment r0 (holdout rule + 5-min product), 2026-10-31

Status: PROPOSAL for blind peer review (architect + prediction-market-reviewer). Not frozen. No look taken.
Authored by a Claude planner sub-agent (Grok 402, Codex model_not_found); landed verbatim by the coordinator.
Invariants: Nautilus immutable; `allow_short` False; no operator cap touched; `iem_cli_fetch.fetch` never
called; zero network; every experiment pre-registered, ONE look (L-34, `docs/core/LESSONS.md:182-184`).

## 1. What the holdout protects, and why

- Declaration: `DEFAULT_SPLITS.holdout_start = 2026-07-01` (`src/breezy/analysis/nbp_calibration.py:273-278`);
  the holdout "grows forward as labels accrue" and has no end date (`:236-240`).
- Purpose, stated in code: `HoldoutLeakError` = "A row on or after the sealed holdout start reached a fit,
  a fold or a score" (`src/breezy/analysis/multisource_blend_features.py:41-42`); `assert_pre_holdout`
  (`:380-385`). F13 rule: "rows on or after holdout_start are REFUSED by the fit, the folds, the scorer and
  the runner; open_holdout is never called" (`docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F13_prereg_blend_v1.json:12-13`).
  LAMP archive: "only days < 2026-07-01 reach a fit or a score" (`scripts/archive/lamp_archive_runs.py:58-60`).
- What it protects: the out-of-sample forward block on which the F13 forecast ladder (M0'..M3, CRPS vs
  CLI) and the NBP calibration will eventually be scored. The leak it prevents is a forecast model, a
  feature or a selection choice being fitted or tuned on rows that will later score it.
- Enforcement at the data layer: `scripts/archive/metar_routine_minute_probe.py:121-122`
  (`HOLDOUT_START = 2026-07-01`; plan refusal `:390-393`; docstring `:28-31`) and
  `scripts/archive/metar_routine_store.py:236-238, :285-286`. The routine-METAR store exists to feed the
  FB-R13 `obs_so_far` FEATURE (`metar_routine_minute_probe.py:6-9`). It is a defence-in-depth seal on
  a forecast-feature source, not a general ban on looking at calendar dates after 07-01.
- No LESSONS entry names the holdout (`grep -i holdout docs/core/LESSONS.md` = 0 hits). The binding
  lessons are L-34 (one look) and L-59 (dry runs on counts and timestamps only, `:314-316`).
- Precedent CONTRADICTION (for the architect): the ruling in `review_card_a_r0.md:27-28` says the seal
  covers DATES. But Card E read CLI truth for 2026-07-05..10-30 (`docs/evidence/STRAT_DESIGN_2026-10-31/card_e_cli_vs_twc.md:12`),
  Card A read Depth10 for 09-21..10-30, and P2 "spends days from the sealed S2 holdout … The evidence file
  says so" (`docs/plans/backlog/AUDIT_PATH_2026-10-22/P2_plan_r2.md:20-23`). Practice so far has treated
  the seal as fit/fold/score with disclosure.

## 2. The two candidate quantities

| | Routine-METAR minute (`metar-routine`) | 5-min ASOS cache (settlement-alignment) |
|---|---|---|
| Source | IEM asos.py `report_type=3` (`metar_routine_minute_probe.py:113,371`) | IEM asos.py `report_type=1` + `2` (`scripts/analysis/settlement_alignment_study.py:438-463`) |
| Coverage | 2021-01-01..2026-06-30; KLAX KMDW KMIA KNYC KSFO (`metar_routine_store.py:118-120`) | 08-27 → today. Fetch start 08-28/08-30 (`h4_preliminary_economic_read.py:150`, `ma_prelock_winner_ask_study.py:184`), padded 1 day earlier (`settlement_alignment_study.py:441`). Five sites via `load_sites` |
| Resolution | T-group tenths °C → whole °F via `round_half_up_f` | Whole °C per the architect. The repo reader keeps only rows with a T-group (`settlement_alignment_study.py:251-253`). Whether 5-min rows carry a T-group is UNVERIFIED (Q2) |
| Overlap with order-book recording (08-30..) | NONE | Full Card D window, 09-21..10-30 |
| Card D question it can answer | None. Its window ends before the recording starts | G0 (an observation exists in the hour); later, the running-max lower bound for the bid test |

Card D G0 text, verbatim (`prereg_r2.md:62-63`): "PASS: ≥ 90% of that denominator have a METAR max row
covering the hour. Coverage only. **Not an edge rate.** KILL: none. Below 90% is INCONCLUSIVE and the bid
test does not run." Design (`design_r2.md:227-228`): "≥ 90% of station-days that have a frame in the
hour also have a METAR max row for that hour." The data path named `metar-routine` (`design_r2.md:211`).
Yet the estimand already assumes "Integer °C maps through ×9/5+32 with no interior degree"
(`design_r2.md:206`). That is the 5-min product's resolution, so naming the cache aligns the data path
with the estimand.

## 3. Proposed rule (HOLDOUT-OBS-COVERAGE-1)

Card D may read, for climate days 2026-09-21..2026-10-30 only:
- R1. 5-min cache row TIMESTAMPS, through `load_recent_asos_rows` → `metar_temperatures` → `hour_coverage`.
  The artefact gets per-LST-hour coverage booleans only. No temperature value, running max or T-group
  value is written, logged or returned.
- R2. Depth10 frame presence in the LST hour, and the §4.0 own-order set (denominator trim only).
- R3. Nothing else. No CLI or settlement truth, no `settlement_truth`, no NBP/LAMP/MOS/PFM/blend output.
Remains sealed: every fit, fold, score and runner guarded by `assert_pre_holdout` and the F13 rule; the
`metar-routine` store and probe guards (byte-unchanged; never widened); `open_holdout` never called.
Future out-of-sample test stays possible: G0 tunes no forecast parameter and reads no forecast or label,
so the F13/NBP holdout score stays clean. A Card D output may not become a feature, threshold or
selection input to any forecast model scored on dates ≥ 07-01, unless that model is scored on a fresh
forward window that starts after this freeze. The artefact says it spent holdout dates for coverage
only (P2 precedent).
Thresholds — AMENDED, per the binding revival terms in `design_r2_1_deltas.md:41-47`:
- Grid = 5 stations × 40 climate days (HIGH only, Q4). Report grid, frame-days and obs-covered days
  separately.
- LST hour 10:00–11:00 from each station's `std_utc_offset_hours` (Pacific 10:00 LST = 18:00Z). The PDT
  shift is deleted.
- PASS = pooled ≥ 90% AND every station ≥ 70%. Stated rationale for the 90%: missing observations are
  plausibly weather-correlated, so ≤ 10% missingness bounds selection bias in the bid median.
- KILL: none. INCONCLUSIVE otherwise.
Freeze: Run 2 was never frozen (`prereg_r2.md:7-8` PENDING; `prereg_r2_1.md:3` "Run 2 is not
registered"). **Zero looks consumed.** The amendment is a NEW prereg, `prereg_card_d_g0.md`, with
`FREEZE_card_d_g0.txt`, frozen once after peer review. The bid test (`design_r2.md:233-237`) gets its own
later prereg. It reads temperature VALUES, so it needs an R1 extension ruled separately.

## 4. Implementation — reuse only (operator 10-21: never a new harness/evaluator/runner/unit)

- Host: `scripts/analysis/wp7b_market_as_forecaster.py` `main`. One new flag, `--g0-only`, branching
  before `collect` beside `--census-only` (`:1313-1324`). Same window constants as Card A
  (`wp7b_census.py:45-46`).
- Imported unchanged: `read_rung_tape` (wp7 `:860-923`), `load_sites`, `read_own_orders`
  (`wp7b_census.py:557`; D5 positive control), `load_recent_asos_rows` (`cli_basis_offer_gate_scan.py:495-536`),
  `metar_temperatures` (`settlement_alignment_study.py:240-273`), `hour_coverage`
  (`cli_basis_boundary_study.py:116-134`).
- Allowed new code: LST-hour frame-presence test, label arithmetic, a sha/one-look guard keyed to this
  prereg (Q5), atomic writer to `docs/evidence/STRAT_DESIGN_2026-10-31/card_d_g0.{md,parquet}`.
- Not used: `cli_basis_offer_gate_scan.py` `main`. Its tape default `:219-221` is stale; the recording
  has been on /mnt/storage since 10-19.
- Dry run (NOT a look; L-59 counts/timestamps):
  - Prints the own-order count and PC result, grid size, and frame-days per station.
  - For the cache, prints only file count and each station's min/max `valid`.
  - No per-hour coverage inside 09-21..10-30.
  - Zero writes and zero store side effects (mode=ro).
- Quantity characterisation before freeze (resolves Q2), on 08-27..09-20 only, outside the sample: T-group
  share and minute-of-hour histogram of the cached rows. Not gated; recorded in the prereg.

## 5. STOP alternative (stated honestly)

If the architect holds that the seal covers DATES:
- No rule preserves it. All PM.us recording is ≥ 08-30 > 07-01, so no Card D test is possible on any
  past window.
- Then mark Card D G0 MOOT (`design_r2_1_deltas.md:39`) and close Card D.
- Cost is small: the bid test's expected outcome is KILL (`design_r2.md:235-236`), and the PM.us prize
  is ≈ $0 at qty 1.
- The same ruling would also put Card E's CLI read (07-05..10-30) in question. Record that, don't bury it.

## 6. Open questions

- Q1 (architect): Is the holdout scope fit/fold/score (code + F13 text) or calendar dates
  (`review_card_a_r0.md:28`)? Reconcile with Card E and P2 precedent.
- Q2 (both): Do the cache's 5-min rows carry a T-group? If not, `metar_temperatures` drops them, and G0
  measures routine/special-METAR coverage instead. Settled by the 08-27..09-20 characterisation. Note the
  T-group regex differs between `settlement_alignment_study.py:97-99` and `breezy.ingest.iem_observations`
  (the L-13 parser).
- Q3 (architect): `load_recent_asos_rows` globs every `*.txt` in the shared cache. Do cached CLI products
  share that directory? If so, they must be shown to be discarded by the station filter, or excluded.
- Q4 (pm): HIGH only, or LOW too (running min)? KNYC hourly cadence: keep it in the grid or exclude it
  (the cli_basis precedent excludes it, `:237-240`)?
- Q5 (architect): Parameterise the `wp7b_census` freeze/one-look helpers (`:672`, `:696`, `:719-733`;
  this changes Card A's closed module) or write a ≤ 30-line local guard?
- Q6 (pm): Is the 90% + 70% rationale sufficient, or is G0 itself a coverage gate with P(PASS) ≈ 1 that
  should be folded into the bid test's prereg?

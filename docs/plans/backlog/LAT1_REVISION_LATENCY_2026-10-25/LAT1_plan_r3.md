# Implementation Plan r3: NBP Revision-Latency Study (LAT-1)

## Honest feasibility (read first)
- **Only one event per station-day can be traded.** The nominal permit opens at 16:50Z and lasts 10 h, so it closes at about 02:50Z.
  - A 01Z D event decides at about 02:12Z. Its 60 m exit (and even a 15 m exit plus the 30 m exit window) falls after 02:50Z.
  - A 13Z D−1 event is available at about 14:05Z, before the permit opens.
  - So only the 19Z D−1 event is executable. 01Z and 13Z become registered report-only strata. No permit change is proposed; that is operator-only.
- **Planning SD is σ = 0.12.** This is a mixture: interior-rung markout SD of 0.10-0.15, plus exits at the 30-minute fallback, plus missing exits.
  - Design effect 1.5. With LD-OBF and conditional-power (CP) futility, `n ≈ 0.192/δ²` takes for 80% power. That is `1.03·(1.96+0.84)²·σ²·1.5/δ²` with about 10% added for the futility loss.
- **Eligible rate.**
  - The ΔP filter at τ_primary keeps about 35%. This is an assumption; the τ report replaces it with real counts. The entry rules and permit then keep about 80%.
  - 4 stations × 1 event × 0.35 × 0.8 ≈ **1.1 takes/day** in Stage 2.
  - About 59 takes in the search corpus.

  | δ (net USD/take) | n (takes) | Stage 2 days |
  |---|---|---|
  | 0.02 | 480 | **about 435** |
  | 0.03 | 213 | about 195 |
  | 0.035 | 157 | about 143 |
  | 0.04 | 120 | about 109 |
  | 0.05 | 77 | about 70 |

- **Conclusions, stated plainly:**
  - δ = 0.02 cannot be confirmed in any horizon this plan should commit to: it needs about 435 days. Extending the cap to 180 days does not reach it, so the cap is set to 180 days for a different reason.
  - The **180-day cap (about 198 takes) confirms δ ≥ about 0.031 net**. The 120-day cap would reach only δ ≥ about 0.038.
  - An edge that clears costs by less than about 0.03 per take is undetectable here.
  - Net 0.03 needs gross about 0.095 against a round-trip cost of about 0.065. At τ ≥ 0.18 that means roughly half the revision still untransmitted after 5 minutes. That is plausible only if the lag is real and large, and it sits just under the 0.04 audit trigger.
- **Prize at qty 1:** about 1.1 × 0.03 ≈ $0.03/day. Scale depends on operator caps and L0 depth, and that decision is not in this plan.
- **Why run it anyway:** Stage 0 plus Stage 1 cost about 1 h of compute and can stop the programme cheaply. Stage 2 can only confirm a large lag. Choosing to run Stage 2 at all is a stated decision at the Stage 1 boundary, not a default.

## Overview
- **Question:** after a 19Z NBP cycle becomes available, does the D-market band price lag the revision enough that a qty-1 YES taker can enter at `available_at + L` and exit at the executable bid about 60 m later for a profit, net of two cent-rounded fees?
- **Stage 0:** mechanism gate, outcome-free. Its one kill rule is KILL-COST in difference-in-differences (DiD) form.
- **Stage 1:** pre-registered selection screen that picks at most 2 variants.
- **Stage 2:** LD-OBF on post-cutoff data, the only hypothesis test.
- **Report-only:** settlement PnL, the 01Z/13Z strata, and an exploratory maker arm.
- **Inputs:**
  - `.../scratchpad/lat_s1_result.md` and `lat_s2_result.md`
  - P2 evidence
  - Peer reviews `rev_lat1_{pmr,arch}.md` (r1) and `rev2_lat1_{pmr,arch}.md` (r2)

## Reused code (verified with codegraph; the r2 reviewer confirmed signatures)
- **pno_store, `src/` copy only** (`src/breezy/strategy/no_ladder_maker/pno_store.py`):
  - `_pinned` `:144`, `read_pinned(PartitionSource…)` `:186`
  - `build_chain` / `VectorChain.at` `:273-299`, `ladder_p_yes` `:239`
  - `STATIONS = (LAX, MDW, MIA, SFO)` `:49`
- **P2 script** (`scripts/analysis/p2_nbp_ask_murphy.py`):
  - `_NbpSource` `:614`. It is a private name, so it is imported explicitly and a test pins that import.
  - `cash_taker_fee_usd` `:180`
- **release_timing** (`src/breezy/analysis/release_timing.py`):
  - `ols_slope` `:192`
  - `day_block_bootstrap_slope_ci(events=EventObservation(day, regressor, change), n_boot, alpha, seed)`
  - `time_to_fraction_of_move` `:339`, `holm_reject` `:270`, `metar_offset_placebo_instants` `:425`
- **release_timing_b0:** `read_top_of_book` returns L0 price only, reads the whole instrument directory, and has no time filter, so scoping is done in memory. An empty side is NaN.
- **nbp_market_comparison:** `is_inside_nominal_permit` `:318`, `MAKER_THETA_CEILING` `:74`.
- **nbp_calibration:** `cluster_bootstrap_draws` / `percentile_interval`.
- **backtest_harness:** `backtest` `:1026`. `run_backtest` installs `install_order_guard`, which raises `NakedShortRefusedError`.
- **Maker simulator:** `maker_stage0_fill.simulate_station_day` `:200`, fed by `maker_stage0_events_build`. `DROP_REASONS` at `maker_stage0_fill_events.py:32` already includes `CANCEL_HARD` and `CANCEL_STALE`.
- **nbp_backfill:** requires `BREEZY_LIVE`, `BREEZY_USER_AGENT` and `--request-budget` on an apply run (`:621`).

## Requirements
- **R1. Events.** `e = (station, D, c)`, for the 4 pno_store stations only.
  - `ΔP_r = P_c(r) − P_prev(r)`, both from `ladder_p_yes` on the pinned artefact (sha `9c0b6d6e…`).
  - `P_prev = chain.at(cur.available_at_ns − 1)` and must have the same climate day D.
  - **Tradable stratum:** c = 19Z D−1.
  - **Report-only strata:** c = 01Z D, and 13Z D−1 against the 01Z D−1 lead-2 column. These are mechanism-only and never eligible for selection.
- **R2. Both signs.** `r+ = argmax ΔP` (when > 0) is the YES taker rung. `r− = argmin ΔP` (when < 0) is used for the mechanism and the exploratory maker only, because NO taker cannot be scored and `allow_short=False`. Ties break on the lower `rung_id`. All rungs with `|ΔP| ≥ τ` are a report-only secondary.
- **R3. Book basis.**
  - The as-of book at time t is the last Depth10 snapshot with `ts_init ≤ t`. The clock basis is `ts_init`; `custom_venue_clock_offset` is reported only.
  - **Missing** means either (a) a `QuoteTapeGap` record covers t, or (b) the heartbeat fails: no Depth10 or QuoteTick row on any instrument of that station's tape in `[t−300 s, t]`, which catches recorder zombies.
  - The age of an unchanged quote never makes it missing.
  - An empty side (NaN) means that side is missing. A mid needs both sides; otherwise the mid is missing for Stage 0.
- **R4. Primary metric: markout PnL.**
  - Entry is at the as-of ask at `t_dec = available_at_ns + L_ns + 1`.
  - Exit is at the as-of bid at the first instant `t'` in `[t_exit, t_exit + W]` where a bid exists. `t_exit = t_dec + X`, `W = 30 min`. The first candidate is `t_exit`, then each later snapshot's `ts_init`.
  - `pnl = bid(t') − ask − cash_taker_fee_usd(ask, t_dec) − cash_taker_fee_usd(bid, t')`.
  - **No bid in the window:** `bid = 0`, no exit fee, never dropped. The take is flagged `missing_exit`.
  - Reported: the PnL mix split into exit-at-`t_exit`, exit-in-window and missing-exit groups; a hold-to-settlement sensitivity; a one-tick-worse stress.
  - Entry ask missing or above 0.97 means no take, with the reason counted.
- **R5. Executability.** All of `is_inside_nominal_permit` at `t_dec`, at `t_exit` and at `t_exit + W` must hold. `cash_taker_fee_usd(ask, t_dec) is None` is a counted drop.
- **R6. Pinned design constants.**
  - `L_primary = 300 s`. Reachable with 60 s S3 HEAD polling plus permit and evaluation slack, independent of the current poll schedule.
  - `L_alt = 120 s`, `X_primary = 60 m`, `W = 30 m`.
  - Ledger lag is description only.
- **R7. τ.**
  - Computed **only from 19Z cycles that exist at the freeze**, from NBP data alone (no tape, no truth).
  - `τ_primary = max(0.13, q60(ΔP_{r+}))` and `τ_alt = max(0.18, q80)`.
  - The floor 0.13 follows from a round-trip cost of about 0.065 with half the move transmitted. The floor 0.18 leaves a margin over that.
  - The prereg records the q60 and q80 values, whether each floor binds, and the event counts at and above each τ. Those counts replace the 35% assumption in the power section.
- **R8. Invariants.**
  - Nautilus is not modified. `allow_short=False`.
  - No live-enablement, permit or NO-SEND change. Operator caps are never assigned.
  - No safety, settlement or contract test is weakened.
  - `nbp_shadow_parity*` is untouched.
  - One heavy job at a time. Basetemp is `<tree>/.pytest-tmp/`.

## Phase P: before the freeze (outcome-blind; no tape prices)
1. **Backfill.**
   - Command: `BREEZY_LIVE=1 BREEZY_USER_AGENT=<the configured project UA> nbp_backfill.py --start 2026-10-13 --end 2026-10-26 --apply --request-budget 84 --pace-s 1`. That is 14 days × 3 default cycles × 2 worst-case requests.
   - Launch after 03:00Z on 10-26, so the 01Z 10-26 cycle exists. Otherwise re-run that one item.
   - The 13Z and 19Z cycles of 10-26 feed only D = 10-27, which is excluded.
   - Avoid 16:30-17:10Z and the nightly studies.
   - Ledger cross-check: report the `|derived − ledger|` distribution with the source host. Where it exceeds 300 s, the ledger wins and the cycle is flagged. The 10-12 19Z ledger hole is a counted drop.
2. **Calibration provenance**, one time, cited in the prereg.
   - Find the commit that added `deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json` and the builder invocation behind it.
   - Show the builder used `DEFAULT_SPLITS` with `holdout_start = 2026-07-01`, and that its code reads no row with D ≥ that date.
   - Show there has been no refit since.
   - **Correction to the round-2 wording:** the coordinator asked for the artefact's creation date to be before 2026-07-01. It is not: the artefact was built about 09-30 (per its filename and P2). The testable property is that the fit data ends at or before 2026-06-30, which needs the builder code and splits, not a file date.
   - Code guard: `assert splits.holdout_start <= min(search D) − 1 day`, reading the `DEFAULT_SPLITS` object, not a copied constant.
   - If provenance cannot be shown, STOP.
3. **τ derivation:** `nbp_revision_latency.py --stage tau`, which reads only `derived/nbp` and the artefact.
4. **Code and RED→GREEN tests** on synthetic fixtures. Real tape is touched only for a structural census: directory and day counts, never prices.
5. **Freeze commit.**
   - `docs/specs/PREREG_NBP_REVISION_LATENCY_2026-10-25.md`.
   - **Cutoff `C = 2026-10-27T00:00:00Z`.** If the commit lands later, C is the next 00:00Z.
   - `PREREG_SHA256` is pinned in the CLI.
   - Search corpus: D ≤ 2026-10-26 with every `t_dec < C`. Confirm corpus: D ≥ 2026-10-28. D = 10-27 is excluded and counted.
   - Domain sign-off is required before the prereg takes effect.

## Stage 0: mechanism gate (outcome-free)
- **Population.**
  - All strata and both signs are measured.
  - Each needs non-missing mids (R3) at every grid point used, over a fixed 180 m horizon. That horizon is truncated only by the next scheduled release.
  - D has not started at any of these instants, so no market can resolve inside the window.
- **Response.**
  - `y(τ1,τ2) = sgn·[mid(t_a+τ2) − mid(t_a+τ1)]`, on the grid {30 s, 1, 2, 5, 10, 15, 30, 60, 120, 180 m}.
  - `β` = `ols_slope`, with a CI from `day_block_bootstrap_slope_ci`, climate-day blocks, B = 20000.
  - Half-life from `time_to_fraction_of_move(fraction=0.5, min_move=0.01)`.
  - The ratio `F(τ)` is the only new statistic.
  - Diagnostic labels: ALREADY-PRICED (pre-release `β_DiD(−60m, 0)` per minute, CI above 0) and TOO-FAST (half-life < L).
- **Placebo.**
  - Generated by `metar_offset_placebo_instants`, at the event's minute-of-hour, with the releases list including 07Z. That uses the ledger time where available, otherwise the nominal `[07:55Z, 09:40Z]`.
  - **Post-filters** in `revision_latency.placebo_instants`: `[p−60m, p+180m]` contains no release (the upstream helper excludes symmetrically and works on UTC days); `local_standard_date(p) == D`; same instrument.
  - Expected 4-6 per UTC day. The 09:40-14:05Z window gives 0-1.
  - The placebo carries the real event's ΔP.
  - `y_DiD` = the event minus the mean of that same station-day's placebos.
  - DiD is also reported by placebo hour stratum, flagged as weak evidence because placebos sit in other parts of the day.
- **Covariate-adjusted β** (registered secondary): `y(0,60m)` regressed on `|ΔP|` plus the signed change in as-of observed temperature over `[t_a−60m, t_a+60m]`. Observations are as-of their F13 publication pin, `1923961500685 ns`.
- **The single kill rule, KILL-COST in DiD form.**
  - Traded subset: 19Z, `r+`, `ΔP ≥ τ_primary`, permit per R5.
  - `cost_e = cash_taker_fee_usd(ask, t_dec) + cash_taker_fee_usd(bid_est, t_exit) + ½spread(t_dec) + ½spread(t_exit)`, with `bid_est` = the as-of bid at `t_exit`.
  - `K = mean(y_DiD(L_primary → 60m) − cost_e)`, with a station-day clustered bootstrap CI (B = 20000). The wider of station-day and climate-day is used.
  - **KILL** if the upper 95% bound of K is below 0.
  - **INCONCLUSIVE** if there are fewer than 30 traded-subset events, fewer than 15 climate-day clusters, or a median below 2 placebos per station-day.
  - **INCONCLUSIVE-EXEC** if more than 25% of the traded subset has a missing mid at `t_exit`. This blocks KILL.
  - Otherwise **GO**.
  - Reported both before and after entry rule (b), with the share rule (b) removes.

## Engine parity (after the freeze, before any Stage 1 verdict)
- **Driver:** `scripts/analysis/nbp_revision_latency_parity.py` calls `backtest_harness.backtest(BreezyBacktestConfig(...))`.
  - Market data: Depth10 for the involved instruments.
  - Settlement prices from the venue settlement snapshot, falling back to fq-truth.
  - `allow_open_positions=True`, only so that missing exits can stay open.
- **Strategy:** `scripts/analysis/revision_latency_backtest_strategy.py`.
  - **It subclasses Nautilus `Strategy` directly.** It copies the `isinstance(self.clock, TestClock)` check into `on_start`, with its own `NotABacktestClockError`-style class. It has its own AST one-importer pin, with the only importer being the parity driver. It never imports `current_rung_hold.backtest_only`.
  - Input: frozen decision records (instrument, `t_dec`, `t_exit`, W).
  - At `t_dec` a time alert sends an IOC BUY, qty 1, at the as-of ask.
  - **Exit:** only when `cache.positions_open(instrument_id)` shows an open long. The order is an IOC SELL with `reduce_only=True`, sized to the filled quantity, starting at `t_exit` and retrying on each Depth10 until `t_exit + W`.
  - **An entry that did not fill sends no exit.** It is recorded as `PARITY_MISMATCH_UNFILLED_ENTRY`, never as a crash. This avoids `NakedShortRefusedError`.
- **Parity days:** the first 10 search days, in date order and on or after 2026-09-18 (post-drift θ), that have at least one primary take and on which every instrument has a `CONTRACT_EXPIRED` close and a 0/1 settlement price (needed by `assert_settlement_invariants`).
- **Asserts per take:**
  - Fill price and time equal the scorer's, for entry and exit.
  - **The engine commission on each fill equals `cash_taker_fee_usd` to the cent.**
  - A missing exit means both sides are missing.
  - Depth consumed at L0 is reported.
  - Any mismatch stops Stage 1.

## Stage 1: pre-registered selection screen (search corpus, 19Z stratum only)
- **V0 (primary):** `L=300 s`, `τ=τ_primary`, `X=60 m`, YES taker on `r+`.
  - Entry rule (a): an as-of ask exists, is at most 0.97, and R5 holds.
  - Entry rule (b): `ask(t_dec) ≤ ask(t_a) + 0.5·ΔP`, meaning the market has not already moved.
- **Secondaries** (Holm over 4, reported): V1 `X=15 m`, V2 `X=180 m` (exit about 23:22Z plus W, inside the permit), V3 `τ_alt`, V4 `L=120 s`.
- **Takes:** one per (event, rung, variant).
- **Statistics.**
  - Mean net markout, with 95% CIs from `cluster_bootstrap_draws` (B = 20000, seed 20260929) under both station-day and climate-day clustering. The wider is used.
  - One-sided p-values reported: V0 at 0.025, V1-V4 with Holm.
- **Report-only:** the 01Z and 13Z strata, settlement PnL (venue snapshot, falling back to fq-truth, disagreements counted), all rungs with `|ΔP| ≥ τ`, 07Z, and the drop census with the outcome mix of drops. The outcome is used in the census only.
- **Qualifies:** point > 0, upper bound of the wider CI > 0, at least 30 takes, at least 15 climate-day clusters, missing-exit rate ≤ 25%, all leak asserts pass, and the pre-release placebo take (rule fired at `t_a−90m`, deliberate look-ahead, diagnostic only) has a point at most 0.5× the real one.
- **Audit triggers:** mean > 0.04, hit rate > 0.75, or mean/SD > 1.0.
  - Any trigger makes the variant **AUDIT-PENDING**. The programme is held open, never SCREEN-FAIL.
  - An independent leak audit then either clears the variant, which re-enters selection, or confirms a leak. A confirmed leak is fixed under a registered amendment, and that variant is excluded.
- **Frozen selection rule:**
  - If V0 qualifies: V0 plus the qualifying secondary with the highest lower bound.
  - Otherwise: the top 2 qualifying secondaries by lower bound.
  - If none qualify and none are AUDIT-PENDING: **SCREEN-FAIL**. It is recorded and the taker programme closes. Nothing is deleted.
- **Selection artefact:** `docs/evidence/NBP_REVISION_LATENCY_SELECTION_<date>.json` is committed. A following commit pins its `SELECTION_SHA256` in the Stage 2 CLI.
- **Go decision:** the coordinator records whether Stage 2 runs, given the Honest Feasibility reach (δ ≥ about 0.031).
- **Exploratory maker arm** (outside every family):
  - NO resting bid on `r−` via `simulate_station_day`. The selector cancels at `t_a+180m` or the next release, using `CANCEL_HARD` if its semantics are "cancel at a decided horizon" (`CANCEL_STALE` if they are not).
  - If neither fits, the arm is deferred and `maker_stage0_fill_events.py` is not edited.
  - Fee stress at `MAKER_THETA_CEILING`. Reports fill rate and 60 m adverse-selection markout. Never promotable.

## Stage 2: confirmation (the only hypothesis test)
- **Starting condition:** the Stage 2 CLI refuses to start without a selection artefact whose sha matches. Stages tau, 0, 1 and parity all refuse any D ≥ 2026-10-28, so no confirm-period price is read before selection.
- **Data:** a daily D−1 `nbp_backfill` with default cycles, the same env vars, budget 6, run under `systemd-run --user` with a stall watch, and the ledger cross-check.
- **Test:**
  - LD-OBF sequential, one-sided α = 0.025. Looks every 20 takes from 40. Maximum 180 days, about 198 takes.
  - Statistic: `z = mean/SE`, SE from the climate-day cluster sandwich.
  - Fixed-sequence gatekeeping: V0 at 0.025 first, then the second variant at 0.025 only if V0 rejects. If V0 was not selected, Holm on the two.
  - Futility: CP under δ = 0.03 below 0.05, at any look from n = 40.
  - The first-look boundary is about z ≈ 4, so early stopping requires a large effect. The day estimates are horizons, not expected stopping times.
  - Reaching the cap without crossing a boundary is **INCONCLUSIVE**, and the result is recorded.
- **Blinded nuisance re-estimate:** at n = 40, if `|σ̂ − 0.12|/0.12 > 0.25`, re-derive the δ the cap can reach with the same formula and publish it. α and the cap are unchanged.
- **Promotion on PASS:**
  - A shadow family manifest under `deploy/families/` through the autonomy transition path, run for at least 14 days.
  - The existing exit seam is armed.
  - Live trading only through an operator ruling. Caps are never touched.

## Leak and data guards (all fatal and tested)
1. `prev.available_at_ns < cur.available_at_ns`, and `prev.climate_day == cur.climate_day == D`.
2. `cur.available_at_ns + L_ns < t_dec_ns`, and `chain.at(t_dec_ns) is cur`. Otherwise the event is dropped as `superseded`.
3. Every book row used has `row.ts_init <= t` for its query time. Missingness is decided only by R3. There is no hour-of-day predicate, and a test greps for one.
4. `cur.available_at_ns >= cur.cycle_runtime_ns + MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]`.
5. `DEFAULT_SPLITS.holdout_start <= min(search D) − 1 day`, read from the object. The artefact sha is pinned. The provenance citation is present in the prereg.
6. Decision records are hashed before the truth join. Truth is opened only by `report_settlement()`. The hash must be unchanged at join.
7. Search: `D <= 2026-10-26` and `t_dec < C`. Confirm: `D >= 2026-10-28`. Every pre-Stage-2 CLI refuses D ≥ 10-28. `PREREG_SHA256` and `SELECTION_SHA256` pins are enforced.
8. `cash_taker_fee_usd(entry) is None` is a counted drop.
9. Placebo: same D, same instrument, no release inside `[p−60m, p+180m]`.
10. Census identity per variant: `population == takes + Σ drops by reason`.
11. R5 permit at `t_dec`, `t_exit` and `t_exit + W` for every eligible take.

## File-by-file plan
| Path | New/Mod | Content |
|---|---|---|
| `docs/specs/PREREG_NBP_REVISION_LATENCY_2026-10-25.md` | New | All rules, constants, τ report, provenance citation, cutoff C. This is the freeze. |
| `src/breezy/strategy/weather_common/revision_gate.py` | New | Pure, strategy layer: `revision`, `signed_bands`, `decision_instant`, `as_of_snapshot`, `is_missing(gap_records, heartbeat_ts, t)`, `first_bid_in_window`. |
| `src/breezy/analysis/revision_latency.py` | New | Pure, no Nautilus: placebo post-filters, `fraction_of_move`, the `kill_cost_did` statistic, guards, census identity. |
| `scripts/analysis/nbp_revision_latency.py` | New | `--stage {tau,0,1,2}` shell. `markout_pnl` via `cash_taker_fee_usd`. R5 permit. Explicit `_NbpSource` import. Sha pins. Address-space cap. One station-day at a time. |
| `scripts/analysis/revision_latency_backtest_strategy.py` | New | Direct `Strategy` subclass, copied TestClock check, own error class, open-long `reduce_only` exit, unfilled entry recorded as mismatch. |
| `scripts/analysis/nbp_revision_latency_parity.py` | New | Driver; asserts fill price, time and commission parity; reports depth consumed. |
| `tests/unit/test_revision_gate.py`, `test_revision_latency.py`, `test_nbp_revision_latency_cli.py`, `test_revision_latency_parity.py`, `test_revision_latency_backtest_strategy_importers.py` | New | Listed below. |
| `docs/evidence/NBP_REVISION_LATENCY_{TAU,PROVENANCE,STAGE0,PARITY,STAGE1,SELECTION}_*`, `docs/core/PROGRESS.md` | New/Mod | Evidence and backlog state. |
| `nbp_shadow_parity*`, `pno_store.py`, `maker_stage0_fill_events.py`, `nbp_backfill.py`, `current_rung_hold/backtest_only.py` | Unchanged | |

## Test strategy (RED first; RED→GREEN output kept)
- **revision_gate:**
  - Sign and magnitude; mismatched climate days refused; `prev.available ≥ cur.available` refused.
  - `r+`/`r−` tie-break, and the cases where none exists.
  - Strict `t_dec`.
  - As-of picks the last row ≤ t.
  - **A 2-hour-old unchanged quote with a live heartbeat is not missing. A gap record or a dead heartbeat is missing.**
  - An empty side gives a missing mid.
  - `first_bid_in_window` picks the first bid in `[t_exit, t_exit+W]`; none gives bid 0.
  - Planted future: a row at `t+1 ns` is never used.
- **analysis:**
  - A placebo whose window contains any release, nominal 07Z included, is rejected.
  - A placebo on another D is rejected.
  - `kill_cost_did` on synthetic data: kills when the upper bound is below 0, INCONCLUSIVE-EXEC above 25% missing, INCONCLUSIVE when n is too small.
  - Guards 1-11 each raise on a crafted violation.
  - Changing `DEFAULT_SPLITS` makes guard 5 fail.
- **cli:**
  - Two cent-rounded fees, with θ 0.06, None, 0.0695 at the schedule edges.
  - The missing-exit split is reported.
  - The permit check at all three instants.
  - **A 01Z event is never eligible.**
  - `PREREG_SHA256` and `SELECTION_SHA256` mismatches are refused.
  - Stage 2 without a selection artefact is refused.
  - Any pre-Stage-2 stage given D ≥ 10-28 is refused.
  - Census identity end to end.
  - The `_NbpSource` import pin.
  - τ uses only cycles with `available_at < freeze`.
- **parity:**
  - A synthetic fixture through `backtest_harness.backtest` gives equal fill price, time and commission to the cent.
  - **RED: an entry the book cannot fill gives `PARITY_MISMATCH_UNFILLED_ENTRY` and no SELL is submitted. No `NakedShortRefusedError` is raised.**
  - The exit is `reduce_only` and sized to the fill.
  - `on_start` refuses a non-TestClock clock.
  - An AST scan confirms the single importer.
  - Parity-day selection requires closes.
- **maker:** the selector cancels at the horizon with `CANCEL_HARD`/`CANCEL_STALE`.
- **Guards that must stay green:**
  - The existing A-5 test and the `current_rung_hold` one-importer test stay green and unchanged.
  - `lint-imports` is clean, run from the tree root.
  - The full `scripts/ci/run_tests_no_egress.sh` gate passes on the primary tree. Briefs name the whole-tree guards: exec import pin, `autonomy_*`, citation map, fee pins.

## Power (σ = 0.12, 19Z stratum only)
- **Assumptions** (all reported back, never tuned):
  - About 210 search station-days give about 210 19Z events.
  - τ_primary keeps 35% and the entry rules and permit keep 80%, for about 59 V0 takes. The τ report gives the real number.
  - Design effect 1.5.
- **Stage 1:** SE = 0.12·√(1.5/59) ≈ 0.019, so the screen MDE is about 0.054. The screen is a ranking device, not a test, which is why Stage 2 exists.
- **Stage 2:** see the Honest Feasibility table. 180 days is about 198 takes, reaching δ ≈ 0.031. 120 days reaches δ ≈ 0.038. δ = 0.02 is out of reach.
- **Futility cost:** using CP < 0.05 under δ = 0.03 loses about 5% relative power, which is already in the 10% inflation.
- **Stage 0:** about 210 19Z `r+` events plus about 210 01Z events for the mechanism. KILL-COST rests on about 70 traded-subset events before rule (b): SE ≈ 0.12·√(1.5/70) ≈ 0.018. It kills only clear futility.

## Trade-offs
| Decision | Chosen | Why |
|---|---|---|
| Metric | Markout, with W fallback | Outcome-free, much smaller σ than settlement, and tests the lag directly. W keeps a quiet-book exit from being turned into a −0.4 loss. |
| Missingness | Gap records plus heartbeat | The tape is event-driven, so quote age says nothing about liquidity. |
| 01Z handling | Report-only | The permit excludes it. Any permit change is operator-only and not proposed. |
| Kill rule | One KILL-COST in DiD form | A single, unambiguous population; a slope-vs-break-even comparison was not comparable with profit. |
| Implausible result | AUDIT-PENDING | A large real lag must not close the programme. |
| Stage 2 cap | 180 days | It reaches δ ≈ 0.031. Not running Stage 2 is the stated alternative at the Stage 1 boundary. |
| Parity strategy | Direct `Strategy` subclass | Keeps the existing one-importer pin intact. |

## Risk register
- **Underpowered by design for δ < 0.03** (High). Stated in Honest Feasibility. Stage 2 is a conscious decision at the selection boundary.
- **Common-information confound** (High). Covariate β, pre-release placebo take, forward confirmation. A PASS means the trade is profitable, not that the market lags this file.
- **Hour-of-day leak recurrence** (High). Guards 3 and 9, the grep test, absolute ns.
- **Thin evening books** (Medium). W fallback, missing-exit split, INCONCLUSIVE-EXEC.
- **σ misestimated** (Medium). Blinded re-estimate at 25% deviation, with the reachable δ republished.
- **Engine and scorer fee divergence** (Medium). Per-fill commission parity, post-drift parity days.
- **Write-capable delegate** (Medium). Invariants repeated in every brief, read-only by default, the coordinator re-runs the gate.

## Compute and memory budget
- Stages tau, 0 and 1 each run under `systemd-run --user -p MemoryMax=10G -p LimitNOFILE=524288` with an 8 GiB address-space cap.
  - One station-day at a time.
  - 10-30 min each.
  - Never alongside nightly studies. A stall watch is armed in the launch turn.
- Parity: 10 engine days, about 1 h.
- Backfill: 84 requests, paced.
- Disk: at least 10 GB free. Basetemp is removed after EXIT is read.

## Success criteria
- [ ] Backfill, provenance and τ reports complete. Prereg committed and signed off. C and the sha pin enforced.
- [ ] RED→GREEN kept. `lint-imports` clean. Full gate EXIT 0. A-5 and current_rung_hold importer tests unchanged and green.
- [ ] Stage 0 verdict, parity PASS (price, time, commission), Stage 1 table and selection artefact, published in that order.
- [ ] Stage 2 starts only with a sha-matched selection artefact, on confirm data, with every look logged.
- [ ] No change to caps, enablement, the permit, the NO-SEND firewall, `allow_short`, Nautilus or `nbp_shadow_parity`.

---

### Issue → fix
| Issue | Fix in r3 |
|---|---|
| B1 staleness, bid=0, σ, re-estimate, cap | R3 gap records plus heartbeat; R4 W = 30 m first-bid exit, bid 0 only if none, missing-exit split; INCONCLUSIVE-EXEC above 25% blocks KILL; σ = 0.12; re-estimate at 25% relative deviation; cap 180 days reaches δ ≈ 0.031; δ = 0.02 needs about 435 days, stated |
| B2 permit at exit | R5 permit at `t_dec`, `t_exit` and `t_exit+W`; 01Z and 13Z report-only and never eligible; about 1.1 takes/day recomputed; no permit change proposed |
| B3 KILL-FUTILITY | Merged into one KILL-COST on the traded subset in DiD form, cost per event from `cash_taker_fee_usd` plus half-spreads |
| B4 τ floors, τ timing | Floors 0.13 and 0.18; τ from 19Z cycles that exist at the freeze; counts reported; power recomputed |
| B5 LEAK-SUSPECT vs SCREEN-FAIL | AUDIT-PENDING keeps the programme open; hit rate and mean/SD are audit triggers only |
| B6 fit end, confirm boundary | Provenance check (builder commit, `DEFAULT_SPLITS`, no refit) cited, with the creation-date wording corrected; guard reads the splits object; selection artefact committed and sha-pinned; Stage 2 refuses without it; pre-Stage-2 CLIs refuse D ≥ 10-28 |
| Arch 1 naked-short exit | Exit only against an open long from the cache, `reduce_only`, sized to the fill; unfilled entry recorded as mismatch; RED test |
| Arch 2 importer pin | Direct `Strategy` subclass, copied TestClock check, own error class, own AST importer pin |
| Arch 3 fee parity | Per-fill engine commission equals `cash_taker_fee_usd` to the cent; post-drift parity days |
| Arch non-blocking | Backfill env vars, `--request-budget 84`, launch after 03:00Z 10-26; placebo post-filters with expected counts; empty side means missing mid; parity days need closes; maker cancel via `CANCEL_HARD`/`CANCEL_STALE`; `_NbpSource` import pin |
| PMR non-blocking | CP threshold 0.05 with power loss stated; DiD by placebo hour stratum; z ≈ 4 first-look note; before and after rule (b) reported; depth consumed reported |

**Read the Honest Feasibility section first.** At σ = 0.12 with only the 19Z event tradable, 180 days can confirm a net edge of about 0.031 per take or more. δ = 0.02 is out of reach at any horizon this plan sets. The coordinator should decide whether to run Stage 2 at the Stage 1 boundary.

**Where r3 departs from what you asked:**
- **Artefact date.** You asked for a check that the calibration artefact was created before 2026-07-01. It was built around 09-30, so that check cannot pass. r3 instead proves the fit data ends at or before 2026-06-30, using the builder commit and `DEFAULT_SPLITS`.
- **Cap length.** You said to extend the cap to 180 days if δ = 0.02 needs it. It needs about 435 days, so 180 days does not get there. I set the cap at 180 days because that is what reaches δ ≈ 0.031, and I say so plainly.
# S3 — A1 loss-floor reachability for a maker mix

| Field | Value |
|---|---|
| ID | S3 |
| Title | A1 loss-floor reachability for a maker mix (parameterise the FQ floor tooling) |
| Revision | r1 |
| Date | 2026-10-12 |
| Status | DRAFT (needs peer review before any build) |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.2, §4 "Reachability pre-check", §7.8, §9.8 |
| Governing rulings | `docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md` (T2 route); `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md` (FWER, horizon, B-3 firewall) |

Hard invariants (restated, binding on every WP):
- Nautilus Trader is immutable.
- `allow_short` stays False.
- No safety, settlement, contract or NO-SEND test is weakened. Exact-set barriers may only be WIDENED by one reviewed row (L-12).
- No value is assigned to the max daily budget or max per position.
- Live enablement and `BREEZY_ORDERS_ENABLED` are not touched.
- No frozen PREREG/amendment JSON is edited. That includes `F5_prereg_v2_amendment_A1.json` and `_A0.json`. No pre-registered date moves.
- Stage 0 numbers are exploratory inputs, never promotion evidence.
- The NO-TRADE ruling stays in force.

## 1. Goal state (acceptance test)

`docs/evidence/maker/A1_REACHABILITY_<run-date>.md` exists, committed beside its machine-readable evidence `docs/evidence/maker/a1_reachability_mc_seed<seed>.json` (sha256 quoted in the .md). It states exactly one verdict:

- **`REACHABLE`**: at the Stage 0 fill-rate lower bound `f_lo`, every verdict cell's A1 floor returns `floor_mode = sqrt_boundary` (power class `edge_capable` or `gross_loss_tripwire`). Each cell also has its `alpha_star`, `c`, `t_min`, G3(−0.16/−0.08/−0.04) and T_low per epoch.
- **`UNREACHABLE — family not registrable`**: any verdict cell returns `unreachable_veto` or `freeze_blocked`. The artifact then names the binding cell and cause (`g1_unreachable` or `g3_floor`).

It also carries the full sweep table, f ∈ {0.1, 0.2, 0.3, 0.4, 0.5} × b ∈ {0.70, 0.80} × rungs ∈ {2, 1}, at exploratory replicates. The table is context only. The verdict is read from the binding run alone.

## 2. Entry criteria and STOP conditions

Entry, build half (WP0–WP3):
- Needs nothing from S1/S2.
- It uses synthetic station-day templates, so it reads no tape and spends no RA-13 B-3 corpus days (RA-13 §7 B-3).

Entry, verdict half (WP4 binding run):
- S2 Stage 0 has emitted the maker fill rate with a climate-date cluster-bootstrap 95% CI.
- S2 has emitted the realised bid distribution.
- S2 has emitted a §6.9 verdict that is not FAIL.
- S3 consumes only those summary numbers. Any firewall cost of computing them belongs to S2, not S3.

STOP conditions:
1. **S2 already stopped the family.** A Stage 0 fill rate below 0.1, or a §6.9 FAIL (spec §6 Stage 0), means WP4 is not run. The sweep stays as context.
2. **UNREACHABLE at `f_lo`.**
   - The maker family is **not registrable**.
   - The programme ends at this step.
   - S4 (exec resting-order path) and S5 (shadow and promotion tooling) are not started. No exec build happens.
   - The spec gets a v0.2 design-history row saying so (spec §4: "this file says so instead of being frozen").
   - The NO-TRADE ruling and the RA-13 2027-01-25 horizon proceed unchanged.
3. **`freeze_blocked` (s6_failed or refused templates).** Treated as UNREACHABLE unless a reviewer proves a builder defect. A defect may be fixed. The bar may not move.
4. **Forking-path guard.** The seed, grids, epoch length and verdict rule are committed in code before the binding run (same discipline as `e_proj` pinned at fe741c9d before the FQ Stage 0 run, ruling :29). Any post-result change to these is void.

## 3. Simplest direct path

The FQ floor engine already models exactly the maker's path:
- Its per-leg P&L is `x_piece(h, be) = h − be` (`fq_loss_floor_mc_rows.py:180-183`).
- Same-ladder legs are mutually exclusive outcomes of one categorical draw (`fq_loss_floor_mc_draw.py:121-137`, `:238`).
- It resamples whole climate-date groups (`fq_loss_floor_mc_sim.py`, `simulate_family` loop).

So the direct path is:
1. Write a ~150-line maker template builder.
2. Thread a `mixes` tuple and epoch offsets through the engine. The FQ defaults stay byte-identical.
3. Call the unchanged `run_floor` once per sweep cell.
4. Read the verdict at Stage 0's `f_lo`.

No new engine, no NP bound run, no prereg checker change. Nothing heavier is justified (§3.2).

### 3.1 Which modules are FQ-specific and which are generic

| Module | Class | Evidence | S3 action |
|---|---|---|---|
| `fq_loss_floor_mc_draw.py` (prepare_day, advance_prepared, critical_values) | generic | path model works on any `StationDay` of `Leg`s | reuse unchanged |
| `fq_loss_floor_mc_sim.py` (simulate_family) | generic | resamples date groups; per-station-day keep thinning | reuse unchanged (`p_keep = 1`, fills encoded in templates) |
| `fq_loss_floor_mc_solve.py` | generic | grid c, crossing rates | reuse unchanged |
| `fq_loss_floor_mc_rows.py` (Leg, StationDay, make_leg, apply_mix, h1_win_probability) | generic | `apply_mix("M-no")` keeps NO legs (`:249-256`) | reuse unchanged |
| `src/breezy/analysis/fq_loss_stop_core.py` / `_clock.py` | generic, production | `ALPHA_FLOOR_GRID (0.10,0.20,0.30)` `:47`, `G3_FLOOR_MULTIPLIER 2.5` `:49`, `T_MIN_GRID` `:51`, `first_crossing` `clock.py:99`, `step_clock` `:114` | reuse unchanged; these ARE the bar |
| `fq_loss_floor_mc_gate.py` | generic logic, FQ dates | `DEFAULT_FREEZE` `:57`, `HORIZON` `:58`, absolute `_EPOCH_FIXED` `:60-64`, `epoch_grid` `:151-153` | add relative epoch offsets (WP2) |
| `fq_loss_floor_mc_engine.py` | generic, FQ mixset | `MIXES = ("M-pool","M-yes","M-no")` `:56`, iterated `:236-241,:266,:352` | thread `mixes` param (WP1) |
| `fq_loss_floor_mc_report.py` | generic, FQ mixset | `MIXES` `:69`, G3 = min over MIXES `:182`, `:201-203` | thread `mixes` (WP1) |
| `fq_loss_floor_mc_e2.py` | generic, FQ mixset | `_MIX_ORDER` `:19`, missing-mix check `:112` | thread `mixes` (WP1) |
| `fq_loss_floor_mc_outer.py` | generic, FQ mixset | imports `MIXES` `:100-112` | thread `mixes` (WP1) |
| `fq_loss_floor_mc.py` (CLI, `_world`) | **FQ-specific** | Kalshi candles pool, `load_pool`, `mc_pool_days`, F5 pins, `DEFAULT_FREEZE` `:189-226` | not used; a maker CLI sits beside it |
| `fq_loss_floor_mc_rates.py` | **FQ-specific** | take-rate bisection on the FQ take rule (`plan_floor_rates`) | not used (rates come straight from f) |
| `fq_loss_floor_np_bound.py` | **FQ-specific** | `_EVIDENCE` `:85`, `_MIXSET` `:94`, RuntimeError drift pins `:147-150` | not run (§3.2) |
| `fq_loss_floor_np_stat.py` | generic, FQ pins | `E_PROJ` `:77`, `REACH 0.30` `:80` | not run |
| `prereg_amendment_check.py` | **F5-specific** | `_HORIZON_CLIMATE_DAY` `:150`, F5 filenames `:66`, evidence under `docs/evidence/f5/` | not touched; a maker prereg checker is S5/prereg scope |
| `fq_kill_power_report.py` (A0) | **FQ-specific** | `_DATA_ROOT` Kalshi `:89`, `AMENDMENT_ID` `:79` | optional WP5 report row only |

### 3.2 Why no new engine, and the code lines that block reuse today

Nothing in the path model blocks a maker mix. What blocks it is the hard-coded FQ mixset and dates:
- **`fq_loss_floor_mc_report.py:182`.** `scores[t_min] = min(power(-0.16, mix, n_cal, t_min, solved) for mix in MIXES)` and `:201-203` take G3 as the minimum over `("M-pool","M-yes","M-no")` (`fq_loss_floor_mc_engine.py:56`). On an all-NO world, `prepare_mix_groups(..., "M-yes")` drops every leg (`rows.py:255`), so the M-yes cell has zero ticks and G3 = 0. That is below 2.5·α, so the run returns `unreachable_veto` **by construction, not by evidence**. WP1 fixes this by passing `mixes`, never by changing the bar.
- **`fq_loss_floor_mc_gate.py:153`.** `epoch_grid` returns `{freeze, 2026-11-01, 2026-11-15, 2026-12-01}`. For any maker anchor after 2026-12-01, the fixed epochs precede the freeze. WP2 adds offsets.

The NP bound (D1) is not run. In the FQ ruling, D1 decided only whether a *replacement* floor (A1b) could exist after A1 vetoed (ruling :19, :29). Under this programme an A1 veto ends the family outright (STOP 2), so D1 cannot change any decision.

## 4. Path model, statistic, pass bar, α allocation

### 4.1 Maker path model (one leg = one filled resting NO bid, qty 1, held to settlement)

- Break-even:
  - `BE = b + fee(b)`, with `fee(b) = θ·b·(1−b)`.
  - θ = 0.0695 (F5 design `theta`; spec §2). This is the taker coefficient.
  - A maker rebate or zero maker fee is **not** modelled. `PolymarketUSFeeModel` refuses rebates until a real maker fill is observed (`src/breezy/adapters/polymarket_us/errors.py:305` `MakerRebateUnmodelledError`; `src/breezy/strategy/weather_common/costs.py` module doc).
  - Spec §6.7 already uses "maker coefficient = taker coefficient" as its stress case.
  - If S2 reads a lower maker coefficient from the wire, it may be reported as a sensitivity row only. The verdict uses θ = 0.0695.
- P&L per leg:
  - win (rung settles NO): `+(1 − b) − fee = 1 − BE`;
  - loss (rung settles YES): `−(b + fee) = −BE`.
  - Correction to the brief's "loss = −bid": the fee is paid at fill in both outcomes (spec §3: EV = w − (b + fee)). This is exactly `x_piece(h, BE)` (`rows.py:180-183`).
  - Legs are built as `make_leg(rung, "no", BE, price=b)` (`rows.py:76-91`).
- At most 2 legs per station-day, on distinct rungs of one ladder, mutually exclusive in loss:
  - `prepare_day` enumerates `len(legs)+1` categorical outcomes, one per rung settling YES plus "none" (`draw.py:131-137`). So two NO legs can never both lose.
  - H0 masses are the BE-implied YES probabilities `1 − BE` per leg (sum ≤ 0.6 on the grid).
  - H1(δ) uses `h1_win_probability = BE − |δ|` (`rows.py:310-311`). At b = 0.70, δ = −0.16, the YES masses sum to 0.89 < 1, so the categorical H1 holds.
  - b < ~0.645 (BE < 0.66) would push the YES masses past 1 and trigger the Bernoulli fallback (`draw.py:216`), which breaks exclusivity. So the grid floor is 0.70, and `h1_bernoulli_fallback` share must be 0. WP3 asserts this.
- Fills and listing:
  - Per climate date, each of 4 stations (LAX, MDW, MIA, SFO) is listed with probability 0.91 (spec §9.15).
  - A listed station-day carries `k ∈ {2, 1}` candidate rungs. Each fills independently with probability `f`.
  - A station-day with no fill is absent.
  - Fills are drawn **in the template**, so `simulate_family` runs with `p_keep = 1`. `FloorConfig` gets `take_rate_lower = lambda_pool = r_sd·lambda_sd` (realised fills/date), which makes `keep_probability` (`gate.py:129-133`) exactly 1. T_low then counts ticking station-days honestly (`gate.py:136-142`).
  - Why per-leg encoding: the engine thins whole station-days (`sim.py`, `p_keep` branch). Per-leg fills cannot go through that knob without misstating the 1-vs-2-leg mix. Encoding fills in the template is exact and needs no engine change.
- Adverse selection is not a fill–outcome coupling in this MC. It is the δ alternative itself: a filled-bid win rate δ below BE. This matches how FQ framed G3.
- Climate-date clustering:
  - Whole date groups are resampled.
  - Cross-station outcome dependence uses the engine's existing S5 Gaussian-copula rows: ρ_bind = max(0.25, ρ̂) with ρ̂ = None → 0.25 (`rows.py:286-289`), plus S5 "half" (ρ = 0.5).
  - Both are calibration rows already in `_CAL` (`engine.py:57-66`). The binding-max c covers them.
- Exits: hold to settlement. The S4 exit-perturbed calibration row stays at its 0.10 floor (`rows.py:53`), as in FQ. That is conservative and unchanged.

### 4.2 Reachability statistic and pass bar (same bar as FQ v2, cited)

The statistic is the unchanged r3 §4.6 A1 floor solve (`select_alpha`, `gate.py:266-333`):
- G1 reach: the all-lose path crosses by `T_low(e)`. At α > 0.10 the margin `⌊0.8·T_low⌋` applies.
- α ladder `{0.10, 0.20, 0.30}`. It escalates on G1 only and never on G3.
- G3(−0.16) ≥ 2.5·α at the chosen α (`gate.py:75-77`; core `:47-49`).

Pass bar: the floor is not `unreachable_veto` and not `freeze_blocked`. This is the bar FQ v2 failed: G3(−0.16) = 0.2104 < 0.25 in M-yes (ruling :26). T2 names it explicitly: "a new family … whose floor passes the §4.6 gate for its own mix" (ruling :49). **The same bar applies. Nothing is relaxed.** Same α grid, same 2.5 multiplier, same T_MIN_GRID, same 10,000 replicates for the binding run, and the same epoch structure (§4.3).

The FQ-specific part is replaced only where the ruling allows it: the mix. MIXSET = {M-no} (≡ M-pool on all-NO templates), justified structurally:
- The spec rule buys NO only (§3 "NO leg only"). The maker prereg must carry that as a design key.
- Stage −1 for FQ found **no** structural exclusion because the F5 design had no side key (`docs/evidence/f5/fq_r8_2_stage_minus1_mix.md`).
- WP3 asserts every template leg has `side == "no"`.

### 4.3 Epoch window (not laxer than FQ)

- FQ ran from freeze 2026-10-08 to horizon 2027-01-25, which is **110 inclusive days**, with epochs at offsets {0, 24, 38, 54} days.
- The maker run uses the **same 110-day window and the same offsets**, anchored at a nominal arming date. Reachability depends only on day counts, so the anchor is a label.
- A longer window would add ticks and loosen the bar, so the CLI **refuses** `epoch_days > 110`.
- Open question Q1 covers whether the absolute RA-13 date should bind instead.

### 4.4 α allocation (RA-13 nesting)

There are two different error budgets. The plan keeps them apart.

**Confirmatory (promotion) α: spends FWER.**
- The programme FWER is α = 0.025 (RA-13 header :5; F5 design `alpha_total` 0.025).
- PM.us per-class allocation is 0.025/4 = 0.00625 (RA-13 §4 K-1 :62; §7 B-2 :87).
- The maker family takes one class slot: **α_maker = 0.00625 one-sided**. Spec §7.4's ≤3 revisions are Holm-adjusted inside it, so the first test is at 0.00625/3 ≈ 0.00208. The LD-OBF sequential looks (spec §4) spend within 0.00625.
- Finding for S5: spec §7.3's "95% CI excludes 0" is **laxer** than α_maker and must be replaced by the nested level.

**Harm-side stops: false-STOP rates, spend no FWER.**
- These are the A1 floor α ∈ {0.10, 0.20, 0.30} and A0 `alpha_kill` 0.05.
- A stop never asserts an edge, so it cannot cause a false CONFIRM. They are carried over unchanged from FQ.
- S3 checks only this side. α_maker is recorded in the artifact for S5 and is not used by the S3 verdict.

## 5. Nautilus null-hypothesis check

| Need | Native capability checked | Covers it? |
|---|---|---|
| Power/reach of a sequential loss stop under H0/H1 path models | `nautilus_trader/analysis/analyzer.py:38` `PortfolioAnalyzer`. It gives descriptive realised stats (`get_performance_stats_*` :562-634). No sequential test, no MC under hypotheses. | No |
| Maker fee | `nautilus_trader/adapters/polymarket/fee_model.py` `PolymarketFeeModel`. It credits maker rebates (`infer_maker_rebate_rate` :132), which Breezy refuses (`errors.py:305`). | Not usable; θ = taker by policy |
| Fill simulation | Nautilus `FillModel`/backtest. That is S2's concern. Reachability needs a fill *rate*, not a replay. | N/A here |

Genuinely missing: nothing new. The gap is filled by Breezy's own existing FQ floor tooling (`scripts/analysis`, outside Nautilus), parameterised. Nautilus is not touched.

## 6. Work packages

All paths are relative to the worktree `<wt>`.

Interpreter: `/home/jon/breezy/.venv/bin/python` with `PYTHONPATH=<wt>/src:<wt>`. Never use `uv`/`pip`.

Focused gate (every WP):
```
PYTHONPATH=<wt>/src:<wt> /home/jon/breezy/.venv/bin/python -m pytest \
  tests/unit/test_fq_loss_floor_mc_*.py tests/unit/test_fq_loss_floor_np_bound.py \
  tests/unit/test_fq_kill_power_report.py tests/unit/test_prereg_amendment_check.py \
  tests/unit/test_fq_loss_floor_mc_maker.py tests/contract/test_fq_loss_stop_writer_allowlist.py \
  --basetemp ~/.cache/breezy-s3-basetemp -q
```
- Then `lint-imports` from `<wt>`, requiring "N kept, 0 broken".
- `ruff check`/`ruff format` **only on files the WP touched**.
- Full gate after merge: `scripts/ci/run_tests_no_egress.sh` with basetemp under `~/.cache`. Read EXIT, then `rm` the basetemp.

### WP0 — FQ golden pin (RED-first safety net)
- Create `tests/unit/test_fq_loss_floor_mc_maker.py` with
  `test_fq_default_floor_document_is_unchanged_by_parameterisation`. It runs `run_floor` on a fixed small FQ-shaped fixture (3 date groups, mixed YES/NO legs, replicates = 64, fixed seed), hashes the JSON-canonical document, and compares it to a hash recorded **before** WP1 on the current HEAD.
- Add `test_np_bound_drift_guards_still_raise_for_fq`. It asserts `np_bound._prepare` still raises on MIXSET/freeze drift (`:147-150`), so the guards are not weakened.
- Completion: both tests GREEN on HEAD before any edit, and the hash is committed.

### WP1 — thread `mixes` through the floor engine
- Modify `fq_loss_floor_mc_engine.py` (`run_floor(..., mixes: tuple[str, ...] = MIXES)`; `PATH_FAMILIES` becomes a function of `len(mixes)`), `fq_loss_floor_mc_report.py` (`append_rows`, `evaluate_alpha`, `finish_document`, `h1_fallback_table` take `mixes`), `fq_loss_floor_mc_e2.py` (`finish_e2`/`_measured`/`_failing_mix` take `mixes`; `_MIX_ORDER` stays as the default), and `fq_loss_floor_mc_outer.py` (`apply_outer_se(..., mixes)`).
- Validation: `mixes` must be a non-empty subset of `("M-pool","M-yes","M-no")` in canonical order, otherwise `ValueError`.
- RED tests:
  - `test_all_no_world_under_fq_mixset_is_a_spurious_veto` (characterises the §3.2 blocker: G3 = 0 from the empty M-yes cell);
  - `test_run_floor_with_m_no_mix_evaluates_only_that_mix`;
  - `test_mixes_must_be_a_canonical_subset`.
- Completion: WP0 golden hash unchanged; all existing `test_fq_loss_floor_mc_*` green.

### WP2 — relative epoch offsets
- Modify `fq_loss_floor_mc_gate.py`:
  - `FloorConfig.epoch_offsets_days: tuple[int, ...] | None = None`.
  - `epoch_grid(freeze, offsets=None)`: `None` returns today's absolute FQ grid; offsets give `freeze + d`.
  - `FQ_EPOCH_OFFSETS: Final = (0, 24, 38, 54)` and `FQ_EPOCH_DAYS: Final = 110`.
- Update the engine/report call sites to pass `config.epoch_offsets_days`.
- RED tests:
  - `test_fq_offsets_reproduce_the_absolute_fq_epoch_grid` (freeze 2026-10-08 + offsets equals the current grid, and inclusive 10-08→01-25 equals 110);
  - `test_maker_epoch_window_longer_than_fq_is_refused`.
- Completion: golden hash unchanged.

### WP3 — maker template builder and CLI
- Create `scripts/analysis/fq_loss_floor_mc_maker.py` (≤ 300 lines).
- Interfaces:
  - `@dataclass(frozen=True) MakerMix(stations: tuple[str,...]=("LAX","MDW","MIA","SFO"), listing: float=0.91, rungs: int=2, fill_rate: float, bid: float, theta: float=0.0695)`.
  - `maker_be(bid: float, theta: float) -> float`. It refuses bid > 0.80 (B_CAP) or < 0.70 (grid floor, §4.1).
  - `build_maker_groups(mix: MakerMix, *, n_dates: int, seed: int) -> tuple[tuple[StationDay, ...], ...]`. Rung ids are numeric (e.g. `lt58`, `gte80`) so `rung_temperature` orders them (`rows.py:60-64`).
  - `maker_floor_config(groups, mix, *, anchor: date) -> FloorConfig`. It sets rates so that p_keep = 1, `half_spread=None`, `pool_exit_fraction=0.0`, `rho_hat=None`, offsets `FQ_EPOCH_OFFSETS`, and horizon = anchor + 109 d.
  - `run_cell(mix, *, replicates, seed) -> dict` calls `run_floor(..., mixes=("M-no",))`.
  - `verdict(cells, *, f_lo) -> Literal["REACHABLE","UNREACHABLE"]`.
  - CLI `--sweep` / `--binding --f-lo X --bids 0.70,0.80` / `--subset-benchmark`, with `apply_address_space_cap` as in `fq_loss_floor_mc.py`.
  - Pinned constants: `SEED = 20261012`, `SWEEP_REPLICATES = 2000`, `BINDING_REPLICATES = 10_000` (= FQ A1), grids as in §1.
- Verdict cells at `f_lo` are rungs ∈ {2, 1} × each bid grid point inside Stage 0's realised bid IQR, rounded outward to {0.70, 0.75, 0.80}. If there is no S2 bid data, use all three. **All cells must pass** (stricter unit, spec §3).
- RED tests:
  - `test_maker_be_is_bid_plus_theta_fee`;
  - `test_maker_leg_pnl_win_is_one_minus_be_and_loss_is_minus_be`;
  - `test_two_maker_legs_cannot_both_lose`;
  - `test_template_fill_and_listing_rates_match_parameters` (binomial tolerance, fixed seed);
  - `test_maker_templates_are_all_no_side`;
  - `test_maker_config_keep_probability_is_one`;
  - `test_h1_bernoulli_fallback_share_is_zero_on_the_bid_grid`;
  - `test_bid_outside_grid_is_refused`;
  - `test_verdict_unreachable_if_any_cell_vetoes_or_freeze_blocks`;
  - `test_verdict_reads_f_lo_not_the_point_estimate`.
- Completion: focused gate green, lint-imports clean, `--subset-benchmark` projection recorded.

### WP4 — sweep, binding run, artifact
1. Run `--subset-benchmark` and record the projected wall time and RSS.
2. Run the sweep (20 cells × 2000 replicates) under `systemd-run --user -p RuntimeMaxSec=<2×projection> -p MemoryMax=5G -p LimitNOFILE=524288`, with per-cell progress lines as the stall watch.
   - One heavy job on the host. Never run it during the nightly studies window.
3. After S2 lands, run `--binding` at `f_lo` (10,000 replicates per verdict cell) the same way.
4. Write `docs/evidence/maker/A1_REACHABILITY_<run-date>.md` containing:
   - verdict;
   - binding table (`floor_mode`, `power_class`, `alpha_star`, c ± `c_mc_se`, `t_min`, G3 by δ, T_low per epoch, median ticks, `h1_fallback` share);
   - sweep table (labelled context only);
   - α_maker record (§4.4);
   - θ basis;
   - the evidence JSON sha256;
   - provenance (git sha, seed, S2 artifact path and sha).
5. On UNREACHABLE, add the spec §8 row and a PROGRESS line.
- Completion: artifact committed. Commit and push only after a gate-green merge, with the gate EXIT read before the push.

### WP5 (optional, report-only; peers may cut) — A0 KILL power row
- Payoff: S5's prereg needs to know whether its KILL e-process can fire inside the 110-day window. FQ's could not (`p_kill_by_kill_date` = 0 at every δ, `fq_kill_power_negative_edge_seed20261008.json`).
- Do it only if `fq_kill_power_report.simulate_clamped` accepts injected take records without refactor, otherwise defer to S5.
- No verdict depends on WP5.

## 7. Data and tooling dependencies

| Item | Path | Status |
|---|---|---|
| FQ floor engine | `scripts/analysis/fq_loss_floor_mc_*.py` | on disk, tests exist (`tests/unit/test_fq_loss_floor_mc_{e2,gate,review,rows,solve}.py`) |
| Loss-stop core (bar constants) | `src/breezy/analysis/fq_loss_stop_core.py`, `_clock.py` | on disk |
| FQ A1 evidence (bar comparison) | `docs/evidence/f5/fq_loss_floor_mc_seed20261008.json` | on disk, read-only |
| θ | `F5_prereg_v2_design.json` `theta` 0.0695 | frozen; read-only |
| Stage 0 fill rate, CI, bid distribution | S2 artifact (path set by S2) | **UNVERIFIED / not yet produced** |
| Listing share 0.91 | spec §9.15 | **UNVERIFIED** for the 4-station subset; S1 census should confirm |
| Maker fee coefficient | wire, via S2 | **UNVERIFIED**; the verdict uses taker θ |
| Two candidate rungs per listed station-day passing P_MIN ∧ b_max ≥ 0.50 ∧ not modal-adjacent | spec §3 | **UNVERIFIED**; the rungs = 1 cell covers the shortfall |

## 8. Risks and guards

| Risk | Invariant at stake | Guard |
|---|---|---|
| WP1/WP2 silently change the frozen FQ A1 result's reproducibility | frozen evidence and A1 integrity | WP0 golden hash; FQ defaults unchanged; no edit to A1/A0 JSON or `docs/evidence/f5/*` |
| Relaxing the np_bound drift pins to "make room" | never weaken a contract guard | np_bound not modified; `test_np_bound_drift_guards_still_raise_for_fq` |
| Longer epoch, smaller α grid or lower multiplier sneaks in a laxer bar | ruling bar | constants imported from core, never redefined; `epoch_days > 110` refused |
| Choosing `f`, bid or seed after seeing the sweep | forking paths (ruling Disclosures) | pinned in code before the binding run; verdict on `f_lo` and all cells |
| Synthetic templates understate clustering of NO tail losses | the verdict could be optimistic | ρ 0.25 and 0.5 calibration rows bind c; Q3 asks for a ρ = 0.9 report row |
| Agent reformats whole dirs / touches the exec client | byte-pinned exec, NO-SEND pins | WP briefs say "format only your files"; `git status` check for strays before commit |
| Heavy run collides with nightly studies / OOMs | host stability | one heavy job; systemd-run caps; subset benchmark first |
| Tape read for templates | RA-13 B-3 firewall | S3 reads no tape; only S2's summary numbers |

## 9. Effort and evidence artifact

| WP | Agent-hours |
|---|---|
| WP0 | 1 |
| WP1 | 2.5 |
| WP2 | 1 |
| WP3 | 3 |
| WP4 | 1.5 plus compute (sweep projected from benchmark; FQ's 10k-replicate run is the reference) |
| WP5 (optional) | ≤ 2 |
| Review loop | 2 |
| **Total** | **~11 agent-hours (13 with WP5)** |

Single evidence artifact: `docs/evidence/maker/A1_REACHABILITY_<run-date>.md`, with `a1_reachability_mc_seed20261012.json` beside it.

## 10. Open questions for peer review

1. **Window anchoring.** Should the maker's loss-stop window be the relative 110 days (this plan), or the absolute RA-13 horizon 2027-01-25? Arming after a ~100-day S5 shadow falls past 2027-01-25, so the absolute date gives zero days. RA-13 R4 ("a new estimand that clears its power check at intake", :53) is the deferral route. Is this S3 artifact plus S2 that intake check?
2. **Class slot.** Is α_maker = 0.025/4 correct? The maker family may be a 5th AUD-18 class, which would make it 0.025/5, unless the KILLED trigger-4 path's slot (RA-13 §1) is formally reassigned.
3. **ρ stress.** Should a ρ = 0.9 copula row be added as report-only, or as binding? It would cover the case where one synoptic regime puts all four stations' tails together.
4. **Verdict cells.** Is "every bid cell in Stage 0's IQR × rungs {1, 2} must pass" the right stricter unit, or should rungs = 1 be report-only?
5. **Cut D1/A0.** Is it acceptable to skip the NP bound entirely, because an A1 veto is terminal here, and to cut WP5?

# S3 — A1 loss-floor reachability for a maker mix

| Field | Value |
|---|---|
| ID | S3 |
| Title | A1 loss-floor reachability for a maker mix (parameterise the FQ floor tooling) |
| Revision | r2 (supersedes r1; reviews `reviews/S3-r1-architect.md`, `reviews/S3-r1-prediction-market-reviewer.md`) |
| Date | 2026-10-12 |
| Status | READY-FOR-REVIEW |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.2 §4, §6.1, §6.7, §7.8, §9.8 |
| Rulings | `docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md` (T2 route); `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md` |

Hard invariants (binding on every WP):
- Nautilus Trader is immutable. `allow_short` stays False.
- No safety, settlement, contract or NO-SEND test is weakened. Exact-set barriers are only WIDENED by one reviewed row (L-12).
- No value is assigned to max daily budget or max per position. Live enablement and `BREEZY_ORDERS_ENABLED` are untouched.
- No frozen PREREG/amendment JSON is edited (incl. `F5_prereg_v2_amendment_A1.json`, `_A0.json`, `docs/evidence/f5/*`). No pre-registered date moves.
- Stage 0 numbers are exploratory, never promotion evidence. The NO-TRADE ruling stays in force.

## 1. Goal state (acceptance test)

`docs/evidence/maker/A1_REACHABILITY_<run-date>.md` is committed beside `a1_reachability_sweep_seed20261012.json` and `a1_reachability_binding_seed20261012.json`.

The .md records: both JSON sha256s; `git_head` and a clean-tree assertion (`git status --porcelain scripts/analysis` empty); each Stage 0 input, with its S2 artifact path and line.

It states exactly one verdict. The rule is pinned in code before the binding run (§4.5).

| Verdict | Condition | Next action |
|---|---|---|
| `REACHABLE` | every verdict cell is `sqrt_boundary` at `f_pass` | S4/S5 may start; S5 freezes the A1 clock (§4.4) |
| `UNDERDETERMINED` | every cell passes at `f_kill`, some cell fails at `f_pass` | no S4 build; one pinned re-run after more census (§4.5) |
| `UNREACHABLE — not registrable` | some cell is `unreachable_veto` or `freeze_blocked` at `f_kill` | programme ends at S3 (STOP 2) |
| `NOT-APPLICABLE` | S2 two-leg sub-0.70 bid share > 10% and spec v0.3 has not ruled on B_FLOOR | coordinator carries §10 input 3 |

If the power class is `gross_loss_tripwire`, REACHABLE is spelled out: the stop catches collapse (win rate ~0.57–0.65), not the realistic adverse-selection range. G3(−0.08) and G3(−0.04) are printed beside the verdict.

## 2. Entry criteria and STOP conditions

Build half (WP0, WP1, WP3) needs nothing from S1/S2. It uses synthetic templates, reads no tape, and spends no RA-13 B-3 days.

The binding run (WP4 step 3) needs ALL of:
1. **S2 numbers.** S2 has emitted, under both the base and the 2× stress fill rules (spec §6.1, §6.7): the fill-rate point estimate and its climate-date cluster-bootstrap 95% CI; the Stage 0 climate-date count `n0`; the realised bid IQR; the share of filled bids < 0.70, split one-leg / two-leg.
2. **S2 did not stop the family.** S2's §6.9 verdict is not FAIL, and S2 did not apply its 0.1 fill floor. S3 reads S2's verdict and does not re-judge it.
3. **Window ruling.** A dated coordinator ruling says the maker loss-stop window is a relative 110 days, not the absolute 2027-01-25. Under the absolute date the window is ~0 days, so the run would be moot (arch F11).
4. **Pins committed.** The §4.5 rule and the WP3 pins are committed. This is the forking-path guard: any post-result change is void.

STOPs:
1. S2 stopped the family. The binding run is not run; the sweep stays as context.
2. UNREACHABLE at `f_kill`: not registrable; S4 and S5 not started; spec design-history row; NO-TRADE and RA-13 unchanged.
3. `freeze_blocked` (`s6_failed` or refused templates) counts as UNREACHABLE unless a reviewer proves a builder defect. The bar never moves.
4. UNDERDETERMINED twice. There is no third look. The family is not registrable before the RA-13 horizon, and that horizon decides.

## 3. Simplest direct path

The FQ floor engine already models the maker path: per-leg `x_piece(h, be)` (`fq_loss_floor_mc_rows.py:180-183`); exclusive rung outcomes from one categorical draw (`fq_loss_floor_mc_draw.py:119-137`, `invert_cdf` at `:238`); whole climate-date resampling (`fq_loss_floor_mc_sim.py` `simulate_family`).

What blocks reuse is that the FQ mixset, calibration rows and binding set are module constants spread over four files. The direct path:
1. Bundle them into one frozen `FloorSpec` whose default is FQ's, byte-identical.
2. Write a maker template builder.
3. Call `run_floor(spec=MAKER_SPEC)` with a `FloorConfig` on FQ's own `DEFAULT_FREEZE`/`HORIZON`, used as a 110-day label.

Cut from r1: the epoch code (r1 WP2); the NP bound D1 (an A1 veto here is terminal, so D1 cannot change a decision); the A0 row (r1 WP5, deferred to S5).

Only two engine additions, each with a named payoff:
- **Station persistence** in `simulate_family`. TE-2 losses are same-station runs, and the engine has no serial knob (PMR F2).
- **A worst-feasible G1 path.** `all_lose_z` scores an impossible path for exclusive NO legs (PMR F5).

### 3.1 Why the FQ mixset vetoes an all-NO world (corrected, arch F1)

1. On an all-NO world the M-yes cell is empty. `apply_mix` drops every NO leg (`rows.py:249-256`), and `prepare_mix_groups` skips legless days (`engine.py:103-104`).
2. So `_median_z(cleaned,"M-yes")` is None (`report.py:88-95`), `t_cross` is None, and `g1_holds` is False (`gate.py:87-92`, called at `report.py:215-219`).
3. `all(passes)` is then False at every α. `select_alpha` returns `unreachable_veto` with `veto_cause="g1_unreachable"` (`gate.py:280-292`) before G3 is read.

Empty prepared groups are safe: `simulate_family` guards only `if not groups` (`sim.py:71-72`); `_criticals` handles empty cuts (`engine.py:111-119`).

This veto comes from construction, not evidence. WP1 fixes the mix and never the bar.

### 3.2 Which mix (arch F2): `mixes = ("M-pool",)`

`engine.py:355` hard-codes `cal_sims[("H0","none","M-pool")]` for the carry diagnostic. On all-NO, zero-netting templates M-pool ≡ M-no: `apply_mix(day,"M-pool")` returns the day unchanged (`rows.py:250-251`); `"M-no"` keeps the same legs with netting 0.0 (`:253-256`); netting arises only from paired YES/NO rungs (`rows.py:131-140`), which maker templates never contain.

So `FloorSpec` requires `"M-pool" ∈ mixes`, `engine.py:355` is unchanged, and a WP1 test pins the equivalence.

## 4. Path model, statistic, bar

### 4.1 Maker path model (one leg = one filled resting NO bid, qty 1, held to settlement)

- **BE and θ.** `BE = b + θ·b·(1−b)` with θ = 0.0695 (taker). The documented venue maker coefficient is a rebate (`errors.py:305` doc), so taker θ overstates BE by ~0.012–0.014. That makes the null stricter, which is conservative for a harm stop. If the wire ever shows a positive maker fee, the sign flips and the wire θ must be used.
- **P&L.** Win `1 − BE`, loss `−BE`; the fee is paid at fill in both outcomes. Legs are `make_leg(rung,"no",BE,price=b)` (`rows.py:76-91`).
- **Exclusivity.** At most 2 legs per station-day, on distinct rungs, exclusive in loss (`draw.py:131-137`); Two-leg templates need b ≥ 0.70. Below ~0.645, the two H1(−0.16) YES masses sum past 1, `_h1_masses` returns None (`draw.py:61-91`), and `advance_prepared` falls back to independent Bernoulli draws (`draw.py:216-217`). Both legs can then lose, which inflates G3; Single-leg templates stay categorical down to B_FLOOR 0.50.
- **Listing and fills.** Each of LAX/MDW/MIA/SFO is listed with probability 0.91 per date (spec §9.15); A listed station-day has k ∈ {1,2} candidate rungs; The date-level fill rate f_d ~ Beta(mean f, `FILL_ICC = 0.5/7`), which gives design effect 1.5 (spec §6.4) at 8 rung-trials per date. Each rung fills Bernoulli(f_d); Unfilled station-days are absent. Fill-less dates stay as empty groups, so the per-date tick rate is honest; Over-dispersion widens the tick-count spread in the power MC. T_low stays the expected count (engine rule). f is not also divided by 1.5, which would double-count (PMR F3c).
- **Rates from templates (PMR F6).** `lambda_sd` = mean template station-days per date; `r_sd` = mean legs per template station-day; `lambda_pool = take_rate_lower = r_sd·lambda_sd`; So `keep_probability = 1` (`gate.py:129-133`), and `T_low = ⌊n·λ_sd·tick_share⌋` (`gate.py:136-142`) counts exactly what the sim ticks; `tick_share` (`report.py:316-321`) = 1.0 on NO-leg days; Analytic checks, asserted within 3 SE: λ_sd = 4·0.91·(1−(1−f)^k), r_sd = k·f/(1−(1−f)^k).
- **Adverse selection** is the δ alternative (filled win rate below BE), as in FQ G3.

### 4.2 Dependence rows (PMR F1, F2)

| Row | Mechanism | Role | Pin |
|---|---|---|---|
| H0, S4 | as FQ | binding | unchanged |
| S5 `bind` | cross-station copula per date (`sim.py:36-47`) at `rho_bind(rho_hat)` | binding | maker `FloorConfig.rho_hat = 0.5`. There is no maker pool ρ̂, so the 0.25 floor (`rows.py:286-289`) is not used. No code change. |
| S5 `half` | ρ = 0.5 | report (duplicates `bind`) | unchanged |
| **S8 `persist3`** | per-station factor held for L consecutive simulated days; `u = Φ(√ρp·F_station + √(1−ρp)·ε)` | **binding** | L = 3, ρp = 0.5 |
| **S9 `persist5`** | same | report; false-stop rate at solved c printed | L = 5, ρp = 0.9 |

- **Why a copula and not block resampling.** Synthetic templates carry no outcomes; the outcome is drawn in `advance_prepared`. Block-resampling templates cannot make a loss persist.
- **L calibration.** TE-2 records 14 loss station-days in 7 same-station clusters, mean run 2 (`docs/evidence/te2/phase_b/fq_v1_loss_taxonomy_2026-10-12.md:56`). L = 3 exceeds it.
- **ρp is pinned, not estimated.** The artifact states that **REACHABLE is conditional on station persistence no worse than (L=3, ρp=0.5)**. A Gaussian copula has zero tail dependence, so S9 (ρp = 0.9) is the printed stress.
- **Row label.** S8 needs its own row label because `binding_max` keys cells by `(row, mix)` (`report.py:177-178`). An unknown row takes the H0 masses path (`draw.py:235`) and the pooled set (`day_pool`, `draw.py:313-318`).

### 4.3 Statistic and pass bar (same bar as FQ v2)

**Statistic.** The unchanged r3 §4.6 solve, `select_alpha` (`gate.py:266-333`): G1 reach by T_low, with margin ⌊0.8·T_low⌋ at α > 0.10; α ladder {0.10, 0.20, 0.30}, escalating on G1 only; G3(−0.16) ≥ 2.5·α (`gate.py:316`; core `fq_loss_stop_core.py:47-51`); 10,000 replicates, as FQ A1.

**Outer-SE parity (arch F5).** The binding run pins `OUTER_RESAMPLES = 20` and `OUTER_REPLICATES = 2000`, as FQ A1 did (`fq_loss_floor_mc_seed20261008.json:1656-1657`; CLI defaults `fq_loss_floor_mc.py:84-85`).

**G1 path (PMR F5).** `all_lose_z` loses every leg (`rows.py:326-334`), a path two exclusive NO legs cannot take. The maker spec uses `g1_path="worst_feasible"`: the minimum x over the categorical outcomes, one leg YES or none.
- That path is less extreme, so it crosses later and makes G1 **stricter**.
- All-lose z is reported as context. FQ keeps `all_lose` by default.

**Deviations from FQ** (each is tightening or structural): mix {M-pool ≡ M-no}, because the spec buys NO only; WP3 asserts `side == "no"`; ρ binds at 0.5, not 0.25; S8 persistence is added to the binding set; G1 uses the feasible path.

**Window.**
- `freeze = DEFAULT_FREEZE`, `horizon = HORIZON` (`gate.py:57-58`; `FloorConfig` defaults `:347-348`).
- This reproduces 110 inclusive days and epoch offsets {0, 24, 38, 54}.
- It keeps `complete_veto`'s `epoch_grid(freeze)[0]` (`e2.py:231`) correct.
- The artifact says "window = FQ v2 window 2026-10-08..2027-01-25 used as a 110-day label".
- The builder refuses any other freeze/horizon.

### 4.4 Which stop is certified (PMR F4)

S3 certifies the **A1 sqrt-boundary clock on station-day ticks**: production `fq_loss_stop_core`/`_clock`, the stop spec §7.8 names. S5 must freeze that clock as the maker loss stop.

Spec §4's "LD-OBF on Wilson, look every 10 positions" is a second stop, in a different unit, and S3 does not test it (§10 input 1).
- If v0.3 keeps LD-OBF as a *loss* stop, it needs its own reach check at `f_pass`, added as a new S3 WP.
- If LD-OBF stays only as a confirmatory look, nothing is added.

### 4.5 Verdict rule (pinned before the binding run; PMR F3, F7, F10)

**Fill inputs.**
- `f_pass` = the 2×-rule 95% lower bound.
- `f_kill` = the base-rule point estimate, the most optimistic Stage 0 number.

A terminal KILL never rests on a lower bound.

**Verdict cells.**
- k ∈ {2, 1} × each bid in S2's two-leg IQR, rounded outward to {0.70, 0.75, 0.80}. If there is no IQR, use all three.
- Plus k = 1 at b ∈ {0.50, 0.60} if S2's one-leg sub-0.70 share > 10%.

If the two-leg sub-0.70 share > 10%, the verdict is `NOT-APPLICABLE` until spec v0.3 rules on B_FLOOR. **All cells must pass** (the stricter unit, spec §3).

**Borderline.** If |G3(−0.16) − 2.5·α*| < 2·binomial SE at 10k, that cell is re-run once at 50,000 replicates with seed 20261013. The re-run is final.

**UNDERDETERMINED.**
- Trigger: once the census adds ≥ `n0` more climate dates, S2 re-emits its numbers and S3 re-runs the binding run once.
- Second-look rule: pass at `f_pass` → REACHABLE; fail at the 2× point estimate → UNREACHABLE; otherwise STOP 4.
- S4 does not start while the verdict is UNDERDETERMINED (kill-first; the exec build is the expensive step).

### 4.6 α records (not used by the S3 verdict; PMR F8, F9)

The confirmatory α_maker is recorded both ways: 0.025/5 = 0.005, the default, with Holm/3 0.00167; 0.025/4 = 0.00625, with Holm/3 0.00208, only if a ruling reassigns the KILLED trigger-4 slot.

Cites: RA-13 header :5 and §7 B-2 :86-88. Harm-side A1 α spends no FWER.

This artifact is an input to a separate dated R4 ruling (RA-13 §3 :53), not the ruling itself. That ruling needs confirmatory power at the nested α and must land before 2027-01-25.

## 5. Nautilus null-hypothesis check

| Need | Native capability checked | Covers it? |
|---|---|---|
| Reach/power of a sequential loss stop under H0/H1 | `nautilus_trader/analysis/analyzer.py:38` `PortfolioAnalyzer`: descriptive realised stats only | No |
| Maker fee | `nautilus_trader/adapters/polymarket/fee_model.py:132` `infer_maker_rebate_rate`; Breezy refuses rebates (`errors.py:305`) | Not usable; taker θ by policy |
| Fill simulation | `FillModel`/backtest belongs to S2; S3 needs only a rate | N/A |

Nothing new is needed. Breezy's own `scripts/analysis` FQ tooling is parameterised. Nautilus is not touched.

## 6. Work packages

Paths are relative to the worktree `<wt>`. Interpreter: `PYTHONPATH=<wt>/src:<wt> /home/jon/breezy/.venv/bin/python`. Never `uv`/`pip`.

Focused gate (every WP):
```
PYTHONPATH=<wt>/src:<wt> /home/jon/breezy/.venv/bin/python -m pytest \
  tests/unit/test_fq_loss_floor_mc_*.py tests/unit/test_fq_loss_floor_np_bound.py \
  tests/unit/test_fq_kill_power_report.py tests/unit/test_prereg_amendment_check.py \
  tests/unit/test_fq_loss_stop_core.py tests/contract/test_fq_loss_stop_writer_allowlist.py \
  --basetemp ~/.cache/breezy-s3-basetemp -q ; echo EXIT=$?
```
Then, in order:
1. `lint-imports` from `<wt>`; require "N kept, 0 broken".
2. `ruff check`/`ruff format` on touched files only.
3. `git status` check for strays.
4. After merge, the full gate `scripts/ci/run_tests_no_egress.sh` with basetemp under `~/.cache`. Read EXIT, then `rm` the basetemp.

### WP0 — FQ reproducibility pins (characterisation; GREEN on HEAD before any edit; arch F4, F9, PMR F11)

Create `tests/unit/test_fq_loss_floor_mc_spec_pins.py`. Hashes are sha256 of `json.dumps(doc, sort_keys=True)`; `run_floor`'s provenance args default to None, so the hashes are stable.

| Test | Pins |
|---|---|
| `test_fq_floor_pass_document_hash_is_pinned` | Fixture A, a mixed YES/NO world reaching `sqrt_boundary`. Distinct `gate_groups`, `outer_resamples=2`, `outer_replicates=32`, `alphas=None`, `replicates=64`. |
| `test_fq_floor_veto_document_hash_is_pinned` | Fixture B, a vetoing world, same knobs. Exercises `complete_veto`, `_rows_at`, `_measured`, `_failing_mix` (`e2.py:99-150`, `:220-240`) and `outer.binding_c` (`outer.py:87-125`). |
| `test_fq_module_constants_are_unchanged` | `engine.MIXES == report.MIXES == e2._MIX_ORDER == ("M-pool","M-yes","M-no")`; `engine.PATH_FAMILIES == 60`; `report.py:80` and `outer.py:45` binding sets = {H0, S4, S5-bind}. |
| `test_all_no_world_under_fq_spec_vetoes_g1_unreachable_on_m_yes` | Characterisation pin, not RED: `veto_cause == "g1_unreachable"`, `failing_mix == "M-yes"`. |

Real-CLI snapshot on HEAD: `fq_loss_floor_mc.py --seed 20261008 --replicates 200 --outer-resamples 2 --outer-replicates 100 --out <scratch>/fq_before.json`; run it under `systemd-run --user -p MemoryMax=5G -p RuntimeMaxSec=3600`; it reads `~/.local/share/breezy/kalshi` (`candles.jsonl` and `markets_*.json` are on disk); a byte match against `docs/evidence/f5/...seed20261008.json` is impossible, because `git_head` changes.

Completion: the four tests are GREEN on HEAD, the hashes are committed, and the `fq_before.json` sha is recorded.

### WP1 — `FloorSpec`, persistence, feasible G1 path (FQ default byte-identical)

`fq_loss_floor_mc_gate.py` is the canonical home: report cannot import engine (`engine.py:33`; arch F8).
```python
@dataclass(frozen=True, slots=True)
class FloorSpec:
    mixes: tuple[str, ...] = ("M-pool", "M-yes", "M-no")
    cal: tuple[tuple[str, str], ...] = FQ_CAL            # today's _CAL, verbatim
    binding: tuple[tuple[str, str], ...] = (("H0","none"), ("S4","none"), ("S5","bind"))
    persist: tuple[tuple[str, int, float], ...] = ()     # (mode, block_days L, rho_p)
    g1_path: Literal["all_lose", "worst_feasible"] = "all_lose"
FQ_SPEC: Final = FloorSpec()
def path_families(spec: FloorSpec) -> int: ...
```
`__post_init__` raises `ValueError` if: `mixes` is not a non-empty canonical-order subset containing `"M-pool"`; `binding ⊄ cal`; two binding rows share a row label; a `persist` mode is not in `cal`.

Changes by file:
- **engine.** `run_floor(..., spec: FloorSpec = FQ_SPEC)` replaces `MIXES`/`_CAL` at `:236-241`, `:266`, `:352`. `_run` passes `persist`. `MIXES` and `PATH_FAMILIES` stay as `FQ_SPEC` aliases, because `fq_loss_floor_mc.py:29-30,312` and `np_bound:37,147` import them (arch F6).
- **report.** `append_rows`, `evaluate_alpha` and `h1_fallback_table` take `spec`; `_median_z(groups, mix, path)` dispatches between the two G1 paths; `stamp_run` adds the `floor_spec` key and the all-lose context only when the spec is not `FQ_SPEC`.
- **e2.** `finish_e2` already takes `mixes` (`e2.py:173`); add `binding` for the tuple at `:195`; `_rows_at`, `_measured`, `_failing_mix` and `complete_veto` take `mixes`, defaulting to `_MIX_ORDER` (arch F7).
- **outer.** `apply_outer_se` → `solve_resampled` → `binding_c` take `spec`, replacing the lazy `MIXES` import and `_BINDING` (`outer.py:45,99-112`).
- **sim.** `simulate_family(..., persist: tuple[int, float] | None = None)`: per-station factors are redrawn every L simulated days, and `u = _copula_u(rng, rho_p, F_station)`; setting both `rho` and `persist` raises; `persist=None` leaves the RNG stream untouched.
- **rows.** `worst_feasible_z(day)` is the minimum over the `len(legs)+1` categorical outcomes of Σ x_piece, normalised through `step_clock` the same way `all_lose_z` is.

RED-first tests, appended to the WP0 file:
- `test_run_floor_default_and_explicit_fq_spec_hash_equal`
- `test_run_floor_maker_spec_all_no_world_is_not_vetoed_by_empty_cells` (the true RED)
- `test_floor_spec_rejects_noncanonical_mixes_and_missing_m_pool`
- `test_floor_spec_rejects_duplicate_binding_row_labels_and_binding_outside_cal`
- `test_m_pool_equals_m_no_on_all_no_templates`
- `test_persist_none_leaves_rng_stream_unchanged`
- `test_persist_full_correlation_shares_station_factor_within_block`
- `test_persist_and_rho_together_are_refused`
- `test_g1_all_lose_path_is_infeasible_for_exclusive_no_legs` (worst-feasible z > all-lose z, and equals the one-leg-lost z)
- `test_maker_spec_g1_uses_worst_feasible_and_reports_all_lose`
- `test_fq_spec_document_has_no_floor_spec_key`

Completion:
1. The WP0 hashes are unchanged.
2. Existing `test_fq_loss_floor_mc_*` pass.
3. The real CLI re-run with WP0's args produces `fq_after.json`, and `jq 'del(.script_git_sha,.parent_sha,.a0_sha,.git_head)'` of the before and after files is identical. The diff is recorded.

### WP3 — maker template builder and CLI

Create `scripts/analysis/fq_loss_floor_mc_maker.py` (≤ 300 lines).
```python
MAKER_SPEC: Final = FloorSpec(mixes=("M-pool",), cal=(*FQ_CAL, ("S8","persist3"), ("S9","persist5")),
    binding=(("H0","none"), ("S4","none"), ("S5","bind"), ("S8","persist3")),
    persist=(("persist3", 3, 0.5), ("persist5", 5, 0.9)), g1_path="worst_feasible")
@dataclass(frozen=True) class MakerMix: fill_rate: float; bid: float; rungs: Literal[1, 2]
    stations=("LAX","MDW","MIA","SFO"); listing=0.91; theta=0.0695; fill_icc=0.5/7
def maker_be(bid: float, theta: float) -> float
def build_maker_groups(mix: MakerMix, *, n_dates: int, seed: int) -> tuple[tuple[StationDay, ...], ...]
def maker_floor_config(groups, mix) -> FloorConfig   # §4.1 rates; rho_hat=0.5; FQ window; half_spread=None; pool_exit_fraction=0.0
def run_cell(mix, *, replicates, outer_resamples, outer_replicates, seed) -> dict
def verdict(cells_pass, cells_kill, *, sub070_two_leg_share, spec_b_floor) -> str   # §4.5
```
Pins: `SEED = 20261012`; `N_TEMPLATE_DATES = 1000`; `SWEEP_REPLICATES = 2000`; `BINDING_REPLICATES = 10_000`; `OUTER_RESAMPLES = 20`; `OUTER_REPLICATES = 2000`; `BORDERLINE_REPLICATES = 50_000`; `BORDERLINE_SEED = 20261013`; `SUB070_THRESHOLD = 0.10`; sweep f ∈ {0.1, 0.2, 0.3, 0.4, 0.5} × b ∈ {0.70, 0.75, 0.80} × k ∈ {1, 2}, plus k = 1 at b ∈ {0.50, 0.60}; rung ids are numeric, so `rung_temperature` orders them (`rows.py:60-64`).

CLI modes: `--subset-benchmark`, `--sweep`, and `--binding --s2-artifact PATH`. The binding mode reads only the §2 fields and records their sha and lines. All modes use `apply_address_space_cap`, as in `fq_loss_floor_mc.py`.

RED-first tests in `tests/unit/test_fq_loss_floor_mc_maker.py`:
- **Path model:** `test_maker_be_is_bid_plus_theta_fee`; `test_maker_leg_pnl_win_is_one_minus_be_and_loss_is_minus_be`; `test_two_maker_legs_cannot_both_lose`.
- **Templates:** `test_template_listing_and_fill_rates_match_parameters`; `test_template_fill_overdispersion_matches_pinned_design_effect`; `test_maker_templates_are_all_no_side`.
- **Rates:** `test_lambda_sd_equals_template_mean_station_days_per_date`; `test_r_sd_times_lambda_sd_equals_template_fills_per_date`; `test_maker_config_keep_probability_is_one`; `test_maker_tick_share_is_one`.
- **Bids:** `test_h1_bernoulli_fallback_share_is_zero_on_two_leg_cells`; `test_two_leg_bid_below_070_is_refused`; `test_single_leg_bid_down_to_b_floor_is_accepted`.
- **Config pins:** `test_maker_config_pins_rho_hat_half_and_fq_window`; `test_other_freeze_or_horizon_is_refused`; `test_binding_run_pins_outer_resamples_and_replicates`.
- **Verdict:** `test_verdict_reachable_underdetermined_unreachable_not_applicable`; `test_verdict_kill_reads_f_kill_and_pass_reads_f_pass`; `test_borderline_g3_triggers_one_pinned_rerun`.

Completion: the focused gate passes, lint-imports is clean, and the `--subset-benchmark` projection is recorded.

### WP4 — sweep, binding run, artifact

1. Run `--subset-benchmark` and record the projected wall time and RSS.
2. Run `--sweep` at 2000 replicates: under `systemd-run --user -p RuntimeMaxSec=<2×projection> -p MemoryMax=5G -p LimitNOFILE=524288`; with per-cell progress lines as the stall watch, armed in the launch turn; as the only heavy job, outside the nightly-study window. The sweep is context only.
3. Once the §2 entry criteria (items 1–4) hold, run `--binding` the same way at `f_pass` and `f_kill` on the verdict cells. Apply the borderline rule.
4. Write the artifact: the verdict and its meaning line; a per-cell table: `floor_mode`, `power_class`, `alpha_star`, c ± `c_mc_se`, `t_min`, G3 by δ, T_low per epoch, G1 z (worst-feasible and all-lose), S8/S9 rates, h1 fallback share; the sweep table; the α records; the θ basis and its sign note; the window label; the persistence condition; both shas, `git_head`, and the clean-tree line.
5. On UNREACHABLE, add the spec §8 row and a PROGRESS line. Commit after a gate-green merge, and read the gate EXIT before pushing.

## 7. Data and tooling dependencies

| Item | Path | Status |
|---|---|---|
| FQ floor engine + tests | `scripts/analysis/fq_loss_floor_mc_*.py`; `tests/unit/test_fq_loss_floor_mc_{e2,gate,review,rows,solve}.py` | on disk |
| Bar constants | `src/breezy/analysis/fq_loss_stop_core.py:47-51` | on disk |
| FQ A1 evidence | `docs/evidence/f5/fq_loss_floor_mc_seed20261008.json` | read-only |
| FQ CLI data (WP0/WP1 diff) | `~/.local/share/breezy/kalshi/` | on disk; run cost UNVERIFIED |
| θ | `F5_prereg_v2_design.json` `theta` 0.0695 | frozen, read-only |
| Stage 0 numbers (base + 2×, CI, `n0`, IQR, sub-0.70 shares) | S2 artifact | **UNVERIFIED / not produced** |
| Listing 0.91 for the 4-station subset | spec §9.15 | **UNVERIFIED**; S1 census |
| Window ruling (§2 item 3) | coordinator | **not issued** |
| TE-2 clusters (L calibration) | `docs/evidence/te2/phase_b/fq_v1_loss_taxonomy_2026-10-12.md` | on disk; post-hoc, n = 14 |

## 8. Risks and guards

| Risk | Invariant at stake | Guard |
|---|---|---|
| WP1 changes FQ A1 reproducibility | frozen evidence | two hashed documents (pass and veto, with outer and gate_groups); default-vs-explicit hash; provenance-stripped real-CLI diff; `docs/evidence/f5/` untouched |
| np_bound drift pins relaxed | contract guards | np_bound not modified; aliases pinned in WP0 |
| Laxer window, α grid or multiplier | ruling bar | core constants imported; non-FQ freeze/horizon refused |
| f, bid, ρp, L or seed chosen after results | forking paths | pinned in WP3 before the binding run; all cells must pass |
| Optimistic dependence → c too small | false REACHABLE | ρ = 0.5 binding; S8 binding; S9 printed; conditionality stated |
| Terminal KILL on an exploratory lower bound | Stage 0 is exploratory | KILL reads `f_kill`; the lower bound only gates PASS |
| Agent reformats dirs or touches exec | byte-pinned exec, NO-SEND | "format only your files"; strays check |
| Heavy run collides or OOMs | host | one job; systemd caps; benchmark first; stall watch |

## 9. Effort and evidence artifact

| WP | Agent-hours |
|---|---|
| WP0 | 1.5 |
| WP1 | 3.5 |
| WP3 | 3 |
| WP4 | 2, plus compute |
| Review loop | 2 |
| **Total** | **~12** |

Evidence: `docs/evidence/maker/A1_REACHABILITY_<run-date>.md` plus the two JSONs.

## 10. Spec v0.3 inputs (surfaced by the reviews; not fixed here)

1. **One loss stop.** §4 names LD-OBF on Wilson (positions, every 10); §7.8 names A1 (station-day ticks). Recommendation: A1 is the loss stop; LD-OBF, if kept, is confirmatory only. Otherwise LD-OBF needs its own reach check (PMR F4).
2. **Stage 0 fill floor.** "Fill rate below 0.1" must name the rule (base or 2×) and the statistic (point).
3. **B_FLOOR.** Two NO legs at b < ~0.645 make the H1(−0.16) alternative infeasible as a categorical. Either raise B_FLOOR to 0.70, or allow the second rung only when both bids are ≥ 0.70.
4. **§7.3 and the class slot.** "95% CI excludes 0" is laxer than the nested α_maker, and the class slot (/4 vs /5) needs a ruling.
5. **Maker fee sign.** A positive wire maker fee makes a taker-θ run unevaluable (keep §6.5).

## 11. Open questions for peer review

1. Is (L = 3, ρp = 0.5) binding with (L = 5, ρp = 0.9) as report an adequate persistence pin, given only n = 14 post-hoc TE-2 station-days?
2. Is `f_kill` = the base-rule point the right terminal anchor? And is "no S4 build while UNDERDETERMINED" the right cost trade?
3. Is `FILL_ICC = 0.5/7` acceptable without S2 per-date dispersion data, or should S3 pin max(S2 ICC, 0.5/7)?
4. Is `N_TEMPLATE_DATES = 1000` right? It fixes the outer-SE template term.

## Review disposition

Conflicts:
- **PMR F1 vs simplest path.** PMR F1 asks for a `binding_rows` parameter. I follow the simpler route: `rho_hat = 0.5`, which binds S5 at 0.5 with no code. A binding set is still threaded via `FloorSpec`, but only for S8, whose payoff is PMR F2.
- **Arch F1 and PMR F11** agree: the r1 test becomes a pin, and a true RED is added.

| Review file | # | Disposition |
|---|---|---|
| S3-r1-architect | 1 | ACCEPTED, changed §3.1, WP0, WP1: `g1_unreachable`/`M-yes`; empty groups verified (`sim.py:71-72`, `engine.py:111-119`) |
| S3-r1-architect | 2 | ACCEPTED, changed §3.2: mixes ("M-pool",); `engine.py:355` unchanged; equivalence test |
| S3-r1-architect | 3 | ACCEPTED, changed §3, §4.3: WP2 cut; DEFAULT_FREEZE/HORIZON used as a 110-day label |
| S3-r1-architect | 4 | ACCEPTED, changed WP0, WP1: two documents, outer=2, gate_groups, default-vs-explicit hash, CLI diff minus provenance |
| S3-r1-architect | 5 | ACCEPTED, changed §4.3, WP3: OUTER 20/2000 pinned |
| S3-r1-architect | 6 | ACCEPTED, changed WP1: PATH_FAMILIES alias kept, plus `path_families(spec)` |
| S3-r1-architect | 7 | ACCEPTED, changed WP1: full e2/outer threading |
| S3-r1-architect | 8 | ACCEPTED, changed WP1: canonical `FQ_SPEC` in gate.py; np_bound unchanged |
| S3-r1-architect | 9 | ACCEPTED, changed WP0: constants test replaces the np_bound guard test |
| S3-r1-architect | 10 | ACCEPTED, changed §1, WP4: two JSONs, git_head, clean tree, S2 source lines |
| S3-r1-architect | 11 | ACCEPTED, changed §2 item 3: binding run gated on the window ruling |
| S3-r1-prediction-market-reviewer | 1 | ACCEPTED, changed §4.2: ρ binds at 0.5 via `rho_hat` (see conflict note) |
| S3-r1-prediction-market-reviewer | 2 | ACCEPTED, changed §4.2, WP1: S8 binding, S9 stress, conditionality stated |
| S3-r1-prediction-market-reviewer | 3 | ACCEPTED, changed §4.1, §4.5: 2× rule; terminal on the base point; UNDERDETERMINED route; beta-binomial over-dispersion instead of λ/1.5 (no double count) |
| S3-r1-prediction-market-reviewer | 4 | ACCEPTED, changed §4.4, §10.1: A1 certified; LD-OBF goes to spec v0.3 |
| S3-r1-prediction-market-reviewer | 5 | ACCEPTED, changed §4.3, WP1: worst-feasible G1 path (stricter); all-lose reported |
| S3-r1-prediction-market-reviewer | 6 | ACCEPTED, changed §4.1, WP3: λ_sd, r_sd and tick_share from templates; tests |
| S3-r1-prediction-market-reviewer | 7 | ACCEPTED, changed §4.5, §10.3: one-leg cells down to 0.50; NOT-APPLICABLE rule; B_FLOOR spec input |
| S3-r1-prediction-market-reviewer | 8 | ACCEPTED, changed §4.6: /4 and /5 both recorded, default /5; cite :86-88 |
| S3-r1-prediction-market-reviewer | 9 | ACCEPTED, changed §4.6: separate R4 ruling before 2027-01-25 |
| S3-r1-prediction-market-reviewer | 10 | ACCEPTED, changed §4.5: borderline re-run pinned |
| S3-r1-prediction-market-reviewer | 11 | ACCEPTED, changed WP0, WP1: pin vs true RED |
| S3-r1-prediction-market-reviewer | 12 | ACCEPTED, changed §4.1: rebate sign stated |
| S3-r1-prediction-market-reviewer | 13 | ACCEPTED, changed §1: tripwire meaning; G3(−0.08/−0.04) printed |

MINORs deferred: none. r1 cited-vs-actual mismatches corrected: the §3.2 mechanism, `outer.py:99-112`, `draw.py:216-217`, RA-13 :86-88, and the ρ binding claim.

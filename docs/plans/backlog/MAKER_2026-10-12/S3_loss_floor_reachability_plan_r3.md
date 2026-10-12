# S3 — A1 loss-floor reachability for a maker mix

| Field | Value |
|---|---|
| ID | S3 |
| Title | A1 loss-floor reachability for a maker mix (parameterise the FQ floor tooling) |
| Revision | r3 (supersedes r2; conformance revision to spec v0.3; verdict `reviews/S3-r2-final.md`) |
| Date | 2026-10-12 |
| Status | READY |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` **v0.3** §3, §4, §6.0, §6.1, §6.4, §6.5, §6.7, §7.3, §7.8, §9.8, §9.15 |
| Rulings | `docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md` (T2 route); `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md` |

Hard invariants (binding on every WP):
- Nautilus Trader is immutable. `allow_short` stays False.
- No safety, settlement, contract or NO-SEND test is weakened. Exact-set barriers are only WIDENED by one reviewed row (L-12).
- No value is assigned to max daily budget or max per position. Live enablement and `BREEZY_ORDERS_ENABLED` are untouched.
- No frozen PREREG/amendment JSON is edited (incl. `F5_prereg_v2_amendment_A1.json`, `_A0.json`, `docs/evidence/f5/*`). No pre-registered date moves.
- Stage 0 numbers are exploratory, never promotion evidence. The NO-TRADE ruling stays in force.

## 1. Goal state (acceptance test)

`docs/evidence/maker/A1_REACHABILITY_<run-date>.md` is committed beside `a1_reachability_sweep_seed20261012.json` and `a1_reachability_binding_seed20261012.json`.

The .md records: both JSON sha256s; `git_head` and a clean-tree assertion (`git status --porcelain scripts/analysis` empty); each Stage 0 input, with its S2 artifact path and line; the certified stop object (§4.4): `alpha_star`, `t_min`, `c` (unit-variance form), `c_deff = c/√1.5` (deff-1.5 form), and the equivalence statement.

It states exactly one verdict. The rule is pinned in code before the binding run (§4.5).

| Verdict | Condition | Next action |
|---|---|---|
| `REACHABLE` | every binding cell is `sqrt_boundary` at `f_pass` (2×-rule 95% lower bound) | S4/S5 may start; S5 freezes the §4.4 object |
| `UNDERDETERMINED` | every binding cell passes at `f_kill` (2×-rule point), some cell fails at `f_pass` | no S4 build; one pinned re-run after more census (§4.5) |
| `UNREACHABLE — not registrable` | some binding cell is `unreachable_veto` or `freeze_blocked` at `f_kill` | programme ends at S3 (STOP 2) |

If the power class is `gross_loss_tripwire`, REACHABLE is spelled out: the stop catches collapse (win rate ~0.57–0.65), not the realistic adverse-selection range. G3(−0.08) and G3(−0.04) are printed beside the verdict.

## 2. Entry criteria and STOP conditions

Build half (WP0, WP1, WP3) needs nothing from S1/S2. It uses synthetic templates, reads no tape, and spends no RA-13 B-3 days.

The binding run (WP4 step 3) needs ALL of:
1. **S2 numbers** (spec §6.0, process-schedule simulation, denominator = all covered bid-bearing station-days), under both the base and the 2× rule (2 × (size ahead + 1), spec §6.1/§6.7): the station-day fill rate (share of bid-bearing station-days with ≥ 1 maker fill) as a point estimate and its climate-date cluster-bootstrap 95% CI; the same rate counting only the lowest-p_YES rung (the MAX_RUNGS = 1 rate); the share of filled station-days with two fills; the bid-bearing share of covered listed station-days; the per-date fill ICC; the Stage 0 climate-date count `n0`; the realised bid IQR.
2. **S2 verdict is NOT-KILLED or NOT-KILLED-UNSCREENED** (spec §6.0). NO-GO stops the family before S3's binding run. S3 reads S2's verdict and does not re-judge it.
3. **Window ruling.** A dated coordinator ruling says the maker loss-stop window is a relative 110 days, not the absolute 2027-01-25 (spec §9.15: the PREREG must address the RA-13 review date explicitly). Under the absolute date the window is ~0 days and the run is moot.
4. **Pins committed.** The §4.5 rule and the WP3 pins are committed. Any post-result change is void.

STOPs:
1. S2 verdict NO-GO. The binding run is not run; the sweep stays as context.
2. UNREACHABLE at `f_kill`: not registrable (spec §4); S4 and S5 not started; spec §8 design-history row; NO-TRADE and RA-13 unchanged.
3. `freeze_blocked` (`s6_failed` or refused templates) counts as UNREACHABLE unless a reviewer proves a builder defect. The bar never moves.
4. UNDERDETERMINED twice. There is no third look; the RA-13 horizon decides.

## 3. Simplest direct path

The FQ floor engine already models the maker path: per-leg `x_piece(h, be)` (`fq_loss_floor_mc_rows.py:180-183`); exclusive rung outcomes from one categorical draw (`fq_loss_floor_mc_draw.py:119-141`, `invert_cdf` at `:172-178`); whole climate-date resampling (`fq_loss_floor_mc_sim.py` `simulate_family`).

What blocks reuse is that the FQ mixset, calibration rows and binding set are module constants spread over four files. The direct path:
1. Bundle them into one frozen `FloorSpec` whose default is FQ's, byte-identical.
2. Write a maker template builder.
3. Call `run_floor(spec=MAKER_SPEC)` with a `FloorConfig` on FQ's own `DEFAULT_FREEZE`/`HORIZON`, used as a 110-day label.

Not built (no decision payoff): an epoch code; the NP bound D1 (an A1 veto is terminal, so D1 cannot change a decision); an A0 row (S5); a variance-scale knob in the engine (§4.4 shows it cancels exactly).

Only two engine additions, each with a named payoff:
- **Station persistence** in `simulate_family`. TE-2 losses are same-station runs, and the engine has no serial knob.
- **A worst-feasible G1 path.** `all_lose_z` scores a path two exclusive NO legs cannot take.

### 3.1 Why the FQ mixset vetoes an all-NO world

1. On an all-NO world the M-yes cell is empty. `apply_mix` drops every NO leg (`rows.py:249-256`), and `prepare_mix_groups` skips legless days (`engine.py:103-104`).
2. So `_median_z(cleaned,"M-yes")` is None (`report.py:88-95`), `t_cross` is None, and `g1_holds` is False (`gate.py:87-92`).
3. `select_alpha` then finds no α and returns `unreachable_veto` with `veto_cause="g1_unreachable"` (`gate.py:280-292`) before G3 is read.

Empty prepared groups are safe: `simulate_family` guards only `if not groups` (`sim.py:71-72`); `prepare_mix_groups` appends a list per date (`engine.py:91-108`); `_criticals` handles empty cuts (`engine.py:111-119`). This veto comes from construction, not evidence. WP1 fixes the mix and never the bar.

### 3.2 Which mix: `mixes = ("M-pool",)`

`engine.py:355` hard-codes `cal_sims[("H0","none","M-pool")]` for the carry diagnostic. On all-NO, zero-netting templates M-pool ≡ M-no: `apply_mix(day,"M-pool")` returns the day unchanged (`rows.py:250-251`); `"M-no"` keeps the same legs with netting 0.0 (`:253-256`); netting arises only from paired YES/NO rungs (`rows.py:131-140`), which maker templates never contain. `FloorSpec` requires `"M-pool" ∈ mixes`, `engine.py:355` is unchanged, and a WP1 test pins the equivalence.

## 4. Path model, statistic, bar

### 4.1 Maker path model (one leg = one filled resting NO bid, qty 1, held to settlement)

- **BE and θ.** `BE = b + θ·b·(1−b)` with θ = 0.0695 (taker). The documented venue maker coefficient is a rebate (`errors.py:305` doc), so taker θ overstates BE by ~0.012–0.014: a stricter null, conservative for a harm stop. A positive wire maker fee flips the sign; then the wire θ is used (spec §2, §6.5).
- **P&L.** Win `1 − BE`, loss `−BE`; the fee is paid at fill in both outcomes. An unresolved position past D+14 is a LOSS (spec §6.5), so the loss outcome already covers it; no separate branch. Legs are `make_leg(rung,"no",BE,price=b)` (`rows.py:76-91`). A taker-filled bid (spec §3) is a position on the clock like any other; the stop is P&L-based.
- **Bids.** Every template bid is in [B_FLOOR 0.70, B_CAP 0.80] (spec §3); the builder refuses anything else. At b ≥ 0.70 the H1(−0.16) NO masses sum below 1, so the H1 draw stays categorical.
- **Exclusivity.** At most MAX_RUNGS legs per station-day on distinct rungs, exclusive in loss (`draw.py:54-58`, one categorical draw).
- **Listing, bid-bearing, fills (spec §6.0 denominator).** Each of LAX/MDW/MIA/SFO is listed with probability 0.91 per date (spec §9.15). A listed station-day is bid-bearing with probability β (S2). A bid-bearing station-day fills with probability f_d, where f_d ~ Beta(mean f, `FILL_ICC`) per date. A filled station-day carries 2 legs with probability p₂ (k = 2 cells) and 1 leg otherwise; k = 1 cells use 1 leg and the MAX_RUNGS = 1 rate. Unfilled station-days are absent; fill-less dates stay as empty groups, so the per-date tick rate is honest. S2's fill rate already includes the process schedule (boot, 10 h permit, relaunch cancels; spec §3, §6.0), so S3 does not re-model churn.
- **`FILL_ICC`** = max(S2 per-date ICC, 0.5/7). 0.5/7 gives the spec §6.4 design-effect ceiling 1.5 at 8 rung-trials per date; a lower S2 value would be optimistic and is not used. f is not also divided by 1.5 (double count).
- **Rates from templates.** `lambda_sd` = mean template station-days per date; `r_sd` = mean legs per template station-day; `lambda_pool = take_rate_lower = r_sd·lambda_sd`; so `keep_probability = 1` (`gate.py:129-133`), `T_low = ⌊n·λ_sd·tick_share⌋` (`gate.py:136-142`) counts exactly what the sim ticks, and `tick_share` (`report.py:316-321`) = 1.0 on NO-leg days. Analytic checks within 3 SE: λ_sd = 4·0.91·β·f, r_sd = 1 + p₂ (k = 2) or 1 (k = 1).
- **Adverse selection** is the δ alternative (filled win rate below BE), as in FQ G3.
- **Look order.** The sim ticks by climate date. Spec §4 orders looks by settlement time; every station-day of one date settles D+1 08:00 ET (11:00 ET on a CLI/METAR conflict), so climate-date order equals settlement order up to same-date ties, and within-date order does not change S_t at the date's last tick.

### 4.2 Dependence rows

| Row | Mechanism | Role | Pin |
|---|---|---|---|
| H0, S4 | as FQ | binding | unchanged |
| S5 `bind` | cross-station copula per date (`sim.py:36-47`) at `rho_bind(rho_hat)` (`rows.py:286-289`) | binding | maker `FloorConfig.rho_hat = 0.5` binds at 0.5, above the 0.25 floor; no code change |
| S5 `half` | ρ = 0.5 | report (duplicates `bind`) | unchanged |
| **S8 `persist3`** | per-station factor held for L consecutive simulated days; `u = Φ(√ρp·F_station + √(1−ρp)·ε)` | **binding** | L = 3, ρp = 0.5 |
| **S9 `persist5`** | same | report; false-stop rate at solved c printed | L = 5, ρp = 0.9 |

- **Why a copula and not block resampling.** Synthetic templates carry no outcomes; the outcome is drawn in `advance_prepared` (`draw.py:195-251`). Block-resampling templates cannot make a loss persist.
- **L calibration.** TE-2 records 14 loss station-days in 7 same-station clusters, mean run 2 (`docs/evidence/te2/phase_b/fq_v1_loss_taxonomy_2026-10-12.md`, footer). L = 3 exceeds it.
- **ρp is pinned, not estimated.** The artifact states that **REACHABLE is conditional on station persistence no worse than (L=3, ρp=0.5)**. A Gaussian copula has zero tail dependence, so S9 is the printed stress.
- **Row label.** S8 needs its own label because `binding_max` keys cells by `(row, mix)` (`report.py:177-179`). An unknown row takes the H0 masses path (`draw.py:234-235`).

### 4.3 Statistic and pass bar (same bar as FQ v2)

**Statistic.** The unchanged r3 §4.6 solve, `select_alpha` (`gate.py:266-333`): G1 reach by T_low, with margin ⌊0.8·T_low⌋ at α > 0.10 (`gate.py:80-92`); α ladder {0.10, 0.20, 0.30}, escalating on G1 only; G3(−0.16) ≥ 2.5·α (`gate.py:75-77`, `:316`; core `fq_loss_stop_core.py:47-51`); 10,000 replicates, as FQ A1.

**Outer-SE parity.** The binding run pins `OUTER_RESAMPLES = 20` and `OUTER_REPLICATES = 2000`, as FQ A1 did (`fq_loss_floor_mc_seed20261008.json:1656-1657`; CLI defaults `fq_loss_floor_mc.py:84-85`).

**G1 path.** `all_lose_z` loses every leg (`rows.py:326-334`), a path two exclusive NO legs cannot take. `MAKER_SPEC` uses `g1_path="worst_feasible"`: the minimum x over the categorical outcomes (one leg YES or none). It crosses later, so G1 is **stricter**. All-lose z is printed as context; FQ keeps `all_lose`.

**Deviations from FQ** (each tightening or structural): mix {M-pool ≡ M-no} (spec buys NO only; WP3 asserts `side == "no"`); ρ binds at 0.5, not 0.25; S8 persistence binds; G1 uses the feasible path.

**Window.** `freeze = DEFAULT_FREEZE`, `horizon = HORIZON` (`gate.py:57-58`; `FloorConfig` defaults `:345-348`): 110 inclusive days, epoch offsets {0, 24, 38, 54}, keeping `complete_veto`'s `epoch_grid(freeze)[0]` (`e2.py:231`) correct. The artifact says "window = FQ v2 window 2026-10-08..2027-01-25 used as a 110-day label". The builder refuses any other freeze/horizon.

### 4.4 The certified stop, and the deff-1.5 inflation (spec §4, §7.8; verdict R2)

Spec §4 has **one loss stop**: the A1 sqrt-boundary clock on station-day ticks (production `fq_loss_stop_core`/`fq_loss_stop_clock`), whose variance carries the cluster design-effect inflation (1.5 ceiling). It is a harm stop, outside the RA-13 efficacy α spend. S3 certifies that object; S5 freezes it.

**Option (a) holds: the inflation is a uniform σ rescale and cancels exactly, because c is re-solved on H0.** Evidence from the code:
- A tick is `z = x/σ`, σ = √variance (`fq_loss_stop_clock.py:114-126`). Multiplying every station-day variance by 1.5 multiplies every z by 1/√1.5. Carry is in x units and is unchanged (`:125`, `:132`).
- The stop fires at the first t ≥ t_min with S_t < −c√t (`fq_loss_stop_clock.py:99-111`). The H0 critical value is max_t(−S_t/√t) (`fq_loss_floor_mc_solve.py:34-45`), so every replicate's critical scales by exactly 1/√1.5, and the crossing event {S_t < −c√t} equals {S_t/√1.5 < −(c/√1.5)√t}.
- G1 uses `repeated_crossing(z, c)` and `fully_lost_fraction = c/(|z|√T_low)` (`gate.py:95-106`): both ratio-invariant. G3, S6 and every binding-row rate are crossing rates, hence invariant.
- The tick rule `variance > VARIANCE_EPS = 1e-12` (`fq_loss_stop_clock.py:55`) is unaffected: maker legs have variance ≥ ~0.16.
- The only non-exact step is the solver grid: `smallest_grid_c` rounds c up to `GRID_STEP = 0.01` (`fq_loss_floor_mc_solve.py:31`, `:63-92`). S3 therefore solves on the unit-variance clock (the production `bundle_variance`, untouched) and records `c_deff = c/√1.5` at full float precision. The pair (σ·√1.5, c/√1.5) fires on exactly the same paths as (σ, c), so the PREREG may freeze either form and it is the certified object. No engine knob is added.

**Where the clustered-null risk actually lives.** A uniform rescale cannot protect against clustering: it cancels. The protection is in the H0 calibration rows that set c: the S5 cross-station copula at ρ = 0.5 (binding), S8 station persistence (binding), and beta-binomial fills at `FILL_ICC` ≥ 0.5/7. The artifact says so in one line.

**Test.** WP3 `test_deff_variance_inflation_cancels_in_certified_stop` (production `step_clock` + `first_crossing` + `critical_value` on maker template days, 2,000 seeded paths): (i) z under variance × 1.5 equals z/√1.5 (rel 1e-12); (ii) each critical equals critical/√1.5 (rel 1e-12); (iii) crossing indicators at (c, unit) and (c/√1.5, ×1.5) agree on every path; (iv) `fully_lost_fraction` and `repeated_crossing` agree. `test_artifact_records_c_and_c_deff` pins the reporting. If S5 ever freezes a stop that is NOT a uniform rescale (fixed c, a floor on the increment, a per-station deff), this equivalence no longer holds and S3 must be re-run on that object: §8 guard.

### 4.5 Verdict rule (pinned before the binding run; verdict R1)

**Fill inputs** (spec §4: "must not freeze as `unreachable_veto` ... at the Stage 0 stressed fill rate"):
- `f_kill` = the 2×-rule **point estimate** (the stressed fill rate). A terminal KILL never rests on a lower bound.
- `f_pass` = the 2×-rule **95% lower bound**.
- The base-rule point is printed as context only.

**Binding cells.** k ∈ {2, 1} × each bid in S2's realised bid IQR, rounded outward to the grid {0.70, 0.75, 0.80}; if there is no IQR, all three. MAX_RUNGS = 2 is conditional on the exclusive-conflict admission (spec §3): if that ruling has landed before the binding run, only the admitted k binds; otherwise **all cells must pass** (the stricter unit).

**Report cells (not in the verdict).** θ = 0.08 at `f_pass` on each binding cell (spec §6.7 gated stress; its net-positive gate belongs to S5/§7.5); S9 rates; base-rule point.

**Borderline.** If |G3(−0.16) − 2.5·α*| < 2·binomial SE at 10k, that cell is re-run once at 50,000 replicates with seed 20261013. The re-run is final.

**UNDERDETERMINED** (pass at the 2× point, fail at the 2× lower bound).
- Trigger: once the census adds ≥ `n0` more climate dates, S2 re-emits its numbers and S3 re-runs the binding run once.
- Second look: pass at `f_pass` → REACHABLE; fail at `f_kill` → UNREACHABLE; otherwise STOP 4.
- S4 does not start while UNDERDETERMINED (kill-first; the exec build is the expensive step).

### 4.6 α records (not used by the S3 verdict)

The A1 stop is a harm stop and spends no RA-13 efficacy α (spec §4). For the confirmatory gate (spec §7.3: one-sided lower bound at α_family, nested in the RA-13 ledger, 7-day block clusters) the artifact records α_maker both ways: 0.025/5 = 0.005 (default; Holm/3 0.00167) and 0.025/4 = 0.00625 (Holm/3 0.00208) only if a ruling reassigns the KILLED trigger-4 slot. Cites: RA-13 header :5 and §7 B-2 :86-88. This artifact is an input to a separate dated R4 ruling (RA-13 §3 :53) that must land before 2027-01-25.

## 5. Nautilus null-hypothesis check

| Need | Native capability checked | Covers it? |
|---|---|---|
| Reach/power of a sequential loss stop under H0/H1 | `nautilus_trader/analysis/analyzer.py:38` `PortfolioAnalyzer`: descriptive realised stats only | No |
| Maker fee | `nautilus_trader/adapters/polymarket/fee_model.py:132` `infer_maker_rebate_rate`; Breezy refuses rebates (`errors.py:305`) | Not usable; taker θ by policy |
| Fill simulation | belongs to S2; S3 consumes rates only | N/A |

Nothing new is needed from Nautilus. Breezy's own `scripts/analysis` FQ tooling is parameterised. Nautilus is not touched.

## 6. Work packages

Paths are relative to the worktree `<wt>`. Interpreter: `PYTHONPATH=<wt>/src:<wt> /home/jon/breezy/.venv/bin/python`. Never `uv`/`pip`. WP2 was cut in r2; numbering is kept.

Focused gate (every WP):
```
PYTHONPATH=<wt>/src:<wt> /home/jon/breezy/.venv/bin/python -m pytest \
  tests/unit/test_fq_loss_floor_mc_*.py tests/unit/test_fq_loss_floor_np_bound.py \
  tests/unit/test_fq_kill_power_report.py tests/unit/test_prereg_amendment_check.py \
  tests/unit/test_fq_loss_stop_core.py tests/contract/test_fq_loss_stop_writer_allowlist.py \
  --basetemp ~/.cache/breezy-s3-basetemp -q ; echo EXIT=$?
```
Then: `lint-imports` from `<wt>` ("N kept, 0 broken"); `ruff check`/`ruff format` on touched files only; `git status` for strays; after merge the full gate `scripts/ci/run_tests_no_egress.sh` with basetemp under `~/.cache`; read EXIT, then `rm` the basetemp.

### WP0 — FQ reproducibility pins (characterisation; GREEN on HEAD before any edit)

Create `tests/unit/test_fq_loss_floor_mc_spec_pins.py`. Hashes are sha256 of `json.dumps(doc, sort_keys=True)`; `run_floor`'s provenance args default to None, so the hashes are stable.

| Test | Pins |
|---|---|
| `test_fq_floor_pass_document_hash_is_pinned` | Fixture A, a mixed YES/NO world reaching `sqrt_boundary`; distinct `gate_groups`, `outer_resamples=2`, `outer_replicates=32`, `alphas=None`, `replicates=64` |
| `test_fq_floor_veto_document_hash_is_pinned` | Fixture B, a vetoing world, same knobs; exercises `complete_veto`, `_rows_at`, `_measured`, `_failing_mix` (`e2.py:99-150`, `:220-240`) and `outer.binding_c` (`outer.py:87-125`) |
| `test_fq_module_constants_are_unchanged` | `engine.MIXES == report.MIXES == e2._MIX_ORDER == ("M-pool","M-yes","M-no")`; `engine.PATH_FAMILIES == 60`; `report.py:80` and `outer.py:45` binding sets = {H0, S4, S5-bind} |
| `test_all_no_world_under_fq_spec_vetoes_g1_unreachable_on_m_yes` | characterisation, not RED: `veto_cause == "g1_unreachable"`, `failing_mix == "M-yes"` |

Real-CLI snapshot on HEAD: `fq_loss_floor_mc.py --seed 20261008 --replicates 200 --outer-resamples 2 --outer-replicates 100 --out <scratch>/fq_before.json` under `systemd-run --user -p MemoryMax=5G -p RuntimeMaxSec=3600`; it reads `~/.local/share/breezy/kalshi`. A byte match against `docs/evidence/f5/...seed20261008.json` is impossible (`git_head` changes).

Completion: four tests GREEN on HEAD, hashes committed, `fq_before.json` sha recorded.

### WP1 — `FloorSpec`, persistence, feasible G1 path (FQ default byte-identical)

`fq_loss_floor_mc_gate.py` is the canonical home (report cannot import engine, `engine.py:33`).
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
`__post_init__` raises `ValueError` if: `mixes` is not a non-empty canonical-order subset containing `"M-pool"`; `binding ⊄ cal`; two binding rows share a label; a `persist` mode is not in `cal`.

Changes by file:
- **engine.** `run_floor(..., spec: FloorSpec = FQ_SPEC)` replaces `MIXES`/`_CAL` at `:236-241`, `:266`, `:352`; `_run` passes `persist`. `MIXES` and `PATH_FAMILIES` stay as `FQ_SPEC` aliases (imported by `fq_loss_floor_mc.py:29-30,312` and `np_bound:37,147`).
- **report.** `append_rows`, `evaluate_alpha`, `h1_fallback_table` take `spec`; `_median_z(groups, mix, path)` dispatches the G1 path; `stamp_run` adds `floor_spec` and the all-lose context only when the spec is not `FQ_SPEC`.
- **e2.** `finish_e2` already takes `mixes` (`e2.py:173`); add `binding` for `:195`; `_rows_at`, `_measured`, `_failing_mix`, `complete_veto` take `mixes`, defaulting to `_MIX_ORDER`.
- **outer.** `apply_outer_se` → `solve_resampled` → `binding_c` take `spec`, replacing the lazy `MIXES` import and `_BINDING` (`outer.py:45,99-112`).
- **sim.** `simulate_family(..., persist: tuple[int, float] | None = None)`: per-station factors redrawn every L simulated days, `u = _copula_u(rng, rho_p, F_station)`; `rho` with `persist` raises; `persist=None` leaves the RNG stream untouched.
- **rows.** `worst_feasible_z(day)` = minimum over the `len(legs)+1` categorical outcomes of Σ x_piece, normalised through `step_clock` as `all_lose_z` is.

RED-first tests, appended to the WP0 file:
- `test_run_floor_default_and_explicit_fq_spec_hash_equal`
- `test_run_floor_maker_spec_all_no_world_is_not_vetoed_by_empty_cells` (the true RED)
- `test_floor_spec_rejects_noncanonical_mixes_and_missing_m_pool`
- `test_floor_spec_rejects_duplicate_binding_row_labels_and_binding_outside_cal`
- `test_m_pool_equals_m_no_on_all_no_templates`
- `test_persist_none_leaves_rng_stream_unchanged`
- `test_persist_full_correlation_shares_station_factor_within_block`
- `test_persist_and_rho_together_are_refused`
- `test_g1_all_lose_path_is_infeasible_for_exclusive_no_legs` (worst-feasible z > all-lose z, equals the one-leg-lost z)
- `test_maker_spec_g1_uses_worst_feasible_and_reports_all_lose`
- `test_fq_spec_document_has_no_floor_spec_key`

Completion: WP0 hashes unchanged; existing `test_fq_loss_floor_mc_*` pass; the real CLI re-run with WP0's args produces `fq_after.json`, and `jq 'del(.script_git_sha,.parent_sha,.a0_sha,.git_head)'` of before and after is identical (diff recorded).

### WP3 — maker template builder and CLI

Create `scripts/analysis/fq_loss_floor_mc_maker.py` (≤ 300 lines).
```python
MAKER_SPEC: Final = FloorSpec(mixes=("M-pool",), cal=(*FQ_CAL, ("S8","persist3"), ("S9","persist5")),
    binding=(("H0","none"), ("S4","none"), ("S5","bind"), ("S8","persist3")),
    persist=(("persist3", 3, 0.5), ("persist5", 5, 0.9)), g1_path="worst_feasible")
@dataclass(frozen=True) class MakerMix:
    fill_rate: float; bid: float; rungs: Literal[1, 2]; bid_bearing: float; two_fill_share: float
    fill_icc: float; theta: float = 0.0695
    stations=("LAX","MDW","MIA","SFO"); listing=0.91
B_FLOOR: Final = 0.70; B_CAP: Final = 0.80; DEFF_CEILING: Final = 1.5
def maker_be(bid: float, theta: float) -> float
def build_maker_groups(mix: MakerMix, *, n_dates: int, seed: int) -> tuple[tuple[StationDay, ...], ...]
def maker_floor_config(groups, mix) -> FloorConfig   # §4.1 rates; rho_hat=0.5; FQ window; half_spread=None; pool_exit_fraction=0.0
def run_cell(mix, *, replicates, outer_resamples, outer_replicates, seed) -> dict   # adds c_deff = c/sqrt(DEFF_CEILING)
def verdict(cells_pass, cells_kill) -> str   # §4.5: REACHABLE | UNDERDETERMINED | UNREACHABLE
```
`MakerMix.__post_init__` refuses `bid ∉ [B_FLOOR, B_CAP]`, `fill_icc < 0.5/7`, `two_fill_share > 0` with `rungs == 1`.

Pins: `SEED = 20261012`; `N_TEMPLATE_DATES = 1000`; `SWEEP_REPLICATES = 2000`; `BINDING_REPLICATES = 10_000`; `OUTER_RESAMPLES = 20`; `OUTER_REPLICATES = 2000`; `BORDERLINE_REPLICATES = 50_000`; `BORDERLINE_SEED = 20261013`; `STRESS_THETA = 0.08` (report cell); sweep f ∈ {0.1, 0.2, 0.3, 0.4, 0.5} × b ∈ {0.70, 0.75, 0.80} × k ∈ {1, 2} at β = 1, p₂ = 0.5, `FILL_ICC = 0.5/7`; rung ids are numeric so `rung_temperature` orders them (`rows.py:60-64`).

CLI modes: `--subset-benchmark`, `--sweep`, `--binding --s2-artifact PATH`. Binding mode reads only the §2 item-1 fields, refuses when any is missing, and records their sha and lines. All modes use `apply_address_space_cap`, as `fq_loss_floor_mc.py` does.

RED-first tests in `tests/unit/test_fq_loss_floor_mc_maker.py`:
- **Path model:** `test_maker_be_is_bid_plus_theta_fee`; `test_maker_leg_pnl_win_is_one_minus_be_and_loss_is_minus_be`; `test_two_maker_legs_cannot_both_lose`; `test_h1_bernoulli_fallback_share_is_zero_on_maker_cells`.
- **Templates:** `test_template_listing_bid_bearing_and_fill_rates_match_parameters`; `test_template_fill_overdispersion_matches_pinned_design_effect`; `test_maker_templates_are_all_no_side`; `test_templates_refuse_bid_outside_b_floor_b_cap`; `test_fill_icc_below_ceiling_floor_is_refused`.
- **Rates:** `test_lambda_sd_equals_template_mean_station_days_per_date`; `test_r_sd_times_lambda_sd_equals_template_fills_per_date`; `test_maker_config_keep_probability_is_one`; `test_maker_tick_share_is_one`.
- **Config pins:** `test_maker_config_pins_rho_hat_half_and_fq_window`; `test_other_freeze_or_horizon_is_refused`; `test_binding_run_pins_outer_resamples_and_replicates`; `test_binding_mode_refuses_missing_s2_field`.
- **Deff (§4.4):** `test_deff_variance_inflation_cancels_in_certified_stop`; `test_artifact_records_c_and_c_deff`.
- **Verdict:** `test_verdict_reachable_underdetermined_unreachable`; `test_verdict_kill_reads_stressed_point_and_pass_reads_stressed_lower_bound`; `test_theta_008_cell_is_report_only`; `test_borderline_g3_triggers_one_pinned_rerun`.

Completion: focused gate passes, lint-imports clean, `--subset-benchmark` projection recorded.

### WP4 — sweep, binding run, artifact

1. `--subset-benchmark`: record projected wall time and RSS.
2. `--sweep` at 2000 replicates under `systemd-run --user -p RuntimeMaxSec=<2×projection> -p MemoryMax=5G -p LimitNOFILE=524288`, per-cell progress lines as the stall watch (armed in the launch turn), the only heavy job, outside the nightly-study window. Context only.
3. Once §2 items 1–4 hold, `--binding` the same way at `f_pass` and `f_kill` on the binding cells, plus the report cells; apply the borderline rule.
4. Artifact: verdict and meaning line; certified object (`alpha_star`, `t_min`, `c`, `c_deff`, equivalence line, where the clustered-null risk lives); per-cell table (`floor_mode`, `power_class`, `alpha_star`, c ± `c_mc_se`, `c_deff`, `t_min`, G3 by δ, T_low per epoch, G1 z worst-feasible and all-lose, S8/S9 rates); report cells (θ 0.08, base point); sweep table; α records; θ basis and sign note; window label; persistence condition; both shas, `git_head`, clean-tree line.
5. On UNREACHABLE: spec §8 row and a PROGRESS line. Commit after a gate-green merge; read the gate EXIT before pushing.

## 7. Data and tooling dependencies

| Item | Path | Status |
|---|---|---|
| FQ floor engine + tests | `scripts/analysis/fq_loss_floor_mc_*.py`; `tests/unit/test_fq_loss_floor_mc_{e2,gate,review,rows,solve}.py` | on disk |
| Clock and bar constants | `src/breezy/analysis/fq_loss_stop_clock.py`; `fq_loss_stop_core.py:47-51` | on disk, untouched |
| FQ A1 evidence | `docs/evidence/f5/fq_loss_floor_mc_seed20261008.json` | read-only |
| FQ CLI data (WP0/WP1 diff) | `~/.local/share/breezy/kalshi/` | on disk; run cost UNVERIFIED |
| θ | `F5_prereg_v2_design.json` `theta` 0.0695 | frozen, read-only |
| Stage 0 numbers (§2 item 1) | S2 artifact | **UNVERIFIED / not produced** |
| Listing 0.91 for the 4-station subset | spec §9.15 | **UNVERIFIED**; S1 census |
| Exclusive-conflict admission ruling (k binding) | spec §3 | not issued; default all cells bind |
| Window ruling (§2 item 3) | coordinator | **not issued** |
| TE-2 clusters (L calibration) | `docs/evidence/te2/phase_b/fq_v1_loss_taxonomy_2026-10-12.md` | on disk; post-hoc, n = 14 |

## 8. Risks and guards

| Risk | Invariant at stake | Guard |
|---|---|---|
| WP1 changes FQ A1 reproducibility | frozen evidence | two hashed documents; default-vs-explicit hash; provenance-stripped real-CLI diff; `docs/evidence/f5/` untouched |
| np_bound drift pins relaxed | contract guards | np_bound not modified; aliases pinned in WP0 |
| Laxer window, α grid or multiplier | ruling bar | core constants imported; non-FQ freeze/horizon refused |
| f, bid, ρp, L, ICC or seed chosen after results | forking paths | pinned in WP3 before the binding run; all binding cells must pass |
| Optimistic dependence → c too small | false REACHABLE | ρ 0.5 binding; S8 binding; ICC ≥ 0.5/7; S9 printed; conditionality stated |
| Frozen stop ≠ certified stop (deff applied differently in S5) | spec §4 "exactly the object S3 certifies" | §4.4 equivalence test; artifact records `c` and `c_deff`; any non-uniform inflation forces an S3 re-run |
| Terminal KILL on a lower bound | Stage 0 exploratory | KILL reads the 2× point; the 2× lower bound only gates PASS |
| Agent reformats dirs or touches exec | byte-pinned exec, NO-SEND | "format only your files"; strays check |
| Heavy run collides or OOMs | host | one job; systemd caps; benchmark first; stall watch |

## 9. Effort and evidence artifact

| WP | Agent-hours |
|---|---|
| WP0 | 1.5 |
| WP1 | 3.5 |
| WP3 | 3.5 |
| WP4 | 2, plus compute |
| Review loop | 1.5 |
| **Total** | **~12** |

Evidence: `docs/evidence/maker/A1_REACHABILITY_<run-date>.md` plus the two JSONs.

## 10. Open questions for peer review

1. Is (L = 3, ρp = 0.5) binding with (L = 5, ρp = 0.9) as report an adequate persistence pin, given only n = 14 post-hoc TE-2 station-days?
2. Is "no S4 build while UNDERDETERMINED" the right cost trade?
3. Is `N_TEMPLATE_DATES = 1000` right? It fixes the outer-SE template term.
4. Should the k cells bind on the admission ruling (§4.5) or always both?

## 11. r3 conformance table

| Item (source) | Plan § changed |
|---|---|
| R1 MAJOR: `f_kill` = 2× point, `f_pass` = 2× lower bound; base point context only | §1 table, §4.5, second-look rule, WP3 verdict test renamed, §8 row; old Q2 removed |
| R2 MAJOR: deff-1.5 variance modelled or shown to cancel, with a test | §4.4 (option (a), code evidence, grid caveat, `c_deff`), §1 artifact fields, WP3 deff tests, §8 row |
| R3 MINOR: header v0.3; LD-OBF branch removed; sub-0.70 machinery removed; old §10 inputs 1–5 removed (resolved by v0.3) | header, §4.4, §4.5, WP3 pins/tests (one B_FLOOR/B_CAP refusal test kept), `NOT-APPLICABLE` verdict deleted |
| R4 MINOR: θ 0.08 printed cell; look order vs settlement time | §4.5 report cells, WP3 pin/test, §4.1 look order |
| R5 MINOR: `FILL_ICC = max(S2 ICC, 0.5/7)` | §4.1, `MakerMix` refusal, §2 item 1 |
| Spec §6.0 denominator (bid-bearing station-days), process schedule, verdict table | §2 items 1–2 (NOT-KILLED / NOT-KILLED-UNSCREENED; NO-GO = STOP 1), §4.1 β and p₂ |
| Spec §3 B_FLOOR 0.70, MAX_RUNGS 2 conditional with fallback 1 | §4.1 bids, §4.5 binding cells |
| Spec §4 one loss stop, harm stop outside RA-13 spend | §4.4, §4.6 |
| Spec §6.5 unresolved = LOSS; taker fills | §4.1 P&L |
| Spec §7.3 one-sided at α_family, 7-day blocks | §4.6 |

r1 dispositions (24) were verified present by `reviews/S3-r2-final.md` and are unchanged except where the table above says otherwise.

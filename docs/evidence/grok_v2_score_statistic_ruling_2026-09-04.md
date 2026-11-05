# Grok strategy-lead ruling — v2 interim statistic under drifting break-even, truncation, venue stratum, D0 discriminant (2026-09-04)

Status: RULING (read-only consultation; the CLI's streamed stdout preceding the ruling was garbled and is omitted; the ruling block is verbatim). Amends `grok_prereg_v2_ratification_2026-09-04.md` (1)(a) statistic and (1)(c) information fraction. Binding on PREREG v2 and the Kalshi sibling.

---

**RULING (read-only).** Binding on v2 and the Kalshi sibling. Amends ratification (1)(a) statistic and (1)(c) `t_k`. Does **not** amend `n_max=160`, two one-sided α=0.025, LD-OBF, pooled-only sequential, per-row `BE_i`, v1 byte-identical, never-pool.

**CRITICAL: accepted.** Plug-in `π_k=mean_i(BE_i)` at every look (`PREREG_v2` §3:36-39; ratification:222; blueprint `z_score`:44) plus `t_k=n_k/160` (`PREREG_v2` §4:79) is a homogeneous-Bernoulli / independent-increments table. Under H0, `held_i | ask_i ~ Bern(BE_i)` with `BE_i` known (`decision.py:298`; fee on `ScoredTrial`, `trial_scorer.py:138`). Numerator `Σ(held_i−BE_i)` has independent increments; re-estimated `π_k` and `nπ(1−π)` do not (`x(1−x)` concave ⇒ `nπ(1−π) ≥ Σ BE(1−BE)`). No Type I number is claimed.

### Statistic — **(C)**

```
S_k = Σ_i (held_i − BE_i) / sqrt(Σ_i BE_i(1−BE_i))
I_k = Σ_i BE_i(1−BE_i)
t_k = min(1, I_k / I_max)
```

Looks still fire every 10 filled Takes (`n_k=10,…,160`, pooled only). At each look evaluate `S_k` at **realized** `I_k` and spend `α*(t_k)` (OBF). Generator emits a spending function of `t`, not 16 z-values at equal `n`. Blueprint `z_score(k,n,pi)` is replaced by this score.

**`I_max` pin (before first fill, in the generator input-sha256):** `I_max = n_max × 1/4` with ratified `n_max=160` (ratification:235-236) ⇒ **`I_max = 40`**. That is the Bernoulli bound `p(1−p) ≤ 1/4`, not an empirical mean. Do **not** use live asks, look-1 `π`, archive mean, or realized `I_160`. If `I_k` hits 40 before `n=160`, that look is terminal (`t=1`, remaining α). At `n=160` if `I_160<40`, spend remaining α so terminal `b_eff = z = 1.959963984540054` (`PREREG_v2` §3:58).

**(A) rejected.** No ask-distribution DGP fixture exists (`crh_group_sequential_boundaries.py` absent; fee worked example `test_polymarket_us_fee_model.py:164-179` is not a sequential DGP). A sim under one mix cannot cover selector-endogenous live asks. No Type I / tolerance invented.

**(B) rejected, not as a post-hoc screen.** Freeze-π-at-look-1 **would not** be a v1 §7 / blueprint:48 screen if written into v2 before D0 (registered nuisance, not a row filter; v1 freeze binds v1 only, v1 §7:137-150). It still mis-centers later `Bern(BE_i)≠π_1`. `n=10` is not a null.

Strata: unchanged (1)(d) — station/ask-band stay fixed-rule `cell_dead` at `n≥60` vs `mean(BE_i)` (`PREREG_v2` §6:118-121). Not sequentialized.

### (D) Truncation — remaining α, family **closed**

Clock `D0+165` and loss `ΣPnL≤−60` still truncate (`PREREG_v2` §4:76-77; v1 §6:121-128). Off-grid `n` is a look: **not** `row_for_n` (blueprint:53 `None` between looks) and **not** an unadjusted look-16 `z`.

- Observed information: `t_trunc = min(1, I_trunc/I_max)` (this amends `n_trunc/160`). Architect’s `I ∝ n` is the homogeneous case C just rejected.
- Spending: **remaining** α `= 0.025 − α_spent(last completed scheduled look)` (0.025 if none). Kalshi §6:166-168 (“cumulative alpha spent through that look”) is **wrong**; inherit remaining-α. Then BCa once (`PREREG_v2` §6:125-127).
- **CONTINUE illegal.** Pending excluded from `n` and stop-ΣPnL until scored/fallback, then the terminal look (v1 §6:132-135).
- **D0+165:** KILL **and** SURVIVE both possible. SURVIVE ⇔ `S_k ≥ b_trunc^eff` ∧ `ΣPnL>0` ∧ no `cell_dead` (`PREREG_v2` §3:58-60). KILL ⇔ `S_k ≤ b_trunc^fut` ∨ `cell_dead` ∨ (`b_fut < S_k < b_eff` — fail-closed; family is stopping). Afternoon structural-dead (`PREREG_v2` §9:172-173) stays a separate KILL, not a substitute for the clock.
- **ΣPnL≤−60:** SURVIVE **impossible** (`ΣPnL>0` fails). Family closed → KILL. Efficacy remaining-α is vacuous.

### (E) `venue:` stratum — **REJECT**

Unregistered axis. v1 strata = pooled / station / ask-band only (v1 §5:97-98), frozen (v1 §7:142). (1)(d) did not add venue. Single-venue families, never pooled (ratification:269; Kalshi §8:207-209) ⇒ `venue:*` ≡ pooled. Kalshi-alone `cell_dead` is the sibling’s own pooled + station/ask-band + prefix barrier (blueprint:65-66). Blueprint:71 is the defect its own risk names (blueprint:98). Kalshi §4:117-119 (`venue` on `ScoredTrial`) is **forbidden** — schema is 17 columns, no venue (`trial_scorer.py:119-138`; `scored_trial_store.py:53-72`). Prefix already encodes venue (Kalshi §0:17).

### (F) D0 discriminant — **`climate_day ≥ d0_utc_day`** (LST station-day)

Latch key is `(station, climate_day)` (`trial_day_latch.py:113-114`). Unit of observation is one trial per that pair (v1 §2:41-44). `climate_day` is LST, never DST (`station_observation.py:175-191`; `climate_day.py:6-12,41-53`). `ScoredTrial` has `climate_day` and **no** fill timestamp (`trial_scorer.py:119-138`); `FilledTrial.filled_at_ns` exists (`:109`) but the tally reads `ScoredTrial`. v2 D0 is the first UTC day after spec+tally (`PREREG_v2` §8:151-154).

Offsets (`sites.toml`): MIA `−5.0`, MDW `−6.0`, LAX/SFO `−8.0`. Afternoon `[12:00,17:00)` LST (v1 §2:35-36) ⇒ fill UTC ∈ `{D, D+1}` for climate_day `D`; **never `D−1`**. Blueprint “filled on D0−1 for a D0 climate day” (`:93-95`) **cannot occur**. `climate_day ≥ d0_utc_day` is **conservative** vs “any fill before D0 is v1-only”: Pacific 16:00–16:59 LST on `D0−1` fills 00:00–00:59 UTC **D0** and stays v1.

**Kalshi:** inherit C verbatim (`PREREG_v1_kalshi` §5:129-133). Drop copied `Z_k`/`π_k`/`t_k=n_k/n_max` (`:135-146`). Own `I_k` from own `BE_i`, own `n`, own D0; same `I_max=40` rule. Shadow until θ/rounding pinned.

**v1:** do not touch. Sequential score, `I_k`, remaining-α, and `mean(BE_i)` stay off `live_family_tally.py` (ratification (3):287-289).

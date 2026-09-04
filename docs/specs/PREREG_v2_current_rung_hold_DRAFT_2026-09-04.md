# PREREG v2 — current_rung_hold (Polymarket.us) — group-sequential amendment (DRAFT, ratified-with-amendments 2026-09-04 (rev b))

Status: DRAFT, ratified-with-amendments (rev b). This revision applies the second binding ruling
(`docs/evidence/grok_v2_score_statistic_ruling_2026-09-04.md`), which **amends** ratification
(1)(a) [statistic] and (1)(c) [information fraction] only. It explicitly does **not** amend
`n_max=160`, two one-sided α=0.025, Lan-DeMets O'Brien-Fleming (LD-OBF), pooled-only sequential
monitoring, per-row `BE_i`, "v1 byte-identical," or "never-pool" (ruling line 7). All other
sections carry forward from rev a (`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md`,
the ratified-with-amendments draft) unchanged except where noted.

## 1. Purpose

Unchanged from rev a: replace v1's fixed 60/150 Wilson interim-monitoring rule
(`mb_current_rung_edge_study.py:717,719,723-724`) with a valid alpha-spent sequential design,
without loosening v1's Type I error, terminal decision quantities, or frozen parameters.

## 2. Binding inheritance from v1

Unchanged from rev a. v1's Wilson `z = 1.959963984540054` remains the terminal critical value
(§3 below). Frozen and untouched: strata definition, take rule, per-row BE
(`decision.py:249-256,298-300`), scoring rule, `z`, BCa statistic/`B`/seed/ceiling
(`roi_bound.py:93,97,100,104`), station set. **v1 stays byte-identical** — no clause in this spec
touches `live_family_tally.py`'s existing v1 code path (v1 §7:137-150; ratification "Whether v1
permits computational-defect tally fixes while live" — Not granted; ruling line 51 restates:
"Sequential score, `I_k`, remaining-α, and `mean(BE_i)` stay off `live_family_tally.py`").

## 3. The sequential rule (AMENDED — per-row centred score, not plug-in π_k)

**Why this replaces rev a's `Z_k`.** The first ratification's plug-in statistic
(`π_k = mean_i(BE_i)` re-estimated at every look, `t_k = n_k/160`) is a homogeneous-Bernoulli /
independent-increments table under the false premise that re-estimated `π_k` and `n·π(1−π)`
behave like a fixed-variance walk. The ruling identifies this as **CRITICAL: accepted** —
under H0, `held_i | ask_i ~ Bern(BE_i)` with `BE_i` known per-row (`decision.py:298`; fee already
on `ScoredTrial`, `trial_scorer.py:138`); the numerator `Σ(held_i − BE_i)` has independent
increments, but a *re-estimated* `π_k` and `nπ(1−π)` do not, because `x(1−x)` is concave, so
`nπ(1−π) ≥ Σ BE_i(1−BE_i)` (ruling line 9). Rev a's `π_k`/`n_k`-based statistic is withdrawn.

**Statistic (ruling's option (C), binding):**

```
S_k = Σ_i (held_i − BE_i) / sqrt(Σ_i BE_i(1−BE_i))
I_k = Σ_i BE_i(1−BE_i)                              (observed statistical information)
t_k = min(1, I_k / I_max)                            (information fraction, NOT n_k/160)
```

`held_i` and `BE_i` are per-row, over filled Takes only (v1 §5:105; `live_family_tally.py:139-171`
barrier unchanged). `S_k` is the per-row centred score — never a plug-in mean-based Wald or Wilson
form. Looks still fire every 10 filled Takes (`n_k = 10, 20, …, 160`, pooled only — unchanged
from rev a §6/(1)(d)). At each look, evaluate `S_k` at the **realized** `I_k` (not at a nominal
`n_k`-implied information) and spend `α*(t_k)` per the OBF spending function. The boundary
generator (§7) must emit **a spending function of `t`**, not 16 fixed z-values pinned to equal `n`
— the equal-`t` 16-row table used in rev a is retained **only as a regression fixture**, not the
operative rule.

**`I_max` pin — `I_max = 40`, fixed before first fill.** `I_max = n_max × 1/4` with the ratified
`n_max = 160` (ratification (b), confirmed unchanged) ⇒ `I_max = n_max/4 = 40`. This is the
Bernoulli variance bound `p(1−p) ≤ 1/4`, **not** an empirical estimate. The generator's input
sha256 (§7) must pin `I_max = 40` as a constant. It is forbidden to substitute: live observed
asks, the look-1 `π`, an archive-corpus mean `BE`, or the realized `I_160` from any sample —
`I_max` is the theoretical bound, fixed once, ex ante.

**Terminal and early-stop behavior on `I_k`, not `n_k`.**
- If `I_k` reaches 40 before `n = 160` filled Takes, **that look is terminal**: `t_k = 1`, and the
  full remaining α is spent at that look.
- If `n = 160` is reached with `I_160 < 40` (the realized information fell short of the
  theoretical bound — plausible since real `BE_i` values are typically well below 0.5), spend the
  remaining α at that final look so the terminal boundary collapses to `b_eff = z =
  1.959963984540054` — i.e. the design always closes at exactly v1's fixed critical value,
  whichever of `n=160` or `I=40` triggers it first.

**Boundaries.** Efficacy/futility stop rules are unchanged in form from rev a:

| Direction | H1 | Stop when |
|---|---|---|
| Efficacy / SURVIVE | p > π | S_k ≥ b_k^eff |
| Binding futility / KILL | p < π | S_k ≤ b_k^fut |

Both frozen v1 clauses still gate SURVIVE in addition to crossing `b_k^eff`: ΣPnL > 0 and no
stratum `cell_dead` (§6). Wilson endpoints are still never sequentialized — only `S_k` is
monitored.

**Rejected sub-alternatives within this ruling (see §10 for the full rejected-alternatives list):**
plug-in `π_k` with `t_k = n_k/160` (the original rev-a form) — rejected for lack of independent
increments under a drifting/re-estimated `π_k`; freezing `π` at look-1 — rejected as mis-centering
later rows whose true `Bern(BE_i) ≠ π_1`.

## 4. Truncation (AMENDED — remaining-α on realized information, family closed at truncation)

Unchanged: v1's time stop (D0+165, v1 §6:121-123) and loss stop (ΣPnL ≤ −60 contract-units, v1
§6:124-128) still truncate the schedule. An off-grid `n` at truncation is treated as **a look**,
never as a skipped `None` and never as an unadjusted terminal `z`.

**Observed information at truncation — AMENDED.** `t_trunc = min(1, I_trunc / I_max)`, using the
**realized** `I_trunc = Σ_i BE_i(1−BE_i)` over trials actually scored by truncation — this amends
rev a's `n_trunc/160` (an assumption of `I ∝ n`, which is exactly the homogeneous-Bernoulli
premise (C) rejects). `I_trunc` is computed the same way as any interim `I_k` (§3), just evaluated
at the truncation point rather than a scheduled `n_k`.

**Spending at truncation — AMENDED.** Spend the **remaining** α: `α_remaining = 0.025 −
α_spent(last completed scheduled look)` (= 0.025 if no scheduled look has yet completed). This
corrects rev a's mechanism (there stated as "cumulative alpha spent through that look," which the
ruling identifies as wrong — line 34). The terminal BCa bound is computed once, after this
truncation-look boundary is applied (§6, BCa remains terminal-only).

**CONTINUE is illegal.** A trial still PENDING at truncation is excluded from `n` and from the
stop-rule ΣPnL until scored or fallback-stamped (v1 §6:132-135, unchanged); the family does not
run an additional unplanned look afterward — the truncation look **is** the terminal look.

**D0+165 — both KILL and SURVIVE are possible outcomes**, not KILL-only:
- **SURVIVE** ⇔ `S_k ≥ b_trunc^eff` AND `ΣPnL > 0` AND no `cell_dead`.
- **KILL** ⇔ `S_k ≤ b_trunc^fut` OR `cell_dead` OR (`b_trunc^fut < S_k < b_trunc^eff` —
  **fail-closed to KILL**: the family is stopping at the clock regardless of an inconclusive
  interior score). The afternoon structural-dead stop (§9) remains a **separate** KILL condition —
  it is never a substitute for, or triggered by, the calendar clock.
- **ΣPnL ≤ −60** ⇒ SURVIVE is **impossible** (the ΣPnL > 0 gate fails by construction) ⇒ the
  family is closed as **KILL**; any efficacy remaining-α computation at that point is vacuous
  (there is no scenario in which it could produce SURVIVE).

## 5. BE definition (AMENDED in rev a — v2 only; concave-fee defect; unchanged in rev b)

Carried forward from rev a verbatim. The fee is concave in ask (`fees.py:86-88`), so
`break_even(mean_ask)` (v1's registered analysis BE, `mb_current_rung_edge_study.py:736,743`)
overstates the true hurdle relative to `mean(BE_i)` by Jensen's inequality. v2 registers
`BE_i = entry_ask_i + fee_i` per row (fee already on `ScoredTrial`, `trial_scorer.py:138`), used
both in `S_k`/`I_k` (§3) and in the fixed-rule strata (§6). **v1 is untouched** — its registered
`BE(mean entry_ask)` is frozen by §7:142/147-150 with no computational-defect carve-out.

## 6. Strata — CONFIRMED UNCHANGED (no venue stratum)

Sequential monitoring applies to the **pooled** statistic only. Station and ask-band strata remain
v1's fixed-rule `cell_dead` check at `n ≥ 60` (`mb_current_rung_edge_study.py:717-719`;
`live_family_tally.py:251-253,265-277`), now evaluated against `mean(BE_i)` per §5 — this is
unchanged from rev a and the ruling reconfirms it verbatim ("(1)(d) did not add venue," ruling
line 27, 41).

**`venue:` stratum — explicitly REJECTED.** v1's strata are pooled / station / ask-band only
(v1 §5:97-98), frozen by v1 §7:142; adding a `venue` axis was never registered. Because
Polymarket.us and the Kalshi sibling are single-venue families that are never pooled with each
other (ratification "Kalshi sibling family prereg"; §8 below), a `venue:*` stratum within either
family is definitionally identical to that family's own pooled stratum and adds nothing but an
unregistered axis. **`venue` is forbidden as a column on `ScoredTrial`** — the schema is the fixed
17 columns already defined (`trial_scorer.py:119-138`; `scored_trial_store.py:53-72`); the
live-trial-ID prefix already encodes venue (v1's `current_rung_hold/trial/…` vs the Kalshi
sibling's own prefix) and is the sole provenance signal, exactly as it already is for the
live/paper barrier (`live_family_tally.py:139-171`).

## 7. Boundary generation & pinning (script contract) — AMENDED

`scripts/analysis/crh_group_sequential_boundaries.py` must compute (not author):

- **Inputs (pinned in the generator input sha256):** two one-sided tests at α = 0.025 each;
  LD-OBF spending function of **`t`** (not of `n`); look schedule `n_k = 10..160` step 10, each
  look's `S_k`/`I_k` evaluated at realized per-row `BE_i` (§3, §5); `I_max = 40` (`n_max/4`,
  fixed constant, never re-derived from a sample).
- **Boundary solver, not a fixed table.** Because `t_k = I_k/I_max` depends on the realized sample
  of `BE_i` values rather than a deterministic function of `n_k`, the generator's primary output
  is a **boundary solver** — a function `b^eff(t)`, `b^fut(t)` over `t ∈ [0,1]` — not 16
  precomputed z-values. Live/paper evaluation calls this solver at the look's actual realized `t_k`.
- **Regression fixture only.** The equal-`t` 16-row table (assuming `I_k` accrues exactly
  proportionally to `n_k`, i.e. `t_k = n_k/160`) is retained as a **test fixture** for regression-
  testing the solver's numerical output at a known, reproducible input — it is never the live
  decision table.
- **Also required:** simulated ASN under a real-edge scenario and a leak/no-edge scenario, drawn
  from a genuine ask-distribution DGP fixture that does not yet exist in the repo (ruling line 23:
  "No ask-distribution DGP fixture exists … A sim under one mix cannot cover selector-endogenous
  live asks"). Report this honestly as unbuilt, not approximated by the fee worked example
  (`test_polymarket_us_fee_model.py:164-179`), which is not a sequential DGP.

## 8. Registration & D0 (AMENDED — climate_day discriminant, LST station-day)

v2 is a new family (v1 §7:147-150) — `n` resets to 0, no v1-scored row pools into v2.

**D0 discriminant — `climate_day ≥ d0_utc_day`, not a fill UTC timestamp.** The latch key is
`(station, climate_day)` (`trial_day_latch.py:113-114`); the unit of observation is one trial per
that pair (v1 §2:41-44). `climate_day` is a **local-standard-time (LST) station-day**, never a
DST-shifted day (`station_observation.py:175-191`; `climate_day.py:6-12,41-53`). `ScoredTrial`
carries `climate_day` and **no** fill timestamp (`trial_scorer.py:119-138`) — `FilledTrial.
filled_at_ns` exists (`:109`) but the tally reads `ScoredTrial`, so the discriminant must be
expressed on `climate_day`, not on a fill-time UTC stamp.

D0 itself is still: the first UTC day after (a) this spec is committed and (b) a v2-only tally is
running the §3/§7 boundary solver. The membership test for "is this fill v1 or v2" is:
**`climate_day ≥ d0_utc_day`**. This is deliberately **conservative** relative to a naive
"any fill before D0 is v1-only" reading: because the afternoon decision window is `[12:00,17:00)`
LST (v1 §2:35-36) and station UTC offsets are all negative (`sites.toml`: MIA −5.0, MDW −6.0,
LAX/SFO −8.0), a fill's UTC timestamp for climate_day `D` always falls in `{D, D+1}` UTC and
**never in `D−1`** — e.g. a Pacific-station fill at 16:00–16:59 LST on `D0−1` occurs at
00:00–00:59 UTC on **D0** and is still correctly v1 (its `climate_day` is `D0−1 < d0_utc_day`).
Any earlier wording describing "filled on D0−1 for a D0 climate day" is corrected — the geometry
of the window and the offsets makes that case impossible.

Any fill whose `climate_day < d0_utc_day` is v1-only and reported separately, never merged into
v2's `n`, regardless of its fill UTC timestamp.

**Kalshi sibling.** Own PREREG, own `n`, own D0 (first UTC day after its own committed spec and
its own v2-boundary tally), never pooled with Polymarket.us (ratification "Kalshi sibling family
prereg"). It inherits statistic (C) verbatim: its own `S_k`/`I_k` from its own per-row `BE_i`,
its own `n`, its own D0, the same `I_max = 40` rule. It drops the copied `Z_k`/`π_k`/`t_k=n_k/n_max`
form the earlier Kalshi draft carried over from rev a. Shadow-only (diagnostic, never gating a
verdict) until θ and rounding are pinned on a published fee schedule and one real fill.

## 9. Structural-dead test — unchanged from rev a

Carried forward verbatim (unaffected by this ruling, which is scoped to (1)(a) and (1)(c) only).

| Piece | Definition | Cite |
|---|---|---|
| Window | `[12:00, 17:00)` LST | v1 §2:35-36 |
| Afternoon-covered | span of distinct captured Depth10/quote instants in that window ≥ 30 min; 0–1 instant ⇒ 0 | `ma_prelock_winner_ask_study.py:160,323-332,360-361` |
| Listed | venue listed that station-day; skip-days excluded from denominator | v1 §2:45-47 |
| Denominator | covered listed station-days of the family set (LAX, MDW, MIA, SFO) | v1 §2:32 |
| Fire at | count ≥ 15 | `MIN_AFTERNOON_STATION_DAYS = 15`, `ma_prelock_winner_ask_study.py:163`; v1 §5:105 |
| "≈0" | filled Takes = 0 on those days; one fill kills this stop (L-9) | analogous to `mb_current_rung_edge_study.py:54-58` |

Distinct from, never a substitute for, the D0+165 clock stop (§4). `all_visited_cells_dead_by_
construction` (`mb_current_rung_edge_study.py:683-697`) is archive-only, not this test.

## 10. Rejected alternatives (AMENDED — two new entries from this ruling)

Carried forward from rev a (SPRT at α=0.05/β=0.20; sequential rule on the BCa ratio-of-sums;
unspent Wilson peeks; calendar-time information fraction), plus:

- **Plug-in `π_k = mean_i(BE_i)` with `t_k = n_k/160`** — rejected: `nπ(1−π)` re-estimated at each
  look does not form an independent-increments sequence under a drifting per-row `BE_i`, because
  `x(1−x)` is concave; only the numerator `Σ(held_i − BE_i)` has that property, hence the switch to
  the centred score `S_k` (§3).
- **Freeze `π` at look-1** — rejected: would not itself be a v1-frozen-parameter violation if
  registered before D0 (it is a v2 nuisance parameter, not a v1 row filter), but it still
  mis-centres later rows whose true `Bern(BE_i) ≠ π_1`, and `n=10` is too small a sample to serve
  as a stable null estimate.

## 11. Implementation gap list (AMENDED)

| Item | Module | Missing test |
|---|---|---|
| Boundary solver over arbitrary `t` (not a fixed 16-row table) | new file `scripts/analysis/crh_group_sequential_boundaries.py` — does not exist | none — write RED-first with the equal-`t` regression fixture (§7) |
| `I_k` accumulation (`Σ BE_i(1−BE_i)` per look, realized, not `n_k`-derived) | new helper alongside `build_realized_stratum` (`mb_current_rung_edge_study.py:727-746`); must not alter v1's function | no test found |
| `S_k` per-row centred score evaluation wired into a v2-only live tally | new module or new mode on `live_family_tally.py` (current `build_live_family_tally`, lines 229-301, is v1's fixed rule only; must not be mutated) | no test found |
| Truncation as a terminal look (`I_trunc`, remaining-α, `t_trunc`) | not present anywhere | none |
| `mean(BE_i)` for the fixed-rule station/ask-band strata (v2 only) | new helper, must not alter v1's `build_realized_stratum` | no test found |
| Structural-dead check (§9), implementable on v1 now | `live_family_tally.py` — no afternoon-covered-station-day counter anywhere in `:229-301` | no `test_live_family_tally_structural_dead*` found |
| Ask-distribution DGP fixture for ASN simulation | does not exist (ruling line 23) | none |

## 12. Not touched on live v1 — unchanged

| If applied to v1 | Why post-hoc |
|---|---|
| Sequential `S_k`/`I_k`, `n_max=160`, spending-to-horizon, boundary solver in `live_family_tally.py` | Replaces frozen 60/150 Wilson (v1 §5:101-104, §7:142) |
| mean(BE_i) in the v1 tally / expansion-plan S2 | Changes registered `BE(mean entry_ask)` (v1 §5:101, §7:142,147-150) |
| Adding stations, Kalshi rows, a `venue` stratum or column | Frozen station set (v1 §2:32, §7:143); sibling never pooled; `venue` unregistered axis (§6) |
| Lowering floors, peeking Wilson, sequential BCa, Wald interval | v1 §5:112, §6:130-131, §7:143-144 |
| Extra structural-dead ε / Wilson-on-take-rate | New screen (blueprint:48) |

**Allowed on v1:** implement the already-registered structural-dead pin (§9); ALERT-only corpus
hash check (v1 §7:144-145). The §8 D0 rule stands: any fill with `climate_day < d0_utc_day` is
v1-only.

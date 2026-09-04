# Grok strategy-lead ratification — PREREG v2 amendments, Kalshi sibling-family prereg, structural-dead pin, 2026-09-04

Status: RULING (read-only consultation; verbatim). Binding on: v2 statistic (Wilson score Z with OBF boundaries, two one-sided α=0.025, n_max=160, t_k=n_k/160, pooled only), BE defect = v2 only (fee is CONCAVE; v1 byte-identical), structural-dead pin (implementable on v1), Kalshi admission gate (cadence 90%-of-days rule as applied; per-station CLI-final vs venue-settled n≥90, Wilson-lower agreement >0.99), same-city fills admissible in each family.

---

## Grok models auth check (run twice, verbatim)

```
You are logged in with grok.com.

Default model: grok-4.6

Available models:
  * grok-4.6 (default)
  - grok-4.5
```
(second run identical)

## Grok's ruling (verbatim, in delivered order — full transcript)

I'll rule from the repo evidence, not from memory. First I'll read the v2 draft and the live v1/tally/Kalshi measurements in parallel so the statistic, n_max, break-even, and sibling-family calls are pinned to file:line.Repo is `feat/data-capture-and-risk` with the v2 draft and Kalshi measurements still untracked. Next I'll read those plus the live tally and v1 clauses so the ruling is pinned to file:line.I'll read the named evidence/plan docs and search Kalshi fee plus Polymarket settlement-truth files in parallel.I'll pull the v1 spec and today's strategy-ruling evidence first, then quote every binding clause with file:line.I'll gather the cited files and formulas first so the defect can be documented from evidence only.Spec is in hand. Next I'll locate today's A2 ruling and the v1 freeze/tally clauses that mention sequential monitoring.Next I'll pull the Kalshi θ=0.07 UNVERIFIED cites and the Polymarket four-station CLI-vs-venue settlement numbers.Codegraph is required for symbol lookup; I'll fetch its schema and query the cited files.Next I'll pull the fee formula, stratum BE, cadence rule, and decision selector.v1 and the tally path are in hand. Next I'll pin spec-rev2 structural-dead, Kalshi M1/M2, cadence, and the four-station reconciliation so the remaining clauses aren't inferred.

**Defect:** tally BE is `break_even(mean_ask)`, not `mean(ask_i + fee_i)`. Fee is **concave** in ask, so Jensen applies.

### Formulas (file:line)

| What | Formula | Where |
|---|---|---|
| Study BE | `ask + FEE_THETA * ask * (1.0 - ask)` | `/home/jon/breezy/scripts/analysis/mb_current_rung_edge_study.py:179-181` |
| Stratum BE | `mean_ask = sum(entry_ask)/n`; `break_even=break_even(mean_ask)` | same file `:736-743` |
| Venue fee | `theta * C * p * (1 - p)`, bankers to cent | `/home/jon/breezy/src/breezy/adapters/polymarket_us/fees.py:83-86,163,200,238-239` |
| Selector BE | `break_even = ask + _fee(ask, fee_coefficient)`; `_fee`: `fee_coefficient * ask * (1 - ask)` quantized `ROUND_HALF_EVEN` to cent | `/home/jon/breezy/src/breezy/strategy/current_rung_hold/decision.py:249-256,298-300` |
| PnL (scorer) | `1{held} − fill_px − fee` | brief `/home/jon/breezy/docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md:23` |

**theta:** module constant `FEE_THETA: Final[float] = 0.06` at `mb_current_rung_edge_study.py:174-176`. Adapter has **no** module default (`fees.py:90-92`); per-market `instrument.info`.

**Convex?** **No — concave.** `fees.py:86-88`: "The function is concave with a maximum at `p = 0.50`". Tests pin `p(1-p)` symmetry (`test_polymarket_us_fee_model.py:164-179`).

### live_family_tally BE

**Yes, via the shared helper on mean ask** — it does not recompute BE itself.

- Imports `break_even`, `build_realized_stratum` (`live_family_tally.py:47-54`); re-exports `break_even` (`:71`).
- `:184`, `:197`, `:248` all call `build_realized_stratum(...)`, whose body is `break_even=break_even(mean_ask)` (`mb_current_rung_edge_study.py:743`).
- Spec test name: `test_break_even_uses_the_shared_helper_at_the_published_mean_ask` (brief `:70`).

### Structural-dead: **not implemented** in tally `:229-301`

M_B structural check (`:683-697`): every tape-visited cell `n/a` / `m=1` / open-lower; `evaluate_mb` kills on `all_visited_cells_dead` (`:817-823`).

`build_live_family_tally` only: `cell_dead` = Wilson-upper < stratum BE at `n>=60` (`:251-253,256-262,265`); SURVIVE adds `SigmaPnL > 0`. No `all_visited_cells_dead_by_construction`.

### Cadence (`config.py:16-29`)

`/home/jon/breezy/src/breezy/strategy/current_rung_hold/config.py:16-29`:

> `SUPPORTED_STATIONS` is exactly the four dense stations the archive study (`archive_table.py`) was measured on. NYC/KNYC is deliberately excluded: it is an HOURLY-only station (no 5-minute NWS feed), so the `stale_observation_minutes` bound this package pins (50 min, rev 3's `max(K_B_REQUIRED_LAGS_LIVE) + 5 min ASOS cadence`) is miscalibrated for it — see the spec's `stale_observation_hours` table, which gives KNYC its own, larger, NOT-YET-ADOPTED bound and states "Not this package". Constructing with any station outside the allow-list is refused loudly (`UnsupportedStationError`) rather than silently ignored — a mis-wired KNYC must fail at startup, not trade on a stale-declared-fresh observation forever.

(`STALE_OBSERVATION_MINUTES = 50` at `:78-86`.)

### Selector vs tally

`evaluate_decision` step 9 (`decision.py:48-49,298-300`): **per-quote** `p_hold_lower > ask + fee(ask)` else `edge_below_break_even`. Tally hurdle is **BE of mean ask**, not mean of per-row BEs.

### Per-row vs `break_even(mean)` (from existing hand-calcs, not invented)

`test_polymarket_us_fee_model.py:164-179` (`C=100`, `θ=0.06`):

- `0.06*100*0.50*0.50 = 1.50` → per-contract fee `0.015`; BE=`0.515`
- `0.06*100*0.10*0.90 = 0.54` → fee `0.0054`; BE=`0.1054`
- `0.06*100*0.90*0.10 = 0.54` → fee `0.0054`; BE=`0.9054`

Two rows `{0.10, 0.90}`: `mean_ask=0.50` → `break_even(mean)=0.5154`; `mean(BE_i)=(0.1054+0.9054)/2=0.5054`. Concave fee ⇒ `E[fee(ask)] ≥ E[fee](E[ask])` ⇒ pooled BE is too high vs `BE_i = entry_ask_i + fee_i`.

**Scope:** binding clauses from `/home/jon/breezy/docs/specs/PREREG_v1_current_rung_hold_2026-09-04.md`. Related citations only where v1 points at them. No recommendations.

### Family identity / freeze / repair
- **§3–6** pre-registered **BEFORE the first live order**.
- **§7:137–150** "What will NOT change after the first order" — frozen for the life of this family: every `config.py` default in §3; frozen table (`P_HOLD_LOWER`, 240 cells, `CORPUS_SHA256`, `STUDY_GIT_SHA`); rule order and closed refusal-reason set; **BE formula and rounding mode**; **scoring rule**; **strata**; **`z`**; **60/150 thresholds**; **BCa statistic, `B`, seed and 0.20 ceiling**; **station set**. "No floor is lowered and no post-hoc screen is added (blueprint §7 standing refusal)."
- **§7:147–150** "any change to a **parameter, the table, or a threshold** requires a **NEW** pre-registration document (`PREREG v2 — …`) … the family **restarts** — `n` resets to 0 and trials scored under v1 are never pooled with v2 rows. **Amending v1 in place is prohibited.**"
- **v1 does not** name "computational defect," "bugfix," or "tally repair." No carve-out for live-family tally edits.

### Full v1 §5 (structural-dead + kill/survive)
**95–112:**
- Strata: pooled, per-station, per entry_ask band `(0.05,0.15]`, `(0.15,0.30]`, `(0.30,0.95)`.
- Interval: Wilson, `z = 1.959963984540054` — "a second Wilson implementation is a defect."
- **KILL:** pooled `n ≥ 60` with Wilson **upper** < **`BE(mean entry_ask)`**, or any stratum `n ≥ 60` dead (`POOLED_KILL_N_MIN=60`, `STRATUM_KILL_N_MIN=60`).
- **SURVIVE:** pooled `n ≥ 150` AND Wilson **lower** > `BE` AND no dead stratum AND **ΣPnL > 0**.
- Else **UNDERPOWERED**. **"Structural dead: live taken ≈ 0 over ≥ 15 afternoon-covered listed station-days (spec rev2 §6)."**
- ROI bound: `θ = ΣPnL / Σcost`, BCa `B=10_000`, seed `20260904`; Wald never printed.

**Related kill/refuse:**
- **§6:115–116** KILL → stop immediately; no ΔT / month / forecast resurrection.
- **§6:121–123** D0+165 without n=150 is a structural-dead stop.
- **§6:130–131** "Do NOT lower the n floors."
- **§2:45–47** venue skip-days not Wilson zeros; archive never pooled into live tally.
- **§3:51–58** standing refuse path (latch, fee mismatch, obs unavailable/ambiguous, illegal_cell, not_executable, p_hold_undefined, edge_below_break_even).
- **§4:81–90** FINAL-only scoring; fallback excluded, never pooled with NWS-keyed rows.

**Rev2 cited by §5** (`docs/evidence/grok_live_small_spec_rev2_2026-09-04.md:139`): "Do not lower n floors. … Falsify: KILL, or SURVIVE fails at n≥150, or **live taken≈0 over ≥15 afternoon-covered listed station-days**. Then stop this book class; no ΔT/month/forecast resurrection."

Blueprint standing refusal (`docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md:48`): "standing refusal: no floor lowered, no post-hoc screen."

### BE / fee / θ / tally
- **Take (per-row):** **§3:66–67** `fee(ask) = ROUND_HALF_EVEN_to_cent(0.06 · ask · (1 − ask))`; **`BE(ask) = ask + fee(ask)`**. Worked example ask=0.40 → BE=0.41.
- **Hypothesis / KILL / SURVIVE (stratum):** **§1:26–27** realized hold vs **`BE(mean entry_ask)`**; **§5:101** Wilson upper vs **`BE(mean entry_ask)`**.
- **§4:91–93** ask-band, `mean_ask` and **`break_even` use decision-time `entry_ask`**; `pnl` uses `fill_px`.
- **BCa θ** is **not** fee θ: **§5:107–108** `θ = ΣPnL / Σcost`. Fee θ frozen as `required_fee_coefficient=Decimal("0.06")` (**§3:61**).
- **v1 defines analysis BE as `BE(mean entry_ask)`, not mean of per-row `BE_i`.**

### Sequential / n_max / Lan-DeMets / Wilson
**v1 never mentions** sequential monitoring, n_max, Lan-DeMets, O'Brien-Fleming, alpha-spending, or unspent peeks. Wilson is the **fixed** 60/150 rule only.

### Shadow / Kalshi / new stations / n floors
**Absent from v1** except: stations frozen to LAX/MDW/MIA/SFO, NYC excluded (**§2:32–34**, **§7:143**); archive never pooled (**§2:46–47**); n floors not lowered (**§6:130–131**). No shadow-trial or Kalshi-pooling clause.

### Byte-identical / registered-before-fill / post-hoc / amendment / v2
- Header **3–4**: registered before first live order.
- **§7:143–144** no post-hoc screen.
- **§7:144–145** nightly corpus-hash ALERT-ONLY (blueprint amendment 5) — not a runtime refusal.
- **§7:147–150** change → **PREREG v2**, restart, no pooling; in-place amendment prohibited.
- **"byte-identical" does not appear in v1.**

### docs/evidence search: A2 Lan-DeMets O'Brien-Fleming on Wilson
**No matches** in `docs/evidence/**` for `Lan-DeMets`, `O'Brien-Fleming`, or group-sequential. That ruling is **not** in evidence. Repo occurrence is only the later draft `docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md:45,79,122` (cites a Grok ruling; not an evidence file). Same-day evidence ruling on file is **rev3 (A)** stale-bound (`docs/evidence/grok_live_small_spec_rev3_delta_2026-09-04.md:22`), not A2 sequential.

### Whether v1 permits computational-defect tally fixes while live
**Not granted.** Frozen scoring/BE/z/60/150/BCa; any parameter/table/**threshold** change requires **new family**; amending v1 in place prohibited. Changing how the live tally computes BE (or Wilson) while v1 is live would be an in-place analysis change against **§7:137–150**.

## Kalshi OPEN daily high + low

| Item | Value | Cite |
|---|---|---|
| Climate series listed | 369 | `KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md:7` |
| Daily `KXHIGH*`/`KXLOW*` series | **102** | `:8,11` |
| **OPEN today (high AND low)** | **24 cities × both series = 48 series** (2 open events each) | `:12` |
| Zero-open daily series | 54 (intl + dormant US dups) | `:47` |
| `fee_type` | `"quadratic"` on **all 102** | `:11` |
| `fee_multiplier` | **1** on all 102 | `:11` |
| `settlement_sources` (open daily) | **"The Weather Company"** (every row in table) | `:15-40` |
| Legacy non-`KX` (`HIGHNY` etc.) | `National Weather Service` (pre-2023) | `:48` |
| NWS CLI ids (quoted from `rules_primary`) | CLIATL, CLIAUS, CLIBOS, **CLIMDW**, CLIDFW, CLIDEN, CLIHOU, CLILAS, CLILAX, CLISDF, CLIMIA, CLIMSP, CLIMSY, CLINYC, CLIEWR, CLIOKC, CLIPHL, CLIPHX, CLISAT, CLISAN, CLISFO, CLISEA, CLITTN, CLIDCA | `:17-40` |

## Five known vs 19 new

**Known (all present):** NYC `KXHIGHNY`/CLINYC, MIA `KXHIGHMIA`/CLIMIA, Chicago `KXHIGHCHI`/**CLIMDW**, LAX `KXHIGHLAX`/CLILAX, SFO `KXHIGHTSFO`/CLISFO.
**19 candidates:** ATL, AUS, BOS, DFW, DEN, HOU, LAS, SDF, MSP, MSY, EWR, OKC, PHL, PHX, SAT, SAN, SEA, TTN, DCA.
Cite: enumeration `:13-14`; plan `:13,64`.

## Cadence (2025-07, 12:00–17:00 local; n=30 days)

Pass text in file: median-of-daily-medians ≤5 min **AND ≥90% of days ≤5 min** (`kalshi_station_cadence_2026-09-04.md:9`). Enumeration/plan cite `config.py:16-29` as **≥95%** (`enumeration:3`; plan `:56`).

| ICAO | CLI | % days ≤5 | median gap | verdict |
|---|---|---|---|---|
| KATL | CLIATL | 96.7 | 5.0 | PASS |
| KAUS | CLIAUS | 100.0 | 5.0 | PASS |
| KBOS | CLIBOS | 100.0 | 5.0 | PASS |
| KDFW | CLIDFW | 100.0 | 5.0 | PASS |
| KDEN | CLIDEN | 100.0 | 5.0 | PASS |
| **KHOU** | CLIHOU | **83.3** | 5.0 | **PASS-WITH-CAVEAT** (5 archive-gap days; populated days still 5.0) |
| KLAS | CLILAS | 100.0 | 5.0 | PASS |
| KSDF | CLISDF | 100.0 | 5.0 | PASS |
| KMSP | CLIMSP | 100.0 | 5.0 | PASS |
| KMSY | CLIMSY | 100.0 | 5.0 | PASS |
| KEWR | CLIEWR | 100.0 | 5.0 | PASS |
| KOKC | CLIOKC | 100.0 | 5.0 | PASS |
| KPHL | CLIPHL | 100.0 | 5.0 | PASS |
| KPHX | CLIPHX | 100.0 | 5.0 | PASS |
| KSAT | CLISAT | 100.0 | 5.0 | PASS |
| KSAN | CLISAN | 100.0 | 5.0 | PASS |
| KSEA | CLISEA | 100.0 | 5.0 | PASS |
| KTTN | CLITTN | 100.0 | 5.0 | PASS |
| KDCA | CLIDCA | 100.0 | 5.0 | PASS |
| **KLAX** (control) | CLILAX | **100.0** | 5.0 | **PASS** |
| **KNYC** (control) | CLINYC | **0.0** | **60.0** | **FAIL** (hourly) |

Cite: cadence `:17-38`. 83.3% fails both 90% and 95% bars. CLIHOU = Hobby **KHOU** not Bush (`plan:216`).

## Winter month

**Not measured.** Cadence `:48`: "One sample month only (2025-07). Re-run for a winter month before pinning." Plan addendum `:216`: 2025-01 (all) + KHOU 2025-10 "being measured now" — no winter evidence file in `docs/evidence/`.

## Kalshi θ / taker coefficient

**UNVERIFIED 0.07.** Used as K1 input only.
- Plan status: `KALSHI_INTEGRATION_PLAN_2026-09-03.md:77` §5.2 **UNVERIFIED** (secondary source; needs published schedule + one fill).
- Same: CRH plan `:45,71`; `k1_kalshi_prior_2026-09-02.md:9`; `kalshi_history_as_k1_prior_2026-09-02.md:17,62-63` (maker 0.0175 also UNVERIFIED).
- **VERIFIED:** functional form only — `fee_type="quadratic"`, `fee_multiplier=1` (`INTEGRATION:76`; enumeration `:11`). Rounding-up §5.4 UNVERIFIED; settlement-leg fee §5.5 MISSING.

## Polymarket four-station CLI-final vs venue-settled

**No measured CLI-final vs venue-settled rate found** for LAX/MDW/MIA/SFO. Enumeration `:45` and plan `:59` say "do not inherit the four-station divergence rate" but cite no n or %. Closest:

| What exists | Result | Not this question because |
|---|---|---|
| `THRESHOLD_SEMANTICS_2026-08-25.md:172-178` | NYC 2026-04-23 CLI tmax=73; `gte72lt73f` **YES** (n=1) | NYC, n=1, inclusive-bounds proof |
| `k1_cheap_open_2026-09-01.md:123-127` | **MEASURED POPULATION = 0** (24 no CLI, 6 PRELIM) | no venue join |
| `settlement_alignment_2026-08-25.md:38-44` | METAR vs CLI, 2021-01-01..2025-12-31: LAX 342/7280 mismatch (0.953), MDW 376/7304, MIA 272/7252, SFO 346/7196, NYC 7/7256 | **ASOS/METAR vs CLI**, not venue cash |
| `pmr_climatology_2026-09-01.md:142-148` | P(|Δ|≥1) LAX 43.9% / MDW 35.7% / MIA 40.5% / SFO 41.2% (NYC 56.0%) | same METAR↔CLI basis |
| `paper_replay_current_rung_hold_2026-09-04.md:39-41` | 1 scored trial, `settlement_basis=nws_final` | no venue settlement field |
| `EXEC_SPINE_2026-09-01.md:861-868` | divergence rate **to be reported** after R-9 | planned, not measured |

## Take rate ~1/4

**Stated, observed 09-01 only:** ~1 taken trial / 4 station-days ≈ **0.25/station-day**.
- CRH plan `:17`: "~1 taken trial/day on 09-01 at 4 station-days (≈0.25/station-day)" vs archive-implied ~3/day (`mb_current_rung_edge_2026-09-02.md:246`). Projections use 0.25.
- `venue_city_census_2026-09-03.md:45`: "taken/covered ratio **(1/4 on 09-01)**".
- `grok_live_small_spec_rev2_2026-09-04.md:131`: "09-01 was 1/4 covered".
Kalshi take rate: **unknown** (plan `:145`).

## Final ruling

**AMEND, then register v2 as a new family before the first fill.** v1 stays byte-identical. Kalshi is a sibling, never pooled. Same-city fills on both venues are both admissible.

### (1) Draft `docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md`

**(a) Statistic — AMEND the Wald label.** The formula at draft §3:39 is the **Wilson score**, not Wald.

Pin:
- Z_k=(p̂_k−π_k)/sqrt(π_k(1−π_k)/n_k)
- p̂_k=k/n_k on filled Takes only (v1 §5:105; `live_family_tally.py:139-171`)
- **v2** π_k=mean_i(BE_i), BE_i=entry_ask_i+fee_i (fee already on `ScoredTrial`)
- Wald would put p̂ in the variance; Wilson interval (`archive_correction_probe.py:66,352-363`) is the inversion of this score. v1 kill/survive (`mb_current_rung_edge_study.py:717-724`) is that inversion at fixed z=1.959963984540054.

**Boundary form.** Lan-DeMets O'Brien-Fleming, looks n_k=10,20,…,160. Two one-sided tests, each α=0.025, matching v1's two-sided Wilson used one-sided each way (draft §2:21-25; v1 §5:99-104):

| Direction | H1 | Stop when |
|---|---|---|
| Efficacy / SURVIVE | p>π | Z_k≥b_k^eff |
| Binding futility / KILL | p<π | Z_k≤b_k^fut |

Terminal b_16^eff=z. Plus frozen ΣPnL>0 and no `cell_dead` (draft §5:88-92). BCa remains terminal-only (draft §5:93-96). Do not sequentialize Wilson endpoints; sequentialize Z_k.

**(b) n_max=160 — CONFIRM.** Smallest multiple of 10 ≥154; look 15 is v1's n=150 (`mb_current_rung_edge_study.py:206`). No uneven last look.

**(c) Information fraction — CONFIRM t_k=n_k/n_max.** Not calendar t/165. Truncation (D0+165 or ΣPnL≤−60, v1 §6:121-128) spends remaining α at n_trunc/160, then BCa. Draft Q2's "calendar-time information fraction" is rejected.

**(d) Sequential on pooled only — CONFIRM.** Station/ask-band stay fixed-rule `cell_dead` at n≥60 (v1 §5:101-102; `live_family_tally.py:251-253,265-277`). v2 uses mean(BE_i) in those strata too.

**(e) BE defect — (i) v2 only. v1 tally stays byte-identical.**

v1 **registered** analysis BE as `BE(mean entry_ask)` (v1 §1:26-27, §5:101-104). Code matches: `break_even(mean_ask)` at `mb_current_rung_edge_study.py:176,179-181,743` via `live_family_tally.py:184,197,248`. Per-row take BE is different and already correct (`decision.py:249-256,298`).

Clause: v1 §7:142 freezes "the BE formula and rounding mode"; §7:147-150 "any change to a parameter, the table, or a **threshold** requires a NEW pre-registration… Amending v1 in place is prohibited." Blueprint standing refusal: "no floor lowered, no post-hoc screen" (`CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md:48`). No computational-defect carve-out exists.

Correction (fee is **concave**, not convex — `fees.py:86-88`; Jensen fee(E[a])≥E[fee(a)], so `break_even(mean_ask)` **raises** the hurdle): register in v2 as BE_i=entry_ask_i+fee_i, stratum π=mean(BE_i). AMEND draft §2:26-29 and §7:123-125, which currently freeze v1's mean-ask BE.

**(f) Structural-dead — pin for RED-first (unimplemented in `live_family_tally.py:229-301`).**

v1 §5:105-106 cites spec rev2 §6:139. Numeric pin from the cited machinery, not a new screen:

| Piece | Definition | Cite |
|---|---|---|
| Window | [12:00,17:00) LST | v1 §2:35-36 |
| Afternoon-covered | span of distinct captured Depth10/quote instants in that window ≥30 min; 0–1 instant ⇒0 | `ma_prelock_winner_ask_study.py:160,323-332,360-361` |
| Listed | venue listed that station-day; skip-days ∉ denominator | v1 §2:45-47; spec:119 "listed" |
| Denominator | covered **listed** station-days of the family set (PM: LAX, MDW, MIA, SFO) | v1 §2:32 |
| Fire at | count ≥15 | `MIN_AFTERNOON_STATION_DAYS=15` (`:162`); v1 §5:105 |
| "≈0" | **filled Takes =0** on those days. One fill kills this stop (L-9 "no seller", spec:119). Not a Wilson take-rate test. | M_B kill `mb_current_rung_edge_study.py:54-58` |

Distinct clock stop, already registered: D0+165 without n=150 (v1 §6:121-123). Do not add ε>0 or Wilson-on-take-rate to v1.

AMEND draft §9 to this pin. `all_visited_cells_dead_by_construction` (`:683-697`) is archive-only; not this test.

### (2) Kalshi sibling family prereg

**Family.** `current_rung_hold` / Kalshi. Own PREREG, own n, own D0 = first UTC day after committed sibling spec **and** a Kalshi-only tally running v2 boundaries. Never pool with PM (`KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md:7-11`; `mb_current_rung_edge_2026-09-02.md:244`). Shadow diagnostic-only (plan:21).

**Selector/scoring.** Same `config.py` / `decision.py` order. θ per instance: `required_fee_coefficient=Decimal("0.07")`, rounding "up" — both **UNVERIFIED** (`KALSHI_INTEGRATION_PLAN_2026-09-03.md:77,79` §5.2/§5.4). Form VERIFIED: `fee_type=quadratic`, `fee_multiplier=1` on all 102 daily series (enumeration:11). Shadow until θ and rounding are pinned on a published schedule **and** one real fill. Settlement-leg fee MISSING (§5.5) — if non-zero, add before any Kalshi row enters a verdict.

**Cells.** Each admitted station: own `P_HOLD_LOWER` cells, n_min=90, corpus 2021-01-01..2025-12-31 (`mb_current_rung_edge_study.py:20,30,170-172`). New pin, old `archive_table.py` untouched. NYC/KNYC excluded (cadence FAIL, `:38`; `config.py:16-29`).

**Admission gate (ordered).**

1. Cadence, **two** sample months including a winter month. Operational rule actually applied: median-of-daily-medians ≤5 min **and** ≥90% of days with daily median ≤5 min (`kalshi_station_cadence_2026-09-04.md:9`). Header `:3` says 95% — pin the table's 90%. `config.py:16-29` has **no** 90/95 number. July-2025: 18/19 PASS; **KHOU 83.3% PASS-WITH-CAVEAT, not admitted** (`:22,45-48`). Controls KLAX PASS / KNYC FAIL as expected (`:37-38`).
2. Station from `rules_primary` only (enumeration:12,46).
3. **CLI-final vs venue-settled, per station. Do not inherit a PM four-station rate — that quantity is UNMEASURED in `docs/evidence/`.** What exists is METAR-max vs CLI-final (`settlement_alignment_2026-08-25.md:12-20,36-44`, window 2021-01-01..2025-12-31, min n=1000): LAX 342/7280, MDW 376/7304, MIA 272/7252, SFO 346/7196 mismatch — **wrong comparison**. EXEC_SPINE R-9 divergence is planned, not measured. Gate: n≥90 settled HIGH events/station (G-01 floor); agreement = venue `result` equals CLI-FINAL winner via `WeatherBucketFacts.contains`; Wilson lower (z=1.959963984540054) >0.99; voids counted separately and raise (plan S15).

**Same-city both venues.** Admissible in each family. Pseudo-replication is within-family only.

**Clock (arithmetic, not a forecast).** Assumptions: 18 July-PASS new + 4 dense = 22 stations; 0.25 taken/listed-station-day (09-01: 1/4, `venue_city_census_2026-09-03.md:45`; rev2:131); no extra skip (plan:173 uses the same 0.25). Events/day =22×0.25=5.5. n=60⇒60/5.5≈10.91→ **D0+11 d**. n=150⇒150/5.5≈27.27→ **D0+28 d**. n=160⇒ **D0+30 d**. Kalshi take rate UNVERIFIED (plan:145) — re-size from shadow.

### (3) Do not touch LIVE v1

| If applied to v1 | Why post-hoc |
|---|---|
| Sequential Z_k, n_max=160, spending-to-horizon, boundary script in `live_family_tally.py` | Replaces frozen 60/150 Wilson (v1 §5:101-104, §7:142) |
| mean(BE_i) in the v1 tally / expansion-plan S2 | Changes registered `BE(mean entry_ask)` (v1 §5:101, §7:142,147-150) |
| Adding stations, Kalshi rows, shared pooled flag | Frozen station set (v1 §2:32, §7:143); sibling never pooled |
| Lowering floors, peeking Wilson, sequential BCa, Wald interval | v1 §5:112, §6:130-131, §7:143-144 |
| Extra structural-dead ε / Wilson-on-take-rate | New screen (blueprint:48) |

Allowed on v1: implement the **already-registered** structural-dead pin in (1f); ALERT-only corpus hash (v1 §7:144-145). Draft §8 D0 rule stands: any fill before v2 spec **and** v2 tally is v1-only.

v2 registration remains cost-free at live n=0.

---

## Self-consistency check on citations (5 lines)

1. Internal contradiction: Grok labels the draft's Z_k formula "Wald" then rules it's actually "Wilson score" — flags a genuine draft mislabeling, but Grok never explicitly resolved whether the draft's *stated* variance denominator (BE(1-BE)/n vs BE_k(1-BE_k)/n_k with time-varying π) matches Wilson-form; worth re-checking `PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md:39` directly.
2. It flags its own earlier premise as unverifiable: it explicitly searched `docs/evidence/**` for "A2 Lan-DeMets O'Brien-Fleming" and found **no matches**, meaning the brief's claim of an "earlier ruling today" is not evidence-backed in this repo — only cited via the draft, which cites Grok itself circularly. This is an honest, load-bearing caveat, not a citation error.
3. Fee concavity claim is internally consistent and cited twice (`fees.py:86-88` docstring plus `test_polymarket_us_fee_model.py:164-179` worked numbers) — the arithmetic in the worked example (mean(BE_i)=0.5054 vs break_even(mean)=0.5154) is directionally consistent with concave-fee Jensen reasoning, though it corrects a stray typo mid-render ("0.515**Scope" garbling) that resolved after formatting noise, not a numeric error.
4. The four-station CLI-vs-venue-settlement question is answered honestly as unmeasured, with a clearly labeled "wrong comparison" table (METAR vs CLI, not venue cash) rather than papering over the gap — strong self-consistency, no fabricated number substituted.
5. Kalshi arithmetic (22 stations × 0.25/day = 5.5 events/day; D0+11/D0+28/D0+30) is simple, correctly computed, and explicitly labeled arithmetic-with-assumptions rather than forecast, per the brief's requirement — consistent with its own stated inputs.

Relevant files: `/home/jon/breezy/docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md`, `/home/jon/breezy/docs/evidence/venue/kalshi/KALSHI_DAILY_TEMP_SERIES_ENUMERATION_2026-09-04.md`, `/home/jon/breezy/docs/evidence/kalshi_station_cadence_2026-09-04.md`, `/home/jon/breezy/scripts/analysis/mb_current_rung_edge_study.py`, `/home/jon/breezy/src/breezy/strategy/current_rung_hold/live_family_tally.py`, `/home/jon/breezy/src/breezy/strategy/current_rung_hold/decision.py`, `/home/jon/breezy/src/breezy/strategy/current_rung_hold/config.py`, `/home/jon/breezy/src/breezy/adapters/polymarket_us/fees.py`.

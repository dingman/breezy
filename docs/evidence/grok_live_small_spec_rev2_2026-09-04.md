# Grok live-small spec — revision 2 (2026-09-04)
Command: grok --prompt-file scratchpad/grok_live_small_followup.md --permission-mode plan --disallowed-tools spawn_subagent,run_terminal_command (retry; first run permission_cancelled). Exit 0, 12955 bytes, model grok-4.6. Verbatim below.

I'll revise the live-small spec against the new latency and precision measurements. First I'm reading the original spec, the two new evidence files, the BL-24 amendments, the M_B study, and the kill amendment.Next I’ll pin the lagged-entry code, taken-trial filter, station set, and how the archive temperatures are stored so the lag and precision rules can be stated exactly.I still need the archive ASOS cadence, how `running_max_at` rounds, the dense-station set, and M_B’s taken-trial counts so the precision and clock answers are grounded.# `current_rung_hold` — revised live-small spec (2026-09-04, post-latency)

Invariants unchanged. Not a GO on live enablement / NO-SEND / operator caps. Status: **not implementable on lag-15 evidence.** Live family is lag **30 and 45**, interval R, NYC out.

---

## Changelog vs `docs/evidence/grok_live_small_strategy_spec_2026-09-04.md`

| Where | Falsified | Replacement |
|---|---|---|
| §0 thesis | “5-min ASOS `R(t)` as a point” | NWS JSON 5-min rows are integer °C; `R(t)` is `[lower_f, upper_f)`; exact only at METAR (`docs/evidence/observation_source_latency_2026-09-04.md`; BL-24 A13) |
| §1 source | Live ingest implied IEM CSV; IEM-vs-public **UNVERIFIED** | Seam B source is **NWS API** (A12). IEM CSV 19–43 min behind; IEM 1-min = 0 rows; AWC = METAR-only (`docs/evidence/iem_asos_live_latency_2026-09-04.md`) |
| §1 lag = 15 on ask after **receipt** | 15 min is not a live-matching lag. Receipt is already ~20–45 min after measurement. Extra +15 double-counts the cancel-race hedge | Live **L_extra = 0**: quote `ts_event ≥ receipt` of the R-setting obs (A1: lag is on the ASK, never on R). Archive arms that measure **that same rule**: **30 and 45 min** from measurement instant `t` |
| §1 “10 min = two IEM poll cycles” | Bottleneck is publication lag, not 300 s poll | Poll ≥300 s is a few extra minutes on top of 20–35 min NWS lag |
| §1 “5 min paper-only; live = 15” | 10 **and** 15 are now paper-only too | `LAG_MINUTES_SWEEP += (30, 45)`; `K_B_REQUIRED_LAGS = (30, 45)` for the live family. 5/10/15 stay as **archive-only upper bound** (faster-feed counterfactual we do not have) |
| §5 `stale_observation_hours=0.5` | 30 min **<** NWS publication lag; a healthy 5-min feed would refuse `stale_observation` | **0.75 h (45 min)** on LAX/MDW/MIA/SFO |
| §6 “live implements lag 15; paper needs 10 and 15” | Live cannot implement 15 | Live family SURVIVE/KILL requires **30 and 45** to agree. A 10/15 SURVIVE does not license live |
| §6 clock D0=2026-09-04 → 09-26 / 10-29 | 09-04 was not a live-small day | Offsets unchanged **if** 3 taken/listed-day holds: **D0+22 / D0+55**. Earliest D0=2026-09-05 → **2026-09-27 / 2026-10-30**. 3/day is now an **optimistic** cap |
| §8.2 “lag 15 after receipt” | Same double-count | Publication delay **is** the MM window |
| §8 UNVERIFIED “IEM vs public METAR” | Now measured | NWS 5-min ~20–35 min; IEM CSV 19–43; KNYC ~45; integer-C 5-min VERIFIED |

Unchanged: long-only 1-lot IOC; first **unambiguous** taken snapshot consumes the day; hold-to-settlement; archive p_hold selects only (kill amendment); no ΔT/month/forecast resurrection; operator caps unset.

---

## 0. Thesis

Buy YES on the **current** 2 °F rung that unambiguous `R(t)` sits in, at the first lagged executable afternoon ask in `(0.05, 0.95)` whose frozen Part A Wilson-lower `p_hold` exceeds `BE(ask)=ask+0.06·ask·(1−ask)`, size 1, hold to CLI settlement. Evidence = realized hold rate of those fills (L-21; `docs/evidence/grok_mb_kill_amendment_2026-09-02.md`). Live `R(t)` is an interval; a spanning interval is refused, never rounded (A13).

---

## 1. Entry

**Stations — NYC excluded**, not a 60-min arm. Live set = **LAX, MDW, MIA, SFO** (`DENSE_STATIONS` via `CONTAMINATED_STATIONS`; L-13). KNYC is hourly-only in NWS, IEM, and AWC; a ≤45-min running-max rule is unsatisfiable; hourly R is a different (low-biased) statistic and must not enter the live family’s `n`. Optional archive NYC/60-min sensitivity: label CONTAMINATED, **not** in `K_B_REQUIRED_LAGS`.

Window, one-trial latch, legal cells, ask band, K-depth, selector, max ask: **unchanged** from original §1, except the first candidate is the first in-window snapshot with an **unambiguous** rung (see §1b). Taken-filter failure on that candidate still consumes the day (`is_taken_trial` / `gather_taken_trials` `mb_current_rung_edge_study.py:633-667`).

**`R(t)` (A1, A13).** `R(t) = max` over climate-day obs with `measurement ≤ t` **and** `receipt ≤ t`. Do **not** lag R. Live source: NWS `api.weather.gov/stations/{icao}/observations` (A12), consumed as `StationObservation` — strategy does not fetch. Accumulator `value_at(now_ns)` → `[lower_f, upper_f)` plus `exact_f` iff the max-setting row is METAR (`precision_c=0.05`). Do not read `NwsClimateDay` preliminary `tmax_f`.

**Lag — live and archive must measure the same rule.**

| Arm | Role |
|---|---|
| **30, 45 min** | **Live family.** Add to `LAG_MINUTES_SWEEP`. Set `K_B_REQUIRED_LAGS = (30, 45)` in `mb_current_rung_edge_study.py:181-182`. Archive: `running_max_at(series, t)` unlagged; `find_lagged_entry(..., not_before=t+lag)` (`:466-508`). Live: `L_extra=0` — price only vs quote `ts_event ≥ receipt` of the obs that set R |
| **5, 10, 15 min** | **Keep** in the sweep. Archive-only **upper bound** (faster feed we do not have). Report separately. Do **not** feed `evaluate_mb_family` (`:849-858`) |

30 brackets NWS 5-min ~20–35 min (+≤5 min poll). 45 is the pessimistic envelope (IEM 43; slow NWS batch). Live receipts are a **mixture** in that band; requiring **both** arms to agree covers the mixture.

**Will the edge survive 30–45 min?** The **hold event** is lag-invariant (same R, same rung, same CLI). The **selector** (`edge>0` on the lagged ask) is **not expected to survive as a mispricing**: the ask at `t+45` has had 45 minutes to incorporate R. Cheap 0.06 asks that lasted 15 min on 09-01 (`docs/evidence/mb_current_rung_edge_2026-09-02.md`) are the L-21 trap, not evidence they last 45. Likely: taken rate down and/or mean ask up. Pre-register 30/45; do not go live on 15-min SURVIVE. A 15-min SURVIVE with a 45-min KILL is a faster-feed result.

Hour/season lookup, coverage floor, frozen Part A table: unchanged.

### 1b. Precision — interval rule, not METAR-only

NWS 5-min: integer °C, empty `rawMessage`, span ~1.8 °F (up to two 1 °F values / two venue rungs). Hourly :53 METAR: tenths. **Trade iff the whole interval lies in one venue rung. Not METAR-only.**

```
if exact_f is not None:
    rung = rung_containing(ladder, exact_f)
else:
    r_lo = rung_containing(ladder, rounded_f(lower_f))
    r_hi = rung_containing(ladder, rounded_f(upper_f - ε))
    if r_lo is None or r_hi is None or r_lo != r_hi:
        refuse observation_ambiguous   # never round, never midpoint
    else:
        rung = r_lo
```
Then existing legal-cell / taken filter. `rounded_f` = same `round_half_up_f` as `settlement_alignment_study.py:192-194`.

**Why not METAR-only:** that throws away the only public sub-hourly source and pushes first-candidate ~:53 LST, stacking another ~30–50 min on a 20–45 min publication lag.

**Archive precision (do not confuse sources):**
- M_B R is built only from IEM rows with a METAR **T-group** (`metar_temperatures`; missing T-group dropped). Dense stations ~321 obs/day vs NYC ~24 — **5-min + hourly cadence, both tenths**. Archive does **not** mix integer-C with tenths.
- Live NWS 5-min **does**. Apples-to-apples requires a **degraded archive arm** (floor non-METAR T-groups to integer C, apply the interval rule). Until that arm runs, live precision is a **new measurement**.

**Fraction of M_B taken trials that would survive:**
- Interval rule on archive **as recorded** (tenths): **100%** (intervals degenerate).
- METAR-only: **not computable** from published tables (no METAR vs 5-min tag). The only Part B taken trial (MDW 09-01, h=12, all of lags 5/10/15) is the first afternoon depth snapshot, not the :53 METAR → **0/1** on that tape.
- Interval rule after degrading 5-min to integer C: **not in the tables.** Geometry: integer C → 1.8 °F F-interval; ~80% of integer C yield 3 possible `rounded_f` (always two rungs → refuse); ~20% yield 2; on odd-even 2 °F rungs (MDW [91,92]) **~10%** of integer-C rows are wholly in one rung. METAR-set running max stays exact until a 5-min interval can raise it. UNVERIFIED vs NWS rounding mode.

Ambiguous instants are **not** a taken-filter failure: no legal rung yet → skip, do not consume the station-day. First **unambiguous** candidate that fails taken **does** consume the day.

---

## 2–4. Order / size / exit

Unchanged from original (BUY YES, displayed ask, IOC, 1 lot, hold to settlement, entry-only halt).

---

## 5. Freshness / no-trade + engineer wiring

| Condition | Action | Who |
|---|---|---|
| Quote age > 15 min or future | `stale_quote` / `future_quote` | `evaluate_order` |
| No current-day obs, or age > bound | refuse; no synthesised R | decision `observation_unavailable` (A4); risk `stale_observation` / `observation_limit_unset` |
| R interval spans two rungs | refuse; **do not latch the day** | decision **`observation_ambiguous`** (A13) |
| Obs timestamp ahead of clock | `future_signal` | `evaluate_order` |
| Missing / unparseable | drop-and-count (L-17); R unchanged; staleness rises | Seam B ingest |
| Venue skip-day (~9%) | no trial, not a miss, not Wilson 0 | discovery |
| Ask-only `MarketQuote`; equity observed | unchanged | |

### `stale_observation_hours` (risk gate; age = measurement/issuance, not ingest; A6 never subtracts `assumed_publication_lag_ns`)

| Station | Bound | Why |
|---|---|---|
| LAX, MDW, MIA, SFO | **`0.75` h (45 min)** | NWS 5-min visible ~20–35 min after `valid`; 0.5 h would refuse a healthy feed. 45 min = measured upper + one 300 s poll + pad. Do not set below 45 min |
| KNYC | **not set — station excluded** | If later included: **`1.0` h (60 min)** minimum (A14). Not this package |

Default `None` still refuses every OBSERVATION order — this config **must** set 0.75. Not `running_extreme_lock`’s ~12.7 h.

### `observation_ambiguous`

- Add `"observation_ambiguous"` to `COUNTED_REFUSAL_REASONS` (`risk.py:80-112`). **Decision layer only** (`weather_common/refusals.py`), same as `observation_unavailable` (A4). No new `evaluate_order` branch.
- Fire when `value_at` interval maps to two (or zero) venue rungs. Never round.
- Not a Wilson 0; not `ioc_miss`; does not set the first-snapshot latch.
- `exact_f` present → this reason cannot fire.
- Log `n_filled` vs `n_scored` vs `n_ambiguous_skip`.

---

## 6. Pre-registered evaluation

Unit, hold, PnL, BE, Wilson z, KILL n≥60 / SURVIVE n≥150 / UNDERPOWERED / structural dead: **unchanged** (kill amendment).

**Family:** KILL/SURVIVE of the **live** rule requires lags **30 and 45** to agree. Do not claim live SURVIVE from 10/15.

**Clock** (n = taken **station-days**, not snapshots). 4 stations; skip ~9% → 3×0.91 = **2.73 taken/calendar-day** if the 3/listed-day rate holds. Cadence drop (ambiguous 5-min) does **not** stretch n by itself. Longer lag + interval refusals make 3/day **optimistic** (taken rate UNVERIFIED; 09-01 was 1/4 covered).

| Assumption | n=60 | n=150 |
|---|---|---|
| 3 taken/listed-day, skip 9% | **D0+22 d** | **D0+55 d** |
| Earliest D0=2026-09-05 | **2026-09-27** | **2026-10-30** |
| Taken stays ~1/listed-day | D0+66 d → **2026-11-10** | D0+165 d → **2027-02-17** |

Do not lower n floors. Skip-days are not trials. Falsify: KILL, or SURVIVE fails at n≥150, or live taken≈0 over ≥15 afternoon-covered listed station-days. Then stop this book class; no ΔT/month/forecast resurrection.

---

## 7. Package and gates

Package path, copy-shape, BL-24 Seam A+B first, `allow_short=False`, IOC wiring, `min_liquidity_contracts=1.0`, `min_model_edge=0.0`, operator caps unset: unchanged.

New vs original §7: ASK lag is **receipt (L_extra=0)** live / **30+45** archive; `stale_observation_hours=0.75`; decision reasons `observation_unavailable` **and** `observation_ambiguous`; source NWS not IEM (A12).

---

## 8. Self-fooling modes

1. L-21 archive base rate vs forecast-conditioned ask — unchanged guard.
2. **Acting on a faster information set than we have.** Public NWS is 20–45 min behind the measurement; the MM may be faster. Guard: live L_extra=0 (receipt is the lag); archive 30 **and** 45; IOC at displayed ask; miss consumes the day; stale/missing/ambiguous refuse rather than carrying a rounded R.
3. Pseudo-replication — unchanged. Plus: do not fold NYC hourly into dense n (L-13).

**UNVERIFIED:** taken rate at lag 30/45; degraded-precision taken fraction; NWS rounding mode vs A13 `[x−0.5, x+0.5)`; `currentBalance` vs notional (T-4); `minimumTradeQty` vs 1.0. **Now verified:** IEM/NWS/AWC latency and KNYC hourly-only.


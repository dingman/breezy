# PREREG v1 — current_rung_hold live-small family (2026-09-04)

Status: DRAFT under peer review; becomes binding at the commit that removes this line. The two PROPOSED stop rules in §6 are coordinator decisions accepted as written (D0 + 165 calendar days; cumulative ΣPnL ≤ −60 contract-units).

Status: pre-registered BEFORE the first live order (blueprint build-order step 7,
`docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md:45,85`). Nothing in this document is an
operator control; the two operator-reserved caps (max daily budget, max notional per position)
are deliberately absent (`src/breezy/strategy/current_rung_hold/config.py:41-51,174-176`).

## 0. Provenance pins (frozen at registration)

| Pin | Value | Source |
|---|---|---|
| Repo commit | `348f9c8` | this registration |
| Archive corpus sha256 | `3b410fb9c0c9208c5afb5cd8de05789077aca93c71fd540ddae0607ad6f04d48` | `archive_table.py:32` |
| Study git sha | `6cc1dd89d929ca975c68796a38e090ffb4985052` | `archive_table.py:33` |
| Corpus window | 2021-01-01..2025-12-31, complete 24h days, dense stations only | `archive_table.py:6-8` |
| Frozen table size | 240 defined/undefined cells | `archive_table.py` (240 keys) |
| Table generated at | 2026-09-04T02:15:54+00:00 UTC | `archive_table.py:13` |
| Config pin binding | `archive_table_pin` must equal `CORPUS_SHA256` or construction raises | `config.py:187,208-212` |
| Observation feed | NWS `api.weather.gov/stations/{icao}/observations` (A12) | spec rev2 §1 (`grok_live_small_spec_rev2_2026-09-04.md:41`) |

## 1. Hypothesis (falsifiable, one sentence)

Among live 1-contract IOC buys of the venue rung currently containing the unambiguous running
max, taken only when the frozen archive Wilson-lower `p_hold` exceeds `BE(ask)`, the **realized**
hold rate is above `BE(mean entry_ask)` at the 95% Wilson lower bound with n ≥ 150 and ΣPnL > 0 —
falsified if the Wilson **upper** bound falls below `BE` at n ≥ 60 pooled or in any n ≥ 60 stratum
(`mb_current_rung_edge_2026-09-02.md:17-20`; `mb_current_rung_edge_study.py:204-206`; L-21).

## 2. Population

- **Stations:** LAX, MDW, MIA, SFO (`config.py:74,179`). **NYC/KNYC excluded** — hourly-only feed,
  a running max from a sparse series is biased low (L-13, `LESSONS.md:648-656`; `config.py:16-29`).
  NYC never enters live `n`, not even as a sensitivity arm (spec rev2 §1).
- **Seasons / hours:** every climate day the strategy runs; decision hour restricted to the
  in-window afternoon `[12:00, 17:00)` LST (blueprint §2 PINNED constants, `:24`). Season and
  `hour_lst` are the frozen table's lookup axes (`archive_table.py:15`).
- **Legal cells:** `(width_code == 0 AND m_code == 0)` OR `width_code == 1` (open_upper).
  `width_code == 2` (open_lower) is NEVER legal; `m_code == 1` never trades live even though such
  cells are populated in the frozen table (`decision.py:29-40,214-225`).
- **Unit of observation:** ONE trial per (station, climate_day) = the **first executable snapshot**
  (`0.05 < ask < 0.95`, displayed size ≥ 1.0) to which the taken test is applied once
  (blueprint header `:4-6`; `mb_current_rung_edge_study.py:545-551,632-644`). A failed taken test
  consumes the station-day; an ambiguous or non-executable snapshot does not.
- **Not trials:** venue skip-days (~9% of station-days) are not misses and not Wilson zeros
  (spec rev2 §5 table); archive trials are never pooled into the live tally
  (`SCORER_TALLY_BCA_BRIEF_2026-09-04.md:96`).

## 3. The exact take rule (frozen)

Evaluated by `evaluate_decision` (`decision.py:238-287`), in this binding order:
1. `trial_day_consumed` (latch) → refuse. 2. instrument fee coefficient ≠ `0.06` →
`fee_schedule_mismatch`. 3. no running max, or staleness > `0.75 h` → `observation_unavailable`.
4. interval spans two rungs → `observation_ambiguous` (never rounded, never midpointed — L-17).
5. name the containing rung. 6. cell not legal → `illegal_cell`. 7. `not_executable`.
8. no defined table cell → `p_hold_undefined` (undefined, never "worst cell",
`archive_table.py:18-20`). 9. `p_hold_lower ≤ BE` → `edge_below_break_even`; else **Take**:
LONG_YES, quantity 1, limit = displayed level-0 ask, IOC, hold to settlement.

**Frozen parameter defaults** (`config.py:179-189`): `stations=("LAX","MDW","MIA","SFO")` ·
`stale_observation_hours=0.75` · `required_fee_coefficient=Decimal("0.06")` ·
`executable_ask_lower=Decimal("0.05")` · `executable_ask_upper=Decimal("0.95")` (both strict) ·
`minimum_displayed_size=1` · `order_quantity=1` · `allow_short=False` (constructing `True` raises,
L-22) · `archive_table_pin=CORPUS_SHA256` · `entry_only_halt=True`.

**Fee / break-even.** `fee(ask) = ROUND_HALF_EVEN_to_cent(0.06 · ask · (1 − ask))`;
`BE(ask) = ask + fee(ask)` (`decision.py:228-235,277`).
**Worked example (ask = 0.40):** `0.06 · 0.40 · 0.60 = 0.0144` → `0.01` → `BE = 0.41`; a cell with
`p_hold_lower > 0.41` takes (`tests/unit/test_current_rung_hold_decision.py:4-5,54-56,96-102`).

**Lag.** Live `L_extra = 0`: a quote may only be priced when `ts_event ≥ receipt` of the
observation that set R (spec rev2 §1 table). The archive arms that measure this same rule are
**30 and 45 minutes**, and BOTH must agree for a live family verdict; a 5/10/15-minute SURVIVE is
an archive-only faster-feed upper bound and does not license live (spec rev2 §1, §6).

## 4. The exact scoring rule (frozen)

- `held = 1` iff the NWS **FINAL** CLI `tmax_f` lies inside the rung bought, by
  `WeatherBucketFacts.contains` on both closed bounds
  (`SCORER_TALLY_BCA_BRIEF_2026-09-04.md:12,39`).
- **FINAL print only.** Preliminary-only, superseded, sentinel-`tmax`, unresolved-rung,
  station-day-mismatch and instrument-unavailable trials are REFUSED, never scored
  (`SCORER_TALLY_BCA_BRIEF:35,100`); `len(scored) + len(refused) == len(trials)`.
- `pnl = 1{held} − fill_px − fee`, Decimal throughout; `fee` is the entry leg only, per contract;
  it is never summed with a fee-inclusive `Position.realized_pnl` (`SCORER_TALLY_BCA_BRIEF:23,97`).
- **Fallback exclusion.** A trial the venue settles at last fair market price because no NWS FINAL
  published within 7 days is stamped `settlement_basis="venue_last_fair_price_fallback"` and
  `excluded_reason="venue_settled_without_nws"`; it is EXCLUDED from strata and from the ROI bound
  and is never pooled with NWS-keyed rows. Until venue settlement is recorded it stays PENDING; a
  late FINAL does not re-score it (`SCORER_TALLY_BCA_BRIEF:94-95`).
- **Basis split:** ask-band classification, `mean_ask` and `break_even` use decision-time
  `entry_ask` (latch); `pnl` uses `fill_px`; `slippage = fill_px − entry_ask` is a required column
  (`SCORER_TALLY_BCA_BRIEF:99`). A re-scored trial counts once, at max `score_seq` (`:67,101`).

## 5. The exact pre-declared analysis (frozen)

- **Strata:** pooled, per-station, and per **entry_ask band** `(0.05,0.15)`, `(0.15,0.30)`,
  `(0.30,0.95)` (`mb_current_rung_edge_study.py:210,424`).
- **Interval:** Wilson, `z = 1.959963984540054`, the one shared constant
  (`archive_correction_probe.py:66,352`) — a second Wilson implementation is a defect.
- **KILL:** pooled `n ≥ 60` with Wilson **upper** < `BE(mean entry_ask)`, or any stratum with
  `n ≥ 60` dead (`POOLED_KILL_N_MIN=60`, `STRATUM_KILL_N_MIN=60`, `:204-205`).
- **SURVIVE:** pooled `n ≥ 150` AND Wilson **lower** > `BE` AND no dead stratum AND **ΣPnL > 0**
  (`SURVIVE_N_MIN=150`, `:206`; the ΣPnL clause is added by `SCORER_TALLY_BCA_BRIEF:98`).
- Otherwise **UNDERPOWERED**. Structural dead: live taken ≈ 0 over ≥ 15 afternoon-covered listed
  station-days (spec rev2 §6).
- **ROI bound (stop-gate quantity):** BCa bootstrap on the **ratio of sums**
  `θ = ΣPnL / Σcost`, paired over trial indices, `B = 10_000`, seed `20260904`, 95% level
  (`src/breezy/settlement/roi_bound.py:93,97,104`). `BCa: REFUSED` if the exclusion fraction
  exceeds the ceiling `Decimal("0.20")` (`exit_guard.EXCLUSION_FRACTION_CEILING`,
  `roi_bound.py:23-24,76,185`); `BCa: UNDERPOWERED (n<30)` below `MIN_NON_EXCLUDED_N = 30`
  non-excluded rows (`:100,250`). A **Wald** interval is never printed under any circumstance.

## 6. Stop rules

- **KILL** → stop the family immediately; no ΔT / month / forecast resurrection (spec rev2 §6).
- **SURVIVE + gate** → SURVIVE alone does not close the stop gate. The gate as restated by the
  operator 2026-09-01 is: positive ROI from real, very small marketable orders with the
  **confidence-interval LOWER BOUND clearing break-even** — i.e. the §5 BCa lower bound must be
  computed (not `NOT BUILT`, not `REFUSED`, not `UNDERPOWERED`) and must be above break-even.
- **Max calendar horizon — PROPOSED (coordinator decision, not an operator budget):** stop at
  **D0 + 165 calendar days**, the pessimistic 1-taken/listed-day clock to n = 150
  (spec rev2 §6 table, `:137`). Reaching it without n = 150 is a structural-dead stop.
- **Max cumulative loss — PROPOSED (coordinator decision, denominated in CONTRACT UNITS, never
  dollars, because dollar caps are operator-reserved):** stop when cumulative ΣPnL ≤ **−60
  contract-units** (60 = `POOLED_KILL_N_MIN`, i.e. one full kill-sample of maximum-loss trials).
  This is a floor on our own evidence spend and is independent of, and never a substitute for,
  the operator-reserved caps.
- Expected clock: n=60 at D0+22, n=150 at D0+55 under the optimistic 2.73 taken/calendar-day
  assumption; earliest D0 = 2026-09-05 → 2026-09-27 / 2026-10-30 (spec rev2 §6). Do NOT lower the
  n floors.

## 7. What will NOT change after the first order

Frozen for the life of this family: every `config.py` default in §3; the frozen table
(`P_HOLD_LOWER`, its 240 cells, `CORPUS_SHA256`, `STUDY_GIT_SHA`); the rule order and the closed
refusal-reason set (`decision.py:119-131`); the BE formula and rounding mode; the scoring rule;
the strata definition; `z`; the 60/150 thresholds; the BCa statistic, `B`, seed and 0.20 ceiling;
the station set. No floor is lowered and no post-hoc screen is added (blueprint §7 standing
refusal). The nightly corpus-hash check is ALERT-ONLY and never a runtime refusal (blueprint
amendment 5).

**How a change would be recorded:** any change to a parameter, the table, or a threshold requires
a NEW pre-registration document (`PREREG v2 — …`) that states the change and its motivation; the
family **restarts** — `n` resets to 0 and trials scored under v1 are never pooled with v2 rows.
Amending v1 in place is prohibited.

## 8. Artefacts to be produced

| Artefact | Path | Provenance carried |
|---|---|---|
| Scored trials (parquet, append-only) | `$BREEZY_DERIVED_DIR/scored_trials/scored_trials_<UTC ts>.parquet` | `trial_id` = latch key `current_rung_hold/trial/{station}/{climate_day}`, `raw_sha256` of the FINAL print, `revision_seq`, `score_seq`, `scored_at_ns` (`SCORER_TALLY_BCA_BRIEF:28,34,101`) |
| Nightly tally (Markdown) | `~/.local/share/breezy/derived/live_family_tally_<YYYY-MM-DD>.md` | source parquet paths, row count, `as_of`, git sha, and the explicit "live trials only — archive trials are never pooled here" line (`SCORER_TALLY_BCA_BRIEF:67`) |
| Evidence memo (at verdict) | `docs/evidence/current_rung_hold_live_family_<verdict>_<date>.md` | this PREREG's commit `348f9c8`, corpus sha, study sha, BCa seed/B, final n/k |

## 9. Known limitations (registered in advance, not discovered later)

1. **Bid side is empty.** There is no executable exit; the design is hold-to-settlement with no
   exit path (blueprint §1 "Hold-to-settlement … no exit path (T-9)"). A mid-life mark is not
   realizable and is never used as evidence.
2. **Venue skips ~9% of station-days.** A skipped day is a non-trial, not a miss and not a Wilson
   zero (spec rev2 §5); missing listings must be treated as VENUE-NEVER-LISTED until a by-slug
   probe says otherwise (L-23).
3. **Observation latency.** NWS 5-minute rows are visible ~20–35 min after `valid`; IEM CSV 19–43
   min; KNYC ~45 min (spec rev2 §1 changelog). Live receipts are a mixture across that band, which
   is why both the 30 and 45 archive arms must agree. 5-minute NWS rows are integer °C, so R is an
   interval and spanning intervals are refused, not rounded (spec rev2 §1b).
4. **Selector survival at 30–45 min is UNVERIFIED.** The hold event is lag-invariant; the
   mispricing is not expected to survive 45 minutes (spec rev2 §1). Also UNVERIFIED: taken rate at
   lag 30/45, degraded-precision taken fraction, NWS rounding mode, `minimumTradeQty` vs 1.0.
5. **OQ-4 synchronous execution is unmeasured.** The end-to-end latency of the synchronous submit
   path under live conditions has not been measured; slippage (`fill_px − entry_ask`) is carried as
   a required column specifically so this shows up as data rather than as an assumption.

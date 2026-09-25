# RULING — AUD-18 §7 step 8, hypothesis `H-ARCHIVE-RECAL-2026-09`

Authority: `docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md`
§6.1, §6.3, §6.6, §7 step 8, §9, D12/D13. Governed hypothesis class: **`pm_us_crh_v4`
archive-table recalibration** (§6.3 row 2), disposition today `BLOCKED on data, not
closed` per `DECISION_FUNNEL_2026-09-20.md` ("UNSALVAGEABLE, not merely miscalibrated"
absent real historical venue ladders).

Ruled by: trading-bot-architect (AUTHOR) + prediction-market-reviewer (ADVERSARIAL
REVIEWER), briefed blind and separately per §7 step 8's dispatch instruction.
DRAFT pending the adversarial peer's independent pass — not yet dated/signed.

Binding, not re-litigated: `forecast-edge-closed-pmus-rungs` (TERMINAL, a different
class); `two-structural-gates-block-every-take`; §6.1 POWER-PRIMARY-ONLY (anchor,
not restated here beyond citation).

## 0. Freeze-date corpus scope — SEARCH vs. CONFIRM boundary set by wp7b run timing

`docs/evidence/RULING_aud02_step5_dispositions_2026-09-25.md` (same date) ran the
wp7b qualifying-rate script against the **since=2026-09-21, until=open** window
(`AUD02_step5_wp7b_since_2026-09-21_run.md`: n=12 station-days) against the PM.us
venue-priced ladder tape from 2026-08-30 onward. This is the same underlying tape
corpus this hypothesis's own confirmatory look would read. Per `PREREG_WP7_MULTIPLICITY_RULE §1.v`, the firewall is stated over the corpus, not the statistic — even though the wp7b
statistic (YES-ask qualifying rate) is not this hypothesis's primary statistic, both
are drawn from identical underlying tape for the same station-days, and wp7b scored
them to inform a real decision (C1 build/park call cited by §6.3 row 4).

**Resolution: the `freeze_commit` postdates the 2026-09-21..2026-09-25 wp7b run.
Every station-day on or before `freeze_commit` is declared SEARCH corpus for this
hypothesis, not confirmatory.** This prevents the freeze-date-firewall violation
`PREREG_WP7_MULTIPLICITY_RULE §1.v` exists to prevent.

`freeze_commit = 49261a5c2119fc621863ad7df05af1e2a96c6b55` (2026-09-25, HEAD at
ruling time, postdating both the qualifying-rate run and this ruling's own
issuance). Confirmatory station-days for `H-ARCHIVE-RECAL-2026-09` are those observed
strictly after this commit/date. This costs the hypothesis its accrual over
2026-09-21..2026-09-25 as SEARCH, not CONFIRM — an explicit, bounded, and cheap price
for closing the leak.

## 1. Design fixed BEFORE any data for this hypothesis is opened

| Field | Value | Basis |
|---|---|---|
| `hypothesis_id` | `H-ARCHIVE-RECAL-2026-09` | §6.3 row 2 |
| `hypothesis_class` | `pm_us_crh_v4_archive_recalibration` | closed enum, §6.2 |
| `k_variants` | **1** | one recalibration design (interval-aware venue-priced ladders from tape start 2026-08-30 forward), not a sweep — "fewer, sharper hypotheses" (§6.1) |
| `allocated_alpha` | `PROGRAMME_ALPHA / MAX_HYPOTHESES = 0.05 / 4 = 0.0125` | §6.1 fixed split, ASSIGNED not chosen |
| `per_variant_alpha` | `allocated_alpha / k_variants = 0.0125 / 1 = 0.0125` | §6.1 |
| `look_policy` | `SINGLE_LOOK` | only admitted value, §6.1/§6.4 step 3 |
| `min_station_days` (with-takes, §6.1 zero-take rule) | **600** | ≈120 days at PM.us's full 5-station/day accrual, matching §9's own worked `n=600` horizon; pooled across the design's registered strata for the confirmatory look — per-stratum (station × season × hour × width × m) sufficiency is very likely slower and is tracked separately by §6.4 step 3's scheduling recomputation, not asserted here |
| `station_day_statistic` | `MEAN_EXCESS_PER_TAKE` | §6.1, only admitted value |
| `order_quantity` | `1` | §6.1 pin |
| `max_single_day_leg_share_cap` | `0.20` | §6.1 pin, not a per-hypothesis dial |
| KILL horizon (PARKED duration) | **180 days** from `registered_at` | per-stratum accrual on a 5-station/day surface is slower than the pooled `n=600`; 180 days gives ~900 station-days of pooled headroom before §6.6 reads this class specifically |
| `freeze_commit` | `49261a5c2119fc621863ad7df05af1e2a96c6b55` (2026-09-25) | corpus on or before this commit/date is SEARCH; confirmatory draws are station-days observed strictly after it. 2026-09-21..09-25 declared SEARCH per §0 above. |

## 2. Power check (§6.1, computed and stated before any data is opened)

`MDE = (z_(1-per_variant_alpha) + z_POWER) / (2 * sqrt(n))`, `per_variant_alpha=0.0125`,
`POWER=0.80`, variance bound `1/4` (Popoviciu on `MEAN_EXCESS_PER_TAKE`, §6.1):

- `z_(1-0.0125) = 2.24140`, `z_0.80 = 0.84162`, sum = `3.08302`.
- `n=300`: `3.08302 / (2*sqrt(300)) = 3.08302/34.6410 = 0.0890`.
- **`n=600` (the pre-registered `min_station_days`): `3.08302/(2*sqrt(600)) =
  3.08302/48.9898 = 0.0629`.**
- (Reference only, not the design point) `n=1200`: `0.0445`.

`power_is_primary_only = true`. This is the PRIMARY test's design power ONLY
(§6.1 POWER-PRIMARY-ONLY): the mandatory pooled-P&L veto (below) makes
`P(reach CONFIRMED) <= 0.80` strictly whenever a true positive can fail the veto;
no number is asserted here for that shortfall.

**Market terms.** At reference ask `a = 0.30`, `theta = 0.0695`
(`FEE_SCHEDULE_PIN_2026-09-18.md:7,47`, NOT `config.py:226`'s stale `0.06`),
slippage = **AUD-12's unmeasured placeholder `0.01`** (measured value pending;
AUD-12 §6(a) records `slippage_prob` as an unmeasured hardcoded one-tick
placeholder — commit `0d0f681` measured n=8, giving `0.0000`, which is **not** a
general slippage allowance and is not substituted here):
`BE = 0.30 + 0.0695*0.30*0.70 + 0.01 = 0.324595`. An MDE of `0.0629` at `n=600`
demands a true per-take hold probability of about **`0.3875`** against that
break-even — a **6.3-point** absolute edge net of fees and slippage.

## 3. Plausibility bound

`mde_plausibility_bound = 0.03` (3 points). Justification: this repo's own
measured effect sizes on this venue are sub-percentage-point to low-single-digit —
WP-7b's paired-Brier CIs on the traded ask straddle zero at a ≈2-point half-width
(`AUD02_step5_wp7b_since_2026-09-21_run.md`: CI `[-0.02147,+0.02079]`), and the
CLOSED forecast-taker programme's own confirmed effect was `CI95
[-0.03229,-0.00373]` — under 3.3 points at its widest. No evidence anywhere in
this repo supports asserting this venue could plausibly carry a **6.3-point**
edge; `0.03` is generous relative to every measured comparator, not conservative
against them.

`MDE (0.0629) > mde_plausibility_bound (0.03)`.

## 4. Expected disposition

**`UNDERPOWERED_NOT_REGISTERED`.** `register_hypothesis` REFUSES this intake at
its recomputed MDE, consuming no alpha and no slot (§6.1). Doubling `n` to 1200
(≈240 days pooled, likely 1+ year per-stratum) only reaches `0.0445`, still
above the bound — the class cannot be rescued by patience alone at any horizon
this repo could defend as "current tape."

## 5. Pooled-P&L veto and concentration cap (pre-registered; moot if step 4 holds)

If a future amendment raises `min_station_days`/lowers the bound enough to
register: `CONFIRMED` additionally requires `pooled_net_pnl_per_contract > 0`
strictly over the same confirmatory sample (`combine_station_day`'s own `x`,
net of `theta=0.0695` and AUD-12's slippage through each `BE_i`) AND
`max_single_day_leg_share <= 0.20`. The veto spends no alpha (alpha-free,
veto-only, §6.1).

## 6. Provisional flag — MUST be re-issued

This ruling's `BE`/MDE use AUD-12's **unmeasured placeholder** slippage
(`0.01`). **This ruling is PROVISIONAL and MUST be re-issued the moment AUD-12
publishes a measured slippage value that changes `BE`.** A measured slippage
above `0.01` widens `BE` and only worsens the MDE-vs-bound gap (safe direction
for this ruling's UNDERPOWERED conclusion); a measured value at/near `0.0000`
(as AUD-12's own n=8 interim read suggests) narrows `BE` marginally and does
not change the ordinal conclusion at this MDE/bound gap, but the ruling must
still be re-issued with the corrected number per §7 step 8(v).

## 7. Operator-reserved controls — untouched

No value is assigned to the max-daily-budget or max-per-position controls.
No live-trading enablement is proposed or implied. This ruling arms nothing.

## Peer review (2026-09-25)

**Verdict: AMEND.** Peer review confirmed:
- Corpus scope amendment (§0): postdate `freeze_commit` to 49261a5c2119fc621863ad7df05af1e2a96c6b55, declare 2026-09-21..09-25 SEARCH. ENDORSED.
- MDE at n=600 (0.0629) is verified. `UNDERPOWERED_NOT_REGISTERED` disposition ENDORSED.
- `PREREG_WP7_MULTIPLICITY_RULE §1.v` application: corpus-scoped, not statistic-scoped. ENDORSED.

This amended ruling, with §0 and table §1 updates applied, receives ENDORSED status subject to peer confirmation of the corpus rationale.

## Peer confirmation of the corpus rationale (2026-09-25, appended; closes the :137 condition)

An independent pass by `mle-reviewer` returned **CONFIRMED-WITH-NOTES**.

- **Recomputed MDE.** The recompute matches the ruling exactly at every sample size:

  | n | MDE |
  |---|---|
  | 300 | 0.08900 |
  | 600 | 0.06293 |
  | 1200 | 0.04450 |

  BE is 0.324595. The required hold probability is 0.3875.
- **Comparator sources.** Both comparators behind the 0.03 bound predate `freeze_commit` 49261a5, and neither is drawn from this hypothesis's SEARCH window (2026-09-21..09-25):
  - The WP-7b ask CI `[-0.02147,+0.02079]`, clusters=84, matches `AUD02_step5_wp7b_since_2026-09-21_run.md:16` byte for byte. It comes from a pinned `--corpus-json` corpus dated 2026-09-20. The windowed step-5 addendum in the same file uses a separate, non-overlapping code path.
  - The forecast-taker CI `[-0.03229,-0.00373]`, n=64, matches `RULING_forecast_edge_programme_closes_2026-09-20.md:45`.
- **Leakage.** None found.
- **Train/serve skew.** The archive table was calibrated without the tenths-METAR ambiguity gate, and that skew is real. It does not matter here, because an UNDERPOWERED disposition refuses intake before any archive-table data is opened.
- **Notes.**
  - "The corpus rationale" could mean either §0 (SEARCH scoping) or §3 (bound justification). Both were verified.
  - That the comparator corpora do not overlap the SEARCH window was established by script and commit forensics. The ruling body does not state it.

**The :137 condition is closed.** Registration of H-ARCHIVE-RECAL-2026-09 is unblocked, as a follow-up slice.

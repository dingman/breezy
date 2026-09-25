# RULING — AUD-18 §7 step 8, hypothesis `H-NO-SIDE-2026-09`

Authority: `docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md`
§6.1, §6.3, §6.6, §7 step 8, §9, D12/D13. Governed hypothesis class: **NO-side
hunting** (§6.3 row 4), disposition today `BLOCKED on capture, not closed`
(standing requirement, memory `no-side-hunting-is-a-requirement`).

Ruled by: trading-bot-architect (AUTHOR) + prediction-market-reviewer (ADVERSARIAL
REVIEWER), briefed blind and separately per §7 step 8's dispatch instruction.
DRAFT pending the adversarial peer's independent pass — not yet dated/signed.

Binding, not re-litigated: `forecast-edge-closed-pmus-rungs` (TERMINAL, a different
class); `venue-nets-no-holding-as-short-yes`; `venue-represents-no-buy-as-sell-buy-short`.

## 0. Freeze-leak finding — resolved by setting the freeze commit AFTER the leak

`docs/evidence/RULING_aud02_step5_dispositions_2026-09-25.md` (this same date)
already ran the wp7b qualifying-rate script against the **since=2026-09-21,
until=open** window (`AUD02_step5_wp7b_since_2026-09-21_run.md`: n=12
station-days, 0 qualifying) to inform the C1 (NO-leg depth capture) build/park
call. That window overlaps exactly the venue tape this hypothesis's own future
confirmatory draws would read. Treating any station-day on or before that run
as still-unopened confirmatory corpus would be the freeze-date-firewall
violation `PREREG_WP7_MULTIPLICITY_RULE §1.v` exists to prevent — even though
the wp7b statistic (YES-ask qualifying rate) is not this hypothesis's own
primary statistic, it is drawn from the identical underlying tape and was used
to make a real triage decision (C1 PARK) that this hypothesis's own §6.3 row
cites as its evidence.

**Resolution: the NO-side `freeze_commit` postdates the 2026-09-21..2026-09-25
wp7b run. Every station-day on or before `freeze_commit` is declared SEARCH
corpus for this hypothesis, not confirmatory — chosen over the alternative
(re-window the run out of the confirmatory corpus by date splicing) because
the run's own artefact is dated by commit, not by a clean pre/post tape
boundary, and a date-only carve-out would still leave the specific station-days
already scored by wp7b inside a nominally "unopened" window.**

`freeze_commit = 49261a5c2119fc621863ad7df05af1e2a96c6b55` (2026-09-25, HEAD at
ruling time, postdating both the qualifying-rate run and this ruling's own
issuance). Confirmatory station-days for `H-NO-SIDE-2026-09` are those observed
strictly after this commit/date. This costs the hypothesis its most recent 4
climate days of accrual (2026-09-21..2026-09-25) as SEARCH, not CONFIRM — an
explicit, bounded, and cheap price for closing the leak, not an open-ended one.

## 1. Design fixed BEFORE any (post-freeze) data for this hypothesis is opened

| Field | Value | Basis |
|---|---|---|
| `hypothesis_id` | `H-NO-SIDE-2026-09` | §6.3 row 4 |
| `hypothesis_class` | `no_side_hunting` | closed enum, §6.2 |
| `k_variants` | **1** | one NO-side design (mirror the existing YES-side architecture on the NO leg), not a sweep |
| `allocated_alpha` | `0.05 / 4 = 0.0125` | §6.1 |
| `per_variant_alpha` | `0.0125 / 1 = 0.0125` | §6.1 |
| `look_policy` | `SINGLE_LOOK` | §6.1/§6.4 step 3 |
| `min_station_days` (with-takes) | **300** | ≈60 days at full 5-station accrual **after** NO-leg capture exists — smaller than the archive-table target because capture must be built first (C1, currently PARKED per the 09-25 step-5 ruling) and the clock realistically cannot start until then (see §3 below, and the peer-review question in the accompanying findings memo) |
| `station_day_statistic` | `MEAN_EXCESS_PER_TAKE` | §6.1 — mixed YES/NO legs on one station-day are exactly the case this statistic (not the SUM) is pinned for |
| `order_quantity` | `1` | §6.1 pin |
| `max_single_day_leg_share_cap` | `0.20` | §6.1 pin |
| KILL horizon (PARKED duration) | **120 days** from `registered_at` | shorter than archive-table's 180 because this class is gated on an upstream, separately-tracked capture build (C1/C2, owned by AUD-02) rather than pure accrual time |
| `freeze_commit` | `49261a5c2119fc621863ad7df05af1e2a96c6b55` (2026-09-25) | see §0 above |

## 2. Power check (§6.1)

Same formula, `per_variant_alpha=0.0125`, `POWER=0.80`, variance bound `1/4`:
`z_(1-0.0125)=2.24140`, `z_0.80=0.84162`, sum=`3.08302`.

**`n=300` (the pre-registered `min_station_days`): `3.08302/(2*sqrt(300)) =
3.08302/34.6410 = 0.0890`.**

`power_is_primary_only = true` (§6.1 POWER-PRIMARY-ONLY) — PRIMARY-test design
power only; the mandatory pooled-P&L veto strictly lowers `P(reach CONFIRMED)`
below `0.80` by an amount this design does not bound, and this ruling asserts
no number for it.

**Market terms.** Reference ask `a=0.30` (same convention as YES-side, no
NO-specific ask evidence exists yet since NO has never been quoted), `theta =
0.0695`, slippage = AUD-12's unmeasured placeholder `0.01`:
`BE = 0.324595` (identical arithmetic to §2 of the archive-table ruling — the
break-even formula is side-agnostic). An MDE of `0.0890` demands a true
per-take hold probability of about **`0.4136`** against that break-even — an
**8.9-point** absolute edge net of costs.

## 3. Plausibility bound

`mde_plausibility_bound = 0.04` (4 points) — slightly more generous than the
archive-table ruling's `0.03` because NO-side is genuinely untested territory
(no live sub-degree observation confound applies the way it does to the YES
rung ladder), but still bounded above by the same comparators: WP-7b's ≈2-point
CI half-widths and the closed forecast-taker programme's ≈3.3-point confirmed
effect. Nothing in this repo's evidence supports an 8.9-point plausible edge on
either side of this venue.

`MDE (0.0890) > mde_plausibility_bound (0.04)`.

## 4. Expected disposition

**`UNDERPOWERED_NOT_REGISTERED`.** Consumes no alpha, no slot. Raising `n` to
600 only reaches `0.0629` (still above `0.04`); reaching parity with the bound
would need `n` on the order of `(3.08302/(2*0.04))^2 ≈ 1487` with-takes
station-days — roughly 297 days of full 5-station accrual, assuming NO-leg
capture exists and fires on every eligible day from day one, neither of which
is currently true.

## 5. Provisional flag — MUST be re-issued

Same AUD-12 placeholder-slippage caveat as the archive-table ruling (§6 there,
incorporated by reference). This ruling MUST be re-issued when AUD-12 publishes
a measured slippage value.

## 6. Operator-reserved controls — untouched

No value is assigned to the max-daily-budget or max-per-position controls. No
live-trading enablement is proposed or implied. This ruling arms nothing.

## Peer review (2026-09-25)

**Verdict: ENDORSED as-is.** Peer review confirmed:
- Freeze-date corpus scope (§0): postdate `freeze_commit` to 49261a5c2119fc621863ad7df05af1e2a96c6b55, declare 2026-09-21..09-25 SEARCH. ENDORSED.
- MDE at n=300 (0.0890) is verified: `(z_(1-α')+z_0.80)/(2√n)` with α'=0.0125, sum 3.08302. ENDORSED.
- `UNDERPOWERED_NOT_REGISTERED` disposition ENDORSED.
- Plausibility bound (0.04) vs. MDE (0.0890) comparison ENDORSED.

This ruling receives ENDORSED status for immediate adoption.

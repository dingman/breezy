# RULING — EDGE-5 RA-9: trigger-4 off-window hypothesis `H-OFFWINDOW-T4-2026-09` (SIGNED, 2026-09-27)

Authority: `EDGE-5_rearm_roadmap_plan_r4_2026-09-27.md` (r4 rulings 2, 3, 6, 7; AM-1..AM-4 BINDING);
`RULING_HUNT-1_all_hours_hunting_2026-09-26.md` trigger 4; AUD-18 §6.1/§6.2/§7 step 8;
`README.md` (EDGE_2026-09-27) binding cross-item rules; `RULING_AUD-12a_slippage_allowance_2026-09-27.md`.
Author: planner (drafter). Adversarial peers (blind): trading-bot-architect REQUEST_CHANGES(minor), prediction-market-reviewer ENDORSE-WITH-CHANGES — both endorse the headline; all required edits applied in §11. **Arms nothing.**

Binding, not re-litigated: `forecast-edge-closed-pmus-rungs` (TERMINAL); L-9 (no seller for certainty);
L-34 (the trigger is pinned); L-40 (+ amendment: the 1/4 ceiling is same-side, qty≡1 only); the
SEARCH/CONFIRM firewall (EDGE-4 disposition); α = 0.025 programme FWER (RA-8b); AUD-12a (0.01 retained).

## 0. Corpus declaration (fixed before anything else)
- **This ruling computes nothing on any tape, pre- or post-freeze.** Every number here is one of:
  (a) quoted from plan text (MDE 0.0964 / 0.0682, r3 ruling 1);
  (b) a pinned constant (`EVIDENCED_FEE_THETA` 0.0695; slippage 0.01 per AUD-12a);
  (c) arithmetic on the outcome-free `recompute_mde` formula; or
  (d) a comparator already signed in a pre-freeze ruling (§5).
  **So this ruling forfeits no `H-ARCHIVE-RECAL-2026-09` station-day.**
- **SEARCH for this hypothesis:** all tape through RA-9's `freeze_commit`. That includes pre-2026-09-25
  tape, because `daf81a1` and the HUNT-1 cluster counts already opened off-window hours (1–6 clusters
  per hour).
- **CONFIRM for this hypothesis:** only station-days whose `climate_day` is strictly after
  `registered_at`, replayed by the RA-9b candidate unit.
- **Declared, accepted cost (r4 ruling 7):** every post-2026-09-25 station-day the candidate unit reads
  is **permanently** SEARCH for `H-ARCHIVE-RECAL-2026-09`. It can never be reclassified CONFIRM.
- **RA-9b development and verification runs** use pre-freeze tape (≤ 2026-09-25) or synthetic fixtures
  only. A dev run on post-freeze tape spends that day for `H-ARCHIVE-RECAL`. A dev run on tape after
  `registered_at` also spends RA-9's own CONFIRM corpus, and that day must be logged and excluded.

## 1. Hypothesis and shape
- **Estimand.** The station-day-clustered mean excess-per-take (`MEAN_EXCESS_PER_TAKE`) of the price-only
  take rule in §2. It applies to the existing PM.us current-rung family shape, YES leg only, at
  qty 1, over LST hours `{00-08, 17-23}`. `k_variants = 1`. It never reads `P_HOLD`.
- **ONE manifest, ONE strategy instance, one two-range window.** The instance is built with the r4/AM-2
  seams set to `window_start_hour_lst=0`, `window_end_hour_lst=24` (half-open, so every hour passes
  the `_hunt_tick` gate). The registered hour set is enforced inside `compose_decision` (§2 step 2).
- **Why not two manifests.** Two instances, `[0,9)` and `[17,24)`, would each carry their own latch
  and day budget.
  - One instrument could then fill twice on one station-day, e.g. at hour 03 and again at hour 18.
    That makes qty 2 on one rung, which breaks the qty≡1 variance ceiling (L-40).
  - Two instances would also test something a single live family (RA-11b) could never deploy.
- **Plan-text bug (for RA-9b).** r4 lines 60-61 say `window_end_hour_lst=8`. Under half-open
  semantics (`strategy.py:155`, `continuous_strategy.py:1807`) that would drop hour 08. It is moot
  under this design.
- **Inherited, not part of the take rule.** Current-rung selection (`instrument_rung_is_current`, which
  reads `running_max`), the latch, dedupe, family halt, the day-budget gates, and the L-34 trigger
  (first Depth10 frame on which the rule fires for an unlatched current-rung instrument). All of these
  stay byte-inherited from `_hunt_tick`.
- **Declared estimand feature.** `observation_ambiguous` and `illegal_cell` live on the replaced
  `evaluate_decision` path, so this rule does not apply them. The candidate therefore takes in exactly
  the cases the champion refuses. When the running max spans two rungs, both rungs are eligible; that
  gives multiple same-side qty-1 legs, which L-40 permits.

## 2. Take rule (the replacement body of `compose_decision`; r4 ruling 3)
Named constants, stored in the manifest:
- `TAKER_FEE_COEFFICIENT = 0.0695` (registered; EDGE-1 probe AGREEs)
- `SLIPPAGE_ALLOWANCE = 0.01` (AUD-12a)
- `MARGIN = 0.0964`

`A_MAX = 1 − 0.0695 − 0.01 − 0.0964 = 0.8241`.

For each frame `_hunt_tick` passes in, with LST hour `h`, YES ask `a` and bid `b`, apply these steps
in order:
1. **NO leg:** always `Refuse("side_not_registered")`. NO-side hunting is H-NO-SIDE's scope.
2. `h ∉ {0..8, 17..23}` → `Refuse("outside_registered_hours")`.
3. `fee_coefficient is None` or mismatched → `Refuse("fee_schedule_mismatch")` (Barrier F1 is kept).
4. `b is not None and b ≥ a` → `Refuse("not_executable")` (the crossed-book gate is kept).
5. The existing executability predicate (`decision.py:386-395`, imported, never reimplemented) is false
   → `Refuse("not_executable")`. **Required:** AUD-12a's 0.01 only covers qty-1 orders that REFUSE on
   thin books.
6. **TAKE iff `0.01 < a ≤ A_MAX`.** Otherwise `Refuse("price_outside_registered_band")`.

The rule never reads `running_max`, `P_HOLD_LOWER`/`P_HOLD_UPPER`, the archive table, or any forecast.

**How to read "clears".** r4 says "clears `1 − θ − s − m`". This ruling reads it as `a ≤ 1 − θ − s − m`,
which is the same statement as `1 − a − θ − s ≥ m`.

**Why margin = 0.0964.** It is the design MDE at `min_station_days = 300` (§4), so it is outcome-free.
- A take's excess `W − BE(a)` can be at most `1 − BE(a)`.
- `BE(a) = a + θ·a(1−a) + s`, and `θ·a(1−a) ≤ θ/4 < θ`. So `1 − BE(a) > 1 − a − θ − s ≥ m`.
- Setting m to the MDE therefore guarantees every admitted take could, if it wins, carry the effect the
  test is powered to detect.
- It also keeps the rule out of the near-certain regime, where L-9 shows no seller exists.

**Why the floor at `a > 0.01`.** L-9's amendment: asks at the tick floor are "a lottery that has
already lost", and the tick grid cannot express a sub-tick edge.

**R14 (circularity) resolved by sequencing.** `SLIPPAGE_ALLOWANCE` is a named, swappable input. Any
change to it, or any AUD-12a re-estimate trigger, forces this ruling to be re-issued BEFORE the first
look. It is never swapped silently.

## 3. Trial-level hour join (O6; r4 ruling 2)
- `hour_lst` is computed per `FilledTrial` as `_local_hour(trial.filled_at_ns, std_utc_offset_hours)`
  (`strategy.py:214`). The offset comes from `default_registry().climate_day_window(...)`. It is
  computed at read time from the candidate unit's own `scored_trials_*.parquet`.
- It is NEVER taken from `ReplayResult.run_ts`, and never persisted on a row.
- Each trial is admitted if its hour is in `{0..8, 17..23}` and excluded otherwise, BEFORE aggregation to
  the per-station-day draw (`_draw_for_station_day` → `station_day_mean_x`).
- A mixed-hour station-day contributes only its admitted trials. A station-day with zero admitted trials
  is a zero-take day and is dropped (§6.1 zero-take rule).
- **The same admitted-trial filter must decide the with-takes count** that triage checks against
  `min_station_days`. Today that count is `max(row.fills)` (`hypothesis_triage.py:605`). It must never
  diverge from the draw set.

## 4. Design fixed before any CONFIRM data is opened
| Field | Value |
|---|---|
| `hypothesis_id` / `hypothesis_class` | `H-OFFWINDOW-T4-2026-09` / `pm_us_crh_offwindow_price_only` |
| `k_variants` | 1 |
| `programme_alpha_override` | 0.025 → `allocated_alpha` = 0.00625, `per_variant_alpha` = **0.00625** (RA-8b) |
| `look_policy` | `SINGLE_LOOK`. The one look fires on the first nightly triage run with admitted with-takes CONFIRM station-days ≥ `min_station_days`, AND every row passing C-validity |
| `min_station_days` (with-takes) | **300**. Matches the domain's 3–5-month accrual estimate. At ≤ 5 station-days/day (PM.us: 5 cities × HIGH) that is ≥ 60 days; realistically longer |
| Primary test | One-sided lower bound of the station-day cluster bootstrap of the mean (`cluster_bootstrap_ci`, `alpha = per_variant_alpha`) must be > 0 |
| Veto / cap | `pooled_net_pnl_per_contract > 0` and `max_single_day_leg_share ≤ 0.20` (alpha-free) |
| Outcomes | CONFIRMED only if the primary passes AND the veto is `NONE`. Primary passes but veto fails → `PRIMARY_PASSED_PNL_VETO`. Primary fails → `ABANDONED_CAP_EXHAUSTED` (the k=1 look is spent). The last two both feed RA-13 |
| KILL horizon | **180 days** from `registered_at`. If still PARKED at 180 days → HORIZON_STALL → RA-13 evidenced-KILL input. An AUD-12-caused stall is recorded as a separate, named cause |
| `mde_reference_ask` / θ / slippage / variance | 0.30 (house convention; not a claim about admitted asks) / 0.0695 / 0.01 / 0.25. YES-only qty 1 keeps each station-day same-side, so the 1/4 bound holds (L-40 amendment) |
| `order_quantity` / statistic | 1 / `MEAN_EXCESS_PER_TAKE` |
| `freeze_commit` | HEAD of the commit that lands the `register_hypothesis` call. CONFIRM = `climate_day > registered_at` |

## 5. Power check, plausibility bound, expected disposition
- **MDE.** `(z(1−0.00625) + z(0.80)) · 0.5 / √n`; the z-sum is ≈ 3.3393.
  - n = 300 → **0.0964**; n = 600 → **0.0682** (both within `MDE_MISMATCH_TOLERANCE` of the plan text).
  - `BE(0.30) = 0.324595`. At n = 300 this requires a hold rate of about 0.421 at a 0.30 ask, i.e. a
    **9.6-point** edge net of fees and slippage.
- **`mde_plausibility_bound = 0.04`.** This is the most generous house value (the H-NO-SIDE precedent
  for "untested territory"). Every comparator predates the freeze and is already signed:
  - WP-7b ask CI `[-0.02147, +0.02079]`;
  - forecast-taker confirmed CI `[-0.03229, -0.00373]`;
  - `daf81a1`: no tested hour clears zero;
  - L-9.
  Nothing in the repo supports a plausible edge of ≈ 10 points in any hour of this venue. `daf81a1`'s CIs
  are 0.15–0.35 wide; that is uninformative, not supportive.
- **`MDE (0.0964) > bound (0.04)` → expected disposition `UNDERPOWERED_NOT_REGISTERED`.** It consumes no
  alpha and no slot.
  - Reaching the bound would take n ≈ (3.3393 / 0.08)² ≈ **1743** with-takes station-days. That is
    ≥ 349 days even at 100% take-day accrual across all 5 stations.
  - Patience cannot rescue the design within any horizon this programme can defend.
- **Consequence for EDGE-5 (named, not decided here).** The trigger-4 path on PM.us at k = 1 cannot reach
  a look.
  - RA-9b/RA-9c/RA-10 lose their trigger-4 purpose.
  - The honest next step is RA-13's evidenced-KILL input (Kalshi item, `wip/kalshi-s4-registry`).
  - HUNT-1 remains BLOCKED-OPEN. This result is not a KILL of the operator requirement.
- **Conditional branch.** If the peer loop rules, on outcome-free pre-freeze evidence, that the bound is
  ≥ 0.0964, then §2–§4 apply unchanged as a REGISTERED look-taking record and §7 binds. Choosing a bound
  to make registration pass is prohibited (it is a forking path).

## 6. `variant_stratum_filters` (RA-2 schema v2)
`("station=ALL|hour_lst=0-8,17-23|side=YES|composition_kind=pm_us_crh_offwindow_price_cap_v1",)`

**This string is refused today.** `_HOUR_LST_RE` (`hypothesis_ledger.py:283`) admits only `ALL`, `N` or a
single `N-M`.

**Required first — RA-2b (S):** widen `_parse_hour_lst` to accept a comma-joined list of ascending,
pairwise-disjoint ranges within 0–23. Widen the exact barrier; never relax it (L-12).
- New RED: `test_hour_lst_accepts_disjoint_ascending_range_union`.
- REDs that must keep refusing: overlapping ranges, descending ranges, a wrap such as `17-8`.
- Rejected alternatives: `hour_lst=ALL` (no real binding), and k = 2 (halves α to 0.003125 and splits
  the estimand).

## 7. Preconditions for the actual `register_hypothesis` call
- **Path A — the expected UNDERPOWERED record.** It is zero-look, so no triage seam can rubber-stamp it.
  It may land as soon as:
  - RA-2b is merged;
  - this ruling is two-peer signed;
  - `register_and_persist(require_status="UNDERPOWERED_NOT_REGISTERED")` is used, mirroring
    `register_no_side_underpowered`.
- **Path B — a REGISTERED look-taking record, only if §5's bound is changed.** It must NOT land until ALL
  of these are merged:
  1. **RA-9c, stratum-scoped, not a merged list of sources.** Each record's `completed` rows AND its
     scored-trial store (`_store_dir`, `hypothesis_triage.py:165`, which today is always the
     champion's) are selected by that record's `composition_kind`. Candidate rows and champion rows
     never merge under the same `(station, climate_day)` key. Only `climate_day > registered_at` is
     admitted (§0), and the §3 trial filter is applied.
  2. **RA-9b's candidate source exists.** That means the unit, the manifest, the §2 compose body with a
     RED named `test_price_only_take_iff_ask_above_tick_floor_and_at_most_a_max_0_8241`, and the §3
     join. Its window-parameterized sufficiency (`replay_sufficiency.py`) feeds
     `_completed_on_whole_days`.
  3. **RA-9d (NEW, S): a per-record horizon.** Triage runs with the default `--horizon-days=21`
     (`hypothesis-triage-run.sh:42`, `:88`), and `_triage_record` returns HORIZON_STALL at `:581`
     BEFORE any n check. Every look-taking record older than 21 days would therefore be blocked from
     its look forever. Fix: honour the record's 180-day horizon.
  4. **Bootstrap resolution.** B = 400 at α = 0.00625 uses `stats[2]` (resolution 0.0025), so the test is
     not at 0.00625. Raise B until α·B ≥ 100 (B ≥ 16 000), or re-rule α accordingly.

## 8. Risks
- **Unequal admitted-trial counts per station-day (domain minor, r4).** `station_day_mean_x` weights a
  1-trial day and a 4-trial day equally, so the primary test is per station-day, not per contract.
  Mitigation: the per-contract pooled-P&L veto and the 0.20 leg-share cap. The divergence is declared,
  not corrected.
- **AUD-12 gates the first look (r4 ruling 4).** Until AUD-12b (EDGE-1) is live and RA-3's
  `AUD11_AND_AUD12_LANDED` flip is ruled, every row stays `MECHANISM_ONLY`. `_triage_record` then skips
  with C_VALIDITY (`:594-597`), and `promotion_criteria.py:427` rejects. Accrual can run with no look.
- **L-9 / TERMINAL forecast edge.** The rule does not harvest certainty (`A_MAX` excludes that regime),
  but the prior probability of an edge is low.
- **Two opposite mechanisms are pooled.** Overnight current rungs are usually surpassed later in the
  day; late-evening current rungs usually hold. A pooled null result can hide a signed sub-effect, and
  per-half diagnosis stays SEARCH only.
- **Capture holes.** The recorder's 09:00Z rotate falls inside 00–08 LST at every station. Add ~9%
  venue-skipped station-days and thin off-window books, and accrual is slower than the plan assumes.
- **Fee rounding** (`fees.py:215-229`) is separate from slippage and is not absorbed by the 0.01
  allowance.

## 9. Provisional flag
Any AUD-12a re-estimate trigger, or any change to θ, the slippage allowance or `A_MAX`, re-opens this
ruling. It must be re-issued before any look.

## 10. Operator-reserved controls — untouched
Clearing the A1 halt, live-trading enablement, and the max-daily-budget / max-per-position caps stay
operator-only. This ruling assigns no value to any of them and implies no enablement.

## 11. Peer-loop amendments (BINDING, override anything above)
Peers: the trading-bot-architect and the prediction-market-reviewer, each briefed blind. Coordinator decisions are marked (C).
- **A-1 (domain: the variance bound rule).**
  - The 0.25 bound is the true worst case over the rule's own admissible domain, because BE(a) = 0.5 lies inside `(0.01, 0.82]` (a ≈ 0.47).
  - Tightening the variance with an observed off-window ask or hold rate is outcome-dependent, and is prohibited (a forking path).
- **A-2 (domain: the tick).** The PM.us tick is 0.01 (`orderPriceMinTickSize=0.01` on every weather market), so the effective admissible ceiling is **0.82**. 0.8241 is not a reachable price.
- **A-3 (C: the α scope).** 0.025 is the programme-wide FWER for **every re-arm-gating hypothesis**.
  - Every future re-arm-gating registration MUST pass `programme_alpha_override=0.025`.
  - A research-only hypothesis may keep the 0.05 default, but its result can NEVER gate a re-arm or feed an A1-class ruling.
  - Follow-up RA-8c: enforce this in code by refusing a re-arm-gating flag without the override.
  - **A-3a (amendment 2026-09-27, LEDGER-V3 peer loop).** The bound is "≤ 0.025", not "exactly 0.025". A re-arm-gating registration MUST pass `programme_alpha_override` ≤ 0.025. A stricter α is conservative: it can only lower the FWER.
    - Peers: prediction-market-reviewer (round 2: "defensible… get an explicit sign-off") and trading-bot-architect (round 2: exact comparison is sound).
    - The code check is an exact float comparison with no tolerance (`allocated_alpha × MAX_HYPOTHESES ≤ 0.025`).
    - Changing MAX_HYPOTHESES (4) requires re-deriving this bound in a ruling first.
- **A-4 (domain: H-ARCHIVE-RECAL status).** Its registration status is `UNDERPOWERED_NOT_REGISTERED` (zero alpha). Its "accruing" refers only to EDGE-4's revival-trigger corpus tracking. The SEARCH forfeiture in §0 still binds that corpus.
- **A-5 (C: AUD-12 stalls).** Any 180-day horizon **pauses** while every candidate row is forced to `MECHANISM_ONLY` by the AUD-12 validity gate. The pause ends on the day the RA-3 flag is flipped by its own ruling. This is recorded in the look schedule.
- **A-6 (architect: a factual fix to §7 B-3).** `hypothesis-triage-run.sh` passes no `--horizon-days`. The 21-day default (`hypothesis_triage.py:88`) is what applies, and the defect stands.
- **A-7 (architect: RA-9c).** The merged RA-9c (named, ordered input sources; ea72d16) is inert infrastructure. It does **not** satisfy Path B item 1, which still needs `_store_dir` + `completed` scoped by `composition_kind` (follow-up RA-9c2).
- **A-8 (architect: the predicate).** `_is_executable` is private, so RA-9b must import a public alias.
- **A-9 (architect: dispositions).**
  - **RA-9b and RA-10 are PARKED.** Building and accruing for a design that cannot register only forfeits CONFIRM days. Reopen only if a peer-reviewed bound revision, from outcome-free pre-freeze evidence, clears §5.
  - **Build now:** RA-9d (a per-record horizon) and RA-9e (bootstrap B ≥ 16 000, i.e. α·B ≥ 100). Both are latent defects for ANY future look-taking hypothesis.
  - **Path A** (recording the UNDERPOWERED record) needs RA-2b (the two-range `hour_lst`) first.
- **Consequence.** The trigger-4 path at k = 1 on PM.us cannot reach a look. The honest next EDGE-5 step is the **RA-13 evidenced-KILL ruling**, with this ruling as an input. That opens the parked Kalshi item. HUNT-1 remains BLOCKED-OPEN (this is not a KILL of the operator requirement).

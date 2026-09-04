# PREREG v1-KALSHI — current_rung_hold sibling family on Kalshi (DRAFT, rev b)

Status: **DRAFT, not yet registered.** Registers the sibling family ordered by the strategy
lead's binding ruling, `docs/evidence/grok_prereg_v2_ratification_2026-09-04.md` §Final ruling
(2), and amended by two later rulings/evidence drops folded in below (no separate addendum
section — folded inline per section): `docs/evidence/grok_v2_score_statistic_ruling_2026-09-04.md`
(statistic (C), remaining-α truncation, no `venue:` axis, D0 discriminant) and
`docs/evidence/venue/kalshi/s0_2026-09-04/S0_FINDINGS_2026-09-04.md` +
`docs/plans/KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md` Rev 3 §Venue mechanics/§Fees (settlement
source, fee rounding, no NO-ticker, `client_order_id` latch). This document is the family's PREREG
artefact; it is not itself an enablement — the two operator-reserved caps and Kalshi
account/KYC/API-key issuance (plan §Operator items, S11) stay entirely outside it.

## 0. Provenance pins (frozen at registration — placeholders below until §9 closes)

| Pin | Value | Source |
|---|---|---|
| Family id | `current_rung_hold` / Kalshi (sibling, never pooled with PM) | ratification §Final ruling (2); plan Rev 3:9-11 |
| Trial-id prefix | `kalshi:current_rung_hold/trial/{station}/{climate_day}` — the sole venue-provenance carrier; **no `venue` column exists on the trial schema** (§4) | score-statistic ruling §(E):41,49 |
| Archive table pin | `archive_table_rev2` (own module, own `CORPUS_SHA256`/`STUDY_GIT_SHA`; v1's `archive_table.py` untouched) | plan §Stations "Corpus pin versioning" |
| Corpus window | 2021-01-01..2025-12-31, `mb_current_rung_edge_study.py:20,30` | plan Rev 3:99 |
| n_min per cell | 90 | plan Rev 3:99 |
| Parser fix (rev2 only) | `parse_metar_t_group` in `scripts/analysis/settlement_alignment_study.py` accepts the 4-digit short T-group (`\bT[01]\d{3}\b`), not only 8-digit — KBOS 7.1→59.4, KDEN 62.6→64.1, KEWR 49.4→65.7 rows/day; fixed RED-first, rev2-only, v1's pin untouched | plan Rev 3:101 |
| Sequential-tally path | New sibling module (e.g. `scripts/analysis/family_tally_v2.py`) consuming `ScoredTrial` directly — **v1's `live_family_tally.py`/`mb_current_rung_edge_study.build_realized_stratum` stay byte-unmodified while v1 is live** | ratification (3):287-289; score-statistic ruling last line:51 |
| Boundary/spending generator | Emits a **spending function of `t`**, not 16 z-values at equal `n`; sha256 of `{α=0.025, LD-OBF, look schedule, n_max=160, I_max=40}` pinned before first fill | score-statistic ruling:9,19-21 |

## 1. Hypothesis (falsifiable, one sentence)

Among live 1-contract IOC buys of the Kalshi venue rung currently containing the unambiguous
running max, on the family's own admitted station set, taken only when the frozen rev2 archive
Wilson-lower `p_hold` exceeds the per-trial `BE_i = entry_ask_i + fee_i`, the **realized** score
`S_k = Σ(held_i − BE_i) / sqrt(Σ BE_i(1−BE_i))` crosses the efficacy boundary before the futility
boundary or the calendar/loss stop, under the group-sequential design in §5 — never v1's fixed
60/150 Wilson comparison (v1 §1:24-28; score-statistic ruling §Statistic (C)).

## 2. Population

- **Stations — admission gate is ordered; none of the 19 candidates is admitted by this document
  alone** (`kalshi_station_temp_cadence_2026-09-04.md:139`):
  1. **Cadence, two sample months including winter**: median-of-daily-medians ≤5 min **and** ≥90%
     of days with daily median ≤5 min, **and** temperature-bearing cadence on **both** feeds (live
     `api.weather.gov` observations, archive IEM METAR T-group) — not merely record cadence
     (`kalshi_station_cadence_2026-09-04.md:9`; plan Rev 3:81,85).
  2. Station name taken from `rules_primary` only, never `settlement_sources` or geography
     (plan Rev 3:91).
  3. **CLI-final vs venue-settled, per station — the load-bearing test.** Kalshi settles on **The
     Weather Company**, not the NWS CLI product: `rules_primary` names CLILAX only as the station
     identifier while `settlement_sources` and `rules_secondary` both name TWC as the authority
     (`S0_FINDINGS_2026-09-04.md` item 10.4). This is **not the same event-source pair PM uses** —
     the two venues settle on the **same weather event, different settlement source**, not "one
     NWS CLI event" as earlier drafts stated (plan Rev 3:9, correcting `KALSHI_CRH_EXPANSION_PLAN`
     Rev 2's premise). The PM four-station CLI-vs-venue divergence rate is **not inherited and is
     UNMEASURED for Kalshi**. Gate: n≥90 settled HIGH events per station, agreement = venue
     `result` equals the CLI-FINAL winner via `WeatherBucketFacts.contains`, Wilson lower
     (`z=1.959963984540054`) > 0.99, voids counted separately and **raise** (plan Rev 3:91).
- **Candidate set (19), current status:**
  - **18 ADMITTABLE on gate item 1:** KATL, KAUS, KBOS, KDFW, KLAS, KSDF, KMSP, KMSY, KEWR, KOKC,
    KPHL, KPHX, KSAT, KSAN, KSEA, KTTN, KDCA, KHOU* (plan Rev 3:86).
  - **KDEN — HELD.** Archive clean; live NWS feed published only 6 observations on 2026-09-03
    (60-min median) — recheck ≥2 further days (plan Rev 3:87).
  - **KHOU — HELD.** Live 5-min clean; archive loses 5-min rows mid-2025-07 (hourly-only after) —
    usable corpus density must be sized in S9 (plan Rev 3:88).
  - **NYC/KNYC excluded** — hourly-only on both feeds, confirmed as a control
    (`kalshi_station_temp_cadence_2026-09-04.md:33,50`).
  - **Gate item 3 is UNMEASURED for every candidate as of this draft** — no candidate clears the
    full ordered gate yet. The frozen admitted set is fixed **only at registration**; any station
    added after registration is a **new family**, mirroring v1 §7's restart rule.
  - Existing four PM cities (LAX, MDW, MIA, SFO) may also run on Kalshi — **same-city fills on
    both venues are admissible in each family** (pseudo-replication is within-family only), but add
    PnL rows, **not independent hold-rate events**, so they never accelerate this family's own `n`
    beyond its own fills.
- **Legal cells, unit of observation, "not trials"** — unchanged from v1 §2
  (`decision.py:29-40,214-225`; v1 §2:38-47).
- **Shadow rows are a diagnostic prefix only** — measure take rate and selector reachability;
  enter **neither** the kill nor the survive side, never enter the sequential tally, never
  retroactively scored (plan Rev 3, R2).

## 3. The exact take rule (frozen per instance) — selector unchanged, θ/rounding/market-shape substituted

Evaluated by the same `evaluate_decision` (`decision.py:238-287`), same binding order as v1 §3.
Per-instance substitutions and Kalshi-specific mechanics:

- `stations=` the admitted subset only (frozen at registration; see §2).
- `required_fee_coefficient=Decimal("0.07")` — **UNVERIFIED, remains a placeholder.** The series
  object VERIFIES the fee **model** (`fee_type="quadratic"`, `fee_multiplier=1`, uniform across all
  102 daily series) but not the coefficient: a grep for `0.07`/"trading fee" over the entire 531 KB
  `llms-full.txt` returns nothing, and the fee-schedule PDF on `kalshi.com` returns HTTP 429 to
  every non-browser agent. Two admissible closures: operator fetch of the PDF, or deriving θ from
  the first real fill's `average_fee_paid` against known `count`/`price`
  (`S0_FINDINGS_2026-09-04.md` item 5.2; plan Rev 3:108).
- `fee_rounding_rule="kalshi_ceil6dp_order_accumulator"` (**replaces** the earlier
  `fee_rounding="up"` field name — that field described a rule Kalshi does not have). Per
  `fee_rounding.md`, verbatim: trade fee = `ceil_6dp(model_fee)`, then an
  `aligned_change`/`rounding_fee` split, **plus a fee accumulator maintained per ORDER across all
  fills** (net fee = trade fee + rounding fee − rebate). `KalshiFeeModel(FeeModel)` implements
  exactly this, mirroring `fees.py:80`'s keyword-invocation discipline (`:70-79`). Config field
  is `fee_rounding_rule ∈ {"half_even", "kalshi_ceil6dp_order_accumulator"}`, validated at
  `config.py:239`, defaulting `"half_even"` (v1 unchanged); Kalshi pins its own rule
  (`S0_FINDINGS_2026-09-04.md` item 5.4; plan Rev 3:109-110).
- **Settlement-leg fee: VERIFIED ZERO for this product.** `market_settlement.md`: "Settlement fees
  are zero for simple yes/no determinations"; KXHIGH*/KXLOWT* markets are `market_type:"binary"`
  with a yes/no `result`. `trial_scorer.py:187`'s zero-settlement-leg assumption **holds** —
  **confirmed by one measured real settlement** before any Kalshi row enters a verdict, not merely
  asserted from documentation (`S0_FINDINGS_2026-09-04.md` item 5.5; plan Rev 3:111).
- **No NO-ticker.** `order_direction.md`: `bid ≡ yes`, `ask ≡ no`, always; the orderbook returns
  yes-bids and no-bids of the **same** book (`yes_ask 0.41 = 1 − no_bid 0.59`). **One `BinaryOption`
  instrument per market ticker**, one signed position; the bot is BUY-YES-only →
  **`side="bid"`, always**; a NO-side instrument is never constructed
  (`S0_FINDINGS_2026-09-04.md` item 6.1; plan Rev 3:49-51). `order_quantity=1` (contracts).
- **Precision is read per market, never assumed.** `tick_size` is deprecated (removal 2026-05-07);
  precision comes from `price_level_structure` + `price_ranges[].step` (fixed-point dollar strings,
  e.g. `linear_cent` at step `"0.0100"`; tapered structures exist and must be read live, never
  hardcoded to a cent) (`S0_FINDINGS_2026-09-04.md` items 4.1/4.3/6.3; plan Rev 3:53).
- **`client_order_id` is the durable-latch key**, derived deterministically from the trial id
  (`kalshi:current_rung_hold/trial/{station}/{climate_day}`), so the local record and the
  venue-side identifier are one string. **The venue's behaviour on a duplicate `client_order_id`
  is UNVERIFIED** — the vendor text is silent on reject/dedupe/second-order. The latch is
  therefore **not** relaxed to "the venue refuses duplicates": after any ambiguous submit the
  client reconciles first (`GET /portfolio/orders?status=resting` + `GET /portfolio/fills`, matched
  on `client_order_id`) and only resubmits once both reads prove absence — **reconcile-before-
  resubmit is the authority**, a possible venue-side duplicate rejection is a second belt, never
  the first (`S0_FINDINGS_2026-09-04.md` item 6.5; plan Rev 3:61).
- All other frozen defaults (`executable_ask_lower/upper`, `minimum_displayed_size`,
  `allow_short=False`, `entry_only_halt=True`, staleness rule) inherit v1 §3 unchanged.
- **This family runs SHADOW until, per instance:** (a) θ is pinned against a published schedule or
  a first-fill derivation, and (b) at least one real fill confirms rounding and the zero
  settlement-leg fee in practice.

## 4. The exact scoring rule (frozen)

Identical to v1 §4 (`SCORER_TALLY_BCA_BRIEF_2026-09-04.md`), with one addition and one explicit
**non**-addition, both corrected from an earlier draft of this document by the score-statistic
ruling:

- **Per-trial break-even applies to this family's tally only.** `BE_i = entry_ask_i + fee_i` (fee
  already stored on `ScoredTrial`, `trial_scorer.py:107,138`); v1's own tally stays on
  `break_even(mean_ask)`, byte-unmodified (ratification (2) "S2 per-trial BE: v2/Kalshi tally path
  only; v1 byte-identical").
- **No `venue` field is added to `FilledTrial`/`ScoredTrial`, and no `venue:` stratum exists.**
  `ScoredTrial`'s schema is **17 columns** and adding one is forbidden
  (`trial_scorer.py:119-138`; `scored_trial_store.py:53-72`); venue provenance is carried
  **entirely by the trial-id prefix** (§0). Strata for this family are **pooled, station, and
  ask-band only** — the same three v1 uses, never a fourth `venue:` axis, because this is a
  single-venue family and `venue:*` would be identical to pooled
  (score-statistic ruling §(E):39-41).
- FINAL-print-only scoring, the fallback-exclusion rule, and the ask-band/basis split are
  otherwise unchanged from v1 §4.

## 5. The exact pre-declared analysis (frozen) — v2's ruled statistic (C), inherited verbatim

This family inherits v2's group-sequential design **exactly as last ruled**, correcting an earlier
plug-in `Z_k`/`π_k`/`t_k=n_k/n_max` form that this document previously carried
(`grok_v2_score_statistic_ruling_2026-09-04.md`, replacing `PREREG_v1_kalshi` draft §5):

- **Statistic (ruled form C):**
  `S_k = Σ_i (held_i − BE_i) / sqrt(Σ_i BE_i(1−BE_i))`, `I_k = Σ_i BE_i(1−BE_i)`,
  `t_k = min(1, I_k / I_max)`. Under `held_i | ask_i ~ Bern(BE_i)` with `BE_i` known, the numerator
  has independent increments; a re-estimated `π_k`/`nπ(1−π)` (the earlier plug-in form) does not,
  because `x(1−x)` is concave (score-statistic ruling:9,14-19).
- **`I_max = 40`**, pinned as `n_max × 1/4` (the Bernoulli bound `p(1−p) ≤ 1/4`, ratified
  `n_max=160`) — **never** live asks, look-1 `π`, archive mean, or realized `I_160`
  (score-statistic ruling:21). Pinned in the generator's input sha256 before the first fill.
- **Boundary form:** Lan-DeMets O'Brien-Fleming spending, two one-sided tests, each α = 0.025,
  evaluated at each look's **realized** `I_k` (not equal-`n` z-values) — the generator emits a
  spending function of `t`, not 16 fixed z-values (score-statistic ruling:19).
- **Look schedule:** every 10 filled Takes, `n_k = 10, …, 160` (pooled only — station/ask-band
  strata stay fixed-rule `cell_dead` kills at n≥60 against `mean(BE_i)`, unsequentialized,
  score-statistic ruling:27).
- **Truncation — remaining-α, not cumulative-α-through-look.** If `D0+165` or `ΣPnL≤−60` fires
  before `n_max=160`: `t_trunc = min(1, I_trunc/I_max)`; spend is the **remaining** α
  (`0.025 − α_spent(last completed scheduled look)`, or 0.025 if none) — **an earlier statement in
  this document that truncation spends "cumulative alpha spent through that look" was WRONG and is
  corrected here** (score-statistic ruling §(D):34, explicitly naming and rejecting that wording).
  BCa is computed once, after this terminal look. **CONTINUE is illegal** at truncation: an
  off-grid `n` is itself a look, not `None`/an unadjusted look-16 `z` (score-statistic ruling:31).
  At `D0+165` both KILL and SURVIVE remain possible (SURVIVE ⇔ `S_k ≥ b_trunc^eff` ∧ ΣPnL>0 ∧ no
  `cell_dead`; KILL ⇔ `S_k ≤ b_trunc^fut` ∨ `cell_dead` ∨ fail-closed mid-band). At `ΣPnL≤−60`,
  SURVIVE is impossible (ΣPnL>0 fails) — family closes KILL, efficacy remaining-α is vacuous
  (score-statistic ruling:36-37).
- **Terminal quantities unchanged and terminal-only:** BCa ROI bound
  (`src/breezy/settlement/roi_bound.py:93-112`) computed once, never per-look; ΣPnL > 0 required
  in addition to any boundary crossing for SURVIVE.
- **Boundary generation is a prerequisite, shared with v2** —
  `scripts/analysis/crh_group_sequential_boundaries.py`, run against this family's own admitted
  stations' realized `BE_i`, pinning `I_max=40` and the score form above, not the earlier plug-in.

## 6. Stop rules

- **KILL** → stop immediately, no resurrection.
- **Time stop:** D0 + 165 calendar days. **Loss stop:** ΣPnL ≤ −60 contract-units (never dollars).
- **Spending-to-horizon at truncation:** per §5 above — remaining α at `t_trunc`, CONTINUE illegal.
- **Pending trials at horizon:** unchanged from v1 §6:132-135.
- **Structural-dead pin**, identical machinery to v2 §9's amendment target, with the **Kalshi
  family's admitted station set as the denominator**:

| Piece | Definition | Cite |
|---|---|---|
| Window | [12:00,17:00) LST | v1 §2:35-36 |
| Afternoon-covered | span of distinct captured quote instants in that window ≥30 min; 0–1 instant ⇒ 0 | `ma_prelock_winner_ask_study.py:160,323-332,360-361` |
| Listed | venue listed that station-day; skip-days ∉ denominator | v1 §2:45-47 |
| Denominator | covered **listed** station-days of **this family's admitted Kalshi station set** | ratification (1)(f); this doc §2 |
| Fire at | count ≥15 | `MIN_AFTERNOON_STATION_DAYS=15` |
| "≈0" | filled Takes = 0 on those days; one fill kills this stop (L-9 "no seller") | ratification (1)(f) |

## 7. D0 and clock (arithmetic, not a forecast)

- **D0 rule (binding):** the first UTC day **after** (a) this document is committed as the
  family's spec, and (b) a Kalshi-only tally is actually running against §5's pinned boundary
  table for its verdict logic. Any fill occurring before both (a) and (b) does not belong to this
  family.
- **D0 discriminant (ruled): `climate_day ≥ d0_utc_day`** (LST station-day), not a fill-timestamp
  comparison. The latch key is `(station, climate_day)` (`trial_day_latch.py:113-114`);
  `climate_day` is LST, never DST; `ScoredTrial` carries `climate_day` and **no** fill timestamp
  (`trial_scorer.py:119-138` — `FilledTrial.filled_at_ns` exists at `:109` but the tally reads
  `ScoredTrial`). Given the afternoon window `[12:00,17:00)` LST and this family's station UTC
  offsets, a fill lands in UTC `{D, D+1}` for climate_day `D` and **never `D−1`** — so
  `climate_day ≥ d0_utc_day` is the conservative discriminant, strictly stronger than "any fill
  before D0 is v1-only" (score-statistic ruling §(F):43-49).
- **Clock arithmetic**, named-assumption arithmetic, not a commitment: 18 admittable candidates +
  4 dense PM stations = 22 (KDEN/KHOU HELD, excluded pending §2's gate); observed take rate 0.25
  taken/listed-station-day. Events/day = 22 × 0.25 = 5.5. `n=60` at ≈ D0+11 d; `n=150` at
  ≈ D0+28 d; `n=160` at ≈ D0+30 d. **Kalshi's actual take rate is UNVERIFIED and must be re-sized
  from shadow (S10) before this arithmetic is treated as a schedule.**

## 8. What will NOT change after the first Kalshi order

Frozen for the life of this family: every per-instance value in §3; the rev2 archive table's
cells, `CORPUS_SHA256`, `STUDY_GIT_SHA`; the take-rule order and refusal-reason set; §4's per-trial
BE formula for this family's own tally, and the **absence** of a `venue` column/stratum; the §5
score form (`S_k`, `I_k`, `I_max=40`), α=0.025, LD-OBF spending, look schedule, n_max=160, and the
remaining-α truncation rule; the BCa statistic, B, seed, and 0.20 exclusion ceiling; the admitted
station set; the D0 discriminant (`climate_day ≥ d0_utc_day`); the one-instrument/`side="bid"`
market model; `fee_rounding_rule`; the `client_order_id` latch and reconcile-before-resubmit
discipline. No floor is lowered, no post-hoc screen is added. **Any change requires a NEW
pre-registration document; this family restarts (n resets to 0) rather than being amended in
place** (v1 §7:147-150, inherited). **This family never pools with the PM family, at any point, for
any reason.**

## 9. Registration checklist — must ALL be TRUE before DRAFT → BINDING

| # | Item | Not yet true because |
|---|---|---|
| 1 | **θ verified** against a published fee schedule OR derived from a real fill's `average_fee_paid` | PDF returns HTTP 429 to non-browser agents; no fill exists yet (`S0_FINDINGS` item 5.2) |
| 2 | **`fee_rounding_rule` and settlement-leg-zero confirmed by one real measured settlement**, not documentation alone | no Kalshi execution client exists; documentation-only confirmation stands (`S0_FINDINGS` items 5.4/5.5) |
| 3 | **First real fill confirms (1) and (2) in practice** | no `src/breezy/adapters/kalshi/` execution path exists (plan Rev 3 §Inventory) |
| 4 | **Rev2 archive cells generated with a recorded sha256**, parser fix landed and re-measured | rev2 table not yet emitted (plan S9 not started) |
| 5 | **Admission evidence closed per station**, in order: temp-bearing two-month cadence, `rules_primary` identity, CLI-final-vs-**TWC**-settled (n≥90, Wilson lower >0.99, voids raising) | gate item 3 UNMEASURED for all candidates; KDEN/KHOU HELD on gate item 1 |
| 6 | **Kalshi permit and enablement are operator-gated and separate from Polymarket's** — own verified-canonical-string flag, own operator-requested flag, cross-venue permit misuse raises `TypeError` | `OrderSubmissionPermit` is currently venue-blind and would inherit PM's already-`True` verified flag |
| 7 | **`client_order_id`-keyed latch built and reconcile-before-resubmit path implemented** | R-7 latch not yet re-decided in code; duplicate-id venue behaviour still UNVERIFIED |
| 8 | **Kalshi-only tally running against the §5-pinned boundary table** (D0 rule clause (b)) | boundary generator not yet emitting the ruled `S_k`/`I_k` form; no `family_tally_v2.py`-shaped module exists |
| 9 | **Operator prerequisites satisfied** — Kalshi account, KYC/eligibility, funding, API key | operator-only, on the critical path (plan Rev 3 §Operator items) |

Until all nine are true, this document remains DRAFT and authorizes nothing — no Kalshi order,
shadow or otherwise, may be constructed against it.

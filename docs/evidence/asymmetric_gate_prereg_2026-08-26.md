# Pre-registration — Asymmetric settlement-alignment gate

**Written:** 2026-08-26. **Revision 14** (amended same day). **APPROVED.**
**Status:** PRE-REGISTRATION. Written BEFORE any asymmetric statistic has been
computed. No asymmetric hit rate exists in this repo at the time of writing.
**Authorises:** nothing yet. Computation is gated on adversarial domain review
(see §8) and belongs to backlog item G-17, not to this document.

> **Revision 14 applies the two ADVISORY amendments from round 13, which
> returned APPROVE-WITH-AMENDMENTS** — the first non-BLOCK verdict in fourteen
> revisions and thirteen adversarial reviews. G-17 is now authorised **on
> methodological grounds**, and remains unconditionally blocked on G-16 (>=14
> days of captured tape), which is an operational blocker and not a
> methodological objection. Amendments marked **[R14]**; record in §10l.
>
> **Revision 13 amended revision 12 in response to a TWELFTH BLOCK verdict.**
> Round 12 confirmed round 11's finding closed and found "everything else in the
> document is now sound", but caught that revision 12's new
> `PROVISIONAL-UNDERPOWERED` state **copied STRUCTURALLY UNREACHABLE's exemption
> from the expiry clock without copying its escalation** — so a cell landing
> there could never resolve to GO or NO-GO, reopening the DOM-1
> non-falsifiability hole for exactly the cells the document predicts will land
> there. Corrected here; amendments marked **[R13]**; record in §10k.
>
> **Revision 12 amended revision 11 in response to an ELEVENTH BLOCK verdict.**
> Round 11 confirmed round 10's finding closed, then found revision 11's own
> closing sentence self-contradictory: "mark the cell Branch B ... do not fall
> back to the pooled anchor" — but Branch B is *defined* as `2c-1`/`c` on the
> whole-city **pooled** concordance, so the instruction and its mechanism said
> opposite things, "reproducing round 9's population-mismatch defect silently,
> dressed in different terminology." Corrected here; amendments marked
> **[R12]**; record in §10j.
>
> **Revision 11 amended revision 10 in response to a TENTH BLOCK verdict.** Round 10
> found revision 10's representativeness diagnostic **pointed at the wrong
> partition**: the passage correctly derives that the tradeable subpopulation is
> the *early*-in-day one (the market closes before the 14:00-16:00 daily-max
> window), then instructs the implementer to substitute the *late*-window
> anchor. The two sentences contradict each other, and the error fires exactly
> when the diagnostic matters — producing "false confidence that a control has
> run, not merely a missing control." Corrected here; amendments marked
> **[R11]**; record in §10i.
>
> **Revision 10 amended revision 9 in response to a NINTH BLOCK verdict.** Round 9
> confirmed the anchor/gate-statistic separation was implemented cleanly with no
> residual contradiction, then found the separation created a **population
> mismatch**: `H(c,k)` now conditions on tradeability while `p̂_anchor(c,k)` does
> not, so for LAX/SFO — where DOM-9 is plausibly a *partial, day-varying*
> constraint rather than a clean binary — the anchor may measure a different
> population than the statistic it sizes. Revision 10 adds the diagnostic check
> that settles it empirically. Amendments marked **[R10]**; record in §10h.
>
> **Revision 9 amended revision 8 in response to an EIGHTH BLOCK verdict.** Round 8
> confirmed round 7's finding closed, then found revision 8's own DOM-9
> "prerequisite" clause was the same failure mode on the *declared-blocker* side:
> it announced a gate that the four-step construction does not implement, and
> its two sentences contradicted each other on whether DOM-9 blocks the anchor
> at all. Revision 9 takes the reviewer's second option, which is the correct
> one on the merits: the anchor is a **power anchor, not the gate statistic**,
> so tradeability does not belong in it. DOM-9 is relocated to where it does
> belong — the `FIRE` predicate of the gate statistic. Amendments marked
> **[R9]**; record in §10g.
>
> **Revision 8 amended revision 7 in response to a SEVENTH BLOCK verdict.** Round 7
> confirmed both of round 6's findings genuinely closed, then found that
> revision 7's own new 45-minute lag proxy carried an **unfounded conservatism
> claim**: a constant additive shift cannot change the relative order of
> observations, so the order-based crossing determination — and therefore the
> anchor — is numerically invariant to LAG absent a real-clock cutoff. The claim
> was "a no-op dressed as a safety margin". This is the same shape as the
> guessed-discount defects of rounds 5 and 6, committed by this document one
> revision after it recorded the lesson. Amendments marked **[R8]**; record in
> §10f.
>
> **Revision 7 amended revision 6 in response to a SIXTH BLOCK verdict.** Round 6
> found revision 6's "computable today" claim was **false as written**: the
> cited script strata by `metar_max.rounded_max_f - margin` — the city-day's
> *final* max, known only in hindsight — not by the running max at receipt that
> §4 requires, and its margins (0..3) cannot produce the `[3,5)` and `[5,∞)`
> bins at all. It also found the archive-underpowered fallback ordering was
> self-contradictory: its first option was the very source the branch premise
> declares unavailable, so it could only ever resolve to the guessed discount,
> silently. Both **independently verified by the coordinator against
> `scripts/analysis/settlement_alignment_study.py`** before amending.
> Amendments marked **[R7]**; record in §10e.
>
> **Revision 6 amended revision 5 in response to a FIFTH BLOCK verdict.** Round 5
> confirmed revision 5 cleanly closed all three prior paper-closes, then found a
> deeper defect: the Wilson lower bound converges to `p̂` **from below** and never
> exceeds it, so when `BE(c,k) > p̂_anchor(c,k)` **no finite `N` exists** — the
> floor is not large, it is undefined. Revision 5's arbitrary 2x error discount
> put four of five cities' boundary strata in exactly that position, which would
> have produced a programme-wide NO-GO "by arithmetic, not by evidence."
> Revision 6 replaces the guessed discount with a **measurable** one and adds
> explicit unreachability handling. Amendments marked **[R6]**; record in §10d.
>
> **Revision 5 amended revision 4 in response to a FOURTH BLOCK verdict.** The
> review found revision 4 reintroduced the paper-close pattern *inside the very
> formula meant to fix it*: the stated equation `min(c, 2c)` reduces to `c`,
> making it a per-city constant with **zero stratum dependence** — the exact
> defect it claimed to remove — while the bullets below it defined a different
> and materially more conservative value (`2c-1`). Corrected here; amendments
> marked **[R5]**. Record in §10c.
>
> **Revision 4 amended revision 3 in response to a THIRD BLOCK verdict.** The
> review found revision 3's `p̂` fix was **paper-closed**: the prose announced a
> replacement anchor while the binding `N(c,k)` formula still hardcoded the
> discredited `0.985`, so "the math a G-17 implementer would actually run is
> unchanged from the version that was BLOCKed for circularity." It also found
> the prose describing the new concordance table was **inverted** relative to
> the table itself. Both are corrected here; amendments marked **[R4]**. Full
> record in §10b.
>
> **Revision 3 amended revision 2 in response to a SECOND BLOCK verdict.** The
> re-review found that revision 2's new `H2` statistic reintroduced the DOM-1
> defect it had just fixed for `H`, and that the `p̂ = 0.985` power anchor
> merely *relocated* revision 1's circularity — from presupposing the target
> hit rate to presupposing that price ≈ true probability, which is exactly what
> DOM-10 disputes. Amendments marked **[R3]**; full record in §10.
>
> **Revision 2 amended revision 1 in response to a BLOCK verdict from adversarial
> domain review.** The review found that revision 1's central empirical premise —
> that METAR reads *below* CLI, the conservative direction for this rule — is
> **already falsified at MDW** by data sitting in this repo. Revision 1
> generalised from four cities while omitting the fifth, whose sign contradicts
> the mechanism. Amendments are marked **[R2]** throughout. The review's full
> findings are recorded in §10.

---

## 1. Why this document exists, and the hazard it must survive

The pre-registered **2 °F symmetric bucket-alignment gate FAILED all five
cities.** A post-hoc boundary guard-band sweep did not rescue it: agreement
DEGRADED as the guard tightened (0.764 → 0.688) while retention collapsed to
12.97%.

This document proposes testing a **different, asymmetric** formulation. That is
exactly the shape of a post-hoc rescue, and it must be treated as guilty until
proven otherwise. Reformulating a failed gate into a shape that passes is
p-hacking by default.

The defence is ordering, and it is a hard requirement:

1. Write this pre-registration. *(this document)*
2. Adversarial domain review of this pre-registration. *(§8)*
3. Only then compute the statistic. *(G-17)*

If any part of §§2–7 were written after the asymmetric number was known, this
document would be worthless regardless of how sound its reasoning reads. It is
recorded here that no such number exists yet.

## 2. The argument that the symmetric gate was the wrong instrument

**This argument must stand on its own, without reference to the failed result.
If it does not, that is itself the answer.**

The Tier-1 decision rule is one-sided by construction. It buys **only after**
the observed METAR running maximum has already cleared the strike, and it
refuses the P≈0 side entirely. It never takes a position that depends on the
temperature *not* having been reached.

A symmetric bucket-alignment test asks: *does METAR agree with CLI, in both
directions, within ±2 °F?* That is a test of **estimator agreement**.

The rule does not need estimator agreement. It needs a one-sided guarantee:
*given that METAR says the strike was cleared, does CLI also say so?* Errors in
the other direction — METAR reading **below** CLI — do not cost the rule money.
They cost it *trades it never took*. They are missed opportunity, not loss.

So the symmetric test measures a quantity strictly larger than the rule's risk,
and can fail on error mass that is, for this rule, harmless. A one-sided rule
requires a one-sided test. This would have been true had the symmetric gate
passed.

**The honest counter-argument**, which the review in §8 must weigh: this
reasoning is *available* before the result, but it was not *acted on* before the
result. The symmetric gate was the one actually pre-registered. That sequencing
is a genuine mark against this proposal and is not explained away here.

## 3. What is already known about the residual — per city, with signs **[R2]**

The failure is **not** boundary noise. But nor is it uniform in direction, and
revision 1 was wrong to present it as though it were.

Per-city signed error (`rounded_metar_max_f - cli_tmax_f`), measured, from
`docs/evidence/settlement_alignment_diagnosis_2026-08-25.md` §1:

| City | Mean signed °F | METAR < CLI | METAR > CLI | Direction for this rule |
|---|---:|---:|---:|---|
| NYC | -0.668688 | 99.71% | 0.29% | conservative (degenerately so) |
| MIA | -0.118036 | 63.03% | 36.97% | conservative |
| LAX | -0.102198 | 57.36% | 42.64% | conservative |
| SFO | -0.051695 | 54.04% | 45.96% | weakly conservative |
| **MDW** | **+0.052574** | **43.63%** | **56.37%** | **DANGEROUS — reversed** |

**MDW runs the wrong way.** METAR reads *above* CLI more often than below. That
is precisely the non-conservative direction for an asymmetric rule: METAR clears
the strike, the position opens, and CLI then settles below it. The mechanism
proposed in revision 1 — sparse sampling misses peaks, so METAR under-reports —
does not hold at MDW, and any claim that the bias is "conservative" as a general
property of the estimator is **falsified by this repo's own data**.

MDW's tail makes it worse, not better. Its signed-difference distribution
carries `7: 1, 9: 1, 12: 1` — three days on which METAR exceeded CLI by 7 °F or
more. Those are exactly the days on which an asymmetric rule fires confidently
and settles wrong. NYC, by contrast, has one -15 outlier in the harmless
direction.

**What survives.** The one-sided-instrument argument of §2 is unaffected: it is
an argument about which *test* matches a one-sided *rule*, and it stands
regardless of which way the bias points at any given site. What does NOT survive
is the empirical expectation that the asymmetric statistic will therefore look
better. At MDW it should be expected to look **worse** than the symmetric one,
and §5 is amended so that this is a pre-declared prediction rather than a
post-hoc explanation.

**NYC's degeneracy is a separate matter.** KNYC (Central Park) reports ~29
observations/day against ~306 at the airport ASOS sites, and NYC is 99.71%
one-directional. That is a sampling artefact of a different kind — see §7.

## 4. Hypothesis and statistic

**Decision predicate under test.** For city `c`, climate-day `d`, strike `s`:

    FIRE(c, d, s)  iff  max{ METAR temp observed by Breezy, at Breezy receipt
                             time, on day d, city c } >= s
                        AND the crossing occurs while market (c,d,s) is open
                            for trading                                   [R9]

**Statistic.** The one-sided hit rate

    H(c, k) = P( CLI_tmax(c,d) >= s  |  FIRE(c,d,s) and clearance stratum k )

reported with a **Wilson lower bound** at 95%, per city `c` and per
degree-of-clearance stratum `k`, where clearance = `METAR_running_max - s`.

Reuse `wilson_lower_bound` from `scripts/analysis/settlement_alignment_study.py`
(~line 206). Do not re-derive it.

**Timestamp definition (DOM-2 / ARC-3).** `t_cross` is **Breezy's own receipt
timestamp**, never the METAR *valid* time. Keying on valid time would grant the
analysis 5–45 minutes of information the live strategy will not have, and
produces a false GO.

**Tradeability condition and DOM-9 [R9].** The second conjunct above is where
DOM-9 lands. Verbatim: "Market trading hours appear nowhere in the register. The
daily max occurs 14:00-16:00 local = 17:00-19:00 ET for LAX/SFO; if trading
closes before then, Tier 1 is a three-city strategy." A crossing that happens
after the market has closed is not a trade the strategy could have taken, and
counting it in `H(c,k)` would measure a strategy that does not exist.

Consequences, pre-declared:

- **`H(c,k)` cannot be finalised for LAX and SFO until DOM-9's actual trading
  hours are known.** This is a genuine blocking dependency on the *gate
  statistic*, and it is recorded as such.
- It does **not** block `p̂_anchor(c,k)` for any city (§7) — the anchor measures
  the METAR-versus-CLI relationship, not tradeability.
- If DOM-9 resolves such that LAX and SFO are untradeable at the relevant hours,
  those cities are **out of scope entirely** rather than NO-GO: there is no
  strategy to evaluate. Report them as OUT-OF-SCOPE-DOM-9, distinct from NO-GO,
  and exclude them from the §7 rule-3 count of city failures — a city that
  cannot be traded is not evidence about the instrument.
- **Concrete criterion for OUT-OF-SCOPE-DOM-9 [R10]**, so the boundary is not
  left to implementer judgement: a city is OUT-OF-SCOPE only if **fewer than 10%
  of historical city-days have their daily maximum occur before the venue's
  actual close**. Between 10% and 90%, the city is **IN SCOPE with a reduced
  sample** — `H(c,k)` is computed over the tradeable subset only, and the
  representativeness diagnostic of §7 governs its anchor. Above 90%, DOM-9 is
  immaterial for that city. The trigger is an objective venue fact combined with
  historical timing, not an observed hit rate, so it cannot be reverse-engineered
  from a disappointing result — but it is pinned here regardless.
- NYC, MIA and MDW are unaffected and may proceed.

**Strata.** Clearance bands, at minimum: `[0,1)`, `[1,2)`, `[2,3)`, `[3,5)`,
`[5,∞)` °F. Reported separately. A pooled figure alone is not acceptable — the
whole question is how the rate behaves near the boundary.

**Second, jointly-stratified statistic — adverse selection [R2].** `H(c,k)`
conditions only on city and clearance. It never conditions on realized price or
counterparty behaviour, so a seller who mispriced the trigger — offering 0.97
when the true settlement risk is higher — lands in exactly the same bucket as a
fairly-priced trade at the same clearance. `H(c,k)` is therefore **structurally
blind** to DOM-10, and revision 1 left adverse selection untested rather than
merely unaddressed.

Pre-register a second statistic:

    H2(c, k, q) = P( CLI_tmax(c,d) >= s | FIRE(c,d,s), stratum k, entry-price
                     decile q )

**Falsification test [R3].** Revision 2 declared "a monotone decreasing trend in
`H2` over the top three price deciles" a FAIL. That was not a statistic — it was
a shape, with no sample floor and no underpowered category, applied to cells
that cross-cut city × stratum × decile. Over ~14 days of tape most such cells
will hold a handful of trades or none, and "monotone decreasing" over near-empty
cells is noise dressed as a test. It could FAIL the gate on an artifact, which
is the same DOM-1 defect this document claims to have fixed for `H`. Replaced:

- **Power floor `N(c,k,q)` mirroring §7**, computed and recorded before any
  observed rate is read. A decile cell below its floor is **UNDERPOWERED**.
- **Minimum 30 trades per decile cell** before that cell may contribute at all.
- **Concrete test, replacing "monotone decreasing":** adverse selection is
  declared only where the 95% Wilson intervals of the top price decile and the
  median decile within the same `(c,k)` are **non-overlapping**, with the top
  decile lower. Overlapping intervals are **not** a FAIL and are **not** a PASS;
  they are UNDERPOWERED.
- If the top-decile cells in every in-scope `(c,k)` are UNDERPOWERED, DOM-10 is
  recorded as **UNTESTED** — explicitly not as "no adverse selection found".

## 5. Direction that must hold, and what falsifies it

**Required inequality.** For the bias to be conservative for this rule:

    H(c, k)  >=  BE(c, k)      for every city c and stratum k in scope

where `BE` is the **volume-weighted break-even** defined in §6.

**Falsified if:** `H(c,k)` sits below `BE(c,k)` in any in-scope city/stratum at
the 95% Wilson lower bound.

**MDW is flagged a priori as the most likely city to fail [R2].** Its mean
signed error is positive (+0.0527) and 56.37% of its non-zero days run METAR >
CLI — the direction that costs money — with a tail of three days at +7 °F or
worse. This is a **pre-declared prediction**, recorded before computation: if
MDW fails while the other in-scope cities pass, that is the expected result and
must NOT be reported as an incidental per-site exception, nor may MDW be dropped
after the fact to rescue a pooled verdict. If MDW instead *passes*, that is
evidence the one-sided statistic is measuring something other than what §3
describes, and demands explanation before any GO.

**Blanket falsification:** any evidence that CLI systematically reads **below**
METAR falsifies the conservatism claim outright, because that is the direction
that costs money. Per §3 this is **already observed at MDW**, so the conservatism
claim is at best site-specific and may not be asserted as a general property of
the estimator in any downstream document.

## 6. Threshold — and why it is not the market-implied baseline

**PASS threshold:** the Wilson **lower** bound on `H(c,k)` must exceed the
**volume-weighted break-even** implied by realized entry prices in that
stratum, plus a required-no-default minimum-edge floor.

**The market-implied baseline is explicitly rejected** (DOM-7): for a
deterministic tier the market-implied probability **IS the price paid**, so
"beats the market-implied baseline" is a tautology and cannot fail.

The minimum-edge floor exists because REQ-ALPHA-03's strict `>` would otherwise
permit trading at one basis point of edge (DOM-5). Its value is
required-no-default and must be set before computation, not after.

**Fee dependency, stated plainly:** break-even depends on the venue fee, and
`theta` in `fee = theta * C * p * (1-p)` is `[UNKNOWN]` — the schedule is
unresolved and `assert_fee_schedule_known` is fail-closed. Therefore `BE` must
be evaluated **across a theta sensitivity range**, and a PASS that holds only at
the optimistic end of that range is recorded as **CONDITIONAL on G-15**, not as
a PASS.

## 7. Sample floor, exclusions, and scope

**Sample floor (DOM-8) — non-circular restatement [R2].** Revision 1 defined the
floor as "whatever N makes the Wilson lower bound resolvable against BE", which
presupposes the target hit rate it is meant to size for. That is a description
of the acceptance criterion, not a pre-registered floor. Replaced with an
explicit power calculation, fixed now:

- **Assumed `p̂` for power purposes — derived from observation, not price
  [R3].** Revision 2 set `p̂ = 0.985` "because it is the entry region where the
  depth actually is". That substitutes *the price traders pay* for *the assumed
  true hit rate*, an equivalence that holds only if the market is calibrated —
  which is precisely the hypothesis DOM-10 disputes. It relocated revision 1's
  circularity rather than removing it. Replaced with two anchors, neither taken
  from price:

  **Primary anchor — observed one-sided concordance [prose corrected in R4].**
  From `settlement_alignment_diagnosis_2026-08-25.md` §1. The final column is
  **`P(METAR <= CLI)`** — the *safe-direction complement*, computed as
  `1 - (METAR>CLI days / city-days)`. It is **not** the exceedance fraction.
  Revision 3's prose described the exceedance fraction while the table and every
  downstream use carried the complement; an implementer following that prose
  literally would have computed the anchor backwards.

  | City | METAR > CLI days | City-days | One-sided concordance |
  |---|---:|---:|---:|
  | NYC | 3 | 1814 | 0.9983 |
  | MIA | 271 | 1813 | 0.8505 |
  | LAX | 342 | 1820 | 0.8121 |
  | SFO | 341 | 1799 | 0.8105 |
  | MDW | 367 | 1826 | 0.7990 |

  **Read this correctly.** These are UNCONDITIONAL over all city-days. They are
  **not** the gate statistic and **must not** be reported as an early answer:
  `H(c,k)` conditions on FIRE and on clearance stratum, and at wide clearance
  will be far higher. They are used here only to size samples without borrowing
  the market's own opinion.

  **What they nonetheless signal, stated now so it cannot be claimed as a
  surprise later:** four of five cities sit near 0.80–0.85 unconditionally,
  against a total failure budget of ~1–2% (DOM-4). The burden falls entirely on
  clearance stratification to close a gap of that size. If it does not, the gate
  fails — and that is the correct outcome.

  **Stratum-specific anchor `p̂_anchor(c,k)` [R4].** Revision 3 applied one
  whole-history figure per city identically to every clearance stratum. That is
  wrong in the dangerous direction: `[0,1)` is enriched for exactly the boundary
  cases that generate METAR > CLI errors, while `[5,∞)` is near-certain by
  physical continuity. Because the Wilson lower bound rises with `p̂`, a pooled
  anchor **overstates** the true rate at `[0,1)` and therefore **understates**
  the required `N(0,1)` — under-powering the one floor the document insists must
  not be gamed. Defined instead as:

  **Definition [R5] — this is the single source of truth. There is no other
  formula.** Let `c = concordance(c)` from the table above. Then:

  | Stratum `k` | `p̂_anchor(c,k)` | Rationale |
  |---|---|---|
  | `[0,1)` | `2c - 1` | boundary strata assumed to carry **twice** the city's pooled error rate |
  | `[1,2)` | `2c - 1` | same |
  | `[2,3)` | `c` | unadjusted |
  | `[3,5)` | `c` | unadjusted |
  | `[5,∞)` | `c` | unadjusted; may never carry a verdict alone (coverage rule below) |

  **[R6] The `2c - 1` form above is a FALLBACK, not the primary definition.** It
  doubles the assumed error rate by fiat. Round 5 showed that fiat is not
  harmless: at MDW it yields 0.598, and if `BE(c,k)` for the boundary stratum
  sits near the ~0.985 region where DOM-8 says the depth is, then **no finite
  `N` satisfies the floor** and the stratum is unreachable by arithmetic rather
  than by evidence.

  **Primary definition [R6, construction specified in R7] — measure the
  discount instead of guessing it.** The clearance-stratified error rate is
  derivable from the IEM archive (~1,800 city-days per site) **without tape,
  venue access or credentials**, because it is a property of METAR versus CLI
  alone.

  **It is NOT, however, computable by the existing script as it stands.**
  Revision 6 claimed it was "computable today ... from the same IEM archive
  already used by `scripts/analysis/settlement_alignment_study.py`". That claim
  is withdrawn. Verified against the script:

  - `build_threshold_cases` sets `threshold = metar_max.rounded_max_f - margin`
    — the city-day's **final** METAR max, a hindsight quantity — whereas §4
    conditions on the **intraday running max at Breezy's receipt time**. Same
    word, different conditioning variable. Substituting the final max would
    reintroduce exactly the look-ahead that DOM-2 exists to prevent.
  - `margin in (0, 1, 2, 3)` and `bucket_for_margin` emit only
    `0-1F / 1-2F / 2-3F / 3F+`. The `[3,5)` and `[5,∞)` bins of §4 **cannot be
    produced at all**.

  **Required extension, pre-declared as work [R7]** — this is a sub-task of
  G-03, not an assumed capability:

  1. Stratify on a **simulated running max**: for each city-day, replay the
     archive's timestamped observations in order and take the running maximum
     up to each simulated decision time, rather than the day's final max.
  2. **Receipt time does not exist in archive data, and LAG is inert unless a
     cutoff is modelled [R8].** The archive carries METAR *valid* times only, so
     receipt time is proxied as `t_receipt = t_valid + LAG`.

     **Revision 7 claimed LAG at the upper end of the 5-45 minute window made
     the anchor "conservative". That claim is WITHDRAWN — it was false.** `LAG`
     is a constant, uniform additive shift; a constant shift cannot change the
     relative order of observations. The construction in point 1 determines the
     crossing observation, its running-max value at crossing, the clearance
     stratum and the hit/miss classification **entirely from that ordered
     sequence**. The anchor is therefore numerically identical at LAG = 5
     minutes and LAG = 45 minutes. There was no safety margin; there was a no-op
     described as one.

     Pre-declared instead:

     **Resolved [R9]: the anchor construction models NO market-hours cutoff, for
     any city.** Revision 8 named market hours and the climate-day boundary as
     cutoffs that would make LAG load-bearing, then asserted DOM-9 was "a
     prerequisite input to this construction". Round 8 showed the four-step
     construction contains no truncation step at all, so nothing was actually
     gated — and that the two sentences disagreed about whether DOM-9 blocked
     the anchor. Both are withdrawn. The reasoning:

     - `p̂_anchor(c,k)` is a **power anchor, not the gate statistic** (stated
       above). It conditions on clearance, and deliberately not on FIRE, strike,
       market data or **tradeability**. Its only job is to size `N`.
     - Whether a crossing was *tradeable* is a property of the market, not of
       the METAR-versus-CLI relationship the anchor measures. Truncating the
       anchor by market hours would make it a different quantity, and a
       market-dependent one — reintroducing exactly the market dependence that
       makes the anchor a legitimate, non-circular power basis in the first
       place (round 6 confirmed this: "the anchor draws on a temporally disjoint
       historical archive ... that is standard, non-circular power-analysis
       practice").
     - Therefore **LAG is inert in the anchor, full stop.** Its value is not
       load-bearing, no conservatism may be claimed from it, and it is not
       pinned at any particular value. The 5-45 minute range is recorded as
       context only.
     - The **climate-day boundary** remains real and is handled at point 2b, not
       by LAG.

     **DOM-9 is reclassified [R9]** from an anchor-computability prerequisite to
     a **live-trading eligibility gate**, and is relocated to §4's `FIRE`
     predicate where it actually bites. It does **not** block anchor computation
     for any city, LAX and SFO included. The anchor is computable for all five
     cities once the point 1-4 extension is built.

     **Mandatory representativeness diagnostic [R10].** Separating the anchor
     from the gate statistic answered *circularity* but not
     *representativeness*. `H(c,k)` conditions on tradeability; the anchor does
     not. DOM-9 describes a *typical* window ("the daily max occurs 14:00-16:00
     local"), not a fixed one, and daily-max timing varies day to day — so for
     LAX/SFO the tradeability filter is plausibly a **partial, day-varying
     selection on crossing time**. If the tradeable subpopulation is
     systematically earlier-in-day than the archive's unconditional population,
     and if early-day crossings agree with CLI at a different rate than late-day
     ones, then the anchor **overstates** the true rate for the tradeable
     population, **understating `N(c,k)`** and silently under-powering `[0,1)`
     for exactly the two cities already flagged as fragile.

     This is not assumed either way. It is measured, using the simulated
     crossing timestamps that point 1's running-max construction already
     produces:

     1. For each city, partition simulated crossings by time of day into
        **early-window** (at or before the split point — the tradeable side) and
        **late-window** (after it) strata.

        **Split point [R11].** DOM-9 states a *daily-max timing* range
        (14:00-16:00 local), not a market-close range; revision 10 said "the
        earliest plausible market close under DOM-9's range" without saying
        which. Pre-declared: until DOM-9's actual close time is known, use
        **14:00 local** — the start of the daily-max window — as the split
        proxy, and **sweep** the split across 12:00-16:00 local in one-hour
        steps, reporting the diagnostic at every step. A conclusion that holds
        only at one split point is reported as split-sensitive, not as a
        conclusion. **The 14:00 result — not any sweep point — governs the
        binding `N(c,k)` [R12];** the sweep is mandatory transparency, never a
        menu from which a favourable split may be chosen. When DOM-9 resolves,
        re-run at the true close, which then governs.
     2. Compute the conditional METAR-vs-CLI agreement rate, with Wilson bounds,
        for each partition, per clearance stratum.
     3. **If the two partitions' Wilson intervals are non-overlapping in any
        `(c,k)`, the pooled anchor is population-mismatched for that cell.**
        Substitute the **EARLY-window** partition's anchor — that is the
        tradeable-matching one. **[R11 — direction corrected.]** Revision 10
        said "late-window", which inverted its own stated mechanism: DOM-9's
        concern is that the market **closes before** the 14:00-16:00 daily-max
        window, so the crossings that are unambiguously tradeable are the ones
        occurring **before** close — the early ones. Substituting the late-window
        anchor would have drawn from the population that is *least*
        representative of what the strategy can trade, precisely when the
        diagnostic fires, and left the direction of the resulting error on
        `N(c,k)` unknown rather than corrected.
        **If the early-window partition is itself thin [R12].** Revision 11 said
        "mark the cell Branch B and report it; do not fall back to the pooled
        anchor" — but Branch B is defined as `2c-1`/`c` where `c` is the
        **whole-city, unconditional** concordance from the §7 table. Routing a
        thin early partition to Branch B therefore *is* falling back to the
        pooled anchor: it mixes early and late crossings in exactly the
        proportion this diagnostic exists to distrust, and does so precisely
        when the diagnostic has already *proven* the two partitions differ. The
        instruction and its mechanism contradicted each other. Replaced with an
        explicit two-step rule:

        - **First, re-estimate the concordance on the early partition alone.**
          Define `c_early(city)` = the 95% Wilson lower bound of
          `1 - P(METAR_running_max > CLI_tmax)` computed over **early-window
          crossings only**. Where Branch B fires from this path, it consumes
          `c_early(city)`, never the pooled `c`. All other Branch B behaviour is
          unchanged.
        - **Second, if the early-window crossing count for that city is below
          the Branch A bar of 200 cases [R13 — comparand restated]**, emit **no
          numeric anchor at all** for that cell. Classify it
          `PROVISIONAL-UNDERPOWERED`: it carries no `N(c,k)`, contributes to no
          verdict, and is reported by name. A cell whose tradeable population
          cannot be estimated must produce an absent number, not a substituted
          one.

          **Forcing function [R13] — this state resolves, it does not sit.**
          Revision 12 made `PROVISIONAL-UNDERPOWERED` "exempt from
          expiry-to-NO-GO exactly as STRUCTURALLY UNREACHABLE is", but copied
          only the exemption, not the escalation that makes the exemption safe.
          STRUCTURALLY UNREACHABLE is exempt from the *clock* precisely because
          it substitutes an **immediate** evidence-based verdict for the timed
          one. `PROVISIONAL-UNDERPOWERED` had no such substitute, and its
          underlying population is the **fixed IEM archive** — which does not
          grow with tape capture — so a cell there today would still be there at
          day 42, permanently, blocking its city from ever leaving
          NOT YET ANSWERABLE. That is the DOM-1 hole reopened, and it would have
          fired on LAX/SFO's `[0,1)` strata, which this document predicts as the
          likely path.

          Pre-declared resolution:

          1. On first classification, report it immediately and name the cells.
          2. Attempt one re-derivation: widen the early-window definition by
             sweeping the split later within the 12:00-16:00 range **for anchor
             estimation only** — never for the binding `N(c,k)`, which remains
             governed by the 14:00 split — and record whether any split yields a
             sufficient early population. This is the only remedy available,
             because the archive is fixed.

             **Selection rule [R14].** Where more than one split clears the
             200-case bar, use the **first** split reaching it, moving
             monotonically later from 14:00. Stop there: do not continue
             sweeping past the first qualifying split, and **never select a
             later split on the ground that it yields a larger anchor.** A
             higher anchor lowers the required `N(c,k)`, so free choice among
             qualifying splits would be a selection surface — bounded (at most
             three candidates, one-time, archive-only, never touching the
             binding `N(c,k)` or the live `H(c,k)`), but pinned here regardless.
          3. **If no split yields a sufficient early population, the cell
             converts to a stated, evidence-labelled NO-GO** for that city.
             **[R14 — resolved at first classification, not at day 42.]** The
             42-day cadence exists for quantities that grow with tape capture.
             `c_early` draws only on the **fixed** IEM archive, so step 2's
             outcome is fully knowable at first classification and nothing
             changes between evaluations. Waiting out a clock that has nothing
             left to tell us is unmotivated delay, so the conversion happens
             **immediately on the failed re-derivation**. The NO-GO text: *"the tradeable population cannot be
             estimated from available archive data, therefore the falsification
             test cannot be run."* That NO-GO **counts** toward §7 rule 3's
             two-city programme-rejection tally.
          4. It may not be extended further without a new pre-registration and
             its own adversarial review.

          A verdict that cannot be reached is not a neutral outcome. Where the
          data cannot support the test, the answer is NO-GO, stated on that
          ground — not silence.

        This is the expected path for LAX/SFO's boundary strata — an early-in-day
        clearance before a 14:00-16:00 daily max is the less common event — so
        it must not silently resolve to a pooled figure.
     4. Until this diagnostic has been run, **`N(c,k)` for LAX and SFO is
        PROVISIONAL** and must be labelled as such in the feasibility table. NYC,
        MIA and MDW are unaffected where DOM-9 does not apply.

     The diagnostic needs no tape, no venue access and no DOM-9 resolution — it
     uses the archive alone, and sweeps the plausible close times rather than
     assuming one.

  2b. **Day-boundary assignment [R8].** State explicitly which timestamp assigns
     an observation to a climate day — valid time or proxied receipt time — and
     use it consistently. Practical risk is low (daily maxima rarely fall near
     midnight) but leaving it unstated is how a silent off-by-one day enters.
  3. Extend the margin loop and bucketing to the full five-bin scheme of §4,
     including `[3,5)` and `[5,∞)`.
  4. Reuse `wilson_lower_bound` (~line 206). Do not re-derive it.

  With that extension:

      p̂_anchor(c,k) = 1 - P( METAR_running_max > CLI_tmax | clearance stratum k )

  estimated per city and per stratum from the archive, using the **95% Wilson
  lower bound** of that conditional rate so the anchor is itself conservative.

  This is a **power anchor, not the gate statistic.** It conditions on clearance
  but not on FIRE, on strike, or on any market data, and it may not be reported
  as an early answer to §4's `H(c,k)`. Computing it is authorised as part of
  G-03 precisely because it touches no market data.

  **Anchor selection — two branches, not an ordered list [R7].** Revision 6
  wrote this as a three-option fallback triggered by "if a `(c,k)` cell is
  underpowered **in the archive**", whose first option was "the archive-derived
  stratified anchor" — the very source the branch premise declares unavailable.
  Option (2) is pure arithmetic on a whole-city constant and is therefore always
  available, so the list could only ever resolve to (2): the guessed discount,
  silently, with round 5's "4/5 cities unreachable by fiat" outcome and no
  surfaced flag. Replaced with an explicit two-branch rule:

  - **Branch A — archive cell has `>= 200` city-day-threshold cases.** Use the
    archive-derived stratified anchor. This is the primary path.
    **Why 200 [R8]:** this is an *archive-cell sufficiency* bar for estimating a
    power anchor, a different quantity from DOM-8's live-sample floor, which
    warns that ">= 200 settlements is under-powered above ~0.985 entries". The
    two are not in conflict, and the failure mode here is benign in a way the
    live floor's is not: the anchor is taken as a **Wilson lower bound**, so a
    thin cell drags `p̂_anchor` *down*, enlarging `N` — over-conservative, not
    silently dangerous. The bar is nonetheless a judgement, declared now rather
    than chosen later.
  - **Branch B — archive cell is below that count.** Use `2c - 1` for `[0,1)`
    and `[1,2)`, `c` otherwise, per the fallback table. **Branch B firing is
    itself a reportable condition**: it means a guessed discount is doing the
    work, and every cell on Branch B must be listed explicitly in the study
    output alongside its sample count.

  **STRUCTURALLY UNREACHABLE is not a third branch.** It is the outcome of the
  feasibility check below, applied to whichever anchor Branch A or B supplied.
  Record, for every cell: which branch fired, the sample count, the anchor
  value, and the feasibility classification. A study output that does not carry
  all four per cell is incomplete and may not be used for a verdict. Worked values, for the avoidance of any
  transcription ambiguity:

  | City | `c` | `2c - 1` (boundary strata) |
  |---|---:|---:|
  | NYC | 0.9983 | 0.9966 |
  | MIA | 0.8505 | 0.7010 |
  | LAX | 0.8121 | 0.6242 |
  | SFO | 0.8105 | 0.6210 |
  | MDW | 0.7990 | 0.5980 |

  Revision 4 additionally stated `p̂_anchor(c,k) = min(c, 1 - 2*(1-c) + 1)`.
  **That line is deleted.** Its second term simplifies to `2c`, so the whole
  expression reduced to `min(c, 2c) = c` for every observed concordance —
  a per-city constant with no stratum dependence at all, materially less
  conservative than the `2c-1` the bullets intended, and therefore silently
  under-powering `[0,1)`. It was dead algebra presented as the operative
  equation.

  If the observed per-stratum error structure later contradicts the 2x discount,
  that is reported as a finding — it may **not** be used to retroactively shrink
  a floor after the fact.

  **Sensitivity range [R5 — re-derived].** Revision 4 carried
  `p̂ ∈ {0.95, 0.98, 0.99, 0.995}`, an unrevised holdover from the discredited
  `0.985` regime that sat far ABOVE the concordance-derived anchors it was meant
  to stress-test — the boundary anchors run 0.598 to 0.9966. A stress range that
  never visits the region the anchor actually occupies tests nothing. Re-derived
  to span the anchor family:

      p̂ ∈ {0.60, 0.70, 0.80, 0.90, 0.95, 0.99}

  Mirroring §6's treatment of theta, the power calculation is ALSO run across
  this range and every resulting `N(c,k)` recorded alongside the anchor-derived
  floor. A floor satisfiable only at the optimistic end is reported as such, not
  as satisfied. Where the sensitivity range and the anchor disagree, the
  **larger N** governs.
- **Binding formula [R4].** The per-stratum floor `N(c,k)` is the smallest N for
  which the 95% Wilson lower bound at **`p̂_anchor(c,k)`** exceeds `BE(c,k)`
  evaluated at the **pessimistic** end of the theta sensitivity range. Compute
  and record every `N(c,k)` in the study output **before** reading any observed
  hit rate.

  **No literal `0.985` may appear anywhere in the computation.** It was
  revision 2's price-derived anchor and is discredited. **[R5 — claim
  corrected]** Revision 4 asserted it survived "only inside the review records
  of §10a and §10b"; that was inaccurate — it also appears in this section's own
  historical narrative above, and in §10. All such occurrences are narrative
  descriptions of why the anchor was removed, none is binding math, but the
  claim about their location is now stated correctly rather than approximately.

  `p̂_anchor(c,k)` is defined in the **"Definition [R5]"** table below, which is
  its only definition. (Revision 4 said "defined in the next bullet"; the next
  bullet was the UNDERPOWERED-reporting rule, so that pointer resolved to
  nothing.) Where any residual ambiguity remains, the **lower** — more
  conservative, larger-`N` — value governs.
- Strata below their floor are reported **UNDERPOWERED**, contribute to no
  verdict, and are **never pooled upward** to manufacture power.

- **Mandatory feasibility check, BEFORE any computation begins [R6].** The 95%
  Wilson lower bound at a fixed `p̂` converges to `p̂` **from below** and never
  exceeds it. Therefore if

      BE(c,k) >= p̂_anchor(c,k)

  then **no finite `N` satisfies the floor**: `N(c,k)` is undefined, not large.
  Revision 5 treated this case as ordinary UNDERPOWERED, which would have let
  four of five cities' boundary strata time out to NO-GO at 42 days without the
  falsification test ever having been computable — a programme-wide rejection
  "by arithmetic, not by evidence", which is the DOM-1 defect on its
  can-never-pass side.

  Pre-declared: evaluate `BE(c,k)` across its full theta sensitivity range
  against every `p̂_anchor(c,k)` **before** reading any observed rate, and
  classify each cell:

  | Condition | Classification | Consequence |
  |---|---|---|
  | `BE(c,k) < p̂_anchor(c,k)` across the whole theta range | **FEASIBLE** | compute `N(c,k)`, proceed |
  | `BE(c,k) < p̂_anchor(c,k)` only at the optimistic theta end | **THETA-CONTINGENT** | proceed, but the verdict is CONDITIONAL on G-15 fee discovery |
  | `BE(c,k) >= p̂_anchor(c,k)` across the whole theta range | **STRUCTURALLY UNREACHABLE** | see below |

- **STRUCTURALLY UNREACHABLE is a finding, not a timeout [R6].** It is
  explicitly distinct from UNDERPOWERED and **may not** be converted to NO-GO by
  the 42-day expiry clause, because more tape cannot fix it. It routes to
  mandatory escalation:

  1. Report it immediately and prominently, naming the cells affected.
  2. Re-derive `p̂_anchor(c,k)` from the archive-stratified primary definition if
     the fallback `2c-1` was what produced the unreachability — a guessed
     discount causing unreachability is a defect in the guess, not a finding
     about the world.
  3. If the **archive-derived** anchor is still below `BE(c,k)` across the theta
     range, that IS a substantive result and must be reported as such: **the
     rule cannot clear its own break-even at that stratum on measured
     historical data.** That is a legitimate NO-GO — but it is a NO-GO on
     evidence, stated plainly and immediately, never one arrived at by letting a
     clock run out.
  4. Escalation requires an adversarial re-review before any verdict is issued
     on the affected cells.

**Minimum coverage requirement [R2].** Large-clearance strata (`[5,∞)`) pass
close to trivially: once METAR has cleared a strike by 5 °F, CLI agreement
follows from physical continuity, not from any property of the rule. The strata
where the DOM-4 divergence modes actually bite — `[0,1)` and `[1,2)` — are, by
the floor above, the hardest to power at the prices where the depth exists.
Without a coverage rule the gate can therefore report GO while never evaluating
the boundary condition that motivated the entire exercise. That is structurally
analogous to the DOM-1 defect that killed the original gate.

**Pre-declared: the `[0,1)` stratum must reach a verdict — not UNDERPOWERED — in
every in-scope city.** If it does not, the overall determination is
**NOT YET ANSWERABLE**, which is distinct from and may not be reported as PASS.
A PASS carried entirely by wide-clearance strata is void.

**NOT YET ANSWERABLE expires [R3].** Revision 2 created this category with no
deadline, retry cap, or escalation path — letting the one stratum that motivated
the whole exercise sit in permanent limbo while the programme proceeded on other
grounds. That is the original DOM-1 non-falsifiability defect moved one layer
up: a verdict that can never be reached is a verdict that can never fail.
Pre-declared expiry:

- The determination may be re-run at most **twice** after the initial 14-day
  window, each after a further 14 days of capture (42 days of tape total).
- If the `[0,1)` stratum has still not reached a verdict in a given city at the
  end of the third evaluation, that city converts to **NO-GO**, not to a further
  extension.
- **[R4 — wording corrected]** Rule 3 fires at **two** or more cities at NO-GO,
  not three. Revision 3's expiry clause said "three or more", which was
  inconsistent with the rule it cited and could mislead a reader into treating
  two-NO-GO-plus-one-pending as safe. It is not: **two NO-GOs reject the
  formulation programme-wide**, whether they arrive at the initial evaluation or
  by expiry conversion.
- Extending beyond three evaluations requires a NEW pre-registration with its
  own adversarial review. It may not be granted by amending this document.

**Pre-declared exclusion — NYC.** KNYC's ~29 obs/day against ~306 at ASOS sites
is a sampling deficit of an order of magnitude, and NYC is ~99.6%
one-directional at every band. **NYC is EXCLUDED from the primary verdict** and
reported separately as a secondary, clearly-labelled result. Ground: the
estimator is materially different in kind, not merely noisier. Including it
would let a single degenerate site drive a pooled figure either way.

This exclusion is declared now, before computation, and may not be reversed
after seeing the result.

**Pre-declared review — MDW [R2].** MDW is **NOT excluded**, but is flagged for
mandatory separate scrutiny on directional-sign grounds (§3, §5), distinct from
NYC's sampling-density grounds. MDW stays in the primary verdict precisely so
that it can fail it. Removing MDW after seeing a failure is forbidden by this
document.

**Decision granularity — declared now [R3].** Revision 2 forbade dropping MDW
without ever stating whether the verdict is global or per-city, which made the
prohibition rhetorical: under a per-city rule, "keeping MDW in so it can fail"
produces the identical downstream outcome to dropping it, while letting the
document claim it dropped nothing. Discipline that changes no action is theatre.
Pre-declared:

1. **The trading determination is PER-CITY.** Each in-scope city receives its
   own GO / NO-GO. A NO-GO at MDW does not by itself bar the other cities.
2. **But the conservatism claim of §3 is PROGRAMME-WIDE and is already
   falsified.** No downstream document, requirement, or strategy may assert
   "METAR reads below CLI" as a general property of the estimator. Any component
   relying on that property must re-derive it per city.
3. **Programme-level NO-GO trigger:** if two or more of the five cities return
   NO-GO, the asymmetric formulation is rejected programme-wide, regardless of
   how many cities individually pass. Two independent site failures is evidence
   about the instrument, not about the sites.
4. **Headline reporting:** MDW's result appears in the headline determination
   whatever it is. A four-city pass may never be reported without MDW's number
   stated alongside it.
5. **Halt-and-unwind on later programme rejection [R4].** A city may reach GO at
   the initial 14-day evaluation while another city is still cycling through the
   42-day expiry window that could later trip rule 3. Revision 3 left the
   interaction unstated. Pre-declared: a programme-wide rejection **halts new
   position-taking in every city immediately**, including cities already live,
   and open positions are held to settlement rather than force-closed — closing
   early would realise a loss on a premise that has not been shown false for
   that city, while opening new ones would compound a premise now known to be
   false for the instrument. This rule binds regardless of how profitable the
   live cities appear at the time.

**Other pre-declared exclusions:** days with no CLI product; days where the
preliminary/final distinction is unresolved; days where the venue's named
station differs from the station Breezy ingested (DOM-4, station identity).

## 8. Required adversarial domain review

This pre-registration is **not** authorised for computation until an
independent domain reviewer, briefed to attack rather than approve it, answers
all of the following. **A bare APPROVE with no findings is treated as a failed
review, not a passed one.**

1. Is the asymmetric reformulation a legitimate correction of instrument
   choice, or a post-hoc rescue? Build the strongest case for "rescue",
   including the §2 sequencing admission.
2. Can the six **DOM-4 divergence modes** hide inside the one-sided statistic?
   Namely: C→F rounding at 1 °F granularity (31.1 C = 87.98 F — and the trigger
   lives exactly where the conversion decides); intraday METAR CORs revising a
   temperature **downward after Breezy has traded**; LST-vs-clock window; METAR
   group choice vs the CLI's ASOS 5-minute derivation; station identity vs the
   venue's named station; and the venue's CLI-vs-METAR tiebreak.
   The intraday-COR mode deserves particular attention: it is the one mode that
   is *not* conservative for an asymmetric rule, because it can retract a
   clearance after the position is open.
3. Does the KNYC deficit invalidate NYC entirely, or is §7's exclusion too
   generous — should other sites be scrutinised on the same ground?
4. **Adverse selection (DOM-10).** A 0.97 offer may exist precisely because the
   seller knows the trigger is wrong, meaning the strategy would preferentially
   trade exactly the markets where its own trigger is defective. Does `H(c,k)`
   detect this, or is it structurally blind to it? If blind, what additional
   pre-registered statistic would detect it — and should it be added here
   before review closes?
5. Is the §5 falsification condition genuinely capable of failing, or has it
   been drawn so that it cannot? Apply the DOM-1 test that killed the original
   gate: *is the measured quantity bounded away from failure by construction?*

## 9. Review status **[R4]**

- **Revision 1** — reviewed, verdict **BLOCK**. Findings in §10.
- **Revision 2** — re-reviewed, verdict **BLOCK**. Findings in §10a.
- **Revision 3** — re-reviewed, verdict **BLOCK**. Findings in §10b.
- **Revision 4** — re-reviewed, verdict **BLOCK**. Findings in §10c.
- **Revision 5** — re-reviewed, verdict **BLOCK**. Findings in §10d.
- **Revision 6** — re-reviewed, verdict **BLOCK**. Findings in §10e.
- **Revision 7** — re-reviewed, verdict **BLOCK**. Findings in §10f.
- **Revision 8** — re-reviewed, verdict **BLOCK**. Findings in §10g.
- **Revision 9** — re-reviewed, verdict **BLOCK**. Findings in §10h.
- **Revision 10** — re-reviewed, verdict **BLOCK**. Findings in §10i.
- **Revision 11** — re-reviewed, verdict **BLOCK**. Findings in §10j.
- **Revision 12** — re-reviewed, verdict **BLOCK**. Findings in §10k.
- **Revision 13** — re-reviewed, verdict **APPROVE-WITH-AMENDMENTS**. Findings
  in §10l.
- **Revision 14** — this document. Applies both advisory amendments. **G-17 is
  authorised on methodological grounds.**

Computation (G-17) remains **NOT AUTHORISED**. It additionally cannot begin
before G-16 (>=14 days of captured tape), which has not started.

## 10. Adversarial review record — revision 1 **[R2]**

Verdict: **BLOCK**. Findings, as returned:

- **[CRITICAL] §3's "conservative direction" claim is already falsified — MDW
  runs the wrong way.** Revision 1 asserted METAR-below-CLI as a universal
  mechanism while omitting the one site whose sign contradicts it: MDW is
  majority METAR > CLI (56.3%), mean signed error +0.0526. Combined with §2's
  admission that the reasoning was available pre-result but unacted-on, this
  "tips this from 'legitimate instrument correction' to rescue."
  **Independently verified by the coordinator against
  `settlement_alignment_diagnosis_2026-08-25.md` §1 — the finding is correct.**
  → Addressed in §3 (per-city signed table) and §5 (MDW flagged a priori).
- **[HIGH] Stratification structurally exiles the risk to UNDERPOWERED.** The
  informative near-boundary strata are the hardest to power, so the gate could
  report GO while never evaluating the boundary condition — "structurally
  analogous" to the DOM-1 defect that killed the original gate.
  → Addressed in §7 (minimum coverage requirement; NOT YET ANSWERABLE verdict).
- **[HIGH] `H(c,k)` is structurally blind to adverse selection.** It never
  conditions on realized price, so a mispriced 0.97 offer is indistinguishable
  from a fair one at the same clearance. DOM-10 was untested, not merely
  unaddressed. → Addressed in §4 (`H2` price-decile statistic and its
  monotonicity FAIL condition).
- **[MEDIUM] NYC exclusion correctly grounded but under-inclusive** — MDW needs
  its own exclusion review, on directional-sign rather than density grounds.
  → Addressed in §7.
- **[MEDIUM] Sample floor is circular.** → Addressed in §7 (assumed
  `p̂ = 0.985`, explicit power calculation) — **superseded**: that anchor was
  itself BLOCKed in round 2 and removed from the binding formula in R4. See
  §10a and §10b.
- **[MEDIUM] §6 theta-sensitivity handling is sound** — fail-closed,
  CONDITIONAL-not-PASS at the optimistic end. No finding.

Reviewer's ruling: "Step 3 (G-17 computation) is **not authorized** until the
MDW and stratification-coverage findings are addressed in an amended
pre-registration."

## 10a. Adversarial re-review record — revision 2 **[R3]**

Verdict: **BLOCK**. G-17 not authorised.

- **[CRITICAL, new defect introduced by revision 2] `H2` had no sample floor and
  no UNDERPOWERED fallback, unlike `H`.** Cross-cutting city × stratum × price
  decile over ~14 days leaves most target cells near-empty; "monotone
  decreasing" over near-empty cells "is not a statistical test, it's noise
  dressed as one — and it can FAIL the gate on an artifact. This is the same
  DOM-1 shape the document claims to have fixed for `H(c,k)`, reintroduced for
  `H2`." → Addressed in §4: power floor, 30-trade minimum per cell,
  non-overlapping-Wilson test replacing the shape claim, and an UNTESTED
  outcome for DOM-10.
- **[CRITICAL] `p̂ = 0.985` is justified by market price — the very thing DOM-10
  questions.** "It has only relocated the circularity: from 'presupposing the
  target hit rate' to 'presupposing price ≈ true probability'." → Addressed in
  §7: primary anchor derived from observed one-sided concordance in the
  diagnosis data (0.799–0.9983 per city), plus a `p̂` sensitivity range. The
  derived anchors are materially *worse* than 0.985 and that is recorded rather
  than smoothed.
- **[HIGH] MDW's forbidden-to-drop status may be rhetorical.** The document
  never stated whether the verdict is global or per-city; under a per-city rule
  the prohibition changes no downstream action — "discipline that changes no
  downstream action is theater." → Addressed in §7: per-city determination
  declared, plus a programme-wide rejection trigger at two city failures and a
  headline-reporting rule.
- **[HIGH] NOT YET ANSWERABLE has no expiry** — "the same non-falsifiability
  shape as the original DOM-1 defect, moved one layer up." → Addressed in §7:
  at most three evaluations over 42 days, then conversion to NO-GO.
- **§3 numbers — VERIFIED, no discrepancy.** All five cities' means and
  percentages cross-checked against the diagnosis source; every figure matches
  exactly. Genuinely closed.
- **Revision-1 findings 2 and 4 (stratification exile, NYC/MDW exclusion
  split)** — "genuinely addressed by §7's coverage rule and separate MDW-review
  clause; not cosmetic."

## 10b. Adversarial re-review record — revision 3 **[R4]**

Verdict: **BLOCK**. G-17 not authorised.

- **[CRITICAL] The `p̂` anchor was announced as replaced but the operative
  formula still hardcoded `0.985`.** "The prose above it is cosmetic; the math a
  G-17 implementer would actually run is unchanged from the version that was
  BLOCKed for circularity. This is exactly the 'paper-closed' pattern the
  charter asked me to hunt for — round 2's finding is **not** genuinely closed."
  → Addressed in §7: the binding formula now consumes `p̂_anchor(c,k)`, and the
  literal `0.985` is banned from the computation.
- **[CRITICAL] §7 table arithmetically correct, but its introducing prose was
  inverted.** The reviewer independently recomputed all five cities from the
  diagnosis source — NYC 0.99835, MIA 0.85052, LAX 0.81209, SFO 0.81045, MDW
  0.79901 — and confirmed **no numeric discrepancy**, but the sentence described
  the exceedance fraction while the table carried its complement. "A reader or
  implementer following the prose literally would compute the anchor backwards."
  → Addressed in §7: prose corrected to state `P(METAR <= CLI)` explicitly.
- **[HIGH] The anchor was unconditional across strata, biasing `[0,1)` toward
  under-power.** A pooled anchor overstates the rate at the boundary stratum;
  since the Wilson lower bound rises with `p̂`, that understates the required
  `N(0,1)` — "the same shape as the DOM-1/DOM-8 defects already fixed elsewhere,
  reintroduced here." → Addressed in §7: stratum-specific `p̂_anchor(c,k)` with
  a conservative 2x error discount on `[0,1)` and `[1,2)`.
- **[MEDIUM] Expiry clause misstated its own trigger** ("three or more" citing a
  rule that fires at two). → Corrected in §7.
- **[MEDIUM] Sequencing gap** between a per-city GO going live and a later
  programme-wide rejection. → Addressed in §7 rule 5: halt new position-taking
  everywhere, hold open positions to settlement.

Reviewer's answers to the charge questions, recorded:

- **Q1:** the `H2` floor and MDW-granularity fixes are real; the `p̂`
  circularity was **not** genuinely closed.
- **Q3:** non-circular with respect to price, but biased toward under-powering
  `[0,1)`.
- **Q4 (the consequential one):** the 0.80-0.85 unconditional concordance "is
  not by itself dispositive (it's dominated by zero-error, off-boundary days),
  but the document's claimed seriousness about it is undermined by the CRITICAL
  #1 bug, which means the actual computation ignores it."
- **Q5:** no infinite limbo, but a real live-trading/rejection sequencing gap.

## 10c. Adversarial re-review record — revision 4 **[R5]**

Verdict: **BLOCK** (fourth consecutive). G-17 not authorised.

- **[CRITICAL] `p̂_anchor(c,k)` was algebraically vacuous and contradicted its
  own bullets.** "Simplify the second term: `1 - 2*(1-c) + 1 = 2c`. So the
  formula reduces to `min(c, 2c)`. Since every observed concordance is in
  `(0.799, 0.9983)`, `2c > c` always, so this expression **always evaluates to
  `concordance(c)` — a single per-city constant, with zero stratum dependence,
  for every `k`**." The bullets below defined `2c-1` instead — e.g. MDW 0.598 vs
  the formula's 0.799 — "materially different anchors: the formula's value is
  less conservative, produces a smaller required `N(0,1)`, and reintroduces
  precisely the 'pooled anchor overstates the boundary rate, understates
  `N(0,1)`' defect that R4's own prose says it fixed." Compounded by a broken
  cross-reference: "`p̂_anchor(c,k)` is defined in the next bullet" pointed at
  the UNDERPOWERED-reporting bullet, "so the pointer resolves to nothing."
  Failure scenario given: an implementer transcribes the only line presented as
  an equation, silently under-powering the one stratum §7 insists must reach a
  verdict, "raising the odds of a false GO at the boundary where DOM-4's
  divergence modes actually bite." → Addressed in §7: dead line deleted,
  definition given as a table with worked per-city values, pointer corrected.
- **[MEDIUM, advisory] The claim about where `0.985` survives was inaccurate** —
  it also appears in §7's own narrative, not only in the review records.
  → Corrected in §7.
- **[MEDIUM, advisory] The sensitivity range was an unrevised holdover** sitting
  far above the concordance-derived anchors, "disconnected from the anchor
  family it's meant to stress-test." → Re-derived in §7 to
  `{0.60, 0.70, 0.80, 0.90, 0.95, 0.99}`.
- **Checked clean:** §3/§7 concordance table independently recomputed against
  the diagnosis source, exact match. §4/§7 coverage-expiry interaction "cannot
  produce a silent GO without `[0,1)` reaching a verdict." §5's falsification
  condition "is genuinely capable of failing (DOM-1 satisfied at the statistic
  level)." New §7 rule 5 and the corrected expiry trigger "are coherent
  additions with no new defect."

## 10d. Adversarial re-review record — revision 5 **[R6]**

Verdict: **BLOCK** (fifth consecutive). G-17 not authorised.

**Confirmed closed by round 5's own verification** — recorded because these took
four rounds to get right:

- The concordance table recomputes exactly against the diagnosis source (all
  five cities), and `2c-1` recomputes exactly (0.9966 / 0.7010 / 0.6242 /
  0.6210 / 0.5980).
- "The dead `min(c, 1-2*(1-c)+1)` line is deleted and clearly marked historical;
  the table in 'Definition [R5]' is now the sole, unambiguous, internally-
  consistent source... **No fourth paper-close instance (prose contradicting
  live math) exists in revision 5** — this specific hunt comes back clean, and
  that is a genuine, verified fix."
- §10c "is an accurate, unsoftened record of round 4's findings."

**[CRITICAL, introduced by R5] `N(c,k)` can be mathematically undefined, not
merely large.** "The Wilson lower bound at a fixed `p̂` **converges to `p̂` from
below** as N→∞ and never exceeds it. If `BE(c,k) > p̂_anchor(c,k)`, **no finite N
satisfies the inequality — `N(c,k)` does not exist**, not 'is large'." DOM-8
records that depth concentrates above ~0.985 entries, so plausible break-evens
sit well above the discounted anchors of 0.598-0.701 for MDW/LAX/SFO/MIA. Those
four cities' boundary strata would then be "permanently UNDERPOWERED by
construction, independent of how much tape is captured", and the expiry clause
would "silently convert them to NO-GO at 42 days without ever computing the real
falsification test on live data." Combined with rule 3, that makes programme-wide
NO-GO "close to certain **by arithmetic, not by evidence** — the same DOM-1 shape
the document claims to have closed, now on the 'can never pass' side." The
"larger N governs" rule does not rescue it: "comparing two potentially-infinite
quantities and taking the max is still infinite."

→ Addressed in §7 twice over: (a) the guessed 2x discount is demoted to a
fallback and replaced by an **archive-derived, clearance-stratified** anchor
computable today without tape or venue access; (b) a mandatory pre-computation
feasibility check classifies every cell FEASIBLE / THETA-CONTINGENT /
STRUCTURALLY UNREACHABLE, and the last is a reportable finding with mandatory
escalation, explicitly exempt from expiry-to-NO-GO.

Round 5's judgement on the discount, recorded verbatim because it drove the fix:
"The `2c-1` discount is directionally conservative but **not necessarily
correctly calibrated** — its magnitude, combined with plausible break-evens,
likely makes `[0,1)` structurally unreachable for 4/5 cities. This is the
badly-calibrated-discount outcome, not the honest-answer outcome, because the
document never even tests for it."

## 10e. Adversarial re-review record — revision 6 **[R7]**

Verdict: **BLOCK** (sixth consecutive). G-17 not authorised.

**Confirmed genuinely closed by round 6:** "The Wilson-converges-from-below
CRITICAL is substantively addressed: the mandatory pre-computation feasibility
table ... makes a NO-GO reachable *on measured archive evidence* rather than by
construction from an arbitrary fiat discount, and STRUCTURALLY UNREACHABLE is
correctly exempted from silent 42-day expiry. §10d is a faithful, unsoftened
record of round 5." On circularity: "the anchor draws on a temporally disjoint
historical archive, not the live tape `H(c,k)` will use — that is standard,
non-circular power-analysis practice, not DOM-8's defect."

**[CRITICAL] The archive anchor's "clearance" did not match `H(c,k)`'s
"clearance", and the cited script cannot produce the strata as specified.**
§4 conditions on the intraday running max at receipt (`t_cross`), the DOM-2
discipline. But `build_threshold_cases` constructs synthetic thresholds as
`metar_max.rounded_max_f - margin`, "using the city-day's **final** METAR max
(known only in hindsight), not the running max at any real decision time. That
is a different conditioning variable wearing the same name." And its buckets
"cannot produce the document's five-bin scheme — nothing distinguishes `[3,5)`
from `[5,∞)`, and margin never exceeds 3." Conclusion: "'Computable today from
the same archive' is true of the raw data; false, as written, of the specific
stratification and script cited."
**Coordinator independently verified both halves against the script before
amending** — `threshold = metar_max.rounded_max_f - margin` at the daily-max
level, and `for margin in (0, 1, 2, 3)` with
`bucket_for_margin` emitting only `0-1F / 1-2F / 2-3F / 3F+`. The finding is
correct. → Addressed in §7: the "computable today" claim is **withdrawn**, the
running-max construction is specified, the absent receipt time is handled by a
pre-declared conservative 45-minute lag proxy with its bias direction stated,
and the script extension is pre-declared as G-03 work rather than assumed.

**[HIGH] The archive-underpowered fallback ordering was self-contradictory and
could never reach STRUCTURALLY UNREACHABLE by that path.** The branch premise
declared the archive unavailable while listing the archive anchor as its first
option; the arithmetic fallback "is therefore *always* available", so "the
ordering as written can never select (1) in this branch and can never reach (3):
it always resolves to (2), silently reintroducing the guessed discount — and
round 5's exact '4/5 cities unreachable by fiat' outcome — for every clearance
stratum where the archive itself is thin ... with no surfaced flag that this
happened." → Addressed in §7: replaced with an explicit two-branch rule at a
declared sample threshold, Branch B firing made a reportable condition, and
STRUCTURALLY UNREACHABLE correctly re-sited as an outcome of the feasibility
check rather than a third branch.

## 10f. Adversarial re-review record — revision 7 **[R8]**

Verdict: **BLOCK** (seventh consecutive). G-17 not authorised.

**Round 6's two findings confirmed genuinely closed.** On the withdrawn
"computable today" claim: "this is not a paper-close, it is an honest retreat to
'not yet built, here is the spec.'" On the fallback: the two-branch rule "can
actually reach Branch A and can actually reach STRUCTURALLY UNREACHABLE — the
self-contradiction that made round 6 always resolve to the guessed discount is
gone."

**[CRITICAL, introduced by R7] The 45-minute LAG proxy's conservatism claim was
unfounded.** "`t_receipt = t_valid + LAG` is a **constant, uniform** additive
shift applied to every observation's valid time. A constant shift cannot change
the *relative order* of observations." Since the specified construction derives
the crossing observation, its running-max value, the clearance stratum and the
hit/miss classification purely from that ordered sequence, "**the computed
anchor is numerically identical whether LAG is 5 minutes or 45 minutes**, absent
some unstated external real-clock cutoff (market close, day boundary) that the
document does not say is modeled anywhere in this construction." The claim was
therefore "either (a) a no-op dressed as a safety margin, or (b) if some
unstated cutoff *does* interact with it, a directional claim whose sign is
actually unknown and could run the dangerous way (LAG pushing late-day
observations past a market-hours or day-boundary cutoff — DOM-9's market-hours
question is exactly adjacent here and is never connected to this
construction)."

The reviewer's framing, recorded because it is the point: "This is precisely the
failure mode this document's own convergence discipline was built to catch — an
unverified conservatism claim locked in and forbidden to be re-derived downward
'after seeing a failing result'. Every prior guessed-discount BLOCK (rounds 5
and 6) was exactly this shape."

→ Addressed in §7 point 2 by taking option (b): the conservatism claim is
**withdrawn**, LAG is declared inert where no absolute cutoff is modelled, the
two cutoffs that would make it load-bearing are named (market hours, climate-day
boundary), the direction of its effect is explicitly NOT assumed conservative
where a cutoff is modelled, and DOM-9 is declared a prerequisite input rather
than an adjacent finding.

**Advisory, both addressed:** the Branch A `>=200` bar now carries a one-line
justification distinguishing it from DOM-8's live-sample floor and noting the
Wilson-lower-bound framing makes thin cells over-conservative rather than
dangerous; day-boundary assignment is now required to be stated explicitly
(§7 point 2b).

§10d and §10e confirmed faithful and unsoftened.

## 10g. Adversarial re-review record — revision 8 **[R9]**

Verdict: **BLOCK** (eighth consecutive). G-17 not authorised.

**Round 7's finding confirmed genuinely closed**, and both round-7 advisories
confirmed addressed "with no new defect". §10e and §10f confirmed "verbatim,
unsoftened records".

**[CRITICAL, introduced by R8] The DOM-9 "prerequisite" claim was not enforced
by the construction it claimed to gate.** The four-step construction that
actually produces `p̂_anchor(c,k)` "contains **no market-hours truncation step
anywhere**", and `FIRE` was likewise defined without one — "so read literally,
no cutoff is ever modelled by this construction, for any city — which means, by
the document's own second sentence ... nothing is actually gated". Meanwhile the
first sentence claimed DOM-9 gated "this construction" outright. "Those two
sentences disagree, and the document never resolves which governs. This is
precisely round 7's shape recurring one clause later."

The reviewer laid out the fork exactly: if a market-hours cutoff *should* be in
the anchor, "the construction as specified is silently wrong for LAX/SFO, not
merely blocked"; if it should *not* be — "because the anchor is explicitly 'a
power anchor, not the gate statistic', conditioning on clearance but not on
tradeability" — then the prerequisite sentence "is overclaiming a dependency
that doesn't exist and should be deleted."

Also noted: the feasibility machinery "presuppose[s] `p̂_anchor(c,k)` already
exists; there is no fourth state for 'anchor construction itself
unspecified/blocked pending DOM-9'", which under the prerequisite reading would
have reintroduced "the exact 'verdict that can silently time out without ever
being computed' shape that rounds 5 and 6 closed."

→ Addressed by taking the second fork, which is correct on the merits: §7 now
states plainly that the anchor models no cutoff for any city, LAG is inert
**full stop**, and the prerequisite sentence is deleted. DOM-9 is relocated to
§4's `FIRE` predicate, where it is a real blocking dependency on the *gate
statistic* for LAX/SFO — with a new OUT-OF-SCOPE-DOM-9 classification, distinct
from NO-GO and excluded from the rule-3 failure count, because a city that
cannot be traded is not evidence about the instrument. No fourth feasibility
state is needed, because anchor computation is no longer blocked for anyone.

## 10h. Adversarial re-review record — revision 9 **[R10]**

Verdict: **BLOCK** (ninth consecutive). G-17 not authorised.

**Round 8's contradiction confirmed genuinely closed.** "§4's `FIRE` now carries
the tradeability conjunct explicitly ... §7 states plainly 'the anchor
construction models NO market-hours cutoff, for any city,' and the two
previously-contradictory sentences are gone — replaced by a coherent,
consistently-applied division: DOM-9 gates `H(c,k)` for LAX/SFO but never gates
`p̂_anchor`. That fork is implemented cleanly and I find no residual
self-contradiction anywhere it is referenced."

**[CRITICAL, introduced by R9] The anchor's population no longer matches the
population `H(c,k)` measures, for the two cities DOM-9 exists to protect.** The
anchor is computed "over **all** simulated crossings, with no time-of-day
filter", and revision 9's defence — that truncating it would reintroduce market
dependence — "answers *circularity*, not *representativeness*." DOM-9's text
"describes a typical window, not a fixed one — daily-max timing varies day to
day ... so for LAX/SFO the tradeability filter is plausibly a **partial**,
day-varying selection on crossing time, not a clean binary." Consequence: the
anchor "overstates the true rate for the actual tradeable LAX/SFO population,
understating `N(c,k)` and silently under-powering the `[0,1)` stratum for
exactly the two cities already flagged as fragile — the same 'conditioning
variable wearing the same name' shape that BLOCKed round 6, and the same
'load-bearing assumption asserted rather than tested' shape that BLOCKed
round 5."

→ Addressed in §7 by taking the reviewer's option (a), the empirical one: a
mandatory representativeness diagnostic partitions simulated crossings by time
of day, compares conditional agreement rates with Wilson bounds per stratum,
substitutes the tradeable-matching partition's anchor where the intervals are
non-overlapping, and marks LAX/SFO's `N(c,k)` PROVISIONAL until it has run. It
needs no tape, no venue access and no DOM-9 resolution.

**[MEDIUM, advisory] "Untradeable at the relevant hours" was not defined
precisely enough** to distinguish whole-city OUT-OF-SCOPE from a partial-overlap
city that should get a reduced-sample in-scope `H(c,k)`. The reviewer noted this
"doesn't create a MDW-style gaming risk (the trigger is an objective venue fact,
not an observed result, so it can't be reverse-engineered from a bad hit rate)"
but should be pinned before implementation. → Addressed in §4 with a concrete
10% / 90% criterion.

**Confirmed sound and not outcome-dependent:** §7 coverage/expiry interaction,
§5's DOM-1 falsifiability test, §6's fee-sensitivity handling, and the
OUT-OF-SCOPE-DOM-9 vs rule-3 exclusion logic. §10f and §10g confirmed faithful
and unsoftened.

## 10i. Adversarial re-review record — revision 10 **[R11]**

Verdict: **BLOCK** (tenth consecutive). G-17 not authorised on methodological
grounds, separately from its unconditional block on G-16.

**[CRITICAL, introduced by R10] The representativeness-diagnostic substitution
rule pointed at the wrong partition** — "the exact failure shape this document
has been BLOCKed for nine times, now inside the fix for round 9's finding."

The passage states the mechanism correctly — "the anchor overstates the true
rate for the tradeable population" when "the tradeable subpopulation is
systematically **earlier-in-day**" — which "follows directly from DOM-9: the
market closes before the 14:00-16:00 daily-max window, so only crossings
occurring **before** close are tradeable — the tradeable subpopulation is the
**early** one by construction." The operative rule then said to "use the
**late-window** — i.e. the tradeable-subset-matching — partition's anchor",
which "inverts the document's own stated logic."

Failure scenario recorded verbatim: "exactly when the diagnostic fires ... an
implementer following this text substitutes the anchor from the population that
is *not* representative of the tradeable subset, believing the mismatch is
fixed. The direction of the resulting error on `N(c,k)` is now unknown rather
than corrected, which is worse than the PROVISIONAL flag the document intends:
it produces false confidence that a control has run, not merely a missing
control."

→ Corrected in §7: the substitution now selects the EARLY-window partition, with
the reasoning stated inline so the direction cannot drift again, and a thin
early partition falls to Branch B rather than back to the pooled anchor.

**[MEDIUM, advisory] The split point was underspecified** — DOM-9 gives a
daily-max timing range, not a market-close range. → Addressed in §7: 14:00 local
pre-declared as the proxy, with a mandatory 12:00-16:00 sweep and
split-sensitivity reporting.

**Confirmed sound:** the 10%/90% criterion "correctly falls through to the
existing §7 floor/coverage machinery with no new interaction defect"; the DOM-1
test still passes at the whole-gate level, "unaffected by this finding, which is
local to the LAX/SFO anchor-substitution mechanism"; §10g and §10h are
"unsoftened, accurate records".

**On the process itself**, recorded because it is the reason this loop continues:
"the repeated-BLOCK process is working as designed — it is catching a real
defect each round, including this one — but it has not yet produced a document
free of the 'prose states the property, mechanism does the opposite' defect it
exists to hunt. That is not a process failure; it is evidence the process should
keep running rather than stop at a round number."

## 10j. Adversarial re-review record — revision 11 **[R12]**

Verdict: **BLOCK** (eleventh consecutive). G-17 not authorised on methodological
grounds.

**Round 10's finding confirmed genuinely closed:** "The early/late direction now
matches the mechanism paragraph above it and point 1's own early=tradeable
definition; internally consistent."

**[CRITICAL, introduced by R11] "Do not fall back to the pooled anchor" was
contradicted by the mechanism it named.** Branch B "is defined as: use
`2c-1`/`c`, where `c = concordance(c)` is the **whole-city, unconditional**
figure ... No partition-specific `c` is defined anywhere in the document ... So
when a thin early-window partition fires 'Branch B,' the number an implementer
actually plugs in is the pooled, whole-archive `c` — mixing early and late
crossings in exactly the proportion the representativeness diagnostic exists to
distrust."

Failure scenario recorded: "This is the expected path for LAX/SFO's boundary
strata — a genuine early-in-day clearance of the strike before a 14:00-16:00
window daily max is the less common event, so the early-window `[0,1)`/`[1,2)`
cells are plausibly thin exactly where the diagnostic already found the two
partitions' intervals non-overlapping (i.e., where the mismatch is proven, not
merely suspected). At that moment the document instructs falling to a
computation that is substantively 'the pooled anchor' while its own sentence
says the opposite — reproducing round 9's population-mismatch defect silently,
dressed in different terminology."

→ Addressed in §7 by taking both of the reviewer's options rather than one:
`c_early(city)` is defined as a partition-specific Wilson lower bound that
Branch B consumes when it fires from this path, and if `c_early` is itself below
the Branch A bar the cell emits **no numeric anchor at all**, classified
`PROVISIONAL-UNDERPOWERED` and exempt from expiry exactly as STRUCTURALLY
UNREACHABLE is.

**Confirmed sound by round 11:** the 12:00-16:00 sweep introduces no
multiple-comparisons surface — "14:00 is pre-declared as the operative split;
the sweep is mandatory full-reporting diagnostic transparency, not a 'pick the
favorable split' mechanism — no p-hacking surface introduced." Its minor
advisory, that the document should say explicitly that the 14:00 result governs
the binding `N(c,k)`, is now stated. DOM-1 still satisfied at the whole-gate
level. §10h and §10i confirmed "accurate, unsoftened", cross-checked against
DOM-9's verbatim wording. On whole-document structure: "none beyond Finding 1 —
no new whole-document defect found."

## 10k. Adversarial re-review record — revision 12 **[R13]**

Verdict: **BLOCK** (twelfth consecutive). G-17 not authorised on methodological
grounds.

**Round 11's finding confirmed genuinely closed:** `c_early(city)` "is
well-defined ... and is computable from data the representativeness diagnostic
already produces: nothing beyond the early/late partition of simulated crossings
is needed. Branch B, when it fires from a thin early partition, now consumes
`c_early`, never pooled `c` — the population-mismatch contradiction round 11
found is gone, and the reasoning is stated inline so it can't drift again."

**[CRITICAL, introduced by R12] `PROVISIONAL-UNDERPOWERED` had no resolution
path — the DOM-1 hole reopened, narrower but real.** STRUCTURALLY UNREACHABLE's
exemption from the 42-day clock "is paired with a mandatory escalation ... It
never sits in limbo — it substitutes an immediate, evidence-based verdict for
the timed one. `PROVISIONAL-UNDERPOWERED` copies the exemption but not the
escalation." And critically: "Since `c_early`'s underlying population is the
fixed IEM archive (not growing with G-16 tape), a cell that is
`PROVISIONAL-UNDERPOWERED` today will be `PROVISIONAL-UNDERPOWERED` at day 14,
28, and 42 — permanently."

Consequence: because `[0,1)` must reach a verdict before a city can leave
NOT YET ANSWERABLE, "LAX and/or SFO can be stuck in `NOT YET ANSWERABLE`
indefinitely, contributing to neither a GO nor a NO-GO, and never counted in
rule 3's failure tally either. This directly fails the DOM-1 test for those
cities: the gate cannot return GO *or* NO-GO on them." The reviewer's path count:
"Five states, three that resolve cleanly ..., one that resolves via forced
escalation ..., and one — `PROVISIONAL-UNDERPOWERED` — that does not resolve at
all."

→ Addressed in §7: the state now carries a mandatory forcing function —
immediate report, one bounded re-derivation attempt by sweeping the split for
anchor estimation only, then conversion at the third evaluation to a stated
evidence-labelled NO-GO that **counts** toward rule 3.

**Advisory, addressed:** "below the Branch A sample bar" now restates the
comparand explicitly (early-window crossing count against the 200-case bar).

**Confirmed by round 12:** §10i and §10j "faithful, unsoftened records"; the
end-to-end trace "shows no other instance of the 'prose promises a property the
mechanism doesn't deliver' pattern this round — the one instance found is the
escalation gap above"; and "everything else in the document is now sound."

## 10l. Adversarial re-review record — revision 13 **[R14]**

Verdict: **APPROVE-WITH-AMENDMENTS**. First non-BLOCK verdict in the sequence.
**G-17 computation authorised on methodological grounds**, subject to two
advisory amendments, both applied in revision 14. Separately and
unconditionally still blocked on G-16 (tape capture), which the reviewer
explicitly notes "is not a methodological objection".

**Round 12's finding confirmed genuinely closed**, with the path count re-run
independently: "Every branch now terminates in a verdict or a properly-excluded
OUT-OF-SCOPE-DOM-9 classification ... I find no remaining path by which a cell
avoids ever producing a verdict."

**[MEDIUM, advisory — applied in R14] The bounded re-derivation had a tie-break
gap.** The document "specifies the **failure** path exhaustively ... but is
silent on the **success** path: if multiple splits between 15:00-16:00 clear the
sufficiency bar with materially different `c_early` values, nothing pins which
one governs." Since a higher anchor lowers the required floor, that was "a
selection-effect surface, though bounded ... it cannot manufacture a false GO on
live data — it only affects how much live evidence is required."
→ Applied: first qualifying split moving monotonically later from 14:00 governs.

**[LOW, advisory — applied in R14] The 42-day deadline was unexplained slack.**
"`c_early`'s re-derivation draws only on the fixed IEM archive ... That means the
outcome of step 2 is knowable at the moment of first classification — yet step 3
defers the NO-GO conversion to 'the third evaluation' (day 42) ... Nothing
changes between evaluations for this state."
→ Applied: conversion happens immediately on the failed re-derivation.

**Independently re-verified by the reviewer:** all five cities' concordance and
signed-error figures "match exactly" against
`settlement_alignment_diagnosis_2026-08-25.md` §1; `wilson_lower_bound` at line
206 and `build_threshold_cases` margins `(0,1,2,3)` at line 313 in
`settlement_alignment_study.py`, "confirming the still-unbuilt-extension
characterization remains accurate". No new instance of the "prose promises a
property the mechanism doesn't deliver" pattern. DOM-1 satisfied per city
including LAX/SFO. §10j and §10k faithful and unsoftened.

## 11. GREEN criterion for backlog item G-03

This document written, adversarially reviewed, and the verdict recorded
verbatim with its findings.

**Computing the statistic is explicitly NOT part of G-03.** It belongs to G-17
and requires ≥14 days of captured tape. Computing it here would defeat this
document's entire purpose.

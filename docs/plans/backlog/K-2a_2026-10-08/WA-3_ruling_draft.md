# RULING_K-2a_WA-3_classes_alpha_corpus (DRAFT)

**Status:** DRAFT, not issued. Once converged it will be issued as `docs/evidence/RULING_K-2a_WA-3_classes_alpha_corpus_<date>.md`.
- Drafted by prediction-market-reviewer.
- Pending: architect review (WA-4 interplay, F1, F2), then prediction-market-reviewer co-sign.

**Authority:**
- K-2a plan r2 §5 and §7 WA-3, governed by B2, B4, N5 and R4.
- RA-13 §5/§7.
- RULING_R3-VIABILITY §3.3.

**Desk-only:**
- No outcome-derived number.
- No file touched: no PREREG.json, ledger file, `src/`, `scripts/`, `tests/` or `deploy/`.
- The operator caps are not named.
- FQ-v2 NO-TRADE is in force.

## Coordinator note on F1 (provisional resolution, for architect ruling)
F1 shows a conflict in B2 as written.
- **If Kalshi slots are reserved now,** PM.us look-taking intake closes. That contradicts B-8 ("K-2a never displaces PM.us work").
- **If they are not reserved,** the K constants become a dead letter.

**Provisional resolution:**
- WA-3 freezes the *procedure* and records today's values as informational only.
- The binding freeze of PROGRAMME_ALPHA_K / RE_ARM_GATING_PROGRAMME_ALPHA_K happens at **WB-7b**, read from the PM.us ledger as it stands then.
- No Kalshi reservation exists before K-2b start.
- Rationale: K-2b starts only on programme KILL. After KILL, PM.us look-taking intake is itself closed, so freezing at WB-7b loses nothing and displaces nothing.
- R4 is evaluated at WB-7b, as the draft already says.

The architect is to confirm or replace this.

## 1. Kalshi class table
| Class | Definition | Entry condition (all required) |
|---|---|---|
| KC-1 | NBP-HIGH D+1 taker; YES and NO legs; `MEAN_EXCESS_PER_TAKE` | Stage-0 ADMITTED series (Wilson lower > 0.99, TWC-era), θ_K sourced (§7), Kalshi S2' per-station pass under Holm, WB-7 SEARCH bound and n_K feasible (otherwise a zero-look record), and the WB-7a loss floor passes FQ-v2 §4.6 (§8) |
| KC-2 | NBP-LOW (separate model) | A LOW model exists and passes its own S2'. Stage 0 LOW is evaluated separately. Same θ_K, power and α rules as KC-1 |
| KC-3 | Reserve maker | A verified Kalshi maker fee (vendor docs plus series fee fields). Until then it is an unregistered reserve slot |

- MAX_HYPOTHESES_K = 3, one slot per class. The 1/3 slot split IS the Bonferroni split across classes; there is no further layer on top of it (P7).
- Zero-look records consume no slot (mirrors `hypothesis_ledger.py:815-824`).
- HIGH and LOW are separate hypotheses. The YES and NO legs are variants of KC-1.

## 2. MAX_VARIANTS_K = 4 (confirmed)
- It mirrors PM.us `MAX_VARIANTS_PER_HYPOTHESIS = 4` (`:183`).
- Allocation divides by the *actual* k (KC-1 k=2; KC-2 and KC-3 k=1), so the ceiling only sets the asserted floor.
- It can change only by a successor ruling (L-12).

## 3. α accounting (B2), with values read 2026-10-08 (informational under the F1 note)
**Source:** the PM.us ledger `~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl` (path from `scripts/analysis/hypothesis_register.py:265`; 4 lines; mtime 2026-09-28 18:22). Its constants are PROGRAMME_ALPHA 0.05 (`:177`), RE_ARM 0.025 (`:158`) and MAX_HYPOTHESES 4 (`:181`).

| hypothesis_id | schema | status | zero_look | allocated_alpha | re_arm_gating |
|---|---|---|---|---|---|
| H-ARCHIVE-RECAL-2026-09 | 1 | UNDERPOWERED_NOT_REGISTERED | true | 0.0 | None |
| H-FORECAST-TAKER-RUNG-SCREEN-2026-09-20 | 1 | REJECTED | true | 0.0 | None |
| H-NO-SIDE-2026-09 | 1 | UNDERPOWERED_NOT_REGISTERED | true | 0.0 | None |
| H-OFFWINDOW-T4-2026-09 | 1 | UNDERPOWERED_NOT_REGISTERED | true | 0.0 | None |

**Totals.**
- Σ PM.us look-taking allocated_alpha = 0, and Σ re-arm-gating = 0.
- PM.us remaining = 4 slots.

**Derived K values as of today.**
- PROGRAMME_ALPHA_K = 0.05.
- RE_ARM_GATING_PROGRAMME_ALPHA_K = 0.025.
- allocated_alpha_K per look-taking record = 0.05/3 = 1/60.
- R4_WORST_CASE_K_FLOOR = 0.05/4/4 = 0.003125 (the 1/240 label is withdrawn; P2).

**Combined-budget test (Kalshi side).** It reads both ledgers. It refuses if combined look-taking allocated_alpha > 0.05, or if combined re-arm-gating alpha > 0.025. The comparison is exact with no tolerance. PM.us is read only through `read_hypothesis_ledger`.

**Narrowing rule for later PM.us registrations.**
- Each carries `programme_alpha_override = o` (`:899`, `:961-968`: narrow only, 0 < o ≤ 0.05).
- `Σpm_alloc + o/4 + K_reserved ≤ 0.05` must hold. K_reserved is zero before K-2b start, under the F1 note.
- A re-arm-gating registration additionally needs o ≤ 0.025 and must pass the combined re-arm test.

**F1 (HIGH).** See the coordinator note above.

**F2 (MEDIUM).** R4 tests only PROGRAMME_ALPHA_K.
- A re-arm-gating KC record would allocate 0.025/3/4 = 0.0020833 per variant, which is below the 0.003125 floor. PM.us itself would sit at 0.0015625.
- No code enforces such a floor today.
- Proposed reading: R4's per-variant floor applies to the look-taking budget only. Re-arm-gating records need a stated power check at their own α.
- The architect is to confirm.

## 4. R4 check (informational now; binding at WB-7b)
- PROGRAMME_ALPHA_K = 0.05 > 0, and it is ≥ 3 × 4 × 0.003125 = 0.0375 (headroom 0.0125), so no zero-look is triggered.
- The check re-fires at WB-7b. If the value is ≤ 0.0375 then, write a zero-look record and go to N-2.

## 5. WA-4 interplay (architect)
- The pin and D6(i) widenings stand as specified in B3/R2.
- `HypothesisRecord.__post_init__` (`:581-587`) checks `allocated × 4 ≤ 0.025` for re-arm-gating records, hence `KalshiHypothesisRecord`.
- The R3 parity vectors must include a re-arm-gating case.

## 6. Corpus partition and F_K
**F_K = 2026-10-08**, frozen with this ruling.

| Partition | Window |
|---|---|
| SEARCH | [TWC switch date per admitted series, F_K). TWC-era days only; top-of-book candlesticks. The switch date comes from `rules_primary` per event (N1) |
| Confirmatory holdout | [max(2026-07-01, F_K), F_H) = [2026-10-08, F_H), where F_H = min(2027-01-01, K-2b start). Shared-city stations are excluded by default |
| Sealed weather holdout | Kalshi marker `holdout_marker_kalshi_<sha256>.json`: O_EXCL, append on reopen, never the PM.us path |

**Rules.**
- SEARCH ∩ confirmatory holdout = ∅. SEARCH is < F_K and the holdout is ≥ F_K. A WB-4/WB-5 test enforces this.
- The K-1 prior is SEARCH-spent.
- No Kalshi path reads PM.us tape after 2026-09-25.
- The candlestick fetch is a separate, later, ledger-logged spend and is not authorised here.

## 7. θ_K sourcing rule
- **Source:** series `fee_type`/`fee_multiplier` (KXHIGHNY: quadratic, 1; `tests/fixtures/kalshi/series_KXHIGHNY.json:11-12`) plus the published schedule.
- **Rounding:** cent rounding is verified against vendor docs and at least one golden vector.
- **Record:** the sourcing artefact and its sha go in the Kalshi PREREG.
- **Before sourcing:** no bound_K, n_K or feasibility value is quoted. PM.us θ 0.0695 and ceil_6dp are not used.
- **Live truth** comes from fill reconciliation. `KalshiFeeModel` is the replay seam only.
- **Ineligible series:** a series with missing or disagreeing fee fields is ineligible.

## 8. KC-1 loss-floor rule (FQ-v2 §4.6)
**Requirement (F5 pin request r3 §4.6 and FQ-v2 T2).** The loss floor must pass the M2 gate for the family's own mix:
- G1 is structural reachability, "with margin" (`t_cross ≤ ⌊0.8·T_low(e)⌋`) when α* > 0.10.
- G3 power at δ = −0.16 must be ≥ 2.5 × α*. It is never rescued by raising α*.
- α* takes 0.10, else {0.20, 0.30}, else `unreachable_veto`.

**What WB-7a must deliver.**
- Its own floor for the Kalshi mix (leg composition, Kalshi path lengths, Kalshi take rate). It must not assume PM.us's M-yes ~7-tick median.
- A distinct `loss_stop_artefact_path` (`trade.py:779`).
- A frozen `sqrt_boundary`, a prediction-market-reviewer sign-off, and a recorded T2 ruling.

**Outcome rules.**
- `unreachable_veto` means KC-1 does not go live, recorded and never re-run at a higher α.
- Opening this plan does not count as T2.
- The PM.us F6 tests and the F5 PREREG stay untouched.

## 9. NOT decided
- Cross-venue α apportionment or discount (F1, beyond the provisional note).
- The F2 reading.
- WA-2 items.
- bound_K, n_K, take rate, horizon, and Kalshi PREREG contents.
- Any admission, switch date or candlestick spend.
- The K-2b start.
- Caps, enablement, permit and egress rows, and the shared-city position rule (WB-9b).
- Whether FQ-v2 T2 is met.

---
## Review amendments (BINDING): architect review, 2026-10-08

The review returned CHANGES. Where these amendments conflict with text above, the amendments govern.

### F1 (ruled; replaces the "Coordinator note on F1")
The freeze moves to WB-7b. The draft's earlier rationale ("after KILL, PM.us look-taking intake is closed") is **struck**: RA-13 §1/§5 keep HUNT-1, NO-side and archive-recal open after KILL. The deferral is safe for a different reason: Kalshi reserves nothing before WB-7b, which satisfies B-8.

This amends B2's "frozen in WA-3" to "procedure frozen in WA-3; values frozen at WB-7b".
1. **No early reservation.** No Kalshi α is reserved before WB-7b. Values read on 2026-10-08 are informational only.
2. **R_pm.** The N-S START ruling states R_pm, the number of PM.us ledger slots reserved for PM.us intake routes still open at that date. R_pm = 0 only if that ruling records that no PM.us route is open.
3. **Values at WB-7b.** Both are read once via `read_hypothesis_ledger` and frozen in the Kalshi PREREG:
   - PROGRAMME_ALPHA_K = 0.05 − Σpm_alloc − R_pm·0.0125
   - RE_ARM_GATING_PROGRAMME_ALPHA_K = 0.025 − Σpm_rearm_alloc
4. **K_reserved.** K_reserved = PROGRAMME_ALPHA_K, i.e. the whole frozen budget. Unused Kalshi slots are not released without a successor ruling.
5. **Enforcement.** All of it is Kalshi-side, with no PM.us edit:
   - The K register re-reads the PM.us ledger and refuses if the combined budget exceeds 0.05 or 0.025.
   - The K `may_gate_re_arm` fails closed on breach.
   - Nightly Kalshi triage alerts on a breach, and Kalshi takes no further looks until a ruling, so Kalshi always yields.
   - Any PM.us registration after WB-7b narrows its budget via `programme_alpha_override`, by ruling.
6. **Arithmetic.** All sums and comparisons use `fractions.Fraction(str(x))`, never float.

### F2 (confirmed; replaces the "Proposed reading")
- R4's floor tests the feasibility of the look-taking budget and nothing else.
- Every look-taking record, whether or not it is re-arm-gating, passes the power check at its actual per_variant_α = allocated/k (k = the class's real variant count). The check uses the K `recompute_mde` and must come in ≤ that class's plausibility bound. Otherwise the record is a zero-look `UNDERPOWERED_NOT_REGISTERED` (mirrors `hypothesis_ledger.py:1118-1157`).
- If RE_ARM_GATING_PROGRAMME_ALPHA_K ≤ 0 at WB-7b, no Kalshi record may gate re-arm. That is recorded and leads to N-2.
- `MIN_PER_VARIANT_ALPHA` is declared at `:186` but enforced nowhere today.

### Fixes
- **§4.** "≤ 0.0375" becomes "< 0.0375". Exactly 0.0375 (one full PM.us slot taken) passes R4.
- **§3 re-arm example.** Divide by the actual k: KC-1 has k = 2, so 0.025/3/2.

**Status after amendments:** CONVERGED as a ruling draft. It is issued to `docs/evidence/` when K-2b's N-S START ruling is written, because R_pm is only known then. Until then it binds as the procedure.

---
## Domain co-sign amendments (BINDING): prediction-market-reviewer, 2026-10-08

**Review verdict:** CHANGES. The review found the architecture sound and conservative: fixed-slot Bonferroni across both venues gives FWER ≤ Σ allocated ≤ 0.05, and the re-arm budget is a subset of the look budget. The coordinator ruled on each item below; these amendments govern over the text above.

### P1. Re-arm reservations are symmetric
- The N-S START ruling states two numbers:
  - R_pm: the PM.us look slots reserved.
  - R_pm_rearm ≤ R_pm: how many of those reserved routes may gate re-arm.
- The F1(3) re-arm value becomes:
  - RE_ARM_GATING_PROGRAMME_ALPHA_K = 0.025 − Σpm_rearm_alloc − R_pm_rearm·(0.025/4)
- R_pm_rearm = 0 is allowed only if the ruling records that every reserved route is non-re-arm.

### P2. R4 floor naming
- The R4 pre-screen is the **R4_WORST_CASE_K_FLOOR**: 0.003125 = 0.05/4/4, applied at k = MAX_VARIANTS. A programme α below 0.0375 fails; exactly 0.0375 passes.
- The 1/240 MIN_PER_VARIANT label is withdrawn.
- The binding test is F2's power check at the actual k. The floor is only a pre-screen.
- WA-4 W6's `min_per_variant_alpha` stays a derived informational field. It is never a floor.

### P3. Cluster-level statistic (pinned in the Kalshi PREREG)
- The confirmatory statistic is the **unweighted mean over distinct climate dates of the per-date mean excess per take**. Each take's excess is 1{win} − BE(a_i, C=1).
- n = the number of dates with at least one take. This is WA-4 G5/W7.
- A per-take ratio estimator such as `MEAN_EXCESS_PER_TAKE` is forbidden as the Kalshi confirmatory statistic.

### P4. Variance bound and reference ask
**Variance bound** (coordinator ruling, recorded verbatim in every record's `mde_variance_bound_justification`): the bound is taken conditional on the realised asks.
- Given a_i, BE_i is deterministic. So Var(excess_i | a) = p_i(1−p_i) ≤ 0.25.
- A per-date mean of variables that each have variance ≤ 0.25 has variance ≤ 0.25 (Cauchy-Schwarz), whatever the within-date correlation.
- The across-date mean therefore has conditional variance ≤ 0.25/n.
- The test is conditional on the realised take schedule, so σ ≤ 0.5 holds without a range-1 assumption on pooled excess.

**Reference ask:**
- `mde_reference_ask` is the **worst-case break-even ask** in the declared traded ask band, i.e. the band edge that maximises BE − a under per-order cent-ceil at C=1. A mid-band value is not allowed.
- The traded ask band is declared in the PREREG. Takes outside the band are refused by the strategy.

### P5. C=1 is an end-to-end invariant
Both of the following are tested in WB:
- The confirmatory statistic is computed only on C=1 fills.
- The Kalshi live order path submits quantity 1.

Any fill with C ≠ 1 is excluded and logged. This is not an operator-cap assignment: C=1 is the pinned order quantity, as on PM.us (`PINNED_ORDER_QUANTITY`).

### P6. The holdout before freeze
- No holdout outcome (settlement-joined excess) is read before the Kalshi PREREG sha is frozen at WB-7b. Shadow accrual may log counts only.
- **Stated consequence:** if F_H ≤ the K-2b start, the window may hold fewer than about 85 climate dates. At α_v≈0.0083 the MDE is then about 0.17 per take, so a zero-look `UNDERPOWERED_NOT_REGISTERED` (route N-2) is the likely outcome. That outcome is accepted.

### P7. Wording
- The 1/3 slot split is the cross-class Bonferroni (the text above is amended).
- The **Wilson n≥381 admission** (WA-2 Stage 0) and **n_K** are different quantities and are never interchanged:
  - **Wilson n≥381:** counts admitted events per series. It is a label-fidelity gate and spends no α.
  - **n_K:** counts distinct holdout climate dates. It is the confirmatory sample and is spent against α_v.

### P8. Multiplicity guards
**Re-registration after UNDERPOWERED:**
- Allowed only with new SEARCH data, since `bound_K` is derived from SEARCH outcomes.
- Every attempt is logged.
- The zero-look record is permanent.

**Slot release:** a successor ruling may never lower an allocation that has already been looked at.

**Enforcement:** it fails closed on any read error of the PM.us ledger (WA-4 W8).

**Status after these amendments:** superseded by the round-2 section below.

---
## Domain co-sign round 2 (BINDING): prediction-market-reviewer re-check, 2026-10-08

**Review verdict:** CHANGES. The amendments below supersede P4 and refine P2, P3, P5 and P6.

### P4′. Inference, variance and the reference ask (replaces P4)
**Primary test.** The test is a one-sided **Azuma–Hoeffding** test on the date-mean martingale differences.
- Order the dates d = 1..n. Let X_d be the mean excess per take on date d, so each X_d lies in an interval of length 1.
- The null is H0: E[X_d | F_{d−1}] ≤ 0 for all d. Under H0 the partial sums form a supermartingale.
- Reject H0 when X̄ ≥ c_α = √(ln(1/α_v)/(2n)).
- This needs **no independence across dates** and no variance estimate, so it is valid under serial and spatial weather correlation.
- The only requirement is predictable selection: every take and every weight 1/m_d is fixed by information available before that date settles.
- Sample-variance z-tests and fixed-σ normal critical values are **forbidden** for the Kalshi confirmatory read.

**Power and MDE.** The power screen uses the matching Hoeffding lower-tail bound:
- MDE_K(n, α_v) = c_α + c_β, where c_β = √(ln(1/(1−POWER))/(2n)) and POWER = 0.80.
- If μ ≥ MDE_K, then P(reject) ≥ 0.8.
- Coordinator check at α_v = 0.05/3/2:

| n | c_α | c_β | MDE_K |
|---|---|---|---|
| 85 | 0.1678 | 0.0973 | 0.2651 |
| 150 | 0.1263 | 0.0732 | 0.1996 |
| 365 | 0.0810 | 0.0470 | 0.1279 |

- **This is a deliberate cost.** The bound ignores the low realised variance of a series with win rate above 0.99, so MDE_K is conservative by a material factor. `UNDERPOWERED_NOT_REGISTERED` (route N-2) is the expected outcome at short holdouts, and that outcome is accepted.
- A tighter p_max-based bound is **rejected**. p_max would come from SEARCH outcomes, which adds a forking-path degree of freedom.

**Outcome-blind schedule.** During the holdout read window the Kalshi take rule is outcome-blind:
- no settlement feedback;
- no re-arm, loss-halt or bankroll gating that depends on holdout settlements.

The operator caps are fixed constants, not outcome feedback. If any outcome feedback ever exists, the test still holds conditionally on F_{d−1} alone, which is the martingale form above.

**Reference ask.** `mde_reference_ask` = argmax of [BE(a) − a] over **every tick** in the declared traded band, enumerated over both legs, using the sourced θ_K.
- The tie-break is the lowest ask.
- The value is used only for documentation and band admission, because MDE_K does not depend on BE under the Azuma bound.
- BE in the statistic uses the **actual C=1 fill price**. The same `break_even_k` function serves both the statistic and the documentation.

**Variance justification.** `mde_variance_bound_justification` records:
- the Azuma range-1 argument;
- the predictable-selection condition;
- the deliberate-conservatism note above.

### P2′. Floor arithmetic
0.05/4/4 = 0.0375/3/4 = 0.003125. Both derivations give the same single floor.

### P3′. Fixing n and the weights
- n (dates with at least one take) and the weights 1/m_d are fixed before settlement.
- Voided or cancelled markets are excluded by this pre-declared rule, and every exclusion is logged with its market id.

### P5′. Break-even uses the fill price
BE in the statistic uses the actual C=1 fill price, not the decision ask.

### P6′. Wording fix
The small-n consequence reads: "MDE_K ≈ 0.265 at n=85 (larger below 85)". This supersedes the 0.17 figure, which came from the withdrawn normal-σ form.

### Consequence for WA-4
WA-4 W15 applies: K uses its own `recompute_mde_k` (Azuma) and does not adopt `recompute_mde`.

**Status:** domain CO-SIGN given in round 2, with wording fixes N1 and N2 applied below. W15 was confirmed by the architect via WA-4 W15a. **Ruling draft CONVERGED.** It is issued to `docs/evidence/` with the K-2b N-S START ruling, once R_pm and R_pm_rearm are known.

### Round-2 wording fixes (BINDING)
- **N1.** In P4′, "each X_d lies in an interval of length 1" now reads: each X_d lies in [−B̄_d, 1−B̄_d], where B̄_d is the mean fill-price break-even of date d's takes, fixed before date d settles.
  - F_{d−1} includes date d's fills but not its settlements.
  - The power statement holds when μ is a lower bound on the conditional means E[X_d | F_{d−1}]. Mean-stationarity is not required.
- **N2.** This supersedes the void clause of P3′.
  - A voided or cancelled take is **kept** in m_d and n.
  - It is scored as excess = 0 (refund) minus any non-refunded fee. That value stays inside the date's interval, so the range-1 argument holds.
  - Every void is logged with its market id.
  - Dropping voided takes is forbidden.

# RULING — A1: disposition of `pm_us_crh_v4`

Status: ENDORSED 2026-09-21 — independent peer review ENDORSE, no required change, on Revision 3 (`docs/evidence/reviews/RULING_A1_review_2026-09-21.md`). Rulings delegated to engineering peers by the operator. UNENFORCED until AUD-02b lands and the halt is set.

**Slug:** `A1_pm_us_crh_v4_disposition` · **Date:** 2026-09-21 · **Author:** prediction-market-reviewer (domain peer, BLIND run; no other agent's output visible)

## Revision 2 (2026-09-21) — changes made in response to independent review

Independent review: `docs/evidence/reviews/RULING_A1_review_2026-09-21.md`
(verdict ENDORSE-WITH-REQUIRED-CHANGES). Every defect re-verified against
source directly before editing, not taken on trust. Disposition (ii)
unchanged.

- **D1 [MEDIUM], applied:** §3 item 5 wrongly claimed
  `docs/evidence/venue/polymarket_us/` does not exist. It exists and
  contains `FEE_SCHEDULE_PIN_2026-09-18.md`. Corrected to state the
  directory exists but that file does not meet A0's per-slug/
  ≥5-consecutive-day/extended-pin-test acceptance criterion. Bottom-line
  conclusion (A0 unmet) unchanged.
- **D2 [HIGH], applied:** §4 wrongly characterized the halt mechanism as
  unbuilt ("EXIT-1-shaped" follow-up). The halt STATE and VETO
  (`FAMILY_HALT_KEY`/`is_family_halted`, `family_halt_submit_veto`) already
  exist and are already wired at the submit chokepoint; only a
  policy-triggered SET path is missing (only `clear_family_halt_cli.py`
  exists, no `set` sibling). Rewritten to name the precise missing piece
  (a `breezy-set-family-halt` CLI), assign it to **AUD-02b: enforce the
  A1 ruling** (Revision 3 correction — see below; not AUD-01), and state
  plainly, present tense, that this ruling is **unenforced until that CLI
  lands and is run** — today's zero-take state remains accidental, not
  designed.
- **D3 [LOW], applied:** §7 now names HUNT-1 (operator requirement,
  commit `9ddcb8b`, `PROGRESS.md:51`) as a second, independent
  precondition any future re-arm must clear, alongside the CI/A0/A-9
  conditions.
- **Citation fix (brief mis-cite):** §7 item 4's n-reset requirement is
  now attributed to `POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2, not
  L-34. §1's verbatim quote of the plan's own A1 row (which itself says
  "per L-34") is left unedited since it is a direct quotation, not this
  ruling's own analysis.

## Revision 3 (2026-09-21) — coordinator-directed ownership correction

Delta review (appended to `docs/evidence/reviews/RULING_A1_review_2026-09-21.md`)
confirmed D1-D3 fixed and found one remaining defect: assigning the
`breezy-set-family-halt` CLI to AUD-01 conflicts with AUD-01's own hardened
§5 scope. Verified directly: `AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md`
§5 explicitly EXCLUDES "Retiring `pm_us_crh_v4` outright, or ruling on the
YES side — a family-disposition and edge question, owned by **AUD-02**
(G-02); AUD-01a is the minimum safety action available without that
ruling." Setting the halt to enforce this A1 disposition ruling is exactly
such a family-disposition action. Also verified `AUD-02-edge-discovery-programme-status-and-fold-in.md`
§5 already names A1 itself as its own excluded item ("Deciding A1 itself...
a strategy-lead ruling") — i.e. AUD-02 already owns A1 as a topic, and
nothing in its §5 forbids adding an implementation sub-item now that A1 has
been ruled; its current "documentation-only" framing (§5/§6 preamble) is a
description of today's scope, not a structural barrier to widening it.

**Correction applied throughout:** every "owner: AUD-01" assignment for the
set-halt CLI is replaced with **AUD-02b: enforce the A1 ruling** — a new
named sub-item of AUD-02, scoped to (a) a `breezy-set-family-halt` CLI
mirroring `clear_family_halt_cli.py`; (b) RED-first tests including
refusal-to-send after set and idempotent re-set; (c) a logged AND alerted
halt event (matching the alert-egress discipline `POST_FORECAST_PHASE`
amendment B-0/WP-B0 already established — a halt event is exactly the
"correct finding, undelivered" shape that amendment exists to prevent);
(d) the one-time act of running it for `pm_us_crh_v4`. AUD-01 is
UNTOUCHED — no change to its scope, §5, or work packages.

## 1. Question(s) ruled, verbatim

From `docs/plans/POST_FORECAST_PHASE_2026-09-20.md` work-package row **A1**
(`:45`): "**The θ ruling — a DECISION, not a constant edit.** Options: (i)
RETIRE v3; (ii) **STOP TRADING THIS SURFACE**; (iii) re-register class-C
`pm_us_crh_v4` at observed θ, **n reset to 0 per L-34**, new
`d0_climate_day`, new `trial_id_prefix`, fresh LD-OBF α." Precondition
column: "a post-θ edge estimate whose CI excludes 0... if A0 cannot produce
one, (iii) is abandoned by default and (ii) is the answer." Critical-path
note (`:57-63`): "honest expected outcome is (ii) stop trading this
surface." A-9 (`:211-227`) and A-10 (`:229-233`) — the invariants a (iii)
ruling must satisfy and the brake it removes. B-1 (`:263-268`) — correction
that A1's stated precondition previously cited the wrong family's statistic.

Widened by `docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md`
§6 item 2 (`:170-180`, the item the plan itself calls "§6.2"): the
post-θ edge estimate "must be computed WITHOUT relying on
`P_HOLD_LOWER`/`P_HOLD_UPPER` cells whose gate-pass conditioning the domain
reviewer has ruled a collider... if none can be produced without real
(non-synthetic) historical venue ladders, (ii) STOP TRADING THIS SURFACE is
not merely the default, it is very likely the only defensible ruling." §12
(`:319-325`, `:340-345`) names A1 as the still-open blocker and names A1
itself as owner of the A-9-consistency question for `bcb82d6`/`e3e8ac6`.

**Second question (operator):** does adding a backlog item ("AUD-18":
design/backtest/iterate on the strategy, owning "a genuinely independent
edge estimate") make A1 decidable now, and if not, what does it resolve?

## 2. Options considered

- **(i) RETIRE the lineage.** Rejected as the sole disposition: retirement
  implies the estimand is permanently abandoned. The evidence below shows
  the *current* pricing table and observation feed are unsalvageable, not
  that a future, correctly-built edge estimate is impossible. Folding into
  (ii) with a defined reopening path is more informative than a bare
  retirement with no stated re-entry condition.
- **(ii) STOP TRADING THIS SURFACE.** Adopted — see §4.
- **(iii) Keep/re-register at observed θ=0.0695 with a genuinely
  independent edge estimate.** Rejected FOR NOW: its own stated
  precondition (CI-excludes-zero edge estimate, per AUD-02 §6.2 not built
  on gate-pass `P_HOLD` cells, per A0 a completed fee-drift evidence pack)
  is unmet today on the evidence in §3. Not closed permanently — see §7.
- **Leave open (no ruling).** Rejected. AUD-02 §12 already names A1 as an
  aging, undelivered blocker of exactly the shape (`docs/core/LESSONS.md`
  "alerts-reach-nobody", "readiness-audit-2026-09-12") that has twice cost
  this repo multi-day silent failures. The operator dispatched this ruling
  specifically to close that gap; declining to rule would reproduce it.

## 3. Evidence (verified)

1. **Zero decisions reach pricing, on two separate days.**
   `docs/evidence/DECISION_FUNNEL_2026-09-20.md:8-19`: 09-20 40,796
   decisions / 09-16 53,624 decisions, `illegal_cell` = 0 legal in both, ask
   and break_even `None` on every row of every recorded day. Re-confirmed
   at day-end (`:347-354`): 51,398 decisions, still zero reached pricing.
   Independently corroborated: `docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:32-36`
   (G-01, coordinator-verified) — "No order since 2026-09-15T20:12:06Z
   while the node is alive with a valid permit."
2. **The frozen `p_hold` table is CONFIRMED biased, not merely
   under-populated.** `DECISION_FUNNEL_2026-09-20.md:709-716` ("Status: the
   p_hold finding is now CONFIRMED, not provisional"): NO-side inflation in
   233/240 cells, mean +0.094 against the correct bound `P_HOLD_UPPER`,
   reproduction control re-derived and verified (`:630-659`), clustering
   resolved and strengthening the sign (`:661-687`, 4/4 independent
   station-level groups positive). Wiring verified at
   `decision.py:439-441` (cited in-doc, not independently re-read by me —
   flagged as unverified-by-me below).
3. **"Recalibrate on gate-pass" is independently ruled invalid** —
   `DECISION_FUNNEL_2026-09-20.md:491-495, 535-547`: conditioning on a
   near-degenerate collider (79/240 cells at p-hat=1.0, n below the
   corpus's own `N_MIN=90`), domain-review verdict verbatim: "the family is
   currently **UNSALVAGEABLE, not merely miscalibrated**." This is the
   exact clause AUD-02 §6.2 cites to widen A1's precondition — verified
   the citation is accurate, not paraphrased-beyond-source.
4. **No real (non-synthetic) historical venue ladders exist for this
   question.** `DECISION_FUNNEL_2026-09-20.md:545-546, 606-611`: only n=71
   station-days are ladder-MEASURED; the large-n arm (6,956 station-days)
   is ladder-ASSUMED (synthetic 2°F tiling). This is the concrete blocker
   AUD-02 §6.2 names as making (iii) "very likely the only defensible
   ruling" absent it.
5. **A0 (the evidence pack A1 itself depends on) has not been produced —
   REVISED per review D1.** `docs/evidence/venue/polymarket_us/` EXISTS
   (verified directly: `ls -la` succeeds, not exit 1 — my original claim
   that it does not exist was wrong and is corrected here) and contains
   `docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md`
   (read in full). That file documents the `0.06` pin, a single
   2026-08-25 snapshot exact-set (729 captured objects, all `0.06`), and
   the 09-17 drift discovery (six offer-tape rows, all `0.0695`, one day).
   It does **not** satisfy A0's own acceptance criterion
   (`POST_FORECAST_PHASE_2026-09-20.md:44`): a re-pull of `feeCoefficient`
   across **all listed weather slugs**, **≥5 consecutive days**, wire
   drift separated from tape-writer artefact, maker field recorded
   independently, and a RED-first test extending
   `test_polymarket_us_fee_schedule_pin.py` to pin the OBSERVED SET. No
   per-slug/per-day table and no such extended pin test exist anywhere
   under `docs/evidence/`. **Net effect unchanged: A1's own stated
   dependency (A0 → A1) is unmet** — a second, independent reason (iii)
   cannot be ruled today, alongside the `P_HOLD` finding.
6. **Admissible sample is zero.** Six historical live fills exist
   (operator-stated evidence, taken as given per this ruling's brief); no
   fill has occurred since `2026-09-15T20:12:06Z`
   (`AUTONOMY_ROI_AUDIT_2026-09-21.md:35-36`, `AUDIT_2026-09-21` corpus).
   `docs/core/PROGRESS.md`'s own recorded state (per AUD-02 §12, `:326-329`
   and MEMORY `no-family-has-an-edge.md`) is "NO FAMILY HAS A PROVEN EDGE,
   admissible n = 0."
7. **`pm_us_crh_v4` IS registered and deployed.**
   `deploy/families/pm_us_crh_v4.json` (read directly): `status:
   "REGISTERED"`, `taker_fee_coefficient: "0.0695"`, `d0_climate_day:
   "2026-09-20"`, `trial_id_prefix: "continuous_rung_hold/trial/"`.
   Commits `bcb82d6`, `e3e8ac6` read directly (not agent-summarized):
   e3e8ac6 registers θ on the manifest after a **first attempt was
   rejected by security review as a laundered pin edit** (env-var theta,
   reverted); bcb82d6 fixes an unrelated alert-delivery regression and
   promotes the unit name to v4.
8. **A-9 invariant check (I performed this, since AUD-02 §12 names A1 as
   its own owner):**
   - Clause 1 (θ constant stays `Decimal("0.06")`): **HOLDS** — verified
     `src/breezy/adapters/polymarket_us/fees.py:86`,
     `DOCUMENTED_TAKER_FEE_COEFFICIENT = Decimal("0.06")`; pinned by
     `tests/unit/test_polymarket_us_fee_schedule_pin.py:226`.
   - Clause 2 (new `trial_id_prefix`): **LITERALLY NOT MET** —
     `pm_us_crh_v4.json`'s `trial_id_prefix` is byte-identical to
     `pm_us_crh_cont.json`'s (`"continuous_rung_hold/trial/"`). **However,
     this is BY DESIGN, not a defect**: `src/breezy/persistence/family_manifest.py:13-21`
     and `src/breezy/settlement/family_barrier.py:15-22` both document,
     and `assert_family_only` (`family_barrier.py:52-96`, read directly)
     mechanically enforces, that prefix-sharing between successive
     families on one latch is expected — `d0_climate_day` (lower,
     inclusive) plus the predecessor's `terminal_climate_day` (upper,
     inclusive) are the real discriminant. `pm_us_crh_cont.json` declares
     `terminal_climate_day: "2026-09-19"`; `pm_us_crh_v4.json` declares
     `d0_climate_day: "2026-09-20"` — contiguous, non-overlapping. The
     plan's checklist prose ("new trial_id_prefix") is imprecise against
     the mechanism it is protecting; the protection itself holds.
   - Clause 3 (family-keyed residual sidecar): **NOT VERIFIED** — did not
     locate and read the residual-sidecar code in this session; flagged,
     not claimed.
   - Clause 4 (`assert_family_only` refuses cross-family rows both ways):
     **HOLDS structurally** — confirmed by reading the four independent
     checks in `family_barrier.py:75-96` (prefix, D0 lower bound, terminal
     upper bound inclusive, station census); this is symmetric by
     construction per its own docstring, which I verified against the
     code rather than trusting the docstring alone.
   - Clause 5 (v4's n accrues only from station-days strictly after
     registration): **CONSISTENT with available evidence** — the venue fee
     mismatch (`FEE_SCHEDULE_MISMATCH_REFUSALS`, A-10) refused every order
     from 09-17 until `e3e8ac6` landed 09-20 15:26Z, so no same-day v4-rung
     trade could have occurred before registration. Not independently
     re-derived from raw logs in this session.

## 4. RULING

**A1 = (ii) STOP TRADING THIS SURFACE.** `pm_us_crh_v4` is not to place any
further order. This is the most conservative option that still moves the
programme toward the goal state: it does not delete the registration or the
family's history (nothing here weakens or deletes any artefact, test, or
safety gate), and it names the exact conditions (§7) under which a *future*,
properly-evidenced (iii) could reopen A1 as a *new* ruling against a *new*
manifest.

**What v4 is and is not permitted to do in the meantime — REVISED per
review D2 [HIGH]:** the original text of this section understated what
already exists and overstated what is missing. Verified directly this
revision:

- **The halt STATE and its VETO already exist and are already wired at
  the chokepoint.** `FAMILY_HALT_KEY` / `TrialDayLatch.is_family_halted`
  (`src/breezy/strategy/current_rung_hold/trial_day_latch.py:1002-1015`)
  is read by `family_halt_submit_veto`
  (`src/breezy/strategy/current_rung_hold/composition.py:195-228`), which
  `src/breezy/app/trade.py:260` wires into the exec client's synchronous
  submit-time veto — confirmed by reading all three sites. Per
  `trade_supervisor_core.py:158-170` (`continuous_family_halt_key`,
  read directly) this halt is sender-global under the node's cardinality-1
  design ("halted is GLOBAL-equivalent to this node's only sender is
  halted... no matter which literal family id currently occupies that
  slot"), so a halt set for the node's current sender denies
  `pm_us_crh_v4` specifically today. **There is no `family_halted` state
  left to build; my earlier text was wrong to describe this as
  greenfield "EXIT-1-shaped" work.**
- **What is actually missing: an operator/build-invocable primitive to
  SET the halt for a policy reason, not an automatic one.** Verified: the
  only two writers of `FAMILY_HALT_KEY` are
  `TrialDayLatch.record_duplicate_fill` and
  `TrialDayLatch.record_ambiguous_exit`
  (`trial_day_latch.py:861-915`, `:968-1000`) — both automatic
  consequences of specific fill/exit events, never a deliberate "halt
  this family now" action. The only CLI touching this key is
  `src/breezy/strategy/current_rung_hold/clear_family_halt_cli.py`, which
  only clears (confirmed: no sibling "set" CLI exists anywhere in the
  repo — searched by filename, none found).
- **NOT permitted:** to remain armed and reliant on the current
  `observation_ambiguous`/`illegal_cell` gates as an implicit safety net.
  Those gates are data-quality artefacts of the NWS feed's whole-degree
  cadence (§3.1) — unrelated to the NO-side pricing defect — and multiple
  independent efforts already in flight (LAX/MDW station-stall diagnosis
  under AUD-01, any future observation-feed change) could unblock Gate
  1/Gate 2 without anyone having re-ruled A1, exposing the
  **confirmed-unsafe** frozen `p_hold` table (§3.2) to real orders before a
  deliberate decision authorizes it.
- **Precisely what "not permitted" means operationally:** this ruling
  means `pm_us_crh_v4` may not SEND orders. It does not mean the node,
  quote-tape capture, shadow valuation, or the KILL clock stop running —
  none of those write orders, and nothing here asks any of them to halt.
- **Honest state, in the present tense: this ruling is UNENFORCED until
  the missing SET path lands and is actually run.** Today, nothing in
  the repo prevents `pm_us_crh_v4` from placing an order the moment
  pricing legalizes — the zero-take state remains the same accidental
  by-product of Gate 1/Gate 2 described in §5, not a designed control.
  Writing this ruling does not, by itself, stop the family.
- **Required follow-up (code, not performed in this artefact — this
  ruling is read-only per its brief), scoped precisely:** a
  `breezy-set-family-halt` CLI mirroring `clear_family_halt_cli.py`'s
  shape (reason string + evidence-path argument, flock-respecting,
  writing exactly the `FAMILY_HALT_KEY` payload shape
  `record_ambiguous_exit` already writes) — **not** a new state or veto,
  since both already exist. **Owner: AUD-02, as a new named sub-item
  "AUD-02b: enforce the A1 ruling" — REVISED per Revision 3, coordinator
  directed.** AUD-01's own §5 explicitly excludes "retiring `pm_us_crh_v4`
  outright... a family-disposition and edge question, owned by AUD-02
  (G-02)"; enforcing this disposition ruling by setting the halt is
  exactly that. AUD-02 already owns A1 as a topic (its own §5 names
  "deciding A1 itself" as its excluded item, i.e. A1 belongs to AUD-02's
  scope once ruled); nothing in AUD-02's §5 forbids adding an
  implementation sub-item now that A1 has been ruled — its "documentation-
  only" framing describes current scope, not a structural limit. AUD-02b
  is: the set-halt CLI; RED-first tests (refusal-to-send after set,
  idempotent re-set); a logged AND alerted halt event; and the one-time
  act of running it for `pm_us_crh_v4`. Because this is a several-line CLI
  mirroring one that already exists — not new gate machinery — it should
  be treated as urgent and small, not open-ended backlog engineering.
- **Permitted:** `pm_us_crh_v4` stays REGISTERED (do not delete the
  manifest, do not rewrite `d0_climate_day`/`trial_id_prefix` retroactively
  — that would violate the manifest's own non-retroactivity guarantee,
  `family_manifest.py:17-21`); its historical 6 fills and its tally
  remain a durable, citable record. AUD-01's NO-side calibration
  fail-closed gate should still land, untouched by this revision — it
  becomes a second, independent control for if/when a future family is
  re-armed, not the thing that makes today's halt safe (AUD-02b's set-halt
  CLI, once actually run, is what makes the state safe; AUD-01's gate is
  defense in depth for later).

**AUD-18 (operator proposal — "add a backlog item for designing,
backtesting and iterating on the strategy"): APPROVE AS A NEW BACKLOG ITEM,
but it does NOT make A1 decidable differently today, and does not retroactively
unblock (iii).**
- **What creating AUD-18 does:** gives the missing precondition (§3.4, §3.5
  — a genuinely independent edge estimate built on real, non-synthetic
  historical venue ladders, not reliant on gate-pass `P_HOLD` cells per
  AUD-02 §6.2) an owner and a place to be built, backtested, and iterated
  on, honestly scoped as new work rather than folded into the closed
  forecast-taker hunt.
- **What it does not do:** an item on a backlog is a plan, not a
  measurement. It contains no data and produces no CI. Today's ruling is
  (ii) because the evidence in §3 is what exists *today*; creating AUD-18
  changes nothing in §3. A backlog item cannot retroactively satisfy a
  CI-excludes-zero precondition any more than scheduling a study performs
  it.
- **Binding scope note for AUD-18, so it cannot smuggle (iii) back in
  without a fresh ruling:** AUD-18 is explicitly EXCLUDED from re-running
  the closed forecast-taker hunt (`RULING_forecast_edge_programme_closes_2026-09-20.md`,
  restated at `DECISION_FUNNEL_2026-09-20.md:625-628` and AUD-02 §5) and
  from recalibrating on the gate-pass subsample (ruled invalid, §3.3). Its
  output, if any, is an INPUT to a future A1-class ruling, never a
  self-executing re-arm.

## 5. Rationale, including the strongest argument against

**Strongest argument against (ii):** the funnel already yields zero trades
(§3.1), so an explicit halt is redundant ceremony — nothing is pricing,
nothing can fire, and setting the halt costs an operator/build action for
no marginal risk reduction today.

**Why it loses:** the zero-trade state is an *accident* of two unrelated
data-quality gates (whole-degree NWS cadence; an SFO-only `illegal_cell`
rung policy), not a designed control. AUD-01 (untouched by this revision)
is actively diagnosing why LAX/MDW stopped hunting at all (§3, "two of four stations are not hunting")
and multiple observation-feed redesigns were evaluated this same day
(Options A/B/C in `DECISION_FUNNEL_2026-09-20.md`) — any successful fix to
either gate reopens pricing onto a table this ruling's own evidence (§3.2)
shows is confirmed biased against the NO side in 233/240 cells. The
operator has already paid two multi-day costs for exactly this shape of
gap (a correct internal finding that never became an enforced control).
The halt mechanism itself already exists (§4, revised) — the missing
piece is a several-line `breezy-set-family-halt` CLI mirroring the
existing clear CLI, not new gate machinery — so closing this gap is cheap
relative to the risk it removes. Conservative wins, and there is no
engineering-cost excuse for leaving it unenforced.

## 6. Consequences — exact text changes needed (not performed here)

- **`docs/plans/POST_FORECAST_PHASE_2026-09-20.md`, A1 row (`:45`) and §2
  critical path (`:57-69`):** append "RULED 2026-09-21: (ii) STOP TRADING
  THIS SURFACE — see `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`.
  The halt state/veto already exist; the open follow-up work item is
  AUD-02b (`breezy-set-family-halt` CLI, owner: AUD-02), not a new gate."
- **`docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md`
  §12 (`:319-325`):** the "Named BLOCKER... A1 itself" bullet is RESOLVED —
  **A1 is RULED (ii)**; replace with a pointer to this ruling. Add a new
  §6/§7 sub-item **AUD-02b: enforce the A1 ruling**, scoped exactly per
  Revision 3 above (the set-halt CLI, RED-first refusal-to-send and
  idempotent-re-set tests, a logged+alerted halt event, and the one-time
  act of setting the halt for `pm_us_crh_v4`) — this is the plan's own
  work now, not a citation of AUD-01. The §12 bullet at `:340-345` (A-9
  consistency, "Owner is A1 itself") is RESOLVED by §3.8 above — record
  the clause-2 imprecision finding so it is not re-litigated as a defect
  later. **Delete the separate "Named BLOCKER (operator, budget-ceiling
  only)" bullet in §12** ("nothing arms... without an operator budget
  ceiling even if A1 rules (iii)") — it is now stale: A1 has ruled (ii),
  not (iii), so no arming question is pending on this family, and
  regardless the operator has stated the budget ceiling is already
  established (§7 below).
- **`docs/plans/backlog/AUDIT_2026-09-21/AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md`:**
  **no change.** AUD-01's own §5 excludes family-disposition/enforcement
  work on `pm_us_crh_v4`, naming AUD-02 as the owner; the set-halt CLI
  therefore belongs entirely to AUD-02b, not AUD-01. AUD-01's NO-side
  gate and LAX/MDW station-stall diagnosis proceed exactly as already
  scoped, unaffected by this ruling.
- **New backlog item AUD-18** (title suggestion: "genuinely independent
  edge estimate — design, backtest, iterate"): scope per §4 above (real
  non-synthetic ladders only; explicitly excludes re-opening the closed
  forecast-taker hunt or gate-pass recalibration); its acceptance
  criterion should be exactly the CI-excludes-zero, non-`P_HOLD`-dependent
  estimate AUD-02 §6.2 already specifies, PLUS the HUNT-1 condition (§7
  item 5), so a future A1-class ruling has something concrete to
  evaluate.
- **`docs/core/PROGRESS.md`:** the existing "NO FAMILY HAS A PROVEN EDGE,
  admissible n = 0" entry stays true and should now also note
  `pm_us_crh_v4` is RULED HALTED (ii) but **UNENFORCED** until the
  `breezy-set-family-halt` CLI lands and is run.

## 7. What would overturn this ruling; what remains operator-only

**Would overturn (ii) in favor of a future (iii)**, all of the following,
none of which exist today:
1. AUD-18 (or equivalent) produces an edge estimate computed on real,
   non-synthetic historical venue ladders — not the assumed/tiled arm —
   with a station-day-clustered 95% CI that excludes zero.
2. That estimate does not depend, directly or by construction, on the
   `P_HOLD_LOWER`/`P_HOLD_UPPER` gate-pass cells ruled a collider (§3.3).
3. A0's fee-drift evidence pack is actually produced under
   `docs/evidence/venue/polymarket_us/`, meeting A0's own acceptance
   criterion in full (§3.5, revised: per-slug re-pull, ≥5 consecutive
   days, wire-vs-tape-writer drift separated, maker field recorded
   independently, extended RED-first pin test), confirming θ=0.0695 is
   stable and taker-only, independent of the edge question.
4. A fresh manifest is registered satisfying `POST_FORECAST_PHASE_2026-09-20.md`
   §A-9 item 2 in full (including the still-unverified clause 3,
   residual-sidecar family-keying) with n reset to 0 and fresh LD-OBF α.
   (Correction: the shared ruling-author brief's "per L-34" citation for
   this n-reset requirement was a mis-citation carried over from that
   brief; the actual source is A-9 item 2 of the base plan, not L-34 —
   corrected here and in §1's verbatim quote is left as-is since it
   quotes the plan's own row text unmodified.)
5. **Any future re-arm must also clear the operator's continuous-hunting
   requirement (HUNT-1)** — REVISED per review D3. Verified directly:
   commit `9ddcb8b` ("evidence: continuous hunting is REQUIRED and is not
   met") records the operator's own words, "there is a definitive
   requirement that the trading bot's strategy must be continuously
   hunting, never inside just a specific window," and
   `docs/core/PROGRESS.md:51` (HUNT-1, CRIT) states the live
   `[12:00,17:00)` LST gate is a direct consequence of `P_HOLD_LOWER`
   covering `hour_lst` ∈ {12..16} only — removing the window gate today
   yields `None`, not hunting, not a wider window. Any future edge
   estimate AUD-18 or a successor produces must therefore also satisfy
   HUNT-1 (cover all hours, not just 12-16) before a re-arm, independent
   of the CI/A0/A-9 conditions above; this is not currently listed as an
   AUD-18 acceptance criterion and should be added when that item is
   drafted.
6. This ruling is a decision node, not a lock: a new A1-class ruling would
   still be required to actually re-arm — this document does not
   pre-authorize that outcome, it only states the evidentiary bar.

**Operator-only, and untouched by this ruling:** the two budget-ceiling
values (max daily budget, max per position) and live-trading enablement.
Per this ruling's brief, the operator budget ceiling is already
established and is treated as satisfied, not stated or valued here. No
other part of this decision is reserved to the operator — the θ=0.0695
disposition, the `P_HOLD` finding, and the A-9 consistency check are all
resolvable from evidence already in the repo, which is what this ruling
does.

## Unverifiable / not independently confirmed by me

- A-9 clause 3 (residual sidecar is family-keyed) — not located/read this
  session.
- `decision.py:439-441`'s exact NO-side wiring — cited from
  `DECISION_FUNNEL_2026-09-20.md`, not re-read line-by-line by me
  independently in this session.
- The claim that no v4-rung trade occurred before `e3e8ac6` registered
  (A-9 clause 5) — inferred from the fee-refusal mechanism (A-10) and
  commit timing, not re-derived from raw node logs.
- The six historical live fills and their dates — taken as given per this
  ruling's brief (operator-stated); not independently re-counted from the
  tally in this session.

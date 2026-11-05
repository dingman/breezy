# AUD-18 round-2 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-18-strategy-design-backtest-iterate-programme.md
sha256: 8d64da2403183c32bb8db8c5ea336f6e32070856100df9ce473c7e9f1c10b54d
Round: 2
Reviewer: mle-reviewer (independent, blind). Self-score text in §13 ignored per instruction.

## Round-1 defects — verification against source

1. **`load_realized_draws` citation — FIXED.** Now correctly cited to `src/breezy/persistence/realized_draws.py:249`; `combine_station_day`/`score_combined`/`resolve_alert_sink`/`emit_alert`/`information_fraction` re-verified at 298/348/579/668/367 — all CONFIRMED against source.
2. **No re-look guard — PARTIALLY FIXED, and a new defect introduced (see below).** `SINGLE_LOOK` with an "already-looked" ledger row mechanically blocks re-evaluation — sound. `LD_OBF` correctly reuses the shipped, pin-verified `BoundaryArtefact.boundary_for/alpha_spent/remaining_alpha` (`src/breezy/persistence/gs_boundary_artefact.py:183,201,211`) over `information_fraction` — API signatures CONFIRMED usable as cited. But the *composition* with the programme Holm ladder is not mechanically sound as specified — see MATERIAL defect below.
3. **§12 blocker → peer-ruling step — FIXED.** §7 step 8 now dispatches two named, independently-briefed specialists producing a dated `docs/evidence/RULING_*` artefact before registration and before data access, fixing n/stopping-rule/alpha-share/KILL criterion, touching no operator cap. Matches the operator-context instruction.
4. **D6 automated — FIXED.** Now an `import-linter` forbidden contract in both directions plus a write-path test plus the no-egress gate, not a hand check.
5. **Length — NOT FIXED, moved backward.** File is now 638 lines (was 473; target 120-250), despite the revision log's claim "Length reduced" — that claim is true only of §13's internal prose, not the file as a whole, which grew net +165 lines from §6.4b and the expanded §7/§12.
6. **Fourth-wrapper-invocation uncertainty — RESOLVED, correctly.** AUD-09 B18/AUD-10 C19 verified to name exactly three sanctioned scripts and fail an unnamed fourth; AUD-18 now ships its own `breezy-hypothesis-triage` unit/timer/wrapper (§6.4b), ordered `After=breezy-replay-daily.service`, serialized on the same `breezy-studies.lock`, capped `MemoryHigh=1G`/`MemoryMax=2G` — pattern matches the existing `breezy-offer-gate-daily.{service,timer}` precedent, confirmed to exist. §7 step 5 adds a non-regression RED on AUD-09's wrapper set. Sound.

## New defect — LD_OBF/Holm composition does not control FWER as specified

**What IS controlled:** within one `LD_OBF` variant, sequential monitoring on its pre-registered `n_k` grid via the shipped, pin-verified solver correctly bounds that variant's own marginal Type-I error to its nominal one-sided alpha — **but only if the variant's registered `family_wise_alpha`/`i_max` equal 0.025/40**, because `load_boundary_artefact` hard-validates `i_max != 40` and `alpha != 0.025` as refusals (`gs_boundary_artefact.py` docstring, confirmed), and the only committed reference table in the repo is pinned to the live family's own `n_max=160, I_max=40, alpha=0.025` design (`PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md:6,55-58,88`). The ledger schema's own comment ("e.g. 0.05, one-sided per WP-7 precedent") implies a hypothesis may register a *different* alpha — but no new pinned reference table can exist for it without extra, unscoped engineering (generating and validating a new `inputs_sha256`-pinned artifact), so an `LD_OBF` hypothesis is in practice locked to 0.025/40 or the plan's cited reuse path does not work as written.

**What is NOT controlled / unspecified:** §6.4 step 3's composition rule says each variant's "ENTIRE sequential alpha ... is the one number entering the Holm ladder" for the cross-variant selection decision. Holm-Bonferroni's step-down procedure requires **data-dependent p-values** (or an equivalent attained-significance ranking) to order and threshold hypotheses; a pre-registered **alpha budget** (fixed at registration, not data-dependent) is a different quantity and cannot be substituted — ranking candidates by their own declared budget is not a test of evidence. If instead each `LD_OBF` variant is meant to spend its **full own** 0.025 independently (which the pin forces) and Holm is applied only as a post-hoc filter afterward, then no variant's own alpha is actually shrunk by the Holm ladder, and the design provides no protection against exactly the repeated-tries risk this item exists to close (§1, §11) — up to `K_variants` independent 0.025 shots. The plan does not state which of these two interpretations is intended, and neither is currently correct as literally written. **Required change:** either (a) specify precisely how each variant's Holm-input quantity is a data-dependent attained p-value derived from its terminal boundary crossing (with the formula), and how a per-variant alpha smaller than 0.025 is obtained (new pinned artifact, generation procedure, and CI verification of it) when Holm shrinks a variant below its nominal registered alpha; or (b) drop the "Holm ladder over LD_OBF variants" framing and state explicitly that cross-class protection comes only from the fixed, pre-registered `K_variants`/one-hypothesis-per-class structure, not from post-hoc Holm on sequential results — and say so plainly rather than implying FWER control that isn't there.

## Per-criterion scoring (round 2, whole plan, fresh)

- Fidelity to audit gap and completeness: 18/20 — closes the loop faithfully and converts the operator-flagged blocker correctly; not 20 because the composition gap above leaves the central "multiplicity control" promise partly unproven.
- Technical correctness and evidence grounding: 15/20 — all citations now verified correct (up from one error), but the Holm/LD_OBF composition is a genuine, unresolved statistical-soundness gap, and the pin-lock (alpha=0.025/i_max=40) constraint on reuse is undocumented.
- Implementation specificity and feasibility: 11/15 — ledger/triage/scheduling surface (§6.4b) are now concretely specified and verified against real precedent files; the composition formula and new-pin-generation path (if a hypothesis needs alpha != 0.025) are left for the implementer.
- Acceptance criteria and validation quality: 17/20 — D9-D11 add real, testable coverage of the no-re-look invariant, D5 non-regression, and failure alerting; no criterion tests that the Holm-ladder input is a valid data-dependent quantity rather than a fixed budget.
- Autonomous operation, failure handling and recovery: 13/15 — §6.4b's unit/timer/lock/memory-cap/alert design is concrete and precedent-matched; crash-mid-look recovery still asserted, not independently tested.
- Portfolio objective alignment, scope and dependencies: 8/10 — scope, exclusions, and dependency IDs remain tight; docked for the length regression (638 vs 120-250 target, moving the wrong direction since round 1).

**Total: 82/100**

## Blockers

- None newly introduced requiring operator/external input. The peer-ruling step (§7 step 8) is correctly converted to an in-plan artefact-producing step, not an external blocker.
- The Holm/LD_OBF composition gap above is author-fixable (a specification/formula fix, possibly plus a new pinned-artifact generation step) and not an unavailable-evidence blocker.

Not 100/100: one MATERIAL defect remains open (Holm/LD_OBF composition), plus the length regression.

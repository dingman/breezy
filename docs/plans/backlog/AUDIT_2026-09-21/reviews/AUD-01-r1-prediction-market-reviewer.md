# AUD-01 review — round 1 — prediction-market-reviewer

Plan: AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md
sha256: 17a956c71f84ef96c8a37e2dd0576e066612459fdb1f366dcf92fa250f982427
Round: 1
Reviewer: prediction-market-reviewer (blind, independent)

## Claims verified

- `decision.py:436-441` gate placement (bid/bid_size check then `no_ask`/`p_hold_upper` lookup) — CONFIRMED verbatim against source.
- `_is_legal_cell` (`decision.py:291-302`) unconditional refusal of `width_code==2`, cites L-22 — CONFIRMED (docstring text matches, L-22 header confirmed at `LESSONS.md:1017`).
- `REFUSAL_REASONS` is a closed `frozenset[str]` (`decision.py:120`, validated in `Refuse.__post_init__`) — CONFIRMED; plan's hedge ("verify... before assuming") is appropriately cautious and accurate.
- `f97c26f`/`6aa9d92`/`e83fc5c` commit content — CONFIRMED, matches plan's characterization.
- Funnel numbers (40,796 decisions, 0 legal/priced/margin/orders) — CONFIRMED against `DECISION_FUNNEL_2026-09-20.md`.
- Domain reviewer verdict ("UNSALVAGEABLE... absent real historical venue ladders") — CONFIRMED verbatim in the evidence doc.

## Claim REFUTED

- §5/§12: "Widening the trading window (HUNT-1) — moot per DECISION_FUNNEL's own consequence note; not re-litigated here." REFUTED on two grounds:
  1. `DECISION_FUNNEL_2026-09-20.md` itself says "HUNT-1 stays open but is de-prioritised behind these two [gates]" — not "moot". The plan overstates its own cited source.
  2. `docs/core/PROGRESS.md:51` currently carries HUNT-1 at **CRIT** priority, restored same-day (commit `9ddcb8b`, "restore the item I deleted") on an explicit OPERATOR STATEMENT: *"there is a definitive requirement that the trading bot's strategy must be continuously hunting, never inside just a specific window."* PROGRESS's HUNT-1 entry names the mechanism directly: the `[12:00,17:00)` gate is a consequence of `P_HOLD_LOWER` covering `hour_lst ∈ {12..16}` only — i.e. an operator-mandated, structural cause of decisions never reaching pricing outside that window, on top of the two in-window gates this plan does address.

## Defects

- **MATERIAL** — §5/§12, HUNT-1 exclusion. The plan dismisses an operator-mandated, CRIT-priority, currently-open requirement as "moot" using a citation that does not say what the plan claims (brief §"a citation that does not say what the plan claims is a defect"), and never reconciles this against PROGRESS.md despite the brief requiring that check. This bears directly on whether G-01 is left "honestly dispositioned": a reader of AUD-01 alone would conclude the pricing-gate problem is fully accounted for by Gate 1/Gate 2, when a third, distinct, operator-flagged structural cause (window narrowness itself) is left completely unaddressed and mischaracterized as closed.
  - Required change: correct §5/§12 to state HUNT-1 stays open at CRIT per PROGRESS.md and the operator's continuous-hunting requirement; narrow the "moot" claim to what was actually measured (widening the window alone does not clear an edge threshold, per `ALL_HOURS_EDGE_TABLE_2026-09-20.md`) without implying the operator's requirement is satisfied or irrelevant. This does not have to be solved by AUD-01 — it must not be mischaracterized as closed.
- **MINOR** — §7/§8, AUD-01a's RED test plan does not specify asserting the refusal fires strictly BEFORE the `P_HOLD_UPPER.get(key)` lookup executes (only that the outcome is `Refuse`), so an implementer could satisfy the letter of the acceptance criteria by gating after the lookup, weakening the "never computed" intent stated in §6.2. Add an explicit assertion (e.g. via a spy/mocked lookup) that the table is never consulted when the flag is False.

## Per-criterion points

- Fidelity to audit gap and completeness: 14/20 — AUD-01a is well-grounded and correctly minimal; the HUNT-1 mischaracterization undermines "honestly dispositioned" for G-01 as a whole.
- Technical correctness and evidence grounding: 16/20 — every other citation verified accurate; the HUNT-1 citation is inaccurate relative to its own source.
- Implementation specificity and feasibility: 17/20 — gate placement, config field, and refusal-reason wiring are concrete and independently verified correct.
- Acceptance criteria and validation quality: 17/20 — concrete and testable; minor gap on asserting the lookup is never reached (see MINOR above).
- Autonomous operation, failure handling, recovery: 14/15 — pure function, fail-closed default, explicit rollback story.
- Portfolio alignment, scope, dependencies: 8/10 — correctly scopes family-retirement to AUD-02, but the HUNT-1 mischaracterization creates a scope-boundary risk (a reader could believe HUNT-1 is settled and drop it from the backlog).

**Total: 86/100.**

## Required changes to reach 100

1. Correct the HUNT-1 characterization in §5 and §12 to match PROGRESS.md's live CRIT status and the operator's stated continuous-hunting requirement; do not use "moot".
2. Strengthen the RED test to assert `P_HOLD_UPPER.get` is never called when the gate is closed, not merely that the outcome is `Refuse`.

## Blockers

None that require operator/strategy-lead input beyond the pre-existing, correctly-named AUD-02 blocker (A1 ruling). The HUNT-1 correction is a plan-text fix, not a ruling.

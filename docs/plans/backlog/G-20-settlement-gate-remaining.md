# G-20 — Asymmetric settlement gate: what remains after the rollup

Status as of 2026-08-27. The per-city coverage rule (`src/breezy/settlement/coverage.py`)
and the programme rollup (`src/breezy/settlement/programme.py`) are implemented, tested,
and pure per [R7]. Neither is wired into any trading path.

Binding spec: `docs/evidence/asymmetric_gate_prereg_2026-08-26.md`.

## Open

### [HIGH] Rule 4 — headline reporting is unimplemented
Prereg §7 rule 4 (line 855-857): "**MDW's result appears in the headline determination
whatever it is. A four-city pass may never be reported without MDW's number stated
alongside it.**"

`programme.py` contains zero references to MDW or to a headline concept. `grep -c MDW`
returns 0 for the module. `ProgrammeDetermination` does carry every city determination,
so a reporter *can* reach MDW's number — nothing yet *forces* it to.

This was omitted from the implementation brief, not by the implementer.

Note the sentence immediately preceding these rules, line 845: "Discipline that changes
no action is theatre." An unenforced reporting rule is exactly that. The obligation is a
reporting-layer constraint rather than a computation one, so it lands with the reporter —
but it must land *with* it, not after.

Suggested shape: the reporter cannot emit a programme headline without MDW's cell
figures; a guard test asserts a headline built from a four-city pass that omits MDW
raises rather than rendering.

### [MEDIUM] No consumer exists
`grep -rn determine_programme src` finds only the module itself. The gate computes a
determination that nothing reads. Until a consumer exists, every guarantee here is
latent.

### [MEDIUM] Rule 2 has no mechanism
Rule 2 (line 850-853) forbids any downstream document, requirement, or strategy from
asserting "METAR reads below CLI" as a general property of the estimator, and requires
any component relying on it to re-derive per city. There is no barrier test enforcing
this. It is a candidate for an AST/prose scan in the barrier-suite style.

## Closed

- Rule 3 — two-or-more primary NO-GO rejects programme-wide. Threshold is 2 per [R4],
  which corrected revision 3's "three or more". Expiry-converted NO-GOs count.
- Rule 5 — halt-and-unwind. Programme rejection sets every city, including live GO
  cities, to HALT_NEW_POSITIONS_HOLD_OPEN_TO_SETTLEMENT. Open positions held to
  settlement, never force-closed.
- Rule 1 — per-city determination preserved. One NO-GO yields PROGRAMME_NOT_REJECTED,
  not a pass and not a rejection.
- NYC exclusion (lines 822-830) — structurally SECONDARY_NYC, contributes nothing to
  the failure tally.
- OUT_OF_SCOPE_DOM_9 ([R10], lines 265-274) — expressible, and excluded from the count.
- Minimum coverage [R2] — closed-set membership at the boundary AND at wide strata.
- [R13]/[R6] pre-resolution states raise rather than resolving to a determination.

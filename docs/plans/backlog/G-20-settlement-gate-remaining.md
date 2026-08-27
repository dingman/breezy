# G-20 — Asymmetric settlement gate: what remains after the rollup

Status as of 2026-08-27. The per-city coverage rule (`src/breezy/settlement/coverage.py`)
and the programme rollup (`src/breezy/settlement/programme.py`) are implemented, tested,
and pure per [R7]. Neither is wired into any trading path.

Binding spec: `docs/evidence/asymmetric_gate_prereg_2026-08-26.md`.

## Open

### [MEDIUM] No consumer exists
`grep -rn determine_programme src` finds only the module itself. The gate computes a
determination that nothing reads. Until a consumer exists, every guarantee here is
latent.

## Closed

- Rule 4 reporting path — `src/breezy/settlement/reporting.py` now refuses sanctioned
  reports that omit MDW, refuses `PRIMARY_GO` without MDW's boundary figure reported,
  renders MDW in the headline, and renders primary detail from the identity-checked
  headline lines.
- Rule 2 second clause for the reporting path — D4a/D4b AST guards reject obvious
  programme-wide claim identifiers and one-sided direction identifiers while allowing
  per-city/city-keyed measurement and `SignedErrorDirection`'s two-polarity enum.
- Rule 2 first clause — closed as a prose lint, not a semantic proof. P1 scans
  `docs/plans`, `docs/core`, `docs/evidence`, `src`, and `scripts`, strips Markdown
  code spans/fences, and currently reports zero live hits.
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

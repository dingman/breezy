# AUD-04 delta 2026-11-01 — backlog item ROI-LEDGER (acceptance check, not a build)

Applies on top of `AUD-04-portfolio-roi-measurement.md` + `AUD-04-AMENDMENT-2026-09-21.md`. Status: r1 — peer review pending (python-reviewer + prediction-market-reviewer).

## 1 Objective and ROI mechanism
Portfolio-level realised ROI net of fees, per family and in total, is the denominator every other ROI item (SIZE-UNDER-CAPS bankroll, AUTO-PROMOTE-RETIRE retire rule, STRATEGY-SEARCH scorecard) measures against. AUD-04 is BUILT and DEPLOYED (`scripts/analysis/portfolio_roi_report.py`, `PORTFOLIO_ROI_SCHEMA_VERSION = 5` with `fill_pnl`/`family_pnl`/`disclosures`; `deploy/systemd/breezy-portfolio-roi.timer`). This item verifies it already serves those consumers and closes, or names the one missing field.

## 2 Acceptance (read-only, one delegation, ≤ 1 h)
A1. The latest report under the ROI output root carries `schema_version = 5`, a per-family block with realised P&L net of venue fees and settled count, a portfolio total, and the capital-deployed series (AUD-04 §6 I1–I3). Cite the artefact path and the fields by name; counts only.
A2. The timer is `active (waiting)` with a last run in the past 24 h and the OPS-4 label marker consumed (`n_labels_gated` reported; S3b fix 40dec67b).
A3. The per-family net view is readable by a pure function (no new script) that SIZE-UNDER-CAPS stage 2 can import: name it (`file:line`) or state the ≤ 20-line additive accessor needed (schema bump to 6 is additive-only per §6 D7).
A4. Fees: realised P&L uses the per-order banker's-rounded θ=0.0695 taker fee path and fee 0 for maker fills; cite where.

## 3 Outcome
A1–A4 MET → ROI-LEDGER = DONE in the backlog, no build. Any item unmet → one additive change under AUD-04's existing schema rules, RED-first, gate before push; never a new ledger or unit.

## 4 Invariants
Read-only check; no operator caps; no enablement; L-75 (report files never hand-edited).

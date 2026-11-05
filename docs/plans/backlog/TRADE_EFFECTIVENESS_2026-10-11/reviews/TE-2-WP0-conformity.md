# TE-2 WP0 conformity reviews (2026-10-11) — coordinator merge

- Stats (prediction-market-reviewer): CHANGES-REQUIRED; 1 HIGH (phase_b_refusals self-ancestor assertion unsatisfiable), 4 MED, LOWs. All expected statistics recomputed and CORRECT; design points (a) UNTESTABLE keeps commit, (b) reflog format, (c) T-LOC anchors formula-agnostic (formula must be named in the predeclaration), (d) FQ filter = instrument climate day ≥ 2026-10-01, (e) enum vocabulary — ACCEPTED.
- Python (python-reviewer): CHANGES-REQUIRED; same BLOCKER; HIGH: real-git porcelain cases, real reflog snapshot production path, GitPort.log_commits, per-file AST allowlists + bypass cases, core I/O-free test, module split; MEDs typing/FillRead/clip/refreeze/POST_EPOCH/S0-A gate/phase_a_truth/StrEnum/constants.
- Disposition: all BLOCKER/HIGH/MED applied in WP0 r2 by the original author.

## Plan §5 layout erratum (E-TE2-a)
To hold the 400-line cap after implementation, core splits into `scripts/analysis/fq_loss_taxonomy_stats.py`, `_classify.py`, `_verdict.py`; inputs into `_pins.py`, `_logs.py`, `_truth.py`. `fq_loss_taxonomy_core.py` and `fq_loss_taxonomy_inputs.py` remain the plan-named facades (re-exports). The S0-H HEAD-blob pins (`TE2_PINS.json`) cover the CLI script plus every core-side module (facade + stats/classify/verdict).

## WP2 freeze record (2026-10-12)
- First freeze b0fe067c/1c007b82 superseded BEFORE any Phase B run (no outcome consumed): freeze reviews (stats CHANGES-REQUIRED: honest expectation wrong — T-WIN rejection derivable from public W=2 + Phase A P_c; K4 gate; code CHANGES-REQUIRED: 6 HIGH provenance/clip gaps). Fixes 122ad04f/48f9bcd1.
- RE-FREEZE: predeclaration 526bdd11, pins 34e15832 (18 family modules + 14 src deps). Confirmation (python-reviewer): FREEZE-CONFIRMED; check_gates against the real repo returns no refusal.
- ACCEPTED GAP (MED, coordinator ruling): breezy.domain.{validation,strict_arrow,nws_raw_product} are in Phase B's import closure but unpinned; they validate NWS climate-day values. Accepted rather than a third re-freeze; any edit to them before the Phase B run is checked by hand (`git log 34e15832..<run commit> -- <paths>` must be empty) and recorded in the Phase B report.

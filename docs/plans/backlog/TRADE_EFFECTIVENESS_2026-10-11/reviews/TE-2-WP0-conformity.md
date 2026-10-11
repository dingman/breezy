# TE-2 WP0 conformity reviews (2026-10-11) — coordinator merge

- Stats (prediction-market-reviewer): CHANGES-REQUIRED; 1 HIGH (phase_b_refusals self-ancestor assertion unsatisfiable), 4 MED, LOWs. All expected statistics recomputed and CORRECT; design points (a) UNTESTABLE keeps commit, (b) reflog format, (c) T-LOC anchors formula-agnostic (formula must be named in the predeclaration), (d) FQ filter = instrument climate day ≥ 2026-10-01, (e) enum vocabulary — ACCEPTED.
- Python (python-reviewer): CHANGES-REQUIRED; same BLOCKER; HIGH: real-git porcelain cases, real reflog snapshot production path, GitPort.log_commits, per-file AST allowlists + bypass cases, core I/O-free test, module split; MEDs typing/FillRead/clip/refreeze/POST_EPOCH/S0-A gate/phase_a_truth/StrEnum/constants.
- Disposition: all BLOCKER/HIGH/MED applied in WP0 r2 by the original author.

## Plan §5 layout erratum (E-TE2-a)
To hold the 400-line cap after implementation, core splits into `scripts/analysis/fq_loss_taxonomy_stats.py`, `_classify.py`, `_verdict.py`; inputs into `_pins.py`, `_logs.py`, `_truth.py`. `fq_loss_taxonomy_core.py` and `fq_loss_taxonomy_inputs.py` remain the plan-named facades (re-exports). The S0-H HEAD-blob pins (`TE2_PINS.json`) cover the CLI script plus every core-side module (facade + stats/classify/verdict).

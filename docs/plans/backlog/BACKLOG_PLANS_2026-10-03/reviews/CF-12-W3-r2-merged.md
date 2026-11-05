# CF-12-W3 r2: merged review (coordinator)

Reviewer scores: python 91 (1 HIGH), architect 93. Final score 91, so the plan goes to r3. Both reviewers independently verified the C1 triage (non-reachable).

- **E1 [python, HIGH]: pin with counts.** R4 pins `Counter`/`tuple[(code, message, count)]`, not a frozenset. Add a positive control: replacing a fixed error with one that has a duplicate message must fail R4.
- **E2 [architect, MEDIUM]: a G4b real-resolution check.** In the same scrubbed `-m` environment that the unit uses, import the module and resolve `fee_drift_evidence_pull`, which is the `discovery_venue_pull.py:373` path. Do not stop at `--help`. Extend the omit-bootstrap RED proof to the venue directory. Copy the unit's real `Environment=` into the command.
- **E3 [both, MEDIUM]: checker rigor.**
  - Do not delete imports. Map `scripts.<dir>.x` to `x`.
  - Allow only the explicitly listed new imports (`sys`, `Path`, `importlib`).
  - Compare the import multisets.
  - Require the bootstrap to match an exact AST template.
  - Strip only the newly added `_REPO_ROOT`/`_SCRIPTS_*_DIR` assignments.
- **E4 [python, MEDIUM]: snapshot R5(c).** Pin R5(c) to a snapshot of the declared dependencies, or report it as a named-allowlist warning, so that a future dependency cannot fail an unrelated slice.
- **LOW**
  - State the R2/R5 file glob explicitly.
  - Re-measure the six-error pin at Stage 0, and say so in the comment.

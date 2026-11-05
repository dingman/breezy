# CF-12-W3 r3: APPROVED (sha e22bc682…)

Scores: python-reviewer 96, architect 96. No CRITICAL or HIGH findings. Three rounds.

Binding build items:
- **MEDIUM (python):** in Stage 0, dry-run the G4b probe at HEAD before any edit. Record that it prints `G4B-OK`, and confirm the `_main_async` signature and flags.
- **LOW:**
  - `import sys` must be a direct child of `Module.body`.
  - State that `test_nbp_skill_study.py` gets no added block, and have the checker assert it.
  - State that `:250` is covered by G2 and the unit, not by the G4b NO-PULL path.
  - Run `mkdir <scratch>/empty` before the probe.
  - Bind each `_SCRIPTS_*_DIR` name to its directory expression.
  - Correct the isort comment at `pyproject.toml:227`.

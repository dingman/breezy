# CF-12-W3 r1 merged review (coordinator)

Scores: python-reviewer 91, architect 90. Neither reviewer raised a CRITICAL or HIGH. Final score 90, so the plan goes to r2.

## Items

**C1 [both reviewers]: triage the possibly-None permit in `trade.py`**
- Do a read-only reachability triage now, inside the plan: can `permit=None` reach the dereferences at `trade.py:1189-1207` on the live boot path? Use codegraph and record the verdict.
- If a site is reachable: W3b becomes HIGH, gets its own row, and is fixed before W3 merges.
- In either case, pin the ceiling with a file-and-line comment, so one new error cannot silently replace a fixed one.

**C2 [both]: basename-uniqueness test, now**
- Cover cross-directory collisions, stdlib names and venv top-level names.
- Have the bootstrap append to `sys.path` rather than `insert(0)`. If it must insert, the same test must assert there are no collisions.

**C3 [architect]: G4 smoke test runs in the worktree**
- Run it as `cd <wt>` with an explicit `PYTHONPATH=<wt>/src`.

**C4 [architect]: claim the runtime-edit carve-out explicitly**
- Cite CF-12 Rev2 `:121`.
- Require AST equality outside the import and bootstrap lines.

## LOW
- Extend R2 to scan `monkeypatch.setattr`/`patch` string literals.
- R1b must fail loudly unless the fixture exits 0 or 1.
- Drive the removal of `unused-ignore` from the mypy report.
- Stale comments:
  - update the test docstring and `pyproject.toml:243-246`;
  - log a deferred doc row for the `breezy-discovery-pull.service:55-66` comment.
- State in §1 that `scripts/` is outside the import-linter `root_packages`.

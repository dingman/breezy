# LESSONS archived 2026-10-20 (prevention now mechanised)

### L-5 — A state document that outgrows re-verification becomes a source of false claims (2026-08-31)
**Mistake:** PROGRESS.md grew to 1401 lines of closed items and restated evidence.
**Prevention:** Keep docs/core/PROGRESS.md to OPEN items under 250 lines / 12 KB (`.claude/hooks/progress-size-gate.sh`), delete items on close, link evidence, consolidate rather than raise the budget, and archive superseded history to docs/core/archive/, never delete it.
**Applied:** 2026-08-31
**Last updated:** 2026-08-31
Enforced by: .claude/hooks/progress-size-gate.sh:6-7 (MAX_LINES/MAX_BYTES; wired in .claude/settings.json:9)

### L-57 — A production-default path that a test can reach will write live state the moment its precondition flips (2026-10-11)
**Mistake:** Pinned producer let a guard test reach the live production factory.
**Prevention:** A host-path production default must refuse unless inside its exact unit name and not under pytest (`"pytest" in sys.modules`); before unlocking any such path, grep `tests/` for un-injected calls and quarantine spurious artefacts by move.
**Applied:** 2026-10-11
**Last updated:** 2026-10-11
Enforced by: src/breezy/analysis/labeling/unit_factory_default.py:101 (raises HostSeamsRefused when _under_pytest(), defined :87-88)

### L-61 — A unit-file change is a whole-tree change; a oneshot is bounded by TimeoutStartSec only (2026-10-16)
**Mistake:** Trigger unit failed seven whole-tree guards: RuntimeMaxSec on a oneshot; TIMER row missing.
**Prevention:** Bound every `Type=oneshot` unit with `TimeoutStartSec` (never `RuntimeMaxSec`); and for ANY unit, timer or `src/breezy/runtime` change, name in the implementer brief and run before merge: `test_truth_units`, `test_autonomy_units_health`, `test_launch_window_table`, `test_autonomy_owner_placeholders`, `test_monitor_watch`, `test_code_identity_pins*`, `test_mypy_ratchet`, `test_runtime_import_isolation` and `test_persistence_import_free` — a re-pin that follows is a reviewed one-line edit, never a skipped test.
**Applied:** 2026-10-16
**Last updated:** 2026-10-16
Enforced by: tests/unit/test_truth_units.py:93 (oneshot must not declare RuntimeMaxSec; see also tests/contract/test_autonomy_units_health.py:99)


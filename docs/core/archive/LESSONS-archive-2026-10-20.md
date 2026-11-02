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


## Absorbed 2026-11-02 (consolidation; original text verbatim)

Absorbed 2026-11-02 into L-6

### L-38 — A stop rule whose counter cannot increment is a missing stop, not a running clock (2026-09-12)
**Mistake:** A KILL counter read 0 for eight days, so the stop could not fire.
**Prevention:** Before citing a stop as active, show its counter can increment (a day that should count does) and that every family's tally receives it; report a stop that cannot fire as MISSING.
**Applied:** 2026-09-12
**Last updated:** 2026-09-12

Absorbed 2026-11-02 into L-29

### L-49 — Low CPU over wall time on a failing unit means a memory ceiling, not a slow job (2026-09-24)
**Mistake:** `MemoryHigh=4G` on a 90G backlog thrashed in reclaim until timeout.
**Prevention:** When CPU/wall is below 0.3, check memory.high throttling (`systemctl --user show -p MemoryHigh,MemoryMax,TimeoutStartSec`) before touching timeouts; size ceilings to the working set; never `read_all()` a one-row-per-message Arrow stream; measure memory as delta RSS in a child process (`ru_maxrss`); and keep downstream inputs off one unbounded run.
**Applied:** 2026-09-24
**Last updated:** 2026-09-26

Absorbed 2026-11-02 into L-16

### L-68 — Nautilus LiveClock callbacks run off the kernel thread; hop before touching thread-confined state (2026-10-24, recorded 2026-10-28)
**Mistake:** A maker timer read the FQ halt veto from the state store inside a LiveClock callback; the off-thread access failed closed and cancelled every rest.
**Prevention:** Every strategy clock callback touching thread-confined state (state store, exec-client latches, caches) goes through the `_on_clock` wrapper that hops onto the kernel loop via `loop.call_soon_threadsafe` (loop captured in `on_start`); any review of a new timer or exec-client state mutation names the thread it runs on; and the first live minutes after a new timer are checked for thread errors.
**Applied:** 2026-10-24
**Last updated:** 2026-10-28

Absorbed 2026-11-02 into L-39

### L-77 — Never allowlist a frequently edited ledger in an exact-set prose guard (2026-11-02)
**Mistake:** docs/core/PROGRESS.md was added to the operator-control prose-census allowlist; a routine ledger edit then removed the only control mention and the binding gate went red on the merged tree.
**Prevention:** Never allowlist a frequently edited ledger (PROGRESS.md, LESSONS.md) in an exact-set prose guard; allowlist only stable plan and review artefacts, and re-run the guard on the MERGED tree before push.
**Applied:** 2026-11-02
**Last updated:** 2026-11-02

Absorbed 2026-11-02 into L-14

### L-19 — Measure a blast radius by SIMULATING the change, not by counting call sites (2026-09-02)
**Mistake:** A hand census was off, and `portfolio.equity or 0.0` type-checked while fabricating.
**Prevention:** Simulate any change to a widely-constructed type's default (monkeypatch it, run the full suite, read every failure), and write out the escape hatch and check it compiles before claiming the type enforces anything.
**Applied:** 2026-09-02
**Last updated:** 2026-09-02


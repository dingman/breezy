"""Runtime wiring: settings, node composition, health/alerting, logging.

**This package `__init__.py` must stay import-free.** ``breezy-study-failed``
(`study_failure_notifier.py`) is the LAST line of alert delivery for a failed
study unit -- see that module's own docstring, "a detector without delivery
is not a control" (`study_failure_notifier.py:55-56`). Importing it, or any
other `breezy.runtime.*` submodule, always runs this file first (ordinary
Python package-import semantics), so an eager import here of
`breezy.runtime.composition` -- which pulls in `nautilus_trader.live.node` --
meant a broken Nautilus install, a missing dependency, or a syntax error
anywhere in that chain also silently killed the alert that was supposed to
report exactly that kind of failure (NOTIFIER-IMPORT-ISOLATION,
2026-09-27).

**Deleted, not made lazy.** An earlier revision of this file re-exported 41
names via a PEP 562 `__getattr__` facade. Peer review (architect, round 1)
found zero callers: no `from breezy.runtime import <name>` and no
`breezy.runtime.<name>` attribute access anywhere in `src/`, `tests/`, or
`scripts/` ever used the facade -- every real call site imports the owning
submodule directly (`from breezy.runtime.health import resolve_alert_sink`,
`from breezy.runtime.composition import build_ingest_node`, etc.). With no
consumer, a lazy `__getattr__`/`_LAZY` mapping would only add a way for
`breezy.runtime.<typo>` to silently resolve to `AttributeError` at the wrong
call site instead of at import time -- deleting the facade is the simpler,
KISS/YAGNI-correct fix.

**Verified safe (Stage 0, D-2 + R3-1 of the plan below).** Every Breezy
`register_arrow(` call sits at module scope in the class's own defining
module (`domain/*.py`, `adapters/polymarket_us/tape_records.py`,
`strategy/current_rung_hold/monitor_records.py`), so any caller that already
holds the class has already triggered its registration independent of this
package's own imports. A `grimp`-based static reachability check (with
synthetic `module -> ancestor package` edges, since `grimp` does not
otherwise model that importing a submodule runs its ancestors' `__init__.py`
first) across every `[project.scripts]` entry, every `deploy/systemd/`
`ExecStart` module, and every `scripts/**/*.py` that imports `breezy.runtime`
found ZERO entries that lose reachability to any `register_arrow` module
once this file's own imports are removed -- corroborated by a fresh-process
`sys.modules` snapshot per entry. See
`docs/plans/backlog/EDGE_2026-09-27/NOTIFIER-IMPORT-ISOLATION_plan_r1_2026-09-27.md`
and its `..._plan_r2_delta_2026-09-27.md` (r3 amendments are binding) for the
full method, and `tests/unit/test_runtime_import_isolation.py` for the tests
this guarantees stay true (T1, T4, T7 pin this file directly; T9 is the
fresh-process import smoke test per entry).

**A missing registration fails LOUDLY, never silently** (verified in the
round-2 peer review): `nautilus_trader.serialization.arrow.serializer`
raises `TypeError` (`:240-247,313-323`) or `KeyError` (`:81-82`) on an
unregistered custom type at catalog read or write time -- there is no silent
degradation path this file's own imports were ever load-bearing for.
"""

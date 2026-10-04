"""AUT-1 WP0 premises, V-15: adapter-free closures; submit_chain.py is not byte-pinned.

Shared helpers live in ``aut1_premises_support`` (WP0-R10).
"""

import ast
import hashlib
from pathlib import Path
from typing import Final

import pytest

from tests.unit.aut1_premises_support import (
    REPO_ROOT,
    SRC_DIR,
    _adapter_modules,
    _fresh_process_modules,
    _module_level_imports,
    static_module_closure,
)

# ---------------------------------------------------------------------------
# V-15  adapter-free closures; submit_chain.py is not byte-pinned
# ---------------------------------------------------------------------------


#: Planned AUT-1 entry-point dependencies that exist today (WP1/WP5 modules do not).
CLEAN_PLANNED_DEPENDENCIES: Final[tuple[str, ...]] = (
    "breezy.domain.forecast_point",
    "breezy.persistence.exit_tags",
    "breezy.runtime.submit_intent",
    "breezy.persistence.nbp_derived_store",
    "breezy.domain.instrument_leg",
)


def test_static_walk_positive_and_negative_controls() -> None:
    """V-15 controls. The walk agrees with a fresh-process ``sys.modules`` import on adapter
    membership for a clean module and for a module known to reach the adapters (33 modules,
    AUT-6 r12 fact 18), so a zero is a measurement.

    MUTATION (red): making ``_module_level_imports`` ignore ``ImportFrom`` drops the adapter
    count of ``trade_supervisor`` to 0 and fails the positive control.
    """
    clean = "breezy.domain.instrument_leg"
    dirty = "breezy.runtime.trade_supervisor"
    assert _adapter_modules(static_module_closure(clean)) == []
    assert [m for m in _fresh_process_modules(clean) if m.startswith("breezy.adapters")] == []
    walked = _adapter_modules(static_module_closure(dirty))
    assert len(walked) == 33
    imported = sorted(m for m in _fresh_process_modules(dirty) if m.startswith("breezy.adapters"))
    assert walked == imported


@pytest.mark.parametrize("entry", CLEAN_PLANNED_DEPENDENCIES)
def test_aut1_entry_point_closures_are_free_of_venue_adapter_modules(entry: str) -> None:
    """V-15. The planned post-move dependencies that exist today reach no ``breezy.adapters.*``
    module and no ``current_rung_hold`` package ``__init__``.

    MUTATION (red): ``breezy.adapters.polymarket_us.exec.submit_chain`` (where
    ``intent_fingerprint`` lives today) has 33 adapter modules, which is why it moves.
    """
    closure = static_module_closure(entry)
    assert _adapter_modules(closure) == []
    assert "breezy.strategy.current_rung_hold" not in closure


def test_forecast_state_closure_is_adapter_free() -> None:
    """V-15, the planned ``capture_forecast_ref.py`` dependency: the closure of
    ``breezy.strategy.ladder_ev.forecast_state`` contains no venue-adapter module. This was a
    strict xfail (33 adapter modules via the ``ladder_ev`` facade) until WP1's first commit
    stripped the facade (WP0-R6); the marker was removed in that commit.

    MUTATION (red): restoring the ``ladder_ev.decision`` import in ``ladder_ev/__init__.py``
    brings back the 33 adapter modules.
    """
    closure = static_module_closure("breezy.strategy.ladder_ev.forecast_state")
    assert _adapter_modules(closure) == []


def test_ladder_ev_package_init_has_no_imports() -> None:
    """V-15 / WP0-R6 (AUT-1 WP1). ``strategy/ladder_ev/__init__.py`` is its docstring plus
    ``__all__: list[str] = []`` (mirroring ``strategy/__init__.py``): no import statement other
    than ``from __future__``. The AST walk is the lint, because grimp has no edge for a package's
    implicit ``__init__``; a facade re-export would drag ``ladder_ev.decision`` ->
    ``current_rung_hold`` -> ``trial_day_latch`` -> the venue adapters into every submodule's
    closure.

    MUTATION (red): restoring the ``ladder_ev.decision`` import in ``__init__`` fails both asserts.
    """
    init = SRC_DIR / "breezy" / "strategy" / "ladder_ev" / "__init__.py"
    tree = ast.parse(init.read_text(encoding="utf-8"))
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        or (isinstance(node, ast.ImportFrom) and node.module != "__future__")
    ]
    assert imports == []
    assert [
        m
        for m in _module_level_imports("breezy.strategy.ladder_ev")
        if m != "__future__" and not m.startswith("__future__.")
    ] == []


def test_forecast_state_closure_no_longer_reaches_adapters_through_ladder_ev_init() -> None:
    """V-15 successor of the pre-WP0-R6 evidence test (which pinned 33 adapter modules reached
    through the ``ladder_ev`` package ``__init__``). Now neither the package ``__init__`` nor
    ``forecast_state`` reaches an adapter module or the ``current_rung_hold`` package.

    MUTATION (red): restoring the ``ladder_ev.decision`` import in ``__init__`` puts 33 adapter
    modules and ``current_rung_hold`` back into both closures.
    """
    for entry in ("breezy.strategy.ladder_ev", "breezy.strategy.ladder_ev.forecast_state"):
        closure = static_module_closure(entry)
        assert _adapter_modules(closure) == [], entry
        assert "breezy.strategy.current_rung_hold" not in closure, entry
    own = _module_level_imports("breezy.strategy.ladder_ev.forecast_state")
    assert not [m for m in own if m.startswith("breezy.adapters")]


def test_submit_chain_is_not_byte_pinned_in_tests() -> None:
    """V-15 second half. No test file carries the sha256 of ``exec/submit_chain.py`` or of the
    source of ``intent_fingerprint``. Positive control: the same scan DOES find
    ``exec/client.py``'s pin. (Other pins exist but are not whole-file or ``intent_fingerprint``
    pins: ``classify_create_order_outcome`` + ``CreateOrderOutcome`` source hash, the firewall
    scans of the file's path, and the callee name ``submit_chain.intent_fingerprint``.)

    MUTATION (red): adding the file's own digest as a literal in a scanned test file makes the
    scan find it (shown on a temporary copy).
    """
    import inspect

    from breezy.adapters.polymarket_us.exec import submit_chain

    exec_dir = SRC_DIR / "breezy" / "adapters" / "polymarket_us" / "exec"
    pins = {
        "submit_chain.py": hashlib.sha256((exec_dir / "submit_chain.py").read_bytes()).hexdigest(),
        "intent_fingerprint": hashlib.sha256(
            inspect.getsource(submit_chain.intent_fingerprint).encode("utf-8")
        ).hexdigest(),
    }
    control = hashlib.sha256((exec_dir / "client.py").read_bytes()).hexdigest()
    hits: dict[str, list[str]] = {key: [] for key in (*pins, "client.py")}
    needles = {**pins, "client.py": control}
    this_file = Path(__file__).resolve()
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        if path.resolve() == this_file:
            continue
        text = path.read_text(encoding="utf-8")
        for key, digest in needles.items():
            if digest in text:
                hits[key].append(str(path.relative_to(REPO_ROOT)))
    assert hits["client.py"], "positive control: the exec client's pin must be findable"
    assert hits["submit_chain.py"] == []
    assert hits["intent_fingerprint"] == []

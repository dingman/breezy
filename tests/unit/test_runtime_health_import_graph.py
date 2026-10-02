"""Import-graph pin for the R1.5 health-model move.

``import breezy.runtime.health`` must stay a re-export. The only ``breezy``
modules it may add, versus a clean interpreter, are the shim, its package,
and ``breezy.registry`` (whose ``__init__`` loads ``sites``). A Nautilus
import here would mean the home stopped being import-light.

Identity is checked in the same child: the shim must hand back the defining
module's objects, not copies. A running process that still imports the old
path has to keep working.
"""

from __future__ import annotations

import subprocess
import sys

_ALLOWED_BREEZY = {
    "breezy",
    "breezy.runtime",
    "breezy.runtime.health",
    "breezy.registry",
    "breezy.registry.sites",
    "breezy.registry.health_model",
}

_IDENTITY_NAMES = (
    "AlertState",
    "GapSummary",
    "HealthSnapshot",
    "AlertPayload",
    "AlertCondition",
    "AlertConditionKey",
    "SiteHealth",
    "emit_alert",
    "resolve_alert_sink",
    "write_snapshot_atomic",
)


def test_importing_runtime_health_adds_only_the_registry_reexport() -> None:
    """Fresh child: the parent's ``sys.modules`` already holds Nautilus."""
    names = ", ".join(repr(name) for name in _IDENTITY_NAMES)
    allowed = ", ".join(repr(name) for name in sorted(_ALLOWED_BREEZY))
    script = f"""
import sys
before = set(sys.modules)
import breezy.runtime.health as shim
import breezy.registry.health_model as model
added_breezy = {{
    m for m in sys.modules
    if m not in before and (m == "breezy" or m.startswith("breezy."))
}}
added_nautilus = {{
    m for m in sys.modules
    if m not in before and (m == "nautilus_trader" or m.startswith("nautilus_trader."))
}}
allowed = {{{allowed}}}
assert added_breezy == allowed, sorted(added_breezy ^ allowed)
assert not added_nautilus, sorted(added_nautilus)
for name in ({names}):
    assert getattr(shim, name) is getattr(model, name), name
print("OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout

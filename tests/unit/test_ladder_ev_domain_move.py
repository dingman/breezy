"""AUT-6 WP5 / M3: ``quantile_density`` and ``location_correction`` live in ``domain/``.

The strategy modules are alias-only: every module-level name of the moved module is the very same
object, so the live FQ family's behaviour is identical by identity (plan r15 section 3.1.2).
"""

from __future__ import annotations

import inspect
import logging
import types

import pytest

from breezy.domain import location_correction as domain_lc
from breezy.domain import quantile_density as domain_qd
from breezy.strategy.ladder_ev import location_correction as strategy_lc
from breezy.strategy.ladder_ev import quantile_density as strategy_qd

_PAIRS = [
    pytest.param(domain_qd, strategy_qd, id="quantile_density"),
    pytest.param(domain_lc, strategy_lc, id="location_correction"),
]


def _own_names(domain: types.ModuleType) -> list[str]:
    """Names the moved module defines itself: classes and functions by ``__module__``, plus its
    module-level constants. Imported modules and foreign objects are not part of the moved API."""
    names: list[str] = []
    for name, obj in vars(domain).items():
        if name.startswith("__") and name.endswith("__"):
            continue
        if inspect.ismodule(obj) or name == "annotations":
            continue
        if inspect.isclass(obj) or inspect.isfunction(obj):
            if getattr(obj, "__module__", None) == domain.__name__:
                names.append(name)
        elif name.lstrip("_").isupper() or name == "_logger":
            names.append(name)
    return names


@pytest.mark.parametrize(("domain", "strategy"), _PAIRS)
def test_strategy_quantile_density_and_location_correction_names_are_the_domain_objects(
    domain: types.ModuleType, strategy: types.ModuleType
) -> None:
    names = _own_names(domain)
    assert names, "the moved module defines nothing: the check is vacuous"
    for name in names:
        assert getattr(strategy, name) is getattr(domain, name), name
    # public API: everything in the moved module's __all__ is re-exported by identity
    for name in domain.__all__:
        assert getattr(strategy, name) is getattr(domain, name), name
    # the moved classes really live in domain/ and the alias modules define nothing of their own
    for name in names:
        obj = getattr(strategy, name)
        if inspect.isclass(obj) or inspect.isfunction(obj):
            assert obj.__module__ == domain.__name__, name
    own = [
        n
        for n, o in vars(strategy).items()
        if (inspect.isclass(o) or inspect.isfunction(o)) and o.__module__ == strategy.__name__
    ]
    assert own == []


def test_moved_quantile_density_keeps_strategy_logger_name() -> None:
    assert domain_qd._logger.name == "breezy.strategy.ladder_ev.quantile_density"
    assert strategy_qd._logger is domain_qd._logger
    assert logging.getLogger("breezy.strategy.ladder_ev.quantile_density") is domain_qd._logger
    # the pure move did NOT rename it to the new module path
    assert domain_qd._logger.name != domain_qd.__name__


def test_domain_modules_import_no_strategy_or_adapter_module() -> None:
    import subprocess
    import sys

    code = (
        "import sys; import breezy.domain.quantile_density, breezy.domain.location_correction;"
        "bad=[m for m in sys.modules if m.startswith(('breezy.strategy','breezy.adapters'))];"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr

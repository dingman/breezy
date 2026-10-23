"""ARM post-B2 MEDIUM: ``generate_order_status_report`` returns ``None`` on ANY read failure
(including a 404), and Nautilus reads ``None`` as "not found at the venue". This module pins the
CONFIGURATION FACT that makes that harmless today, so a change that would make it live fails here.

Finding (installed Nautilus 1.231.0, read with /usr/bin/grep; line numbers are for that wheel):

* The only native callers of the SINGULAR ``generate_order_status_report`` are
  ``live/execution_engine.py:1454`` (inside ``_resolve_order_not_found_at_venue``, which marks an
  ACCEPTED/SUBMITTED order REJECTED and a PARTIALLY_FILLED one CANCELED on ``None``) and
  ``live/execution_client.py:526`` (the BASE ``_query_order``).
* ``_resolve_order_not_found_at_venue`` is reached only from ``_handle_missing_orders_at_venue``
  <- ``_check_orders_consistency`` <- ``_continuous_reconciliation_loop``. That task is scheduled
  (``:383-386``) only when ``inflight_check_interval_ms``, ``open_check_interval_secs`` or
  ``position_check_interval_secs`` is truthy. Breezy's ``LiveExecEngineConfig`` sets the first to 0
  and leaves the other two ``None``, so the loop (and therefore the missing-order path) never runs.
* Startup reconciliation goes through the PLURAL ``generate_order_status_reports`` /
  ``generate_mass_status`` (overridden in the client from the durable ledger), never the singular.
* The Breezy client OVERRIDES ``_query_order`` (a ledger-bound GET-only poll that never calls the
  singular report method nor ``super()``), so the base-class caller is dead code here.

Therefore no native path turns a transient read failure into a terminal order event in this
configuration. If any assertion below fails, enabling that interval (or a Nautilus upgrade that
adds a caller) has made the ``None`` return a false-terminal hazard: change
``generate_order_status_report`` to raise or hold instead of returning ``None`` for a read failure
BEFORE touching these pins.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Final

import nautilus_trader.live as nt_live
import pytest
from nautilus_trader.live.config import LiveExecEngineConfig

from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.runtime.node_config import build_trade_node_config
from tests.unit.test_runtime_trade_node_config import (
    OPERATOR_ORDER_CEILING_USD,
    make_data_client_config,
    make_exec_client_config,
    make_trade_settings,
)

LIVE_DIR: Final[Path] = Path(nt_live.__file__).resolve().parent
SINGULAR: Final = "generate_order_status_report"
CLIENT_SOURCE: Final[Path] = (
    Path(__file__).resolve().parents[2] / "src/breezy/adapters/polymarket_us/exec/client.py"
)


def _enclosing_callers(path: Path, callee: str) -> set[str]:
    """Names of the functions in ``path`` whose body calls ``<x>.callee(...)``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == callee
            ):
                found.add(fn.name)
    return found


def test_the_only_native_callers_of_the_singular_status_report_are_the_two_known_ones() -> None:
    engine = _enclosing_callers(LIVE_DIR / "execution_engine.py", SINGULAR)
    client = _enclosing_callers(LIVE_DIR / "execution_client.py", SINGULAR)
    assert engine == {"_resolve_order_not_found_at_venue"}
    assert client == {"_query_order"}


def test_the_missing_order_path_is_reachable_only_through_the_continuous_reconciliation_loop() -> (
    None
):
    path = LIVE_DIR / "execution_engine.py"
    chain = [
        ("_resolve_order_not_found_at_venue", {"_handle_missing_orders_at_venue"}),
        ("_handle_missing_orders_at_venue", {"_check_orders_consistency"}),
        ("_check_orders_consistency", {"_continuous_reconciliation_loop"}),
    ]
    for callee, callers in chain:
        assert _enclosing_callers(path, callee) == callers, callee


def _loop_would_be_scheduled(engine: LiveExecEngineConfig) -> bool:
    """The `or` at live/execution_engine.py:383-386, evaluated on a config."""
    return bool(
        engine.inflight_check_interval_ms
        or engine.open_check_interval_secs
        or engine.position_check_interval_secs
    )


def test_the_continuous_reconciliation_task_is_never_scheduled_by_the_trade_node_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # test-local stand-in for the builder's fail-closed per-order ceiling env (not an operator cap)
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, OPERATOR_ORDER_CEILING_USD)
    config = build_trade_node_config(
        make_trade_settings(), make_data_client_config(), make_exec_client_config()
    )
    assert config.exec_engine is not None
    assert _loop_would_be_scheduled(config.exec_engine) is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"inflight_check_interval_ms": 5000},
        {"open_check_interval_secs": 60.0},
        {"position_check_interval_secs": 60.0},
    ],
)
def test_the_scheduling_predicate_trips_when_any_interval_is_enabled(
    overrides: dict[str, Any],
) -> None:
    """Mutation evidence: each of the three intervals alone flips the pin's predicate."""
    assert _loop_would_be_scheduled(
        LiveExecEngineConfig(**{"inflight_check_interval_ms": 0, **overrides})
    )


def test_the_client_overrides_query_order_without_the_singular_report_or_super() -> None:
    tree = ast.parse(CLIENT_SOURCE.read_text(encoding="utf-8"))
    overrides = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_query_order"
    ]
    assert len(overrides) == 1, "the base _query_order calls the singular report"
    called = {
        n.func.attr
        for n in ast.walk(overrides[0])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert SINGULAR not in called
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "super"
        for n in ast.walk(overrides[0])
    )


def test_the_scan_is_not_vacuous_it_finds_a_planted_caller(tmp_path: Path) -> None:
    planted = tmp_path / "x.py"
    planted.write_text(
        "async def sneaky(c):\n    return await c.generate_order_status_report(1)\n",
        encoding="utf-8",
    )
    assert _enclosing_callers(planted, SINGULAR) == {"sneaky"}

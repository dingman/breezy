"""Seam contract: every weather strategy subscribes to the ONE real weather feed.

The defect this pins (measured, not assumed). The operator's strategy bundles
each defined their own ``NWSForecastUpdate`` / ``NWSObservation`` custom data
types and subscribed on topics ``NWSForecastUpdate*`` / ``NWSObservation*``,
with ``nws_client_id`` defaulting to the string ``"NWS"``. Breezy publishes
``NwsClimateDay*`` on ``ClientId("BREEZY-NWS")``. Both halves are broken
independently, and NEITHER raises:

* ``is_matching_py("NwsClimateDay*", "NWSObservation*")`` is ``False`` -- the
  subscriber receives ZERO records.
* a ``client_id`` mismatch makes ``DataEngine._execute_command`` drop the
  ``SubscribeData`` command with one ERROR log line, and the run completes
  looking healthy.

So a strategy wired the bundle's way trades on no weather data at all while
every test that only checks ``DataType`` EQUALITY still passes -- ``__eq__``
compares a ``frozenset`` while ``topic`` is built by insertion order (see
``tests/unit/test_weather_data_type_barrier.py``).

This module therefore asserts the two halves at the level they actually
break: topic MATCHING (not equality) against the real publisher, and the
call-site shape of ``subscribe_data`` in each strategy module -- the shared
factory and the shared ``ClientId`` constant BY NAME, never a literal.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from nautilus_trader.common.component import is_matching_py

from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID

#: Every Nautilus-facing weather strategy module that subscribes to the feed.
STRATEGY_MODULES = (
    "src/breezy/strategy/forecast_mispricing/strategy.py",
    "src/breezy/strategy/calibration_mean_reversion/strategy.py",
    "src/breezy/strategy/forecast_revision/strategy.py",
)

#: The topics the bundles used, kept here so the regression stays named.
BUNDLE_TOPICS = ("NWSForecastUpdate*", "NWSObservation*")


def _subscribe_data_calls(path: str) -> list[ast.Call]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "subscribe_data"
    ]


def test_publisher_topic_does_not_match_the_bundles_topics() -> None:
    """Non-vacuity: prove the bundle's seam really is broken."""
    publisher = nws_climate_day_data_type().topic
    for bundle_topic in BUNDLE_TOPICS:
        assert not is_matching_py(publisher, bundle_topic), (
            f"{bundle_topic!r} unexpectedly matches {publisher!r}"
        )


def test_shared_factory_topic_matches_the_publisher() -> None:
    topic = nws_climate_day_data_type().topic
    assert is_matching_py(topic, topic)
    assert topic == "NwsClimateDay*"


@pytest.mark.parametrize("path", STRATEGY_MODULES)
def test_strategy_subscribes_via_the_shared_factory_and_client_id(path: str) -> None:
    calls = _subscribe_data_calls(path)
    assert calls, f"{path} makes no subscribe_data call"
    for call in calls:
        assert isinstance(call.args[0], ast.Call), f"{path}: data_type is not a factory call"
        assert isinstance(call.args[0].func, ast.Name)
        assert call.args[0].func.id == "nws_climate_day_data_type", (
            f"{path}: subscribes with {ast.dump(call.args[0])} rather than the shared factory"
        )
        client_ids = [kw for kw in call.keywords if kw.arg == "client_id"]
        assert client_ids, f"{path}: subscribe_data has no client_id (command is dropped silently)"
        value = client_ids[0].value
        assert isinstance(value, ast.Name), f"{path}: client_id must be the shared constant"
        assert value.id == "NWS_BACKTEST_CLIENT_ID", (
            f"{path}: client_id is {value.id!r}, not the shared NWS_BACKTEST_CLIENT_ID"
        )


def _non_docstring_str_constants(tree: ast.Module) -> list[str]:
    """Every string literal in EXECUTABLE code, excluding docstrings.

    The docstrings in these modules necessarily quote the wrong client ids in
    order to explain the defect being pinned, so a plain substring scan would
    fail on the documentation instead of on the code.
    """
    docstring_ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstring_ids.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_ids
    ]


@pytest.mark.parametrize("path", STRATEGY_MODULES)
def test_strategy_module_names_no_weather_client_id_literal(path: str) -> None:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    literals = _non_docstring_str_constants(tree)
    forbidden = {"NWS", str(NWS_BACKTEST_CLIENT_ID)}
    offenders = sorted(set(literals) & forbidden)
    assert not offenders, (
        f"{path} carries weather client id(s) {offenders} as literals in code "
        "rather than importing NWS_BACKTEST_CLIENT_ID"
    )

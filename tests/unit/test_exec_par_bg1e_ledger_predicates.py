"""EXEC-PAR BG-1e: value-free aggregate predicates on ``DailySpendLedger`` (K6).

Aggregates and a budget fraction in, ``bool`` out. No cap value is returned,
logged, or placed in an exception message; an absent control raises a typed
error and nothing defaults.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest

from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    DailySpendLedger,
)
from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
from breezy.runtime.breaker_watcher import LedgerPredicatePort
from tests.unit.operator_control_env import operator_control_env, operator_control_unset

D = Decimal
BUDGET = "100.00"
# Strings that would betray the budget or a derived limit in any message/log.
LEAKS = ("100", "15.00", "25.00", "40.00", "0.15", "0.25")


@contextmanager
def budgeted() -> Iterator[DailySpendLedger]:
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, BUDGET):
        yield DailySpendLedger()


def pnl(ledger: DailySpendLedger, value: Any, fraction: Any) -> bool:
    return ledger.pnl_breaches_budget_fraction(aggregate_pnl=value, fraction=fraction)


def open_cost(ledger: DailySpendLedger, value: Any, fraction: Any) -> bool:
    return ledger.open_cost_exceeds_budget_fraction(
        aggregate_open_cost=value,
        fraction=fraction,
    )


# ---------------------------------------------------------------- P&L stop
@pytest.mark.parametrize("fraction,limit", [("0.15", "15"), ("0.40", "40"), ("1.0", "100")])
def test_pnl_stop_boundaries_equal_just_over_just_under(fraction: str, limit: str) -> None:
    with budgeted() as ledger:
        f = D(fraction)
        assert pnl(ledger, D(f"-{limit}"), f) is True  # equal: <= trips
        assert pnl(ledger, D(f"-{limit}.01"), f) is True  # just over
        assert pnl(ledger, D(f"-{limit}") + D("0.01"), f) is False  # just under


def test_pnl_zero_and_positive_never_trip() -> None:
    with budgeted() as ledger:
        assert pnl(ledger, D(0), D("0.15")) is False
        assert pnl(ledger, D("-0"), D("0.15")) is False
        assert pnl(ledger, D("500"), D("1.0")) is False


def test_pnl_decimal_precision_is_exact() -> None:
    with budgeted() as ledger:
        assert pnl(ledger, D("-15.000000000000000000001"), D("0.15")) is True
        assert pnl(ledger, D("-14.999999999999999999999"), D("0.15")) is False


# ------------------------------------------------------ station-day open cost
def test_open_cost_boundaries_strictly_greater() -> None:
    with budgeted() as ledger:
        f = D("0.25")
        assert open_cost(ledger, D("25.00"), f) is False  # equal: not over
        assert open_cost(ledger, D("25.01"), f) is True
        assert open_cost(ledger, D("24.99"), f) is False


def test_open_cost_zero_is_false_negative_is_typed_error() -> None:
    with budgeted() as ledger:
        assert open_cost(ledger, D(0), D("0.25")) is False
        with pytest.raises(LiveTradingPermissionError):
            open_cost(ledger, D("-0.01"), D("0.25"))


def test_open_cost_decimal_precision_is_exact() -> None:
    with budgeted() as ledger:
        assert open_cost(ledger, D("25.000000000000000000001"), D("0.25")) is True
        assert open_cost(ledger, D("24.999999999999999999999"), D("0.25")) is False


# ----------------------------------------------------------- input rejection
@pytest.mark.parametrize("fraction", [D(0), D("-0.1"), D("1.01"), D("NaN"), D("Infinity")])
def test_bad_fraction_raises_typed_error(fraction: Decimal) -> None:
    with budgeted() as ledger:
        with pytest.raises(LiveTradingPermissionError):
            pnl(ledger, D("-1"), fraction)
        with pytest.raises(LiveTradingPermissionError):
            open_cost(ledger, D("1"), fraction)


@pytest.mark.parametrize("bad", [0.5, 1, "1", None, True, D("NaN"), D("Infinity")])
def test_non_decimal_or_non_finite_aggregate_raises_typed_error(bad: Any) -> None:
    with budgeted() as ledger:
        with pytest.raises(LiveTradingPermissionError):
            pnl(ledger, bad, D("0.15"))
        with pytest.raises(LiveTradingPermissionError):
            open_cost(ledger, bad, D("0.25"))


def test_non_decimal_fraction_raises_typed_error() -> None:
    with budgeted() as ledger:
        with pytest.raises(LiveTradingPermissionError):
            pnl(ledger, D("-1"), 0.15)
        with pytest.raises(LiveTradingPermissionError):
            open_cost(ledger, D("1"), "0.25")


# ------------------------------------------------------------ absent budget
def test_missing_budget_raises_typed_error_and_never_defaults() -> None:
    with operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR):
        ledger = DailySpendLedger()
        with pytest.raises(LiveTradingPermissionError) as pnl_exc:
            pnl(ledger, D("-1000000"), D("0.15"))
        with pytest.raises(LiveTradingPermissionError) as cost_exc:
            open_cost(ledger, D("1000000"), D("0.25"))
    for exc in (pnl_exc.value, cost_exc.value):
        assert MAX_DAILY_BUDGET_USD_ENV_VAR in str(exc)


def test_blank_budget_raises_typed_error() -> None:
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "  "),
        pytest.raises(LiveTradingPermissionError),
    ):
        pnl(DailySpendLedger(), D("-1"), D("0.15"))


# --------------------------------------------------- value-free: msgs & logs
def test_return_values_are_plain_bool() -> None:
    with budgeted() as ledger:
        for result in (
            pnl(ledger, D("-20"), D("0.15")),
            pnl(ledger, D("1"), D("0.15")),
            open_cost(ledger, D("30"), D("0.25")),
            open_cost(ledger, D("1"), D("0.25")),
        ):
            assert type(result) is bool


def test_no_cap_value_in_exception_messages_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    messages: list[str] = []
    with budgeted() as ledger:
        pnl(ledger, D("-50"), D("0.15"))
        open_cost(ledger, D("50"), D("0.25"))
        bad_calls: list[tuple[Callable[[DailySpendLedger, Any, Any], bool], Any, Any]] = [
            (pnl, D("NaN"), D("0.15")),
            (pnl, D("-1"), D("1.01")),
            (open_cost, D("-1"), D("0.25")),
            (open_cost, 1.5, D("0.25")),
        ]
        for fn, value, fraction in bad_calls:
            with pytest.raises(LiveTradingPermissionError) as exc:
                fn(ledger, value, fraction)
            messages.append(str(exc.value))
    with operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR):
        with pytest.raises(LiveTradingPermissionError) as exc:
            pnl(DailySpendLedger(), D("-1"), D("0.15"))
        messages.append(str(exc.value))
    texts = messages + [r.getMessage() for r in caplog.records]
    for text in texts:
        for leak in LEAKS:
            assert leak not in text, (leak, text)


# --------------------------------------------------------- port conformance
def test_ledger_satisfies_the_runtime_port_structurally() -> None:
    port_methods = {
        n
        for n, _ in inspect.getmembers(LedgerPredicatePort, inspect.isfunction)
        if not n.startswith("_")
    }
    assert port_methods == {"pnl_breaches_budget_fraction", "open_cost_exceeds_budget_fraction"}
    for name in port_methods:
        port_sig = inspect.signature(getattr(LedgerPredicatePort, name))
        impl_sig = inspect.signature(getattr(DailySpendLedger, name))
        assert list(port_sig.parameters) == list(impl_sig.parameters), name
        assert [p.kind for p in port_sig.parameters.values()] == [
            p.kind for p in impl_sig.parameters.values()
        ], name
    port: LedgerPredicatePort = DailySpendLedger()
    assert port is not None


def test_adapter_module_does_not_import_runtime() -> None:
    import ast
    from pathlib import Path

    from breezy.adapters.polymarket_us import operator_controls

    tree = ast.parse(Path(operator_controls.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("breezy.runtime"), node.module
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("breezy.runtime") for a in node.names)

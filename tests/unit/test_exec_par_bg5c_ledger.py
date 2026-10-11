"""EXEC-PAR BG-5c WP-A (amendment A1): ledger injection through the exec factory.

``exec/client.py`` is byte-pinned, so the ledger the client admits against is
handed in through an optional factory config field (the ``submit_intent_latch``
precedent), and a read-only ``SpendLedgerView`` plus an identity check expose it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import msgspec
import pytest

from breezy.adapters.polymarket_us import factories
from breezy.adapters.polymarket_us.operator_controls import (
    DailySpendLedger,
    LedgerUnavailable,
    SpendLedgerView,
    ledger_view_or_fail,
)
from breezy.runtime.node_config import (
    BREAKER_OPEN_AMBIGUOUS_FRACTION,
    OPEN_EXPOSURE_BOUND_FRACTION,
)
from breezy.runtime.settings import SettingsError
from tests.unit.test_polymarket_us_factories import (  # noqa: F401 -- fixtures
    _clear_shared_polymarket_us_caches,
    build_exec_client,
    make_exec_config,
    wired,
)


def test_spend_ledger_for_is_public_and_k1_builds_the_unbounded_ledger() -> None:
    config = make_exec_config(Path("/tmp/unused-bg5c"))
    ledger = factories.spend_ledger_for(config)
    assert type(ledger) is DailySpendLedger
    assert ledger._f_adm is None and ledger._f_breaker is None


def test_spend_ledger_for_k_gt_1_carries_the_config_fractions() -> None:
    config = make_exec_config(
        Path("/tmp/unused-bg5c"),
        max_concurrent_intents=2,
        open_exposure_bound_fraction=OPEN_EXPOSURE_BOUND_FRACTION,
        breaker_open_ambiguous_fraction=BREAKER_OPEN_AMBIGUOUS_FRACTION,
    )
    ledger = factories.spend_ledger_for(config)
    assert ledger._f_adm == OPEN_EXPOSURE_BOUND_FRACTION
    assert ledger._f_breaker == BREAKER_OPEN_AMBIGUOUS_FRACTION


def test_config_spend_ledger_defaults_to_none() -> None:
    assert make_exec_config(Path("/tmp/unused-bg5c")).spend_ledger is None


@pytest.mark.usefixtures("wired")
def test_without_injection_the_client_ledger_is_the_k1_one_built_today(tmp_path: Path) -> None:
    client = build_exec_client(make_exec_config(tmp_path))
    ledger = client._ledger
    assert type(ledger) is DailySpendLedger
    assert ledger._f_adm is None and ledger._f_breaker is None
    assert ledger._open == {}


@pytest.mark.usefixtures("wired")
def test_without_injection_each_client_gets_its_own_fresh_ledger(tmp_path: Path) -> None:
    config = make_exec_config(tmp_path)
    assert build_exec_client(config)._ledger is not build_exec_client(config)._ledger


@pytest.mark.usefixtures("wired")
def test_an_injected_ledger_is_the_very_object_the_client_admits_against(tmp_path: Path) -> None:
    injected = DailySpendLedger()
    client = build_exec_client(make_exec_config(tmp_path, spend_ledger=injected))
    assert client._ledger is injected


@pytest.mark.usefixtures("wired")
def test_an_injected_k_gt_1_ledger_is_not_rebuilt(tmp_path: Path) -> None:
    config = make_exec_config(
        tmp_path,
        max_concurrent_intents=2,
        open_exposure_bound_fraction=OPEN_EXPOSURE_BOUND_FRACTION,
        breaker_open_ambiguous_fraction=BREAKER_OPEN_AMBIGUOUS_FRACTION,
    )
    built = factories.spend_ledger_for(config)
    with_ledger = msgspec.structs.replace(config, spend_ledger=built)
    assert build_exec_client(with_ledger)._ledger is built


@pytest.mark.usefixtures("wired")
def test_the_factory_refuses_a_non_ledger_spend_ledger(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="spend_ledger"):
        build_exec_client(make_exec_config(tmp_path, spend_ledger=object()))


def test_view_or_fail_returns_the_identical_instance() -> None:
    ledger = DailySpendLedger()
    assert ledger_view_or_fail(ledger, ledger) is ledger


def test_view_or_fail_rejects_a_non_identical_equal_looking_ledger() -> None:
    with pytest.raises(LedgerUnavailable):
        ledger_view_or_fail(DailySpendLedger(), DailySpendLedger())


@pytest.mark.parametrize("view", [None, object(), "ledger"])
def test_view_or_fail_rejects_a_missing_or_foreign_view(view: object) -> None:
    with pytest.raises(LedgerUnavailable):
        ledger_view_or_fail(view, DailySpendLedger())


def test_view_or_fail_rejects_when_the_expected_instance_is_absent() -> None:
    with pytest.raises(LedgerUnavailable):
        ledger_view_or_fail(DailySpendLedger(), None)


def test_ledger_unavailable_is_a_typed_error_with_the_fail_reason() -> None:
    assert issubclass(LedgerUnavailable, Exception)
    assert LedgerUnavailable.reason == "ledger_unavailable"


def test_daily_spend_ledger_structurally_conforms_to_the_view() -> None:
    assert isinstance(DailySpendLedger(), SpendLedgerView)


def test_a_partial_object_does_not_conform_to_the_view() -> None:
    class Partial:
        def spent_today_usd(self, *, now_ns: int) -> Decimal:
            return Decimal(0)

    assert not isinstance(Partial(), SpendLedgerView)


def test_the_view_exposes_no_mutating_surface() -> None:
    members = {n for n in vars(SpendLedgerView) if not n.startswith("_")}
    assert members == {
        "spent_today_usd",
        "cost_budget_bucket",
        "pnl_breaches_budget_fraction",
        "open_cost_exceeds_budget_fraction",
    }

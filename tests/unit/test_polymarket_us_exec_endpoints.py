"""R-3: the private-endpoint decode, and the balances -> ``AccountBalance`` map.

Authority: ``docs/plans/EXEC_SPINE_2026-09-01.md`` section R-3. This suite is
READ/MAP ONLY -- nothing here submits, cancels, or contacts a venue.

WHAT IS PINNED, AND WHY EACH PIN EXISTS
---------------------------------------

* **The decode.** ``UserBalance``
  (``docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/account.py``)
  types every money field as a bare ``float``, so the venue sends them as bare
  JSON number literals. ``json.loads`` without ``parse_float`` binds each one
  to a binary ``float`` and the JSON literal is gone -- irrecoverably so once
  it needs more precision than a ``float`` carries. ``Amount``
  (``types/common.py:6-10``) is a decimal STRING and is unaffected; the bare
  float path is the whole gap, and ``parse_float=Decimal`` closes it.

* **Refusal, never coercion, never a default.** A missing required field, a
  non-USD balance, or a money value that will not survive ``Money``'s currency
  precision all raise. ``Money(Decimal("0.3125"), USD)`` silently returns
  ``Money(0.31, USD)`` -- measured -- so the refusal is in Breezy, ahead of the
  native constructor.

* **Nothing private is ever echoed.** ``endpoints.py`` promises that only a
  body's SIZE is named, never its content. The balances mapper is held to the
  same rule: its refusals name the FIELDS, because ``currentBalance`` and
  ``buyingPower`` are the operator's money and R-4 attaches a logger to exactly
  this path.

The report TYPES are native and are used unwrapped: ``OrderStatusReport``,
``FillReport``, ``PositionStatusReport``, ``ExecutionMassStatus``
(``nautilus_trader/execution/reports.py:95,619,859,1038``). Breezy defines no
parallel report class and this suite asserts that it does not.

Siblings: the order and fill mappers are in
``test_polymarket_us_exec_reports.py``, the position mapper in
``test_polymarket_us_exec_positions.py``, and the allowlists' drift check
against the SDK snapshot in ``test_polymarket_us_exec_snapshot_drift.py``.
Shared payload shapes live in ``polymarket_us_exec_shapes.py``.
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal

import pytest
from nautilus_trader.execution.reports import (
    ExecutionMassStatus,
    FillReport,
    OrderStatusReport,
    PositionStatusReport,
)
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import AccountBalance, Money

from breezy.adapters.polymarket_us.errors import (
    ExecutionReportMappingError,
    PolymarketUSError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
    PRIVATE_READ_PATHS,
    PRIVATE_READ_QUOTA_KEY,
    decode_private_payload,
)
from breezy.adapters.polymarket_us.exec.reports import parse_account_balances
from breezy.adapters.polymarket_us.transport import PERMITTED_QUOTA_KEYS
from tests.unit.polymarket_us_exec_shapes import (
    EXEC_DIR,
    EXEC_MODULES,
    TS_EVENT_TEXT,
    balances_body,
)

# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", EXEC_MODULES)
def test_module_contains_no_float_call(module_name: str) -> None:
    """Same structural pin as the parsing modules: money never meets ``float``."""
    tree = ast.parse((EXEC_DIR / module_name).read_text(encoding="utf-8"))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "float"
    ]
    assert offenders == []


def test_breezy_defines_no_parallel_report_class() -> None:
    """Breezy supplies MAPPING ONLY; the report types stay native."""
    native = (OrderStatusReport, FillReport, PositionStatusReport, ExecutionMassStatus)
    for module_name in EXEC_MODULES:
        tree = ast.parse((EXEC_DIR / module_name).read_text(encoding="utf-8"))
        defined = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        }
        assert defined & {cls.__name__ for cls in native} == set()


def test_private_read_paths_are_budgeted_and_declared() -> None:
    assert ACCOUNT_BALANCES_PATH in PRIVATE_READ_PATHS
    assert PORTFOLIO_POSITIONS_PATH in PRIVATE_READ_PATHS
    assert PRIVATE_READ_QUOTA_KEY in PERMITTED_QUOTA_KEYS


# ---------------------------------------------------------------------------
# The decode -- the headline defect
# ---------------------------------------------------------------------------


def test_balance_decode_preserves_decimal_literal() -> None:
    """``0.1`` must NOT become ``0.1000000000000000055...``."""
    payload = decode_private_payload(balances_body("0.1"), context="balances")

    value = payload["balances"][0]["currentBalance"]

    assert isinstance(value, Decimal)
    assert not isinstance(value, float)
    assert value == Decimal("0.1")
    assert str(value) == "0.1"


def test_bare_json_decode_damages_the_literal_this_decoder_preserves() -> None:
    """Non-vacuity: the shipped bare decode really does lose the literal.

    Two distinct losses are shown. ``0.1`` binds to a binary ``float`` whose
    exact value is not one tenth, and a literal carrying more significant
    digits than a ``float`` holds is silently rewritten to a different number.
    """
    literal = "12345678901234567.89"

    damaged = json.loads(balances_body(literal))["balances"][0]["currentBalance"]
    preserved = decode_private_payload(balances_body(literal), context="balances")[
        "balances"
    ][0]["currentBalance"]

    assert isinstance(damaged, float)
    assert Decimal(damaged) != Decimal(literal)
    assert preserved == Decimal(literal)

    assert Decimal(json.loads(balances_body("0.1"))["balances"][0]["currentBalance"]) != (
        Decimal("0.1")
    )


def test_decode_refuses_a_non_object_body() -> None:
    with pytest.raises(VenuePayloadError):
        decode_private_payload(b"[1, 2, 3]", context="balances")


def test_decode_refuses_a_body_that_is_not_json() -> None:
    with pytest.raises(VenuePayloadError):
        decode_private_payload(b"<html>nope</html>", context="balances")


def test_decode_error_withholds_the_body() -> None:
    """A private-endpoint body carries the portfolio; it never reaches a log."""
    with pytest.raises(PolymarketUSError) as excinfo:
        decode_private_payload(b'{"currentBalance": 4242.42', context="balances")
    assert "4242.42" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Balances -> native AccountBalance
# ---------------------------------------------------------------------------


def test_account_balances_round_trip() -> None:
    payload = decode_private_payload(balances_body("12.34"), context="balances")

    balances = parse_account_balances(payload)

    assert balances == (
        AccountBalance(
            total=Money(Decimal("12.34"), USD),
            locked=Money(Decimal("0.00"), USD),
            free=Money(Decimal("12.34"), USD),
        ),
    )
    assert balances[0].currency == USD


def test_account_balance_locked_is_derived_not_guessed() -> None:
    payload = {
        "balances": [
            {"currency": "USD", "currentBalance": Decimal("12.34"), "buyingPower": Decimal("10.00")}
        ]
    }

    (balance,) = parse_account_balances(payload)

    assert balance.total == Money(Decimal("12.34"), USD)
    assert balance.free == Money(Decimal("10.00"), USD)
    assert balance.locked == Money(Decimal("2.34"), USD)


def test_non_usd_balance_is_refused() -> None:
    payload = {
        "balances": [
            {"currency": "EUR", "currentBalance": Decimal("1.00"), "buyingPower": Decimal("1.00")}
        ]
    }

    with pytest.raises(ExecutionReportMappingError, match="EUR"):
        parse_account_balances(payload)


def test_balance_without_a_currency_is_refused_not_assumed_usd() -> None:
    payload = {"balances": [{"currentBalance": Decimal("1.00"), "buyingPower": Decimal("1.00")}]}

    with pytest.raises(ExecutionReportMappingError):
        parse_account_balances(payload)


def test_balance_missing_a_money_field_is_refused_not_defaulted() -> None:
    payload = {"balances": [{"currency": "USD", "currentBalance": Decimal("1.00")}]}

    with pytest.raises(ExecutionReportMappingError, match="buyingPower"):
        parse_account_balances(payload)


def test_buying_power_above_the_total_balance_is_refused() -> None:
    """A negative ``locked`` is a shape we have never observed; do not invent one."""
    payload = {
        "balances": [
            {"currency": "USD", "currentBalance": Decimal("1.00"), "buyingPower": Decimal("2.00")}
        ]
    }

    with pytest.raises(ExecutionReportMappingError):
        parse_account_balances(payload)


def test_sub_cent_balance_is_quantized_down_not_refused() -> None:
    """R-4 correction 2026-09-04: the venue now reports sub-cent balances.

    ``currentBalance``/``buyingPower`` are Nautilus portfolio bookkeeping, not
    an observation or a price, so they are quantized to ``USD.precision``
    with ``ROUND_DOWN`` at construction rather than refused -- unlike the
    price guard, which stays strict (see
    ``test_polymarket_us_exec_reports.py::test_sub_tick_avg_px_is_refused_rather_than_silently_rounded``).
    """
    payload = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("100.123456"),
                "buyingPower": Decimal("50.999999"),
            }
        ]
    }

    (balance,) = parse_account_balances(payload)

    assert balance.total == Money(Decimal("100.12"), USD)
    assert balance.free == Money(Decimal("50.99"), USD)
    assert balance.locked == balance.total - balance.free
    assert balance.locked.as_decimal() >= 0


def test_sub_cent_balance_locked_is_derived_after_quantization() -> None:
    payload = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("100.123456"),
                "buyingPower": Decimal("50.999999"),
            }
        ]
    }

    (balance,) = parse_account_balances(payload)

    assert balance.locked == Money(Decimal("49.13"), USD)


def test_sub_cent_balance_rounds_toward_zero_not_half_even() -> None:
    """``100.005`` at precision 2 ROUND_DOWN is ``100.00``, not ``100.01``."""
    payload = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("100.005"),
                "buyingPower": Decimal("100.005"),
            }
        ]
    }

    (balance,) = parse_account_balances(payload)

    assert balance.total == Money(Decimal("100.00"), USD)
    assert balance.free == Money(Decimal("100.00"), USD)


def test_exact_cent_balances_are_unchanged_by_quantization() -> None:
    payload = {
        "balances": [
            {"currency": "USD", "currentBalance": Decimal("12.34"), "buyingPower": Decimal("10.00")}
        ]
    }

    (balance,) = parse_account_balances(payload)

    assert balance.total == Money(Decimal("12.34"), USD)
    assert balance.free == Money(Decimal("10.00"), USD)
    assert balance.locked == Money(Decimal("2.34"), USD)


def test_buying_power_that_only_exceeds_total_after_quantization_is_refused() -> None:
    """A sub-cent overage that rounds into an apparent negative encumbrance
    still hits the existing negative-encumbrance refusal, unchanged."""
    payload = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("1.001"),
                "buyingPower": Decimal("1.019"),
            }
        ]
    }

    with pytest.raises(ExecutionReportMappingError):
        parse_account_balances(payload)


def test_balance_quantization_logs_one_record_with_only_the_count(caplog) -> None:
    payload = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("100.123456"),
                "buyingPower": Decimal("50.999999"),
            }
        ]
    }

    with caplog.at_level("INFO"):
        parse_account_balances(payload)

    records = [r for r in caplog.records if "non-exact" in r.getMessage().lower()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "2" in message
    for leaked in ("100.123456", "50.999999", "100.12", "50.99", "currentBalance", "buyingPower"):
        assert leaked not in message


def test_balance_quantization_does_not_log_when_already_exact(caplog) -> None:
    payload = {
        "balances": [
            {"currency": "USD", "currentBalance": Decimal("12.34"), "buyingPower": Decimal("10.00")}
        ]
    }

    with caplog.at_level("INFO"):
        parse_account_balances(payload)

    records = [r for r in caplog.records if "non-exact" in r.getMessage().lower()]
    assert records == []


def test_empty_balances_list_is_refused() -> None:
    with pytest.raises(ExecutionReportMappingError):
        parse_account_balances({"balances": []})


def test_unknown_balance_key_is_refused() -> None:
    payload = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("1.00"),
                "buyingPower": Decimal("1.00"),
                "collateralHaircut": Decimal("0.25"),
            }
        ]
    }

    with pytest.raises(ExecutionReportMappingError, match="collateralHaircut"):
        parse_account_balances(payload)


def test_drifted_balance_six_unread_fields_are_accepted_money_unchanged() -> None:
    """BALANCES_SHAPE_DRIFT_2026-09-04: the six new fields are accepted, and
    the money fields reconciliation actually reads are unaffected by them.
    """
    pre_drift = {
        "balances": [
            {"currency": "USD", "currentBalance": Decimal("12.34"), "buyingPower": Decimal("10.00")}
        ]
    }
    drifted = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("12.34"),
                "buyingPower": Decimal("10.00"),
                "availableToWithdraw": Decimal("10.00"),
                "bonusReservation": Decimal(0),
                "depositReservation": Decimal(0),
                "displayedAvailableSoon": Decimal(0),
                "displayedBonus": Decimal(0),
                "displayedCash": Decimal("12.34"),
            }
        ]
    }

    assert parse_account_balances(drifted) == parse_account_balances(pre_drift)


def test_a_seventh_unknown_field_still_refuses_even_alongside_the_six() -> None:
    """The six-name widening is exact -- a genuinely new, unpinned field is
    still refused, even when it arrives alongside the six already allowed.
    """
    payload = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("1.00"),
                "buyingPower": Decimal("1.00"),
                "availableToWithdraw": Decimal("1.00"),
                "someFutureField": Decimal("0.01"),
            }
        ]
    }

    with pytest.raises(ExecutionReportMappingError, match="someFutureField"):
        parse_account_balances(payload)


def test_balance_refusal_names_the_fields_not_the_operator_s_money() -> None:
    """``endpoints.py`` promises a private body is never echoed. Same rule here."""
    payload = {
        "balances": [
            {
                "currency": "USD",
                "currentBalance": Decimal("100.00"),
                "buyingPower": Decimal("250.00"),
                "lastUpdated": TS_EVENT_TEXT,
            }
        ]
    }

    with pytest.raises(ExecutionReportMappingError) as excinfo:
        parse_account_balances(payload)

    message = str(excinfo.value)
    assert "buyingPower" in message
    assert "currentBalance" in message
    assert "100.00" not in message
    assert "250.00" not in message


def test_the_money_docstring_records_the_r4_commission_obligation() -> None:
    """DOC PIN. ``create_inferred_order_filled_event`` falls back to a ZERO fee.

    ``reconciliation.py:507-508``: when ``client.calculate_commission`` returns
    ``None`` Nautilus books ``Money(0, quote_currency)`` -- an implied-zero fee,
    which is exactly what ``assert_fee_schedule_known`` exists to prevent. That
    fallback is Nautilus's and is IMMUTABLE, so R-4's execution client MUST
    implement ``calculate_commission`` from ``PolymarketUSFeeModel``. This pin
    keeps the obligation from being dropped silently.
    """
    source = (EXEC_DIR / "reports.py").read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(source))
    assert docstring is not None
    assert "calculate_commission" in docstring
    assert "PolymarketUSFeeModel" in docstring

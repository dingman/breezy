"""ARM maker-sharp B6 review P1 + SEC L8: an absent or garbled commission on a FILLED rest.

A fill is never refused for its commission (L-48), but it is no longer booked at zero cost:
it books the MODELLED TAKER cent fee (conservative; the design cost), ``fee_reconciled`` False and
``venue_fee_raw`` None, raises a value-free CRITICAL ``commission_unreadable`` alert and latches NEW
rests. The sign class ``?`` stays in the booked log line; no raw value is ever logged.

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import (
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import _payload
from tests.unit.test_polymarket_us_resting_query import (
    _fill,
    _filled_events,
    _query,
    _reasons,
    _records,
    _rested,
)
from tests.unit.test_polymarket_us_resting_submit import _rest_command

#: NO 0.40, qty 1, theta 0.06: 0.0144 banker's-rounded to the cent.
MODELLED_TAKER_FEE: Final[Decimal] = Decimal("0.01")
GARBLED: Final[tuple[Any, ...]] = (
    {"value": "not-a-number", "currency": "USD"},
    {"value": "NaN", "currency": "USD"},
    {"value": None, "currency": "USD"},
    "garbled",
)


def _absent(rig: Any) -> None:
    del _payload(rig, 0)["commissionNotionalTotalCollected"]


def _garble(rig: Any, value: Any) -> None:
    _payload(rig, 0)["commissionNotionalTotalCollected"] = value


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("shape", ["absent", *range(len(GARBLED))])
async def test_an_unreadable_commission_books_the_modelled_taker_fee_unreconciled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: Any
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0)
    _absent(rig) if shape == "absent" else _garble(rig, GARBLED[shape])
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    (event,) = _filled_events(rig)
    assert record.venue_fee_raw is None and record.fee_reconciled is False
    assert record.cumulative_fee == MODELLED_TAKER_FEE
    assert event.commission.as_decimal() == MODELLED_TAKER_FEE
    assert record.fee_source == client_module.FEE_SOURCE_MODELLED_AT_FILL_TIME
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_an_unreadable_commission_raises_a_value_free_critical_alert_and_latches_new_rests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0)
    _garble(rig, {"value": "SECRET-9.87654", "currency": "USD"})
    await rig.client._query_order(_query(rig, command))
    alerts = [dict(a) for a in rig.client.resting_commission_alerts]
    assert [a["event"] for a in alerts] == ["commission_unreadable"]
    assert alerts[0]["severity"] == "CRITICAL"
    assert "SECRET" not in json.dumps(alerts) and "9.87654" not in json.dumps(alerts)
    assert submit_chain.RESTING_COMMISSION_UNREADABLE_REASON in _reasons(rig)
    posts = len(rig.sender.calls)
    await rig.client._submit_order(_rest_command(rig.client))
    assert len(rig.sender.calls) == posts, "NEW rests are refused"
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_an_unreadable_commission_logs_the_unknown_sign_class_and_no_raw_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0)
    _garble(rig, {"value": "SECRET-9.87654", "currency": "USD"})
    await rig.client._query_order(_query(rig, command))
    booked = [
        line
        for level in ("info", "warning", "error")
        for line in rig.client.log_lines(level, "booked the fill")
    ]
    assert booked and all("commission sign ?" in line for line in booked)
    everything = " ".join(
        line
        for level in ("debug", "info", "warning", "error")
        for line in rig.client.log_lines(level, "")
    )
    assert "SECRET" not in everything and "9.87654" not in everything
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_readable_commission_raises_no_unreadable_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="0.01")
    await rig.client._query_order(_query(rig, command))
    assert not [
        a for a in rig.client.resting_commission_alerts if a["event"] == "commission_unreadable"
    ]
    assert submit_chain.RESTING_COMMISSION_UNREADABLE_REASON not in _reasons(rig)
    await rig.client._disconnect()

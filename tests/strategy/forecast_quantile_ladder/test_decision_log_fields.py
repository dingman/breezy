"""decision_log_fields -- explicit, field-by-field Decision serialisation.

``dataclasses.asdict`` is banned repo-wide outside the closed allowlist in
``tests/unit/test_polymarket_us_credential_serialization.py`` (item 2's
partial-secret-leak guard). This package's shadow log must never call it, so
every ``Decision`` variant is serialised by a small pure function instead.
"""

from __future__ import annotations

import datetime as dt

from breezy.strategy.forecast_quantile_ladder.decision import (
    NotDPlus1,
    NotExecutable,
    Refuse,
    Take,
    decision_log_fields,
)

_DAY = dt.date(2026, 10, 1)


def test_not_executable_fields() -> None:
    fields = decision_log_fields(NotExecutable())

    assert fields == {"reason": "outside_permit_window"}


def test_not_executable_carries_a_non_default_reason() -> None:
    fields = decision_log_fields(NotExecutable(reason="custom"))

    assert fields == {"reason": "custom"}


def test_not_d_plus_1_fields() -> None:
    fields = decision_log_fields(NotDPlus1())

    assert fields == {"reason": "not_d_plus_1"}


def test_refuse_fields() -> None:
    fields = decision_log_fields(Refuse(reason="already_latched"))

    assert fields == {"reason": "already_latched"}


def test_take_fields_carries_every_field() -> None:
    take = Take(
        instrument_id="KMIA-2026-10-01-i1.POLY_US",
        station="KMIA",
        climate_day=_DAY,
        side="yes",
        rung_id="i1",
        qty=1,
        ev_net=0.05,
        p_hat=0.30,
        p_lower=0.27,
        p_upper=0.33,
    )

    fields = decision_log_fields(take)

    assert fields == {
        "instrument_id": "KMIA-2026-10-01-i1.POLY_US",
        "station": "KMIA",
        "climate_day": _DAY,
        "side": "yes",
        "rung_id": "i1",
        "qty": 1,
        "ev_net": 0.05,
        "p_hat": 0.30,
        "p_lower": 0.27,
        "p_upper": 0.33,
    }


def test_an_unknown_decision_type_raises() -> None:
    """Fails CLOSED: widening the Decision alphabet without teaching this
    function about it must not silently drop fields from the shadow log."""
    import pytest

    class _NotADecision:
        pass

    with pytest.raises((TypeError, ValueError)):
        decision_log_fields(_NotADecision())  # type: ignore[arg-type]

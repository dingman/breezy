"""SL-9 SEARCH comparison tests for ``nbp_market_comparison``.

Synthetic only: the coordinator runs the real quote-tape/NBP/catalog job later.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from typing import Any

import pytest
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Money

from breezy.adapters.polymarket_us.fees import taker_fee_at_fill
from scripts.analysis import nbp_market_comparison as m

DAY = dt.date(2026, 9, 25)
NEXT_DAY = dt.date(2026, 9, 26)
STATION = "KMIA"
RUNG = "gte80lt82f"
NS = 1_000_000_000


def _ns(day: dt.date, hour: int, minute: int = 0) -> int:
    return int(dt.datetime.combine(day, dt.time(hour, minute), tzinfo=dt.UTC).timestamp()) * NS


def _forecast(
    *,
    available_at_ns: int,
    climate_day: dt.date = DAY,
    rung_id: str = RUNG,
    p_point: float = 0.80,
    p_lower: float = 0.76,
    p_upper: float = 0.84,
) -> m.ForecastRungProbability:
    return m.ForecastRungProbability(
        station=STATION,
        climate_day=climate_day,
        rung_id=rung_id,
        available_at_ns=available_at_ns,
        p_point=p_point,
        p_lower=p_lower,
        p_upper=p_upper,
    )


def _snapshot(
    *,
    price_ts_ns: int,
    climate_day: dt.date = DAY,
    rung_id: str = RUNG,
    side: m.LegSide = "yes",
    ask: float = 0.40,
    bid: float = 0.38,
    source: m.BookSource | None = None,
) -> m.MarketSnapshot:
    return m.MarketSnapshot(
        station=STATION,
        climate_day=climate_day,
        rung_id=rung_id,
        side=side,
        price_ts_ns=price_ts_ns,
        ask=ask,
        bid=bid,
        ask_size=10.0,
        bid_size=12.0,
        source=source or ("captured_no_book" if side == "no" else "captured_yes_book"),
    )


def test_lookahead_raises_when_forecast_available_at_is_not_before_price_ts() -> None:
    snap = _snapshot(price_ts_ns=_ns(DAY, 18))
    forecast = _forecast(available_at_ns=snap.price_ts_ns)

    with pytest.raises(m.AvailabilityLookAheadError, match="available_at_ns"):
        m.select_forecast_for_snapshot((forecast,), snap)


def test_tape_days_after_the_prefreeze_cutoff_are_refused() -> None:
    with pytest.raises(m.PostFreezeTapeRefusedError, match="2026-09-25"):
        m.assert_allowed_tape_day(NEXT_DAY)


def test_price_timestamps_after_the_prefreeze_cutoff_are_refused_even_when_climate_day_is_allowed() -> None:
    snap = _snapshot(price_ts_ns=_ns(NEXT_DAY, 0), climate_day=DAY)

    with pytest.raises(m.PostFreezeTapeRefusedError, match="price_ts"):
        m.compare_model_vs_market(
            forecasts=(_forecast(available_at_ns=_ns(DAY, 18)),),
            snapshots=(snap,),
            truths={(STATION, DAY, RUNG): True},
        )


def test_s4_shadow_logs_are_refused_before_registration() -> None:
    with pytest.raises(m.ShadowLogRefusedError, match="S4 shadow"):
        m.assert_not_shadow_log_path("logs/s4_shadow/decisions-2026-09-24.jsonl")


def test_scope_filters_by_date_and_hour_together() -> None:
    in_scope = _snapshot(price_ts_ns=_ns(DAY, 18))
    wrong_day = m.MarketSnapshot(
        station=STATION,
        climate_day=NEXT_DAY,
        rung_id=RUNG,
        side="yes",
        price_ts_ns=_ns(NEXT_DAY, 18),
        ask=0.40,
        bid=0.38,
        ask_size=10.0,
        bid_size=12.0,
        source="captured_yes_book",
    )
    wrong_hour = _snapshot(price_ts_ns=_ns(DAY, 15))

    scoped = m.scope_snapshots(
        (in_scope, wrong_day, wrong_hour),
        scope=m.Scope(days=frozenset({DAY}), hours_utc=frozenset({18})),
    )

    assert scoped == (in_scope,)


def test_no_leg_price_must_come_from_the_captured_no_book() -> None:
    derived = _snapshot(
        price_ts_ns=_ns(DAY, 18),
        side="no",
        ask=0.61,
        bid=0.59,
        source="derived_from_yes_book",
    )

    with pytest.raises(m.CapturedNoBookRequiredError, match="captured NO book"):
        m.executable_ask(derived)


def test_maker_no_leg_fill_must_come_from_the_captured_no_book() -> None:
    derived = _snapshot(
        price_ts_ns=_ns(DAY, 18),
        side="no",
        ask=0.61,
        bid=0.59,
        source="derived_from_yes_book",
    )

    with pytest.raises(m.CapturedNoBookRequiredError, match="captured NO book"):
        m.maker_fill_ev(
            fill=derived,
            forecast=_forecast(available_at_ns=_ns(DAY, 17)),
            later_same_leg_snapshots=(derived,),
        )


class _FakeId:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeBinaryOption:
    def __init__(
        self,
        instrument_id: str,
        *,
        lower_f: int | None,
        upper_f: int | None,
    ) -> None:
        self.id = _FakeId(instrument_id)
        self.info: dict[str, Any] = {
            "weather_facts_status": "KNOWN",
            "settlement_station": STATION,
            "climate_date": DAY.isoformat(),
            "measure": "high",
            "strike_lower_f": lower_f,
            "strike_upper_f": upper_f,
        }


class _FakeCatalog:
    def __init__(self, instruments: tuple[_FakeBinaryOption, ...]) -> None:
        self._instruments = instruments

    def instruments(self) -> tuple[_FakeBinaryOption, ...]:
        return self._instruments


def test_incomplete_catalog_partition_is_skipped_and_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m, "BinaryOption", _FakeBinaryOption)
    catalog = _FakeCatalog(
        (
            _FakeBinaryOption(
                "tc-temp-miahigh-2026-09-25-lt80f.POLYMARKET_US",
                lower_f=None,
                upper_f=79,
            ),
            _FakeBinaryOption(
                "tc-temp-miahigh-2026-09-25-gte82f.POLYMARKET_US",
                lower_f=82,
                upper_f=None,
            ),
        )
    )

    rungs_by_station_day, counts = m.rungs_by_station_day_from_catalog(catalog)

    assert rungs_by_station_day == {}
    assert counts["catalog_station_days_incomplete_partition"] == 1


def test_incomplete_per_instant_partition_is_counted_and_excluded() -> None:
    rungs_by_station_day = {
        (STATION, DAY): (
            m.Rung(rung_id="lt80f", lo=None, hi=79),
            m.Rung(rung_id="gte80lt81f", lo=80, hi=81),
            m.Rung(rung_id="gte82f", lo=82, hi=None),
        )
    }
    snap = _snapshot(price_ts_ns=_ns(DAY, 18), rung_id="lt80f")

    report = m.compare_model_vs_market(
        forecasts=(
            _forecast(available_at_ns=_ns(DAY, 17), rung_id="lt80f"),
        ),
        snapshots=(snap,),
        truths={(STATION, DAY, "lt80f"): True},
        rungs_by_station_day=rungs_by_station_day,
    )

    assert report.decisions["taker_v1"].n_events == 0
    assert report.counts["instants_partition_incomplete"] == 1


def test_fee_is_bankers_rounded_quadratic_and_matches_taker_fee_at_fill() -> None:
    fee = m.rounded_quadratic_fee_usd(
        quantity=Decimal("1"),
        price=Decimal("0.44"),
        theta=Decimal("0.0695"),
    )
    src_fee = taker_fee_at_fill(
        quantity=Decimal("1"),
        price=Decimal("0.44"),
        ts_event_ns=1_789_664_400_000_000_000,
        fee_coefficient_at_fill=Decimal("0.0695"),
    )

    assert src_fee == Money(fee, USD)


def test_fee_rejects_flat_per_contract_arithmetic() -> None:
    quadratic = m.rounded_quadratic_fee_usd(
        quantity=Decimal("1"),
        price=Decimal("0.50"),
        theta=Decimal("0.0695"),
    )
    flat = Decimal("0.07")

    assert quadratic != flat
    assert quadratic == Decimal("0.02")


def test_maker_uses_theta_ceiling_and_five_minute_haircut_same_leg() -> None:
    fill = _snapshot(price_ts_ns=_ns(DAY, 18), ask=0.40, bid=0.39)
    same_leg_worse = _snapshot(price_ts_ns=_ns(DAY, 18, 3), ask=0.42, bid=0.35)
    other_leg = m.MarketSnapshot(
        station=STATION,
        climate_day=DAY,
        rung_id="lt80f",
        side="yes",
        price_ts_ns=_ns(DAY, 18, 2),
        ask=0.99,
        bid=0.01,
        ask_size=10.0,
        bid_size=10.0,
        source="captured_yes_book",
    )

    result = m.maker_fill_ev(
        fill=fill,
        forecast=_forecast(available_at_ns=_ns(DAY, 17), p_point=0.50),
        later_same_leg_snapshots=(same_leg_worse, other_leg),
    )

    assert result.fee_theta == Decimal("0.0695")
    assert result.haircut == pytest.approx(0.05)


def test_outside_permit_snapshots_are_not_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m.trade_supervisor_core, "LAUNCH_UTC", dt.time(16, 50))
    monkeypatch.setattr(m.safety, "PERMIT_TTL_NS", 10 * 60 * 60 * NS)
    outside = _snapshot(price_ts_ns=_ns(DAY, 15))

    assert m.execution_status(outside) == "NOT_EXECUTABLE"


def test_decisive_statistic_excludes_snapshots_outside_the_permit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m.trade_supervisor_core, "LAUNCH_UTC", dt.time(16, 50))
    monkeypatch.setattr(m.safety, "PERMIT_TTL_NS", 10 * 60 * 60 * NS)
    inside = _snapshot(price_ts_ns=_ns(DAY, 18), ask=0.40)
    outside = _snapshot(price_ts_ns=_ns(DAY, 15), ask=0.99)

    report = m.compare_model_vs_market(
        forecasts=(_forecast(available_at_ns=_ns(DAY, 14), p_point=0.80),),
        snapshots=(inside, outside),
        truths={(STATION, DAY, RUNG): True},
    )

    assert report.decisions["taker_v1"].n_events == 1
    assert report.all_hours["label"] == "descriptive forecast-skill only"


def test_monkeypatched_permit_constants_move_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = _snapshot(price_ts_ns=_ns(DAY, 15, 30))
    monkeypatch.setattr(m.trade_supervisor_core, "LAUNCH_UTC", dt.time(16, 50))
    monkeypatch.setattr(m.safety, "PERMIT_TTL_NS", 10 * 60 * 60 * NS)
    assert not m.is_inside_nominal_permit(snap.price_ts_ns)

    monkeypatch.setattr(m.trade_supervisor_core, "LAUNCH_UTC", dt.time(15, 0))
    monkeypatch.setattr(m.safety, "PERMIT_TTL_NS", 60 * 60 * NS)
    assert m.is_inside_nominal_permit(snap.price_ts_ns)


def test_all_hours_output_has_descriptive_label_and_no_drop_keep() -> None:
    report = m.compare_model_vs_market(
        forecasts=(_forecast(available_at_ns=_ns(DAY, 17), p_point=0.80),),
        snapshots=(_snapshot(price_ts_ns=_ns(DAY, 18)),),
        truths={(STATION, DAY, RUNG): True},
    )

    assert report.all_hours["label"] == "descriptive forecast-skill only"
    assert "drop_keep" not in report.all_hours


def test_drop_keep_bytes_do_not_change_when_out_of_window_prices_are_perturbed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(m.trade_supervisor_core, "LAUNCH_UTC", dt.time(16, 50))
    monkeypatch.setattr(m.safety, "PERMIT_TTL_NS", 10 * 60 * 60 * NS)
    forecast = _forecast(available_at_ns=_ns(DAY, 14), p_point=0.80)
    inside = _snapshot(price_ts_ns=_ns(DAY, 18), ask=0.40)
    outside_a = _snapshot(price_ts_ns=_ns(DAY, 15), ask=0.01)
    outside_b = _snapshot(price_ts_ns=_ns(DAY, 15), ask=0.99)

    first = m.drop_keep_json_bytes(
        m.compare_model_vs_market(
            forecasts=(forecast,),
            snapshots=(inside, outside_a),
            truths={(STATION, DAY, RUNG): True},
        )
    )
    second = m.drop_keep_json_bytes(
        m.compare_model_vs_market(
            forecasts=(forecast,),
            snapshots=(inside, outside_b),
            truths={(STATION, DAY, RUNG): True},
        )
    )

    assert first == second


def test_taker_and_maker_verdict_rules_are_predeclared() -> None:
    assert m.taker_verdict(ci_upper=-0.0001) == "DROP"
    assert m.taker_verdict(ci_upper=0.0) == "KEEP"
    assert m.maker_verdict(ev_point=0.0) == "DROP"
    assert m.maker_verdict(ev_point=0.0001) == "KEEP"


def test_calibration_artefact_loader_refuses_non_ok_fit_status(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "artefact.json"
    payload = {
        "schema_version": 1,
        "cdf_method": "normal",
        "recalibration": "emos",
        "correction_form": "none",
        "delta": 1.0,
        "kappa": 0.0,
        "emos_params_by_version": {"v5.0": [0.0, 0.0]},
        "emos_draws_by_version": {"v5.0": [[0.0, 0.0, 1.0]]},
        "n_min": 1,
        "sigma_d": 0.1,
        "rung_probability_bounds": {RUNG: [0.5, 0.4, 0.6]},
        "fit_status": "FIT_NOT_CONVERGED",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(m.CalibrationArtefactRefusedError, match="fit_status"):
        m.load_calibration_artefact(path)

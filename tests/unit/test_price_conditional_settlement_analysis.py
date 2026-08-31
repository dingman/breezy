from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.objects import Price, Quantity

from tests.unit.test_polymarket_us_fee_model import (
    build,
    load_open_market,
    order_with_liquidity,
)


def _load_analysis_module() -> ModuleType:
    path = Path("scripts/analysis/price_conditional_settlement_analysis.py")
    sys.path.insert(0, path.parent.as_posix())
    spec = importlib.util.spec_from_file_location(
        "price_conditional_settlement_analysis",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _truth_row(
    *,
    climate_day: dt.date,
    tmax_f: int,
    within_expected_window: bool = True,
) -> dict[str, Any]:
    return {
        "station": "NYC",
        "city": "NYC",
        "climate_day": climate_day,
        "status": "FINAL",
        "is_final": True,
        "tmax_f": tmax_f,
        "within_expected_window": within_expected_window,
    }


def test_leave_one_year_out_never_lets_a_day_train_on_its_own_year() -> None:
    analysis = _load_analysis_module()
    target = analysis.TargetCell(
        station="NYC",
        climate_day=dt.date(2026, 8, 30),
        lower_f=80,
        upper_f=85,
        bucket_slug="gte80lt85f",
        bucket_parity="even",
        instrument_id="fixture.POLYMARKET_US",
    )
    rows = [
        _truth_row(climate_day=dt.date(2026, 8, 30), tmax_f=82),
        _truth_row(climate_day=dt.date(2025, 8, 30), tmax_f=90),
        _truth_row(climate_day=dt.date(2024, 8, 29), tmax_f=84),
    ]

    cell = analysis.compute_base_rate_cell(
        rows,
        target=target,
        sample_scope="including_spillover",
        day_window_radius=1,
        min_sample_floor=1,
    )

    assert cell.sample_count == 2
    assert cell.yes_count == 1
    assert cell.excluded_year == 2026
    assert cell.observation_years == (2024, 2025)


def test_break_even_price_matches_hand_computed_yes_and_no_examples() -> None:
    analysis = _load_analysis_module()

    # YES with base rate 0.63 and theta 0.06:
    # EV = 0.63 - x - 0.06*x*(1-x). At x=0.615804643, EV rounds to zero.
    yes = analysis.break_even_executable_price(
        event_probability=Decimal("0.63"),
        theta=Decimal("0.06"),
    )
    assert yes.quantize(Decimal("0.000000001")) == Decimal("0.615804643")

    # NO with YES base rate 0.63 means event probability 0.37.
    no = analysis.break_even_executable_price(
        event_probability=Decimal("0.37"),
        theta=Decimal("0.06"),
    )
    assert no.quantize(Decimal("0.000000001")) == Decimal("0.356240016")


def test_analysis_fee_formula_matches_the_real_polymarket_us_fee_model() -> None:
    analysis = _load_analysis_module()
    instrument = build(load_open_market())
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    qty = Quantity.from_int(100)
    price = Price.from_str("0.90")

    model_fee = analysis.model_fee_for_contracts(
        theta=Decimal("0.06"),
        contracts=Decimal(100),
        executable_price=Decimal("0.90"),
        currency_precision=instrument.quote_currency.precision,
    )
    real_fee = analysis.PolymarketUSFeeModel().get_commission(order, qty, price, instrument)

    assert model_fee == real_fee.as_decimal()


def test_main_writes_json_artifact_with_limitations_and_quote_comparison(tmp_path: Path) -> None:
    analysis = _load_analysis_module()
    truth_path = tmp_path / "truth.json"
    output_path = tmp_path / "analysis.json"
    truth_rows = [
        _truth_row(climate_day=dt.date(2025, 8, 29), tmax_f=82),
        _truth_row(climate_day=dt.date(2025, 8, 30), tmax_f=90),
        _truth_row(climate_day=dt.date(2024, 8, 30), tmax_f=83),
    ]
    truth_path.write_text(json.dumps(truth_rows, default=str), encoding="utf-8")

    exit_code = analysis.main(
        [
            "--settlement-truth",
            str(truth_path),
            "--output",
            str(output_path),
            "--skip-live-quotes",
            "--target",
            "NYC,2026-08-30,80,85,gte80lt85f,fixture.POLYMARKET_US",
            "--min-sample-floor",
            "1",
            "--generated-at-utc",
            "2026-08-30T18:00:00Z",
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["methodology"]["anti_lookahead"] == "leave_one_year_out"
    assert "not a P&L" in " ".join(payload["limitations"])
    assert payload["summary"]["live_quote_sample"] == "skipped"
    assert payload["base_rate_cells"]

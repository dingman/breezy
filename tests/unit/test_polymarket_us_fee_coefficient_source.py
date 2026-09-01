"""Unit tests for `PolymarketUSFeeCoefficients`, the venue-specific END of the
`FeeCoefficientSource` seam.

WHERE IT LIVES, AND WHY THAT IS NOT AN ACCIDENT
------------------------------------------------
It must reach BOTH `breezy.adapters.polymarket_us` (the validated coefficient
read) and `breezy.strategy.weather_common.costs` (the error type the strategy
layer catches). `pyproject.toml`'s layers contract is
`strategy > runtime > adapters` with `exhaustive = true`, so a `runtime` home
fails `lint-imports` outright -- "breezy.runtime is not allowed to import
breezy.strategy" -- and the only module inside `breezy` that legally sees both
is one in the `strategy` layer, which would weld a strategy package to one
venue.

So it lives at the construction site, which is the precedent this repo
already set for the IDENTICAL problem: the only concrete `ForecastSource`
(`_SequenceForecastSource`) lives in the same script, for the same reason. The
injected Protocol stays venue-neutral in `weather_common`; the concrete
implementation stays with the wiring.

Loaded via `importlib` from its file path, matching
`test_run_weather_strategy_backtests.py`: `scripts/` carries no package
`__init__.py`.

THE PROPERTY UNDER TEST: refuse, never default.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.strategy.weather_common.costs import (
    FeeCoefficientSource,
    UnknownFeeScheduleError,
)
from tests.unit.test_polymarket_us_fee_model import rebuild_with_info


def _load_runner_module() -> ModuleType:
    path = Path("scripts/analysis/run_weather_strategy_backtests.py")
    sys.path.insert(0, path.parent.as_posix())
    spec = importlib.util.spec_from_file_location("run_weather_strategy_backtests", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner_module()
PolymarketUSFeeCoefficients = runner.PolymarketUSFeeCoefficients

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT = 1_787_617_213_000_000_000


def _market() -> BinaryOption:
    payload: dict[str, Any] = json.loads(
        (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8"),
    )
    return parse_binary_option(payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def _source(*instruments: BinaryOption) -> Any:
    return PolymarketUSFeeCoefficients({str(i.id): i for i in instruments})


def test_it_satisfies_the_venue_neutral_protocol() -> None:
    instrument = _market()
    source: FeeCoefficientSource = _source(instrument)

    assert isinstance(source, FeeCoefficientSource)


def test_it_returns_the_markets_own_coefficient_as_a_float() -> None:
    instrument = _market()
    source = _source(instrument)

    theta = source.fee_coefficient_for(str(instrument.id))

    assert isinstance(theta, float)
    assert theta == pytest.approx(float(instrument.info["fee_coefficient"]))


def test_an_unknown_instrument_id_refuses_rather_than_defaulting() -> None:
    """Not in the mapping is not "free"; it is "we do not know"."""
    source = _source(_market())

    with pytest.raises(UnknownFeeScheduleError):
        source.fee_coefficient_for("some-market-we-never-loaded")


def test_an_unknown_fee_schedule_refuses_rather_than_trading_free() -> None:
    """Barrier F1's status marker, surfaced through the strategy-layer type."""
    instrument = _market()
    unknown = rebuild_with_info(instrument, {"fee_schedule_status": "UNKNOWN"})
    source = _source(unknown)

    with pytest.raises(UnknownFeeScheduleError):
        source.fee_coefficient_for(str(unknown.id))


@pytest.mark.parametrize("bad", [None, True, "not-a-decimal", "-0.5", "1.5"])
def test_a_known_marker_carrying_an_unusable_coefficient_still_refuses(bad: object) -> None:
    """The MARKER alone never licenses a computation -- the adapter's own rule.

    Delegated to `adapters.polymarket_us.fees`'s validated read rather than
    re-implemented here, so the gate-time resolution and the settlement-time
    authority cannot diverge on what counts as usable.
    """
    instrument = _market()
    info: dict[str, Any] = {"fee_schedule_status": "KNOWN"}
    if bad is not None:
        info["fee_coefficient"] = bad
    broken = rebuild_with_info(instrument, info)
    source = _source(broken)

    with pytest.raises(UnknownFeeScheduleError):
        source.fee_coefficient_for(str(broken.id))


def test_the_adapter_error_never_escapes_as_an_adapter_type() -> None:
    """The strategy layer must never have to catch a venue-specific exception."""
    from breezy.adapters.polymarket_us.errors import FeeScheduleUnknownError

    instrument = _market()
    unknown = rebuild_with_info(instrument, {"fee_schedule_status": "UNKNOWN"})
    source = _source(unknown)

    with pytest.raises(UnknownFeeScheduleError) as caught:
        source.fee_coefficient_for(str(unknown.id))

    assert not isinstance(caught.value, FeeScheduleUnknownError)
    assert isinstance(caught.value.__cause__, FeeScheduleUnknownError)


def test_a_zero_coefficient_is_returned_rather_than_refused() -> None:
    """`theta = 0` is an OBSERVED value; refusing it would be a different rule.

    The adapter validates the range `[0, 1]` and accepts 0. Fail-closed applies
    to an ABSENT or unparseable schedule, not to a venue that genuinely charges
    nothing on this market.
    """
    instrument = _market()
    free = rebuild_with_info(
        instrument, {"fee_schedule_status": "KNOWN", "fee_coefficient": "0"},
    )
    source = _source(free)

    assert source.fee_coefficient_for(str(free.id)) == 0.0

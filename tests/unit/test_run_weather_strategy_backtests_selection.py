"""Selection-helper equivalence for the two climate-day reading contracts.

``_select_highest_revision_readings`` does not exist until AUD-11 wires it.
``require_final``, ``raise_on_missing`` and ``filter_superseded`` are
independent: the real-observation wrapper raises when a fixed station is
absent and filters ``is_superseded``; the settlement wrapper omits a station
that has no final print and does NOT consult ``is_superseded`` -- see
``breezy.domain.nws_climate_day.NwsClimateDay`` (``is_superseded``) and
``breezy.domain.selection`` (module docstring).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "run_weather_strategy_backtests.py"
_DAY = dt.date(2026, 8, 30)
_SHA = hashlib.sha256(b"aud11-synthetic-climate-day").hexdigest()


def _load() -> ModuleType:
    if str(_SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_weather_strategy_backtests", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 70,
        "tmin_f": 60,
        "tavg_f": 65,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": False,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": 10,
        "retrieved_at_ns": 20,
        "parser_version": "test",
        "registry_version": "sites.toml@test",
        "raw_sha256": _SHA,
        "source_channel": "aud11-synthetic",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": 10,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def test_non_final_selection_matches_the_real_observation_rule() -> None:
    module = _load()
    nyc_low = _day(station="NYC", revision_seq=1, tmax_f=70, retrieved_at_ns=20)
    nyc_high = _day(station="NYC", revision_seq=2, tmax_f=71, retrieved_at_ns=30)
    mia = _day(station="MIA", revision_seq=1, tmax_f=80, retrieved_at_ns=25)
    superseded = _day(
        station="NYC",
        revision_seq=9,
        tmax_f=99,
        is_superseded=True,
        retrieved_at_ns=40,
    )
    observed, chosen = module._select_highest_revision_readings(
        [nyc_low, superseded, mia, nyc_high],
        stations=("NYC", "MIA"),
        require_final=False,
        raise_on_missing=True,
        filter_superseded=True,
    )
    assert observed == {"NYC": 71, "MIA": 80}
    assert chosen["NYC"] is nyc_high
    assert chosen["MIA"] is mia
    assert list(observed) == ["NYC", "MIA"]


def test_missing_fixed_station_raises_the_real_observation_lookup_error() -> None:
    module = _load()
    nyc = _day(station="NYC", tmax_f=70)
    with pytest.raises(LookupError, match=r"station='MIA'"):
        module._select_highest_revision_readings(
            [nyc],
            stations=("NYC", "MIA"),
            require_final=False,
            raise_on_missing=True,
            filter_superseded=True,
            missing_context="/tmp/aud11-synthetic-catalog",
        )


def test_final_selection_omits_a_station_that_has_only_a_preliminary() -> None:
    module = _load()
    preliminary = _day(station="NYC", revision_seq=1, tmax_f=70, is_final=False)
    final = _day(station="MIA", revision_seq=2, tmax_f=91, is_final=True, retrieved_at_ns=50)
    records = [preliminary, final]
    observed, _chosen = module._select_highest_revision_readings(
        records,
        stations=("MIA", "NYC"),
        require_final=True,
        raise_on_missing=False,
        filter_superseded=False,
    )
    assert observed == {"MIA": 91}
    assert "NYC" not in observed
    assert module._settled_readings(records) == observed


def test_settled_readings_omits_a_preliminary_only_station_without_raising() -> None:
    module = _load()
    preliminary = _day(station="NYC", revision_seq=3, tmax_f=77, is_final=False)
    observed, _chosen = module._select_highest_revision_readings(
        [preliminary],
        stations=("NYC",),
        require_final=True,
        raise_on_missing=False,
        filter_superseded=False,
    )
    assert observed == {}
    assert module._settled_readings([preliminary]) == observed


def test_load_real_observations_wrapper_still_raises_when_a_fixed_station_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    # The wrapper is only the real-observation contract once it delegates here.
    assert callable(module._select_highest_revision_readings)
    nyc = _day(station="NYC", tmax_f=70)

    def _only_nyc(*_args: object, **_kwargs: object) -> list[NwsClimateDay]:
        return [nyc]

    monkeypatch.setattr(module, "_load_climate_day_records", _only_nyc)
    with pytest.raises(LookupError, match=r"station='MIA'"):
        module._load_real_observations(Path("/tmp/aud11-synthetic-catalog"))


def test_settled_readings_selects_a_superseded_higher_revision_final() -> None:
    """Settlement truth does NOT consult ``is_superseded``.

    ``breezy.domain.nws_climate_day.NwsClimateDay`` (``is_superseded``) and
    ``breezy.domain.selection`` (module docstring) both state the flag can
    only record what was known when a record was written -- it is never set
    retroactively on the record it supersedes -- so selecting on it would
    silently disagree with the write path. The settlement wrapper therefore
    ranks on ``revision_seq`` alone among FINAL prints: a higher-revision
    FINAL is selected even though it carries ``is_superseded=True``.
    """
    module = _load()
    superseded = _day(
        station="NYC",
        revision_seq=5,
        tmax_f=80,
        is_final=True,
        is_superseded=True,
        retrieved_at_ns=90,
    )
    current = _day(
        station="NYC",
        revision_seq=2,
        tmax_f=77,
        is_final=True,
        is_superseded=False,
        retrieved_at_ns=40,
    )
    assert module._settled_readings([superseded, current]) == {"NYC": 80}


def test_the_default_branch_does_not_restamp_climate_days() -> None:
    """The restamp helper and the engine feed of climate days are gone."""
    source = _SCRIPT.read_text(encoding="utf-8")
    assert "_restamp_climate_day" not in source
    assert "weather_data: list[Any] = []" in source
    assert "assert_available_before_decision" in source
    assert "except LookAheadRecordError" in source


def test_a_selected_record_with_no_tmax_still_raises() -> None:
    module = _load()
    missing = _day(station="NYC", tmax_f=None, tmax_flag="M", is_final=True)
    with pytest.raises(LookupError, match="tmax_f"):
        module._select_highest_revision_readings(
            [missing],
            stations=("NYC",),
            require_final=True,
            raise_on_missing=False,
            filter_superseded=False,
        )

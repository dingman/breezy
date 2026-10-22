"""ARM C3: the parity-fixture extractor refuses every read outside the evidence fence.

The fence is: maker stations only, climate days on or before 2026-10-13, and never the sealed
2026-10-01. The refusal must happen before any catalog, census or NBP path is touched.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import maker_parity_fixture_extract as fx

LAST = dt.date(2026, 10, 13)


@pytest.mark.parametrize("station", ["LAX", "MDW", "MIA", "SFO"])
def test_the_last_allowed_day_is_inside_the_fence(station: str) -> None:
    fx.check_fence(station, LAST)
    fx.check_fence(station, dt.date(2026, 9, 18))


@pytest.mark.parametrize(
    "day",
    [
        dt.date(2026, 10, 14),  # first sealed second-look day
        dt.date(2026, 10, 15),
        dt.date(2026, 11, 15),
        dt.date(2027, 1, 1),
        dt.date(2026, 10, 1),  # the sealed holdout day
    ],
)
def test_days_outside_the_fence_are_refused(day: dt.date) -> None:
    with pytest.raises(fx.FenceRefused, match=day.isoformat()):
        fx.check_fence("SFO", day)


@pytest.mark.parametrize("station", ["NYC", "sfo", "", "KSFO", "DEN"])
def test_stations_outside_the_maker_set_are_refused(station: str) -> None:
    with pytest.raises(fx.FenceRefused, match="station"):
        fx.check_fence(station, dt.date(2026, 9, 21))


def test_a_malformed_case_is_refused() -> None:
    for text in ("SFO", "SFO:not-a-date", "SFO:2026-09-21:fill_day:extra", ":2026-09-21"):
        with pytest.raises(fx.FenceRefused):
            fx.parse_case(text)


@pytest.mark.parametrize("case", ["SFO:2026-10-14", "LAX:2026-10-01", "NYC:2026-09-21"])
def test_main_refuses_before_touching_any_input(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("an input was touched before the fence refused")

    monkeypatch.setattr(fx, "CatalogSession", boom)
    monkeypatch.setattr(fx, "read_plan_cache", boom)
    monkeypatch.setattr(fx, "read_census_row", boom)
    out = tmp_path / "fixture.json.gz"
    missing = tmp_path / "does-not-exist"
    argv = [
        "--case", case, "--out", str(out), "--catalog-root", str(missing),
        "--nbp-root", str(missing), "--plan-cache", str(missing), "--census-days", str(missing),
        "--trade-unit", str(missing), "--calibration", str(missing), "--work-root", str(missing),
    ]  # fmt: skip
    assert fx.main(argv) == 2
    assert "refused" in capsys.readouterr().err
    assert not out.exists()


def test_one_refused_case_refuses_the_whole_batch(tmp_path: Path) -> None:
    with pytest.raises(fx.FenceRefused):
        fx.check_cases([fx.parse_case("SFO:2026-09-21"), fx.parse_case("SFO:2026-10-14")])

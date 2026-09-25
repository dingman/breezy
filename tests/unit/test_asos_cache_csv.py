"""RED-first unit tests for `scripts/analysis/asos_cache_csv.py` (AUD-09b §6b.1).

The producer is CACHE-ONLY and ZERO-NETWORK by construction, exactly like
`cli_basis_offer_gate_scan.py`. Every test here runs against a plain temp
directory of `.txt` cache files -- no `httpx.Client` may ever be
constructed, asserted directly below.
"""

from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from asos_cache_csv import (
    ASOS_CACHE_EMPTY,
    ASOS_CACHE_UNPARSEABLE_ROWS,
    CSV_FIELDNAMES,
    AsosCacheCsvError,
    climate_day_utc_bounds,
    main,
    site_for_station,
    windowed_asos_rows,
)

# SFO's IEM ASOS id is "SFO" (3-letter, not the "KSFO" ICAO), per
# `settlement_alignment_study.IEM_ASOS_IDS`.
_CACHE_TEXT = (
    "station,valid,metar\n"
    # Inside the SFO 2026-09-01 local-standard window ([08:00Z, next 08:00Z)):
    "SFO,2026-09-01 12:00,KSFO 011200Z AUTO 10SM CLR 18/10 A2995 RMK T01780100 MADISHF\n"
    # Just before the window (07:59Z == 2026-08-31 23:59 local) -- excluded.
    "SFO,2026-09-01 07:59,KSFO 010759Z AUTO 10SM CLR 17/09 A2995 RMK T01700090 MADISHF\n"
    # Exactly at the window end (next day 08:00Z) -- half-open, excluded.
    "SFO,2026-09-02 08:00,KSFO 020800Z AUTO 10SM CLR 16/08 A2995 RMK T01600080 MADISHF\n"
    # A different station, inside the same UTC instant -- must never appear
    # in an SFO output file.
    "LAX,2026-09-01 12:00,KLAX 011200Z AUTO 10SM CLR 20/11 A2993 RMK T02000110 MADISHF\n"
)


def _write_cache(tmp_path: Path, text: str = _CACHE_TEXT) -> Path:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "incidental_fetch.txt").write_text(text, encoding="utf-8")
    return cache_dir


# ---------------------------------------------------------------------------
# climate_day_utc_bounds / site_for_station -- pure
# ---------------------------------------------------------------------------


def test_climate_day_utc_bounds_is_the_half_open_local_standard_day_in_utc_ns() -> None:
    start_ns, end_ns = climate_day_utc_bounds(station="SFO", climate_day=dt.date(2026, 9, 1))
    assert start_ns == int(
        dt.datetime(2026, 9, 1, 8, tzinfo=dt.UTC).timestamp() * 1_000_000_000
    )
    assert end_ns == int(
        dt.datetime(2026, 9, 2, 8, tzinfo=dt.UTC).timestamp() * 1_000_000_000
    )
    assert end_ns - start_ns == 24 * 60 * 60 * 1_000_000_000


def test_site_for_station_raises_on_an_unsupported_station() -> None:
    with pytest.raises(AsosCacheCsvError, match="XXX"):
        site_for_station("XXX")


# ---------------------------------------------------------------------------
# windowed_asos_rows
# ---------------------------------------------------------------------------


def test_windowed_rows_excludes_other_stations_and_out_of_window_rows(tmp_path: Path) -> None:
    cache_dir = _write_cache(tmp_path)
    result = windowed_asos_rows(
        station="SFO", climate_day=dt.date(2026, 9, 1), cache_dir=cache_dir
    )
    assert [r["valid"] for r in result.rows] == ["2026-09-01 12:00"]
    assert all(r["station"] == "SFO" for r in result.rows)
    assert result.drops.total() == 0


def test_windowed_rows_is_empty_for_a_cache_with_no_matching_row(tmp_path: Path) -> None:
    cache_dir = _write_cache(tmp_path, text="station,valid,metar\n")
    result = windowed_asos_rows(
        station="SFO", climate_day=dt.date(2026, 9, 1), cache_dir=cache_dir
    )
    assert result.rows == ()
    assert result.drops.total() == 0


def test_windowed_rows_is_empty_for_a_missing_cache_directory(tmp_path: Path) -> None:
    result = windowed_asos_rows(
        station="SFO",
        climate_day=dt.date(2026, 9, 1),
        cache_dir=tmp_path / "does-not-exist",
    )
    assert result.rows == ()
    assert result.drops.total() == 0


def test_windowed_rows_counts_an_unparseable_valid_field_as_a_drop_not_a_silent_omission(
    tmp_path: Path,
) -> None:
    cache_dir = _write_cache(
        tmp_path,
        text=(
            "station,valid,metar\n"
            "SFO,2026-09-01 12:00,KSFO 011200Z AUTO 10SM CLR 18/10 A2995 "
            "RMK T01780100 MADISHF\n"
            # Garbage `valid` field -- must be COUNTED, never silently folded
            # into "outside the window".
            "SFO,not-a-timestamp,KSFO 011300Z AUTO 10SM CLR 18/10 A2995 "
            "RMK T01780100 MADISHF\n"
        ),
    )
    result = windowed_asos_rows(
        station="SFO", climate_day=dt.date(2026, 9, 1), cache_dir=cache_dir
    )
    assert [r["valid"] for r in result.rows] == ["2026-09-01 12:00"]
    assert result.drops["unparseable_valid"] == 1


# ---------------------------------------------------------------------------
# main() -- CLI end to end
# ---------------------------------------------------------------------------


def test_main_writes_exactly_station_valid_metar_for_the_target_station(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("no HTTP client may be constructed by asos_cache_csv")

    monkeypatch.setattr(httpx, "Client", _boom)

    cache_dir = _write_cache(tmp_path)
    out_path = tmp_path / "out" / "asos_SFO_2026-09-01.csv"

    exit_code = main(
        [
            "--station",
            "SFO",
            "--climate-day",
            "2026-09-01",
            "--out",
            str(out_path),
            "--cache-dir",
            str(cache_dir),
        ]
    )

    assert exit_code == 0
    with out_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        data_rows = list(reader)
    assert header == list(CSV_FIELDNAMES)
    assert data_rows == [["SFO", "2026-09-01 12:00", data_rows[0][2]]]


def test_main_exits_nonzero_with_asos_cache_empty_and_writes_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("no HTTP client may be constructed by asos_cache_csv")

    monkeypatch.setattr(httpx, "Client", _boom)

    # A cache that holds rows, but none for SFO 2026-09-01: LAX-only.
    cache_dir = _write_cache(
        tmp_path,
        text=(
            "station,valid,metar\n"
            "LAX,2026-09-01 12:00,KLAX 011200Z AUTO 10SM CLR 20/11 A2993 "
            "RMK T02000110 MADISHF\n"
        ),
    )
    out_path = tmp_path / "out" / "asos_SFO_2026-09-01.csv"

    exit_code = main(
        [
            "--station",
            "SFO",
            "--climate-day",
            "2026-09-01",
            "--out",
            str(out_path),
            "--cache-dir",
            str(cache_dir),
        ]
    )

    assert exit_code != 0
    assert not out_path.exists()


def test_main_exits_with_a_distinct_code_and_writes_no_file_on_unparseable_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unparseable `valid` field fails CLOSED: it is data the replay would
    otherwise silently lack, so it is never treated the same as a row that
    simply falls outside the window (`ASOS_CACHE_EMPTY`).
    """

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("no HTTP client may be constructed by asos_cache_csv")

    monkeypatch.setattr(httpx, "Client", _boom)

    cache_dir = _write_cache(
        tmp_path,
        text=(
            "station,valid,metar\n"
            "SFO,2026-09-01 12:00,KSFO 011200Z AUTO 10SM CLR 18/10 A2995 "
            "RMK T01780100 MADISHF\n"
            "SFO,not-a-timestamp,KSFO 011300Z AUTO 10SM CLR 18/10 A2995 "
            "RMK T01780100 MADISHF\n"
        ),
    )
    out_path = tmp_path / "out" / "asos_SFO_2026-09-01.csv"

    exit_code = main(
        [
            "--station",
            "SFO",
            "--climate-day",
            "2026-09-01",
            "--out",
            str(out_path),
            "--cache-dir",
            str(cache_dir),
        ]
    )

    assert exit_code != 0
    assert exit_code != 2  # distinct from the ASOS_CACHE_EMPTY / bad-station code
    assert not out_path.exists()
    stderr = capsys.readouterr().err
    assert ASOS_CACHE_UNPARSEABLE_ROWS in stderr
    assert "1" in stderr
    assert ASOS_CACHE_EMPTY not in stderr


def test_main_exits_nonzero_for_an_unsupported_station(tmp_path: Path) -> None:
    cache_dir = _write_cache(tmp_path)
    out_path = tmp_path / "out.csv"
    exit_code = main(
        [
            "--station",
            "XXX",
            "--climate-day",
            "2026-09-01",
            "--out",
            str(out_path),
            "--cache-dir",
            str(cache_dir),
        ]
    )
    assert exit_code != 0
    assert not out_path.exists()


# ---------------------------------------------------------------------------
# write_asos_cache_csv -- a comma-bearing METAR must round-trip exactly
# ---------------------------------------------------------------------------


def test_a_metar_containing_a_comma_round_trips_exactly_through_csv_reader(
    tmp_path: Path,
) -> None:
    from asos_cache_csv import write_asos_cache_csv

    metar_with_comma = "KSFO 011200Z AUTO 10SM CLR 18/10 A2995 RMK T01780100 MADISHF, TRAILING"
    out_path = tmp_path / "out.csv"
    write_asos_cache_csv(
        [{"station": "SFO", "valid": "2026-09-01 12:00", "metar": metar_with_comma}],
        out_path,
    )

    with out_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        next(reader)  # header
        (row,) = list(reader)
    assert row == ["SFO", "2026-09-01 12:00", metar_with_comma]

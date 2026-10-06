"""Historical PFM backfill: placement, the pre-2022 LOT layout, and the refusal quarantine.

Fixtures ``pfm_*_real_2021*.txt`` / ``pfm_*_real_2022*.txt`` are public NWS products captured by
the 2021-2026 backfill run (trimmed to the header lines + one point block).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import pytest

from breezy.ingest.pfm_parse import PfmParseError, parse_pfm_product
from breezy.persistence.us_source_revision_store import UsSourceRevisionStore
from scripts.archive import us_source_backfill as bf

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "us_sources"
_NS = 1_000_000_000
_UTC = dt.UTC


def _fixture(name: str) -> str:
    raw = (_FIXTURES / name).read_text(encoding="utf-8")
    return "".join(ln for ln in raw.splitlines(keepends=True) if not ln.startswith("#"))


def _okx_synthetic(header_ddhhmm: str) -> str:
    """The 2026 OKX capture with the WMO header edited and its (now stale) body time dropped."""
    text = _fixture("pfm_okx_real_20261006.txt")
    text = "".join(ln for ln in text.splitlines(keepends=True) if "301 PM EDT" not in ln)
    return text.replace("051901", header_ddhhmm)


# ------------------------------------------------------------- parser: pre-2022 LOT layout


def test_lot_2021_layout_with_utc_row_above_the_local_row_parses() -> None:
    point = parse_pfm_product(
        _fixture("pfm_lot_real_20210101.txt").encode(),
        station="KMDW",
        reference_time=dt.datetime(2021, 1, 1, 0, 15, 1, tzinfo=_UTC),
    )

    assert point.point_name == "Chicago Midway Airport-Cook IL"
    assert point.issued_at == dt.datetime(2021, 1, 1, 0, 15, tzinfo=_UTC)
    # Hand-read from the product: 3hrly MIN/MAX 25 34 29 36 28, then 6hrly MAX/MIN 35 24 36 ...
    assert dict(point.max_by_day) == {
        dt.date(2021, 1, 1): 34,
        dt.date(2021, 1, 2): 36,
        dt.date(2021, 1, 3): 35,
        dt.date(2021, 1, 4): 36,
        dt.date(2021, 1, 5): 38,
        dt.date(2021, 1, 6): 41,
        dt.date(2021, 1, 7): 40,
    }


def test_a_table_whose_hour_rows_are_not_utc_and_local_is_still_refused() -> None:
    raw = _fixture("pfm_lot_real_20210101.txt").replace("UTC 3hrly", "CST 3hrly", 1)

    with pytest.raises(PfmParseError) as err:
        parse_pfm_product(
            raw.encode(),
            station="KMDW",
            reference_time=dt.datetime(2021, 1, 1, 0, 15, 1, tzinfo=_UTC),
        )
    assert err.value.reason == "table_header"


def test_the_2026_layout_is_unchanged_by_the_older_layout_support() -> None:
    point = parse_pfm_product(
        _fixture("pfm_lot_real_20261006.txt").encode(),
        station="KMDW",
        reference_time=dt.datetime(2026, 10, 6, 2, 11, tzinfo=_UTC),
    )
    assert point.point_name == "Chicago Midway Airport-Cook IL"


# ------------------------------------------------- the NWS "MM" missing marker in an extrema row


def _parse_okx_2021(raw: str) -> dict[dt.date, int]:
    point = parse_pfm_product(
        raw.encode(),
        station="KNYC",
        reference_time=dt.datetime(2021, 3, 12, 23, 5, 1, tzinfo=_UTC),
    )
    return dict(point.max_by_day)


def test_an_mm_extrema_cell_is_a_missing_day_not_a_refusal() -> None:
    raw = _fixture("pfm_okx_real_20210312.txt")
    baseline = _parse_okx_2021(raw)

    partial = _parse_okx_2021(raw.replace("          47", "          MM", 1))

    assert len(partial) == len(baseline) - 1
    assert all(baseline[day] == value for day, value in partial.items())


def test_a_product_whose_extrema_are_all_mm_is_refused_as_carrying_no_max() -> None:
    # Real SFO point block of 2022-08-24 18:02Z: every Min/Max cell of both tables is MM.
    with pytest.raises(PfmParseError) as err:
        parse_pfm_product(
            _fixture("pfm_mtr_real_20220824_1802.txt").encode(),
            station="KSFO",
            reference_time=dt.datetime(2022, 8, 24, 18, 2, 1, tzinfo=_UTC),
        )
    assert err.value.reason == "no_max_values"


def test_a_garbled_extrema_cell_is_still_refused() -> None:
    raw = _fixture("pfm_okx_real_20210312.txt").replace("          47", "          4X", 1)

    with pytest.raises(PfmParseError) as err:
        _parse_okx_2021(raw)
    assert err.value.reason == "bad_extrema_cell"


# --------------------------------------------------- placement from the product body


def test_body_issued_line_places_a_product_when_the_cursor_is_months_away() -> None:
    report = bf.LegReport(station="KMDW", wfo="LOT")

    paired = bf._place([_fixture("pfm_lot_real_20210101.txt")], dt.date(2020, 12, 1), report)

    # "615 PM CST Thu Dec 31 2020" == 2021-01-01T00:15Z == WMO 010015
    assert [i for _p, i in paired] == [dt.datetime(2021, 1, 1, 0, 15, tzinfo=_UTC)]
    assert report.refused == {}


def test_body_time_a_minute_off_the_wmo_header_still_places_at_the_wmo_instant() -> None:
    report = bf.LegReport(station="KLAX", wfo="LOX")

    paired = bf._place([_fixture("pfm_lox_real_20220707.txt")], dt.date(2022, 7, 7), report)

    # body "858 AM PDT Thu Jul 7 2022" = 15:58Z; WMO 071559
    assert [i for _p, i in paired] == [dt.datetime(2022, 7, 7, 15, 59, tzinfo=_UTC)]


def test_backwards_wmo_minute_does_not_push_the_product_a_month_ahead() -> None:
    """The live run's MTR stop: 241801 archived after 241802 resolved to Sep 24."""
    report = bf.LegReport(station="KSFO", wfo="MTR")
    products = [
        _fixture("pfm_mtr_real_20220824_1802.txt"),
        _fixture("pfm_mtr_real_20220824_1801.txt"),
    ]

    paired = bf._place(products, dt.date(2022, 8, 22), report)

    assert [i for _p, i in paired] == [
        dt.datetime(2022, 8, 24, 18, 2, tzinfo=_UTC),
        dt.datetime(2022, 8, 24, 18, 1, tzinfo=_UTC),
    ]
    assert report.refused == {}


def test_body_and_wmo_that_disagree_are_refused_not_placed() -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")
    raw = _fixture("pfm_okx_real_20210312.txt").replace("122305", "142305")

    paired = bf._place([raw], dt.date(2021, 3, 12), report)

    assert [i for _p, i in paired] == [None]
    assert report.refused == {"header_body_mismatch": 1}


def test_a_present_but_unparseable_body_zone_is_refused_and_counted() -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")
    raw = _fixture("pfm_okx_real_20210312.txt").replace("EST", "HST")

    paired = bf._place([raw], dt.date(2021, 3, 12), report)

    assert [i for _p, i in paired] == [None]
    assert report.refused == {"body_time_unparseable": 1}


@pytest.mark.parametrize(
    "edit",
    [
        ("EST", "XXX"),
        ("Mar 12 2021", "Mar 32 2021"),
        ("605 PM", "605 QM"),
        ("Mar 12 2021", "Mar 12 2O21"),
    ],
)
def test_a_typo_in_the_body_issuance_line_is_refused_not_cursor_placed(
    edit: tuple[str, str],
) -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")
    raw = _fixture("pfm_okx_real_20210312.txt").replace(*edit)

    paired = bf._place([raw], dt.date(2021, 3, 12), report)

    assert [i for _p, i in paired] == [None]
    assert report.refused == {"body_time_unparseable": 1}


def test_a_product_with_no_body_issuance_line_still_uses_cursor_placement() -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")
    raw = "".join(
        ln
        for ln in _fixture("pfm_okx_real_20210312.txt").splitlines(keepends=True)
        if "605 PM EST" not in ln
    )

    paired = bf._place([raw], dt.date(2021, 3, 12), report)

    assert [i for _p, i in paired] == [dt.datetime(2021, 3, 12, 23, 5, tzinfo=_UTC)]
    assert report.refused == {}


def test_a_body_weekday_that_contradicts_the_date_is_refused() -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")
    raw = _fixture("pfm_okx_real_20210312.txt").replace("Fri Mar 12 2021", "Sat Mar 12 2021")

    paired = bf._place([raw], dt.date(2021, 3, 12), report)

    assert [i for _p, i in paired] == [None]
    assert report.refused == {"body_weekday_mismatch": 1}


def test_a_matching_body_weekday_places_at_the_wmo_instant() -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")
    raw = _fixture("pfm_okx_real_20210312.txt")

    paired = bf._place([raw], dt.date(2021, 3, 12), report)

    assert [i for _p, i in paired] == [dt.datetime(2021, 3, 12, 23, 5, tzinfo=_UTC)]


# ------------------------------------------- placement fallback: refuse one, keep going


def test_same_day_backwards_header_without_a_body_time_is_placed_on_that_day() -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")

    paired = bf._place(
        [_okx_synthetic("051901"), _okx_synthetic("051801")], dt.date(2026, 10, 5), report
    )

    assert [i for _p, i in paired] == [
        dt.datetime(2026, 10, 5, 19, 1, tzinfo=_UTC),
        dt.datetime(2026, 10, 5, 18, 1, tzinfo=_UTC),
    ]


def test_an_earlier_day_header_is_refused_and_the_rest_of_the_page_still_places() -> None:
    report = bf.LegReport(station="KNYC", wfo="OKX")
    products = [_okx_synthetic(h) for h in ("061901", "051901", "071901")]

    paired = bf._place(products, dt.date(2026, 10, 5), report)

    assert [i for _p, i in paired] == [
        dt.datetime(2026, 10, 6, 19, 1, tzinfo=_UTC),
        None,
        dt.datetime(2026, 10, 7, 19, 1, tzinfo=_UTC),
    ]
    assert report.refused == {"unplaceable_header": 1}


class _Clock:
    def __init__(self) -> None:
        self.now = int(dt.datetime(2026, 10, 9, 12, tzinfo=_UTC).timestamp()) * _NS

    def __call__(self) -> int:
        return self.now

    def timestamp_ns(self) -> int:
        return self.now


def _leg(tmp_path: Path, fetch: Any, **kwargs: Any) -> bf.LegReport:
    clock = _Clock()
    return bf.run_pfm_leg(
        station="KNYC",
        start=dt.date(2026, 10, 5),
        end=dt.date(2026, 10, 9),
        fetch=fetch,
        store=UsSourceRevisionStore(tmp_path / "archive", clock),
        clock_ns=clock,
        window_ok=lambda _now: True,
        sleep=lambda _s: None,
        page_limit=10,
        **kwargs,
    )


def test_one_unplaceable_product_does_not_stop_the_station(tmp_path: Path) -> None:
    text = "".join(_okx_synthetic(h) for h in ("051901", "031901", "061901"))

    report = _leg(tmp_path, lambda _w, _s, _l: text)

    assert report.status == "complete"
    assert report.appended == 2
    assert report.refused == {"unplaceable_header": 1}
    assert report.resume_sdate is None


def test_a_page_with_no_placeable_product_still_stops_the_station(tmp_path: Path) -> None:
    text = _okx_synthetic("031901")

    report = _leg(tmp_path, lambda _w, _s, _l: text)

    assert report.status == "unplaceable_header"
    assert report.resume_sdate == dt.date(2026, 10, 5)
    assert report.appended == 0


# ------------------------------------------------------------------ quarantine


def test_refused_products_are_quarantined_verbatim_with_a_reason_line(tmp_path: Path) -> None:
    good, early, garbled = (
        _okx_synthetic("051901"),
        _okx_synthetic("031901"),
        _okx_synthetic("061901"),
    )
    garbled = garbled.replace("Central Park-New York NY", "Central Park-Elsewhere NY")
    text = good + early + garbled
    quarantine = bf.RefusalQuarantine(tmp_path / "q")

    report = _leg(tmp_path, lambda _w, _s, _l: text, quarantine=quarantine)

    lines = [json.loads(ln) for ln in (tmp_path / "q" / "refusals.jsonl").read_text().splitlines()]
    assert {(ln["reason"], ln["station"], ln["wfo"]) for ln in lines} == {
        ("unplaceable_header", "KNYC", "OKX"),
        ("point_not_unique", "KNYC", "OKX"),
    }
    assert report.refused == {"unplaceable_header": 1, "point_not_unique": 1}
    by_reason = {ln["reason"]: ln for ln in lines}
    assert by_reason["unplaceable_header"]["sdate"] == "2026-10-05"
    raw_early = (tmp_path / "q" / by_reason["unplaceable_header"]["raw_file"]).read_bytes()
    assert raw_early == early.encode()
    assert by_reason["point_not_unique"]["issued"] == "2026-10-06T19:01:00+00:00"


def test_no_quarantine_by_default(tmp_path: Path) -> None:
    text = _okx_synthetic("051901") + _okx_synthetic("031901")

    _leg(tmp_path, lambda _w, _s, _l: text)

    assert not (tmp_path / "q").exists()


def _main_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--archive-root", str(tmp_path / "archive"),
        "--start-date", "2026-10-05",
        "--end-date", "2026-10-09",
        "--report-json", str(tmp_path / "report.json"),
        "--legs", "pfm",
        "--stations", "KNYC",
        *extra,
    ]  # fmt: skip


@pytest.mark.parametrize(
    "where",
    ["archive/inside", "holdout/q", "live"],
)
def test_quarantine_dir_inside_the_archive_a_holdout_or_the_live_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    live = tmp_path / "livehome"
    monkeypatch.setattr(bf, "LIVE_DATA_ROOT", live)
    target = live / "q" if where == "live" else tmp_path / where

    code = bf.main(
        _main_args(tmp_path, "--dry-run", "--quarantine-dir", str(target)),
    )

    assert code == 2


def test_main_quarantines_through_the_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    text = _okx_synthetic("051901") + _okx_synthetic("031901")

    def factory(**_kwargs: Any) -> Any:
        return lambda _w, _s, _l: text

    code = bf.main(
        _main_args(
            tmp_path, "--apply", "--request-budget", "50", "--quarantine-dir", str(tmp_path / "q")
        ),
        clock=_Clock(),
        sleep=lambda _s: None,
        pfm_fetch_factory=factory,
    )

    assert code == 0
    reasons = [
        json.loads(ln)["reason"]
        for ln in (tmp_path / "q" / "refusals.jsonl").read_text().splitlines()
    ]
    assert reasons == ["unplaceable_header"]


# ------------------------------ review fixes: guards, MM-only, atomic quarantine

_GOLDEN_MAIN_PARSE: dict[str, tuple[str, str, str, list[tuple[str, int]]]] = {
    # fixture -> (station, issued_at, ...); recorded by running the parser of main (6d1eb4f3)
    "pfm_lot_real_20261006.txt": ("KMDW", "2026-10-06T01:56:00+00:00", "", [
        ("2026-10-06", 73), ("2026-10-07", 76), ("2026-10-08", 68), ("2026-10-09", 67),
        ("2026-10-10", 72), ("2026-10-11", 75), ("2026-10-12", 69)]),
    "pfm_lox_real_20261006.txt": ("KLAX", "2026-10-05T21:52:00+00:00", "", [
        ("2026-10-06", 97), ("2026-10-07", 90), ("2026-10-08", 88), ("2026-10-09", 85),
        ("2026-10-10", 81), ("2026-10-11", 77), ("2026-10-12", 75)]),
    "pfm_mfl_real_20261006.txt": ("KMIA", "2026-10-05T18:21:00+00:00", "", [
        ("2026-10-06", 89), ("2026-10-07", 89), ("2026-10-08", 89), ("2026-10-09", 89),
        ("2026-10-10", 89), ("2026-10-11", 89), ("2026-10-12", 89)]),
    "pfm_mtr_real_20261006.txt": ("KSFO", "2026-10-06T01:00:00+00:00", "", [
        ("2026-10-06", 87), ("2026-10-07", 84), ("2026-10-08", 82), ("2026-10-09", 74),
        ("2026-10-10", 69), ("2026-10-11", 67), ("2026-10-12", 69)]),
    "pfm_okx_real_20261006.txt": ("KNYC", "2026-10-05T19:01:00+00:00", "", [
        ("2026-10-06", 63), ("2026-10-07", 68), ("2026-10-08", 76), ("2026-10-09", 72),
        ("2026-10-10", 69), ("2026-10-11", 68), ("2026-10-12", 71)]),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(_GOLDEN_MAIN_PARSE))
def test_current_layout_real_fixtures_parse_exactly_as_on_main(name: str) -> None:
    station, issued, _unused, expected = _GOLDEN_MAIN_PARSE[name]

    point = parse_pfm_product(
        _fixture(name).encode(),
        station=station,
        reference_time=dt.datetime(2026, 10, 6, 23, 0, tzinfo=_UTC),
    )

    assert point.issued_at.isoformat() == issued
    assert [(d.isoformat(), v) for d, v in point.max_by_day] == expected


def test_a_block_with_no_max_column_and_no_mm_cell_keeps_the_prior_empty_result() -> None:
    # Every Min/Max row emptied: no MM was skipped, so this is not the all-MM refusal.
    lines = _fixture("pfm_okx_real_20261006.txt").splitlines(keepends=True)
    emptied = "".join(
        ln[:14] + "\n" if ln.startswith(("Min/Max", "Max/Min")) else ln for ln in lines
    )
    ref = dt.datetime(2026, 10, 6, 23, 0, tzinfo=_UTC)

    point = parse_pfm_product(emptied.encode(), station="KNYC", reference_time=ref)

    assert point.max_by_day == ()


def _live_apply_args(tmp_path: Path, *extra: str) -> list[str]:
    return _main_args(tmp_path, "--apply", "--quarantine-dir", str(tmp_path / "q"), *extra)


def test_apply_with_a_quarantine_dir_still_requires_the_live_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("BREEZY_LIVE", raising=False)

    code = bf.main(_live_apply_args(tmp_path, "--request-budget", "50"))

    assert code == 2
    assert "BREEZY_LIVE=1 is required" in capsys.readouterr().err


def test_apply_with_a_quarantine_dir_still_requires_a_request_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")

    code = bf.main(_live_apply_args(tmp_path))

    assert code == 2
    assert "--request-budget is required" in capsys.readouterr().err


def test_apply_with_a_quarantine_dir_refuses_a_zero_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")

    code = bf.main(_live_apply_args(tmp_path, "--request-budget", "0"))

    assert code == 2
    assert "--request-budget" in capsys.readouterr().err


def test_quarantine_raw_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_src: Any, _dst: Any) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(os, "replace", boom)
    quarantine = bf.RefusalQuarantine(tmp_path / "q")

    with pytest.raises(OSError, match="rename failed"):
        quarantine.record(
            reason="x", station="KNYC", wfo="OKX", sdate=dt.datetime(2026, 10, 5, tzinfo=_UTC),
            issued=None, raw=b"raw",
        )  # fmt: skip

    assert list((tmp_path / "q").glob("*.raw")) == []
    assert not (tmp_path / "q" / "refusals.jsonl").exists()


def test_quarantine_log_append_is_flushed_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    real_fsync = os.fsync

    def spy(fd: int) -> None:
        synced.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)

    bf.RefusalQuarantine(tmp_path / "q").record(
        reason="x", station="KNYC", wfo="OKX", sdate=dt.datetime(2026, 10, 5, tzinfo=_UTC),
        issued=None, raw=b"raw",
    )  # fmt: skip

    assert synced
    assert (tmp_path / "q" / "refusals.jsonl").read_text().endswith("\n")

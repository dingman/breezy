"""M1 market calibration scan: model-free, Depth10-only, day-block bootstrap, validity STOP.

Fixtures are synthetic catalogs written through Nautilus' own ``ParquetDataCatalog`` writer (L-42),
the same writer and layout the recorder uses.
"""

from __future__ import annotations

import ast
import csv
import datetime as dt
import importlib.util
import random
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "market_calibration_scan.py"
_NS = 1_000_000_000
_DAY = dt.date(2026, 9, 10)


@pytest.fixture(scope="module")
def scan() -> ModuleType:
    spec = importlib.util.spec_from_file_location("market_calibration_scan", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ns(day: dt.date, hour: int, minute: int = 0) -> int:
    return (
        int(dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC).timestamp())
        * _NS
    )


def _side(levels: list[tuple[str, str]], side: OrderSide) -> tuple[list[BookOrder], list[int]]:
    orders = [BookOrder(side, Price(float(p), 2), Quantity(float(s), 2), 0) for p, s in levels]
    counts = [1] * len(orders)
    filler = BookOrder(side, Price(0, 2), Quantity(0, 2), 0)
    while len(orders) < 10:
        orders.append(filler)
        counts.append(0)
    return orders, counts


def _depth(
    slug: str, ts: int, asks: list[tuple[str, str]], bids: list[tuple[str, str]]
) -> OrderBookDepth10:
    bid_orders, bid_counts = _side(bids, OrderSide.BUY)
    ask_orders, ask_counts = _side(asks, OrderSide.SELL)
    return OrderBookDepth10(
        InstrumentId.from_str(f"{slug}.POLYMARKET_US"),
        bid_orders,
        ask_orders,
        bid_counts,
        ask_counts,
        0,
        ts,
        ts,
        ts,
    )


def _slug(station: str, day: dt.date, bucket: str) -> str:
    return f"tc-temp-{station}high-{day.isoformat()}-{bucket}f"


def _write(root: Path, rows: list[OrderBookDepth10]) -> None:
    by_instrument: dict[str, list[OrderBookDepth10]] = {}
    for row in rows:
        by_instrument.setdefault(str(row.instrument_id), []).append(row)
    catalog = ParquetDataCatalog(root)
    for batch in by_instrument.values():
        catalog.write_data(sorted(batch, key=lambda r: r.ts_event))


def _truth_file(
    path: Path, rows: list[tuple[str, dt.date, int]], issued_hour: int = 12, issued_offset: int = 1
) -> Path:
    fields = ["station", "climate_day", "status", "is_final", "tmax_f", "issued_at_utc"]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for station, day, tmax in rows:
            issued = dt.datetime(
                day.year, day.month, day.day, issued_hour, tzinfo=dt.UTC
            ) + dt.timedelta(days=issued_offset)
            writer.writerow(
                {
                    "station": station,
                    "climate_day": day.isoformat(),
                    "status": "FINAL",
                    "is_final": "True",
                    "tmax_f": tmax,
                    "issued_at_utc": issued.isoformat(),
                }
            )
    return path


def _collect(
    scan: ModuleType, root: Path, truth_rows: list[tuple[str, dt.date, int]], tmp: Path
) -> Any:
    truth, last = scan.load_truth(_truth_file(tmp / "truth.csv", truth_rows))
    return scan.collect(root, truth, last)


def test_scan_scopes_windows_by_date_and_hour(scan: ModuleType, tmp_path: Path) -> None:
    slug = _slug("lax", _DAY, "gte72lt73")
    rows = [
        _depth(
            slug, _ns(_DAY - dt.timedelta(days=2), 17, 5), [("0.11", "5")], []
        ),  # wrong date, 17Z
        _depth(
            slug, _ns(_DAY + dt.timedelta(days=1), 17, 5), [("0.12", "5")], []
        ),  # wrong date, 17Z
        _depth(slug, _ns(_DAY, 11, 55), [("0.13", "5")], []),  # right date, wrong hour
        _depth(slug, _ns(_DAY, 17, 5), [("0.31", "5")], []),  # in window
        _depth(slug, _ns(_DAY, 17, 30), [("0.32", "5")], []),  # in window, later
        _depth(slug, _ns(_DAY, 18, 5), [("0.14", "5")], []),  # right date, wrong hour
    ]
    _write(tmp_path / "cat", rows)
    got = _collect(scan, tmp_path / "cat", [("LAX", _DAY, 72)], tmp_path)
    yes = [o for o in got.observations if o.window == "D_17Z" and o.side == "YES"]
    assert [o.ask for o in yes] == [Decimal("0.31")]
    assert {o.window for o in got.observations} == {"D_17Z"}
    lo, hi = scan.window_bounds_ns(_DAY, next(w for w in scan.WINDOWS if w.label == "D_17Z"))
    assert all(lo <= o.ref_ts_ns < hi for o in got.observations)


def test_scan_asserts_ref_ts_lt_settlement(scan: ModuleType, tmp_path: Path) -> None:
    slug = _slug("lax", _DAY, "gte72lt73")
    _write(tmp_path / "cat", [_depth(slug, _ns(_DAY, 17, 5), [("0.31", "5")], [])])
    # Settlement published at 16:00Z on D: before the 17Z reference, so the reference looks ahead.
    truth_path = _truth_file(
        tmp_path / "t.csv", [("LAX", _DAY, 72)], issued_hour=16, issued_offset=0
    )
    rows, last = scan.load_truth(truth_path)
    got = scan.collect(tmp_path / "cat", rows, last)
    assert got.lookahead_failures
    report = scan.build_report(got, None)
    assert report["status"] == "INVALID"
    assert "cells" not in report and "conclusion" not in report
    ok = scan.Observation("LAX", _DAY, "D_17Z", "r", "YES", Decimal("0.3"), 10, 11, True)
    scan.assert_no_lookahead(ok)
    with pytest.raises(scan.LookAheadError):
        scan.assert_no_lookahead(
            scan.Observation("LAX", _DAY, "D_17Z", "r", "YES", Decimal("0.3"), 11, 11, True)
        )
    with pytest.raises(scan.LookAheadError):
        scan.assert_no_lookahead(
            scan.Observation(
                "LAX",
                _DAY,
                "D_17Z",
                "r",
                "YES",
                Decimal("0.3"),
                _ns(_DAY + dt.timedelta(days=1), 1),
                _ns(_DAY + dt.timedelta(days=3), 1),
                True,
            )
        )


def test_scan_uses_depth10_ask_not_quote_tick(scan: ModuleType, tmp_path: Path) -> None:
    slug = _slug("lax", _DAY, "gte72lt73")
    iid = InstrumentId.from_str(f"{slug}.POLYMARKET_US")
    quote = QuoteTick(
        iid,
        Price(0.05, 2),
        Price(0.10, 2),
        Quantity(5, 2),
        Quantity(5, 2),
        _ns(_DAY, 17, 1),
        _ns(_DAY, 17, 1),
    )
    root = tmp_path / "cat"
    ParquetDataCatalog(root).write_data([quote])
    _write(root, [_depth(slug, _ns(_DAY, 17, 2), [("0.45", "5")], [("0.40", "5")])])
    got = _collect(scan, root, [("LAX", _DAY, 72)], tmp_path)
    assert {(o.side, o.ask) for o in got.observations} == {
        ("YES", Decimal("0.45")),
        ("NO", Decimal("0.60")),
    }
    only_quote = tmp_path / "cat2"
    ParquetDataCatalog(only_quote).write_data([quote])
    assert _collect(scan, only_quote, [("LAX", _DAY, 72)], tmp_path).observations == ()


def _obs(scan: ModuleType, day: dt.date, ask: str, hit: bool, n: int = 1) -> list[Any]:
    return [
        scan.Observation("LAX", day, "D_17Z", f"r{i}", "YES", Decimal(ask), 1, 2, hit)
        for i in range(n)
    ]


def test_scan_bootstrap_by_calendar_day(scan: ModuleType) -> None:
    # Six days; each day is internally homogeneous (all hit or all miss), 40 rows per day.
    obs = []
    for i in range(6):
        obs += _obs(scan, dt.date(2026, 9, 1 + i), "0.45", hit=i % 2 == 0, n=40)
    result = scan.build_scan(obs, min_n=30, min_days=5, resamples=2000, seed=7)
    (cell,) = result.cells
    assert cell["n"] == 240 and cell["n_days"] == 6
    # A per-row bootstrap of 240 rows would give a CI half-width near 0.06; whole-day resampling
    # of six day-means in {+0.5, -0.5} is an order of magnitude wider.
    assert cell["ci95_hi"] - cell["ci95_lo"] > 0.4
    # Deterministic under the pinned seed.
    again = scan.build_scan(obs, min_n=30, min_days=5, resamples=2000, seed=7)
    assert again.cells == result.cells


def test_scan_reports_join_coverage_and_invalid_below_95pct(
    scan: ModuleType, tmp_path: Path
) -> None:
    rows = []
    days = [dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(10)]
    for day in days:
        rows.append(
            _depth(_slug("lax", day, "gte72lt73"), _ns(day, 17, 5), [("0.31", "5")], [("0.2", "5")])
        )
    _write(tmp_path / "cat", rows)
    full = [("LAX", d, 72) for d in days]
    good = _collect(scan, tmp_path / "cat", full, tmp_path)
    report = scan.build_report(
        good, scan.build_scan(good.observations, min_n=1, min_days=1, resamples=50)
    )
    assert report["join_coverage"]["horizon"] == 1.0
    assert report["status"] == "VALID" and "cells" in report
    # Truth for 9 of 10 days: coverage 0.9, below the 95% floor.
    short = _collect(scan, tmp_path / "cat", full[:9] + [], tmp_path)
    assert short.tape_station_days == 10
    # The last truth day is day 9, so day 10 is past the horizon; drop a MIDDLE day instead.
    gap = _collect(scan, tmp_path / "cat", full[:4] + full[5:], tmp_path)
    bad = scan.build_report(
        gap, scan.build_scan(gap.observations, min_n=1, min_days=1, resamples=50)
    )
    assert bad["join_coverage"]["horizon"] == pytest.approx(0.9)
    assert bad["join_coverage"]["all_tape_station_days"] == pytest.approx(0.9)
    assert bad["status"] == "INVALID" and "cells" not in bad and "conclusion" not in bad
    assert "SCREENING ONLY" in bad["notice"]


def test_scan_reads_no_model_output() -> None:
    tree = ast.parse(_SCRIPT.read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert modules
    for name in modules:
        assert not name.startswith("breezy.strategy"), name
        assert not any(w in name for w in ("forecast", "calibration", "scoring", "probability")), (
            name
        )


def test_no_side_requires_existing_book_side(scan: ModuleType, tmp_path: Path) -> None:
    assert scan.no_ask({"bids": [], "asks": [["0.50", "5"]]}) is None
    assert scan.no_ask({"bids": [["0.40", "0.5"]], "asks": []}) is None  # size < 1
    assert scan.no_ask({"bids": [["0.40", "5"], ["0.42", "2"]], "asks": []}) == Decimal("0.58")
    assert scan.best_ask({"bids": [["0.4", "5"]], "asks": []}) is None
    assert scan.best_ask({"asks": [["0.50", "0.5"], ["0.55", "1"], ["0.60", "9"]]}) == Decimal(
        "0.55"
    )
    slug = _slug("lax", _DAY, "gte72lt73")
    _write(tmp_path / "cat", [_depth(slug, _ns(_DAY, 17, 5), [("0.31", "5")], [])])
    got = _collect(scan, tmp_path / "cat", [("LAX", _DAY, 72)], tmp_path)
    assert [o.side for o in got.observations] == ["YES"]
    assert got.skipped_no_bid_side == 1


def test_fee_matches_venue_formula_cent_rounded(scan: ModuleType) -> None:
    assert scan.THETA == Decimal("0.0695")
    assert scan.venue_fee(Decimal("0.50")) == Decimal("0.02")  # 0.017375
    assert scan.venue_fee(Decimal("0.10")) == Decimal("0.01")  # 0.006255
    assert scan.venue_fee(Decimal("0.05")) == Decimal("0.00")  # 0.0033
    assert scan.venue_fee(Decimal("0.99")) == Decimal("0.00")
    assert scan.venue_fee(Decimal("0.5"), theta=Decimal("0.5")) == Decimal("0.12")  # 0.125 -> even
    with pytest.raises(ValueError):
        scan.venue_fee(Decimal("1.2"))
    obs = scan.Observation("LAX", _DAY, "D_17Z", "r", "YES", Decimal("0.50"), 1, 2, True)
    assert scan.excess(obs) == pytest.approx(1 - 0.50 - 0.02)
    miss = scan.Observation("LAX", _DAY, "D_17Z", "r", "NO", Decimal("0.50"), 1, 2, False)
    assert scan.excess(miss) == pytest.approx(-0.52)


def test_multiplicity_reported(scan: ModuleType) -> None:
    obs = []
    for i in range(8):
        day = dt.date(2026, 9, 1 + i)
        obs += _obs(scan, day, "0.45", hit=i % 2 == 0, n=10)
        obs += _obs(scan, day, "0.25", hit=i % 3 == 0, n=10)
        obs += [
            scan.Observation("LAX", day, "D_17Z", f"n{k}", "NO", Decimal("0.75"), 1, 2, k % 2 == 0)
            for k in range(10)
        ]
    result = scan.build_scan(obs, min_n=30, min_days=5, resamples=500, seed=3)
    mult = result.multiplicity
    assert mult["tested_cells"] == 3 == len(result.cells)
    assert mult["bonferroni_alpha_per_cell"] == pytest.approx(0.05 / 3)
    assert 0.0 < mult["reality_check_p"] <= 1.0 and 0.0 < mult["spa_p"] <= 1.0
    assert set(mult["best_cell_by_t"]) == {"window", "side", "ask_bin"}
    for cell in result.cells:
        assert cell["p_bonferroni"] == pytest.approx(min(1.0, cell["p_one_sided"] * 3))


def test_out_dir_refuses_live_data_root(scan: ModuleType) -> None:
    with pytest.raises(ValueError, match="live data root"):
        scan.write_outputs(scan.LIVE_DATA_ROOT / "derived" / "m1_scan_test", {})


def test_parse_slug_and_outcome(scan: ModuleType) -> None:
    """The slug token is not the interval: ``gte72lt73f`` is the CLOSED bucket [72, 73] (title
    "72 to 73"), and ``lt62f`` is "61 or below" (venue ``strike_upper_f`` = 61)."""
    spec = scan.parse_slug("tc-temp-sfohigh-2026-09-10-gte72lt73f.POLYMARKET_US")
    assert (spec.station, spec.lower, spec.upper) == ("SFO", 72, 73)
    assert [scan.rung_outcome(spec, t) for t in (71, 72, 73, 74)] == [False, True, True, False]
    low = scan.parse_slug("tc-temp-sfohigh-2026-09-10-lt62f.POLYMARKET_US")
    assert (low.lower, low.upper) == (None, 61)
    assert scan.rung_outcome(low, 61) and not scan.rung_outcome(low, 62)
    top = scan.parse_slug("tc-temp-sfohigh-2026-09-10-gte90f.POLYMARKET_US")
    assert (top.lower, top.upper) == (90, None)
    assert scan.rung_outcome(top, 90) and not scan.rung_outcome(top, 89)
    assert scan.parse_slug("tc-temp-sfolow-2026-09-10-gte90f.POLYMARKET_US") is None


def test_spa_small_for_overwhelming_edge_and_large_for_noise(scan: ModuleType) -> None:
    rng = random.Random(11)
    days = [dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(20)]
    edge, noise = [], []
    for day in days:
        edge += _obs(scan, day, "0.45", hit=True, n=4)  # hits every time at 0.45: huge edge
        for i in range(4):
            noise += [
                scan.Observation(
                    "LAX", day, "D_17Z", f"n{i}", "NO", Decimal("0.60"), 1, 2, rng.random() < 0.62
                )
            ]
    strong = scan.build_scan(edge + noise, min_n=30, min_days=5, resamples=2000, seed=5)
    assert strong.multiplicity["spa_p"] < 0.05
    assert strong.multiplicity["reality_check_p"] < 0.05
    null_only = scan.build_scan(noise, min_n=30, min_days=5, resamples=2000, seed=5)
    assert null_only.multiplicity["spa_p"] > 0.05

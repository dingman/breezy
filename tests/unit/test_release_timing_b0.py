"""F13 Phase B0: read-only tape inventory, placebo feasibility, MDE and B1 family size.

The tape is a synthetic Depth10 catalog under ``tmp_path`` written in the recorder layout
(``data/order_book_depths/<instrument>/*.parquet``); no network, no outcome, no model value.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.analysis import release_timing_b0 as b0

_NS = 1_000_000_000
_SCRIPT = Path(b0.__file__)
_DEPTH = "order_book_depths"


def _utc_ns(day: int, hour: int, minute: int = 0, month: int = 9) -> int:
    return int(dt.datetime(2026, month, day, hour, minute, tzinfo=dt.UTC).timestamp()) * _NS


def _fixed(values: list[float]) -> pa.Array:
    raw = b"".join(round(v * 1e16).to_bytes(16, "little", signed=True) for v in values)
    return pa.FixedSizeBinaryArray.from_buffers(
        pa.binary(16), len(values), [None, pa.py_buffer(raw)]
    )


def _write_depth(
    root: Path,
    instrument: str,
    ts: list[int],
    bid: list[float],
    ask: list[float],
    *,
    bid_size: list[float] | None = None,
    name: str = "2026-09-02T04-00-00-000000000Z_2026-09-03T06-00-00-000000000Z.parquet",
) -> None:
    directory = root / "data" / _DEPTH / instrument
    directory.mkdir(parents=True, exist_ok=True)
    count = len(ts)
    table = pa.table(
        {
            "ts_event": pa.array(ts, type=pa.uint64()),
            "bid_price_0": _fixed(bid),
            "bid_size_0": _fixed(bid_size if bid_size is not None else [1.0] * count),
            "ask_price_0": _fixed(ask),
            "ask_size_0": _fixed([1.0] * count),
        }
    )
    pq.write_table(table, directory / name)


def _instrument(city: str, day: str, band: str) -> str:
    return f"tc-temp-{city}high-{day}-{band}.POLYMARKET_US"


def _synthetic_tape(
    root: Path,
    *,
    days: tuple[int, ...] = (2,),
    step_s: int = 30,
    empty_bid_rows: int = 0,
) -> None:
    """One NYC ladder per listed climate day, quoted 04:00Z of that day to 06:00Z of the next."""
    for day in days:
        ts = list(range(_utc_ns(day, 4), _utc_ns(day + 1, 6), step_s * _NS))
        for index, band in enumerate(("lt80f", "gte80lt81f", "gte82lt83f")):
            bid = [0.20 + 0.05 * math.sin(k / 40.0 + index + day) for k in range(len(ts))]
            ask = [b + 0.02 for b in bid]
            sizes = [0.0 if (index == 1 and k < empty_bid_rows) else 1.0 for k in range(len(ts))]
            instrument = _instrument("nyc", f"2026-09-{day:02d}", band)
            _write_depth(root, instrument, ts, bid, ask, bid_size=sizes)


def _census(path: Path, *, event_days: tuple[int, ...] = (2,), nbp_present: bool = False) -> Path:
    times = [_utc_ns(d, h, 15) for d in event_days for h in range(9, 21)]
    path.write_text(
        json.dumps(
            {
                "pfm": {"OKX": {"issuance_times_ns": times}},
                "nbp": {"vintages_present": nbp_present},
            }
        )
    )
    return path


def _recording_cap(sink: list[float]) -> Callable[[float], int]:
    def cap(gib: float) -> int:
        sink.append(gib)
        return 0

    return cap


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _run(
    tmp_path: Path, argv_extra: list[str] | None = None, **census_kwargs: Any
) -> dict[str, Any]:
    tape = tmp_path / "tape"
    out = tmp_path / "report.json"
    census_path = _census(tmp_path / "census.json", **census_kwargs)
    rc = b0.main(
        [
            "--tape-catalog",
            str(tape),
            "--census-json",
            str(census_path),
            "--since",
            "2026-09-01",
            "--until",
            "2026-09-04",
            "--out",
            str(out),
            *(argv_extra or []),
        ],
        cap=lambda _gib: 0,
    )
    assert rc == 0
    report: dict[str, Any] = json.loads(out.read_text())
    return report


# ------------------------------------------------------------ instrument names


def test_parse_instrument_maps_city_day_and_rung_value() -> None:
    interior = b0.parse_instrument(_instrument("nyc", "2026-09-02", "gte80lt81f"))
    low = b0.parse_instrument(_instrument("mia", "2026-09-02", "lt80f"))
    high = b0.parse_instrument(_instrument("mia", "2026-09-02", "gte94f"))
    assert interior is not None and low is not None and high is not None
    assert (interior.station, interior.climate_day) == ("KNYC", dt.date(2026, 9, 2))
    assert interior.rung_id == "gte80lt81f"
    assert interior.value_f == pytest.approx(80.5)
    assert low.value_f == pytest.approx(79 - b0.TAIL_OFFSET_F)
    assert high.value_f == pytest.approx(94 + b0.TAIL_OFFSET_F)


@pytest.mark.parametrize(
    "name",
    [
        "garbage",
        "tc-temp-xyzhigh-2026-09-02-gte80lt81f.POLYMARKET_US",
        "tc-temp-nychigh-bad-gte80f.X",
    ],
)
def test_parse_instrument_returns_none_for_names_outside_the_five_cities(name: str) -> None:
    assert b0.parse_instrument(name) is None


# ----------------------------------------------------------------- reader


def test_reader_decodes_top_of_book_and_marks_empty_sides(tmp_path: Path) -> None:
    ts = [10 * _NS, 20 * _NS, 30 * _NS]
    _write_depth(tmp_path, "i1", ts, [0.1, 0.2, 0.3], [0.2, 0.3, 0.4], bid_size=[1.0, 0.0, 1.0])

    top = b0.read_top_of_book(tmp_path / "data" / _DEPTH / "i1")

    assert top.ts.tolist() == ts
    assert top.bid[0] == pytest.approx(0.1)
    assert np.isnan(top.bid[1])  # a QuoteTick-style 0.0 would hide this; Depth10 size 0 is empty
    assert top.ask.tolist() == pytest.approx([0.2, 0.3, 0.4])
    assert top.empty_bid_rows == 1


def test_reader_merges_files_in_time_order(tmp_path: Path) -> None:
    _write_depth(tmp_path, "i1", [30 * _NS], [0.3], [0.4], name="b.parquet")
    _write_depth(tmp_path, "i1", [10 * _NS], [0.1], [0.2], name="a.parquet")

    top = b0.read_top_of_book(tmp_path / "data" / _DEPTH / "i1")

    assert top.ts.tolist() == [10 * _NS, 30 * _NS]


# --------------------------------------------------------------- ladder reads


def _rungs() -> list[b0.RungSeries]:
    def series(rung_id: str, value: float, ts: list[int], bid: list[float]) -> b0.RungSeries:
        top = b0.TopOfBook(
            np.array(ts, dtype=np.uint64),
            np.array(bid, dtype=float),
            np.array([x + 0.02 for x in bid], dtype=float),
            0,
        )
        return b0.RungSeries(rung_id, value, top)

    return [
        series("A", 70.5, [10 * _NS, 100 * _NS], [0.20, 0.30]),
        series("B", 72.5, [50 * _NS], [0.40]),  # first quote only at t=50
    ]


def test_ladder_snapshot_carries_the_last_quote_and_omits_unlisted_rungs() -> None:
    snap = b0.ladder_snapshot(_rungs(), 40 * _NS)

    assert set(snap) == {"A"}  # B has no quote at or before 40 s
    assert snap["A"].bid == pytest.approx(0.20)
    later = b0.ladder_snapshot(_rungs(), 60 * _NS)
    assert set(later) == {"A", "B"}


def test_window_change_counts_dropout_and_never_renormalises() -> None:
    # B is quoted at t=60 s but has no two-sided quote at t+delta (series ends one-sided).
    rungs = _rungs()
    rungs[1] = b0.RungSeries(
        "B",
        72.5,
        b0.TopOfBook(
            np.array([50 * _NS, 90 * _NS], dtype=np.uint64),
            np.array([0.40, np.nan]),
            np.array([0.42, 0.45]),
            1,
        ),
    )

    result = b0.window_change(rungs, 60 * _NS, 100 * _NS)

    assert result is not None
    assert result.dropout_rungs == 1
    assert result.panel_rungs == 2
    assert result.change == pytest.approx((0.31 - 0.21) * 70.5)  # B carried flat contributes 0


def test_window_change_is_none_when_no_rung_is_two_sided_at_the_start() -> None:
    assert b0.window_change(_rungs(), 1 * _NS, 100 * _NS) is None


# ----------------------------------------------------------- end to end


def test_b0_reports_tape_inventory_and_whether_depth10_cadence_resolves_60s(
    tmp_path: Path,
) -> None:
    _synthetic_tape(tmp_path / "tape", empty_bid_rows=25)

    report = _run(tmp_path)

    windows = report["tape_inventory"]["station_windows"]
    assert len(windows) == 1
    window = windows[0]
    assert (window["station"], window["climate_day"]) == ("KNYC", "2026-09-02")
    assert window["n_instruments"] == 3
    assert window["resolves_60s"] is True
    assert window["median_gap_s"] == pytest.approx(30.0)
    assert window["empty_bid_row_share"] > 0
    assert window["coverage_fraction"] == pytest.approx(1.0)
    assert report["cadence_60s"]["verdict"] == "RESOLVES"
    assert report["cadence_60s"]["b2_60s_stop_testable"] is True


def test_b0_cadence_that_does_not_resolve_makes_the_b2_stop_untestable(tmp_path: Path) -> None:
    _synthetic_tape(tmp_path / "tape", step_s=600)

    report = _run(tmp_path)

    assert report["cadence_60s"]["verdict"] == "DOES_NOT_RESOLVE"
    assert report["cadence_60s"]["b2_60s_stop_testable"] is False


def test_placebo_pool_feasibility_counted_per_stratum_and_empty_pfm_pool_goes_descriptive(
    tmp_path: Path,
) -> None:
    _synthetic_tape(tmp_path / "tape", days=(2, 3))
    with_pool = _run(tmp_path)
    stratum = with_pool["strata"]["KNYC"]
    assert stratum["source"] == "PFM"
    assert stratum["n_events"] == 12
    assert stratum["same_clock_pool_days_total"] > 0  # 09-03 carries no release in the census
    assert with_pool["placebo"]["pfm_pool_empty"] is False

    # a release at every slot on both tape days leaves no no-update day at the same clock time
    empty = _run(tmp_path, event_days=(2, 3))
    assert empty["strata"]["KNYC"]["same_clock_pool_days_total"] == 0
    assert empty["placebo"]["pfm_pool_empty"] is True
    assert empty["placebo"]["pfm_mode"] == "descriptive_only"
    assert empty["placebo"]["controls_available"] == ["pre_window", "placebo_metar_offset"]


def test_pre_window_control_runs_for_every_event(tmp_path: Path) -> None:
    _synthetic_tape(tmp_path / "tape")

    report = _run(tmp_path)

    arm = report["arms"]["pre_window"]
    assert arm["n_events"] == 12
    assert arm["n_evaluated"] + arm["n_unevaluable"] == 12
    assert arm["n_evaluated"] == 12
    assert {"dropout_rungs", "panel_rungs", "empty_side_rungs"} <= set(arm)


def test_mde_reported_before_any_effect_estimate_and_sd_comes_from_placebo_arms(
    tmp_path: Path,
) -> None:
    _synthetic_tape(tmp_path / "tape", days=(2, 3))

    report = _run(tmp_path)

    assert report["effect_estimate"] is None
    assert report["mde"]["sd_arms"] == ["placebo_metar_offset", "placebo_same_clock", "pre_window"]
    assert "post_release" not in report["arms"]
    assert report["mde"]["sd"] > 0
    assert report["mde"]["by_family_size"]["1"] < report["mde"]["by_family_size"]["2"]
    assert report["mde"]["n_eff"] == pytest.approx(1.0)  # one (station, day) cluster
    assert list(report)[:1] != ["effect_estimate"]


def test_b0_power_prereg_fixes_alpha_0_025_holm2_power_0_8_event_day_cluster(
    tmp_path: Path,
) -> None:
    _synthetic_tape(tmp_path / "tape")

    report = _run(tmp_path)

    assert report["power_prereg"] == {
        "alpha": 0.025,
        "holm_family_max": 2,
        "power": 0.8,
        "analysis_unit": "event-day",
        "cluster": "climate_day",
        "icc": 1.0,
    }


def test_b0_stops_underpowered_when_mde_exceeds_plausible_slope(tmp_path: Path) -> None:
    _synthetic_tape(tmp_path / "tape")

    tiny = _run(tmp_path, ["--plausible-effect", "1e-9"])
    huge = _run(tmp_path, ["--plausible-effect", "1000"])
    unset = _run(tmp_path)

    assert tiny["mde"]["underpowered"] is True
    assert huge["mde"]["underpowered"] is False
    assert unset["mde"]["underpowered"] is None


def test_b1_family_is_pfm_alone_when_nbp_vintages_are_absent_else_two(tmp_path: Path) -> None:
    _synthetic_tape(tmp_path / "tape")

    alone = _run(tmp_path)
    both = _run(tmp_path, nbp_present=True)

    assert alone["b1_family"] == {
        "size": 1,
        "members": ["PFM"],
        "alpha": 0.025,
        "reason": "NBP vintages absent from the node catalog",
    }
    assert both["b1_family"]["size"] == 2
    assert both["b1_family"]["members"] == ["PFM", "NBP"]
    assert both["mde"]["chosen_family_size"] == 2


def test_b0_reads_no_outcome_no_model_value_and_leaves_the_tape_untouched(tmp_path: Path) -> None:
    _synthetic_tape(tmp_path / "tape")
    before = _tree_digest(tmp_path / "tape")

    report = _run(tmp_path)

    assert _tree_digest(tmp_path / "tape") == before
    assert report["inputs"]["outcomes_read"] is False
    assert report["inputs"]["model_values_read"] is False
    assert report["inputs"]["network_used"] is False


def test_main_enforces_the_memory_cap_and_refuses_an_out_path_inside_the_tape(
    tmp_path: Path,
) -> None:
    _synthetic_tape(tmp_path / "tape")
    caps: list[float] = []
    census_path = _census(tmp_path / "census.json")

    rc = b0.main(
        [
            "--tape-catalog",
            str(tmp_path / "tape"),
            "--census-json",
            str(census_path),
            "--out",
            str(tmp_path / "tape" / "report.json"),
            "--max-memory-gib",
            "3",
        ],
        cap=_recording_cap(caps),
    )

    assert rc == 2
    assert not (tmp_path / "tape" / "report.json").exists()
    assert caps == []  # refused before any work


def test_script_imports_no_network_client_no_outcome_and_no_model_module() -> None:
    tree = ast.parse(_SCRIPT.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    flat = " ".join(sorted(imported))
    for banned in (
        "httpx",
        "urllib",
        "socket",
        "requests",
        "settlement",
        "cli_parse",
        "forecast_point",
        "forecast_catalog",
        "iem_mos",
        "nautilus_trader",
    ):
        assert banned not in flat

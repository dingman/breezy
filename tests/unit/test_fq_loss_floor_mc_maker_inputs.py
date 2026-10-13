"""MAKER S3 WP3 review fixes: input schema validation, provenance lines, unknown_share basis."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import fq_loss_floor_mc_maker as maker
from scripts.analysis import fq_loss_floor_mc_maker_inputs as inputs
from tests.unit.test_fq_loss_floor_mc_maker_verdict import CAP_PIN, S2_DOC, _s1_rows, _write

GOOD_ROW: dict[str, Any] = {
    "station": "LAX",
    "climate_day": "2026-09-01",
    "reason": "COVERED",
    "first_seen_ns": 1,
}


def _s1(tmp: Path, lines: list[str]) -> Path:
    path = tmp / "s1.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _good_lines() -> list[str]:
    return [json.dumps(r) for r in _s1_rows(30, 0, 0)]


@pytest.mark.parametrize(
    ("line", "needle"),
    [
        ("[1, 2]", "JSON object"),
        ('"text"', "JSON object"),
        ("{not json", "not JSON"),
        (json.dumps({k: v for k, v in GOOD_ROW.items() if k != "reason"}), "missing reason"),
        (json.dumps({k: v for k, v in GOOD_ROW.items() if k != "station"}), "missing station"),
        (json.dumps({**GOOD_ROW, "first_seen_ns": "5"}), "first_seen_ns"),
        (json.dumps({**GOOD_ROW, "first_seen_ns": True}), "first_seen_ns"),
        (json.dumps({**GOOD_ROW, "reason": "MAYBE"}), "reason"),
        (json.dumps({**GOOD_ROW, "station": ""}), "station"),
        (json.dumps({**GOOD_ROW, "climate_day": 20260901}), "climate_day"),
    ],
)
def test_s1_malformed_row_is_refused_with_file_and_line(
    tmp_path: Path, line: str, needle: str
) -> None:
    lines = [*_good_lines()[:3], line, *_good_lines()[4:]]
    path = _s1(tmp_path, lines)
    with pytest.raises(maker.MakerRefusal, match=needle) as err:
        maker.load_s1(path)
    assert f"{path}:4" in str(err.value)


def test_main_exits_2_with_refused_on_malformed_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pin = _write(tmp_path, "pin.json", CAP_PIN)
    good_s2 = _write(tmp_path, "s2.json", S2_DOC)
    bad_s1 = _s1(tmp_path, ["[1]"])
    argv = ["--binding", "--inputs-only", "--s2-artifact", str(good_s2), "--s5-cap-pin", str(pin)]
    assert maker.main([*argv, "--s1-artifact", str(bad_s1)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("REFUSED:") and "Traceback" not in err
    bad_s2 = _write(tmp_path, "bad.json", {**S2_DOC, "realised_bid_iqr": ["a", 0.8]})
    ok_s1 = _s1(tmp_path, _good_lines())
    swapped = [
        "--binding",
        "--inputs-only",
        "--s2-artifact",
        str(bad_s2),
        "--s5-cap-pin",
        str(pin),
        "--s1-artifact",
        str(ok_s1),
    ]
    assert maker.main(swapped) == 2
    assert capsys.readouterr().err.startswith("REFUSED:")


@pytest.mark.parametrize(
    "iqr",
    [
        ["a", 0.8],
        [True, 0.8],
        [0.7],
        [0.7, 0.8, 0.9],
        "0.7-0.8",
        [-0.1, 0.8],
        [0.7, 1.2],
        [0.8, 0.7],
        [0.72, 0.74],  # does not contain the 0.75 median
        [0.76, 0.78],
        [float("nan"), 0.8],
    ],
)
def test_s2_iqr_is_validated(tmp_path: Path, iqr: Any) -> None:
    path = tmp_path / "s2.json"
    path.write_text(json.dumps({**S2_DOC, "realised_bid_iqr": iqr}), encoding="utf-8")
    with pytest.raises(maker.MakerRefusal, match="realised_bid_iqr"):
        maker.load_s2(path)


def test_s2_iqr_containing_median_is_accepted(tmp_path: Path) -> None:
    s2 = maker.load_s2(_write(tmp_path, "s2.json", {**S2_DOC, "realised_bid_iqr": [0.75, 0.75]}))
    assert s2.bid_iqr == (0.75, 0.75)


def test_s2_refuses_f_pass_above_f_kill(tmp_path: Path) -> None:
    swapped = copy.deepcopy(S2_DOC)
    swapped["fill_rate_2x"] = {"point": 0.22, "lower95": 0.30}
    with pytest.raises(maker.MakerRefusal, match="swapped"):
        maker.load_s2(_write(tmp_path, "s2a.json", swapped))
    k1 = copy.deepcopy(S2_DOC)
    k1["fill_rate_2x_lowest_rung"] = {"point": 0.14, "lower95": 0.20}
    with pytest.raises(maker.MakerRefusal, match="swapped"):
        maker.load_s2(_write(tmp_path, "s2b.json", k1))
    equal = copy.deepcopy(S2_DOC)
    equal["fill_rate_2x"] = {"point": 0.3, "lower95": 0.3}
    assert maker.load_s2(_write(tmp_path, "s2c.json", equal)).f_pass == 0.3


def test_s2_lines_resolve_nested_keys_to_their_own_line(tmp_path: Path) -> None:
    path = _write(tmp_path, "s2.json", S2_DOC)
    s2 = maker.load_s2(path)
    text = path.read_text(encoding="utf-8").splitlines()
    names = (
        "fill_rate_2x.point",
        "fill_rate_2x.lower95",
        "fill_rate_2x_lowest_rung.point",
        "fill_rate_2x_lowest_rung.lower95",
        "fill_rate_base.point",
    )
    numbers = [s2.lines[name] for name in names]
    assert len(set(numbers)) == len(numbers)
    for name, number in zip(names, numbers, strict=True):
        assert f'"{name.rsplit(".", 1)[-1]}"' in text[number - 1]
    parent = {
        n: next(i for i, t in enumerate(text, 1) if f'"{n.split(".")[0]}"' in t) for n in names
    }
    assert all(s2.lines[n] > parent[n] for n in names)
    assert s2.lines["fill_rate_2x.point"] < s2.lines["fill_rate_2x_lowest_rung.point"]
    assert '"n0"' in text[s2.lines["n0"] - 1]
    assert inputs._line("{}", "missing.key") == 0


def test_s2_records_raw_icc_and_clamp(tmp_path: Path) -> None:
    low = maker.load_s2(_write(tmp_path, "s2.json", {**S2_DOC, "fill_icc": 0.01}))
    assert low.fill_icc_raw == 0.01 and low.fill_icc == maker.FILL_ICC


def test_unknown_share_basis_is_four_station_and_all_rows_is_recorded() -> None:
    rows = _s1_rows(listed=10, unlisted=0, outage_days=2)
    rows += [  # six covered rows of a non-four station: only the all-rows denominator sees them
        {
            "station": "DEN",
            "climate_day": f"2026-10-{d:02d}",
            "reason": "COVERED",
            "first_seen_ns": 1,
        }
        for d in range(1, 7)
    ]
    rate = maker.listing_rate_4stn(rows)
    assert rate.unknown_share == pytest.approx(8 / 48)  # 8 unknown / 48 four-station rows
    assert rate.unknown_share_all_rows == pytest.approx(10 / 66)  # incl. the DEN rows
    assert rate.rows == len(rows)
    assert (
        "four_station" in inputs.UNKNOWN_SHARE_BASIS
        and "all non-PRE_TRADE" in inputs.UNKNOWN_SHARE_BASIS
    )
    assert "unknown_share" in (inputs.__doc__ or "") and "Deviation" in (inputs.__doc__ or "")

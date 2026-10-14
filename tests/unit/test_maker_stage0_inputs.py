"""MAKER-S2 WP1: census, trade-unit and truth loaders; the V0 effective-n estimator; the fixture.

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP1 + r4 delta (a)(k).
Nothing here reads a real catalog, truth store or node log: fixtures and ``tmp_path`` only.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.analysis.maker_tape_census import (
    REASONS,
    read_censused_days,
    summarise,
    write_censused_days,
)
from scripts.analysis.maker_stage0_inputs import (
    InputRefused,
    TradeUnit,
    TruthConflict,
    TruthTable,
    UnitHypothesis,
    UnitRefused,
    is_underpowered,
    load_census_days,
    load_trade_unit,
    load_truth,
    n_eff_gov,
    per_date_counts,
)
from tests.fixtures.maker_stage0 import make_census_fixture as fx

DAY = dt.date(2026, 9, 20)


# --- shared fixture -----------------------------------------------------------------------


def test_shared_fixture_round_trips_write_read_censused_days(tmp_path: Path) -> None:
    rows = fx.census_grid(
        n_days=3, overrides={("MIA", dt.date(2026, 9, 19)): {"reason": "LONG_HOLE"}}
    )
    path = fx.write_census_fixture(tmp_path / "censused_days.jsonl", rows)
    back = read_censused_days(path)
    assert sorted(back, key=lambda r: (r.station, r.climate_day)) == sorted(
        rows, key=lambda r: (r.station, r.climate_day)
    )
    assert {r.reason for r in back} <= set(REASONS)
    # Every serialised key comes from the dataclass itself.
    raw = json.loads(path.read_text().splitlines()[0])
    assert set(raw) == set(rows[0].to_dict())
    # Byte-idempotent through S1's own writer.
    again = tmp_path / "again.jsonl"
    write_censused_days(again, back)
    assert again.read_bytes() == path.read_bytes()


def test_fixture_unit_verdict_set_is_the_three_s1_hypotheses() -> None:
    assert set(fx.UNIT_VERDICT_SET) == {"CONTRACTS", "USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER"}
    assert fx.unit_verdict_json("BRACKETED_USD")["surviving"] == [
        "USD_NOTIONAL_TAKER",
        "USD_NOTIONAL_YES",
    ]


def test_fixture_fails_loudly_when_the_census_schema_drifts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drifted = {**fx._DEFAULTS, "a_new_s1_field": 1}
    monkeypatch.setattr(fx, "_DEFAULTS", drifted)
    with pytest.raises(AssertionError, match="a_new_s1_field"):
        fx.census_row()


# --- census loader ------------------------------------------------------------------------


def test_load_census_days_filters_and_counts_nyc(tmp_path: Path) -> None:
    rows = [*fx.census_grid(n_days=2), fx.census_row("NYC", DAY)]
    path = fx.write_census_fixture(tmp_path / "c.jsonl", rows)
    loaded = load_census_days(path)
    assert loaded.nyc_filtered == 1
    assert {r.station for r in loaded.rows} == {"LAX", "MDW", "MIA", "SFO"}
    assert len(loaded.rows) == 8


def test_load_census_days_refuses_a_schema_violation(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    body = fx.census_row().to_dict()
    body["surprise"] = 1
    path.write_text(json.dumps(body) + "\n")
    with pytest.raises(ValueError, match="differ from the schema"):
        load_census_days(path)


def test_load_census_days_refuses_an_unknown_station(tmp_path: Path) -> None:
    path = fx.write_census_fixture(tmp_path / "c.jsonl", [fx.census_row("DEN", DAY)])
    with pytest.raises(InputRefused, match="DEN"):
        load_census_days(path)


# --- V0 effective n (r4 delta (a)) --------------------------------------------------------


def test_n_eff_gov_equals_s1_n_eff_on_same_per_date() -> None:
    rows = [
        *fx.census_grid(n_days=4),
        *[fx.census_row("SFO", dt.date(2026, 9, 25) + dt.timedelta(days=i)) for i in range(3)],
        fx.census_row("LAX", dt.date(2026, 9, 25)),
    ]
    assert all(r.reason == "COVERED" for r in rows)
    expected = summarise(rows).n_eff_ub
    assert n_eff_gov(per_date_counts(rows)) == pytest.approx(expected, rel=0, abs=1e-12)
    assert n_eff_gov({}) == 0.0


def test_below_the_s1_floor_is_underpowered_and_at_the_floor_is_not() -> None:
    # 8 dates x 4 station-days: 8 * 4 / (1 + 3 * 0.5) = 12.8 < 30 (r4 (b), "without E5").
    assert is_underpowered(n_eff_gov({DAY + dt.timedelta(days=i): 4 for i in range(8)}))
    assert not is_underpowered(30.0)
    assert is_underpowered(29.999)


def test_n_eff_gov_does_not_import_the_private_s1_helper() -> None:
    source = Path("scripts/analysis/maker_stage0_inputs.py").read_text()
    assert "_n_eff" not in source.replace("n_eff_gov", "")


# --- trade unit ---------------------------------------------------------------------------


def test_unresolved_trade_unit_is_refused(tmp_path: Path) -> None:
    path = fx.write_unit_fixture(tmp_path / "unit.json", "UNRESOLVED")
    with pytest.raises(UnitRefused, match="UNRESOLVED"):
        load_trade_unit(path)


def test_bracketed_unit_yields_two_hypotheses(tmp_path: Path) -> None:
    unit = load_trade_unit(fx.write_unit_fixture(tmp_path / "unit.json", "BRACKETED_USD"))
    hyps = unit.hypotheses()
    assert [h.name for h in hyps] == ["USD_NOTIONAL_TAKER", "USD_NOTIONAL_YES"]
    size, price = Decimal("2.50"), Decimal("0.25")
    by_name = {h.name: h for h in hyps}
    assert by_name["USD_NOTIONAL_YES"].to_contracts(size, price) == Decimal(10)
    assert by_name["USD_NOTIONAL_TAKER"].to_contracts(size, price, aggressor="BUYER") == Decimal(10)
    # A SELLER print is a NO purchase: the taker paid 1 - yes_price per contract.
    assert by_name["USD_NOTIONAL_TAKER"].to_contracts(
        Decimal("1.50"), price, aggressor="SELLER"
    ) == Decimal(2)


@pytest.mark.parametrize("verdict", ["CONTRACTS", "USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER"])
def test_resolved_unit_yields_one_hypothesis(tmp_path: Path, verdict: str) -> None:
    unit = load_trade_unit(fx.write_unit_fixture(tmp_path / "u.json", verdict))
    (only,) = unit.hypotheses()
    assert only.name == verdict
    if verdict == "CONTRACTS":
        assert only.to_contracts(Decimal(7), Decimal("0.4")) == Decimal(7)


def test_taker_unit_needs_the_aggressor_side(tmp_path: Path) -> None:
    unit = load_trade_unit(fx.write_unit_fixture(tmp_path / "u.json", "USD_NOTIONAL_TAKER"))
    with pytest.raises(UnitRefused, match="aggressor"):
        unit.hypotheses()[0].to_contracts(Decimal(1), Decimal("0.5"))


@pytest.mark.parametrize("price", [Decimal(0), Decimal(1), Decimal("-0.1")])
def test_conversion_refuses_a_price_outside_the_open_unit_interval(price: Decimal) -> None:
    unit = TradeUnit.from_result(fx.unit_verdict_json("USD_NOTIONAL_YES"))
    with pytest.raises(UnitRefused, match="price"):
        unit.hypotheses()[0].to_contracts(Decimal(1), price)


@pytest.mark.parametrize(
    "mutation",
    [
        {"verdict": "MAYBE"},
        {"s2_stop": True},
        {"surviving": []},
        {"verdict": "CONTRACTS", "surviving": ["USD_NOTIONAL_YES"]},
    ],
)
def test_unit_result_that_is_inconsistent_is_refused(
    tmp_path: Path, mutation: dict[str, object]
) -> None:
    body = {**fx.unit_verdict_json("CONTRACTS"), **mutation}
    path = tmp_path / "u.json"
    path.write_text(json.dumps(body))
    with pytest.raises(UnitRefused):
        load_trade_unit(path)


def test_unit_file_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "u.json"
    path.write_text("{not json")
    with pytest.raises(UnitRefused):
        load_trade_unit(path)


def test_unknown_unit_hypothesis_name_is_refused() -> None:
    with pytest.raises(UnitRefused, match="BOGUS"):
        UnitHypothesis("BOGUS")


# --- truth --------------------------------------------------------------------------------

_CSV_HEAD = "station,climate_day,tmax_f,tmax_flag,correction_flag,product_sha256\n"
SEALED = dt.date(2026, 10, 1)


def _csv(path: Path, *rows: str) -> Path:
    path.write_text(_CSV_HEAD + "".join(row + "\n" for row in rows))
    return path


def _parquet(path: Path, rows: list[dict[str, object]]) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            ("station", pa.string()),
            ("climate_day", pa.date32()),
            ("status", pa.string()),
            ("tmax_f", pa.int64()),
        ]
    )
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    return path


def _pq_row(station: str, day: str, tmax: int | None, status: str = "FINAL") -> dict[str, object]:
    return {
        "station": station,
        "climate_day": dt.date.fromisoformat(day),
        "status": status,
        "tmax_f": tmax,
    }


def _keys(*pairs: tuple[str, dt.date]) -> frozenset[tuple[str, dt.date]]:
    return frozenset(pairs) or frozenset({("SFO", DAY)})


def _load(
    tmp_path: Path,
    csv_path: Path,
    rows: list[dict[str, object]] | None = None,
    *,
    expected_csv_sha256: str | None = None,
) -> TruthTable:
    chosen = rows if rows is not None else [_pq_row("SFO", "2026-09-20", 70)]
    cross = _parquet(tmp_path / "x.parquet", chosen)
    return load_truth(
        csv_path,
        cross,
        tmp_path / "run",
        keys=_keys(),
        expected_csv_sha256=expected_csv_sha256,
    )


def test_load_truth_keeps_final_rows_copies_and_pins_the_csv(tmp_path: Path) -> None:
    csv_path = _csv(
        tmp_path / "truth.csv",
        "SFO,2026-09-20,71,,False,aa",
        "LAX,2026-09-20,,M,False,bb",  # sentinel reading: not final-grade
        "NYC,2026-09-20,60,,False,cc",  # never admitted
    )
    cross = _parquet(tmp_path / "x.parquet", [_pq_row("SFO", "2026-09-20", 71)])
    run_dir = tmp_path / "run"
    keys = _keys(("SFO", DAY), ("LAX", DAY), ("NYC", DAY))
    table = load_truth(csv_path, cross, run_dir, keys=keys)
    assert table.finals == {("SFO", DAY): 71}
    assert table.csv_sha256 == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert table.run_copy.read_bytes() == csv_path.read_bytes()
    assert table.run_copy.parent == run_dir
    assert table.n_overlap == 1
    assert table.cross_check_sha256 == hashlib.sha256(cross.read_bytes()).hexdigest()


def test_truth_conflict_between_sources_raises_without_printing_values(tmp_path: Path) -> None:
    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,71,,False,aa")
    with pytest.raises(TruthConflict, match="SFO") as info:
        _load(tmp_path, csv_path, [_pq_row("SFO", "2026-09-20", 72)])
    assert "71" not in str(info.value) and "72" not in str(info.value)
    assert not (tmp_path / "run" / "truth_cli_finals.csv").exists()


def test_a_correction_row_takes_the_final_revision(tmp_path: Path) -> None:
    csv_path = _csv(
        tmp_path / "t.csv",
        "SFO,2026-09-20,70,,False,aa",
        "SFO,2026-09-20,72,,True,bb",
    )
    table = _load(tmp_path, csv_path, [_pq_row("SFO", "2026-09-20", 72)])
    assert table.finals[("SFO", DAY)] == 72


def test_two_conflicting_uncorrected_rows_raise_without_printing_values(tmp_path: Path) -> None:
    csv_path = _csv(
        tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa", "SFO,2026-09-20,72,,False,bb"
    )
    with pytest.raises(TruthConflict) as info:
        _load(tmp_path, csv_path)
    assert "70" not in str(info.value) and "72" not in str(info.value)


def test_truth_csv_with_a_missing_column_is_refused(tmp_path: Path) -> None:
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("station,climate_day,tmax_f\nSFO,2026-09-20,70\n")
    with pytest.raises(InputRefused, match="column"):
        _load(tmp_path, csv_path)


def test_truth_csv_sha_must_match_the_pinned_sha_when_given(tmp_path: Path) -> None:
    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa")
    with pytest.raises(InputRefused, match="sha256"):
        _load(tmp_path, csv_path, expected_csv_sha256="0" * 64)


def test_rows_outside_the_licensed_keys_are_never_parsed(tmp_path: Path) -> None:
    # The sealed day and a post-10-13 day carry values that would raise if parsed.
    csv_path = _csv(
        tmp_path / "t.csv",
        "SFO,2026-09-20,70,,False,aa",
        "SFO,2026-10-01,SEALED-ABC,,False,bb",
        "SFO,2026-10-14,70.5,,False,cc",
        "DEN,2026-09-20,zzz,,False,dd",
    )
    table = _load(tmp_path, csv_path)
    assert table.finals == {("SFO", DAY): 70}
    assert table.csv_sha256 == hashlib.sha256(csv_path.read_bytes()).hexdigest()


def test_cross_check_rows_outside_the_licensed_keys_are_not_compared(tmp_path: Path) -> None:
    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa")
    rows = [_pq_row("SFO", "2026-09-20", 70), _pq_row("SFO", "2026-10-01", 1)]
    assert _load(tmp_path, csv_path, rows).n_overlap == 1


def test_load_truth_refuses_an_empty_key_set(tmp_path: Path) -> None:
    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa")
    cross = _parquet(tmp_path / "x.parquet", [_pq_row("SFO", "2026-09-20", 70)])
    with pytest.raises(InputRefused, match="keys"):
        load_truth(csv_path, cross, tmp_path / "run", keys=frozenset())


@pytest.mark.parametrize(
    "row",
    ["SFO,2026-09-20", "SFO,2026-09-20,70,,False,aa,EXTRA"],
    ids=["truncated", "extra-cell"],
)
def test_a_malformed_csv_row_is_refused_not_dropped(tmp_path: Path, row: str) -> None:
    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa", row)
    with pytest.raises(InputRefused, match="row 3"):
        _load(tmp_path, csv_path)


@pytest.mark.parametrize("tmax", ["abc", "70.0", "9" * 40 + "x"])
def test_a_non_integer_tmax_on_a_licensed_row_is_refused_without_the_value(
    tmp_path: Path, tmax: str
) -> None:
    csv_path = _csv(tmp_path / "t.csv", f"SFO,2026-09-20,{tmax},,False,aa")
    with pytest.raises(InputRefused, match="SFO") as info:
        _load(tmp_path, csv_path)
    assert tmax not in str(info.value)


def test_a_bad_correction_flag_is_refused(tmp_path: Path) -> None:
    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,maybe,aa")
    with pytest.raises(InputRefused, match="correction_flag"):
        _load(tmp_path, csv_path)


def test_a_non_utf8_csv_is_refused(tmp_path: Path) -> None:
    csv_path = tmp_path / "t.csv"
    csv_path.write_bytes(_CSV_HEAD.encode() + b"SFO,2026-09-20,70,,False,\xff\xfe\n")
    with pytest.raises(InputRefused, match="utf-8"):
        _load(tmp_path, csv_path)


def test_a_missing_truth_csv_or_cross_check_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InputRefused, match="truth csv"):
        _load(tmp_path, tmp_path / "nope.csv")
    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa")
    with pytest.raises(InputRefused, match="cross-check"):
        load_truth(csv_path, tmp_path / "nope.parquet", tmp_path / "run", keys=_keys())


def test_an_unreadable_or_schema_broken_cross_check_is_refused(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa")
    garbage = tmp_path / "garbage.parquet"
    garbage.write_bytes(b"not a parquet file")
    with pytest.raises(InputRefused, match="cross-check"):
        load_truth(csv_path, garbage, tmp_path / "run", keys=_keys())
    lacking = tmp_path / "lacking.parquet"
    pq.write_table(pa.table({"station": ["SFO"]}), lacking)
    with pytest.raises(InputRefused, match="cross-check"):
        load_truth(csv_path, lacking, tmp_path / "run", keys=_keys())


def test_a_cross_check_whose_climate_day_is_not_a_date_is_refused(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa")
    stringly = tmp_path / "str.parquet"
    pq.write_table(
        pa.table(
            {
                "station": ["SFO"],
                "climate_day": ["2026-09-20"],
                "status": ["FINAL"],
                "tmax_f": [70],
            }
        ),
        stringly,
    )
    with pytest.raises(InputRefused, match="date"):
        load_truth(csv_path, stringly, tmp_path / "run", keys=_keys())


def test_a_cross_check_with_no_overlap_is_refused_as_vacuous(tmp_path: Path) -> None:
    csv_path = _csv(tmp_path / "t.csv", "SFO,2026-09-20,70,,False,aa")
    with pytest.raises(InputRefused, match="overlap"):
        _load(tmp_path, csv_path, [_pq_row("LAX", "2026-08-01", 80)])
    assert not (tmp_path / "run" / "truth_cli_finals.csv").exists()

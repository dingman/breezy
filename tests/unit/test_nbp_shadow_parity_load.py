"""S4a RED: real-partition loading, LST climate day, and the NO-depth census.

`docs/plans/FQ_GO_LIVE_PLAN_2026-10-01.md` §3 S4a. The fixture mirrors the
real 13Z grid (first MAX column is FHR 35, 00Z on UTC day D+2), not a
closer invented 00Z. KLAX std offset -8 makes that column's LST climate
day equal D+1 of the cycle.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

import scripts.analysis.nbp_shadow_parity as live_module
from breezy.ingest.gaps import local_standard_date
from breezy.persistence.nbp_derived_store import DerivedNbpRow, write_partition
from breezy.strategy.ladder_ev.forecast_state import (
    NBP_QUANTILE_VARIABLES,
    ForecastQuantileState,
)
from scripts.analysis.nbp_shadow_parity_pure import (
    DepthSnapshotRow,
    diff_decision_keys,
)

_NS = 1_000_000_000
_KLAX_OFFSET_HOURS = -8.0
_CYCLE = dt.datetime(2026, 9, 20, 13, tzinfo=dt.UTC)
_NEAREST_VALID = dt.datetime(2026, 9, 22, tzinfo=dt.UTC)
_N_LEADS = 9
_NEAREST_VERSION = "5.0"
_LATER_VERSION = "4.2"


def _ns(instant: dt.datetime) -> int:
    return int(instant.timestamp()) * _NS


def _partition_rows() -> tuple[DerivedNbpRow, ...]:
    cycle_ns = _ns(_CYCLE)
    rows: list[DerivedNbpRow] = []
    for lead in range(_N_LEADS):
        valid_ns = _ns(_NEAREST_VALID + dt.timedelta(days=lead))
        version = _NEAREST_VERSION if lead == 0 else _LATER_VERSION
        for index, variable in enumerate(NBP_QUANTILE_VARIABLES):
            rows.append(
                DerivedNbpRow(
                    station="KLAX",
                    variable=variable,
                    cycle_runtime_ns=cycle_ns,
                    valid_start_ns=valid_ns,
                    valid_end_ns=valid_ns,
                    value_f=70.0 + index if lead == 0 else 0.0,
                    absence_reason=None,
                    header_model_version=version,
                    nbm_version_era=f"v{version}",
                    version_break_mismatch=False,
                    available_at_ns=cycle_ns + 3_600 * _NS,
                    last_modified=None,
                    source_host="test",
                    raw_sha256="0" * 64,
                    fetched_at_ns=cycle_ns,
                ),
            )
    return tuple(rows)


def test_nine_max_leads_load_as_one_lst_d_plus_1_cycle(tmp_path: Path) -> None:
    cycle_ns = _ns(_CYCLE)
    lst_d_plus_1 = local_standard_date(cycle_ns, _KLAX_OFFSET_HOURS) + dt.timedelta(days=1)
    assert lst_d_plus_1 == dt.date(2026, 9, 21)
    root = tmp_path / "nbp"
    write_partition(_partition_rows(), root / "2026" / "09" / "nbp_20260920_13z.parquet")

    loaded = live_module._load_nbp_rows(
        root,
        start=dt.date(2026, 9, 21),
        end=dt.date(2026, 9, 30),
    )
    state = ForecastQuantileState()
    for row in loaded:
        state.push(
            variable=row.variable,
            value_f=row.value_f,
            available_at_ns=row.available_at_ns,
            cycle_runtime_ns=row.cycle_runtime_ns,
            climate_day=row.climate_day,
        )

    assert len(loaded) == len(NBP_QUANTILE_VARIABLES)
    assert {row.climate_day for row in loaded} == {lst_d_plus_1}
    assert {row.header_model_version for row in loaded} == {_NEAREST_VERSION}
    assert {row.value_f for row in loaded} == {70.0 + index for index in range(7)}
    vector = state.value_at(cycle_ns + 3_600 * _NS)
    assert vector is not None
    assert vector.climate_day == lst_d_plus_1


def test_the_written_report_carries_the_no_depth_census() -> None:
    report = diff_decision_keys((), ())
    day = dt.date(2026, 9, 2)
    rows = (
        DepthSnapshotRow(
            instrument_id="MIA-2026-09-02-80_81.POLY_US",
            ts_ns=1,
            best_ask_price=0.10,
            best_ask_size=1.0,
            station="MIA",
            climate_day=day,
            rung_id="80_81",
            side="no",
        ),
        DepthSnapshotRow(
            instrument_id="MIA-2026-09-02-80_81.POLY_US",
            ts_ns=2,
            best_ask_price=0.11,
            best_ask_size=1.0,
            station="MIA",
            climate_day=day,
            rung_id="80_81",
            side="yes",
        ),
    )

    payload = live_module._parity_report_payload(report, rows)

    assert payload["no_depth_days_by_station"] == {"MIA": 1}
    assert payload["n_mismatches"] == 0


def test_no_depth_census_counts_distinct_days_per_station() -> None:
    from scripts.analysis.nbp_shadow_parity_pure import no_depth_census

    rows = (
        DepthSnapshotRow(
            instrument_id="KMIA-2026-09-02-i1.POLY_US",
            ts_ns=1,
            best_ask_price=0.10,
            best_ask_size=1.0,
            station="KMIA",
            climate_day=dt.date(2026, 9, 2),
            rung_id="i1",
            side="no",
        ),
        DepthSnapshotRow(
            instrument_id="KMIA-2026-09-02-i2.POLY_US",
            ts_ns=2,
            best_ask_price=0.12,
            best_ask_size=1.0,
            station="KMIA",
            climate_day=dt.date(2026, 9, 2),
            rung_id="i2",
            side="no",
        ),
        DepthSnapshotRow(
            instrument_id="KMIA-2026-09-03-i1.POLY_US",
            ts_ns=3,
            best_ask_price=0.13,
            best_ask_size=1.0,
            station="KMIA",
            climate_day=dt.date(2026, 9, 3),
            rung_id="i1",
            side="no",
        ),
        DepthSnapshotRow(
            instrument_id="KLAX-2026-09-02-i1.POLY_US",
            ts_ns=4,
            best_ask_price=0.20,
            best_ask_size=1.0,
            station="KLAX",
            climate_day=dt.date(2026, 9, 2),
            rung_id="i1",
            side="yes",
        ),
        DepthSnapshotRow(
            instrument_id="KSFO-2026-09-04-i1.POLY_US",
            ts_ns=5,
            best_ask_price=0.30,
            best_ask_size=1.0,
            side="no",
        ),
    )

    assert no_depth_census(rows) == {"KLAX": 0, "KMIA": 2, "KSFO": 1}


def test_side_kind_counts_cover_both_paths() -> None:
    from scripts.analysis.nbp_shadow_parity_pure import DecisionKey

    def key(*, side: Literal["yes", "no"], action: str, ts_ns: int) -> DecisionKey:
        return DecisionKey(
            station="KMIA",
            climate_day=dt.date(2026, 9, 2),
            rung_id="i1",
            instrument_id="KMIA-2026-09-02-i1.POLY_US",
            side=side,
            action=action,
            reason=None,
            ts_ns=ts_ns,
        )

    live = (
        key(side="yes", action="Take", ts_ns=1),
        key(side="no", action="Refuse", ts_ns=2),
        key(side="yes", action="NotExecutable", ts_ns=3),
    )
    batch = (
        key(side="yes", action="Take", ts_ns=1),
        key(side="no", action="NotDPlus1", ts_ns=4),
    )
    counts = diff_decision_keys(live, batch).to_counts_dict()

    assert counts["n_live_yes_Take"] == 1
    assert counts["n_live_no_Refuse"] == 1
    assert counts["n_live_yes_NotExecutable"] == 1
    assert counts["n_live_no_Take"] == 0
    assert counts["n_batch_yes_Take"] == 1
    assert counts["n_batch_no_NotDPlus1"] == 1
    assert counts["n_batch_yes_NotDPlus1"] == 0
    live_kind_total = sum(
        counts[f"n_live_{side}_{kind}"]
        for side in ("yes", "no")
        for kind in ("NotDPlus1", "NotExecutable", "Refuse", "Take")
    )
    assert live_kind_total == counts["n_live"] == 3


def test_loader_passes_date_and_instrument_bounds_to_the_catalog(tmp_path: Path) -> None:
    """The depth query must not be catalog-wide: ids and a ts window, both set."""
    from nautilus_trader.model.data import OrderBookDepth10
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.instruments import BinaryOption

    in_window = "tc-temp-laxhigh-2026-09-01-gte80lt81f.POLYMARKET_US"
    also_in_window = "tc-temp-miahigh-2026-09-01-lt80f^no.POLYMARKET_US"
    out_of_window = "tc-temp-laxhigh-2026-09-08-gte80lt81f.POLYMARKET_US"
    option_root = tmp_path / "data" / "binary_option"
    for name in (in_window, also_in_window, out_of_window):
        (option_root / name).mkdir(parents=True)

    class _Instrument:
        def __init__(self) -> None:
            self.id = InstrumentId.from_str(in_window)
            self.info = {
                "weather_facts_status": "KNOWN",
                "settlement_station": "LAX",
                "climate_date": "2026-09-01",
                "measure": "high",
                "strike_lower_f": 80,
                "strike_upper_f": 81,
            }

    instrument = _Instrument()

    class _RecordingCatalog:
        def __init__(self) -> None:
            self.queries: list[dict[str, object]] = []

        def query(self, data_cls: type, **kwargs: object) -> list[object]:
            self.queries.append({"data_cls": data_cls, **kwargs})
            identifiers = kwargs.get("identifiers")
            if (
                data_cls is BinaryOption
                and isinstance(identifiers, list)
                and in_window in identifiers
            ):
                return [instrument]
            return []

    catalog = _RecordingCatalog()
    loaded = live_module._load_catalog_inputs(
        tmp_path,
        start=dt.date(2026, 9, 1),
        end=dt.date(2026, 9, 1),
        catalog=catalog,
    )

    binary = [query for query in catalog.queries if query["data_cls"] is BinaryOption]
    depth = [query for query in catalog.queries if query["data_cls"] is OrderBookDepth10]
    assert len(binary) == 1
    binary_ids = binary[0]["identifiers"]
    assert isinstance(binary_ids, list)
    assert set(binary_ids) == {in_window, also_in_window}
    assert out_of_window not in binary_ids
    start_ts, end_ts = live_module._tape_query_bounds(dt.date(2026, 9, 1), dt.date(2026, 9, 1))
    assert binary[0]["start"] == start_ts
    assert binary[0]["end"] == end_ts
    assert start_ts == dt.datetime(2026, 8, 30, tzinfo=dt.UTC)
    assert end_ts == dt.datetime(2026, 9, 4, tzinfo=dt.UTC)
    assert len(depth) == 1
    assert depth[0]["identifiers"] == [in_window]
    assert depth[0]["start"] == start_ts
    assert depth[0]["end"] == end_ts
    assert loaded[4]["LAX"] == -8.0


def test_per_day_reports_sum_without_dropping_a_mismatch() -> None:
    from scripts.analysis.nbp_shadow_parity_pure import DecisionKey, diff_decision_keys

    def key(day: int, action: str) -> DecisionKey:
        return DecisionKey(
            station="KLAX",
            climate_day=dt.date(2026, 9, day),
            rung_id="i1",
            instrument_id=f"KLAX-2026-09-0{day}.POLY_US",
            side="yes",
            action=action,
            reason=None,
            ts_ns=day,
        )

    first = diff_decision_keys((key(1, "Take"),), (key(1, "Take"),))
    second = diff_decision_keys((key(2, "Refuse"),), (key(2, "Take"),))
    merged = live_module._merge_parity_reports((first, second))
    assert merged.n_live == 2
    assert merged.n_batch == 2
    assert merged.n_matched == 1
    assert merged.n_mismatches == 2
    assert merged.to_counts_dict()["n_live_yes_Take"] == 1
    assert merged.to_counts_dict()["n_live_yes_Refuse"] == 1

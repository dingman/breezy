"""Contract tests pinning verified NautilusTrader 1.231.0 catalog behaviour.

Every assertion here was observed by execution against the pinned install, not
inferred from documentation. Run these FIRST on any version bump: a failure means
the platform moved, not that Breezy is wrong.

Scope: `src/breezy/domain/` record types and their ParquetDataCatalog round-trip.
No network access; every catalog lives under `tmp_path`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from nautilus_trader.model.data import CustomData
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.selection import select_climate_day
from breezy.domain.strict_arrow import SchemaDriftError

pytestmark = pytest.mark.contract

_DAY = dt.date(2026, 8, 22)
# Aug 22 2026 24:00 EST (local STANDARD time) == Aug 23 05:00 UTC.
_DAY_END_NS = int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_FINAL_ISSUED_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_FINAL_RETRIEVED_NS = int(
    dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000,
)
_PRELIM_ISSUED_NS = int(dt.datetime(2026, 8, 22, 20, 44, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_PRELIM_RETRIEVED_NS = int(
    dt.datetime(2026, 8, 22, 20, 50, tzinfo=dt.UTC).timestamp() * 1_000_000_000,
)
_SHA = hashlib.sha256(b"CDUS41 KOKX 230627").hexdigest()


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tavg_flag": None,
        "tmax_flag": None,
        "tmin_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _FINAL_ISSUED_NS,
        "retrieved_at_ns": _FINAL_RETRIEVED_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "sites.toml@1",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def make_catalog(tmp_path: Path, name: str = "catalog") -> ParquetDataCatalog:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return ParquetDataCatalog(path=root)


def unwrap(results: list[Any]) -> list[NwsClimateDay]:
    return [r.data if isinstance(r, CustomData) else r for r in results]


# --------------------------------------------------------------------------------------


def test_explicit_arrow_schema_roundtrips_nullable_fields(tmp_path: Path) -> None:
    """construct -> to_dict -> to_arrow -> write_data -> query -> from_arrow.

    A null `tmax_f` alongside its `M` sentinel flag must survive intact. This is
    the reason the type carries an explicit schema: pyarrow would otherwise infer
    the column type from the first fragment it happens to read.
    """
    catalog = make_catalog(tmp_path)
    original = make_climate_day(
        tmax_f=None,
        tmax_flag="M",
        tavg_f=None,
        tavg_flag="T",
    )

    catalog.write_data([original])
    restored = unwrap(catalog.query(data_cls=NwsClimateDay))

    assert len(restored) == 1
    assert restored[0].tmax_f is None
    assert restored[0].tmax_flag == "M"
    assert restored[0].tavg_f is None
    assert restored[0].tavg_flag == "T"
    assert restored[0].tmin_f == 63
    assert restored[0].climate_day == _DAY
    assert restored[0].ts_event == _DAY_END_NS
    assert restored[0].ts_init == _FINAL_RETRIEVED_NS
    assert restored[0].to_dict() == original.to_dict()


def test_schema_drift_is_detected_not_silently_defaulted(tmp_path: Path) -> None:
    """A fragment missing a column must raise on read, not default the value.

    `_query_pyarrow` (parquet.py:2145) builds `pds.dataset(files, schema=None)`,
    so the on-disk schema is inferred from the first fragment. The strict decoder
    registered via `register_arrow` is the only detection point.
    """
    catalog = make_catalog(tmp_path)
    batch = ArrowSerializer.serialize(make_climate_day(), NwsClimateDay)
    drifted = pa.Table.from_batches([batch]).drop_columns(["tavg_f", "raw_sha256"])

    drifted_file = tmp_path / "drifted.parquet"
    pq.write_table(drifted, where=str(drifted_file))

    with pytest.raises(SchemaDriftError) as excinfo:
        catalog.query(data_cls=NwsClimateDay, files=[str(drifted_file)])

    message = str(excinfo.value)
    assert "tavg_f" in message
    assert "raw_sha256" in message


def test_rewrite_of_same_timestamp_range_is_not_silently_skipped(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`_write_chunk` prints and RETURNS NORMALLY when the filename already exists.

    parquet.py:378-380. A successful return therefore does not mean data was
    written, so the ingest path must verify by re-reading. This test pins the trap
    and demonstrates the read-back detection it forces.
    """
    catalog = make_catalog(tmp_path)
    catalog.write_data([make_climate_day(tmax_f=84)])
    capsys.readouterr()

    corrected = make_climate_day(tmax_f=99, revision_seq=2, correction_flag=True)
    catalog.write_data([corrected])  # same ts_init range -> same filename

    stdout = capsys.readouterr().out
    stored = unwrap(catalog.query(data_cls=NwsClimateDay))

    assert "already exists, skipping write" in stdout
    assert [r.tmax_f for r in stored] == [84], "the correction was silently discarded"
    assert stored[0].to_dict() != corrected.to_dict(), "read-back detects the skipped write"


def test_custom_data_query_returns_wrapper_objects(tmp_path: Path) -> None:
    """`query` and `custom_data` both return `CustomData`; callers unwrap `.data`."""
    catalog = make_catalog(tmp_path)
    catalog.write_data([make_climate_day()])

    from_query = catalog.query(data_cls=NwsClimateDay)
    assert all(isinstance(r, CustomData) for r in from_query)
    assert all(isinstance(r.data, NwsClimateDay) for r in from_query)
    assert from_query[0].data_type.type is NwsClimateDay

    from_custom_data = catalog.custom_data(cls=NwsClimateDay)
    assert all(isinstance(r, CustomData) for r in from_custom_data)
    assert all(isinstance(r.data, NwsClimateDay) for r in from_custom_data)


def test_correction_supersedes_via_later_ts_init(tmp_path: Path) -> None:
    """§4.3: a correction is a NEW record with a strictly later `ts_init`."""
    catalog = make_catalog(tmp_path)
    original = make_climate_day(tmax_f=84, revision_seq=1)
    correction = make_climate_day(
        tmax_f=85,
        revision_seq=2,
        correction_flag=True,
        issuance_time_ns=_FINAL_ISSUED_NS + 86_400_000_000_000,
        retrieved_at_ns=_FINAL_RETRIEVED_NS + 86_400_000_000_000,
    )

    catalog.write_data([original])
    catalog.write_data([correction])  # disjoint ts_init range -> a real second file

    stored = unwrap(catalog.query(data_cls=NwsClimateDay))
    assert len(stored) == 2, "both revisions persist; nothing is rewritten in place"

    current = select_climate_day(stored, "NYC", _DAY)
    assert current is not None
    assert current.tmax_f == 85
    assert current.revision_seq == 2

    as_of_before = select_climate_day(
        stored,
        "NYC",
        _DAY,
        as_of_ts_init=_FINAL_RETRIEVED_NS + 3_600_000_000_000,
    )
    assert as_of_before is not None
    assert as_of_before.tmax_f == 84


def test_ts_event_le_ts_init_holds_for_finals_only(tmp_path: Path) -> None:
    """The invariant is scoped to finals and must NOT be enforced globally.

    A final's `ts_event` is the end of the climate day (LST), always before the
    ~02:27 local retrieval that follows it. A preliminary is polled mid-afternoon
    while its own climate day still has hours to run, so any record whose
    `ts_event` is the climate-day end violates the ordering by construction.
    """
    catalog = make_catalog(tmp_path)
    preliminary = make_climate_day(
        is_final=False,
        tmax_f=82,
        tmin_f=63,
        issuance_time_ns=_PRELIM_ISSUED_NS,
        retrieved_at_ns=_PRELIM_RETRIEVED_NS,
        ts_event=_DAY_END_NS,  # climate day ends hours AFTER this poll
    )
    final = make_climate_day()

    catalog.write_data([preliminary])
    catalog.write_data([final])

    stored = unwrap(catalog.query(data_cls=NwsClimateDay))
    finals = [r for r in stored if r.is_final]
    preliminaries = [r for r in stored if not r.is_final]

    assert finals and preliminaries
    for record in finals:
        assert record.ts_event <= record.ts_init

    assert any(r.ts_event > r.ts_init for r in preliminaries), (
        "the catalog accepted and returned a preliminary whose semantic instant "
        "post-dates its arrival; a global ts_event <= ts_init assertion is invalid"
    )


def test_delete_data_range_is_never_relied_upon(tmp_path: Path) -> None:
    """It no-ops for identifier-less custom types (parquet.py:1386-1406).

    The `identifier=None` branch substring-matches `"/data/<name>/"`, which a flat
    custom-data directory never contains. It returns normally and deletes nothing.
    """
    catalog = make_catalog(tmp_path)
    catalog.write_data([make_climate_day()])
    assert len(catalog.query(data_cls=NwsClimateDay)) == 1

    catalog.delete_data_range(data_cls=NwsClimateDay)

    assert len(catalog.query(data_cls=NwsClimateDay)) == 1, (
        "delete_data_range silently deleted nothing; it is not an escape hatch "
        "from the silent same-range write skip"
    )


def test_two_stations_share_one_flat_directory(tmp_path: Path) -> None:
    """Trap 21: no `instrument_id` -> flat partition, so stations merge on read.

    Pins the plan's §5 requirement that per-station separation needs one catalog
    root per station rather than a metadata or identifier filter.
    """
    shared = make_catalog(tmp_path, "shared")
    nyc = make_climate_day(station="NYC", tmax_f=84)
    mdw = make_climate_day(
        station="MDW",
        issuing_office="KLOT",
        tmax_f=91,
        retrieved_at_ns=_FINAL_RETRIEVED_NS + 60_000_000_000,
    )
    shared.write_data([nyc])
    shared.write_data([mdw])

    assert {r.station for r in unwrap(shared.query(data_cls=NwsClimateDay))} == {"NYC", "MDW"}
    assert shared.query(data_cls=NwsClimateDay, identifiers=["NYC"]) == []

    per_station = make_catalog(tmp_path, "per_station_nyc")
    per_station.write_data([nyc])
    assert {r.station for r in unwrap(per_station.query(data_cls=NwsClimateDay))} == {"NYC"}


def test_drift_detection_is_one_sided_when_the_first_fragment_matches(tmp_path: Path) -> None:
    """The strict decoder guards the dataset schema, not each fragment.

    `_query_pyarrow` unifies fragments under the schema inferred from the FIRST
    one, and `get_file_list_from_data_cls` globs (so oldest-first, since filenames
    are zero-padded nanosecond ranges). Both real version-drift directions are
    therefore caught -- the oldest fragment disagrees with the registered schema,
    which is exactly what the decoder compares. What the schema check cannot see
    is a LATER fragment diverging while the first still matches: its missing
    column is coerced to NULL before the decoder runs.

    The record's own constructor invariants close most of that gap as defence in
    depth, and this test pins exactly how much: a coerced NULL is caught wherever
    it contradicts a non-null type or a paired value/flag column. The residual
    hole is a genuinely nullable column whose NULL is legitimate on its own --
    a `*_flag` alongside a present value. Breezy's strict encoder makes all of
    this unreachable through its own write path, so the exposure is a foreign or
    corrupted fragment. Pinned so the decoder is not mistaken for a total guard.
    """
    catalog = make_catalog(tmp_path)
    batch = ArrowSerializer.serialize(make_climate_day(), NwsClimateDay)
    matching = pa.Table.from_batches([batch])

    first = tmp_path / "a.parquet"
    pq.write_table(matching, where=str(first))

    def query_with_dropped(column: str) -> list[NwsClimateDay]:
        divergent = tmp_path / f"b_{column}.parquet"
        pq.write_table(matching.drop_columns([column]), where=str(divergent))
        return unwrap(catalog.query(data_cls=NwsClimateDay, files=[str(first), str(divergent)]))

    # (a) First fragment diverges -> the dataset schema diverges -> schema guard fires.
    divergent_first = tmp_path / "b_first.parquet"
    pq.write_table(matching.drop_columns(["tavg_f"]), where=str(divergent_first))
    with pytest.raises(SchemaDriftError):
        catalog.query(data_cls=NwsClimateDay, files=[str(divergent_first), str(first)])

    # (b) Later fragment, value column -> coerced NULL contradicts its sentinel flag.
    with pytest.raises(ValueError, match="tavg_flag"):
        query_with_dropped("tavg_f")

    # (b) Later fragment, non-nullable column -> coerced NULL fails the field guard.
    with pytest.raises(TypeError, match="source_channel"):
        query_with_dropped("source_channel")

    # (c) Residual: a nullable flag whose NULL is legitimate beside a present value.
    coerced = query_with_dropped("tavg_flag")
    assert [r.tavg_flag for r in coerced] == [None, None]
    assert [r.tavg_f for r in coerced] == [74, 74]


def test_missing_and_trace_average_survive_the_catalog_round_trip(tmp_path: Path) -> None:
    """A missing AVERAGE and a trace AVERAGE must stay distinguishable on disk.

    Both carry `tavg_f = NULL`, so the sentinel kind lives only in `tavg_flag`.
    Without that column the two collapse into one indistinguishable value the
    moment a record is built from a parsed product.
    """
    catalog = make_catalog(tmp_path)
    missing = make_climate_day(climate_day=dt.date(2026, 8, 21), tavg_f=None, tavg_flag="M")
    trace = make_climate_day(
        climate_day=_DAY,
        tavg_f=None,
        tavg_flag="T",
        retrieved_at_ns=_FINAL_RETRIEVED_NS + 60_000_000_000,
    )

    catalog.write_data([missing])
    catalog.write_data([trace])

    stored = {r.climate_day: r for r in unwrap(catalog.query(data_cls=NwsClimateDay))}

    assert stored[dt.date(2026, 8, 21)].tavg_f is None
    assert stored[dt.date(2026, 8, 21)].tavg_flag == "M"
    assert stored[_DAY].tavg_f is None
    assert stored[_DAY].tavg_flag == "T"
    assert stored[dt.date(2026, 8, 21)].tavg_flag != stored[_DAY].tavg_flag


def test_published_average_persists_as_a_whole_degree_int(tmp_path: Path) -> None:
    """The venue settles on the CLI's published AVERAGE; it is never computed here."""
    catalog = make_catalog(tmp_path)
    catalog.write_data([make_climate_day(tmax_f=84, tmin_f=63, tavg_f=74)])

    (restored,) = unwrap(catalog.query(data_cls=NwsClimateDay))

    assert restored.tavg_f == 74
    assert isinstance(restored.tavg_f, int)
    assert restored.tavg_f != (restored.tmax_f + restored.tmin_f) / 2

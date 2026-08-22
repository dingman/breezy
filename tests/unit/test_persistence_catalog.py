"""Unit tests for `breezy.persistence.catalog` -- per-station catalog plumbing.

Scope: path derivation, station isolation, the silent write-skip detector, the
non-decreasing `ts_init` guard, wrapper unwrapping, and the as-of composition
over `breezy.domain.selection`.

Every catalog lives under `tmp_path`; nothing here touches the network.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import CustomData, DataType
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.nws_raw_product import RAW_PRODUCT_SCHEMA_VERSION, NwsRawProduct, sha256_text
from breezy.persistence import catalog as catalog_module
from breezy.persistence.catalog import (
    WRITER_LOCK_FILENAME,
    CatalogPathError,
    CatalogWriteError,
    ConcurrentWriterError,
    FilesystemLocality,
    FilesystemProbe,
    NonMonotonicWriteError,
    WriteOutcome,
    WriterLockError,
    WriterLockFilesystemError,
    assert_writer_lock_filesystem_supported,
    open_station_catalog,
    probe_filesystem,
    read_climate_days,
    read_current_climate_day,
    read_raw_products,
    station_catalog_path,
    write_records,
)

_DAY = dt.date(2026, 8, 22)
_DAY_END_NS = int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_ISSUED_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_RETRIEVED_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"CDUS41 KOKX 230627").hexdigest()
_MINUTE_NS = 60_000_000_000


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _ISSUED_NS,
        "retrieved_at_ns": _RETRIEVED_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def make_raw_product(**overrides: Any) -> NwsRawProduct:
    raw_text = str(overrides.pop("raw_text", "CDUS41 KOKX 230627\nCLINYC\n"))
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "product_uuid": "00000000-0000-4000-8000-000000000001",
        "product_code": "CLI",
        "issuing_office": "KOKX",
        "wmo_collective_id": "CDUS41",
        "awips_pil": "CLINYC",
        "wmo_bbb_token": None,
        "issuance_time_ns": _ISSUED_NS,
        "retrieved_at_ns": _RETRIEVED_NS,
        "climate_day": _DAY,
        "raw_text": raw_text,
        "raw_sha256": sha256_text(raw_text),
        "response_sha256": sha256_text(f"{{'productText': {raw_text!r}}}"),
        "response_etag": None,
        "response_last_modified": None,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "registry_version": "1.0.0",
        "schema_version": RAW_PRODUCT_SCHEMA_VERSION,
    }
    kwargs.update(overrides)
    return NwsRawProduct(**kwargs)


# -- path derivation ------------------------------------------------------------------------


def test_station_catalog_path_derives_from_registry_identifiers(tmp_path: Path) -> None:
    path = station_catalog_path(tmp_path / "nws", "polymarket_us", "NYC")

    assert path == (tmp_path / "nws" / "polymarket_us" / "NYC")


def test_station_catalog_path_separates_stations_and_venues(tmp_path: Path) -> None:
    base = tmp_path / "nws"
    nyc = station_catalog_path(base, "polymarket_us", "NYC")
    mdw = station_catalog_path(base, "polymarket_us", "MDW")
    other_venue = station_catalog_path(base, "kalshi", "NYC")

    assert len({nyc, mdw, other_venue}) == 3


@pytest.mark.parametrize(
    "component",
    [
        "..",
        ".",
        "../../etc",
        "a/b",
        "a\\b",
        "/absolute",
        "",
        " ",
        "with space",
        "with\x00null",
        "trailing.",
        "-leading-dash",
        "NYC\n",
        "x" * 65,
    ],
)
def test_station_catalog_path_rejects_unsafe_components(tmp_path: Path, component: str) -> None:
    with pytest.raises(CatalogPathError):
        station_catalog_path(tmp_path, component, "NYC")

    with pytest.raises(CatalogPathError):
        station_catalog_path(tmp_path, "polymarket_us", component)


def test_station_catalog_path_rejects_non_string_components(tmp_path: Path) -> None:
    with pytest.raises(CatalogPathError):
        station_catalog_path(tmp_path, "polymarket_us", 42)  # type: ignore[arg-type]


def test_station_catalog_path_never_escapes_the_base(tmp_path: Path) -> None:
    """A path-traversal write primitive is the specific hazard being closed."""
    base = (tmp_path / "nws").resolve()

    for venue, city in (("polymarket_us", "NYC"), ("kalshi", "MDW")):
        derived = station_catalog_path(base, venue, city).resolve()
        assert derived.is_relative_to(base)


# -- opening ---------------------------------------------------------------------------------


def test_open_station_catalog_creates_the_root_and_is_idempotent(tmp_path: Path) -> None:
    base = tmp_path / "nws"
    first = open_station_catalog(base, "polymarket_us", "NYC")
    second = open_station_catalog(base, "polymarket_us", "NYC")

    assert isinstance(first, ParquetDataCatalog)
    assert (base / "polymarket_us" / "NYC").is_dir()
    assert Path(first.path) == Path(second.path)


def test_open_station_catalog_rejects_unsafe_components(tmp_path: Path) -> None:
    with pytest.raises(CatalogPathError):
        open_station_catalog(tmp_path, "polymarket_us", "../escape")


def test_two_stations_land_in_separate_roots_with_no_cross_reads(tmp_path: Path) -> None:
    """Metadata does not filter the catalog; the directory is the partition key."""
    base = tmp_path / "nws"
    nyc_catalog = open_station_catalog(base, "polymarket_us", "NYC")
    mdw_catalog = open_station_catalog(base, "polymarket_us", "MDW")

    write_records(nyc_catalog, [make_climate_day(station="NYC", tmax_f=84)])
    write_records(
        mdw_catalog,
        [make_climate_day(station="MDW", issuing_office="KLOT", tmax_f=91)],
    )

    assert [r.station for r in read_climate_days(nyc_catalog)] == ["NYC"]
    assert [r.station for r in read_climate_days(mdw_catalog)] == ["MDW"]
    assert Path(nyc_catalog.path) != Path(mdw_catalog.path)


# -- writing ---------------------------------------------------------------------------------


def test_write_records_reports_written_records(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    record = make_climate_day()

    outcome = write_records(catalog, [record])

    assert isinstance(outcome, WriteOutcome)
    assert outcome.is_complete
    assert outcome.written == (record,)
    assert outcome.skipped == ()


def test_write_records_writes_mixed_record_types_in_one_call(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")

    outcome = write_records(catalog, [make_raw_product(), make_climate_day()])

    assert outcome.is_complete
    assert len(outcome.written) == 2
    assert len(read_climate_days(catalog)) == 1
    assert len(read_raw_products(catalog)) == 1


def test_write_records_detects_the_silent_same_range_skip(tmp_path: Path) -> None:
    """`_write_chunk` prints and returns normally when the filename exists.

    A successful return therefore does not mean data was written. Detection is by
    read-back, and the outcome reports the skip rather than raising.
    """
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day(tmax_f=84)])

    # Same `retrieved_at_ns` => same `ts_init` range => same computed filename.
    corrected = make_climate_day(tmax_f=99, revision_seq=2, correction_flag=True)
    outcome = write_records(catalog, [corrected])

    assert not outcome.is_complete
    assert outcome.skipped == (corrected,)
    assert outcome.written == ()
    assert [r.tmax_f for r in read_climate_days(catalog)] == [84]


def test_write_records_reports_success_for_a_later_ts_init_correction(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day(tmax_f=84)])

    corrected = make_climate_day(
        tmax_f=99,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_RETRIEVED_NS + _MINUTE_NS,
    )
    outcome = write_records(catalog, [corrected])

    assert outcome.is_complete
    assert outcome.written == (corrected,)
    assert sorted(r.tmax_f or 0 for r in read_climate_days(catalog)) == [84, 99]


def test_write_records_rejects_non_monotonic_ts_init(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    later = make_climate_day(retrieved_at_ns=_RETRIEVED_NS + _MINUTE_NS)
    earlier = make_climate_day()

    with pytest.raises(NonMonotonicWriteError) as excinfo:
        write_records(catalog, [later, earlier])

    assert "ts_init" in str(excinfo.value)
    assert "NwsClimateDay" in str(excinfo.value)
    assert read_climate_days(catalog) == []


def test_write_records_allows_equal_ts_init_within_a_batch(tmp_path: Path) -> None:
    """Non-DECREASING, not strictly increasing: a poll can yield two at once."""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    first = make_climate_day(climate_day=dt.date(2026, 8, 21))
    second = make_climate_day(climate_day=_DAY)

    outcome = write_records(catalog, [first, second])

    assert outcome.is_complete
    assert len(read_climate_days(catalog)) == 2


def test_write_records_orders_per_class_like_the_catalog_does(tmp_path: Path) -> None:
    """`write_data` groups by class, so ordering is a per-class property."""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    raw = make_raw_product(retrieved_at_ns=_RETRIEVED_NS + _MINUTE_NS)
    climate = make_climate_day()

    outcome = write_records(catalog, [raw, climate])

    assert outcome.is_complete


def test_write_records_rejects_pre_wrapped_custom_data(tmp_path: Path) -> None:
    """The catalog wraps on read and unwraps on write; callers submit raw records."""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    wrapped = CustomData(DataType(NwsClimateDay), make_climate_day())

    with pytest.raises(TypeError, match="CustomData"):
        write_records(catalog, [wrapped])


def test_write_records_fails_loudly_for_an_unregistered_record_type(tmp_path: Path) -> None:
    """An unregistered type raises in the serializer, before anything is written.

    `_objects_to_table` serializes BEFORE `_write_chunk` creates the directory, so
    a rejected batch leaves no trace on disk.
    """

    class Unregistered(Data):
        @property
        def ts_event(self) -> int:
            return 0

        @property
        def ts_init(self) -> int:
            return 0

    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")

    with pytest.raises(TypeError) as excinfo:
        write_records(catalog, [Unregistered()])

    # NB: assert on the platform's wording, not on a substring that also appears
    # in this test's own name -- `<locals>` qualnames leak the test name into the
    # message and would make such a match a false positive.
    assert "Register a serialization method" in str(excinfo.value)
    assert list(Path(catalog.path).rglob("*.parquet")) == []


def test_write_records_raises_when_a_write_is_neither_complete_nor_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial write means the platform's per-class chunking changed.

    Simulated, because 1.231.0 writes one chunk per class for our identifier-less
    types and so cannot produce this. The branch exists so that a version bump
    which DOES split a class into several files fails loudly instead of reporting
    a half-written batch as complete.
    """
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    real_write_data = catalog.write_data

    def write_only_the_first(records: list[Any], *args: Any, **kwargs: Any) -> None:
        real_write_data(records[:1], *args, **kwargs)

    monkeypatch.setattr(catalog, "write_data", write_only_the_first)

    with pytest.raises(CatalogWriteError, match="neither a complete write nor a complete skip"):
        write_records(
            catalog,
            [
                make_climate_day(climate_day=dt.date(2026, 8, 20)),
                make_climate_day(
                    climate_day=_DAY,
                    retrieved_at_ns=_RETRIEVED_NS + _MINUTE_NS,
                ),
            ],
        )


def test_write_records_accepts_an_empty_batch(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")

    outcome = write_records(catalog, [])

    assert outcome.is_complete
    assert outcome.written == ()
    assert outcome.skipped == ()


# -- reading ---------------------------------------------------------------------------------


def test_read_climate_days_unwraps_custom_data_wrappers(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day()])

    records = read_climate_days(catalog)

    assert all(isinstance(r, NwsClimateDay) for r in records)
    assert not any(isinstance(r, CustomData) for r in records)
    assert records[0].tmax_f == 84


def test_read_raw_products_unwraps_custom_data_wrappers(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_raw_product()])

    records = read_raw_products(catalog)

    assert all(isinstance(r, NwsRawProduct) for r in records)
    assert not any(isinstance(r, CustomData) for r in records)
    assert records[0].verify_digest()


def test_reads_on_an_empty_catalog_return_empty_lists(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")

    assert read_climate_days(catalog) == []
    assert read_raw_products(catalog) == []


def test_read_climate_days_honours_the_ts_init_window(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    first = make_climate_day(climate_day=dt.date(2026, 8, 20))
    second = make_climate_day(
        climate_day=dt.date(2026, 8, 21),
        retrieved_at_ns=_RETRIEVED_NS + _MINUTE_NS,
    )
    write_records(catalog, [first])
    write_records(catalog, [second])

    windowed = read_climate_days(catalog, start=_RETRIEVED_NS + 1)

    assert [r.climate_day for r in windowed] == [dt.date(2026, 8, 21)]


# -- as-of composition over `domain.selection` -----------------------------------------------


def test_read_current_climate_day_returns_the_superseding_record(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    original = make_climate_day(tmax_f=84)
    corrected = make_climate_day(
        tmax_f=99,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_RETRIEVED_NS + _MINUTE_NS,
    )
    write_records(catalog, [original])
    write_records(catalog, [corrected])

    current = read_current_climate_day(catalog, station="NYC", climate_day=_DAY)

    assert current is not None
    assert current.tmax_f == 99
    assert current.revision_seq == 2


def test_read_current_climate_day_respects_the_as_of_bound(tmp_path: Path) -> None:
    """Post-hoc audit: what would the resolver have returned before the fix?"""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day(tmax_f=84)])
    write_records(
        catalog,
        [
            make_climate_day(
                tmax_f=99,
                revision_seq=2,
                correction_flag=True,
                retrieved_at_ns=_RETRIEVED_NS + _MINUTE_NS,
            ),
        ],
    )

    before = read_current_climate_day(
        catalog,
        station="NYC",
        climate_day=_DAY,
        as_of_ts_init=_RETRIEVED_NS,
    )
    at_correction = read_current_climate_day(
        catalog,
        station="NYC",
        climate_day=_DAY,
        as_of_ts_init=_RETRIEVED_NS + _MINUTE_NS,
    )

    assert before is not None
    assert before.tmax_f == 84
    assert at_correction is not None
    assert at_correction.tmax_f == 99


def test_read_current_climate_day_returns_none_for_an_unknown_key(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day()])

    assert read_current_climate_day(catalog, station="NYC", climate_day=dt.date(2026, 1, 1)) is None
    assert read_current_climate_day(catalog, station="MDW", climate_day=_DAY) is None


# -- single-writer enforcement ----------------------------------------------------------------


def _hold_writer_lock(catalog: ParquetDataCatalog) -> int:
    """Take the station writer lock from a separate descriptor.

    `flock` treats descriptors independently even within one process, so this
    faithfully simulates a second writer without spawning one.
    """
    lock_path = Path(catalog.path) / WRITER_LOCK_FILENAME
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _release(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def test_write_records_fails_loudly_when_another_writer_holds_the_lock(tmp_path: Path) -> None:
    """A second writer must fail at the door, not rely on the skip detector."""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    fd = _hold_writer_lock(catalog)

    try:
        with pytest.raises(ConcurrentWriterError) as excinfo:
            write_records(catalog, [make_climate_day()])
    finally:
        _release(fd)

    assert str(catalog.path) in str(excinfo.value)
    assert read_climate_days(catalog) == []


def test_the_writer_lock_is_released_between_calls(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")

    first = write_records(catalog, [make_climate_day(climate_day=dt.date(2026, 8, 20))])
    second = write_records(
        catalog,
        [make_climate_day(climate_day=_DAY, retrieved_at_ns=_RETRIEVED_NS + _MINUTE_NS)],
    )

    assert first.is_complete
    assert second.is_complete
    assert len(read_climate_days(catalog)) == 2


def test_the_writer_lock_is_released_after_a_failed_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raised write must not strand the lock and wedge the station forever."""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")

    def explode(records: list[Any], *args: Any, **kwargs: Any) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr(catalog, "write_data", explode)
    with pytest.raises(OSError, match="disk on fire"):
        write_records(catalog, [make_climate_day()])
    monkeypatch.undo()

    assert write_records(catalog, [make_climate_day()]).is_complete


def test_readers_never_take_the_writer_lock(tmp_path: Path) -> None:
    """Multi-process read-only replay must not be serialised by a writer's lock."""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day()])
    fd = _hold_writer_lock(catalog)

    try:
        assert len(read_climate_days(catalog)) == 1
        assert read_raw_products(catalog) == []
        assert read_current_climate_day(catalog, station="NYC", climate_day=_DAY) is not None
    finally:
        _release(fd)


def test_the_writer_lock_file_is_invisible_to_the_catalog(tmp_path: Path) -> None:
    """The lock lives at the root; Nautilus only ever globs `data/<name>/`."""
    catalog = open_station_catalog(tmp_path, "polymarket_us", "NYC")
    write_records(catalog, [make_climate_day()])

    lock_path = Path(catalog.path) / WRITER_LOCK_FILENAME

    assert lock_path.is_file()
    assert lock_path.stat().st_size == 0
    assert lock_path not in set(Path(catalog.path).rglob("*.parquet"))
    assert len(catalog.get_file_list_from_data_cls(NwsClimateDay)) == 1
    assert len(read_climate_days(catalog)) == 1


# -- lock subversion by symlink ----------------------------------------------------------------


@pytest.mark.parametrize("target_exists", [True, False])
def test_write_records_refuses_a_symlinked_writer_lock(tmp_path: Path, target_exists: bool) -> None:
    """A pre-planted symlink must not redirect the flock to a target of its choosing.

    Without `O_NOFOLLOW` the lock is taken on the symlink's TARGET, so two writers
    on the same station root hold locks on two different inodes and the
    single-writer guarantee is silently gone. Both a resolving and a dangling
    symlink are refused -- `O_CREAT` on a dangling symlink would otherwise create
    (and lock) the attacker-chosen path.
    """
    catalog = open_station_catalog(tmp_path / "nws", "polymarket_us", "NYC")
    planted = tmp_path / "planted.lock"
    if target_exists:
        planted.write_text("")
    lock_path = Path(catalog.path) / WRITER_LOCK_FILENAME
    lock_path.symlink_to(planted)

    with pytest.raises(CatalogPathError, match="symlink"):
        write_records(catalog, [make_climate_day()])

    assert lock_path.is_symlink(), "the planted link is left in place as evidence"
    assert planted.exists() is target_exists, "the lock never reached the planted target"
    assert read_climate_days(catalog) == []


def test_station_catalog_path_rejects_a_symlinked_venue_component(tmp_path: Path) -> None:
    base = tmp_path / "nws"
    (base / "kalshi").mkdir(parents=True)
    (base / "polymarket_us").symlink_to(base / "kalshi")

    with pytest.raises(CatalogPathError, match="symlink"):
        station_catalog_path(base, "polymarket_us", "NYC")


def test_station_catalog_path_rejects_a_city_symlink_aliasing_another_station(
    tmp_path: Path,
) -> None:
    """Containment alone does not catch this: the link stays *inside* the base.

    Two registry stations resolving to one directory merges their records and
    defeats the per-station partition this module exists to enforce.
    """
    base = tmp_path / "nws"
    (base / "polymarket_us" / "MDW").mkdir(parents=True)
    (base / "polymarket_us" / "NYC").symlink_to(base / "polymarket_us" / "MDW")

    with pytest.raises(CatalogPathError, match="symlink"):
        station_catalog_path(base, "polymarket_us", "NYC")


def test_open_station_catalog_rejects_a_symlinked_component(tmp_path: Path) -> None:
    base = tmp_path / "nws"
    (base / "polymarket_us" / "MDW").mkdir(parents=True)
    (base / "polymarket_us" / "NYC").symlink_to(base / "polymarket_us" / "MDW")

    with pytest.raises(CatalogPathError, match="symlink"):
        open_station_catalog(base, "polymarket_us", "NYC")


def test_station_catalog_path_allows_a_symlinked_base(tmp_path: Path) -> None:
    """Only components DERIVED here are checked; the operator-supplied base is not.

    Pointing a data root at a symlinked volume is ordinary deployment practice --
    rejecting it would be the false positive that gets the check ripped out.
    """
    volume = tmp_path / "volume"
    volume.mkdir()
    base = tmp_path / "nws"
    base.symlink_to(volume)

    assert station_catalog_path(base, "polymarket_us", "NYC") == base / "polymarket_us" / "NYC"


# -- flock's local-filesystem precondition ------------------------------------------------------


def _mountinfo(*entries: tuple[str, str]) -> str:
    """Render `(mount_point, fs_type)` pairs as `/proc/self/mountinfo` lines."""
    lines = []
    for index, (mount_point, fs_type) in enumerate(entries, start=1):
        escaped = mount_point.replace("\\", "\\134").replace(" ", "\\040")
        lines.append(
            f"{index + 20} 1 0:{index} / {escaped} rw,relatime shared:{index} "
            f"- {fs_type} source{index} rw"
        )
    return "\n".join(lines) + "\n"


def _write_mountinfo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *entries: tuple[str, str],
) -> None:
    fake = tmp_path / "mountinfo"
    fake.write_text(_mountinfo(*entries))
    monkeypatch.setattr(catalog_module, "_MOUNTINFO_PATH", fake)


def test_probe_filesystem_reports_local_for_an_ordinary_temp_dir(tmp_path: Path) -> None:
    probe = probe_filesystem(tmp_path)

    assert probe.locality is FilesystemLocality.LOCAL
    assert probe.fs_type is not None
    assert probe.mount_point is not None


@pytest.mark.parametrize("fs_type", ["nfs", "nfs4", "cifs", "smb3", "fuse.sshfs", "ceph"])
def test_probe_filesystem_detects_network_filesystems(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fs_type: str,
) -> None:
    _write_mountinfo(monkeypatch, tmp_path, ("/", "ext4"), (str(tmp_path.resolve()), fs_type))

    probe = probe_filesystem(tmp_path / "nws" / "polymarket_us" / "NYC")

    assert probe.locality is FilesystemLocality.NETWORK
    assert probe.fs_type == fs_type


@pytest.mark.parametrize(
    "fs_type",
    ["ext4", "xfs", "btrfs", "zfs", "overlay", "tmpfs", "f2fs", "fuse.gocryptfs"],
)
def test_probe_filesystem_does_not_flag_local_or_container_filesystems(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fs_type: str,
) -> None:
    """Containers run on overlayfs and tmpfs, where `flock` is perfectly correct.

    Blanket-rejecting anything that is not a plain local disk is a false positive
    that gets the check disabled, which is worse than not having it.
    """
    _write_mountinfo(monkeypatch, tmp_path, ("/", "ext4"), (str(tmp_path.resolve()), fs_type))

    assert probe_filesystem(tmp_path).locality is FilesystemLocality.LOCAL


def test_probe_filesystem_matches_the_longest_mount_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local root with a network mount deeper down must resolve to the deeper one."""
    root = tmp_path.resolve()
    _write_mountinfo(
        monkeypatch,
        tmp_path,
        ("/", "ext4"),
        (str(root), "ext4"),
        (str(root / "nws"), "nfs4"),
    )

    assert probe_filesystem(tmp_path / "nws" / "NYC").fs_type == "nfs4"
    assert probe_filesystem(tmp_path / "other").fs_type == "ext4"


def test_probe_filesystem_prefers_the_last_of_two_identical_mount_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-mount shadows the mount beneath it; file order breaks the tie."""
    root = str(tmp_path.resolve())
    _write_mountinfo(monkeypatch, tmp_path, ("/", "ext4"), (root, "ext4"), (root, "nfs4"))

    assert probe_filesystem(tmp_path).fs_type == "nfs4"


def test_probe_filesystem_decodes_octal_escaped_mount_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`mountinfo` octal-escapes space, tab, newline and backslash in the path."""
    spaced = tmp_path.resolve() / "data island"
    spaced.mkdir()
    _write_mountinfo(monkeypatch, tmp_path, ("/", "ext4"), (str(spaced), "nfs4"))

    probe = probe_filesystem(spaced / "polymarket_us")

    assert probe.mount_point == str(spaced)
    assert probe.locality is FilesystemLocality.NETWORK


def test_probe_filesystem_is_undetermined_when_mountinfo_is_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-Linux, or a container without /proc: honest 'unknown', never 'local'."""
    monkeypatch.setattr(catalog_module, "_MOUNTINFO_PATH", tmp_path / "absent")

    probe = probe_filesystem(tmp_path)

    assert probe.locality is FilesystemLocality.UNDETERMINED
    assert probe.fs_type is None
    assert probe.mount_point is None


def test_probe_filesystem_is_undetermined_when_no_mount_point_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_mountinfo(monkeypatch, tmp_path, ("/somewhere/else", "ext4"))

    assert probe_filesystem(tmp_path).locality is FilesystemLocality.UNDETERMINED


def test_probe_filesystem_ignores_malformed_mountinfo_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = tmp_path / "mountinfo"
    fake.write_text(
        "this line has no separator at all\n"
        "\n"
        "1 2 - nfs4 src rw\n"  # separator too early to be the real one
        "21 1 0:1 / /somewhere rw shared:1 -\n"  # separator present, no fs type after it
        f"21 1 0:1 / {tmp_path.resolve()} rw - ext4 src rw\n"
    )
    monkeypatch.setattr(catalog_module, "_MOUNTINFO_PATH", fake)

    assert probe_filesystem(tmp_path).locality is FilesystemLocality.LOCAL


def test_probe_filesystem_keeps_the_deepest_mount_when_it_is_listed_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Depth wins over file order; only an equally deep mount may displace it."""
    root = tmp_path.resolve()
    _write_mountinfo(
        monkeypatch,
        tmp_path,
        (str(root / "nws"), "nfs4"),
        (str(root), "ext4"),
        ("/", "ext4"),
    )

    assert probe_filesystem(root / "nws" / "NYC").fs_type == "nfs4"


def test_assert_writer_lock_filesystem_supported_accepts_a_local_probe(tmp_path: Path) -> None:
    assert_writer_lock_filesystem_supported(probe_filesystem(tmp_path))


def test_assert_writer_lock_filesystem_supported_refuses_a_network_probe() -> None:
    probe = FilesystemProbe(
        path="/mnt/shared/nws",
        mount_point="/mnt/shared",
        fs_type="nfs4",
        locality=FilesystemLocality.NETWORK,
        detail="",
    )

    with pytest.raises(WriterLockFilesystemError) as excinfo:
        assert_writer_lock_filesystem_supported(probe)

    assert "nfs4" in str(excinfo.value)
    assert "/mnt/shared" in str(excinfo.value)


def test_assert_writer_lock_filesystem_supported_refuses_an_undetermined_probe() -> None:
    """Fail closed: 'cannot verify' must never be reported as 'verified local'."""
    probe = FilesystemProbe(
        path="/data/nws",
        mount_point=None,
        fs_type=None,
        locality=FilesystemLocality.UNDETERMINED,
        detail="no mount table",
    )

    with pytest.raises(WriterLockFilesystemError, match="could not be determined"):
        assert_writer_lock_filesystem_supported(probe)


def test_the_filesystem_assertion_is_never_an_implicit_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It is deployment-invoked. Opening and writing must not probe the mount table.

    Import-time (or hot-path) filesystem probing is hostile to tests and tooling,
    so an absent mount table must not disturb ordinary operation.
    """
    monkeypatch.setattr(catalog_module, "_MOUNTINFO_PATH", tmp_path / "absent")

    catalog = open_station_catalog(tmp_path / "nws", "polymarket_us", "NYC")

    assert write_records(catalog, [make_climate_day()]).is_complete


# -- lock-acquisition error taxonomy ------------------------------------------------------------


def test_concurrent_writer_error_is_a_writer_lock_error() -> None:
    """Callers may catch the narrow contention type or the whole lock family."""
    assert issubclass(ConcurrentWriterError, WriterLockError)
    assert issubclass(WriterLockError, RuntimeError)


def test_write_records_normalizes_an_unwritable_station_root(tmp_path: Path) -> None:
    """A read-only root fails closed as a documented type, not a raw `OSError`."""
    catalog = open_station_catalog(tmp_path / "nws", "polymarket_us", "NYC")
    root = Path(catalog.path)
    root.chmod(0o500)

    try:
        with pytest.raises(WriterLockError) as excinfo:
            write_records(catalog, [make_climate_day()])
    finally:
        root.chmod(0o700)

    assert not isinstance(excinfo.value, ConcurrentWriterError)
    assert str(catalog.path) in str(excinfo.value)
    assert read_climate_days(catalog) == []


def test_write_records_normalizes_a_directory_at_the_lock_path(tmp_path: Path) -> None:
    catalog = open_station_catalog(tmp_path / "nws", "polymarket_us", "NYC")
    (Path(catalog.path) / WRITER_LOCK_FILENAME).mkdir()

    with pytest.raises(WriterLockError) as excinfo:
        write_records(catalog, [make_climate_day()])

    assert not isinstance(excinfo.value, ConcurrentWriterError)
    assert read_climate_days(catalog) == []
    assert WRITER_LOCK_FILENAME in str(excinfo.value)


def test_write_records_normalizes_an_uncreatable_station_root(tmp_path: Path) -> None:
    """`mkdir` sits on the same acquisition path and must share the taxonomy."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    catalog = ParquetDataCatalog(path=blocker / "NYC")

    with pytest.raises(WriterLockError):
        write_records(catalog, [make_climate_day()])

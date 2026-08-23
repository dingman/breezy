"""Pins the `ts_init`-interval write contract that `_persist_batch`'s nudge relies on.

Verified NautilusTrader version: **1.231.0**. Every assertion below was observed
by executing against the pinned install, not inferred from documentation --
confirm this yourself on any version bump before trusting the module docstring.

**A failure here means the `_persist_batch` nudge (`src/breezy/ingest/nws_actor.py`,
around `:981-982`) needs re-review. It does NOT mean this test is broken.**

Background
----------
`_persist_batch` nudges a colliding `retrieved_at_ns` to `existing_max_ts_init + 1`
to defeat a silent-data-loss trap in `ParquetDataCatalog`. That trap, as observed
against 1.231.0:

* The written parquet filename is derived from the batch's `ts_init` interval --
  `_timestamps_to_filename(data[0].ts_init, data[-1].ts_init)`
  (`nautilus_trader/persistence/catalog/parquet.py:375`, inside `_write_chunk`,
  which starts at `:357`).
* Writing a second batch whose interval produces the SAME filename is silently
  skipped: `_write_chunk` prints `"File ... already exists, skipping write"`
  (`parquet.py:379`) and returns normally -- no exception, nothing raised, the
  rows are simply discarded.
* Equal `ts_init` values WITHIN one batch are legal: `_objects_to_table`
  (`parquet.py:398`) requires only that the batch be "monotonically increasing
  (or non-decreasing)" based on `ts_init` (`parquet.py:406-411`), so a batch of
  two records sharing one `ts_init` is accepted and yields two rows in one file.

This module writes directly against a real `ParquetDataCatalog` in `tmp_path`,
never through `breezy.persistence.catalog.write_records` -- the point is to pin
what NAUTILUS does with these intervals, independent of Breezy's own wrapper
(which is already covered by `tests/unit/test_persistence_catalog.py` and by the
narrower `tests/contract/test_catalog_nws_records.py::
test_rewrite_of_same_timestamp_range_is_not_silently_skipped`). No network I/O;
no hard-coded absolute dates -- every timestamp here is derived from a base
anchored to the time the test runs, never a fixed calendar date.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.core.data import Data
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.nws_raw_product import RAW_PRODUCT_SCHEMA_VERSION, NwsRawProduct, sha256_text

pytestmark = pytest.mark.contract

# Anchored to "now", not a fixed calendar date: a hard-coded absolute date has
# already once made an unrelated test fail the moment the wall clock passed it
# (docs/plans/NWS_COLLECTION_RUNTIME_PLAN.md, WI-1). Nothing here drives a real
# clock or timer -- these are plain field values on hand-built `Data` records --
# but the base stays relative on principle.
_NOW = dt.datetime.now(tz=dt.UTC).replace(minute=0, second=0, microsecond=0)
_BASE_DAY = (_NOW - dt.timedelta(days=3)).date()
_BASE_NS = int(_NOW.timestamp() * 1_000_000_000)
_MINUTE_NS = 60_000_000_000
_SHA = hashlib.sha256(b"CDUS41 KOKX INTERVAL-CONTRACT").hexdigest()


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _BASE_DAY,
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
        "issuance_time_ns": _BASE_NS,
        "retrieved_at_ns": _BASE_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _BASE_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def make_raw_product(**overrides: Any) -> NwsRawProduct:
    raw_text = str(overrides.pop("raw_text", "CDUS41 KOKX INTERVAL-CONTRACT\nCLINYC\n"))
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "product_uuid": "00000000-0000-4000-8000-000000000002",
        "product_code": "CLI",
        "issuing_office": "KOKX",
        "wmo_collective_id": "CDUS41",
        "awips_pil": "CLINYC",
        "wmo_bbb_token": None,
        "issuance_time_ns": _BASE_NS,
        "retrieved_at_ns": _BASE_NS,
        "climate_day": _BASE_DAY,
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


def make_catalog(tmp_path: Path) -> ParquetDataCatalog:
    root = tmp_path / "catalog"
    root.mkdir(parents=True, exist_ok=True)
    return ParquetDataCatalog(path=root)


def _parquet_files(catalog: ParquetDataCatalog, data_cls: type[Data]) -> list[str]:
    return list(catalog.get_file_list_from_data_cls(data_cls))


# --------------------------------------------------------------------------------------
# 1. Equal ts_init WITHIN a single batch is accepted.
# --------------------------------------------------------------------------------------


def test_equal_ts_init_within_one_batch_is_accepted_and_all_rows_survive(
    tmp_path: Path,
) -> None:
    """Two records sharing one `ts_init` in a single call must both land.

    Pins that `_require_non_decreasing` (`src/breezy/persistence/catalog.py:884-890`,
    NOT modified by this test) is no stricter than Nautilus itself: Nautilus's own
    gate (`parquet.py:406-411`) accepts non-decreasing, not strictly increasing.
    """
    catalog = make_catalog(tmp_path)
    first = make_climate_day(climate_day=_BASE_DAY, tmax_f=84, retrieved_at_ns=_BASE_NS)
    second = make_climate_day(
        climate_day=_BASE_DAY + dt.timedelta(days=1),
        tmax_f=91,
        retrieved_at_ns=_BASE_NS,  # identical ts_init -- legal within one batch
    )
    assert first.ts_init == second.ts_init

    catalog.write_data([first, second])

    stored = catalog.query(data_cls=NwsClimateDay)
    restored_tmax = sorted(r.data.tmax_f for r in stored)

    assert restored_tmax == [84, 91], "both rows of the equal-ts_init batch must be readable back"
    assert len(_parquet_files(catalog, NwsClimateDay)) == 1, (
        "one shared ts_init interval collapses to one filename -- this is exactly "
        "why a same-range REWRITE (test below) collides and is silently skipped"
    )


def test_raw_product_also_accepts_equal_ts_init_within_one_batch(tmp_path: Path) -> None:
    """The same acceptance rule holds for `NwsRawProduct`, not just `NwsClimateDay`."""
    catalog = make_catalog(tmp_path)
    first = make_raw_product(raw_text="CDUS41 KOKX A\nCLINYC\n", retrieved_at_ns=_BASE_NS)
    second = make_raw_product(
        raw_text="CDUS41 KOKX B\nCLINYC\n",
        product_uuid="00000000-0000-4000-8000-000000000003",
        retrieved_at_ns=_BASE_NS,
    )

    catalog.write_data([first, second])

    stored = catalog.query(data_cls=NwsRawProduct)

    assert len(stored) == 2


# --------------------------------------------------------------------------------------
# 2. An exact-range rewrite is SILENTLY skipped -- this is the data-loss trap itself.
# --------------------------------------------------------------------------------------


def test_DATA_LOSS_an_exact_ts_init_range_rewrite_is_silently_discarded_not_raised(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """THE TRAP: a second batch whose interval matches an existing file vanishes.

    No exception. No logger record. `_write_chunk` prints to stdout and returns
    normally, and the second batch's row is gone. This is precisely the behaviour
    `_persist_batch`'s `existing_max_ts_init + 1` nudge exists to avoid ever
    reaching in production. If this test goes RED because Nautilus now raises (or
    otherwise stops silently discarding), that is GOOD NEWS for correctness but
    means the nudge should be re-evaluated -- it does not mean this test is wrong.
    """
    catalog = make_catalog(tmp_path)
    original = make_climate_day(tmax_f=84, retrieved_at_ns=_BASE_NS)
    catalog.write_data([original])
    capsys.readouterr()

    before = catalog.query(data_cls=NwsClimateDay)
    assert [r.data.tmax_f for r in before] == [84]

    colliding = make_climate_day(
        tmax_f=99,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_BASE_NS,  # SAME ts_init interval as `original` -> same filename
    )
    catalog.write_data([colliding])  # returns normally; raises nothing

    stdout = capsys.readouterr().out
    after = catalog.query(data_cls=NwsClimateDay)

    assert "already exists, skipping write" in stdout, (
        "empirical observation of the skip message -- see completion report for the "
        "verbatim capture"
    )
    assert len(after) == len(before) == 1, "row count is unchanged by the colliding write"
    assert [r.data.tmax_f for r in after] == [84], "the original survives; the correction is lost"
    assert not any(r.data.tmax_f == 99 for r in after), "the second batch never landed anywhere"


# --------------------------------------------------------------------------------------
# 3. An adjacent, strictly-greater interval (the nudge's own strategy) writes cleanly.
# --------------------------------------------------------------------------------------


def test_existing_max_plus_one_ts_init_writes_as_a_genuinely_new_file(tmp_path: Path) -> None:
    """Pins that the nudge's exact strategy -- `existing_max_ts_init + 1` -- works.

    A single-nanosecond bump is enough to produce a disjoint interval and
    therefore a distinct filename, so both records persist.
    """
    catalog = make_catalog(tmp_path)
    original = make_climate_day(tmax_f=84, retrieved_at_ns=_BASE_NS)
    catalog.write_data([original])

    existing_max_ts_init = max(r.ts_init for r in catalog.query(data_cls=NwsClimateDay))
    nudged = make_climate_day(
        climate_day=_BASE_DAY + dt.timedelta(days=1),
        tmax_f=99,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=existing_max_ts_init + 1,
    )

    catalog.write_data([nudged])  # must not be skipped

    stored = catalog.query(data_cls=NwsClimateDay)

    assert sorted(r.data.tmax_f for r in stored) == [84, 99], "rows accumulate; nothing is lost"
    assert len(_parquet_files(catalog, NwsClimateDay)) == 2, "a genuinely new, disjoint file"


def test_a_merely_later_but_still_colliding_interval_still_collides(tmp_path: Path) -> None:
    """Negative control for #3: "later" alone is not sufficient -- the INTERVAL must differ.

    Writing at the exact same `ts_init` a second time (not nudged) reproduces the
    trap even though, chronologically, the write itself happens "later" in the
    test. This guards against a shallow fix that bumps some unrelated field
    while leaving `ts_init` untouched.
    """
    catalog = make_catalog(tmp_path)
    catalog.write_data([make_climate_day(tmax_f=84, retrieved_at_ns=_BASE_NS)])

    not_nudged = make_climate_day(
        tmax_f=99,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_BASE_NS,  # deliberately NOT bumped
    )
    catalog.write_data([not_nudged])

    stored = catalog.query(data_cls=NwsClimateDay)

    assert [r.data.tmax_f for r in stored] == [84], "un-nudged same ts_init still collides"

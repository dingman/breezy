"""F13-C1 S1: US-source archive keys, one source per writer, archive_cache untouched."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_CACHE = REPO_ROOT / "src" / "breezy" / "persistence" / "archive_cache.py"
#: sha256 of archive_cache.py at F13-C1 S1 (R27: the module is byte-unchanged).
ARCHIVE_CACHE_SHA256 = "27559447635781105cc8067d805b7c6dd031093e2d3597f5b76c60767bee191f"
RUN_TS = 1_790_000_000_000_000_000


class _Clock:
    def timestamp_ns(self) -> int:
        return RUN_TS + 5


def test_archive_cache_module_is_byte_unchanged() -> None:
    assert hashlib.sha256(ARCHIVE_CACHE.read_bytes()).hexdigest() == ARCHIVE_CACHE_SHA256


def test_us_source_products_table_does_not_modify_iem_mos_model_products() -> None:
    from breezy.persistence.archive_cache import IEM_MOS_MODEL_PRODUCTS
    from breezy.persistence.us_source_request import US_SOURCE_PRODUCTS

    assert dict(IEM_MOS_MODEL_PRODUCTS) == {"NBS": "mos-nbs", "GFS": "mos-gfs"}
    assert set(US_SOURCE_PRODUCTS).isdisjoint({"iem-mos", "iem-asos-1min"})


def test_each_writer_has_exactly_one_source_value() -> None:
    from breezy.persistence import us_source_request as m

    requests = {
        "us-lamp-live": m.lamp_live_request(RUN_TS),
        "us-lav-iem": m.lav_iem_request("KSFO", RUN_TS),
        "us-pfm-afos": m.pfm_afos_request("KSFO", RUN_TS),
        "us-lamp-mdl": m.lamp_mdl_request(RUN_TS),
    }
    assert {name: r.source for name, r in requests.items()} == {n: n for n in requests}
    assert set(m.US_SOURCE_PRODUCTS) == set(requests)
    assert len({m.US_SOURCE_PRODUCTS[s] for s in requests}) == 4


def test_new_factories_reexported_via_archive_request() -> None:
    from breezy.persistence import archive_request as ar
    from breezy.persistence import us_source_request as m

    for name in (
        "lamp_live_request",
        "lamp_mdl_request",
        "lav_iem_request",
        "pfm_afos_request",
        "normalised_request",
        "revision_request",
        "US_SOURCE_PRODUCTS",
    ):
        assert getattr(ar, name) is getattr(m, name)
        assert name in ar.__all__


@pytest.mark.parametrize(
    ("station", "wfo"),
    [("KNYC", "OKX"), ("KLAX", "LOX"), ("KMDW", "LOT"), ("KSFO", "MTR"), ("KMIA", "MFL")],
)
def test_pfm_key_is_icao_pfm_wfo_per_a0_r2(station: str, wfo: str) -> None:
    from breezy.persistence.us_source_request import pfm_afos_request

    request = pfm_afos_request(station, RUN_TS)

    assert (request.source, request.station, request.model) == ("us-pfm-afos", station, wfo)
    assert request.product == "pfm-r0"


def test_pfm_point_map_is_the_closed_five_entry_a0_r2_map() -> None:
    from breezy.persistence.us_source_request import PFM_POINTS

    assert {k: (v.wfo, v.point_name) for k, v in PFM_POINTS.items()} == {
        "KNYC": ("OKX", "Central Park-New York NY"),
        "KLAX": ("LOX", "Los Angeles Airport CA"),
        "KMDW": ("LOT", "Chicago Midway Airport-Cook IL"),
        "KSFO": ("MTR", "San Francisco Airport-San Mateo CA"),
        "KMIA": ("MFL", "Miami-Miami Dade FL"),
    }


def test_pfm_unmapped_station_refused() -> None:
    from breezy.persistence.us_source_request import pfm_afos_request

    with pytest.raises(ValueError, match="closed PFM point"):
        pfm_afos_request("KJFK", RUN_TS)


def test_lav_station_outside_closed_set_refused() -> None:
    from breezy.persistence.us_source_request import lav_iem_request

    with pytest.raises(ValueError, match="closed set"):
        lav_iem_request("KJFK", RUN_TS)


def test_revision_request_window_is_run_ts_to_run_ts_plus_one_ns() -> None:
    from breezy.persistence.us_source_request import lamp_live_request

    request = lamp_live_request(RUN_TS, revision=3)

    assert request.product == "lamp-lavtxt-r3"
    assert (request.window_start, request.window_end) == (RUN_TS, RUN_TS + 1)


def test_revisions_have_distinct_cache_keys() -> None:
    from breezy.persistence.us_source_request import lamp_live_request

    keys = {lamp_live_request(RUN_TS, revision=n).cache_key() for n in range(4)}
    assert len(keys) == 4


@pytest.mark.parametrize("bad", [-1, True, 1.5, "1"])
def test_revision_must_be_a_non_negative_int(bad: object) -> None:
    from breezy.persistence.us_source_request import revision_product

    with pytest.raises(ValueError, match="non-negative"):
        revision_product("pfm", bad)  # type: ignore[arg-type]


def test_unknown_source_refused() -> None:
    from breezy.persistence.us_source_request import revision_request

    with pytest.raises(ValueError, match="closed set"):
        revision_request("iem-mos", "KSFO", RUN_TS, 0, model=None)


def test_normalised_request_has_distinct_product_per_revision() -> None:
    from breezy.persistence.us_source_request import (
        normalised_request,
        pfm_afos_request,
        revision_product_pattern,
    )

    raw = pfm_afos_request("KMIA", RUN_TS, revision=2)
    norm = normalised_request(raw)

    assert norm.product == "pfm-norm-r2"
    assert norm.cache_key() != raw.cache_key()
    assert (norm.source, norm.station, norm.model) == (raw.source, raw.station, raw.model)
    assert revision_product_pattern("pfm").fullmatch(norm.product) is None
    assert revision_product_pattern("pfm").fullmatch(raw.product) is not None


def test_normalised_request_refuses_non_revision_product() -> None:
    from breezy.persistence.archive_cache import ArchiveRequest
    from breezy.persistence.us_source_request import normalised_request

    odd = ArchiveRequest("us-lamp-live", "ALL", "lamp-lavtxt", 1, 2, None)
    with pytest.raises(ValueError, match="raw revision product"):
        normalised_request(odd)


def test_revision_product_pattern_is_a_fullmatch_not_a_prefix() -> None:
    from breezy.persistence.us_source_request import revision_product_pattern

    pattern = revision_product_pattern("pfm")
    assert pattern.fullmatch("pfm-r12") is not None
    assert pattern.fullmatch("pfm-r") is None
    assert pattern.fullmatch("xpfm-r1") is None
    assert pattern.fullmatch("pfm-r1-extra") is None


def test_normalised_csv_roundtrips_through_archive_cache_with_digest(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCache
    from breezy.persistence.us_source_request import normalised_request, pfm_afos_request

    csv_bytes = (
        b"source,source_version,station_icao,run_ts_utc,valid_ts_utc,variable,value\n"
        b"us-pfm-afos,v1,KSFO,2026-10-06T01:00:00Z,2026-10-06T20:00:00Z,tmax,71\n"
    )
    request = normalised_request(pfm_afos_request("KSFO", RUN_TS))
    cache = ArchiveCache(tmp_path, fetch=lambda _r: csv_bytes, clock=_Clock())

    assert cache.get_or_fetch(request) == csv_bytes
    (entry,) = cache.entries("us-pfm-afos")
    assert entry.sha256 == hashlib.sha256(csv_bytes).hexdigest()
    assert entry.rows == 1
    assert cache.read(request) == csv_bytes

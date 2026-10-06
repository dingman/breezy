"""F13-C1 US-source archive keys: one ``source`` per writer, closed key maps.

This module only CONSTRUCTS :class:`ArchiveRequest`; ``archive_cache`` is
unmodified (plan r3.1 R27). No HTTP client, no hostname, no URL.

Key shapes (A0-R2, R20, R28):

* ``us-lamp-live``  station ``ALL`` (one bulletin carries every station), model None.
* ``us-lav-iem``    station ``<ICAO>``, model ``LAV``.
* ``us-pfm-afos``   station ``<ICAO>``, product ``pfm``, model ``<WFO>``.
* ``us-lamp-mdl``   station ``ALL``, model None.

A RAW payload is always a revision: product ``<base>-r<N>`` with
``window_start = run_ts`` and ``window_end = run_ts + 1 ns``; the first-seen
payload is ``-r0``. A normalised CSV is stored under the distinct product
``<base>-norm-r<N>`` so the revision digest set never sees it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from breezy.persistence.archive_cache import ArchiveRequest

__all__ = [
    "LAMP_ALL_STATION",
    "LAMP_EXT_STATION",
    "LAV_MODEL",
    "PFM_POINTS",
    "US_LAMP_LIVE_SOURCE",
    "US_LAMP_MDL_SOURCE",
    "US_LAV_IEM_SOURCE",
    "US_PFM_AFOS_SOURCE",
    "US_SOURCE_PRODUCTS",
    "US_SOURCE_STATIONS",
    "PfmPoint",
    "lamp_live_request",
    "lamp_mdl_request",
    "lav_iem_request",
    "normalised_request",
    "pfm_afos_request",
    "revision_product",
    "revision_product_pattern",
    "revision_request",
]

US_LAMP_LIVE_SOURCE: Final[str] = "us-lamp-live"
US_LAV_IEM_SOURCE: Final[str] = "us-lav-iem"
US_PFM_AFOS_SOURCE: Final[str] = "us-pfm-afos"
US_LAMP_MDL_SOURCE: Final[str] = "us-lamp-mdl"

#: source -> base raw product. A SEPARATE table: ``IEM_MOS_MODEL_PRODUCTS`` is
#: MOS-only and is never edited (R17/R27).
US_SOURCE_PRODUCTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        US_LAMP_LIVE_SOURCE: "lamp-lavtxt",
        US_LAV_IEM_SOURCE: "lav-iem",
        US_PFM_AFOS_SOURCE: "pfm",
        US_LAMP_MDL_SOURCE: "lamp-mdl",
    }
)

LAV_MODEL: Final[str] = "LAV"
#: Station token for a bulletin that carries every station in one payload.
LAMP_ALL_STATION: Final[str] = "ALL"
#: The ``lavtxt_ext`` bulletin (forecast hours 26-38) rides the SAME source and base product
#: under this station token, so it never collides with the main bulletin's ``ALL`` key. It is a
#: key token only: it is not in ``US_SOURCE_STATIONS`` (so no per-station request builder
#: accepts it) and station-enumerating readers must skip it. Raw-only until its layout is
#: verified.
LAMP_EXT_STATION: Final[str] = "ALLEXT"
#: The closed station set shared with the IEM MOS backfill, KNYC included (R33).
US_SOURCE_STATIONS: Final[tuple[str, ...]] = ("KLAX", "KMDW", "KMIA", "KNYC", "KSFO")
_NORMALISED_INFIX: Final[str] = "-norm"
_NS_PER_REVISION_WINDOW: Final[int] = 1


@dataclass(frozen=True, slots=True)
class PfmPoint:
    """One closed PFM map entry: the WFO and the forecast-point NAME (A0-R2).

    The zone code is deliberately absent: zone codes are shared between
    stations (ILZ104, CAZ508) so they are never a key.
    """

    wfo: str
    point_name: str


#: KMIA is inferred (A0-R2); B0 confirms it by lat/lon.
PFM_POINTS: Final[Mapping[str, PfmPoint]] = MappingProxyType(
    {
        "KNYC": PfmPoint("OKX", "Central Park-New York NY"),
        "KLAX": PfmPoint("LOX", "Los Angeles Airport CA"),
        "KMDW": PfmPoint("LOT", "Chicago Midway Airport-Cook IL"),
        "KSFO": PfmPoint("MTR", "San Francisco Airport-San Mateo CA"),
        "KMIA": PfmPoint("MFL", "Miami-Miami Dade FL"),
    }
)


def revision_product(base_product: str, revision: int) -> str:
    """``<base>-r<N>``. ``N`` must be a non-negative int (bool refused)."""
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError(f"revision must be a non-negative int, was {revision!r}")
    return f"{base_product}-r{revision}"


def revision_product_pattern(base_product: str) -> re.Pattern[str]:
    """``fullmatch(<base>-r\\d+)``; group 1 is the revision number (R34)."""
    return re.compile(rf"{re.escape(base_product)}-r(\d+)")


def _require_source(source: str) -> str:
    base = US_SOURCE_PRODUCTS.get(source)
    if base is None:
        raise ValueError(
            f"unknown US source {source!r}; the closed set is {sorted(US_SOURCE_PRODUCTS)}"
        )
    return base


def _require_station(station: str) -> str:
    if station not in US_SOURCE_STATIONS:
        raise ValueError(
            f"station {station!r} is outside the closed set {list(US_SOURCE_STATIONS)}"
        )
    return station


def revision_request(
    source: str,
    station: str,
    run_ts_ns: int,
    revision: int,
    *,
    model: str | None,
) -> ArchiveRequest:
    """The raw-payload key for revision ``revision`` of ``(source, station, run_ts)``."""
    base = _require_source(source)
    return ArchiveRequest(
        source=source,
        station=station,
        product=revision_product(base, revision),
        window_start=run_ts_ns,
        window_end=run_ts_ns + _NS_PER_REVISION_WINDOW,
        model=model,
    )


def lamp_live_request(run_ts_ns: int, *, revision: int = 0) -> ArchiveRequest:
    return revision_request(US_LAMP_LIVE_SOURCE, LAMP_ALL_STATION, run_ts_ns, revision, model=None)


def lamp_mdl_request(run_ts_ns: int, *, revision: int = 0) -> ArchiveRequest:
    return revision_request(US_LAMP_MDL_SOURCE, LAMP_ALL_STATION, run_ts_ns, revision, model=None)


def lav_iem_request(station: str, run_ts_ns: int, *, revision: int = 0) -> ArchiveRequest:
    return revision_request(
        US_LAV_IEM_SOURCE, _require_station(station), run_ts_ns, revision, model=LAV_MODEL
    )


def pfm_afos_request(station: str, run_ts_ns: int, *, revision: int = 0) -> ArchiveRequest:
    """``station=<ICAO>``, ``product=pfm-r<N>``, ``model=<WFO>`` (A0-R2)."""
    point = PFM_POINTS.get(station)
    if point is None:
        raise ValueError(
            f"no closed PFM point for station {station!r}; refused, never guessed "
            f"(closed set {sorted(PFM_POINTS)})"
        )
    return revision_request(US_PFM_AFOS_SOURCE, station, run_ts_ns, revision, model=point.wfo)


def normalised_request(raw: ArchiveRequest) -> ArchiveRequest:
    """The key for the normalised CSV derived from a raw revision request.

    Same identity as the raw request except the product, ``<base>-norm-r<N>``
    (one per revision, so revisions never collide). It never matches the
    ``<base>-r\\d+`` fullmatch the revision digest set uses (R32).
    """
    base = _require_source(raw.source)
    matched = revision_product_pattern(base).fullmatch(raw.product)
    if matched is None:
        raise ValueError(f"{raw.product!r} is not a raw revision product of {raw.source!r}")
    return ArchiveRequest(
        source=raw.source,
        station=raw.station,
        product=f"{base}{_NORMALISED_INFIX}-r{matched.group(1)}",
        window_start=raw.window_start,
        window_end=raw.window_end,
        model=raw.model,
    )

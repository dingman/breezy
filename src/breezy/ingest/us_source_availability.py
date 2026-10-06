"""Pure availability-interval rule for the F13 US sources (plan §2, R5, R26, R29).

``available_at`` returns ``(ts, basis, miss_ts)``: the source became public in
``(miss_ts, ts]`` and backtests anchor on the UPPER bound ``ts``. Nothing here
performs I/O, and nothing imports the NBP store: the ``max(observed, run +
floor)`` pattern is re-stated, with parity pinned by test.

Floors:

* ``MINIMUM_PUBLICATION_LAG_NS`` is a SANITY floor only (R29). Its keys
  (``NBM_NBP``, ``GFS_MOS``, ...) are read, never extended.
* LAMP and PFM have no key there; their floor comes from the prereg A0 table
  passed in as :class:`LagPrereg`.
* A row with no observed time takes ``nominal_plus_conservative_lag``: the
  prereg conservative lag, which must be >= the floor and >= the C1-measured
  maximum where one exists. It is never the bare sanity floor.
"""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Final, NamedTuple

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS

__all__ = [
    "AvailabilityBasis",
    "AvailabilityConfigError",
    "AvailabilityResult",
    "LagFreeze",
    "LagPrereg",
    "LagSample",
    "Observation",
    "available_at",
    "freeze_lag",
    "parse_last_modified_ns",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000
LagKey = str | tuple[str, str]


class AvailabilityConfigError(ValueError):
    """The prereg lag table cannot answer for a source. Refused, never defaulted."""


class AvailabilityBasis(enum.StrEnum):
    MEASURED_HEADER = "measured_header"
    WMO_HEADER = "wmo_header"
    FIRST_SEEN = "first_seen"
    NOMINAL_PLUS_CONSERVATIVE_LAG = "nominal_plus_conservative_lag"


class AvailabilityResult(NamedTuple):
    """``(ts, basis, miss_ts, clamped_to_miss)``. ``miss_ts`` is None when no miss was seen.

    ``clamped_to_miss`` is True when the observed time was at or before a poll
    that saw the file absent, so ``ts`` was raised to ``miss_ts + 1`` (the
    conservative upper bound). The basis is unchanged; the census counts these.

    ``basis`` is the enum value, with ``@<host_tag>`` appended when the
    observation came from a named host (``measured_header@iem``).
    """

    ts: int
    basis: str
    miss_ts: int | None
    clamped_to_miss: bool = False


@dataclass(frozen=True, slots=True)
class Observation:
    """What a poll actually saw. Every field is optional; absence is data.

    ``last_modified`` is the RAW header text (parsed here, tolerantly).
    ``host_tag`` names the host the header came from (``iem``, ``mdl``,
    ``s3``, ``nomads``): a mirror's Last-Modified is its ingest time, so it is
    tagged and never labelled ``wmo_header``.
    """

    first_seen_ns: int | None = None
    last_miss_ns: int | None = None
    last_modified: str | None = None
    wmo_header_ns: int | None = None
    host_tag: str | None = None


@dataclass(frozen=True, slots=True)
class LagPrereg:
    """The prereg A0 lag table. Keys are a source or a ``(source, version)`` pair.

    ``sanity_floors_ns`` supplies floors only for sources absent from
    ``MINIMUM_PUBLICATION_LAG_NS``. ``conservative_lags_ns`` must each be >= the
    resolved floor and >= ``measured_max_lag_ns`` where one exists (R29).
    """

    sanity_floors_ns: Mapping[LagKey, int]
    conservative_lags_ns: Mapping[LagKey, int]
    measured_max_lag_ns: Mapping[LagKey, int] | None = None

    def __post_init__(self) -> None:
        for table in (self.sanity_floors_ns, self.conservative_lags_ns, self.measured_max_lag_ns):
            for key, value in (table or {}).items():
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise AvailabilityConfigError(f"lag for {key!r} must be a non-negative int ns")
        for key, lag in self.conservative_lags_ns.items():
            source = key if isinstance(key, str) else key[0]
            floor = _floor_ns(source, key if not isinstance(key, str) else None, self)
            if lag < floor:
                raise AvailabilityConfigError(
                    f"conservative lag for {key!r} is below its sanity floor"
                )
            measured = _measured_max_for(self.measured_max_lag_ns, key)
            if measured is not None and lag < measured:
                raise AvailabilityConfigError(
                    f"conservative lag for {key!r} is below the measured maximum"
                )


def _lookup(table: Mapping[LagKey, int] | None, key: LagKey) -> int | None:
    if table is None:
        return None
    if key in table:
        return table[key]
    if isinstance(key, tuple):
        return table.get(key[0])
    return None


def _measured_max_for(table: Mapping[LagKey, int] | None, key: LagKey) -> int | None:
    """Largest measured max that constrains ``key``.

    A source-only key is constrained by the source's measurement under any
    version; a versioned key by its own and by the source-only measurement.
    """
    if table is None:
        return None
    source = key if isinstance(key, str) else key[0]
    applicable = [
        value
        for k, value in table.items()
        if k == key
        or k == source
        or (isinstance(key, str) and isinstance(k, tuple) and k[0] == key)
    ]
    return max(applicable) if applicable else None


def _floor_ns(source: str, versioned: LagKey | None, prereg: LagPrereg) -> int:
    key: LagKey = versioned if versioned is not None else source
    if source in MINIMUM_PUBLICATION_LAG_NS:
        return MINIMUM_PUBLICATION_LAG_NS[source]
    floor = _lookup(prereg.sanity_floors_ns, key)
    if floor is None:
        raise AvailabilityConfigError(f"no sanity floor for source {source!r} in the prereg table")
    return floor


def parse_last_modified_ns(value: str | None) -> int | None:
    """RFC 2822/1123 ``Last-Modified`` to UTC ns; None when missing or unparsable."""
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return int(parsed.astimezone(dt.UTC).timestamp()) * _NS_PER_SECOND


def _require_ns(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int of UNIX nanoseconds")
    return value


def _label(basis: AvailabilityBasis, host_tag: str | None) -> str:
    return f"{basis.value}@{host_tag}" if host_tag else basis.value


def available_at(
    source: str,
    version: str,
    run_ts: int,
    observed: Observation | None,
    *,
    prereg: LagPrereg,
) -> AvailabilityResult:
    """Availability interval for one run of one source.

    Precedence, strongest evidence first:

    1. ``wmo_header_ns`` (PFM): exact issuance time -> ``wmo_header``.
    2. a parsable ``last_modified`` -> ``measured_header[@host]``.
    3. ``first_seen_ns`` (also when ``last_modified`` is absent or unparsable)
       -> ``first_seen[@host]``.
    4. nothing observed -> ``nominal_plus_conservative_lag``.

    Cases 1-3 return ``max(observed, run_ts + floor)``, then are clamped to
    ``last_miss + 1`` so the anchor never precedes provable absence (leakage);
    ``clamped_to_miss`` records the event. The floor is a sanity clamp, never a
    lag estimate. ``ts`` therefore never precedes ``run_ts``.
    """
    if not source or not version:
        raise ValueError("source and version must be non-empty")
    run = _require_ns("run_ts", run_ts)
    assert run is not None
    versioned: LagKey = (source, version)
    floor_ns = _floor_ns(source, versioned, prereg)
    floor_ts = run + floor_ns
    obs = observed or Observation()
    miss = _require_ns("last_miss_ns", obs.last_miss_ns)
    host = obs.host_tag

    def _anchored(
        observed_ts: int, basis: AvailabilityBasis, tag: str | None
    ) -> AvailabilityResult:
        ts = max(observed_ts, floor_ts)
        clamped = miss is not None and ts <= miss
        if miss is not None and clamped:
            ts = miss + 1
        return AvailabilityResult(ts, _label(basis, tag), miss, clamped)

    wmo = _require_ns("wmo_header_ns", obs.wmo_header_ns)
    if wmo is not None:
        return _anchored(wmo, AvailabilityBasis.WMO_HEADER, None)

    modified = parse_last_modified_ns(obs.last_modified)
    if modified is not None:
        return _anchored(modified, AvailabilityBasis.MEASURED_HEADER, host)

    first_seen = _require_ns("first_seen_ns", obs.first_seen_ns)
    if first_seen is not None:
        return _anchored(first_seen, AvailabilityBasis.FIRST_SEEN, host)

    conservative = _lookup(prereg.conservative_lags_ns, versioned)
    if conservative is None:
        raise AvailabilityConfigError(
            f"no conservative lag for {source!r}; refused rather than falling back to the floor"
        )
    return AvailabilityResult(
        run + max(conservative, floor_ns),
        AvailabilityBasis.NOMINAL_PLUS_CONSERVATIVE_LAG.value,
        None,
        False,
    )


@dataclass(frozen=True, slots=True)
class LagSample:
    """One observed lag (``ts - run_ts``). ``late`` rows are right-censored."""

    source: str
    lag_ns: int
    late: bool


@dataclass(frozen=True, slots=True)
class LagFreeze:
    """Lag-freeze result for one source: max over UNCENSORED samples only (R21, R26)."""

    source: str
    max_lag_ns: int | None
    uncensored_n: int
    late_n: int


def freeze_lag(samples: Iterable[LagSample], source: str, *, min_uncensored: int = 1) -> LagFreeze:
    """Maximum lag over non-``late`` samples; ``late`` rows are counted, never maxed.

    ``max_lag_ns`` is None until ``min_uncensored`` uncensored samples exist
    (R26), so an under-sampled source cannot freeze a lag.
    """
    if min_uncensored < 1:
        raise ValueError("min_uncensored must be >= 1")
    own = [s for s in samples if s.source == source]
    uncensored = [s.lag_ns for s in own if not s.late]
    enough = len(uncensored) >= min_uncensored
    return LagFreeze(
        source=source,
        max_lag_ns=max(uncensored) if enough else None,
        uncensored_n=len(uncensored),
        late_n=len(own) - len(uncensored),
    )

"""`StationObservation` -- one raw 5-minute ASOS/METAR temperature reading.

Pattern
-------
A hand-written `nautilus_trader.core.data.Data` subclass with explicit
``ts_event``/``ts_init`` properties, ``to_dict``/``from_dict``, a ``schema()``
classmethod, and **exactly one** ``register_arrow`` call at module scope --
the same in-tree pattern as :mod:`breezy.domain.nws_climate_day`
(``nws_climate_day.py:383-389``), for the same reason: ``@customdataclass``
routes ``from_arrow`` through ``from_dict``, which lets a vanished column
arrive as a dataclass default rather than raising.

Timestamps
----------
``ts_init`` is ``received_at_ns`` -- the instant Breezy received the bytes --
and is not a constructor parameter under that name, so it cannot be
re-stamped from a clock; the constructor takes ``received_at_ns`` and derives
``ts_init`` from it, mirroring ``NwsClimateDay.retrieved_at_ns``.

``ts_event`` is ``observed_at_ns`` -- the METAR's own measurement instant.
Arrival strictly after measurement is enforced: ``received_at_ns`` equal to
or before ``observed_at_ns`` is physically impossible for a real feed and is
rejected at construction, never merely logged.

No settlement-shaped column
----------------------------
This record stores the raw METAR value in **tenths of degrees Celsius**
(``temp_c_tenths``, the native METAR ``T``-group unit -- see
``breezy.ingest.iem_observations``), never a derived Fahrenheit or rounded
column. ``NwsClimateDay`` carries ``tmax_f``/``tmin_f``/``tavg_f`` because
those ARE the settlement datum, published verbatim by NWS; a
``StationObservation`` is one raw 5-minute reading, not a settlement value,
and deriving Fahrenheit here would let this record start to look like one.
Conversion (``c_tenths_to_f``) and rounding (``round_half_up_f``) happen at
the point of consumption -- see
:mod:`breezy.strategy.weather_common.running_extreme`.

Provenance, not physics
------------------------
``assumed_publication_lag_ns`` is declared PROVENANCE ONLY: an estimate of
how stale a fresh IEM row typically is when Breezy observes it, recorded so
an operator reading the catalog can see what the feed's own latency was
assumed to be. It is NEVER subtracted from ``observed_at_ns``, never folded
into `R(t)`, staleness, or any refusal -- see
``docs/plans/BL24_LIVE_RT_2026-09-04.md`` amendment A6.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.serialization.arrow.serializer import register_arrow

from breezy.domain.climate_day import climate_day_for_instant
from breezy.domain.strict_arrow import make_strict_decoder, make_strict_encoder
from breezy.domain.validation import require_bool, require_int, require_text

#: Bumped to 2 when `precision_c_tenths`/`is_metar` were added (amendment
#: A13, BL-24 Seam A-2) -- the Arrow schema gained two required columns.
STATION_OBSERVATION_SCHEMA_VERSION: Final[int] = 2

_NS_PER_SECOND: Final[int] = 1_000_000_000

#: Channels whose `assumed_publication_lag_ns` must be strictly positive.
#: WIDENED from the single IEM channel when the NWS API channel landed (BL-24
#: Seam B) -- never relaxed: every live feed declares a measured lag.
_POSITIVE_LAG_CHANNELS: Final[tuple[str, ...]] = ("iem_asos_metar", "nws_api_observations")


class StationObservation(Data):
    """One station's raw 5-minute ASOS/METAR temperature reading.

    Parameters
    ----------
    station : str
        The IEM ASOS station id (e.g. ``"KNYC"``), read from the registry's
        ``iem_asos_id``, never derived from the ICAO field.
    observed_at_ns : int
        UNIX nanoseconds of the METAR's own measurement instant. Becomes
        ``ts_event``.
    received_at_ns : int
        UNIX nanoseconds when Breezy received the bytes. Becomes ``ts_init``.
        Must be strictly greater than ``observed_at_ns`` -- arrival at or
        before the moment of measurement is not physically possible.
    temp_c_tenths : int
        Raw METAR ``T``-group value, tenths of a degree Celsius. Never
        converted to Fahrenheit or rounded on this record (see module
        docstring).
    precision_c_tenths : int
        The FULL width, in tenths of a degree Celsius, of the reporting
        interval -- NOT a half-width: ``10`` for an integer-Celsius row such
        as the NWS 5-minute API (the true value lies in
        ``[x - 0.5, x + 0.5)`` degrees C, i.e. a 10-tenths-wide interval,
        half-width 5 either side of ``x``), ``5`` for a METAR ``T``-group
        reading -- recorded only as descriptive provenance, since a METAR
        row's own tenths-resolution value is consumed as an EXACT point (see
        ``breezy.strategy.weather_common.running_extreme``), never widened
        into an interval by this field. Amendment A13.
    is_metar : bool
        ``True`` when this reading came from a METAR ``T``-group (tenths
        resolution); ``False`` for an integer-Celsius source. Amendment A13.
    source_channel : str
        Feed the reading came from (e.g. ``"iem_asos_metar"``).
    assumed_publication_lag_ns : int
        Declared provenance only -- see module docstring. Required to be
        strictly positive when ``source_channel == "iem_asos_metar"``.
    schema_version : int
        Revision of this record layout.

    """

    def __init__(
        self,
        *,
        station: str,
        observed_at_ns: int,
        received_at_ns: int,
        temp_c_tenths: int,
        precision_c_tenths: int,
        is_metar: bool,
        source_channel: str,
        assumed_publication_lag_ns: int,
        schema_version: int = STATION_OBSERVATION_SCHEMA_VERSION,
    ) -> None:
        self.station = require_text(station, "station")
        self.observed_at_ns = require_int(observed_at_ns, "observed_at_ns")
        self.received_at_ns = require_int(received_at_ns, "received_at_ns")
        self.temp_c_tenths = require_int(temp_c_tenths, "temp_c_tenths")
        self.precision_c_tenths = require_int(precision_c_tenths, "precision_c_tenths")
        self.is_metar = require_bool(is_metar, "is_metar")
        self.source_channel = require_text(source_channel, "source_channel")
        self.assumed_publication_lag_ns = require_int(
            assumed_publication_lag_ns, "assumed_publication_lag_ns",
        )
        self.schema_version = require_int(schema_version, "schema_version")

        if self.received_at_ns <= self.observed_at_ns:
            raise ValueError(
                f"`received_at_ns` ({self.received_at_ns}) must be strictly after "
                f"`observed_at_ns` ({self.observed_at_ns}); arrival cannot precede "
                f"or coincide with the measurement it reports",
            )

        if (
            self.source_channel in _POSITIVE_LAG_CHANNELS
            and self.assumed_publication_lag_ns <= 0
        ):
            raise ValueError(
                "`assumed_publication_lag_ns` must be positive for "
                f"source_channel={self.source_channel!r}, "
                f"was {self.assumed_publication_lag_ns}",
            )

        if self.precision_c_tenths <= 0:
            raise ValueError(
                f"`precision_c_tenths` must be positive, was {self.precision_c_tenths}",
            )

        self._ts_event = self.observed_at_ns
        self._ts_init = self.received_at_ns

    @property
    def ts_event(self) -> int:
        """UNIX nanoseconds of the METAR's own measurement instant."""
        return self._ts_event

    @property
    def ts_init(self) -> int:
        """UNIX nanoseconds when Breezy received the bytes (`received_at_ns`)."""
        return self._ts_init

    def climate_day(self, std_utc_offset_hours: float) -> dt.date:
        """The local-standard-time climate day containing `observed_at_ns`.

        Computed on demand rather than stored: the fixed standard-time
        offset is a per-site registry value, and storing it here would
        duplicate that SSOT on every record. Never DST-aware -- see
        `breezy.domain.climate_day.climate_day_for_instant`.

        Uses integer `divmod`, never float division: `observed_at_ns / 1e9`
        loses sub-microsecond precision at real epoch magnitudes, which is
        enough to round an instant across a day boundary.
        """
        seconds, nanoseconds = divmod(self.observed_at_ns, _NS_PER_SECOND)
        instant = dt.datetime.fromtimestamp(seconds, tz=dt.UTC) + dt.timedelta(
            microseconds=nanoseconds // 1_000,
        )
        return climate_day_for_instant(instant, std_utc_offset_hours)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"station={self.station!r}, "
            f"temp_c_tenths={self.temp_c_tenths}, "
            f"precision_c_tenths={self.precision_c_tenths}, "
            f"is_metar={self.is_metar}, "
            f"source_channel={self.source_channel!r}, "
            f"ts_event={self._ts_event}, ts_init={self._ts_init})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the record as Arrow-native values, keyed in `schema()` order."""
        return {
            "station": self.station,
            "temp_c_tenths": self.temp_c_tenths,
            "precision_c_tenths": self.precision_c_tenths,
            "is_metar": self.is_metar,
            "source_channel": self.source_channel,
            "assumed_publication_lag_ns": self.assumed_publication_lag_ns,
            "schema_version": self.schema_version,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> StationObservation:
        """Rebuild a record from `to_dict` output.

        Every key is read by direct subscript: a missing column raises
        `KeyError` here rather than silently adopting a default.
        """
        return cls(
            station=values["station"],
            observed_at_ns=values["ts_event"],
            received_at_ns=values["ts_init"],
            temp_c_tenths=values["temp_c_tenths"],
            precision_c_tenths=values["precision_c_tenths"],
            is_metar=values["is_metar"],
            source_channel=values["source_channel"],
            assumed_publication_lag_ns=values["assumed_publication_lag_ns"],
            schema_version=values["schema_version"],
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        """Return the explicit Arrow schema for this record type."""
        return pa.schema(
            [
                pa.field("station", pa.string(), nullable=False),
                pa.field("temp_c_tenths", pa.int64(), nullable=False),
                pa.field("precision_c_tenths", pa.int64(), nullable=False),
                pa.field("is_metar", pa.bool_(), nullable=False),
                pa.field("source_channel", pa.string(), nullable=False),
                pa.field("assumed_publication_lag_ns", pa.int64(), nullable=False),
                pa.field("schema_version", pa.int64(), nullable=False),
                pa.field("ts_event", pa.int64(), nullable=False),
                pa.field("ts_init", pa.int64(), nullable=False),
            ],
        )


# Registered exactly once, at module scope.
register_arrow(
    data_cls=StationObservation,
    schema=StationObservation.schema(),
    encoder=make_strict_encoder(StationObservation.schema()),
    decoder=make_strict_decoder(StationObservation, StationObservation.schema()),
)

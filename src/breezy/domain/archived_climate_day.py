"""`ArchivedClimateDay` -- one normalized CLI observation from the IEM archive.

Pattern
-------
A hand-written `nautilus_trader.core.data.Data` subclass with explicit
``ts_event``/``ts_init`` properties, ``to_dict``/``from_dict``, a ``schema()``
classmethod, and exactly one ``register_arrow`` call at module scope.

``@customdataclass`` is deliberately not used. Its generated Arrow decoder routes
through ``from_dict`` in a way that can let a vanished column arrive as a default,
which is silent drift on a schema that cannot be changed after the first fragment
is written. Since this type needs a strict decoder anyway, hand-writing the class
keeps the safety rule visible.

``register_arrow`` is called once. A second call for the same class can make the
global serializer registry disagree with the class's own schema, so the schema
used to encode and the schema used by the catalog would no longer be one fact.

Timestamps
----------
For archived rows, ``ts_init`` and ``ts_event`` are both the WMO issuance instant:
the public-information instant the backfill can defend. The real archive fetch
time is stored separately as ``archive_retrieved_at_ns`` for audit. Neither
``ts_init`` nor ``ts_event`` is a constructor parameter, so callers cannot stamp
or restamp the stream-ordering fields independently of ``issuance_time_ns``.

The live ``NwsClimateDay`` type uses ``ts_init`` for Breezy's receipt time. This
type does not make that claim, and it is intentionally not a subclass of the live
type: archived and live rows answer different point-in-time questions and must
not satisfy each other's runtime ``isinstance`` checks.

Revisions
---------
Archive corrections and retransmissions are accumulated as new rows, never
rewrites. Selection can order by ``(is_final, ts_init, revision_seq)``: finality
first, then the public issuance instant, then the caller-assigned revision within
one ``(station, climate_day, is_final)`` group.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.serialization.arrow.serializer import register_arrow

from breezy.domain.nws_climate_day import MISSING_VALUE_FLAGS
from breezy.domain.strict_arrow import make_strict_decoder, make_strict_encoder
from breezy.domain.validation import (
    require_bool,
    require_float,
    require_hex_digest,
    require_int,
    require_optional_int,
    require_optional_text,
    require_pure_date,
    require_text,
)
from breezy.domain.wmo import is_correction_bbb_token

ARCHIVED_CLIMATE_DAY_SCHEMA_VERSION: Final[int] = 1

_ADMISSION_ERAS: Final[frozenset[str]] = frozenset({"modern", "transitional"})
"""The only two legal `admission_era` values (see `docs/plans/CLI_BACKFILL_PLAN.md`).

`admission_era` is a sample-selection covariate that later bias analysis
depends on. Unlike a free-text field, this vocabulary is closed and must stay
closed: once a row is written under a typo'd or mis-cased era (``"Modern"``,
``"legacy"``), the frozen Arrow schema can never rename the value away, so
the bad label is uncorrectable and silently pollutes the stratum forever."""


class ArchivedClimateDay(Data):
    """A station climate-day summary as published in one archived CLI product.

    Parameters
    ----------
    station : str
        Registry CLI location code, never parsed from product text.
    climate_day : datetime.date
        The climate day covered by the product.
    tmax_f, tmin_f, tavg_f : int or None
        Whole degrees Fahrenheit as published. ``tavg_f`` is never computed:
        the product's own integer AVERAGE line is the stored datum.
    tmax_flag, tmin_flag, tavg_flag : str or None
        Sentinel kind when the paired value is absent; ``None`` when present.
    is_final : bool
        Derived from classifying the verbatim product text.
    correction_flag : bool
        Whole-text correction evidence.
    is_correction_bbb : bool
        Positional BBB-token correction verdict, stored separately from the
        broader free-text evidence. An independent constructor argument, not
        a property derived from ``wmo_bbb_token`` -- but cross-checked
        against it at construction time (`breezy.domain.wmo.is_correction_bbb_token`)
        so a hand-built or corrupted row can never round-trip a disagreement
        on this frozen schema.
    revision_seq : int
        Monotonic per ``(station, climate_day, is_final)``, starting at 1.
    issuing_office : str
        WFO from the WMO heading.
    wmo_transmission_sequence : str
        The transmission sequence from the WMO header.
    wmo_bbb_token : str or None
        WMO BBB token as parsed from the heading.
    issuance_time_ns : int
        UNIX nanoseconds. Becomes both ``ts_init`` and ``ts_event``.
    issuance_time_source : str
        How the issuance instant was recovered, e.g. ``"wmo_filename"`` or
        ``"issued_line"``.
    archive_retrieved_at_ns : int
        Real archive fetch instant. Never ``ts_init``.
    archive_source_url : str
        Redacted IEM archive URL.
    archive_job_version, parser_version, registry_version : str
        Batch job, parser and registry provenance.
    raw_sha256 : str
        Digest of the verbatim archived product text.
    station_year_yield : float
        Admission yield for the station-year this row came from.
    admission_era : str
        Era label used by later sample-selection analysis.
    schema_version : int
        schema_version is forensics only. It is NOT a compatibility mechanism.

    """

    def __init__(
        self,
        *,
        station: str,
        climate_day: dt.date,
        tmax_f: int | None,
        tmin_f: int | None,
        tavg_f: int | None,
        tmax_flag: str | None,
        tmin_flag: str | None,
        tavg_flag: str | None,
        is_final: bool,
        correction_flag: bool,
        is_correction_bbb: bool,
        revision_seq: int,
        issuing_office: str,
        wmo_transmission_sequence: str,
        wmo_bbb_token: str | None,
        issuance_time_ns: int,
        issuance_time_source: str,
        archive_retrieved_at_ns: int,
        archive_source_url: str,
        archive_job_version: str,
        parser_version: str,
        registry_version: str,
        raw_sha256: str,
        station_year_yield: float,
        admission_era: str,
        schema_version: int = ARCHIVED_CLIMATE_DAY_SCHEMA_VERSION,
    ) -> None:
        self.station = require_text(station, "station")
        self.climate_day = require_pure_date(climate_day, "climate_day")
        self.tmax_f = require_optional_int(tmax_f, "tmax_f")
        self.tmin_f = require_optional_int(tmin_f, "tmin_f")
        self.tavg_f = require_optional_int(tavg_f, "tavg_f")
        self.tmax_flag = _require_flag(tmax_flag, self.tmax_f, "tmax_f", "tmax_flag")
        self.tmin_flag = _require_flag(tmin_flag, self.tmin_f, "tmin_f", "tmin_flag")
        self.tavg_flag = _require_flag(tavg_flag, self.tavg_f, "tavg_f", "tavg_flag")
        self.is_final = require_bool(is_final, "is_final")
        self.correction_flag = require_bool(correction_flag, "correction_flag")
        self.is_correction_bbb = require_bool(is_correction_bbb, "is_correction_bbb")
        self.revision_seq = require_int(revision_seq, "revision_seq")
        self.issuing_office = require_text(issuing_office, "issuing_office")
        self.wmo_transmission_sequence = require_text(
            wmo_transmission_sequence,
            "wmo_transmission_sequence",
        )
        self.wmo_bbb_token = require_optional_text(wmo_bbb_token, "wmo_bbb_token")
        self.issuance_time_ns = require_int(issuance_time_ns, "issuance_time_ns")
        self.issuance_time_source = require_text(issuance_time_source, "issuance_time_source")
        self.archive_retrieved_at_ns = require_int(
            archive_retrieved_at_ns,
            "archive_retrieved_at_ns",
        )
        self.archive_source_url = require_text(archive_source_url, "archive_source_url")
        self.archive_job_version = require_text(archive_job_version, "archive_job_version")
        self.parser_version = require_text(parser_version, "parser_version")
        self.registry_version = require_text(registry_version, "registry_version")
        self.raw_sha256 = require_hex_digest(raw_sha256, "raw_sha256")
        self.station_year_yield = require_float(station_year_yield, "station_year_yield")
        self.admission_era = _require_admission_era(admission_era, "admission_era")
        self.schema_version = require_int(schema_version, "schema_version")

        if self.revision_seq < 1:
            raise ValueError(
                f"`revision_seq` is monotonic per (station, climate_day, is_final) "
                f"starting at 1, was {self.revision_seq}",
            )

        if self.tmax_f is not None and self.tmin_f is not None and self.tmin_f > self.tmax_f:
            raise ValueError(
                f"`tmin_f` ({self.tmin_f}) exceeds `tmax_f` ({self.tmax_f}) for "
                f"{self.station} {self.climate_day.isoformat()}",
            )

        if self.issuance_time_ns > self.archive_retrieved_at_ns:
            raise ValueError(
                f"`issuance_time_ns` ({self.issuance_time_ns}) is after "
                f"`archive_retrieved_at_ns` ({self.archive_retrieved_at_ns}) for "
                f"{self.station} {self.climate_day.isoformat()}",
            )

        expected_is_correction_bbb = is_correction_bbb_token(self.wmo_bbb_token)
        if self.is_correction_bbb is not expected_is_correction_bbb:
            raise ValueError(
                f"`is_correction_bbb` ({self.is_correction_bbb}) disagrees with "
                f"`wmo_bbb_token` ({self.wmo_bbb_token!r}), which implies "
                f"{expected_is_correction_bbb}, for {self.station} "
                f"{self.climate_day.isoformat()}; this is an independent constructor "
                "argument on this frozen record, not a derived property, precisely "
                "so a hand-built or corrupted row can be cross-checked instead of "
                "silently round-tripping an inconsistency the Arrow schema can never "
                "later correct",
            )

        self._ts_event = self.issuance_time_ns
        self._ts_init = self.issuance_time_ns

    @property
    def ts_event(self) -> int:
        """UNIX nanoseconds of the archived public issuance instant."""
        return self._ts_event

    @property
    def ts_init(self) -> int:
        """UNIX nanoseconds used for archived replay ordering."""
        return self._ts_init

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"station={self.station!r}, "
            f"climate_day={self.climate_day.isoformat()}, "
            f"tmax_f={self.tmax_f}, tmin_f={self.tmin_f}, tavg_f={self.tavg_f}, "
            f"is_final={self.is_final}, revision_seq={self.revision_seq}, "
            f"raw_sha256={self.raw_sha256}, "
            f"ts_event={self._ts_event}, ts_init={self._ts_init})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the record as Arrow-native values, keyed in `schema()` order."""
        return {
            "station": self.station,
            "climate_day": self.climate_day,
            "tmax_f": self.tmax_f,
            "tmin_f": self.tmin_f,
            "tavg_f": self.tavg_f,
            "tmax_flag": self.tmax_flag,
            "tmin_flag": self.tmin_flag,
            "tavg_flag": self.tavg_flag,
            "is_final": self.is_final,
            "correction_flag": self.correction_flag,
            "is_correction_bbb": self.is_correction_bbb,
            "revision_seq": self.revision_seq,
            "issuing_office": self.issuing_office,
            "wmo_transmission_sequence": self.wmo_transmission_sequence,
            "wmo_bbb_token": self.wmo_bbb_token,
            "issuance_time_ns": self.issuance_time_ns,
            "issuance_time_source": self.issuance_time_source,
            "archive_retrieved_at_ns": self.archive_retrieved_at_ns,
            "archive_source_url": self.archive_source_url,
            "archive_job_version": self.archive_job_version,
            "parser_version": self.parser_version,
            "registry_version": self.registry_version,
            "raw_sha256": self.raw_sha256,
            "station_year_yield": self.station_year_yield,
            "admission_era": self.admission_era,
            "schema_version": self.schema_version,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> ArchivedClimateDay:
        """Rebuild a record from `to_dict` output.

        Every key is read by direct subscript: a missing column raises `KeyError`
        here rather than silently adopting a default.
        """
        if values["ts_event"] != values["issuance_time_ns"]:
            raise ValueError(
                f"`ts_event` ({values['ts_event']}) must equal `issuance_time_ns` "
                f"({values['issuance_time_ns']})",
            )

        if values["ts_init"] != values["issuance_time_ns"]:
            raise ValueError(
                f"`ts_init` ({values['ts_init']}) must equal `issuance_time_ns` "
                f"({values['issuance_time_ns']})",
            )

        return cls(
            station=values["station"],
            climate_day=values["climate_day"],
            tmax_f=values["tmax_f"],
            tmin_f=values["tmin_f"],
            tavg_f=values["tavg_f"],
            tmax_flag=values["tmax_flag"],
            tmin_flag=values["tmin_flag"],
            tavg_flag=values["tavg_flag"],
            is_final=values["is_final"],
            correction_flag=values["correction_flag"],
            is_correction_bbb=values["is_correction_bbb"],
            revision_seq=values["revision_seq"],
            issuing_office=values["issuing_office"],
            wmo_transmission_sequence=values["wmo_transmission_sequence"],
            wmo_bbb_token=values["wmo_bbb_token"],
            issuance_time_ns=values["issuance_time_ns"],
            issuance_time_source=values["issuance_time_source"],
            archive_retrieved_at_ns=values["archive_retrieved_at_ns"],
            archive_source_url=values["archive_source_url"],
            archive_job_version=values["archive_job_version"],
            parser_version=values["parser_version"],
            registry_version=values["registry_version"],
            raw_sha256=values["raw_sha256"],
            station_year_yield=values["station_year_yield"],
            admission_era=values["admission_era"],
            schema_version=values["schema_version"],
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        """Return the explicit Arrow schema for this record type."""
        return pa.schema(
            [
                pa.field("station", pa.string(), nullable=False),
                pa.field("climate_day", pa.date32(), nullable=False),
                pa.field("tmax_f", pa.int64(), nullable=True),
                pa.field("tmin_f", pa.int64(), nullable=True),
                pa.field("tavg_f", pa.int64(), nullable=True),
                pa.field("tmax_flag", pa.string(), nullable=True),
                pa.field("tmin_flag", pa.string(), nullable=True),
                pa.field("tavg_flag", pa.string(), nullable=True),
                pa.field("is_final", pa.bool_(), nullable=False),
                pa.field("correction_flag", pa.bool_(), nullable=False),
                pa.field("is_correction_bbb", pa.bool_(), nullable=False),
                pa.field("revision_seq", pa.int64(), nullable=False),
                pa.field("issuing_office", pa.string(), nullable=False),
                pa.field("wmo_transmission_sequence", pa.string(), nullable=False),
                pa.field("wmo_bbb_token", pa.string(), nullable=True),
                pa.field("issuance_time_ns", pa.int64(), nullable=False),
                pa.field("issuance_time_source", pa.string(), nullable=False),
                pa.field("archive_retrieved_at_ns", pa.int64(), nullable=False),
                pa.field("archive_source_url", pa.string(), nullable=False),
                pa.field("archive_job_version", pa.string(), nullable=False),
                pa.field("parser_version", pa.string(), nullable=False),
                pa.field("registry_version", pa.string(), nullable=False),
                pa.field("raw_sha256", pa.string(), nullable=False),
                pa.field("station_year_yield", pa.float64(), nullable=False),
                pa.field("admission_era", pa.string(), nullable=False),
                pa.field("schema_version", pa.int64(), nullable=False),
                pa.field("ts_event", pa.int64(), nullable=False),
                pa.field("ts_init", pa.int64(), nullable=False),
            ],
        )


def _require_flag(
    raw_flag: Any,
    value: int | None,
    value_name: str,
    flag_name: str,
) -> str | None:
    """Enforce the value/sentinel-flag exclusivity in both directions."""
    flag: str | None = require_optional_text(raw_flag, flag_name)

    if flag is not None and flag not in MISSING_VALUE_FLAGS:
        raise ValueError(
            f"`{flag_name}` must be one of {MISSING_VALUE_FLAGS}, was {flag!r}",
        )

    if value is None and flag is None:
        raise ValueError(
            f"`{value_name}` is missing, so `{flag_name}` must name the sentinel kind "
            f"(one of {MISSING_VALUE_FLAGS})",
        )

    if value is not None and flag is not None:
        raise ValueError(
            f"`{value_name}` is present ({value}), so `{flag_name}` must be `None`, was {flag!r}",
        )

    return flag


def _require_admission_era(value: Any, name: str) -> str:
    """Enforce the closed sample-selection-era vocabulary.

    Matches `_require_flag`'s allowlist style above: a small, closed set of
    legal values enforced at construction, not left to downstream analysis
    to discover a stray value was never valid.
    """
    era = require_text(value, name)

    if era not in _ADMISSION_ERAS:
        raise ValueError(
            f"`{name}` must be one of {sorted(_ADMISSION_ERAS)}, was {era!r}",
        )

    return era


# Registered exactly once, at module scope.
register_arrow(
    data_cls=ArchivedClimateDay,
    schema=ArchivedClimateDay.schema(),
    encoder=make_strict_encoder(ArchivedClimateDay.schema()),
    decoder=make_strict_decoder(ArchivedClimateDay, ArchivedClimateDay.schema()),
)

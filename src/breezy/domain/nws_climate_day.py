"""`NwsClimateDay` -- one normalized NWS Daily Climate Report observation.

Pattern
-------
A hand-written `nautilus_trader.core.data.Data` subclass with explicit
``ts_event``/``ts_init`` properties, ``to_dict``/``from_dict``, a ``schema()``
classmethod, and **exactly one** ``register_arrow`` call at module scope. This is
the in-tree pattern from ``adapters/betfair/data_types.py``.

``@customdataclass`` is deliberately not used. Its injected ``from_arrow`` routes
through ``from_dict``, which lets a column that vanished from a fragment arrive as
a dataclass default -- undetectable drift on the single most safety-critical value
Breezy stores. Since the decoder has to be overridden anyway, hand-writing the
class is fewer moving parts, not more.

``register_arrow`` is called once. A second call for the same class wins in the
serializer's ``_SCHEMAS`` registry while leaving ``cls._schema`` untouched, which
permanently diverges what ``to_arrow`` uses from what the catalog writes.

Timestamps
----------
``ts_init`` is ``retrieved_at_ns`` -- the instant *Breezy* received the product --
and is not a constructor parameter, so it cannot be re-stamped from a clock.
Replay order then equals real arrival order, because ``ts_init`` is the key
Nautilus sorts the merged stream on and advances the backtest clock from;
``ts_event`` is never read in the replay path.

``ts_event`` is the semantic instant and is supplied by the caller, because
deriving it needs the station registry. It means a **different thing per issuance
class**, and :func:`breezy.ingest.records.build_climate_day` is its only deriver:

* **finals** -- the end of the climate day: 24:00 on the summary date in the
  site's local **standard** time (never UTC, never the DST-adjusted clock).
  Computed from the summary date and the registry's fixed offset, so it is
  independent of when the product was fetched.
* **preliminaries** -- the issuance instant, ``issuance_time_ns``, copied from
  the archived product.

``ts_event <= ts_init`` is asserted **for finals only**, in ``build_climate_day``.
The scoping is not headroom granted to preliminaries -- it is the reverse. A
preliminary's ``ts_event`` *is* its issuance instant, and
:class:`~breezy.domain.nws_raw_product.NwsRawProduct` already rejects
``issuance_time_ns > retrieved_at_ns`` at construction, so for a preliminary the
ordering holds by construction and asserting it could never fail. A final is the
only record whose ``ts_event`` is derived independently of the fetch, so it is the
only one where the comparison carries information: ``ts_event > ts_init`` means
the climate day had not ended when the bytes arrived, which means the product is
**not** a final and was misclassified. Finals are the class that needs the check;
preliminaries are exempt because the check is vacuous for them, not because they
are allowed to violate it.

This class enforces no ordering check of its own, for either issuance class. The
check is an ingestion-time classification guard, not a field invariant: it belongs
where the issuance class is decided and the failure can be named, and this
constructor is also the catalog decode path (``from_dict``), so a rejection here
would make an already-written row unreadable rather than surfacing at ingestion.

Pinned by ``test_final_ts_event_is_the_climate_day_end_in_local_standard_time``,
``test_preliminary_ts_event_is_the_issuance_instant`` and
``test_a_final_may_not_predate_the_climate_day_it_reports`` in
``tests/unit/test_ingest_records.py``, and by the ordering tests in
``tests/unit/test_domain_nws_climate_day.py``.

Revisions
---------
A correction is a **new record with a strictly later** ``ts_init``, never a
rewrite: ``ParquetDataCatalog._write_chunk`` silently skips a write whose computed
filename already exists, and ``delete_data_range`` no-ops for identifier-less
custom types.

Readers therefore select max ``(is_final, ts_init, revision_seq)`` per
``(station, climate_day)``. ``is_final`` leads so that a backfilled preliminary
can never shadow a final -- a final outranks a preliminary at any ``ts_init``.
``ts_init`` then orders *within* a finality class: among finals the later arrival
wins, which is the correction path, and among preliminaries likewise.
``revision_seq`` breaks a remaining tie. Selection guarantees a final is never
shadowed, **not that one exists**, so settlement callers must still check
``is_final``. That rule and the ``as_of_ts_init`` bound live in
:mod:`breezy.domain.selection`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.serialization.arrow.serializer import register_arrow

from breezy.domain.strict_arrow import make_strict_decoder, make_strict_encoder
from breezy.domain.validation import (
    require_bool,
    require_hex_digest,
    require_int,
    require_optional_int,
    require_optional_text,
    require_pure_date,
    require_text,
)

CLIMATE_DAY_SCHEMA_VERSION: Final[int] = 2

MISSING_VALUE_FLAGS: Final[tuple[str, ...]] = ("M", "T", "MS", "MB", "UNREADABLE")
"""NWS sentinel kinds: missing, trace, missing-at-time, missing-at-midnight --
plus "UNREADABLE", which is OURS, not NWS's: the parser's row was absent or
its token could not be read for a non-settlement-bearing field (tmin/tavg).
See `breezy.normalize.units.SentinelFlag` for why it is a distinct kind
rather than reusing one of the four NWS sentinels.

A missing value is a genuinely null Arrow column *plus* the sentinel kind in the
paired ``*_flag`` column. There is no bitmask, and no field is annotated as a
number while carrying ``None``.
"""


class NwsClimateDay(Data):
    """A single station's climate-day summary as published in one CLI product.

    Parameters
    ----------
    station : str
        CLI location code from the registry (e.g. ``"NYC"``), never parsed from
        product text.
    climate_day : datetime.date
        The climate day covered, midnight-to-midnight local standard time.
    tmax_f, tmin_f : int or None
        Observed extremes in whole degrees Fahrenheit; ``None`` iff the paired
        flag names a sentinel.
    tavg_f : int or None
        The product's own published AVERAGE line, in whole degrees Fahrenheit,
        exactly as NWS printed it. Never computed: deriving ``(tmax + tmin) / 2``
        here would invent a settlement number, which is forbidden in the same
        terms as imputing a sentinel. The venue settles on the observed high, low
        and average, so the published integer *is* the settlement datum.
        ``None`` iff ``tavg_flag`` names a sentinel.
    tmax_flag, tmin_flag, tavg_flag : str or None
        Sentinel kind from :data:`MISSING_VALUE_FLAGS`; ``None`` iff the paired
        value is present. Every temperature field carries one, because a missing
        AVERAGE and a trace AVERAGE are different facts and collapsing both to
        ``None`` destroys a distinction the settlement path depends on.
    is_final : bool
        ``True`` only for the ~02:27-local final issuance. Preliminaries are
        never settlement-grade.
    correction_flag : bool
        Correction evidence (``CCA``/``CCB``/``CORRECTED``/``CORRECTION``) was
        found in the raw text.
    revision_seq : int
        Monotonic per ``(station, climate_day)``, starting at 1.
    is_superseded : bool
        Known-superseded at write time. Selection does not consult it -- it ranks
        on ``(is_final, ts_init, revision_seq)`` -- so this flag is only a record
        of what was known when the record was written, since prior records are
        never rewritten.
    issuing_office : str
        WFO that issued the product (e.g. ``"KOKX"``). Not sufficient on its own
        to bind a product to a station -- one office issues for several cities.
    issuance_time_ns, retrieved_at_ns : int
        UNIX nanoseconds. ``retrieved_at_ns`` becomes ``ts_init``.
    parser_version, registry_version : str
        Provenance of the code and configuration that produced this record.
    raw_sha256 : str
        Digest of the verbatim product text; joins this record to its
        :class:`~breezy.domain.nws_raw_product.NwsRawProduct` archive row.
    source_channel : str
        Feed the product came from.
    schema_version : int
        Revision of this record layout.
    ts_event : int
        Semantic instant in UNIX nanoseconds: the climate-day end in local
        standard time for a final, the issuance instant for a preliminary. No
        ordering against ``ts_init`` is checked here (see the module docstring).

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
        revision_seq: int,
        is_superseded: bool,
        issuing_office: str,
        issuance_time_ns: int,
        retrieved_at_ns: int,
        parser_version: str,
        registry_version: str,
        raw_sha256: str,
        source_channel: str,
        schema_version: int = CLIMATE_DAY_SCHEMA_VERSION,
        ts_event: int,
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
        self.revision_seq = require_int(revision_seq, "revision_seq")
        self.is_superseded = require_bool(is_superseded, "is_superseded")
        self.issuing_office = require_text(issuing_office, "issuing_office")
        self.issuance_time_ns = require_int(issuance_time_ns, "issuance_time_ns")
        self.retrieved_at_ns = require_int(retrieved_at_ns, "retrieved_at_ns")
        self.parser_version = require_text(parser_version, "parser_version")
        self.registry_version = require_text(registry_version, "registry_version")
        self.raw_sha256 = require_hex_digest(raw_sha256, "raw_sha256")
        self.source_channel = require_text(source_channel, "source_channel")
        self.schema_version = require_int(schema_version, "schema_version")

        if self.revision_seq < 1:
            raise ValueError(
                f"`revision_seq` is monotonic per (station, climate_day) starting at 1, "
                f"was {self.revision_seq}",
            )

        if self.tmax_f is not None and self.tmin_f is not None and self.tmin_f > self.tmax_f:
            raise ValueError(
                f"`tmin_f` ({self.tmin_f}) exceeds `tmax_f` ({self.tmax_f}) for "
                f"{self.station} {self.climate_day.isoformat()}",
            )

        self._ts_event = require_int(ts_event, "ts_event")
        # `ts_init` is stamped once, at retrieval, and propagated -- never re-stamped
        # from a clock, and never a constructor parameter that could disagree.
        self._ts_init = self.retrieved_at_ns

    @property
    def ts_event(self) -> int:
        """UNIX nanoseconds of the semantic instant this record describes."""
        return self._ts_event

    @property
    def ts_init(self) -> int:
        """UNIX nanoseconds when Breezy received the product (`retrieved_at_ns`)."""
        return self._ts_init

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"station={self.station!r}, "
            f"climate_day={self.climate_day.isoformat()}, "
            f"tmax_f={self.tmax_f}, tmin_f={self.tmin_f}, tavg_f={self.tavg_f}, "
            f"tmax_flag={self.tmax_flag!r}, tmin_flag={self.tmin_flag!r}, "
            f"tavg_flag={self.tavg_flag!r}, "
            f"is_final={self.is_final}, correction_flag={self.correction_flag}, "
            f"revision_seq={self.revision_seq}, is_superseded={self.is_superseded}, "
            f"issuing_office={self.issuing_office!r}, "
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
            "revision_seq": self.revision_seq,
            "is_superseded": self.is_superseded,
            "issuing_office": self.issuing_office,
            "issuance_time_ns": self.issuance_time_ns,
            "retrieved_at_ns": self.retrieved_at_ns,
            "parser_version": self.parser_version,
            "registry_version": self.registry_version,
            "raw_sha256": self.raw_sha256,
            "source_channel": self.source_channel,
            "schema_version": self.schema_version,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> NwsClimateDay:
        """Rebuild a record from `to_dict` output.

        Every key is read by direct subscript: a missing column raises `KeyError`
        here rather than silently adopting a default.
        """
        if values["ts_init"] != values["retrieved_at_ns"]:
            raise ValueError(
                f"`ts_init` ({values['ts_init']}) must equal `retrieved_at_ns` "
                f"({values['retrieved_at_ns']}); ts_init is stamped once at retrieval",
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
            revision_seq=values["revision_seq"],
            is_superseded=values["is_superseded"],
            issuing_office=values["issuing_office"],
            issuance_time_ns=values["issuance_time_ns"],
            retrieved_at_ns=values["retrieved_at_ns"],
            parser_version=values["parser_version"],
            registry_version=values["registry_version"],
            raw_sha256=values["raw_sha256"],
            source_channel=values["source_channel"],
            schema_version=values["schema_version"],
            ts_event=values["ts_event"],
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
                pa.field("revision_seq", pa.int64(), nullable=False),
                pa.field("is_superseded", pa.bool_(), nullable=False),
                pa.field("issuing_office", pa.string(), nullable=False),
                pa.field("issuance_time_ns", pa.int64(), nullable=False),
                pa.field("retrieved_at_ns", pa.int64(), nullable=False),
                pa.field("parser_version", pa.string(), nullable=False),
                pa.field("registry_version", pa.string(), nullable=False),
                pa.field("raw_sha256", pa.string(), nullable=False),
                pa.field("source_channel", pa.string(), nullable=False),
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


# Registered exactly once, at module scope.
register_arrow(
    data_cls=NwsClimateDay,
    schema=NwsClimateDay.schema(),
    encoder=make_strict_encoder(NwsClimateDay.schema()),
    decoder=make_strict_decoder(NwsClimateDay, NwsClimateDay.schema()),
)

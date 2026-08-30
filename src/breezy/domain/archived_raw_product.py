"""`ArchivedRawProduct` -- verbatim CLI product text from the IEM archive.

The archive job stores raw text in the catalog so parser changes can be audited
against the exact bytes that produced each archived climate-day row. The record
has no ``product_uuid``: IEM does not assign one, and inventing an identifier
would be false provenance. Identity is ``(station, issuance_time_ns,
raw_sha256)``.

This is a hand-written Nautilus ``Data`` subclass with explicit
``ts_event``/``ts_init`` properties, ``to_dict``/``from_dict``, a ``schema()``
classmethod, and exactly one module-scope ``register_arrow`` call. Generated
dataclass codecs are avoided because a missing Arrow column must raise, not
default, and a second registration can make the serializer registry disagree
with the class schema.

For archived rows, both timestamps are the WMO issuance instant. The real archive
fetch instant is stored separately as ``archive_retrieved_at_ns`` and must not
precede issuance.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Final

import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.serialization.arrow.serializer import register_arrow

from breezy.domain.strict_arrow import make_strict_decoder, make_strict_encoder
from breezy.domain.validation import (
    require_hex_digest,
    require_int,
    require_optional_pure_date,
    require_optional_text,
    require_text,
)

ARCHIVED_RAW_PRODUCT_SCHEMA_VERSION: Final[int] = 1


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArchivedRawProduct(Data):
    """One archived NWS text product, stored verbatim with archive provenance.

    Parameters
    ----------
    station : str
        Registry CLI location code the archive request targeted.
    product_code : str
        Product family, e.g. ``"CLI"``.
    issuing_office : str
        WFO from the WMO heading.
    wmo_collective_id : str
        WMO collective identifier, e.g. ``"CDUS41"``.
    awips_pil : str or None
        AWIPS PIL from the product text.
    wmo_bbb_token : str or None
        WMO BBB token as parsed from the heading.
    issuance_time_ns : int
        UNIX nanoseconds. Becomes both ``ts_init`` and ``ts_event``.
    issuance_time_source : str
        How the issuance instant was recovered.
    archive_retrieved_at_ns : int
        Real archive fetch instant. Never ``ts_init``.
    climate_day : datetime.date or None
        Summary date when parseable.
    raw_text : str
        Product text, verbatim.
    raw_sha256 : str
        Digest of ``raw_text``. Recomputed and checked at construction.
    archive_source_url, archive_job_version, registry_version : str
        Archive provenance.
    schema_version : int
        schema_version is forensics only. It is NOT a compatibility mechanism.

    """

    def __init__(
        self,
        *,
        station: str,
        product_code: str,
        issuing_office: str,
        wmo_collective_id: str,
        awips_pil: str | None,
        wmo_bbb_token: str | None,
        issuance_time_ns: int,
        issuance_time_source: str,
        archive_retrieved_at_ns: int,
        climate_day: dt.date | None,
        raw_text: str,
        raw_sha256: str,
        archive_source_url: str,
        archive_job_version: str,
        registry_version: str,
        schema_version: int = ARCHIVED_RAW_PRODUCT_SCHEMA_VERSION,
    ) -> None:
        self.station = require_text(station, "station")
        self.product_code = require_text(product_code, "product_code")
        self.issuing_office = require_text(issuing_office, "issuing_office")
        self.wmo_collective_id = require_text(wmo_collective_id, "wmo_collective_id")
        self.awips_pil = require_optional_text(awips_pil, "awips_pil")
        self.wmo_bbb_token = require_optional_text(wmo_bbb_token, "wmo_bbb_token")
        self.issuance_time_ns = require_int(issuance_time_ns, "issuance_time_ns")
        self.issuance_time_source = require_text(issuance_time_source, "issuance_time_source")
        self.archive_retrieved_at_ns = require_int(
            archive_retrieved_at_ns,
            "archive_retrieved_at_ns",
        )
        self.climate_day = require_optional_pure_date(climate_day, "climate_day")
        self.raw_text = require_text(raw_text, "raw_text")
        self.raw_sha256 = require_hex_digest(raw_sha256, "raw_sha256")
        self.archive_source_url = require_text(archive_source_url, "archive_source_url")
        self.archive_job_version = require_text(archive_job_version, "archive_job_version")
        self.registry_version = require_text(registry_version, "registry_version")
        self.schema_version = require_int(schema_version, "schema_version")

        if not self.verify_digest():
            raise ValueError(
                f"`raw_sha256` does not match `raw_text` for {self.station} "
                f"issuance {self.issuance_time_ns}: declared {self.raw_sha256}, "
                f"computed {_sha256_text(self.raw_text)}",
            )

        if self.issuance_time_ns > self.archive_retrieved_at_ns:
            raise ValueError(
                f"`issuance_time_ns` ({self.issuance_time_ns}) is after "
                f"`archive_retrieved_at_ns` ({self.archive_retrieved_at_ns}) for "
                f"{self.station}: archive bytes cannot be retrieved before issuance",
            )

        self._ts_event = self.issuance_time_ns
        self._ts_init = self.issuance_time_ns

    @property
    def ts_event(self) -> int:
        """UNIX nanoseconds the archived product was issued."""
        return self._ts_event

    @property
    def ts_init(self) -> int:
        """UNIX nanoseconds used for archived replay ordering."""
        return self._ts_init

    def verify_digest(self) -> bool:
        """Return whether `raw_sha256` still matches `sha256(raw_text)`."""
        return _sha256_text(self.raw_text) == self.raw_sha256

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"station={self.station!r}, product_code={self.product_code!r}, "
            f"issuing_office={self.issuing_office!r}, climate_day={self.climate_day}, "
            f"raw_len={len(self.raw_text)}, raw_sha256={self.raw_sha256}, "
            f"ts_event={self._ts_event}, ts_init={self._ts_init})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the record as Arrow-native values, keyed in `schema()` order."""
        return {
            "station": self.station,
            "product_code": self.product_code,
            "issuing_office": self.issuing_office,
            "wmo_collective_id": self.wmo_collective_id,
            "awips_pil": self.awips_pil,
            "wmo_bbb_token": self.wmo_bbb_token,
            "issuance_time_ns": self.issuance_time_ns,
            "issuance_time_source": self.issuance_time_source,
            "archive_retrieved_at_ns": self.archive_retrieved_at_ns,
            "climate_day": self.climate_day,
            "raw_text": self.raw_text,
            "raw_sha256": self.raw_sha256,
            "archive_source_url": self.archive_source_url,
            "archive_job_version": self.archive_job_version,
            "registry_version": self.registry_version,
            "schema_version": self.schema_version,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> ArchivedRawProduct:
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
            product_code=values["product_code"],
            issuing_office=values["issuing_office"],
            wmo_collective_id=values["wmo_collective_id"],
            awips_pil=values["awips_pil"],
            wmo_bbb_token=values["wmo_bbb_token"],
            issuance_time_ns=values["issuance_time_ns"],
            issuance_time_source=values["issuance_time_source"],
            archive_retrieved_at_ns=values["archive_retrieved_at_ns"],
            climate_day=values["climate_day"],
            raw_text=values["raw_text"],
            raw_sha256=values["raw_sha256"],
            archive_source_url=values["archive_source_url"],
            archive_job_version=values["archive_job_version"],
            registry_version=values["registry_version"],
            schema_version=values["schema_version"],
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        """Return the explicit Arrow schema for this record type."""
        return pa.schema(
            [
                pa.field("station", pa.string(), nullable=False),
                pa.field("product_code", pa.string(), nullable=False),
                pa.field("issuing_office", pa.string(), nullable=False),
                pa.field("wmo_collective_id", pa.string(), nullable=False),
                pa.field("awips_pil", pa.string(), nullable=True),
                pa.field("wmo_bbb_token", pa.string(), nullable=True),
                pa.field("issuance_time_ns", pa.int64(), nullable=False),
                pa.field("issuance_time_source", pa.string(), nullable=False),
                pa.field("archive_retrieved_at_ns", pa.int64(), nullable=False),
                pa.field("climate_day", pa.date32(), nullable=True),
                pa.field("raw_text", pa.string(), nullable=False),
                pa.field("raw_sha256", pa.string(), nullable=False),
                pa.field("archive_source_url", pa.string(), nullable=False),
                pa.field("archive_job_version", pa.string(), nullable=False),
                pa.field("registry_version", pa.string(), nullable=False),
                pa.field("schema_version", pa.int64(), nullable=False),
                pa.field("ts_event", pa.int64(), nullable=False),
                pa.field("ts_init", pa.int64(), nullable=False),
            ],
        )


# Registered exactly once, at module scope.
register_arrow(
    data_cls=ArchivedRawProduct,
    schema=ArchivedRawProduct.schema(),
    encoder=make_strict_encoder(ArchivedRawProduct.schema()),
    decoder=make_strict_decoder(ArchivedRawProduct, ArchivedRawProduct.schema()),
)

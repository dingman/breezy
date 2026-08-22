"""`NwsRawProduct` -- the verbatim, immutable archive of one fetched NWS product.

api.weather.gov offers no archive guarantee: a product that vanishes from the live
API is gone, and the Iowa Environmental Mesonet AFOS archive is only a practical
fallback. The raw text therefore lives **in the catalog**, not merely on the
filesystem -- verifying a settlement digest against a filesystem side-channel that
does not exist during replay would break live/backtest parity at the single most
safety-critical predicate.

The record carries the provenance set plus the verbatim ``raw_text`` and two
digests:

* ``raw_sha256`` -- over the product text itself. Recomputed and checked at
  construction, and re-checkable at any later moment via :meth:`verify_digest`.
  Dedupe keys on ``(product_code, station, climate_day, raw_sha256)``, never on
  the product UUID, because every re-issue receives a fresh UUID.
* ``response_sha256`` -- over the whole HTTP response body, so a transport-level
  change is distinguishable from a product-level one.

Timestamps: ``ts_event`` is the issuance instant, ``ts_init`` the retrieval
instant. Neither is a constructor parameter -- both derive from the provenance
fields, so ``ts_event <= ts_init`` holds by construction for this type.

No ``parser_version`` field: this record is captured *before* parsing, and
claiming a parser produced it would be false provenance. The parsed values and
their parser version live on
:class:`~breezy.domain.nws_climate_day.NwsClimateDay`, joined by ``raw_sha256``.

The pattern (hand-written `Data` subclass, explicit schema, exactly one
``register_arrow``) and the reasons for it are documented in
:mod:`breezy.domain.nws_climate_day`.
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

RAW_PRODUCT_SCHEMA_VERSION: Final[int] = 1


def sha256_text(text: str) -> str:
    """Return the lowercase hex SHA-256 of `text` encoded as UTF-8.

    The single definition of "the digest of a product", so the ingest path, the
    record constructor and any later verification cannot disagree about encoding.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class NwsRawProduct(Data):
    """One fetched NWS text product, stored verbatim with its provenance.

    Parameters
    ----------
    station : str
        CLI location code from the registry (e.g. ``"NYC"``) -- the location that
        was polled, never a value interpolated from parsed text.
    product_uuid : str
        Identifier assigned by api.weather.gov. Not a dedupe key: every re-issue
        of identical text receives a new one.
    product_code : str
        e.g. ``"CLI"``.
    issuing_office : str
        e.g. ``"KOKX"``. One office issues for several cities, so this alone
        cannot bind a product to a station.
    wmo_collective_id : str
        e.g. ``"CDUS41"``.
    awips_pil : str or None
        AWIPS PIL from line 3 of the product text (e.g. ``"CLINYC"``). Nullable:
        a malformed product may not carry a recognisable one.
    wmo_bbb_token : str or None
        WMO BBB token from line 2 (``"CCA"``, ``"CCB"``, ...) when present. The
        ``/products/{id}`` endpoint does not expose this field, so it is parsed
        from the raw text and is frequently absent.
    issuance_time_ns, retrieved_at_ns : int
        UNIX nanoseconds. These become ``ts_event`` and ``ts_init``.
    climate_day : datetime.date or None
        Summary date extracted from the headline once known. Nullable, because
        capture precedes parsing.
    raw_text : str
        The product text, verbatim and immutable.
    raw_sha256 : str
        ``sha256(raw_text)``; verified against `raw_text` at construction.
    response_sha256 : str
        Digest of the full HTTP response body.
    response_etag, response_last_modified : str or None
        HTTP caching headers as received, when present.
    source_channel : str
        Feed the product came from.
    registry_version : str
        Version of the station registry that selected this poll target.
    schema_version : int
        Revision of this record layout.

    """

    def __init__(
        self,
        *,
        station: str,
        product_uuid: str,
        product_code: str,
        issuing_office: str,
        wmo_collective_id: str,
        awips_pil: str | None,
        wmo_bbb_token: str | None,
        issuance_time_ns: int,
        retrieved_at_ns: int,
        climate_day: dt.date | None,
        raw_text: str,
        raw_sha256: str,
        response_sha256: str,
        response_etag: str | None,
        response_last_modified: str | None,
        source_channel: str,
        registry_version: str,
        schema_version: int = RAW_PRODUCT_SCHEMA_VERSION,
    ) -> None:
        self.station = require_text(station, "station")
        self.product_uuid = require_text(product_uuid, "product_uuid")
        self.product_code = require_text(product_code, "product_code")
        self.issuing_office = require_text(issuing_office, "issuing_office")
        self.wmo_collective_id = require_text(wmo_collective_id, "wmo_collective_id")
        self.awips_pil = require_optional_text(awips_pil, "awips_pil")
        self.wmo_bbb_token = require_optional_text(wmo_bbb_token, "wmo_bbb_token")
        self.issuance_time_ns = require_int(issuance_time_ns, "issuance_time_ns")
        self.retrieved_at_ns = require_int(retrieved_at_ns, "retrieved_at_ns")
        self.climate_day = require_optional_pure_date(climate_day, "climate_day")
        self.raw_text = require_text(raw_text, "raw_text")
        self.raw_sha256 = require_hex_digest(raw_sha256, "raw_sha256")
        self.response_sha256 = require_hex_digest(response_sha256, "response_sha256")
        self.response_etag = require_optional_text(response_etag, "response_etag")
        self.response_last_modified = require_optional_text(
            response_last_modified,
            "response_last_modified",
        )
        self.source_channel = require_text(source_channel, "source_channel")
        self.registry_version = require_text(registry_version, "registry_version")
        self.schema_version = require_int(schema_version, "schema_version")

        if not self.verify_digest():
            raise ValueError(
                f"`raw_sha256` does not match `raw_text` for {self.station} "
                f"product {self.product_uuid}: declared {self.raw_sha256}, "
                f"computed {sha256_text(self.raw_text)}",
            )

        self._ts_event = self.issuance_time_ns
        self._ts_init = self.retrieved_at_ns

    @property
    def ts_event(self) -> int:
        """UNIX nanoseconds the product was issued (`issuance_time_ns`)."""
        return self._ts_event

    @property
    def ts_init(self) -> int:
        """UNIX nanoseconds Breezy received the product (`retrieved_at_ns`)."""
        return self._ts_init

    def verify_digest(self) -> bool:
        """Return whether `raw_sha256` still matches `sha256(raw_text)`.

        Call this before any settlement use of the stored text -- a stored digest
        alone is circular; only recomputation detects mutation in transit or at
        rest.
        """
        return sha256_text(self.raw_text) == self.raw_sha256

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"station={self.station!r}, "
            f"product_uuid={self.product_uuid!r}, "
            f"product_code={self.product_code!r}, "
            f"issuing_office={self.issuing_office!r}, "
            f"wmo_collective_id={self.wmo_collective_id!r}, "
            f"awips_pil={self.awips_pil!r}, "
            f"wmo_bbb_token={self.wmo_bbb_token!r}, "
            f"climate_day={self.climate_day}, "
            f"raw_len={len(self.raw_text)}, "
            f"raw_sha256={self.raw_sha256}, "
            f"response_sha256={self.response_sha256}, "
            f"ts_event={self._ts_event}, ts_init={self._ts_init})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the record as Arrow-native values, keyed in `schema()` order."""
        return {
            "station": self.station,
            "product_uuid": self.product_uuid,
            "product_code": self.product_code,
            "issuing_office": self.issuing_office,
            "wmo_collective_id": self.wmo_collective_id,
            "awips_pil": self.awips_pil,
            "wmo_bbb_token": self.wmo_bbb_token,
            "issuance_time_ns": self.issuance_time_ns,
            "retrieved_at_ns": self.retrieved_at_ns,
            "climate_day": self.climate_day,
            "raw_text": self.raw_text,
            "raw_sha256": self.raw_sha256,
            "response_sha256": self.response_sha256,
            "response_etag": self.response_etag,
            "response_last_modified": self.response_last_modified,
            "source_channel": self.source_channel,
            "registry_version": self.registry_version,
            "schema_version": self.schema_version,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> NwsRawProduct:
        """Rebuild a record from `to_dict` output.

        Every key is read by direct subscript: a missing column raises `KeyError`
        here rather than silently adopting a default.
        """
        if values["ts_event"] != values["issuance_time_ns"]:
            raise ValueError(
                f"`ts_event` ({values['ts_event']}) must equal `issuance_time_ns` "
                f"({values['issuance_time_ns']})",
            )

        if values["ts_init"] != values["retrieved_at_ns"]:
            raise ValueError(
                f"`ts_init` ({values['ts_init']}) must equal `retrieved_at_ns` "
                f"({values['retrieved_at_ns']})",
            )

        return cls(
            station=values["station"],
            product_uuid=values["product_uuid"],
            product_code=values["product_code"],
            issuing_office=values["issuing_office"],
            wmo_collective_id=values["wmo_collective_id"],
            awips_pil=values["awips_pil"],
            wmo_bbb_token=values["wmo_bbb_token"],
            issuance_time_ns=values["issuance_time_ns"],
            retrieved_at_ns=values["retrieved_at_ns"],
            climate_day=values["climate_day"],
            raw_text=values["raw_text"],
            raw_sha256=values["raw_sha256"],
            response_sha256=values["response_sha256"],
            response_etag=values["response_etag"],
            response_last_modified=values["response_last_modified"],
            source_channel=values["source_channel"],
            registry_version=values["registry_version"],
            schema_version=values["schema_version"],
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        """Return the explicit Arrow schema for this record type."""
        return pa.schema(
            [
                pa.field("station", pa.string(), nullable=False),
                pa.field("product_uuid", pa.string(), nullable=False),
                pa.field("product_code", pa.string(), nullable=False),
                pa.field("issuing_office", pa.string(), nullable=False),
                pa.field("wmo_collective_id", pa.string(), nullable=False),
                pa.field("awips_pil", pa.string(), nullable=True),
                pa.field("wmo_bbb_token", pa.string(), nullable=True),
                pa.field("issuance_time_ns", pa.int64(), nullable=False),
                pa.field("retrieved_at_ns", pa.int64(), nullable=False),
                pa.field("climate_day", pa.date32(), nullable=True),
                pa.field("raw_text", pa.string(), nullable=False),
                pa.field("raw_sha256", pa.string(), nullable=False),
                pa.field("response_sha256", pa.string(), nullable=False),
                pa.field("response_etag", pa.string(), nullable=True),
                pa.field("response_last_modified", pa.string(), nullable=True),
                pa.field("source_channel", pa.string(), nullable=False),
                pa.field("registry_version", pa.string(), nullable=False),
                pa.field("schema_version", pa.int64(), nullable=False),
                pa.field("ts_event", pa.int64(), nullable=False),
                pa.field("ts_init", pa.int64(), nullable=False),
            ],
        )


# Registered exactly once, at module scope.
register_arrow(
    data_cls=NwsRawProduct,
    schema=NwsRawProduct.schema(),
    encoder=make_strict_encoder(NwsRawProduct.schema()),
    decoder=make_strict_decoder(NwsRawProduct, NwsRawProduct.schema()),
)

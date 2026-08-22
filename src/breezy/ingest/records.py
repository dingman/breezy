"""Turn one fetched NWS CLI product into the two catalog record types.

Two public functions, deliberately separate (PHASE1_ACTOR_BRIEF §3.5):

* :func:`build_raw_product` -- the verbatim archive plus provenance. It never
  looks at the *content* of the product, so it cannot fail on a malformed one:
  the bytes that could not be parsed are exactly the bytes worth archiving.
* :func:`build_climate_day` -- the parsed settlement record, built *from* an
  already-archived raw product plus the normalize layer's parsed reading.

They are not one builder returning both. The inputs differ, the failure modes
differ, and only the second can fail on parse; a combined function would force
every caller through a union return it does not want.

Why both builders take a whole object rather than repeating its fields
----------------------------------------------------------------------
`retrieved_at_ns`, `raw_sha256`, `issuance_time_ns`, `issuing_office`,
`registry_version` and `source_channel` must be identical on both records --
`raw_sha256` is the join between them, and `retrieved_at_ns` becomes `ts_init`
on both. Passing them twice creates a way for them to disagree; passing the
archive record itself removes it. Sequencing follows: archive the bytes, then
build the reading from the archive.

The same principle governs `build_raw_product`'s `fetch` parameter. It takes
the whole `FetchResult` -- digest, URL, cache validators **and receipt
instant** -- because those all describe one event and must not be able to
disagree about it.

Timestamps
----------
`ts_init` is `retrieved_at_ns` -- the instant the bytes were received -- on both
records, and neither record class accepts it as a constructor parameter, so it
cannot be re-stamped. **Nothing in this module reads a clock** (proved by
`test_neither_builder_reads_a_clock`): stamping construction time would make a
backtest replay in the wrong order and return a plausible, wrong answer.

`retrieved_at_ns` is **not** a parameter of either builder. It is read from
`fetch.retrieved_at_ns`, which `HttpTransport.fetch` stamps adjacent to the
digest, in the only layer that knows when the bytes arrived. A separate
parameter would be a second source of truth for a settlement timestamp, and
"stamp it at the moment `fetch()` returns" would be a rule resting on every
caller being careful, forever.

`ts_event` is derived here, from the registry and a typed date only:

* finals -- the end of the climate day in the site's local **standard** time,
  via the fixed `ClimateDayWindow.std_utc_offset_hours` (never `ZoneInfo`,
  which would follow DST and alias the window);
* preliminaries -- the issuance instant.

`ts_event <= ts_init` is checked for finals only, here, at the first point in
the pipeline where both values exist. Finals are not an exempted class -- they
are the only class where the comparison carries information. A final's
`ts_event` is derived from `(summary_date, registry standard offset)`
*independently of the fetch*, so it can genuinely contradict the retrieval
instant; when it does, the climate day had not ended when the bytes arrived and
the product is therefore not a final. The check is a **misclassification
detector**, not a tolerance.

For a preliminary the same comparison is vacuous: its `ts_event` *is*
`raw_product.issuance_time_ns`, and `NwsRawProduct` already rejects
`issuance_time_ns > retrieved_at_ns` unconditionally at construction. Both
values are read off that one record, so `ts_event <= ts_init` holds for every
pipeline-built preliminary as a theorem, and checking it there would assert
something that cannot fail. It is still not a field invariant of
`NwsClimateDay`: that type accepts a hand-built row the builder can never emit,
which is a fact about the record type's permissiveness rather than about
preliminaries.

Guards this module adds, and guards it deliberately does not
------------------------------------------------------------
Adds: the 304 rejection, `retrieved_at_ns >= issuance_time_ns`, the finals
ordering assertion, and four cross-object consistency checks (window/site,
raw-product station, body-header regex, climate day). Every one of these
catches a caller mistake that would otherwise settle silently against the
wrong day or the wrong station.

Does **not** add:

* *Field validation* -- `NwsRawProduct` and `NwsClimateDay` already guard every
  field through `breezy.domain.validation`, verify `sha256(raw_text)` at
  construction, enforce the value/sentinel-flag exclusivity, `tmin <= tmax` and
  `revision_seq >= 1`. Re-checking here would be a second copy that can drift.
* *An `issuing_office` match against the registry.* One WFO issues for several
  cities, so the field cannot bind a product to a station in the first place
  (the AWIPS PIL and `body_header_regex` do that, in `normalize.cli_parse`),
  and NWS backup operations mean a *different* office legitimately issues a
  site's product during an outage. Rejecting on mismatch would block settlement
  on a valid product. The value is stored verbatim for audit.
* *Physical sanity bounds* (max <= 130 F, min >= -100 F). Those belong to the
  normalization layer -- see `breezy.domain.validation`'s module docstring --
  and their gate route (`record_sanity_violation`) is distinct from "the caller
  passed incoherent arguments". Raising a bare `ValueError` here would collapse
  the two. **No module currently implements them; the caller must, before
  trusting any value for settlement.**
"""

from __future__ import annotations

import datetime as dt
from typing import Final

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct, sha256_text
from breezy.ingest.http import FetchResult, redact_url
from breezy.normalize.classify import classify_issuance, has_correction_evidence
from breezy.normalize.cli_parse import ParsedCliProduct
from breezy.normalize.climate_day import standard_time_zone
from breezy.normalize.units import TemperatureReadingF
from breezy.registry.sites import ClimateDayWindow, SettlementSite

__all__ = ["build_climate_day", "build_raw_product"]

_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_NS_PER_SECOND: Final[int] = 1_000_000_000
_NS_PER_MICROSECOND: Final[int] = 1_000


def build_raw_product(
    *,
    site: SettlementSite,
    registry_version: str,
    fetch: FetchResult,
    product_text: str,
    product_uuid: str,
    product_code: str,
    issuing_office: str,
    wmo_collective_id: str,
    awips_pil: str | None,
    wmo_bbb_token: str | None,
    issuance_time_ns: int,
    climate_day: dt.date | None,
) -> NwsRawProduct:
    """Build the verbatim archive record for one fetched product.

    Parameters
    ----------
    site : SettlementSite
        The registry entry that was polled. `station` is taken from
        `site.cli_location` and from nowhere else -- an identifier extracted
        from product text and interpolated into a catalog path is a
        path-traversal write primitive.
    registry_version : str
        `SiteRegistry.registry_version` of the registry `site` came from.
    fetch : FetchResult
        The transport result, passed whole. `sha256` (the digest of the exact
        received bytes), `retrieved_at_ns` (the instant they arrived, stamped
        inside `HttpTransport.fetch` adjacent to that digest), `url` and the
        cache-validator headers are read from it. The digest is stored verbatim
        as `response_sha256` and is **never** recomputed from decoded text -- a
        re-encoded round trip would attest to bytes that were never on the
        wire. `retrieved_at_ns` becomes `ts_init`, and there is deliberately no
        parameter through which a caller could supply a different one.
    product_text : str
        The verbatim product text. When the response body *is* the product,
        this is the decoded body; when the body is a JSON envelope, it is the
        `productText` field. `raw_sha256` is `sha256(product_text)`, which is a
        different value from `response_sha256` in the envelope case, and both
        are stored.
    product_uuid, product_code, issuing_office, wmo_collective_id : str
        Provenance from the product's own metadata. `product_uuid` is not a
        dedupe key: every re-issue receives a fresh one.
    awips_pil, wmo_bbb_token : str or None
        Line 3 and the line-2 BBB token of the product text, supplied by the
        caller. `normalize` validates both and now publishes them, as
        `CliStructuralHeader` and as `ParsedCliProduct.awips_pil` / `.wmo_bbb`
        -- but archiving deliberately precedes parsing (a product that fails to
        parse is still archived), so they cannot be sourced from a parse result
        on this path. Neither is used as an identifier here.
    issuance_time_ns : int
        UNIX nanoseconds the product was issued. Becomes `ts_event`.
    climate_day : datetime.date or None
        The parsed summary date when it is already known, else `None`. Capture
        legitimately precedes parsing: a product that fails to parse is still
        archived.

    Raises
    ------
    ValueError
        If `fetch` is a 304 Not Modified (a "nothing changed" response carries
        no body and must never become a provenance record), or if the fetch's
        `retrieved_at_ns` precedes `issuance_time_ns`.

    """
    # A 304 sets both `text` and `sha256` to None under `FetchResult`'s own
    # runtime invariant. Narrow rather than assert past it: this is the whole
    # reason those fields are `str | None`. (`retrieved_at_ns` is unconditional
    # on a `FetchResult` and needs no such narrowing -- a 304 still happened at
    # a time -- but a 304 must not become a record regardless.)
    if fetch.status_code == 304 or fetch.sha256 is None:
        raise ValueError(
            f"a {fetch.status_code} response for {site.cli_location} carries no body and "
            f"must never become a provenance record; freshness was satisfied, so record "
            f"the poll as a no-op success instead of building a record",
        )

    if fetch.retrieved_at_ns < issuance_time_ns:
        raise ValueError(
            f"the fetch's `retrieved_at_ns` ({fetch.retrieved_at_ns}) precedes "
            f"`issuance_time_ns` ({issuance_time_ns}) for {site.cli_location}; bytes "
            f"cannot be received before they were issued",
        )

    return NwsRawProduct(
        station=site.cli_location,
        product_uuid=product_uuid,
        product_code=product_code,
        issuing_office=issuing_office,
        wmo_collective_id=wmo_collective_id,
        awips_pil=awips_pil,
        wmo_bbb_token=wmo_bbb_token,
        issuance_time_ns=issuance_time_ns,
        retrieved_at_ns=fetch.retrieved_at_ns,
        climate_day=climate_day,
        raw_text=product_text,
        raw_sha256=sha256_text(product_text),
        response_sha256=fetch.sha256,
        response_etag=fetch.headers.get("etag"),
        response_last_modified=fetch.headers.get("last-modified"),
        source_channel=redact_url(fetch.url),
        registry_version=registry_version,
    )


def build_climate_day(
    *,
    site: SettlementSite,
    window: ClimateDayWindow,
    raw_product: NwsRawProduct,
    parsed: ParsedCliProduct,
    parser_version: str,
    revision_seq: int,
    is_superseded: bool,
) -> NwsClimateDay:
    """Build the parsed settlement record for one archived product.

    Parameters
    ----------
    site : SettlementSite
        The registry entry that was polled. Supplies `station` and the
        `body_header_regex` the parsed header line is re-checked against.
    window : ClimateDayWindow
        The site's fixed standard-time offset, used only to place the end of
        the climate day. Must be the window for the same `(venue, city)` as
        `site`.
    raw_product : NwsRawProduct
        The archive record for the bytes this reading was parsed from, built by
        :func:`build_raw_product`. Supplies `retrieved_at_ns` (hence `ts_init`),
        `raw_sha256` (the join between the two records), `issuance_time_ns`,
        `issuing_office`, `registry_version` and `source_channel`, and the
        verbatim text that `is_final` and `correction_flag` are derived from.
    parsed : ParsedCliProduct
        The normalize layer's parsed reading. `tavg` is the product's own
        published AVERAGE line and is stored exactly as published -- it is
        never computed from max/min, and its sentinel kind is preserved so that
        a missing average and a trace average stay distinguishable.
    parser_version : str
        Provenance of the code that produced `parsed`.
    revision_seq : int
        Monotonic per `(station, climate_day)`, starting at 1. Owned by the
        caller's supersession index; no default, because a silent `1` would
        mask a missing increment on a correction.
    is_superseded : bool
        What was known at write time. Records are never rewritten, so this is a
        historical note, not a selection input.

    Raises
    ------
    ValueError
        If `window` is not the window for `site`; if `raw_product` archives a
        different station than `site`; if the parsed header line does not match
        `site.body_header_regex` (it was parsed against another site's
        pattern); if `raw_product.climate_day` disagrees with
        `parsed.summary_date`; or if a final's `ts_event` post-dates its
        `ts_init`.

    """
    if (window.venue, window.city) != (site.venue, site.city):
        raise ValueError(
            f"climate-day window is for {window.venue}/{window.city} but the site is "
            f"{site.venue}/{site.city}; the standard-time offset defines the climate-day "
            f"boundary and a mismatched one settles the wrong day",
        )

    if raw_product.station != site.cli_location:
        raise ValueError(
            f"raw product archives station {raw_product.station!r} but the site is "
            f"{site.cli_location!r}; one office issues products for several cities, so "
            f"the station must never be inferred across records",
        )

    if site.body_header_regex.match(parsed.station_header_line) is None:
        raise ValueError(
            f"parsed header {parsed.station_header_line!r} does not match "
            f"{site.cli_location}'s registry `body_header_regex`; this product was parsed "
            f"against a different site's pattern",
        )

    if raw_product.climate_day is not None and raw_product.climate_day != parsed.summary_date:
        raise ValueError(
            f"raw product records climate_day {raw_product.climate_day.isoformat()} but the "
            f"parsed headline says {parsed.summary_date.isoformat()}",
        )

    # Derived from the archived bytes, not supplied: a hand-passed `is_final`
    # is the two-issuance trap waiting to happen, and both flags must describe
    # exactly the text whose digest this record carries.
    is_final = classify_issuance(raw_product.raw_text) == "FINAL"

    ts_event = (
        _climate_day_end_ns(parsed.summary_date, window.std_utc_offset_hours)
        if is_final
        else raw_product.issuance_time_ns
    )

    if is_final and ts_event > raw_product.ts_init:
        raise ValueError(
            f"final for {site.cli_location} {parsed.summary_date.isoformat()} has "
            f"`ts_event` {ts_event} after `ts_init` {raw_product.ts_init}: the climate day "
            f"had not ended when the product was retrieved, so this is not a final",
        )

    tmax_f, tmax_flag = _value_and_flag(parsed.tmax)
    tmin_f, tmin_flag = _value_and_flag(parsed.tmin)
    tavg_f, tavg_flag = _value_and_flag(parsed.tavg)

    return NwsClimateDay(
        station=site.cli_location,
        climate_day=parsed.summary_date,
        tmax_f=tmax_f,
        tmin_f=tmin_f,
        tavg_f=tavg_f,
        tmax_flag=tmax_flag,
        tmin_flag=tmin_flag,
        tavg_flag=tavg_flag,
        is_final=is_final,
        correction_flag=has_correction_evidence(raw_product.raw_text),
        revision_seq=revision_seq,
        is_superseded=is_superseded,
        issuing_office=raw_product.issuing_office,
        issuance_time_ns=raw_product.issuance_time_ns,
        retrieved_at_ns=raw_product.retrieved_at_ns,
        parser_version=parser_version,
        registry_version=raw_product.registry_version,
        raw_sha256=raw_product.raw_sha256,
        source_channel=raw_product.source_channel,
        ts_event=ts_event,
    )


def _value_and_flag(reading: TemperatureReadingF) -> tuple[int | None, str | None]:
    """Split a parsed reading into the record's paired value and sentinel flag.

    A sentinel is carried through as the flag with a null value; it is never
    imputed to a number, and never collapsed to a bare `None` that would make
    "missing" and "trace" indistinguishable.
    """
    if reading.sentinel == "NONE":
        return reading.value_f, None
    return None, reading.sentinel


def _climate_day_end_ns(climate_day: dt.date, std_utc_offset_hours: float) -> int:
    """Return UNIX nanoseconds at the end of `climate_day` in local standard time.

    The climate day runs local-standard midnight to midnight year-round, so its
    end is midnight at the start of the following date under the site's fixed
    offset -- never `ZoneInfo`, which follows DST and would alias the window
    across the spring and autumn transitions.
    """
    day_end = dt.datetime.combine(
        climate_day + dt.timedelta(days=1),
        dt.time(0, 0),
        tzinfo=standard_time_zone(std_utc_offset_hours),
    )
    delta = day_end - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * _NS_PER_SECOND + (
        delta.microseconds * _NS_PER_MICROSECOND
    )

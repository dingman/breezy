"""Unit tests for `breezy.ingest.records` -- the two record-construction functions.

These cover the four hazards the brief names as already-live defects or standing
settlement-safety rules:

1. ``ts_init`` propagates ``retrieved_at_ns`` and is never a construction-time
   clock reading (proved by making every ``time`` clock raise during a build).
2. A 304 ``FetchResult`` -- whose ``text``/``sha256`` are ``None`` by runtime
   invariant -- can never reach a provenance record.
3. ``response_sha256`` is the transport's digest of the exact received bytes,
   never recomputed from decoded/round-tripped text.
4. ``tavg_f`` is the product's published AVERAGE, never computed from max/min,
   and missing/trace/present stay three distinct states.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.nws_raw_product import RAW_PRODUCT_SCHEMA_VERSION, NwsRawProduct, sha256_text
from breezy.ingest.http import FetchResult
from breezy.ingest.records import build_climate_day, build_raw_product, value_and_flag
from breezy.normalize.cli_parse import ParsedCliProduct, parse_cli_product
from breezy.normalize.units import TemperatureReadingF
from breezy.registry.sites import ClimateDayWindow, SettlementSite, default_registry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"

VENUE = "polymarket_us"

_NYC_FINAL = "nyc_final_2026-08-21"
_NYC_PRELIM = "nyc_preliminary_2026-08-21"
_NYC_CORRECTION = "nyc_correction_synthetic_2026-08-21"
_NYC_SENTINEL = "nyc_sentinel_synthetic"
_MIA_FINAL = "mia_final_2026-08-21"

# Climate day 2026-08-21 ends at 2026-08-22 00:00 EST (local STANDARD time,
# never EDT) == 2026-08-22 05:00 UTC. Both NYC and MIA run at UTC-5 standard.
_DAY_END_NS = int(dt.datetime(2026, 8, 22, 5, 0, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
_FINAL_ISSUED_NS = int(dt.datetime(2026, 8, 22, 6, 26, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
_FINAL_RETRIEVED_NS = (
    int(dt.datetime(2026, 8, 22, 6, 31, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
)
_PRELIM_ISSUED_NS = int(dt.datetime(2026, 8, 21, 20, 44, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
_PRELIM_RETRIEVED_NS = (
    int(dt.datetime(2026, 8, 21, 20, 49, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
)

PARSER_VERSION = "breezy.normalize.cli_parse@0.1.0"


# --------------------------------------------------------------------------------------
# Fixture loading -- real captured products, not hand-rolled strings
# --------------------------------------------------------------------------------------


def load_product_bytes(dirname: str) -> bytes:
    """Return the fixture's product text as the exact bytes on disk."""
    return (FIXTURES_DIR / dirname / "product.txt").read_bytes()


def load_product_text(dirname: str) -> str:
    return load_product_bytes(dirname).decode("utf-8")


def load_meta(dirname: str) -> dict[str, Any]:
    meta: dict[str, Any] = json.loads((FIXTURES_DIR / dirname / "meta.json").read_text())
    return meta


def site_for(city: str) -> SettlementSite:
    return default_registry().settlement_site(VENUE, city)


def window_for(city: str) -> ClimateDayWindow:
    return default_registry().climate_day_window(VENUE, city)


def registry_version() -> str:
    return default_registry().registry_version


def test_value_and_flag_is_public_for_archive_builder_parity() -> None:
    assert value_and_flag(TemperatureReadingF(value_f=72, sentinel="NONE")) == (72, None)
    assert value_and_flag(TemperatureReadingF(value_f=None, sentinel="T")) == (None, "T")


def make_fetch(
    *,
    text: str | None = "body",
    sha256: str | None = None,
    status_code: int = 200,
    url: str = "https://api.weather.gov/products/40bb657c-e166-44d4-a038-dd18701cf2c8",
    headers: dict[str, str] | None = None,
    retrieved_at_ns: int = _FINAL_RETRIEVED_NS,
) -> FetchResult:
    """Build a `FetchResult` the way the transport would.

    `sha256` defaults to the digest of the *encoded body bytes*, mirroring
    `HttpTransport.fetch`, which digests before decoding. `retrieved_at_ns` is
    stamped by `HttpTransport.fetch` adjacent to that digest, so both describe
    the same event; here it is supplied explicitly for the same reason.
    """
    digest = sha256
    if digest is None and text is not None:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return FetchResult(
        text=text,
        sha256=digest,
        status_code=status_code,
        headers=httpx.Headers(headers or {}),
        url=url,
        retrieved_at_ns=retrieved_at_ns,
    )


def parse_fixture(dirname: str, city: str) -> ParsedCliProduct:
    site = site_for(city)
    return parse_cli_product(
        load_product_text(dirname),
        cli_location=site.cli_location,
        body_header_regex=site.body_header_regex,
    )


def build_nyc_final_raw(**overrides: Any) -> NwsRawProduct:
    meta = load_meta(_NYC_FINAL)
    text = load_product_text(_NYC_FINAL)
    # `retrieved_at_ns` is no longer a `build_raw_product` parameter -- the
    # transport stamps it onto the `FetchResult`, and that is the only place it
    # exists. The helper keeps the name as a convenience knob and folds it into
    # the fetch it builds, so a test still reads "this product arrived at T"
    # while exercising the single-source-of-truth path.
    retrieved_at_ns: int = overrides.pop("retrieved_at_ns", _FINAL_RETRIEVED_NS)
    kwargs: dict[str, Any] = {
        "site": site_for("NYC"),
        "registry_version": registry_version(),
        "fetch": make_fetch(text=text, url=meta["url"], retrieved_at_ns=retrieved_at_ns),
        "product_text": text,
        "product_uuid": meta["product_id"],
        "product_code": "CLI",
        "issuing_office": meta["issuing_office"],
        "wmo_collective_id": meta["wmo_collective_id"],
        "awips_pil": "CLINYC",
        "wmo_bbb_token": None,
        "issuance_time_ns": _FINAL_ISSUED_NS,
        "climate_day": dt.date(2026, 8, 21),
    }
    kwargs.update(overrides)
    return build_raw_product(**kwargs)


def build_nyc_final_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "site": site_for("NYC"),
        "window": window_for("NYC"),
        "raw_product": build_nyc_final_raw(),
        "parsed": parse_fixture(_NYC_FINAL, "NYC"),
        "parser_version": PARSER_VERSION,
        "revision_seq": 1,
        "is_superseded": False,
    }
    kwargs.update(overrides)
    return build_climate_day(**kwargs)


# --------------------------------------------------------------------------------------
# 1. ts_init propagation -- risk #1 in the proposal
# --------------------------------------------------------------------------------------


def test_raw_product_ts_init_is_the_supplied_retrieval_instant() -> None:
    """§4.2: `ts_init` = `retrieved_at_ns`, stamped at receipt and propagated."""
    record = build_nyc_final_raw()

    assert record.retrieved_at_ns == _FINAL_RETRIEVED_NS
    assert record.ts_init == _FINAL_RETRIEVED_NS
    assert record.ts_init != time.time_ns()


def test_climate_day_ts_init_propagates_the_raw_products_retrieval_instant() -> None:
    """The parsed record inherits `ts_init` from the record that attests the bytes."""
    raw = build_nyc_final_raw()
    record = build_climate_day(
        site=site_for("NYC"),
        window=window_for("NYC"),
        raw_product=raw,
        parsed=parse_fixture(_NYC_FINAL, "NYC"),
        parser_version=PARSER_VERSION,
        revision_seq=1,
        is_superseded=False,
    )

    assert record.ts_init == raw.ts_init == _FINAL_RETRIEVED_NS
    assert record.retrieved_at_ns == _FINAL_RETRIEVED_NS
    assert record.ts_init != time.time_ns()


def test_neither_builder_reads_a_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stamping construction time destroys replay fidelity -- so read no clock.

    Every `time` clock is made to raise for the duration of the build. A builder
    that reached for "now" instead of propagating `retrieved_at_ns` fails loudly
    here rather than silently returning a plausible, wrong record.
    """

    def _boom(*_args: object, **_kwargs: object) -> float:
        raise AssertionError("record construction must not read a clock")

    monkeypatch.setattr(time, "time_ns", _boom)
    monkeypatch.setattr(time, "time", _boom)
    monkeypatch.setattr(time, "monotonic", _boom)
    monkeypatch.setattr(time, "monotonic_ns", _boom)

    raw = build_nyc_final_raw()
    day = build_nyc_final_day(raw_product=raw)

    assert raw.ts_init == day.ts_init == _FINAL_RETRIEVED_NS


def test_building_the_same_inputs_twice_is_byte_identical() -> None:
    """A clock read would make two builds of one fetch disagree."""
    first = build_nyc_final_day()
    second = build_nyc_final_day()

    assert first.to_dict() == second.to_dict()


def test_raw_product_rejects_a_retrieval_earlier_than_issuance() -> None:
    """Bytes cannot be received before they were issued."""
    with pytest.raises(ValueError, match="retrieved_at_ns"):
        build_nyc_final_raw(retrieved_at_ns=_FINAL_ISSUED_NS - 1)


def test_ts_init_comes_from_the_fetch_result_and_nowhere_else() -> None:
    """The transport's stamp is the single source of truth for `ts_init`."""
    fetch = make_fetch(
        text=load_product_text(_NYC_FINAL),
        url=load_meta(_NYC_FINAL)["url"],
        retrieved_at_ns=_FINAL_RETRIEVED_NS + 42,
    )
    record = build_raw_product(
        site=site_for("NYC"),
        registry_version=registry_version(),
        fetch=fetch,
        product_text=load_product_text(_NYC_FINAL),
        product_uuid=load_meta(_NYC_FINAL)["product_id"],
        product_code="CLI",
        issuing_office=load_meta(_NYC_FINAL)["issuing_office"],
        wmo_collective_id=load_meta(_NYC_FINAL)["wmo_collective_id"],
        awips_pil="CLINYC",
        wmo_bbb_token=None,
        issuance_time_ns=_FINAL_ISSUED_NS,
        climate_day=dt.date(2026, 8, 21),
    )

    assert record.retrieved_at_ns == fetch.retrieved_at_ns
    assert record.ts_init == fetch.retrieved_at_ns


def test_build_raw_product_no_longer_accepts_a_separate_retrieval_timestamp() -> None:
    """Two sources of truth for a settlement timestamp is the removed defect.

    The parameter existed only because `FetchResult` carried no timestamp. Now
    that it does, a caller cannot hand down a value that disagrees with the
    fetch -- there is no parameter left to disagree through.
    """
    with pytest.raises(TypeError, match="retrieved_at_ns"):
        build_raw_product(  # type: ignore[call-arg]
            site=site_for("NYC"),
            registry_version=registry_version(),
            fetch=make_fetch(text=load_product_text(_NYC_FINAL)),
            retrieved_at_ns=_FINAL_RETRIEVED_NS + 999,
            product_text=load_product_text(_NYC_FINAL),
            product_uuid=load_meta(_NYC_FINAL)["product_id"],
            product_code="CLI",
            issuing_office=load_meta(_NYC_FINAL)["issuing_office"],
            wmo_collective_id=load_meta(_NYC_FINAL)["wmo_collective_id"],
            awips_pil="CLINYC",
            wmo_bbb_token=None,
            issuance_time_ns=_FINAL_ISSUED_NS,
            climate_day=dt.date(2026, 8, 21),
        )


# --------------------------------------------------------------------------------------
# 2. A 304 must never reach a provenance record
# --------------------------------------------------------------------------------------


def test_a_304_fetch_result_is_rejected() -> None:
    """§4.3 of the brief: a 304 carries no body; it is a programming error here."""
    not_modified = make_fetch(text=None, sha256=None, status_code=304)

    with pytest.raises(ValueError, match="304"):
        build_nyc_final_raw(fetch=not_modified)


def test_the_304_rejection_names_the_station_and_is_not_an_assert() -> None:
    """`python -O` strips `assert`; this guard must survive it."""
    not_modified = make_fetch(text=None, sha256=None, status_code=304)

    with pytest.raises(ValueError) as excinfo:
        build_nyc_final_raw(fetch=not_modified)

    assert "NYC" in str(excinfo.value)


# --------------------------------------------------------------------------------------
# 3. Digest fidelity -- the stored digest attests to the bytes that were fetched
# --------------------------------------------------------------------------------------


def test_response_sha256_is_the_transports_digest_verbatim() -> None:
    """Never recomputed from decoded text: the transport digests raw bytes."""
    fetch = make_fetch(text=load_product_text(_NYC_FINAL))
    record = build_nyc_final_raw(fetch=fetch)

    assert record.response_sha256 == fetch.sha256


def test_response_sha256_is_not_recomputed_from_the_product_text() -> None:
    """The body is a JSON envelope; the product text is a field inside it.

    `response_sha256` must therefore be the envelope's digest, and `raw_sha256`
    the product text's -- two different values that must not be conflated.
    """
    product_text = load_product_text(_NYC_FINAL)
    envelope = json.dumps({"productText": product_text})
    fetch = make_fetch(text=envelope)

    record = build_nyc_final_raw(fetch=fetch, product_text=product_text)

    assert record.response_sha256 == hashlib.sha256(envelope.encode("utf-8")).hexdigest()
    assert record.raw_sha256 == sha256_text(product_text)
    assert record.response_sha256 != record.raw_sha256


def test_raw_sha256_matches_the_exact_fixture_bytes() -> None:
    """Independently computed from the file's bytes -- no round-trip in between."""
    expected = hashlib.sha256(load_product_bytes(_NYC_FINAL)).hexdigest()
    record = build_nyc_final_raw()

    assert record.raw_sha256 == expected
    assert record.raw_sha256 == load_meta(_NYC_FINAL)["sha256_body"]
    assert record.verify_digest()


def test_raw_text_is_stored_verbatim() -> None:
    record = build_nyc_final_raw()

    assert record.raw_text == load_product_text(_NYC_FINAL)


def test_climate_day_joins_to_its_raw_product_by_digest() -> None:
    raw = build_nyc_final_raw()
    day = build_nyc_final_day(raw_product=raw)

    assert day.raw_sha256 == raw.raw_sha256


# --------------------------------------------------------------------------------------
# 4. tavg -- published AVERAGE, never computed; three distinct states
# --------------------------------------------------------------------------------------


def test_tavg_is_the_published_average_present_case() -> None:
    record = build_nyc_final_day()

    assert record.tavg_f == 71
    assert record.tavg_flag is None


@pytest.mark.parametrize(
    ("dirname", "city", "tmax", "tmin", "published_avg"),
    [
        # 94/81 -> midpoint 87.5; published 88, so a floor() would read 87.
        (_MIA_FINAL, "MIA", 94, 81, 88),
        # 80/63 -> midpoint 71.5; published 71, so a round() would read 72.
        (_NYC_CORRECTION, "NYC", 80, 63, 71),
    ],
)
def test_tavg_is_never_computed_from_max_and_min(
    dirname: str,
    city: str,
    tmax: int,
    tmin: int,
    published_avg: int,
) -> None:
    """Together these two cases exclude both floor() and round() of the midpoint."""
    raw = build_nyc_final_raw(
        site=site_for(city),
        product_text=load_product_text(dirname),
        awips_pil=f"CLI{site_for(city).cli_location}",
    )
    record = build_climate_day(
        site=site_for(city),
        window=window_for(city),
        raw_product=raw,
        parsed=parse_fixture(dirname, city),
        parser_version=PARSER_VERSION,
        revision_seq=1,
        is_superseded=False,
    )

    assert (record.tmax_f, record.tmin_f) == (tmax, tmin)
    assert record.tavg_f == published_avg


def test_sentinels_keep_missing_and_trace_distinct() -> None:
    """`M` (missing), `T` (trace) and `MS` must not collapse into a bare `None`."""
    raw = build_nyc_final_raw(product_text=load_product_text(_NYC_SENTINEL))
    record = build_climate_day(
        site=site_for("NYC"),
        window=window_for("NYC"),
        raw_product=raw,
        parsed=parse_fixture(_NYC_SENTINEL, "NYC"),
        parser_version=PARSER_VERSION,
        revision_seq=1,
        is_superseded=False,
    )

    assert (record.tmax_f, record.tmax_flag) == (None, "M")
    assert (record.tmin_f, record.tmin_flag) == (None, "T")
    assert (record.tavg_f, record.tavg_flag) == (None, "MS")
    assert record.tmax_flag != record.tmin_flag


@pytest.mark.parametrize("sentinel", ["M", "T", "MS", "MB"])
def test_every_sentinel_kind_reaches_the_record_unchanged(sentinel: str) -> None:
    parsed = parse_fixture(_NYC_FINAL, "NYC")
    replaced = ParsedCliProduct(
        summary_date=parsed.summary_date,
        station_header_line=parsed.station_header_line,
        tmax=parsed.tmax,
        tmin=parsed.tmin,
        tavg=TemperatureReadingF(value_f=None, sentinel=sentinel),  # type: ignore[arg-type]
        awips_pil=parsed.awips_pil,
        wmo_bbb=parsed.wmo_bbb,
    )

    record = build_nyc_final_day(parsed=replaced)

    assert record.tavg_f is None
    assert record.tavg_flag == sentinel


# --------------------------------------------------------------------------------------
# ts_event -- semantic instant, derived from the registry and a typed date
# --------------------------------------------------------------------------------------


def test_final_ts_event_is_the_climate_day_end_in_local_standard_time() -> None:
    """Never UTC, never the DST clock: 2026-08-21 ends at 05:00Z under EST."""
    record = build_nyc_final_day()

    assert record.is_final is True
    assert record.ts_event == _DAY_END_NS
    assert record.ts_event <= record.ts_init


def test_preliminary_ts_event_is_the_issuance_instant() -> None:
    raw = build_nyc_final_raw(
        product_text=load_product_text(_NYC_PRELIM),
        issuance_time_ns=_PRELIM_ISSUED_NS,
        retrieved_at_ns=_PRELIM_RETRIEVED_NS,
    )
    record = build_climate_day(
        site=site_for("NYC"),
        window=window_for("NYC"),
        raw_product=raw,
        parsed=parse_fixture(_NYC_PRELIM, "NYC"),
        parser_version=PARSER_VERSION,
        revision_seq=1,
        is_superseded=False,
    )

    assert record.is_final is False
    assert record.ts_event == _PRELIM_ISSUED_NS


def test_a_final_may_not_predate_the_climate_day_it_reports() -> None:
    """§4.2: `ts_event <= ts_init` is asserted for finals, at its first executable point."""
    raw = build_nyc_final_raw(
        issuance_time_ns=_FINAL_ISSUED_NS - 86_400 * 1_000_000_000,
        retrieved_at_ns=_FINAL_RETRIEVED_NS - 86_400 * 1_000_000_000,
    )

    with pytest.raises(ValueError, match="ts_event"):
        build_climate_day(
            site=site_for("NYC"),
            window=window_for("NYC"),
            raw_product=raw,
            parsed=parse_fixture(_NYC_FINAL, "NYC"),
            parser_version=PARSER_VERSION,
            revision_seq=1,
            is_superseded=False,
        )


def test_ts_event_uses_the_sites_own_standard_offset() -> None:
    """LAX is UTC-8 standard, so the same climate day ends three hours later."""
    lax_day_end = int(dt.datetime(2026, 8, 22, 8, 0, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
    # The real LAX final was issued 08:50Z -- after its climate day ended at
    # 08:00Z under PST, three hours later than NYC's under EST.
    raw = build_nyc_final_raw(
        site=site_for("LAX"),
        product_text=load_product_text("lax_final_2026-08-21"),
        awips_pil="CLILAX",
        issuance_time_ns=int(
            dt.datetime(2026, 8, 22, 8, 50, tzinfo=dt.UTC).timestamp(),
        )
        * 1_000_000_000,
        retrieved_at_ns=int(
            dt.datetime(2026, 8, 22, 8, 55, tzinfo=dt.UTC).timestamp(),
        )
        * 1_000_000_000,
    )

    record = build_climate_day(
        site=site_for("LAX"),
        window=window_for("LAX"),
        raw_product=raw,
        parsed=parse_fixture("lax_final_2026-08-21", "LAX"),
        parser_version=PARSER_VERSION,
        revision_seq=1,
        is_superseded=False,
    )

    assert record.ts_event == lax_day_end


# --------------------------------------------------------------------------------------
# Identifiers come from the registry, never from product text
# --------------------------------------------------------------------------------------


def test_station_comes_from_the_registry_not_the_product_text() -> None:
    """Interpolating an extracted location into a path is a traversal primitive."""
    record = build_nyc_final_raw(product_text="../../../etc/passwd\nnot a CLI product\n")

    assert record.station == site_for("NYC").cli_location == "NYC"


def test_climate_day_station_comes_from_the_registry() -> None:
    record = build_nyc_final_day()

    assert record.station == "NYC"


def test_climate_day_is_the_parsed_summary_date_as_a_typed_date() -> None:
    record = build_nyc_final_day()

    assert record.climate_day == dt.date(2026, 8, 21)
    assert type(record.climate_day) is dt.date


def test_source_channel_records_the_url_that_was_actually_fetched() -> None:
    record = build_nyc_final_raw()

    assert record.source_channel == load_meta(_NYC_FINAL)["url"]


def test_source_channel_redacts_query_values() -> None:
    record = build_nyc_final_raw(
        fetch=make_fetch(
            text=load_product_text(_NYC_FINAL),
            url="https://api.weather.gov/products?token=supersecret",
        ),
    )

    assert "supersecret" not in record.source_channel
    assert "REDACTED" in record.source_channel


def test_climate_day_inherits_provenance_from_the_raw_product() -> None:
    raw = build_nyc_final_raw()
    day = build_nyc_final_day(raw_product=raw)

    assert day.issuing_office == raw.issuing_office
    assert day.issuance_time_ns == raw.issuance_time_ns
    assert day.registry_version == raw.registry_version
    assert day.source_channel == raw.source_channel


# --------------------------------------------------------------------------------------
# Classification and correction evidence describe the archived bytes
# --------------------------------------------------------------------------------------


def test_is_final_is_derived_from_the_archived_product_text() -> None:
    """The two-issuance trap: a preliminary must never be recorded as final."""
    prelim_raw = build_nyc_final_raw(
        product_text=load_product_text(_NYC_PRELIM),
        issuance_time_ns=_PRELIM_ISSUED_NS,
        retrieved_at_ns=_PRELIM_RETRIEVED_NS,
    )
    prelim = build_climate_day(
        site=site_for("NYC"),
        window=window_for("NYC"),
        raw_product=prelim_raw,
        parsed=parse_fixture(_NYC_PRELIM, "NYC"),
        parser_version=PARSER_VERSION,
        revision_seq=1,
        is_superseded=False,
    )

    assert prelim.is_final is False
    assert build_nyc_final_day().is_final is True


def test_correction_evidence_is_detected_from_the_archived_product_text() -> None:
    raw = build_nyc_final_raw(product_text=load_product_text(_NYC_CORRECTION))
    record = build_climate_day(
        site=site_for("NYC"),
        window=window_for("NYC"),
        raw_product=raw,
        parsed=parse_fixture(_NYC_CORRECTION, "NYC"),
        parser_version=PARSER_VERSION,
        revision_seq=2,
        is_superseded=False,
    )

    assert record.correction_flag is True
    assert record.revision_seq == 2
    assert build_nyc_final_day().correction_flag is False


# --------------------------------------------------------------------------------------
# Cross-object consistency guards
# --------------------------------------------------------------------------------------


def test_a_window_for_another_site_is_rejected() -> None:
    """Using LAX's standard offset for NYC silently settles the wrong day."""
    with pytest.raises(ValueError, match="climate-day window"):
        build_nyc_final_day(window=window_for("LAX"))


def test_a_raw_product_for_another_station_is_rejected() -> None:
    """The office-collision hazard: one WFO issues several cities' products."""
    mia_raw = build_nyc_final_raw(
        site=site_for("MIA"),
        product_text=load_product_text(_MIA_FINAL),
        awips_pil="CLIMIA",
    )

    with pytest.raises(ValueError, match="station"):
        build_nyc_final_day(raw_product=mia_raw)


def test_a_header_line_that_the_registry_regex_rejects_is_refused() -> None:
    """Guards a parse run against the wrong site's regex."""
    parsed = parse_fixture(_MIA_FINAL, "MIA")

    with pytest.raises(ValueError, match="body_header_regex"):
        build_nyc_final_day(parsed=parsed)


def test_a_climate_day_disagreeing_with_the_raw_product_is_rejected() -> None:
    raw = build_nyc_final_raw(climate_day=dt.date(2026, 8, 20))

    with pytest.raises(ValueError, match="climate_day"):
        build_nyc_final_day(raw_product=raw)


def test_a_raw_product_captured_before_parsing_carries_no_climate_day() -> None:
    """`build_raw_product` cannot fail on content, so it archives unparsed bytes."""
    raw = build_nyc_final_raw(climate_day=None)

    assert raw.climate_day is None
    day = build_nyc_final_day(raw_product=raw)
    assert day.climate_day == dt.date(2026, 8, 21)


# --------------------------------------------------------------------------------------
# Field pass-through and schema stamping
# --------------------------------------------------------------------------------------


def test_raw_product_carries_the_full_provenance_set() -> None:
    meta = load_meta(_NYC_FINAL)
    record = build_nyc_final_raw(wmo_bbb_token="CCA")

    assert record.product_uuid == meta["product_id"]
    assert record.product_code == "CLI"
    assert record.issuing_office == meta["issuing_office"]
    assert record.wmo_collective_id == meta["wmo_collective_id"]
    assert record.awips_pil == "CLINYC"
    assert record.wmo_bbb_token == "CCA"
    assert record.issuance_time_ns == _FINAL_ISSUED_NS
    assert record.registry_version == registry_version()
    assert record.schema_version == RAW_PRODUCT_SCHEMA_VERSION


def test_raw_product_records_http_cache_validators_when_present() -> None:
    fetch = make_fetch(
        text=load_product_text(_NYC_FINAL),
        headers={"ETag": '"abc123"', "Last-Modified": "Sat, 22 Aug 2026 06:26:00 GMT"},
    )
    record = build_nyc_final_raw(fetch=fetch)

    assert record.response_etag == '"abc123"'
    assert record.response_last_modified == "Sat, 22 Aug 2026 06:26:00 GMT"


def test_raw_product_cache_validators_are_none_when_absent() -> None:
    record = build_nyc_final_raw()

    assert record.response_etag is None
    assert record.response_last_modified is None


def test_climate_day_carries_the_supplied_revision_state() -> None:
    record = build_nyc_final_day(revision_seq=3, is_superseded=True)

    assert record.revision_seq == 3
    assert record.is_superseded is True
    assert record.parser_version == PARSER_VERSION
    assert record.schema_version == CLIMATE_DAY_SCHEMA_VERSION


def test_domain_field_guards_still_apply_through_the_builders() -> None:
    """The builders add guards; they never replace the record types' own."""
    with pytest.raises(ValueError, match="revision_seq"):
        build_nyc_final_day(revision_seq=0)

    with pytest.raises(TypeError):
        build_nyc_final_raw(product_uuid=None)

"""Unit tests for archived CLI backfill record builders."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from breezy.domain.archived_raw_product import ArchivedRawProduct
from breezy.ingest.archive_records import build_archived_climate_day
from breezy.normalize.cli_parse import ParsedCliProduct, parse_cli_product
from breezy.registry.sites import SettlementSite

from .test_ingest_records import (
    PARSER_VERSION,
    build_nyc_final_day,
    build_nyc_final_raw,
    load_product_text,
    parse_fixture,
    registry_version,
    site_for,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"

_FINAL_ISSUED_NS = int(dt.datetime(2026, 8, 22, 6, 26, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
_ARCHIVE_RETRIEVED_NS = (
    int(dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
)


def make_archived_raw_product(
    *,
    site: SettlementSite | None = None,
    parsed: ParsedCliProduct | None = None,
    text: str | None = None,
    **overrides: Any,
) -> ArchivedRawProduct:
    site = site or site_for("NYC")
    text = text or load_product_text("nyc_final_2026-08-21")
    parsed = parsed or parse_fixture("nyc_final_2026-08-21", "NYC")
    live_raw = build_nyc_final_raw(site=site, product_text=text, awips_pil=parsed.awips_pil)
    kwargs: dict[str, Any] = {
        "station": site.cli_location,
        "product_code": live_raw.product_code,
        "issuing_office": live_raw.issuing_office,
        "wmo_collective_id": live_raw.wmo_collective_id,
        "awips_pil": live_raw.awips_pil,
        "wmo_bbb_token": live_raw.wmo_bbb_token,
        "issuance_time_ns": live_raw.issuance_time_ns,
        "issuance_time_source": "wmo_filename",
        "archive_retrieved_at_ns": _ARCHIVE_RETRIEVED_NS,
        "climate_day": parsed.summary_date,
        "raw_text": text,
        "raw_sha256": live_raw.raw_sha256,
        "archive_source_url": "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?<redacted>",
        "archive_job_version": "breezy-archive-backfill@stage2-test",
        "registry_version": registry_version(),
    }
    kwargs.update(overrides)
    return ArchivedRawProduct(**kwargs)


def test_archived_builder_matches_live_builder_on_explicit_settlement_fields() -> None:
    """Builder parity mutant: live and archived builders drifting semantically."""
    site = site_for("NYC")
    parsed = parse_fixture("nyc_final_2026-08-21", "NYC")
    live = build_nyc_final_day(parsed=parsed)
    archived = build_archived_climate_day(
        site=site,
        raw_product=make_archived_raw_product(site=site, parsed=parsed),
        parsed=parsed,
        parser_version=PARSER_VERSION,
        revision_seq=1,
        station_year_yield=0.9836,
        admission_era="modern",
    )
    excluded_fields = [
        "archive_job_version",
        "archive_retrieved_at_ns",
        "archive_source_url",
        "admission_era",
        "is_correction_bbb",
        "is_superseded",
        "issuance_time_source",
        "retrieved_at_ns",
        "schema_version",
        "source_channel",
        "station_year_yield",
        "ts_event",
        "ts_init",
        "wmo_transmission_sequence",
        "wmo_bbb_token",
    ]
    comparable = sorted((set(live.to_dict()) | set(archived.to_dict())) - set(excluded_fields))

    assert comparable == [
        "climate_day",
        "correction_flag",
        "is_final",
        "issuance_time_ns",
        "issuing_office",
        "parser_version",
        "raw_sha256",
        "registry_version",
        "revision_seq",
        "station",
        "tavg_f",
        "tavg_flag",
        "tmax_f",
        "tmax_flag",
        "tmin_f",
        "tmin_flag",
    ]
    assert {field: live.to_dict()[field] for field in comparable} == {
        field: archived.to_dict()[field] for field in comparable
    }


def test_archived_builder_derives_finality_and_rejects_manual_is_final() -> None:
    """Builder mutant: accepting a caller-supplied finality flag."""
    parsed = parse_fixture("nyc_preliminary_2026-08-21", "NYC")
    text = load_product_text("nyc_preliminary_2026-08-21")
    raw = make_archived_raw_product(parsed=parsed, text=text, issuance_time_ns=_FINAL_ISSUED_NS - 1)

    record = build_archived_climate_day(
        site=site_for("NYC"),
        raw_product=raw,
        parsed=parsed,
        parser_version=PARSER_VERSION,
        revision_seq=1,
        station_year_yield=0.9836,
        admission_era="modern",
    )

    assert record.is_final is False
    with pytest.raises(TypeError, match="is_final"):
        build_archived_climate_day(  # type: ignore[call-arg]
            site=site_for("NYC"),
            raw_product=raw,
            parsed=parsed,
            parser_version=PARSER_VERSION,
            revision_seq=1,
            station_year_yield=0.9836,
            admission_era="modern",
            is_final=True,
        )


def test_archived_builder_uses_structural_header_for_transmission_sequence() -> None:
    """Builder mutant: inventing sequence provenance from `ParsedCliProduct`."""
    text = load_product_text("nyc_final_2026-08-21").replace("\n000\n", "\n487\n", 1)
    parsed = parse_cli_product(
        text,
        cli_location=site_for("NYC").cli_location,
        body_header_regex=site_for("NYC").body_header_regex,
    )

    record = build_archived_climate_day(
        site=site_for("NYC"),
        raw_product=make_archived_raw_product(parsed=parsed, text=text),
        parsed=parsed,
        parser_version=PARSER_VERSION,
        revision_seq=1,
        station_year_yield=0.9836,
        admission_era="modern",
    )

    assert not hasattr(parsed, "wmo_transmission_sequence")
    assert record.wmo_transmission_sequence == "487"


def test_archived_builder_rechecks_body_header_against_registry() -> None:
    """Builder mutant: omitting the registry body-header re-check."""
    parsed = parse_fixture("mia_final_2026-08-21", "MIA")

    with pytest.raises(ValueError, match="body_header_regex"):
        build_archived_climate_day(
            site=site_for("NYC"),
            raw_product=make_archived_raw_product(climate_day=None),
            parsed=parsed,
            parser_version=PARSER_VERSION,
            revision_seq=1,
            station_year_yield=0.9836,
            admission_era="modern",
        )

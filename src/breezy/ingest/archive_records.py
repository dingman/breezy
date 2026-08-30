"""Builders for archived CLI backfill records.

These mirror the live record builder while preserving archive-only provenance
and the different archived timestamp semantics. Finality is derived from the
verbatim bytes every time; callers cannot supply it.
"""

from __future__ import annotations

from breezy.domain.archived_climate_day import ArchivedClimateDay
from breezy.domain.archived_raw_product import ArchivedRawProduct
from breezy.ingest.records import _value_and_flag
from breezy.normalize.classify import classify_issuance, has_correction_evidence
from breezy.normalize.cli_parse import ParsedCliProduct, check_structural_allowlist
from breezy.registry.sites import SettlementSite

__all__ = ["build_archived_climate_day"]


def build_archived_climate_day(
    *,
    site: SettlementSite,
    raw_product: ArchivedRawProduct,
    parsed: ParsedCliProduct,
    parser_version: str,
    revision_seq: int,
    station_year_yield: float,
    admission_era: str,
) -> ArchivedClimateDay:
    """Build the parsed archived climate-day record for one archived product."""
    if raw_product.station != site.cli_location:
        raise ValueError(
            f"archived raw product records station {raw_product.station!r} but the site is "
            f"{site.cli_location!r}; station identity must come from the registry",
        )

    header = check_structural_allowlist(raw_product.raw_text, cli_location=site.cli_location)

    if raw_product.awips_pil is not None and raw_product.awips_pil != header.awips_pil:
        raise ValueError(
            f"archived raw product records AWIPS PIL {raw_product.awips_pil!r} but the "
            f"structural header says {header.awips_pil!r}",
        )

    if raw_product.wmo_bbb_token != header.wmo_bbb:
        raise ValueError(
            f"archived raw product records WMO BBB {raw_product.wmo_bbb_token!r} but the "
            f"structural header says {header.wmo_bbb!r}",
        )

    if site.body_header_regex.match(parsed.station_header_line) is None:
        raise ValueError(
            f"parsed header {parsed.station_header_line!r} does not match "
            f"{site.cli_location}'s registry `body_header_regex`; this product was parsed "
            f"against a different site's pattern",
        )

    if raw_product.climate_day is not None and raw_product.climate_day != parsed.summary_date:
        raise ValueError(
            f"archived raw product records climate_day {raw_product.climate_day.isoformat()} "
            f"but the parsed headline says {parsed.summary_date.isoformat()}",
        )

    is_final = classify_issuance(raw_product.raw_text) == "FINAL"
    tmax_f, tmax_flag = _value_and_flag(parsed.tmax)
    tmin_f, tmin_flag = _value_and_flag(parsed.tmin)
    tavg_f, tavg_flag = _value_and_flag(parsed.tavg)

    return ArchivedClimateDay(
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
        is_correction_bbb=header.is_correction_bbb,
        revision_seq=revision_seq,
        issuing_office=raw_product.issuing_office,
        wmo_transmission_sequence=header.wmo_transmission_sequence,
        wmo_bbb_token=header.wmo_bbb,
        issuance_time_ns=raw_product.issuance_time_ns,
        issuance_time_source=raw_product.issuance_time_source,
        archive_retrieved_at_ns=raw_product.archive_retrieved_at_ns,
        archive_source_url=raw_product.archive_source_url,
        archive_job_version=raw_product.archive_job_version,
        parser_version=parser_version,
        registry_version=raw_product.registry_version,
        raw_sha256=raw_product.raw_sha256,
        station_year_yield=station_year_yield,
        admission_era=admission_era,
    )

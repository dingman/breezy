from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay


def _load_study_module() -> ModuleType:
    path = Path("scripts/analysis/settlement_alignment_study.py")
    spec = importlib.util.spec_from_file_location("settlement_alignment_study", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_DAY_END_NS = int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_BASE_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"settlement-alignment").hexdigest()


def _climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": dt.date(2026, 8, 22),
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tavg_flag": None,
        "tmax_flag": None,
        "tmin_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _BASE_NS - 240_000_000_000,
        "retrieved_at_ns": _BASE_NS,
        "parser_version": "test",
        "registry_version": "test",
        "raw_sha256": _SHA,
        "source_channel": "test",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def test_join_builds_running_max_thresholds_and_margin_buckets() -> None:
    study = _load_study_module()

    rows = [
        {
            "valid": "2025-08-01 04:30",
            "metar": "KNYC 010430Z AUTO RMK AO2 T02500150 $",
        },
        {
            "valid": "2025-08-01 18:00",
            "metar": "KNYC 011800Z AUTO RMK AO2 T03110160 $",
        },
        {
            "valid": "2025-08-02 03:30",
            "metar": "KNYC 020330Z AUTO RMK AO2 T03000150 $",
        },
        {
            "valid": "2025-08-02 05:30",
            "metar": "KNYC 020530Z AUTO RMK AO2 T01000050 $",
        },
    ]

    temperatures, drops = study.metar_temperatures(
        city="NYC",
        rows=rows,
        std_utc_offset_hours=-5.0,
    )
    maxima = study.daily_metar_maxima(temperatures, source="fixture")
    labels = {
        dt.date(2025, 7, 31): study.CliLabel(
            city="NYC",
            climate_day=dt.date(2025, 7, 31),
            tmax_f=77,
            tmax_flag=None,
            is_final=True,
            correction_flag=False,
            issued_at_utc=None,
            source="fixture-cli-0731",
            raw_sha256="0" * 64,
        ),
        dt.date(2025, 8, 1): study.CliLabel(
            city="NYC",
            climate_day=dt.date(2025, 8, 1),
            tmax_f=88,
            tmax_flag=None,
            is_final=True,
            correction_flag=False,
            issued_at_utc=None,
            source="fixture-cli-0801",
            raw_sha256="1" * 64,
        ),
        dt.date(2025, 8, 2): study.CliLabel(
            city="NYC",
            climate_day=dt.date(2025, 8, 2),
            tmax_f=50,
            tmax_flag=None,
            is_final=True,
            correction_flag=False,
            issued_at_utc=None,
            source="fixture-cli-0802",
            raw_sha256="2" * 64,
        ),
    }

    cases, case_drops = study.build_threshold_cases(
        city="NYC",
        labels=labels,
        daily_maxima=maxima,
    )

    assert drops == {}
    assert case_drops == {}
    assert maxima[dt.date(2025, 7, 31)].rounded_max_f == 77
    assert maxima[dt.date(2025, 8, 1)].rounded_max_f == 88
    assert maxima[dt.date(2025, 8, 1)].unrounded_max_f == 87.98

    august_cases = [case for case in cases if case.climate_day == dt.date(2025, 8, 1)]
    assert [(case.threshold_f, case.bucket, case.hit) for case in august_cases] == [
        (88, "0-1F", True),
        (87, "1-2F", True),
        (86, "2-3F", True),
        (85, "3F+", True),
    ]
    assert august_cases[0].rounding_sensitive is True
    assert august_cases[1].rounding_sensitive is False


def test_catalog_final_selection_requires_the_venue_cli_location() -> None:
    study = _load_study_module()

    preliminary = _climate_day(
        is_final=False,
        tmax_f=82,
        retrieved_at_ns=_BASE_NS - 10,
        ts_event=_BASE_NS - 10,
    )
    expected_final = _climate_day(tmax_f=84, retrieved_at_ns=_BASE_NS)
    wrong_station_final = _climate_day(
        station="JFK",
        tmax_f=99,
        retrieved_at_ns=_BASE_NS + 1,
        revision_seq=2,
    )

    selected, summary = study.select_catalog_finals_for_site(
        city="NYC",
        expected_cli_location="NYC",
        records=(preliminary, expected_final, wrong_station_final),
    )

    assert selected == {("NYC", dt.date(2026, 8, 22)): expected_final}
    assert summary.final_records == 1
    assert summary.preliminary_records == 1
    assert summary.wrong_station_records == 1


def test_missing_catalog_base_is_not_reported_as_empty_catalog() -> None:
    study = _load_study_module()

    validation, labels = study.validate_archive_against_catalog(
        client=object(),
        cache_dir=Path("/unused"),
        delay_s=0.0,
        catalog_base=None,
        sites=(),
    )

    assert labels == {}
    assert validation.status == "blocked: catalog_base_not_configured"
    assert validation.checked_count == 0
    assert validation.details == ("BREEZY_CATALOG_BASE/--catalog-base was not supplied",)


def test_insufficient_sample_message_names_days_needed_and_unblock_date() -> None:
    study = _load_study_module()
    generated_at = dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC)
    stats = study.BucketStats(
        sample_count=28,
        hit_count=28,
        hit_rate=1.0,
        wilson_95_lower=0.879353,
    )

    message = study.insufficient_sample_message(
        stats,
        min_sample_count=study.MIN_SAMPLE_COUNT,
        cases_per_climate_day=4,
        generated_at=generated_at,
    )

    assert message == (
        "NOT YET ANSWERABLE: insufficient sample; 28/1000 cases evaluated, "
        "972 more cases needed = 243 more climate days at 4 cases/day; "
        "earliest live-only unblock date 2027-04-25"
    )

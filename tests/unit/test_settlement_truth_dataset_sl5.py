"""Unit tests for SL-5: extending CLI settlement-truth coverage to yesterday.

Covers the additions in ``scripts/analysis/settlement_truth_dataset.py`` made
for plan §3.2 item 10 / §7 SL-5 (`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3`):

* ``archive_windows(include_extension=True)`` adds the 2026-01-01..
  2026-09-28 window per city, without altering any pre-SL-5 window (the
  ones ``test_declared_archive_windows_are_not_contiguous`` in
  ``test_settlement_truth_dataset.py`` pins);
* absent days inside that window are reported, never interpolated;
* ``final_rows_for_gate`` -- the new selector every split-bearing consumer
  must read through -- excludes preliminary-only, no-product, ambiguous-final
  and sentinel-tmax final rows, keeps only the post-supersession final value
  (never a superseded one), and refuses if more than one final row ever
  reaches it for the same ``(station, climate_day)``;
* overlapping ``ArchiveWindow`` coverage for one city, flowing through
  ``main()``'s real multi-window merge path, dedupes to one row per day via
  the existing digest dedupe -- not merely via ``build_truth_rows``'s
  one-row-per-day grouping, which is true by construction regardless.

This file does not import or modify ``test_settlement_truth_dataset.py``;
it reuses that file's own module-loading convention so both suites load one
consistent module object per test run.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
import zipfile
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_ANCHOR_PRODUCT_PATH = (
    _REPO_ROOT
    / "docs"
    / "evidence"
    / "venue"
    / "polymarket_us"
    / "raw"
    / "nws"
    / "CLINYC_202604240617-KOKX-CDUS41-CLINYC.txt"
)


def _load_module() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / "settlement_truth_dataset.py"
    spec = importlib.util.spec_from_file_location("settlement_truth_dataset", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _issuance(module: ModuleType, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "city": "NYC",
        "climate_day": dt.date(2026, 4, 23),
        "issuance": "FINAL",
        "tmax_f": 73,
        "tmin_f": 45,
        "tavg_f": 59,
        "tmax_flag": None,
        "issued_at_utc": dt.datetime(2026, 4, 24, 6, 17, tzinfo=dt.UTC),
        "wmo_transmission_sequence": "207",
        "wmo_bbb": None,
        "is_correction_bbb": False,
        "correction_text_evidence": False,
        "product_id": "202604240617-KOKX-CDUS41-CLINYC",
        "raw_sha256": "0" * 64,
        "source_zip": "fixture.zip",
        "source_member": "CLINYC_202604240617.txt",
    }
    kwargs.update(overrides)
    return module.ArchiveIssuance(**kwargs)


# --- A. archive_windows(include_extension=True) ------------------------


def test_include_extension_adds_exactly_one_2026_window_per_city_untouched_otherwise() -> None:
    """The SL-5 window is additive: every pre-SL-5 ``ArchiveWindow`` (same
    dataclass field values) still appears, with the same multiplicity, and
    exactly one new window per city is added.
    """
    from collections import Counter

    module = _load_module()

    base = module.archive_windows()
    extended = module.archive_windows(include_extension=True)

    base_counts = Counter(base)
    extended_counts = Counter(extended)
    removed = base_counts - extended_counts
    added = extended_counts - base_counts

    assert not removed, f"pre-SL-5 windows must be untouched, but lost: {removed}"

    cities = {window.city for window in base}
    assert sum(added.values()) == len(cities)
    for window in added:
        assert window.start == dt.date(2026, 1, 1)
        assert window.end == dt.date(2026, 9, 28)


def test_extension_window_absent_by_default_matching_the_pre_sl5_regression() -> None:
    """Byte-identical to the assertions the pre-SL-5 test file already pins,
    re-asserted here so this file also documents the contract it depends on.
    """
    module = _load_module()

    windows = [w for w in module.archive_windows() if w.cli_location == "NYC"]
    spans = sorted((w.start, w.end) for w in windows)

    assert spans[-2][1] == dt.date(2025, 12, 31)
    assert spans[-1][0] == dt.date(2026, 8, 17)


def test_extension_window_days_span_2026_01_01_through_2026_09_28_inclusive() -> None:
    module = _load_module()

    extended = module.archive_windows(cities=["NYC"], include_extension=True)
    extension = next(w for w in extended if w.start == dt.date(2026, 1, 1))

    days = extension.days()
    assert days[0] == dt.date(2026, 1, 1)
    assert days[-1] == dt.date(2026, 9, 28)
    assert len(days) == (dt.date(2026, 9, 28) - dt.date(2026, 1, 1)).days + 1
    assert len(days) == len(set(days))


# --- B. Absent days are reported, never interpolated -------------------


def test_days_absent_from_the_extension_window_are_reported_not_interpolated() -> None:
    """A day inside the SL-5 window with no admitted product is emitted as
    ``NO_PRODUCT`` and counted in ``missing_days`` -- never silently filled
    from a neighboring day's reading.
    """
    module = _load_module()

    expected_days = (
        dt.date(2026, 2, 1),
        dt.date(2026, 2, 2),
        dt.date(2026, 2, 3),
    )
    issuances = (
        _issuance(module, climate_day=dt.date(2026, 2, 1), tmax_f=40),
        # 2026-02-02 and 2026-02-03 have no archived product at all.
    )

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=expected_days,
    )
    summary = module.coverage_summary(rows)

    assert summary["missing_days"] == ["2026-02-02", "2026-02-03"]
    assert summary["missing_day_count"] == 2
    row_by_day = {row.climate_day: row for row in rows}
    assert row_by_day[dt.date(2026, 2, 2)].status == module.STATUS_NO_PRODUCT
    assert row_by_day[dt.date(2026, 2, 2)].tmax_f is None
    assert row_by_day[dt.date(2026, 2, 3)].status == module.STATUS_NO_PRODUCT
    # The present day is untouched and carries its own real value.
    assert row_by_day[dt.date(2026, 2, 1)].tmax_f == 40


# --- C. final_rows_for_gate: final, latest-revision only ---------------


def test_final_rows_for_gate_excludes_preliminary_only_and_no_product_rows() -> None:
    module = _load_module()

    issuances = (
        _issuance(module, climate_day=dt.date(2026, 4, 23), tmax_f=70),
        _issuance(
            module,
            climate_day=dt.date(2026, 4, 24),
            issuance="PRELIMINARY",
            tmax_f=71,
            issued_at_utc=dt.datetime(2026, 4, 24, 18, 0, tzinfo=dt.UTC),
            product_id="202604241800-KOKX-CDUS41-CLINYC",
            raw_sha256="1" * 64,
        ),
    )
    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(
            dt.date(2026, 4, 23),
            dt.date(2026, 4, 24),
            dt.date(2026, 4, 25),  # NO_PRODUCT
        ),
    )

    gated = module.final_rows_for_gate(rows)

    assert {row.climate_day for row in gated} == {dt.date(2026, 4, 23)}
    assert gated[0].status == module.STATUS_FINAL
    assert gated[0].is_final is True


def test_final_rows_for_gate_never_emits_a_superseded_final_value() -> None:
    """A day with a correction reaches the gate exactly once, carrying the
    SUPERSEDING value -- the superseded 73 never appears in the output.
    """
    module = _load_module()

    issuances = (
        _issuance(module, climate_day=dt.date(2026, 4, 23), tmax_f=73, raw_sha256="a" * 64),
        _issuance(
            module,
            climate_day=dt.date(2026, 4, 23),
            tmax_f=75,
            wmo_bbb="CCA",
            is_correction_bbb=True,
            correction_text_evidence=True,
            issued_at_utc=dt.datetime(2026, 4, 24, 12, 3, tzinfo=dt.UTC),
            product_id="202604241203-KOKX-CDUS41-CLINYC",
            raw_sha256="b" * 64,
        ),
    )
    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(dt.date(2026, 4, 23),),
    )

    gated = module.final_rows_for_gate(rows)

    assert len(gated) == 1
    assert gated[0].tmax_f == 75
    assert gated[0].final_tmax_revised is True
    assert 73 not in {row.tmax_f for row in gated}


def test_final_rows_for_gate_excludes_ambiguous_final_days() -> None:
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(
            _issuance(module, tmax_f=73, raw_sha256="a" * 64),
            _issuance(module, tmax_f=99, raw_sha256="b" * 64, wmo_transmission_sequence="207"),
        ),
        expected_days=(dt.date(2026, 4, 23),),
    )
    assert rows[0].status == module.STATUS_AMBIGUOUS_FINAL

    gated = module.final_rows_for_gate(rows)

    assert gated == ()


def test_final_rows_for_gate_refuses_a_duplicate_final_for_one_station_day() -> None:
    """Structurally unreachable through ``build_truth_rows`` (it groups by
    day before a row is ever built) -- this proves the selector's own
    defense-in-depth guard, not the upstream grouping.
    """
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(_issuance(module, climate_day=dt.date(2026, 4, 23), tmax_f=70),),
        expected_days=(dt.date(2026, 4, 23),),
    )
    duplicate = replace(rows[0])

    with pytest.raises(module.ArchiveSelectionError):
        module.final_rows_for_gate((rows[0], duplicate))


# --- D. main() only opts in to the extension via --include-extension ---


def test_main_only_passes_include_extension_when_the_cli_flag_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``main``'s DEFAULT call to ``archive_windows`` must stay exactly
    ``archive_windows(requested_cities)`` -- no extra keyword, ever -- so
    ``test_main_build_refuses_zip_digest_mismatch_before_any_output_write``
    and ...``_missing_zip_digest_sidecar_entry_...`` in
    ``test_settlement_truth_dataset.py`` (which replace ``archive_windows``
    with a ``cities=None``-only double) keep working byte-unchanged. Only
    ``--include-extension`` reaches the branch that passes
    ``include_extension=True``.
    """
    module = _load_module()
    tmp_path.with_suffix(".sha256").write_text("", encoding="utf-8")

    calls: list[dict[str, Any]] = []

    def fake_archive_windows(
        cities: Any = None, *, include_extension: bool = False
    ) -> tuple[Any, ...]:
        calls.append({"cities": cities, "include_extension": include_extension})
        return ()

    monkeypatch.setattr(module, "archive_windows", fake_archive_windows)

    with pytest.raises(module.SettlementTruthError, match="zero archive windows"):
        module.main(
            ["--cache-dir", str(tmp_path), "--output-dir", str(tmp_path / "out"), "--city", "NYC"]
        )
    assert calls == [{"cities": ("NYC",), "include_extension": False}]

    calls.clear()
    with pytest.raises(module.SettlementTruthError, match="zero archive windows"):
        module.main(
            [
                "--cache-dir",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "out"),
                "--city",
                "NYC",
                "--include-extension",
            ]
        )
    assert calls == [{"cities": ("NYC",), "include_extension": True}]


# --- E. final_rows_for_gate excludes sentinel-tmax final rows ----------


def test_final_rows_for_gate_excludes_final_tmax_sentinel_rows() -> None:
    """A FINAL issuance whose own reading is a missing/trace sentinel sets
    ``status=STATUS_FINAL_TMAX_SENTINEL`` and ``is_final=True`` --
    ``_build_day_row``'s existing, untouched semantics (``is_final`` means a
    FINAL issuance was selected, not that it carries a usable value). The
    gate selector must still refuse it: ``is_final=True`` alone is not
    admission, only ``status == STATUS_FINAL and tmax_f is not None`` is.
    """
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(_issuance(module, climate_day=dt.date(2026, 4, 23), tmax_f=None),),
        expected_days=(dt.date(2026, 4, 23),),
    )

    assert rows[0].status == module.STATUS_FINAL_TMAX_SENTINEL
    assert rows[0].is_final is True  # untouched _build_day_row semantics

    gated = module.final_rows_for_gate(rows)

    assert gated == ()


def test_final_rows_for_gate_admits_a_real_final_alongside_an_excluded_sentinel() -> None:
    """A mixed batch: one ordinary final and one sentinel-tmax final for a
    different day. Only the ordinary final reaches the gate.
    """
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(
            _issuance(module, climate_day=dt.date(2026, 4, 23), tmax_f=70),
            _issuance(
                module,
                climate_day=dt.date(2026, 4, 24),
                tmax_f=None,
                issued_at_utc=dt.datetime(2026, 4, 25, 6, 17, tzinfo=dt.UTC),
                product_id="202604250617-KOKX-CDUS41-CLINYC",
                raw_sha256="c" * 64,
            ),
        ),
        expected_days=(dt.date(2026, 4, 23), dt.date(2026, 4, 24)),
    )

    gated = module.final_rows_for_gate(rows)

    assert {row.climate_day for row in gated} == {dt.date(2026, 4, 23)}
    assert gated[0].tmax_f == 70


# --- F. overlapping windows dedupe through main()'s real merge path ----


def test_overlapping_windows_dedupe_to_one_row_per_day_through_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two ``ArchiveWindow``s for NYC overlap on 2026-04-23; each carries a
    byte-identical transmission for that day in its own cached zip.

    ``main()``'s per-city loop reads BOTH windows and ``.extend()``s their
    issuances into one list before ``build_truth_rows`` is called -- the
    real multi-window merge path, not just the pure ``build_truth_rows``
    function tests exercise elsewhere. Asserting ``total_issuance_count
    == 1`` (not just "exactly one row", which is true by construction
    regardless of dedupe) proves the digest dedupe actually collapsed the
    two identical transmissions rather than merely picking one arbitrarily.
    """
    module = _load_module()
    anchor_bytes = _ANCHOR_PRODUCT_PATH.read_bytes()

    cache_dir = tmp_path / "cache"
    output_dir = tmp_path / "out"

    window_a = module.ArchiveWindow(
        city="NYC",
        cli_location="NYC",
        start=dt.date(2026, 4, 20),
        end=dt.date(2026, 4, 23),
        limit=500,
    )
    window_b = module.ArchiveWindow(
        city="NYC",
        cli_location="NYC",
        start=dt.date(2026, 4, 22),
        end=dt.date(2026, 4, 25),
        limit=500,
    )
    assert window_a.url != window_b.url  # distinct cache entries, overlapping dates

    digests: dict[str, str] = {}
    for window in (window_a, window_b):
        zip_path = module.cache_path_for_url(cache_dir, window.url, suffix=".zip")
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("CLINYC_202604240617.txt", anchor_bytes)
        digests[zip_path.name] = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    lines = [f"{digest}  {name}\n" for name, digest in sorted(digests.items())]
    cache_dir.with_suffix(".sha256").write_text("".join(lines), encoding="utf-8")

    monkeypatch.setattr(module, "archive_windows", lambda cities=None: (window_a, window_b))

    exit_code = module.main(
        ["--cache-dir", str(cache_dir), "--output-dir", str(output_dir), "--city", "NYC"]
    )
    assert exit_code == 0

    import pyarrow.parquet as pq

    records = pq.read_table(output_dir / "settlement_truth.parquet").to_pylist()
    day_records = [r for r in records if r["climate_day"] == dt.date(2026, 4, 23)]

    assert len(day_records) == 1
    assert day_records[0]["total_issuance_count"] == 1
    assert day_records[0]["tmax_f"] == 73
    assert day_records[0]["status"] == module.STATUS_FINAL

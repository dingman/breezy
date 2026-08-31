"""Unit tests for the historical settlement-truth dataset builder.

Covers the pure logic in ``scripts/analysis/settlement_truth_dataset.py``:

* the SETTLEMENT PREDICATE, pinned to the exact boundary case that established
  it (``docs/evidence/venue/polymarket_us/THRESHOLD_SEMANTICS_2026-08-25.md``
  section 4, lines 170-223: an observed 73F settled YES against the
  ``gte72lt73f``-named bucket, refuting the literal strict-``lt`` reading);
* the IEM archive transmission-envelope adapter, which must PRESERVE the real
  WMO transmission sequence rather than rewriting it to ``000``;
* preliminary -> final revision detection and corrected-final supersession;
* honest coverage: a day with no product, or with only a preliminary, is
  emitted as a row with a refusing status, never silently dropped.

One test runs end-to-end over a REAL, committed, digest-verified archive
record: the 2026-04-23 CLINYC final that is itself the THRESHOLD_SEMANTICS
anchor. Everything else is synthetic. No network, no live catalog, no venue.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
import warnings
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"

#: The THRESHOLD_SEMANTICS anchor product: a real IEM AFOS archive record,
#: committed with its digest in `raw/nws/SHA256SUMS.txt`.
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
_ANCHOR_SHA256 = "d8909a8c10e56a265efd584491f640c43c417ed5ad43f38b48e9dd2d409e7249"


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


def _write_zip(path: Path, members: dict[str, str | bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, contents in members.items():
            archive.writestr(name, contents)


def _write_zip_digest_sidecar(cache_dir: Path, entries: dict[str, str]) -> None:
    lines = [f"{digest}  {name}\n" for name, digest in sorted(entries.items())]
    cache_dir.with_suffix(".sha256").write_text("".join(lines), encoding="utf-8")


def _single_window(module: ModuleType) -> Any:
    return module.ArchiveWindow(
        city="NYC",
        cli_location="NYC",
        start=dt.date(2026, 4, 23),
        end=dt.date(2026, 4, 23),
        limit=500,
    )


def _anchor_text_with_sequence_and_tmax(*, sequence: str, tmax_f: int) -> str:
    text = _ANCHOR_PRODUCT_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    lines[0] = f"{sequence} "
    return "\n".join(lines).replace("MAXIMUM         73", f"MAXIMUM         {tmax_f}")


# --- A. THE SETTLEMENT PREDICATE ---------------------------------------
#
# THRESHOLD_SEMANTICS_2026-08-25.md:212-220 --
#   "For two-token weather slugs gte{A}lt{B}f, the settling predicate is:
#        A <= observed <= B        (INCLUSIVE on both bounds)
#    The `lt` token in the slug is venue naming, not the settlement predicate."


def test_seventy_three_settles_yes_in_the_gte72lt73f_bucket() -> None:
    """THRESHOLD_SEMANTICS:173-184 -- the exact boundary case.

    NWS observed high for KNYC on 2026-04-23 was exactly 73F and market
    15806 (`tc-temp-nychigh-2026-04-23-gte72lt73f`) resolved YES. Under the
    literal strict reading the bucket is {72} and it would have resolved NO.
    """
    module = _load_module()

    assert module.settles_yes(73, lower_f=72, upper_f=73) is True
    assert module.settles_yes(72, lower_f=72, upper_f=73) is True


def test_strict_lt_reading_is_refuted_not_merely_unused() -> None:
    module = _load_module()

    # The refuted reading would exclude the upper bound. It must not be
    # reachable through any argument spelling of the public predicate.
    assert module.settles_yes(73, lower_f=72, upper_f=73) is not False
    # Values genuinely outside the closed interval still settle NO.
    assert module.settles_yes(74, lower_f=72, upper_f=73) is False
    assert module.settles_yes(71, lower_f=72, upper_f=73) is False


def test_single_sided_slug_bounds_keep_their_literal_reading() -> None:
    """THRESHOLD_SEMANTICS:222-223 -- `lt66f` = <=65, `gte74f` = >=74."""
    module = _load_module()

    assert module.settles_yes(65, lower_f=None, upper_f=65) is True
    assert module.settles_yes(66, lower_f=None, upper_f=65) is False
    assert module.settles_yes(74, lower_f=74, upper_f=None) is True
    assert module.settles_yes(73, lower_f=74, upper_f=None) is False


def test_captured_2026_04_23_nyc_ladder_tiles_the_integers_without_gap() -> None:
    """THRESHOLD_SEMANTICS:186-208 -- the structural proof, re-asserted.

    Exactly one bucket of the published ladder settles YES for every integer
    reading, and 73 lands in the `gte72lt73f` bucket.
    """
    module = _load_module()

    ladder: tuple[tuple[int | None, int | None], ...] = (
        (None, 65),  # lt66f
        (66, 67),  # gte66lt67f
        (68, 69),  # gte68lt69f
        (70, 71),  # gte70lt71f
        (72, 73),  # gte72lt73f
        (74, None),  # gte74f
    )
    for reading in range(-30, 130):
        winners = [
            index
            for index, (lower, upper) in enumerate(ladder)
            if module.settles_yes(reading, lower_f=lower, upper_f=upper)
        ]
        assert len(winners) == 1, f"reading {reading} matched buckets {winners}"

    assert [
        index
        for index, (lower, upper) in enumerate(ladder)
        if module.settles_yes(73, lower_f=lower, upper_f=upper)
    ] == [4]


def test_interior_bucket_is_two_degrees_wide_and_parity_explicit() -> None:
    module = _load_module()

    assert module.interior_bucket(73, anchor_parity=0) == (72, 73)
    assert module.interior_bucket(72, anchor_parity=0) == (72, 73)
    assert module.interior_bucket(73, anchor_parity=1) == (73, 74)
    assert module.interior_bucket(74, anchor_parity=1) == (73, 74)
    assert module.interior_bucket(-3, anchor_parity=1) == (-3, -2)
    assert module.interior_bucket_slug(72) == "gte72lt73f"


# --- B. THE IEM ARCHIVE TRANSMISSION ENVELOPE --------------------------


def test_archive_member_keeps_its_real_wmo_transmission_sequence() -> None:
    """The `000` rewrite in `split_iem_afos_products` is not reused here.

    `cli_parse.check_structural_allowlist` now accepts a 1-6 digit sequence,
    so the real sequence is provenance that must survive to the parser.
    """
    module = _load_module()

    member = b"207 \nCDUS41 KOKX 240617\nCLINYC\n\nCLIMATE REPORT \n"
    text = module.iem_member_to_product_text(member)

    lines = text.split("\n")
    assert lines[0] == ""
    assert lines[1].strip() == "207"
    assert "000" not in lines[1]
    # Everything from the WMO abbreviated heading onward is byte-identical.
    assert text[1:] == member.decode("utf-8")


def test_archive_product_id_is_built_from_member_name_and_wmo_heading() -> None:
    module = _load_module()

    text = module.iem_member_to_product_text(
        b"207 \nCDUS41 KOKX 240617\nCLINYC\n\nCLIMATE REPORT \n"
    )
    assert (
        module.iem_product_id("CLINYC_202604240617.txt", text) == "202604240617-KOKX-CDUS41-CLINYC"
    )


def test_issuance_stores_wmo_transmission_sequence() -> None:
    module = _load_module()

    from breezy.registry.sites import default_registry

    site = default_registry().settlement_site("polymarket_us", "NYC")
    issuance = module.issuance_from_member(
        city="NYC",
        site=site,
        member_bytes=_ANCHOR_PRODUCT_PATH.read_bytes(),
        member_name="CLINYC_202604240617.txt",
        source_zip=_ANCHOR_PRODUCT_PATH.name,
    )

    assert issuance.wmo_transmission_sequence == "207"


# --- C. PRELIMINARY vs FINAL, AND SUPERSESSION -------------------------


def test_final_wins_and_a_differing_preliminary_is_recorded() -> None:
    module = _load_module()

    issuances = (
        _issuance(
            module,
            issuance="PRELIMINARY",
            tmax_f=72,
            issued_at_utc=dt.datetime(2026, 4, 23, 20, 38, tzinfo=dt.UTC),
            product_id="202604232038-KOKX-CDUS41-CLINYC",
            raw_sha256="1" * 64,
        ),
        _issuance(module, tmax_f=73),
    )

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(dt.date(2026, 4, 23),),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.status == module.STATUS_FINAL
    assert row.is_final is True
    assert row.tmax_f == 73
    assert row.preliminary_tmax_f == 72
    assert row.preliminary_differed is True
    assert row.total_issuance_count == 2
    assert row.final_issuance_count == 1


def test_matching_preliminary_records_no_revision() -> None:
    module = _load_module()

    issuances = (
        _issuance(
            module,
            issuance="PRELIMINARY",
            tmax_f=73,
            issued_at_utc=dt.datetime(2026, 4, 23, 20, 38, tzinfo=dt.UTC),
            raw_sha256="1" * 64,
        ),
        _issuance(module, tmax_f=73),
    )

    row = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(dt.date(2026, 4, 23),),
    )[0]

    assert row.preliminary_tmax_f == 73
    assert row.preliminary_differed is False
    assert row.had_correction is False


def test_corrected_final_supersedes_the_first_final() -> None:
    module = _load_module()

    issuances = (
        _issuance(module, tmax_f=73, raw_sha256="a" * 64),
        _issuance(
            module,
            tmax_f=75,
            wmo_bbb="CCA",
            is_correction_bbb=True,
            correction_text_evidence=True,
            issued_at_utc=dt.datetime(2026, 4, 24, 12, 3, tzinfo=dt.UTC),
            product_id="202604241203-KOKX-CDUS41-CLINYC",
            raw_sha256="b" * 64,
        ),
    )

    row = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(dt.date(2026, 4, 23),),
    )[0]

    assert row.tmax_f == 75
    assert row.final_issuance_count == 2
    assert row.final_tmax_revised is True
    assert row.final_is_correction_bbb is True
    assert row.had_correction is True
    assert row.product_id == "202604241203-KOKX-CDUS41-CLINYC"
    assert row.revision_seq == 2
    assert row.wmo_transmission_sequence == "207"


def test_identical_retransmission_dedupes_on_digest_not_on_product_id() -> None:
    module = _load_module()

    issuances = (
        _issuance(module, raw_sha256="a" * 64),
        _issuance(
            module,
            raw_sha256="a" * 64,
            product_id="202604240900-KOKX-CDUS41-CLINYC",
            issued_at_utc=dt.datetime(2026, 4, 24, 9, 0, tzinfo=dt.UTC),
        ),
    )

    row = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(dt.date(2026, 4, 23),),
    )[0]

    assert row.total_issuance_count == 1
    assert row.final_issuance_count == 1
    assert row.final_tmax_revised is False


def test_ambiguous_duplicate_finals_are_quarantined_not_selected_by_archive_order() -> None:
    module = _load_module()

    refusals: list[Any] = []
    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(
            _issuance(module, tmax_f=73, raw_sha256="a" * 64),
            _issuance(
                module,
                tmax_f=99,
                raw_sha256="b" * 64,
                wmo_transmission_sequence="207",
            ),
        ),
        expected_days=(dt.date(2026, 4, 23),),
        selection_refusals=refusals,
    )

    assert rows[0].status == module.STATUS_AMBIGUOUS_FINAL
    assert rows[0].tmax_f is None
    assert rows[0].settlement_grade_including_spillover is False
    assert rows[0].settlement_grade_within_window is False
    assert [(refusal.error_type, refusal.source_member) for refusal in refusals] == [
        ("ArchiveSelectionError", "CLINYC_202604240617.txt")
    ]
    assert "differing final tmax values" in refusals[0].message


# --- D. HONEST COVERAGE: NOTHING IS SILENTLY DROPPED -------------------


def test_day_with_only_a_preliminary_is_not_settlement_grade() -> None:
    module = _load_module()

    issuances = (
        _issuance(
            module,
            issuance="PRELIMINARY",
            tmax_f=72,
            issued_at_utc=dt.datetime(2026, 4, 23, 20, 38, tzinfo=dt.UTC),
        ),
    )

    row = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(dt.date(2026, 4, 23),),
    )[0]

    assert row.status == module.STATUS_PRELIMINARY_ONLY
    assert row.is_final is False
    assert row.tmax_f is None
    assert row.preliminary_tmax_f == 72


def test_expected_day_with_no_product_is_emitted_not_dropped() -> None:
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(_issuance(module),),
        expected_days=(dt.date(2026, 4, 22), dt.date(2026, 4, 23)),
    )

    assert [row.climate_day for row in rows] == [dt.date(2026, 4, 22), dt.date(2026, 4, 23)]
    assert rows[0].status == module.STATUS_NO_PRODUCT
    assert rows[0].tmax_f is None
    assert rows[1].status == module.STATUS_FINAL


def test_final_with_a_sentinel_tmax_refuses_rather_than_imputing() -> None:
    module = _load_module()

    row = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(_issuance(module, tmax_f=None, tmax_flag="M"),),
        expected_days=(dt.date(2026, 4, 23),),
    )[0]

    assert row.status == module.STATUS_FINAL_TMAX_SENTINEL
    assert row.tmax_f is None
    assert row.is_final is True


def test_observed_day_outside_the_expected_grid_is_still_emitted() -> None:
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(_issuance(module, climate_day=dt.date(2026, 4, 25)),),
        expected_days=(dt.date(2026, 4, 23),),
    )

    days = {row.climate_day: row for row in rows}
    assert set(days) == {dt.date(2026, 4, 23), dt.date(2026, 4, 25)}
    assert days[dt.date(2026, 4, 25)].within_expected_window is False
    assert days[dt.date(2026, 4, 23)].within_expected_window is True
    assert days[dt.date(2026, 4, 25)].settlement_grade_including_spillover is True
    assert days[dt.date(2026, 4, 25)].settlement_grade_within_window is False


def test_coverage_summary_counts_every_status() -> None:
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(_issuance(module),),
        expected_days=(dt.date(2026, 4, 22), dt.date(2026, 4, 23)),
    )
    summary = module.coverage_summary(rows)

    assert summary["rows"] == 2
    assert summary["settlement_grade_rows_within_window"] == 1
    assert summary["settlement_grade_rows_including_spillover"] == 1
    assert summary["status_counts"][module.STATUS_NO_PRODUCT] == 1
    assert summary["missing_days"] == ["2026-04-22"]


def test_coverage_summary_labels_spillover_and_within_window_statistics_separately() -> None:
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(
            _issuance(module, tmax_f=73),
            _issuance(
                module,
                climate_day=dt.date(2026, 4, 25),
                tmax_f=81,
                raw_sha256="1" * 64,
            ),
        ),
        expected_days=(dt.date(2026, 4, 23),),
    )
    summary = module.coverage_summary(rows)

    assert summary["settlement_grade_rows_within_window"] == 1
    assert summary["settlement_grade_rows_including_spillover"] == 2
    assert summary["outside_expected_window_settlement_grade_rows"] == 1
    assert "settlement_grade_rows" not in summary


# --- E. REAL ARCHIVE RECORD, END TO END --------------------------------


def test_real_committed_archive_record_settles_the_threshold_semantics_case() -> None:
    """The 2026-04-23 CLINYC final, from bytes on disk to bucket outcome."""
    module = _load_module()

    from breezy.registry.sites import default_registry

    member_bytes = _ANCHOR_PRODUCT_PATH.read_bytes()
    assert hashlib.sha256(member_bytes).hexdigest() == _ANCHOR_SHA256

    site = default_registry().settlement_site("polymarket_us", "NYC")
    issuance = module.issuance_from_member(
        city="NYC",
        site=site,
        member_bytes=member_bytes,
        member_name="CLINYC_202604240617.txt",
        source_zip=_ANCHOR_PRODUCT_PATH.name,
    )

    assert issuance.climate_day == dt.date(2026, 4, 23)
    assert issuance.issuance == "FINAL"
    assert issuance.tmax_f == 73
    assert issuance.tmin_f == 45
    assert issuance.tavg_f == 59
    assert issuance.is_correction_bbb is False
    assert issuance.raw_sha256 == _ANCHOR_SHA256
    assert issuance.product_id == "202604240617-KOKX-CDUS41-CLINYC"

    row = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(issuance,),
        expected_days=(dt.date(2026, 4, 23),),
    )[0]

    assert row.status == module.STATUS_FINAL
    assert row.tmax_f == 73
    assert row.raw_sha256 == _ANCHOR_SHA256

    # And the market that actually resolved YES against this reading.
    assert module.settles_yes(row.tmax_f, lower_f=72, upper_f=73) is True


def test_digest_mismatch_refuses_before_the_value_is_used() -> None:
    module = _load_module()

    from breezy.registry.sites import default_registry

    site = default_registry().settlement_site("polymarket_us", "NYC")
    member_bytes = _ANCHOR_PRODUCT_PATH.read_bytes()

    with pytest.raises(module.ArchiveDigestError):
        module.issuance_from_member(
            city="NYC",
            site=site,
            member_bytes=member_bytes,
            member_name="CLINYC_202604240617.txt",
            source_zip=_ANCHOR_PRODUCT_PATH.name,
            expected_sha256="f" * 64,
        )


def test_main_build_refuses_zip_digest_mismatch_before_any_output_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()

    cache_dir = tmp_path / "cache"
    output_dir = tmp_path / "out"
    window = _single_window(module)
    zip_path = module.cache_path_for_url(cache_dir, window.url, suffix=".zip")
    _write_zip(zip_path, {"CLINYC_202604240617.txt": _ANCHOR_PRODUCT_PATH.read_bytes()})
    _write_zip_digest_sidecar(cache_dir, {zip_path.name: "f" * 64})
    monkeypatch.setattr(module, "archive_windows", lambda cities=None: (window,))

    with pytest.raises(module.ArchiveDigestError):
        module.main(
            ["--cache-dir", str(cache_dir), "--output-dir", str(output_dir), "--city", "NYC"]
        )

    assert not output_dir.exists()


def test_main_build_refuses_missing_zip_digest_sidecar_entry_before_any_output_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()

    cache_dir = tmp_path / "cache"
    output_dir = tmp_path / "out"
    window = _single_window(module)
    zip_path = module.cache_path_for_url(cache_dir, window.url, suffix=".zip")
    _write_zip(zip_path, {"CLINYC_202604240617.txt": _ANCHOR_PRODUCT_PATH.read_bytes()})
    _write_zip_digest_sidecar(cache_dir, {})
    monkeypatch.setattr(module, "archive_windows", lambda cities=None: (window,))

    with pytest.raises(module.ArchiveDigestError):
        module.main(
            ["--cache-dir", str(cache_dir), "--output-dir", str(output_dir), "--city", "NYC"]
        )

    assert not output_dir.exists()


def test_wrong_station_product_is_refused_not_relabelled() -> None:
    module = _load_module()

    from breezy.registry.sites import default_registry

    site = default_registry().settlement_site("polymarket_us", "SFO")
    member_bytes = _ANCHOR_PRODUCT_PATH.read_bytes()

    with pytest.raises(module.ArchiveRefusalError):
        module.issuance_from_member(
            city="SFO",
            site=site,
            member_bytes=member_bytes,
            member_name="CLINYC_202604240617.txt",
            source_zip=_ANCHOR_PRODUCT_PATH.name,
        )


# --- F. ARCHIVE READING HAZARDS ----------------------------------------


def test_duplicate_zip_member_names_are_both_read(tmp_path: Path) -> None:
    """IEM zips carry duplicate member names; `namelist()` loses one.

    `ZipFile.read(name)` resolves a duplicated name to the LAST entry, so a
    name-keyed reader silently drops one of two distinct transmissions. 21
    duplicated names exist in the held corpus.
    """
    module = _load_module()

    from breezy.registry.sites import default_registry

    original = _ANCHOR_PRODUCT_PATH.read_text(encoding="utf-8")
    altered = original.replace("207 ", "208 ", 1).replace(
        "MAXIMUM         73", "MAXIMUM         75"
    )
    assert altered != original

    zip_path = tmp_path / "duplicates.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("CLINYC_202604240617.txt", original)
            archive.writestr("CLINYC_202604240617.txt", altered)

    site = default_registry().settlement_site("polymarket_us", "NYC")
    issuances, refusals = module.read_window_issuances(zip_path=zip_path, city="NYC", site=site)

    assert refusals == ()
    assert sorted(issuance.tmax_f for issuance in issuances) == [73, 75]

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(dt.date(2026, 4, 23),),
    )

    assert rows[0].tmax_f == 75
    assert rows[0].raw_sha256 == hashlib.sha256(altered.encode("utf-8")).hexdigest()
    assert rows[0].source_member == "CLINYC_202604240617.txt"
    assert rows[0].wmo_transmission_sequence == "208"


def test_ambiguous_duplicate_zip_member_finals_are_quarantined_on_selection(
    tmp_path: Path,
) -> None:
    module = _load_module()

    from breezy.registry.sites import default_registry

    truthful = _anchor_text_with_sequence_and_tmax(sequence="207", tmax_f=73)
    forged = _anchor_text_with_sequence_and_tmax(sequence="207", tmax_f=99)
    assert truthful != forged

    zip_path = tmp_path / "duplicates.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("CLINYC_202604240617.txt", truthful)
            archive.writestr("CLINYC_202604240617.txt", forged)

    site = default_registry().settlement_site("polymarket_us", "NYC")
    issuances, refusals = module.read_window_issuances(zip_path=zip_path, city="NYC", site=site)
    assert refusals == ()

    selection_refusals: list[Any] = []
    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=issuances,
        expected_days=(dt.date(2026, 4, 23),),
        selection_refusals=selection_refusals,
    )

    assert rows[0].status == module.STATUS_AMBIGUOUS_FINAL
    assert rows[0].tmax_f is None
    assert len(selection_refusals) == 1
    assert selection_refusals[0].error_type == "ArchiveSelectionError"


def test_zip_member_size_cap_refuses_before_decompression(tmp_path: Path) -> None:
    module = _load_module()

    from breezy.registry.sites import default_registry

    zip_path = tmp_path / "oversized.zip"
    _write_zip(
        zip_path,
        {"CLINYC_202604240617.txt": b"0" * (module.MAX_ARCHIVE_MEMBER_BYTES + 1)},
    )

    site = default_registry().settlement_site("polymarket_us", "NYC")
    issuances, refusals = module.read_window_issuances(zip_path=zip_path, city="NYC", site=site)

    assert issuances == ()
    assert len(refusals) == 1
    assert refusals[0].error_type == "ArchiveMemberSafetyError"
    assert "decompressed size" in refusals[0].message


def test_zip_member_compression_ratio_cap_refuses_before_decompression(tmp_path: Path) -> None:
    module = _load_module()

    from breezy.registry.sites import default_registry

    zip_path = tmp_path / "ratio.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CLINYC_202604240617.txt", b"0" * module.MAX_ARCHIVE_MEMBER_BYTES)

    site = default_registry().settlement_site("polymarket_us", "NYC")
    issuances, refusals = module.read_window_issuances(zip_path=zip_path, city="NYC", site=site)

    assert issuances == ()
    assert len(refusals) == 1
    assert refusals[0].error_type == "ArchiveMemberSafetyError"
    assert "compression ratio" in refusals[0].message


def test_dataset_round_trips_through_parquet_and_csv(tmp_path: Path) -> None:
    module = _load_module()

    rows = module.build_truth_rows(
        city="NYC",
        station="NYC",
        issuances=(_issuance(module),),
        expected_days=(dt.date(2026, 4, 22), dt.date(2026, 4, 23)),
    )
    paths = module.write_dataset(rows, tmp_path)

    import csv as _csv

    import pyarrow.parquet as pq

    table = pq.read_table(paths["parquet"])
    assert table.num_rows == 2
    assert table.column("tmax_f").to_pylist() == [None, 73]
    assert table.column("status").to_pylist() == [
        module.STATUS_NO_PRODUCT,
        module.STATUS_FINAL,
    ]
    assert table.column("settlement_grade_within_window").to_pylist() == [False, True]
    assert table.column("settlement_grade_including_spillover").to_pylist() == [False, True]
    assert table.column("wmo_transmission_sequence").to_pylist() == [None, "207"]
    assert table.column("interior_bucket_slug_even").to_pylist() == [None, "gte72lt73f"]
    assert table.column("interior_bucket_slug_odd").to_pylist() == [None, "gte73lt74f"]

    with paths["csv"].open(encoding="utf-8", newline="") as handle:
        csv_rows = list(_csv.DictReader(handle))
    assert [row["climate_day"] for row in csv_rows] == ["2026-04-22", "2026-04-23"]
    assert csv_rows[1]["raw_sha256"] == "0" * 64


def test_declared_archive_windows_are_not_contiguous() -> None:
    """A gap in coverage is a fact the caller must be able to see.

    The held cache stops at 2025-12-31 and resumes 2026-08-16/17. Nothing may
    interpolate across it.
    """
    module = _load_module()

    windows = [w for w in module.archive_windows() if w.cli_location == "NYC"]
    spans = sorted((w.start, w.end) for w in windows)
    assert spans[-2][1] == dt.date(2025, 12, 31)
    assert spans[-1][0] == dt.date(2026, 8, 17)
    assert (spans[-1][0] - spans[-2][1]).days > 200


def test_station_substitution_is_refused_when_building_rows() -> None:
    module = _load_module()

    with pytest.raises(module.SettlementTruthError):
        module.build_truth_rows(
            city="SFO",
            station="SFO",
            issuances=(_issuance(module, station="NYC"),),
            expected_days=(dt.date(2026, 4, 23),),
        )


def test_invalid_city_refuses_before_any_output_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()

    def fail_write(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("write path must not be reached for an invalid city")

    monkeypatch.setattr(module, "write_dataset", fail_write)
    with pytest.raises(module.SettlementTruthError, match="unknown --city"):
        module.main(
            [
                "--cache-dir",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "out"),
                "--city",
                "BOGUS",
            ]
        )

    assert not (tmp_path / "out").exists()


def test_output_dir_inside_live_catalog_or_archive_is_refused_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()

    def fail_write(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("write path must not be reached for a fenced output dir")

    monkeypatch.setattr(module, "write_dataset", fail_write)
    monkeypatch.setattr(module, "DEFAULT_LIVE_CATALOG_DIR", tmp_path / "catalog")
    monkeypatch.setattr(module, "DEFAULT_ARCHIVE_ROOT_DIR", tmp_path / "archive")

    with pytest.raises(module.SettlementTruthError, match="live catalog"):
        module.main(
            [
                "--cache-dir",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "catalog" / "settlement-truth"),
                "--city",
                "NYC",
            ]
        )

    with pytest.raises(module.SettlementTruthError, match="archive cache"):
        module.main(
            [
                "--cache-dir",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "archive" / "settlement-truth"),
                "--city",
                "NYC",
            ]
        )

"""MAKER-S2 second look, unit C6b: the opt-in maker s2b TEXT window of the truth dataset.

Plan delta ``docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3_delta_coordinator.md``
section 1. The window is read from a cached ``.txt`` (the text-only IEM transport cannot
carry a zip); the ``.zip`` reader and every default stay unchanged.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
import zipfile
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pyarrow.parquet as pq
import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
ANALYSIS_DIR: Final[Path] = REPO_ROOT / "scripts" / "analysis"
LAX_PRODUCT: Final[Path] = REPO_ROOT / "tests/fixtures/nws/lax_final_2026-08-21/product.txt"
ANCHOR_PATH: Final[Path] = (
    REPO_ROOT
    / "docs/evidence/venue/polymarket_us/raw/nws/CLINYC_202604240617-KOKX-CDUS41-CLINYC.txt"
)
MAKER: Final[tuple[str, ...]] = ("LAX", "MDW", "MIA", "SFO")


def _load_module() -> ModuleType:
    if str(ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(ANALYSIS_DIR))
    path = ANALYSIS_DIR / "settlement_truth_dataset.py"
    spec = importlib.util.spec_from_file_location("settlement_truth_dataset", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def lax_text_body(days: list[dt.date], *, tmax: int = 83) -> str:
    template = LAX_PRODUCT.read_text(encoding="utf-8")
    chunks: list[str] = []
    for day in days:
        following = day + dt.timedelta(days=1)
        text = (
            template.replace("AUGUST 21 2026", day.strftime("%B %-d %Y").upper())
            .replace("AUGUST 22 2026", following.strftime("%B %-d %Y").upper())
            .replace(
                "SAT AUG 22 2026",
                f"{following.strftime('%a').upper()} {following.strftime('%b %-d %Y').upper()}",
            )
            .replace("MAXIMUM         83", f"MAXIMUM         {tmax:2d}")
        )
        chunks.append("\x01" + text + "\x03")
    return "".join(chunks)


def s2b_windows(module: ModuleType, cities: Any = None) -> list[Any]:
    base = Counter(module.archive_windows(cities))
    return list((Counter(module.archive_windows(cities, include_maker_s2b=True)) - base).elements())


def test_maker_s2b_window_is_opt_in_maker_only_and_defaults_unchanged() -> None:
    module = _load_module()
    default = module.archive_windows()

    assert module._MAKER_S2B_WINDOW_START == dt.date(2026, 9, 29)
    assert module._MAKER_S2B_WINDOW_END == dt.date(2026, 11, 15)
    assert not any(getattr(window, "text", False) for window in default)
    assert default == module.archive_windows(include_extension=False)

    added = s2b_windows(module)
    assert sorted(window.city for window in added) == sorted(MAKER)  # never NYC
    for window in added:
        assert (window.start, window.end, window.limit) == (
            dt.date(2026, 9, 29),
            dt.date(2026, 11, 15),
            3_000,
        )
        assert window.text is True
        assert "fmt=text" in window.url and "fmt=zip" not in window.url
    # Every pre-existing window is untouched with the same multiplicity.
    all_with = Counter(module.archive_windows(include_maker_s2b=True))
    assert not (Counter(default) - all_with)
    # Combining with the SL-5 extension stays additive.
    both = Counter(module.archive_windows(include_extension=True, include_maker_s2b=True))
    assert not (Counter(module.archive_windows(include_extension=True)) - both)
    # A non-maker city selection yields no s2b window at all.
    assert s2b_windows(module, ["NYC"]) == []
    # The cached path of a text window is a URL-hashed .txt; the zip windows stay .zip.
    window = added[0]
    with pytest.raises(module.ArchiveCoverageError, match=r"\.txt"):
        module.window_zip_path(Path("/nonexistent-cache"), window)
    assert module.parse_args([]).include_maker_s2b_window is False


def test_dataset_text_window_emits_rows_for_block_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_module()
    cache = tmp_path / "cache"
    cache.mkdir()
    window = next(w for w in s2b_windows(module, ["LAX"]))
    block = [dt.date(2026, 10, 14) + dt.timedelta(days=n) for n in range(7)]
    body = lax_text_body(block, tmax=77)
    path = module.cache_path_for_url(cache, window.url, ".txt")
    path.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cache.with_suffix(".sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")

    real = module.archive_windows
    monkeypatch.setattr(
        module,
        "archive_windows",
        lambda cities=None, **kw: tuple(w for w in real(cities, **kw) if w.text),
    )
    out = tmp_path / "maker_stage0_inputs" / "cross_check_s2b"

    code = module.main(
        [
            "--cache-dir", str(cache), "--output-dir", str(out),
            "--city", "LAX", "--include-maker-s2b-window",
        ]
    )  # fmt: skip

    assert code == 0
    table = pq.read_table(out / "settlement_truth.parquet").to_pylist()
    by_day = {row["climate_day"]: row for row in table}
    for day in block:
        row = by_day[day]
        assert (row["station"], row["status"], row["tmax_f"], row["is_final"]) == (
            "LAX",
            "FINAL",
            77,
            True,
        )
        assert row["source_zip"] == path.name
        assert row["product_id"].endswith("-KLOX-CDUS46-CLILAX")
    # Days the text holds nothing for are reported, never dropped or interpolated.
    assert by_day[dt.date(2026, 10, 13)]["status"] == "NO_PRODUCT"
    assert by_day[dt.date(2026, 11, 15)]["status"] == "NO_PRODUCT"
    assert len(table) == (dt.date(2026, 11, 15) - dt.date(2026, 9, 29)).days + 1


def test_zip_reader_path_byte_identical(tmp_path: Path) -> None:
    module = _load_module()
    anchor = ANCHOR_PATH.read_bytes()
    zip_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("CLINYC_202604240617.txt", anchor)
    site = module.default_registry().settlement_site(module.VENUE, "NYC")
    expected = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    issuances, refusals = module.read_window_issuances(
        zip_path=zip_path, city="NYC", site=site, expected_zip_sha256=expected
    )

    assert refusals == ()
    (issuance,) = issuances
    assert (issuance.station, issuance.climate_day, issuance.issuance, issuance.tmax_f) == (
        "NYC",
        dt.date(2026, 4, 23),
        "FINAL",
        73,
    )
    assert issuance.raw_sha256 == hashlib.sha256(anchor).hexdigest()
    assert issuance.source_zip == "fixture.zip"
    assert issuance.source_member == "CLINYC_202604240617.txt"
    assert issuance.product_id == "202604240617-KOKX-CDUS41-CLINYC"
    assert issuance.wmo_transmission_sequence == "207"
    assert issuance.issued_at_utc == dt.datetime(2026, 4, 24, 6, 17, tzinfo=dt.UTC)
    # A bad zip digest is still refused before any member is read.
    with pytest.raises(module.ArchiveDigestError):
        module.read_window_issuances(
            zip_path=zip_path, city="NYC", site=site, expected_zip_sha256="0" * 64
        )


@pytest.mark.parametrize(
    "extra",
    [[], ["--city", "NYC"], ["--city", "LAX", "--city", "NYC"], ["--city", "ZZZ"]],
)
def test_s2b_run_without_maker_only_cities_refused(tmp_path: Path, extra: list[str]) -> None:
    module = _load_module()
    out = tmp_path / "out"

    with pytest.raises(module.SettlementTruthError, match="maker"):
        module.main(["--output-dir", str(out), "--include-maker-s2b-window", *extra])

    assert not out.exists()
    # An explicit output dir is also mandatory: the shared dataset is never the target.
    with pytest.raises(module.SettlementTruthError, match="output-dir"):
        module.main(["--include-maker-s2b-window", "--city", "LAX"])
    with pytest.raises(module.SettlementTruthError, match="output-dir"):
        module.main(
            [
                "--include-maker-s2b-window",
                "--city", "LAX",
                "--output-dir", str(module.DEFAULT_OUTPUT_DIR),
            ]
        )  # fmt: skip

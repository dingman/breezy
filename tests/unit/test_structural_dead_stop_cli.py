"""RED-first tests for the structural-dead-stop CLI (I3 "d0 plumbing").

Spec: `docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` section 3.0(i) and
the "d0 plumbing" / "the wrapper reads ONE file" / "`fetch_end` and day one
(R3)" / "Absent depth root" bullets. LESSON L-28: a helper's default
arguments are part of the population -- the manifest window must be passed
explicitly, never left to `count_covered_listed_station_days_from_catalog`'s
own defaults.

Covers ONLY the CLI surface (`_parse_args`, `main`, the new `--output` JSON
helper). The pure functions (`structural_dead`, `covered_listed_station_days`)
are covered by `tests/unit/test_structural_dead_stop.py` and are UNCHANGED
here -- this module reuses that file's `importlib.util` loader idiom rather
than re-declaring it.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
_REAL_MANIFEST = _REPO_ROOT / "deploy" / "families" / "pm_us_crh_v2.json"


def _load_module(name: str) -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    path = _SCRIPTS_ANALYSIS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sds_mod() -> ModuleType:
    return _load_module("structural_dead_stop")


def _make_depth_root(tmp_path: Path, *, city: str, day: dt.date) -> Path:
    """A quote-tape catalog root with one 45-minute-covered station-day."""
    catalog_root = tmp_path / "catalog"
    depth_root = catalog_root / "data" / "order_book_depths"
    token = f"tc-temp-{city.lower()}high-{day.isoformat()}-0"
    (depth_root / token).mkdir(parents=True)
    return catalog_root


def _registered_manifest_fixture(tmp_path: Path, *, d0: str, stations: list[str]) -> Path:
    """A REGISTERED manifest shaped exactly like `pm_us_crh_v2.json` (never a fabricated sha)."""
    payload = {
        "family_id": "test_fixture_family",
        "venue": "polymarket_us",
        "trial_id_prefix": "current_rung_hold/trial/",
        "d0_climate_day": d0,
        "boundary_artefact_path": "deploy/families/gs_boundary_test_fixture.json",
        "boundary_inputs_sha256": "1" * 64,
        "stations": stations,
        "status": "REGISTERED",
    }
    path = tmp_path / "test_fixture_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _draft_manifest_fixture(tmp_path: Path) -> Path:
    payload = {
        "family_id": "test_fixture_family",
        "venue": "polymarket_us",
        "trial_id_prefix": "current_rung_hold/trial/",
        "d0_climate_day": "2026-09-05",
        "boundary_artefact_path": "deploy/families/gs_boundary_test_fixture.json",
        "boundary_inputs_sha256": "0" * 64,
        "stations": ["LAX"],
        "status": "DRAFT_NOT_REGISTERED",
    }
    path = tmp_path / "draft_manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# (i) main() FORWARDS the manifest's fetch_start/cities to the counter --
# a silent no-op is exactly the manufactured-KILL bug this flag exists to fix
# ---------------------------------------------------------------------------


def test_family_manifest_forwards_fetch_start_and_cities_to_the_counter(
    sds_mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _registered_manifest_fixture(tmp_path, d0="2026-09-05", stations=["LAX", "MDW"])
    catalog_root = _make_depth_root(tmp_path, city="LAX", day=dt.date(2026, 9, 5))

    captured: dict[str, object] = {}

    def _spy(*, catalog_root: Path, cities, fetch_start, fetch_end):
        captured["cities"] = tuple(cities)
        captured["fetch_start"] = fetch_start
        captured["fetch_end"] = fetch_end
        return 0

    monkeypatch.setattr(sds_mod, "count_covered_listed_station_days_from_catalog", _spy)

    exit_code = sds_mod.main(
        [
            "--catalog-root",
            str(catalog_root),
            "--family-manifest",
            str(manifest_path),
        ]
    )

    assert exit_code == 0
    assert captured["fetch_start"] == dt.date(2026, 9, 5)
    assert captured["cities"] == ("LAX", "MDW")


def test_without_family_manifest_the_module_defaults_still_forward(
    sds_mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(vii) defaults path: no `--family-manifest` -> module defaults forwarded."""
    catalog_root = _make_depth_root(tmp_path, city="LAX", day=dt.date(2026, 8, 30))

    captured: dict[str, object] = {}

    def _spy(*, catalog_root: Path, cities, fetch_start, fetch_end):
        captured["cities"] = tuple(cities)
        captured["fetch_start"] = fetch_start
        captured["fetch_end"] = fetch_end
        return 0

    monkeypatch.setattr(sds_mod, "count_covered_listed_station_days_from_catalog", _spy)

    exit_code = sds_mod.main(["--catalog-root", str(catalog_root)])

    assert exit_code == 0
    assert captured["fetch_start"] == sds_mod.ASOS_FETCH_START
    assert captured["cities"] == sds_mod.DENSE_STATIONS
    assert captured["fetch_end"] == sds_mod.ASOS_FETCH_END


# ---------------------------------------------------------------------------
# (ii) the --output JSON: exactly six keys, sorted, indent 2, and the plan's
# pinned sed expressions extract count/fetch_start from it
# ---------------------------------------------------------------------------


def test_output_json_has_exactly_six_sorted_keys_indent_2(
    sds_mod: ModuleType, tmp_path: Path
) -> None:
    day = dt.date(2026, 9, 5)
    catalog_root = _make_depth_root(tmp_path, city="LAX", day=day)
    manifest_path = _registered_manifest_fixture(tmp_path, d0=day.isoformat(), stations=["LAX"])
    output_path = tmp_path / "out.json"

    exit_code = sds_mod.main(
        [
            "--catalog-root",
            str(catalog_root),
            "--family-manifest",
            str(manifest_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    text = output_path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert set(payload) == {
        "count",
        "depth_root_present",
        "fetch_end",
        "fetch_start",
        "manifest_sha256",
        "stations",
    }
    assert isinstance(payload["count"], int)
    assert isinstance(payload["depth_root_present"], bool)
    assert isinstance(payload["manifest_sha256"], str)
    assert isinstance(payload["stations"], list)

    # indent=2, sort_keys=True -> deterministic byte shape
    reserialized = json.dumps(payload, indent=2, sort_keys=True)
    assert text == reserialized


def test_pinned_sed_expressions_extract_count_and_fetch_start(
    sds_mod: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact `sed -nE` expressions pinned in plan section 3.0(i).

    The counter is stubbed to a known count -- this test is about the JSON
    shape and the wrapper's extraction expressions, not the real quote-tape
    parquet reader (covered by test_structural_dead_stop.py's own tests).
    """
    day = dt.date(2026, 9, 5)
    catalog_root = _make_depth_root(tmp_path, city="LAX", day=day)
    manifest_path = _registered_manifest_fixture(tmp_path, d0=day.isoformat(), stations=["LAX"])
    output_path = tmp_path / "out.json"

    monkeypatch.setattr(
        sds_mod,
        "count_covered_listed_station_days_from_catalog",
        lambda **_kwargs: 1,
    )

    exit_code = sds_mod.main(
        [
            "--catalog-root",
            str(catalog_root),
            "--family-manifest",
            str(manifest_path),
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0

    count_result = subprocess.run(
        ["sed", "-nE", r's/^  "count": ([0-9]+),?$/\1/p', str(output_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    fetch_start_result = subprocess.run(
        [
            "sed",
            "-nE",
            r's/^  "fetch_start": "([0-9]{4}-[0-9]{2}-[0-9]{2})",?$/\1/p',
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert count_result.stdout.strip() != ""
    assert int(count_result.stdout.strip()) == 1
    assert fetch_start_result.stdout.strip() == "2026-09-05"


# ---------------------------------------------------------------------------
# (iii) inverted day-one range -> count 0, no raise
# ---------------------------------------------------------------------------


def test_inverted_fetch_range_counts_zero_and_does_not_raise(
    sds_mod: ModuleType, tmp_path: Path
) -> None:
    catalog_root = _make_depth_root(tmp_path, city="LAX", day=dt.date(2026, 8, 30))
    # d0 in the far future relative to ASOS_FETCH_END (today) -> inverted range
    manifest_path = _registered_manifest_fixture(tmp_path, d0="2099-01-01", stations=["LAX"])
    output_path = tmp_path / "out.json"

    exit_code = sds_mod.main(
        [
            "--catalog-root",
            str(catalog_root),
            "--family-manifest",
            str(manifest_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["count"] == 0


# ---------------------------------------------------------------------------
# (iv) absent depth root -> count 0 / depth_root_present false / exit 0;
# absent catalog root parent -> non-zero
# ---------------------------------------------------------------------------


def test_absent_depth_root_is_conservative_count_zero_exit_zero(
    sds_mod: ModuleType, tmp_path: Path
) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()  # exists, but no data/order_book_depths under it
    output_path = tmp_path / "out.json"

    exit_code = sds_mod.main(["--catalog-root", str(catalog_root), "--output", str(output_path)])

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["count"] == 0
    assert payload["depth_root_present"] is False


def test_absent_catalog_root_parent_is_non_zero(sds_mod: ModuleType, tmp_path: Path) -> None:
    catalog_root = tmp_path / "does" / "not" / "exist"
    exit_code = sds_mod.main(["--catalog-root", str(catalog_root)])
    assert exit_code != 0


# ---------------------------------------------------------------------------
# (v) draft/absent manifest -> non-zero, value-free
# ---------------------------------------------------------------------------


def test_draft_manifest_is_refused_non_zero_value_free(
    sds_mod: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = _draft_manifest_fixture(tmp_path)
    catalog_root = _make_depth_root(tmp_path, city="LAX", day=dt.date(2026, 9, 5))

    exit_code = sds_mod.main(
        [
            "--catalog-root",
            str(catalog_root),
            "--family-manifest",
            str(manifest_path),
        ]
    )

    assert exit_code != 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # value-free: never echoes the manifest's own field values
    assert "DRAFT_NOT_REGISTERED" not in combined
    assert "LAX" not in combined


def test_absent_manifest_is_refused_non_zero(sds_mod: ModuleType, tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.json"
    catalog_root = _make_depth_root(tmp_path, city="LAX", day=dt.date(2026, 9, 5))

    exit_code = sds_mod.main(
        [
            "--catalog-root",
            str(catalog_root),
            "--family-manifest",
            str(missing_path),
        ]
    )

    assert exit_code != 0


# ---------------------------------------------------------------------------
# (vi) fetch_start in the JSON equals the manifest's d0_climate_day, using
# the REAL registered manifest (read-only) as well as a tmp REGISTERED fixture
# ---------------------------------------------------------------------------


def test_fetch_start_equals_the_real_manifests_d0_climate_day(
    sds_mod: ModuleType, tmp_path: Path
) -> None:
    assert _REAL_MANIFEST.is_file(), "deploy/families/pm_us_crh_v2.json must exist read-only"
    manifest = sds_mod.load_family_manifest(_REAL_MANIFEST)

    catalog_root = _make_depth_root(
        tmp_path, city=manifest.stations[0], day=dt.date.fromisoformat(manifest.d0_climate_day)
    )
    output_path = tmp_path / "out.json"

    exit_code = sds_mod.main(
        [
            "--catalog-root",
            str(catalog_root),
            "--family-manifest",
            str(_REAL_MANIFEST),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["fetch_start"] == manifest.d0_climate_day
    assert payload["manifest_sha256"] == manifest.manifest_sha256
    assert payload["stations"] == list(manifest.stations)


def test_fetch_start_equals_a_tmp_registered_fixtures_d0_climate_day(
    sds_mod: ModuleType, tmp_path: Path
) -> None:
    manifest_path = _registered_manifest_fixture(tmp_path, d0="2026-08-31", stations=["MIA"])
    catalog_root = _make_depth_root(tmp_path, city="MIA", day=dt.date(2026, 8, 31))
    output_path = tmp_path / "out.json"

    exit_code = sds_mod.main(
        [
            "--catalog-root",
            str(catalog_root),
            "--family-manifest",
            str(manifest_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["fetch_start"] == "2026-08-31"

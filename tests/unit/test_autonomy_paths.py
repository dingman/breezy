"""ARCH-0 seam 3a: autonomy storage paths (plan "Paths" table; V19)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy.paths import (
    AutonomyPaths,
    ShadowPaths,
    default_data_root,
)
from breezy.persistence.autonomy.wire import WireRefusalReason, WireRefused

ROOT = Path("/tmp/autonomy-root")
SHA = "a" * 64
DAY = "2026-10-03"

#: Every attack a component must refuse: traversal, separators, NUL, case, length, non-ASCII.
VECTORS: tuple[str, ...] = (
    "",
    ".",
    "..",
    "../x",
    "x/..",
    "a/b",
    "/abs",
    "a\0b",
    "a\nb",
    "A",
    "a-b",
    "a b",
    "é",
    "x" * 65,
)


def _case(name: str, args: tuple[Any, ...]) -> tuple[str, tuple[Any, ...]]:
    return name, args


#: (builder, valid args). A traversal vector is substituted into each str argument in turn.
CASES: tuple[tuple[str, tuple[Any, ...]], ...] = (
    _case("family_file", ("pm_us_crh_fq_v1",)),
    _case("demand_dir", ("pm_us",)),
    _case("heartbeat_file", ("pm_us",)),
    _case("export_file", ("pm_us", DAY)),
    _case("journal_dir", ("pm_us", "rollback")),
    _case("journal_file", ("pm_us", "rollback", 1)),
    _case("verdict_dir", ("pm_us_crh_fq_v1", DAY)),
    _case("verdict_file", ("pm_us_crh_fq_v1", DAY, SHA)),
    _case("artefact_dir", ("forecast_quantile_ladder:density_table", SHA)),
    _case("artefact_file", ("forecast_quantile_ladder:density_table", SHA)),
)


def _call(paths: Any, name: str, args: tuple[Any, ...]) -> Path:
    result: Path = getattr(paths, name)(*args)
    return result


@pytest.mark.parametrize("cls", [AutonomyPaths, ShadowPaths])
@pytest.mark.parametrize(("name", "args"), CASES, ids=[c[0] for c in CASES])
def test_builder_refuses_traversal_vector_in_every_str_argument(
    cls: type, name: str, args: tuple[Any, ...]
) -> None:
    paths = cls(ROOT)
    assert str(_call(paths, name, args)).startswith(str(ROOT) + "/")  # control: valid args build
    str_positions = [i for i, a in enumerate(args) if isinstance(a, str)]
    assert str_positions
    for i in str_positions:
        for vector in VECTORS:
            bad = (*args[:i], vector, *args[i + 1 :])
            with pytest.raises(WireRefused) as caught:
                _call(paths, name, bad)
            assert caught.value.reason is WireRefusalReason.BAD_VALUE
            assert "\0" not in str(caught.value)
            assert str(ROOT) not in str(caught.value)


@pytest.mark.parametrize(("name", "args"), CASES, ids=[c[0] for c in CASES])
def test_builder_result_stays_under_root(name: str, args: tuple[Any, ...]) -> None:
    built = _call(AutonomyPaths(ROOT), name, args)
    assert built.is_relative_to(ROOT)
    assert ".." not in built.parts


@pytest.mark.parametrize("seq", [0, -1, 10**10, True, 1.5, "1", None])
def test_seq_vectors_refused(seq: object) -> None:
    with pytest.raises(WireRefused):
        AutonomyPaths(ROOT).journal_file("pm_us", "rollback", seq)  # type: ignore[arg-type]
    if seq is not None:  # None means "no reset suffix" for the export builder
        with pytest.raises(WireRefused):
            AutonomyPaths(ROOT).export_file("pm_us", DAY, hwm_export_seq=seq)  # type: ignore[arg-type]


def test_seq_is_zero_padded_to_ten_digits() -> None:
    built = AutonomyPaths(ROOT).journal_file("pm_us", "rollback", 7)
    assert built.name == "0000000007.json"
    assert (
        AutonomyPaths(ROOT).journal_file("pm_us", "rollback", 10**10 - 1).name == "9999999999.json"
    )


@pytest.mark.parametrize(
    "day", ["2026-13-01", "2026-02-30", "20261003", "2026-W40-1", "2026-1-3", "x"]
)
def test_date_vectors_refused(day: str) -> None:
    with pytest.raises(WireRefused):
        AutonomyPaths(ROOT).verdict_dir("pm_us_crh_fq_v1", day)


@pytest.mark.parametrize("sha", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, SHA + "\n"])
def test_sha_vectors_refused(sha: str) -> None:
    with pytest.raises(WireRefused):
        AutonomyPaths(ROOT).artefact_dir("forecast_quantile_ladder:density_table", sha)


@pytest.mark.parametrize(
    "model_class",
    [
        "density_table",
        "forecast_quantile_ladder:",
        "unknown_kind:density_table",
        "forecast_quantile_ladder:Density",
        "forecast_quantile_ladder:" + "a" * 49,
        "forecast_quantile_ladder:a/b",
    ],
)
def test_model_class_vectors_refused(model_class: str) -> None:
    with pytest.raises(WireRefused):
        AutonomyPaths(ROOT).artefact_dir(model_class, SHA)


def test_model_class_kind_set_equals_composition_kinds() -> None:
    from breezy.persistence.family_manifest import _COMPOSITION_KINDS

    paths = AutonomyPaths(ROOT)
    for kind in _COMPOSITION_KINDS:
        assert paths.artefact_dir(f"{kind}:density_table", SHA).is_relative_to(ROOT)
    with pytest.raises(WireRefused):
        paths.artefact_dir("not_a_kind:density_table", SHA)


@pytest.mark.parametrize("value", [None, 1, b"x", Path("x")])
def test_non_string_component_is_wrong_type(value: object) -> None:
    with pytest.raises(WireRefused) as caught:
        AutonomyPaths(ROOT).family_file(value)  # type: ignore[arg-type]
    assert caught.value.reason is WireRefusalReason.WRONG_TYPE


@pytest.mark.parametrize("root", [Path("relative/root"), Path("rel")])
def test_root_must_be_absolute(root: Path) -> None:
    for cls in (AutonomyPaths, ShadowPaths):
        with pytest.raises(WireRefused):
            cls(root)


def test_root_must_be_a_path() -> None:
    with pytest.raises(WireRefused):
        AutonomyPaths("/abs")  # type: ignore[arg-type]


def test_venue_and_family_length_boundaries() -> None:
    paths = AutonomyPaths(ROOT)
    assert paths.demand_dir("v" * 32).name == "v" * 32
    with pytest.raises(WireRefused):
        paths.demand_dir("v" * 33)
    assert paths.family_file("f" * 64).name == "f" * 64 + ".json"
    with pytest.raises(WireRefused):
        paths.family_file("f" * 65)


def test_storage_layout_matches_plan() -> None:
    p = AutonomyPaths(ROOT)
    assert p.registry_db() == ROOT / "registry/registry.sqlite"
    assert p.engine_lock() == ROOT / "registry/engine.lock"
    assert p.family_file("fam_1") == ROOT / "registry/families/fam_1.json"
    assert p.demand_dir("pm_us") == ROOT / "registry/demand/pm_us"
    assert p.heartbeat_file("pm_us") == ROOT / "registry/heartbeat/pm_us.json"
    assert p.drill_marker() == ROOT / "registry/drill/marker.json"
    assert p.export_dir() == ROOT / "evidence/registry"
    assert p.export_file("pm_us", DAY) == ROOT / "evidence/registry/registry_pm_us_2026-10-03.jsonl"
    assert (
        p.export_file("pm_us", DAY, hwm_export_seq=3)
        == ROOT / "evidence/registry/registry_pm_us_2026-10-03_hwm3.jsonl"
    )
    assert (
        p.journal_file("pm_us", "rollback", 12)
        == ROOT / "evidence/journal/pm_us/rollback/0000000012.json"
    )
    assert p.verdict_file("fam_1", DAY, SHA) == ROOT / f"derived/verdicts/fam_1/{DAY}/{SHA}.json"
    mc = "forecast_quantile_ladder:density_table"
    assert p.artefact_file(mc, SHA) == ROOT / f"derived/artefacts/{mc}/{SHA}/artefact.json"


def test_family_component_accepted_by_both_existing_id_patterns() -> None:
    from breezy.runtime.settings import _FAMILY_ID_RE as settings_re
    from breezy.strategy.current_rung_hold.trial_day_latch import FAMILY_ID_PATTERN

    samples = ["pm_us_crh_fq_v1", "a", "0", "_", "a" * 64, "pm_us_crh_cont", "f_" * 32]
    paths = AutonomyPaths(ROOT)
    for sample in samples:
        assert settings_re.match(sample), sample
        assert FAMILY_ID_PATTERN.fullmatch(sample), sample
        assert paths.family_file(sample).name == f"{sample}.json"
    # The component grammar is the INTERSECTION: it refuses what either pattern refuses.
    for hostile in ("A", "a-b", "a:b", "a" * 65, ""):
        with pytest.raises(WireRefused):
            paths.family_file(hostile)


def test_shadow_paths_is_distinct_type() -> None:
    assert not issubclass(ShadowPaths, AutonomyPaths)
    assert not issubclass(AutonomyPaths, ShadowPaths)
    assert AutonomyPaths.is_shadow is False
    assert ShadowPaths.is_shadow is True
    prod, shadow = AutonomyPaths(ROOT), ShadowPaths(ROOT)
    assert prod.is_shadow is False
    assert shadow.is_shadow is True
    assert not isinstance(shadow, AutonomyPaths)
    assert prod != shadow  # same root, different role
    assert prod.registry_db() == shadow.registry_db()  # one layout


def test_paths_are_value_objects() -> None:
    assert AutonomyPaths(ROOT) == AutonomyPaths(Path(str(ROOT)))
    assert hash(AutonomyPaths(ROOT)) == hash(AutonomyPaths(ROOT))
    assert AutonomyPaths(ROOT).root == ROOT
    with pytest.raises(AttributeError):
        AutonomyPaths(ROOT).root = Path("/other")  # type: ignore[misc]
    with pytest.raises(AttributeError):
        AutonomyPaths(ROOT).extra = 1  # type: ignore[attr-defined]


def test_default_data_root_is_under_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_data_root() == tmp_path / ".local" / "share" / "breezy"

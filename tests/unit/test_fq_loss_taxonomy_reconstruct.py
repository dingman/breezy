"""TE-2 WP1b (RED then GREEN): the S0-D reconstruction module (plan section 4, S0-D).

Fakes are paired with the production default path (L-55): the real ``SubprocessGit`` over a tmp repo
and over this repo's real pinned commit, and the real derived-store reader over a store written by
the real ``write_partition``.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from pathlib import Path

import pytest

from scripts.analysis.fq_loss_taxonomy_core import S0DMiss
from scripts.analysis.fq_loss_taxonomy_inputs import (
    Boot,
    BootPin,
    FillSpec,
    Reconstructor,
    S0DStop,
    SubprocessGit,
    boot_for,
    iter_published_cycles,
    load_derived_cycles,
    load_pinned_model,
    partition_complete,
    published_cycles,
    reconstruct_all,
    s0d_gate,
)
from tests.support.te2_cli_fixtures import (
    BOOT_STAMPS,
    ICAO,
    MANIFEST_REL,
    REAL_ARTEFACT,
    REPO,
    World,
    _derived_rows,
    build_world,
    expected_p_hat,
    sha256_file,
    utc_ns,
)

_NS = 10**9


def _specs(world: World) -> list[FillSpec]:
    return [
        FillSpec(f"f{i}", c.instrument_id, c.p_hat, c.decision_ns, 0.15)
        for i, c in enumerate(world.cases)
    ]


def _reconstructor(world: World, workdir: Path) -> Reconstructor:
    return Reconstructor(
        SubprocessGit(world.repo_root), manifest_path=MANIFEST_REL, workdir=workdir,
        cycles=load_derived_cycles(world.derived_root), published=published_cycles(world.logs),
    )  # fmt: skip


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    return build_world(tmp_path_factory.mktemp("recon") / "w")


def test_published_cycles_stream_the_visibility_from_the_node_log(world: World) -> None:
    pairs = [p for log in world.logs for p in iter_published_cycles(log)]
    mapping = published_cycles(world.logs)

    assert len(pairs) == len(mapping) == 5  # one cycle per FQ climate day
    day = dt.date(2026, 10, 3)
    assert mapping[world.cycle_ns_by_day[day]] == utc_ns(day - dt.timedelta(days=1), 17.0)


def test_derived_store_reader_groups_rows_by_cycle(world: World) -> None:
    cycles = load_derived_cycles(world.derived_root)

    assert set(cycles) == set(world.cycle_ns_by_day.values())
    rows = cycles[world.cycle_ns_by_day[dt.date(2026, 10, 3)]]
    assert len(rows) == 4 * 2 * 7 and {r.station for r in rows} == set(ICAO.values())


def test_every_fill_reconstructs_with_the_d_plus_1_window_and_the_cycle_facts(
    world: World, tmp_path: Path
) -> None:
    rec = _reconstructor(world, tmp_path / "wd")
    results = [rec.reconstruct(spec, world.commit) for spec in _specs(world)]

    assert all(r.match for r in results)
    assert max(abs(r.delta or 0.0) for r in results) <= 1e-9
    first = results[0]
    assert first.cycle_ns == world.cycle_ns_by_day[world.cases[0].climate_day]
    assert first.newest_visible is True
    assert first.cycle_age_s == pytest.approx(5 * 3600.0)  # 13Z cycle, decided at 18Z
    assert first.raw_sha256 and set(first.vector or {}) >= {"q10", "q50", "q90", "sd"}
    assert first.vector is not None and first.vector["q50"] == pytest.approx(
        70.0 + 3 * 0 + world.cases[0].climate_day.day
    )  # the D+1 window, never the D+2 one
    assert first.pmf is not None and math.fsum(first.pmf.values()) == pytest.approx(1.0, abs=1e-6)


def test_a_perturbed_vector_mismatches_and_is_k1a_with_a_materiality_flag(
    world: World, tmp_path: Path
) -> None:
    case = world.cases[0]
    cycle = world.cycle_ns_by_day[case.climate_day]
    visible = utc_ns(case.climate_day - dt.timedelta(days=1), 17.0)
    cycles = load_derived_cycles(world.derived_root)
    cycles[cycle] = tuple(_derived_rows(case.climate_day, cycle, visible, {case.station: 1.5}))
    rec = Reconstructor(
        SubprocessGit(world.repo_root), manifest_path=MANIFEST_REL, workdir=tmp_path / "wd",
        cycles=cycles, published=published_cycles(world.logs),
    )  # fmt: skip

    result = rec.reconstruct(_specs(world)[0], world.commit)

    assert result.match is False and result.s0d_class == S0DMiss.K1A
    assert result.delta is not None and abs(result.delta) > 1e-9
    assert result.material == (abs(result.delta) > 0.01)


def _run(world: World, wd: Path, spec: FillSpec, cycles: dict, published: dict):  # type: ignore[no-untyped-def,type-arg]
    rec = Reconstructor(
        SubprocessGit(world.repo_root), manifest_path=MANIFEST_REL, workdir=wd,
        cycles=cycles, published=published,
    )  # fmt: skip
    return rec.reconstruct(spec, world.commit)


def test_missing_and_reissued_bulletins_are_untestable_and_a_late_cycle_is_ambiguous(
    world: World, tmp_path: Path
) -> None:
    spec = _specs(world)[0]
    case = world.cases[0]
    cycle = world.cycle_ns_by_day[case.climate_day]
    base = load_derived_cycles(world.derived_root)
    live = published_cycles(world.logs)

    missing = _run(world, tmp_path / "a", spec, {k: v for k, v in base.items() if k != cycle}, live)
    assert (missing.match, missing.s0d_class) == (False, S0DMiss.UNTESTABLE)

    visible = utc_ns(case.climate_day - dt.timedelta(days=1), 17.0)
    reissued_rows = tuple(
        dataclasses.replace(r, available_at_ns=visible + 3600 * _NS)
        for r in _derived_rows(case.climate_day, cycle, visible, {case.station: 1.5})
    )  # a reissued bulletin: different values, Last-Modified after the live publication
    reissued = _run(world, tmp_path / "b", spec, {**base, cycle: reissued_rows}, live)
    assert (reissued.match, reissued.s0d_class) == (False, S0DMiss.UNTESTABLE)
    assert reissued.reason == "bulletin_reissued"

    late, late_at = cycle + 3600 * _NS, spec.decision_now_ns + 2 * _NS
    late_rows = tuple(_derived_rows(case.climate_day, late, late_at, {case.station: 2.0}))
    ambiguous = _run(
        world, tmp_path / "c", spec, {**base, late: late_rows}, {**live, late: late_at}
    )
    assert ambiguous.match is True  # the earlier cycle is still the one visible at now_ns
    perturbed = dataclasses.replace(spec, p_hat_logged=spec.p_hat_logged + 0.02)
    flagged = _run(
        world, tmp_path / "d", perturbed, {**base, late: late_rows}, {**live, late: late_at}
    )
    assert flagged.s0d_class == S0DMiss.CYCLE_AMBIGUOUS


def test_reconstruct_all_assigns_boots_by_time_and_respects_untestable_pins(
    world: World, tmp_path: Path
) -> None:
    boots = [
        Boot(i + 1, dt.datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=dt.UTC), "m", "a")
        for i, s in enumerate(BOOT_STAMPS)
    ]
    pins = [BootPin(b.number, world.commit, False, "PINNED", None) for b in boots]
    pins[8] = BootPin(9, world.commit, False, "UNTESTABLE", None)  # type: ignore[arg-type]
    specs = _specs(world)
    rec = _reconstructor(world, tmp_path / "wd")

    results = reconstruct_all(rec, specs, boots, pins)

    assert len(results) == 25
    assert boot_for(boots, specs[0].decision_now_ns) == world.cases[0].boot_number
    on_nine = [r for r, c in zip(results, world.cases, strict=True) if c.boot_number == 9]
    assert on_nine and all(r.s0d_class == S0DMiss.UNTESTABLE and not r.match for r in on_nine)
    assert all(r.boot_number == c.boot_number for r, c in zip(results, world.cases, strict=True))
    assert boot_for(boots, 0) is None


def test_reproduces_under_callback_requires_every_fill_of_the_boot_to_match(
    world: World, tmp_path: Path
) -> None:
    specs = _specs(world)
    rec = _reconstructor(world, tmp_path / "wd")
    by_boot = {3: [s for s, c in zip(specs, world.cases, strict=True) if c.boot_number == 3]}
    callback = rec.reproduces_under(by_boot)

    assert callback(3, world.commit) is True
    bad = {3: [dataclasses.replace(by_boot[3][0], p_hat_logged=0.5)]}
    assert rec.reproduces_under(bad)(3, world.commit) is False


def test_s0d_gate_counts_untestable_as_a_non_match_and_stops_below_23(
    world: World, tmp_path: Path
) -> None:
    rec = _reconstructor(world, tmp_path / "wd")
    results = [rec.reconstruct(s, world.commit) for s in _specs(world)]
    assert s0d_gate(results).passed is True
    broken = [dataclasses.replace(r, match=False) for r in results[:2]] + results[2:]
    assert s0d_gate(broken).n_match == 23
    with pytest.raises(S0DStop):
        s0d_gate([dataclasses.replace(r, match=False) for r in results[:3]] + results[3:])


@pytest.mark.parametrize(
    ("ids", "expected"),
    [
        (["lt_69", "70_99", "100_gte"], True),
        (["lt_69", "100_gte"], False),
        (["70_99", "100_gte"], False),
        (["lt_69", "70_99"], False),
        (["lt_69", "69_99", "100_gte"], False),
        ([], False),
    ],
)
def test_partition_complete_needs_contiguous_coverage_from_open_to_open(
    ids: list[str], expected: bool
) -> None:
    assert partition_complete(ids) is expected


def test_production_defaults_real_git_real_pinned_commit_and_real_store_reader(
    world: World, tmp_path: Path
) -> None:
    """L-55: SubprocessGit over THIS repo's pinned go-live commit and the real derived reader."""
    git = SubprocessGit(REPO)
    model = load_pinned_model(git, "60290e9ddd29", "deploy/families/pm_us_crh_fq_v1.json", tmp_path)

    assert model.commit.startswith("60290e9ddd29") and model.fee_coefficient == pytest.approx(
        0.0695
    )
    assert git.blob_sha256("60290e9ddd29", "deploy/families/pm_us_crh_fq_v1.json") is not None
    pinned = git.show_blob(
        "60290e9ddd29",
        "deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json",
    )
    assert pinned == REAL_ARTEFACT.read_bytes() and sha256_file(REAL_ARTEFACT)
    cycles = load_derived_cycles(world.derived_root)
    published = published_cycles(world.logs)
    rec = Reconstructor(
        git, manifest_path="deploy/families/pm_us_crh_fq_v1.json", workdir=tmp_path / "w",
        cycles=cycles, published=published,
    )  # fmt: skip
    case = world.cases[3]
    logged = expected_p_hat(case.station, case.climate_day, case.instrument_id)
    spec = FillSpec("g", case.instrument_id, logged, case.decision_ns, 0.15)

    result = rec.reconstruct(spec, "60290e9ddd29")

    assert result.match is True and result.commit is not None

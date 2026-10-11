"""TE-2 WP1c (RED then GREEN): the Phase B pipeline, pin coverage, boot-2 transparency, verifier.

End to end over a fully synthetic tree: the Phase A world and table, a copied tmp git repo holding
a committed predeclaration and a stub frozen family, a real durable fill store and a catalog that
is clipped at 10-06. Nothing real is read: no real settlement, no holdout, no M1-v3, no network.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.catalog import open_station_catalog, write_records
from scripts.analysis import fq_loss_taxonomy_provenance as prov
from scripts.analysis import fq_v1_loss_taxonomy as cli
from scripts.analysis.fq_loss_taxonomy_battery import DayRecord, run_battery
from scripts.analysis.fq_loss_taxonomy_fills import k3_flips, k4_mismatches, metar_daily_max
from scripts.analysis.fq_loss_taxonomy_predecl import (
    PredeclarationError,
    load_predeclaration,
    thresholds_block,
    unpinned_family_modules,
)
from scripts.analysis.fq_loss_taxonomy_report import delivery, forward_route
from scripts.analysis.fq_loss_taxonomy_verdict import (
    VerdictInputs,
    VerdictLabel,
    decide_verdict,
    render_footer,
)
from tests.support.te2_cli_fixtures import World, build_world
from tests.support.te2_fixtures import (
    FQ_TMAX,
    fq_instrument_ids,
    fq_settlement_records,
    git_cmd,
    nws_record,
)
from tests.support.te2_phase_b_fixtures import (
    FAMILY,
    PRE_REL,
    BPaths,
    build_phase_b,
    faithful_locate,
    sha256_path,
)

_CLASSES = {"WIN", "SIBLING_WON", "BOUNDARY", "TAIL", "BAND_SELECTION", "BODY_MISS", "UNTESTABLE"}
_TOP_KEYS = {
    "phase", "provenance", "predeclaration", "audit", "fills", "class_counts", "ranked_classes",
    "flag_counts", "tests", "sensitivity", "downgrade", "testability", "tie_reevaluation",
    "verdict", "report_phrases", "footer", "consumers", "delivery", "te1_cross_check",
    "alt_truth", "t_edge", "h0k", "caveats",
}  # fmt: skip


def _records() -> dict[tuple[str, dt.date], NwsClimateDay]:
    return {(r.station, r.climate_day): r for r in fq_settlement_records()}


def _router(
    records: Mapping[tuple[str, dt.date], NwsClimateDay], asked: list[dt.date] | None = None
) -> type:
    class _Router:
        def __init__(self, base: Path) -> None:
            pass

        def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
            assert climate_day >= dt.date(2026, 10, 1), "pre-October (holdout) truth was read"
            if asked is not None:
                asked.append(climate_day)
            return records.get((station, climate_day))

    return _Router


@pytest.fixture(autouse=True)
def _running_code_is_the_frozen_tmp_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stub family in the tmp repo stands in for the running code (H1 is tested elsewhere)."""
    monkeypatch.setattr(prov, "locate_running", faithful_locate)


def _policy(world: World) -> cli.PinPolicy:
    return cli.PinPolicy((world.commit[:12],) * 9, (world.first_commit, world.commit))


@pytest.fixture(scope="module")
def phase_a(tmp_path_factory: pytest.TempPathFactory) -> tuple[World, Path]:
    root = tmp_path_factory.mktemp("phase_a_for_b")
    world = build_world(root / "w")
    out = root / "out"
    assert cli.main(world.phase_a_argv(out), policy=_policy(world)) == 0
    return world, out / "phase_a_table.json"


@pytest.fixture(scope="module")
def completed(
    phase_a: tuple[World, Path], tmp_path_factory: pytest.TempPathFactory
) -> tuple[BPaths, dict[str, Any], str]:
    world, table = phase_a
    b = build_phase_b(tmp_path_factory.mktemp("b_ok"), world, table)
    asked: list[dt.date] = []
    mp = pytest.MonkeyPatch()
    mp.setattr(prov, "locate_running", faithful_locate)
    mp.setattr(cli, "_CatalogRouter", _router(_records(), asked))
    try:
        assert cli.main(b.argv()) == 0
    finally:
        mp.undo()
    assert asked and min(asked) >= dt.date(2026, 10, 1)  # never a pre-October (holdout) day
    return b, json.loads(b.result_json.read_text()), b.result_md.read_text()


def test_phase_a_rows_carry_the_pmf_and_raw_vector_inputs_phase_b_needs(
    phase_a: tuple[World, Path],
) -> None:
    _world, table = phase_a
    rows = json.loads(table.read_text())["per_fill"]

    assert all(r["pmf"] and r["raw_q50"] is not None and r["raw_sd"] for r in rows)
    assert all("p_hat_predecessor" in r and "predecessor_commit" in r for r in rows)


def test_phase_b_writes_json_and_md_with_every_section(
    completed: tuple[BPaths, dict[str, Any], str],
) -> None:
    b, payload, md = completed

    assert _TOP_KEYS <= set(payload), _TOP_KEYS - set(payload)
    assert payload["phase"] == "B"
    assert payload["audit"]["n_fills"] == 25 and payload["audit"]["n_wins"] == 2
    assert abs(float(payload["audit"]["net_pnl"]) + 2.17) <= 0.005
    assert len(payload["fills"]) == 25
    assert all(f["class"] in _CLASSES and isinstance(f["flags"], list) for f in payload["fills"])
    wins = [f for f in payload["fills"] if f["class"] == "WIN"]
    assert sorted(f["tmax_f"] for f in wins) == [87, 90]
    assert {
        ("gte86lt87" in f["instrument_id"], "gte89lt90" in f["instrument_id"]) for f in wins
    } == {
        (True, False),
        (False, True),
    }
    counts = Counter(f["class"] for f in payload["fills"])
    assert counts["WIN"] == 2 and counts["SIBLING_WON"] == 2
    assert sum(payload["class_counts"].values()) == 25
    assert abs(sum(r["share_of_loss"] for r in payload["ranked_classes"]) - 1.0) < 1e-9
    assert "TE-1 cross-check pending" in md and b.pre_commit in md
    assert payload["verdict"]["label"] in {v.value for v in VerdictLabel}


def test_phase_b_reports_every_test_with_status_power_loo_and_sensitivities(
    completed: tuple[BPaths, dict[str, Any], str],
) -> None:
    _b, payload, _md = completed
    tests = payload["tests"]

    assert {"T-WIN", "T-LOC", "T-SPREAD", "T-ART"} <= set(tests)
    win = tests["T-WIN"]
    assert win["w_obs"] == 2 and win["n_units"] == 7
    assert 0.0 <= win["p_value"] <= 1.0 and 0.0 <= win["power"]["power"] <= 1.0
    assert win["status"] in {"TESTABLE", "TESTABLE-CONDITIONAL", "NOT-TESTABLE"}
    assert "dropped_station" in win["leave_one_out"] and "rejects" in win["leave_one_out"]
    assert "power" in tests["T-SPREAD"] and "n_after_drops" in tests["T-ART"]
    assert "n_after_drops" in tests["T-LOC"] and "p_at_pi_min" in tests["T-LOC"]
    assert payload["sensitivity"]["six_cluster"]["T-WIN"]["n_units"] == 6
    assert payload["sensitivity"]["station_day"]["T-WIN"]["n_units"] == 14
    assert set(payload["downgrade"]) >= {"decisions", "range_notes", "scope_sensitive"}
    assert set(payload["testability"]) >= {"predeclared", "after_ties"}
    assert set(payload["tie_reevaluation"]) >= {"downgraded", "variance_eligible"}
    assert payload["h0k"]["p_value"] is not None and payload["t_edge"]["confirmatory_weight"] == 0


def test_phase_b_footer_consumers_delivery_and_provenance(
    completed: tuple[BPaths, dict[str, Any], str],
) -> None:
    b, payload, md = completed

    assert payload["footer"] == render_footer(14, 7) and payload["footer"] in md
    assert payload["consumers"] and all(
        c["finding"] and c["consumer"] for c in payload["consumers"]
    )
    assert payload["verdict"]["label"] in {c["finding"] for c in payload["consumers"]}
    assert payload["delivery"] == {"soft_target": "2026-10-20", "slip": None}
    assert payload["te1_cross_check"]["status"] == "TE-1 cross-check pending"
    assert (
        payload["alt_truth"]["k3_status"] == "UNTESTABLE"
        and payload["alt_truth"]["k3_count"] is None
    )
    prov = payload["provenance"]
    assert prov["pins_json_sha256"] == sha256_path(b.pins)
    assert prov["script_sha256"] == sha256_path(b.repo / FAMILY[2])
    assert prov["reflog_snapshot_sha256"] == b.world.snapshot_sha256
    assert prov["phase_a_table_sha256"] == sha256_path(b.table)
    assert payload["predeclaration"]["commit"] == b.pre_commit


def test_a_predeclared_threshold_is_what_phase_b_uses(
    phase_a: tuple[World, Path],
    tmp_path: Path,
    completed: tuple[BPaths, dict[str, Any], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, table = phase_a
    _b0, default_payload, _md = completed
    assert not any("FLANK_CHEAP" in f["flags"] for f in default_payload["fills"])
    b = build_phase_b(tmp_path, world, table, thresholds_patch={"flank_cheap_ask": 0.99})
    monkeypatch.setattr(cli, "_CatalogRouter", _router(_records()))

    assert cli.main(b.argv()) == 0
    patched = json.loads(b.result_json.read_text())
    assert all("FLANK_CHEAP" in f["flags"] for f in patched["fills"])


def test_phase_b_refuses_when_a_frozen_constant_drifted_from_the_predeclaration(
    phase_a: tuple[World, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world, table = phase_a
    b = build_phase_b(tmp_path, world, table, thresholds_patch={"alpha_primary": 0.05})

    assert cli.main(b.argv()) == cli.EXIT_STOP
    assert "alpha_primary" in capsys.readouterr().err
    assert not b.result_json.exists()


def test_phase_b_refuses_on_phase_a_table_sha_mismatch_before_reading_any_truth(
    phase_a: tuple[World, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, table = phase_a
    b = build_phase_b(tmp_path, world, table)
    tampered = tmp_path / "tampered_table.json"
    tampered.write_text(table.read_text() + "\n")
    asked: list[dt.date] = []
    monkeypatch.setattr(cli, "_CatalogRouter", _router(_records(), asked))
    argv = [str(tampered) if a == str(table) else a for a in b.argv()]

    assert cli.main(argv) == cli.EXIT_STOP
    assert "phase_a_table_sha256" in capsys.readouterr().err
    assert not asked and not b.result_json.exists()


def test_phase_b_refuses_an_unpinned_family_module_even_untracked(
    phase_a: tuple[World, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world, table = phase_a
    b = build_phase_b(tmp_path, world, table)
    (b.repo / "scripts/analysis/fq_loss_taxonomy_extra.py").write_text("Y = 1\n")

    assert cli.main(b.argv()) == cli.EXIT_STOP
    err = capsys.readouterr().err
    assert "unpinned_family_module" in err and "fq_loss_taxonomy_extra.py" in err
    assert not b.result_json.exists()


def test_phase_b_refuses_a_predeclaration_edited_after_its_commit(
    phase_a: tuple[World, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world, table = phase_a
    b = build_phase_b(tmp_path, world, table)
    b.predeclaration.write_text(b.predeclaration.read_text() + "\n")

    assert cli.main(b.argv()) == cli.EXIT_STOP
    assert "predeclaration_modified" in capsys.readouterr().err


def test_audit_mismatch_is_a_stop_with_no_result_artefact(
    phase_a: tuple[World, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, table = phase_a
    b = build_phase_b(tmp_path, world, table)
    records = _records()
    records[("MIA", dt.date(2026, 10, 3))] = nws_record("MIA", dt.date(2026, 10, 3), 60)
    monkeypatch.setattr(cli, "_CatalogRouter", _router(records))

    assert cli.main(b.argv()) == cli.EXIT_STOP
    assert "STOP" in capsys.readouterr().err
    assert (b.out / "phase_b_audit_STOP.json").exists() and not b.result_json.exists()
    assert not (b.out / "phase_b_audit.json").exists()  # M8: only a PASSED audit is recorded


def test_phase_b_runs_the_production_catalog_router_once(
    phase_a: tuple[World, Path], tmp_path: Path
) -> None:
    """L-55: no router is injected; a real station catalog written by the real writer is read."""
    world, table = phase_a
    b = build_phase_b(tmp_path, world, table)
    base = b.out / "catalog"
    for station in ("LAX", "MDW", "MIA", "SFO"):
        rows = [r for r in fq_settlement_records() if r.station == station]
        write_records(open_station_catalog(base, "polymarket_us", station), rows)

    assert cli.main(b.argv()) == 0
    payload = json.loads(b.result_json.read_text())
    assert payload["audit"]["n_fills"] == 25 and payload["audit"]["n_wins"] == 2


def test_unpinned_family_modules_lists_every_family_file_absent_from_the_pins(
    tmp_path: Path,
) -> None:
    analysis = tmp_path / "scripts" / "analysis"
    analysis.mkdir(parents=True)
    for name in ("fq_loss_taxonomy_a.py", "fq_loss_taxonomy_b.py", "fq_v1_loss_taxonomy.py",
                 "unrelated_tool.py"):  # fmt: skip
        (analysis / name).write_text("x = 1\n")
    pinned = ["scripts/analysis/fq_loss_taxonomy_a.py"]

    assert unpinned_family_modules(tmp_path, pinned) == (
        "scripts/analysis/fq_loss_taxonomy_b.py",
        "scripts/analysis/fq_v1_loss_taxonomy.py",
    )
    assert (
        unpinned_family_modules(tmp_path, [*pinned, *unpinned_family_modules(tmp_path, pinned)])
        == ()
    )


def test_load_predeclaration_rejects_missing_keys_and_wrong_phase_a_sha(tmp_path: Path) -> None:
    table = tmp_path / "t.json"
    table.write_text("{}")
    good = {
        "phase_a_table_sha256": sha256_path(table), "thresholds": thresholds_block(),
        "consumer_map": {}, "s0i_statuses": {}, "terminal_climate_day": "2026-10-05",
    }  # fmt: skip
    path = tmp_path / "p.json"
    path.write_text(json.dumps(good))
    assert load_predeclaration(path, table).phase_a_table_sha256 == sha256_path(table)
    path.write_text(json.dumps({**good, "phase_a_table_sha256": "0" * 64}))
    with pytest.raises(PredeclarationError, match="phase_a_table_sha256"):
        load_predeclaration(path, table)
    path.write_text(json.dumps({**good, "thresholds": {}}))
    with pytest.raises(PredeclarationError, match="missing"):
        load_predeclaration(path, table)


def _day(
    station: str, tail: bool = False, *, corr: float = 3.0, raw: float = 1.0, won: bool = False
) -> DayRecord:
    return DayRecord(
        station=station, climate_day=dt.date(2026, 10, 2), p_d=0.5, won=won, ask_prob=0.5,
        fill_qs=(0.9,), tail_flags=(tail,), pi=0.5, corr_err=corr, raw_err=raw,
    )  # fmt: skip


def test_ties_downgrade_t_art_and_a_downgraded_test_cannot_feed_variance() -> None:
    days = [_day(f"S{i}", won=i < 3) for i in range(6)] + [_day("S6", corr=1.0, raw=1.0)]  # d == 0
    result = run_battery(days, level="cluster", alpha_primary=0.02, alpha_art=0.01)

    assert result.report["T-ART"]["n_after_drops"] == 6 and result.report["T-ART"]["n_dropped"] == 1
    assert result.report["testability"]["pre_ties"]["T-ART"] == "TESTABLE"
    assert result.after_ties["T-ART"] == "NOT-TESTABLE"
    assert result.report["tie_reevaluation"]["variance_eligible"]["T-ART"] is False
    verdict = decide_verdict(
        VerdictInputs(
            t_win=dataclasses.replace(result.outcomes["T-WIN"], power=0.95),
            loo_rejects=False,
            t_loc=result.outcomes["T-LOC"],
            t_spread=result.outcomes["T-SPREAD"],
            t_art=result.outcomes["T-ART"],
        )
    )
    assert verdict.label is VerdictLabel.INCONCLUSIVE
    assert "no unconditionally TESTABLE secondary" in (verdict.reason or "")


def test_battery_t_win_matches_the_exact_lower_tail() -> None:
    days = [_day(f"S{i}") for i in range(7)]
    result = run_battery(days, level="cluster", alpha_primary=0.02, alpha_art=0.01)

    # 7 clusters, P_c = 0.5, w_obs = 0: P(W <= 0) = 0.5**7.
    assert result.report["T-WIN"]["p_value"] == pytest.approx(0.5**7)
    assert result.outcomes["T-WIN"].rejects is True and result.report["T-WIN"]["w_obs"] == 0


def _git_repo_with_artefact(tmp: Path, *, same_commit: bool) -> tuple[Path, Path]:
    repo = tmp / "r"
    repo.mkdir(parents=True)
    git_cmd(repo, "init", "-q", "-b", "main")
    (repo / "docs/evidence/te2").mkdir(parents=True)
    pre = repo / PRE_REL
    pre.write_text("{}\n")
    artefact = repo / "docs/evidence/te2/fq_v1_loss_taxonomy_2026-10-12.json"
    if same_commit:
        artefact.write_text("{}\n")
        git_cmd(repo, "add", "docs")
        git_cmd(repo, "commit", "-q", "-m", "pre+artefact")
        first = git_cmd(repo, "rev-parse", "HEAD")
    else:
        git_cmd(repo, "add", "docs")
        git_cmd(repo, "commit", "-q", "-m", "pre")
        first = git_cmd(repo, "rev-parse", "HEAD")
        artefact.write_text("{}\n")
        git_cmd(repo, "add", "docs")
        git_cmd(repo, "commit", "-q", "-m", "artefact")
    pins = tmp / "pins.json"
    pins.write_text(json.dumps({"head_blob_sha256": {PRE_REL: sha256_path(pre)},
                                "predeclaration_commit": first}))  # fmt: skip
    return repo, pins


# The passing verify path (artefact + pins + siblings committed) is exercised end to end in
# test_fq_loss_taxonomy_prefreeze.py (verify now also binds every pinned blob and the siblings).


def test_verify_fails_when_the_artefact_shares_the_predeclaration_commit_or_is_uncommitted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, pins = _git_repo_with_artefact(tmp_path / "a", same_commit=True)
    path = repo / "docs/evidence/te2/fq_v1_loss_taxonomy_2026-10-12.json"
    base = ["verify", "--repo-root", str(repo), "--pins-json", str(pins)]

    assert cli.main([*base, "--artefact", str(path)]) == cli.EXIT_STOP
    assert "artefact_not_after_predeclaration" in capsys.readouterr().err
    loose = repo / "docs/evidence/te2/never_committed.json"
    loose.write_text("{}\n")
    assert cli.main([*base, "--artefact", str(loose)]) == cli.EXIT_STOP
    assert "artefact" in capsys.readouterr().err


def test_near_boundary_boot_rows_carry_the_predecessor_p_hat_and_commit(tmp_path: Path) -> None:
    world = build_world(tmp_path / "w")
    git_cmd(world.repo_root, "commit", "--allow-empty", "-q", "-m", "c2")
    c2 = git_cmd(world.repo_root, "rev-parse", "HEAD")
    first = f"2026-09-30T00:00:00+00:00 old={'0' * 12} new={world.commit} commit: c1\n"
    second = f"2026-10-01T16:50:00+00:00 old={world.commit} new={c2} commit: c2\n"
    body = f"# Captured\n# source: .git/logs/HEAD\n{first}{second}"
    body += f"# source: .git/logs/refs/heads/main\n{first}{second}"
    snapshot = tmp_path / "reflog2.txt"
    snapshot.write_text(body)
    import hashlib

    sha = hashlib.sha256(body.encode()).hexdigest()
    world2 = dataclasses.replace(world, snapshot=snapshot, snapshot_sha256=sha)
    policy = cli.PinPolicy(
        (world.commit[:12],) * 2 + (c2[:12],) * 7, (world.first_commit, c2)
    )  # fmt: skip

    assert cli.main(world2.phase_a_argv(tmp_path / "out"), policy=policy) == 0
    table = json.loads((tmp_path / "out" / "phase_a_table.json").read_text())
    near = [r for r in table["per_fill"] if r["boot"] == 3]
    other = [r for r in table["per_fill"] if r["boot"] != 3]
    assert near and other
    for row in near:
        assert row["predecessor_commit"] == world.commit
        assert row["p_hat_predecessor"] == pytest.approx(row["p_hat_reconstructed"], abs=1e-12)
    assert all(r["predecessor_commit"] is None and r["p_hat_predecessor"] is None for r in other)
    boot3 = next(p for p in table["pin_table"] if p["boot_number"] == 3)
    assert boot3["near_boundary"] is True and boot3["predecessor"] == world.commit


_METAR_HEADER = "station,valid_utc,tmpf,tgroup_c,report_type,tmpf_source,metar\n"


def test_metar_daily_max_uses_the_local_standard_day_window(tmp_path: Path) -> None:
    station = tmp_path / "metar-routine" / "KLAX"
    station.mkdir(parents=True)
    (station / "2026.csv").write_text(
        _METAR_HEADER
        + "KLAX,2026-10-02T07:53Z,99,,3,x,x\n"  # 23:53 local on 10-01: before the window
        + "KLAX,2026-10-02T20:53Z,80.6,,3,x,x\n"
        + "KLAX,2026-10-03T07:53Z,70,,3,x,x\n"  # 23:53 local on 10-02: inside
        + "KLAX,2026-10-03T08:53Z,95,,3,x,x\n"  # 00:53 local on 10-03: after the window
    )

    assert metar_daily_max(tmp_path, "KLAX", dt.date(2026, 10, 2), -8.0) == 81
    assert metar_daily_max(tmp_path, "KMIA", dt.date(2026, 10, 2), -5.0) is None


def test_metar_daily_max_mirrors_the_fq_window_and_ignores_days_outside_it(tmp_path: Path) -> None:
    station = tmp_path / "metar-routine" / "KLAX"
    station.mkdir(parents=True)
    (station / "2026.csv").write_text(
        _METAR_HEADER + "".join(
            f"KLAX,{d}T20:00Z,80,,3,x,x\n" for d in ("2026-09-30", "2026-10-01", "2026-10-07")
        )
    )  # fmt: skip

    assert metar_daily_max(tmp_path, "KLAX", dt.date(2026, 9, 30), -8.0) is None  # holdout side
    assert metar_daily_max(tmp_path, "KLAX", dt.date(2026, 10, 7), -8.0) is None  # after the clip
    assert metar_daily_max(tmp_path, "KLAX", dt.date(2026, 10, 1), -8.0) == 80


def _fake_records(days: list[tuple[str, str]]) -> list[Any]:
    from types import SimpleNamespace

    return [
        SimpleNamespace(
            fill_id=f"f{i}", station=st, climate_day=dt.date.fromisoformat(day), won=False,
            instrument_id=f"tc-temp-{st.lower()}high-{day}-gte80lt81f.POLYMARKET_US",
        )
        for i, (st, day) in enumerate(days)
    ]  # fmt: skip


def test_k3_flips_streams_and_reads_each_station_csv_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stations = {"LAX": "KLAX", "MDW": "KMDW", "MIA": "KMIA", "SFO": "KSFO"}
    archive = tmp_path / "archive"
    for icao in stations.values():
        folder = archive / "metar-routine" / icao
        folder.mkdir(parents=True)
        rows = "".join(f"{icao},2026-10-0{d}T20:00Z,80,,3,x,x\n" for d in (2, 3, 4))
        (folder / "2026.csv").write_text(_METAR_HEADER + rows)
    recs = _fake_records([(st, f"2026-10-0{d}") for st in stations for d in (2, 3, 4)])
    opened: list[str] = []
    real_open = Path.open

    def spy(self: Path, *a: Any, **k: Any) -> Any:
        if self.suffix == ".csv":
            opened.append(str(self))
        return real_open(self, *a, **k)

    def boom(*_a: Any, **_k: Any) -> str:
        raise AssertionError("read_text loads the whole CSV; stream it")

    monkeypatch.setattr(Path, "open", spy)
    monkeypatch.setattr(Path, "read_text", boom)

    flips = k3_flips(recs, archive, present=True)

    assert flips is not None and len(flips) == 12
    assert len(opened) == 4  # once per station file, not once per record


def test_k4_is_untestable_unless_phase_a_found_the_source_present(tmp_path: Path) -> None:
    from types import SimpleNamespace

    rec = SimpleNamespace(fill_id="f1", instrument_id="i1", won=True)
    venue = tmp_path / "venue.json"
    venue.write_text(json.dumps({"i1": False}))

    assert k4_mismatches([rec], venue, present=False) is None  # file exists; Phase A: UNTESTABLE
    assert k4_mismatches([rec], venue, present=True) == {"f1": True}
    assert k4_mismatches([rec], None, present=True) is None


@pytest.mark.parametrize("bad", ['{"i1": "false"}', '{"i1": 0}', '{"i1": null}', "[1]"])
def test_k4_rejects_non_boolean_or_non_object_venue_outcomes(tmp_path: Path, bad: str) -> None:
    from types import SimpleNamespace

    rec = SimpleNamespace(fill_id="f1", instrument_id="i1", won=True)
    venue = tmp_path / "venue.json"
    venue.write_text(bad)

    with pytest.raises(ValueError, match="venue"):
        k4_mismatches([rec], venue, present=True)


def _with_k4_present(table: Path, tmp: Path) -> Path:
    patched = json.loads(table.read_text())
    patched["s0g"]["k4_status"] = "SOURCE_PRESENT"
    out = tmp / "t_k4.json"
    out.write_text(json.dumps(patched))
    return out


def test_phase_b_ignores_a_venue_file_when_phase_a_did_not_find_the_source(
    phase_a: tuple[World, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, table = phase_a
    assert json.loads(table.read_text())["s0g"]["k4_status"] == "UNTESTABLE"
    flipped = next(i for i in fq_instrument_ids() if "miahigh-2026-10-03-gte86lt87" in i)
    venue = tmp_path / "venue.json"
    venue.write_text(json.dumps({flipped: False}))
    b = build_phase_b(tmp_path / "b", world, table)
    monkeypatch.setattr(cli, "_CatalogRouter", _router(_records()))

    assert cli.main(b.argv(extra=["--venue-outcomes", str(venue)])) == 0
    payload = json.loads(b.result_json.read_text())
    alt = payload["alt_truth"]
    assert alt["k4_status"] == "UNTESTABLE" and alt["k4_count"] is None
    assert payload["provenance"]["venue_outcomes_sha256"] is None


def test_phase_b_records_the_venue_file_hash_when_k4_is_tested(
    phase_a: tuple[World, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, table = phase_a
    venue = tmp_path / "venue.json"
    venue.write_text(json.dumps({fq_instrument_ids()[0]: True}))
    b = build_phase_b(tmp_path / "b", world, _with_k4_present(table, tmp_path))
    monkeypatch.setattr(cli, "_CatalogRouter", _router(_records()))

    assert cli.main(b.argv(extra=["--venue-outcomes", str(venue)])) == 0
    prov_block = json.loads(b.result_json.read_text())["provenance"]
    assert prov_block["venue_outcomes_sha256"] == sha256_path(venue)


def test_a_non_boolean_venue_outcome_is_a_stop_with_no_result(
    phase_a: tuple[World, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    world, table = phase_a
    venue = tmp_path / "venue.json"
    venue.write_text(json.dumps({fq_instrument_ids()[0]: "false"}))
    b = build_phase_b(tmp_path / "b", world, _with_k4_present(table, tmp_path))
    monkeypatch.setattr(cli, "_CatalogRouter", _router(_records()))

    assert cli.main(b.argv(extra=["--venue-outcomes", str(venue)])) == cli.EXIT_STOP
    assert "venue" in capsys.readouterr().err and not b.result_json.exists()


def test_a_passed_audit_is_recorded_as_phase_b_audit_json(
    completed: tuple[BPaths, dict[str, Any], str],
) -> None:
    b, _payload, _md = completed

    assert (b.out / "phase_b_audit.json").exists()
    assert not (b.out / "phase_b_audit_STOP.json").exists()


def test_the_cli_wires_both_clipping_sites_with_the_fq_window_start(
    phase_a: tuple[World, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.analysis.fq_loss_taxonomy_truth import ClippingSettlementSource

    seen: list[dt.date | None] = []

    class _Recording(ClippingSettlementSource):
        def __init__(self, inner: Any, last_day: dt.date, first_day: dt.date | None = None) -> None:
            seen.append(first_day)
            super().__init__(inner, last_day, first_day=first_day)

    world, table = phase_a
    b = build_phase_b(tmp_path, world, table)
    monkeypatch.setattr(cli, "ClippingSettlementSource", _Recording)
    monkeypatch.setattr(cli, "_CatalogRouter", _router(_records()))

    assert cli.main(b.argv()) == 0  # the Phase B site
    cli._truth_projection(tmp_path / "cat", [("LAX", dt.date(2026, 10, 2))])  # the Phase A site

    assert seen == [dt.date(2026, 10, 1)] * 2


def test_alternative_sources_flag_k3_and_k4_and_k4_makes_the_verdict_fixable(
    phase_a: tuple[World, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, table = phase_a
    patched = json.loads(table.read_text())
    patched["s0g"]["k3_status"] = "SOURCE_PRESENT"
    patched["s0g"]["k4_status"] = "SOURCE_PRESENT"
    table2 = tmp_path / "table_k3.json"
    table2.write_text(json.dumps(patched))
    archive = tmp_path / "archive"
    for station, icao in (("LAX", "KLAX"), ("MDW", "KMDW"), ("MIA", "KMIA"), ("SFO", "KSFO")):
        folder = archive / "metar-routine" / icao
        folder.mkdir(parents=True)
        rows = []
        for (st, day), tmax in FQ_TMAX.items():
            hot = 85 if (st, day) == ("MIA", dt.date(2026, 10, 3)) else tmax  # flips MIA 10-03
            if st == station:
                rows.append(f"{icao},{day.isoformat()}T20:00Z,{hot},,3,x,x\n")
        (folder / "2026.csv").write_text(_METAR_HEADER + "".join(rows))
    flipped = next(i for i in fq_instrument_ids() if "miahigh-2026-10-03-gte86lt87" in i)
    venue = tmp_path / "venue.json"
    venue.write_text(json.dumps({flipped: False}))
    b = build_phase_b(tmp_path / "b", world, table2)
    monkeypatch.setattr(cli, "_CatalogRouter", _router(_records()))

    argv = b.argv(extra=["--archive-root", str(archive), "--venue-outcomes", str(venue)])
    assert cli.main(argv) == 0
    payload = json.loads(b.result_json.read_text())
    assert payload["alt_truth"]["k3_status"] == "TESTED" and payload["alt_truth"]["k3_count"] == 2
    assert payload["alt_truth"]["k4_status"] == "TESTED" and payload["alt_truth"]["k4_count"] == 1
    assert payload["verdict"]["label"] == "FIXABLE_DEFECT"
    assert {c["finding"] for c in payload["consumers"]} >= {"FIXABLE_DEFECT", "K3", "K4"}
    assert payload["flag_counts"]["K3"] == 2 and payload["flag_counts"]["K4"] == 1


def test_delivery_states_a_slip_and_forward_route_sizes_the_plan() -> None:
    th = thresholds_block()

    assert delivery(th, dt.date(2026, 10, 20))["slip"] is None
    assert delivery(th, dt.date(2026, 10, 21))["slip"]
    near = forward_route([0.2] * 7, th)
    assert near["clusters_needed"] == 18 and near["route"] == "forward_evidence_plan_to_T2"
    far = forward_route([0.01] * 7, th)
    assert far["route"] == "closed_no_action_until_T1_12_07"
    assert forward_route([], th)["clusters_needed"] is None

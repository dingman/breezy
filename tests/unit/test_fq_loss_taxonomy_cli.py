"""TE-2 WP1b (RED then GREEN): the Phase A / Phase B CLI over a fully synthetic fixture tree.

Fill store from the real writer, nine boot logs, a derived NBP store written by the real
``write_partition``, a tmp git repo holding the real artefact, and a reflog snapshot that pins every
boot. Nothing touches the network, the live reflog or any holdout path.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import fq_v1_loss_taxonomy as cli
from tests.support.aut2_fixtures import seed_fills
from tests.support.te2_cli_fixtures import World, build_world
from tests.support.te2_fixtures import (
    fq_durable_fills,
    fq_september_fills,
    fq_settlement_records,
    nws_record,
    sha256_text,
    tmp_git_repo,
)

_OUTCOME_KEYS = {"tmax", "tmax_f", "win", "won", "wins", "n_wins", "pnl", "net_pnl", "audit_all"}
_FILL_FIELDS = {
    "instrument_id", "p_hat", "p_hat_reconstructed", "match", "s0d_class", "ask_proxy",
    "cycle_age_s", "newest_visible", "cycle_ns", "raw_sha256", "lower_f", "upper_f", "boot",
    "pinned_commit", "pin_state", "pin_label", "k1b", "q_f",
}  # fmt: skip
_DAY_FIELDS = {"station", "climate_day", "P_d", "pi_d", "q_d", "partition_rungs", "partition_complete"}
_CLUSTER_FIELDS = {"station", "climate_days", "P_d", "P_c", "q_c", "pi_min", "pi_max"}


def _policy(world: World) -> Any:
    return cli.PinPolicy(
        expected_commits=(world.commit[:12],) * 9, pin_range=(world.first_commit, world.commit)
    )


def _run(world: World, out: Path, **kw: Any) -> int:
    return cli.main(world.phase_a_argv(out), policy=kw.pop("policy", _policy(world)))


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in _keys(v)}
    return set()


@pytest.fixture(scope="module")
def phase_a(tmp_path_factory: pytest.TempPathFactory) -> tuple[World, dict[str, Any]]:
    root = tmp_path_factory.mktemp("phase_a")
    world = build_world(root / "w")
    out = root / "out"
    assert _run(world, out) == 0
    return world, json.loads((out / "phase_a_table.json").read_text())


def test_phase_a_emits_every_s0h_field_and_no_outcome_field(
    phase_a: tuple[World, dict[str, Any]],
) -> None:
    _world, table = phase_a

    assert table["phase"] == "A" and table["outcome_blind"] is True
    assert not _keys(table) & _OUTCOME_KEYS
    assert len(table["per_fill"]) == 25
    for row in table["per_fill"]:
        assert _FILL_FIELDS <= set(row), _FILL_FIELDS - set(row)
    assert all(_DAY_FIELDS <= set(d) for d in table["station_days"])
    assert all(_CLUSTER_FIELDS <= set(c) for c in table["clusters"])
    assert table["pin_label"] == "INFERRED"
    assert {r["pin_state"] for r in table["per_fill"]} == {"PINNED"}
    assert table["s0d"]["n_match"] == 25 and table["s0d"]["passed"] is True
    assert table["s0d"]["vectors"] and "pending_coordinator" not in table
    assert all(v["raw_sha256"] for v in table["s0d"]["vectors"])
    k1b = [r for r in table["per_fill"] if r["k1b"]]
    assert len(k1b) == 5


def test_phase_a_filters_the_34_fill_store_to_the_25_fq_fills(
    phase_a: tuple[World, dict[str, Any]],
) -> None:
    world, table = phase_a
    total = len(fq_durable_fills()) + len(fq_september_fills())

    assert total == 34 and len(world.cases) == 25
    assert table["s0c"]["n"] == 25 and table["s0c"]["matched"] == 25
    assert len(table["station_days"]) == 14 and len(table["clusters"]) == 7
    assert {r["instrument_id"][:20] for r in table["per_fill"]}.isdisjoint({"tc-temp-laxhigh-2026-09"})
    assert all("2026-09" not in r["instrument_id"] for r in table["per_fill"])


def test_phase_a_pin_table_and_partition_and_s0g_are_written(
    phase_a: tuple[World, dict[str, Any]],
) -> None:
    world, table = phase_a

    assert [p["commit"][:12] for p in table["pin_table"]] == [world.commit[:12]] * 9
    assert len(table["pin_table"]) == 9
    lax = next(d for d in table["station_days"] if d["station"] == "LAX" and d["climate_day"] == "2026-10-02")
    assert lax["partition_complete"] is True  # lt_69 + 70_99 (a Refuse line) + 100_gte
    mdw = next(d for d in table["station_days"] if d["station"] == "MDW" and d["climate_day"] == "2026-10-05")
    assert mdw["partition_complete"] is False
    assert table["s0g"]["k3_status"] == "UNTESTABLE" and table["s0g"]["k4_status"] == "UNTESTABLE"
    assert table["s0g"]["metar_last_valid"]["KLAX"] == "2026-06-30"


def test_s0g_reports_a_covering_metar_series_as_present(tmp_path: Path) -> None:
    world = build_world(tmp_path / "w")
    archive = world.archive_root / "metar-routine"
    for icao in ("KLAX", "KMDW", "KMIA", "KSFO"):
        (archive / icao).mkdir(exist_ok=True)
        (archive / icao / "2026.csv").write_text(
            "station,valid_utc,tmpf,tgroup_c,report_type,tmpf_source,metar\n"
            f"{icao},2026-10-06T23:53Z,68,20.0,3,tgroup,x\n"
        )
    out = tmp_path / "out"

    assert _run(world, out) == 0
    s0g = json.loads((out / "phase_a_table.json").read_text())["s0g"]
    assert s0g["k3_status"] == "SOURCE_PRESENT" and s0g["k4_status"] == "UNTESTABLE"


def test_reconstruction_positive_control_perturbed_vector_mismatches_and_is_k1a(
    tmp_path: Path,
) -> None:
    world = build_world(tmp_path / "w", perturb=[("LAX", dt.date(2026, 10, 4))])
    out = tmp_path / "out"

    assert _run(world, out) == 0  # 24 of 25 still clears the gate
    table = json.loads((out / "phase_a_table.json").read_text())
    bad = [r for r in table["per_fill"] if not r["match"]]
    assert table["s0d"]["n_match"] == 24 and len(bad) == 1
    assert bad[0]["s0d_class"] == "K1a" and abs(bad[0]["delta"]) > 1e-9


def test_s0d_untestable_bulletins_count_as_non_matches(tmp_path: Path) -> None:
    world = build_world(
        tmp_path / "w", drop_cycle=dt.date(2026, 10, 6), reissue=dt.date(2026, 10, 4)
    )
    out = tmp_path / "out"

    assert _run(world, out) == 2  # 5 + 4 untestable fills: 16 matches < 23
    assert not (out / "phase_a_table.json").exists()


def test_stop_below_23_matches_exits_with_the_stop_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = build_world(
        tmp_path / "w",
        perturb=[("LAX", dt.date(2026, 10, 4)), ("SFO", dt.date(2026, 10, 4)),
                 ("LAX", dt.date(2026, 10, 6))],
    )  # fmt: skip

    assert _run(world, tmp_path / "out") == cli.EXIT_STOP
    assert "S0-D" in capsys.readouterr().err


def test_a_pin_table_mismatch_a_missing_sha_or_a_wrong_log_count_is_a_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world = build_world(tmp_path / "w")
    wrong = cli.PinPolicy(("deadbeefcafe",) * 9, (world.first_commit, world.commit))
    assert _run(world, tmp_path / "o1", policy=wrong) == cli.EXIT_STOP
    assert "pin" in capsys.readouterr().err.lower()
    short = cli.PinPolicy((world.commit[:12],) * 8, (world.first_commit, world.commit))
    assert _run(world, tmp_path / "o2", policy=short) == cli.EXIT_STOP
    first = world.logs[0]
    first.write_text(
        "\n".join(ln for ln in first.read_text().splitlines() if "manifest_sha256" not in ln) + "\n"
    )
    assert _run(world, tmp_path / "o3") == cli.EXIT_STOP
    assert "sha" in capsys.readouterr().err.lower()


def test_default_policy_is_the_p7_table_of_nine_boots() -> None:
    assert len(cli.P7_POLICY.expected_commits) == 9
    assert cli.P7_POLICY.expected_commits[0] == "60290e9ddd29"
    assert cli.P7_POLICY.expected_commits[-1] == "4ba7f10cd1f6"
    assert (cli.EXPECTED_FQ_FILLS, cli.EXPECTED_FQ_WINS) == (25, 2)


def _phase_b_inputs(tmp: Path) -> tuple[Path, Path, Path]:
    repo = tmp / "repo"
    commits = tmp_git_repo(repo, ["{}\n"])
    pins = tmp / "pins.json"
    pins.write_text(
        json.dumps(
            {"head_blob_sha256": {"manifest.json": sha256_text("{}\n")},
             "predeclaration_commit": commits[0]}
        )  # fmt: skip
    )
    store = tmp / "exec.db"
    seed_fills(store, [*fq_durable_fills(), *fq_september_fills()])
    return repo, pins, store


def _phase_b_argv(repo: Path, pins: Path, store: Path, out: Path) -> list[str]:
    return [
        "phase-b", "--fills-db", str(store), "--output-dir", str(out), "--repo-root", str(repo),
        "--catalog-root", str(out), "--pins-json", str(pins), "--now-ns", "1800000000000000000",
    ]  # fmt: skip


def test_phase_b_refuses_without_pins(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, pins, store = _phase_b_inputs(tmp_path)
    (repo / "manifest.json").write_text("dirty\n")  # the pinned HEAD blob no longer matches
    assert cli.main(_phase_b_argv(repo, pins, store, tmp_path / "o1")) == cli.EXIT_STOP
    assert "PHASE B REFUSED" in capsys.readouterr().err
    pins.write_text(json.dumps({"head_blob_sha256": {}, "predeclaration_commit": "x"}))
    assert cli.main(_phase_b_argv(repo, pins, store, tmp_path / "o2")) == cli.EXIT_STOP
    assert "PHASE B REFUSED" in capsys.readouterr().err


def test_phase_b_reproduces_only_the_25_fq_fills_and_never_reads_pre_october_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, pins, store = _phase_b_inputs(tmp_path)
    records = {(r.station, r.climate_day): r for r in fq_settlement_records()}
    asked: list[dt.date] = []

    class _Router:
        def __init__(self, base: Path) -> None:
            pass

        def record(self, station: str, climate_day: dt.date) -> Any:
            asked.append(climate_day)
            assert climate_day >= dt.date(2026, 10, 1), "pre-October (holdout) truth was read"
            return records.get((station, climate_day)) or nws_record(station, climate_day, 0)

    monkeypatch.setattr(cli, "_CatalogRouter", _Router)
    out = tmp_path / "out"

    assert cli.main(_phase_b_argv(repo, pins, store, out)) == 0
    payload = json.loads((out / "phase_b_audit.json").read_text())
    assert "audit_all" not in payload
    assert payload["audit_fq"]["n_fills"] == 25 and payload["audit_fq"]["n_wins"] == 2
    assert asked and min(asked) >= dt.date(2026, 10, 1)


def test_unparseable_instrument_is_a_stop_not_a_bare_assert() -> None:
    from tests.support.te2_fixtures import fill_read

    bad = fq_durable_fills()[0]
    object.__setattr__(bad, "instrument_id", "garbage.POLYMARKET_US")
    with pytest.raises(cli.UnparseableInstrumentStop):
        cli._station_day_table(fill_read([bad]), [0.3])


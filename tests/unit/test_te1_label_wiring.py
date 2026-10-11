"""TE-1 WP-A: the production wiring of the label run (R4 lag, R11 straddle, the default factory).

The 34-fill ledger of 2026-10-11 is rebuilt on the real latch, fill and scored-trial writers
(``tests/support/te1_fixtures.py``). The L-55 rule holds throughout: the planner's key check is the
production ``latch_key_exists`` against a real SQLite store, never a lambda, and one test drives
``label_run.main`` through the production default factory.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import datetime as dt
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from breezy.analysis.autonomy.offline_plugins import OFFLINE_PLUGINS
from breezy.analysis.labeling import settlement_source, unit_factory_default, unit_wiring
from breezy.analysis.labeling.attribution import BridgeBasis, PreEpochAttribution
from breezy.analysis.labeling.constants import LABEL_MEMORY_TARGET_GIB
from breezy.analysis.labeling.epoch import C1Epoch
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.labeling.label_core import LabelRunDeps, run_labels
from breezy.analysis.labeling.label_run import (
    LABEL_UNIT,
    WP7_ACTIVE,
    MeasureSeams,
    StudiesFlock,
    UnitContext,
    UnitWiring,
    main,
)
from breezy.analysis.labeling.legacy_join import (
    LegacyAttributionDisagreement,
    legacy_join,
)
from breezy.analysis.labeling.memory_gate import label_slot_held
from breezy.analysis.labeling.settlement_source import NwsCliFinal, RefusingSettlementSource
from breezy.analysis.labeling.unit_factory_default import FactorySeams
from breezy.analysis.labeling.unit_wiring import (
    HostSeamsRefused,
    LagRule,
    ProducerUnpinned,
    StationCatalogSettlements,
    activation_ns,
    build_planner,
    family_infos,
    fill_deadline_ns,
    row_deadline_ns,
)
from breezy.persistence import scored_trial_dedupe
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole
from breezy.persistence.autonomy.label_store import (
    MarkerCorrupt,
    RunMarker,
    RunOutcome,
    admissible_rows,
    oldest_marker_ns,
    read_labels,
    write_marker,
)
from breezy.persistence.catalog import station_catalog_path
from breezy.runtime.health import LoggingAlertSink
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.trial_day_latch import TrialDayRecord, open_trial_day_latch
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
    PersistentQuantileLadderLatch,
)
from tests.support.aut2_fixtures import durable_fill, seed_fills
from tests.support.aut2_run_fixtures import Sink, verdict_wires
from tests.support.te1_fixtures import (
    FAMILIES_DIR,
    FQ_POST_TERMINAL_IDS,
    MapSettlements,
    World,
    build_world,
    day_start_ns,
    load_repo_manifests,
    slug,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_IN_UNIT = UnitContext(invocation_id="inv-1", cgroup_path=f"/user.slice/{LABEL_UNIT}.service")
_VENUE = "polymarket_us"
_FQ_KIND = "forecast_quantile_ladder"
_GIB = 1024**3
_PINNED = (True, "ab" * 32)
_UNPINNED = (False, "0" * 64)
_STATIONS = ("LAX", "MDW", "MIA", "SFO")
_HOUR_NS = 3_600_000_000_000


# -- shared builders ---


@pytest.fixture
def world(tmp_path: Path) -> World:
    return build_world(tmp_path)


def _evidence(world: World) -> C1Epoch:
    return C1Epoch(world.data_root, venue=_VENUE, family_id="pm_us_crh_fq_v1")


def _lag(world: World) -> LagRule:
    return LagRule(activation_ns=world.now_ns, deadline_of=fill_deadline_ns(_VENUE))


def _planner(world: World, **over: Any) -> Any:
    manifests = load_repo_manifests()
    base: dict[str, Any] = {
        "exec_db": world.exec_db,
        "venue": _VENUE,
        "manifests": manifests,
        "families": family_infos(manifests),
        "evidence": _evidence(world),
        "scored_trials": world.scored,
        "release_ns": fill_deadline_ns(_VENUE),
        "lag_rule": _lag(world),
    }
    base.update(over)
    return build_planner(**base)


def _deps(world: World, **over: Any) -> LabelRunDeps:
    manifests = load_repo_manifests()
    base: dict[str, Any] = {
        "data_root": world.data_root,
        "exec_db": world.exec_db,
        "now_ns": world.now_ns,
        "venue": _VENUE,
        "registry": OFFLINE_PLUGINS,
        "families": lambda: family_infos(manifests),
        "plan": _planner(world),
        "settlements": world.settlements,
        "deliver": Sink(),
        "deadline_ns": row_deadline_ns(_VENUE),
        "lag_start_ns": _lag(world),
        "producer_code_sha": "c" * 64,
        "subject_artefact_sha256": None,
    }
    base.update(over)
    return LabelRunDeps(**base)


class _CatalogReader:
    """Stands in for the parquet reader: serves the world's settlements by (station, day)."""

    def __init__(self, world: World) -> None:
        self._world = world

    def __call__(self, catalog: Any, *, station: str, climate_day: dt.date) -> Any:
        return self._world.settlements.record(station, climate_day)


def _seams(world: World, tmp_path: Path, **over: Any) -> FactorySeams:
    base_dir = tmp_path / "catalog"
    for station in _STATIONS:
        station_catalog_path(base_dir, _VENUE, station).mkdir(parents=True, exist_ok=True)
    cgroup = tmp_path / "cg" / "user.slice" / f"{LABEL_UNIT}.service"
    cgroup.mkdir(parents=True, exist_ok=True)
    (cgroup / "memory.max").write_text(f"{3 * _GIB}\n")
    base: dict[str, Any] = {
        "data_root": world.data_root,
        "exec_db": world.exec_db,
        "families_dir": FAMILIES_DIR,
        "scored_trials_dir": world.scored_dir,
        "catalog_base": base_dir,
        "lock_path": tmp_path / "studies.lock",
        "alerts_root": tmp_path / "alerts",
        "proc_cgroup_text": f"0::/user.slice/{LABEL_UNIT}.service\n",
        "cgroup_root": tmp_path / "cg",
        "open_catalog": lambda base, venue, city: (base, venue, city),
        "make_sink": LoggingAlertSink,
        "time_ns": lambda: world.now_ns,
        "snapshot": _unused_snapshot,
    }
    base.update(over)
    return FactorySeams(**base)


@contextlib.contextmanager
def _unused_snapshot(data_root: Path, cache_dir: Path) -> Iterator[Path]:
    raise AssertionError("the exec store snapshot must not be taken when --exec-db is given")
    yield Path()  # pragma: no cover


def _args(world: World, **over: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "data_root": world.data_root,
        "exec_db": world.exec_db,
        "venue": _VENUE,
        "family": "pm_us_crh_fq_v1",
        "now_ns": world.now_ns,
        "slot_ns": None,
        "output_root": None,
    }
    base.update(over)
    return argparse.Namespace(**base)


def _patch_production_seams(
    monkeypatch: pytest.MonkeyPatch, world: World, tmp_path: Path, **over: Any
) -> FactorySeams:
    seams = _seams(world, tmp_path, **over)
    monkeypatch.setattr(unit_factory_default, "default_seams", lambda: seams)
    monkeypatch.setattr(
        settlement_source, "read_climate_day_including_corrections", _CatalogReader(world)
    )
    return seams


def _run_args(world: World) -> list[str]:
    return [
        "--data-root",
        str(world.data_root),
        "--exec-db",
        str(world.exec_db),
        "--now-ns",
        str(world.now_ns),
    ]


# -- the planner (R11, legacy join) ---


def test_planner_pre_epoch_fq_fill_bridges_to_v1(tmp_path: Path) -> None:
    world = build_world(tmp_path, with_post_terminal=False)

    plan = _planner(world)(world.fills)

    inputs = plan.inputs_by_kind.get(_FQ_KIND, ())
    assert len(inputs) == 20
    assert {i.attribution.storage_key for i in inputs} == {"pm_us_crh_fq_v1"}
    assert {i.attribution.basis for i in inputs} == {BridgeBasis.BRIDGE}
    assert {plan.fill_kinds[i.fill.client_order_id] for i in inputs} == {_FQ_KIND}


def test_planner_post_terminal_fq_fills_bridge_to_v1_and_count_logged(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _planner(world)(world.fills)  # production latch_key_exists over the real latch store

    straddle = [
        i
        for i in plan.inputs_by_kind.get(_FQ_KIND, ())
        if isinstance(i.attribution, PreEpochAttribution)
        and i.attribution.basis is BridgeBasis.BRIDGE_POST_TERMINAL
    ]
    assert {i.fill.client_order_id for i in straddle} == FQ_POST_TERMINAL_IDS
    assert {i.attribution.storage_key for i in straddle} == {"pm_us_crh_fq_v1"}
    assert "AUT2 PRE_EPOCH_BRIDGE basis=bridge_post_terminal n=5\n" in capsys.readouterr().out


def test_planner_legacy_crh_fill_joins_frozen_scored_trial(world: World) -> None:
    plan = _planner(world)(world.fills)

    legacy = [
        i
        for kind in ("current_rung_hold", "continuous_rung_hold")
        for i in plan.inputs_by_kind.get(kind, ())
    ]
    by_coid = {i.fill.client_order_id: i for i in legacy}
    assert len(legacy) == 9
    mdw = by_coid["O-L2"]  # MDW 2026-09-15: inside pm_us_crh_cont's window, instrument-keyed latch
    assert mdw.label_family == "pm_us_crh_cont"
    assert mdw.scored is world.scored[mdw.trial_id]
    assert by_coid["O-L5"].trial_id.startswith("continuous_rung_hold/trial/SFO/2026-09-15/")
    assert by_coid["O-L7"].label_family == "pm_us_crh_v4"  # 2026-09-21: after pm_us_crh_cont ended
    assert sum(1 for i in legacy if i.scored is not None) == 7


def test_planner_residual_fill_gets_null_pnl_legacy_row_not_missing(world: World) -> None:
    result = run_labels(_deps(world))

    assert result.coverage is not None and result.coverage.missing_label == 0
    rows = {r.client_order_id: r for r in read_labels(world.data_root)}
    for coid in ("O-L0", "O-L1"):  # the two residual fills: station-day keys, no ScoredTrial
        assert rows[coid].scorer_id == "legacy_crh/v1"
        assert rows[coid].realized_pnl is None
        assert rows[coid].excluded_reason is ExcludedReason.UNATTRIBUTED
    assert rows["O-L2"].realized_pnl is not None


def test_planner_unbridgeable_fill_is_unresolved(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    stray = durable_fill(
        venue_order_id="vo-stray",
        client_order_id="O-stray",
        instrument_id=slug("LAX", "2026-10-03", 99),  # no latch key of any family
        ts_event=day_start_ns("2026-10-03", 15),
    )
    seed_fills(world.exec_db, [stray])

    plan = _planner(world)((*world.fills, stray))

    assert [r.rule_outcomes for r in plan.unresolved] == [("no_backfill_family",)]
    assert plan.unresolved_fill_keys == frozenset({"vo-stray"})
    assert "O-stray" not in plan.fill_kinds


def test_planner_disagreement_fails_the_run_closed(tmp_path: Path) -> None:
    """A legacy latch that no manifest window covers is refused: exit 1, no marker, a CRITICAL."""
    clean = build_world(tmp_path / "clean")
    assert run_labels(_deps(clean)).exit_code == 0  # the control: the clean world labels

    bad = build_world(tmp_path / "bad")
    stray = _legacy_fill_with_latch(
        bad.exec_db, "SFO", "2026-09-10", prefix="continuous_rung_hold/trial/"
    )
    seed_fills(bad.exec_db, [stray])
    sink = Sink()

    result = run_labels(_deps(bad, deliver=sink))

    assert result.exit_code == 1 and result.marker_path is None
    assert "AUT2 INPUT_UNREADABLE input=plan cause=LegacyAttributionDisagreement" in result.lines
    assert "aut2.label_input_unreadable" in sink.events


# -- legacy_join ---


def _legacy_fill_with_latch(
    exec_db: Path,
    station: str,
    day: str,
    *,
    prefix: str,
    venue_order_id: str = "vo-stray-legacy",
    latch_venue_order_id: str | None = None,
    station_day_key: bool = False,
) -> Any:
    fill = durable_fill(
        venue_order_id=venue_order_id,
        client_order_id="O-stray-legacy",
        instrument_id=slug(station, day, 70),
        ts_event=day_start_ns(day, 15),
    )
    with open_submit_intent_latch(SqliteStateStore(exec_db), exec_db) as intent:
        trial = open_trial_day_latch(intent, key_prefix=prefix, family_id="pm_us_crh_te1_fixture")
        trial.consume_if_absent(
            station,
            day,
            TrialDayRecord(
                latched_at_ns=fill.ts_event,
                instrument_id=fill.instrument_id,
                ask=Decimal("0.4"),
                reason="taken",
                venue_order_id=latch_venue_order_id,
            ),
            key_instrument_id=None if station_day_key else fill.instrument_id,
        )
    return fill


def test_legacy_join_matches_latch_row_with_null_venue_order_id(world: World) -> None:
    fill = next(f for f in world.fills if f.client_order_id == "O-L0")  # SFO 2026-09-11 shape

    joined = legacy_join(
        fill,
        load_repo_manifests(),
        exec_db=world.exec_db,
        venue=_VENUE,
        scored_by_trial_id=world.scored,
    )

    assert joined is not None
    assert joined.kind == "current_rung_hold"
    assert joined.fill_input.label_family == "pm_us_crh_v2"
    assert joined.fill_input.trial_id == "current_rung_hold/trial/SFO/2026-09-11"
    assert joined.fill_input.scored is None  # a residual: no frozen ScoredTrial


def test_legacy_join_refuses_on_trial_id_disagreement(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    fill = _legacy_fill_with_latch(
        world.exec_db, "SFO", "2026-09-10", prefix="continuous_rung_hold/trial/"
    )  # 2026-09-10 precedes pm_us_crh_cont (2026-09-12): no manifest names this latch

    with pytest.raises(LegacyAttributionDisagreement):
        legacy_join(
            fill,
            load_repo_manifests(),
            exec_db=world.exec_db,
            venue=_VENUE,
            scored_by_trial_id=world.scored,
        )


def test_legacy_join_refuses_when_non_null_venue_order_id_disagrees(tmp_path: Path) -> None:
    world = build_world(tmp_path)
    fill = _legacy_fill_with_latch(
        world.exec_db,
        "SFO",
        "2026-09-16",
        prefix="continuous_rung_hold/trial/",
        latch_venue_order_id="vo-someone-else",
    )

    with pytest.raises(LegacyAttributionDisagreement):
        legacy_join(
            fill,
            load_repo_manifests(),
            exec_db=world.exec_db,
            venue=_VENUE,
            scored_by_trial_id=world.scored,
        )


def test_legacy_join_returns_none_for_a_fill_with_no_legacy_latch(world: World) -> None:
    fill = next(f for f in world.fills if f.client_order_id == "O-FQ-03-0")

    assert (
        legacy_join(
            fill,
            load_repo_manifests(),
            exec_db=world.exec_db,
            venue=_VENUE,
            scored_by_trial_id=world.scored,
        )
        is None
    )


# -- the default factory and its seams ---


def test_wiring_settlements_is_nws_cli_final_for_polymarket_us(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seams = _patch_production_seams(monkeypatch, world, tmp_path)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)

    wiring = unit_factory_default.factory(_args(world), seams)

    settlements = wiring.deps.settlements
    assert isinstance(settlements, StationCatalogSettlements)
    assert isinstance(settlements.source_for("LAX"), NwsCliFinal)
    record = settlements.record("LAX", dt.date(2026, 10, 2))
    assert record is not None and record.station == "LAX"
    assert seams.catalog_base.is_dir()
    assert settlements.record("NYC", dt.date(2026, 10, 2)) is None  # no catalog dir: pending
    kalshi = unit_factory_default.factory(_args(world, venue="kalshi"), seams)
    assert isinstance(kalshi.deps.settlements.source_for("LAX"), RefusingSettlementSource)


def test_wiring_deliver_is_deliver_with_proof(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seams = _patch_production_seams(monkeypatch, world, tmp_path)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)
    calls: list[dict[str, Any]] = []

    def fake(sink: object, payload: Any, **kw: Any) -> Any:
        calls.append({"sink": sink, "payload": payload, **kw})
        return SimpleNamespace(delivered=True, status_class="2xx")

    monkeypatch.setattr(unit_wiring, "deliver_with_proof", fake)
    wiring = unit_factory_default.factory(_args(world), seams)

    proof = wiring.deps.deliver(
        {"event": "aut2.unresolved_fill", "severity": "CRITICAL", "subject": "abc"}
    )

    assert proof is not None and proof.delivered is True and proof.status_class == "2xx"
    (call,) = calls
    assert (call["payload"].severity, call["payload"].event, call["payload"].site) == (
        "CRITICAL",
        "aut2.unresolved_fill",
        "abc",
    )
    assert call["writer"] == "aut2_label" and call["attempt_kind"] == "alert"
    assert call["records"].root == seams.alerts_root and call["outbox"].root == seams.alerts_root


def test_wiring_memory_gate_holds_above_4gib_without_aut6_reading(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)
    seams = _patch_production_seams(monkeypatch, world, tmp_path)
    (seams.cgroup_root / "user.slice" / f"{LABEL_UNIT}.service" / "memory.max").write_text(
        f"{8 * _GIB}\n"
    )

    wiring = unit_factory_default.factory(_args(world), seams)

    assert wiring.unit_max_bytes == 8 * _GIB
    hold = label_slot_held(unit_max_bytes=wiring.unit_max_bytes, aut6=wiring.aut6)
    assert hold is not None and hold.cause == "memory_gate" and hold.reason == "verdict_missing"
    # positive control: a unit capped at the 4 GiB target needs no AUT-6 verdict
    cap = seams.cgroup_root / "user.slice" / f"{LABEL_UNIT}.service" / "memory.max"
    cap.write_text(f"{LABEL_MEMORY_TARGET_GIB * _GIB}\n")
    capped = unit_factory_default.factory(_args(world), seams)
    assert label_slot_held(unit_max_bytes=capped.unit_max_bytes, aut6=capped.aut6) is None
    # an unbounded unit (memory.max = max) fails closed
    cap.write_text("max\n")
    unbounded = unit_factory_default.factory(_args(world), seams)
    assert label_slot_held(unit_max_bytes=unbounded.unit_max_bytes, aut6=unbounded.aut6) is not None


def test_wiring_proof_window_none_while_wp7_inactive(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seams = _patch_production_seams(monkeypatch, world, tmp_path)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)

    wiring = unit_factory_default.factory(_args(world), seams)

    assert WP7_ACTIVE is False
    assert wiring.proof_window is None and wiring.measured_peak_bytes is None


def test_wiring_producer_sha_is_pinned_closure_sha(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seams = _patch_production_seams(monkeypatch, world, tmp_path)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)

    wiring = unit_factory_default.factory(_args(world), seams)

    assert wiring.deps.producer_code_sha == "ab" * 32


def test_factory_returns_unit_wiring_with_every_field_real(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seams = _patch_production_seams(monkeypatch, world, tmp_path)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)

    wiring = unit_factory_default.factory(_args(world, slot_ns=77), seams)

    assert isinstance(wiring, UnitWiring)
    deps = wiring.deps
    assert (deps.data_root, deps.exec_db, deps.now_ns, deps.venue) == (
        world.data_root,
        world.exec_db,
        world.now_ns,
        _VENUE,
    )
    assert deps.registry is OFFLINE_PLUGINS
    assert {(f.family_id, f.kind, f.retired) for f in deps.families()} == {
        ("pm_us_crh_fq_v1", _FQ_KIND, False),
        ("pm_us_crh_v4", "continuous_rung_hold", True),
        ("pm_us_crh_cont", "continuous_rung_hold", True),
        ("pm_us_crh_v2", "current_rung_hold", True),
    }
    assert isinstance(wiring.lock, StudiesFlock)
    assert wiring.lock._path == seams.lock_path
    assert wiring.slot_ns == 77
    assert (
        isinstance(deps.lag_start_ns, LagRule) and deps.lag_start_ns.activation_ns == world.now_ns
    )
    plan = deps.plan(world.fills)
    assert sum(len(v) for v in plan.inputs_by_kind.values()) == 34
    assert deps.deadline_ns(_stand_in_row()) > 0


def _stand_in_row() -> Any:
    """The two attributes ``row_deadline_ns`` reads from a label row."""
    return SimpleNamespace(station="LAX", climate_day="2026-10-02")


def test_factory_snapshots_exec_store_when_no_exec_db_is_given(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered: list[tuple[Path, Path]] = []

    @contextlib.contextmanager
    def snapshot(data_root: Path, cache_dir: Path) -> Iterator[Path]:
        entered.append((data_root, cache_dir))
        yield world.exec_db

    seams = _patch_production_seams(monkeypatch, world, tmp_path, snapshot=snapshot)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)

    wiring = unit_factory_default.factory(_args(world, exec_db=None), seams)

    assert wiring.deps.exec_db == world.exec_db
    assert entered == [(world.data_root, world.data_root / "cache" / "label_run_snapshot")]


def test_unpinned_producer_refuses_with_exit_2(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_production_seams(monkeypatch, world, tmp_path)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _UNPINNED)
    data_root = tmp_path / "d"

    rc = main(
        ["--data-root", str(data_root), "--exec-db", str(tmp_path / "e")], unit_context=_IN_UNIT
    )

    assert rc == 2
    assert "LABEL_OUTCOMES REFUSED reason=producer_unpinned" in capsys.readouterr().out
    assert not data_root.exists()
    with pytest.raises(ProducerUnpinned):
        unit_factory_default.factory(_args(world), _seams(world, tmp_path))


def test_default_mode_outside_the_real_unit_never_touches_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An injected in-unit context cannot make the production host seams readable: the default
    seams re-check the REAL process context, and this process is a test, not the label unit.

    Without the check, a pinned ``label_run`` run from a test would take the host studies flock,
    write a hold journal into the live data root and page the operator (it did, once, in the
    gate): the tripwire below fails the test BEFORE any such write if the check is ever dropped.
    """
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)

    def tripwire(self: StudiesFlock, wait_s: float) -> bool:
        raise AssertionError("the production factory reached the host studies flock")

    monkeypatch.setattr(StudiesFlock, "acquire", tripwire)
    data_root = tmp_path / "d"
    data_root.mkdir(mode=0o700)

    rc = main(
        ["--data-root", str(data_root), "--exec-db", str(tmp_path / "e")], unit_context=_IN_UNIT
    )

    assert rc == 2 and "LABEL_OUTCOMES REFUSED reason=not_under_unit" in capsys.readouterr().out
    assert list(data_root.iterdir()) == []
    with pytest.raises(HostSeamsRefused):
        unit_factory_default.default_seams()


def test_measure_peak_with_unpinned_producer_fails_closed(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_production_seams(monkeypatch, world, tmp_path)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _UNPINNED)
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable:   40000000 kB\n")
    seams = MeasureSeams(meminfo, lambda: 0, "0::/user.slice/run-r1.service\n", tmp_path / "cg")
    out_root = tmp_path / "out"

    rc = main(
        ["--measure-peak", "--output-root", str(out_root), *_run_args(world)],
        unit_context=UnitContext("inv-1", "/user.slice/run-r1.service"),
        measure_seams=seams,
    )

    assert rc == 2
    assert "LABEL_OUTCOMES REFUSED reason=producer_unpinned" in capsys.readouterr().out
    assert not out_root.exists()


def test_main_under_unit_runs_production_factory(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """L-55: the production default factory, the production planner and the production
    ``latch_key_exists``; only the host paths and the catalog reader are substituted."""
    _patch_production_seams(monkeypatch, world, tmp_path)
    monkeypatch.setattr(unit_wiring, "producer_pin_state", lambda: _PINNED)

    rc = main(_run_args(world), unit_context=_IN_UNIT)

    out = capsys.readouterr().out
    assert rc == 0, out
    assert (
        "LABEL_OUTCOMES run_outcome=LABELLED durable_fill_count=34 labelled_final=34 "
        "pending=0 unresolved=0 missing_label=0"
    ) in out
    assert "AUT2 PRE_EPOCH_BRIDGE basis=bridge_post_terminal n=5\n" in out
    assert "AUT2 LAG_BACKLOG n=25\n" in out
    rows = read_labels(world.data_root)
    fq = [r for r in rows if r.scorer_id == "forecast_quantile_ladder/v1"]
    assert len(fq) == 25 and len(rows) == 34
    assert {r.excluded_reason for r in fq} == {ExcludedReason.UNATTRIBUTED}
    assert all(r.realized_pnl is not None and not r.admissible for r in fq)
    lag = [v for v in verdict_wires(world.data_root) if v.get("detector") == "aut2.label_lag"]
    assert lag and {v["outcome"] for v in lag} == {"PASS"}
    assert {v["producer_code_sha"] for v in lag} == {"ab" * 32}


def test_label_run_unit_wiring_and_factory_import_standalone() -> None:
    """One subprocess per module, against THIS tree (never the primary checkout): a module-level
    import cycle between ``label_run`` and the default factory would break the first import."""
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT / "src")}
    for module in (
        "breezy.analysis.labeling.unit_wiring",
        "breezy.analysis.labeling.unit_factory_default",
        "breezy.analysis.labeling.legacy_join",
        "breezy.analysis.labeling.label_run",
    ):
        done = subprocess.run(
            [sys.executable, "-c", f"import {module} as m; print(m.__file__)"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, (module, done.stderr[-400:])
        assert Path(done.stdout.strip()).is_relative_to(_REPO_ROOT / "src"), done.stdout


# -- R4: the label-lag clock ---


def test_lag_backlog_fill_starts_at_first_activation() -> None:
    activation = day_start_ns("2026-10-11", 14)
    deadline = day_start_ns("2026-10-03", 12)
    rule = LagRule(activation_ns=activation, deadline_of=lambda fill: deadline)
    old = durable_fill(ts_event=day_start_ns("2026-10-02", 15))

    assert rule(old) == activation  # the plain rule (the deadline) would start the clock 8 days ago
    assert rule.rule(old) == deadline
    assert rule.is_raised(old) is True


def test_lag_post_activation_fill_still_lag_checked() -> None:
    activation = day_start_ns("2026-10-11", 14)
    deadline = activation - 10 * _HOUR_NS  # a fill after activation whose settlement already passed
    rule = LagRule(activation_ns=activation, deadline_of=lambda fill: deadline)
    fresh = durable_fill(ts_event=activation + 1)

    assert rule(fresh) == deadline  # unraised: the plain rule applies to a post-activation fill
    assert rule.is_raised(fresh) is False
    early = LagRule(
        activation_ns=activation,
        deadline_of=lambda fill: deadline,
        first_record_ns=lambda fill: deadline - 5,
    )
    assert early(fresh) == deadline - 5  # min(first record, deadline), as verdicts.lag_start_ns


def test_lag_anchor_ignores_measure_output_root_markers(tmp_path: Path) -> None:
    live, measure = tmp_path / "live", tmp_path / "measure"
    for root in (live, measure):
        root.mkdir(mode=0o700)
    marker = RunMarker(RunOutcome.LABELLED, 1, None, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    write_marker(measure, marker, day="2026-10-01", now_ns=100)  # a measure-peak run, older
    write_marker(live, marker, day="2026-10-05", now_ns=500)
    write_marker(live, marker, day="2026-10-07", now_ns=900)

    assert activation_ns(live, now_ns=10_000) == 500
    fresh = tmp_path / "fresh"
    fresh.mkdir(mode=0o700)
    assert activation_ns(fresh, now_ns=10_000) == 10_000  # no marker yet: this run's own clock


def test_oldest_marker_ns_raises_on_corrupt_name(tmp_path: Path) -> None:
    marker = RunMarker(RunOutcome.LABELLED, 1, None, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    write_marker(tmp_path, marker, day="2026-10-05", now_ns=500)
    assert oldest_marker_ns(tmp_path) == 500
    empty = tmp_path / "empty"
    empty.mkdir(mode=0o700)
    assert oldest_marker_ns(empty) is None
    bad = tmp_path / "derived" / "label_outcomes" / "2026-10-05" / "marker_notanumber.json"
    bad.write_text("{}")

    with pytest.raises(MarkerCorrupt):
        oldest_marker_ns(tmp_path)


def test_lag_backlog_counts_only_non_retired_family_fills(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    _planner(world)(world.fills)

    out = capsys.readouterr().out
    assert "AUT2 LAG_BACKLOG n=25\n" in out  # 25 FQ fills; the 9 retired-family CRH fills excluded


# -- fills, L-44, the closure, the move ---


@pytest.mark.parametrize("tmax", [88, 89, 90, 91])
def test_no_leg_buy_pays_one_when_yes_false(tmp_path: Path, tmax: int) -> None:
    """L-44: a NO BUY pays 1 iff the YES bucket is false; the expectation is read from
    ``bucket_facts_from_instrument_id``, never from a hand-written band."""
    world = build_world(tmp_path)
    no_fill = durable_fill(
        venue_order_id="vo-no",
        client_order_id="O-no",
        instrument_id="tc-temp-laxhigh-2026-10-03-gte89lt90f^no.POLYMARKET_US",
        cost=Decimal("0.40"),
        fee=Decimal("0.03"),
        ts_event=day_start_ns("2026-10-03", 16),
    )
    seed_fills(world.exec_db, [no_fill])
    with open_submit_intent_latch(SqliteStateStore(world.exec_db), world.exec_db) as intent:
        trial = open_trial_day_latch(
            intent, key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX, family_id="pm_us_fq_no_te1"
        )
        PersistentQuantileLadderLatch(trial).latch(
            station="LAX", climate_day=dt.date(2026, 10, 3), rung_id="89_90", side="no"
        )
    facts = bucket_facts_from_instrument_id(no_fill.instrument_id)
    assert facts is not None
    payout = Decimal(0) if facts.contains(tmax) else Decimal(1)
    settlements = MapSettlements({**world.settlements._tmax, ("LAX", "2026-10-03"): tmax})

    result = run_labels(_deps(world, settlements=settlements))

    assert result.exit_code == 0 and result.coverage is not None
    assert result.coverage.durable_fill_count == 35 and result.coverage.missing_label == 0
    row = next(r for r in read_labels(world.data_root) if r.client_order_id == "O-no")
    assert row.leg == "no" and row.role is LabelRole.ENTRY
    assert row.realized_pnl == payout - Decimal("0.40") - Decimal("0.03")


def test_aut2_label_closure_has_no_quote_tape_module() -> None:
    from breezy.persistence.autonomy.closure import closure_from_grimp

    modules = closure_from_grimp("breezy.analysis.labeling.label_run")

    assert "breezy.analysis.labeling.unit_wiring" in modules  # the lazy imports are inside it
    assert "breezy.analysis.labeling.unit_factory_default" in modules
    assert [m for m in modules if "quote_tape" in m] == []


def test_moved_dedupe_lives_in_persistence() -> None:
    prr = _portfolio_roi_module()

    assert prr.dedupe_scored_trials.__module__ == "breezy.persistence.scored_trial_dedupe"


def test_moved_dedupe_names_are_re_exported_by_the_script() -> None:
    prr = _portfolio_roi_module()
    for name in (
        "dedupe_scored_trials",
        "_scored_trial_economic_fingerprint",
        "_SCORED_TRIAL_ECONOMIC_FIELDS",
        "DuplicateScoredTrialEconomicsMismatchError",
        "_default_scored_trials_dir",
    ):
        moved = getattr(scored_trial_dedupe, name, None)
        assert moved is not None, name
        assert getattr(prr, name) is moved, name


def _portfolio_roi_module() -> Any:
    from tests.support.aut2_fixtures import portfolio_roi_module

    return portfolio_roi_module()


def test_post_terminal_rows_excluded_from_every_label_consumer(tmp_path: Path) -> None:
    """Adding the five straddle fills moves the P&L consumer and nothing else: no row of them is
    admissible, so ``admissible_rows`` (the only statistics selector) is unchanged."""
    with_five = build_world(tmp_path / "a")
    without = build_world(tmp_path / "b", with_post_terminal=False)

    run_labels(_deps(with_five))
    run_labels(_deps(without))

    rows_with = read_labels(with_five.data_root)
    rows_without = read_labels(without.data_root)
    five = [r for r in rows_with if r.client_order_id in FQ_POST_TERMINAL_IDS]
    assert len(five) == 5 and len(rows_with) - len(rows_without) == 5
    assert all(not r.admissible and r.excluded_reason is ExcludedReason.UNATTRIBUTED for r in five)
    assert all(r.decision_id is None for r in five)
    assert admissible_rows(rows_with) == admissible_rows(rows_without) == ()


def test_not_wired_refusal_is_gone_from_src_and_tests() -> None:
    pattern = re.compile(r"\bnot" + r"_wired\b")
    hits = [
        f"{path.relative_to(_REPO_ROOT)}:{lineno}"
        for root in (_REPO_ROOT / "src", _REPO_ROOT / "tests")
        for path in sorted(root.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert hits == []


def test_no_label_wiring_module_reads_storage_key() -> None:
    """The AST guard of ``test_aut2_attribution`` extends to the new modules: the planner reads
    ``.basis`` and never the storage key."""
    root = _REPO_ROOT / "src" / "breezy" / "analysis" / "labeling"
    for name in ("unit_wiring.py", "unit_factory_default.py", "legacy_join.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        offenders = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr == "storage_key"
        ]
        assert offenders == [], name

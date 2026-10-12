"""The TE-1 WP-B report world: the 34-fill ledger, labelled, with the two residual fills recorded.

Builds on ``tests/support/te1_fixtures.py`` (real fill, latch and scored-trial writers). The label
run is driven through ``label_core.run_labels`` exactly as the WP-A tests drive it, the two
fee-unverified residual fills get the real ``excluded_fills.jsonl`` writer, and the report is run
through ``portfolio_roi_report._run`` with every host seam injected (L-57): the catalog, the CLI
FINAL reader, the labels root, the output root and the alert sink are all under ``tmp_path``.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from breezy.analysis.autonomy.offline_plugins import OFFLINE_PLUGINS
from breezy.analysis.labeling.attribution import BridgeBasis, PreEpochAttribution, fill_key_sha
from breezy.analysis.labeling.epoch import C1Epoch
from breezy.analysis.labeling.label_core import LabelRunDeps, run_labels
from breezy.analysis.labeling.unit_wiring import (
    LagRule,
    build_planner,
    family_infos,
    fill_deadline_ns,
    row_deadline_ns,
)
from breezy.registry.health_model import AlertPayload
from tests.support.aut2_fixtures import portfolio_roi_module
from tests.support.aut2_run_fixtures import Sink
from tests.support.te1_fixtures import (
    FAMILIES_DIR,
    LEGACY_COIDS,
    World,
    build_world,
    load_repo_manifests,
)

__all__ = [
    "CaptureSink",
    "ReportRun",
    "label_world",
    "post_terminal_label_keys",
    "run_report",
    "settlements_reader",
]

VENUE = "polymarket_us"
FQ_FAMILY = "pm_us_crh_fq_v1"
_RESIDUAL_SCORED_RUN = "2026-09-30T00:00:00Z"


@dataclass
class CaptureSink:
    """An ``AlertSink`` that records every payload."""

    payloads: list[AlertPayload] = field(default_factory=list)

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)

    def events(self) -> list[str]:
        return [p.event for p in self.payloads]

    def severities(self, event: str) -> list[str]:
        return [p.severity for p in self.payloads if p.event == event]


def _lag(world: World) -> LagRule:
    return LagRule(activation_ns=world.now_ns, deadline_of=fill_deadline_ns(VENUE))


def _planner(world: World) -> Any:
    manifests = load_repo_manifests()
    return build_planner(
        exec_db=world.exec_db,
        venue=VENUE,
        manifests=manifests,
        families=family_infos(manifests),
        evidence=C1Epoch(world.data_root, venue=VENUE, family_id=FQ_FAMILY),
        scored_trials=world.scored,
        release_ns=fill_deadline_ns(VENUE),
        lag_rule=_lag(world),
    )


def _deps(world: World) -> LabelRunDeps:
    manifests = load_repo_manifests()
    return LabelRunDeps(
        data_root=world.data_root,
        exec_db=world.exec_db,
        now_ns=world.now_ns,
        venue=VENUE,
        registry=OFFLINE_PLUGINS,
        families=lambda: family_infos(manifests),
        plan=_planner(world),
        settlements=world.settlements,
        deliver=Sink(),
        deadline_ns=row_deadline_ns(VENUE),
        lag_start_ns=_lag(world),
        producer_code_sha="c" * 64,
        subject_artefact_sha256=None,
    )


def _write_residual_sidecar(world: World) -> None:
    """The real ``excluded_fills.jsonl`` writer marks the two fee-unverified fills RESIDUAL."""
    import score_live_trials  # on sys.path once the report script is loaded

    prr = portfolio_roi_module()
    exclusions = []
    for coid in LEGACY_COIDS[:2]:
        fill = next(f for f in world.fills if f.client_order_id == coid)
        trial_id = _residual_trial_id(prr, world, fill.venue_order_id)
        exclusions.append(
            score_live_trials.FillExclusion(
                trial_id=trial_id,
                station=_station_of(fill.instrument_id),
                climate_day=_day_of(fill.instrument_id),
                qty="1",
                reason="fee_unverified",
                detail="te1 fixture",
                venue_order_id=fill.venue_order_id,
                filled_at_ns=fill.ts_event,
            )
        )
    score_live_trials._append_excluded_fills(
        world.scored_dir / "pm_us_crh_cont", exclusions, scored_run_utc=_RESIDUAL_SCORED_RUN
    )


def _station_of(instrument_id: str) -> str:
    return instrument_id.split("high-")[0].rsplit("-", 1)[1].upper()


def _day_of(instrument_id: str) -> str:
    return instrument_id.split("high-")[1][:10]


def _residual_trial_id(prr: Any, world: World, venue_order_id: str) -> str:
    fills, _ = prr.enumerate_family_station_pairs(
        families_dir=FAMILIES_DIR, exec_state_db_path=world.exec_db
    )
    ledger = prr.read_ledger_fills_with_counts(world.exec_db)
    attributed = prr.build_attribution_from_results(ledger.fills, fills)
    for item in attributed:
        if item.fill.venue_order_id == venue_order_id and item.trial_id is not None:
            return str(item.trial_id)
    raise AssertionError(f"no trial attributed for {venue_order_id}")


def label_world(tmp_path: Path, *, with_post_terminal: bool = True) -> World:
    """34 fills, the residual sidecar written, and one LABELLED label run over them."""
    world = build_world(tmp_path, with_post_terminal=with_post_terminal)
    _write_residual_sidecar(world)
    run_labels(_deps(world))
    return world


def post_terminal_label_keys(world: World) -> frozenset[str]:
    """The ``fill_key_sha`` of every fill the label planner bridged by the R11 straddle."""
    plan = _planner(world)(world.fills)
    return frozenset(
        fill_key_sha(item.fill)
        for items in plan.inputs_by_kind.values()
        for item in items
        if isinstance(item.attribution, PreEpochAttribution)
        and item.attribution.basis is BridgeBasis.BRIDGE_POST_TERMINAL
    )


def settlements_reader(world: World, *, shift: dict[tuple[str, str], int] | None = None) -> Any:
    """``(station, day) -> tmax`` from the world's settled highs, optionally shifted (a synthetic
    correction fixture): the fresh CLI FINAL the report compares against."""
    shifts = shift or {}

    def read(station: str, climate_day: dt.date) -> int | None:
        record = world.settlements.record(station, climate_day)
        if record is None or record.tmax_f is None:
            return None
        return int(record.tmax_f) + shifts.get((station, climate_day.isoformat()), 0)

    return read


@dataclass(frozen=True)
class ReportRun:
    exit_code: int
    sink: CaptureSink
    json_path: Path

    def report(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(self.json_path.read_text())
        return loaded


@contextmanager
def _patched_catalog(monkeypatch: Any, prr: Any, world: World) -> Iterator[None]:
    """Residual settlement reads its tmax through the report's own catalog seam."""

    def read(catalog: Any, *, station: str, climate_day: dt.date) -> Any:
        return world.settlements.record(station, climate_day)

    monkeypatch.setattr(prr, "open_station_catalog", lambda base, venue, city: (base, venue, city))
    monkeypatch.setattr(prr, "read_climate_day_including_corrections", read)
    monkeypatch.setattr(prr, "_read_bucket_facts_by_instrument_id", lambda *a, **k: {})
    yield


def run_report(
    monkeypatch: Any,
    world: World,
    tmp_path: Path,
    *,
    sink: CaptureSink | None = None,
    reader: Callable[[str, dt.date], int | None] | None = None,
    now_ns: int | None = None,
    labels_root: Path | None = None,
) -> ReportRun:
    """``portfolio_roi_report._run`` over the world, every seam injected."""
    prr = portfolio_roi_module()
    capture = sink if sink is not None else CaptureSink()
    out = tmp_path / "report_out"
    with _patched_catalog(monkeypatch, prr, world):
        code = prr._run(
            exec_state_db_path=world.exec_db,
            scored_trials_dir=world.scored_dir,
            logs_dir=tmp_path / "logs",
            output_dir=out,
            families_dir=FAMILIES_DIR,
            now_ns=world.now_ns if now_ns is None else now_ns,
            sink=capture,
            catalog_base=tmp_path / "catalog",
            labels_data_root=world.data_root if labels_root is None else labels_root,
            cli_final_reader=reader if reader is not None else settlements_reader(world),
        )
    day = dt.datetime.fromtimestamp((world.now_ns if now_ns is None else now_ns) / 1e9, dt.UTC)
    return ReportRun(
        exit_code=int(code),
        sink=capture,
        json_path=out / f"PRIVATE_portfolio_roi_{day:%Y-%m-%d}.json",
    )

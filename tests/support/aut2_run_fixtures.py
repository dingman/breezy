"""Shared builders for the AUT-2 label-run tests: a real exec store, a real FQ scorer behind the C6
plug-in seam, and a recording delivery sink. Nothing here touches live data or the network."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from breezy.analysis.labeling.attribution import Attribution
from breezy.analysis.labeling.delivery import DeliveryProof
from breezy.analysis.labeling.fq_scorer import (
    ForecastQuantileLadderScorer,
    FqFillInput,
    Reconciliation,
)
from breezy.analysis.labeling.label_core import FamilyInfo, InputPlan, LabelRunDeps
from breezy.analysis.labeling.scoring_batch import ScoredBatch, ScoringBatch
from breezy.domain.nws_climate_day import NwsClimateDay
from tests.contract.test_catalog_nws_records import make_climate_day
from tests.support.aut2_fixtures import (
    HOUR_NS,
    RELEASE_NS,
    TS,
    YES,
    durable_fill,
    make_decision,
    make_link,
    seed_fills,
)

__all__ = [
    "DAY",
    "FAMILY",
    "FQ_KIND",
    "NOW_NS",
    "DroppingPlugin",
    "FqPlugin",
    "RecordingPlugin",
    "Sink",
    "StaticSettlements",
    "fq_planner",
    "make_deps",
    "marker_files",
    "verdict_wires",
]

FQ_KIND = "forecast_quantile_ladder"
FAMILY = "pm_us_crh_fq_v1"
DAY = dt.date(2026, 10, 2)
NOW_NS = RELEASE_NS + HOUR_NS
_GOOD = Reconciliation(reconciled=True, delta=Decimal(0), source="venue_get")


class StaticSettlements:
    def __init__(self, record: NwsClimateDay | None) -> None:
        self._record = record

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        return self._record


class FqPlugin:
    """The real FQ scorer behind the C6 ``label`` seam (``batch`` carries the clock and prior)."""

    refusing = False

    def __init__(self) -> None:
        self.calls = 0

    def label(self, capture_day: Any, batch: ScoringBatch, settlements: Any) -> ScoredBatch:
        self.calls += 1
        scorer = ForecastQuantileLadderScorer(now_ns=batch.now_ns, prior=batch.prior)
        result = scorer.label_with_alerts(capture_day, list(batch.inputs), settlements)
        return ScoredBatch(
            rows=result.rows,
            p_null_count=result.p_null_count,
            non_c1_post_epoch_count=result.non_c1_post_epoch_count,
        )


class DroppingPlugin(FqPlugin):
    """Silently drops the last fill's row: the real MISSING_LABEL control (P9)."""

    def label(self, capture_day: Any, batch: ScoringBatch, settlements: Any) -> ScoredBatch:
        kept = ScoringBatch(batch.now_ns, batch.prior, tuple(batch.inputs[:-1]))
        return super().label(capture_day, kept, settlements)


class RecordingPlugin:
    refusing = False

    def __init__(self) -> None:
        self.batches: list[ScoringBatch] = []

    def label(self, capture_day: Any, batch: ScoringBatch, settlements: Any) -> ScoredBatch:
        self.batches.append(batch)
        return ScoredBatch(rows=())


@dataclass
class Sink:
    """A delivery sink recording every payload; ``fail`` makes it raise."""

    fail: bool = False
    payloads: list[Mapping[str, Any]] = field(default_factory=list)

    def __call__(self, payload: Mapping[str, Any]) -> DeliveryProof:
        if self.fail:
            raise OSError("sink down")
        self.payloads.append(dict(payload))
        return DeliveryProof(delivered=True)

    @property
    def events(self) -> list[str]:
        return [str(p.get("event")) for p in self.payloads]


def fq_planner(fills: Sequence[Any]) -> InputPlan:
    inputs = []
    for fill in fills:
        decision = make_decision(
            decision_id=f"dec-{fill.client_order_id}", instrument_id=fill.instrument_id
        )
        link = make_link(
            fill.client_order_id, decision.decision_id, instrument_id=fill.instrument_id
        )
        attribution = Attribution(
            family_id=FAMILY,
            decision=decision,
            link=link,
            drill=False,
            voided_pair=False,
            alerts=(),
        )
        inputs.append(
            FqFillInput(
                fill=fill,
                attribution=attribution,
                scheduled_release_at_ns=RELEASE_NS,
                reconciliation=_GOOD,
            )
        )
    return InputPlan(
        inputs_by_kind={FQ_KIND: tuple(inputs)},
        fill_kinds={f.client_order_id: FQ_KIND for f in fills},
    )


def make_deps(
    tmp_path: Path,
    *,
    n_fills: int | None = 2,
    settled: bool = True,
    **over: Any,
) -> LabelRunDeps:
    """Deps over a fresh data root and an exec store of ``n_fills`` YES fills (``None``: no store)."""
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    exec_db = tmp_path / "exec.sqlite"
    if n_fills is not None:
        seed_fills(
            exec_db,
            [
                durable_fill(
                    venue_order_id=f"vo-{i}",
                    client_order_id=f"O-{i}",
                    instrument_id=YES,
                    ts_event=TS + i,
                    trade_id=f"T-{i}",
                )
                for i in range(1, n_fills + 1)
            ],
        )
    record = make_climate_day(station="LAX", climate_day=DAY, tmax_f=89) if settled else None
    base: dict[str, Any] = {
        "data_root": data_root,
        "exec_db": exec_db,
        "now_ns": NOW_NS,
        "venue": "polymarket_us",
        "registry": {FQ_KIND: FqPlugin()},
        "families": lambda: (FamilyInfo(FAMILY, FQ_KIND, retired=False),),
        "plan": fq_planner,
        "settlements": StaticSettlements(record),
        "deliver": Sink(),
        "deadline_ns": lambda _row: RELEASE_NS,
        "lag_start_ns": lambda _fill: RELEASE_NS,
        "producer_code_sha": "c" * 64,
        "subject_artefact_sha256": "a" * 64,
    }
    base.update(over)
    return LabelRunDeps(**base)


def marker_files(data_root: Path) -> list[Path]:
    return sorted(data_root.joinpath("derived", "label_outcomes").rglob("marker_*.json"))


def verdict_wires(data_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(data_root.joinpath("derived", "verdicts").rglob("*.json")):
        out.append(json.loads(path.read_text()))
    return out

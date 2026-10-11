"""TE-2 loss taxonomy: settlement truth wrappers, Phase A projection, audit (I/O). WP0 stub."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from breezy.analysis.labeling.fill_source import FillRead
from breezy.analysis.labeling.settlement_source import SettlementSource
from breezy.domain.nws_climate_day import NwsClimateDay

LAST_FQ_CLIMATE_DAY: Final = dt.date(2026, 10, 6)


class ClippingSettlementSource:
    """A ``SettlementSource`` that returns ``None`` for any climate day after ``last_day``."""

    def __init__(self, inner: SettlementSource, last_day: dt.date) -> None:
        raise NotImplementedError

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        raise NotImplementedError


@dataclass(frozen=True)
class PhaseAProjection:
    """A settlement record with ``tmax_f`` removed: what the outcome-blind Phase A may see."""

    station: str
    climate_day: dt.date
    is_final: bool
    is_superseded: bool
    correction_flag: bool
    revision_seq: int


def project_phase_a(record: NwsClimateDay) -> PhaseAProjection:
    raise NotImplementedError


def phase_a_truth(
    source: SettlementSource,
    station: str,
    climate_day: dt.date,
    *,
    last_day: dt.date = LAST_FQ_CLIMATE_DAY,
) -> PhaseAProjection | None:
    """The only Phase A entry to settlement data: clip, then project (never ``tmax_f``)."""
    raise NotImplementedError


def truth_status(
    projection: PhaseAProjection | None, *, catalog_disagreement: bool = False
) -> Literal["SETTLED", "TRUTH_UNSETTLED"]:
    raise NotImplementedError


@dataclass(frozen=True)
class AuditReproduction:
    n_fills: int
    n_wins: int
    net_pnl: Decimal
    wins: tuple[tuple[str, int], ...]
    n_refused: int


def reproduce_audit(fills: FillRead, source: SettlementSource, *, now_ns: int) -> AuditReproduction:
    """Score every fill through ``source`` (the caller wraps it in ``ClippingSettlementSource``)."""
    raise NotImplementedError


@dataclass(frozen=True)
class AltTruth:
    k3_status: Literal["TESTED", "UNTESTABLE"]
    k3_count: int | None
    k4_status: Literal["TESTED", "UNTESTABLE"]
    k4_count: int | None


def alt_truth_summary(
    metar_flips: dict[str, bool] | None, venue_mismatches: dict[str, bool] | None
) -> AltTruth:
    raise NotImplementedError

"""TE-2 loss taxonomy: settlement truth wrappers, Phase A projection, audit (I/O). Plan S0-F."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from breezy.analysis.labeling.fill_source import FillRead
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.labeling.settlement_source import SettlementSource
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.settlement.trial_scorer import FilledTrial, ScoreRefusal, score_trial

LAST_FQ_CLIMATE_DAY: Final = dt.date(2026, 10, 6)


class ClippingSettlementSource:
    """A ``SettlementSource`` that returns ``None`` for any climate day after ``last_day``."""

    def __init__(self, inner: SettlementSource, last_day: dt.date) -> None:
        self._inner = inner
        self._last_day = last_day

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        if climate_day > self._last_day:
            return None
        return self._inner.record(station, climate_day)


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
    return PhaseAProjection(
        station=record.station,
        climate_day=record.climate_day,
        is_final=record.is_final,
        is_superseded=record.is_superseded,
        correction_flag=record.correction_flag,
        revision_seq=record.revision_seq,
    )


def phase_a_truth(
    source: SettlementSource,
    station: str,
    climate_day: dt.date,
    *,
    last_day: dt.date = LAST_FQ_CLIMATE_DAY,
) -> PhaseAProjection | None:
    """The only Phase A entry to settlement data: clip, then project (never ``tmax_f``)."""
    if climate_day > last_day:
        return None
    record = source.record(station, climate_day)
    return None if record is None else project_phase_a(record)


def truth_status(
    projection: PhaseAProjection | None, *, catalog_disagreement: bool = False
) -> Literal["SETTLED", "TRUTH_UNSETTLED"]:
    """A missing, preliminary, superseded or corrected day is TRUTH_UNSETTLED (counted)."""
    if projection is None or catalog_disagreement:
        return "TRUTH_UNSETTLED"
    if projection.correction_flag or projection.is_superseded or not projection.is_final:
        return "TRUTH_UNSETTLED"
    return "SETTLED"


@dataclass(frozen=True)
class AuditReproduction:
    n_fills: int
    n_wins: int
    net_pnl: Decimal
    wins: tuple[tuple[str, int], ...]
    n_refused: int


def reproduce_audit(fills: FillRead, source: SettlementSource, *, now_ns: int) -> AuditReproduction:
    """Score every fill through ``source`` (the caller wraps it in ``ClippingSettlementSource``).

    Outcomes key on the INSTRUMENT climate day. A fill with no record (clipped included) or an
    unparseable id is counted in ``n_refused``, never scored.
    """
    scored = refused = 0
    net = Decimal(0)
    wins: list[tuple[str, int]] = []
    for fill in fills.fills:
        facts = bucket_facts_from_instrument_id(fill.instrument_id)
        if facts is None:
            refused += 1
            continue
        qty = fill.cumulative_qty
        fill_px = fill.cumulative_cost / qty
        trial = FilledTrial(
            trial_id=fill.venue_order_id,
            station=facts.settlement_station,
            climate_day=facts.climate_day.isoformat(),
            instrument_id=fill.instrument_id,
            bucket=facts,
            fill_px=fill_px,
            fee=fill.cumulative_fee / qty,
            qty=qty,
            filled_at_ns=fill.ts_event,
            entry_ask=fill_px,
            scheduled_release_at_ns=0,
        )
        result = score_trial(
            trial, source.record(facts.settlement_station, facts.climate_day), now_ns=now_ns
        )
        if isinstance(result, ScoreRefusal):
            refused += 1
            continue
        scored += 1
        net += result.pnl * qty
        if result.held:
            wins.append((fill.instrument_id, result.settlement_tmax_f))
    return AuditReproduction(scored, len(wins), net, tuple(wins), refused)


@dataclass(frozen=True)
class AltTruth:
    k3_status: Literal["TESTED", "UNTESTABLE"]
    k3_count: int | None
    k4_status: Literal["TESTED", "UNTESTABLE"]
    k4_count: int | None


def alt_truth_summary(
    metar_flips: dict[str, bool] | None, venue_mismatches: dict[str, bool] | None
) -> AltTruth:
    """An absent source is UNTESTABLE with a null count, never a zero count."""
    k3 = None if metar_flips is None else sum(1 for flipped in metar_flips.values() if flipped)
    k4 = (
        None
        if venue_mismatches is None
        else sum(1 for mismatch in venue_mismatches.values() if mismatch)
    )
    return AltTruth(
        k3_status="UNTESTABLE" if k3 is None else "TESTED",
        k3_count=k3,
        k4_status="UNTESTABLE" if k4 is None else "TESTED",
        k4_count=k4,
    )


@dataclass(frozen=True)
class AltSourceDiscovery:
    """S0-G: which alternative truth sources exist for the FQ window (outcome-blind)."""

    metar_last_valid: Mapping[str, str | None]
    metar_covers: bool
    venue_outcomes_present: bool


def discover_alt_sources(
    archive_root: Path,
    icaos: Sequence[str],
    last_day: dt.date,
    *,
    venue_outcomes: Path | None = None,
) -> AltSourceDiscovery:
    raise NotImplementedError

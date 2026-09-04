"""6c settlement scorer -- `held`/`pnl` per filled trial.

`docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md` section 6c, as amended by
the "Converged peer review (2026-09-04)" section, which is BINDING over the
draft body. Pure module: no Nautilus, no I/O, no wall clock -- every time
value the scorer needs is an explicit `now_ns` input from the caller.

Fill source (draft, unchanged by review): neither the trial latch nor
`Position` is today's input. The latch is written before submit and holds
only the quoted ask; `Position.realized_pnl` is fee-INCLUSIVE and requires an
unlanded live exec client. `FilledTrial` is therefore an explicit, caller-
built input record, and `pnl = 1{held} - fill_px - fee` is built from a
fee-EXCLUSIVE `fill_px` plus a separate, per-contract `fee` term -- never
`Position.realized_pnl`, and the two are never summed (see
`breezy/settlement/exit_guard.py` for the fee-inclusive sibling quantity).

Venue fallback settlement (review item 1): `VENUE_FACTS_2026-08-25.md:721` --
absent an NWS FINAL seven days after the scheduled release, the contract
settles at the venue's own last-fair-price. A trial scores
`settlement_basis="venue_last_fair_price_fallback"` ONLY once both the
seven-day window has elapsed AND the venue's own settlement value is present
on the input (`FilledTrial.venue_settlement_tmax_f`); such a score is always
stamped `excluded_reason="venue_settled_without_nws"` so 6d/6e never pool it
with an NWS-keyed row. Before that, the trial stays refused/PENDING. Once a
trial has been fallback-scored, a caller must not re-invoke this scorer for
that trial against a later-arriving FINAL -- "a FINAL that lands after the
venue booked fallback cash does NOT re-score against NWS" is a DRIVER-level
invariant (`scripts/analysis/score_live_trials.py` must skip re-scoring a
trial whose latest stored row already carries the fallback basis); this pure
function has no history to consult and always scores off its inputs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.settlement.settlement_truth import final_tmax_f

__all__ = [
    "FilledTrial",
    "ScoreRefusal",
    "ScoredTrial",
    "score_trial",
    "score_trials",
]

#: Venue fallback window (review item 1): seven days after the scheduled
#: NWS release, absent a FINAL, the venue's own settlement becomes eligible.
_SEVEN_DAYS_NS: int = 7 * 24 * 60 * 60 * 1_000_000_000

SettlementBasis = Literal["nws_final", "venue_last_fair_price_fallback"]

RefusalReason = Literal[
    "no_record",
    "preliminary_only",
    "superseded",
    "sentinel_tmax",
    "rung_unresolved",
    "station_day_mismatch",
    "instrument_unavailable",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class FilledTrial:
    """One filled trial's inputs to the per-trial net return.

    `bucket` is `None` when the caller (the driver script) could not resolve
    the rung -- e.g. the persisted instrument definition itself is absent, in
    which case the caller emits `ScoreRefusal(reason="instrument_unavailable")`
    directly and never constructs a `FilledTrial` at all; a resolved
    instrument whose rung bounds are still unusable is represented as
    `bucket=None` here and refused with `reason="rung_unresolved"`.

    `fee` is per-contract, entry leg only (venue charges at fill; settlement
    carries no fee -- OQ8). An adapter that divides a total commission by
    `qty` before populating this field lands with the `OrderFilled` ->
    `FilledTrial` adapter (R-7/R-8), not here; this module always treats
    `fee` as already per-contract and never multiplies or divides it by
    `qty` when computing `pnl`.

    `entry_ask` is the decision-time (latch) ask, carried alongside
    `fill_px` so `slippage = fill_px - entry_ask` can be computed without a
    second join (review item 6).

    `climate_day` is an ISO-8601 date string (`"2026-08-31"`), not
    `datetime.date` -- `src/breezy/settlement/` is an AST-enforced pure
    package (`tests/unit/test_settlement_purity_guard.py` D1: no `datetime`,
    `os`, `pathlib`, `time`, or similar side-effecting/non-deterministic
    imports anywhere under it), so this module never imports `datetime`.
    Callers hold real `datetime.date` values (`NwsClimateDay.climate_day`,
    `WeatherBucketFacts.climate_day`) and pass `.isoformat()`.
    """

    trial_id: str
    station: str
    climate_day: str
    instrument_id: str
    bucket: WeatherBucketFacts | None
    fill_px: Decimal
    fee: Decimal
    qty: Decimal
    filled_at_ns: int
    entry_ask: Decimal
    #: When the NWS FINAL was scheduled to publish for this station-day.
    scheduled_release_at_ns: int
    #: The venue's own recorded settlement reading, once (and only once) it
    #: has booked a last-fair-price fallback close. `None` until then.
    venue_settlement_tmax_f: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoredTrial:
    """One trial's settlement outcome -- `held`, `pnl`, and full provenance."""

    trial_id: str
    station: str
    climate_day: str
    instrument_id: str
    settlement_tmax_f: int
    held: bool
    pnl: Decimal
    revision_seq: int
    raw_sha256: str
    scored_at_ns: int
    score_seq: int
    settlement_basis: SettlementBasis
    excluded_reason: str | None
    slippage: Decimal
    entry_ask: Decimal
    fill_px: Decimal
    fee: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreRefusal:
    """Why one trial could not be scored -- never a fabricated outcome."""

    trial_id: str
    reason: RefusalReason
    detail: str


def score_trial(
    trial: FilledTrial,
    record: NwsClimateDay | None,
    *,
    now_ns: int,
    score_seq: int = 0,
) -> ScoredTrial | ScoreRefusal:
    """Score one filled trial against its settlement record.

    `record` is the caller-resolved `NwsClimateDay` for `(trial.station,
    trial.climate_day)` (or `None` if none exists yet) -- resolving it is the
    caller's I/O, kept out of this pure function.
    """
    if trial.bucket is None:
        return ScoreRefusal(
            trial_id=trial.trial_id,
            reason="rung_unresolved",
            detail=f"{trial.instrument_id}: no resolvable WeatherBucketFacts for this trial",
        )
    if record is not None and (
        record.station != trial.station or record.climate_day.isoformat() != trial.climate_day
    ):
        return ScoreRefusal(
            trial_id=trial.trial_id,
            reason="station_day_mismatch",
            detail=(
                f"record is for ({record.station}, {record.climate_day.isoformat()}), "
                f"trial is for ({trial.station}, {trial.climate_day})"
            ),
        )

    final = final_tmax_f(record)
    settlement_basis: SettlementBasis
    excluded_reason: str | None
    settlement_tmax_f: int
    revision_seq: int
    raw_sha256: str

    if final is not None:
        assert record is not None
        settlement_basis = "nws_final"
        excluded_reason = None
        settlement_tmax_f = final
        revision_seq = record.revision_seq
        raw_sha256 = record.raw_sha256
    else:
        fallback_due = now_ns >= trial.scheduled_release_at_ns + _SEVEN_DAYS_NS
        if fallback_due and trial.venue_settlement_tmax_f is not None:
            settlement_basis = "venue_last_fair_price_fallback"
            excluded_reason = "venue_settled_without_nws"
            settlement_tmax_f = trial.venue_settlement_tmax_f
            revision_seq = 0
            raw_sha256 = ""
        else:
            return ScoreRefusal(
                trial_id=trial.trial_id,
                reason=_pending_reason(record),
                detail=(
                    f"{trial.station} {trial.climate_day}: not settlement-grade "
                    "and the venue fallback window has not both elapsed and produced a "
                    "venue settlement reading"
                ),
            )

    held = trial.bucket.contains(settlement_tmax_f)
    pnl = (Decimal(1) if held else Decimal(0)) - trial.fill_px - trial.fee
    slippage = trial.fill_px - trial.entry_ask

    return ScoredTrial(
        trial_id=trial.trial_id,
        station=trial.station,
        climate_day=trial.climate_day,
        instrument_id=trial.instrument_id,
        settlement_tmax_f=settlement_tmax_f,
        held=held,
        pnl=pnl,
        revision_seq=revision_seq,
        raw_sha256=raw_sha256,
        scored_at_ns=now_ns,
        score_seq=score_seq,
        settlement_basis=settlement_basis,
        excluded_reason=excluded_reason,
        slippage=slippage,
        entry_ask=trial.entry_ask,
        fill_px=trial.fill_px,
        fee=trial.fee,
    )


def score_trials(
    pairs: Sequence[tuple[FilledTrial, NwsClimateDay | None]],
    *,
    now_ns: int,
) -> tuple[tuple[ScoredTrial, ...], tuple[ScoreRefusal, ...]]:
    """Score every `(trial, record)` pair; `len(scored) + len(refused) ==
    len(pairs)` always -- the `TradeReturnSample` invariant
    (`exit_guard.py:100-108`), applied here to settlement scoring."""
    scored: list[ScoredTrial] = []
    refused: list[ScoreRefusal] = []
    for trial, record in pairs:
        result = score_trial(trial, record, now_ns=now_ns)
        if isinstance(result, ScoreRefusal):
            refused.append(result)
        else:
            scored.append(result)
    return tuple(scored), tuple(refused)


def _pending_reason(record: NwsClimateDay | None) -> RefusalReason:
    if record is None:
        return "no_record"
    if not record.is_final:
        return "preliminary_only"
    if record.is_superseded:
        return "superseded"
    return "sentinel_tmax"

"""SL-13p A-5 shadow-parity: the PURE batch path.

Ruling `docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-5
(binding) and plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`
§4.4. Parity compares two independent code paths on PRE-FREEZE tape only
(2026-08-30..2026-09-25, >= 14 days):

* (i) the LIVE code path -- the NBP actor and the `forecast_quantile_ladder`
  strategy composed in a native Nautilus `BacktestEngine` replay of the
  captured tape (``nbp_shadow_parity.py``, the sibling orchestrator);
* (ii) the BATCH path -- THIS module. An offline recomputation of decisions
  from the same NBP rows and tape, using ONLY the pure modules
  (``quantile_density``, ``ladder_ev`` scoring via ``decision.evaluate``, the
  latch/permit rules, ``margin``, ``bounds``), with NO import of the
  strategy or actor classes. Pinned by
  ``tests/unit/test_nbp_shadow_parity_contract.py``.

Parity = decision-key set equality, with mismatches = 0 (§12 A-5). This
module never computes P&L, an outcome, or an ev-aggregate (plan §4.4 items
1 and 4): :func:`diff_decision_keys` and :meth:`ParityReport.to_counts_dict`
carry keys and mismatch COUNTS only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal

from breezy.adapters.polymarket_us.safety import PERMIT_TTL_NS
from breezy.runtime.trade_supervisor_core import LAUNCH_UTC
from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import CalibrationArtefact
from breezy.strategy.forecast_quantile_ladder.decision import Decision, SidedAsk, evaluate
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import (
    NBP_QUANTILE_VARIABLES,
    ForecastQuantileState,
    ForecastQuantileVector,
)
from breezy.strategy.ladder_ev.quantile_density import Rung

__all__ = [
    "MIN_PRE_FREEZE_DAYS",
    "PRE_FREEZE_END",
    "PRE_FREEZE_START",
    "BatchSnapshotInput",
    "DecisionKey",
    "DepthSnapshotRow",
    "InsufficientPreFreezeDaysError",
    "NbpQuantileRow",
    "ParityReport",
    "PostFreezeTapeRefusedError",
    "UnparsableRungInstrumentIdError",
    "assert_minimum_pre_freeze_days",
    "assert_pre_freeze_tape_day",
    "decision_key_from",
    "diff_decision_keys",
    "evaluate_batch_snapshot",
    "hours_to_settlement",
    "nominal_permit_expiry_upper_bound",
    "parse_rung_instrument_id",
    "permit_covers",
    "permit_window_for_day",
    "run_batch_parity",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000
_NS_PER_HOUR: Final[int] = 3_600 * _NS_PER_SECOND

#: A-5's pre-freeze tape window (ruling §12): "2026-08-30..09-25; >= 14 days
#: are required, and about 27 are available." Both bounds inclusive.
PRE_FREEZE_START: Final[date] = date(2026, 8, 30)
PRE_FREEZE_END: Final[date] = date(2026, 9, 25)
MIN_PRE_FREEZE_DAYS: Final[int] = 14


class PostFreezeTapeRefusedError(ValueError):
    """Raised when a tape day falls outside the sealed pre-freeze window.

    A-5 parity is defined ONLY on ``PRE_FREEZE_START..PRE_FREEZE_END``
    (ruling §12); post-freeze logs are liveness-only until S4-gate
    (plan §4.4) and must never feed this comparison.
    """


class InsufficientPreFreezeDaysError(ValueError):
    """Raised when fewer than :data:`MIN_PRE_FREEZE_DAYS` distinct days are present."""


class UnparsableRungInstrumentIdError(ValueError):
    """Raised when a tape instrument id does not match this harness's naming
    convention (``<STATION>-<YYYY>-<MM>-<DD>-<RUNG_ID>.<SUFFIX>``, matching
    ``tests/strategy/forecast_quantile_ladder/test_strategy.py``'s own
    fixture shape)."""


def assert_pre_freeze_tape_day(day: date) -> None:
    """Refuse any tape day outside the sealed A-5 window (ruling §12)."""
    if day < PRE_FREEZE_START or day > PRE_FREEZE_END:
        raise PostFreezeTapeRefusedError(
            f"{day.isoformat()} is outside the sealed pre-freeze A-5 window "
            f"({PRE_FREEZE_START.isoformat()}..{PRE_FREEZE_END.isoformat()}); "
            f"post-freeze tape is liveness-only until S4-gate (plan §4.4) and "
            f"must never feed decision-key parity",
        )


def assert_minimum_pre_freeze_days(days: Iterable[date]) -> None:
    """Refuse a run covering fewer than :data:`MIN_PRE_FREEZE_DAYS` distinct days."""
    distinct = set(days)
    if len(distinct) < MIN_PRE_FREEZE_DAYS:
        raise InsufficientPreFreezeDaysError(
            f"only {len(distinct)} distinct pre-freeze tape day(s) supplied; "
            f"A-5 parity requires at least {MIN_PRE_FREEZE_DAYS} (ruling §12)",
        )


# ---------------------------------------------------------------------------
# Nominal permit window -- [LAUNCH_UTC, LAUNCH_UTC + PERMIT_TTL_NS), read
# from code (SL-13p brief), never re-declared as a local constant.
# ---------------------------------------------------------------------------


def permit_window_for_day(day: date) -> tuple[int, int]:
    """The nominal ``[start_ns, end_ns)`` permit window opening on ``day`` (UTC)."""
    start_dt = datetime.combine(day, LAUNCH_UTC, tzinfo=UTC)
    start_ns = int(start_dt.timestamp()) * _NS_PER_SECOND
    return start_ns, start_ns + PERMIT_TTL_NS


def permit_covers(now_ns: int) -> bool:
    """Whether ``now_ns`` falls inside the nominal permit window.

    The 10 h TTL (``PERMIT_TTL_NS``) can carry a window past UTC midnight
    (``LAUNCH_UTC`` is 16:50), so both ``now_ns``'s own UTC calendar day and
    the PRECEDING day's window are checked -- a window opened yesterday can
    still cover a ``now_ns`` read just after today's midnight.
    """
    now_dt = datetime.fromtimestamp(now_ns / _NS_PER_SECOND, tz=UTC)
    for day in (now_dt.date(), now_dt.date() - timedelta(days=1)):
        start_ns, end_ns = permit_window_for_day(day)
        if start_ns <= now_ns < end_ns:
            return True
    return False


def nominal_permit_expiry_upper_bound(now_ns: int) -> int:
    """Reconstruct the two-sided nominal permit window through a ONE-SIDED
    ``now_ns < expires_at_ns`` check.

    ``ForecastQuantileLadderStrategy._permit_covers`` (``strategy.py``) only
    ever checks ``now_ns < permit.expires_at_ns`` -- the ``SupportsExpiresAtNs``
    Protocol it depends on carries no start/lower bound. That is a real gap
    in the strategy's guard shape (reported, not patched: this slice may not
    modify ``src/breezy/strategy/forecast_quantile_ladder``). The live-path
    orchestrator works around it, without touching the strategy, by handing
    it a clock-driven permit stub whose ``expires_at_ns`` is recomputed on
    every access via THIS function: it returns the covering window's own
    ``end_ns`` when ``now_ns`` falls inside a nominal window (so the
    one-sided check reads True), and ``now_ns`` itself otherwise (so the
    check reads False) -- by construction, ``permit_covers(now_ns) ==
    (now_ns < nominal_permit_expiry_upper_bound(now_ns))`` for every
    ``now_ns`` (pinned by
    ``tests/unit/test_nbp_shadow_parity_pure.py``).
    """
    now_dt = datetime.fromtimestamp(now_ns / _NS_PER_SECOND, tz=UTC)
    for day in (now_dt.date(), now_dt.date() - timedelta(days=1)):
        start_ns, end_ns = permit_window_for_day(day)
        if start_ns <= now_ns < end_ns:
            return end_ns
    return now_ns


def hours_to_settlement(
    *, now_ns: int, climate_day: date, std_utc_offset_hours: float,
) -> float:
    """Hours from ``now_ns`` to the END of ``climate_day`` in the station's
    local standard time (its settlement instant -- local midnight starting
    ``climate_day + 1``)."""
    settlement_ns = _local_midnight_utc_ns(
        climate_day + timedelta(days=1), std_utc_offset_hours,
    )
    return (settlement_ns - now_ns) / _NS_PER_HOUR


def _local_midnight_utc_ns(local_date: date, std_utc_offset_hours: float) -> int:
    naive_midnight = datetime.combine(local_date, time(0, 0), tzinfo=UTC)
    utc_instant = naive_midnight - timedelta(hours=std_utc_offset_hours)
    return int(utc_instant.timestamp()) * _NS_PER_SECOND


# ---------------------------------------------------------------------------
# Decision keys and the parity diff -- counts only (plan §4.4 items 1, 2, 4).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionKey:
    """The identity of ONE evaluated snapshot: station, climate_day, rung,
    side, the decision KIND (``type(decision).__name__``, never a scored
    field), and the evaluation instant. No ev/p_hat/outcome field -- parity
    is decision-KEY set equality only (ruling §12 A-5)."""

    station: str
    climate_day: date
    rung_id: str
    side: Literal["yes", "no"]
    kind: str
    ts_ns: int


def decision_key_from(
    decision: Decision,
    *,
    station: str,
    climate_day: date,
    rung_id: str,
    side: Literal["yes", "no"],
    ts_ns: int,
) -> DecisionKey:
    return DecisionKey(
        station=station,
        climate_day=climate_day,
        rung_id=rung_id,
        side=side,
        kind=type(decision).__name__,
        ts_ns=ts_ns,
    )


def _sort_key(key: DecisionKey) -> tuple[str, date, str, str, str, int]:
    return (key.station, key.climate_day, key.rung_id, key.side, key.kind, key.ts_ns)


@dataclass(frozen=True, slots=True, kw_only=True)
class ParityReport:
    """decision-key set equality between the live and batch paths.

    ``live_only``/``batch_only`` are exposed for TESTS to assert an injected
    divergence was actually caught -- they are keys (station/day/rung/side/
    kind/ts), never P&L, an outcome, or an ev-aggregate. The ON-DISK report
    (:meth:`to_counts_dict`) carries mismatch COUNTS only, per plan §4.4
    item 2 ("It emits mismatch counts only").
    """

    n_live: int
    n_batch: int
    n_matched: int
    live_only: tuple[DecisionKey, ...]
    batch_only: tuple[DecisionKey, ...]

    @property
    def n_live_only(self) -> int:
        return len(self.live_only)

    @property
    def n_batch_only(self) -> int:
        return len(self.batch_only)

    @property
    def n_mismatches(self) -> int:
        return self.n_live_only + self.n_batch_only

    def to_counts_dict(self) -> dict[str, int]:
        """Mismatch COUNTS only -- no key detail, no ev/p&l/outcome field."""
        return {
            "n_live": self.n_live,
            "n_batch": self.n_batch,
            "n_matched": self.n_matched,
            "n_live_only": self.n_live_only,
            "n_batch_only": self.n_batch_only,
            "n_mismatches": self.n_mismatches,
        }


def diff_decision_keys(
    live: Iterable[DecisionKey], batch: Iterable[DecisionKey],
) -> ParityReport:
    """decision-key set equality (ruling §12 A-5: "mismatches = 0")."""
    live_set = frozenset(live)
    batch_set = frozenset(batch)
    matched = live_set & batch_set
    return ParityReport(
        n_live=len(live_set),
        n_batch=len(batch_set),
        n_matched=len(matched),
        live_only=tuple(sorted(live_set - batch_set, key=_sort_key)),
        batch_only=tuple(sorted(batch_set - live_set, key=_sort_key)),
    )


# ---------------------------------------------------------------------------
# The batch path: `decision.evaluate` directly, no strategy/actor import.
# ---------------------------------------------------------------------------

#: ``<STATION>-<YYYY>-<MM>-<DD>-<RUNG_ID>.<SUFFIX>`` -- this harness's own
#: naming convention, matching the fixture shape in
#: ``tests/strategy/forecast_quantile_ladder/test_strategy.py``
#: (``"KMIA-2026-10-01-i1.POLY_US"``). Deliberately NOT a re-implementation
#: of any venue-specific band-id parser (e.g. ``gte92lt94``): the harness
#: never resolves rung bounds from the instrument id itself -- those are
#: supplied by the caller's ladder mapping (see :func:`run_batch_parity`).
_INSTRUMENT_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<station>[A-Z0-9]+)-(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"-(?P<rung_id>[^.]+)\.[A-Za-z0-9_]+$",
)


def parse_rung_instrument_id(instrument_id: str) -> tuple[str, date, str]:
    """Return ``(station, climate_day, rung_id)`` from a tape instrument id."""
    match = _INSTRUMENT_ID_RE.match(instrument_id)
    if match is None:
        raise UnparsableRungInstrumentIdError(
            f"{instrument_id!r} does not match "
            f"<STATION>-<YYYY>-<MM>-<DD>-<RUNG_ID>.<SUFFIX>",
        )
    climate_day = date(
        int(match.group("year")), int(match.group("month")), int(match.group("day")),
    )
    return match.group("station"), climate_day, match.group("rung_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class DepthSnapshotRow:
    """One depth-tape frame, reduced to what the batch path needs.

    Deliberately NOT a ``nautilus_trader.model.data.OrderBookDepth10`` --
    the batch path takes no Nautilus dependency at all (plan §4.4 / ruling
    §12 A-5(ii)); the live-path orchestrator converts real ``OrderBookDepth10``
    rows into this shape before either path runs.
    """

    instrument_id: str
    ts_ns: int
    best_ask_price: float | None
    best_ask_size: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class NbpQuantileRow:
    """One derived NBP quantile/summary row -- the fields
    :meth:`ForecastQuantileState.push` needs, decoupled from
    ``breezy.persistence.nbp_derived_store.DerivedNbpRow`` (that module is a
    backfill-store reader/writer, out of scope for this pure path)."""

    station: str
    variable: str
    cycle_runtime_ns: int
    value_f: float | None
    available_at_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchSnapshotInput:
    now_ns: int
    std_utc_offset_hours: float
    station: str
    climate_day: date
    ladder: Sequence[Rung]
    rung_id: str
    side: Literal["yes", "no"]
    ask: SidedAsk
    fee_coefficient: float
    slippage_floor_prob: float
    vector: ForecastQuantileVector | None


def evaluate_batch_snapshot(
    inp: BatchSnapshotInput,
    *,
    cfg: LadderEvConfig,
    artefact: CalibrationArtefact,
    bounds_provider: BoundsProvider,
    latch: QuantileLadderLatch,
) -> Decision:
    """Call ``decision.evaluate`` directly -- the ONE shared call both the
    batch path and (through the strategy) the live path route through."""
    h_hours = hours_to_settlement(
        now_ns=inp.now_ns,
        climate_day=inp.climate_day,
        std_utc_offset_hours=inp.std_utc_offset_hours,
    )
    return evaluate(
        now_ns=inp.now_ns,
        std_utc_offset_hours=inp.std_utc_offset_hours,
        permit_covers=permit_covers(inp.now_ns),
        vector=inp.vector,
        station=inp.station,
        climate_day=inp.climate_day,
        ladder=inp.ladder,
        rung_id=inp.rung_id,
        side=inp.side,
        ask=inp.ask,
        fee_coefficient=inp.fee_coefficient,
        slippage_floor_prob=inp.slippage_floor_prob,
        h_hours=h_hours,
        cfg=cfg,
        artefact=artefact,
        bounds_provider=bounds_provider,
        latch=latch,
    )


def run_batch_parity(
    *,
    depth_snapshots: Sequence[DepthSnapshotRow],
    nbp_rows: Sequence[NbpQuantileRow],
    ladder_by_key: Mapping[tuple[str, date], Sequence[Rung]],
    artefact: CalibrationArtefact,
    ladder_cfg: LadderEvConfig,
    bounds_provider: BoundsProvider,
    fee_coefficient: float,
    slippage_floor_prob: float,
    std_utc_offset_hours_by_station: Mapping[str, float],
) -> tuple[DecisionKey, ...]:
    """The batch path's own driver loop: one YES-side evaluation per depth
    snapshot with a genuine (non-null) ask, latched across the whole run.

    V1 scope (stated, not hidden): evaluates ``side="yes"`` only. Every
    ``instrument_id`` on the tape is that rung's YES market (matching
    :func:`parse_rung_instrument_id`'s own convention and every
    ``SidedAsk(side="yes", ...)`` fixture in
    ``tests/strategy/forecast_quantile_ladder/test_strategy.py``); a NO-side
    harness needs the sibling NO instrument's bid, which is a distinct data
    seam this slice does not build (see the SL-13p return notes).

    Every ``climate_day`` seen must be inside the sealed pre-freeze window
    (:func:`assert_pre_freeze_tape_day`) -- enforced unconditionally, on
    every call, regardless of scope. The full-study ``>= MIN_PRE_FREEZE_DAYS``
    distinct-day requirement (ruling §12 A-5) is a STUDY-level concern, not a
    per-call one (a caller may legitimately run one day at a time and
    accumulate); call :func:`assert_minimum_pre_freeze_days` once, over the
    full set of days a parity study actually covers, before treating that
    study as A-5-complete.
    """
    ordered = sorted(depth_snapshots, key=lambda row: row.ts_ns)

    states_by_station: dict[str, ForecastQuantileState] = {}
    for nbp_row in nbp_rows:
        if nbp_row.variable not in NBP_QUANTILE_VARIABLES:
            continue
        state = states_by_station.setdefault(nbp_row.station, ForecastQuantileState())
        state.push(
            variable=nbp_row.variable,
            value_f=nbp_row.value_f,
            available_at_ns=nbp_row.available_at_ns,
            cycle_runtime_ns=nbp_row.cycle_runtime_ns,
        )

    for row in ordered:
        _station, climate_day, _rung_id = parse_rung_instrument_id(row.instrument_id)
        assert_pre_freeze_tape_day(climate_day)

    latch = QuantileLadderLatch()
    keys: list[DecisionKey] = []
    for row in ordered:
        if row.best_ask_price is None:
            continue
        station, climate_day, rung_id = parse_rung_instrument_id(row.instrument_id)
        ladder = ladder_by_key[(station, climate_day)]
        std_utc_offset_hours = std_utc_offset_hours_by_station[station]
        vector = states_by_station.get(station)
        snapshot_input = BatchSnapshotInput(
            now_ns=row.ts_ns,
            std_utc_offset_hours=std_utc_offset_hours,
            station=station,
            climate_day=climate_day,
            ladder=ladder,
            rung_id=rung_id,
            side="yes",
            ask=SidedAsk(side="yes", instrument_id=row.instrument_id, price=row.best_ask_price),
            fee_coefficient=fee_coefficient,
            slippage_floor_prob=slippage_floor_prob,
            vector=None if vector is None else vector.value_at(row.ts_ns),
        )
        decision = evaluate_batch_snapshot(
            snapshot_input,
            cfg=ladder_cfg,
            artefact=artefact,
            bounds_provider=bounds_provider,
            latch=latch,
        )
        keys.append(
            decision_key_from(
                decision,
                station=station,
                climate_day=climate_day,
                rung_id=rung_id,
                side="yes",
                ts_ns=row.ts_ns,
            ),
        )
    return tuple(keys)

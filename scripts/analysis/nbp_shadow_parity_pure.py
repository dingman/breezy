"""SL-13p A-5 shadow-parity: the PURE batch path.

Ruling `docs/evidence/RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-5
(binding) and plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`
§4.4. Parity compares two independent code paths on PRE-FREEZE tape only
(2026-08-30..2026-09-25, >= 14 days):

* (i) the LIVE code path -- the NBP actor and the `forecast_quantile_ladder`
  strategy composed in a native Nautilus `BacktestEngine` replay of the
  captured tape (``nbp_shadow_parity.py``, the sibling orchestrator);
* (ii) the BATCH path -- THIS module. An offline recomputation of decisions
  from the same NBP rows and tape, reimplementing the take/refuse formulas
  DIRECTLY from the plan and ruling text (never calling
  ``forecast_quantile_ladder.decision.evaluate``, ``.margin.forecast_margin``
  or ``weather_common.costs.venue_fee_prob`` -- review item 1, SL-13p2: a
  shared scoring call would make A-5 a vacuous self-comparison even though
  the live/batch entry points differ). Only genuinely low-level, side-free
  math primitives are shared: ``quantile_density`` (``Percentiles``,
  ``Rung``, ``EmosParams``, ``CdfMethod``), the shared ``location_correction``
  module (``daylight_hours``,
  ``correction_prediction_f`` -- FQ-S4b, plan §3 S4b), and the
  ``bounds``/``latch`` Protocols both paths are independently WIRED to (not
  the scoring logic itself). NO import of the strategy or actor classes
  either, and NO import of ``calibration_artefact.LiveCalibration``/
  ``.resolve`` -- :class:`BatchCalibration`/:func:`resolve_batch_calibration`
  below reimplement that per-version resolution independently. Pinned by
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
from breezy.ingest.gaps import local_standard_date
from breezy.runtime.trade_supervisor_core import LAUNCH_UTC
from breezy.strategy.forecast_quantile_ladder.bounds import BoundsProvider
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import (
    NBP_QUANTILE_VARIABLES,
    ForecastQuantileState,
    ForecastQuantileVector,
)
from breezy.strategy.ladder_ev.location_correction import (
    CorrectionForm,
    correction_prediction_f,
    daylight_hours,
)
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams, Percentiles, Rung

__all__ = [
    "MIN_PRE_FREEZE_DAYS",
    "NUMERIC_FIELD_TOLERANCE",
    "OPPOSITE_SIDE_LATCHED",
    "PRE_FREEZE_END",
    "PRE_FREEZE_START",
    "BatchCalibration",
    "BatchCalibrationUnknownVersionError",
    "BatchSnapshotInput",
    "DecisionKey",
    "DepthSnapshotRow",
    "InsufficientPreFreezeDaysError",
    "NbpQuantileRow",
    "ParityReport",
    "PostFreezeTapeRefusedError",
    "ResolvedBatchCalibration",
    "UnparsableRungInstrumentIdError",
    "assert_minimum_pre_freeze_days",
    "assert_pre_freeze_tape_day",
    "decision_key_from",
    "diff_decision_keys",
    "evaluate_batch_snapshot",
    "hours_to_settlement",
    "no_depth_census",
    "nominal_permit_expiry_upper_bound",
    "parse_rung_instrument_id",
    "permit_covers",
    "permit_window_for_day",
    "resolve_batch_calibration",
    "run_batch_parity",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000
_NS_PER_HOUR: Final[int] = 3_600 * _NS_PER_SECOND
NUMERIC_FIELD_TOLERANCE: Final[float] = 1e-9

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
    instrument_id: str
    side: Literal["yes", "no"]
    action: str
    reason: str | None
    ts_ns: int
    ev_net: float | None = None
    p_hat: float | None = None
    p_lower: float | None = None
    p_upper: float | None = None

    @property
    def kind(self) -> str:
        return self.action


_COUNT_SIDES: Final[tuple[Literal["yes", "no"], ...]] = ("yes", "no")
_COUNT_KINDS: Final[tuple[str, ...]] = ("NotDPlus1", "NotExecutable", "Refuse", "Take")


def _side_kind_counts(path: str, keys: Iterable[DecisionKey]) -> dict[str, int]:
    """Closed per-(side, kind) counts for one path. Missing buckets stay 0."""
    counts = {
        f"n_{path}_{side}_{kind}": 0 for side in _COUNT_SIDES for kind in _COUNT_KINDS
    }
    for key in keys:
        name = f"n_{path}_{key.side}_{key.kind}"
        if name not in counts:
            raise ValueError(
                f"decision kind {key.kind!r} on side {key.side!r} is outside "
                "the closed parity count set",
            )
        counts[name] += 1
    return counts


def decision_key_from(
    decision: Decision,
    *,
    station: str,
    climate_day: date,
    rung_id: str,
    side: Literal["yes", "no"],
    instrument_id: str,
    ts_ns: int,
) -> DecisionKey:
    reason = getattr(decision, "reason", None)
    ev_net = decision.ev_net if isinstance(decision, Take) else None
    p_hat = decision.p_hat if isinstance(decision, Take) else None
    p_lower = decision.p_lower if isinstance(decision, Take) else None
    p_upper = decision.p_upper if isinstance(decision, Take) else None
    return DecisionKey(
        station=station,
        climate_day=climate_day,
        rung_id=rung_id,
        instrument_id=decision.instrument_id if isinstance(decision, Take) else instrument_id,
        side=side,
        action=type(decision).__name__,
        reason=None if reason is None else str(reason),
        ts_ns=ts_ns,
        ev_net=ev_net,
        p_hat=p_hat,
        p_lower=p_lower,
        p_upper=p_upper,
    )


def _sort_key(key: DecisionKey) -> tuple[str, date, str, str, str, str, str | None, int]:
    return (
        key.station,
        key.climate_day,
        key.rung_id,
        key.instrument_id,
        key.side,
        key.action,
        key.reason,
        key.ts_ns,
    )


def _identity_key(key: DecisionKey) -> tuple[str, date, str, str, str, str, str | None, int]:
    return (
        key.station,
        key.climate_day,
        key.rung_id,
        key.instrument_id,
        key.side,
        key.action,
        key.reason,
        key.ts_ns,
    )


def _numeric_fields_equal(live: DecisionKey, batch: DecisionKey) -> bool:
    for name in ("ev_net", "p_hat", "p_lower", "p_upper"):
        live_value = getattr(live, name)
        batch_value = getattr(batch, name)
        if live_value is None or batch_value is None:
            if live_value != batch_value:
                return False
            continue
        if abs(live_value - batch_value) > NUMERIC_FIELD_TOLERANCE:
            return False
    return True


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
    side_kind_counts: Mapping[str, int]
    numeric_mismatches: tuple[tuple[DecisionKey, DecisionKey], ...] = ()

    @property
    def n_live_only(self) -> int:
        return len(self.live_only)

    @property
    def n_batch_only(self) -> int:
        return len(self.batch_only)

    @property
    def n_mismatches(self) -> int:
        return self.n_live_only + self.n_batch_only + self.n_numeric_mismatches

    @property
    def n_numeric_mismatches(self) -> int:
        return len(self.numeric_mismatches)

    def to_counts_dict(self) -> dict[str, int]:
        """Mismatch COUNTS only -- no key detail, no ev/p&l/outcome field.

        Also the closed per-(path, side, kind) counts. Still counts: no key
        detail and no scored field.
        """
        counts = {
            "n_live": self.n_live,
            "n_batch": self.n_batch,
            "n_matched": self.n_matched,
            "n_live_only": self.n_live_only,
            "n_batch_only": self.n_batch_only,
            "n_numeric_mismatches": self.n_numeric_mismatches,
            "n_mismatches": self.n_mismatches,
        }
        counts.update(self.side_kind_counts)
        return counts


def diff_decision_keys(
    live: Iterable[DecisionKey], batch: Iterable[DecisionKey],
) -> ParityReport:
    """decision-key set equality (ruling §12 A-5: "mismatches = 0")."""
    live_by_key = {_identity_key(item): item for item in live}
    batch_by_key = {_identity_key(item): item for item in batch}
    live_set = frozenset(live_by_key)
    batch_set = frozenset(batch_by_key)
    matched = live_set & batch_set
    numeric_mismatches = tuple(
        (live_by_key[key], batch_by_key[key])
        for key in sorted(matched)
        if not _numeric_fields_equal(live_by_key[key], batch_by_key[key])
    )
    side_kind_counts = _side_kind_counts("live", live_by_key.values())
    side_kind_counts.update(_side_kind_counts("batch", batch_by_key.values()))
    return ParityReport(
        n_live=len(live_set),
        n_batch=len(batch_set),
        n_matched=len(matched),
        live_only=tuple(sorted((live_by_key[key] for key in live_set - batch_set), key=_sort_key)),
        batch_only=tuple(
            sorted((batch_by_key[key] for key in batch_set - live_set), key=_sort_key),
        ),
        side_kind_counts=side_kind_counts,
        numeric_mismatches=numeric_mismatches,
    )


# ---------------------------------------------------------------------------
# The batch path: an INDEPENDENT reimplementation of the take/refuse
# formulas (review item 1, SL-13p2) -- never `decision.evaluate`, never a
# strategy/actor import.
# ---------------------------------------------------------------------------

#: Sizing is always exactly 1 contract (plan §3.3), mirrored independently
#: of `forecast_quantile_ladder.decision.QTY` (never imported).
_QTY: Final = 1

#: Same reason string `decision.py`'s `VECTOR_DAY_MISMATCH` constant carries
#: -- kept textually identical (not imported) so a live-vs-batch
#: `DecisionKey.reason` comparison is a real check, never a mismatch that is
#: an artefact of two paths spelling the same refusal differently.
_VECTOR_DAY_MISMATCH: Final[str] = "vector_day_mismatch"

#: Same reason string `decision.py`'s `CALIBRATION_VERSION_UNAVAILABLE`
#: constant carries (FQ-S4b, plan §3 S4b) -- textually identical, not
#: imported. Checked immediately after `_VECTOR_DAY_MISMATCH`, mirroring
#: `decision.evaluate`'s own check order (that function's docstring: "A
#: later slice that adds a scoring refusal must insert it after (8)").
_CALIBRATION_VERSION_UNAVAILABLE: Final[str] = "calibration_version_unavailable"

#: D10 / S10, mirrored independently (plan §3 S4: "The batch path mirrors
#: D10's `opposite_side_latched` independently"). Textually identical to
#: `decision.OPPOSITE_SIDE_LATCHED`, never imported.
OPPOSITE_SIDE_LATCHED: Final[str] = "opposite_side_latched"

_OPPOSITE: Final[dict[Literal["yes", "no"], Literal["yes", "no"]]] = {
    "yes": "no",
    "no": "yes",
}


# ---------------------------------------------------------------------------
# FQ-S4b: the batch path's OWN per-version calibration resolution --
# independently reimplemented from `calibration_artefact.LiveCalibration`/
# `.resolve` (never imported, never called), sharing only the low-level,
# side-free `location_correction` primitives (plan §3 S4b, review item 1).
# ---------------------------------------------------------------------------


class BatchCalibrationUnknownVersionError(KeyError):
    """Mirrors `calibration_artefact.CalibrationArtefactUnknownVersionError`
    (never imported): raised by :func:`resolve_batch_calibration` when
    ``era`` names an NBM version this calibration carries no parameters/
    draws for. The batch path's own :func:`_evaluate_independently` turns
    this into ``Refuse(_CALIBRATION_VERSION_UNAVAILABLE)``, never an
    uncaught exception."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchCalibration:
    """Independent mirror of `calibration_artefact.LiveCalibration`'s SHAPE
    (never imported -- review item 1, SL-13p2/S4b): the batch path's own
    per-version EMOS point/draws plus the shared location-correction
    configuration. The CLI orchestrator (``nbp_shadow_parity.py``)
    constructs ONE of these per run, from the SAME sha-pinned fields
    ``calibration_artefact.load_live_calibration`` already validated for the
    live leg -- loading/parsing (the sha pin, the schema, the fail-closed
    checks) is shared, read ONCE; only the RESOLUTION math below is
    independently written.
    """

    cdf_method: CdfMethod
    correction_form: CorrectionForm
    linear_coefficients: tuple[float, float] | None
    month_offsets: Mapping[int, float]
    point_by_version: Mapping[str, EmosParams]
    draws_by_version: Mapping[str, tuple[EmosParams, ...]]


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedBatchCalibration:
    """One ``(era, latitude_deg, climate_day)`` resolution -- the batch
    path's own mirror of `calibration_artefact.ResolvedCalibration`."""

    cdf_method: CdfMethod
    point: EmosParams
    draws: tuple[EmosParams, ...]
    correction_f: float


def resolve_batch_calibration(
    calibration: BatchCalibration, era: str, *, latitude_deg: float, climate_day: date,
) -> ResolvedBatchCalibration:
    """The batch path's OWN per-version resolution (review item 1, S4b):
    reimplements `calibration_artefact.LiveCalibration.resolve` directly
    from the plan text, never calling it. Shares only the low-level,
    side-free `location_correction` primitives (`daylight_hours`,
    `correction_prediction_f`), per the module docstring.

    Raises :class:`BatchCalibrationUnknownVersionError` when ``era`` is not
    a version this calibration carries parameters for -- never pools or
    substitutes a different version's draws (finding F3).
    """
    point = calibration.point_by_version.get(era)
    draws = calibration.draws_by_version.get(era)
    if point is None or not draws:
        raise BatchCalibrationUnknownVersionError(
            f"{era!r} is not a version this calibration carries parameters "
            f"for ({sorted(calibration.point_by_version)!r})",
        )
    day_length_hours = daylight_hours(latitude_deg, climate_day)
    correction_f = correction_prediction_f(
        calibration.correction_form,
        month=climate_day.month,
        day_length_hours=day_length_hours,
        month_offsets=calibration.month_offsets,
        linear_coefficients=calibration.linear_coefficients,
    )
    corrected_point = EmosParams(a=point.a + correction_f, gamma=point.gamma, delta=point.delta)
    corrected_draws = tuple(
        EmosParams(a=draw.a + correction_f, gamma=draw.gamma, delta=draw.delta) for draw in draws
    )
    return ResolvedBatchCalibration(
        cdf_method=calibration.cdf_method,
        point=corrected_point,
        draws=corrected_draws,
        correction_f=correction_f,
    )


class AskSideMismatchError(ValueError):
    """Raised when a :class:`SidedAsk` was quoted from the wrong side's
    instrument -- mirrors ``decision.AskSideMismatchError`` (never imported)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SidedAsk:
    """One venue ask, tagged with the side and instrument it was quoted from.

    Independently defined (never imported from ``decision.py``) -- review
    item 1, SL-13p2.
    """

    side: Literal["yes", "no"]
    instrument_id: str
    price: float


@dataclass(frozen=True, slots=True, kw_only=True)
class NotExecutable:
    """Outside a live order-permit window: never latched, never a trial."""

    reason: str = "outside_permit_window"


@dataclass(frozen=True, slots=True, kw_only=True)
class NotDPlus1:
    """``climate_day`` is not D+1 of ``now_ns`` in the station's LST."""

    reason: str = "not_d_plus_1"


@dataclass(frozen=True, slots=True, kw_only=True)
class Refuse:
    """Evaluated, but not taken; the latch is untouched."""

    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Take:
    """The first qualifying snapshot for this (station-day, rung, side)."""

    instrument_id: str
    station: str
    climate_day: date
    side: Literal["yes", "no"]
    rung_id: str
    qty: Literal[1]
    ev_net: float
    p_hat: float
    p_lower: float
    p_upper: float


Decision = NotExecutable | NotDPlus1 | Refuse | Take


def _is_d_plus_1(*, now_ns: int, climate_day: date, std_utc_offset_hours: float) -> bool:
    """Plan §2.3: "V1 is D+1 only." Reimplemented from ``local_standard_date``
    (a low-level calendar primitive, not forecast-quantile-ladder scoring
    logic) directly, never via ``decision._is_d_plus_1`` (private, and would
    re-couple the two paths regardless)."""
    today_lst = local_standard_date(now_ns, std_utc_offset_hours)
    return climate_day == today_lst + timedelta(days=1)


def _forecast_margin(h_hours: float, cfg: LadderEvConfig) -> float:
    """Ruling `RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-6 (quoted in
    `forecast_quantile_ladder/margin.py`'s own docstring) / review item 1:
    "margin(h) = 0.02 + 0.04*clamp((h - 6)/18, 0, 1)". Reimplemented HERE,
    independently of `forecast_quantile_ladder.margin.forecast_margin`
    (never imported) -- reads the SAME `LadderEvConfig` fields
    (`margin_m0`/`margin_m24`/`margin_h0_hours`) that function reads, so a
    config change is reflected identically on both paths without either
    path calling the other's code.
    """
    m0 = cfg.margin_m0
    m24 = cfg.margin_m24
    h0 = float(cfg.margin_h0_hours)
    span = 24.0 - h0
    t = min(1.0, max(0.0, (h_hours - h0) / span))
    return m0 + (m24 - m0) * t


def _fee_prob(*, price: float, fee_coefficient: float) -> float:
    """Plan §4.2 / review item 1: "fee = 0.0695*p*(1-p) per share".
    Reimplemented HERE, independently of
    `weather_common.costs.venue_fee_prob` (never imported)."""
    return fee_coefficient * price * (1.0 - price)


def _evaluate_independently(
    *,
    now_ns: int,
    std_utc_offset_hours: float,
    permit_covers_now: bool,
    vector: ForecastQuantileVector | None,
    station: str,
    climate_day: date,
    ladder: Sequence[Rung],
    rung_id: str,
    side: Literal["yes", "no"],
    ask: SidedAsk,
    fee_coefficient: float,
    slippage_floor_prob: float,
    h_hours: float,
    cfg: LadderEvConfig,
    calibration: BatchCalibration,
    latitude_deg: float,
    bounds_provider: BoundsProvider,
    latch: QuantileLadderLatch,
) -> Decision:
    """The pure path's OWN take/refuse evaluation (review item 1, SL-13p2).

    Ruling `RULING_forecast_nbp_reopen_2026-09-29.md` §12 A-6 (quoted
    verbatim in `forecast_quantile_ladder/decision.py`'s own docstring,
    which this function deliberately never calls): "The take rule is
    side-specific: YES needs `p_lower - ask - fee(ask) > margin`; NO needs
    `(1 - p_upper) - no_ask - fee(no_ask) > margin`, and `no_ask` MUST be
    quoted from the native NO instrument." ``ask.price`` here is always
    THIS side's own instrument price (the caller builds ``SidedAsk`` off
    the NO instrument's own book for a NO evaluation -- see
    :func:`run_batch_parity`), never derived from the sibling leg.

    Check order, reason strings and the D+1/permit/latch/vector-availability
    gates mirror `decision.evaluate` exactly (so a live-vs-batch
    `DecisionKey` compares like for like) -- only the ARITHMETIC (fee,
    margin, net) and the control-flow that computes it are independently
    written, never shared. FQ-S4b adds the opposite-side latch check (D10 /
    S10) and the per-version calibration resolution (S2), at the SAME
    position `decision.evaluate` places them.
    """
    if ask.side != side:
        raise AskSideMismatchError(
            f"ask was quoted from the {ask.side!r} instrument {ask.instrument_id!r}, "
            f"but this evaluation is for side {side!r}",
        )

    rung_ids = {rung.rung_id for rung in ladder}
    if rung_id not in rung_ids:
        raise ValueError(f"rung_id {rung_id!r} is not a member of `ladder`")

    if not _is_d_plus_1(
        now_ns=now_ns, climate_day=climate_day, std_utc_offset_hours=std_utc_offset_hours,
    ):
        return NotDPlus1()

    if not permit_covers_now:
        return NotExecutable()

    if latch.is_latched(station=station, climate_day=climate_day, rung_id=rung_id, side=side):
        return Refuse(reason="already_latched")

    # Precedence, pinned: own-side latch (above) then this opposite-side
    # check, then forecast_unavailable/vector_day_mismatch/calibration
    # resolution -- mirrors `decision.evaluate`'s own check order exactly.
    if latch.is_latched(
        station=station, climate_day=climate_day, rung_id=rung_id, side=_OPPOSITE[side],
    ):
        return Refuse(reason=OPPOSITE_SIDE_LATCHED)

    if vector is None:
        return Refuse(reason="forecast_unavailable")

    if vector.climate_day != climate_day:
        return Refuse(reason=_VECTOR_DAY_MISMATCH)

    try:
        resolved = resolve_batch_calibration(
            calibration, vector.model_version, latitude_deg=latitude_deg, climate_day=climate_day,
        )
    except BatchCalibrationUnknownVersionError:
        return Refuse(reason=_CALIBRATION_VERSION_UNAVAILABLE)

    percentiles = Percentiles(
        q10=vector.q10,
        q25=vector.q25,
        q50=vector.q50,
        q75=vector.q75,
        q90=vector.q90,
        mean=vector.mean,
        sd=vector.sd,
    )
    # `resolved.point` is deliberately never read here (ruling A-6, mirrored
    # from `decision.evaluate`): only `resolved.draws` carries statistical
    # uncertainty into the injected `BoundsProvider`, which derives `p_hat`
    # as the MEAN of the per-draw rung probabilities. `point` is kept on
    # `ResolvedBatchCalibration` only for a future live/batch parity check,
    # mirroring `calibration_artefact.ResolvedCalibration.point`'s own
    # docstring.
    bounds = bounds_provider(
        percentiles=percentiles, draws=resolved.draws, ladder=ladder, rung_id=rung_id,
    )
    p_hat, p_lower, p_upper = bounds.p_hat, bounds.p_lower, bounds.p_upper

    fee = _fee_prob(price=ask.price, fee_coefficient=fee_coefficient)
    # Ruling §12 A-6's own formula carries no slippage term (it is always
    # 0.0 at every call site in this repo); summed here anyway so a future
    # non-zero `slippage_floor_prob` still parity-matches the live path's
    # `DepthAwareTradeCost.total_prob = fee_prob + slippage_floor_prob`,
    # rather than silently diverging from it.
    if side == "yes":
        net = p_lower - ask.price - fee - slippage_floor_prob
    else:
        net = (1.0 - p_upper) - ask.price - fee - slippage_floor_prob

    buffer = _forecast_margin(h_hours, cfg)
    if not (net > buffer):
        return Refuse(reason="below_margin")

    latch.latch(station=station, climate_day=climate_day, rung_id=rung_id, side=side)
    return Take(
        instrument_id=ask.instrument_id,
        station=station,
        climate_day=climate_day,
        side=side,
        rung_id=rung_id,
        qty=_QTY,
        ev_net=net,
        p_hat=p_hat,
        p_lower=p_lower,
        p_upper=p_upper,
    )


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
    station: str | None = None
    climate_day: date | None = None
    rung_id: str | None = None
    side: Literal["yes", "no"] = "yes"


@dataclass(frozen=True, slots=True, kw_only=True)
class NbpQuantileRow:
    """One derived NBP quantile/summary row -- the fields
    :meth:`ForecastQuantileState.push` needs, decoupled from
    ``breezy.persistence.nbp_derived_store.DerivedNbpRow`` (that module is a
    backfill-store reader/writer, out of scope for this pure path).

    ``valid_start_ns``/``valid_end_ns`` (FQ-S4b, plan §3 S4b) are the row's
    OWN MAX-column validity window -- carried through so the live leg's
    ``ForecastPoint`` (``nbp_shadow_parity.py``) is built from this row's
    REAL window, never a placeholder repeating ``cycle_runtime_ns``.
    """

    station: str
    variable: str
    cycle_runtime_ns: int
    valid_start_ns: int
    valid_end_ns: int
    value_f: float | None
    available_at_ns: int
    climate_day: date
    header_model_version: str


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
    latitude_deg: float


def _row_context(row: DepthSnapshotRow) -> tuple[str, date, str, Literal["yes", "no"]]:
    if row.station is not None and row.climate_day is not None and row.rung_id is not None:
        return row.station, row.climate_day, row.rung_id, row.side
    station, climate_day, rung_id = parse_rung_instrument_id(row.instrument_id)
    return station, climate_day, rung_id, row.side


def evaluate_batch_snapshot(
    inp: BatchSnapshotInput,
    *,
    cfg: LadderEvConfig,
    calibration: BatchCalibration,
    bounds_provider: BoundsProvider,
    latch: QuantileLadderLatch,
) -> Decision:
    """Call :func:`_evaluate_independently` -- review item 1 (SL-13p2): the
    batch path's OWN reimplementation of the take/refuse formulas, never
    ``decision.evaluate``."""
    h_hours = hours_to_settlement(
        now_ns=inp.now_ns,
        climate_day=inp.climate_day,
        std_utc_offset_hours=inp.std_utc_offset_hours,
    )
    return _evaluate_independently(
        now_ns=inp.now_ns,
        std_utc_offset_hours=inp.std_utc_offset_hours,
        permit_covers_now=permit_covers(inp.now_ns),
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
        calibration=calibration,
        latitude_deg=inp.latitude_deg,
        bounds_provider=bounds_provider,
        latch=latch,
    )


def no_depth_census(depth_snapshots: Sequence[DepthSnapshotRow]) -> dict[str, int]:
    """Days with at least one NO-leg depth row, per station on the tape.

    Every station that appears (YES or NO) is present. The value is the
    number of distinct climate days carrying a ``side="no"`` row, so a
    YES-only station is 0. Counts only: never a price, a size, or an outcome.
    """
    no_days: dict[str, set[date]] = {}
    stations: set[str] = set()
    for row in depth_snapshots:
        station, climate_day, _rung_id, side = _row_context(row)
        stations.add(station)
        if side == "no":
            no_days.setdefault(station, set()).add(climate_day)
    return {
        station: len(no_days[station]) if station in no_days else 0
        for station in sorted(stations)
    }


def run_batch_parity(
    *,
    depth_snapshots: Sequence[DepthSnapshotRow],
    nbp_rows: Sequence[NbpQuantileRow],
    ladder_by_key: Mapping[tuple[str, date], Sequence[Rung]],
    calibration: BatchCalibration,
    ladder_cfg: LadderEvConfig,
    bounds_provider: BoundsProvider,
    fee_coefficient: float,
    slippage_floor_prob: float,
    std_utc_offset_hours_by_station: Mapping[str, float],
    latitude_deg_by_station: Mapping[str, float],
    quantile_station_keys: Mapping[str, str] | None = None,
    stations: Sequence[str] | None = None,
) -> tuple[DecisionKey, ...]:
    """The batch path's own driver loop: one evaluation per depth snapshot
    with a genuine (non-null) ask, on that row's own side, latched across
    the whole run.

    A NO-leg depth row (``side="no"``, ask quoted from the native NO
    instrument) is evaluated as NO. The live harness stamps that side from
    the instrument leg before calling this function. ``side`` defaults to
    ``"yes"`` only when the caller did not set it.

    Every ``climate_day`` seen must be inside the sealed pre-freeze window
    (:func:`assert_pre_freeze_tape_day`) -- enforced unconditionally, on
    every call, regardless of scope. The full-study ``>= MIN_PRE_FREEZE_DAYS``
    distinct-day requirement (ruling §12 A-5) is a STUDY-level concern, not a
    per-call one (a caller may legitimately run one day at a time and
    accumulate); call :func:`assert_minimum_pre_freeze_days` once, over the
    full set of days a parity study actually covers, before treating that
    study as A-5-complete.
    """
    station_key_map = quantile_station_keys if quantile_station_keys is not None else {}
    allowed = None if stations is None else frozenset(stations)
    # Drop non-manifest rows before the pre-freeze assert and before the
    # ladder lookup, so a foreign station cannot fail the study or KeyError.
    ordered = sorted(
        (
            row
            for row in depth_snapshots
            if allowed is None or _row_context(row)[0] in allowed
        ),
        key=lambda row: row.ts_ns,
    )

    states_by_station: dict[str, ForecastQuantileState] = {}
    for nbp_row in nbp_rows:
        if nbp_row.variable not in NBP_QUANTILE_VARIABLES:
            continue
        state = states_by_station.setdefault(nbp_row.station, ForecastQuantileState())
        # "header wins" convention (plan D2, SL-13 S2) -- the SAME
        # transformation `ForecastQuantileStateActor.on_data` applies to a
        # live `ForecastPoint.model_version`, reimplemented here so the
        # batch path resolves calibration per the SAME NBM version era.
        state.push(
            variable=nbp_row.variable,
            value_f=nbp_row.value_f,
            available_at_ns=nbp_row.available_at_ns,
            cycle_runtime_ns=nbp_row.cycle_runtime_ns,
            climate_day=nbp_row.climate_day,
            model_version=f"v{nbp_row.header_model_version}",
        )

    for row in ordered:
        _station, climate_day, _rung_id, _side = _row_context(row)
        assert_pre_freeze_tape_day(climate_day)

    latch = QuantileLadderLatch()
    keys: list[DecisionKey] = []
    for row in ordered:
        if row.best_ask_price is None:
            continue
        station, climate_day, rung_id, side = _row_context(row)
        ladder = ladder_by_key[(station, climate_day)]
        std_utc_offset_hours = std_utc_offset_hours_by_station[station]
        vector = states_by_station.get(station_key_map.get(station, station))
        snapshot_input = BatchSnapshotInput(
            now_ns=row.ts_ns,
            std_utc_offset_hours=std_utc_offset_hours,
            station=station,
            climate_day=climate_day,
            ladder=ladder,
            rung_id=rung_id,
            side=side,
            ask=SidedAsk(side=side, instrument_id=row.instrument_id, price=row.best_ask_price),
            fee_coefficient=fee_coefficient,
            slippage_floor_prob=slippage_floor_prob,
            vector=None if vector is None else vector.value_at(row.ts_ns),
            latitude_deg=latitude_deg_by_station[station],
        )
        decision = evaluate_batch_snapshot(
            snapshot_input,
            cfg=ladder_cfg,
            calibration=calibration,
            bounds_provider=bounds_provider,
            latch=latch,
        )
        keys.append(
            decision_key_from(
                decision,
                station=station,
                climate_day=climate_day,
                rung_id=rung_id,
                side=side,
                instrument_id=row.instrument_id,
                ts_ns=row.ts_ns,
            ),
        )
    return tuple(keys)

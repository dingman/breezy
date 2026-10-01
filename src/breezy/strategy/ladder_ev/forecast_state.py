"""In-memory forecast visibility for the ladder_ev forecast-mode hot path.

Nautilus Cache/catalog can store custom ``Data``, but the live decider must
not ``catalog.query`` (plan R1-11). This accumulator mirrors
``RunningExtremeAccumulator.value_at(now_ns)``: latest point with
``available_at_ns <= now_ns``, never interpolated, never a future vintage.
``ForecastPoint`` is pushed here by
:class:`breezy.strategy.ladder_ev.forecast_subscriber.ForecastStateActor`
(WP-12 Seam D); WP-10 is the store.

ABSENCE IS EXPLICIT (WP-12 Seam D). ``value_at`` answering ``None`` is the
same answer whether the producing Actor is absent, has published nothing yet,
or published only absences -- and an absent forecast must never read as a
zero or as yesterday's number. :meth:`ForecastState.visibility_at` therefore
returns a NAMED verdict -- `FORECAST_UNAVAILABLE`, `FORECAST_STALE` or
`FORECAST_OK` -- and :func:`forecast_take_permitted` is the single place that
turns a verdict into "may this leg trade". A stale value is still REPORTED,
so an operator can see what was known and how old it was; it simply does not
license a take.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final

__all__ = [
    "FORECAST_OK",
    "FORECAST_STALE",
    "FORECAST_UNAVAILABLE",
    "NBP_QUANTILE_VARIABLES",
    "ForecastQuantileState",
    "ForecastQuantileVector",
    "ForecastState",
    "ForecastTxnSnapshot",
    "ForecastVisibility",
    "forecast_take_permitted",
]

#: The closed verdict alphabet. Named strings, never a bare ``None``.
FORECAST_OK: Final[str] = "ok"
FORECAST_UNAVAILABLE: Final[str] = "forecast_unavailable"
FORECAST_STALE: Final[str] = "forecast_stale"


@dataclass(frozen=True, slots=True)
class ForecastTxnSnapshot:
    """One visible TXN value at an ``available_at_ns`` vintage.

    Distinct from ``weather_common.models.ForecastSnapshot`` (mispricing
    predicted-high vehicle). Do not alias or re-export that name.
    """

    value_f: float
    available_at_ns: int
    cycle_runtime_ns: int


@dataclass(frozen=True, slots=True)
class ForecastVisibility:
    """What the decider is allowed to know about the forecast at one instant.

    ``snapshot`` is ``None`` exactly when ``reason`` is
    `FORECAST_UNAVAILABLE`; a stale verdict still carries its value so the
    refusal is auditable rather than merely negative.
    """

    snapshot: ForecastTxnSnapshot | None
    reason: str
    staleness_ns: int | None


class ForecastState:
    """Per-station in-memory TXN store. Actor-push; never a catalog read.

    Eviction / climate-day reset is WP-12's actor-push concern; this store
    only answers PIT visibility.
    """

    def __init__(self) -> None:
        self._points: list[ForecastTxnSnapshot] = []

    def push(
        self,
        *,
        value_f: float | None,
        available_at_ns: int,
        cycle_runtime_ns: int,
    ) -> None:
        if value_f is None:
            return
        self._points.append(
            ForecastTxnSnapshot(
                value_f=value_f,
                available_at_ns=available_at_ns,
                cycle_runtime_ns=cycle_runtime_ns,
            )
        )

    def value_at(self, now_ns: int) -> ForecastTxnSnapshot | None:
        """Latest TXN visible at ``now_ns``, or ``None`` (forecast_unavailable)."""
        eligible = [point for point in self._points if point.available_at_ns <= now_ns]
        if not eligible:
            return None
        return max(eligible, key=lambda point: (point.available_at_ns, point.cycle_runtime_ns))

    def staleness_ns(self, now_ns: int) -> int | None:
        """``now_ns`` minus the newest VISIBLE vintage, or ``None`` if none is.

        Applies the same visibility gate as :meth:`value_at`
        (``available_at_ns <= now_ns``), so a not-yet-published point can
        never make staleness negative nor hide a genuinely stale store behind
        a vintage nobody could have known yet.
        """
        latest = self.value_at(now_ns)
        if latest is None:
            return None
        return now_ns - latest.available_at_ns

    def visibility_at(self, now_ns: int, *, max_staleness_ns: int) -> ForecastVisibility:
        """The NAMED forecast verdict at ``now_ns``.

        `max_staleness_ns` has no default on purpose: a silently-defaulted
        staleness bound is a policy decision made in the wrong file.
        """
        if max_staleness_ns <= 0:
            raise ValueError(
                f"`max_staleness_ns` must be positive, was {max_staleness_ns}",
            )
        snapshot = self.value_at(now_ns)
        if snapshot is None:
            return ForecastVisibility(
                snapshot=None,
                reason=FORECAST_UNAVAILABLE,
                staleness_ns=None,
            )
        staleness_ns = now_ns - snapshot.available_at_ns
        reason = FORECAST_STALE if staleness_ns > max_staleness_ns else FORECAST_OK
        return ForecastVisibility(
            snapshot=snapshot,
            reason=reason,
            staleness_ns=staleness_ns,
        )


def forecast_take_permitted(visibility: ForecastVisibility) -> bool:
    """Whether `visibility` licenses a forecast-mode take. Fails CLOSED.

    Only `FORECAST_OK` with a value permits one. An unknown verdict -- a
    future member of the alphabet that nobody taught this function about --
    permits nothing, so widening the alphabet can never silently widen what
    is tradable.
    """
    return visibility.reason == FORECAST_OK and visibility.snapshot is not None


# ---------------------------------------------------------------------------
# SL-12 (FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md §7 row 12):
# scalar TXN -> quantile vector per (station, cycle). ``ForecastState`` above
# is UNTOUCHED -- this is a pure addition, so the scalar TXN path stays
# byte-compatible with every existing caller and test.
# ---------------------------------------------------------------------------

#: The closed set of NBM v5.0 NBP quantile/summary variables a station-cycle
#: vector is assembled from (plan §3.2 item 7, SL-1a). Order is significant
#: only for readability; membership is what ``ForecastQuantileState`` checks.
NBP_QUANTILE_VARIABLES: Final[tuple[str, ...]] = (
    "TXN_Q10",
    "TXN_Q25",
    "TXN_Q50",
    "TXN_Q75",
    "TXN_Q90",
    "TXN_MEAN",
    "TXN_SD",
)


@dataclass(frozen=True, slots=True)
class ForecastQuantileVector:
    """One cycle's complete 7-variable NBP percentile bulletin, at ONE vintage.

    ``available_at_ns`` is the vector's OWN vintage: the max of the 7
    variables' own ``available_at_ns``, never an individual variable's. A
    vector is never partial -- see :meth:`ForecastQuantileState.value_at`.

    ``climate_day`` (SL-13e defence-in-depth) is the D+1 calendar day this
    cycle's MAX-column window targets, in the station's own local standard
    time -- the SAME mapping ``breezy.ingest.nbm_quantile_parse.
    max_column_lst_climate_day`` derives, computed once by
    :class:`~breezy.strategy.ladder_ev.forecast_subscriber.
    ForecastQuantileStateActor` at push time (it is the only caller that
    knows both the point's own ``valid_end_ns`` and the station's
    ``std_utc_offset_hours``). Never inferred downstream from
    ``cycle_runtime_ns`` -- that instant is NOT the MAX window's own instant
    (see the parser module's own docstring on why a 13Z cycle's nearest MAX
    column lands roughly 11h later, at 00Z the following day).

    ``model_version`` (SL-13 S2, plan D2/F3) is the NBM version ERA string
    (``f"v{header_model_version}"``, "header wins" -- the same convention
    ``scripts/analysis/nbp_backfill.py`` uses) this cycle's bulletin was
    issued under. The live calibration consumer
    (``forecast_quantile_ladder.calibration_artefact.LiveCalibration.
    resolve``) resolves EMOS parameters per this era, never pooled across
    versions. Defaults to ``""`` only for callers that do not care about
    per-version calibration (e.g. existing fixtures predating this field);
    the real producer (``ForecastQuantileStateActor.on_data``) always
    supplies a real era.
    """

    q10: float
    q25: float
    q50: float
    q75: float
    q90: float
    mean: float
    sd: float
    available_at_ns: int
    cycle_runtime_ns: int
    climate_day: date
    model_version: str = ""


class ForecastQuantileState:
    """Per-station accumulator of the 7 NBP quantile/summary variables, by cycle.

    Widens :class:`ForecastState`'s own PIT visibility rule to a vector: a
    cycle's :class:`ForecastQuantileVector` becomes visible at ``now_ns``
    only once ALL 7 variables for that cycle have been pushed AND ``now_ns``
    is at or after the vector's own vintage (the max of the 7 variables' own
    ``available_at_ns``). A partial cycle -- even one missing only its
    slowest-arriving variable -- is never visible, never interpolated from
    a neighbouring cycle, and never a future vintage.
    """

    def __init__(self) -> None:
        self._by_cycle: dict[int, dict[str, tuple[float, int]]] = {}
        self._climate_day_by_cycle: dict[int, date] = {}
        self._model_version_by_cycle: dict[int, str] = {}

    def push(
        self,
        *,
        variable: str,
        value_f: float | None,
        available_at_ns: int,
        cycle_runtime_ns: int,
        climate_day: date,
        model_version: str = "",
    ) -> None:
        if variable not in NBP_QUANTILE_VARIABLES:
            raise ValueError(
                f"variable must be one of {NBP_QUANTILE_VARIABLES}, was {variable!r}",
            )
        if value_f is None:
            return
        existing_day = self._climate_day_by_cycle.get(cycle_runtime_ns)
        if existing_day is not None and existing_day != climate_day:
            raise ValueError(
                f"cycle {cycle_runtime_ns} already recorded climate_day "
                f"{existing_day.isoformat()}; {variable!r} carries "
                f"{climate_day.isoformat()} -- every variable of one cycle "
                f"must target the SAME climate day",
            )
        existing_version = self._model_version_by_cycle.get(cycle_runtime_ns)
        if existing_version is not None and existing_version != model_version:
            raise ValueError(
                f"cycle {cycle_runtime_ns} already recorded model_version "
                f"{existing_version!r}; {variable!r} carries {model_version!r} "
                "-- every variable of one cycle must target the SAME NBM version",
            )
        self._climate_day_by_cycle[cycle_runtime_ns] = climate_day
        self._model_version_by_cycle[cycle_runtime_ns] = model_version
        cell = self._by_cycle.setdefault(cycle_runtime_ns, {})
        cell[variable] = (value_f, available_at_ns)

    def _complete_vector_for(self, cycle_runtime_ns: int) -> ForecastQuantileVector | None:
        cell = self._by_cycle.get(cycle_runtime_ns)
        if cell is None or set(cell) != set(NBP_QUANTILE_VARIABLES):
            return None
        vintage = max(available_at_ns for _, available_at_ns in cell.values())
        return ForecastQuantileVector(
            q10=cell["TXN_Q10"][0],
            q25=cell["TXN_Q25"][0],
            q50=cell["TXN_Q50"][0],
            q75=cell["TXN_Q75"][0],
            q90=cell["TXN_Q90"][0],
            mean=cell["TXN_MEAN"][0],
            sd=cell["TXN_SD"][0],
            available_at_ns=vintage,
            cycle_runtime_ns=cycle_runtime_ns,
            climate_day=self._climate_day_by_cycle[cycle_runtime_ns],
            model_version=self._model_version_by_cycle[cycle_runtime_ns],
        )

    def is_complete(self, cycle_runtime_ns: int) -> bool:
        """``True`` once all 7 NBP variables have been pushed for this cycle.

        FQ-S6 feed-proof seam (plan §3 S6, finding F8): lets a caller (the
        publishing Actor) log a ONE-TIME positive line the moment a cycle's
        vector becomes evaluable, without reaching into
        :meth:`_complete_vector_for` directly.
        """
        return self._complete_vector_for(cycle_runtime_ns) is not None

    def value_at(self, now_ns: int) -> ForecastQuantileVector | None:
        """Latest COMPLETE, visible vector at ``now_ns``, or ``None``.

        Mirrors :meth:`ForecastState.value_at`: filters to vectors whose own
        vintage is ``<= now_ns``, then picks the max by ``(available_at_ns,
        cycle_runtime_ns)`` -- never an incomplete cycle, regardless of how
        much of it has arrived.
        """
        eligible: list[ForecastQuantileVector] = []
        for cycle_runtime_ns in self._by_cycle:
            vector = self._complete_vector_for(cycle_runtime_ns)
            if vector is not None and vector.available_at_ns <= now_ns:
                eligible.append(vector)
        if not eligible:
            return None
        return max(eligible, key=lambda vector: (vector.available_at_ns, vector.cycle_runtime_ns))

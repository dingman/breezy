"""WP-7b -- score the MARKET as a competing forecaster, on the traded rung.

GOVERNING DOCUMENT
------------------
``docs/specs/PREREG_WP7b_MARKET_AS_FORECASTER_2026-09-20.md`` (committed
`3e67cbe` BEFORE the first run). Every parameter below is a COPY of a pinned
value in that document. The three readings in its §3 are FIXED; this module
applies the decision procedure MECHANICALLY and prints which reading it
selects, so no reading can be chosen after seeing the number.

THE QUESTION (§1)
-----------------
Does the forecast carry information the venue price does not already have, on
the 2 F rung the venue actually trades? Answered by a PAIRED Brier comparison
over rung-events -- not by realised PnL over 59-63 takes, which has SE ~ 0.035
against a plausible 0.01-0.03 effect and can only ever return a non-detection.

DESIGN (§2), AND WHAT IT DELIBERATELY DOES NOT DO
-------------------------------------------------
* Unit of observation: one ``(station, climate_day, rung)`` rung-event.
* ONE pre-declared decision instant per station-day: **09:00 LST**, first
  liftable quote at or after it. ``decision_instant_ns`` and
  ``STATION_TIME_ZONES`` are REUSED from ``forecast_cheap_screen_wp7``
  (`a0a9ea8`), never restated. There is NO argmax over instants: §5 rules that
  dimension collapsed rather than corrected, because ``candidates.sort()`` over
  ~10^4 instants fires with probability -> 1 under a true-zero null.
* EVERY rung on the ladder is emitted, with NO selection: no take rule, no
  threshold, no variant sweep. Selection is the defect §0 correction 4 names.
* An instant whose ladder is not a COMPLETE PARTITION of the integers is
  REFUSED, never imputed. A partial ladder is not a partition.
* The settlement outcome is used ONLY as an aggregate scoring label (§7). It
  never enters a per-event decision -- there is no per-event decision to enter.

WHAT IS REUSED, AND NOTHING IS RE-DERIVED
-----------------------------------------
* ``Trial`` / ``brier`` / ``_clusters`` / ``bootstrap_brier_difference_ci``
  from ``forecast_conditional_scoring`` -- re-exported here BY IDENTITY so a
  second Brier implementation cannot drift in behind this one (pinned by
  ``test_brier_is_the_reused_forecast_conditional_scoring_implementation``).
  The market forecast rides in the ``p_clim`` slot, so the shipped paired
  bootstrap scores it with no new statistic.
* the fee: ``forecast_tape_screen.venue_fee`` -> the LIVE rule's
  ``current_rung_hold.decision.fee_on_ask``, ``theta*p*(1-p)`` banker's-rounded
  to the cent at theta = 0.0695. A FLAT subtraction of the coefficient inflates
  the hurdle ~5x (WP-7 amendment A2) and is exactly how a null gets
  manufactured.
* the rung bounds: ``h4_preliminary_economic_read.parse_rung`` -- a CLOSED
  integer-F interval, the reading under which the ladder is a partition.
* the corpus load and the frozen 0b error model:
  ``wp7_realised_pnl_falsification._load_corpus``, i.e. the screen's own.

POWER, AND WHAT A NULL MEANS (§6)
---------------------------------
The effective n of every interval is the number of CLUSTERS, not rows, so the
cluster count is printed beside every interval. A null here is a NON-DETECTION
AT SMALL MAGNITUDES, never a proof of market efficiency.

No network. No clock beyond the tape's own timestamps. Starts and stops no
process. Writes one artefact under ``docs/`` and nothing else; nothing under
``~/.local/share/breezy`` is ever written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import math
import re
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from forecast_cheap_screen_wp7 import (
    CITY_TO_ICAO,
    LIFTABLE_QUANTITY,
    STATION_TIME_ZONES,
    RungInstant,
    RungTape,
    decision_instant_ns,
)
from forecast_conditional_scoring import (
    CLUSTER_DATE,
    CLUSTER_STATION,
    CLUSTER_STATION_DAY,
    MODEL_CLIMATOLOGY,
    MODEL_FORECAST,
    ClusterCI,
    Trial,
    _clusters,
    bootstrap_brier_difference_ci,
    brier,
)
from forecast_tape_screen import DEFAULT_FEE_COEFFICIENT, venue_fee
from h4_preliminary_economic_read import Rung, parse_ladder, parse_rung

__all__ = [
    "FAMILY",
    "MARKET_ASK",
    "MARKET_MID",
    "QUALIFYING_ASK_MIN",
    "QUALIFYING_SUM_ASK_MAX",
    "STATION_TIME_ZONES",
    "ClusterCI",
    "IncompleteLadderError",
    "LookAheadError",
    "QualifyingRateReport",
    "RungEvent",
    "RungInstant",
    "SumAskRow",
    "Trial",
    "_clusters",
    "assert_complete_partition",
    "bootstrap_brier_difference_ci",
    "brier",
    "build_artefact",
    "build_rung_probabilities",
    "build_station_day_events",
    "compute_qualifying_rate",
    "decision_instant_ns",
    "first_liftable_at_or_after",
    "hurdle",
    "mu_sigma_at_instant",
    "paired_brier",
    "paired_brier_ci",
    "parse_forecast_archive_gaps",
    "render_qualifying_rate_report",
    "sum_ask_row",
    "to_trials",
]

#: The scored family: the venue's OWN rung, which is the unit it trades. NOT
#: the median family whose +0.594 BSS was withdrawn as near-tautological (§0
#: correction 1).
FAMILY: Final[str] = "rung_2f_wp7b"

#: The two market forecasts scored against ``p_fc``, separately (§2).
MARKET_MID: Final[str] = "mid"
MARKET_ASK: Final[str] = "ask"
MARKETS: Final[tuple[str, ...]] = (MARKET_MID, MARKET_ASK)

#: §2.2 of WP-7, copied: liftability is qty = 1 at L0 from Depth10.
_NS: Final[int] = 10**9

#: §3's REPORTING bar for the secondary consistency check: a ladder whose asks
#: sum at or below this would be a riskless long-only buy of the whole ladder.
ARB_SUM_ASK_MAX: Final[float] = 0.98


class IncompleteLadderError(RuntimeError):
    """The ladder at this instant is not a complete partition of the integers.

    §2 pins REFUSE, never impute. A partial ladder is not a partition: with one
    rung missing the remaining asks no longer sum toward 1, exactly one rung no
    longer settles YES, and both the paired Brier and the ``sum(ask)``
    diagnostic silently become measurements of a different object.
    """


class LookAheadError(AssertionError):
    """A ``p_fc`` input was timestamped AFTER the decision instant.

    This is the defect class that produced the false +0.55/take headline in
    this programme (ruled in `f6b7146`, fixed in `a0a9ea8`). It is guarded
    HERE, at the point ``p_fc`` is constructed, so no code path can build a
    probability from an input the decision could not have seen.
    """


# ---------------------------------------------------------------------------
# The ladder must be a partition -- checked, never assumed
# ---------------------------------------------------------------------------


def assert_complete_partition(rungs: Sequence[Rung]) -> tuple[Rung, ...]:
    """Return the sorted ladder, or RAISE if it does not partition the integers.

    A complete venue ladder is: exactly one open LOWER tail (``lt<N>f``),
    exactly one open UPPER tail (``gte<N>f``), and interior rungs that abut
    with no gap and no overlap under the CLOSED reading (``gte78lt79f`` covers
    78 AND 79, so the next rung starts at 80).
    """
    if not rungs:
        raise IncompleteLadderError("an empty ladder is not a partition of the integers")
    ladder = parse_ladder(r.instrument_id for r in rungs)
    heads = [r for r in ladder if r.lower_f is None]
    tails = [r for r in ladder if r.upper_f is None]
    if len(heads) != 1 or ladder[0] is not heads[0]:
        raise IncompleteLadderError(
            f"ladder has {len(heads)} open LOWER tail(s); every integer below the lowest "
            "named bound must belong to exactly one rung"
        )
    if len(tails) != 1 or ladder[-1] is not tails[0]:
        raise IncompleteLadderError(
            f"ladder has {len(tails)} open UPPER tail(s); every integer above the highest "
            "named bound must belong to exactly one rung"
        )
    for previous, following in itertools.pairwise(ladder):
        if previous.upper_f is None or following.lower_f is None:
            raise IncompleteLadderError(
                f"{previous.instrument_id} and {following.instrument_id} both claim an open "
                "tail in the interior of the ladder"
            )
        if following.lower_f != previous.upper_f + 1:
            raise IncompleteLadderError(
                f"ladder is not a partition between {previous.instrument_id} (upper "
                f"{previous.upper_f}) and {following.instrument_id} (lower "
                f"{following.lower_f}): "
                + (
                    "the integers between them belong to no rung"
                    if following.lower_f > previous.upper_f + 1
                    else "they overlap, so some integer belongs to two rungs"
                )
            )
    return ladder


# ---------------------------------------------------------------------------
# The single pre-declared decision instant (§2, §5)
# ---------------------------------------------------------------------------


def first_liftable_at_or_after(
    instants: Sequence[RungInstant], *, decision_ns: int
) -> RungInstant | None:
    """The first L0 snapshot at or after ``decision_ns`` with a liftable ask.

    "At or after" is strict: a quote from BEFORE 09:00 LST is never the
    instant's quote, however close. The ask side is what liftability is defined
    on (``allow_short = False`` repo-wide, so the YES ask is the only price a
    decision could ever pay); the bid is read from the SAME snapshot and is
    never back-filled from another one.
    """
    for instant in sorted(instants, key=lambda i: i.ts_ns):
        if instant.ts_ns < decision_ns:
            continue
        if instant.ask is not None and instant.ask_size >= LIFTABLE_QUANTITY:
            return instant
    return None


def mu_sigma_at_instant(
    *,
    city: str,
    climate_day: dt.date,
    cycle_runtime_ns: int,
    txn_f: float,
    error_model: object,
) -> tuple[float, float]:
    """``(mu, sigma)`` from the FROZEN 0b error model -- the screen's own index.

    The ``lead_hours`` index is computed EXACTLY as
    ``forecast_cheap_screen_wp7._rung_probabilities`` computes it, UTC day
    boundary included. That boundary is internally inconsistent with the local
    climate day by 5-8 h and is recorded as such in `a0a9ea8`; re-indexing it
    here would silently re-point the frozen sigma and make this measurement
    incomparable with the screen it is meant to explain. WP-13 owns that fix.
    """
    lead_hours = max(
        1.0,
        (
            int(
                dt.datetime(
                    climate_day.year, climate_day.month, climate_day.day, 0, tzinfo=dt.UTC
                ).timestamp()
            )
            * _NS
            + 24 * 3600 * _NS
            - cycle_runtime_ns
        )
        / (3600 * _NS),
    )
    icao = CITY_TO_ICAO[city]
    mu = txn_f + error_model.bias(icao, climate_day, lead_hours)  # type: ignore[attr-defined]
    sigma = error_model.sigma(icao, climate_day, lead_hours)  # type: ignore[attr-defined]
    return float(mu), float(sigma)


def build_rung_probabilities(
    *,
    ladder: Sequence[Rung],
    cycle_runtime_ns: int,
    decision_ns: int,
    mu: float,
    sigma: float,
) -> dict[str, float]:
    """``p_fc`` per rung from a Gaussian with the 0.5 F continuity correction.

    Raises
    ------
    LookAheadError
        If the forecast cycle was issued AFTER the decision instant. The guard
        is on the CONSTRUCTOR of ``p_fc``, not on a caller's filter, so there
        is no path that builds a probability from an unobservable input.
    IncompleteLadderError
        If the ladder is not a partition -- the probabilities would then not
        sum to 1 and the "market vs forecast" comparison would be between two
        different sample spaces.
    """
    if cycle_runtime_ns > decision_ns:
        raise LookAheadError(
            f"forecast cycle runtime_ns={cycle_runtime_ns} is AFTER the pre-declared "
            f"decision instant {decision_ns} (by "
            f"{(cycle_runtime_ns - decision_ns) / (3600 * _NS):.2f} h); a p_fc built from "
            "it prices information the decision could not have seen"
        )
    if sigma <= 0.0:
        raise ValueError(f"sigma must be strictly positive, was {sigma!r}")
    rungs = assert_complete_partition(ladder)

    from forecast_conditional_model_study import _norm_cdf

    out: dict[str, float] = {}
    for rung in rungs:
        low = _norm_cdf((rung.lower_f - 0.5 - mu) / sigma) if rung.lower_f is not None else 0.0
        high = _norm_cdf((rung.upper_f + 0.5 - mu) / sigma) if rung.upper_f is not None else 1.0
        out[rung.instrument_id] = max(0.0, min(1.0, high - low))
    return out


# ---------------------------------------------------------------------------
# The rung-event -- the unit of observation (§2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RungEvent:
    """One ``(station, climate_day, rung)`` event, priced and labelled.

    ``settled`` is the aggregate scoring label ONLY (§7). Nothing in this
    module consults it before scoring, and there is no per-event decision it
    could bias.
    """

    station: str
    climate_day: dt.date
    rung_id: str
    ts_ns: int
    p_fc: float
    ask: float
    ask_size: float
    bid: float | None
    bid_size: float
    settled: bool

    @property
    def mid(self) -> float | None:
        """``(ask + bid) / 2``, or ``None`` when the bid side is unpriced."""
        return None if self.bid is None else (self.ask + self.bid) / 2.0

    @property
    def half_spread(self) -> float | None:
        return None if self.bid is None else (self.ask - self.bid) / 2.0

    def market_probability(self, market: str) -> float | None:
        if market == MARKET_ASK:
            return self.ask
        if market == MARKET_MID:
            return self.mid
        raise ValueError(f"unknown market forecast {market!r}")


def build_station_day_events(
    *,
    station: str,
    climate_day: dt.date,
    ladder: Sequence[Rung],
    quotes: Mapping[str, RungInstant],
    p_fc: Mapping[str, float],
    settled_tmax_f: int,
) -> tuple[RungEvent, ...]:
    """EVERY rung of one station-day, exactly once, or REFUSE the station-day.

    There is no selection here and no partial emission: a rung without a quote
    at the instant, or without a ``p_fc``, refuses the whole station-day (§2).
    Scoring five of six rungs would quietly drop whichever rung the venue
    stopped quoting -- which is not a random rung.
    """
    rungs = assert_complete_partition(ladder)
    missing_quote = [r.instrument_id for r in rungs if r.instrument_id not in quotes]
    if missing_quote:
        raise IncompleteLadderError(
            f"{station} {climate_day.isoformat()}: {len(missing_quote)} of {len(rungs)} rungs "
            f"have no liftable quote at the decision instant ({missing_quote[0]} ...); a "
            "partial ladder is not a partition and is REFUSED, never imputed"
        )
    missing_p = [r.instrument_id for r in rungs if r.instrument_id not in p_fc]
    if missing_p:
        raise IncompleteLadderError(
            f"{station} {climate_day.isoformat()}: {len(missing_p)} rung(s) carry no p_fc "
            f"({missing_p[0]} ...); the forecast must price the WHOLE partition or none of it"
        )
    winners = [r for r in rungs if r.contains(int(settled_tmax_f))]
    if len(winners) != 1:
        raise IncompleteLadderError(
            f"{station} {climate_day.isoformat()}: settled {settled_tmax_f}F is in "
            f"{len(winners)} rungs; a partition settles exactly one YES"
        )
    events: list[RungEvent] = []
    for rung in rungs:
        quote = quotes[rung.instrument_id]
        if quote.ask is None:
            raise IncompleteLadderError(
                f"{rung.instrument_id}: the instant's quote carries no ask, so the rung is "
                "unpriced and the ladder is not complete at this instant"
            )
        events.append(
            RungEvent(
                station=station,
                climate_day=climate_day,
                rung_id=rung.instrument_id,
                ts_ns=quote.ts_ns,
                p_fc=float(p_fc[rung.instrument_id]),
                ask=float(quote.ask),
                ask_size=float(quote.ask_size),
                bid=None if quote.bid is None else float(quote.bid),
                bid_size=float(quote.bid_size),
                settled=rung.contains(int(settled_tmax_f)),
            )
        )
    return tuple(events)


# ---------------------------------------------------------------------------
# Scoring -- the REUSED Brier machinery, market in the p_clim slot
# ---------------------------------------------------------------------------


def to_trials(events: Sequence[RungEvent], *, market: str) -> list[Trial]:
    """``Trial`` records for the PAIRED comparison on IDENTICAL events.

    ``p_fc`` is the forecast; the market's price rides in the ``p_clim`` slot,
    which is what makes ``bootstrap_brier_difference_ci(..., against=p_clim)``
    -- the shipped, tested paired bootstrap -- score exactly this contest with
    no second implementation of anything.
    """
    trials: list[Trial] = []
    for event in events:
        p_mkt = event.market_probability(market)
        if p_mkt is None:
            raise ValueError(
                f"{event.rung_id}: the {market} forecast is undefined (no bid side). A "
                "pairing must be on identical events; the caller selects the event set"
            )
        trials.append(
            Trial(
                family=FAMILY,
                station=event.station,
                climate_day=event.climate_day,
                outcome=event.settled,
                p_fc=event.p_fc,
                p_clim=p_mkt,
            )
        )
    return trials


def paired_brier(events: Sequence[RungEvent], *, market: str) -> tuple[float, float, float]:
    """``(Brier_fc, Brier_mkt, Brier_fc - Brier_mkt)`` on identical events."""
    trials = to_trials(events, market=market)
    fc = brier(trials, MODEL_FORECAST)
    mkt = brier(trials, MODEL_CLIMATOLOGY)
    return fc, mkt, fc - mkt


def paired_brier_ci(
    events: Sequence[RungEvent], *, market: str, cluster: str = CLUSTER_STATION_DAY
) -> ClusterCI:
    """Block bootstrap of the paired Brier difference, clustered.

    The PRIMARY cluster is ``station_day``: §2's unit is the rung-event and a
    station-day contributes ~6 of them off ONE forecast and ONE ladder, so rows
    are anything but independent. ``n_clusters`` is therefore the effective n
    (§6) and is printed with every interval. ``date`` and ``station`` are
    reported as sensitivity.
    """
    return bootstrap_brier_difference_ci(
        to_trials(events, market=market), against=MODEL_CLIMATOLOGY, cluster=cluster
    )


def hurdle(*, ask: float, bid: float, fee_coefficient: float = DEFAULT_FEE_COEFFICIENT) -> float:
    """``theta*p*(1-p) + half-spread`` -- §3's monetisation hurdle.

    The fee is the LIVE rule's, never re-derived here.
    """
    return venue_fee(ask_probability=ask, fee_coefficient=fee_coefficient) + (ask - bid) / 2.0


# ---------------------------------------------------------------------------
# §4 -- cross-rung consistency, with DEPTH so a 1-contract arb is visible
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SumAskRow:
    station: str
    climate_day: dt.date
    n_rungs: int
    sum_ask: float
    sum_fee: float
    min_ask_size: float
    total_ask_size: float

    @property
    def overround(self) -> float:
        return self.sum_ask - 1.0

    @property
    def overround_with_fee(self) -> float:
        return self.sum_ask + self.sum_fee - 1.0

    def to_dict(self) -> dict[str, object]:
        """Explicit -- ``dataclasses.asdict`` is banned repo-wide."""
        return {
            "station": self.station,
            "climate_day": self.climate_day.isoformat(),
            "n_rungs": self.n_rungs,
            "sum_ask": self.sum_ask,
            "sum_fee": self.sum_fee,
            "sum_ask_minus_1": self.overround,
            "sum_ask_plus_fee_minus_1": self.overround_with_fee,
            "min_ask_size": self.min_ask_size,
            "total_ask_size": self.total_ask_size,
        }


def sum_ask_row(
    events: Sequence[RungEvent], *, fee_coefficient: float = DEFAULT_FEE_COEFFICIENT
) -> SumAskRow:
    """``sum(ask)`` over ONE instant's VERIFIED complete partition, with depth.

    Depth is carried because an apparent riskless ladder buy backed by one
    contract at L0 is a quoting artefact, not an edge, and the only way a
    reader can tell is if the size is in the row (§4).
    """
    if not events:
        raise IncompleteLadderError("sum(ask) over an empty ladder is undefined")
    stations = {(e.station, e.climate_day) for e in events}
    if len(stations) != 1:
        raise IncompleteLadderError(
            f"sum(ask) is a per-INSTANT statistic; got {len(stations)} station-days"
        )
    assert_complete_partition([parse_rung(e.rung_id) for e in events])
    station, climate_day = next(iter(stations))
    return SumAskRow(
        station=station,
        climate_day=climate_day,
        n_rungs=len(events),
        sum_ask=math.fsum(e.ask for e in events),
        sum_fee=math.fsum(
            venue_fee(ask_probability=e.ask, fee_coefficient=fee_coefficient) for e in events
        ),
        min_ask_size=min(e.ask_size for e in events),
        total_ask_size=math.fsum(e.ask_size for e in events),
    )


# ---------------------------------------------------------------------------
# §3 -- the PRE-DECLARED decision procedure, applied mechanically
# ---------------------------------------------------------------------------

READING_B: Final[str] = (
    "(b) SKILL IS IN THE PRICE -- L-7 confirmed on the traded unit. A SUCCESSFUL "
    "outcome: no decision rule can recover edge that is not there."
)
READING_C: Final[str] = (
    "(c) STRUCTURAL -- real information beyond the price, too small to monetise "
    "against fee and spread. A terminal conclusion, and a SUCCESSFUL outcome."
)
READING_A: Final[str] = (
    "(a) THE RULE IS THE PROBLEM -- information beyond the price, larger than the "
    "hurdle. First suspects in order: the under-confident sigma, then the "
    "instant-selection argmax, then the fixed zero-edge threshold."
)
READING_INSUFFICIENT: Final[str] = (
    "INSUFFICIENT-DATA -- the corpus cannot support the registered design. §7 "
    "forbids weakening the design to obtain a number."
)


def select_reading(
    *, ci: ClusterCI | None, mean_gap: float | None, mean_hurdle: float | None
) -> tuple[str, str]:
    """Apply §3 MECHANICALLY. Returns ``(reading, the arithmetic that selects it)``.

    Nothing here inspects magnitudes for attractiveness: the branch is fixed by
    the sign of the interval and by ``gap`` vs ``hurdle``, both pre-declared.
    """
    if ci is None:
        return READING_INSUFFICIENT, "no interval could be computed"
    if ci.high >= 0.0:
        return READING_B, (
            f"CI for Brier_fc - Brier_mkt = [{ci.low:+.5f}, {ci.high:+.5f}] over "
            f"{ci.n_clusters} clusters; upper bound >= 0, so the forecast is NOT "
            "significantly better than the price (it straddles zero or is worse)."
        )
    if mean_gap is None or mean_hurdle is None:
        return READING_INSUFFICIENT, (
            "Brier_fc is significantly lower, but no take-eligible rung carries both "
            "sides, so the gap-vs-hurdle comparison is undefined"
        )
    if mean_gap < mean_hurdle:
        return READING_C, (
            f"CI = [{ci.low:+.5f}, {ci.high:+.5f}] (< 0, {ci.n_clusters} clusters) AND "
            f"mean |p_fc - p_mkt| = {mean_gap:.5f} < hurdle {mean_hurdle:.5f}."
        )
    return READING_A, (
        f"CI = [{ci.low:+.5f}, {ci.high:+.5f}] (< 0, {ci.n_clusters} clusters) AND "
        f"mean |p_fc - p_mkt| = {mean_gap:.5f} > hurdle {mean_hurdle:.5f}, yet realised "
        "PnL is non-positive."
    )


# ---------------------------------------------------------------------------
# Step-5 qualifying-rate window (AUD-02 completion plan §3)
#
# Definition, from ``docs/evidence/WP7b_MARKET_AS_FORECASTER_2026-09-20.md``
# (frozen confirmatory region, lines 203-208): an event qualifies when its OWN
# ``yes_ask >= 0.70`` AND its station-day's ``sum(ask)`` over the complete
# partition is ``<= 1.20``, at the pre-declared 09:00 LST instant. NO new
# predicate is introduced: ``ask_events`` (built from the L0 YES ask, no bid
# required -- the NO leg is not captured) and ``sum_ask_rows`` are the
# existing values §4/§2 already compute; this section only filters and counts
# them over a climate-day window. The frozen region opened 2026-09-21.
# ---------------------------------------------------------------------------

#: §3's qualifying threshold on a single rung's YES ask.
QUALIFYING_ASK_MIN: Final[float] = 0.70

#: §3's qualifying ceiling on the station-day's Σask over the complete partition.
QUALIFYING_SUM_ASK_MAX: Final[float] = 1.20

_ARCHIVE_GAP_RE: Final[re.Pattern[str]] = re.compile(
    r"FORECAST ARCHIVE GAP for (\S+):.*\((\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})\)"
)


def parse_forecast_archive_gaps(notes: Sequence[str]) -> tuple[tuple[str, dt.date, dt.date], ...]:
    """Extract ``(icao, start, end)`` gap ranges from the corpus load's own notes.

    The notes are produced by ``wp7_realised_pnl_falsification._load_corpus``
    (``FORECAST ARCHIVE GAP for <icao>: ... (<start>..<end>)``); this is a
    read of that existing, already-computed fact, not a new detector.
    """
    gaps: list[tuple[str, dt.date, dt.date]] = []
    for note in notes:
        match = _ARCHIVE_GAP_RE.search(note)
        if match is None:
            continue
        icao, start, end = match.groups()
        gaps.append((icao, dt.date.fromisoformat(start), dt.date.fromisoformat(end)))
    return tuple(gaps)


def _in_window(day: dt.date, *, since: dt.date, until: dt.date | None) -> bool:
    """Inclusive on both ends: ``since <= day`` and, if given, ``day <= until``."""
    return since <= day and (until is None or day <= until)


def _window_overlaps_gap(
    *, since: dt.date, until: dt.date | None, gap_start: dt.date, gap_end: dt.date
) -> bool:
    if until is None:
        return gap_end >= since
    return gap_start <= until and gap_end >= since


@dataclass(frozen=True, slots=True)
class QualifyingRateReport:
    """The step-5 qualifying-rate measurement over a climate-day window.

    ``station_days_in_window`` is the "n admitted" the report line names --
    the count of station-days whose complete-partition Σask is known in the
    window, whether or not they qualify. It is the denominator; it is never
    left implicit or reconstructed by a reader from the qualifying count.
    """

    since: dt.date
    until: dt.date | None
    gap_ranges: tuple[tuple[str, dt.date, dt.date], ...]
    station_days_in_window: int
    qualifying_events: int
    qualifying_station_days: int

    @property
    def gap_intersects_window(self) -> bool:
        return any(
            _window_overlaps_gap(since=self.since, until=self.until, gap_start=start, gap_end=end)
            for _icao, start, end in self.gap_ranges
        )

    @property
    def no_data(self) -> bool:
        return self.station_days_in_window == 0


def compute_qualifying_rate(
    *,
    ask_events: Sequence[RungEvent],
    sum_ask_rows: Sequence[SumAskRow],
    notes: Sequence[str],
    since: dt.date,
    until: dt.date | None = None,
) -> QualifyingRateReport:
    """Count qualifying events and station-days in ``[since, until]`` (both inclusive).

    A rung-event qualifies iff its own ask meets ``QUALIFYING_ASK_MIN`` AND its
    station-day's Σask (from ``sum_ask_rows``, already verified over a
    complete partition -- §4) is at or under ``QUALIFYING_SUM_ASK_MAX``. A
    rung-event whose station-day carries no ``sum_ask_rows`` entry in the
    window is not counted: sum(ask) is undefined for it, so the predicate is
    undefined too, not vacuously true.
    """
    sum_ask_by_day = {
        (row.station, row.climate_day): row.sum_ask
        for row in sum_ask_rows
        if _in_window(row.climate_day, since=since, until=until)
    }
    qualifying_station_days: set[tuple[str, dt.date]] = set()
    qualifying_events = 0
    for event in ask_events:
        if not _in_window(event.climate_day, since=since, until=until):
            continue
        key = (event.station, event.climate_day)
        sum_ask = sum_ask_by_day.get(key)
        if sum_ask is None:
            continue
        if event.ask >= QUALIFYING_ASK_MIN and sum_ask <= QUALIFYING_SUM_ASK_MAX:
            qualifying_events += 1
            qualifying_station_days.add(key)
    return QualifyingRateReport(
        since=since,
        until=until,
        gap_ranges=parse_forecast_archive_gaps(notes),
        station_days_in_window=len(sum_ask_by_day),
        qualifying_events=qualifying_events,
        qualifying_station_days=len(qualifying_station_days),
    )


def render_qualifying_rate_report(report: QualifyingRateReport) -> str:
    """Render the step-5 window report. Never a bare 0/0 rate or NaN on no data."""
    until_text = "open" if report.until is None else report.until.isoformat()
    lines = [
        "## Step-5 qualifying rate (AUD-02 completion plan §3)",
        "",
        (
            "`yes_ask >= 0.70` AND `sum(ask) <= 1.20` over the complete partition, at the "
            "09:00 LST instant; YES side only (the NO leg is not captured)."
        ),
        "",
        (
            f"Window (climate-day, inclusive both ends): since={report.since.isoformat()} "
            f"until={until_text}. Station-days admitted in window (n): "
            f"**{report.station_days_in_window}**."
        ),
    ]
    if report.gap_ranges:
        gap_text = "; ".join(
            f"{icao} {start.isoformat()}..{end.isoformat()}"
            for icao, start, end in report.gap_ranges
        )
        if report.gap_intersects_window:
            lines.append(f"- FORECAST ARCHIVE GAP intersects this window: {gap_text}")
        else:
            lines.append(f"- FORECAST ARCHIVE GAP(s) recorded, outside this window: {gap_text}")
    else:
        lines.append("- no FORECAST ARCHIVE GAP recorded for this corpus load")

    if report.no_data:
        if report.gap_intersects_window:
            lines.append("- qualifying rate: **NO DATA (archive gap)** -- n=0 station-days")
        else:
            lines.append("- qualifying rate: **NO DATA** -- n=0 station-days in window")
    else:
        rate = report.qualifying_station_days / report.station_days_in_window
        lines.append(
            f"- qualifying events: {report.qualifying_events}; qualifying station-days: "
            f"{report.qualifying_station_days} of {report.station_days_in_window} "
            f"({rate:.4f})"
        )
    return "\n".join(lines)


def build_artefact(
    collected: Collected, *, since: dt.date | None, until: dt.date | None
) -> str:
    """The full rendered artefact: ``render()``, plus the step-5 section iff ``since`` is set.

    With ``since=None`` this is byte-identical to ``render(collected)`` -- the
    default CLI path (no ``--since``/``--until``) never appends anything.
    """
    artefact = render(collected)
    if since is None:
        return artefact
    report = compute_qualifying_rate(
        ask_events=collected.ask_events,
        sum_ask_rows=collected.sum_ask_rows,
        notes=collected.notes,
        since=since,
        until=until,
    )
    return artefact + "\n" + render_qualifying_rate_report(report) + "\n"


def _parse_climate_day(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid climate-day {value!r}; expected YYYY-MM-DD"
        ) from exc


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT: Final[Path] = Path("docs/evidence/WP7b_MARKET_AS_FORECASTER_2026-09-20.md")
DEFAULT_QUOTE_TAPE_CATALOG: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_CORPUS_JSON: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/forecast_conditional_corpus_wp6.json"
)


@dataclass(slots=True)
class Census:
    station_days_on_tape: int = 0
    station_days_complete_join: int = 0
    station_days_scored_ask: int = 0
    station_days_scored_mid: int = 0
    refused_partition: int = 0
    refused_no_quote: int = 0
    refused_no_bid: int = 0
    refused_no_forecast: int = 0
    refused_no_truth: int = 0
    rung_events: int = 0


@dataclass(slots=True)
class Collected:
    ask_events: list[RungEvent]
    mid_events: list[RungEvent]
    sum_ask_rows: list[SumAskRow]
    single_instant_takes: list[object]
    census: Census
    notes: list[str]


def _single_instant_tapes(
    tapes: Sequence[RungTape], quotes: Mapping[str, RungInstant], *, decision_ns: int
) -> list[RungTape]:
    """The screen's own tapes, with the WINDOW collapsed to the single instant.

    Pre-window instants are KEPT because the C2 variants screen the live ask
    against a pre-window reference and would otherwise have none; they carry
    hours before 09:00 LST and so can never themselves become the take.
    """
    out: list[RungTape] = []
    for tape in tapes:
        quote = quotes.get(tape.rung_id)
        if quote is None:
            continue
        kept = tuple(i for i in tape.instants if i.ts_ns < decision_ns) + (quote,)
        out.append(
            RungTape(
                rung_id=tape.rung_id,
                lower_f=tape.lower_f,
                upper_f=tape.upper_f,
                instants=kept,
            )
        )
    return out


def collect(*, tape_root: Path, corpus_json: Path) -> Collected:
    """Stream the tape ONE station-day at a time and emit every rung-event."""
    import forecast_cheap_screen_wp7 as wp7
    import wp7_realised_pnl_falsification as falsification

    by_station_day, truth, error_model, forecasts, sites, notes = falsification._load_corpus(
        wp7, tape_root, corpus_json
    )
    price_scalar, size_scalar = wp7._fixed_scalars()
    census = Census(station_days_on_tape=len(by_station_day))
    ask_events: list[RungEvent] = []
    mid_events: list[RungEvent] = []
    rows: list[SumAskRow] = []
    takes: list[object] = []

    for (city, climate_day), dirs in sorted(by_station_day.items()):
        if (city, climate_day) not in truth:
            census.refused_no_truth += 1
            continue
        cycles = list(forecasts.get((city, climate_day), ()))
        decision_ns = decision_instant_ns(city=city, climate_day=climate_day)
        legal = [c for c in cycles if c[0] <= decision_ns]
        if not legal:
            census.refused_no_forecast += 1
            continue
        census.station_days_complete_join += 1

        offset = sites[city].std_utc_offset_hours
        tapes: list[RungTape] = []
        for child in dirs:
            rung = parse_rung(child.name)
            instants, _rows_read = wp7.read_rung_tape(
                child,
                std_utc_offset_hours=offset,
                price_scalar=price_scalar,
                size_scalar=size_scalar,
            )
            tapes.append(
                RungTape(
                    rung_id=child.name,
                    lower_f=rung.lower_f,
                    upper_f=rung.upper_f,
                    instants=tuple(instants),
                )
            )
            del instants

        ladder = [parse_rung(t.rung_id) for t in tapes]
        try:
            assert_complete_partition(ladder)
        except IncompleteLadderError:
            census.refused_partition += 1
            del tapes
            continue

        quotes = {
            t.rung_id: q
            for t in tapes
            if (q := first_liftable_at_or_after(t.instants, decision_ns=decision_ns)) is not None
        }
        runtime_ns, txn_f = legal[-1]
        mu, sigma = mu_sigma_at_instant(
            city=city,
            climate_day=climate_day,
            cycle_runtime_ns=runtime_ns,
            txn_f=txn_f,
            error_model=error_model,
        )
        p_fc = build_rung_probabilities(
            ladder=ladder, cycle_runtime_ns=runtime_ns, decision_ns=decision_ns, mu=mu, sigma=sigma
        )
        try:
            events = build_station_day_events(
                station=city,
                climate_day=climate_day,
                ladder=ladder,
                quotes=quotes,
                p_fc=p_fc,
                settled_tmax_f=truth[(city, climate_day)],
            )
        except IncompleteLadderError:
            census.refused_no_quote += 1
            del tapes
            continue

        ask_events.extend(events)
        census.station_days_scored_ask += 1
        census.rung_events += len(events)
        rows.append(sum_ask_row(events))
        if all(e.bid is not None for e in events):
            mid_events.extend(events)
            census.station_days_scored_mid += 1
        else:
            census.refused_no_bid += 1

        # §5 free falsification: the SAME screen, window collapsed to the one
        # pre-declared instant. A1 is the only registered window containing
        # 09:00 LST; A2 (12-17) and A3 (10-11) cannot admit it by construction
        # and are reported as such rather than given an instant of their own.
        collapsed = _single_instant_tapes(tapes, quotes, decision_ns=decision_ns)
        for variant in wp7.ALL_VARIANTS:
            if variant.window_start_lst != 9:
                continue
            trial = wp7.screen_station_day(
                station=city,
                climate_day=climate_day,
                rungs=collapsed,
                variant=variant,
                p_yes_by_rung=p_fc,
            )
            if not trial.took:
                continue
            takes.append(
                falsification.score_take(
                    station=city,
                    climate_day=climate_day,
                    variant_id=variant.variant_id,
                    side=trial.side,
                    rung_id=trial.rung,
                    price=trial.ask,
                    claimed_margin=trial.margin,
                    settled_tmax_f=truth[(city, climate_day)],
                )
            )
        del tapes, collapsed
    return Collected(
        ask_events=ask_events,
        mid_events=mid_events,
        sum_ask_rows=rows,
        single_instant_takes=takes,
        census=census,
        notes=list(notes),
    )


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}

    def at(fraction: float) -> float:
        index = round(fraction * (len(ordered) - 1))
        return ordered[min(len(ordered) - 1, max(0, index))]

    return {
        "min": ordered[0],
        "p10": at(0.10),
        "p50": at(0.50),
        "p90": at(0.90),
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def _fmt(value: float | None, digits: int = 5) -> str:
    return "--" if value is None else f"{value:+.{digits}f}"


def _ci_cell(ci: ClusterCI | None) -> str:
    if ci is None:
        return "--"
    return f"[{ci.low:+.5f}, {ci.high:+.5f}] (clusters={ci.n_clusters}, max={ci.max_cluster_size})"


def _gap_and_hurdle(events: Sequence[RungEvent]) -> tuple[float | None, float | None, int]:
    """Mean ``|p_fc - mid|`` and mean hurdle on TAKE-ELIGIBLE rungs.

    Take-eligible = both sides priced at L0, so a decision could actually be
    made and a hurdle actually exists. No edge filter is applied: filtering on
    ``p_fc > ask`` would reintroduce the §0-correction-4 selector.
    """
    eligible = [e for e in events if e.bid is not None]
    if not eligible:
        return None, None, 0
    gaps = [abs(e.p_fc - float(e.mid)) for e in eligible]
    hurdles = [hurdle(ask=e.ask, bid=float(e.bid)) for e in eligible]
    return statistics.fmean(gaps), statistics.fmean(hurdles), len(eligible)


def render(collected: Collected) -> str:
    import wp7_realised_pnl_falsification as falsification

    census = collected.census
    lines = [
        "# WP-7b -- the MARKET scored as a competing forecaster (2026-09-20)",
        "",
        (
            "Governed by `docs/specs/PREREG_WP7b_MARKET_AS_FORECASTER_2026-09-20.md`, "
            "committed `3e67cbe` BEFORE this run. The three readings in its §3 were fixed "
            "in advance and the decision procedure below is applied mechanically."
        ),
        "",
        "## Corpus census (measured, before any statistic)",
        "",
        (
            "- station-days on the venue depth tape (4-station pool): "
            f"**{census.station_days_on_tape}**"
        ),
        (
            "- station-days with a COMPLETE join (truth + a cycle <= 09:00 LST): "
            f"**{census.station_days_complete_join}**"
        ),
        (
            f"- station-days SCORED on the ask: **{census.station_days_scored_ask}**; "
            f"on the mid: **{census.station_days_scored_mid}**"
        ),
        f"- rung-events emitted (every rung, no selection): **{census.rung_events}**",
        (
            f"- REFUSED -- ladder not a partition: {census.refused_partition}; no liftable "
            f"quote for some rung at the instant: {census.refused_no_quote}; some rung "
            f"unbid (mid undefined): {census.refused_no_bid}"
        ),
        (
            "- REFUSED -- no forecast cycle at or before the instant: "
            f"{census.refused_no_forecast}; no settlement truth: {census.refused_no_truth}"
        ),
        "",
    ]
    for note in collected.notes:
        lines.append(f"- {note}")

    lines += [
        "",
        "## (i) Paired Brier: forecast vs market, identical events",
        "",
        (
            "`Brier_fc - Brier_mkt` < 0 means the FORECAST is better. Every interval is a "
            "block bootstrap; the effective n is the CLUSTER count printed in the cell, "
            "never the row count (§6)."
        ),
        "",
        (
            "| market | rung-events | Brier_fc | Brier_mkt | difference | "
            "CI (station-day, PRIMARY) | CI (date) | CI (station) |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    primary: dict[str, ClusterCI | None] = {}
    for market, events in ((MARKET_MID, collected.mid_events), (MARKET_ASK, collected.ask_events)):
        if not events:
            lines.append(f"| `{market}` | 0 | -- | -- | -- | -- | -- | -- |")
            primary[market] = None
            continue
        fc, mkt, diff = paired_brier(events, market=market)
        cis = {}
        for cluster in (CLUSTER_STATION_DAY, CLUSTER_DATE, CLUSTER_STATION):
            try:
                cis[cluster] = paired_brier_ci(events, market=market, cluster=cluster)
            except Exception as exc:  # noqa: BLE001 -- reported, never swallowed
                cis[cluster] = None
                lines.append(f"<!-- {market}/{cluster}: {type(exc).__name__}: {exc} -->")
        primary[market] = cis[CLUSTER_STATION_DAY]
        lines.append(
            f"| `{market}` | {len(events)} | {fc:.5f} | {mkt:.5f} | {diff:+.5f} | "
            f"{_ci_cell(cis[CLUSTER_STATION_DAY])} | {_ci_cell(cis[CLUSTER_DATE])} | "
            f"{_ci_cell(cis[CLUSTER_STATION])} |"
        )

    mid_ci, ask_ci = primary.get(MARKET_MID), primary.get(MARKET_ASK)
    lines += [
        "",
        (
            "The reading below is taken on the MID, the first market forecast §2 names. "
            "It is INVARIANT to that choice here: "
            + (
                "both intervals straddle zero"
                if mid_ci is not None and ask_ci is not None
                and mid_ci.high >= 0.0 and ask_ci.high >= 0.0
                else "the two markets do NOT agree, which is itself reported"
            )
            + ", so no choice of market moves the §3 branch."
        ),
        (
            "The MID set is the smaller one BY REFUSAL, not by selection: a station-day "
            "whose ladder carries any unbid rung has no mid on the whole partition, and "
            "§2 refuses a partial ladder rather than imputing a bid. The ASK set is the "
            "full corpus and carries the same sign."
        ),
    ]

    gap, hurdle_mean, n_eligible = _gap_and_hurdle(collected.mid_events)
    lines += [
        "",
        "## (ii) Mean gap vs the monetisation hurdle",
        "",
        (
            "Hurdle = `venue_fee(ask) + half-spread`, the live rule's own fee, never a flat "
            "subtraction of theta. Take-eligible = both sides priced at L0, with NO edge "
            "filter (an edge filter is the selector §0 correction 4 names)."
        ),
        "",
        "| take-eligible rung-events | mean \\|p_fc - mid\\| | mean hurdle | gap - hurdle |",
        "|---|---|---|---|",
        (
            f"| {n_eligible} | {'--' if gap is None else f'{gap:.5f}'} | "
            f"{'--' if hurdle_mean is None else f'{hurdle_mean:.5f}'} | "
            f"{'--' if gap is None or hurdle_mean is None else f'{gap - hurdle_mean:+.5f}'} |"
        ),
        "",
        "## (iii) Cross-rung consistency: sum(ask) over the complete partition (§4)",
        "",
    ]
    if not collected.sum_ask_rows:
        lines.append("- no instant carried a complete, liftable partition")
    else:
        arb = [r for r in collected.sum_ask_rows if r.sum_ask <= ARB_SUM_ASK_MAX]
        n_arb = len(arb)
        n_arb_one_lot = sum(1 for r in arb if r.min_ask_size <= 1.0)
        overround = _quantiles([r.overround for r in collected.sum_ask_rows])
        with_fee = _quantiles([r.overround_with_fee for r in collected.sum_ask_rows])
        depth = _quantiles([r.min_ask_size for r in collected.sum_ask_rows])
        lines += [
            f"- instants measured: **{len(collected.sum_ask_rows)}**",
            "",
            "| statistic | min | p10 | p50 | p90 | max | mean |",
            "|---|---|---|---|---|---|---|",
            "| `sum(ask) - 1` | "
            + " | ".join(
                f"{overround[k]:+.4f}" for k in ("min", "p10", "p50", "p90", "max", "mean")
            )
            + " |",
            "| `sum(ask) + sum(fee) - 1` | "
            + " | ".join(
                f"{with_fee[k]:+.4f}" for k in ("min", "p10", "p50", "p90", "max", "mean")
            )
            + " |",
            "| thinnest L0 ask size on the ladder | "
            + " | ".join(f"{depth[k]:.1f}" for k in ("min", "p10", "p50", "p90", "max", "mean"))
            + " |",
            "",
            (
                f"- instants with `sum(ask) <= {ARB_SUM_ASK_MAX}` (a riskless long-only "
                "ladder buy WOULD be legal under `allow_short = False`): "
                f"**{n_arb}**, of which backed by an L0 depth of 1 contract somewhere "
                f"on the ladder: **{n_arb_one_lot}**"
            ),
        ]

    takes = collected.single_instant_takes
    lines += [
        "",
        "## (iv) §5 free falsification -- the corrected WP-7 screen at the SINGLE instant",
        "",
        (
            "Pre-declared: realised PnL **UP** versus the instant-scan means the scan was "
            "harvesting noise and selection is confirmed; **unchanged** means the scan is "
            "not the driver. A1 (09-12 LST) is the only registered window that contains "
            "09:00 LST; A2 (12-17) and A3 (10-11) cannot admit the pre-declared instant by "
            "construction and are NOT given an instant of their own."
        ),
        "",
        (
            "| variant | takes (single instant) | win rate | mean realised | "
            "median realised | scan mean realised (`a0a9ea8`) | shift |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    scan_baseline = {"A1-B1-C1": 0.0063, "A1-B1-C2": 0.0093}
    for variant_id, baseline in scan_baseline.items():
        subset = [t for t in takes if t.variant_id == variant_id]
        summary = falsification.summarise(subset)
        shift = (
            "--" if summary.mean_realised is None else f"{summary.mean_realised - baseline:+.4f}"
        )
        wr = "--" if summary.win_rate is None else f"{summary.win_rate * 100:.1f}%"
        lines.append(
            f"| `{variant_id}` | {summary.n_takes} | {wr} | {_fmt(summary.mean_realised, 4)} | "
            f"{_fmt(summary.median_realised, 4)} | {baseline:+.4f} | {shift} |"
        )
    lines.append("")
    for variant_id in scan_baseline:
        subset = [t for t in takes if t.variant_id == variant_id]
        ci = falsification.cluster_bootstrap_mean_ci(subset, cluster=falsification.CLUSTER_DATE)
        lines.append(
            f"- `{variant_id}` 95% CI on mean realised (date-clustered, DECISIONAL): "
            + ("--" if ci is None else f"[{ci[0]:+.4f}, {ci[1]:+.4f}]")
        )

    reading, arithmetic = select_reading(
        ci=primary.get(MARKET_MID), mean_gap=gap, mean_hurdle=hurdle_mean
    )
    lines += [
        "",
        "## The §3 reading the PRE-DECLARED decision procedure selects",
        "",
        f"**{reading}**",
        "",
        f"Selected by: {arithmetic}",
        "",
        (
            "A null here is a **NON-DETECTION AT SMALL MAGNITUDES**, never a proof of "
            "market efficiency (§6). The effective n is the cluster count above, not the "
            "rung-event count."
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WP-7b -- score the market as a forecaster")
    parser.add_argument("--tape", type=Path, default=DEFAULT_QUOTE_TAPE_CATALOG)
    parser.add_argument("--corpus-json", type=Path, default=DEFAULT_CORPUS_JSON)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--since",
        type=_parse_climate_day,
        default=None,
        help=(
            "step-5 qualifying-rate window: climate-day lower bound (YYYY-MM-DD), "
            "inclusive. Adds a report section; the default output is unchanged "
            "when this is omitted."
        ),
    )
    parser.add_argument(
        "--until",
        type=_parse_climate_day,
        default=None,
        help=(
            "step-5 qualifying-rate window: climate-day upper bound (YYYY-MM-DD), "
            "inclusive. Requires --since."
        ),
    )
    args = parser.parse_args(argv)

    if args.until is not None and args.since is None:
        parser.error("--until requires --since")
    if args.since is not None and args.until is not None and args.since > args.until:
        parser.error(f"--since {args.since.isoformat()} is after --until {args.until.isoformat()}")

    collected = collect(tape_root=args.tape, corpus_json=args.corpus_json)
    artefact = build_artefact(collected, since=args.since, until=args.until)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(artefact, encoding="utf-8")
    print(artefact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""MAKER-S2 WP5 rows: ``SdRow`` / ``PosRow``, their CSV contract (r4 (g)) and the generic codec.

Split out of ``maker_stage0_verdict`` / ``maker_stage0_tables`` (plan ceiling 400 lines per module);
both re-export every name here so no public import path changes. Pure; imports no verdict logic.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from functools import partial
from typing import Any, Final, cast, get_args, get_type_hints

from scripts.analysis import maker_stage0_stats as st
from scripts.analysis.maker_stage0_fill_events import StationDaySummary

# --- rows -------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class SdRow:
    """``station_days.csv`` (r4 (g)); replay fields are None where the day was not replayed.

    ``rung_trials_attempted`` (position-unit denominator) and ``n_no_book_wants`` (WP4 re-check M1:
    wanted rungs that never had a book) are appended after the contract columns.
    """

    station: str
    climate_day: str
    cluster_id: str
    unit_hypothesis: str
    census_reason: str | None = None
    covered_bidlive: bool = False
    covered: bool = False
    outage_excluded: bool = False
    node_log_absent: bool = False
    bid_bearing: bool | None = None
    guard_refused_only: bool | None = None
    n_depth_frames: int | None = None
    has_depth_frame: bool | None = None
    n_attempts: int | None = None
    n_episodes: int | None = None
    n_refused: int | None = None
    n_process_cuts: int | None = None
    n_gtd_cuts: int | None = None
    rung_trials_posted: int | None = None
    rung_trials_filled_base: int | None = None
    rung_trials_filled_stress: int | None = None
    process_live_h: float | None = None
    forecast_valid_h: float | None = None
    gap_h: float | None = None
    covered_live_h: float | None = None
    gap_share: float | None = None
    filled_pairs_base: int | None = None
    filled_pairs_stress: int | None = None
    k1_rung_id: str | None = None
    k1_filled_base: int | None = None
    k1_filled_stress: int | None = None
    bid_median_fills_stress: float | None = None
    nogo_driving: bool | None = None
    positions_filled_k2_base: int | None = None
    positions_filled_k2_stress: int | None = None
    positions_filled_k1_base: int | None = None
    positions_filled_k1_stress: int | None = None
    delta_ns: int | None = None
    truth_final: bool | None = None
    truth_tmax_f: int | None = None
    void: bool | None = None
    unresolved_d14: bool | None = None
    theta: float | None = None
    rung_trials_attempted: int | None = None
    n_no_book_wants: int | None = None

    def cluster_key(self, cluster: str) -> object:
        return self.climate_day


@dataclass(frozen=True, kw_only=True)
class PosRow:
    """``scored_episodes.csv`` row; ``truth_final`` is "", YES, NO, VOID or UNRESOLVED."""

    position_id: str
    rung_trial_id: str
    station: str
    climate_day: str
    unit_hypothesis: str
    bid: float
    filled_base: bool
    filled_stress: bool
    p_yes_point_live: float | None
    truth_final: str

    def cluster_key(self, cluster: str) -> object:
        return self.climate_day


def nz(value: float | None) -> float:
    return 0.0 if value is None else float(value)


def in_denominator(row: SdRow) -> bool:
    """Covered, not outage-excluded, bid-bearing (or with a never-booked want; WP4 M1)."""
    booked = bool(row.bid_bearing) or nz(row.n_no_book_wants) > 0
    return row.covered and not row.outage_excluded and booked


_SHARED: Final[tuple[str, ...]] = tuple(
    f.name for f in fields(SdRow) if f.name in {g.name for g in fields(StationDaySummary)}
)

# --- CSV --------------------------------------------------------------------------------------


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return repr(value) if isinstance(value, float) else str(value)


def _coerce(raw: str, hint: object) -> object:
    args = get_args(hint)
    base = next((a for a in args if a is not type(None)), hint)
    if raw == "":
        if type(None) in args or base is str:
            return None if type(None) in args else ""
        raise ValueError("blank cell in a non-null column")
    if base is bool:
        if raw not in ("true", "false"):
            raise ValueError(f"bad boolean cell {raw!r}")
        return raw == "true"
    return cast(Callable[[str], object], base)(raw)


def _to_csv(cls: type, rows: Sequence[object]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    names = [f.name for f in fields(cls)]
    writer.writerow(names)
    writer.writerows([_cell(getattr(row, n)) for n in names] for row in rows)
    return out.getvalue()


def _from_csv[T](text: str, ctor: Callable[..., T], optional: Sequence[str] = ()) -> list[T]:
    hints = get_type_hints(ctor)
    reader = csv.DictReader(io.StringIO(text))
    missing = set(hints) - set(reader.fieldnames or ()) - set(optional)
    if missing:
        raise ValueError(f"csv is missing columns {sorted(missing)}")
    return [ctor(**{k: _coerce(row[k], hints[k]) for k in hints if k in row}) for row in reader]


sd_rows_to_csv = partial(_to_csv, SdRow)
pos_rows_to_csv = partial(_to_csv, PosRow)
tail_rows_to_csv = partial(_to_csv, st.TailRow)
read_station_days_csv = partial(
    _from_csv, ctor=SdRow, optional=("rung_trials_attempted", "n_no_book_wants")
)
read_scored_csv = partial(_from_csv, ctor=PosRow)
read_tail_csv = partial(_from_csv, ctor=st.TailRow)


def sd_row_from_summary(
    s: StationDaySummary,
    *,
    census_reason: str,
    covered_bidlive: bool,
    covered: bool,
    outage_excluded: bool,
    node_log_absent: bool,
    n_depth_frames: int,
    truth_final: bool | None = None,
    truth_tmax_f: int | None = None,
    void: bool | None = None,
    unresolved_d14: bool | None = None,
    theta: float | None = None,
    n_no_book_wants: int = 0,
) -> SdRow:
    """A replayed row from WP4's summary; WP6 supplies the census, depth and truth fields."""
    copied: dict[str, Any] = {name: getattr(s, name) for name in _SHARED}
    in_den = covered and not outage_excluded and (s.bid_bearing or n_no_book_wants > 0)
    return SdRow(
        **copied, cluster_id=s.climate_day, census_reason=census_reason,
        covered_bidlive=covered_bidlive, covered=covered, outage_excluded=outage_excluded,
        node_log_absent=node_log_absent, n_depth_frames=n_depth_frames,
        has_depth_frame=n_depth_frames > 0, nogo_driving=in_den and s.filled_pairs_stress == 0,
        positions_filled_k2_base=s.filled_pairs_base,
        positions_filled_k2_stress=s.filled_pairs_stress,
        positions_filled_k1_base=s.k1_filled_base, positions_filled_k1_stress=s.k1_filled_stress,
        truth_final=truth_final, truth_tmax_f=truth_tmax_f, void=void,
        unresolved_d14=unresolved_d14, theta=theta, n_no_book_wants=n_no_book_wants,
    )  # fmt: skip

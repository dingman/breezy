"""MAKER-S2 WP6: scoring and the tail table (the ONLY module that loads truth).

Plan r3 WP6 flow steps (2)-(3), r4 delta (f)(g)(i)6. Nothing here runs before every station-day is
simulated: the driver calls ``score`` once, after its simulation loop. The simulation loop's import
closure (``station_loop``, ``runio``, ``events_build``, ``adapter``, ``modes``) cannot reach this
module, and the truth loader is named nowhere else. The Markdown lives in ``maker_stage0_render``.
"""

from __future__ import annotations

import datetime as dt
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.maker_tape_census import CensusedDay
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.quantile_density import Rung
from scripts.analysis import maker_stage0_verdict as vd
from scripts.analysis.maker_stage0_frozen import (
    FrozenDateSet,
    truth_keys,
    verify_set_matches_rule,
)
from scripts.analysis.maker_stage0_inputs import TruthTable, load_truth, write_text_atomic
from scripts.analysis.maker_stage0_modes import write_manifest
from scripts.analysis.maker_stage0_pno import AbstainReason, classify_p_no, release_instants
from scripts.analysis.maker_stage0_pno_store import PNoStore
from scripts.analysis.maker_stage0_preflight_v2 import is_v2_block
from scripts.analysis.maker_stage0_run_types import Pre, RunConfig, RunSummary
from scripts.analysis.maker_stage0_runio import PositionSeed
from scripts.analysis.maker_stage0_stats import TAIL_EDGES, TailRow
from scripts.analysis.maker_stage0_tables import tail_rows_to_csv

__all__ = [
    "Scored",
    "day_truth",
    "load_tail_truth",
    "load_truth",
    "no_final_days",
    "run_tail",
    "score",
    "tail_bands",
    "tail_rows_for",
    "truth_token",
    "write_text_atomic",
]

OUTCOME_YES: Final[str] = "YES"
TAIL_P_YES_MAX: Final[float] = TAIL_EDGES[-1]
TAIL_BAND_FLOOR_F: Final[int] = 10
TAIL_BAND_CEIL_F: Final[int] = 125


@dataclass(frozen=True, slots=True)
class Scored:
    sd_rows: list[vd.SdRow]
    pos_rows: list[vd.PosRow]
    truth: TruthTable


def day_truth(tmax_f: int | None) -> dict[str, object]:
    """The station-day truth fields; the ONE place that decides whether a FINAL row exists.

    A day with no FINAL row is blank (excluded from 6.9 and counted) at ANY age. ``UNRESOLVED``
    (spec 6.5, past D+14 = loss) and ``VOID`` need venue resolution state that the pinned truth CSV
    does not carry, so no row is ever scored either here (see ``DEVIATIONS`` in the driver and the
    report's disclosures).
    """
    return {
        "truth_final": tmax_f is not None, "truth_tmax_f": tmax_f, "void": False,
        "unresolved_d14": False,
    }  # fmt: skip


def truth_token(rung_id: str, tmax_f: int | None) -> str:
    """ "" (no FINAL row), or YES / NO from the rung's inclusive band (from ``day_truth``)."""
    if not day_truth(tmax_f)["truth_final"]:
        return vd.NO_FINAL
    facts = bucket_facts_from_instrument_id(rung_id)
    if facts is None:
        raise ValueError(f"{rung_id} has no rung facts; cannot settle it")
    assert tmax_f is not None
    return OUTCOME_YES if facts.contains(tmax_f) else vd.OUTCOME_NO


def _truth_row(row: vd.SdRow, truth: TruthTable) -> vd.SdRow:
    day = dt.date.fromisoformat(row.climate_day)
    return replace(row, **day_truth(truth.finals.get((row.station, day))))  # type: ignore[arg-type]


def _pos_row(seed: PositionSeed, truth: TruthTable) -> vd.PosRow:
    day = dt.date.fromisoformat(seed.climate_day)
    token = truth_token(seed.rung_id, truth.finals.get((seed.station, day)))
    return vd.PosRow(
        position_id=f"{seed.station}|{seed.climate_day}|{seed.unit_hypothesis}|{seed.rung_id}",
        rung_trial_id=seed.rung_id,
        station=seed.station,
        climate_day=seed.climate_day,
        unit_hypothesis=seed.unit_hypothesis,
        bid=seed.bid,
        filled_base=seed.filled_base,
        filled_stress=seed.filled_stress,
        p_yes_point_live=seed.p_yes_point_live,
        truth_final=token,
    )


def score(
    *,
    sd_rows: Sequence[vd.SdRow],
    seeds: Iterable[PositionSeed],
    census: Iterable[CensusedDay],
    frozen: FrozenDateSet,
    truth_csv: Path,
    cross_check: Path,
    run_dir: Path,
) -> Scored:
    """Load FINAL truth for the replayed station-days; called once, post-simulation.

    v1 reads the replayed ``sd_rows`` keys. v2 deliberately reads the whole ``truth_keys`` grid
    (stations x frozen dates): the exact key set the pre-claim agreement already proved, so a
    post-claim ``FrozenSetRefused``/``TruthConflict`` from a key-set mismatch cannot arise. The
    per-row truth tokens are unchanged (each ``sd_rows`` row still looks up its own key).
    """
    if is_v2_block(frozen):
        keys = truth_keys(frozen.stations, frozen.dates)
    else:
        keys = {(r.station, dt.date.fromisoformat(r.climate_day)) for r in sd_rows}
    truth = load_truth(
        truth_csv, cross_check, run_dir, keys=keys, expected_csv_sha256=frozen.truth_csv_sha256
    )
    verify_set_matches_rule(frozen, census, truth)
    return Scored(
        [_truth_row(r, truth) for r in sd_rows],
        [_pos_row(s, truth) for s in seeds],
        truth,
    )


def load_tail_truth(
    truth_csv: Path,
    cross_check: Path,
    scratch: Path,
    expected_sha: str,
    keys: set[tuple[str, dt.date]],
) -> TruthTable:
    """FINAL truth for the tail days (report-only); the copy goes to ``scratch``."""
    return load_truth(truth_csv, cross_check, scratch, keys=keys, expected_csv_sha256=expected_sha)


def tail_rows_for(
    store: PNoStore,
    station: str,
    day: dt.date,
    tmax_f: int | None,
    bands: Mapping[str, tuple[int, int]],
) -> list[TailRow]:
    """Every inclusive 2 F band with p_YES < 0.06 for each day-D vector (report-only)."""
    if tmax_f is None:
        return []
    rows: list[TailRow] = []
    for release in release_instants(store, station, day, stress="none"):
        served = classify_p_no(store, station, day, release + 1, stress="none")
        if isinstance(served, AbstainReason):
            continue
        cycle = dt.datetime.fromtimestamp(served.vector.cycle_runtime_ns // 10**9, tz=dt.UTC)
        label = f"{cycle.hour:02d}Z"
        for rung_id, p_yes in sorted(served.p_yes_point_live.items()):
            lo, hi = bands[rung_id]
            if p_yes < TAIL_P_YES_MAX:
                rows.append(
                    TailRow(station, day.isoformat(), label, p_yes, int(lo <= tmax_f <= hi))
                )
    return rows


def no_final_days(rows: Iterable[vd.SdRow]) -> int:
    """Distinct COVERED station-days with no FINAL row (excluded from 6.9, disclosed)."""
    return len({(r.station, r.climate_day) for r in rows if r.covered and not r.truth_final})


# --- tail-only ----------------------------------------------------------------------------------


def tail_bands(parity: int) -> dict[str, tuple[int, int]]:
    """Every inclusive 2 F band on the station's parity (no open tails)."""
    first = TAIL_BAND_FLOOR_F + ((parity - TAIL_BAND_FLOOR_F) % 2)
    return {f"{lo}-{lo + 1}": (lo, lo + 1) for lo in range(first, TAIL_BAND_CEIL_F, 2)}


def run_tail(
    cfg: RunConfig, pre: Pre, calibration: LiveCalibration, tail_range: tuple[dt.date, dt.date]
) -> RunSummary:
    """Report-only: the tail-reliability CSV, nothing else (no fill, rate, episode or label)."""
    cfg.out_dir.mkdir(parents=True)
    first, last = tail_range
    days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    parity = dict(cfg.parity or ())
    truth = load_tail_truth(
        cfg.need("truth"),
        cfg.truth_cross_check,
        cfg.work_root / "tail_truth",
        pre.frozen.truth_csv_sha256,
        {(s, d) for s in parity for d in days},
    )
    rows: list[TailRow] = []
    for station, p in sorted(parity.items()):
        bands = tail_bands(p)
        rungs = [Rung(rung_id=i, lo=lo, hi=hi) for i, (lo, hi) in bands.items()]
        for day in days:
            store = PNoStore.from_root(
                cfg.nbp_root,
                stations=[station],
                days=[day],
                calibration=calibration,
                ladders={(station, day): rungs},
            )
            rows += tail_rows_for(store, station, day, truth.finals.get((station, day)), bands)
    shutil.rmtree(cfg.work_root, ignore_errors=True)
    write_text_atomic(cfg.out_dir / "tail_reliability.csv", tail_rows_to_csv(rows))
    write_manifest(cfg, pre, "tail-only", ["preflight", "tail"], parity)
    return RunSummary(cfg.out_dir, None, pre.code_sha, "tail-only")

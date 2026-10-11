"""The TE-1 world: the 34-fill ledger of 2026-10-11 rebuilt on real writers (L-42, L-55).

25 FQ fills (20 inside ``pm_us_crh_fq_v1``'s window, 5 straddling its terminal day) and 9 legacy CRH
fills (7 with a frozen ``ScoredTrial``, 2 residual). Fills are written with ``seed_fills``; every
latch key is written by the real ``PersistentQuantileLadderLatch`` / ``TrialDayLatch`` writers, and
the 7 scored trials by the real ``write_scored_trials``. Nothing here imports the exec client (the
x1 pin names ``tests/support/aut2_fixtures.py``) and nothing touches the network or the host.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestError,
    load_family_manifest,
)
from breezy.persistence.scored_trial_store import write_scored_trials
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.settlement.trial_scorer import ScoredTrial
from breezy.strategy.current_rung_hold.trial_day_latch import (
    TrialDayRecord,
    open_trial_day_latch,
    trial_id_for,
)
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
    PersistentQuantileLadderLatch,
)
from tests.contract.test_catalog_nws_records import make_climate_day
from tests.support.aut2_fixtures import DurableFillRecord, durable_fill, seed_fills

__all__ = [
    "FAMILIES_DIR",
    "FQ_POST_TERMINAL_IDS",
    "MapSettlements",
    "World",
    "build_world",
    "day_start_ns",
    "load_repo_manifests",
    "slug",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILIES_DIR = REPO_ROOT / "deploy" / "families"
VENUE = "polymarket_us"
_NS = 1_000_000_000
_FQ_KEY_PREFIX = FORECAST_QUANTILE_TRIAL_KEY_PREFIX
#: The five fills of climate day 2026-10-06 sent on 2026-10-05 (R11): ``client_order_id`` set.
FQ_POST_TERMINAL_IDS = frozenset(f"O-FQ-1006-{i}" for i in range(5))


def day_start_ns(day: str, hour: int = 0) -> int:
    d = dt.date.fromisoformat(day)
    return int(dt.datetime(d.year, d.month, d.day, hour, tzinfo=dt.UTC).timestamp()) * _NS


def slug(station: str, day: str, lower: int, *, no: bool = False) -> str:
    leg = "^no" if no else ""
    return f"tc-temp-{station.lower()}high-{day}-gte{lower}lt{lower + 1}f{leg}.POLYMARKET_US"


def load_repo_manifests() -> tuple[FamilyManifest, ...]:
    out: list[FamilyManifest] = []
    for path in sorted(FAMILIES_DIR.glob("*.json")):
        with contextlib.suppress(FamilyManifestError):  # a non-manifest json is skipped, as in prod
            out.append(load_family_manifest(path, allow_draft=True))
    return tuple(out)


class MapSettlements:
    """A settlement source over a fixed ``{(station, ISO day): tmax}`` map; missing -> no record."""

    def __init__(self, tmax: dict[tuple[str, str], int]) -> None:
        self._tmax = tmax

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        value = self._tmax.get((station, climate_day.isoformat()))
        if value is None:
            return None
        return make_climate_day(station=station, climate_day=climate_day, tmax_f=value)


@dataclass(frozen=True)
class World:
    exec_db: Path
    data_root: Path
    scored_dir: Path
    fills: tuple[DurableFillRecord, ...]
    scored: dict[str, ScoredTrial]
    settlements: MapSettlements
    now_ns: int
    post_terminal_ids: frozenset[str]


# (station, day, lower, no, scored?, fee_reconciled) of the nine legacy fills.
_LEGACY: tuple[tuple[str, str, int, bool, bool, bool], ...] = (
    ("SFO", "2026-09-11", 73, False, False, False),  # v2 station-day key, RESIDUAL
    ("MIA", "2026-09-13", 92, False, False, False),  # cont station-day key, RESIDUAL
    ("MDW", "2026-09-15", 85, False, True, True),
    ("MIA", "2026-09-15", 93, True, True, True),
    ("MDW", "2026-09-15", 84, False, True, True),
    ("SFO", "2026-09-15", 73, False, True, True),
    ("MIA", "2026-09-21", 88, True, True, True),
    ("SFO", "2026-09-21", 68, False, True, True),
    ("MDW", "2026-09-22", 62, True, True, True),
)
_FQ_STATIONS = ("LAX", "MDW", "MIA", "SFO")
_FQ_DAYS = ("2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05")
_POST_TERMINAL = (("SFO", 81), ("MDW", 69), ("MDW", 70), ("LAX", 91), ("SFO", 83))


def _legacy_prefix(day: str) -> str:
    if day < "2026-09-12":
        return "current_rung_hold/trial/"
    return "continuous_rung_hold/trial/"


def _fq_specs() -> list[tuple[str, str, str, int]]:
    """``(client_order_id, station, climate_day, lower)``: 20 inside the window, 5 straddling."""
    specs: list[tuple[str, str, str, int]] = []
    for d, day in enumerate(_FQ_DAYS):
        for k in range(5):
            station = _FQ_STATIONS[k % 4]
            specs.append((f"O-FQ-{day[-2:]}-{k}", station, day, 60 + 5 * k + d))
    for i, (station, lower) in enumerate(_POST_TERMINAL):
        specs.append((f"O-FQ-1006-{i}", station, "2026-10-06", lower))
    return specs


def _write_fq_latches(store_path: Path, specs: list[tuple[str, str, str, int]]) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent:
        trial = open_trial_day_latch(
            intent, key_prefix=_FQ_KEY_PREFIX, family_id="pm_us_fq_te1_fixture"
        )
        latch = PersistentQuantileLadderLatch(trial)
        for _coid, station, day, lower in specs:
            latch.latch(
                station=station,
                climate_day=dt.date.fromisoformat(day),
                rung_id=f"{lower}_{lower + 1}",
                side="yes",
            )


def _write_legacy_latches(
    store_path: Path, pairs: list[tuple[DurableFillRecord, bool, str, str]]
) -> None:
    """``(fill, station_day_key, station, day)`` -> one real ``TrialDayLatch`` record each."""
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent:
        for fill, station_day_key, station, day in pairs:
            trial = open_trial_day_latch(
                intent, key_prefix=_legacy_prefix(day), family_id="pm_us_crh_te1_fixture"
            )
            record = TrialDayRecord(
                latched_at_ns=fill.ts_event,
                instrument_id=fill.instrument_id,
                ask=Decimal("0.40"),
                reason="taken",
                venue_order_id=None if station_day_key else fill.venue_order_id,
            )
            trial.consume_if_absent(
                station,
                day,
                record,
                key_instrument_id=None if station_day_key else fill.instrument_id,
            )


def _scored_trial(fill: Any, station: str, day: str, key: str, tmax: int) -> ScoredTrial:
    no = "^no" in fill.instrument_id
    lower = int(fill.instrument_id.split("-gte")[1].split("lt")[0])
    contains = lower <= tmax <= lower + 1
    held = (not contains) if no else contains
    cost = fill.cumulative_cost
    fee = fill.cumulative_fee
    pnl = (Decimal(1) if held else Decimal(0)) - cost - fee
    return ScoredTrial(
        trial_id=key,
        station=station,
        climate_day=day,
        instrument_id=fill.instrument_id,
        settlement_tmax_f=tmax,
        held=held,
        pnl=pnl,
        revision_seq=1,
        raw_sha256="c" * 64,
        scored_at_ns=fill.ts_event + 40 * 3_600 * _NS,
        score_seq=1,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=cost,
        fill_px=cost,
        fee=fee,
    )


def build_world(tmp_path: Path, *, with_post_terminal: bool = True) -> World:
    """Seed the 34-fill ledger (or the 29 without the five straddle fills) under ``tmp_path``."""
    exec_db = tmp_path / "exec.sqlite"
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    scored_dir = tmp_path / "scored_trials"
    tmax: dict[tuple[str, str], int] = {}
    fills: list[DurableFillRecord] = []
    fq_specs = _fq_specs()
    if not with_post_terminal:
        fq_specs = [s for s in fq_specs if s[0] not in FQ_POST_TERMINAL_IDS]
    for n, (coid, station, day, lower) in enumerate(fq_specs):
        ts = day_start_ns(day, 14) if day != "2026-10-06" else day_start_ns("2026-10-05", 17)
        fills.append(
            durable_fill(
                venue_order_id=f"vo-{coid}",
                client_order_id=coid,
                instrument_id=slug(station, day, lower),
                cost=Decimal("0.20"),
                fee=Decimal("0.01"),
                ts_event=ts + n,
                trade_id=f"T-{coid}",
            )
        )
        tmax[(station, day)] = lower + 1 if n % 5 == 0 else lower + 6
    legacy_pairs: list[tuple[DurableFillRecord, bool, str, str]] = []
    scored: dict[str, ScoredTrial] = {}
    scored_rows: list[ScoredTrial] = []
    for n, (station, day, lower, no, is_scored, reconciled) in enumerate(_LEGACY):
        fill = durable_fill(
            venue_order_id=f"vo-L{n}",
            client_order_id=f"O-L{n}",
            instrument_id=slug(station, day, lower, no=no),
            cost=Decimal("0.30"),
            fee=Decimal("0.02"),
            fee_reconciled=reconciled,
            ts_event=day_start_ns(day, 15) + n,
            trade_id=f"T-L{n}",
        )
        fills.append(fill)
        station_day_key = n < 2
        legacy_pairs.append((fill, station_day_key, station, day))
        tmax[(station, day)] = lower + 1
        if is_scored:
            key = trial_id_for(_legacy_prefix(day), station, day, fill.instrument_id)
            row = _scored_trial(fill, station, day, key, lower + 1)
            scored[key] = row
            scored_rows.append(row)
    seed_fills(exec_db, fills)
    _write_fq_latches(exec_db, fq_specs)
    _write_legacy_latches(exec_db, legacy_pairs)
    write_scored_trials(
        scored_dir / "pm_us_crh_cont", scored_rows, now_ns=day_start_ns("2026-10-01")
    )
    now = day_start_ns("2026-10-11", 14) + 15 * 60 * _NS
    return World(
        exec_db=exec_db,
        data_root=data_root,
        scored_dir=scored_dir,
        fills=tuple(sorted(fills, key=lambda f: f.ts_event)),
        scored=scored,
        settlements=MapSettlements(tmax),
        now_ns=now,
        post_terminal_ids=FQ_POST_TERMINAL_IDS if with_post_terminal else frozenset(),
    )

"""The TE-1 world: the REAL 34-fill ledger of 2026-10-11 rebuilt on real writers (L-42, L-55).

25 FQ fills (20 inside ``pm_us_crh_fq_v1``'s window, 5 straddling its terminal day) and 9 legacy CRH
fills (7 with a frozen ``ScoredTrial``, 2 residual). Instruments, prices, fees, timestamps and the
settled highs are the venue's own (``tests/support/te1_real_ledger.py``, constants copied from a
read-only look at the exec store). Fills are written with ``seed_fills``; every latch key is
written by the real ``PersistentQuantileLadderLatch`` / ``TrialDayLatch`` writers, and the 7 scored
trials by the real ``write_scored_trials``. Nothing here imports the exec client (the x1 pin names
``tests/support/aut2_fixtures.py``) and nothing touches the network or the host.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import re
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
from tests.support.te1_real_ledger import FQ_RUNG_IDS, REAL_FILLS, REAL_TMAX

__all__ = [
    "FAMILIES_DIR",
    "FQ_POST_TERMINAL_IDS",
    "FQ_WIN_COIDS",
    "LEGACY_COIDS",
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
_SLUG_RE = re.compile(r"^tc-temp-(?P<station>[a-z]+)high-(?P<day>\d{4}-\d{2}-\d{2})-")
_N_LEGACY = 9
#: The nine legacy CRH fills' client order ids, in fill order (the first two are the RESIDUALS).
LEGACY_COIDS: tuple[str, ...] = tuple(row[0] for row in REAL_FILLS[:_N_LEGACY])
_LAST_WINDOW_DAY = "2026-10-05"  # pm_us_crh_fq_v1's terminal climate day (R11)


def _station_day(instrument_id: str) -> tuple[str, str]:
    m = _SLUG_RE.match(instrument_id)
    assert m is not None, instrument_id
    return m["station"].upper(), m["day"]


#: The five fills of climate day 2026-10-06 sent on 2026-10-05 (R11): real client order ids.
FQ_POST_TERMINAL_IDS = frozenset(
    row[0] for row in REAL_FILLS[_N_LEGACY:] if _station_day(row[1])[1] > _LAST_WINDOW_DAY
)
#: The two FQ winners (MIA 10-03 gte86lt87 tmax 87 +0.88; MIA 10-05 gte89lt90 tmax 90 +0.50).
FQ_WIN_COIDS = (
    "O-20261003-021031-L001-MIA-1",
    "O-20261004-165019-L001-MIA-1",
)


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


def _legacy_prefix(day: str) -> str:
    if day < "2026-09-12":
        return "current_rung_hold/trial/"
    return "continuous_rung_hold/trial/"


def _write_fq_latches(store_path: Path, fills: list[DurableFillRecord]) -> None:
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent:
        trial = open_trial_day_latch(
            intent, key_prefix=_FQ_KEY_PREFIX, family_id="pm_us_fq_te1_fixture"
        )
        latch = PersistentQuantileLadderLatch(trial)
        for fill in fills:
            station, day = _station_day(fill.instrument_id)
            latch.latch(
                station=station,
                climate_day=dt.date.fromisoformat(day),
                rung_id=FQ_RUNG_IDS[fill.client_order_id],
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


def _real_fill(row: tuple[str, str, str, str, int, bool]) -> DurableFillRecord:
    coid, instrument_id, cost, fee, ts_event, reconciled = row
    return durable_fill(
        venue_order_id=f"vo-{coid}",
        client_order_id=coid,
        instrument_id=instrument_id,
        cost=Decimal(cost),
        fee=Decimal(fee),
        fee_reconciled=reconciled,
        ts_event=ts_event,
        trade_id=f"T-{coid}",
    )


def build_world(tmp_path: Path, *, with_post_terminal: bool = True) -> World:
    """Seed the 34-fill ledger (or the 29 without the five straddle fills) under ``tmp_path``."""
    exec_db = tmp_path / "exec.sqlite"
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    scored_dir = tmp_path / "scored_trials"
    legacy = [_real_fill(r) for r in REAL_FILLS[:_N_LEGACY]]
    fq = [
        _real_fill(r)
        for r in REAL_FILLS[_N_LEGACY:]
        if with_post_terminal or r[0] not in FQ_POST_TERMINAL_IDS
    ]
    legacy_pairs: list[tuple[DurableFillRecord, bool, str, str]] = []
    scored: dict[str, ScoredTrial] = {}
    scored_rows: list[ScoredTrial] = []
    for n, fill in enumerate(legacy):
        station, day = _station_day(fill.instrument_id)
        station_day_key = n < 2  # SFO 09-11 and MIA 09-13: no instrument in the latch key
        legacy_pairs.append((fill, station_day_key, station, day))
        if not station_day_key:  # the seven frozen ScoredTrials; the two residuals have none
            key = trial_id_for(_legacy_prefix(day), station, day, fill.instrument_id)
            row = _scored_trial(fill, station, day, key, REAL_TMAX[(station, day)])
            scored[key] = row
            scored_rows.append(row)
    fills = [*legacy, *fq]
    seed_fills(exec_db, fills)
    _write_fq_latches(exec_db, fq)
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
        settlements=MapSettlements(dict(REAL_TMAX)),
        now_ns=now,
        post_terminal_ids=FQ_POST_TERMINAL_IDS if with_post_terminal else frozenset(),
    )

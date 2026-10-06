"""The pre-holdout ask pool and the imported live take rule for the FQ F5 N Monte-Carlo.

Split out of `fq_resume_n_mc.py`. Every take decision is made by the shipped
`forecast_quantile_ladder.decision.evaluate`; only its inputs are synthetic. Pool rows dated on or
after the sealed-holdout start (`nbp_calibration.DEFAULT_SPLITS.holdout_start`) are never kept, and
nothing here calls the holdout opener.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS
from breezy.strategy.forecast_quantile_ladder.bounds import RungBounds
from breezy.strategy.forecast_quantile_ladder.decision import (
    SidedAsk,
    Take,
    evaluate,
)
from breezy.strategy.forecast_quantile_ladder.latch import QuantileLadderLatch
from breezy.strategy.forecast_quantile_ladder.margin import (
    forecast_margin,
    hours_to_settlement,
)
from breezy.strategy.ladder_ev.config import LadderEvConfig
from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.weather_common.costs import venue_fee_prob
from scripts.analysis.fq_mc_eprocess import (
    ALPHA_KILL,
    K_SLOTS,
    MAX_LAMBDA,
    ItemBatch,
    order_takes,
)
from scripts.analysis.k1_kalshi_prior import ask_at_open

Side = Literal["yes", "no"]


#: The sealed-holdout start, from the one place the repo declares it.
HOLDOUT_START: Final[dt.date] = DEFAULT_SPLITS.holdout_start


#: Kalshi's exhaustive-bucket era (k1_kalshi_prior: 2021-22 were single thresholds).
POOL_START: Final[dt.date] = dt.date(2023, 1, 1)


_TICKER_RE: Final = re.compile(r"^([A-Z0-9]+)-(\d{2})([A-Z]{3})(\d{2})-(.+)$")


_MONTHS: Final = {
    m: i + 1
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    )
}


@dataclass(frozen=True, slots=True)
class PoolRung:
    station: str
    climate_day: dt.date
    rung_id: str
    yes_ask: float
    yes_bid: float | None
    result: bool | None = None  # settled YES? used ONLY for rho-hat / variance


@dataclass(frozen=True, slots=True)
class PoolDay:
    climate_day: dt.date
    stations: tuple[tuple[str, tuple[PoolRung, ...]], ...]


def filter_pre_holdout(rows: Sequence[PoolRung]) -> list[PoolRung]:
    """Drop every row on or after the holdout start. The guard is the repo's own split table."""
    kept = [r for r in rows if r.climate_day < HOLDOUT_START]
    for row in kept:
        if row.climate_day >= DEFAULT_SPLITS.train.start:
            assert DEFAULT_SPLITS.split_for_date(row.climate_day) != "holdout"
    return kept


def group_days(rows: Sequence[PoolRung]) -> list[PoolDay]:
    by_day: dict[dt.date, dict[str, list[PoolRung]]] = {}
    for row in filter_pre_holdout(rows):
        by_day.setdefault(row.climate_day, {}).setdefault(row.station, []).append(row)
    return [
        PoolDay(
            climate_day=day,
            stations=tuple(
                (st, tuple(sorted(rungs, key=lambda r: r.rung_id)))
                for st, rungs in sorted(by_day[day].items())
            ),
        )
        for day in sorted(by_day)
    ]


def _ticker_day(ticker: str) -> tuple[str, dt.date, str] | None:
    m = _TICKER_RE.match(ticker)
    if not m or m.group(3) not in _MONTHS:
        return None
    return (
        m.group(1),
        dt.date(2000 + int(m.group(2)), _MONTHS[m.group(3)], int(m.group(4))),
        m.group(5),
    )


def _bid_close(response: Mapping[str, Any]) -> float | None:
    candles = response.get("candlesticks")
    if not isinstance(candles, Sequence) or not candles or not isinstance(candles[0], Mapping):
        return None
    node = candles[0].get("yes_bid")
    if not isinstance(node, Mapping):
        return None
    for key in ("close", "close_dollars"):
        try:
            value = float(node[key])
        except (KeyError, TypeError, ValueError):
            continue
        return value if value > 0.01 else None  # an empty / penny bid is "no YES bid"
    return None


def _load_results(markets_dir: Path) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for path in sorted(markets_dir.glob("markets_*.json")):
        try:
            markets = json.loads(path.read_text(encoding="utf-8")).get("markets", [])
        except (OSError, ValueError):
            continue
        for market in markets:
            if isinstance(market, Mapping) and market.get("result") in ("yes", "no"):
                results[str(market.get("ticker"))] = market["result"] == "yes"
    return results


def load_pool(
    candles_path: Path, *, markets_dir: Path | None = None, start: dt.date = POOL_START
) -> list[PoolRung]:
    """Read-only. Rows dated at or after the holdout start are never kept."""
    results = _load_results(markets_dir) if markets_dir is not None else {}
    rows: list[PoolRung] = []
    with candles_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            parsed = _ticker_day(str(record.get("ticker", "")))
            response = record.get("response")
            if parsed is None or not isinstance(response, Mapping):
                continue
            station, day, rung = parsed
            if day < start or day >= HOLDOUT_START:
                continue
            ask = ask_at_open(response)
            if ask is None:
                continue
            rows.append(
                PoolRung(
                    station=station,
                    climate_day=day,
                    rung_id=rung,
                    yes_ask=float(ask.price),
                    yes_bid=_bid_close(response),
                    result=results.get(str(record["ticker"])),
                )
            )
    return filter_pre_holdout(rows)


@dataclass(frozen=True, slots=True)
class LoopConfig:
    theta: float = 0.0695  # FQ required_fee_coefficient
    slippage_floor_prob: float = 0.01  # LadderEvConfig default, one tick
    h_hours: float = 30.0  # D+1 scope: 24 <= h < 48, so the margin sits at m24
    bound_halfwidth: float = 0.03  # the bootstrap p_lower/p_upper half-width of the model view
    haircut: float = 0.01  # one tick on ask_exec (BE only; the live rule sees the raw ask)
    ask_floor: float = 0.05
    ask_ceiling: float = 0.95
    edge_excess_mean: float = 0.04  # Exp mean of the model's edge beyond cost + margin
    std_utc_offset_hours: float = -5.0
    latitude_deg: float = 40.0


@dataclass(frozen=True, slots=True)
class TakeRecord:
    station: str
    rung_id: str
    side: Side
    ask: float  # the quote the live rule saw
    be: float  # haircut ask + fee: the e-process break-even
    p_side: float  # the model's probability of the side bought
    ev_net: float


@dataclass(frozen=True, slots=True)
class DayTemplate:
    climate_day: dt.date
    takes: tuple[TakeRecord, ...]

    @property
    def n(self) -> int:
        return len(self.takes)

    @property
    def is_mixed_side(self) -> bool:
        sides: dict[str, set[str]] = {}
        for t in self.takes:
            sides.setdefault(t.station, set()).add(t.side)
        return any(len(s) > 1 for s in sides.values())


@dataclass(frozen=True, slots=True)
class _Draw:
    fav: bool
    direction: int  # +1 favours YES, -1 favours NO
    extra: float
    noise: float


ModelView = dict[tuple[str, str], _Draw]


def draw_model_view(
    day: PoolDay, *, pi_fav: float, seed: int, cfg: LoopConfig | None = None
) -> ModelView:
    """One draw per (station, rung); same seed -> same uniforms, ``fav`` monotone in pi_fav."""
    cfg = cfg or LoopConfig()
    rng = np.random.default_rng(seed)
    view: ModelView = {}
    for station, rungs in day.stations:
        for rung in rungs:
            u_fav, u_dir, u_extra, noise = (
                rng.random(),
                rng.random(),
                rng.random(),
                rng.standard_normal(),
            )
            view[(station, rung.rung_id)] = _Draw(
                fav=bool(u_fav < pi_fav),
                direction=1 if u_dir < 0.5 else -1,
                extra=-cfg.edge_excess_mean * math.log(max(u_extra, 1e-12)),
                noise=float(noise),
            )
    return view


def _no_ask(rung: PoolRung, cfg: LoopConfig) -> float | None:
    if rung.yes_bid is None:  # NO takes with an empty YES bid are ineligible (FQ-R16)
        return None
    price = round(1.0 - rung.yes_bid, 4)
    return price if cfg.ask_floor <= price <= cfg.ask_ceiling else None


def _yes_ask(rung: PoolRung, cfg: LoopConfig) -> float | None:
    return rung.yes_ask if cfg.ask_floor <= rung.yes_ask <= cfg.ask_ceiling else None


def _break_even(ask: float, cfg: LoopConfig) -> float:
    exec_ask = ask + cfg.haircut
    return exec_ask + venue_fee_prob(executable_price=min(exec_ask, 1.0), fee_coefficient=cfg.theta)


def _model_p_hat(rung: PoolRung, draw: _Draw, cfg: LoopConfig, margin: float) -> float:
    yes, no = _yes_ask(rung, cfg), _no_ask(rung, cfg)
    if draw.fav and draw.direction > 0 and yes is not None:
        fee = venue_fee_prob(executable_price=yes, fee_coefficient=cfg.theta)
        p_lower = yes + fee + cfg.slippage_floor_prob + margin + draw.extra
        return min(1.0, p_lower + cfg.bound_halfwidth)
    if draw.fav and draw.direction < 0 and no is not None:
        fee = venue_fee_prob(executable_price=no, fee_coefficient=cfg.theta)
        p_upper = 1.0 - no - fee - cfg.slippage_floor_prob - margin - draw.extra
        return max(0.0, p_upper - cfg.bound_halfwidth)
    return min(1.0, max(0.0, rung.yes_ask + 0.01 * draw.noise))


class _StubResolved:
    draws: tuple[()] = ()
    point = None


class _StubCalibration:
    """`evaluate` forwards only ``draws`` to the bounds provider, which ignores them."""

    def resolve(self, era: str, *, latitude_deg: float, climate_day: dt.date) -> _StubResolved:
        return _StubResolved()


def _vector(day: dt.date) -> ForecastQuantileVector:
    return ForecastQuantileVector(
        q10=0.0,
        q25=0.0,
        q50=0.0,
        q75=0.0,
        q90=0.0,
        mean=0.0,
        sd=1.0,
        available_at_ns=0,
        cycle_runtime_ns=0,
        climate_day=day,
        model_version="v4.0",
    )


def _now_ns(climate_day: dt.date, cfg: LoopConfig, h_hours: float) -> int:
    settle_ns = (
        hours_to_settlement(
            now_ns=0, climate_day=climate_day, std_utc_offset_hours=cfg.std_utc_offset_hours
        )
        * 3_600_000_000_000
    )
    return int(settle_ns - h_hours * 3_600_000_000_000)


def _call_evaluate(
    *,
    climate_day: dt.date,
    station: str,
    ladder: Sequence[Rung],
    rung_id: str,
    side: Side,
    ask: SidedAsk,
    p_hat: float,
    cfg: LoopConfig,
    h_hours: float,
    latch: QuantileLadderLatch,
) -> Any:
    """ONE call of the shipped take rule. The only injected piece is the bounds provider."""

    def provider(**_kw: Any) -> RungBounds:
        return RungBounds(p_hat, p_hat - cfg.bound_halfwidth, p_hat + cfg.bound_halfwidth)

    return evaluate(
        now_ns=_now_ns(climate_day, cfg, h_hours),
        std_utc_offset_hours=cfg.std_utc_offset_hours,
        permit_covers=True,
        vector=_vector(climate_day),
        station=station,
        climate_day=climate_day,
        ladder=ladder,
        rung_id=rung_id,
        side=side,
        ask=ask,
        fee_coefficient=cfg.theta,
        slippage_floor_prob=cfg.slippage_floor_prob,
        h_hours=h_hours,
        cfg=LadderEvConfig(),
        calibration=_StubCalibration(),  # type: ignore[arg-type]
        latitude_deg=cfg.latitude_deg,
        bounds_provider=provider,
        latch=latch,
    )


def _record(take: Take, ask: float, cfg: LoopConfig) -> TakeRecord:
    p_side = take.p_hat if take.side == "yes" else 1.0 - take.p_hat
    return TakeRecord(
        take.station, take.rung_id, take.side, ask, _break_even(ask, cfg), p_side, take.ev_net
    )


def replay_live_day(day: PoolDay, view: ModelView, cfg: LoopConfig) -> list[TakeRecord]:
    """One climate day through the shipped take rule, rung by rung, with its own latch."""
    margin = forecast_margin(cfg.h_hours, LadderEvConfig())
    latch = QuantileLadderLatch()
    takes: list[TakeRecord] = []
    for station, rungs in day.stations:
        ladder = tuple(Rung(r.rung_id, None, None) for r in rungs)
        for rung in rungs:
            p_hat = _model_p_hat(rung, view[(station, rung.rung_id)], cfg, margin)
            sided: tuple[tuple[Side, float | None], ...] = (
                ("yes", _yes_ask(rung, cfg)),
                ("no", _no_ask(rung, cfg)),
            )
            for side, price in sided:
                if price is None or _break_even(price, cfg) >= 1.0:
                    continue
                decision = _call_evaluate(
                    climate_day=day.climate_day,
                    station=station,
                    ladder=ladder,
                    rung_id=rung.rung_id,
                    side=side,
                    ask=SidedAsk(
                        side=side, instrument_id=f"{station}-{rung.rung_id}-{side}", price=price
                    ),
                    p_hat=p_hat,
                    cfg=cfg,
                    h_hours=cfg.h_hours,
                    latch=latch,
                )
                if isinstance(decision, Take):
                    takes.append(_record(decision, price, cfg))
    return order_takes(takes)


def build_templates(
    days: Sequence[PoolDay], *, pi_fav: float, seed: int, cfg: LoopConfig | None = None
) -> list[DayTemplate]:
    cfg = cfg or LoopConfig()
    return [
        DayTemplate(
            day.climate_day,
            tuple(
                replay_live_day(
                    day, draw_model_view(day, pi_fav=pi_fav, seed=seed + i, cfg=cfg), cfg
                )
            ),
        )
        for i, day in enumerate(days)
    ]


def calibrate_take_rate(
    days: Sequence[PoolDay],
    *,
    target_rate: float,
    seed: int,
    cfg: LoopConfig | None = None,
    iterations: int = 14,
) -> tuple[float, list[DayTemplate]]:
    """Bisect pi_fav so the mean takes per climate day hits ``target_rate`` (fixed draws)."""
    lo, hi = 0.0, 1.0
    best = build_templates(days, pi_fav=hi, seed=seed, cfg=cfg)
    if float(np.mean([t.n for t in best])) <= target_rate:
        return hi, best
    best_pi = hi
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        templates = build_templates(days, pi_fav=mid, seed=seed, cfg=cfg)
        rate = float(np.mean([t.n for t in templates]))
        best, best_pi = templates, mid
        lo, hi = (mid, hi) if rate < target_rate else (lo, mid)
        if abs(rate - target_rate) < 0.02 * max(target_rate, 0.1):
            break
    return best_pi, best


@dataclass(frozen=True, slots=True)
class Design:
    delta_h: float
    m_cap: int = 2
    x_max: float = 4.0
    earliest_look_n: int = 20
    lam_max: float = MAX_LAMBDA
    mu_max: float = MAX_LAMBDA
    alpha_kill: float = ALPHA_KILL


@dataclass(slots=True)
class _TemplateArrays:
    n: np.ndarray
    be: np.ndarray
    ask: np.ndarray
    p: np.ndarray
    st: np.ndarray
    valid: np.ndarray
    mixed: np.ndarray
    stations: list[str] = field(default_factory=list)


def _arrays(templates: Sequence[DayTemplate]) -> _TemplateArrays:
    stations = sorted({t.station for tpl in templates for t in tpl.takes}) or ["-"]
    index = {s: i for i, s in enumerate(stations)}
    count = len(templates)
    out = _TemplateArrays(
        n=np.array([t.n for t in templates], dtype=np.int64),
        be=np.full((count, K_SLOTS), 0.5),
        ask=np.full((count, K_SLOTS), 0.5),
        p=np.full((count, K_SLOTS), 0.5),
        st=np.zeros((count, K_SLOTS), dtype=np.int64),
        valid=np.zeros((count, K_SLOTS), dtype=bool),
        mixed=np.array([t.is_mixed_side for t in templates], dtype=bool),
        stations=stations,
    )
    for i, tpl in enumerate(templates):
        for j, take in enumerate(tpl.takes[:K_SLOTS]):
            out.be[i, j], out.ask[i, j], out.p[i, j] = take.be, take.ask, take.p_side
            out.st[i, j], out.valid[i, j] = index[take.station], True
    return out


def simulate_pooled(
    templates: Sequence[DayTemplate],
    design: Design,
    *,
    reps: int,
    days: int,
    seed: int,
    null: bool,
    mixed_only: bool = False,
) -> ItemBatch:
    """Resample pooled climate-day templates; outcomes comonotone within a station-day."""
    pick = [i for i, t in enumerate(templates) if (t.is_mixed_side or not mixed_only)]
    if not pick:
        raise ValueError("no template qualifies (mixed_only with no mixed-side day in the pool)")
    arr = _arrays(templates)
    rng = np.random.default_rng(seed)
    idx = np.asarray(pick)[rng.integers(0, len(pick), (reps, days))]
    u = rng.random((reps, days, len(arr.stations)))
    st = arr.st[idx]
    uu = np.take_along_axis(u, st, axis=2)
    be = arr.be[idx]
    q = be if null else np.minimum(1.0, be + design.delta_h)
    return ItemBatch(
        be=be,
        ask=arr.ask[idx],
        p=arr.p[idx],
        h=(uu < q).astype(float),
        valid=arr.valid[idx],
        n_d=arr.n[idx],
        st=st,
        mixed=arr.mixed[idx],
    )

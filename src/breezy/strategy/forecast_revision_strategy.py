"""Forecast Revision / Momentum Strategy — standalone NautilusTrader module

Trades unabsorbed NWS forecast revisions versus the prediction-market book.

Standalone file: drop into a NautilusTrader project. No other weather_trading
modules are required. Version-sensitive NautilusTrader calls live in the
NT adapter section of this file.

Required external data
----------------------
* Quote ticks (bid/ask) on the temperature contract.
* NWSForecastUpdate custom data with original issuance timestamps.
* TemperatureContract metadata mapping instrument_id -> station/date/outcome.

Example
-------
from datetime import date
from forecast_revision_strategy import (
    ForecastRevisionConfig,
    ForecastRevisionStrategy,
    TemperatureContract,
    ContractKind,
    WeatherContractRegistry,
    WeatherProbabilityEngine,
)

contract = TemperatureContract(
    instrument_id="KORD-2026-08-28-GE90.KALSHI",
    location_id="KORD",
    station_id="KORD",
    settlement_date=date(2026, 8, 28),
    kind=ContractKind.ABOVE,
    threshold_f=90.0,
)
registry = WeatherContractRegistry([contract])
strategy = ForecastRevisionStrategy(
    ForecastRevisionConfig(instrument_ids=(contract.instrument_id,)),
    registry,
    WeatherProbabilityEngine(),
)
# engine.add_strategy(strategy)
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from math import erf, exp, log, pi, sqrt
from typing import Any, Deque, Iterable, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo


# === models.py ===
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Mapping


class SideIntent(str, Enum):
    """Desired economic exposure in a binary 0/1 contract."""

    LONG_YES = "LONG_YES"  # buy the contract (profit if outcome = 1)
    SHORT_YES = "SHORT_YES"  # sell/short the contract (profit if outcome = 0)
    FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class MarketQuote:
    """Executable top-of-book snapshot used for edge calculation.

    Prices are stored in raw venue units. Convert to implied probability with
    ``implied_prob = raw_price * price_scale`` where ``price_scale`` is 1.0
    for 0-1 markets and 0.01 for cent markets.
    """

    instrument_id: str
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    ts_event: datetime
    mid: float | None = None

    def __post_init__(self) -> None:
        if self.mid is None and self.bid is not None and self.ask is not None:
            object.__setattr__(self, "mid", 0.5 * (self.bid + self.ask))

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid

    def implied_bid(self, price_scale: float) -> float | None:
        return None if self.bid is None else self.bid * price_scale

    def implied_ask(self, price_scale: float) -> float | None:
        return None if self.ask is None else self.ask * price_scale

    def implied_mid(self, price_scale: float) -> float | None:
        if self.mid is None:
            return None
        return self.mid * price_scale


@dataclass(slots=True)
class ForecastSnapshot:
    """Latest usable NWS point forecast for one station/target-date."""

    location_id: str
    target_date: date
    published_at: datetime
    expected_high_f: float
    horizon_hours: float
    source: str = "NWS"
    nws_product: str | None = None
    raw_payload_id: str | None = None

    def is_stale(self, now: datetime, max_age_hours: float) -> bool:
        published = self.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        aware_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        age_hours = (aware_now - published).total_seconds() / 3600.0
        return age_hours > max_age_hours


@dataclass(slots=True)
class ProbabilityView:
    """Model probability for one contract at one instant."""

    contract_id: str
    model_probability: float
    mu_f: float
    sigma_f: float
    horizon_hours: float
    distribution: str
    components: Mapping[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class SignalDecision:
    """Strategy output consumed by the shared execution layer."""

    instrument_id: str
    intent: SideIntent
    model_probability: float
    market_probability: float
    edge: float
    conviction: float
    quantity: float
    reason: str
    metadata: Mapping[str, float | str | int | None] = field(default_factory=dict)


def ensure_aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def hours_until(later: datetime, now: datetime) -> float:
    return (ensure_aware(later) - ensure_aware(now)).total_seconds() / 3600.0

# === weather_events.py ===
from datetime import date, datetime, timezone
from typing import Any



def _datetime_to_ns(ts: datetime) -> int:
    ts = ensure_aware(ts)
    return int(ts.timestamp() * 1_000_000_000)


def _try_data_base() -> type:
    """Return Nautilus Data base class if installed, else a local stand-in."""
    try:
        from nautilus_trader.core.data import Data  # type: ignore

        return Data
    except Exception:  # pragma: no cover - unit/offline use

        class _Data:
            def __init__(self, ts_event: int = 0, ts_init: int = 0) -> None:
                self.ts_event = ts_event
                self.ts_init = ts_init

        return _Data


DataBase = _try_data_base()


class NWSForecastUpdate(DataBase):
    """Point-forecast issuance that would have been available at ``published_at``.

    Fields required by the task:
    * location identifier
    * forecast target date
    * forecast publication timestamp
    * expected high temperature
    * forecast horizon
    * source identifier
    """

    def __init__(
        self,
        location_id: str,
        target_date: date,
        published_at: datetime,
        expected_high_f: float,
        horizon_hours: float,
        source: str = "NWS",
        nws_product: str | None = None,
        station_id: str | None = None,
        raw_payload_id: str | None = None,
        ts_event: int | None = None,
        ts_init: int | None = None,
    ) -> None:
        published_at = ensure_aware(published_at)
        event_ns = ts_event if ts_event is not None else _datetime_to_ns(published_at)
        init_ns = ts_init if ts_init is not None else event_ns
        super().__init__(event_ns, init_ns)
        self.location_id = location_id
        self.target_date = target_date
        self.published_at = published_at
        self.expected_high_f = float(expected_high_f)
        self.horizon_hours = float(horizon_hours)
        self.source = source
        self.nws_product = nws_product
        self.station_id = station_id or location_id
        self.raw_payload_id = raw_payload_id

    def to_snapshot(self) -> ForecastSnapshot:
        return ForecastSnapshot(
            location_id=self.location_id,
            target_date=self.target_date,
            published_at=self.published_at,
            expected_high_f=self.expected_high_f,
            horizon_hours=self.horizon_hours,
            source=self.source,
            nws_product=self.nws_product,
            raw_payload_id=self.raw_payload_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "location_id": self.location_id,
            "target_date": self.target_date.isoformat(),
            "published_at": self.published_at.isoformat(),
            "expected_high_f": self.expected_high_f,
            "horizon_hours": self.horizon_hours,
            "source": self.source,
            "nws_product": self.nws_product,
            "station_id": self.station_id,
            "raw_payload_id": self.raw_payload_id,
            "ts_event": self.ts_event,
            "ts_init": self.ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "NWSForecastUpdate":
        return cls(
            location_id=values["location_id"],
            target_date=date.fromisoformat(values["target_date"]),
            published_at=datetime.fromisoformat(values["published_at"]),
            expected_high_f=float(values["expected_high_f"]),
            horizon_hours=float(values["horizon_hours"]),
            source=values.get("source", "NWS"),
            nws_product=values.get("nws_product"),
            station_id=values.get("station_id"),
            raw_payload_id=values.get("raw_payload_id"),
            ts_event=values.get("ts_event"),
            ts_init=values.get("ts_init"),
        )


class NWSObservation(DataBase):
    """Official observed daily high used only at or after settlement.

    Strategies must ignore this event for trading decisions. It exists so a
    backtest can mark contracts to the realized outcome after the settlement
    timestamp — never before.
    """

    def __init__(
        self,
        location_id: str,
        target_date: date,
        observed_high_f: float,
        observed_at: datetime,
        source: str = "NWS_CLI",
        ts_event: int | None = None,
        ts_init: int | None = None,
    ) -> None:
        observed_at = ensure_aware(observed_at)
        event_ns = ts_event if ts_event is not None else _datetime_to_ns(observed_at)
        init_ns = ts_init if ts_init is not None else event_ns
        super().__init__(event_ns, init_ns)
        self.location_id = location_id
        self.target_date = target_date
        self.observed_high_f = float(observed_high_f)
        self.observed_at = observed_at
        self.source = source


def build_forecast_update(
    *,
    location_id: str,
    target_date: date,
    published_at: datetime,
    expected_high_f: float,
    horizon_hours: float | None = None,
    settlement_datetime: datetime | None = None,
    source: str = "NWS",
    nws_product: str | None = None,
    station_id: str | None = None,
    raw_payload_id: str | None = None,
) -> NWSForecastUpdate:
    """Adapter helper: construct an event from parsed NWS product fields.

    If ``horizon_hours`` is omitted, it is inferred from ``settlement_datetime
    - published_at``. Settlement datetime should be local-station end-of-day
    converted to UTC, not the catalog ingest time.
    """
    published_at = ensure_aware(published_at)
    if horizon_hours is None:
        if settlement_datetime is None:
            raise ValueError("Provide horizon_hours or settlement_datetime")
        horizon_hours = (ensure_aware(settlement_datetime) - published_at).total_seconds() / 3600.0
    return NWSForecastUpdate(
        location_id=location_id,
        target_date=target_date,
        published_at=published_at,
        expected_high_f=expected_high_f,
        horizon_hours=max(horizon_hours, 0.0),
        source=source,
        nws_product=nws_product,
        station_id=station_id,
        raw_payload_id=raw_payload_id,
    )


def nws_forecast_data_type():
    """Return a Nautilus ``DataType`` for subscription, if the package exists."""
    try:
        from nautilus_trader.model.data import DataType  # type: ignore

        return DataType(NWSForecastUpdate)
    except Exception:  # pragma: no cover
        return NWSForecastUpdate


def nws_observation_data_type():
    try:
        from nautilus_trader.model.data import DataType  # type: ignore

        return DataType(NWSObservation)
    except Exception:  # pragma: no cover
        return NWSObservation

# === contract_metadata.py ===
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from enum import Enum
from typing import Iterable
from zoneinfo import ZoneInfo


class ContractKind(str, Enum):
    ABOVE = "ABOVE"  # YES if realized high >= threshold_f
    BELOW = "BELOW"  # YES if realized high <= threshold_f
    RANGE = "RANGE"  # YES if lo_f <= realized high <= hi_f (inclusive integers)


@dataclass(frozen=True, slots=True)
class TemperatureContract:
    """Maps a venue instrument to a weather outcome.

    ``instrument_id`` should be the NautilusTrader InstrumentId string, e.g.
    ``KORD-2026-08-28-GE90.KALSHI``.
    """

    instrument_id: str
    location_id: str
    station_id: str
    settlement_date: date
    kind: ContractKind
    threshold_f: float | None = None
    range_lo_f: float | None = None
    range_hi_f: float | None = None
    venue: str = "KALSHI"
    timezone: str = "America/Chicago"
    settlement_local_time: time = time(23, 59)
    tick_size: float = 0.01
    price_scale: float = 1.0  # 1.0 => prices already in [0, 1]
    contract_size: float = 1.0  # payout dollars per contract at YES
    event_id: str | None = None  # groups mutually exclusive buckets

    def __post_init__(self) -> None:
        if self.kind in (ContractKind.ABOVE, ContractKind.BELOW) and self.threshold_f is None:
            raise ValueError(f"{self.kind} requires threshold_f")
        if self.kind == ContractKind.RANGE:
            if self.range_lo_f is None or self.range_hi_f is None:
                raise ValueError("RANGE requires range_lo_f and range_hi_f")
            if self.range_lo_f > self.range_hi_f:
                raise ValueError("range_lo_f must be <= range_hi_f")

    @property
    def event_key(self) -> str:
        return self.event_id or f"{self.location_id}:{self.settlement_date.isoformat()}"

    def settlement_datetime_utc(self) -> datetime:
        local = datetime.combine(self.settlement_date, self.settlement_local_time, tzinfo=ZoneInfo(self.timezone))
        return local.astimezone(timezone.utc)

    def outcome_from_high(self, realized_high_f: float) -> int:
        if self.kind == ContractKind.ABOVE:
            return int(realized_high_f >= float(self.threshold_f))
        if self.kind == ContractKind.BELOW:
            return int(realized_high_f <= float(self.threshold_f))
        return int(float(self.range_lo_f) <= realized_high_f <= float(self.range_hi_f))

    def label(self) -> str:
        if self.kind == ContractKind.ABOVE:
            return f"{self.location_id} high >= {self.threshold_f:.0f}F on {self.settlement_date}"
        if self.kind == ContractKind.BELOW:
            return f"{self.location_id} high <= {self.threshold_f:.0f}F on {self.settlement_date}"
        return (
            f"{self.location_id} high in [{self.range_lo_f:.0f}, {self.range_hi_f:.0f}]F "
            f"on {self.settlement_date}"
        )


class WeatherContractRegistry:
    """Lookup contracts by instrument, event, or location."""

    def __init__(self, contracts: Iterable[TemperatureContract] | None = None) -> None:
        self._by_instrument: dict[str, TemperatureContract] = {}
        self._by_event: dict[str, list[TemperatureContract]] = {}
        if contracts:
            for contract in contracts:
                self.add(contract)

    def add(self, contract: TemperatureContract) -> None:
        self._by_instrument[contract.instrument_id] = contract
        self._by_event.setdefault(contract.event_key, []).append(contract)

    def get(self, instrument_id: str) -> TemperatureContract | None:
        return self._by_instrument.get(str(instrument_id))

    def require(self, instrument_id: str) -> TemperatureContract:
        contract = self.get(instrument_id)
        if contract is None:
            raise KeyError(f"No weather metadata for instrument {instrument_id}")
        return contract

    def event_contracts(self, event_key: str) -> list[TemperatureContract]:
        return list(self._by_event.get(event_key, []))

    def instruments(self) -> list[str]:
        return list(self._by_instrument)

    def all(self) -> list[TemperatureContract]:
        return list(self._by_instrument.values())

    def mutually_exclusive_group(self, instrument_id: str) -> list[TemperatureContract]:
        contract = self.require(instrument_id)
        group = self.event_contracts(contract.event_key)
        # Only treat RANGE buckets that partition the same event as exclusive.
        ranges = [c for c in group if c.kind == ContractKind.RANGE]
        if contract.kind == ContractKind.RANGE and ranges:
            return ranges
        # ABOVE/BELOW on the same threshold are complements, not a full partition
        # unless both exist. Return same-event same-kind siblings plus complements.
        return [c for c in group if c.location_id == contract.location_id]


def example_ord_ge90_contract() -> TemperatureContract:
    """Chicago O'Hare daily high at least 90F — used by the backtest example."""
    return TemperatureContract(
        instrument_id="KORD-2026-08-28-GE90.KALSHI",
        location_id="KORD",
        station_id="KORD",
        settlement_date=date(2026, 8, 28),
        kind=ContractKind.ABOVE,
        threshold_f=90.0,
        venue="KALSHI",
        timezone="America/Chicago",
        tick_size=0.01,
        price_scale=1.0,
        contract_size=1.0,
        event_id="KORD:2026-08-28:HIGH",
    )

# === probability.py ===
from dataclasses import dataclass, field
from datetime import date
from math import erf, exp, log, pi, sqrt
from typing import Iterable, Mapping, Sequence



def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def _student_t_cdf(x: float, df: float) -> float:
    """Regularized incomplete-beta Student-t CDF, accurate enough for trading."""
    if df <= 0:
        raise ValueError("df must be positive")
    # Symmetric identity
    if x == 0:
        return 0.5
    # For large df the t and normal coincide.
    if df > 100:
        return _norm_cdf(x)
    xx = x * x
    z = df / (df + xx)
    a = 0.5 * df
    b = 0.5
    ib = _regularized_incomplete_beta(z, a, b)
    if x > 0:
        return 1.0 - 0.5 * ib
    return 0.5 * ib


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """I_x(a, b) via continued fraction. x in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = _log_gamma(a) + _log_gamma(b) - _log_gamma(a + b)
    front = exp(a * log(x) + b * log(1.0 - x) - ln_beta) / a
    # Lentz continued fraction for the incomplete beta.
    use_complement = x > (a + 1.0) / (a + b + 2.0)
    if use_complement:
        return 1.0 - _regularized_incomplete_beta(1.0 - x, b, a)
    cf = _betacf(x, a, b)
    return front * cf


def _betacf(x: float, a: float, b: float, max_iter: int = 200, eps: float = 1e-12) -> float:
    am, bm = 1.0, 1.0
    az = 1.0
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    bz = 1.0 - qab * x / qap
    for m in range(1, max_iter + 1):
        em = float(m)
        tem = em + em
        d = em * (b - em) * x / ((qam + tem) * (a + tem))
        ap = az + d * am
        bp = bz + d * bm
        d = -(a + em) * (qab + em) * x / ((a + tem) * (qap + tem))
        app = ap + d * az
        bpp = bp + d * bz
        if bpp == 0.0:
            bpp = 1e-30
        am, bm, az, bz = ap / bpp, bp / bpp, app / bpp, 1.0
        if abs(app / bpp - az) < eps * abs(az) if False else abs(az - 1.0) < eps:
            # az converges to the continued-fraction value around 1 after rescale
            return az
        if abs(az - 1.0) < eps and m > 8:
            return az
    return az


def _log_gamma(z: float) -> float:
    """Lanczos approximation for ln Gamma(z), z > 0."""
    coeffs = (
        76.18009172947146,
        -86.50532032941677,
        24.01409824083091,
        -1.231739572450155,
        0.1208650973866179e-2,
        -0.5395239384953e-5,
    )
    x = z
    y = z
    tmp = x + 5.5
    tmp -= (x + 0.5) * log(tmp)
    ser = 1.000000000190015
    for c in coeffs:
        y += 1.0
        ser += c / y
    return -tmp + log(2.5066282746310005 * ser / x)


@dataclass(frozen=True, slots=True)
class HorizonSigmaParams:
    sigma_floor_f: float = 1.1
    sigma_per_sqrt_hour_f: float = 0.55
    min_horizon_hours: float = 0.25
    max_sigma_f: float = 14.0


@dataclass(slots=True)
class ForecastErrorModel:
    """Configurable error model used by every strategy.

    ``bias_by_key`` maps ``f"{location}|{month}|{horizon_bin}"`` or coarser
    fallbacks to a mean error (realized - forecast) in Fahrenheit.
    ``sigma_by_key`` overrides the parametric sigma when sample size is large.
    ``sample_size_by_key`` gates whether an override is used.
    """

    distribution: str = "gaussian"  # "gaussian" | "student_t"
    student_t_df: float = 7.0
    sigma_params: HorizonSigmaParams = field(default_factory=HorizonSigmaParams)
    bias_by_key: dict[str, float] = field(default_factory=dict)
    sigma_by_key: dict[str, float] = field(default_factory=dict)
    sample_size_by_key: dict[str, int] = field(default_factory=dict)
    min_samples_for_local: int = 40
    p_floor: float = 0.01
    continuity_correction_f: float = 0.5
    horizon_bins: tuple[float, ...] = (3, 6, 12, 24, 36, 48, 72, 120, 168, 240)

    def horizon_bin(self, horizon_hours: float) -> float:
        for edge in self.horizon_bins:
            if horizon_hours <= edge:
                return edge
        return self.horizon_bins[-1]

    def lookup_keys(self, location_id: str, target_date: date, horizon_hours: float) -> list[str]:
        month = target_date.month
        hbin = int(self.horizon_bin(horizon_hours))
        return [
            f"{location_id}|{month}|{hbin}",
            f"{location_id}|*|{hbin}",
            f"*|{month}|{hbin}",
            f"*|*|{hbin}",
            "*",
        ]

    def _first_override(self, table: Mapping[str, float], keys: Sequence[str]) -> float | None:
        for key in keys:
            if key in table:
                n = self.sample_size_by_key.get(key, self.min_samples_for_local)
                if key == "*" or n >= self.min_samples_for_local:
                    return table[key]
        return None

    def bias(self, location_id: str, target_date: date, horizon_hours: float) -> float:
        keys = self.lookup_keys(location_id, target_date, horizon_hours)
        found = self._first_override(self.bias_by_key, keys)
        return 0.0 if found is None else found

    def sigma(self, location_id: str, target_date: date, horizon_hours: float) -> float:
        keys = self.lookup_keys(location_id, target_date, horizon_hours)
        found = self._first_override(self.sigma_by_key, keys)
        if found is not None:
            return max(found, 0.25)
        p = self.sigma_params
        h = max(horizon_hours, p.min_horizon_hours)
        raw = sqrt(p.sigma_floor_f**2 + (p.sigma_per_sqrt_hour_f * sqrt(h)) ** 2)
        return min(max(raw, 0.25), p.max_sigma_f)

    def cdf(self, x: float, mu: float, sigma: float) -> float:
        z = (x - mu) / sigma
        if self.distribution == "student_t":
            return _student_t_cdf(z, self.student_t_df)
        return _norm_cdf(z)

    def pdf(self, x: float, mu: float, sigma: float) -> float:
        z = (x - mu) / sigma
        if self.distribution == "student_t":
            # t pdf scaled
            df = self.student_t_df
            c = exp(_log_gamma((df + 1.0) / 2.0) - _log_gamma(df / 2.0))
            return (c / (sqrt(df * pi) * sigma)) * (1.0 + z * z / df) ** (-0.5 * (df + 1.0))
        return _norm_pdf(z) / sigma


class WeatherProbabilityEngine:
    def __init__(self, error_model: ForecastErrorModel | None = None) -> None:
        self.error_model = error_model or ForecastErrorModel()

    def mu_sigma(
        self,
        expected_high_f: float,
        horizon_hours: float,
        location_id: str,
        target_date: date,
    ) -> tuple[float, float]:
        bias = self.error_model.bias(location_id, target_date, horizon_hours)
        sigma = self.error_model.sigma(location_id, target_date, horizon_hours)
        return expected_high_f + bias, sigma

    def prob_above(
        self,
        expected_high_f: float,
        threshold_f: float,
        horizon_hours: float,
        location_id: str,
        target_date: date,
        inclusive: bool = True,
    ) -> float:
        mu, sigma = self.mu_sigma(expected_high_f, horizon_hours, location_id, target_date)
        cc = self.error_model.continuity_correction_f
        cut = threshold_f - cc if inclusive else threshold_f + cc
        # P(T >= threshold) ≈ 1 - F(threshold - 0.5)
        raw = 1.0 - self.error_model.cdf(cut, mu, sigma)
        return self._clip(raw)

    def prob_below(
        self,
        expected_high_f: float,
        threshold_f: float,
        horizon_hours: float,
        location_id: str,
        target_date: date,
        inclusive: bool = True,
    ) -> float:
        mu, sigma = self.mu_sigma(expected_high_f, horizon_hours, location_id, target_date)
        cc = self.error_model.continuity_correction_f
        cut = threshold_f + cc if inclusive else threshold_f - cc
        raw = self.error_model.cdf(cut, mu, sigma)
        return self._clip(raw)

    def prob_range(
        self,
        expected_high_f: float,
        lo_f: float,
        hi_f: float,
        horizon_hours: float,
        location_id: str,
        target_date: date,
    ) -> float:
        mu, sigma = self.mu_sigma(expected_high_f, horizon_hours, location_id, target_date)
        cc = self.error_model.continuity_correction_f
        raw = self.error_model.cdf(hi_f + cc, mu, sigma) - self.error_model.cdf(lo_f - cc, mu, sigma)
        return self._clip(max(raw, 0.0))

    def contract_probability(
        self,
        contract: TemperatureContract,
        expected_high_f: float,
        horizon_hours: float,
    ) -> float:
        if contract.kind == ContractKind.ABOVE:
            return self.prob_above(
                expected_high_f,
                float(contract.threshold_f),
                horizon_hours,
                contract.location_id,
                contract.settlement_date,
            )
        if contract.kind == ContractKind.BELOW:
            return self.prob_below(
                expected_high_f,
                float(contract.threshold_f),
                horizon_hours,
                contract.location_id,
                contract.settlement_date,
            )
        return self.prob_range(
            expected_high_f,
            float(contract.range_lo_f),
            float(contract.range_hi_f),
            horizon_hours,
            contract.location_id,
            contract.settlement_date,
        )

    def normalize_exclusive_buckets(
        self,
        probabilities: Mapping[str, float],
        residual_key: str | None = None,
    ) -> dict[str, float]:
        """Renormalize mutually exclusive RANGE contracts so they sum to <= 1.

        If the buckets are not a complete partition, leftover mass is assigned
        to ``residual_key`` when provided; otherwise leftover is left implicit.
        """
        clipped = {k: self._clip(v) for k, v in probabilities.items()}
        total = sum(clipped.values())
        if total <= 1.0:
            if residual_key is not None and residual_key not in clipped:
                clipped[residual_key] = self._clip(1.0 - total)
            return clipped
        return {k: self._clip(v / total) for k, v in clipped.items()}

    def revision(
        self,
        contract: TemperatureContract,
        previous_high_f: float,
        previous_horizon_hours: float,
        current_high_f: float,
        current_horizon_hours: float,
    ) -> dict[str, float]:
        p0 = self.contract_probability(contract, previous_high_f, previous_horizon_hours)
        p1 = self.contract_probability(contract, current_high_f, current_horizon_hours)
        return {
            "forecast_revision_f": current_high_f - previous_high_f,
            "prob_revision": p1 - p0,
            "prev_prob": p0,
            "new_prob": p1,
            "horizon_change_h": current_horizon_hours - previous_horizon_hours,
        }

    def expected_probability_se(
        self,
        model_probability: float,
        horizon_hours: float,
        extra_market_noise: float = 0.03,
    ) -> float:
        """Rough SE of a probability quote vs calibrated model.

        Combines Bernoulli sampling variance of the model with a horizon-
        dependent market-noise term. Used by the calibration strategy z-score.
        """
        p = self._clip(model_probability)
        bernoulli = sqrt(p * (1.0 - p))
        horizon_scale = 1.0 / sqrt(max(horizon_hours, 1.0) / 24.0 + 0.25)
        return max(0.02, 0.25 * bernoulli * horizon_scale + extra_market_noise)

    def _clip(self, p: float) -> float:
        floor = self.error_model.p_floor
        return min(max(p, floor), 1.0 - floor)


def default_conus_summer_error_model() -> ForecastErrorModel:
    """Conservative pooled CONUS warm-season defaults.

    These are starting priors, not claimed NWS statistics. Replace
    ``bias_by_key`` / ``sigma_by_key`` with station-level calibration before
    live trading.
    """
    sigma_by_key = {
        "*|*|3": 1.4,
        "*|*|6": 1.7,
        "*|*|12": 2.1,
        "*|*|24": 2.8,
        "*|*|36": 3.3,
        "*|*|48": 3.7,
        "*|*|72": 4.5,
        "*|*|120": 5.6,
        "*|*|168": 6.6,
        "*|*|240": 7.8,
        "*": 3.5,
    }
    sample_size_by_key = {k: 200 for k in sigma_by_key}
    return ForecastErrorModel(
        distribution="gaussian",
        sigma_by_key=sigma_by_key,
        sample_size_by_key=sample_size_by_key,
        min_samples_for_local=40,
    )

# === risk.py ===
from dataclasses import dataclass, field
from typing import Mapping



@dataclass(slots=True)
class RiskLimits:
    max_position_contracts: float = 250.0
    max_event_notional: float = 1_000.0
    max_location_notional: float = 2_000.0
    max_simultaneous_positions: int = 12
    max_equity_fraction: float = 0.08
    min_model_edge: float = 0.04
    max_bid_ask_spread: float = 0.06
    min_liquidity_contracts: float = 25.0
    min_hours_to_settlement: float = 2.0
    halt_hours_before_settlement: float = 1.0
    stale_forecast_hours: float = 8.0
    stale_quote_minutes: float = 15.0
    transaction_cost_prob: float = 0.015  # fees + expected slippage in prob units
    allow_short: bool = True
    allow_overlapping_exclusive_yes: bool = False


@dataclass(slots=True)
class PortfolioSnapshot:
    """Strategy-maintained view so risk does not depend on NT portfolio internals."""

    position_qty: dict[str, float] = field(default_factory=dict)  # signed YES qty
    pending_qty: dict[str, float] = field(default_factory=dict)
    equity: float = 10_000.0

    def net_qty(self, instrument_id: str) -> float:
        return self.position_qty.get(instrument_id, 0.0) + self.pending_qty.get(instrument_id, 0.0)

    def open_position_count(self) -> int:
        return sum(1 for q in self.position_qty.values() if abs(q) > 1e-9)


@dataclass(slots=True)
class RiskDecision:
    allowed: bool
    reason: str
    clipped_quantity: float = 0.0


class RiskManager:
    def __init__(self, limits: RiskLimits, registry: WeatherContractRegistry) -> None:
        self.limits = limits
        self.registry = registry

    def quote_tradable(self, quote: MarketQuote, price_scale: float, now_ts_age_minutes: float) -> tuple[bool, str]:
        if quote.bid is None or quote.ask is None:
            return False, "missing_bid_ask"
        if quote.ask <= quote.bid:
            return False, "crossed_or_locked_ignored"
        spread = (quote.ask - quote.bid) * price_scale
        if spread > self.limits.max_bid_ask_spread:
            return False, f"spread_{spread:.3f}"
        liq = min(quote.bid_size or 0.0, quote.ask_size or 0.0)
        if liq < self.limits.min_liquidity_contracts:
            return False, "insufficient_liquidity"
        if now_ts_age_minutes > self.limits.stale_quote_minutes:
            return False, "stale_quote"
        return True, "ok"

    def event_notional(self, portfolio: PortfolioSnapshot, event_key: str) -> float:
        total = 0.0
        for contract in self.registry.event_contracts(event_key):
            qty = abs(portfolio.net_qty(contract.instrument_id))
            total += qty * contract.contract_size
        return total

    def location_notional(self, portfolio: PortfolioSnapshot, location_id: str) -> float:
        total = 0.0
        for contract in self.registry.all():
            if contract.location_id != location_id:
                continue
            total += abs(portfolio.net_qty(contract.instrument_id)) * contract.contract_size
        return total

    def exclusive_conflict(
        self,
        contract: TemperatureContract,
        signed_qty_delta: float,
        portfolio: PortfolioSnapshot,
    ) -> bool:
        if self.limits.allow_overlapping_exclusive_yes:
            return False
        if signed_qty_delta <= 0:
            return False  # reducing or shorting YES is not a second long-YES
        group = self.registry.mutually_exclusive_group(contract.instrument_id)
        for other in group:
            if other.instrument_id == contract.instrument_id:
                continue
            if portfolio.net_qty(other.instrument_id) > 1e-9:
                return True
        return False

    def evaluate_order(
        self,
        *,
        contract: TemperatureContract,
        signed_qty_delta: float,
        hours_to_settlement: float,
        forecast_age_hours: float,
        edge: float,
        portfolio: PortfolioSnapshot,
        quote: MarketQuote,
    ) -> RiskDecision:
        limits = self.limits
        if hours_to_settlement < limits.halt_hours_before_settlement:
            return RiskDecision(False, "settlement_halt")
        if hours_to_settlement < limits.min_hours_to_settlement:
            return RiskDecision(False, "too_close_to_settlement")
        if forecast_age_hours > limits.stale_forecast_hours:
            return RiskDecision(False, "stale_forecast")
        if abs(edge) < limits.min_model_edge:
            return RiskDecision(False, "edge_below_minimum")
        if signed_qty_delta < 0 and not limits.allow_short:
            # selling YES when flat would create a short
            if portfolio.net_qty(contract.instrument_id) + signed_qty_delta < -1e-9:
                return RiskDecision(False, "shorts_disabled")

        age_min = 0.0
        ok, why = self.quote_tradable(quote, contract.price_scale, age_min)
        if not ok:
            return RiskDecision(False, why)

        if self.exclusive_conflict(contract, signed_qty_delta, portfolio):
            return RiskDecision(False, "exclusive_bucket_conflict")

        projected = portfolio.net_qty(contract.instrument_id) + signed_qty_delta
        if abs(projected) > limits.max_position_contracts + 1e-9:
            room = limits.max_position_contracts - abs(portfolio.net_qty(contract.instrument_id))
            if room <= 0:
                return RiskDecision(False, "max_position")
            signed_qty_delta = room if signed_qty_delta > 0 else -room

        event_after = self.event_notional(portfolio, contract.event_key) + abs(
            signed_qty_delta
        ) * contract.contract_size
        if event_after > limits.max_event_notional:
            return RiskDecision(False, "max_event_notional")

        loc_after = self.location_notional(portfolio, contract.location_id) + abs(
            signed_qty_delta
        ) * contract.contract_size
        if loc_after > limits.max_location_notional:
            return RiskDecision(False, "max_location_notional")

        if portfolio.open_position_count() >= limits.max_simultaneous_positions:
            if abs(portfolio.net_qty(contract.instrument_id)) < 1e-9:
                return RiskDecision(False, "max_simultaneous_positions")

        order_notional = abs(signed_qty_delta) * contract.contract_size
        if portfolio.equity > 0 and order_notional > limits.max_equity_fraction * portfolio.equity:
            clipped = (limits.max_equity_fraction * portfolio.equity) / max(contract.contract_size, 1e-9)
            if clipped < 1.0:
                return RiskDecision(False, "equity_fraction")
            signed_qty_delta = clipped if signed_qty_delta > 0 else -clipped

        return RiskDecision(True, "ok", clipped_quantity=signed_qty_delta)


def edge_after_costs(
    *,
    model_p: float,
    bid_p: float | None,
    ask_p: float | None,
    intent_long_yes: bool,
    cost: float,
) -> float | None:
    """Executable edge versus bid/ask, not midpoint.

    Long YES edge = model_p - ask_p - cost
    Short YES edge = bid_p - model_p - cost
    """
    if intent_long_yes:
        if ask_p is None:
            return None
        return model_p - ask_p - cost
    if bid_p is None:
        return None
    return bid_p - model_p - cost

# === nt_adapt.py ===
from datetime import datetime, timezone
from typing import Any, Iterable


def import_strategy_types() -> tuple[type, type]:
    try:
        from nautilus_trader.trading import Strategy
        from nautilus_trader.config import StrategyConfig

        return Strategy, StrategyConfig
    except Exception:  # pragma: no cover
        try:
            from nautilus_trader.trading.strategy import Strategy
            from nautilus_trader.trading.strategy import StrategyConfig

            return Strategy, StrategyConfig
        except Exception:

            class StrategyConfig:  # type: ignore
                def __init__(self, **kwargs: Any) -> None:
                    seen: set[str] = set()
                    for cls in type(self).mro():
                        annot = getattr(cls, "__annotations__", {})
                        for name in annot:
                            if name.startswith("_") or name in seen:
                                continue
                            if name in kwargs:
                                setattr(self, name, kwargs[name])
                            elif hasattr(cls, name):
                                setattr(self, name, getattr(cls, name))
                            seen.add(name)
                    for k, v in kwargs.items():
                        setattr(self, k, v)

            class Strategy:  # type: ignore
                def __init__(self, config: Any = None) -> None:
                    self.config = config
                    self.clock = _DummyClock()
                    self.log = _DummyLog()
                    self.cache = _DummyCache()
                    self.portfolio = _DummyPortfolio()
                    self.order_factory = _DummyOrderFactory()

                def subscribe_quote_ticks(self, instrument_id: Any) -> None:
                    return None

                def subscribe_data(self, data_type: Any, client_id: Any = None) -> None:
                    return None

                def submit_order(self, order: Any) -> None:
                    return None

                def cancel_all_orders(self, instrument_id: Any = None) -> None:
                    return None

                def close_all_positions(self, instrument_id: Any = None) -> None:
                    return None

            return Strategy, StrategyConfig


class _DummyClock:
    def utc_now(self) -> datetime:
        return datetime.now(timezone.utc)


class _DummyLog:
    def info(self, msg: str) -> None:
        print(f"INFO {msg}")

    def warning(self, msg: str) -> None:
        print(f"WARN {msg}")

    def error(self, msg: str) -> None:
        print(f"ERROR {msg}")

    def debug(self, msg: str) -> None:
        print(f"DEBUG {msg}")


class _DummyCache:
    def instrument(self, instrument_id: Any) -> None:
        return None

    def quote_tick(self, instrument_id: Any) -> None:
        return None

    def positions_open(self, instrument_id: Any = None) -> list:
        return []

    def orders_open(self, instrument_id: Any = None) -> list:
        return []


class _DummyPortfolio:
    def account(self, account_id: Any = None) -> None:
        return None


class _DummyOrderFactory:
    def market(self, **kwargs: Any) -> dict:
        return {"type": "market", **kwargs}

    def limit(self, **kwargs: Any) -> dict:
        return {"type": "limit", **kwargs}


def instrument_id_from_str(value: str) -> Any:
    try:
        from nautilus_trader.model import InstrumentId

        return InstrumentId.from_str(value)
    except Exception:
        try:
            from nautilus_trader.model.identifiers import InstrumentId

            return InstrumentId.from_str(value)
        except Exception:
            return value


def order_side_buy() -> Any:
    try:
        from nautilus_trader.model.enums import OrderSide

        return OrderSide.BUY
    except Exception:
        return "BUY"


def order_side_sell() -> Any:
    try:
        from nautilus_trader.model.enums import OrderSide

        return OrderSide.SELL
    except Exception:
        return "SELL"


def time_in_force_ioc() -> Any:
    try:
        from nautilus_trader.model.enums import TimeInForce

        return TimeInForce.IOC
    except Exception:
        return "IOC"


def time_in_force_gtc() -> Any:
    try:
        from nautilus_trader.model.enums import TimeInForce

        return TimeInForce.GTC
    except Exception:
        return "GTC"


def make_qty(instrument: Any, qty: float) -> Any:
    if instrument is not None and hasattr(instrument, "make_qty"):
        try:
            return instrument.make_qty(qty)
        except Exception:
            pass
    try:
        from nautilus_trader.model.objects import Quantity

        return Quantity.from_str(str(qty))
    except Exception:
        return qty


def make_price(instrument: Any, price: float) -> Any:
    if instrument is not None and hasattr(instrument, "make_price"):
        try:
            return instrument.make_price(price)
        except Exception:
            pass
    try:
        from nautilus_trader.model.objects import Price

        return Price.from_str(f"{price:.4f}")
    except Exception:
        return price


def quote_to_raw(tick: Any) -> tuple[float | None, float | None, float | None, float | None, datetime]:
    bid = _px(getattr(tick, "bid_price", None))
    ask = _px(getattr(tick, "ask_price", None))
    bid_sz = _px(getattr(tick, "bid_size", None))
    ask_sz = _px(getattr(tick, "ask_size", None))
    ts = getattr(tick, "ts_event", None)
    if isinstance(ts, int):
        dt = datetime.fromtimestamp(ts / 1_000_000_000, tz=timezone.utc)
    elif isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.now(timezone.utc)
    return bid, ask, bid_sz, ask_sz, dt


def _px(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def utc_now_from(strategy: Any) -> datetime:
    now = strategy.clock.utc_now()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now
    # pandas.Timestamp
    try:
        py = now.to_pydatetime()
        if py.tzinfo is None:
            return py.replace(tzinfo=timezone.utc)
        return py
    except Exception:
        return datetime.now(timezone.utc)


def signed_position_qty(strategy: Any, instrument_id: Any) -> float:
    cache = strategy.cache
    positions: Iterable[Any] = []
    if hasattr(cache, "positions_open"):
        try:
            positions = cache.positions_open(instrument_id=instrument_id)
        except TypeError:
            positions = cache.positions_open()
    total = 0.0
    for pos in positions or []:
        pid = str(getattr(pos, "instrument_id", ""))
        if pid and pid != str(instrument_id):
            continue
        signed = getattr(pos, "signed_qty", None)
        if signed is not None:
            total += float(signed)
            continue
        qty = float(getattr(pos, "quantity", 0.0) or 0.0)
        side = str(getattr(getattr(pos, "side", None), "name", getattr(pos, "side", "")))
        total += qty if "SHORT" not in side.upper() else -qty
    return total


def has_open_orders(strategy: Any, instrument_id: Any) -> bool:
    cache = strategy.cache
    if not hasattr(cache, "orders_open"):
        return False
    try:
        orders = cache.orders_open(instrument_id=instrument_id)
    except TypeError:
        orders = cache.orders_open()
    for order in orders or []:
        if str(getattr(order, "instrument_id", "")) == str(instrument_id):
            return True
    return False

# === strategy_base.py ===
from datetime import date, datetime, timedelta
from typing import Any


Strategy, StrategyConfig = import_strategy_types()


class WeatherStrategyConfig(StrategyConfig):  # type: ignore[misc]
    """Common knobs. Concrete configs subclass this and add signal parameters."""

    instrument_ids: tuple[str, ...] = ()
    nws_client_id: str | None = "NWS"
    price_scale_override: float | None = None
    use_limit_orders: bool = True
    limit_inside_ticks: int = 0
    flatten_on_stop: bool = True
    flatten_on_observation: bool = False
    diagnostic_log: bool = True
    # Risk
    max_position_contracts: float = 250.0
    max_event_notional: float = 1_000.0
    max_location_notional: float = 2_000.0
    max_simultaneous_positions: int = 12
    max_equity_fraction: float = 0.08
    min_model_edge: float = 0.04
    max_bid_ask_spread: float = 0.06
    min_liquidity_contracts: float = 25.0
    min_hours_to_settlement: float = 2.0
    halt_hours_before_settlement: float = 1.0
    stale_forecast_hours: float = 8.0
    stale_quote_minutes: float = 15.0
    transaction_cost_prob: float = 0.015
    allow_short: bool = True
    starting_equity: float = 10_000.0
    # Probability
    error_distribution: str = "gaussian"
    student_t_df: float = 7.0
    sigma_floor_f: float = 1.1
    sigma_per_sqrt_hour_f: float = 0.55
    p_floor: float = 0.01


class WeatherStrategyBase(Strategy):  # type: ignore[misc]
    def __init__(
        self,
        config: WeatherStrategyConfig,
        registry: WeatherContractRegistry,
        engine: WeatherProbabilityEngine | None = None,
    ) -> None:
        super().__init__(config)
        self.registry = registry
        self.engine = engine or WeatherProbabilityEngine()
        self.risk = RiskManager(self._limits_from_config(config), registry)
        self.forecasts: dict[tuple[str, date], ForecastSnapshot] = {}
        self.quotes: dict[str, MarketQuote] = {}
        self.portfolio_view = PortfolioSnapshot(equity=float(config.starting_equity))
        self._last_order_reason: dict[str, str] = {}
        self._last_signal_ts: dict[str, datetime] = {}
        self._observations: dict[tuple[str, date], float] = {}
        self._nt_ids = {iid: instrument_id_from_str(iid) for iid in config.instrument_ids}

    def _limits_from_config(self, config: WeatherStrategyConfig) -> RiskLimits:
        return RiskLimits(
            max_position_contracts=config.max_position_contracts,
            max_event_notional=config.max_event_notional,
            max_location_notional=config.max_location_notional,
            max_simultaneous_positions=config.max_simultaneous_positions,
            max_equity_fraction=config.max_equity_fraction,
            min_model_edge=config.min_model_edge,
            max_bid_ask_spread=config.max_bid_ask_spread,
            min_liquidity_contracts=config.min_liquidity_contracts,
            min_hours_to_settlement=config.min_hours_to_settlement,
            halt_hours_before_settlement=config.halt_hours_before_settlement,
            stale_forecast_hours=config.stale_forecast_hours,
            stale_quote_minutes=config.stale_quote_minutes,
            transaction_cost_prob=config.transaction_cost_prob,
            allow_short=config.allow_short,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_start(self) -> None:
        for iid, nt_id in self._nt_ids.items():
            self.subscribe_quote_ticks(nt_id)
            self.log.info(f"{self.__class__.__name__} subscribed quotes {iid}")
        # Adaptation point: custom data subscription
        try:
            kwargs: dict[str, Any] = {}
            if self.config.nws_client_id:
                try:
                    from nautilus_trader.model.identifiers import ClientId

                    kwargs["client_id"] = ClientId(self.config.nws_client_id)
                except Exception:
                    kwargs["client_id"] = self.config.nws_client_id
            self.subscribe_data(nws_forecast_data_type(), **kwargs)
            self.subscribe_data(nws_observation_data_type(), **kwargs)
        except Exception as exc:
            self.log.warning(f"subscribe_data adaptation needed: {exc}")
        self._sync_positions_from_cache()

    def on_stop(self) -> None:
        if self.config.flatten_on_stop:
            for nt_id in self._nt_ids.values():
                try:
                    self.cancel_all_orders(nt_id)
                    self.close_all_positions(nt_id)
                except Exception as exc:
                    self.log.warning(f"flatten adaptation: {exc}")

    def on_reset(self) -> None:
        self.forecasts.clear()
        self.quotes.clear()
        self.portfolio_view = PortfolioSnapshot(equity=float(self.config.starting_equity))
        self._last_order_reason.clear()
        self._last_signal_ts.clear()

    # ------------------------------------------------------------------
    # Data handlers
    # ------------------------------------------------------------------
    def on_quote_tick(self, tick: Any) -> None:
        iid = str(getattr(tick, "instrument_id", ""))
        bid, ask, bid_sz, ask_sz, ts = quote_to_raw(tick)
        self.quotes[iid] = MarketQuote(
            instrument_id=iid,
            bid=bid,
            ask=ask,
            bid_size=bid_sz,
            ask_size=ask_sz,
            ts_event=ts,
        )
        self._evaluate_and_act(iid)

    def on_data(self, data: Any) -> None:
        if isinstance(data, NWSForecastUpdate):
            self.on_nws_forecast(data)
        elif isinstance(data, NWSObservation):
            self.on_nws_observation(data)

    def on_nws_forecast(self, event: NWSForecastUpdate) -> None:
        snap = event.to_snapshot()
        key = (snap.location_id, snap.target_date)
        prev = self.forecasts.get(key)
        if prev is not None and snap.published_at < prev.published_at:
            self.log.warning(
                f"Ignoring out-of-order forecast {key} pub={snap.published_at} < {prev.published_at}"
            )
            return
        self.forecasts[key] = snap
        if self.config.diagnostic_log:
            self.log.info(
                f"NWS {snap.location_id} {snap.target_date} high={snap.expected_high_f:.1f}F "
                f"h={snap.horizon_hours:.1f}h src={snap.source}"
            )
        self.on_forecast_updated(snap, prev)
        for contract in self.registry.all():
            if contract.location_id == snap.location_id and contract.settlement_date == snap.target_date:
                self._evaluate_and_act(contract.instrument_id)

    def on_nws_observation(self, event: NWSObservation) -> None:
        self._observations[(event.location_id, event.target_date)] = event.observed_high_f
        if self.config.diagnostic_log:
            self.log.info(
                f"OBS {event.location_id} {event.target_date} high={event.observed_high_f:.1f}F "
                "(not used for trading)"
            )
        if not self.config.flatten_on_observation:
            return
        for contract in self.registry.all():
            if contract.location_id == event.location_id and contract.settlement_date == event.target_date:
                self._flatten(contract.instrument_id, "observation_received")

    def on_forecast_updated(self, current: ForecastSnapshot, previous: ForecastSnapshot | None) -> None:
        """Hook for revision strategy."""

    def evaluate_instrument(
        self,
        contract: TemperatureContract,
        quote: MarketQuote,
        forecast: ForecastSnapshot,
        now: datetime,
    ) -> SignalDecision | None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def _evaluate_and_act(self, instrument_id: str) -> None:
        contract = self.registry.get(instrument_id)
        if contract is None:
            return
        now = utc_now_from(self)
        if hours_until(contract.settlement_datetime_utc(), now) <= self.config.halt_hours_before_settlement:
            self._flatten(instrument_id, "settlement_halt")
            return
        quote = self.quotes.get(instrument_id)
        forecast = self.forecasts.get((contract.location_id, contract.settlement_date))
        if quote is None or forecast is None:
            return
        self._sync_positions_from_cache()
        decision = self.evaluate_instrument(contract, quote, forecast, now)
        if decision is None or decision.intent == SideIntent.FLAT:
            if decision is not None and decision.intent == SideIntent.FLAT:
                if abs(self.portfolio_view.net_qty(instrument_id)) > 1e-9:
                    self._flatten(instrument_id, decision.reason)
            return
        self._maybe_submit(contract, quote, decision, forecast, now)

    def _maybe_submit(
        self,
        contract: TemperatureContract,
        quote: MarketQuote,
        decision: SignalDecision,
        forecast: ForecastSnapshot,
        now: datetime,
    ) -> None:
        iid = contract.instrument_id
        nt_id = self._nt_ids.get(iid) or instrument_id_from_str(iid)
        if has_open_orders(self, nt_id):
            self.log.debug(f"skip {iid}: working order exists")
            return
        current_qty = self.portfolio_view.net_qty(iid)
        target_qty = decision.quantity if decision.intent == SideIntent.LONG_YES else -decision.quantity
        delta = target_qty - current_qty
        if abs(delta) < 1.0:
            return
        hours_left = hours_until(contract.settlement_datetime_utc(), now)
        forecast_age = (ensure_aware(now) - ensure_aware(forecast.published_at)).total_seconds() / 3600.0
        risk = self.risk.evaluate_order(
            contract=contract,
            signed_qty_delta=delta,
            hours_to_settlement=hours_left,
            forecast_age_hours=forecast_age,
            edge=decision.edge,
            portfolio=self.portfolio_view,
            quote=quote,
        )
        if not risk.allowed:
            if self.config.diagnostic_log:
                self.log.info(f"RISK block {iid}: {risk.reason} edge={decision.edge:.3f}")
            return
        delta = risk.clipped_quantity
        self._submit_delta(contract, quote, delta, decision)

    def _submit_delta(
        self,
        contract: TemperatureContract,
        quote: MarketQuote,
        signed_delta: float,
        decision: SignalDecision,
    ) -> None:
        iid = contract.instrument_id
        nt_id = self._nt_ids.get(iid) or instrument_id_from_str(iid)
        instrument = None
        try:
            instrument = self.cache.instrument(nt_id)
        except Exception:
            instrument = None
        side = order_side_buy() if signed_delta > 0 else order_side_sell()
        qty = make_qty(instrument, abs(signed_delta))
        # Adaptation point: order construction
        try:
            if self.config.use_limit_orders:
                raw_px = quote.ask if signed_delta > 0 else quote.bid
                if raw_px is None:
                    return
                tick = contract.tick_size
                adjust = self.config.limit_inside_ticks * tick
                limit_px = raw_px if signed_delta > 0 else raw_px
                # optionally step inside the spread
                if signed_delta > 0:
                    limit_px = raw_px - adjust
                else:
                    limit_px = raw_px + adjust
                order = self.order_factory.limit(
                    instrument_id=nt_id,
                    order_side=side,
                    quantity=qty,
                    price=make_price(instrument, float(limit_px)),
                    time_in_force=time_in_force_ioc(),
                )
            else:
                order = self.order_factory.market(
                    instrument_id=nt_id,
                    order_side=side,
                    quantity=qty,
                )
            self.submit_order(order)
            self.portfolio_view.pending_qty[iid] = self.portfolio_view.pending_qty.get(iid, 0.0) + signed_delta
            self._last_order_reason[iid] = decision.reason
            self._last_signal_ts[iid] = utc_now_from(self)
            self.log.info(
                f"ORDER {iid} delta={signed_delta:+.1f} intent={decision.intent.value} "
                f"edge={decision.edge:.3f} model={decision.model_probability:.3f} "
                f"mkt={decision.market_probability:.3f} reason={decision.reason}"
            )
        except Exception as exc:
            self.log.error(f"submit_order adaptation needed for {iid}: {exc}")

    def _flatten(self, instrument_id: str, reason: str) -> None:
        nt_id = self._nt_ids.get(instrument_id) or instrument_id_from_str(instrument_id)
        qty = self.portfolio_view.net_qty(instrument_id)
        if abs(qty) < 1e-9:
            return
        if has_open_orders(self, nt_id):
            try:
                self.cancel_all_orders(nt_id)
            except Exception:
                pass
        try:
            self.close_all_positions(nt_id)
            self.log.info(f"FLATTEN {instrument_id} qty={qty:.1f} reason={reason}")
        except Exception as exc:
            self.log.warning(f"close_all_positions adaptation: {exc}")

    def _sync_positions_from_cache(self) -> None:
        for iid, nt_id in self._nt_ids.items():
            self.portfolio_view.position_qty[iid] = signed_position_qty(self, nt_id)
        # pending is cleared when cache qty matches; conservative decay
        for iid, pending in list(self.portfolio_view.pending_qty.items()):
            cached = self.portfolio_view.position_qty.get(iid, 0.0)
            if abs(pending) > 0 and abs(cached) > 0:
                self.portfolio_view.pending_qty[iid] = 0.0
        try:
            account = self.portfolio.account()
            if account is not None and hasattr(account, "balance_total"):
                # Adaptation point: account equity accessor
                bal = account.balance_total
                if callable(bal):
                    bal = bal()
                if bal is not None:
                    self.portfolio_view.equity = float(getattr(bal, "as_double", lambda: bal)())
        except Exception:
            pass

    def hours_to_settlement(self, contract: TemperatureContract, now: datetime) -> float:
        return hours_until(contract.settlement_datetime_utc(), now)

    def implied_probs(self, contract: TemperatureContract, quote: MarketQuote) -> tuple[float | None, float | None, float | None]:
        scale = self.config.price_scale_override or contract.price_scale
        return quote.implied_bid(scale), quote.implied_ask(scale), quote.implied_mid(scale)

    def quote_age_minutes(self, quote: MarketQuote, now: datetime) -> float:
        return (ensure_aware(now) - ensure_aware(quote.ts_event)).total_seconds() / 60.0

# === forecast_revision.py ===
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Deque



class ForecastRevisionConfig(WeatherStrategyConfig):  # type: ignore[misc]
    strategy_id: str | None = "FORECAST-REVISION-001"
    min_temp_revision_f: float = 1.5
    min_prob_revision: float = 0.05
    min_revision_over_sigma: float = 0.60  # |dT| / sigma_prev
    min_unabsorbed_prob: float = 0.03  # model_dp - market_dp
    min_caught_up_fraction: float = 0.55
    persistence_updates: int = 2
    persistence_same_sign: bool = True
    reaction_window_minutes: float = 90.0
    cooldown_minutes: float = 45.0
    base_quantity: float = 20.0
    max_quantity: float = 120.0
    revision_qty_scale: float = 500.0
    exit_when_market_catches_up: bool = True
    history_len: int = 12


class ForecastRevisionStrategy(WeatherStrategyBase):
    def __init__(
        self,
        config: ForecastRevisionConfig,
        registry: WeatherContractRegistry,
        engine: WeatherProbabilityEngine | None = None,
    ) -> None:
        super().__init__(config, registry, engine)
        self.config: ForecastRevisionConfig = config
        self._forecast_hist: dict[tuple[str, object], Deque[ForecastSnapshot]] = defaultdict(
            lambda: deque(maxlen=config.history_len)
        )
        self._market_p_at_forecast: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        self._traded_publication: dict[str, datetime] = {}
        self._active_revision: dict[str, dict[str, float | str | datetime]] = {}

    def on_forecast_updated(self, current: ForecastSnapshot, previous: ForecastSnapshot | None) -> None:
        key = (current.location_id, current.target_date)
        self._forecast_hist[key].append(current)
        # Snapshot market probs at the moment the forecast arrives so later
        # quotes can measure how much the book has absorbed.
        for contract in self.registry.all():
            if contract.location_id != current.location_id or contract.settlement_date != current.target_date:
                continue
            quote = self.quotes.get(contract.instrument_id)
            if quote is None or quote.mid is None:
                continue
            mid_p = quote.implied_mid(contract.price_scale)
            if mid_p is None:
                continue
            self._market_p_at_forecast[contract.instrument_id].append((current.published_at, mid_p))

    def evaluate_instrument(
        self,
        contract: TemperatureContract,
        quote: MarketQuote,
        forecast: ForecastSnapshot,
        now: datetime,
    ) -> SignalDecision | None:
        cfg = self.config
        key = (contract.location_id, contract.settlement_date)
        hist = list(self._forecast_hist.get(key, []))
        if len(hist) < 2:
            return None
        current = hist[-1]
        previous = hist[-2]
        if current.published_at <= previous.published_at:
            return None

        rev = self.engine.revision(
            contract,
            previous.expected_high_f,
            previous.horizon_hours,
            current.expected_high_f,
            current.horizon_hours,
        )
        d_t = rev["forecast_revision_f"]
        d_p = rev["prob_revision"]
        _, sigma_prev = self.engine.mu_sigma(
            previous.expected_high_f,
            previous.horizon_hours,
            contract.location_id,
            contract.settlement_date,
        )

        window_end = current.published_at + timedelta(minutes=cfg.reaction_window_minutes)
        if ensure_aware(now) > ensure_aware(window_end):
            return self._maybe_exit_caught_up(contract, quote, d_p, now)

        last_traded = self._traded_publication.get(contract.instrument_id)
        if last_traded is not None and last_traded == current.published_at:
            return self._maybe_exit_caught_up(contract, quote, d_p, now)
        cooldown_until = (last_traded or datetime.min.replace(tzinfo=current.published_at.tzinfo)) + timedelta(
            minutes=cfg.cooldown_minutes
        )
        if last_traded is not None and ensure_aware(now) < ensure_aware(cooldown_until):
            return None

        if abs(d_t) < cfg.min_temp_revision_f and abs(d_p) < cfg.min_prob_revision:
            return None
        if abs(d_t) / max(sigma_prev, 0.4) < cfg.min_revision_over_sigma and abs(d_p) < cfg.min_prob_revision:
            return None

        if cfg.persistence_same_sign and len(hist) >= cfg.persistence_updates + 1:
            signs = []
            for i in range(-cfg.persistence_updates, 0):
                a, b = hist[i - 1], hist[i]
                signs.append(1 if b.expected_high_f - a.expected_high_f >= 0 else -1)
            if abs(sum(signs)) != cfg.persistence_updates:
                # require the last N revisions to share a sign
                if cfg.persistence_updates > 1:
                    return None

        market_dp = self._market_move_since(contract.instrument_id, current.published_at, quote, contract.price_scale)
        if market_dp is None:
            market_dp = 0.0
        # How much of the model revision the book has already priced.
        if abs(d_p) > 1e-9:
            absorbed = market_dp / d_p
        else:
            absorbed = 1.0
        unabsorbed = d_p - market_dp
        if abs(unabsorbed) < cfg.min_unabsorbed_prob:
            return None
        if absorbed >= cfg.min_caught_up_fraction and d_p * market_dp > 0:
            return None

        intent = SideIntent.LONG_YES if unabsorbed > 0 else SideIntent.SHORT_YES
        if intent == SideIntent.SHORT_YES and not cfg.allow_short:
            return None

        bid_p, ask_p, mid_p = self.implied_probs(contract, quote)
        mkt = (ask_p if intent == SideIntent.LONG_YES else bid_p) or mid_p or 0.0
        edge = abs(unabsorbed) - cfg.transaction_cost_prob
        if edge < cfg.min_model_edge:
            return None

        qty = min(cfg.max_quantity, cfg.base_quantity + cfg.revision_qty_scale * abs(unabsorbed))
        decision = SignalDecision(
            instrument_id=contract.instrument_id,
            intent=intent,
            model_probability=rev["new_prob"],
            market_probability=mkt,
            edge=edge,
            conviction=min(1.0, abs(unabsorbed) / max(cfg.min_prob_revision, 1e-6)),
            quantity=qty,
            reason="forecast_revision_unabsorbed",
            metadata={
                "dT": d_t,
                "dP_model": d_p,
                "dP_market": market_dp,
                "unabsorbed": unabsorbed,
                "absorbed_frac": absorbed,
                "sigma_prev": sigma_prev,
                "publication": current.published_at.isoformat(),
            },
        )
        self._traded_publication[contract.instrument_id] = current.published_at
        self._active_revision[contract.instrument_id] = {
            "dP_model": d_p,
            "published_at": current.published_at,
        }
        return decision

    def _maybe_exit_caught_up(
        self,
        contract: TemperatureContract,
        quote: MarketQuote,
        d_p: float,
        now: datetime,
    ) -> SignalDecision | None:
        cfg = self.config
        if not cfg.exit_when_market_catches_up:
            return None
        if abs(self.portfolio_view.net_qty(contract.instrument_id)) < 1e-9:
            return None
        active = self._active_revision.get(contract.instrument_id)
        if not active:
            return None
        pub = active["published_at"]
        assert isinstance(pub, datetime)
        market_dp = self._market_move_since(contract.instrument_id, pub, quote, contract.price_scale) or 0.0
        model_dp = float(active["dP_model"])
        if abs(model_dp) < 1e-9:
            return None
        absorbed = market_dp / model_dp
        if absorbed >= cfg.min_caught_up_fraction and model_dp * market_dp > 0:
            mid = quote.implied_mid(contract.price_scale) or 0.0
            return SignalDecision(
                contract.instrument_id,
                SideIntent.FLAT,
                mid + model_dp,
                mid,
                0.0,
                0.0,
                0.0,
                "revision_market_caught_up",
                {"absorbed_frac": absorbed},
            )
        return None

    def _market_move_since(
        self,
        instrument_id: str,
        published_at: datetime,
        quote: MarketQuote,
        price_scale: float,
    ) -> float | None:
        series = self._market_p_at_forecast.get(instrument_id, [])
        baseline = None
        for ts, p in series:
            if ts == published_at:
                baseline = p
                break
        if baseline is None and series:
            # nearest snapshot at or before publication
            prior = [p for ts, p in series if ts <= published_at]
            baseline = prior[-1] if prior else None
        mid = quote.implied_mid(price_scale)
        if baseline is None or mid is None:
            return None
        return mid - baseline

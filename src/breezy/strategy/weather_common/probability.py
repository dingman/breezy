"""Forecast-error probability model, carried over from the bundle's ``probability.py``.

The math (Gaussian/Student-t CDF via a hand-rolled Lanczos log-gamma and
continued-fraction incomplete beta, horizon-scaled sigma, continuity
correction) is untouched -- it is exactly the operator's calibration model,
which this task preserves rather than redesigns.

What changed from the bundle: :meth:`WeatherProbabilityEngine.contract_probability`
took the bundle's own ``TemperatureContract``/``ContractKind`` (parsed by the
bundle itself, never verified against a real venue). It is replaced here by
:meth:`WeatherProbabilityEngine.bucket_probability`, which takes a
:class:`breezy.domain.weather_bucket_facts.WeatherBucketFacts` -- the
already-verified, venue-corroborated bucket bounds
(``breezy.domain.weather_bucket_facts.read_weather_bucket_facts``). The
mapping from closed ``(lower_f, upper_f)`` bounds to a one-sided or two-sided
probability integral is new plumbing, not new math: the three branches below
are the same ``prob_above`` / ``prob_below`` / ``prob_range`` calls the bundle
made, selected by which bound is present instead of by a hand-authored
``ContractKind`` enum.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from math import erf, exp, log, pi, sqrt
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from breezy.domain.weather_bucket_facts import WeatherBucketFacts

from breezy.domain.weather_bucket_facts import Measure

__all__ = [
    "ForecastErrorModel",
    "ForecastRevision",
    "HorizonSigmaParams",
    "UnsupportedMeasureError",
    "WeatherProbabilityEngine",
    "default_conus_summer_error_model",
]


class UnsupportedMeasureError(ValueError):
    """Raised for a bucket whose ``measure`` is not ``Measure.HIGH``.

    ``WeatherProbabilityEngine`` models the day's HIGH temperature only --
    that is what ``expected_high_f`` means throughout this module, and it is
    what the operator's original model assumed unconditionally (it had no
    ``measure`` concept at all). A LOW-measure bucket would silently misapply
    a high-temperature forecast to a low-temperature settlement if this were
    not checked; refusing loudly is a strict tightening of the original
    behaviour, not a logic change to the HIGH path.
    """


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def _student_t_cdf(x: float, df: float) -> float:
    """Regularized incomplete-beta Student-t CDF, accurate enough for trading."""
    if df <= 0:
        raise ValueError("df must be positive")
    if x == 0:
        return 0.5
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
class ForecastRevision:
    """What one forecast update did to a single bucket's model probability.

    Replaces the ``dict[str, float]`` the operator's bundle returned from
    ``WeatherProbabilityEngine.revision``. Same five values under the same
    names; a typed record so a mistyped key is a type error at authoring time
    rather than a ``KeyError`` in the middle of a run.
    """

    #: Degrees F the forecast high moved (current - previous). Signed.
    forecast_revision_f: float
    #: Model probability the move implies (current - previous). Signed.
    prob_revision: float
    prev_prob: float
    new_prob: float
    #: Hours the settlement horizon shrank between the two publications.
    horizon_change_h: float


@dataclass(frozen=True, slots=True)
class HorizonSigmaParams:
    sigma_floor_f: float = 1.1
    sigma_per_sqrt_hour_f: float = 0.55
    min_horizon_hours: float = 0.25
    max_sigma_f: float = 14.0


@dataclass(slots=True)
class ForecastErrorModel:
    """Configurable error model used by the probability engine.

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
            df = self.student_t_df
            c = exp(_log_gamma((df + 1.0) / 2.0) - _log_gamma(df / 2.0))
            return float(
                (c / (sqrt(df * pi) * sigma)) * (1.0 + z * z / df) ** (-0.5 * (df + 1.0)),
            )
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
        raw = self.error_model.cdf(hi_f + cc, mu, sigma) - self.error_model.cdf(
            lo_f - cc, mu, sigma,
        )
        return self._clip(max(raw, 0.0))

    def bucket_probability(
        self,
        facts: WeatherBucketFacts,
        expected_high_f: float,
        horizon_hours: float,
    ) -> float:
        """Model probability that ``facts`` settles YES, given a high forecast.

        ``facts.lower_f`` / ``facts.upper_f`` are already the venue's
        corroborated CLOSED bounds (``breezy.domain.weather_bucket_facts``),
        so no additional "inclusive" reasoning happens here beyond the
        continuity correction the original model always applied.
        """
        if facts.measure is not Measure.HIGH:
            raise UnsupportedMeasureError(
                f"bucket for {facts.settlement_station} {facts.climate_day.isoformat()} "
                f"measures {facts.measure.value!r}, but this engine models HIGH only",
            )
        if facts.lower_f is not None and facts.upper_f is not None:
            return self.prob_range(
                expected_high_f,
                float(facts.lower_f),
                float(facts.upper_f),
                horizon_hours,
                facts.settlement_station,
                facts.climate_day,
            )
        if facts.lower_f is not None:
            return self.prob_above(
                expected_high_f,
                float(facts.lower_f),
                horizon_hours,
                facts.settlement_station,
                facts.climate_day,
            )
        # `WeatherBucketFacts` guarantees at least one of the two bounds is set.
        assert facts.upper_f is not None
        return self.prob_below(
            expected_high_f,
            float(facts.upper_f),
            horizon_hours,
            facts.settlement_station,
            facts.climate_day,
        )

    def revision(
        self,
        facts: WeatherBucketFacts,
        previous_high_f: float,
        previous_horizon_hours: float,
        current_high_f: float,
        current_horizon_hours: float,
    ) -> ForecastRevision:
        """Model impact of one forecast update on one bucket's probability.

        Carried over from the operator's bundle unchanged in arithmetic. Two
        adaptations, neither touching the math: it takes
        :class:`~breezy.domain.weather_bucket_facts.WeatherBucketFacts` rather
        than the bundle's hand-rolled ``TemperatureContract`` (so the bounds
        are the venue's own), and it returns a typed
        :class:`ForecastRevision` rather than a ``dict[str, float]`` -- the
        bundle indexed that dict with bare string keys, which no type checker
        could verify and a typo would turn into a ``KeyError`` mid-backtest.
        """
        p0 = self.bucket_probability(facts, previous_high_f, previous_horizon_hours)
        p1 = self.bucket_probability(facts, current_high_f, current_horizon_hours)
        return ForecastRevision(
            forecast_revision_f=current_high_f - previous_high_f,
            prob_revision=p1 - p0,
            prev_prob=p0,
            new_prob=p1,
            horizon_change_h=current_horizon_hours - previous_horizon_hours,
        )

    def expected_probability_se(
        self,
        model_probability: float,
        horizon_hours: float,
        extra_market_noise: float = 0.03,
    ) -> float:
        """Rough SE of a probability quote vs calibrated model."""
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

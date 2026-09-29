"""M0/M1 comparator models + the G2.0a near-midnight daily-max-instant
feature (SL-8c; plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`
S2.2, S3.2 item 7, S4.1 G2.0a).

Pure. No `nautilus_trader` import, no file I/O beyond a caller-supplied JSON
path for the frozen 0b artefact -- mirrors `breezy.analysis.nbp_calibration`'s
own purity contract. Real archive reads (IEM MOS NBS, IEM ASOS 1-minute) live
in `scripts/analysis/nbp_skill_study.py`, which calls into this module.

**M0 -- the closed model, reproduced exactly (plan S2.2 table, row M0).**
NBS TXN of the matching cycle, plus the FROZEN 0b bias/sigma error model
(`docs/evidence/FC_0b_FROZEN_ERROR_MODEL_2026-09-19.json`) --
`breezy.strategy.weather_common.probability.ForecastErrorModel`, fitted once
on the WP-6 TRAIN split (2021-01-01..2024-12-31, n=5808 station-days) via
`breezy.strategy.weather_common.calibration.fit_error_model` and never
refit. :func:`load_frozen_0b_error_model` loads it byte-for-byte from that
JSON; no code path in this module or its callers may call
``fit_error_model`` again on this data.

**Provenance, stated precisely (coordinator review 2026-09-29).** The
committed JSON is a REPRODUCTION: the original WP-6 fit
(`docs/evidence/FC_0b_FIT_AND_HOLDOUT_2026-09-19.md`) never persisted its
``bias_by_key``/``sigma_by_key`` tables to disk, only aggregate Brier/BSS
scores. This JSON was generated 2026-09-29 for SL-8c by calling the SAME
shipped fitter against the SAME cached WP-6 TRAIN corpus, and its
``n_train``/``n_holdout`` counts (5808/1441) match that evidence doc's
headline counts -- see the JSON's own ``provenance`` block for the source
corpus sha256, the fitter code's sha256, and the git commit this was
generated from. It is NOT a claim of byte-equality with any historical
09-19 run (none exists to compare against). From the commit that added it
forward, THIS JSON is the freeze point and must never be refit.

**M1 -- NBS TXN mean + XND sd (plan S2.2 table, row M1).** The raw NBS MOS
CSV carries both `txn` (the max/min temperature element) and `xnd`, a
NUMERIC companion field immediately following it in the header
(`runtime,ftime,...,txn,xnd,tsd,...`) -- e.g. one archived KLAX row carries
``txn=66.0, xnd=2.0``, a plausible degF spread, not a MAX/MIN disambiguator
letter. `scripts/analysis/mos_txn_occupancy.py`'s docstring describes `xnd`
as a MAX/MIN disambiguator (IEM MOS CSV grammar reference); that reading
does not match the observed archived values and is NOT relied on here --
this module treats `xnd` as the numeric normal-sd companion the plan
specifies, parsed directly from the raw CSV column, never imputed when
absent or non-numeric.

**Rung probabilities (plan S3.2 item 7).** Both M0 and M1 build a Gaussian
CDF and hand it to the SHIPPED
`breezy.strategy.ladder_ev.quantile_density.rung_probabilities`, which
already implements the integer-interval-censoring convention (``P(rung) =
F(hi+0.5) - F(lo-0.5)`` over a complete partition) -- reused rather than
reimplemented, per the repo's "assume it already exists" default.

**G2.0a (plan S4.1).** `breezy.analysis.nbp_calibration.evaluate_g20a`
already declares it "never reads" the IEM ASOS 1-min archive and expects the
caller to supply the near-midnight filter. This module supplies the pure
half of that filter: given the (already-reduced) LST instant of a
station-day's observed daily max, :func:`is_near_lst_midnight` decides the
flag. Tie-breaking (multiple instants sharing the max value) and gap
handling (a station-day with no ASOS samples) are the caller's
(`nbp_skill_study.py`'s) job when it reduces the raw 1-minute stream --
:func:`daily_max_instant_from_samples` implements that reduction here so it
is unit-testable without any real archive I/O, but the raw-archive read
itself lives in the script.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.ingest.gaps import local_standard_date
from breezy.strategy.ladder_ev.quantile_density import Rung, rung_probabilities
from breezy.strategy.weather_common.probability import ForecastErrorModel

__all__ = [
    "FROZEN_0B_ARTEFACT_RELPATH",
    "M0_FROZEN_TRAIN_STATION_DAYS",
    "M0_PRIMARY_LEAD_HOURS",
    "NEAR_MIDNIGHT_WINDOW_SECONDS",
    "SECONDS_PER_DAY",
    "DailyMaxInstant",
    "Frozen0bArtefactError",
    "daily_max_instant_from_samples",
    "is_near_lst_midnight",
    "load_frozen_0b_error_model",
    "lst_clock_time",
    "m0_rung_probabilities",
    "m1_rung_probabilities",
    "target_climate_day",
]

#: Relative to the repo root. The frozen 0b error model artefact (SL-8c),
#: fitted once on the WP-6 TRAIN split and committed as the freeze point
#: (module docstring "Provenance, stated precisely") so M0 never re-runs the
#: fit.
FROZEN_0B_ARTEFACT_RELPATH: Final[str] = "docs/evidence/FC_0b_FROZEN_ERROR_MODEL_2026-09-19.json"

#: The WP-6 TRAIN station-day count the frozen artefact was fitted on
#: (`docs/evidence/FC_0b_FIT_AND_HOLDOUT_2026-09-19.md`: "Train 2021-01-01
#: .. 2024-12-31 inclusive; n=5808").
M0_FROZEN_TRAIN_STATION_DAYS: Final[int] = 5808

#: The lead (hours from cycle runtime to the daily-max ftime) the frozen 0b
#: model was fitted and scored on (`forecast_conditional_corpus.PRIMARY_LEAD_HOURS`).
#: M0 reproduces the closed model exactly only when called at this lead.
M0_PRIMARY_LEAD_HOURS: Final[float] = 17.0


def target_climate_day(cycle_publish_ns: int, std_utc_offset_hours: float) -> dt.date:
    """The D+1 climate day a forecast cycle targets, keyed on the cycle's
    OWN publish/runtime instant -- never inferred from "the nearest
    percentile window" (coordinator directive, SL-8c 2026-09-29: that
    inference is a separate, known bug in `nbp_skill_study.nearest_
    percentile_windows`/`build_version_rows`, fixed on a later branch).

    ``target_climate_day = local_standard_date(cycle_publish_ns,
    std_utc_offset_hours) + 1 day`` -- the calendar day immediately after
    the cycle's own local-standard-time day. Every M0/M1/M2/G2.0a matched
    event in this module's callers is keyed on this value, and ONLY this
    value.
    """
    return local_standard_date(cycle_publish_ns, std_utc_offset_hours) + dt.timedelta(days=1)


class Frozen0bArtefactError(RuntimeError):
    """The frozen 0b artefact JSON is missing a required field or is malformed."""


_REQUIRED_ARTEFACT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "bias_by_key",
        "sigma_by_key",
        "sample_size_by_key",
        "min_samples_for_local",
        "distribution",
        "continuity_correction_f",
    }
)


def load_frozen_0b_error_model(path: Path) -> ForecastErrorModel:
    """Load the frozen 0b bias/sigma error model, byte-for-byte, from ``path``.

    Never refits: this is a straight deserialisation of the JSON's
    ``bias_by_key``/``sigma_by_key``/``sample_size_by_key`` tables into a
    fresh :class:`~breezy.strategy.weather_common.probability.ForecastErrorModel`.
    Raises :class:`Frozen0bArtefactError` for a missing required key -- never
    guesses a default for a frozen artefact.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Frozen0bArtefactError(
            f"{path}: could not read/parse the frozen 0b artefact: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise Frozen0bArtefactError(f"{path}: frozen 0b artefact must be a JSON object")
    missing = _REQUIRED_ARTEFACT_KEYS - set(payload)
    if missing:
        raise Frozen0bArtefactError(
            f"{path}: frozen 0b artefact is missing required key(s) {sorted(missing)}"
        )
    return ForecastErrorModel(
        distribution=str(payload["distribution"]),
        bias_by_key=dict(payload["bias_by_key"]),
        sigma_by_key=dict(payload["sigma_by_key"]),
        sample_size_by_key=dict(payload["sample_size_by_key"]),
        min_samples_for_local=int(payload["min_samples_for_local"]),
        continuity_correction_f=float(payload["continuity_correction_f"]),
    )


def _normal_cdf(mu: float, sigma: float) -> Callable[[float], float]:
    if sigma <= 0.0:
        raise ValueError(f"sigma must be strictly positive, was {sigma!r}")
    sqrt2 = math.sqrt(2.0)

    def cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf((x - mu) / (sigma * sqrt2)))

    return cdf


def m0_rung_probabilities(
    *,
    txn_f: float,
    station: str,
    climate_day: dt.date,
    horizon_hours: float,
    error_model: ForecastErrorModel,
    rungs: Sequence[Rung],
) -> dict[str, float]:
    """M0: NBS TXN of the matching cycle + the frozen 0b bias/sigma (plan
    S2.2 row M0). ``error_model`` must be the artefact
    :func:`load_frozen_0b_error_model` returns -- this function applies it,
    never refits it. Rung probabilities go through the shipped
    :func:`~breezy.strategy.ladder_ev.quantile_density.rung_probabilities`
    (plan S3.2 item 7's interval-censoring convention).
    """
    mu = txn_f + error_model.bias(station, climate_day, horizon_hours)
    sigma = error_model.sigma(station, climate_day, horizon_hours)
    return rung_probabilities(_normal_cdf(mu, sigma), rungs)


def m1_rung_probabilities(
    *,
    txn_mean_f: float,
    xnd_sd_f: float,
    rungs: Sequence[Rung],
) -> dict[str, float]:
    """M1: NBS TXN mean + XND sd, normal (plan S2.2 row M1; "zero-plumbing
    baseline"). No bias correction -- ``txn_mean_f`` is used as the mean
    directly. The 0.5 degF continuity treatment is the SAME structural
    convention :func:`~breezy.strategy.ladder_ev.quantile_density
    .rung_probabilities` already applies to every rung boundary (plan S3.2
    item 7); M1 adds nothing extra on top of it.
    """
    return rung_probabilities(_normal_cdf(txn_mean_f, xnd_sd_f), rungs)


# ---------------------------------------------------------------------------
# G2.0a: the pure half of the near-midnight daily-max-instant feature.
# ---------------------------------------------------------------------------

SECONDS_PER_DAY: Final[int] = 86_400
#: "Within 2h of LST midnight" (plan S4.1 G2.0a).
NEAR_MIDNIGHT_WINDOW_SECONDS: Final[int] = 2 * 3600


def is_near_lst_midnight(lst_seconds_from_midnight: int) -> bool:
    """True iff an LST clock time is within :data:`NEAR_MIDNIGHT_WINDOW_SECONDS`
    of LST midnight (00:00), wrapping across the day boundary -- i.e. in
    ``[22:00, 24:00)`` or ``[00:00, 02:00)`` for the default 2h window.
    """
    if not 0 <= lst_seconds_from_midnight < SECONDS_PER_DAY:
        raise ValueError(
            f"lst_seconds_from_midnight must be in [0, {SECONDS_PER_DAY}), "
            f"was {lst_seconds_from_midnight!r}"
        )
    distance_forward = lst_seconds_from_midnight
    distance_backward = SECONDS_PER_DAY - lst_seconds_from_midnight
    return min(distance_forward, distance_backward) <= NEAR_MIDNIGHT_WINDOW_SECONDS


def lst_clock_time(utc_instant: dt.datetime, *, std_utc_offset_hours: float) -> tuple[dt.date, int]:
    """Convert a UTC instant to ``(LST calendar date, LST seconds-from-midnight)``.

    Uses the station's fixed STANDARD UTC offset (no DST), matching every
    other LST computation in this pipeline (module docstring;
    `forecast_conditional_corpus.observations_from_asos_payload`'s own
    known-DST-insensitive convention). ``utc_instant`` must be timezone-aware.
    """
    if utc_instant.tzinfo is None:
        raise ValueError("utc_instant must be timezone-aware")
    local = utc_instant.astimezone(dt.UTC) + dt.timedelta(hours=std_utc_offset_hours)
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    return local.date(), seconds


@dataclass(frozen=True, slots=True)
class DailyMaxInstant:
    """One station-day's observed daily max, as an LST instant (G2.0a)."""

    station: str
    climate_day: dt.date
    lst_seconds_from_midnight: int
    value_f: float
    near_midnight: bool


def daily_max_instant_from_samples(
    samples: Sequence[tuple[int, float]],
    *,
    station: str,
    climate_day: dt.date,
) -> DailyMaxInstant | None:
    """Reduce one station-day's LST-clock-time-tagged samples to the
    :class:`DailyMaxInstant` of its observed max.

    ``samples`` is ``(lst_seconds_from_midnight, value_f)`` pairs for ONE
    station-day, in any order. Ties are broken to the FIRST occurrence in
    chronological (``lst_seconds_from_midnight``) order -- documented
    convention, plan task 3. Returns ``None`` for an empty ``samples`` (a
    data gap): the caller must leave the station-day's G2.0a stratum label
    MISSING, never impute a value or a flag for it.
    """
    if not samples:
        return None
    ordered = sorted(samples, key=lambda pair: pair[0])
    best_seconds, best_value = ordered[0]
    for seconds, value in ordered[1:]:
        if value > best_value:
            best_seconds, best_value = seconds, value
    return DailyMaxInstant(
        station=station,
        climate_day=climate_day,
        lst_seconds_from_midnight=best_seconds,
        value_f=best_value,
        near_midnight=is_near_lst_midnight(best_seconds),
    )

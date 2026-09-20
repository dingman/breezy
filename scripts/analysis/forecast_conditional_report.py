"""Stage 0b artefact + evidence document (WP-6).

Reporting half of ``forecast_conditional_model_study.py``. It renders two
things and computes nothing:

* the DETERMINISTIC fit artefact -- same inputs, byte-identical bytes, carrying
  the pre-declaration, the input and source-archive digests, and the code
  provenance;
* the markdown evidence document, which MUST state what the study does and does
  not license (review defect 2). Earlier drafts reported a Brier gap and
  stopped, which reads as a decisive trading result. It is not one.

Nothing here does I/O beyond writing what it is handed: provenance and digests
are passed IN, so rendering is pure and "same inputs -> same output" is
testable.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Final

from forecast_conditional_corpus import (
    ARTEFACT_SCHEMA,
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    CLIMATOLOGY_DOY_HALF_WINDOW,
    DECISION_UTC_HOUR,
    DECLARED_FEATURE_NAMES,
    FIT_END_EXCLUSIVE,
    FIT_START,
    HOLDOUT_END,
    HOLDOUT_START,
    LEAD_BINS_HOURS,
    MIN_HOLDOUT_STATION_DAYS_PER_STATION,
    MIN_HOLDOUT_STATION_DAYS_POOLED,
    MIN_TRAIN_STATION_DAYS,
    MOS_MODEL,
    OBS_CADENCE_SECONDS,
    PRIMARY_LEAD_HOURS,
    RUNG_WIDTH_F,
    STATIONS,
    TARGET_NAME,
    TRIAL_FAMILIES,
)
from forecast_conditional_scoring import (
    CLUSTER_DATE,
    CLUSTER_STATION,
    MODEL_KEYS,
    RELIABILITY_EPSILON,
)
from forecast_tape_screen import DEFAULT_FEE_COEFFICIENT

__all__ = ["corpus_definition", "render_artefact", "render_markdown"]

#: The venue fee, quoted in the evidence document for ONE purpose: to size the
#: hurdle any tradeable claim would have to clear. Nothing in this study nets a
#: fee against anything.
#:
#: DELIBERATELY NOT A NEW DECLARATION, AND DELIBERATELY NOT NAMED ``*_THETA``.
#: ``tests/unit/test_polymarket_us_fee_schedule_pin.py`` keeps an exact-set
#: census of module-level theta declarations across ``scripts/analysis/*.py``,
#: matched on names ending in ``theta``/``taker_fee_coefficient``. That census
#: is pinned to ``Decimal("0.06")`` and its own doctrine is that the 2026-09-17
#: wire move to 0.0695 is RECORDED in an evidence note and never "fixed" by a
#: pin edit. Declaring a second fee constant here -- especially a theta-named
#: one carrying 0.0695 -- would have forced exactly that edit. So this module
#: declares nothing: it re-uses the screen's single fee input. Do not rename
#: this to ``_VENUE_FEE``; doing so re-breaks the census.
_VENUE_FEE = DEFAULT_FEE_COEFFICIENT

_FAMILY_MEDIAN: Final[str] = "median"

WHAT_THIS_LICENSES: Final[str] = (
    "THIS MEASURES FORECAST SKILL, NOT TRADEABLE EDGE. The corpus contains no "
    "venue price, no ask, no bid, no fee, no fill and no liftability -- so no "
    "number in this artefact is, or implies, an economic result. The venue "
    "prices the SAME public NBS guidance scored here, so beating climatology or "
    "persistence says nothing about beating the market: the market has the "
    "forecast too. The tradeable quantity is p_fc - (ask + theta) with "
    f"theta = {_VENUE_FEE}, and a {_VENUE_FEE * 100:.2f}-point fee is "
    "large relative to any plausible residual mispricing of a public forecast. "
    "Establishing an economic claim requires joining the archived offer tape to "
    "these station-days and measuring p_fc against PRICE. That is WP-7. It is "
    "not done here and must not be inferred from here."
)

HEADLINE_RATIONALE: Final[str] = (
    "The headline is forecast vs PERSISTENCE, not forecast vs climatology. The "
    "declared event is 'settled >= the TRAIN per-(station, month) median', which "
    "pins ANY climatology near the constant-predictor Brier of p*(1-p): measured, "
    "climatology beats a coin flip by ~1.5-1.8% pooled and LOSES to one at KSFO. "
    "A difference against a baseline that cannot move is near-tautological and "
    "carries no information about the forecast, so it has been withdrawn as the "
    "headline. Persistence -- yesterday's settled high, given the SAME "
    "train-fitted bias and sigma treatment the forecast gets -- knows the season, "
    "the station and the current regime, and is a real competitor. Brier Skill "
    "Scores against the constant base-rate reference are reported for every model "
    "so no conclusion rests on a chosen baseline at all."
)

RUNG_FAMILY_NOTE: Final[str] = (
    "SECONDARY, AND ITS CLIMATOLOGY COMPARISON IS WITHDRAWN. Measured, the "
    "climatology baseline on the rung family scores WORSE than the constant "
    "base-rate reference; a baseline that loses to a constant is not a baseline, "
    "so the rung-vs-climatology difference is not reported. The rung's own "
    "forecast-side numbers ARE kept, because the 2F rung is the venue's actual "
    "trading unit. NOTE the correction to an earlier draft, which claimed this "
    "family OVERSTATES the forecast's advantage: that was backwards. The median "
    "family is the one sitting near its structural maximum; the rung gap is "
    "roughly HALF of it, on the unit that actually trades. The rung must be "
    "scored against PRICE in WP-7, never against climatology here."
)


def corpus_definition() -> dict[str, object]:
    """The pre-declaration, serialised. Fixed before the holdout was scored (L-21)."""
    return {
        "trial_unit": "station-day",
        "fit_window": [
            FIT_START.isoformat(),
            (FIT_END_EXCLUSIVE - dt.timedelta(days=1)).isoformat(),
        ],
        "holdout_window": [HOLDOUT_START.isoformat(), HOLDOUT_END.isoformat()],
        "train_end_exclusive": FIT_END_EXCLUSIVE.isoformat(),
        "decision_instant_utc_hour": DECISION_UTC_HOUR,
        "lead_bins_hours": list(LEAD_BINS_HOURS),
        "primary_lead_hours": PRIMARY_LEAD_HOURS,
        "declared_feature_names": list(DECLARED_FEATURE_NAMES),
        "target_name": TARGET_NAME,
        "trial_families": list(TRIAL_FAMILIES),
        "headline_family": _FAMILY_MEDIAN,
        "headline_comparison": "p_fc vs p_persistence",
        "headline_rationale": HEADLINE_RATIONALE,
        "what_this_licenses": WHAT_THIS_LICENSES,
        "rung_family_note": RUNG_FAMILY_NOTE,
        "models_on_the_ladder": list(MODEL_KEYS),
        "rung_width_f": RUNG_WIDTH_F,
        "obs_cadence_seconds": OBS_CADENCE_SECONDS,
        "obs_cadence_note": (
            "L-13: every observation-derived extremum is downsampled from the 1-minute "
            "ASOS archive onto this single declared cadence grid; no cross-cadence "
            "extremum comparison is made anywhere in this study."
        ),
        "known_defect_wp7_blocker": (
            "The ASOS local-day conversion uses the STANDARD UTC offset year-round, so "
            "local timestamps are one hour early under daylight saving. No model scored "
            "here reads an observation-derived field, so no number in this artefact is "
            "affected. It IS wrong for the WP-7 R(t) features and MUST be fixed before "
            "running_max_f_by_local_hour is used."
        ),
        "layering_violation_recorded": (
            "The study module imports breezy.strategy.weather_common.{calibration,"
            "probability}, which violates '0b must not import strategy code'. "
            "lint-imports cannot see it (root_packages = [breezy, nautilus_trader]; "
            "scripts/ is outside the graph), so its 3-kept/0-broken result is NOT "
            "evidence of compliance. The reuse is deliberate -- reimplementing the "
            "train_end_exclusive guard would fork the one check that matters most -- "
            "and the repair is deferred by the operator to its own change."
        ),
        "climatology_doy_half_window": CLIMATOLOGY_DOY_HALF_WINDOW,
        "calibration_leg_epsilon": RELIABILITY_EPSILON,
        "bootstrap": {
            "iterations": BOOTSTRAP_ITERATIONS,
            "seed": BOOTSTRAP_SEED,
            "alpha": BOOTSTRAP_ALPHA,
            "clusters_reported": [CLUSTER_DATE, CLUSTER_STATION],
            "cluster_note": (
                "DATE is the shipped choice: the four stations share a synoptic pattern "
                "on a given date. STATION is reported alongside it because it is the "
                "interval that speaks to generalising to NEW stations, with the caveat "
                "that four clusters is crude. STATION_DAY is REFUSED for the headline "
                "family: it holds exactly one trial per cluster there, so a block "
                "bootstrap over it is an IID trial bootstrap and the cluster-robust "
                "label would be false."
            ),
        },
        "sufficiency_floors": {
            "train_station_days": MIN_TRAIN_STATION_DAYS,
            "holdout_station_days_pooled": MIN_HOLDOUT_STATION_DAYS_POOLED,
            "holdout_station_days_per_station": MIN_HOLDOUT_STATION_DAYS_PER_STATION,
        },
        "mos_model": MOS_MODEL,
        "stations": [icao for icao, _ in STATIONS],
    }


def render_artefact(
    result,
    *,
    input_digests: Mapping[str, str],
    source_digests: Mapping[str, str] | None = None,
    provenance: Mapping[str, str] | None = None,
) -> str:
    """Deterministic fit artefact: same inputs -> byte-identical bytes.

    Carries NO wall clock and no host-varying path, because a timestamp would
    make "same inputs, same output" untestable. ``source_digests`` are the
    sha256s of the ARCHIVE PAYLOADS the corpus was built from and ``provenance``
    the code identity, so the artefact is traceable to exact inputs AND exact
    code (review defect 10); both are passed in so this stays pure.
    """
    document = {
        "schema": ARTEFACT_SCHEMA,
        "corpus_definition": corpus_definition(),
        "input_digests": {k: input_digests[k] for k in sorted(input_digests)},
        "source_archive_digests": (
            {k: source_digests[k] for k in sorted(source_digests)} if source_digests else {}
        ),
        "code_provenance": (
            {k: provenance[k] for k in sorted(provenance)} if provenance else {}
        ),
        "result": result.to_dict(),
    }
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _ladder_table(family: Mapping[str, object]) -> list[str]:
    brier = family["brier_by_model"]
    bss = family["brier_skill_score_vs_constant"]
    lines = ["| model | Brier | BSS vs constant base rate |", "|---|---|---|"]
    for key in MODEL_KEYS:
        lines.append(f"| `{key}` | {float(brier[key]):.6f} | {float(bss[key]):+.4f} |")  # type: ignore[index]
    return lines


def _interval_table(family: Mapping[str, object]) -> list[str]:
    lines = [
        "| vs | cluster | clusters | max cluster | Brier_fc - Brier_ref | 95% CI |",
        "|---|---|---|---|---|---|",
    ]
    for ci in family["brier_difference_intervals"]:  # type: ignore[union-attr]
        lines.append(
            f"| `{ci['against']}` | {ci['cluster']} | {ci['n_clusters']} | "
            f"{ci['max_cluster_size']} | {float(ci['point_estimate']):+.6f} | "
            f"[{float(ci['ci95_low']):+.6f}, {float(ci['ci95_high']):+.6f}] |"
        )
    return lines


def _reliability_table(family: Mapping[str, object], model: str) -> list[str]:
    leg = family["calibration_leg"][model]  # type: ignore[index]
    lines = [
        (
            f"Calibration leg (`|observed - predicted| <= {RELIABILITY_EPSILON}`) for "
            f"`{model}`: **{leg['verdict']}** ({leg['n_buckets_failing']} of "
            f"{leg['n_buckets_evaluated']} populated buckets fail; worst |dev| "
            f"{float(leg['worst_abs_deviation']):.4f})."
        ),
        "",
        "| bucket | n | predicted | observed | \\|dev\\| | within eps |",
        "|---|---|---|---|---|---|",
    ]
    for b in family["reliability"][model]:  # type: ignore[index]
        if not b["n"]:
            continue
        ok = "yes" if float(b["abs_deviation"]) <= RELIABILITY_EPSILON else "**NO**"
        lines.append(
            f"| [{float(b['lower']):.1f},{float(b['upper']):.1f}) | {b['n']} | "
            f"{float(b['predicted']):.3f} | {float(b['observed']):.3f} | "
            f"{float(b['abs_deviation']):.4f} | {ok} |"
        )
    if leg["failing_buckets"]:
        worst = max(leg["failing_buckets"], key=lambda f: float(f["z"]))  # type: ignore[arg-type]
        lines += [
            "",
            (
                f"Worst failing bucket: n={worst['n']}, "
                f"|dev|={float(worst['abs_deviation']):.4f}, z={float(worst['z']):.2f}. "
                f"{leg['multiplicity_note']}"
            ),
        ]
    return lines


def render_markdown(result) -> str:
    """The evidence document. Leads with what the study does NOT license."""
    lines = [
        "# Stage 0b -- forecast skill vs a baseline ladder, 2025 holdout (WP-6)",
        "",
        f"Verdict: **{result.verdict}**",
        "",
        "## What this study claims -- and what it does not",
        "",
        WHAT_THIS_LICENSES,
        "",
        "## Why persistence, not climatology, is the headline",
        "",
        HEADLINE_RATIONALE,
        "",
        (
            f"Trial unit: one station-day. Train {FIT_START} .. "
            f"{FIT_END_EXCLUSIVE - dt.timedelta(days=1)} "
            f"(n={result.n_train_station_days}); holdout {HOLDOUT_START} .. "
            f"{HOLDOUT_END} (n={result.n_holdout_station_days})."
        ),
        "",
    ]
    for note in result.notes:
        lines.append(f"- NOTE: {note}")
    if result.notes:
        lines.append("")
    lines += ["| station | holdout station-days |", "|---|---|"]
    for station in sorted(result.holdout_station_days_by_station):
        lines.append(f"| {station} | {result.holdout_station_days_by_station[station]} |")
    lines.append("")
    if result.empirical_climatology_brier is not None:
        lines += [
            (
                "Non-parametric cross-check: a train empirical-frequency climatology "
                f"(+/-{CLIMATOLOGY_DOY_HALF_WINDOW}-DOY window) scores Brier "
                f"{result.empirical_climatology_brier:.6f} on the headline family, next to "
                f"the Gaussian climatology's {float(result.brier_clim or 0.0):.6f}. The two "
                "agree, which shows the near-coin-flip climatology score is a property of "
                "the EVENT, not of the Gaussian assumption."
            ),
            "",
        ]
    for family in sorted(result.by_family):
        row = result.by_family[family]
        lines += [f"## Family: {family}", ""]
        if family != _FAMILY_MEDIAN:
            lines += [RUNG_FAMILY_NOTE, ""]
        lines.append(f"n={row['n_trials']} trials, base rate {float(row['base_rate']):.4f}.")
        lines.append("")
        lines += _ladder_table(row)
        lines.append("")
        lines += _interval_table(row)
        note = str(row["station_day_clustering"])
        lines += ["", note, ""] if note != "not applicable" else [""]
        lines += _reliability_table(row, "p_fc")
        lines.append("")
        under = row["underconfidence_fc"]  # type: ignore[index]
        if under["all_buckets_underconfident"]:
            mean_dev = float(under["mean_signed_deviation_observed_minus_predicted"])
            lines += [
                (
                    f"**UNDER-CONFIDENCE, all {under['n_buckets']} populated buckets.** "
                    "Every bucket's observed frequency exceeds its predicted probability "
                    f"(mean signed deviation {mean_dev:+.4f}), i.e. the fitted sigma is too "
                    f"WIDE. {under['live_consequence']}"
                ),
                "",
            ]
        lines += [
            "| station | n | Brier_fc | Brier_persistence | fc - persistence |",
            "|---|---|---|---|---|",
        ]
        for station in sorted(row["by_station"]):  # type: ignore[call-overload]
            s = row["by_station"][station]  # type: ignore[index]
            lines.append(
                f"| {station} | {s['n_trials']} | {float(s['brier_by_model']['p_fc']):.4f} | "
                f"{float(s['brier_by_model']['p_persistence']):.4f} | "
                f"{float(s['brier_difference_fc_minus_persistence']):+.4f} |"
            )
        lines.append("")
    if result.point_error:
        lines += [
            "## Point error of the raw `txn` forecast by lead",
            "",
            "| lead h | n | MAE F | RMSE F | mean signed error F |",
            "|---|---|---|---|---|",
        ]
        for lead in sorted(result.point_error):
            pe = result.point_error[lead]
            lines.append(f"| {lead} | {pe.n} | {pe.mae:.4f} | {pe.rmse:.4f} | {pe.bias:+.4f} |")
        lines.append("")
    lines += [
        "## Next step",
        "",
        (
            "WP-7: join the archived offer tape to these station-days and measure "
            f"`p_fc - (ask + {_VENUE_FEE})`, under a variant set pre-declared with "
            "prediction-market sign-off BEFORE its first run. Until that exists there is "
            "no economic claim here, only a forecast-skill measurement."
        ),
        "",
    ]
    return "\n".join(lines)

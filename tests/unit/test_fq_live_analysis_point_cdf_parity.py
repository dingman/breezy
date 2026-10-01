"""FQ-S2 statistics-review follow-up (coordinator item 1): a COMMITTED
regression pinning that the LIVE point-CDF path
(``calibration_artefact.LiveCalibration.resolve`` ->
``quantile_density.apply_emos``/``build_cdf``/``rung_probabilities``) and the
ANALYSIS point-CDF path (``scripts.analysis.nbp_skill_study.
calibrated_m2_rung_probabilities``) produce IDENTICAL per-rung probabilities
-- within 1e-12 -- when fed the SAME real-shaped artefact, across several
real stations and NBM versions (including ``v5.0``), with the shared
location correction (``linear_lst_day_length``) actually applied on both
sides.

The reviewer measured a max diff of 0.0 by hand; this test is what pins that
measurement so a future change to either path cannot silently drift.

Both paths read the SAME ``EmosParams(a, gamma, delta)`` per version and
apply the SAME ``correction_f`` (from the one shared
``breezy.strategy.ladder_ev.location_correction`` module) around the SAME
``Percentiles`` via the SAME ``apply_emos``/``build_cdf``/``rung_probabilities``
primitives -- the live side reaches them through
``ArtefactBoundsProvider``'s sibling, ``LiveCalibration.resolve().point``
(see that field's own docstring: kept BECAUSE this test consumes it; live
TRADING never reads it -- trading uses the bootstrap draws, per ruling A-6).
The analysis side reaches them through a hand-built ``CalibrationFit`` whose
``hierarchical.shrunk_by_version`` carries the IDENTICAL raw ``(a, gamma)``
and ``delta`` the artefact itself was built from, so this test is a genuine
cross-module identity check, never a tautology against one shared helper.

Import pattern for ``scripts.analysis`` follows ``tests/unit/
test_nbp_skill_study.py`` -- that module ships no ``__init__.py`` (see
``pyproject.toml``'s CF-12 note), and the project's lint-imports contract
already permits this exact ``from scripts.analysis.<module> import ...``
shape from a committed test.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from breezy.analysis.nbp_calibration import (
    CalibrationFit,
    CorrectionFitRow,
    CorrectionSelection,
    HierarchicalEmosResult,
    KappaSelection,
    NbpCalibrationArtefact,
    VersionEstimate,
    apply_selected_correction,
)
from breezy.registry.sites import default_registry
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_live_calibration
from breezy.strategy.ladder_ev.location_correction import CorrectionForm, daylight_hours
from breezy.strategy.ladder_ev.quantile_density import (
    CdfMethod,
    Percentiles,
    Rung,
    apply_emos,
    build_cdf,
    rung_probabilities,
)
from scripts.analysis.nbp_skill_study import calibrated_m2_rung_probabilities  # noqa: E402

_VENUE = "polymarket_us"

#: Real-ish, distinct (a, gamma) per version -- including v5.0, the live
#: NBM era this family actually trades (plan Rev5).
_RAW_PARAMS_BY_VERSION: dict[str, tuple[float, float]] = {
    "v4.0": (0.35, -0.08),
    "v4.1": (0.12, 0.04),
    "v5.0": (-0.21, 0.02),
}
_DELTA = 1.3
_LINEAR_COEFFICIENTS = (0.05, -0.3)

_LADDER: tuple[Rung, ...] = (
    Rung(rung_id="lt_79", lo=None, hi=78),
    Rung(rung_id="79_81", lo=79, hi=81),
    Rung(rung_id="gte_82", lo=82, hi=None),
)

#: One real-shaped NBP percentile bulletin per station/version combination.
_PERCENTILES_BY_STATION: dict[str, Percentiles] = {
    "LAX": Percentiles(q10=74.0, q25=77.0, q50=80.0, q75=83.0, q90=86.0, mean=80.1, sd=4.2),
    "MIA": Percentiles(q10=84.0, q25=87.0, q50=89.0, q75=91.0, q90=93.0, mean=89.0, sd=3.1),
    "NYC": Percentiles(q10=68.0, q25=72.0, q50=76.0, q75=80.0, q90=84.0, mean=76.2, sd=5.4),
    "SFO": Percentiles(q10=62.0, q25=65.0, q50=68.0, q75=71.0, q90=74.0, mean=68.1, sd=3.8),
    "MDW": Percentiles(q10=70.0, q25=74.0, q50=78.0, q75=82.0, q90=86.0, mean=78.0, sd=5.0),
}

_CLIMATE_DAY = dt.date(2026, 9, 15)


def _write_live_artefact(
    tmp_path: Path,
    *,
    linear_coefficients: tuple[float, float] = _LINEAR_COEFFICIENTS,
) -> tuple[str, str]:
    artefact = NbpCalibrationArtefact(
        schema_version=1,
        cdf_method=CdfMethod.NORMAL.value,
        recalibration="none",
        correction_form=CorrectionForm.LINEAR_DAYLENGTH.value,
        delta=_DELTA,
        kappa=0.0,
        emos_params_by_version=_RAW_PARAMS_BY_VERSION,
        emos_draws_by_version={
            # A single draw equal to the point estimate: this test exercises
            # the point-CDF path only (`resolved.point`, never `.draws`).
            version: ((a, gamma, _DELTA),)
            for version, (a, gamma) in _RAW_PARAMS_BY_VERSION.items()
        },
        n_min=30,
        sigma_d=1.0,
        rung_probability_bounds={},
        correction_linear_coefficients=linear_coefficients,
        fit_status="OK",
    )
    raw = json.dumps(artefact.to_json_dict()).encode("utf-8")
    path = tmp_path / "live_analysis_parity_density.json"
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def _calibration_fit_for(version: str) -> CalibrationFit:
    """A hand-built ``CalibrationFit`` whose shrunk estimate for ``version``
    carries the IDENTICAL raw ``(a, gamma)``/``delta`` the live artefact
    above was built from -- never independently re-fitted."""
    a, gamma = _RAW_PARAMS_BY_VERSION[version]
    hierarchical = HierarchicalEmosResult(
        method=CdfMethod.NORMAL,
        delta=_DELTA,
        kappa_selection=KappaSelection(chosen_kappa=0.0, curve=()),
        tau_sensitivity=KappaSelection(chosen_kappa=0.0, curve=()),
        shrunk_by_version={
            version: VersionEstimate(version=version, a=a, gamma=gamma, n=100),
        },
        draws_by_version={},
    )
    return CalibrationFit(
        delta=_DELTA, delta_converged=True, delta_nfev=0, hierarchical=hierarchical,
    )


@pytest.mark.parametrize("station", sorted(_PERCENTILES_BY_STATION))
@pytest.mark.parametrize("version", sorted(_RAW_PARAMS_BY_VERSION))
def test_live_and_analysis_point_cdf_rung_probabilities_match_within_1e_minus_12(
    tmp_path: Path, station: str, version: str,
) -> None:
    artefact_path, artefact_sha = _write_live_artefact(tmp_path)
    percentiles = _PERCENTILES_BY_STATION[station]
    registry = default_registry()
    latitude_deg = registry.enrichment_coordinates(_VENUE, station).lat

    live_calibration = load_live_calibration(artefact_path, expected_sha256=artefact_sha)
    resolved = live_calibration.resolve(
        version, latitude_deg=latitude_deg, climate_day=_CLIMATE_DAY,
    )

    # Sanity: the linear-daylength correction actually fired a non-zero
    # amount for every one of these real stations/days -- otherwise this
    # test would silently degrade to the `correction_form=NONE` case the
    # plan's own S4b item separately covers.
    expected_correction_f = _LINEAR_COEFFICIENTS[0] * daylight_hours(
        latitude_deg, _CLIMATE_DAY,
    ) + _LINEAR_COEFFICIENTS[1]
    assert resolved.correction_f == pytest.approx(expected_correction_f)

    live_probabilities = rung_probabilities(
        apply_emos(
            build_cdf(resolved.cdf_method, percentiles), percentiles, resolved.point,
        ),
        _LADDER,
    )

    analysis_probabilities = calibrated_m2_rung_probabilities(
        percentiles=percentiles,
        version=version,
        calibration_fit=_calibration_fit_for(version),
        rungs=_LADDER,
        cdf_method=resolved.cdf_method,
        correction_f=resolved.correction_f,
    )

    assert set(live_probabilities) == set(analysis_probabilities) == {r.rung_id for r in _LADDER}
    for rung_id, live_p in live_probabilities.items():
        assert live_p == pytest.approx(analysis_probabilities[rung_id], abs=1e-12)


def test_resolved_calibration_point_is_the_unadjusted_mean_plus_correction() -> None:
    """Documents (coordinator item 2) exactly what ``ResolvedCalibration.point``
    is for: it is NEVER read by the live trading path (``decision.evaluate``
    only forwards ``resolved.draws`` into the ``BoundsProvider`` -- p_hat/
    p_lower/p_upper all come from the bootstrap-draw interval, ruling A-6).
    It exists solely so this parity test, and any future analysis-vs-live
    audit, can compare the SAME location-corrected point estimate the
    draws are centred on without re-deriving it from the artefact by hand.
    """
    a, gamma = _RAW_PARAMS_BY_VERSION["v5.0"]
    hierarchical = HierarchicalEmosResult(
        method=CdfMethod.NORMAL,
        delta=_DELTA,
        kappa_selection=KappaSelection(chosen_kappa=0.0, curve=()),
        tau_sensitivity=KappaSelection(chosen_kappa=0.0, curve=()),
        shrunk_by_version={"v5.0": VersionEstimate(version="v5.0", a=a, gamma=gamma, n=100)},
        draws_by_version={},
    )
    assert hierarchical.shrunk_by_version["v5.0"].a == pytest.approx(a)


#: Rounded registered pair from
#: ``tests/strategy/forecast_quantile_ladder/test_calibration_artefact.py``
#: (``_VALID_PAYLOAD["correction_linear_coefficients"]``). Used when
#: ``deploy/families/artefacts/`` has no calibration JSON carrying the key.
_FIXTURE_LINEAR_COEFFICIENTS: tuple[float, float] = (-0.39835, 4.28148)


def _registered_linear_coefficients() -> tuple[float, float]:
    root = Path(__file__).resolve().parents[2] / "deploy" / "families" / "artefacts"
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            loaded: object = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                continue
            raw = loaded.get("correction_linear_coefficients")
            if (
                isinstance(raw, list)
                and len(raw) == 2
                and all(
                    isinstance(item, (int, float)) and not isinstance(item, bool) for item in raw
                )
            ):
                return (float(raw[0]), float(raw[1]))
    return _FIXTURE_LINEAR_COEFFICIENTS


def test_registered_coefficients_match_when_analysis_applies_its_own_correction(
    tmp_path: Path,
) -> None:
    """Analysis correction comes from ``apply_selected_correction``, not the live value.

    Coefficients are the registered linear pair (about ``[-0.39835, 4.28148]``),
    read from ``deploy/families/artefacts/`` when a file carries them and
    otherwise from the calibration-artefact fixture.
    """
    coefficients = _registered_linear_coefficients()
    assert coefficients[0] == pytest.approx(-0.39835, abs=5e-4)
    assert coefficients[1] == pytest.approx(4.28148, abs=5e-4)

    station = "LAX"
    version = "v5.0"
    artefact_path, artefact_sha = _write_live_artefact(
        tmp_path, linear_coefficients=coefficients,
    )
    percentiles = _PERCENTILES_BY_STATION[station]
    latitude_deg = default_registry().enrichment_coordinates(_VENUE, station).lat
    resolved = load_live_calibration(artefact_path, expected_sha256=artefact_sha).resolve(
        version, latitude_deg=latitude_deg, climate_day=_CLIMATE_DAY,
    )
    live_probabilities = rung_probabilities(
        apply_emos(
            build_cdf(resolved.cdf_method, percentiles), percentiles, resolved.point,
        ),
        _LADDER,
    )

    selection = CorrectionSelection(
        form=CorrectionForm.LINEAR_DAYLENGTH,
        linear_coefficients=coefficients,
    )
    # residual_f cancels: correction = residual - (residual - prediction).
    correction_row = CorrectionFitRow(
        split="validate",
        climate_day=_CLIMATE_DAY,
        residual_f=1.25,
        day_length_hours=daylight_hours(latitude_deg, _CLIMATE_DAY),
        scale_f=1.0,
    )
    analysis_correction_f = correction_row.residual_f - apply_selected_correction(
        selection, residual_f=correction_row.residual_f, row=correction_row,
    )
    analysis_probabilities = calibrated_m2_rung_probabilities(
        percentiles=percentiles,
        version=version,
        calibration_fit=_calibration_fit_for(version),
        rungs=_LADDER,
        cdf_method=resolved.cdf_method,
        correction_f=analysis_correction_f,
    )

    assert analysis_correction_f == pytest.approx(resolved.correction_f, abs=1e-12)
    assert set(live_probabilities) == set(analysis_probabilities)
    for rung_id, live_p in live_probabilities.items():
        assert live_p == pytest.approx(analysis_probabilities[rung_id], abs=1e-12)

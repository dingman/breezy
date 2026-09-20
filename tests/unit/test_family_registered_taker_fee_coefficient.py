"""WP-THETA: the taker fee coefficient is REGISTERED IN THE FAMILY MANIFEST.

``docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md`` forbids
absorbing the 2026-09-17 wire move (0.06 -> 0.0695) as a code fix: no
in-place edit of ``CurrentRungHoldConfig.required_fee_coefficient`` and none
of ``DOCUMENTED_TAKER_FEE_COEFFICIENT``. Both therefore stay
``Decimal("0.06")``, pinned below.

The legitimate shape is REGISTRATION, and the registration artifact already
exists: ``deploy/families/<family_id>.json``, committed, content-hashed
(``manifest_sha256``), and refused unless ``status == "REGISTERED"``. A
family's theta is part of its cost basis, hence part of its estimand, so it
belongs on that artifact beside ``d0_climate_day`` and the boundary sha --
never in a launch-shell environment variable, which binds to no artifact, no
hash, and no tally record.

Two halves, both load-bearing:

* the coefficient travels manifest -> ``app.trade.run`` -> every station's
  ``CurrentRungHoldConfig``, so a new theta REQUIRES a new committed,
  sha-changed, REGISTERED manifest;
* the older family's tally gets a TERMINAL bound. ``assert_family_only``
  enforced only a lower bound (``climate_day >= d0_climate_day``), so
  ``pm_us_crh_cont`` would silently ADMIT every 0.0695-priced row and pool
  it into v3's in-flight alpha-spending sequence.
"""

from __future__ import annotations

import ast
import io
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.fees import DOCUMENTED_TAKER_FEE_COEFFICIENT
from breezy.app.trade import run
from breezy.persistence.family_manifest import (
    FamilyManifestValidationError,
    load_family_manifest,
)
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.trade_cli import EXIT_OK
from breezy.settlement.family_barrier import FamilyBarrierRefusal, assert_family_only
from breezy.settlement.trial_scorer import ScoredTrial
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.decision import (
    DecisionInputs,
    Refuse,
    evaluate_decision,
)
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- reused harness
    RecordingNode,
    _operator_order_ceiling,
    _trade_env,
    _write_today_catalog,
)

_FAMILIES_DIR = Path("deploy/families")
_V3 = _FAMILIES_DIR / "pm_us_crh_cont.json"
_V4 = _FAMILIES_DIR / "pm_us_crh_v4.json"

_NEW_THETA = Decimal("0.0695")
_DECISION_SOURCE = Path("src/breezy/strategy/current_rung_hold/decision.py")


# --------------------------------------------------------------------------
# 1. The pin itself is UNCHANGED.
# --------------------------------------------------------------------------


def test_the_documented_taker_theta_and_the_config_default_are_both_still_the_pin() -> None:
    assert DOCUMENTED_TAKER_FEE_COEFFICIENT == Decimal("0.06")
    assert CurrentRungHoldConfig().required_fee_coefficient == Decimal("0.06")


def test_the_fee_schedule_gate_is_still_an_exact_inequality_with_no_tolerance_band() -> None:
    """A tolerance band (``abs(a - b) < eps``) is the softest possible pin
    edit -- it would silently accept a drifted venue theta."""
    source = _DECISION_SOURCE.read_text(encoding="utf-8")
    assert "if inputs.fee_coefficient != inputs.config.required_fee_coefficient:" in source
    tree = ast.parse(source, filename=str(_DECISION_SOURCE))
    evaluate = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_decision"
    )
    assert "abs(" not in ast.unparse(evaluate)


def test_no_environment_variable_carries_the_fee_coefficient() -> None:
    """Registration, not laundering: there must be NO env-var back door that
    re-prices a family without changing its committed manifest."""
    settings_source = Path("src/breezy/runtime/settings.py").read_text(encoding="utf-8")
    assert "FEE_COEFFICIENT" not in settings_source


# --------------------------------------------------------------------------
# 2. The manifest carries the coefficient, strictly parsed.
# --------------------------------------------------------------------------


def _manifest_payload(**overrides: Any) -> dict[str, Any]:
    payload = json.loads(_V3.read_text(encoding="utf-8"))
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def _write_manifest(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "family.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_every_shipped_family_manifest_declares_a_decimal_taker_fee_coefficient() -> None:
    paths = [
        path
        for path in sorted(_FAMILIES_DIR.glob("*.json"))
        if "family_id" in json.loads(path.read_text(encoding="utf-8"))
    ]
    assert len(paths) >= 5
    for path in paths:
        manifest = load_family_manifest(path, allow_draft=True)
        assert isinstance(manifest.taker_fee_coefficient, Decimal)
        assert Decimal(0) < manifest.taker_fee_coefficient < Decimal(1)


def test_a_manifest_missing_the_taker_fee_coefficient_is_refused(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _manifest_payload(taker_fee_coefficient=None))

    with pytest.raises(FamilyManifestValidationError) as excinfo:
        load_family_manifest(path)

    assert "taker_fee_coefficient" in str(excinfo.value)


@pytest.mark.parametrize(
    "raw",
    [
        " 0.0695",
        "0.0695 ",
        "0.0695\n",
        "6.95E-2",
        "6.95e-2",
        "NaN",
        "nan",
        "Infinity",
        "-Infinity",
        "-0.0695",
        "+0.0695",
        "1.5",
        "1",
        "0",
        "0.0",
        "0.000000",
        "00.06",
        ".06",
        "0.",
        "0_0695",
        "0.06_95",
        "0.0695123",
        "6%",
        "abc",
        "",
    ],
)
def test_a_loosely_spelled_taker_fee_coefficient_is_refused(tmp_path: Path, raw: str) -> None:
    path = _write_manifest(tmp_path, _manifest_payload(taker_fee_coefficient=raw))

    with pytest.raises(FamilyManifestValidationError) as excinfo:
        load_family_manifest(path)

    assert "taker_fee_coefficient" in str(excinfo.value)


@pytest.mark.parametrize("raw", [0.0695, 695, None, True, ["0.0695"], {"v": "0.0695"}])
def test_a_non_string_taker_fee_coefficient_is_refused(tmp_path: Path, raw: Any) -> None:
    payload = _manifest_payload()
    payload["taker_fee_coefficient"] = raw
    path = _write_manifest(tmp_path, payload)

    with pytest.raises(FamilyManifestValidationError):
        load_family_manifest(path)


@pytest.mark.parametrize("raw", ["0.06", "0.0695", "0.1", "0.123456"])
def test_a_strictly_spelled_taker_fee_coefficient_parses_exactly(
    tmp_path: Path, raw: str
) -> None:
    path = _write_manifest(tmp_path, _manifest_payload(taker_fee_coefficient=raw))

    manifest = load_family_manifest(path)

    assert manifest.taker_fee_coefficient == Decimal(raw)
    assert str(manifest.taker_fee_coefficient) == raw


def test_the_coefficient_never_travels_through_float(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _manifest_payload(taker_fee_coefficient="0.0695"))

    theta = load_family_manifest(path).taker_fee_coefficient

    assert theta == Decimal("0.0695")
    # `Decimal.from_float(0.0695)` is the binary expansion
    # 0.069500000000000000388578058618804789148271083831787109375.
    assert theta != Decimal.from_float(0.0695)


# --------------------------------------------------------------------------
# 3. The two registered families.
# --------------------------------------------------------------------------


def test_the_v3_family_is_still_registered_at_the_documented_basis() -> None:
    manifest = load_family_manifest(_V3)

    assert manifest.family_id == "pm_us_crh_cont"
    assert manifest.taker_fee_coefficient == DOCUMENTED_TAKER_FEE_COEFFICIENT
    assert manifest.status == "REGISTERED"


def test_the_v4_family_is_registered_at_the_drifted_basis_and_starts_where_v3_stops() -> None:
    v3 = load_family_manifest(_V3)
    v4 = load_family_manifest(_V4)

    assert v4.family_id == "pm_us_crh_v4"
    assert v4.taker_fee_coefficient == _NEW_THETA
    assert v4.status == "REGISTERED"
    assert v4.d0_climate_day == "2026-09-20"
    assert v4.terminal_climate_day is None
    # The COST BASIS changed, not the boundary or the census.
    assert v4.venue == v3.venue
    assert v4.composition_kind == v3.composition_kind
    assert v4.trial_id_prefix == v3.trial_id_prefix
    assert v4.stations == v3.stations
    assert v4.boundary_artefact_path == v3.boundary_artefact_path
    assert v4.boundary_inputs_sha256 == v3.boundary_inputs_sha256
    assert v4.density_artefact_path == v3.density_artefact_path
    assert v4.density_artefact_sha256 == v3.density_artefact_sha256


def test_the_v3_family_now_carries_a_terminal_climate_day() -> None:
    assert load_family_manifest(_V3).terminal_climate_day == "2026-09-19"


# --------------------------------------------------------------------------
# 4. THE BARRIER: v3's tally is closed at the top, so v4 rows never pool in.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class _FakeManifest:
    trial_id_prefix: str
    d0_climate_day: str
    stations: tuple[str, ...]
    terminal_climate_day: str | None = None


def _row(climate_day: str) -> ScoredTrial:
    return ScoredTrial(
        trial_id=f"continuous_rung_hold/trial/LAX/{climate_day}/0",
        station="LAX",
        climate_day=climate_day,
        instrument_id="instrument-1",
        settlement_tmax_f=80,
        held=True,
        pnl=Decimal("0.10"),
        revision_seq=0,
        raw_sha256="deadbeef",
        scored_at_ns=1,
        score_seq=0,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=Decimal("0.5"),
        fill_px=Decimal("0.5"),
        fee=Decimal("0.02"),
    )


def test_a_row_after_the_terminal_day_is_refused_into_the_older_familys_tally() -> None:
    """The fatal asymmetry: without a terminal bound, every 0.0695-priced
    row would be admitted into the 0.06 family's in-flight sequential test."""
    with pytest.raises(FamilyBarrierRefusal) as excinfo:
        assert_family_only((_row("2026-09-20"),), load_family_manifest(_V3))

    assert "2026-09-20" in str(excinfo.value)


def test_a_row_exactly_on_the_terminal_day_is_admitted_boundary_inclusive() -> None:
    assert_family_only((_row("2026-09-19"),), load_family_manifest(_V3))  # no raise


def test_the_same_row_is_admitted_into_the_new_familys_tally() -> None:
    assert_family_only((_row("2026-09-20"),), load_family_manifest(_V4))  # no raise


def test_a_pre_d0_row_is_still_refused_into_the_new_familys_tally() -> None:
    with pytest.raises(FamilyBarrierRefusal):
        assert_family_only((_row("2026-09-19"),), load_family_manifest(_V4))


def test_a_manifest_without_a_terminal_bound_is_unbounded_above() -> None:
    """Additive: the bound is optional, and its absence is exactly the
    pre-existing behaviour."""
    manifest = _FakeManifest(
        trial_id_prefix="continuous_rung_hold/trial/",
        d0_climate_day="2026-09-12",
        stations=("LAX",),
    )

    assert_family_only((_row("2099-01-01"),), manifest)  # no raise


def test_a_terminal_day_that_is_not_a_real_date_is_refused(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _manifest_payload(terminal_climate_day="2026-13-45"))

    with pytest.raises(FamilyManifestValidationError) as excinfo:
        load_family_manifest(path)

    assert "terminal_climate_day" in str(excinfo.value)


def test_a_terminal_day_before_d0_is_refused(tmp_path: Path) -> None:
    path = _write_manifest(tmp_path, _manifest_payload(terminal_climate_day="2026-01-01"))

    with pytest.raises(FamilyManifestValidationError) as excinfo:
        load_family_manifest(path)

    assert "terminal_climate_day" in str(excinfo.value)


# --------------------------------------------------------------------------
# 5. The decision path: drift detection keeps working at the NEW basis.
# --------------------------------------------------------------------------


def _decision_inputs(*, venue_theta: Decimal, config: CurrentRungHoldConfig) -> DecisionInputs:
    return DecisionInputs(
        station="LAX",
        climate_day=date(2026, 9, 20),
        now_ns=0,
        ladder=(),
        fee_coefficient=venue_theta,
        ask=Decimal("0.50"),
        size=1,
        running_max=None,
        staleness_ns=None,
        config=config,
        season="warm",
        hour_lst=12,
        width_code=0,
        m_code=0,
        latch_consumed=False,
    )


def test_a_venue_theta_of_0695_no_longer_mismatches_at_the_new_registered_basis() -> None:
    config = CurrentRungHoldConfig(required_fee_coefficient=_NEW_THETA)

    decision = evaluate_decision(_decision_inputs(venue_theta=_NEW_THETA, config=config))

    assert decision != Refuse("fee_schedule_mismatch")


def test_a_venue_theta_that_differs_from_the_manifest_theta_still_refuses() -> None:
    config = CurrentRungHoldConfig(
        required_fee_coefficient=load_family_manifest(_V4).taker_fee_coefficient
    )

    reverted = evaluate_decision(_decision_inputs(venue_theta=Decimal("0.06"), config=config))
    moved_again = evaluate_decision(
        _decision_inputs(venue_theta=Decimal("0.075"), config=config)
    )

    assert reverted == Refuse("fee_schedule_mismatch")
    assert moved_again == Refuse("fee_schedule_mismatch")


def test_the_default_config_still_refuses_the_drifted_venue_theta() -> None:
    decision = evaluate_decision(
        _decision_inputs(venue_theta=_NEW_THETA, config=CurrentRungHoldConfig())
    )

    assert decision == Refuse("fee_schedule_mismatch")


# --------------------------------------------------------------------------
# 6. End to end: naming the family is the ONLY act required.
# --------------------------------------------------------------------------


def _run_with_family(tmp_path: Path, family_id: str) -> list[Any]:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: family_id,
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )
    assert not [key for key in env if "FEE" in key]

    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    strategies = [
        strategy
        for strategy in node.trader.strategies
        if isinstance(strategy, ContinuousRungHoldStrategy)
    ]
    assert strategies, "no ContinuousRungHoldStrategy was registered"
    return strategies


def test_booting_the_new_family_prices_every_station_at_the_registered_theta(
    tmp_path: Path,
) -> None:
    for strategy in _run_with_family(tmp_path, "pm_us_crh_v4"):
        assert strategy.config.required_fee_coefficient == _NEW_THETA


def test_booting_the_old_family_still_prices_every_station_at_the_documented_theta(
    tmp_path: Path,
) -> None:
    for strategy in _run_with_family(tmp_path, "pm_us_crh_cont"):
        assert strategy.config.required_fee_coefficient == Decimal("0.06")

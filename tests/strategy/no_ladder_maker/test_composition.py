"""ARM C2: the maker's composition helpers and the strict harm-stop probe wiring (D1 K2)."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.health import AlertPayload
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactPinMismatchError,
)
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import (
    REASON_FAIL,
    REASON_STALE,
    REASON_UNKNOWN,
    Verdict,
)
from breezy.strategy.no_ladder_maker import composition
from breezy.strategy.no_ladder_maker.harm_stop import maker_loss_stop_artefact_path
from breezy.strategy.no_ladder_maker.params import SHARP_V1
from tests.support.fq_loss_stop_artefact import write_artefact

REPO: Final[Path] = Path(__file__).resolve().parents[3]
CALIBRATION: Final[Path] = (
    REPO / "deploy/families/artefacts/nbp_calibration_pm_us_crh_fq_v1_2026-09-30.json"
)
CALIBRATION_SHA: Final[str] = "9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e"
STATIONS: Final = ("LAX", "MDW", "MIA", "SFO")


def _build(**overrides: object) -> object:
    kwargs: dict[str, object] = {
        "stations": STATIONS,
        "calibration_artefact_path": str(CALIBRATION),
        "calibration_artefact_sha256": CALIBRATION_SHA,
        "theta": 0.0695,
        "order_submission_permit": None,
        "submit_veto": None,
        "fee_verified": None,
    }
    kwargs.update(overrides)
    return composition.build_no_ladder_maker_strategy(**kwargs)  # type: ignore[arg-type]


def test_one_strategy_serves_every_station_and_fails_closed_by_default() -> None:
    strategy = _build()
    assert strategy.config.stations == STATIONS  # type: ignore[attr-defined]
    assert strategy.config.shadow_only is True  # type: ignore[attr-defined]
    assert strategy.config.allow_short is False  # type: ignore[attr-defined]
    assert strategy.config.manage_gtd_expiry is True  # type: ignore[attr-defined]
    assert strategy.config.order_id_tag == composition.ORDER_ID_TAG  # type: ignore[attr-defined]
    assert strategy._params is SHARP_V1  # type: ignore[attr-defined]
    assert strategy._theta == 0.0695  # type: ignore[attr-defined]


def test_shadow_only_is_the_callers_value_untouched() -> None:
    assert _build(shadow_only=False).config.shadow_only is False  # type: ignore[attr-defined]
    assert _build(shadow_only=True).config.shadow_only is True  # type: ignore[attr-defined]


def test_a_wrong_calibration_sha_is_refused_before_a_strategy_exists() -> None:
    with pytest.raises(CalibrationArtefactPinMismatchError):
        _build(calibration_artefact_sha256="0" * 63 + "1")
    assert hashlib.sha256(CALIBRATION.read_bytes()).hexdigest() == CALIBRATION_SHA


# --- the harm-stop probe -----------------------------------------------------------------------


class _OffBoxSink:
    """A sink whose emits count as delivered off the box (the non-strict probe's escape hatch)."""

    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _wiring(
    tmp_path: Path, *, halts: list[tuple[str, str]] | None = None, now: datetime | None = None
) -> composition.HarmStopWiring:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir(exist_ok=True)
    return composition.build_harm_stop_wiring(
        catalog_root=catalog_root,
        halt_veto=lambda: None,
        set_family_halted=(lambda r, e: halts.append((r, e)))
        if halts is not None
        else (lambda r, e: None),
        clock=(lambda: now) if now is not None else (lambda: datetime.now(tz=UTC)),
        alert_sink=_OffBoxSink(),
        alert_every_probe=lambda: True,
        expected_uid=os.getuid(),
    )


def _artefact_path(tmp_path: Path) -> Path:
    return maker_loss_stop_artefact_path(tmp_path / "catalog")


def test_the_probe_reads_the_maker_artefact_path_and_an_absent_file_vetoes(tmp_path: Path) -> None:
    wiring = _wiring(tmp_path)
    assert wiring.probe.probe_once() is Verdict.UNKNOWN
    assert wiring.veto() == REASON_UNKNOWN
    assert _artefact_path(tmp_path).parts[-3:] == ("derived", "maker-loss-stop", "latest.json")


def test_a_fresh_pass_adds_no_refusal(tmp_path: Path) -> None:
    wiring = _wiring(tmp_path)
    write_artefact(_artefact_path(tmp_path), verdict="PASS")
    assert wiring.probe.probe_once() is Verdict.PASS
    assert wiring.veto() is None


def test_a_fail_sets_the_family_halt_and_vetoes(tmp_path: Path) -> None:
    halts: list[tuple[str, str]] = []
    wiring = _wiring(tmp_path, halts=halts)
    write_artefact(_artefact_path(tmp_path), verdict="FAIL")
    assert wiring.probe.probe_once() is Verdict.FAIL
    assert wiring.veto() == REASON_FAIL
    assert len(halts) == 1


def test_the_probe_is_strict_a_stale_pass_vetoes_even_when_the_alert_left_the_box(
    tmp_path: Path,
) -> None:
    """Between MAX_AGE_H (26) and STALE_VETO_H (36) the FQ probe lets entries through while its
    CRITICAL alert is delivered off-box; the maker's STRICT probe never does (D1 review K2)."""
    stale = datetime.now(tz=UTC) - timedelta(hours=30)
    write_artefact(_artefact_path(tmp_path), verdict="PASS", as_of=stale)
    strict = _wiring(tmp_path)
    assert strict.probe.probe_once() is Verdict.UNKNOWN_STALE
    assert strict.veto() == REASON_STALE

    from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import LossStopProbe

    lax = LossStopProbe(
        path=_artefact_path(tmp_path),
        clock=lambda: datetime.now(tz=UTC),
        set_family_halted=lambda r, e: None,
        alert_sink=_OffBoxSink(),
        alert_every_probe=lambda: True,
        expected_uid=os.getuid(),
    )
    assert lax.probe_once() is Verdict.UNKNOWN_STALE
    assert lax.veto_reason() is None, "plant: the non-strict probe would have let entries through"


def test_the_halt_veto_comes_first(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    wiring = composition.build_harm_stop_wiring(
        catalog_root=catalog_root,
        halt_veto=lambda: "family_halt",
        set_family_halted=lambda r, e: None,
        clock=lambda: datetime.now(tz=UTC),
        alert_sink=_OffBoxSink(),
        alert_every_probe=lambda: True,
    )
    assert wiring.veto() == "family_halt"

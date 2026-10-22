"""Composition helpers for the ``no_ladder_maker`` kind (ARM C2).

Two pieces, both pure construction (no node, no I/O beyond the sha-pinned calibration load):

* :func:`build_no_ladder_maker_strategy` -- ONE :class:`NoLadderMakerStrategy` serving every
  configured station, over the sha-pinned design-run calibration;
* :func:`build_harm_stop_wiring` -- the maker's ``LossStopProbe`` (STRICT staleness, D1 review K2)
  over ``maker_loss_stop_artefact_path(catalog_root)``, and the composed entry veto (family halt
  first, then the harm stop). A harm-stop FAIL sets the family halt through the injected setter; the
  strategy reads the same veto on every decision and on its poll timer and answers a veto by
  cancelling every live order, per order from the cache (R12). HOLD, an absent file, a stale file
  and a FAIL all veto entries: the probe reads UNKNOWN for all but PASS.
* :func:`refuse_placeholder_d0` -- the shipped manifest's ``d0_climate_day`` is a PLACEHOLDER until
  the ARM commit sets the first legitimately tradable ladder day; it may never reach a send.

The caller (``app/trade.py``) owns the halt latch, the permit, the live-orders gate and the actors.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from breezy.persistence.family_manifest import FamilyManifest
from breezy.runtime.health import AlertSink
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import load_live_calibration
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import FqComposedVeto, LossStopProbe
from breezy.strategy.no_ladder_maker.config import NoLadderMakerConfig
from breezy.strategy.no_ladder_maker.harm_stop import maker_loss_stop_artefact_path
from breezy.strategy.no_ladder_maker.params import SHARP_V1, MakerRuleParams
from breezy.strategy.no_ladder_maker.strategy import NoLadderMakerStrategy, SupportsExpiresAtNs

__all__ = [
    "COMPONENT_ID",
    "D0_PLACEHOLDER",
    "ORDER_ID_TAG",
    "TRIAL_KEY_PREFIX",
    "HarmStopWiring",
    "PlaceholderD0Error",
    "build_harm_stop_wiring",
    "build_no_ladder_maker_strategy",
    "refuse_placeholder_d0",
]

#: The family's durable namespace for the halt latch it shares with the exec client's store.
TRIAL_KEY_PREFIX: Final[str] = "no_ladder_maker/trial/"
COMPONENT_ID: Final[str] = "NO-LADDER-MAKER"
ORDER_ID_TAG: Final[str] = "SHARP"
#: The manifest's draft ``d0_climate_day``. The ARM commit replaces it with the real D0.
D0_PLACEHOLDER: Final[str] = "2026-10-28"


class PlaceholderD0Error(ValueError):
    """The placeholder D0 would reach a live send (a ruling is present, or sending is enabled)."""


def refuse_placeholder_d0(manifest: FamilyManifest, *, shadow_only: bool) -> None:
    """W6: the placeholder D0 is allowed only for a shadow family that carries no ruling."""
    if manifest.d0_climate_day != D0_PLACEHOLDER:
        return
    if not shadow_only or manifest.live_orders_ruling:
        raise PlaceholderD0Error(
            f"{manifest.family_id}: d0_climate_day {D0_PLACEHOLDER!r} is the draft placeholder; "
            "set the real D0 (the first legitimately tradable ladder day) before any live send"
        )


@dataclass(frozen=True, slots=True)
class HarmStopWiring:
    probe: LossStopProbe
    veto: FqComposedVeto


def build_harm_stop_wiring(
    *,
    catalog_root: Path,
    halt_veto: Callable[[], str | None],
    set_family_halted: Callable[[str, str], None],
    clock: Callable[[], datetime],
    alert_sink: AlertSink,
    alert_every_probe: Callable[[], bool],
    expected_uid: int | None = None,
) -> HarmStopWiring:
    """The strict maker loss-stop probe and the veto the strategy and the exec client share."""
    probe = LossStopProbe(
        path=maker_loss_stop_artefact_path(catalog_root),
        clock=clock,
        set_family_halted=set_family_halted,
        alert_sink=alert_sink,
        alert_every_probe=alert_every_probe,
        expected_uid=os.getuid() if expected_uid is None else expected_uid,
        strict_staleness=True,
    )
    return HarmStopWiring(
        probe=probe,
        veto=FqComposedVeto(halt_veto=halt_veto, loss_stop_veto=probe.veto_reason),
    )


def build_no_ladder_maker_strategy(
    *,
    stations: Sequence[str],
    calibration_artefact_path: str,
    calibration_artefact_sha256: str,
    theta: float,
    order_submission_permit: SupportsExpiresAtNs | None,
    submit_veto: Callable[[], str | None] | None,
    fee_verified: Callable[[int], bool] | None,
    shadow_only: bool = True,
    params: MakerRuleParams = SHARP_V1,
) -> NoLadderMakerStrategy:
    """One strategy for all ``stations``; ``shadow_only`` defaults True (fail closed).

    ``shadow_only=False`` may only originate from the live-orders gate's output at the caller
    (``not live_orders.enabled``); this function forwards it untouched.
    """
    calibration = load_live_calibration(
        calibration_artefact_path, expected_sha256=calibration_artefact_sha256
    )
    config = NoLadderMakerConfig(
        stations=tuple(stations),
        shadow_only=shadow_only,
        strategy_id=COMPONENT_ID,
        order_id_tag=ORDER_ID_TAG,
    )
    return NoLadderMakerStrategy(
        config,
        calibration=calibration,
        theta=theta,
        params=params,
        order_submission_permit=order_submission_permit,
        submit_veto=submit_veto,
        fee_verified=fee_verified,
    )

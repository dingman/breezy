"""ARM D1: ``crosscheck_with_cli`` builds carrier rows for ``reconcile_settlement``.

The carrier's ``fill_px`` / ``station`` / ``qty`` are inert placeholders: ``reconcile_settlement``
must decide from the entry role, the leg, the settled outcome and the net-position key only.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, Final

from breezy.analysis.labeling.maker_settlement_crosscheck import _row, crosscheck_with_cli
from breezy.analysis.labeling.reconcile import SettlementEvidence, reconcile_settlement

SLUG: Final[str] = "tc-temp-nychigh-2026-08-09-gte94lt95f"


def _reconciled(venue_yes: bool, *, cli_yes: bool, **overrides: Any) -> bool:
    row = replace(_row(SLUG, cli_yes=cli_yes), **overrides)
    leg = reconcile_settlement([row], {SLUG: SettlementEvidence(venue_yes_resolved=venue_yes)})
    return leg.rows[0].reconciled


def test_reconcile_settlement_ignores_the_carrier_fill_px_station_and_qty() -> None:
    placeholders: list[dict[str, Any]] = [
        {},
        {"fill_px": Decimal("0.5")},
        {"fill_px": Decimal(123)},
        {"station": "NYC"},
        {"station": "anything-else"},
        {"qty": Decimal(7)},
        {"fill_px": Decimal("0.9"), "station": "SFO", "qty": Decimal(3)},
    ]
    for venue_yes, cli_yes in ((True, True), (False, False), (True, False), (False, True)):
        baseline = _reconciled(venue_yes, cli_yes=cli_yes)
        assert baseline is (venue_yes == cli_yes)
        for overrides in placeholders:
            assert _reconciled(venue_yes, cli_yes=cli_yes, **overrides) is baseline


def test_the_crosscheck_agrees_and_mismatches_through_reconcile_settlement() -> None:
    result = crosscheck_with_cli({SLUG: False}, lambda facts: 94)  # CLI 94 is inside the rung
    assert result.mismatched == (SLUG,) and result.agreed == ()
    result = crosscheck_with_cli({SLUG: False}, lambda facts: 60)
    assert result.agreed == (SLUG,) and result.mismatched == ()

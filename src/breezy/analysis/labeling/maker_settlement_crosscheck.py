"""ARM D1: cross-check the venue's YES resolutions against the CLI final.

The comparison itself is the existing ``reconcile_settlement`` (one ENTRY label row per resolved
market, the CLI-derived outcome against the venue's resolution); this module only builds those
rows. Read-only and pure apart from the injected CLI reader.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.labeling.reconcile import SettlementEvidence, reconcile_settlement
from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.persistence.autonomy.label_schema import LabelRole, PSource
from breezy.persistence.autonomy.label_store import LabelRow

__all__ = ["CrossCheck", "crosscheck_with_cli"]

_FAMILY: str = "pm_us_no_maker_sharp_v1"
_SCORER: str = "maker_venue_settlement_crosscheck"
#: the instrument-id venue suffix of a Polymarket.us slug (``<slug>.POLYMARKET_US``)
_VENUE_SUFFIX: str = "POLYMARKET_US"

CliReading = Callable[[WeatherBucketFacts], int | None]


@dataclass(frozen=True, slots=True)
class CrossCheck:
    """``agreed``: venue and CLI agree. ``unchecked``: no usable CLI final yet. ``mismatched``:
    they disagree (or the slug is not a parseable weather rung): never trusted."""

    agreed: tuple[str, ...]
    unchecked: tuple[str, ...]
    mismatched: tuple[str, ...]


def _row(slug: str, *, cli_yes: bool) -> LabelRow:
    return LabelRow(
        label_id=slug,
        decision_id=None,
        family_id=_FAMILY,
        trial_id="",
        client_order_id="",
        trade_id=None,
        station="",
        climate_day="",
        instrument_id=slug,
        rung_id=slug,
        leg="yes",
        role=LabelRole.ENTRY,
        qty=Decimal(1),
        fill_px=Decimal(0),
        entry_ask=None,
        fee_reconciled=None,
        slippage=None,
        p_at_decision=None,
        p_raw_at_decision=None,
        p_source=PSource.NONE,
        settled_outcome=cli_yes,
        settlement_tmax_f=None,
        settlement_basis=None,
        realized_pnl=None,
        counterfactual_hold_pnl=None,
        reconciled=True,
        reconciliation_delta=None,
        reconciliation_source="cli",
        net_position_key=slug,
        admissible=True,
        excluded_reason=None,
        labelled_at_ns=0,
        label_seq=0,
        scorer_id=_SCORER,
    )


def crosscheck_with_cli(yes_resolved: Mapping[str, bool], cli_reading: CliReading) -> CrossCheck:
    """Compare each venue resolution with the CLI final through ``reconcile_settlement``."""
    rows: list[LabelRow] = []
    unchecked: list[str] = []
    mismatched: list[str] = []
    for slug in sorted(yes_resolved):
        facts = bucket_facts_from_instrument_id(f"{slug}.{_VENUE_SUFFIX}")
        if facts is None:
            mismatched.append(slug)
            continue
        reading = cli_reading(facts)
        if reading is None:
            unchecked.append(slug)
            continue
        rows.append(_row(slug, cli_yes=facts.contains(reading)))
    evidence = {
        slug: SettlementEvidence(venue_yes_resolved=yes_resolved[slug]) for slug in yes_resolved
    }
    leg = reconcile_settlement(rows, evidence)
    mismatched.extend(row.net_position_key for row in leg.rows if not row.reconciled)
    agreed = [row.net_position_key for row in leg.rows if row.reconciled]
    return CrossCheck(tuple(agreed), tuple(unchecked), tuple(sorted(mismatched)))

"""Shared builders for the AUT-2 labelling tests: durable fills written into a real exec store.

This module imports ``exec.client`` for ``DurableFillRecord`` and ``FILL_KEY_PREFIX`` only, so every
AUT-2 test file reaches the exec package through this one registered module (the X1 pin names it).
Nothing is constructed from the client and no socket is opened.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.analysis.labeling.completeness import Coverage
from breezy.analysis.labeling.verdicts import ReconFacts, ReconMode
from breezy.persistence.autonomy.capture_reader import DecisionView, OrderLinkView
from breezy.persistence.autonomy.label_schema import LabelRole, PSource
from breezy.persistence.autonomy.label_store import LabelRow
from breezy.persistence.autonomy.verdict import VerdictOutcome
from breezy.runtime.sqlite_store import SqliteStateStore

__all__ = [
    "ART",
    "FILL_KEY_PREFIX",
    "HOUR_NS",
    "LABEL_FAMILY",
    "LABEL_NOW_NS",
    "NO",
    "NOW",
    "PASS",
    "RELEASE_NS",
    "SHA",
    "TS",
    "VENUE",
    "YES",
    "DurableFillRecord",
    "durable_fill",
    "make_coverage",
    "make_decision",
    "make_label_row",
    "make_link",
    "make_recon_facts",
    "portfolio_roi_module",
    "seed_fills",
]

FQ_YES_SLUG = "tc-temp-laxhigh-2026-10-02-gte89lt90f"


def durable_fill(
    *,
    venue_order_id: str = "vo-1",
    client_order_id: str | None = None,
    instrument_id: str = f"{FQ_YES_SLUG}.POLYMARKET_US",
    order_side: str = "BUY",
    qty: Decimal = Decimal(1),
    cost: Decimal = Decimal("0.40"),
    fee: Decimal = Decimal("0.03"),
    fee_reconciled: bool = True,
    ts_event: int = 1_790_000_000_000_000_000,
    trade_id: str | None = "T-1",
) -> DurableFillRecord:
    return DurableFillRecord(
        venue_order_id=venue_order_id,
        client_order_id=client_order_id or f"O-{venue_order_id}",
        instrument_id=instrument_id,
        order_side=order_side,
        cumulative_qty=qty,
        cumulative_cost=cost,
        cumulative_fee=fee,
        fee_reconciled=fee_reconciled,
        ts_event=ts_event,
        trade_id=trade_id,
    )


def seed_fills(store_path: Path, fills: Iterable[DurableFillRecord]) -> None:
    """Write ``fills`` under the real durable-fill key prefix with the real record serialiser."""
    store = SqliteStateStore(store_path)
    try:
        for fill in fills:
            store.set(f"{FILL_KEY_PREFIX}{fill.venue_order_id}", fill.to_bytes())
    finally:
        store.close()


# -- shared builders (public so test modules never import each other's private helpers) -----------

VENUE = "polymarket_us"
YES = "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US"
NO = "tc-temp-laxhigh-2026-10-02-gte89lt90f^no.POLYMARKET_US"
TS = 1_790_000_000_000_000_000


HOUR_NS = 3_600_000_000_000
RELEASE_NS = TS + 10 * HOUR_NS
LABEL_FAMILY = "pm_us_crh_fq_v1"
LABEL_NOW_NS = 1_790_000_000_000_000_000
NOW = LABEL_NOW_NS
SHA = "c" * 64
ART = "a" * 64
PASS = VerdictOutcome.PASS


def make_decision(**over: Any) -> DecisionView:
    base: dict[str, Any] = {
        "schema": "capture_decision/v2",
        "decision_id": "dec-1",
        "family_id": "pm_us_crh_fq_v1",
        "node_boot_id": "boot-1",
        "build_sha": "b" * 40,
        "registry_seq": 0,
        "drill": False,
        "source": "live",
        "kind": "Take",
        "reason": "",
        "eval_ns": TS - 10,
        "eval_seq": 0,
        "wall_ns": TS - 10,
        "ts_ns": TS - 10,
        "station": "LAX",
        "climate_day": "2026-10-02",
        "rung_id": "89_90",
        "side": "yes",
        "instrument_id": YES,
        "ask_px": "0.40",
        "depth_ref": "",
        "quote_ref": "",
        "p_hat": "0.62",
        "p_hat_raw": "0.62",
        "p_lower": "0.5",
        "p_upper": "0.7",
        "ev_net": "0.1",
        "margin": "0.1",
        "forecast_input_ref": "",
        "artefact_sha256": "a" * 64,
        "manifest_sha256": "m" * 64,
    }
    base.update(over)
    return DecisionView(**base)


def make_link(coid: str = "O-1", decision_id: str = "dec-1", **over: Any) -> OrderLinkView:
    base: dict[str, Any] = {
        "decision_id": decision_id,
        "client_order_id": coid,
        "venue_order_id_sha256": "",
        "instrument_id": YES,
        "side": "1",
        "qty": "1.00",
        "px": "0.40",
        "time_in_force": "2",
        "intent_fingerprint": "f" * 64,
        "ts_ns": TS - 5,
        "source": "live",
    }
    base.update(over)
    return OrderLinkView(**base)


def make_label_row(**overrides: Any) -> LabelRow:
    base: dict[str, Any] = {
        "label_id": "a" * 32,
        "decision_id": "d" * 64,
        "family_id": LABEL_FAMILY,
        "trial_id": "forecast_quantile_ladder/trial/LAX/2026-10-02/89_90:yes.POLYMARKET_US",
        "client_order_id": "O-20261002-1",
        "trade_id": "T-1",
        "station": "LAX",
        "climate_day": "2026-10-02",
        "instrument_id": "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US",
        "rung_id": "89_90",
        "leg": "yes",
        "role": LabelRole.ENTRY,
        "qty": Decimal(1),
        "fill_px": Decimal("0.40"),
        "entry_ask": Decimal("0.40"),
        "fee_reconciled": Decimal("0.03"),
        "slippage": Decimal(0),
        "p_at_decision": 0.62,
        "p_raw_at_decision": 0.62,
        "p_source": PSource.C1_DECISION,
        "settled_outcome": True,
        "settlement_tmax_f": Decimal(89),
        "settlement_basis": "nws_final",
        "realized_pnl": Decimal("0.57"),
        "counterfactual_hold_pnl": None,
        "reconciled": True,
        "reconciliation_delta": Decimal(0),
        "reconciliation_source": "venue_get",
        "net_position_key": "tc-temp-laxhigh-2026-10-02-gte89lt90f",
        "admissible": True,
        "excluded_reason": None,
        "labelled_at_ns": LABEL_NOW_NS,
        "label_seq": 0,
        "scorer_id": "forecast_quantile_ladder/v1",
    }
    base.update(overrides)
    return LabelRow(**base)


def make_coverage(**over: Any) -> Coverage:
    base: dict[str, Any] = {
        "durable_fill_count": 10,
        "c2_final": 10,
        "open": 0,
        "pending": 0,
        "unresolved": 0,
        "missing_label": 0,
        "unattributed_pre_epoch": 4,
        "legacy_labelled": 6,
    }
    base.update(over)
    return Coverage(**base)


def make_recon_facts(**over: Any) -> ReconFacts:
    base: dict[str, Any] = {
        "family_id": "pm_us_crh_fq_v1",
        "mode": ReconMode.DAILY,
        "produced_at_ns": NOW,
        "producer_code_sha": SHA,
        "subject_artefact_sha256": ART,
        "position": PASS,
        "settlement": PASS,
        "cash": PASS,
        "coverage": make_coverage(),
        "breaches": (),
        "n": 7,
        "metrics": {"p_null_count": 2, "non_c1_post_epoch_count": 0},
        "policy": None,
    }
    base.update(over)
    return ReconFacts(**base)


def portfolio_roi_module() -> Any:
    """The ``scripts/analysis/portfolio_roi_report.py`` module, loaded once and shared."""
    import importlib.util
    import sys

    existing = sys.modules.get("portfolio_roi_report")
    if existing is not None:
        return existing
    path = Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "portfolio_roi_report.py"
    spec = importlib.util.spec_from_file_location("portfolio_roi_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

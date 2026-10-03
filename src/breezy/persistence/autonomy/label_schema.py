"""C2 ``label/v1``: the pinned arrow schema and its closed vocabularies (ARCH-0 AC 24).

One parquet file per labelling run holds rows of this schema, column for column in ARCH C2 order.
Decimals (quantities, prices, fees, slippage, P&L, deltas, the settlement temperature) are
canonical decimal strings, so no money value passes through binary floating point; the two
probabilities are the only ``float64`` columns, as ARCH names them. A column is nullable only
where ARCH allows a null: the decision link, the trade id, a probability with a stated reason, and
every value that does not exist until settlement, an exit or a reconciliation.

This module reaches ``pyarrow`` and is therefore outside import contract (c).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

import pyarrow as pa

__all__ = [
    "LABEL_SCHEMA_ID",
    "LABEL_V1_ARROW_SCHEMA",
    "ExcludedReason",
    "LabelRole",
    "PSource",
]

LABEL_SCHEMA_ID: Final = "label/v1"


class ExcludedReason(StrEnum):
    """Why a fill is not an admissible label. ``q≠1`` is ARCH's literal value."""

    DUPLICATE_FILL = "duplicate_fill"
    QTY_NOT_ONE = "q≠1"
    FEE_UNRECONCILED = "fee_unreconciled"
    WINDOW_INCOMPLETE = "window_incomplete"
    CANARY = "canary"
    DRILL = "drill"
    VOIDED_PAIR = "voided_pair"
    SLIPPAGE_DEFECT = "slippage_defect"
    UNATTRIBUTED = "unattributed"


class PSource(StrEnum):
    """Where ``p_at_decision`` came from; only ``c1_decision`` rows feed fits and statistics."""

    C1_DECISION = "c1_decision"
    ARTEFACT_RECOMPUTE = "artefact_recompute"
    NONE = "none"


class LabelRole(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


_STR: Final = pa.string()
_FLOAT: Final = pa.float64()
_BOOL: Final = pa.bool_()
_INT: Final = pa.int64()


def _col(name: str, arrow_type: pa.DataType, *, nullable: bool = False) -> pa.Field:
    return pa.field(name, arrow_type, nullable=nullable)


LABEL_V1_ARROW_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        # identity
        _col("label_id", _STR),
        _col("decision_id", _STR, nullable=True),
        _col("family_id", _STR),
        _col("trial_id", _STR),
        _col("client_order_id", _STR),
        _col("trade_id", _STR, nullable=True),
        # market
        _col("station", _STR),
        _col("climate_day", _STR),
        _col("instrument_id", _STR),
        _col("rung_id", _STR),
        _col("leg", _STR),
        _col("role", _STR),
        # fill (decimal strings)
        _col("qty", _STR),
        _col("fill_px", _STR),
        _col("entry_ask", _STR, nullable=True),
        _col("fee_reconciled", _STR, nullable=True),
        _col("slippage", _STR, nullable=True),
        # the bought leg's win probability
        _col("p_at_decision", _FLOAT, nullable=True),
        _col("p_raw_at_decision", _FLOAT, nullable=True),
        _col("p_source", _STR),
        # settlement
        _col("settled_outcome", _BOOL, nullable=True),
        _col("settlement_tmax_f", _STR, nullable=True),
        _col("settlement_basis", _STR, nullable=True),
        # P&L (decimal strings)
        _col("realized_pnl", _STR, nullable=True),
        _col("counterfactual_hold_pnl", _STR, nullable=True),
        # reconciliation
        _col("reconciled", _BOOL),
        _col("reconciliation_delta", _STR, nullable=True),
        _col("reconciliation_source", _STR),
        _col("net_position_key", _STR),
        # admissibility
        _col("admissible", _BOOL),
        _col("excluded_reason", _STR, nullable=True),
        # run metadata
        _col("labelled_at_ns", _INT),
        _col("label_seq", _INT),
        _col("scorer_id", _STR),
    ]
)

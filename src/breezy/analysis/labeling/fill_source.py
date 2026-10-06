"""The durable-fill reader and the leg-signed ledger net (AUT-2 r7 WP2, ``fill_source.py``).

Every ``DurableFillRecord`` under ``exec/polymarket_us/fill/`` is read through a SQLite
``mode=ro`` URI with ``query_only`` (the G6 idiom, E-7 rule 3), so this reader can never contend
with the node's writer and never writes. A record that does not decode is counted, never skipped
silently: the caller treats ``n_undecodable > 0`` as store corruption (plan r7 section 3.12).

The canary store is never opened here (plan r7 section 3.8).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.client import FILL_KEY_PREFIX, DurableFillRecord
from breezy.domain.instrument_leg import base_symbol_of, leg_of_symbol, symbol_of_instrument_id
from breezy.persistence.autonomy.net_position import LegFill, net_signed_qty

__all__ = [
    "FillRead",
    "FillStoreCorruption",
    "leg_fill_of",
    "net_by_base_slug",
    "read_durable_fills",
]

_BUSY_TIMEOUT_S: Final = 5.0
_SIDES: Final = ("BUY", "SELL")


class FillStoreCorruption(Exception):
    """One or more durable fill records did not decode: the ledger cannot be trusted."""


@dataclass(frozen=True)
class FillRead:
    """``n_keys`` counts every key under the fill prefix; ``fills`` holds the decodable ones."""

    fills: tuple[DurableFillRecord, ...]
    n_keys: int
    n_undecodable: int

    def require_clean(self) -> FillRead:
        """``self`` when every key decoded; otherwise ``FillStoreCorruption`` (never a skip)."""
        if self.n_undecodable:
            raise FillStoreCorruption(
                f"{self.n_undecodable} of {self.n_keys} durable fill records did not decode"
            )
        return self


def read_durable_fills(db_path: Path) -> FillRead:
    """Every durable fill in the exec store at ``db_path``, read-only.

    An absent store raises ``FileNotFoundError`` (an absent ledger is never an empty one). A store
    that cannot be opened or queried as the exec schema raises ``sqlite3.Error``.
    """
    if not db_path.is_file():
        raise FileNotFoundError("the exec state store does not exist")
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=_BUSY_TIMEOUT_S)
    try:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT key, value FROM state WHERE substr(key, 1, ?) = ? ORDER BY key",
            (len(FILL_KEY_PREFIX), FILL_KEY_PREFIX),
        ).fetchall()
    finally:
        conn.close()
    fills: list[DurableFillRecord] = []
    undecodable = 0
    for _key, value in rows:
        try:
            fills.append(DurableFillRecord.from_bytes(value))
        except (ExecutionReportMappingError, TypeError):
            undecodable += 1
    return FillRead(fills=tuple(fills), n_keys=len(rows), n_undecodable=undecodable)


def leg_fill_of(fill: DurableFillRecord) -> LegFill:
    """The netting view of one fill: its leg, side, quantity and event time.

    The durable record stores a NO buy as ``BUY`` on the NO-leg instrument; the venue nets the
    holding as short YES, so the sign is applied from the leg (``net_signed_qty``), here and before
    any comparison with the venue.
    """
    if fill.order_side not in _SIDES:
        raise ValueError(f"a fill's order side must be BUY or SELL, got {fill.order_side!r}")
    side: Literal["BUY", "SELL"] = "BUY" if fill.order_side == "BUY" else "SELL"
    return LegFill(
        leg=leg_of_symbol(symbol_of_instrument_id(fill.instrument_id)),
        side=side,
        qty=fill.cumulative_qty,
        ts_event_ns=fill.ts_event,
    )


def net_by_base_slug(fills: Iterable[DurableFillRecord]) -> dict[str, Decimal]:
    """The ledger's YES-equivalent net quantity per base slug (both legs summed with their sign)."""
    grouped: dict[str, list[LegFill]] = {}
    for fill in fills:
        slug = base_symbol_of(symbol_of_instrument_id(fill.instrument_id))
        grouped.setdefault(slug, []).append(leg_fill_of(fill))
    return {slug: net_signed_qty(legs) for slug, legs in grouped.items()}

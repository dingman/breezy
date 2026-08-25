"""Live-trading safety chokepoints for Polymarket.us order submission."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials


class LiveTradingPermissionError(PermissionError):
    """Raised when a live order submission lacks an explicit runtime permit."""


@dataclass(frozen=True, slots=True)
class LiveTradingPermit:
    """Runtime-only approval for live order submission."""

    operator_id: str
    max_order_notional_usd: Decimal
    issued_at_ns: int

    def __post_init__(self) -> None:
        if not self.operator_id.strip():
            raise ValueError("operator_id must not be empty")
        if self.max_order_notional_usd <= Decimal(0):
            raise ValueError("max_order_notional_usd must be positive")
        if self.issued_at_ns <= 0:
            raise ValueError("issued_at_ns must be positive")


def assert_live_order_submission_permitted(
    *,
    credentials: PolymarketUSCredentials | None,
    permit: LiveTradingPermit | None,
    manual_order_indicator: bool | None,
    order_notional_usd: Decimal,
) -> None:
    """Authorize the single future live create-order chokepoint.

    This must be called immediately before any order-submission request is
    dispatched. Credentials alone are never permission to trade.
    """
    if credentials is None or not credentials.is_complete():
        raise LiveTradingPermissionError("valid credentials are required for live trading")
    if permit is None:
        raise LiveTradingPermissionError("explicit live-trading permit is required")
    if manual_order_indicator is None:
        raise LiveTradingPermissionError("manualOrderIndicator must be explicit")
    if order_notional_usd <= Decimal(0):
        raise LiveTradingPermissionError("order notional must be positive")
    if order_notional_usd > permit.max_order_notional_usd:
        raise LiveTradingPermissionError("order notional exceeds permit maximum")

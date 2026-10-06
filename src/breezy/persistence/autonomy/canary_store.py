"""The canary store (AUT-2 r7 WP8, section 3.8, Z14): synthetic C1-shaped fills, kept apart.

A canary proves the labelling path on a UTC day with no real fill. Its fills live at
``derived/canary/<venue>/canary_fills_<YYYY-MM-DD>.jsonl`` and its labels at
``derived/labels_canary/<family_id>/``; neither is ever read by reconciliation, the entry guard,
portfolio-roi, the verdict ``n`` or the completeness identity. The only writer is
``label_run --canary`` under the studies flock.

The day's file is published once through ``single_read.write_once`` (directories 0700, file 0600):
the synthetic set is deterministic, so a re-run is an idempotent no-op and a differing set is
refused. No append primitive exists on purpose, which keeps this module free of a raw write site.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.canonical import canonical_json, decimal_str
from breezy.persistence.autonomy.paths import date_component, venue_component
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    ensure_dir,
    open_root,
    read_once_at,
    walk_dirs,
    write_once,
)

__all__ = [
    "CANARY_DIR",
    "CANARY_FILE_MODE",
    "CANARY_ID_PREFIX",
    "CANARY_SCHEMA",
    "LABELS_CANARY_DIR",
    "CanaryFill",
    "InvalidCanaryFill",
    "canary_relative_path",
    "read_canary_fills",
    "write_canary_fills",
]

CANARY_DIR: Final[tuple[str, ...]] = ("derived", "canary")
LABELS_CANARY_DIR: Final[tuple[str, ...]] = ("derived", "labels_canary")
CANARY_FILE_MODE: Final = 0o600
CANARY_SCHEMA: Final = "aut2_canary_fill/v1"
#: Every canary identifier starts with this, so one can never be mistaken for a real order id.
CANARY_ID_PREFIX: Final = "canary-"
_MAX_BYTES: Final = 4 * 1024 * 1024
_SIDES: Final = frozenset({"yes", "no"})
_ORDER_SIDES: Final = frozenset({"BUY", "SELL"})


class InvalidCanaryFill(ValueError):
    """A canary fill breaks the store's shape; nothing is written."""


@dataclass(frozen=True)
class CanaryFill:
    """One synthetic fill with its C1-shaped decision facts. ``source`` is always ``canary``."""

    venue_order_id: str
    client_order_id: str
    instrument_id: str
    order_side: str
    qty: Decimal
    cost: Decimal
    fee: Decimal
    ts_event: int
    trade_id: str
    decision_id: str
    family_id: str
    station: str
    climate_day: str
    rung_id: str
    side: str
    p_hat: str
    p_hat_raw: str


_STRINGS: Final = (
    "venue_order_id",
    "client_order_id",
    "instrument_id",
    "trade_id",
    "decision_id",
    "family_id",
    "station",
    "climate_day",
    "rung_id",
    "p_hat",
    "p_hat_raw",
)
_MONEY: Final = ("qty", "cost", "fee")


def canary_relative_path(venue: str, day: str) -> tuple[str, ...]:
    return (*CANARY_DIR, venue_component(venue), f"canary_fills_{date_component(day)}.jsonl")


def _check(fill: CanaryFill) -> None:
    for name in _STRINGS:
        value = getattr(fill, name)
        if not isinstance(value, str) or not value:
            raise InvalidCanaryFill(f"{name} must be a non-empty string")
    for name in ("venue_order_id", "client_order_id", "decision_id", "trade_id"):
        if not getattr(fill, name).startswith(CANARY_ID_PREFIX):
            raise InvalidCanaryFill(f"{name} must start with {CANARY_ID_PREFIX!r}")
    if fill.order_side not in _ORDER_SIDES or fill.side not in _SIDES:
        raise InvalidCanaryFill("order_side must be BUY/SELL and side yes/no")
    for name in _MONEY:
        value = getattr(fill, name)
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise InvalidCanaryFill(f"{name} must be a finite non-negative Decimal")
    if fill.qty <= 0:
        raise InvalidCanaryFill("qty must be positive")
    if isinstance(fill.ts_event, bool) or not isinstance(fill.ts_event, int) or fill.ts_event < 0:
        raise InvalidCanaryFill("ts_event must be a non-negative int")


def _wire(fill: CanaryFill) -> dict[str, object]:
    body: dict[str, object] = {name: getattr(fill, name) for name in _STRINGS}
    body.update(
        {
            "order_side": fill.order_side,
            "side": fill.side,
            "ts_event": fill.ts_event,
            **{name: decimal_str(getattr(fill, name)) for name in _MONEY},
            "schema": CANARY_SCHEMA,
            "source": "canary",
            "drill": False,
        }
    )
    return body


def write_canary_fills(data_root: Path, venue: str, day: str, fills: Sequence[CanaryFill]) -> Path:
    """Publish the day's canary fills once; identical bytes are a no-op, different are refused."""
    parts = canary_relative_path(venue, day)
    if not fills:
        raise InvalidCanaryFill("a canary day needs at least one fill")
    for fill in fills:
        _check(fill)
    data = b"".join(canonical_json(_wire(f)) + b"\n" for f in fills)
    rootfd = open_root(data_root)
    try:
        os.close(ensure_dir(rootfd, parts[:-1]))
    finally:
        os.close(rootfd)
    path = data_root.joinpath(*parts)
    write_once(path, data, root=data_root, mode=CANARY_FILE_MODE)
    return path


def _fill_of(line: bytes) -> CanaryFill:
    try:
        raw = json.loads(line)
        if raw["schema"] != CANARY_SCHEMA or raw["source"] != "canary" or raw["drill"] is not False:
            raise InvalidCanaryFill("a stored line is not a canary fill/v1")
        values = {n: raw[n] for n in _STRINGS}
        fill = CanaryFill(
            **values,
            order_side=raw["order_side"],
            side=raw["side"],
            ts_event=raw["ts_event"],
            qty=Decimal(raw["qty"]),
            cost=Decimal(raw["cost"]),
            fee=Decimal(raw["fee"]),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise InvalidCanaryFill("a stored canary line does not decode") from exc
    _check(fill)
    return fill


def read_canary_fills(data_root: Path, venue: str, day: str) -> tuple[CanaryFill, ...]:
    """The day's canary fills in stored order; an absent day is empty."""
    parts = canary_relative_path(venue, day)
    rootfd = open_root(data_root)
    try:
        try:
            dirfd = walk_dirs(rootfd, parts[:-1])
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return ()
            raise
        try:
            try:
                raw = read_once_at(dirfd, parts[-1], max_bytes=_MAX_BYTES, policy=ReadPolicy.STRICT)
            except SingleReadRefused as exc:
                if exc.reason is SingleReadReason.NOT_FOUND:
                    return ()
                raise
        finally:
            os.close(dirfd)
    finally:
        os.close(rootfd)
    return tuple(_fill_of(line) for line in raw.splitlines() if line)

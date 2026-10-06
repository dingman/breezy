"""AUT-2 r7 WP8 / section 3.8: the canary store is write-once, validated and private (0700/0600)."""

from __future__ import annotations

import stat
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy.canary_store import (
    CANARY_DIR,
    CanaryFill,
    InvalidCanaryFill,
    canary_relative_path,
    read_canary_fills,
    write_canary_fills,
)
from breezy.persistence.autonomy.single_read import SingleReadReason, SingleReadRefused

_DAY = "2026-10-02"
_VENUE = "polymarket_us"


def _fill(**over: Any) -> CanaryFill:
    base: dict[str, Any] = {
        "venue_order_id": "canary-vo-1",
        "client_order_id": "canary-O-1",
        "instrument_id": "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US",
        "order_side": "BUY",
        "qty": Decimal(1),
        "cost": Decimal("0.40"),
        "fee": Decimal("0.03"),
        "ts_event": 1_790_000_000_000_000_000,
        "trade_id": "canary-T-1",
        "decision_id": "canary-dec-1",
        "family_id": "pm_us_crh_fq_v1",
        "station": "LAX",
        "climate_day": _DAY,
        "rung_id": "89_90",
        "side": "yes",
        "p_hat": "0.62",
        "p_hat_raw": "0.62",
    }
    base.update(over)
    return CanaryFill(**base)


def test_canary_path_is_under_derived_canary_per_venue_and_day() -> None:
    assert CANARY_DIR == ("derived", "canary")
    assert canary_relative_path(_VENUE, _DAY) == (
        "derived",
        "canary",
        _VENUE,
        f"canary_fills_{_DAY}.jsonl",
    )


def test_fills_round_trip_with_private_modes(tmp_path: Path) -> None:
    fills = (_fill(), _fill(venue_order_id="canary-vo-2", client_order_id="canary-O-2", side="no"))

    path = write_canary_fills(tmp_path, _VENUE, _DAY, fills)

    assert read_canary_fills(tmp_path, _VENUE, _DAY) == fills
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_every_stored_fill_is_marked_canary_never_drill(tmp_path: Path) -> None:
    path = write_canary_fills(tmp_path, _VENUE, _DAY, (_fill(),))

    text = path.read_text()

    assert '"source":"canary"' in text and '"drill":false' in text


def test_second_identical_write_is_idempotent_and_different_is_refused(tmp_path: Path) -> None:
    write_canary_fills(tmp_path, _VENUE, _DAY, (_fill(),))
    write_canary_fills(tmp_path, _VENUE, _DAY, (_fill(),))

    with pytest.raises(SingleReadRefused) as caught:
        write_canary_fills(tmp_path, _VENUE, _DAY, (_fill(qty=Decimal(2)),))

    assert caught.value.reason is SingleReadReason.EXISTS_DIFFERENT


def test_absent_day_reads_empty(tmp_path: Path) -> None:
    assert read_canary_fills(tmp_path, _VENUE, _DAY) == ()


@pytest.mark.parametrize(
    "bad",
    [
        {"client_order_id": "O-1"},  # a real-looking id must never enter the canary store
        {"venue_order_id": "vo-1"},
        {"qty": Decimal(0)},
        {"order_side": "HOLD"},
        {"side": "maybe"},
        {"cost": Decimal(-1)},
    ],
)
def test_invalid_canary_fill_is_refused_before_any_write(
    tmp_path: Path, bad: dict[str, Any]
) -> None:
    with pytest.raises(InvalidCanaryFill):
        write_canary_fills(tmp_path, _VENUE, _DAY, (replace(_fill(), **bad),))

    assert not (tmp_path / "derived").exists()


def test_empty_fill_set_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidCanaryFill):
        write_canary_fills(tmp_path, _VENUE, _DAY, ())


def test_bad_venue_or_day_component_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Exception):  # noqa: B017 - the path validators raise WireRefused
        write_canary_fills(tmp_path, "../x", _DAY, (_fill(),))
    with pytest.raises(Exception):  # noqa: B017
        write_canary_fills(tmp_path, _VENUE, "2026-1-2", (_fill(),))

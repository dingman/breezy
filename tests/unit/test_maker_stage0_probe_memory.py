"""MAKER S2 WP0 -- the probe's preamble memory is bounded and its report is unchanged (S-5).

The verdict run was OOM-killed inside the probe because the ledger kept every gap-free ``Frame`` of
every rung of every instance until the last instance had been read. The frames now live in a
per-rung scratch store and the direction check folds one rung at a time. These tests pin that the
report is byte-for-byte what the in-memory implementation produced (the expected digest was
computed on the base commit, ae7801c1, by ``git archive``) and that no more than one rung's frames
are ever alive.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import AggressorSide, OrderSide
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity

from breezy.analysis.maker_tape_census import PrintRecord
from scripts.analysis import maker_stage0_probe as p
from scripts.analysis import maker_stage0_probe_frames as pf
from scripts.analysis.maker_stage0_probe_core import DirectionFold
from tests.unit.test_maker_stage0_probe import (
    _DAY,
    _LEVELS,
    _capture,
    _depth,
    _instrument,
    _ns,
    _slug,
    _trade,
    _write_instance,
)

# sha256 of json.dumps(report.to_dict(), sort_keys=True) on the base commit, on _world().
_BASE_DIGEST = "44666ae925605a8d4d1ee2b172448f4dac40c4d9e3e2ef4de30e36be4598a255"
_BASE_DIGEST_LAX_CONTROL = "bcb2951bfefb3c8420f882c95811672bdcb17da675608cd8187134035d0715ff"
_BASE_DIRECTION = "INSUFFICIENT"  # the world is thin on purpose: the tallies are in the digest


def _one_sided(instrument: BinaryOption, ts: int) -> OrderBookDepth10:
    """A frame whose best bid has no size: ``mid_of`` is None."""

    def side(px: str, size: str, order_side: OrderSide) -> list[BookOrder]:
        levels = [(px, size)] + [("0.000", "0")] * (_LEVELS - 1)
        return [
            BookOrder(order_side, Price.from_str(price), Quantity.from_str(qty), i)
            for i, (price, qty) in enumerate(levels)
        ]

    return OrderBookDepth10(
        instrument_id=instrument.id,
        bids=side("0.400", "0", OrderSide.BUY),
        asks=side("0.600", "10", OrderSide.SELL),
        bid_counts=[1] * _LEVELS,
        ask_counts=[1] * _LEVELS,
        flags=0,
        sequence=0,
        ts_event=ts,
        ts_init=ts,
    )


def _world(tmp_path: Path) -> Path:
    """Two identical instances (same frames and prints: ties and cross-instance overlap) and a
    third, read last, whose frame ties a stamp of the first two with a DIFFERENT mid."""
    capture = _capture(tmp_path, instance="inst-a")
    _capture(tmp_path, instance="inst-b")
    t = _ns
    lax = _instrument(_slug("lax"), t("2026-09-21T11:00:00"))
    lax2 = _instrument(_slug("lax", "gte90lt91f"), t("2026-09-21T11:00:00"))
    records = [
        _depth(lax, "0.290", "0.310", t("2026-09-22T05:30:00")),  # ties inst-a's 05:30, mid .30
        _depth(lax, "0.440", "0.460", t("2026-09-22T05:35:00")),
        _one_sided(lax2, t("2026-09-22T05:00:00")),
        _depth(lax2, "0.690", "0.710", t("2026-09-22T05:20:00")),
        _trade(lax, "c-1", "0.500", AggressorSide.BUYER, t("2026-09-22T05:31:00")),
        _trade(lax, "c-2", "0.400", AggressorSide.SELLER, t("2026-09-22T05:36:00")),
        _trade(lax2, "c-3", "0.600", AggressorSide.SELLER, t("2026-09-22T05:10:00")),
        _trade(lax2, "c-4", "0.700", AggressorSide.BUYER, t("2026-09-22T05:25:00")),
    ]
    _write_instance(
        capture,
        "inst-c",
        instruments=[lax, lax2],
        records=records,
        offsets=[(t("2026-09-22T01:30:00"), 3 * 1_000_000_000)],
    )
    return capture


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def test_the_probe_report_is_unchanged_by_the_frame_spill(tmp_path: Path) -> None:
    capture = _world(tmp_path)

    report = p.probe(capture, {_DAY}, ("LAX", "SFO"), work_root=tmp_path / "work")

    assert report.direction.verdict == _BASE_DIRECTION
    assert _digest(report.to_dict()) == _BASE_DIGEST
    lax = p.probe(capture, {_DAY}, ("LAX", "SFO"), work_root=tmp_path / "w2", control_station="LAX")
    assert _digest(lax.to_dict()) == _BASE_DIGEST_LAX_CONTROL
    assert not (tmp_path / "work" / "_frames").exists()  # the scratch store is removed


def test_the_scratch_store_is_removed_when_a_pass_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _world(tmp_path)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fold failed")

    monkeypatch.setattr(p, "fold_directions", boom)
    with pytest.raises(RuntimeError, match="fold failed"):
        p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert not (tmp_path / "work" / "_frames").exists()


_RUNGS = 6
_FRAMES_PER_RUNG = 40


def _many_rungs(tmp_path: Path) -> Path:
    """One instance: ``_RUNGS`` LAX rungs with ``_FRAMES_PER_RUNG`` in-window frames and a print."""
    capture = tmp_path / "capture"
    instruments = [
        _instrument(_slug("lax", f"gte{80 + n}lt{81 + n}f"), _ns("2026-09-21T11:00:00"))
        for n in range(_RUNGS)
    ]
    start = _ns("2026-09-22T03:00:00")
    records = [
        _depth(inst, "0.390", "0.410", start + k * 1_000_000_000)
        for inst in instruments
        for k in range(_FRAMES_PER_RUNG)
    ] + [
        _trade(inst, f"t{n}", "0.500", AggressorSide.BUYER, start + 60 * 1_000_000_000)
        for n, inst in enumerate(instruments)
    ]
    _write_instance(
        capture, "inst-a", instruments=instruments, records=records, offsets=[(start, 0)]
    )
    return capture


def test_the_probe_never_holds_more_than_one_rungs_frames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _many_rungs(tmp_path)
    real_load = pf.FrameSpill.load
    alive: list[int] = []

    def load(self: pf.FrameSpill, rung: str) -> list[p.Frame]:
        frames = real_load(self, rung)
        alive.append(len(frames))
        return frames

    monkeypatch.setattr(pf.FrameSpill, "load", load)
    report = p.probe(capture, {_DAY}, ("LAX",), work_root=tmp_path / "work")

    assert report.depth_frames == _RUNGS * _FRAMES_PER_RUNG
    assert alive == [_FRAMES_PER_RUNG] * _RUNGS  # one rung's frames per load, never the sum
    assert report.direction.buyer.n_agree == _RUNGS  # 0.50 >= the .40 mid, on every rung


def test_the_spill_round_trips_frames_exactly_and_sorts_stably(tmp_path: Path) -> None:
    spill = pf.FrameSpill(tmp_path / "frames")
    first = [p.Frame(30, Decimal("0.4")), p.Frame(10, None), p.Frame(20, Decimal("0.4050"))]
    second = [p.Frame(20, Decimal("0.6")), p.Frame(5, Decimal("0.123456789012345678"))]
    spill.append("r", first)
    spill.append("r", [])
    spill.append("r", second)

    loaded = spill.load("r")

    assert [(f.ts_ns, f.mid) for f in loaded] == [
        (5, Decimal("0.123456789012345678")),
        (10, None),
        (20, Decimal("0.4050")),  # equal stamps keep append order: first, then second
        (20, Decimal("0.6")),
        (30, Decimal("0.4")),
    ]
    assert spill.load("never-written") == []
    assert spill.rungs() == frozenset({"r"})
    spill.close()
    assert not (tmp_path / "frames").exists()


def test_the_rung_fold_equals_the_all_at_once_direction_result() -> None:
    frames = {
        "a": [p.Frame(10, Decimal("0.40")), p.Frame(30, None), p.Frame(50, Decimal("0.70"))],
        "b": [p.Frame(5, Decimal("0.55"))],
    }
    prints = [
        _print("a", "BUYER", "0.45", 20, "1"),
        _print("a", "SELLER", "0.45", 40, "2"),
        _print("a", "BUYER", "0.70", 60, "3"),
        _print("b", "SELLER", "0.55", 9, "4"),
        _print("b", "BUYER", "0.10", 8, "5"),
        _print("c", "BUYER", "0.10", 8, "6"),  # a rung with no frames
    ]
    want = p.direction_result(prints, frames)

    fold = DirectionFold()
    for rung in ("c", "b", "a"):
        fold.add([r for r in prints if r.rung == rung], {rung: frames.get(rung, [])})

    assert fold.result() == want


def _print(rung: str, side: str, price: str, ts: int, trade_id: str) -> PrintRecord:
    return PrintRecord(trade_id, ts, Decimal(price), side, rung, Decimal(1))

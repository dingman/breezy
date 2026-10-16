"""MAKER-S2 second look C3: the first-replayable check is report-only for a v2 block."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis.maker_stage0_first_replayable import check_first_replayable
from scripts.analysis.maker_stage0_inputs import InputRefused
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.unit import test_maker_stage0_pno as pno_fx
from tests.unit.test_maker_stage0_driver import _fresh, _ledger


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> rw.World:
    return rw.build_world(tmp_path_factory.mktemp("world"))


_OTHER_DAY = rw.FIRST_DAY + dt.timedelta(days=3)


@pytest.fixture(autouse=True)
def _calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())


def _frozen(block: int, first: dt.date) -> Any:
    return SimpleNamespace(block=block, first_replayable_day=first)


def _probed(day: str | None) -> Any:
    return SimpleNamespace(first_replayable_day=day)


def _shift_frozen(monkeypatch: pytest.MonkeyPatch, **change: Any) -> None:
    real = drv._preflight

    def patched(cfg: drv.RunConfig, mode: str) -> drv.Pre:
        pre = real(cfg, mode)
        return dataclasses.replace(pre, frozen=dataclasses.replace(pre.frozen, **change))

    monkeypatch.setattr(drv, "_preflight", patched)


def test_v2_records_but_never_refuses_on_first_replayable_day(
    world: rw.World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shift_frozen(monkeypatch, block=2, first_replayable_day=_OTHER_DAY)
    monkeypatch.setattr(drv, "_simulate_all", lambda *a, **k: None)
    monkeypatch.setattr(
        drv, "finish", lambda cfg, *a, **k: drv.RunSummary(cfg.out_dir, None, "x", "verdict")
    )
    cfg = _fresh(world, tmp_path)
    summary = drv.run(cfg)  # no RunVoided
    agreement = json.loads((cfg.out_dir / "wp0_agreement.json").read_text())
    assert agreement["first_replayable_day"] == rw.FIRST_DAY.isoformat()
    assert summary.first_replayable_observed == rw.FIRST_DAY.isoformat()
    assert [e["kind"] for e in _ledger(cfg)] == ["verdict_run_start"]


def test_v1_still_requires_equality(
    world: rw.World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shift_frozen(monkeypatch, first_replayable_day=_OTHER_DAY)
    cfg = _fresh(world, tmp_path)
    with pytest.raises(drv.RunVoided) as info:
        drv.run(cfg)
    assert isinstance(info.value.cause, InputRefused)
    assert "first print implies replayable day" in str(info.value.cause)
    assert [e["kind"] for e in _ledger(cfg)] == ["verdict_run_start", "void"]


def test_tail_only_refused_for_a_v2_block(
    world: rw.World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shift_frozen(monkeypatch, block=2)
    cfg = _fresh(world, tmp_path, tail_only=True, parity=(("SFO", 0),))
    with pytest.raises(InputRefused, match="--tail-only is not licensed for a v2 block.*Doc B"):
        drv.run(cfg)
    assert not cfg.out_dir.exists()
    assert not cfg.ledger.exists() or _ledger(cfg) == []


def test_check_first_replayable_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_io(*_a: object, **_k: object) -> None:
        raise AssertionError("I/O in a pure check")

    monkeypatch.setattr("builtins.open", no_io)
    monkeypatch.setattr(Path, "read_bytes", no_io)
    monkeypatch.setattr(Path, "write_text", no_io)
    v1, v2 = _frozen(1, rw.FIRST_DAY), _frozen(2, rw.FIRST_DAY)
    same, other = _probed(rw.FIRST_DAY.isoformat()), _probed(_OTHER_DAY.isoformat())
    assert check_first_replayable(same, v1) is None
    msg = check_first_replayable(other, v1)
    assert msg is not None and _OTHER_DAY.isoformat() in msg and rw.FIRST_DAY.isoformat() in msg
    assert check_first_replayable(other, v1) == msg
    assert check_first_replayable(other, v2) is None
    assert check_first_replayable(_probed(None), v2) is None


def test_v2_claim_writes_block_first_day_from_pre_frozen(
    world: rw.World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = drv.RunSummary(tmp_path, None, "x", "verdict")
    monkeypatch.setattr(drv, "_execute", lambda cfg, pre: sentinel)
    cfg = _fresh(world, tmp_path, block_first_day=_OTHER_DAY.isoformat())
    drv.run(cfg)
    start = _ledger(cfg)[0]
    assert start["block_first_day"] == _OTHER_DAY.isoformat()


def test_v1_claim_entry_keeps_six_keys(
    world: rw.World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = drv.RunSummary(tmp_path, None, "x", "verdict")
    monkeypatch.setattr(drv, "_execute", lambda cfg, pre: sentinel)
    cfg = _fresh(world, tmp_path)
    drv.run(cfg)
    assert "block_first_day" not in _ledger(cfg)[0]

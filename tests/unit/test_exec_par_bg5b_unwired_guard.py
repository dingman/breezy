"""EXEC-PAR BG-5b: fail closed at K>1 until the stage evaluator is wired (BG-6 is not built yet)."""

from __future__ import annotations

from pathlib import Path

from breezy.runtime.exec_par_stage_guard import (
    EVENT_STAGE_EVAL_UNWIRED,
    force_k1_unless_stage_eval_wired,
)
from breezy.runtime.health import AlertPayload
from breezy.runtime.submit_intent import open_submit_intent_latch


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


class _Sink:
    def __init__(self) -> None:
        self.emitted: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.emitted.append(payload)


def _latch(tmp_path: Path, k: int):  # type: ignore[no-untyped-def]
    return open_submit_intent_latch(
        _Store(), tmp_path / "s.db", max_slots=k, v2_predicate=lambda: True, clock_ns=lambda: 1
    )


def test_k2_without_ports_is_forced_to_k1_with_a_critical_alert(tmp_path: Path) -> None:
    sink = _Sink()
    with _latch(tmp_path, 2) as latch:
        assert force_k1_unless_stage_eval_wired(latch, stage_eval_ports=None, alert_sink=sink)
        assert latch.max_slots() == 1
        assert latch.k_forced_reason is not None
    assert [(p.severity, p.event) for p in sink.emitted] == [("CRITICAL", EVENT_STAGE_EVAL_UNWIRED)]
    assert EVENT_STAGE_EVAL_UNWIRED == "EXEC_PAR_STAGE_EVAL_UNWIRED"


def test_k2_with_ports_is_untouched(tmp_path: Path) -> None:
    sink = _Sink()
    with _latch(tmp_path, 2) as latch:
        assert not force_k1_unless_stage_eval_wired(
            latch,
            stage_eval_ports=object(),
            alert_sink=sink,
        )
        assert latch.max_slots() == 2
    assert sink.emitted == []


def test_k1_is_untouched_and_silent(tmp_path: Path) -> None:
    sink = _Sink()
    with _latch(tmp_path, 1) as latch:
        assert not force_k1_unless_stage_eval_wired(latch, stage_eval_ports=None, alert_sink=sink)
        assert latch.k_forced_reason is None
    assert sink.emitted == []


def test_trade_boot_calls_the_guard_before_the_watcher_is_built() -> None:
    text = (Path(__file__).resolve().parents[2] / "src/breezy/app/trade.py").read_text()
    guard = text.index("force_k1_unless_stage_eval_wired(")
    watcher = text.index("exec_watcher = build_exec_watcher(")
    assert guard < watcher


def test_the_boot_site_wires_no_ports_by_default_so_k_gt_1_fails_closed() -> None:
    from breezy.app import trade as app_trade

    assert app_trade._build_stage_eval_ports(object()) is None  # type: ignore[arg-type]

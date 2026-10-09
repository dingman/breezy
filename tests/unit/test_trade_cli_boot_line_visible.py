"""AMBIG-LATCH-RESUME section 5.4: the ``no_id_retire_admitted=`` boot line must reach the node log.

Nautilus's logging subsystem is live only once the node (kernel) exists, so a
stdlib record emitted while the config is BUILT is dropped by the real sink.
The sink below models that: it records only after a node was constructed.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from breezy.runtime import logging_bridge
from breezy.runtime.trade_cli import EXIT_OK, run
from tests.unit.test_trade_cli import (  # noqa: F401  (autouse fixtures)
    TRADE_ENV,
    RecordingNode,
    _clean_process_state,
    _no_send_alert_sink,
    _operator_order_ceiling,
)


class _LateLiveSink:
    """A Nautilus-logger stand-in that drops everything before the node exists."""

    lines: ClassVar[list[str]] = []

    def __init__(self, name: str) -> None:
        del name

    def _record(self, message: str) -> None:
        if RecordingNode.instances:
            type(self).lines.append(message)

    def debug(self, message: str) -> None:
        self._record(message)

    info = warning = error = debug


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_LateLiveSink]]:
    _LateLiveSink.lines = []
    monkeypatch.setattr(logging_bridge, "NautilusLogger", _LateLiveSink)
    logging_bridge.uninstall()
    yield _LateLiveSink
    logging_bridge.uninstall()


def _boot(monkeypatch: pytest.MonkeyPatch, admitted: bool, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "breezy.runtime.node_config.supervisor_admits_retirement_reason",
        lambda *_a, **_k: admitted,
    )
    env = {**TRADE_ENV, "POLYMARKET_US_EXEC_STATE_DB": str(tmp_path / "exec.db")}
    assert run(env=env, node_factory=RecordingNode, stderr=io.StringIO()) == EXIT_OK


def test_boot_line_true_reaches_the_node_log_sink(
    sink: type[_LateLiveSink], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _boot(monkeypatch, True, tmp_path)
    assert [m for m in sink.lines if "no_id_retire_admitted=" in m] == [
        "no_id_retire_admitted=True"
    ]


def test_boot_line_false_when_marker_absent(
    sink: type[_LateLiveSink], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _boot(monkeypatch, False, tmp_path)
    assert [m for m in sink.lines if "no_id_retire_admitted=" in m] == [
        "no_id_retire_admitted=False"
    ]

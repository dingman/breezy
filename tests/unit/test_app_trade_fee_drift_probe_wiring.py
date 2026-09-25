"""AUD-12b, wiring: the fee-drift probe runs on the live continuous node only.

Coordinator decision (2026-09-24): complete the live wiring, using exactly
the extension points identified for the Actor itself --
``trade_cli.run``'s new ``extra_actors`` seam (``node.trader.add_actor``,
BEFORE ``build()``, no new mechanism) and the ``after_build`` hook already
used for ``install_current_rung_hold_refusal_watch``.

Reuses the harness from ``test_trade_cli_current_rung_hold.py`` (env
builder, catalog writer, ``RecordingNode``) exactly as
``test_app_trade_continuous_exit_manifest.py`` already does, rather than
redefining it.

Every assertion that reads ``TrialDayLatch.is_family_halted()`` (via the
composition's own ``submit_veto``) or writes through
``record_policy_halt`` runs from INSIDE a node's ``run()`` override --
exactly the window ``test_trial_day_latch_is_the_shared_binding_opened_once``
uses this same harness for, and for the same reason: ``app.trade.run``'s
``ExitStack`` releases the shared submit-intent flock the instant its own
``run()`` returns, and a real, blocking ``node.run()`` would occupy that
window for the node's entire life. Asserting AFTER ``run()`` returns would
observe a released latch, not a live one.

``RecordingNode``'s fake kernel carries no ``data_engine`` (it only stands
in for the slice R-6a/R-7-PRE's guards read) -- used DELIBERATELY below to
exercise the probe's "no live client resolved yet" path, which takes the
exact same code path a real first-read transport failure would:
:meth:`FeeDriftProbeActor.probe_once` must swallow it into ``"UNKNOWN"``,
alert once, and never touch the family halt.
"""

from __future__ import annotations

import asyncio
import io
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.app.trade import run
from breezy.runtime.health import AlertPayload
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.trade_cli import EXIT_OK
from breezy.strategy.current_rung_hold.fee_drift_probe import FeeDriftProbeActor
from tests.unit.test_trade_cli_current_rung_hold import (  # noqa: F401 -- reused harness
    RecordingNode,
    _operator_order_ceiling,
    _trade_env,
    _write_today_catalog,
)


class _RecordingAlertSink:
    def __init__(self) -> None:
        self.emitted: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.emitted.append(payload)


def _fee_drift_actors(node: RecordingNode) -> list[FeeDriftProbeActor]:
    return [actor for actor in node.trader.actors if isinstance(actor, FeeDriftProbeActor)]


def _continuous_env(tmp_path: Path) -> dict[str, str]:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    return _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_cont",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )


def test_continuous_run_registers_exactly_one_fee_drift_probe_actor(tmp_path: Path) -> None:
    code = run(env=_continuous_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    assert len(_fee_drift_actors(node)) == 1


def test_current_rung_hold_run_never_registers_the_fee_drift_probe_actor(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    env = _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_v2",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )

    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    assert _fee_drift_actors(node) == []


def test_the_probes_first_read_failing_never_changes_boot_and_fails_closed_to_unknown(
    tmp_path: Path,
) -> None:
    results: dict[str, Any] = {}

    class _Capture(RecordingNode):
        def run(self) -> None:
            (actor,) = _fee_drift_actors(self)
            submit_veto = self.config.exec_clients[POLYMARKET_US_CLIENT_NAME].submit_veto
            results["outcome"] = asyncio.run(actor.probe_once())
            results["veto_after"] = submit_veto()
            super().run()

    code = run(env=_continuous_env(tmp_path), node_factory=_Capture, stderr=io.StringIO())

    assert code == EXIT_OK
    assert results["outcome"] == "UNKNOWN"
    assert results["veto_after"] is None, "an unresolved client must never itself halt the family"


def test_disagree_reaches_the_same_latch_the_submit_veto_reads_and_alerts_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _RecordingAlertSink()
    monkeypatch.setattr("breezy.app.trade.resolve_alert_sink", lambda: sink)
    results: dict[str, Any] = {}

    class _Capture(RecordingNode):
        def run(self) -> None:
            (actor,) = _fee_drift_actors(self)
            submit_veto = self.config.exec_clients[POLYMARKET_US_CLIENT_NAME].submit_veto
            results["veto_before"] = submit_veto()

            async def _disagreeing() -> Decimal:
                return Decimal("0.0695")

            actor._wire_fee_fetcher = _disagreeing
            results["outcome"] = asyncio.run(actor.probe_once())
            results["veto_after"] = submit_veto()
            super().run()

    code = run(env=_continuous_env(tmp_path), node_factory=_Capture, stderr=io.StringIO())

    assert code == EXIT_OK
    assert results["veto_before"] is None
    assert results["outcome"] == "DISAGREE"
    assert results["veto_after"] is not None, "DISAGREE must reach the SAME latch the veto reads"
    assert len(sink.emitted) == 1
    assert sink.emitted[0].severity == "CRITICAL"


def test_unknown_never_halts_but_still_alerts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _RecordingAlertSink()
    monkeypatch.setattr("breezy.app.trade.resolve_alert_sink", lambda: sink)
    results: dict[str, Any] = {}

    class _Capture(RecordingNode):
        def run(self) -> None:
            (actor,) = _fee_drift_actors(self)
            submit_veto = self.config.exec_clients[POLYMARKET_US_CLIENT_NAME].submit_veto
            results["outcome"] = asyncio.run(actor.probe_once())
            results["veto_after"] = submit_veto()
            super().run()

    code = run(env=_continuous_env(tmp_path), node_factory=_Capture, stderr=io.StringIO())

    assert code == EXIT_OK
    assert results["outcome"] == "UNKNOWN"
    assert len(sink.emitted) == 1
    assert results["veto_after"] is None

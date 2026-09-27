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
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.identifiers import ClientId
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.app.trade import _FeeVerifiedHolder, run
from breezy.runtime.health import AlertPayload
from breezy.runtime.settings import (
    LIVE_OBSERVATIONS_VAR,
    SENDING_FAMILY_ID_VAR,
    TRADE_CATALOG_ROOT_VAR,
)
from breezy.runtime.trade_cli import EXIT_OK
from breezy.strategy.current_rung_hold.fee_drift_probe import (
    FEE_COEFFICIENT_WIRE_KEY,
    FeeDriftProbeActor,
)
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


def _register_clock(actor: FeeDriftProbeActor, clock: TestClock) -> None:
    """`RecordingNode`'s fake `Trader.add_actor` never calls the native
    `register_base` (no real Nautilus registration in this harness -- see
    its own docstring), so `actor.clock` stays `None` unless a test that
    drives a DISAGREE (which reads `self.clock.timestamp_ns()` for the
    mismatch-alert dedupe window) registers one itself, exactly as
    `test_fee_drift_probe.py`'s own `_register` does."""
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )


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


def _v4_env(tmp_path: Path) -> dict[str, str]:
    """`pm_us_crh_v4` -- the LIVE family, registered at theta 0.0695, never
    0.06 (fee-drift-probe-target ruling, 2026-09-25)."""
    catalog_root = tmp_path / "catalog"
    catalog_root.mkdir()
    _write_today_catalog(catalog_root)
    return _trade_env(
        tmp_path,
        **{
            SENDING_FAMILY_ID_VAR: "pm_us_crh_v4",
            LIVE_OBSERVATIONS_VAR: "1",
            TRADE_CATALOG_ROOT_VAR: str(catalog_root),
        },
    )


def test_continuous_run_registers_exactly_one_fee_drift_probe_actor(tmp_path: Path) -> None:
    code = run(env=_continuous_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    assert len(_fee_drift_actors(node)) == 1


def test_the_probes_reference_theta_is_the_sending_familys_registered_one(tmp_path: Path) -> None:
    """Wiring RED test (fee-drift-probe-target ruling, 2026-09-25): the
    constructed Actor's reference must be `pm_us_crh_v4`'s OWN registered
    theta (0.0695), never the module-level `DOCUMENTED_TAKER_FEE_COEFFICIENT`
    (0.06) -- comparing against the wrong constant made the probe DISAGREE
    forever for this family."""
    code = run(env=_v4_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    (actor,) = _fee_drift_actors(node)
    assert actor._documented == Decimal("0.0695")


def test_wire_equal_to_the_registered_family_theta_agrees_with_no_alert_and_no_halt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect this ruling fixes, proven end to end: `pm_us_crh_v4` is
    registered at 0.0695, so a wire read of 0.0695 must AGREE -- before the
    fix this compared against the stale 0.06 pin and DISAGREED forever."""
    sink = _RecordingAlertSink()
    monkeypatch.setattr("breezy.app.trade.resolve_alert_sink", lambda: sink)
    results: dict[str, Any] = {}

    class _Capture(RecordingNode):
        def run(self) -> None:
            (actor,) = _fee_drift_actors(self)
            _register_clock(actor, TestClock())
            submit_veto = self.config.exec_clients[POLYMARKET_US_CLIENT_NAME].submit_veto

            async def _agreeing() -> Decimal:
                return Decimal("0.0695")

            actor._wire_fee_fetcher = _agreeing
            results["outcome"] = asyncio.run(actor.probe_once())
            results["veto_after"] = submit_veto()
            super().run()

    code = run(env=_v4_env(tmp_path), node_factory=_Capture, stderr=io.StringIO())

    assert code == EXIT_OK
    assert results["outcome"] == "AGREE"
    assert sink.emitted == []
    assert results["veto_after"] is None


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
            _register_clock(actor, TestClock())
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


class _NoClientsAttrDataEngine:
    """Simulates a future Nautilus rename that drops `_clients` -- item 2
    (silent-failure-hunter review, 2026-09-25): the guarded `getattr` chain
    must fail closed to UNKNOWN, never raise `AttributeError` and crash the
    probe or the node."""


def test_a_data_engine_missing_the_private_clients_attr_fails_closed_not_a_crash(
    tmp_path: Path,
) -> None:
    results: dict[str, Any] = {}

    class _Capture(RecordingNode):
        def run(self) -> None:
            self.kernel.data_engine = _NoClientsAttrDataEngine()
            (actor,) = _fee_drift_actors(self)
            results["outcome"] = asyncio.run(actor.probe_once())
            super().run()

    code = run(env=_continuous_env(tmp_path), node_factory=_Capture, stderr=io.StringIO())

    assert code == EXIT_OK
    assert results["outcome"] == "UNKNOWN"


class _FakeVenueHttpClient:
    def __init__(self, payload: dict[str, str]) -> None:
        self._payload = payload

    async def get_public(self, path: str, *, query: Any = None, quota_key: str) -> dict[str, str]:
        del path, query, quota_key
        return self._payload


def test_client_resolution_is_retried_each_probe_until_it_first_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 3 (silent-failure-hunter review, 2026-09-25): a first-resolve
    failure must not be cached forever -- a data client that only becomes
    available after the first probe fire must be picked up by the NEXT one."""
    fake_client = _FakeVenueHttpClient({"market": {FEE_COEFFICIENT_WIRE_KEY: "0.06"}})
    monkeypatch.setattr(
        "breezy.app.trade.shared_polymarket_us_http_client",
        lambda venue_config, clock: fake_client,
    )
    results: dict[str, Any] = {}

    class _FakeExecClient:
        _venue_config = object()

    class _FakeDataEngine:
        def __init__(self) -> None:
            self._clients = {ClientId(POLYMARKET_US_CLIENT_NAME): _FakeExecClient()}

    class _Capture(RecordingNode):
        def run(self) -> None:
            (actor,) = _fee_drift_actors(self)
            _register_clock(actor, TestClock())
            # No `data_engine` on this fake kernel yet -- the first fire
            # must fail closed to UNKNOWN, not raise.
            results["first"] = asyncio.run(actor.probe_once())
            # The data client "connects" between fires.
            self.kernel.data_engine = _FakeDataEngine()
            results["second"] = asyncio.run(actor.probe_once())
            super().run()

    code = run(env=_continuous_env(tmp_path), node_factory=_Capture, stderr=io.StringIO())

    assert code == EXIT_OK
    assert results["first"] == "UNKNOWN"
    assert results["second"] == "AGREE", "resolution must be retried, not cached as a failure"


# ---------------------------------------------------------------------------
# EDGE-1 (r2/AM-2..4): the late-bound `_FeeVerifiedHolder` and its wiring
# into the live composition root only.
# ---------------------------------------------------------------------------


def test_the_holder_starts_unbound_and_reads_as_unverified_before_the_probe_is_constructed() -> (
    None
):
    holder = _FeeVerifiedHolder()

    assert holder.is_fee_verified(0) is False


def test_the_holder_is_bound_to_the_real_probes_is_fee_verified_after_composition(
    tmp_path: Path,
) -> None:
    """AM-4: the holder is bound to the SAME actor the node registered --
    proven by mutating the actor's own staleness state directly and
    observing the composed strategy's `_fee_verified_check` reflect it live,
    never a stale snapshot taken at bind time."""
    code = run(env=_continuous_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    (actor,) = _fee_drift_actors(node)
    strategies = node.trader.strategies
    assert strategies
    strategy = strategies[0]
    assert strategy._fee_verified_check is not None

    assert strategy._fee_verified_check(0) is False, "unverified until the first AGREE"
    actor._last_agree_at_ns = 0
    assert strategy._fee_verified_check(0) is True, (
        "the holder must reflect the SAME actor's live state, not a snapshot"
    )


def test_the_live_composition_root_passes_a_non_none_fee_verified_check(
    tmp_path: Path,
) -> None:
    """AM-2: the live path (`app/trade.py`) is the ONE caller that passes a
    non-None check to `ContinuousRungHoldStrategy`."""
    code = run(env=_continuous_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    strategies = node.trader.strategies
    assert strategies
    assert all(strategy._fee_verified_check is not None for strategy in strategies)


def test_when_no_probe_is_built_the_holder_stays_unbound_and_vetoes_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AM-3: `_build_fee_drift_probe` returns `None` when no instrument
    resolves for any composed station (`trade.py:318-324`) -- the holder
    then stays unbound for the rest of the process's life, which reads as
    permanently unverified. Safe: nothing is tradable either way."""
    monkeypatch.setattr(
        "breezy.app.trade._representative_fee_drift_slug", lambda strategies: None,
    )

    code = run(env=_continuous_env(tmp_path), node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    node = RecordingNode.instances[-1]
    assert _fee_drift_actors(node) == [], "no probe should have been registered"
    strategies = node.trader.strategies
    assert strategies
    strategy = strategies[0]
    assert strategy._fee_verified_check is not None
    assert strategy._fee_verified_check(0) is False, (
        "an unbound holder must veto every entry, unconditionally"
    )

"""S4 WP2/WP4 (ARM maker-sharp B5): the ``BOOT_SWEEP_RESTING_NO_FILL`` admission guard.

``_sweep_retire_admitted`` is plumbed exactly like B4's ``resting_accept_admitted``
(client param, exec-client config field, factory, ``build_trade_node_config`` from
the supervisor decode marker, a boot proof line). Without it a swept no-id rest
stays AMBIGUOUS with the existing ``resolver_no_id_retire_blocked``-shaped
CRITICAL detail (r3 WP2). The retirement DRIVER (two consistent holding reads) is
B6; this module proves only the guard and that the default reason is unchanged.

No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import inspect
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import msgspec
import pytest

from breezy.adapters.polymarket_us.config import PolymarketUSExecClientConfig
from breezy.adapters.polymarket_us.factories import PolymarketUSLiveExecClientFactory
from breezy.runtime import logging_bridge
from breezy.runtime.trade_cli import EXIT_OK, run
from tests.unit.ambig_latch_rig import (
    gate_env,  # noqa: F401 -- used via usefixtures
    read_context,
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_ambig_no_id_resolver import _retirement
from tests.unit.test_polymarket_us_resting_adopt import _no_id_rest
from tests.unit.test_trade_cli_boot_line_visible import (
    TRADE_ENV,
    RecordingNode,
    _clean_process_state,  # noqa: F401  (autouse fixtures)
    _LateLiveSink,
    _no_send_alert_sink,  # noqa: F401
    _operator_order_ceiling,  # noqa: F401
)

SWEEP = submit_chain.RETIRE_BOOT_SWEEP_RESTING_NO_FILL


def test_the_exec_config_defaults_sweep_retire_admitted_to_false() -> None:
    """Fail closed: an unset config never admits the sweep reason."""
    by_name = {f.name: f for f in msgspec.structs.fields(PolymarketUSExecClientConfig)}
    assert by_name["sweep_retire_admitted"].default is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_sweep_retire_refused_until_supervisor_admits_boot_sweep_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, current, _command = await _no_id_rest(tmp_path, monkeypatch)
    context = read_context(client, current.intent_id)
    now = client._clock.timestamp_ns()
    # the OTHER decode marker is present: it must NOT stand in for the sweep one
    client._no_id_retire_admitted = True
    client._sweep_retire_admitted = False
    client._resolved_no_id_ts_ns = {**client._resolved_no_id_ts_ns, current.intent_id: now}
    client._resolve_no_order(current.intent_id, context, now, None, slug="", reason=SWEEP)
    assert client._latch.current_open() is not None, "refused: the intent stays OPEN"
    assert _retirement(client) is None
    detail = client.resolver_evidence_contradictions
    assert [d["event"] for d in detail] == ["resolver_no_id_retire_blocked"]
    assert detail[0]["severity"] == "CRITICAL"
    client._sweep_retire_admitted = True
    client._resolve_no_order(current.intent_id, context, now, None, slug="", reason=SWEEP)
    assert _retirement(client) == SWEEP
    assert client._latch.open_slot_count() == 0
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resolve_no_order_default_reason_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[CHAR] With no ``reason`` the retirement is still RESOLVER_NO_ID_NO_FILL and is
    gated by ``_no_id_retire_admitted`` alone (the sweep marker is irrelevant)."""
    client, current, _command = await _no_id_rest(tmp_path, monkeypatch)
    context = read_context(client, current.intent_id)
    now = client._clock.timestamp_ns()
    client._no_id_retire_admitted = True
    client._sweep_retire_admitted = False
    client._resolved_no_id_ts_ns = {**client._resolved_no_id_ts_ns, current.intent_id: now}
    client._resolve_no_order(current.intent_id, context, now, None, slug="")
    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    await client._disconnect()


# -- node_config / trade_cli plumbing ------------------------------------------------


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_LateLiveSink]]:
    _LateLiveSink.lines = []
    monkeypatch.setattr(logging_bridge, "NautilusLogger", _LateLiveSink)
    logging_bridge.uninstall()
    yield _LateLiveSink
    logging_bridge.uninstall()


def _boot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, admitted: set[str]) -> Any:
    monkeypatch.setattr(
        "breezy.runtime.node_config.supervisor_admits_retirement_reason",
        lambda _path, name: name in admitted,
    )
    env = {**TRADE_ENV, "POLYMARKET_US_EXEC_STATE_DB": str(tmp_path / "exec.db")}
    assert run(env=env, node_factory=RecordingNode, stderr=io.StringIO()) == EXIT_OK
    return RecordingNode.instances[-1].config


@pytest.mark.parametrize("sweep_admitted", [True, False])
def test_node_config_and_boot_line_carry_the_sweep_marker_independently(
    sink: type[_LateLiveSink],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sweep_admitted: bool,
) -> None:
    admitted = {"RESOLVER_NO_ID_NO_FILL", "ACCEPTED_RESTING"} | (
        {SWEEP} if sweep_admitted else set()
    )
    config = _boot(monkeypatch, tmp_path, admitted)
    exec_config = next(iter(config.exec_clients.values()))
    assert exec_config.sweep_retire_admitted is sweep_admitted
    assert exec_config.resting_accept_admitted is True
    assert [m for m in sink.lines if "sweep_retire_admitted=" in m] == [
        f"sweep_retire_admitted={sweep_admitted}"
    ]


def test_the_factory_hands_the_config_marker_to_the_client() -> None:
    """The factory forwards the field verbatim (no default, no environment read)."""
    source = inspect.getsource(PolymarketUSLiveExecClientFactory)
    assert "sweep_retire_admitted=config.sweep_retire_admitted" in source

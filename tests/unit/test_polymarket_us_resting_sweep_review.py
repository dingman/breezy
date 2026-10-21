"""S4 WP4 (ARM maker-sharp B5 review G6, G7, G13, G16): the boot sweep's refusal paths.

The sweep is the cancel-on-stop enforcement and the only retirement route for a prior
process's rests. Whenever it cannot finish -- it does not run, a ledger id is still listed
after the per-id pass, the claim "unbound orders are never cancelled" stops being true, or
the whole sweep overruns -- it LATCHES ``resting_cancel_unconfirmed`` (new rests refused, the
never-arm gate refuses) instead of leaving only a log line.

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.strategy.current_rung_hold.trial_day_latch import startup_evidence_refusal_reason
from tests.unit.ambig_latch_rig import (
    OPEN_ORDERS_PATH,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import CancelSender, _rig
from tests.unit.test_polymarket_us_resting_submit import _submit_rest
from tests.unit.test_polymarket_us_resting_sweep import (
    _EVIDENCE_KEY,
    _open_row,
    _second_process,
)

_LATCH: Final[str] = submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON


def _latched(client: Any) -> bool:
    return _LATCH in [r.reason for r in client._trading_refusals]


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("cause", ["no_sender", "canonical_unverified"])
async def test_a_sweep_that_does_not_run_latches_and_the_gate_refuses_the_own_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cause: str
) -> None:
    """G6: the rest could not be cancelled and the gate exempts own orders, so the
    refusal must be the latch (and the evidence must say so), not just a log line."""
    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    second = await _second_process(
        tmp_path,
        monkeypatch,
        rig.client,
        rig.client.latch_cm,
        sender=None if cause == "no_sender" else CancelSender(),
        payloads={OPEN_ORDERS_PATH: {"orders": [_open_row(command, 0)]}},
    )
    if cause == "canonical_unverified":
        monkeypatch.setattr(client_module.write_transport, "WRITE_CANONICAL_STRING_VERIFIED", False)
    await second._connect()
    assert _latched(second)
    evidence = json.loads(second._store_get(_EVIDENCE_KEY))
    assert [o["own_resting"] for o in evidence["open_orders"]] == [True]
    assert evidence["resting_cancel_unconfirmed"] is True
    assert startup_evidence_refusal_reason(evidence) == "resting_cancel_unconfirmed"
    assert not second.log_lines("error", "arm gate keeps refusing")
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_sweep_with_nothing_to_cancel_does_not_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=None
    )
    await second._connect()
    assert not _latched(second)
    await second._disconnect()

"""S4 WP5 (ARM maker-sharp B6): a no-id RESTING intent left by a PRIOR process.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md``
section 2 WP5 and r3 WP5 ("No-id resting, prior process (R2)"). After a restart a no-id
resting intent is never classified by the attribution join (the order is gone: the boot
sweep cancelled and read-confirmed its slug). Its ONLY retirement route is the sweep's
"swept" marker plus two consistent reads at least 60 s apart:

* (a) ``holding_delta_consistent`` is ``True`` against the context baseline;
* (b) no non-manual TRADE row on the slug at or after the intent's creation;

then ``_resolve_no_order(..., reason=BOOT_SWEEP_RESTING_NO_FILL)`` gated on
``_sweep_retire_admitted``. A fill while down (a is ``False`` or b is present) stays
AMBIGUOUS with the CRITICAL ``resting_no_id_fill_while_down``; an unevaluable ``a`` retries.

Every sender and private read is a local double: no network, no venue contact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import (
    SEC_NS,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    read_context,
    rig_slug,
    run_passes,
    submit_chain,
    trade_row,
    wire_payloads,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_ambig_no_id_resolver import _negative, _retirement
from tests.unit.test_polymarket_us_resting_adopt import _no_id_rest
from tests.unit.test_polymarket_us_resting_cancel import CancelSender
from tests.unit.test_polymarket_us_resting_sweep import _second_process

SLUG: Final[str] = rig_slug()
SWEEP: Final[str] = submit_chain.RETIRE_BOOT_SWEEP_RESTING_NO_FILL
DETAIL_REASON: Final[str] = "resting_no_id_fill_while_down"


async def _prior_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    sender: CancelSender | None,
    sweep_admitted: bool = True,
) -> tuple[Any, str, Any]:
    """A no-id resting take in process one; process two boots over its store, runs the
    boot sweep (``_connect``) and returns ``(client, intent_id, context)``."""
    first, current, _command = await _no_id_rest(tmp_path, monkeypatch)
    context = read_context(first, current.intent_id)
    second = await _second_process(tmp_path, monkeypatch, first, first.latch_cm, sender=sender)
    second._sweep_retire_admitted = sweep_admitted
    second._no_id_retire_admitted = True
    _negative(second)
    await second._connect()
    return second, current.intent_id, context


def _spy_classify(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    real = client_module.classify_no_id_evidence

    def spy(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(client_module, "classify_no_id_evidence", spy)
    return calls


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_prior_process_no_id_resting_intent_is_never_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No sender means the sweep cannot run: nothing is swept. The intent is returned from
    BEFORE any read or classification, however old it is, and stays AMBIGUOUS."""
    second, intent_id, _context = await _prior_process(tmp_path, monkeypatch, sender=None)
    assert intent_id not in second._swept_resting_intent_ids
    classify = _spy_classify(monkeypatch)
    reads_before = len(second._private_read.paths)
    second.advance(400)
    await run_passes(second, 2)
    assert classify == [], "never classified"
    assert [p for p in second._private_read.paths[reads_before:] if "activities" in p] == [], (
        "the attribution evidence (the activities join) was not even read for it"
    )
    assert second._latch.current_open() is not None
    assert _retirement(second) is None
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_unswept_no_id_resting_intent_stays_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sweep that ran but could not certify the slug empty swept nothing: the intent
    stays AMBIGUOUS even though every read looks clean."""
    sender = CancelSender()
    first, current, _command = await _no_id_rest(tmp_path, monkeypatch)
    second = await _second_process(tmp_path, monkeypatch, first, first.latch_cm, sender=sender)
    second._sweep_retire_admitted = True
    second._no_id_retire_admitted = True
    # the slug is busy on the sweep's certifying re-read: another order is open on it
    busy = {
        "id": "FOREIGN123456",
        "marketSlug": SLUG,
        "state": "ORDER_STATE_NEW",
        "tif": "TIME_IN_FORCE_GOOD_TILL_DATE",
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_MANUAL",
    }
    _negative(second, open_orders=[busy])
    await second._connect()
    assert current.intent_id not in second._swept_resting_intent_ids
    _negative(second)
    second.advance(400)
    await run_passes(second, 2)
    second.advance(70)
    await run_passes(second, 2)
    assert second._latch.current_open() is not None
    assert _retirement(second) is None
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_swept_no_fill_retires_boot_sweep_resting_no_fill_after_two_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second, intent_id, _context = await _prior_process(tmp_path, monkeypatch, sender=CancelSender())
    assert intent_id in second._swept_resting_intent_ids
    second.advance(305)
    await run_passes(second, 1)
    assert second._latch.current_open() is not None, "one consistent read retires nothing"
    second.advance(30)
    await run_passes(second, 1)
    assert _retirement(second) is None, "30 s is inside the recheck interval"
    second.advance(40)
    await run_passes(second, 1)
    assert _retirement(second) == SWEEP
    assert second._latch.open_slot_count() == 0
    assert second._resolver_contradiction_details.get(intent_id) is None
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_swept_retire_is_refused_until_the_supervisor_admits_the_sweep_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second, intent_id, _context = await _prior_process(
        tmp_path, monkeypatch, sender=CancelSender(), sweep_admitted=False
    )
    second.advance(305)
    await run_passes(second, 1)
    second.advance(70)
    await run_passes(second, 1)
    assert _retirement(second) is None
    detail = second._resolver_contradiction_details[intent_id]
    assert detail["event"] == "resolver_no_id_retire_blocked"
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_swept_retire_refused_on_non_manual_trade_row_on_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second, intent_id, context = await _prior_process(tmp_path, monkeypatch, sender=CancelSender())
    row = trade_row(
        ts_ns=context.created_ns + 20 * SEC_NS,
        order_id="AGGRESSOR-1",
        slug=SLUG,
        price="0.60",
        tif="TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
    )
    _negative(second, activities=[row])
    second.advance(305)
    await run_passes(second, 1)
    second.advance(70)
    await run_passes(second, 1)
    assert _retirement(second) is None
    detail = second._resolver_contradiction_details[intent_id]
    assert detail["severity"] == "CRITICAL"
    assert detail["reason"] == DETAIL_REASON
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_manual_trade_row_on_the_slug_does_not_block_the_swept_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator's own manual aggressor row is not our fill: (b) is about NON-manual rows.
    (The holding check (a) still has to explain its net effect; here the venue net moved by
    exactly that manual fill.)"""
    second, intent_id, context = await _prior_process(tmp_path, monkeypatch, sender=CancelSender())
    manual = trade_row(
        ts_ns=context.created_ns + 120 * SEC_NS,
        order_id="OPERATOR-1",
        slug=SLUG,
        price="0.60",
        tif="TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        manual=True,
    )
    # a manual YES buy raises the slug's venue net by exactly its fill quantity
    _negative(second, activities=[manual], positions={SLUG: {"netPosition": "1"}})
    second.advance(305)
    await run_passes(second, 1)
    second.advance(70)
    await run_passes(second, 1)
    assert intent_id not in second._resolver_contradiction_details
    assert _retirement(second) == SWEEP
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_restart_no_id_resting_filled_while_down_stays_ambiguous_and_alerts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The holding moved with no explaining manual fill: (a) is False. Stays AMBIGUOUS with
    the CRITICAL ``resting_no_id_fill_while_down`` and the operator clearing path."""
    second, intent_id, _context = await _prior_process(tmp_path, monkeypatch, sender=CancelSender())
    _negative(second, positions={SLUG: {"netPosition": "-1"}})
    second.advance(305)
    await run_passes(second, 1)
    second.advance(70)
    await run_passes(second, 2)
    assert _retirement(second) is None
    assert second._latch.current_open() is not None
    detail = second._resolver_contradiction_details[intent_id]
    assert detail["severity"] == "CRITICAL"
    assert detail["reason"] == DETAIL_REASON
    assert detail["next"] == client_module._RESTING_NO_ID_OPERATOR_CLEAR_NEXT
    alerts = [dict(a) for a in second.resolver_evidence_contradictions]
    assert any(a["reason"] == DETAIL_REASON for a in alerts)
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_swept_intent_with_unreadable_positions_retries_and_retires_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) not evaluable (the positions read fails): retry, never retire, never alert."""
    second, intent_id, _context = await _prior_process(tmp_path, monkeypatch, sender=CancelSender())
    payloads = wire_payloads(second)
    good = payloads["/v1/portfolio/positions"]
    del payloads["/v1/portfolio/positions"]
    second.advance(305)
    await run_passes(second, 2)
    assert _retirement(second) is None
    assert intent_id not in second._resolver_contradiction_details
    payloads["/v1/portfolio/positions"] = good
    second.advance(70)
    await run_passes(second, 1)
    second.advance(70)
    await run_passes(second, 1)
    assert _retirement(second) == SWEEP
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_this_process_no_id_rest_still_uses_the_attribution_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[CHAR] The same-process route is unchanged: classified by the join, retired
    ``RESOLVER_NO_ID_NO_FILL`` after two negative passes, never the sweep reason."""
    client, _current, _command = await _no_id_rest(tmp_path, monkeypatch)
    classify = _spy_classify(monkeypatch)
    client.advance(305)
    await run_passes(client, 1)
    client.advance(70)
    await run_passes(client, 1)
    assert classify, "the join ran"
    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    await client._disconnect()

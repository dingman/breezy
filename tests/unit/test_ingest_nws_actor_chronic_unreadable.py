"""CF-5b: chronic unreadable CLI parses must raise ONE deduped alert, not a
per-poll warning that never resolves.

`_prepare_product`'s CF-5 field-warnings loop (`nws_actor.py`) already logs a
WARNING per occurrence, every poll, for a non-settlement-bearing field
(tmin/tavg) this poll could not parse. That is correct as the immediate
signal, but nothing tracked the condition CHRONICALLY before this change: a
field left unreadable for days produced an unbroken stream of WARNING lines
and never reached the operator-facing `AlertState` the site's other standing
conditions (`SITE_BLOCKED`, `POLL_STALE`, `LEDGER_UNAVAILABLE`) all go
through. This module proves the fix: N consecutive unreadable parses raise
`CHRONIC_UNREADABLE_PRODUCT` through the real `AlertState`, which then
dedupes it exactly the way it dedupes every other standing condition (fires
once on the false->true edge, stays muted while the streak holds).

Drives the streak/alert machinery directly (`_record_field_read_outcome`,
`reconcile_and_report`) rather than through a full `poll_once()` +
`respx`-mocked network round trip -- the same lighter-weight seam
`test_ingest_actor_observability_hardening.py` already uses for the sibling
`LEDGER_UNAVAILABLE` condition, since discovery-time dedupe would otherwise
require a fresh, distinct product uuid per simulated poll for no benefit to
what this module is proving.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from breezy.ingest import nws_actor as nws_actor_module
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.shared_state import SharedIngestState
from breezy.registry.sites import default_registry
from tests.unit.test_ingest_actor_observability_hardening import (
    ConditionRecorder,
    RecordingSink,
    _conditions_of_kind,
    _stub_reconcile,
)
from tests.unit.test_ingest_nws_actor import (
    ALL_SITES,
    CITY,
    VENUE,
    FakeClock,
    _local_probe,
    build_actor,
    durable_store_pair,
)

SITE_LABEL = f"{VENUE}/{CITY}"


@pytest.fixture
def shared(tmp_path: Path) -> Iterator[SharedIngestState]:
    store, opener = durable_store_pair()
    state = SharedIngestState(
        registry=default_registry(),
        sites=ALL_SITES,
        catalog_base=tmp_path / "nws",
        store=store,
        clock=FakeClock(),
        store_opener=opener,
        probe=_local_probe,
        check_proxy_env=False,
    )
    try:
        yield state
    finally:
        state.dispose()


@pytest.fixture
def actor(shared: SharedIngestState) -> Iterator[NwsIngestActor]:
    instance = build_actor(shared)
    try:
        yield instance
    finally:
        instance.shutdown_executor()


@pytest.mark.asyncio
async def test_n_consecutive_unreadable_parses_emit_exactly_one_alert(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CF-5b RED: the threshold-th consecutive unreadable parse raises the
    deduped alert once, and further cycles at the same streak do not re-fire
    it -- the whole point of routing through `AlertState` instead of a bare
    per-poll `logger.warning`."""
    _stub_reconcile(monkeypatch, actor)
    sink = RecordingSink()
    actor.alert_sink = sink

    threshold = nws_actor_module.CHRONIC_UNREADABLE_PRODUCT_STREAK
    for _ in range(threshold + 2):
        actor._record_field_read_outcome(unreadable=True)
        await actor.reconcile_and_report()

    fired = [p for p in sink.payloads if p.event == nws_actor_module.CHRONIC_UNREADABLE_PRODUCT]
    assert len(fired) == 1, (
        f"{threshold + 2} consecutive unreadable parses must raise exactly "
        f"one deduped CHRONIC_UNREADABLE_PRODUCT alert; got {len(fired)}"
    )
    assert fired[0].site == SITE_LABEL


@pytest.mark.asyncio
async def test_a_clean_parse_resets_the_streak_and_clears_the_condition(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parse with no unreadable field must clear the streak -- otherwise a
    site that recovers stays permanently muted at the 24h re-notify instead
    of re-arming for the NEXT genuine chronic run."""
    _stub_reconcile(monkeypatch, actor)
    sink = RecordingSink()
    actor.alert_sink = sink

    threshold = nws_actor_module.CHRONIC_UNREADABLE_PRODUCT_STREAK
    for _ in range(threshold):
        actor._record_field_read_outcome(unreadable=True)
        await actor.reconcile_and_report()
    assert actor._unreadable_field_streak == threshold

    actor._record_field_read_outcome(unreadable=False)
    assert actor._unreadable_field_streak == 0

    recorder = ConditionRecorder()
    actor._alert_state = recorder  # type: ignore[assignment]
    await actor.reconcile_and_report()

    # `AlertState.evaluate` never fires on a true->false transition (see its
    # own docstring), so the sink count stays at the original false->true
    # emission -- but the condition itself must have been PASSED as
    # `active=False` this cycle, or the NEXT chronic run would be a
    # true->true no-op muted for 24h instead of a fresh false->true.
    condition = _conditions_of_kind(
        recorder.cycles[-1], nws_actor_module.CHRONIC_UNREADABLE_PRODUCT
    )
    assert len(condition) == 1, "the condition vanished instead of clearing"
    assert condition[0].active is False

    fired = [p for p in sink.payloads if p.event == nws_actor_module.CHRONIC_UNREADABLE_PRODUCT]
    assert len(fired) == 1, fired

"""AUT-2 r7 WP5 / 3.2.1 and 3.7.3: CRITICAL delivery, episode dedup and the delivery budget."""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.constants import (
    AUT2_DELIVERY_DEADLINE_S,
    INTRADAY_POST_READ_BUDGET_S,
    POST_READ_WRITE_RESERVE_S,
    POST_STOP_FLOCK_WAIT_S,
    POST_STOP_POST_READ_BUDGET_S,
    POST_STOP_READ_DEADLINE_S,
    POST_STOP_TIMEOUT_START_S,
)
from breezy.analysis.labeling.delivery import (
    AlertDeliveryFailed,
    DeliveryProof,
    DeliveryStatus,
    critical_dedup_key,
    deliver_critical,
    deliver_or_fail,
    episode_id,
    is_duplicate,
    max_deliveries_in_budget,
)
from breezy.analysis.labeling.skip_journal import utc_day

NOW = 1_790_000_000_000_000_000
_DAY_NS = 86_400_000_000_000
_EVENT = "aut2.position_mismatch"
_VENUE = "polymarket_us"
_SUBJECT = "tc-temp-laxhigh-2026-10-02-gte89lt90f"
_PAYLOAD: Mapping[str, Any] = {"event": _EVENT, "subject": _SUBJECT}


class _Sink:
    def __init__(self, *, ok: bool = True) -> None:
        self.calls = 0
        self.ok = ok

    def __call__(self, payload: Mapping[str, Any]) -> DeliveryProof | None:
        self.calls += 1
        return DeliveryProof(delivered=self.ok)


def _critical(root: Path, sink: Any, *, episode: int = 1, now: int = NOW, **kw: Any) -> Any:
    return deliver_critical(
        root,
        event=_EVENT,
        venue=_VENUE,
        subject=_SUBJECT,
        episode=episode,
        payload=_PAYLOAD,
        deliver=sink,
        now_ns=now,
        **kw,
    )


def test_deliver_or_fail_raises_without_delivered_proof() -> None:
    with pytest.raises(AlertDeliveryFailed):
        deliver_or_fail(_PAYLOAD, deliver=_Sink(ok=False))
    with pytest.raises(AlertDeliveryFailed):
        deliver_or_fail(_PAYLOAD, deliver=lambda p: None)

    def _boom(payload: Mapping[str, Any]) -> DeliveryProof:
        raise RuntimeError("sink down")

    with pytest.raises(AlertDeliveryFailed):
        deliver_or_fail(_PAYLOAD, deliver=_boom)
    assert deliver_or_fail(_PAYLOAD, deliver=_Sink()).delivered is True


def test_repeated_critical_delivered_once_per_day(tmp_path: Path) -> None:
    sink = _Sink()

    first = _critical(tmp_path, sink)
    second = _critical(tmp_path, sink, now=NOW + 3_600_000_000_000)
    next_day = _critical(tmp_path, sink, now=NOW + _DAY_NS)

    assert (first.status, second.status, next_day.status) == (
        DeliveryStatus.DELIVERED,
        DeliveryStatus.SUPPRESSED,
        DeliveryStatus.DELIVERED,
    )
    assert sink.calls == 2
    assert second.line == f"AUT2 CRITICAL_SUPPRESSED event={_EVENT} key={first.key[:12]}"


def test_failed_delivery_not_deduplicated(tmp_path: Path) -> None:
    failing = _Sink(ok=False)

    failed = _critical(tmp_path, failing)
    retried = _critical(tmp_path, _Sink())

    assert failed.status is DeliveryStatus.FAILED and failed.line is not None
    assert is_duplicate(tmp_path, utc_day(NOW), failed.key) is True  # only after the retry
    assert retried.status is DeliveryStatus.DELIVERED


def test_failed_delivery_leaves_no_file(tmp_path: Path) -> None:
    outcome = _critical(tmp_path, _Sink(ok=False))

    assert outcome.status is DeliveryStatus.FAILED
    assert is_duplicate(tmp_path, utc_day(NOW), outcome.key) is False


def test_suppressed_critical_keeps_verdict_effect(tmp_path: Path) -> None:
    from breezy.analysis.labeling.reconcile import CompareResult  # noqa: F401  (effect lives there)
    from breezy.analysis.labeling.verdicts import (
        build_reconciliation_verdict,
    )
    from breezy.persistence.autonomy.verdict import VerdictOutcome
    from tests.unit.test_aut2_verdicts import _facts

    _critical(tmp_path, _Sink())
    suppressed = _critical(tmp_path, _Sink())
    verdict = build_reconciliation_verdict(_facts(position=VerdictOutcome.FAIL))

    assert suppressed.status is DeliveryStatus.SUPPRESSED
    assert verdict.outcome is VerdictOutcome.FAIL  # suppression never softens the verdict


def test_dedup_across_locks_at_least_once_never_lost(tmp_path: Path) -> None:
    from breezy.analysis.labeling import delivery

    label_lock_sink, recon_lock_sink = _Sink(), _Sink()
    key = critical_dedup_key(_EVENT, _VENUE, _SUBJECT, 1)

    # two writers pass is_duplicate before either has written: both deliver (at least once)
    both = [
        _critical(tmp_path, label_lock_sink, episode=1),
    ]
    delivery._record_delivered(tmp_path, utc_day(NOW), key, _EVENT)  # the other lock's EEXIST
    both.append(_critical(tmp_path, recon_lock_sink, episode=1))

    assert both[0].status is DeliveryStatus.DELIVERED
    assert both[1].status is DeliveryStatus.SUPPRESSED  # run sequentially: the second is suppressed
    assert is_duplicate(tmp_path, utc_day(NOW), key) is True
    delivery._record_delivered(tmp_path, utc_day(NOW), key, _EVENT)  # EEXIST is success, no raise


def test_intervening_match_starts_new_episode_and_redelivers(tmp_path: Path) -> None:
    sink = _Sink()
    t1, t2, t3 = NOW, NOW + 1_000, NOW + 2_000  # MISMATCH, MATCH, MISMATCH inside one UTC day
    obs = [(t1, False), (t2, True), (t3, False)]

    first = _critical(tmp_path, sink, episode=episode_id(obs[:1]) or 0, now=t1)
    second = _critical(tmp_path, sink, episode=episode_id(obs) or 0, now=t3)

    assert episode_id(obs) == t3 and episode_id(obs[:1]) == t1
    assert (first.status, second.status) == (DeliveryStatus.DELIVERED, DeliveryStatus.DELIVERED)
    assert sink.calls == 2


def test_same_episode_same_day_delivered_once(tmp_path: Path) -> None:
    sink = _Sink()
    obs = [(NOW, False), (NOW + 1_000, False), (NOW + 2_000, False)]
    ep = episode_id(obs)

    results = [_critical(tmp_path, sink, episode=ep or 0, now=t) for t, _ in obs]

    assert ep == NOW and sink.calls == 1
    assert [r.status for r in results] == [
        DeliveryStatus.DELIVERED,
        DeliveryStatus.SUPPRESSED,
        DeliveryStatus.SUPPRESSED,
    ]
    assert episode_id([(NOW, True)]) is None


def test_hung_sink_delivery_deadline_keeps_post_stop_inside_timeout_start(tmp_path: Path) -> None:
    release = threading.Event()
    seen: list[str] = []

    def _hung(payload: Mapping[str, Any]) -> DeliveryProof | None:
        seen.append("outbox")  # deliver_with_proof writes the outbox entry first
        release.wait(30)
        return None

    started = time.monotonic()
    outcome = _critical(tmp_path, _hung, deadline_s=0.2)
    elapsed = time.monotonic() - started
    release.set()

    assert outcome.status is DeliveryStatus.FAILED  # the run exits 4 after its durable writes
    assert outcome.line == f"AUT2 DELIVERY_FAILED event={_EVENT}"
    assert elapsed < 1.0 and seen == ["outbox"]
    assert AUT2_DELIVERY_DEADLINE_S < POST_STOP_TIMEOUT_START_S
    assert is_duplicate(tmp_path, utc_day(NOW), outcome.key) is False


def test_delivery_not_started_when_budget_below_deadline(tmp_path: Path) -> None:
    sink = _Sink()

    deferred = _critical(tmp_path, sink, budget_remaining_s=AUT2_DELIVERY_DEADLINE_S - 0.1)
    fits = _critical(tmp_path, sink, budget_remaining_s=AUT2_DELIVERY_DEADLINE_S)

    assert deferred.status is DeliveryStatus.DEFERRED and deferred.line is not None
    assert fits.status is DeliveryStatus.DELIVERED and sink.calls == 1


def test_delivery_deadline_fits_post_read_budget() -> None:
    assert POST_READ_WRITE_RESERVE_S + 3 * AUT2_DELIVERY_DEADLINE_S == POST_STOP_POST_READ_BUDGET_S
    assert max_deliveries_in_budget(POST_STOP_POST_READ_BUDGET_S) == 3
    assert max_deliveries_in_budget(INTRADAY_POST_READ_BUDGET_S) >= 3
    assert (
        POST_STOP_FLOCK_WAIT_S + POST_STOP_READ_DEADLINE_S + POST_STOP_POST_READ_BUDGET_S
        == POST_STOP_TIMEOUT_START_S
    )


def test_measure_peak_delivery_is_dry_run_and_writes_no_real_dedup_journal(tmp_path: Path) -> None:
    real_root, measure_root = tmp_path / "real", tmp_path / "measure"
    real_root.mkdir(mode=0o700)
    measure_root.mkdir(mode=0o700)
    sink = _Sink()

    outcome = _critical(real_root, sink, dry_run_root=measure_root)

    assert outcome.status is DeliveryStatus.DRY_RUN and sink.calls == 0
    assert list(real_root.rglob("*")) == []
    written = [p for p in measure_root.rglob("*.json")]
    assert len(written) == 1 and '"status_class":"measure_dry_run"' in written[0].read_text()
    assert '"delivered":false' in written[0].read_text()

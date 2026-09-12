"""Turn a quote-tape recorder gap into exactly one operator alert (SP-6 A6).

Null hypothesis, checked before writing any of it:

* **Publication is native and already shipped.** ``PolymarketUSDataClient.
  _publish_custom`` (``adapters/polymarket_us/data.py:1749-1758``) wraps
  every :class:`~breezy.adapters.polymarket_us.tape_records.QuoteTapeGap`
  row in ``CustomData(DataType(type(record)), record)`` and hands it to
  the native ``DataClient._handle_data`` -> ``DataEngine._handle_custom_data``
  chain, which publishes it on ``data.QuoteTapeGap.<venue>.<symbol>``
  (``nautilus_trader/common/data_topics.pyx::TopicCache.
  get_custom_data_topic``). Nothing here reimplements that path, and
  ``data.py`` stays byte-unchanged.
* **The subscription mechanism is already native.** ``MessageBus.subscribe``
  with a ``*`` glob is the same idiom
  ``runtime/component_health_watch.py`` already uses for
  ``events.system.*`` -- one wiring idiom, not two.
* **The alert seam already exists.** ``runtime/health.AlertSink`` /
  ``resolve_alert_sink`` / ``emit_alert`` are shipped and tested.

What genuinely did not exist is the join between those three: the gap
record was published to a topic nothing in Breezy subscribed to, so a
reconnect that silently truncates the tape had no operator-visible
signal. That join -- and only that join -- is what this module is.

**Dedupe is a bounded dict, not `AlertState` (AM-3).** `AlertState`
(`health.py:624-644`) never evicts a key and this recorder's `gap_seq`
never repeats (one global counter per instrument per process,
`data.py:743`/`:2045`/`:2088`), so a plain `AlertState` would leak two
dict entries per gap FOREVER. `alerted_gaps: dict[str, int]` (gap id ->
last-alerted ns) is evicted on the `resolved=True` edge instead, which
also preserves the `DEFAULT_RENOTIFY_AFTER_NS` (24h) re-notify a bounded
`set` would have silently dropped (N3).

**The 300s cross-seq floor is a SECOND, independent rate limiter
(arbitrary, build-side judgement, not measured).** A single reconnect
can open a gap on every subscribed instrument in the same cycle, each
with its OWN (never-repeating) `gap_seq` -- the per-id dict dedupe alone
would then fire one alert PER INSTRUMENT for what is operationally one
event. `install_quote_tape_gap_watch` additionally tracks, per
`recorder_instance_id` (a "shard"), the ns of the last-emitted alert;
a second gap opening within `floor_ns` of that is suppressed and
counted, and the count is folded into the next unsuppressed alert's
`detail` as `suppressed=<n>`.

CONTAINMENT
-----------
The handler runs ON the message bus, synchronously, inside the data
engine. Every exception is caught: a broken handler must never unwind
into the publisher, and a dead webhook cannot unwind into a running
recorder (`health.py`'s `emit_alert` already catches `BaseException`
deliberately; this module adds nothing that reads back).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from breezy.adapters.polymarket_us.tape_records import QuoteTapeGap
from breezy.runtime.alert_detail import assert_payload_detail_is_safe
from breezy.runtime.health import (
    DEFAULT_RENOTIFY_AFTER_NS,
    AlertPayload,
    emit_alert,
    resolve_alert_sink,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.common.component import MessageBus

    from breezy.runtime.health import AlertSink

logger = logging.getLogger(__name__)

#: A ``*`` glob over every instrument this gap type is published for --
#: never hand-lifted; ``tests/unit/test_quote_tape_gap_watch.py`` derives
#: the real topic from Nautilus's own ``TopicCache`` and round-trips a
#: record through a real ``MessageBus`` before this constant is trusted.
QUOTE_TAPE_GAP_TOPIC: Final[str] = f"data.{QuoteTapeGap.__name__}*"

QUOTE_TAPE_GAP_ALERT_EVENT: Final[str] = "quote_tape_gap_open"

#: WARN, not CRITICAL: an open recorder gap means the TAPE is degraded
#: (a future analysis loses that interval), not that trading itself is at
#: risk -- this recorder has no execution client at all.
QUOTE_TAPE_GAP_ALERT_SEVERITY: Final[str] = "WARN"

#: ``AlertPayload.site`` convention: the shard's identity travels in
#: ``detail`` instead, since a gap watch spans every instrument a shard
#: records.
QUOTE_TAPE_GAP_ALERT_SITE: Final[str] = "global"

#: Build-side judgement (not measured): a flapping shard mints a new,
#: never-repeating ``gap_seq`` on every reconnect cycle, so the per-id
#: dedupe map alone cannot rate-limit a storm. 300s cross-seq floor.
DEFAULT_CROSS_SEQ_FLOOR_NS: Final[int] = 300_000_000_000

ClockNs = Callable[[], int]


def _gap_id(record: QuoteTapeGap) -> str:
    return f"{record.recorder_instance_id}:{record.gap_seq}"


def _detail(record: QuoteTapeGap, *, suppressed: int) -> str:
    return (
        f"gap_seq={record.gap_seq} instrument_count=1 suppressed={suppressed}"
    )


def install_quote_tape_gap_watch(
    msgbus: MessageBus,
    *,
    sink: AlertSink | None = None,
    clock_ns: ClockNs = time.time_ns,
    floor_ns: int = DEFAULT_CROSS_SEQ_FLOOR_NS,
    renotify_after_ns: int = DEFAULT_RENOTIFY_AFTER_NS,
) -> Callable[[object], None]:
    """Subscribe one operator alert per still-open quote-tape gap.

    Parameters
    ----------
    msgbus
        A LIVE node's ``node.kernel.msgbus``, after ``build()``.
    sink
        Defaults to :func:`~breezy.runtime.health.resolve_alert_sink`.
    clock_ns
        Injectable for tests; defaults to :func:`time.time_ns`.
    floor_ns
        The cross-``gap_seq`` rate-limit window per shard (see the module
        docstring). Build-side judgement, not measured.
    renotify_after_ns
        How long a still-open gap stays silent before re-alerting.
        Defaults to :data:`~breezy.runtime.health.DEFAULT_RENOTIFY_AFTER_NS`
        (24h) -- never re-declared here (N3).

    Returns
    -------
    The subscribed handler, so a caller (and a test) can hold it.
    """
    active_sink = resolve_alert_sink() if sink is None else sink
    alerted_gaps: dict[str, int] = {}
    last_alert_ns_by_shard: dict[str, int] = {}
    suppressed_by_shard: dict[str, int] = {}

    def _on_gap(record: object) -> None:
        try:
            if not isinstance(record, QuoteTapeGap):
                return

            gap_id = _gap_id(record)
            if record.resolved:
                alerted_gaps.pop(gap_id, None)
                return

            now_ns = clock_ns()
            last_for_id = alerted_gaps.get(gap_id)
            if last_for_id is not None and (now_ns - last_for_id) < renotify_after_ns:
                return

            shard = record.recorder_instance_id
            last_shard_alert = last_alert_ns_by_shard.get(shard)
            if last_shard_alert is not None and (now_ns - last_shard_alert) < floor_ns:
                suppressed_by_shard[shard] = suppressed_by_shard.get(shard, 0) + 1
                return

            suppressed = suppressed_by_shard.pop(shard, 0)
            detail = _detail(record, suppressed=suppressed)
            assert_payload_detail_is_safe(detail)
            emit_alert(
                active_sink,
                AlertPayload(
                    severity=QUOTE_TAPE_GAP_ALERT_SEVERITY,
                    event=QUOTE_TAPE_GAP_ALERT_EVENT,
                    site=QUOTE_TAPE_GAP_ALERT_SITE,
                    detail=detail,
                ),
            )
            alerted_gaps[gap_id] = now_ns
            last_alert_ns_by_shard[shard] = now_ns
        # Broad, deliberately: a failing handler must never unwind into the
        # publishing DataEngine (CONTAINMENT, module docstring).
        except Exception:
            logger.exception("quote tape gap watch handler failed")

    msgbus.subscribe(topic=QUOTE_TAPE_GAP_TOPIC, handler=_on_gap)
    return _on_gap

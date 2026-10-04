"""AUT-1 node-log online sinks (design S2-R1).

A ``LogSink`` consumes the classified events of ONE ``scan_node_log`` pass as they stream by, so
the audit's reducers (the R2 replay, the marker collector) never need the capped ``entry_lines``
list or a second pass over a gigabyte log. ``scan_node_log(..., sinks=...)`` calls every sink with
every event, in file order, BEFORE the scan's own accounting; a sink that raises aborts the scan
with ``NodeLogSinkFailed``.

The LogSink contract: ``feed`` holds BOUNDED state (a counter, a per-tick set, a per-key map), never
the events themselves; it must not mutate the event; and it may raise only to fail the day.

Non-writer, stdlib only.
"""

from typing import ClassVar, Final, Protocol

from breezy.analysis.capture_node_log_decisions import NodeLogEvent

__all__ = ["LogSink", "NodeLogSinkFailed"]

CAUSE_NODE_LOG_SINK_FAILED: Final[str] = "node_log_sink_failed"


class NodeLogSinkFailed(Exception):
    """A sink raised mid-scan (chained as ``__cause__``). The node-log package owns this error; the
    audit's ``gather_inputs`` maps it to ``AuditInputError("node_log_sink_failed")``."""

    cause: ClassVar[str] = CAUSE_NODE_LOG_SINK_FAILED


class LogSink(Protocol):
    """An online consumer of node-log events (bounded state; see the module docstring)."""

    def feed(self, event: NodeLogEvent) -> None: ...

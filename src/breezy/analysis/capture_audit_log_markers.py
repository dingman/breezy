"""AUT-1 WP5 stage 2b, W2: the marker collector sink (STUB).

Owner: stage-2b worktree W2. The marker GRAMMAR is not here: ``classify_line`` already yields the
typed marker events (``capture_node_log_markers``, S2-R2). ``MarkerParser`` is a ``LogSink`` that
collects them per ``(instance_id, UTC day)`` into ``LogMarkers`` with bounded state, switching on
each ``InstanceIdLine``. Signatures are pinned by ``tests/unit/test_capture_audit_stubs.py``.
"""

import datetime as dt
from collections.abc import Mapping

from breezy.analysis.capture_audit_input_types import LogMarkers, LogSink
from breezy.analysis.capture_node_log import NodeLogEvent

__all__ = ["MarkerParser"]


class MarkerParser(LogSink):
    """Collects marker events by boot and UTC day."""

    def __init__(self) -> None:
        raise NotImplementedError("AUT-1 stage 2b W2")

    def feed(self, event: NodeLogEvent) -> None:
        raise NotImplementedError("AUT-1 stage 2b W2")

    def markers(self) -> Mapping[tuple[str, dt.date], LogMarkers]:
        """The collected markers of each ``(instance_id, UTC day)`` seen."""
        raise NotImplementedError("AUT-1 stage 2b W2")

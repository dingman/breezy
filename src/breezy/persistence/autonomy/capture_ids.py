"""AUT-1 capture ids: ``decision_id``, the exit and orphan ids, and the per-frame ordinal counter.

Plan r12 section 3.4.1 (ids unchanged from r8 section 3.3.1; ARCH C1, R9.2-Z9). Pure and
Nautilus-free, so the node writer and the daily audit's replay share one definition. Recomputation
uses a record's own stored fields and never re-derives ``eval_ns`` or ``eval_seq``.

A frame reference is ``(frame_kind, instrument, frame_ts_event)`` (ER-3) and carries no hash, so
r8's payload-ref helpers (``depth_ref_of`` and friends) do not exist here.
"""

import hashlib
from collections.abc import Callable
from typing import Final

__all__ = [
    "DECISION_ID_HEX_LEN",
    "EVAL_SEQ_REORDER_BASE",
    "EVAL_SEQ_RETAINED_TS",
    "EvalSeqCounter",
    "compute_decision_id",
    "compute_exit_decision_id",
    "compute_orphan_decision_id",
]

DECISION_ID_HEX_LEN: Final[int] = 32
_SEPARATOR: Final[str] = "|"
_EXIT_DOMAIN: Final[str] = "exit/v1"
_ORPHAN_DOMAIN: Final[str] = "orphan/v1"

#: ``EvalSeqCounter`` keeps this many most-recent ``ts_event`` values per instrument (r8 H2).
EVAL_SEQ_RETAINED_TS: Final[int] = 4
#: Ordinals of a non-monotone (late, evicted) frame start here, disjoint from any real ordinal.
EVAL_SEQ_REORDER_BASE: Final[int] = 1_000_000


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:DECISION_ID_HEX_LEN]


def compute_decision_id(
    family_id: str,
    manifest_sha256: str,
    artefact_sha256: str,
    station: str,
    climate_day: str,
    rung_id: str,
    side: str,
    eval_ns: int,
    eval_seq: int,
) -> str:
    """First 32 hex of sha256 over the nine C1 fields joined by ``|``, in exactly this order."""
    return _digest(
        _SEPARATOR.join(
            (
                family_id,
                manifest_sha256,
                artefact_sha256,
                station,
                climate_day,
                rung_id,
                side,
                str(eval_ns),
                str(eval_seq),
            )
        )
    )


def compute_exit_decision_id(
    exit_rule: str, exit_position_id: str, exit_family_id: str, exit_client_order_id: str
) -> str:
    """Pure sha256 over the four native exit tag values only (C1 P1-8), in the pinned order."""
    return _digest(
        _SEPARATOR.join(
            (_EXIT_DOMAIN, exit_rule, exit_position_id, exit_family_id, exit_client_order_id)
        )
    )


def compute_orphan_decision_id(family_id: str, client_order_id: str) -> str:
    """The id of an untagged order's link (D12); no ``DecisionRecord`` ever carries it."""
    return _digest(_SEPARATOR.join((_ORPHAN_DOMAIN, family_id, client_order_id)))


class EvalSeqCounter:
    """The 0-based ordinal of an evaluation among all evaluations of one ``(instrument, ts_event)``.

    Counted across the quote and depth handler calls in arrival order (R-10) and for EVERY
    evaluation, admitted by the on-change filter or not. Memory is O(subscribed instruments): the
    last ``EVAL_SEQ_RETAINED_TS`` ``ts_event`` values are kept per instrument. A ``ts_event`` that
    is no longer retained and is older than the newest retained one is non-monotone: its ordinals
    start at ``EVAL_SEQ_REORDER_BASE`` and count up per instrument, so no ordinal repeats.
    ``on_nonmonotone`` (optional) is called with the instrument id on each such frame; the caller
    owns any rate limit on logging it.
    """

    def __init__(self, on_nonmonotone: Callable[[str], None] | None = None) -> None:
        self._on_nonmonotone = on_nonmonotone
        self._counts: dict[str, dict[int, int]] = {}
        self._reordered: dict[str, int] = {}

    def next(self, instrument_id: str, ts_event: int) -> int:
        counts = self._counts.setdefault(instrument_id, {})
        if ts_event in counts:
            counts[ts_event] += 1
            return counts[ts_event]
        if counts and ts_event < max(counts):
            return self._reordered_ordinal(instrument_id)
        counts[ts_event] = 0
        while len(counts) > EVAL_SEQ_RETAINED_TS:
            del counts[min(counts)]
        return 0

    def _reordered_ordinal(self, instrument_id: str) -> int:
        seen = self._reordered.get(instrument_id, 0)
        self._reordered[instrument_id] = seen + 1
        if self._on_nonmonotone is not None:
            self._on_nonmonotone(instrument_id)
        return EVAL_SEQ_REORDER_BASE + seen

    def retained(self, instrument_id: str) -> int:
        return len(self._counts.get(instrument_id, {}))

    def nonmonotone_count(self, instrument_id: str) -> int:
        return self._reordered.get(instrument_id, 0)

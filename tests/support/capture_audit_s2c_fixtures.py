"""PASS fixtures for the stage-2c integration tests (design S2-R25).

Each builder returns an ``AuditInputs`` that is internally consistent on every leg, so
``audit_day`` over it with the REAL legs is ``PASS``. ``PASS_FIXTURES`` is the registry the one
registry test walks: a PASS fixture added to it is checked for free.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from breezy.analysis.capture_audit_input_types import AuditInputs, IngestLine
from tests.support import capture_audit_w1_fixtures as w1
from tests.support.capture_audit_fixtures import GOOD_INGEST, make_replay

__all__ = ["PASS_FIXTURES", "RowsTape", "pass_entry_day", "pass_exit_day"]


class RowsTape(w1.DictTape):
    """A ``DictTape`` whose ``quote_rows`` and ``depth_rows`` hold the rows of its dict."""

    def _of(self, kind: str, instrument_id: str) -> Iterable[Mapping[str, Any]]:
        return [
            body
            for (k, instrument, _ts), body in self.rows.items()
            if (k, instrument) == (kind, instrument_id)
        ]

    def quote_rows(self, instrument_id: str, start_ns: int, end_ns: int) -> Iterable[Any]:
        return self._of("quote", instrument_id)

    def depth_rows(self, instrument_id: str, start_ns: int, end_ns: int) -> Iterable[Any]:
        return self._of("depth10", instrument_id)


def _clean_ingest(inp: AuditInputs) -> dict[str, Any]:
    rows = dict(getattr(inp.tape, "rows", {}))
    rows.setdefault(("quote", w1.INSTRUMENT, w1.FRAME_TS), w1.QUOTE_BODY)
    rows.setdefault(("depth10", w1.INSTRUMENT, w1.FRAME_TS), w1.DEPTH_BODY)
    return {
        "tape": RowsTape(rows=rows),
        "ingest_lines": (IngestLine(GOOD_INGEST),),
        "ingest_exited_after_rotation": True,
    }


def _consistent_replay(inp: AuditInputs) -> AuditInputs:
    """The live boot's replay counts exactly the decisions its ``c1`` holds: a ``TrySubmit`` is
    admitted but never advances the evaluation counter (design S2-R5)."""
    boot = inp.boots[0]
    kinds = Counter(decision.kind for decision in boot.c1.decisions)
    evaluations = sum(count for kind, count in kinds.items() if kind != "TrySubmit")
    replay = make_replay(
        admitted_total=sum(kinds.values()),
        admitted_by_kind=dict(kinds),
        evaluations=evaluations,
        eval_seq_final=max(evaluations - 1, 0),
    )
    return w1.replace_boot(inp, replay=replay)


def pass_entry_day(**over: Any) -> AuditInputs:
    """One BUY fill with its decision, order link, frame copy, tape frame and settlement."""
    base = w1.entry_day()
    return _consistent_replay(w1.entry_day(**{**_clean_ingest(base), **over}))


def pass_exit_day(**over: Any) -> AuditInputs:
    """The exit-side counterpart of ``pass_entry_day``."""
    base = w1.exit_day()
    return _consistent_replay(w1.exit_day(**{**_clean_ingest(base), **over}))


PASS_FIXTURES: Final[Mapping[str, Callable[[], AuditInputs]]] = {
    "entry_day": pass_entry_day,
    "exit_day": pass_exit_day,
}

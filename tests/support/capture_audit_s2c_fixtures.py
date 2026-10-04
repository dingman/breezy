"""PASS fixtures for the stage-2c integration tests (design S2-R25).

Each builder returns an ``AuditInputs`` that is internally consistent on every leg, so
``audit_day`` over it with the REAL legs is ``PASS``. ``PASS_FIXTURES`` is the registry the one
registry test walks: a PASS fixture added to it is checked for free.
"""

import dataclasses
import datetime as dt
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from breezy.analysis.capture_audit_input_types import (
    AuditInputs,
    FunnelCount,
    FunnelRow,
    IngestLine,
)
from breezy.analysis.capture_audit_replay import BootReplay
from breezy.analysis.capture_node_log_decisions import (
    KIND_TAKE,
    KIND_TRY_SUBMIT,
    DecisionLine,
    InstanceIdLine,
    TakeInputs,
)
from tests.support import capture_audit_w1_fixtures as w1
from tests.support.capture_audit_fixtures import GOOD_INGEST, NS, make_replay

#: The funnel flush lands at 19:00 UTC: clear of every decision stamp by more than the race window.
_FUNNEL_FLUSH_HOUR: Final[int] = 19

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


def _log_lines(inp: AuditInputs) -> list[DecisionLine]:
    """The node-log decision lines that produced the boot's entry records: one ``Take`` or
    ``TrySubmit`` line per such record, stamped with the clock R1 and R2 key on (a Take's
    ``eval_ns``, a follow-up's ``wall_ns``). ``Exit`` records have no ``SHADOW_DECISION`` line."""
    lines: list[DecisionLine] = []
    for record in inp.boots[0].c1.decisions:
        if record.kind not in (KIND_TAKE, KIND_TRY_SUBMIT):
            continue
        is_take = record.kind == KIND_TAKE
        now_ns = record.eval_ns if is_take else record.wall_ns
        lines.append(
            DecisionLine(
                line_no=len(lines) + 1,
                log_ts_ns=now_ns,
                component="BREEZY-L001",
                now_ns=now_ns,
                station=record.station,
                climate_day=dt.date.fromisoformat(record.climate_day),
                rung_id=record.rung_id,
                side=record.side,
                instrument_id=record.instrument_id,
                kind=record.kind,
                reason=None if is_take else record.reason,
                take=TakeInputs(qty=1, ev_net=0.1, p_hat=0.5, p_lower=0.4, p_upper=0.6)
                if is_take
                else None,
            )
        )
    return lines


def _consistent_node_evidence(inp: AuditInputs) -> AuditInputs:
    """The boot's node-log scan, REAL replay and funnel row, all derived from its own records, so
    R1 (bijection), R2 (replay equals stream) and R3 (funnel equals log) pass without any leg
    skipping (S2-R36, S2-R48). The replay is ``BootReplay`` fed the very lines the scan holds."""
    boot = inp.boots[0]
    assert boot.scan is not None
    lines = _log_lines(inp)
    replay_sink = BootReplay()
    replay_sink.feed(InstanceIdLine(0, 0, boot.instance_id))
    for line in lines:
        replay_sink.feed(line)
    replay = replay_sink.results().get((boot.instance_id, inp.day)) or make_replay()
    counts = Counter(
        (line.station, line.side, line.kind, "" if line.kind == KIND_TAKE else line.reason or "")
        for line in lines
    )
    scan = dataclasses.replace(
        boot.scan,
        entry_lines=tuple(lines),
        entry_total=len(lines),
        decision_line_count=len(lines),
        kind_counts=dict(Counter(line.kind for line in lines)),
    )
    funnel_row = FunnelRow(
        w1.DAY_START_NS + _FUNNEL_FLUSH_HOUR * 3600 * NS,
        inp.day.isoformat(),
        tuple(FunnelCount(*key, count) for key, count in sorted(counts.items())),
    )
    return dataclasses.replace(w1.replace_boot(inp, scan=scan, replay=replay), funnel=(funnel_row,))


def pass_entry_day(**over: Any) -> AuditInputs:
    """One BUY fill with its decision, order link, frame copy, tape frame and settlement."""
    base = w1.entry_day()
    return _consistent_node_evidence(w1.entry_day(**{**_clean_ingest(base), **over}))


def pass_exit_day(**over: Any) -> AuditInputs:
    """The exit-side counterpart of ``pass_entry_day``."""
    base = w1.exit_day()
    return _consistent_node_evidence(w1.exit_day(**{**_clean_ingest(base), **over}))


PASS_FIXTURES: Final[Mapping[str, Callable[[], AuditInputs]]] = {
    "entry_day": pass_entry_day,
    "exit_day": pass_exit_day,
}

"""Test support: a stage-eval stamp of THIS boot, so K>1 fixtures clear the BG-6 boot gate.

At configured K>1 ``SubmitIntentLatch`` denies entries with ``stage_eval_boot_pending`` until a
stamp with ``boot_ns == latch.boot_ns`` and ``ts_ns >= latch.boot_ns`` exists (D-PREREG r4 1a).
Fixtures that are about something else (slots, the order path, the resolver) publish one here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from breezy.runtime.exec_par_records import StageEvalStamp


def fresh_stamp(latch: Any, ts_ns: int | None = None) -> None:
    """Write a stamp of this boot at ``ts_ns`` (default: the boot instant itself)."""
    boot = latch.boot_ns
    latch.write_stage_eval_stamp(StageEvalStamp(boot if ts_ns is None else max(ts_ns, boot), boot))


@contextmanager
def stamp_gate_stood_down(latch: Any) -> Iterator[None]:
    """Stand the BG-6 stamp gate down for fixture arms made in the PAST.

    A slot hand-armed with ``now_ns`` before this boot models a slot a previous process left
    behind. The gate judges the caller's ``now_ns``, so it can never be satisfied for such an
    arm (a stamp of this boot is, by definition, newer). Only the fixture arm is exempt; the
    gate itself is under test in ``test_exec_par_bg6_latch_denial``.
    """
    latch._stage_stamp_denial = lambda now_ns: None
    try:
        yield
    finally:
        del latch._stage_stamp_denial

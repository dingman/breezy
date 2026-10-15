"""MAKER-S2 S-5 follow-up world: one station, two replayable days whose ladders differ in parity.

``rw.build_capture`` carries SFO 2026-09-29 with an even-lower-edge ladder (80, 82, 84, 86).
This adds a second recorder instance holding SFO ``ODD_DAY`` with an odd-lower-edge ladder
(81, 83, 85, 87). The driver keeps the first replayed day's parity, so the ladder parity of the
station is the even one although the last replayed day is odd.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from tests.fixtures.maker_stage0 import replay_world as rw
from tests.unit.test_maker_stage0_probe import _depth, _instrument, _slug, _write_instance

ODD_DAY = dt.date(2026, 10, 3)  # after rw.DAY, so first-wins (0) and last-wins (1) differ
ODD_RUNGS = ("lt81f", "gte81lt82f", "gte83lt84f", "gte85lt86f", "gte87f")
FIRST_DAY_PARITY = 0  # rw.DAY (even lower edges) is replayed before ODD_DAY
LATER_DAY_PARITY = 1


def build_two_parity_capture(root: Path, **kwargs: Any) -> Path:
    """The base fixture capture plus an ``inst-odd`` instance for ``ODD_DAY``."""
    capture = rw.build_capture(root, **kwargs)
    prior = (ODD_DAY - dt.timedelta(days=1)).isoformat()
    listed = rw._t(f"{prior}T08:00:00")
    rungs = [_instrument(_slug("sfo", r, ODD_DAY.isoformat()), listed) for r in ODD_RUNGS]
    records = [
        _depth(inst, "0.150", "0.250", rw._t(f"{prior}T{hour}"))
        for hour in ("17:00:00", "20:30:00", "22:30:00")
        for inst in rungs
    ]
    _write_instance(capture, "inst-odd", instruments=rungs, records=records, offsets=[])
    return capture

"""Celsius-tenths <-> Fahrenheit conversion and rounding.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no global
state.

PORT, not import. `round_half_up_f` and `c_tenths_to_f` are a minimal PORT of
`scripts/analysis/settlement_alignment_study.py:192-198` -- the two functions
must exist independently in `src/` because `scripts/` is deliberately outside
the `breezy` package (see that module's own docstring) and `domain` may not
import from `scripts/`. The port is pinned against the original by a
differential test in `tests/unit/test_domain_temperature.py` so the two
copies cannot silently drift.

`round_half_up_f` rounds half AWAY FROM the floor (i.e. `x.5` always rounds
UP, never "round half to even") -- this is the settlement convention NWS
publishes under, ported verbatim including its use of `math.floor(x + 0.5)`
rather than `round()`.
"""

from __future__ import annotations

import math


def c_tenths_to_f(c_tenths: int) -> float:
    """Convert tenths of a degree Celsius to Fahrenheit, exactly as the port source."""
    return (c_tenths / 10.0) * 9.0 / 5.0 + 32.0


def round_half_up_f(c_tenths: int) -> int:
    """Convert tenths of a degree Celsius to Fahrenheit, rounded half up."""
    fahrenheit = c_tenths_to_f(c_tenths)
    return math.floor(fahrenheit + 0.5)

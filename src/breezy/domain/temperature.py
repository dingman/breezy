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

`max_rounded_f_below` (BL-24 Seam A-2 fix) answers a different question:
given a real-valued, half-open Celsius-tenths interval `[.., c_tenths_exclusive)`
whose upper end is NOT on the tenths grid but approached from below by a
CONTINUOUS real temperature, what is the largest whole-F value
`round_half_up_f` can ever produce for a value strictly inside that
interval? `round_half_up(y) = floor(y + 1/2)` is monotone non-decreasing and
right-continuous, so it is maximized in the limit as the real Celsius value
approaches the interval's exclusive upper bound. With `U` the EXACT (exact
Fraction, never float) Fahrenheit conversion of `c_tenths_exclusive` and
`v = U + 1/2`, the supremum of `floor(y + 1/2)` over reals `y < U` is
`ceil(v) - 1` -- equal to `floor(v)` unless `v` is itself an integer, in
which case the supremum is `v - 1` (never attained, but rounding is
integer-valued so the largest ACHIEVED value is exactly `v - 1`).
"""

from __future__ import annotations

import math
from fractions import Fraction


def c_tenths_to_f(c_tenths: int) -> float:
    """Convert tenths of a degree Celsius to Fahrenheit, exactly as the port source."""
    return (c_tenths / 10.0) * 9.0 / 5.0 + 32.0


def round_half_up_f(c_tenths: int) -> int:
    """Convert tenths of a degree Celsius to Fahrenheit, rounded half up."""
    fahrenheit = c_tenths_to_f(c_tenths)
    return math.floor(fahrenheit + 0.5)


def max_rounded_f_below(c_tenths_exclusive: Fraction | int) -> int:
    """Max whole-F `round_half_up` can produce below the given EXCLUSIVE Celsius-tenths bound.

    `c_tenths_exclusive` is tenths of a degree C and may be a `Fraction`
    (e.g. a half-integer tenths boundary); exact `Fraction` arithmetic is
    used throughout -- never `float` -- so the boundary case (`v` exactly
    an integer) is decided precisely rather than by floating-point luck.
    See the module docstring for the derivation.
    """
    exact_c_tenths = Fraction(c_tenths_exclusive)
    exact_f = (exact_c_tenths / 10) * 9 / 5 + 32
    v = exact_f + Fraction(1, 2)
    return math.ceil(v) - 1

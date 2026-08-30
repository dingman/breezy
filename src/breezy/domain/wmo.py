"""WMO abbreviated-heading BBB-token interpretation, shared across layers.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no
global state.

This is the BOTTOM layer's copy of "does this BBB token mean CORRECTION?"
The predicate is evaluated in two independent places -- `normalize.cli_parse`
(structural parse of a live/archived product) and `domain.archived_climate_day`
(the frozen archived record's own cross-check) -- and both must derive the
verdict from this one function so the two can never drift apart. `domain` is
the bottom layer (see `pyproject.toml`'s `importlinter` layer contract), so
this lives here and `normalize` imports it downward; the reverse import would
be illegal.
"""

from __future__ import annotations

import re

_CORRECTION_BBB_RE = re.compile(r"^CC[A-Z]$")
"""A BBB indicator that means CORRECTION, and only that.

The BBB space is NOT a correction flag -- it is four different things:

    ``CCx``  correction to a previously transmitted product   <- correction
    ``AAx``  amendment                                        <- NOT
    ``RRx``  delayed / retransmitted report                   <- NOT
    ``Pxx``  message segment number                           <- NOT

`CC[A-Z]`, not `CC[AB]`: corrections run CCA, CCB, CCC, ... and a third
correction to one climate day is exactly the case most likely to land
AFTER settlement. Matching only the first two would be a false negative on
the highest-consequence instance of the signal.

This range is kept IDENTICAL to `normalize.classify._CORRECTION_RE`, which
answers the same question from the free text. The two signals differ in COVERAGE
by design (the free-text scan is a deliberate superset that also catches
CORRECTED/CORRECTION wording in a body with no BBB token at all), but they
must never differ in ALPHABET: two signals for one concept disagreeing
about which letters count is a contradiction waiting to be found by
whoever wires either one into `revision_seq`.
`tests/unit/test_normalize_correction_signal_agreement.py` fails if the
two are changed independently -- change both or neither."""


def is_correction_bbb_token(bbb: str | None) -> bool:
    """Is this BBB indicator a correction (``CCx``), as opposed to an
    amendment, a retransmission, a segment number, or nothing at all?

    Published as the `is_correction_bbb` property of `CliStructuralHeader`
    and `ParsedCliProduct` (`normalize.cli_parse`), and as the constructor
    cross-check on `domain.archived_climate_day.ArchivedClimateDay`, so a
    caller reads a decided boolean instead of re-deriving one from a token
    whose spelling it would have to know.
    """
    if bbb is None:
        return False
    return _CORRECTION_BBB_RE.match(bbb) is not None

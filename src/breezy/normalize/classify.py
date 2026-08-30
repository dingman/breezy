"""Preliminary vs final CLI classification, and correction-evidence detection.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no
global state. Classification predicates are pure functions with no clock
access, so they behave identically live and in replay.

CRITICAL, recently corrected (2026-08-22): both the preliminary and final
CLI issuances read "...THE <SITE> CLIMATE SUMMARY FOR <DATE>...". An
earlier rule claiming the final reads "CLIMATE REPORT" while the
preliminary reads "CLIMATE SUMMARY" is FALSE -- both use "CLIMATE
SUMMARY" in the headline. The actual discriminator is a separate line:
the preliminary carries "VALID TODAY AS OF 0400 PM LOCAL TIME." and the
final does not.

Never classify on `issuanceTime` (a late-polled final can have an
issuanceTime that sorts oddly relative to a same-day preliminary) and
never on REPORT-vs-SUMMARY wording (empirically false).
"""

from __future__ import annotations

import re
from typing import Literal

Issuance = Literal["PRELIMINARY", "FINAL"]

_VALID_TODAY_RE = re.compile(
    r"VALID\s+TODAY\s+AS\s+OF\s+\d{3,4}\s*[AP]M\s+LOCAL\s+TIME\.",
    re.IGNORECASE,
)

_CORRECTION_RE = re.compile(
    r"\bCC[A-Z]\b|\bCORRECTED\b|\bCORRECTIONS?\b",
    re.IGNORECASE,
)
"""Deliberately a WHOLE-TEXT SUPERSET, not a precise classifier.

`CC[A-Z]`, not `CC[AB]`: corrections run CCA, CCB, CCC, ... and a THIRD
correction to one climate day is the instance most likely to land after
settlement has already happened -- exactly the case where the audit trail
has to be right. Missing it is the expensive direction.

This range is kept IDENTICAL to `breezy.domain.wmo._CORRECTION_BBB_RE`
(consumed positionally via `cli_parse.CliStructuralHeader.is_correction_bbb`),
which answers the same question from the positional BBB token. Two signals for
one concept disagreeing about which letters count is a contradiction
waiting to be found by whoever wires either one into `revision_seq`.
`tests/unit/test_normalize_correction_signal_agreement.py` fails if the
two alphabets are ever changed independently -- change both or neither.

`CORRECTIONS?` (not `CORRECTION`): `\\b` after the singular requires a
non-word character next, and the `S` of the plural is a word character, so
`CORRECTIONS` matched nothing at all. `CORRECTIONAL`/`CORRECTIVE` are
still excluded -- the trailing `\\b` only admits the exact plural.

The word-boundary anchors are load-bearing on the widened `CC[A-Z]`: a
bare `CCC` inside a longer token (`CCC072`, `XCCCX`) must not match, or an
advisory flag becomes noise instead of signal.

The scan runs over the whole product text on purpose, and it stays a
SUPERSET of the positional signal: CORRECTED/CORRECTION wording in a body
carrying no BBB token at all is still correction evidence here and is
still not a positional correction. That divergence in COVERAGE is
reviewed and deliberate; the divergence in ALPHABET was not. This flag is
ADVISORY: a false positive costs an operator a few seconds dismissing an
alert, while a false negative silently degrades the audit trail that has
to explain a settlement discrepancy after the fact. Catch more, not less.

Use `cli_parse.CliStructuralHeader.is_correction_bbb` -- the positional,
structurally-validated verdict -- for supersession decisions, and this one
for the audit trail."""


class ClassificationError(ValueError):
    """Raised when issuance cannot be conclusively determined."""


def classify_issuance(product_text: str) -> Issuance:
    """Classify a CLI product as PRELIMINARY or FINAL.

    The discriminator is the presence/absence of the
    "VALID TODAY AS OF <time> LOCAL TIME." line. Never issuanceTime, never
    REPORT-vs-SUMMARY wording.
    """
    if not product_text or not product_text.strip():
        raise ClassificationError("empty product text; cannot classify issuance")
    if _VALID_TODAY_RE.search(product_text):
        return "PRELIMINARY"
    return "FINAL"


def has_correction_evidence(product_text: str) -> bool:
    """Detect correction evidence: a CCA/CCB WMO BBB token, or
    CORRECTED/CORRECTION text, anywhere in the raw product text.
    """
    if not product_text:
        return False
    return bool(_CORRECTION_RE.search(product_text))

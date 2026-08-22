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
    r"\bCC[AB]\b|\bCORRECTED\b|\bCORRECTION\b",
    re.IGNORECASE,
)


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

"""Derived resampling seeds (AUT-4 r11 §3.1, K7): one stream per (subject, slot date, role)."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Final

from breezy.settlement.roi_bound import SEED as ROI_BOUND_SEED

#: The closed role literal: every resampling draw in AUT-4 names exactly one of these.
ROLES: Final[tuple[str, ...]] = (
    "screen_brier_bootstrap",
    "fs_a_permutation",
    "fs_b_ev_signflip",
    "fs_c_calibration_bootstrap",
)
_FIELD_SEPARATOR: Final[bytes] = b"\x1f"
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_HEX_DIGITS_USED: Final[int] = 8


def derive_seed(subject_sha: str, slot_date: dt.date, role: str) -> int:
    """``roi_bound.SEED XOR int(sha256(subject || 0x1F || slot_date || 0x1F || role)[:8], 16)``.

    ``slot_date`` is the ISO UTC date of the slot start. A same-slot recompute on identical
    inputs reproduces the seed (so verdict bodies are byte-equal); a different subject, day or
    role never reuses a draw stream.
    """
    if role not in ROLES:
        raise ValueError(f"role {role!r} is not one of the closed roles {ROLES}")
    if _SHA256_RE.fullmatch(subject_sha) is None:
        raise ValueError("subject_sha must be 64 lowercase hex characters")
    if not isinstance(slot_date, dt.date) or isinstance(slot_date, dt.datetime):
        raise TypeError("slot_date must be a datetime.date")
    blob = _FIELD_SEPARATOR.join(
        (subject_sha.encode("utf-8"), slot_date.isoformat().encode("utf-8"), role.encode("utf-8"))
    )
    digest = hashlib.sha256(blob).hexdigest()
    return ROI_BOUND_SEED ^ int(digest[:_HEX_DIGITS_USED], 16)

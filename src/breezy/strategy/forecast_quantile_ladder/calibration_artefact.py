"""Sha-pinned calibration artefact loader (EMOS location-scale params only).

Plan §2.2 / §3.2 item 9 (`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`):
"Live code sees calibration only through the sha-pinned manifest artefact."
There is no live refitting. This module performs the ONE piece of I/O this
package needs -- reading the artefact bytes -- and refuses outright unless
the artefact's own sha256 equals the caller-supplied ``expected_sha256``
(which in production is the family manifest's pinned
``density_artefact_sha256``, never a source constant).

**No haircut fields (SL-12 review item 4).** ``p_lower``/``p_upper`` are
never derived here from a fixed haircut around a point estimate -- they are
bootstrap draws (ruling A-6, A-4) supplied at evaluation time through an
injected ``bounds.BoundsProvider``. This artefact carries only what builds
the point-estimate CDF.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams

__all__ = [
    "CalibrationArtefact",
    "CalibrationArtefactPinMismatchError",
    "load_calibration_artefact",
]

_UNPINNED_SHA256: Final[str] = "0" * 64


class CalibrationArtefactPinMismatchError(ValueError):
    """Raised when the artefact's own sha256 does not match ``expected_sha256``,
    or when ``expected_sha256`` is itself the unpinned all-zero placeholder."""


@dataclass(frozen=True, slots=True)
class CalibrationArtefact:
    """A fitted, sha-pinned M2 recalibration -- never fitted here (plan §2.2)."""

    sha256: str
    cdf_method: CdfMethod
    emos: EmosParams


def load_calibration_artefact(path: str, *, expected_sha256: str) -> CalibrationArtefact:
    """Read, hash-verify and parse the artefact at ``path``.

    Raises
    ------
    CalibrationArtefactPinMismatchError
        If ``expected_sha256`` is the unpinned all-zero placeholder, or if
        the file's own sha256 disagrees with it.
    """
    if expected_sha256 == _UNPINNED_SHA256:
        raise CalibrationArtefactPinMismatchError(
            "expected_sha256 is the unpinned all-zero placeholder; there is "
            "no live refitting (plan §2.2, SL-12) -- a real manifest pin is required",
        )
    raw = Path(path).read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise CalibrationArtefactPinMismatchError(
            f"calibration artefact at {path!r} hashes to {actual_sha256!r}, "
            f"expected the manifest-pinned {expected_sha256!r}",
        )
    payload: dict[str, Any] = json.loads(raw)
    emos_payload = payload["emos"]
    return CalibrationArtefact(
        sha256=actual_sha256,
        cdf_method=CdfMethod(payload["cdf_method"]),
        emos=EmosParams(
            a=float(emos_payload["a"]),
            gamma=float(emos_payload["gamma"]),
            delta=float(emos_payload["delta"]),
        ),
    )

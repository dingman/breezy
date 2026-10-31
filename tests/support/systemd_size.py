"""The ONE parser of a systemd size literal (``4G``, ``966367641``) for the deploy-unit tests."""

from __future__ import annotations

import re
from typing import Final

_SIZE_MULTIPLIERS: Final[dict[str, int]] = {
    "": 1,
    "K": 1024,
    "M": 1024**2,
    "G": 1024**3,
    "T": 1024**4,
}
_SIZE_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+(?:\.\d+)?)([KMGT]?)$")


def parse_systemd_size(raw: str) -> float:
    """Bytes of a plain systemd size literal; asserts on anything else."""
    match = _SIZE_RE.match(raw.strip())
    assert match is not None, f"unparseable systemd size literal: {raw!r}"
    number, suffix = match.groups()
    return float(number) * _SIZE_MULTIPLIERS[suffix]

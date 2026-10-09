"""The drop-in allowlist of the health pass (X-13, binding activation ruling; WP3 S6).

Kept apart from ``unit_health_*`` on purpose: the allowed directive set names the one environment
variable that the orders-off drop-in sets, and the health modules must mention no trading-gate
name at all (``test_unit_health_modules_read_no_permit_or_orders_state``).

A drop-in is allowlisted only when the sha256 of its bytes equals the row's, it is a regular file
(never read through a symlink), the row has not expired, and its only directives are ``[Service]``
and the orders-off ``Environment=`` line, so a drop-in that sets operator caps or the permit can
never match, whatever the row says.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from breezy.runtime.unit_health_support import DRIFT_CRITICAL_FROM, DriftFinding

__all__ = [
    "DROPIN_ALLOWLIST",
    "DropinAllow",
    "DropinVerdicts",
    "classify_dropins",
    "read_dropin_file",
    "unit_config_drift",
]


@dataclass(frozen=True, slots=True)
class DropinAllow:
    """One allowlisted drop-in (X-13): a unit, a file name, the sha256 of its bytes, the ruling
    that justifies it and the first day it no longer applies."""

    unit: str
    dropin: str
    sha256: str
    ruling: str
    expires: str


#: The orders-off drop-in of the FQ v2 no-trade ruling. Removed when that ruling is lifted.
DROPIN_ALLOWLIST: Final[tuple[DropinAllow, ...]] = (
    DropinAllow(
        "breezy-trade-supervisor.service",
        "fq-v1-halt-orders-off.conf",
        "5ff0d6a1b157aa730cd9c87c4060e3016bed744777674b71af874c95c485e09d",
        "RULING_FQ-v2-NO-TRADE_2026-10-08",
        "2026-12-31",
    ),
)
#: The only directives an allowlisted drop-in may contain: never caps, never the permit.
_ALLOWED_DIRECTIVES: Final = frozenset({"[Service]", "Environment=BREEZY_ORDERS_ENABLED=0"})
_DROPIN_MAX_BYTES: Final = 65_536


@dataclass(frozen=True, slots=True)
class DropinVerdicts:
    findings: tuple[DriftFinding, ...]
    #: ``unit:dropin`` of every drop-in that matched an allowlist row (listed in the day rollup).
    allowlisted: tuple[str, ...]


def read_dropin_file(path: str) -> bytes | None:
    """The bytes of a regular file (never through a symlink), at most 64 KiB; else ``None``."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, _DROPIN_MAX_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    return data if len(data) <= _DROPIN_MAX_BYTES else None


def _directives(data: bytes) -> set[str] | None:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None
    return {ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith(("#", ";"))}


def _allowlist_match(row: DropinAllow, data: bytes | None, today: str) -> bool:
    if data is None or today >= row.expires:
        return False
    if hashlib.sha256(data).hexdigest() != row.sha256:
        return False
    directives = _directives(data)
    return directives is not None and directives <= _ALLOWED_DIRECTIVES


def classify_dropins(
    blocks: Mapping[str, Mapping[str, str]],
    committed: Mapping[str, frozenset[str]],
    *,
    today: str,
    read_dropin: Callable[[str], bytes | None] = read_dropin_file,
    allowlist: Sequence[DropinAllow] = DROPIN_ALLOWLIST,
    critical_from: str = DRIFT_CRITICAL_FROM,
) -> DropinVerdicts:
    """Drop-ins in a unit's ``DropInPaths`` with no committed copy (row #24), less the allowlist.

    An allowlisted name that fails its row (edited bytes, a symlink or unreadable file, an expired
    row, a forbidden directive) is CRITICAL at once; any other uncommitted drop-in keeps the
    date-based severity.
    """
    ordinary = "CRITICAL" if today >= critical_from else "WARNING"
    found: list[DriftFinding] = []
    listed: list[str] = []
    for unit in sorted(blocks):
        known = committed.get(unit, frozenset())
        for path in blocks[unit].get("DropInPaths", "").split():
            name = path.rsplit("/", 1)[-1]
            if name in known:
                continue
            row = next((r for r in allowlist if (r.unit, r.dropin) == (unit, name)), None)
            if row is None:
                found.append(
                    DriftFinding(unit, name, ordinary, f"unit={unit} dropin={name} uncommitted")
                )
            elif _allowlist_match(row, read_dropin(path), today):
                listed.append(f"{unit}:{name}")
            else:
                detail = f"unit={unit} dropin={name} allowlist_mismatch"
                found.append(DriftFinding(unit, name, "CRITICAL", detail))
    return DropinVerdicts(tuple(found), tuple(listed))


def unit_config_drift(
    blocks: Mapping[str, Mapping[str, str]],
    committed: Mapping[str, frozenset[str]],
    *,
    today: str,
    critical_from: str = DRIFT_CRITICAL_FROM,
) -> tuple[DriftFinding, ...]:
    """Drop-ins in a unit's ``DropInPaths`` that have no committed copy (row #24), no allowlist."""
    return classify_dropins(
        blocks, committed, today=today, allowlist=(), critical_from=critical_from
    ).findings

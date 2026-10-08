"""AUT-6 write authority: the per-entry-point write scope of the read-only closure lint.

Plan r15 section 3.1 (E-7 rules 3 and 4, E-7a rule 4): a literal, one row per AUT-6 entry point,
naming the only places it may write (paths under ``~/.local/share/breezy/``) and the process
calls it may make. ``tests/unit/test_autonomy_readonly_closure.py`` judges each entry point's
import closure against its row. A bwrap row (``AUTONOMY_BWRAP_TABLE``) enforces the same scope at
the OS level; this table is the defence-in-depth lint's input and is never described as enforced
for the unwrapped lines (E-7a rule 5).

This module holds data only. Later work packages add their own detector tables beside it.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, NamedTuple


class AuthorityRow(NamedTuple):
    """What one entry point may write and which process calls it may make."""

    writes: tuple[str, ...]
    process_calls: tuple[str, ...] = ()


_ALERTS: Final = "evidence/alerts/**"

AUT6_WRITE_AUTHORITY: Final[MappingProxyType[str, AuthorityRow]] = MappingProxyType(
    {
        "breezy-autonomy-producer-intraday#evaluate": AuthorityRow(
            ("derived/verdicts/**", _ALERTS, "cache/aut6_intraday_exec_snapshot/")
        ),
        "breezy-autonomy-producer-intraday#demand": AuthorityRow(
            ("registry/demand/<venue>/", _ALERTS)
        ),
        "breezy-autonomy-producer-daily": AuthorityRow(
            ("derived/verdicts/**", _ALERTS, "cache/aut6_daily_exec_snapshot/"),
            ("systemctl --user show",),
        ),
        "breezy-autonomy-health": AuthorityRow(
            ("evidence/unit_health/**", "derived/verdicts/**", _ALERTS),
            ("systemctl --user show", "systemctl --user list-units", "journalctl"),
        ),
        "breezy-autonomy-alert-redeliver": AuthorityRow((_ALERTS,)),
        "breezy-autonomy-canary": AuthorityRow((_ALERTS,)),
        "breezy-check-alerts": AuthorityRow((_ALERTS,)),
        "node-sinks": AuthorityRow((_ALERTS,)),
        "bwrap-self-probe": AuthorityRow(()),
        "breezy-autonomy-failed@": AuthorityRow((_ALERTS,), ("systemctl --user show",)),
    }
)

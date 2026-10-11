"""EXEC-PAR BG-5c WP-C: the day-convention PORT, free of every heavy import.

The pure stage evaluator and snapshot (which must not load Nautilus or ``breezy.adapters``,
a BG-5a import-purity test) depend only on this protocol. The implementation,
:class:`~breezy.runtime.exec_par_governed_days.GovernedDays`, imports ``breezy.domain`` (whose
package initialiser loads Nautilus) and is injected at the wiring.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["DayConvention"]


class DayConvention(Protocol):
    """What the migrated attribution sites need from the convention."""

    def entry_day(self, station: str, arm_ns: int) -> str: ...
    def open_days_at(self, ts_ns: int) -> frozenset[str]: ...
    def today(self, ts_ns: int) -> str: ...

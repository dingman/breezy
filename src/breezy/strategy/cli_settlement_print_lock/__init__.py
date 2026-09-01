"""CLI settlement-print lock trading strategy.

Public surface: :class:`CliSettlementPrintLockConfig` and
:class:`CliSettlementPrintLockStrategy`. See ``strategy.py`` for the module
docstring covering the data seam, the required observation-freshness bound,
and where the measured ``p_stable`` constant comes from; see ``decision.py``
for the edge hypothesis and why an INTERIOR bucket is sound after the FINAL
print.

This file is a package marker and a re-export only. It performs no
registration: the design brief's "zero changes to pyproject.toml or any
__init__.py" refers to strategy REGISTRATION, and this mirrors the sibling
package ``breezy.strategy.running_extreme_lock`` so the runner can import by
name.
"""

from __future__ import annotations

from breezy.strategy.cli_settlement_print_lock.config import CliSettlementPrintLockConfig
from breezy.strategy.cli_settlement_print_lock.strategy import CliSettlementPrintLockStrategy

__all__ = ["CliSettlementPrintLockConfig", "CliSettlementPrintLockStrategy"]

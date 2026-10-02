"""Shared, framework-agnostic building blocks for weather-mispricing strategies.

Nothing in this package subclasses ``nautilus_trader.trading.strategy.Strategy``
or imports it: every symbol here is plain Python (dataclasses, protocols, pure
functions) so it can be unit-tested with zero Nautilus objects in scope. The
Nautilus-facing wiring (subscriptions, order construction, event handlers)
lives one layer up, in the concrete strategy packages (e.g.
``breezy.strategy.current_rung_hold``).

This package was originally split out of the operator-supplied strategy
bundles, which each concatenated near-identical ``models.py`` /
``contract_metadata.py`` / ``probability.py`` / ``risk.py`` sections. The
dead weather strategy shells that first consumed it were removed at BC-3 (git
tag ``bc3-pre-removal-2026-10-02``).
"""

from __future__ import annotations

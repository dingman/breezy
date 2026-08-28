"""Shared, framework-agnostic building blocks for weather-mispricing strategies.

Nothing in this package subclasses ``nautilus_trader.trading.strategy.Strategy``
or imports it: every symbol here is plain Python (dataclasses, protocols, pure
functions) so it can be unit-tested with zero Nautilus objects in scope. The
Nautilus-facing wiring (subscriptions, order construction, event handlers)
lives one layer up, in the concrete strategy package
(e.g. ``breezy.strategy.forecast_mispricing``).

This package exists because the operator-supplied strategy bundles
(``forecast_mispricing_strategy.py`` and its two siblings) each concatenated
near-identical ``models.py`` / ``contract_metadata.py`` / ``probability.py`` /
``risk.py`` sections. Splitting the first bundle here, rather than duplicating
those sections again under ``forecast_mispricing/``, avoids re-creating the
duplication the split was meant to remove.
"""

from __future__ import annotations

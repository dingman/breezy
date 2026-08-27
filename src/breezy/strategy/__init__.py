"""Breezy trading strategies.

The top layer of the import contract: strategies may reach ``runtime`` (for
the backtest feed's shared ``ClientId``) and ``ingest`` (for the shared
weather ``DataType`` factories), and nothing may reach back down into them.

Deliberately EMPTY of re-exports. A strategy is loaded by name at its own call
site -- a backtest harness invocation, or eventually a live node's
``ImportableStrategyConfig`` -- and a facade here would make importing any one
strategy import all of them, including their dependencies. Import the module
you want directly, e.g.::

    from breezy.strategy.harness_probe import BreezyHarnessProbe
"""

from __future__ import annotations

__all__: list[str] = []

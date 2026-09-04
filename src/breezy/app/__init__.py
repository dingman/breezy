"""Top-layer composition root for Breezy processes.

Sits above ``breezy.strategy`` in the import-linter layer contract so the
trading entrypoint can construct strategies and hand already-built objects
down to ``breezy.runtime``. Runtime itself never imports strategy.
"""

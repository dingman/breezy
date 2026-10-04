"""AUT-1 WP5 stage 2b, W3: the ``breezy-capture-audit`` entry point (STUB).

Owner: stage-2b worktree W3. Imports no ``breezy.adapters.*`` module (r12 section 3.11.1). Stage 3
wires the unit to ``python -m breezy.analysis.capture_audit_cli``. The bus snapshot is read FIRST,
before any scan or lock wait (S2-R8). Signature pinned by
``tests/unit/test_capture_audit_stubs.py``.
"""

from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the audit; the return value is the process exit code."""
    raise NotImplementedError("AUT-1 stage 2b W3")

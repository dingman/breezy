"""AUT-1 WP5 stage 3a STUB: the ``breezy-capture-live-proof`` entry point (design r3 D8).

Stage 3 stream S2 fills it in; until then ``main`` raises ``NotImplementedError``. It imports no
``breezy.adapters.*`` module and defers inside the launch window.
"""

from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the live-proof unit; the return value is the process exit code (stage 3 S2)."""
    raise NotImplementedError("stage 3 S2: the live-proof CLI")

"""``breezy-autonomy-health``: the AUT-6 unit health pass (plan r15 section 3.9). Skeleton (WP3 S2).

This slice ships the entry module of the ``breezy-autonomy-health`` bwrap row so the unit, the row
and their contract tests exist before the pass does. It reads nothing, writes nothing and calls no
process: it prints a NOT_IMPLEMENTED line and exits 78, so an early enable fails
loudly. The real pass (the bus-snapshot read, the journal cursor, the classification records and
the heartbeat) lands in S3-S6, each with its own RED tests; until then the timer stays disabled.

The entry is deliberately not called ``main``: the ARCH owner ledger names
``breezy.runtime.autonomy_health_cli:main`` as the delivery marker of two pending cross-area tests
(memory sum, the oneshot rule), and defining it here would flip them early.
S6 defines ``main`` with the real pass.
"""

from __future__ import annotations

from collections.abc import Sequence

SUMMARY = "AUTONOMY_HEALTH pass_result=NOT_IMPLEMENTED slice=S2"
#: ``EX_CONFIG``: an early enable of the timer fails the unit (and its ``OnFailure=``) loudly.
EX_CONFIG = 78


def run_skeleton(argv: Sequence[str] | None = None) -> int:
    """Print the placeholder summary and return ``EX_CONFIG``: the pass does not exist yet."""
    del argv
    print(SUMMARY)
    return EX_CONFIG


if __name__ == "__main__":
    raise SystemExit(run_skeleton())

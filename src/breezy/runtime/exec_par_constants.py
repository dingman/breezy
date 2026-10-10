"""EXEC-PAR: the configured concurrent-intent count, in a dependency-free module.

The long-lived trade supervisor must read K without importing ``node_config``
(which pulls in Nautilus and pandas), so the one constant both sides need lives
here and imports nothing but ``typing``. ``runtime.node_config`` re-exports it,
so every existing import keeps working.

A Breezy-owned ``Final``: never env-derived, not an operator control. K stays 1
until D-PREREG is frozen and the activation gates pass.
"""

from typing import Final

#: K, the most submit intents OPEN at once. 1 = today's one-at-a-time latch.
EXEC_PAR_MAX_CONCURRENT_INTENTS: Final[int] = 1

"""ARCH-0 seam 4b: the drawdown-producer label handshake stub (seam A AC 27).

The test is owned by AUT-5 WP11 (the drawdown producer) and AUT-2 (the labels it consumes). Until
the producer lands it is a carried owner-pending stub: see ``autonomy_owner_stub``.
"""

from __future__ import annotations

import pytest

from tests.support.autonomy_owner import OwnerPending
from tests.support.autonomy_owner_stub import await_owner


@pytest.mark.xfail(strict=True, raises=OwnerPending, reason="AUT-5:WP11; blocks none")
def test_drawdown_gates_on_labels_consumable() -> None:
    await_owner("test_drawdown_gates_on_labels_consumable")

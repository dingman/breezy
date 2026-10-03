"""The owner-placeholder ledger (ARCH-0 seam A AC 27; AUT-5 r7 owner-RED ledger).

One row per carried stub: ``(node_id, owner, owner_symbol, blocks_kinds)``.

* ``node_id``: the stub's full pytest node id, literal params included.
* ``owner``: a plan id (``AUT-5``) or ``<plan id>:<token>`` where the token (``WP1``) appears in
  that plan's newest revision. ``test_owner_ids_exist_in_plan_docs`` checks it.
* ``owner_symbol``: ``module`` or ``module:dotted.attribute`` the owner will deliver. A row whose
  symbol now resolves is stale and fails ``test_owner_placeholder_symbol_absent``.
* ``blocks_kinds``: the widening kinds that must stay disabled while the row stands. A row may not
  block fewer kinds than ``autonomy_blocks_kinds_floor.BLOCKS_KINDS_FLOOR`` demands.

The ledger is empty in seam 4a: it ships the mechanism, and seam 4b carries the stubs and their
rows in the same commit. An owner deletes a row, the marker and the stub in one commit.
"""

from __future__ import annotations

from typing import Final, NamedTuple

__all__ = ["OWNER_PLACEHOLDERS", "OwnerRow"]


class OwnerRow(NamedTuple):
    node_id: str
    owner: str
    owner_symbol: str
    blocks_kinds: frozenset[str]


OWNER_PLACEHOLDERS: Final[tuple[OwnerRow, ...]] = ()

"""The body of a carried owner-pending stub (ARCH-0 seam 4b; seam A AC 27).

A stub names itself (``test_name`` or ``test_name[param]``); ``await_owner`` finds that stub's row
in the ledger and requires the owner symbol the row declares. The ledger stays the single source of
the symbol, so a stub cannot drift from its row.

* symbol absent: ``OwnerPending`` (the stub's strict ``xfail(raises=OwnerPending)`` is satisfied);
* symbol delivered: ``NotImplementedError``, a real failure, so the owner must replace the stub;
* no row for the stub: ``KeyError``, also a real failure.
"""

from __future__ import annotations

from collections.abc import Iterable

from tests.support.autonomy_owner import require_owner_symbol
from tests.unit.autonomy_owner_placeholders import OWNER_PLACEHOLDERS, OwnerRow

__all__ = ["await_owner"]


def await_owner(key: str, ledger: Iterable[OwnerRow] = OWNER_PLACEHOLDERS) -> None:
    """Raise ``OwnerPending`` until the owner symbol declared for ``key`` exists."""
    matches = [row for row in ledger if row.node_id.split("::", 1)[1] == key]
    if len(matches) != 1:
        raise KeyError(f"{key}: expected exactly one ledger row, found {len(matches)}")
    module, _, attribute = matches[0].owner_symbol.partition(":")
    require_owner_symbol(module, attribute or None)
    raise NotImplementedError(
        f"{key}: the owner delivered {matches[0].owner_symbol}; write the test"
    )

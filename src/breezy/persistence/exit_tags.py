"""Nautilus ``Order.tags`` prefixes carrying an exit order's authorisation
fields -- the ONE definition site, shared by the strategy layer (which
writes the tags, ``strategy/current_rung_hold/exit_wiring.py``) and the
adapters layer (which reads them back, ``adapters/polymarket_us/exec/
client.py``, INC-E2c).

Lives under ``persistence/``, not ``strategy/``: the importlinter layer
contract (``pyproject.toml`` ``[tool.importlinter]``) places ``strategy``
above ``adapters`` above ``persistence`` (see ``persistence/exit_gate.py``'s
own docstring for the same reasoning), so this is the lowest layer both a
``strategy``-layer writer and an ``adapters``-layer reader can import without
either reaching sideways into the other. ``exit_wiring.py`` re-exports these
four names unchanged (a transparent alias, not a copy) so every existing
importer of ``exit_wiring.EXIT_RULE_TAG_PREFIX`` (etc.) keeps working with no
call-site change.

Four prefixes only -- no ``order_is_exit``/``exit_position_id_from_tags``-
style helper functions here. Those stay in ``exit_wiring.py`` because they
take a ``nautilus_trader.model.orders.Order`` argument, and this module is
kept importable from ``adapters/`` with zero ``nautilus_trader`` dependency,
matching ``persistence/exit_gate.py``'s own "no I/O, nothing beyond the
declared constants" shape. The adapters-layer reader reconstructs its own
tag-scanning over these same prefixes (see ``exec/client.py``'s
``_submit_order`` docstring) rather than importing a strategy-layer helper.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "EXIT_CLIENT_ORDER_ID_TAG_PREFIX",
    "EXIT_FAMILY_TAG_PREFIX",
    "EXIT_POSITION_TAG_PREFIX",
    "EXIT_RULE_TAG_PREFIX",
]

#: INC-E3 (plan §3): the Nautilus-native ``Order.tags`` carrier for an exit
#: order's ``ExitAuthorization`` fields -- never a global registry.
#: ``EXIT_RULE_TAG_PREFIX``'s presence on ANY tag is the sole "is this order
#: an exit" test (see both readers' own docstrings for why).
EXIT_RULE_TAG_PREFIX: Final[str] = "exit_rule="
EXIT_POSITION_TAG_PREFIX: Final[str] = "exit_position_id="
EXIT_FAMILY_TAG_PREFIX: Final[str] = "exit_family_id="
EXIT_CLIENT_ORDER_ID_TAG_PREFIX: Final[str] = "exit_client_order_id="

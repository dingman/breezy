"""Owner-pending carrying mechanism for ARCH-0 placeholder tests (seam A AC 27).

A carried test body is a fixture-free stub: it calls :func:`require_owner_symbol` on the
symbol its owner will deliver, and sits under
``xfail(strict=True, raises=OwnerPending)``. The marker is therefore narrow on purpose:

* only a ``ModuleNotFoundError`` naming the declared module, or one of its ``breezy.``
  ancestors, becomes :class:`OwnerPending` (the owner has not landed the module yet);
* only an ``AttributeError`` on the declared attribute of a module that imported cleanly
  becomes :class:`OwnerPending` (the module landed, the symbol has not);
* anything else propagates. A broken owner module (a failing import of something else, a
  syntax error, an ``ImportError`` for a name) fails the stub loudly instead of hiding behind
  an expected failure.
"""

from __future__ import annotations

import importlib
from typing import Any, Final

__all__ = ["OwnerPending", "declared_module_names", "require_owner_symbol"]

_BREEZY_ROOT: Final = "breezy"


class OwnerPending(Exception):
    """The declared owner symbol has not been delivered yet."""


def declared_module_names(module: str) -> frozenset[str]:
    """Module names whose absence means the declared owner module is absent.

    For a ``breezy.`` module that is the module and every ancestor below the root package
    (``breezy`` itself is excluded: if it is missing, the tree is broken, not pending).
    """
    parts = module.split(".")
    if parts[0] != _BREEZY_ROOT or len(parts) < 2:
        return frozenset({module})
    return frozenset(".".join(parts[:end]) for end in range(2, len(parts) + 1))


def require_owner_symbol(module: str, attribute: str | None = None) -> Any:
    """Return the owner's module (or its dotted ``attribute``), or raise ``OwnerPending``."""
    try:
        imported = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name in declared_module_names(module):
            raise OwnerPending(f"owner module {module} is not delivered yet") from exc
        raise
    if attribute is None:
        return imported
    value: Any = imported
    for part in attribute.split("."):
        try:
            value = getattr(value, part)
        except AttributeError as exc:
            raise OwnerPending(f"owner symbol {module}:{attribute} is not delivered yet") from exc
    return value

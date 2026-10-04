"""The one stage policy (ARCH-0 seam A 6c; AC 15).

``STAGE`` is a frozen ``StagePolicy`` built once, at import, from two reviewed literals:
``pins.ENABLED_WIDENING_KINDS`` (kind names; ships empty) and ``transitions._ADMISSION_IMPLEMENTED``
(ships empty). It is never constructed, replaced, copied or re-typed anywhere else in ``src``
(``test_autonomy_policy_not_mutable_from_src``), and the store and resolver refuse any stage that
is not this object. Import order: ``schemas`` then ``transitions`` then ``stage_policy``.

An enabled name that is not a ``Kind`` value raises ``ValueError`` here, so a misspelt pin stops
the import instead of silently enabling nothing.
"""

from __future__ import annotations

from typing import Final

from breezy.persistence.autonomy import pins, transitions
from breezy.persistence.autonomy.schemas import Kind, StagePolicy

__all__ = ["STAGE"]


def _build() -> StagePolicy:
    return StagePolicy(
        enabled_widening_kinds=frozenset(Kind(name) for name in pins.ENABLED_WIDENING_KINDS),
        admission_implemented=frozenset(transitions._ADMISSION_IMPLEMENTED),
    )


STAGE: Final[StagePolicy] = _build()

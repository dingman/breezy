"""The pure column rules of one registry row (ARCH-0 seam A 6e; AUT-5 r7 3.2; E-16 a; A6e-R10).

``shape_problem(row)`` returns the first rule a row breaks, or ``None``. It is split out of
``registry_store`` so the store stays under its size cap and so the rules read without SQLite.

* ``(from_state, to_state)`` must be in ``transitions.ALLOWED[kind]``.
* ``lineage_root_family_id`` is required on BOOTSTRAP, MINT, PROMOTE, DRILL_PROMOTE, ROLLBACK,
  ROOT_ADMIT and ACTIVATE.
* The nomination columns are all present on a SHADOW to CHALLENGER PROMOTE and all null elsewhere.
* ``paired_transition_id`` is present exactly on SUPERSEDE, DISPLACED and ACTIVATE (E-16 a).
* ``attest_valid_until_ns`` belongs to ATTEST; ``hwm_from``, ``hwm_to`` and ``carried_counters`` to
  HWM_RESET; ``voids_transition_ids`` to SWAP_CANCEL, where it must be non-empty.
* ``halt_cause_class`` is allowed only on DEMOTE and HALT (required-on is for 7c/7d).
* ``cause_code`` is allowed only on DEMOTE, HALT, SWAP_CANCEL and TARGET_INELIGIBLE;
  ``drill_close_restore`` only on RESUME and ``target_integrity`` only on TARGET_INELIGIBLE.
* ``trigger_cause_class`` is allowed only on a ``rollback_failed`` HALT.

Pure: no I/O, no clock.
"""

from __future__ import annotations

from typing import Final

from breezy.persistence.autonomy import transitions
from breezy.persistence.autonomy.schemas import CauseCode, Kind, State, TransitionRow

__all__ = ["NOMINATION_FIELDS", "PAIR_CITING", "is_nomination", "shape_problem"]

LINEAGE_REQUIRED: Final = frozenset(
    {
        Kind.BOOTSTRAP, Kind.MINT, Kind.PROMOTE, Kind.DRILL_PROMOTE, Kind.ROLLBACK,
        Kind.ROOT_ADMIT, Kind.ACTIVATE,
    }
)  # fmt: skip
CAUSE_CODE_KINDS: Final = frozenset(
    {Kind.DEMOTE, Kind.HALT, Kind.SWAP_CANCEL, Kind.TARGET_INELIGIBLE}
)
HALT_CLASS_KINDS: Final = frozenset({Kind.DEMOTE, Kind.HALT})
PAIR_CITING: Final = frozenset({Kind.SUPERSEDE, Kind.DISPLACED, Kind.ACTIVATE})
NOMINATION_FIELDS: Final = ("k_life", "alpha_k", "n_min_eff", "n_cap", "nomination_feasible")
#: ``cause_code`` values that are valid on exactly one kind, besides the four in CAUSE_CODE_KINDS.
_CODE_KIND: Final = {
    CauseCode.DRILL_CLOSE_RESTORE: Kind.RESUME,
    CauseCode.TARGET_INTEGRITY: Kind.TARGET_INELIGIBLE,
}


def is_nomination(row: TransitionRow) -> bool:
    return (
        row.kind is Kind.PROMOTE
        and row.from_state is State.SHADOW
        and row.to_state is State.CHALLENGER
    )


def _cause_code_allowed(row: TransitionRow) -> bool:
    code = row.cause_code
    if code is None:
        return True
    if code in _CODE_KIND:
        return row.kind is _CODE_KIND[code]
    return row.kind in CAUSE_CODE_KINDS


def shape_problem(row: TransitionRow) -> str | None:
    """The first column rule ``row`` breaks, or ``None``."""
    kind = row.kind
    if (row.from_state, row.to_state) not in transitions.ALLOWED[kind]:
        return "transition pair not allowed for kind"
    if kind in LINEAGE_REQUIRED and row.lineage_root_family_id is None:
        return "lineage_root_family_id required"
    present = {name for name in NOMINATION_FIELDS if getattr(row, name) is not None}
    if present != (set(NOMINATION_FIELDS) if is_nomination(row) else set()):
        return "nomination columns required on a nomination and null elsewhere"
    if (row.paired_transition_id is not None) != (kind in PAIR_CITING):
        return "paired_transition_id belongs to SUPERSEDE, DISPLACED and ACTIVATE only"
    if (row.attest_valid_until_ns is not None) != (kind is Kind.ATTEST):
        return "attest_valid_until_ns belongs to ATTEST only"
    hwm_present = {
        row.hwm_from is not None,
        row.hwm_to is not None,
        row.carried_counters is not None,
    }
    if hwm_present != ({True} if kind is Kind.HWM_RESET else {False}):
        return "hwm_from, hwm_to and carried_counters belong to HWM_RESET only"
    if kind is Kind.SWAP_CANCEL:
        if not row.voids_transition_ids:
            return "voids_transition_ids required and non-empty on SWAP_CANCEL"
    elif row.voids_transition_ids is not None:
        return "voids_transition_ids belongs to SWAP_CANCEL only"
    if row.halt_cause_class is not None and kind not in HALT_CLASS_KINDS:
        return "halt_cause_class belongs to DEMOTE and HALT only"
    if not _cause_code_allowed(row):
        return "cause_code not allowed for kind"
    if row.trigger_cause_class is not None and not (
        kind is Kind.HALT and row.cause_code is CauseCode.ROLLBACK_FAILED
    ):
        return "trigger_cause_class belongs to a rollback_failed HALT only"
    return None

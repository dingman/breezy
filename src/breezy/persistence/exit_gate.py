"""Exit-rule gate -- the unforgeable second half of a family's exit permission.

Lives under `persistence/`, not `strategy/` or `settlement/`: the
importlinter layer contract (`pyproject.toml` `[tool.importlinter]`) places
`strategy` above `runtime` above `adapters` above `persistence`, so a
`strategy`-layer consumer (the intra-day position monitor, `strategy/
current_rung_hold/position_monitor.py`) may import downward into this
module, and an `adapters`-layer execution seam may later import it too
(INC-9, `§5` of `INTRADAY_POSITION_MONITOR_2026-09-15.md`) -- both reach
down through the same layer direction `scored_trial_store.py` already
established for `persistence`. `settlement` never imports this module (it
stays pure per `test_settlement_purity_guard.py`, rule D1).

`FamilyManifest.exit_rule` (`persistence/family_manifest.py`) is a
DECLARATION only -- a field any committed manifest JSON can carry. If that
declaration alone were sufficient to grant exit capability, a single
un-reviewed JSON edit could flip a hold-to-settlement family into one that
exits mid-day. `_EXIT_RULE_REGISTERED_FAMILIES` is the second, independent
gate: a `Final` frozenset literal in THIS module's source, never read from
disk, never derived from a manifest field, and never mutated at runtime
(the module ships no setter). Flipping it requires a code change -- a
diff, a review, a commit -- not a data edit (L-22: unforgeable exclusion).
`family_declares_exit_rule` requires BOTH the manifest's own `exit_rule`
being set AND the family's id being named in this frozenset; either one
alone is refused.

Today the frozenset is EMPTY: no family may exit. Every currently
registered and draft family (`pm_us_crh_v2`, `pm_us_crh_cont`,
`kalshi_crh_v1`) holds to settlement, per PREREG v3 and plan
`INTRADAY_POSITION_MONITOR_2026-09-15.md` §5 (the execution seam that would
ever let a family act on this gate is itself BLOCKED, increment INC-9,
pending the `unmappable_order_reason` widening and REDUCE_ONLY_BYPASS/R6A
remediation landing together). The intra-day position monitor
(`strategy/current_rung_hold/position_monitor.py`) is SHADOW-ONLY: it may
consult this gate for reporting/decision-labelling purposes but must never
construct, submit, modify, or cancel an order on the strength of it.
"""

from __future__ import annotations

from typing import Final

from breezy.persistence.family_manifest import FamilyManifest

__all__ = ["family_declares_exit_rule"]

_EXIT_RULE_REGISTERED_FAMILIES: Final[frozenset[str]] = frozenset()


def family_declares_exit_rule(manifest: FamilyManifest) -> bool:
    """True only if `manifest.family_id` is code-registered AND the
    manifest itself declares a non-None `exit_rule`.

    Neither condition alone is sufficient (see module docstring): a
    manifest declaring `exit_rule` for a family absent from
    `_EXIT_RULE_REGISTERED_FAMILIES` gates False, and a code-registered
    family whose manifest omits `exit_rule` also gates False.
    """
    return (
        manifest.family_id in _EXIT_RULE_REGISTERED_FAMILIES
        and manifest.exit_rule is not None
    )

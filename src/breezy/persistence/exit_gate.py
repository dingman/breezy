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

The frozenset gains its first (and, as of this commit, only) member,
`pm_us_crh_exit_v4`, per PREREG v4 (`docs/plans/
POSITION_EXIT_EXECUTION_2026-09-16.md` §2, INC-E1): a change to the ACTION
is a new family, never an amendment of `pm_us_crh_cont` (L-34). Every other
currently registered or draft family (`pm_us_crh_v2`, `pm_us_crh_cont`,
`kalshi_crh_v1`) still holds to settlement -- membership here alone grants
nothing (see below): `pm_us_crh_exit_v4`'s own manifest
(`deploy/families/pm_us_crh_exit_v4.json`) ships `status:
DRAFT_NOT_REGISTERED` with NO `exit_rule` key at INC-E1, so
`family_declares_exit_rule` still gates False for it until the manifest is
amended to declare `exit_rule` at REGISTRATION (§2, INC-E4 enable). The
execution seam that would ever let a family act on a True gate is itself
BLOCKED through INC-E3 (`POSITION_EXIT_EXECUTION_2026-09-16.md` §3: "Nothing
in E1-E3 can reach the venue: the gate stays closed until E4"). The intra-day
position monitor (`strategy/current_rung_hold/position_monitor.py`) is
SHADOW-ONLY: it may consult this gate for reporting/decision-labelling
purposes but must never construct, submit, modify, or cancel an order on the
strength of it.
"""

from __future__ import annotations

from typing import Final

from breezy.persistence.family_manifest import FamilyManifest

__all__ = ["family_declares_exit_rule", "family_declares_no_leg_exit"]

_EXIT_RULE_REGISTERED_FAMILIES: Final[frozenset[str]] = frozenset({"pm_us_crh_exit_v4"})


def family_declares_exit_rule(manifest: FamilyManifest) -> bool:
    """True only if `manifest.family_id` is code-registered AND the
    manifest itself declares a non-None `exit_rule`.

    Neither condition alone is sufficient (see module docstring): a
    manifest declaring `exit_rule` for a family absent from
    `_EXIT_RULE_REGISTERED_FAMILIES` gates False, and a code-registered
    family whose manifest omits `exit_rule` also gates False.
    """
    return manifest.family_id in _EXIT_RULE_REGISTERED_FAMILIES and manifest.exit_rule is not None


def family_declares_no_leg_exit(manifest: FamilyManifest) -> bool:
    """True only if `family_declares_exit_rule(manifest)` is True AND the
    manifest itself declares `no_leg_exit`.

    FU-1d: a NO-leg exit is guarded by TWO deliberate gates, never by
    missing data. This is the second, narrower one -- it can only ever
    ADD a restriction on top of `family_declares_exit_rule`, never grant an
    exit on its own (a manifest cannot set `no_leg_exit` without also
    declaring `exit_rule`; see `family_manifest.load_family_manifest`).

    FU-1d S2 (`RULING_FU-1b_no_leg_marks_2026-09-26.md` re-open item 2):
    has TWO consumers, deliberately, not one -- `exit_decider.decide_exit`
    (the primary gate, strategy layer) and
    `adapters.polymarket_us.exec.submit_chain.unmappable_exit_order_reason`
    (the defense-in-depth re-check at the exec seam both the standalone
    submit-chain client and `exec/client.py`'s exec-client boundary reach).
    Both consumers call the SAME function, never a re-literalled copy, so
    they can never silently disagree on which families may close a NO leg.
    """
    return family_declares_exit_rule(manifest) and manifest.no_leg_exit

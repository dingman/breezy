"""Live-orders enable gate -- the unforgeable second half of a family's
real-order permission (plan `FQ_GO_LIVE_PLAN_2026-10-01.md` D3, S5).

Lives under `persistence/`, the same layer and the same split-gate shape as
`persistence/exit_gate.py`: `FamilyManifest.live_orders_ruling`
(`persistence/family_manifest.py`) is a DECLARATION only -- a field any
committed manifest JSON can carry. If that declaration alone were
sufficient to let a family send real orders, a single un-reviewed JSON edit
could flip a shadow-only family live. `_LIVE_ORDERS_ALLOWLIST` is the
second, independent gate: a `Final` frozenset literal in THIS module's
source, never read from disk, never derived from a manifest field, and
never mutated at runtime. Flipping it requires a code change -- a diff, a
review, a commit -- not a data edit.

The allowlist entry is a 3-tuple `(family_id, ruling_id, ruling_sha256)`.
`live_orders_authorized` additionally re-hashes the ruling file named by
`ruling_id` (resolved under `docs/evidence/` relative to the caller's
`repo_root`, with symlink-safe path containment) and compares it to the
pinned sha256 -- a later edit to the committed ruling file, even
whitespace-only, fails the gate closed. Neither this module nor its caller
reads, assigns, or logs an operator-reserved control (max daily budget, max
per position); `permit_present` is a plain bool the caller derives from its
own `OrderSubmissionPermit`/`None` state.

`shadow_only=False` is permitted ONLY when `live_orders_authorized(...)
.enabled` is `True` -- see `app/trade.py`'s fq branch and the AST guard in
`tests/unit/test_shadow_only_false_is_only_the_gate_output.py`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from breezy.persistence.family_manifest import FamilyManifest

__all__ = [
    "LiveOrdersDecision",
    "LiveOrdersGateRefusedError",
    "LiveOrdersReason",
    "live_orders_authorized",
]

LiveOrdersReason = Literal[
    "no_ruling",
    "not_allowlisted",
    "ruling_missing",
    "ruling_outside_evidence",
    "ruling_sha_mismatch",
    "permit_absent",
    "ok",
]

#: D3: code-committed allowlist of 3-tuples `(family_id, ruling_id,
#: ruling_sha256)`. Adding a member is a reviewed source change, never a
#: data edit -- the same unforgeable-allowlist shape as
#: `exit_gate._EXIT_RULE_REGISTERED_FAMILIES`.
_LIVE_ORDERS_ALLOWLIST: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {
        (
            "pm_us_crh_fq_v1",
            "RULING_operator_fq_live_real_orders_2026-10-01",
            "11c69d132a70d8e328d3720314336aa6f2cf176d52fd25d5f2e20a7189711c1f",
        ),
    }
)

#: Where a ruling file must live, relative to `repo_root`.
_EVIDENCE_SUBTREE: Final[str] = "docs/evidence"

#: Every reason OTHER than these two refuses boot (EXIT_CONFIG_ERROR) at the
#: caller -- `no_ruling` means nothing was ever declared (stay shadow,
#: nothing wrong), `permit_absent` means the ruling verified clean but no
#: order-submission permit exists yet (stay shadow, nothing wrong either).
_REFUSES_BOOT: Final[frozenset[str]] = frozenset(
    {"not_allowlisted", "ruling_missing", "ruling_outside_evidence", "ruling_sha_mismatch"}
)


class LiveOrdersGateRefusedError(RuntimeError):
    """A declared `live_orders_ruling` failed verification; the caller must
    refuse boot (EXIT_CONFIG_ERROR), never silently fall back to shadow."""

    def __init__(self, reason: LiveOrdersReason, message: str) -> None:
        super().__init__(message)
        self.reason: LiveOrdersReason = reason


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveOrdersDecision:
    """`enabled=True` iff a composed fq strategy may run with
    `shadow_only=False`. `reason` is always one of the two non-refusing
    members of `LiveOrdersReason` -- every refusing reason is raised as
    `LiveOrdersGateRefusedError` instead of being returned."""

    enabled: bool
    reason: LiveOrdersReason


def live_orders_authorized(
    manifest: FamilyManifest, repo_root: Path, *, permit_present: bool
) -> LiveOrdersDecision:
    """Resolve whether `manifest` may send real orders.

    Checks, in order: (1) a ruling is declared at all; (2) the
    `(family_id, ruling_id)` pair is allowlisted; (3) the ruling file's path
    stays inside `repo_root/docs/evidence` even through a symlink; (4) the
    file exists; (5) its sha256 matches the allowlisted pin; (6) a live
    order-submission permit exists. Raises `LiveOrdersGateRefusedError` for
    every failure except "no ruling declared" and "permit absent", which
    return a `LiveOrdersDecision(enabled=False, ...)` instead -- both are
    ordinary shadow-mode states, never a configuration error.
    """
    ruling_id = manifest.live_orders_ruling
    if ruling_id is None:
        return LiveOrdersDecision(enabled=False, reason="no_ruling")

    match = next(
        (
            entry
            for entry in _LIVE_ORDERS_ALLOWLIST
            if entry[0] == manifest.family_id and entry[1] == ruling_id
        ),
        None,
    )
    if match is None:
        raise LiveOrdersGateRefusedError(
            "not_allowlisted",
            f"live_orders_ruling {ruling_id!r} is not allowlisted for "
            f"family_id {manifest.family_id!r}",
        )
    _, _, expected_sha256 = match

    evidence_dir = (repo_root / _EVIDENCE_SUBTREE).resolve()
    ruling_path = (repo_root / _EVIDENCE_SUBTREE / f"{ruling_id}.md").resolve()
    if not ruling_path.is_relative_to(evidence_dir):
        raise LiveOrdersGateRefusedError(
            "ruling_outside_evidence",
            f"ruling path for {ruling_id!r} escapes {_EVIDENCE_SUBTREE}",
        )
    if not ruling_path.is_file():
        raise LiveOrdersGateRefusedError(
            "ruling_missing", f"ruling file missing: {ruling_path}"
        )

    actual_sha256 = hashlib.sha256(ruling_path.read_bytes()).hexdigest()
    if actual_sha256 != expected_sha256:
        raise LiveOrdersGateRefusedError(
            "ruling_sha_mismatch",
            f"ruling {ruling_id!r} sha256 mismatch: expected {expected_sha256}, "
            f"got {actual_sha256}",
        )

    if not permit_present:
        return LiveOrdersDecision(enabled=False, reason="permit_absent")

    return LiveOrdersDecision(enabled=True, reason="ok")

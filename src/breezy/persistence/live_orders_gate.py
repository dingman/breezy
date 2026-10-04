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
`ruling_id` (resolved under `deploy/families/rulings/` relative to the
caller's `repo_root`, with symlink-safe path containment) and compares it to
the pinned sha256 -- a later edit to the committed ruling file, even
whitespace-only, fails the gate closed. Neither this module nor its caller
reads, assigns, or logs an operator-reserved control (max daily budget, max
per position); `permit_present` is a plain bool the caller derives from its
own `OrderSubmissionPermit`/`None` state.

Deviation from plan `FQ_GO_LIVE_PLAN_2026-10-01.md` D3/S5 (coordinator
decision, this change): D3 states the ruling resolves under
`docs/evidence/`. `tests/unit/test_probe_containment.py::
test_no_module_under_src_reads_docs_evidence` enforces a repo-wide
containment contract -- no module under `src/` may carry `docs/evidence` as
a runtime value, docstring citations exempted -- and this module's own
allowlist-driven resolution is exactly that violation, not an exempt
citation. Rather than widen that containment test's allowlist (which the
coordinator ruled out), the ruling's live copy moves to
`deploy/families/rulings/`, alongside the family manifests and artefacts
this module already reasons about path-containment for. A byte-identical
copy of the committed `docs/evidence/<ruling>.md` lives there (verified by
`tests/unit/test_live_orders_ruling_deploy_copy_matches_evidence.py`); the
allowlist's pinned sha256 is unchanged, since both copies are byte-for-byte
identical.

`shadow_only=False` is permitted ONLY when `live_orders_authorized(...)
.enabled` is `True` -- see `app/trade.py`'s fq branch and the AST guard in
`tests/unit/test_shadow_only_false_is_only_the_gate_output.py`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from breezy.persistence.family_manifest import FamilyManifest

__all__ = [
    "CHILD_FAMILY_ID_RE",
    "LineagePolicyDecision",
    "LiveOrdersDecision",
    "LiveOrdersGateRefusedError",
    "LiveOrdersReason",
    "lineage_policy_authorized",
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

#: Lineage-policy allowlist of `(root_family_id, policy_ruling_id,
#: policy_ruling_sha256)` 3-tuples, the second independent gate for CHILD
#: families (`<root>_rNNNN`). Ships empty: a later reviewed source change adds
#: the one row. A literal in source, never read from disk or a manifest.
_LINEAGE_POLICY_ALLOWLIST: Final[frozenset[tuple[str, str, str]]] = frozenset()

#: A child family id: the root's id plus `_r` and four digits. The regex only
#: checks consistency; the caller names the root from its own authoritative
#: record and passes it to `lineage_policy_authorized`.
CHILD_FAMILY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(?P<root>[a-z0-9_]{1,58})_r[0-9]{4}\Z", re.ASCII
)

#: Where a ruling file must live, relative to `repo_root`. NOT `docs/evidence`
#: -- see the module docstring's "Deviation from plan" note: `src/` may never
#: carry that path as a runtime value, so the live copy lives here instead.
_RULINGS_SUBTREE: Final[str] = "deploy/families/rulings"

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
    `LiveOrdersGateRefusedError` instead of being returned.

    `ruling_sha256` is the allowlist-pinned sha256 (already verified to
    equal the on-disk ruling file's own sha256) when a ruling was declared
    and matched -- `reason in ("ok", "permit_absent")` -- and `None` for
    `reason == "no_ruling"` (nothing was ever verified). The caller logs it
    verbatim on the `fq_live_orders` boot line (plan `FQ_GO_LIVE_PLAN_2026
    -10-01.md` §3 S5), the security reviewer's required field alongside
    `calibration_sha256`.
    """

    enabled: bool
    reason: LiveOrdersReason
    ruling_sha256: str | None = None


def _verify_ruling_file(ruling_id: str, expected_sha256: str, repo_root: Path) -> None:
    """Containment, existence and sha256 checks for a committed ruling file.

    Move-only extraction of the verification lines of `live_orders_authorized`
    (ARCH-0 seam A 8a): the reasons and messages are unchanged. Returns `None`
    when the ruling file verifies; raises `LiveOrdersGateRefusedError` otherwise.
    """
    rulings_dir = (repo_root / _RULINGS_SUBTREE).resolve()
    ruling_path = (repo_root / _RULINGS_SUBTREE / f"{ruling_id}.md").resolve()
    if not ruling_path.is_relative_to(rulings_dir):
        raise LiveOrdersGateRefusedError(
            "ruling_outside_evidence",
            f"ruling path for {ruling_id!r} escapes {_RULINGS_SUBTREE}",
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


def live_orders_authorized(
    manifest: FamilyManifest, repo_root: Path, *, permit_present: bool
) -> LiveOrdersDecision:
    """Resolve whether `manifest` may send real orders.

    Checks, in order: (1) a ruling is declared at all; (2) the
    `(family_id, ruling_id)` pair is allowlisted; (3) the ruling file's path
    stays inside `repo_root/deploy/families/rulings` even through a symlink;
    (4) the file exists; (5) its sha256 matches the allowlisted pin; (6) a
    live order-submission permit exists. Raises `LiveOrdersGateRefusedError` for
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

    _verify_ruling_file(ruling_id, expected_sha256, repo_root)

    if not permit_present:
        return LiveOrdersDecision(
            enabled=False, reason="permit_absent", ruling_sha256=expected_sha256
        )

    return LiveOrdersDecision(enabled=True, reason="ok", ruling_sha256=expected_sha256)


@dataclass(frozen=True, slots=True, kw_only=True)
class LineagePolicyDecision:
    """Whether a child family's lineage-policy ruling verified. It carries no
    permit semantics: `authorized=True` means only that the child declares the
    root's allowlisted policy ruling and the committed file re-hashes clean.
    `reason` is `"ok"` or `"no_ruling"`; every refusal is raised as
    `LiveOrdersGateRefusedError`. `ruling_sha256` is the allowlist-pinned sha256
    when `authorized`, else `None`."""

    authorized: bool
    reason: LiveOrdersReason
    ruling_sha256: str | None = None


def _lineage_policy_authorized(
    child: FamilyManifest,
    root_family_id: str,
    repo_root: Path,
    *,
    allowlist: frozenset[tuple[str, str, str]],
) -> LineagePolicyDecision:
    """`lineage_policy_authorized` against an explicit `allowlist` (a private
    seam so tests inject a fixture row; production passes the literal)."""
    child_match = CHILD_FAMILY_ID_RE.match(child.family_id)
    if child_match is None or child_match.group("root") != root_family_id:
        raise LiveOrdersGateRefusedError(
            "not_allowlisted",
            f"family_id {child.family_id!r} is not a child of lineage root {root_family_id!r}",
        )
    ruling_id = child.live_orders_ruling
    if ruling_id is None:
        return LineagePolicyDecision(authorized=False, reason="no_ruling")

    match = next(
        (
            entry
            for entry in sorted(allowlist)
            if entry[0] == root_family_id and entry[1] == ruling_id
        ),
        None,
    )
    if match is None:
        raise LiveOrdersGateRefusedError(
            "not_allowlisted",
            f"live_orders_ruling {ruling_id!r} is not the lineage-policy ruling "
            f"for root {root_family_id!r}",
        )
    _, _, expected_sha256 = match

    _verify_ruling_file(ruling_id, expected_sha256, repo_root)
    return LineagePolicyDecision(authorized=True, reason="ok", ruling_sha256=expected_sha256)


def lineage_policy_authorized(
    child: FamilyManifest, root_family_id: str, repo_root: Path
) -> LineagePolicyDecision:
    """Resolve whether `child` may be routed under `root_family_id`'s
    lineage-policy ruling. Raises `LiveOrdersGateRefusedError` for every failure
    except "no ruling declared". Uses `_LINEAGE_POLICY_ALLOWLIST` only."""
    return _lineage_policy_authorized(
        child, root_family_id, repo_root, allowlist=_LINEAGE_POLICY_ALLOWLIST
    )

"""FQ-S5 deviation (coordinator decision, `live_orders_gate`'s "Deviation
from plan" docstring note): `persistence.live_orders_gate` resolves its
ruling file under `deploy/families/rulings/`, never `docs/evidence/`, to
satisfy `tests/unit/test_probe_containment.py::
test_no_module_under_src_reads_docs_evidence` (src/ may never carry
`docs/evidence` as a runtime value).

This suite is the proof that the live copy is not a second, drifting
artefact: it is byte-identical to the committed `docs/evidence/` original,
and both hash to the gate's own allowlisted pin. A test module is allowed to
read `docs/evidence/` -- only `src/` is forbidden.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from breezy.persistence.live_orders_gate import _LIVE_ORDERS_ALLOWLIST

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_RULING_ID: Final[str] = "RULING_operator_fq_live_real_orders_2026-10-01"
_EVIDENCE_PATH: Final[Path] = _REPO_ROOT / "docs" / "evidence" / f"{_RULING_ID}.md"
_DEPLOY_PATH: Final[Path] = (
    _REPO_ROOT / "deploy" / "families" / "rulings" / f"{_RULING_ID}.md"
)


def _allowlisted_sha256() -> str:
    (_, _, expected_sha256), = (
        entry for entry in _LIVE_ORDERS_ALLOWLIST if entry[1] == _RULING_ID
    )
    return expected_sha256


def test_the_deploy_copy_exists_alongside_the_evidence_original() -> None:
    assert _EVIDENCE_PATH.is_file()
    assert _DEPLOY_PATH.is_file()


def test_the_deploy_copy_is_byte_identical_to_the_evidence_original() -> None:
    assert _DEPLOY_PATH.read_bytes() == _EVIDENCE_PATH.read_bytes()


def test_the_deploy_copy_sha256_equals_the_evidence_originals_sha256() -> None:
    evidence_sha256 = hashlib.sha256(_EVIDENCE_PATH.read_bytes()).hexdigest()
    deploy_sha256 = hashlib.sha256(_DEPLOY_PATH.read_bytes()).hexdigest()
    assert deploy_sha256 == evidence_sha256


def test_both_copies_sha256_equal_the_gates_allowlisted_pin() -> None:
    expected = _allowlisted_sha256()
    assert hashlib.sha256(_EVIDENCE_PATH.read_bytes()).hexdigest() == expected
    assert hashlib.sha256(_DEPLOY_PATH.read_bytes()).hexdigest() == expected

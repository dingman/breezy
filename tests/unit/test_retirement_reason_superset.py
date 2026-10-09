"""AMBIG-LATCH-RESUME Phase A, T47: the node/supervisor retirement-reason superset.

Every retirement reason NAME a node can emit must be decodable by the
supervisor: ``emitted ⊆ RetirementReason ⊆ marker.retirement_reasons``. A name
that escapes this chain makes an older supervisor raise ``SubmitIntentCorrupt``
on the RETIRED singleton, read it as OPEN and refuse every launch (L-48).

The emitted set is collected by AST over ``exec/client.py`` and
``exec/submit_chain.py`` BY PATH (this module never imports ``exec/``, so it
adds no row to the X1 exec-import pin).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    RetirementReason,
    SubmitIntentCorrupt,
    SubmitIntentState,
    open_submit_intent_latch,
)
from breezy.runtime.supervisor_decode_marker import (
    supervisor_decode_marker_path,
    write_supervisor_decode_marker,
)
from breezy.runtime.trade_supervisor import probe_open_intent

_ROOT = Path(__file__).resolve().parents[2]
_EXEC = _ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "exec"
_CLIENT = _EXEC / "client.py"
_SUBMIT_CHAIN = _EXEC / "submit_chain.py"
_NOW_NS = 1_700_000_000_000_000_000


def _module_str_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` / ``NAME: Final[str] = "literal"``."""
    constants: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            constants[target.id] = value.value
    return constants


def _resolve(expr: ast.expr, constants: dict[str, str]) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.Name):
        return constants.get(expr.id)
    return None


def emitted_reason_names(client_tree: ast.AST, chain_tree: ast.AST) -> set[str]:
    """Reason names the node can emit.

    * ``self._retire(<intent_id>, <name>, <now>)`` second argument, literal or a
      module-level string constant (non-resolvable names such as the
      ``retire_name`` variable are fed by submit_chain constants, collected below);
    * ``retirement_member(<reasons>, <name>)`` second argument;
    * every ``retirement_name=<literal|constant>`` keyword in submit_chain;
    * every module-level ``RETIRE_*`` string constant in submit_chain.
    """
    names: set[str] = set()
    client_consts = _module_str_constants(client_tree)
    chain_consts = _module_str_constants(chain_tree)
    names.update(v for k, v in chain_consts.items() if k.startswith("RETIRE_"))
    for tree, consts in ((client_tree, client_consts), (chain_tree, chain_consts)):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if callee in {"_retire", "retirement_member"} and len(node.args) >= 2:
                idx = 1
                resolved = _resolve(node.args[idx], consts)
                if resolved is not None:
                    names.add(resolved)
            for kw in node.keywords:
                if kw.arg == "retirement_name":
                    resolved = _resolve(kw.value, consts)
                    if resolved is not None:
                        names.add(resolved)
    return names


def _real_emitted() -> set[str]:
    return emitted_reason_names(
        ast.parse(_CLIENT.read_text(encoding="utf-8")),
        ast.parse(_SUBMIT_CHAIN.read_text(encoding="utf-8")),
    )


_MEMBERS = {m.value for m in RetirementReason}


def test_collector_finds_the_known_emitters_so_the_superset_check_is_not_vacuous() -> None:
    emitted = _real_emitted()
    assert {
        "STATUS_REPORT_ZERO_FILL_TERMINAL",
        "STATUS_REPORT_ACCEPT_FILL_TERMINAL",
        "ACCEPTED_WITH_DURABLE_FILL",
        "ACCEPTED_ZERO_FILL_TERMINAL",
        "DEFINITIVE_REJECT",
    } <= emitted


def test_every_emitted_reason_name_is_a_retirement_reason_member() -> None:
    assert _real_emitted() <= _MEMBERS


def test_a_planted_unknown_reason_name_fails_the_superset_check() -> None:
    planted_client = ast.parse(
        "class C:\n    def f(self, x, n):\n        self._retire(x, 'NOT_A_MEMBER', n)\n"
    )
    planted_chain = ast.parse("RETIRE_PLANTED = 'ALSO_NOT_A_MEMBER'\n")
    planted = emitted_reason_names(planted_client, planted_chain)
    assert planted == {"NOT_A_MEMBER", "ALSO_NOT_A_MEMBER"}
    assert not planted <= _MEMBERS


def test_a_name_resolved_through_a_module_constant_is_collected() -> None:
    client = ast.parse(
        "_X = 'VIA_CONSTANT'\nclass C:\n    def f(self, i, n):\n        self._retire(i, _X, n)\n"
    )
    assert emitted_reason_names(client, ast.parse("")) == {"VIA_CONSTANT"}


def test_members_are_a_subset_of_what_the_supervisor_marker_advertises(tmp_path: Path) -> None:
    store_path = tmp_path / "store.sqlite3"
    write_supervisor_decode_marker(store_path, revision="0123456789ab")
    advertised = set(
        json.loads(supervisor_decode_marker_path(store_path).read_text())["retirement_reasons"]
    )
    assert _real_emitted() <= _MEMBERS <= advertised
    assert "RESOLVER_NO_ID_NO_FILL" in advertised


@pytest.mark.parametrize("member", sorted(_MEMBERS))
def test_probe_open_intent_decodes_a_retired_singleton_of_every_member_as_not_open(
    tmp_path: Path, member: str
) -> None:
    store_path = tmp_path / "store.sqlite3"
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as latch:
        intent = latch.arm("a" * 64, now_ns=_NOW_NS)
        retired = latch.retire(intent.intent_id, RetirementReason(member), now_ns=_NOW_NS + 1)
        assert retired.state is SubmitIntentState.RETIRED
    assert probe_open_intent(store_path, node_pid=None) is False


def test_an_undecodable_reason_reads_as_open_which_is_why_the_superset_matters(
    tmp_path: Path,
) -> None:
    """Documents the L-48 hazard the superset test guards: an unknown reason
    string in a RETIRED singleton is Corrupt -> probe_open_intent True."""
    from breezy.runtime.submit_intent import CURRENT_INTENT_KEY, SubmitIntent

    store_path = tmp_path / "store.sqlite3"
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as latch:
        intent = latch.arm("a" * 64, now_ns=_NOW_NS)
        retired = latch.retire(
            intent.intent_id, RetirementReason.OPERATOR_CLEARED, now_ns=_NOW_NS + 1
        )
    payload = json.loads(retired.to_bytes())
    payload["retirement_reason"] = "NOT_A_MEMBER"
    raw = json.dumps(payload).encode()
    with pytest.raises(SubmitIntentCorrupt):
        SubmitIntent.from_bytes(raw)
    with SqliteStateStore(store_path) as store:
        store.set(CURRENT_INTENT_KEY, raw)
    assert probe_open_intent(store_path, node_pid=None) is True

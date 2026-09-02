"""The exec mappers' allowlists, checked against the SDK snapshot ITSELF.

Authority: ``docs/plans/EXEC_SPINE_2026-09-01.md`` section R-3.

WHY THIS FILE EXISTS
--------------------

``exec/reports.py`` refuses any key the SDK snapshot does not declare, and maps
every enum member it does. Both properties were asserted against a **hardcoded
inline copy** of the snapshot's own lists: ``ast.parse`` ran only against
``src/breezy/adapters/polymarket_us/exec/``, never against
``docs/evidence/venue/polymarket_us/sdk_snapshot/``. A snapshot that grew an
``OrderState``, or a ``UserPosition`` field, left the mapper table stale AND the
test green -- the second copy drifted in lockstep with the first because it was
never compared to the source of truth at all.

Every assertion below reads the snapshot through ``ast``, so the only way to
keep this file green is to keep the mapper tables faithful. Set EQUALITY, never
containment, in both directions: a key the snapshot dropped is as much a drift
as one it added.

The snapshot is a frozen artifact of ``polymarket-us==0.1.2``; it is not
imported (the package is an optional dependency) and it is not executed. It is
parsed as text, which is also why an unparseable snapshot fails loudly here
rather than degrading to an empty set -- see the non-vacuity proofs at the end.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from breezy.adapters.polymarket_us.exec.reports import (
    _BALANCES_RESPONSE_KEYS,
    _EXECUTION_KEYS,
    _FILL_EXECUTION_TYPES,
    _MARKET_METADATA_KEYS,
    _ORDER_KEYS,
    _ORDER_SIDES,
    _ORDER_TYPES,
    _TIME_IN_FORCE,
    _USER_BALANCE_KEYS,
    _USER_POSITION_KEYS,
    ORDER_STATE_TO_ORDER_STATUS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The frozen SDK snapshot -- the ONLY source of truth for these shapes, since
#: no live capture exists (all four authenticated smoke runs recorded
#: ``Connectivity verdict: FAIL``).
SNAPSHOT_TYPES: Final[Path] = (
    REPO_ROOT
    / "docs"
    / "evidence"
    / "venue"
    / "polymarket_us"
    / "sdk_snapshot"
    / "polymarket_us_0.1.2"
    / "types"
)


def _snapshot_tree(module_name: str) -> ast.Module:
    path = SNAPSHOT_TYPES / module_name
    assert path.is_file(), f"SDK snapshot module is missing: {path}"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def typed_dict_keys(module_name: str, class_name: str) -> frozenset[str]:
    """Every annotated field the snapshot's ``TypedDict`` declares.

    Absence is an ERROR, not an empty set: a renamed or deleted class must
    fail this suite rather than silently satisfy every equality against it.
    """
    for node in ast.walk(_snapshot_tree(module_name)):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        return frozenset(
            statement.target.id
            for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        )
    raise AssertionError(f"SDK snapshot {module_name} declares no class {class_name!r}")


def literal_members(module_name: str, alias_name: str) -> frozenset[str]:
    """Every string member of a snapshot ``Literal[...]`` type alias."""
    for node in ast.walk(_snapshot_tree(module_name)):
        if (
            not isinstance(node, ast.Assign)
            or len(node.targets) != 1
            or not isinstance(node.targets[0], ast.Name)
            or node.targets[0].id != alias_name
            or not isinstance(node.value, ast.Subscript)
        ):
            continue
        index = node.value.slice
        elements = index.elts if isinstance(index, ast.Tuple) else [index]
        return frozenset(
            element.value
            for element in elements
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
    raise AssertionError(f"SDK snapshot {module_name} declares no Literal alias {alias_name!r}")


# ---------------------------------------------------------------------------
# Key allowlists -- exact set equality against the snapshot TypedDicts
# ---------------------------------------------------------------------------

#: ``(allowlist, snapshot module, snapshot class)``. Every allowlist
#: ``reports.py`` uses to refuse an undeclared key appears here; a new one that
#: does not is caught by the coverage pin below.
KEY_ALLOWLISTS: Final[tuple[tuple[str, frozenset[str], str, str], ...]] = (
    (
        "_BALANCES_RESPONSE_KEYS",
        _BALANCES_RESPONSE_KEYS,
        "account.py",
        "GetAccountBalancesResponse",
    ),
    ("_USER_BALANCE_KEYS", _USER_BALANCE_KEYS, "account.py", "UserBalance"),
    ("_ORDER_KEYS", _ORDER_KEYS, "orders.py", "Order"),
    ("_EXECUTION_KEYS", _EXECUTION_KEYS, "orders.py", "Execution"),
    ("_MARKET_METADATA_KEYS", _MARKET_METADATA_KEYS, "orders.py", "MarketMetadata"),
    ("_USER_POSITION_KEYS", _USER_POSITION_KEYS, "portfolio.py", "UserPosition"),
)


@pytest.mark.parametrize(
    ("name", "allowlist", "module_name", "class_name"),
    KEY_ALLOWLISTS,
    ids=[entry[0] for entry in KEY_ALLOWLISTS],
)
def test_every_key_allowlist_equals_the_snapshot_typed_dict(
    name: str, allowlist: frozenset[str], module_name: str, class_name: str
) -> None:
    declared = typed_dict_keys(module_name, class_name)
    assert declared, f"{class_name} parsed to zero fields; the snapshot reader is broken"
    assert allowlist == declared, (
        f"{name} has drifted from {module_name}:{class_name}; "
        f"missing={sorted(declared - allowlist)} extra={sorted(allowlist - declared)}"
    )


# ---------------------------------------------------------------------------
# Enum tables -- exact set equality against the snapshot Literals
# ---------------------------------------------------------------------------


def test_the_order_state_table_covers_exactly_the_snapshot_states() -> None:
    """Totality AND minimality, read off ``OrderState`` (``orders.py:21-33``)."""
    assert set(ORDER_STATE_TO_ORDER_STATUS) == set(literal_members("orders.py", "OrderState"))


def test_the_order_side_table_covers_exactly_the_snapshot_sides() -> None:
    assert set(_ORDER_SIDES) == set(literal_members("orders.py", "OrderSide"))


def test_the_order_type_table_covers_exactly_the_snapshot_types() -> None:
    assert set(_ORDER_TYPES) == set(literal_members("orders.py", "OrderType"))


def test_the_time_in_force_table_covers_exactly_the_snapshot_members() -> None:
    assert set(_TIME_IN_FORCE) == set(literal_members("orders.py", "TimeInForce"))


def test_the_fill_execution_types_are_a_named_subset_of_the_snapshot_members() -> None:
    """DELIBERATELY a subset: the other six members are lifecycle acknowledgements.

    Equality would be wrong here -- turning ``EXECUTION_TYPE_CANCELED`` into a
    ``FillReport`` invents a trade. What must hold is that both members Breezy
    DOES accept are still declared, and that the ones it refuses are the rest.
    """
    declared = literal_members("orders.py", "ExecutionType")
    assert _FILL_EXECUTION_TYPES < declared
    assert declared - _FILL_EXECUTION_TYPES == {
        "EXECUTION_TYPE_NEW",
        "EXECUTION_TYPE_CANCELED",
        "EXECUTION_TYPE_REPLACE",
        "EXECUTION_TYPE_REJECTED",
        "EXECUTION_TYPE_EXPIRED",
        "EXECUTION_TYPE_DONE_FOR_DAY",
    }


# ---------------------------------------------------------------------------
# Non-vacuity -- a reader that cannot fail is not a check
# ---------------------------------------------------------------------------


def test_the_snapshot_reader_finds_the_fields_it_claims_to_read() -> None:
    """The counts a reviewer hand-verified. A reader returning ``set()`` for
    everything would satisfy no equality above -- but only because the
    allowlists are non-empty, which is not something this file should assume."""
    assert len(typed_dict_keys("orders.py", "Order")) == 20
    assert len(typed_dict_keys("orders.py", "Execution")) == 11
    assert len(typed_dict_keys("orders.py", "MarketMetadata")) == 7
    assert len(typed_dict_keys("account.py", "UserBalance")) == 12
    assert len(typed_dict_keys("account.py", "GetAccountBalancesResponse")) == 1
    assert len(typed_dict_keys("portfolio.py", "UserPosition")) == 11
    assert len(literal_members("orders.py", "OrderState")) == 11


def test_the_snapshot_reader_refuses_a_class_that_is_not_there() -> None:
    with pytest.raises(AssertionError, match="GetOpenOrdersReply"):
        typed_dict_keys("orders.py", "GetOpenOrdersReply")


def test_the_snapshot_reader_refuses_a_literal_alias_that_is_not_there() -> None:
    with pytest.raises(AssertionError, match="OrderCondition"):
        literal_members("orders.py", "OrderCondition")


def test_the_authoritative_position_slug_is_the_dict_key_not_a_field() -> None:
    """Why ``parse_position_status_report`` takes ``market_slug`` from its caller.

    ``GetUserPositionsResponse.positions`` is a ``dict[str, UserPosition]``
    (``portfolio.py:45-50``) and ``UserPosition`` itself declares no slug --
    only an OPTIONAL ``marketMetadata``. The mapper therefore cannot derive its
    own market binding, and a mapper that binds a position to whatever
    instrument it was handed is how market A's exposure lands on instrument B.
    """
    assert "marketSlug" not in typed_dict_keys("portfolio.py", "UserPosition")
    assert "marketMetadata" in typed_dict_keys("portfolio.py", "UserPosition")

    tree = _snapshot_tree("portfolio.py")
    annotations = {
        statement.target.id: ast.unparse(statement.annotation)
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "GetUserPositionsResponse"
        for statement in node.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    }
    assert annotations["positions"] == "dict[str, UserPosition]"

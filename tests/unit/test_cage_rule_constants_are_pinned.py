"""The cage's rule constants are EQUALITY-pinned, in both directions.

Authority: ``docs/plans/EXEC_CLIENT_NOSEND_PLAN.md`` (revision 3) increment
NS-2, counters 1, 3, 5, 7 and 8.

WHY THIS MODULE EXISTS, MEASURED RATHER THAN ASSERTED
-----------------------------------------------------

Every barrier in this repo is a scan, and every scan is parameterised by a
handful of module-level constants. Nothing pinned those constants, so the
whole cage could be loosened -- or, worse, silently NARROWED -- by a one-token
diff that no test could see. Two experiments, run on the shipped tree at
``fd470eb`` before this module existed:

* ``_WRITE_METHODS`` widened by one neutral token (``PROPFIND``) --
  ``3819 passed, 1 skipped, 4 deselected``. Identical to the baseline.
* ``_EGRESS_CLASS_BASES`` NARROWED, by deleting ``"LiveExecutionClient"`` --
  ``3819 passed, 1 skipped, 4 deselected``. Identical to the baseline.

The second is the dangerous one, and it is worth stating exactly why it went
undetected. ``test_n2_e2_detects_a_live_execution_client_subclass`` plants
``class PolymarketUSExecClient(LiveExecutionClient)`` and asserts ``E2`` --
but that class NAME ends with ``ExecClient``, which is in
``_EGRESS_CLASS_SUFFIXES``, and ``_scan_source`` checks the suffix rule first
and ``continue``s. So the detector proof for the bases rule was actually
being carried by the suffix rule, and deleting the base that classifies every
real Nautilus execution client changed nothing anywhere in 3819 tests.

That is counter 8's exact shape: a rule constant narrowed rather than widened,
silently disarming a scan. An equality pin fails in BOTH directions, which is
the only reason to prefer it over a subset assertion.

WHAT IS PINNED, AND WHAT A PIN IS WORTH
---------------------------------------

The plan names nine rule constants. This module pins those nine and seven
more, each with its own reason recorded in the table: the E0 path prefix
(created by NS-0, after the nine were enumerated -- narrowing it disarms the
whole ``exec/`` classification), the firewall module's own same-named
``EGRESS_SCAN_ROOTS``, the B6/B7 deny table, and the four rule sets NS-2
itself adds. Pinning one's own new rules is the same counter applied to one's
own work.

A pin is worth nothing unless the comparison it uses can actually fail, so
every pin ships with TWO neighbour proofs -- a widened value and a narrowed
one -- both asserted to be REFUSED by :func:`pin_holds`, the same predicate
the live pin runs. Without them this module would be sixteen assertions that
a value equals itself.

Type identity is part of the comparison, and deliberately: in Python
``frozenset({"GET"}) == {"GET"}`` is ``True``, so a "pin" that compared only
values would accept the immutable rule set being replaced by a mutable one.

REBINDING (counter 7)
---------------------

An equality pin reads the constant where it is DEFINED. It cannot see
``signing.PERMITTED_METHODS = frozenset({"GET", "POST"})`` executed from
another module against the imported module object -- the definition is
untouched and the pin still passes while the running process is wide open.
Rule P1 below bans assignment to those names through an ATTRIBUTE target,
repo-wide across ``src/``, ``scripts/`` and ``tests/``.

Attribute targets only, and that is not a gap: a bare ``NAME = ...`` target IS
the definition site, and the definition site is what the equality pins cover.
The two rules are complements, not duplicates.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest

import tests.unit.test_execution_egress_firewall_guard as firewall
import tests.unit.test_polymarket_us_readonly_guard as readonly
from tests.unit.test_polymarket_us_readonly_guard import Violation, iter_python_sources

REPO_ROOT = Path(__file__).resolve().parents[2]


# ==========================================================================
# The pin table
# ==========================================================================


@dataclass(frozen=True)
class RulePin:
    """One cage rule constant, its expected value, and its two neighbours."""

    module: str
    attr: str
    expected: object
    widened: object
    narrowed: object
    why: str

    @property
    def label(self) -> str:
        return f"{self.module}.{self.attr}"


def pin_holds(actual: object, expected: object) -> bool:
    """The single comparison every pin and every neighbour proof runs.

    Compiled patterns are compared on ``(pattern, flags)`` because two
    ``re.Pattern`` objects are never equal by identity, and dropping
    ``IGNORECASE`` is a narrowing a naive comparison would miss.
    """
    if isinstance(actual, re.Pattern) or isinstance(expected, re.Pattern):
        if not (isinstance(actual, re.Pattern) and isinstance(expected, re.Pattern)):
            return False
        return actual.pattern == expected.pattern and actual.flags == expected.flags
    if type(actual) is not type(expected):
        return False
    return bool(actual == expected)


CAGE_RULE_PINS: tuple[RulePin, ...] = (
    RulePin(
        module="readonly",
        attr="_WRITE_METHODS",
        expected=frozenset({"POST", "PUT", "PATCH", "DELETE"}),
        widened=frozenset({"POST", "PUT", "PATCH", "DELETE", "PROPFIND"}),
        narrowed=frozenset({"PUT", "PATCH", "DELETE"}),
        why="V1: the write-method literals banned inside a venue-touching module",
    ),
    RulePin(
        module="readonly",
        attr="_WRITE_ATTRS",
        expected=frozenset({"post", "put", "patch", "delete", "request"}),
        widened=frozenset({"post", "put", "patch", "delete", "request", "head"}),
        narrowed=frozenset({"put", "patch", "delete", "request"}),
        why="V3/V4: the write-capable attribute names, on any receiver",
    ),
    RulePin(
        module="readonly",
        attr="_ORDER_PATH_RE",
        expected=re.compile(r"/v\d+/orders?\b", re.IGNORECASE),
        widened=re.compile(r"/v\d+/orders?\b|/v\d+/positions\b", re.IGNORECASE),
        narrowed=re.compile(r"/v\d+/orders?\b"),
        why="V2: the order-path shape. The narrowed neighbour merely drops "
        "IGNORECASE, which is exactly how a regex pin gets disarmed silently",
    ),
    RulePin(
        module="readonly",
        attr="_VENUE_NAME_RE",
        expected=re.compile(r"polymarket", re.IGNORECASE),
        widened=re.compile(r"polymarket|kalshi", re.IGNORECASE),
        narrowed=re.compile(r"polymarket"),
        why="C5 (NS-2): classifies a module that names the venue without "
        "naming its host -- the environment-driven escape",
    ),
    RulePin(
        module="readonly",
        attr="EGRESS_SCAN_ROOTS",
        expected=("src", "scripts"),
        widened=("src", "scripts", "docs"),
        narrowed=("src",),
        why="B4/B6/B7 reach. Narrowing it to ('src',) exempts every script",
    ),
    RulePin(
        module="readonly",
        attr="SDK_IMPORT_ORACLE",
        expected="tests/unit/test_polymarket_us_signing.py",
        widened="tests/unit/",
        narrowed="tests/unit/test_polymarket_us_signin.py",
        why="B5's ONLY exemption. The widened neighbour is the shape that "
        "matters: an exact path degraded into a directory prefix",
    ),
    RulePin(
        module="readonly",
        attr="BARRED_CALLEES",
        expected=MappingProxyType(
            {
                "assert_live_order_submission_permitted": "B6",
                "issue_live_trading_permit": "B7",
            }
        ),
        widened=MappingProxyType(
            {
                "assert_live_order_submission_permitted": "B6",
                "issue_live_trading_permit": "B7",
                "consume": "B8",
            }
        ),
        narrowed=MappingProxyType({"assert_live_order_submission_permitted": "B6"}),
        why="B6/B7 (NS-2 defect D-2). The narrowed neighbour is the real "
        "hazard: dropping the issuer re-opens self-issuance in one token",
    ),
    RulePin(
        module="firewall",
        attr="EGRESS_SCAN_ROOTS",
        expected=("src", "scripts"),
        widened=("src", "scripts", "tests"),
        narrowed=("src",),
        why="N2's live scan reach. A SECOND constant of the same name in a "
        "different module -- pinning one would have left the other loose",
    ),
    RulePin(
        module="firewall",
        attr="_EGRESS_PATH_PREFIXES",
        expected=("src/breezy/adapters/polymarket_us/exec/",),
        widened=(
            "src/breezy/adapters/polymarket_us/exec/",
            "src/breezy/adapters/polymarket_us/order/",
        ),
        narrowed=(),
        why="E0, added by NS-0 AFTER the plan enumerated its nine constants. "
        "Emptying it disarms the whole exec/ classification and, with it, "
        "the sessionstart abort",
    ),
    RulePin(
        module="firewall",
        attr="_EGRESS_MODULE_BASENAMES",
        expected=frozenset(
            {
                "execution.py",
                "execution_client.py",
                "exec_client.py",
                "order_submit.py",
                "order_router.py",
                "orders.py",
                "trading.py",
            }
        ),
        widened=frozenset(
            {
                "execution.py",
                "execution_client.py",
                "exec_client.py",
                "order_submit.py",
                "order_router.py",
                "orders.py",
                "trading.py",
                "broker.py",
            }
        ),
        narrowed=frozenset(
            {
                "execution.py",
                "execution_client.py",
                "exec_client.py",
                "order_submit.py",
                "order_router.py",
                "orders.py",
            }
        ),
        why="E1: execution-egress module names",
    ),
    RulePin(
        module="firewall",
        attr="_EGRESS_CLASS_SUFFIXES",
        expected=("ExecutionClient", "ExecClient", "OrderRouter"),
        widened=("ExecutionClient", "ExecClient", "OrderRouter", "OrderGateway"),
        narrowed=("ExecutionClient", "ExecClient"),
        why="E2: class-name suffixes",
    ),
    RulePin(
        module="firewall",
        attr="_EGRESS_CLASS_BASES",
        expected=frozenset(
            {"LiveExecutionClient", "LiveExecClientFactory", "LiveExecutionClientFactory"}
        ),
        widened=frozenset(
            {
                "LiveExecutionClient",
                "LiveExecClientFactory",
                "LiveExecutionClientFactory",
                "ExecutionClient",
            }
        ),
        narrowed=frozenset({"LiveExecClientFactory", "LiveExecutionClientFactory"}),
        why="E2: the Nautilus bases. The narrowed neighbour is the exact "
        "mutation measured to leave the whole suite green",
    ),
    RulePin(
        module="firewall",
        attr="_EGRESS_FUNCTION_NAMES",
        expected=frozenset(
            {
                "submit_order",
                "place_order",
                "cancel_order",
                "modify_order",
                "submit_order_list",
                "_submit_order",
                "_place_order",
                "_cancel_order",
                "_modify_order",
                "_submit_order_list",
                "_cancel_all_orders",
                "_batch_cancel_orders",
            }
        ),
        widened=frozenset(
            {
                "submit_order",
                "place_order",
                "cancel_order",
                "modify_order",
                "submit_order_list",
                "_submit_order",
                "_place_order",
                "_cancel_order",
                "_modify_order",
                "_submit_order_list",
                "_cancel_all_orders",
                "_batch_cancel_orders",
                "_close_position",
            }
        ),
        narrowed=frozenset(
            {
                "submit_order",
                "place_order",
                "cancel_order",
                "modify_order",
                "submit_order_list",
                "_place_order",
                "_cancel_order",
                "_modify_order",
                "_submit_order_list",
                "_cancel_all_orders",
                "_batch_cancel_orders",
            }
        ),
        why="E3: both forms of every order verb. The narrowed neighbour drops "
        "_submit_order, the one coroutine every real client implements",
    ),
    RulePin(
        module="firewall",
        attr="SOCKET_RESTORING_MARKERS",
        expected=frozenset({"allow_socket", "live", "venue_live", "real_money"}),
        widened=frozenset({"allow_socket", "live", "venue_live", "real_money", "contract"}),
        narrowed=frozenset({"allow_socket", "live", "venue_live"}),
        why="X1 (NS-2): the four markers for which conftest restores the real "
        "pyo3 clients",
    ),
    RulePin(
        module="firewall",
        attr="BANNED_NATIVE_NAMES",
        expected=frozenset({"SandboxExecutionClient", "BettingAccount"}),
        widened=frozenset({"SandboxExecutionClient", "BettingAccount", "MakerTakerFeeModel"}),
        narrowed=frozenset({"SandboxExecutionClient"}),
        why="X2 (NS-2): the constructs the plan bans by name",
    ),
    RulePin(
        module="firewall",
        attr="BANNED_EXEC_DIRECTION_TOKENS",
        expected=frozenset({"_SHORT", "OUTCOME_SIDE_NO"}),
        widened=frozenset({"_SHORT", "OUTCOME_SIDE_NO", "_LAY"}),
        narrowed=frozenset({"_SHORT"}),
        why="X3 (NS-2): direction vocabulary prohibited under exec/",
    ),
)

_MODULES = {"readonly": readonly, "firewall": firewall}

#: Every exemption the cage grants, as an EXACT path. Counter 1: a directory
#: prefix would be a blanket allowance, and an entry naming a file that does
#: not exist is an allowance nobody is checking.
CAGE_EXEMPTIONS: tuple[str, ...] = (readonly.SDK_IMPORT_ORACLE,)


def _pin_ids() -> list[str]:
    return [pin.label for pin in CAGE_RULE_PINS]


# ==========================================================================
# The pins themselves, and the proof that each can fail in both directions
# ==========================================================================


@pytest.mark.parametrize("pin", CAGE_RULE_PINS, ids=_pin_ids())
def test_every_cage_rule_constant_still_equals_its_pin(pin: RulePin) -> None:
    actual = getattr(_MODULES[pin.module], pin.attr)
    assert pin_holds(actual, pin.expected), (
        f"{pin.label} drifted from its pin.\n  why it is pinned: {pin.why}\n"
        f"  pinned:  {pin.expected!r}\n  actual:  {actual!r}\n"
        "A rule constant changes only in a commit that says so."
    )


@pytest.mark.parametrize("pin", CAGE_RULE_PINS, ids=_pin_ids())
def test_every_pin_refuses_a_widened_neighbour(pin: RulePin) -> None:
    """Non-vacuity, direction 1: loosening is caught."""
    assert pin.widened != pin.expected or isinstance(pin.expected, re.Pattern)
    assert pin_holds(pin.widened, pin.expected) is False


@pytest.mark.parametrize("pin", CAGE_RULE_PINS, ids=_pin_ids())
def test_every_pin_refuses_a_narrowed_neighbour(pin: RulePin) -> None:
    """Non-vacuity, direction 2 -- counter 8, and the one that was measured."""
    assert pin_holds(pin.narrowed, pin.expected) is False


def test_the_pin_predicate_accepts_the_pinned_value_itself() -> None:
    """Control: a predicate that refused everything would pass both proofs."""
    for pin in CAGE_RULE_PINS:
        assert pin_holds(pin.expected, pin.expected) is True


def test_the_pin_predicate_refuses_an_equal_value_of_another_type() -> None:
    """``frozenset({"GET"}) == {"GET"}`` is True in Python. A pin must not be."""
    assert frozenset({"GET"}) == {"GET"}
    assert pin_holds({"GET"}, frozenset({"GET"})) is False
    assert pin_holds(["src", "scripts"], ("src", "scripts")) is False


def test_the_pin_table_covers_every_rule_constant_the_plan_names() -> None:
    """The nine the plan enumerates, plus the seven added with a reason.

    An equality on the SET OF PINS, so a pin cannot be deleted quietly --
    which is the same defect one level up from the one the pins close.
    """
    pinned = {pin.label for pin in CAGE_RULE_PINS}
    plans_nine = {
        "readonly._WRITE_METHODS",
        "readonly._WRITE_ATTRS",
        "readonly._ORDER_PATH_RE",
        "readonly.EGRESS_SCAN_ROOTS",
        "readonly.SDK_IMPORT_ORACLE",
        "firewall._EGRESS_MODULE_BASENAMES",
        "firewall._EGRESS_CLASS_SUFFIXES",
        "firewall._EGRESS_CLASS_BASES",
        "firewall._EGRESS_FUNCTION_NAMES",
    }
    added_with_a_reason = {
        "readonly._VENUE_NAME_RE",
        "readonly.BARRED_CALLEES",
        "firewall.EGRESS_SCAN_ROOTS",
        "firewall._EGRESS_PATH_PREFIXES",
        "firewall.SOCKET_RESTORING_MARKERS",
        "firewall.BANNED_NATIVE_NAMES",
        "firewall.BANNED_EXEC_DIRECTION_TOKENS",
    }
    assert plans_nine <= pinned, f"unpinned: {sorted(plans_nine - pinned)}"
    assert pinned == plans_nine | added_with_a_reason


def test_every_pinned_constant_actually_exists_on_its_module() -> None:
    """A pin naming an absent attribute would fail loudly; a pin naming the
    WRONG module would silently pin nothing. This reads the attribute."""
    for pin in CAGE_RULE_PINS:
        assert hasattr(_MODULES[pin.module], pin.attr), f"{pin.label} does not exist"


# ==========================================================================
# Counter 1 -- exemptions are exact paths that resolve to real files
# ==========================================================================


def test_every_cage_exemption_resolves_to_an_existing_file() -> None:
    for entry in CAGE_EXEMPTIONS:
        assert (REPO_ROOT / entry).is_file(), f"exemption {entry} names no file"


def test_every_cage_exemption_is_an_exact_path_not_a_prefix() -> None:
    """A directory prefix exempts every file added to it, forever."""
    for entry in CAGE_EXEMPTIONS:
        assert entry.endswith(".py"), f"exemption {entry} is not a single module"
        assert "*" not in entry
        assert not entry.endswith("/")


def test_the_cage_grants_exactly_one_exemption() -> None:
    """An equality, not ``<=``: a second exemption must be argued for.

    NS-2 creates no allowlist. The V2 allowlist the plan contemplates arrives
    with ``exec/endpoints.py`` at NS-4, together with its own ``== 1`` pin.
    """
    assert len(CAGE_EXEMPTIONS) == 1


# ==========================================================================
# P1 (counter 7) -- no module rebinds a pinned constant on another module
# ==========================================================================

#: Roots scanned for the rebinding ban. Wider than the write-egress roots:
#: a test module can rebind an imported constant just as effectively as a
#: source module, and ``monkeypatch.setattr`` is how it would be spelled.
REBINDING_SCAN_ROOTS = ("src", "scripts", "tests")

#: Constant names that may never be assigned through an attribute.
PINNED_CONSTANT_NAMES = frozenset({"PERMITTED_METHODS", "PERMITTED_QUOTA_KEYS"})
PINNED_CONSTANT_PREFIXES = ("_WRITE_",)


def is_pinned_constant_name(name: str) -> bool:
    return name in PINNED_CONSTANT_NAMES or name.startswith(PINNED_CONSTANT_PREFIXES)


def _assignment_targets(node: ast.AST) -> Iterator[ast.expr]:
    if isinstance(node, ast.Assign):
        yield from node.targets
    elif isinstance(node, ast.AugAssign | ast.AnnAssign):
        yield node.target


def find_constant_rebindings(path: str, source: str) -> list[Violation]:
    """P1: report every rebinding of a pinned constant on a module object.

    Two spellings, both real:

    * ``signing.PERMITTED_METHODS = ...`` -- an ``ast.Attribute`` target;
    * ``setattr(signing, "PERMITTED_METHODS", ...)`` and its
      ``monkeypatch.setattr`` form -- a call whose second argument names the
      constant as a string.

    A bare ``NAME = ...`` target is NOT reported: that is the definition
    site, and the definition site is what the equality pins above cover.
    """
    tree = ast.parse(source, filename=path)
    found: list[Violation] = []
    for node in ast.walk(tree):
        for target in _assignment_targets(node):
            if isinstance(target, ast.Attribute) and is_pinned_constant_name(target.attr):
                found.append(
                    Violation(
                        path,
                        getattr(node, "lineno", 0),
                        "P1",
                        f"rebinds .{target.attr} on an imported module object",
                    )
                )
        if (
            isinstance(node, ast.Call)
            and (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and is_pinned_constant_name(node.args[1].value)
        ):
            found.append(
                Violation(
                    path,
                    node.lineno,
                    "P1",
                    f"setattr bypass rebinding {node.args[1].value}",
                )
            )
    return found


def scan_constant_rebindings(
    roots: tuple[str, ...] = REBINDING_SCAN_ROOTS,
) -> list[Violation]:
    return [
        v for path, src in iter_python_sources(roots) for v in find_constant_rebindings(path, src)
    ]


def test_p1_no_module_rebinds_a_pinned_constant_anywhere_in_the_repo() -> None:
    violations = scan_constant_rebindings()
    assert violations == [], "P1 violations:\n" + "\n".join(str(v) for v in violations)


def test_p1_detects_the_attribute_rebinding_of_the_signer_s_method_pin() -> None:
    """Counter 7's exact case, and note it carries no write-method literal."""
    source = (
        "from breezy.adapters.polymarket_us import signing\n"
        "\n"
        "\n"
        "def widen():\n"
        "    signing.PERMITTED_METHODS = frozenset({'GET', *_extra()})\n"
    )
    assert [v.rule for v in find_constant_rebindings("src/breezy/rogue.py", source)] == ["P1"]


def test_p1_detects_the_quota_key_rebinding() -> None:
    source = "transport.PERMITTED_QUOTA_KEYS = frozenset()\n"
    assert [v.rule for v in find_constant_rebindings("src/breezy/rogue.py", source)] == ["P1"]


def test_p1_detects_a_write_rule_constant_rebinding_by_prefix() -> None:
    source = "guard._WRITE_METHODS = frozenset()\n"
    assert [v.rule for v in find_constant_rebindings("tests/unit/test_x.py", source)] == ["P1"]


def test_p1_detects_the_augmented_assignment_form() -> None:
    source = "signing.PERMITTED_METHODS |= _extra\n"
    assert [v.rule for v in find_constant_rebindings("src/breezy/rogue.py", source)] == ["P1"]


def test_p1_detects_the_setattr_bypass() -> None:
    source = "setattr(signing, 'PERMITTED_METHODS', _wide)\n"
    assert [v.rule for v in find_constant_rebindings("src/breezy/rogue.py", source)] == ["P1"]


def test_p1_detects_the_monkeypatch_setattr_form() -> None:
    """The spelling a test would actually use to open the data path."""
    source = (
        "def test_x(monkeypatch):\n"
        "    monkeypatch.setattr(signing, 'PERMITTED_METHODS', frozenset({'GET'}))\n"
    )
    assert [v.rule for v in find_constant_rebindings("tests/unit/test_x.py", source)] == ["P1"]


def test_p1_does_not_fire_on_the_shipped_definition_sites() -> None:
    """Read off the real modules: the definitions must stay legal.

    A rule that flagged its own definition site would have to be silenced,
    and a barrier that must be silenced is a barrier that will be.
    """
    for relative in (
        "src/breezy/adapters/polymarket_us/signing.py",
        "src/breezy/adapters/polymarket_us/http.py",
        "src/breezy/adapters/polymarket_us/transport.py",
        "tests/unit/test_polymarket_us_readonly_guard.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        # Precondition: the file really does define one of the pinned names,
        # so "no violation" is evidence about the rule and not about an
        # unrelated file.
        assert any(
            token in source
            for token in ("PERMITTED_METHODS", "PERMITTED_QUOTA_KEYS", "_WRITE_")
        ), f"precondition failed: {relative} defines no pinned constant"
        assert find_constant_rebindings(relative, source) == []


def test_p1_does_not_fire_on_reading_the_constant() -> None:
    source = "def check(m):\n    return m in signing.PERMITTED_METHODS\n"
    assert find_constant_rebindings("src/breezy/x.py", source) == []


def test_p1_scan_covers_src_scripts_and_tests() -> None:
    scanned = {path for path, _ in iter_python_sources(REBINDING_SCAN_ROOTS)}
    assert any(p.startswith("src/") for p in scanned)
    assert any(p.startswith("scripts/") for p in scanned)
    assert any(p.startswith("tests/") for p in scanned)

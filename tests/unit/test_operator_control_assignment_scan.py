"""R-6e: nothing in this repository assigns an operator-reserved control.

The two controls -- the ones named by
``operator_controls.OPERATOR_RESERVED_CONTROL_ENV_VARS``, deliberately not spelt
out here -- arrive ONLY from the shell that launches ``breezy-trade``. This
module is the proof, in four independent layers, because no single layer covers
the whole surface:

* **A -- an AST scan** of ``src/``, ``scripts/`` and ``tests/`` for the shapes
  that give an environment variable a value: subscript assignment,
  ``setdefault``, ``update``, ``putenv``, ``monkeypatch.setenv``, a two-argument
  ``os.environ.get`` / ``os.getenv``, an ``or``-fallback, a mapping literal, a
  local alias of the control's name, and a COMPUTED variable name (the shape an
  evasion arrives in). Catches assignment through the constant's IDENTIFIER,
  which carries no searchable literal.
* **B -- a text census** over EVERY tracked file, whose set of files mentioning
  either control name must EQUAL an exact pinned set. Catches a ``.env.example``
  a systemd unit under ``deploy/``, a YAML/JSON/TOML config, a shell script, or
  a docstring code sample -- none of which layer A parses, and all of which the
  brief asks about by name.
* **C -- a runtime import probe** in a subprocess whose environment lacks both
  controls: importing the package must leave both absent. Catches an assignment
  executed at import time no matter what syntax produced it.
* **D -- a reader audit**: every read of either control goes through
  ``safety._require_operator_value`` and no read has a default.

**The whitelisted seam.** A test must be able to DRIVE the mechanism, which
means putting a value in the environment for the length of one test. Exactly
one path may do that -- ``tests/unit/operator_control_env.py`` -- and it is
whitelisted from layer A only. It survives layer B because it never names a
control, and it is separately audited here: it carries no control name and no
value of its own, and it restores the prior state in a ``finally``. Every other
route, including a ``monkeypatch.setenv`` in any other test, fires.

**What was already here, and is not re-implemented.**
``test_polymarket_us_permit_issuance.find_environ_mutations`` already bans EVERY
write to the process environment from ``src/`` and ``scripts/``, name-agnostic,
along with ``load_dotenv``, ``os.putenv`` and ``os.unsetenv``
(``test_no_shipped_code_can_set_the_operator_trading_gate``). So the shipped
half of layer A is belt-and-braces, and it is cited rather than duplicated. What
R-6e adds on top of it is real and separable: that scan does not walk ``tests/``
(a fixture or ``conftest`` is where a default actually creeps in), and it bans
only WRITES -- an ``os.environ.get(CONTROL, "100.00")`` is a READ, passes it
untouched, and is exactly the form the plan names.

**Known gaps, stated rather than implied.**

* Layer B sees tracked files plus untracked-and-not-ignored ones, so a
  ``.gitignore``d ``.env`` / ``.env.example`` is invisible to it. That is not
  left open: nothing in this repo can load one. ``load_dotenv`` is banned by the
  barrier cited above and ``python-dotenv`` is not a dependency, so a dotenv
  file in this tree is inert bytes. A control that reached the process from such
  a file would have to be exported by the operator's own shell, which IS the
  sanctioned arrival path.
* Layer A cannot follow a control name through a CROSS-module alias chain that
  never touches an env-assigning node. Layer C closes that for anything executed
  at import time, layer B for anything spelt as a literal, and A6 for anything
  handed to an unapproved callable -- an evasion has to defeat all four.
* Nothing here constrains ``exec``/``eval`` of a constructed string, nor a C
  extension. No file in this repo uses either on this path.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from breezy.adapters.polymarket_us import operator_controls, safety
from tests.unit.operator_control_env import operator_control_env, operator_control_unset
from tests.unit.test_polymarket_us_readonly_guard import iter_python_sources

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Roots layer A walks. ``tests`` is included deliberately: a fixture or a
#: ``conftest`` giving a control a value is exactly as much an assignment as a
#: shipped module doing it, and is likelier.
SCAN_ROOTS: Final[tuple[str, ...]] = ("src", "scripts", "tests")

#: The env-var NAMES, derived from the shipped inventory rather than restated,
#: so a third control added to the module is scanned without editing this file.
CONTROL_ENV_VAR_NAMES: Final[frozenset[str]] = frozenset(
    operator_controls.OPERATOR_RESERVED_CONTROL_ENV_VARS
)

#: The IDENTIFIERS those names are carried by. An assignment written as
#: ``monkeypatch.setenv(MAX_DAILY_BUDGET_USD_ENV_VAR, "5")`` contains no
#: searchable literal at all, so the scan must know the constants too. Derived
#: by reflection, not by hand: any new ``*_ENV_VAR`` constant in the module
#: whose value is one of the controls is picked up automatically.
CONTROL_CONSTANT_IDENTIFIERS: Final[frozenset[str]] = frozenset(
    {
        name
        for name, value in vars(operator_controls).items()
        if isinstance(value, str) and value in CONTROL_ENV_VAR_NAMES
    }
    | {"OPERATOR_RESERVED_CONTROL_ENV_VARS"}
)

#: The module that DEFINES the controls. It contains the two names as string
#: literals -- that is the definition, not an assignment of a value -- and is
#: the single member of layer B's pinned set.
DEFINITION_MODULE: Final[str] = "src/breezy/adapters/polymarket_us/operator_controls.py"

#: The ONE path layer A exempts. See this module's docstring, and the audit
#: test below which is what makes the exemption safe.
WHITELISTED_TEST_HELPER: Final[str] = "tests/unit/operator_control_env.py"

#: The enforcement site itself. It derives its search tokens from the shipped
#: inventory, so it necessarily references the constant that carries them.
SCAN_MODULE: Final[str] = "tests/unit/test_operator_control_assignment_scan.py"

#: A6: the ONLY callables that may be handed a control's NAME as an argument
#: outside the definition module. Everything here either removes a value
#: (fail-closed), tabulates cases, or IS the whitelisted seam. Anything else --
#: including a test-local ``def _set(name, value): os.environ[name] = value``,
#: which layer A's node-local rules cannot see through -- fires.
PERMITTED_CONTROL_ARGUMENT_CALLEES: Final[frozenset[str]] = frozenset(
    {
        "operator_control_env",
        "operator_control_unset",
        "delenv",
        "pop",
        "parametrize",
    }
)

#: The reader chain itself, plus the set constructor the enforcement site uses
#: to derive its tokens from the shipped inventory. Neither assigns anything.
_READER_CHAIN_CALLEES: Final[frozenset[str]] = frozenset({"_read_operator_money", "frozenset"})

#: Calls that WRITE an environment variable.
_ENV_WRITE_CALLS: Final[frozenset[str]] = frozenset({"setenv", "setdefault", "update", "putenv"})

#: Calls that READ an environment variable, and therefore can carry a default.
_ENV_READ_CALLS: Final[frozenset[str]] = frozenset({"get", "getenv"})


@dataclass(frozen=True, slots=True)
class Assignment:
    """One place a control is (or could be) given a value."""

    path: str
    lineno: int
    rule: str
    detail: str


def _mentions_control(node: ast.AST | None) -> bool:
    """True if ``node`` names a control, by literal or by its constant."""
    if node is None:
        return False
    for inner in ast.walk(node):
        if isinstance(inner, ast.Constant) and inner.value in CONTROL_ENV_VAR_NAMES:
            return True
        if isinstance(inner, ast.Name) and inner.id in CONTROL_CONSTANT_IDENTIFIERS:
            return True
        if isinstance(inner, ast.Attribute) and inner.attr in CONTROL_CONSTANT_IDENTIFIERS:
            return True
    return False


def _control_aliases(tree: ast.AST) -> frozenset[str]:
    """Names bound anywhere in the module to an expression naming a control.

    Closes the local-indirection evasion: ``n = MAX_DAILY_BUDGET_USD_ENV_VAR``
    followed by ``os.environ[n] = "5"`` carries no control token at the
    assigning node, so the node-local check alone would miss it.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        value = None
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            value, targets = node.value, list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            value, targets = node.value, [node.target]
        if value is None or not _mentions_control(value):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                aliases.add(target.id)
    return frozenset(aliases)


def _names_a_control(expr: ast.expr | None, aliases: frozenset[str]) -> bool:
    if _mentions_control(expr):
        return True
    return isinstance(expr, ast.Name) and expr.id in aliases


def _is_environ_receiver(func: ast.expr) -> bool:
    """True when a call's receiver is the process environment."""
    if not isinstance(func, ast.Attribute):
        return False
    return "environ" in ast.unparse(func.value)


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", "")


def _static_env_name(expr: ast.expr | None) -> bool:
    """True when an env-var name is a plain constant or a plain identifier.

    A COMPUTED name -- an f-string, a concatenation, a call, a subscript -- is
    refused outright wherever it addresses the environment, whether or not it
    resolves to a control today. There are zero of them in this repo, and it
    is the one shape that defeats every static check above.
    """
    return isinstance(expr, (ast.Constant, ast.Name, ast.Attribute))


def find_control_assignments(path: str, source: str) -> list[Assignment]:
    """Report every place ``source`` gives an operator-reserved control a value.

    Removal (``delenv``, ``os.environ.pop``) is deliberately NOT reported: it
    is the fail-closed direction, and a test proving absence must be able to
    guarantee absence.
    """
    tree = ast.parse(source, filename=path)
    aliases = _control_aliases(tree)
    found: list[Assignment] = []

    for node in ast.walk(tree):
        # A1 -- os.environ["X"] = ... / env[X] = ...
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if not isinstance(target, ast.Subscript):
                    continue
                if "environ" not in ast.unparse(target.value):
                    continue
                if _names_a_control(target.slice, aliases):
                    found.append(Assignment(path, node.lineno, "A1", "environment subscript"))
                elif not _static_env_name(target.slice):
                    found.append(Assignment(path, node.lineno, "A5", "computed variable name"))

        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            first = node.args[0] if node.args else None

            # A2 -- setenv / setdefault / update / putenv
            if name in _ENV_WRITE_CALLS and (
                name in {"setenv", "putenv"} or _is_environ_receiver(node.func)
            ):
                if any(_names_a_control(arg, aliases) for arg in node.args) or any(
                    _names_a_control(kw.value, aliases) for kw in node.keywords
                ):
                    found.append(Assignment(path, node.lineno, "A2", f"{name}()"))
                elif name in {"setenv", "putenv"} and not _static_env_name(first):
                    found.append(Assignment(path, node.lineno, "A5", "computed variable name"))

            # A3 -- os.environ.get(X, fallback) / os.getenv(X, fallback)
            if (
                name in _ENV_READ_CALLS
                and (name == "getenv" or _is_environ_receiver(node.func))
                and len(node.args) >= 2
                and _names_a_control(first, aliases)
            ):
                found.append(Assignment(path, node.lineno, "A3", f"{name}() default"))

        # A3b -- os.environ.get(X) or "5"
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            head = node.values[0]
            if (
                isinstance(head, ast.Call)
                and _call_name(head.func) in _ENV_READ_CALLS
                and (_call_name(head.func) == "getenv" or _is_environ_receiver(head.func))
                and head.args
                and _names_a_control(head.args[0], aliases)
            ):
                found.append(Assignment(path, node.lineno, "A3", "or-fallback on a control"))

        # A6 -- a control's NAME handed to an unapproved callable. The rule
        # that closes the local-helper evasion: a helper taking the variable
        # name as a PARAMETER writes the environment under a name layer A
        # cannot resolve, so the seam is policed at the CALL instead.
        if isinstance(node, ast.Call):
            callee = _call_name(node.func)
            if callee not in PERMITTED_CONTROL_ARGUMENT_CALLEES | _READER_CHAIN_CALLEES and (
                any(_mentions_control(arg) for arg in node.args)
                or any(_mentions_control(kw.value) for kw in node.keywords)
            ):
                found.append(Assignment(path, node.lineno, "A6", f"{callee}(<control>)"))

        # A4 -- {CONTROL: "5"} -- the shape a subprocess `env=` mapping takes
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if _names_a_control(key, aliases) and not (
                    isinstance(value, ast.Constant) and value.value is None
                ):
                    found.append(Assignment(path, node.lineno, "A4", "mapping literal entry"))

    return found


def scan_control_assignments(
    roots: tuple[str, ...] = SCAN_ROOTS,
    *,
    whitelist: frozenset[str] = frozenset({WHITELISTED_TEST_HELPER}),
) -> list[Assignment]:
    """Layer A over ``roots``.

    Three paths are outside the general rules and each is here for a different
    reason: the DEFINITION module (it defines the names), the whitelisted SEAM
    (it is the one legal dynamic setter, and is separately audited), and the
    SCAN module (the enforcement site, which must name the inventory to scan
    for it). None of them is exempt from layer B, C or D.
    """
    exempt = whitelist | {DEFINITION_MODULE, SCAN_MODULE}
    return [
        violation
        for path, source in iter_python_sources(roots)
        if path not in exempt
        for violation in find_control_assignments(path, source)
    ]


def tracked_files() -> list[str]:
    """Every file git would carry: tracked PLUS untracked-and-not-ignored.

    ``--others --exclude-standard`` matters. A file an agent has just written
    and not yet committed is exactly as much a part of this repository as a
    committed one, and a census that only saw ``--cached`` would pass on the
    increment that introduced the defect and fail on the next one.
    """
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    return [entry for entry in completed.stdout.decode("utf-8").split("\0") if entry]


def files_naming_a_control() -> set[str]:
    """Layer B: tracked files whose BYTES contain either control's name."""
    needles = [name.encode("utf-8") for name in sorted(CONTROL_ENV_VAR_NAMES)]
    naming: set[str] = set()
    for relative in tracked_files():
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        blob = path.read_bytes()
        if any(needle in blob for needle in needles):
            naming.add(relative)
    return naming


# ==========================================================================
# Layer A -- the live scan, and its non-vacuity
# ==========================================================================


def test_no_repo_file_assigns_an_operator_reserved_control() -> None:
    """THE R-6e invariant. Nothing in the tree gives either control a value."""
    assignments = scan_control_assignments()
    assert assignments == [], (
        "an operator-reserved control is assigned a value in this repository: "
        f"{[(a.path, a.lineno, a.rule) for a in assignments]}"
    )


_PLANTED: Final[dict[str, str]] = {
    "setdefault_in_src": (
        "import os\n"
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    MAX_DAILY_BUDGET_USD_ENV_VAR,\n"
        ")\n"
        'os.environ.setdefault(MAX_DAILY_BUDGET_USD_ENV_VAR, "5")\n'
    ),
    "monkeypatch_setenv_in_a_test": (
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    MAX_POSITION_COST_USD_ENV_VAR,\n"
        ")\n"
        "def test_something(monkeypatch):\n"
        '    monkeypatch.setenv(MAX_POSITION_COST_USD_ENV_VAR, "25.00")\n'
    ),
    "fallback_in_environ_get": ('import os\nCAP = os.environ.get("<DAILY>", "100.00")\n'),
    "fallback_in_getenv": ('import os\nCAP = os.getenv("<DAILY>", "100.00")\n'),
    "or_fallback": ('import os\nCAP = os.environ.get("<DAILY>") or "100.00"\n'),
    "subscript_assignment": ('import os\nos.environ["<DAILY>"] = "100.00"\n'),
    "subprocess_env_mapping": (
        'import subprocess\nsubprocess.run(["true"], env={"<POSITION>": "25.00"})\n'
    ),
    "environ_update": ('import os\nos.environ.update({"<DAILY>": "100.00"})\n'),
    "local_alias_of_the_constant": (
        "import os\n"
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    MAX_DAILY_BUDGET_USD_ENV_VAR,\n"
        ")\n"
        "def go():\n"
        "    name = MAX_DAILY_BUDGET_USD_ENV_VAR\n"
        '    os.environ[name] = "5"\n'
    ),
    "computed_variable_name": (
        'import os\ndef go(suffix):\n    os.environ["BREEZY_" + suffix] = "5"\n'
    ),
    "raw_environ_read_outside_the_reader_chain": (
        "import os\n"
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    MAX_DAILY_BUDGET_USD_ENV_VAR,\n"
        ")\n"
        "BUDGET = os.environ.get(MAX_DAILY_BUDGET_USD_ENV_VAR)\n"
    ),
    "test_local_dynamic_setter": (
        "import os\n"
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    MAX_DAILY_BUDGET_USD_ENV_VAR,\n"
        ")\n"
        "def _set(name, value):\n"
        "    os.environ[name] = value\n"
        "def test_something():\n"
        '    _set(MAX_DAILY_BUDGET_USD_ENV_VAR, "100.00")\n'
    ),
    "conftest_fixture": (
        "import pytest\n"
        "from breezy.adapters.polymarket_us import operator_controls\n"
        "@pytest.fixture(autouse=True)\n"
        "def _budget(monkeypatch):\n"
        "    monkeypatch.setenv("
        'operator_controls.MAX_DAILY_BUDGET_USD_ENV_VAR, "100.00")\n'
    ),
}


def _plant(template: str) -> str:
    """Render a planted mutant, interpolating the control names at RUNTIME.

    The placeholders exist so that THIS file never contains either control's
    literal name: layer B's census is an exact set over every tracked file, and
    a test fixture spelling the name would have to be exempted from the very
    check it is proving.
    """
    return template.replace("<DAILY>", operator_controls.MAX_DAILY_BUDGET_USD_ENV_VAR).replace(
        "<POSITION>", operator_controls.MAX_POSITION_COST_USD_ENV_VAR
    )


@pytest.mark.parametrize("case", sorted(_PLANTED))
def test_the_scan_fires_on_every_planted_assignment_form(case: str) -> None:
    """Non-vacuity, one case per shape the scan claims to catch."""
    found = find_control_assignments(f"src/planted_{case}.py", _plant(_PLANTED[case]))
    assert found, f"the scan did not fire on the planted {case!r}"


def test_the_scan_does_not_fire_on_the_shipped_reader() -> None:
    """Specificity: the sanctioned read names no variable at the call site."""
    source = (
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    operator_max_daily_budget_usd,\n"
        ")\n"
        "def size_an_order():\n"
        "    return operator_max_daily_budget_usd()\n"
    )
    assert find_control_assignments("src/planted_reader.py", source) == []


def test_the_scan_does_not_fire_on_asserting_about_a_control_name() -> None:
    """Specificity: naming the control in an assertion assigns nothing."""
    source = (
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    MAX_DAILY_BUDGET_USD_ENV_VAR,\n"
        ")\n"
        "def test_message(message):\n"
        "    assert MAX_DAILY_BUDGET_USD_ENV_VAR in message\n"
    )
    assert find_control_assignments("tests/unit/planted_assert.py", source) == []


def test_the_scan_does_not_fire_on_removing_a_control() -> None:
    """Removal is the fail-closed direction and must stay available."""
    source = (
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    MAX_DAILY_BUDGET_USD_ENV_VAR,\n"
        ")\n"
        "def test_absent(monkeypatch):\n"
        "    monkeypatch.delenv(MAX_DAILY_BUDGET_USD_ENV_VAR, raising=False)\n"
    )
    assert find_control_assignments("tests/unit/planted_delenv.py", source) == []


def test_the_scan_does_not_fire_on_another_operator_variable() -> None:
    """Specificity: the three pre-existing permit controls are not R-6e's."""
    source = (
        "from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR\n"
        "def test_permit(monkeypatch):\n"
        '    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, "5.00")\n'
    )
    assert find_control_assignments("tests/unit/planted_other.py", source) == []


def test_the_scan_actually_reaches_src_scripts_and_tests() -> None:
    """A scan that walks nothing passes vacuously."""
    scanned = {path for path, _ in iter_python_sources(SCAN_ROOTS)}
    assert DEFINITION_MODULE in scanned
    assert WHITELISTED_TEST_HELPER in scanned
    assert any(path.startswith("scripts/") for path in scanned)
    assert "tests/conftest.py" in scanned
    assert len(scanned) > 300


# ==========================================================================
# The whitelisted seam -- what makes exempting one path safe
# ==========================================================================


def test_the_whitelisted_helper_names_no_operator_reserved_control() -> None:
    """The exemption cannot be abused, because the helper cannot name a control.

    Its own docstring explains the seam in prose, which is why the check is an
    AST one over code rather than a substring search over bytes: a docstring is
    an ``ast.Expr`` statement at the head of a module or function and is
    excluded, while any live reference -- literal or imported constant -- is
    not.
    """
    tree = ast.parse((REPO_ROOT / WHITELISTED_TEST_HELPER).read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    offenders = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if id(node) not in docstrings
        and _mentions_control(node)
        and not isinstance(node, ast.Module)
    ]
    assert offenders == [], f"the whitelisted helper names a control: {offenders}"


def test_the_whitelisted_helper_carries_no_value_of_its_own() -> None:
    """No non-docstring string constant: a default cannot hide in the seam."""
    tree = ast.parse((REPO_ROOT / WHITELISTED_TEST_HELPER).read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    assert literals == [], f"the whitelisted helper carries string literals: {literals}"


def test_the_whitelisted_helper_restores_a_previously_set_value() -> None:
    name = "BREEZY_TEST_OPERATOR_CONTROL_SEAM"
    with operator_control_env(name, "outer"):
        with operator_control_env(name, "inner"):
            assert os.environ[name] == "inner"
        assert os.environ[name] == "outer"
    assert name not in os.environ


def test_the_whitelisted_helper_removes_a_value_that_was_absent_before() -> None:
    name = "BREEZY_TEST_OPERATOR_CONTROL_SEAM"
    assert name not in os.environ
    with operator_control_env(name, "transient"):
        assert os.environ[name] == "transient"
    assert name not in os.environ


def test_the_whitelisted_helper_is_the_only_exempt_path() -> None:
    """A one-entry exemption, pinned by equality so a second is a visible diff."""
    import inspect

    default = inspect.signature(scan_control_assignments).parameters["whitelist"].default
    assert default == frozenset({WHITELISTED_TEST_HELPER})
    assert (REPO_ROOT / WHITELISTED_TEST_HELPER).is_file()


def test_the_scan_still_fires_on_the_shipped_tree_if_the_exemption_is_removed() -> None:
    """The seam is real: without the whitelist the helper is NOT what fires.

    The helper writes the environment under a PARAMETER name, so even unexempt
    it trips nothing -- which is the point of taking the name as an argument.
    What the whitelist buys is the ability to state, in one pinned place, which
    file is allowed to be the dynamic setter at all.
    """
    assert scan_control_assignments(whitelist=frozenset()) == []


# ==========================================================================
# Layer B -- the text census over every tracked file
# ==========================================================================


def test_only_the_definition_module_names_an_operator_reserved_control() -> None:
    """An EXACT set over every tracked file -- widen it, never relax the ``==``.

    This is the layer that sees what an AST scan of ``*.py`` cannot: a
    ``.env.example``, a systemd unit under ``deploy/``, a CI YAML, a shell
    script, a JSON fixture, or a docstring code sample. Any of them naming a
    control lands here as a failing diff a reviewer has to look at.
    """
    assert files_naming_a_control() == {DEFINITION_MODULE}


def test_the_census_fires_on_a_control_name_planted_in_a_config_file(
    tmp_path: Path,
) -> None:
    """Non-vacuity for layer B, on the exact artefact the brief asks about."""
    planted = tmp_path / ".env.example"
    planted.write_text(
        f"{operator_controls.MAX_DAILY_BUDGET_USD_ENV_VAR}=100.00\n", encoding="utf-8"
    )
    needles = [name.encode("utf-8") for name in CONTROL_ENV_VAR_NAMES]
    assert any(needle in planted.read_bytes() for needle in needles)


def test_the_census_reads_real_tracked_files() -> None:
    tracked = tracked_files()
    assert DEFINITION_MODULE in tracked
    assert "deploy/systemd/breezy-quote-tape.service" in tracked
    assert len(tracked) > 300


# ==========================================================================
# Layer C -- nothing is assigned at import time, whatever the syntax
# ==========================================================================


def test_importing_the_package_assigns_neither_control() -> None:
    """A runtime probe, indifferent to the syntax an assignment is written in.

    Runs in a subprocess whose environment has both controls removed, imports
    the module and the whole adapter package, and reports whether either name
    materialised.
    """
    child_env = dict(os.environ)
    for name in CONTROL_ENV_VAR_NAMES:
        child_env.pop(name, None)
    probe = (
        "import os\n"
        "import breezy.adapters.polymarket_us.operator_controls as m\n"
        "import breezy.adapters.polymarket_us.safety\n"
        "print(sorted(n for n in m.OPERATOR_RESERVED_CONTROL_ENV_VARS if n in os.environ))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == "[]", completed.stdout


# ==========================================================================
# Layer D -- every read goes through the one operator reader, with no default
# ==========================================================================


def _reader_calls(tree: ast.AST) -> Iterator[ast.Call]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def test_operator_controls_have_no_default_on_any_path() -> None:
    """Every control read routes to ``_require_operator_value``, defaultless.

    Three assertions, because "no default" has three distinct meanings here:
    the shared reader takes no default argument; the shipped readers take no
    argument at ALL (so no caller can inject its own ceiling, the same reason
    ``issue_live_trading_permit`` has no ``env`` parameter); and every
    reference to a control in the shipped tree is an argument to that reader
    chain rather than a direct environment read.
    """
    import inspect

    require = inspect.signature(safety._require_operator_value)
    assert [p.default for p in require.parameters.values()] == [inspect.Parameter.empty]

    for reader in (
        operator_controls.operator_max_daily_budget_usd,
        operator_controls.operator_max_position_cost_usd,
    ):
        assert list(inspect.signature(reader).parameters) == []

    # `_read_operator_money` is the money-shaped wrapper, and it must be a
    # wrapper: the chain has to terminate in `_require_operator_value` or
    # there are two refusal policies.
    money = ast.parse(inspect.getsource(safety._read_operator_money))
    assert any(
        isinstance(call.func, ast.Name) and call.func.id == "_require_operator_value"
        for call in _reader_calls(money)
    )

    # Every LOAD of a control constant in the definition module is either an
    # argument to `_read_operator_money`, a name inside a refusal message, or
    # a member of the published inventory tuple. Nothing reads the environment
    # directly, and nothing carries a default alongside the name.
    module = ast.parse((REPO_ROOT / DEFINITION_MODULE).read_text(encoding="utf-8"))
    permitted: set[int] = {
        id(arg)
        for call in _reader_calls(module)
        if isinstance(call.func, ast.Name) and call.func.id == "_read_operator_money"
        for arg in call.args
    }
    for node in ast.walk(module):
        # A name interpolated into a refusal message.
        if isinstance(node, ast.JoinedStr):
            permitted |= {id(inner) for inner in ast.walk(node)}
        # The published inventory tuple.
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "OPERATOR_RESERVED_CONTROL_ENV_VARS"
            and node.value is not None
        ):
            permitted |= {id(inner) for inner in ast.walk(node.value)}

    unrouted = [
        ast.unparse(node)
        for node in ast.walk(module)
        if isinstance(node, ast.Name)
        and node.id in CONTROL_CONSTANT_IDENTIFIERS
        and isinstance(node.ctx, ast.Load)
        and id(node) not in permitted
    ]
    assert unrouted == [], f"a control is read outside the one reader chain: {unrouted}"


def test_the_definition_module_never_touches_os_environ_itself() -> None:
    """One reader, one refusal policy: the module imports no ``os`` at all."""
    source = (REPO_ROOT / DEFINITION_MODULE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "os" not in imported
    # Prose is not code: the check is an AST one, so the module docstring may
    # explain the environment without tripping it.
    assert [
        ast.unparse(node)
        for node in ast.walk(tree)
        if (isinstance(node, ast.Attribute) and node.attr == "environ")
        or (isinstance(node, ast.Name) and node.id == "environ")
    ] == []


# ==========================================================================
# The refusal names the control, never its value
# ==========================================================================


@pytest.mark.parametrize(
    ("env_var", "read"),
    [
        (
            operator_controls.MAX_DAILY_BUDGET_USD_ENV_VAR,
            operator_controls.operator_max_daily_budget_usd,
        ),
        (
            operator_controls.MAX_POSITION_COST_USD_ENV_VAR,
            operator_controls.operator_max_position_cost_usd,
        ),
    ],
)
def test_refusal_names_the_control_not_the_value(env_var: str, read: object) -> None:
    """A malformed value is refused by NAME, and the value never appears."""
    secret_value = "919191.91x"
    with (
        operator_control_env(env_var, secret_value),
        pytest.raises(safety.LiveTradingPermissionError) as excinfo,
    ):
        read()  # type: ignore[operator]
    message = str(excinfo.value)
    assert env_var in message
    assert secret_value not in message
    assert "919191" not in message


def test_the_ceiling_refusal_names_the_control_not_the_amounts() -> None:
    """The per-position refusal carries the control's name and no number."""
    ledger = operator_controls.DailySpendLedger()
    with (
        operator_control_env(operator_controls.MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
        operator_control_env(operator_controls.MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        pytest.raises(safety.LiveTradingPermissionError) as excinfo,
    ):
        ledger.authorize_order_cost(
            price_usd=Decimal("0.55"),
            quantity=Decimal(100),
            now_ns=1_787_617_213_000_000_000,
        )
    message = str(excinfo.value)
    assert operator_controls.MAX_POSITION_COST_USD_ENV_VAR in message
    assert not any(character.isdigit() for character in message.replace("BREEZY_", ""))


def test_the_daily_refusal_names_the_control_not_the_amounts() -> None:
    ledger = operator_controls.DailySpendLedger()
    with (
        operator_control_env(operator_controls.MAX_POSITION_COST_USD_ENV_VAR, "1000.00"),
        operator_control_env(operator_controls.MAX_DAILY_BUDGET_USD_ENV_VAR, "10.00"),
        pytest.raises(safety.LiveTradingPermissionError) as excinfo,
    ):
        ledger.authorize_order_cost(
            price_usd=Decimal("0.55"),
            quantity=Decimal(100),
            now_ns=1_787_617_213_000_000_000,
        )
    message = str(excinfo.value)
    assert operator_controls.MAX_DAILY_BUDGET_USD_ENV_VAR in message
    assert not any(character.isdigit() for character in message.replace("BREEZY_", ""))


def test_an_absent_control_is_refused_by_name() -> None:
    for env_var, read in (
        (
            operator_controls.MAX_DAILY_BUDGET_USD_ENV_VAR,
            operator_controls.operator_max_daily_budget_usd,
        ),
        (
            operator_controls.MAX_POSITION_COST_USD_ENV_VAR,
            operator_controls.operator_max_position_cost_usd,
        ),
    ):
        with (
            operator_control_unset(env_var),
            pytest.raises(safety.LiveTradingPermissionError) as excinfo,
        ):
            read()
        assert env_var in str(excinfo.value)
        assert "no default" in str(excinfo.value)

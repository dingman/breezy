"""Barrier W1: every weather `DataType` comes from the ONE shared factory.

Why this file exists (the defect it pins). ``DataType.__eq__`` and
``DataType.__hash__`` compare a ``frozenset`` of the metadata items, while
``DataType.topic`` -- the string the message bus actually routes on -- is built
from the metadata in INSERTION ORDER. Measured on the installed
``nautilus-trader==1.231.0``::

    DataType(NwsClimateDay, {"p": 1, "q": 2}) == DataType(NwsClimateDay, {"q": 2, "p": 1})
    # True, and the hashes are equal
    .topic  ->  "NwsClimateDay.p=1.q=2"   vs   "NwsClimateDay.q=2.p=1"

So two ``DataType`` objects can be indistinguishable to every equality-based
unit test in this repo and still publish and subscribe on DIFFERENT topics. The
publisher's messages match nobody's pattern, ``is_matching_py`` returns False,
and the subscriber receives ZERO records with no error raised anywhere. Phase 1
carries no metadata at all precisely so this cannot bite today -- but "no
metadata" is a property of the ONE construction site, and it is only true while
there is one construction site.

The defence has two halves, and this file proves the second:

1. **The shared factories.** ``nws_climate_day_data_type()`` and
   ``nws_raw_product_data_type()`` (``src/breezy/ingest/nws_actor.py``), both
   ``lru_cache``d, so every caller gets the SAME object -- not merely an equal
   one. The live publisher, the warm-start path, the backtest feed and any
   future ``BacktestDataConfig`` all route through them.

2. **A barrier that forces them to be used.** Until now the rule "never
   construct another" lived only in a comment above the factories
   (``nws_actor.py:365-378``). A comment does not fail a build. Rule W1 below
   makes an inline construction a TEST FAILURE.

RULE W1, stated so it is falsifiable (and proved non-vacuous by the
``*_detects_*`` tests below):

  Step 1 -- scan every module under ``src/`` and ``scripts/``. Unlike barriers
  B4 and F1 there is no venue-touching pre-filter: a weather ``DataType`` is
  wrong wherever it is built, and the exempt set is one named pair of
  functions rather than a class of modules.

  Step 2 -- collect every ``ast.Call`` whose callee is named ``DataType``
  (bare ``DataType(...)`` or dotted ``data.DataType(...)``, so an aliased
  import does not bypass the rule) whose record argument -- first positional
  or the ``type=`` keyword -- names ``NwsClimateDay`` or ``NwsRawProduct``,
  as a bare name or as an attribute (``domain.NwsClimateDay``).

  Step 3 -- a collected construction is EXEMPT only when it sits inside one of
  the two shared factory functions, BY NAME, in the factory module itself.
  Everything else is a violation. The exemption is deliberately not "anything
  in ``nws_actor.py``": that module is the one most likely to grow a second,
  well-meant construction site.

RESIDUAL GAPS, stated precisely rather than papered over. This barrier is
syntactic, so three holes remain OPEN and are pinned by tests so they cannot
be mistaken for closed:

  G1 -- **indirection through a variable.** ``cls = NwsClimateDay;
  DataType(cls)`` is not detected, because the rule resolves no names. Closing
  it needs reaching-definitions analysis. Pinned by
  ``test_the_documented_residual_gap_is_real_and_reported_honestly``.

  G2 -- **a fully dynamic callee.** ``getattr(data, "DataType")(...)`` names
  no callee statically. Same class of gap that barriers B4 and F1 document.

  G3 -- **construction outside the scanned roots.** Only ``src/`` and
  ``scripts/`` are scanned. Tests build ``DataType`` objects freely and must
  be able to -- several tests below do exactly that to prove the hazard.

None of the three is reachable by accident, which is the failure mode this
barrier exists to stop.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from nautilus_trader.model.data import DataType

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.ingest.nws_actor import nws_climate_day_data_type, nws_raw_product_data_type
from tests.unit.test_polymarket_us_readonly_guard import iter_python_sources

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

#: Roots scanned by rule W1 (same shape as barriers B4 and F1).
WEATHER_SCAN_ROOTS = ("src", "scripts")

#: The record classes that have exactly one legitimate `DataType` each.
_RECORD_NAMES = frozenset({"NwsClimateDay", "NwsRawProduct"})

#: The two shared factories, and the ONE module they are allowed to live in.
_FACTORY_NAMES = frozenset({"nws_climate_day_data_type", "nws_raw_product_data_type"})
_FACTORY_MODULE = "src/breezy/ingest/nws_actor.py"


@dataclass(frozen=True, slots=True)
class DataTypeViolation:
    path: str
    lineno: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: [W1] {self.detail}"


def _record_name(node: ast.expr | None) -> str | None:
    """Return the record class name `node` refers to, if it names one directly.

    Bare ``NwsClimateDay`` and dotted ``domain.NwsClimateDay`` both resolve;
    anything else (a variable, a subscript, a call) does not -- see gap G1.
    """
    if isinstance(node, ast.Name) and node.id in _RECORD_NAMES:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in _RECORD_NAMES:
        return node.attr
    return None


def _data_type_constructions(tree: ast.AST) -> Iterator[tuple[ast.Call, str]]:
    """Yield `(call, record_name)` for each weather `DataType` construction."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if callee != "DataType":
            continue
        argument = node.args[0] if node.args else None
        if argument is None:
            argument = next((kw.value for kw in node.keywords if kw.arg == "type"), None)
        record = _record_name(argument)
        if record is not None:
            yield node, record


def _exempt_factory_calls(tree: ast.AST) -> set[ast.Call]:
    """Return the constructions sitting inside a shared factory's own body."""
    exempt: set[ast.Call] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name not in _FACTORY_NAMES:
            continue
        exempt.update(call for call, _ in _data_type_constructions(node))
    return exempt


def find_inline_data_type_constructions(
    path: str,
    source: str,
    *,
    allow_factories: bool = True,
) -> list[DataTypeViolation]:
    """Apply rule W1 to one module.

    ``allow_factories=False`` disables the exemption and is used only by
    ``test_the_exemption_covers_exactly_the_two_shared_factories``, which
    proves the exemption is load-bearing rather than vacuous.
    """
    tree = ast.parse(source, filename=path)
    exempt = (
        _exempt_factory_calls(tree) if allow_factories and path == _FACTORY_MODULE else set()
    )
    return [
        DataTypeViolation(path, call.lineno, f"constructs DataType({record}) inline")
        for call, record in _data_type_constructions(tree)
        if call not in exempt
    ]


def scan_inline_data_type_constructions(
    roots: tuple[str, ...] = WEATHER_SCAN_ROOTS,
) -> list[DataTypeViolation]:
    return [
        v
        for path, src in iter_python_sources(roots)
        for v in find_inline_data_type_constructions(path, src)
    ]


# ---------------------------------------------------------------------------
# The hazard itself, pinned rather than certified as acceptable
# ---------------------------------------------------------------------------


def test_two_equal_data_types_can_route_to_different_topics() -> None:
    """The defect W1 exists to prevent, demonstrated on the real class.

    Equality and hash agree; the ROUTING string does not. Every equality-based
    assertion in this repo is therefore blind to the difference that decides
    whether a subscriber receives anything at all.
    """
    a = DataType(NwsClimateDay, {"p": 1, "q": 2})
    b = DataType(NwsClimateDay, {"q": 2, "p": 1})

    assert a == b
    assert hash(a) == hash(b)
    assert a.topic != b.topic


def test_the_shared_factories_return_one_object_not_merely_an_equal_one() -> None:
    """Identity is the property the barrier protects, so it is asserted here."""
    assert nws_climate_day_data_type() is nws_climate_day_data_type()
    assert nws_raw_product_data_type() is nws_raw_product_data_type()
    assert nws_climate_day_data_type() is not nws_raw_product_data_type()


def test_the_shared_factories_carry_no_metadata() -> None:
    """No metadata means no ordering to disagree about -- by construction.

    A metadata-bearing subscriber never receives a metadata-less publication,
    so the empty mapping here and an omitted ``BacktestDataConfig(metadata=...)``
    there match by construction rather than by review.
    """
    assert nws_climate_day_data_type().metadata == {}
    assert nws_climate_day_data_type().topic == "NwsClimateDay*"
    assert nws_raw_product_data_type().metadata == {}
    assert nws_raw_product_data_type().topic == "NwsRawProduct*"


# ---------------------------------------------------------------------------
# Rule W1 over the repository
# ---------------------------------------------------------------------------


def test_no_module_constructs_a_weather_data_type_inline() -> None:
    violations = scan_inline_data_type_constructions()

    assert not violations, "\n".join(str(v) for v in violations)


def test_the_exemption_covers_exactly_the_two_shared_factories() -> None:
    """Non-vacuity: without the exemption, the factory module IS flagged.

    Two hits, one per factory. If this drops to zero the detector has stopped
    detecting and the repo-wide scan above is passing for the wrong reason.
    """
    source = next(
        src for path, src in iter_python_sources(("src",)) if path == _FACTORY_MODULE
    )

    unexempt = find_inline_data_type_constructions(
        _FACTORY_MODULE, source, allow_factories=False
    )
    exempt = find_inline_data_type_constructions(_FACTORY_MODULE, source)

    assert len(unexempt) == 2
    assert exempt == []


def test_the_exemption_is_bound_to_the_factory_module_not_the_function_name() -> None:
    """A second module may not re-declare a same-named factory and be excused."""
    source = (
        "from nautilus_trader.model.data import DataType\n"
        "from breezy.domain.nws_climate_day import NwsClimateDay\n"
        "def nws_climate_day_data_type():\n"
        "    return DataType(NwsClimateDay)\n"
    )

    violations = find_inline_data_type_constructions("src/breezy/elsewhere.py", source)

    assert len(violations) == 1


# ---------------------------------------------------------------------------
# The detector detects (proving the repo-wide pass is not vacuous)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("bare call", "DataType(NwsClimateDay)\n"),
        ("with metadata", 'DataType(NwsClimateDay, {"p": 1, "q": 2})\n'),
        ("raw product", "DataType(NwsRawProduct)\n"),
        ("dotted callee", "data.DataType(NwsClimateDay)\n"),
        ("dotted record", "nws.NwsRawProduct\nDataType(nws.NwsRawProduct)\n"),
        ("keyword form", "DataType(type=NwsClimateDay)\n"),
        ("inside a function", "def f():\n    return DataType(NwsClimateDay)\n"),
        ("inside a class body", "class C:\n    dt = DataType(NwsRawProduct)\n"),
    ],
)
def test_the_rule_detects_an_inline_construction(label: str, source: str) -> None:
    violations = find_inline_data_type_constructions("src/breezy/probe.py", source)

    assert len(violations) == 1, label
    assert str(violations[0]).startswith("src/breezy/probe.py:")
    assert "[W1]" in str(violations[0])


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("a foreign record class", "DataType(QuoteTick)\n"),
        ("a call to the shared factory", "nws_climate_day_data_type()\n"),
        ("an unrelated callee", "SomethingElse(NwsClimateDay)\n"),
        ("a bare reference", "records = [NwsClimateDay]\n"),
    ],
)
def test_the_rule_leaves_legitimate_code_alone(label: str, source: str) -> None:
    assert find_inline_data_type_constructions("src/breezy/probe.py", source) == [], label


def test_the_documented_residual_gap_is_real_and_reported_honestly() -> None:
    """Gap G1: indirection through a variable is NOT detected.

    Asserted rather than hoped for, so the gap cannot quietly be believed
    closed. It is unreachable by accident -- writing it requires deliberately
    routing the class through a local -- but it is a hole and it is named.
    """
    source = "cls = NwsClimateDay\nDataType(cls)\n"

    assert find_inline_data_type_constructions("src/breezy/probe.py", source) == []

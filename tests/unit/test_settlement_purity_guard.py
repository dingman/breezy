"""AST barriers over the pure settlement package."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from tests.unit.test_polymarket_us_readonly_guard import Violation, iter_python_sources

SETTLEMENT_ROOT = "src/breezy/settlement"
SETTLEMENT_SCAN_ROOTS = ("src/breezy/settlement",)
SRC_SCAN_ROOTS = ("src/breezy",)

_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "datetime",
        "httpx",
        "json",
        "os",
        "pathlib",
        "random",
        "requests",
        "secrets",
        "socket",
        "subprocess",
        "time",
    }
)
_FORBIDDEN_CALLS = frozenset({"open", "input", "print"})

_PINNED_DETERMINATION_FIELDS = {
    "CityDetermination": frozenset(
        {
            "city",
            "determination",
            "tradeable",
            "boundary_classification",
            "blocking_cells",
            "expiry_disposition",
            "escalation_required",
            "reason",
        }
    ),
    "CityProgrammeDetermination": frozenset(
        {"city", "city_determination", "scope", "position_taking"}
    ),
    "ProgrammeDetermination": frozenset(
        {
            "determination",
            "city_determinations",
            "primary_city_determinations",
            "secondary_city_determinations",
            "out_of_scope_city_determinations",
            "rejecting_primary_cities",
            "primary_no_go_count",
            "reason",
        }
    ),
}

_D4A_RE = re.compile(
    r"(?i)conservatism|conservative_estimator|estimator_conservat|"
    r"one_sided_conservat|metar_reads_below|reads_below_cli"
)
_D4B_RE = re.compile(r"(?i)^(metar|cli)_(above|below)_(cli|metar)$")


@dataclass(frozen=True, slots=True)
class IdentifierRecord:
    name: str
    kind: str
    lineno: int
    class_name: str | None = None
    class_fields: frozenset[str] = frozenset()
    function_parameters: frozenset[str] = frozenset()
    enum_members: frozenset[str] = frozenset()


def find_settlement_purity_violations(path: str, source: str) -> list[Violation]:
    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_IMPORT_ROOTS:
                    violations.append(Violation(path, node.lineno, "D1", f"import {root}"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                violations.append(Violation(path, node.lineno, "D1", f"import {root}"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FORBIDDEN_CALLS
        ):
            violations.append(Violation(path, node.lineno, "D1", f"call {node.func.id}"))
    return violations


def scan_settlement_purity() -> list[Violation]:
    return [
        violation
        for path, source in iter_python_sources(SETTLEMENT_SCAN_ROOTS)
        for violation in find_settlement_purity_violations(path, source)
    ]


def find_reporting_import_violations(path: str, source: str) -> list[Violation]:
    if not path.startswith(SETTLEMENT_ROOT + "/") or path.endswith("/reporting.py"):
        return []
    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "breezy.settlement.reporting":
                    violations.append(Violation(path, node.lineno, "D2", alias.name))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module == "breezy.settlement.reporting"
        ):
            violations.append(Violation(path, node.lineno, "D2", node.module))
    return violations


def scan_reporting_imports() -> list[Violation]:
    return [
        violation
        for path, source in iter_python_sources(SETTLEMENT_SCAN_ROOTS)
        for violation in find_reporting_import_violations(path, source)
    ]


def extract_determination_fields(path: str, source: str) -> dict[str, frozenset[str]]:
    tree = ast.parse(source, filename=path)
    found: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in _PINNED_DETERMINATION_FIELDS:
            continue
        fields = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fields.append(item.target.id)
        found[node.name] = frozenset(fields)
    return found


def scan_determination_field_drift() -> list[Violation]:
    actual: dict[str, frozenset[str]] = {}
    for path, source in iter_python_sources(SETTLEMENT_SCAN_ROOTS):
        actual.update(extract_determination_fields(path, source))
    violations = []
    for name, expected in _PINNED_DETERMINATION_FIELDS.items():
        observed = actual.get(name, frozenset())
        if observed != expected:
            violations.append(
                Violation(
                    "<settlement dataclasses>",
                    0,
                    "D3",
                    f"{name}: expected={sorted(expected)!r}, observed={sorted(observed)!r}",
                )
            )
    return violations


def _decorator_names(node: ast.ClassDef) -> set[str]:
    names = set()
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name):
            names.add(decorator.id)
        elif isinstance(decorator, ast.Attribute):
            names.add(decorator.attr)
        elif isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _base_names(node: ast.ClassDef) -> set[str]:
    names = set()
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def _opposite_polarity(name: str) -> str | None:
    match = _D4B_RE.match(name)
    if match is None:
        return None
    left, relation, right = match.groups()
    opposite = "below" if relation.lower() == "above" else "above"
    return f"{left}_{opposite}_{right}".upper()


def iter_identifier_records(path: str, source: str) -> list[IdentifierRecord]:
    tree = ast.parse(source, filename=path)
    records: list[IdentifierRecord] = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            records.append(IdentifierRecord(node.target.id, "constant", node.lineno))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    records.append(IdentifierRecord(target.id, "constant", node.lineno))
        elif isinstance(node, ast.FunctionDef):
            records.append(
                IdentifierRecord(
                    node.name,
                    "function",
                    node.lineno,
                    function_parameters=frozenset(arg.arg for arg in node.args.args),
                )
            )
        elif isinstance(node, ast.ClassDef):
            class_fields = frozenset(
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            )
            enum_members = frozenset(
                item.targets[0].id
                for item in node.body
                if isinstance(item, ast.Assign)
                and item.targets
                and isinstance(item.targets[0], ast.Name)
            )
            is_enum = "Enum" in _base_names(node)
            records.append(
                IdentifierRecord(
                    node.name,
                    "class",
                    node.lineno,
                    class_fields=class_fields,
                    enum_members=enum_members if is_enum else frozenset(),
                )
            )
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    records.append(
                        IdentifierRecord(
                            item.target.id,
                            "field",
                            item.lineno,
                            class_name=node.name,
                            class_fields=class_fields,
                        )
                    )
                elif (
                    is_enum
                    and isinstance(item, ast.Assign)
                    and item.targets
                    and isinstance(item.targets[0], ast.Name)
                ):
                    records.append(
                        IdentifierRecord(
                            item.targets[0].id,
                            "enum_member",
                            item.lineno,
                            class_name=node.name,
                            enum_members=enum_members,
                        )
                    )
                elif isinstance(item, ast.FunctionDef):
                    records.append(
                        IdentifierRecord(
                            item.name,
                            "function",
                            item.lineno,
                            class_name=node.name,
                            class_fields=class_fields,
                            function_parameters=frozenset(arg.arg for arg in item.args.args),
                        )
                    )
    return records


def find_d4_violations(path: str, source: str) -> list[Violation]:
    violations: list[Violation] = []
    for record in iter_identifier_records(path, source):
        city_keyed = "city" in record.class_fields or "city" in record.function_parameters
        if _D4A_RE.search(record.name) and not city_keyed:
            violations.append(
                Violation(path, record.lineno, "D4a", f"{record.name} is not city-keyed")
            )
        if not _D4B_RE.match(record.name):
            continue
        opposite = _opposite_polarity(record.name)
        has_opposite = opposite is not None and opposite in {
            member.upper() for member in record.enum_members
        }
        if record.kind == "enum_member" and has_opposite:
            continue
        violations.append(
            Violation(path, record.lineno, "D4b", f"{record.name} is one-sided")
        )
    return violations


def scan_d4() -> list[Violation]:
    return [
        violation
        for path, source in iter_python_sources(SRC_SCAN_ROOTS)
        for violation in find_d4_violations(path, source)
    ]


def test_d1_settlement_package_is_pure() -> None:
    violations = scan_settlement_purity()
    assert violations == [], "D1 violations:\n" + "\n".join(str(v) for v in violations)


def test_d1_detects_a_planted_pathlib_import() -> None:
    source = "from pathlib import Path\nVALUE = Path('.')\n"
    assert find_settlement_purity_violations("src/breezy/settlement/x.py", source)


def test_d1_detects_a_planted_open_call() -> None:
    source = "def f():\n    return open('x')\n"
    assert find_settlement_purity_violations("src/breezy/settlement/x.py", source)


def test_d2_gate_does_not_import_reporter() -> None:
    violations = scan_reporting_imports()
    assert violations == [], "D2 violations:\n" + "\n".join(str(v) for v in violations)


def test_d2_detects_a_planted_reporting_import_in_the_gate() -> None:
    source = "from breezy.settlement.reporting import Stratum\n"
    assert find_reporting_import_violations("src/breezy/settlement/coverage.py", source)


def test_d3_pinned_names_match_the_shipped_tree() -> None:
    violations = scan_determination_field_drift()
    assert violations == [], "D3 violations:\n" + "\n".join(str(v) for v in violations)


def test_d3_detects_a_planted_extra_field_of_any_type() -> None:
    source = """
from dataclasses import dataclass

@dataclass(frozen=True, slots=True, kw_only=True)
class CityDetermination:
    city: str
    determination: object
    tradeable: bool
    boundary_classification: object
    blocking_cells: tuple[str, ...]
    expiry_disposition: object
    escalation_required: bool
    reason: str
    wilson_lower: str
"""
    fields = extract_determination_fields("src/breezy/settlement/coverage.py", source)
    assert fields["CityDetermination"] != _PINNED_DETERMINATION_FIELDS["CityDetermination"]


def test_d4a_detects_a_programme_wide_conservatism_type() -> None:
    source = "class ProgrammeConservatismVerdict:\n    pass\n"
    assert find_d4_violations("src/breezy/x.py", source)


def test_d4a_allows_a_city_keyed_conservatism_finding() -> None:
    source = "class ConservatismFinding:\n    city: str\n"
    assert find_d4_violations("src/breezy/x.py", source) == []


def test_d4a_detects_a_conservatism_function_without_a_city_parameter() -> None:
    source = "def estimator_conservatism_holds() -> bool:\n    return True\n"
    assert find_d4_violations("src/breezy/x.py", source)


def test_d4a_allows_a_per_city_re_derivation_function() -> None:
    source = "def estimator_conservatism_holds(city: str) -> bool:\n    return True\n"
    assert find_d4_violations("src/breezy/x.py", source) == []


def test_d4b_detects_a_module_level_one_sided_direction_constant() -> None:
    source = "METAR_BELOW_CLI = 'METAR_BELOW_CLI'\n"
    assert find_d4_violations("src/breezy/x.py", source)


def test_d4b_detects_an_enum_offering_only_one_polarity() -> None:
    source = "import enum\nclass Direction(enum.Enum):\n    METAR_BELOW_CLI = 'x'\n"
    assert find_d4_violations("src/breezy/x.py", source)


def test_d4b_allows_signed_error_direction_which_offers_both() -> None:
    source = """
import enum
class SignedErrorDirection(enum.Enum):
    METAR_ABOVE_CLI = 'METAR_ABOVE_CLI'
    METAR_BELOW_CLI = 'METAR_BELOW_CLI'
"""
    assert find_d4_violations("src/breezy/x.py", source) == []


def test_d4_no_obvious_programme_wide_claims_in_src() -> None:
    violations = scan_d4()
    assert violations == [], "D4 violations:\n" + "\n".join(str(v) for v in violations)


def test_d4_does_not_fire_on_any_type_this_plan_requires() -> None:
    path = Path("src/breezy/settlement/reporting.py")
    if not path.exists():
        return
    violations = find_d4_violations(path.as_posix(), path.read_text(encoding="utf-8"))
    assert violations == [], "D4 violations:\n" + "\n".join(str(v) for v in violations)


def test_d1_scan_actually_covers_both_settlement_modules() -> None:
    paths = {path for path, _ in iter_python_sources(SETTLEMENT_SCAN_ROOTS)}
    assert "src/breezy/settlement/coverage.py" in paths
    assert "src/breezy/settlement/programme.py" in paths

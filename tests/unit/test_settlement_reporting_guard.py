"""Construction and renderer guards for settlement reports."""

from __future__ import annotations

import ast

from tests.unit.test_polymarket_us_readonly_guard import Violation, iter_python_sources

SCAN_ROOTS = ("src", "scripts")


def find_programme_headline_construction_violations(path: str, source: str) -> list[Violation]:
    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []
    builder_stack: list[bool] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            builder_stack.append(node.name == "build_programme_report")
            self.generic_visit(node)
            builder_stack.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            for base in node.bases:
                name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                if name == "ProgrammeHeadline":
                    violations.append(
                        Violation(path, node.lineno, "R1", "ProgrammeHeadline subclass")
                    )
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else getattr(node.func, "attr", "")
            )
            if name == "ProgrammeHeadline" and not any(builder_stack):
                violations.append(
                    Violation(path, node.lineno, "R1", "direct ProgrammeHeadline construction")
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    return violations


def scan_r1() -> list[Violation]:
    return [
        violation
        for path, source in iter_python_sources(SCAN_ROOTS)
        for violation in find_programme_headline_construction_violations(path, source)
    ]


def renderer_revalidates_headline(source: str) -> bool:
    tree = ast.parse(source, filename="src/breezy/settlement/reporting.py")
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "render_markdown":
            continue
        return any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "_assert_headline_invariants"
            for child in ast.walk(node)
        )
    return False


def test_r1_no_unsanctioned_programme_headline_construction() -> None:
    violations = scan_r1()
    assert violations == [], "R1 violations:\n" + "\n".join(str(v) for v in violations)


def test_r1_detects_a_planted_direct_construction() -> None:
    source = "def f():\n    return ProgrammeHeadline(reason='x')\n"
    assert find_programme_headline_construction_violations("src/x.py", source)


def test_r1_detects_a_planted_subclass() -> None:
    source = "class Bad(ProgrammeHeadline):\n    pass\n"
    assert find_programme_headline_construction_violations("src/x.py", source)


def test_r1_allows_the_sanctioned_builder() -> None:
    source = "def build_programme_report():\n    return ProgrammeHeadline(reason='x')\n"
    assert find_programme_headline_construction_violations("src/x.py", source) == []


def test_r2_render_markdown_revalidates_the_headline() -> None:
    for path, source in iter_python_sources(("src/breezy/settlement",)):
        if path == "src/breezy/settlement/reporting.py":
            assert renderer_revalidates_headline(source)
            return
    raise AssertionError("reporting.py not found")


def test_r2_detects_a_renderer_without_revalidation() -> None:
    source = "def render_markdown(report):\n    return 'body'\n"
    assert renderer_revalidates_headline(source) is False

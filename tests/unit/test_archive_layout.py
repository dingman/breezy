"""Path-policy pins for the durable IEM archive cache roots."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "archive" / "backup_irreplaceable_data.py"
LAYOUT_MODULE = REPO_ROOT / "src" / "breezy" / "persistence" / "archive_layout.py"


def _ann_assign_value(tree: ast.AST, name: str) -> ast.expr:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return node.value
    raise AssertionError(f"{name} assignment not found")


def _eval_path_expr(node: ast.expr) -> Path:
    expr = ast.Expression(body=node)
    ast.fix_missing_locations(expr)
    value = eval(compile(expr, "<path-expr>", "eval"), {"Path": Path})
    assert isinstance(value, Path)
    return value


def test_the_backup_scripts_default_archive_dir_expression_matches_the_src_constant() -> None:
    from breezy.persistence.archive_layout import BACKED_UP_ARCHIVE_DATASET_DIR

    script_tree = ast.parse(BACKUP_SCRIPT.read_text(encoding="utf-8"), filename=str(BACKUP_SCRIPT))
    src_tree = ast.parse(LAYOUT_MODULE.read_text(encoding="utf-8"), filename=str(LAYOUT_MODULE))

    script_expr = _ann_assign_value(script_tree, "DEFAULT_ARCHIVE_DIR")
    src_expr = _ann_assign_value(src_tree, "BACKED_UP_ARCHIVE_DATASET_DIR")

    assert ast.unparse(script_expr) == ast.unparse(src_expr)
    assert _eval_path_expr(script_expr) == BACKED_UP_ARCHIVE_DATASET_DIR
    assert _eval_path_expr(src_expr) == BACKED_UP_ARCHIVE_DATASET_DIR


def test_no_tilde_literal_and_the_default_roots_are_absolute() -> None:
    from breezy.persistence.archive_layout import (
        BACKED_UP_ARCHIVE_DATASET_DIR,
        DEFAULT_IEM_CACHE_DIR,
    )

    tree = ast.parse(LAYOUT_MODULE.read_text(encoding="utf-8"), filename=str(LAYOUT_MODULE))
    string_constants = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]

    assert not any("~" in value for value in string_constants)
    assert BACKED_UP_ARCHIVE_DATASET_DIR.is_absolute()
    assert DEFAULT_IEM_CACHE_DIR.is_absolute()
    assert BACKED_UP_ARCHIVE_DATASET_DIR != DEFAULT_IEM_CACHE_DIR

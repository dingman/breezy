"""S4 WP5 (ARM maker-sharp B6): the static scan that keeps a raw (possibly negative)
maker commission out of every consumer.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md``
section 0 ("scripts/ readers"), section 2 WP5 (the allowlist is a PRECONDITION of merging
the poll booking) and section 4 ("Static scan").

The raw venue commission lives ONLY in ``DurableFillRecord.venue_fee_raw`` (exact string)
and the readers listed below. The RECOGNISED value (``recognised_commission``) is what
feeds ``cumulative_fee`` and the native ``OrderFilled.commission``, so every consumer sees
a value that cannot be an unverified rebate. Two directions are pinned, both over ``src/``
AND ``scripts/``:

* (a) every reference to a raw-commission name is in an allowlist with ONE disposition per
  ``(file, enclosing scope)``; a new reader fails the scan;
* (b) no consumer file outside the ``exec`` package (the one writer) that reads a commission
  VALUE (``.cumulative_fee``, ``.commission``, ``realized_pnl``) references a raw-commission
  name at all.

Pure AST; no ``exec`` import (barrier X1 pins by set equality the test modules that import
the ``exec`` package, and this module is not one of them).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCAN_ROOTS: Final[tuple[str, ...]] = ("src", "scripts")

#: Names whose appearance means "reads the RAW venue commission".
RAW_COMMISSION_NAMES: Final[frozenset[str]] = frozenset(
    {
        "venue_fee_raw",
        "venueFeeRaw",
        "commission_raw",
        "commissionNotionalTotalCollected",
        "resting_commission_total",
    }
)
#: Attributes that read a commission VALUE a consumer prices from.
VALUE_READ_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"cumulative_fee", "commission", "realized_pnl"}
)

_EXEC: Final[str] = "src/breezy/adapters/polymarket_us/exec"
_CLIENT: Final[str] = f"{_EXEC}/client.py"
_DUR: Final[str] = "DurableFillRecord"
_CLI: Final[str] = "PolymarketUSExecutionClient"

#: (file, enclosing scope) -> the ONE disposition of that raw read. Adding a row is a
#: reviewed edit of this file; the scope is the qualified def/class chain (``""`` = module).
RAW_COMMISSION_READ_ALLOWLIST: Final[dict[tuple[str, str], str]] = {
    ("scripts/venue/polymarket_us_shape_capture.py", ""): "key NAME in a shape-capture list",
    (_CLIENT, _DUR): "the record's own field",
    (_CLIENT, f"{_DUR}.to_bytes"): "the record's own serialisation",
    (_CLIENT, f"{_DUR}.from_bytes"): "the record's own decoding",
    (_CLIENT, f"{_CLI}._reconciled_commission"): "O4 fee-source derivation (the string's presence)",
    (_CLIENT, f"{_CLI}._resolve_accept_fill"): "writes None: the resolver never books a raw fee",
    (_CLIENT, f"{_CLI}._submit_order"): "create-path writer (taker audit string)",
    (_CLIENT, f"{_CLI}.record_fill"): "O4 fee-source stamp (the string's presence)",
    (_CLIENT, "fee_source_for"): "O4 fee-source derivation (the string's presence)",
    (f"{_EXEC}/reports.py", ""): "key NAME in the wire-order key list",
    (f"{_EXEC}/reports.py", "resting_commission_total"): "the single signed raw reader (poll)",
    (f"{_EXEC}/submit_chain.py", "FillGeneration"): "the create-path generation's raw field",
    (f"{_EXEC}/submit_chain.py", "_commission_raw_audit"): "create-path audit string",
    (f"{_EXEC}/submit_chain.py", "_order_total_commission"): "create-path total (taker)",
    (f"{_EXEC}/submit_chain.py", "fill_generation"): "create-path generation",
}

#: The scripts that read a RECORDED ``.cumulative_fee`` (the recognised value, as-is), r4
#: section 0 ("scripts/ readers"). Any other scripts file reading it fails the scan.
SCRIPTS_CUMULATIVE_FEE_READERS: Final[frozenset[str]] = frozenset(
    {
        "scripts/analysis/portfolio_roi_report.py",
        "scripts/analysis/fq_loss_taxonomy_truth.py",
    }
)


def _python_files(root: str) -> list[Path]:
    return sorted(
        p
        for p in (REPO_ROOT / root).rglob("*.py")
        if "__pycache__" not in p.parts and ".venv" not in p.parts
    )


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _hit(node: ast.AST, names: frozenset[str]) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in names:
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return node.id
    if isinstance(node, ast.keyword) and node.arg in names:
        return node.arg
    if isinstance(node, ast.arg) and node.arg in names:
        return node.arg
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in names:
        return node.name
    return None


def _walk(
    node: ast.AST, scope: tuple[str, ...], names: frozenset[str], out: set[tuple[str, str]]
) -> None:
    for child in ast.iter_child_nodes(node):
        inner = scope
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            inner = (*scope, child.name)
        if _hit(child, names) is not None:
            out.add((".".join(inner), _hit(child, names) or ""))
        _walk(child, inner, names, out)


def _references(source: str, names: frozenset[str]) -> set[tuple[str, str]]:
    """``(enclosing scope, name)`` for every reference to a name in ``names``."""
    found: set[tuple[str, str]] = set()
    _walk(ast.parse(source), (), names, found)
    return found


def _scan(names: frozenset[str]) -> dict[str, set[tuple[str, str]]]:
    result: dict[str, set[tuple[str, str]]] = {}
    for root in SCAN_ROOTS:
        for path in _python_files(root):
            hits = _references(path.read_text(encoding="utf-8"), names)
            if hits:
                result[_rel(path)] = hits
    return result


def test_budget_and_cap_readers_use_recognised_commission_static_scan() -> None:
    """(a) the raw-commission reads are exactly the allowlist (src AND scripts), and
    (b) no consumer (outside the exec writer package) that reads a commission VALUE also
    references a raw-commission name."""
    raw = _scan(RAW_COMMISSION_NAMES)
    seen = {(path, scope) for path, hits in raw.items() for scope, _name in hits}
    assert seen == set(RAW_COMMISSION_READ_ALLOWLIST), (
        sorted(seen - set(RAW_COMMISSION_READ_ALLOWLIST)),
        sorted(set(RAW_COMMISSION_READ_ALLOWLIST) - seen),
    )
    consumers = {path for path in _scan(VALUE_READ_ATTRIBUTES) if not path.startswith(f"{_EXEC}/")}
    crossing = consumers & set(raw)
    assert crossing == set(), f"a commission VALUE reader also reads the raw string: {crossing}"


def test_scripts_fee_readers_match_the_enumerated_allowlist() -> None:
    """The precondition to merging the poll booking: the ``scripts/`` readers of the
    recorded fee are exactly the two enumerated ones; no scripts file reads ``.commission``,
    ``venue_fee_raw`` or ``commission_raw``."""
    cumulative = {
        path
        for path, hits in _scan(frozenset({"cumulative_fee"})).items()
        if path.startswith("scripts/") and hits
    }
    assert cumulative == SCRIPTS_CUMULATIVE_FEE_READERS
    commission = {path for path in _scan(frozenset({"commission"})) if path.startswith("scripts/")}
    assert commission == set()
    raw_in_scripts = {
        path
        for path, hits in _scan(
            frozenset({"venue_fee_raw", "commission_raw", "venueFeeRaw"})
        ).items()
        if path.startswith("scripts/") and hits
    }
    assert raw_in_scripts == set()


def test_the_static_scan_sees_a_planted_raw_reader() -> None:
    """Non-vacuity: a raw read planted into a value reader's source is found by the same
    machinery, in a scope the allowlist does not name."""
    planted = "def price(rec):\n    return rec.cumulative_fee + rec.venue_fee_raw\n"
    assert _references(planted, RAW_COMMISSION_NAMES) == {("price", "venue_fee_raw")}
    assert _references(planted, VALUE_READ_ATTRIBUTES) == {("price", "cumulative_fee")}
    clean = "def price(rec):\n    return rec.cumulative_fee\n"
    assert _references(clean, RAW_COMMISSION_NAMES) == set()
